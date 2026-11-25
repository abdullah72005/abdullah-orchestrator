"""Focused v1.2.0 release workflow gates (A–F).

These tests use the real supervisor transitions, the real guarded launcher and
fake CLI executables. They make no live model calls and never touch live state.
"""
from __future__ import annotations

import copy
import errno
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

import test_orchestrator as baseline

orc = baseline.orc
SRC = baseline.SRC

FAKE_CLI = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import hashlib, json, os, sys
    data = b""
    try:
        data = sys.stdin.buffer.read()
    except Exception:
        data = b""
    record = os.environ.get("FAKE_RECORD")
    payload = {"argv": sys.argv[1:], "stdin_bytes": len(data),
               "stdin_sha256": hashlib.sha256(data).hexdigest(),
               "stdin_text": data.decode("utf-8", "replace"),
               "stdin_prefix_sha256": hashlib.sha256(data[:64]).hexdigest()}
    if record:
        with open(record, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload) + "\\n")
    print(json.dumps({"ok": True}))
    """)


TRIAL_METADATA = {"architect": {
    "state": "confirmed", "source": "test", "detail": "fixture",
    "version": "test", "models": {},
    "variants": ["low", "medium", "high"]}}


def fake_bin(root: Path, names=("codex", "claude", "opencode")):
    directory = root / "fake-bin"
    directory.mkdir(exist_ok=True)
    for name in names:
        path = directory / name
        path.write_text(FAKE_CLI)
        path.chmod(0o755)
    return directory


class ReleaseFixture(unittest.TestCase):
    """Isolated config/state plus a disposable Git project."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.env = patch.dict(os.environ, {
            "ABDULLAH_STATE_DIR": str(self.root / "runs"),
            "ABDULLAH_CONFIG": str(self.root / "config.json"),
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": "", "XDG_DATA_HOME": "",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        os.environ.pop("ABDULLAH_CHECKOUT_REGISTRY", None)
        state_patch = patch.object(orc, "DEFAULT_STATE", self.root / "runs")
        state_patch.start()
        self.addCleanup(state_patch.stop)
        self.cfg = orc.read_json(orc.HERE / "config.example.json")
        self.cfg_path = self.root / "config.json"
        orc.atomic_json(self.cfg_path, self.cfg)
        cfg_patch = patch.object(orc, "CONFIG_PATH", self.cfg_path)
        cfg_patch.start()
        self.addCleanup(cfg_patch.stop)
        self.bin = fake_bin(self.root)
        path_patch = patch.dict(os.environ, {
            "PATH": str(self.bin) + ":" + os.environ.get("PATH", "")})
        path_patch.start()
        self.addCleanup(path_patch.stop)
        self.project = baseline.setup_repo(self.root)
        self.rundir = self.root / "runs/test-v12000"
        self.rundir.mkdir(parents=True)
        self.record = self.root / "delivery.jsonl"

    def state(self, **overrides):
        state = {
            "id": "test-v12000", "status": "running", "phase": "implement",
            "project": str(self.project), "host": "codex", "goal": "Add a feature",
            "plan_approval": False, "batch_index": 0, "corrections": 0,
            "schema_version": orc.STATE_SCHEMA_VERSION,
            "supervisor_version": orc.SUPERVISOR_VERSION,
            "config_schema_version": orc.CONFIG_SCHEMA_VERSION,
            "config_sha256": orc.configuration_provenance().get("sha256"),
            "contract_version_required": orc.REPORT_CONTRACT_VERSION,
            "correction": "", "plan": None, "plan_version": None,
            "plan_revision": 1, "active_job": None, "completed_jobs": [],
            "failed_jobs": [], "accepted_batches": [], "review": None,
            "implementation": None, "verification": None, "amendments": [],
            "amendment_epoch": 0, "authority_epoch": 0, "retry_session": None,
            "plan_history": [], "accepted_history": [],
            "usage": {"strong_calls": 0, "cheap_calls": 0, "failed_attempts": 0,
                      "interrupted_attempts": 0, "corrections": 0,
                      "human_interventions": 0},
            "model_routes": {role: orc.model_route(self.cfg, "codex", role,
                                                   project=self.project)
                             for role in ("architect", "explorer", "implementer",
                                          "reviewer")},
        }
        state.update(overrides)
        return state

    def saved(self, state):
        orc.save(self.rundir, state)
        orc.atomic_json(self.rundir / "control.json", {"action": "run"})
        return state

    def state_file(self):
        return orc.read_json(self.rundir / "state.json")

    def plan(self, risk="ordinary", checks=None, batches=1):
        return {
            "status": "complete", "summary": "Plan", "invariants": ["Behavior"],
            "batches": [{"title": f"batch {n}", "goal": "Edit", "acceptance": ["Works"],
                         "checks": checks or [["true"]], "risk": risk}
                        for n in range(batches)],
            "blocker": ""}


class EscalationRoutingTests(ReleaseFixture):
    def test_explicit_needs_architect_goes_straight_to_durable_diagnosis(self):
        state = self.saved(self.state(plan=self.plan(), plan_version=None))
        state["plan_version"] = orc.content_hash(state["plan"])
        report = {"contract_version": 2, "status": "needs_architect",
                  "summary": "Which transaction boundary owns the retry?",
                  "files": ["app.py"], "tests": [], "evidence": ["app.py:1"],
                  "unknowns": ["idempotency key"], "blocker": "contract unclear"}
        strong_calls = []

        def worker(_dir, saved_state, _cfg, role, kind, prompt, project, **kw):
            self.assertEqual(kind, "implementer")
            return report, {"id": "impl-1"}

        def strong(_dir, saved_state, _cfg, kind, extra=None, **kw):
            strong_calls.append((kind, extra))
            return {"verdict": "changes_required", "reason": "Investigated",
                    "inspected": ["app.py"], "correction": "Do X", "blocker": ""}

        with patch.object(orc, "call_model", side_effect=worker), \
                patch.object(orc, "strong_call", side_effect=strong):
            orc.advance(self.rundir, state, self.cfg)
            self.assertEqual(state["phase"], "diagnose")
            self.assertEqual(state["corrections"], 0)  # escalation is not a retry
            request = state["diagnosis_request"]
            self.assertEqual(request["question"], report["summary"])
            self.assertEqual(request["evidence"], ["app.py:1"])
            self.assertEqual(request["unknowns"], ["idempotency key"])
            orc.advance(self.rundir, state, self.cfg)
        self.assertEqual([call[0] for call in strong_calls], ["diagnose"])
        self.assertEqual(strong_calls[0][1]["diagnosis_request"]["question"],
                         report["summary"])
        self.assertEqual(state["phase"], "implement")
        self.assertIn("Do X", state["correction"])

    def test_cached_completed_escalation_is_routed_to_diagnosis(self):
        state = self.state(plan=self.plan())
        state["plan_version"] = orc.content_hash(state["plan"])
        report = {"contract_version": 2, "status": "needs_architect",
                  "summary": "Unknown migration order", "files": ["app.py"],
                  "tests": [], "evidence": ["app.py:2"], "unknowns": ["order"],
                  "blocker": ""}
        state["completed_jobs"] = [{"id": "impl-cached", "kind": "implementer",
                                    "role": "implementer", "status": "complete",
                                    "created_at": orc.now(), "path": str(self.rundir)}]
        orc.atomic_json(self.rundir / "jobs" / "implementer-impl-cached" / "report.json", report)
        state["completed_jobs"][0]["path"] = str(self.rundir / "jobs" / "implementer-impl-cached")
        self.saved(state)
        with patch.object(orc, "strong_call") as strong:
            orc.advance(self.rundir, state, self.cfg)
        self.assertEqual(state["phase"], "diagnose")
        self.assertEqual(state["diagnosis_request"]["question"],
                         "Unknown migration order")
        strong.assert_not_called()

    def test_first_check_failure_retries_once_then_diagnoses(self):
        state = self.saved(self.state(plan=self.plan(), phase="verify"))
        state["plan_version"] = orc.content_hash(state["plan"])
        failed = {"passed": False, "source_unchanged": True,
                  "candidate_hash": "x", "commands": [], "error": None}
        retry_report = {"contract_version": 2, "status": "complete",
                        "summary": "retry", "files": [], "tests": [],
                        "evidence": [], "unknowns": [], "blocker": ""}
        with patch.object(orc, "run_checks", return_value=failed), \
                patch.object(orc, "call_model",
                             return_value=(retry_report, {"id": "impl-retry"})):
            orc.advance(self.rundir, state, self.cfg)
            self.assertEqual((state["phase"], state["corrections"]), ("implement", 1))
            orc.advance(self.rundir, state, self.cfg)  # cheap retry returns
            self.assertEqual(state["phase"], "verify")
            orc.advance(self.rundir, state, self.cfg)  # second failure
        self.assertEqual((state["phase"], state["corrections"]), ("diagnose", 2))
        self.assertEqual(state["diagnosis_source"], "routine_failure")

    def test_correction_budget_exhaustion_pauses_without_a_new_wave(self):
        state = self.saved(self.state(plan=self.plan(), phase="verify",
                                      corrections=self.cfg["limits"]["max_corrections_per_batch"]))
        state["plan_version"] = orc.content_hash(state["plan"])
        failed = {"passed": False, "source_unchanged": True,
                  "candidate_hash": "x", "commands": [], "error": None}
        with patch.object(orc, "run_checks", return_value=failed), \
                patch.object(orc, "call_model") as worker:
            orc.advance(self.rundir, state, self.cfg)
        self.assertEqual(state["status"], "blocked")
        self.assertIn("budget", state["pause_reason"].lower())
        worker.assert_not_called()

    def test_infrastructure_failure_keeps_pause_path(self):
        state = self.saved(self.state(plan=self.plan(), phase="verify"))
        state["plan_version"] = orc.content_hash(state["plan"])
        failed = {"passed": False, "source_unchanged": False, "error": None,
                  "candidate_hash": "x", "commands": []}
        with patch.object(orc, "run_checks", return_value=failed):
            orc.advance(self.rundir, state, self.cfg)
        self.assertEqual(state["corrections"], 0)
        self.assertNotEqual(state["phase"], "diagnose")

    def test_requirement_amendment_replans_and_invalidates_every_authority(self):
        plan = self.plan()
        state = self.state(phase="verify", plan=plan,
                           plan_version=orc.content_hash(plan),
                           verification={"path": str(self.root / "v.json"), "passed": True},
                           review={"status": "complete", "findings": []},
                           architect_verdict={"verdict": "approved"},
                           final_verdict={"verdict": "approved"},
                           single_batch_verification={"path": "old"},
                           decision_binding={"binding_sha256": "old"},
                           review_projection={"projection_sha256": "old"},
                           retry_session={"role": "implementer", "session_id": "s"},
                           accepted_batches=[{"index": 0, "verdict": {}}],
                           report_recoveries=[{"kind": "reviewer", "job_id": "r1",
                                               "authority_epoch": 0,
                                               "batch_index": 0, "plan_version": orc.content_hash(plan)}])
        self.saved(state)
        result = orc.amend_run(state["id"], "Also support offline resume",
                               kind="requirement")
        self.assertTrue(result["persisted"])
        _, state = orc.load(state["id"])
        self.assertEqual(state["phase"], "plan")
        self.assertIsNone(state["plan"])
        self.assertIsNone(state["verification"])
        self.assertIsNone(state["review"])
        self.assertIsNone(state["architect_verdict"])
        self.assertIsNone(state["final_verdict"])
        self.assertIsNone(state["retry_session"])
        self.assertNotIn("single_batch_verification", state)
        self.assertEqual(state["accepted_batches"], [])
        self.assertEqual(len(state["accepted_history"]), 1)
        self.assertEqual(len(state["plan_history"]), 1)
        self.assertGreater(state["authority_epoch"], 0)
        self.assertGreater(state["amendment_epoch"], 0)
        self.assertEqual(state["amendments"][-1]["text"], "Also support offline resume")
        # A recovered review from the old plan/epoch can never be consumed.
        self.assertIsNone(orc.cached_recovered_job_report(self.rundir, state, "reviewer"))

    def test_requirement_amendment_while_awaiting_plan_approval_stays_paused_at_plan(self):
        plan = self.plan()
        state = self.state(phase="plan", status="awaiting_plan_approval",
                           plan=plan, plan_version=orc.content_hash(plan),
                           plan_approval=True)
        self.saved(state)
        orc.amend_run(state["id"], "Change the acceptance rule", kind="requirement")
        _, state = orc.load(state["id"])
        self.assertEqual(state["phase"], "plan")
        self.assertEqual(state["status"], "paused")
        self.assertTrue(state["plan_approval"])

    def test_material_correction_keeps_the_diagnosis_investigation_path(self):
        plan = self.plan()
        state = self.state(phase="implement", plan=plan,
                           plan_version=orc.content_hash(plan))
        self.saved(state)
        orc.amend_run(state["id"], "Retry semantics look wrong",
                      architect_review=True, kind="correction")
        _, state = orc.load(state["id"])
        self.assertEqual(state["phase"], "diagnose")
        self.assertEqual(state["amendments"][-1]["routed_to"], "diagnose")

    def test_minor_correction_stays_bounded_and_references_the_amendment_id(self):
        plan = self.plan()
        state = self.state(phase="implement", plan=plan,
                           plan_version=orc.content_hash(plan),
                           implementation={"status": "complete", "summary": "s"})
        self.saved(state)
        orc.amend_run(state["id"], "Rename the helper", kind="correction")
        _, state = orc.load(state["id"])
        amendment = state["amendments"][-1]
        self.assertEqual(state["phase"], "implement")
        self.assertEqual(state["implementation"]["summary"], "s")
        self.assertIn(amendment["id"], state["correction"])
        self.assertEqual(amendment["routed_to"], "implement")

    def test_byte_identical_replan_still_requires_fresh_checks(self):
        plan = self.plan()
        version = orc.content_hash(plan)
        state = self.state(phase="accept", plan=plan, plan_version=version,
                           verification={"path": str(self.root / "v.json")},
                           architect_verdict={"verdict": "approved"})
        self.saved(state)
        orc.amend_run(state["id"], "No-op clarification that must replan",
                      kind="requirement")
        _, state = orc.load(state["id"])
        self.assertEqual(state["plan_revision"], 1)  # revision distinguishes the replan
        self.assertIsNone(state["verification"])
        # The new plan may be byte-identical; the plan_version is a content digest
        # but the epoch/revision still distinguish authority.
        state["plan"] = plan
        state["plan_version"] = version
        with self.assertRaises(Exception):
            orc._review_plan_guard({**state, "batch_index": 0})


