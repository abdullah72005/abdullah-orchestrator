"""Final independent-audit regressions: security, provenance, plans, authorization."""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_orchestrator as baseline

orc = baseline.orc


def shipped_config():
    return orc.read_json(orc.HERE / "config.example.json")


class CommandPolicyDefaults(unittest.TestCase):
    def test_shipped_default_rejects_auditor_reproducers(self):
        cfg = shipped_config()
        for argv, reason in (
                (["bash", "-lc", "pytest -q"], "shell_wrapper"),
                (["bash", "-c", "docker compose run web pytest"], "shell_wrapper"),
                (["python3", "-c", "print('x')"], "interpreter_string"),
                (["/usr/bin/python3.10", "-c", "x"], "interpreter_string"),
                (["env", "FOO=1", "bash", "-c", "pytest"], "shell_wrapper")):
            with self.subTest(argv=argv):
                policy = orc.verification_command_policy(argv, cfg)
                self.assertFalse(policy["allowed"], policy)
                self.assertIn(reason, policy["rejected_reasons"])

    def test_shipped_default_keeps_legitimate_commands_usable(self):
        cfg = shipped_config()
        for argv in (["pytest", "-q"], ["python3", "-m", "unittest", "discover"],
                     ["git", "status", "--porcelain"],
                     ["docker", "compose", "run", "--rm", "web", "pytest"]):
            with self.subTest(argv=argv):
                self.assertTrue(orc.verification_command_policy(argv, cfg)["allowed"])

    def test_disabling_protection_requires_explicit_acknowledgement(self):
        cfg = shipped_config()
        cfg["verification"]["command_policy"]["reject_shell_wrappers"] = False
        cfg["verification"]["command_policy"]["reject_arbitrary_scripts"] = False
        with self.assertRaisesRegex(ValueError, "unsafe_acknowledged"):
            orc.verification_command_policy(["bash", "-lc", "pytest"], cfg)
        cfg["verification"]["command_policy"]["unsafe_acknowledged"] = \
            "I accept unclassified verification commands"
        self.assertTrue(orc.verification_command_policy(["bash", "-lc", "pytest"], cfg)["allowed"])

    def test_scoped_exception_is_recorded_and_cannot_be_model_authorized(self):
        cfg = shipped_config()
        cfg["verification"]["command_policy"]["exceptions"] = [{
            "argv_regex": r'.*"bash","-lc","pytest -q".*',
            "reason": "legacy project wrapper required by CI",
            "scope": "/repo/project-a",
            "authorized_by": "abdullah",
        }]
        # A scoped exception requires a project identity; without one it must
        # not silently become global.
        unscoped = orc.verification_command_policy(["bash", "-lc", "pytest -q"], cfg)
        self.assertFalse(unscoped["allowed"], unscoped)
        policy = orc.verification_command_policy(
            ["bash", "-lc", "pytest -q"], cfg, project=Path("/repo/project-a"))
        self.assertTrue(policy["allowed"])
        self.assertEqual(policy["policy"], "exception")
        self.assertEqual(policy["exception"]["authorized_by"], "abdullah")
        self.assertEqual(policy["exception"]["scope"], "/repo/project-a")
        cfg["verification"]["command_policy"]["exceptions"][0]["authorized_by"] = "architect"
        with self.assertRaisesRegex(ValueError, "cannot authorize"):
            orc.verification_command_policy(["bash", "-lc", "pytest -q"], cfg)

    def test_wrappers_and_project_local_executables_are_rejected(self):
        cfg = shipped_config()
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "payload").write_text("#!/bin/sh\n")
            (project / "run.zsh").write_text("echo hi\n")
            for argv in (["sudo", "pytest"], ["timeout", "30", "pytest"],
                         ["env", "PATH=.", "pytest"], ["xargs", "pytest"],
                         ["./payload"], ["scripts/run"], ["run.zsh"]):
                with self.subTest(argv=argv):
                    policy = orc.verification_command_policy(argv, cfg, project=project)
                    self.assertFalse(policy["allowed"], policy)
                    self.assertTrue(policy["rejected_reasons"], policy)

    def test_exception_for_plain_command_does_not_authorize_wrapper(self):
        cfg = shipped_config()
        cfg["verification"]["command_policy"]["exceptions"] = [{
            "argv_regex": r'.*"pytest","-q".*',
            "reason": "plain pytest is approved",
            "scope": "*",
            "authorized_by": "ops",
        }]
        self.assertTrue(orc.verification_command_policy(["pytest", "-q"], cfg)["allowed"])
        wrapped = orc.verification_command_policy(["bash", "-lc", "pytest -q"], cfg)
        self.assertFalse(wrapped["allowed"], wrapped)

    def test_exception_scope_is_enforced(self):
        cfg = shipped_config()
        with tempfile.TemporaryDirectory() as tmp:
            allowed_project = Path(tmp) / "allowed"
            other_project = Path(tmp) / "other"
            allowed_project.mkdir()
            other_project.mkdir()
            cfg["verification"]["command_policy"]["exceptions"] = [{
                "argv_regex": r'.*"bash","-lc","pytest -q".*',
                "reason": "legacy wrapper for one project",
                "scope": str(allowed_project),
                "authorized_by": "ops",
            }]
            self.assertTrue(orc.verification_command_policy(
                ["bash", "-lc", "pytest -q"], cfg, project=allowed_project)["allowed"])
            self.assertFalse(orc.verification_command_policy(
                ["bash", "-lc", "pytest -q"], cfg, project=other_project)["allowed"])

    def test_exception_requires_scope_and_reason(self):
        cfg = shipped_config()
        cfg["verification"]["command_policy"]["exceptions"] = [{
            "argv_regex": r".*", "authorized_by": "abdullah"}]
        with self.assertRaisesRegex(ValueError, "missing"):
            orc.verification_command_policy(["pytest"], cfg)


