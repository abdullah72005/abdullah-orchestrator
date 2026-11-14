"""AOR31 Batch 01 correction round 02 (R02-F1..F3).

Dispatch-boundary fakes and disposable processes only; no inference, plugin
execution or provider account access.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

import test_orchestrator as baseline
import test_v31_aor31_corrections as corrections
orc = baseline.orc


def _wait_dead(test, pid, timeout=6.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not test.alive(pid):
            return True
        time.sleep(0.02)
    return not test.alive(pid)


class R02Base(unittest.TestCase):
    setUp = corrections.CorrectionTests.setUp
    tearDown = corrections.CorrectionTests.tearDown
    configure = corrections.CorrectionTests.configure
    route = corrections.CorrectionTests.route
    write_json = corrections.CorrectionTests.write_json
    preflight = corrections.CorrectionTests.preflight
    alive = staticmethod(corrections.CorrectionTests.alive)

    def replace_opencode(self, body):
        binary = self.bin_dir / "opencode"
        if binary.is_symlink() or binary.exists():
            binary.unlink()
        binary.write_text(body)
        binary.chmod(0o755)
        return binary

    def clean_v1(self):
        self.write_json(self.project / "opencode.json",
                        {"provider": {"opencode-go": {
                            "models": {"model": {}}}}})

    def clean_v2(self):
        self.write_json(self.project / "opencode.json",
                        {"providers": {"opencode-go": {
                            "models": {"model": {}}}}})

    def assert_no_inference(self, state):
        self.assertIsNone(state["active_job"])
        self.assertFalse(self.history.exists())
        self.assertFalse(self.capture.exists())
        self.assertFalse((state.get("usage") or {}).get("strong_calls"))
        self.assertFalse((state.get("usage") or {}).get("cheap_calls"))
        self.assertEqual(orc.load_grant_ledger(self.rundir)["grants"], {})


class VersionBoundaryTests(R02Base):
    """R02-F1: the prepared launch must obey the resolved executable's version."""

    def native_v2_route(self):
        self.write_json(self.project / "opencode.json",
                        {"providers": {"opencode-go": {
                            "settings": {"baseURL": "https://v2-only.invalid/v1"},
                            "models": {"model": {}}}}})
        route = self.route()
        route["effort"] = ""
        self.state["model_routes"] = {"explorer": route}
        orc.save(self.rundir, self.state)
        return route

    def assert_refused(self, route, pattern):
        with patch.object(orc, "_spawn_guarded",
                          wraps=orc._spawn_guarded) as spawn:
            with self.assertRaisesRegex(RuntimeError, pattern):
                orc.call_model(self.rundir, self.state, self.cfg, "explorer",
                               "explorer", "prompt", self.project, route=route)
        self.assertEqual(spawn.call_count, 0)
        state = orc.read_json(self.rundir / "state.json")
        self.assert_no_inference(state)

    def test_pinned_v1_binary_v2_refuses_before_spawn(self):
        self.configure("1.18.35")
        os.environ["FAKE_OC_VERSION"] = "2.2.7"
        self.assert_refused(self.native_v2_route(),
                            "does not match pinned|unprovable")

    def test_pinned_v2_binary_v1_refuses_before_spawn(self):
        self.configure("2.2.7")
        os.environ["FAKE_OC_VERSION"] = "1.18.35"
        self.clean_v1()
        route = self.route()
        self.state["model_routes"] = {"explorer": route}
        orc.save(self.rundir, self.state)
        self.assert_refused(route, "does not match pinned|unprovable")

    def test_unsupported_actual_version_refuses_before_spawn(self):
        self.configure("auto")
        os.environ["FAKE_OC_VERSION"] = "3.0.0"
        self.clean_v2()
        route = self.route()
        self.state["model_routes"] = {"explorer": route}
        orc.save(self.rundir, self.state)
        self.assert_refused(route, "Unsupported OpenCode version|unprovable")

    def test_failed_version_query_refuses_before_spawn(self):
        self.configure("2.2.7")
        self.replace_opencode(
            "#!/usr/bin/env python3\nimport sys\nsys.exit(3)\n")
        self.clean_v2()
        route = self.route()
        self.state["model_routes"] = {"explorer": route}
        orc.save(self.rundir, self.state)
        self.assert_refused(route, "version|unprovable")

    def test_matching_v1_pin_dispatches_with_v1_controls(self):
        self.configure("1.18.35")
        self.clean_v1()
        route = self.route()
        route["effort"] = "low"
        self.state["model_routes"] = {"explorer": route}
        orc.save(self.rundir, self.state)
        commands = []
        original = orc._spawn_guarded
        def spawn(command, *args, **kwargs):
            commands.append(list(command))
            return original(command, *args, **kwargs)
        with patch.object(orc, "_spawn_guarded", side_effect=spawn):
            orc.call_model(self.rundir, self.state, self.cfg, "explorer",
                           "explorer", "prompt", self.project)
        self.assertTrue(commands)
        self.assertFalse(any("--standalone" in command for command in commands))
        self.assertTrue(any("--variant" in command for command in commands))
        self.assertTrue(self.history.exists())

    def test_matching_v2_pin_dispatches_standalone_with_empty_variant(self):
        self.configure("2.2.7")
        self.clean_v2()
        route = self.route()
        route["effort"] = ""
        self.state["model_routes"] = {"explorer": route}
        orc.save(self.rundir, self.state)
        commands = []
        original = orc._spawn_guarded
        def spawn(command, *args, **kwargs):
            commands.append(list(command))
            return original(command, *args, **kwargs)
        with patch.object(orc, "_spawn_guarded", side_effect=spawn):
            orc.call_model(self.rundir, self.state, self.cfg, "explorer",
                           "explorer", "prompt", self.project)
        self.assertTrue(commands)
        self.assertTrue(any("--standalone" in command for command in commands))
        self.assertFalse(any("--variant" in command for command in commands))
        self.assertFalse(any("#" in str(part) for command in commands
                             for part in command if part == route["model"]))
        self.assertTrue(self.history.exists())


