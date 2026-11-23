"""v1.2.1 explicit skill routing: identity, bounds, safety and persistence."""
from __future__ import annotations

import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import test_orchestrator as baseline

orc = baseline.orc


class SkillRoutingTests(unittest.TestCase):
    setUp = baseline.ControlTests.setUp
    tearDown = baseline.ControlTests.tearDown

    def skill_root(self):
        root = self.root / "skills"
        root.mkdir(exist_ok=True)
        return root

    def write_skill(self, name, text, root=None):
        root = root or self.skill_root()
        folder = root / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "SKILL.md").write_text(text, encoding="utf-8")
        return folder

    def with_root(self, root):
        patcher = patch.dict(os.environ, {"ABDULLAH_SKILLS_ROOT": str(root)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def create_run(self, skills):
        self.with_root(self.skill_root())
        # The baseline fixture owns this checkout for a non-final run.  Finish
        # it explicitly so the new run's lease admission is a real acquisition,
        # not a fixture conflict.
        self.state["status"] = "cancelled"
        orc.save(self.rundir, self.state)
        return orc.create_run(project=self.project, goal="Use the named skills",
                              host="codex", skip_doctor=True, skills=skills)

    def test_explicit_skill_is_pinned_in_state_and_injected_before_task(self):
        self.write_skill("demo", "---\nname: demo\n---\nFollow demo instructions.\n")
        _run, folder, state = self.create_run({"implementer": ["demo"]})
        record = state["skill_assignments"]["roles"]["implementer"][0]
        self.assertEqual(record["name"], "demo")
        self.assertEqual(record["sha256"], orc._sha256_file(Path(record["instructions_path"])))
        payload = orc._skill_prompt_payload(state, "implementer")
        self.assertFalse(payload["native_loading"])
        self.assertIn("Supervisor and role policy override", payload["precedence"])
        prompt = orc.render_prompt("implementer", {"skills": payload, "task": "write"})
        policy_at = prompt.index("Abdullah Orchestrator's implementer role")
        skill_at = prompt.index("Follow demo instructions.")
        task_at = prompt.index("Task and evidence:")
        self.assertLess(policy_at, skill_at)
        self.assertLess(skill_at, task_at)
        self.assertIn("never grant permissions", orc._render_skill_section(payload))

    def test_missing_skill_fails_visibly(self):
        with self.assertRaisesRegex(ValueError, "not present under known roots"):
            self.create_run({"reviewer": ["absent-skill"]})

    def test_bundle_expands_deterministically_and_missing_members_fail(self):
        self.write_skill("using-superpowers", "super\n")
        self.write_skill("brainstorming", "brain\n")
        with self.assertRaisesRegex(ValueError, "writing-plans"):
            self.create_run({"architect": ["superpowers"]})
        self.write_skill("writing-plans", "plans\n")
        self.write_skill("verification-before-completion", "verify\n")
        _run, _folder, state = self.create_run({"architect": ["superpowers"]})
        names = [item["name"] for item in
                 state["skill_assignments"]["roles"]["architect"]]
        self.assertEqual(names, ["using-superpowers", "brainstorming",
                                 "writing-plans", "verification-before-completion"])

    def test_ambiguous_cross_root_content_fails_closed(self):
        other = self.root / "skills-other"
        other.mkdir()
        self.write_skill("demo", "one\n")
        self.write_skill("demo", "two\n", root=other)
        self.with_root(self.skill_root())
        cfg = orc.read_json(Path(orc.CONFIG_PATH))
        cfg["skills"] = {"roots": [str(other)]}
        orc.atomic_json(Path(orc.CONFIG_PATH), cfg)
        self.cfg = orc.config()
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            orc.resolve_skill_reference("demo", cfg=self.cfg, project=self.project)

    def test_symlink_escape_and_oversized_content_fail_closed(self):
        root = self.skill_root()
        self.with_root(root)
        outside = self.root / "outside.md"
        outside.write_text("secret outside\n")
        folder = root / "linked"
        folder.mkdir()
        (folder / "SKILL.md").symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "escapes its declared root"):
            orc.resolve_skill_reference("linked", cfg=self.cfg, project=self.project)
        self.write_skill("large", "x" * (orc.SKILL_MAX_INSTRUCTION_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "budget"):
            orc.resolve_skill_reference("large", cfg=self.cfg, project=self.project)

    def test_tampered_skill_artifact_is_refused(self):
        self.write_skill("demo", "original\n")
        _run, _folder, state = self.create_run({"implementer": ["demo"]})
        path = Path(state["skill_assignments"]["roles"]["implementer"][0]["instructions_path"])
        path.write_text("tampered\n")
        with self.assertRaisesRegex(RuntimeError, "changed since resolution"):
            orc._skill_prompt_payload(state, "implementer")

    def test_writer_specific_assignment_and_persistence_across_reload(self):
        self.write_skill("demo", "demo\n")
        self.write_skill("lane", "lane\n")
        run, folder, state = self.create_run({
            "implementer": ["demo"],
            "writers": {"w1": ["lane"]}})
        reloaded = orc.read_json(folder / "state.json")
        payload = orc._skill_prompt_payload(reloaded, "implementer", writer="w1")
        self.assertEqual([item["name"] for item in payload["skills"]], ["demo", "lane"])
        self.assertIn("w1", reloaded["skill_assignments"]["writers"])
        summary = orc._skill_summary(reloaded)
        self.assertEqual(summary["delivery"], "prompt_injection")
        self.assertFalse(summary["permissions_from_skills"])
        self.assertEqual(reloaded["goal"], "Use the named skills")

    def test_no_skill_is_inferred_from_goal_text(self):
        _run, _folder, state = self.create_run(None)
        self.assertEqual(state["skill_assignments"]["roles"], {})
        self.assertIsNone(orc._skill_prompt_payload(state, "architect"))


    def test_reviewer_shell_requirement_fails_visibly_but_writer_allows_it(self):
        skill_text = ("---\nname: demo\nrequires:\n  - bash\n---\nRun shell.\n")
        self.write_skill("demo", skill_text)
        with self.assertRaisesRegex(ValueError, "read-only role reviewer"):
            self.create_run({"reviewer": ["demo"]})
        _run, _folder, state = self.create_run({"implementer": ["demo"]})
        self.assertEqual(
            state["skill_assignments"]["roles"]["implementer"][0]["required_tools"],
            ["bash"])

    def test_source_change_leaves_the_pinned_copy_and_missing_copy_is_visible(self):
        folder = self.write_skill("demo", "original pinned text\n")
        _run, _folder, state = self.create_run({"implementer": ["demo"]})
        (folder / "SKILL.md").write_text("changed after start\n")
        payload = orc._skill_prompt_payload(state, "implementer")
        self.assertIn("original pinned text", payload["skills"][0]["instructions"])
        self.assertNotIn("changed after start", payload["skills"][0]["instructions"])
        pinned = Path(state["skill_assignments"]["roles"]["implementer"][0][
            "instructions_path"])
        pinned.unlink()
        with self.assertRaisesRegex(RuntimeError, "missing"):
            orc._skill_prompt_payload(state, "implementer")
        preflight = orc.permission_preflight(state, self.cfg, self.project)
        self.assertTrue(any(item["kind"] == "skill_artifact"
                            for item in preflight["missing"]),
                        preflight["missing"])

    def test_fresh_reviewer_request_is_read_only_and_scoped(self):
        self.write_skill("review-only", "Read changed source and report findings.\n")
        _run, _folder, state = self.create_run({"reviewer": ["review-only"]})
        payload = orc._skill_prompt_payload(state, "reviewer")
        self.assertEqual(payload["role"], "reviewer")
        prompt = orc.render_prompt("reviewer", {"skills": payload, "task": "review"})
        policy_at = prompt.index("Abdullah Orchestrator's reviewer role")
        skill_at = prompt.index("Read changed source and report findings.")
        task_at = prompt.index("Task and evidence:")
        self.assertLess(policy_at, skill_at)
        self.assertLess(skill_at, task_at)
        self.assertIn("never grant permissions", prompt)

    def test_implementer_tool_requirement_matches_the_effective_adapter(self):
        record = {"name": "needs-agent", "required_tools": ["subagent"]}
        opencode = {"provider": "opencode", "billing": "go"}
        codex = {"provider": "codex", "billing": "subscription"}
        self.assertIn("denies", orc._skill_tool_problem(
            "implementer", record, opencode, dialect="v2"))
        self.assertIsNone(orc._skill_tool_problem(
            "implementer", record, codex, dialect=None))
        self.assertIn("denies", orc._skill_tool_problem(
            "implementer", {"name": "needs-agent", "required_tools": ["task"]},
            opencode, dialect="v1"))
        self.write_skill(
            "agent-skill",
            "---\nname: agent-skill\nrequires:\n  - subagent\n---\nDelegate.\n")
        with self.assertRaisesRegex(ValueError, "adapter profile denies"):
            self.create_run({"implementer": ["agent-skill"]})

    def test_missing_artifact_is_blocking_only_for_the_pending_role(self):
        self.write_skill("demo", "pinned\n")
        _run, _folder, state = self.create_run({"implementer": ["demo"]})
        pinned = Path(state["skill_assignments"]["roles"]["implementer"][0][
            "instructions_path"])
        pinned.unlink()
        state["phase"] = "implement"
        blocking = orc.permission_preflight(state, self.cfg, self.project,
                                            scope="pending")
        self.assertTrue(any(item["kind"] == "skill_artifact"
                            for item in blocking["missing"]))
        state["phase"] = "accept"
        deferred = orc.permission_preflight(state, self.cfg, self.project,
                                            scope="pending")
        self.assertFalse(any(item["kind"] == "skill_artifact"
                             for item in deferred["missing"]))
        self.assertTrue(any(item["kind"] == "skill_artifact"
                            and item.get("deferred")
                            for item in deferred["advisories"]))

    def test_writer_retry_keeps_the_same_pinned_skill_identity(self):
        self.write_skill("lane", "lane instructions\n")
        _run, folder, state = self.create_run({"writers": {"w1": ["lane"]}})
        first = orc._skill_prompt_payload(state, "implementer", writer="w1")
        reloaded = orc.read_json(folder / "state.json")
        second = orc._skill_prompt_payload(reloaded, "implementer", writer="w1")
        self.assertEqual([item["sha256"] for item in first["skills"]],
                         [item["sha256"] for item in second["skills"]])
        self.assertEqual(first["skills"][0]["instructions"],
                         second["skills"][0]["instructions"])


if __name__ == "__main__":
    unittest.main()
