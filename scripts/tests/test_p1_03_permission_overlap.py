"""P1-03: V2 Doctor must reject wildcard overlaps that defeat mandatory denies.

These regressions are independent of the finite sample filenames used by the
historical checks. They exercise the ordered normalized rule list the installed
OpenCode V2 CLI actually returns.
"""
from __future__ import annotations

import copy
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import test_orchestrator as baseline

orc = baseline.orc
FIXTURE = Path(__file__).parent / "fixtures" / "opencode-v2.2.7-normalized-permissions.json"
ROLES = ("explorer", "implementer", "reviewer")


def profile(role):
    return copy.deepcopy(orc.opencode_profile(role, "v2")["permissions"])


def appended(role, action, resource, effect="allow"):
    rules = profile(role)
    rules.append({"action": action, "resource": resource, "effect": effect})
    return rules


def genuine_v227(role):
    with FIXTURE.open(encoding="utf-8") as handle:
        return copy.deepcopy(json.load(handle)["roles"][role])


class OverlapRejectionTests(unittest.TestCase):
    def assert_rejected(self, role, rules):
        with self.assertRaisesRegex(ValueError, "not restrictive enough"):
            orc.validate_v2_effective_permissions(role, rules)

    def test_later_broad_allow_overriding_earlier_deny_is_rejected(self):
        for role in ROLES:
            with self.subTest(role=role):
                self.assert_rejected(
                    role, appended(role, "*", "*", "allow"))

    def test_read_src_star_overlaps_nested_secret_file(self):
        for role in ROLES:
            with self.subTest(role=role):
                rules = appended(role, "read", "src/*")
                self.assertEqual(
                    orc.v2_effective_permission(rules, "read", "src/.env.secret"),
                    "allow")
                self.assert_rejected(role, rules)

    def test_read_secret_directory_star_overlaps_env(self):
        for role in ROLES:
            with self.subTest(role=role):
                rules = appended(role, "read", "src/secret/*")
                self.assertEqual(
                    orc.v2_effective_permission(rules, "read", "src/secret/.env"),
                    "allow")
                self.assert_rejected(role, rules)

    def test_read_private_star_overlaps_env(self):
        for role in ROLES:
            with self.subTest(role=role):
                rules = appended(role, "read", "private/*")
                self.assertEqual(
                    orc.v2_effective_permission(rules, "read", "private/.env"),
                    "allow")
                self.assert_rejected(role, rules)

    def test_nested_secret_at_previously_unenumerated_path_is_rejected(self):
        path = "deep/unenumerated/tree/.env.production"
        for role in ROLES:
            with self.subTest(role=role):
                rules = appended(role, "read", "deep/unenumerated/tree/*")
                self.assertEqual(
                    orc.v2_effective_permission(rules, "read", path), "allow")
                self.assertNotIn(path, orc.V2_SECRET_RESOURCES)
                self.assert_rejected(role, rules)

    def test_wildcard_overlap_edge_cases_are_fail_closed(self):
        resources = (
            "*env*", "?.env", "**/*.env", "src/**/.env*", "*.env.example.bak",
            "[a-z]*.env", "src/.*",
        )
        for resource in resources:
            for role in ROLES:
                with self.subTest(role=role, resource=resource):
                    self.assert_rejected(role, appended(role, "read", resource))

    def test_overlap_prover_only_declares_provable_disjointness(self):
        self.assertTrue(orc._v2_glob_overlap("*.env", "src/*"))
        self.assertTrue(orc._v2_glob_overlap("?.env", "*.env"))
        self.assertTrue(orc._v2_glob_overlap("a*", "*b"))
        self.assertTrue(orc._v2_glob_overlap("*", "anything"))
        self.assertFalse(orc._v2_glob_overlap("*.env", "*.py"))
        self.assertFalse(orc._v2_glob_overlap("src/*.py", "tests/*.py"))
        self.assertFalse(orc._v2_glob_overlap("a*", "b*"))
        self.assertFalse(orc._v2_glob_overlap("?.env", ".env"))

    def test_overlap_prover_models_opencode_optional_trailing_space(self):
        # OpenCode rewrites "git push *" to also match "git push".
        self.assertTrue(orc._v2_glob_overlap("git push *", "git push"))
        self.assertTrue(orc._v2_glob_overlap("git clean *", "git clean"))
        self.assertFalse(orc._v2_glob_overlap("git push *", "git clean"))

    def test_later_ask_overriding_mandatory_deny_is_rejected(self):
        for role in ROLES:
            for resource in ("*.env", "*.env.*", ".env.production"):
                with self.subTest(role=role, resource=resource):
                    self.assert_rejected(
                        role, appended(role, "read", resource, "ask"))

    def test_unrecognized_action_names_are_rejected(self):
        for role in ROLES:
            for action in ("write", "patch", "task", "list", "future_tool"):
                with self.subTest(role=role, action=action):
                    self.assert_rejected(
                        role, appended(role, action, "*", "allow"))
                with self.subTest(role=role, action=action, effect="deny"):
                    self.assert_rejected(
                        role, appended(role, action, "*", "deny"))

    def test_dangerous_shell_overlap_is_rejected_without_sample_commands(self):
        cases = (("git push --force*", "git push --force origin main"),
                 ("docker * down *", "docker compose down -v"),
                 ("git reset*", "git reset --hard HEAD"))
        for resource, command in cases:
            with self.subTest(resource=resource):
                rules = appended("implementer", "shell", resource)
                self.assertEqual(
                    orc.v2_effective_permission(rules, "shell", command),
                    "allow")
                self.assert_rejected("implementer", rules)

    def test_reordered_or_contradictory_sequence_is_rejected(self):
        rules = profile("explorer")
        rules.reverse()
        self.assert_rejected("explorer", rules)
        rules = profile("reviewer")
        rules[-1] = {"action": "read", "resource": "*.env.example",
                     "effect": "deny"}
        self.assert_rejected("reviewer", rules)
        rules = profile("implementer")
        rules[0] = {"action": "*", "resource": "*", "effect": "deny"}
        self.assert_rejected("implementer", rules)

    def test_repo_controlled_oversized_pattern_fails_closed(self):
        resource = "a" * 900 + "*"
        self.assertTrue(orc._v2_glob_overlap(resource, "*"))
        self.assert_rejected("explorer", appended("explorer", "read", resource))

    def test_malformed_or_missing_permissions_are_rejected(self):
        for role in ROLES:
            for rules in (None, [], [{"action": "read"}],
                          [{"action": "read", "resource": "*",
                            "effect": "maybe"}]):
                with self.subTest(role=role, rules=rules):
                    with self.assertRaises(ValueError):
                        orc.validate_v2_effective_permissions(role, rules)