class V1SourceBoundaryTests(R02Base):
    """R02-F2: V1 native remaps, child-cwd paths, accounts and plugins."""

    def assert_unqualified(self, entry, expect_endpoint):
        self.configure("1.18.35")
        self.write_json(self.project / "opencode.json",
                        {"provider": {"opencode-go": entry}})
        result = self.preflight(self.route())
        self.assertFalse(result["ok"])
        self.assertNotEqual(result["classification"], "go_subscription")
        if expect_endpoint:
            self.assertIsNotNone(result["observed"].get("endpoint_sha256"))
        self.assertFalse(result["observed"]["go_route"]["qualified"])

    def test_provider_api_custom_url_is_not_go_consent(self):
        self.assert_unqualified(
            {"api": "https://provider-api.invalid/v1",
             "models": {"model": {}}}, expect_endpoint=True)

    def test_model_provider_api_custom_url_is_not_go_consent(self):
        self.assert_unqualified(
            {"models": {"model": {"provider": {
                "api": "https://model-api.invalid/v1"}}}},
            expect_endpoint=True)

    def test_provider_npm_package_remap_is_not_go_consent(self):
        self.assert_unqualified(
            {"npm": "@ai-sdk/anthropic", "models": {"model": {}}},
            expect_endpoint=False)

    def test_model_id_remap_is_not_go_consent(self):
        self.assert_unqualified(
            {"models": {"model": {"id": "upstream-other"}}},
            expect_endpoint=False)

    def test_unmodeled_nested_provider_routing_keys_refuse(self):
        self.configure("1.18.35")
        self.write_json(self.project / "opencode.json",
                        {"provider": {"opencode-go": {
                            "models": {"model": {"provider": {
                                "unknownRoute": "x"}}}}}})
        result = self.preflight(self.route())
        self.assertFalse(result["ok"])
        self.assertNotEqual(result["classification"], "go_subscription")
        self.assertIn("unmodeled", " ".join(result["reasons"]))

    def test_relative_explicit_config_is_resolved_in_child_cwd(self):
        self.configure("1.18.35")
        self.write_json(self.root / "relative.json",
                        {"provider": {"opencode-go": {"models": {"model": {}}}}})
        child = self.project / "relative.json"
        self.write_json(child, {"provider": {"opencode-go": {
            "options": {"baseURL": "https://child-relative.invalid/v1"},
            "models": {"model": {}}}}})
        os.environ["OPENCODE_CONFIG"] = "relative.json"
        prior = Path.cwd()
        try:
            os.chdir(self.root)
            result = self.preflight(self.route())
        finally:
            os.chdir(prior)
            os.environ.pop("OPENCODE_CONFIG", None)
        self.assertFalse(result["ok"])
        self.assertIn(str(child), result["observed"]["effective_files"])
        self.assertEqual(
            result["observed"]["endpoint_sha256"],
            orc.hashlib.sha256(b"https://child-relative.invalid/v1").hexdigest())

    def test_relative_custom_config_directory_is_resolved_in_child_cwd(self):
        self.configure("1.18.35")
        self.write_json(self.project / "relcfg" / "opencode.json",
                        {"provider": {"opencode-go": {
                            "options": {"baseURL": "https://relative-dir.invalid/v1"},
                            "models": {"model": {}}}}})
        os.environ["OPENCODE_CONFIG_DIR"] = "relcfg"
        prior = Path.cwd()
        try:
            os.chdir(self.root)
            result = self.preflight(self.route())
        finally:
            os.chdir(prior)
            os.environ.pop("OPENCODE_CONFIG_DIR", None)
        self.assertFalse(result["ok"])
        self.assertIn(str(self.project / "relcfg" / "opencode.json"),
                      result["observed"]["effective_files"])

    def account_db(self, active=True):
        path = self.root / "account.db"
        connection = sqlite3.connect(path)
        connection.executescript('''
CREATE TABLE account(id TEXT PRIMARY KEY,email TEXT NOT NULL,url TEXT NOT NULL,
  access_token TEXT NOT NULL,refresh_token TEXT NOT NULL,token_expiry INTEGER,
  time_created INTEGER,time_updated INTEGER);
CREATE TABLE account_state(id INTEGER PRIMARY KEY,active_account_id TEXT,
  active_org_id TEXT);
INSERT INTO account VALUES('synthetic-account','test@example.invalid',
  'https://org.invalid','dummy-access','dummy-refresh',4102444800000,0,0);
''')
        connection.execute("INSERT INTO account_state VALUES(1,?,?)",
                           ("synthetic-account" if active else None,
                            "synthetic-org" if active else None))
        connection.commit()
        connection.close()
        return path

    def test_active_account_store_is_inspected_read_only_and_refused(self):
        self.configure("1.18.35")
        self.clean_v1()
        path = self.account_db(active=True)
        os.environ["OPENCODE_DB"] = str(path)
        try:
            result = self.preflight(self.route())
        finally:
            os.environ.pop("OPENCODE_DB", None)
        self.assertFalse(result["ok"])
        self.assertEqual(result["classification"], "unprovable_routing")
        boundary = result["observed"]["boundary"]
        self.assertFalse(boundary["adapter_complete"])
        self.assertTrue(boundary["account_store"]["active"])
        self.assertIn("account", " ".join(boundary["external_hazards"]).lower())
        self.assertTrue(any(record.get("path") == str(path)
                            for record in result["observed"]["source_identity"]))
        self.assertNotIn("dummy-access", json.dumps(result))

    def test_account_store_without_active_selection_is_still_unprovable(self):
        self.configure("1.18.35")
        self.clean_v1()
        path = self.account_db(active=False)
        os.environ["OPENCODE_DB"] = str(path)
        try:
            result = self.preflight(self.route())
        finally:
            os.environ.pop("OPENCODE_DB", None)
        self.assertFalse(result["ok"])
        self.assertEqual(result["classification"], "unprovable_routing")

    def test_absent_and_malformed_account_stores(self):
        self.configure("1.18.35")
        self.clean_v1()
        absent = self.root / "missing-account.db"
        os.environ["OPENCODE_DB"] = str(absent)
        try:
            clean = self.preflight(self.route())
        finally:
            os.environ.pop("OPENCODE_DB", None)
        self.assertTrue(clean["ok"], clean["reasons"])
        self.assertEqual(clean["classification"], "go_subscription")
        malformed = self.root / "not-a-db"
        malformed.write_text("not sqlite")
        os.environ["OPENCODE_DB"] = str(malformed)
        try:
            broken = self.preflight(self.route())
        finally:
            os.environ.pop("OPENCODE_DB", None)
        self.assertFalse(broken["ok"])
        self.assertEqual(broken["classification"], "unprovable_routing")

    def test_unreadable_account_file_is_unprovable(self):
        self.configure("1.18.35")
        self.clean_v1()
        store = self.root / "account-dir.db"
        store.mkdir()
        os.environ["OPENCODE_DB"] = str(store)
        try:
            with self.assertRaisesRegex(RuntimeError, "uninspectable|preflight"):
                orc.call_model(self.rundir, self.state, self.cfg, "explorer",
                               "explorer", "prompt", self.project)
        finally:
            os.environ.pop("OPENCODE_DB", None)
        self.assertFalse(self.history.exists())
        self.assertFalse(self.capture.exists())

    def test_automatic_plugin_sources_refuse_in_v1(self):
        self.configure("1.18.35")
        self.clean_v1()
        for directory in ("plugins", "plugin"):
            with self.subTest(directory=directory):
                plugin = self.project / ".opencode" / directory / "local.ts"
                plugin.parent.mkdir(parents=True, exist_ok=True)
                plugin.write_text("export const Local = async () => ({})\n")
                result = self.preflight(self.route())
                self.assertFalse(result["ok"])
                self.assertEqual(result["classification"], "unprovable_routing")
                boundary = result["observed"]["boundary"]
                self.assertTrue(boundary["plugin_config_present"])
                self.assertTrue(any(record["path"] == str(plugin)
                                    for record in boundary["plugin_sources"]))
                plugin.unlink()

    def test_automatic_plugin_source_blocks_before_v2_inspection(self):
        self.configure("2.2.7")
        self.clean_v2()
        plugin = self.project / ".opencode/plugins/local.ts"
        plugin.parent.mkdir(parents=True)
        plugin.write_text("export const Local = async () => ({})\n")
        with patch.object(orc, "_opencode_inspected_documents",
                          wraps=orc._opencode_inspected_documents) as inspector:
            result = self.preflight(self.route())
        self.assertFalse(result["ok"])
        self.assertEqual(result["classification"], "unprovable_routing")
        self.assertEqual(inspector.call_count, 0)

    def test_clean_legacy_go_controls_remain_subscription(self):
        self.configure("1.18.35")
        self.clean_v1()
        result = self.preflight(self.route())
        self.assertTrue(result["ok"], result["reasons"])
        self.assertEqual(result["classification"], "go_subscription")
        self.assertEqual(result["observed"]["boundary"]["plugin_sources"], [])


