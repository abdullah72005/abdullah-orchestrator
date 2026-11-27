#!/usr/bin/env python3
"""Opt-in bounded parallel runner for the existing ``unittest`` suite.

Serial execution stays the default.  This helper is for a full discovery or a
large selected test set where two workers are genuinely useful.  It keeps the
repository's discovery and test-id semantics, partitions selected tests by
module so fixtures are never split across workers, runs timing-sensitive
modules in a separate serial group first, and limits the aggregate process
trees to four logical CPUs at lower scheduling priority on Ubuntu/WSL.  If the
CPU limit cannot be applied, or host memory is tight, it falls back to serial.

It is a developer tool, not a replacement for the final local gate::

    python3 scripts/run_tests_parallel.py --parallel --workers 2

    python3 scripts/run_tests_parallel.py --list \
        --module test_live_stage_progress --module test_v122_reviewer_packet_proof

The JSON summary records the exact selection, revision, group commands, logs,
digests, worker/CPU limits and aggregate counts.  A retry is a new invocation
with the failed modules and a recorded reason; this helper does not silently
rerun a group.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

# Suites that are timing- or process-sensitive and must not share a parallel
# batch with unrelated fixtures.  They still use the repository's runner.
DEFAULT_SERIAL_MODULES = (
    "test_v31_stage_deadline",
    "test_v121_parallel_writers",
    "test_v31_grant_contention",
)

DEFAULT_CPU_BUDGET = 4
DEFAULT_WORKERS = 2
DEFAULT_NICE = 10
DEFAULT_MIN_MEMORY_MB = 1024
_TEST_ID = re.compile(r"^[A-Za-z_][\w.]*$")


def _module_of(test_id):
    return test_id.split(".", 1)[0]


def collect_test_ids(start_dir, pattern="test*.py"):
    """Collect test ids with the same loader/discovery used by unittest."""
    start = Path(start_dir).resolve()
    if not start.is_dir():
        raise ValueError("test directory does not exist: %s" % start)
    before = set(sys.modules)
    suite = unittest.defaultTestLoader.discover(
        str(start), pattern=pattern, top_level_dir=str(start))
    ids = []

    def walk(item):
        if isinstance(item, unittest.TestSuite):
            for child in item:
                walk(child)
        else:
            ids.append(item.id())

    walk(suite)
    # Discovery imports temporary modules by their bare names.  Drop only the
    # modules imported from this start directory so a later fixture with the
    # same tiny module names cannot collide in sys.modules.
    for name in set(sys.modules) - before:
        module = sys.modules.get(name)
        filename = getattr(module, "__file__", None)
        if not filename:
            continue
        try:
            Path(filename).resolve().relative_to(start)
        except ValueError:
            continue
        sys.modules.pop(name, None)
    return ids


def select_tests(ids, *, modules=None, tests=None):
    """Filter discovered ids without changing discovery semantics."""
    selected = list(ids)
    if modules:
        wanted = {str(name).split(".", 1)[0] for name in modules}
        selected = [test_id for test_id in selected
                    if _module_of(test_id) in wanted]
    if tests:
        wanted = set(tests)
        missing = wanted - set(selected)
        if missing:
            raise ValueError("selected tests were not discovered: "
                             + ", ".join(sorted(missing)))
        selected = [test_id for test_id in selected if test_id in wanted]
    return selected


def partition_tests(ids, *, workers=DEFAULT_WORKERS, serial_modules=()):
    """Partition ids into disjoint, module-preserving groups.

    Timing-sensitive modules become sequential serial groups.  All remaining
    modules are assigned whole to the least-loaded parallel worker.  The union
    of every group is exactly the selection, once.
    """
    ids = list(ids)
    if not ids:
        return {"serial": [], "parallel": [], "selected": 0}
    serial_modules = tuple(dict.fromkeys(serial_modules or ()))
    by_module = {}
    for test_id in ids:
        by_module.setdefault(_module_of(test_id), []).append(test_id)
    serial = []
    parallel_modules = []
    for module in serial_modules:
        if module in by_module:
            serial.append({"name": "serial:" + module,
                           "modules": [module],
                           "tests": sorted(by_module[module]),
                           "serial": True})
    for module, module_ids in sorted(by_module.items()):
        if module in serial_modules:
            continue
        parallel_modules.append((module, sorted(module_ids)))
    workers = max(1, int(workers))
    if workers == 1:
        parallel = []
        if parallel_modules:
            tests = [test_id for _module, module_ids in parallel_modules
                     for test_id in module_ids]
            parallel.append({"name": "worker:1", "modules":
                             [module for module, _ in parallel_modules],
                             "tests": tests, "serial": False})
    else:
        buckets = [{"name": "worker:%d" % (index + 1), "modules": [],
                    "tests": [], "serial": False}
                   for index in range(workers)]
        loads = [0] * workers
        # Largest modules first keeps the two workers reasonably balanced.
        for module, module_ids in sorted(
                parallel_modules, key=lambda item: (-len(item[1]), item[0])):
            target = min(range(workers), key=lambda index: (loads[index], index))
            buckets[target]["modules"].append(module)
            buckets[target]["tests"].extend(module_ids)
            loads[target] += len(module_ids)
        parallel = [bucket for bucket in buckets if bucket["tests"]]
    grouped = [test_id for group in serial + parallel
               for test_id in group["tests"]]
    if sorted(grouped) != sorted(ids) or len(grouped) != len(ids):
        raise AssertionError("partition did not account for every test exactly once")
    return {"serial": serial, "parallel": parallel, "selected": len(ids)}


def _available_cpus():
    try:
        cpus = sorted(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        cpus = list(range(os.cpu_count() or 1))
    return cpus


def _available_memory_mb():
    try:
        pages = os.sysconf("SC_AVPHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return int((pages * page_size) // (1024 * 1024))
    except (AttributeError, OSError, ValueError):
        return None


def resolve_limits(*, workers=DEFAULT_WORKERS, cpu_budget=DEFAULT_CPU_BUDGET,
                   nice=DEFAULT_NICE, min_memory_mb=DEFAULT_MIN_MEMORY_MB,
                   require_taskset=True, taskset_available=None):
    """Resolve effective workers and CPU affinity, or a serial fallback."""
    requested = max(1, int(workers))
    cpu_budget = max(1, int(cpu_budget))
    if taskset_available is False:
        taskset = None
    else:
        taskset = shutil.which("taskset") or (
            "/usr/bin/taskset" if taskset_available else None)
    cpus = _available_cpus()
    memory = _available_memory_mb()
    fallback = None
    if requested > 2:
        requested = 2
    if requested <= 1:
        requested = 1
    if requested > 1 and cpu_budget < 2:
        fallback = "the CPU budget is too small for two workers"
    if requested > 1 and require_taskset and not taskset:
        fallback = "taskset is unavailable, so the CPU limit cannot be applied"
    if requested > 1 and len(cpus) < 2:
        fallback = "fewer than two logical CPUs are available"
    if (requested > 1 and memory is not None
            and memory < int(min_memory_mb)):
        fallback = ("available memory is below %d MB" % int(min_memory_mb))
    effective = 1 if fallback else requested
    allowed = cpus[:cpu_budget]
    per_worker = max(1, len(allowed) // effective) if allowed else 0
    assignments = []
    for index in range(effective):
        start = index * per_worker
        chosen = allowed[start:start + per_worker]
        assignments.append(chosen or allowed[:1])
    return {
        "requested_workers": requested,
        "workers": effective,
        "serial_fallback": bool(fallback),
        "fallback_reason": fallback,
        "cpu_budget": cpu_budget,
        "available_cpus": cpus,
        "allowed_cpus": allowed,
        "cpu_assignments": assignments,
        "nice": int(nice),
        "taskset": taskset,
        "available_memory_mb": memory,
        "min_memory_mb": int(min_memory_mb),
    }


def build_group_command(group, *, python=sys.executable, limits=None,
                        start_dir=None):
    """Build one exact unittest command with the CPU/nice prefix."""
    command = [python, "-m", "unittest", "-v"] + list(group["tests"])
    limits = limits or {}
    if limits.get("workers", 0) > 1 and limits.get("taskset"):
        prefix = []
        index = None
        name = group.get("name") or ""
        if name.startswith("worker:"):
            try:
                index = int(name.split(":", 1)[1]) - 1
            except ValueError:
                index = None
        assignments = limits.get("cpu_assignments") or []
        chosen = assignments[index] if index is not None and index < len(assignments) else []
        if chosen:
            prefix.extend([limits["taskset"], "-c", ",".join(str(cpu) for cpu in chosen)])
        nice = int(limits.get("nice") or 0)
        if nice:
            prefix.extend(["nice", "-n", str(nice)])
        command = prefix + command
    return command


def _parse_unittest_output(text):
    counts = {"ran": 0, "failures": 0, "errors": 0, "skipped": 0}
    match = re.search(r"^Ran (\d+) tests? in ", text, re.MULTILINE)
    if match:
        counts["ran"] = int(match.group(1))
    status = re.search(r"^(OK|FAILED)\b(.*)$", text, re.MULTILINE)
    if status:
        detail = status.group(2)
        for key in ("failures", "errors", "skipped"):
            found = re.search(r"%s=(\d+)" % key, detail)
            if found:
                counts[key] = int(found.group(1))
    return counts


def _log_digest(path):
    data = Path(path).read_bytes()
    return {"path": str(path), "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}


def run_group(group, *, start_dir, output_dir, limits, env=None,
              timeout=None):
    """Run one group in its own process tree and capture a bounded result."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    log_path = output / ("%s.log" % group["name"].replace(":", "-"))
    command = build_group_command(group, limits=limits, start_dir=start_dir)
    child_env = dict(os.environ)
    child_env.pop("PYTHONDONTWRITEBYTECODE", None)
    child_env["PYTHONDONTWRITEBYTECODE"] = "1"
    existing = child_env.get("PYTHONPATH")
    child_env["PYTHONPATH"] = (str(start_dir) + (os.pathsep + existing
                                                 if existing else ""))
    if env:
        child_env.update(env)
    started = time.monotonic()
    result = {"name": group["name"], "modules": list(group.get("modules") or []),
              "tests": list(group["tests"]), "serial": bool(group.get("serial")),
              "command": command, "started_at": started}
    try:
        with log_path.open("wb") as stream:
            proc = subprocess.run(command, cwd=str(start_dir), env=child_env,
                                  stdout=stream, stderr=subprocess.STDOUT,
                                  timeout=timeout, check=False)
        text = log_path.read_text(encoding="utf-8", errors="replace")
        result.update({"returncode": proc.returncode,
                       "counts": _parse_unittest_output(text),
                       "log": _log_digest(log_path),
                       "elapsed_seconds": round(time.monotonic() - started, 2)})
    except FileNotFoundError as exc:
        result.update({"returncode": None, "missing": True,
                       "error": str(exc),
                       "elapsed_seconds": round(time.monotonic() - started, 2)})
    except subprocess.TimeoutExpired as exc:
        result.update({"returncode": None, "interrupted": True,
                       "error": "timed out: %s" % exc,
                       "elapsed_seconds": round(time.monotonic() - started, 2)})
    return result


