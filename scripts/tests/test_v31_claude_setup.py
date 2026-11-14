"""v3.1 Claude MCP registration and foreground host setup (offline fake CLI)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import install_wsl


FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
state_path = pathlib.Path(os.environ['FAKE_CLAUDE_STATE'])
mode = os.environ.get('FAKE_CLAUDE_MODE', 'normal')
args = sys.argv[1:]
state = json.loads(state_path.read_text()) if state_path.exists() else {
    'servers': {'unrelated-server': {'scope': 'user', 'type': 'stdio',
                                     'command': '/usr/bin/other', 'args': ['serve']}},
    'removed': []}
def save():
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True))
if args[:2] == ['mcp', 'get']:
    name = args[2]
    if mode == 'get_error':
        print('permission denied while reading config', file=sys.stderr)
        sys.exit(2)
    if mode == 'malformed':
        print('this is not a server record')
        sys.exit(0)
    server = state['servers'].get(name)
    if not server:
        print('No MCP server found with name: ' + name, file=sys.stderr)
        sys.exit(1)
    print(name + ':')
    print('  Scope: ' + server.get('scope', 'user') + ' config')
    print('  Type: ' + server.get('type', 'stdio'))
    print('  Command: ' + server['command'])
    print('  Args: ' + ' '.join(server.get('args', [])))
    sys.exit(0)
if args[:2] == ['mcp', 'add']:
    if mode == 'add_fail':
        print('add failed', file=sys.stderr); sys.exit(1)
    try:
        sep = args.index('--')
    except ValueError:
        sep = len(args)
    name = [item for item in args[2:sep] if not item.startswith('-') and
            item not in {'user', 'stdio'}][-1]
    server = {'scope': 'user', 'type': 'stdio', 'command': args[sep + 1],
              'args': args[sep + 2:]}
    state['servers'][name] = server
    if mode != 'add_unverified':
        save()
    sys.exit(0)
if args[:2] == ['mcp', 'remove']:
    name = args[-1]
    state['servers'].pop(name, None)
    state['removed'].append(name)
    save()
    sys.exit(0)
sys.exit(3)
'''


class ClaudeSetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = __import__("tempfile").TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        self.fake = self.bin_dir / "claude"
        self.fake.write_text(FAKE_CLAUDE)
        self.fake.chmod(0o755)
        self.state = self.root / "claude-state.json"
        self.state.write_text(json.dumps({"servers": {
            "unrelated-server": {"scope": "user", "type": "stdio",
                                 "command": "/usr/bin/other", "args": ["serve"]}},
            "removed": []}))
        self.env = {**os.environ, "FAKE_CLAUDE_STATE": str(self.state),
                    "FAKE_CLAUDE_MODE": "normal"}
        self.skill = self.root / "skill"
        (self.skill / "scripts").mkdir(parents=True)
        (self.skill / "scripts/orchestrator.py").write_text("# supervisor\n")

    def register(self, **kwargs):
        return install_wsl.register_claude(
            cli=str(self.fake), python="/usr/bin/python3",
            skill=self.skill, env=self.env, **kwargs)

    def servers(self):
        return json.loads(self.state.read_text())["servers"]

    def test_fresh_registration_is_user_scoped_stdio_and_preserves_unrelated(self):
        result = self.register()
        self.assertTrue(result["changed"])
        server = self.servers()["abdullah-orchestrator"]
        self.assertEqual(server["scope"], "user")
        self.assertEqual(server["type"], "stdio")
        self.assertEqual(server["command"], "/usr/bin/python3")
        self.assertEqual(server["args"],
                         [str(self.skill / "scripts/orchestrator.py"), "mcp"])
        self.assertIn("unrelated-server", self.servers())

    def test_repeat_registration_is_a_noop(self):
        self.register()
        before = self.state.read_bytes()
        result = self.register()
        self.assertFalse(result["changed"])
        self.assertEqual(result["state"], "already_registered")
        self.assertEqual(self.state.read_bytes(), before)

    def test_conflicting_registration_is_never_overwritten(self):
        state = json.loads(self.state.read_text())
        state["servers"]["abdullah-orchestrator"] = {
            "scope": "user", "type": "stdio", "command": "/usr/bin/python3",
            "args": ["/some/other/orchestrator.py", "mcp"]}
        self.state.write_text(json.dumps(state))
        before = self.state.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "conflicting"):
            self.register()
        self.assertEqual(self.state.read_bytes(), before)

    def test_wrong_scope_is_a_conflict(self):
        state = json.loads(self.state.read_text())
        state["servers"]["abdullah-orchestrator"] = {
            "scope": "project", "type": "stdio", "command": "/usr/bin/python3",
            "args": [str(self.skill / "scripts/orchestrator.py"), "mcp"]}
        self.state.write_text(json.dumps(state))
        with self.assertRaisesRegex(RuntimeError, "conflicting"):
            self.register()

    def test_unparsable_and_failed_inspection_are_not_treated_as_missing(self):
        for mode, pattern in (("malformed", "unparsable"), ("get_error", "without guessing")):
            with self.subTest(mode=mode):
                self.env["FAKE_CLAUDE_MODE"] = mode
                before = self.state.read_bytes()
                with self.assertRaisesRegex(RuntimeError, pattern):
                    self.register()
                self.assertEqual(self.state.read_bytes(), before)

    def test_missing_cli_reports_actionable_manual_command(self):
        with patch.object(install_wsl.shutil, "which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "Manual command|install it"):
                install_wsl.register_claude(cli=None, python="/usr/bin/python3",
                                            skill=self.skill, env=self.env)

    def test_add_failure_creates_no_registration(self):
        self.env["FAKE_CLAUDE_MODE"] = "add_fail"
        with self.assertRaisesRegex(RuntimeError, "registration failed"):
            self.register()
        self.assertNotIn("abdullah-orchestrator", self.servers())

    def test_unverified_add_rolls_back_only_this_invocation(self):
        self.env["FAKE_CLAUDE_MODE"] = "add_unverified"
        with self.assertRaisesRegex(RuntimeError, "rollback"):
            self.register()
        stored = json.loads(self.state.read_text())
        self.assertNotIn("abdullah-orchestrator", stored["servers"])
        self.assertIn("abdullah-orchestrator", stored["removed"])
        self.assertIn("unrelated-server", stored["servers"])

    def test_manual_snippets_use_separate_real_destinations_and_timeout_path(self):
        alt = self.root / "claude-config"
        with patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(alt)}):
            snippets = install_wsl.manual_claude_snippets("/usr/bin/python3",
                                                          self.skill)
        self.assertEqual(snippets["settings"]["destination"],
                         str(alt / "settings.json"))
        self.assertEqual(snippets["mcp_server"]["destination"],
                         str(alt / ".claude.json"))
        self.assertEqual(
            snippets["settings"]["content"]["env"]
            ["CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS"], "0")
        server = snippets["mcp_server"]["content"]["abdullah-orchestrator"]
        self.assertEqual(server["timeout"], 18_000_000)
        self.assertEqual(server["command"], "/usr/bin/python3")
        self.assertEqual(server["args"],
                         [str(self.skill / "scripts/orchestrator.py"), "mcp"])
        self.assertIn("mcp add-json", snippets["timeout_command"])
        self.assertIn("--scope", snippets["timeout_command"])
        self.assertTrue(any("do not put mcpServers in settings.json" in step
                            for step in snippets["merge_steps"]))
        self.assertIn("/mcp", " ".join(snippets["verify"]))

    def test_disposable_settings_and_user_mcp_stores_are_kept_separate(self):
        root = self.root / "disposable-claude"
        settings = root / "settings.json"
        mcp_store = root / ".claude.json"
        root.mkdir(parents=True)
        settings.write_text(json.dumps({"theme": "dark"}))
        mcp_store.write_text(json.dumps({"mcpServers": {
            "unrelated-server": {"type": "stdio", "command": "/usr/bin/other",
                                 "args": ["serve"]}}}))
        with patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(root)}):
            snippets = install_wsl.manual_claude_snippets("/usr/bin/python3",
                                                          self.skill)
            host = json.loads(settings.read_text())
            host.setdefault("env", {}).update(
                snippets["settings"]["content"]["env"])
            store = json.loads(mcp_store.read_text())
            store.setdefault("mcpServers", {}).update(
                snippets["mcp_server"]["content"])
        self.assertEqual(host["theme"], "dark")
        self.assertEqual(host["env"]["CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS"], "0")
        self.assertNotIn("mcpServers", host)
        self.assertIn("unrelated-server", store["mcpServers"])
        self.assertEqual(
            store["mcpServers"]["abdullah-orchestrator"]["timeout"], 18_000_000)
        # The helper never writes the developer's files.
        self.assertIn("unrelated-server", mcp_store.read_text())
        self.assertNotIn("abdullah-orchestrator", settings.read_text())

    def test_repeated_registration_and_manual_merge_are_idempotent(self):
        self.register()
        before = self.state.read_bytes()
        result = self.register()
        self.assertFalse(result["changed"])
        self.assertEqual(self.state.read_bytes(), before)
        snippets = install_wsl.manual_claude_snippets("/usr/bin/python3",
                                                      self.skill)
        store = {"mcpServers": {}}
        store["mcpServers"].update(snippets["mcp_server"]["content"])
        first = json.dumps(store, sort_keys=True)
        store["mcpServers"].update(snippets["mcp_server"]["content"])
        self.assertEqual(json.dumps(store, sort_keys=True), first)


if __name__ == "__main__":
    unittest.main()
