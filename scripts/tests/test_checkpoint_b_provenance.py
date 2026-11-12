"""Checkpoint B: verification provenance and command policy."""
from __future__ import annotations

import copy
import json
import os
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

    def test_ao_04_ignored_nested_runtime_input_change_invalidates(self):
        (self.project / ".gitignore").write_text(".env.local\n")
        nested = self.project / "compose"
        nested.mkdir()
        (nested / ".env.local").write_text("FEATURE=one\n")
        evidence = orc.run_checks(
            self.rundir, self.state, self.cfg, self.project,
            {"title": "runtime", "checks": [[sys.executable, "-c", "print('ok')"]]})
        self.assertTrue(evidence["passed"])
        (nested / ".env.local").write_text("FEATURE=two\n")
        with self.assertRaisesRegex(ValueError, "stale|snapshot|fingerprint"):
            orc.verification_evidence_package(
                {"path": evidence["path"], "passed": True,
                 "candidate_hash": evidence["after_hash"]},
                orc.source_snapshot(self.project, cfg=self.cfg))

    def test_symlinked_runtime_input_hashes_target_content(self):
        (self.project / ".gitignore").write_text(".env.link\n")
        target = self.project / "runtime.env"
        target.write_text("TOKEN=one\n")
        link = self.project / ".env.link"
        link.symlink_to(target.name)
        first = orc.source_snapshot(self.project, cfg=self.cfg)
        self.assertIn(".env.link", first["runtime_inputs"]["files"])
        target.write_text("TOKEN=two\n")
        second = orc.source_snapshot(self.project, cfg=self.cfg)
        self.assertNotEqual(orc.signature(first), orc.signature(second))

    def test_out_of_tree_symlink_marks_manifest_incomplete(self):
        (self.project / ".gitignore").write_text(".env.outside\n")
        outside = self.root / "outside.env"
        outside.write_text("TOKEN=x\n")
        (self.project / ".env.outside").symlink_to(outside)
        manifest = orc.runtime_input_manifest(self.project, self.cfg)
        self.assertFalse(manifest["complete"])
        self.assertTrue(manifest["files"][".env.outside"]["target_outside_project"])

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

    def test_signature_ignores_volatile_environment(self):
        first = orc.source_snapshot(self.project, cfg=self.cfg)
        with patch.dict(os.environ, {"PYTHONPATH": "/tmp/changed-path"}):
            second = orc.source_snapshot(self.project, cfg=self.cfg)
        self.assertEqual(orc.signature(first), orc.signature(second))
        self.assertNotEqual(first.get("environment"), second.get("environment"))

    def test_policy_catches_combined_flags_and_script_files(self):
        for argv, key in ((["bash", "-lc", "x"], "shell_wrapper"),
                          (["bash", "-e", "-u", "-c", "x"], "shell_wrapper"),
                          (["python", "-B", "-I", "-c", "x"], "interpreter_string"),
                          (["node", "-p", "1"], "interpreter_string"),
                          (["node", "--eval", "1"], "interpreter_string"),
                          (["ruby", "--eval", "1"], "interpreter_string"),
                          (["python3.10", "-c", "x"], "interpreter_string"),
                          (["python3.11", "-B", "-c", "x"], "interpreter_string"),
                          (["python", "evil.py"], "arbitrary_script"),
                          (["env", "FOO=1", "./run.sh"], "arbitrary_script"),
                          (["docker", "compose", "run", "web", "bash", "-c", "x"],
                           "shell_wrapper")):
            with self.subTest(argv=argv):
                policy = orc.verification_command_policy(argv)
                self.assertTrue(policy[key], policy)
                self.assertEqual(policy["policy"], "explicit")

    def test_v2_evidence_missing_provenance_is_rejected(self):
        snap = orc.source_snapshot(self.project, cfg=self.cfg)
        candidate = orc.signature(snap)
        log = self.root / "unprovenanced.log"
        log.write_text("ok")
        path = self.root / "unprovenanced.json"
        orc.atomic_json(path, {
            "evidence_version": 2, "candidate": snap, "after": snap,
            "candidate_hash": candidate, "after_hash": candidate,
            "passed": True, "source_unchanged": True,
            "commands": [{"argv": ["true"], "returncode": 0, "log": str(log)}]})
        with self.assertRaisesRegex(ValueError, "provenance|manifest"):
            orc.verification_evidence_package(
                {"path": str(path), "passed": True, "candidate_hash": candidate}, snap)

    def test_contract_v2_is_enforced_and_legacy_is_marked(self):
        with self.assertRaisesRegex(ValueError, "files|evidence"):
            orc.validate_report("implementer", {"contract_version": 2,
                                                "status": "complete", "summary": "x"})
        legacy = orc.validate_report("implementer", {"status": "complete", "summary": "x"})
        self.assertNotIn("legacy_contract", legacy)
        with self.assertRaisesRegex(ValueError, "invariants"):
            orc.validate_report("plan", {"contract_version": 2, "status": "complete",
                                         "summary": "x", "batches": [{"title": "x", "goal": "x",
                                         "acceptance": ["ok"], "checks": [["true"]],
                                         "risk": "ordinary"}], "blocker": ""})

    def test_legacy_verification_path_is_not_accepted_silently(self):
        snap = orc.source_snapshot(self.project, cfg=self.cfg)
        candidate = orc.signature(snap)
        log = self.root / "legacy-accept.log"
        log.write_text("ok")
        path = self.root / "legacy-accept.json"
        orc.atomic_json(path, {"candidate": snap, "after": snap,
                               "candidate_hash": candidate, "after_hash": candidate,
                               "passed": True, "source_unchanged": True,
                               "commands": [{"argv": ["true"], "returncode": 0,
                                             "log": str(log)}]})
        self.state.update(phase="accept",
                          plan={"batches": [{"title": "one", "checks": [["true"]]}]},
                          verification={"path": str(path), "candidate_hash": candidate,
                                        "passed": True},
                          review={"status": "complete", "findings": []})
        with patch.object(orc, "run_checks") as checks:
            orc.advance(self.rundir, self.state, self.cfg)
        checks.assert_not_called()
        self.assertEqual(self.state["status"], "blocked")
        self.assertIn("Legacy verification", self.state["pause_reason"])

    def test_baseline_and_plan_hashes_are_stable(self):
        snap = orc.source_snapshot(self.project, cfg=self.cfg)
        with patch.dict(os.environ, {"PYTHONPATH": "/tmp/other"}):
            current = orc.source_snapshot(self.project, cfg=self.cfg)
        self.assertEqual(orc.signature(snap), orc.signature(current))
        self.assertNotEqual(orc.content_hash({"invariants": ["a"]}),
                            orc.content_hash({"invariants": ["b"]}))
        self.assertNotEqual(orc.signature(snap), orc.content_hash({"invariants": ["a"]}))

    def test_cross_process_signature_is_stable(self):
        code = (
            "import importlib.util, json, sys\n"
            "from pathlib import Path\n"
            "spec=importlib.util.spec_from_file_location('o', sys.argv[1])\n"
            "o=importlib.util.module_from_spec(spec); spec.loader.exec_module(o)\n"
            "print(o.signature(o.source_snapshot(Path(sys.argv[2]), cfg=o.config())))\n")
        module = Path(orc.__file__)
        env = {**os.environ, "ABDULLAH_CONFIG": str(orc.HERE / "config.example.json")}
        one = subprocess.check_output([sys.executable, "-c", code, str(module),
                                       str(self.project)], env=env, text=True).strip()
        env["PYTHONPATH"] = "/tmp/different-path"
        two = subprocess.check_output([sys.executable, "-c", code, str(module),
                                       str(self.project)], env=env, text=True).strip()
        self.assertEqual(one, two)

    def test_legacy_acknowledgment_is_explicit_and_recordable(self):
        snap = orc.source_snapshot(self.project, cfg=self.cfg)
        candidate = orc.signature(snap)
        path = self.root / "legacy-ack.json"
        orc.atomic_json(path, {})
        self.state.update(verification={"path": str(path), "candidate_hash": candidate,
                                       "passed": True})
        orc.save(self.rundir, self.state)
        result = orc.acknowledge_legacy_verification(
            "test-run00", "user inspected old evidence", "no re-run available")
        self.assertTrue(result["ok"])
        self.assertEqual(result["legacy_verification_acknowledged"]["reason"],
                         "user inspected old evidence")
        saved = orc.read_json(self.rundir / "state.json")
        saved["verification"]["evidence_version"] = 2
        orc.save(self.rundir, saved)
        with self.assertRaisesRegex(RuntimeError, "already attested"):
            orc.acknowledge_legacy_verification("test-run00", "x", "y")

    def test_baseline_environment_change_does_not_pause_implement(self):
        snap = orc.source_snapshot(self.project, cfg=self.cfg)
        batch = {"title": "one", "goal": "change", "acceptance": ["works"],
                 "checks": [["true"]], "risk": "ordinary"}
        self.state.update(phase="implement", plan={"batches": [batch]},
                          plan_version=orc.content_hash({"batches": [batch]}),
                          baseline=snap, batch_index=0,
                          handoff_authorization={"explicit_user_authorization": True})
        report = {"contract_version": 2, "status": "complete", "summary": "done",
                  "files": ["app.py"], "tests": [], "evidence": ["app.py:1"],
                  "unknowns": [], "blocker": ""}
        with patch.dict(os.environ, {"PYTHONPATH": "/tmp/only-env-change"}),                 patch.object(orc, "call_model", return_value=(report, {"id": "job"})) as model:
            orc.advance(self.rundir, self.state, self.cfg)
        model.assert_called_once()
        self.assertEqual(self.state["phase"], "verify")

    def test_legacy_acknowledgment_allows_acceptance(self):
        snap = orc.source_snapshot(self.project, cfg=self.cfg)
        candidate = orc.signature(snap)
        path = self.root / "legacy-accept-ack.json"
        orc.atomic_json(path, {})
        batch = {"title": "one", "checks": [["true"]]}
        self.state.update(phase="accept", plan={"batches": [batch]},
                          verification={"path": str(path), "candidate_hash": candidate,
                                        "passed": True},
                          review={"status": "complete", "findings": []},
                          single_batch_fast_path=True)
        orc.save(self.rundir, self.state)
        orc.acknowledge_legacy_verification("test-run00", "legacy inspected", "accept")
        self.state = orc.read_json(self.rundir / "state.json")
        evidence = {"passed": True, "candidate_hash": candidate,
                    "source_unchanged": True, "commands": []}
        verdict = {"verdict": "approved", "reason": "inspected", "inspected": ["app.py"],
                   "dismissed_findings": []}
        with patch.object(orc, "run_checks", return_value=evidence),                 patch.object(orc, "strong_call", return_value=verdict):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(self.state["status"], "complete")

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
