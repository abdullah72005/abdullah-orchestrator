"""Focused fixtures for the opt-in bounded parallel test runner.

These tests do not execute the product suite.  They use tiny disposable
``unittest`` modules to prove selection, module/fixture boundaries, exactly-once
accounting, bounded concurrency, CPU/nice command construction, serial fallback
and result aggregation.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "run_tests_parallel.py"
spec = importlib.util.spec_from_file_location("run_tests_parallel", MODULE_PATH)
runner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runner
spec.loader.exec_module(runner)


def _write_module(folder, name, tests):
    lines = ["import unittest\n", "\n", "class Cases(unittest.TestCase):\n"]
    for test_name in tests:
        lines.append("    def %s(self):\n        self.assertTrue(True)\n" % test_name)
    lines.append("\n\nif __name__ == '__main__':\n    unittest.main()\n")
    (Path(folder) / (name + ".py")).write_text("".join(lines), encoding="utf-8")


class RunnerFixture(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="parallel-runner-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.tests = self.root / "tests"
        self.tests.mkdir()
        _write_module(self.tests, "test_alpha",
                      ["test_one", "test_two", "test_three"])
        _write_module(self.tests, "test_beta", ["test_only"])
        _write_module(self.tests, "test_slow", ["test_timing"])


class SelectionAndPartitionTests(RunnerFixture):
    def test_discovery_selection_and_exact_once_partition(self):
        ids = runner.collect_test_ids(self.tests)
        self.assertEqual(len(ids), 5, ids)
        self.assertEqual(sorted(runner.select_tests(
            ids, modules=["test_alpha"])), sorted(
                item for item in ids if item.startswith("test_alpha.")))
        plan = runner.partition_tests(ids, workers=2,
                                      serial_modules=["test_slow"])
        self.assertEqual(len(plan["serial"]), 1)
        self.assertEqual([item for item in plan["serial"][0]["tests"]], [
            item for item in ids if item.startswith("test_slow.")])
        grouped = [test_id for group in plan["serial"] + plan["parallel"]
                   for test_id in group["tests"]]
        self.assertEqual(sorted(grouped), sorted(ids))
        self.assertEqual(len(grouped), len(ids))

    def test_module_fixture_boundaries_are_never_split(self):
        ids = runner.collect_test_ids(self.tests)
        plan = runner.partition_tests(ids, workers=2, serial_modules=())
        seen = {}
        for group in plan["serial"] + plan["parallel"]:
            for module in group["modules"]:
                self.assertNotIn(module, seen, module)
                seen[module] = group["name"]
            self.assertTrue(group["modules"])
        for module in ("test_alpha", "test_beta", "test_slow"):
            owners = [group["name"] for group in plan["serial"] + plan["parallel"]
                      if module in group["modules"]]
            self.assertEqual(len(owners), 1, (module, owners))
        alpha = [test_id for test_id in ids if test_id.startswith("test_alpha.")]
        alpha_groups = [group for group in plan["serial"] + plan["parallel"]
                        if any(test_id.startswith("test_alpha.") for test_id in group["tests"])]
        self.assertEqual(len(alpha_groups), 1)
        self.assertEqual(sorted(alpha_groups[0]["tests"]), sorted(alpha))

    def test_unknown_selected_test_is_refused(self):
        ids = runner.collect_test_ids(self.tests)
        with self.assertRaisesRegex(ValueError, "not discovered"):
            runner.select_tests(ids, tests=["test_missing.Cases.test_x"])

    def test_imported_test_classes_are_counted_once_as_unique_ids(self):
        (self.tests / "test_source.py").write_text(
            "import unittest\n\n"
            "class Cases(unittest.TestCase):\n"
            "    def test_one(self):\n        self.assertTrue(True)\n"
            "    def test_two(self):\n        self.assertTrue(True)\n",
            encoding="utf-8")
        (self.tests / "test_importer.py").write_text(
            "from test_source import Cases  # noqa: F401\n", encoding="utf-8")
        discovery = {}
        ids = runner.collect_test_ids(self.tests, discovery=discovery)
        self.assertEqual(discovery["unique"], len(ids))
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreater(discovery["entries"], discovery["unique"])
        self.assertEqual(discovery["duplicates"]["test_source.Cases.test_one"], 2)
        self.assertEqual(discovery["duplicates"]["test_source.Cases.test_two"], 2)
        self.assertNotIn("test_importer.Cases.test_one", ids)
        plan = runner.partition_tests(ids, workers=2, serial_modules=())
        grouped = [test_id for group in plan["serial"] + plan["parallel"]
                   for test_id in group["tests"]]
        self.assertEqual(sorted(grouped), sorted(ids))
        owners = [group["name"] for group in plan["serial"] + plan["parallel"]
                  if "test_source" in group["modules"]]
        self.assertEqual(len(owners), 1, owners)
        self.assertFalse(any("test_importer" in group["modules"]
                             for group in plan["serial"] + plan["parallel"]))

    def test_conflicting_duplicate_id_is_refused(self):
        (self.tests / "test_spoof.py").write_text(
            "import unittest\n\n"
            "class One(unittest.TestCase):\n"
            "    def test_same(self):\n        pass\n\n"
            "class Two(unittest.TestCase):\n"
            "    def test_same(self):\n        pass\n\n"
            "One.__module__ = Two.__module__ = 'test_spoof'\n"
            "One.__qualname__ = Two.__qualname__ = 'Cases'\n",
            encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "conflicting tests"):
            runner.collect_test_ids(self.tests)


class LimitsAndCommandTests(unittest.TestCase):
    def test_serial_is_default_and_two_workers_are_opt_in(self):
        limits = runner.resolve_limits(workers=1)
        self.assertEqual(limits["workers"], 1)
        self.assertFalse(limits["serial_fallback"])

    def test_serial_fallback_when_cpu_limit_cannot_apply(self):
        too_few = runner.resolve_limits(workers=2, cpu_budget=1)
        self.assertEqual(too_few["workers"], 1)
        self.assertTrue(too_few["serial_fallback"])
        with patch.object(runner.shutil, "which", return_value=None):
            missing = runner.resolve_limits(workers=2, require_taskset=True)
        self.assertEqual(missing["workers"], 1)
        self.assertIn("taskset", missing["fallback_reason"])
        tight = runner.resolve_limits(workers=2, min_memory_mb=10 ** 9)
        self.assertEqual(tight["workers"], 1)
        self.assertIn("memory", tight["fallback_reason"])

    def test_two_worker_cpu_affinity_and_nice_are_bounded(self):
        with patch.object(runner.shutil, "which", return_value="/usr/bin/taskset"), \
                patch.object(runner, "_available_cpus",
                             return_value=[0, 1, 2, 3, 4, 5]), \
                patch.object(runner, "_available_memory_mb", return_value=8192):
            limits = runner.resolve_limits(workers=2, cpu_budget=4, nice=10,
                                           require_taskset=True)
        self.assertEqual(limits["workers"], 2)
        self.assertEqual(limits["allowed_cpus"], [0, 1, 2, 3])
        aggregate = [cpu for assigned in limits["cpu_assignments"]
                     for cpu in assigned]
        self.assertLessEqual(len(aggregate), 4)
        self.assertEqual(sorted(aggregate), [0, 1, 2, 3])
        command = runner.build_group_command(
            {"name": "worker:1", "tests": ["test_alpha.Cases.test_one"],
             "modules": ["test_alpha"]}, limits=limits)
        self.assertEqual(command[:5], ["/usr/bin/taskset", "-c", "0,1",
                                       "nice", "-n"])
        self.assertIn("10", command)
        self.assertEqual(command[-4:], ["-m", "unittest", "-v",
                                        "test_alpha.Cases.test_one"])
        second = runner.build_group_command(
            {"name": "worker:2", "tests": ["test_beta.Cases.test_only"],
             "modules": ["test_beta"]}, limits=limits)
        self.assertEqual(second[2], "2,3")

    def test_cli_cannot_relax_worker_cpu_or_priority_bounds(self):
        with patch.object(runner.shutil, "which", return_value="/usr/bin/taskset"), \
                patch.object(runner, "_available_cpus",
                             return_value=list(range(8))), \
                patch.object(runner, "_available_memory_mb", return_value=8192):
            limits = runner.resolve_limits(workers=8, cpu_budget=8, nice=0,
                                           require_taskset=True)
        self.assertEqual(limits["workers"], 2)
        self.assertEqual(limits["requested_workers"], 2)
        self.assertEqual(limits["requested_cpu_budget"], 8)
        self.assertEqual(limits["cpu_budget"], 4)
        self.assertEqual(len(limits["allowed_cpus"]), 4)
        self.assertEqual(limits["requested_nice"], 0)
        self.assertEqual(limits["nice"], 10)
        command = runner.build_group_command(
            {"name": "worker:1", "tests": ["test_alpha.Cases.test_one"],
             "modules": ["test_alpha"]}, limits=limits)
        self.assertEqual(command[:3], ["/usr/bin/taskset", "-c", "0,1"])

    def test_affinity_probe_failure_falls_back_before_any_group_starts(self):
        with patch.object(runner.shutil, "which", return_value="/usr/bin/taskset"), \
                patch.object(runner, "_available_cpus",
                             return_value=[0, 1, 2, 3]), \
                patch.object(runner, "_available_memory_mb", return_value=8192):
            limits = runner.resolve_limits(workers=2, cpu_budget=4,
                                           require_taskset=True)
        failed = runner.probe_parallel_environment(
            limits, probe=lambda command: (126, "failed to set pid affinity"))
        self.assertEqual(failed["workers"], 1)
        self.assertTrue(failed["serial_fallback"])
        self.assertFalse(failed["affinity_verified"])
        self.assertIn("affinity", failed["fallback_reason"])
        verified = runner.probe_parallel_environment(
            limits, probe=lambda command: (0, ""))
        self.assertEqual(verified["workers"], 2)
        self.assertTrue(verified["affinity_verified"])
        self.assertFalse(verified["serial_fallback"])

    def test_wsl_requires_provable_host_memory_headroom(self):
        with patch.object(runner.shutil, "which", return_value="/usr/bin/taskset"), \
                patch.object(runner, "_available_cpus",
                             return_value=[0, 1, 2, 3]), \
                patch.object(runner, "_available_memory_mb", return_value=8192):
            unknown = runner.resolve_limits(workers=2, wsl=True,
                                            host_memory_mb=None)
            tight = runner.resolve_limits(workers=2, wsl=True,
                                          host_memory_mb=512,
                                          min_memory_mb=1024)
            roomy = runner.resolve_limits(workers=2, wsl=True,
                                          host_memory_mb=8192,
                                          min_memory_mb=1024)
        self.assertEqual(unknown["workers"], 1)
        self.assertIn("headroom", unknown["fallback_reason"])
        self.assertEqual(tight["workers"], 1)
        self.assertIn("Windows host", tight["fallback_reason"])
        self.assertEqual(roomy["workers"], 2)
        self.assertFalse(roomy["serial_fallback"])

    def test_incident_suites_stay_serial_and_outside_parallel_groups(self):
        ids = ["test_v121_evidence_reuse.Cases.test_a",
               "test_live_stage_progress.Cases.test_b",
               "test_v31_review_recovery.Cases.test_c",
               "test_alpha.Cases.test_one"]
        plan = runner.partition_tests(
            ids, workers=2, serial_modules=runner.DEFAULT_SERIAL_MODULES)
        self.assertEqual(
            sorted(group["name"] for group in plan["serial"]),
            ["serial:test_live_stage_progress",
             "serial:test_v121_evidence_reuse",
             "serial:test_v31_review_recovery"])
        parallel = [test_id for group in plan["parallel"]
                    for test_id in group["tests"]]
        self.assertEqual(parallel, ["test_alpha.Cases.test_one"])


class ExecutionAggregationTests(RunnerFixture):
    def _plan(self, ids, workers=2, serial_modules=()):
        return runner.partition_tests(ids, workers=workers,
                                      serial_modules=serial_modules)

    def test_two_workers_overlap_while_serial_is_exclusive(self):
        lock = threading.Lock()
        active = {"now": 0, "max": 0}

        def fake(group, **_kwargs):
            with lock:
                active["now"] += 1
                active["max"] = max(active["max"], active["now"])
            time.sleep(0.2)
            with lock:
                active["now"] -= 1
            return {"name": group["name"], "tests": group["tests"],
                    "counts": {"ran": len(group["tests"])}, "returncode": 0}

        ids = runner.collect_test_ids(self.tests)
        plan = self._plan(ids, workers=2)
        limits = runner.resolve_limits(workers=2, cpu_budget=4,
                                       require_taskset=False)
        limits["workers"] = 2
        runner.execute_plan(plan, start_dir=self.tests,
                            output_dir=self.root / "logs", limits=limits,
                            group_runner=fake)
        self.assertEqual(active["max"], 2)
        active.update({"now": 0, "max": 0})
        serial_plan = {"serial": [], "parallel": [], "selected": 0}
        for group in plan["parallel"]:
            copy = dict(group)
            copy["name"] = "serial:%s" % group["name"]
            serial_plan["parallel"].append(copy)
        limits["workers"] = 1
        runner.execute_plan(serial_plan, start_dir=self.tests,
                            output_dir=self.root / "logs", limits=limits,
                            group_runner=fake)
        self.assertEqual(active["max"], 1)

    def test_real_groups_account_for_each_test_exactly_once(self):
        record = self.root / "ran.txt"
        for path in self.tests.glob("test_*.py"):
            module = path.stem
            lines = []
            for test_id in runner.collect_test_ids(self.tests):
                if not test_id.startswith(module + "."):
                    continue
                lines.append(
                    "    def %s(self):\n"
                    "        with open(%r, 'a', encoding='utf-8') as stream:\n"
                    "            stream.write(%r + '\\n')\n"
                    % (test_id.rsplit(".", 1)[1], str(record), test_id))
            path.write_text(
                "import unittest\n\nclass Cases(unittest.TestCase):\n"
                + "".join(lines)
                + "\n\nif __name__ == '__main__':\n    unittest.main()\n",
                encoding="utf-8")
        ids = runner.collect_test_ids(self.tests)
        plan = self._plan(ids, workers=2)
        limits = runner.resolve_limits(workers=2, cpu_budget=4,
                                       require_taskset=False)
        results = runner.execute_plan(
            plan, start_dir=self.tests, output_dir=self.root / "real-logs",
            limits=limits)
        totals = runner.aggregate(results, selected=len(ids))
        self.assertEqual(totals["exit_code"], 0, totals)
        self.assertEqual(totals["ran"], len(ids), totals)
        ran = Path(record).read_text(encoding="utf-8").splitlines()
        self.assertEqual(sorted(ran), sorted(ids))
        self.assertEqual(len(ran), len(set(ran)))

    def test_aggregation_reports_skips_failures_and_missing_groups(self):
        passed = {"name": "worker:1", "counts": {"ran": 3, "failures": 0,
                                                  "errors": 0, "skipped": 1},
                  "returncode": 0}
        skipped = {"name": "worker:2", "counts": {"ran": 2, "failures": 0,
                                                   "errors": 0, "skipped": 2},
                   "returncode": 0}
        totals = runner.aggregate([passed, skipped], selected=5)
        self.assertEqual(totals["exit_code"], 0, totals)
        self.assertEqual(totals["skipped"], 3)
        failed = {"name": "worker:3", "counts": {"ran": 1, "failures": 1,
                                                  "errors": 0, "skipped": 0},
                  "returncode": 1}
        totals = runner.aggregate([passed, failed], selected=4)
        self.assertEqual(totals["exit_code"], 1)
        self.assertEqual(totals["failed_groups"], ["worker:3"])
        missing = {"name": "worker:4", "missing": True, "returncode": None,
                   "counts": {}}
        totals = runner.aggregate([passed, missing], selected=4)
        self.assertEqual(totals["exit_code"], 1)
        self.assertEqual(totals["missing_groups"], ["worker:4"])

    def test_unittest_parser_reads_ok_skips_and_failed_counts(self):
        ok = runner._parse_unittest_output(
            "Ran 4 tests in 0.123s\n\nOK (skipped=2)\n")
        self.assertEqual(ok, {"ran": 4, "failures": 0, "errors": 0,
                              "skipped": 2})
        failed = runner._parse_unittest_output(
            "Ran 3 tests in 0.1s\n\nFAILED (failures=1, errors=2, skipped=1)\n")
        self.assertEqual(failed, {"ran": 3, "failures": 1, "errors": 2,
                                  "skipped": 1})

    def test_report_records_selection_limits_logs_and_totals(self):
        ids = runner.collect_test_ids(self.tests)
        plan = self._plan(ids, workers=1)
        limits = runner.resolve_limits(workers=1)
        results = runner.execute_plan(
            plan, start_dir=self.tests, output_dir=self.root / "report-logs",
            limits=limits)
        report = runner.build_report(
            start_dir=self.tests, pattern="test*.py", selected=ids,
            plan=plan, limits=limits, results=results)
        self.assertEqual(report["selection"]["count"], len(ids))
        self.assertEqual(report["totals"]["ran"], len(ids))
        for result in report["results"]:
            self.assertTrue(result["log"]["sha256"])
            self.assertTrue(Path(result["log"]["path"]).is_file())
        json.dumps(report)

    def test_class_level_skip_is_accounted_without_missing_coverage(self):
        (self.tests / "test_classskip.py").write_text(
            "import unittest\n\n"
            "class Skipped(unittest.TestCase):\n"
            "    @classmethod\n"
            "    def setUpClass(cls):\n"
            "        raise unittest.SkipTest('class unavailable')\n"
            "    def test_first(self):\n        pass\n"
            "    def test_second(self):\n        pass\n\n"
            "class Running(unittest.TestCase):\n"
            "    def test_third(self):\n        pass\n",
            encoding="utf-8")
        ids = runner.collect_test_ids(self.tests)
        selected = [test_id for test_id in ids
                    if test_id.startswith("test_classskip.")]
        plan = runner.partition_tests(selected, workers=1)
        limits = runner.resolve_limits(workers=1)
        results = runner.execute_plan(
            plan, start_dir=self.tests,
            output_dir=self.root / "class-skip-logs", limits=limits)
        totals = runner.aggregate(results, selected=len(selected))
        self.assertEqual(totals["exit_code"], 0, totals)
        self.assertEqual(totals["ran"], 1, totals)
        self.assertEqual(totals["class_skips"], 1, totals)
        self.assertEqual(totals["class_skipped_tests"], 2, totals)
        self.assertEqual(totals["accounted"], len(selected), totals)

    def test_sigint_child_is_interrupted_not_a_failed_group(self):
        group = {"name": "worker:sigint", "modules": ["test_alpha"],
                 "tests": ["test_alpha.Cases.test_one"], "serial": False}
        limits = runner.resolve_limits(workers=1)
        with patch.object(runner, "build_group_command", return_value=[
                sys.executable, "-c",
                "import os, signal; os.kill(os.getpid(), signal.SIGINT)"]):
            result = runner.run_group(
                group, start_dir=self.tests,
                output_dir=self.root / "sigint-logs", limits=limits,
                timeout=30)
        self.assertEqual(result["returncode"], -2, result)
        self.assertTrue(result["interrupted"])
        self.assertIn("SIGINT", result["interrupt_reason"])
        self.assertTrue(result["log"]["sha256"])
        totals = runner.aggregate([result], selected=1)
        self.assertEqual(totals["interrupted_groups"], ["worker:sigint"])
        self.assertEqual(totals["failed_groups"], [])
        self.assertEqual(totals["exit_code"], 1)

    def test_runner_interrupt_marks_incomplete_and_cancelled_groups(self):
        first = {"name": "serial:one", "modules": ["test_alpha"],
                 "tests": ["test_alpha.Cases.test_one"], "serial": True}
        second = {"name": "serial:two", "modules": ["test_beta"],
                  "tests": ["test_beta.Cases.test_only"], "serial": True}

        def fake(group, **_kwargs):
            if group["name"] == "serial:one":
                raise KeyboardInterrupt
            return {"name": group["name"], "tests": group["tests"],
                    "counts": {"ran": 1}, "returncode": 0}

        limits = runner.resolve_limits(workers=1)
        results = runner.execute_plan(
            {"serial": [first, second], "parallel": [], "selected": 2},
            start_dir=self.tests, output_dir=self.root / "cancel-logs",
            limits=limits, group_runner=fake)
        totals = runner.aggregate(results, selected=2)
        self.assertEqual(totals["interrupted_groups"], ["serial:one"])
        self.assertEqual(totals["cancelled_groups"], ["serial:two"])
        self.assertEqual(totals["ran"], 0)
        self.assertEqual(totals["exit_code"], 1)

    def test_source_fingerprint_and_report_mark_a_changing_checkout(self):
        before = {"head": "a" * 40, "dirty": False, "fingerprint": "before"}
        after = {"head": "a" * 40, "dirty": True, "fingerprint": "after"}
        ids = runner.collect_test_ids(self.tests)
        plan = runner.partition_tests(ids, workers=1)
        limits = runner.resolve_limits(workers=1)
        report = runner.build_report(
            start_dir=self.tests, pattern="test*.py", selected=ids,
            plan=plan, limits=limits, results=[],
            discovery={"entries": len(ids) + 2, "unique": len(ids),
                       "duplicates": {"test_alpha.Cases.test_one": 2}},
            source_before=before, source_after=after)
        self.assertTrue(report["source"]["changed"])
        self.assertEqual(report["selection"]["discovered_entries"],
                         len(ids) + 2)
        self.assertEqual(report["selection"]["duplicate_ids"],
                         {"test_alpha.Cases.test_one": 2})
        self.assertEqual(report["revision"], "a" * 40)

    def test_source_state_fingerprints_the_real_checkout(self):
        root = Path(runner.__file__).resolve().parents[1]
        state = runner._source_state(root / "scripts" / "tests")
        self.assertTrue(state["head"])
        self.assertIsInstance(state["dirty"], bool)
        self.assertTrue(state["fingerprint"])


if __name__ == "__main__":
    unittest.main()
