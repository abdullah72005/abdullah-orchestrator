"""AOR31-03: bounded, cancellable, separate-process grant-ledger locking."""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import test_orchestrator as baseline
orc = baseline.orc

ORCHESTRATOR = Path(__file__).resolve().parents[1] / "orchestrator.py"
CFG = {"limits": {"max_grant_lock_wait_seconds": 5.0}}


CHILD = r'''
import importlib.util, json, os, pathlib, signal, sys, time
src, run, entry_path, ready, hold, rid, mode = sys.argv[1:8]
wait = float(sys.argv[8]) if len(sys.argv) > 8 else 5.0
deadline = float(sys.argv[9]) if len(sys.argv) > 9 else 0
cancel_file = sys.argv[10] if len(sys.argv) > 10 else ''
spec = importlib.util.spec_from_file_location('grant_child', src)
o = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = o
spec.loader.exec_module(o)
entry = json.loads(pathlib.Path(entry_path).read_text())
folder = pathlib.Path(run)
ready_path = pathlib.Path(ready) if ready else None
original = o._save_grant_ledger

def slow_save(target, ledger):
    if ready_path is not None:
        ready_path.write_text('locked')
    if mode == 'crash-before-save':
        os.kill(os.getpid(), signal.SIGKILL)
    time.sleep(float(hold))
    original(target, ledger)
    if mode == 'crash-after-save':
        os.kill(os.getpid(), signal.SIGKILL)

o._save_grant_ledger = slow_save
cfg = {'limits': {'max_grant_lock_wait_seconds': wait}}
cancel = (lambda: pathlib.Path(cancel_file).exists()) if cancel_file else None
limit = time.monotonic() + deadline if deadline else None
start = time.monotonic()
try:
    used, grant = o._reserve_in_ledger(
        folder, entry, rid, 'explorer', 'route', cfg=cfg, deadline=limit,
        cancel=cancel)
    print(json.dumps({'ok': True, 'used': used,
                      'seconds': time.monotonic() - start}))
except Exception as exc:
    print(json.dumps({'ok': False, 'error': type(exc).__name__ + ': ' + str(exc),
                      'seconds': time.monotonic() - start}))
'''


HOLDER = r'''
import importlib.util, pathlib, sys, time
spec = importlib.util.spec_from_file_location('grant_holder', sys.argv[1])
o = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = o
spec.loader.exec_module(o)
cfg = {'limits': {'max_grant_lock_wait_seconds': 5.0}}
with o.grant_ledger_lock(pathlib.Path(sys.argv[2]), cfg=cfg):
    pathlib.Path(sys.argv[3]).write_text('held')
    time.sleep(30)
'''


class GrantContentionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="aor31-grant-")
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.entry_path = self.folder / "entry.json"
        self.entry = {"id": "grant", "role": "explorer",
                      "route_sha256": "route", "max_dispatches": 2,
                      "used": 0, "run_id": "aor31-test"}
        self.entry_path.write_text(json.dumps(self.entry))
        orc.register_route_grant(self.folder, self.entry)

    def spawn(self, ready="", hold=0.0, rid="intent", mode="normal",
              wait=5.0, deadline=0.0, cancel_file=""):
        return subprocess.Popen(
            [sys.executable, "-c", CHILD, str(ORCHESTRATOR), str(self.folder),
             str(self.entry_path), ready, str(hold), rid, mode, str(wait),
             str(deadline), cancel_file],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def wait_for(self, path, timeout=10.0):
        until = time.monotonic() + timeout
        while not Path(path).exists():
            if time.monotonic() >= until:
                self.fail(f"timed out waiting for {path}")
            time.sleep(0.005)

    @staticmethod
    def output(proc, timeout=20):
        out, err = proc.communicate(timeout=timeout)
        try:
            return json.loads(out)
        except ValueError:
            raise AssertionError(f"no JSON output: {out!r} stderr={err!r}")

    def test_genuine_overlap_with_capacity_succeeds_within_the_bound(self):
        ready = self.folder / "ready-one"
        first = self.spawn(ready=str(ready), hold=0.5, rid="intent-one")
        self.wait_for(ready)
        second = self.spawn(rid="intent-two")
        one = self.output(first)
        two = self.output(second)
        self.assertTrue(one["ok"], one)
        self.assertTrue(two["ok"], two)
        ledger = orc.load_grant_ledger(self.folder)
        self.assertEqual(orc._grant_usage(ledger["grants"]["grant"]), 2)

    def test_contenders_cannot_exceed_capacity(self):
        self.entry["max_dispatches"] = 1
        self.entry_path.write_text(json.dumps(self.entry))
        ledger = orc.load_grant_ledger(self.folder)
        ledger["grants"]["grant"]["max_dispatches"] = 1
        orc._save_grant_ledger(self.folder, ledger)
        ready = self.folder / "ready-one"
        first = self.spawn(ready=str(ready), hold=0.5, rid="intent-one")
        self.wait_for(ready)
        second = self.spawn(rid="intent-two")
        one = self.output(first)
        two = self.output(second)
        self.assertTrue(one["ok"], one)
        self.assertFalse(two["ok"], two)
        self.assertIn("exhausted", two["error"])
        ledger = orc.load_grant_ledger(self.folder)
        self.assertEqual(orc._grant_usage(ledger["grants"]["grant"]), 1)

    def test_holder_release_lets_a_waiter_proceed(self):
        ready = self.folder / "ready-one"
        holder = self.spawn(ready=str(ready), hold=0.4, rid="intent-one")
        self.wait_for(ready)
        waiter = self.spawn(rid="intent-two")
        self.assertTrue(self.output(holder)["ok"])
        self.assertTrue(self.output(waiter)["ok"])
        ledger = orc.load_grant_ledger(self.folder)
        self.assertEqual(orc._grant_usage(ledger["grants"]["grant"]), 2)

    def test_bounded_wait_timeout_is_not_supervisor_ownership(self):
        ready = self.folder / "ready-one"
        first = self.spawn(ready=str(ready), hold=1.5, rid="intent-one")
        self.wait_for(ready)
        second = self.spawn(rid="intent-two", wait=0.25)
        two = self.output(second)
        self.assertFalse(two["ok"], two)
        self.assertIn("GrantLedgerTimeout", two["error"])
        self.assertIn("ledger", two["error"])
        self.assertNotIn("Another supervisor", two["error"])
        self.assertTrue(self.output(first)["ok"])

    def test_cancel_while_waiting_fails_fast_without_consuming(self):
        ready = self.folder / "ready-one"
        cancel = self.folder / "cancel"
        first = self.spawn(ready=str(ready), hold=1.5, rid="intent-one")
        self.wait_for(ready)
        second = self.spawn(rid="intent-two", cancel_file=str(cancel))
        time.sleep(0.15)
        cancel.write_text("cancel")
        two = self.output(second)
        self.assertFalse(two["ok"], two)
        self.assertIn("GrantWaitCancelled", two["error"])
        self.assertTrue(self.output(first)["ok"])
        ledger = orc.load_grant_ledger(self.folder)
        self.assertEqual(orc._grant_usage(ledger["grants"]["grant"]), 1)

    def test_deadline_while_waiting_is_reported_separately(self):
        ready = self.folder / "ready-one"
        first = self.spawn(ready=str(ready), hold=1.5, rid="intent-one")
        self.wait_for(ready)
        second = self.spawn(rid="intent-two", deadline=0.25)
        two = self.output(second)
        self.assertFalse(two["ok"], two)
        self.assertIn("GrantDeadlineExpired", two["error"])
        self.assertIn("deadline", two["error"])
        self.assertTrue(self.output(first)["ok"])

    def test_holder_crash_releases_the_kernel_lock(self):
        ready = self.folder / "held"
        holder = subprocess.Popen(
            [sys.executable, "-c", HOLDER, str(ORCHESTRATOR), str(self.folder),
             str(ready)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True)
        self.wait_for(ready)
        holder.send_signal(signal.SIGKILL)
        holder.communicate(timeout=10)
        child = self.spawn(rid="intent-after-crash", wait=1.0)
        result = self.output(child)
        self.assertTrue(result["ok"], result)
        self.assertLess(result["seconds"], 1.0)

    def test_crash_before_durable_reservation_consumes_nothing(self):
        ready = self.folder / "ready-one"
        child = self.spawn(ready=str(ready), rid="intent-before",
                           mode="crash-before-save")
        self.wait_for(ready)
        child.communicate(timeout=10)
        ledger = orc.load_grant_ledger(self.folder)
        self.assertEqual(orc._grant_usage(ledger["grants"]["grant"]), 0)
        retry = self.spawn(rid="intent-before")
        self.assertTrue(self.output(retry)["ok"])
        ledger = orc.load_grant_ledger(self.folder)
        self.assertEqual(orc._grant_usage(ledger["grants"]["grant"]), 1)

    def test_crash_after_durable_reservation_is_conservative_and_idempotent(self):
        ready = self.folder / "ready-one"
        child = self.spawn(ready=str(ready), rid="intent-after",
                           mode="crash-after-save")
        self.wait_for(ready)
        child.communicate(timeout=10)
        ledger = orc.load_grant_ledger(self.folder)
        self.assertEqual(orc._grant_usage(ledger["grants"]["grant"]), 1)
        # Retrying the same reservation id must not consume again.
        retry = self.spawn(rid="intent-after")
        result = self.output(retry)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["used"], 1)
        ledger = orc.load_grant_ledger(self.folder)
        self.assertEqual(len(ledger["grants"]["grant"]["reservations"]), 1)

    def test_same_id_replay_across_processes_consumes_once(self):
        first = self.spawn(rid="same-intent")
        second = self.spawn(rid="same-intent")
        self.assertTrue(self.output(first)["ok"])
        self.assertTrue(self.output(second)["ok"])
        ledger = orc.load_grant_ledger(self.folder)
        self.assertEqual(len(ledger["grants"]["grant"]["reservations"]), 1)

    def test_supervisor_ownership_remains_nonblocking_and_independent(self):
        holder = self.folder / "supervisor-held"
        proc = subprocess.Popen(
            [sys.executable, "-c",
             "import importlib.util,pathlib,sys,time\n"
             "s=importlib.util.spec_from_file_location('h',sys.argv[1])\n"
             "o=importlib.util.module_from_spec(s);sys.modules[s.name]=o;s.loader.exec_module(o)\n"
             "with o.exclusive(pathlib.Path(sys.argv[2])):\n"
             "    pathlib.Path(sys.argv[3]).write_text('held')\n"
             "    time.sleep(30)\n",
             str(ORCHESTRATOR), str(self.folder), str(holder)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.wait_for(holder)
        try:
            with self.assertRaisesRegex(RuntimeError, "Another supervisor"):
                with orc.exclusive(self.folder):
                    pass
            # The dedicated ledger lock is independent of supervisor ownership.
            child = self.spawn(rid="intent-despite-supervisor", wait=1.0)
            result = self.output(child)
            self.assertTrue(result["ok"], result)
            self.assertLess(result["seconds"], 1.0)
        finally:
            proc.send_signal(signal.SIGKILL)
            proc.communicate(timeout=10)

    def test_stale_parent_save_cannot_reset_durable_usage(self):
        stale = {"id": "aor31-test", "route_authorizations": [
            {"id": "grant", "role": "explorer", "route_sha256": "route",
             "max_dispatches": 2, "used": 0}]}
        child = self.spawn(rid="intent-one")
        self.assertTrue(self.output(child)["ok"])
        orc._sync_grant_usage(stale, self.folder)
        self.assertEqual(stale["route_authorizations"][0]["used"], 1)


FAKE_OPENCODE = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
if '--version' in args:
    print('1.18.35')
    sys.exit(0)
if pathlib.Path(sys.argv[0]).name != 'opencode':
    sys.exit(4)
if '--help' in args:
    print('--agent --model --format --auto --session --variant')
    sys.exit(0)
history = pathlib.Path(os.environ.get('FAKE_OC_HISTORY', '/dev/null'))
if os.environ.get('FAKE_OC_HISTORY'):
    with history.open('a') as stream:
        stream.write('run\n')
role = args[args.index('--agent') + 1].replace('abdullah-', '')
report = {'contract_version': 2, 'status': 'complete', 'summary': role,
          'files': [], 'tests': [], 'evidence': ['app.py:1'],
          'unknowns': [], 'blocker': ''}
print(json.dumps({'type': 'text', 'sessionID': 'ses-contention',
                  'part': {'text': json.dumps(report)}}))
print(json.dumps({'type': 'step_finish', 'sessionID': 'ses-contention',
                  'part': {'reason': 'stop'}}))
'''


class CallModelGrantWaitTests(unittest.TestCase):
    """call_model passes its deadline/cancel context into the ledger wait."""

    setUp = baseline.ControlTests.setUp
    tearDown = baseline.ControlTests.tearDown

    tearDown = baseline.ControlTests.tearDown

    def setUp(self):
        baseline.ControlTests.setUp(self)
        bin_dir = self.root / "contention-bin"
        bin_dir.mkdir()
        fake = bin_dir / "opencode"
        fake.write_text(FAKE_OPENCODE)
        fake.chmod(0o755)
        self.history = self.root / "history"
        env_patch = patch.dict(os.environ, {
            "PATH": str(bin_dir) + ":" + os.environ["PATH"],
            "HOME": str(self.root / "contention-home"),
            "FAKE_OC_HISTORY": str(self.history),
            "OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": ""})
        env_patch.start()
        self.addCleanup(env_patch.stop)
        cfg = orc.read_json(orc.CONFIG_PATH)
        cfg["limits"]["max_grant_lock_wait_seconds"] = 0.25
        cfg["workers"]["explorer"] = {
            "provider": "opencode-zen", "model": "opencode-zen/explorer-model",
            "variant": "low", "billing": "api"}
        orc.atomic_json(orc.CONFIG_PATH, cfg)
        self.cfg = orc.config()
        # A rewritten config invalidates the previously adopted policy view;
        # save() re-adopts the exact bytes this fixture just wrote.
        self.state.pop("config_policy", None)
        self.state["config_sha256"] = orc.configuration_provenance().get("sha256")
        route = orc.model_route(self.cfg, "codex", "explorer",
                                project=self.project)
        self.state["model_routes"] = {"explorer": route}
        self.state["route_authorizations"] = [{
            "id": "grant-wait", "role": "explorer",
            "route_sha256": orc.route_authorization_sha(route),
            "max_dispatches": 1, "used": 0,
            "attestation": "reviewed api endpoint"}]
        orc.save(self.rundir, self.state)
        orc.register_route_grant(self.rundir,
                                 self.state["route_authorizations"][0],
                                 cfg=self.cfg)
        self.route = route

    def start_holder(self):
        ready = self.root / "held"
        holder = subprocess.Popen(
            [sys.executable, "-c", HOLDER, str(ORCHESTRATOR), str(self.rundir),
             str(ready)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True)
        self.addCleanup(lambda: (holder.poll() is None and holder.kill(),
                                 holder.communicate(timeout=5)))
        until = time.monotonic() + 10
        while not ready.exists():
            if time.monotonic() >= until:
                self.fail("holder did not acquire the ledger lock")
            time.sleep(0.005)
        return holder

    def test_invalid_grant_wait_limit_is_rejected(self):
        raw = orc.read_json(orc.CONFIG_PATH)
        for value in (0, -1, 0.0, None, "nan", "inf", "not-a-number"):
            with self.subTest(value=value):
                raw["limits"]["max_grant_lock_wait_seconds"] = value
                orc.atomic_json(orc.CONFIG_PATH, raw)
                with self.assertRaises(ValueError):
                    orc.config()

    def test_bounded_wait_is_reported_in_durable_diagnostics(self):
        holder = self.start_holder()
        try:
            with self.assertRaisesRegex(RuntimeError, "contention|ledger"):
                orc.call_model(self.rundir, self.state, self.cfg, "explorer",
                               "explorer", "prompt", self.project)
        finally:
            holder.kill()
            holder.communicate(timeout=5)
        state = orc.read_json(self.rundir / "state.json")
        self.assertIsNone(state["active_job"])
        self.assertEqual(state["status"], "blocked")
        rejection = state["preflight_rejection"]
        self.assertEqual(rejection["reason_code"], "grant_ledger_timeout")
        self.assertTrue(rejection["active_job_created"] is False)
        self.assertFalse(self.history.exists())
        ledger = orc.load_grant_ledger(self.rundir)
        self.assertEqual(orc._grant_usage(ledger["grants"]["grant-wait"]), 0)

    def test_deadline_after_reservation_releases_the_unlaunched_intent(self):
        with patch.object(orc, "remaining_budget",
                          side_effect=TimeoutError("Whole-stage deadline exceeded")):
            with self.assertRaises(TimeoutError):
                orc.call_model(self.rundir, self.state, self.cfg, "explorer",
                               "explorer", "prompt", self.project)
        state = orc.read_json(self.rundir / "state.json")
        self.assertIsNone(state["active_job"])
        self.assertFalse(self.history.exists())
        ledger = orc.load_grant_ledger(self.rundir)
        self.assertEqual(orc._grant_usage(ledger["grants"]["grant-wait"]), 0)

    def test_stage_deadline_while_waiting_is_not_authorization_exhaustion(self):
        holder = self.start_holder()
        # Owned version/config inspection is whole-stage work too; leave it
        # enough budget to complete and let the deadline expire in the wait.
        self.cfg["limits"]["max_grant_lock_wait_seconds"] = 5.0
        try:
            with self.assertRaisesRegex(RuntimeError, "deadline|ledger"):
                orc.call_model(self.rundir, self.state, self.cfg, "explorer",
                               "explorer", "prompt", self.project,
                               deadline=time.monotonic() + 2.0)
        finally:
            holder.kill()
            holder.communicate(timeout=5)
        state = orc.read_json(self.rundir / "state.json")
        rejection = state["preflight_rejection"]
        self.assertEqual(rejection["reason_code"], "grant_deadline_expired")
        self.assertNotIn("exhausted", " ".join(rejection["reasons"]))
        self.assertFalse(self.history.exists())


if __name__ == "__main__":
    unittest.main()
