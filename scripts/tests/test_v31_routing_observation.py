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

FIXTURES = Path(__file__).parent / "fixtures"
V2_VARIANT_FIXTURE = FIXTURES / "opencode-v2.2.7-variant-config.json"

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


CAPTURE_CLI = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
if '--version' in args:
    print(os.environ.get('FAKE_OPENCODE_VERSION', '1.18.35'))
    sys.exit(0)
if pathlib.Path(sys.argv[0]).name != 'opencode':
    sys.exit(4)
if 'models' in args:
    print('local/probe-model')
    sys.exit(0)
if '--help' in args:
    print('--agent --model --format --auto --session --variant --standalone')
    sys.exit(0)
capture = pathlib.Path(os.environ['FAKE_CAPTURE'])
capture.write_text(json.dumps({'argv': args,
                               'config': os.environ.get('OPENCODE_CONFIG_CONTENT')}))
report = {'contract_version': 2, 'status': 'complete', 'summary': 'explored',
          'files': ['app.py'], 'tests': [], 'evidence': ['app.py:1'],
          'unknowns': [], 'blocker': ''}
print(json.dumps({'type': 'text', 'sessionID': 'ses-capture',
                  'part': {'text': json.dumps(report)}}))
print(json.dumps({'type': 'step_finish', 'sessionID': 'ses-capture',
                  'part': {'reason': 'stop'}}))
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