class ProvenanceBinding(unittest.TestCase):
    def setUp(self):
        baseline.ControlTests.setUp(self)

    def _verify(self):
        return orc.run_checks(
            self.rundir, self.state, self.cfg, self.project,
            {"title": "env", "checks": [["git", "status", "--porcelain"]]})

    def test_environment_drift_invalidates_reused_evidence(self):
        with patch.dict(os.environ, {"NODE_ENV": "test"}):
            evidence = self._verify()
        self.assertTrue(evidence["passed"])
        reference = {"path": evidence["path"], "passed": True,
                     "candidate_hash": evidence["after_hash"]}
        with patch.dict(os.environ, {"NODE_ENV": "production"}):
            with self.assertRaisesRegex(ValueError, "environment"):
                orc.verification_evidence_package(
                    reference, orc.source_snapshot(self.project, cfg=self.cfg))
        with patch.dict(os.environ, {"NODE_ENV": "test"}):
            package = orc.verification_evidence_package(
                reference, orc.source_snapshot(self.project, cfg=self.cfg))
        self.assertEqual(package["evidence_version"], orc.VERIFICATION_EVIDENCE_VERSION)

    def test_toolchain_drift_is_detected_directly(self):
        recorded = orc.source_snapshot(self.project, cfg=self.cfg)
        current = copy.deepcopy(recorded)
        current["toolchain"] = dict(current["toolchain"], python={"version": "changed"})
        self.assertIn("toolchain", orc.provenance_drift(recorded, current))

    def test_ignored_executable_change_invalidates_signature(self):
        (self.project / ".gitignore").write_text("helper.py\n")
        helper = self.project / "helper.py"
        helper.write_text("VALUE = 1\n")
        before = orc.source_snapshot(self.project, cfg=self.cfg)
        self.assertIn("helper.py", before["runtime_inputs"]["files"])
        helper.write_text("VALUE = 2\n")
        after = orc.source_snapshot(self.project, cfg=self.cfg)
        self.assertNotEqual(orc.signature(before), orc.signature(after))

    def test_missing_declared_required_input_fails_closed(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["verification"]["runtime_inputs"]["required"] = ["must-exist.conf"]
        manifest = orc.runtime_input_manifest(self.project, cfg)
        self.assertFalse(manifest["complete"])
        self.assertIn("must-exist.conf", manifest["missing_required"])
        with self.assertRaisesRegex(RuntimeError, "runtime-input manifest"):
            orc.run_checks(self.rundir, self.state, cfg, self.project,
                           {"title": "x", "checks": [["git", "status"]]})

    def test_project_declared_exclusion_fails_closed(self):
        declared = self.project / ".abdullah"
        declared.mkdir()
        (self.project / "evil.py").write_text("V=1\n")
        (declared / "runtime-inputs.json").write_text(json.dumps(
            {"exclude": ["evil.py"]}))
        manifest = orc.runtime_input_manifest(self.project, self.cfg)
        self.assertFalse(manifest["complete"])
        self.assertEqual(manifest["project_excludes"], ["evil.py"])

    def test_project_declaration_adds_inputs(self):
        declared = self.project / ".abdullah"
        declared.mkdir()
        (declared / "runtime-inputs.json").write_text(json.dumps(
            {"include": ["custom.asset"], "required": ["custom.asset"]}))
        (self.project / "custom.asset").write_text("data")
        manifest = orc.runtime_input_manifest(self.project, self.cfg)
        self.assertIn("custom.asset", manifest["files"])
        self.assertTrue(manifest["complete"])

    def test_evidence_from_another_plan_revision_is_rejected(self):
        self.state["plan_version"] = "plan-a"
        evidence = self._verify()
        with self.assertRaisesRegex(ValueError, "different plan revision"):
            orc.verification_evidence_package(
                {"path": evidence["path"], "passed": True,
                 "candidate_hash": evidence["after_hash"]},
                orc.source_snapshot(self.project, cfg=self.cfg),
                plan_version="a-different-plan")


class PlanQuality(unittest.TestCase):
    def plan(self, batch):
        return {"contract_version": 2, "status": "complete", "summary": "s",
                "invariants": ["invariant"],
                "batches": [batch], "blocker": "", "required_exploration": {
                    "job_id": "", "scope_satisfied": True}}

    def batch(self, **overrides):
        value = {"title": "t", "goal": "g", "acceptance": ["done"],
                 "checks": [["pytest", "-q"]], "risk": "ordinary"}
        value.update(overrides)
        return value

    def test_blank_acceptance_is_rejected(self):
        for acceptance in ([], ["   "], ["ok", ""]):
            with self.subTest(acceptance=acceptance):
                with self.assertRaisesRegex(ValueError, "acceptance"):
                    orc.validate_report("plan", self.plan(self.batch(acceptance=acceptance)))

    def test_malformed_check_argv_is_rejected(self):
        for check in ([[]], [[""]], [["pytest", ""]]):
            with self.subTest(check=check):
                with self.assertRaisesRegex(ValueError, "malformed|argv"):
                    orc.validate_report("plan", self.plan(self.batch(checks=check)))

    def test_high_risk_requires_distinct_meaningful_checks(self):
        duplicate = self.batch(risk="high", checks=[["pytest", "-q"], ["pytest", "-q"]],
                               verification_purpose="cover the migration risk")
        with self.assertRaisesRegex(ValueError, "distinct"):
            orc.validate_report("plan", self.plan(duplicate))
        trivial = self.batch(risk="high", checks=[["true"], ["pytest", "-q"]],
                             verification_purpose="cover the migration risk")
        with self.assertRaisesRegex(ValueError, "trivial"):
            orc.validate_report("plan", self.plan(trivial))
        no_purpose = self.batch(risk="high", checks=[["pytest", "-q"], ["ruff", "check"]])
        with self.assertRaisesRegex(ValueError, "verification_purpose"):
            orc.validate_report("plan", self.plan(no_purpose))
        ok = self.batch(risk="high", checks=[["pytest", "-q"], ["ruff", "check"]],
                        verification_purpose="cover the migration risk")
        plan = self.plan(ok)
        self.assertIs(orc.validate_report("plan", plan), plan)


class HumanAuthorization(unittest.TestCase):
    def test_mcp_does_not_expose_human_only_approvals(self):
        self.assertNotIn("orchestrator_approve_plan", orc.MCP_TOOL_NAMES)
        self.assertNotIn("orchestrator_approve_fallback", orc.MCP_TOOL_NAMES)

    def test_non_interactive_operator_action_is_refused(self):
        with patch.object(orc.sys.stdin, "isatty", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "interactive operator terminal"):
                orc.require_human_operator("approve-plan", "run-1", "approve-plan:run-1")

    def test_agent_marker_context_is_refused(self):
        with patch.dict(os.environ, {"ABDULLAH_JOB_ID": "job"}):
            with self.assertRaisesRegex(RuntimeError, "model-owned"):
                orc.require_human_operator("approve-fallback", "run-1",
                                           "approve-fallback:run-1")

    def test_confirmation_token_is_exact(self):
        with patch.object(orc.sys.stdin, "isatty", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "Confirmation mismatch"):
                orc.require_human_operator("approve-plan", "run-1", "approve-plan:run-2")
            result = orc.require_human_operator("approve-plan", "run-1", "approve-plan:run-1")
        self.assertEqual(result["method"], "interactive-tty-confirmation")


class AmendmentsAndContext(unittest.TestCase):
    def setUp(self):
        baseline.ControlTests.setUp(self)

    def _plan(self):
        plan = {"contract_version": 2, "status": "complete", "summary": "s",
                "invariants": ["i"],
                "batches": [{"title": "t", "goal": "g", "acceptance": ["a"],
                             "checks": [["pytest", "-q"]], "risk": "ordinary"}],
                "blocker": "", "required_exploration": {"job_id": "", "scope_satisfied": True}}
        self.state.update(plan=plan, plan_version=orc.content_hash(plan),
                          phase="implement", status="paused", batch_index=0)
        orc.save(self.rundir, self.state)
        return plan

    def test_user_requirement_change_defaults_to_replan(self):
        plan = self._plan()
        orc.amend_run("test-run00", "Add a new required feature")
        saved = orc.read_json(self.rundir / "state.json")
        self.assertEqual(saved["amendments"][-1]["kind"], "material")
        self.assertEqual(saved["amendments"][-1]["request_kind"], "requirement")
        self.assertEqual(saved["phase"], "diagnose")
        self.assertIsNone(saved["verification"])
        self.assertEqual(saved["plan_history"][-1]["plan_version"], orc.content_hash(plan))

    def test_explicit_correction_stays_bounded(self):
        self._plan()
        orc.amend_run("test-run00", "Fix the typo", kind="correction")
        saved = orc.read_json(self.rundir / "state.json")
        self.assertEqual(saved["amendments"][-1]["kind"], "minor")
        self.assertEqual(saved["phase"], "implement")

    def test_architect_review_forces_material_even_for_correction(self):
        self._plan()
        orc.amend_run("test-run00", "Design change", kind="correction",
                      architect_review=True)
        saved = orc.read_json(self.rundir / "state.json")
        self.assertEqual(saved["amendments"][-1]["kind"], "material")
        self.assertEqual(saved["phase"], "diagnose")

    def test_essential_context_is_never_silently_dropped(self):
        payload = {"goal": "required goal", "invariants": ["i1"],
                   "blob": "x" * 5000}
        parsed = json.loads(orc._bounded_context(payload, 1200))
        self.assertEqual(parsed["goal"], "required goal")
        self.assertEqual(parsed["invariants"], ["i1"])
        self.assertTrue(parsed["blob"]["omitted"])
        self.assertTrue(parsed["_context_budget"]["truncated"])

    def test_oversized_essential_context_fails_clearly(self):
        with self.assertRaisesRegex(ValueError, "Essential handoff context exceeds"):
            orc._bounded_context({"goal": "x" * 5000}, 200)


class OpenCodeV2(unittest.TestCase):
    def test_version_policy_accepts_only_tested_ranges(self):
        self.assertEqual(orc.opencode_dialect("opencode 1.18.35"), "v1")
        self.assertEqual(orc.opencode_dialect("opencode v2.2.7"), "v2")
        with self.assertRaisesRegex(RuntimeError, "Unsupported OpenCode version"):
            orc.opencode_dialect("opencode 2.0.0")
        with self.assertRaisesRegex(RuntimeError, "Unsupported OpenCode version"):
            orc.opencode_dialect("opencode 3.0.0")
        with self.assertRaisesRegex(RuntimeError, "does not match pinned"):
            orc.opencode_dialect("opencode 2.2.7", pinned="1.18")
        self.assertEqual(orc.opencode_dialect("opencode v1.18.35"), "v1")
        self.assertEqual(orc.opencode_dialect("opencode v2.2.7", pinned="2.2.7"), "v2")
        with self.assertRaisesRegex(RuntimeError, "does not match pinned"):
            orc.opencode_dialect("opencode v2.2.7", pinned="2.2.6")

    def test_v2_profiles_enforce_role_restrictions(self):
        for role in ("explorer", "reviewer"):
            self.assertTrue(orc.validate_worker_profile(role, "v2"))
            rules = orc.opencode_profile(role, "v2")["permissions"]
            for action in ("edit", "shell", "subagent", "external_directory",
                           "webfetch", "websearch"):
                self.assertTrue(any(r["action"] == action and r["effect"] == "deny"
                                    for r in rules), (role, action))
        self.assertTrue(orc.validate_worker_profile("implementer", "v2"))
        rules = orc.opencode_profile("implementer", "v2")["permissions"]
        for resource in ("git push *", "git clean *", "git reset --hard *"):
            self.assertTrue(any(r["action"] == "shell" and r["resource"] == resource
                                and r["effect"] == "deny" for r in rules))

    def test_v2_model_inventory_parser(self):
        models = orc.parse_model_inventory_v2(
            "opencode-go/deepseek-v4.1-flash\nopencode-go/glm-5.3\nother/model\n")
        self.assertIn("opencode-go/deepseek-v4.1-flash", models)
        self.assertIn("other/model", models)
        with self.assertRaises(ValueError):
            orc.parse_model_inventory_v2("")

    def test_v2_doctor_introspection_uses_debug_agents(self):
        role = "explorer"
        rules = [dict(rule) for rule in orc.opencode_profile(role, "v2")["permissions"]]
        payload = json.dumps([{
            "id": f"abdullah-{role}", "mode": "primary",
            "system": orc.role_text(role),
            "description": orc.opencode_profile(role, "v2")["description"],
            "permissions": rules}])
        reply = subprocess.CompletedProcess([], 0, stdout=payload)
        with patch.object(orc.subprocess, "run", return_value=reply) as run:
            self.assertIs(orc.probe_opencode_config(Path("/tmp"), role, "v2"), True)
        self.assertEqual(run.call_args[0][0][:3], ["opencode", "debug", "agents"])
        broken = json.dumps([{
            "id": f"abdullah-{role}", "mode": "primary",
            "system": orc.role_text(role),
            "description": orc.opencode_profile(role, "v2")["description"],
            "permissions": []}])
        with patch.object(orc.subprocess, "run",
                          return_value=subprocess.CompletedProcess([], 0, stdout=broken)):
            self.assertIs(orc.probe_opencode_config(Path("/tmp"), role, "v2"), False)
        with patch.object(orc.subprocess, "run",
                          return_value=subprocess.CompletedProcess([], 1, stdout="")):
            self.assertIsNone(orc.probe_opencode_config(Path("/tmp"), role, "v2"))

    def test_v2_command_uses_variant_reference_and_standalone(self):
        route = {"provider": "opencode", "model": "opencode-go/deepseek-v4.1-flash",
                 "effort": "high", "billing": "go"}
        with patch.object(orc, "opencode_dialect", return_value="v2"):
            command, env, fmt = orc.cli_command("codex", "implementer", route,
                                                "Task", Path("/tmp/x"))
        self.assertEqual(fmt, "jsonl")
        self.assertIn("--standalone", command)
        self.assertNotIn("--variant", command)
        self.assertEqual(command[command.index("--model") + 1],
                         "opencode-go/deepseek-v4.1-flash#high")
        inline = json.loads(env["OPENCODE_CONFIG_CONTENT"])
        self.assertIn("agents", inline)
        self.assertEqual(inline["experimental"]["subagent_depth"], 0)


if __name__ == "__main__":
    unittest.main()
