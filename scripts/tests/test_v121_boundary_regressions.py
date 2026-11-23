"""v1.2.1 paid-launch, post-apply, lane-recovery and approval regressions.

These regressions target the boundaries reported in fix-b01-r03: exact paid
authority from preflight through child launch, an exact after-apply checkpoint,
lane-only uncertainty through the public operator entry points, and the effective
single-writer decision at plan approval.  Model prose is never authority; the
durable ledger, real route preflight, real Git apply and process identities are.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

import test_orchestrator as baseline
import test_v121_parallel_writers as pw

orc = baseline.orc


def report(summary="complete"):
    return {"contract_version": 2, "status": "complete", "summary": summary,
            "files": [], "tests": [], "evidence": [summary], "unknowns": [],
            "blocker": ""}


def blocked(summary="blocked"):
    return {"contract_version": 2, "status": "blocked", "summary": summary,
            "files": [], "tests": [], "evidence": [summary], "unknowns": [],
            "blocker": summary}


def paid_batch():
    return {"title": "paid", "goal": "change app", "acceptance": ["works"],
            "checks": [[sys.executable, "-c", "raise SystemExit(0)"]],
            "risk": "ordinary", "verification_purpose": None,
            "repeat_checks": None}


class BoundaryBase(unittest.TestCase):
    setUp = baseline.ControlTests.setUp
    tearDown = baseline.ControlTests.tearDown

    def plan(self, writers, checks=True):
        batch = paid_batch()
        batch["writers"] = writers
        if not checks:
            batch["checks"] = []
        return {"contract_version": 2, "status": "complete", "summary": "plan",
                "invariants": ["Keep behavior"], "batches": [batch],
                "blocker": "", "required_exploration": {
                    "job_id": "", "scope_satisfied": True}}

    def install_plan(self, plan, *, max_writers=3, status="running"):
        self.state.update({
            "status": status, "phase": "implement", "plan": plan,
            "plan_version": orc.content_hash(plan), "plan_revision": 1,
            "batch_index": 0, "corrections": 0, "correction": "",
            "parallel_permission": {"max_writers": max_writers,
                                    "enabled": max_writers > 1},
            "completed_jobs": [], "failed_jobs": [], "batch_deltas": []})
        orc.save(self.rundir, self.state)

    def paid_state(self, dispatches, *, max_writers=3, writers=None):
        plan = self.plan(writers or [pw.writer("a", path="a.py"),
                                     pw.writer("b", path="b.py")])
        route = {"provider": "codex", "model": "fixture-strong", "effort": "low",
                 "billing": "api"}
        grant = {"id": "paid-grant", "role": "implementer", "run_id": "test-run00",
                 "route_sha256": orc.route_authorization_sha(route),
                 "role_generation": 0, "used": 0,
                 "max_dispatches": dispatches}
        self.install_plan(plan, max_writers=max_writers)
        self.state["model_routes"] = {"implementer": route}
        self.state["route_authorizations"] = [grant]
        orc.save(self.rundir, self.state)
        return plan, route


class PaidLaunchBoundaryTests(BoundaryBase):
    """Exact reservations survive real preflight, call_model and the ledger."""

    def transport(self, spawns):
        def fake_guarded(command, cwd, env, log_stream, launch_file=None,
                         stdin_data=None, error_stream=None, stdin_fifo=None):
            writer = Path(cwd).parent.name
            (Path(cwd) / f"{writer}.py").write_text(f"{writer} = 1\n")
            out = command[command.index("--output-last-message") + 1]
            Path(out).write_text(json.dumps(report(f"{writer} finished")))
            proc = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(0.4)"],
                start_new_session=True)
            if launch_file:
                orc.atomic_json(Path(launch_file),
                                {"guard": orc.process_identity(proc.pid)})
            spawns.append(writer)
            return proc, None
        return fake_guarded

    def run_paid(self, dispatches, writers, max_writers=3):
        plan, route = self.paid_state(
            dispatches, max_writers=max_writers, writers=writers)
        batch = plan["batches"][0]
        resolved = orc.resolve_parallel_batch(
            self.state, self.project, batch, run_dir=self.rundir)
        self.assertEqual(resolved["mode"], "parallel")
        spawns = []
        with patch.object(orc, "_spawn_guarded",
                          side_effect=self.transport(spawns)):
            result = orc.run_parallel_batch(
                self.rundir, self.state, self.cfg, self.project, batch,
                resolved, None)
        return result, spawns, route

    def test_two_exactly_funded_lanes_launch_and_charge_once(self):
        result, spawns, route = self.run_paid(
            2, [pw.writer("a", path="a.py"), pw.writer("b", path="b.py")])
        self.assertIsNotNone(result, self.state.get("pause_reason"))
        self.assertEqual(sorted(spawns), ["a", "b"])
        self.assertEqual(len(spawns), 2, "a lane was launched more than once")
        ledger = orc.load_grant_ledger(self.rundir, run_id=self.state["id"])
        grant = ledger["grants"]["paid-grant"]
        self.assertEqual(orc._grant_usage(grant), 2)
        self.assertEqual([item.get("state") for item in grant["reservations"]],
                         ["launched", "launched"])
        self.assertEqual(orc._grant_usage(grant), 2,
                         "a launched reservation was silently refunded")
        self.assertEqual(self.state["parallel_integration"]["phase"], "complete")
        self.assertEqual((self.project / "a.py").read_text(), "a = 1\n")
        self.assertEqual((self.project / "b.py").read_text(), "b = 1\n")
        # Every lane reused exactly the group reservation assigned to it.
        self.assertEqual(
            {lane["grant_reservation_id"] for lane in
             self.state["parallel_writers"]["lanes"].values()},
            set(item["id"] for item in grant["reservations"]))

    def test_three_exactly_funded_lanes_launch_and_charge_once(self):
        result, spawns, route = self.run_paid(
            3, [pw.writer("a", path="a.py"), pw.writer("b", path="b.py"),
                pw.writer("c", path="c.py")])
        self.assertIsNotNone(result, self.state.get("pause_reason"))
        self.assertEqual(sorted(spawns), ["a", "b", "c"])
        ledger = orc.load_grant_ledger(self.rundir, run_id=self.state["id"])
        self.assertEqual(orc._grant_usage(ledger["grants"]["paid-grant"]), 3)
        for name in ("a.py", "b.py", "c.py"):
            self.assertEqual((self.project / name).read_text(),
                             f"{name[0]} = 1\n")

    def test_insufficient_grant_launches_nothing_and_refunds_nothing(self):
        plan, route = self.paid_state(
            1, writers=[pw.writer("a", path="a.py"),
                        pw.writer("b", path="b.py")])
        batch = plan["batches"][0]
        resolved = orc.resolve_parallel_batch(
            self.state, self.project, batch, run_dir=self.rundir)
        spawns = []

        def must_not_run(*args, **kwargs):
            spawns.append("model")
            raise AssertionError("a paid lane launched without a slot")

        with patch.object(orc, "_spawn_guarded", side_effect=self.transport(spawns)), \
                patch.object(orc, "call_model", side_effect=must_not_run):
            result = orc.run_parallel_batch(
                self.rundir, self.state, self.cfg, self.project, batch,
                resolved, None)
        self.assertIsNone(result)
        self.assertEqual(spawns, [])
        ledger = orc.load_grant_ledger(self.rundir, run_id=self.state["id"])
        self.assertEqual(orc._grant_usage(ledger["grants"]["paid-grant"]), 0)
        self.assertEqual(self.state["status"], "blocked")

    def test_wrong_scope_and_released_reservations_are_denied(self):
        plan, route = self.paid_state(
            3, writers=[pw.writer("a", path="a.py"),
                        pw.writer("b", path="b.py")])
        ids, problem = orc._reserve_parallel_authority(
            self.state, self.rundir, 2, self.cfg, None, 0,
            targets=[{"writer_id": "a", "attempt_id": "attempt-a"},
                     {"writer_id": "b", "attempt_id": "attempt-b"}])
        self.assertIsNone(problem)
        spawns = []
        lane_state = copy.deepcopy(self.state)
        with patch.object(orc, "_spawn_guarded",
                          side_effect=self.transport(spawns)):
            # A different lane's held slot cannot admit this attempt and is not
            # refunded by the refusal.
            with self.assertRaisesRegex(RuntimeError, "preflight"):
                orc.call_model(
                    self.rundir, lane_state, self.cfg, "implementer",
                    "implementer", "do work", self.project, route=route,
                    assignment="a", grant_reservation_id=ids[1],
                    grant_attempt_id="attempt-b")
            ledger = orc.load_grant_ledger(
                self.rundir, run_id=self.state["id"])
            grant = ledger["grants"]["paid-grant"]
            self.assertEqual(orc._grant_usage(grant), 2,
                             "a mismatched refusal refunded another lane's slot")
            self.assertEqual(grant["releases"], [])
            # Releasing the exact held slot is allowed; a later launch is denied.
            orc.release_route_grant(
                self.state, self.rundir, "implementer", route,
                "unit test release", reservation_id=ids[1], cfg=self.cfg)
            with self.assertRaisesRegex(RuntimeError, "preflight"):
                orc.call_model(
                    self.rundir, lane_state, self.cfg, "implementer",
                    "implementer", "do work", self.project, route=route,
                    assignment="b", grant_reservation_id=ids[1],
                    grant_attempt_id="attempt-b")
            with self.assertRaisesRegex(RuntimeError, "preflight"):
                orc.call_model(
                    self.rundir, lane_state, self.cfg, "implementer",
                    "implementer", "do work", self.project, route=route,
                    assignment="a", grant_reservation_id=ids[1],
                    grant_attempt_id="attempt-a")
        self.assertEqual(spawns, [])
        ledger = orc.load_grant_ledger(self.rundir, run_id=self.state["id"])
        grant = ledger["grants"]["paid-grant"]
        self.assertEqual(orc._grant_usage(grant), 1,
                         "an unrelated held grant was changed")
        self.assertEqual(sorted(item["id"] for item in grant["releases"]),
                         [ids[1]])

    def test_preflight_rejection_after_reservation_launches_nothing(self):
        plan, route = self.paid_state(
            2, writers=[pw.writer("a", path="a.py"),
                        pw.writer("b", path="b.py")])
        ids, problem = orc._reserve_parallel_authority(
            self.state, self.rundir, 1, self.cfg, None, 0,
            targets=[{"writer_id": "a", "attempt_id": "attempt-a"}])
        self.assertIsNone(problem)
        other = dict(route, model="different-strong-route")
        spawns = []
        lane_state = copy.deepcopy(self.state)
        with patch.object(orc, "_spawn_guarded",
                          side_effect=self.transport(spawns)):
            with self.assertRaisesRegex(RuntimeError, "preflight"):
                orc.call_model(
                    self.rundir, lane_state, self.cfg, "implementer",
                    "implementer", "do work", self.project, route=other,
                    assignment="a", grant_reservation_id=ids[0],
                    grant_attempt_id="attempt-a")
        self.assertEqual(spawns, [])
        ledger = orc.load_grant_ledger(self.rundir, run_id=self.state["id"])
        self.assertEqual(orc._grant_usage(ledger["grants"]["paid-grant"]), 1,
                         "an unrelated route's held grant was released")
        self.assertFalse((self.project / "a.py").exists())

    def test_parent_loss_after_reservation_reuses_the_same_slots(self):
        plan, route = self.paid_state(
            2, writers=[pw.writer("a", path="a.py"),
                        pw.writer("b", path="b.py")])
        ids, problem = orc._reserve_parallel_authority(
            self.state, self.rundir, 2, self.cfg, None, 0,
            targets=[{"writer_id": "a", "attempt_id": "attempt-a"},
                     {"writer_id": "b", "attempt_id": "attempt-b"}])
        self.assertIsNone(problem)
        # Simulate parent loss between the group reservation and any launch.
        self.state = orc.load(self.state["id"])[1]
        batch = self.state["plan"]["batches"][0]
        resolved = orc.resolve_parallel_batch(
            self.state, self.project, batch, run_dir=self.rundir)
        self.assertEqual(resolved["mode"], "parallel")
        spawns = []
        with patch.object(orc, "_spawn_guarded",
                          side_effect=self.transport(spawns)):
            result = orc.run_parallel_batch(
                self.rundir, self.state, self.cfg, self.project, batch,
                resolved, None)
        self.assertIsNotNone(result, self.state.get("pause_reason"))
        self.assertEqual(sorted(spawns), ["a", "b"])
        ledger = orc.load_grant_ledger(self.rundir, run_id=self.state["id"])
        grant = ledger["grants"]["paid-grant"]
        self.assertEqual(orc._grant_usage(grant), 2,
                         "recovery consumed a second slot per lane")
        self.assertEqual(sorted(item["id"] for item in grant["reservations"]),
                         sorted(ids))


class PostApplyRecoveryTests(BoundaryBase):
    """Exact before/after/divergent recovery at the durable apply boundary."""

    def prepare_writers(self, writers, max_writers=3):
        plan = self.plan(writers)
        self.install_plan(plan, max_writers=max_writers)
        batch = self.state["plan"]["batches"][0]
        resolved = orc.resolve_parallel_batch(
            self.state, self.project, batch, run_dir=self.rundir)
        return batch, resolved

    def crash_on_manifest(self, predicate):
        real = orc.atomic_json
        target = orc._integration_record_path(self.rundir, 0)

        def patched(path, value, *args, **kwargs):
            if Path(path) == target and predicate(value):
                raise RuntimeError("simulated process loss at manifest write")
            return real(path, value, *args, **kwargs)
        return patch.object(orc, "atomic_json", side_effect=patched)

    def count_canonical_applies(self):
        real = orc._apply_writer_patch
        count = {"n": 0}

        def counting(worktree, patch_path, **kwargs):
            if (Path(worktree).resolve() == self.project.resolve()
                    and not kwargs.get("check_only")):
                count["n"] += 1
            return real(worktree, patch_path, **kwargs)
        return count, patch.object(orc, "_apply_writer_patch", side_effect=counting)

    def test_final_manifest_loss_after_full_apply_advances_without_replay(self):
        batch, resolved = self.prepare_writers(
            [pw.writer("a", path="a.py"), pw.writer("b", path="b.py")])
        fake = pw.ParallelWriterTests.fake_model(
            self, {"a": {"a.py": "a = 1\n"}, "b": {"b.py": "b = 2\n"}})
        with patch.object(orc, "call_model", side_effect=fake):
            with self.crash_on_manifest(
                    lambda value: value.get("phase") == "complete"):
                first = orc.run_parallel_batch(
                    self.rundir, self.state, self.cfg, self.project, batch,
                    resolved, None)
        self.assertIsNone(first)
        self.assertEqual((self.project / "a.py").read_text(), "a = 1\n")
        self.assertEqual((self.project / "b.py").read_text(), "b = 2\n")
        record_path = orc._integration_record_path(self.rundir, 0)
        record = orc.read_json(record_path)
        self.assertEqual(record["phase"], "applying")
        self.assertEqual(sorted(record["applied"]), ["a", "b"])
        self.assertEqual(orc._checkout_content_sha(self.project),
                         record["after_sha"])
        self.state = orc.load(self.state["id"])[1]
        self.state["status"] = "running"
        orc.atomic_json(self.rundir / "control.json", {"action": "run"})
        orc.save(self.rundir, self.state)
        launches = []
        count, apply_patch = self.count_canonical_applies()

        def must_not_run(*args, **kwargs):
            launches.append("model")
            raise AssertionError("a writer launched after the exact apply")

        with patch.object(orc, "call_model", side_effect=must_not_run), apply_patch:
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(launches, [])
        self.assertEqual(count["n"], 0, "the completed apply was replayed")
        self.assertEqual(self.state["phase"], "verify",
                         self.state.get("pause_reason"))
        self.assertEqual(self.state["parallel_integration"]["phase"], "complete")
        self.assertEqual((self.project / "a.py").read_text(), "a = 1\n")
        self.assertEqual((self.project / "b.py").read_text(), "b = 2\n")
        self.assertEqual(sorted(self.state["parallel_integration"]["applied"]),
                         ["a", "b"])
        self.assertEqual(orc.read_json(record_path)["phase"], "complete")
        integration_delta = [item for item in self.state.get("batch_deltas", [])
                             if item.get("job_id") == "parallel-integration-0"]
        self.assertEqual(len(integration_delta), 1,
                         "full integration attribution was not recorded")
        self.assertEqual({item["path"] for item in integration_delta[0]["paths"]},
                         {"a.py", "b.py"})

    def test_prepared_record_continues_the_exact_apply_without_a_writer(self):
        batch, resolved = self.prepare_writers(
            [pw.writer("a", path="a.py"), pw.writer("b", path="b.py")])
        fake = pw.ParallelWriterTests.fake_model(
            self, {"a": {"a.py": "a = 1\n"}, "b": {"b.py": "b = 2\n"}})
        with patch.object(orc, "call_model", side_effect=fake):
            result = orc.run_parallel_batch(
                self.rundir, self.state, self.cfg, self.project, batch,
                resolved, None)
        self.assertIsNotNone(result)
        record_path = orc._integration_record_path(self.rundir, 0)
        record = orc.read_json(record_path)
        base_head = record["base_head"]
        # Roll the canonical checkout back to the recorded before identity and
        # preserve only the prepared manifest: a parent loss after the dry-run
        # identity was recorded but before the first apply.
        orc.git(self.project, ["reset", "--hard", base_head])
        orc.git(self.project, ["clean", "-fd"])
        record.update({"phase": "prepared", "applied": [], "completed_at": None})
        orc.atomic_json(record_path, record)
        self.state = orc.load(self.state["id"])[1]
        self.state.update({"phase": "implement", "implementation": None,
                           "parallel_integration": None, "status": "running"})
        orc.atomic_json(self.rundir / "control.json", {"action": "run"})
        orc.save(self.rundir, self.state)
        launches = []
        count, apply_patch = self.count_canonical_applies()

        def must_not_run(*args, **kwargs):
            launches.append("model")
            raise AssertionError("a writer launched to continue the recorded apply")

        with patch.object(orc, "call_model", side_effect=must_not_run), apply_patch:
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(launches, [])
        self.assertEqual(count["n"], 2, "the recorded apply was not completed once")
        self.assertEqual(self.state["phase"], "verify",
                         self.state.get("pause_reason"))
        self.assertEqual((self.project / "a.py").read_text(), "a = 1\n")
        self.assertEqual((self.project / "b.py").read_text(), "b = 2\n")

    def test_divergent_identity_blocks_even_with_pending_fallbacks(self):
        batch, resolved = self.prepare_writers(
            [pw.writer("a", path="a.py"), pw.writer("b", path="b.py")])
        fake = pw.ParallelWriterTests.fake_model(
            self, {"a": {"a.py": "a = 1\n"}, "b": {"b.py": "b = 2\n"}})
        with patch.object(orc, "call_model", side_effect=fake):
            with self.crash_on_manifest(
                    lambda value: value.get("phase") == "complete"):
                orc.run_parallel_batch(
                    self.rundir, self.state, self.cfg, self.project, batch,
                    resolved, None)
        spec = self.cfg["fallback"]["codex"]
        self.state = orc.load(self.state["id"])[1]
        self.state.update({
            "status": "running",
            "correction": "",
            "parallel_fallback_batches": {"0": {
                "at": orc.now(), "incomplete": ["b"], "reason": "pending fallback"}},
            "worker_fallback_authorization": {
                "role": "implementer", "approved_at": orc.now(),
                "route_sha256": orc.route_authorization_sha(
                    {"provider": "codex", "model": spec["model"],
                     "effort": spec.get("effort"), "billing": "subscription"}),
                "role_generation": 0,
                "route": {"provider": "codex", "model": spec["model"],
                          "effort": spec.get("effort"),
                          "billing": "subscription"}}})
        orc.atomic_json(self.rundir / "control.json", {"action": "run"})
        orc.save(self.rundir, self.state)
        # An unrecorded edit makes the canonical identity divergent.
        (self.project / "app.py").write_text("value = 99\n")
        launches = []
        count, apply_patch = self.count_canonical_applies()

        def must_not_run(*args, **kwargs):
            launches.append("model")
            raise AssertionError("a fallback bypassed divergent recovery")

        with patch.object(orc, "call_model", side_effect=must_not_run), apply_patch:
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(launches, [])
        self.assertEqual(count["n"], 0)
        self.assertEqual(self.state["status"], "blocked")
        self.assertIn("no longer matches", self.state["pause_reason"])
        self.assertEqual((self.project / "app.py").read_text(), "value = 99\n")
        self.assertTrue(orc._integration_record_path(self.rundir, 0).is_file())

    def test_sibling_divergence_blocks_instead_of_dispatching_a_writer(self):
        batch, resolved = self.prepare_writers(
            [pw.writer("a", path="a.py"), pw.writer("b", path="b.py"),
             pw.writer("c", path="c.py")])
        fake = pw.ParallelWriterTests.fake_model(
            self, {"a": {"a.py": "a = 1\n"}, "b": {"b.py": "b = 2\n"}},
            fail={"c"})

        def crash_after_first_sibling(value):
            return (value.get("mode") == "sibling_recovery"
                    and value.get("phase") == "applying"
                    and list(value.get("applied") or []) == ["a"])

        with patch.object(orc, "call_model", side_effect=fake):
            with self.crash_on_manifest(crash_after_first_sibling):
                orc.run_parallel_batch(
                    self.rundir, self.state, self.cfg, self.project, batch,
                    resolved, None)
        record_path = orc._integration_record_path(self.rundir, 0)
        record = orc.read_json(record_path)
        self.assertEqual(record["mode"], "sibling_recovery")
        self.assertEqual(record["phase"], "prepared")
        self.assertEqual(record["applied"], [])
        identity = orc._checkout_content_sha(self.project)
        self.assertNotIn(identity, {record["before_sha"], record["after_sha"]})
        self.state = orc.load(self.state["id"])[1]
        self.state["status"] = "running"
        orc.atomic_json(self.rundir / "control.json", {"action": "run"})
        orc.save(self.rundir, self.state)
        launches = []
        count, apply_patch = self.count_canonical_applies()

        def must_not_run(*args, **kwargs):
            launches.append("model")
            raise AssertionError("a single writer ran over the intermediate tree")

        with patch.object(orc, "call_model", side_effect=must_not_run), apply_patch:
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(launches, [])
        self.assertEqual(count["n"], 0)
        self.assertEqual(self.state["status"], "blocked")
        self.assertIn("intermediate", self.state["pause_reason"])
        self.assertEqual((self.project / "a.py").read_text(), "a = 1\n")
        self.assertFalse((self.project / "c.py").exists())
        self.assertEqual(orc.read_json(record_path)["applied"], [])
        self.assertEqual(orc.read_json(record_path)["phase"], "prepared")


class LaneOnlyReconcileTests(BoundaryBase):
    """Lane-only uncertainty is resolvable through public reconcile/resume."""

    def test_lane_only_uncertainty_reconciles_and_finishes_lifecycle(self):
        batch, resolved = PostApplyRecoveryTests.prepare_writers(
            self, [pw.writer("a", path="a.py"), pw.writer("b", path="b.py")])
        sleeper = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(120)"],
            start_new_session=True)
        self.addCleanup(lambda: sleeper.kill() if sleeper.poll() is None else None)
        identity = orc.process_identity(sleeper.pid) or {"pid": sleeper.pid}
        starts = []

        def fake(run_dir, state, cfg, role, kind, prompt, project, **kwargs):
            writer = kwargs.get("assignment")
            starts.append(writer)
            if writer == "a":
                (Path(project) / "a.py").write_text("a = 1\n")
                return report("a finished"), pw.writer_job(run_dir, "a")
            state["active_job"] = {
                "id": "old-lane-job", "role": "implementer",
                "kind": "implementer", "status": "dispatched", **identity}
            state["permission_blocked"] = {
                "version": 1, "role": "implementer", "assignment": "b",
                "action": "credential required", "reason": "provider prompt",
                "cause": "recognized", "resume_step": "correct and resume",
                "raw_text_persisted": False}
            orc.save(run_dir, state)
            raise RuntimeError("lane b lost its parent while running")

        before = orc._checkout_content_sha(self.project)
        with patch.object(orc, "call_model", side_effect=fake):
            result = orc.run_parallel_batch(
                self.rundir, self.state, self.cfg, self.project, batch,
                resolved, None)
        self.assertIsNone(result)
        self.assertEqual(self.state["status"], "uncertain")
        lane_b = self.state["parallel_writers"]["lanes"]["b"]
        self.assertEqual(lane_b["status"], "uncertain")
        self.assertTrue(lane_b.get("active_job"))
        self.assertIsNone(self.state.get("active_job"))
        self.assertIsNone(self.state.get("active_check"))
        self.assertEqual(orc._checkout_content_sha(self.project), before)
        launches = []
        applies = {"n": 0}
        real_apply = orc._apply_writer_patch

        def counting(*args, **kwargs):
            applies["n"] += 1
            return real_apply(*args, **kwargs)

        def must_not_run(*args, **kwargs):
            launches.append("model")
            raise AssertionError("a writer ran while lane execution was live")

        with patch.object(orc, "call_model", side_effect=must_not_run), \
                patch.object(orc, "_apply_writer_patch", side_effect=counting):
            with self.assertRaisesRegex(RuntimeError, "not proven stopped"):
                orc.reconcile_run(self.state["id"])
            with self.assertRaises(RuntimeError):
                orc.resume_run(self.state["id"])
        self.assertEqual(launches, [])
        self.assertEqual(applies["n"], 0)
        self.assertEqual(orc._checkout_content_sha(self.project), before)
        self.assertEqual(self.state["status"], "uncertain")
        sleeper.terminate()
        sleeper.wait(timeout=10)
        reconciled = orc.reconcile_run(self.state["id"])
        self.assertEqual(reconciled["status"], "paused")
        self.state = orc.load(self.state["id"])[1]
        self.assertEqual(self.state["status"], "paused")
        lane_a = self.state["parallel_writers"]["lanes"]["a"]
        lane_b = self.state["parallel_writers"]["lanes"]["b"]
        self.assertEqual(lane_a["status"], "complete")
        self.assertIn(lane_b["status"], {"interrupted", "failed"})
        self.assertFalse(lane_b.get("active_job"))
        self.assertTrue(lane_b.get("execution_stopped"))
        self.assertIsInstance(self.state.get("permission_blocked"), dict,
                              "the pending scoped authorization was discarded")
        self.assertTrue(Path(lane_a["worktree"]).is_dir(),
                        "unrelated completed lane output was removed")
        resumed = orc.resume_run(self.state["id"])
        self.assertEqual(resumed["status"], "running")
        self.state = orc.load(self.state["id"])[1]
        resumed_starts = []

        def finish(run_dir, state, cfg, role, kind, prompt, project, **kwargs):
            writer = kwargs.get("assignment")
            resumed_starts.append(writer)
            (Path(project) / "b.py").write_text("b = 2\n")
            return report("b finished"), pw.writer_job(run_dir, "b")

        with patch.object(orc, "call_model", side_effect=finish):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(resumed_starts, ["b"],
                         "completed lane a was dispatched again")
        self.assertEqual(self.state["phase"], "verify",
                         self.state.get("pause_reason"))
        self.assertEqual((self.project / "a.py").read_text(), "a = 1\n")
        self.assertEqual((self.project / "b.py").read_text(), "b = 2\n")
        self.assertEqual(self.state["parallel_integration"]["phase"], "complete")


class SingleWriterApprovalTests(BoundaryBase):
    """The resolver's effective one-writer choice governs preflight/approval."""

    def approve_and_dispatch(self, writers, *, max_writers=3, dirty=False,
                             route=None):
        plan = self.plan(writers)
        self.install_plan(plan, max_writers=max_writers,
                          status="awaiting_plan_approval")
        self.state.update({
            "plan_approval": True,
            "plan_authority": {
                "plan_version": orc.content_hash(plan), "plan_revision": 1,
                "amendment_epoch": 0, "authority_epoch": 0, "approved": False}})
        if route is not None:
            self.state["model_routes"] = {"implementer": route}
        if dirty:
            (self.project / "notes.txt").write_text("user work\n")
        orc.save(self.rundir, self.state)
        launched = orc.modify_locked(self.rundir, self.state, self.state["id"],
                                     "approve-plan")
        return launched

    def dispatch_single(self, writes):
        starts = []

        def fake(run_dir, state, cfg, role, kind, prompt, project, **kwargs):
            starts.append(kwargs.get("assignment"))
            for name, value in writes.items():
                (Path(project) / name).write_text(value)
            return report("single finished"), pw.writer_job(run_dir, "single")

        with patch.object(orc, "call_model", side_effect=fake):
            orc.advance(self.rundir, self.state, self.cfg)
        return starts

    def test_explicit_one_writer_on_dirty_checkout_approves_and_preserves(self):
        launched = self.approve_and_dispatch(
            [pw.writer("a", path="a.py")], dirty=True)
        self.assertTrue(launched, self.state.get("pause_reason"))
        self.assertEqual(self.state["status"], "running")
        starts = self.dispatch_single({"a.py": "a = 1\n"})
        self.assertEqual(starts, [None])
        self.assertEqual(self.state["phase"], "verify",
                         self.state.get("pause_reason"))
        self.assertEqual((self.project / "notes.txt").read_text(), "user work\n")
        self.assertEqual((self.project / "a.py").read_text(), "a = 1\n")

    def test_unreproducible_multi_writer_proposal_approves_single_fallback(self):
        launched = self.approve_and_dispatch(
            [pw.writer("a", path="a.py"), pw.writer("b", path="b.py")],
            dirty=True)
        self.assertTrue(launched, self.state.get("pause_reason"))
        advisories = self.state["permission_preflight"]["advisories"]
        fallback = [item for item in advisories
                    if item.get("kind") == "parallel_single_fallback"]
        self.assertEqual(len(fallback), 1, advisories)
        self.assertIn("dirty", fallback[0]["reason"])
        self.assertFalse(self.state["permission_preflight"]["ok"] is False)
        starts = self.dispatch_single({"a.py": "a = 1\n", "b.py": "b = 2\n"})
        self.assertEqual(starts, [None])
        self.assertEqual(self.state["phase"], "verify",
                         self.state.get("pause_reason"))
        self.assertEqual((self.project / "notes.txt").read_text(), "user work\n")
        self.assertFalse(orc._integration_record_path(self.rundir, 0).exists())

    def test_proposal_above_run_permission_approves_single_fallback(self):
        launched = self.approve_and_dispatch(
            [pw.writer("a", path="a.py"), pw.writer("b", path="b.py")],
            max_writers=1)
        self.assertTrue(launched, self.state.get("pause_reason"))
        advisories = self.state["permission_preflight"]["advisories"]
        fallback = [item for item in advisories
                    if item.get("kind") == "parallel_single_fallback"]
        self.assertEqual(len(fallback), 1, advisories)
        self.assertIn("permits 1", fallback[0]["reason"])
        starts = self.dispatch_single({"a.py": "a = 1\n", "b.py": "b = 2\n"})
        self.assertEqual(starts, [None])
        self.assertEqual(self.state["phase"], "verify",
                         self.state.get("pause_reason"))

    def test_missing_authority_on_selected_route_still_blocks(self):
        route = {"provider": "opencode", "model": "opencode-go/x",
                 "effort": "low", "billing": "api",
                 "routing_fingerprint": "9" * 64}
        launched = self.approve_and_dispatch(
            [pw.writer("a", path="a.py"), pw.writer("b", path="b.py")],
            dirty=True, route=route)
        self.assertFalse(launched)
        self.assertEqual(self.state["status"], "blocked")
        self.assertIn("route_grant", self.state["pause_reason"])
        self.assertFalse(any("parallel_grant" in (item.get("kind") or "")
                             for item in self.state["permission_preflight"]["missing"]))