class EffectiveChildRoutingTests(unittest.TestCase):
    """The observed route must equal the configuration the child actually runs."""

    setUp = baseline.ControlTests.setUp
    tearDown = baseline.ControlTests.tearDown

    def setUp(self):
        baseline.ControlTests.setUp(self)
        self.home = self.root / "child-home"
        self.home.mkdir()
        self.bin_dir = self.root / "capture-bin"
        self.bin_dir.mkdir()
        script = self.bin_dir / "capture.py"
        script.write_text(CAPTURE_CLI)
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        (self.bin_dir / "opencode").symlink_to(script)
        self.capture = self.root / "capture.json"
        self.env_patch = patch.dict(os.environ, {
            "PATH": str(self.bin_dir) + ":" + os.environ["PATH"],
            "HOME": str(self.home), "OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": "",
            "XDG_CONFIG_HOME": "", "OPENCODE_CONFIG": "",
            "OPENCODE_CONFIG_DIR": "", "OPENCODE_CONFIG_CONTENT": "",
            "ZEN_BASE": "", "REVIEW_ROUTE_KEY": "",
            "FAKE_CAPTURE": str(self.capture)})
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        for name in ("OPENCODE_CONFIG", "OPENCODE_CONFIG_DIR",
                     "OPENCODE_CONFIG_CONTENT", "ZEN_BASE", "REVIEW_ROUTE_KEY"):
            os.environ.pop(name, None)

    def configure_local(self, dialect):
        cfg = orc.read_json(orc.HERE / "config.example.json")
        cfg["runtime"]["opencode_version"] = "1.18.35" if dialect == "v1" else "2.2.7"
        cfg["workers"]["explorer"] = {
            "provider": "local", "model": "local/probe-model",
            "variant": "low", "billing": "local"}
        orc.atomic_json(orc.CONFIG_PATH, cfg)
        self.cfg = orc.config()
        self.state["config_sha256"] = orc.configuration_provenance().get("sha256")
        os.environ["FAKE_OPENCODE_VERSION"] = cfg["runtime"]["opencode_version"]
        self.addCleanup(lambda: os.environ.pop("FAKE_OPENCODE_VERSION", None))
        return cfg

    def ambient_local(self, dialect, endpoint="http://127.0.0.1:11434/v1"):
        if dialect == "v1":
            return {"provider": {"local": {
                "options": {"baseURL": endpoint},
                "models": {"probe-model": {}}}}}
        return {"providers": {"local": {
            "settings": {"baseURL": endpoint},
            "models": {"probe-model": {}}}}}

    def dispatch_local(self, dialect, ambient):
        self.configure_local(dialect)
        os.environ["OPENCODE_CONFIG_CONTENT"] = json.dumps(ambient)
        self.addCleanup(lambda: os.environ.pop("OPENCODE_CONFIG_CONTENT", None))
        route = orc.model_route(self.cfg, "codex", "explorer", project=self.project)
        self.state["model_routes"] = {"explorer": route}
        self.state["route_authorizations"] = [{
            "id": "grant-local-" + dialect, "role": "explorer",
            "route_sha256": orc.route_authorization_sha(route),
            "max_dispatches": 1, "used": 0,
            "attestation": "reviewed local loopback endpoint",
            "actor": {"user": "tester"}, "at": orc.now()}]
        orc.save(self.rundir, self.state)
        return route

    @staticmethod
    def provider_container(dialect, content):
        return content["provider" if dialect == "v1" else "providers"]["local"]

    def test_fake_child_receives_the_approved_provider_for_both_dialects(self):
        for dialect in ("v1", "v2"):
            with self.subTest(dialect=dialect):
                self.capture.unlink(missing_ok=True)
                ambient = self.ambient_local(dialect)
                route = self.dispatch_local(dialect, ambient)
                pinned = route["routing_fingerprint"]
                report, job = orc.call_model(
                    self.rundir, self.state, self.cfg, "explorer", "explorer",
                    "prompt", self.project)
                self.assertTrue(self.capture.is_file(), report)
                captured = json.loads(self.capture.read_text())
                content = json.loads(captured["config"])
                provider = self.provider_container(dialect, content)
                options_key = "options" if dialect == "v1" else "settings"
                self.assertEqual(provider[options_key]["baseURL"],
                                 "http://127.0.0.1:11434/v1")
                self.assertIn("probe-model", provider["models"])
                container_key = "agent" if dialect == "v1" else "agents"
                self.assertEqual(content[container_key]["abdullah-explorer"],
                                 orc.opencode_profile("explorer", dialect))
                self.assertIn("--model", captured["argv"])
                selector = captured["argv"][captured["argv"].index("--model") + 1]
                self.assertTrue(selector.startswith("local/probe-model"))
                self.assertEqual(dialect == "v2", "--standalone" in captured["argv"])
                self.assertEqual(dialect == "v1", "--variant" in captured["argv"])
                # The pinned preflight identity must be reproducible from what
                # the child actually received, not from a substituted inline env.
                os.environ["OPENCODE_CONFIG_CONTENT"] = captured["config"]
                recomputed = orc.routing_fingerprint(
                    route, self.cfg, project=self.project, role="explorer")
                self.assertEqual(recomputed, pinned)
                self.assertEqual(job["preflight"]["current_routing_fingerprint"], pinned)

    def test_inline_expansion_uses_the_child_environment_and_project_cwd(self):
        self.configure_local("v1")
        route = orc.model_route(self.cfg, "codex", "explorer", project=self.project)
        (self.project / "endpoint.txt").write_text("http://127.0.0.1:9999/v1")
        os.environ["ZEN_BASE"] = "http://127.0.0.1:8888/v1"
        self.addCleanup(lambda: os.environ.pop("ZEN_BASE", None))
        file_ambient = {"provider": {"local": {
            "options": {"baseURL": "{file:endpoint.txt}"},
            "models": {"probe-model": {}}}}}
        os.environ["OPENCODE_CONFIG_CONTENT"] = json.dumps(file_ambient)
        self.addCleanup(lambda: os.environ.pop("OPENCODE_CONFIG_CONTENT", None))
        observed = orc.opencode_provider_observation(
            route, project=self.project, cfg=self.cfg, role="explorer")
        self.assertEqual(observed["endpoint_source"], "provider")
        self.assertEqual(observed["endpoint_sha256"], orc.hashlib.sha256(
            b"http://127.0.0.1:9999/v1").hexdigest())
        env_ambient = {"provider": {"local": {
            "options": {"baseURL": "{env:ZEN_BASE}"},
            "models": {"probe-model": {}}}}}
        os.environ["OPENCODE_CONFIG_CONTENT"] = json.dumps(env_ambient)
        observed = orc.opencode_provider_observation(
            route, project=self.project, cfg=self.cfg, role="explorer")
        self.assertEqual(observed["endpoint_sha256"], orc.hashlib.sha256(
            b"http://127.0.0.1:8888/v1").hexdigest())
        # The wrapper strips credential variables from the child environment; a
        # declared name must not be observed as an authenticated endpoint.
        os.environ["OPENAI_API_KEY"] = "http://should-not-resolve.invalid/v1"
        self.addCleanup(lambda: os.environ.pop("OPENAI_API_KEY", None))
        stripped = {"provider": {"local": {
            "options": {"baseURL": "{env:OPENAI_API_KEY}"},
            "models": {"probe-model": {}}}}}
        os.environ["OPENCODE_CONFIG_CONTENT"] = json.dumps(stripped)
        observed = orc.opencode_provider_observation(
            route, project=self.project, cfg=self.cfg, role="explorer")
        self.assertIsNone(observed["endpoint_sha256"])

    def test_ambient_inline_controls_cannot_weaken_generated_profile(self):
        self.configure_local("v1")
        ambient = self.ambient_local("v1")
        ambient.update({
            "agent": {"abdullah-explorer": {"permission": {"*": "allow"}}},
            "permission": {"bash": "allow"},
            "subagent_depth": 3})
        os.environ["OPENCODE_CONFIG_CONTENT"] = json.dumps(ambient)
        self.addCleanup(lambda: os.environ.pop("OPENCODE_CONFIG_CONTENT", None))
        route = orc.model_route(self.cfg, "codex", "explorer", project=self.project)
        self.state["route_authorizations"] = [{
            "id": "grant-local", "role": "explorer",
            "route_sha256": orc.route_authorization_sha(route),
            "max_dispatches": 1, "used": 0,
            "attestation": "reviewed local loopback endpoint"}]
        result = orc.route_preflight("explorer", route, self.cfg, self.project,
                                     self.state, run_dir=self.rundir)
        self.assertTrue(result["ok"], result["reasons"])
        warnings = " ".join(result["warnings"])
        for control in ("agent", "permission", "subagent_depth"):
            self.assertIn(control, warnings)
        content = json.loads(
            orc.opencode_env("explorer", "v1")["OPENCODE_CONFIG_CONTENT"])
        self.assertEqual(content["agent"]["abdullah-explorer"],
                         orc.opencode_profile("explorer", "v1"))
        self.assertNotIn("permission", content)
        self.assertEqual(content["subagent_depth"], 0)
        self.assertIn("local", content["provider"])

    def test_file_defined_worker_agent_conflict_fails_closed_before_spawn(self):
        self.configure_local("v1")
        (self.project / "opencode.json").write_text(json.dumps({
            "provider": {"local": {"options": {
                "baseURL": "http://127.0.0.1:11434/v1"},
                "models": {"probe-model": {}}}},
            "agent": {"abdullah-explorer": {"permission": {"*": "allow"},
                                            "tools": {"write": True}}}}))
        route = orc.model_route(self.cfg, "codex", "explorer", project=self.project)
        self.state["model_routes"] = {"explorer": route}
        self.state["route_authorizations"] = [{
            "id": "grant-local", "role": "explorer",
            "route_sha256": orc.route_authorization_sha(route),
            "max_dispatches": 1, "used": 0,
            "attestation": "reviewed local loopback endpoint"}]
        orc.save(self.rundir, self.state)
        result = orc.route_preflight("explorer", route, self.cfg, self.project,
                                     self.state, run_dir=self.rundir)
        self.assertFalse(result["ok"])
        self.assertIn("abdullah-explorer", " ".join(result["reasons"]))
        with self.assertRaisesRegex(RuntimeError, "preflight"):
            orc.call_model(self.rundir, self.state, self.cfg, "explorer",
                           "explorer", "prompt", self.project)
        self.assertIsNone(self.state["active_job"])
        self.assertFalse(self.capture.exists())

    def test_authorized_custom_v2_variant_dispatches_without_go_bypass(self):
        cfg = orc.read_json(orc.HERE / "config.example.json")
        cfg["runtime"]["opencode_version"] = "2.2.7"
        cfg["workers"]["explorer"] = {
            "provider": "local", "model": "local/probe-model",
            "variant": "low", "billing": "api"}
        orc.atomic_json(orc.CONFIG_PATH, cfg)
        self.cfg = orc.config()
        self.state["config_sha256"] = orc.configuration_provenance().get("sha256")
        os.environ["FAKE_OPENCODE_VERSION"] = "2.2.7"
        self.addCleanup(lambda: os.environ.pop("FAKE_OPENCODE_VERSION", None))
        data = {"providers": {"local": {
            "settings": {"baseURL": "http://127.0.0.1:11434/v1"},
            "models": {"probe-model": {"variants": [
                {"id": "low", "settings": {
                    "baseURL": "http://127.0.0.1:9999/v1"}},
                {"id": "high", "settings": {
                    "baseURL": "http://127.0.0.1:9998/v1"}},
            ]}}}}}
        (self.project / "opencode.json").write_text(json.dumps(data))
        route = orc.model_route(self.cfg, "codex", "explorer",
                                project=self.project)
        self.assertEqual(route["billing"], "api")
        self.state["model_routes"] = {"explorer": route}
        self.state["route_authorizations"] = [{
            "id": "grant-custom-variant", "role": "explorer",
            "route_sha256": orc.route_authorization_sha(route),
            "max_dispatches": 1, "used": 0,
            "attestation": "reviewed custom variant endpoint",
            "actor": {"user": "tester"}, "at": orc.now()}]
        orc.save(self.rundir, self.state)
        preflight = orc.route_preflight(
            "explorer", route, self.cfg, self.project, self.state,
            run_dir=self.rundir)
        self.assertTrue(preflight["ok"], preflight["reasons"])
        self.assertEqual(preflight["classification"], "api")
        self.assertEqual(preflight["observed"]["endpoint_source"], "variant")
        report, job = orc.call_model(
            self.rundir, self.state, self.cfg, "explorer", "explorer",
            "prompt", self.project)
        self.assertTrue(self.capture.is_file(), report)
        captured = json.loads(self.capture.read_text())
        content = json.loads(captured["config"])
        self.assertEqual(content["agents"]["abdullah-explorer"],
                         orc.opencode_profile("explorer", "v2"))
        selector = captured["argv"][captured["argv"].index("--model") + 1]
        self.assertEqual(selector, "local/probe-model#low")
        self.assertIn("--standalone", captured["argv"])
        self.assertNotIn("--variant", captured["argv"])
        self.assertEqual(job["preflight"]["classification"], "api")

    def test_auth_environment_availability_is_part_of_the_pin_for_both_dialects(self):
        for dialect in ("v1", "v2"):
            with self.subTest(dialect=dialect):
                self.configure_local(dialect)
                options_key = "options" if dialect == "v1" else "settings"
                container = "provider" if dialect == "v1" else "providers"
                data = {container: {"local": {
                    options_key: {"baseURL": "http://127.0.0.1:11434/v1"},
                    "env": ["REVIEW_ROUTE_KEY"],
                    "models": {"probe-model": {}}}}}
                path = self.project / "opencode.json"
                path.write_text(json.dumps(data))
                route = orc.model_route(self.cfg, "codex", "explorer",
                                        project=self.project)
                absent_pin = route["routing_fingerprint"]
                os.environ["REVIEW_ROUTE_KEY"] = "dummy-not-a-real-key"
                self.addCleanup(lambda: os.environ.pop("REVIEW_ROUTE_KEY", None))
                present_pin = orc.routing_fingerprint(
                    route, self.cfg, project=self.project)
                self.assertNotEqual(absent_pin, present_pin)
                blocked = orc.route_preflight(
                    "explorer", route, self.cfg, self.project, self.state,
                    run_dir=self.rundir)
                self.assertFalse(blocked["ok"])
                self.assertIn("routing material changed", " ".join(blocked["reasons"]))
                self.assertNotIn("dummy-not-a-real-key", json.dumps(blocked))
                del os.environ["REVIEW_ROUTE_KEY"]
                self.assertEqual(
                    orc.routing_fingerprint(route, self.cfg,
                                            project=self.project),
                    absent_pin)

    def test_go_route_model_and_variant_endpoint_overrides_are_not_subscription(self):
        for dialect in ("v1", "v2"):
            options_key = "options" if dialect == "v1" else "settings"
            container = "provider" if dialect == "v1" else "providers"
            for layer in ("model", "variant", "remap"):
                with self.subTest(dialect=dialect, layer=layer):
                    self.configure_local(dialect)
                    model = {"modelID": "go-model"}
                    if layer == "model":
                        model[options_key] = {
                            "baseURL": "https://proxy.invalid/v1"}
                    elif layer == "variant":
                        if dialect == "v1":
                            model["variants"] = {"low": {options_key: {
                                "baseURL": "https://variant.invalid/v1"}}}
                        else:
                            # Supported V2 variants are an array keyed by id.
                            model["variants"] = [{
                                "id": "low",
                                options_key: {
                                    "baseURL": "https://variant.invalid/v1"}}]
                    else:
                        model["modelID"] = "remapped-upstream"
                    data = {container: {"opencode-go": {
                        options_key: {}, "models": {"go-model": model}}}}
                    (self.project / "opencode.json").write_text(json.dumps(data))
                    route = {"provider": "opencode",
                             "worker_provider": "opencode-go",
                             "model": "opencode-go/go-model", "effort": "low",
                             "billing": "go"}
                    result = orc.route_preflight("explorer", route, self.cfg,
                                                 self.project, self.state,
                                                 run_dir=self.rundir)
                    self.assertFalse(result["ok"])
                    self.assertNotEqual(result["classification"], "go_subscription")
                    self.assertRegex(" ".join(result["reasons"]),
                                     "model|variant|remap|endpoint|package|canonical")
                    # An accurately classified explicit grant may still dispatch.
                    grant_route = dict(route, billing="api")
                    self.state["route_authorizations"] = [{
                        "id": "grant-go-override", "role": "explorer",
                        "route_sha256": orc.route_authorization_sha(grant_route),
                        "max_dispatches": 1, "used": 0,
                        "attestation": "reviewed custom proxy endpoint"}]
                    authorized = orc.route_preflight(
                        "explorer", grant_route, self.cfg, self.project,
                        self.state, run_dir=self.rundir)
                    self.assertTrue(authorized["ok"], authorized["reasons"])
                    self.assertEqual(authorized["classification"], "api")

    def test_captured_v2_variant_fixture_resolves_the_selected_endpoint(self):
        fixture = json.loads(V2_VARIANT_FIXTURE.read_text())
        self.assertEqual(fixture["provenance"]["opencode_version"],
                         "v2.2.7")
        self.configure_local("v2")
        (self.project / "opencode.json").write_text(
            json.dumps(fixture["normalized_document"]))
        for effort, endpoint in (
                ("low", "https://variant-low.invalid/v1"),
                ("high", "https://variant-high.invalid/v1")):
            with self.subTest(effort=effort):
                route = {"provider": "opencode", "worker_provider": "opencode-go",
                         "model": "opencode-go/go-model", "effort": effort,
                         "billing": "go"}
                observed = orc.opencode_provider_observation(
                    route, project=self.project, cfg=self.cfg)
                self.assertIsNone(observed["error"])
                self.assertEqual(observed["endpoint_source"], "variant")
                self.assertEqual(
                    observed["endpoint_sha256"],
                    orc.hashlib.sha256(endpoint.encode()).hexdigest())
                self.assertFalse(observed["go_route"]["qualified"])
                result = orc.route_preflight(
                    "explorer", route, self.cfg, self.project, self.state,
                    run_dir=self.rundir)
                self.assertFalse(result["ok"])
                self.assertEqual(result["classification"],
                                 "unqualified_go_route")
                self.assertIn("variant", " ".join(result["reasons"]))
        selected = {"provider": "opencode", "worker_provider": "opencode-go",
                    "model": "opencode-go/go-model", "effort": "low",
                    "billing": "go"}
        self.state["model_routes"] = {"explorer": selected}
        orc.save(self.rundir, self.state)
        with self.assertRaisesRegex(RuntimeError, "preflight"):
            orc.call_model(self.rundir, self.state, self.cfg, "explorer",
                           "explorer", "prompt", self.project)
        self.assertIsNone(self.state["active_job"])
        self.assertFalse(self.capture.exists())

    def test_v2_variant_selection_is_by_id_not_position(self):
        self.configure_local("v2")
        data = {"providers": {"opencode-go": {
            "settings": {"baseURL": "https://provider.invalid/v1"},
            "models": {"go-model": {
                "settings": {"baseURL": "https://model.invalid/v1"},
                "variants": [
                    {"id": "high", "settings": {
                        "baseURL": "https://variant-high.invalid/v1"}},
                    {"id": "low", "settings": {
                        "baseURL": "https://variant-low.invalid/v1"}},
                ]}}}}}
        (self.project / "opencode.json").write_text(json.dumps(data))
        route = {"provider": "opencode", "worker_provider": "opencode-go",
                 "model": "opencode-go/go-model", "effort": "low",
                 "billing": "go"}
        observed = orc.opencode_provider_observation(
            route, project=self.project, cfg=self.cfg)
        self.assertEqual(observed["endpoint_source"], "variant")
        self.assertEqual(
            observed["endpoint_sha256"],
            orc.hashlib.sha256(
                b"https://variant-low.invalid/v1").hexdigest())
        # The unselected variant must not supply the selected endpoint.
        self.assertNotEqual(
            observed["endpoint_sha256"],
            orc.hashlib.sha256(
                b"https://variant-high.invalid/v1").hexdigest())

    def test_selected_v2_variant_auth_and_remap_are_observed(self):
        self.configure_local("v2")
        data = {"providers": {"opencode-go": {
            "settings": {},
            "models": {"go-model": {"variants": [
                {"id": "low", "settings": {
                    "apiKey": "{env:REVIEW_ROUTE_KEY}"}},
                {"id": "high", "settings": {"reasoningEffort": "high"}},
            ]}}}}}
        path = self.project / "opencode.json"
        path.write_text(json.dumps(data))
        route = {"provider": "opencode", "worker_provider": "opencode-go",
                 "model": "opencode-go/go-model", "effort": "low",
                 "billing": "go"}
        absent = orc.routing_fingerprint(route, self.cfg, project=self.project)
        os.environ["REVIEW_ROUTE_KEY"] = "dummy-not-a-real-key"
        self.addCleanup(lambda: os.environ.pop("REVIEW_ROUTE_KEY", None))
        present = orc.routing_fingerprint(route, self.cfg, project=self.project)
        self.assertNotEqual(absent, present)
        observed = orc.opencode_provider_observation(
            route, project=self.project, cfg=self.cfg)
        self.assertNotIn("dummy-not-a-real-key", json.dumps(observed))
        self.assertTrue(observed["auth_mode_sha256"])
        # A remap on the selected variant must not inherit Go consent.
        data["providers"]["opencode-go"]["models"]["go-model"]["variants"][0][
            "modelID"] = "remapped-variant-upstream"
        path.write_text(json.dumps(data))
        observed = orc.opencode_provider_observation(
            route, project=self.project, cfg=self.cfg)
        self.assertFalse(observed["go_route"]["qualified"])
        self.assertTrue(any("variant" in reason
                            for reason in observed["go_route"]["reasons"]))
        result = orc.route_preflight(
            "explorer", route, self.cfg, self.project, self.state,
            run_dir=self.rundir)
        self.assertFalse(result["ok"])
        self.assertEqual(result["classification"], "unqualified_go_route")

    def test_invalid_v2_variant_shapes_fail_closed_before_spawn(self):
        self.configure_local("v2")
        shapes = {
            "dict": {"low": {"settings": {
                "baseURL": "https://variant.invalid/v1"}}},
            "null": None,
            "scalar": "low",
            "non_object_entry": ["low"],
            "missing_id": [{"settings": {
                "baseURL": "https://variant.invalid/v1"}}],
            "blank_id": [{"id": " ", "settings": {}}],
            "duplicate_id": [
                {"id": "low", "settings": {
                    "baseURL": "https://variant-a.invalid/v1"}},
                {"id": "low", "settings": {
                    "baseURL": "https://variant-b.invalid/v1"}}],
        }
        for name, variants in shapes.items():
            with self.subTest(shape=name):
                data = {"providers": {"opencode-go": {
                    "settings": {}, "models": {"go-model": {
                        "variants": variants}}}}}
                (self.project / "opencode.json").write_text(json.dumps(data))
                route = {"provider": "opencode",
                         "worker_provider": "opencode-go",
                         "model": "opencode-go/go-model", "effort": "low",
                         "billing": "go"}
                result = orc.route_preflight(
                    "explorer", route, self.cfg, self.project, self.state,
                    run_dir=self.rundir)
                self.assertFalse(result["ok"])
                self.assertEqual(result["classification"],
                                 "unprovable_routing")
                self.assertIn("variant", " ".join(result["reasons"]))
                self.assertNotEqual(result["classification"],
                                    "go_subscription")
        # An explicit API grant cannot turn an uninspectable variant shape into
        # an approved route.
        api_route = dict(route, billing="api")
        self.state["route_authorizations"] = [{
            "id": "grant-invalid-shape", "role": "explorer",
            "route_sha256": orc.route_authorization_sha(api_route),
            "max_dispatches": 1, "used": 0,
            "attestation": "reviewed custom endpoint"}]
        granted = orc.route_preflight(
            "explorer", api_route, self.cfg, self.project, self.state,
            run_dir=self.rundir)
        self.assertFalse(granted["ok"])
        self.assertEqual(granted["classification"], "unprovable_routing")
        self.state["model_routes"] = {"explorer": api_route}
        orc.save(self.rundir, self.state)
        with self.assertRaisesRegex(RuntimeError, "preflight"):
            orc.call_model(self.rundir, self.state, self.cfg, "explorer",
                           "explorer", "prompt", self.project)
        self.assertIsNone(self.state["active_job"])

    def test_benign_v2_variant_settings_keep_default_go_subscription(self):
        self.configure_local("v2")
        data = {"providers": {"opencode-go": {
            "settings": {}, "models": {"go-model": {"variants": [
                {"id": "low", "settings": {"reasoningEffort": "low"}},
                {"id": "high", "settings": {"reasoningEffort": "high"}},
            ]}}}}}
        (self.project / "opencode.json").write_text(json.dumps(data))
        route = {"provider": "opencode", "worker_provider": "opencode-go",
                 "model": "opencode-go/go-model", "effort": "low",
                 "billing": "go"}
        result = orc.route_preflight(
            "explorer", route, self.cfg, self.project, self.state,
            run_dir=self.rundir)
        self.assertTrue(result["ok"], result["reasons"])
        self.assertEqual(result["classification"], "go_subscription")
        self.assertIsNone(result["observed"]["endpoint_source"])
        self.assertTrue(result["observed"]["go_route"]["qualified"])

    def test_unchanged_go_route_remains_a_subscription_without_a_grant(self):
        for dialect in ("v1", "v2"):
            with self.subTest(dialect=dialect):
                self.configure_local(dialect)
                options_key = "options" if dialect == "v1" else "settings"
                container = "provider" if dialect == "v1" else "providers"
                data = {
                    container: {
                        "opencode-go": {
                            options_key: {},
                            "models": {"go-model": {}},
                        }
                    }
                }
                (self.project / "opencode.json").write_text(json.dumps(data))
                route = {"provider": "opencode",
                         "worker_provider": "opencode-go",
                         "model": "opencode-go/go-model", "effort": "low",
                         "billing": "go"}
                result = orc.route_preflight("explorer", route, self.cfg,
                                             self.project, self.state,
                                             run_dir=self.rundir)
                self.assertTrue(result["ok"], result["reasons"])
                self.assertEqual(result["classification"], "go_subscription")


if __name__ == "__main__":
    unittest.main()