class ReviewIndependenceTests(ReleaseFixture):
    def _dirty_project(self):
        project = self.project
        (project / "app.py").write_text("value = 1\n# user staged\n")
        subprocess.run(["git", "add", "app.py"], cwd=project, check=True, capture_output=True)
        (project / "extra.py").write_text("user unstaged\n")
        (project / "notes.txt").write_text("pre-existing untracked\n")
        return project

    def test_batch_delta_separates_preexisting_work_and_is_exact(self):
        project = self._dirty_project()
        state = self.state(plan=self.plan())
        state["plan_version"] = orc.content_hash(state["plan"])
        boundary = orc.capture_batch_boundary(
            project, self.rundir, "impl-1", batch_index=0,
            plan_version=state["plan_version"])
        staged_before = subprocess.run(
            ["git", "-C", str(project), "diff", "--cached", "--binary", "HEAD", "--"],
            capture_output=True, check=True).stdout
        # The writer edits a dirty file (same region) and adds a genuinely new file.
        (project / "app.py").write_text("value = 2\n# user staged\n")
        (project / "feature.py").write_text("def feature():\n    return 'new'\n")
        index_result = orc.finalize_batch_delta(
            project, self.rundir, "impl-1", boundary,
            final_snapshot=orc.source_snapshot(project), attempt=1)
        staged_after = subprocess.run(
            ["git", "-C", str(project), "diff", "--cached", "--binary", "HEAD", "--"],
            capture_output=True, check=True).stdout
        self.assertEqual(staged_before, staged_after)  # the real index untouched
        entries = {item["path"]: item for item in index_result["paths"]}
        self.assertTrue(entries["app.py"]["pre_existing"])
        self.assertTrue(entries["app.py"]["changed_in_window"])
        self.assertEqual(entries["feature.py"]["base_source"], "absent_at_dispatch_head")
        patches = [Path(item["hunks"][0]["path"]) for item in entries.values()
                   if item.get("hunks")]
        text = "".join((Path(index_result["hunks_dir"]) / p.name).read_text()
                       for p in patches)
        self.assertIn("+value = 2", text)
        self.assertNotIn("+# user staged", text)  # pre-existing work is not misattributed
        self.assertEqual((project / "extra.py").read_text(), "user unstaged\n")
        self.assertEqual((project / "notes.txt").read_text(), "pre-existing untracked\n")
        self.assertEqual(entries["notes.txt"]["pre_existing"], True)
        self.assertFalse(entries["notes.txt"]["changed_in_window"])

    def test_reviewer_packet_has_requirements_but_no_implementer_conclusions(self):
        plan = self.plan()
        state = self.saved(self.state(phase="review", plan=plan,
                                      plan_version=orc.content_hash(plan),
                                      verification={"path": "x"}, review=None))
        state["amendments"] = [{"id": "am1", "text": "MUST support offline resume",
                                "kind": "material", "request_kind": "requirement"}]
        state["implementation"] = {"status": "complete",
                                   "summary": "IMPLEMENTER-ONLY-CONCLUSION"}
        captured = {}
        package = {"commands": [{"argv": ["true"], "returncode": 0,
                                 "log": str(self.root / "log.txt"), "log_sha256": "a",
                                 "log_bytes": 1, "output_tail": "ok"}],
                   "passed": True, "source_unchanged": True,
                   "candidate_hash": orc.signature(orc.source_snapshot(self.project)),
                   "evidence_version": 2}
        with patch.object(orc, "review_verification_admission",
                          return_value=(plan["batches"][0], package)), \
                patch.object(orc, "call_model") as model:
            def fake(*args, **kwargs):
                captured["prompt"] = args[5]
                return ({"contract_version": 2, "status": "complete",
                         "summary": "reviewed", "files": [], "tests": [],
                         "evidence": [], "unknowns": [], "blocker": "",
                         "findings": []}, {"id": "rev-1"})
            model.side_effect = fake
            orc.advance(self.rundir, state, self.cfg)
        request = captured["prompt"][orc.PROMPT_REQUEST_KEY]
        text = json.dumps(request["context"])
        self.assertIn("MUST support offline resume", text)
        self.assertIn("Add a feature", text)
        self.assertNotIn("IMPLEMENTER-ONLY-CONCLUSION", text)
        self.assertEqual(text.count("MUST support offline resume"), 1)
        self.assertTrue(request["context"]["delta_index"]["attempts"] >= 0)
        projection = request["context"]["review_evidence"]
        self.assertIn(str(self.project), projection["root"])
        # The projection is genuinely readable through the reviewer's read path.
        relative = Path(projection["root"]).name + "/requirements.json"
        self.assertEqual(
            json.loads(orc.read_review_projection(self.project, relative))
            ["amendments"][0]["text"], "MUST support offline resume")
        with self.assertRaises(PermissionError):
            orc.read_review_projection(self.project, "../../../etc/passwd")

    def test_batch_delta_includes_committed_work(self):
        boundary = orc.capture_batch_boundary(
            self.project, self.rundir, "impl-commit", batch_index=0,
            plan_version="v")
        (self.project / "app.py").write_text("value = 9\n")
        subprocess.run(["git", "add", "app.py"], cwd=self.project, check=True,
                       capture_output=True)
        subprocess.run(["git", "commit", "-qm", "writer"], cwd=self.project,
                       check=True, capture_output=True)
        result = orc.finalize_batch_delta(
            self.project, self.rundir, "impl-commit", boundary,
            final_snapshot=orc.source_snapshot(self.project), attempt=1)
        entries = {item["path"]: item for item in result["paths"]}
        self.assertTrue(entries["app.py"]["changed_in_window"])

    def test_review_projection_works_in_a_linked_worktree(self):
        linked = self.root / "linked"
        subprocess.run(["git", "worktree", "add", "-q", str(linked), "-b",
                        "linked-review"], cwd=self.project, check=True,
                       capture_output=True)
        self.assertTrue((linked / ".git").is_file())
        (linked / "app.py").write_text("linked dirty work\n")
        plan = self.plan()
        state = self.saved(self.state(phase="review", plan=plan,
                                      plan_version=orc.content_hash(plan),
                                      project=str(linked)))
        before = orc.signature(orc.source_snapshot(linked))
        projection, rejection = orc.prepare_review_projection(
            self.rundir, state, self.cfg, linked, plan["batches"][0],
            {"commands": [], "passed": True})
        self.assertIsNone(rejection)
        self.assertEqual(projection["mode"], "checkout_scratch")
        self.assertEqual(orc.signature(orc.source_snapshot(linked)), before)
        relative = Path(projection["root"]).name + "/requirements.json"
        self.assertIn("Add a feature",
                      orc.read_review_projection(linked, relative))

    def test_protected_paths_are_not_copied_into_the_readable_projection(self):
        (self.project / ".env").write_text("SECRET=old\n")
        state = self.saved(self.state(phase="review", plan=self.plan()))
        state["plan_version"] = orc.content_hash(state["plan"])
        boundary = orc.capture_batch_boundary(
            self.project, self.rundir, "impl-env", batch_index=0,
            plan_version=state["plan_version"])
        (self.project / ".env").write_text("SECRET=new\n")
        result = orc.finalize_batch_delta(
            self.project, self.rundir, "impl-env", boundary,
            final_snapshot=orc.source_snapshot(self.project), attempt=1)
        state["batch_deltas"] = [{
            "attempt": 1, "job_id": "impl-env", "batch_index": 0,
            "plan_version": state["plan_version"], "hunks_dir": result["hunks_dir"],
            "paths": result["paths"], "limitations": result["limitations"]}]
        projection, rejection = orc.prepare_review_projection(
            self.rundir, state, self.cfg, self.project,
            state["plan"]["batches"][0], {"commands": [], "passed": True})
        self.assertIsNone(rejection)
        self.assertFalse(any(".env" in name for name in projection["files"]))
        self.assertTrue(any("protected" in item.get("reason", "")
                            for item in projection["limitations"]))

    def test_large_delta_has_readable_hunk_projection(self):
        body = "".join(f"line {number}\n" for number in range(400))
        (self.project / "app.py").write_text(body)
        state = self.saved(self.state(phase="review", plan=self.plan()))
        state["plan_version"] = orc.content_hash(state["plan"])
        boundary = orc.capture_batch_boundary(
            self.project, self.rundir, "impl-large", batch_index=0,
            plan_version=state["plan_version"])
        (self.project / "app.py").write_text(
            body.replace("line 200\n", "line 200 changed by the writer\n"))
        result = orc.finalize_batch_delta(
            self.project, self.rundir, "impl-large", boundary,
            final_snapshot=orc.source_snapshot(self.project), attempt=1)
        state["batch_deltas"] = [{
            "attempt": 1, "job_id": "impl-large", "batch_index": 0,
            "plan_version": state["plan_version"], "hunks_dir": result["hunks_dir"],
            "paths": result["paths"], "limitations": result["limitations"]}]
        projection, rejection = orc.prepare_review_projection(
            self.rundir, state, self.cfg, self.project,
            state["plan"]["batches"][0], {"commands": [], "passed": True})
        self.assertIsNone(rejection)
        patches = [name for name in projection["files"] if name.endswith(".patch")]
        self.assertTrue(patches)
        relative = Path(projection["root"]).name + "/" + patches[0]
        self.assertIn("changed by the writer",
                      orc.read_review_projection(self.project, relative))

    def test_implementer_prompt_carries_goal_and_amendments_once(self):
        plan = self.plan()
        state = self.saved(self.state(plan=plan, plan_version=orc.content_hash(plan)))
        state["amendments"] = [{"id": "am1", "text": "SENTINEL-REQUIREMENT",
                                "kind": "material", "request_kind": "requirement"}]
        state["approved_handoff"] = {"goal": "Add a feature", "constraints": ["no push"]}
        captured = {}
        with patch.object(orc, "call_model") as model:
            def fake(*args, **kwargs):
                captured["prompt"] = args[5]
                return ({"contract_version": 2, "status": "complete",
                         "summary": "done", "files": ["app.py"], "tests": [],
                         "evidence": ["app.py:1"], "unknowns": [], "blocker": ""},
                        {"id": "impl-1"})
            model.side_effect = fake
            orc.advance(self.rundir, state, self.cfg)
        context = captured["prompt"][orc.PROMPT_REQUEST_KEY]["context"]
        text = json.dumps(context)
        self.assertEqual(text.count("SENTINEL-REQUIREMENT"), 1)  # supplied once, verbatim
        requirements = context["requirements"]
        self.assertEqual(requirements["original_goal"], "Add a feature")
        self.assertEqual(requirements["amendments"][0]["id"], "am1")
        self.assertNotIn("goal", context["approved_handoff"])
        self.assertIn("duplicate", json.dumps(context["approved_handoff"]))

    def test_plan_omitting_a_user_requirement_still_reaches_the_worker_verbatim(self):
        # The plan deliberately omits the user's offline-resume requirement.
        state = self.saved(self.state(plan=self.plan(),
                                      goal="Add a feature; MUST support offline resume"))
        state["plan_version"] = orc.content_hash(state["plan"])
        captured = {}
        with patch.object(orc, "call_model") as model:
            def fake(*args, **kwargs):
                captured["prompt"] = args[5]
                return ({"contract_version": 2, "status": "complete",
                         "summary": "done", "files": [], "tests": [],
                         "evidence": ["app.py:1"], "unknowns": [], "blocker": ""},
                        {"id": "impl-1"})
            model.side_effect = fake
            orc.advance(self.rundir, state, self.cfg)
        text = json.dumps(captured["prompt"][orc.PROMPT_REQUEST_KEY]["context"])
        self.assertIn("MUST support offline resume", text)


class PromptTransportTests(ReleaseFixture):
    def _run_delivery(self, cmd, env, prompt, stdin_data):
        log_path = self.root / "delivery.log"
        env = dict(env)
        env["FAKE_RECORD"] = str(self.record)
        with log_path.open("w") as log:
            proc, lease = orc._spawn_guarded(cmd, self.project, env, log,
                                             stdin_data=stdin_data)
            proc.wait(timeout=30)
            os.close(lease)
        records = [json.loads(line) for line in
                   self.record.read_text().splitlines() if line.strip()]
        return records[-1]

    def test_codex_and_claude_receive_exact_utf8_bytes_on_stdin(self):
        payload = "Goal: " + "موثوق" * 40000 + " END-SENTINEL"
        self.assertGreater(len(payload.encode()), 128 * 1024)
        route = {"provider": "codex", "model": "gpt-6.2-sol", "effort": "high",
                 "billing": "subscription"}
        for host in ("codex", "claude"):
            with self.subTest(host=host):
                self.record.unlink(missing_ok=True)
                cmd, env, fmt = orc.cli_command(host, "architect", route, payload,
                                                self.rundir / f"{host}-job")
                self.assertNotIn(payload, cmd)
                if host == "codex":
                    self.assertEqual(cmd[-1], "-")
                else:
                    self.assertEqual(cmd[:2], ["claude", "-p"])
                delivered = self._run_delivery(cmd, env, payload, payload)
                self.assertEqual(delivered["stdin_bytes"], len(payload.encode()))
                self.assertEqual(delivered["stdin_sha256"],
                                 hashlib.sha256(payload.encode()).hexdigest())
                self.assertEqual(delivered["stdin_text"], payload)

    def test_opencode_keeps_positional_prompt_and_delivers_exact_argv_bytes(self):
        payload = "Task: " + "عربي" * 2000 + " END"
        route = {"provider": "opencode", "model": "opencode-go/deepseek-v4.1-flash",
                 "effort": "high", "billing": "go"}
        prepared = {"context": {"dialect": "v1"},
                    "env": {"PATH": str(self.bin) + ":" + os.environ.get("PATH", "")}}
        cmd, env, fmt = orc.cli_command("codex", "implementer", route, payload,
                                        self.rundir / "implementer-job",
                                        prepared=prepared)
        self.assertEqual(cmd[-1], payload)
        self.assertEqual(fmt, "jsonl")
        self.assertIsNone(orc.transport_space_error(cmd, env, prompt=payload))
        delivered = self._run_delivery(cmd, env, payload, None)
        self.assertEqual(delivered["argv"][-1], payload)

    def test_oversized_opencode_argv_is_refused_before_any_child(self):
        route = {"provider": "opencode", "model": "opencode-go/deepseek-v4.1-flash",
                 "effort": "high", "billing": "go"}
        big = "x" * 200000
        prepared = {"context": {"dialect": "v1"}, "env": {"PATH": os.environ["PATH"]}}
        cmd, env, _ = orc.cli_command("codex", "implementer", route, big,
                                      self.rundir / "job", prepared=prepared)
        problem = orc.transport_space_error(cmd, env, prompt=big)
        self.assertIsNotNone(problem)
        self.assertIn("per-string", problem)
        state = self.saved(self.state(phase="implement",
                                      plan=self.plan(),
                                      plan_version="v"))
        state["plan_version"] = orc.content_hash(state["plan"])
        with patch.object(orc, "route_preflight",
                          return_value={"ok": True, "authorization": {},
                                        "route_sha256": "x"}), \
                patch.object(orc, "_opencode_validated_dialect",
                             return_value={"dialect": "v1", "identity": {}}), \
                patch.object(orc, "_opencode_launch_context",
                             return_value={"context": {}}), \
                patch.object(orc, "_route_identity_recheck", return_value=None), \
                patch.object(orc, "cli_command",
                             return_value=(["/bin/true", big], {}, "jsonl")), \
                patch.object(orc, "_spawn_guarded") as spawn:
            with self.assertRaisesRegex(RuntimeError, "transport"):
                orc.call_model(self.rundir, state, self.cfg, "implementer",
                               "implementer", "prompt", self.project,
                               host="codex", route=route)
        spawn.assert_not_called()
        self.assertEqual(state["usage"]["strong_calls"], 0)
        self.assertIsNone(state.get("active_job"))
        self.assertEqual(state["preflight_rejection"]["reason_code"],
                         "transport_too_large")

    def test_oversized_environment_and_combined_exec_are_refused(self):
        route = {"provider": "codex", "model": "gpt-6.2-sol", "effort": "high",
                 "billing": "subscription"}
        cmd = ["codex", "exec", "-"]
        problem = orc.transport_space_error(
            cmd, {"HUGE": "x" * 200000}, lease_fds=2)
        self.assertIn("Environment entry", problem)
        # Individually legal argv strings can still overflow the combined block.
        many = ["x" * 100000 for _ in range(20)]
        problem = orc.transport_space_error(
            ["codex"] + many, {}, lease_fds=2)
        self.assertIn("Combined argv+environment", problem)

    def test_unexpected_e2big_is_prelaunch_and_uncounted(self):
        state = self.saved(self.state(phase="implement", plan=self.plan()))
        state["plan_version"] = orc.content_hash(state["plan"])
        route = {"provider": "codex", "model": "gpt-6.2-sol", "effort": "high",
                 "billing": "subscription"}
        with patch.object(orc, "route_preflight",
                          return_value={"ok": True, "authorization": {},
                                        "route_sha256": "x"}), \
                patch.object(orc, "_route_identity_recheck", return_value=None), \
                patch.object(orc, "_spawn_guarded",
                             side_effect=OSError(errno.E2BIG, "argument list too long")), \
                patch.object(orc, "cli_command",
                             return_value=(["codex", "exec"], {}, "codex")):
            with self.assertRaises(OSError):
                orc.call_model(self.rundir, state, self.cfg, "implementer",
                               "implementer", "prompt", self.project,
                               host="codex", route=route)
        self.assertEqual(state["usage"]["strong_calls"], 0)
        self.assertEqual(state["usage"]["cheap_calls"], 0)
        self.assertEqual(state["usage"]["failed_attempts"], 0)
        self.assertEqual(state["preflight_rejection"]["reason_code"],
                         "transport_too_large")
        self.assertIsNone(state.get("active_job"))

    def test_policy_is_delivered_once_per_route(self):
        context = {"goal": "Add a feature"}
        for provider in ("codex", "claude"):
            rendered = orc.render_prompt("implementer", context, include_policy=True)
            self.assertEqual(rendered.count("## Implementer — OpenCode Go"), 1)
        rendered = orc.render_prompt("implementer", context, include_policy=False)
        self.assertNotIn("## Implementer — OpenCode Go", rendered)
        self.assertIn("Add a feature", rendered)

    def test_explorer_placeholder_substitution_never_touches_user_text(self):
        state = self.state(phase="plan", plan=None)
        state["explorer_policy"] = "on_demand"
        context = orc.architect_context(self.rundir, state, "plan")
        context["goal"] = "Keep the literal __ABDULLAH_PARENT_JOB__ in my goal"
        rendered = orc.render_prompt("plan", context, parent_job="job-123")
        self.assertIn("Keep the literal __ABDULLAH_PARENT_JOB__ in my goal", rendered)
        self.assertIn("--parent-job job-123", rendered)
        self.assertNotIn("--parent-job __ABDULLAH_PARENT_JOB__", rendered)


class ForegroundTests(ReleaseFixture):
    def test_preview_carries_local_time_role_model_batch_and_expected_phase(self):
        plan = self.plan(batches=2)
        state = self.state(phase="implement", plan=plan, batch_index=1)
        state["plan_version"] = orc.content_hash(plan)
        preview = orc.next_stage_preview(state)
        self.assertEqual(preview["agent"], "implementer")
        self.assertEqual(preview["batch"]["label"], "Batch 2/2")
        self.assertEqual(preview["model"], state["model_routes"]["implementer"]["model"])
        self.assertIn("DeepSeek", preview["agent_label"])
        self.assertIn("deepseek", preview["agent_label"])
        self.assertEqual(preview["expected_phase"], "implement")
        self.assertRegex(preview["started_at"], r"[+-]\d\d:\d\d$")
        self.assertIn("Expected", json.dumps({"Expected": preview["expected"]}))

    def test_verify_stage_is_reported_as_supervisor_not_the_next_reviewer(self):
        plan = self.plan()
        state = self.state(phase="verify", plan=plan)
        payload = orc.stage_payload(self.rundir, state, "verify", None,
                                    "Run checks", "pass", 1.5,
                                    started={"batch": {"label": "Batch 1/1"},
                                             "agent_label": "Supervisor"})
        self.assertIsNone(payload["agent"])
        self.assertEqual(payload["route"]["provider"], "supervisor")
        self.assertEqual(payload["route"]["role"], None)
        self.assertEqual(payload["outcome"], "complete")

    def test_fallback_and_trial_show_configured_and_effective_routes(self):
        state = self.state(phase="review", plan=self.plan())
        state["model_routes"]["reviewer"] = {
            "provider": "opencode", "model": "opencode-go/deepseek-v4.1-flash",
            "effort": "high", "billing": "go",
            "fallback_route": {"provider": "codex", "model": "gpt-6-luna",
                               "effort": "medium", "billing": "subscription"}}
        state["worker_fallback_authorization"] = {
            "role": "reviewer",
            "route_sha256": orc.route_authorization_sha(
                state["model_routes"]["reviewer"]["fallback_route"])}
        preview = orc.next_stage_preview(state)
        self.assertEqual(preview["route_source"], "approved_worker_fallback")
        self.assertEqual(preview["route_configured"]["model"],
                         "opencode-go/deepseek-v4.1-flash")
        self.assertEqual(preview["route_effective"]["model"], "gpt-6-luna")
        self.assertTrue(preview["config_route_differs"])

    def test_stage_journal_records_start_local_time_and_pretransition_batch(self):
        plan = self.plan()
        state = self.saved(self.state(plan=plan, phase="verify"))
        state["plan_version"] = orc.content_hash(plan)
        passed = {"passed": True, "source_unchanged": True, "candidate_hash":
                  orc.signature(orc.source_snapshot(self.project)), "commands": [],
                  "path": None}
        with patch.object(orc, "run_checks", return_value=passed):
            payload = orc.stage_run(state["id"])
        self.assertEqual(payload["stage"], "verify")
        self.assertRegex(payload["started_at"], r"[+-]\d\d:\d\d$")
        self.assertEqual(payload["batch"]["label"], "Batch 1/1")
        events = [json.loads(line) for line in
                  (self.rundir / "journal.jsonl").read_text().splitlines()]
        start = [event for event in events if event["event"] == "stage_start"][-1]
        self.assertEqual(start["stage"], "verify")
        self.assertRegex(start["started_at"], r"[+-]\d\d:\d\d$")
        self.assertEqual(start["batch"]["label"], "Batch 1/1")
        end = [event for event in events if event["event"] == "stage_end"][-1]
        self.assertIn("elapsed_seconds", end)
        self.assertIn(end["outcome"], {"running", "paused", "complete", "blocked"})
        recap = orc.recap_run(state["id"])
        self.assertEqual(recap["facts"]["last_stage"]["stage"], "verify")
        self.assertIn("Last stage:", recap["text"])


