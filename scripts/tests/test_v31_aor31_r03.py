"""AOR31 Batch 01 correction round 03 (R03-F1..F3).

Disposable SQLite stores, source-backed V1 fixtures and owned test processes
only; no real V1 binary, account request, plugin execution or inference.
"""
from __future__ import annotations

import os
from pathlib import Path
import signal
import sqlite3
import sys
import time
import unittest
from unittest.mock import patch

import test_v31_aor31_r02 as r02
import test_v31_aor31_corrections as corrections
orc = r02.orc


def _wait_dead(test, pid, timeout=6.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not test.alive(pid):
            return True
        time.sleep(0.02)
    return not test.alive(pid)


ACCOUNT_SCHEMA = '''
CREATE TABLE account(id TEXT PRIMARY KEY,email TEXT NOT NULL,url TEXT NOT NULL,
  access_token TEXT NOT NULL,refresh_token TEXT NOT NULL,token_expiry INTEGER,
  time_created INTEGER,time_updated INTEGER);
CREATE TABLE account_state(id INTEGER PRIMARY KEY,active_account_id TEXT,
  active_org_id TEXT);
INSERT INTO account_state VALUES(1,NULL,NULL);
'''


class R03Base(r02.R02Base):
    def account_db(self, path=None, active=False):
        path = Path(path or (self.root / "account.db"))
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        connection.executescript(ACCOUNT_SCHEMA)
        if active:
            connection.execute(
                "INSERT INTO account VALUES('synthetic-account',"
                "'test@example.invalid','https://org.invalid','dummy-access',"
                "'dummy-refresh',4102444800000,0,0)")
            connection.execute(
                "UPDATE account_state SET active_account_id=?,active_org_id=?",
                ("synthetic-account", "synthetic-org"))
        connection.commit()
        connection.close()
        return path

    def session_db(self, path):
        connection = sqlite3.connect(path)
        connection.executescript('''
CREATE TABLE account(id TEXT PRIMARY KEY,email TEXT NOT NULL,url TEXT NOT NULL,
  access_token TEXT NOT NULL,refresh_token TEXT NOT NULL,token_expiry INTEGER);
CREATE TABLE account_state(id INTEGER PRIMARY KEY,active_account_id TEXT,
  active_org_id TEXT);
INSERT INTO account_state VALUES(1,NULL,NULL);
CREATE TABLE session(id TEXT PRIMARY KEY,title TEXT NOT NULL);
INSERT INTO session VALUES('session-1','first');
CREATE TABLE message(id TEXT PRIMARY KEY,session_id TEXT,data TEXT);
CREATE TABLE part(id TEXT PRIMARY KEY,message_id TEXT,data TEXT);
''')
        connection.commit()
        connection.close()
        return path

    def set_env(self, **values):
        patch_dict = {key: str(value) for key, value in values.items()}
        patcher = patch.dict(os.environ, patch_dict)
        patcher.start()
        self.addCleanup(patcher.stop)

    def pinned_route(self, route):
        first = orc.opencode_provider_observation(
            route, self.project, cfg=self.cfg, role="explorer")
        route["routing_fingerprint"] = orc.routing_fingerprint(
            route, self.cfg, project=self.project, observation=first,
            role="explorer")
        return route

    def assert_no_model_dispatch(self, spawn):
        corrections.assert_no_inference_dispatch(self, spawn)

    def kill_pid(self, pid):
        if not pid:
            return
        for sender in (os.killpg, os.kill):
            try:
                sender(pid, signal.SIGKILL)
            except OSError:
                pass
        self.assertTrue(_wait_dead(self, pid))


class AccountStoreSelectionTests(R03Base):
    """R03-F1: inspect the exact V1 store selected by the upstream contract."""

    def test_relative_database_resolves_under_the_data_root(self):
        self.configure("1.18.35")
        self.clean_v1()
        actual = self.home / ".local/share/opencode/selected.db"
        actual.parent.mkdir(parents=True)
        self.account_db(actual, active=True)
        self.assertFalse((self.project / "selected.db").exists())
        self.set_env(OPENCODE_DB="selected.db")
        result = self.preflight(self.route())
        self.assertFalse(result["ok"])
        self.assertEqual(result["classification"], "unprovable_routing")
        store = result["observed"]["boundary"]["account_store"]
        self.assertEqual(store["path"], str(actual))
        self.assertEqual(store["mode"], "relative")
        self.assertTrue(store["active"])
        self.assertIn("account", " ".join(
            result["observed"]["boundary"]["external_hazards"]).lower())

    def test_absolute_database_path_is_inspected(self):
        self.configure("1.18.35")
        self.clean_v1()
        store = self.account_db(self.root / "absolute.db", active=True)
        self.set_env(OPENCODE_DB=store)
        result = self.preflight(self.route())
        self.assertFalse(result["ok"])
        self.assertEqual(
            result["observed"]["boundary"]["account_store"]["path"], str(store))

    def test_default_data_root_database_is_inspected(self):
        self.configure("1.18.35")
        self.clean_v1()
        store = self.home / ".local/share/opencode/opencode.db"
        store.parent.mkdir(parents=True)
        self.account_db(store, active=True)
        result = self.preflight(self.route())
        self.assertFalse(result["ok"])
        boundary = result["observed"]["boundary"]
        self.assertEqual(boundary["account_store"]["path"], str(store))
        self.assertEqual(boundary["account_store"]["mode"], "default")

    def test_explicit_data_root_and_channel_selector(self):
        self.configure("1.18.35")
        self.clean_v1()
        xdg = self.root / "xdg"
        store = xdg / "opencode/opencode.db"
        store.parent.mkdir(parents=True)
        self.account_db(store, active=True)
        self.set_env(XDG_DATA_HOME=xdg, OPENCODE_DISABLE_CHANNEL_DB="1")
        result = self.preflight(self.route())
        self.assertFalse(result["ok"])
        self.assertEqual(
            result["observed"]["boundary"]["account_store"]["path"], str(store))

    def test_channel_database_name_follows_the_compiled_channel(self):
        env = {"HOME": str(self.home)}
        self.assertEqual(
            orc._opencode_database_filename(
                env, {"version": {"text": "1.18.35"}}), ("opencode.db", None))
        self.assertEqual(
            orc._opencode_database_filename(
                env, {"version": {"text": "0.0.0-dev-202601010000"}}),
            ("opencode-dev.db", None))
        self.assertEqual(
            orc._opencode_database_filename(
                env, {"version": {"text": "0.0.0-design/r03-202601010000"}}),
            ("opencode-design-r03.db", None))
        self.assertEqual(
            orc._opencode_database_filename(
                {"HOME": str(self.home), "OPENCODE_DISABLE_CHANNEL_DB": "true"},
                {"version": {"text": "0.0.0-dev-202601010000"}}),
            ("opencode.db", None))

    def test_unhonored_data_dir_does_not_divert_the_scan(self):
        self.configure("1.18.35")
        self.clean_v1()
        actual = self.home / ".local/share/opencode/opencode.db"
        actual.parent.mkdir(parents=True)
        self.account_db(actual, active=True)
        divert = self.root / "divert"
        divert_store = self.account_db(divert / "opencode.db", active=False)
        self.set_env(OPENCODE_DATA_DIR=divert)
        refused = self.preflight(self.route())
        self.assertFalse(refused["ok"])
        self.assertEqual(
            refused["observed"]["boundary"]["account_store"]["path"], str(actual))
        self.assertNotEqual(
            refused["observed"]["boundary"]["account_store"]["path"],
            str(divert_store))
        actual.unlink()
        clean = self.preflight(self.route())
        self.assertTrue(clean["ok"], clean["reasons"])
        self.assertEqual(clean["classification"], "go_subscription")

    def test_memory_store_has_no_persistent_account_routing(self):
        self.configure("1.18.35")
        self.clean_v1()
        self.set_env(OPENCODE_DB=":memory:")
        result = self.preflight(self.route())
        self.assertTrue(result["ok"], result["reasons"])
        store = result["observed"]["boundary"]["account_store"]
        self.assertEqual(store["mode"], "memory")
        self.assertIsNone(store["path"])

    def test_relative_missing_malformed_and_directory_stores(self):
        self.configure("1.18.35")
        self.clean_v1()
        self.set_env(OPENCODE_DB="missing.db")
        missing = self.preflight(self.route())
        self.assertTrue(missing["ok"], missing["reasons"])
        self.assertEqual(
            missing["observed"]["boundary"]["account_store"]["mode"], "relative")
        data_dir = self.home / ".local/share/opencode"
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "broken.db").write_text("not sqlite")
        self.set_env(OPENCODE_DB="broken.db")
        broken = self.preflight(self.route())
        self.assertFalse(broken["ok"])
        self.assertEqual(broken["classification"], "unprovable_routing")
        (data_dir / "directory.db").mkdir()
        self.set_env(OPENCODE_DB="directory.db")
        directory = self.preflight(self.route())
        self.assertFalse(directory["ok"])
        self.assertEqual(directory["classification"], "unprovable_routing")

    def test_unresolved_default_store_refuses(self):
        self.configure("1.18.35")
        self.clean_v1()
        with patch.object(orc, "_opencode_database_filename",
                          return_value=(None, "channel cannot be established")):
            result = self.preflight(self.route())
        self.assertFalse(result["ok"])
        self.assertEqual(result["classification"], "unprovable_routing")
        self.assertFalse(
            result["observed"]["boundary"]["account_store"]["resolved"])
        self.assertIn("cannot be established", " ".join(
            result["observed"]["boundary"]["external_hazards"]))

    def test_active_store_refuses_before_inference_or_grant_use(self):
        self.configure("1.18.35")
        self.clean_v1()
        actual = self.home / ".local/share/opencode/selected.db"
        actual.parent.mkdir(parents=True)
        self.account_db(actual, active=True)
        self.set_env(OPENCODE_DB="selected.db")
        route = self.route()
        self.state["model_routes"] = {"explorer": route}
        orc.save(self.rundir, self.state)
        with patch.object(orc, "_spawn_guarded",
                          wraps=orc._spawn_guarded) as spawn:
            with self.assertRaisesRegex(RuntimeError, "preflight|routing"):
                orc.call_model(self.rundir, self.state, self.cfg, "explorer",
                               "explorer", "prompt", self.project, route=route)
            self.assert_no_model_dispatch(spawn)
        state = orc.read_json(self.rundir / "state.json")
        self.assertIsNone(state["active_job"])
        self.assertFalse(self.history.exists())
        self.assertFalse(self.capture.exists())
        self.assertEqual(orc.load_grant_ledger(self.rundir)["grants"], {})


