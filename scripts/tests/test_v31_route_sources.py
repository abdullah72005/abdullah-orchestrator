"""AOR31-01: version-aware OpenCode routing sources and grant identity."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys
import time
import unittest
from unittest.mock import patch

import test_orchestrator as baseline
orc = baseline.orc


FAKE_OPENCODE = r'''#!/usr/bin/env python3
import json, os, pathlib, signal, sys, time
args = sys.argv[1:]
version = os.environ.get('FAKE_OC_VERSION', '2.2.7')
mode = os.environ.get('FAKE_OC_MODE', 'normal')
if '--version' in args:
    print(version)
    sys.exit(0)
name = pathlib.Path(sys.argv[0]).name
if name != 'opencode':
    sys.exit(3)
if 'debug' in args and 'config' in args:
    if mode == 'fail':
        sys.exit(2)
    if mode == 'sleep':
        pathlib.Path(os.environ['FAKE_OC_PID']).write_text(str(os.getpid()))
        time.sleep(30)
        sys.exit(0)
    if 'FAKE_OC_ENTRIES' in os.environ:
        print(os.environ['FAKE_OC_ENTRIES'])
        sys.exit(0)
    documents = []
    custom = os.environ.get('OPENCODE_CONFIG_DIR')
    home = pathlib.Path(os.environ.get('HOME', ''))
    global_dir = pathlib.Path(custom) if custom else home / '.config' / 'opencode'
    for name in ('opencode.json', 'opencode.jsonc'):
        path = global_dir / name
        if path.is_file():
            documents.append({'type': 'document', 'path': str(path),
                              'info': json.loads(path.read_text())})
    explicit = os.environ.get('OPENCODE_CONFIG')
    if explicit and pathlib.Path(explicit).is_file():
        documents.append({'type': 'document', 'path': explicit,
                          'info': json.loads(pathlib.Path(explicit).read_text())})
    cwd = pathlib.Path.cwd()
    chain = [cwd]
    while chain[-1] != chain[-1].parent:
        if (chain[-1] / '.git').exists():
            break
        chain.append(chain[-1].parent)
    disabled = (os.environ.get('OPENCODE_DISABLE_PROJECT_CONFIG', '') or
                os.environ.get('OPENCODE_CONFIG_PROJECT_DISABLE', '')).lower() in ('1', 'true')
    if not disabled:
        for directory in reversed(chain):
            path = directory / 'opencode.json'
            if path.is_file():
                documents.append({'type': 'document', 'path': str(path),
                                  'info': json.loads(path.read_text())})
        for directory in reversed(chain):
            path = directory / '.opencode' / 'opencode.json'
            if path.is_file():
                documents.append({'type': 'document', 'path': str(path),
                                  'info': json.loads(path.read_text())})
    documents.append({'type': 'document',
                      'info': json.loads(os.environ.get('OPENCODE_CONFIG_CONTENT') or '{}')})
    print(json.dumps(documents))
    sys.exit(0)
if 'models' in args:
    print('opencode-go/model')
    sys.exit(0)
if '--help' in args:
    print('--agent --model --format --auto --session --variant --standalone')
    sys.exit(0)
history = pathlib.Path(os.environ.get('FAKE_OC_HISTORY', '/dev/null'))
if os.environ.get('FAKE_OC_HISTORY'):
    with history.open('a') as stream:
        stream.write('run\n')
role = args[args.index('--agent') + 1].replace('abdullah-', '')
report = {'contract_version': 2, 'status': 'complete', 'summary': role,
          'files': [], 'tests': [], 'evidence': [], 'unknowns': [],
          'blocker': ''}
if role in {'architect'}:
    report = {'contract_version': 2, 'status': 'complete', 'summary': 'plan',
              'invariants': ['Keep behavior'], 'blocker': '',
              'batches': [{'title': 'b', 'goal': 'g', 'acceptance': ['a'],
                           'checks': [[sys.executable, '-c', 'pass']],
                           'risk': 'ordinary'}]}
if role == 'reviewer':
    report = {'contract_version': 2, 'status': 'complete', 'summary': 'reviewed',
              'findings': [], 'files': [], 'tests': [], 'evidence': [],
              'unknowns': [], 'blocker': ''}
print(json.dumps({'type': 'text', 'sessionID': 'ses-source',
                  'part': {'text': json.dumps(report)}}))
print(json.dumps({'type': 'step_finish', 'sessionID': 'ses-source',
                  'part': {'reason': 'stop'}}))
'''


class RouteSourceTests(unittest.TestCase):
    setUp = baseline.ControlTests.setUp
    tearDown = baseline.ControlTests.tearDown

    def setUp(self):
        baseline.ControlTests.setUp(self)
        self.bin_dir = self.root / "source-bin"
        self.bin_dir.mkdir()
        script = self.bin_dir / "fake.py"
        script.write_text(FAKE_OPENCODE)
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        (self.bin_dir / "opencode").symlink_to(script)
        (self.bin_dir / "codex").symlink_to(script)
        self.home = self.root / "source-home"
        self.home.mkdir()
        self.history = self.root / "history"
        env = {"PATH": str(self.bin_dir) + ":" + os.environ["PATH"],
               "HOME": str(self.home), "XDG_CONFIG_HOME": "",
               "OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": "",
               "FAKE_OC_HISTORY": str(self.history),
               "FAKE_OC_VERSION": "2.2.7"}
        self.env_patch = patch.dict(os.environ, env)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        for name in ("OPENCODE_CONFIG", "OPENCODE_CONFIG_DIR",
                     "OPENCODE_CONFIG_CONTENT", "FAKE_OC_MODE",
                     "FAKE_OC_ENTRIES", "FAKE_OC_PID"):
            os.environ.pop(name, None)
            self.addCleanup(lambda name=name: os.environ.pop(name, None))

    def configure(self, version="2.2.7", billing="go"):
        cfg = orc.read_json(orc.HERE / "config.example.json")
        cfg.setdefault("runtime", {})["opencode_version"] = version
        cfg.setdefault("authorization", {})["sensitive_cli_enabled"] = True
        orc.atomic_json(orc.CONFIG_PATH, cfg)
        self.cfg = orc.config()
        self.state["config_sha256"] = orc.configuration_provenance().get("sha256")
        os.environ["FAKE_OC_VERSION"] = version
        orc.save(self.rundir, self.state)
        return cfg

    def route(self, billing="go", model="opencode-go/deepseek-v4.1-flash"):
        return {"provider": "opencode", "worker_provider": model.split("/", 1)[0],
                "model": model, "effort": "low", "billing": billing}

    def write_json(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))

    def provider(self, endpoint=None, legacy=False, models=None, extra=None):
        entry = {"models": models if models is not None else {}}
        if endpoint is not None:
            entry["options" if legacy else "settings"] = {"baseURL": endpoint}
        if extra:
            entry.update(extra)
        return {"$schema": "https://opencode.ai/config.json",
                "provider" if legacy else "providers": {"opencode-go": entry}}

    def test_v2_custom_global_root_replaces_ordinary_global_and_explicit_follows(self):
        self.configure("2.2.7")
        ordinary = self.home / ".config/opencode/opencode.json"
        custom = self.root / "custom/opencode.json"
        explicit = self.root / "explicit.json"
        self.write_json(ordinary, self.provider("https://ordinary.invalid/v1"))
        self.write_json(custom, {"providers": {"opencode-go": {
            "settings": {"baseURL": None}, "models": {}}}})
        self.write_json(explicit, self.provider("https://explicit.invalid/v1"))
        os.environ.update({"OPENCODE_CONFIG_DIR": str(custom.parent),
                           "OPENCODE_CONFIG": str(explicit)})
        observed = orc.opencode_provider_observation(
            self.route(), project=self.project, cfg=self.cfg, role="explorer")
        self.assertTrue(observed["available"])
        self.assertNotIn(str(ordinary), observed["effective_files"])
        self.assertIn(str(custom), observed["effective_files"])
        self.assertIn(str(explicit), observed["effective_files"])
        self.assertEqual(
            observed["endpoint_sha256"],
            orc.hashlib.sha256(b"https://explicit.invalid/v1").hexdigest())
        first = orc.routing_fingerprint(self.route(), self.cfg,
                                        project=self.project, role="explorer")
        self.write_json(explicit, self.provider("https://changed.invalid/v1"))
        second = orc.routing_fingerprint(self.route(), self.cfg,
                                         project=self.project, role="explorer")
        self.assertNotEqual(first, second)

    def test_v1_custom_config_directory_is_additional_late_source(self):
        self.configure("1.18.35")
        ordinary = self.home / ".config/opencode/opencode.json"
        custom = self.root / "v1-custom/opencode.json"
        self.write_json(ordinary, self.provider("https://ordinary.invalid/v1",
                                                legacy=True))
        self.write_json(custom, self.provider("https://custom.invalid/v1",
                                              legacy=True))
        os.environ["OPENCODE_CONFIG_DIR"] = str(custom.parent)
        observed = orc.opencode_provider_observation(
            self.route(), project=self.project, cfg=self.cfg, role="explorer")
        self.assertIn(str(ordinary), observed["effective_files"])
        self.assertIn(str(custom), observed["effective_files"])
        self.assertEqual(
            observed["endpoint_sha256"],
            orc.hashlib.sha256(b"https://custom.invalid/v1").hexdigest())

    def test_managed_settings_supersede_inline_and_project(self):
        self.configure("1.18.35")
        managed = self.root / "managed/opencode.json"
        self.write_json(managed, self.provider("https://managed.invalid/v1",
                                              legacy=True))
        self.write_json(self.project / "opencode.json",
                        self.provider("https://project.invalid/v1", legacy=True))
        os.environ["OPENCODE_CONFIG_CONTENT"] = json.dumps(
            self.provider("https://inline.invalid/v1", legacy=True))
        with patch.object(orc, "OPENCODE_MANAGED_CONFIG_FILES", (managed,)):
            observed = orc.opencode_provider_observation(
                self.route(), project=self.project, cfg=self.cfg,
                role="explorer")
        self.assertEqual(
            observed["endpoint_sha256"],
            orc.hashlib.sha256(b"https://managed.invalid/v1").hexdigest())

    def test_legacy_and_native_provider_coexistence_matches_the_normalizer(self):
        self.configure("2.2.7")
        document = self.provider("https://legacy.invalid/v1", legacy=True)
        document["providers"] = {"opencode-go": {
            "settings": {"baseURL": "https://native.invalid/v1"},
            "models": {"go-model": {}}}}
        document["provider"]["opencode-go"]["models"] = {"legacy-only": {}}
        self.write_json(self.project / "opencode.json", document)
        route = {"provider": "opencode", "worker_provider": "opencode-go",
                 "model": "opencode-go/go-model", "effort": "low",
                 "billing": "go"}
        observed = orc.opencode_provider_observation(
            route, project=self.project, cfg=self.cfg, role="explorer")
        self.assertEqual(observed["providers"], ["opencode-go"])
        self.assertEqual(
            observed["endpoint_sha256"],
            orc.hashlib.sha256(b"https://native.invalid/v1").hexdigest())
        self.assertEqual(observed["model_count"], 1)

    def test_masked_endpoint_is_unprovable_not_a_default_route(self):
        self.configure("2.2.7")
        os.environ["FAKE_OC_ENTRIES"] = json.dumps([{
            "type": "document",
            "info": {"providers": {"opencode-go": {
                "settings": {"baseURL": "***"}, "models": {}}}}}])
        result = orc.route_preflight("explorer", self.route(), self.cfg,
                                     self.project, self.state,
                                     run_dir=self.rundir)
        self.assertFalse(result["ok"])
        self.assertEqual(result["classification"], "unprovable_routing")
        self.assertIn("masked", " ".join(result["reasons"]))

    def test_missing_or_failed_inspector_uses_the_bounded_source_adapter(self):
        self.configure("2.2.7")
        self.write_json(self.project / "opencode.json",
                        self.provider("https://source.invalid/v1"))
        os.environ["FAKE_OC_MODE"] = "fail"
        observed = orc.opencode_provider_observation(
            self.route(), project=self.project, cfg=self.cfg, role="explorer")
        self.assertIsNone(observed["error"])
        self.assertEqual(observed["inspection"], "source_adapter")
        self.assertEqual(observed["inspection_reason"], "inspector_exit_2")
        self.assertEqual(
            observed["endpoint_sha256"],
            orc.hashlib.sha256(b"https://source.invalid/v1").hexdigest())

    def test_inspector_is_bounded_and_fully_cleaned_up(self):
        self.configure("2.2.7")
        self.write_json(self.project / "opencode.json",
                        self.provider("https://source.invalid/v1"))
        os.environ["FAKE_OC_MODE"] = "sleep"
        pid_file = self.root / "inspector.pid"
        os.environ["FAKE_OC_PID"] = str(pid_file)
        with patch.object(orc, "OPENCODE_INSPECTION_TIMEOUT", 0.3):
            started = time.monotonic()
            observed = orc.opencode_provider_observation(
                self.route(), project=self.project, cfg=self.cfg,
                role="explorer")
            elapsed = time.monotonic() - started
        self.assertLess(elapsed, 5.0)
        self.assertEqual(observed["inspection"], "source_adapter")
        self.assertIn("inspector_failed", observed["inspection_reason"])
        pid = int(pid_file.read_text())
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and orc.process_stat(pid):
            time.sleep(0.05)
        self.assertIsNone(orc.process_stat(pid))

    def test_route_material_drift_after_preflight_spawns_no_child(self):
        self.configure("1.18.35")
        self.write_json(self.project / "opencode.json",
                        self.provider("https://first.invalid/v1", legacy=True))
        route = self.route(billing="api")
        self.state["model_routes"] = {"explorer": route}
        self.state["route_authorizations"] = [{
            "id": "grant-drift", "role": "explorer",
            "route_sha256": orc.route_authorization_sha(route),
            "max_dispatches": 1, "used": 0,
            "attestation": "reviewed endpoint"}]
        orc.save(self.rundir, self.state)
        first = orc.opencode_provider_observation(
            route, project=self.project, cfg=self.cfg, role="explorer")
        second = dict(first, routing_material_sha256="different-material")
        with patch.object(orc, "opencode_provider_observation",
                          side_effect=[first, second]):
            with self.assertRaisesRegex(RuntimeError, "preflight"):
                orc.call_model(self.rundir, self.state, self.cfg, "explorer",
                               "explorer", "prompt", self.project)
        self.assertIsNone(self.state["active_job"])
        self.assertFalse(self.history.exists())
        ledger = orc.load_grant_ledger(self.rundir)
        self.assertEqual(orc._grant_usage(ledger["grants"]["grant-drift"]), 0)

    def test_rejected_route_has_no_phantom_job_or_grant_consumption(self):
        self.configure("1.18.35")
        self.write_json(self.project / "opencode.json",
                        self.provider("https://custom.invalid/v1", legacy=True))
        route = self.route(billing="api")
        self.state["model_routes"] = {"explorer": route}
        orc.save(self.rundir, self.state)
        with self.assertRaisesRegex(RuntimeError, "preflight"):
            orc.call_model(self.rundir, self.state, self.cfg, "explorer",
                           "explorer", "prompt", self.project)
        state = orc.read_json(self.rundir / "state.json")
        self.assertIsNone(state["active_job"])
        self.assertFalse(self.history.exists())
        self.assertFalse(state.get("completed_jobs"))
        self.assertFalse((state.get("usage") or {}).get("strong_calls"))
        self.assertFalse((state.get("usage") or {}).get("cheap_calls"))
        ledger = orc.load_grant_ledger(self.rundir)
        self.assertEqual(ledger["grants"], {})

    def test_grant_identity_binds_material_not_only_the_label(self):
        route = self.route()
        label_only = dict(route)
        bound = dict(route, routing_fingerprint="material-a")
        rebound = dict(route, routing_fingerprint="material-b")
        self.assertNotEqual(orc.route_authorization_sha(label_only),
                            orc.route_authorization_sha(bound))
        self.assertNotEqual(orc.route_authorization_sha(bound),
                            orc.route_authorization_sha(rebound))

    def test_project_disable_flag_excludes_project_sources(self):
        self.configure("2.2.7")
        self.write_json(self.project / "opencode.json",
                        self.provider("https://project.invalid/v1"))
        os.environ["OPENCODE_DISABLE_PROJECT_CONFIG"] = "1"
        self.addCleanup(lambda: os.environ.pop("OPENCODE_DISABLE_PROJECT_CONFIG", None))
        observed = orc.opencode_provider_observation(
            self.route(), project=self.project, cfg=self.cfg, role="explorer")
        self.assertNotIn(str(self.project / "opencode.json"),
                         observed["effective_files"])
        self.assertIsNone(observed.get("endpoint_sha256"))

    def test_project_directory_supplements_direct_project_config(self):
        self.configure("1.18.35")
        self.write_json(self.project / "opencode.json",
                        self.provider("https://root.invalid/v1", legacy=True))
        self.write_json(self.project / ".opencode" / "opencode.json",
                        self.provider("https://supplement.invalid/v1",
                                      legacy=True))
        observed = orc.opencode_provider_observation(
            self.route(), project=self.project, cfg=self.cfg, role="explorer")
        self.assertEqual(
            observed["endpoint_sha256"],
            orc.hashlib.sha256(b"https://supplement.invalid/v1").hexdigest())

    def test_expansion_file_dependency_is_part_of_the_pin(self):
        self.configure("1.18.35")
        (self.project / "endpoint.txt").write_text("https://file-a.invalid/v1")
        self.write_json(self.project / "opencode.json",
                        self.provider("{file:endpoint.txt}", legacy=True))
        first = orc.routing_fingerprint(self.route(), self.cfg,
                                        project=self.project, role="explorer")
        (self.project / "endpoint.txt").write_text("https://file-b.invalid/v1")
        second = orc.routing_fingerprint(self.route(), self.cfg,
                                         project=self.project, role="explorer")
        self.assertNotEqual(first, second)
        observed = orc.opencode_provider_observation(
            self.route(), project=self.project, cfg=self.cfg, role="explorer")
        self.assertEqual(
            observed["endpoint_sha256"],
            orc.hashlib.sha256(b"https://file-b.invalid/v1").hexdigest())

    def test_missing_explicit_config_fails_closed(self):
        self.configure("2.2.7")
        os.environ["OPENCODE_CONFIG"] = str(self.root / "missing.json")
        observed = orc.opencode_provider_observation(
            self.route(), project=self.project, cfg=self.cfg, role="explorer")
        self.assertIn("OPENCODE_CONFIG file is missing", observed["error"])
        result = orc.route_preflight("explorer", self.route(), self.cfg,
                                     self.project, self.state,
                                     run_dir=self.rundir)
        self.assertFalse(result["ok"])
        self.assertEqual(result["classification"], "unprovable_routing")

    def test_unresolved_endpoint_expansion_is_unprovable(self):
        self.configure("1.18.35")
        self.write_json(self.project / "opencode.json",
                        self.provider("{env:AOR31_UNSET_ENDPOINT}", legacy=True))
        os.environ.pop("AOR31_UNSET_ENDPOINT", None)
        result = orc.route_preflight("explorer", self.route(), self.cfg,
                                     self.project, self.state,
                                     run_dir=self.rundir)
        self.assertFalse(result["ok"])
        self.assertEqual(result["classification"], "unprovable_routing")
        self.assertIn("unresolved", " ".join(result["reasons"]))

    def test_malformed_normalized_entry_falls_back_to_the_source_adapter(self):
        self.configure("2.2.7")
        self.write_json(self.project / "opencode.json",
                        self.provider("https://source.invalid/v1"))
        os.environ["FAKE_OC_ENTRIES"] = json.dumps([
            {"type": "document", "info": None}])
        observed = orc.opencode_provider_observation(
            self.route(), project=self.project, cfg=self.cfg, role="explorer")
        self.assertIsNone(observed["error"])
        self.assertEqual(observed["inspection"], "source_adapter")
        self.assertEqual(observed["inspection_reason"],
                         "inspector_document_without_object_info")
        self.assertEqual(
            observed["endpoint_sha256"],
            orc.hashlib.sha256(b"https://source.invalid/v1").hexdigest())

    def test_v1_legacy_config_json_global_file_is_observed(self):
        self.configure("1.18.35")
        legacy = self.home / ".config/opencode/config.json"
        self.write_json(legacy, self.provider("https://legacy-file.invalid/v1",
                                              legacy=True))
        observed = orc.opencode_provider_observation(
            self.route(), project=self.project, cfg=self.cfg, role="explorer")
        self.assertIn(str(legacy), observed["effective_files"])
        self.assertEqual(
            observed["endpoint_sha256"],
            orc.hashlib.sha256(b"https://legacy-file.invalid/v1").hexdigest())

    def test_default_legacy_go_stays_a_subscription_without_a_grant(self):
        self.configure("2.2.7")
        self.write_json(self.home / ".config/opencode/opencode.json",
                        self.provider(None, models={"deepseek-v4.1-flash": {}}))
        result = orc.route_preflight("explorer", self.route(), self.cfg,
                                     self.project, self.state,
                                     run_dir=self.rundir)
        self.assertTrue(result["ok"], result["reasons"])
        self.assertEqual(result["classification"], "go_subscription")


if __name__ == "__main__":
    unittest.main()
