"""Live stage progress: attempt identity, read-only observation and transport.

Deterministic; no paid model calls.  Real installed clients are checked
separately (see docs/validation.md).
"""
from __future__ import annotations

import io
import json
from contextlib import contextmanager
import os
from pathlib import Path
import queue
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
        _append(self.folder, {"event": "stage_end", "attempt": "synthetic0002",
                              "outcome": "complete"})
        self.synthetic_start(attempt="synthetic0003", owner_pid_start=None,
                             monotonic_started=round(time.monotonic() - 1, 3))
        unproven = self.snapshot()
        self.assertFalse(unproven["active"])
        self.assertEqual(unproven["ownership"], "unknown")
        self.assertIn("could not be proven", unproven["activity"])

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

    def test_unexpected_failure_keeps_no_partial_save_and_records_error(self):
        before = (self.folder / "state.json").read_bytes()
        with patch.object(orc, "advance", side_effect=TypeError("boom")):
            with self.assertRaises(TypeError):
                self.stage()
        self.assertEqual((self.folder / "state.json").read_bytes(), before)
        ends = [row for row in _records(self.folder) if row.get("event") == "stage_end"]
        self.assertTrue(ends)
        self.assertEqual(ends[-1]["outcome"], "error")
        self.assertIn("TypeError", ends[-1]["error"])
        snapshot = self.snapshot()
        self.assertFalse(snapshot["active"])
        self.assertEqual(snapshot["outcome"], "error")

    @staticmethod
    @contextmanager
    def failing_activity_journal():
        original = orc.journal_event

        def journal(run_dir, state, event, **fields):
            if event == "stage_activity":
                raise OSError("injected advisory activity failure")
            return original(run_dir, state, event, **fields)

        with patch.object(orc, "journal_event", side_effect=journal):
            yield

    def test_activity_write_failure_during_admission_and_worker_does_not_abort(self):
        with patch.object(orc, "DEFAULT_STATE", self.runs), \
                patch.dict(os.environ, self.env), \
                self.failing_activity_journal():
            result = orc.stage_run(self.run_id)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["stage"], "plan")
        self.assertEqual(result["phase"], "implement")
        self.assertIsNone(orc._current_attempt())
        records = _records(self.folder)
        starts = [row for row in records if row.get("event") == "stage_start"]
        ends = [row for row in records if row.get("event") == "stage_end"]
        self.assertEqual(starts[-1]["attempt"], ends[-1]["attempt"])
        self.assertEqual(ends[-1]["outcome"], "complete")
        self.assertTrue(ends[-1]["elapsed_seconds"] > 0)
        snapshot = self.snapshot()
        self.assertFalse(snapshot["active"])
        self.assertEqual(snapshot["ownership"], "complete")
        self.assertIn("stage finished", snapshot["activity"])

    def test_activity_write_failure_during_verification_preserves_evidence(self):
        self.stage()  # plan
        self.stage()  # implement
        self.assertIn("# implemented", (self.project / "app.py").read_text())
        with patch.object(orc, "DEFAULT_STATE", self.runs), \
                patch.dict(os.environ, self.env), \
                self.failing_activity_journal():
            result = orc.stage_run(self.run_id)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["stage"], "verify")
        self.assertTrue(result["report"]["passed"])
        self.assertIsNone(orc._current_attempt())
        state = json.loads((self.folder / "state.json").read_text())
        self.assertTrue(state["verification"]["passed"])
        self.assertIn("# implemented", (self.project / "app.py").read_text())
        ends = [row for row in _records(self.folder) if row.get("event") == "stage_end"]
        self.assertEqual(ends[-1]["outcome"], "complete")

    def test_task_metadata_is_bounded_and_terminal_safe(self):
        hostile = ("Implement \x1b[31mred\x1b[0m\nsecond\ttab"
                   "\x9b31mC1\x9d" + "x" * 400)
        self.synthetic_start(task=hostile, expected="ok\nAlso bad \x07" + "y" * 400)
        snapshot = self.snapshot()
        for value in (snapshot["task"], snapshot["expected"]):
            self.assertNotIn("\x1b", value)
            self.assertNotIn("\n", value)
            self.assertNotIn("\t", value)
            self.assertFalse(any(127 <= ord(char) <= 159 for char in value))
            self.assertLessEqual(len(value), 200)
        self.assertNotIn("\x1b", snapshot["activity"])

    def test_verification_task_never_embeds_check_argv(self):
        state = json.loads((self.folder / "state.json").read_text())
        state["phase"] = "verify"
        state["plan"] = {"batches": [{"title": "b", "goal": "g",
                                      "checks": [["echo", "SECRET-CHECK-ARGV"]]}]}
        (self.folder / "state.json").write_text(json.dumps(state))
        raw = ('Run supervisor verification: [["echo", '
               '"TEST-ONLY-ARGV-MARKER"]]')
        _append(self.folder, {"event": "stage_start", "stage": "verify",
                              "role": None, "agent_label": "Supervisor",
                              "task": raw,
                              "attempt": "synthetic-verify",
                              "monotonic_started": round(time.monotonic(), 3),
                              **_identity()})
        snapshot = self.snapshot()
        self.assertEqual(snapshot["task"], orc._VERIFICATION_TASK)
        self.assertNotIn("TEST-ONLY-ARGV-MARKER", snapshot["task"])
        # The upcoming stage preview must be safe even when the phase is verify.
        self.assertEqual(snapshot["next"]["task"], orc._VERIFICATION_TASK)
        self.assertNotIn("SECRET-CHECK-ARGV", json.dumps(snapshot["next"]))

    def test_activity_never_inherits_a_previous_attempt(self):
        _append(self.folder, {"event": "stage_start", "stage": "verify",
                              "attempt": "old-attempt",
                              "monotonic_started": round(time.monotonic() - 20, 3),
                              **_identity()})
        _append(self.folder, {"event": "stage_activity",
                              "activity": "verification_complete",
                              "attempt": "old-attempt"})
        _append(self.folder, {"event": "stage_end", "stage": "verify",
                              "attempt": "old-attempt", "outcome": "complete",
                              "elapsed_seconds": 3.0})
        self.synthetic_start()
        self.assertEqual(self.snapshot()["activity"], "preparing the stage")

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
        job = {"path": str(job_dir), "route": {"provider": "opencode"}}
        label = orc._worker_stream_activity(self.folder, job)
        self.assertEqual(label, "worker step running")
        self.assertNotIn("SECRET", label)
        (job_dir / "events.log").write_text('{"type":"unknown"}\nnot json\n')
        self.assertIsNone(orc._worker_stream_activity(self.folder, job))

    def test_malformed_structured_worker_records_are_ignored(self):
        job_dir = self.folder / "jobs" / "job-1"
        job_dir.mkdir(parents=True)
        (job_dir / "events.log").write_text(
            '{"type":{"unexpected":true}}\n'
            '{"type":["tool"]}\n'
            '{"type":null}\n'
            '{"type":"tool","part":{"input":"SECRET"}}\n')
        job = {"path": str(job_dir), "route": {"provider": "opencode"}}
        self.assertEqual(orc._worker_stream_activity(self.folder, job),
                         "worker using a tool")

    def test_plain_worker_providers_are_never_parsed(self):
        job_dir = self.folder / "jobs" / "job-1"
        job_dir.mkdir(parents=True)
        (job_dir / "events.log").write_text('{"type":"tool"}\n')
        for provider in ("codex", "claude"):
            job = {"path": str(job_dir), "route": {"provider": provider}}
            self.assertIsNone(orc._worker_stream_activity(self.folder, job))

    def test_worker_stream_outside_the_jobs_dir_is_not_read(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "events.log").write_text('{"type":"tool"}\n')
        job = {"path": str(outside), "route": {"provider": "opencode"}}
        self.assertIsNone(orc._worker_stream_activity(self.folder, job))

    def test_full_journal_reads_preserve_rows_after_large_newer_records(self):
        first = {"event": "run_created", "attempt": "old"}
        _append(self.folder, first)
        huge = {"event": "stage_start", "stage": "implement", "attempt": "huge",
                "payload": "x" * (200 * 1024)}
        with (self.folder / orc.JOURNAL_FILE).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(huge) + "\n")
        _append(self.folder, {"event": "stage_end", "attempt": "last"})
        tail = orc.journal_tail(self.folder, 50)
        self.assertEqual(tail[-1]["attempt"], "last")
        self.assertIn("old", [row.get("attempt") for row in tail])
        bounded = orc.journal_tail_bounded(self.folder, 50, tail_bytes=64 * 1024)
        self.assertEqual(bounded[-1]["attempt"], "last")
        self.assertNotIn("old", [row.get("attempt") for row in bounded])

    def test_bounded_tail_never_reads_past_its_window(self):
        path = self.folder / "tail.bin"
        path.write_bytes(b"a" * 5000 + b"\n" + b"b" * 5000)
        data = orc._read_tail_bytes(path, 1024)
        self.assertLessEqual(len(data), 1024)
        self.assertFalse(data.startswith(b"a"), data[:20])

    def test_missing_worker_stream_keeps_waiting_activity(self):
        self.synthetic_start()
        snapshot = self.snapshot()
        self.assertEqual(snapshot["activity"], "preparing the stage")


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
    def _snapshot(self, *, attempt="attempt-A", active=True, ownership="active",
                  elapsed=1.0, source="live", outcome=None):
        return {"available": True, "active": active, "ownership": ownership,
                "attempt_id": attempt, "elapsed_seconds": elapsed,
                "elapsed_source": source, "outcome": outcome, "stage": "implement",
                "agent_label": "Implementer", "batch": {"label": "Batch 1/1"},
                "model": "gpt-5.1", "effort": "high", "activity": "worker running"}

    def test_updates_are_ordered_and_bounded(self):
        sent = []
        stop = threading.Event()

        def reader(_run_id):
            value = self._snapshot()
            value["elapsed_seconds"] = round(time.monotonic() % 100, 1)
            return value

        def send(token, sequence, message):
            sent.append((token, sequence, message))
            if sequence >= 2:
                stop.set()
            return True

        orc._emit_stage_progress(send, 7, "run", {"attempt": "attempt-A"}, stop,
                                 snapshot_reader=reader, interval=0.05)
        self.assertGreaterEqual(len(sent), 2)
        self.assertEqual([row[1] for row in sent], list(range(1, len(sent) + 1)))
        self.assertTrue(all(row[0] == 7 for row in sent))
        self.assertTrue(all(len(row[2]) <= 240 for row in sent))

    def test_other_attempt_is_never_reported(self):
        sent = []
        stop = threading.Event()
        threading.Timer(0.3, stop.set).start()
        orc._emit_stage_progress(
            lambda *row: sent.append(row), 1, "run", {"attempt": "attempt-A"}, stop,
            snapshot_reader=lambda _run_id: self._snapshot(attempt="attempt-B"),
            interval=0.05)
        self.assertEqual(sent, [])

    def test_no_admission_means_no_updates(self):
        sent = []
        stop = threading.Event()
        threading.Timer(0.3, stop.set).start()
        orc._emit_stage_progress(
            lambda *row: sent.append(row), 1, "run", {}, stop,
            snapshot_reader=lambda _run_id: self._snapshot(), interval=0.05,
            admission_timeout=1.0)
        self.assertEqual(sent, [])

    def test_unavailable_snapshot_is_not_reported(self):
        sent = []
        stop = threading.Event()
        threading.Timer(0.3, stop.set).start()
        orc._emit_stage_progress(
            lambda *row: sent.append(row), 1, "run", {"attempt": "attempt-A"}, stop,
            snapshot_reader=lambda _run_id: {"available": False}, interval=0.05)
        self.assertEqual(sent, [])

    def test_completion_sends_one_final_update(self):
        sent = []
        orc._emit_stage_progress(
            lambda *row: sent.append(row), "tok", "run", {"attempt": "attempt-A"},
            threading.Event(),
            snapshot_reader=lambda _run_id: self._snapshot(
                active=False, ownership="complete", elapsed=2.5,
                source="recorded", outcome="complete"),
            interval=0.05)
        self.assertEqual(len(sent), 1)
        self.assertIn("complete", sent[0][2])


