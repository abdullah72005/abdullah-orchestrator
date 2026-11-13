"""v3.1 generalized OpenCode worker routes, billing grants and pinned routes."""
from __future__ import annotations

import copy
import contextlib
import io
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


FAKE_OPENCODE = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
if '--version' in args:
    print('1.18.35')
    sys.exit(0)
name = pathlib.Path(sys.argv[0]).name
if name != 'opencode':
    sys.exit(3)
role = args[args.index('--agent') + 1].replace('abdullah-', '')
session = args[args.index('--session') + 1] if '--session' in args else 'ses-' + role
history = pathlib.Path(os.environ.get('FAKE_HISTORY', '/dev/null'))
if os.environ.get('FAKE_HISTORY'):
    with history.open('a') as stream:
        stream.write(role + '\n')
if os.environ.get('FAKE_EXIT'):
    sys.exit(3)
if role == 'reviewer':
    report = {'contract_version': 2, 'status': 'complete', 'summary': 'reviewed',
              'findings': [], 'files': [], 'tests': [], 'evidence': ['app.py:1'],
              'unknowns': [], 'blocker': ''}
else:
    report = {'contract_version': 2, 'status': 'complete', 'summary': role,
              'files': ['app.py'], 'tests': [], 'evidence': ['app.py:1'],
              'unknowns': [], 'blocker': ''}
print(json.dumps({'type': 'text', 'sessionID': session,
                  'part': {'text': json.dumps(report)}}))
print(json.dumps({'type': 'step_finish', 'sessionID': session,
                  'part': {'reason': 'stop'}}))
