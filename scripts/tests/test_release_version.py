"""Release identity: public version never resets the protocol or schemas.

These tests do not launch a model and do not touch live state.  They pin the
public v1.0.0 release to its independent internal identifiers and check the
documented example configuration and CLI surface stayed consistent.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest

import test_orchestrator as baseline

orc = baseline.orc
SRC = baseline.SRC


class ReleaseIdentityTests(unittest.TestCase):
    def test_public_version_is_separate_from_internal_identifiers(self):
        info = orc.version_info()
        self.assertEqual(info["product"], "abdullah-orchestrator")
        self.assertEqual(info["product_version"], "1.2.1")
        # A public tag must not renumber the supervisor protocol or schemas.
        self.assertEqual(info["supervisor_version"], "3.1.0")
        self.assertEqual(info["state_schema_version"], 3)
        self.assertEqual(info["config_schema_version"], 3)
        self.assertEqual(info["report_contract_version"], 2)
        self.assertNotEqual(info["product_version"], info["supervisor_version"])

    def test_version_command_prints_json_and_exits_zero(self):
        proc = subprocess.run([sys.executable, str(SRC), "version"],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["product_version"], orc.PRODUCT_VERSION)
        self.assertEqual(payload["supervisor_version"], orc.SUPERVISOR_VERSION)
        self.assertEqual(payload["state_schema_version"], orc.STATE_SCHEMA_VERSION)

    def test_example_config_pins_the_unchanged_protocol_versions(self):
        config = json.loads((SRC.parent / "config.example.json").read_text())
        self.assertEqual(config["schema_version"], orc.CONFIG_SCHEMA_VERSION)
        self.assertEqual(config["runtime"]["supervisor_version"],
                         orc.SUPERVISOR_VERSION)
        # The documented ranges are the tested ones; no public release widens them.
        self.assertEqual(config["runtime"]["opencode_supported"],
                         [">=1.18 <2.0", ">=2.2 <3.0"])

    def test_strict_protocol_version_pin_still_rejects_a_public_version(self):
        """A public tag must not satisfy the internal supervisor pin."""
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        cfg = json.loads((SRC.parent / "config.example.json").read_text())
        cfg["runtime"]["supervisor_version"] = "1.0.0"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            path.write_text(json.dumps(cfg))
            with patch.object(orc, "CONFIG_PATH", path), \
                    self.assertRaisesRegex(ValueError, "does not match"):
                orc.config()
