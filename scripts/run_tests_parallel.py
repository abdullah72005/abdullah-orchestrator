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
digests, worker/CPU limits and aggregate counts.  Discovery entries are not
the same as unique test ids: ``unittest`` finds an imported test class under
every module that imports it, so the raw entry count can exceed the unique id
count.  Selection, partitioning and accounting use the unique ids once each.
A retry is a new invocation with the failed modules and a recorded reason;
this helper does not silently rerun a group.

Hard bounds are repository policy, not defaults that a flag can relax: at most
two workers, at most four logical CPUs across their process trees, and reduced
scheduling priority.  ``--workers``/``--cpu-budget`` may only tighten those
bounds and ``--nice`` only raises the effective niceness.

Each group runs through ``_unittest_group.py``, which writes the child's own
``TestResult`` counts and per-test outcomes to a sidecar file.  The runner never
derives its accounting from ordinary test output, so nested suites and printed
``Ran N tests`` lines cannot change the result.  A group whose process tree or
sidecar cannot be proven is reported as unproven rather than passed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest

# Suites that are timing- or process-sensitive and must not share a parallel
# batch with unrelated fixtures.  They still use the repository's runner.
# The last three were named in the earlier concurrency incident: a default
# discovery selection had placed them in parallel worker groups.
DEFAULT_SERIAL_MODULES = (
    "test_v31_stage_deadline",
    "test_v121_parallel_writers",
    "test_v31_grant_contention",
    "test_v121_evidence_reuse",
    "test_live_stage_progress",
    "test_v31_review_recovery",
)

DEFAULT_CPU_BUDGET = 4
DEFAULT_WORKERS = 2
DEFAULT_NICE = 10
DEFAULT_MIN_MEMORY_MB = 1024
_TEST_ID = re.compile(r"^[A-Za-z_][\w.]*$")
_CLASS_SKIP_PREFIX = "setUpClass ("
_MODULE_SKIP_PREFIX = "setUpModule ("
_GROUP_HELPER = Path(__file__).resolve().with_name("_unittest_group.py")


def _module_of(test_id):
    return test_id.split(".", 1)[0]


def _test_signature(test):
    """Executable identity behind one discovery entry.

    An imported ``TestCase`` produces the same id from every importing module
    because ``TestCase.id`` uses the class's defining module and qualname.
    Those entries share the same class and test function, so the comparison is
    exact.  Two different classes that spoof the same id are ambiguous.
    """
    cls = test.__class__
    method = getattr(test, "_testMethodName", None)
    func = getattr(cls, method, None) if method else None
    return (cls, getattr(func, "__func__", func))


def collect_test_ids(start_dir, pattern="test*.py", *, discovery=None):
    """Collect unique test ids with the same loader/discovery used by unittest.

    ``discovery`` (when supplied) is updated with ``entries`` (raw discovery
    count), ``unique`` (returned id count) and per-id ``duplicates``.  Exact
    duplicates such as imported test classes are collapsed; a duplicate id that
    resolves to a different executable test is refused as ambiguous.
    """
    start = Path(start_dir).resolve()
    if not start.is_dir():
        raise ValueError("test directory does not exist: %s" % start)
    before = set(sys.modules)
    suite = unittest.defaultTestLoader.discover(
        str(start), pattern=pattern, top_level_dir=str(start))
    entries = []

    def walk(item):
        if isinstance(item, unittest.TestSuite):
            for child in item:
                walk(child)
        else:
            entries.append(item)

    walk(suite)
    ids = []
    seen = {}
    duplicates = {}
    ambiguous = []
    for test in entries:
        test_id = test.id()
        if test_id in seen:
            duplicates[test_id] = duplicates.get(test_id, 1) + 1
            if _test_signature(seen[test_id]) != _test_signature(test):
                ambiguous.append(test_id)
            continue
        seen[test_id] = test
        ids.append(test_id)
    if discovery is not None:
        discovery.clear()
        discovery.update({"entries": len(entries), "unique": len(ids),
                          "duplicates": duplicates})
    # Discovery imports temporary modules by their bare names.  Drop only the
    # modules imported from this start directory so a later fixture with the
    # same tiny module names cannot collide in sys.modules.  Cleanup runs even
    # when the ambiguous-id refusal below fires.
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
    if ambiguous:
        raise ValueError(
            "discovery produced conflicting tests for id(s) that cannot be "
            "deduplicated without changing semantics: "
            + ", ".join(sorted(set(ambiguous))))
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