class ProgressSinkTests(unittest.TestCase):
    def test_send_is_dropped_after_close(self):
        stream = io.StringIO()
        send, close = orc._progress_sink(stream, threading.Lock())
        self.assertTrue(send("tok", 1, "first"))
        close()
        self.assertFalse(send("tok", 2, "second"))
        self.assertIn("first", stream.getvalue())
        self.assertNotIn("second", stream.getvalue())

    def test_close_does_not_wait_for_a_stalled_notification_write(self):
        released = threading.Event()
        entered = threading.Event()

        class BlockingStream:
            def __init__(self):
                self.writes = []

            def write(self, text):
                entered.set()
                released.wait(5)
                self.writes.append(text)

            def flush(self):
                pass

        stream = BlockingStream()
        send, close = orc._progress_sink(stream, threading.Lock())
        sender = threading.Thread(target=send, args=("tok", 1, "in flight"))
        sender.start()
        self.assertTrue(entered.wait(5))
        started = time.monotonic()
        close()
        self.assertLess(time.monotonic() - started, 0.2,
                        "close blocked on the stalled write")
        self.assertTrue(sender.is_alive())
        self.assertFalse(send("tok", 2, "late"))
        released.set()
        sender.join(5)
        self.assertEqual(len(stream.writes), 1)

    def test_sender_waiting_on_the_output_lock_is_dropped_after_close(self):
        stream = io.StringIO()
        lock = threading.Lock()
        send, close = orc._progress_sink(stream, lock)
        lock.acquire()  # hold the shared serialization a response would use
        result = {}
        sender = threading.Thread(
            target=lambda: result.setdefault("value", send("tok", 1, "queued")))
        sender.start()
        time.sleep(0.1)
        close()
        lock.release()
        sender.join(5)
        self.assertIs(result.get("value"), False)
        self.assertEqual(stream.getvalue(), "")


