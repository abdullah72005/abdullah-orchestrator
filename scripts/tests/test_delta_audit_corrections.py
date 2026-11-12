"""Final delta-audit regressions: P1-01, P1-02, P1-03, P2-01, P2-02.

All model CLIs are faked or unused; no network/model calls occur.
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_orchestrator as baseline

orc = baseline.orc


def shipped_config():
    return orc.read_json(orc.HERE / "config.example.json")


def write_executable(path: Path, version: str):
    path.write_text(f"#!/bin/sh\necho {version}\n", encoding="utf-8")
    path.chmod(0o755)


class ToolchainRefreshTests(unittest.TestCase):
    """P1-01: an in-place executable upgrade must invalidate stale evidence."""

    setUp = baseline.ControlTests.setUp
    tearDown = baseline.ControlTests.tearDown

    def test_in_place_node_upgrade_invalidates_verification_evidence(self):
        bindir = self.root / "toolbin"
        bindir.mkdir()
        node = bindir / "node"
        write_executable(node, "v1.0.0")
        path_value = f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}"
        batch = {"title": "toolchain", "checks": [["git", "status", "--porcelain"]]}
        with patch.dict(os.environ, {"PATH": path_value}):
            before = orc.source_snapshot(self.project, cfg=self.cfg)
            self.assertTrue(before["toolchain"]["node"]["available"])
            evidence = orc.run_checks(
                self.rundir, self.state, self.cfg, self.project, batch)
            self.assertTrue(evidence["passed"])
            recorded = evidence["provenance"]["toolchain"]
            reference = {"path": evidence["path"], "passed": True,
                         "candidate_hash": evidence["after_hash"]}
            # Upgrade the same executable in place; PATH is unchanged.
            write_executable(node, "v2.0.0")
            bumped = node.stat().st_mtime_ns + 2_000_000
            os.utime(node, ns=(bumped, bumped))
            after = orc.source_snapshot(self.project, cfg=self.cfg)
            self.assertEqual(before["toolchain"]["path_sha256"],
                             after["toolchain"]["path_sha256"])
            self.assertNotEqual(recorded["node"], after["toolchain"]["node"])
            self.assertNotEqual(recorded["executables"]["node"],
                                after["toolchain"]["executables"]["node"])
            with self.assertRaisesRegex(ValueError, "toolchain"):
                orc.verification_evidence_package(reference, after)

    def test_replaced_check_executable_invalidates_evidence(self):
        bindir = self.root / "checkbin"
        bindir.mkdir()
        tool = bindir / "faketool"
        write_executable(tool, "ok")
        batch = {"title": "check tool", "checks": [[str(tool), "run"]]}
        evidence = orc.run_checks(
            self.rundir, self.state, self.cfg, self.project, batch)
        self.assertTrue(evidence["passed"], evidence.get("error"))
        reference = {"path": evidence["path"], "passed": True,
                     "candidate_hash": evidence["after_hash"]}
        current = orc.source_snapshot(self.project, cfg=self.cfg)
        orc.load_verification_evidence(reference, current,
                                       plan_version=self.state.get("plan_version"))
        write_executable(tool, "changed")
        bumped = tool.stat().st_mtime_ns + 2_000_000
        os.utime(tool, ns=(bumped, bumped))
        with self.assertRaisesRegex(ValueError, "toolchain drifted"):
            orc.load_verification_evidence(
                reference, orc.source_snapshot(self.project, cfg=self.cfg),
                plan_version=self.state.get("plan_version"))

    def test_cached_acceptance_decision_cannot_reuse_drifted_evidence(self):
        batch = {"title": "one", "goal": "g", "acceptance": ["works"],
                 "checks": [["git", "status", "--porcelain"]], "risk": "ordinary"}
        plan = {"contract_version": 2, "status": "complete", "summary": "p",
                "invariants": ["i"], "batches": [batch]}
        evidence = orc.run_checks(self.rundir, self.state, self.cfg,
                                  self.project, batch)
        decision_dir = self.rundir / "jobs" / "decision-final"
        decision_dir.mkdir(parents=True)
        orc.atomic_json(decision_dir / "report.json", {
            "verdict": "approved", "reason": "looks good",
            "inspected": ["app.py"], "correction": "", "dismissed_findings": []})
        self.state.update(
            phase="accept", plan=plan, plan_version=orc.content_hash(plan),
            review={"status": "complete", "summary": "review", "files": [],
                    "tests": [], "evidence": [], "unknowns": [], "blocker": "",
                    "findings": []},
            completed_jobs=[{"id": "decision-final", "kind": "decision",
                             "role": "architect", "status": "complete",
                             "path": str(decision_dir),
                             "final_snapshot": evidence["after"]}])
        orc.save(self.rundir, self.state)
        drifted = copy.deepcopy(orc.toolchain_identity())
        drifted["node"] = {"available": True, "sha256": "changed-after-check"}
        with patch.object(orc, "toolchain_identity", return_value=drifted), \
                patch.object(orc, "strong_call") as model:
            orc.advance(self.rundir, self.state, self.cfg)
        model.assert_not_called()
        # Recoverable by construction: stale evidence is discarded and the
        # approved checks are re-run instead of pausing in a dead end.
        self.assertEqual(self.state["phase"], "verify")
        self.assertIsNone(self.state.get("verification"))
        self.assertIsNone(self.state.get("review"))

    def test_legacy_toolchain_record_remains_compatible(self):
        current = orc.source_snapshot(self.project, cfg=self.cfg)["toolchain"]
        legacy = copy.deepcopy(current)
        legacy.pop("executables", None)
        legacy["python"].pop("fingerprint", None)
        recorded = {"toolchain": legacy}
        self.assertNotIn("toolchain",
                         orc.provenance_drift(recorded, {"toolchain": current}))

    def test_replaced_inode_is_detected_even_with_same_reported_version(self):
        bindir = self.root / "toolbin2"
        bindir.mkdir()
        node = bindir / "node"
        write_executable(node, "v9.9.9")
        path_value = f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}"
        with patch.dict(os.environ, {"PATH": path_value}):
            before = orc.toolchain_identity()
            replacement = bindir / "node.new"
            write_executable(replacement, "v9.9.9")
            os.replace(replacement, node)
            after = orc.toolchain_identity()
        self.assertEqual(before["node"], after["node"])
        self.assertNotEqual(before["executables"]["node"],
                            after["executables"]["node"])


class CriticalContextTests(unittest.TestCase):
    """P1-02: review findings, evidence, amendments and source identity survive."""

    setUp = baseline.ControlTests.setUp
    tearDown = baseline.ControlTests.tearDown

    def _evidence(self):
        batch = {"title": "accept", "checks": [["git", "status", "--porcelain"]]}
        evidence = orc.run_checks(self.rundir, self.state, self.cfg,
                                  self.project, batch)
        current = orc.source_snapshot(self.project, cfg=self.cfg)
        package = orc.verification_evidence_package(
            {"path": evidence["path"], "passed": True,
             "candidate_hash": evidence["after_hash"]}, current)
        return evidence, package, current

    @staticmethod
    def _findings(count=12):
        return [{
            "severity": "critical" if index == 0 else "high",
            "location": f"app.py:{index + 1}",
            "claim": f"Critical independent-review finding {index}",
            "evidence": f"observed behavior at app.py:{index + 1}",
            "confidence": "confirmed",
            "disposition": "must be corrected before acceptance",
        } for index in range(count)]

    def test_acceptance_context_preserves_review_evidence_and_amendments(self):
        evidence, package, current = self._evidence()
        findings = self._findings()
        batch_checks = [["git", "status", "--porcelain"]]
        context = {
            "run_id": "test-run00", "stage": "accept", "goal": "Ship the feature",
            "invariants": ["existing behavior stays intact"],
            "batch": {"title": "accept", "acceptance": ["feature works"],
                      "checks": batch_checks},
            "checks": batch_checks,
            "source": current,
            "snapshot": current,
            "verification": {"path": evidence["path"], "passed": True,
                             "candidate_hash": evidence["after_hash"]},
            "independent_review": {
                "contract_version": 2, "status": "complete",
                "summary": "Independent review completed",
                "files": ["app.py"], "tests": ["pytest"],
                "evidence": ["app.py:1"], "unknowns": [], "blocker": "",
                "findings": findings,
            },
            "recent_implementation": {
                "contract_version": 2, "status": "complete", "summary": "implemented",
                "files": ["app.py"], "tests": [], "evidence": ["app.py:1"],
                "unknowns": [], "blocker": "",
            },
            "verification_evidence": package,
            "verification_evidence_root": str(Path(self.rundir).resolve()),
            "correction": "MUST FIX auth bypass at app.py:42",
            "prior_attempt": {"status": "complete", "summary": "first attempt"},
            "user_amendments": [{
                "id": "amd-1", "kind": "material",
                "text": "The user requires the migration to preserve audit logs.",
            }],
            "artifacts": {
                "state": orc._run_artifact_reference(
                    self.rundir, self.rundir / "state.json"),
                "verification_record": orc._run_artifact_reference(
                    self.rundir, evidence["path"]),
            },
            "bulk_optional_blob": "x" * 250_000,
        }
        parsed = json.loads(orc._bounded_context(context, 60_000))
        self.assertEqual(parsed["goal"], "Ship the feature")
        self.assertEqual(parsed["batch"]["acceptance"], ["feature works"])
        self.assertEqual(parsed["independent_review"]["findings"], findings)
        self.assertEqual(parsed["user_amendments"][0]["text"],
                         "The user requires the migration to preserve audit logs.")
        self.assertEqual(parsed["source"]["git_head"], current["git_head"])
        runtime = parsed["source"]["runtime_inputs"]
        self.assertIn("files_sha256", runtime)
        self.assertNotIn("files", runtime)
        self.assertEqual(parsed["correction"], "MUST FIX auth bypass at app.py:42")
        self.assertEqual(parsed["prior_attempt"]["summary"], "first attempt")
        evidence_inline = parsed["verification_evidence"]
        provenance_manifest = evidence_inline["provenance"]["runtime_inputs"]
        self.assertNotIn("files", provenance_manifest)
        self.assertIn("files_sha256", provenance_manifest)
        self.assertEqual(evidence_inline["verification_path"],
                         package["verification_path"])
        self.assertEqual(evidence_inline["verification_sha256"],
                         package["verification_sha256"])
        self.assertTrue(evidence_inline["commands"])
        for command in evidence_inline["commands"]:
            log_path = Path(command["log_path"])
            self.assertTrue(log_path.is_file())
            self.assertEqual(command["log_sha256"],
                             orc.hashlib.sha256(log_path.read_bytes()).hexdigest())
        self.assertIn("detail_retrieval", evidence_inline)
        self.assertTrue(parsed["artifacts"]["state"]["valid"])
        self.assertNotIn("omitted", parsed["independent_review"])
        self.assertTrue(parsed["bulk_optional_blob"]["omitted"])
        self.assertIn("independent_review", parsed["_context_budget"][
            "mandatory_keys_preserved"])

    def test_architect_acceptance_context_exposes_review_and_evidence_artifacts(self):
        evidence, package, _current = self._evidence()
        findings = self._findings(3)
        plan = {"contract_version": 2, "status": "complete", "summary": "p",
                "invariants": ["i"], "batches": [{
                    "title": "accept", "goal": "g", "acceptance": ["works"],
                    "checks": [["git", "status", "--porcelain"]],
                    "risk": "ordinary"}]}
        review_dir = self.rundir / "jobs" / "reviewer-final"
        review_dir.mkdir(parents=True)
        review = {"contract_version": 2, "status": "complete",
                  "summary": "independent review", "files": ["app.py"],
                  "tests": [], "evidence": ["app.py:1"], "unknowns": [],
                  "blocker": "", "findings": findings}
        orc.atomic_json(review_dir / "report.json", review)
        self.state.update(
            phase="accept", plan=plan, plan_version=orc.content_hash(plan),
            review=review,
            verification={"path": evidence["path"], "passed": True,
                          "candidate_hash": evidence["after_hash"],
                          "evidence_version": evidence["evidence_version"]},
            completed_jobs=[{"id": "reviewer-final", "kind": "reviewer",
                             "role": "reviewer", "status": "complete",
                             "path": str(review_dir)}])
        orc.save(self.rundir, self.state)
        context = orc.architect_context(self.rundir, self.state, "decision")
        context["verification_evidence"] = package
        context["bulk_optional_blob"] = "x" * 150_000
        parsed = json.loads(orc._bounded_context(context, 80_000))
        self.assertEqual(parsed["independent_review"]["findings"], findings)
        self.assertTrue(parsed["artifacts"]["review_report"]["valid"])
        self.assertEqual(parsed["artifacts"]["review_report"]["path"],
                         str((review_dir / "report.json").resolve()))
        self.assertTrue(parsed["artifacts"]["verification_record"]["valid"])
        self.assertTrue(parsed["artifacts"]["state"]["valid"])
        self.assertEqual(parsed["verification_evidence"]["verification_sha256"],
                         package["verification_sha256"])

    def test_planning_context_preserves_requirements_and_plan(self):
        context = {
            "goal": "Plan a safe migration",
            "invariants": ["no data loss", "checkout lock preserved"],
            "plan": {"contract_version": 2, "status": "complete",
                     "summary": "two batches", "invariants": ["no data loss"],
                     "batches": [{"title": "one", "goal": "migrate",
                                  "acceptance": ["works"], "risk": "high",
                                  "checks": [["pytest", "-q"]]}]},
            "user_amendments": [{"id": "amd-2", "kind": "material",
                                 "text": "Keep the legacy endpoint during migration."}],
            "previous_explorer_findings": [
                {"path": f"/tmp/explore-{i}/report.json", "summary": "s" * 20_000}
                for i in range(8)],
        }
        parsed = json.loads(orc._bounded_context(context, 60_000))
        self.assertEqual(parsed["goal"], "Plan a safe migration")
        self.assertEqual(parsed["invariants"], ["no data loss", "checkout lock preserved"])
        self.assertEqual(parsed["plan"]["batches"][0]["acceptance"], ["works"])
        self.assertEqual(parsed["user_amendments"][0]["text"],
                         "Keep the legacy endpoint during migration.")
        self.assertEqual(len(parsed["previous_explorer_findings"]), 8)
        self.assertEqual(parsed["previous_explorer_findings"][0]["path"],
                         "/tmp/explore-0/report.json")

    def test_reviewing_context_keeps_verification_paths_under_large_logs(self):
        evidence, package, current = self._evidence()
        package = copy.deepcopy(package)
        # Simulate long logs without losing durable references.
        for command in package["commands"]:
            command["output_tail"] = "log line\n" * 5000
        context = {
            "batch": {"title": "review", "acceptance": ["works"]},
            # Review uses the production key "verification" for the package.
            "verification": package,
            "source": current,
            "user_amendments": [{"id": "amd-3", "text": "Reviewer must check audit logs."}],
            "unrelated_bulk": "y" * 200_000,
        }
        parsed = json.loads(orc._bounded_context(context, 60_000))
        self.assertIn("detail_retrieval", parsed["verification"])
        commands = parsed["verification"]["commands"]
        self.assertTrue(commands)
        for command in commands:
            self.assertTrue(Path(command["log_path"]).is_file())
            self.assertIn("log_sha256", command)
            self.assertLessEqual(len(command["output_tail"]), 4000)
            self.assertTrue(command.get("output_tail_truncated"))
        self.assertEqual(parsed["user_amendments"][0]["text"],
                         "Reviewer must check audit logs.")

    def test_material_amendment_is_never_replaced_by_a_hash(self):
        context = {
            "amendment": {"kind": "material", "epoch": 3},
            "goal": "Preserve behavior",
            "user_amendments": [{
                "id": "amd-4", "kind": "material", "request_kind": "requirement",
                "text": "The new requirement is mandatory: keep the audit trail.",
            }],
            "diagnosis_bulk": "z" * 200_000,
        }
        parsed = json.loads(orc._bounded_context(context, 10_000))
        self.assertEqual(parsed["amendment"]["kind"], "material")
        self.assertEqual(parsed["user_amendments"][0]["text"],
                         "The new requirement is mandatory: keep the audit trail.")
        self.assertTrue(parsed["diagnosis_bulk"]["omitted"])

    def test_approved_handoff_source_is_condensed_but_plan_is_preserved(self):
        current = orc.source_snapshot(self.project, cfg=self.cfg)
        handoff = {
            "goal": "Implement the handoff",
            "provenance": "snapshot at approval",
            "architectural_decisions": "keep the public API",
            "execution_restrictions": "no new dependencies",
            "source": current,
            "plan": {"contract_version": 2, "status": "complete",
                     "invariants": ["keep behavior"],
                     "batches": [{"title": "one", "goal": "g",
                                  "acceptance": ["works"],
                                  "checks": [["git", "status", "--porcelain"]]}]},
        }
        parsed = json.loads(orc._bounded_context(
            {"approved_handoff": handoff, "goal": "Implement the handoff",
             "bulk": "q" * 100_000}, 20_000))
        source = parsed["approved_handoff"]["source"]
        self.assertEqual(source["git_head"], current["git_head"])
        self.assertNotIn("files", source["runtime_inputs"])
        self.assertEqual(
            parsed["approved_handoff"]["plan"]["invariants"], ["keep behavior"])

    def test_large_dirty_tree_is_condensed_not_failed_closed(self):
        current = orc.source_snapshot(self.project, cfg=self.cfg)
        big = copy.deepcopy(current)
        big["changed"] = {f"src/generated_{i}.py": f"{i:064x}"
                          for i in range(500)}
        context = {
            "goal": "accept a large refactor",
            "snapshot": big,
            "verification_evidence": {
                "package_version": 2, "commands": [],
                "candidate": big, "after": big,
                "provenance": {"source": big},
            },
        }
        parsed = json.loads(orc._bounded_context(context, 80_000))
        changed = parsed["snapshot"]["changed"]
        self.assertEqual(changed["changed_count"], 500)
        self.assertIn("changed_sha256", changed)
        self.assertNotIn("src/generated_0.py", changed)
        self.assertEqual(
            parsed["verification_evidence"]["candidate"]["changed"]["changed_count"],
            500)

    def test_previous_explorer_findings_keep_paths_and_bounded_summaries(self):
        reports = [{"path": f"/tmp/explore-{i}/report.json",
                    "summary": "s" * 20_000, "status": "complete",
                    "evidence": [f"app.py:{j}" for j in range(150)]}
                   for i in range(8)]
        parsed = json.loads(orc._bounded_context({
            "goal": "plan from exploration",
            "previous_explorer_findings": reports,
            "bulk": "x" * 100_000,
        }, 60_000))
        kept = parsed["previous_explorer_findings"]
        self.assertEqual(len(kept), 8)
        self.assertEqual(kept[0]["path"], "/tmp/explore-0/report.json")
        self.assertTrue(kept[0]["summary_truncated"])
        self.assertEqual(kept[0]["evidence_omitted_count"], 50)

    def test_small_optional_stage_inputs_stay_inline(self):
        parsed = json.loads(orc._bounded_context({
            "goal": "g",
            "user_requested_plan_approval": True,
            "exploration_required": False,
            "bulk": "b" * 100_000,
        }, 5_000))
        self.assertIs(parsed["user_requested_plan_approval"], True)
        self.assertIs(parsed["exploration_required"], False)
        self.assertTrue(parsed["bulk"]["omitted"])

    def test_mandatory_evidence_over_budget_fails_closed(self):
        with self.assertRaisesRegex(ValueError,
                                    "Essential handoff context exceeds"):
            orc._bounded_context({
                "goal": "g",
                "user_amendments": [{"id": "amd-5", "text": "q" * 80_000}],
            }, 2_000)
        with self.assertRaisesRegex(ValueError, "independent_review"):
            orc._bounded_context({
                "goal": "g",
                "independent_review": {"findings": [
                    {"claim": "c" * 80_000}]},
            }, 2_000)

    def test_artifact_reference_rejects_paths_outside_run_directory(self):
        inside = self.rundir / "state.json"
        self.assertTrue(inside.is_file())
        self.assertTrue(orc._run_artifact_reference(self.rundir, inside)["valid"])
        outside = self.root / "outside.json"
        outside.write_text("{}")
        reference = orc._run_artifact_reference(self.rundir, outside)
        self.assertFalse(reference["valid"])
        self.assertIn("outside", reference["reason"])


class EffectivePermissionTests(unittest.TestCase):
    """P1-03: V2 Doctor must evaluate ordered last-match rules."""

    def test_generated_profiles_remain_valid(self):
        for role in ("explorer", "implementer", "reviewer"):
            with self.subTest(role=role):
                self.assertTrue(orc.validate_v2_effective_permissions(
                    role, orc.opencode_profile(role, "v2")["permissions"]))

    def test_later_allow_defeating_a_deny_is_rejected(self):
        for role in ("explorer", "reviewer", "implementer"):
            with self.subTest(role=role):
                rules = copy.deepcopy(orc.opencode_profile(role, "v2")["permissions"])
                rules.append({"action": "*", "resource": "*", "effect": "allow"})
                with self.assertRaisesRegex(ValueError, "not restrictive enough"):
                    orc.validate_v2_effective_permissions(role, rules)

    def test_overlapping_later_allow_for_secret_env_is_rejected(self):
        rules = copy.deepcopy(orc.opencode_profile("explorer", "v2")["permissions"])
        rules.append({"action": "read", "resource": "*", "effect": "allow"})
        self.assertEqual(orc.v2_effective_permission(rules, "read", ".env"), "allow")
        with self.assertRaisesRegex(ValueError, "read:.*env"):
            orc.validate_v2_effective_permissions("explorer", rules)

    def test_narrow_later_allow_below_a_universal_deny_is_rejected(self):
        rules = copy.deepcopy(orc.opencode_profile("reviewer", "v2")["permissions"])
        rules.append({"action": "edit", "resource": "src/*", "effect": "allow"})
        with self.assertRaisesRegex(ValueError, "edit:src/\\*"):
            orc.validate_v2_effective_permissions("reviewer", rules)

    def test_unenumerated_action_allow_is_rejected(self):
        for role, action in (("explorer", "write"), ("reviewer", "patch"),
                             ("explorer", "list"), ("reviewer", "task")):
            with self.subTest(role=role, action=action):
                rules = copy.deepcopy(
                    orc.opencode_profile(role, "v2")["permissions"])
                rules.append({"action": action, "resource": "*",
                              "effect": "allow"})
                with self.assertRaisesRegex(ValueError, "not restrictive enough"):
                    orc.validate_v2_effective_permissions(role, rules)

    def test_narrow_shell_allow_outside_probe_list_is_rejected(self):
        rules = copy.deepcopy(
            orc.opencode_profile("implementer", "v2")["permissions"])
        rules.append({"action": "shell", "resource": "git push --force*",
                      "effect": "allow"})
        self.assertEqual(
            orc.v2_effective_permission(rules, "shell", "git push --force origin main"),
            "allow")
        with self.assertRaisesRegex(ValueError, "not restrictive enough"):
            orc.validate_v2_effective_permissions("implementer", rules)

    def test_universal_allow_appended_after_intended_shell_denies_is_rejected(self):
        rules = copy.deepcopy(
            orc.opencode_profile("implementer", "v2")["permissions"])
        rules.append({"action": "shell", "resource": "*", "effect": "allow"})
        with self.assertRaisesRegex(ValueError, "not restrictive enough"):
            orc.validate_v2_effective_permissions("implementer", rules)

    def test_invalid_effect_and_missing_deny_fail(self):
        rules = copy.deepcopy(orc.opencode_profile("explorer", "v2")["permissions"])
        rules.append({"action": "edit", "resource": "*", "effect": "maybe"})
        with self.assertRaisesRegex(ValueError, "invalid ordered permissions"):
            orc.validate_v2_effective_permissions("explorer", rules)
        with self.assertRaisesRegex(ValueError, "invalid ordered permissions"):
            orc.validate_v2_effective_permissions("explorer", [])

    def test_doctor_probe_uses_effective_rules_not_set_membership(self):
        role = "explorer"
        rules = copy.deepcopy(orc.opencode_profile(role, "v2")["permissions"])
        rules.append({"action": "*", "resource": "*", "effect": "allow"})
        payload = json.dumps([{
            "id": f"abdullah-{role}", "mode": "primary",
            "system": orc.role_text(role),
            "description": orc.opencode_profile(role, "v2")["description"],
            "permissions": rules}])
        with patch.object(orc.subprocess, "run",
                          return_value=subprocess.CompletedProcess([], 0, stdout=payload)):
            self.assertIs(orc.probe_opencode_config(Path("/tmp"), role, "v2"), False)

    def test_doctor_probe_accepts_real_rule_order(self):
        role = "implementer"
        rules = copy.deepcopy(orc.opencode_profile(role, "v2")["permissions"])
        # The real CLI prepends global defaults before the agent rules.
        rules = [{"action": "*", "resource": "*", "effect": "allow"},
                 {"action": "read", "resource": "*.env", "effect": "ask"}] + rules
        payload = json.dumps([{
            "id": f"abdullah-{role}", "mode": "primary",
            "system": orc.role_text(role),
            "description": orc.opencode_profile(role, "v2")["description"],
            "permissions": rules}])
        with patch.object(orc.subprocess, "run",
                          return_value=subprocess.CompletedProcess([], 0, stdout=payload)):
            self.assertIs(orc.probe_opencode_config(Path("/tmp"), role, "v2"), True)


class PartialTokenTotalTests(unittest.TestCase):
    """P2-01: never present an incomplete derived total as complete."""

    @staticmethod
    def step(tokens, part_id="prt"):
        event = {"type": "step_finish", "timestamp": 1, "sessionID": "ses",
                 "part": {"id": part_id, "type": "step-finish", "tokens": tokens}}
        return json.dumps(event)

    def test_partial_v2_step_is_preserved_but_marked_partial(self):
        usage = orc.extract_reported_usage(
            self.step({"input": 10, "cache": {"read": 3}}), "jsonl")
        self.assertEqual(usage["tokens"], 13)
        self.assertEqual(usage["input_tokens"], 10)
        self.assertIsNone(usage["output_tokens"])
        self.assertEqual(usage["total_status"], "partial")

    def test_complete_derived_and_explicit_totals_are_distinguished(self):
        derived = orc.extract_reported_usage(
            self.step({"input": 10, "output": 5, "reasoning": 0,
                       "cache": {"read": 0, "write": 0}}), "jsonl")
        self.assertEqual(derived["tokens"], 15)
        self.assertEqual(derived["total_status"], "derived")
        explicit = orc.extract_reported_usage(
            self.step({"total": 999, "input": 10}), "jsonl")
        self.assertEqual(explicit["tokens"], 999)
        self.assertEqual(explicit["total_status"], "reported")

    def test_generic_partial_total_keeps_components_and_status(self):
        usage = orc.extract_reported_usage(
            json.dumps({"usage": {"input_tokens": 10, "output_tokens": 5}}),
            "claude")
        self.assertEqual(usage["tokens"], 15)
        self.assertEqual(usage["total_status"], "partial")
        reported = orc.extract_reported_usage(
            json.dumps({"usage": {"total_tokens": 7}}), "jsonl")
        self.assertEqual(reported["total_status"], "reported")

    def test_legacy_unknown_status_is_not_presented_as_complete(self):
        state = {}
        job = {"role": "explorer", "route": {"billing": "go"},
               "reported_usage": {"tokens": 100}}
        orc.record_usage(state, job, "complete", 1)
        self.assertEqual(state["usage"]["reported_tokens"], 100)
        self.assertEqual(state["usage"]["reported_tokens_status"], "partial")
        merged = {}
        orc.merge_usage(merged, {"reported_tokens": 50})
        self.assertEqual(merged["usage"]["reported_tokens"], 50)
        self.assertEqual(merged["usage"]["reported_tokens_status"], "partial")
        self.assertIn("tokens=100(partial)", orc.usage_line(state["usage"]))

    def test_usage_report_aggregates_partial_status_without_inventing_quota(self):
        state = {}
        reported = {"role": "explorer", "route": {"billing": "go"},
                    "reported_usage": {"tokens": 7, "total_status": "reported"}}
        partial = {"role": "explorer", "route": {"billing": "go"},
                   "reported_usage": {"tokens": 3, "total_status": "partial"}}
        orc.record_usage(state, reported, "complete", 1)
        orc.record_usage(state, partial, "complete", 1)
        usage = orc.usage_report(state)
        self.assertEqual(usage["reported_tokens"], 10)
        self.assertEqual(usage["reported_tokens_status"], "partial")
        self.assertNotIn("quota", json.dumps(usage.get("billing")))
        self.assertIn("not inferred", usage["note"])


class ScopedExceptionTests(unittest.TestCase):
    """P2-02: scoped exceptions fail closed without a project identity."""

    def test_scoped_exception_requires_project(self):
        cfg = shipped_config()
        cfg["verification"]["command_policy"]["exceptions"] = [{
            "argv_regex": r'.*"bash","-lc","pytest -q".*',
            "reason": "legacy wrapper for one project",
            "scope": "/tmp/project-a",
            "authorized_by": "ops",
        }]
        without_project = orc.verification_command_policy(
            ["bash", "-lc", "pytest -q"], cfg)
        self.assertFalse(without_project["allowed"], without_project)
        self.assertNotEqual(without_project["policy"], "exception")
        allowed = orc.verification_command_policy(
            ["bash", "-lc", "pytest -q"], cfg, project=Path("/tmp/project-a"))
        self.assertTrue(allowed["allowed"])

    def test_global_exception_still_applies_without_project(self):
        cfg = shipped_config()
        cfg["verification"]["command_policy"]["exceptions"] = [{
            "argv_regex": r'.*"bash","-lc","pytest -q".*',
            "reason": "explicitly global operator exception",
            "scope": "*",
            "authorized_by": "ops",
        }]
        self.assertTrue(orc.verification_command_policy(
            ["bash", "-lc", "pytest -q"], cfg)["allowed"])


if __name__ == "__main__":
    unittest.main()
