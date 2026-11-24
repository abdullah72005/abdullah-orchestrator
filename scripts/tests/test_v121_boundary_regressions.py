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
import os
import shutil
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

    def test_collection_loss_with_finished_paid_lanes_resumes_without_new_grant(self):
        primary = {"provider": "codex", "model": "fixture-primary",
                   "effort": "low", "billing": "api"}
        plan = self.plan([pw.writer("a", path="a.py"),
                          pw.writer("b", path="b.py")])
        grant = {"id": "collection-grant", "role": "implementer",
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
        spawns = []
        with patch.object(orc, "_spawn_guarded",
                          side_effect=PaidLaunchBoundaryTests.transport(
                              self, spawns)), \
                patch.object(orc, "_validate_lane_outcome",
                             side_effect=RuntimeError("simulated collection loss")):
            with self.assertRaisesRegex(RuntimeError, "collection loss"):
                orc.run_parallel_batch(
                    self.rundir, self.state, self.cfg, self.project, batch,
                    resolved, None)
        self.assertEqual(len(spawns), 2)
        self.state = orc.load(self.state["id"])[1]
        for lane in self.state["parallel_writers"]["lanes"].values():
            self.assertTrue((Path(lane["lane_dir"]) / "lane-result.json").is_file())
            self.assertIsNotNone(orc._durable_lane_outcome(lane))
        resumed = orc.resume_run(self.state["id"])
        self.assertEqual(resumed["status"], "running",
                         self.state.get("pause_reason"))
        self.state = orc.load(self.state["id"])[1]
        launches = []

        def must_not_run(*args, **kwargs):
            launches.append("model")
            raise AssertionError("a finished paid lane was launched again")

        with patch.object(orc, "call_model", side_effect=must_not_run):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(launches, [])
        self.assertEqual(self.state["phase"], "verify",
                         self.state.get("pause_reason"))
        self.assertEqual((self.project / "a.py").read_text(), "a = 1\n")
        self.assertEqual((self.project / "b.py").read_text(), "b = 1\n")
        ledger = orc.load_grant_ledger(self.rundir, run_id=self.state["id"])
        self.assertEqual(orc._grant_usage(ledger["grants"]["collection-grant"]), 2)
        self.assertTrue(all(item.get("state") == "launched" for item in
                            ledger["grants"]["collection-grant"]["reservations"]))

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

    def test_final_binding_refusal_releases_only_the_held_slot(self):
        route, ids = self.paid_grant()
        lane_state = copy.deepcopy(self.state)
        observed = orc._source_observation(self.project)
        binding = {"version": 1, "source": observed["source"],
                   "signature": observed["signature"],
                   "checkout_sha256": "0" * 64,
                   "manifest": None, "origin": "test"}

        def must_not_spawn(*args, **kwargs):
            raise AssertionError("a child started after a binding refusal")

        with patch.object(orc, "_spawn_guarded", side_effect=must_not_spawn):
            with self.assertRaisesRegex(RuntimeError, "Dispatch not attempted"):
                orc.call_model(
                    self.rundir, lane_state, self.cfg, "implementer",
                    "implementer", "do work", self.project, route=route,
                    assignment="a", grant_reservation_id=ids[0],
                    grant_attempt_id="attempt-a", expected_binding=binding)
        rejection = lane_state["preflight_rejection"]
        self.assertEqual(rejection["reason_code"], "dispatch_binding_changed")
        self.assertFalse(rejection["active_job_created"])
        self.assertEqual(rejection["expected_binding"]["checkout_sha256"],
                         "0" * 64)
        self.assertIsNotNone(rejection["observed_binding"]["checkout_sha256"])
        ledger = orc.load_grant_ledger(self.rundir, run_id=self.state["id"])
        grant = ledger["grants"]["exec-grant"]
        by_id = {item["id"]: item for item in grant["reservations"]}
        self.assertEqual(by_id[ids[0]]["state"], "released")
        self.assertEqual(by_id[ids[0]]["release_reason"],
                         "dispatch binding changed before launch")
        self.assertEqual(by_id[ids[1]]["state"], "reserved")
        self.assertEqual(orc._grant_usage(grant), 1)

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

    def test_admission_marker_without_dispatch_rechecks_divergence(self):
        batch, record = self.sibling_run()
        self.state = orc.load(self.state["id"])[1]
        self.state["status"] = "running"
        orc.atomic_json(self.rundir / "control.json", {"action": "run"})
        orc.save(self.rundir, self.state)

        def refusal(*args, **kwargs):
            raise RuntimeError("known preflight refusal before launch")

        with patch.object(orc, "call_model", side_effect=refusal):
            with self.assertRaisesRegex(RuntimeError, "preflight refusal"):
                orc.advance(self.rundir, self.state, self.cfg)
        self.state = orc.load(self.state["id"])[1]
        accepted = self.state["parallel_sibling_single"]["0"]
        self.assertEqual(accepted["after_sha"], record["after_sha"])
        self.assertIsNone(orc._sibling_single_attempt(self.state, accepted))
        original = (self.project / "app.py").read_text()
        (self.project / "app.py").write_text("value = 99\n")
        self.state["status"] = "running"
        orc.atomic_json(self.rundir / "control.json", {"action": "run"})
        orc.save(self.rundir, self.state)
        launches = []

        def must_not_run(*args, **kwargs):
            launches.append("model")
            raise AssertionError("a marker without a proven dispatch authorized edits")

        with patch.object(orc, "call_model", side_effect=must_not_run):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(launches, [])
        self.assertEqual(self.state["status"], "blocked")
        self.assertIn("no longer matches", self.state["pause_reason"])
        self.assertEqual((self.project / "app.py").read_text(), "value = 99\n")
        # Restoring the exact recorded after identity safely continues once.
        (self.project / "app.py").write_text(original)
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
        self.state["model_routes"] = {"implementer": {
            "provider": "codex", "model": "fixture-primary", "effort": "low",
            "billing": "subscription"}}
        orc.atomic_json(self.rundir / "control.json", {"action": "run"})
        orc.save(self.rundir, self.state)
        starts = []

        def failing_transport(command, cwd, env, log_stream, launch_file=None,
                              stdin_data=None, error_stream=None,
                              stdin_fifo=None):
            (Path(cwd) / "b.py").write_text("b = 'partial'\n")
            starts.append(command[command.index("--model") + 1])
            proc = subprocess.Popen(
                [sys.executable, "-c", "import sys; sys.exit(1)"],
                start_new_session=True)
            if launch_file:
                orc.atomic_json(Path(launch_file),
                                {"guard": orc.process_identity(proc.pid)})
            return proc, None

        with patch.object(orc, "_spawn_guarded",
                          side_effect=failing_transport):
            with self.assertRaisesRegex(RuntimeError, "exited 1"):
                orc.advance(self.rundir, self.state, self.cfg)
        self.state = orc.load(self.state["id"])[1]
        self.assertIn("parallel_sibling_single", self.state)
        accepted = self.state["parallel_sibling_single"]["0"]
        self.assertIsNotNone(orc._sibling_single_attempt(self.state, accepted),
                             "the real dispatch was not source-bound")
        self.state["status"] = "uncertain"
        orc.save(self.rundir, self.state)
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
        self.assertEqual(starts, ["fixture-primary"])
        self.assertEqual(self.state["phase"], "verify",
                         self.state.get("pause_reason"))
        self.assertEqual((self.project / "b.py").read_text(), "b = 2\n")


class EffectiveRouteResumeTests(BoundaryBase):
    """Public resume authorizes the route the pending single writer will use."""

    def paused_after_fallback(self, primary, approve):
        plan = self.plan([pw.writer("a", path="a.py"),
                          pw.writer("b", path="b.py")])
        self.install_plan(plan, max_writers=2, status="blocked")
        self.state["model_routes"] = {"implementer": primary}
        orc.save(self.rundir, self.state)
        approve()
        self.state = orc.load(self.state["id"])[1]
        self.state["status"] = "paused"
        orc.atomic_json(self.rundir / "control.json", {"action": "pause"})
        orc.save(self.rundir, self.state)
        return plan

    def test_unfunded_primary_with_approved_host_fallback_resumes(self):
        primary = {"provider": "codex", "model": "fixture-primary",
                   "effort": "low", "billing": "api"}
        self.paused_after_fallback(
            primary,
            lambda: self.assertTrue(orc.modify_locked(
                self.rundir, self.state, self.state["id"], "approve-fallback",
                role="implementer")))
        self.state = orc.load(self.state["id"])[1]
        fallback_model = self.state["fallback_authorization"]["route"]["model"]
        resumed = orc.resume_run(self.state["id"])
        self.assertEqual(resumed["status"], "running",
                         self.state.get("pause_reason"))
        self.state = orc.load(self.state["id"])[1]
        advisories = self.state["permission_preflight"]["advisories"]
        self.assertTrue(any(item.get("role") == "implementer"
                            and item.get("primary_deferred") for item in advisories),
                        advisories)
        self.assertFalse(any(item.get("kind") == "route_grant"
                             and item.get("role") == "implementer"
                             and not item.get("primary_deferred")
                             for item in self.state["permission_preflight"]["missing"]))
        self.state = orc.load(self.state["id"])[1]
        seen = []
        with patch.object(orc, "_spawn_guarded",
                          side_effect=OneShotFallbackBoundaryTests.transport(
                              self, seen)):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(seen, [fallback_model])
        self.assertIsNone(self.state.get("fallback_authorization"))
        self.assertEqual(self.state["phase"], "verify",
                         self.state.get("pause_reason"))

    def test_missing_primary_grant_with_configured_worker_fallback_resumes(self):
        primary = {"provider": "codex", "model": "fixture-primary",
                   "effort": "low", "billing": "api",
                   "fallback_route": {
                       "provider": "codex", "model": "fixture-worker-fallback",
                       "effort": "low", "billing": "subscription"}}
        with patch.object(orc, "require_human_operator",
                          return_value={"actor": "test", "method": "test"}):
            self.paused_after_fallback(
                primary,
                lambda: orc.approve_worker_fallback_run(self.state["id"],
                                                        "implementer"))
        self.state = orc.load(self.state["id"])[1]
        self.assertIsInstance(self.state.get("worker_fallback_authorization"),
                              dict)
        self.assertEqual(orc.resume_run(self.state["id"])["status"], "running")
        self.state = orc.load(self.state["id"])[1]
        seen = []
        with patch.object(orc, "_spawn_guarded",
                          side_effect=OneShotFallbackBoundaryTests.transport(
                              self, seen)):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(seen, ["fixture-worker-fallback"])
        self.assertIsNone(self.state.get("worker_fallback_authorization"))
        self.assertEqual(self.state["phase"], "verify",
                         self.state.get("pause_reason"))

    def test_invalid_fallback_authorization_blocks_resume(self):
        primary = {"provider": "codex", "model": "fixture-primary",
                   "effort": "low", "billing": "api"}
        self.paused_after_fallback(
            primary,
            lambda: self.assertTrue(orc.modify_locked(
                self.rundir, self.state, self.state["id"], "approve-fallback",
                role="implementer")))
        self.state = orc.load(self.state["id"])[1]
        self.state["fallback_authorization"]["route_sha256"] = "0" * 64
        orc.save(self.rundir, self.state)
        launches = []

        def must_not_run(*args, **kwargs):
            launches.append("model")
            raise AssertionError("an invalid fallback authorization dispatched")

        with patch.object(orc, "call_model", side_effect=must_not_run):
            resumed = orc.resume_run(self.state["id"])
        self.assertEqual(resumed["status"], "blocked")
        self.assertEqual(launches, [])
        self.state = orc.load(self.state["id"])[1]
        missing = self.state["permission_preflight"]["missing"]
        self.assertTrue(any(item.get("kind") == "fallback_authorization"
                            for item in missing), missing)
        self.assertIn("fallback_authorization", self.state["pause_reason"])
        self.assertIsInstance(self.state.get("fallback_authorization"), dict)


class OwnerGrantReleaseTests(BoundaryBase):
    """Exact preflight cleanup releases through the slot's owning grant."""

    def setup_grants(self):
        route = {"provider": "codex", "model": "fixture-primary",
                 "effort": "low", "billing": "unknown"}
        plan = self.plan([pw.writer("a", path="a.py")])
        older = {"id": "older-grant", "role": "implementer",
                 "run_id": self.state["id"],
                 "route_sha256": orc.route_authorization_sha(route),
                 "role_generation": 0, "used": 0, "max_dispatches": 2}
        newer = {"id": "newer-grant", "role": "implementer",
                 "run_id": self.state["id"],
                 "route_sha256": orc.route_authorization_sha(route),
                 "role_generation": 0, "used": 0, "max_dispatches": 2}
        self.install_plan(plan, max_writers=1)
        self.state["model_routes"] = {"implementer": route}
        self.state["route_authorizations"] = [older]
        orc.register_route_grant(self.rundir, older)
        orc.save(self.rundir, self.state)
        ids, problem = orc._reserve_parallel_authority(
            self.state, self.rundir, 1, self.cfg, None, 0,
            targets=[{"writer_id": "a", "attempt_id": "attempt-a"}])
        self.assertIsNone(problem)
        # A newer same-route grant arrives after the slot is already held.
        orc.register_route_grant(self.rundir, newer)
        self.state["route_authorizations"].append(newer)
        orc.save(self.rundir, self.state)
        return route, ids[0]

    def test_real_preflight_rejection_releases_the_older_held_slot(self):
        route, reservation_id = self.setup_grants()
        expectation = {"id": reservation_id, "lane": "a",
                       "attempt_id": "attempt-a", "batch_index": 0}
        lane_state = copy.deepcopy(self.state)
        spawns = []

        def must_not_spawn(*args, **kwargs):
            spawns.append("child")
            raise AssertionError("a child started after a preflight rejection")

        with patch.object(orc, "_spawn_guarded", side_effect=must_not_spawn):
            with self.assertRaisesRegex(RuntimeError, "preflight"):
                orc.call_model(
                    self.rundir, lane_state, self.cfg, "implementer",
                    "implementer", "do work", self.project, route=route,
                    assignment="a", grant_reservation_id=reservation_id,
                    grant_attempt_id="attempt-a")
        self.assertEqual(spawns, [])
        ledger = orc.load_grant_ledger(self.rundir, run_id=self.state["id"])
        older = ledger["grants"]["older-grant"]
        newer = ledger["grants"]["newer-grant"]
        self.assertEqual(orc._grant_usage(older), 0)
        self.assertEqual(
            [item["id"] for item in older["reservations"]], [reservation_id])
        self.assertEqual(older["reservations"][0]["state"], "released")
        self.assertEqual(orc._grant_usage(newer), 0)
        self.assertEqual(newer["reservations"], [])

    def test_exact_helper_resolves_the_owning_grant(self):
        route, reservation_id = self.setup_grants()
        expectation = {"id": reservation_id, "lane": "a",
                       "attempt_id": "attempt-a", "batch_index": 0}
        released = orc._release_exact_held_reservation(
            self.state, self.rundir, "implementer", route, reservation_id,
            expectation, "exact held rejection", cfg=self.cfg)
        self.assertIsNotNone(released)
        ledger = orc.load_grant_ledger(self.rundir, run_id=self.state["id"])
        older = ledger["grants"]["older-grant"]
        newer = ledger["grants"]["newer-grant"]
        self.assertEqual(orc._grant_usage(older), 0)
        self.assertEqual(older["reservations"][0]["state"], "released")
        self.assertEqual(newer["reservations"], [])


class WriterSourceBindingTests(BoundaryBase):
    """The first single writer is bound to the validated sibling source."""

    def prepare_sibling(self):
        SiblingSingleRecoveryTests.sibling_run(self)
        self.state = orc.load(self.state["id"])[1]
        self.state["status"] = "running"
        self.state["model_routes"] = {
            "implementer": {"provider": "codex", "model": "fixture-primary",
                            "effort": "low", "billing": "subscription"}}
        orc.atomic_json(self.rundir / "control.json", {"action": "run"})
        orc.save(self.rundir, self.state)
        self.assertEqual((self.project / "a.py").read_text(), "a = 1\n")

    def assert_blocked_before_any_child(self, reason_code):
        self.state = orc.load(self.state["id"])[1]
        self.assertEqual(self.state["phase"], "implement")
        self.assertEqual(self.state["status"], "blocked")
        self.assertFalse(self.state.get("active_job"))
        self.assertEqual(self.state["preflight_rejection"]["reason_code"],
                         reason_code)
        self.assertFalse(self.state["preflight_rejection"]["active_job_created"])
        self.assertFalse(self.state["preflight_rejection"]["model_calls_counted"])

    def test_source_change_before_prompt_capture_blocks_first_writer(self):
        self.prepare_sibling()
        record_path = orc._integration_record_path(self.rundir, 0)
        manifest_before = orc._sha256_file(record_path)
        real_journal = orc.journal_event
        mutated = []

        def mutate_at_fallback(run_dir, state, event, **values):
            result = real_journal(run_dir, state, event, **values)
            if event == "parallel_plan_single_fallback" and not mutated:
                mutated.append(True)
                (self.project / "app.py").write_text("value = 99\n")
            return result

        def must_not_spawn(*args, **kwargs):
            raise AssertionError("a writer child started on a drifted source")

        with patch.object(orc, "journal_event", side_effect=mutate_at_fallback), \
                patch.object(orc, "_spawn_guarded", side_effect=must_not_spawn):
            with self.assertRaisesRegex(RuntimeError,
                                        "candidate changed before launch"):
                orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(mutated, [True])
        self.assert_blocked_before_any_child("candidate_changed_before_dispatch")
        self.assertEqual((self.project / "app.py").read_text(), "value = 99\n")
        self.assertEqual((self.project / "a.py").read_text(), "a = 1\n")
        self.assertEqual(orc._sha256_file(record_path), manifest_before)
        accepted = self.state["parallel_sibling_single"]["0"]
        self.assertEqual(orc.signature(accepted["after_source"]),
                         accepted["after_snapshot"])
        self.assertNotEqual(orc.signature(accepted["after_source"]),
                            orc.signature(orc.source_snapshot(self.project)))

    def test_source_change_after_prompt_construction_blocks(self):
        self.prepare_sibling()
        real_prompt = orc.prompt_request
        mutated = []

        def prompt_with_edit(kind, context):
            if kind == "implementer" and not mutated:
                mutated.append(True)
                (self.project / "notes.txt").write_text("external\n")
            return real_prompt(kind, context)

        def must_not_spawn(*args, **kwargs):
            raise AssertionError("a writer child started after prompt construction")

        with patch.object(orc, "prompt_request",
                          side_effect=prompt_with_edit), \
                patch.object(orc, "_spawn_guarded", side_effect=must_not_spawn):
            with self.assertRaisesRegex(RuntimeError,
                                        "candidate changed before launch"):
                orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(mutated, [True])
        self.assert_blocked_before_any_child("candidate_changed_before_dispatch")
        self.assertEqual((self.project / "notes.txt").read_text(), "external\n")
        self.assertEqual((self.project / "a.py").read_text(), "a = 1\n")

    def test_exact_sibling_source_continues_with_the_same_dispatch_source(self):
        self.prepare_sibling()
        seen = []
        with patch.object(
                orc, "_spawn_guarded",
                side_effect=OneShotFallbackBoundaryTests.transport(self, seen)):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(seen, ["fixture-primary"])
        self.state = orc.load(self.state["id"])[1]
        self.assertEqual(self.state["phase"], "verify",
                         self.state.get("pause_reason"))
        accepted = self.state["parallel_sibling_single"]["0"]
        job = self.state["completed_jobs"][-1]
        self.assertEqual(job["role"], "implementer")
        dispatch = orc.read_json(Path(job["path"]) / "dispatch.json")
        self.assertEqual(orc.signature(dispatch["source"]),
                         accepted["after_snapshot"])
        self.assertEqual(orc.signature(dispatch["source"]),
                         orc.signature(accepted["after_source"]))


class StoppedWriterSourceTests(BoundaryBase):
    """A correction retry continues only the last attributable source boundary."""

    def prepare_sibling(self):
        WriterSourceBindingTests.prepare_sibling(self)

    def failing_transport(self, attempts):
        def failing(command, cwd, env, log_stream, launch_file=None,
                    stdin_data=None, error_stream=None, stdin_fifo=None):
            (Path(cwd) / "b.py").write_text("b = 'partial'\n")
            proc = subprocess.Popen(
                [sys.executable, "-c", "import sys; sys.exit(1)"],
                start_new_session=True)
            if launch_file:
                orc.atomic_json(Path(launch_file),
                                {"guard": orc.process_identity(proc.pid)})
            attempts.append(command[command.index("--model") + 1])
            return proc, None
        return failing

    def finishing_transport(self, starts):
        def finishing(command, cwd, env, log_stream, launch_file=None,
                      stdin_data=None, error_stream=None, stdin_fifo=None):
            (Path(cwd) / "b.py").write_text("b = 2\n")
            out = command[command.index("--output-last-message") + 1]
            Path(out).write_text(json.dumps(report("b finished")))
            proc = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(0.3)"],
                start_new_session=True)
            if launch_file:
                orc.atomic_json(Path(launch_file),
                                {"guard": orc.process_identity(proc.pid)})
            starts.append(command[command.index("--model") + 1])
            return proc, None
        return finishing

    def test_external_edit_after_reconcile_blocks_and_unchanged_partial_resumes(self):
        self.prepare_sibling()
        original_app = (self.project / "app.py").read_text()
        attempts = []
        with patch.object(orc, "_spawn_guarded",
                          side_effect=self.failing_transport(attempts)):
            with self.assertRaisesRegex(RuntimeError, "exited 1"):
                orc.advance(self.rundir, self.state, self.cfg)
        self.state = orc.load(self.state["id"])[1]
        self.assertEqual(attempts, ["fixture-primary"])
        self.assertEqual((self.project / "b.py").read_text(), "b = 'partial'\n")
        self.assertIn("writer_source_boundaries", self.state)
        self.assertEqual(self.state["writer_source_boundaries"]["0"]["phase"],
                         "failure")
        self.state["status"] = "uncertain"
        orc.save(self.rundir, self.state)
        reconciled = orc.reconcile_run(self.state["id"])
        self.assertEqual(reconciled["status"], "paused")
        self.state = orc.load(self.state["id"])[1]
        boundary = self.state["writer_source_boundaries"]["0"]
        self.assertEqual(boundary["phase"], "failure")
        self.assertEqual(orc.signature(boundary["source"]),
                         orc.signature(orc.source_snapshot(self.project)))

        # An external edit after the reconciliation evidence cannot be
        # attributed to the stopped attempt and must not reach a writer.
        (self.project / "app.py").write_text("value = 99\n")
        self.assertEqual(orc.resume_run(self.state["id"])["status"], "running")
        self.state = orc.load(self.state["id"])[1]
        starts = []

        def must_not_spawn(*args, **kwargs):
            starts.append("child")
            raise AssertionError("a writer launched over an unattributed edit")

        with patch.object(orc, "_spawn_guarded", side_effect=must_not_spawn):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(starts, [])
        self.state = orc.load(self.state["id"])[1]
        self.assertEqual(self.state["phase"], "implement")
        self.assertEqual(self.state["status"], "blocked")
        self.assertIn("changed after the last attributable writer boundary",
                      self.state["pause_reason"])
        self.assertEqual((self.project / "app.py").read_text(), "value = 99\n")
        self.assertEqual((self.project / "b.py").read_text(), "b = 'partial'\n")
        self.assertEqual(orc.signature(self.state["writer_source_boundaries"]["0"]["source"]),
                         boundary["signature"])

        # Restoring the exact boundary (including the partial worker output)
        # permits one replacement writer from that same source.
        (self.project / "app.py").write_text(original_app)
        self.assertEqual(orc.resume_run(self.state["id"])["status"], "running")
        self.state = orc.load(self.state["id"])[1]
        resumed = []
        with patch.object(orc, "_spawn_guarded",
                          side_effect=self.finishing_transport(resumed)):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(resumed, ["fixture-primary"])
        self.state = orc.load(self.state["id"])[1]
        self.assertEqual(self.state["phase"], "verify",
                         self.state.get("pause_reason"))
        self.assertEqual((self.project / "b.py").read_text(), "b = 2\n")
        restored = [job for job in self.state["completed_jobs"]
                    if job.get("role") == "implementer"][-1]
        dispatch = orc.read_json(Path(restored["path"]) / "dispatch.json")
        self.assertEqual(orc.signature(dispatch["source"]),
                         boundary["signature"])