class QuotaRoutingTests(ReleaseFixture):
    def test_shipped_codex_architect_default_is_sol_6_2_high(self):
        cfg = orc.read_json(orc.HERE / "config.example.json")
        self.assertEqual(cfg["architect"]["codex"]["model"], "gpt-6.2-sol")
        self.assertEqual(cfg["architect"]["codex"]["effort"], "high")
        self.assertEqual(cfg["architect"]["codex"]["auth"], "subscription")

    def test_trial_validation_rejects_unknown_risk_and_wrong_host(self):
        cfg = self.cfg
        self.assertIsNotNone(orc.validate_planning_trial(
            cfg, "codex", True, metadata=TRIAL_METADATA))
        with self.assertRaisesRegex(ValueError, "ordinary"):
            orc.validate_planning_trial(cfg, "codex", True,
                                        declared_risk="high",
                                        metadata=TRIAL_METADATA)
        with self.assertRaisesRegex(ValueError, "Codex"):
            orc.validate_planning_trial(cfg, "claude", True,
                                        metadata=TRIAL_METADATA)
        # No Sol-version literal gate: any catalogue-confirmed model works.
        other = json.loads(json.dumps(cfg))
        other["architect"]["codex"]["model"] = "gpt-6.1-sol"
        self.assertIsNotNone(orc.validate_planning_trial(
            other, "codex", True, metadata=TRIAL_METADATA))
        high_only = json.loads(json.dumps(TRIAL_METADATA))
        high_only["architect"]["variants"] = ["high"]
        with self.assertRaisesRegex(ValueError, "missing"):
            orc.validate_planning_trial(other, "codex", True,
                                        metadata=high_only)

    def test_initial_plan_uses_medium_and_acceptance_stays_high(self):
        plan = self.plan(risk="ordinary")
        trial = orc.validate_planning_trial(
            self.cfg, "codex", True, metadata=TRIAL_METADATA)
        state = self.saved(self.state(phase="plan", plan=None,
                                      ordinary_planning_trial=trial))
        calls = []

        def strong(_dir, saved_state, _cfg, kind, extra=None, **kw):
            calls.append((kind, kw.get("route")))
            if kind == "plan":
                return plan
            return {"verdict": "approved", "reason": "inspected", "inspected": ["app.py"],
                    "correction": "", "dismissed_findings": []}

        with patch.object(orc, "strong_call", side_effect=strong):
            orc.advance(self.rundir, state, self.cfg)
        self.assertEqual(calls[0][0], "plan")
        self.assertEqual(calls[0][1]["effort"], "medium")
        self.assertEqual(state["ordinary_planning_trial"]["state"], "adopted")
        self.assertIsNotNone(state["plan"])
        # Acceptance is dispatched through the pinned High route (no trial override).
        verification_path = self.root / "verification.json"
        verification_path.write_text("{}")
        state["phase"] = "accept"
        state["review"] = {"status": "complete", "findings": []}
        state["verification"] = {
            "path": str(verification_path), "passed": True,
            "candidate_hash": orc.signature(orc.source_snapshot(self.project)),
            "evidence_version": 2}
        with patch.object(orc, "strong_call", side_effect=strong), \
                patch.object(orc, "load_verification_evidence", return_value={}), \
                patch.object(orc, "validate_acceptance_references",
                             side_effect=lambda st, pr, refs, **kwargs: orc.source_snapshot(pr)), \
                patch.object(orc, "cached_decision_report", return_value=None):
            orc.advance(self.rundir, state, self.cfg)
        accept_calls = [call for call in calls if call[0] == "decision"]
        self.assertTrue(accept_calls)
        self.assertIsNone(accept_calls[-1][1])

    def test_high_risk_trial_plan_is_not_admitted(self):
        trial = orc.validate_planning_trial(
            self.cfg, "codex", True, metadata=TRIAL_METADATA)
        state = self.saved(self.state(phase="plan", plan=None,
                                      ordinary_planning_trial=trial))
        with patch.object(orc, "strong_call",
                          return_value=self.plan(risk="high")):
            orc.advance(self.rundir, state, self.cfg)
        self.assertIsNone(state["plan"])
        self.assertEqual(state["status"], "paused")
        self.assertEqual(state["ordinary_planning_trial"]["state"],
                         "rejected_high_risk")
        self.assertIn("High plan", state["pause_reason"])

    def test_ordinary_single_batch_success_is_two_strong_calls_and_no_explorer(self):
        plan = self.plan(risk="ordinary", batches=1)
        state = self.saved(self.state(phase="plan", plan=None))
        calls = []

        def strong(_dir, saved_state, _cfg, kind, extra=None, **kw):
            calls.append(kind)
            if kind == "plan":
                return plan
            return {"verdict": "approved", "reason": "inspected", "inspected": ["app.py"],
                    "correction": "", "dismissed_findings": []}

        def worker(_dir, saved_state, _cfg, role, kind, prompt, project, **kw):
            calls.append(role)
            if role == "implementer":
                (project / "app.py").write_text("value = 5\n")
                return ({"contract_version": 2, "status": "complete",
                         "summary": "done", "files": ["app.py"], "tests": [],
                         "evidence": ["app.py:1"], "unknowns": [], "blocker": ""},
                        {"id": "impl-1", "kind": "implementer"})
            return ({"contract_version": 2, "status": "complete", "summary": "r",
                     "files": [], "tests": [], "evidence": [], "unknowns": [],
                     "blocker": "", "findings": []}, {"id": "rev-1",
                                                      "kind": "reviewer"})

        def checks(_dir, saved_state, _cfg, project, batch, final=False, deadline=None):
            snapshot = orc.source_snapshot(project)
            path = self.root / "verification.json"
            path.write_text("{}")
            saved_state["verification"] = {
                "path": str(path), "passed": True,
                "candidate_hash": orc.signature(snapshot), "evidence_version": 2}
            return {"passed": True, "source_unchanged": True,
                    "candidate_hash": orc.signature(snapshot),
                    "commands": [], "path": str(path)}

        with patch.object(orc, "strong_call", side_effect=strong), \
                patch.object(orc, "call_model", side_effect=worker), \
                patch.object(orc, "run_checks", side_effect=checks), \
                patch.object(orc, "review_verification_admission",
                             return_value=(plan["batches"][0], {"commands": []})), \
                patch.object(orc, "load_verification_evidence", return_value={}), \
                patch.object(orc, "validate_acceptance_references",
                             side_effect=lambda st, pr, refs, **kwargs: orc.source_snapshot(pr)), \
                patch.object(orc, "cached_decision_report", return_value=None):
            for _ in range(12):
                if state["status"] == "complete":
                    break
                orc.advance(self.rundir, state, self.cfg)
        self.assertEqual(state["status"], "complete")
        self.assertEqual(calls.count("plan"), 1)
        self.assertEqual(calls.count("decision"), 1)
        self.assertEqual(calls.count("implementer"), 1)
        self.assertEqual(calls.count("reviewer"), 1)
        self.assertEqual(calls.count("explorer"), 0)

    def test_mechanical_exemption_and_high_risk_checks_are_unchanged(self):
        self.assertFalse(orc.risk_policy("mechanical", self.cfg)["independent_review"])
        self.assertEqual(orc.risk_policy("high", self.cfg)["minimum_checks"], 2)
        self.assertTrue(orc.risk_policy("ordinary", self.cfg)["independent_review"])

    def test_historical_route_pins_are_not_rewritten(self):
        record = {"provider": "codex", "model": "gpt-6.1-sol",
                  "effort": "high", "billing": "subscription"}
        normalized = orc._normalize_recorded_route("architect", record)
        self.assertEqual(normalized["model"], "gpt-6.1-sol")
        self.assertEqual(normalized["effort"], "high")


class WorkerInstructionTests(ReleaseFixture):
    def test_active_orchestrator_rule_appears_once_and_keeps_debugging_and_tdd(self):
        for role in ("implementer", "reviewer", "explorer", "plan", "decision"):
            with self.subTest(role=role):
                text = orc.role_text(role)
                self.assertEqual(text.count("## Active orchestrator run"), 1)
                for excluded in ("writing-plans", "executing-plans",
                                 "subagent-driven-development"):
                    self.assertIn(excluded, text)
                self.assertIn("systematic-debugging", text)
                self.assertIn("test-driven development", text)
                self.assertIn("standalone", text)

    def test_opencode_profile_carries_the_active_run_policy_once(self):
        for dialect, key in (("v1", "prompt"), ("v2", "system")):
            with self.subTest(dialect=dialect):
                profile = orc.opencode_profile("implementer", dialect)
                self.assertEqual(profile[key].count("## Active orchestrator run"), 1)
                self.assertIn("writing-plans", profile[key])

    def test_coordinator_startup_does_not_require_all_references(self):
        skill = (SRC.parents[1] / "SKILL.md").read_text()
        self.assertIn("You do not need to read the references first", skill)
        self.assertIn("1.2.1", skill)
        # Safety-critical stop/resume guidance stays in the entry skill.
        self.assertIn("orchestrator_reconcile", skill)
        self.assertIn("Never claim a worker stopped", skill)


class ReleaseIdentityCurrentTests(unittest.TestCase):
    def test_product_version_keeps_unchanged_internal_versions(self):
        info = orc.version_info()
        self.assertEqual(info["product_version"], "1.2.1")
        self.assertEqual(info["supervisor_version"], "3.1.0")
        self.assertEqual(info["state_schema_version"], 3)
        self.assertEqual(info["config_schema_version"], 3)
        self.assertEqual(info["report_contract_version"], 2)

    def test_release_evidence_and_changelog_exist_for_v120(self):
        root = SRC.parents[1]
        changelog = (root / "CHANGELOG.md").read_text()
        self.assertIn("1.2.0", changelog)
        evidence = root / "docs" / "release-evidence" / "v1.2.0"
        self.assertTrue(evidence.is_dir())
        self.assertTrue((evidence / "README.md").is_file())
        readme = (evidence / "README.md").read_text()
        self.assertIn("opencode-v2.txt", readme)
        self.assertIn("Installed OpenCode V2 module", readme)
        self.assertIn("correction", readme.lower())
        self.assertTrue((evidence / "opencode-v2.txt").is_file())
        self.assertTrue((evidence / "suite-correction.txt").is_file())
        # Candidate documentation links to a real path, not an unpublished tag.
        project_readme = (root / "README.md").read_text()
        self.assertNotIn("releases/tag/v1.2.0", project_readme)
        self.assertIn("docs/release-evidence/v1.2.0/README.md", project_readme)
        self.assertIn("tree/v1.0.0", project_readme)


