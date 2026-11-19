"""Release-closure gates: config policy, model metadata and role switching.

All checks are local and deterministic.  Fake CLIs establish adapter parsing;
a separate operator smoke exercises the real authenticated Reviewer route.
"""
from __future__ import annotations

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
        self.assertIn("gpt-any-9.9", catalogue["models"])
        self.assertIn("gpt-page-two", catalogue["models"])

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
                            "variants": ["high", "medium"]}}}

    def test_preview_is_read_only_and_tied_to_the_route_identity(self):
        self.prepared()
        before = (self.rundir / "state.json").read_bytes()
        with patch.object(orc, "model_catalogue",
                          return_value=self.confirmed_catalogue()):
            preview = orc.preview_role_switch(
                "test-v12000", "reviewer", self.route_spec())
        self.assertEqual((self.rundir / "state.json").read_bytes(), before)
        self.assertFalse(preview["applied"])
        self.assertTrue(preview["expected_confirmation"].startswith(
            "switch-role:test-v12000:reviewer:"))
        with patch.object(orc, "model_catalogue",
                          return_value=self.confirmed_catalogue()):
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
        with patch.object(orc, "model_catalogue",
                          return_value=self.confirmed_catalogue()):
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
        with patch.object(orc, "model_catalogue",
                          return_value=self.confirmed_catalogue()):
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
                with patch.object(orc, "model_catalogue",
                                  return_value=self.confirmed_catalogue()):
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
        with patch.object(orc, "model_catalogue",
                          return_value=self.confirmed_catalogue()):
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
        with patch.object(orc, "model_catalogue",
                          return_value=self.confirmed_catalogue()):
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
        hunk = Path(manifest["hunk_path"]).read_text(encoding="utf-8")
        self.assertIn("MAGIC_SENTINEL = 314159", hunk)
        prompt = Path(manifest["prompt_path"]).read_text(encoding="utf-8")
        self.assertNotIn("314159", prompt)
        self.assertNotIn("MAGIC_SENTINEL", prompt)
        self.assertIn(manifest["hunk_relpath"], prompt)
        projection = json.loads(Path(manifest["manifest_path"]).read_text())
        self.assertIn("delta/attempt-1/app.py-0001.patch", projection["files"])
        self.assertTrue(Path(manifest["verification_path"]).is_file())
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
