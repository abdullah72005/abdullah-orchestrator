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

    def test_opencode_version_pin_is_explicit(self):
        self.assertEqual(orc.opencode_dialect("1.18.35", pinned="1.18"), "v1")
        with self.assertRaisesRegex(RuntimeError, "pinned"):
            orc.opencode_dialect("1.19.1", pinned="1.18")
        with self.assertRaisesRegex(RuntimeError, "Unsupported|Unrecognized"):
            orc.opencode_dialect("3.0.0", pinned="")

    def test_worker_environment_scrubs_credentials(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "secret", "GITHUB_TOKEN": "secret",
                                     "NORMAL_SETTING": "yes"}):
            env = orc.scrubbed_env()
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("GITHUB_TOKEN", env)
        self.assertEqual(env["NORMAL_SETTING"], "yes")

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