def execute_plan(plan, *, start_dir, output_dir, limits, group_runner=None,
                 serial_first=True):
    """Execute serial groups first, then at most two parallel groups."""
    group_runner = group_runner or run_group
    results = []
    for group in plan.get("serial") or []:
        results.append(group_runner(group, start_dir=start_dir,
                                    output_dir=output_dir, limits=limits))
    parallel = list(plan.get("parallel") or [])
    if limits.get("workers", 1) <= 1:
        for group in parallel:
            sequential = dict(group)
            sequential["name"] = "serial:%s" % group["name"]
            sequential["serial"] = True
            results.append(group_runner(sequential, start_dir=start_dir,
                                        output_dir=output_dir, limits=limits))
        return results
    # Two workers at most; the plan itself is already disjoint by module.
    index = 0
    while index < len(parallel):
        batch = parallel[index:index + limits["workers"]]
        if len(batch) == 1:
            results.append(group_runner(batch[0], start_dir=start_dir,
                                        output_dir=output_dir, limits=limits))
        else:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(
                    max_workers=len(batch)) as pool:
                futures = [
                    pool.submit(group_runner, group, start_dir=start_dir,
                                output_dir=output_dir, limits=limits)
                    for group in batch
                ]
                for future in futures:
                    results.append(future.result())
        index += limits["workers"]
    return results


