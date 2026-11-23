"""Release-closure gates: config policy, model metadata and role switching.

All checks are local and deterministic.  Fake CLIs establish adapter parsing;
a separate operator smoke exercises the real authenticated Reviewer route.
"""
from __future__ import annotations

import contextlib
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest
from unittest.mock import patch

import test_v120_release_workflow as release
import test_orchestrator as baseline

orc = release.orc
ReleaseFixture = release.ReleaseFixture

FAKE_CODEX = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import json, sys
    if "--version" in sys.argv:
        print("codex-cli 0.169.1")
        raise SystemExit(0)
    if "app-server" not in sys.argv:
        raise SystemExit(3)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        message = json.loads(line)
        method = message.get("method")
        if method == "initialize":
            print(json.dumps({"id": message["id"], "result": {}}), flush=True)
        elif method == "model/list":
            cursor = (message.get("params") or {}).get("cursor")
            if cursor == "page-2":
                models = [{"id": "gpt-page-two", "model": "gpt-page-two",
                           "supportedReasoningEfforts": [
                               {"reasoningEffort": "high"}]}]
                result = {"data": models, "nextCursor": None}
            else:
                models = [{"id": "gpt-any-9.9", "model": "gpt-any-9.9",
                           "supportedReasoningEfforts": [
                               {"reasoningEffort": "low"},
                               {"reasoningEffort": "medium"},
                               {"reasoningEffort": "high"}]},
                          {"id": "gpt-6.2-sol", "model": "gpt-6.2-sol",
                           "supportedReasoningEfforts": [
                               {"reasoningEffort": "medium"},
                               {"reasoningEffort": "high"}]}]
                result = {"data": models, "nextCursor": "page-2"}
            print(json.dumps({"id": message["id"], "result": result}), flush=True)
    """)


FAKE_OPENCODE = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import json, sys
    args = sys.argv[1:]
    if "--version" in args:
        print("v2.2.7")
        raise SystemExit(0)
    if args[:1] == ["api"]:
        print(json.dumps({"data": [
            {"id": "deepseek-v4.1-flash", "modelID": "deepseek-v4.1-flash",
             "providerID": "opencode-go", "enabled": True,
             "variants": [{"id": "low"}, {"id": "high"}, {"id": "max"}]},
            {"id": "disabled-model", "modelID": "disabled-model",
             "providerID": "opencode-go", "enabled": False,
             "variants": [{"id": "high"}]}]}))
        raise SystemExit(0)
    print("{}")
    """)


def write_fake(directory: Path, name: str, body: str):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(body)
    path.chmod(0o755)
    return path


def confirmed(model="gpt-any-9.9", variants=("low", "medium", "high")):
    return {"state": "confirmed", "source": "test", "detail": "fixture",
            "version": "test", "models": {
                model: {"id": model, "provider": None,
                        "variants": list(variants)}}}


class ConfigPolicyTests(ReleaseFixture):
    def policy_state(self, cfg=None):
        cfg = cfg or self.cfg
        observed = orc.observe_configuration()
        return self.state(
            config_sha256=observed["raw_sha256"],
            config_policy={**observed["policy"], "source": "run_creation"},
            model_routes={role: orc.model_route(cfg, "codex", role,
                                                project=self.project)
                          for role in ("architect", "explorer", "implementer",
                                       "reviewer")})

    def test_preference_only_change_keeps_semantic_policy_and_run_current(self):
        state = self.policy_state()
        before = state["config_policy"]["sha256"]
        cfg = copy.deepcopy(self.cfg)
        cfg["architect"]["codex"]["model"] = "gpt-6.1-sol"
        cfg["workers"]["implementer"]["variant"] = "low"
        cfg["workers"]["reviewer"]["model"] = "opencode-go/another-reviewer"
        cfg["workers"]["reviewer"]["provider"] = "opencode-go"
        cfg["workers"]["reviewer"]["billing"] = "go"
        after = orc.config_policy_fingerprint(cfg)["sha256"]
        self.assertEqual(before, after)
        self.assertEqual(orc.state_compatibility(state)["status"], "current")

    def test_formatting_only_change_keeps_policy_and_verification_equivalent(self):
        recorded_view = orc.configuration_provenance(self.cfg)["policy"]
        path = self.cfg_path
        path.write_text(json.dumps(self.cfg, indent=8, sort_keys=False) + "\n\n")
        current_view = orc.configuration_provenance()["policy"]
        self.assertEqual(recorded_view["sha256"], current_view["sha256"])
        drift = orc.provenance_drift(
            {"configuration": {"policy": recorded_view}, "environment": {},
             "toolchain": {}, "runtime_inputs": {}},
            {"configuration": {"policy": current_view}, "environment": {},
             "toolchain": {}, "runtime_inputs": {}})
        self.assertEqual(drift, [])

    def test_stage_observation_binds_policy_not_a_later_file_read(self):
        old_cfg = copy.deepcopy(self.cfg)
        recorded = orc.source_snapshot(self.project, cfg=old_cfg)
        changed = copy.deepcopy(self.cfg)
        changed["limits"]["max_stage_seconds"] = 4599
        orc.atomic_json(self.cfg_path, changed)
        current = orc.source_snapshot(self.project, cfg=changed)
        self.assertNotEqual(recorded["configuration"]["policy"]["sha256"],
                            current["configuration"]["policy"]["sha256"])
        self.assertIn("configuration",
                      orc.provenance_drift(recorded, current))
        # Passing the stage's parsed config records that policy, not the
        # later file contents, so a mid-stage policy edit cannot be laundered.
        self.assertEqual(
            recorded["configuration"]["policy"]["sha256"],
            orc.config_policy_fingerprint(old_cfg)["sha256"])

    def test_genuine_policy_change_still_blocks(self):
        state = self.policy_state()
        cfg = copy.deepcopy(self.cfg)
        cfg["limits"]["max_stage_seconds"] = 1234
        orc.atomic_json(self.cfg_path, cfg)
        result = orc.state_compatibility(state)
        self.assertEqual(result["status"], "config_changed")
        self.assertTrue(result["migration_required"])

    def test_unknown_key_is_fail_closed(self):
        before = orc.config_policy_fingerprint(self.cfg)["sha256"]
        cfg = copy.deepcopy(self.cfg)
        cfg["future_policy"] = {"enabled": True}
        self.assertNotEqual(before, orc.config_policy_fingerprint(cfg)["sha256"])

    def test_old_run_keeps_pinned_routes_and_evidence_after_new_default(self):
        observed = orc.observe_configuration()
        old_routes = {role: orc.model_route(self.cfg, "codex", role,
                                            project=self.project)
                      for role in ("architect", "explorer", "implementer",
                                   "reviewer")}
        state = self.state(config_sha256=observed["raw_sha256"],
                           config_policy={**observed["policy"],
                                          "source": "run_creation"},
                           model_routes=old_routes)
        cfg = copy.deepcopy(self.cfg)
        cfg["architect"]["codex"]["model"] = "gpt-6.2-sol"
        cfg["workers"]["reviewer"]["model"] = "opencode-go/reviewer-v2"
        cfg["workers"]["reviewer"]["provider"] = "opencode-go"
        cfg["workers"]["reviewer"]["billing"] = "go"
        orc.atomic_json(self.cfg_path, cfg)
        self.assertEqual(orc.state_compatibility(state)["status"], "current")
        orc.assert_state_compatible(state)
        self.assertEqual(state["model_routes"]["architect"]["model"],
                         old_routes["architect"]["model"])
        recorded = {"policy": observed["policy"]}
        current = {"policy": orc.configuration_provenance()["policy"]}
        self.assertEqual(orc.provenance_drift(
            {"configuration": recorded, "environment": {}, "toolchain": {},
             "runtime_inputs": {}},
            {"configuration": current, "environment": {}, "toolchain": {},
             "runtime_inputs": {}}), [])

    def test_legacy_matching_raw_digest_adopts_without_changing_routes(self):
        observed = orc.observe_configuration()
        routes = {role: orc.model_route(self.cfg, "codex", role,
                                        project=self.project)
                  for role in ("architect", "explorer", "implementer",
                               "reviewer")}
        state = self.state(config_sha256=observed["raw_sha256"],
                           model_routes=routes)
        result = orc.state_compatibility(state)
        self.assertEqual(result["status"], "current")
        self.assertEqual(result["config_policy_upgrade"], "matching_raw_digest")
        orc.save(self.rundir, state)
        saved = orc.read_json(self.rundir / "state.json")
        self.assertEqual(saved["config_policy"]["sha256"],
                         observed["policy"]["sha256"])
        self.assertEqual(saved["model_routes"], routes)

    def test_legacy_unknown_old_config_digest_fails_closed(self):
        state = self.state(config_sha256="0" * 64)
        result = orc.state_compatibility(state)
        self.assertEqual(result["status"], "config_changed")
        self.assertEqual(result["config_policy_upgrade"], "unproven_old_config")

    def test_operator_adoption_requires_exact_old_bytes_and_is_backup_first(self):
        observed = orc.observe_configuration()
        state = self.state(config_sha256=observed["raw_sha256"])
        orc.save(self.rundir, state)
        saved = orc.read_json(self.rundir / "state.json")
        saved.pop("config_policy", None)
        orc.atomic_json(self.rundir / "state.json", saved)
        other = copy.deepcopy(self.cfg)
        other["limits"]["max_stage_seconds"] = 4321
        wrong = self.root / "wrong.json"
        orc.atomic_json(wrong, other)
        with patch.object(orc, "_operator_action_allowed", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "does not match"):
                orc.adopt_config_policy_run("test-v12000", str(wrong),
                                            "kept a backup")
            unchanged = orc.read_json(self.rundir / "state.json")
            self.assertNotIn("config_policy", unchanged)
            result = orc.adopt_config_policy_run(
                "test-v12000", str(self.cfg_path),
                "old config retained at /backup")
        self.assertTrue(result["equivalent_to_current"])
        adopted = orc.read_json(self.rundir / "state.json")
        self.assertEqual(adopted["config_policy"]["source"],
                         "operator_old_config")
        self.assertTrue(Path(result["backup"], "state.json").is_file())
        self.assertEqual(adopted["model_routes"], saved["model_routes"])

    def test_attested_old_policy_still_fails_when_policy_really_differs(self):
        state = self.policy_state()
        cfg = copy.deepcopy(self.cfg)
        cfg["verification"]["require_checks"] = True
        cfg["limits"]["max_stage_seconds"] = 9999
        old_sha = state["config_policy"]["sha256"]
        orc.atomic_json(self.cfg_path, cfg)
        new_sha = orc.configuration_provenance()["policy"]["sha256"]
        self.assertNotEqual(old_sha, new_sha)
        self.assertEqual(orc.state_compatibility(state)["status"],
                         "config_changed")

    def test_host_fallback_consent_is_bound_to_the_pinned_route(self):
        observed = orc.observe_configuration()
        fallback = {"provider": "codex", "model": "gpt-pinned-fallback",
                    "effort": "medium", "billing": "subscription"}
        state = self.state(config_sha256=observed["raw_sha256"],
                           config_policy={**observed["policy"],
                                          "source": "run_creation"},
                           host_fallback_route=fallback,
                           role_generations={"architect": 0})
        cfg = copy.deepcopy(self.cfg)
        cfg["fallback"]["enabled"] = False
        cfg["fallback"]["codex"] = {"model": "gpt-later-default",
                                    "effort": "high"}
        orc.atomic_json(self.cfg_path, cfg)
        resolved = orc.effective_route(state, "architect")
        self.assertEqual(resolved["configured"]["model"],
                         self.cfg["architect"]["codex"]["model"])
        # Consent recorded for a different route is refused before any spawn.
        wrong = {"role": "architect", "approved_at": "now", "limit": "one dispatch",
                 "route_sha256": orc.route_authorization_sha(
                     {"provider": "codex", "model": "gpt-later-default",
                      "effort": "high", "billing": "subscription"}),
                 "role_generation": 0}
        state["fallback_authorization"] = wrong
        with patch.object(orc, "_spawn_guarded") as spawn:
            with self.assertRaisesRegex(RuntimeError, "does not match the exact"):
                orc.call_model(self.rundir, state, self.cfg, "architect", "plan",
                               "prompt", self.project)
        spawn.assert_not_called()
        # A consent from an older role generation is also refused.
        state["fallback_authorization"] = {
            **wrong,
            "route_sha256": orc.route_authorization_sha(
                {"provider": "codex", "model": "gpt-pinned-fallback",
                 "effort": "medium", "billing": "subscription"}),
            "role_generation": 1}
        with patch.object(orc, "_spawn_guarded") as spawn:
            with self.assertRaisesRegex(RuntimeError, "earlier role generation"):
                orc.call_model(self.rundir, state, self.cfg, "architect", "plan",
                               "prompt", self.project)
        spawn.assert_not_called()


