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
orc = baseline.orc


SECRET = "sk-v31-super-secret-value"


class DispatchSafetyTests(unittest.TestCase):
    setUp = baseline.ControlTests.setUp
    tearDown = baseline.ControlTests.tearDown

    def setUp(self):
        baseline.ControlTests.setUp(self)
        self.addCleanup(lambda: os.environ.pop("OPENAI_API_KEY", None))
        self.addCleanup(lambda: os.environ.pop("ANTHROPIC_API_KEY", None))
        bin_dir = self.root / "safety-bin"
        bin_dir.mkdir()
        fake = bin_dir / "fake-cli.py"
        fake.write_text("#!/usr/bin/env python3\n"
                        "import sys\n"
                        "print('1.18.35' if '--version' in sys.argv else "
                        "'--agent --model --format --auto --session --variant "
                        "--output-schema --output-last-message --json-schema')\n")
        fake.chmod(0o755)
        for name in ("opencode", "codex", "claude"):
            (bin_dir / name).symlink_to(fake)
        env_patch = patch.dict(os.environ, {
            "PATH": str(bin_dir) + ":" + os.environ["PATH"]})
        env_patch.start()
        self.addCleanup(env_patch.stop)

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
        home = self.root / "aws-inert-home"
        home.mkdir()
        env = {name: "" for name in orc.CLAUDE_BILLING_ENV}
        env.update({"HOME": str(home), "AWS_ACCESS_KEY_ID": "ambient",
                    "AWS_SECRET_ACCESS_KEY": "ambient", "ANTHROPIC_API_KEY": ""})
        with patch.dict(os.environ, env):
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

    def claude_preflight(self, extra=None, project=None):
        env = {name: "" for name in orc.CLAUDE_BILLING_ENV}
        env.update({name: "" for name in orc.INERT_CLOUD_ENV})
        env.update(extra or {})
        with patch.dict(os.environ, env):
            return orc.route_preflight(
                "architect", {"provider": "claude", "model": "claude-opus-5-5",
                              "effort": "high", "billing": "subscription"},
                self.cfg, project or self.project, self.state)

    def test_claude_alternate_config_dir_endpoint_blocks_subscription(self):
        home = self.root / "claude-home"
        alt = self.root / "claude-alt"
        alt.mkdir(parents=True)
        (alt / "settings.json").write_text(json.dumps({
            "apiKeyHelper": "/bin/print-secret",
            "env": {"ANTHROPIC_BASE_URL": "https://custom.invalid"}}))
        result = self.claude_preflight({"HOME": str(home),
                                        "CLAUDE_CONFIG_DIR": str(alt)})
        self.assertFalse(result["ok"])
        self.assertTrue(any("ANTHROPIC_BASE_URL" in reason
                            for reason in result["reasons"]))
        self.assertTrue(any("apiKeyHelper" in reason for reason in result["reasons"]))
        self.assertNotIn("custom.invalid", json.dumps(result))
        self.assertNotIn("/bin/print-secret", json.dumps(result))

    def test_clean_alternate_config_directory_is_inspected_not_auto_rejected(self):
        home = self.root / "claude-clean-alt-home"
        alt = self.root / "claude-clean-alt"
        alt.mkdir(parents=True)
        (alt / "settings.json").write_text(json.dumps({"theme": "dark"}))
        result = self.claude_preflight({"HOME": str(home),
                                        "CLAUDE_CONFIG_DIR": str(alt)})
        self.assertTrue(result["ok"], result["reasons"])
        self.assertEqual(result["observed"]["config_dir"], str(alt))

    def test_provider_managed_host_and_fallback_settings_block_subscription(self):
        home = self.root / "claude-managed-home"
        (home / ".claude").mkdir(parents=True)
        settings = home / ".claude/settings.json"
        settings.write_text(json.dumps({"fallbackModel": ["claude-haiku-4-5"]}))
        result = self.claude_preflight(
            {"HOME": str(home),
             "CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST": "1"})
        self.assertFalse(result["ok"])
        self.assertTrue(any("PROVIDER_MANAGED_BY_HOST" in reason
                            for reason in result["reasons"]))
        self.assertTrue(any("fallbackModel" in reason for reason in result["reasons"]))

    def test_managed_settings_and_model_routing_keys_block_subscription(self):
        home = self.root / "claude-clean-home"
        home.mkdir()
        managed = self.root / "managed-settings.json"
        managed.write_text(json.dumps({"apiKeyHelper": "/bin/print-secret"}))
        with patch.object(orc, "CLAUDE_MANAGED_SETTINGS_FILES", (managed,)):
            result = self.claude_preflight({"HOME": str(home)})
        self.assertFalse(result["ok"])
        self.assertTrue(any("apiKeyHelper" in reason for reason in result["reasons"]))
        self.assertNotIn("/bin/print-secret", json.dumps(result))

    def test_malformed_effective_claude_settings_fail_closed_and_doctor_agrees(self):
        home = self.root / "claude-broken-home"
        (home / ".claude").mkdir(parents=True)
        (home / ".claude/settings.json").write_text("{not json")
        result = self.claude_preflight({"HOME": str(home)})
        self.assertFalse(result["ok"])
        self.assertTrue(any("unreadable" in reason for reason in result["reasons"]))
        with patch.dict(os.environ, {"HOME": str(home)}):
            checks = orc.doctor(self.project, "claude")
        self.assertFalse(checks["billing_preflight"]["architect"]["ok"])

    def test_post_doctor_contamination_is_rechecked_at_dispatch(self):
        home = self.root / "claude-contaminate-home"
        (home / ".claude").mkdir(parents=True)
        clean = self.claude_preflight({"HOME": str(home)})
        self.assertTrue(clean["ok"], clean["reasons"])
        (home / ".claude/settings.json").write_text(json.dumps({
            "env": {"ANTHROPIC_AUTH_TOKEN": SECRET}}))
        contaminated = self.claude_preflight({"HOME": str(home)})
        self.assertFalse(contaminated["ok"])
        self.assertNotIn(SECRET, json.dumps(contaminated))

    def managed_preflight(self, managed, extra=None):
        home = self.root / "managed-home"
        home.mkdir(exist_ok=True)
        env = {"HOME": str(home)}
        env.update(extra or {})
        with patch.object(orc, "CLAUDE_MANAGED_SETTINGS_FILES", (managed,)):
            return self.claude_preflight(env)

    def managed_layout(self, base_present=False):
        index = getattr(self, "_managed_index", 0)
        self._managed_index = index + 1
        managed = self.root / f"managed-policy-{index}" / "managed-settings.json"
        managed.parent.mkdir(parents=True)
        dropins = managed.parent / "managed-settings.d"
        dropins.mkdir()
        if base_present:
            managed.write_text(json.dumps({"apiKeyHelper": "/bin/print-secret"}))
        return managed, dropins

    def test_managed_dropin_is_inspected_when_base_file_is_absent(self):
        managed, dropins = self.managed_layout(base_present=False)
        (dropins / "10-route.json").write_text(json.dumps({
            "env": {"ANTHROPIC_BASE_URL": "https://" + SECRET + ".invalid"}}))
        result = self.managed_preflight(managed)
        self.assertFalse(result["ok"])
        reasons = " ".join(result["reasons"])
        self.assertIn("10-route.json", reasons)
        self.assertIn("ANTHROPIC_BASE_URL", reasons)
        self.assertNotIn(SECRET, json.dumps(result))
        env = {name: "" for name in orc.CLAUDE_BILLING_ENV}
        env["HOME"] = str(self.root / "dropin-home")
        (self.root / "dropin-home").mkdir()
        with patch.dict(os.environ, env), \
                patch.object(orc, "CLAUDE_MANAGED_SETTINGS_FILES", (managed,)):
            with self.assertRaisesRegex(RuntimeError, "preflight"):
                orc.call_model(self.rundir, self.state, self.cfg, "architect",
                               "plan", "prompt", self.project, host="claude")
        self.assertIsNone(self.state["active_job"])
        for path in self.rundir.rglob("*"):
            if path.is_file():
                self.assertNotIn(SECRET, path.read_text(errors="replace"), str(path))

    def test_managed_dropins_are_ordered_and_hidden_or_non_json_ignored(self):
        managed, dropins = self.managed_layout(base_present=True)
        (dropins / "20-endpoint.json").write_text(json.dumps({
            "env": {"ANTHROPIC_AUTH_TOKEN": "placeholder"}}))
        (dropins / "10-model.json").write_text(json.dumps({"model": "claude-haiku"}))
        (dropins / ".hidden.json").write_text(json.dumps({"apiKeyHelper": "/bin/x"}))
        (dropins / "notes.txt").write_text("not policy")
        result = self.managed_preflight(managed)
        self.assertFalse(result["ok"])
        reasons = " ".join(result["reasons"])
        self.assertIn("apiKeyHelper", reasons)
        self.assertIn("ANTHROPIC_AUTH_TOKEN", reasons)
        self.assertIn("model", reasons)
        managed_entries = [entry for entry in result["observed"]["settings"]
                           if str(entry["scope"]).startswith("managed")]
        names = [Path(entry["path"]).name for entry in managed_entries]
        self.assertEqual(names, ["managed-settings.json", "10-model.json",
                                 "20-endpoint.json"])

    def test_malformed_and_non_object_managed_dropins_fail_closed(self):
        cases = {"bad-json": "{not json", "array": "[]"}
        for name, text in cases.items():
            with self.subTest(name=name):
                managed, dropins = self.managed_layout(base_present=False)
                (dropins / f"{name}.json").write_text(text)
                result = self.managed_preflight(managed)
                self.assertFalse(result["ok"])
                self.assertIn(name, " ".join(result["reasons"]))

    @unittest.skipIf(os.geteuid() == 0, "root ignores file permissions")
    def test_unreadable_managed_dropin_fails_closed(self):
        managed, dropins = self.managed_layout(base_present=False)
        secret_file = dropins / "10-secret.json"
        secret_file.write_text(json.dumps({"env": {
            "ANTHROPIC_BASE_URL": "https://" + SECRET + ".invalid"}}))
        secret_file.chmod(0)
        self.addCleanup(secret_file.chmod, 0o600)
        result = self.managed_preflight(managed)
        self.assertFalse(result["ok"])
        reasons = " ".join(result["reasons"])
        self.assertIn("10-secret.json", reasons)
        self.assertIn("unreadable", reasons)
        self.assertNotIn(SECRET, json.dumps(result))

    def test_unreadable_managed_directory_fails_closed(self):
        managed, dropins = self.managed_layout(base_present=False)
        with patch.object(orc.os, "scandir", side_effect=PermissionError("denied")):
            result = self.managed_preflight(managed)
        self.assertFalse(result["ok"])
        reasons = " ".join(result["reasons"])
        self.assertIn("managed-settings.d", reasons)
        self.assertIn("unreadable", reasons)

    def test_clean_dropin_and_authorized_alternate_classification(self):
        for name, payload in (("10-theme.json", {"theme": "dark"}),
                              ("20-clean.json", {"env": {}})):
            with self.subTest(name=name):
                managed, dropins = self.managed_layout(base_present=False)
                (dropins / name).write_text(json.dumps(payload))
                clean = self.managed_preflight(managed)
                self.assertTrue(clean["ok"], clean["reasons"])
                self.assertEqual(clean["classification"], "subscription")
                self.addCleanup(lambda: [p.unlink() for p in dropins.glob("*.json")])
        managed, dropins = self.managed_layout(base_present=False)
        (dropins / "10-route.json").write_text(json.dumps({
            "env": {"ANTHROPIC_BASE_URL": "https://authorized.invalid"}}))
        alternate = {"provider": "claude", "model": "claude-opus-5-5",
                     "effort": "high", "billing": "api"}
        self.state["route_authorizations"] = [{
            "id": "claude-dropin-api", "role": "architect",
            "route_sha256": orc.route_authorization_sha(alternate),
            "max_dispatches": 1, "used": 0,
            "attestation": "authorized alternate API route",
            "actor": {"user": "operator"}}]
        with patch.object(orc, "CLAUDE_MANAGED_SETTINGS_FILES", (managed,)):
            env = {name: "" for name in orc.CLAUDE_BILLING_ENV}
            env.update({"HOME": str(self.root / "dropin-home"),
                        "ANTHROPIC_BASE_URL": "https://authorized.invalid"})
            with patch.dict(os.environ, env):
                authorized = orc.route_preflight(
                    "architect", alternate, self.cfg, self.project, self.state)
        self.assertTrue(authorized["ok"], authorized["reasons"])
        self.assertEqual(authorized["classification"], "api")

    def test_clean_subscription_passes_and_authorized_alternate_remains_available(self):
        home = self.root / "claude-empty-home"
        home.mkdir()
        clean = self.claude_preflight({"HOME": str(home)})
        self.assertTrue(clean["ok"], clean["reasons"])
        alternate = {"provider": "claude", "model": "claude-opus-5-5",
                     "effort": "high", "billing": "api"}
        self.state["route_authorizations"] = [{
            "id": "claude-api", "role": "architect",
            "route_sha256": orc.route_authorization_sha(alternate),
            "max_dispatches": 1, "used": 0,
            "attestation": "authorized alternate API route",
            "actor": {"user": "operator"}}]
        env = {name: "" for name in orc.CLAUDE_BILLING_ENV}
        env.update({"HOME": str(home), "ANTHROPIC_BASE_URL": "https://authorized.invalid"})
        with patch.dict(os.environ, env):
            result = orc.route_preflight("architect", alternate, self.cfg,
                                         self.project, self.state)
        self.assertTrue(result["ok"], result["reasons"])

    def test_claude_hazard_is_durable_and_never_spawns_or_counts_a_call(self):
        home = self.root / "claude-block-home"
        (home / ".claude").mkdir(parents=True)
        (home / ".claude/settings.json").write_text(json.dumps({
            "env": {"ANTHROPIC_BASE_URL": "https://" + SECRET + ".invalid"}}))
        env = {name: "" for name in orc.CLAUDE_BILLING_ENV}
        env.update({"HOME": str(home)})
        with patch.dict(os.environ, env):
            with self.assertRaisesRegex(RuntimeError, "preflight"):
                orc.call_model(self.rundir, self.state, self.cfg, "architect",
                               "plan", "prompt", self.project, host="claude")
        self.assertIsNone(self.state["active_job"])
        self.assertEqual(orc._usage_state(self.state)["strong_calls"], 0)
        self.assertFalse((self.rundir / "jobs").exists() and any(
            (self.rundir / "jobs").glob("plan-*")))
        for path in self.rundir.rglob("*"):
            if path.is_file():
                self.assertNotIn(SECRET, path.read_text(errors="replace"), str(path))

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
