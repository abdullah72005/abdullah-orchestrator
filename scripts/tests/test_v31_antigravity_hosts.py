"""Three-host orchestration: Antigravity routing, transport, consultation,
run-scoped check authority, execution visibility and automatic progression.

The model boundary is faked; every CLI probe is either a test-owned executable
or an explicitly patched observation, so no real provider can be launched.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_orchestrator as baseline

orc = baseline.orc


ANTIGRAVITY_HELP = (
    "Usage: agy [options]\n"
    "  --print                 print the answer and exit\n"
    "  --model <id>            select a model\n"
    "  --output-format <fmt>   json or text\n"
    "  --effort <level>        reasoning effort\n"
    "  --session <id>          continue a session\n")


class _FakeTty:
    def isatty(self):
        return True


class _NoTty:
    def isatty(self):
        return False


# Mirrors orchestrator.HUMAN_ONLY_ACTIONS' marker tuple.  Kept local so the
# test fails if the supervisor ever silently drops one of these markers.
AGENT_MARKERS = ("ABDULLAH_JOB_ID", "ABDULLAH_RUN_ID", "ABDULLAH_CHECK_TOKEN",
                 "ABDULLAH_PARENT_JOB", "ABDULLAH_AGENT_CONTEXT")


def _human_operator_env():
    """Clear every agent marker so the human-only boundary is genuinely tested.

    Patching only ABDULLAH_JOB_ID leaves the test dependent on how the
    developer's shell was launched; a supervisor-launched process also carries
    ABDULLAH_RUN_ID and the result would differ per environment.
    """
    return patch.dict(os.environ, {marker: "" for marker in AGENT_MARKERS})


def plan_report(checks):
    return {"contract_version": 2, "status": "complete",
            "summary": "plan", "invariants": ["Keep behavior"],
            "batches": [{"title": "feature", "goal": "change app",
                         "acceptance": ["works"], "checks": checks,
                         "risk": "high", "verification_purpose": None,
                         "repeat_checks": None, "writers": []}],
            "blocker": "",
            "required_exploration": {"job_id": "", "scope_satisfied": True}}


class AntigravityHostTests(unittest.TestCase):
    setUp = baseline.ControlTests.setUp
    tearDown = baseline.ControlTests.tearDown

    # -- routing ---------------------------------------------------------
    def test_host_validation_is_explicit_and_antigravity_is_opt_in(self):
        self.assertIn("antigravity", orc.CONTROLLING_HOSTS)
        with self.assertRaisesRegex(ValueError, "architect.antigravity"):
            orc.model_route(orc.config(), "antigravity", "architect")
        with self.assertRaisesRegex(ValueError, "controlling host"):
            orc.create_run(project=self.project, goal="x", host="gemini",
                           skip_doctor=True)
        with self.assertRaises(ValueError):
            orc.create_run(project=self.project, goal="x", host=None,
                           skip_doctor=True)
        # Existing hosts keep working with the shipped configuration.
        route = orc.model_route(orc.config(), "codex", "architect")
        self.assertEqual(route["provider"], "codex")

    # -- default changes --------------------------------------------------
    def test_default_change_is_previewed_atomically_and_backed_up(self):
        original_state = (self.rundir / "state.json").read_bytes()
        original_cfg = orc.CONFIG_PATH.read_bytes()
        preview = orc.preview_default_change(
            "implementer", {"model": "opencode-go/other-model",
                            "variant": "low"})
        self.assertTrue(preview["preview"])
        self.assertFalse(preview["billing_changed"])
        self.assertEqual(preview["previous"]["model"],
                         self.cfg["workers"]["implementer"]["model"])
        self.assertEqual(preview["proposed"]["model"],
                         "opencode-go/other-model")
        self.assertEqual(orc.CONFIG_PATH.read_bytes(), original_cfg)

        with self.assertRaises(RuntimeError):
            orc.apply_default_change("implementer",
                                     {"model": "opencode-go/other-model",
                                      "variant": "low"}, "wrong")
        with _human_operator_env(), \
                patch.object(orc.sys, "stdin", _FakeTty()):
            applied = orc.apply_default_change(
                "implementer", {"model": "opencode-go/other-model",
                                "variant": "low"},
                preview["expected_confirmation"])
        self.assertTrue(applied["applied"])
        updated = json.loads(orc.CONFIG_PATH.read_text())
        self.assertEqual(updated["workers"]["implementer"]["model"],
                         "opencode-go/other-model")
        self.assertEqual(updated["workers"]["explorer"],
                         self.cfg["workers"]["explorer"])
        self.assertTrue(applied["backup"])
        self.assertTrue(Path(applied["backup"]).exists())
        # Existing run state, including its pins, is untouched.
        self.assertEqual((self.rundir / "state.json").read_bytes(),
                         original_state)

    def test_default_change_rejects_stale_preview_and_paid_billing(self):
        preview = orc.preview_default_change(
            "reviewer", {"model": "opencode-go/other-model"})
        cfg = json.loads(orc.CONFIG_PATH.read_text())
        cfg["limits"]["max_stage_seconds"] = 16000
        orc.atomic_json(orc.CONFIG_PATH, cfg)
        with _human_operator_env(), \
                patch.object(orc.sys, "stdin", _FakeTty()):
            with self.assertRaisesRegex(RuntimeError, "Stale"):
                orc.apply_default_change(
                    "reviewer", {"model": "opencode-go/other-model"},
                    preview["expected_confirmation"])

        preview = orc.preview_default_change(
            "reviewer", {"model": "opencode-go/other-model", "billing": "api"})
        self.assertTrue(preview["billing_changed"])
        with _human_operator_env(), \
                patch.object(orc.sys, "stdin", _FakeTty()):
            with self.assertRaisesRegex(RuntimeError, "billing"):
                orc.apply_default_change(
                    "reviewer",
                    {"model": "opencode-go/other-model", "billing": "api"},
                    preview["expected_confirmation"])

    def test_every_agent_marker_blocks_a_model_owned_default_change(self):
        # The boundary must hold for each marker independently; clearing only
        # one leaves the other four as an accidental escape hatch.
        original = orc.CONFIG_PATH.read_bytes()
        preview = orc.preview_default_change(
            "explorer", {"model": "opencode-go/other-model"})
        for marker in AGENT_MARKERS:
            with patch.dict(os.environ, {marker: "worker-1"}), \
                    patch.object(orc.sys, "stdin", _FakeTty()):
                with self.assertRaisesRegex(RuntimeError, "worker context"):
                    orc.apply_default_change(
                        "explorer", {"model": "opencode-go/other-model"},
                        preview["expected_confirmation"])
            self.assertEqual(orc.CONFIG_PATH.read_bytes(), original)
        # A TTY is also required: correct confirmation without one still fails.
        with _human_operator_env(), \
                patch.object(orc.sys, "stdin", _NoTty()):
            with self.assertRaisesRegex(RuntimeError, "interactive operator"):
                orc.apply_default_change(
                    "explorer", {"model": "opencode-go/other-model"},
                    preview["expected_confirmation"])
        self.assertEqual(orc.CONFIG_PATH.read_bytes(), original)

    def test_default_change_refuses_unsupported_values(self):
        with self.assertRaisesRegex(ValueError, "High"):
            orc.preview_default_change(
                "architect", {"host": "antigravity", "model": "m",
                              "effort": "medium", "billing": "subscription"})
        allowed = orc.preview_default_change(
            "architect", {"host": "antigravity", "model": "m",
                          "effort": "high", "billing": "subscription"})
        self.assertTrue(allowed["preview"])
        self.assertEqual(allowed["proposed"],
                         {"model": "m", "effort": "high",
                          "auth": "subscription"})
        with self.assertRaisesRegex(ValueError, "host"):
            orc.preview_default_change(
                "architect", {"host": "gemini", "model": "m",
                              "effort": "high", "billing": "subscription"})
        with self.assertRaisesRegex(ValueError, "model prefix"):
            orc.preview_default_change(
                "implementer", {"model": "opencode-go/other-model",
                                "provider": "wrong-prefix"})

    def test_antigravity_usage_billing_needs_an_explicit_grant(self):
        route = {"provider": "antigravity", "model": "m", "effort": "high",
                 "billing": "api"}
        verdict = orc.route_preflight("architect", route, self.cfg,
                                      self.project, state=None)
        self.assertFalse(verdict["ok"])
        self.assertIn("authorize-route",
                      " ".join(verdict["reasons"]))
        # Subscription classification is configuration-only, never a silent
        # fallback to a paid API route.
        subscription = dict(route, billing="subscription")
        allowed = orc.route_preflight("architect", subscription, self.cfg,
                                      self.project, state=None)
        self.assertTrue(allowed["ok"])
        self.assertEqual(allowed["classification"], "subscription")

    def test_configured_antigravity_architect_must_use_high(self):
        cfg = copy.deepcopy(self.cfg)
        cfg.setdefault("architect", {})["antigravity"] = {
            "model": "antigravity-test-model", "effort": "medium",
            "auth": "subscription"}
        with patch.object(orc, "config", return_value=cfg):
            with self.assertRaisesRegex(ValueError, "requires High"):
                orc.resolve_run_routes(
                    cfg, "antigravity", self.project,
                    overrides={"architect": {"effort": "medium"}},
                    allow_unverified=True)

    def test_antigravity_doctor_never_probes_claude(self):
        fixture = self.root / "agy-bin"
        fixture.mkdir()
        agy = fixture / "agy"
        agy.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "if '--version' in sys.argv:\n"
            "    print('agy fixture 0.1')\n"
            "else:\n"
            f"    print({ANTIGRAVITY_HELP!r})\n")
        agy.chmod(0o755)
        cfg = orc.read_json(orc.HERE / "config.example.json")
        cfg.setdefault("architect", {})["antigravity"] = {
            "model": "antigravity-test-model", "effort": "high",
            "auth": "subscription"}
        cfg_path = self.root / "config-antigravity.json"
        orc.atomic_json(cfg_path, cfg)
        with patch.dict(os.environ, {
                "PATH": str(fixture) + ":" + os.environ.get("PATH", "")}), \
                patch.object(orc, "CONFIG_PATH", cfg_path):
            result = orc.doctor(self.project, "antigravity")
        self.assertEqual(result["host"], "antigravity")
        # The required strong CLI is agy, not claude/codex.
        self.assertIn("agy", result["commands"])
        self.assertNotIn("claude", result["commands"])
        self.assertNotIn("codex", result["commands"])
        self.assertTrue(result["antigravity"]["available"])
        self.assertEqual(result["antigravity"]["transport"], "stdin-utf8")
        self.assertTrue(result["cli_compatible"]["antigravity"])

    # -- adapter ---------------------------------------------------------
    def test_capability_gate_refuses_unverified_arguments(self):
        partial = orc.antigravity_capabilities(help_text="--print --model")
        self.assertFalse(partial["available"])
        self.assertIn("--output-format", partial["missing"])
        with self.assertRaisesRegex(RuntimeError, "unverified"):
            orc.antigravity_architect_command(
                {"model": "m", "effort": "high"}, capabilities=partial)

        no_effort = orc.antigravity_capabilities(
            help_text="--print --model --output-format json")
        self.assertTrue(no_effort["available"])
        with self.assertRaisesRegex(RuntimeError, "effort"):
            orc.antigravity_architect_command(
                {"model": "m", "effort": "high"}, capabilities=no_effort)

        complete = orc.antigravity_capabilities(help_text=ANTIGRAVITY_HELP)
        argv = orc.antigravity_architect_command(
            {"model": "antigravity-test-model", "effort": "high"},
            capabilities=complete)
        self.assertEqual(argv[1:3], ["--print", "--model"])
        self.assertIn("--effort", argv)
        self.assertIn("high", argv)

    def test_missing_cli_is_an_actionable_blocker(self):
        with patch.object(orc.shutil, "which", return_value=None):
            caps = orc.antigravity_capabilities()
            self.assertFalse(caps["available"])
            self.assertIn("agy", caps["reason"])
            with self.assertRaisesRegex(RuntimeError, "blocked"):
                orc.cli_command(
                    "antigravity", "architect",
                    {"provider": "antigravity", "model": "m", "effort": "high",
                     "billing": "subscription"},
                    "prompt", self.rundir / "plan-probe")

    def test_large_arabic_prompt_travels_on_stdin_only(self):
        caps = orc.antigravity_capabilities(help_text=ANTIGRAVITY_HELP)
        prompt = ("اعمل على تنفيذ المهمة بالكامل. " * 400).strip()
        self.assertGreater(len(prompt.encode("utf-8")), 8000)
        with patch.object(orc, "antigravity_capabilities", return_value=caps):
            command, env, output_format = orc.cli_command(
                "antigravity", "architect",
                {"provider": "antigravity", "model": "m", "effort": "high",
                 "billing": "subscription"},
                prompt, self.rundir / "plan-probe")
        self.assertEqual(output_format, "antigravity")
        self.assertNotIn(prompt, command)
        self.assertFalse(any(prompt in token for token in command))
        self.assertEqual(env["PYTHONIOENCODING"], "utf-8")
        self.assertIsNone(orc.transport_space_error(command, env, prompt=prompt))

    def test_antigravity_report_contract(self):
        good = {"type": "result", "session_id": "s1",
                "report": {"contract_version": 2, "status": "complete",
                           "summary": "done"}}
        report, session = orc.extract_antigravity_report(
            json.dumps(good), expected_session="s1", require_terminal=True)
        self.assertEqual(report["status"], "complete")
        self.assertEqual(session, "s1")

        stream = "\n".join([
            json.dumps({"type": "token", "session_id": "s1"}),
            json.dumps({"type": "result", "session_id": "s1",
                        "structured_output": {"contract_version": 2,
                                              "status": "complete"}})])
        report, session = orc.extract_antigravity_report(
            stream, expected_session="s1", require_terminal=True)
        self.assertEqual(report["status"], "complete")

        cases = [
            (json.dumps({"type": "token", "report": {"status": "complete"}}),
             "incomplete_stream"),
            (json.dumps({"type": "result", "report": {"status": "complete"},
                         "result": {"status": "complete", "summary": "other"}}),
             "conflicting_results"),
            (json.dumps({"type": "result", "session_id": "other",
                         "report": {"status": "complete"}}),
             "session_mismatch"),
            (json.dumps({"type": "result", "session_id": "s1"}),
             "report_missing"),
            ("", "empty_output"),
            ("plain prose without json", "transport_invalid"),
        ]
        for raw, code in cases:
            with self.assertRaises(orc.ReportIngestionError) as raised:
                orc.extract_antigravity_report(
                    raw, expected_session="s1", require_terminal=True)
            self.assertEqual(raised.exception.code, code, raw)

    # -- model configuration --------------------------------------------
    def test_configure_models_view_distinguishes_conversation_and_architect(self):
        routes = {
            "architect": {"provider": "codex", "model": "gpt-test",
                          "effort": "high", "billing": "subscription"},
            "explorer": {"provider": "opencode", "worker_provider": "opencode-go",
                         "model": "opencode-go/fixture", "effort": "low",
                         "billing": "go"},
            "implementer": {"provider": "opencode",
                            "worker_provider": "opencode-go",
                            "model": "opencode-go/fixture", "effort": "high",
                            "billing": "go"},
            "reviewer": {"provider": "opencode", "worker_provider": "opencode-go",
                         "model": "opencode-go/fixture", "effort": "high",
                         "billing": "go"}}
        self.state.update({"phase": "implement", "model_routes": routes,
                           "plan_version": "v1", "plan_revision": 1})
        orc.save(self.rundir, self.state)
        with patch.object(orc, "validate_route_metadata",
                          return_value={"state": "unavailable",
                                        "source": "test"}):
            view = orc.model_configuration("test-run00")
        self.assertEqual(view["entry_point"], "configure-models")
        self.assertEqual(view["conversation_model"]["managed_by"], "codex")
        self.assertEqual(view["conversation_model"]["selected_by"],
                         "controlling_host")
        self.assertEqual(set(view["roles"]),
                         {"architect", "explorer", "implementer", "reviewer"})
        self.assertEqual(view["roles"]["architect"]["pinned"]["model"],
                         "gpt-test")
        self.assertEqual(view["roles"]["implementer"]["billing"], "go")
        self.assertIn("antigravity", view["architect_hosts"])
        self.assertFalse(view["architect_hosts"]["antigravity"]["configured"])
        self.assertEqual(view["next"], orc.next_action_for(self.state))

    # -- automatic progression and consultation -------------------------
    def test_high_risk_multi_writer_plan_needs_no_approval(self):
        checks = [[sys.executable, "-c", "raise SystemExit(0)"]]
        writers = [{"id": "a", "goal": "A", "paths": ["a.py"],
                    "components": [], "completion_criteria": "A done",
                    "role": "implementer"},
                   {"id": "b", "goal": "B", "paths": ["b.py"],
                    "components": [], "completion_criteria": "B done",
                    "role": "implementer"},
                   {"id": "c", "goal": "C", "paths": ["c.py"],
                    "components": [], "completion_criteria": "C done",
                    "role": "implementer"}]
        plan = plan_report(checks)
        plan["batches"][0]["writers"] = writers
        self.state.update({"phase": "plan", "plan": None,
                           "max_parallel_writers": 3,
                           "parallel_permission": {"max_writers": 3,
                                                   "enabled": True}})
        with patch.object(orc, "strong_call", return_value=plan), \
                patch.object(orc, "permission_preflight",
                             return_value={"ok": True, "missing": []}):
            orc.advance(self.rundir, self.state, self.cfg, deadline=None)
        folder, state = orc.load("test-run00")
        self.assertFalse(state["plan_approval"])
        self.assertNotEqual(state["status"], "awaiting_plan_approval")
        self.assertIn(state["phase"], {"explore", "implement"})
        self.assertTrue(state["plan_authority"]["approved"])
        progression = orc.progression_view(state)
        self.assertTrue(progression["automatic"])
        self.assertFalse(progression["consultation_required"])
        self.assertEqual(progression["recovery"]["class"], "advance")

    def _awaiting_consultation(self):
        plan = plan_report([[sys.executable, "-c", "raise SystemExit(0)"]])
        self.state.update({
            "phase": "implement", "status": "awaiting_plan_approval",
            "plan_approval": True, "plan": plan,
            "plan_version": orc.content_hash(plan), "plan_revision": 2,
            "amendment_epoch": 0,
            "plan_authority": {"plan_version": orc.content_hash(plan),
                               "plan_revision": 2, "amendment_epoch": 0,
                               "approved": False, "source": "architect_plan"}})
        orc.save(self.rundir, self.state)
        return plan

    def test_consultation_accept_needs_no_terminal_command(self):
        self._awaiting_consultation()
        status = orc.status_run("test-run00")
        self.assertEqual(status["next_action"], "orchestrator_consult")
        self.assertEqual(status["consultation"]["status"], "awaiting_user")
        with patch.object(orc, "permission_preflight",
                          return_value={"ok": True, "missing": []}):
            result = orc.answer_consultation("test-run00", "approve")
        self.assertEqual(result["decision"], "accept")
        folder, state = orc.load("test-run00")
        self.assertEqual(state["status"], "running")
        self.assertEqual(state["consultation"]["response"], "approve")
        self.assertEqual(state["plan_authority"]["source"],
                         "user_consultation_accept")
        self.assertTrue(state["plan_authority"]["approved"])

    def test_consultation_material_reply_versions_the_plan(self):
        plan = self._awaiting_consultation()
        result = orc.answer_consultation("test-run00", "Use SQLite instead.")
        self.assertEqual(result["decision"], "amend")
        self.assertTrue(result["persisted"])
        folder, state = orc.load("test-run00")
        self.assertEqual(state["status"], "paused")
        self.assertEqual(state["phase"], "plan")
        self.assertIsNone(state["plan"])
        self.assertEqual(state["consultation"]["response"], "Use SQLite instead.")
        requirements = orc.user_requirements(state)
        self.assertIn("Use SQLite instead.",
                      [item.get("text") for item in requirements["amendments"]])
        stale = orc.consultation_view(state)
        # The answered consultation refers to the superseded plan, so it is
        # now visibly stale rather than silently reusable.
        self.assertEqual(stale["status"], "stale")
        self.assertTrue(stale["stale"])
        self.assertFalse((state.get("plan_authority") or {}).get("approved", False))

    def test_consultation_cannot_be_created_for_an_ordinary_run(self):
        self.state.update({"status": "awaiting_plan_approval",
                           "phase": "implement", "plan_approval": False})
        orc.save(self.rundir, self.state)
        with self.assertRaisesRegex(RuntimeError, "did not request"):
            orc.answer_consultation("test-run00", "approve")

    def test_answered_consultation_is_stale_after_a_new_plan_revision(self):
        self._awaiting_consultation()
        with patch.object(orc, "permission_preflight",
                          return_value={"ok": True, "missing": []}):
            orc.answer_consultation("test-run00", "approve")
        folder, state = orc.load("test-run00")
        self.assertFalse(orc.consultation_view(state)["stale"])
        state["plan_version"] = "a-different-plan"
        self.assertTrue(orc.consultation_view(state)["stale"])
        self.assertEqual(orc.consultation_view(state)["status"], "stale")

    # -- run-scoped check authority --------------------------------------
    def _plan_with_script_check(self):
        script = self.project / "scripts" / "tests" / "local_check.py"
        script.parent.mkdir(parents=True)
        script.write_text("print('ok')\n")
        argv = [sys.executable, "scripts/tests/local_check.py"]
        plan = plan_report([argv])
        self.state.update({"plan": plan, "phase": "verify",
                           "plan_version": orc.content_hash(plan),
                           "plan_revision": 3, "amendment_epoch": 0,
                           "batch_index": 0, "status": "running"})
        orc.save(self.rundir, self.state)
        return argv, plan

    def test_routine_check_exception_is_narrow_and_run_scoped(self):
        argv, plan = self._plan_with_script_check()
        base = orc.verification_command_policy(argv, self.cfg,
                                               project=self.project)
        self.assertFalse(base["allowed"])
        self.assertIn("arbitrary_script", base["rejected_reasons"])

        records = orc.ensure_routine_check_exceptions(
            self.state, self.cfg, self.project)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["authorization_kind"], "automatic")
        self.assertEqual(records[0]["scope"], "run")
        decision = orc.verification_command_policy(
            argv, self.cfg, project=self.project, state=self.state)
        self.assertTrue(decision["allowed"])
        self.assertEqual(decision["exception"]["source"],
                         "run_scoped_exception")
        self.assertEqual(decision["exception"]["argv_sha256"],
                         records[0]["argv_sha256"])

        # Another saved run cannot inherit it.
        other = {"id": "other-run", "project": str(self.project),
                 "plan_version": self.state["plan_version"],
                 "plan_revision": 3, "amendment_epoch": 0,
                 "check_exceptions": copy.deepcopy(records)}
        self.assertIsNone(orc.run_scoped_check_exception(
            other, argv, self.project))
        # A new plan revision invalidates the old exception.
        revised = copy.deepcopy(self.state)
        revised["plan_revision"] = 4
        self.assertIsNone(orc.run_scoped_check_exception(
            revised, argv, self.project))
        # A different checkout cannot reuse it.
        self.assertIsNone(orc.run_scoped_check_exception(
            self.state, argv, self.root / "elsewhere"))

    def test_manual_check_exception_needs_a_human_terminal(self):
        argv, _plan = self._plan_with_script_check()
        token = "check-exception:test-run00:" + orc.content_hash(list(argv))[:12]
        # A model-owned worker context is refused before any state write.
        with patch.dict(os.environ, {"ABDULLAH_RUN_ID": "test-run00"}):
            with self.assertRaisesRegex(RuntimeError, "worker context"):
                orc.grant_check_exception(
                    "test-run00", argv, reason="needed", authorized_by="agent",
                    confirmation=token)
        self.assertFalse((orc.load("test-run00")[1].get("check_exceptions")))
        # A non-interactive shell cannot self-grant even with the right token.
        with _human_operator_env(), patch.object(orc.sys, "stdin", _NoTty()):
            with self.assertRaisesRegex(RuntimeError, "interactive operator"):
                orc.grant_check_exception(
                    "test-run00", argv, reason="needed", authorized_by="agent",
                    confirmation=token)
        # A typed, exact confirmation from an operator terminal is accepted.
        with _human_operator_env(), patch.object(orc.sys, "stdin", _FakeTty()):
            with self.assertRaisesRegex(RuntimeError, "Confirmation mismatch"):
                orc.grant_check_exception(
                    "test-run00", argv, reason="needed", authorized_by="agent",
                    confirmation="check-exception:test-run00:deadbeef")
            granted = orc.grant_check_exception(
                "test-run00", argv, reason="needed", authorized_by="operator",
                confirmation=token)
        self.assertEqual(granted["exception"]["authorization_kind"], "operator")
        _folder, state = orc.load("test-run00")
        self.assertEqual(len(state["check_exceptions"]), 1)

    def test_check_exception_refuses_dangerous_argv(self):
        for argv in (["git", "push"], ["curl", "https://example.com"],
                     ["python3", "-c", "print('TOKEN=1')"],
                     ["npm", "publish"], ["rm", "-rf", "build"]):
            self.assertIsNotNone(orc._check_exception_refusal(argv), argv)
        self.assertIsNone(orc._check_exception_refusal(
            [sys.executable, "-m", "unittest", "discover"]))

    def test_shell_wrapper_checks_are_never_auto_excepted(self):
        argv = ["bash", "-c", "python3 -m unittest"]
        plan = plan_report([argv])
        self.state.update({"plan": plan,
                           "plan_version": orc.content_hash(plan),
                           "plan_revision": 1})
        records = orc.ensure_routine_check_exceptions(
            self.state, self.cfg, self.project)
        self.assertEqual(records, [])

    # -- execution visibility -------------------------------------------
    def test_environment_line_uses_real_observations(self):
        info = orc.execution_environment(self.project)
        self.assertTrue(info["label"].startswith("Running in "))
        self.assertIn(os.path.realpath(str(self.project)), info["label"])
        if info["wsl"]:
            self.assertIn("WSL", info["label"])
        if info["distro"]:
            self.assertIn(info["distro"], info["label"])
        if sys.platform != "win32":
            self.assertNotIn("native Windows", info["label"])
        status = orc.status_run("test-run00")
        self.assertEqual(status["execution_environment"]["project"],
                         os.path.realpath(str(self.project)))
        # Doctor is exercised by its own host-specific test; here only the
        # environment projection must be status-visible.
        self.assertIn("execution_environment", status)
        # The read-only terminal viewer carries the same line, so a coordinator
        # cannot mislabel a WSL supervisor from a Windows desktop chat.
        lines = orc._viewer_lines({"id": "test-run00", "status": "running",
                                  "project": str(self.project)},
                                 {"available": False, "next": {}})
        self.assertEqual(lines[1], info["label"])
        self.assertTrue(lines[0].startswith("run test-run00"))
        self.assertLessEqual(len(lines), 11)

    # -- bounded recovery -------------------------------------------------
    def test_bounded_recovery_classification_and_stopping_conditions(self):
        # A live stage is monitored, never re-dispatched.
        self.state.update({"status": "running", "phase": "implement",
                           "active_job": {"status": "running"}})
        monitor = orc.recovery_classification(self.state)
        self.assertEqual(monitor["class"], "monitor")
        self.assertEqual(monitor["next_action"], "orchestrator_status")

        # An uncertain attempt is reconciled before any retry.
        self.state.update({"active_job": {"status": "uncertain"},
                           "status": "uncertain"})
        self.assertEqual(orc.recovery_classification(self.state)["class"],
                         "reconcile")

        # A supported recoverable pause resumes without asking the user.
        self.state.update({"status": "paused", "active_job": None,
                           "pause_reason": "rate limited; retry is safe"})
        recoverable = orc.recovery_classification(self.state)
        self.assertEqual(recoverable["class"], "resume")
        self.assertEqual(recoverable["next_action"], "orchestrator_resume")
        self.assertTrue(recoverable["bounded"])

        # Sensitive authorization stays a human stopping condition.
        self.state.update({"status": "blocked",
                           "pause_reason": "usage-billed route needs authorization"})
        sensitive = orc.recovery_classification(self.state)
        self.assertEqual(sensitive["class"], "human_authorization")
        self.assertIn("authorize-route", sensitive["next_action"])
        self.assertTrue(orc.recovery_classification(self.state)["bounded"])

        # Final and cancelled runs need nothing further.
        for status in ("complete", "cancelled"):
            self.state.update({"status": status, "active_job": None})
            self.assertEqual(orc.recovery_classification(self.state)["class"],
                             "none")

    def test_saved_legacy_run_loads_and_reports_new_surfaces(self):
        # A pre-upgrade state has none of the new progression/consultation or
        # exception keys; loading it must still yield a safe next action.
        legacy = copy.deepcopy(self.state)
        for key in ("progression", "consultation", "check_exceptions",
                    "recovery"):
            legacy.pop(key, None)
        orc.save(self.rundir, legacy)
        _folder, loaded = orc.load("test-run00")
        self.assertNotIn("progression", loaded)
        status = orc.status_run("test-run00")
        self.assertIn("progression", status)
        self.assertTrue(status["progression"]["automatic"])
        self.assertEqual(status["execution_environment"]["project"],
                         os.path.realpath(str(self.project)))

    def test_dispatched_worker_cannot_start_a_recursive_run(self):
        # The recursion guard fires before config, state, lease or billing.
        with patch.dict(os.environ, {"ABDULLAH_AGENT_CONTEXT": "architect"}), \
                patch.object(orc, "observe_configuration",
                             side_effect=AssertionError("config was read")):
            with self.assertRaisesRegex(RuntimeError, "Recursive supervisor"):
                orc.create_run(project=self.project, goal="nested", host="codex",
                               skip_doctor=True)
        with patch.dict(os.environ, {"ABDULLAH_PARENT_JOB": "job-1"}), \
                patch.object(orc, "observe_configuration",
                             side_effect=AssertionError("config was read")):
            with self.assertRaisesRegex(RuntimeError, "Recursive supervisor"):
                orc.create_run(project=self.project, goal="nested", host="codex",
                               skip_doctor=True)

    def test_existing_hosts_remain_usable_without_antigravity(self):
        cfg = orc.read_json(orc.HERE / "config.example.json")
        self.assertNotIn("antigravity", cfg.get("architect", {}))
        orc._validated_config(cfg)
        with patch.object(orc, "validate_route_metadata",
                          return_value={"state": "unavailable"}):
            view = orc.model_configuration()
        self.assertTrue(view["roles"]["explorer"]["model"])
        self.assertFalse(view["architect_hosts"]["antigravity"]["configured"])
        self.assertTrue(view["architect_hosts"]["codex"]["configured"])


if __name__ == "__main__":
    unittest.main()
