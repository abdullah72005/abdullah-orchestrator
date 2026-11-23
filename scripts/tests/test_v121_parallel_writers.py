"""v1.2.1 permission-bounded parallel writers, integration and recovery.

The model boundary is faked; worktrees, patches and the canonical checkout are
real Git state, so skipped launches, double integration and lost edits are
observable.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import threading
import time
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

    def test_ignored_runtime_input_selects_one_writer(self):
        (self.project / ".gitignore").write_text("local.cache\n")
        (self.project / "local.cache").write_text("ignored runtime input\n")
        orc.git(self.project, ["add", ".gitignore"])
        orc.git(self.project, ["commit", "-qm", "ignore local cache"])
        batch, resolved = self.prepare([writer("a", path="a.py"),
                                        writer("b", path="b.py")])
        self.assertEqual(resolved["mode"], "single")
        self.assertIn("ignored local/runtime input", resolved["reason"])
        self.assertEqual((self.project / "local.cache").read_text(),
                         "ignored runtime input\n")

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


def blocked_report(blocker="shared contract decision is missing"):
    return {"contract_version": 2, "status": "blocked", "summary": blocker,
            "files": [], "tests": [], "evidence": ["partial writer evidence"],
            "unknowns": [], "blocker": blocker}


def escalation_report(question="Which shared contract should win?"):
    return {"contract_version": 2, "status": "needs_architect",
            "summary": question, "files": [], "tests": [],
            "evidence": ["both slices touch the same public API"],
            "unknowns": ["no approved precedence"], "blocker": question}


def writer_job(run_dir, writer_id):
    return {"id": f"job-{writer_id}", "role": "implementer",
            "kind": "implementer",
            "path": str(Path(run_dir) / "jobs" / f"implementer-{writer_id}")}


class ParallelWriterRecoveryTests(unittest.TestCase):
    """Corrections for completed-process vs completed-work and transaction recovery."""

    setUp = baseline.ControlTests.setUp
    tearDown = baseline.ControlTests.tearDown

    def prepare(self, writers, max_writers=3):
        return ParallelWriterTests.prepare(self, writers, max_writers)

    def fake_model(self, writes, starts=None, fail=None, interrupt=None):
        return ParallelWriterTests.fake_model(
            self, writes, starts=starts, fail=fail, interrupt=interrupt)

    def test_blocked_report_never_enters_candidate_and_sibling_resumes(self):
        batch, resolved = self.prepare([writer("a", path="a.py"),
                                        writer("b", path="b.py")])
        self.assertEqual(resolved["mode"], "parallel")

        def first(run_dir, state, cfg, role, kind, prompt, project, **kwargs):
            writer_id = kwargs.get("assignment")
            project = Path(project)
            if writer_id == "a":
                (project / "a.py").write_text("a = 1\n")
                return report("a finished"), writer_job(run_dir, "a")
            (project / "b.py").write_text("b = 'partial'\n")
            return blocked_report(), writer_job(run_dir, "b")

        with patch.object(orc, "call_model", side_effect=first):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(self.state["status"], "blocked")
        self.assertEqual(self.state["phase"], "implement")
        self.assertIsNone(self.state.get("parallel_integration"))
        self.assertFalse((self.project / "a.py").exists(),
                         "a completed sibling was integrated before the blocker cleared")
        self.assertFalse((self.project / "b.py").exists(),
                         "a blocked writer's partial patch entered the candidate")
        lane_a = self.state["parallel_writers"]["lanes"]["a"]
        lane_b = self.state["parallel_writers"]["lanes"]["b"]
        self.assertEqual(lane_a["status"], "complete")
        self.assertEqual(lane_b["status"], "blocked")
        self.assertEqual(lane_b["report"]["blocker"],
                         "shared contract decision is missing")
        self.assertTrue(Path(lane_b["patch"]["path"]).is_file())
        self.assertTrue(Path(lane_b["worktree"]).is_dir())
        self.assertEqual(self.state["parallel_blocked"]["lane"], "b")
        # Resume reruns only the blocked lane; the completed sibling is reused
        # from its durable patch/worktree and is not dispatched again.
        resumed_calls = []

        def second(run_dir, state, cfg, role, kind, prompt, project, **kwargs):
            writer_id = kwargs.get("assignment")
            resumed_calls.append(writer_id)
            (Path(project) / "b.py").write_text("b = 2\n")
            return report("b finished"), writer_job(run_dir, "b")

        self.state["status"] = "running"
        orc.atomic_json(self.rundir / "control.json", {"action": "run"})
        with patch.object(orc, "call_model", side_effect=second):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(resumed_calls, ["b"])
        self.assertEqual(self.state["phase"], "verify")
        self.assertEqual((self.project / "a.py").read_text(), "a = 1\n")
        self.assertEqual((self.project / "b.py").read_text(), "b = 2\n")
        self.assertEqual(self.state["parallel_integration"]["phase"], "complete")

    def test_needs_architect_report_reaches_diagnosis_without_applying_partials(self):
        batch, resolved = self.prepare([writer("a", path="a.py"),
                                        writer("b", path="b.py")])

        def fake(run_dir, state, cfg, role, kind, prompt, project, **kwargs):
            writer_id = kwargs.get("assignment")
            project = Path(project)
            if writer_id == "a":
                (project / "a.py").write_text("a = 1\n")
                return report("a finished"), writer_job(run_dir, "a")
            (project / "b.py").write_text("b = 'partial'\n")
            return escalation_report(), writer_job(run_dir, "b")

        with patch.object(orc, "call_model", side_effect=fake):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(self.state["phase"], "diagnose")
        request = self.state["diagnosis_request"]
        self.assertEqual(request["source"], "parallel_writer_escalation")
        self.assertEqual(request["question"], "Which shared contract should win?")
        self.assertEqual(request["evidence"], ["both slices touch the same public API"])
        self.assertEqual(request["unknowns"], ["no approved precedence"])
        self.assertEqual(self.state["parallel_writers"]["lanes"]["b"]["status"],
                         "needs_architect")
        self.assertEqual(self.state["parallel_writers"]["lanes"]["a"]["status"],
                         "complete")
        self.assertFalse((self.project / "a.py").exists())
        self.assertFalse((self.project / "b.py").exists())
        self.assertIsNone(self.state.get("parallel_integration"))

    def test_cancellation_before_parent_reconciliation_reuses_completed_sibling(self):
        batch, resolved = self.prepare([writer("a", path="a.py"),
                                        writer("b", path="b.py")])
        records = {record["id"]: record for record in resolved["writers"]}
        base_head = orc.git(self.project, ["rev-parse", "HEAD"]).decode().strip()
        lane_dir = orc._parallel_batch_dir(self.rundir, 0) / "a"
        lane_dir.mkdir(parents=True, exist_ok=True)
        worktree = orc.create_writer_worktree(
            self.project, lane_dir / "worktree", base_head)
        provenance = orc._lane_provenance(
            self.state, 0, records["a"], base_head, "attempt-crash")
        fake = self.fake_model({"a": {"a.py": "a = 1\n"}})
        with patch.object(orc, "call_model", side_effect=fake):
            orc._parallel_lane_worker(
                self.rundir, self.state, self.cfg, self.project, batch,
                records["a"], worktree, lane_dir, base_head,
                orc.source_snapshot(worktree), None, None, provenance)
        self.assertEqual(fake.count["n"], 1)
        self.assertTrue((lane_dir / "lane-result.json").is_file())
        # The parent died before validation: the lane still says running and the
        # result was never promoted, but the completed output is durable.
        self.state["parallel_writers"] = {
            "batch_index": 0, "lanes": {"a": {
                "status": "running", "batch_index": 0,
                "worktree": str(worktree), "lane_dir": str(lane_dir),
                "base_head": base_head,
                "plan_version": self.state["plan_version"], "plan_revision": 1,
                "amendment_epoch": 0, "attempt": 1, "intent": provenance,
                "assignment": records["a"]}}}
        orc.save(self.rundir, self.state)
        resumed = self.fake_model({"b": {"b.py": "b = 2\n"}})
        with patch.object(orc, "call_model", side_effect=resumed):
            result = orc.run_parallel_batch(
                self.rundir, self.state, self.cfg, self.project, batch, resolved,
                None)
        self.assertIsNotNone(result)
        self.assertEqual(resumed.starts, ["b"],
                         "the completed sibling was dispatched again")
        self.assertEqual((self.project / "a.py").read_text(), "a = 1\n")
        self.assertEqual((self.project / "b.py").read_text(), "b = 2\n")
        self.assertEqual(self.state["parallel_integration"]["phase"], "complete")

    def test_interruption_during_startup_has_no_duplicate_launch(self):
        batch, resolved = self.prepare([writer("a", path="a.py"),
                                        writer("b", path="b.py")])
        base_head = orc.git(self.project, ["rev-parse", "HEAD"]).decode().strip()
        # Lane a was journaled/admitted but its execution slot never existed
        # because the parent stopped during startup.
        lane_dir = orc._parallel_batch_dir(self.rundir, 0) / "a"
        lane_dir.mkdir(parents=True, exist_ok=True)
        worktree = orc.create_writer_worktree(
            self.project, lane_dir / "worktree", base_head)
        self.state["parallel_writers"] = {
            "batch_index": 0, "lanes": {"a": {
                "status": "starting", "batch_index": 0,
                "worktree": str(worktree), "lane_dir": str(lane_dir),
                "base_head": base_head, "plan_version": self.state["plan_version"],
                "plan_revision": 1, "amendment_epoch": 0, "attempt": 1,
                "intent": orc._lane_provenance(
                    self.state, 0, writer("a"), base_head, "attempt-start")}}}
        orc.save(self.rundir, self.state)
        fake = self.fake_model({"a": {"a.py": "a = 1\n"},
                                "b": {"b.py": "b = 2\n"}})
        with patch.object(orc, "call_model", side_effect=fake):
            result = orc.run_parallel_batch(
                self.rundir, self.state, self.cfg, self.project, batch, resolved,
                None)
        self.assertIsNotNone(result)
        self.assertEqual(sorted(fake.starts), ["a", "b"])
        self.assertEqual(fake.count["n"], 2, "a lane was launched more than once")
        self.assertEqual(self.state["parallel_integration"]["phase"], "complete")

    def test_crash_after_apply_advances_without_another_writer(self):
        batch, resolved = self.prepare([writer("a", path="a.py"),
                                        writer("b", path="b.py")])
        fake = self.fake_model({"a": {"a.py": "a = 1\n"},
                                "b": {"b.py": "b = 2\n"}})
        with patch.object(orc, "call_model", side_effect=fake):
            orc.run_parallel_batch(self.rundir, self.state, self.cfg,
                                   self.project, batch, resolved, None)
        # Simulate process loss after the exact apply but before phase advance.
        self.state["phase"] = "implement"
        self.state["implementation"] = None
        self.state["parallel_active"] = None
        orc.save(self.rundir, self.state)
        calls = []

        def must_not_run(*args, **kwargs):
            calls.append("model")
            raise AssertionError("a fresh writer was dispatched after a complete apply")

        with patch.object(orc, "call_model", side_effect=must_not_run):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(calls, [])
        self.assertEqual(self.state["phase"], "verify")
        self.assertIn("integrated", self.state["implementation"]["summary"])
        self.assertEqual(self.state["parallel_integration"]["phase"], "complete")

    def test_index_state_mismatch_blocks_before_any_writer(self):
        batch, resolved = self.prepare([writer("a", path="a.py"),
                                        writer("b", path="b.py")])
        fake = self.fake_model({"a": {"a.py": "a = 1\n"},
                                "b": {"b.py": "b = 2\n"}})
        with patch.object(orc, "call_model", side_effect=fake):
            orc.run_parallel_batch(self.rundir, self.state, self.cfg,
                                   self.project, batch, resolved, None)
        # Change only the index entry (executable mode) after integration. The
        # exact tree/index identity no longer matches the recorded apply.
        orc.git(self.project, ["update-index", "--chmod=+x", "app.py"])
        self.state["phase"] = "implement"
        self.state["implementation"] = None
        orc.save(self.rundir, self.state)
        calls = []

        def must_not_run(*args, **kwargs):
            calls.append("model")
            raise AssertionError("a writer was dispatched over a mismatched index")

        with patch.object(orc, "call_model", side_effect=must_not_run):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(calls, [])
        self.assertEqual(self.state["status"], "blocked")
        self.assertIn("no longer matches", self.state["pause_reason"])
        self.assertEqual((self.project / "a.py").read_text(), "a = 1\n")

    def test_unreadable_integration_record_is_a_visible_blocker(self):
        batch, resolved = self.prepare([writer("a", path="a.py"),
                                        writer("b", path="b.py")])
        path = orc._integration_record_path(self.rundir, 0)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not-json")
        calls = []

        def must_not_run(*args, **kwargs):
            calls.append("model")
            raise AssertionError("a writer was dispatched over an unreadable record")

        with patch.object(orc, "call_model", side_effect=must_not_run):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(calls, [])
        self.assertEqual(self.state["status"], "blocked")
        self.assertIn("unreadable", self.state["pause_reason"])

    def test_explicit_one_writer_uses_the_ordinary_single_writer_path(self):
        batch, resolved = self.prepare([writer("a", path="a.py")])
        self.assertEqual(resolved["mode"], "single")
        starts = []

        def fake(run_dir, state, cfg, role, kind, prompt, project, **kwargs):
            starts.append(kwargs.get("assignment"))
            (Path(project) / "a.py").write_text("a = 1\n")
            return report("single writer finished"), writer_job(run_dir, "single")

        with patch.object(orc, "call_model", side_effect=fake):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(starts, [None])
        self.assertEqual(self.state["phase"], "verify")
        self.assertFalse(orc._integration_record_path(self.rundir, 0).exists())
        self.assertNotIn("parallel_writers", self.state)

    def test_fast_lane_completion_is_observed_before_a_quiet_sibling(self):
        batch, resolved = self.prepare([writer("a", path="a.py"),
                                        writer("b", path="b.py")])
        observed = {"value": False}
        self.state["status"] = "running"

        def fake(run_dir, state, cfg, role, kind, prompt, project, **kwargs):
            writer_id = kwargs.get("assignment")
            project = Path(project)
            if writer_id == "a":
                (project / "a.py").write_text("a = 1\n")
                return report("a finished"), writer_job(run_dir, "a")
            limit = time.monotonic() + 10
            while time.monotonic() < limit:
                events = orc.journal_tail_bounded(self.rundir, 300)
                if any(event.get("event") == "parallel_lane_observed"
                       and event.get("assignment") == "a" for event in events):
                    observed["value"] = True
                    break
                time.sleep(0.1)
            (project / "b.py").write_text("b = 2\n")
            return report("b finished"), writer_job(run_dir, "b")

        orc._STAGE_CONTEXT.attempt = "stage-attempt"
        try:
            with patch.object(orc, "call_model", side_effect=fake):
                result = orc.run_parallel_batch(
                    self.rundir, self.state, self.cfg, self.project, batch,
                    resolved, None)
        finally:
            orc._STAGE_CONTEXT.attempt = None
        self.assertIsNotNone(result)
        self.assertTrue(observed["value"],
                        "lane a completion was not visible while b was running")
        payload = orc.stage_payload(self.rundir, self.state, "implement",
                                    "implementer", "task", "expected", 1.0)
        self.assertTrue(any("writer a" in item for item in
                            payload["progress"]["replay"]),
                        payload["progress"]["replay"])


if __name__ == "__main__":
    unittest.main()
