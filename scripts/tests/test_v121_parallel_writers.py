"""v1.2.1 permission-bounded parallel writers, integration and recovery.

The model boundary is faked; worktrees, patches and the canonical checkout are
real Git state, so skipped launches, double integration and lost edits are
observable.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import test_orchestrator as baseline

orc = baseline.orc


def writer(writer_id, path=None, component=None):
    return {
        "id": writer_id,
        "goal": f"Implement {writer_id}",
        "paths": [path] if path else [],
        "components": [component] if component else [],
        "completion_criteria": f"{writer_id} slice is complete",
        "role": "implementer",
    }


def report(summary="writer complete"):
    return {"contract_version": 2, "status": "complete", "summary": summary,
            "files": [], "tests": [], "evidence": ["writer evidence"],
            "unknowns": [], "blocker": ""}


class ParallelWriterTests(unittest.TestCase):
    setUp = baseline.ControlTests.setUp
    tearDown = baseline.ControlTests.tearDown

    def prepare(self, writers, max_writers=3):
        plan = {"contract_version": 2, "status": "complete",
                "summary": "plan", "invariants": ["Keep behavior"],
                "batches": [{"title": "feature", "goal": "change app",
                             "acceptance": ["works"],
                             "checks": [[sys.executable, "-c",
                                         "raise SystemExit(0)"]],
                             "risk": "ordinary",
                             "verification_purpose": None,
                             "repeat_checks": None,
                             "writers": writers}],
                "blocker": "", "required_exploration": {
                    "job_id": "", "scope_satisfied": True}}
        self.state.update({
            "status": "running", "phase": "implement",
            "plan_version": orc.content_hash(plan), "plan_revision": 1,
            "batch_index": 0, "corrections": 0, "correction": "",
            "parallel_permission": {"max_writers": max_writers,
                                    "enabled": max_writers > 1},
            "plan": plan,
            "completed_jobs": [], "failed_jobs": [], "batch_deltas": [],
        })
        orc.save(self.rundir, self.state)
        batch = self.state["plan"]["batches"][0]
        resolved = orc.resolve_parallel_batch(self.state, self.project, batch)
        return batch, resolved

    def fake_model(self, writes, starts=None, fail=None, interrupt=None):
        starts = starts if starts is not None else []
        count = {"n": 0}

        def fake(run_dir, state, cfg, role, kind, prompt, project, **kwargs):
            count["n"] += 1
            writer_id = kwargs.get("assignment")
            starts.append(writer_id)
            project = Path(project)
            if interrupt and writer_id in interrupt:
                (project / f"{writer_id}.py").write_text("partial\n")
                raise InterruptedError("run pause requested")
            if fail and writer_id in fail:
                (project / f"{writer_id}.py").write_text("partial\n")
                raise RuntimeError(f"{writer_id} failed after partial work")
            for relative, data in writes.get(writer_id, {}).items():
                path = project / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(data)
            job = {"id": f"job-{writer_id}", "role": "implementer",
                   "kind": "implementer",
                   "path": str(Path(run_dir) / "jobs" / f"implementer-{writer_id}"),
                   "status": "complete", "assignment": writer_id}
            return report(f"{writer_id} finished"), job

        fake.starts = starts
        fake.count = count
        return fake

    def test_two_writers_integrate_on_one_pinned_base(self):
        batch, resolved = self.prepare([writer("a", path="a.py"),
                                        writer("b", path="b.py")])
        self.assertEqual(resolved["mode"], "parallel")
        fake = self.fake_model({"a": {"a.py": "a = 1\n"},
                                "b": {"b.py": "b = 2\n"}})
        with patch.object(orc, "call_model", side_effect=fake):
            result = orc.run_parallel_batch(
                self.rundir, self.state, self.cfg, self.project, batch, resolved,
                None)
        self.assertIsNotNone(result)
        self.assertEqual(fake.count["n"], 2)
        self.assertEqual(sorted(fake.starts), ["a", "b"])
        self.assertEqual((self.project / "a.py").read_text(), "a = 1\n")
        self.assertEqual((self.project / "b.py").read_text(), "b = 2\n")
        self.assertEqual(self.state["parallel_integration"]["phase"], "complete")
        self.assertEqual(sorted(self.state["parallel_writers"]["lanes"]), ["a", "b"])
        for lane in self.state["parallel_writers"]["lanes"].values():
            self.assertEqual(lane["status"], "complete")
            self.assertTrue(lane["patch"]["sha256"])
            self.assertTrue(lane["worktree_removed"])
        self.assertEqual(len(self.state["batch_deltas"]), 1)
        self.assertEqual({item["path"] for item in
                          self.state["batch_deltas"][0]["paths"]},
                         {"a.py", "b.py"})
        self.assertTrue(self.state["batch_deltas"][0]["complete"])
        self.assertIn("parallel_writer_attribution",
                      orc.batch_delta_index(self.state))

    def test_three_writers_components_and_exact_paths(self):
        batch, resolved = self.prepare([
            writer("one", component="pkg/one"),
            writer("two", component="pkg/two"),
            writer("three", path="top.txt")])
        fake = self.fake_model({
            "one": {"pkg/one/mod.py": "one = 1\n"},
            "two": {"pkg/two/mod.py": "two = 2\n"},
            "three": {"top.txt": "top\n"},
        })
        with patch.object(orc, "call_model", side_effect=fake):
            result = orc.run_parallel_batch(
                self.rundir, self.state, self.cfg, self.project, batch, resolved,
                None)
        self.assertIsNotNone(result)
        self.assertEqual(fake.count["n"], 3)
        self.assertEqual((self.project / "pkg/one/mod.py").read_text(), "one = 1\n")
        self.assertEqual((self.project / "pkg/two/mod.py").read_text(), "two = 2\n")
        self.assertEqual((self.project / "top.txt").read_text(), "top\n")
        self.assertEqual(self.state["parallel_writers"]["timing"][
                             "sum_writer_seconds"] >= 0, True)

    def test_full_parallel_lifecycle_reviews_combined_candidate_once(self):
        batch, resolved = self.prepare([writer("a", path="a.py"),
                                        writer("b", path="b.py")])
        self.state.update({"single_batch_fast_path": True,
                           "review": None, "implementation": None,
                           "verification": None})
        orc.save(self.rundir, self.state)
        reviewer_calls = []

        def fake_model(run_dir, state, cfg, role, kind, prompt, project, **kwargs):
            project = Path(project)
            if role == "reviewer":
                reviewer_calls.append(str(project))
                self.assertIn("a = 1", (project / "a.py").read_text())
                self.assertIn("b = 2", (project / "b.py").read_text())
                return ({"contract_version": 2, "status": "complete",
                         "summary": "reviewed combined source", "files": ["a.py", "b.py"],
                         "tests": [], "evidence": ["a.py", "b.py"],
                         "unknowns": [], "blocker": "", "findings": []},
                        {"id": f"review-{len(reviewer_calls)}", "role": "reviewer",
                         "kind": "reviewer", "status": "complete",
                         "path": str(Path(run_dir) / "jobs" / "reviewer-1"),
                         "route": {"provider": "opencode"}})
            writer_id = kwargs.get("assignment")
            writes = {"a": {"a.py": "a = 1\n"}, "b": {"b.py": "b = 2\n"}}
            for relative, data in writes[writer_id].items():
                (project / relative).write_text(data)
            return report(f"{writer_id} finished"), {
                "id": f"job-{writer_id}", "role": "implementer",
                "kind": "implementer",
                "path": str(Path(run_dir) / "jobs" / f"implementer-{writer_id}")}

        def approve(run_dir, state, cfg, kind, extra=None, **kwargs):
            references = ([state["single_batch_verification"], state["verification"]]
                          if state.get("single_batch_verification")
                          else [state["verification"]])
            state["decision_binding"] = orc.make_decision_binding(
                state, self.project, references)
            return {"contract_version": 2, "verdict": "approved",
                    "reason": "combined candidate inspected",
                    "inspected": ["a.py", "b.py"], "correction": "",
                    "dismissed_findings": []}

        with patch.object(orc, "call_model", side_effect=fake_model), \
                patch.object(orc, "strong_call", side_effect=approve):
            orc.advance(self.rundir, self.state, self.cfg)  # implement
            self.assertEqual(self.state["phase"], "verify")
            orc.advance(self.rundir, self.state, self.cfg)  # verify combined source
            self.assertEqual(self.state["phase"], "review")
            orc.advance(self.rundir, self.state, self.cfg)  # fresh reviewer
            self.assertEqual(self.state["phase"], "accept",
                             self.state.get("pause_reason"))
            orc.advance(self.rundir, self.state, self.cfg)  # strong decision
        self.assertEqual(self.state["status"], "complete")
        self.assertEqual(len(reviewer_calls), 1)
        self.assertEqual(self.state["final_acceptance"]["mode"],
                         "reused_supervisor_verification")
        source = self.state["final_evidence"]["reuse"]["sources"][0]
        self.assertTrue(source["path"])
        self.assertTrue(source["sha256"])
        self.assertEqual(sorted(self.state["parallel_writers"]["lanes"]), ["a", "b"])

    def test_one_writer_permission_falls_back_with_reason(self):
        batch, resolved = self.prepare([writer("a", path="a.py"),
                                        writer("b", path="b.py")],
                                       max_writers=1)
        self.assertEqual(resolved["mode"], "single")
        self.assertIn("permits 1", resolved["reason"])

    def test_dirty_source_selects_one_writer_with_durable_reason(self):
        (self.project / "untracked.txt").write_text("user work\n")
        batch, resolved = self.prepare([writer("a", path="a.py"),
                                        writer("b", path="b.py")])
        self.assertEqual(resolved["mode"], "single")
        self.assertIn("dirty", resolved["reason"])
        self.assertEqual((self.project / "untracked.txt").read_text(), "user work\n")

    def test_overlap_duplicate_and_unsafe_paths_fail_before_launch(self):
        with self.assertRaisesRegex(ValueError, "overlapping"):
            orc._writer_assignment_records([
                writer("a", component="pkg"), writer("b", path="pkg/x.py")])
        with self.assertRaisesRegex(ValueError, "Duplicate writer id"):
            orc._writer_assignment_records([
                writer("a", path="a.py"), writer("a", path="b.py")])
        with self.assertRaisesRegex(ValueError, "relative"):
            orc._writer_assignment_records([writer("a", path="/etc/passwd")])
        with self.assertRaisesRegex(ValueError, "inside the checkout"):
            orc._writer_assignment_records([writer("a", path="../escape.py")])
        with self.assertRaisesRegex(ValueError, "at least one"):
            orc._writer_assignment_records([writer("a")])

    def test_unowned_change_is_preserved_but_not_integrated(self):
        batch, resolved = self.prepare([writer("b", path="b.py")])
        fake = self.fake_model({"b": {"elsewhere.py": "bad\n"}})
        before = orc._checkout_content_sha(self.project)
        with patch.object(orc, "call_model", side_effect=fake):
            result = orc.run_parallel_batch(
                self.rundir, self.state, self.cfg, self.project, batch, resolved,
                None)
        self.assertIsNone(result)
        lane = self.state["parallel_writers"]["lanes"]["b"]
        self.assertEqual(lane["status"], "invalid")
        self.assertIn("unowned", lane["error"])
        self.assertFalse((self.project / "elsewhere.py").exists())
        self.assertEqual(orc._checkout_content_sha(self.project), before)
        self.assertEqual(self.state["phase"], "implement")
        self.assertIn("Single-writer recovery", self.state["correction"])

    def test_one_failure_after_sibling_finishes_preserves_sibling(self):
        batch, resolved = self.prepare([writer("a", path="a.py"),
                                        writer("b", path="b.py")])
        fake = self.fake_model({"a": {"a.py": "a = 1\n"}}, fail={"b"})
        with patch.object(orc, "call_model", side_effect=fake):
            result = orc.run_parallel_batch(
                self.rundir, self.state, self.cfg, self.project, batch, resolved,
                None)
        self.assertIsNone(result)
        self.assertEqual(self.state["parallel_writers"]["lanes"]["a"]["status"],
                         "complete")
        self.assertEqual(self.state["parallel_writers"]["lanes"]["b"]["status"],
                         "failed")
        # Completed sibling output is durable; failed output is preserved only
        # in its worktree and never applied as an accepted candidate.
        self.assertEqual((self.project / "a.py").read_text(), "a = 1\n")
        self.assertFalse((self.project / "b.py").exists())
        self.assertEqual(self.state["phase"], "implement")
        self.assertTrue(Path(self.state["parallel_writers"]["lanes"]["b"][
                                 "worktree"]).is_dir())
        self.assertEqual(self.state["parallel_fallback_batches"]["0"][
                             "incomplete"], ["b"])

    def test_cancellation_preserves_all_lanes_then_resume_integrates_once(self):
        batch, resolved = self.prepare([writer("a", path="a.py"),
                                        writer("b", path="b.py"),
                                        writer("c", path="c.py")])
        interrupting = self.fake_model({}, interrupt={"a", "b", "c"})
        orc.atomic_json(self.rundir / "control.json", {"action": "pause"})
        with patch.object(orc, "call_model", side_effect=interrupting):
            with self.assertRaises(InterruptedError):
                orc.run_parallel_batch(
                    self.rundir, self.state, self.cfg, self.project, batch,
                    resolved, None)
        self.assertEqual(interrupting.count["n"], 3)
        self.assertFalse((self.project / "a.py").exists())
        self.assertFalse((self.project / "b.py").exists())
        self.assertFalse((self.project / "c.py").exists())
        self.assertEqual(
            {lane["status"] for lane in self.state["parallel_writers"]["lanes"].values()},
            {"interrupted"})
        preserved = [Path(lane["worktree"]) for lane in
                     self.state["parallel_writers"]["lanes"].values()]
        self.assertTrue(all(path.is_dir() for path in preserved))
        # Resume: every previous process is stopped, so unfinished lanes are
        # relaunched once and integrated once.
        self.state["status"] = "running"
        orc.atomic_json(self.rundir / "control.json", {"action": "run"})
        resumed = self.fake_model({"a": {"a.py": "a = 1\n"},
                                   "b": {"b.py": "b = 2\n"},
                                   "c": {"c.py": "c = 3\n"}})
        with patch.object(orc, "call_model", side_effect=resumed):
            result = orc.run_parallel_batch(
                self.rundir, self.state, self.cfg, self.project, batch, resolved,
                None)
        self.assertIsNotNone(result)
        self.assertEqual(resumed.count["n"], 3)
        for name, value in (("a.py", "a = 1\n"), ("b.py", "b = 2\n"),
                            ("c.py", "c = 3\n")):
            self.assertEqual((self.project / name).read_text(), value)
        self.assertEqual(len([record for record in self.state["batch_deltas"]
                              if record.get("job_id") == "parallel-integration-0"]),
                         1)

    def test_completed_integration_is_never_applied_twice(self):
        batch, resolved = self.prepare([writer("a", path="a.py"),
                                        writer("b", path="b.py")])
        fake = self.fake_model({"a": {"a.py": "a = 1\n"},
                                "b": {"b.py": "b = 2\n"}})
        with patch.object(orc, "call_model", side_effect=fake):
            orc.run_parallel_batch(self.rundir, self.state, self.cfg, self.project,
                                   batch, resolved, None)
        record_path = orc._integration_record_path(self.rundir, 0)
        first = json.loads(record_path.read_text())
        calls = {"n": 0}
        real_apply = orc._apply_writer_patch

        def counting(*args, **kwargs):
            calls["n"] += 1
            return real_apply(*args, **kwargs)

        with patch.object(orc, "_apply_writer_patch", side_effect=counting):
            again = orc._parallel_integrate(
                self.rundir, self.state, self.project, 0,
                {writer_id: lane for writer_id, lane in
                 self.state["parallel_writers"]["lanes"].items()},
                first["base_head"])
        self.assertEqual(again["phase"], "complete")
        self.assertEqual(calls["n"], 0, "completed integration was replayed")

    def test_interrupted_apply_blocks_with_a_recovery_path(self):
        batch, resolved = self.prepare([writer("a", path="a.py"),
                                        writer("b", path="b.py")])
        fake = self.fake_model({"a": {"a.py": "a = 1\n"},
                                "b": {"b.py": "b = 2\n"}})
        with patch.object(orc, "call_model", side_effect=fake):
            orc.run_parallel_batch(self.rundir, self.state, self.cfg, self.project,
                                   batch, resolved, None)
        # Model a crash in the middle of a *fresh* integration by replacing the
        # durable record and leaving one patch applied without the expected
        # post-integration identity.
        record_path = orc._integration_record_path(self.rundir, 0)
        record = json.loads(record_path.read_text())
        record.update({"phase": "applying", "applied": [record["patches"][0]["writer"]]})
        orc.atomic_json(record_path, record)
        (self.project / "unrecorded.txt").write_text("manual edit\n")
        with self.assertRaisesRegex(RuntimeError, "unrecognized checkout identity"):
            orc._parallel_integrate(
                self.rundir, self.state, self.project, 0,
                self.state["parallel_writers"]["lanes"], record["base_head"])
        self.assertEqual((self.project / "unrecorded.txt").read_text(),
                         "manual edit\n")
        self.assertTrue(record_path.is_file())


if __name__ == "__main__":
    unittest.main()
