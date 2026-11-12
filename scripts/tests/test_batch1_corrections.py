"""Acceptance-blocking corrections for Batch 1 (review P0/P1)."""
from __future__ import annotations

import concurrent.futures
import contextlib
import io
import json
import os
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import test_orchestrator as baseline

orc = baseline.orc


class Batch1Corrections(unittest.TestCase):
    def setUp(self):
        baseline.ControlTests.setUp(self)
        self.runs = self.root / "runs"

    def _repo(self, name):
        base = self.root / name
        base.mkdir(parents=True, exist_ok=True)
        return baseline.setup_repo(base)

    def _sleep(self, code="import time; time.sleep(30)"):
        return subprocess.Popen([sys.executable, "-c", code], start_new_session=True)

    def _identity(self, proc):
        ident = orc.process_identity(proc.pid)
        self.assertIsNotNone(ident)
        return ident

    def _save(self, state=None, folder=None):
        orc.save(folder or self.rundir, state or self.state)

    def _conflicting_run(self, root, run_id="other-run-01", status="running"):
        folder = root / run_id
        folder.mkdir(parents=True, exist_ok=True)
        state = dict(self.state)
        state.update(id=run_id, project=str(self.project), status=status,
                     phase="plan", plan=None, active_job=None, active_check=None)
        orc.atomic_json(folder / "state.json", state)
        return folder, state

    # ------------------------------------------------------------------
    # P0-1: every execution path enforces checkout ownership
    # ------------------------------------------------------------------

    def test_serve_refuses_conflicting_checkout_without_advancing(self):
        self._conflicting_run(self.runs)
        before = (self.rundir / "state.json").read_bytes()
        def fake_advance(run_dir, state, cfg):
            state["status"] = "complete"
        with patch.object(orc, "advance", side_effect=fake_advance) as advance, \
                contextlib.redirect_stdout(io.StringIO()) as out:
            orc.serve("test-run00")
        advance.assert_not_called()
        self.assertIn("checkout_conflict", out.getvalue())
        self.assertEqual((self.rundir / "state.json").read_bytes(), before)

    def test_cli_resume_and_approvals_refuse_conflict(self):
        self._conflicting_run(self.runs)
        self.state["status"] = "paused"
        self._save()
        with patch.object(orc, "detach") as detach:
            with self.assertRaises(orc.CheckoutOwnedError):
                orc.modify("test-run00", "resume")
            detach.assert_not_called()
        self.state["status"] = "awaiting_plan_approval"
        self._save()
        with self.assertRaises(orc.CheckoutOwnedError):
            orc.modify_locked(self.rundir, self.state, "test-run00", "approve-plan")
        self.state["status"] = "blocked"
        self.state["phase"] = "implement"
        self._save()
        with self.assertRaises(orc.CheckoutOwnedError):
            orc.modify_locked(self.rundir, self.state, "test-run00", "approve-fallback",
                              role="implementer")

    def test_advance_refuses_conflict_directly(self):
        self._conflicting_run(self.runs)
        with self.assertRaises(orc.CheckoutOwnedError):
            orc.advance(self.rundir, self.state, self.cfg)

    def test_explore_refuses_conflict_before_model_call(self):
        self._conflicting_run(self.runs)
        self.state.update(explorer_policy="on_demand", status="running", phase="plan",
                          active_job={"id": "parent-job", "role": "architect",
                                      "status": "running"})
        with patch.object(orc, "load", return_value=(self.rundir, self.state)), \
                patch.object(orc, "call_model") as call:
            with self.assertRaises(orc.CheckoutOwnedError):
                orc.explore(SimpleNamespace(run="test-run00", task="inspect",
                                            parent_job="parent-job"))
            call.assert_not_called()

    def test_stage_conflict_is_actionable_and_not_stage_loop(self):
        self._conflicting_run(self.runs)
        result = orc.stage_run("test-run00")
        self.assertFalse(result["ok"])
        self.assertIn("other-run-01", result["error"])
        self.assertIn("retire", result["error"])
        self.assertEqual(result["next_action"], "orchestrator_runs")
        self.assertEqual(result["next"]["action"], "orchestrator_runs")
        self.assertEqual(result["status"], "checkout_conflict")

    def test_legacy_serve_conflict_does_not_write_state(self):
        root = self.root / "legacy-runs"
        root.mkdir(parents=True)
        for name in ("legacy-a", "legacy-b"):
            folder = root / name
            folder.mkdir()
            state = dict(self.state)
            state.update(id=name, project=str(self.project), status="running",
                         phase="plan", plan=None, active_job=None, active_check=None)
            orc.atomic_json(folder / "state.json", state)
        before = (root / "legacy-a/state.json").read_bytes()
        with patch.object(orc, "DEFAULT_STATE", root), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            orc.serve("legacy-a")
        self.assertEqual((root / "legacy-a/state.json").read_bytes(), before)
        self.assertFalse((root / "legacy-a/supervisor.lock").exists())
        self.assertIn("checkout_conflict", out.getvalue())

    # ------------------------------------------------------------------
    # P0-2: explicit retirement and conflict resolution
    # ------------------------------------------------------------------

    def test_retire_inactive_run_preserves_artifacts_and_releases_lease(self):
        project = self._repo("retire-project")
        root = self.root / "retire-runs"
        with patch.object(orc, "DEFAULT_STATE", root):
            run_id, folder, state = orc.create_run(project=str(project), goal="x",
                                                   skip_doctor=True)
            artifact = folder / "jobs" / "report.json"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text('{"keep":true}')
            before_artifact = artifact.read_bytes()
            state.update(status="blocked", completed_jobs=[{"id": "done"}],
                         accepted_batches=[{"index": 0}])
            orc.save(folder, state)
            result = orc.retire_run(run_id, "abandon remaining work", "no further work")
            self.assertEqual(result["status"], "cancelled")
            saved = orc.read_json(folder / "state.json")
            self.assertEqual(saved["retirement"]["mode"], "administrative_abandonment")
            self.assertEqual(saved["completed_jobs"], [{"id": "done"}])
            self.assertEqual(artifact.read_bytes(), before_artifact)
            self.assertFalse((orc.leases_root() / f"{orc.checkout_identity(project)['key']}.json").exists())

    def test_retire_refuses_live_worker(self):
        proc = self._sleep()
        try:
            ident = self._identity(proc)
            self.state["active_job"] = {"id": "live", "role": "implementer",
                                        "status": "running", **ident}
            self._save()
            with self.assertRaisesRegex(RuntimeError, "not proven stopped"):
                orc.retire_run("test-run00", "reason", "ack")
        finally:
            proc.kill()
            proc.wait(timeout=5)

    def test_retire_refuses_process_carrying_run_identity(self):
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                start_new_session=True,
                                env={**os.environ, "ABDULLAH_RUN_ID": "test-run00"})
        try:
            with self.assertRaisesRegex(RuntimeError, "run identity"):
                orc.retire_run("test-run00", "reason", "ack")
        finally:
            proc.kill()
            proc.wait(timeout=5)

    def test_retire_refuses_missing_identity(self):
        self.state["active_check"] = {"argv": ["true"], "log": "log"}
        self._save()
        with self.assertRaisesRegex(RuntimeError, "not proven stopped"):
            orc.retire_run("test-run00", "reason", "ack")

    def test_retire_and_adopt_sanatry_state_copies(self):
        actual = Path.home() / ".local/state/abdullah-orchestrator/runs"
        names = ("20261109T132000-39d6dd12", "20261110T034941-4419f301")
        if not all((actual / name / "state.json").is_file() for name in names):
            self.skipTest("Sanatry run states are not present on this machine")
        hashes = {name: orc.hashlib.sha256((actual / name / "state.json").read_bytes()).hexdigest()
                  for name in names}
        root = self.root / "sanatry-copies"
        root.mkdir(parents=True)
        for name in names:
            folder = root / name
            folder.mkdir()
            state = orc.read_json(actual / name / "state.json")
            orc.atomic_json(folder / "state.json", state)
            (folder / "artifact.txt").write_text("preserved")
        with patch.object(orc, "DEFAULT_STATE", root):
            retired = orc.retire_run(names[0], "superseded by active run",
                                     "abandon blocked plan; preserve reports")
            self.assertEqual(retired["status"], "cancelled")
            adopted = orc.adopt_run(names[1])
            self.assertTrue(adopted["ok"])
        self.assertEqual((root / names[0] / "artifact.txt").read_text(), "preserved")
        self.assertEqual((root / names[1] / "artifact.txt").read_text(), "preserved")
        for name in names:
            self.assertEqual(orc.hashlib.sha256((actual / name / "state.json").read_bytes()).hexdigest(),
                             hashes[name])

    def test_checkout_recover_orphan_and_audit(self):
        project = self._repo("orphan-project")
        identity = orc.checkout_identity(project)
        dead = baseline.dead_process_identity()
        record = {"run_id": "orphan-run", "lease_id": "x", "project": str(project),
                  "checkout_key": identity["key"], "inode": identity["inode"],
                  "status": "initializing", "owner_pid": dead["pid"],
                  "owner_identity": dead, "created_at": orc.now()}
        orc.atomic_json(orc._lease_path(identity["key"]), record)
        result = orc.checkout_recover(project, "orphan-run", "owner vanished",
                                      "inspected no state and no process")
        self.assertTrue(result["ok"])
        self.assertFalse(orc._lease_path(identity["key"]).exists())
        self.assertTrue(Path(result["audit"]).is_file())

    def test_checkout_recover_refuses_live_owner(self):
        project = self._repo("live-owner-project")
        identity = orc.checkout_identity(project)
        proc = self._sleep()
        try:
            proc_ident = self._identity(proc)
            record = {"run_id": "live-owner", "lease_id": "x", "project": str(project),
                      "checkout_key": identity["key"], "inode": identity["inode"],
                      "status": "initializing", "owner_pid": proc.pid,
                      "owner_identity": proc_ident, "created_at": orc.now()}
            orc.atomic_json(orc._lease_path(identity["key"]), record)
            with self.assertRaisesRegex(RuntimeError, "still alive"):
                orc.checkout_recover(project, "live-owner", "reason", "ack")
        finally:
            proc.kill()
            proc.wait(timeout=5)

    def test_different_state_roots_use_different_registries(self):
        shared = self.root / "shared-parent"
        with patch.object(orc, "DEFAULT_STATE", shared / "runs-a"):
            first = orc.leases_root()
            self.assertTrue(first.resolve().is_relative_to(self.root.resolve()))
        with patch.object(orc, "DEFAULT_STATE", shared / "runs-b"):
            second = orc.leases_root()
            self.assertTrue(second.resolve().is_relative_to(self.root.resolve()))
        self.assertNotEqual(first, second)

    def test_checkout_status_is_read_only(self):
        project = self._repo("status-project")
        with patch.object(orc, "DEFAULT_STATE", self.root / "status-runs"):
            result = orc.checkout_status(project)
            self.assertTrue(result["ok"])
            self.assertFalse(orc.leases_root().exists())

    # ------------------------------------------------------------------
    # P0-3: initializing, orphaned, and concurrent admission
    # ------------------------------------------------------------------

    def test_concurrent_create_identifies_owner_not_corruption(self):
        project = self._repo("concurrent-correction-project")
        root = self.root / "concurrent-correction-runs"
        def start(index):
            try:
                return ("ok", orc.create_run(project=str(project), goal=f"g{index}",
                                             skip_doctor=True)[0])
            except Exception as exc:
                return ("error", str(exc))
        with patch.object(orc, "DEFAULT_STATE", root):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results = [future.result() for future in
                           [pool.submit(start, 0), pool.submit(start, 1)]]
        winners = [value for status, value in results if status == "ok"]
        errors = [value for status, value in results if status == "error"]
        self.assertEqual(len(winners), 1, results)
        self.assertEqual(len(errors), 1, results)
        self.assertIn(winners[0], errors[0])
        self.assertNotIn("no readable state", errors[0])
        self.assertNotIn("corrupt", errors[0].lower())

    def test_initializing_record_is_retry_not_corruption(self):
        project = self._repo("init-project")
        identity = orc.checkout_identity(project)
        live = self._sleep()
        try:
            record = {"run_id": "init-owner", "lease_id": "x", "project": str(project),
                      "checkout_key": identity["key"], "inode": identity["inode"],
                      "status": "initializing", "owner_pid": live.pid,
                      "owner_identity": self._identity(live), "created_at": orc.now()}
            orc.atomic_json(orc._lease_path(identity["key"]), record)
            with self.assertRaises(orc.CheckoutOwnedError) as caught:
                orc.acquire_checkout_lease(project, "new-run")
            self.assertEqual(caught.exception.state, "initializing")
            self.assertIn("retry", str(caught.exception).lower())
        finally:
            live.kill()
            live.wait(timeout=5)

    def test_orphaned_record_points_to_recovery(self):
        project = self._repo("orphan-record-project")
        identity = orc.checkout_identity(project)
        dead = baseline.dead_process_identity()
        record = {"run_id": "orphan-owner", "lease_id": "x", "project": str(project),
                  "checkout_key": identity["key"], "inode": identity["inode"],
                  "status": "initializing", "owner_pid": dead["pid"],
                  "owner_identity": dead, "created_at": orc.now()}
        orc.atomic_json(orc._lease_path(identity["key"]), record)
        with self.assertRaises(orc.CheckoutOwnedError) as caught:
            orc.acquire_checkout_lease(project, "new-run")
        self.assertEqual(caught.exception.state, "orphaned")
        self.assertIn("checkout-recover", str(caught.exception))

    # ------------------------------------------------------------------
    # P0-4: crash windows and launch identity
    # ------------------------------------------------------------------

    def test_job_identity_merges_launch_record(self):
        launch = self.root / "launch.json"
        ident = orc.process_identity(os.getpid())
        orc.atomic_json(launch, {"phase": "running", "guard": ident,
                                 "guard_pid": os.getpid()})
        merged = orc.job_identity({"launch_file": str(launch)})
        self.assertEqual(merged["pid"], ident["pid"])
        self.assertEqual(merged["pid_start"], ident["pid_start"])

    def test_reconcile_launch_missing_requires_evidence_and_audits(self):
        self.state["active_check"] = {"argv": ["true"], "log": "log",
                                      "launch_file": str(self.root / "missing-launch.json")}
        self.state["status"] = "uncertain"
        self._save()
        with self.assertRaisesRegex(RuntimeError, "launch-missing"):
            orc.reconcile_run("test-run00")
        with self.assertRaisesRegex(RuntimeError, "requires --evidence"):
            orc.reconcile_run("test-run00", launch_missing=True, evidence="")
        result = orc.reconcile_run("test-run00", launch_missing=True,
                                   evidence="inspected: no launch file, no matching process")
        self.assertEqual(result["status"], "paused")
        self.assertIsNone(orc.read_json(self.rundir / "state.json")["active_check"])
        audits = list((self.rundir / "jobs").glob("reconciliation-launch-*.json"))
        self.assertTrue(audits)

    def test_crash_before_identity_persistence_recovers_from_launch_file(self):
        batch = {"title": "check", "checks": [[sys.executable, "-c",
                                              "import time; time.sleep(5)"]]}
        real_wait = orc._wait_launch
        def wait_but_do_not_record(path, timeout=2.0):
            real_wait(path, timeout)
            return None
        with patch.object(orc, "_wait_launch", side_effect=wait_but_do_not_record), \
                patch.object(orc, "process_identity", return_value=None), \
                patch.object(orc, "control", side_effect=KeyboardInterrupt("crash")):
            with self.assertRaises(KeyboardInterrupt):
                orc.run_checks(self.rundir, self.state, self.cfg, self.project, batch)
        saved = orc.read_json(self.rundir / "state.json")
        check = saved["active_check"]
        self.assertTrue(check.get("launch_file"))
        merged = orc.job_identity(check)
        self.assertIsNotNone(merged.get("pid_start"))
        saved["status"] = "uncertain"
        orc.save(self.rundir, saved)
        result = orc.reconcile_run("test-run00")
        self.assertEqual(result["status"], "paused")

    def test_worker_crash_before_identity_recovers_from_launch_file(self):
        fake = self.root / "codex"
        fake.write_text("#!/bin/sh\nsleep 5\n")
        fake.chmod(0o755)
        real_wait = orc._wait_launch
        def wait_but_do_not_record(path, timeout=2.0):
            real_wait(path, timeout)
            return None
        with patch.dict(os.environ, {"PATH": str(self.root) + ":" + os.environ["PATH"],
                                     "OPENAI_API_KEY": ""}), \
                patch.object(orc, "_wait_launch", side_effect=wait_but_do_not_record), \
                patch.object(orc, "process_identity", return_value=None), \
                patch.object(orc, "control", side_effect=KeyboardInterrupt("crash")):
            with self.assertRaises(KeyboardInterrupt):
                orc.call_model(self.rundir, self.state, self.cfg, "architect",
                               "plan", "prompt", self.project)
        saved = orc.read_json(self.rundir / "state.json")
        job = saved["active_job"]
        self.assertTrue(job.get("launch_file"))
        merged = orc.job_identity(job)
        self.assertIsNotNone(merged.get("pid_start"))
        saved["status"] = "uncertain"
        orc.save(self.rundir, saved)
        result = orc.reconcile_run("test-run00")
        self.assertEqual(result["status"], "paused")

    def test_explorer_tracker_recovers_launch_identity(self):
        tracker = self.rundir / "explorations" / "tracker"
        tracker.mkdir(parents=True)
        dead = baseline.dead_process_identity()
        launch = tracker / "launch.json"
        orc.atomic_json(launch, {"phase": "running", "guard": dead,
                                 "guard_pid": dead["pid"]})
        orc.atomic_json(tracker / "state.json", {
            "host": "codex", "project": str(self.project),
            "active_job": {"id": "e-dead", "role": "explorer", "kind": "explorer",
                           "launch_file": str(launch), "status": "running"},
            "completed_jobs": [], "failed_jobs": [], "explorer_calls": 1})
        orc.reconcile_explorer("test-run00")
        self.assertIsNone(orc.read_json(tracker / "state.json")["active_job"])

    def test_explorer_launch_missing_reconciles_with_audit(self):
        tracker = self.rundir / "explorations" / "tracker"
        tracker.mkdir(parents=True)
        orc.atomic_json(tracker / "state.json", {
            "host": "codex", "project": str(self.project),
            "active_job": {"id": "e-broken", "role": "explorer", "kind": "explorer",
                           "launch_file": str(self.root / "missing-explorer-launch.json"),
                           "status": "running"},
            "completed_jobs": [], "failed_jobs": [], "explorer_calls": 1})
        with self.assertRaisesRegex(RuntimeError, "launch-missing"):
            orc.reconcile_explorer("test-run00")
        orc.reconcile_explorer("test-run00", launch_missing=True,
                               evidence="inspected: no launch file or process")
        self.assertIsNone(orc.read_json(tracker / "state.json")["active_job"])

    # ------------------------------------------------------------------
    # P0-6: escaped verification processes
    # ------------------------------------------------------------------

    def test_double_fork_setsid_escape_is_detected_and_fails_verification(self):
        code = (
            "import os, time\n"
            "if os.fork() == 0:\n"
            "    os.setsid()\n"
            "    if os.fork() == 0:\n"
            "        time.sleep(30)\n"
            "    os._exit(0)\n"
            "os._exit(0)\n"
        )
        batch = {"title": "escape", "checks": [[sys.executable, "-c", code]]}
        evidence = orc.run_checks(self.rundir, self.state, self.cfg, self.project, batch)
        self.assertFalse(evidence["passed"])
        self.assertIn("escaped execution", evidence.get("error", ""))
        containment = evidence["containment"][0]
        escaped = containment["escaped_processes"]
        self.assertTrue(escaped)
        for item in escaped:
            try:
                os.kill(item["pid"], signal.SIGKILL)
            except OSError:
                pass
        time.sleep(0.2)
        self.assertTrue(all(not orc._identity_alive({"pid": item["pid"],
                                                     "pid_start": item["starttime"]})
                            for item in escaped))

    # ------------------------------------------------------------------
    # P0-7: side effects and next action
    # ------------------------------------------------------------------

    def test_paused_and_final_stage_do_not_create_registry(self):
        for status in ("paused", "complete"):
            with self.subTest(status=status):
                root = self.root / f"no-side-effect-{status}"
                folder = root / "phase-run"
                folder.mkdir(parents=True)
                state = dict(self.state)
                state.update(id="phase-run", status=status, project=str(self.project),
                             active_job=None, active_check=None)
                orc.atomic_json(folder / "state.json", state)
                with patch.object(orc, "DEFAULT_STATE", root):
                    orc.stage_run("phase-run")
                self.assertFalse(orc.leases_root().exists())

    # ------------------------------------------------------------------
    # P1 Explorer details
    # ------------------------------------------------------------------

    def test_explorer_requires_active_executing_parent(self):
        self.state.update(explorer_policy="on_demand", status="running", phase="plan",
                          active_job={"id": "parent-job", "role": "architect",
                                      "status": "uncertain"})
        with patch.object(orc, "load", return_value=(self.rundir, self.state)), \
                patch.object(orc, "call_model") as call:
            with self.assertRaisesRegex(RuntimeError, "active Architect job"):
                orc.explore(SimpleNamespace(run="test-run00", task="inspect",
                                            parent_job="parent-job"))
            call.assert_not_called()

    def test_explorer_environment_mismatch_is_refused(self):
        self.state.update(explorer_policy="on_demand", status="running", phase="plan",
                          active_job={"id": "parent-job", "role": "architect",
                                      "status": "running"})
        with patch.object(orc, "load", return_value=(self.rundir, self.state)), \
                patch.dict(os.environ, {"ABDULLAH_PARENT_JOB": "different-job"}), \
                patch.object(orc, "call_model") as call:
            with self.assertRaisesRegex(RuntimeError, "disagrees"):
                orc.explore(SimpleNamespace(run="test-run00", task="inspect",
                                            parent_job="parent-job"))
            call.assert_not_called()

    def test_explorer_run_and_stage_environment_mismatch(self):
        self.state.update(explorer_policy="on_demand", status="running", phase="plan",
                          active_job={"id": "parent-job", "role": "architect",
                                      "status": "running"})
        base_env = {"ABDULLAH_PARENT_JOB": "parent-job", "ABDULLAH_STAGE": "plan"}
        with patch.object(orc, "load", return_value=(self.rundir, self.state)), \
                patch.dict(os.environ, {**base_env, "ABDULLAH_RUN_ID": "other-run"}):
            with self.assertRaisesRegex(RuntimeError, "different run"):
                orc.explore(SimpleNamespace(run="test-run00", task="inspect",
                                            parent_job="parent-job"))
        with patch.object(orc, "load", return_value=(self.rundir, self.state)), \
                patch.dict(os.environ, {**base_env, "ABDULLAH_RUN_ID": "test-run00",
                                        "ABDULLAH_STAGE": "decision"}):
            with self.assertRaisesRegex(RuntimeError, "does not match run phase"):
                orc.explore(SimpleNamespace(run="test-run00", task="inspect",
                                            parent_job="parent-job"))

    def test_concurrent_explorer_dispatch_and_budget(self):
        self.state.update(explorer_policy="on_demand", status="running", phase="plan",
                          active_job={"id": "parent-job", "role": "architect",
                                      "status": "running"})
        report = {"status": "complete", "summary": "ok", "files": [], "tests": [],
                  "evidence": [], "unknowns": [], "blocker": ""}
        def fake_call(*args, **kwargs):
            time.sleep(0.4)
            return report, {"id": "e1"}
        def call_explore():
            try:
                orc.explore(SimpleNamespace(run="test-run00", task="inspect",
                                            parent_job="parent-job"))
                return "ok"
            except Exception as exc:
                return str(exc)
        with patch.object(orc, "load", return_value=(self.rundir, self.state)), \
                patch.object(orc, "call_model", side_effect=fake_call), \
                contextlib.redirect_stdout(io.StringIO()):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results = [future.result() for future in
                           [pool.submit(call_explore), pool.submit(call_explore)]]
        self.assertEqual(sum(1 for item in results if item == "ok"), 1, results)
        self.assertEqual(sum(1 for item in results if item != "ok"), 1, results)
        tracker = orc.read_json(self.rundir / "explorations" / "tracker" / "state.json")
        self.assertEqual(tracker.get("explorer_calls"), 1)

    def test_missing_explorer_tracker_state_is_actionable(self):
        with self.assertRaisesRegex(RuntimeError, "tracker state is missing"):
            orc.reconcile_explorer("test-run00")

    def test_test_state_root_is_isolated_tripwire(self):
        self.assertTrue(Path(orc.DEFAULT_STATE).resolve().is_relative_to(self.root.resolve()))
        self.assertTrue(orc.leases_root().resolve().is_relative_to(self.root.resolve()))


if __name__ == "__main__":
    unittest.main()
