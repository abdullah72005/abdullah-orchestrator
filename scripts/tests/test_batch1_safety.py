"""Batch 1 regression tests: fail-closed ownership, interruption, Explorer policy."""
from __future__ import annotations

import concurrent.futures
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import test_orchestrator as baseline

orc = baseline.orc


class Batch1Safety(unittest.TestCase):
    def setUp(self):
        baseline.ControlTests.setUp(self)
        self.state_patch = patch.object(orc, "DEFAULT_STATE", self.root / "runs")
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)

    def _save(self):
        orc.save(self.rundir, self.state)

    def _sleeping_process(self, code="import time; time.sleep(30)"):
        return subprocess.Popen([sys.executable, "-c", code], start_new_session=True)

    def _repo(self, name):
        base = self.root / name
        base.mkdir(parents=True, exist_ok=True)
        return baseline.setup_repo(base)

    def _check_identity(self, proc):
        ident = orc.process_identity(proc.pid)
        self.assertIsNotNone(ident)
        return ident

    # ------------------------------------------------------------------
    # AO-01: unverified verification interruption must not be resumable
    # ------------------------------------------------------------------

    def test_interrupt_reused_pid_check_stays_uncertain(self):
        proc = self._sleeping_process()
        try:
            ident = self._check_identity(proc)
            self.state["active_check"] = {
                "argv": ["true"], "log": str(self.rundir / "check.log"),
                "candidate_hash": "candidate",
                "pid": proc.pid, "pid_start": ident["pid_start"] + 1,
                "pgid": ident["pgid"], "sid": ident["sid"], "process": ident,
            }
            self._save()
            result = orc.interrupt_run("test-run00", "test interruption")
            self.assertFalse(result["termination"]["stopped"])
            saved = orc.read_json(self.rundir / "state.json")
            self.assertEqual(saved["status"], "uncertain")
            self.assertIsNotNone(saved["active_check"])
            with self.assertRaisesRegex(RuntimeError, "Uncertain"):
                orc.resume_run("test-run00")
        finally:
            proc.kill()
            proc.wait(timeout=5)

    def test_interrupt_missing_identity_check_stays_uncertain(self):
        self.state["active_check"] = {
            "argv": ["true"], "log": str(self.rundir / "check.log"),
            "candidate_hash": "candidate",
        }
        self._save()
        result = orc.interrupt_run("test-run00", "test interruption")
        self.assertFalse(result["termination"]["stopped"])
        saved = orc.read_json(self.rundir / "state.json")
        self.assertEqual(saved["status"], "uncertain")
        self.assertIsNotNone(saved["active_check"])
        self.assertIn("no_process_identity",
                      json.dumps(saved["interruptions"][-1]["termination"]))

    def test_interrupt_verified_check_pauses_and_requires_rerun(self):
        proc = self._sleeping_process()
        ident = self._check_identity(proc)
        self.state["active_check"] = {
            "argv": ["true"], "log": str(self.rundir / "check.log"),
            "candidate_hash": "candidate",
            "pid": proc.pid, "pid_start": ident["pid_start"],
            "pgid": ident["pgid"], "sid": ident["sid"], "process": ident,
        }
        self._save()
        try:
            result = orc.interrupt_run("test-run00", "test interruption")
            self.assertTrue(result["termination"]["stopped"])
            saved = orc.read_json(self.rundir / "state.json")
            self.assertEqual(saved["status"], "paused")
            self.assertIsNone(saved["active_check"])
            self.assertEqual(saved["verification_interrupted"]["argv"], ["true"])
        finally:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)

    def test_interrupt_preserves_dirty_worktree(self):
        dirty = self.project / "app.py"
        dirty.write_text("value = 2\n")
        before = dirty.read_text()
        self.state["active_check"] = {
            "argv": ["true"], "log": str(self.rundir / "check.log"),
            "candidate_hash": "candidate",
        }
        self._save()
        orc.interrupt_run("test-run00", "dirty tree")
        self.assertEqual(dirty.read_text(), before)
        self.assertIn("app.py", orc.git(self.project, ["status", "--porcelain"]).decode())

    # ------------------------------------------------------------------
    # AO-02: one non-final run per checkout
    # ------------------------------------------------------------------

    def _create(self, project, root):
        with patch.object(orc, "DEFAULT_STATE", root):
            return orc.create_run(project=str(project), goal="batch1", host="codex",
                                  skip_doctor=True)

    def test_second_run_for_same_checkout_is_refused(self):
        project = self._repo("create-project")
        root = self.root / "create-runs"
        first_id, _folder, first = self._create(project, root)
        self.assertEqual(first["project_lease"]["checkout_key"],
                         orc.checkout_identity(project)["key"])
        with self.assertRaises(orc.CheckoutOwnedError) as caught:
            self._create(project, root)
        self.assertIn(first_id, str(caught.exception))

    def test_concurrent_create_run_admits_exactly_one(self):
        project = self._repo("concurrent-project")
        root = self.root / "concurrent-runs"
        def start(index):
            try:
                return ("ok", orc.create_run(project=str(project),
                                             goal=f"goal-{index}", host="codex",
                                             skip_doctor=True)[0])
            except Exception as exc:
                return ("error", type(exc).__name__ + ": " + str(exc))
        with patch.object(orc, "DEFAULT_STATE", root):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results = [future.result() for future in
                           [pool.submit(start, 0), pool.submit(start, 1)]]
        self.assertEqual(sum(1 for status, _ in results if status == "ok"), 1, results)
        self.assertEqual(sum(1 for status, _ in results if status == "error"), 1, results)

    def test_symlinked_path_is_the_same_checkout(self):
        project = self._repo("symlink-project")
        link = self.root / "project-link"
        link.symlink_to(project, target_is_directory=True)
        root = self.root / "symlink-runs"
        self._create(project, root)
        with self.assertRaises(orc.CheckoutOwnedError):
            self._create(link, root)

    def test_final_run_releases_checkout(self):
        project = self._repo("release-project")
        root = self.root / "release-runs"
        first_id, folder, _state = self._create(project, root)
        with patch.object(orc, "DEFAULT_STATE", root):
            _folder, saved = orc.load(first_id)
            saved["status"] = "complete"
            orc.save(folder, saved)
            second_id, _folder2, _state2 = orc.create_run(
                project=str(project), goal="second", host="codex", skip_doctor=True)
        self.assertNotEqual(first_id, second_id)

    def test_uncertain_run_keeps_lease_and_blocks_new_run(self):
        project = self._repo("uncertain-project")
        root = self.root / "uncertain-runs"
        first_id, folder, _state = self._create(project, root)
        with patch.object(orc, "DEFAULT_STATE", root):
            _folder, saved = orc.load(first_id)
            saved.update(status="uncertain", active_check={"argv": ["true"]})
            orc.save(folder, saved)
            with self.assertRaises(orc.CheckoutOwnedError):
                orc.create_run(project=str(project), goal="second", host="codex",
                               skip_doctor=True)

    def test_final_status_with_uncertain_check_still_holds_lease(self):
        project = self._repo("final-uncertain-project")
        root = self.root / "final-uncertain-runs"
        first_id, folder, _state = self._create(project, root)
        with patch.object(orc, "DEFAULT_STATE", root):
            _folder, saved = orc.load(first_id)
            saved.update(status="complete", active_check={"argv": ["true"]})
            orc.save(folder, saved)
            with self.assertRaises(orc.CheckoutOwnedError):
                orc.create_run(project=str(project), goal="second", host="codex",
                               skip_doctor=True)

    def test_missing_owner_state_requires_explicit_takeover(self):
        project = self._repo("missing-owner-project")
        root = self.root / "missing-owner-runs"
        with patch.object(orc, "DEFAULT_STATE", root):
            identity = orc.checkout_identity(project)
            leases = orc.leases_root()
            leases.mkdir(parents=True, exist_ok=True)
            orc.atomic_json(leases / f"{identity['key']}.json",
                            {"run_id": "vanished-run", "project": str(project),
                             "checkout_key": identity["key"], "created_at": orc.now()})
            with self.assertRaisesRegex(orc.CheckoutOwnedError, "no readable state"):
                orc.create_run(project=str(project), goal="second", host="codex",
                               skip_doctor=True)

    def test_legacy_conflict_does_not_modify_state(self):
        project = self._repo("legacy-project")
        root = self.root / "legacy-runs"
        root.mkdir(parents=True, exist_ok=True)
        states = {}
        for name in ("legacy-run-a", "legacy-run-b"):
            folder = root / name
            folder.mkdir()
            state = dict(self.state)
            state.update(id=name, project=str(project), status="running", phase="plan",
                         plan=None, active_job=None, active_check=None)
            orc.atomic_json(folder / "state.json", state)
            states[name] = (folder / "state.json").read_bytes()
        with patch.object(orc, "DEFAULT_STATE", root):
            result = orc.stage_run("legacy-run-a")
        self.assertFalse(result["ok"])
        self.assertIn("already used", result["error"])
        self.assertEqual((root / "legacy-run-a/state.json").read_bytes(),
                         states["legacy-run-a"])
        self.assertFalse((root / "legacy-run-a/supervisor.lock").exists())

    # ------------------------------------------------------------------
    # AO-07: guarded verification in the legacy non-interactive mode
    # ------------------------------------------------------------------

    def test_legacy_noninteractive_timeout_has_identity_and_reconciles(self):
        self.state["interactive"] = False
        batch = {"title": "check", "checks": [[
            sys.executable, "-c", "import time; time.sleep(5)"]]}
        self.cfg["limits"]["max_check_seconds"] = 0.3
        with self.assertRaises(TimeoutError):
            orc.run_checks(self.rundir, self.state, self.cfg, self.project, batch)
        saved = orc.read_json(self.rundir / "state.json")
        check = saved["active_check"]
        self.assertIsNotNone(check.get("pid"))
        self.assertIsNotNone(check.get("sid"))
        self.assertTrue(orc.terminate_identity(check, grace=2)["stopped"])
        saved["status"] = "uncertain"
        orc.save(self.rundir, saved)
        result = orc.reconcile_run("test-run00")
        self.assertEqual(result["status"], "paused")
        self.assertIsNone(orc.read_json(self.rundir / "state.json")["active_check"])

    def test_guarded_timeout_cleans_session_descendants(self):
        self.state["interactive"] = False
        code = "import subprocess, time; subprocess.Popen(['sleep','30']); time.sleep(30)"
        batch = {"title": "check", "checks": [[sys.executable, "-c", code]]}
        self.cfg["limits"]["max_check_seconds"] = 0.4
        with self.assertRaises(TimeoutError):
            orc.run_checks(self.rundir, self.state, self.cfg, self.project, batch)
        check = orc.read_json(self.rundir / "state.json")["active_check"]
        liveness = orc.job_liveness(check)
        self.assertIs(liveness["alive"], False, liveness)

    # ------------------------------------------------------------------
    # INC-01: nested Explorer dispatch is policy-gated
    # ------------------------------------------------------------------

    def test_legacy_missing_explorer_policy_is_none(self):
        self.assertNotIn("explorer_policy", self.state)
        self.assertEqual(orc.explorer_policy_for(self.state), "none")
        context = orc.architect_context(self.rundir, self.state, "plan")
        self.assertIsNone(context["explorer_dispatch"])

    def test_architect_prompt_only_advertises_explorer_when_allowed(self):
        self.state["explorer_policy"] = "on_demand"
        plan = orc.architect_context(self.rundir, self.state, "plan")
        decision = orc.architect_context(self.rundir, self.state, "decision")
        self.assertIsNotNone(plan["explorer_dispatch"])
        self.assertIn("--parent-job __ABDULLAH_PARENT_JOB__", plan["explorer_dispatch"])
        self.assertIsNone(decision["explorer_dispatch"])

    def _explorer_args(self, **overrides):
        values = {"run": "test-run00", "task": "inspect", "parent_job": "parent-job"}
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_explore_refuses_policy_none_without_model_call(self):
        with patch.object(orc, "load", return_value=(self.rundir, self.state)), \
                patch.object(orc, "call_model") as call:
            with self.assertRaisesRegex(RuntimeError, "disabled"):
                orc.explore(self._explorer_args())
            call.assert_not_called()

    def test_explore_requires_exact_active_architect_parent(self):
        self.state.update(explorer_policy="on_demand", status="running", phase="plan",
                          active_job={"id": "parent-job", "role": "architect",
                                      "status": "running"})
        report = {"status": "complete", "summary": "read", "files": ["app.py"],
                  "tests": [], "evidence": ["app.py:1"], "unknowns": [], "blocker": ""}
        with patch.object(orc, "load", return_value=(self.rundir, self.state)), \
                patch.object(orc, "call_model", return_value=(report, {"id": "e1"})) as call, \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "parent job"):
                orc.explore(self._explorer_args(parent_job="wrong"))
            call.assert_not_called()
            orc.explore(self._explorer_args())
            call.assert_called_once()

    def test_explore_refuses_wrong_phase_and_paused_status(self):
        self.state.update(explorer_policy="on_demand", status="running", phase="accept",
                          active_job={"id": "parent-job", "role": "architect",
                                      "status": "running"})
        with patch.object(orc, "load", return_value=(self.rundir, self.state)), \
                patch.object(orc, "call_model") as call:
            with self.assertRaisesRegex(RuntimeError, "phase"):
                orc.explore(self._explorer_args())
            self.state["phase"] = "plan"
            self.state["status"] = "paused"
            with self.assertRaisesRegex(RuntimeError, "running"):
                orc.explore(self._explorer_args())
            call.assert_not_called()

    def test_explore_budget_is_enforced(self):
        self.state.update(explorer_policy="on_demand", status="running", phase="plan",
                          active_job={"id": "parent-job", "role": "architect",
                                      "status": "running"})
        tracker = self.rundir / "explorations" / "tracker"
        tracker.mkdir(parents=True)
        orc.atomic_json(tracker / "state.json", {
            "host": "codex", "project": str(self.project), "active_job": None,
            "completed_jobs": [], "failed_jobs": [], "explorer_calls": 8})
        with patch.object(orc, "load", return_value=(self.rundir, self.state)), \
                patch.object(orc, "call_model") as call:
            with self.assertRaisesRegex(RuntimeError, "budget"):
                orc.explore(self._explorer_args())
            call.assert_not_called()


    def test_architect_subprocess_receives_parent_job_environment(self):
        captured = {}
        def fake_spawn(command, cwd, env, log, **kwargs):
            captured.update({"command": command, "env": env})
            raise KeyboardInterrupt("stop before spawn")
        with patch.object(orc, "_spawn_guarded", side_effect=fake_spawn):
            with self.assertRaises(KeyboardInterrupt):
                orc.call_model(self.rundir, self.state, self.cfg, "architect",
                               "plan", "prompt __ABDULLAH_PARENT_JOB__", self.project)
        self.assertEqual(captured["env"]["ABDULLAH_RUN_ID"], "test-run00")
        self.assertTrue(captured["env"]["ABDULLAH_PARENT_JOB"])
        self.assertEqual(captured["env"]["ABDULLAH_STAGE"], "plan")
        prompt = captured["command"][-1]
        self.assertIn(captured["env"]["ABDULLAH_PARENT_JOB"], prompt)
        self.assertNotIn("__ABDULLAH_PARENT_JOB__", prompt)

    def test_explore_accepts_parent_job_from_supervisor_environment(self):
        self.state.update(explorer_policy="on_demand", status="running", phase="plan",
                          active_job={"id": "parent-job", "role": "architect",
                                      "status": "running"})
        report = {"status": "complete", "summary": "read", "files": ["app.py"],
                  "tests": [], "evidence": ["app.py:1"], "unknowns": [], "blocker": ""}
        args = self._explorer_args(parent_job=None)
        with patch.object(orc, "load", return_value=(self.rundir, self.state)), \
                patch.object(orc, "call_model", return_value=(report, {"id": "e1"})) as call, \
                patch.dict(os.environ, {"ABDULLAH_RUN_ID": "test-run00",
                                        "ABDULLAH_PARENT_JOB": "parent-job"}), \
                contextlib.redirect_stdout(io.StringIO()):
            orc.explore(args)
        call.assert_called_once()

    def test_new_run_requires_explicit_explorer_permission(self):
        for index, kwargs in enumerate((
                {}, {"allow_explorer": True}, {"require_explorer": True})):
            with self.subTest(kwargs=kwargs):
                project = self._repo(f"policy-project-{index}")
                root = self.root / f"policy-runs-{index}"
                with patch.object(orc, "DEFAULT_STATE", root):
                    _id, _folder, state = orc.create_run(
                        project=str(project), goal="x", host="codex",
                        skip_doctor=True, **kwargs)
                expected = "on_demand" if kwargs.get("allow_explorer") else (
                    "required" if kwargs.get("require_explorer") else "none")
                self.assertEqual(state["explorer_policy"], expected)


if __name__ == "__main__":
    unittest.main()
