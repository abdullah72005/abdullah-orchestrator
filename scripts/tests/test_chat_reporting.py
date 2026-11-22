"""Focused regressions for informative chat reporting.

Covers the bounded plan view, material-first finding previews, the distinction
between a completed Implementer and supervisor-verified checks, canonical
verdicts, and the opt-in Architect consultation path. No model calls.
"""
from __future__ import annotations

import json
from unittest.mock import patch

from test_orchestrator import ControlTests, orc


def plan_report(marker="Plan", *, batches=1, invariants=("Keep behavior",)):
    return {
        "contract_version": 2,
        "status": "complete",
        "summary": f"{marker} summary",
        "invariants": list(invariants),
        "batches": [{
            "title": f"Batch {index + 1}",
            "goal": f"Goal {index + 1}",
            "acceptance": [f"Acceptance {index + 1}.{item}" for item in range(6)],
            "checks": [["python3", "-m", "unittest", f"SECRET-ARGV-{index}"]],
            "risk": "ordinary",
            "verification_purpose": f"Purpose {index + 1}",
        } for index in range(batches)],
        "blocker": "",
        "required_exploration": {"job_id": "", "scope_satisfied": False},
    }


def approved_authority(version="plan-version-1", revision=1):
    return {
        "plan_version": version,
        "plan_revision": revision,
        "amendment_epoch": 0,
        "authority_epoch": 0,
        "approved": True,
        "approval": {"plan_version": version, "plan_revision": revision,
                     "amendment_epoch": 0, "approved_at": "now"},
        "source": "architect_plan",
        "recorded_at": "now",
    }


