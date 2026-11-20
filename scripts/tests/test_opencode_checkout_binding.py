"""OpenCode project-scoped entry points must bind PWD to the checkout.

The installed CLI prefers an inherited ``PWD`` over the process cwd and
changes directory to it.  These tests pin the supervisor-side contract with
no model launch: every project-scoped entry point carries the resolved
checkout in ``PWD`` and never mutates the caller's environment.
"""
from __future__ import annotations

import os
from pathlib import Path
import unittest
from unittest.mock import patch

import test_orchestrator as baseline
orc = baseline.orc


class OpenCodeCheckoutBindingTests(unittest.TestCase):
    setUp = baseline.ControlTests.setUp
    tearDown = baseline.ControlTests.tearDown

    def stale_parent(self):
        stale = self.root / "stale-ambient"
        stale.mkdir()
        return stale

    def test_prepared_context_binds_pwd_to_resolved_checkout(self):
        stale = self.stale_parent()
        caller_env = {"PATH": os.environ.get("PATH", ""),
                      "HOME": str(self.root / "home"),
                      "PWD": str(stale)}
        with patch.object(orc, "_opencode_binary_identity",
                          return_value={"available": False}):
            context = orc._opencode_prepared_context(
                "reviewer", "v1", self.project, child_env=caller_env)
        self.assertEqual(context["project"], self.project.resolve())
        self.assertEqual(context["child_env"]["PWD"], str(self.project.resolve()))
        # The caller's mapping is a caller asset; it must not be rewritten.
        self.assertEqual(caller_env["PWD"], str(stale))

    def test_launch_context_rebinds_pwd_from_a_prepared_context(self):
        stale = self.stale_parent()
        context = {
            "dialect": "v2", "project": str(self.project.resolve()),
            "child_env": {"HOME": str(self.root / "home"), "PWD": str(stale)},
            "inline_bytes": "{}",
        }
        with patch.object(orc, "_opencode_prepared_context",
                          return_value=context):
            launch = orc._opencode_launch_context(
                "reviewer", "v2", self.project, allow_free=True)
        self.assertEqual(launch["env"]["PWD"], str(self.project.resolve()))

    def test_launch_context_rebinds_pwd_to_the_context_project(self):
        # The prepared project is authoritative even if the caller's path
        # argument later differs, so launch cannot drift from observation.
        other = self.root / "other-checkout"
        other.mkdir()
        context = {
            "dialect": "v2", "project": str(other.resolve()),
            "child_env": {"HOME": str(self.root / "home")},
            "inline_bytes": "{}",
        }
        with patch.object(orc, "_opencode_prepared_context",
                          return_value=context):
            launch = orc._opencode_launch_context(
                "reviewer", "v2", self.project, allow_free=True)
        self.assertEqual(launch["env"]["PWD"], str(other.resolve()))

    def test_opencode_env_binds_only_when_a_project_is_supplied(self):
        stale = self.stale_parent()
        with patch.dict(os.environ, {"PWD": str(stale)}):
            unbound = orc.opencode_env("reviewer", "v2")
            bound = orc.opencode_env("reviewer", "v2", project=self.project)
            self.assertEqual(os.environ["PWD"], str(stale))
        self.assertEqual(unbound["PWD"], str(stale))
        self.assertEqual(bound["PWD"], str(self.project.resolve()))

    def test_doctor_profile_probe_binds_pwd(self):
        stale = self.stale_parent()
        captured = {}

        class Response:
            returncode = 0
            stdout = "[]"
            stderr = ""

        def fake_run(command, **kwargs):
            captured["command"] = command
            captured["cwd"] = kwargs.get("cwd")
            captured["env"] = kwargs.get("env")
            return Response()

        with patch.dict(os.environ, {"PWD": str(stale)}), \
                patch.object(orc.subprocess, "run", side_effect=fake_run):
            result = orc.probe_opencode_config(self.project, "reviewer", "v2")
        self.assertFalse(result)
        self.assertEqual(captured["cwd"], self.project)
        self.assertEqual(captured["env"]["PWD"], str(self.project.resolve()))

    def test_both_catalogue_adapters_bind_pwd(self):
        stale = self.stale_parent()
        captured = []
        identity = {"available": True, "resolved": "/fixture/opencode",
                    "version": {"text": "2.2.7", "returncode": 0}}

        def fake_bounded(argv, cwd, env, timeout, **kwargs):
            captured.append((argv, cwd, env))
            return (1, "", "")

        with patch.dict(os.environ, {"PWD": str(stale)}), \
                patch.object(orc, "_opencode_binary_identity",
                             return_value=identity), \
                patch.object(orc, "_opencode_run_bounded",
                             side_effect=fake_bounded):
            first = orc._opencode_v1_catalogue(self.project)
            second = orc._opencode_v2_catalogue(self.project)
        self.assertEqual(first["state"], "unavailable")
        self.assertEqual(second["state"], "unavailable")
        self.assertEqual(len(captured), 2)
        for _argv, cwd, env in captured:
            self.assertEqual(cwd, str(self.project))
            self.assertEqual(env["PWD"], str(self.project.resolve()))


if __name__ == "__main__":
    unittest.main()