def _in_wsl():
    """Whether this process runs inside a WSL guest."""
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    return Path("/proc/sys/fs/binfmt_misc/WSLInterop").exists()


def _windows_memory_probe():
    """Windows host free physical memory in MB, or ``None`` if unprovable."""
    executable = shutil.which("powershell.exe")
    if not executable:
        return None
    completed = subprocess.run(
        [executable, "-NoProfile", "-NonInteractive", "-Command",
         "(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory"],
        capture_output=True, text=True, timeout=30, check=False)
    match = re.search(r"\d+", completed.stdout or "")
    if completed.returncode != 0 or not match:
        return None
    return int(match.group(0)) // 1024


def host_memory_headroom_mb(*, probe=None):
    """Best-effort Windows host headroom under WSL.

    WSL reports guest free pages, which can stay high while the Windows host is
    constrained.  ``None`` means the value could not be proven, so a caller can
    choose the conservative serial fallback.
    """
    if not _in_wsl():
        return None
    probe = probe or _windows_memory_probe
    try:
        return probe()
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def resolve_limits(*, workers=DEFAULT_WORKERS, cpu_budget=DEFAULT_CPU_BUDGET,
                   nice=DEFAULT_NICE, min_memory_mb=DEFAULT_MIN_MEMORY_MB,
                   require_taskset=True, taskset_available=None,
                   wsl=False, host_memory_mb=None):
    """Resolve effective workers and CPU affinity, or a serial fallback.

    Repository bounds can only be tightened: at most two workers, at most
    ``DEFAULT_CPU_BUDGET`` logical CPUs and at least ``DEFAULT_NICE`` reduced
    priority.  ``min_memory_mb`` may only raise the repository floor; a caller
    cannot lower it to admit parallel work on a tight host.  ``wsl``/
    ``host_memory_mb`` add the Windows-host headroom gate; an unprovable host
    value is treated conservatively as unavailable.
    """
    requested = min(2, max(1, int(workers)))
    requested_cpu_budget = max(1, int(cpu_budget))
    cpu_budget = min(requested_cpu_budget, DEFAULT_CPU_BUDGET)
    requested_nice = int(nice)
    effective_nice = min(19, max(DEFAULT_NICE, requested_nice))
    min_memory_mb = max(DEFAULT_MIN_MEMORY_MB, int(min_memory_mb))
    if taskset_available is False:
        taskset = None
    else:
        taskset = shutil.which("taskset") or (
            "/usr/bin/taskset" if taskset_available else None)
    cpus = _available_cpus()
    memory = _available_memory_mb()
    fallback = None
    if requested > 1 and cpu_budget < 2:
        fallback = "the CPU budget is too small for two workers"
    if requested > 1 and require_taskset and not taskset:
        fallback = "taskset is unavailable, so the CPU limit cannot be applied"
    if requested > 1 and len(cpus) < 2:
        fallback = "fewer than two logical CPUs are available"
    if (requested > 1 and memory is not None
            and memory < int(min_memory_mb)):
        fallback = ("available memory is below %d MB" % int(min_memory_mb))
    if requested > 1 and memory is None:
        fallback = ("available memory could not be proven, so a conservative "
                    "serial run is required")
    if requested > 1 and wsl:
        if host_memory_mb is None:
            fallback = ("the Windows host memory headroom is unavailable under "
                        "WSL, so a conservative serial run is required")
        elif int(host_memory_mb) < int(min_memory_mb):
            fallback = ("the Windows host reports less than %d MB available"
                        % int(min_memory_mb))
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
        "requested_cpu_budget": requested_cpu_budget,
        "cpu_budget": cpu_budget,
        "requested_nice": requested_nice,
        "nice": effective_nice,
        "available_cpus": cpus,
        "allowed_cpus": allowed,
        "cpu_assignments": assignments,
        "taskset": taskset,
        "available_memory_mb": memory,
        "host_memory_mb": host_memory_mb,
        "wsl": bool(wsl),
        "min_memory_mb": int(min_memory_mb),
        "affinity_verified": False,
    }


def _run_affinity_probe(command):
    completed = subprocess.run(command, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, timeout=30,
                               check=False, text=True)
    return completed.returncode, completed.stdout or ""


