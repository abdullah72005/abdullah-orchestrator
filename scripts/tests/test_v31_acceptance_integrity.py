"""v3.1 acceptance integrity: late drift and decision binding.

Every verification record is a real supervisor record produced by
``run_checks``; nothing here weakens the evidence validator to make a test
green.  Fake strong calls model only the Architect's report, never its
authority to approve stale evidence.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import test_orchestrator as baseline
orc = baseline.orc


def make_plan(count=1, checks=None):
    batch = {"title": "one", "goal": "change app", "acceptance": ["works"],
             "checks": checks or [[sys.executable, "-c", "pass"]],
             "risk": "ordinary"}
    batches = [copy.deepcopy(batch) for _ in range(count)]
    for index, item in enumerate(batches):
        item["title"] = f"batch {index + 1}"
    return {"contract_version": 2, "status": "complete", "summary": "plan",
            "invariants": ["Keep behavior"], "batches": batches, "blocker": "",
            "required_exploration": {"job_id": "", "scope_satisfied": True}}


class AcceptanceIntegrityTests(unittest.TestCase):
    setUp = baseline.ControlTests.setUp
    tearDown = baseline.ControlTests.tearDown

    def install_check(self, name="v31check"):
        bin_dir = self.root / "check-bin"
        bin_dir.mkdir(exist_ok=True)
        script = bin_dir / name
        script.write_text("#!/bin/sh\nexit 0\n")
        script.chmod(0o755)
        env_patch = patch.dict(os.environ, {
            "PATH": str(bin_dir) + ":" + os.environ["PATH"]})
        env_patch.start()
        self.addCleanup(env_patch.stop)
        return script

    def prepare(self, plan, phase="accept", review=True, verify=True):
        self.state.update(
            phase=phase, plan=copy.deepcopy(plan),
            plan_version=orc.content_hash(plan), plan_revision=1,
            batch_index=0, corrections=0, correction="",
            single_batch_fast_path=True,
            review=({"status": "complete", "findings": [], "summary": "reviewed",
                     "files": [], "tests": [], "evidence": [], "unknowns": [],
                     "blocker": ""} if review else None))
        orc.save(self.rundir, self.state)
        if verify:
            batch = plan["batches"][0]
            evidence = orc.run_checks(self.rundir, self.state, self.cfg,
                                      self.project, batch)
            self.state["verification"] = {
                "path": evidence["path"], "passed": True,
                "candidate_hash": evidence["after_hash"],
                "evidence_version": orc.VERIFICATION_EVIDENCE_VERSION}
            self.state["check_progress"] = None
            orc.save(self.rundir, self.state)
            return evidence
        return None

    def add_decision_job(self, verdict, references, job_id="decision-old",
                         binding=True):
        jobdir = self.rundir / "jobs" / job_id
        jobdir.mkdir(parents=True, exist_ok=True)
        snapshot = orc.source_snapshot(self.project)
        orc.atomic_json(jobdir / "dispatch.json", {
            "kind": "decision", "role": "architect", "source": snapshot})
        orc.atomic_json(jobdir / "completion.json", {"final_snapshot": snapshot})
        orc.atomic_json(jobdir / "report.json", verdict)
        record = None
        if binding:
            record = orc.make_decision_binding(self.state, self.project, references)
            orc.atomic_json(jobdir / "decision-binding.json", record)
        job = {"id": job_id, "kind": "decision", "role": "architect",
               "status": "complete", "path": str(jobdir),
               "decision_binding": record, "final_snapshot": snapshot}
        self.state.setdefault("completed_jobs", []).append(job)
        self.state["last_consumed_job_id"] = None
        orc.save(self.rundir, self.state)
        return jobdir, record

    def verdict(self, value="approved"):
        return {"contract_version": 2, "verdict": value, "reason": "inspected",
                "inspected": ["app.py"], "correction": "", "dismissed_findings": []}

    def test_single_fast_path_late_check_executable_drift_blocks_completion(self):
        check = self.install_check()
        plan = make_plan(1, [[str(check)]])
        self.prepare(plan)
        original = check.read_text()

        def approve(*_args, **_kwargs):
            check.write_text(original + "# replaced during strong decision\n")
            return self.verdict()

        with patch.object(orc, "strong_call", side_effect=approve) as strong:
            orc.advance(self.rundir, self.state, self.cfg)
        strong.assert_called_once()
        self.assertNotEqual(self.state["status"], "complete")
        self.assertEqual(self.state["phase"], "verify")
        self.assertFalse(self.state["accepted_batches"])
        self.assertIsNone(self.state["verification"])
        self.assertTrue(self.state["invalidated_decisions"])
        reason = self.state["invalidated_decisions"][-1]["reason"]
        self.assertIn("executable", reason.lower())
        # Preserved artifacts stay inspectable; nothing was rolled back.
        self.assertTrue((self.rundir / "jobs").is_dir())
        self.assertIn("replaced during strong decision", check.read_text())

    def test_multibatch_late_tracked_source_edit_blocks_next_acceptance(self):
        plan = make_plan(2)
        self.prepare(plan)
        original = (self.project / "app.py").read_text()

        def approve(*_args, **_kwargs):
            (self.project / "app.py").write_text(original + "# late architect edit\n")
            return self.verdict()

        with patch.object(orc, "strong_call", side_effect=approve):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertFalse(self.state["accepted_batches"])
        self.assertEqual(self.state["phase"], "verify")
        self.assertIn("# late architect edit", (self.project / "app.py").read_text())
        self.assertTrue(self.state["invalidated_decisions"])

    def test_integration_late_tool_drift_clears_checks_and_reruns(self):
        check = self.install_check()
        plan = make_plan(2, [[str(check)]])
        self.state.update(
            phase="integrate", plan=copy.deepcopy(plan),
            plan_version=orc.content_hash(plan), plan_revision=1,
            batch_index=2, corrections=0, correction="",
            single_batch_fast_path=False,
            accepted_batches=[{"index": 0}, {"index": 1}],
            review={"status": "complete", "findings": []})
        orc.save(self.rundir, self.state)
        original = check.read_text()
        calls = {"count": 0}

        def approve(*_args, **_kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                check.write_text(original + "# integration drift\n")
            return self.verdict()

        with patch.object(orc, "strong_call", side_effect=approve):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertNotEqual(self.state["status"], "complete")
        self.assertIsNone(self.state["check_progress"])
        self.assertIsNone(self.state["verification"])
        self.assertTrue(self.state["invalidated_decisions"])
        first_path = self.state.get("verification") or {}
        with patch.object(orc, "strong_call", return_value=self.verdict()):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(self.state["status"], "complete")
        self.assertTrue(self.state["verification"]["path"])
        self.assertNotEqual(self.state["verification"]["path"],
                            first_path.get("path"))

    def test_cached_decision_evidence_byte_replacement_is_rejected(self):
        plan = make_plan(2)
        evidence = self.prepare(plan)
        self.add_decision_job(self.verdict(), [self.state["verification"]])
        path = Path(evidence["path"])
        path.write_text("\n" + path.read_text())
        with patch.object(orc, "strong_call") as strong:
            orc.advance(self.rundir, self.state, self.cfg)
        strong.assert_not_called()
        self.assertEqual(self.state["phase"], "verify")
        self.assertIsNone(self.state["verification"])
        self.assertEqual(self.state["invalidated_decisions"][-1]["kind"], "decision")

    def test_new_verification_record_requires_a_new_decision(self):
        plan = make_plan(2)
        self.prepare(plan)
        self.add_decision_job(self.verdict(), [self.state["verification"]])
        # Same source, but a genuinely new supervisor record.
        self.state["check_progress"] = None
        new_evidence = orc.run_checks(self.rundir, self.state, self.cfg,
                                      self.project, plan["batches"][0])
        self.state["verification"] = {
            "path": new_evidence["path"], "passed": True,
            "candidate_hash": new_evidence["after_hash"],
            "evidence_version": orc.VERIFICATION_EVIDENCE_VERSION}
        orc.save(self.rundir, self.state)
        with patch.object(orc, "strong_call") as strong:
            orc.advance(self.rundir, self.state, self.cfg)
        strong.assert_not_called()
        self.assertEqual(self.state["phase"], "verify")
        self.assertTrue(self.state["invalidated_decisions"])

    def test_unchanged_bound_recovery_consumes_without_duplicate_model_call(self):
        plan = make_plan(1)
        batch_ref = self.prepare(plan)
        self.state["single_batch_verification"] = dict(batch_ref)
        final = orc.run_checks(self.rundir, self.state, self.cfg, self.project,
                               {"title": "feature integration",
                                "checks": plan["batches"][0]["checks"]}, final=True)
        self.state["verification"] = {
            "path": final["path"], "passed": True,
            "candidate_hash": final["after_hash"],
            "evidence_version": orc.VERIFICATION_EVIDENCE_VERSION}
        references = [self.state["single_batch_verification"],
                      self.state["verification"]]
        self.add_decision_job(self.verdict(), references)
        # check_progress remains finished, exactly as after a crash.
        with patch.object(orc, "strong_call") as strong:
            orc.advance(self.rundir, self.state, self.cfg)
        strong.assert_not_called()
        self.assertEqual(self.state["status"], "complete")
        self.assertEqual(self.state["final_verdict"]["verdict"], "approved")
        self.assertTrue(self.state["accepted_batches"][0]["decision_binding"])

    def test_missing_decision_binding_cannot_authorize(self):
        plan = make_plan(2)
        self.prepare(plan)
        self.add_decision_job(self.verdict(), [self.state["verification"]],
                              binding=False)
        with patch.object(orc, "strong_call") as strong:
            orc.advance(self.rundir, self.state, self.cfg)
        strong.assert_not_called()
        self.assertEqual(self.state["phase"], "verify")
        self.assertIn("binding", self.state["invalidated_decisions"][-1]["reason"])

    def test_changed_plan_invalidates_stored_approval(self):
        plan = make_plan(2)
        self.prepare(plan)
        self.add_decision_job(self.verdict(), [self.state["verification"]])
        changed = copy.deepcopy(self.state["plan"])
        changed["invariants"] = ["A different invariant"]
        self.state["plan"] = changed
        orc.save(self.rundir, self.state)
        with patch.object(orc, "strong_call") as strong:
            orc.advance(self.rundir, self.state, self.cfg)
        strong.assert_not_called()
        self.assertEqual(self.state["phase"], "verify")
        self.assertIn("plan content changed",
                      self.state["invalidated_decisions"][-1]["reason"])

    def test_environment_drift_routes_to_verification_and_checks_run_again(self):
        plan = make_plan(2)
        evidence = self.prepare(plan)
        with patch.dict(os.environ, {"PYTHONPATH": "/v31/drifted"}):
            with patch.object(orc, "strong_call") as strong:
                orc.advance(self.rundir, self.state, self.cfg)
            strong.assert_not_called()
        self.assertEqual(self.state["phase"], "verify")
        self.assertIsNone(self.state["verification"])
        with patch.object(orc, "strong_call") as strong:
            orc.advance(self.rundir, self.state, self.cfg)
        strong.assert_not_called()
        state = orc.read_json(self.rundir / "state.json")
        self.assertEqual(state["phase"], "review")
        self.assertNotEqual(state["verification"]["path"], evidence["path"])
        self.assertTrue(Path(state["verification"]["path"]).is_file())

    def test_runtime_declaration_drift_routes_to_verification(self):
        declaration = self.project / ".abdullah"
        declaration.mkdir()
        declared = self.project / "runtime.conf"
        declared.write_text("MODE=one\n")
        (declaration / "runtime-inputs.json").write_text(json.dumps(
            {"include": ["runtime.conf"], "required": ["runtime.conf"]}))
        plan = make_plan(2)
        self.prepare(plan)
        declared.write_text("MODE=two\n")
        with patch.object(orc, "strong_call") as strong:
            orc.advance(self.rundir, self.state, self.cfg)
        strong.assert_not_called()
        self.assertEqual(self.state["phase"], "verify")
        self.assertIn("stale", self.state["invalidated_decisions"][-1]["reason"].lower())

    def test_configuration_byte_drift_routes_to_verification(self):
        plan = make_plan(2)
        self.prepare(plan)
        config_path = Path(orc.CONFIG_PATH)
        config_path.write_text(config_path.read_text() + "\n")
        with patch.object(orc, "strong_call") as strong:
            orc.advance(self.rundir, self.state, self.cfg)
        strong.assert_not_called()
        self.assertEqual(self.state["phase"], "verify")
        self.assertIsNone(self.state["verification"])

    def test_clean_single_completion_binds_batch_and_final_records(self):
        plan = make_plan(1)
        batch_ref = self.prepare(plan)

        def approve(_dir, state, _cfg, _kind, extra=None, **kwargs):
            references = [state["single_batch_verification"], state["verification"]]
            state["decision_binding"] = orc.make_decision_binding(
                state, self.project, references)
            return self.verdict()

        with patch.object(orc, "strong_call", side_effect=approve):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(self.state["status"], "complete")
        accepted = self.state["accepted_batches"][0]
        self.assertEqual(accepted["verification"]["path"], batch_ref["path"])
        self.assertTrue(self.state["final_evidence"]["final"])
        self.assertEqual(self.state["decision_binding"]["version"],
                         orc.DECISION_BINDING_VERSION)
        self.assertEqual(len(self.state["decision_binding"]["verification"]), 2)


if __name__ == "__main__":
    unittest.main()