class CompatibilityTests(unittest.TestCase):
    def test_known_opencode_v227_profiles_are_accepted(self):
        for role in ROLES:
            with self.subTest(role=role):
                self.assertTrue(orc.validate_v2_effective_permissions(
                    role, genuine_v227(role)))

    def test_generated_profiles_are_accepted(self):
        for role in ROLES:
            with self.subTest(role=role):
                self.assertTrue(orc.validate_v2_effective_permissions(
                    role, profile(role)))

    def test_deny_only_hardening_is_accepted(self):
        for role in ROLES:
            with self.subTest(role=role):
                rules = profile(role)
                rules.append({"action": "read", "resource": "*.pem",
                              "effect": "deny"})
                self.assertTrue(orc.validate_v2_effective_permissions(role, rules))


class DoctorProbeTests(unittest.TestCase):
    def probe(self, role, permissions, system=None, description=None, agent_id=None):
        agent = {"id": agent_id or f"abdullah-{role}", "mode": "primary",
                 "system": system if system is not None else orc.role_text(role),
                 "description": description if description is not None
                 else orc.opencode_profile(role, "v2")["description"],
                 "permissions": permissions}
        payload = json.dumps([agent])
        with patch.object(
                orc.subprocess, "run",
                return_value=subprocess.CompletedProcess([], 0, stdout=payload)):
            return orc.probe_opencode_config(Path("/tmp"), role, "v2")

    def test_doctor_accepts_only_safe_normalized_output(self):
        for role in ROLES:
            with self.subTest(role=role):
                self.assertIs(self.probe(role, genuine_v227(role)), True)
                self.assertIs(self.probe(role, profile(role)), True)
                unsafe = copy.deepcopy(genuine_v227(role))
                unsafe.append({"action": "read", "resource": "src/*",
                               "effect": "allow"})
                self.assertIs(self.probe(role, unsafe), False)

    def test_doctor_rejects_malformed_or_missing_normalized_permissions(self):
        for role in ROLES:
            with self.subTest(role=role, case="missing"):
                self.assertIs(self.probe(role, None), False)
            with self.subTest(role=role, case="empty"):
                self.assertIs(self.probe(role, []), False)
            with self.subTest(role=role, case="bad-effect"):
                self.assertIs(self.probe(
                    role, [{"action": "read", "resource": "*",
                            "effect": "maybe"}]), False)
            with self.subTest(role=role, case="unknown-action"):
                bad = genuine_v227(role)
                bad.append({"action": "future_tool", "resource": "*",
                            "effect": "allow"})
                self.assertIs(self.probe(role, bad), False)

    def test_doctor_rejects_ambiguous_or_malformed_payloads(self):
        role = "explorer"
        good = genuine_v227(role)
        malformed = (
            json.dumps({"agents": []}),
            json.dumps(["not-an-agent"]),
            json.dumps([{"id": f"abdullah-{role}", "mode": "primary",
                         "system": orc.role_text(role),
                         "description": f"Abdullah {role}, tracked external worker",
                         "permissions": good},
                        {"id": f"abdullah-{role}", "mode": "primary",
                         "system": orc.role_text(role),
                         "description": f"Abdullah {role}, tracked external worker",
                         "permissions": good + [{"action": "read",
                                                 "resource": "src/*",
                                                 "effect": "allow"}]}]),
        )
        for payload in malformed:
            with self.subTest(payload=payload[:40]):
                with patch.object(
                        orc.subprocess, "run",
                        return_value=subprocess.CompletedProcess(
                            [], 0, stdout=payload)):
                    self.assertIs(
                        orc.probe_opencode_config(Path("/tmp"), role, "v2"), False)

    def test_doctor_rejects_wrong_policy_identity(self):
        role = "explorer"
        self.assertIs(self.probe(role, genuine_v227(role),
                                 system="permissive policy"), False)
        self.assertIs(self.probe(role, genuine_v227(role),
                                 description="permissive role"), False)
        self.assertIs(self.probe(role, genuine_v227(role),
                                 agent_id="abdullah-someone-else"), False)

    def test_doctor_rejects_oversized_pattern_without_crashing(self):
        role = "explorer"
        unsafe = genuine_v227(role)
        unsafe.append({"action": "read", "resource": "a" * 900 + "*",
                       "effect": "allow"})
        self.assertIs(self.probe(role, unsafe), False)

    def test_doctor_rejects_later_ask_and_broad_allow(self):
        for role in ROLES:
            for rule in ({"action": "read", "resource": "*.env",
                          "effect": "ask"},
                         {"action": "*", "resource": "*", "effect": "allow"}):
                with self.subTest(role=role, rule=rule):
                    unsafe = copy.deepcopy(genuine_v227(role))
                    unsafe.append(rule)
                    self.assertIs(self.probe(role, unsafe), False)


if __name__ == "__main__":
    unittest.main()
