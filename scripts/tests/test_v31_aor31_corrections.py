"""AOR31 Batch 01 correction round 01 regressions (R01-F1..F6)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys
import threading
import time
import unittest
from unittest.mock import patch

import test_orchestrator as baseline
from test_v31_route_sources import FAKE_OPENCODE
from test_v31_grant_ledger import FakeTTY
orc = baseline.orc
FIXTURES = Path(__file__).parent / "fixtures"


class CorrectionTests(unittest.TestCase):
    setUp = baseline.ControlTests.setUp
    tearDown = baseline.ControlTests.tearDown

    def setUp(self):
        baseline.ControlTests.setUp(self)
        self.bin_dir = self.root / "correction-bin"
        self.bin_dir.mkdir()
        script = self.bin_dir / "fake.py"
        script.write_text(FAKE_OPENCODE)
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        (self.bin_dir / "opencode").symlink_to(script)
        (self.bin_dir / "codex").symlink_to(script)
        self.home = self.root / "correction-home"
        self.home.mkdir()
        self.history = self.root / "history"
        self.capture = self.root / "capture.json"
        env_patch = patch.dict(os.environ, {
            "PATH": str(self.bin_dir) + ":" + os.environ["PATH"],
            "HOME": str(self.home), "XDG_CONFIG_HOME": "", "XDG_DATA_HOME": "",
            "OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": "",
            "FAKE_OC_HISTORY": str(self.history),
            "FAKE_OC_CAPTURE": str(self.capture),
            "FAKE_OC_VERSION": "2.2.7"})
        env_patch.start()
        self.addCleanup(env_patch.stop)
        for name in ("OPENCODE_CONFIG", "OPENCODE_CONFIG_DIR",
                     "OPENCODE_CONFIG_CONTENT", "OPENCODE_AUTH_CONTENT",
                     "FAKE_OC_MODE", "FAKE_OC_ENTRIES", "FAKE_OC_PID",
                     "OPENCODE_DISABLE_PROJECT_CONFIG"):
            os.environ.pop(name, None)
            self.addCleanup(lambda name=name: os.environ.pop(name, None))

    @staticmethod
    def alive(pid):
        stat = orc.process_stat(pid)
        return bool(stat and stat.get("state") not in {"Z", "X", "x"})

    def configure(self, version="2.2.7"):
        cfg = orc.read_json(orc.HERE / "config.example.json")
        cfg["runtime"]["opencode_version"] = version
        cfg["authorization"]["sensitive_cli_enabled"] = True
        orc.atomic_json(orc.CONFIG_PATH, cfg)
        self.cfg = orc.config()
        os.environ["FAKE_OC_VERSION"] = version
        self.state["config_sha256"] = orc.configuration_provenance().get("sha256")
        orc.save(self.rundir, self.state)
        return cfg

    def route(self, billing="go", provider="opencode-go",
              model="opencode-go/model"):
        return {"provider": "opencode", "worker_provider": provider,
                "model": model, "effort": "low", "billing": billing}

    def write_json(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))

    def preflight(self, route):
        return orc.route_preflight("explorer", route, self.cfg, self.project,
                                   self.state, run_dir=self.rundir)

    # R01-F1 -----------------------------------------------------------------
    def test_v1_home_opencode_directory_is_discovered_and_cannot_qualify_go(self):
        self.configure("1.18.35")
        self.write_json(self.home / ".opencode" / "opencode.json",
                        {"provider": {"opencode-go": {
                            "options": {"baseURL": "https://home.invalid/v1"},
                            "models": {}}}})
        result = self.preflight(self.route())
        self.assertFalse(result["ok"])
        self.assertEqual(result["classification"], "unqualified_go_route")
        self.assertIn(str(self.home / ".opencode" / "opencode.json"),
                      result["observed"]["effective_files"])
        self.assertIsNotNone(result["observed"]["endpoint_sha256"])

    def test_v1_legacy_global_file_loads_before_opencode_json(self):
        self.configure("1.18.35")
        global_dir = self.home / ".config" / "opencode"
        self.write_json(global_dir / "config.json",
                        {"provider": {"opencode-go": {
                            "options": {"baseURL": None}}}})
        self.write_json(global_dir / "opencode.json",
                        {"provider": {"opencode-go": {
                            "options": {"baseURL": "https://later.invalid/v1"},
                            "models": {}}}})
        result = self.preflight(self.route())
        self.assertFalse(result["ok"])
        self.assertEqual(result["classification"], "unqualified_go_route")
        self.assertEqual(
            result["observed"]["endpoint_sha256"],
            orc.hashlib.sha256(b"https://later.invalid/v1").hexdigest())

    def test_v2_failed_inspection_with_disjoint_legacy_provider_is_unprovable(self):
        self.configure("2.2.7")
        document = {"provider": {"opencode-go": {
            "options": {"baseURL": "https://legacy.invalid/v1"}}},
            "providers": {"other-provider": {}}}
        self.write_json(self.project / "opencode.json", document)
        os.environ["FAKE_OC_MODE"] = "fail"
        result = self.preflight(self.route())
        self.assertFalse(result["ok"])
        self.assertEqual(result["classification"], "unprovable_routing")
        self.assertNotEqual(result["classification"], "go_subscription")

    def test_v2_disjoint_legacy_and_native_providers_match_normalizer(self):
        self.configure("2.2.7")
        document = {"provider": {"opencode-go": {
            "options": {"baseURL": "https://legacy.invalid/v1"}}},
            "providers": {"other-provider": {}}}
        self.write_json(self.project / "opencode.json", document)
        observed = orc.opencode_provider_observation(
            self.route(), project=self.project, cfg=self.cfg, role="explorer")
        self.assertIn("opencode-go", observed["providers"])
        self.assertIn("other-provider", observed["providers"])
        self.assertEqual(
            observed["endpoint_sha256"],
            orc.hashlib.sha256(b"https://legacy.invalid/v1").hexdigest())

    def test_disjoint_provider_fixture_matches_real_normalizer(self):
        fixture = json.loads(
            (FIXTURES / "opencode-v2.2.7-disjoint-provider-config.json").read_text())
        expected = fixture["normalized_documents"][0]["providers"]
        normalized = orc._opencode_normalize_v2_document(fixture["input"])
        self.assertEqual(normalized["providers"], expected)

    def test_clean_legacy_go_paths_remain_subscription(self):
        self.configure("2.2.7")
        self.write_json(self.home / ".config/opencode/opencode.json",
                        {"providers": {"opencode-go": {
                            "models": {"model": {}}}}})
        result = self.preflight(self.route())
        self.assertTrue(result["ok"], result["reasons"])
        self.assertEqual(result["classification"], "go_subscription")
        self.configure("1.18.35")
        self.write_json(self.home / ".config/opencode/opencode.json",
                        {"provider": {"opencode-go": {
                            "models": {"model": {}}}}})
        result = self.preflight(self.route())
        self.assertTrue(result["ok"], result["reasons"])
        self.assertEqual(result["classification"], "go_subscription")

    def test_plugin_configuration_is_unprovable_in_both_dialects(self):
        for version in ("1.18.35", "2.2.7"):
            with self.subTest(dialect=version):
                self.configure(version)
                self.write_json(self.project / "opencode.json",
                                {"plugin": ["example-plugin"],
                                 "providers": {"opencode-go": {"models": {}}}})
                result = self.preflight(self.route())
                self.assertFalse(result["ok"])
                self.assertEqual(result["classification"], "unprovable_routing")
                self.assertIn("plugin", " ".join(result["reasons"]).lower())

    # R01-F2 -----------------------------------------------------------------
    def test_inspector_output_is_never_reused_from_cache(self):
        self.configure("2.2.7")
        first = {"providers": {"opencode-go": {
            "settings": {"baseURL": "https://first.invalid/v1"}, "models": {}}}}
        second = {"providers": {"opencode-go": {
            "settings": {"baseURL": "https://second.invalid/v1"}, "models": {}}}}
        os.environ["FAKE_OC_ENTRIES"] = json.dumps([
            {"type": "document", "info": first}])
        one = orc.opencode_provider_observation(
            self.route(), project=self.project, cfg=self.cfg, role="explorer")
        os.environ["FAKE_OC_ENTRIES"] = json.dumps([
            {"type": "document", "info": second}])
        two = orc.opencode_provider_observation(
            self.route(), project=self.project, cfg=self.cfg, role="explorer")
        self.assertNotEqual(one["endpoint_sha256"], two["endpoint_sha256"])
        self.assertNotEqual(one["routing_material_sha256"],
                            two["routing_material_sha256"])

    def test_identity_is_bound_when_no_selected_provider_entry_exists(self):
        self.configure("1.18.35")
        route = self.route(provider="absent-provider",
                           model="absent-provider/model")
        self.write_json(self.project / "opencode.json",
                        {"provider": {"other": {
                            "options": {"baseURL": "https://one.invalid/v1"}}}})
        first = orc.routing_fingerprint(route, self.cfg, project=self.project,
                                        role="explorer")
        self.write_json(self.project / "opencode.json",
                        {"provider": {"other": {
                            "options": {"baseURL": "https://two.invalid/v1"}}}})
        second = orc.routing_fingerprint(route, self.cfg,
                                         project=self.project, role="explorer")
        self.assertNotEqual(first, second)

    def test_v2_parent_above_git_root_is_observed_and_blocks_drift(self):
        self.configure("2.2.7")
        parent = self.root / "opencode.json"
        self.write_json(parent, {"providers": {"opencode-go": {
            "settings": {"baseURL": "https://parent-first.invalid/v1"},
            "models": {"model": {}}}}})
        route = self.route()
        route["routing_fingerprint"] = orc.routing_fingerprint(
            route, self.cfg, project=self.project, role="explorer")
        first = orc.opencode_provider_observation(
            route, project=self.project, cfg=self.cfg, role="explorer")
        self.assertIn(str(parent), first["effective_files"])
        self.write_json(parent, {"providers": {"opencode-go": {
            "settings": {"baseURL": "https://parent-second.invalid/v1"},
            "models": {"model": {}}}}})
        second = orc.opencode_provider_observation(
            route, project=self.project, cfg=self.cfg, role="explorer")
        self.assertNotEqual(first["endpoint_sha256"], second["endpoint_sha256"])
        drift = orc._route_identity_recheck(
            route, {"observed": first}, self.cfg, self.project, "explorer")
        self.assertIsNotNone(drift)

    # R01-F3 -----------------------------------------------------------------
    def test_ambient_inline_change_during_preparation_never_launches(self):
        self.configure("2.2.7")
        self.write_json(self.project / "opencode.json",
                        {"providers": {"opencode-go": {"models": {"model": {}}}}})
        route = self.route()
        self.state["model_routes"] = {"explorer": route}
        orc.save(self.rundir, self.state)
        original = orc.source_snapshot
        def snapshot(*args, **kwargs):
            result = original(*args, **kwargs)
            os.environ["OPENCODE_CONFIG_CONTENT"] = json.dumps({
                "providers": {"opencode-go": {
                    "settings": {"baseURL": "https://after-preflight.invalid/v1"},
                    "models": {}}}})
            return result
        with patch.object(orc, "source_snapshot", side_effect=snapshot):
            with self.assertRaisesRegex(RuntimeError, "drift|preflight|changed|blocked"):
                orc.call_model(self.rundir, self.state, self.cfg, "explorer",
                               "explorer", "prompt", self.project)
        self.assertIsNone(self.state["active_job"])
        self.assertFalse(self.capture.exists())
        self.assertFalse(self.history.exists())
        self.assertEqual(self.state.get("route_authorizations", []), [])

    def test_child_receives_the_prepared_inline_material(self):
        self.configure("2.2.7")
        self.write_json(self.project / "opencode.json",
                        {"providers": {"opencode-go": {
                            "settings": {"baseURL": "https://approved.invalid/v1"},
                            "models": {"model": {}}}}})
        route = self.route(billing="api")
        route["routing_fingerprint"] = orc.routing_fingerprint(
            route, self.cfg, project=self.project, role="explorer")
        self.state["model_routes"] = {"explorer": route}
        self.state["route_authorizations"] = [{
            "id": "capture-grant", "role": "explorer",
            "route_sha256": orc.route_authorization_sha(route),
            "max_dispatches": 1, "used": 0,
            "attestation": "reviewed endpoint"}]
        orc.save(self.rundir, self.state)
        orc.register_route_grant(self.rundir,
                                 self.state["route_authorizations"][0])
        orc.call_model(self.rundir, self.state, self.cfg, "explorer",
                       "explorer", "prompt", self.project)
        captured = json.loads(self.capture.read_text())
        self.assertEqual(captured["agents"]["abdullah-explorer"],
                         orc.opencode_profile("explorer", "v2"))
        self.assertNotIn("after-preflight.invalid", self.capture.read_text())

    # R01-F4 -----------------------------------------------------------------
    def test_unpinned_public_grant_is_refused_before_creation(self):
        self.configure("1.18.35")
        self.write_json(self.project / "opencode.json",
                        {"provider": {"opencode-go": {
                            "options": {"baseURL": "https://first.invalid/v1"},
                            "models": {}}}})
        route = self.route(billing="api")
        self.state["model_routes"] = {"explorer": route}
        orc.save(self.rundir, self.state)
        with patch.object(orc.sys, "stdin", FakeTTY()):
            with self.assertRaisesRegex(RuntimeError, "material binding"):
                orc.authorize_route_run(
                    "test-run00", "explorer", max_dispatches=2,
                    confirmation="authorize-route:test-run00")
        result = self.preflight(route)
        self.assertFalse(result["ok"])
        self.assertEqual(result["classification"], "unbound_route")

    def test_pinned_grant_cannot_authorize_a_changed_endpoint(self):
        self.configure("1.18.35")
        self.write_json(self.project / "opencode.json",
                        {"provider": {"opencode-go": {
                            "options": {"baseURL": "https://first.invalid/v1"},
                            "models": {}}}})
        route = self.route(billing="api")
        route["routing_fingerprint"] = orc.routing_fingerprint(
            route, self.cfg, project=self.project, role="explorer")
        self.state["model_routes"] = {"explorer": route}
        self.state["route_authorizations"] = [{
            "id": "grant", "role": "explorer",
            "route_sha256": orc.route_authorization_sha(route),
            "max_dispatches": 1, "used": 0,
            "attestation": "reviewed endpoint"}]
        orc.save(self.rundir, self.state)
        self.write_json(self.project / "opencode.json",
                        {"provider": {"opencode-go": {
                            "options": {"baseURL": "https://second.invalid/v1"},
                            "models": {}}}})
        result = self.preflight(route)
        self.assertFalse(result["ok"])
        self.assertIn("changed", " ".join(result["reasons"]))
        self.assertNotIn("authorization", result)

    # R01-F5 -----------------------------------------------------------------
    def runtime_project(self):
        self.state.update(phase="plan", status="running")
        ignored = self.project / ".gitignore"
        ignored.write_text(".cache/\nruntime\n")
        self.write_path(".cache/lib/unused.txt", "stable\n")
        self.write_path(".cache/shared.py", "value = 1\n")
        (self.project / ".cache/lib/module.py").symlink_to("../shared.py")
        (self.project / "runtime").symlink_to(".cache/lib")
        orc.save(self.rundir, self.state)

    def write_path(self, name, text):
        path = self.project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def install_codex_mutation(self, path):
        script = self.bin_dir / "codex"
        if script.is_symlink() or script.exists():
            script.unlink()
        script.write_text(
            "#!/usr/bin/env python3\n"
            "import json, pathlib, sys\n"
            "if '--version' in sys.argv:\n"
            "    print('0.167.0'); sys.exit(0)\n"
            "pathlib.Path(%r).write_text('mutated\\n')\n"
            "output = pathlib.Path(sys.argv[sys.argv.index('--output-last-message') + 1])\n"
            "output.write_text(json.dumps({'contract_version': 2, 'status': 'complete',\n"
            "    'summary': 'plan', 'invariants': ['Keep behavior'], 'blocker': '',\n"
            "    'batches': [{'title': 'b', 'goal': 'g', 'acceptance': ['a'],\n"
            "                 'checks': [['true']], 'risk': 'ordinary'}]}))\n"
            % path)
        script.chmod(0o755)

    def test_nested_runtime_symlink_target_change_blocks_planning(self):
        self.configure("1.18.35")
        self.runtime_project()
        self.install_codex_mutation(".cache/shared.py")
        before = orc.source_snapshot(self.project)
        with self.assertRaises(orc.SourceMutationError):
            orc.call_model(self.rundir, self.state, self.cfg, "architect",
                           "plan", "prompt", self.project, host="codex")
        self.assertEqual(self.state["completed_jobs"], [])
        self.assertEqual((self.project / ".cache/shared.py").read_text(),
                         "mutated\n")
        self.assertTrue(before["runtime_inputs"]["complete"])

    def test_nested_outside_or_dangling_link_makes_projection_unprovable(self):
        self.configure("1.18.35")
        self.runtime_project()
        outside = self.root / "outside.py"
        outside.write_text("outside = 1\n")
        (self.project / ".cache/lib/outside.py").symlink_to(outside)
        snapshot = orc.source_snapshot(self.project)
        self.assertFalse(snapshot["runtime_inputs"]["complete"])
        self.assertTrue(orc.source_mutation(snapshot, snapshot)["mutated"])

    def test_nested_link_budget_exhaustion_is_unprovable(self):
        self.configure("1.18.35")
        self.runtime_project()
        cfg = json.loads(json.dumps(self.cfg))
        cfg["verification"]["runtime_inputs"]["max_files"] = 1
        snapshot = orc.source_snapshot(self.project, cfg=cfg)
        self.assertFalse(snapshot["runtime_inputs"]["complete"])

    def test_nested_link_cycle_is_stable_and_change_is_detected(self):
        self.configure("1.18.35")
        self.runtime_project()
        (self.project / ".cache/lib/loop").symlink_to(".")
        snapshot = orc.source_snapshot(self.project)
        self.assertFalse(snapshot["runtime_inputs"]["complete"])
        self.assertTrue(orc.source_mutation(snapshot, snapshot)["mutated"])

    def test_cached_completion_replays_nested_link_mutation(self):
        self.configure("1.18.35")
        self.runtime_project()
        before = orc.source_snapshot(self.project)
        self.write_path(".cache/shared.py", "mutated\n")
        after = orc.source_snapshot(self.project)
        job_dir = self.rundir / "jobs" / "plan-nested"
        job_dir.mkdir(parents=True)
        report = {"contract_version": 2, "status": "complete", "summary": "plan",
                  "invariants": ["Keep behavior"], "blocker": "",
                  "batches": [{"title": "b", "goal": "g", "acceptance": ["a"],
                               "checks": [["true"]], "risk": "ordinary"}]}
        orc.atomic_json(job_dir / "dispatch.json", {"kind": "plan",
                                                    "source": before})
        orc.atomic_json(job_dir / "completion.json",
                        {"final_snapshot": after})
        orc.atomic_json(job_dir / "report.json", report)
        self.state["completed_jobs"] = [{
            "id": "cached-nested", "kind": "plan", "role": "architect",
            "path": str(job_dir), "amendment_epoch": 0,
            "source_integrity": {
                "dispatch_sha256": orc.source_write_sha(before),
                "completion_sha256": orc.source_write_sha(after)}}]
        orc.save(self.rundir, self.state)
        with self.assertRaises(orc.SourceMutationError):
            orc.cached_job_report(self.rundir, self.state, "plan")

    # R01-F6 -----------------------------------------------------------------
    def test_cancel_during_inspection_never_spawns_or_consumes(self):
        self.configure("2.2.7")
        self.write_json(self.project / "opencode.json",
                        {"providers": {"opencode-go": {"models": {"model": {}}}}})
        os.environ["FAKE_OC_MODE"] = "sleep"
        pid_file = self.root / "inspector.pid"
        os.environ["FAKE_OC_PID"] = str(pid_file)
        route = self.route()
        self.state["model_routes"] = {"explorer": route}
        orc.save(self.rundir, self.state)
        def cancel():
            deadline = time.monotonic() + 5
            while not pid_file.exists() and time.monotonic() < deadline:
                time.sleep(0.005)
            orc.atomic_json(self.rundir / "control.json", {"action": "cancel"})
        thread = threading.Thread(target=cancel)
        thread.start()
        started = time.monotonic()
        with patch.object(orc, "_spawn_guarded",
                          wraps=orc._spawn_guarded) as spawn:
            with self.assertRaises(InterruptedError):
                orc.call_model(self.rundir, self.state, self.cfg, "explorer",
                               "explorer", "prompt", self.project, route=route)
            self.assertEqual(spawn.call_count, 0)
        thread.join(timeout=6)
        self.assertLess(time.monotonic() - started, 5.0)
        self.assertIsNone(self.state["active_job"])
        self.assertFalse(self.history.exists())
        self.assertFalse(self.capture.exists())
        pid = int(pid_file.read_text())
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and self.alive(pid):
            time.sleep(0.05)
        self.assertFalse(self.alive(pid))

    def test_inspector_descendant_tree_is_cleaned_up(self):
        self.configure("2.2.7")
        self.write_json(self.project / "opencode.json",
                        {"providers": {"opencode-go": {"models": {"model": {}}}}})
        os.environ["FAKE_OC_MODE"] = "sleep"
        os.environ["FAKE_OC_PID"] = str(self.root / "inspector.pid")
        child_pid = self.root / "inspector-child.pid"
        os.environ["FAKE_OC_CHILD_PID"] = str(child_pid)
        route = self.route()
        self.state["model_routes"] = {"explorer": route}
        orc.save(self.rundir, self.state)
        with patch.object(orc, "OPENCODE_INSPECTION_TIMEOUT", 0.4), \
                patch.object(orc, "_spawn_guarded",
                             wraps=orc._spawn_guarded) as spawn:
            with self.assertRaisesRegex(RuntimeError, "inspection|unprovable|preflight"):
                orc.call_model(self.rundir, self.state, self.cfg, "explorer",
                               "explorer", "prompt", self.project, route=route)
        self.assertEqual(spawn.call_count, 0)
        deadline = time.monotonic() + 5
        while child_pid.exists() is False and time.monotonic() < deadline:
            time.sleep(0.02)
        pids = [int((self.root / "inspector.pid").read_text()),
                int(child_pid.read_text())]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and any(self.alive(pid)
                                                  for pid in pids):
            time.sleep(0.05)
        self.assertEqual([pid for pid in pids if self.alive(pid)], [])

    def test_deadline_during_inspection_never_spawns(self):
        self.configure("2.2.7")
        self.write_json(self.project / "opencode.json",
                        {"providers": {"opencode-go": {"models": {"model": {}}}}})
        os.environ["FAKE_OC_MODE"] = "sleep"
        os.environ["FAKE_OC_PID"] = str(self.root / "inspector.pid")
        route = self.route()
        self.state["model_routes"] = {"explorer": route}
        orc.save(self.rundir, self.state)
        with patch.object(orc, "OPENCODE_INSPECTION_TIMEOUT", 5.0), \
                patch.object(orc, "_spawn_guarded",
                             wraps=orc._spawn_guarded) as spawn:
            with self.assertRaises(TimeoutError):
                orc.call_model(self.rundir, self.state, self.cfg, "explorer",
                               "explorer", "prompt", self.project,
                               route=route, deadline=time.monotonic() + 0.2)
        self.assertEqual(spawn.call_count, 0)
        self.assertFalse(self.history.exists())
        self.assertFalse(self.capture.exists())


if __name__ == "__main__":
    unittest.main()
