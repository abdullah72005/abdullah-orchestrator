"""Checkpoint B: verification provenance and command policy."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import test_orchestrator as baseline

orc = baseline.orc


class CheckpointBProvenance(unittest.TestCase):
    def setUp(self):
        baseline.ControlTests.setUp(self)
        self.env_file = self.project / ".env"
        self.env_file.write_text("FEATURE=1\n")
        self.compose = self.project / "docker-compose.yml"
        self.compose.write_text("services:\n  web:\n    image: test\n")

    def test_source_snapshot_attests_runtime_inputs_and_environment(self):
        snap = orc.source_snapshot(self.project, cfg=self.cfg)
        self.assertEqual(snap["provenance_version"], orc.SOURCE_PROVENANCE_VERSION)
        self.assertTrue(snap["provenance_complete"])
        self.assertIn(".env", snap["runtime_inputs"]["files"])
        self.assertIn("docker-compose.yml", snap["runtime_inputs"]["files"])
        self.assertIn("PATH", snap["environment"]["values"])
        self.assertEqual(snap["configuration"]["available"], True)
        before = orc.signature(snap)
        self.env_file.write_text("FEATURE=2\n")
        self.assertNotEqual(before, orc.signature(orc.source_snapshot(self.project, cfg=self.cfg)))

    def test_ao_04_runtime_input_change_invalidates_verification(self):
        evidence = orc.run_checks(
            self.rundir, self.state, self.cfg, self.project,
            {"title": "runtime", "checks": [[sys.executable, "-c", "print('ok')"]]})
        self.assertTrue(evidence["passed"])
        self.env_file.write_text("FEATURE=3\n")
        with self.assertRaisesRegex(ValueError, "stale|snapshot|fingerprint"):
            orc.verification_evidence_package(
                {"path": evidence["path"], "passed": True,
                 "candidate_hash": evidence["after_hash"]},
                orc.source_snapshot(self.project, cfg=self.cfg))

    def test_incomplete_runtime_manifest_blocks_verification(self):
        manifest = {"version": 2, "complete": False, "truncated": True, "files": {}}
        with patch.object(orc, "runtime_input_manifest", return_value=manifest):
            with self.assertRaisesRegex(RuntimeError, "runtime-input manifest"):
                orc.run_checks(
                    self.rundir, self.state, self.cfg, self.project,
                    {"title": "blocked", "checks": [[sys.executable, "-c", "print('no')"]]})
        self.assertIsNone(orc.read_json(self.rundir / "state.json").get("verification"))

    def test_verification_evidence_is_versioned_and_command_policy_recorded(self):
        evidence = orc.run_checks(
            self.rundir, self.state, self.cfg, self.project,
            {"title": "versioned", "checks": [[sys.executable, "-c", "print('ok')"]]})
        self.assertEqual(evidence["evidence_version"], 2)
        self.assertEqual(evidence["provenance"]["version"], orc.SOURCE_PROVENANCE_VERSION)
        command = evidence["commands"][0]
        self.assertTrue(command["command_policy"]["interpreter_string"])
        self.assertEqual(command["command_policy"]["policy"], "explicit")
        package = orc.verification_evidence_package(
            {"path": evidence["path"], "passed": True,
             "candidate_hash": evidence["after_hash"]},
            evidence["after"], run_id="test-run00")
        self.assertEqual(package["evidence_version"], 2)
        self.assertFalse(package["legacy_evidence"])
        self.assertTrue(package["provenance_complete"])

    def test_ao_08_wrapper_policy_can_reject(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["verification"].setdefault("command_policy", {})["reject_shell_wrappers"] = True
        policy = orc.verification_command_policy(["bash", "-c", "pytest"], cfg)
        self.assertTrue(policy["shell_wrapper"])
        self.assertFalse(policy["allowed"])
        with self.assertRaisesRegex(RuntimeError, "command policy"):
            orc.run_checks(self.rundir, self.state, cfg, self.project,
                           {"title": "wrapper", "checks": [["bash", "-c", "true"]]})

    def test_ao_03_compose_build_context_outside_project_is_rejected(self):
        reply = subprocess.CompletedProcess([], 0, stdout=json.dumps({
            "name": "demo",
            "services": {"web": {
                "build": {"context": "/outside/project"},
                "working_dir": "/workspace",
                "volumes": [{"type": "bind", "source": str(self.project),
                             "target": "/workspace"}]}}}))
        with patch.object(orc.subprocess, "run", return_value=reply):
            with self.assertRaisesRegex(RuntimeError, "outside the candidate checkout"):
                orc.check_docker_source(
                    self.project, ["docker", "compose", "run", "--rm", "web", "pytest"])

    def test_compose_image_service_and_build_provenance_recorded(self):
        reply = subprocess.CompletedProcess([], 0, stdout=json.dumps({
            "name": "demo",
            "services": {"web": {
                "image": "demo:test",
                "build": {"context": ".", "dockerfile": "Dockerfile"},
                "working_dir": "/workspace",
                "user": "1000",
                "environment": {"TOKEN": "secret", "MODE": "test"},
                "volumes": [{"type": "bind", "source": str(self.project),
                             "target": "/workspace"}]}}}))
        with patch.object(orc.subprocess, "run", return_value=reply):
            proof = orc.check_docker_source(
                self.project, ["docker", "compose", "-f", "docker-compose.yml",
                               "run", "--rm", "web", "pytest"])
        self.assertTrue(proof["attested"])
        self.assertEqual(proof["service"], "web")
        self.assertEqual(proof["image"], "demo:test")
        self.assertEqual(proof["build"]["dockerfile"], "Dockerfile")
        self.assertEqual(proof["compose_files"], ["docker-compose.yml"])
        self.assertEqual(proof["environment_keys"], ["MODE", "TOKEN"])
        self.assertNotIn("secret", json.dumps(proof))

    def test_compose_exec_records_image_id_and_user(self):
        replies = [
            subprocess.CompletedProcess([], 0, stdout="cid123\n"),
            subprocess.CompletedProcess([], 0, stdout=json.dumps({
                "Image": "sha256:image-id",
                "Config": {"Image": "demo:test", "WorkingDir": "/workspace",
                           "User": "1000", "Env": ["MODE=test", "TOKEN=secret"]},
                "Mounts": [{"Type": "bind", "Source": str(self.project),
                            "Destination": "/workspace"}]}))]
        with patch.object(orc.subprocess, "run", side_effect=replies):
            proof = orc.check_docker_source(
                self.project, ["docker", "compose", "-f", "docker-compose.yml",
                               "exec", "web", "pytest"])
        self.assertTrue(proof["attested"])
        self.assertEqual(proof["image_id"], "sha256:image-id")
        self.assertEqual(proof["user"], "1000")
        self.assertEqual(proof["environment_keys"], ["MODE", "TOKEN"])
        self.assertNotIn("secret", json.dumps(proof))

    def test_legacy_evidence_is_marked_not_equivalent(self):
        snap = orc.source_snapshot(self.project, cfg=self.cfg)
        candidate = orc.signature(snap)
        log = self.root / "legacy.log"
        log.write_text("ok")
        path = self.root / "legacy-verification.json"
        orc.atomic_json(path, {
            "candidate": snap, "after": snap, "candidate_hash": candidate,
            "after_hash": candidate, "passed": True, "source_unchanged": True,
            "commands": [{"argv": ["true"], "returncode": 0, "log": str(log)}]})
        package = orc.verification_evidence_package(
            {"path": str(path), "passed": True, "candidate_hash": candidate}, snap)
        self.assertEqual(package["evidence_version"], 1)
        self.assertTrue(package["legacy_evidence"])
        self.assertFalse(package["provenance_complete"])


if __name__ == "__main__":
    unittest.main()
