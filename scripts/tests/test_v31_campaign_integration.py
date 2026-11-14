"""v3.1 cross-boundary integration: full fake Claude and Codex stage paths."""
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


FAKE_CLI = r'''#!/usr/bin/env python3
import json, os, pathlib, sys, time
args = sys.argv[1:]
name = pathlib.Path(sys.argv[0]).name
if '--version' in args:
    print('1.18.35')
    sys.exit(0)
history = pathlib.Path(os.environ['FAKE_HISTORY'])

def plan_report(batches):
    return {'contract_version': 2, 'status': 'complete', 'summary': 'plan',
            'invariants': ['Keep behavior'], 'blocker': '',
            'batches': [{'title': f'batch {i + 1}', 'goal': 'change app',
                         'acceptance': ['works'],
                         'checks': [[sys.executable, '-c', 'pass']],
                         'risk': 'ordinary'} for i in range(batches)]}

if name == 'codex':
    output = pathlib.Path(args[args.index('--output-last-message') + 1])
    kind = output.parent.name.split('-')[0]
    with history.open('a') as stream:
        stream.write(kind + '\n')
    if kind == 'plan':
        report = plan_report(int(os.environ.get('FAKE_BATCHES', '1')))
    elif kind == 'decision':
        report = {'contract_version': 2, 'verdict': 'approved', 'reason': 'inspected',
                  'inspected': ['app.py'], 'correction': '', 'dismissed_findings': []}
    elif kind == 'integration':
        report = {'contract_version': 2, 'verdict': 'approved', 'reason': 'inspected',
                  'inspected': ['app.py'], 'correction': '', 'dismissed_findings': []}
    else:
        report = {'contract_version': 2, 'verdict': 'changes_required',
                  'reason': 'diagnosed', 'inspected': ['app.py'],
                  'correction': 'do the work', 'dismissed_findings': []}
    output.write_text(json.dumps(report))
    sys.exit(0)
if name == 'claude':
    prompt = args[-1]
    if 'Create a complete' in prompt:
        kind, report = 'plan', plan_report(int(os.environ.get('FAKE_BATCHES', '1')))
    elif 'Inspect end-to-end' in prompt:
        kind, report = 'integration', {'contract_version': 2, 'verdict': 'approved',
                                       'reason': 'inspected', 'inspected': ['app.py'],
                                       'correction': '', 'dismissed_findings': []}
    else:
        kind, report = 'decision', {'contract_version': 2, 'verdict': 'approved',
                                    'reason': 'inspected', 'inspected': ['app.py'],
                                    'correction': '', 'dismissed_findings': []}
    with history.open('a') as stream:
        stream.write(kind + '\n')
    print(json.dumps({'structured_output': report, 'session_id': 'ses-claude'}))
    sys.exit(0)
role = args[args.index('--agent') + 1].replace('abdullah-', '')
with history.open('a') as stream:
    stream.write(role + '\n')
if role == 'implementer':
    path = pathlib.Path('app.py')
    path.write_text(path.read_text() + '# implemented by ' + role + '\n')
    if os.environ.get('FAKE_SLEEP'):
        time.sleep(30)
if role == 'reviewer':
    report = {'contract_version': 2, 'status': 'complete', 'summary': 'reviewed',
              'findings': [], 'evidence': ['app.py:1'], 'files': ['app.py'],
              'tests': ['focused'], 'unknowns': [], 'blocker': ''}
else:
    report = {'contract_version': 2, 'status': 'complete', 'summary': role,
              'files': ['app.py'], 'tests': [], 'evidence': ['app.py:1'],
              'unknowns': [], 'blocker': ''}
print(json.dumps({'type': 'text', 'sessionID': 'ses-' + role,
                  'part': {'text': json.dumps(report)}}))
print(json.dumps({'type': 'step_finish', 'sessionID': 'ses-' + role,
                  'part': {'reason': 'stop'}}))
'''


class FakeTTY:
    def isatty(self):
        return True


