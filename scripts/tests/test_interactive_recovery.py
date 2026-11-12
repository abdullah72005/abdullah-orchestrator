"""Recovery regressions and zero-cost interactive workflow tests.

No paid model is launched.  Fake CLIs are installed on a temporary PATH and the
interactive control API is exercised in-process.  Host TUI behaviour is not
proven here; see test_mcp_stdio_protocol for the transport contract only.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from test_orchestrator import ControlTests, SRC, orc


def _wait_for(predicate, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError("condition was not met in time")


class ProcessIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_descendant_survives_exited_parent_and_is_detected(self):
        script = (
            "import subprocess, sys\n"
            "child = subprocess.Popen(['sleep', '30'])\n"
            "print(child.pid, flush=True)\n"
        )
        parent = subprocess.Popen([sys.executable, "-c", script],
                                  stdout=subprocess.PIPE, start_new_session=True, text=True)
        child_pid = int(parent.stdout.readline().strip())
        parent.wait(timeout=5)
        parent.stdout.close()
        self.addCleanup(lambda: _kill_quietly(child_pid))
        job = {"pid": parent.pid, "pgid": parent.pid, "sid": parent.pid,
               "pid_start": None}
        live = orc.job_liveness(job)
        self.assertTrue(live["alive"], live)
        self.assertIn(child_pid, [item["pid"] for item in live["processes"]])

    def test_zombie_is_not_live(self):
        zombie = subprocess.Popen(["true"])
        self.addCleanup(lambda: zombie.wait(timeout=5))
        _wait_for(lambda: orc.process_stat(zombie.pid) and
                  orc.process_stat(zombie.pid)["state"] == "Z")
        identity = {"pid": zombie.pid,
                    "pid_start": orc.process_stat(zombie.pid)["starttime"],
                    "pgid": zombie.pid, "sid": zombie.pid}
        live = orc.job_liveness(identity)
        self.assertFalse(live["alive"], live)

    def test_reused_pid_is_not_accepted_as_same_job(self):
        proc = subprocess.Popen(["sleep", "5"])
        self.addCleanup(lambda: _terminate_popen(proc))
        stat = orc.process_stat(proc.pid)
        job = {"pid": proc.pid, "pid_start": stat["starttime"] + 1,
               "pgid": proc.pid, "sid": proc.pid}
        live = orc.job_liveness(job)
        self.assertIsNone(live["alive"], live)
        self.assertEqual(live["reason"], "pid_reused")

    def test_termination_kills_descendants(self):
        script = (
            "import subprocess, sys, time\n"
            "child = subprocess.Popen(['sleep', '30'])\n"
            "print(child.pid, flush=True)\n"
            "time.sleep(30)\n"
        )
        parent = subprocess.Popen([sys.executable, "-c", script],
                                  stdout=subprocess.PIPE, start_new_session=True, text=True)
        child_pid = int(parent.stdout.readline().strip())
        self.addCleanup(lambda: _kill_quietly(child_pid))
        self.addCleanup(lambda: _terminate_popen(parent))
        parent.stdout.close()
        job = {"pid": parent.pid, "pgid": parent.pid, "sid": parent.pid,
               "pid_start": orc.process_stat(parent.pid)["starttime"]}
        result = orc.terminate_identity(job, grace=2)
        self.assertTrue(result["stopped"], result)
        self.assertFalse(orc.job_liveness(job)["alive"])


def _kill_quietly(pid):
    try:
        os.kill(pid, 9)
    except OSError:
        pass
    end = time.monotonic() + 3
    while time.monotonic() < end and orc.process_stat(pid):
        time.sleep(0.02)


def _terminate_popen(proc):
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass
    if getattr(proc, "stdout", None) is not None:
        try:
            proc.stdout.close()
        except OSError:
            pass


class CompletionRecoveryGateTests(unittest.TestCase):
    setUp = ControlTests.setUp
    def _artifacts(self, snapshot=None):
        jobdir = self.rundir / "jobs/implementer-gate"
        jobdir.mkdir(parents=True)
        snapshot = snapshot or orc.source_snapshot(self.project)
        orc.atomic_json(jobdir / "execution.json", {"returncode": 0, "seconds": 1})
        orc.atomic_json(jobdir / "report.json", {"status": "complete", "summary": "Done"})
        orc.atomic_json(jobdir / "completion.json",
                        {"final_snapshot": snapshot, "session_id": "ses_done"})
        return jobdir

    def test_artifacts_with_live_descendants_do_not_complete(self):
        jobdir = self._artifacts()
        parent = subprocess.Popen([sys.executable, "-c",
                                   "import subprocess,time;"
                                   "subprocess.Popen(['sleep','30']);time.sleep(30)"],
                                  start_new_session=True)
        self.addCleanup(lambda: _terminate_popen(parent))
        self.addCleanup(lambda: orc.terminate_identity(
            {"pid": parent.pid, "pgid": parent.pid, "sid": parent.pid}, grace=1))
        self.state["active_job"] = {
            "id": "gate", "kind": "implementer", "role": "implementer",
            "path": str(jobdir), "status": "running", "pid": parent.pid,
            "pgid": parent.pid, "sid": parent.pid,
            "pid_start": orc.process_stat(parent.pid)["starttime"]}
        orc.save(self.rundir, self.state)
        self.assertFalse(orc.recover_finished_dispatch(self.rundir, self.state))
        self.assertIsNotNone(self.state["active_job"])

    def test_artifacts_without_process_identity_fail_closed(self):
        jobdir = self._artifacts()
        self.state["active_job"] = {"id": "gate", "kind": "implementer",
                                    "role": "implementer", "path": str(jobdir),
                                    "status": "running"}
        orc.save(self.rundir, self.state)
        self.assertFalse(orc.recover_finished_dispatch(self.rundir, self.state))
        self.assertIsNotNone(self.state["active_job"])


    def test_missing_or_contradictory_artifacts_fail_closed(self):
        jobdir = self._artifacts()
        (jobdir / "report.json").unlink()
        self.state["active_job"] = {"id": "missing", "kind": "implementer",
                                    "role": "implementer", "path": str(jobdir),
                                    "status": "running", **{
                                        "pid": 99999999, "pgid": 99999999,
                                        "sid": 99999999}}
        self.assertFalse(orc.recover_finished_dispatch(self.rundir, self.state))
        self.assertIsNotNone(self.state["active_job"])
        orc.atomic_json(jobdir / "report.json", {"status": "complete", "summary": "Done"})
        contradictory = orc.source_snapshot(self.project)
        contradictory["git_head"] = "different"
        orc.atomic_json(jobdir / "completion.json",
                        {"final_snapshot": contradictory, "session_id": "s"})
        self.state["active_job"] = {"id": "contradictory", "kind": "implementer",
                                    "role": "implementer", "path": str(jobdir),
                                    "status": "running", "pid": 99999999,
                                    "pgid": 99999999, "sid": 99999999}
        self.assertFalse(orc.recover_finished_dispatch(self.rundir, self.state))

    def test_dead_process_artifacts_complete_only_after_liveness_proof(self):
        jobdir = self._artifacts()
        child = subprocess.Popen(["true"])
        child.wait(timeout=5)
        stat = orc.process_stat(child.pid)
        self.state["active_job"] = {
            "id": "dead", "kind": "implementer", "role": "implementer",
            "path": str(jobdir), "status": "running", "pid": child.pid,
            "pgid": child.pid, "sid": child.pid,
            "pid_start": stat["starttime"] if stat else None}
        orc.save(self.rundir, self.state)
        self.assertTrue(orc.recover_finished_dispatch(self.rundir, self.state))
        self.assertIsNone(self.state["active_job"])


class RetrySessionReconciliationTests(unittest.TestCase):
    setUp = ControlTests.setUp
    def test_stale_retry_session_is_cleared_by_reconciliation(self):
        self.state.update(
            status="uncertain", phase="implement",
            active_job={"id": "interrupted", "pid": 99999999,
                        "status": "uncertain", "error": "Run pause requested",
                        "session_id": "ses_interrupted"},
            retry_session={"role": "implementer", "session_id": "ses_old"})
        orc.save(self.rundir, self.state)
        orc.modify_locked(self.rundir, self.state, "test-run00", "reconcile")
        self.assertIsNone(self.state["retry_session"])
        self.assertIsNone(self.state["active_job"])
        self.assertEqual(self.state["status"], "paused")

    def test_rate_limited_session_may_resume_only_after_verified_reconciliation(self):
        self.state.update(
            status="uncertain", phase="implement",
            active_job={"id": "rate", "pid": 99999999, "status": "uncertain",
                        "error": "rate_limited: 429", "session_id": "ses_rate"},
            retry_session={"role": "implementer", "session_id": "ses_rate"})
        orc.save(self.rundir, self.state)
        orc.modify_locked(self.rundir, self.state, "test-run00", "reconcile")
        retry = self.state["retry_session"]
        self.assertEqual(retry["session_id"], "ses_rate")
        self.assertTrue(retry.get("reconciled"))
        self.assertTrue(retry.get("termination_verified"))

    def test_resume_refuses_uncertain_session_before_reconciliation(self):
        self.state.update(status="uncertain", active_job={"id": "x", "pid": 99999999},
                          retry_session={"role": "implementer", "session_id": "ses_x"})
        orc.save(self.rundir, self.state)
        with self.assertRaisesRegex(RuntimeError, "reconcile"):
            orc.modify_locked(self.rundir, self.state, "test-run00", "resume")


def _install_fake_clis(root: Path, mode: str = "normal"):
    fakebin = root / "bin"
    fakebin.mkdir(exist_ok=True)
    fake = fakebin / "fake_cli.py"
    fake.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys, time
args = sys.argv[1:]
name = pathlib.Path(sys.argv[0]).name
if '--version' in args:
    print('1.18.35'); sys.exit(0)
history = pathlib.Path(os.environ['FAKE_HISTORY'])
if name == 'codex':
    output = pathlib.Path(args[args.index('--output-last-message') + 1])
    kind = output.parent.name.split('-')[0]
    previous = history.read_text().splitlines() if history.exists() else []
    with history.open('a') as f: f.write(kind + '\\n')
    if kind == 'plan':
        report = {'contract_version':2, 'status':'complete', 'summary':'plan', 'invariants':['Keep behavior'],
                  'blocker':'',
                  'batches':[{'title':'batch', 'goal':'change app', 'acceptance':['done'],
                              'checks':[[sys.executable, '-c', 'pass']], 'risk':'ordinary'}]}
    elif kind == 'diagnose':
        report = {'contract_version':2, 'verdict':'changes_required', 'reason':'amendment reassessed',
                  'inspected':['app.py'], 'correction':'Apply accessibility amendment',
                  'dismissed_findings':[]}
    else:
        report = {'contract_version':2, 'verdict':'approved', 'reason':'inspected app.py', 'inspected':['app.py'],
                  'correction':'', 'dismissed_findings':[]}
    output.write_text(json.dumps(report))
else:
    role = args[args.index('--agent') + 1].replace('abdullah-', '')
    with history.open('a') as f: f.write(role + '\\n')
    if role == 'implementer':
        p = pathlib.Path('app.py')
        p.write_text(p.read_text() + '# implemented\\n')
        if os.environ.get('FAKE_SLEEP'):
            time.sleep(30)
    report = {'contract_version':2, 'status':'complete', 'summary':role, 'findings':[],
              'evidence':['app.py:1'], 'files':['app.py'], 'tests':['focused'],
              'unknowns':[], 'blocker':''} if role == 'reviewer' else {
              'contract_version':2, 'status':'complete', 'summary':role, 'files':['app.py'], 'tests':[],
              'evidence':['app.py:1'], 'unknowns':[], 'blocker':''}
    print(json.dumps({'type':'text','sessionID':'fake-session',
                      'part':{'text':json.dumps(report)}}))
''')
    fake.chmod(0o755)
    for name in ("codex", "opencode"):
        link = fakebin / name
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(fake)
    return fakebin


class InteractiveWorkflowTests(unittest.TestCase):
    def setUp(self):
        ControlTests.setUp(self)
        self.runs = self.root / "interactive-runs"
        self.history = self.root / "history"
        self.fakebin = _install_fake_clis(self.root)
        self.env = {"PATH": str(self.fakebin) + ":" + os.environ["PATH"],
                    "FAKE_HISTORY": str(self.history), "OPENAI_API_KEY": ""}
        self.state_patch = patch.object(orc, "DEFAULT_STATE", self.runs)
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)
        self.env_patch = patch.dict(os.environ, self.env)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def _start(self, require_explorer=False, plan_approval=False):
        with patch.object(orc, "DEFAULT_STATE", self.runs), \
                patch.dict(os.environ, self.env):
            started = orc.start_run(project=str(self.project), goal="Add accessible feature",
                                    host="codex", plan_approval=plan_approval,
                                    require_explorer=require_explorer, skip_doctor=True,
                                    interactive=True)
            _folder, self.state = orc.load(started["run_id"])
            return started

    def _stage(self):
        with patch.object(orc, "DEFAULT_STATE", self.runs), \
                patch.dict(os.environ, self.env):
            return orc.stage_run(self.state["id"])

    def test_visible_dispatch_returns_agent_task_and_structured_result(self):
        started = self._start()
        self.assertTrue(started["run_id"])
        result = self._stage()
        self.assertEqual(result["agent"], "architect")
        self.assertIn("Add accessible feature", result["task"])
        self.assertTrue(result["expected"])
        self.assertEqual(result["stage"], "plan")
        self.assertEqual(result["status"], "running")
        self.assertIn("report", result)
        self.assertIn("elapsed_seconds", result)

    def test_normal_workflow_with_required_explorer_has_no_duplicate_calls(self):
        self._start(require_explorer=True)
        seen = []
        for _ in range(12):
            with patch.object(orc, "DEFAULT_STATE", self.runs), \
                    patch.dict(os.environ, self.env):
                result = orc.stage_run(self.state["id"])
            seen.append(result["stage"])
            if result["status"] == "complete":
                break
        self.assertEqual(seen, ["plan", "explore", "implement", "verify",
                                "review", "accept"])
        self.assertEqual(self.history.read_text().splitlines(),
                         ["plan", "explorer", "implementer", "reviewer", "decision"])

    def test_interrupt_during_implementation_preserves_changes_and_blocks_duplicate(self):
        self._start()
        self._stage()  # plan
        os.environ["FAKE_SLEEP"] = "1"
        try:
            thread_result = {}

            def work():
                with patch.object(orc, "DEFAULT_STATE", self.runs), \
                        patch.dict(os.environ, self.env):
                    thread_result["value"] = orc.stage_run(self.state["id"])

            thread = threading.Thread(target=work)
            thread.start()
            with patch.object(orc, "DEFAULT_STATE", self.runs), \
                    patch.dict(os.environ, self.env):
                _wait_for(lambda: orc.load(self.state["id"])[1].get("active_job"))
                _wait_for(lambda: "# implemented" in (self.project / "app.py").read_text())
                result = orc.interrupt_run(self.state["id"], "Stop and recap")
            thread.join(timeout=20)
            self.assertFalse(thread.is_alive())
        finally:
            os.environ.pop("FAKE_SLEEP", None)
        _, state = orc.load(self.state["id"])
        self.assertIn(state["status"], {"paused", "uncertain"})
        self.assertTrue(result["termination"]["stopped"])
        self.assertIn("# implemented", (self.project / "app.py").read_text())
        self.assertEqual(self.history.read_text().splitlines().count("implementer"), 1)
        with patch.object(orc, "DEFAULT_STATE", self.runs), \
                patch.dict(os.environ, self.env):
            blocked = orc.stage_run(self.state["id"])
        self.assertFalse(blocked["ok"])
        self.assertIn(blocked["next_action"],
                      {"orchestrator_resume", "orchestrator_reconcile"})

    def test_recap_after_interruption_reports_partial_work_and_next_action(self):
        self._start()
        self._stage()
        os.environ["FAKE_SLEEP"] = "1"
        try:
            def work():
                with patch.object(orc, "DEFAULT_STATE", self.runs), \
                        patch.dict(os.environ, self.env):
                    orc.stage_run(self.state["id"])

            thread = threading.Thread(target=work)
            thread.start()
            with patch.object(orc, "DEFAULT_STATE", self.runs), \
                    patch.dict(os.environ, self.env):
                _wait_for(lambda: orc.load(self.state["id"])[1].get("active_job"))
                _wait_for(lambda: "# implemented" in (self.project / "app.py").read_text())
                orc.interrupt_run(self.state["id"], "recap please")
            thread.join(timeout=20)
        finally:
            os.environ.pop("FAKE_SLEEP", None)
        with patch.object(orc, "DEFAULT_STATE", self.runs), \
                patch.dict(os.environ, self.env):
            quick = orc.recap_run(self.state["id"], "quick")
            developer = orc.recap_run(self.state["id"], "developer")
        self.assertIn("app.py", quick["text"])
        self.assertIn("interrupt", quick["text"].lower())
        self.assertIn("app.py", developer["text"])
        self.assertIn("Remaining", developer["text"])
        self.assertLessEqual(len(quick["text"].splitlines()), 12)

    def test_amendment_is_persisted_and_reassessed_by_architect(self):
        self._start()
        self._stage()
        with patch.object(orc, "DEFAULT_STATE", self.runs), \
                patch.dict(os.environ, self.env):
            amended = orc.amend_run(self.state["id"],
                                    "Add keyboard accessibility",
                                    architect_review=True)
        self.assertTrue(amended["persisted"])
        _, state = orc.load(self.state["id"])
        self.assertEqual(state["amendments"][-1]["text"], "Add keyboard accessibility")
        self.assertEqual(state["phase"], "diagnose")
        with patch.object(orc, "DEFAULT_STATE", self.runs), \
                patch.dict(os.environ, self.env):
            orc.resume_run(self.state["id"])
            diagnosed = orc.stage_run(self.state["id"])
        self.assertEqual(diagnosed["stage"], "diagnose")
        _, state = orc.load(self.state["id"])
        self.assertEqual(state["phase"], "plan")
        self.assertNotIn("implementer", self.history.read_text().splitlines())


    def test_repeated_interrupt_and_resume_never_duplicates_a_dispatch(self):
        self._start()
        self._stage()  # plan
        os.environ["FAKE_SLEEP"] = "1"
        try:
            for cycle in range(2):
                def work():
                    with patch.object(orc, "DEFAULT_STATE", self.runs), \
                            patch.dict(os.environ, self.env):
                        orc.stage_run(self.state["id"])

                thread = threading.Thread(target=work)
                thread.start()
                with patch.object(orc, "DEFAULT_STATE", self.runs), \
                        patch.dict(os.environ, self.env):
                    _wait_for(lambda: orc.load(self.state["id"])[1].get("active_job"))
                    _wait_for(lambda: (self.project / "app.py").read_text().count("# implemented") >= cycle + 1)
                    orc.interrupt_run(self.state["id"], f"cycle {cycle}")
                thread.join(timeout=20)
                _, state = orc.load(self.state["id"])
                history_count = self.history.read_text().splitlines().count("implementer")
                for _ in range(2):
                    with patch.object(orc, "DEFAULT_STATE", self.runs), \
                            patch.dict(os.environ, self.env):
                        blocked = orc.stage_run(self.state["id"])
                    self.assertFalse(blocked["ok"])
                self.assertEqual(self.history.read_text().splitlines().count("implementer"),
                                 history_count)
                with patch.object(orc, "DEFAULT_STATE", self.runs), \
                        patch.dict(os.environ, self.env):
                    resumed = orc.resume_run(self.state["id"])
                self.assertEqual(resumed["phase"], "implement")
                self.assertEqual(resumed["next"]["action"], "orchestrator_stage")
        finally:
            os.environ.pop("FAKE_SLEEP", None)
        _, state = orc.load(self.state["id"])
        ids = [job.get("id") for job in state.get("completed_jobs", []) +
               state.get("failed_jobs", []) if job.get("role") == "implementer"]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), 2)

    def test_new_session_recovers_run_state_and_next_action(self):
        started = self._start()
        self._stage()
        with patch.object(orc, "DEFAULT_STATE", self.runs), \
                patch.dict(os.environ, self.env):
            listed = orc.list_runs()
            status = orc.status_run(started["run_id"])
        self.assertIn(started["run_id"], [item["run_id"] for item in listed["runs"]])
        self.assertEqual(status["run_id"], started["run_id"])
        self.assertEqual(status["phase"], "implement")
        self.assertEqual(status["next_action"], "orchestrator_stage")

    def test_status_and_recap_make_no_model_calls(self):
        started = self._start()
        self._stage()
        before = self.history.read_text().splitlines()
        with patch.object(orc, "DEFAULT_STATE", self.runs), \
                patch.dict(os.environ, self.env), \
                patch.object(orc, "call_model") as model, \
                patch.object(orc, "strong_call") as strong:
            orc.status_run(started["run_id"])
            orc.recap_run(started["run_id"], "quick")
            orc.recap_run(started["run_id"], "developer")
        model.assert_not_called()
        strong.assert_not_called()
        self.assertEqual(self.history.read_text().splitlines(), before)
        _, state = orc.load(started["run_id"])
        self.assertEqual(state["model_routes"]["architect"]["model"], "gpt-6.1-sol")
        self.assertTrue(state["model_routes"]["implementer"]["model"].startswith("opencode-go/"))

    def test_interactive_workers_do_not_receive_architect_evidence_root(self):
        self._start()
        with patch.dict(os.environ, {"LEAN_CTX_READ_ONLY_ROOTS": "/tmp/evidence-root"}):
            env = orc.opencode_env("implementer", "v1")
        self.assertNotIn("LEAN_CTX_READ_ONLY_ROOTS", env)
        self.assertNotIn("__LEAN_CTX_NO_DAEMON", env)



class McpToolCallTests(unittest.TestCase):
    setUp = ControlTests.setUp

    def test_tools_call_starts_and_reads_a_run_without_a_model(self):
        runs = self.root / "mcp-runs"
        with patch.object(orc, "DEFAULT_STATE", runs), \
                patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            started = orc.mcp_handle({
                "jsonrpc": "2.0", "id": 7, "method": "tools/call",
                "params": {"name": "orchestrator_start", "arguments": {
                    "project": str(self.project), "goal": "MCP goal",
                    "skip_doctor": True}}})
            payload = json.loads(started["result"]["content"][0]["text"])
            self.assertTrue(payload["ok"])
            run_id = payload["run_id"]
            status = orc.mcp_handle({
                "jsonrpc": "2.0", "id": 8, "method": "tools/call",
                "params": {"name": "orchestrator_status",
                           "arguments": {"run_id": run_id}}})
            status_payload = json.loads(status["result"]["content"][0]["text"])
            self.assertEqual(status_payload["run_id"], run_id)
            self.assertEqual(status_payload["next_action"], "orchestrator_stage")
            self.assertFalse(status["result"]["isError"])

    def test_tools_call_unknown_tool_is_a_protocol_error(self):
        response = orc.mcp_handle({
            "jsonrpc": "2.0", "id": 9, "method": "tools/call",
            "params": {"name": "orchestrator_nope", "arguments": {}}})
        self.assertEqual(response["error"]["code"], -32602)

@unittest.skipUnless(True, "transport-only MCP contract; Codex TUI is not exercised")
class McpTransportTests(unittest.TestCase):
    setUp = ControlTests.setUp

    def test_mcp_stdio_protocol_lists_tools_and_calls_status(self):
        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        response = orc.mcp_handle(request)
        names = {tool["name"] for tool in response["result"]["tools"]}
        for name in ("orchestrator_start", "orchestrator_stage",
                     "orchestrator_interrupt", "orchestrator_recap",
                     "orchestrator_amend", "orchestrator_resume",
                     "orchestrator_reconcile", "orchestrator_status"):
            self.assertIn(name, names)


    def test_mcp_stdio_cancellation_stops_live_worker_and_preserves_changes(self):
        fakebin = _install_fake_clis(self.root)
        runs = self.root / "stdio-runs"
        env = os.environ.copy()
        env.update({"PATH": str(fakebin) + ":" + env["PATH"],
                    "FAKE_HISTORY": str(self.root / "stdio-history"),
                    "OPENAI_API_KEY": "", "ABDULLAH_STATE_DIR": str(runs),
                    "FAKE_SLEEP": "1"})
        proc = subprocess.Popen(
            [sys.executable, str(SRC), "mcp"], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        def stop_server():
            try:
                proc.stdin.close()
            except OSError:
                pass
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            for stream in (proc.stdout, proc.stderr):
                try:
                    stream.close()
                except OSError:
                    pass

        self.addCleanup(stop_server)

        def send(value):
            proc.stdin.write(json.dumps(value) + "\n")
            proc.stdin.flush()

        def recv(timeout=40):
            end = time.monotonic() + timeout
            while time.monotonic() < end:
                ready, _, _ = select.select([proc.stdout], [], [], 0.1)
                if ready:
                    line = proc.stdout.readline()
                    if line:
                        return json.loads(line)
            raise AssertionError("MCP response timeout")

        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        recv()
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
              "params": {"name": "orchestrator_start", "arguments": {
                  "project": str(self.project), "goal": "Cancel live work",
                  "skip_doctor": True}}})
        run_id = json.loads(recv()["result"]["content"][0]["text"])["run_id"]
        send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
              "params": {"name": "orchestrator_stage", "arguments": {"run_id": run_id}}})
        recv()
        send({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
              "params": {"name": "orchestrator_stage", "arguments": {"run_id": run_id}}})
        run_dir = runs / run_id

        def worker_started():
            try:
                state = json.loads((run_dir / "state.json").read_text())
            except (OSError, ValueError):
                return False
            return (state.get("active_job")
                    and "# implemented" in (self.project / "app.py").read_text())

        _wait_for(worker_started, timeout=20)
        send({"jsonrpc": "2.0", "method": "notifications/cancelled",
              "params": {"requestId": 4, "reason": "user stop"}})
        response = recv(timeout=60)
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(payload["status"], "paused")
        self.assertEqual(payload["next_action"], "orchestrator_resume")
        state = json.loads((run_dir / "state.json").read_text())
        self.assertIsNone(state.get("active_job"))
        self.assertIn("# implemented", (self.project / "app.py").read_text())

    def test_mcp_initialize_advertises_tools_capability(self):
        response = orc.mcp_handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                   "params": {"protocolVersion": "2025-06-18"}})
        self.assertIn("tools", response["result"]["capabilities"])
        self.assertEqual(response["result"]["serverInfo"]["name"],
                         "abdullah-orchestrator")


if __name__ == "__main__":
    unittest.main()
