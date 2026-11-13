"""v3.1 schema-3 migration: recorded routes only, backup-first and reversible."""
from __future__ import annotations

import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import test_orchestrator as baseline
orc = baseline.orc


def recorded_routes():
    return {
        "architect": {"provider": "codex", "model": "gpt-6.1-sol",
                      "effort": "high", "billing": "subscription"},
        "explorer": {"provider": "opencode", "model": "opencode-go/small",
                     "effort": "low", "billing": "go"},
        "implementer": {"provider": "opencode", "model": "opencode-go/large",
                        "effort": "high", "billing": "go"},
        "reviewer": {"provider": "opencode", "model": "opencode-go/large",
                     "effort": "high", "billing": "go"},
    }


class RouteMigrationTests(unittest.TestCase):
    setUp = baseline.ControlTests.setUp
    tearDown = baseline.ControlTests.tearDown

    def legacy_state(self, **updates):
        self.state.update({
            "schema_version": 2,
            "config_schema_version": 2,
            "status": "paused",
            "phase": "accept",
            "plan": {"batches": [{"title": "one", "checks": [["true"]]}]},
            "plan_version": "plan-v1",
            "model_routes": recorded_routes(),
            "verification": {"path": "/old/verification.json", "passed": True},
            "review": {"status": "complete", "findings": []},
            "check_progress": {"identity": {}, "finished": True},
            "single_batch_verification": {"path": "/old/batch.json"},
            "architect_verdict": {"verdict": "approved"},
            "final_verdict": {"verdict": "approved"},
            "accepted_batches": [{"index": 0}],
            "completed_jobs": [
                {"id": "decision-1", "kind": "decision", "role": "architect",
                 "status": "complete", "path": "/old/decision"},
                {"id": "impl-1", "kind": "implementer", "role": "implementer",
                 "status": "complete", "path": "/old/impl",
                 "route": {"provider": "opencode", "model": "opencode-go/large",
                           "effort": "high", "billing": "go"}}],
        })
        self.state.update(updates)
        orc.save(self.rundir, self.state)
        return self.state

    def test_backup_first_migration_uses_recorded_routes_and_invalidates_approvals(self):
        self.legacy_state()
        before_bytes = (self.rundir / "state.json").read_bytes()
        before = orc.state_compatibility(self.state)
        self.assertEqual(before["status"], "migration_required")
        result = orc.migrate_run("test-run00", backup_dir=self.root / "backups")
        self.assertTrue(result["migrated"])
        self.assertTrue(Path(result["backup"]).is_file())
        self.assertEqual(Path(result["backup"]).read_bytes(), before_bytes)
        state = orc.read_json(self.rundir / "state.json")
        self.assertEqual(state["schema_version"], orc.STATE_SCHEMA_VERSION)
        self.assertEqual(state["config_schema_version"], orc.CONFIG_SCHEMA_VERSION)
        self.assertEqual(state["migration_route_source"], "recorded_routes")
        for role in ("explorer", "implementer", "reviewer"):
            self.assertEqual(state["model_routes"][role]["worker_provider"], "opencode-go")
        self.assertIsNone(state["verification"])
        self.assertIsNone(state["review"])
        self.assertIsNone(state["check_progress"])
        self.assertIsNone(state["final_verdict"])
        self.assertEqual(state["phase"], "verify")
        self.assertIn("decision-1", [job["id"] for job in
                                     state["migration_invalidated_jobs"]])
        self.assertNotIn("decision-1", [job["id"] for job in state["completed_jobs"]])
        self.assertEqual(state["status"], "paused")
        self.assertEqual(state["accepted_batches"], [{"index": 0}])
        self.assertEqual(orc.state_compatibility(state)["status"], "current")

    def test_rollback_restores_the_pre_migration_state(self):
        self.legacy_state()
        result = orc.migrate_run("test-run00", backup_dir=self.root / "backups")
        restored = orc.restore_run("test-run00", result["backup"], "restore")
        self.assertTrue(restored["ok"])
        state = orc.read_json(self.rundir / "state.json")
        self.assertEqual(state["schema_version"], 2)
        self.assertEqual(state["verification"], {"path": "/old/verification.json",
                                                 "passed": True})
        self.assertEqual(state["review"], {"status": "complete", "findings": []})
        self.assertIn("decision-1", [job["id"] for job in state["completed_jobs"]])
        self.assertEqual(restored["compatibility"]["status"], "migration_required")

    def test_insufficient_recorded_routes_block_without_writing(self):
        self.legacy_state(model_routes={}, completed_jobs=[])
        before = (self.rundir / "state.json").read_bytes()
        with self.assertRaisesRegex(RuntimeError, "Insufficient recorded route"):
            orc.migrate_run("test-run00", backup_dir=self.root / "backups")
        self.assertEqual((self.rundir / "state.json").read_bytes(), before)
        self.assertFalse((self.root / "backups").exists())

    def test_explicit_route_mapping_is_reviewed_and_applied(self):
        self.legacy_state(model_routes={}, completed_jobs=[])
        mapping = recorded_routes()
        mapping["implementer"] = {"provider": "opencode-zen",
                                  "model": "opencode-zen/model", "effort": "high",
                                  "billing": "api"}
        result = orc.migrate_run("test-run00", backup_dir=self.root / "backups",
                                 route_map=mapping)
        self.assertEqual(result["route_source"], "explicit_mapping")
        state = orc.read_json(self.rundir / "state.json")
        self.assertEqual(state["model_routes"]["implementer"]["worker_provider"],
                         "opencode-zen")
        self.assertEqual(state["model_routes"]["implementer"]["billing"], "api")

    def test_jobs_supply_routes_when_model_routes_are_missing(self):
        routes = recorded_routes()
        jobs = [{"id": role, "kind": role, "role": role, "status": "complete",
                 "route": route} for role, route in routes.items()]
        self.legacy_state(model_routes={}, completed_jobs=jobs)
        result = orc.migrate_run("test-run00", backup_dir=self.root / "backups")
        state = orc.read_json(self.rundir / "state.json")
        self.assertEqual(result["route_source"], "recorded_routes")
        self.assertEqual(state["model_routes"]["architect"]["model"], "gpt-6.1-sol")

    def test_active_or_running_migration_is_refused(self):
        self.legacy_state(active_job={"id": "live"})
        with self.assertRaisesRegex(RuntimeError, "active or uncertain"):
            orc.migrate_run("test-run00", backup_dir=self.root / "backups")
        self.legacy_state(active_job=None, status="running")
        with self.assertRaisesRegex(RuntimeError, "Interrupt and pause"):
            orc.migrate_run("test-run00", backup_dir=self.root / "backups")

    def test_newer_state_schema_is_rejected(self):
        self.legacy_state(schema_version=orc.STATE_SCHEMA_VERSION + 1)
        with self.assertRaisesRegex(RuntimeError, "newer"):
            orc.migrate_run("test-run00", backup_dir=self.root / "backups")

    def test_integrate_migration_stays_integrate_but_clears_evidence(self):
        self.legacy_state(phase="integrate", batch_index=2)
        orc.migrate_run("test-run00", backup_dir=self.root / "backups")
        state = orc.read_json(self.rundir / "state.json")
        self.assertEqual(state["phase"], "integrate")
        self.assertIsNone(state["verification"])
        self.assertIsNone(state["check_progress"])
        self.assertIsNone(state["final_verdict"])

    def test_legacy_config_is_normalized_in_memory_without_rewriting_it(self):
        cfg = orc.read_json(orc.HERE / "config.example.json")
        cfg["schema_version"] = 2
        for spec in cfg["workers"].values():
            spec.pop("provider", None)
        orc.atomic_json(orc.CONFIG_PATH, cfg)
        before = Path(orc.CONFIG_PATH).read_bytes()
        loaded = orc.config()
        self.assertEqual(loaded["schema_version"], 2)
        route = orc.model_route(loaded, "codex", "implementer")
        self.assertEqual(route["worker_provider"], "opencode-go")
        self.assertEqual(route["billing"], "go")
        self.assertEqual(Path(orc.CONFIG_PATH).read_bytes(), before)

    def test_newer_config_schema_is_rejected(self):
        cfg = orc.read_json(orc.HERE / "config.example.json")
        cfg["schema_version"] = orc.CONFIG_SCHEMA_VERSION + 1
        orc.atomic_json(orc.CONFIG_PATH, cfg)
        with self.assertRaisesRegex(ValueError, "newer"):
            orc.config()

    def test_inconsistent_recorded_route_is_rejected(self):
        routes = recorded_routes()
        routes["implementer"] = {"provider": "opencode",
                                 "worker_provider": "other",
                                 "model": "opencode-zen/model",
                                 "effort": "high", "billing": "api"}
        self.legacy_state(model_routes=routes)
        with self.assertRaisesRegex(ValueError, "contradicts model prefix"):
            orc.migrate_run("test-run00", backup_dir=self.root / "backups")


if __name__ == "__main__":
    unittest.main()