class EffectiveRouteExecutableTests(BoundaryBase):
    """Preflight checks the executable for the route the stage will select."""

    def paused_after_fallback(self, primary):
        EffectiveRouteResumeTests.paused_after_fallback(
            self, primary,
            lambda: self.assertTrue(orc.modify_locked(
                self.rundir, self.state, self.state["id"], "approve-fallback",
                role="implementer")))

    def which_without(self, missing):
        real = shutil.which

        def fake(command, path=None):
            if command in missing:
                return None
            return real(command, path=path)
        return fake

    def test_missing_unused_primary_cli_does_not_block_selected_fallback(self):
        self.paused_after_fallback({"provider": "opencode",
                                    "model": "opencode-go/x",
                                    "effort": "low", "billing": "go"})
        self.state = orc.load(self.state["id"])[1]
        fallback_model = self.state["fallback_authorization"]["route"]["model"]
        with patch.object(orc.shutil, "which",
                          side_effect=self.which_without({"opencode"})):
            resumed = orc.resume_run(self.state["id"])
        self.assertEqual(resumed["status"], "running",
                         self.state.get("pause_reason"))
        self.state = orc.load(self.state["id"])[1]
        preflight = self.state["permission_preflight"]
        self.assertTrue(any(item.get("kind") == "route_executable"
                            and item.get("role") == "implementer"
                            and item.get("primary_deferred")
                            for item in preflight["advisories"]), preflight)
        self.assertFalse(any(item.get("kind") == "route_executable"
                             for item in preflight["missing"]), preflight)
        seen = []
        with patch.object(orc.shutil, "which",
                          side_effect=self.which_without({"opencode"})), \
                patch.object(orc, "_spawn_guarded",
                             side_effect=OneShotFallbackBoundaryTests.transport(
                                 self, seen)):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(seen, [fallback_model])
        self.state = orc.load(self.state["id"])[1]
        self.assertEqual(self.state["phase"], "verify",
                         self.state.get("pause_reason"))
        self.assertIsNone(self.state.get("fallback_authorization"))

    def test_missing_selected_fallback_cli_blocks_resume(self):
        self.paused_after_fallback({"provider": "opencode",
                                    "model": "opencode-go/x",
                                    "effort": "low", "billing": "go"})
        with patch.object(orc.shutil, "which",
                          side_effect=self.which_without({"opencode", "codex"})):
            resumed = orc.resume_run(self.state["id"])
        self.assertEqual(resumed["status"], "blocked")
        self.state = orc.load(self.state["id"])[1]
        missing = self.state["permission_preflight"]["missing"]
        self.assertTrue(any(item.get("kind") == "route_executable"
                            and item.get("role") == "implementer"
                            and item.get("selected_route") == "fallback"
                            for item in missing), missing)
        self.assertIn("route_executable", self.state["pause_reason"])
        self.assertIsInstance(self.state.get("fallback_authorization"), dict)


