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

    def test_protected_recovery_actions_remain_cli_only(self):
        self.assertNotIn("orchestrator_retire", orc.MCP_TOOL_NAMES)
        self.assertNotIn("orchestrator_adopt", orc.MCP_TOOL_NAMES)
        self.assertNotIn("orchestrator_checkout_recover", orc.MCP_TOOL_NAMES)
        self.assertIn("orchestrator_reconcile", orc.MCP_TOOL_NAMES)


if __name__ == "__main__":
    unittest.main()