class _LineInput:
    """Blocking line source for an in-process mcp_serve call."""

    def __init__(self):
        self.items = queue.Queue()

    def push(self, request):
        self.items.put(json.dumps(request) + "\n")

    def close(self):
        self.items.put(None)

    def __iter__(self):
        while True:
            item = self.items.get()
            if item is None:
                return
            yield item


class _LineOutput:
    def __init__(self):
        self.items = queue.Queue()

    def write(self, text):
        self.items.put(text)

    def flush(self):
        pass

    def messages(self, timeout=5.0, count=None):
        collected = []
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                text = self.items.get(timeout=0.05)
            except queue.Empty:
                if count is not None and len(collected) >= count:
                    break
                continue
            for line in text.splitlines():
                if line.strip():
                    collected.append(json.loads(line))
            if count is not None and len(collected) >= count:
                break
        return collected

    def quiet(self, seconds=0.4):
        try:
            text = self.items.get(timeout=seconds)
        except queue.Empty:
            return True
        return not text.strip()


class McpAdmissionBindingTests(unittest.TestCase):
    def _snapshot(self, attempt="attempt-A", *, active=True):
        return {"available": True, "active": active, "ownership": "active",
                "attempt_id": attempt, "elapsed_seconds": 1.0,
                "elapsed_source": "live", "outcome": None, "stage": "implement",
                "agent_label": "Implementer", "batch": {"label": "Batch 1/1"},
                "model": "gpt-5.1", "effort": "high", "activity": "worker running"}

    def test_only_the_admitted_attempt_reports_and_the_refused_call_is_silent(self):
        admitted = threading.Event()
        release = threading.Event()

        def tool(name, arguments, on_admit=None):
            if arguments["run_id"] == "won":
                on_admit({"attempt": "attempt-A"})
                admitted.set()
                release.wait(10)
                return {"ok": True}
            raise RuntimeError("Another supervisor owns this run")

        instream, outstream = _LineInput(), _LineOutput()
        thread = threading.Thread(target=orc.mcp_serve,
                                  args=(instream, outstream), daemon=True)
        with patch.object(orc, "_mcp_tool_call", side_effect=tool), \
                patch.object(orc, "stage_progress",
                             side_effect=lambda _run: self._snapshot()):
            thread.start()
            try:
                instream.push({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                               "params": {"name": "orchestrator_stage",
                                          "arguments": {"run_id": "won"},
                                          "_meta": {"progressToken": "t1"}}})
                self.assertTrue(admitted.wait(5), "admission was not reported")
                instream.push({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                               "params": {"name": "orchestrator_stage",
                                          "arguments": {"run_id": "refused"},
                                          "_meta": {"progressToken": "t2"}}})
                collected = []

                def until(request_id, timeout=5.0):
                    end = time.monotonic() + timeout
                    while time.monotonic() < end:
                        for message in outstream.messages(timeout=0.2, count=None):
                            collected.append(message)
                            if message.get("id") == request_id:
                                return message
                    raise AssertionError("no response for %r" % (request_id,))

                # The first update arrives before the refused response.
                def next_message(timeout=5.0):
                    end = time.monotonic() + timeout
                    while time.monotonic() < end:
                        for message in outstream.messages(timeout=0.2, count=None):
                            collected.append(message)
                            return message
                    raise AssertionError("no MCP message arrived")

                refused = None
                saw_progress = False
                end = time.monotonic() + 5
                while time.monotonic() < end and not saw_progress:
                    message = next_message(1.0)
                    if message.get("method") == "notifications/progress":
                        saw_progress = True
                        self.assertEqual(message["params"]["progressToken"], "t1")
                    elif message.get("id") == 2:
                        refused = message
                    elif message.get("id") == 1:
                        raise AssertionError("stage finished before any update")
                self.assertTrue(saw_progress, "the admitted call produced no update")
                while refused is None:
                    message = next_message(1.0)
                    if message.get("id") == 2:
                        refused = message
                self.assertTrue(refused["result"]["isError"])
                release.set()
                final = until(1)
                self.assertEqual(final.get("id"), 1)
                tokens = [row["params"].get("progressToken")
                          for row in collected
                          if row.get("method") == "notifications/progress"]
                self.assertNotIn("t2", tokens)
                self.assertTrue(outstream.quiet(0.4))
            finally:
                instream.close()
                thread.join(timeout=10)
        self.assertFalse(thread.is_alive())

    def test_read_held_past_the_reply_is_dropped(self):
        read_entered = threading.Event()
        allow_read = threading.Event()

        def tool(name, arguments, on_admit=None):
            on_admit({"attempt": "attempt-A"})
            read_entered.wait(5)
            return {"ok": True}

        def reader(_run_id):
            read_entered.set()
            allow_read.wait(10)
            return self._snapshot()

        instream, outstream = _LineInput(), _LineOutput()
        thread = threading.Thread(target=orc.mcp_serve,
                                  args=(instream, outstream), daemon=True)
        with patch.object(orc, "_mcp_tool_call", side_effect=tool), \
                patch.object(orc, "stage_progress", side_effect=reader):
            thread.start()
            try:
                instream.push({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                               "params": {"name": "orchestrator_stage",
                                          "arguments": {"run_id": "run"},
                                          "_meta": {"progressToken": 9}}})
                self.assertTrue(read_entered.wait(5))
                messages = outstream.messages(timeout=5, count=1)
                self.assertEqual(messages[0].get("id"), 1)
                allow_read.set()
                self.assertTrue(outstream.quiet(0.6),
                                "progress was sent after the final response")
            finally:
                instream.close()
                thread.join(timeout=10)

    def test_cancellation_starts_containment_while_a_progress_write_is_stalled(self):
        interrupted = threading.Event()
        allow_tool_end = threading.Event()

        def tool(name, arguments, on_admit=None):
            on_admit({"attempt": "attempt-A"})
            allow_tool_end.wait(10)
            return {"ok": True}

        class GatedOutput(_LineOutput):
            def __init__(self):
                super().__init__()
                self.gate = threading.Event()
                self.entered = threading.Event()

            def write(self, text):
                self.entered.set()
                self.gate.wait(10)
                super().write(text)

        instream, outstream = _LineInput(), GatedOutput()
        thread = threading.Thread(target=orc.mcp_serve,
                                  args=(instream, outstream), daemon=True)
        with patch.object(orc, "_mcp_tool_call", side_effect=tool), \
                patch.object(orc, "stage_progress",
                             side_effect=lambda _run: self._snapshot()), \
                patch.object(orc, "interrupt_run",
                             side_effect=lambda *args, **kwargs: interrupted.set()):
            thread.start()
            try:
                instream.push({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                               "params": {"name": "orchestrator_stage",
                                          "arguments": {"run_id": "run"},
                                          "_meta": {"progressToken": "tok"}}})
                self.assertTrue(outstream.entered.wait(5),
                                "progress write never started")
                instream.push({"jsonrpc": "2.0", "method": "notifications/cancelled",
                               "params": {"requestId": 1, "reason": "user stop"}})
                self.assertTrue(interrupted.wait(2),
                                "containment waited for stalled output")
            finally:
                allow_tool_end.set()
                outstream.gate.set()
                instream.close()
                thread.join(timeout=10)
        self.assertFalse(thread.is_alive())

    def test_eof_starts_emergency_stop_while_a_progress_write_is_stalled(self):
        stopped = threading.Event()
        allow_tool_end = threading.Event()

        def tool(name, arguments, on_admit=None):
            on_admit({"attempt": "attempt-A"})
            allow_tool_end.wait(10)
            return {"ok": True}

        class GatedOutput(_LineOutput):
            def __init__(self):
                super().__init__()
                self.gate = threading.Event()
                self.entered = threading.Event()

            def write(self, text):
                self.entered.set()
                self.gate.wait(10)
                super().write(text)

        instream, outstream = _LineInput(), GatedOutput()
        thread = threading.Thread(target=orc.mcp_serve,
                                  args=(instream, outstream), daemon=True)
        with patch.object(orc, "_mcp_tool_call", side_effect=tool), \
                patch.object(orc, "stage_progress",
                             side_effect=lambda _run: self._snapshot()), \
                patch.object(orc, "_emergency_stop",
                             side_effect=lambda _run: stopped.set()):
            thread.start()
            try:
                instream.push({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                               "params": {"name": "orchestrator_stage",
                                          "arguments": {"run_id": "run"},
                                          "_meta": {"progressToken": 3}}})
                self.assertTrue(outstream.entered.wait(5))
                instream.close()  # host EOF
                self.assertTrue(stopped.wait(2),
                                "teardown waited for stalled output")
            finally:
                allow_tool_end.set()
                outstream.gate.set()
                thread.join(timeout=10)
        self.assertFalse(thread.is_alive())

    def test_malformed_meta_or_invalid_token_disables_progress(self):
        seen = {}

        def tool(name, arguments, on_admit=None):
            seen["on_admit"] = on_admit
            return {"ok": True}

        for meta in ({"progressToken": True}, {"progressToken": {"nested": 1}},
                     ["not", "an", "object"]):
            instream, outstream = _LineInput(), _LineOutput()
            thread = threading.Thread(target=orc.mcp_serve,
                                      args=(instream, outstream), daemon=True)
            with patch.object(orc, "_mcp_tool_call", side_effect=tool), \
                    patch.object(orc, "stage_progress",
                                 side_effect=lambda _run: self._snapshot()):
                thread.start()
                try:
                    instream.push({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                   "params": {"name": "orchestrator_stage",
                                              "arguments": {"run_id": "run"},
                                              "_meta": meta}})
                    messages = outstream.messages(timeout=5, count=1)
                    self.assertEqual(messages[0].get("id"), 1)
                    self.assertIsNone(seen.get("on_admit"))
                    self.assertTrue(outstream.quiet(0.3),
                                    "progress was emitted for %r" % (meta,))
                finally:
                    instream.close()
                    thread.join(timeout=10)


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

    def test_waiting_view_shows_role_task_and_expected_output(self):
        out = io.StringIO()
        with patch.object(orc, "DEFAULT_STATE", self.runs), \
                patch.dict(os.environ, self.env):
            orc.status_follow(self.run_id, out, inplace=True, interval=0.05,
                              max_seconds=0.3)
        text = out.getvalue()
        self.assertIn("next:", text)
        self.assertIn("next task:", text)
        self.assertIn("next expected:", text)

    def test_between_stages_shows_outcome_and_next_preview(self):
        self.stage()  # plan completes; next stage is implement
        out = io.StringIO()
        with patch.object(orc, "DEFAULT_STATE", self.runs), \
                patch.dict(os.environ, self.env):
            orc.status_follow(self.run_id, out, inplace=True, interval=0.05,
                              max_seconds=0.3)
        text = out.getvalue()
        self.assertIn("outcome: complete", text)
        self.assertIn("next:", text)
        self.assertIn("next task:", text)
        self.assertIn("next expected:", text)

    def test_plain_heartbeat_refires_for_unchanged_activity(self):
        self.stage()  # plan completed; activity/outcome no longer change
        out = io.StringIO()
        with patch.object(orc, "DEFAULT_STATE", self.runs), \
                patch.dict(os.environ, self.env):
            orc.status_follow(self.run_id, out, inplace=False, interval=0.05,
                              heartbeat=0.2, max_seconds=0.55)
        self.assertGreaterEqual(out.getvalue().count("run "), 2)

    def test_final_state_waits_for_the_matching_end_record(self):
        self.synthetic_start(monotonic_started=round(time.monotonic() - 3, 3))
        state = json.loads((self.folder / "state.json").read_text())
        state["status"] = "complete"
        (self.folder / "state.json").write_text(json.dumps(state))
        out = io.StringIO()

        def append_end():
            time.sleep(0.25)
            _append(self.folder, {"event": "stage_end", "stage": "implement",
                                  "attempt": "synthetic0001",
                                  "elapsed_seconds": 3.4, "outcome": "complete",
                                  "next_action": "none"})

        writer = threading.Thread(target=append_end)
        writer.start()
        started = time.monotonic()
        with patch.object(orc, "DEFAULT_STATE", self.runs), \
                patch.dict(os.environ, self.env):
            orc.status_follow(self.run_id, out, inplace=True, interval=0.05,
                              max_seconds=3.0, final_grace=2.0)
        writer.join(5)
        self.assertLess(time.monotonic() - started, 2.0)
        text = out.getvalue()
        self.assertIn("measured 3.4s", text)
        self.assertIn("stage finished (complete)", text)

    def test_final_state_without_end_exits_after_the_grace_bound(self):
        self.synthetic_start(monotonic_started=round(time.monotonic() - 3, 3))
        state = json.loads((self.folder / "state.json").read_text())
        state["status"] = "complete"
        (self.folder / "state.json").write_text(json.dumps(state))
        out = io.StringIO()
        started = time.monotonic()
        with patch.object(orc, "DEFAULT_STATE", self.runs), \
                patch.dict(os.environ, self.env):
            orc.status_follow(self.run_id, out, inplace=True, interval=0.05,
                              max_seconds=3.0, final_grace=0.4)
        self.assertLess(time.monotonic() - started, 2.0)
        self.assertIn("run is finished", out.getvalue())

    def test_narrow_output_falls_back_to_plain_append(self):
        self.stage()
        out = io.StringIO()
        with patch.object(orc, "DEFAULT_STATE", self.runs), \
                patch.dict(os.environ, self.env), \
                patch.object(orc.shutil, "get_terminal_size",
                             return_value=os.terminal_size((20, 24))):
            orc.status_follow(self.run_id, out, inplace=True, interval=0.05,
                              max_seconds=0.25)
        text = out.getvalue()
        self.assertNotIn("\x1b[", text)
        self.assertIn("expected:", text)

    def test_shrinking_block_clears_remaining_rows(self):
        self.stage()
        long_snapshot = {
            "available": True, "run_id": self.run_id,
            "batch": {"label": "Batch 1/1"}, "agent_label": "Implementer",
            "stage": "implement", "attempt_id": "attempt-1", "model": "m",
            "effort": "high", "elapsed_seconds": 1.0, "elapsed_source": "live",
            "activity": "worker running", "task": "task", "expected": "expected",
            "outcome": "complete", "ownership": "complete", "next_action": "next",
            "next": {"phase": "verify", "agent_label": "Supervisor",
                     "task": "checks", "expected": "evidence", "model": "m",
                     "effort": "high"}}
        short_snapshot = {"available": False, "run_id": self.run_id,
                          "batch": {"label": "Batch 1/1"},
                          "next": {"phase": "verify", "agent_label": "Supervisor",
                                   "task": "checks", "expected": "evidence",
                                   "model": "m", "effort": "high"}}
        calls = {"count": 0}

        def snapshot(_folder, _state):
            calls["count"] += 1
            return long_snapshot if calls["count"] == 1 else short_snapshot

        out = io.StringIO()
        with patch.object(orc, "DEFAULT_STATE", self.runs), \
                patch.dict(os.environ, self.env), \
                patch.object(orc, "stage_snapshot", side_effect=snapshot), \
                patch.object(orc.shutil, "get_terminal_size",
                             return_value=os.terminal_size((200, 24))):
            orc.status_follow(self.run_id, out, inplace=True, interval=0.05,
                              max_seconds=0.3)
        self.assertIn("\x1b[0J", out.getvalue())

    def _active(self):
        state = json.loads((self.folder / "state.json").read_text())
        return bool(state.get("active_job")
                    and "# implemented" in (self.project / "app.py").read_text())


