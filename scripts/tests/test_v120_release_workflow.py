"""Focused v1.2.0 release workflow gates (A–F).

These tests use the real supervisor transitions, the real guarded launcher and
fake CLI executables. They make no live model calls and never touch live state.
"""
from __future__ import annotations

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
        self.assertIsNotNone(orc.validate_planning_trial(cfg, "codex", True))
        with self.assertRaisesRegex(ValueError, "ordinary"):
            orc.validate_planning_trial(cfg, "codex", True, declared_risk="high")
        with self.assertRaisesRegex(ValueError, "Codex"):
            orc.validate_planning_trial(cfg, "claude", True)
        legacy = json.loads(json.dumps(cfg))
        legacy["architect"]["codex"]["model"] = "gpt-6.1-sol"
        with self.assertRaisesRegex(ValueError, "6.2"):
            orc.validate_planning_trial(legacy, "codex", True)

    def test_initial_plan_uses_medium_and_acceptance_stays_high(self):
        plan = self.plan(risk="ordinary")
        trial = orc.validate_planning_trial(self.cfg, "codex", True)
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
                             side_effect=lambda st, pr, refs: orc.source_snapshot(pr)), \
                patch.object(orc, "cached_decision_report", return_value=None):
            orc.advance(self.rundir, state, self.cfg)
        accept_calls = [call for call in calls if call[0] == "decision"]
        self.assertTrue(accept_calls)
        self.assertIsNone(accept_calls[-1][1])

    def test_high_risk_trial_plan_is_not_admitted(self):
        trial = orc.validate_planning_trial(self.cfg, "codex", True)
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
                             side_effect=lambda st, pr, refs: orc.source_snapshot(pr)), \
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
        self.assertIn("1.2.0", skill)
        # Safety-critical stop/resume guidance stays in the entry skill.
        self.assertIn("orchestrator_reconcile", skill)
        self.assertIn("Never claim a worker stopped", skill)


class ReleaseIdentityV120Tests(unittest.TestCase):
    def test_product_version_is_1_2_0_with_unchanged_internal_versions(self):
        info = orc.version_info()
        self.assertEqual(info["product_version"], "1.2.0")
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


if __name__ == "__main__":
    unittest.main()