class CorrectionCycleF120Tests(ReleaseFixture):
    """Findings F1/A1/A4/F2/F4/F5 from the Batch 1 review."""

    def _planned_state(self, **overrides):
        plan = self.plan()
        state = self.state(plan=plan, plan_version=orc.content_hash(plan))
        state.update(overrides)
        return self.saved(state), plan

    # -- F1 ---------------------------------------------------------------
    def test_material_correction_diagnoses_then_replans_never_implements_null(self):
        state, _plan = self._planned_state(phase="implement")
        result = orc.amend_run(state["id"], "Retry semantics look wrong",
                               architect_review=True, kind="correction")
        self.assertTrue(result["persisted"])
        _, state = orc.load(state["id"])
        self.assertEqual(state["phase"], "diagnose")
        self.assertIsNone(state["plan"])
        self.assertTrue(state["correction_replan"])
        seen = []

        def diagnose(_dir, saved, _cfg, kind, extra=None, **kw):
            seen.append(kind)
            return {"verdict": "changes_required", "reason": "investigated",
                    "inspected": ["app.py"], "correction": "Redo retries",
                    "blocker": ""}

        with patch.object(orc, "cached_job_report", return_value=None), \
                patch.object(orc, "strong_call", side_effect=diagnose):
            orc.advance(self.rundir, state, self.cfg)
        self.assertEqual(seen, ["diagnose"])
        self.assertEqual(state["phase"], "plan")
        self.assertIsNone(state["plan"])

        plan = self.plan()
        with patch.object(orc, "cached_job_report", return_value=None), \
                patch.object(orc, "strong_call", return_value=plan):
            orc.advance(self.rundir, state, self.cfg)
        self.assertEqual(state["phase"], "implement")
        self.assertEqual(state["plan_version"], orc.content_hash(plan))
        self.assertGreater(state["plan_revision"], 0)

    def test_pending_requirement_replan_keeps_route_and_both_entries(self):
        state, _plan = self._planned_state(phase="plan", status="paused", plan=None,
                                       plan_version=None, amendment_material=True,
                                       amendments=[{"id": "req-1", "at": orc.now(),
                                                     "text": "MUST support offline resume",
                                                     "request_kind": "requirement",
                                                     "kind": "material",
                                                     "routed_to": "plan"}])
        orc.amend_run(state["id"], "Also keep the legacy endpoint",
                      architect_review=True, kind="correction")
        _, state = orc.load(state["id"])
        self.assertEqual(state["phase"], "plan")
        self.assertIsNone(state["plan"])
        self.assertTrue(state["amendment_material"])
        self.assertEqual([item["text"] for item in state["amendments"]],
                         ["MUST support offline resume",
                          "Also keep the legacy endpoint"])
        self.assertEqual(state["amendments"][-1]["routed_to"], "plan")
        self.assertEqual(state["status"], "paused")

    def test_ordinary_correction_without_plan_reaches_planning(self):
        state, _plan = self._planned_state(phase="implement", plan=None,
                                       plan_version=None)
        orc.amend_run(state["id"], "Rename the helper", kind="correction")
        _, state = orc.load(state["id"])
        self.assertEqual(state["phase"], "plan")
        self.assertIsNone(state["plan"])
        self.assertEqual(state["amendments"][-1]["routed_to"], "plan")

    def test_blocked_diagnosis_never_reaches_implementation(self):
        state, _plan = self._planned_state(phase="implement")
        orc.amend_run(state["id"], "Retry semantics look wrong",
                      architect_review=True, kind="correction")
        _, state = orc.load(state["id"])
        with patch.object(orc, "cached_job_report", return_value=None), \
                patch.object(orc, "strong_call",
                             return_value={"verdict": "blocked",
                                           "reason": "contradiction",
                                           "inspected": [], "correction": "",
                                           "blocker": "contradiction"}):
            orc.advance(self.rundir, state, self.cfg)
        self.assertEqual(state["phase"], "diagnose")
        self.assertIsNone(state["plan"])
        self.assertNotEqual(state["status"], "running")

    def test_lock_time_active_dispatch_recheck_rejects_the_amendment(self):
        state, _plan = self._planned_state(phase="implement")
        clean = copy.deepcopy(state)
        active = copy.deepcopy(state)
        active["active_job"] = {"id": "live", "role": "implementer",
                                "status": "running"}
        responses = iter([(self.rundir, clean), (self.rundir, active)])
        stream = object()
        with patch.object(orc, "load", side_effect=lambda _id: next(responses)), \
                patch.object(orc, "_acquire_lock_file", return_value=stream), \
                patch.object(orc, "_release_lock_file", return_value=None):
            result = orc.amend_run(state["id"], "Apply this mid-flight",
                                   architect_review=True, kind="correction")
        self.assertFalse(result["ok"])
        self.assertIn("became active", result["error"])
        self.assertEqual(clean["amendments"], [])
        self.assertEqual(clean["phase"], "implement")

    # -- A4 ---------------------------------------------------------------
    def test_protected_decision_rejects_medium_default_route_before_dispatch(self):
        state, _plan = self._planned_state(phase="accept")
        route = {"provider": "codex", "model": "gpt-6.2-sol",
                 "effort": "medium", "billing": "subscription"}
        with self.assertRaisesRegex(RuntimeError, "Protected Architect decision"):
            orc.call_model(self.rundir, state, self.cfg, "architect", "decision",
                           "prompt", self.project, route=dict(route))
        self.assertIsNone(state.get("active_job"))

    def test_authorized_medium_architect_fallback_is_rejected_and_consent_kept(self):
        state, _plan = self._planned_state(phase="accept", host="codex")
        state["fallback_authorization"] = {"role": "architect", "used": 0}
        cfg = copy.deepcopy(self.cfg)
        cfg["fallback"]["codex"] = {"model": "gpt-6-luna", "effort": "medium"}
        with patch.object(orc, "config", return_value=cfg):
            with self.assertRaisesRegex(RuntimeError, "approved fallback"):
                orc.call_model(self.rundir, state, cfg, "architect", "decision",
                               "prompt", self.project)
        self.assertEqual(state["fallback_authorization"],
                         {"role": "architect", "used": 0})

    def test_high_acceptance_route_is_admitted_for_dispatch(self):
        state, _plan = self._planned_state(phase="accept")
        route = {"provider": "codex", "model": "gpt-6.2-sol",
                 "effort": "high", "billing": "subscription"}
        with patch.object(orc, "route_preflight",
                          side_effect=RuntimeError("sentinel-preflight")) as preflight:
            with self.assertRaisesRegex(RuntimeError, "sentinel-preflight"):
                orc.call_model(self.rundir, state, self.cfg, "architect",
                               "decision", "prompt", self.project, route=route)
        preflight.assert_called()

    # -- F2 ---------------------------------------------------------------
    def test_compacted_reviewer_prompt_keeps_packet_and_delta_pointer(self):
        project = self.project
        state, plan = self._planned_state(phase="review", plan_version=None)
        state["plan_version"] = orc.content_hash(plan)
        boundary = orc.capture_batch_boundary(
            project, self.rundir, "impl-f2", batch_index=0,
            plan_version=state["plan_version"])
        (project / "app.py").write_text("value = 42\n")
        result = orc.finalize_batch_delta(
            project, self.rundir, "impl-f2", boundary,
            final_snapshot=orc.source_snapshot(project), attempt=1)
        state["batch_deltas"] = [{
            "attempt": 1, "job_id": "impl-f2", "batch_index": 0,
            "plan_version": state["plan_version"], "hunks_dir": result["hunks_dir"],
            "paths": result["paths"], "limitations": result["limitations"]}]
        package = {"commands": [{"argv": ["true"], "returncode": 0,
                                 "log": str(self.root / "log.txt"), "log_sha256": "a",
                                 "log_bytes": 1, "output_tail": "ok"}],
                   "passed": True, "source_unchanged": True,
                   "candidate_hash": orc.signature(orc.source_snapshot(project)),
                   "verification_path": str(self.root / "verification.json"),
                   "verification_sha256": "verify-f2", "evidence_version": 2}
        projection, rejection = orc.prepare_review_projection(
            self.rundir, state, self.cfg, project, plan["batches"][0], package)
        self.assertIsNone(rejection)
        real_hunk = next(Path(result["hunks_dir"]) / Path(h["path"]).name
                         for item in result["paths"] for h in item.get("hunks", []))
        self.assertTrue(real_hunk.is_file())
        files = {name: {"sha256": orc._sha256_file(real_hunk), "bytes": 1}
                 for name in [f"delta/fake-{n}.patch" for n in range(45)]}
        context = {
            "project": str(project), "batch": plan["batches"][0],
            "plan_version": state["plan_version"],
            "source": orc.source_snapshot(project), "verification": package,
            "requirements": orc.user_requirements(state),
            "review_evidence": {**projection, "files": files,
                                "untrusted_files": ["verification.json"]},
            "delta_index": {"batch_index": 0, "attempts": 1,
                            "files": [{"path": f"f{n}.py", "hunks": [
                                {"path": str(real_hunk)}]} for n in range(60)],
                            "totals": {"additions": 1, "deletions": 0},
                            "paths": [result.get("index_path") or
                                      str(Path(result["hunks_dir"]).parent / "index.json")],
                            "note": "delta"},
            "invariants": plan["invariants"],
            "instruction": "Review independently.",
            "bulk_optional_noise": "x" * 60_000,
        }
        cfg = copy.deepcopy(self.cfg)
        cfg.setdefault("limits", {})["max_context_chars"] = 40_000
        with patch.object(orc, "config", return_value=cfg):
            prompt = orc.render_prompt("reviewer", context)
        body = prompt.split("Task and evidence:\n", 1)[1]
        body = body.rsplit("\n\nReply with ONE valid JSON object", 1)[0]
        parsed = json.loads(body)
        self.assertTrue(parsed["_context_budget"]["truncated"])
        evidence = parsed["review_evidence"]
        self.assertEqual(evidence["root"], projection["root"])
        self.assertEqual(evidence["manifest"], projection["manifest"])
        self.assertTrue(Path(evidence["manifest"]).is_file())
        self.assertTrue(evidence["files_truncated"])
        delta = parsed["delta_index"]
        self.assertTrue(delta["files_truncated"])
        self.assertTrue(delta["index_paths"])
        self.assertTrue(Path(delta["index_paths"][0]).is_file())
        hunk_path = Path(delta["files"][0]["hunks"][0]["path"])
        self.assertTrue(hunk_path.is_file())
        self.assertIn("+value = 42", hunk_path.read_text())
        # The pointer is readable through the Reviewer's real read policy.
        relative = Path(projection["root"]).name + "/" + \
            next(name for name in projection["files"] if name.endswith(".patch"))
        self.assertIn("value = 42",
                      orc.read_review_projection(project, relative))

    # -- F4 ---------------------------------------------------------------
    def test_medium_plan_stage_reports_attempted_trial_route_and_outcome(self):
        trial = orc.validate_planning_trial(
            self.cfg, "codex", True, metadata=TRIAL_METADATA)
        state = self.saved(self.state(phase="plan", plan=None,
                                      ordinary_planning_trial=trial))
        with patch.object(orc, "strong_call", return_value=self.plan()):
            payload = orc.stage_run(state["id"])
        self.assertEqual(payload["outcome"], "complete")
        self.assertEqual(payload["route_source"], "ordinary_planning_trial")
        self.assertEqual(payload["effort"], "medium")
        self.assertEqual(payload["batch"]["label"], "planning")
        self.assertEqual(self.state_file()["ordinary_planning_trial"]["state"],
                         "adopted")
        events = [json.loads(line) for line in
                  (self.rundir / "journal.jsonl").read_text().splitlines()]
        start = [event for event in events if event["event"] == "stage_start"][-1]
        end = [event for event in events if event["event"] == "stage_end"][-1]
        self.assertEqual(start["route"]["route_source"], "ordinary_planning_trial")
        self.assertEqual(end["outcome"], "complete")
        recap = orc.recap_run(state["id"])
        self.assertEqual(recap["facts"]["last_stage"]["outcome"], "complete")

    def test_verification_completion_uses_one_outcome_and_one_stage(self):
        state, plan = self._planned_state(phase="verify")
        passed = {"passed": True, "source_unchanged": True,
                  "candidate_hash": orc.signature(orc.source_snapshot(self.project)),
                  "commands": [], "path": None}
        with patch.object(orc, "run_checks", return_value=passed):
            payload = orc.stage_run(state["id"])
        self.assertEqual(payload["outcome"], "complete")
        self.assertEqual(self.state_file()["phase"], "review")
        self.assertEqual(self.state_file()["status"], "running")
        events = [json.loads(line) for line in
                  (self.rundir / "journal.jsonl").read_text().splitlines()]
        self.assertEqual(sum(1 for event in events
                             if event["event"] == "stage_start"), 1)
        self.assertEqual(sum(1 for event in events
                             if event["event"] == "stage_end"), 1)
        self.assertEqual([event["outcome"] for event in events
                          if event["event"] == "stage_end"], ["complete"])
        recap = orc.recap_run(state["id"])
        self.assertEqual(recap["facts"]["last_stage"]["outcome"], "complete")

    def test_phase_changing_stage_keeps_pre_transition_batch_and_route(self):
        state, plan = self._planned_state(phase="implement")
        report = {"contract_version": 2, "status": "complete", "summary": "done",
                  "files": ["app.py"], "tests": [], "evidence": ["app.py:1"],
                  "unknowns": [], "blocker": ""}
        job = {"id": "impl-f4", "kind": "implementer", "role": "implementer",
               "path": str(self.rundir / "jobs")}
        with patch.object(orc, "cached_job_report", return_value=None), \
                patch.object(orc, "call_model", return_value=(dict(report), job)):
            payload = orc.stage_run(state["id"])
        self.assertEqual(payload["batch"]["label"], "Batch 1/1")
        self.assertEqual(payload["route_source"], "pinned")
        self.assertIsNotNone(payload["started_at_offset"])
        self.assertGreaterEqual(payload["elapsed_seconds"], 0)
        self.assertEqual(self.state_file()["phase"], "verify")
        self.assertEqual(payload["next_phase"], "verify")
        self.assertEqual(payload["outcome"], "complete")

    # -- F5 ---------------------------------------------------------------
    def test_nested_explorer_is_route_aware_and_carries_requirements_once(self):
        plan = self.plan()
        state = self.state(phase="plan", plan=plan,
                           plan_version=orc.content_hash(plan),
                           explorer_policy="on_demand")
        state["goal"] = "Add a feature"
        state["amendments"] = [{"id": "am1", "at": orc.now(),
                                "text": "MUST support offline resume",
                                "request_kind": "requirement",
                                "kind": "material", "routed_to": "plan"}]
        state["active_job"] = {"id": "architect-parent", "role": "architect",
                               "status": "running"}
        self.saved(state)
        captured = {}

        def model(*args, **kwargs):
            captured["prompt"] = args[5]
            return ({"contract_version": 2, "status": "complete", "summary": "explored",
                     "files": [], "tests": [], "evidence": [], "unknowns": [],
                     "blocker": ""},
                    {"id": "expl-1", "role": "explorer"})

        from types import SimpleNamespace
        os.environ.pop("ABDULLAH_PARENT_JOB", None)
        os.environ.pop("ABDULLAH_RUN_ID", None)
        with patch.object(orc, "call_model", side_effect=model):
            orc.explore(SimpleNamespace(run=state["id"], task="find callers",
                                        parent_job="architect-parent"))
        request = captured["prompt"][orc.PROMPT_REQUEST_KEY]
        context = request["context"]
        self.assertNotIn("goal", context)
        self.assertEqual(context["requirements"]["original_goal"], "Add a feature")
        self.assertEqual(context["requirements"]["amendments"][0]["text"],
                         "MUST support offline resume")
        rendered = orc.render_prompt(request["kind"], context, include_policy=True)
        self.assertEqual(rendered.count("MUST support offline resume"), 1)
        self.assertEqual(rendered.count("Add a feature"), 1)

    def test_strong_architect_context_has_no_duplicate_goal_or_amendment(self):
        plan = self.plan()
        state = self.state(phase="plan", plan=None)
        state["goal"] = "Add a feature"
        state["amendments"] = [{"id": "am1", "at": orc.now(),
                                "text": "MUST support offline resume",
                                "request_kind": "requirement",
                                "kind": "material", "routed_to": "plan"}]
        self.saved(state)
        captured = {}

        def model(*args, **kwargs):
            captured["prompt"] = args[5]
            return plan, {"id": "plan-f5"}

        with patch.object(orc, "cached_job_report", return_value=None), \
                patch.object(orc, "call_model", side_effect=model):
            orc.advance(self.rundir, state, self.cfg)
        context = captured["prompt"][orc.PROMPT_REQUEST_KEY]["context"]
        self.assertNotIn("goal", context)
        self.assertNotIn("user_amendments", context)
        self.assertEqual(context["requirements"]["original_goal"], "Add a feature")
        rendered = orc.render_prompt("plan", context, include_policy=True)
        self.assertEqual(rendered.count("MUST support offline resume"), 1)
        self.assertEqual(rendered.count("Add a feature"), 1)


class DeltaFidelityF120Tests(ReleaseFixture):
    def _edit(self, relative, text):
        path = self.project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def _commit(self, message="fixture"):
        subprocess.run(["git", "add", "-A"], cwd=self.project, check=True,
                       capture_output=True)
        subprocess.run(["git", "commit", "-qm", message], cwd=self.project,
                       check=True, capture_output=True)

    def test_mode_only_change_and_empty_add_delete_are_tracked(self):
        self._edit("mode.sh", "#!/bin/sh\nexit 0\n")
        self._edit("empty.txt", "")
        self._commit()
        boundary = orc.capture_batch_boundary(
            self.project, self.rundir, "impl-a3", batch_index=0,
            plan_version="v")
        (self.project / "mode.sh").chmod(0o755)
        (self.project / "empty.txt").unlink()
        self._edit("new-empty.txt", "")
        result = orc.finalize_batch_delta(
            self.project, self.rundir, "impl-a3", boundary,
            final_snapshot=orc.source_snapshot(self.project), attempt=1)
        entries = {item["path"]: item for item in result["paths"]}
        self.assertTrue(entries["mode.sh"]["mode_changed"])
        self.assertTrue(entries["mode.sh"]["changed_in_window"])
        self.assertEqual(entries["empty.txt"]["presence_before"], "file")
        self.assertEqual(entries["empty.txt"]["presence_after"], "absent")
        self.assertTrue(entries["empty.txt"]["changed_in_window"])
        self.assertEqual(entries["new-empty.txt"]["presence_before"], "absent")
        self.assertEqual(entries["new-empty.txt"]["presence_after"], "file")
        self.assertTrue(entries["new-empty.txt"]["changed_in_window"])

    def test_nonempty_deletion_records_removed_lines(self):
        boundary = orc.capture_batch_boundary(
            self.project, self.rundir, "impl-del", batch_index=0,
            plan_version="v")
        (self.project / "app.py").unlink()
        result = orc.finalize_batch_delta(
            self.project, self.rundir, "impl-del", boundary,
            final_snapshot=orc.source_snapshot(self.project), attempt=1)
        entry = next(item for item in result["paths"]
                     if item["path"] == "app.py")
        self.assertTrue(entry["changed_in_window"])
        self.assertEqual(entry["presence_after"], "absent")
        self.assertTrue(entry.get("hunks"))
        patch_path = Path(result["hunks_dir"]) / Path(entry["hunks"][0]["path"]).name
        text = patch_path.read_text()
        self.assertIn("-value = 1", text)
        self.assertGreater(entry["deletions"], 0)

    def test_restored_head_bytes_are_labelled_as_overlap(self):
        self._edit("app.py", "user pre-existing\n")
        boundary = orc.capture_batch_boundary(
            self.project, self.rundir, "impl-restore", batch_index=0,
            plan_version="v")
        self._edit("app.py", "value = 1\n")
        result = orc.finalize_batch_delta(
            self.project, self.rundir, "impl-restore", boundary,
            final_snapshot=orc.source_snapshot(self.project), attempt=1)
        entry = next(item for item in result["paths"]
                     if item["path"] == "app.py")
        self.assertTrue(entry["changed_in_window"])
        self.assertTrue(entry["overlap"])
        self.assertTrue(entry.get("restored_to_head"))
        self.assertTrue(entry.get("after_matches_head"))

    def test_unavailable_capture_budget_marks_dirty_path_not_clean(self):
        self._edit("first.py", "one\n")
        self._edit("second.py", "two\n")
        with patch.object(orc, "DELTA_MAX_PATHS", 1):
            boundary = orc.capture_batch_boundary(
                self.project, self.rundir, "impl-limit", batch_index=0,
                plan_version="v")
        self.assertFalse(boundary["capture_complete"])
        self.assertTrue(boundary["omitted_paths"])
        result = orc.finalize_batch_delta(
            self.project, self.rundir, "impl-limit", boundary,
            final_snapshot=orc.source_snapshot(self.project), attempt=1)
        entries = {item["path"]: item for item in result["paths"]}
        omitted = boundary["omitted_paths"][0]
        self.assertEqual(entries[omitted]["attributable"], "unavailable")
        self.assertIn("before_image_not_captured", entries[omitted]["base_source"])
        self.assertEqual(entries[omitted]["before"], "pre_existing_worktree")
        self.assertFalse(entries[omitted].get("changed_in_window", False))

    def test_unreachable_head_and_comparison_failure_are_reported(self):
        boundary = orc.capture_batch_boundary(
            self.project, self.rundir, "impl-bad-head", batch_index=0,
            plan_version="v")
        boundary["head"] = "0" * 40
        snapshot = orc.source_snapshot(self.project)
        real_git = orc.git

        def failing_git(project, args, *a, **kw):
            if args and args[0] == "diff":
                raise orc.subprocess.CalledProcessError(128, ["git", "diff"])
            return real_git(project, args, *a, **kw)

        with patch.object(orc, "git", side_effect=failing_git):
            result = orc.finalize_batch_delta(
                self.project, self.rundir, "impl-bad-head", boundary,
                final_snapshot=snapshot, attempt=1)
        self.assertEqual(result["dispatch_head_comparison"], "unavailable")
        self.assertTrue(any(item.get("reason") ==
                            "dispatch-head comparison unavailable"
                            for item in result["limitations"]))

    def test_tracked_file_deleted_before_dispatch_is_not_treated_as_clean(self):
        self._edit("gone.py", "removed before dispatch\n")
        self._commit("add gone")
        (self.project / "gone.py").unlink()
        boundary = orc.capture_batch_boundary(
            self.project, self.rundir, "impl-gone", batch_index=0,
            plan_version="v")
        self.assertIn("gone.py", boundary["dirty_paths"])
        result = orc.finalize_batch_delta(
            self.project, self.rundir, "impl-gone", boundary,
            final_snapshot=orc.source_snapshot(self.project), attempt=1)
        entry = next(item for item in result["paths"]
                     if item["path"] == "gone.py")
        self.assertEqual(entry["before"], "pre_existing_worktree")
        self.assertFalse(entry["changed_in_window"])
        self.assertTrue(entry["pre_existing"])
        self.assertEqual(entry["presence_before"], "absent")
        self.assertEqual(entry["presence_after"], "absent")

    def test_index_and_worktree_state_are_labelled(self):
        self._edit("app.py", "value = 9\n")
        subprocess.run(["git", "add", "app.py"], cwd=self.project, check=True,
                       capture_output=True)
        self._edit("extra.py", "unstaged\n")
        boundary = orc.capture_batch_boundary(
            self.project, self.rundir, "impl-state", batch_index=0,
            plan_version="v")
        index_before = subprocess.run(
            ["git", "-C", str(self.project), "diff", "--cached", "--binary",
             "HEAD", "--"], capture_output=True, check=True).stdout
        self._edit("feature.py", "new\n")
        result = orc.finalize_batch_delta(
            self.project, self.rundir, "impl-state", boundary,
            final_snapshot=orc.source_snapshot(self.project), attempt=1)
        index_after = subprocess.run(
            ["git", "-C", str(self.project), "diff", "--cached", "--binary",
             "HEAD", "--"], capture_output=True, check=True).stdout
        self.assertEqual(index_before, index_after)
        self.assertEqual(result["index_sha256_at_dispatch"],
                         boundary["index_sha256"])
        self.assertEqual(result["worktree_status_sha256_at_dispatch"],
                         boundary["status_sha256"])
        self.assertIn("app.py", result["pre_existing_dirty_paths"])
        self.assertIn("extra.py", result["pre_existing_dirty_paths"])
        self.assertEqual(result["dispatch_head_comparison"], "complete")


