"""v3.1 dispatch safety: explicit host, shared route/billing preflight."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_orchestrator as baseline
from test_orchestrator import ControlTests, orc


SECRET = "sk-v31-super-secret-value"


class DispatchSafetyTests(ControlTests):
    def setUp(self):
        ControlTests.setUp(self)
        self.addCleanup(lambda: os.environ.pop("OPENAI_API_KEY", None))
        self.addCleanup(lambda: os.environ.pop("ANTHROPIC_API_KEY", None))

    def outlook(self):
        return [path for path in self.root.rglob("*")
                if path.is_file() and path.suffix in {".json", ".jsonl", ".log"}]

    def test_missing_or_invalid_host_is_refused_before_any_state_write(self):
        before = set((self.root / "runs").rglob("*")) if (self.root / "runs").exists() else set()
        for host in (None, "", "gpt", "Codex"):
            with self.subTest(host=host):
                with self.assertRaisesRegex(ValueError, "explicit controlling host"):
                    orc.create_run(project=str(self.project), goal="host safety",
                                   host=host, skip_doctor=True)
        after = set((self.root / "runs").rglob("*")) if (self.root / "runs").exists() else set()
        self.assertEqual(before, after)

    def test_mcp_start_requires_host_and_resume_rejects_a_contradiction(self):
        response = orc.mcp_handle({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "orchestrator_start",
                       "arguments": {"project": str(self.project), "goal": "g"}}})
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertFalse(payload["ok"])
        self.assertIn("host", payload["error"])
        self.state["host"] = "codex"
        self.state["status"] = "paused"
        orc.save(self.rundir, self.state)
        with self.assertRaisesRegex(RuntimeError, "contradicts"):
            orc.resume_run("test-run00", host="claude")

    def test_status_reports_persisted_host_and_resolved_route_separately(self):
        self.state.update(host="claude", phase="plan",
                          model_routes={"architect": {
                              "provider": "claude", "model": "claude-opus-5-5",
                              "effort": "high", "billing": "subscription"}})
        orc.save(self.rundir, self.state)
        status = orc.status_run("test-run00")
        self.assertEqual(status["host"], "claude")
        self.assertEqual(status["route"]["provider"], "claude")
        self.assertEqual(status["route"]["role"], "architect")
        self.assertEqual(status["route"]["model"], "claude-opus-5-5")

    def test_subscription_api_key_rejection_is_durable_and_secret_free(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": SECRET}):
            with self.assertRaisesRegex(RuntimeError, "preflight"):
                orc.call_model(self.rundir, self.state, self.cfg, "architect", "plan",
                               "prompt", self.project, host="claude")
        self.assertIsNone(self.state["active_job"])
        self.assertEqual(orc._usage_state(self.state)["strong_calls"], 0)
        self.assertEqual(self.state["status"], "blocked")
        rejection = self.state["preflight_rejection"]
        self.assertTrue(rejection["path"])
        self.assertFalse(any(path.name.startswith("plan-")
                             for path in (self.rundir / "jobs").glob("*")))
        for path in self.outlook():
            try:
                text = path.read_text(errors="replace")
            except OSError:
                continue
            self.assertNotIn(SECRET, text, str(path))

    def test_provider_flags_and_endpoint_overrides_fail_closed(self):
        cases = ["CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_MANTLE",
                 "CLAUDE_CODE_USE_ANTHROPIC_AWS", "ANTHROPIC_BASE_URL",
                 "ANTHROPIC_AUTH_TOKEN"]
        for name in cases:
            with self.subTest(name=name), patch.dict(os.environ, {name: "configured"}):
                result = orc.route_preflight("architect", {
                    "provider": "claude", "model": "claude-opus-5-5",
                    "effort": "high", "billing": "subscription"}, self.cfg,
                    self.project, self.state)
                self.assertFalse(result["ok"])
                self.assertTrue(any(name in reason for reason in result["reasons"]))

    def test_ambient_aws_credentials_are_inert_without_a_provider_selection(self):
        with patch.dict(os.environ, {"AWS_ACCESS_KEY_ID": "ambient",
                                     "AWS_SECRET_ACCESS_KEY": "ambient",
                                     "ANTHROPIC_API_KEY": ""}):
            result = orc.route_preflight("architect", {
                "provider": "claude", "model": "claude-opus-5-5",
                "effort": "high", "billing": "subscription"}, self.cfg,
                self.project, self.state)
        self.assertTrue(result["ok"], result["reasons"])
        self.assertIn("AWS_ACCESS_KEY_ID", result["observed"]["inert_cloud"])

    def test_runtime_environment_change_after_doctor_is_rechecked_at_dispatch(self):
        route = {"provider": "codex", "model": "gpt-6.1-sol", "effort": "high",
                 "billing": "subscription"}
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            clean = orc.route_preflight("architect", route, self.cfg,
                                        self.project, self.state)
        self.assertTrue(clean["ok"])
        with patch.dict(os.environ, {"OPENAI_API_KEY": SECRET}):
            changed = orc.route_preflight("architect", route, self.cfg,
                                          self.project, self.state)
        self.assertFalse(changed["ok"])
        self.assertTrue(any("OPENAI_API_KEY" in reason
                            for reason in changed["reasons"]))

    def test_settings_helpers_and_malformed_settings_fail_closed(self):
        home = self.root / "home"
        (home / ".claude").mkdir(parents=True)
        settings = home / ".claude/settings.json"
        settings.write_text(json.dumps({"apiKeyHelper": "/bin/print-secret",
                                        "env": {"ANTHROPIC_BASE_URL": "https://example"}}))
        with patch.dict(os.environ, {"HOME": str(home), "ANTHROPIC_API_KEY": ""}):
            result = orc.route_preflight("architect", {
                "provider": "claude", "model": "claude-opus-5-5",
                "effort": "high", "billing": "subscription"}, self.cfg,
                self.project, self.state)
        self.assertFalse(result["ok"])
        self.assertTrue(any("apiKeyHelper" in reason for reason in result["reasons"]))
        self.assertNotIn("/bin/print-secret", json.dumps(result))
        settings.write_text("{not json")
        with patch.dict(os.environ, {"HOME": str(home), "ANTHROPIC_API_KEY": ""}):
            result = orc.route_preflight("architect", {
                "provider": "claude", "model": "claude-opus-5-5",
                "effort": "high", "billing": "subscription"}, self.cfg,
                self.project, self.state)
        self.assertFalse(result["ok"])
        self.assertTrue(any("unreadable" in reason for reason in result["reasons"]))

    def test_unapproved_api_route_fails_before_spawn_and_approved_is_bounded(self):
        route = {"provider": "opencode", "worker_provider": "opencode-zen",
                 "model": "opencode-zen/some-model", "effort": "high",
                 "billing": "api"}
        self.state["model_routes"] = {"implementer": route}
        orc.save(self.rundir, self.state)
        self.cfg["workers"]["implementer"] = {
            "provider": "opencode-zen", "model": "opencode-zen/some-model",
            "variant": "high", "billing": "api"}
        result = orc.route_preflight("implementer", route, self.cfg,
                                     self.project, self.state)
        self.assertFalse(result["ok"])
        self.assertIn("authorize-route", " ".join(result["reasons"]))
        with self.assertRaisesRegex(RuntimeError, "preflight"):
            orc.call_model(self.rundir, self.state, self.cfg, "implementer",
                           "implementer", "prompt", self.project)
        self.assertIsNone(self.state["active_job"])
        grant = {
            "id": "grant1", "role": "implementer",
            "route_sha256": orc.route_authorization_sha(route),
            "max_dispatches": 2, "used": 0, "attestation": "reviewed api endpoint",
            "actor": {"user": "tester"}, "at": orc.now()}
        self.state["route_authorizations"] = [grant]
        home = self.root / "api-empty-home"
        home.mkdir(exist_ok=True)
        with patch.dict(os.environ, {"HOME": str(home)}):
            result = orc.route_preflight("implementer", route, self.cfg,
                                         self.project, self.state)
        self.assertTrue(result["ok"], result["reasons"])
        self.assertTrue(result["authorization"]["authorized"])
        reserved = orc.reserve_route_grant(self.state, self.rundir, "implementer", route)
        self.assertEqual(reserved["used"], 1)
        orc.release_route_grant(self.state, self.rundir, "implementer", route,
                                "launch never attempted")
        state = orc.read_json(self.rundir / "state.json")
        self.assertEqual(state["route_authorizations"][0]["used"], 0)

    def test_free_or_local_route_requires_attested_grant(self):
        home = self.root / "empty-home"
        home.mkdir()
        for billing in ("free", "local"):
            with self.subTest(billing=billing), patch.dict(os.environ, {"HOME": str(home)}):
                route = {"provider": "opencode", "worker_provider": "local",
                         "model": "local/model", "effort": "",
                         "billing": billing}
                result = orc.route_preflight("explorer", route, self.cfg,
                                             self.project, self.state)
                self.assertFalse(result["ok"])
                self.assertTrue(any("authorize-route" in reason
                                    for reason in result["reasons"]))

    def test_repeated_rejection_creates_no_active_job_or_reconciliation_work(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": SECRET}):
            for _ in range(2):
                with self.assertRaises(RuntimeError):
                    orc.call_model(self.rundir, self.state, self.cfg, "architect",
                                   "plan", "prompt", self.project)
        self.assertIsNone(self.state["active_job"])
        self.assertEqual(self.state["failed_jobs"], [])
        self.assertEqual(orc._usage_state(self.state)["strong_calls"], 0)
        rejections = list((self.rundir / "jobs").glob("preflight-*.json"))
        self.assertGreaterEqual(len(rejections), 2)

    def test_spawn_failure_remains_distinct_from_preflight_rejection(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}), \
                patch.object(orc, "_spawn_guarded", side_effect=OSError("no exec")):
            with self.assertRaises(OSError):
                orc.call_model(self.rundir, self.state, self.cfg, "architect", "plan",
                               "prompt", self.project)
        self.assertNotIn("preflight_rejection", self.state)
        self.assertEqual(self.state["failed_jobs"][-1]["status"], "failed")
        self.assertIsNone(self.state["active_job"])

    def test_doctor_reports_the_same_preflight_hazard_without_inference(self):
        def probe(argv, **kwargs):
            if argv[-1] == "--version":
                return subprocess.CompletedProcess(argv, 0, stdout="1.18.35")
            if argv[-1] == "--help" and len(argv) > 3:
                return subprocess.CompletedProcess(argv, 0, stdout="help")
            if argv[:3] == ["opencode", "debug", "agent"]:
                role = argv[3].replace("abdullah-", "")
                profile = orc.opencode_profile(role, "v1")
                rules = []
                for permission, setting in profile["permission"].items():
                    for pattern, action in (setting.items() if isinstance(setting, dict)
                                            else [("*", setting)]):
                        rules.append({"permission": permission, "pattern": pattern,
                                      "action": action})
                return subprocess.CompletedProcess(
                    argv, 0, stdout=json.dumps({**profile, "permission": rules}))
            if argv[:3] == ["opencode", "run", "--help"]:
                return subprocess.CompletedProcess(
                    argv, 0, stdout="--agent --model --format --auto --session --variant")
            if argv[:3] == ["codex", "exec", "--help"]:
                return subprocess.CompletedProcess(
                    argv, 0, stdout="--output-schema --output-last-message --model "
                                    "--sandbox --config")
            if argv[:2] == ["opencode", "models"]:
                return subprocess.CompletedProcess(
                    argv, 0, stdout="opencode-go/deepseek-v4.1-flash\n"
                                    + json.dumps({"variants": {"low": {}, "high": {}}}))
            raise AssertionError(f"Unexpected probe {argv}")

        with patch.dict(os.environ, {"OPENAI_API_KEY": SECRET,
                                     "ANTHROPIC_API_KEY": ""}), \
                patch.object(orc, "source_snapshot",
                             return_value={"git_head": "a", "changed": {}}), \
                patch.object(orc.shutil, "which", return_value="/usr/bin/tool"), \
                patch.object(orc.subprocess, "run", side_effect=probe):
            checks = orc.doctor(self.project)
        self.assertFalse(checks["ready"])
        self.assertFalse(checks["billing_preflight"]["architect"]["ok"])
        self.assertTrue(any("OPENAI_API_KEY" in item
                            for item in checks["api_billing_risk"]))
        self.assertNotIn(SECRET, json.dumps(checks))


if __name__ == "__main__":
    unittest.main()