class LateDispatchBindingTests(BoundaryBase):
    """Every bound input is rechecked at the final no-child dispatch gate."""

    def prepare_sibling(self):
        WriterSourceBindingTests.prepare_sibling(self)

    def mutate_at_prompt(self, kind, mutated):
        real_prompt = orc.prompt_request

        def prompt_with_mutation(prompt_kind, context):
            if prompt_kind == "implementer" and not mutated:
                mutated.append(True)
                if kind == "manifest":
                    path = orc._integration_record_path(self.rundir, 0)
                    path.write_bytes(path.read_bytes() + b"\n")
                else:
                    path = self.project / "a.py"
                    current = path.stat().st_mode & 0o777
                    path.chmod(0o644 if current == 0o600 else 0o600)
            return real_prompt(prompt_kind, context)
        return prompt_with_mutation

    def blocked_first_dispatch(self, kind):
        self.prepare_sibling()
        mode_before = (self.project / "a.py").stat().st_mode & 0o777
        mutated = []
        starts = []

        def must_not_spawn(*args, **kwargs):
            starts.append("child")
            raise AssertionError("a child started after a late binding change")

        with patch.object(orc, "prompt_request",
                          side_effect=self.mutate_at_prompt(kind, mutated)), \
                patch.object(orc, "_spawn_guarded", side_effect=must_not_spawn):
            with self.assertRaisesRegex(RuntimeError, "Dispatch not attempted"):
                orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(mutated, [True])
        self.assertEqual(starts, [])
        self.state = orc.load(self.state["id"])[1]
        self.assertEqual(self.state["phase"], "implement")
        self.assertEqual(self.state["status"], "blocked")
        self.assertEqual(self.state["preflight_rejection"]["reason_code"],
                         "dispatch_binding_changed")
        self.assertFalse(self.state["preflight_rejection"]["active_job_created"])
        self.assertEqual((self.project / "a.py").read_text(), "a = 1\n")
        if kind == "mode":
            self.assertNotEqual(
                (self.project / "a.py").stat().st_mode & 0o777, mode_before)
        return self.state["preflight_rejection"]

    def test_manifest_change_after_prompt_construction_blocks(self):
        rejection = self.blocked_first_dispatch("manifest")
        self.assertIn("manifest changed", rejection["reasons"][0])
        self.assertTrue(orc._integration_record_path(
            self.rundir, 0).read_bytes().endswith(b"\n"))
        self.assertEqual(rejection["expected_binding"]["checkout_sha256"],
                         rejection["observed_binding"]["checkout_sha256"])

    def test_mode_change_after_prompt_construction_blocks(self):
        rejection = self.blocked_first_dispatch("mode")
        self.assertIn("tree/index/mode", rejection["reasons"][0])
        self.assertNotEqual(rejection["expected_binding"]["checkout_sha256"],
                            rejection["observed_binding"]["checkout_sha256"])

    def blocked_retry(self, kind):
        self.prepare_sibling()
        mode_before = (self.project / "a.py").stat().st_mode & 0o777
        attempts = []
        with patch.object(
                orc, "_spawn_guarded",
                side_effect=StoppedWriterSourceTests.failing_transport(
                    self, attempts)):
            with self.assertRaisesRegex(RuntimeError, "exited 1"):
                orc.advance(self.rundir, self.state, self.cfg)
        self.state = orc.load(self.state["id"])[1]
        self.assertEqual(attempts, ["fixture-primary"])
        boundary = self.state["writer_source_boundaries"]["0"]
        self.state["status"] = "uncertain"
        orc.save(self.rundir, self.state)
        self.assertEqual(orc.reconcile_run(self.state["id"])["status"], "paused")
        self.assertEqual(orc.resume_run(self.state["id"])["status"], "running")
        self.state = orc.load(self.state["id"])[1]
        mutated = []
        starts = []

        def must_not_spawn(*args, **kwargs):
            starts.append("child")
            raise AssertionError("a retry started after a late binding change")

        with patch.object(orc, "prompt_request",
                          side_effect=self.mutate_at_prompt(kind, mutated)), \
                patch.object(orc, "_spawn_guarded", side_effect=must_not_spawn):
            with self.assertRaisesRegex(RuntimeError, "Dispatch not attempted"):
                orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(mutated, [True])
        self.assertEqual(starts, [])
        self.state = orc.load(self.state["id"])[1]
        self.assertEqual(self.state["status"], "blocked")
        self.assertEqual(self.state["preflight_rejection"]["reason_code"],
                         "dispatch_binding_changed")
        self.assertEqual(self.state["writer_source_boundaries"]["0"]["signature"],
                         boundary["signature"])
        self.assertEqual(self.state["writer_source_boundaries"]["0"]["checkout_sha256"],
                         boundary["checkout_sha256"])
        self.assertEqual((self.project / "b.py").read_text(), "b = 'partial'\n")
        if kind == "mode":
            self.assertNotEqual(
                (self.project / "a.py").stat().st_mode & 0o777, mode_before)
        return boundary

    def test_manifest_change_before_correction_retry_blocks(self):
        self.blocked_retry("manifest")
        self.assertTrue(orc._integration_record_path(
            self.rundir, 0).read_bytes().endswith(b"\n"))

    def test_mode_change_before_correction_retry_blocks(self):
        self.blocked_retry("mode")