class ProjectionIntegrityF120Tests(ReleaseFixture):
    def _package(self, sha="verify-one"):
        return {"commands": [{"argv": ["true"], "returncode": 0,
                              "log": str(self.root / "log.txt"),
                              "log_sha256": "a", "log_bytes": 1,
                              "output_tail": "ok"}],
                "passed": True, "source_unchanged": True,
                "candidate_hash": orc.signature(orc.source_snapshot(self.project)),
                "verification_path": str(self.root / f"{sha}.json"),
                "verification_sha256": sha, "evidence_version": 2}

    def _projection(self, state, package=None):
        return orc.prepare_review_projection(
            self.rundir, state, self.cfg, self.project,
            state["plan"]["batches"][0], package or self._package())

    def _review_state(self):
        plan = self.plan()
        state = self.state(phase="review", plan=plan,
                           plan_version=orc.content_hash(plan))
        self.saved(state)
        return state

    def test_corrupt_and_missing_packet_files_are_rebuilt_not_reused(self):
        state = self._review_state()
        projection, rejection = self._projection(state)
        self.assertIsNone(rejection)
        self.assertIsNone(orc._validate_projection_packet(projection))
        requirements = Path(projection["root"]) / "requirements.json"
        requirements.write_text("{corrupt")
        self.assertIsNotNone(orc._validate_projection_packet(projection))
        repaired, rejection = self._projection(state)
        self.assertIsNone(rejection)
        self.assertIsNone(orc._validate_projection_packet(repaired))
        self.assertIn("Add a feature",
                      json.loads(requirements.read_text())["original_goal"])
        target = Path(repaired["root"]) / "batch.json"
        target.unlink()
        self.assertIsNotNone(orc._validate_projection_packet(repaired))
        rebuilt, rejection = self._projection(state)
        self.assertIsNone(rejection)
        self.assertTrue((Path(rebuilt["root"]) / "batch.json").is_file())

    def test_interrupted_staging_is_retryable_and_unowned_path_is_refused(self):
        state = self._review_state()
        projection, rejection = self._projection(state)
        self.assertIsNone(rejection)
        root, _mode = orc.review_projection_root(self.project)
        name = Path(projection["root"]).name
        staging = root / (".staging-" + name)
        staging.mkdir()
        orc.atomic_json(staging / "STAGING.json", {
            "generated_by": "abdullah-orchestrator",
            "run_id": state["id"], "project": str(self.project)})
        state.pop("review_projection", None)
        retried, rejection = self._projection(state)
        self.assertIsNone(rejection)
        self.assertFalse(staging.exists())
        self.assertIsNone(orc._validate_projection_packet(retried))

        unowned = root / (name + "-unowned")
        unowned.mkdir()
        (unowned / "user.txt").write_text("user content\n")
        state.pop("review_projection", None)
        package = self._package("verify-unowned")
        package["candidate_hash"] = "x" * 40
        with patch.object(orc, "review_projection_root",
                          return_value=(unowned.parent, "git_metadata")), \
                patch.object(orc, "_projection_owner_problem", return_value=None), \
                patch.object(orc, "signature", return_value="x" * 40):
            target_name = (f"{state['id']}-b{state.get('batch_index', 0)}-"
                           f"{('x' * 40)[:12]}-verify-unown")
            if unowned.name != target_name:
                unowned.rename(unowned.parent / target_name)
            result, rejection = orc.prepare_review_projection(
                self.rundir, state, self.cfg, self.project,
                state["plan"]["batches"][0], package)
        self.assertIsNone(result)
        self.assertIsNotNone(rejection)
        self.assertEqual((unowned.parent / target_name / "user.txt").read_text(),
                         "user content\n")

    def test_linked_worktree_excludes_only_verified_generated_files(self):
        linked = self.root / "linked-f3"
        subprocess.run(["git", "worktree", "add", "-q", str(linked), "-b",
                        "linked-f3"], cwd=self.project, check=True,
                       capture_output=True)
        plan = self.plan()
        state = self.state(phase="review", plan=plan,
                           plan_version=orc.content_hash(plan),
                           project=str(linked))
        self.saved(state)
        package = self._package("linked-verify")
        package["candidate_hash"] = orc.signature(orc.source_snapshot(linked))
        projection, rejection = orc.prepare_review_projection(
            self.rundir, state, self.cfg, linked, plan["batches"][0], package)
        self.assertIsNone(rejection)
        scratch = Path(projection["root"]).parent
        (scratch / "user-notes.txt").write_text("unrelated user content\n")
        root, owned = orc._projection_owned_paths(linked)
        self.assertEqual(root, scratch)
        self.assertIn(".abdullah-review/OWNER.json", owned)
        self.assertNotIn(str((scratch / "user-notes.txt").relative_to(linked)),
                         owned)
        cfg = copy.deepcopy(self.cfg)
        cfg["verification"]["runtime_inputs"] = {
            "patterns": ["*"], "heuristic": False, "declared": [],
            "required": [], "exclude": [], "max_files": 5000,
            "max_total_bytes": 20 * 1024 * 1024}
        manifest = orc.runtime_input_manifest(linked, cfg)
        names = set(manifest["files"])
        relative_user = str((scratch / "user-notes.txt").relative_to(linked))
        self.assertIn(relative_user, names)
        relative_generated = str((Path(projection["root"]) / "requirements.json")
                                 .relative_to(linked))
        self.assertNotIn(relative_generated, names)

    def test_new_verification_identity_gets_a_new_packet_not_the_old_one(self):
        state = self._review_state()
        first, rejection = self._projection(state, self._package("verify-old"))
        self.assertIsNone(rejection)
        second, rejection = self._projection(state, self._package("verify-new"))
        self.assertIsNone(rejection)
        self.assertNotEqual(first["root"], second["root"])
        self.assertNotEqual(first["verification_sha256"],
                            second["verification_sha256"])
        self.assertTrue(Path(first["root"]).is_dir())
        self.assertIsNone(orc._validate_projection_packet(first))
        self.assertIsNone(orc._validate_projection_packet(second))

    def test_evidence_candidate_mismatch_is_refused(self):
        state = self._review_state()
        package = self._package("wrong-candidate")
        package["candidate_hash"] = "not-the-current-candidate"
        projection, rejection = self._projection(state, package)
        self.assertIsNone(projection)
        self.assertIsNotNone(rejection)
        self.assertEqual(rejection.code, "review_projection_unavailable")


class BatchCorrectionsR02Tests(ReleaseFixture):
    def _commit(self, message="fixture"):
        subprocess.run(["git", "add", "-A"], cwd=self.project, check=True,
                       capture_output=True)
        subprocess.run(["git", "commit", "-qm", message], cwd=self.project,
                       check=True, capture_output=True)

    def _package(self, sha="verify-r02", candidate=None):
        return {"commands": [{"argv": ["true"], "returncode": 0,
                              "log": str(self.root / "log.txt"),
                              "log_sha256": "a", "log_bytes": 1,
                              "output_tail": "ok"}],
                "passed": True, "source_unchanged": True,
                "candidate_hash": (candidate or orc.signature(
                    orc.source_snapshot(self.project))),
                "verification_path": str(self.root / f"{sha}.json"),
                "verification_sha256": sha, "evidence_version": 2}

    def _review_projection(self, state, package=None):
        return orc.prepare_review_projection(
            self.rundir, state, self.cfg, self.project,
            state["plan"]["batches"][0], package or self._package())

    def _review_state(self):
        plan = self.plan()
        state = self.state(phase="review", plan=plan,
                           plan_version=orc.content_hash(plan))
        self.saved(state)
        return state

    # -- finding 1: index vs worktree -------------------------------------
    def test_pre_existing_staged_bytes_are_reviewed_not_hidden(self):
        (self.project / "app.py").write_text("value = 2\n")
        subprocess.run(["git", "add", "app.py"], cwd=self.project, check=True,
                       capture_output=True)
        (self.project / "app.py").write_text("value = 1\n")
        boundary = orc.capture_batch_boundary(
            self.project, self.rundir, "impl-staged-only", batch_index=0,
            plan_version="v")
        result = orc.finalize_batch_delta(
            self.project, self.rundir, "impl-staged-only", boundary,
            final_snapshot=orc.source_snapshot(self.project), attempt=1)
        entry = next(item for item in result["paths"] if item["path"] == "app.py")
        self.assertFalse(entry["changed_in_window"])
        self.assertTrue(entry["index_pre_existing"])
        self.assertTrue(entry["index_differs_from_head"])
        self.assertTrue(entry["staged_only"])
        scopes = {hunk["scope"] for hunk in entry["hunks"]}
        self.assertIn("index_pre_existing", scopes)
        patch_path = (Path(result["hunks_dir"])
                      / Path(next(h for h in entry["hunks"]
                                  if h["scope"] == "index_pre_existing")["path"]).name)
        text = patch_path.read_text()
        self.assertIn("-value = 1", text)
        self.assertIn("+value = 2", text)

    def test_staged_only_window_change_has_a_staged_hunk(self):
        boundary = orc.capture_batch_boundary(
            self.project, self.rundir, "impl-stage-window", batch_index=0,
            plan_version="v")
        # The writer stages a change and leaves the worktree bytes unchanged.
        (self.project / "app.py").write_text("value = 3\n")
        subprocess.run(["git", "add", "app.py"], cwd=self.project, check=True,
                       capture_output=True)
        (self.project / "app.py").write_text("value = 1\n")
        result = orc.finalize_batch_delta(
            self.project, self.rundir, "impl-stage-window", boundary,
            final_snapshot=orc.source_snapshot(self.project), attempt=1)
        entry = next(item for item in result["paths"] if item["path"] == "app.py")
        self.assertTrue(entry["changed_in_window"])
        self.assertTrue(entry["index_changed_in_window"])
        self.assertFalse(entry["worktree_changed_in_window"])
        staged = [hunk for hunk in entry["hunks"] if hunk["scope"] == "index"]
        self.assertEqual(len(staged), 1)
        text = (Path(result["hunks_dir"])
                / Path(staged[0]["path"]).name).read_text()
        self.assertIn("+value = 3", text)
        # The real index was only read; the staged value is still current.
        staged_now = subprocess.run(
            ["git", "-C", str(self.project), "show", ":app.py"],
            capture_output=True, text=True, check=True).stdout
        self.assertEqual(staged_now, "value = 3\n")

    def test_staged_overlap_distinguishes_preexisting_from_later_staging(self):
        (self.project / "app.py").write_text("value = 2\n")
        subprocess.run(["git", "add", "app.py"], cwd=self.project, check=True,
                       capture_output=True)
        (self.project / "app.py").write_text("value = 1\n")
        boundary = orc.capture_batch_boundary(
            self.project, self.rundir, "impl-overlap", batch_index=0,
            plan_version="v")
        (self.project / "app.py").write_text("value = 4\n")
        subprocess.run(["git", "add", "app.py"], cwd=self.project, check=True,
                       capture_output=True)
        result = orc.finalize_batch_delta(
            self.project, self.rundir, "impl-overlap", boundary,
            final_snapshot=orc.source_snapshot(self.project), attempt=1)
        entry = next(item for item in result["paths"] if item["path"] == "app.py")
        self.assertTrue(entry["index_pre_existing"])
        self.assertTrue(entry["index_changed_in_window"])
        self.assertTrue(entry["index_overlap"])
        texts = [(Path(result["hunks_dir"]) / Path(hunk["path"]).name).read_text()
                 for hunk in entry["hunks"]]
        self.assertTrue(any("+value = 4" in text for text in texts))

    def test_attempt_chain_flags_unaccounted_change_and_missing_boundary(self):
        first = orc.capture_batch_boundary(
            self.project, self.rundir, "chain-1", batch_index=0,
            plan_version="v")
        (self.project / "app.py").write_text("value = 5\n")
        orc.finalize_batch_delta(self.project, self.rundir, "chain-1", first,
                                 final_snapshot=orc.source_snapshot(self.project),
                                 attempt=1)
        # A change between the recorded completion and the next dispatch.
        (self.project / "app.py").write_text("value = 6\n")
        second = orc.capture_batch_boundary(
            self.project, self.rundir, "chain-2", batch_index=0,
            plan_version="v", previous_job_id="chain-1")
        result = orc.finalize_batch_delta(
            self.project, self.rundir, "chain-2", second,
            final_snapshot=orc.source_snapshot(self.project), attempt=2)
        self.assertEqual(result["attempt_chain"]["status"],
                         "unaccounted_changes")
        self.assertTrue(any("unaccounted changes between writer windows"
                            in item["reason"] for item in result["limitations"]))
        # Missing previous boundary evidence is explicit uncertainty, not clean.
        orphan = orc.capture_batch_boundary(
            self.project, self.rundir, "chain-3", batch_index=0,
            plan_version="v", previous_job_id="does-not-exist")
        result = orc.finalize_batch_delta(
            self.project, self.rundir, "chain-3", orphan,
            final_snapshot=orc.source_snapshot(self.project), attempt=3)
        self.assertEqual(result["attempt_chain"]["status"], "unavailable")
        self.assertTrue(any("previous writer boundary unavailable"
                            in item["reason"] for item in result["limitations"]))

    def test_dispatch_head_git_error_is_never_confirmed_absence(self):
        boundary = orc.capture_batch_boundary(
            self.project, self.rundir, "impl-bad-head-r02", batch_index=0,
            plan_version="v")
        boundary["head"] = "f" * 40
        (self.project / "app.py").write_text("value = 8\n")
        result = orc.finalize_batch_delta(
            self.project, self.rundir, "impl-bad-head-r02", boundary,
            final_snapshot=orc.source_snapshot(self.project), attempt=1)
        entry = next(item for item in result["paths"] if item["path"] == "app.py")
        self.assertEqual(entry["attributable"], "unavailable")
        self.assertEqual(entry["base_source"], "dispatch_head_unreadable")

    # -- finding 2: byte-aware handoff ------------------------------------
    def _opencode_route(self):
        return {"provider": "opencode", "model": "opencode-go/deepseek-v4.1-flash",
                "effort": "high", "billing": "go"}

    def _dispatch(self, state, prompt, captured, *, side_effect=None):
        def fake_cli(_host, _role, _route, value, *a, **kw):
            captured["prompt"] = value
            return (["/bin/true", value], {}, "jsonl")

        with patch.object(orc, "route_preflight",
                          return_value={"ok": True, "authorization": {},
                                        "route_sha256": "x"}), \
                patch.object(orc, "_opencode_validated_dialect",
                             return_value={"dialect": "v1", "identity": {}}), \
                patch.object(orc, "_opencode_launch_context",
                             return_value={"context": {}}), \
                patch.object(orc, "_route_identity_recheck", return_value=None), \
                patch.object(orc, "cli_command", side_effect=fake_cli), \
                patch.object(orc, "_spawn_guarded",
                             side_effect=side_effect or RuntimeError("stop-after-gates")):
            return orc.call_model(self.rundir, state, self.cfg, "reviewer",
                                  "reviewer", prompt, self.project, host="codex",
                                  route=self._opencode_route())

    def _large_review_context(self):
        real_hunk = self.root / "packet" / "delta" / "attempt-1" / "0001.patch"
        real_hunk.parent.mkdir(parents=True, exist_ok=True)
        real_hunk.write_text("--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n"
                             "-value = 1\n+value = 2\n")
        files = {f"delta/attempt-1/file-{n:04d}.patch":
                 {"sha256": "a" * 64, "bytes": 10} for n in range(1000)}
        hunks = [{"path": str(real_hunk), "sha256": "a" * 64, "bytes": 10}
                 for _ in range(1000)]
        return {
            "requirements": {"original_goal": "اعتماد المراجعة",
                             "amendments": []},
            "review_evidence": {
                "root": str(self.root / "packet"),
                "manifest": str(self.root / "packet" / "manifest.json"),
                "manifest_sha256": "m" * 64,
                "projection_sha256": "p" * 64,
                "files": files, "limitations": []},
            "delta_index": {
                "batch_index": 0,
                "files": [{"path": f"f{n}.py", "note": "موثوق" * 4,
                           "hunks": [hunks[n]]} for n in range(1000)],
                "paths": [str(self.root / "batch-deltas" / "j"
                              / "after" / "index.json")]},
            "instruction": "Review the candidate independently.",
            "optional_bulk": "x" * 60_000,
        }

    def test_large_utf8_review_is_compacted_before_argv_admission(self):
        state = self._review_state()
        context = self._large_review_context()
        cfg = copy.deepcopy(self.cfg)
        cfg.setdefault("limits", {})["max_context_chars"] = 500_000
        raw = json.dumps(context, ensure_ascii=False)
        self.assertLess(len(raw), cfg["limits"]["max_context_chars"])
        self.assertGreater(len(raw.encode()), orc._arg_string_limit())
        captured = {}
        with patch.object(orc, "config", return_value=cfg), \
                self.assertRaisesRegex(RuntimeError, "stop-after-gates"):
            self._dispatch(state, orc.prompt_request("reviewer", context), captured)
        prompt = captured["prompt"]
        self.assertLessEqual(len(prompt.encode()),
                             orc._arg_string_limit())
        self.assertIsNone(orc.transport_space_error(
            ["/bin/true", prompt], {}, prompt=prompt))
        body = prompt.split("Task and evidence:\n", 1)[1]
        body = body.rsplit("\n\nReply with ONE valid JSON object", 1)[0]
        parsed = json.loads(body)
        self.assertTrue(parsed["_context_budget"]["truncated"])
        evidence = parsed["review_evidence"]
        self.assertEqual(evidence["root"], str(self.root / "packet"))
        self.assertTrue(evidence["manifest"].endswith("manifest.json"))
        self.assertTrue(evidence["files_truncated"])
        delta = parsed["delta_index"]
        self.assertTrue(delta["index_paths"])
        self.assertTrue(delta["files"][0]["hunks"][0]["path"].endswith("0001.patch"))

    def test_true_oversized_mandatory_review_is_refused_uncounted(self):
        state = self.saved(self.state(
            phase="review", plan=self.plan(),
            plan_version=orc.content_hash(self.plan())))
        state["fallback_authorization"] = {"role": "reviewer", "used": 0}
        cfg = copy.deepcopy(self.cfg)
        cfg["fallback"]["codex"] = {"model": "gpt-6-luna", "effort": "medium"}
        context = {"requirements": {"original_goal": "x" * 250_000,
                                    "amendments": []},
                   "instruction": "Review."}
        captured = {}
        with patch.object(orc, "config", return_value=cfg), \
                patch.object(orc, "route_preflight",
                             return_value={"ok": True, "authorization": {},
                                           "route_sha256": "x"}), \
                patch.object(orc, "_route_identity_recheck", return_value=None), \
                patch.object(orc, "cli_command") as cli, \
                patch.object(orc, "_spawn_guarded") as spawn:
            with self.assertRaisesRegex(RuntimeError, "transport"):
                orc.call_model(self.rundir, state, cfg, "reviewer", "reviewer",
                               orc.prompt_request("reviewer", context),
                               self.project, host="codex")
        cli.assert_not_called()
        spawn.assert_not_called()
        self.assertEqual(state["fallback_authorization"],
                         {"role": "reviewer", "used": 0})
        self.assertEqual(state["usage"]["strong_calls"], 0)
        self.assertEqual(state["usage"]["cheap_calls"], 0)
        self.assertIsNone(state.get("active_job"))
        rejection = state["preflight_rejection"]
        self.assertEqual(rejection["reason_code"], "transport_too_large")
        self.assertFalse(rejection["active_job_created"])
        self.assertFalse(rejection["model_calls_counted"])

    # -- finding 3: packet integrity gates --------------------------------
    def test_packet_change_before_launch_is_refused_uncounted(self):
        state = self._review_state()
        projection, rejection = self._review_projection(state)
        self.assertIsNone(rejection)
        state["review_projection"] = projection
        self.saved(state)
        capture = {}

        def mutate(_route, _preflight, _cfg, _project, _role, **kwargs):
            target = Path(projection["root"]) / "requirements.json"
            target.write_text('{"tampered": true}\n')
            return None

        with patch.object(orc, "route_preflight",
                          return_value={"ok": True, "authorization": {},
                                        "route_sha256": "x"}), \
                patch.object(orc, "_route_identity_recheck", side_effect=mutate), \
                patch.object(orc, "_spawn_guarded") as spawn:
            with self.assertRaisesRegex(RuntimeError, "review packet"):
                orc.call_model(self.rundir, state, self.cfg, "reviewer",
                               "reviewer", "prompt", self.project,
                               host="codex", dispatch_evidence=projection,
                               route={"provider": "codex", "model": "gpt-6.2-sol",
                                      "effort": "high", "billing": "subscription"})
        spawn.assert_not_called()
        self.assertEqual(state["usage"]["strong_calls"], 0)
        self.assertIsNone(state.get("active_job"))
        self.assertEqual(state["preflight_rejection"]["reason_code"],
                         "review_packet_invalid")
        self.assertFalse(state["preflight_rejection"]["model_calls_counted"])

    def test_staged_packet_validation_refuses_linked_components(self):
        state = self._review_state()
        projection, rejection = self._review_projection(state)
        self.assertIsNone(rejection)
        root = Path(projection["root"])
        outside = self.root / "outside-delta"
        (root / "delta").rename(outside)
        os.symlink(outside, root / "delta")
        self.assertIn("symlink", orc._validate_projection_packet(projection))

    def test_completed_review_loses_authority_when_packet_changes(self):
        state = self._review_state()
        projection, rejection = self._review_projection(state)
        self.assertIsNone(rejection)
        jobdir = self.rundir / "jobs" / "reviewer-r02"
        snapshot = orc.source_snapshot(self.project)
        orc.atomic_json(jobdir / "dispatch.json", {
            "kind": "reviewer", "role": "reviewer", "source": snapshot,
            "review_packet": projection["binding"],
            "dispatch_evidence": projection})
        orc.atomic_json(jobdir / "completion.json", {"final_snapshot": snapshot})
        job = {"id": "reviewer-r02", "kind": "reviewer", "role": "reviewer",
               "path": str(jobdir)}
        self.assertIsNone(orc.validate_preserved_stage_source(job, jobdir, "reviewer"))
        (Path(projection["root"]) / "requirements.json").write_text("{}\n")
        violation = orc.validate_preserved_stage_source(job, jobdir, "reviewer")
        self.assertIsNotNone(violation)
        self.assertEqual(violation.diagnostics["reasons"],
                         ["review_packet_changed"])

    def test_new_format_review_without_binding_is_refused(self):
        state = self._review_state()
        projection, rejection = self._review_projection(state)
        self.assertIsNone(rejection)
        jobdir = self.rundir / "jobs" / "reviewer-nobind"
        snapshot = orc.source_snapshot(self.project)
        # New-format job (dispatch carries packet evidence) but no binding.
        orc.atomic_json(jobdir / "dispatch.json", {
            "kind": "reviewer", "role": "reviewer", "source": snapshot,
            "dispatch_evidence": projection})
        orc.atomic_json(jobdir / "completion.json", {"final_snapshot": snapshot})
        job = {"id": "reviewer-nobind", "kind": "reviewer", "role": "reviewer",
               "path": str(jobdir)}
        violation = orc.validate_preserved_stage_source(job, jobdir, "reviewer")
        self.assertIsNotNone(violation)
        # Historical job with no packet at all preserves old behavior.
        legacy = self.rundir / "jobs" / "reviewer-legacy"
        orc.atomic_json(legacy / "dispatch.json", {
            "kind": "reviewer", "role": "reviewer", "source": snapshot})
        orc.atomic_json(legacy / "completion.json", {"final_snapshot": snapshot})
        self.assertIsNone(orc.validate_preserved_stage_source(
            {"id": "reviewer-legacy", "kind": "reviewer", "role": "reviewer",
             "path": str(legacy)}, legacy, "reviewer"))

    def test_interrupted_retry_preserves_unrecognized_user_file(self):
        state = self._review_state()
        projection, rejection = self._review_projection(state)
        self.assertIsNone(rejection)
        root, _mode = orc.review_projection_root(self.project)
        staging = root / (".staging-" + Path(projection["root"]).name)
        staging.mkdir()
        orc.atomic_json(staging / "STAGING.json", {
            "generated_by": "abdullah-orchestrator",
            "run_id": state["id"], "project": str(self.project)})
        (staging / "user-notes.txt").write_text("keep me\n")
        state.pop("review_projection", None)
        retried, rejection = self._review_projection(state)
        self.assertIsNone(rejection)
        self.assertFalse(staging.exists())
        preserved = list(root.glob(".staging-*.preserved-*"))
        self.assertEqual(len(preserved), 1)
        self.assertEqual((preserved[0] / "user-notes.txt").read_text(),
                         "keep me\n")
        self.assertIsNone(orc._validate_projection_packet(retried))

    def test_linked_worktree_excludes_only_verified_artifacts(self):
        linked = self.root / "linked-r02"
        subprocess.run(["git", "worktree", "add", "-q", str(linked), "-b",
                        "linked-r02"], cwd=self.project, check=True,
                       capture_output=True)
        plan = self.plan()
        state = self.state(phase="review", plan=plan,
                           plan_version=orc.content_hash(plan),
                           project=str(linked))
        self.saved(state)
        package = self._package("linked-r02",
                                candidate=orc.signature(orc.source_snapshot(linked)))
        projection, rejection = orc.prepare_review_projection(
            self.rundir, state, self.cfg, linked, plan["batches"][0], package)
        self.assertIsNone(rejection)
        root, owned = orc._projection_owned_paths(linked)
        generated = str((Path(projection["root"]) / "requirements.json")
                        .relative_to(linked))
        self.assertIn(generated, owned)
        # A changed artifact invalidates the whole exclusion set for that packet.
        (Path(projection["root"]) / "requirements.json").write_text("{}\n")
        _root, owned_after = orc._projection_owned_paths(linked)
        self.assertNotIn(generated, owned_after)


