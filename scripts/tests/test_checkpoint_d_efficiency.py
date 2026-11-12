"""Checkpoint D: amendments, risk policy, usage and bounded context."""
from __future__ import annotations

import copy
import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import test_orchestrator as baseline

orc = baseline.orc


class CheckpointDEfficiency(unittest.TestCase):
    def setUp(self):
        baseline.ControlTests.setUp(self)
        self.batch = {"title": "one", "goal": "change", "acceptance": ["works"],
                      "checks": [["true"]], "risk": "ordinary"}

    def _with_plan(self):
        plan = {"contract_version": 2, "status": "complete", "summary": "plan",
                "invariants": ["keep working"], "batches": [copy.deepcopy(self.batch)],
                "blocker": ""}
        self.state.update(plan=plan, plan_version=orc.content_hash(plan),
                          plan_revision=1, batch_index=0)
        orc.save(self.rundir, self.state)
        return plan

    def test_material_amendment_versions_plan_and_invalidates_accepted_work(self):
        plan = self._with_plan()
        self.state.update(phase="accept", status="paused",
                          accepted_batches=[{"index": 0, "title": "one"}],
                          verification={"path": "/tmp/old", "passed": True},
                          review={"status": "complete", "findings": []})
        orc.save(self.rundir, self.state)
        result = orc.amend_run("test-run00", "Change the required behavior",
                              architect_review=True)
        self.assertTrue(result["persisted"])
        saved = orc.read_json(self.rundir / "state.json")
        self.assertEqual(saved["amendments"][-1]["kind"], "material")
        self.assertEqual(saved["phase"], "diagnose")
        self.assertEqual(saved["accepted_batches"], [])
        self.assertEqual(saved["accepted_history"][0]["invalidated_by"],
                         saved["amendments"][-1]["id"])
        self.assertEqual(saved["plan_history"][-1]["plan_version"], plan and orc.content_hash(plan))
        self.assertIsNone(saved["verification"])
        self.assertIsNone(saved["review"])
        diagnosed = {"verdict": "changes_required", "reason": "new requirement",
                     "inspected": ["app.py"], "correction": "replan"}
        new_plan = {"contract_version": 2, "status": "complete", "summary": "new",
                    "invariants": ["new invariant"],
                    "batches": [{"title": "new", "goal": "new", "acceptance": ["new"],
                                 "checks": [["true"]], "risk": "ordinary"}],
                    "blocker": ""}
        with patch.object(orc, "strong_call", side_effect=[diagnosed, new_plan]):
            orc.resume_run("test-run00")
            orc.advance(self.rundir, orc.read_json(self.rundir / "state.json"), self.cfg)
            state = orc.read_json(self.rundir / "state.json")
            self.assertEqual(state["phase"], "plan")
            self.assertIsNone(state["plan"])
            orc.advance(self.rundir, state, self.cfg)
        final = orc.read_json(self.rundir / "state.json")
        self.assertEqual(final["phase"], "implement")
        self.assertEqual(final["plan_revision"], 2)
        self.assertEqual(final["batch_index"], 0)
        self.assertNotEqual(final["plan_version"], orc.content_hash(plan))

    def test_minor_amendment_stays_implementation_correction(self):
        plan = self._with_plan()
        self.state.update(phase="implement", status="paused")
        orc.save(self.rundir, self.state)
        orc.amend_run("test-run00", "Fix the typo", architect_review=False)
        saved = orc.read_json(self.rundir / "state.json")
        self.assertEqual(saved["amendments"][-1]["kind"], "minor")
        self.assertEqual(saved["phase"], "implement")
        self.assertEqual(saved["plan_version"], orc.content_hash(plan))
        self.assertIn("Fix the typo", saved["correction"])

    def test_mechanical_batch_skips_independent_review(self):
        self._with_plan()
        self.state["plan"]["batches"][0]["risk"] = "mechanical"
        self.state.update(phase="verify")
        orc.save(self.rundir, self.state)
        evidence = {"passed": True, "source_unchanged": True, "commands": []}
        with patch.object(orc, "run_checks", return_value=evidence), \
                patch.object(orc, "call_model") as model:
            orc.advance(self.rundir, self.state, self.cfg)
        model.assert_not_called()
        self.assertEqual(self.state["phase"], "accept")
        self.assertEqual(self.state["review"]["status"], "complete")

    def test_high_risk_requires_two_checks(self):
        self._with_plan()
        self.state["plan"]["batches"][0].update(risk="high", checks=[["true"]])
        self.state.update(phase="verify")
        orc.save(self.rundir, self.state)
        evidence = {"passed": True, "source_unchanged": True, "commands": []}
        with patch.object(orc, "run_checks", return_value=evidence), \
                patch.object(orc, "reviewer_verification_package") as package:
            orc.advance(self.rundir, self.state, self.cfg)
        package.assert_not_called()
        self.assertEqual(self.state["status"], "blocked")
        self.assertIn("at least 2", self.state["pause_reason"])

    def test_risk_policy_is_configurable_and_unknown_fails(self):
        self.assertTrue(orc.risk_policy("ordinary", self.cfg)["independent_review"])
        cfg = copy.deepcopy(self.cfg)
        cfg.setdefault("risk_policy", {})["mechanical"] = {
            "independent_review": True, "minimum_checks": 2}
        policy = orc.risk_policy("mechanical", cfg)
        self.assertTrue(policy["independent_review"])
        self.assertEqual(policy["minimum_checks"], 2)
        with self.assertRaisesRegex(ValueError, "Unknown risk"):
            orc.risk_policy("extreme", cfg)

    def test_usage_report_preserves_unavailable_fields(self):
        state = copy.deepcopy(self.state)
        job = {"role": "explorer", "route": {"billing": "go"},
               "reported_usage": {"tokens": 120, "cache_tokens": 20, "cost": None}}
        orc.record_usage(state, job, "complete", 1.5)
        orc.record_usage(state, job, "complete", 1.5)
        usage = orc.usage_report(state)
        self.assertEqual(usage["cheap_calls"], 1)
        self.assertEqual(usage["strong_calls"], 0)
        self.assertEqual(usage["reported_tokens"], 120)
        self.assertEqual(usage["reported_cache_tokens"], 20)
        self.assertEqual(usage["cost_status"], "unavailable")
        self.assertIsNone(usage["reported_provider_cost"])
        self.assertEqual(usage["billing"]["go"], 1)
        self.assertIn("not inferred", usage["note"])
        failed = {"role": "architect", "route": {"billing": "subscription"}}
        orc.record_usage(state, failed, "failed", 2)
        self.assertEqual(state["usage"]["strong_calls"], 1)
        self.assertEqual(state["usage"]["failed_attempts"], 1)

    def test_context_handoff_is_bounded(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["limits"]["max_context_chars"] = 300
        with patch.object(orc, "config", return_value=cfg):
            prompt = orc.report_prompt("plan", {"blob": "x" * 5000})
        self.assertIn("context truncated", prompt)
        self.assertLess(len(prompt), 20000)

    def test_git_checkpointing_is_not_automatic(self):
        source = Path(orc.__file__).read_text(encoding="utf-8")
        self.assertNotIn("git\", \"commit", source)
        self.assertNotIn("git commit", source)
        self.assertNotIn("--only", source)


if __name__ == "__main__":
    unittest.main()
