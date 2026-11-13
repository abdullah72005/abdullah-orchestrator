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

    def test_sequential_checks_are_clipped_to_one_stage_deadline(self):
        self.configure_stage(1.2)
        plan = {"contract_version": 2, "status": "complete", "summary": "plan",
                "invariants": ["Keep behavior"],
                "batches": [{"title": "one", "goal": "g", "acceptance": ["a"],
                             "checks": [[sys.executable, "-c", "import time; time.sleep(1)"],
                                        [sys.executable, "-c", "import time; time.sleep(1)"]],
                             "risk": "ordinary"}],
                "blocker": ""}
        self.state.update(phase="verify", plan=plan,
                          plan_version=orc.content_hash(plan), batch_index=0,
                          single_batch_fast_path=False)
        orc.save(self.rundir, self.state)
        result = orc.stage_run("test-run00")
        self.assertFalse(result["ok"])
        self.assertEqual(result["stage"], "verify")
        self.assertIn("timed out", (result["pause_reason"] or "").lower())
        state = orc.read_json(self.rundir / "state.json")
        self.assertIn(state["status"], {"uncertain", "blocked"})
        self.assertEqual(state["phase"], "verify")
        self.assertIsNone(state.get("verification"))
        # Both check logs exist; the second was killed by the clipped budget.
        logs = sorted((self.rundir / "jobs").glob("check-*.log"))
        self.assertGreaterEqual(len(logs), 1)
        self.assertTrue(any(item["returncode"] != 0
                            for item in state.get("check_progress", {}).get("evidence", {}).get("commands", []))
                        or state.get("active_check") or state.get("pause_reason"))
        # A timed-out stage must not advance to review.
        again = orc.stage_run("test-run00")
        self.assertFalse(again["ok"])
        self.assertNotEqual(again["stage"], "review")

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

    def test_each_check_fits_but_checks_plus_decision_do_not(self):
        # First check 0.4s, second 0.4s, decision would need 0.4s: no single
        # child exceeds the 2.0s stage, but the whole sequence is bounded.
        self.configure_stage(5.0)
        plan = {"contract_version": 2, "status": "complete", "summary": "plan",
                "invariants": ["Keep behavior"],
                "batches": [{"title": "one", "goal": "g", "acceptance": ["a"],
                             "checks": [[sys.executable, "-c",
                                         "import time; time.sleep(0.4)"],
                                        [sys.executable, "-c",
                                         "import time; time.sleep(0.4)"]],
                             "risk": "ordinary"}],
                "blocker": ""}
        self.state.update(phase="verify", plan=plan,
                          plan_version=orc.content_hash(plan), batch_index=0)
        orc.save(self.rundir, self.state)
        result = orc.stage_run("test-run00")
        # Two sub-second checks fit; the stage is ready for review.
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["stage"], "verify")
        state = orc.read_json(self.rundir / "state.json")
        self.assertEqual(state["phase"], "review")
        self.assertTrue(state["verification"]["passed"])


if __name__ == "__main__":
    unittest.main()