class BatchCorrectionsR03Tests(ReleaseFixture):
    """Writer-attempt accounting, staged deletion and snapshot identity."""

    def _commit(self, message="fixture"):
        subprocess.run(["git", "add", "-A"], cwd=self.project, check=True,
                       capture_output=True)
        subprocess.run(["git", "commit", "-qm", message], cwd=self.project,
                       check=True, capture_output=True)

    def _package(self, sha="verify-r03"):
        return {"commands": [], "passed": True, "source_unchanged": True,
                "candidate_hash": orc.signature(
                    orc.source_snapshot(self.project)),
                "verification_path": str(self.root / f"{sha}.json"),
                "verification_sha256": sha, "evidence_version": 2}

    def _projection(self, state, package=None):
        return orc.prepare_review_projection(
            self.rundir, state, self.cfg, self.project,
            state["plan"]["batches"][0], package or self._package())

    def _implementer_job(self, job_id, *, write_boundary=True,
                         prewrite_index=False):
        jobdir = self.rundir / "jobs" / f"implementer-{job_id}"
        jobdir.mkdir(parents=True, exist_ok=True)
        boundary = None
        dispatch = {"kind": "implementer", "role": "implementer",
                    "source": orc.source_snapshot(self.project)}
        if write_boundary:
            boundary = orc.capture_batch_boundary(
                self.project, self.rundir, job_id, batch_index=0,
                plan_version="v")
            orc.atomic_json(jobdir / "batch-boundary.json", boundary)
            dispatch["batch_boundary"] = boundary
        orc.atomic_json(jobdir / "dispatch.json", dispatch)
        return jobdir, boundary

    def _finish_job(self, state, job_id, jobdir):
        (self.project / "app.py").write_text("value = 7\n")
        snapshot = orc.source_snapshot(self.project)
        orc.atomic_json(jobdir / "execution.json", {"returncode": 0, "seconds": 1})
        orc.atomic_json(jobdir / "report.json", {
            "contract_version": 2, "status": "complete", "summary": "done",
            "files": ["app.py"], "tests": [], "evidence": ["app.py:1"],
            "unknowns": [], "blocker": ""})
        orc.atomic_json(jobdir / "completion.json",
                        {"final_snapshot": snapshot, "session_id": "ses-r03"})
        state["active_job"] = {
            "id": job_id, "kind": "implementer", "role": "implementer",
            "path": str(jobdir), "status": "running",
            **baseline.dead_process_identity()}
        return snapshot

    def test_recovered_writer_delta_reaches_the_review_projection(self):
        plan = self.plan()
        state = self.saved(self.state(phase="implement", plan=plan,
                                      plan_version=orc.content_hash(plan)))
        job_id = "impl-recovered-r03"
        jobdir, boundary = self._implementer_job(job_id)
        # Simulate a crash after the delta index was published but before state.
        self._finish_job(state, job_id, jobdir)
        completion = orc.source_snapshot(self.project)
        publisher = copy.deepcopy(state)
        prewritten = orc._record_batch_delta(
            self.rundir, publisher, self.project, job_id, boundary,
            completion, phase="completion")
        self.assertTrue(prewritten["complete"])
        orc.save(self.rundir, state)
        rolled_back = copy.deepcopy(state)
        self.assertTrue(orc.recover_finished_dispatch(self.rundir, state))
        records = [item for item in state["batch_deltas"]
                   if item.get("job_id") == job_id]
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertTrue(record["complete"])
        self.assertEqual(record["index_sha256"], prewritten["index_sha256"])
        entry = next(item for item in record["paths"] if item["path"] == "app.py")
        self.assertTrue(entry["changed_in_window"])
        self.assertTrue(entry["hunks"])
        # A crash before the state save replays the same attempt via the same
        # durable index; it must not add a second record.
        orc.save(self.rundir, rolled_back)
        self.assertTrue(orc.recover_finished_dispatch(self.rundir, rolled_back))
        self.assertEqual(len([item for item in rolled_back["batch_deltas"]
                              if item.get("job_id") == job_id]), 1)
        self.assertEqual(rolled_back["batch_deltas"][0]["index_sha256"],
                         prewritten["index_sha256"])
        # An explicit replay of the recording entry point is also idempotent.
        orc._record_batch_delta(self.rundir, state, self.project, job_id,
                                boundary, orc.source_snapshot(self.project))
        self.assertEqual(len([item for item in state["batch_deltas"]
                              if item.get("job_id") == job_id]), 1)
        delta = orc.batch_delta_index(state)
        self.assertEqual(delta["attempts"], 1)
        self.assertFalse(delta["incomplete_writer_attempts"])
        state["phase"] = "review"
        projection, rejection = self._projection(state)
        self.assertIsNone(rejection)
        patches = [name for name in projection["files"] if name.endswith(".patch")]
        self.assertTrue(any("app.py" in name for name in patches))
        readable = [orc.read_review_projection(
            self.project, Path(projection["root"]).name + "/" + name)
            for name in patches]
        self.assertTrue(any("+value = 7" in text for text in readable))
        index_text = orc.read_review_projection(
            self.project, Path(projection["root"]).name + "/delta/index.json")
        self.assertEqual(json.loads(index_text)["attempts"], 1)

    def test_missing_writer_boundary_is_a_counted_review_limitation(self):
        plan = self.plan()
        state = self.saved(self.state(phase="implement", plan=plan,
                                      plan_version=orc.content_hash(plan)))
        job_id = "impl-lost-boundary-r03"
        jobdir, _ = self._implementer_job(job_id, write_boundary=False)
        self._finish_job(state, job_id, jobdir)
        orc.save(self.rundir, state)
        self.assertTrue(orc.recover_finished_dispatch(self.rundir, state))
        record = next(item for item in state["batch_deltas"]
                      if item.get("job_id") == job_id)
        self.assertFalse(record["complete"])
        self.assertEqual(record["paths"], [])
        self.assertTrue(any("writer attempt evidence unavailable"
                            in item["reason"] for item in record["limitations"]))
        delta = orc.batch_delta_index(state)
        self.assertEqual(delta["attempts"], 1)
        self.assertEqual(len(delta["incomplete_writer_attempts"]), 1)
        state["phase"] = "review"
        projection, rejection = self._projection(state)
        self.assertIsNone(rejection)
        self.assertTrue(any("writer attempt evidence unavailable"
                            in item.get("reason", "")
                            for item in projection["limitations"]))
        index_text = orc.read_review_projection(
            self.project, Path(projection["root"]).name + "/delta/index.json")
        projected = json.loads(index_text)
        self.assertEqual(projected["attempts"], 1)
        self.assertEqual(projected["files"], [])

    def test_staged_deletion_has_a_reachable_staged_hunk(self):
        boundary = orc.capture_batch_boundary(
            self.project, self.rundir, "impl-staged-delete", batch_index=0,
            plan_version="v")
        subprocess.run(["git", "rm", "--cached", "-q", "app.py"],
                       cwd=self.project, check=True, capture_output=True)
        self.assertEqual((self.project / "app.py").read_text(), "value = 1\n")
        index_before = subprocess.run(
            ["git", "-C", str(self.project), "ls-files", "-s"],
            capture_output=True, text=True, check=True).stdout
        result = orc.finalize_batch_delta(
            self.project, self.rundir, "impl-staged-delete", boundary,
            final_snapshot=orc.source_snapshot(self.project), attempt=1)
        entry = next(item for item in result["paths"] if item["path"] == "app.py")
        self.assertTrue(entry["index_changed_in_window"])
        self.assertTrue(entry["index_deleted"])
        self.assertEqual(entry["index_after"], "absent")
        self.assertEqual(entry["presence_after"], "file")
        staged = [hunk for hunk in entry["hunks"] if hunk["scope"] == "index"]
        self.assertEqual(len(staged), 1)
        text = (Path(result["hunks_dir"]) / Path(staged[0]["path"]).name).read_text()
        self.assertIn("-value = 1", text)
        index_after = subprocess.run(
            ["git", "-C", str(self.project), "ls-files", "-s"],
            capture_output=True, text=True, check=True).stdout
        self.assertEqual(index_before, index_after)
        state = self.saved(self.state(
            phase="review", plan=self.plan(),
            plan_version=orc.content_hash(self.plan())))
        state["plan_version"] = orc.content_hash(state["plan"])
        state["batch_deltas"] = [{
            "attempt": 1, "job_id": "impl-staged-delete", "batch_index": 0,
            "plan_version": state["plan_version"], "complete": True,
            "hunks_dir": result["hunks_dir"], "paths": result["paths"],
            "limitations": result["limitations"]}]
        projection, rejection = self._projection(state)
        self.assertIsNone(rejection)
        names = [name for name in projection["files"] if name.endswith(".patch")]
        projected = [orc.read_review_projection(
            self.project, Path(projection["root"]).name + "/" + name)
            for name in names]
        self.assertTrue(any("-value = 1" in text for text in projected))
        self.assertEqual(subprocess.run(
            ["git", "-C", str(self.project), "ls-files", "-s"],
            capture_output=True, text=True, check=True).stdout, index_after)

    def test_already_staged_and_empty_deletions_are_explicit(self):
        (self.project / "empty.txt").write_text("")
        self._commit("add empty")
        subprocess.run(["git", "rm", "--cached", "-q", "empty.txt"],
                       cwd=self.project, check=True, capture_output=True)
        (self.project / "app.py").unlink()
        subprocess.run(["git", "rm", "--cached", "-q", "app.py"],
                       cwd=self.project, check=True, capture_output=True)
        boundary = orc.capture_batch_boundary(
            self.project, self.rundir, "impl-predelete", batch_index=0,
            plan_version="v")
        result = orc.finalize_batch_delta(
            self.project, self.rundir, "impl-predelete", boundary,
            final_snapshot=orc.source_snapshot(self.project), attempt=1)
        entries = {item["path"]: item for item in result["paths"]}
        self.assertTrue(entries["app.py"]["index_pre_existing"])
        self.assertTrue(entries["app.py"]["index_deleted"])
        self.assertEqual(entries["app.py"]["index_hunks"][0]["scope"],
                         "index_pre_existing")
        self.assertTrue(entries["empty.txt"]["index_deleted"])
        self.assertTrue(entries["empty.txt"]["index_deletion"]["empty"])
        self.assertFalse(entries["empty.txt"]["index_hunks"])

    def test_uncaptured_staged_bytes_are_not_a_window_change(self):
        (self.project / "aaa.py").write_text("writer baseline\n")
        (self.project / "zzz_staged.py").write_text("pre-existing staged\n")
        subprocess.run(["git", "add", "zzz_staged.py"], cwd=self.project,
                       check=True, capture_output=True)
        with patch.object(orc, "DELTA_MAX_PATHS", 1):
            boundary = orc.capture_batch_boundary(
                self.project, self.rundir, "impl-cap", batch_index=0,
                plan_version="v")
        self.assertIn("zzz_staged.py", boundary["omitted_paths"])
        (self.project / "aaa.py").write_text("writer changed\n")
        (self.project / "zzz_staged.py").write_text("writer also touched\n")
        result = orc.finalize_batch_delta(
            self.project, self.rundir, "impl-cap", boundary,
            final_snapshot=orc.source_snapshot(self.project), attempt=1)
        entry = next(item for item in result["paths"]
                     if item["path"] == "zzz_staged.py")
        self.assertEqual(entry["index_comparison"], "unavailable")
        self.assertFalse(entry.get("index_changed_in_window"))
        self.assertFalse(entry.get("hunks"))
        self.assertTrue(any(item.get("reason") == "dispatch index state not captured"
                            for item in result["limitations"]))
        state = self.saved(self.state(
            phase="review", plan=self.plan(),
            plan_version=orc.content_hash(self.plan())))
        state["plan_version"] = orc.content_hash(state["plan"])
        state["batch_deltas"] = [{
            "attempt": 1, "job_id": "impl-cap", "batch_index": 0,
            "plan_version": state["plan_version"], "complete": True,
            "hunks_dir": result["hunks_dir"], "paths": result["paths"],
            "limitations": result["limitations"]}]
        projection, rejection = self._projection(state)
        self.assertIsNone(rejection)
        self.assertTrue(any("dispatch index state not captured"
                            in item.get("reason", "")
                            for item in projection["limitations"]))
        patched = [orc.read_review_projection(
            self.project, Path(projection["root"]).name + "/" + name)
            for name in projection["files"] if name.endswith(".patch")]
        self.assertFalse(any("pre-existing staged" in text for text in patched))
        staged = subprocess.run(
            ["git", "-C", str(self.project), "show", ":zzz_staged.py"],
            capture_output=True, text=True, check=True).stdout
        self.assertEqual(staged, "pre-existing staged\n")

    def test_unavailable_index_before_image_stays_explicit(self):
        (self.project / "app.py").write_text("value = 2\n")
        subprocess.run(["git", "add", "app.py"], cwd=self.project, check=True,
                       capture_output=True)
        (self.project / "app.py").write_text("value = 1\n")
        boundary = orc.capture_batch_boundary(
            self.project, self.rundir, "impl-index-lost", batch_index=0,
            plan_version="v")
        manifest = orc.read_json(Path(boundary["dir"]) / "manifest.json")
        blob = manifest["entries"]["app.py"]["index"]["blob"]
        Path(blob).unlink()
        result = orc.finalize_batch_delta(
            self.project, self.rundir, "impl-index-lost", boundary,
            final_snapshot=orc.source_snapshot(self.project), attempt=1)
        entry = next(item for item in result["paths"] if item["path"] == "app.py")
        self.assertEqual(entry["index_unavailable"],
                         "index_before_bytes_unavailable")
        self.assertEqual(entry["index_hunks"], [])
        self.assertFalse(any(hunk["scope"].startswith("index")
                             for hunk in entry.get("hunks") or []))

    def test_unchanged_ignored_runtime_input_keeps_continuity(self):
        exclude = self.project / ".git" / "info" / "exclude"
        exclude.write_text("local_override.py\n")
        runtime = self.project / "local_override.py"
        runtime.write_text("VALUE = 1\n")
        first = orc.capture_batch_boundary(
            self.project, self.rundir, "chain-r03-1", batch_index=0,
            plan_version="v")
        self.assertEqual(first["source_signature_projection"],
                         orc.SOURCE_IDENTITY_PROJECTION)
        first_result = orc.finalize_batch_delta(
            self.project, self.rundir, "chain-r03-1", first,
            final_snapshot=orc.source_snapshot(self.project), attempt=1)
        self.assertEqual(first_result["final_snapshot_signature_projection"],
                         orc.SOURCE_IDENTITY_PROJECTION)
        second = orc.capture_batch_boundary(
            self.project, self.rundir, "chain-r03-2", batch_index=0,
            plan_version="v", previous_job_id="chain-r03-1")
        result = orc.finalize_batch_delta(
            self.project, self.rundir, "chain-r03-2", second,
            final_snapshot=orc.source_snapshot(self.project), attempt=2)
        self.assertEqual(result["attempt_chain"]["status"], "continuous")
        self.assertFalse(any("unaccounted changes between writer windows"
                             in item["reason"] for item in result["limitations"]))

    def test_runtime_input_change_between_attempts_is_not_discarded(self):
        exclude = self.project / ".git" / "info" / "exclude"
        exclude.write_text("local_override.py\n")
        runtime = self.project / "local_override.py"
        runtime.write_text("VALUE = 1\n")
        first = orc.capture_batch_boundary(
            self.project, self.rundir, "chain-r03-a", batch_index=0,
            plan_version="v")
        orc.finalize_batch_delta(
            self.project, self.rundir, "chain-r03-a", first,
            final_snapshot=orc.source_snapshot(self.project), attempt=1)
        runtime.write_text("VALUE = 2\n")
        second = orc.capture_batch_boundary(
            self.project, self.rundir, "chain-r03-b", batch_index=0,
            plan_version="v", previous_job_id="chain-r03-a")
        result = orc.finalize_batch_delta(
            self.project, self.rundir, "chain-r03-b", second,
            final_snapshot=orc.source_snapshot(self.project), attempt=2)
        self.assertEqual(result["attempt_chain"]["status"],
                         "unaccounted_changes")
        self.assertTrue(any(item.get("evidence") == "worktree_content"
                            for item in result["attempt_chain"]["mismatches"]))
        self.assertTrue(any("unaccounted changes between writer windows"
                            in item["reason"] for item in result["limitations"]))

    def test_incompatible_historical_identity_is_uncertainty(self):
        first = orc.capture_batch_boundary(
            self.project, self.rundir, "chain-r03-old", batch_index=0,
            plan_version="v")
        orc.finalize_batch_delta(
            self.project, self.rundir, "chain-r03-old", first,
            final_snapshot=orc.source_snapshot(self.project), attempt=1)
        index_path = Path(first["dir"]).parent / "after" / "index.json"
        value = orc.read_json(index_path)
        value.pop("final_snapshot_signature_projection", None)
        value["index_sha256"] = orc.content_hash(
            {key: item for key, item in value.items() if key != "index_sha256"})
        orc.atomic_json(index_path, value)
        second = orc.capture_batch_boundary(
            self.project, self.rundir, "chain-r03-new", batch_index=0,
            plan_version="v", previous_job_id="chain-r03-old")
        result = orc.finalize_batch_delta(
            self.project, self.rundir, "chain-r03-new", second,
            final_snapshot=orc.source_snapshot(self.project), attempt=2)
        self.assertEqual(result["attempt_chain"]["status"], "incomplete")
        self.assertTrue(any(item.get("reason") ==
                            "source identity projection unavailable"
                            for item in result["limitations"]))

    # -- recovered Reviewer reuse -----------------------------------------
    def _reviewer_job(self, state, projection):
        jobdir = self.rundir / "jobs" / "reviewer-recovered-r03"
        jobdir.mkdir(parents=True, exist_ok=True)
        snapshot = orc.source_snapshot(self.project)
        orc.atomic_json(jobdir / "dispatch.json", {
            "kind": "reviewer", "role": "reviewer", "source": snapshot,
            "review_packet": projection["binding"],
            "dispatch_evidence": projection})
        orc.atomic_json(jobdir / "completion.json",
                        {"final_snapshot": snapshot, "session_id": "ses-rv"})
        orc.atomic_json(jobdir / "report.json", {
            "contract_version": 2, "status": "complete",
            "summary": "recovered review", "findings": [], "files": ["app.py"],
            "tests": [], "evidence": ["app.py:1"], "unknowns": [],
            "blocker": ""})
        orc.atomic_json(jobdir / "execution.json", {"returncode": 0})
        state["active_job"] = {
            "id": "reviewer-recovered-r03", "kind": "reviewer",
            "role": "reviewer", "path": str(jobdir), "status": "running",
            **baseline.dead_process_identity()}
        return jobdir

    def test_recovered_reviewer_restores_its_packet_identity(self):
        plan = self.plan()
        state = self.saved(self.state(phase="review", plan=plan,
                                      plan_version=orc.content_hash(plan)))
        projection, rejection = self._projection(state)
        self.assertIsNone(rejection)
        self._reviewer_job(state, projection)
        orc.save(self.rundir, state)
        self.assertTrue(orc.recover_finished_dispatch(self.rundir, state))
        job = state["completed_jobs"][-1]
        self.assertEqual(job["review_projection_sha256"],
                         projection["projection_sha256"])
        self.assertEqual(job["review_verification_sha256"],
                         projection["verification_sha256"])
        self.assertTrue(orc.packet_binding_matches(job["review_packet_binding"],
                                                   projection))

    def test_valid_recovered_review_is_reused_without_a_model_call(self):
        plan = self.plan()
        state = self.saved(self.state(phase="review", plan=plan,
                                      plan_version=orc.content_hash(plan)))
        package = self._package()
        projection, rejection = self._projection(state, package)
        self.assertIsNone(rejection)
        self._reviewer_job(state, projection)
        state["review_projection"] = projection
        orc.save(self.rundir, state)
        self.assertTrue(orc.recover_finished_dispatch(self.rundir, state))
        state = self.state_file()
        with patch.object(orc, "review_verification_admission",
                          return_value=(plan["batches"][0], package)):
            with patch.object(orc, "call_model") as model:
                orc.advance(self.rundir, state, self.cfg)
                model.assert_not_called()
        self.assertEqual(self.state_file()["review"]["summary"],
                         "recovered review")
        self.assertEqual(self.state_file()["phase"], "accept")

    def test_recovered_review_is_rejected_after_verification_changes(self):
        plan = self.plan()
        state = self.saved(self.state(phase="review", plan=plan,
                                      plan_version=orc.content_hash(plan)))
        old_package = self._package("verify-r03-old")
        projection, rejection = self._projection(state, old_package)
        self.assertIsNone(rejection)
        self._reviewer_job(state, projection)
        state["review_projection"] = projection
        orc.save(self.rundir, state)
        self.assertTrue(orc.recover_finished_dispatch(self.rundir, state))
        state = self.state_file()
        new_package = self._package("verify-r03-new")
        fresh = {"contract_version": 2, "status": "complete",
                 "summary": "fresh review", "findings": [], "files": ["app.py"],
                 "tests": [], "evidence": ["app.py:1"], "unknowns": [],
                 "blocker": ""}
        with patch.object(orc, "review_verification_admission",
                          return_value=(plan["batches"][0], new_package)):
            with patch.object(orc, "call_model",
                              return_value=(fresh, {"id": "fresh-r03"})) as model:
                orc.advance(self.rundir, state, self.cfg)
                self.assertEqual(model.call_count, 1)
        updated = self.state_file()
        self.assertEqual(updated["review"]["summary"], "fresh review")
        self.assertEqual(updated["stale_cached_review"]["job_id"],
                         "reviewer-recovered-r03")


    def test_recovered_implementer_report_attribution_is_exact_or_limited(self):
        state = self.saved(self.state(phase="implement", plan=self.plan()))
        job_id = "impl-report-recovered"
        jobdir, boundary = self._implementer_job(job_id)
        job = {"id": job_id, "kind": "implementer", "role": "implementer",
               "path": str(jobdir)}
        state["failed_jobs"] = [job]
        state["report_recoveries"] = [{
            "job_id": job_id, "kind": "implementer",
            "source_signature": boundary["source_signature"]}]
        exact = orc._record_recovered_writer_attempt(
            self.rundir, state, self.project, job)
        self.assertTrue(exact["complete"])
        self.assertEqual(exact["paths"], [])
        # A report whose source cannot be tied to the dispatch boundary must
        # not be presented as a proven clean window.
        other = self.saved(self.state(phase="implement", plan=self.plan()))
        other_job = {"id": "impl-report-moved", "kind": "implementer",
                     "role": "implementer", "path": str(jobdir)}
        other["failed_jobs"] = [other_job]
        other["report_recoveries"] = [{
            "job_id": "impl-report-moved", "kind": "implementer",
            "source_signature": "different-source"}]
        limited = orc._record_recovered_writer_attempt(
            self.rundir, other, self.project, other_job)
        self.assertFalse(limited["complete"])
        self.assertEqual(limited["paths"], [])
        self.assertTrue(any(item["reason"] in {
            "writer attempt evidence unavailable",
            "writer completion not attested"}
            for item in limited["limitations"]))
        self.assertTrue(any(item.get("detail") for item in limited["limitations"]))

    def test_recovered_reviewer_with_invalid_packet_keeps_reuse_rejected(self):
        plan = self.plan()
        state = self.saved(self.state(phase="review", plan=plan,
                                      plan_version=orc.content_hash(plan)))
        projection, rejection = self._projection(state)
        self.assertIsNone(rejection)
        self._reviewer_job(state, projection)
        # The packet must still be exactly valid at recovery time.
        manifest = Path(projection["manifest"])
        manifest.write_text("{}\n")
        orc.save(self.rundir, state)
        self.assertTrue(orc.recover_finished_dispatch(self.rundir, state))
        job = state["completed_jobs"][-1]
        self.assertIsNone(job.get("review_projection_sha256"))
        self.assertIsNone(job.get("review_packet_binding"))


