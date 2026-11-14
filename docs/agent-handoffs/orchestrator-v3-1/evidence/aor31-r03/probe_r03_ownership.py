"""R03 production-boundary ownership observations; disposable fixture only.

The saved review fixture (`review03_ownership.py`) uses a sleeping inspector
whose own guard now proves containment, so it observes a proven-stopped
timeout rather than a live owner.  This probe exercises the remaining case:
an inspector that escapes into a new session and whose supervisor-side
termination is denied.  It creates no model call and kills every test PID.
"""
import json
import os
import signal
import sys
import time
from pathlib import Path
from unittest.mock import patch

repo = Path(sys.argv[1])
sys.path.insert(0, str(repo / "scripts/tests"))
from test_v31_aor31_r03 import InspectionOwnershipTests, orc  # noqa: E402


def wait_dead(pid, timeout=6.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        stat = orc.process_stat(pid)
        if not stat or stat["state"] in {"Z", "X", "x"}:
            return True
        time.sleep(0.02)
    return False


def kill(pid):
    for sender in (os.killpg, os.kill):
        try:
            sender(pid, signal.SIGKILL)
        except OSError:
            pass
    return wait_dead(pid)


def production_denied_cleanup(test):
    child_pid = test.root / "probe-inspector-child.pid"
    test.set_env(FAKE_OC_MODE="detach", FAKE_OC_PID=test.root / "probe.pid",
                 FAKE_OC_CHILD_PID=child_pid)
    route = test.route()
    test.state["model_routes"] = {"explorer": route}
    orc.save(test.rundir, test.state)
    pid = None
    try:
        with patch.object(orc.os, "kill", side_effect=PermissionError), \
                patch.object(orc.os, "killpg", side_effect=PermissionError):
            try:
                orc.call_model(test.rundir, test.state, test.cfg, "explorer",
                               "explorer", "prompt", test.project, route=route)
                outcome = "completed"
            except Exception as exc:  # noqa: BLE001 - diagnostic observation
                outcome = type(exc).__name__ + ": " + str(exc)
        state = orc.read_json(test.rundir / "state.json")
        record = state.get("active_check") or {}
        pid = int(child_pid.read_text()) if child_pid.exists() else None
        return {
            "probe": "denied-cleanup-detached-inspection",
            "outcome": outcome,
            "status": state.get("status"),
            "active_job": state.get("active_job"),
            "active_check_kind": record.get("kind"),
            "active_check_status": record.get("status"),
            "pid": record.get("pid"),
            "sid": record.get("sid"),
            "launch_file_present": bool(record.get("launch_file")
                                        and Path(record["launch_file"]).is_file()),
            "escaped_pid_recorded": pid in [
                item.get("pid") for item in record.get("escaped_processes") or []],
            "next_action": orc.next_action_for(state),
            "history_exists": test.history.exists(),
            "capture_exists": test.capture.exists(),
            "grant_ledger": orc.load_grant_ledger(test.rundir)["grants"],
            "cleanup_verified": kill(pid) if pid else True,
        }
    finally:
        if pid is None and child_pid.exists():
            pid = int(child_pid.read_text())
        if pid:
            kill(pid)


def non_run_containment(test):
    child_pid = test.root / "probe-doctor-child.pid"
    test.set_env(FAKE_OC_MODE="detach", FAKE_OC_PID=test.root / "probe-doctor.pid",
                 FAKE_OC_CHILD_PID=child_pid)
    pid = None
    try:
        with patch.object(orc.os, "kill", side_effect=PermissionError), \
                patch.object(orc.os, "killpg", side_effect=PermissionError):
            observed = orc.opencode_provider_observation(
                test.route(), test.project, cfg=test.cfg, role="explorer")
        record = observed.get("inspection_containment") or {}
        pid = int(child_pid.read_text()) if child_pid.exists() else None
        return {
            "probe": "non-run-inspection-keeps-exact-metadata",
            "reason": observed.get("inspection_reason"),
            "error_has_ownership": "ownership is unproven" in str(observed.get("error")),
            "record_kind": record.get("kind"),
            "pid": record.get("pid"),
            "sid": record.get("sid"),
            "launch_file_present": bool(record.get("launch_file")
                                        and Path(record["launch_file"]).is_file()),
            "escaped_pid_recorded": pid in [
                item.get("pid") for item in record.get("escaped_processes") or []],
            "cleanup_verified": kill(pid) if pid else True,
        }
    finally:
        if pid is None and child_pid.exists():
            pid = int(child_pid.read_text())
        if pid:
            kill(pid)


test = InspectionOwnershipTests("test_non_run_inspection_retains_exact_metadata_when_denied")
try:
    test.setUp()
    test.configure("2.2.7")
    test.clean_v2()
    print(json.dumps(production_denied_cleanup(test)), flush=True)
    test.configure("2.2.7")
    test.clean_v2()
    print(json.dumps(non_run_containment(test)), flush=True)
finally:
    test.tearDown()
    test.doCleanups()