def aggregate(results, *, selected):
    totals = {"selected": int(selected), "ran": 0, "failures": 0,
              "errors": 0, "skipped": 0, "groups": len(results),
              "missing_groups": [], "failed_groups": [],
              "interrupted_groups": []}
    for result in results:
        counts = result.get("counts") or {}
        totals["ran"] += int(counts.get("ran") or 0)
        totals["failures"] += int(counts.get("failures") or 0)
        totals["errors"] += int(counts.get("errors") or 0)
        totals["skipped"] += int(counts.get("skipped") or 0)
        if result.get("missing"):
            totals["missing_groups"].append(result["name"])
        if result.get("interrupted"):
            totals["interrupted_groups"].append(result["name"])
        if result.get("returncode") not in (0, None):
            totals["failed_groups"].append(result["name"])
    totals["exit_code"] = 0 if (totals["ran"] == totals["selected"]
                                and not totals["missing_groups"]
                                and not totals["interrupted_groups"]
                                and not totals["failed_groups"]
                                and totals["failures"] == 0
                                and totals["errors"] == 0) else 1
    return totals


def _git_revision(start_dir):
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(start_dir),
                              check=True, capture_output=True,
                              text=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def build_report(*, start_dir, pattern, selected, plan, limits, results):
    totals = aggregate(results, selected=len(selected))
    return {
        "version": 1,
        "start_dir": str(start_dir),
        "pattern": pattern,
        "revision": _git_revision(Path(start_dir).resolve().parents[1]),
        "selection": {"count": len(selected), "tests": selected},
        "limits": limits,
        "plan": plan,
        "results": results,
        "totals": totals,
    }