class AccountMetadataIdentityTests(R03Base):
    """R03-F2: bind account-routing metadata, not mutable session history."""

    def test_session_writes_keep_the_pinned_route_valid(self):
        self.configure("1.18.35")
        self.clean_v1()
        store = self.session_db(self.root / "history.db")
        self.set_env(OPENCODE_DB=store)
        route = self.pinned_route(self.route())
        first = self.preflight(route)
        self.assertTrue(first["ok"], first["reasons"])
        before = first["observed"]["boundary"]["account_store"]
        connection = sqlite3.connect(store)
        connection.execute("UPDATE session SET title='ordinary-session-write'")
        connection.execute("INSERT INTO session VALUES('session-2','second')")
        connection.execute(
            "INSERT INTO message VALUES('m1','session-1','{}')")
        connection.execute("INSERT INTO part VALUES('p1','m1','{}')")
        connection.commit()
        connection.close()
        second = self.preflight(route)
        self.assertTrue(second["ok"], second["reasons"])
        self.assertEqual(second["classification"], "go_subscription")
        after = second["observed"]["boundary"]["account_store"]
        self.assertEqual(before["accounts"], after["accounts"])
        self.assertFalse(before["active"] or after["active"])
        self.assertEqual(before["routing_sha256"], after["routing_sha256"])
        self.assertNotEqual(before["sha256"], after["sha256"])
        # The same pin and dispatch boundary must still launch after ordinary
        # history activity; the fake CLI never writes to the account store.
        self.state["model_routes"] = {"explorer": route}
        orc.save(self.rundir, self.state)
        orc.call_model(self.rundir, self.state, self.cfg, "explorer",
                       "explorer", "prompt", self.project, route=route)
        self.assertTrue(self.history.exists())
        self.assertFalse((self.state.get("usage") or {}).get("strong_calls"))

    def test_benign_empty_store_initialization_keeps_the_pin(self):
        self.configure("1.18.35")
        self.clean_v1()
        store = self.root / "initialized.db"
        self.set_env(OPENCODE_DB=store)
        route = self.pinned_route(self.route())
        missing = self.preflight(route)
        self.assertTrue(missing["ok"], missing["reasons"])
        connection = sqlite3.connect(store)
        connection.executescript(ACCOUNT_SCHEMA)
        connection.commit()
        connection.close()
        initialized = self.preflight(route)
        self.assertTrue(initialized["ok"], initialized["reasons"])
        self.assertEqual(
            missing["observed"]["boundary"]["account_store"]["routing_sha256"],
            initialized["observed"]["boundary"]["account_store"]["routing_sha256"])

    def test_account_row_or_active_org_change_refuses_before_spawn(self):
        self.configure("1.18.35")
        self.clean_v1()
        store = self.account_db(self.root / "changed.db")
        self.set_env(OPENCODE_DB=store)
        route = self.pinned_route(self.route())
        clean = self.preflight(route)
        self.assertTrue(clean["ok"], clean["reasons"])
        connection = sqlite3.connect(store)
        connection.execute(
            "INSERT INTO account VALUES('new','new@example.invalid',"
            "'https://org.invalid','access','refresh',4102444800000,0,0)")
        connection.execute(
            "UPDATE account_state SET active_account_id='new',"
            "active_org_id='org-2'")
        connection.commit()
        connection.close()
        refused = self.preflight(route)
        self.assertFalse(refused["ok"])
        self.assertEqual(refused["classification"], "unprovable_routing")
        with patch.object(orc, "_spawn_guarded",
                          wraps=orc._spawn_guarded) as spawn:
            with self.assertRaisesRegex(RuntimeError, "preflight|routing"):
                orc.call_model(self.rundir, self.state, self.cfg, "explorer",
                               "explorer", "prompt", self.project, route=route)
            self.assert_no_model_dispatch(spawn)
        self.assertFalse(self.history.exists())
        self.assertFalse(self.capture.exists())

    def test_active_organization_change_alone_refuses(self):
        self.configure("1.18.35")
        self.clean_v1()
        store = self.account_db(self.root / "org.db")
        self.set_env(OPENCODE_DB=store)
        route = self.pinned_route(self.route())
        self.assertTrue(self.preflight(route)["ok"])
        connection = sqlite3.connect(store)
        connection.execute(
            "UPDATE account_state SET active_org_id='org-only'")
        connection.commit()
        connection.close()
        refused = self.preflight(route)
        self.assertFalse(refused["ok"])
        self.assertEqual(refused["classification"], "unprovable_routing")
        self.assertTrue(
            refused["observed"]["boundary"]["account_store"]["active"])


