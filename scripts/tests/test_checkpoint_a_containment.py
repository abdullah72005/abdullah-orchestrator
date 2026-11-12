"""Checkpoint A: one containment gate for every identity-clearing path."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import test_orchestrator as baseline

orc = baseline.orc


class CheckpointAContainment(unittest.TestCase):
    def setUp(self):
        baseline.ControlTests.setUp(self)
        self.runs = self.root / "runs"

    def _save(self, state=None):
        orc.save(self.rundir, state or self.state)

    def _marked(self, name, value, code="import time; time.sleep(30)"):
        env = {**os.environ, name: value, "ABDULLAH_RUN_ID": "test-run00"}
        return subprocess.Popen([sys.executable, "-c", code], start_new_session=True,
                                env=env)

    def _run_only(self, code="import time; time.sleep(30)"):
        return subprocess.Popen([sys.executable, "-c", code], start_new_session=True,
                                env={**os.environ, "ABDULLAH_RUN_ID": "test-run00"})

    def _double_fork_marked(self, marker_name, marker_value, *, strip_token=False):
        pidfile = self.root / ("escape-" + marker_value + ".pid")
        code = (
            "import os, time\n"
            f"pidfile = {str(pidfile)!r}\n"
            "if os.fork() == 0:\n"
            "    os.setsid()\n"
            "    if os.fork() == 0:\n"
            "        open(pidfile, 'w').write(str(os.getpid()))\n"
            + ("        os.environ.pop('ABDULLAH_CHECK_TOKEN', None)\n" if strip_token else "")
            + "        time.sleep(30)\n"
            "    os._exit(0)\n"
            "os._exit(0)\n"
        )
        parent = subprocess.Popen([sys.executable, "-c", code], start_new_session=True,
                                  env={**os.environ, marker_name: marker_value,
                                       "ABDULLAH_RUN_ID": "test-run00"})
        parent.wait(timeout=5)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if pidfile.exists():
                try:
                    value = pidfile.read_text().strip()
                    if value:
                        return int(value)
                except (OSError, ValueError):
                    pass
            time.sleep(0.02)
        self.fail("double-fork survivor did not publish a PID")

    def _kill_pid(self, pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass

    def _dead_job(self, job_id="job-1", check=False):
        dead = baseline.dead_process_identity()
        return {"id": job_id, "role": "implementer", "status": "running",
                "pid": dead["pid"], "pid_start": dead.get("pid_start"),
                "pgid": dead["pid"], "sid": dead["pid"],
                "launch_file": str(self.root / "missing-launch.json"),
                **({"check_token": "token-1"} if check else {})}

    def test_reconcile_launch_missing_refuses_live_run_marker_survivor(self):
        proc = self._marked("ABDULLAH_JOB_ID", "job-1")
        try:
            self.state.update(status="uncertain", active_job=self._dead_job())
            self._save()
            with self.assertRaisesRegex(RuntimeError, "surviving"):
                orc.reconcile_run("test-run00", launch_missing=True,
                                  evidence="inspected; no launch file")
            saved = orc.read_json(self.rundir / "state.json")
            self.assertIsNotNone(saved["active_job"])
            self.assertEqual(saved["status"], "uncertain")
        finally:
            proc.kill(); proc.wait(timeout=5)

    def test_reconcile_refuses_live_job_marker_after_dead_identity(self):
        proc = self._marked("ABDULLAH_JOB_ID", "job-1")
        try:
            self.state.update(status="uncertain", active_job=self._dead_job())
            self._save()
            with self.assertRaisesRegex(RuntimeError, "surviving"):
                orc.reconcile_run("test-run00")
            saved = orc.read_json(self.rundir / "state.json")
            self.assertIsNotNone(saved["active_job"])
        finally:
            proc.kill(); proc.wait(timeout=5)

    def test_reconcile_refuses_live_recorded_escaped_descendant(self):
        proc = self._marked("ABDULLAH_JOB_ID", "unrelated")
        try:
            stat = orc.process_stat(proc.pid)
            self.assertIsNotNone(stat)
            check = self._dead_job("check-1", check=True)
            check["escaped_processes"] = [stat]
            self.state.update(status="uncertain", active_check=check)
            self._save()
            with self.assertRaisesRegex(RuntimeError, "surviving"):
                orc.reconcile_run("test-run00")
        finally:
            proc.kill(); proc.wait(timeout=5)

    def test_recover_finished_dispatch_refuses_live_escaped_job_marker(self):
        proc = self._marked("ABDULLAH_JOB_ID", "job-1")
        try:
            jobdir = self.rundir / "jobs" / "implementer-job-1"
            jobdir.mkdir(parents=True)
            snapshot = orc.source_snapshot(self.project)
            report = {"status": "complete", "summary": "done", "files": [],
                      "tests": [], "evidence": [], "unknowns": [], "blocker": ""}
            orc.atomic_json(jobdir / "report.json", report)
            orc.atomic_json(jobdir / "execution.json", {"returncode": 0})
            orc.atomic_json(jobdir / "completion.json", {"final_snapshot": snapshot,
                                                         "session_id": "s"})
            job = self._dead_job()
            job.update(path=str(jobdir), kind="implement", role="implementer")
            self.state.update(active_job=job)
            self._save()
            self.assertFalse(orc.recover_finished_dispatch(self.rundir, self.state))
            saved = orc.read_json(self.rundir / "state.json")
            self.assertEqual(saved["active_job"]["status"], "uncertain")
            self.assertFalse(saved.get("completed_jobs"))
        finally:
            proc.kill(); proc.wait(timeout=5)

    def test_reconcile_explorer_refuses_live_job_marker_after_dead_identity(self):
        proc = self._marked("ABDULLAH_JOB_ID", "explorer-1")
        try:
            tracker = self.rundir / "explorations" / "tracker"
            tracker.mkdir(parents=True)
            job = self._dead_job("explorer-1")
            job.update(role="explorer", kind="explorer")
            orc.atomic_json(tracker / "state.json", {
                "host": "codex", "project": str(self.project), "run_id": "test-run00",
                "active_job": job, "completed_jobs": [], "failed_jobs": [],
                "explorer_calls": 1})
            with self.assertRaisesRegex(RuntimeError, "surviving"):
                orc.reconcile_explorer("test-run00")
            self.assertIsNotNone(orc.read_json(tracker / "state.json")["active_job"])
        finally:
            proc.kill(); proc.wait(timeout=5)

    def test_interrupt_run_refuses_dead_identity_with_live_job_marker(self):
        proc = self._marked("ABDULLAH_JOB_ID", "job-1")
        try:
            self.state.update(status="running", active_job=self._dead_job())
            self._save()
            result = orc.interrupt_run("test-run00", "stop")
            self.assertFalse(result["termination"]["stopped"])
            self.assertEqual(result["status"], "uncertain")
            saved = orc.read_json(self.rundir / "state.json")
            self.assertIsNotNone(saved["active_job"])
        finally:
            proc.kill(); proc.wait(timeout=5)

    def test_run_checks_retains_active_check_when_escape_containment_fails(self):
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
        real_terminate = orc._terminate_pids
        def not_clean(stats, grace=2):
            result = real_terminate(stats, grace)
            result["clean"] = False
            return result
        with patch.object(orc, "_terminate_pids", side_effect=not_clean):
            evidence = orc.run_checks(self.rundir, self.state, self.cfg,
                                      self.project, batch)
        saved = orc.read_json(self.rundir / "state.json")
        self.assertFalse(evidence["passed"])
        self.assertIsNotNone(saved.get("active_check"))
        self.assertEqual(saved["active_check"]["status"], "uncertain")
        for item in saved["active_check"].get("escaped_processes", []):
            try:
                os.kill(item["pid"], signal.SIGKILL)
            except OSError:
                pass

    def test_recovery_docs_state_the_same_user_trust_boundary(self):
        text = (Path(orc.SKILL) / "references/operation.md").read_text(encoding="utf-8")
        self.assertIn("Protected operator recovery", text)
        self.assertIn("not cryptographic authorization", text)
        self.assertIn("user-executed CLI", text)
        self.assertIn("Unified containment gate", text)

    def test_reconcile_refuses_run_marker_only(self):
        proc = self._run_only()
        try:
            self.state.update(status="uncertain", active_job=self._dead_job())
            self._save()
            with self.assertRaisesRegex(RuntimeError, "surviving"):
                orc.reconcile_run("test-run00")
        finally:
            proc.kill(); proc.wait(timeout=5)

    def test_interrupt_refuses_run_marker_without_active_record(self):
        proc = self._run_only()
        try:
            self.state.update(status="running", active_job=None, active_check=None)
            self._save()
            result = orc.interrupt_run("test-run00", "stop")
            self.assertFalse(result["termination"]["stopped"])
            self.assertEqual(result["status"], "uncertain")
            saved = orc.read_json(self.rundir / "state.json")
            self.assertEqual(saved["status"], "uncertain")
            self.assertIn("marked run processes", saved["pause_reason"])
        finally:
            proc.kill(); proc.wait(timeout=5)

    def test_final_owner_takeover_refuses_run_marker_survivor(self):
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                start_new_session=True,
                                env={**os.environ, "ABDULLAH_RUN_ID": "final-owner"})
        try:
            owner = self.root / "runs" / "final-owner"
            owner.mkdir()
            state = dict(self.state)
            state.update(id="final-owner", status="complete", active_job=None,
                         active_check=None, project=str(self.project))
            orc.atomic_json(owner / "state.json", state)
            identity = orc.checkout_identity(self.project)
            orc.atomic_json(orc._lease_path(identity["key"]), {
                "run_id": "final-owner", "lease_id": "x", "project": str(self.project),
                "checkout_key": identity["key"], "inode": identity["inode"],
                "status": "active", "owner_pid": os.getpid(), "created_at": orc.now()})
            with self.assertRaises(orc.CheckoutOwnedError) as caught:
                orc.acquire_checkout_lease(self.project, "new-run")
            self.assertEqual(caught.exception.state, "containment")
            self.assertEqual(orc._lease_record(identity["key"])["run_id"], "final-owner")
        finally:
            proc.kill(); proc.wait(timeout=5)

    def test_reconcile_refuses_live_launch_child_identity(self):
        clean_env = {k: v for k, v in os.environ.items()
                     if not k.startswith("ABDULLAH_")}
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                start_new_session=True, env=clean_env)
        try:
            launch = self.root / "launch-with-child.json"
            dead = baseline.dead_process_identity()
            orc.atomic_json(launch, {"phase": "running", "guard": dead,
                                     "child_identity": orc.process_identity(proc.pid)})
            with patch.object(orc, "process_identity", return_value=dead):
                orc._write_launch(launch, "exited", returncode=0)
            saved_launch = orc.read_json(launch)
            self.assertEqual(saved_launch["child_identity"]["pid"], proc.pid)
            check = self._dead_job("check-1", check=True)
            check["launch_file"] = str(launch)
            check.pop("pid", None); check.pop("pid_start", None)
            check.pop("pgid", None); check.pop("sid", None)
            self.state.update(status="uncertain", active_check=check)
            self._save()
            with self.assertRaisesRegex(RuntimeError, "surviving"):
                orc.reconcile_run("test-run00")
        finally:
            proc.kill(); proc.wait(timeout=5)

    def test_reconcile_refuses_recorded_descendant(self):
        proc = self._run_only()
        try:
            stat = orc.process_stat(proc.pid)
            job = self._dead_job()
            job["descendant_pids"] = [stat["pid"]]
            self.state.update(status="uncertain", active_job=job)
            self._save()
            with self.assertRaisesRegex(RuntimeError, "surviving"):
                orc.reconcile_run("test-run00")
        finally:
            proc.kill(); proc.wait(timeout=5)

    def test_verification_double_fork_stripping_token_retains_active_check(self):
        survivor = self._double_fork_marked("ABDULLAH_JOB_ID", "check-escape",
                                            strip_token=True)
        batch = {"title": "escape", "checks": [[sys.executable, "-c", (
            "import os, time\n"
            "if os.fork() == 0:\n"
            "    os.setsid()\n"
            "    if os.fork() == 0:\n"
            "        os.environ.pop('ABDULLAH_CHECK_TOKEN', None)\n"
            "        time.sleep(30)\n"
            "    os._exit(0)\n"
            "os._exit(0)\n")]]}
        try:
            evidence = orc.run_checks(self.rundir, self.state, self.cfg,
                                      self.project, batch)
            saved = orc.read_json(self.rundir / "state.json")
            self.assertFalse(evidence["passed"])
            self.assertIn("escaped execution", evidence.get("error", ""))
            self.assertIsNotNone(saved.get("active_check"))
            self.assertEqual(saved["active_check"]["status"], "uncertain")
            self.assertTrue(saved["active_check"]["escaped_processes"])
        finally:
            self._kill_pid(survivor)
            for item in (orc.read_json(self.rundir / "state.json").get("active_check") or {}).get("escaped_processes", []):
                self._kill_pid(item["pid"])

    def test_recover_finished_dispatch_refuses_double_fork_job_survivor(self):
        survivor = self._double_fork_marked("ABDULLAH_JOB_ID", "job-1")
        try:
            jobdir = self.rundir / "jobs" / "implementer-job-1"
            jobdir.mkdir(parents=True)
            snapshot = orc.source_snapshot(self.project)
            orc.atomic_json(jobdir / "report.json", {
                "status": "complete", "summary": "done", "files": [],
                "tests": [], "evidence": [], "unknowns": [], "blocker": ""})
            orc.atomic_json(jobdir / "execution.json", {"returncode": 0})
            orc.atomic_json(jobdir / "completion.json", {"final_snapshot": snapshot,
                                                         "session_id": "s"})
            job = self._dead_job()
            job.update(path=str(jobdir), kind="implement", role="implementer")
            self.state.update(active_job=job)
            self._save()
            self.assertFalse(orc.recover_finished_dispatch(self.rundir, self.state))
            self.assertEqual(orc.read_json(self.rundir / "state.json")["active_job"]["status"],
                             "uncertain")
        finally:
            self._kill_pid(survivor)

    def test_reconcile_explorer_refuses_double_fork_job_survivor(self):
        survivor = self._double_fork_marked("ABDULLAH_JOB_ID", "explorer-1")
        try:
            tracker = self.rundir / "explorations" / "tracker"
            tracker.mkdir(parents=True)
            job = self._dead_job("explorer-1")
            job.update(role="explorer", kind="explorer")
            orc.atomic_json(tracker / "state.json", {
                "host": "codex", "project": str(self.project), "run_id": "test-run00",
                "active_job": job, "completed_jobs": [], "failed_jobs": [],
                "explorer_calls": 1})
            with self.assertRaisesRegex(RuntimeError, "surviving"):
                orc.reconcile_explorer("test-run00")
        finally:
            self._kill_pid(survivor)

    def test_final_owner_takeover_refuses_completed_job_marker_survivor(self):
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                start_new_session=True,
                                env={**os.environ, "ABDULLAH_JOB_ID": "old-job"})
        try:
            owner = self.root / "runs" / "final-owner"
            owner.mkdir()
            state = dict(self.state)
            state.update(id="final-owner", status="complete", active_job=None,
                         active_check=None, project=str(self.project),
                         completed_jobs=[{"id": "old-job", "status": "complete"}])
            orc.atomic_json(owner / "state.json", state)
            with self.assertRaises(orc.CheckoutOwnedError) as caught:
                orc.acquire_checkout_lease(self.project, "new-run")
            self.assertEqual(caught.exception.state, "containment")
        finally:
            proc.kill(); proc.wait(timeout=5)

    def test_final_survivor_on_other_project_does_not_block_checkout(self):
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                start_new_session=True,
                                env={**os.environ, "ABDULLAH_RUN_ID": "other-project-run"})
        try:
            other_base = self.root / "other-project"
            other_base.mkdir()
            other = baseline.setup_repo(other_base)
            new_base = self.root / "new-project"
            new_base.mkdir()
            new_project = baseline.setup_repo(new_base)
            owner = self.root / "runs" / "other-project-run"
            owner.mkdir()
            state = dict(self.state)
            state.update(id="other-project-run", status="complete", active_job=None,
                         active_check=None, project=str(other))
            orc.atomic_json(owner / "state.json", state)
            lease = orc.acquire_checkout_lease(new_project, "new-run")
            self.assertEqual(lease["run_id"], "new-run")
            orc.release_checkout_lease({"id": "new-run", "project": str(new_project)})
        finally:
            proc.kill(); proc.wait(timeout=5)

    def test_terminate_identity_reports_descendants(self):
        code = (
            "import subprocess, sys, time\n"
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
            "print(child.pid, flush=True)\n"
            "time.sleep(30)\n")
        proc = subprocess.Popen([sys.executable, "-c", code], start_new_session=True,
                                stdout=subprocess.PIPE, text=True)
        try:
            child_pid = int(proc.stdout.readline().strip())
            result = orc.terminate_identity(orc.process_identity(proc.pid), grace=2)
            self.assertIn(child_pid, result.get("descendants", []))
        finally:
            proc.kill(); proc.wait(timeout=5)
            proc.stdout.close()

    def test_final_conflict_preview_uses_containment_guidance(self):
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                start_new_session=True,
                                env={**os.environ, "ABDULLAH_RUN_ID": "final-owner"})
        try:
            owner = self.root / "runs" / "final-owner"
            owner.mkdir()
            state = dict(self.state)
            state.update(id="final-owner", status="complete", active_job=None,
                         active_check=None, project=str(self.project))
            orc.atomic_json(owner / "state.json", state)
            preview = orc.checkout_conflict(self.state)
            self.assertEqual(preview["kind"], "containment")
            self.assertNotIn("orchestrator.py retire", preview["resolution"])
            self.assertNotIn("orchestrator.py adopt", preview["resolution"])
        finally:
            proc.kill(); proc.wait(timeout=5)

    def test_verification_escape_status_is_reconcilable(self):
        code = (
            "import os, time\n"
            "if os.fork() == 0:\n"
            "    os.setsid()\n"
            "    time.sleep(30)\n"
            "os._exit(0)\n")
        self.state.update(phase="verify", plan={"batches": [{"title": "x",
                          "checks": [[sys.executable, "-c", code]], "risk": "ordinary"}]})
        orc.save(self.rundir, self.state)
        real = orc._terminate_pids
        def not_clean(stats, grace=2):
            result = real(stats, grace)
            result["clean"] = False
            return result
        with patch.object(orc, "_terminate_pids", side_effect=not_clean):
            orc.advance(self.rundir, self.state, self.cfg)
        saved = orc.read_json(self.rundir / "state.json")
        self.assertEqual(saved["status"], "uncertain")
        self.assertIsNotNone(saved.get("active_check"))
        self.assertEqual(orc.next_action_for(saved), "orchestrator_reconcile")

    def test_explorer_reconcile_refuses_run_marker_only_survivor(self):
        proc = self._run_only()
        try:
            tracker = self.rundir / "explorations" / "tracker"
            tracker.mkdir(parents=True)
            orc.atomic_json(tracker / "state.json", {
                "host": "codex", "project": str(self.project), "run_id": "test-run00",
                "active_job": self._dead_job("explorer-1"),
                "completed_jobs": [], "failed_jobs": [], "explorer_calls": 1})
            with self.assertRaisesRegex(RuntimeError, "surviving"):
                orc.reconcile_explorer("test-run00")
        finally:
            proc.kill(); proc.wait(timeout=5)

    def test_explorer_reconcile_excludes_live_parent_session(self):
        parent = self._run_only()
        try:
            tracker = self.rundir / "explorations" / "tracker"
            tracker.mkdir(parents=True)
            orc.atomic_json(tracker / "state.json", {
                "host": "codex", "project": str(self.project), "run_id": "test-run00",
                "active_job": self._dead_job("explorer-1"),
                "parent_job_identity": orc.process_identity(parent.pid),
                "completed_jobs": [], "failed_jobs": [], "explorer_calls": 1})
            orc.reconcile_explorer("test-run00")
            self.assertIsNone(orc.read_json(tracker / "state.json")["active_job"])
        finally:
            parent.kill(); parent.wait(timeout=5)

    def test_protected_recovery_actions_remain_cli_only(self):
        self.assertNotIn("orchestrator_retire", orc.MCP_TOOL_NAMES)
        self.assertNotIn("orchestrator_adopt", orc.MCP_TOOL_NAMES)
        self.assertNotIn("orchestrator_checkout_recover", orc.MCP_TOOL_NAMES)
        self.assertIn("orchestrator_reconcile", orc.MCP_TOOL_NAMES)


if __name__ == "__main__":
    unittest.main()