class ManifestAdmissionBindingTests(BoundaryBase):
    """Scope admission and the accepted digest share exactly one manifest read."""

    def prepare_sibling(self):
        WriterSourceBindingTests.prepare_sibling(self)

    def test_replaced_manifest_between_scope_check_and_acceptance_blocks(self):
        self.prepare_sibling()
        original_app = (self.project / "app.py").read_text()
        original_a = (self.project / "a.py").read_text()
        target = orc._integration_record_path(self.rundir, 0)
        real_scope = orc._parallel_record_scope_problem
        mutated = []

        def scope_then_replace(record, transaction, resolved):
            problem = real_scope(record, transaction, resolved)
            if not mutated:
                mutated.append(True)
                replacement = orc.read_json(target)
                replacement["writers"] = ["z"]
                replacement["patches"] = []
                orc.atomic_json(target, replacement)
            return problem

        starts = []

        def must_not_spawn(*args, **kwargs):
            starts.append("child")
            raise AssertionError(
                "a writer started after the admitted manifest was replaced")

        with patch.object(orc, "_parallel_record_scope_problem",
                          side_effect=scope_then_replace), \
                patch.object(orc, "_spawn_guarded", side_effect=must_not_spawn):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(mutated, [True])
        self.assertEqual(starts, [])
        self.state = orc.load(self.state["id"])[1]
        self.assertEqual(self.state["phase"], "implement")
        self.assertEqual(self.state["status"], "blocked")
        self.assertIn("changed after scope validation",
                      self.state["pause_reason"])
        self.assertNotIn("parallel_sibling_single", self.state)
        self.assertFalse(self.state.get("preflight_rejection"))
        self.assertEqual((self.project / "a.py").read_text(), original_a)
        self.assertEqual((self.project / "app.py").read_text(), original_app)
        self.assertEqual(orc.read_json(target)["writers"], ["z"],
                         "the replacement manifest was silently rewritten")
        self.assertNotEqual(self.state["phase"], "verify")

    def test_manifest_patch_outside_the_approved_scope_blocks(self):
        self.prepare_sibling()
        original_app = (self.project / "app.py").read_text()
        target = orc._integration_record_path(self.rundir, 0)
        record = orc.read_json(target)
        self.assertTrue(record["patches"])
        for item in record["patches"]:
            item["paths"] = ["unowned/" + (item.get("paths") or ["x"])[0]]
        orc.atomic_json(target, record)
        starts = []

        def must_not_run(*args, **kwargs):
            starts.append("model")
            raise AssertionError("a writer launched outside its approved scope")

        def must_not_spawn(*args, **kwargs):
            starts.append("child")
            raise AssertionError("a child launched outside the approved scope")

        with patch.object(orc, "call_model", side_effect=must_not_run), \
                patch.object(orc, "_spawn_guarded", side_effect=must_not_spawn):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(starts, [])
        self.state = orc.load(self.state["id"])[1]
        self.assertEqual(self.state["status"], "blocked")
        self.assertIn("unowned path", self.state["pause_reason"])
        self.assertEqual((self.project / "app.py").read_text(), original_app)
        self.assertEqual((self.project / "a.py").read_text(), "a = 1\n")
        self.assertNotIn("parallel_sibling_single", self.state)


