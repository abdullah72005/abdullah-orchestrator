"""v1.2.1 permission preflight and durable blocked-state recovery."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

import test_orchestrator as baseline

orc = baseline.orc


class PermissionRecoveryTests(unittest.TestCase):
    setUp = baseline.ControlTests.setUp
    tearDown = baseline.ControlTests.tearDown

    def test_structured_and_plaintext_prompt_detection_is_conservative(self):
        structured = orc._detect_permission_prompt(json.dumps({
            "type": "permission", "permission": "bash",
            "message": "The tool wants to run a command"}))
        self.assertEqual(structured["source"], "structured")
        self.assertIn("bash", structured["action"])
        plain = orc._detect_permission_prompt(
            "Error: authentication required. Run login first.",
            {"provider": "codex"})
        self.assertEqual(plain["source"], "documented_plaintext")
        # An OpenCode-looking arbitrary text line is never promoted to a prompt
        # without a structured record.
        self.assertIsNone(orc._detect_permission_prompt(
            "authentication required in a test assertion", {"provider": "opencode"}))
        self.assertIsNone(orc._detect_permission_prompt(
            json.dumps({"type": "tool_use", "part": {"tool": "bash"}}),
            {"provider": "opencode"}))

    def test_blocked_record_is_bounded_persisted_and_resumable(self):
        record = orc._record_permission_blocked(
            self.rundir, self.state, role="implementer", assignment="writer-a",
            action="run bash", reason="permission prompt for a new command")
        self.assertEqual(self.state["status"], "blocked")
        self.assertFalse(record["raw_text_persisted"])
        self.assertIn("orchestrator_resume", record["resume_step"])
        status = orc.status_run(self.state["id"])
        self.assertEqual(status["permission_blocked"]["action"], "run bash")
        self.assertIn("needs run bash", status["pause_reason"])
        recap = orc.recap_run(self.state["id"], detail="quick")
        self.assertIn("Permissions: blocked", recap["text"])
        resumed = orc.resume_run(self.state["id"])
        self.assertEqual(resumed["status"], "running")
        reloaded = orc.load(self.state["id"])[1]
        self.assertIsNone(reloaded["permission_blocked"])
        self.assertEqual(reloaded["resolved_permission_blocks"][0]["action"],
                         "run bash")

    def test_preflight_groups_route_check_and_skill_decisions(self):
        check = [["bash", "-c", "echo disguised"]]
        self.state.update({
            "id": "test-run00",
            "model_routes": {"implementer": {
                "provider": "opencode", "model": "gpt-5.2-codex",
                "billing": "api", "routing_fingerprint": "a" * 64}},
            "skill_assignments": {"roles": {"implementer": [{
                "name": "demo", "required_tools": ["definitely-not-installed-zz"]}]},
                "writers": {}},
            "plan": {"batches": [{"checks": check}]},
        })
        preflight = orc.permission_preflight(self.state, self.cfg, self.project)
        kinds = {item["kind"] for item in preflight["missing"]}
        self.assertIn("route_grant", kinds)
        self.assertIn("check_policy", kinds)
        self.assertIn("skill_tool", kinds)
        self.assertFalse(preflight["ok"])
        self.assertEqual(self.state["permission_preflight"]["version"], 1)

    def test_startup_shows_permission_and_parallel_inputs(self):
        skills_root = self.root / "skills"
        (skills_root / "demo").mkdir(parents=True)
        (skills_root / "demo" / "SKILL.md").write_text("demo\n", encoding="utf-8")
        self.with_skills = patch.dict(
            os.environ, {"ABDULLAH_SKILLS_ROOT": str(skills_root)})
        self.with_skills.start()
        self.addCleanup(self.with_skills.stop)
        self.state["status"] = "cancelled"
        orc.save(self.rundir, self.state)
        run, folder, state = orc.create_run(
            project=self.project, goal="explicit skills", host="codex",
            skip_doctor=True, skills={"implementer": ["demo"]},
            max_parallel_writers=2)
        self.assertEqual(state["parallel_permission"]["max_writers"], 2)
        self.assertEqual(state["parallel_permission"]["enabled"], True)
        self.assertEqual(state["skill_assignments"]["roles"]["implementer"][0]["name"],
                         "demo")
        self.assertIn("permission_preflight", state)
        self.assertEqual(state["skill_request"], {"implementer": ["demo"]})


class PermissionPreflightTests(unittest.TestCase):
    setUp = baseline.ControlTests.setUp
    tearDown = baseline.ControlTests.tearDown

    def test_default_subscription_and_go_routes_need_no_new_grant(self):
        self.state["model_routes"] = {
            "architect": {"provider": "codex", "model": "gpt", "effort": "high",
                          "billing": "subscription"},
            "implementer": {"provider": "opencode", "model": "opencode-go/x",
                            "effort": "low", "billing": "go",
                            "routing_fingerprint": "a" * 64},
            "reviewer": {"provider": "codex", "model": "gpt", "effort": "low",
                         "billing": "subscription"},
        }
        preflight = orc.permission_preflight(self.state, self.cfg, self.project)
        kinds = {item["kind"] for item in preflight["missing"]}
        self.assertNotIn("route_grant", kinds, preflight["missing"])

    def test_insufficient_known_grant_launches_zero_writers(self):
        route = {"provider": "opencode", "model": "opencode-go/x", "effort": "low",
                 "billing": "api", "routing_fingerprint": "b" * 64}
        self.state["model_routes"] = {"implementer": route}
        self.state["route_authorizations"] = [{
            "id": "grant-1", "role": "implementer",
            "route_sha256": orc.route_authorization_sha(route),
            "role_generation": 0, "used": 0, "max_dispatches": 1}]
        plan = {"contract_version": 2, "status": "complete", "summary": "plan",
                "invariants": ["Keep behavior"],
                "batches": [{"title": "feature", "goal": "change",
                             "acceptance": ["works"],
                             "checks": [[sys.executable, "-c", "raise SystemExit(0)"]],
                             "risk": "ordinary", "verification_purpose": None,
                             "repeat_checks": None,
                             "writers": [
                                 {"id": "a", "goal": "a", "paths": ["a.py"],
                                  "components": [], "completion_criteria": "a",
                                  "role": "implementer"},
                                 {"id": "b", "goal": "b", "paths": ["b.py"],
                                  "components": [], "completion_criteria": "b",
                                  "role": "implementer"}]}],
                "blocker": "", "required_exploration": {
                    "job_id": "", "scope_satisfied": True}}
        self.state.update({"plan": plan, "plan_version": orc.content_hash(plan),
                           "plan_revision": 1, "batch_index": 0,
                           "parallel_permission": {"max_writers": 2,
                                                   "enabled": True}})
        preflight = orc.permission_preflight(self.state, self.cfg, self.project)
        self.assertTrue(any(item["kind"] == "parallel_grant"
                            for item in preflight["missing"]), preflight["missing"])
        batch = plan["batches"][0]
        resolved = orc.resolve_parallel_batch(self.state, self.project, batch,
                                              run_dir=self.rundir)
        starts = []

        def must_not_run(*args, **kwargs):
            starts.append("model")
            raise AssertionError("a lane launched without enough grant authority")

        with patch.object(orc, "call_model", side_effect=must_not_run):
            result = orc.run_parallel_batch(
                self.rundir, self.state, self.cfg, self.project, batch, resolved,
                None)
        self.assertIsNone(result)
        self.assertEqual(starts, [])
        self.assertEqual(self.state["status"], "blocked")
        self.assertIn("no writer was started", self.state["pause_reason"])
        self.assertFalse(any((orr := orc._parallel_batch_dir(self.rundir, 0) / wid)
                             .exists() for wid in ("a", "b")))

    def test_plan_approval_and_resume_stop_on_known_missing_items(self):
        plan = {"contract_version": 2, "status": "complete", "summary": "plan",
                "invariants": ["Keep behavior"],
                "batches": [{"title": "feature", "goal": "change",
                             "acceptance": ["works"],
                             "checks": [["definitely-missing-check-zz"]],
                             "risk": "ordinary", "verification_purpose": None,
                             "repeat_checks": None, "writers": None}],
                "blocker": "", "required_exploration": {
                    "job_id": "", "scope_satisfied": True}}
        self.state.update({
            "plan": plan, "plan_version": orc.content_hash(plan),
            "plan_revision": 1, "status": "awaiting_plan_approval",
            "plan_authority": {"plan_version": orc.content_hash(plan),
                               "plan_revision": 1, "amendment_epoch": 0,
                               "authority_epoch": 0, "approved": False}})
        orc.save(self.rundir, self.state)
        launched = orc.modify_locked(self.rundir, self.state, "test-run00",
                                     "approve-plan")
        self.assertFalse(launched)
        self.assertEqual(self.state["status"], "blocked")
        self.assertIn("check_executable", self.state["pause_reason"])
        self.assertEqual(self.state["plan_authority"]["approved"], True)
        # The same grouped gate applies to resume after a block.
        orc.atomic_json(self.rundir / "control.json", {"action": "pause"})
        self.state["status"] = "blocked"
        orc.save(self.rundir, self.state)
        resumed = orc.modify_locked(self.rundir, self.state, "test-run00",
                                    "resume")
        self.assertFalse(resumed)
        self.assertEqual(self.state["status"], "blocked")
        self.assertFalse(self.state["permission_preflight"]["ok"])

    def test_check_prompt_is_detected_and_contained_before_the_deadline(self):
        code = ("import time; print('authentication required', flush=True); "
                "time.sleep(120)")
        self.state.update({"phase": "verify", "check_progress": None,
                           "active_check": None})
        orc.save(self.rundir, self.state)
        started = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, "Recognized authority"):
            orc.run_checks(
                self.rundir, self.state, self.cfg, self.project,
                {"title": "prompt", "checks": [[sys.executable, "-c", code]]})
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 30, "the check waited for its full deadline")
        self.assertEqual(self.state["status"], "blocked")
        self.assertIsNone(self.state.get("active_check"))
        record = self.state["permission_blocked"]
        self.assertEqual(record["role"], "supervisor")
        self.assertEqual(record["cause"], "recognized")
        self.assertIn("authentication required", record["action"])

    def test_worker_prompt_is_detected_through_a_real_guarded_child(self):
        code = ("import time; print('permission required: run login', flush=True); "
                "time.sleep(120)")

        def fake_guarded(command, cwd, env, log_stream, launch_file=None,
                         stdin_data=None):
            proc = subprocess.Popen([sys.executable, "-c", code],
                                    stdout=log_stream, stderr=subprocess.STDOUT,
                                    start_new_session=True)
            if launch_file:
                orc.atomic_json(Path(launch_file),
                                {"guard": orc.process_identity(proc.pid)})
            return proc, None

        preflight = {"ok": True, "reasons": [], "warnings": [],
                     "classification": "subscription", "authorization": {}}
        route = {"provider": "codex", "model": "fixture", "effort": "low",
                 "billing": "subscription"}
        self.state.update({"phase": "implement", "active_job": None})
        orc.save(self.rundir, self.state)
        started = time.monotonic()
        with patch.object(orc, "route_preflight", return_value=preflight), \
                patch.object(orc, "_route_identity_recheck", return_value=None), \
                patch.object(orc, "_spawn_guarded", side_effect=fake_guarded):
            with self.assertRaisesRegex(RuntimeError, "Recognized authority"):
                orc.call_model(self.rundir, self.state, self.cfg, "implementer",
                               "implementer", "do work", self.project,
                               route=route)
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 30, "the worker waited for its full deadline")
        self.assertEqual(self.state["status"], "blocked")
        record = self.state["permission_blocked"]
        self.assertEqual(record["role"], "implementer")
        self.assertEqual(record["cause"], "recognized")
        self.assertEqual(record["assignment"], None)
        self.assertFalse(record["raw_text_persisted"])
        self.assertEqual(orc.read_json(self.rundir / "control.json")["action"],
                         "pause")

    def test_unrecognized_prompt_shape_remains_unknown(self):
        hint = orc._unknown_permission_hint(
            "Authentication required. Enter the account token to continue.\n")
        self.assertEqual(hint["source"], "unknown")
        self.assertEqual(hint["action"], "unrecognized authority/credential prompt")
        self.assertIsNone(orc._unknown_permission_hint("tests passed\n"))

    def test_permission_block_propagates_to_running_siblings(self):
        plan = {"contract_version": 2, "status": "complete", "summary": "plan",
                "invariants": ["Keep behavior"],
                "batches": [{"title": "feature", "goal": "change",
                             "acceptance": ["works"],
                             "checks": [[sys.executable, "-c", "raise SystemExit(0)"]],
                             "risk": "ordinary", "verification_purpose": None,
                             "repeat_checks": None,
                             "writers": [
                                 {"id": "a", "goal": "a", "paths": ["a.py"],
                                  "components": [], "completion_criteria": "a",
                                  "role": "implementer"},
                                 {"id": "b", "goal": "b", "paths": ["b.py"],
                                  "components": [], "completion_criteria": "b",
                                  "role": "implementer"},
                                 {"id": "c", "goal": "c", "paths": ["c.py"],
                                  "components": [], "completion_criteria": "c",
                                  "role": "implementer"}]}],
                "blocker": "", "required_exploration": {
                    "job_id": "", "scope_satisfied": True}}
        self.state.update({"phase": "implement", "plan": plan,
                           "plan_version": orc.content_hash(plan),
                           "plan_revision": 1, "batch_index": 0,
                           "parallel_permission": {"max_writers": 3,
                                                   "enabled": True}})
        orc.save(self.rundir, self.state)
        batch = plan["batches"][0]
        resolved = orc.resolve_parallel_batch(self.state, self.project, batch,
                                              run_dir=self.rundir)
        seen = []

        def fake(run_dir, state, cfg, role, kind, prompt, project, **kwargs):
            writer_id = kwargs.get("assignment")
            seen.append(writer_id)
            project = Path(project)
            if writer_id == "a":
                (project / "a.py").write_text("a = 1\n")
                return ({"contract_version": 2, "status": "complete",
                         "summary": "a done", "files": [], "tests": [],
                         "evidence": [], "unknowns": [], "blocker": ""},
                        {"id": "job-a", "role": "implementer",
                         "kind": "implementer"})
            if writer_id == "b":
                (project / "b.py").write_text("b = 'partial'\n")
                orc._record_permission_blocked(
                    run_dir, state, role="implementer", assignment="b",
                    action="credential required",
                    reason="provider asked for a login token")
                orc._request_execution_pause(Path(run_dir).parents[2],
                                             "recognized authority prompt")
                raise RuntimeError("Recognized authority/credential prompt")
            limit = time.monotonic() + 10
            while time.monotonic() < limit:
                try:
                    action = orc.read_json(
                        Path(run_dir).parents[2] / "control.json")["action"]
                except (OSError, ValueError, KeyError):
                    action = "run"
                if action in {"pause", "cancel"}:
                    raise InterruptedError("Run pause requested")
                time.sleep(0.1)
            (project / "c.py").write_text("c = 3\n")
            return ({"contract_version": 2, "status": "complete",
                     "summary": "c done", "files": [], "tests": [],
                     "evidence": [], "unknowns": [], "blocker": ""},
                    {"id": "job-c", "role": "implementer",
                     "kind": "implementer"})

        with patch.object(orc, "call_model", side_effect=fake):
            result = orc.run_parallel_batch(
                self.rundir, self.state, self.cfg, self.project, batch, resolved,
                None)
        self.assertIsNone(result)
        self.assertEqual(self.state["status"], "blocked")
        self.assertEqual(self.state["permission_blocked"]["lane"], "b")
        self.assertEqual(self.state["parallel_writers"]["lanes"]["a"]["status"],
                         "complete")
        self.assertFalse((self.project / "a.py").exists())
        self.assertFalse((self.project / "c.py").exists())
        self.assertEqual(orc.read_json(self.rundir / "control.json")["action"],
                         "pause")


if __name__ == "__main__":
    unittest.main()
