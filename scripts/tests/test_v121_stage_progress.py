"""v1.2.1 bounded stage progress, milestones and quiet-stage heartbeats."""
from __future__ import annotations

import json
import os
import time
import unittest

import test_orchestrator as baseline

orc = baseline.orc


class StageProgressTests(unittest.TestCase):
    setUp = baseline.ControlTests.setUp
    tearDown = baseline.ControlTests.tearDown

    def start_attempt(self, elapsed=0.0, attempt="attempt-1"):
        identity = orc.process_identity(os.getpid()) or {}
        self.state["status"] = "running"
        orc.journal_event(
            self.rundir, self.state, "stage_start", stage="implement",
            role="implementer", agent_label="Implementer", task="write code",
            expected="focused change", attempt=attempt,
            monotonic_started=time.monotonic() - elapsed,
            boot_id=orc._boot_identity(), owner_pid=os.getpid(),
            owner_pid_start=identity.get("pid_start"),
            batch={"index": 0, "label": "batch 1"})
        orc.save(self.rundir, self.state)
        return attempt

    def test_worker_milestone_is_labelled_sanitized_and_bounded(self):
        attempt = self.start_attempt()
        orc._STAGE_CONTEXT.attempt = attempt
        try:
            orc._record_stage_milestone(
                self.rundir, self.state, "tests written\x1b[31m",
                source="worker_reported", assignment="writer-1",
                next_action="run focused tests")
        finally:
            orc._STAGE_CONTEXT.attempt = None
        snapshot = orc.stage_snapshot(self.rundir, self.state)
        self.assertEqual(snapshot["milestone"], "reported: tests written")
        self.assertEqual(snapshot["milestone_source"], "worker_reported")
        self.assertTrue(snapshot["milestone_reported"])
        self.assertEqual(snapshot["assignment"], "writer-1")
        self.assertEqual(snapshot["observed_next_action"], "run focused tests")
        self.assertNotIn("\x1b", snapshot["milestone"])

    def test_supervisor_milestone_is_not_labelled_as_worker_reported(self):
        attempt = self.start_attempt()
        orc.journal_event(self.rundir, self.state, "stage_milestone",
                          attempt=attempt, milestone="plan recorded",
                          source="supervisor")
        snapshot = orc.stage_snapshot(self.rundir, self.state)
        self.assertEqual(snapshot["milestone"], "plan recorded")
        self.assertFalse(snapshot["milestone_reported"])

    def test_heartbeat_is_coalesced_and_marks_45_minutes(self):
        attempt = self.start_attempt(elapsed=2705.0)
        first = orc._coalesced_heartbeat(self.rundir, self.state, attempt, 2705.0)
        second = orc._coalesced_heartbeat(self.rundir, self.state, attempt, 2706.0)
        third = orc._coalesced_heartbeat(self.rundir, self.state, attempt, 2740.0)
        self.assertIsNotNone(first)
        self.assertIsNone(second, "same 30s bucket wrote a duplicate heartbeat")
        self.assertIsNotNone(third)
        events = [event for event in orc.journal_tail_bounded(self.rundir, 200)
                  if event.get("event") == "stage_heartbeat"]
        self.assertEqual([event["bucket"] for event in events], [90, 91])
        snapshot = orc.stage_snapshot(self.rundir, self.state)
        self.assertTrue(snapshot["long_running"])
        self.assertIn("45-minute informational marker",
                      snapshot["long_running_marker"])
        self.assertIn("never restarts", snapshot["long_running_marker"])
        self.assertIsNotNone(snapshot["elapsed_seconds"])

    def test_structured_worker_signal_ignores_tool_start(self):
        jobdir = self.rundir / "jobs" / "writer-lane"
        jobdir.mkdir(parents=True)
        job = {"role": "implementer", "path": str(jobdir),
               "route": {"provider": "opencode"}}
        events = jobdir / "events.log"
        events.write_text("\n".join([
            json.dumps({"type": "tool_use", "status": "started",
                        "part": {"tool": "bash"}}),
            json.dumps({"type": "text", "part": {"text": "working"}}),
        ]) + "\n")
        self.assertIsNone(orc._structured_worker_milestone(self.rundir, job))
        events.write_text(events.read_text() + json.dumps(
            {"type": "milestone", "message": "focused tests green"}) + "\n")
        self.assertEqual(orc._structured_worker_milestone(self.rundir, job),
                         "reported: focused tests green")
        events.write_text(events.read_text() + json.dumps(
            {"type": "tool_use", "status": "completed",
             "part": {"tool": "read"}}) + "\n")
        self.assertIn("tool completion observed",
                      orc._structured_worker_milestone(self.rundir, job))

    def test_viewer_and_mcp_message_expose_milestone_and_heartbeat(self):
        attempt = self.start_attempt(elapsed=61.0)
        orc.journal_event(self.rundir, self.state, "stage_milestone",
                          attempt=attempt, milestone="reported: check finished",
                          source="worker_reported")
        import datetime as dt
        old = (dt.datetime.now(dt.timezone.utc)
               - dt.timedelta(seconds=61)).isoformat()
        with (self.rundir / "journal.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({
                "at": old, "event": "stage_activity", "attempt": attempt,
                "activity": "worker launched", "run_id": self.state["id"]}) + "\n")
        snapshot = orc.stage_snapshot(self.rundir, self.state)
        viewer = "\n".join(orc._viewer_lines(self.state, snapshot))
        self.assertIn("reported: check finished", viewer)
        self.assertIn("no new progress", viewer)
        message = orc.stage_progress_message(snapshot)
        self.assertIn("reported: check finished", message)
        payload = orc.stage_payload(self.rundir, self.state, "implement",
                                    "implementer", "task", "expected", 61.0)
        self.assertEqual(payload["progress"]["milestone"],
                         "reported: check finished")
        self.assertTrue(payload["progress"]["informational_only"])


if __name__ == "__main__":
    unittest.main()