class LaunchEvidenceTests(ProgressFixture):
    """Every transition states whether a model launched, who acts and why."""

    def _rewrite(self, **updates):
        path = self.folder / "state.json"
        state = json.loads(path.read_text())
        state.update(updates)
        path.write_text(json.dumps(state))
        return state

    def test_pending_stage_says_model_has_not_launched(self):
        snapshot = self.snapshot()
        launch = snapshot["launch"]
        self.assertEqual(launch["state"], "not_launched")
        self.assertFalse(launch["worker_started"])
        self.assertFalse(launch["model_active"])
        self.assertEqual(launch["statement"], "model has not launched")
        state = json.loads((self.folder / "state.json").read_text())
        lines = orc._viewer_lines(state, snapshot)
        self.assertTrue(any("has not launched" in line for line in lines), lines)

    def test_prelaunch_refusal_reports_zero_launches_reason_and_actor(self):
        state = self._rewrite(
            status="blocked",
            pause_reason="Dispatch not attempted (transport): too large",
            preflight_rejection={
                "reason_code": "transport_too_large",
                "reasons": ["Essential handoff context exceeds the configured budget"],
                "active_job_created": False, "model_calls_counted": False,
                "kind": "reviewer", "role": "reviewer"},
            active_job=None, active_check=None)
        snapshot = self.snapshot()
        launch = snapshot["launch"]
        self.assertEqual(launch["state"], "blocked")
        self.assertFalse(launch["worker_started"])
        self.assertEqual(launch["model_calls"], 0)
        self.assertEqual(launch["blocked_by"]["code"], "transport_too_large")
        self.assertEqual(launch["actor"], "operator")
        self.assertEqual(launch["next_action"], "orchestrator_resume")
        self.assertIn("zero launches", launch["statement"])
        status = orc.status_run(self.run_id)
        self.assertEqual(status["launch"], launch)
        text = "\n".join(orc._viewer_lines(state, snapshot))
        self.assertIn("blocked:", text)
        self.assertIn("transport_too_large", text)
        self.assertIn("zero launches", text)
        self.assertIn("actor: operator", text)
        self.assertIn("next: orchestrator_resume", text)
        self.assertNotIn("waiting for the next stage", text)

    def test_verification_says_no_model_and_check_ordinal(self):
        commands = [["python3", "-m", "unittest"], ["git", "diff", "--check"]]
        state = self._rewrite(
            status="running", phase="verify", active_job=None,
            active_check={"id": "check-1", "argv": commands[0]},
            check_progress={"identity": {"argv": commands},
                            "evidence": {"commands": [{"argv": commands[0]}]}})
        snapshot = self.snapshot()
        launch = snapshot["launch"]
        self.assertEqual(launch["state"], "verification")
        self.assertFalse(launch["model_active"])
        self.assertEqual(launch["check"],
                         {"ordinal": 2, "total": 2, "completed": 1})
        self.assertIn("no model is active", launch["statement"])
        self.assertIn("check 2/2", launch["statement"])
        text = "\n".join(orc._viewer_lines(state, snapshot))
        self.assertIn("supervisor", text)
        self.assertIn("check 2/2", text)
        self.assertIn("check 2/2", orc.stage_progress_message(snapshot))

    def test_running_is_claimed_only_with_launch_evidence(self):
        self.synthetic_start()
        jobdir = self.folder / "jobs" / "impl-x"
        self._rewrite(
            status="running", phase="implement",
            active_job={"id": "impl-x", "kind": "implementer",
                        "status": "running", "path": str(jobdir)})
        unproven = self.snapshot()["launch"]
        self.assertEqual(unproven["state"], "launching")
        self.assertFalse(unproven["model_active"])
        self.assertIn("not proven", unproven["statement"])
        jobdir.mkdir(parents=True)
        orc.atomic_json(jobdir / "execution.json", {"status": "running"})
        launch = self.snapshot()["launch"]
        self.assertEqual(launch["state"], "running")
        self.assertTrue(launch["model_active"])
        self.assertEqual(launch["actor"], "worker")
        self.assertEqual(launch["statement"], "worker active")


if __name__ == "__main__":
    unittest.main()
