"""No model calls: deterministic tests of the real supervisor state machine."""
from __future__ import annotations
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "orchestrator.py"
# Tests must be hermetic: never read the developer's live config or state, even
# when the documented ABDULLAH_* overrides are exported in the shell.
os.environ.pop("ABDULLAH_CHECKOUT_REGISTRY", None)
os.environ.pop("ABDULLAH_STATE_DIR", None)
os.environ["ABDULLAH_CONFIG"] = str(SRC.parent / "config.example.json")
spec = importlib.util.spec_from_file_location("abdullah_orchestrator", SRC)
orc = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = orc
spec.loader.exec_module(orc)


def setup_repo(base):
    project = base / "demo"
    project.mkdir()
    for cmd in (["git", "init", "-q"], ["git", "config", "user.name", "Test"],
                ["git", "config", "user.email", "test@example.com"]):
        subprocess.run(cmd, cwd=project, check=True, capture_output=True)
    (project / "app.py").write_text("value = 1\n")
    subprocess.run(["git", "add", "app.py"], cwd=project, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=project, check=True)
    return project


def dead_process_identity():
    """A real PID that has exited, so recovery must prove ownership stopped."""
    proc = subprocess.Popen(["true"])
    proc.wait(timeout=5)
    return {"pid": proc.pid, "pgid": proc.pid, "sid": proc.pid}


def fake_debug_agent(argv, kwargs):
    role = argv[3].replace('abdullah-', '')
    profile = orc.opencode_profile(role, 'v1')
    rules = []
    for permission, setting in profile['permission'].items():
        for pattern, action in (setting.items() if isinstance(setting, dict) else [('*', setting)]):
            rules.append({'permission': permission, 'pattern': pattern, 'action': action})
    return subprocess.CompletedProcess(argv, 0, stdout=json.dumps({**profile, 'permission': rules}))


