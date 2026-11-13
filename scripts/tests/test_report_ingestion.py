"""Offline regressions for the report-generation/ingestion boundary.

The central fixture is a sanitized copy of the real failed OpenCode V2.2.7
Implementer stream (2026-11-13). Its final assistant text is a complete report
whose `summary` contains unescaped double quotes, so it is not valid JSON even
though the process exited 0 and emitted a terminal step_finish.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_orchestrator import orc, setup_repo

FIXTURES = Path(__file__).parent / "fixtures"
SESSION = "ses_fixture"
FAILED_SESSION = "ses_e2a81085bffewSncO0t7NGp5U9"

VALID = {
    "contract_version": 2,
    "status": "complete",
    "summary": "done",
    "files": ["app.py"],
    "tests": ["python3 -m unittest"],
    "evidence": ["app.py:1"],
    "unknowns": [],
    "blocker": "",
}
REVIEWER = {**VALID, "findings": []}


def event(kind, **part):
    return {"type": kind, "timestamp": 1, "sessionID": SESSION,
            "part": {"sessionID": SESSION, "messageID": "msg_fixture",
                     "type": kind, **part}}


def stream(texts, *, terminal=True, session=SESSION, finish_reason="stop"):
    events = [event("step_start", id="prt_start", type="step-start")]
    for index, text in enumerate(texts):
        events.append(event("text", id=f"prt_text_{index}", text=text))
    if terminal:
        events.append(event("step_finish", id="prt_finish",
                            type="step-finish", reason=finish_reason,
                            snapshot="tree_fixture"))
    return "\n".join(json.dumps(item) for item in events) + "\n"


def extract(raw, **kwargs):
    options = {"kind": "implementer", "expected_session": SESSION,
               "require_terminal": True, "require_contract": True,
               "diagnostics": {}}
    options.update(kwargs)
    return orc.extract_cli_report("jsonl", raw, Path("."), **options)


class Harness(unittest.TestCase):
    """Isolated run state; never launches a model CLI."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        state_patch = patch.object(orc, "DEFAULT_STATE", self.root / "runs")
        state_patch.start()
        self.addCleanup(state_patch.stop)
        self.project = setup_repo(self.root)
        self.rundir = self.root / "runs/test-run00"
        self.rundir.mkdir(parents=True)
        test_cfg = orc.read_json(orc.HERE / "config.example.json")
        test_cfg.setdefault("authorization", {})["sensitive_cli_enabled"] = True
        cfg_path = self.root / "config.json"
        orc.atomic_json(cfg_path, test_cfg)
        cfg_patch = patch.object(orc, "CONFIG_PATH", cfg_path)
        cfg_patch.start()
        self.addCleanup(cfg_patch.stop)
        self.cfg = orc.config()
        self.state = {
            "id": "test-run00", "status": "running", "phase": "plan",
            "project": str(self.project), "host": "codex", "goal": "Add a feature",
            "plan_approval": False, "batch_index": 0, "corrections": 0, "correction": "",
            "plan": None, "active_job": None, "completed_jobs": [], "failed_jobs": [],
            "accepted_batches": [], "review": None, "implementation": None,
            "verification": None,
        }
        self.state.update({
            "schema_version": orc.STATE_SCHEMA_VERSION,
            "supervisor_version": orc.SUPERVISOR_VERSION,
            "config_schema_version": orc.CONFIG_SCHEMA_VERSION,
            "config_sha256": orc.configuration_provenance().get("sha256")})
        orc.save(self.rundir, self.state)
        orc.atomic_json(self.rundir / "control.json", {"action": "run"})