class InspectionOwnershipTests(R03Base):
    """R03-F3: owned inspection survives post-snapshot escape and denial."""

    def inspector_parent(self, body):
        script = self.root / f"parent-{time.monotonic_ns()}.py"
        script.write_text(body)
        return script

    def test_post_snapshot_fast_detached_child_is_contained(self):
        release = self.root / "release"
        pidfile = self.root / "fast.pid"
        parent = self.inspector_parent(
            "import pathlib,subprocess,sys,time\n"
            "while not pathlib.Path(sys.argv[1]).exists():\n"
            "    time.sleep(.001)\n"
            "child=subprocess.Popen([sys.executable,'-c',"
            "'import time;time.sleep(60)'],start_new_session=True,"
            "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,"
            "stderr=subprocess.DEVNULL)\n"
            "pathlib.Path(sys.argv[2]).write_text(str(child.pid))\n"
            "print('[]')\n")
        original = orc._opencode_track_descendants
        pid = None

        def scan_then_release(leader, tracked):
            original(leader, tracked)
            release.write_text("after-empty-snapshot")

        try:
            with patch.object(orc, "_opencode_track_descendants",
                              side_effect=scan_then_release):
                # The fake parent only exits after spawning the detached
                # child, so the bounded containment starts after the child
                # exists.  Keep the bound generous enough that host load
                # cannot clip the parent before that marker is written.
                rc, out, _ = orc._opencode_run_bounded(
                    [sys.executable, str(parent), str(release), str(pidfile)],
                    self.root, {"PATH": os.environ["PATH"]}, 10)
            self.assertEqual(rc, 0)
            self.assertEqual(out.strip(), "[]")
            self.assertTrue(pidfile.exists(),
                            "fake inspector exited without proving the "
                            "post-snapshot child had started")
            pid = int(pidfile.read_text())
            started_stat = orc.process_stat(pid)
            self.assertTrue(_wait_dead(self, pid),
                            "post-snapshot detached child survived")
            stat = orc.process_stat(pid)
            # A zombie is already terminated; a reaped PID (None) or a reused
            # PID also proves this exact child is gone.
            reused = bool(stat and started_stat
                          and stat["starttime"] != started_stat["starttime"])
            self.assertTrue(stat is None or stat["state"] in {"Z", "X", "x"}
                            or reused,
                            f"post-snapshot detached child {pid} is still "
                            f"alive: {stat}")
        finally:
            if pid is None and pidfile.exists():
                pid = int(pidfile.read_text())
            self.kill_pid(pid)

    def test_detached_child_after_a_polling_boundary_is_contained(self):
        pidfile = self.root / "late.pid"
        parent = self.inspector_parent(
            "import pathlib,subprocess,sys,time\n"
            "time.sleep(0.3)\n"
            "child=subprocess.Popen([sys.executable,'-c',"
            "'import time;time.sleep(60)'],start_new_session=True,"
            "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,"
            "stderr=subprocess.DEVNULL)\n"
            "pathlib.Path(sys.argv[1]).write_text(str(child.pid))\n"
            "print('[]')\n")
        pid = None
        try:
            rc, out, _ = orc._opencode_run_bounded(
                [sys.executable, str(parent), str(pidfile)], self.root,
                {"PATH": os.environ["PATH"]}, 3)
            self.assertEqual(rc, 0)
            self.assertEqual(out.strip(), "[]")
            pid = int(pidfile.read_text())
            self.assertTrue(_wait_dead(self, pid))
        finally:
            if pid is None and pidfile.exists():
                pid = int(pidfile.read_text())
            self.kill_pid(pid)

    def test_denied_cleanup_through_dispatch_retains_uncertain_ownership(self):
        self.configure("2.2.7")
        self.clean_v2()
        inspector_pid = self.root / "inspector.pid"
        child_pid = self.root / "inspector-child.pid"
        self.set_env(FAKE_OC_MODE="detach", FAKE_OC_PID=inspector_pid,
                     FAKE_OC_CHILD_PID=child_pid)
        route = self.route()
        self.state["model_routes"] = {"explorer": route}
        orc.save(self.rundir, self.state)
        pid = None
        try:
            with patch.object(orc, "_spawn_guarded",
                              wraps=orc._spawn_guarded) as spawn, \
                    patch.object(orc.os, "kill", side_effect=PermissionError), \
                    patch.object(orc.os, "killpg", side_effect=PermissionError):
                with self.assertRaisesRegex(RuntimeError, "ownership is unproven"):
                    orc.call_model(self.rundir, self.state, self.cfg, "explorer",
                                   "explorer", "prompt", self.project, route=route)
                self.assert_no_model_dispatch(spawn)
            state = orc.read_json(self.rundir / "state.json")
            self.assertEqual(state["status"], "uncertain")
            self.assertIsNone(state["active_job"])
            record = state["active_check"]
            self.assertEqual(record["kind"], "opencode_inspection")
            self.assertEqual(record["status"], "uncertain")
            self.assertTrue(record["pid"])
            self.assertTrue(record["check_token"])
            self.assertTrue(Path(record["launch_file"]).is_file())
            pid = int(child_pid.read_text())
            self.assertIn(pid, [item["pid"] for item in
                                record["escaped_processes"]])
            self.assertFalse(self.history.exists())
            self.assertFalse(self.capture.exists())
            self.assertFalse((state.get("usage") or {}).get("strong_calls"))
            self.assertFalse((state.get("usage") or {}).get("cheap_calls"))
            self.assertEqual(orc.load_grant_ledger(self.rundir)["grants"], {})
            self.assertEqual(orc.next_action_for(state), "orchestrator_reconcile")
            stage = orc.stage_run(state["id"])
            self.assertFalse(stage["ok"])
            self.assertIn("inspection", stage["error"].lower())
            with self.assertRaisesRegex(RuntimeError, "Uncertain active dispatch"):
                orc.modify_locked(self.rundir, state, state["id"], "resume")
            with self.assertRaisesRegex(RuntimeError, "active verification|active check|Cannot dispatch"):
                orc.call_model(self.rundir, state, self.cfg, "explorer",
                               "explorer", "prompt", self.project, route=route)
        finally:
            if pid is None and child_pid.exists():
                pid = int(child_pid.read_text())
            self.kill_pid(pid)
        state = orc.read_json(self.rundir / "state.json")
        inspection = orc.inspect_execution(
            state["active_check"], run_id=state["id"], include_run=True)
        self.assertTrue(inspection["stopped"], inspection["reasons"])
        orc.modify_locked(self.rundir, state, state["id"], "reconcile")
        state = orc.read_json(self.rundir / "state.json")
        self.assertIsNone(state["active_check"])
        self.assertEqual(state["status"], "paused")

    def test_non_run_inspection_retains_exact_metadata_when_denied(self):
        self.configure("2.2.7")
        self.clean_v2()
        inspector_pid = self.root / "inspector.pid"
        child_pid = self.root / "inspector-child.pid"
        self.set_env(FAKE_OC_MODE="detach", FAKE_OC_PID=inspector_pid,
                     FAKE_OC_CHILD_PID=child_pid)
        pid = None
        try:
            with patch.object(orc.os, "kill", side_effect=PermissionError), \
                    patch.object(orc.os, "killpg", side_effect=PermissionError):
                observed = orc.opencode_provider_observation(
                    self.route(), self.project, cfg=self.cfg, role="explorer")
            self.assertIn("ownership is unproven", observed["error"])
            record = observed["inspection_containment"]
            self.assertEqual(record["kind"], "opencode_inspection")
            self.assertTrue(record["pid"])
            self.assertTrue(record["sid"] or record["pgid"])
            self.assertTrue(Path(record["launch_file"]).is_file())
            pid = int(child_pid.read_text())
            self.assertIn(pid, [item["pid"] for item in
                                record["escaped_processes"]])
            with self.assertRaises(orc.InspectionOwnershipUnproven):
                orc.routing_fingerprint(
                    self.route(), self.cfg, project=self.project, role="explorer",
                    observation=observed)
        finally:
            if pid is None and child_pid.exists():
                pid = int(child_pid.read_text())
            self.kill_pid(pid)


if __name__ == "__main__":
    unittest.main()
