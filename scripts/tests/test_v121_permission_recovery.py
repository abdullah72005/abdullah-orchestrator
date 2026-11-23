"""v1.2.1 permission preflight and durable blocked-state recovery."""
from __future__ import annotations

import json
import os
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