def _print_summary(report):
    totals = report["totals"]
    limits = report["limits"]
    print("bounded parallel test run")
    print("revision: %s" % (report.get("revision") or "unavailable"))
    print("selected: %d tests" % totals["selected"])
    print("workers: %d (requested %d), CPUs per worker: %s, nice: %d"
          % (limits["workers"], limits["requested_workers"],
             limits.get("cpu_assignments"), limits.get("nice", 0)))
    if limits.get("serial_fallback"):
        print("serial fallback: %s" % limits.get("fallback_reason"))
    for result in report["results"]:
        counts = result.get("counts") or {}
        print("%-24s exit=%s ran=%s failures=%s errors=%s skipped=%s %s"
              % (result["name"], result.get("returncode"),
                 counts.get("ran", 0), counts.get("failures", 0),
                 counts.get("errors", 0), counts.get("skipped", 0),
                 (result.get("log") or {}).get("path", "")))
    print("aggregate: ran=%d failures=%d errors=%d skipped=%d exit=%d"
          % (totals["ran"], totals["failures"], totals["errors"],
             totals["skipped"], totals["exit_code"]))
    if totals["missing_groups"]:
        print("missing groups: " + ", ".join(totals["missing_groups"]))
    if totals["interrupted_groups"]:
        print("interrupted groups: " + ", ".join(totals["interrupted_groups"]))
    if totals["failed_groups"]:
        print("failed groups: " + ", ".join(totals["failed_groups"]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--start-dir", default="scripts/tests")
    parser.add_argument("--pattern", default="test*.py")
    parser.add_argument("--module", action="append", default=[])
    parser.add_argument("--test", action="append", default=[])
    parser.add_argument("--serial-module", action="append", default=[])
    parser.add_argument("--workers", type=int, default=1,
                        help="1 (default, serial) or 2 (opt-in parallel)")
    parser.add_argument("--parallel", action="store_true",
                        help="opt in to two workers; equivalent to --workers 2")
    parser.add_argument("--cpu-budget", type=int, default=DEFAULT_CPU_BUDGET)
    parser.add_argument("--nice", type=int, default=DEFAULT_NICE)
    parser.add_argument("--min-memory-mb", type=int,
                        default=DEFAULT_MIN_MEMORY_MB)
    parser.add_argument("--no-taskset", action="store_true",
                        help="test serial fallback when taskset is unavailable")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--json", default=None)
    parser.add_argument("--list", action="store_true",
                        help="print the selection and partition, then exit")
    parser.add_argument("--timeout", type=float, default=None)
    args = parser.parse_args(argv)
    start_dir = Path(args.start_dir)
    ids = collect_test_ids(start_dir, args.pattern)
    selected = select_tests(ids, modules=args.module, tests=args.test)
    if not selected:
        parser.error("no tests selected")
    workers = 2 if args.parallel else args.workers
    serial_modules = list(DEFAULT_SERIAL_MODULES) + list(args.serial_module)
    limits = resolve_limits(workers=workers, cpu_budget=args.cpu_budget,
                            nice=args.nice,
                            min_memory_mb=args.min_memory_mb,
                            require_taskset=True,
                            taskset_available=(False if args.no_taskset
                                               else None))
    plan = partition_tests(selected, workers=limits["workers"],
                           serial_modules=serial_modules)
    if args.list:
        print(json.dumps({"selection": selected, "plan": plan,
                          "limits": limits}, indent=2))
        return 0
    output_dir = Path(args.output_dir) if args.output_dir else Path(
        tempfile.mkdtemp(prefix="abdullah-tests-"))
    results = execute_plan(plan, start_dir=start_dir, output_dir=output_dir,
                           limits=limits,
                           group_runner=(lambda group, **kwargs:
                                         run_group(group, timeout=args.timeout,
                                                   **kwargs)))
    report = build_report(start_dir=start_dir, pattern=args.pattern,
                          selected=selected, plan=plan, limits=limits,
                          results=results)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(report, indent=2) + "\n")
    _print_summary(report)
    return report["totals"]["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
