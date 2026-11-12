"""Regressions for OpenCode V1/V2 nested usage and bounded 429 detection.

Fixtures are sanitized captures from prior real CLI validation (secret and
live identifiers replaced, event structure preserved):

- V1: ``step_finish.part.tokens`` with total/input/output/reasoning/cache.
- V2.2.7: ``step_finish.part.tokens`` without total (real streaming shape).

No model calls occur: these tests are offline and deterministic.
"""
from __future__ import annotations

import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_orchestrator as baseline

orc = baseline.orc
FIXTURES = Path(__file__).resolve().parent / "fixtures"
V1_EVENTS = (FIXTURES / "opencode-v1-step-finish.jsonl").read_text(encoding="utf-8")
V2_EVENTS = (FIXTURES / "opencode-v2-step-finish.jsonl").read_text(encoding="utf-8")


def step_event(part_id, input_tokens=10, output_tokens=5, reasoning=0,
               cache_read=0, cache_write=0, total=None, reason="stop",
               cost=None):
    tokens = {"input": input_tokens, "output": output_tokens,
              "reasoning": reasoning,
              "cache": {"read": cache_read, "write": cache_write}}
    if total is not None:
        tokens["total"] = total
    part = {"id": part_id, "sessionID": "ses_capture", "messageID": "msg_capture",
            "type": "step-finish", "reason": reason, "tokens": tokens}
    if cost is not None:
        part["cost"] = cost
    return json.dumps({"type": "step_finish", "timestamp": 1794000000000,
                       "sessionID": "ses_capture", "part": part})


class OpenCodeUsageParsingTests(unittest.TestCase):
    def test_v1_nested_step_tokens_are_reported(self):
        usage = orc.extract_reported_usage(V1_EVENTS, "jsonl")
        self.assertEqual(usage["tokens"], 17971)
        self.assertEqual(usage["input_tokens"], 366)
        self.assertEqual(usage["output_tokens"], 762)
        self.assertEqual(usage["reasoning_tokens"], 203)
        self.assertEqual(usage["cache_tokens"], 16640)
        self.assertEqual(usage["cache_read_tokens"], 16640)
        self.assertEqual(usage["cache_write_tokens"], 0)
        self.assertAlmostEqual(usage["cost"], 0.00068382, places=8)
        self.assertEqual(usage["source"], "opencode.step_finish")
        self.assertEqual(usage["events"], 1)

    def test_v2_nested_step_tokens_are_reported(self):
        usage = orc.extract_reported_usage(V2_EVENTS, "jsonl")
        self.assertEqual(usage["tokens"], 15)
        self.assertEqual(usage["input_tokens"], 10)
        self.assertEqual(usage["output_tokens"], 5)
        self.assertEqual(usage["reasoning_tokens"], 0)
        self.assertEqual(usage["cache_tokens"], 0)
        self.assertEqual(usage["cost"], 0.0)
        self.assertEqual(usage["source"], "opencode.step_finish")

    def test_zero_values_stay_reported_and_absent_values_stay_unavailable(self):
        v2 = orc.extract_reported_usage(V2_EVENTS, "jsonl")
        # Genuine Zero values must not collapse into None.
        self.assertEqual(v2["reasoning_tokens"], 0)
        self.assertEqual(v2["cache_tokens"], 0)
        flat = orc.extract_reported_usage(
            json.dumps({"usage": {"input_tokens": 10, "output_tokens": 5}}), "claude")
        self.assertEqual(flat["tokens"], 15)
        self.assertIsNone(flat["reasoning_tokens"])
        self.assertIsNone(flat["cache_tokens"])

    def test_duplicate_step_events_are_counted_once(self):
        usage = orc.extract_reported_usage(V1_EVENTS + V1_EVENTS, "jsonl")
        self.assertEqual(usage["tokens"], 17971)
        self.assertEqual(usage["input_tokens"], 366)
        self.assertEqual(usage["events"], 1)

    def test_distinct_steps_are_summed_once_each(self):
        usage = orc.extract_reported_usage(
            step_event("prt_a") + "\n" + step_event("prt_b"), "jsonl")
        self.assertEqual(usage["tokens"], 30)
        self.assertEqual(usage["input_tokens"], 20)
        self.assertEqual(usage["output_tokens"], 10)
        self.assertEqual(usage["events"], 2)
        self.assertEqual(usage["source"], "opencode.step_finish")

    def test_cumulative_codex_snapshots_use_the_latest_total(self):
        raw = "\n".join(json.dumps({"usage": {"total_token_count": value}})
                        for value in (60, 100))
        usage = orc.extract_reported_usage(raw, "codex")
        self.assertEqual(usage["tokens"], 100)
        self.assertEqual(usage["source"], "codex.token_count")

    def test_flat_claude_usage_remains_compatible(self):
        raw = json.dumps({"usage": {"input_tokens": 10, "output_tokens": 5,
                                    "cache_read_input_tokens": 2,
                                    "cache_creation_input_tokens": 3},
                          "total_cost_usd": 0.25})
        usage = orc.extract_reported_usage(raw, "claude")
        self.assertEqual(usage["tokens"], 15)
        self.assertEqual(usage["cache_tokens"], 5)
        self.assertEqual(usage["cache_read_tokens"], 2)
        self.assertEqual(usage["cache_write_tokens"], 3)
        self.assertEqual(usage["cost"], 0.25)
        self.assertEqual(usage["source"], "claude.result")

    def test_recorded_usage_keeps_detail_source_and_zero(self):
        state = {}
        job = {"role": "implementer", "route": {"billing": "go"},
               "reported_usage": orc.extract_reported_usage(V2_EVENTS, "jsonl")}
        orc.record_usage(state, job, "complete", 1.0)
        usage = orc.usage_report(state)
        self.assertEqual(usage["reported_tokens"], 15)
        self.assertEqual(usage["reported_input_tokens"], 10)
        self.assertEqual(usage["reported_output_tokens"], 5)
        self.assertEqual(usage["reported_reasoning_tokens"], 0)
        self.assertEqual(usage["reported_cache_tokens"], 0)
        self.assertEqual(usage["sources"], ["opencode.step_finish"])
        self.assertEqual(usage["cost_status"], "reported")


