"""Checkpoint C: authorization, version pinning, migration safety."""
from __future__ import annotations

import contextlib
import copy
import io
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import test_orchestrator as baseline

orc = baseline.orc


class CheckpointCSecurity(unittest.TestCase):
    def setUp(self):
        baseline.ControlTests.setUp(self)

    def _cfg(self):
        return copy.deepcopy(self.cfg)

    def test_newer_config_schema_is_refused(self):
        cfg = self._cfg(); cfg["schema_version"] = 999
        with patch.object(orc, "read_json", return_value=cfg):
            with self.assertRaisesRegex(ValueError, "newer|schema"):
                orc.config()

    def test_config_supervisor_pin_mismatch_is_refused(self):
        cfg = self._cfg(); cfg.setdefault("runtime", {})["supervisor_version"] = "0.0.1"
        with patch.object(orc, "read_json", return_value=cfg):
            with self.assertRaisesRegex(ValueError, "supervisor version"):
                orc.config()

    def test_unimplemented_isolation_and_nonboolean_auth_fail_closed(self):
        cfg = self._cfg()
        cfg.setdefault("authorization", {})["isolation_profile"] = "container"
        with patch.object(orc, "read_json", return_value=cfg):
            with self.assertRaisesRegex(ValueError, "isolation profile"):
                orc.config()
        cfg = self._cfg()
        cfg.setdefault("authorization", {})["sensitive_cli_enabled"] = "false"
        with patch.object(orc, "read_json", return_value=cfg):
            with self.assertRaisesRegex(ValueError, "boolean"):
                orc.config()
        cfg = self._cfg()
        cfg.setdefault("authorization", {})["container_profile_enabled"] = True
        with patch.object(orc, "read_json", return_value=cfg):
            with self.assertRaisesRegex(ValueError, "not implemented"):
                orc.config()

    def test_opencode_version_pin_is_explicit(self):
        self.assertEqual(orc.opencode_dialect("1.18.35", pinned="1.18"), "v1")
        self.assertEqual(orc.opencode_dialect("1.18.35", pinned="1.18.35"), "v1")
        with self.assertRaisesRegex(RuntimeError, "Invalid pinned"):
            orc.opencode_dialect("1.18.35", pinned="v1")
        with self.assertRaisesRegex(RuntimeError, "pinned"):
            orc.opencode_dialect("1.19.1", pinned="1.18")
        with self.assertRaisesRegex(RuntimeError, "Unsupported|Unrecognized"):
            orc.opencode_dialect("3.0.0", pinned="")

    def test_worker_environment_scrubs_credentials_and_preserves_config(self):
        with patch.dict(os.environ, {
                "OPENAI_API_KEY": "secret", "GITHUB_TOKEN": "secret",
                "NORMAL_SETTING": "yes", "GITHUB_ACTIONS": "true",
                "AWS_REGION": "eu-west-1", "AWS_ACCESS_KEY_ID": "AKIA",
                "PGPASSWORD": "secret", "MY_DATABASE_URL": "postgres://u:p@db/x",
                "REDIS_URL": "redis://u:p@cache/0", "BASE_URL":
                "https://u:p@example.test/api", "PIP_INDEX_URL":
                "https://user:pass@example.test/simple"}):
            env = orc.scrubbed_env()
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("GITHUB_TOKEN", env)
        self.assertEqual(env["NORMAL_SETTING"], "yes")
        self.assertEqual(env["GITHUB_ACTIONS"], "true")
        self.assertEqual(env["AWS_REGION"], "eu-west-1")
        for key in ("AWS_ACCESS_KEY_ID", "PGPASSWORD", "MY_DATABASE_URL", "REDIS_URL"):
            self.assertNotIn(key, env)
        self.assertNotIn("user:pass", env["PIP_INDEX_URL"])
        self.assertNotIn("u:p", env["BASE_URL"])

    def test_implementer_profile_denies_external_and_network(self):
        v1 = orc.opencode_profile("implementer", "v1")
        self.assertEqual(v1["permission"]["external_directory"], "deny")
        self.assertEqual(v1["permission"]["webfetch"], "deny")
        v2 = orc.opencode_profile("implementer", "v2")
        rendered = str(v2["permissions"])
        self.assertIn("external_directory", rendered)
        self.assertIn("webfetch", rendered)

    def test_state_compatibility_and_newer_state_refusal(self):
        current = dict(self.state)
        current.update(schema_version=orc.STATE_SCHEMA_VERSION,
                       supervisor_version=orc.SUPERVISOR_VERSION)
        self.assertEqual(orc.state_compatibility(current)["status"], "current")
        legacy = dict(self.state)
        legacy.pop("schema_version", None)
        self.assertEqual(orc.state_compatibility(legacy)["status"], "legacy")
        newer = dict(current); newer["schema_version"] = orc.STATE_SCHEMA_VERSION + 1
        with self.assertRaisesRegex(RuntimeError, "newer"):
            orc.assert_state_compatible(newer)

    def test_compatibility_preview_is_read_only(self):
        legacy = dict(self.state); legacy.pop("schema_version", None)
        orc.save(self.rundir, legacy)
        before = (self.rundir / "state.json").read_bytes()
        result = orc.compatibility_run("test-run00")
        self.assertFalse(result["writes"])
        self.assertEqual(result["status"], "legacy")
        self.assertEqual((self.rundir / "state.json").read_bytes(), before)

    def test_explicit_migration_backs_up_before_writing(self):
        legacy = dict(self.state); legacy.pop("schema_version", None)
        legacy.update(status="paused", active_job=None, active_check=None)
        orc.save(self.rundir, legacy)
        backup_dir = self.root / "migration-backups"
        result = orc.migrate_run("test-run00", str(backup_dir))
        self.assertTrue(result["migrated"])
        backup = Path(result["backup"])
        self.assertTrue(backup.is_file())
        backup_state = orc.read_json(backup)
        self.assertNotIn("schema_version", backup_state)
        migrated = orc.read_json(self.rundir / "state.json")
        self.assertEqual(migrated["schema_version"], orc.STATE_SCHEMA_VERSION)
        self.assertEqual(migrated["supervisor_version"], orc.SUPERVISOR_VERSION)
        self.assertIn("migration_from", migrated)

    def test_migration_clears_stale_verification_progress(self):
        legacy = dict(self.state)
        legacy.pop("schema_version", None)
        legacy.update(phase="verify", status="paused",
                      check_progress={"identity": {"old": True}},
                      verification={"path": "/tmp/old", "passed": True})
        orc.save(self.rundir, legacy)
        result = orc.migrate_run("test-run00", str(self.root / "migrate-verify"))
        self.assertTrue(result["migrated"])
        saved = orc.read_json(self.rundir / "state.json")
        self.assertIsNone(saved.get("check_progress"))
        self.assertIsNone(saved.get("verification"))
        self.assertEqual(saved["phase"], "verify")

    def test_migration_resets_review_accept_but_not_integrate(self):
        legacy = dict(self.state); legacy.pop("schema_version", None)
        legacy.update(phase="accept", status="paused", batch_index=0,
                      plan={"batches": [{"title": "x"}]}, verification=None,
                      single_batch_verification={"path": "old"})
        orc.save(self.rundir, legacy)
        orc.migrate_run("test-run00", str(self.root / "migrate-accept"))
        saved = orc.read_json(self.rundir / "state.json")
        self.assertEqual(saved["phase"], "verify")
        self.assertNotIn("single_batch_verification", saved)
        legacy = dict(self.state); legacy.pop("schema_version", None)
        legacy.update(phase="integrate", status="paused", batch_index=1,
                      plan={"batches": [{"title": "x"}]}, verification=None)
        orc.save(self.rundir, legacy)
        orc.migrate_run("test-run00", str(self.root / "migrate-integrate"))
        saved = orc.read_json(self.rundir / "state.json")
        self.assertEqual(saved["phase"], "integrate")
        self.assertEqual(saved["batch_index"], 1)

    def test_generated_recovery_command_uses_project_flag(self):
        advice = orc._conflict_resolution("owner", "new-run", "orphaned")
        self.assertIn("checkout-recover --project <project>", advice)

    def test_new_run_requires_contract_v2(self):
        project = self.root / "new-contract-project"
        project.mkdir(); project = baseline.setup_repo(project)
        with patch.object(orc, "DEFAULT_STATE", self.root / "new-contract-runs"):
            run_id, _folder, state = orc.create_run(project=str(project), goal="x",
                                                    host="codex", skip_doctor=True)
            self.assertEqual(state.get("contract_version_required"), 2)
            self.assertEqual(orc.load(run_id)[1]["contract_version_required"], 2)

    def test_sensitive_cli_is_disabled_by_default(self):
        cfg = self._cfg(); cfg.setdefault("authorization", {})["sensitive_cli_enabled"] = False
        with patch.object(orc, "config", return_value=cfg):
            with self.assertRaisesRegex(RuntimeError, "disabled"):
                orc._operator_action_allowed("retire")

    def test_sensitive_cli_refuses_model_context(self):
        cfg = self._cfg(); cfg.setdefault("authorization", {})["sensitive_cli_enabled"] = True
        with patch.object(orc, "config", return_value=cfg), \
                patch.dict(os.environ, {"ABDULLAH_JOB_ID": "job-1"}):
            with self.assertRaisesRegex(RuntimeError, "model-owned"):
                orc._operator_action_allowed("retire")

    def test_sensitive_functions_guard_direct_import(self):
        cfg = self._cfg()
        cfg.setdefault("authorization", {})["sensitive_cli_enabled"] = False
        with patch.object(orc, "config", return_value=cfg):
            for call in (lambda: orc.retire_run("test-run00", "r", "a"),
                         lambda: orc.adopt_run("test-run00"),
                         lambda: orc.checkout_recover(self.project, "owner", "r", "a"),
                         lambda: orc.migrate_run("test-run00"),
                         lambda: orc.acknowledge_legacy_verification("test-run00", "r", "a")):
                with self.subTest(call=call):
                    with self.assertRaisesRegex(RuntimeError, "disabled"):
                        call()

    def test_cli_resume_refuses_incompatible_state(self):
        newer = dict(self.state); newer["schema_version"] = orc.STATE_SCHEMA_VERSION + 1
        newer["status"] = "paused"; newer["active_job"] = None; newer["active_check"] = None
        orc.save(self.rundir, newer)
        with contextlib.redirect_stderr(io.StringIO()) as err:
            code = orc.main(["resume", "test-run00"])
        self.assertEqual(code, 2)
        self.assertIn("execution-compatible", err.getvalue())
        self.assertEqual(orc.read_json(self.rundir / "state.json")["status"], "paused")

    def test_supervisor_or_config_change_blocks_stage_until_migration(self):
        changed = dict(self.state); changed["supervisor_version"] = "0.0.1"
        orc.save(self.rundir, changed)
        with self.assertRaisesRegex(RuntimeError, "execution-compatible"):
            orc.assert_state_compatible(changed)
        with self.assertRaisesRegex(RuntimeError, "execution-compatible"):
            orc.stage_run("test-run00")
        changed.update(status="paused", schema_version=orc.STATE_SCHEMA_VERSION,
                       supervisor_version="0.0.1", config_schema_version=orc.CONFIG_SCHEMA_VERSION)
        orc.save(self.rundir, changed)
        result = orc.migrate_run("test-run00", str(self.root / "migrate-config"))
        self.assertTrue(result["migrated"])
        self.assertEqual(orc.read_json(self.rundir / "state.json")["supervisor_version"],
                         orc.SUPERVISOR_VERSION)

    def test_migration_refuses_running_or_active_work(self):
        self.state.update(status="running", schema_version=1)
        orc.save(self.rundir, self.state)
        with self.assertRaisesRegex(RuntimeError, "Interrupt|paused"):
            orc.migrate_run("test-run00", str(self.root / "migrate-running"))
        self.state.update(status="paused", schema_version=1,
                          active_job={"id": "j", "status": "running"})
        orc.save(self.rundir, self.state)
        with self.assertRaisesRegex(RuntimeError, "active|uncertain"):
            orc.migrate_run("test-run00", str(self.root / "migrate-active"))

    def test_modify_launch_missing_is_guarded(self):
        cfg = self._cfg()
        cfg.setdefault("authorization", {})["sensitive_cli_enabled"] = False
        self.state.update(status="uncertain", active_job={"id": "j",
                          "launch_file": str(self.root / "missing.json")})
        orc.save(self.rundir, self.state)
        with patch.object(orc, "config", return_value=cfg):
            with self.assertRaisesRegex(RuntimeError, "disabled"):
                orc.modify("test-run00", "reconcile", launch_missing=True,
                           evidence="inspected")

    def test_recovery_does_not_require_current_config_hash(self):
        changed = dict(self.state)
        changed.update(status="uncertain", config_sha256="old-config-hash",
                       active_job={"id": "j", "status": "uncertain",
                                   "launch_file": str(self.root / "missing.json")})
        orc.save(self.rundir, changed)
        with self.assertRaisesRegex(RuntimeError, "unproven|not proven"):
            orc.modify("test-run00", "reconcile")

    def test_sensitive_cli_main_guard_blocks_before_dispatch(self):
        cfg = self._cfg(); cfg.setdefault("authorization", {})["sensitive_cli_enabled"] = False
        with patch.object(orc, "config", return_value=cfg), \
                patch.object(orc, "retire_run") as retire, \
                contextlib.redirect_stderr(io.StringIO()) as err:
            code = orc.main(["retire", "test-run00", "--reason", "r",
                             "--acknowledge", "a"])
        self.assertEqual(code, 2)
        retire.assert_not_called()
        self.assertIn("disabled", err.getvalue())

    def test_newer_state_is_not_staged(self):
        newer = dict(self.state); newer["schema_version"] = orc.STATE_SCHEMA_VERSION + 1
        self.state = newer
        orc.save(self.rundir, newer)
        with patch.object(orc, "advance") as advance:
            with self.assertRaisesRegex(RuntimeError, "newer"):
                orc.stage_run("test-run00")
        advance.assert_not_called()

    def test_model_routes_remain_go_only(self):
        for role in ("explorer", "implementer", "reviewer"):
            self.assertTrue(orc.model_route(self.cfg, "codex", role)["model"]
                            .startswith("opencode-go/"))
        broken = self._cfg(); broken["fallback"]["enabled"] = True
        with patch.object(orc, "read_json", return_value=broken):
            with self.assertRaisesRegex(ValueError, "fallback"):
                orc.config()


if __name__ == "__main__":
    unittest.main()