class CampaignIntegrationTests(unittest.TestCase):
    setUp = baseline.ControlTests.setUp
    tearDown = baseline.ControlTests.tearDown

    def setUp(self):
        baseline.ControlTests.setUp(self)
        self.bin_dir = self.root / "integration-bin"
        self.bin_dir.mkdir()
        fake = self.bin_dir / "fake.py"
        fake.write_text(FAKE_CLI)
        fake.chmod(0o755)
        for name in ("codex", "claude", "opencode"):
            (self.bin_dir / name).symlink_to(fake)
        self.history = self.root / "history"
        self.home = self.root / "home"
        (self.home / ".claude").mkdir(parents=True)
        self.env_patch = patch.dict(os.environ, {
            "PATH": str(self.bin_dir) + ":" + os.environ["PATH"],
            "FAKE_HISTORY": str(self.history), "HOME": str(self.home),
            "OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": ""})
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.addCleanup(lambda: os.environ.pop("FAKE_BATCHES", None))
        self.addCleanup(lambda: os.environ.pop("PYTHONPATH", None))
        self.runs = self.root / "integration-runs"
        self.state_patch = patch.object(orc, "DEFAULT_STATE", self.runs)
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)

    def start(self, host):
        started = orc.start_run(project=str(self.project), goal="integrate feature",
                                host=host, skip_doctor=True, interactive=True)
        return started["run_id"]

    def drive(self, run_id, limit=20):
        seen = []
        for _ in range(limit):
            result = orc.stage_run(run_id)
            seen.append((result["stage"], result["status"]))
            if result["status"] in {"complete", "cancelled"}:
                break
            if result["status"] != "running":
                self.fail(f"integration stopped: {result}")
        return seen

    def test_codex_hosted_multi_batch_path_reaches_integration(self):
        os.environ["FAKE_BATCHES"] = "2"
        run_id = self.start("codex")
        seen = self.drive(run_id)
        self.assertEqual(seen[-1][1], "complete")
        self.assertEqual([stage for stage, _ in seen], [
            "plan", "implement", "verify", "review", "accept",
            "implement", "verify", "review", "accept", "integrate"])
        state = orc.read_json(self.runs / run_id / "state.json")
        self.assertEqual(len(state["accepted_batches"]), 2)
        self.assertEqual(state["final_verdict"]["verdict"], "approved")
        self.assertEqual(self.history.read_text().splitlines().count("decision"), 2)
        self.assertEqual(self.history.read_text().splitlines().count("integration"), 1)
        self.assertEqual(state["host"], "codex")
        self.assertEqual(state["model_routes"]["architect"]["provider"], "codex")

    def test_claude_hosted_multi_batch_path_reaches_integration(self):
        os.environ["FAKE_BATCHES"] = "2"
        run_id = self.start("claude")
        seen = self.drive(run_id)
        self.assertEqual(seen[-1][1], "complete")
        state = orc.read_json(self.runs / run_id / "state.json")
        self.assertEqual(state["host"], "claude")
        self.assertEqual(state["model_routes"]["architect"]["provider"], "claude")
        self.assertEqual(self.history.read_text().splitlines().count("plan"), 1)
        self.assertEqual(self.history.read_text().splitlines().count("integration"), 1)

    def test_mixed_provider_fake_stage_path_uses_real_authorization_helpers(self):
        cfg = orc.read_json(orc.CONFIG_PATH)
        cfg["workers"] = {
            "explorer": {"provider": "opencode-go",
                         "model": "opencode-go/deepseek-v4.1-flash",
                         "variant": "low", "billing": "go"},
            "implementer": {"provider": "opencode-zen",
                            "model": "opencode-zen/worker-model",
                            "variant": "high", "billing": "api"},
            "reviewer": {"provider": "free-provider",
                         "model": "free-provider/free-model",
                         "variant": "", "billing": "free"},
        }
        cfg.setdefault("authorization", {})["sensitive_cli_enabled"] = True
        orc.atomic_json(orc.CONFIG_PATH, cfg)
        self.cfg = orc.config()
        run_id = self.start("codex")
        with patch.object(orc.sys, "stdin", FakeTTY()):
            implemented = orc.authorize_route_run(
                run_id, "implementer", max_dispatches=1,
                confirmation=f"authorize-route:{run_id}")
            reviewed = orc.authorize_route_run(
                run_id, "reviewer", max_dispatches=1,
                attestation="reviewed free provider endpoint/auth mode",
                confirmation=f"authorize-route:{run_id}")
        self.assertEqual(implemented["grant"]["role"], "implementer")
        self.assertEqual(reviewed["grant"]["attestation"],
                         "reviewed free provider endpoint/auth mode")
        seen = self.drive(run_id)
        self.assertEqual(seen[-1][1], "complete")
        history = self.history.read_text().splitlines()
        self.assertEqual(history.count("implementer"), 1)
        self.assertEqual(history.count("reviewer"), 1)
        state = orc.read_json(self.runs / run_id / "state.json")
        self.assertEqual(state["final_verdict"]["verdict"], "approved")
        used = {item["role"]: item["used"]
                for item in state["route_authorizations"]}
        self.assertEqual(used, {"implementer": 1, "reviewer": 1})
        ledger = orc.load_grant_ledger(self.runs / run_id, run_id=run_id)
        for grant_id, grant in ledger["grants"].items():
            self.assertEqual(len(grant["reservations"]), 1, grant_id)

    def test_late_drift_forces_fresh_checks_then_completes(self):
        run_id = self.start("codex")
        # plan, implement, verify, review
        for _ in range(4):
            result = orc.stage_run(run_id)
            self.assertEqual(result["status"], "running", result)
        first_evidence = orc.read_json(self.runs / run_id / "state.json")["verification"]
        os.environ["PYTHONPATH"] = "/v31/integration-drift"
        drifted = orc.stage_run(run_id)
        self.assertEqual(drifted["stage"], "accept")
        state = orc.read_json(self.runs / run_id / "state.json")
        self.assertEqual(state["phase"], "verify")
        self.assertIsNone(state["verification"])
        self.assertNotEqual(state["status"], "complete")
        os.environ.pop("PYTHONPATH")
        remaining = self.drive(run_id)
        self.assertEqual(remaining[-1][1], "complete")
        final = orc.read_json(self.runs / run_id / "state.json")
        self.assertNotEqual(final["verification"]["path"], first_evidence["path"])
        self.assertEqual(final["final_verdict"]["verdict"], "approved")

    def test_clean_single_completion_after_recovery_has_one_decision(self):
        run_id = self.start("codex")
        seen = self.drive(run_id)
        self.assertEqual(seen[-1][1], "complete")
        state = orc.read_json(self.runs / run_id / "state.json")
        self.assertEqual(len(state["accepted_batches"]), 1)
        self.assertEqual(self.history.read_text().splitlines().count("decision"), 1)
        self.assertTrue(state["final_evidence"]["source_unchanged"])
        self.assertTrue(state["decision_binding"])


if __name__ == "__main__":
    unittest.main()
