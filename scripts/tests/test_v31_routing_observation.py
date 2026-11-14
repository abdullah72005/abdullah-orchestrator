"""v3.1 effective OpenCode routing observation and pinned fingerprint drift."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_orchestrator as baseline
orc = baseline.orc

FAKE_CLI = r'''#!/usr/bin/env python3
import json, pathlib, sys

def plan_report(batches):
    return {'contract_version': 2, 'status': 'complete', 'summary': 'plan',
            'invariants': ['Keep behavior'], 'blocker': '',
            'batches': [{'title': 'batch', 'goal': 'change', 'acceptance': ['works'],
                         'checks': [[sys.executable, '-c', 'pass']],
                         'risk': 'ordinary'} for _ in range(batches)]}

args = sys.argv[1:]
name = pathlib.Path(sys.argv[0]).name
if '--version' in args:
    print('1.18.35')
    sys.exit(0)
if name == 'opencode':
    if 'models' in args:
        print('opencode-zen/explorer-model')
        sys.exit(0)
    if '--help' in args:
        print('--agent --model --format --auto --session --variant')
        sys.exit(0)
    print(json.dumps({'type': 'text', 'sessionID': 'ses-fake',
                      'part': {'text': json.dumps({
                          'contract_version': 2, 'status': 'complete',
                          'summary': 'read', 'files': [], 'tests': [],
                          'evidence': [], 'unknowns': [], 'blocker': ''})}}))
    print(json.dumps({'type': 'step_finish', 'sessionID': 'ses-fake',
                      'part': {'reason': 'stop'}}))
    sys.exit(0)
if '--help' in args:
    print('--output-schema --output-last-message --model --sandbox --config')
    sys.exit(0)
output = pathlib.Path(args[args.index('--output-last-message') + 1])
kind = output.parent.name.split('-')[0]
report = (plan_report(1) if kind == 'plan' else
          {'contract_version': 2, 'verdict': 'approved', 'reason': 'inspected',
           'inspected': ['app.py'], 'correction': '', 'dismissed_findings': []})
output.write_text(json.dumps(report))
'''


class RoutingObservationTests(unittest.TestCase):
    setUp = baseline.ControlTests.setUp
    tearDown = baseline.ControlTests.tearDown

    def setUp(self):
        baseline.ControlTests.setUp(self)
        self.home = self.root / "routing-home"
        self.home.mkdir()
        self.env_patch = patch.dict(os.environ, {
            "HOME": str(self.home), "OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": "",
            "XDG_CONFIG_HOME": "", "OPENCODE_CONFIG": "",
            "OPENCODE_CONFIG_DIR": "", "OPENCODE_CONFIG_CONTENT": "",
            "ZEN_BASE": "https://first.invalid"})
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        for name in ("OPENCODE_CONFIG", "OPENCODE_CONFIG_DIR",
                     "OPENCODE_CONFIG_CONTENT", "ZEN_BASE"):
            os.environ.pop(name, None)

    def configure(self, version="1.18.35"):
        cfg = orc.read_json(orc.HERE / "config.example.json")
        cfg.setdefault("runtime", {})["opencode_version"] = version
        cfg.setdefault("authorization", {})["sensitive_cli_enabled"] = True
        orc.atomic_json(orc.CONFIG_PATH, cfg)
        self.cfg = orc.config()
        self.state["config_sha256"] = orc.configuration_provenance().get("sha256")
        orc.save(self.rundir, self.state)
        return cfg

    def route(self, billing="api"):
        return {"provider": "opencode", "worker_provider": "opencode-zen",
                "model": "opencode-zen/explorer-model", "effort": "low",
                "billing": billing}

    def write_project_config(self, data, name="opencode.json", comments=False):
        path = self.project / name
        text = json.dumps(data, indent=2)
        if comments:
            text = ("// project routing\n" + text.replace(
                '"provider":', '"provider": // v1 shape\n')
                .replace("}\n}", "},\n}"))
        path.write_text(text)
        return path

    def test_v1_project_endpoint_change_changes_pin_and_blocks_dispatch(self):
        self.configure("1.18.35")
        self.write_project_config({"provider": {"opencode-zen": {
            "options": {"baseURL": "https://first.invalid"},
            "models": {"explorer-model": {}}}}})
        route = self.route()
        first = orc.routing_fingerprint(route, self.cfg, project=self.project)
        route["routing_fingerprint"] = first
        ok = orc.route_preflight("explorer", route, self.cfg, self.project,
                                 self.state, run_dir=self.rundir)
        self.assertFalse(ok["ok"])
        self.assertTrue(any("authorize-route" in reason for reason in ok["reasons"]))
        self.write_project_config({"provider": {"opencode-zen": {
            "options": {"baseURL": "https://changed.invalid"},
            "models": {"explorer-model": {}}}}})
        second = orc.routing_fingerprint(route, self.cfg, project=self.project)
        self.assertNotEqual(first, second)
        blocked = orc.route_preflight("explorer", route, self.cfg, self.project,
                                      self.state, run_dir=self.rundir)
        self.assertFalse(blocked["ok"])
        self.assertIn("routing material changed", " ".join(blocked["reasons"]))

    def test_v2_providers_settings_model_mapping_and_auth_mode_drift(self):
        self.configure("2.2.7")
        data = {"providers": {"opencode-zen": {
            "settings": {"baseURL": "https://first.invalid"},
            "env": ["ZEN_KEY"],
            "models": {"explorer-model": {"modelID": "upstream-a"}}}}}
        self.write_project_config(data, name="opencode.jsonc", comments=True)
        route = self.route()
        first = orc.routing_fingerprint(route, self.cfg, project=self.project)
        data["providers"]["opencode-zen"]["models"]["explorer-model"]["modelID"] = "upstream-b"
        self.write_project_config(data, name="opencode.jsonc", comments=True)
        mapped = orc.routing_fingerprint(route, self.cfg, project=self.project)
        self.assertNotEqual(first, mapped)
        data["providers"]["opencode-zen"]["settings"]["apiKey"] = "{env:ZEN_KEY}"
        data["providers"]["opencode-zen"].pop("env")
        self.write_project_config(data, name="opencode.jsonc", comments=True)
        auth_changed = orc.routing_fingerprint(route, self.cfg, project=self.project)
        self.assertNotEqual(mapped, auth_changed)

    def test_env_expansion_and_config_directory_drift_change_the_pin(self):
        self.configure("1.18.35")
        self.write_project_config({"provider": {"opencode-zen": {
            "options": {"baseURL": "{env:ZEN_BASE}"}, "models": {}}}})
        route = self.route()
        first = orc.routing_fingerprint(route, self.cfg, project=self.project)
        os.environ["ZEN_BASE"] = "https://second.invalid"
        second = orc.routing_fingerprint(route, self.cfg, project=self.project)
        self.assertNotEqual(first, second)
        alt = self.root / "alt-config"
        alt.mkdir()
        orc.atomic_json(alt / "opencode.json", {"provider": {"opencode-zen": {
            "options": {"baseURL": "https://alt.invalid"}, "models": {}}}})
        os.environ["OPENCODE_CONFIG_DIR"] = str(alt)
        third = orc.routing_fingerprint(route, self.cfg, project=self.project)
        self.assertNotEqual(second, third)

    def test_unreadable_effective_config_blocks_even_go(self):
        self.configure("1.18.35")
        (self.project / "opencode.json").write_text("{not json")
        route = {"provider": "opencode", "worker_provider": "opencode-go",
                 "model": "opencode-go/deepseek-v4.1-flash", "effort": "low",
                 "billing": "go"}
        result = orc.route_preflight("explorer", route, self.cfg, self.project,
                                     self.state, run_dir=self.rundir)
        self.assertFalse(result["ok"])
        self.assertIn("unreadable influential OpenCode config",
                      " ".join(result["reasons"]))

    def test_migrated_pin_then_drift_is_refused(self):
        self.configure("1.18.35")
        self.write_project_config({"provider": {"opencode-zen": {
            "options": {"baseURL": "https://first.invalid"}, "models": {}}}})
        legacy = {"provider": "opencode", "model": "opencode-zen/explorer-model",
                  "effort": "low", "billing": "api"}
        self.state.update({
            "schema_version": 2, "config_schema_version": 2,
            "status": "paused", "phase": "plan",
            "model_routes": {"architect": {"provider": "codex",
                                           "model": "gpt-6.1-sol",
                                           "effort": "high",
                                           "billing": "subscription"},
                             "explorer": legacy,
                             "implementer": dict(legacy, model="opencode-go/large",
                                                 billing="go"),
                             "reviewer": dict(legacy, model="opencode-go/large",
                                              billing="go")}})
        orc.save(self.rundir, self.state)
        orc.migrate_run("test-run00", backup_dir=self.root / "backups")
        state = orc.read_json(self.rundir / "state.json")
        pinned = state["model_routes"]["explorer"]["routing_fingerprint"]
        self.assertTrue(pinned)
        self.assertEqual(state["model_routes"]["explorer"]["routing_pin_source"],
                         "migration_observation")
        self.write_project_config({"provider": {"opencode-zen": {
            "options": {"baseURL": "https://changed.invalid"}, "models": {}}}})
        result = orc.route_preflight("explorer", state["model_routes"]["explorer"],
                                     self.cfg, self.project, state,
                                     run_dir=self.rundir)
        self.assertFalse(result["ok"])
        self.assertIn("routing material changed", " ".join(result["reasons"]))

    def test_doctor_and_dispatch_agree_and_refuse_before_spawn(self):
        self.configure("1.18.35")
        malformed = self.project / "opencode.json"
        malformed.write_text("{broken")
        bin_dir = self.root / "routing-bin"
        bin_dir.mkdir()
        script = bin_dir / "fake.py"
        script.write_text(FAKE_CLI)
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        for name in ("opencode", "codex"):
            (bin_dir / name).symlink_to(script)
        with patch.dict(os.environ, {"PATH": str(bin_dir) + ":" + os.environ["PATH"]}):
            checks = orc.doctor(self.project)
            self.assertFalse(checks["billing_preflight"]["explorer"]["ok"])
            history = self.root / "history"
            os.environ["FAKE_HISTORY"] = str(history)
            self.addCleanup(lambda: os.environ.pop("FAKE_HISTORY", None))
            with self.assertRaisesRegex(RuntimeError, "preflight"):
                orc.call_model(self.rundir, self.state, self.cfg, "explorer",
                               "explorer", "prompt", self.project)
        self.assertIsNone(self.state["active_job"])
        self.assertFalse(history.exists())


if __name__ == "__main__":
    unittest.main()
