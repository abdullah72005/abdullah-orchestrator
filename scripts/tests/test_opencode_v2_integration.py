"""Opt-in real OpenCode V2 checks; no model call, no authentication.

Set ABDULLAH_OPENCODE_V2_BIN to an isolated V2.2.x binary to run these.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_orchestrator as baseline

orc = baseline.orc
V2_BIN = os.environ.get("ABDULLAH_OPENCODE_V2_BIN")


@unittest.skipUnless(V2_BIN and Path(V2_BIN).is_file(),
                     "set ABDULLAH_OPENCODE_V2_BIN to an isolated V2.2.x binary")
class OpenCodeV2Binary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name) / "repo"
        self.project.mkdir()
        self.bin = str(Path(V2_BIN).resolve())
        self.cfg = orc.read_json(orc.HERE / "config.example.json")
        self.cfg["runtime"]["opencode_version"] = "auto"
        cfg_path = Path(self.tmp.name) / "config.json"
        orc.atomic_json(cfg_path, self.cfg)
        patcher = patch.object(orc, "CONFIG_PATH", cfg_path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self, argv, role="explorer", timeout=30):
        env = orc.opencode_env(role, "v2")
        return subprocess.run([self.bin, *argv], cwd=self.project, env=env,
                              capture_output=True, text=True, timeout=timeout,
                              check=False)

    def test_version_is_tested_v2_line(self):
        result = self._run(["--version"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(orc.opencode_dialect(result.stdout.strip(), cfg=self.cfg), "v2")

    def test_run_help_supports_generated_flags(self):
        result = self._run(["run", "--help"])
        text = (result.stdout or "") + (result.stderr or "")
        for flag in ("--agent", "--model", "--format", "--auto", "--session",
                     "--standalone"):
            self.assertIn(flag, text)

    def test_generated_profiles_are_accepted_with_effective_denials(self):
        for role in ("explorer", "implementer", "reviewer"):
            with self.subTest(role=role):
                result = self._run(["debug", "agents", "--standalone"], role=role)
                self.assertEqual(result.returncode, 0, result.stderr)
                agents = json.loads(result.stdout)
                agent = next(a for a in agents if a.get("id") == f"abdullah-{role}")
                self.assertEqual(agent["mode"], "primary")
                actual = {(r["action"], r["resource"], r["effect"])
                          for r in agent["permissions"]}
                expected = {(r["action"], r["resource"], r["effect"])
                            for r in orc.opencode_profile(role, "v2")["permissions"]}
                self.assertTrue(expected.issubset(actual), expected - actual)
                for action in ("subagent", "external_directory"):
                    self.assertIn((action, "*", "deny"), actual)

    def test_doctor_introspection_matches_binary(self):
        with patch.dict(os.environ, {"PATH": str(Path(self.bin).parent)
                                     + os.pathsep + os.environ.get("PATH", "")}):
            for role in ("explorer", "implementer", "reviewer"):
                with self.subTest(role=role):
                    self.assertIs(orc.probe_opencode_config(self.project, role, "v2"), True)


if __name__ == "__main__":
    unittest.main()