class ControlTests(unittest.TestCase):
    def test_plan_prompt_uses_architect_policy(self):
        prompt = orc.report_prompt("plan", {"goal": "approved handoff"})
        self.assertIn("Architect — strong Sol / Opus", prompt)

    def test_decision_prompt_uses_architect_policy(self):
        prompt = orc.report_prompt("decision", {"goal": "accept batch"})
        self.assertIn("Architect — strong Sol / Opus", prompt)

    def test_unknown_prompt_kind_fails_clearly(self):
        with self.assertRaisesRegex(RuntimeError, "Unknown role policy kind"):
            orc.report_prompt("mystery", {})

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        # Every test is isolated from the live orchestrator state and its
        # checkout registry.  Ambient ABDULLAH_* overrides are replaced as
        # well: leases_root() reads them dynamically, so exporting them for a
        # real run must not leak into the suite.
        env_patch = patch.dict(os.environ, {
            "ABDULLAH_STATE_DIR": str(self.root / "runs"),
            "ABDULLAH_CONFIG": str(self.root / "config.json"),
        })
        env_patch.start()
        # An exported registry override would defeat state-root derivation.
        os.environ.pop("ABDULLAH_CHECKOUT_REGISTRY", None)
        self.addCleanup(env_patch.stop)
        # This is also a tripwire: a test that rebinds DEFAULT_STATE outside
        # this temporary root fails immediately.
        state_patch = patch.object(orc, "DEFAULT_STATE", self.root / "runs")
        state_patch.start()
        self.addCleanup(state_patch.stop)
        if not Path(orc.DEFAULT_STATE).resolve().is_relative_to(self.root.resolve()):
            raise AssertionError("Test state root escaped the temporary directory")
        real_popen = subprocess.Popen
        def guarded_popen(args, *pos, **kwargs):
            if isinstance(args, (list, tuple)) and Path(args[0]).name in {'codex', 'claude', 'opencode'}:
                path = orc.shutil.which(args[0], path=(kwargs.get('env') or os.environ).get('PATH'))
                if not path or not Path(path).resolve().is_relative_to(self.root):
                    raise AssertionError('Tests must never launch a real model CLI')
            return real_popen(args, *pos, **kwargs)
        guard = patch.object(subprocess, 'Popen', side_effect=guarded_popen)
        guard.start()
        self.addCleanup(guard.stop)
        self.project = setup_repo(self.root)
        self.rundir = self.root / "runs/test-run00"
        self.rundir.mkdir(parents=True)
        test_cfg = orc.read_json(orc.HERE / "config.example.json")
        test_cfg.setdefault("authorization", {})["sensitive_cli_enabled"] = True
        test_cfg["verification"]["command_policy"]["exceptions"] = [{
            "argv_regex": r'.*python[0-9.]*","-c".*',
            "reason": "test harness containment/provenance probe",
            "scope": "*",
            "authorized_by": "test-operator",
        }]
        cfg_path = self.root / "config.json"
        orc.atomic_json(cfg_path, test_cfg)
        cfg_patch = patch.object(orc, "CONFIG_PATH", cfg_path)
        cfg_patch.start()
        self.addCleanup(cfg_patch.stop)
        self.cfg = orc.config()
        self.state = {
            "id": "test-run00", "status": "running", "phase": "plan",
            "project": str(self.project), "host": "codex", "goal": "Add a feature",
            "plan_approval": False, "batch_index": 0, "corrections": 0, "correction": "",
            "plan": None, "active_job": None, "completed_jobs": [], "failed_jobs": [],
            "accepted_batches": [], "review": None, "implementation": None, "verification": None,
        }
        self.state.update({
            "schema_version": orc.STATE_SCHEMA_VERSION,
            "supervisor_version": orc.SUPERVISOR_VERSION,
            "config_schema_version": orc.CONFIG_SCHEMA_VERSION,
            "config_sha256": orc.configuration_provenance().get("sha256")})
        orc.save(self.rundir, self.state)
        orc.atomic_json(self.rundir / "control.json", {"action": "run"})

    def tearDown(self):
        if not Path(orc.DEFAULT_STATE).resolve().is_relative_to(self.root.resolve()):
            raise AssertionError("A test rebound DEFAULT_STATE outside its temporary environment")
        if not orc.leases_root().resolve().is_relative_to(self.root.resolve()):
            raise AssertionError("A test rebound the checkout registry outside its temporary environment")

    def test_source_fingerprint_changes_and_survives_checkpoint(self):
        first = orc.signature(orc.source_snapshot(self.project))
        (self.project / "app.py").write_text("value = 2\n")
        second = orc.signature(orc.source_snapshot(self.project))
        self.assertNotEqual(first, second)
        self.assertEqual(second, orc.signature(orc.source_snapshot(self.project)))
        (self.project / "extra.py").write_text("hello\n")
        self.assertNotEqual(second, orc.signature(orc.source_snapshot(self.project)))

    def test_jsonl_report_requires_real_text_and_schema(self):
        event = json.dumps({"type": "text", "sessionID": "ses_123", "part": {
            "text": '{"status":"complete","summary":"read","files":["app.py"],"tests":[],"evidence":["app.py:1"],"unknowns":[],"blocker":""}'}})
        report, sid = orc.extract_cli_report("jsonl", event, self.rundir)
        self.assertEqual(sid, "ses_123")
        self.assertEqual(report["summary"], "read")
        self.assertEqual(orc.validate_report("explorer", report), report)
        with self.assertRaises(ValueError):
            orc.validate_report("reviewer", report)
        with self.assertRaises(ValueError):
            orc.extract_cli_report("jsonl", '{"type":"tool_use","part":{"tool":"bash"}}', self.rundir)

    def test_read_only_profiles_deny_shell_edits_and_subagents(self):
        for role in ("reviewer", "explorer"):
            rules = orc.opencode_profile(role, "v2")["permissions"]
            for action in ("edit", "shell", "subagent"):
                self.assertTrue(any(r["action"] == action and r["effect"] == "deny" for r in rules))
            legacy = orc.opencode_profile(role, "v1")
            self.assertIn("prompt", legacy)
            self.assertEqual(legacy["permission"]["edit"], "deny")
            self.assertEqual(legacy["permission"]["bash"], "deny")
            self.assertEqual(legacy["permission"]["task"], "deny")
            self.assertEqual(legacy["permission"]["*"], "deny")
        impl = orc.opencode_profile("implementer", "v2")["permissions"]
        self.assertTrue(any(r["resource"] == "git push *" and r["effect"] == "deny" for r in impl))
        legacy_impl = orc.opencode_profile("implementer", "v1")
        self.assertEqual(legacy_impl["permission"]["bash"]["git push *"], "deny")

    def test_opencode_v1_v2_commands_and_permission_config(self):
        route = {"provider": "opencode", "model": "opencode-go/deepseek-v4.1-flash",
                 "effort": "high", "billing": "go"}
        for dialect in ("v1", "v2"):
            with self.subTest(dialect=dialect), patch.object(orc, "opencode_dialect", return_value=dialect):
                command, env, fmt = orc.cli_command("codex", "implementer", route, "Task", self.rundir)
                self.assertEqual(fmt, "jsonl")
                if dialect == "v1":
                    self.assertNotIn("--standalone", command)
                else:
                    self.assertIn("--standalone", command)
                inline = json.loads(env["OPENCODE_CONFIG_CONTENT"])
                if dialect == "v1":
                    self.assertEqual(command[command.index("--variant") + 1], "high")
                    self.assertEqual(command[command.index("--model") + 1], route["model"])
                    self.assertIn("agent", inline)
                    self.assertEqual(inline["agent"]["abdullah-implementer"]["permission"]["task"], "deny")
                else:
                    self.assertNotIn("--variant", command)
                    self.assertEqual(command[command.index("--model") + 1], route["model"] + "#high")
                    self.assertIn("agents", inline)

    def test_opencode_generation_fails_closed_on_unknown_version(self):
        self.assertEqual(orc.opencode_dialect("opencode version 1.18.35"), "v1")
        self.assertEqual(orc.opencode_dialect("opencode 2.2.7", pinned=""), "v2")
        with self.assertRaises(RuntimeError):
            orc.opencode_dialect("release unknown")

    def test_codex_command_uses_exec_supported_approval_config(self):
        route = {"provider": "codex", "model": "gpt-6.1-sol", "effort": "high",
                 "billing": "subscription"}
        command, _env, fmt = orc.cli_command("codex", "architect", route, "Plan",
                                             self.rundir / "plan-test")
        self.assertEqual(fmt, "codex")
        self.assertNotIn("--ask-for-approval", command)
        self.assertIn("approval_policy=never", command)
        self.assertIn("--output-schema", command)
        self.assertEqual(command[:2], ["codex", "exec"])

    def test_doctor_accepts_current_v1_cli_with_required_flags(self):
        def probe(argv, **kwargs):
            if argv[-1] == "--version":
                name = argv[0]
                return subprocess.CompletedProcess(argv, 0,
                    stdout="1.18.35" if name == "opencode" else "0.167.0")
            if argv[-1] == "--help" and len(argv) > 3:
                return subprocess.CompletedProcess(argv, 0, stdout="help")
            if argv[:3] == ["opencode", "debug", "agent"]:
                return fake_debug_agent(argv, kwargs)
            if argv[:3] == ["opencode", "run", "--help"]:
                return subprocess.CompletedProcess(argv, 0,
                    stdout="--agent --model --format --auto --session --variant")
            if argv[:3] == ["codex", "exec", "--help"]:
                return subprocess.CompletedProcess(argv, 0,
                    stdout="--output-schema --output-last-message --model --sandbox --config")
            if argv[:2] == ["opencode", "models"]:
                return subprocess.CompletedProcess(argv, 0,
                    stdout="opencode-go/deepseek-v4.1-flash\n" + json.dumps({"variants":{"low":{},"high":{}}}))
            raise AssertionError(f"Unexpected probe {argv}")
        with patch.object(orc, "source_snapshot", return_value={"git_head": "a", "changed": {}}), \
             patch.object(orc.shutil, "which", return_value="/usr/bin/tool"), \
             patch.object(orc.subprocess, "run", side_effect=probe), \
             patch.dict(orc.os.environ, {"OPENAI_API_KEY": ""}):
            checks = orc.doctor(self.project)
        self.assertEqual(checks["opencode_dialect"], "v1")
        self.assertTrue(checks["ready"])

    def test_doctor_rejects_codex_exec_without_required_flags(self):
        def probe(argv, **kwargs):
            if argv[:3] == ["opencode", "debug", "agent"]:
                return fake_debug_agent(argv, kwargs)
            if argv[-1] == "--version":
                return subprocess.CompletedProcess(argv, 0, stdout="0.167.0")
            if argv[:3] == ["opencode", "run", "--help"]:
                return subprocess.CompletedProcess(argv, 0,
                    stdout="--agent --model --format --auto --session --variant")
            if argv[:3] == ["codex", "exec", "--help"]:
                return subprocess.CompletedProcess(argv, 0,
                    stdout="--output-schema --output-last-message --model")
            if argv[:2] == ["opencode", "models"]:
                return subprocess.CompletedProcess(argv, 0,
                    stdout="opencode-go/deepseek-v4.1-flash")
            raise AssertionError(f"Unexpected probe {argv}")
        with patch.object(orc, "source_snapshot", return_value={"git_head": "a", "changed": {}}), \
             patch.object(orc.shutil, "which", return_value="/usr/bin/tool"), \
             patch.object(orc.subprocess, "run", side_effect=probe), \
             patch.dict(orc.os.environ, {"OPENAI_API_KEY": ""}):
            checks = orc.doctor(self.project)
        self.assertFalse(checks["cli_compatible"]["codex"])
        self.assertFalse(checks["ready"])

    def test_zero_credit_fallback_and_go_only(self):
        self.assertFalse(self.cfg["fallback"]["enabled"])
        for role in ("explorer", "implementer", "reviewer"):
            self.assertTrue(orc.model_route(self.cfg, "codex", role)["model"].startswith("opencode-go/"))
        broken = json.loads(json.dumps(self.cfg))
        broken["workers"]["implementer"]["model"] = "opencode/deepseek-v4.1-flash"
        with patch.object(orc, "read_json", return_value=broken):
            with self.assertRaises(ValueError):
                orc.config()

    def test_full_two_batch_loop_without_real_models(self):
        calls = []
        plan = {"status": "complete", "summary": "Plan", "invariants": ["Auth"],
                "batches": [
                    {"title": "first", "goal": "Edit", "acceptance": ["Changed"], "checks": [["true"]], "risk": "ordinary"},
                    {"title": "second", "goal": "Edit again", "acceptance": ["Changed"], "checks": [["true"]], "risk": "ordinary"},
                ], "blocker": ""}

        def strong(_dir, state, _cfg, kind, extra=None, **kwargs):
            calls.append(kind)
            if kind == "plan":
                return plan
            return {"verdict": "approved", "reason": "Directly inspected app.py", "inspected": ["app.py"], "correction": ""}

        def worker(_dir, state, _cfg, role, kind, prompt, project, **kw):
            calls.append(role)
            if role == "implementer":
                (project / "app.py").write_text(f"value = {state['batch_index'] + 2}\n")
                return {"status": "complete", "summary": "Updated code", "files": ["app.py"]}, {"id": "job"}
            return {"status": "complete", "summary": "Independent check", "findings": []}, {"id": "review"}

        def verify(_dir, state, _cfg, project, batch, final=False, deadline=None):
            calls.append("final" if final else "check")
            snapshot = orc.source_snapshot(project)
            fingerprint = orc.signature(snapshot)
            evidence_path = self.root / "mock-verification.json"
            orc.atomic_json(evidence_path, {"evidence_version": 2,
                "provenance": {"version": 2, "source": snapshot,
                    "configuration": snapshot.get("configuration"),
                    "environment": snapshot.get("environment"),
                    "toolchain": snapshot.get("toolchain"),
                    "runtime_inputs": snapshot.get("runtime_inputs"),
                    "command_policy": _cfg.get("verification", {}).get("command_policy", {})},
                "candidate":snapshot, "after":snapshot, "candidate_hash":fingerprint,
                "after_hash":fingerprint, "passed":True, "source_unchanged":True,
                "commands":[]})
            state["verification"] = {"path": str(evidence_path), "passed": True,
                                     "candidate_hash": fingerprint,
                                     "evidence_version": 2}
            orc.save(self.rundir, state)
            return {"passed": True, "commands": [], "candidate_hash": fingerprint,
                    "source_unchanged": True, "evidence_version": 2,
                    "path": str(evidence_path)}

        with patch.object(orc, "strong_call", side_effect=strong), \
             patch.object(orc, "call_model", side_effect=worker), \
             patch.object(orc, "run_checks", side_effect=verify):
            for _ in range(20):
                if self.state["status"] == "complete":
                    break
                orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(self.state["status"], "complete")
        self.assertEqual(len(self.state["accepted_batches"]), 2)
        self.assertEqual(calls.count("implementer"), 2)
        self.assertEqual(calls.count("reviewer"), 2)
        self.assertEqual(calls.count("decision"), 2)
        self.assertEqual(calls.count("integration"), 1)

    def test_plan_stage_recovers_from_crash_shaped_state_without_replay(self):
        # Mirrors the persisted state left by the KeyError crash: plan phase,
        # no plan, no consumed jobs, no model job dispatched yet.
        plan = {"status": "complete", "summary": "Plan", "invariants": [],
                "batches": [{"title": "one", "goal": "A", "acceptance": ["A"],
                             "checks": [["true"]], "risk": "ordinary"}], "blocker": ""}
        captured = {}

        def fake_model(_dir, state, _cfg, role, kind, prompt, project, **kw):
            captured.update({"role": role, "kind": kind, "prompt": prompt})
            return plan, {"id": "plan-job"}

        with patch.object(orc, "call_model", side_effect=fake_model):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(captured["role"], "architect")
        self.assertEqual(captured["kind"], "plan")
        self.assertIn("Architect — strong Sol / Opus", captured["prompt"])
        self.assertEqual(self.state["phase"], "implement")
        self.assertEqual(self.state["id"], "test-run00")
        self.assertEqual(self.state["goal"], "Add a feature")
        self.assertEqual(self.state["completed_jobs"], [])

    def test_plan_approval_only_when_requested(self):
        self.state["plan_approval"] = True
        plan = {"status": "complete", "summary": "Plan", "invariants": [],
                "batches": [{"title": "one", "goal": "A", "acceptance": ["A"],
                             "checks": [["true"]], "risk": "mechanical"}], "blocker": ""}
        with patch.object(orc, "strong_call", return_value=plan):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(self.state["status"], "awaiting_plan_approval")
        self.assertEqual(self.state["batch_index"], 0)

    def test_existing_running_worker_fails_closed_on_recovery(self):
        self.state["active_job"] = {"kind": "implementer", "status": "running", "pid": 99999}
        orc.save(self.rundir, self.state)
        with patch.object(orc, "load", return_value=(self.rundir, self.state)):
            with patch.object(orc, "advance") as blocked_advance:
                orc.serve("test-run00")
                blocked_advance.assert_not_called()
        self.assertEqual(self.state["status"], "uncertain")

    def test_correction_escapes_after_bound(self):
        self.state["corrections"] = self.cfg["limits"]["max_corrections_per_batch"]
        orc.handle_repair(self.rundir, self.state, self.cfg, "still failing")
        self.assertEqual(self.state["status"], "blocked")

    def test_docker_wrong_bind_mount_blocks_acceptance(self):
        reply = subprocess.CompletedProcess([], 0, stdout=json.dumps({
            "services": {"web": {"volumes": [{"type": "bind", "source": "/not/the/project", "target": "/app"}]}}}))
        with patch.object(orc.subprocess, "run", return_value=reply):
            with self.assertRaises(RuntimeError):
                orc.check_docker_source(self.project, ["docker", "compose", "run", "--rm", "web", "pytest"])

    def test_docker_requires_test_workdir_under_exact_project_mount(self):
        good = {"services": {"web": {"working_dir": "/workspace",
                "volumes": [{"type": "bind", "source": str(self.project), "target": "/workspace"}]}}}
        with patch.object(orc.subprocess, "run", return_value=subprocess.CompletedProcess(
            [], 0, stdout=json.dumps(good))):
            proof = orc.check_docker_source(self.project, ["docker", "compose", "run", "--rm", "web", "pytest"])
        self.assertEqual(proof["working_dir"], "/workspace")
        good["services"]["web"]["working_dir"] = "/other"
        with patch.object(orc.subprocess, "run", return_value=subprocess.CompletedProcess(
            [], 0, stdout=json.dumps(good))):
            with self.assertRaisesRegex(RuntimeError, "working_dir"):
                orc.check_docker_source(self.project, ["docker", "compose", "run", "--rm", "web", "pytest"])

    def test_completed_dispatch_artifacts_recovered_after_crash(self):
        jobdir = self.rundir / "jobs/implementer-crash"
        jobdir.mkdir(parents=True)
        orc.atomic_json(jobdir / "execution.json", {"returncode": 0, "seconds": 1})
        orc.atomic_json(jobdir / "report.json", {"status": "complete", "summary": "Done"})
        orc.atomic_json(jobdir / "completion.json", {"final_snapshot": orc.source_snapshot(self.project), "session_id": "ses_done"})
        self.state["active_job"] = {"id": "crash", "kind": "implementer",
                                    "role": "implementer", "path": str(jobdir), "status": "running",
                                    **dead_process_identity()}
        orc.save(self.rundir, self.state)
        self.assertTrue(orc.recover_finished_dispatch(self.rundir, self.state))
        self.assertIsNone(self.state["active_job"])
        self.assertEqual(self.state["completed_jobs"][-1]["id"], "crash")

    def test_completed_worker_is_recovered_without_repeat_dispatch(self):
        plan = {"status": "complete", "summary": "Plan", "invariants": [],
                "batches": [{"title": "one", "goal": "A", "acceptance": ["A"],
                             "checks": [["true"]], "risk": "ordinary"}], "blocker": ""}
        self.state["plan"] = plan
        self.state["plan_version"] = orc.signature(plan)
        self.state["phase"] = "implement"
        folder = self.rundir / "jobs/implementer-done"
        folder.mkdir(parents=True)
        report = {"status": "complete", "summary": "Already implemented", "files": ["app.py"]}
        orc.atomic_json(folder / "report.json", report)
        self.state["completed_jobs"] = [{"id": "done", "kind": "implementer",
                                         "path": str(folder), "final_snapshot": orc.source_snapshot(self.project)}]
        orc.save(self.rundir, self.state)
        with patch.object(orc, "call_model") as worker:
            orc.advance(self.rundir, self.state, self.cfg)
            worker.assert_not_called()
        self.assertEqual(self.state["phase"], "verify")
        self.assertEqual(self.state["last_consumed_job_id"], "done")

    def test_fallback_is_only_once_and_never_automatic(self):
        self.state["status"] = "rate_limited"
        self.state["phase"] = "implement"
        orc.save(self.rundir, self.state)
        with patch.object(orc, "load", return_value=(self.rundir, self.state)):
            with patch.object(orc, "detach"):
                with patch.object(orc, "require_human_operator",
                                  return_value={"actor": "test", "method": "test"}):
                    orc.modify("test-run00", "approve-fallback", "implementer")
        self.assertEqual(self.state["fallback_authorization"]["role"], "implementer")
        self.assertEqual(self.state["status"], "running")
        # After dispatch, host model—not a secretly selected free Go model.
        host_route = {"provider": "codex", "model": "gpt-6-luna", "effort": "medium", "billing": "subscription"}
        command, _env, fmt = orc.cli_command("codex", "implementer", host_route,
                                             "Do a task", self.rundir / "implementer-fallback")
        self.assertIn("gpt-6-luna", command)
        self.assertEqual(fmt, "codex")

    def test_real_subprocess_adapter_parses_and_persists_opencode_session(self):
        fakebin = self.root / "bin"
        fakebin.mkdir()
        fake = fakebin / "opencode"
        fake.write_text(
            "#!/usr/bin/env python3\n"
            "import json,sys\n"
            "if '--version' in sys.argv:\n"
            "    print('1.18.35')\n"
            "    sys.exit(0)\n"
            "print(json.dumps({'type':'text', 'sessionID':'ses_realtest', "
            "'part':{'type':'text', 'text':json.dumps({"
            "'status':'complete','summary':'Found callsites','files':['app.py'],"
            "'tests':[],'evidence':['app.py:1'],'unknowns':[],'blocker':''})}}))\n"
            "print(json.dumps({'type':'step_finish', 'sessionID':'ses_realtest', "
            "'part':{'type':'step-finish','reason':'stop'}}))\n")
        fake.chmod(0o755)
        with patch.dict(orc.os.environ, {"PATH": f"{fakebin}:{orc.os.environ['PATH']}"}):
            report, job = orc.call_model(self.rundir, self.state, self.cfg, "explorer", "explorer",
                                         "Find relevant code", self.project)
        self.assertEqual(report["summary"], "Found callsites")
        self.assertEqual(job["session_id"], "ses_realtest")
        self.assertIsNone(self.state["active_job"])
        self.assertTrue((Path(job["path"]) / "report.json").exists())
        self.assertEqual(self.state["completed_jobs"][-1]["id"], job["id"])

    def test_rate_limit_preserves_session_and_code_before_resume(self):
        fakebin = self.root / "bin"
        fakebin.mkdir()
        fake = fakebin / "opencode"
        fake.write_text(
            "#!/usr/bin/env python3\n"
            "import json,sys\n"
            "if '--version' in sys.argv:\n"
            "    print('1.18.35')\n"
            "    sys.exit(0)\n"
            "print(json.dumps({'type':'text','sessionID':'ses_rate', "
            "'part':{'type':'text','text':'checkpointed'}}))\n"
            "sys.stderr.write('429 rate limit\\n')\n"
            "sys.exit(2)\n")
        fake.chmod(0o755)
        (self.project / "app.py").write_text("value = 99\n")
        expected = orc.signature(orc.source_snapshot(self.project))
        with patch.dict(orc.os.environ, {"PATH": f"{fakebin}:{orc.os.environ['PATH']}"}):
            with self.assertRaisesRegex(RuntimeError, "rate_limited"):
                orc.call_model(self.rundir, self.state, self.cfg, "implementer",
                               "implementer", "Finish task", self.project)
        self.assertEqual(self.state["retry_session"]["session_id"], "ses_rate")
        self.assertEqual(expected, orc.signature(orc.source_snapshot(self.project)))
        self.assertEqual(len(self.state["failed_jobs"]), 1)


if __name__ == "__main__":
    unittest.main()
