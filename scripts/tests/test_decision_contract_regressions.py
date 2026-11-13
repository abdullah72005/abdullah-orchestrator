"""Regressions for the Architect decision contract and acceptance recovery.

Provenance for the fixtures (copied byte-for-byte from the failed pilot job
``decision-2613b77dde5a`` of run ``20261113T104752-32561af8``):

- ``decision-schema-pre-fix.json`` (sha256 e3c5f7ff…): the strict output schema
  written by the previous supervisor. It is structurally valid but omitted
  ``contract_version``, so the model could not emit the field the supervisor
  demanded.
- ``decision-report-pre-fix.json`` (sha256 a24ffe6a…): the raw Architect
  verdict, unchanged. It is semantically complete but has no contract_version.

No model call occurs: the CLI tests use a fake ``codex`` that writes the
payload to ``--output-last-message``.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import test_orchestrator as baseline

orc = baseline.orc
FIXTURES = Path(__file__).resolve().parent / "fixtures"
OLD_SCHEMA = json.loads((FIXTURES / "decision-schema-pre-fix.json").read_text(encoding="utf-8"))
OLD_REPORT = json.loads((FIXTURES / "decision-report-pre-fix.json").read_text(encoding="utf-8"))

FAKE_CLI = '''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
out = pathlib.Path(args[args.index("--output-last-message") + 1])
out.write_text(json.dumps(json.loads(os.environ["FAKE_DECISION"])))
'''


class DecisionSchemaContract(unittest.TestCase):
    def test_decision_schema_declares_and_requires_contract_version(self):
        document = orc.schema("decision")
        self.assertEqual(document["properties"]["contract_version"], {"type": "integer"})
        self.assertIn("contract_version", document["required"])
        self.assertEqual(set(document["required"]), set(document["properties"]))

    def test_prompt_and_generated_schema_agree(self):
        # The original defect: the prompt demanded contract_version while the
        # strict schema made it impossible to emit.
        prompt = orc.report_prompt("decision", {"goal": "accept batch"})
        self.assertIn("contract_version", prompt)
        self.assertIn("contract_version", orc.schema("decision")["required"])

    def test_every_report_kind_declares_semantic_contract_fields(self):
        for kind in orc.STRUCTURED_OUTPUT_KINDS:
            with self.subTest(kind=kind):
                document = orc.schema(kind)
                required = set(orc.REPORT_KEYS[kind]) | orc.REPORT_CONTRACT_FIELDS
                self.assertLessEqual(required, set(document["properties"]))
                self.assertLessEqual(required, set(document["required"]))

    def test_structurally_valid_but_contract_incomplete_schema_is_rejected(self):
        # The failed artifact passes strict structural validation; only the
        # contract check catches the missing mandatory field.
        self.assertIs(orc.validate_structured_output_schema(OLD_SCHEMA), OLD_SCHEMA)
        with self.assertRaisesRegex(ValueError, "contract_version"):
            orc.assert_report_schema_contract("decision", OLD_SCHEMA)

    def test_schema_generation_fails_closed_on_the_old_decision_schema(self):
        with patch.object(orc, "_report_schema", return_value=copy.deepcopy(OLD_SCHEMA)):
            with self.assertRaisesRegex(ValueError, "contract_version"):
                orc.schema("decision")

    def test_contract_documentation_includes_the_version(self):
        text = (orc.SKILL / "references/contracts.md").read_text(encoding="utf-8")
        blocks = text.split("## ")
        verdict = next(block for block in blocks if block.startswith("Strong verdict"))
        self.assertIn('"contract_version":2', verdict.replace(" ", ""))
        self.assertIn("mandatory", verdict)
        for section in ("Plan", "Worker"):
            block = next(block for block in blocks if block.startswith(section))
            self.assertIn("contract_version", block)


class DecisionReportContract(unittest.TestCase):
    setUp = baseline.ControlTests.setUp
    tearDown = baseline.ControlTests.tearDown

    def _fake_cli(self):
        fakebin = self.root / "bin"
        fakebin.mkdir(exist_ok=True)
        script = fakebin / "fake_cli.py"
        script.write_text(FAKE_CLI)
        script.chmod(0o755)
        if not (fakebin / "codex").exists():
            (fakebin / "codex").symlink_to(script)
        return fakebin

    def _decide(self, payload):
        fakebin = self._fake_cli()
        self.state["contract_version_required"] = 2
        orc.save(self.rundir, self.state)
        env = {"PATH": f"{fakebin}{os.pathsep}{os.environ['PATH']}",
               "FAKE_DECISION": json.dumps(payload), "OPENAI_API_KEY": ""}
        with patch.dict(os.environ, env):
            return orc.call_model(self.rundir, self.state, self.cfg, "architect",
                                  "decision", "decide the batch", self.project)

    def test_exact_failed_report_shape_is_rejected_with_actionable_error(self):
        self.assertNotIn("contract_version", OLD_REPORT)
        with self.assertRaisesRegex(RuntimeError, "contract_version"):
            self._decide(OLD_REPORT)
        job = self.state["failed_jobs"][-1]
        self.assertIn("contract_version", job["error"])
        self.assertNotIn(job["status"], {"complete"})
        self.assertFalse((Path(job["path"]) / "report.json").exists())

    def test_missing_or_invalid_versions_are_rejected(self):
        cases = {
            "missing": {key: value for key, value in OLD_REPORT.items()
                        if key != "contract_version"},
            "zero": dict(OLD_REPORT, contract_version=0),
            "one": dict(OLD_REPORT, contract_version=1),
            "string": dict(OLD_REPORT, contract_version="2"),
            "null": dict(OLD_REPORT, contract_version=None),
        }
        for label, payload in cases.items():
            with self.subTest(case=label):
                with self.assertRaisesRegex((RuntimeError, ValueError),
                                            "contract_version"):
                    self._decide(payload)

    def test_valid_contract_v2_decision_is_accepted(self):
        payload = dict(copy.deepcopy(OLD_REPORT), contract_version=2)
        report, job = self._decide(payload)
        self.assertEqual(report["contract_version"], 2)
        self.assertEqual(report["verdict"], "changes_required")
        self.assertEqual(job["contract_version"], 2)
        self.assertFalse(job["legacy_contract"])
        self.assertEqual(self.state["completed_jobs"][-1]["kind"], "decision")
        self.assertEqual(self.state["usage"]["strong_calls"], 1)
        self.assertTrue((Path(job["path"]) / "report.json").exists())


class AcceptanceTransition(unittest.TestCase):
    tearDown = baseline.ControlTests.tearDown

    def setUp(self):
        baseline.ControlTests.setUp(self)
        self.batch = {"title": "one", "goal": "change", "acceptance": ["works"],
                      "checks": [["true"]], "risk": "ordinary"}
        self.plan = {"contract_version": 2, "status": "complete", "summary": "plan",
                     "invariants": ["keep working"],
                     "batches": [copy.deepcopy(self.batch)], "blocker": "",
                     "required_exploration": {"job_id": "", "scope_satisfied": True}}
        self.snapshot = orc.source_snapshot(self.project)
        self.implementation = {"contract_version": 2, "status": "complete",
                               "summary": "implemented", "files": ["app.py"],
                               "tests": ["tests/test_duration.py"], "evidence": ["app.py:1"],
                               "unknowns": [], "blocker": ""}
        self.review = {"contract_version": 2, "status": "complete", "summary": "reviewed",
                       "files": ["app.py"], "tests": [], "evidence": ["app.py:1"],
                       "unknowns": [], "blocker": "", "findings": []}
        self.verification = {"passed": True, "evidence_version": 2,
                             "candidate_hash": orc.signature(self.snapshot)}
        self.decision = {"contract_version": 2, "verdict": "changes_required",
                         "reason": "candidate rejects long quantities",
                         "inspected": ["app.py:parse"], "correction": "fix the parser",
                         "dismissed_findings": []}
        self.state.update(
            status="running", phase="accept", plan=copy.deepcopy(self.plan),
            plan_version=orc.content_hash(self.plan), plan_revision=1, batch_index=0,
            contract_version_required=2, single_batch_fast_path=False,
            implementation=copy.deepcopy(self.implementation), implementation_job="impl-1",
            review=copy.deepcopy(self.review), verification=copy.deepcopy(self.verification),
            corrections=0, correction="",
            usage={"strong_calls": 3, "cheap_calls": 2, "failed_attempts": 1})
        orc.save(self.rundir, self.state)

    def test_changes_required_moves_to_the_head_of_the_correction_stage(self):
        before = {
            "implementation": copy.deepcopy(self.state["implementation"]),
            "review": copy.deepcopy(self.state["review"]),
            "verification": copy.deepcopy(self.state["verification"]),
            "usage": copy.deepcopy(self.state["usage"]),
        }
        with patch.object(orc, "strong_call", return_value=copy.deepcopy(self.decision)) as call:
            orc.advance(self.rundir, orc.read_json(self.rundir / "state.json"), self.cfg)
        state = orc.read_json(self.rundir / "state.json")
        call.assert_called_once()
        self.assertEqual(state["phase"], "implement")
        self.assertEqual(state["corrections"], 1)
        self.assertEqual(state["correction"], "fix the parser")
        self.assertEqual(state["architect_verdict"]["verdict"], "changes_required")
        # Prior evidence is preserved for the correction worker and audit.
        self.assertEqual(state["implementation"], before["implementation"])
        self.assertEqual(state["review"], before["review"])
        self.assertEqual(state["verification"], before["verification"])
        self.assertEqual(state["usage"], before["usage"])
        self.assertEqual([job["kind"] for job in state["completed_jobs"]],
                         [job["kind"] for job in self.state["completed_jobs"]])
        self.assertEqual(state["plan_version"], self.state["plan_version"])

    def test_source_change_after_verification_is_not_judged(self):
        (self.project / "app.py").write_text("value = 99\n")
        with patch.object(orc, "strong_call") as call:
            orc.advance(self.rundir, orc.read_json(self.rundir / "state.json"), self.cfg)
        call.assert_not_called()
        state = orc.read_json(self.rundir / "state.json")
        self.assertEqual(state["phase"], "verify")
        self.assertIsNone(state["review"])
        self.assertIsNone(state["check_progress"])

    def test_mismatched_evidence_binding_forces_reverification(self):
        self.state["verification"]["evidence_version"] = 2
        self.state["verification"]["path"] = str(self.rundir / "verification.json")
        orc.atomic_json(Path(self.state["verification"]["path"]), {
            "evidence_version": 2, "passed": True,
            "candidate_hash": "0" * 64, "plan_version": "stale"})
        orc.save(self.rundir, self.state)
        with patch.object(orc, "strong_call") as call:
            orc.advance(self.rundir, orc.read_json(self.rundir / "state.json"), self.cfg)
        call.assert_not_called()
        state = orc.read_json(self.rundir / "state.json")
        self.assertEqual(state["phase"], "verify")
        self.assertIsNone(state["verification"])

    def test_recovered_decision_without_matching_final_checks_is_rejected(self):
        jobdir = self.rundir / "jobs" / "decision-old"
        jobdir.mkdir(parents=True)
        orc.atomic_json(jobdir / "report.json", self.decision)
        self.state.update(
            single_batch_fast_path=True,
            completed_jobs=[{"id": "old", "kind": "decision", "role": "architect",
                             "status": "complete", "path": str(jobdir)}],
            last_consumed_job_id=None,
            check_progress={"finished": False})
        orc.save(self.rundir, self.state)
        with patch.object(orc, "run_checks") as checks, \
                patch.object(orc, "strong_call") as call:
            orc.advance(self.rundir, orc.read_json(self.rundir / "state.json"), self.cfg)
        checks.assert_not_called()
        call.assert_not_called()
        state = orc.read_json(self.rundir / "state.json")
        self.assertIn(state["status"], {"paused", "blocked"})
        self.assertEqual(state["phase"], "accept")
        self.assertIn("Recovered decision", state["pause_reason"])

    def test_failed_decision_preserves_evidence_for_a_decision_only_retry(self):
        # Reproduce the paused E2E shape: failed decision, prior stages intact.
        self.state.update(
            status="paused", phase="accept",
            pause_reason="Reconciled by operator; approval required before resume",
            failed_jobs=[{"id": "2613b77dde5a", "kind": "decision", "role": "architect",
                          "status": "failed", "contract_version": 0,
                          "error": "Newly dispatched workers must return contract_version: 2"}],
            active_job=None)
        orc.save(self.rundir, self.state)
        orc.resume_run("test-run00")
        state = orc.read_json(self.rundir / "state.json")
        self.assertEqual(state["status"], "running")
        self.assertEqual(state["phase"], "accept")
        self.assertEqual(state["implementation"], self.implementation)
        self.assertEqual(state["review"], self.review)
        self.assertEqual(state["verification"], self.verification)
        self.assertEqual(state["plan_version"], self.state["plan_version"])
        self.assertEqual(state["plan"]["batches"], self.plan["batches"])


if __name__ == "__main__":
    unittest.main()
