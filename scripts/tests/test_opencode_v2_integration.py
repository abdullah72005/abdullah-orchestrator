"""Opt-in real OpenCode V2 checks; no model call, no authentication.

Set ABDULLAH_OPENCODE_V2_BIN to an isolated V2.2.x binary to run these.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import test_orchestrator as baseline

orc = baseline.orc
V2_BIN = os.environ.get("ABDULLAH_OPENCODE_V2_BIN")
VARIANT_FIXTURE = (Path(__file__).parent / "fixtures"
                   / "opencode-v2.2.7-variant-config.json")


@unittest.skipUnless(V2_BIN and Path(V2_BIN).is_file(),
                     "set ABDULLAH_OPENCODE_V2_BIN to an isolated V2.2.x binary")
class OpenCodeV2Binary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name) / "repo"
        self.project.mkdir()
        self.bin = str(Path(V2_BIN).resolve())
        self.cfg = orc.read_json(orc.HERE / "config.example.json")
        self.cfg["runtime"]["opencode_version"] = "auto"
        cfg_path = Path(self.tmp.name) / "config.json"
        orc.atomic_json(cfg_path, self.cfg)
        patcher = patch.object(orc, "CONFIG_PATH", cfg_path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self, argv, role="explorer", timeout=30):
        env = orc.opencode_env(role, "v2")
        return subprocess.run([self.bin, *argv], cwd=self.project, env=env,
                              capture_output=True, text=True, timeout=timeout,
                              check=False)

    def test_version_is_tested_v2_line(self):
        result = self._run(["--version"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(orc.opencode_dialect(result.stdout.strip(), cfg=self.cfg), "v2")

    def test_captured_variant_config_normalizes_to_the_recorded_document(self):
        fixture = json.loads(VARIANT_FIXTURE.read_text())
        version = self._run(["--version"])
        self.assertEqual(version.returncode, 0, version.stderr)
        self.assertEqual(
            version.stdout.strip().replace("opencode ", ""),
            fixture["provenance"]["opencode_version"])
        with tempfile.TemporaryDirectory(prefix="ao-v2-variant-") as home:
            # Credential-free disposable environment: the binary must not read
            # real user settings while normalizing this captured config.
            env = {
                "PATH": os.environ.get("PATH", ""),
                "HOME": home,
                "XDG_CONFIG_HOME": os.path.join(home, "config"),
                "XDG_DATA_HOME": os.path.join(home, "data"),
                "XDG_CACHE_HOME": os.path.join(home, "cache"),
                "OPENCODE_DISABLE_AUTOUPDATE": "true",
                "OPENCODE_DISABLE_FREE_MODELS": "1",
                "OPENCODE_CONFIG_CONTENT": json.dumps(fixture["input"]),
            }
            result = subprocess.run(
                [self.bin, "debug", "config", "--standalone"], cwd=home,
                env=env, capture_output=True, text=True, timeout=60,
                check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        entries = json.loads(result.stdout)
        documents = [item for item in entries
                     if item.get("type") == "document"]
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0]["info"], fixture["normalized_document"])

    def test_parent_config_above_git_root_is_freshly_observed(self):
        root = Path(self.tmp.name)
        home = root / "parent-home"
        home.mkdir()
        project = root / "nested" / "repo"
        project.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(project)], check=True)
        parent = root / "opencode.json"
        parent.write_text(json.dumps({"providers": {"opencode-go": {
            "settings": {"baseURL": "https://parent-first.invalid/v1"},
            "models": {"go-model": {}}}}}))
        env = {
            "PATH": str(Path(self.bin).parent) + os.pathsep + os.environ["PATH"],
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / "config"),
            "XDG_DATA_HOME": str(home / "data"),
            "XDG_CACHE_HOME": str(home / "cache"),
            "XDG_STATE_HOME": str(home / "state"),
            "OPENCODE_DISABLE_AUTOUPDATE": "1",
            "OPENCODE_DISABLE_MODELS_FETCH": "1",
            "OPENCODE_DISABLE_FREE_MODELS": "1",
        }
        route = {"provider": "opencode", "worker_provider": "opencode-go",
                 "model": "opencode-go/go-model", "effort": "low",
                 "billing": "api"}
        with patch.dict(os.environ, env, clear=True):
            first = orc.opencode_provider_observation(
                route, project=project, cfg=self.cfg, role="explorer")
            parent.write_text(json.dumps({"providers": {"opencode-go": {
                "settings": {"baseURL": "https://parent-second.invalid/v1"},
                "models": {"go-model": {}}}}}))
            second = orc.opencode_provider_observation(
                route, project=project, cfg=self.cfg, role="explorer")
        self.assertIn(str(parent), first["effective_files"])
        self.assertNotEqual(first["endpoint_sha256"], second["endpoint_sha256"])

    def test_disjoint_legacy_native_providers_match_real_normalizer(self):
        root = Path(self.tmp.name)
        home = root / "mixed-home"
        home.mkdir()
        project = root / "mixed-repo"
        project.mkdir()
        subprocess.run(["git", "init", "-q", str(project)], check=True)
        mixed = {"provider": {"opencode-go": {
            "options": {"baseURL": "https://legacy-retained.invalid/v1"}}},
            "providers": {"other-provider": {}}}
        (project / "opencode.json").write_text(json.dumps(mixed))
        env = {
            "PATH": str(Path(self.bin).parent) + os.pathsep + os.environ["PATH"],
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / "config"),
            "XDG_DATA_HOME": str(home / "data"),
            "XDG_CACHE_HOME": str(home / "cache"),
            "XDG_STATE_HOME": str(home / "state"),
            "OPENCODE_DISABLE_AUTOUPDATE": "1",
            "OPENCODE_DISABLE_MODELS_FETCH": "1",
        }
        with patch.dict(os.environ, env, clear=True):
            observed = orc.opencode_provider_observation(
                {"provider": "opencode", "worker_provider": "opencode-go",
                 "model": "opencode-go/go-model", "effort": "low",
                 "billing": "go"},
                project=project, cfg=self.cfg, role="explorer")
        self.assertIn("opencode-go", observed["providers"])
        self.assertIn("other-provider", observed["providers"])

    def test_run_help_supports_generated_flags(self):
        result = self._run(["run", "--help"])
        text = (result.stdout or "") + (result.stderr or "")
        for flag in ("--agent", "--model", "--format", "--auto", "--session",
                     "--standalone"):
            self.assertIn(flag, text)

    def test_generated_profiles_are_accepted_with_effective_denials(self):
        for role in ("explorer", "implementer", "reviewer"):
            with self.subTest(role=role):
                result = self._run(["debug", "agents", "--standalone"], role=role)
                self.assertEqual(result.returncode, 0, result.stderr)
                agents = json.loads(result.stdout)
                agent = next(a for a in agents if a.get("id") == f"abdullah-{role}")
                self.assertEqual(agent["mode"], "primary")
                actual = {(r["action"], r["resource"], r["effect"])
                          for r in agent["permissions"]}
                expected = {(r["action"], r["resource"], r["effect"])
                            for r in orc.opencode_profile(role, "v2")["permissions"]}
                self.assertTrue(expected.issubset(actual), expected - actual)
                # Ordered, effective validation: the real CLI's last-match
                # precedence must still enforce the intended restrictions.
                orc.validate_v2_effective_permissions(role, agent["permissions"])
                for action in ("subagent", "external_directory"):
                    self.assertEqual(
                        orc.v2_effective_permission(
                            agent["permissions"], action, "probe"), "deny")

    def test_doctor_introspection_matches_binary(self):
        with patch.dict(os.environ, {"PATH": str(Path(self.bin).parent)
                                     + os.pathsep + os.environ.get("PATH", "")}):
            for role in ("explorer", "implementer", "reviewer"):
                with self.subTest(role=role):
                    self.assertIs(orc.probe_opencode_config(self.project, role, "v2"), True)

    def _isolated_binary_env(self, home, *, pwd):
        return {
            "PATH": str(Path(self.bin).parent) + os.pathsep + os.environ["PATH"],
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / "config"),
            "XDG_DATA_HOME": str(home / "data"),
            "XDG_CACHE_HOME": str(home / "cache"),
            "XDG_STATE_HOME": str(home / "state"),
            "OPENCODE_DISABLE_AUTOUPDATE": "1",
            "OPENCODE_DISABLE_MODELS_FETCH": "1",
            "OPENCODE_DISABLE_FREE_MODELS": "1",
            "PWD": str(pwd),
        }

    def test_stale_ambient_pwd_does_not_redirect_config_observation(self):
        """Preflight must observe the intended checkout, not a stale sibling."""
        root = Path(self.tmp.name)
        home = root / "stale-config-home"
        home.mkdir()
        repo = root / "intended-checkout"
        repo.mkdir()
        stale_repo = root / "stale-checkout"
        stale_repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "init", "-q", str(stale_repo)], check=True)
        intended_url = "https://intended.invalid/v1"
        stale_url = "https://stale.invalid/v1"
        (repo / "opencode.json").write_text(json.dumps({
            "providers": {"opencode-go": {
                "settings": {"baseURL": intended_url},
                "models": {"go-model": {}}}}}))
        (stale_repo / "opencode.json").write_text(json.dumps({
            "providers": {"opencode-go": {
                "settings": {"baseURL": stale_url},
                "models": {"go-model": {}}}}}))
        route = {"provider": "opencode", "worker_provider": "opencode-go",
                 "model": "opencode-go/go-model", "effort": "low",
                 "billing": "go"}
        env = self._isolated_binary_env(home, pwd=stale_repo)
        inspection_env = {}
        real_bounded = orc._opencode_run_bounded

        def capture_bounded(argv, cwd, child_env, timeout, **kwargs):
            if "debug" in argv and "config" in argv:
                inspection_env.update(child_env)
            return real_bounded(argv, cwd, child_env, timeout, **kwargs)

        with patch.dict(os.environ, env, clear=True), \
                patch.object(orc, "_opencode_run_bounded",
                             side_effect=capture_bounded):
            observed = orc.opencode_provider_observation(
                route, project=repo, cfg=self.cfg, role="reviewer")
        self.assertEqual(inspection_env.get("PWD"), str(repo.resolve()))
        self.assertEqual(observed["inspection"], "normalized", observed.get("error"))
        self.assertFalse(observed.get("inspection_disagreement"), observed)
        self.assertEqual(
            observed["endpoint_sha256"],
            hashlib.sha256(intended_url.encode()).hexdigest())

    def test_reviewer_read_binds_to_the_checkout_under_stale_ambient_pwd(self):
        """The real Read tool resolves relative paths from the intended checkout."""
        root = Path(self.tmp.name)
        home = root / "read-binding-home"
        home.mkdir()
        repo = root / "read-binding-repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        relative = ".git/abdullah-review/probe.patch"
        intended = repo / relative
        intended.parent.mkdir(parents=True)
        intended.write_text("controlled fixture\n")
        (repo / "app.py").write_text("value = 1\n")
        # A decoy at the same relative path under the stale ambient PWD makes a
        # wrong checkout observable in the returned Read output, not just a miss.
        decoy = root / relative
        decoy.parent.mkdir(parents=True)
        decoy.write_text("stale decoy\n")

        state = {"requests": 0}
        read_paths = [relative, "app.py", str(repo / relative)]

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                document = json.loads(
                    self.rfile.read(int(self.headers["Content-Length"])))
                state["requests"] += 1
                base = {"id": "chatcmpl-abdullah-pwd", "object":
                        "chat.completion.chunk", "created": 1,
                        "model": "probe"}
                if document.get("tools") and not state.get("sent_reads"):
                    state["sent_reads"] = True
                    calls = [
                        {"index": i, "id": f"call_fixture_{i}",
                         "type": "function",
                         "function": {"name": "read",
                                      "arguments": json.dumps({"path": path})}}
                        for i, path in enumerate(read_paths)]
                    delta = {"role": "assistant", "tool_calls": calls}
                    reason = "tool_calls"
                else:
                    delta = {"role": "assistant",
                             "content": "offline read fixture complete"}
                    reason = "stop"
                chunks = [
                    {**base, "choices": [{"index": 0, "delta": delta,
                                          "finish_reason": None}]},
                    {**base, "choices": [{"index": 0, "delta": {},
                                          "finish_reason": reason}]},
                ]
                body = ("".join("data: " + json.dumps(chunk) + "\n\n"
                                for chunk in chunks)
                        + "data: [DONE]\n\n").encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        env = self._isolated_binary_env(home, pwd=root)
        env.update({
            "HTTP_PROXY": "http://127.0.0.1:9",
            "HTTPS_PROXY": "http://127.0.0.1:9",
            "NO_PROXY": "127.0.0.1,localhost"})
        with patch.dict(os.environ, env, clear=True):
            launch = orc._opencode_launch_context(
                "reviewer", "v2", repo, allow_free=True)
        self.assertIsNotNone(launch["env"], launch["context"].get("error"))
        self.assertEqual(launch["env"]["PWD"], str(repo.resolve()))
        run_env = dict(launch["env"])
        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            endpoint = f"http://127.0.0.1:{server.server_port}/v1"
            run_env["OPENCODE_CONFIG_CONTENT"] = json.dumps({
                "providers": {"local": {
                    "package": "@opencode/ai/providers/openai-compatible",
                    "settings": {"baseURL": endpoint, "apiKey": "fixture"},
                    "models": {"probe": {}}}},
                "agents": {"abdullah-reviewer":
                           orc.opencode_profile("reviewer", "v2")}})
            threading.Thread(target=server.serve_forever, daemon=True).start()
            response = subprocess.run(
                [self.bin, "run", "--standalone", "--auto",
                 "--agent", "abdullah-reviewer", "--model", "local/probe",
                 "--format", "json", "Run the controlled fixture."],
                cwd=repo, env=run_env, text=True, capture_output=True,
                timeout=90)
            server.shutdown()
        self.assertEqual(response.returncode, 0, response.stderr[-2000:])
        reads = []
        for line in response.stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            part = event.get("part") or {}
            if event.get("type") == "tool_use" and part.get("tool") == "read":
                reads.append(part.get("state") or {})
        self.assertTrue(reads, response.stdout[-2000:])
        by_path = {str((item.get("input") or {}).get("path")): item
                   for item in reads}
        for path in read_paths:
            self.assertIn(path, by_path, reads)
            self.assertEqual(by_path[path].get("status"), "completed",
                             by_path[path])
        self.assertIn("controlled fixture",
                      by_path[relative].get("output") or "")
        self.assertNotIn("stale decoy", by_path[relative].get("output") or "")
        self.assertIn("controlled fixture",
                      by_path[str(repo / relative)].get("output") or "")

    def test_installed_binary_fs_read_returns_supervisor_generated_hunk(self):
        """Precise boundary: the installed V2 binary's filesystem read path.

        The hunk is generated by the real supervisor delta path
        (``capture_batch_boundary`` -> ``finalize_batch_delta`` ->
        ``prepare_review_projection``), then retrieved through the binary's
        filesystem endpoint with an isolated HOME and no model transport. This
        is not a model-driven Read-tool invocation and does not attest agent
        permission enforcement; the profile test above covers the effective
        allow/deny rules. It proves that the installed binary can retrieve the
        exact bytes of a supervisor-generated hunk inside the checkout's
        review projection, which is what the Reviewer must inspect.
        """
        project = self.project
        subprocess.run(["git", "init", "-q", str(project)], check=True)
        subprocess.run(["git", "-C", str(project), "config", "user.email",
                        "fixture@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(project), "config", "user.name",
                        "fixture"], check=True)
        (project / "app.py").write_text("value = 1\n")
        subprocess.run(["git", "-C", str(project), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(project), "commit", "-qm", "base"],
                       check=True)
        run_dir = Path(self.tmp.name) / "run"
        run_dir.mkdir()
        plan = {"invariants": [],
                "batches": [{"title": "probe", "goal": "edit", "acceptance": [],
                             "checks": [["true"]], "risk": "ordinary"}]}
        state = {"id": "v2probe", "project": str(project), "batch_index": 0,
                 "plan_version": "probe-v", "plan": plan, "goal": "Add a feature",
                 "amendments": []}
        boundary = orc.capture_batch_boundary(
            project, run_dir, "impl-probe", batch_index=0, plan_version="probe-v")
        (project / "app.py").write_text("value = 42\n")
        delta = orc.finalize_batch_delta(
            project, run_dir, "impl-probe", boundary, attempt=1,
            final_snapshot=orc.source_snapshot(project))
        state["batch_deltas"] = [{
            "attempt": 1, "job_id": "impl-probe", "batch_index": 0,
            "plan_version": "probe-v", "hunks_dir": delta["hunks_dir"],
            "paths": delta["paths"], "limitations": delta["limitations"]}]
        package = {
            "commands": [], "passed": True, "source_unchanged": True,
            "candidate_hash": orc.signature(orc.source_snapshot(project)),
            "verification_path": str(run_dir / "verification.json"),
            "verification_sha256": "probe-verify", "evidence_version": 2}
        projection, rejection = orc.prepare_review_projection(
            run_dir, state, self.cfg, project, plan["batches"][0], package)
        self.assertIsNone(rejection)
        hunk_relative = next(name for name in projection["files"]
                             if name.endswith(".patch"))
        hunk = Path(projection["root"]) / hunk_relative
        self.assertIn("+value = 42", hunk.read_text())
        home = Path(self.tmp.name) / "read-home"
        home.mkdir()
        env = {
            "PATH": str(Path(self.bin).parent) + os.pathsep + os.environ["PATH"],
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / "config"),
            "XDG_DATA_HOME": str(home / "data"),
            "XDG_CACHE_HOME": str(home / "cache"),
            "XDG_STATE_HOME": str(home / "state"),
            "OPENCODE_DISABLE_AUTOUPDATE": "1",
            "OPENCODE_DISABLE_MODELS_FETCH": "1",
            "OPENCODE_DISABLE_FREE_MODELS": "1",
        }
        result = subprocess.run(
            [self.bin, "api", "--standalone", "get",
             "/api/fs/read/" + str(hunk.resolve())],
            cwd=project, env=env, capture_output=True, text=True,
            timeout=60, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, hunk.read_text())


if __name__ == "__main__":
    unittest.main()