class ChatReportingTests(ControlTests):
    def _save(self):
        orc.save(self.rundir, self.state)

    def test_status_and_plan_stage_expose_a_bounded_actual_plan(self):
        self.state.update({
            "plan": plan_report("Bounded", batches=10,
                                invariants=[f"Invariant {index}" for index in range(11)]),
            "plan_version": "bounded-version",
            "plan_revision": 3,
            "plan_authority": approved_authority("bounded-version", 3),
            "plan_approval": True,
            "status": "running",
            "phase": "implement",
        })
        self._save()

        status = orc.status_run("test-run00")
        view = status["plan_view"]
        self.assertTrue(view["available"])
        self.assertEqual(view["status"], "complete")
        self.assertEqual(view["revision"], 3)
        self.assertEqual(view["version"], "bounded-version")
        self.assertEqual(view["summary"], "Bounded summary")
        self.assertEqual(view["approval"]["status"], "approved")
        self.assertTrue(view["approval"]["required"])
        self.assertEqual(len(view["batches"]), orc.PLAN_VIEW_BATCH_LIMIT)
        self.assertEqual(view["batches_omitted_count"], 10 - orc.PLAN_VIEW_BATCH_LIMIT)
        self.assertEqual(len(view["invariants"]), orc.PLAN_VIEW_INVARIANT_LIMIT)
        self.assertEqual(view["invariants_omitted_count"],
                         11 - orc.PLAN_VIEW_INVARIANT_LIMIT)
        first = view["batches"][0]
        self.assertEqual(first["title"], "Batch 1")
        self.assertEqual(first["goal"], "Goal 1")
        self.assertEqual(first["risk"], "ordinary")
        self.assertEqual(first["verification_purpose"], "Purpose 1")
        self.assertEqual(len(first["acceptance"]), orc.PLAN_VIEW_ACCEPTANCE_LIMIT)
        self.assertEqual(first["acceptance_omitted_count"],
                         6 - orc.PLAN_VIEW_ACCEPTANCE_LIMIT)
        rendered = json.dumps(view)
        self.assertNotIn("SECRET-ARGV", rendered)
        self.assertNotIn("checks", first)
        self.assertEqual(view["detail"]["recap"],
                         "orchestrator_recap detail=developer")

        payload = orc.stage_payload(self.rundir, self.state, "plan", "architect",
                                    "Create plan", "Plan JSON", 1.25)
        self.assertEqual(payload["plan_view"]["revision"], 3)
        self.assertEqual(payload["report"]["summary"], "Bounded summary")
        self.assertNotIn("SECRET-ARGV", json.dumps(payload["plan_view"]))
        # The authoritative plan is untouched.
        self.assertEqual(len(self.state["plan"]["batches"]), 10)
        self.assertTrue(self.state["plan"]["batches"][0]["checks"])



    def test_material_findings_are_previewed_first_without_mutating_evidence(self):
        findings = [
            {"severity": "low", "confidence": "confirmed", "location": f"low-{index}",
             "claim": f"Low {index}", "evidence": "e", "disposition": "note"}
            for index in range(7)
        ]
        findings.extend([
            {"severity": "medium", "confidence": "confirmed", "location": "medium",
             "claim": "Medium", "evidence": "e", "disposition": "note"},
            {"severity": "high", "confidence": "confirmed", "location": "high",
             "claim": "High", "evidence": "e", "disposition": "fix"},
            {"severity": "critical", "confidence": "confirmed", "location": "critical",
             "claim": "Critical", "evidence": "e", "disposition": "fix"},
        ])
        original = list(findings)
        review = {"status": "complete", "summary": "Review done",
                  "findings": findings, "files": [], "tests": [], "evidence": ["app.py"],
                  "unknowns": [], "blocker": ""}
        preview = orc.compact_report(review)
        severities = [item["severity"] for item in preview["findings"]]
        self.assertEqual(severities[:3], ["critical", "high", "medium"])
        self.assertEqual(len(severities), 8)
        self.assertEqual(preview["findings_omitted_count"], 2)
        # Authoritative evidence keeps its original order and length.
        self.assertEqual(review["findings"], original)
        self.assertEqual(review["findings"][0]["severity"], "low")

        self.state.update({"review": review, "phase": "review", "status": "running"})
        orc.save(self.rundir, self.state)
        status = orc.status_run("test-run00")
        self.assertEqual(status["last_review"]["findings"][0]["severity"], "critical")
        self.assertEqual(status["last_review"]["findings_omitted_count"], 2)



    def test_completed_implementer_is_not_reported_as_verified_tests(self):
        self.state.update({
            "status": "running", "phase": "implement",
            "implementation": {
                "status": "complete", "summary": "Implemented the feature",
                "files": ["app.py"],
                "tests": ["python3 -m unittest (worker report)"],
                "evidence": ["app.py:1"], "unknowns": [], "blocker": ""},
            "verification": None,
        })
        orc.save(self.rundir, self.state)

        status = orc.status_run("test-run00")
        self.assertEqual(status["last_implementation"]["status"], "complete")
        self.assertIsNone(status["verification"])
        summary = orc.stage_summary(self.state, "implement")
        self.assertIn("test note(s)", summary)
        self.assertNotIn("checks passed", summary)

        quick = orc.recap_run("test-run00", "quick")
        self.assertIn("Verification: pending supervisor verification", quick["text"])
        developer = orc.recap_run("test-run00", "developer")
        self.assertIn("No supervisor verification commands are recorded.",
                      developer["text"])



    def test_blocked_plan_exposes_its_question_through_the_current_attempt(self):
        report = {
            "contract_version": 2,
            "status": "blocked",
            "summary": "The data-store choice changes the migration path.",
            "invariants": [],
            "batches": [],
            "blocker": "Should this use SQLite or Postgres?",
            "required_exploration": {"job_id": "", "scope_satisfied": False},
        }
        job_dir = self.rundir / "jobs" / "blocked-plan"
        job_dir.mkdir(parents=True)
        orc.atomic_json(job_dir / "report.json", report)
        self.state.update({
            "plan_approval": True,
            "plan": plan_report("STALE ACTIVE PLAN"),
            "plan_version": "old-version",
            "plan_history": [{
                "version": 0, "plan_version": "old-version",
                "plan": plan_report("STALE PROPOSAL"),
                "accepted_batches": [], "archived_at": "then"}],
        })
        orc.save(self.rundir, self.state)

        def fake_strong(_dir, state, _cfg, kind, *args, **kwargs):
            self.assertEqual(kind, "plan")
            state["completed_jobs"].append({
                "id": "blocked-plan", "kind": "plan", "path": str(job_dir)})
            return report

        with patch.object(orc, "strong_call", side_effect=fake_strong):
            orc.advance(self.rundir, self.state, self.cfg)

        self.assertEqual(self.state["status"], "blocked")
        self.assertEqual(self.state["pause_reason"],
                         "Should this use SQLite or Postgres?")
        status = orc.status_run("test-run00")
        view = status["plan_view"]
        self.assertFalse(view["available"])
        self.assertEqual(view["status"], "blocked")
        self.assertEqual(view["summary"],
                         "The data-store choice changes the migration path.")
        self.assertEqual(view["blocker"], "Should this use SQLite or Postgres?")
        self.assertTrue(view["approval"]["required"])
        self.assertEqual(view["detail"]["report"]["path"],
                         str(job_dir / "report.json"))
        self.assertEqual(view["detail"]["report"]["sha256"],
                         orc.content_hash(report))
        rendered = json.dumps(view)
        self.assertNotIn("STALE PROPOSAL", rendered)

        payload = orc.stage_payload(self.rundir, self.state, "plan", "architect",
                                    "Create plan", "Plan JSON", 1.0)
        self.assertEqual(payload["report"]["blocker"],
                         "Should this use SQLite or Postgres?")
        self.assertEqual(payload["plan_view"]["blocker"],
                         "Should this use SQLite or Postgres?")
        self.assertNotIn("STALE PROPOSAL", json.dumps(payload))

        # A changed report file no longer matches its attested digest, so the
        # recorded question remains the honest current reference.
        orc.atomic_json(job_dir / "report.json",
                        {**report, "summary": "Tampered rationale",
                         "blocker": "Tampered question"})
        changed = orc.status_run("test-run00")["plan_view"]
        self.assertEqual(changed["blocker"], "Should this use SQLite or Postgres?")
        self.assertEqual(changed["summary"],
                         "The data-store choice changes the migration path.")



    def test_default_plan_continues_without_consultation(self):
        captured = {}
        plan = plan_report("Default")

        def fake_model(_dir, _state, _cfg, role, kind, prompt, project, **kwargs):
            captured["request"] = prompt
            return plan, {"id": "plan-job"}

        with patch.object(orc, "call_model", side_effect=fake_model):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(self.state["status"], "running")
        self.assertEqual(self.state["phase"], "implement")
        context = captured["request"][orc.PROMPT_REQUEST_KEY]["context"]
        self.assertIn("do not pause for plan approval", context["instruction"])
        self.assertNotIn("trade-off", context["instruction"])
        view = orc.status_run("test-run00")["plan_view"]
        self.assertTrue(view["available"])
        self.assertEqual(view["approval"]["status"], "not_required")

    def test_explicit_opt_in_pauses_with_rationale_and_applies_approval_boundary(self):
        captured = {}
        plan = plan_report("Proposed direction",
                           invariants=("Preserve the public API",))

        def fake_model(_dir, _state, _cfg, role, kind, prompt, project, **kwargs):
            captured["request"] = prompt
            return plan, {"id": "plan-job"}

        self.state["plan_approval"] = True
        orc.save(self.rundir, self.state)
        with patch.object(orc, "call_model", side_effect=fake_model):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(self.state["status"], "awaiting_plan_approval")
        context = captured["request"][orc.PROMPT_REQUEST_KEY]["context"]
        self.assertIn("expressly requested plan approval", context["instruction"])
        self.assertIn("trade-off", context["instruction"])
        self.assertIn("blocker", context["instruction"])

        status = orc.status_run("test-run00")
        view = status["plan_view"]
        self.assertTrue(view["available"])
        self.assertTrue(view["approval"]["required"])
        self.assertEqual(view["approval"]["status"], "awaiting_user")
        self.assertFalse(view["approval"]["approved"])
        self.assertEqual(view["summary"], "Proposed direction summary")
        self.assertEqual(view["invariants"], ["Preserve the public API"])
        self.assertTrue(status["next_action"].startswith("operator: approve-plan"))

    def test_user_reply_is_carried_into_the_revised_plan(self):
        self.state.update({
            "plan": plan_report("Original"),
            "plan_version": "version-one",
            "plan_revision": 1,
            "plan_authority": approved_authority("version-one", 1),
            "status": "running",
            "phase": "implement",
        })
        orc.save(self.rundir, self.state)
        reply = "Use SQLite, not Postgres."
        amended = orc.amend_run("test-run00", reply, architect_review=True)
        self.assertTrue(amended["persisted"])
        self.assertEqual(amended["amendment"]["text"], reply)

        with patch.object(orc, "ensure_checkout_lease"):
            resumed = orc.resume_run("test-run00")
        self.assertEqual(resumed["status"], "running")
        folder, state = orc.load("test-run00")
        self.assertIsNone(state["plan"])

        captured = {}
        revised = plan_report("Revised")

        def fake_model(_dir, _state, _cfg, role, kind, prompt, project, **kwargs):
            captured["request"] = prompt
            return revised, {"id": "revised-plan-job"}

        with patch.object(orc, "call_model", side_effect=fake_model):
            orc.advance(folder, state, self.cfg)
        context = captured["request"][orc.PROMPT_REQUEST_KEY]["context"]
        self.assertEqual(context["requirements"]["amendments"][-1]["text"], reply)
        self.assertEqual(state["plan"]["summary"], "Revised summary")
        self.assertEqual(state["plan_revision"], 2)
        self.assertEqual(state["plan_history"][-1]["plan_version"], "version-one")
        self.assertEqual(state["plan_history"][-1]["plan"]["summary"],
                         "Original summary")

    def test_approval_of_an_earlier_plan_cannot_authorize_its_revision(self):
        self.state["plan_approval"] = True
        orc.save(self.rundir, self.state)
        first = plan_report("Version one")
        with patch.object(orc, "strong_call", return_value=first):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(self.state["status"], "awaiting_plan_approval")
        first_version = self.state["plan_version"]

        with patch.object(orc, "ensure_checkout_lease"):
            orc.modify_locked(self.rundir, self.state, "test-run00", "approve-plan")
        self.assertEqual(self.state["status"], "running")
        self.assertTrue(self.state["plan_authority"]["approved"])

        orc.amend_run("test-run00", "Prefer SQLite over Postgres.",
                      architect_review=True)
        with patch.object(orc, "ensure_checkout_lease"):
            orc.resume_run("test-run00")
        folder, state = orc.load("test-run00")
        second = plan_report("Version two")
        with patch.object(orc, "strong_call", return_value=second):
            orc.advance(folder, state, self.cfg)

        self.assertEqual(state["status"], "awaiting_plan_approval")
        self.assertNotEqual(state["plan_version"], first_version)
        self.assertFalse(state["plan_authority"]["approved"])
        self.assertNotIn("approved_plan_version", state["plan_authority"])
        status = orc.status_run("test-run00")
        self.assertEqual(status["plan_view"]["approval"]["status"], "awaiting_user")
        self.assertFalse(status["plan_view"]["approval"]["approved"])
        self.assertTrue(status["next_action"].startswith("operator: approve-plan"))
        refused = orc.stage_run("test-run00")
        self.assertFalse(refused["ok"])



    def test_status_and_accept_result_keep_the_verdict_and_reason(self):
        self.state.update({
            "architect_verdict": {
                "verdict": "changes_required",
                "reason": "The authorization bypass is still reachable.",
                "inspected": ["app.py"],
                "corrected": None,
                "correction": "Reject unauthenticated writes before storage."},
            "diagnosis_verdict": {
                "verdict": "changes_required",
                "reason": "The retry loop loses the idempotency key.",
                "inspected": ["worker.py"]},
            "status": "running",
            "phase": "implement",
        })
        orc.save(self.rundir, self.state)

        status = orc.status_run("test-run00")
        self.assertEqual(status["architect_verdict"]["verdict"],
                         "changes_required")
        self.assertEqual(status["architect_verdict"]["reason"],
                         "The authorization bypass is still reachable.")
        self.assertEqual(status["diagnosis_verdict"]["reason"],
                         "The retry loop loses the idempotency key.")

        payload = orc.stage_payload(self.rundir, self.state, "accept",
                                    "architect", "Accept batch", "Verdict", 2.0)
        self.assertEqual(payload["report"]["verdict"], "changes_required")
        self.assertEqual(payload["report"]["reason"],
                         "The authorization bypass is still reachable.")
        self.assertIn("changes_required", payload["summary"])
        self.assertIn("authorization bypass", payload["summary"])