class LegacyEvidenceAdmissionTests(ReleaseFixture):
    def test_unattested_old_raw_config_still_drifts(self):
        recorded = {"configuration": {"path": "/old/config.json",
                                      "sha256": "a" * 64},
                    "environment": {}, "toolchain": {}, "runtime_inputs": {}}
        current = {"configuration": {"policy": {"version": 1,
                                                "sha256": "b" * 64}},
                   "environment": {}, "toolchain": {}, "runtime_inputs": {}}
        self.assertIn("configuration", orc.provenance_drift(recorded, current))

    def test_attested_old_bytes_permit_equivalent_policy(self):
        recorded = {"configuration": {"path": "/old/config.json",
                                      "sha256": "a" * 64},
                    "environment": {}, "toolchain": {}, "runtime_inputs": {}}
        current = {"configuration": {"policy": {"version": 1,
                                                "sha256": "b" * 64}},
                   "environment": {}, "toolchain": {}, "runtime_inputs": {}}
        self.assertEqual(orc.provenance_drift(
            recorded, current,
            attestation={"raw_sha256": "a" * 64, "sha256": "b" * 64}), [])

    def test_attestation_cannot_launder_a_different_policy(self):
        recorded = {"configuration": {"path": "/old/config.json",
                                      "sha256": "a" * 64},
                    "environment": {}, "toolchain": {}, "runtime_inputs": {}}
        current = {"configuration": {"policy": {"version": 1,
                                                "sha256": "b" * 64}},
                   "environment": {}, "toolchain": {}, "runtime_inputs": {}}
        self.assertIn("configuration", orc.provenance_drift(
            recorded, current,
            attestation={"raw_sha256": "a" * 64, "sha256": "c" * 64}))


