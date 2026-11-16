"""v3.1 stale-review verification recovery.

Every verification record here is produced by the real supervisor
``run_checks``.  Model dispatch is always a spy or a fake return value; no test
launches a real model CLI.  The tests use disposable Git checkouts and synthetic
run directories only.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

import test_orchestrator as baseline
import test_v31_acceptance_integrity as acceptance
orc = baseline.orc

make_plan = acceptance.make_plan


REVIEWER_REPORT = {
    "contract_version": 2, "status": "complete", "summary": "fresh independent review",
    "findings": [], "files": ["app.py"], "tests": [], "evidence": ["app.py:1"],
    "unknowns": [], "blocker": "",
}


class ReviewRecoveryTests(unittest.TestCase):
    setUp = baseline.ControlTests.setUp
    tearDown = baseline.ControlTests.tearDown
    install_check = acceptance.AcceptanceIntegrityTests.install_check
    prepare = acceptance.AcceptanceIntegrityTests.prepare
    verdict = acceptance.AcceptanceIntegrityTests.verdict

    # -- fixtures ---------------------------------------------------------
    def state_file(self):
        return orc.read_json(self.rundir / "state.json")

    def stage(self, expected=None):
        return orc.stage_run(self.state["id"], expected)

    def resume(self):
        state = self.state_file()
        orc.modify_locked(self.rundir, state, state["id"], "resume")

    def drifting_path(self):
        empty = self.root / "empty-path-entry"
        empty.mkdir(exist_ok=True)
        return patch.dict(os.environ, {
            "PATH": str(empty) + os.pathsep + os.environ["PATH"]})

    def add_reviewer_cache(self, state, snapshot=None):
        """An unconsumed completed Reviewer report predating invalidation."""
        snapshot = snapshot or orc.source_snapshot(self.project)
        jobdir = self.rundir / "jobs" / "reviewer-old"
        jobdir.mkdir(parents=True, exist_ok=True)
        orc.atomic_json(jobdir / "dispatch.json", {
            "kind": "reviewer", "role": "reviewer", "source": snapshot})
        orc.atomic_json(jobdir / "completion.json", {"final_snapshot": snapshot})
        orc.atomic_json(jobdir / "report.json", dict(REVIEWER_REPORT,
                                                     summary="stale pre-invalidation review"))
        state.setdefault("completed_jobs", []).append({
            "id": "reviewer-old", "kind": "reviewer", "role": "reviewer",
            "status": "complete", "path": str(jobdir), "final_snapshot": snapshot})
        state["last_consumed_job_id"] = None
        return jobdir

    def add_recovered_reviewer_cache(self, state, snapshot=None):
        """An applied recovered Reviewer report predating invalidation."""
        snapshot = snapshot or orc.source_snapshot(self.project)
        jobdir = self.rundir / "jobs" / "reviewer-recovered-old"
        jobdir.mkdir(parents=True, exist_ok=True)
        report_path = jobdir / "recovered-report.json"
        recovery_path = jobdir / "recovery.json"
        orc.atomic_json(jobdir / "dispatch.json", {
            "kind": "reviewer", "role": "reviewer", "source": snapshot})
        orc.atomic_json(report_path, dict(REVIEWER_REPORT,
                                          summary="stale recovered review"))
        record = {
            "version": 1, "run_id": state["id"], "job_id": "reviewer-recovered-old",
            "kind": "reviewer", "role": "reviewer", "applied_at": orc.now(),
            "actor": "test", "report_path": str(report_path),
            "text_path": str(jobdir / "text.json"), "recovery_path": str(recovery_path),
            "report_sha256": orc.content_hash(dict(REVIEWER_REPORT,
                                                   summary="stale recovered review")),
            "source_signature": orc.signature(snapshot),
            "batch_index": state.get("batch_index", 0),
        }
        orc.atomic_json(recovery_path, record)
        orc.atomic_json(jobdir / "text.json", {})
        state.setdefault("failed_jobs", []).append({
            "id": "reviewer-recovered-old", "kind": "reviewer", "role": "reviewer",
            "status": "interrupted", "path": str(jobdir)})
        state.setdefault("report_recoveries", []).append(record)
        state["last_consumed_recovery_job_id"] = None
        return record

    def add_old_decision(self, state):
        jobdir = self.rundir / "jobs" / "decision-old"
        jobdir.mkdir(parents=True, exist_ok=True)
        snapshot = orc.source_snapshot(self.project)
        binding = orc.make_decision_binding(
            state, self.project, [state["verification"]])
        orc.atomic_json(jobdir / "dispatch.json", {
            "kind": "decision", "role": "architect", "source": snapshot})
        orc.atomic_json(jobdir / "completion.json", {"final_snapshot": snapshot})
        orc.atomic_json(jobdir / "report.json", self.verdict())
        orc.atomic_json(jobdir / "decision-binding.json", binding)
        state.setdefault("completed_jobs", []).append({
            "id": "decision-old", "kind": "decision", "role": "architect",
            "status": "complete", "path": str(jobdir), "final_snapshot": snapshot,
            "decision_binding": binding})
        state["last_consumed_job_id"] = None
        return jobdir

    def prepare_blocked_review(self, plan=None):
        plan = plan or make_plan(1)
        evidence = self.prepare(plan, phase="review", review=False)
        self.state["schema_version"] = orc.STATE_SCHEMA_VERSION
        self.state["implementation"] = {
            "status": "complete", "summary": "already implemented",
            "files": ["app.py"], "tests": [], "evidence": [], "unknowns": [],
            "blocker": "", "findings": []}
        self.state["implementation_job"] = "implementer-old"
        orc.save(self.rundir, self.state)
        return plan, evidence

    # -- incident shape and full fresh pipeline ---------------------------
    def test_saved_incident_shape_rewinds_once_and_fresh_pipeline_completes(self):
        plan = make_plan(1)
        # Dirty, ignored and untracked content must survive recovery unchanged.
        (self.project / "app.py").write_text(
            (self.project / "app.py").read_text() + "# pre-existing dirty work\n")
        (self.project / ".env.local").write_text("LOCAL_ONLY=1\n")
        (self.project / "untracked.txt").write_text("untracked work\n")
        evidence = self.prepare(plan, phase="review", review=False)
        implementation = {
            "status": "complete", "summary": "already implemented",
            "files": ["app.py"], "tests": [], "evidence": [], "unknowns": [],
            "blocker": "", "findings": []}
        self.state.update({
            "schema_version": orc.STATE_SCHEMA_VERSION,
            "implementation": copy.deepcopy(implementation),
            "implementation_job": "implementer-old",
            "route_authorizations": [{"id": "grant", "role": "reviewer",
                                      "route_sha256": "route", "max_dispatches": 2,
                                      "used": 1}],
            "worker_fallback_authorization": {"role": "reviewer", "used": 0},
            "usage": {"strong_calls": 1, "cheap_calls": 2},
        })
        self.add_reviewer_cache(self.state)
        # Emulate an existing markerless schema-3 blocked/review run.
        self.state["status"] = "blocked"
        self.state["pause_reason"] = "stale verification"
        orc.save(self.rundir, self.state)
        evidence_path = Path(evidence["path"])
        evidence_bytes = evidence_path.read_bytes()
        source_before = orc.source_write_sha(orc.source_snapshot(self.project))
        files_before = {
            name: (self.project / name).read_bytes()
            for name in ("app.py", ".env.local", "untracked.txt")}
        recovery_dir = self.rundir / "jobs"
        jobs_before = sorted(path.name for path in recovery_dir.iterdir())

        with self.drifting_path(), \
                patch.object(orc, "call_model",
                             side_effect=AssertionError("unexpected model dispatch")) as model, \
                patch.object(orc, "strong_call",
                             side_effect=AssertionError("unexpected strong call")):
            self.resume()
            result = self.stage()

        state = self.state_file()
        self.assertEqual(result["next_action"], "orchestrator_stage")
        self.assertIsNone(result["error"])
        self.assertEqual(state["phase"], "verify")
        self.assertEqual(state["status"], "running")
        self.assertIsNone(state["verification"])
        self.assertIsNone(state["check_progress"])
        self.assertIsNone(state["review"])
        self.assertIsNone(state["architect_verdict"])
        self.assertEqual(len(state["review_recoveries"]), 1)
        recovery = state["review_recovery"]
        self.assertEqual(recovery["code"], "provenance_drift")
        self.assertIn("environment", recovery["dimensions"])
        self.assertIn("toolchain", recovery["dimensions"])
        self.assertEqual(recovery["evidence"]["sha256"],
                         orc.hashlib.sha256(evidence_bytes).hexdigest())
        self.assertTrue(any("PATH" in item["field"]
                            for item in recovery["differences"]["environment"]))
        self.assertEqual(state["implementation"], implementation)
        self.assertEqual(state["batch_index"], 0)
        self.assertEqual(state["plan_version"], orc.content_hash(plan))
        self.assertEqual(state["route_authorizations"][0]["used"], 1)
        self.assertEqual(state["usage"], {"strong_calls": 1, "cheap_calls": 2})
        self.assertEqual(model.call_count, 0)
        self.assertTrue(evidence_path.is_file())
        self.assertEqual(evidence_path.read_bytes(), evidence_bytes)
        self.assertEqual(source_before,
                         orc.source_write_sha(orc.source_snapshot(self.project)))
        for name, value in files_before.items():
            self.assertEqual((self.project / name).read_bytes(), value, name)
        self.assertEqual(jobs_before,
                         sorted(path.name for path in recovery_dir.iterdir()))

        # A repeated resume/stage must not duplicate invalidation or authority.
        self.resume()
        self.assertEqual(len(self.state_file()["review_recoveries"]), 1)
        self.assertEqual(self.state_file()["phase"], "verify")
        self.assertEqual(model.call_count, 0)

        # Fresh real checks, then a fresh independent Reviewer and acceptance.
        with self.drifting_path():
            verify_result = self.stage("verify")
        self.assertIsNone(verify_result["error"])
        state = self.state_file()
        self.assertEqual(state["phase"], "review")
        self.assertNotEqual(state["verification"]["path"], str(evidence_path))
        self.assertTrue(Path(state["verification"]["path"]).is_file())

        fake_job = {"id": "reviewer-new", "kind": "reviewer",
                    "role": "reviewer", "status": "complete",
                    "path": str(self.rundir / "jobs")}
        with self.drifting_path(), \
                patch.object(orc, "call_model",
                             return_value=(dict(REVIEWER_REPORT), fake_job)) as model:
            review_result = self.stage("review")
        self.assertIsNone(review_result["error"])
        self.assertEqual(model.call_count, 1)
        state = self.state_file()
        self.assertEqual(state["review"]["summary"], "fresh independent review")
        self.assertEqual(state["phase"], "accept")

        with self.drifting_path(), \
                patch.object(orc, "strong_call",
                             return_value=self.verdict()) as strong:
            accept_result = self.stage("accept")
        self.assertIsNone(accept_result["error"])
        strong.assert_called_once()
        state = self.state_file()
        self.assertEqual(state["status"], "complete")
        self.assertEqual(state["accepted_batches"][0]["index"], 0)
        self.assertEqual(state["route_authorizations"][0]["used"], 1)
        self.assertEqual(evidence_path.read_bytes(), evidence_bytes)

    # -- classification ---------------------------------------------------
    def test_environment_only_drift_is_classified_and_recoverable(self):
        self.prepare(make_plan(1), phase="review", review=False)
        state = self.state_file()
        with patch.dict(os.environ, {"PYTHONPATH": "/v31/review-drift"}):
            current = orc.source_snapshot(self.project)
            with self.assertRaises(orc.VerificationEvidenceRejected) as raised:
                orc.load_verification_evidence(
                    state["verification"], current,
                    plan_version=state.get("plan_version"))
        error = raised.exception
        self.assertIsInstance(error, ValueError)
        self.assertEqual(error.code, "provenance_drift")
        self.assertEqual(error.dimensions, ["environment"])
        self.assertTrue(error.recoverable)
        fields = error.fields["environment"]
        self.assertTrue(any(item["field"].startswith("values.PYTHONPATH")
                            for item in fields))
        self.assertNotIn("/v31/review-drift",
                         json.dumps(error.as_dict()))

    def test_check_executable_replacement_is_classified_separately(self):
        check = self.install_check("v31driftcheck")
        self.prepare(make_plan(1, [[str(check)]]), phase="review", review=False)
        state = self.state_file()
        check.write_text(check.read_text() + "# replaced\n")
        with self.assertRaises(orc.VerificationEvidenceRejected) as raised:
            orc.load_verification_evidence(
                state["verification"], orc.source_snapshot(self.project),
                plan_version=state.get("plan_version"))
        error = raised.exception
        self.assertEqual(error.code, "check_executable_drift")
        self.assertEqual(error.dimensions, ["check_executable"])
        self.assertTrue(error.recoverable)
        self.assertTrue(any("v31driftcheck" in item["field"]
                            for item in error.fields["check_executable"])
                        or error.fields["check_executable"])

    def test_broader_toolchain_drift_is_classified_separately(self):
        self.prepare(make_plan(1), phase="review", review=False)
        state = self.state_file()
        original = orc.toolchain_identity()
        changed = copy.deepcopy(original)
        changed["node"] = {"available": True, "sha256": "f" * 64}
        with patch.object(orc, "toolchain_identity", return_value=changed):
            current = orc.source_snapshot(self.project)
            with self.assertRaises(orc.VerificationEvidenceRejected) as raised:
                orc.load_verification_evidence(
                    state["verification"], current,
                    plan_version=state.get("plan_version"))
        error = raised.exception
        self.assertEqual(error.code, "provenance_drift")
        self.assertEqual(error.dimensions, ["toolchain"])
        self.assertTrue(error.recoverable)
        self.assertTrue(any(item["field"].startswith("node")
                            for item in error.fields["toolchain"]))

    # -- policy re-evaluation --------------------------------------------
    def test_unavailable_executable_blocks_without_executing_checks(self):
        check = self.install_check("v31missingtool")
        self.prepare(make_plan(1, [[str(check)]]), phase="review", review=False)
        evidence = Path(self.state_file()["verification"]["path"])
        original = evidence.read_bytes()
        check.unlink()
        with patch.object(orc, "call_model",
                          side_effect=AssertionError("unexpected model")) as model, \
                patch.object(orc, "run_checks",
                             side_effect=AssertionError("unexpected check")) as checks:
            result = self.stage("review")
        state = self.state_file()
        self.assertEqual(model.call_count, 0)
        self.assertEqual(checks.call_count, 0)
        self.assertEqual(state["phase"], "review")
        self.assertEqual(state["status"], "blocked")
        self.assertFalse(state.get("review_recoveries"))
        self.assertEqual(state["verification_rejection"]["code"],
                         "check_executable_unavailable")
        self.assertIn("No checks were executed", state["pause_reason"])
        self.assertEqual(result["next_action"], "orchestrator_resume")
        self.assertEqual(evidence.read_bytes(), original)

    def test_newly_disallowed_command_blocks_without_executing_checks(self):
        bin_dir = self.root / "fake-python-bin"
        bin_dir.mkdir()
        fake = bin_dir / "python3"
        fake.write_text("#!/bin/sh\nexit 0\n")
        fake.chmod(0o755)
        env_patch = patch.dict(os.environ, {
            "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"]})
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.prepare(make_plan(1, [["python3", "-c", "pass"]]),
                     phase="review", review=False)
        evidence = Path(self.state_file()["verification"]["path"])
        original = evidence.read_bytes()
        fake.unlink()
        stripped = copy.deepcopy(self.cfg)
        stripped["verification"]["command_policy"]["exceptions"] = []
        with patch.object(orc, "call_model",
                          side_effect=AssertionError("unexpected model")), \
                patch.object(orc, "run_checks",
                             side_effect=AssertionError("unexpected check")):
            with orc.exclusive(self.rundir):
                folder, state = orc.load(self.state["id"])
                orc.advance(folder, state, stripped)
        state = self.state_file()
        self.assertEqual(state["phase"], "review")
        self.assertEqual(state["status"], "blocked")
        self.assertEqual(state["verification_rejection"]["code"],
                         "command_disallowed")
        self.assertIn("command_policy exception", state["pause_reason"])
        self.assertFalse(state.get("review_recoveries"))
        self.assertEqual(evidence.read_bytes(), original)

    # -- non-recoverable evidence ----------------------------------------
    def test_source_change_cannot_be_laundered_into_fresh_authority(self):
        self.prepare(make_plan(1), phase="review", review=False)
        (self.project / "app.py").write_text(
            (self.project / "app.py").read_text() + "# source changed\n")
        with patch.object(orc, "call_model",
                          side_effect=AssertionError("unexpected model")) as model:
            self.stage("review")
        state = self.state_file()
        self.assertEqual(model.call_count, 0)
        self.assertEqual(state["phase"], "review")
        self.assertEqual(state["status"], "blocked")
        self.assertFalse(state.get("review_recoveries"))
        self.assertIn(state["verification_rejection"]["code"],
                      {"reference_stale", "source_changed"})
        self.assertIsNotNone(state["verification"])

    def test_configuration_change_cannot_be_laundered(self):
        self.prepare(make_plan(1), phase="review", review=False)
        config_path = Path(orc.CONFIG_PATH)
        original = config_path.read_text()
        self.addCleanup(config_path.write_text, original)
        config_path.write_text(original + "\n")
        with patch.object(orc, "call_model",
                          side_effect=AssertionError("unexpected model")) as model:
            with self.assertRaisesRegex(RuntimeError, "config_changed"):
                self.stage("review")
        state = self.state_file()
        self.assertEqual(model.call_count, 0)
        self.assertEqual(state["phase"], "review")
        self.assertFalse(state.get("review_recoveries"))
        self.assertIsNotNone(state["verification"])

    def test_runtime_input_change_cannot_be_laundered(self):
        declaration = self.project / ".abdullah"
        declaration.mkdir()
        runtime = self.project / "runtime.conf"
        runtime.write_text("MODE=one\n")
        (declaration / "runtime-inputs.json").write_text(json.dumps(
            {"include": ["runtime.conf"], "required": ["runtime.conf"]}))
        self.prepare(make_plan(1), phase="review", review=False)
        runtime.write_text("MODE=two\n")
        with patch.object(orc, "call_model",
                          side_effect=AssertionError("unexpected model")):
            self.stage("review")
        state = self.state_file()
        self.assertEqual(state["status"], "blocked")
        self.assertFalse(state.get("review_recoveries"))
        self.assertIn(state["verification_rejection"]["code"],
                      {"reference_stale", "source_changed",
                       "runtime_inputs", "provenance_drift"})

    def test_changed_plan_cannot_be_laundered(self):
        self.prepare(make_plan(1), phase="review", review=False)
        state = self.state_file()
        changed = copy.deepcopy(state["plan"])
        changed["invariants"] = ["A different invariant"]
        state["plan"] = changed
        state["plan_version"] = orc.content_hash(changed)
        orc.save(self.rundir, state)
        with patch.object(orc, "call_model",
                          side_effect=AssertionError("unexpected model")):
            self.stage("review")
        state = self.state_file()
        self.assertEqual(state["phase"], "review")
        self.assertEqual(state["status"], "blocked")
        self.assertEqual(state["verification_rejection"]["code"], "plan_changed")
        self.assertFalse(state.get("review_recoveries"))

    def test_missing_corrupt_failed_and_incomplete_evidence_block(self):
        cases = {}
        for name in ("missing", "corrupt", "failed", "incomplete"):
            self.prepare(make_plan(1), phase="review", review=False)
            state = self.state_file()
            path = Path(state["verification"]["path"])
            if name == "missing":
                path.unlink()
            elif name == "corrupt":
                path.write_text("{not json")
            elif name == "failed":
                record = json.loads(path.read_text())
                record["passed"] = False
                path.write_text(json.dumps(record))
            else:
                record = json.loads(path.read_text())
                record["provenance"]["source"]["provenance_complete"] = False
                path.write_text(json.dumps(record))
            with patch.object(orc, "call_model",
                              side_effect=AssertionError("unexpected model")) as model:
                self.stage("review")
            final = self.state_file()
            cases[name] = final["verification_rejection"]["code"]
            self.assertEqual(model.call_count, 0)
            self.assertEqual(final["phase"], "review")
            self.assertEqual(final["status"], "blocked")
            self.assertFalse(final.get("review_recoveries"))
        self.assertEqual(cases["missing"], "record_missing")
        self.assertEqual(cases["corrupt"], "record_unreadable")
        self.assertEqual(cases["failed"], "evidence_not_passed")
        self.assertEqual(cases["incomplete"], "provenance_incomplete")

    def test_missing_verification_log_blocks_without_model(self):
        self.prepare(make_plan(1), phase="review", review=False)
        state = self.state_file()
        record = orc.read_json(Path(state["verification"]["path"]))
        Path(record["commands"][0]["log"]).unlink()
        with patch.object(orc, "call_model",
                          side_effect=AssertionError("unexpected model")) as model:
            self.stage("review")
        final = self.state_file()
        self.assertEqual(model.call_count, 0)
        self.assertEqual(final["status"], "blocked")
        self.assertEqual(final["verification_rejection"]["code"], "log_missing")
        self.assertFalse(final.get("review_recoveries"))

    def test_unknown_drift_dimension_is_not_recoverable(self):
        self.prepare(make_plan(1), phase="review", review=False)
        with patch.object(orc, "provenance_drift", return_value=["mystery"]), \
                patch.object(orc, "call_model",
                             side_effect=AssertionError("unexpected model")):
            self.stage("review")
        state = self.state_file()
        self.assertEqual(state["status"], "blocked")
        self.assertFalse(state.get("review_recoveries"))
        self.assertEqual(state["verification_rejection"]["code"],
                         "provenance_drift")
        self.assertEqual(state["verification_rejection"]["dimensions"],
                         ["mystery"])
        self.assertFalse(state["verification_rejection"]["recoverable"])

    # -- ownership and containment ---------------------------------------
    def test_active_or_uncertain_execution_blocks_recovery(self):
        for field, value in (
                ("active_check", {"id": "check-live", "argv": ["true"],
                                  "status": "uncertain", "pid": 999999}),
                ("active_job", {"id": "job-live", "kind": "reviewer",
                                "role": "reviewer", "status": "uncertain",
                                "pid": 999999, "error": "unproven stop"})):
            self.prepare(make_plan(1), phase="review", review=False)
            self.state.update({field: copy.deepcopy(value),
                               "status": "uncertain"})
            orc.save(self.rundir, self.state)
            with self.drifting_path(), \
                    patch.object(orc, "call_model",
                                 side_effect=AssertionError("unexpected model")):
                with orc.exclusive(self.rundir):
                    folder, state = orc.load(self.state["id"])
                    orc.advance(folder, state, self.cfg)
            final = self.state_file()
            self.assertEqual(final[field]["id"], value["id"])
            self.assertEqual(final["phase"], "review")
            self.assertFalse(final.get("review_recoveries"))
            self.assertEqual(final["verification_rejection"]["code"],
                             "active_execution")
            with self.assertRaisesRegex(RuntimeError, "Uncertain active dispatch"):
                orc.modify_locked(self.rundir, final, final["id"], "resume")

    # -- crash seams and idempotence -------------------------------------
    def test_crash_before_state_commit_retains_old_rejection(self):
        self.prepare(make_plan(1), phase="review", review=False)
        original = self.state_file()["verification"]["path"]
        with self.drifting_path(), \
                patch.object(orc, "save", side_effect=OSError("disk full")):
            with orc.exclusive(self.rundir):
                folder, state = orc.load(self.state["id"])
                with self.assertRaises(OSError):
                    orc.advance(folder, state, self.cfg)
        disk = self.state_file()
        self.assertEqual(disk["phase"], "review")
        self.assertEqual(disk["verification"]["path"], original)
        self.assertFalse(disk.get("review_recoveries"))

    def test_interrupted_journal_append_leaves_state_authoritative(self):
        self.prepare(make_plan(1), phase="review", review=False)
        real = orc.journal_event

        def flaky(run_dir, state, event, **fields):
            if event == "review_verification_recovered":
                raise OSError("journal interrupted")
            return real(run_dir, state, event, **fields)

        with self.drifting_path(), \
                patch.object(orc, "journal_event", side_effect=flaky), \
                patch.object(orc, "call_model",
                             side_effect=AssertionError("unexpected model")):
            result = self.stage("review")
        self.assertIsNone(result["error"])
        state = self.state_file()
        self.assertEqual(state["phase"], "verify")
        self.assertEqual(state["status"], "running")
        self.assertIsNone(state["verification"])
        self.assertEqual(len(state["review_recoveries"]), 1)

    def test_recovery_audit_is_idempotent_and_linked_to_journal(self):
        self.prepare(make_plan(1), phase="review", review=False)
        with self.drifting_path(), \
                patch.object(orc, "call_model",
                             side_effect=AssertionError("unexpected model")):
            self.stage("review")
        state = self.state_file()
        first = state["review_recovery"]
        self.assertEqual(len(state["review_recoveries"]), 1)
        journal = orc.journal_tail(self.rundir, limit=30)
        events = [item for item in journal
                  if item.get("event") == "review_verification_recovered"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["recovery_id"], first["id"])
        self.assertEqual(events[0]["next_action"], "orchestrator_stage")
        # Re-delivery of the same invalidation cannot create a second epoch or
        # duplicate audit record.
        with orc.exclusive(self.rundir):
            folder, current = orc.load(self.state["id"])
            error = orc.VerificationEvidenceRejected(
                first["reason"], code=first["code"],
                dimensions=first["dimensions"], recoverable=True,
                details={"record_sha256": first["evidence"]["sha256"],
                         "evidence_version": first["evidence"]["evidence_version"]})
            reference = {"path": first["evidence"]["path"], "passed": True,
                         "candidate_hash": first["evidence"]["candidate_hash"],
                         "evidence_version": first["evidence"]["evidence_version"]}
            again = orc._rewind_review_to_verify(folder, current, error, reference)
        final = self.state_file()
        self.assertEqual(again["id"], first["id"])
        self.assertEqual(len(final["review_recoveries"]), 1)
        self.assertEqual(final["authority_epoch"], first["authority_epoch"])

    # -- cache disarming --------------------------------------------------
    def test_old_completed_reviewer_is_not_reused_after_fresh_verification(self):
        self.prepare_blocked_review()
        state = self.state_file()
        self.add_reviewer_cache(state)
        orc.save(self.rundir, state)
        with self.drifting_path():
            self.stage("review")
        self.assertEqual(self.state_file()["phase"], "verify")
        with self.drifting_path():
            self.stage("verify")
        fake_job = {"id": "reviewer-new", "kind": "reviewer",
                    "path": str(self.rundir / "jobs")}
        with self.drifting_path(), \
                patch.object(orc, "call_model",
                             return_value=(dict(REVIEWER_REPORT), fake_job)) as model:
            self.stage("review")
        self.assertEqual(model.call_count, 1)
        state = self.state_file()
        self.assertEqual(state["review"]["summary"], "fresh independent review")
        self.assertEqual(state["authority_epoch"], 1)

    def test_old_recovered_reviewer_is_not_reused_after_fresh_verification(self):
        self.prepare(make_plan(1), phase="review", review=False)
        state = self.state_file()
        self.add_recovered_reviewer_cache(state)
        orc.save(self.rundir, state)
        with self.drifting_path():
            self.stage("review")
        with self.drifting_path():
            self.stage("verify")
        fake_job = {"id": "reviewer-new", "kind": "reviewer",
                    "path": str(self.rundir / "jobs")}
        with self.drifting_path(), \
                patch.object(orc, "call_model",
                             return_value=(dict(REVIEWER_REPORT), fake_job)) as model:
            self.stage("review")
        self.assertEqual(model.call_count, 1)
        self.assertNotEqual(self.state_file()["review"]["summary"],
                            "stale recovered review")
        with self.drifting_path(), \
                patch.object(orc, "strong_call",
                             return_value=self.verdict()) as strong:
            self.stage("accept")
        strong.assert_called_once()
        self.assertEqual(self.state_file()["status"], "complete")

    def test_old_decision_cache_cannot_authorize_after_recovery(self):
        self.prepare(make_plan(1), phase="review", review=False)
        state = self.state_file()
        self.add_old_decision(state)
        orc.save(self.rundir, state)
        with self.drifting_path():
            self.stage("review")
        with self.drifting_path():
            self.stage("verify")
        fake_job = {"id": "reviewer-new", "kind": "reviewer",
                    "path": str(self.rundir / "jobs")}
        with self.drifting_path(), \
                patch.object(orc, "call_model",
                             return_value=(dict(REVIEWER_REPORT), fake_job)):
            self.stage("review")
        with self.drifting_path(), \
                patch.object(orc, "strong_call",
                             return_value=self.verdict()) as strong:
            self.stage("accept")
        strong.assert_called_once()
        state = self.state_file()
        self.assertEqual(state["status"], "complete")
        self.assertEqual(state["accepted_batches"][0]["index"], 0)
        self.assertTrue(any(job.get("id") == "decision-old"
                            for job in state.get("completed_jobs", [])))

    def test_interrupted_partial_reviewer_is_never_a_reusable_completion(self):
        self.prepare(make_plan(1), phase="review", review=False)
        state = self.state_file()
        partial_dir = self.rundir / "jobs" / "reviewer-partial"
        partial_dir.mkdir(parents=True)
        orc.atomic_json(partial_dir / "report.json", {
            "contract_version": 2, "status": "blocked",
            "summary": "partial review", "findings": [], "blocker": "interrupted"})
        state.setdefault("failed_jobs", []).append({
            "id": "reviewer-partial", "kind": "reviewer", "role": "reviewer",
            "status": "interrupted", "path": str(partial_dir),
            "error": "interrupted"})
        state["review"] = {"status": "blocked", "summary": "partial review",
                           "findings": [], "blocker": "interrupted"}
        orc.save(self.rundir, state)
        with self.drifting_path():
            self.stage("review")
        self.assertIsNone(self.state_file()["review"])
        with self.drifting_path():
            self.stage("verify")
        fake_job = {"id": "reviewer-new", "kind": "reviewer",
                    "path": str(self.rundir / "jobs")}
        with self.drifting_path(), \
                patch.object(orc, "call_model",
                             return_value=(dict(REVIEWER_REPORT), fake_job)) as model:
            self.stage("review")
        self.assertEqual(model.call_count, 1)
        self.assertEqual(self.state_file()["review"]["summary"],
                         "fresh independent review")

    # -- batch history and concurrency -----------------------------------
    def test_multibatch_recovery_preserves_position_and_accepted_history(self):
        plan = make_plan(2)
        self.prepare(plan, phase="review", review=False)
        state = self.state_file()
        state["batch_index"] = 1
        evidence = orc.run_checks(self.rundir, state, self.cfg,
                                  self.project, plan["batches"][1])
        state["verification"] = {
            "path": evidence["path"], "passed": True,
            "candidate_hash": evidence["after_hash"],
            "evidence_version": orc.VERIFICATION_EVIDENCE_VERSION}
        accepted = [{"index": 0, "verdict": self.verdict(),
                     "verification": copy.deepcopy(state["verification"])}]
        state["accepted_batches"] = copy.deepcopy(accepted)
        state["accepted_history"] = [{"index": 0, "plan_version": state["plan_version"]}]
        state["check_progress"] = None
        orc.save(self.rundir, state)
        accepted_path = Path(state["accepted_batches"][0]["verification"]["path"])
        accepted_bytes = accepted_path.read_bytes()
        with self.drifting_path(), \
                patch.object(orc, "call_model",
                             side_effect=AssertionError("unexpected model")):
            self.stage("review")
        final = self.state_file()
        self.assertEqual(final["phase"], "verify")
        self.assertEqual(final["batch_index"], 1)
        self.assertEqual(final["accepted_batches"], accepted)
        self.assertEqual(final["accepted_history"],
                         [{"index": 0, "plan_version": final["plan_version"]}])
        self.assertEqual(accepted_path.read_bytes(), accepted_bytes)
        self.assertEqual(final["review_recovery"]["batch_index"], 1)

    def test_separate_process_stage_and_resume_contend_for_one_owner(self):
        self.prepare(make_plan(1), phase="review", review=False)
        holder = self.root / "supervisor-held"
        orchestrator = str(Path(orc.__file__).resolve())
        code = (
            "import importlib.util,pathlib,sys,time\n"
            "s=importlib.util.spec_from_file_location('h',sys.argv[1])\n"
            "o=importlib.util.module_from_spec(s);sys.modules[s.name]=o;s.loader.exec_module(o)\n"
            "with o.exclusive(pathlib.Path(sys.argv[2])):\n"
            "    pathlib.Path(sys.argv[3]).write_text('held')\n"
            "    time.sleep(3)\n")
        proc = subprocess.Popen(
            [sys.executable, "-c", code, orchestrator, str(self.rundir),
             str(holder)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        deadline = time.monotonic() + 10
        while not holder.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(holder.exists())
        env = dict(os.environ)
        try:
            empty = self.root / "empty-path-entry"
            empty.mkdir(exist_ok=True)
            env["PATH"] = str(empty) + os.pathsep + env["PATH"]
            child_code = (
                "import importlib.util,sys\n"
                "s=importlib.util.spec_from_file_location('h',sys.argv[1])\n"
                "o=importlib.util.module_from_spec(s);sys.modules[s.name]=o;s.loader.exec_module(o)\n"
                "o.stage_run(sys.argv[2])\n")
            stage_child = subprocess.run(
                [sys.executable, "-c", child_code, orchestrator, self.state["id"]],
                capture_output=True, text=True, env=env, timeout=30)
            resume_code = (
                "import importlib.util,pathlib,sys\n"
                "s=importlib.util.spec_from_file_location('h',sys.argv[1])\n"
                "o=importlib.util.module_from_spec(s);sys.modules[s.name]=o;s.loader.exec_module(o)\n"
                "folder=pathlib.Path(sys.argv[2])\n"
                "with o.exclusive(folder):\n"
                "    o.modify_locked(folder,o.load(sys.argv[3])[1],sys.argv[3],'resume')\n")
            resume_child = subprocess.run(
                [sys.executable, "-c", resume_code, orchestrator,
                 str(self.rundir), self.state["id"]],
                capture_output=True, text=True, env=env, timeout=30)
            self.assertNotEqual(stage_child.returncode, 0)
            self.assertIn("Another supervisor", stage_child.stderr)
            self.assertNotEqual(resume_child.returncode, 0)
            self.assertIn("Another supervisor", resume_child.stderr)
            self.assertEqual(self.state_file()["phase"], "review")
            self.assertFalse(self.state_file().get("review_recoveries"))
        finally:
            proc.send_signal(signal.SIGKILL)
            proc.communicate(timeout=10)
        # After serialization is released exactly one recovery occurs.
        with self.drifting_path(), \
                patch.object(orc, "call_model",
                             side_effect=AssertionError("unexpected model")):
            self.stage("review")
        self.assertEqual(self.state_file()["phase"], "verify")
        self.assertEqual(len(self.state_file()["review_recoveries"]), 1)


if __name__ == "__main__":
    unittest.main()