def _affinity_prefix(taskset, cpus, nice):
    prefix = [taskset, "-c", ",".join(str(cpu) for cpu in cpus)]
    if nice:
        prefix.extend(["nice", "-n", str(nice)])
    return prefix


def probe_parallel_environment(limits, *, probe=None):
    """Prove every planned affinity and priority before starting parallel work.

    ``taskset`` being installed does not mean the planned affinity is legal in
    the current container or WSL session.  Exercise the exact prefix for each
    planned worker once with an interpreter no-op.  A failure returns the serial
    fallback: this runs before any group starts, so no parallel test work has
    been launched.
    """
    limits = dict(limits or {})
    limits.setdefault("affinity_verified", False)
    if limits.get("workers", 1) <= 1 or not limits.get("taskset"):
        return limits
    assignments = limits.get("cpu_assignments") or []
    if not assignments or not all(assignments):
        limits.update({"workers": 1, "serial_fallback": True,
                       "affinity_verified": False,
                       "fallback_reason": "no logical CPU is available for "
                                          "affinity"})
        return limits
    nice = int(limits.get("nice") or 0)
    commands = []
    for chosen in assignments:
        command = _affinity_prefix(limits["taskset"], chosen, nice)
        command.extend([sys.executable, "-c", "pass"])
        commands.append(command)
    runner = probe or _run_affinity_probe
    verified = []
    for command in commands:
        try:
            returncode, detail = runner(command)
        except (OSError, subprocess.SubprocessError) as exc:
            returncode, detail = None, str(exc)
        if returncode != 0:
            reason = ("taskset could not apply the planned CPU affinity/priority"
                      + (": " + detail.strip()
                         if detail and detail.strip() else ""))
            limits.update({"workers": 1, "serial_fallback": True,
                           "affinity_verified": False,
                           "verified_assignments": verified,
                           "fallback_reason": reason})
            return limits
        verified.append(command[command.index("-c") + 1])
    limits["affinity_verified"] = True
    limits["verified_assignments"] = verified
    return limits


def build_group_command(group, *, python=sys.executable, limits=None,
                        start_dir=None, result_path=None):
    """Build one exact group command with the CPU/nice prefix.

    With ``result_path`` the command runs ``_unittest_group.py`` so the child
    records its own counts and outcomes.  Without it, the command is the plain
    ``python -m unittest -v`` form used by diagnostics and command fixtures.
    """
    tests = list(group["tests"])
    if result_path is not None:
        command = [python, str(_GROUP_HELPER), str(result_path)] + tests
    else:
        command = [python, "-m", "unittest", "-v"] + tests
    limits = limits or {}
    if limits.get("workers", 0) > 1 and limits.get("taskset"):
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
            command = _affinity_prefix(limits["taskset"], chosen,
                                       int(limits.get("nice") or 0)) + command
    return command


def _parse_unittest_output(text):
    """Read the runner's own final summary from a combined log.

    Ordinary tests can print their own ``Ran N tests`` and ``OK`` lines (for
    example when they run a nested suite).  The group's summary is emitted last,
    so the final match is the authoritative one for display and fallback.
    """
    counts = {"ran": 0, "failures": 0, "errors": 0, "skipped": 0}
    matches = list(re.finditer(r"^Ran (\d+) tests? in ", text, re.MULTILINE))
    if matches:
        counts["ran"] = int(matches[-1].group(1))
    statuses = list(re.finditer(r"^(OK|FAILED)\b(.*)$", text, re.MULTILINE))
    if statuses:
        detail = statuses[-1].group(2)
        for key in ("failures", "errors", "skipped"):
            found = re.search(r"%s=(\d+)" % key, detail)
            if found:
                counts[key] = int(found.group(1))
    return counts


