"""v3.1 whole-stage deadline: checks and strong calls share one budget."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_orchestrator as baseline
orc = baseline.orc


SLEEPING_CODEX = r'''#!/usr/bin/env python3
import sys, time
if '--version' in sys.argv:
    print('0.167.0')
    sys.exit(0)
if '--output-last-message' in sys.argv:
    time.sleep(10)
sys.exit(0)
'''


class StageDeadlineTests(unittest.TestCase):
    setUp = baseline.ControlTests.setUp
    tearDown = baseline.ControlTests.tearDown

    def configure_stage(self, seconds):
        cfg = orc.read_json(orc.CONFIG_PATH)
        cfg.setdefault("limits", {})["max_stage_seconds"] = seconds
        cfg["limits"]["max_check_seconds"] = 60
        cfg["limits"]["max_architect_seconds"] = 60
        orc.atomic_json(orc.CONFIG_PATH, cfg)
        self.cfg = orc.config()
        self.state["config_sha256"] = orc.configuration_provenance().get("sha256")
        orc.save(self.rundir, self.state)

    def test_expired_budget_before_next_child_blocks_verification(self):
        # Deterministic seam: a genuinely expired whole-stage deadline.  No
        # substring of the safe runtime wording is required.
        self.configure_stage(1.0)
        plan = {"contract_version": 2, "status": "complete", "summary": "plan",
                "invariants": ["Keep behavior"],
                "batches": [{"title": "one", "goal": "g", "acceptance": ["a"],
                             "checks": [[sys.executable, "-c", "pass"]],
                             "risk": "ordinary"}],
                "blocker": ""}
        self.state.update(phase="verify", plan=plan,
                          plan_version=orc.content_hash(plan), batch_index=0,
                          single_batch_fast_path=False)
        orc.save(self.rundir, self.state)
        expired = orc.time.monotonic() - 1.0
        with patch.object(orc, "stage_deadline", lambda cfg: expired):
            result = orc.stage_run("test-run00")
        self.assertFalse(result["ok"])
        self.assertEqual(result["stage"], "verify")
        self.assertTrue(result["pause_reason"])
        state = orc.read_json(self.rundir / "state.json")
        self.assertIn(state["status"], {"uncertain", "blocked"})
        self.assertEqual(state["phase"], "verify")
        self.assertIsNone(state.get("verification"))
        self.assertIsNone(state.get("active_job"))
        self.assertIsNone(state.get("active_check"))
        self.assertFalse(state.get("completed_jobs"))
        self.assertFalse(state.get("accepted_batches"))
        # No Reviewer/worker is dispatched after an expired pre-child budget.
        with patch.object(orc, "stage_deadline", lambda cfg: expired):
            again = orc.stage_run("test-run00")
        after = orc.read_json(self.rundir / "state.json")
        self.assertFalse(again["ok"])
        self.assertEqual(after["phase"], "verify")
        self.assertNotEqual(after["phase"], "review")
        self.assertFalse(after.get("completed_jobs"))
        self.assertIsNone(after.get("verification"))

    def test_already_started_check_is_terminated_at_clipped_deadline(self):
        self.configure_stage(1.5)
        plan = {"contract_version": 2, "status": "complete", "summary": "plan",
                "invariants": ["Keep behavior"],
                "batches": [{"title": "one", "goal": "g", "acceptance": ["a"],
                             "checks": [[sys.executable, "-c",
                                         "import time; time.sleep(0.3)"],
                                        [sys.executable, "-c",
                                         "import time; time.sleep(30)"]],
                             "risk": "ordinary"}],
                "blocker": ""}
        self.state.update(phase="verify", plan=plan,
                          plan_version=orc.content_hash(plan), batch_index=0,
                          single_batch_fast_path=False)
        orc.save(self.rundir, self.state)
        result = orc.stage_run("test-run00")
        self.assertFalse(result["ok"])
        self.assertEqual(result["stage"], "verify")
        self.assertTrue(result["pause_reason"])
        state = orc.read_json(self.rundir / "state.json")
        self.assertIn(state["status"], {"uncertain", "blocked"})
        self.assertEqual(state["phase"], "verify")
        self.assertIsNone(state.get("verification"))
        self.assertFalse(state.get("accepted_batches"))
        # The first check completed; the second was clipped and terminated.
        logs = sorted((self.rundir / "jobs").glob("check-*.log"))
        self.assertGreaterEqual(len(logs), 1)
        evidence = (state.get("check_progress") or {}).get("evidence") or {}
        commands = evidence.get("commands") or []
        self.assertTrue(commands)
        self.assertEqual(commands[0]["returncode"], 0)
        # A timed-out stage must not advance to review or acceptance and must
        # not dispatch a Reviewer/worker on the next stage attempt.
        again = orc.stage_run("test-run00")
        after = orc.read_json(self.rundir / "state.json")
        self.assertFalse(again["ok"])
        self.assertNotIn(again["stage"], {"review", "accept"})
        self.assertEqual(after["phase"], "verify")
        self.assertIsNone(after.get("verification"))
        self.assertFalse(any(job.get("role") in {"reviewer", "implementer"}
                             for job in after.get("completed_jobs", [])))

    def test_decision_child_is_clipped_to_the_remaining_stage_budget(self):
        self.configure_stage(0.7)
        bin_dir = self.root / "deadline-bin"
        bin_dir.mkdir()
        script = bin_dir / "codex"
        script.write_text(SLEEPING_CODEX)
        script.chmod(0o755)
        with patch.dict(os.environ, {"PATH": str(bin_dir) + ":" + os.environ["PATH"],
                                     "OPENAI_API_KEY": ""}):
            result = orc.stage_run("test-run00")
        self.assertFalse(result["ok"])
        self.assertEqual(result["stage"], "plan")
        state = orc.read_json(self.rundir / "state.json")
        self.assertIn(state["status"], {"uncertain", "blocked"})
        self.assertEqual(state["phase"], "plan")
        self.assertTrue(state["failed_jobs"])
        self.assertFalse(state["completed_jobs"])

    def test_worker_timeout_uses_the_remaining_stage_budget(self):
        self.cfg["limits"]["max_stage_seconds"] = 0.2
        deadline = orc.stage_deadline(self.cfg)
        with self.assertRaises(TimeoutError):
            orc.remaining_budget(60, deadline - 1.0)
        clipped = orc.remaining_budget(60, orc.time.monotonic() + 1)
        self.assertLessEqual(clipped, 1.0)
        self.assertEqual(orc.remaining_budget(5, None), 5)

    def test_each_child_fits_but_checks_plus_decision_do_not(self):
        # One final check (0.8s) fits the 2.0s stage; the fake decision (1.5s)
        # also fits alone.  Together they exceed the genuine acceptance budget.
        self.configure_stage(2.0)
        bin_dir = self.root / "acceptance-deadline-bin"
        bin_dir.mkdir()
        script = bin_dir / "codex"
        script.write_text(r'''#!/usr/bin/env python3
import json, pathlib, sys, time
args = sys.argv[1:]
if '--version' in args:
    print('0.167.0')
    sys.exit(0)
if '--output-last-message' in args:
    output = pathlib.Path(args[args.index('--output-last-message') + 1])
    kind = output.parent.name.split('-')[0]
    if kind == 'decision':
        time.sleep(1.5)
    report = {'contract_version': 2, 'verdict': 'approved', 'reason': 'inspected',
              'inspected': ['app.py'], 'correction': '',
              'dismissed_findings': []}
    output.write_text(json.dumps(report))
    sys.exit(0)
sys.exit(3)
''')
        script.chmod(0o755)
        plan = {"contract_version": 2, "status": "complete", "summary": "plan",
                "invariants": ["Keep behavior"],
                "batches": [{"title": "one", "goal": "g", "acceptance": ["a"],
                             "checks": [[sys.executable, "-c",
                                         "import time; time.sleep(0.8)"]],
                             "risk": "ordinary"}],
                "blocker": ""}
        self.state.update(phase="verify", plan=plan,
                          plan_version=orc.content_hash(plan), batch_index=0,
                          single_batch_fast_path=True)
        orc.save(self.rundir, self.state)
        with patch.dict(os.environ, {"PATH": str(bin_dir) + ":" + os.environ["PATH"],
                                     "OPENAI_API_KEY": ""}):
            evidence = orc.run_checks(self.rundir, self.state, self.cfg,
                                      self.project, plan["batches"][0])
            self.assertTrue(evidence["passed"], evidence)
            self.state.update(phase="accept", review={
                "contract_version": 2, "status": "complete", "summary": "reviewed",
                "findings": [], "files": [], "tests": [], "evidence": ["app.py:1"],
                "unknowns": [], "blocker": ""}, check_progress=None)
            orc.save(self.rundir, self.state)
            result = orc.stage_run("test-run00")
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["stage"], "accept")
        state = orc.read_json(self.rundir / "state.json")
        self.assertNotEqual(state["status"], "complete")
        self.assertEqual(state["phase"], "accept")
        self.assertIsNone(state.get("final_verdict"))
        self.assertFalse(state.get("accepted_batches"))
        self.assertIsNone(state.get("active_check"))
        if state.get("active_job"):
            # A timeout is never completion. If containment cannot be proven
            # stopped at observation time, exact uncertain ownership remains.
            self.assertEqual(state["active_job"]["status"], "uncertain")
            self.assertEqual(state["status"], "uncertain")


if __name__ == "__main__":
    unittest.main()
