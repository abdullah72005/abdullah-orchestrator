"""Antigravity CLI/desktop setup: timeout bound and conflict-safe merging.

No real Antigravity, Claude or Codex CLI is invoked.  Every write targets a
test-owned temporary settings file, so unrelated user registrations are never
touched.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import install_wsl


class AntigravitySetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.settings = self.root / "settings.json"
        self.skill = self.root / "skill"

    def _write(self, value):
        self.settings.write_text(json.dumps(value, indent=2), encoding="utf-8")

    def _config(self, max_stage_seconds):
        path = self.root / "config.json"
        path.write_text(json.dumps(
            {"limits": {"max_stage_seconds": max_stage_seconds}}), encoding="utf-8")
        return path

    # -- timeout bound ---------------------------------------------------
    def test_timeout_must_exceed_the_whole_stage_budget(self):
        config = self._config(17_000)
        accepted = install_wsl.server_timeout_bound(config_path=config)
        self.assertTrue(accepted["accepted"])
        self.assertEqual(accepted["required_ms"], 17_060_000)
        self.assertEqual(accepted["requested_ms"],
                         install_wsl.RECOMMENDED_SERVER_TIMEOUT_MS)

        with self.assertRaisesRegex(ValueError, "insufficient"):
            install_wsl.server_timeout_bound(
                config_path=config, requested_ms=17_059_999)
        with self.assertRaisesRegex(ValueError, "insufficient"):
            install_wsl.server_timeout_bound(
                config_path=config, requested_ms=1_000)
        # A larger configured stage budget invalidates the shipped recommendation.
        larger = self._config(20_000)
        with self.assertRaisesRegex(ValueError, "requires at least 20060000"):
            install_wsl.server_timeout_bound(config_path=larger)
        self.assertTrue(install_wsl.server_timeout_bound(
            config_path=larger, requested_ms=21_000_000)["accepted"])

    def test_timeout_rejects_non_finite_and_absent_bounds(self):
        config = self._config(17_000)
        for value in (None, True, "18000000", float("inf"), 0, -1,
                      install_wsl.MAX_SERVER_TIMEOUT_MS + 1):
            if value is None:
                # None means "use the recommendation", which is valid here.
                continue
            with self.assertRaises((ValueError, TypeError), msg=repr(value)):
                install_wsl.server_timeout_bound(
                    config_path=config, requested_ms=value)

    # -- registration writer --------------------------------------------
    def test_registration_preserves_unrelated_servers_and_is_idempotent(self):
        self._write({
            "theme": "dark",
            "mcpServers": {"unrelated": {"command": "/usr/bin/other",
                                          "args": ["serve"]}},
        })
        before_unrelated = json.loads(self.settings.read_text())["mcpServers"]["unrelated"]
        result = install_wsl.register_antigravity(
            self.settings, python=sys.executable, skill=self.skill,
            config_path=self._config(17_000))
        self.assertTrue(result["changed"])
        self.assertEqual(result["state"], "registered")
        self.assertTrue(result["backup"] and Path(result["backup"]).exists())
        stored = json.loads(self.settings.read_text())
        self.assertEqual(stored["theme"], "dark")
        self.assertEqual(stored["mcpServers"]["unrelated"], before_unrelated)
        entry = stored["mcpServers"][install_wsl.MCP_SERVER_NAME]
        self.assertEqual(entry["command"], str(Path(sys.executable).resolve()))
        self.assertEqual(entry["args"], [str((self.skill / "scripts/orchestrator.py").resolve()),
                                         "mcp"])
        self.assertEqual(entry["timeout"],
                         install_wsl.RECOMMENDED_SERVER_TIMEOUT_MS)

        first_bytes = self.settings.read_bytes()
        again = install_wsl.register_antigravity(
            self.settings, python=sys.executable, skill=self.skill,
            config_path=self._config(17_000))
        self.assertFalse(again["changed"])
        self.assertEqual(again["state"], "already_registered")
        self.assertIsNone(again["backup"])
        self.assertEqual(self.settings.read_bytes(), first_bytes)

    def test_conflicting_registration_is_refused_without_writing(self):
        self._write({"mcpServers": {
            install_wsl.MCP_SERVER_NAME: {"command": "/usr/bin/claude",
                                          "args": ["mcp"]}}})
        original = self.settings.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "conflicting"):
            install_wsl.register_antigravity(
                self.settings, python=sys.executable, skill=self.skill,
                config_path=self._config(17_000))
        self.assertEqual(self.settings.read_bytes(), original)
        self.assertEqual(list(self.root.glob("*.bak")), [])

    def test_missing_invalid_or_unsupported_settings_are_not_invented(self):
        missing = self.root / "absent.json"
        with self.assertRaisesRegex(RuntimeError, "No Antigravity settings file"):
            install_wsl.register_antigravity(
                missing, python=sys.executable, skill=self.skill,
                config_path=self._config(17_000))
        self.assertFalse(missing.exists())

        self.settings.write_text("{not json", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "unparsable"):
            install_wsl.register_antigravity(
                self.settings, python=sys.executable, skill=self.skill,
                config_path=self._config(17_000))
        self.assertEqual(self.settings.read_text(), "{not json")

        self._write({"mcpServers": ["not-an-object"]})
        with self.assertRaisesRegex(RuntimeError, "schema"):
            install_wsl.register_antigravity(
                self.settings, python=sys.executable, skill=self.skill,
                config_path=self._config(17_000))

    def test_preview_does_not_write(self):
        self._write({"mcpServers": {}})
        original = self.settings.read_bytes()
        result = install_wsl.register_antigravity(
            self.settings, python=sys.executable, skill=self.skill,
            config_path=self._config(17_000), write=False)
        self.assertEqual(result["state"], "preview")
        self.assertTrue(result["changed"])
        self.assertEqual(self.settings.read_bytes(), original)

    def test_manual_snippets_state_the_unverified_limit(self):
        snippets = install_wsl.antigravity_manual_snippets(
            python=sys.executable, skill=self.skill,
            config_path=self._config(17_000))
        self.assertEqual(snippets["server_entry"]["timeout"],
                         install_wsl.RECOMMENDED_SERVER_TIMEOUT_MS)
        self.assertIn("18000000", " ".join(snippets["manual_steps"]))
        self.assertIn("17060000", " ".join(snippets["manual_steps"]))
        self.assertIn("not", snippets["manual_limit"])
        self.assertIn("available in this environment",
                      snippets["manual_limit"])

    # -- desktop bridge --------------------------------------------------
    def test_desktop_setup_reports_the_real_wsl_identity(self):
        self.skill.mkdir()
        with patch.dict(os.environ, {"WSL_DISTRO_NAME": "Ubuntu"}), \
                patch.object(install_wsl.shutil, "which",
                             side_effect=lambda name: f"/usr/bin/{name}"):
            info = install_wsl.desktop_setup(
                python=sys.executable, skill=self.skill,
                config_path=self._config(17_000))
        self.assertTrue(info["ok"])
        self.assertEqual(info["distro"], "Ubuntu")
        self.assertEqual(info["python"], str(Path(sys.executable).resolve()))
        self.assertEqual(info["checkout"], str(self.skill.resolve()))
        self.assertEqual(info["agy"], "/usr/bin/agy")
        launch = info["windows_launch"]
        self.assertTrue(launch["command"].endswith("wsl.exe"))
        self.assertEqual(launch["args"][:2], ["-d", "Ubuntu"])
        self.assertIn(info["supervisor"], launch["args"])
        self.assertIn("/usr/bin/env", launch["args"])
        self.assertIn("/usr/bin", launch["env"]["PATH"].split(":"))
        self.assertEqual(launch["env"]["ABDULLAH_CONFIG"],
                         str(Path(info["config"]).resolve()))
        self.assertEqual(launch["env"]["ABDULLAH_STATE_DIR"],
                         str(Path(info["state"]).resolve()))
        self.assertEqual(launch["timeout"],
                         install_wsl.RECOMMENDED_SERVER_TIMEOUT_MS)
        self.assertTrue(any("Integrated-terminal" in note
                            for note in info["notes"]))
        self.assertTrue(any("own MCP settings" in note
                            for note in info["notes"]))

    def test_desktop_setup_blocks_on_unknown_distro_and_missing_clis(self):
        with patch.dict(os.environ, {"WSL_DISTRO_NAME": ""}), \
                patch.object(install_wsl.shutil, "which", return_value=None):
            info = install_wsl.desktop_setup(
                python=sys.executable, skill=self.skill,
                config_path=self._config(17_000))
        self.assertFalse(info["ok"])
        joined = " ".join(info["blockers"])
        self.assertIn("WSL_DISTRO_NAME", joined)
        self.assertIn("agy", joined)
        self.assertIn("opencode", joined)


if __name__ == "__main__":
    unittest.main()