def _log_digest(path):
    data = Path(path).read_bytes()
    return {"path": str(path), "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}


_SIGNAL_NAMES = {signal.SIGINT: "SIGINT", signal.SIGTERM: "SIGTERM",
                 signal.SIGQUIT: "SIGQUIT", signal.SIGHUP: "SIGHUP",
                 signal.SIGKILL: "SIGKILL"}
_ACTIVE_PROCS = {}
_ACTIVE_LOCK = threading.Lock()


def _signal_group(proc, number, pgid=None):
    if pgid is None:
        try:
            pgid = os.getpgid(proc.pid)
        except (OSError, ProcessLookupError):
            pgid = proc.pid
    try:
        os.killpg(pgid, number)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        try:
            proc.send_signal(number)
            return True
        except (OSError, ProcessLookupError):
            return False


def _group_alive(pgid):
    """Whether any process remains in ``pgid``'s process group."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_group_gone(pgid, timeout):
    deadline = time.monotonic() + max(0.0, float(timeout))
    while True:
        if not _group_alive(pgid):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.02)


def _terminate_group(proc, *, grace=5.0):
    """Stop one group's whole process tree.

    Waiting for the leader is not enough: a descendant can ignore SIGTERM (or
    keep running) after the leader exits and would otherwise escape the runner.
    This waits for the entire process group, escalates to SIGKILL, and reports
    whether containment could actually be proven.

    Returns ``(returncode, contained)``.
    """
    if proc is None:
        return None, True
    try:
        pgid = os.getpgid(proc.pid)
    except (OSError, ProcessLookupError):
        pgid = proc.pid
    if proc.poll() is None:
        _signal_group(proc, signal.SIGTERM, pgid)
        try:
            proc.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            pass
    if _group_alive(pgid):
        _signal_group(proc, signal.SIGTERM, pgid)
        if not _wait_group_gone(pgid, grace):
            _signal_group(proc, signal.SIGKILL, pgid)
            try:
                proc.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                pass
            if not _wait_group_gone(pgid, grace):
                return proc.poll(), False
    return proc.poll(), True


def _terminate_active(registry=None):
    """Stop every registered group; return names whose containment is unproven."""
    registry = _ACTIVE_PROCS if registry is None else registry
    with _ACTIVE_LOCK:
        procs = list(registry.items())
    unproven = []
    for name, proc in procs:
        _returncode, contained = _terminate_group(proc)
        if not contained:
            unproven.append(name)
    return unproven


def _log_path(output_dir, name):
    return Path(output_dir) / ("%s.log" % name.replace(":", "-"))


def _annotate_log(result, path, *, parse_counts=False):
    path = Path(path)
    if not path.is_file():
        return result
    text = path.read_text(encoding="utf-8", errors="replace")
    if parse_counts and "counts" not in result:
        result["counts"] = _parse_unittest_output(text)
    result["log"] = _log_digest(path)
    return result


def _read_group_result(path):
    """Load the child's structured result, or ``None`` when it is unusable."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if not all(key in data for key in ("ran", "failures", "errors", "skipped",
                                       "outcomes")):
        return None
    if not isinstance(data.get("outcomes"), dict):
        return None
    return data


def _covered_ids(selected, outcomes):
    """Return selected ids with a terminal outcome and class/module expansions.

    A class/module ``SkipTest`` is recorded by unittest as one sentinel skip
    (``setUpClass (module.Class)``), not as per-test outcomes.  Expanding only
    the selected tests that belong to that exact class/module keeps a skip
    elsewhere in the group from accounting for an unrelated missing test.
    """
    selected_set = set(selected)
    outcomes = outcomes or {}
    covered = {test_id for test_id in outcomes if test_id in selected_set}
    expanded = set()
    for test_id, status in outcomes.items():
        if status != "skipped":
            continue
        targets = []
        if test_id.startswith(_CLASS_SKIP_PREFIX) and test_id.endswith(")"):
            class_name = test_id[len(_CLASS_SKIP_PREFIX):-1]
            targets = [selected_id for selected_id in selected_set
                       if selected_id.startswith(class_name + ".")]
        elif test_id.startswith(_MODULE_SKIP_PREFIX) and test_id.endswith(")"):
            module = test_id[len(_MODULE_SKIP_PREFIX):-1]
            targets = [selected_id for selected_id in selected_set
                       if _module_of(selected_id) == module]
        for selected_id in targets:
            if selected_id not in covered:
                covered.add(selected_id)
                expanded.add(selected_id)
    return covered, expanded