'''


class WorkerRouteTests(unittest.TestCase):
    setUp = baseline.ControlTests.setUp
    tearDown = baseline.ControlTests.tearDown

    def setUp(self):
        baseline.ControlTests.setUp(self)
        self.bin_dir = self.root / "route-bin"
        self.bin_dir.mkdir()
        fake = self.bin_dir / "opencode"
        fake.write_text(FAKE_OPENCODE)
        fake.chmod(0o755)
        self.home = self.root / "route-home"
        self.home.mkdir()
        self.env_patch = patch.dict(os.environ, {
            "PATH": str(self.bin_dir) + ":" + os.environ["PATH"],
            "HOME": str(self.home), "OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": ""})
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.addCleanup(lambda: os.environ.pop("FAKE_HISTORY", None))
        self.addCleanup(lambda: os.environ.pop("FAKE_EXIT", None))

    def write_config(self, workers, architect=None):
        cfg = orc.read_json(orc.HERE / "config.example.json")
        cfg["workers"] = workers
        if architect:
            cfg["architect"] = architect
        orc.atomic_json(orc.CONFIG_PATH, cfg)
        self.cfg = orc.config()
        self.state["config_sha256"] = orc.configuration_provenance().get("sha256")
        orc.save(self.rundir, self.state)
        return cfg

    def api_workers(self):
        return {
            "explorer": {"provider": "opencode-go",
                         "model": "opencode-go/deepseek-v4.1-flash",
                         "variant": "low", "billing": "go"},
            "implementer": {"provider": "opencode-zen",
                            "model": "opencode-zen/some-model",
                            "variant": "high", "billing": "api"},
            "reviewer": {"provider": "opencode-go",
                         "model": "opencode-go/deepseek-v4.1-flash",
                         "variant": "high", "billing": "go"},
        }

    def grant(self, role, route, count=1, attestation="reviewed api endpoint"):
        entry = {"id": "grant-" + role, "role": role,
                 "route_sha256": orc.route_authorization_sha(route),
                 "max_dispatches": count, "used": 0,
                 "attestation": attestation, "actor": {"user": "tester"},
                 "at": orc.now()}
        self.state.setdefault("route_authorizations", []).append(entry)
        orc.save(self.rundir, self.state)
        return entry

    def test_legacy_all_go_route_is_retained(self):
        route = orc.model_route(self.cfg, "codex", "implementer")
        self.assertEqual(route["provider"], "opencode")
        self.assertEqual(route["worker_provider"], "opencode-go")
        self.assertEqual(route["model"], "opencode-go/deepseek-v4.1-flash")
        self.assertEqual(route["billing"], "go")
        self.assertEqual(route["effort"], "high")
        self.assertTrue(route["routing_fingerprint"])

    def test_mixed_go_api_local_and_free_routes_validate(self):
        workers = self.api_workers()
        workers["explorer"] = {"provider": "local",
                               "model": "local/small", "variant": "",
                               "billing": "local"}
        workers["reviewer"] = {"provider": "free-provider",
                               "model": "free-provider/model", "variant": "",
                               "billing": "free"}
        self.write_config(workers)
        for role in ("explorer", "implementer", "reviewer"):
            route = orc.model_route(self.cfg, "codex", role)
            self.assertEqual(route["provider"], "opencode")
            self.assertTrue(route["worker_provider"])

    def test_invalid_route_configurations_fail_closed(self):
        cases = [
            ({**self.api_workers()["implementer"], "provider": "other"}, "does not match"),
            ({**self.api_workers()["implementer"], "model": "opencode-zen/model#high"},
             "#variant"),
            ({**self.api_workers()["implementer"], "model": "no-slash"}, "provider/model"),
            ({**self.api_workers()["implementer"], "billing": "mystery"}, "billing"),
            ({**self.api_workers()["implementer"], "variant": 3}, "variant"),
            ({**self.api_workers()["implementer"], "model": "opencode-zen/model",
              "fallback": {"provider": "mismatch", "model": "other/model",
                           "billing": "api"}},
             "does not match"),
        ]
        for spec, pattern in cases:
            with self.subTest(pattern=pattern):
                workers = self.api_workers()
                workers["implementer"] = spec
                cfg = orc.read_json(orc.HERE / "config.example.json")
                cfg["workers"] = workers
                orc.atomic_json(orc.CONFIG_PATH, cfg)
                with self.assertRaisesRegex(ValueError, pattern):
                    orc.config()
        self.write_config(self.api_workers())

    def test_unapproved_api_route_fails_before_spawn(self):
        self.write_config(self.api_workers())
        route = orc.model_route(self.cfg, "codex", "implementer")
        self.state["model_routes"] = {"implementer": route}
        orc.save(self.rundir, self.state)
        os.environ["FAKE_HISTORY"] = str(self.root / "history")
        with self.assertRaisesRegex(RuntimeError, "preflight"):
            orc.call_model(self.rundir, self.state, self.cfg, "implementer",
                           "implementer", "prompt", self.project)
        self.assertIsNone(self.state["active_job"])
        self.assertFalse((self.root / "history").exists())

    def test_approved_bounded_api_dispatch_exhausts_its_grant(self):
        self.write_config(self.api_workers())
        route = orc.model_route(self.cfg, "codex", "implementer")
        self.state["model_routes"] = {"implementer": route}
        grant = self.grant("implementer", route, count=1)
        os.environ["FAKE_HISTORY"] = str(self.root / "history")
        report, job = orc.call_model(self.rundir, self.state, self.cfg, "implementer",
                                     "implementer", "prompt", self.project)
        self.assertEqual(report["status"], "complete")
        self.assertEqual(job["route"]["billing"], "api")
        state = orc.read_json(self.rundir / "state.json")
        self.assertEqual(state["route_authorizations"][0]["used"], 1)
        self.assertEqual(state["usage"]["billing"].get("api"), 1)
        with self.assertRaisesRegex(RuntimeError, "preflight"):
            orc.call_model(self.rundir, state, self.cfg, "implementer",
                           "implementer", "prompt", self.project)
        self.assertEqual((self.root / "history").read_text().splitlines(),
                         ["implementer"])

    def test_endpoint_change_after_admission_is_rejected(self):
        self.write_config(self.api_workers())
        route = orc.model_route(self.cfg, "codex", "implementer")
        self.state["model_routes"] = {"implementer": route}
        self.grant("implementer", route)
        with patch.object(orc, "opencode_provider_observation", return_value={
                "available": True, "provider_configured": True,
                "endpoint_sha256": "changed", "auth_env_names": [], "model_count": 1,
                "error": None}):
            result = orc.route_preflight("implementer", route, self.cfg,
                                         self.project, self.state)
        self.assertFalse(result["ok"])
        self.assertTrue(any("routing material changed" in reason
                            for reason in result["reasons"]))

    def test_config_drift_pauses_compatibility(self):
        before = orc.state_compatibility(self.state)
        self.assertEqual(before["status"], "current")
        cfg = orc.read_json(orc.CONFIG_PATH)
        cfg["workers"]["implementer"]["variant"] = "low"
        orc.atomic_json(orc.CONFIG_PATH, cfg)
        after = orc.state_compatibility(self.state)
        self.assertEqual(after["status"], "config_changed")
        self.assertTrue(after["migration_required"])

    def test_authorized_fallback_is_one_dispatch_and_uses_a_fresh_session(self):
        workers = self.api_workers()
        workers["explorer"]["fallback"] = {
            "provider": "opencode-go",
            "model": "opencode-go/other-model", "variant": "low", "billing": "go"}
        self.write_config(workers)
        primary = orc.model_route(self.cfg, "codex", "explorer")
        fallback = primary["fallback_route"]
        self.state["model_routes"] = {"explorer": primary}
        self.state["retry_session"] = {
            "role": "explorer", "session_id": "ses-primary", "reconciled": True,
            "termination_verified": True,
            "route_sha256": orc.route_authorization_sha(primary)}
        os.environ["FAKE_HISTORY"] = str(self.root / "history")
        # No consent: primary route is used.
        report, job = orc.call_model(self.rundir, self.state, self.cfg, "explorer",
                                     "explorer", "prompt", self.project)
        self.assertEqual(job["route"]["model"], primary["model"])
        self.assertEqual(job["continued_session"], "ses-primary")
        # One-dispatch consent selects the exact alternate and drops the session.
        self.state["retry_session"] = {
            "role": "explorer", "session_id": "ses-primary", "reconciled": True,
            "termination_verified": True,
            "route_sha256": orc.route_authorization_sha(primary)}
        self.state["worker_fallback_authorization"] = {
            "role": "explorer",
            "route_sha256": orc.route_authorization_sha(fallback),
            "limit": "one dispatch"}
        report, job = orc.call_model(self.rundir, self.state, self.cfg, "explorer",
                                     "explorer", "prompt", self.project)
        self.assertEqual(job["route"]["model"], fallback["model"])
        self.assertIsNone(job["continued_session"])
        state = orc.read_json(self.rundir / "state.json")
        self.assertIsNone(state["worker_fallback_authorization"])
        # A second dispatch does not silently use the fallback again.
        report, job = orc.call_model(self.rundir, state, self.cfg, "explorer",
                                     "explorer", "prompt", self.project)
        self.assertEqual(job["route"]["model"], primary["model"])

    def test_reviewer_session_is_always_fresh(self):
        route = orc.model_route(self.cfg, "codex", "reviewer")
        self.state["model_routes"] = {"reviewer": route}
        self.state["retry_session"] = {
            "role": "reviewer", "session_id": "ses-old", "reconciled": True,
            "termination_verified": True,
            "route_sha256": orc.route_authorization_sha(route)}
        os.environ["FAKE_HISTORY"] = str(self.root / "history")
        report, job = orc.call_model(self.rundir, self.state, self.cfg, "reviewer",
                                     "reviewer", "prompt", self.project)
        self.assertIsNone(job["continued_session"])

    def test_free_route_keeps_free_model_guard_unless_authorized(self):
        env = orc.opencode_env("explorer", "v1")
        self.assertEqual(env["OPENCODE_DISABLE_FREE_MODELS"], "1")
        env = orc.opencode_env("explorer", "v1", allow_free=True)
        self.assertNotIn("OPENCODE_DISABLE_FREE_MODELS", env)

    def test_free_label_with_custom_endpoint_needs_explicit_attestation(self):
        route = {"provider": "opencode", "worker_provider": "free",
                 "model": "free/model", "effort": "", "billing": "free"}
        self.state["route_authorizations"] = [{
            "id": "g", "role": "explorer",
            "route_sha256": orc.route_authorization_sha(route),
            "max_dispatches": 1, "used": 0, "attestation": "reviewed free route"}]
        with patch.object(orc, "opencode_provider_observation", return_value={
                "available": True, "provider_configured": True,
                "endpoint_sha256": "abc", "auth_env_names": [], "model_count": 1,
                "error": None}):
            result = orc.route_preflight("explorer", route, self.cfg,
                                         self.project, self.state)
        self.assertFalse(result["ok"])
        self.assertIn("custom endpoint", " ".join(result["reasons"]))
        self.state["route_authorizations"][0]["attestation"] = "reviewed free endpoint only"
        with patch.object(orc, "opencode_provider_observation", return_value={
                "available": True, "provider_configured": True,
                "endpoint_sha256": "abc", "auth_env_names": [], "model_count": 1,
                "error": None}):
            result = orc.route_preflight("explorer", route, self.cfg,
                                         self.project, self.state)
        self.assertTrue(result["ok"], result["reasons"])

    def test_nested_explorer_consumes_the_run_route_grant(self):
        from types import SimpleNamespace
        workers = self.api_workers()
        workers["explorer"] = {"provider": "opencode-zen",
                               "model": "opencode-zen/explorer-model",
                               "variant": "low", "billing": "api"}
        self.write_config(workers)
        route = orc.model_route(self.cfg, "codex", "explorer")
        self.assertEqual(route["billing"], "api")
        self.state.update(explorer_policy="on_demand", status="running", phase="plan",
                          model_routes={"explorer": route},
                          active_job={"id": "parent-job", "role": "architect",
                                      "status": "running"})
        self.grant("explorer", route, count=1)
        args = SimpleNamespace(run="test-run00", task="inspect app",
                               parent_job="parent-job")
        os.environ["FAKE_HISTORY"] = str(self.root / "history")
        with patch.object(orc, "load", return_value=(self.rundir, self.state)), \
                patch.object(orc, "config", return_value=self.cfg), \
                contextlib.redirect_stdout(io.StringIO()):
            orc.explore(args)
        state = orc.read_json(self.rundir / "state.json")
        self.assertEqual(state["route_authorizations"][0]["used"], 1)
        self.assertEqual((self.root / "history").read_text().splitlines(),
                         ["explorer"])

    def test_provider_failure_is_distinct_from_preflight(self):
        route = orc.model_route(self.cfg, "codex", "explorer")
        self.state["model_routes"] = {"explorer": route}
        os.environ["FAKE_HISTORY"] = str(self.root / "history")
        os.environ["FAKE_EXIT"] = "1"
        with self.assertRaises(RuntimeError):
            orc.call_model(self.rundir, self.state, self.cfg, "explorer",
                           "explorer", "prompt", self.project)
        self.assertNotIn("preflight_rejection", self.state)
        self.assertTrue(self.state["failed_jobs"])
        self.assertEqual(self.state["failed_jobs"][-1]["status"], "failed")

    def test_generic_inventory_parsing_supports_both_dialects(self):
        v1 = ("opencode-zen/some-model\n" + json.dumps({"variants": {"high": {}}}))
        parsed = orc.parse_model_inventory(v1)
        self.assertIn("opencode-zen/some-model", parsed)
        v2 = orc.parse_model_inventory_v2("opencode-go/deepseek-v4.1-flash\n"
                                          "opencode-zen/some-model\n")
        self.assertIn("opencode-zen/some-model", v2)


if __name__ == "__main__":
    unittest.main()
