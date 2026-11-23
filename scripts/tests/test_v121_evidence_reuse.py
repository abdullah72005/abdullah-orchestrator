"""v1.2.1 supervisor evidence reuse for final acceptance.

Real supervisor verification records are produced by ``run_checks``.  The
reuse decision never trusts worker prose, a path outside the run directory or a
record without a supervisor log digest.  Invocation counts come from a real
check executable, so a skipped execution is observable rather than asserted.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import test_orchestrator as baseline

orc = baseline.orc


def verdict(value="approved"):
    return {"contract_version": 2, "verdict": value, "reason": "inspected",
            "inspected": ["app.py"], "correction": "",
            "dismissed_findings": []}


def batch(title, checks, **extra):
    return {"title": title, "goal": "change app", "acceptance": ["works"],
            "checks": checks, "risk": "ordinary", **extra}


class EvidenceReuseTests(unittest.TestCase):
    setUp = baseline.ControlTests.setUp
    tearDown = baseline.ControlTests.tearDown

    def counting_check(self, name):
        counter = self.root / f"{name}.count"
        code = ("import pathlib; "
                f"p = pathlib.Path({str(counter)!r}); "
                "n = int(p.read_text()) if p.exists() else 0; "
                "p.write_text(str(n + 1))")
        return [sys.executable, "-c", code], counter

    def invocations(self, counter):
        return int(counter.read_text()) if counter.exists() else 0

    def plan(self, batches, batch_index=0):
        return {"contract_version": 2, "status": "complete", "summary": "plan",
                "invariants": ["Keep behavior"], "batches": batches,
                "blocker": "",
                "required_exploration": {"job_id": "", "scope_satisfied": True}}

    def prepare(self, plan, phase="accept", batch_index=0, review=True):
        self.state.update(
            phase=phase, plan=copy.deepcopy(plan),
            plan_version=orc.content_hash(plan), plan_revision=1,
            batch_index=batch_index, corrections=0, correction="",
            single_batch_fast_path=len(plan["batches"]) == 1,
            review=({"status": "complete", "findings": [], "summary": "reviewed",
                     "files": [], "tests": [], "evidence": [], "unknowns": [],
                     "blocker": ""} if review else None))
        orc.save(self.rundir, self.state)

    def verify(self, batch_value, *, title=None, final=False, batch_index=None):
        if batch_index is not None:
            self.state["batch_index"] = batch_index
        evidence = orc.run_checks(
            self.rundir, self.state, self.cfg, self.project,
            {"title": title or batch_value["title"], "checks": batch_value["checks"]},
            final=final)
        self.state["check_progress"] = None
        reference = {"path": evidence["path"], "passed": evidence["passed"],
                     "candidate_hash": evidence["after_hash"],
                     "evidence_version": evidence["evidence_version"],
                     "record_sha256": orc._sha256_file(Path(evidence["path"]))}
        self.state["verification"] = reference
        orc.save(self.rundir, self.state)
        return reference, evidence

    def accept_with(self, extra=None):
        def approve(_run_dir, state, _cfg, _kind, extra=None, **kwargs):
            references = ([state["single_batch_verification"], state["verification"]]
                          if state.get("single_batch_verification")
                          else [state["verification"]])
            state["decision_binding"] = orc.make_decision_binding(
                state, self.project, references)
            return verdict()
        return patch.object(orc, "strong_call", side_effect=approve)

    def test_single_batch_accept_reuses_verified_source_once(self):
        check, counter = self.counting_check("single")
        plan = self.plan([batch("one", [check])])
        self.prepare(plan)
        reference, _ = self.verify(plan["batches"][0])
        self.assertEqual(self.invocations(counter), 1)
        with self.accept_with() as strong:
            orc.advance(self.rundir, self.state, self.cfg)
        strong.assert_called_once()
        self.assertEqual(self.invocations(counter), 1, "final gate re-ran the suite")
        self.assertEqual(self.state["status"], "complete")
        final = self.state["final_evidence"]
        self.assertTrue(final["final"])
        self.assertTrue(final["reuse"])
        self.assertEqual(final["reuse"]["sources"][0]["sha256"],
                         orc._sha256_file(Path(reference["path"])))
        self.assertEqual(len(self.state["decision_binding"]["verification"]), 2)
        self.assertEqual(self.state["final_acceptance"]["mode"],
                         "reused_supervisor_verification")

    def test_source_change_after_verify_is_never_silently_accepted(self):
        check, counter = self.counting_check("changed")
        plan = self.plan([batch("one", [check])])
        self.prepare(plan)
        self.verify(plan["batches"][0])
        (self.project / "app.py").write_text("value = 2\n")
        with patch.object(orc, "strong_call") as strong:
            orc.advance(self.rundir, self.state, self.cfg)
        strong.assert_not_called()
        self.assertEqual(self.state["phase"], "verify")
        self.assertIsNone(self.state["verification"])
        self.assertEqual(self.invocations(counter), 1)

    def test_tampered_command_log_forces_a_fresh_execution(self):
        check, counter = self.counting_check("tampered-log")
        plan = self.plan([batch("one", [check])])
        self.prepare(plan)
        reference, evidence = self.verify(plan["batches"][0])
        log = Path(evidence["commands"][0]["log"])
        log.write_text(log.read_text() + "tampered\n")
        with self.accept_with() as strong:
            orc.advance(self.rundir, self.state, self.cfg)
        strong.assert_called_once()
        self.assertEqual(self.invocations(counter), 2)
        self.assertEqual(self.state["final_acceptance"]["mode"], "executed")
        # The formal batch record is also part of the Architect decision. Its
        # changed log cannot be laundered by the fresh final repeat.
        self.assertNotEqual(self.state["status"], "complete")
        self.assertEqual(self.state["phase"], "verify")
        self.assertIsNone(self.state["verification"])
        self.assertIn("changed", self.state["pause_reason"])

    def test_repeat_requirement_forces_another_execution(self):
        check, counter = self.counting_check("repeat")
        plan = self.plan([batch("one", [check], repeat_checks=True)])
        self.prepare(plan)
        self.verify(plan["batches"][0])
        with self.accept_with():
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(self.invocations(counter), 2)
        self.assertEqual(self.state["final_acceptance"]["mode"], "executed")
        self.assertTrue(any("repeat" in reason
                            for reason in self.state["final_acceptance"]["reasons"]))

    def test_tampered_record_bytes_rewinds_to_verification(self):
        check, counter = self.counting_check("record")
        plan = self.plan([batch("one", [check])])
        self.prepare(plan)
        reference, _ = self.verify(plan["batches"][0])
        path = Path(reference["path"])
        path.write_text(path.read_text() + "\n")
        with patch.object(orc, "strong_call") as strong:
            orc.advance(self.rundir, self.state, self.cfg)
        strong.assert_not_called()
        self.assertEqual(self.state["phase"], "verify")
        self.assertIsNone(self.state["verification"])
        self.assertEqual(self.invocations(counter), 1)

    def test_correction_cycle_reuses_the_latest_verified_record(self):
        check, counter = self.counting_check("correction")
        plan = self.plan([batch("one", [check])])
        self.prepare(plan)
        self.verify(plan["batches"][0])
        # A bounded correction changes source, then the formal verify stage runs
        # again.  Acceptance must reuse the newest record, not the superseded one.
        (self.project / "app.py").write_text("value = 3\n")
        self.state["verification"] = None
        self.verify(plan["batches"][0])
        self.assertEqual(self.invocations(counter), 2)
        with self.accept_with():
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(self.invocations(counter), 2)
        self.assertEqual(self.state["status"], "complete")

    def test_integration_reuses_per_batch_records(self):
        first, first_counter = self.counting_check("multi-first")
        second, second_counter = self.counting_check("multi-second")
        plan = self.plan([batch("one", [first]), batch("two", [second])])
        self.prepare(plan, batch_index=0)
        one_ref, _ = self.verify(plan["batches"][0], title="one", batch_index=0)
        self.state["verification"] = None
        two_ref, _ = self.verify(plan["batches"][1], title="two", batch_index=1)
        self.state.update(phase="integrate", batch_index=2,
                          verification=None, single_batch_fast_path=False,
                          accepted_batches=[
                              {"index": 0, "verification": copy.deepcopy(one_ref)},
                              {"index": 1, "verification": copy.deepcopy(two_ref)}])
        orc.save(self.rundir, self.state)
        with self.accept_with():
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(self.state["status"], "complete")
        self.assertEqual(self.invocations(first_counter), 1)
        self.assertEqual(self.invocations(second_counter), 1)
        reuse = self.state["final_evidence"]["reuse"]
        self.assertEqual(len(reuse["sources"]), 2)
        self.assertEqual(self.state["final_acceptance"]["mode"],
                         "reused_supervisor_verification")

    def test_integration_extra_check_not_covered_executes_all_checks(self):
        first, first_counter = self.counting_check("extra-first")
        extra, extra_counter = self.counting_check("extra-new")
        plan = self.plan([batch("one", [first]), batch("two", [extra])])
        self.prepare(plan, batch_index=0)
        one_ref, _ = self.verify(plan["batches"][0], title="one", batch_index=0)
        self.state["verification"] = None
        self.state.update(phase="integrate", batch_index=2,
                          verification=None, single_batch_fast_path=False,
                          accepted_batches=[{"index": 0,
                                             "verification": copy.deepcopy(one_ref)}])
        orc.save(self.rundir, self.state)
        with self.accept_with():
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(self.state["status"], "complete")
        # The missing scope is covered by executing the complete combined suite.
        self.assertEqual(self.invocations(first_counter), 2)
        self.assertEqual(self.invocations(extra_counter), 1)
        self.assertEqual(self.state["final_acceptance"]["mode"], "executed")
        self.assertTrue(any("not covered" in reason
                            for reason in self.state["final_acceptance"]["reasons"]))


    def test_log_change_during_strong_decision_cannot_complete(self):
        check, counter = self.counting_check("decision-log")
        plan = self.plan([batch("one", [check])])
        self.prepare(plan)
        reference, evidence = self.verify(plan["batches"][0])
        log = Path(evidence["commands"][0]["log"])

        def approve(_run_dir, state, _cfg, _kind, extra=None, **kwargs):
            log.write_text(log.read_text() + "changed during decision\n")
            references = ([state["single_batch_verification"], state["verification"]]
                          if state.get("single_batch_verification")
                          else [state["verification"]])
            state["decision_binding"] = orc.make_decision_binding(
                state, self.project, references)
            return verdict()

        with patch.object(orc, "strong_call", side_effect=approve):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(self.state["status"], "running")
        self.assertEqual(self.state["phase"], "verify")
        self.assertIsNone(self.state["verification"])
        self.assertIn("changed", self.state["pause_reason"])
        self.assertEqual(self.invocations(counter), 1,
                         "stale evidence was executed instead of rewound")
        self.assertEqual(self.state["accepted_batches"], [])

    def test_removed_log_is_detected_and_forces_one_fresh_execution(self):
        check, counter = self.counting_check("removed-log")
        plan = self.plan([batch("one", [check])])
        self.prepare(plan)
        _reference, evidence = self.verify(plan["batches"][0])
        Path(evidence["commands"][0]["log"]).unlink()
        with self.accept_with() as strong:
            orc.advance(self.rundir, self.state, self.cfg)
        strong.assert_called_once()
        self.assertEqual(self.invocations(counter), 2)
        self.assertEqual(self.state["final_acceptance"]["mode"], "executed")
        self.assertNotEqual(self.state["status"], "complete")
        self.assertEqual(self.state["phase"], "verify")
        self.assertIn("missing", self.state["pause_reason"])

    def test_changed_formal_log_is_refused_before_reviewer_admission(self):
        check, counter = self.counting_check("review-log")
        plan = self.plan([batch("one", [check])])
        self.prepare(plan, phase="review", review=False)
        _reference, evidence = self.verify(plan["batches"][0])
        log = Path(evidence["commands"][0]["log"])
        log.write_text(log.read_text() + "changed before review\n")
        with patch.object(orc, "call_model") as model:
            orc.advance(self.rundir, self.state, self.cfg)
        model.assert_not_called()
        self.assertIn(self.state["phase"], {"review", "verify"})
        self.assertEqual(self.state["status"], "blocked")
        self.assertIn("log", (self.state.get("pause_reason") or "").lower())
        self.assertEqual(self.invocations(counter), 1)

    def test_repeat_log_change_during_final_decision_cannot_complete(self):
        check, counter = self.counting_check("repeat-decision-log")
        plan = self.plan([batch("one", [check], repeat_checks=True)])
        self.prepare(plan)
        _reference, evidence = self.verify(plan["batches"][0])
        log = Path(evidence["commands"][0]["log"])

        def approve(_run_dir, state, _cfg, _kind, extra=None, **kwargs):
            log.write_text(log.read_text() + "changed during repeat decision\n")
            references = ([state["single_batch_verification"],
                           state["verification"]]
                          if state.get("single_batch_verification")
                          else [state["verification"]])
            state["decision_binding"] = orc.make_decision_binding(
                state, self.project, references)
            return verdict()

        with patch.object(orc, "strong_call", side_effect=approve):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(self.invocations(counter), 2)
        self.assertEqual(self.state["final_acceptance"]["mode"], "executed")
        self.assertNotEqual(self.state["status"], "complete")
        self.assertEqual(self.state["phase"], "verify")
        self.assertIn("changed", self.state["pause_reason"])

    def test_derived_reuse_record_revalidates_its_original_records(self):
        check, _counter = self.counting_check("derived-source")
        plan = self.plan([batch("one", [check])])
        self.prepare(plan)
        reference, _evidence = self.verify(plan["batches"][0])
        with self.accept_with():
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(self.state["status"], "complete")
        final = self.state["final_evidence"]
        self.assertTrue(final["reuse"])
        source = Path(final["reuse"]["sources"][0]["path"])
        # Replace the bound source record with a different valid record. The
        # derived record must not keep accepting it by path alone.
        replacement = orc.read_json(source)
        replacement["finished_at"] = "replaced"
        orc.atomic_json(source, replacement)
        assessment = orc.verification_reference_assessment(
            self.rundir, self.state, self.cfg, self.project,
            orc.source_snapshot(self.project), self.state["verification"],
            required=[check], expected_batch_index=0)
        self.assertTrue(assessment["reasons"], assessment)
        self.assertTrue(any("changed" in reason.lower()
                            for reason in assessment["reasons"]),
                        assessment["reasons"])

    def test_multi_batch_repeat_requirement_executes_at_integration(self):
        first, first_counter = self.counting_check("repeat-first")
        second, second_counter = self.counting_check("repeat-second")
        plan = self.plan([batch("one", [first]),
                          batch("two", [second], repeat_checks=True)])
        self.prepare(plan, batch_index=0)
        one_ref, _ = self.verify(plan["batches"][0], title="one", batch_index=0)
        self.state["verification"] = None
        two_ref, _ = self.verify(plan["batches"][1], title="two", batch_index=1)
        self.state.update(phase="integrate", batch_index=2,
                          verification=None, single_batch_fast_path=False,
                          accepted_batches=[
                              {"index": 0, "verification": copy.deepcopy(one_ref)},
                              {"index": 1, "verification": copy.deepcopy(two_ref)}])
        orc.save(self.rundir, self.state)
        with self.accept_with():
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(self.state["status"], "complete")
        self.assertEqual(self.state["final_acceptance"]["mode"], "executed")
        self.assertTrue(any("repeat" in reason
                            for reason in self.state["final_acceptance"]["reasons"]))
        self.assertEqual(self.invocations(first_counter), 2)
        self.assertEqual(self.invocations(second_counter), 2)


if __name__ == "__main__":
    unittest.main()