class OpenCodeIngestionRegressions(Harness):
    def test_actual_failed_stream_is_classified_not_generically_lost(self):
        raw = (FIXTURES / "opencode-v2-implementer-invalid-json.jsonl").read_text()
        diagnostics = {}
        with self.assertRaises(orc.ReportIngestionError) as raised:
            extract(raw, expected_session=FAILED_SESSION,
                    diagnostics=diagnostics)
        error = raised.exception
        self.assertEqual(error.code, "report_invalid_json")
        self.assertEqual(error.details["json_error"]["field"], "summary")
        self.assertTrue(error.details["json_error"]["likely_unescaped_quote"])
        self.assertIn("unescaped double quote", str(error))
        self.assertIn("line 1 column", str(error))
        self.assertEqual(diagnostics["terminal_completion"]["reason"], "stop")
        self.assertEqual(len(diagnostics["text_parts"]), 2)
        # Tool output containing unrelated JSON was never treated as a report.
        self.assertNotIn("tool output is not a report", json.dumps(diagnostics))

    def test_actual_failed_stream_is_recoverable_with_recorded_repair(self):
        raw = (FIXTURES / "opencode-v2-implementer-invalid-json.jsonl").read_text()
        diagnostics = {}
        report, session_id = extract(raw, expected_session=FAILED_SESSION,
                                     repair_unescaped=True,
                                     diagnostics=diagnostics)
        self.assertEqual(session_id, FAILED_SESSION)
        self.assertEqual(report["contract_version"], 2)
        self.assertEqual(report["status"], "complete")
        self.assertIn('"1"*4301', report["summary"])
        self.assertEqual(len(diagnostics["repair"]["ops"]), 2)
        self.assertEqual(orc.validate_report("implementer", report), report)

    def test_actual_failed_stream_valid_counterpart_parses_whole(self):
        raw = (FIXTURES / "opencode-v2-implementer-valid.jsonl").read_text()
        report, session_id = extract(raw, expected_session=FAILED_SESSION)
        self.assertEqual(session_id, FAILED_SESSION)
        self.assertEqual(report["contract_version"], 2)
        self.assertIn('"1"*4301', report["summary"])

    def test_multiple_text_events_are_not_concatenated(self):
        report, _ = extract(stream(["I will inspect.", "Done.", json.dumps(VALID)]))
        self.assertEqual(report["summary"], "done")

    def test_json_inside_markdown_fence(self):
        fenced = "Here is the report:\n```json\n" + json.dumps(VALID) + "\n```\n"
        report, _ = extract(stream([fenced]))
        self.assertEqual(report["summary"], "done")

    def test_ordinary_prose_is_not_converted_into_evidence(self):
        with self.assertRaises(orc.ReportIngestionError) as raised:
            extract(stream(["I inspected the files and everything looks fine."]))
        self.assertEqual(raised.exception.code, "report_missing")

    def test_tool_output_json_is_ignored(self):
        raw = "\n".join(json.dumps(item) for item in [
            event("step_start", id="prt_start", type="step-start"),
            {"type": "tool_use", "sessionID": SESSION, "part": {
                "id": "prt_tool", "sessionID": SESSION, "messageID": "msg",
                "type": "tool", "tool": "shell",
                "state": {"status": "completed", "output": json.dumps(VALID)}}},
            event("text", id="prt_text", text="I finished the inspection."),
            event("step_finish", id="prt_finish", type="step-finish",
                  reason="stop", snapshot="tree_fixture"),
        ]) + "\n"
        with self.assertRaises(orc.ReportIngestionError) as raised:
            extract(raw)
        self.assertEqual(raised.exception.code, "report_missing")

    def test_wrong_contract_version_is_rejected_exactly(self):
        report = {**VALID, "contract_version": 3}
        with self.assertRaises(orc.ReportIngestionError) as raised:
            extract(stream([json.dumps(report)]))
        self.assertEqual(raised.exception.code, "contract_version_mismatch")
        self.assertEqual(raised.exception.details["got"], 3)

    def test_missing_required_fields_are_rejected(self):
        report = {key: value for key, value in VALID.items() if key != "files"}
        with self.assertRaises(orc.ReportIngestionError) as raised:
            extract(stream([json.dumps(report)]))
        self.assertEqual(raised.exception.code, "report_schema_invalid")
        self.assertIn("files", raised.exception.details["missing"])

    def test_truncated_output_is_classified(self):
        truncated = '{"contract_version":2,"status":"complete","summary":"only part'
        with self.assertRaises(orc.ReportIngestionError) as raised:
            extract(stream([truncated], terminal=True))
        self.assertEqual(raised.exception.code, "report_truncated")

    def test_explicit_provider_error_is_classified(self):
        raw = "\n".join(json.dumps(item) for item in [
            event("step_start", id="prt_start", type="step-start"),
            {"type": "error", "sessionID": SESSION,
             "error": {"message": "provider rejected the request"}},
        ]) + "\n"
        with self.assertRaises(orc.ReportIngestionError) as raised:
            extract(raw)
        self.assertEqual(raised.exception.code, "provider_error")
        self.assertIn("provider rejected", str(raised.exception))

    def test_missing_terminal_completion_is_rejected(self):
        with self.assertRaises(orc.ReportIngestionError) as raised:
            extract(stream([json.dumps(VALID)], terminal=False))
        self.assertEqual(raised.exception.code, "missing_terminal_completion")

    def test_tool_call_terminal_reason_is_not_completion(self):
        with self.assertRaises(orc.ReportIngestionError) as raised:
            extract(stream([json.dumps(VALID)], finish_reason="tool-calls"))
        self.assertEqual(raised.exception.code, "missing_terminal_completion")

    def test_session_mismatch_is_rejected(self):
        with self.assertRaises(orc.ReportIngestionError) as raised:
            extract(stream([json.dumps(VALID)]), expected_session="ses_other")
        self.assertEqual(raised.exception.code, "session_mismatch")

    def test_multiple_text_sessions_are_ambiguous(self):
        raw = stream([json.dumps(VALID), "extra prose"])
        events = [json.loads(line) for line in raw.splitlines()]
        events[2]["sessionID"] = "ses_other"
        events[2]["part"]["sessionID"] = "ses_other"
        raw = "\n".join(json.dumps(item) for item in events) + "\n"
        with self.assertRaises(orc.ReportIngestionError) as raised:
            extract(raw, expected_session=None)
        self.assertEqual(raised.exception.code, "session_mismatch")

    def test_valid_report_followed_by_unrelated_text_still_parses(self):
        report, _ = extract(stream([json.dumps(VALID), "Thanks, that is all."]))
        self.assertEqual(report["summary"], "done")

    def test_newest_report_wins_without_concatenation(self):
        first = {**VALID, "summary": "first"}
        second = {**VALID, "summary": "second"}
        report, _ = extract(stream([json.dumps(first), json.dumps(second)]))
        self.assertEqual(report["summary"], "second")

    def test_empty_output(self):
        with self.assertRaises(orc.ReportIngestionError) as raised:
            extract("")
        self.assertEqual(raised.exception.code, "empty_output")

    def test_no_assistant_text_events(self):
        raw = json.dumps(event("step_start", id="prt_start", type="step-start")) + "\n"
        with self.assertRaises(orc.ReportIngestionError) as raised:
            extract(raw)
        self.assertEqual(raised.exception.code, "no_assistant_text")

    def test_explorer_and_reviewer_share_the_corrected_boundary(self):
        explorer = {**VALID}
        report, _ = extract(stream([json.dumps(explorer)]), kind="explorer")
        self.assertEqual(report["status"], "complete")
        review, _ = extract(stream(["```json\n" + json.dumps(REVIEWER) + "\n```"]),
                            kind="reviewer")
        self.assertEqual(review["findings"], [])

    def test_every_role_prompt_requires_valid_json_and_exactly_one_object(self):
        for kind in ("plan", "implementer", "explorer", "reviewer", "decision"):
            with self.subTest(kind=kind):
                prompt = orc.report_prompt(kind, {})
                self.assertIn("ONE valid JSON object", prompt)
                self.assertIn("Escape every literal double quote", prompt)
                self.assertIn("no prose before or after it", prompt)

    def test_every_report_schema_declares_and_requires_contract_version(self):
        for kind in ("plan", "implementer", "explorer", "reviewer", "decision"):
            with self.subTest(kind=kind):
                document = orc.schema(kind)
                self.assertIn("contract_version", document["properties"])
                self.assertIn("contract_version", document["required"])


