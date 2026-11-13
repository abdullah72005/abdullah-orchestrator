"""v3.1: read-only stages must preserve candidate source.

These tests use a real temporary Git checkout and fake executable CLIs.  They
exercise the production dispatch boundary (``call_model``/``stage_run``), not
only a helper, and never launch a real model.
"""
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
import json, os, pathlib, subprocess, sys
args = sys.argv[1:]
name = pathlib.Path(sys.argv[0]).name
mode = os.environ.get('FAKE_MUTATION', 'none')
if '--version' in args:
    print('1.18.35')
    sys.exit(0)

def mutate():
    app = pathlib.Path('app.py')
    if mode in {'tracked', 'malformed', 'exit1'}:
        app.write_text(app.read_text() + '# mutated by read-only stage\n')
    elif mode == 'untracked':
        pathlib.Path('new_file.py').write_text('value = 9\n')
    elif mode == 'untracked_delete':
        pathlib.Path('tracked_new.py').unlink()
    elif mode == 'staged':
        app.write_text(app.read_text() + '# staged mutation\n')
        subprocess.run(['git', 'add', 'app.py'], check=True)
    elif mode == 'commit':
        app.write_text(app.read_text() + '# committed mutation\n')
        subprocess.run(['git', 'add', 'app.py'], check=True)
        subprocess.run(['git', 'commit', '-qm', 'worker commit'], check=True,
                       env={**os.environ, 'GIT_AUTHOR_NAME': 'Worker',
                            'GIT_AUTHOR_EMAIL': 'w@example.com',
                            'GIT_COMMITTER_NAME': 'Worker',
                            'GIT_COMMITTER_EMAIL': 'w@example.com'})

mutate()
if name == 'codex':
    output = pathlib.Path(args[args.index('--output-last-message') + 1])
    kind = output.parent.name.split('-')[0]
else:
    role = args[args.index('--agent') + 1].replace('abdullah-', '')
    kind = role
if kind == 'plan':
    report = {'contract_version': 2, 'status': 'complete', 'summary': 'plan',
              'invariants': ['Keep behavior'], 'blocker': '',
              'batches': [{'title': 'batch', 'goal': 'change', 'acceptance': ['done'],
                           'checks': [[sys.executable, '-c', 'pass']], 'risk': 'ordinary'}]}
elif kind in {'decision', 'diagnose', 'integration'}:
    report = {'contract_version': 2, 'verdict': 'approved', 'reason': 'inspected',
              'inspected': ['app.py'], 'correction': '', 'dismissed_findings': []}
elif kind == 'reviewer':
    report = {'contract_version': 2, 'status': 'complete', 'summary': 'reviewed',
              'findings': [], 'evidence': ['app.py:1'], 'files': ['app.py'],
              'tests': [], 'unknowns': [], 'blocker': ''}
else:
    report = {'contract_version': 2, 'status': 'complete', 'summary': 'read',
              'files': ['app.py'], 'tests': [], 'evidence': ['app.py:1'],
              'unknowns': [], 'blocker': ''}
malformed = mode == 'malformed'
if name == 'codex':
    output.write_text('not a json report' if malformed else json.dumps(report))
    if mode == 'exit1':
        sys.exit(3)
else:
    text = 'not a json report' if malformed else json.dumps(report)
    print(json.dumps({'type': 'text', 'sessionID': 'ses_fake',
                      'part': {'text': text}}))
    print(json.dumps({'type': 'step_finish', 'sessionID': 'ses_fake',
                      'part': {'reason': 'stop'}}))
    if mode == 'exit1':
        sys.exit(3)