class LaunchBookkeepingBindingTests(BoundaryBase):
    """A binding change during spawn bookkeeping is a proven no-child refusal."""

    def prepare_paid_sibling(self):
        WriterSourceBindingTests.prepare_sibling(self)
        self.state = orc.load(self.state["id"])[1]
        route = {"provider": "codex", "model": "fixture-primary",
                 "effort": "low", "billing": "api"}
        reviewer_route = {"provider": "codex", "model": "fixture-reviewer",
                          "effort": "low", "billing": "api"}
        grant = {"id": "bookkeeping-grant", "role": "implementer",
                 "run_id": self.state["id"],
                 "route_sha256": orc.route_authorization_sha(route),
                 "role_generation": 0, "used": 0, "max_dispatches": 1}
        unrelated = {"id": "unrelated-grant", "role": "reviewer",
                     "run_id": self.state["id"],
                     "route_sha256": orc.route_authorization_sha(reviewer_route),
                     "role_generation": 0, "used": 0, "max_dispatches": 1}
        self.state["model_routes"]["implementer"] = route
        self.state["route_authorizations"] = [grant, unrelated]
        orc.register_route_grant(self.rundir, grant)
        orc.register_route_grant(self.rundir, unrelated)
        orc.save(self.rundir, self.state)
        return route, grant

    def replace_manifest(self):
        target = orc._integration_record_path(self.rundir, 0)
        replacement = orc.read_json(target)
        replacement["writers"] = ["z"]
        replacement["patches"] = []
        orc.atomic_json(target, replacement)
        return target

    def flip_mode(self):
        path = self.project / "a.py"
        current = path.stat().st_mode & 0o777
        path.chmod(0o644 if current == 0o600 else 0o600)

    def mutate(self, kind):
        if kind == "manifest":
            self.replace_manifest()
        else:
            self.flip_mode()

    def journal_mutation(self, kind):
        real = orc.journal_event
        mutated = []

        def patched(run_dir, state, event, **values):
            result = real(run_dir, state, event, **values)
            if event == "route_grant_launched" and not mutated:
                mutated.append(True)
                self.mutate(kind)
            return result
        return patched, mutated

    def active_job_mutation(self, kind):
        real = orc.save
        mutated = []

        def patched(path, state):
            real(path, state)
            if (not mutated and Path(path).resolve() == Path(self.rundir).resolve()
                    and isinstance(state.get("active_job"), dict)
                    and state["active_job"].get("role") == "implementer"):
                mutated.append(True)
                self.mutate(kind)
        return patched, mutated

    def assert_no_child_refusal(self, mutated, starts):
        self.assertEqual(mutated, [True])
        self.assertEqual(starts, [])
        self.state = orc.load(self.state["id"])[1]
        self.assertEqual(self.state["phase"], "implement")
        self.assertEqual(self.state["status"], "blocked")
        rejection = self.state["preflight_rejection"]
        self.assertEqual(rejection["reason_code"], "dispatch_binding_changed")
        self.assertFalse(rejection["active_job_created"])
        self.assertFalse(rejection["model_calls_counted"])
        self.assertIsNone(self.state.get("active_job"))

    def assert_slot_refunded(self, grant_id="bookkeeping-grant"):
        ledger = orc.load_grant_ledger(self.rundir, run_id=self.state["id"])
        grant = ledger["grants"][grant_id]
        self.assertEqual(orc._grant_usage(grant), 0,
                         "a proven no-child refusal kept a paid charge")
        self.assertEqual(len(grant["reservations"]), 1)
        self.assertEqual(grant["reservations"][0]["state"], "released")
        self.assertTrue(grant["releases"][-1]["proven_no_exec"])
        unrelated = ledger["grants"]["unrelated-grant"]
        self.assertEqual(orc._grant_usage(unrelated), 0)
        self.assertEqual(unrelated["reservations"], [])

    def test_manifest_change_at_launch_intent_journal_blocks_without_charge(self):
        self.prepare_paid_sibling()
        original_app = (self.project / "app.py").read_text()
        original_a = (self.project / "a.py").read_text()
        patched, mutated = self.journal_mutation("manifest")
        starts = []

        def must_not_spawn(*args, **kwargs):
            starts.append("child")
            raise AssertionError("a child started after journal drift")

        with patch.object(orc, "journal_event", side_effect=patched), \
                patch.object(orc, "_spawn_guarded", side_effect=must_not_spawn):
            with self.assertRaisesRegex(RuntimeError, "Dispatch not attempted"):
                orc.advance(self.rundir, self.state, self.cfg)
        self.assert_no_child_refusal(mutated, starts)
        self.assert_slot_refunded()
        self.assertEqual((self.project / "a.py").read_text(), original_a)
        self.assertEqual((self.project / "app.py").read_text(), original_app)
        target = orc._integration_record_path(self.rundir, 0)
        self.assertEqual(orc.read_json(target)["writers"], ["z"],
                         "the replacement manifest was silently rewritten")
        self.assertNotEqual(self.state["phase"], "verify")

    def test_mode_change_at_active_job_persistence_blocks_without_charge(self):
        old_umask = os.umask(0o077)
        try:
            self.prepare_paid_sibling()
            mode_before = (self.project / "a.py").stat().st_mode & 0o777
            self.assertEqual(mode_before, 0o600,
                             "the restrictive umask did not shape the fixture")
            original_a = (self.project / "a.py").read_text()
            patched, mutated = self.active_job_mutation("mode")
            starts = []

            def must_not_spawn(*args, **kwargs):
                starts.append("child")
                raise AssertionError("a child started after active-job drift")

            with patch.object(orc, "save", side_effect=patched), \
                    patch.object(orc, "_spawn_guarded",
                                 side_effect=must_not_spawn):
                with self.assertRaisesRegex(RuntimeError,
                                            "Dispatch not attempted"):
                    orc.advance(self.rundir, self.state, self.cfg)
        finally:
            os.umask(old_umask)
        self.assert_no_child_refusal(mutated, starts)
        self.assert_slot_refunded()
        self.assertEqual((self.project / "a.py").read_text(), original_a)
        self.assertNotEqual(
            (self.project / "a.py").stat().st_mode & 0o777, mode_before)
        self.assertNotEqual(self.state["phase"], "verify")

    def test_approved_fallback_survives_a_late_binding_refusal(self):
        _route, _grant = self.prepare_paid_sibling()
        self.state = orc.load(self.state["id"])[1]
        self.state["route_authorizations"] = []
        self.state["status"] = "blocked"
        orc.save(self.rundir, self.state)
        self.assertTrue(orc.modify_locked(
            self.rundir, self.state, self.state["id"], "approve-fallback",
            role="implementer"))
        self.state = orc.load(self.state["id"])[1]
        fallback_before = copy.deepcopy(self.state["fallback_authorization"])
        self.assertIsInstance(fallback_before, dict)
        self.state["status"] = "paused"
        orc.atomic_json(self.rundir / "control.json", {"action": "pause"})
        orc.save(self.rundir, self.state)
        self.assertEqual(orc.resume_run(self.state["id"])["status"], "running",
                         self.state.get("pause_reason"))
        self.state = orc.load(self.state["id"])[1]
        original_app = (self.project / "app.py").read_text()
        patched, mutated = self.active_job_mutation("manifest")
        starts = []

        def must_not_spawn(*args, **kwargs):
            starts.append("child")
            raise AssertionError("a fallback child started after bookkeeping drift")

        with patch.object(orc, "save", side_effect=patched), \
                patch.object(orc, "_spawn_guarded", side_effect=must_not_spawn):
            with self.assertRaisesRegex(RuntimeError, "Dispatch not attempted"):
                orc.advance(self.rundir, self.state, self.cfg)
        self.assert_no_child_refusal(mutated, starts)
        self.assertEqual(self.state.get("fallback_authorization"),
                         fallback_before,
                         "an unspent one-shot fallback consent was lost")
        self.assertEqual((self.project / "app.py").read_text(), original_app)
        ledger = orc.load_grant_ledger(self.rundir, run_id=self.state["id"])
        grant = ledger["grants"]["bookkeeping-grant"]
        self.assertEqual(orc._grant_usage(grant), 0)
        self.assertEqual(grant["reservations"], [],
                         "a subscription fallback consumed the paid slot")
        self.assertNotEqual(self.state["phase"], "verify")

    def test_unchanged_paid_single_writer_still_launches_once(self):
        self.prepare_paid_sibling()
        starts = []
        with patch.object(
                orc, "_spawn_guarded",
                side_effect=StoppedWriterSourceTests.finishing_transport(
                    self, starts)):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(starts, ["fixture-primary"])
        self.state = orc.load(self.state["id"])[1]
        self.assertEqual(self.state["phase"], "verify",
                         self.state.get("pause_reason"))
        self.assertEqual((self.project / "b.py").read_text(), "b = 2\n")
        ledger = orc.load_grant_ledger(self.rundir, run_id=self.state["id"])
        grant = ledger["grants"]["bookkeeping-grant"]
        self.assertEqual(orc._grant_usage(grant), 1)
        self.assertEqual(grant["reservations"][0]["state"], "launched")