class RecoveryRegressions(Harness):
    def setUp(self):
        super().setUp()
        self.state.update({
            "status": "paused", "phase": "implement", "batch_index": 0,
            "pause_reason": "operator paused after a classified ingestion failure",
            "project_lease": {"status": "active", "run_id": "test-run00",
                              "project": str(self.project)},
        })
        self.job_id = "jobfailure1"
        self.job_dir = self.rundir / "jobs" / f"implementer-{self.job_id}"
        self.job_dir.mkdir(parents=True)
        self.data_root = self.root / "opencode-data"
        self.tree = self._commit_candidate()
        self._write_job(json.dumps(VALID), "stop")

    def _commit_candidate(self):
        (self.project / "app.py").write_text("value = 2\n")
        subprocess.run(["git", "add", "-A"], cwd=self.project, check=True,
                       capture_output=True)
        subprocess.run(["git", "commit", "-qm", "candidate"], cwd=self.project,
                       check=True, capture_output=True)
        snapshot = self.data_root / "snapshot" / "project" / "git"
        snapshot.parent.mkdir(parents=True)
        subprocess.run(["git", "clone", "--bare", "-q", str(self.project),
                        str(snapshot)], check=True, capture_output=True)
        return subprocess.run(["git", "rev-parse", "HEAD^{tree}"],
                              cwd=self.project, check=True, capture_output=True,
                              text=True).stdout.strip()

    def _write_job(self, report_text, reason, session=SESSION, terminal=True):
        events = [event("step_start", id="prt_start", type="step-start")]
        for part_id, text in (("prt_text", "Working."),
                              ("prt_report", report_text)):
            item = event("text", id=part_id, text=text)
            item["sessionID"] = session
            item["part"]["sessionID"] = session
            events.append(item)
        if terminal:
            finish = event("step_finish", id="prt_finish",
                           type="step-finish", reason=reason,
                           snapshot=self.tree)
            finish["sessionID"] = session
            finish["part"]["sessionID"] = session
            events.append(finish)
        (self.job_dir / "events.log").write_text(
            "\n".join(json.dumps(item) for item in events) + "\n")
        orc.atomic_json(self.job_dir / "execution.json",
                        {"returncode": 0, "seconds": 1.0})
        orc.atomic_json(self.job_dir / "launch.json",
                        {"phase": "exited", "returncode": 0})
        job = {
            "id": self.job_id, "kind": "implementer", "role": "implementer",
            "status": "failed", "path": str(self.job_dir),
            "session_id": session, "created_at": "2026-11-13T15:20:27+00:00",
            "contract_version": 2,
        }
        self.state["failed_jobs"] = [job]
        self.state["completed_jobs"] = []
        orc.save(self.rundir, self.state)
        with (self.rundir / orc.JOURNAL_FILE).open("a") as stream:
            stream.write(json.dumps({
                "event": "job_failed", "job_id": self.job_id,
                "batch_index": 0, "role": "implementer",
                "error": "report_invalid_json"}) + "\n")

    def test_dry_run_validates_identity_and_writes_nothing(self):
        result = orc.recover_report("test-run00", self.job_id,
                                    data_root=self.data_root)
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["applied"])
        self.assertFalse((self.job_dir / "recovered-report.json").exists())
        self.assertEqual(result["source_signature"],
                         orc.signature(orc.source_snapshot(self.project)))

    def test_apply_preserves_failed_job_and_adds_recovery_provenance(self):
        result = orc.recover_report(
            "test-run00", self.job_id, apply=True,
            acknowledge=f"recover-report:test-run00:{self.job_id}",
            data_root=self.data_root)
        self.assertTrue(result["applied"], result)
        folder, state = orc.load("test-run00")
        self.assertEqual(state["failed_jobs"][0]["status"], "failed")
        self.assertEqual(state["completed_jobs"], [])
        self.assertEqual(len(state["report_recoveries"]), 1)
        self.assertTrue((self.job_dir / "recovery.json").is_file())
        self.assertTrue((self.job_dir / "recovered-report-text.json").is_file())
        self.assertIn("failed job remains failed",
                      (self.job_dir / "recovery.json").read_text())
        report, job = orc.cached_recovered_job_report(folder, state, "implementer")
        self.assertEqual(report["summary"], "done")
        self.assertEqual(job["id"], self.job_id)

    def test_apply_requires_exact_acknowledgement(self):
        with self.assertRaisesRegex(RuntimeError, "acknowledge"):
            orc.recover_report("test-run00", self.job_id, apply=True,
                               acknowledge="yes", data_root=self.data_root)

    def test_recovery_rejects_missing_terminal_event(self):
        self._write_job(json.dumps(VALID), "stop", terminal=False)
        result = orc.recover_report("test-run00", self.job_id,
                                    data_root=self.data_root)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "missing_terminal_completion")

    def test_recovery_rejects_wrong_contract_version(self):
        self._write_job(json.dumps({**VALID, "contract_version": 3}), "stop")
        result = orc.recover_report("test-run00", self.job_id,
                                    data_root=self.data_root)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "contract_version_mismatch")

    def test_recovery_rejects_session_mismatch(self):
        self._write_job(json.dumps(VALID), "stop", session="ses_other")
        self.state["failed_jobs"][0]["session_id"] = SESSION
        orc.save(self.rundir, self.state)
        result = orc.recover_report("test-run00", self.job_id,
                                    data_root=self.data_root)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "session_mismatch")

    def test_recovery_rejects_candidate_changed_after_execution(self):
        (self.project / "app.py").write_text("value = 3\n")
        result = orc.recover_report("test-run00", self.job_id,
                                    data_root=self.data_root)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "source_unverified")

    def test_recovery_rejects_unreported_source_changes(self):
        (self.project / "extra.py").write_text("extra = 1\n")
        result = orc.recover_report("test-run00", self.job_id,
                                    data_root=self.data_root)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "unreported_source_changes")

    def test_recovered_report_is_rejected_after_the_candidate_changes(self):
        orc.recover_report("test-run00", self.job_id, apply=True,
                           acknowledge=f"recover-report:test-run00:{self.job_id}",
                           data_root=self.data_root)
        folder, state = orc.load("test-run00")
        (self.project / "app.py").write_text("value = 4\n")
        with self.assertRaisesRegex(RuntimeError, "Candidate changed"):
            orc.cached_recovered_job_report(folder, state, "implementer")


if __name__ == "__main__":
    unittest.main()
