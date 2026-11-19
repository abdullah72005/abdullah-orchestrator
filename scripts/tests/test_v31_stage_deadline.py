"""v3.1 whole-stage deadline: checks and strong calls share one budget."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

import test_orchestrator as baseline
orc = baseline.orc


class MarkerGatedBudget:
    """Test-only deadline value that clips only after a start marker exists.

    Under load, preflight work can consume the whole stage budget before the
    decision child is spawned, turning this test into the pre-spawn timeout
    branch.  Returning this object from ``remaining_budget`` lets the spawn
    happen; its first comparison waits (bounded) for the fake decision's
    marker and then applies the genuine remaining stage budget, or a minimal
    positive clip if the deadline already elapsed while starting up.
    """

    def __init__(self, marker, deadline, configured, wait=10.0, expired=0.05):
        self.marker = Path(marker)
        self.deadline = deadline
        self.configured = float(configured)
        self.wait = float(wait)
        self.expired = float(expired)

    def _clip(self):
        until = time.monotonic() + self.wait
        while time.monotonic() < until:
            if self.marker.exists():
                remaining = (self.deadline - time.monotonic()
                             if self.deadline is not None else self.configured)
                if remaining <= 0.05:
                    # The stage deadline elapsed during startup.  A
                    # prerequisite child gets a small positive window to
                    # finish; the child under test gets an immediate clip.
                    return self.expired
                return min(self.configured, remaining)
            time.sleep(0.01)
        raise AssertionError(
            f"decision start marker {self.marker} was not created within "
            f"{self.wait:.1f}s; refusing to clip a child that never started")

    def __lt__(self, elapsed):
        return elapsed > self._clip()

    def __float__(self):
        return self._clip()

    def __repr__(self):
        return f"MarkerGatedBudget({self.marker})"


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
        # Distinct from the check limit so a test can gate only the decision
        # child's remaining-budget call.
        cfg["limits"]["max_architect_seconds"] = 61
        orc.atomic_json(orc.CONFIG_PATH, cfg)
        self.cfg = orc.config()
        # The setup already adopted a policy record for the original config.
        # Drop it with the raw digest so save() re-adopts the policy of the
        # config this test just wrote instead of retaining the stale one.
        self.state.pop("config_policy", None)
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
        # Each check writes a start marker before running.  The test-only
        # budget wrapper holds the clip until that marker exists, so a loaded
        # host cannot consume the stage budget during interpreter startup and
        # turn this into the pre-spawn branch.  The long check's marker plus
        # its 30s sleep proves it was running when the clipped deadline ended
        # it.  The first-check window is only a startup floor; the long check
        # still receives the genuine remaining stage budget.
        self.configure_stage(3.0)
        first_marker = self.root / "first-check-started"
        long_marker = self.root / "long-check-started"
        first_check = (
            "import pathlib,time; "
            f"pathlib.Path({str(first_marker)!r}).write_text('started'); "
            "time.sleep(0.2)")
        long_check = (
            "import pathlib,time; "
            f"pathlib.Path({str(long_marker)!r}).write_text('started'); "
            "time.sleep(30)")
        plan = {"contract_version": 2, "status": "complete", "summary": "plan",
                "invariants": ["Keep behavior"],
                "batches": [{"title": "one", "goal": "g", "acceptance": ["a"],
                             "checks": [[sys.executable, "-c", first_check],
                                        [sys.executable, "-c", long_check]],
                             "risk": "ordinary"}],
                "blocker": ""}
        self.state.update(phase="verify", plan=plan,
                          plan_version=orc.content_hash(plan), batch_index=0,
                          single_batch_fast_path=False)
        orc.save(self.rundir, self.state)
        real_remaining = orc.remaining_budget
        check_limit = float(self.cfg["limits"]["max_check_seconds"])
        calls = {"checks": 0}

        def gated_remaining(configured, deadline):
            if float(configured) != check_limit:
                return real_remaining(configured, deadline)
            calls["checks"] += 1
            if calls["checks"] == 1:
                return MarkerGatedBudget(first_marker, deadline, configured,
                                         expired=5.0)
            return MarkerGatedBudget(long_marker, deadline, configured)

        with patch.object(orc, "remaining_budget",
                          side_effect=gated_remaining):
            result = orc.stage_run("test-run00")
        self.assertFalse(result["ok"])
        self.assertEqual(result["stage"], "verify")
        self.assertTrue(result["pause_reason"])
        state = orc.read_json(self.rundir / "state.json")
        self.assertIn(state["status"], {"uncertain", "blocked"})
        self.assertEqual(state["phase"], "verify")
        self.assertIsNone(state.get("verification"))
        self.assertFalse(state.get("accepted_batches"))
        # The first check completed; the second started and was clipped.
        logs = sorted((self.rundir / "jobs").glob("check-*.log"))
        self.assertGreaterEqual(len(logs), 1)
        evidence = (state.get("check_progress") or {}).get("evidence") or {}
        commands = evidence.get("commands") or []
        self.assertTrue(commands)
        self.assertEqual(commands[0]["returncode"], 0)
        self.assertTrue(first_marker.exists(),
                        "the first check never started")
        self.assertTrue(long_marker.exists(),
                        "the long check never started before its clipped "
                        "timeout; the test would only prove a pre-spawn branch")
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
        # The timeout leaves the exact check record for reconciliation.  It is
        # refused until the recorded tree is proven stopped, then cleared.
        active = after.get("active_check")
        self.assertIsNotNone(active, after)
        # While the check record exists, the next stage remains paused and
        # directs the operator to reconcile instead of starting new work.
        self.assertIn("reconcile", again["error"].lower())
        inspection = orc.inspect_execution(
            active, run_id=after["id"], include_run=True)
        self.assertTrue(inspection["stopped"], inspection["reasons"])
        orc.modify_locked(self.rundir, after, after["id"], "reconcile")
        reconciled = orc.read_json(self.rundir / "state.json")
        self.assertIsNone(reconciled.get("active_check"))
        self.assertEqual(reconciled["phase"], "verify")

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
        # A 20s stage fits the 2s check and the 19s decision individually.
        # Together they exceed the acceptance budget.  The wide margin keeps
        # host load and decision preflight from consuming the whole budget
        # before the decision is spawned; its start marker then proves it was
        # already running when the remaining budget clipped it.
        self.configure_stage(20.0)
        decision_marker = self.root / "decision-started"
        check_marker = self.root / "final-check-started"
        final_check = (
            "import pathlib,time; "
            f"pathlib.Path({str(check_marker)!r}).write_text('started'); "
            "time.sleep(2.0)")
        bin_dir = self.root / "acceptance-deadline-bin"
        bin_dir.mkdir()
        script = bin_dir / "codex"
        script.write_text(r'''#!/usr/bin/env python3
import json, os, pathlib, sys, time
args = sys.argv[1:]
if '--version' in args:
    print('0.167.0')
    sys.exit(0)
if '--output-last-message' in args:
    output = pathlib.Path(args[args.index('--output-last-message') + 1])
    kind = output.parent.name.split('-')[0]
    if kind == 'decision':
        pathlib.Path(os.environ['FAKE_DECISION_MARKER']).write_text(str(os.getpid()))
        time.sleep(19.0)
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
                             "checks": [[sys.executable, "-c", final_check]],
                             "risk": "ordinary"}],
                "blocker": ""}
        self.state.update(phase="verify", plan=plan,
                          plan_version=orc.content_hash(plan), batch_index=0,
                          single_batch_fast_path=True)
        orc.save(self.rundir, self.state)
        with patch.dict(os.environ, {"PATH": str(bin_dir) + ":" + os.environ["PATH"],
                                     "OPENAI_API_KEY": "",
                                     "FAKE_DECISION_MARKER": str(decision_marker)}):
            evidence = orc.run_checks(self.rundir, self.state, self.cfg,
                                      self.project, plan["batches"][0])
            self.assertTrue(evidence["passed"], evidence)
            self.state.update(phase="accept", review={
                "contract_version": 2, "status": "complete", "summary": "reviewed",
                "findings": [], "files": [], "tests": [], "evidence": ["app.py:1"],
                "unknowns": [], "blocker": ""}, check_progress=None)
            orc.save(self.rundir, self.state)
            real_remaining = orc.remaining_budget

            architect_limit = float(self.cfg["limits"]["max_architect_seconds"])
            check_limit = float(self.cfg["limits"]["max_check_seconds"])

            def gated_remaining(configured, deadline):
                if float(configured) == check_limit:
                    # Prerequisite final check: let it start and finish even
                    # if load consumed the stage budget first, so the decision
                    # budget test is reached deterministically.
                    return MarkerGatedBudget(check_marker, deadline, configured,
                                             expired=8.0)
                if float(configured) != architect_limit:
                    return real_remaining(configured, deadline)
                # The decision clip still uses the genuine remaining stage
                # budget, but is applied only after its marker exists.
                return MarkerGatedBudget(decision_marker, deadline, configured)

            with patch.object(orc, "remaining_budget",
                              side_effect=gated_remaining):
                result = orc.stage_run("test-run00")
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["stage"], "accept")
        self.assertTrue(decision_marker.exists(),
                        "the decision child never started before the clipped "
                        "budget; the test would only prove a pre-spawn branch")
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
