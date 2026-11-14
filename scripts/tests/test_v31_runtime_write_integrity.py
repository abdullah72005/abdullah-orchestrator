"""AOR31-02: ignored runtime inputs and symlinks are part of write detection."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import test_orchestrator as baseline
orc = baseline.orc


FAKE_CLI = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
mode = os.environ.get('FAKE_WRITE_MODE', 'none')
target = os.environ.get('FAKE_WRITE_PATH', '')
if '--version' in args:
    print('1.18.35')
    sys.exit(0)
if mode == 'write' and target:
    pathlib.Path(target).write_text('mutated by read-only stage\n')
elif mode == 'retarget' and target:
    link = pathlib.Path(target)
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(os.environ['FAKE_WRITE_TARGET'])
elif mode == 'delete' and target:
    pathlib.Path(target).unlink()
name = pathlib.Path(sys.argv[0]).name
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
                           'checks': [[sys.executable, '-c', 'pass']],
                           'risk': 'ordinary'}]}
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
if name == 'codex':
    output.write_text(json.dumps(report))
else:
    print(json.dumps({'type': 'text', 'sessionID': 'ses-write',
                      'part': {'text': json.dumps(report)}}))
    print(json.dumps({'type': 'step_finish', 'sessionID': 'ses-write',
                      'part': {'reason': 'stop'}}))
'''


class RuntimeWriteIntegrityTests(unittest.TestCase):
    setUp = baseline.ControlTests.setUp
    tearDown = baseline.ControlTests.tearDown

    def setUp(self):
        baseline.ControlTests.setUp(self)
        bin_dir = self.root / "write-bin"
        bin_dir.mkdir()
        script = bin_dir / "fake_cli.py"
        script.write_text(FAKE_CLI)
        script.chmod(0o755)
        for name in ("codex", "claude", "opencode"):
            (bin_dir / name).symlink_to(script)
        env_patch = patch.dict(os.environ, {
            "PATH": str(bin_dir) + ":" + os.environ["PATH"],
            "OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": ""})
        env_patch.start()
        self.addCleanup(env_patch.stop)
        for name in ("FAKE_WRITE_MODE", "FAKE_WRITE_PATH", "FAKE_WRITE_TARGET"):
            os.environ.pop(name, None)
            self.addCleanup(lambda name=name: os.environ.pop(name, None))

    def dispatch(self, kind="plan"):
        return orc.call_model(
            self.rundir, self.state, self.cfg, "architect", kind,
            "prompt", self.project, host="codex")

    def write(self, path, text):
        (self.project / path).parent.mkdir(parents=True, exist_ok=True)
        (self.project / path).write_text(text)

    def ignored(self, *names):
        (self.project / ".gitignore").write_text("\n".join(names) + "\n")

    def assert_refused_and_preserved(self, path, expected_text):
        with self.assertRaises(orc.SourceMutationError):
            self.dispatch("plan")
        job = self.state["failed_jobs"][-1]
        self.assertEqual(job["status"], "blocked")
        self.assertIsNone(self.state["active_job"])
        self.assertIn("runtime_input", " ".join(
            item.get("source", "") for item in job["source_mutation"]["paths"]))
        self.assertEqual((self.project / path).read_text(), expected_text)

    def test_ignored_python_write_in_a_read_only_stage_is_refused(self):
        self.ignored("ignored_helper.py")
        self.write("ignored_helper.py", "value = 7\n")
        before = orc.source_snapshot(self.project)
        self.assertIn("ignored_helper.py", before["runtime_inputs"]["files"])
        os.environ.update({"FAKE_WRITE_MODE": "write",
                           "FAKE_WRITE_PATH": "ignored_helper.py"})
        self.assert_refused_and_preserved("ignored_helper.py",
                                          "mutated by read-only stage\n")

    def test_ignored_config_write_is_refused(self):
        self.ignored("runtime-settings.json")
        self.write("runtime-settings.json", '{"enabled": true}\n')
        os.environ.update({"FAKE_WRITE_MODE": "write",
                           "FAKE_WRITE_PATH": "runtime-settings.json"})
        self.assert_refused_and_preserved("runtime-settings.json",
                                          "mutated by read-only stage\n")

    def test_in_project_symlink_target_only_edit_is_refused(self):
        self.ignored("linked.py", "target.py")
        self.write("target.py", "value = 1\n")
        (self.project / "linked.py").symlink_to("target.py")
        os.environ.update({"FAKE_WRITE_MODE": "write",
                           "FAKE_WRITE_PATH": "target.py"})
        self.assert_refused_and_preserved("target.py",
                                          "mutated by read-only stage\n")

    def test_symlink_retargeting_is_refused(self):
        self.ignored("linked.py", "one.py", "two.py")
        self.write("one.py", "value = 1\n")
        self.write("two.py", "value = 2\n")
        (self.project / "linked.py").symlink_to("one.py")
        os.environ.update({"FAKE_WRITE_MODE": "retarget",
                           "FAKE_WRITE_PATH": "linked.py",
                           "FAKE_WRITE_TARGET": "two.py"})
        with self.assertRaises(orc.SourceMutationError):
            self.dispatch("plan")
        self.assertEqual(os.readlink(self.project / "linked.py"), "two.py")

    def test_directory_link_target_edit_is_refused(self):
        self.write("real_lib/mod.py", "value = 1\n")
        (self.project / "lib").symlink_to("real_lib")
        os.environ.update({"FAKE_WRITE_MODE": "write",
                           "FAKE_WRITE_PATH": "real_lib/mod.py"})
        with self.assertRaises(orc.SourceMutationError):
            self.dispatch("plan")

    def test_dangling_and_outside_links_are_unprovable_not_certified(self):
        (self.project / "dangling.py").symlink_to("missing-target.py")
        outside = self.root / "outside.py"
        outside.write_text("outside = 1\n")
        (self.project / "outside_link.py").symlink_to(outside)
        snapshot = orc.source_snapshot(self.project)
        self.assertFalse(snapshot["runtime_inputs"]["complete"])
        mutation = orc.source_mutation(snapshot, snapshot)
        self.assertTrue(mutation["mutated"])
        self.assertIn("runtime_projection_incomplete", mutation["reasons"])

    def test_unchanged_dirty_and_ignored_inputs_and_volatile_metadata_pass(self):
        self.ignored("ignored_helper.py", "dirty.txt")
        self.write("ignored_helper.py", "value = 7\n")
        self.write("dirty.txt", "dirty\n")
        before = orc.source_snapshot(self.project)
        (self.project / "ignored_helper.py").touch()
        (self.project / "dirty.txt").touch()
        after = orc.source_snapshot(self.project)
        self.assertEqual(orc.source_write_projection(before),
                         orc.source_write_projection(after))
        self.assertFalse(orc.source_mutation(before, after)["mutated"])
        # Environment/toolchain/configuration are separate provenance checks and
        # are deliberately not part of write detection.
        polluted = dict(after)
        polluted["environment"] = {"changed": True}
        polluted["toolchain"] = {"changed": True}
        polluted["configuration"] = {"changed": True}
        self.assertFalse(orc.source_mutation(before, polluted)["mutated"])

    def test_old_projection_binding_is_invalidated_not_trusted(self):
        snapshot = orc.source_snapshot(self.project)
        job_dir = self.rundir / "jobs" / "plan-old-binding"
        job_dir.mkdir(parents=True)
        orc.atomic_json(job_dir / "dispatch.json", {"kind": "plan",
                                                    "source": snapshot})
        orc.atomic_json(job_dir / "completion.json",
                        {"final_snapshot": snapshot})
        legacy_sha = orc.content_hash({
            "path": snapshot["path"], "git_head": snapshot["git_head"],
            "changed": snapshot["changed"]})
        job = {"id": "old-binding", "kind": "plan",
               "source_integrity": {"dispatch_sha256": legacy_sha,
                                    "completion_sha256": legacy_sha}}
        violation = orc.validate_preserved_stage_source(job, job_dir, "plan")
        self.assertIsNotNone(violation)
        self.assertIn("recorded_binding_mismatch",
                      violation.diagnostics.get("reasons", []))

    def test_cached_recovered_completion_replays_runtime_integrity(self):
        self.ignored("ignored_helper.py")
        self.write("ignored_helper.py", "value = 7\n")
        before = orc.source_snapshot(self.project)
        job_dir = self.rundir / "jobs" / "plan-cached"
        job_dir.mkdir(parents=True)
        (self.project / "ignored_helper.py").write_text("mutated\n")
        after = orc.source_snapshot(self.project)
        report = {"contract_version": 2, "status": "complete", "summary": "plan",
                  "invariants": ["Keep behavior"], "blocker": "",
                  "batches": [{"title": "b", "goal": "g", "acceptance": ["a"],
                               "checks": [[sys.executable, "-c", "pass"]],
                               "risk": "ordinary"}]}
        orc.atomic_json(job_dir / "dispatch.json", {"kind": "plan",
                                                    "source": before})
        orc.atomic_json(job_dir / "completion.json",
                        {"final_snapshot": after})
        orc.atomic_json(job_dir / "report.json", report)
        self.state["completed_jobs"] = [{
            "id": "cached", "kind": "plan", "role": "architect",
            "status": "complete", "path": str(job_dir),
            "amendment_epoch": 0,
            "source_integrity": {
                "dispatch_sha256": orc.source_write_sha(before),
                "completion_sha256": orc.source_write_sha(after)}}]
        orc.save(self.rundir, self.state)
        with self.assertRaises(orc.SourceMutationError):
            orc.cached_job_report(self.rundir, self.state, "plan")

    def test_acceptance_binding_sees_ignored_input_drift(self):
        self.ignored("ignored_helper.py")
        self.write("ignored_helper.py", "value = 7\n")
        snapshot = orc.source_snapshot(self.project)
        binding = {
            "version": orc.DECISION_BINDING_VERSION,
            "run_id": self.state.get("id"),
            "source_signature": orc.signature(snapshot),
            "source_write_sha256": orc.source_write_sha(snapshot),
            "plan_version": None,
            "plan_sha256": orc.content_hash(None),
            "plan_revision": 0,
            "batch_index": 0,
            "verification": [],
            "created_at": orc.now(),
        }
        binding["binding_sha256"] = orc.content_hash(
            {key: value for key, value in binding.items()
             if key != "binding_sha256"})
        (self.project / "ignored_helper.py").write_text("mutated\n")
        drift = orc.decision_binding_drift(binding, self.state, self.project)
        self.assertTrue(any("candidate source" in reason for reason in drift), drift)

    def test_verification_boundary_detects_ignored_input_change(self):
        self.ignored("ignored_helper.py")
        self.write("ignored_helper.py", "value = 7\n")
        batch = {"title": "b", "risk": "ordinary",
                 "checks": [[sys.executable, "-c",
                             "import pathlib; pathlib.Path('ignored_helper.py')"
                             ".write_text('mutated')"]]}
        evidence = orc.run_checks(self.rundir, self.state, self.cfg,
                                  self.project, batch)
        self.assertFalse(evidence["passed"])
        self.assertFalse(evidence["source_unchanged"])


if __name__ == "__main__":
    unittest.main()
