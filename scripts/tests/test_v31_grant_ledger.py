"""v3.1 durable route grants across process boundaries and fallback consent."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_orchestrator as baseline
from test_v31_worker_routes import FAKE_OPENCODE
orc = baseline.orc

ORCHESTRATOR = Path(__file__).resolve().parents[1] / "orchestrator.py"


class FakeTTY:
    def isatty(self):
        return True


class GrantLedgerTests(unittest.TestCase):
    setUp = baseline.ControlTests.setUp
    tearDown = baseline.ControlTests.tearDown

    def setUp(self):
        baseline.ControlTests.setUp(self)
        self.bin_dir = self.root / "ledger-bin"
        self.bin_dir.mkdir()
        fake = self.bin_dir / "opencode"
        fake.write_text(FAKE_OPENCODE)
        fake.chmod(0o755)
        self.home = self.root / "ledger-home"
        self.home.mkdir()
        self.history = self.root / "history"
        self.env_patch = patch.dict(os.environ, {
            "PATH": str(self.bin_dir) + ":" + os.environ["PATH"],
            "HOME": str(self.home), "OPENAI_API_KEY": "",
            "ANTHROPIC_API_KEY": "", "FAKE_HISTORY": str(self.history),
            "ABDULLAH_STATE_DIR": str(self.root / "runs"),
            "ABDULLAH_CONFIG": str(self.root / "config.json")})
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.addCleanup(lambda: os.environ.pop("FAKE_EXIT", None))

    def write_config(self, explorer):
        cfg = orc.read_json(orc.HERE / "config.example.json")
        cfg["workers"]["explorer"] = explorer
        orc.atomic_json(orc.CONFIG_PATH, cfg)
        self.cfg = orc.config()
        self.state["config_sha256"] = orc.configuration_provenance().get("sha256")
        orc.save(self.rundir, self.state)
        return cfg

    def api_explorer(self, fallback=None):
        spec = {"provider": "opencode-zen",
                "model": "opencode-zen/explorer-model",
                "variant": "low", "billing": "api"}
        if fallback:
            spec["fallback"] = fallback
        return spec

    def grant(self, route, count=1, attestation="reviewed api endpoint"):
        entry = {"id": "grant-explorer", "role": "explorer",
                 "route_sha256": orc.route_authorization_sha(route),
                 "max_dispatches": count, "used": 0,
                 "attestation": attestation, "actor": {"user": "tester"},
                 "at": orc.now(), "run_id": "test-run00"}
        response = orc.register_route_grant(self.rundir, entry)
        self.state.setdefault("route_authorizations", []).append(entry)
        orc.save(self.rundir, self.state)
        return response

    def explore_env(self):
        return {**os.environ,
                "PATH": str(self.bin_dir) + ":" + os.environ["PATH"],
                "HOME": str(self.home), "FAKE_HISTORY": str(self.history),
                "ABDULLAH_STATE_DIR": str(self.root / "runs"),
                "ABDULLAH_CONFIG": str(self.root / "config.json"),
                "ABDULLAH_RUN_ID": "test-run00",
                "ABDULLAH_PARENT_JOB": "parent-job"}

    def child_explore(self):
        return subprocess.run(
            [sys.executable, str(ORCHESTRATOR), "explore", "test-run00",
             "--task", "inspect app", "--parent-job", "parent-job"],
            capture_output=True, text=True, timeout=120, check=False,
            env=self.explore_env())

    def prepare_nested_parent(self):
        self.write_config(self.api_explorer())
        route = orc.model_route(self.cfg, "codex", "explorer",
                                project=self.project)
        self.state.update(explorer_policy="on_demand", status="running",
                          phase="plan", model_routes={"explorer": route},
                          active_job={"id": "parent-job", "role": "architect",
                                      "status": "running"})
        orc.save(self.rundir, self.state)
        self.grant(route)
        stale_parent = orc.read_json(self.rundir / "state.json")
        return route, stale_parent

    def test_separate_process_nested_explorer_consumption_survives_parent_save(self):
        route, stale_parent = self.prepare_nested_parent()
        result = self.child_explore()
        self.assertEqual(result.returncode, 0, result.stderr)
        state = orc.read_json(self.rundir / "state.json")
        self.assertEqual(state["route_authorizations"][0]["used"], 1)
        ledger = orc.load_grant_ledger(self.rundir, run_id="test-run00")
        self.assertEqual(len(ledger["grants"]["grant-explorer"]["reservations"]), 1)
        # A parent completion/failure saves its older in-memory snapshot.
        orc.save(self.rundir, stale_parent)
        state = orc.read_json(self.rundir / "state.json")
        self.assertEqual(state["route_authorizations"][0]["used"], 1)
        self.assertEqual(state["active_job"]["id"], "parent-job")
        # The next nested request is refused before spawning.
        again = self.child_explore()
        self.assertNotEqual(again.returncode, 0)
        self.assertIn("preflight", again.stderr)
        self.assertEqual(self.history.read_text().splitlines(), ["explorer"])

    def test_legacy_state_consumption_is_not_reset_by_first_ledger_write(self):
        route = {"provider": "opencode", "worker_provider": "opencode-zen",
                 "model": "opencode-zen/explorer-model", "effort": "low",
                 "billing": "api"}
        entry = {"id": "legacy-grant", "role": "explorer",
                 "route_sha256": orc.route_authorization_sha(route),
                 "max_dispatches": 2, "used": 1, "attestation": "reviewed",
                 "run_id": "test-run00"}
        self.state["route_authorizations"] = [entry]
        orc.save(self.rundir, self.state)
        status = orc.route_authorization_status(
            self.state, "explorer", route, run_dir=self.rundir)
        self.assertTrue(status["authorized"])
        reserved = orc.reserve_route_grant(
            self.state, self.rundir, "explorer", route,
            reservation_id="new-intent")
        self.assertEqual(reserved["used"], 2)
        state = orc.read_json(self.rundir / "state.json")
        self.assertEqual(state["route_authorizations"][0]["used"], 2)
        with self.assertRaisesRegex(RuntimeError, "exhausted"):
            orc.reserve_route_grant(self.state, self.rundir, "explorer", route,
                                    reservation_id="third-intent")

    def test_reservation_replay_is_idempotent(self):
        route, _ = self.prepare_nested_parent()
        state = orc.read_json(self.rundir / "state.json")
        state["route_authorizations"][0]["used"] = 0
        first = orc.reserve_route_grant(
            state, self.rundir, "explorer", route, reservation_id="intent-1")
        second = orc.reserve_route_grant(
            state, self.rundir, "explorer", route, reservation_id="intent-1")
        self.assertEqual(first["used"], 1)
        self.assertEqual(second["used"], 1)
        ledger = orc.load_grant_ledger(self.rundir, run_id="test-run00")
        self.assertEqual(len(ledger["grants"]["grant-explorer"]["reservations"]), 1)

    def test_concurrent_process_reservations_cannot_exceed_the_bound(self):
        route, _ = self.prepare_nested_parent()
        snippet = (
            "import json, pathlib, sys; sys.path.insert(0, %r); "
            "import orchestrator as o; state=o.read_json(pathlib.Path(%r)); "
            "route=json.loads(%r); "
            "print(o.reserve_route_grant(state, pathlib.Path(%r), 'explorer', route, "
            "reservation_id=sys.argv[1])['used'])"
            % (str(Path(__file__).resolve().parents[1]),
               str(self.rundir / "state.json"), json.dumps(route),
               str(self.rundir)))
        processes = [subprocess.Popen(
            [sys.executable, "-c", snippet, "intent-" + str(index)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env=self.explore_env()) for index in range(2)]
        outputs = []
        for proc in processes:
            out, err = proc.communicate(timeout=60)
            outputs.append((proc.returncode, out, err))
        successes = [out for code, out, _ in outputs if code == 0]
        self.assertEqual(len(successes), 1, outputs)
        ledger = orc.load_grant_ledger(self.rundir, run_id="test-run00")
        self.assertEqual(len(ledger["grants"]["grant-explorer"]["reservations"]), 1)

    def test_public_authorize_route_fallback_then_dispatch_once(self):
        fallback = {"provider": "opencode-zen",
                    "model": "opencode-zen/explorer-fallback",
                    "variant": "low", "billing": "api"}
        self.write_config(self.api_explorer(fallback))
        route = orc.model_route(self.cfg, "codex", "explorer",
                                project=self.project)
        self.state.update(model_routes={"explorer": route})
        orc.save(self.rundir, self.state)
        tty = FakeTTY()
        with patch.object(orc.sys, "stdin", tty):
            granted = orc.authorize_route_run(
                "test-run00", "explorer", max_dispatches=1,
                confirmation="authorize-route:test-run00", fallback=True)
            consent = orc.approve_worker_fallback_run(
                "test-run00", "explorer",
                confirmation="approve-worker-fallback:test-run00")
        self.assertEqual(granted["selected_route"], "fallback")
        self.assertEqual(granted["grant"]["route_sha256"],
                         orc.route_authorization_sha(route["fallback_route"]))
        self.assertEqual(consent["worker_fallback_authorization"]["role"], "explorer")
        self.state = orc.read_json(self.rundir / "state.json")
        report, job = orc.call_model(
            self.rundir, self.state, self.cfg, "explorer", "explorer",
            "prompt", self.project)
        self.assertEqual(job["route"]["model"], "opencode-zen/explorer-fallback")
        self.assertEqual(self.history.read_text().splitlines(), ["explorer"])
        state = orc.read_json(self.rundir / "state.json")
        self.assertIsNone(state["worker_fallback_authorization"])
        self.assertEqual(state["route_authorizations"][-1]["used"], 1)

    def test_missing_alternate_grant_keeps_one_dispatch_consent(self):
        fallback = {"provider": "opencode-zen",
                    "model": "opencode-zen/explorer-fallback",
                    "variant": "low", "billing": "api"}
        self.write_config(self.api_explorer(fallback))
        route = orc.model_route(self.cfg, "codex", "explorer",
                                project=self.project)
        self.state.update(model_routes={"explorer": route})
        orc.save(self.rundir, self.state)
        with patch.object(orc.sys, "stdin", FakeTTY()):
            orc.approve_worker_fallback_run(
                "test-run00", "explorer",
                confirmation="approve-worker-fallback:test-run00")
        self.state = orc.read_json(self.rundir / "state.json")
        with self.assertRaisesRegex(RuntimeError, "preflight"):
            orc.call_model(self.rundir, self.state, self.cfg, "explorer",
                           "explorer", "prompt", self.project)
        state = orc.read_json(self.rundir / "state.json")
        self.assertIsNotNone(state["worker_fallback_authorization"])
        self.assertFalse(self.history.exists())

    def test_failed_fallback_consumes_consent_and_grant(self):
        fallback = {"provider": "opencode-zen",
                    "model": "opencode-zen/explorer-fallback",
                    "variant": "low", "billing": "api"}
        self.write_config({"provider": "opencode-go",
                           "model": "opencode-go/deepseek-v4.1-flash",
                           "variant": "low", "billing": "go",
                           "fallback": fallback})
        route = orc.model_route(self.cfg, "codex", "explorer",
                                project=self.project)
        self.state.update(model_routes={"explorer": route})
        self.grant(route["fallback_route"])
        orc.save(self.rundir, self.state)
        with patch.object(orc.sys, "stdin", FakeTTY()):
            orc.approve_worker_fallback_run(
                "test-run00", "explorer",
                confirmation="approve-worker-fallback:test-run00")
        self.state = orc.read_json(self.rundir / "state.json")
        os.environ["FAKE_EXIT"] = "1"
        with self.assertRaises(RuntimeError):
            orc.call_model(self.rundir, self.state, self.cfg, "explorer",
                           "explorer", "prompt", self.project)
        state = orc.read_json(self.rundir / "state.json")
        self.assertIsNone(state["worker_fallback_authorization"])
        self.assertEqual(state["route_authorizations"][-1]["used"], 1)
        os.environ.pop("FAKE_EXIT")
        report, job = orc.call_model(self.rundir, state, self.cfg, "explorer",
                                     "explorer", "prompt", self.project)
        self.assertEqual(job["route"]["billing"], "go")

    def test_changed_alternate_and_exhausted_grant_never_silently_fall_back(self):
        fallback = {"provider": "opencode-zen",
                    "model": "opencode-zen/explorer-fallback",
                    "variant": "low", "billing": "api"}
        self.write_config(self.api_explorer(fallback))
        route = orc.model_route(self.cfg, "codex", "explorer",
                                project=self.project)
        self.state.update(model_routes={"explorer": route})
        self.grant(route["fallback_route"])
        orc.save(self.rundir, self.state)
        with patch.object(orc.sys, "stdin", FakeTTY()):
            orc.approve_worker_fallback_run(
                "test-run00", "explorer",
                confirmation="approve-worker-fallback:test-run00")
        self.state = orc.read_json(self.rundir / "state.json")
        self.state["worker_fallback_authorization"]["route_sha256"] = "changed"
        with self.assertRaisesRegex(RuntimeError, "does not match"):
            orc.call_model(self.rundir, self.state, self.cfg, "explorer",
                           "explorer", "prompt", self.project)
        # Restore exact consent, consume the only grant, then a second consent
        # must be refused before spawn.
        self.state["worker_fallback_authorization"] = {
            "role": "explorer",
            "route_sha256": orc.route_authorization_sha(route["fallback_route"]),
            "limit": "one dispatch"}
        orc.call_model(self.rundir, self.state, self.cfg, "explorer",
                       "explorer", "prompt", self.project)
        self.state["worker_fallback_authorization"] = {
            "role": "explorer",
            "route_sha256": orc.route_authorization_sha(route["fallback_route"]),
            "limit": "one dispatch"}
        with self.assertRaisesRegex(RuntimeError, "preflight"):
            orc.call_model(self.rundir, self.state, self.cfg, "explorer",
                           "explorer", "prompt", self.project)
        self.assertEqual(self.history.read_text().splitlines(), ["explorer"])


if __name__ == "__main__":
    unittest.main()