class RateLimitDetectionTests(unittest.TestCase):
    def test_structured_v2_429_error_is_detected(self):
        event = {"type": "error", "sessionID": "ses_429_real",
                 "error": {"name": "APIError",
                           "data": {"message": "Too Many Requests",
                                    "statusCode": 429, "isRetryable": True}}}
        self.assertTrue(orc.is_rate_limited(json.dumps(event)))

    def test_structured_camel_case_rate_limit_name_is_detected(self):
        event = {"type": "error", "sessionID": "ses_real",
                 "error": {"name": "RateLimitError",
                           "data": {"message": "slow down"}}}
        self.assertTrue(orc.is_rate_limited(json.dumps(event)))

    def test_real_v2_retry_and_error_event_structures_are_detected(self):
        error = {"type": "provider.rate-limit", "message": "Too Many Requests",
                 "status": 429,
                 "response": {"body": "{\"error\": {\"message\": \"Too Many Requests\", "
                                       "\"type\": \"rate_limit_error\", "
                                       "\"code\": \"rate_limit_exceeded\"}}"},
                 "retryAfterMs": 1000}
        retry = {"type": "retry", "timestamp": 1794514106387,
                 "sessionID": "ses_v2rate", "messageID": "msg_v2rate",
                 "attempt": 2, "nextRetryAt": 1794514108068, "error": error}
        final = {"type": "error", "timestamp": 1794514189594,
                 "sessionID": "ses_v2rate", "error": error}
        for event in (retry, final):
            with self.subTest(event_type=event["type"]):
                self.assertTrue(orc.is_rate_limited(json.dumps(event)))

    def test_structured_error_response_body_is_detected(self):
        event = {"type": "error", "sessionID": "ses_v2rate",
                 "error": {"response": {"body":
                                        "{\"error\": {\"code\": \"rate_limit_exceeded\"}}"}}}
        self.assertTrue(orc.is_rate_limited(json.dumps(event)))

    def test_plain_diagnostics_with_bounded_429_are_detected(self):
        for raw in ("Error: 429 Too Many Requests\n",
                    "request failed: status=429\n",
                    "429 rate limit\n",
                    "resource_exhausted: retry later\n"):
            with self.subTest(raw=raw):
                self.assertTrue(orc.is_rate_limited(raw))

    def test_successful_v2_session_with_429_in_metadata_is_not_rate_limited(self):
        raw = (V2_EVENTS
               .replace("9427d79c42c43bba712429af41d2913a9b64d424",
                        "9427d79c42c43bba712429af41d2913a9b64d429")
               .replace("ses_v2capture", "ses_429_capture")
               .replace('"input":10', '"input":429'))
        self.assertIn("429", raw)
        self.assertFalse(orc.is_rate_limited(raw))

    def test_success_outranks_unrelated_assistant_text(self):
        events = V2_EVENTS.splitlines()
        text_event = json.loads(events[1])
        text_event["part"]["text"] = json.dumps({
            "status": "complete",
            "summary": "Analyzed rate limit 429 handling in 429-related code",
            "files": ["build-429.log"], "tests": [], "evidence": [],
            "unknowns": [], "blocker": ""})
        raw = "\n".join([events[0], json.dumps(text_event), events[2]])
        self.assertFalse(orc.is_rate_limited(raw))

    def test_bare_429_in_filenames_counters_hashes_and_ids_is_ignored(self):
        raw = "\n".join(["opened build-429.log",
                         "processed 429 records",
                         "session ses_429capture",
                         "snapshot 9f429e8c0",
                         "token count 429"])
        self.assertFalse(orc.is_rate_limited(raw))

    def test_real_structured_rate_limit_beats_an_earlier_partial_step(self):
        events = [
            {"type": "text", "sessionID": "ses_real",
             "part": {"type": "text", "text": "{\"status\":\"blocked\"}"}},
            {"type": "error", "sessionID": "ses_real",
             "error": {"name": "APIError",
                       "data": {"message": "429 Too Many Requests",
                                "statusCode": 429}}}]
        self.assertTrue(orc.is_rate_limited(
            "\n".join(json.dumps(event) for event in events)))