class ReconcileSourceAuthorityTests(BoundaryBase):
    """Reconciliation contains the process without rewriting source authority."""

    def failed_attempt(self):
        WriterSourceBindingTests.prepare_sibling(self)
        attempts = []
        with patch.object(
                orc, "_spawn_guarded",
                side_effect=StoppedWriterSourceTests.failing_transport(
                    self, attempts)):
            with self.assertRaisesRegex(RuntimeError, "exited 1"):
                orc.advance(self.rundir, self.state, self.cfg)
        self.state = orc.load(self.state["id"])[1]
        self.assertEqual(attempts, ["fixture-primary"])
        return self.state["writer_source_boundaries"]["0"]

    def test_edit_before_reconcile_preserves_boundary_and_blocks_resume(self):
        boundary = self.failed_attempt()
        original_app = (self.project / "app.py").read_text()
        (self.project / "app.py").write_text("value = 99\n")
        self.state["status"] = "uncertain"
        orc.save(self.rundir, self.state)

        reconciled = orc.reconcile_run(self.state["id"])
        self.assertEqual(reconciled["status"], "paused")
        self.state = orc.load(self.state["id"])[1]
        preserved = self.state["writer_source_boundaries"]["0"]
        self.assertEqual(preserved["phase"], "failure")
        self.assertEqual(preserved["signature"], boundary["signature"])
        self.assertEqual(preserved["checkout_sha256"],
                         boundary["checkout_sha256"])
        conflict = self.state["source_boundary_conflict"]
        self.assertEqual(conflict["expected"]["signature"], boundary["signature"])
        self.assertNotEqual(conflict["observed"]["signature"],
                            boundary["signature"])
        self.assertEqual(conflict["expected"]["checkout_sha256"],
                         boundary["checkout_sha256"])
        self.assertIn("source blocker", self.state["pause_reason"])

        starts = []

        def must_not_spawn(*args, **kwargs):
            starts.append("child")
            raise AssertionError("a replacement started over an attributed edit")

        with patch.object(orc, "_spawn_guarded", side_effect=must_not_spawn):
            resumed = orc.resume_run(self.state["id"])
            self.assertEqual(resumed["status"], "blocked")
            self.state = orc.load(self.state["id"])[1]
            self.assertIn("still differs", self.state["pause_reason"])
            payload = orc.stage_run(self.state["id"])
            self.assertFalse(payload["ok"])
        self.assertEqual(starts, [])
        self.state = orc.load(self.state["id"])[1]
        self.assertEqual(self.state["phase"], "implement")
        self.assertEqual(self.state["status"], "blocked")
        self.assertEqual((self.project / "app.py").read_text(), "value = 99\n")
        self.assertEqual((self.project / "b.py").read_text(), "b = 'partial'\n")

        (self.project / "app.py").write_text(original_app)
        self.assertEqual(orc.resume_run(self.state["id"])["status"], "running")
        self.state = orc.load(self.state["id"])[1]
        resumed_starts = []
        with patch.object(
                orc, "_spawn_guarded",
                side_effect=StoppedWriterSourceTests.finishing_transport(
                    self, resumed_starts)):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(resumed_starts, ["fixture-primary"])
        self.state = orc.load(self.state["id"])[1]
        self.assertEqual(self.state["phase"], "verify",
                         self.state.get("pause_reason"))
        job = [item for item in self.state["completed_jobs"]
               if item.get("role") == "implementer"][-1]
        dispatch = orc.read_json(Path(job["path"]) / "dispatch.json")
        self.assertEqual(orc.signature(dispatch["source"]),
                         boundary["signature"])