class OneShotFallbackBoundaryTests(BoundaryBase):
    """Parent-owned fallback consent is never lent to parallel lanes."""

    def blocked_parallel(self, route):
        plan = self.plan([pw.writer("a", path="a.py"),
                          pw.writer("b", path="b.py")])
        grant = {"id": "primary-grant", "role": "implementer",
                 "run_id": self.state["id"],
                 "route_sha256": orc.route_authorization_sha(route),
                 "role_generation": 0, "used": 0, "max_dispatches": 2}
        self.install_plan(plan, max_writers=2)
        self.state["model_routes"] = {"implementer": route}
        self.state["route_authorizations"] = [grant]
        orc.save(self.rundir, self.state)
        batch = plan["batches"][0]
        resolved = orc.resolve_parallel_batch(
            self.state, self.project, batch, run_dir=self.rundir)

        def fake(run_dir, state, cfg, role, kind, prompt, project, **kwargs):
            writer = kwargs.get("assignment")
            (Path(project) / f"{writer}.py").write_text(f"{writer} = 'partial'\n")
            return blocked(f"{writer} needs a route"), pw.writer_job(run_dir, writer)

        with patch.object(orc, "call_model", side_effect=fake):
            result = orc.run_parallel_batch(
                self.rundir, self.state, self.cfg, self.project, batch,
                resolved, None)
        self.assertIsNone(result)
        self.assertEqual(self.state["status"], "blocked")
        self.assertEqual(
            {lane["status"] for lane in
             self.state["parallel_writers"]["lanes"].values()}, {"blocked"})
        return batch, resolved

    def transport(self, seen):
        def fake_guarded(command, cwd, env, log_stream, launch_file=None,
                         stdin_data=None, error_stream=None, stdin_fifo=None):
            model = command[command.index("--model") + 1]
            writer = Path(cwd).parent.name
            (Path(cwd) / f"{writer}.py").write_text(f"{writer} = 1\n")
            out = command[command.index("--output-last-message") + 1]
            Path(out).write_text(json.dumps(report(f"{writer} finished")))
            proc = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(0.3)"],
                start_new_session=True)
            if launch_file:
                orc.atomic_json(Path(launch_file),
                                {"guard": orc.process_identity(proc.pid)})
            seen.append(model)
            return proc, None
        return fake_guarded

    def test_pre_admission_fallback_spends_exactly_one_parent_dispatch(self):
        primary = {"provider": "codex", "model": "fixture-primary",
                   "effort": "low", "billing": "api"}
        plan = self.plan([pw.writer("a", path="a.py"),
                          pw.writer("b", path="b.py")])
        self.install_plan(plan, max_writers=2, status="blocked")
        self.state["model_routes"] = {"implementer": primary}
        orc.save(self.rundir, self.state)
        self.assertTrue(orc.modify_locked(
            self.rundir, self.state, self.state["id"], "approve-fallback",
            role="implementer"))
        fallback_model = self.state["fallback_authorization"]["route"]["model"]
        self.state = orc.load(self.state["id"])[1]
        seen = []
        with patch.object(orc, "_spawn_guarded",
                          side_effect=self.transport(seen)):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(seen, [fallback_model],
                         "the single parent dispatch did not use the fallback once")
        self.assertIsNone(self.state.get("fallback_authorization"),
                          "the one-shot fallback consent was not consumed")
        self.assertEqual(self.state["phase"], "verify",
                         self.state.get("pause_reason"))
        self.assertFalse(orc._integration_record_path(self.rundir, 0).exists())

    def test_host_fallback_never_reaches_parallel_lanes(self):
        primary = {"provider": "codex", "model": "fixture-primary",
                   "effort": "low", "billing": "api"}
        self.blocked_parallel(primary)
        self.assertTrue(orc.modify_locked(
            self.rundir, self.state, self.state["id"], "approve-fallback",
            role="implementer"))
        fallback = self.state["fallback_authorization"]
        self.assertIsInstance(fallback, dict)
        fallback_model = fallback["route"]["model"]
        # A restart after approval must keep the same parent-owned consent.
        self.state = orc.load(self.state["id"])[1]
        seen = []

        with patch.object(orc, "_spawn_guarded",
                          side_effect=self.transport(seen)):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(sorted(seen), ["fixture-primary", "fixture-primary"])
        self.assertNotIn(fallback_model, seen,
                         "a parallel lane consumed the parent's one-shot fallback")
        self.assertEqual(self.state["phase"], "verify",
                         self.state.get("pause_reason"))
        self.assertIsInstance(self.state.get("fallback_authorization"), dict,
                              "the parent fallback consent was lost")
        ledger = orc.load_grant_ledger(self.rundir, run_id=self.state["id"])
        grant = ledger["grants"]["primary-grant"]
        self.assertEqual(orc._grant_usage(grant), 2)
        self.assertTrue(all(item.get("state") == "launched"
                            for item in grant["reservations"]))

    def test_configured_worker_fallback_never_reaches_parallel_lanes(self):
        primary = {"provider": "codex", "model": "fixture-primary",
                   "effort": "low", "billing": "api",
                   "fallback_route": {
                       "provider": "codex", "model": "fixture-worker-fallback",
                       "effort": "low", "billing": "api"}}
        self.blocked_parallel(primary)
        with patch.object(orc, "require_human_operator",
                          return_value={"actor": "test", "method": "test"}):
            orc.approve_worker_fallback_run(self.state["id"], "implementer")
        self.state = orc.load(self.state["id"])[1]
        self.assertIsInstance(self.state.get("worker_fallback_authorization"),
                              dict)
        self.state["status"] = "running"
        orc.atomic_json(self.rundir / "control.json", {"action": "run"})
        orc.save(self.rundir, self.state)
        seen = []
        with patch.object(orc, "_spawn_guarded",
                          side_effect=self.transport(seen)):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(sorted(seen), ["fixture-primary", "fixture-primary"])
        self.assertNotIn("fixture-worker-fallback", seen,
                         "a lane consumed the configured worker fallback")
        self.assertEqual(self.state["phase"], "verify",
                         self.state.get("pause_reason"))
        self.assertIsInstance(self.state.get("worker_fallback_authorization"),
                              dict)


