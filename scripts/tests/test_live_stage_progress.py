"""Live stage progress: attempt identity, read-only observation and transport.

Deterministic; no paid model calls.  Real installed clients are checked
separately (see docs/validation.md).
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import re
import select
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

import test_interactive_recovery as recovery
from test_interactive_recovery import _install_fake_clis, _wait_for
from test_orchestrator import SRC, orc


def _records(run_dir):
    return [json.loads(line) for line in
            (Path(run_dir) / orc.JOURNAL_FILE).read_text().splitlines() if line.strip()]


def _append(run_dir, record):
    with (Path(run_dir) / orc.JOURNAL_FILE).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record) + "\n")


def _identity(pid=None):
    pid = pid or os.getpid()
    stat = orc.process_stat(pid)
    return {"boot_id": orc._boot_identity(), "owner_pid": pid,
            "owner_pid_start": stat["starttime"]}


class ProgressFixture(unittest.TestCase):
    """A real start_run state with a fake CLI on PATH."""

    def setUp(self):
        recovery.ControlTests.setUp(self)
        self.runs = self.root / "progress-runs"
        self.fakebin = _install_fake_clis(self.root)
        self.env = {"PATH": str(self.fakebin) + ":" + os.environ["PATH"],
                    "FAKE_HISTORY": str(self.root / "progress-history"),
                    "OPENAI_API_KEY": ""}
        self._state_patch = patch.object(orc, "DEFAULT_STATE", self.runs)
        self._state_patch.start()
        self.addCleanup(self._state_patch.stop)
        self._env_patch = patch.dict(os.environ, self.env)
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)
        started = orc.start_run(project=str(self.project), goal="Show live progress",
                                host="codex", skip_doctor=True, interactive=True)
        self.run_id = started["run_id"]
        self.folder = self.runs / self.run_id

    def stage(self, **kwargs):
        with patch.object(orc, "DEFAULT_STATE", self.runs), \
                patch.dict(os.environ, self.env):
            return orc.stage_run(self.run_id, **kwargs)

    def snapshot(self):
        with patch.object(orc, "DEFAULT_STATE", self.runs), \
                patch.dict(os.environ, self.env):
            return orc.stage_progress(self.run_id)

    def synthetic_start(self, **overrides):
        record = {"event": "stage_start", "stage": "implement", "role": "architect",
                  "agent_label": "Architect", "task": "Implement batch 1",
                  "expected": "Structured workflow result", "started_at": "now",
                  "started_at_offset": 0, "batch": {"label": "Batch 1/1", "index": 0,
                                                   "total": 1},
                  "attempt": "synthetic0001",
                  "monotonic_started": round(time.monotonic(), 3),
                  "route": {"provider": "codex", "model": "gpt-5.1", "effort": "high",
                            "effective": {"model": "gpt-5.1", "effort": "high"},
                            "billing": "subscription"}}
        record.update(_identity())
        record.update(overrides)
        _append(self.folder, record)
        return record


class AttemptIdentityTests(ProgressFixture):
    def test_phase_transition_keeps_one_matching_attempt(self):
        result = self.stage()
        self.assertEqual(result["stage"], "plan")
        records = _records(self.folder)
        starts = [row for row in records if row.get("event") == "stage_start"]
        ends = [row for row in records if row.get("event") == "stage_end"]
        self.assertEqual(len(starts), 1)
        self.assertEqual(len(ends), 1)
        self.assertTrue(starts[0]["attempt"])
        self.assertEqual(starts[0]["attempt"], ends[0]["attempt"])
        self.assertTrue(starts[0]["boot_id"])
        snapshot = self.snapshot()
        self.assertTrue(snapshot["available"])
        self.assertEqual(snapshot["attempt_id"], starts[0]["attempt"])
        self.assertEqual(snapshot["ownership"], "complete")
        self.assertFalse(snapshot["active"])
        self.assertEqual(snapshot["elapsed_source"], "recorded")
        self.assertEqual(snapshot["elapsed_seconds"], ends[0]["elapsed_seconds"])
        self.assertEqual(snapshot["stage"], "plan")
        self.assertEqual(snapshot["phase"], "implement")
        self.assertIsNotNone(snapshot["next_action"])
        status = orc.status_run(self.run_id)
        self.assertEqual(status["stage_progress"]["attempt_id"], starts[0]["attempt"])

    def test_legacy_rows_without_attempt_identity_stay_readable(self):
        _append(self.folder, {"event": "stage_start", "stage": "plan",
                              "role": "architect", "agent_label": "Architect",
                              "task": "Legacy plan", "started_at": "then"})
        _append(self.folder, {"event": "stage_end", "stage": "plan",
                              "elapsed_seconds": 4.0, "outcome": "complete",
                              "next_action": "orchestrator_stage"})
        snapshot = self.snapshot()
        self.assertTrue(snapshot["available"])
        self.assertIsNone(snapshot["attempt_id"])
        self.assertEqual(snapshot["ownership"], "complete")
        self.assertEqual(snapshot["elapsed_seconds"], 4.0)
        self.assertEqual(snapshot["task"], "Legacy plan")

    def test_quiet_live_attempt_ticks_then_stops_at_recorded_elapsed(self):
        self.synthetic_start(monotonic_started=round(time.monotonic() - 3.0, 3))
        first = self.snapshot()
        self.assertTrue(first["active"], first)
        self.assertEqual(first["elapsed_source"], "live")
        self.assertGreaterEqual(first["elapsed_seconds"], 2.9)
        self.assertTrue(first["activity"])
        time.sleep(0.25)
        second = self.snapshot()
        self.assertGreater(second["elapsed_seconds"], first["elapsed_seconds"])
        _append(self.folder, {"event": "stage_end", "stage": "implement",
                              "attempt": "synthetic0001", "elapsed_seconds": 7.5,
                              "outcome": "complete", "next_action": "orchestrator_stage"})
        ended = self.snapshot()
        self.assertFalse(ended["active"])
        self.assertEqual(ended["elapsed_source"], "recorded")
        self.assertEqual(ended["elapsed_seconds"], 7.5)

    def test_foreign_boot_and_pid_reuse_never_look_active(self):
        self.synthetic_start(boot_id="another-boot", monotonic_started=1.0)
        stale = self.snapshot()
        self.assertFalse(stale["active"])
        self.assertEqual(stale["ownership"], "stale")
        self.assertIsNone(stale["elapsed_seconds"])
        self.assertIn("no longer running", stale["activity"])
        _append(self.folder, {"event": "stage_end", "stage": "implement",
                              "attempt": "synthetic0001", "outcome": "complete"})
        self.synthetic_start(attempt="synthetic0002", owner_pid_start="1",
                             monotonic_started=round(time.monotonic() - 1, 3))
        reused = self.snapshot()
        self.assertFalse(reused["active"])
        self.assertEqual(reused["ownership"], "stale")
        self.assertIsNone(reused["elapsed_seconds"])

    def test_paused_run_does_not_tick(self):
        self.synthetic_start(monotonic_started=round(time.monotonic() - 5, 3))
        state = json.loads((self.folder / "state.json").read_text())
        state["status"] = "paused"
        state["pause_reason"] = "operator paused"
        (self.folder / "state.json").write_text(json.dumps(state))
        snapshot = self.snapshot()
        self.assertFalse(snapshot["active"])
        self.assertIsNone(snapshot["elapsed_seconds"])
        self.assertIn("paused", snapshot["activity"])

    def test_observer_read_is_side_effect_free(self):
        self.stage()
        before = {path: path.read_bytes() for path in self.folder.iterdir()
                  if path.is_file()}
        before_stat = {path: path.stat().st_mtime_ns for path in self.folder.iterdir()
                       if path.is_file()}
        for _ in range(3):
            self.snapshot()
            orc.status_run(self.run_id)
        after = {path: path.read_bytes() for path in self.folder.iterdir()
                 if path.is_file()}
        after_stat = {path: path.stat().st_mtime_ns for path in self.folder.iterdir()
                      if path.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(before_stat, after_stat)

    def test_task_metadata_is_bounded_and_terminal_safe(self):
        hostile = "Implement \x1b[31mred\x1b[0m\nsecond\ttab" + "x" * 400
        self.synthetic_start(task=hostile, expected="ok\nAlso bad \x07" + "y" * 400)
        snapshot = self.snapshot()
        for value in (snapshot["task"], snapshot["expected"]):
            self.assertNotIn("\x1b", value)
            self.assertNotIn("\n", value)
            self.assertNotIn("\t", value)
            self.assertLessEqual(len(value), 200)
        self.assertNotIn("\x1b", snapshot["activity"])

    def test_verification_task_never_embeds_check_argv(self):
        state = json.loads((self.folder / "state.json").read_text())
        state["phase"] = "verify"
        state["plan"] = {"batches": [{"title": "b", "goal": "g",
                                      "checks": [["echo", "SECRET-CHECK-ARGV"]]}]}
        (self.folder / "state.json").write_text(json.dumps(state))
        _append(self.folder, {"event": "stage_start", "stage": "verify",
                              "role": None, "agent_label": "Supervisor",
                              "attempt": "synthetic-verify",
                              "monotonic_started": round(time.monotonic(), 3),
                              **_identity()})
        snapshot = self.snapshot()
        self.assertEqual(snapshot["task"], orc._VERIFICATION_TASK)
        self.assertNotIn("SECRET-CHECK-ARGV", snapshot["task"])

    def test_worker_stream_activity_is_bounded_and_content_free(self):
        job_dir = self.folder / "jobs" / "job-1"
        job_dir.mkdir(parents=True)
        payload = "\n".join([
            '{"type":"unknown","part":{"text":"private reasoning"}}',
            '{"type":"tool","part":{"input":"SECRET ARG"}}',
            '{"type":"tool","part":{"input":"' + "z" * 40000 + '"}}',
            '{"type":"step_start","part":{}}',
            "not-json",
        ])
        (job_dir / "events.log").write_text(payload)
        label = orc._worker_stream_activity(self.folder, {"path": str(job_dir)})
        self.assertEqual(label, "worker step running")
        self.assertNotIn("SECRET", label)
        (job_dir / "events.log").write_text('{"type":"unknown"}\nnot json\n')
        self.assertIsNone(orc._worker_stream_activity(self.folder, {"path": str(job_dir)}))

    def test_oversized_single_journal_record_stays_readable(self):
        huge = {"event": "stage_start", "stage": "implement", "attempt": "huge",
                "payload": "x" * (300 * 1024)}
        with (self.folder / orc.JOURNAL_FILE).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(huge) + "\n")
        tail = orc.journal_tail(self.folder, 5)
        self.assertEqual(tail[-1]["attempt"], "huge")

    def test_missing_worker_stream_keeps_waiting_activity(self):
        self.synthetic_start()
        snapshot = self.snapshot()
        self.assertEqual(snapshot["activity"], "supervisor processing the worker report")


class ProgressMessageTests(unittest.TestCase):
    def test_message_is_bounded_and_hides_control_bytes(self):
        snapshot = {"agent_label": "Implementer", "stage": "implement",
                    "batch": {"label": "Batch 1/2"}, "model": "gpt-5.1", "effort": "high",
                    "activity": "worker running\x1b[2J\n" + "x" * 500,
                    "elapsed_seconds": 3.0, "outcome": None}
        message = orc.stage_progress_message(snapshot)
        self.assertNotIn("\x1b", message)
        self.assertNotIn("\n", message)
        self.assertLessEqual(len(message), 240)
        self.assertIn("3s", message)

    def test_token_validation_rejects_booleans_and_objects(self):
        self.assertTrue(orc._valid_progress_token(1))
        self.assertTrue(orc._valid_progress_token("abc"))
        self.assertFalse(orc._valid_progress_token(True))
        self.assertFalse(orc._valid_progress_token(False))
        self.assertFalse(orc._valid_progress_token(None))
        self.assertFalse(orc._valid_progress_token({"a": 1}))
        self.assertFalse(orc._valid_progress_token("   "))


class ProgressEmitterTests(unittest.TestCase):
    def _snapshot(self, started, *, active=True, ownership="active",
                  elapsed=1.0, source="live", outcome=None):
        return {"available": True, "active": active, "ownership": ownership,
                "attempt_monotonic_started": started, "elapsed_seconds": elapsed,
                "elapsed_source": source, "outcome": outcome, "stage": "implement",
                "agent_label": "Implementer", "batch": {"label": "Batch 1/1"},
                "model": "gpt-5.1", "effort": "high", "activity": "worker running"}

    def test_updates_are_ordered_and_bounded(self):
        sent = []
        stop = threading.Event()
        now = time.monotonic()

        def reader(_run_id):
            value = self._snapshot(now)
            value["elapsed_seconds"] = round(time.monotonic() - now, 1)
            return value

        def send(sequence, token, message):
            sent.append((sequence, token, message))
            if sequence >= 2:
                stop.set()

        orc._emit_stage_progress(send, 7, "run", now, stop,
                                 snapshot_reader=reader, interval=0.05)
        self.assertGreaterEqual(len(sent), 2)
        self.assertEqual([row[0] for row in sent], list(range(1, len(sent) + 1)))
        self.assertTrue(all(row[1] == 7 for row in sent))
        self.assertTrue(all(len(row[2]) <= 240 for row in sent))

    def test_older_attempt_is_never_reported(self):
        sent = []
        stop = threading.Event()
        threading.Timer(0.3, stop.set).start()
        orc._emit_stage_progress(
            lambda *row: sent.append(row), 1, "run", time.monotonic(), stop,
            snapshot_reader=lambda _run_id: self._snapshot(time.monotonic() - 30),
            interval=0.05)
        self.assertEqual(sent, [])

    def test_unavailable_snapshot_is_not_reported(self):
        sent = []
        stop = threading.Event()
        threading.Timer(0.3, stop.set).start()
        orc._emit_stage_progress(
            lambda *row: sent.append(row), 1, "run", time.monotonic(), stop,
            snapshot_reader=lambda _run_id: {"available": False}, interval=0.05)
        self.assertEqual(sent, [])

    def test_completion_sends_one_final_update(self):
        sent = []
        now = time.monotonic()
        orc._emit_stage_progress(
            lambda *row: sent.append(row), "tok", "run", now, threading.Event(),
            snapshot_reader=lambda _run_id: self._snapshot(
                now, active=False, ownership="complete", elapsed=2.5,
                source="recorded", outcome="complete"),
            interval=0.05)
        self.assertEqual(len(sent), 1)
        self.assertIn("complete", sent[0][2])


class McpProgressTransportTests(ProgressFixture):
    def _server(self, token=None, run_id=None, name="orchestrator_stage"):
        params = {"name": name, "arguments": {"run_id": run_id or self.run_id}}
        if token is not None:
            params["_meta"] = {"progressToken": token}
        return {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": params}

    def _run_server(self, requests, env_extra=None, timeout=90):
        env = os.environ.copy()
        env.update({"PATH": str(self.fakebin) + ":" + env["PATH"],
                    "FAKE_HISTORY": str(self.root / "mcp-progress-history"),
                    "OPENAI_API_KEY": "", "ABDULLAH_STATE_DIR": str(self.runs)})
        env.update(env_extra or {})
        proc = subprocess.Popen([sys.executable, str(SRC), "mcp"],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, env=env)
        def cleanup():
            try:
                proc.stdin.close()
            except OSError:
                pass
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            for stream in (proc.stdout, proc.stderr):
                try:
                    stream.close()
                except OSError:
                    pass
        self.addCleanup(cleanup)
        sent = []
        for request in requests:
            proc.stdin.write(json.dumps(request) + "\n")
            proc.stdin.flush()
        return proc, sent

    def _recv(self, proc, timeout=60):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            ready, _, _ = select.select([proc.stdout], [], [], 0.1)
            if ready:
                line = proc.stdout.readline()
                if line:
                    return json.loads(line)
        raise AssertionError("MCP response timeout")

    def test_multiple_updates_arrive_before_the_final_stage_response(self):
        proc, _ = self._run_server([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                "name": "orchestrator_stage",
                "arguments": {"run_id": self.run_id}}},
        ], env_extra={"FAKE_SLEEP": "2"})
        self._recv(proc)  # initialize
        self._recv(proc, timeout=90)  # plan stage
        # Implementation is slow, so the progress window is deterministic.
        proc.stdin.write(json.dumps(self._server(token=11)) + "\n")
        proc.stdin.flush()
        progress = []
        final = None
        end = time.monotonic() + 90
        while time.monotonic() < end and final is None:
            message = self._recv(proc, timeout=90)
            if message.get("method") == "notifications/progress":
                progress.append(message["params"])
            else:
                final = message
        self.assertIsNotNone(final, "no final stage response")
        self.assertGreaterEqual(len(progress), 2, progress)
        sequence = [row["progress"] for row in progress]
        self.assertEqual(sequence, sorted(sequence))
        self.assertEqual(len(set(sequence)), len(sequence))
        self.assertTrue(all(row["progressToken"] == 11 for row in progress))
        self.assertTrue(all("total" not in row for row in progress))
        self.assertTrue(all(row.get("message") for row in progress))
        # No progress may follow the response.
        ready, _, _ = select.select([proc.stdout], [], [], 1.0)
        if ready:
            trailing = proc.stdout.readline()
            self.assertFalse(trailing.strip(), trailing)

    def test_tokenless_and_invalid_tokens_get_no_progress(self):
        proc, _ = self._run_server([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                "name": "orchestrator_stage", "arguments": {"run_id": self.run_id}}},
        ], env_extra={"FAKE_SLEEP": "1"})
        self._recv(proc)  # initialize
        self._recv(proc, timeout=90)  # plan
        proc.stdin.write(json.dumps(self._server(token=True)) + "\n")
        proc.stdin.flush()
        message = self._recv(proc, timeout=90)
        self.assertEqual(message.get("id"), 5)
        ready, _, _ = select.select([proc.stdout], [], [], 0.8)
        self.assertFalse(ready, "progress arrived for an invalid token")

    def test_cancellation_stops_progress_before_the_response(self):
        proc, _ = self._run_server([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                "name": "orchestrator_stage",
                "arguments": {"run_id": self.run_id}}},
        ], env_extra={"FAKE_SLEEP": "4"})
        self._recv(proc)  # initialize
        self._recv(proc, timeout=90)  # plan
        proc.stdin.write(json.dumps(self._server(token="cancel-me")) + "\n")
        proc.stdin.flush()
        first = self._recv(proc, timeout=90)
        self.assertEqual(first.get("method"), "notifications/progress", first)
        proc.stdin.write(json.dumps({"jsonrpc": "2.0",
                                     "method": "notifications/cancelled",
                                     "params": {"requestId": 5,
                                                "reason": "user stop"}}) + "\n")
        proc.stdin.flush()
        final = None
        after_final = []
        end = time.monotonic() + 90
        while time.monotonic() < end:
            message = self._recv(proc, timeout=90)
            if final is None and message.get("id") == 5:
                final = message
                # Drain immediately-following lines, if any, for a short window.
                break
        self.assertIsNotNone(final, "no final cancellation response")
        ready, _, _ = select.select([proc.stdout], [], [], 1.0)
        while ready:
            after_final.append(proc.stdout.readline())
            ready, _, _ = select.select([proc.stdout], [], [], 0.2)
        self.assertFalse([line for line in after_final if line.strip()],
                         after_final)
        payload = json.loads(final["result"]["content"][0]["text"])
        self.assertIn(payload["status"], {"paused", "uncertain"})

    def test_refused_second_call_does_not_mirror_the_first_activity(self):
        proc, _ = self._run_server([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        ])
        self._recv(proc)
        unknown = self._server(token=5, run_id="missing-run-id")
        proc.stdin.write(json.dumps(unknown) + "\n")
        proc.stdin.flush()
        message = self._recv(proc, timeout=30)
        self.assertEqual(message.get("id"), 5)
        payload = json.loads(message["result"]["content"][0]["text"])
        self.assertFalse(payload["ok"])
        ready, _, _ = select.select([proc.stdout], [], [], 0.8)
        self.assertFalse(ready, "refused call mirrored another attempt's progress")


class TerminalViewerTests(ProgressFixture):
    def test_viewer_shows_next_stage_metadata_before_dispatch(self):
        out = io.StringIO()
        with patch.object(orc, "DEFAULT_STATE", self.runs), \
                patch.dict(os.environ, self.env):
            orc.status_follow(self.run_id, out, inplace=True, interval=0.05,
                              max_seconds=0.3)
        text = out.getvalue()
        self.assertIn("waiting for the next stage", text)
        self.assertIn("plan", text)

    def test_viewer_advances_while_the_worker_runs_and_cannot_stop_it(self):
        self.stage()  # plan, next stage is implement
        out = io.StringIO()
        result = {}
        os.environ["FAKE_SLEEP"] = "2"
        try:
            def work():
                with patch.object(orc, "DEFAULT_STATE", self.runs), \
                        patch.dict(os.environ, self.env):
                    result["value"] = orc.stage_run(self.run_id)
            thread = threading.Thread(target=work)
            thread.start()
            _wait_for(lambda: self._active(), timeout=30)
            with patch.object(orc, "DEFAULT_STATE", self.runs), \
                    patch.dict(os.environ, self.env):
                orc.status_follow(self.run_id, out, inplace=True, interval=0.2,
                                  max_seconds=1.4)
            self.assertTrue(thread.is_alive(), "viewer stopped the worker")
            state = json.loads((self.folder / "state.json").read_text())
            self.assertEqual(state["status"], "running")
            thread.join(timeout=60)
        finally:
            os.environ.pop("FAKE_SLEEP", None)
        self.assertFalse(thread.is_alive())
        text = out.getvalue()
        self.assertIn("implement", text.lower())
        self.assertIn("elapsed", text)
        self.assertIn("worker running", text)
        self.assertTrue(result["value"]["ok"])
        # Completion view shows measured elapsed and the next action.
        final = io.StringIO()
        with patch.object(orc, "DEFAULT_STATE", self.runs), \
                patch.dict(os.environ, self.env):
            orc.status_follow(self.run_id, final, inplace=True, interval=0.05,
                              max_seconds=1.0)
        self.assertIn("measured", final.getvalue())

    def test_viewer_attaches_during_a_running_stage(self):
        self.stage()
        out = io.StringIO()
        os.environ["FAKE_SLEEP"] = "2"
        thread = None
        try:
            def work():
                with patch.object(orc, "DEFAULT_STATE", self.runs), \
                        patch.dict(os.environ, self.env):
                    orc.stage_run(self.run_id)
            thread = threading.Thread(target=work)
            thread.start()
            _wait_for(lambda: self._active(), timeout=30)
            with patch.object(orc, "DEFAULT_STATE", self.runs), \
                    patch.dict(os.environ, self.env):
                attempt = orc.stage_progress(self.run_id)["attempt_id"]
                orc.status_follow(self.run_id, out, inplace=True, interval=0.2,
                                  max_seconds=0.6)
            thread.join(timeout=60)
        finally:
            os.environ.pop("FAKE_SLEEP", None)
            if thread is not None:
                thread.join(timeout=60)
        text = out.getvalue()
        self.assertIn("Implementer".lower(), text.lower())
        self.assertIn(attempt, text)
        self.assertIn("elapsed", text)

    def _active(self):
        state = json.loads((self.folder / "state.json").read_text())
        return bool(state.get("active_job")
                    and "# implemented" in (self.project / "app.py").read_text())


if __name__ == "__main__":
    unittest.main()