def run_group(group, *, start_dir, output_dir, limits, env=None,
              timeout=None, registry=None, termination_grace=5.0):
    """Run one group in its own process tree and capture a bounded result."""
    start_dir = Path(start_dir).resolve()
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    log_path = _log_path(output, group["name"])
    result_path = output / ("%s.result.json"
                            % group["name"].replace(":", "-"))
    try:
        result_path.unlink()
    except FileNotFoundError:
        pass
    command = build_group_command(group, limits=limits, start_dir=start_dir,
                                  result_path=result_path)
    child_env = dict(os.environ)
    child_env.pop("PYTHONDONTWRITEBYTECODE", None)
    child_env["PYTHONDONTWRITEBYTECODE"] = "1"
    existing = child_env.get("PYTHONPATH")
    child_env["PYTHONPATH"] = (str(start_dir) + (os.pathsep + existing
                                                 if existing else ""))
    if env:
        child_env.update(env)
    registry = _ACTIVE_PROCS if registry is None else registry
    started = time.monotonic()
    result = {"name": group["name"], "modules": list(group.get("modules") or []),
              "tests": list(group["tests"]), "serial": bool(group.get("serial")),
              "command": command, "started_at": started}
    interrupted = None
    proc = None
    try:
        with log_path.open("wb") as stream:
            proc = subprocess.Popen(command, cwd=str(start_dir), env=child_env,
                                    stdout=stream, stderr=subprocess.STDOUT,
                                    start_new_session=True)
            with _ACTIVE_LOCK:
                registry[group["name"]] = proc
            try:
                returncode = proc.wait(timeout=timeout)
            finally:
                with _ACTIVE_LOCK:
                    registry.pop(group["name"], None)
        returncode, contained = _terminate_group(proc, grace=termination_grace)
        if not contained:
            result["containment_failed"] = True
        if returncode is not None and returncode < 0:
            interrupted = _SIGNAL_NAMES.get(-returncode,
                                            "signal %d" % -returncode)
    except FileNotFoundError as exc:
        result.update({"returncode": None, "missing": True,
                       "error": str(exc),
                       "elapsed_seconds": round(time.monotonic() - started, 2)})
        return result
    except subprocess.TimeoutExpired:
        returncode, contained = _terminate_group(proc, grace=termination_grace)
        if not contained:
            result["containment_failed"] = True
        interrupted = "timeout after %ss" % timeout
        result["error"] = "timed out"
    except BaseException:
        _terminate_group(proc, grace=termination_grace)
        raise
    result.update({"returncode": returncode,
                   "elapsed_seconds": round(time.monotonic() - started, 2)})
    payload = _read_group_result(result_path)
    if payload is not None:
        result.update({
            "counts": {"ran": int(payload.get("ran") or 0),
                       "failures": int(payload.get("failures") or 0),
                       "errors": int(payload.get("errors") or 0),
                       "skipped": int(payload.get("skipped") or 0)},
            "outcomes": dict(payload.get("outcomes") or {}),
            "skip_reasons": dict(payload.get("skip_reasons") or {}),
            "counts_source": "result",
        })
        if payload.get("error"):
            result["error"] = str(payload["error"])
    else:
        result["counts_source"] = "unavailable"
    _annotate_log(result, log_path, parse_counts=payload is None)
    if interrupted:
        result.update({"interrupted": True, "interrupt_reason": interrupted})
    return result


def _unstarted_result(group, output_dir, reason, *, started,
                      termination_unproven=False):
    """Result for a group that started but lost its result, or never started."""
    result = {"name": group["name"],
              "modules": list(group.get("modules") or []),
              "tests": list(group["tests"]),
              "serial": bool(group.get("serial")),
              "returncode": None, "counts": {},
              "counts_source": "unavailable",
              "elapsed_seconds": 0.0}
    if started:
        # The group began before the runner was interrupted: keep any partial
        # log and record the interruption rather than a plain failure.
        _annotate_log(result, _log_path(output_dir, group["name"]))
        result.update({"interrupted": True, "cancel_reason": reason})
        if result.get("log"):
            result["partial"] = True
    else:
        result.update({"cancelled": True, "cancel_reason": reason})
    if termination_unproven:
        result["containment_failed"] = True
    return result