class HeldAuthorityResumeTests(BoundaryBase):
    """Public resume reuses held slots and never double-books a new grant."""

    def interrupt_before_thread_launch(self):
        primary = {"provider": "codex", "model": "fixture-primary",
                   "effort": "low", "billing": "api"}
        plan = self.plan([pw.writer("a", path="a.py"),
                          pw.writer("b", path="b.py")])
        grant = {"id": "held-grant", "role": "implementer",
                 "run_id": self.state["id"],
                 "route_sha256": orc.route_authorization_sha(primary),
                 "role_generation": 0, "used": 0, "max_dispatches": 2}
        self.install_plan(plan, max_writers=2)
        self.state["model_routes"] = {"implementer": primary}
        self.state["route_authorizations"] = [grant]
        orc.save(self.rundir, self.state)
        batch = plan["batches"][0]
        resolved = orc.resolve_parallel_batch(
            self.state, self.project, batch, run_dir=self.rundir)
        with patch.object(orc.threading.Thread, "start",
                          side_effect=RuntimeError("simulated parent loss")):
            with self.assertRaisesRegex(RuntimeError, "parent loss"):
                orc.run_parallel_batch(
                    self.rundir, self.state, self.cfg, self.project, batch,
                    resolved, None)
        self.state = orc.load(self.state["id"])[1]
        ledger = orc.load_grant_ledger(self.rundir, run_id=self.state["id"])
        grant = ledger["grants"]["held-grant"]
        self.assertEqual(orc._grant_usage(grant), 2)
        held = sorted(item["id"] for item in grant["reservations"])
        return batch, resolved, held

    def test_public_resume_uses_the_existing_held_slots(self):
        batch, resolved, held = self.interrupt_before_thread_launch()
        resumed = orc.resume_run(self.state["id"])
        self.assertEqual(resumed["status"], "running",
                         self.state.get("pause_reason"))
        self.state = orc.load(self.state["id"])[1]
        spawns = []
        with patch.object(orc, "_spawn_guarded",
                          side_effect=PaidLaunchBoundaryTests.transport(
                              self, spawns)):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(sorted(spawns), ["a", "b"])
        ledger = orc.load_grant_ledger(self.rundir, run_id=self.state["id"])
        grant = ledger["grants"]["held-grant"]
        self.assertEqual(orc._grant_usage(grant), 2)
        self.assertEqual(sorted(item["id"] for item in grant["reservations"]),
                         held)
        self.assertEqual(self.state["phase"], "verify",
                         self.state.get("pause_reason"))

    def test_new_grant_does_not_rebook_the_existing_slots(self):
        batch, resolved, held = self.interrupt_before_thread_launch()
        route = self.state["model_routes"]["implementer"]
        new_entry = {"id": "later-grant", "role": "implementer",
                     "run_id": self.state["id"],
                     "route_sha256": orc.route_authorization_sha(route),
                     "role_generation": 0, "used": 0, "max_dispatches": 2}
        orc.register_route_grant(self.rundir, new_entry)
        self.state["route_authorizations"].append(new_entry)
        orc.save(self.rundir, self.state)
        resumed = orc.resume_run(self.state["id"])
        self.assertEqual(resumed["status"], "running",
                         self.state.get("pause_reason"))
        self.state = orc.load(self.state["id"])[1]
        spawns = []
        with patch.object(orc, "_spawn_guarded",
                          side_effect=PaidLaunchBoundaryTests.transport(
                              self, spawns)):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(sorted(spawns), ["a", "b"])
        ledger = orc.load_grant_ledger(self.rundir, run_id=self.state["id"])
        original = ledger["grants"]["held-grant"]
        later = ledger["grants"]["later-grant"]
        self.assertEqual(orc._grant_usage(original), 2)
        self.assertEqual(orc._grant_usage(later), 0,
                         "the new grant charged held slots a second time")
        self.assertEqual(later["reservations"], [])
        self.assertEqual(sorted(item["id"] for item in original["reservations"]),
                         held)

    def test_exact_integration_checkpoint_resumes_without_a_new_grant(self):
        primary = {"provider": "codex", "model": "fixture-primary",
                   "effort": "low", "billing": "api"}
        plan = self.plan([pw.writer("a", path="a.py"),
                          pw.writer("b", path="b.py")])
        grant = {"id": "spent-grant", "role": "implementer",
                 "run_id": self.state["id"],
                 "route_sha256": orc.route_authorization_sha(primary),
                 "role_generation": 0, "used": 0, "max_dispatches": 2}
        self.install_plan(plan, max_writers=2)
        self.state["model_routes"] = {"implementer": primary}
        self.state["route_authorizations"] = [grant]
        orc.save(self.rundir, self.state)
        batch = plan["batches"][0]
        resolved = orc.resolve_parallel_batch(
            self.state, self.project, batch, run_dir=self.rundir)
        real = orc.atomic_json
        target = orc._integration_record_path(self.rundir, 0)
        spawns = []

        def patched(path, value, *args, **kwargs):
            if Path(path) == target and value.get("phase") == "complete":
                raise RuntimeError("simulated final manifest loss")
            return real(path, value, *args, **kwargs)

        with patch.object(orc, "_spawn_guarded",
                          side_effect=PaidLaunchBoundaryTests.transport(
                              self, spawns)), \
                patch.object(orc, "atomic_json", side_effect=patched):
            self.assertIsNone(orc.run_parallel_batch(
                self.rundir, self.state, self.cfg, self.project, batch,
                resolved, None))
        self.assertEqual(len(spawns), 2)
        self.state = orc.load(self.state["id"])[1]
        resumed = orc.resume_run(self.state["id"])
        self.assertEqual(resumed["status"], "running",
                         self.state.get("pause_reason"))
        self.state = orc.load(self.state["id"])[1]
        launches = []
        count, apply_patch = PostApplyRecoveryTests.count_canonical_applies(self)

        def must_not_run(*args, **kwargs):
            launches.append("model")
            raise AssertionError("a paid lane launched for bookkeeping only")

        with patch.object(orc, "call_model", side_effect=must_not_run), apply_patch:
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(launches, [])
        self.assertEqual(count["n"], 0)
        self.assertEqual(self.state["phase"], "verify",
                         self.state.get("pause_reason"))
        ledger = orc.load_grant_ledger(self.rundir, run_id=self.state["id"])
        self.assertEqual(orc._grant_usage(ledger["grants"]["spent-grant"]), 2)


