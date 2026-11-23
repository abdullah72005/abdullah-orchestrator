"""One disposable v1.2.1 lifecycle across all five corrections.

Fixture workers stand in for model CLIs.  Worktrees, patches, supervisor checks,
the canonical checkout and durable evidence are real.  The test deliberately
combines parallel recovery, scoped authorization, progress, fresh review and
final evidence reuse rather than exercising each in isolation.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

import test_orchestrator as baseline

orc = baseline.orc


def writer(writer_id):
    return {"id": writer_id, "goal": f"Implement {writer_id}",
            "paths": [f"{writer_id}.py"], "components": [],
            "completion_criteria": f"{writer_id} slice complete",
            "role": "implementer"}


def report(summary):
    return {"contract_version": 2, "status": "complete", "summary": summary,
            "files": [], "tests": [], "evidence": [summary],
            "unknowns": [], "blocker": ""}


def blocked(summary):
    return {"contract_version": 2, "status": "blocked", "summary": summary,
            "files": [], "tests": [], "evidence": [summary],
            "unknowns": [], "blocker": summary}


class CombinedLifecycleTests(unittest.TestCase):
    setUp = baseline.ControlTests.setUp
    tearDown = baseline.ControlTests.tearDown

    def stage(self):
        payload = orc.stage_run(self.state["id"])
        self.state = orc.load(self.state["id"])[1]
        return payload

    def test_combined_lifecycle(self):
        counter = self.root / "combined.count"
        code = ("import pathlib; "
                f"p = pathlib.Path({str(counter)!r}); "
                "n = int(p.read_text()) if p.exists() else 0; "
                "p.write_text(str(n + 1))")
        plan = {"contract_version": 2, "status": "complete", "summary": "plan",
                "invariants": ["Keep behavior"],
                "batches": [{"title": "feature", "goal": "change app",
                             "acceptance": ["works"],
                             "checks": [[sys.executable, "-c", code]],
                             "risk": "ordinary", "verification_purpose": None,
                             "repeat_checks": None,
                             "writers": [writer("a"), writer("b")]}],
                "blocker": "", "required_exploration": {
                    "job_id": "", "scope_satisfied": True}}
        route = {"provider": "opencode", "model": "opencode-go/x", "effort": "low",
                 "billing": "api", "routing_fingerprint": "c" * 64}
        grant = {"id": "combined-grant", "role": "implementer",
                 "route_sha256": orc.route_authorization_sha(route),
                 "role_generation": 0, "used": 0, "max_dispatches": 1}
        self.state.update({
            "status": "awaiting_plan_approval", "phase": "implement",
            "plan": plan, "plan_version": orc.content_hash(plan),
            "plan_revision": 1, "plan_approval": True, "batch_index": 0,
            "single_batch_fast_path": True,
            "plan_authority": {"plan_version": orc.content_hash(plan),
                               "plan_revision": 1, "amendment_epoch": 0,
                               "authority_epoch": 0, "approved": False},
            "model_routes": {"implementer": route},
            "route_authorizations": [grant],
            "parallel_permission": {"max_writers": 2, "enabled": True}})
        orc.save(self.rundir, self.state)

        # Plan approval records consent but stops because the known grant cannot
        # cover the admitted writer set.
        launched = orc.modify_locked(self.rundir, self.state, self.state["id"],
                                     "approve-plan")
        self.assertFalse(launched)
        self.assertEqual(self.state["status"], "blocked")
        self.assertIn("parallel_grant", self.state["pause_reason"])
        self.assertEqual(self.state["plan_authority"]["approved"], True)
        # Correcting the scoped grant makes resume possible without recreating
        # the run or any completed work.
        grant["max_dispatches"] = 3
        orc.save(self.rundir, self.state)
        self.assertTrue(orc.modify_locked(self.rundir, self.state,
                                          self.state["id"], "resume"))
        self.assertEqual(self.state["status"], "running")

        starts = []
        reviewer_calls = []

        def fake_model(run_dir, state, cfg, role, kind, prompt, project, **kwargs):
            project = Path(project)
            if role == "reviewer":
                reviewer_calls.append(str(project))
                self.assertEqual((project / "a.py").read_text(), "a = 1\n")
                self.assertEqual((project / "b.py").read_text(), "b = 2\n")
                return ({"contract_version": 2, "status": "complete",
                         "summary": "reviewed combined source",
                         "files": ["a.py", "b.py"], "tests": [],
                         "evidence": ["a.py", "b.py"], "unknowns": [],
                         "blocker": "", "findings": []},
                        {"id": f"review-{len(reviewer_calls)}",
                         "role": "reviewer", "kind": "reviewer",
                         "status": "complete",
                         "path": str(Path(run_dir) / "jobs" / "reviewer-1")})
            writer_id = kwargs.get("assignment")
            starts.append(writer_id)
            if writer_id == "a":
                (project / "a.py").write_text("a = 1\n")
                return report("a finished"), {
                    "id": "job-a", "role": "implementer", "kind": "implementer"}
            if not self.state.get("resolved_parallel_blocks"):
                (project / "b.py").write_text("b = 'partial'\n")
                return blocked("shared contract needs a decision"), {
                    "id": "job-b-partial", "role": "implementer",
                    "kind": "implementer"}
            (project / "b.py").write_text("b = 2\n")
            return report("b finished"), {
                "id": "job-b", "role": "implementer", "kind": "implementer"}

        with patch.object(orc, "call_model", side_effect=fake_model):
            first = self.stage()
            self.assertEqual(self.state["status"], "blocked")
            self.assertEqual(starts, ["a", "b"], self.state.get("parallel_resolution"))
            self.assertFalse((self.project / "a.py").exists())
            self.assertFalse((self.project / "b.py").exists())
            replay = first["progress"]["replay"]
            self.assertTrue(any("writer a" in item for item in replay), replay)

        self.assertTrue(orc.modify_locked(self.rundir, self.state,
                                          self.state["id"], "resume"))
        with patch.object(orc, "call_model", side_effect=fake_model):
            self.stage()  # resume only the blocked writer; integrate both
        self.assertEqual(self.state["phase"], "verify")
        self.assertEqual(starts, ["a", "b", "b"])
        self.assertEqual((self.project / "b.py").read_text(), "b = 2\n")

        with patch.object(orc, "call_model", side_effect=fake_model):
            self.stage()  # supervisor verification executes the approved check once
        self.assertEqual(self.state["phase"], "review")
        self.assertEqual(int(counter.read_text()), 1)

        with patch.object(orc, "call_model", side_effect=fake_model):
            self.stage()  # one fresh read-only Reviewer on the combined source
        self.assertEqual(self.state["phase"], "accept")
        self.assertEqual(len(reviewer_calls), 1)

        def approve(_run_dir, state, _cfg, _kind, extra=None, **kwargs):
            references = ([state["single_batch_verification"],
                           state["verification"]]
                          if state.get("single_batch_verification")
                          else [state["verification"]])
            state["decision_binding"] = orc.make_decision_binding(
                state, self.project, references)
            return {"contract_version": 2, "verdict": "approved",
                    "reason": "combined candidate inspected",
                    "inspected": ["a.py", "b.py"], "correction": "",
                    "dismissed_findings": []}

        with patch.object(orc, "strong_call", side_effect=approve):
            self.stage()  # final acceptance reuses the verified evidence
        self.assertEqual(self.state["status"], "complete")
        self.assertEqual(int(counter.read_text()), 1,
                         "final acceptance re-ran the formal suite")
        self.assertEqual(self.state["final_acceptance"]["mode"],
                         "reused_supervisor_verification")
        self.assertEqual(self.state["parallel_integration"]["phase"], "complete")
        self.assertEqual(sorted(self.state["parallel_writers"]["lanes"]),
                         ["a", "b"])


if __name__ == "__main__":
    unittest.main()