def execute_plan(plan, *, start_dir, output_dir, limits, group_runner=None,
                 serial_first=True, registry=None):
    """Execute serial groups first, then at most two parallel groups."""
    group_runner = group_runner or run_group
    results = []
    planned = list(plan.get("serial") or [])
    parallel = list(plan.get("parallel") or [])
    if limits.get("workers", 1) <= 1:
        parallel = []
        for group in plan.get("parallel") or []:
            sequential = dict(group)
            sequential["name"] = "serial:%s" % group["name"]
            sequential["serial"] = True
            parallel.append(sequential)
    all_groups = planned + parallel
    started_groups = set()
    cancelled = threading.Event()

    def run(group):
        if cancelled.is_set():
            return _unstarted_result(group, output_dir, "runner cancelled",
                                     started=False)
        started_groups.add(group["name"])
        return group_runner(group, start_dir=start_dir,
                            output_dir=output_dir, limits=limits)

    try:
        for group in planned:
            if cancelled.is_set():
                break
            results.append(run(group))
        if limits.get("workers", 1) <= 1:
            for group in parallel:
                if cancelled.is_set():
                    break
                results.append(run(group))
        else:
            # Two workers at most; the plan itself is already disjoint by module.
            index = 0
            while index < len(parallel) and not cancelled.is_set():
                batch = parallel[index:index + limits["workers"]]
                if len(batch) == 1:
                    results.append(run(batch[0]))
                else:
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor(
                            max_workers=len(batch)) as pool:
                        futures = [pool.submit(run, group) for group in batch]
                        try:
                            for future in futures:
                                results.append(future.result())
                        except KeyboardInterrupt:
                            # Stop live trees before the executor's shutdown
                            # waits, and prevent any queued shard from starting.
                            cancelled.set()
                            _terminate_active(registry)
                            raise
                index += limits["workers"]
    except KeyboardInterrupt:
        # Stop every live process tree before returning an interrupted report.
        cancelled.set()
        unproven = set(_terminate_active(registry))
        done = {result.get("name") for result in results}
        for group in all_groups:
            if group["name"] not in done:
                results.append(_unstarted_result(
                    group, output_dir, "runner interrupted",
                    started=group["name"] in started_groups,
                    termination_unproven=group["name"] in unproven))
    return results


def aggregate(results, *, selected):
    totals = {"selected": int(selected), "ran": 0, "failures": 0,
              "errors": 0, "skipped": 0, "class_skips": 0,
              "class_skipped_tests": 0, "accounted": 0,
              "groups": len(results),
              "missing_groups": [], "failed_groups": [],
              "interrupted_groups": [], "cancelled_groups": [],
              "unaccounted_groups": [], "unproven_groups": [],
              "missing_tests": {}}
    for result in results:
        counts = result.get("counts") or {}
        ran = int(counts.get("ran") or 0)
        totals["ran"] += ran
        totals["failures"] += int(counts.get("failures") or 0)
        totals["errors"] += int(counts.get("errors") or 0)
        totals["skipped"] += int(counts.get("skipped") or 0)
        if result.get("missing"):
            totals["missing_groups"].append(result["name"])
        if result.get("cancelled"):
            totals["cancelled_groups"].append(result["name"])
        if result.get("containment_failed"):
            totals["unproven_groups"].append(result["name"])
        returncode = result.get("returncode")
        if (result.get("interrupted")
                or (isinstance(returncode, int) and returncode < 0)):
            totals["interrupted_groups"].append(result["name"])
        elif returncode not in (0, None):
            totals["failed_groups"].append(result["name"])
        outcomes = result.get("outcomes")
        if isinstance(outcomes, dict):
            totals["class_skips"] += sum(
                1 for test_id, status in outcomes.items()
                if status == "skipped"
                and (test_id.startswith(_CLASS_SKIP_PREFIX)
                     or test_id.startswith(_MODULE_SKIP_PREFIX)))
        if (returncode == 0 and not result.get("cancelled")
                and not result.get("interrupted")):
            group_tests = list(result.get("tests") or [])
            if isinstance(outcomes, dict):
                covered, expanded = _covered_ids(group_tests, outcomes)
                totals["accounted"] += len(covered)
                totals["class_skipped_tests"] += len(expanded)
                missing = set(group_tests) - covered
                if missing:
                    totals["unaccounted_groups"].append(result["name"])
                    totals["missing_tests"][result["name"]] = sorted(missing)
            else:
                # Without the child's own outcomes a skip anywhere in the log
                # cannot prove which selected test ran, so the group is not
                # reusable evidence.
                totals["unaccounted_groups"].append(result["name"])
    totals["exit_code"] = 0 if (totals["accounted"] == totals["selected"]
                                and not totals["missing_groups"]
                                and not totals["interrupted_groups"]
                                and not totals["cancelled_groups"]
                                and not totals["failed_groups"]
                                and not totals["unaccounted_groups"]
                                and not totals["unproven_groups"]
                                and totals["failures"] == 0
                                and totals["errors"] == 0) else 1
    return totals