class RateLimitRecoveryIntegrationTests(unittest.TestCase):
    setUp = baseline.ControlTests.setUp
    tearDown = baseline.ControlTests.tearDown

    def _fake_cli(self, body):
        fake = self.root / "bin" / "opencode"
        fake.parent.mkdir(exist_ok=True)
        fake.write_text("#!/usr/bin/env python3\n"
                        "import json,sys\n"
                        "if '--version' in sys.argv:\n"
                        "    print('1.18.35')\n"
                        "    sys.exit(0)\n" + body)
        fake.chmod(0o755)
        return fake

    def test_genuine_v2_rate_limit_still_sets_retry_session(self):
        partial = {"type": "text", "sessionID": "ses_429_real",
                   "part": {"type": "text", "text": "partial"}}
        error = {"type": "error", "sessionID": "ses_429_real",
                 "error": {"name": "APIError",
                           "data": {"message": "Too Many Requests",
                                    "statusCode": 429}}}
        self._fake_cli(f"print(json.dumps({partial!r}))\n"
                       f"print(json.dumps({error!r}))\n"
                       "sys.exit(2)\n")
        with patch.dict(orc.os.environ,
                        {"PATH": f"{self.root / 'bin'}:{orc.os.environ['PATH']}"}):
            with self.assertRaisesRegex(RuntimeError, "rate_limited"):
                orc.call_model(self.rundir, self.state, self.cfg, "implementer",
                               "implementer", "Finish task", self.project)
        self.assertEqual(self.state["retry_session"]["session_id"], "ses_429_real")
        self.assertEqual(self.state["failed_jobs"][-1]["error"].split(":")[0],
                         "rate_limited")

    def test_successful_v2_session_with_429_metadata_completes(self):
        events = [json.loads(line) for line in V2_EVENTS.splitlines()]
        events[0]["part"]["snapshot"] = "9f429e8c0d1"
        events[1]["part"]["text"] = json.dumps({
            "status": "complete", "summary": "successful session with 429 metadata",
            "files": [], "tests": [], "evidence": ["build-429.log:1"],
            "unknowns": [], "blocker": ""})
        events[2]["part"]["tokens"]["input"] = 429
        self._fake_cli("\n".join(f"print(json.dumps({event!r}))"
                                 for event in events) + "\n")
        with patch.dict(orc.os.environ,
                        {"PATH": f"{self.root / 'bin'}:{orc.os.environ['PATH']}"}):
            report, job = orc.call_model(self.rundir, self.state, self.cfg,
                                         "explorer", "explorer", "Inspect", self.project)
        self.assertEqual(report["summary"], "successful session with 429 metadata")
        self.assertEqual(job["reported_usage"]["tokens"], 434)
        self.assertIsNone(self.state.get("retry_session"))

    def test_success_event_prevents_false_rate_limit_on_nonzero_exit(self):
        events = [json.loads(line) for line in V2_EVENTS.splitlines()]
        events[0]["part"]["snapshot"] = "9f429e8c0d1"
        self._fake_cli("\n".join(f"print(json.dumps({event!r}))"
                                 for event in events) + "\n"
                       "sys.exit(3)\n")
        with patch.dict(orc.os.environ,
                        {"PATH": f"{self.root / 'bin'}:{orc.os.environ['PATH']}"}):
            with self.assertRaisesRegex(RuntimeError, r"^failed:"):
                orc.call_model(self.rundir, self.state, self.cfg, "implementer",
                               "implementer", "Finish task", self.project)
        self.assertIsNone(self.state.get("retry_session"))


if __name__ == "__main__":
    unittest.main()