class NoExecReleaseTests(BoundaryBase):
    """Only a positively proven no-exec launch may refund a launched slot."""

    def paid_grant(self):
        route = {"provider": "codex", "model": "fixture-primary",
                 "effort": "low", "billing": "api"}
        reviewer = {"provider": "codex", "model": "fixture-reviewer",
                    "effort": "low", "billing": "api"}
        plan = self.plan([pw.writer("a", path="a.py"),
                          pw.writer("b", path="b.py")])
        grant = {"id": "exec-grant", "role": "implementer",
                 "run_id": self.state["id"],
                 "route_sha256": orc.route_authorization_sha(route),
                 "role_generation": 0, "used": 0, "max_dispatches": 2}
        unrelated = {"id": "reviewer-grant", "role": "reviewer",
                     "run_id": self.state["id"],
                     "route_sha256": orc.route_authorization_sha(reviewer),
                     "role_generation": 0, "used": 0, "max_dispatches": 1}
        self.install_plan(plan, max_writers=2)
        self.state["model_routes"] = {"implementer": route, "reviewer": reviewer}
        self.state["route_authorizations"] = [grant, unrelated]
        orc.register_route_grant(self.rundir, grant)
        orc.register_route_grant(self.rundir, unrelated)
        orc.save(self.rundir, self.state)
        ids, problem = orc._reserve_parallel_authority(
            self.state, self.rundir, 2, self.cfg, None, 0,
            targets=[{"writer_id": "a", "attempt_id": "attempt-a"},
                     {"writer_id": "b", "attempt_id": "attempt-b"}])
        self.assertIsNone(problem)
        return route, ids

    def test_e2big_releases_only_the_affected_slot(self):
        import errno
        route, ids = self.paid_grant()

        def e2big(*args, **kwargs):
            raise OSError(errno.E2BIG, "argument list too long")

        lane_state = copy.deepcopy(self.state)
        with patch.object(orc, "_spawn_guarded", side_effect=e2big):
            with self.assertRaises(OSError):
                orc.call_model(
                    self.rundir, lane_state, self.cfg, "implementer",
                    "implementer", "do work", self.project, route=route,
                    assignment="a", grant_reservation_id=ids[0],
                    grant_attempt_id="attempt-a")
        ledger = orc.load_grant_ledger(self.rundir, run_id=self.state["id"])
        grant = ledger["grants"]["exec-grant"]
        self.assertEqual(orc._grant_usage(grant), 1)
        by_id = {item["id"]: item for item in grant["reservations"]}
        self.assertEqual(by_id[ids[0]]["state"], "released")
        self.assertEqual(by_id[ids[0]]["release_reason"],
                         "unexpected E2BIG before launch")
        self.assertEqual(by_id[ids[1]]["state"], "reserved")
        self.assertEqual(
            ledger["grants"]["reviewer-grant"]["reservations"], [])

    def test_confirmed_process_failure_retains_the_slot(self):
        route, ids = self.paid_grant()

        def failing_child(command, cwd, env, log_stream, launch_file=None,
                          stdin_data=None, error_stream=None, stdin_fifo=None):
            proc = subprocess.Popen(
                [sys.executable, "-c", "import sys; sys.exit(1)"],
                start_new_session=True)
            if launch_file:
                orc.atomic_json(Path(launch_file),
                                {"guard": orc.process_identity(proc.pid)})
            return proc, None

        lane_state = copy.deepcopy(self.state)
        with patch.object(orc, "_spawn_guarded", side_effect=failing_child):
            with self.assertRaisesRegex(RuntimeError, "exited 1"):
                orc.call_model(
                    self.rundir, lane_state, self.cfg, "implementer",
                    "implementer", "do work", self.project, route=route,
                    assignment="a", grant_reservation_id=ids[0],
                    grant_attempt_id="attempt-a")
        ledger = orc.load_grant_ledger(self.rundir, run_id=self.state["id"])
        grant = ledger["grants"]["exec-grant"]
        reservation = {item["id"]: item for item in grant["reservations"]}[ids[0]]
        self.assertEqual(reservation["state"], "launched")
        self.assertEqual(orc._grant_usage(grant), 2)


