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


if __name__ == "__main__":
    unittest.main()