'''


def install_fake_clis(root: Path):
    bin_dir = root / "v31-bin"
    bin_dir.mkdir()
    script = bin_dir / "fake_cli.py"
    script.write_text(FAKE_CLI)
    script.chmod(0o755)
    for name in ("codex", "claude", "opencode"):
        (bin_dir / name).symlink_to(script)
    return bin_dir


class StageInvariantTests(unittest.TestCase):
    setUp = baseline.ControlTests.setUp
    tearDown = baseline.ControlTests.tearDown

    def setUp(self):
        baseline.ControlTests.setUp(self)
        self.fakebin = install_fake_clis(self.root)
        self.env = {"PATH": str(self.fakebin) + ":" + os.environ["PATH"],
                    "OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": ""}
        env_patch = patch.dict(os.environ, self.env)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        os.environ.pop("FAKE_MUTATION", None)
        self.addCleanup(lambda: os.environ.pop("FAKE_MUTATION", None))

    def dispatch(self, kind="plan", role="architect", host="codex"):
        return orc.call_model(
            self.rundir, self.state, self.cfg, role, kind,
            "prompt", self.project, host=host)

    def test_plan_mutation_blocks_and_preserves_source_report_and_diagnostics(self):
        os.environ["FAKE_MUTATION"] = "tracked"
        with self.assertRaises(orc.SourceMutationError) as raised:
            self.dispatch("plan")
        job = self.state["failed_jobs"][-1]
        self.assertEqual(job["status"], "blocked")
        self.assertIsNone(self.state["active_job"])
        self.assertIn("# mutated by read-only stage", (self.project / "app.py").read_text())
        self.assertTrue((Path(job["path"]) / "report.json").is_file())
        self.assertTrue((Path(job["path"]) / "source-mutation.json").is_file())
        self.assertIn("paths", raised.exception.diagnostics)
        self.assertEqual(raised.exception.diagnostics["paths"][0]["path"], "app.py")
        self.assertFalse(self.state["completed_jobs"])

    def test_read_only_kinds_and_worker_roles_are_all_blocked(self):
        cases = [("diagnose", "architect", "codex"),
                 ("decision", "architect", "codex"),
                 ("integration", "architect", "codex"),
                 ("explorer", "explorer", "opencode"),
                 ("reviewer", "reviewer", "opencode")]
        for kind, role, host in cases:
            with self.subTest(kind=kind):
                (self.project / "app.py").write_text("value = 1\n")
                subprocess.run(["git", "add", "app.py"], cwd=self.project, check=True,
                               capture_output=True)
                subprocess.run(["git", "commit", "-qm", "reset", "--allow-empty"], cwd=self.project,
                               check=True, capture_output=True)
                self.state["completed_jobs"] = []
                self.state["failed_jobs"] = []
                self.state["active_job"] = None
                os.environ["FAKE_MUTATION"] = "untracked"
                with self.assertRaises(orc.SourceMutationError):
                    self.dispatch(kind, role, host)
                self.assertTrue((self.project / "new_file.py").is_file())
                (self.project / "new_file.py").unlink()

    def test_staged_and_committed_source_mutations_are_detected(self):
        for mode in ("staged", "commit", "untracked_delete", "tracked"):
            with self.subTest(mode=mode):
                (self.project / "app.py").write_text("value = 1\n")
                (self.project / "tracked_new.py").write_text("tracked = 1\n")
                subprocess.run(["git", "add", "app.py", "tracked_new.py"],
                               cwd=self.project, check=True, capture_output=True)
                subprocess.run(["git", "commit", "-qm", f"baseline {mode}", "--allow-empty"],
                               cwd=self.project, check=True, capture_output=True)
                self.state["completed_jobs"] = []
                self.state["failed_jobs"] = []
                self.state["active_job"] = None
                os.environ["FAKE_MUTATION"] = mode
                with self.assertRaises(orc.SourceMutationError):
                    self.dispatch("plan")
                self.assertEqual(self.state["failed_jobs"][-1]["status"], "blocked")

    def test_unchanged_pre_existing_dirty_tree_is_allowed(self):
        (self.project / "app.py").write_text("value = 2\n")
        os.environ["FAKE_MUTATION"] = "none"
        report, job = self.dispatch("plan")
        self.assertEqual(report["status"], "complete")
        self.assertEqual(job["status"], "complete")
        self.assertEqual((self.project / "app.py").read_text(), "value = 2\n")

    def test_malformed_report_plus_mutation_blocks_without_silent_replay(self):
        os.environ["FAKE_MUTATION"] = "malformed"
        result = orc.stage_run(self.state["id"])
        self.assertFalse(result["ok"])
        state = orc.read_json(self.rundir / "state.json")
        job = state["failed_jobs"][-1]
        self.assertEqual(job["status"], "blocked")
        self.assertEqual(state["status"], "blocked")
        self.assertIn("# mutated by read-only stage", (self.project / "app.py").read_text())
        self.assertTrue((Path(job["path"]) / "source-mutation.json").is_file())
        # A blocked run must not be silently replayed on the modified tree.
        with patch.object(orc, "call_model") as call:
            again = orc.stage_run(self.state["id"])
        call.assert_not_called()
        self.assertFalse(again["ok"])
        self.assertEqual(again["next_action"], "orchestrator_resume")

    def test_nonzero_child_exit_with_mutation_is_blocked(self):
        os.environ["FAKE_MUTATION"] = "exit1"
        with self.assertRaises(RuntimeError):
            self.dispatch("plan")
        job = self.state["failed_jobs"][-1]
        self.assertEqual(job["status"], "blocked")
        self.assertIsNone(self.state["active_job"])
        self.assertIn("# mutated by read-only stage", (self.project / "app.py").read_text())

    def test_stage_run_blocks_a_mutating_plan_and_keeps_work(self):
        os.environ["FAKE_MUTATION"] = "tracked"
        result = orc.stage_run(self.state["id"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["stage"], "plan")
        self.assertEqual(result["status"], "blocked")
        self.assertIn("read-only", (result["pause_reason"] or "").lower())
        state = orc.read_json(self.rundir / "state.json")
        self.assertIsNone(state["active_job"])
        self.assertIn("# mutated by read-only stage", (self.project / "app.py").read_text())
        self.assertTrue(state["failed_jobs"])

    def test_cached_decision_dispatch_completion_mismatch_is_rejected(self):
        jobdir = self.rundir / "jobs" / "decision-mutated"
        jobdir.mkdir(parents=True)
        before = orc.source_snapshot(self.project)
        (self.project / "app.py").write_text("value = 77\n")
        after = orc.source_snapshot(self.project)
        orc.atomic_json(jobdir / "dispatch.json", {
            "kind": "decision", "role": "architect", "source": before})
        orc.atomic_json(jobdir / "completion.json", {"final_snapshot": after})
        orc.atomic_json(jobdir / "report.json", {
            "contract_version": 2, "verdict": "approved", "reason": "x",
            "inspected": ["app.py"], "dismissed_findings": []})
        self.state.update(phase="accept", completed_jobs=[{
            "id": "mutated", "kind": "decision", "role": "architect",
            "status": "complete", "path": str(jobdir), "final_snapshot": after}],
            last_consumed_job_id=None)
        with self.assertRaises(orc.SourceMutationError):
            orc.cached_job_report(self.rundir, self.state, "decision")

    def test_recovered_plan_report_with_dispatch_completion_mutation_is_rejected(self):
        jobdir = self.rundir / "jobs" / "plan-recovered"
        jobdir.mkdir(parents=True)
        before = orc.source_snapshot(self.project)
        (self.project / "app.py").write_text("value = 55\n")
        after = orc.source_snapshot(self.project)
        orc.atomic_json(jobdir / "dispatch.json", {"kind": "plan", "source": before})
        report_path = jobdir / "recovered-report.json"
        orc.atomic_json(report_path, {"contract_version": 2, "status": "complete",
                                      "summary": "plan", "invariants": ["Keep behavior"],
                                      "batches": [{"title": "one", "goal": "change",
                                                   "acceptance": ["works"],
                                                   "checks": [["true"]], "risk": "ordinary"}],
                                      "blocker": ""})
        recovery_path = jobdir / "recovery.json"
        orc.atomic_json(recovery_path, {"job_id": "plan-recovered"})
        self.state.update(
            phase="plan",
            failed_jobs=[{"id": "plan-recovered", "kind": "plan", "role": "architect",
                          "path": str(jobdir), "status": "failed"}],
            report_recoveries=[{"kind": "plan", "job_id": "plan-recovered",
                                "report_path": str(report_path),
                                "recovery_path": str(recovery_path),
                                "report_sha256": orc.content_hash(orc.read_json(report_path)),
                                "source_signature": orc.signature(after)}])
        with self.assertRaises(orc.SourceMutationError):
            orc.cached_recovered_job_report(self.rundir, self.state, "plan")


if __name__ == "__main__":
    unittest.main()