class SiblingSingleRecoveryTests(BoundaryBase):
    """A completed sibling manifest is revalidated before single dispatch."""

    def sibling_run(self):
        batch, _resolved = PostApplyRecoveryTests.prepare_writers(
            self, [pw.writer("a", path="a.py"), pw.writer("b", path="b.py")])
        fake = pw.ParallelWriterTests.fake_model(
            self, {"a": {"a.py": "a = 1\n"}}, fail={"b"})
        with patch.object(orc, "call_model", side_effect=fake):
            orc.advance(self.rundir, self.state, self.cfg)
        record = orc.read_json(orc._integration_record_path(self.rundir, 0))
        self.assertEqual(record["phase"], "sibling_recovery")
        self.assertEqual(record["after_sha"],
                         orc._checkout_content_sha(self.project))
        return batch, record

    def test_finalized_divergent_sibling_record_blocks(self):
        batch, record = self.sibling_run()
        (self.project / "app.py").write_text("value = 99\n")
        self.state = orc.load(self.state["id"])[1]
        self.state["status"] = "running"
        orc.atomic_json(self.rundir / "control.json", {"action": "run"})
        orc.save(self.rundir, self.state)
        launches = []

        def must_not_run(*args, **kwargs):
            launches.append("model")
            raise AssertionError("a writer ran over the divergent sibling apply")

        with patch.object(orc, "call_model", side_effect=must_not_run):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(launches, [])
        self.assertEqual(self.state["status"], "blocked")
        self.assertIn("no longer matches", self.state["pause_reason"])
        self.assertEqual((self.project / "app.py").read_text(), "value = 99\n")
        self.assertEqual((self.project / "a.py").read_text(), "a = 1\n")
        self.assertNotIn("parallel_sibling_single", self.state)
        self.assertEqual(orc.read_json(
            orc._integration_record_path(self.rundir, 0))["after_sha"],
            record["after_sha"])

    def test_exact_valid_sibling_record_continues_one_writer(self):
        batch, record = self.sibling_run()
        self.state = orc.load(self.state["id"])[1]
        self.state["status"] = "running"
        orc.atomic_json(self.rundir / "control.json", {"action": "run"})
        orc.save(self.rundir, self.state)
        starts = []

        def finish(run_dir, state, cfg, role, kind, prompt, project, **kwargs):
            starts.append(kwargs.get("assignment"))
            (Path(project) / "b.py").write_text("b = 2\n")
            return report("b finished"), pw.writer_job(run_dir, "single")

        with patch.object(orc, "call_model", side_effect=finish):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(starts, [None])
        self.assertEqual(self.state["phase"], "verify",
                         self.state.get("pause_reason"))
        accepted = self.state["parallel_sibling_single"]["0"]
        self.assertEqual(accepted["after_sha"], record["after_sha"])
        self.assertEqual((self.project / "a.py").read_text(), "a = 1\n")
        self.assertEqual((self.project / "b.py").read_text(), "b = 2\n")

    def test_interrupted_accepted_single_writer_correction_resumes(self):
        batch, record = self.sibling_run()
        self.state = orc.load(self.state["id"])[1]
        self.state["status"] = "running"
        orc.atomic_json(self.rundir / "control.json", {"action": "run"})
        orc.save(self.rundir, self.state)
        sleeper = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(120)"],
            start_new_session=True)
        self.addCleanup(lambda: sleeper.kill() if sleeper.poll() is None else None)
        identity = orc.process_identity(sleeper.pid) or {"pid": sleeper.pid}
        starts = []

        def interrupted(run_dir, state, cfg, role, kind, prompt, project, **kwargs):
            starts.append(kwargs.get("assignment"))
            (Path(project) / "b.py").write_text("b = 'partial'\n")
            state["active_job"] = {
                "id": "sibling-single-job", "role": "implementer",
                "kind": "implementer", "status": "dispatched", **identity}
            state["status"] = "uncertain"
            orc.save(run_dir, state)
            raise RuntimeError("simulated single-writer loss")

        with patch.object(orc, "call_model", side_effect=interrupted):
            with self.assertRaisesRegex(RuntimeError, "single-writer loss"):
                orc.advance(self.rundir, self.state, self.cfg)
        self.state = orc.load(self.state["id"])[1]
        self.assertIn("parallel_sibling_single", self.state)
        sleeper.terminate()
        sleeper.wait(timeout=10)
        reconciled = orc.reconcile_run(self.state["id"])
        self.assertEqual(reconciled["status"], "paused")
        self.state = orc.load(self.state["id"])[1]
        self.assertEqual(orc.resume_run(self.state["id"])["status"], "running")
        self.state = orc.load(self.state["id"])[1]
        resumed = []

        def finish(run_dir, state, cfg, role, kind, prompt, project, **kwargs):
            resumed.append(kwargs.get("assignment"))
            (Path(project) / "b.py").write_text("b = 2\n")
            return report("b finished"), pw.writer_job(run_dir, "single")

        with patch.object(orc, "call_model", side_effect=finish):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(resumed, [None])
        self.assertEqual(starts, [None])
        self.assertEqual(self.state["phase"], "verify",
                         self.state.get("pause_reason"))
        self.assertEqual((self.project / "b.py").read_text(), "b = 2\n")


if __name__ == "__main__":
    unittest.main()