class InspectorLifecycleTests(R02Base):
    """R02-F3: whole-execution ownership and budget for inspection/version."""

    def spawn_parent(self, body, **subs):
        script = self.root / "parent.py"
        script.write_text(body)
        for name, value in subs.items():
            script.write_text(script.read_text().replace(name, str(value)))
        return script

    def test_leader_exits_with_live_closed_stdio_child_is_contained(self):
        pidfile = self.root / "child.pid"
        parent = self.spawn_parent(
            "import pathlib,subprocess,sys\n"
            "child=subprocess.Popen([sys.executable,'-c',"
            "'import time;time.sleep(60)'],stdin=subprocess.DEVNULL,"
            "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n"
            "pathlib.Path(sys.argv[1]).write_text(str(child.pid))\n"
            "print('[]')\n")
        rc, out, err = orc._opencode_run_bounded(
            [sys.executable, str(parent), str(pidfile)], self.root,
            {"PATH": os.environ["PATH"]}, 2)
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "[]")
        pid = int(pidfile.read_text())
        self.assertTrue(_wait_dead(self, pid),
                        "inspector descendant survived a successful leader exit")
        self.assertIsNone(orc.process_stat(pid))

    def test_session_escaping_descendant_is_tracked_and_contained(self):
        pidfile = self.root / "escaped.pid"
        parent = self.spawn_parent(
            "import pathlib,subprocess,sys,time\n"
            "child=subprocess.Popen([sys.executable,'-c',"
            "'import os,time;os.setsid();time.sleep(60)'],"
            "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,"
            "stderr=subprocess.DEVNULL)\n"
            "pathlib.Path(sys.argv[1]).write_text(str(child.pid))\n"
            "time.sleep(0.4)\n"
            "print('[]')\n")
        rc, out, _ = orc._opencode_run_bounded(
            [sys.executable, str(parent), str(pidfile)], self.root,
            {"PATH": os.environ["PATH"]}, 3)
        self.assertEqual(rc, 0)
        pid = int(pidfile.read_text())
        self.assertTrue(_wait_dead(self, pid),
                        "setsid descendant escaped whole-execution ownership")

    def test_other_process_group_same_session_is_contained(self):
        pidfile = self.root / "regrouped.pid"
        parent = self.spawn_parent(
            "import pathlib,subprocess,sys\n"
            "child=subprocess.Popen([sys.executable,'-c',"
            "'import os,time;os.setpgid(0,0);time.sleep(60)'],"
            "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,"
            "stderr=subprocess.DEVNULL)\n"
            "pathlib.Path(sys.argv[1]).write_text(str(child.pid))\n"
            "print('[]')\n")
        rc, _, _ = orc._opencode_run_bounded(
            [sys.executable, str(parent), str(pidfile)], self.root,
            {"PATH": os.environ["PATH"]}, 2)
        self.assertEqual(rc, 0)
        pid = int(pidfile.read_text())
        self.assertTrue(_wait_dead(self, pid))

    def test_denied_termination_retains_ownership_and_fails_closed(self):
        pidfile = self.root / "denied.pid"
        command = [sys.executable, "-c",
                   "import pathlib,os,time\n"
                   f"pathlib.Path({str(pidfile)!r}).write_text(str(os.getpid()))\n"
                   "time.sleep(60)\n"]
        real_kill = os.kill
        real_killpg = os.killpg
        try:
            with patch.object(orc.os, "kill", side_effect=PermissionError), \
                    patch.object(orc.os, "killpg", side_effect=PermissionError):
                with self.assertRaises(orc.InspectionContainmentError):
                    orc._opencode_run_bounded(
                        command, self.root, {"PATH": os.environ["PATH"]}, 0.2)
        finally:
            if pidfile.exists():
                pid = int(pidfile.read_text())
                try:
                    real_killpg(pid, signal.SIGKILL)
                except OSError:
                    pass
                try:
                    real_kill(pid, signal.SIGKILL)
                except OSError:
                    pass
                self.assertTrue(_wait_dead(self, pid))

    def test_cold_version_query_respects_auto_and_pinned_deadlines(self):
        for pin in ("auto", "2.2.7"):
            with self.subTest(pin=pin):
                self.configure(pin)
                script = self.bin_dir / "fake.py"
                script.write_text(script.read_text().replace(
                    "if '--version' in args:",
                    "if '--version' in args:\n    time.sleep(0.6)"))
                self.clean_v2()
                route = self.route()
                self.state["model_routes"] = {"explorer": route}
                orc.save(self.rundir, self.state)
                started = time.monotonic()
                with patch.object(orc, "_spawn_guarded",
                                  wraps=orc._spawn_guarded) as spawn:
                    with self.assertRaises(TimeoutError):
                        orc.call_model(self.rundir, self.state, self.cfg,
                                       "explorer", "explorer", "prompt",
                                       self.project, route=route,
                                       deadline=time.monotonic() + 0.08)
                    self.assertEqual(spawn.call_count, 0)
                self.assertLess(time.monotonic() - started, 2.0)
                state = orc.read_json(self.rundir / "state.json")
                self.assert_no_inference(state)

    def test_cold_version_query_cancellation_is_distinct(self):
        self.configure("2.2.7")
        pidfile = self.root / "version.pid"
        self.replace_opencode(
            "#!/usr/bin/env python3\n"
            "import os,pathlib,sys,time\n"
            "if '--version' in sys.argv:\n"
            f"    pathlib.Path({str(pidfile)!r}).write_text(str(os.getpid()))\n"
            "    time.sleep(0.6)\n"
            "    print('2.2.7')\n"
            "    sys.exit(0)\n"
            "sys.exit(3)\n")
        self.clean_v2()
        route = self.route()
        self.state["model_routes"] = {"explorer": route}
        orc.save(self.rundir, self.state)
        def cancel():
            deadline = time.monotonic() + 5
            while not pidfile.exists() and time.monotonic() < deadline:
                time.sleep(0.005)
            orc.atomic_json(self.rundir / "control.json", {"action": "cancel"})
        thread = threading.Thread(target=cancel)
        thread.start()
        started = time.monotonic()
        try:
            with patch.object(orc, "_spawn_guarded",
                              wraps=orc._spawn_guarded) as spawn:
                with self.assertRaises(InterruptedError):
                    orc.call_model(self.rundir, self.state, self.cfg,
                                   "explorer", "explorer", "prompt",
                                   self.project, route=route)
                self.assertEqual(spawn.call_count, 0)
        finally:
            thread.join(timeout=6)
        self.assertLess(time.monotonic() - started, 5.0)
        self.assertTrue(pidfile.exists())
        self.assertTrue(_wait_dead(self, int(pidfile.read_text())))
        state = orc.read_json(self.rundir / "state.json")
        self.assert_no_inference(state)


if __name__ == "__main__":
    unittest.main()