class ModelMetadataTests(ReleaseFixture):
    def metadata_bin(self):
        directory = self.root / "metadata-bin"
        write_fake(directory, "codex", FAKE_CODEX)
        write_fake(directory, "opencode", FAKE_OPENCODE)
        patcher = patch.dict(os.environ, {
            "PATH": str(directory) + ":" + os.environ.get("PATH", "")})
        patcher.start()
        self.addCleanup(patcher.stop)
        return directory

    def test_codex_app_server_probe_parses_effort_and_exhausts_pages(self):
        self.metadata_bin()
        catalogue = orc._codex_model_catalogue()
        self.assertEqual(catalogue["state"], "confirmed")
        self.assertTrue(catalogue["complete"])
        self.assertIn("gpt-any-9.9", catalogue["models"])
        self.assertIn("gpt-page-two", catalogue["models"])

    def test_codex_probe_runs_in_the_route_project(self):
        directory = self.root / "cwd-bin"
        record = self.root / "probe-cwd.jsonl"
        write_fake(directory, "codex", textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json, os, sys
            if "--version" in sys.argv:
                print("codex-cli 0.169.1")
                raise SystemExit(0)
            if "app-server" not in sys.argv:
                raise SystemExit(3)
            target = os.environ.get("PROBE_RECORD")
            if target:
                with open(target, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps({"cwd": os.getcwd()}) + "\\n")
            for line in sys.stdin:
                message = json.loads(line)
                if message.get("method") == "initialize":
                    print(json.dumps({"id": message["id"], "result": {}}), flush=True)
                elif message.get("method") == "model/list":
                    print(json.dumps({"id": message["id"], "result": {
                        "data": [{"id": "gpt-any-9.9", "model": "gpt-any-9.9",
                                  "supportedReasoningEfforts": [
                                      {"reasoningEffort": "high"}]}]}}), flush=True)
            """))
        with patch.dict(os.environ, {
                "PATH": str(directory) + ":" + os.environ.get("PATH", ""),
                "PROBE_RECORD": str(record)}):
            catalogue = orc._codex_model_catalogue(self.project)
        self.assertEqual(catalogue["state"], "confirmed")
        observed = [json.loads(line)["cwd"]
                    for line in record.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(observed, [str(self.project.resolve())])

    def test_unknown_effort_is_rejected_not_treated_as_absent(self):
        catalogue = confirmed()
        typo = orc.model_metadata_verdict(catalogue, "gpt-any-9.9", "hgih")
        self.assertEqual(typo["state"], "unsupported")
        self.assertFalse(typo["effort_supported"])
        self.assertEqual(orc.model_metadata_verdict(
            catalogue, "gpt-any-9.9", "  "), {
            "source": "test", "detail": "fixture", "version": "test",
            "model": "gpt-any-9.9", "complete": None,
            "state": "confirmed", "model_listed": True,
            "effort_supported": None, "variants": ["low", "medium", "high"]})
        provider_variant = confirmed(variants=("high-code", "low"))
        exact = orc.model_metadata_verdict(
            catalogue=provider_variant, model="gpt-any-9.9", effort="high-code")
        self.assertEqual(exact["state"], "confirmed")
        self.assertTrue(exact["effort_supported"])

    def test_typo_effort_is_refused_before_any_run_exists(self):
        self.metadata_bin()
        before = sorted(path.name for path in (self.root / "runs").iterdir())
        with self.assertRaisesRegex(ValueError, "not supported"):
            orc.resolve_run_routes(
                self.cfg, "codex", self.project,
                {"reviewer": {"model": "opencode-go/deepseek-v4.1-flash",
                              "effort": "hgih", "billing": "go"}})
        with self.assertRaisesRegex(ValueError, "not supported"):
            orc.resolve_run_routes(
                self.cfg, "codex", self.project,
                {"reviewer": {"model": "opencode-go/deepseek-v4.1-flash",
                              "effort": "hgih", "billing": "go"}},
                allow_unverified=True)
        self.assertEqual(before, sorted(path.name
                                        for path in (self.root / "runs").iterdir()))

    def test_unvisited_pages_never_make_absence_authoritative(self):
        directory = self.root / "paged-bin"
        write_fake(directory, "codex", textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json, sys
            if "--version" in sys.argv:
                print("codex-cli 0.169.1")
                raise SystemExit(0)
            for line in sys.stdin:
                message = json.loads(line)
                if message.get("method") == "initialize":
                    print(json.dumps({"id": message["id"], "result": {}}), flush=True)
                elif message.get("method") == "model/list":
                    print(json.dumps({"id": message["id"], "result": {
                        "data": [{"id": "gpt-any-9.9", "model": "gpt-any-9.9",
                                  "supportedReasoningEfforts": [
                                      {"reasoningEffort": "high"}]}],
                        "nextCursor": "more"}}), flush=True)
            """))
        with patch.dict(os.environ, {
                "PATH": str(directory) + ":" + os.environ.get("PATH", "")}):
            catalogue = orc._codex_model_catalogue(self.project)
        self.assertEqual(catalogue["state"], "confirmed")
        self.assertFalse(catalogue["complete"])
        verdict = orc.model_metadata_verdict(
            catalogue, "gpt-not-on-visited-pages", "high")
        self.assertEqual(verdict["state"], "unavailable")
        self.assertIn("not authoritative", verdict["reason"])

    def test_catalogue_is_isolated_per_project(self):
        directory = self.root / "project-bin"
        write_fake(directory, "opencode", textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json, os, sys
            args = sys.argv[1:]
            if "--version" in args:
                print("v2.2.7")
                raise SystemExit(0)
            if args[:1] == ["api"]:
                project = os.path.basename(os.getcwd())
                model = "model-a" if project == "proj-a" else "model-b"
                print(json.dumps({"data": [{
                    "id": model, "modelID": model, "providerID": "opencode-go",
                    "enabled": True,
                    "variants": [{"id": "high"}]}]}))
                raise SystemExit(0)
            print("{}")
            """))
        project_a = self.root / "proj-a"
        project_b = self.root / "proj-b"
        project_a.mkdir()
        project_b.mkdir()
        route = {"provider": "opencode", "worker_provider": "opencode-go",
                 "model": "opencode-go/model-a", "effort": "high", "billing": "go"}
        with patch.dict(os.environ, {
                "PATH": str(directory) + ":" + os.environ.get("PATH", "")}):
            first = orc.model_catalogue("codex", "reviewer", route, project_a,
                                        dialect="v2")
            second = orc.model_catalogue("codex", "reviewer", route, project_b,
                                         dialect="v2")
        self.assertIn("opencode-go/model-a", first["models"])
        self.assertNotIn("opencode-go/model-b", first["models"])
        self.assertIn("opencode-go/model-b", second["models"])
        self.assertNotIn("opencode-go/model-a", second["models"])

    def test_architect_without_high_is_refused_for_a_new_selection(self):
        self.metadata_bin()
        no_high = {"state": "confirmed", "source": "test", "complete": True,
                   "models": {"gpt-no-high": {
                       "id": "gpt-no-high", "provider": None,
                       "variants": ["low", "medium"]}}}
        with patch.object(orc, "model_catalogue", return_value=no_high):
            with self.assertRaisesRegex(ValueError, "protected"):
                orc.resolve_run_routes(
                    self.cfg, "codex", self.project,
                    {"architect": {"model": "gpt-no-high", "effort": "medium",
                                   "billing": "subscription"}})

    def test_configured_and_override_medium_architect_routes_are_refused(self):
        self.metadata_bin()
        medium = copy.deepcopy(self.cfg)
        medium["architect"]["codex"]["effort"] = "medium"
        with self.assertRaisesRegex(ValueError, "requires High"):
            orc.resolve_run_routes(medium, "codex", self.project)
        with self.assertRaisesRegex(ValueError, "requires High"):
            orc.resolve_run_routes(
                self.cfg, "codex", self.project,
                {"architect": {"model": "gpt-6.2-sol", "effort": "medium",
                               "billing": "subscription"}})
        # The persistent pin stays High; Medium is the explicit trial's job.
        resolved = orc.resolve_run_routes(
            self.cfg, "codex", self.project,
            {"architect": {"model": "gpt-6.2-sol", "effort": "high",
                           "billing": "subscription"}})
        self.assertEqual(resolved["routes"]["architect"]["effort"], "high")

    def test_unavailable_metadata_still_requires_a_persistent_high_effort(self):
        unavailable = {"state": "unavailable", "models": {}, "source": "x",
                       "detail": "no adapter"}
        medium = copy.deepcopy(self.cfg)
        medium["architect"]["codex"]["effort"] = "medium"
        with patch.object(orc, "model_catalogue", return_value=unavailable):
            with self.assertRaisesRegex(ValueError, "requires High"):
                orc.resolve_run_routes(medium, "codex", self.project,
                                       allow_unverified=True)
            resolved = orc.resolve_run_routes(
                self.cfg, "codex", self.project, allow_unverified=True)
        self.assertEqual(resolved["routes"]["architect"]["effort"], "high")
        self.assertEqual(resolved["record"]["metadata_policy"],
                         "explicitly_authorized_unverified")

    def test_opencode_v2_probe_reads_variants_and_enabled_state(self):
        self.metadata_bin()
        catalogue = orc._opencode_v2_catalogue(self.project)
        self.assertEqual(catalogue["state"], "confirmed")
        verdict = orc.model_metadata_verdict(
            catalogue, "opencode-go/deepseek-v4.1-flash", "high")
        self.assertEqual(verdict["state"], "confirmed")
        self.assertTrue(verdict["effort_supported"])
        disabled = orc.model_metadata_verdict(
            catalogue, "opencode-go/disabled-model", "high")
        self.assertEqual(disabled["state"], "unsupported")

    def test_verdicts_keep_confirmed_unsupported_unavailable_distinct(self):
        catalogue = confirmed()
        self.assertEqual(orc.model_metadata_verdict(
            catalogue, "gpt-any-9.9", "medium")["state"], "confirmed")
        self.assertEqual(orc.model_metadata_verdict(
            catalogue, "gpt-any-9.9", "max")["state"], "unsupported")
        self.assertEqual(orc.model_metadata_verdict(
            catalogue, "gpt-other", "high")["state"], "unsupported")
        unavailable = {"state": "unavailable", "models": {}, "source": "x",
                       "detail": "no adapter"}
        self.assertEqual(orc.model_metadata_verdict(
            unavailable, "gpt-any-9.9", "high")["state"], "unavailable")

    def test_claude_effort_contract_is_validated_without_model_claims(self):
        directory = self.root / "claude-bin"
        write_fake(directory, "claude", textwrap.dedent(
            """\
            #!/usr/bin/env python3
            print("  --effort <level>   Effort level (low, medium, high)")
            """))
        with patch.dict(os.environ, {
                "PATH": str(directory) + ":" + os.environ.get("PATH", "")}):
            catalogue = orc._claude_model_catalogue()
            supported = orc.model_metadata_verdict(
                catalogue, "claude-opus-5-5", "high")
            unsupported = orc.model_metadata_verdict(
                catalogue, "claude-opus-5-5", "max")
        self.assertEqual(catalogue["state"], "unavailable")
        self.assertTrue(catalogue["effort_contract"])
        self.assertEqual(supported["state"], "unavailable")
        self.assertTrue(supported["effort_supported"])
        self.assertIsNone(supported["model_listed"])
        self.assertEqual(unsupported["state"], "unsupported")
        self.assertFalse(unsupported["effort_supported"])

    def test_planning_trial_uses_catalogue_not_a_version_literal(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["architect"]["codex"]["model"] = "gpt-arbitrary-7"
        cfg["architect"]["codex"]["effort"] = "high"
        cfg["architect"]["codex"]["auth"] = "subscription"
        full = {"state": "confirmed", "source": "test", "models": {},
                "detail": "fixture", "version": "test",
                "variants": ["low", "medium", "high"]}
        trial = orc.validate_planning_trial(
            cfg, "codex", True, metadata={"architect": full})
        self.assertTrue(trial["enabled"])
        with self.assertRaisesRegex(ValueError, "missing"):
            orc.validate_planning_trial(
                cfg, "codex", True,
                metadata={"architect": {**full, "variants": ["high"]}})
        with self.assertRaisesRegex(ValueError, "confirmed catalogue"):
            orc.validate_planning_trial(
                cfg, "codex", True,
                metadata={"architect": {"state": "unavailable",
                                        "source": "none", "models": {}}})

    def test_planning_trial_pins_the_resolved_override_route(self):
        self.metadata_bin()
        resolved = orc.resolve_run_routes(
            self.cfg, "codex", self.project,
            {"architect": {"model": "gpt-6.2-sol", "effort": "high",
                           "billing": "subscription"}})
        trial = orc.validate_planning_trial(
            self.cfg, "codex", True, metadata=resolved["metadata"],
            route=resolved["routes"]["architect"])
        self.assertEqual(trial["pinned_route"], {
            "provider": "codex", "model": "gpt-6.2-sol",
            "effort": "high", "billing": "subscription"})
        self.assertEqual(
            trial["pinned_route_sha256"],
            orc.content_hash(resolved["routes"]["architect"]))

    def test_planning_trial_rejects_metadata_for_another_model(self):
        self.metadata_bin()
        resolved = orc.resolve_run_routes(
            self.cfg, "codex", self.project,
            {"architect": {"model": "gpt-6.2-sol", "effort": "high",
                           "billing": "subscription"}})
        wrong = copy.deepcopy(resolved["metadata"])
        wrong["architect"]["model"] = "gpt-any-9.9"
        with self.assertRaisesRegex(ValueError, "resolved run route"):
            orc.validate_planning_trial(
                self.cfg, "codex", True, metadata=wrong,
                route=resolved["routes"]["architect"])

    def test_route_override_trial_runs_medium_then_accepts_on_pinned_high(self):
        self.metadata_bin()
        run_id, folder, state = orc.create_run(
            project=self.project, goal="Override trial", host="codex",
            skip_doctor=True, ordinary_planning_trial=True,
            routes={"architect": {"model": "gpt-6.2-sol", "effort": "high",
                                  "billing": "subscription"}})
        self.assertEqual(state["model_routes"]["architect"]["model"],
                         "gpt-6.2-sol")
        trial = state["ordinary_planning_trial"]
        self.assertEqual(trial["pinned_route"]["model"], "gpt-6.2-sol")
        self.assertEqual(
            trial["pinned_route_sha256"],
            orc.content_hash({key: state["model_routes"]["architect"][key]
                              for key in ("provider", "model", "effort",
                                          "billing")}))
        plan = self.plan(risk="ordinary")
        calls = []

        def strong(_dir, _state, _cfg, kind, extra=None, **kw):
            calls.append((kind, kw.get("route")))
            if kind == "plan":
                return plan
            return {"verdict": "approved", "reason": "inspected",
                    "inspected": ["app.py"], "correction": "",
                    "dismissed_findings": []}

        with patch.object(orc, "strong_call", side_effect=strong):
            orc.advance(folder, state, self.cfg)
        self.assertEqual(calls[0], ("plan", {
            **{key: state["model_routes"]["architect"][key]
               for key in ("provider", "model", "effort", "billing")},
            "effort": "medium"}))
        self.assertEqual(state["ordinary_planning_trial"]["state"], "adopted")
        # Acceptance remains on the pinned High route, not the trial effort.
        verification_path = self.root / "verification.json"
        verification_path.write_text("{}")
        state["phase"] = "accept"
        state["review"] = {"status": "complete", "findings": []}
        state["verification"] = {
            "path": str(verification_path), "passed": True,
            "candidate_hash": orc.signature(orc.source_snapshot(self.project)),
            "evidence_version": 2}
        with patch.object(orc, "strong_call", side_effect=strong), \
                patch.object(orc, "load_verification_evidence", return_value={}), \
                patch.object(orc, "validate_acceptance_references",
                             side_effect=lambda st, pr, refs, **kwargs: orc.source_snapshot(pr)), \
                patch.object(orc, "cached_decision_report", return_value=None):
            orc.advance(folder, state, self.cfg)
        decision = [call for call in calls if call[0] == "decision"]
        self.assertTrue(decision)
        self.assertIsNone(decision[-1][1])

    def test_override_precedence_for_every_role(self):
        self.metadata_bin()
        overrides = {
            "architect": {"model": "gpt-any-9.9", "effort": "high",
                          "billing": "subscription"},
            "explorer": {"model": "opencode-go/deepseek-v4.1-flash",
                         "effort": "low", "billing": "go"},
            "implementer": {"model": "opencode-go/deepseek-v4.1-flash",
                            "effort": "high", "billing": "go"},
            "reviewer": {"provider": "opencode-go",
                         "model": "opencode-go/deepseek-v4.1-flash",
                         "effort": "max", "billing": "go"}}
        resolved = orc.resolve_run_routes(self.cfg, "codex", self.project,
                                          overrides)
        for role, spec in overrides.items():
            route = resolved["routes"][role]
            self.assertEqual(route["model"], spec["model"], role)
            self.assertEqual(route["effort"], spec["effort"], role)
            self.assertEqual(route["billing"], spec["billing"], role)
        self.assertEqual(resolved["record"]["source"], "run_override")
        self.assertEqual(set(resolved["record"]["overrides"]), set(overrides))

    def test_provider_change_requires_a_complete_explicit_route(self):
        with self.assertRaisesRegex(ValueError, "complete route"):
            orc.resolve_run_routes(
                self.cfg, "codex", self.project,
                {"implementer": {"model": "deepseek/deepseek-chat",
                                 "provider": "deepseek", "effort": "high"}})
        with self.assertRaisesRegex(ValueError, "explicit"):
            orc.resolve_run_routes(
                self.cfg, "codex", self.project,
                {"implementer": {"model": "deepseek/deepseek-chat",
                                 "provider": "deepseek", "effort": "high",
                                 "billing": "go"}})

    def test_unknown_keys_and_fallbacks_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown keys"):
            orc.resolve_run_routes(self.cfg, "codex", self.project,
                                   {"reviewer": {"model": "x/y", "secret": 1}})
        with self.assertRaisesRegex(ValueError, "unauthorized fallback"):
            orc.resolve_run_routes(
                self.cfg, "codex", self.project,
                {"reviewer": {"model": "opencode-go/deepseek-v4.1-flash",
                              "fallback": {"model": "a/b"}}})

    def test_unverified_new_selection_needs_explicit_authorization(self):
        unavailable = {"state": "unavailable", "models": {}, "source": "x",
                       "detail": "no adapter"}
        with patch.object(orc, "model_catalogue", return_value=unavailable):
            with self.assertRaisesRegex(RuntimeError, "cannot be attested"):
                orc.resolve_run_routes(
                    self.cfg, "codex", self.project,
                    {"reviewer": {"model": "opencode-go/other",
                                  "effort": "high", "billing": "go"}})
            resolved = orc.resolve_run_routes(
                self.cfg, "codex", self.project,
                {"reviewer": {"model": "opencode-go/other",
                              "effort": "high", "billing": "go"}},
                allow_unverified=True)
            self.assertEqual(
                resolved["record"]["metadata_policy"],
                "explicitly_authorized_unverified")

    def test_unsupported_new_selection_is_refused_before_state(self):
        unsupported = {"state": "confirmed", "source": "test", "models": {
            "opencode-go/other": {"id": "opencode-go/other", "provider":
                                  "opencode-go", "variants": ["low"]}}}
        before = sorted(path.name for path in (self.root / "runs").iterdir())
        with patch.object(orc, "model_catalogue", return_value=unsupported):
            with self.assertRaisesRegex(ValueError, "not supported"):
                orc.resolve_run_routes(
                    self.cfg, "codex", self.project,
                    {"reviewer": {"model": "opencode-go/other",
                                  "effort": "high", "billing": "go"}})
        self.assertEqual(before, sorted(path.name
                                        for path in (self.root / "runs").iterdir()))

    def test_partial_override_inherits_safe_fields(self):
        self.metadata_bin()
        resolved = orc.resolve_run_routes(
            self.cfg, "codex", self.project,
            {"implementer": {"model": "opencode-go/deepseek-v4.1-flash"}})
        route = resolved["routes"]["implementer"]
        self.assertEqual(route["billing"], "go")
        self.assertEqual(route["effort"],
                         self.cfg["workers"]["implementer"]["variant"])

    def test_cli_and_mcp_expose_the_same_role_override_contract(self):
        schema = next(tool for tool in orc.MCP_TOOLS
                      if tool["name"] == "orchestrator_start")
        properties = schema["inputSchema"]["properties"]
        self.assertIn("routes", properties)
        self.assertIn("allow_unverified_metadata", properties)
        self.assertEqual(set(properties["routes"]["properties"]),
                         {"architect", "explorer", "implementer", "reviewer"})
        inline = json.dumps({"reviewer": {"model": "opencode-go/other"}})
        self.assertEqual(orc._load_routes_argument(inline)["reviewer"]["model"],
                         "opencode-go/other")
        path = self.root / "routes.json"
        orc.atomic_json(path, {"architect": {"effort": "high"}})
        self.assertEqual(orc._load_routes_argument(str(path))["architect"]["effort"],
                         "high")
        with patch.object(orc, "create_run",
                          return_value=("run-1", self.rundir, self.state())) as create, \
                patch.object(orc, "next_stage_preview", return_value={}):
            orc.start_run(project=str(self.project), goal="g", host="codex",
                          routes={"reviewer": {"model": "opencode-go/other"}},
                          allow_unverified_metadata=True)
        kwargs = create.call_args.kwargs
        self.assertEqual(kwargs["routes"]["reviewer"]["model"],
                         "opencode-go/other")
        self.assertTrue(kwargs["allow_unverified_metadata"])


class RoleSwitchTests(ReleaseFixture):
    def prepared(self, **overrides):
        state = self.state(**overrides)
        state.setdefault("role_generations",
                         {"architect": 0, "explorer": 0, "implementer": 0,
                          "reviewer": 0})
        state.setdefault("role_switches", [])
        state.setdefault("route_authorizations", [])
        state["accepted_batches"] = [{"title": "kept"}]
        state["accepted_history"] = [{"title": "kept-history"}]
        state["status"] = overrides.get("status", "paused")
        orc.save(self.rundir, state)
        return state

    def route_spec(self, role="reviewer", effort="max"):
        return {"model": "opencode-go/reviewer-v2", "provider": "opencode-go",
                "effort": effort, "billing": "go"}

    def allow_operator(self):
        patcher = patch.object(
            orc, "require_human_operator",
            return_value={"actor": {"user": "test"}, "method": "test"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def switching(self, catalogue=None, preflight=None):
        stack = contextlib.ExitStack()
        stack.enter_context(patch.object(
            orc, "model_catalogue",
            return_value=catalogue or self.confirmed_catalogue()))
        stack.enter_context(patch.object(
            orc, "route_preflight",
            return_value=preflight or {"ok": True, "reasons": [],
                                       "classification": "test"}))
        return stack

    def confirmed_catalogue(self):
        reviewer_local = self.cfg["workers"]["reviewer"]["model"]
        return {"state": "confirmed", "source": "test", "models": {
            "opencode-go/reviewer-v2": {
                "id": "opencode-go/reviewer-v2", "provider": "opencode-go",
                "variants": ["high", "max"]},
            reviewer_local: {
                "id": reviewer_local, "provider": "opencode-go",
                "variants": ["low", "high", "max"]},
            "gpt-6.2-sol": {"id": "gpt-6.2-sol", "provider": None,
                            "variants": ["high", "medium"]},
            "gpt-any-9.9": {"id": "gpt-any-9.9", "provider": None,
                            "variants": ["low", "medium", "high"]}}}

    def test_preview_is_read_only_and_tied_to_the_route_identity(self):
        self.prepared()
        before = (self.rundir / "state.json").read_bytes()
        with self.switching():
            preview = orc.preview_role_switch(
                "test-v12000", "reviewer", self.route_spec())
        self.assertEqual((self.rundir / "state.json").read_bytes(), before)
        self.assertFalse(preview["applied"])
        self.assertTrue(preview["expected_confirmation"].startswith(
            "switch-role:test-v12000:reviewer:"))
        with self.switching():
            other = orc.preview_role_switch(
                "test-v12000", "reviewer", self.route_spec(effort="high"))
        self.assertNotEqual(preview["proposal_sha256"],
                            other["proposal_sha256"])

    def test_apply_preserves_history_and_invalidates_pending_review(self):
        self.allow_operator()
        self.prepared(phase="accept", review={"status": "complete"},
                      final_verdict={"verdict": "approved"},
                      verification={"path": "/tmp/verification.json",
                                    "passed": True},
                      retry_session={"role": "reviewer", "session_id": "s",
                                     "reconciled": True,
                                     "termination_verified": True},
                      route_authorizations=[{
                          "id": "old-grant", "role": "reviewer",
                          "route_sha256": "0" * 64, "max_dispatches": 1,
                          "used": 0, "role_generation": 0}])
        with self.switching():
            preview = orc.preview_role_switch(
                "test-v12000", "reviewer", self.route_spec())
            result = orc.switch_role_run(
                "test-v12000", "reviewer", self.route_spec(),
                preview["expected_confirmation"])
        state = orc.read_json(self.rundir / "state.json")
        self.assertTrue(result["applied"])
        self.assertEqual(state["role_generations"]["reviewer"], 1)
        self.assertIsNone(state["review"])
        self.assertIsNone(state["final_verdict"])
        self.assertIsNone(state["retry_session"])
        self.assertEqual(state["phase"], "review")
        self.assertEqual(state["verification"]["path"],
                         "/tmp/verification.json")
        self.assertEqual(state["accepted_batches"], [{"title": "kept"}])
        self.assertEqual(state["accepted_history"],
                         [{"title": "kept-history"}])
        self.assertEqual(state["model_routes"]["reviewer"]["effort"], "max")
        self.assertTrue(Path(result["backup"], "state.json").is_file())
        events = [item.get("event") for item in orc.journal_tail(self.rundir)]
        self.assertIn("role_switched", events)

    def test_architect_switch_preserves_plan_and_requires_high(self):
        self.allow_operator()
        plan = {"contract_version": 2, "status": "complete", "summary": "s",
                "invariants": [], "batches": [], "blocker": ""}
        self.prepared(phase="accept", plan=plan,
                      plan_version=orc.content_hash(plan),
                      checks={"kept": True},
                      final_verdict={"verdict": "approved"})
        with self.switching():
            with self.assertRaisesRegex(ValueError, "requires High"):
                orc.switch_role_run(
                    "test-v12000", "architect",
                    {"model": "gpt-6.2-sol", "effort": "medium",
                     "billing": "subscription"})
            preview = orc.preview_role_switch(
                "test-v12000", "architect",
                {"model": "gpt-6.2-sol", "effort": "high",
                 "billing": "subscription"})
            result = orc.switch_role_run(
                "test-v12000", "architect",
                {"model": "gpt-6.2-sol", "effort": "high",
                 "billing": "subscription"},
                preview["expected_confirmation"])
        state = orc.read_json(self.rundir / "state.json")
        self.assertTrue(result["applied"])
        self.assertEqual(state["plan"], plan)
        self.assertEqual(state["plan_version"], orc.content_hash(plan))
        self.assertEqual(state["checks"], {"kept": True})
        self.assertIsNone(state["final_verdict"])
        self.assertEqual(state["role_generations"]["architect"], 1)

    def test_mechanical_reviewer_switch_keeps_supervisor_acceptance(self):
        self.allow_operator()
        plan = self.plan(risk="mechanical")
        review = {"status": "complete", "summary":
                  "Mechanical batch accepted by bounded supervisor checks",
                  "files": [], "tests": [], "evidence": [], "unknowns": [],
                  "blocker": "", "findings": []}
        self.prepared(phase="accept", plan=plan,
                      plan_version=orc.content_hash(plan),
                      review=copy.deepcopy(review),
                      verification={"path": "/tmp/verification.json",
                                    "passed": True},
                      final_verdict={"verdict": "approved"})
        with self.switching():
            preview = orc.preview_role_switch(
                "test-v12000", "reviewer", self.route_spec())
            result = orc.switch_role_run(
                "test-v12000", "reviewer", self.route_spec(),
                preview["expected_confirmation"])
        state = orc.read_json(self.rundir / "state.json")
        self.assertTrue(result["applied"])
        self.assertEqual(state["phase"], "accept")
        self.assertEqual(state["review"], review)
        self.assertEqual(state["verification"]["path"],
                         "/tmp/verification.json")
        self.assertIsNone(state["final_verdict"])
        self.assertEqual(state["role_generations"]["reviewer"], 1)
        self.assertTrue(result["invalidated"]["mechanical_review_preserved"])
        self.assertFalse(result["invalidated"]["review"])

    def test_ordinary_reviewer_switch_still_requires_fresh_review(self):
        self.allow_operator()
        plan = self.plan(risk="ordinary")
        self.prepared(phase="accept", plan=plan,
                      plan_version=orc.content_hash(plan),
                      review={"status": "complete"},
                      verification={"path": "/tmp/verification.json",
                                    "passed": True},
                      final_verdict={"verdict": "approved"})
        with self.switching():
            preview = orc.preview_role_switch(
                "test-v12000", "reviewer", self.route_spec())
            result = orc.switch_role_run(
                "test-v12000", "reviewer", self.route_spec(),
                preview["expected_confirmation"])
        state = orc.read_json(self.rundir / "state.json")
        self.assertEqual(state["phase"], "review")
        self.assertIsNone(state["review"])
        self.assertIsNone(state["final_verdict"])
        self.assertTrue(result["invalidated"]["review"])
        self.assertEqual(state["verification"]["path"],
                         "/tmp/verification.json")

    def test_switch_refuses_an_incompatible_preflight_route(self):
        self.allow_operator()
        self.prepared()
        before = (self.rundir / "state.json").read_bytes()
        incompatible = {"ok": False, "classification": "unprovable_routing",
                        "reasons": ["Unrecognized OpenCode version"]}
        with self.switching(preflight=incompatible):
            with self.assertRaisesRegex(RuntimeError, "incompatible"):
                orc.switch_role_run("test-v12000", "reviewer",
                                    self.route_spec())
        self.assertEqual((self.rundir / "state.json").read_bytes(), before)
        self.assertEqual(orc.read_json(
            self.rundir / "state.json")["role_generations"]["reviewer"], 0)

    def test_switch_distinguishes_a_separate_grant_from_incompatibility(self):
        self.allow_operator()
        self.prepared()
        grant_only = {
            "ok": False, "classification": "unknown",
            "reasons": ["usage-billed strong route requires an explicit human "
                        "`authorize-route` grant"],
            "authorization": {"required": True, "authorized": False}}
        with self.switching(preflight=grant_only):
            preview = orc.preview_role_switch(
                "test-v12000", "architect",
                {"model": "gpt-any-9.9", "effort": "high", "billing": "api"})
        self.assertTrue(preview["ok"])
        self.assertEqual(preview["requires_grant"],
                         {"required": True, "authorized": False})
        self.assertFalse(preview["preflight"]["ok"])

    def test_switch_refuses_an_invalid_billing_policy_before_mutation(self):
        self.allow_operator()
        self.prepared()
        before = (self.rundir / "state.json").read_bytes()
        with self.switching():
            with self.assertRaisesRegex(ValueError, "billing 'go'"):
                orc.switch_role_run(
                    "test-v12000", "reviewer",
                    {"model": "deepseek/deepseek-chat", "provider": "deepseek",
                     "effort": "high", "billing": "go"})
        self.assertEqual((self.rundir / "state.json").read_bytes(), before)

    def test_switch_inherits_the_pinned_route_not_new_global_defaults(self):
        self.allow_operator()
        state = self.prepared()
        pinned = copy.deepcopy(state["model_routes"]["reviewer"])
        changed = copy.deepcopy(self.cfg)
        changed["workers"]["reviewer"]["variant"] = "low"
        changed["workers"]["reviewer"]["billing"] = "go"
        orc.atomic_json(self.cfg_path, changed)
        with self.switching():
            preview = orc.preview_role_switch(
                "test-v12000", "reviewer", {"model": pinned["model"]})
        self.assertEqual(preview["proposed_route"]["effort"], pinned["effort"])
        self.assertEqual(preview["proposed_route"]["billing"], pinned["billing"])
        self.assertEqual(preview["proposed_route"]["provider"],
                         pinned["provider"])

    def test_architect_switch_marks_pending_trial_ineligible_immediately(self):
        self.allow_operator()
        pinned = {"provider": "codex", "model": "gpt-6.2-sol",
                  "effort": "high", "billing": "subscription"}
        trial = {"enabled": True, "state": "pending",
                 "effort": "medium",
                 "pinned_route": dict(pinned),
                 "pinned_route_sha256": orc.content_hash(pinned),
                 "scope": "initial_plan_only"}
        self.prepared(phase="plan", plan=None,
                      ordinary_planning_trial=copy.deepcopy(trial),
                      planning_trial_history=[])
        with self.switching():
            preview = orc.preview_role_switch(
                "test-v12000", "architect",
                {"model": "gpt-any-9.9", "effort": "high",
                 "billing": "subscription"})
            self.assertEqual(preview["trial_effect"]["state"],
                             "ineligible_route_drift")
            result = orc.switch_role_run(
                "test-v12000", "architect",
                {"model": "gpt-any-9.9", "effort": "high",
                 "billing": "subscription"},
                preview["expected_confirmation"])
        state = orc.read_json(self.rundir / "state.json")
        self.assertTrue(result["applied"])
        self.assertEqual(state["ordinary_planning_trial"]["state"],
                         "ineligible_route_drift")
        self.assertEqual(state["planning_trial_history"][-1]["state"],
                         "ineligible_route_drift")
        self.assertEqual(state["model_routes"]["architect"]["effort"], "high")
        self.assertEqual(result["invalidated"]["planning_trial"],
                         "ineligible_route_drift")

    def test_switch_refuses_changed_execution_policy_before_and_under_lock(self):
        self.allow_operator()
        grant = {"id": "g", "role": "reviewer", "route_sha256": "0" * 64,
                 "max_dispatches": 1, "used": 0, "role_generation": 0}
        state = self.prepared(route_authorizations=[grant])
        with self.switching():
            preview = orc.preview_role_switch(
                "test-v12000", "reviewer", self.route_spec())
        changed = copy.deepcopy(self.cfg)
        changed["limits"]["max_stage_seconds"] = 4321
        orc.atomic_json(self.cfg_path, changed)
        before = (self.rundir / "state.json").read_bytes()
        with self.switching():
            with self.assertRaisesRegex(RuntimeError, "compatible"):
                orc.preview_role_switch("test-v12000", "reviewer",
                                        self.route_spec())
            with self.assertRaisesRegex(RuntimeError, "compatible"):
                orc.switch_role_run("test-v12000", "reviewer",
                                    self.route_spec(),
                                    preview["expected_confirmation"])
        after = orc.read_json(self.rundir / "state.json")
        self.assertEqual((self.rundir / "state.json").read_bytes(), before)
        self.assertEqual(after["model_routes"], state["model_routes"])
        self.assertEqual(after["role_generations"]["reviewer"], 0)
        self.assertEqual(after["route_authorizations"], [grant])
        self.assertFalse(after["role_switches"])

    def test_preference_only_change_after_preview_still_applies(self):
        self.allow_operator()
        state = self.prepared()
        pinned = copy.deepcopy(state["model_routes"])
        with self.switching():
            preview = orc.preview_role_switch(
                "test-v12000", "reviewer", self.route_spec())
        changed = copy.deepcopy(self.cfg)
        changed["workers"]["implementer"]["variant"] = "low"
        changed["architect"]["codex"]["model"] = "gpt-any-9.9"
        orc.atomic_json(self.cfg_path, changed)
        with self.switching():
            result = orc.switch_role_run(
                "test-v12000", "reviewer", self.route_spec(),
                preview["expected_confirmation"])
        after = orc.read_json(self.rundir / "state.json")
        self.assertTrue(result["applied"])
        self.assertEqual(after["model_routes"]["reviewer"]["effort"], "max")
        for role in ("architect", "explorer", "implementer"):
            self.assertEqual(after["model_routes"][role], pinned[role])
        self.assertEqual(after["role_generations"]["reviewer"], 1)

    def test_architect_switch_to_medium_is_refused_before_protected_phases(self):
        self.allow_operator()
        self.prepared(phase="plan", plan=None)
        with self.switching():
            with self.assertRaisesRegex(ValueError, "requires High"):
                orc.preview_role_switch(
                    "test-v12000", "architect",
                    {"model": "gpt-6.2-sol", "effort": "medium",
                     "billing": "subscription"})
            preview = orc.preview_role_switch(
                "test-v12000", "architect",
                {"model": "gpt-any-9.9", "effort": "high",
                 "billing": "subscription"})
            result = orc.switch_role_run(
                "test-v12000", "architect",
                {"model": "gpt-any-9.9", "effort": "high",
                 "billing": "subscription"},
                preview["expected_confirmation"])
        self.assertTrue(result["applied"])
        state = orc.read_json(self.rundir / "state.json")
        self.assertEqual(state["model_routes"]["architect"]["effort"], "high")

    def test_mid_stage_uncertain_and_terminal_runs_are_refused(self):
        cases = [
            ({"active_job": {"id": "job"}}, "mid-stage"),
            ({"active_check": {"id": "check"}}, "mid-stage"),
            ({"status": "uncertain"}, "uncertain"),
            ({"status": "complete"}, "completed"),
        ]
        for overrides, message in cases:
            with self.subTest(message=message):
                self.prepared(**overrides)
                with self.switching():
                    with self.assertRaisesRegex(RuntimeError, message):
                        orc.preview_role_switch(
                            "test-v12000", "reviewer", self.route_spec())

    def test_a_b_a_cannot_replay_a_grant_or_cached_report(self):
        self.allow_operator()
        route = orc.model_route(self.cfg, "codex", "reviewer",
                                project=self.project)
        state = self.prepared(
            route_authorizations=[{
                "id": "old-grant", "role": "reviewer",
                "route_sha256": orc.route_authorization_sha(route),
                "max_dispatches": 1, "used": 0, "role_generation": 0}],
            completed_jobs=[{
                "id": "old-review", "kind": "reviewer", "role": "reviewer",
                "role_generation": 0, "path": str(self.root / "old-review")}])
        with self.switching():
            first_preview = orc.preview_role_switch(
                "test-v12000", "reviewer", self.route_spec())
            orc.switch_role_run("test-v12000", "reviewer", self.route_spec(),
                                first_preview["expected_confirmation"])
            back = {"model": route["model"],
                    "provider": route.get("worker_provider") or "opencode-go",
                    "effort": route["effort"], "billing": route["billing"]}
            back_preview = orc.preview_role_switch(
                "test-v12000", "reviewer", back)
            orc.switch_role_run("test-v12000", "reviewer", back,
                                back_preview["expected_confirmation"])
        state = orc.read_json(self.rundir / "state.json")
        self.assertEqual(state["role_generations"]["reviewer"], 2)
        status = orc.route_authorization_status(
            state, "reviewer", state["model_routes"]["reviewer"],
            run_dir=self.rundir)
        self.assertFalse(status["authorized"])
        self.assertIsNone(orc.cached_job_report(self.rundir, state, "reviewer"))

    def test_recovered_report_from_an_earlier_generation_is_rejected(self):
        self.allow_operator()
        self.prepared(phase="review", role_generations={
            "architect": 0, "explorer": 0, "implementer": 0, "reviewer": 1})
        job = {"id": "old-review", "kind": "reviewer", "role": "reviewer",
               "role_generation": 0, "path": "/tmp/old-review"}
        record = {"kind": "reviewer", "role_generation": 0,
                  "batch_index": 0, "authority_epoch": 0}
        state = orc.read_json(self.rundir / "state.json")
        self.assertFalse(orc._recovery_authority_current(state, record, job))

    def test_stale_confirmation_is_refused_after_the_run_changes(self):
        self.allow_operator()
        self.prepared()
        with self.switching():
            preview = orc.preview_role_switch(
                "test-v12000", "reviewer", self.route_spec())
            state = orc.read_json(self.rundir / "state.json")
            state["plan_version"] = "changed-after-preview"
            orc.atomic_json(self.rundir / "state.json", state)
            with self.assertRaisesRegex(RuntimeError, "Stale switch"):
                orc.switch_role_run("test-v12000", "reviewer",
                                    self.route_spec(),
                                    preview["expected_confirmation"])

    def test_unavailable_metadata_leaves_routes_and_grants_untouched(self):
        self.allow_operator()
        grant = {"id": "g", "role": "reviewer", "route_sha256": "0" * 64,
                 "max_dispatches": 1, "used": 0, "role_generation": 0}
        state = self.prepared(route_authorizations=[grant])
        before = copy.deepcopy(state["model_routes"])
        unavailable = {"state": "unavailable", "models": {}, "source": "x",
                       "detail": "no adapter"}
        with patch.object(orc, "model_catalogue", return_value=unavailable):
            with self.assertRaisesRegex(RuntimeError, "cannot be attested"):
                orc.switch_role_run("test-v12000", "reviewer",
                                    self.route_spec())
        after = orc.read_json(self.rundir / "state.json")
        self.assertEqual(after["model_routes"], before)
        self.assertEqual(after["route_authorizations"], [grant])
        self.assertEqual(after.get("role_generations", {}).get("reviewer", 0), 0)


class ReviewerSmokePrepareTests(ReleaseFixture):
    """The operator smoke must be prepared deterministically without a model."""

    def script(self):
        return Path(orc.HERE).parent / "scripts" / "reviewer_smoke.py"

    def test_prepare_builds_real_projection_without_revealing_the_answer(self):
        directory = self.root / "smoke-bin"
        write_fake(directory, "codex", FAKE_CODEX)
        write_fake(directory, "opencode", FAKE_OPENCODE)
        root = self.root / "smoke-root"
        env = dict(os.environ)
        env["PATH"] = str(directory) + ":" + env.get("PATH", "")
        proc = subprocess.run(
            [sys.executable, str(self.script()), "prepare", "--root", str(root)],
            capture_output=True, text=True, timeout=300, env=env)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        manifest = json.loads((root / "smoke-manifest.json").read_text())
        self.assertEqual(manifest["version"], 3)
        challenge = manifest["challenge"]["line"]
        value = str(manifest["challenge"]["value"])
        hunk = Path(manifest["hunk_path"]).read_text(encoding="utf-8")
        self.assertIn(challenge, hunk)
        prompt = Path(manifest["prompt_path"]).read_text(encoding="utf-8")
        self.assertNotIn(value, prompt)
        self.assertNotIn("MAGIC_SENTINEL", prompt)
        self.assertIn(manifest["hunk_relpath"], prompt)
        self.assertIn('"contract_version": 2', prompt)
        self.assertIn("echo abdullah-smoke-probe", prompt)
        self.assertEqual(manifest["execution_channel"],
                         "isolated_opencode_go_v2_subscription_readonly")
        self.assertEqual(manifest["pinned_route"],
                         json.loads((Path(manifest["run_dir"]) / "state.json")
                                    .read_text())["model_routes"]["reviewer"])
        self.assertEqual(manifest["route_sha256"],
                         orc.route_authorization_sha(manifest["pinned_route"]))
        self.assertEqual(manifest["profile_sha256"],
                         orc.content_hash(orc.opencode_profile("reviewer", "v2")))
        self.assertIn(str(root / "repo"),
                      manifest["negative_probes"]["write"]["path"])
        projection = json.loads(Path(manifest["manifest_path"]).read_text())
        self.assertIn("delta/attempt-1/app.py-0001.patch",
                      projection["files"])
        self.assertTrue(Path(manifest["verification_path"]).is_file())
        self.assertFalse((root / "evidence.json").exists())
        state = json.loads((Path(manifest["run_dir"]) / "state.json").read_text())
        record = state["batch_deltas"][-1]
        self.assertTrue(record["complete"])
        self.assertEqual(state["batch_delta_chain"][-1], record["job_id"])
        self.assertIn(record["job_id"], record["hunks_dir"])
        self.assertEqual(manifest["contract_version"], 2)
        preflight = subprocess.run(
            [sys.executable, str(self.script()), "preflight",
             "--root", str(root)],
            capture_output=True, text=True, timeout=300, env=env)
        payload = json.loads(preflight.stdout)
        self.assertTrue(payload["prepared_bindings"]["ok"])
        self.assertTrue(payload["prompt_declares_contract_v2"])
        self.assertFalse(payload["prompt_reveals_challenge"])
        self.assertIn("pinned_route", payload)
        self.assertEqual(payload["execution_channel"],
                         "isolated_opencode_go_v2_subscription_readonly")
        self.assertFalse((root / "evidence.json").exists())
        inspect = subprocess.run(
            [sys.executable, str(self.script()), "inspect", "--root", str(root)],
            capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(inspect.returncode, 2)

    def test_shipped_reviewer_profile_denies_shell_and_edit_but_allows_read(self):
        profile = orc.opencode_profile("reviewer", "v2")
        rules = profile["permissions"]
        orc.validate_v2_effective_permissions("reviewer", rules)
        self.assertEqual(orc.v2_effective_permission(rules, "read", "delta/a.patch"),
                         "allow")
        self.assertNotEqual(
            orc.v2_effective_permission(rules, "shell", "echo harmless"), "allow")
        self.assertNotEqual(
            orc.v2_effective_permission(rules, "edit", "probe.txt"), "allow")
        self.assertNotEqual(
            orc.v2_effective_permission(rules, "external_directory", "/tmp"),
            "allow")


sys.path.insert(0, str(Path(orc.HERE)))
import reviewer_smoke as smoke  # noqa: E402 - after the scripts path is known


SMOKE_REPO = "/tmp/opencode/abdullah-smoke-predicate-repo"
SMOKE_HUNK_REL = ".git/review/delta/attempt-1/app.py-0001.patch"
SMOKE_HUNK = SMOKE_REPO + "/" + SMOKE_HUNK_REL


def smoke_manifest(line="MAGIC_SENTINEL = 123456"):
    return {
        "version": 3,
        "repo": SMOKE_REPO,
        "challenge": {"name": "MAGIC_SENTINEL",
                      "value": int(line.rsplit(" ", 1)[-1]),
                      "line": line, "line_sha256": smoke._sha256_text(line)},
        "hunk_relpath": SMOKE_HUNK_REL,
        "hunk_path": SMOKE_HUNK,
        "hunk_sha256": "hunk-sha",
        "candidate_signature": "candidate-sha",
        "manifest_sha256": "manifest-sha",
        "projection_sha256": "projection-sha",
        "binding_sha256": "binding-sha",
        "verification_sha256": "verification-sha",
        "prompt_sha256": "prompt-sha",
        "profile_sha256": "profile-sha",
        "route_sha256": "route-sha",
        "config_policy_sha256": "policy-sha",
        "execution_channel": "isolated_opencode_go_v2_subscription_readonly",
        "pinned_route": {"provider": "opencode",
                         "worker_provider": "opencode-go",
                         "model": "opencode-go/deepseek-v4.1-flash",
                         "effort": "high", "billing": "go"},
        "negative_probes": {
            "shell": {"tool": "shell", "command": "echo abdullah-smoke-probe"},
            "write": {"tool": "edit",
                      "path": SMOKE_REPO + "/.reviewer-smoke-write-probe.txt"}},
    }


def smoke_readiness(**overrides):
    ready = {"ok": True, "problems": [], "route_bound": True,
             "prompt_bound": True, "policy_compatible": True,
             "compatibility": {"status": "current"},
             "prepared_bindings": {"ok": True}}
    ready.update(overrides)
    return ready


def negative_record(observation="denied", outcome=None):
    outcome = outcome or ("denied" if observation == "denied" else
                          "executed" if observation == "executed" else
                          "absent" if observation == "absent" else
                          "unverified")
    return {"probe": {"tool": "shell"}, "observation": observation,
            "outcome": outcome, "proven": outcome in {"denied", "absent"},
            "producing_session": "ses_producer", "attempts": [],
            "other_session_attempts": 0, "unrelated_attempts": 0,
            "inventory": smoke._runtime_inventory()}


def smoke_evidence(manifest, *, status="complete", read=None,
                   shell="denied", write="denied", executed=None,
                   unchanged=True, ingested=True, error=None,
                   job_route_matches=True):
    line = manifest["challenge"]["line"]
    path = manifest["hunk_relpath"]
    matched = read if read is not None else {
        "status": "completed", "session_id": "ses_producer",
        "path_matches": True, "challenge_found": True,
        "challenge_line": line, "path": path}
    report = {"contract_version": 2, "status": status,
              "summary": (f"Read {path} and saw `{line}`." if status == "complete"
                          else "The Read tool was refused"),
              "files": [], "tests": [], "evidence": [], "unknowns": [],
              "blocker": "" if status == "complete" else "read refused",
              "findings": []}
    return {
        "version": 3,
        "error": error,
        "job_route_matches": job_route_matches,
        "report_ingestion": {
            "ok": ingested, "contract_version": 2 if ingested else None,
            "report": report if ingested else None,
            "error": None if ingested else "ReportIngestionError: refused"},
        "runtime": {
            "event_count": 3, "producing_session": "ses_producer",
            "events_log_sha256": "raw-sha",
            "matched_read": matched,
            "read_events": [matched] if matched else [],
            "capability": {"shell": negative_record(shell),
                           "write": negative_record(write)},
            "prohibited_executed": executed or []},
        "source": {"before": "candidate-sha", "after": "candidate-sha",
                   "unchanged": unchanged,
                   "hunk_sha256": "hunk-sha",
                   "manifest_sha256": "manifest-sha",
                   "projection_sha256": "projection-sha",
                   "binding_sha256": "binding-sha",
                   "verification_sha256": "verification-sha"},
        "permissions": {
            "normalized_profile": {"read_hunk": "allow", "shell": "deny",
                                   "edit": "deny"},
            "profile_valid": True,
            "installed_agent_introspection": True},
    }


class ReviewerSmokePredicateTests(ReleaseFixture):
    """One predicate guards both launch and inspect; every refusal is tested."""

    live = {"ok": True, "candidate_signature": "candidate-sha"}

    def assess(self, evidence, live=None, manifest=None, readiness=None):
        return smoke._assess(manifest or smoke_manifest(), evidence,
                             live or self.live,
                             readiness or smoke_readiness())

    def test_complete_evidence_verifies(self):
        manifest = smoke_manifest()
        result = self.assess(smoke_evidence(manifest), manifest=manifest)
        self.assertTrue(result["ok"], result["reasons"])
        self.assertTrue(all(result["checks"].values()))

    def test_missing_read_is_refused(self):
        manifest = smoke_manifest()
        result = self.assess(smoke_evidence(manifest, read={}),
                             manifest=manifest)
        self.assertFalse(result["ok"])
        self.assertFalse(result["checks"]["read_verified"])
        self.assertIn("no completed, path-matched Read",
                      " ".join(result["reasons"]))

    def test_failed_read_is_refused(self):
        manifest = smoke_manifest()
        read = {"status": "error", "session_id": "ses_producer",
                "path_matches": True, "challenge_found": True,
                "challenge_line": manifest["challenge"]["line"]}
        result = self.assess(smoke_evidence(manifest, read=read),
                             manifest=manifest)
        self.assertFalse(result["checks"]["read_completed"])
        self.assertFalse(result["ok"])

    def test_unrelated_path_read_is_refused(self):
        manifest = smoke_manifest()
        read = {"status": "completed", "session_id": "ses_producer",
                "path_matches": False, "challenge_found": True,
                "challenge_line": manifest["challenge"]["line"]}
        result = self.assess(smoke_evidence(manifest, read=read),
                             manifest=manifest)
        self.assertFalse(result["checks"]["read_path_matched"])
        self.assertFalse(result["ok"])

    def test_wrong_session_read_is_refused(self):
        manifest = smoke_manifest()
        read = {"status": "completed", "session_id": "ses_other",
                "path_matches": True, "challenge_found": True,
                "challenge_line": manifest["challenge"]["line"]}
        result = self.assess(smoke_evidence(manifest, read=read),
                             manifest=manifest)
        self.assertFalse(result["checks"]["read_session_matched"])
        self.assertFalse(result["ok"])

    def test_blocked_report_is_refused(self):
        manifest = smoke_manifest()
        result = self.assess(
            smoke_evidence(manifest, status="blocked"), manifest=manifest)
        self.assertFalse(result["checks"]["report_complete"])
        self.assertFalse(result["ok"])

    def test_rejected_ingestion_is_refused(self):
        manifest = smoke_manifest()
        result = self.assess(
            smoke_evidence(manifest, ingested=False), manifest=manifest)
        self.assertFalse(result["checks"]["report_ingested"])
        self.assertFalse(result["ok"])

    def test_checkout_or_binding_drift_is_refused(self):
        manifest = smoke_manifest()
        result = self.assess(
            smoke_evidence(manifest, unchanged=False), manifest=manifest)
        self.assertFalse(result["checks"]["checkout_unchanged"])
        result = self.assess(
            smoke_evidence(manifest), live={"ok": False,
                                            "candidate_signature":
                                                "candidate-sha"},
            manifest=manifest)
        self.assertFalse(result["checks"]["bindings_intact"])
        self.assertFalse(result["ok"])

    def test_executed_capability_or_prohibited_tool_is_refused(self):
        manifest = smoke_manifest()
        result = self.assess(
            smoke_evidence(manifest, shell="executed"), manifest=manifest)
        self.assertFalse(result["checks"]["negative_shell"])
        result = self.assess(
            smoke_evidence(manifest, executed=[{"tool": "write"}]),
            manifest=manifest)
        self.assertFalse(result["checks"]["no_prohibited_execution"])
        self.assertFalse(result["ok"])

    def test_unverified_negative_keeps_read_separate(self):
        manifest = smoke_manifest()
        evidence = smoke_evidence(manifest, shell="not_observed",
                                  write="not_observed")
        result = self.assess(evidence, manifest=manifest)
        self.assertTrue(result["checks"]["read_verified"])
        self.assertFalse(result["checks"]["negative_shell"])
        self.assertFalse(result["checks"]["negative_evidence_verified"])
        self.assertFalse(result["ok"])

    def test_readiness_route_prompt_or_policy_drift_is_refused(self):
        manifest = smoke_manifest()
        evidence = smoke_evidence(manifest)
        for overrides in ({"route_bound": False},
                          {"prompt_bound": False},
                          {"policy_compatible": False},
                          {"ok": False, "problems": ["policy"]}):
            with self.subTest(overrides=overrides):
                result = self.assess(
                    evidence, manifest=manifest,
                    readiness=smoke_readiness(**overrides))
                self.assertFalse(result["ok"])

    def test_job_route_mismatch_is_refused(self):
        manifest = smoke_manifest()
        result = self.assess(
            smoke_evidence(manifest, job_route_matches=False),
            manifest=manifest)
        self.assertFalse(result["checks"]["job_route_matches"])
        self.assertFalse(result["ok"])

    def test_simulated_stream_end_to_end_verifies(self):
        manifest = smoke_manifest()
        line = manifest["challenge"]["line"]
        report = {
            "contract_version": 2, "status": "complete",
            "summary": f"Read {manifest['hunk_relpath']} and saw `{line}`.",
            "files": [], "tests": [], "evidence": [manifest["hunk_relpath"],
                                                   line],
            "unknowns": [], "blocker": "", "findings": []}
        events = [
            {"type": "tool_use", "sessionID": "ses_producer", "part": {
                "type": "tool", "tool": "read", "sessionID": "ses_producer",
                "state": {"status": "completed",
                          "input": {"filePath": manifest["hunk_path"]},
                          "output": ("00001| def value():\n"
                                     f"00002| {line}\n")}}},
            {"type": "tool_use", "sessionID": "ses_producer", "part": {
                "type": "tool", "tool": "shell", "sessionID": "ses_producer",
                "state": {"status": "error",
                          "error": "permission denied: shell is denied",
                          "input": {"command": "echo abdullah-smoke-probe"}}}},
            {"type": "tool_use", "sessionID": "ses_producer", "part": {
                "type": "tool", "tool": "edit", "sessionID": "ses_producer",
                "state": {"status": "error",
                          "error": "permission denied: edit is denied",
                          "input": {"filePath": manifest["negative_probes"][
                              "write"]["path"]}}}},
            {"type": "text", "sessionID": "ses_producer", "part": {
                "text": json.dumps(report)}},
            {"type": "step_finish", "sessionID": "ses_producer", "part": {
                "type": "step-finish", "reason": "stop"}},
        ]
        raw = "\n".join(json.dumps(item) for item in events) + "\n"
        runtime = smoke._analyse_events(raw, manifest, "ses_producer")
        self.assertTrue(runtime["matched_read"])
        self.assertEqual(runtime["capability"]["shell"]["outcome"], "denied")
        self.assertEqual(runtime["capability"]["write"]["outcome"], "denied")
        self.assertTrue(runtime["capability"]["shell"]["proven"])
        ingestion = smoke._ingest(orc, raw, self.root / "job", "ses_producer")
        self.assertTrue(ingestion["ok"], ingestion["error"])
        evidence = smoke_evidence(manifest)
        evidence["runtime"] = {**runtime, "producing_session": "ses_producer",
                               "events_log_sha256": "raw-sha"}
        evidence["report_ingestion"] = ingestion
        result = self.assess(evidence, manifest=manifest)
        self.assertTrue(result["ok"], result["reasons"])

    def test_wrong_file_stream_does_not_match_even_with_the_answer(self):
        manifest = smoke_manifest()
        line = manifest["challenge"]["line"]
        events = [
            {"type": "tool_use", "sessionID": "ses_producer", "part": {
                "type": "tool", "tool": "read", "sessionID": "ses_producer",
                "state": {"status": "completed",
                          "input": {"filePath": "app.py"},
                          "output": f"00009| {line}\n"}}},
        ]
        raw = "\n".join(json.dumps(item) for item in events) + "\n"
        runtime = smoke._analyse_events(raw, manifest, "ses_producer")
        self.assertIsNone(runtime["matched_read"])

    def test_foreign_hunk_suffix_is_not_the_prepared_hunk(self):
        manifest = smoke_manifest()
        foreign = "/tmp/foreign-checkout/" + manifest["hunk_relpath"]
        self.assertFalse(smoke._path_matches(foreign, manifest))
        self.assertTrue(smoke._path_matches(manifest["hunk_path"], manifest))
        line = manifest["challenge"]["line"]
        events = [
            {"type": "tool_use", "sessionID": "ses_producer", "part": {
                "type": "tool", "tool": "read", "sessionID": "ses_producer",
                "state": {"status": "completed",
                          "input": {"filePath": foreign},
                          "output": f"00002| {line}\n"}}},
        ]
        raw = "\n".join(json.dumps(item) for item in events) + "\n"
        runtime = smoke._analyse_events(raw, manifest, "ses_producer")
        self.assertIsNone(runtime["matched_read"])

    def test_generic_error_and_wrong_session_are_not_denials(self):
        manifest = smoke_manifest()
        base = {"type": "tool_use", "sessionID": "ses_producer", "part": {
            "type": "tool", "tool": "shell", "sessionID": "ses_producer",
            "state": {"status": "error", "error": "upstream failed",
                      "input": {"command": "echo abdullah-smoke-probe"}}}}
        raw = json.dumps(base) + "\n"
        runtime = smoke._analyse_events(raw, manifest, "ses_producer")
        record = runtime["capability"]["shell"]
        self.assertEqual(record["observation"], "generic_error")
        self.assertEqual(record["outcome"], "failed_unclassified")
        self.assertFalse(record["proven"])
        wrong = copy.deepcopy(base)
        wrong["part"]["sessionID"] = "ses_other"
        wrong["sessionID"] = "ses_other"
        wrong["part"]["state"]["error"] = "permission denied"
        runtime = smoke._analyse_events(json.dumps(wrong) + "\n",
                                        manifest, "ses_producer")
        record = runtime["capability"]["shell"]
        self.assertEqual(record["observation"], "other_session_only")
        self.assertEqual(record["outcome"], "unverified")
        self.assertFalse(record["proven"])

    def test_unrelated_command_is_not_the_probe(self):
        manifest = smoke_manifest()
        event = {"type": "tool_use", "sessionID": "ses_producer", "part": {
            "type": "tool", "tool": "shell", "sessionID": "ses_producer",
            "state": {"status": "error", "error": "permission denied",
                      "input": {"command": "echo something-else"}}}}
        runtime = smoke._analyse_events(json.dumps(event) + "\n",
                                        manifest, "ses_producer")
        record = runtime["capability"]["shell"]
        self.assertEqual(record["observation"], "not_observed")
        self.assertEqual(record["outcome"], "unverified")
        self.assertEqual(record["unrelated_attempts"], 1)

    def test_authoritative_inventory_can_prove_absence(self):
        manifest = smoke_manifest()
        inventory = {"available": True, "source": "test",
                     "tools": {"read": True}, "detail": "inventory"}
        runtime = smoke._analyse_events("", manifest, "ses_producer",
                                        inventory)
        self.assertEqual(runtime["capability"]["shell"]["outcome"], "absent")
        self.assertTrue(runtime["capability"]["shell"]["proven"])

    @staticmethod
    def probe_event(tool, *, command=None, path=None, session="ses_producer",
                    status="error", message=None, output=None):
        state = {"status": status,
                 "input": ({"command": command} if command is not None
                           else {"filePath": path})}
        if status == "completed":
            state["output"] = output if output is not None else "done"
        else:
            state["error"] = message if message is not None else (
                f'No tool named "{tool}" is currently available. '
                'Please use a tool from the available tool list.')
        return {"type": "tool_use", "sessionID": session, "part": {
            "type": "tool", "tool": tool, "sessionID": session,
            "state": state}}

    def test_exact_runtime_absence_proves_the_exact_tool(self):
        manifest = smoke_manifest()
        probes = manifest["negative_probes"]
        events = [
            self.probe_event("shell", command="echo abdullah-smoke-probe"),
            self.probe_event("edit", path=probes["write"]["path"]),
        ]
        raw = "\n".join(json.dumps(item) for item in events) + "\n"
        runtime = smoke._analyse_events(raw, manifest, "ses_producer")
        for name, tool in (("shell", "shell"), ("write", "edit")):
            record = runtime["capability"][name]
            self.assertEqual(record["observation"], "absent")
            self.assertEqual(record["outcome"], "absent")
            self.assertTrue(record["proven"])
            self.assertEqual(record["attempts"][0]["classification"], "absent")
            self.assertEqual(record["attempts"][0]["absent_tool"], tool)
            self.assertEqual(record["attempts"][0]["session_id"],
                             "ses_producer")

    def test_absence_is_not_promoted_without_exact_tool_attempt_and_session(self):
        manifest = smoke_manifest()
        command = "echo abdullah-smoke-probe"
        path = manifest["negative_probes"]["write"]["path"]
        exact = ('No tool named "shell" is currently available. Please use a '
                 'tool from the available tool list.')
        cases = {
            "different write-family tool than the prepared edit probe":
                (self.probe_event("write", path=path,
                                  message=exact.replace('"shell"', '"write"')),
                 "write"),
            "runtime names a different tool than the event":
                (self.probe_event("shell", command=command,
                                  message='No tool named "write" is currently '
                                          'available. Please use a tool from '
                                          'the available tool list.'),
                 "shell"),
            "attempt in another session":
                (self.probe_event("shell", command=command,
                                  session="ses_other"),
                 "shell"),
            "changed runtime wording":
                (self.probe_event("shell", command=command,
                                  message='No tool named "shell" is currently '
                                          'available now.'),
                 "shell"),
            "absence text in a completed output":
                (self.probe_event("shell", command=command, status="completed",
                                  output=exact),
                 "shell"),
        }
        for label, (event, capability) in cases.items():
            with self.subTest(label=label):
                runtime = smoke._analyse_events(json.dumps(event) + "\n",
                                                manifest, "ses_producer")
                record = runtime["capability"][capability]
                self.assertFalse(record["proven"])
                self.assertNotEqual(record["outcome"], "absent")

    def test_absence_message_on_an_unrelated_command_is_not_the_probe(self):
        manifest = smoke_manifest()
        event = self.probe_event("shell", command="echo something-else")
        runtime = smoke._analyse_events(json.dumps(event) + "\n",
                                        manifest, "ses_producer")
        record = runtime["capability"]["shell"]
        self.assertEqual(record["observation"], "not_observed")
        self.assertEqual(record["outcome"], "unverified")
        self.assertEqual(record["unrelated_attempts"], 1)

    def test_saved_absence_is_rederived_from_the_raw_stream(self):
        manifest = smoke_manifest()
        root = self.root / "inspect-absence"
        job = root / "job"
        job.mkdir(parents=True)
        line = manifest["challenge"]["line"]
        read = {"type": "tool_use", "sessionID": "ses_producer", "part": {
            "type": "tool", "tool": "read", "sessionID": "ses_producer",
            "state": {"status": "completed",
                      "input": {"filePath": manifest["hunk_path"]},
                      "output": f"00002| {line}\n"}}}
        raw_path = job / "events.log"
        raw_path.write_text(json.dumps(read) + "\n")
        evidence = smoke_evidence(manifest, shell="absent", write="absent")
        evidence["job"] = {"path": str(job), "session_id": "ses_producer"}
        evidence["runtime"] = {**evidence["runtime"],
                               "events_log": str(raw_path),
                               "events_log_sha256":
                                   smoke._sha256_file(raw_path),
                               "producing_session": "ses_producer"}
        derived, problems = smoke._rederive_event_evidence(
            root, manifest, evidence, orc)
        self.assertEqual(problems, [])
        self.assertEqual(
            derived["runtime"]["capability"]["shell"]["outcome"], "unverified")
        assessment = smoke._assess(
            manifest, derived, self.live, smoke_readiness())
        self.assertFalse(assessment["ok"])
        self.assertFalse(assessment["checks"]["negative_shell"])
        self.assertFalse(assessment["checks"]["negative_write"])

    def test_inspect_requires_the_exact_raw_stream(self):
        manifest = smoke_manifest()
        root = self.root / "inspect-stream"
        root.mkdir()
        job = root / "job"
        job.mkdir()
        raw_path = job / "events.log"
        raw_path.write_text('{"type":"text","part":{"text":"x"}}\n')
        evidence = {
            "version": 3, "job": {"path": str(job),
                                  "session_id": "ses_producer"},
            "runtime": {"events_log": str(raw_path),
                        "events_log_sha256": smoke._sha256_file(raw_path),
                        "producing_session": "ses_producer"}}
        derived, problems = smoke._rederive_event_evidence(
            root, manifest, evidence, orc)
        self.assertEqual(problems, [])
        self.assertIn("runtime", derived)
        raw_path.write_text('{"type":"text","part":{"text":"changed"}}\n')
        derived, problems = smoke._rederive_event_evidence(
            root, manifest, evidence, orc)
        self.assertIsNone(derived)
        self.assertIn("changed", " ".join(problems))


class WriterLimitationDiagnosticsTests(ReleaseFixture):
    """Both retained-index and rebuild reasons survive into the packet."""

    def _boundary_and_state(self, job_id):
        plan = self.plan()
        state = self.saved(self.state(phase="implement", plan=plan,
                                      plan_version=orc.content_hash(plan)))
        boundary = orc.capture_batch_boundary(
            self.project, self.rundir, job_id, batch_index=0,
            plan_version=state["plan_version"])
        return state, boundary

    def test_dual_failure_preserves_the_secondary_retained_reason(self):
        job_id = "impl-dual-failure"
        state, boundary = self._boundary_and_state(job_id)
        (self.project / "app.py").write_text("value = 12\n")
        snapshot = orc.source_snapshot(self.project)
        with patch.object(orc, "_reusable_delta_index",
                          return_value=(None, "retained boom")), \
                patch.object(orc, "finalize_batch_delta", return_value=None):
            record = orc._record_batch_delta(
                self.rundir, state, self.project, job_id, boundary, snapshot,
                phase="completion")
        self.assertFalse(record["complete"])
        detail = " ".join(str(item.get("detail"))
                          for item in record["limitations"])
        self.assertIn("retained boom", detail)
        self.assertIn("finaliz", detail.lower())


if __name__ == "__main__":
    unittest.main()