class BatchCorrectionsR04Tests(ReleaseFixture):
    """Writer-delta records must be bound to an attested completion."""

    def _package(self, sha="verify-r04"):
        return {"commands": [], "passed": True, "source_unchanged": True,
                "candidate_hash": orc.signature(
                    orc.source_snapshot(self.project)),
                "verification_path": str(self.root / f"{sha}.json"),
                "verification_sha256": sha, "evidence_version": 2}

    def _projection(self, state):
        return orc.prepare_review_projection(
            self.rundir, state, self.cfg, self.project,
            state["plan"]["batches"][0], self._package())

    def _boundary_and_state(self, job_id):
        state = self.saved(self.state(phase="implement", plan=self.plan(),
                                      plan_version=orc.content_hash(self.plan())))
        boundary = orc.capture_batch_boundary(
            self.project, self.rundir, job_id, batch_index=0,
            plan_version=state["plan_version"])
        return state, boundary

    def test_missing_completion_is_counted_and_reviewer_visible(self):
        job_id = "impl-no-completion-r04"
        state, boundary = self._boundary_and_state(job_id)
        (self.project / "app.py").write_text("value = 4\n")
        record = orc._record_batch_delta(
            self.rundir, state, self.project, job_id, boundary, None,
            phase="failure")
        self.assertFalse(record["complete"])
        self.assertEqual(record["paths"], [])
        self.assertTrue(any(item["reason"] == "writer completion not attested"
                            for item in record["limitations"]))
        delta = orc.batch_delta_index(state)
        self.assertEqual(delta["attempts"], 1)
        self.assertEqual(len(delta["incomplete_writer_attempts"]), 1)
        state["phase"] = "review"
        projection, rejection = self._projection(state)
        self.assertIsNone(rejection)
        self.assertTrue(any("writer completion not attested"
                            in item.get("reason", "")
                            for item in projection["limitations"]))
        index_text = orc.read_review_projection(
            self.project, Path(projection["root"]).name + "/delta/index.json")
        self.assertEqual(json.loads(index_text)["files"], [])

    def test_valid_retained_index_is_reused_with_its_hunk(self):
        job_id = "impl-retained-r04"
        state, boundary = self._boundary_and_state(job_id)
        (self.project / "app.py").write_text("value = 5\n")
        snapshot = orc.source_snapshot(self.project)
        publisher = copy.deepcopy(state)
        retained = orc._record_batch_delta(
            self.rundir, publisher, self.project, job_id, boundary,
            snapshot, phase="completion")
        record = orc._record_batch_delta(
            self.rundir, state, self.project, job_id, boundary, snapshot,
            phase="completion")
        self.assertTrue(record["complete"])
        self.assertEqual(record["index_sha256"], retained["index_sha256"])
        entry = next(item for item in record["paths"] if item["path"] == "app.py")
        text = (Path(record["hunks_dir"])
                / Path(entry["hunks"][0]["path"]).name).read_text()
        self.assertIn("+value = 5", text)

    def test_retained_index_for_wrong_completion_is_not_reused(self):
        job_id = "impl-wrong-completion-r04"
        state, boundary = self._boundary_and_state(job_id)
        (self.project / "app.py").write_text("value = 6\n")
        stale_snapshot = orc.source_snapshot(self.project)
        publisher = copy.deepcopy(state)
        stale = orc._record_batch_delta(
            self.rundir, publisher, self.project, job_id, boundary,
            stale_snapshot, phase="completion")
        (self.project / "app.py").write_text("value = 8\n")
        current = orc.source_snapshot(self.project)
        value, problem = orc._reusable_delta_index(
            self.rundir, job_id, boundary, current, 1)
        self.assertIsNone(value)
        self.assertIn("completion_signature", problem)
        record = orc._record_batch_delta(
            self.rundir, state, self.project, job_id, boundary, current,
            phase="completion")
        self.assertTrue(record["complete"])
        self.assertNotEqual(record["index_sha256"], stale["index_sha256"])
        index_value = orc.read_json(Path(record["index_path"]))
        self.assertEqual(index_value["final_snapshot_signature"],
                         orc.signature(current))
        entry = next(item for item in record["paths"] if item["path"] == "app.py")
        text = (Path(record["hunks_dir"])
                / Path(entry["hunks"][0]["path"]).name).read_text()
        self.assertIn("+value = 8", text)

    def test_tampered_retained_hunk_is_not_accepted_as_complete(self):
        job_id = "impl-tampered-hunk-r04"
        state, boundary = self._boundary_and_state(job_id)
        (self.project / "app.py").write_text("value = 9\n")
        snapshot = orc.source_snapshot(self.project)
        publisher = copy.deepcopy(state)
        retained = orc._record_batch_delta(
            self.rundir, publisher, self.project, job_id, boundary,
            snapshot, phase="completion")
        hunk = next(h for item in retained["paths"] for h in item["hunks"])
        artifact = Path(retained["hunks_dir"]) / Path(hunk["path"]).name
        artifact.write_text("tampered\n")
        value, problem = orc._reusable_delta_index(
            self.rundir, job_id, boundary, snapshot, 1)
        self.assertIsNone(value)
        self.assertIn("delta hunk", problem)
        record = orc._record_batch_delta(
            self.rundir, state, self.project, job_id, boundary, snapshot,
            phase="completion")
        self.assertTrue(record["complete"])
        rebuilt = Path(record["hunks_dir"]) / Path(hunk["path"]).name
        self.assertIn("+value = 9", rebuilt.read_text())

    def test_failed_guard_attempt_binds_delta_after_stop(self):
        job_id = None
        state = self.saved(self.state(phase="implement", plan=self.plan()))
        state["model_routes"]["implementer"] = {
            "provider": "codex", "model": "gpt-6-luna",
            "effort": "medium", "billing": "subscription"}
        self.saved(state)
        fake = self.bin / "codex"
        fake.write_text(
            "#!/usr/bin/env python3\n"
            "from pathlib import Path\n"
            "Path('app.py').write_text('value = 11\\n')\n"
            "raise SystemExit(1)\n")
        fake.chmod(0o755)
        with patch.dict(os.environ, {
                "PATH": str(self.bin) + ":" + os.environ.get("PATH", "")}):
            with self.assertRaises(RuntimeError):
                orc.call_model(self.rundir, state, self.cfg, "implementer",
                               "implementer", "task", self.project)
        records = [item for item in state.get("batch_deltas", [])
                   if item.get("phase") == "failure"]
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertTrue(record["complete"])
        entry = next(item for item in record["paths"] if item["path"] == "app.py")
        text = (Path(record["hunks_dir"])
                / Path(entry["hunks"][0]["path"]).name).read_text()
        self.assertIn("+value = 11", text)

    def test_unproven_stop_does_not_record_complete_evidence(self):
        state = self.saved(self.state(phase="implement", plan=self.plan()))
        state["model_routes"]["implementer"] = {
            "provider": "codex", "model": "gpt-6-luna",
            "effort": "medium", "billing": "subscription"}
        self.saved(state)
        fake = self.bin / "codex"
        fake.write_text(
            "#!/usr/bin/env python3\n"
            "from pathlib import Path\n"
            "Path('app.py').write_text('value = 12\\n')\n"
            "raise SystemExit(1)\n")
        fake.chmod(0o755)
        unproven = {"stopped": False, "reasons": ["synthetic survivor"],
                    "survivors": [{"pid": 999999}],
                    "liveness": {"alive": None, "reason": "synthetic"}}
        with patch.dict(os.environ, {
                "PATH": str(self.bin) + ":" + os.environ.get("PATH", "")}), \
                patch.object(orc, "inspect_execution", return_value=unproven):
            with self.assertRaises(RuntimeError):
                orc.call_model(self.rundir, state, self.cfg, "implementer",
                               "implementer", "task", self.project)
        self.assertFalse(any(item.get("phase") == "failure"
                             and item.get("complete", True)
                             for item in state.get("batch_deltas", [])))