def _git(start_dir, *args):
    return subprocess.run(["git", *args], cwd=str(start_dir), check=True,
                          capture_output=True).stdout


def _source_state(start_dir):
    """Source identity before/after a run, including dirty worktree bytes.

    A bare ``HEAD`` cannot show a dirty or mid-run-changing checkout, so this
    fingerprints the revision, status, tracked binary diff and the bytes of
    every untracked, non-ignored file.  Hashing only status would leave an edit
    to an existing untracked test invisible.
    """
    root = Path(start_dir).resolve().parents[1]
    try:
        head = _git(root, "rev-parse", "HEAD").decode("utf-8").strip()
        status = _git(root, "status", "--porcelain=v1",
                      "--untracked-files=normal")
        diff = _git(root, "diff", "HEAD", "--binary")
        untracked = _git(root, "ls-files", "--others", "--exclude-standard",
                         "-z")
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
        return {"head": None, "dirty": None, "fingerprint": None}
    digest = hashlib.sha256()
    digest.update(head.encode("utf-8", "replace"))
    digest.update(b"\0")
    digest.update(status)
    digest.update(b"\0")
    digest.update(diff)
    digest.update(b"\0untracked\0")
    paths = sorted(part for part in untracked.split(b"\0") if part)
    for relative in paths:
        digest.update(relative)
        digest.update(b"\0")
        try:
            data = (root / os.fsdecode(relative)).read_bytes()
        except OSError:
            digest.update(b"<unreadable>")
        else:
            digest.update(hashlib.sha256(data).digest())
    return {"head": head, "dirty": bool(status.strip()),
            "untracked": len(paths),
            "fingerprint": digest.hexdigest()}


def build_report(*, start_dir, pattern, selected, plan, limits, results,
                 discovery=None, source_before=None, source_after=None):
    totals = aggregate(results, selected=len(selected))
    if source_after is None:
        source_after = _source_state(start_dir)
    if source_before is None:
        source_before = source_after
    discovery = dict(discovery or {})
    entry_count = int(discovery.get("entries", len(selected)))
    before_fingerprint = source_before.get("fingerprint")
    after_fingerprint = source_after.get("fingerprint")
    changed = before_fingerprint != after_fingerprint
    unstable = []
    if changed:
        unstable.append("source changed during execution")
    if source_before.get("dirty") or source_after.get("dirty"):
        unstable.append("checkout was dirty")
    if not before_fingerprint or not after_fingerprint:
        unstable.append("source fingerprint unavailable")
    stable = not unstable and not changed
    return {
        "version": 1,
        "start_dir": str(start_dir),
        "pattern": pattern,
        "revision": source_before.get("head") or source_after.get("head"),
        "selection": {"count": len(selected), "tests": selected,
                      "discovered_entries": entry_count,
                      "duplicate_ids": discovery.get("duplicates") or {}},
        "source": {"before": source_before, "after": source_after,
                   "changed": changed,
                   "stable": stable,
                   "evidence_label": ("reusable" if stable
                                      else "local diagnostics"),
                   "unstable_reason": ("; ".join(unstable) if unstable
                                       else None)},
        "limits": limits,
        "plan": plan,
        "results": results,
        "totals": totals,
    }