class ReviewerFallbackPreflightTests(BoundaryBase):
    """Every fallback-capable pending role resolves its effective route first."""

    def reviewer_state(self):
        primary = {"provider": "opencode",
                   "model": "opencode-go/reviewer-fixture",
                   "effort": "low", "billing": "api",
                   "fallback_route": {"provider": "codex",
                                      "model": "fixture-review-fallback",
                                      "effort": "low",
                                      "billing": "subscription"}}
        self.state.update({"phase": "review", "status": "blocked",
                           "model_routes": {"reviewer": primary},
                           "active_job": None, "active_check": None})
        orc.save(self.rundir, self.state)
        with patch.object(orc, "require_human_operator",
                          return_value={"actor": "test", "method": "test"}):
            approved = orc.approve_worker_fallback_run("test-run00", "reviewer")
        self.assertTrue(approved["ok"])
        self.state = orc.load(self.state["id"])[1]
        self.state["status"] = "paused"
        orc.atomic_json(self.rundir / "control.json", {"action": "pause"})
        orc.save(self.rundir, self.state)

    def which_without(self, missing):
        real = shutil.which

        def fake(command, path=None):
            if command in missing:
                return None
            return real(command, path=path)
        return fake

    def test_reviewer_resume_uses_the_selected_fallback(self):
        self.reviewer_state()
        with patch.object(orc.shutil, "which",
                          side_effect=self.which_without({"opencode"})):
            resumed = orc.resume_run(self.state["id"])
        self.assertEqual(resumed["status"], "running",
                         self.state.get("pause_reason"))
        self.state = orc.load(self.state["id"])[1]
        preflight = self.state["permission_preflight"]
        self.assertTrue(any(item.get("kind") == "route_executable"
                            and item.get("role") == "reviewer"
                            and item.get("primary_deferred")
                            for item in preflight["advisories"]), preflight)
        self.assertTrue(any(item.get("kind") == "route_grant"
                            and item.get("role") == "reviewer"
                            and item.get("primary_deferred")
                            for item in preflight["advisories"]), preflight)
        self.assertFalse(any(item.get("kind") in {"route_executable",
                                                  "route_grant"}
                             and item.get("role") == "reviewer"
                             for item in preflight["missing"]), preflight)
        seen = []

        def transport(command, cwd, env, log_stream, launch_file=None,
                      stdin_data=None, error_stream=None, stdin_fifo=None):
            seen.append((command[command.index("--model") + 1],
                         "read-only" in command))
            out = command[command.index("--output-last-message") + 1]
            Path(out).write_text(json.dumps({
                "contract_version": 2, "status": "complete",
                "summary": "reviewed on the fallback", "files": [],
                "tests": [], "evidence": ["app.py"], "unknowns": [],
                "blocker": "", "findings": []}))
            proc = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(0.3)"],
                start_new_session=True)
            if launch_file:
                orc.atomic_json(Path(launch_file),
                                {"guard": orc.process_identity(proc.pid)})
            return proc, None

        self.state["status"] = "running"
        orc.save(self.rundir, self.state)
        with patch.object(orc.shutil, "which",
                          side_effect=self.which_without({"opencode"})), \
                patch.object(orc, "_spawn_guarded", side_effect=transport):
            report, _job = orc.call_model(
                self.rundir, self.state, self.cfg, "reviewer", "reviewer",
                "review", self.project)
        self.assertEqual(seen, [("fixture-review-fallback", True)])
        self.assertEqual(report["status"], "complete")
        self.assertIsNone(self.state.get("worker_fallback_authorization"))

    def test_missing_selected_reviewer_fallback_blocks_resume(self):
        self.reviewer_state()
        with patch.object(orc.shutil, "which",
                          side_effect=self.which_without({"opencode", "codex"})):
            resumed = orc.resume_run(self.state["id"])
        self.assertEqual(resumed["status"], "blocked")
        self.state = orc.load(self.state["id"])[1]
        missing = self.state["permission_preflight"]["missing"]
        self.assertTrue(any(item.get("kind") == "route_executable"
                            and item.get("role") == "reviewer"
                            and item.get("selected_route") == "fallback"
                            for item in missing), missing)
        self.assertIsInstance(self.state.get("worker_fallback_authorization"),
                              dict)


if __name__ == "__main__":
    unittest.main()