class BatchCorrectionsR05Tests(ReleaseFixture):
    """Rebuilt deltas must be sampled at the recorded completion identity."""

    def _package(self, sha="verify-r05"):
        return {"commands": [], "passed": True, "source_unchanged": True,
                "candidate_hash": orc.signature(
                    orc.source_snapshot(self.project)),
                "verification_path": str(self.root / f"{sha}.json"),
                "verification_sha256": sha, "evidence_version": 2}

    def _projection(self, state):
        return orc.prepare_review_projection(
            self.rundir, state, self.cfg, self.project,
            state["plan"]["batches"][0], self._package())

    def _state_and_boundary(self, job_id):
        state = self.saved(self.state(
            phase="implement", plan=self.plan(),
            plan_version=orc.content_hash(self.plan())))
        boundary = orc.capture_batch_boundary(
            self.project, self.rundir, job_id, batch_index=0,
            plan_version=state["plan_version"])
        return state, boundary

    def _assert_incomplete_review_limitation(self, state, record, reason,
                                             forbidden=None):
        self.assertFalse(record["complete"])
        self.assertEqual(record["paths"], [])
        self.assertTrue(any(item["reason"] == reason
                            for item in record["limitations"]))
        delta = orc.batch_delta_index(state)
        self.assertEqual(delta["attempts"], 1)
        self.assertEqual(len(delta["incomplete_writer_attempts"]), 1)
        state["phase"] = "review"
        projection, rejection = self._projection(state)
        self.assertIsNone(rejection)
        self.assertTrue(any(item.get("reason") == reason
                            for item in projection["limitations"]))
        projected = [orc.read_review_projection(
            self.project, Path(projection["root"]).name + "/" + name)
            for name in projection["files"] if name.endswith(".patch")]
        if forbidden is not None:
            self.assertFalse(any(forbidden in text for text in projected))
        index_text = orc.read_review_projection(
            self.project, Path(projection["root"]).name + "/delta/index.json")
        self.assertEqual(json.loads(index_text)["files"], [])

    def test_pre_rebuild_drift_is_not_attributed_to_the_completion(self):
        job_id = "impl-pre-drift-r05"
        state, boundary = self._state_and_boundary(job_id)
        (self.project / "app.py").write_text("value = 2\n")
        recorded_completion = orc.source_snapshot(self.project)
        (self.project / "app.py").write_text("value = 3\n")
        record = orc._record_batch_delta(
            self.rundir, state, self.project, job_id, boundary,
            recorded_completion, phase="completion")
        self._assert_incomplete_review_limitation(
            state, record, "writer delta reconstruction not attributable",
            forbidden="+value = 3")
        self.assertTrue(any("does not match the recorded writer completion"
                            in item["detail"]
                            for item in record["limitations"]))
        self.assertFalse((Path(boundary["dir"]).parent / "after"
                          / "index.json").exists())
        self.assertEqual((self.project / "app.py").read_text(), "value = 3\n")

    def test_write_during_reconstruction_is_detected_and_never_reusable(self):
        job_id = "impl-mid-drift-r05"
        state, boundary = self._state_and_boundary(job_id)
        (self.project / "app.py").write_text("value = 2\n")
        recorded_completion = orc.source_snapshot(self.project)
        real_finalize = orc.finalize_batch_delta

        def drifting_finalize(*args, **kwargs):
            value = real_finalize(*args, **kwargs)
            (self.project / "app.py").write_text("value = 4\n")
            return value

        with patch.object(orc, "finalize_batch_delta",
                          side_effect=drifting_finalize):
            record = orc._record_batch_delta(
                self.rundir, state, self.project, job_id, boundary,
                recorded_completion, phase="completion")
        self._assert_incomplete_review_limitation(
            state, record, "writer delta reconstruction not attributable",
            forbidden="+value = 4")
        self.assertTrue(any("source changed during delta reconstruction"
                            in item["detail"]
                            for item in record["limitations"]))
        canonical = Path(boundary["dir"]).parent / "after" / "index.json"
        self.assertFalse(canonical.exists())
        provisional = list(canonical.parent.glob("staging-*/index.json"))
        self.assertEqual(len(provisional), 1)
        reusable, _problem = orc._reusable_delta_index(
            self.rundir, job_id, boundary, recorded_completion, 1)
        self.assertIsNone(reusable)
        self.assertEqual((self.project / "app.py").read_text(), "value = 4\n")

    def test_unchanged_reconstruction_projects_the_correct_hunk(self):
        job_id = "impl-clean-rebuild-r05"
        state, boundary = self._state_and_boundary(job_id)
        (self.project / "app.py").write_text("value = 2\n")
        completion = orc.source_snapshot(self.project)
        record = orc._record_batch_delta(
            self.rundir, state, self.project, job_id, boundary,
            completion, phase="completion")
        self.assertTrue(record["complete"])
        self.assertEqual(record["limitations"], [])
        entry = next(item for item in record["paths"] if item["path"] == "app.py")
        hunk_text = (Path(record["hunks_dir"])
                     / Path(entry["hunks"][0]["path"]).name).read_text()
        self.assertIn("+value = 2", hunk_text)
        state["phase"] = "review"
        projection, rejection = self._projection(state)
        self.assertIsNone(rejection)
        patches = [name for name in projection["files"]
                   if name.endswith(".patch")]
        projected = [orc.read_review_projection(
            self.project, Path(projection["root"]).name + "/" + name)
            for name in patches]
        self.assertTrue(any("+value = 2" in text for text in projected))
        self.assertFalse(any("+value = 3" in text for text in projected))
        delta = orc.batch_delta_index(state)
        self.assertEqual(delta["attempts"], 1)
        self.assertFalse(delta["incomplete_writer_attempts"])


class BatchCorrectionsR06Tests(ReleaseFixture):
    """Crash-safe delta publication at the three interruption boundaries."""

    def _package(self, sha="verify-r06"):
        return {"commands": [], "passed": True, "source_unchanged": True,
                "candidate_hash": orc.signature(
                    orc.source_snapshot(self.project)),
                "verification_path": str(self.root / f"{sha}.json"),
                "verification_sha256": sha, "evidence_version": 2}

    def _projection(self, state):
        return orc.prepare_review_projection(
            self.rundir, state, self.cfg, self.project,
            state["plan"]["batches"][0], self._package())

    def _state_and_boundary(self, job_id):
        state = self.saved(self.state(
            phase="implement", plan=self.plan(),
            plan_version=orc.content_hash(self.plan())))
        boundary = orc.capture_batch_boundary(
            self.project, self.rundir, job_id, batch_index=0,
            plan_version=state["plan_version"])
        return state, boundary

    def _canonical_index(self, boundary):
        return Path(boundary["dir"]).parent / "after" / "index.json"

    def _provisional_indexes(self, boundary):
        return sorted((Path(boundary["dir"]).parent / "after")
                      .glob("staging-*/index.json"))

    def _hunk_text(self, index_value):
        texts = []
        for item in index_value.get("paths") or []:
            for hunk in item.get("hunks") or []:
                texts.append((Path(index_value["hunks_dir"])
                              / Path(hunk["path"]).name).read_text())
        return "\n".join(texts)

    def _projected_hunks(self, state):
        state["phase"] = "review"
        projection, rejection = self._projection(state)
        self.assertIsNone(rejection)
        texts = [orc.read_review_projection(
            self.project, Path(projection["root"]).name + "/" + name)
            for name in projection["files"] if name.endswith(".patch")]
        return projection, "\n".join(texts)

    def test_crash_after_staging_before_post_check_never_publishes_drift(self):
        job_id = "impl-crash-staging-r06"
        state, boundary = self._state_and_boundary(job_id)
        (self.project / "app.py").write_text("value = 2\n")
        completion = orc.source_snapshot(self.project)
        real_finalize = orc.finalize_batch_delta

        def drifting_then_crash(*args, **kwargs):
            # Drift during reconstruction, then stop before r05's post check.
            (self.project / "app.py").write_text("value = 3\n")
            real_finalize(*args, **kwargs)
            raise RuntimeError("simulated crash after provisional index write")

        with patch.object(orc, "finalize_batch_delta",
                          side_effect=drifting_then_crash):
            with self.assertRaises(RuntimeError):
                orc._record_batch_delta(
                    self.rundir, state, self.project, job_id, boundary,
                    completion, phase="completion")
        self.assertFalse(self._canonical_index(boundary).exists())
        provisional = self._provisional_indexes(boundary)
        self.assertEqual(len(provisional), 1)
        staged = orc.read_json(provisional[0])
        self.assertIn("+value = 3", self._hunk_text(staged))
        self.assertEqual(state.get("batch_deltas", []), [])
        # A provisional index is invisible to the durable reuse path.
        reusable, _problem = orc._reusable_delta_index(
            self.rundir, job_id, boundary, completion, 1)
        self.assertIsNone(reusable)
        # User restores the recorded completion and recovery resumes.
        (self.project / "app.py").write_text("value = 2\n")
        record = orc._record_batch_delta(
            self.rundir, state, self.project, job_id, boundary,
            completion, phase="recovery")
        self.assertTrue(record["complete"])
        self.assertTrue(self._canonical_index(boundary).exists())
        self.assertIn("+value = 2", self._hunk_text(orc.read_json(
            self._canonical_index(boundary))))
        _projection, projected = self._projected_hunks(state)
        self.assertIn("+value = 2", projected)
        self.assertNotIn("+value = 3", projected)

    def test_crash_after_validation_before_publish_leaves_only_staging(self):
        job_id = "impl-crash-publish-r06"
        state, boundary = self._state_and_boundary(job_id)
        (self.project / "app.py").write_text("value = 2\n")
        completion = orc.source_snapshot(self.project)
        with patch.object(orc, "_attest_and_publish_delta_index",
                          side_effect=RuntimeError("simulated crash before publish")):
            with self.assertRaises(RuntimeError):
                orc._record_batch_delta(
                    self.rundir, state, self.project, job_id, boundary,
                    completion, phase="completion")
        self.assertFalse(self._canonical_index(boundary).exists())
        self.assertEqual(len(self._provisional_indexes(boundary)), 1)
        self.assertEqual(state.get("batch_deltas", []), [])
        record = orc._record_batch_delta(
            self.rundir, state, self.project, job_id, boundary,
            completion, phase="recovery")
        self.assertTrue(record["complete"])
        published = orc.read_json(self._canonical_index(boundary))
        self.assertIn("attestation", published)
        self.assertEqual(published["attestation"]["completion_signature"],
                         orc.signature(completion))
        self.assertIn("+value = 2", self._hunk_text(published))

    def test_crash_after_publish_before_state_commit_reuses_attested_index(self):
        job_id = "impl-crash-state-r06"
        state, boundary = self._state_and_boundary(job_id)
        (self.project / "app.py").write_text("value = 2\n")
        completion = orc.source_snapshot(self.project)
        publisher = copy.deepcopy(state)
        published = orc._record_batch_delta(
            self.rundir, publisher, self.project, job_id, boundary,
            completion, phase="completion")
        self.assertTrue(published["complete"])
        canonical = orc.read_json(self._canonical_index(boundary))
        self.assertIn("attestation", canonical)
        # The state commit never happened; recovery must reuse the exact index.
        self.assertEqual(state.get("batch_deltas", []), [])
        record = orc._record_batch_delta(
            self.rundir, state, self.project, job_id, boundary,
            completion, phase="recovery")
        self.assertTrue(record["complete"])
        self.assertEqual(record["index_sha256"], published["index_sha256"])
        self.assertEqual(len([item for item in state["batch_deltas"]
                              if item.get("job_id") == job_id]), 1)
        _projection, projected = self._projected_hunks(state)
        self.assertIn("+value = 2", projected)
        self.assertNotIn("+value = 3", projected)

    def test_unattested_prior_format_index_is_rebuilt_not_trusted(self):
        job_id = "impl-legacy-index-r06"
        state, boundary = self._state_and_boundary(job_id)
        (self.project / "app.py").write_text("value = 2\n")
        completion = orc.source_snapshot(self.project)
        legacy = orc.finalize_batch_delta(
            self.project, self.rundir, job_id, boundary,
            final_snapshot=completion, attempt=1)
        self.assertNotIn("attestation", legacy)
        reusable, problem = orc._reusable_delta_index(
            self.rundir, job_id, boundary, completion, 1)
        self.assertIsNone(reusable)
        self.assertIn("no durable attestation", problem)
        record = orc._record_batch_delta(
            self.rundir, state, self.project, job_id, boundary,
            completion, phase="recovery")
        self.assertTrue(record["complete"])
        published = orc.read_json(self._canonical_index(boundary))
        self.assertIn("attestation", published)
        self.assertIn("+value = 2", self._hunk_text(published))
        self.assertNotEqual(record["index_sha256"], legacy["index_sha256"])
        prior = list((Path(boundary["dir"]).parent / "after")
                     .glob("index.prior-*.json"))
        self.assertEqual(len(prior), 1)
        self.assertNotIn("attestation", orc.read_json(prior[0]))


if __name__ == "__main__":
    unittest.main()