def _print_summary(report):
    totals = report["totals"]
    limits = report["limits"]
    print("bounded parallel test run")
    print("revision: %s%s" % (report.get("revision") or "unavailable",
                              " (dirty)" if (report.get("source") or {}).get(
                                  "before", {}).get("dirty") else ""))
    selection = report.get("selection") or {}
    print("selected: %d unique tests (%d discovery entries)"
          % (totals["selected"], selection.get("discovered_entries",
                                               totals["selected"])))
    print("workers: %d (requested %d), CPU budget: %d, "
          "CPUs per worker: %s, nice: %d"
          % (limits["workers"], limits["requested_workers"],
             limits.get("cpu_budget", 0),
             limits.get("cpu_assignments"), limits.get("nice", 0)))
    if limits.get("serial_fallback"):
        print("serial fallback: %s" % limits.get("fallback_reason"))
    source = report.get("source") or {}
    if source.get("changed"):
        print("source changed during execution: %s -> %s"
              % ((source.get("before") or {}).get("fingerprint"),
                 (source.get("after") or {}).get("fingerprint")))
    if not source.get("stable", True):
        print("evidence: %s (%s)"
              % (source.get("evidence_label", "local diagnostics"),
                 source.get("unstable_reason") or "unstable source"))
    else:
        print("evidence: reusable (clean, stable source)")
    for result in report["results"]:
        counts = result.get("counts") or {}
        print("%-24s exit=%s ran=%s failures=%s errors=%s skipped=%s %s"
              % (result["name"], result.get("returncode"),
                 counts.get("ran", 0), counts.get("failures", 0),
                 counts.get("errors", 0), counts.get("skipped", 0),
                 (result.get("log") or {}).get("path", "")))
    print("aggregate: accounted=%d/%d ran=%d failures=%d errors=%d "
          "skipped=%d class-skipped-tests=%d exit=%d"
          % (totals["accounted"], totals["selected"], totals["ran"],
             totals["failures"], totals["errors"], totals["skipped"],
             totals["class_skipped_tests"], totals["exit_code"]))
    if totals["missing_groups"]:
        print("missing groups: " + ", ".join(totals["missing_groups"]))
    if totals["interrupted_groups"]:
        print("interrupted groups: " + ", ".join(totals["interrupted_groups"]))
    if totals["cancelled_groups"]:
        print("cancelled groups: " + ", ".join(totals["cancelled_groups"]))
    if totals["unaccounted_groups"]:
        print("unaccounted groups: " + ", ".join(totals["unaccounted_groups"]))
    if totals["unproven_groups"]:
        print("containment unproven: " + ", ".join(totals["unproven_groups"]))
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
    parser.add_argument("--cpu-budget", type=int, default=DEFAULT_CPU_BUDGET,
                        help="logical CPUs; effective value is capped at %d"
                             % DEFAULT_CPU_BUDGET)
    parser.add_argument("--nice", type=int, default=DEFAULT_NICE,
                        help="scheduling niceness; values below %d are raised "
                             "to keep reduced priority" % DEFAULT_NICE)
    parser.add_argument("--min-memory-mb", type=int,
                        default=DEFAULT_MIN_MEMORY_MB,
                        help="available-memory floor; values below %d are "
                             "raised to the repository minimum"
                             % DEFAULT_MIN_MEMORY_MB)
    parser.add_argument("--no-taskset", action="store_true",
                        help="test serial fallback when taskset is unavailable")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--json", default=None)
    parser.add_argument("--list", action="store_true",
                        help="print the selection and partition, then exit")
    parser.add_argument("--timeout", type=float, default=None)
    args = parser.parse_args(argv)
    start_dir = Path(args.start_dir)
    discovery = {}
    ids = collect_test_ids(start_dir, args.pattern, discovery=discovery)
    selected = select_tests(ids, modules=args.module, tests=args.test)
    if not selected:
        parser.error("no tests selected")
    workers = 2 if args.parallel else args.workers
    serial_modules = list(DEFAULT_SERIAL_MODULES) + list(args.serial_module)
    wsl = _in_wsl()
    host_memory = (host_memory_headroom_mb()
                   if wsl and min(2, max(1, workers)) > 1 else None)
    limits = resolve_limits(workers=workers, cpu_budget=args.cpu_budget,
                            nice=args.nice,
                            min_memory_mb=args.min_memory_mb,
                            require_taskset=True,
                            taskset_available=(False if args.no_taskset
                                               else None),
                            wsl=wsl, host_memory_mb=host_memory)
    limits = probe_parallel_environment(limits)
    plan = partition_tests(selected, workers=limits["workers"],
                           serial_modules=serial_modules)
    if args.list:
        print(json.dumps({"discovery": discovery, "selection": selected,
                          "plan": plan, "limits": limits}, indent=2))
        return 0
    output_dir = Path(args.output_dir) if args.output_dir else Path(
        tempfile.mkdtemp(prefix="abdullah-tests-"))
    source_before = _source_state(start_dir)
    results = execute_plan(plan, start_dir=start_dir, output_dir=output_dir,
                           limits=limits,
                           group_runner=(lambda group, **kwargs:
                                         run_group(group, timeout=args.timeout,
                                                   **kwargs)))
    source_after = _source_state(start_dir)
    report = build_report(start_dir=start_dir, pattern=args.pattern,
                          selected=selected, plan=plan, limits=limits,
                          results=results, discovery=discovery,
                          source_before=source_before,
                          source_after=source_after)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(report, indent=2) + "\n")
    _print_summary(report)
    return report["totals"]["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
