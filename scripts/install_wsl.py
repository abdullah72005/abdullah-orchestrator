#!/usr/bin/env python3
"""Install the single Orchestrator skill without changing old Abdullah skills."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

SKILL = Path(__file__).resolve().parent.parent
MCP_SERVER_NAME = "abdullah-orchestrator"
FOREGROUND_ENV = {"CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS": "0"}
RECOMMENDED_SERVER_TIMEOUT_MS = 18_000_000  # 5 hours; >=1000 also raises the idle floor


def manual_claude_command(python=None, skill=None):
    python = python or sys.executable
    skill = Path(skill or SKILL)
    return ["claude", "mcp", "add", "--scope", "user", "--transport", "stdio",
            MCP_SERVER_NAME, "--", python,
            str((skill / "scripts/orchestrator.py").resolve()), "mcp"]


def claude_config_paths():
    """Effective user settings and user-scoped MCP store for the Claude CLI."""
    configured = os.environ.get("CLAUDE_CONFIG_DIR")
    if configured and configured.strip():
        root = Path(configured).expanduser()
        return {"settings": root / "settings.json",
                "mcp_store": root / ".claude.json",
                "root": root}
    home = Path.home()
    return {"settings": home / ".claude" / "settings.json",
            "mcp_store": home / ".claude.json",
            "root": home / ".claude"}


def manual_claude_snippets(python=None, skill=None):
    """Separate host-settings and user MCP-store snippets; never write them."""
    command = manual_claude_command(python, skill)
    server = {
        "type": "stdio",
        "command": command[9],
        "args": [command[10], command[11]],
        "timeout": RECOMMENDED_SERVER_TIMEOUT_MS,
    }
    add_json = ["claude", "mcp", "add-json", "--scope", "user",
                MCP_SERVER_NAME, json.dumps(server, separators=(",", ":"))]
    paths = claude_config_paths()
    return {
        "shell": "export CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS=0",
        "settings": {
            "destination": str(paths["settings"]),
            "content": {"env": dict(FOREGROUND_ENV)},
        },
        "mcp_server": {
            "destination": str(paths["mcp_store"]),
            "content": {MCP_SERVER_NAME: server},
        },
        "manual_command": " ".join(shlex.quote(item) for item in command),
        "timeout_command": " ".join(shlex.quote(item) for item in add_json),
        "merge_steps": [
            f"Merge the foreground env keys into {paths['settings']} (user scope) "
            "or export them in the interactive host environment before launch.",
            f"Merge the server entry into the user-scoped MCP store {paths['mcp_store']}; "
            "do not put mcpServers in settings.json.",
            "`claude mcp add` does not install the per-server timeout. Either register "
            "with the printed `claude mcp add-json` command or add "
            f"\"timeout\": {RECOMMENDED_SERVER_TIMEOUT_MS} to the existing entry in "
            f"{paths['mcp_store']}.",
            "Preserve unrelated settings and MCP servers; re-running the installer "
            "must be a no-op for an identical registration.",
        ],
        "verify": ["Run /mcp inside Claude Code and confirm the server is connected.",
                   "Run `claude mcp get abdullah-orchestrator` to inspect scope/command.",
                   f"Confirm the user MCP entry in {paths['mcp_store']} has "
                   f"timeout {RECOMMENDED_SERVER_TIMEOUT_MS}.",
                   "A foreground tool call should not auto-background; Ctrl-C/Esc should "
                   "cancel it and the supervisor should preserve recoverable state."],
        "manual_limit": ("Fake CLI tests and documented snippets do not prove the real "
                         "Claude interactive UX, authenticated long stages or reconnect "
                         "semantics. Those require a separately authorized live check."),
    }


def _normalise_command(text):
    try:
        return shlex.split(text.strip())
    except ValueError:
        return text.strip().split()


def parse_claude_mcp_get(output):
    """Parse JSON or the human `claude mcp get` text into a normalized record."""
    text = (output or "").strip()
    if not text:
        return None
    try:
        value = json.loads(text)
    except ValueError:
        value = None
    if isinstance(value, dict):
        server = value.get("mcpServers", {}).get(MCP_SERVER_NAME) or value.get(MCP_SERVER_NAME) \
            or value.get("server") or value
        if isinstance(server, dict):
            command = server.get("command") or server.get("cmd")
            args = server.get("args") or []
            return {"scope": str(server.get("scope") or value.get("scope") or "").lower(),
                    "transport": str(server.get("type") or server.get("transport") or "stdio").lower(),
                    "command": command, "args": [str(item) for item in args] if isinstance(args, list) else []}
    record = {"scope": "", "transport": "", "command": None, "args": []}
    for line in text.splitlines():
        match = re.match(r"\s*(Scope|Type|Transport|Command|Args)\s*:\s*(.+?)\s*$", line)
        if not match:
            continue
        key, value = match.group(1), match.group(2)
        if key == "Scope":
            record["scope"] = value.lower()
        elif key in {"Type", "Transport"}:
            record["transport"] = value.lower()
        elif key == "Command":
            record["command"] = value.strip('"')
        elif key == "Args":
            record["args"] = _normalise_command(value)
    if not (record["command"] or record["args"] or record["scope"]):
        return None
    return record


def inspect_claude_registration(cli, env=None):
    """Distinguish exact/missing/conflicting/inspection-error without guessing."""
    try:
        proc = subprocess.run([cli, "mcp", "get", MCP_SERVER_NAME],
                              capture_output=True, text=True, timeout=30,
                              check=False, env=env)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"state": "error", "reason": f"CLI invocation failed: {exc.__class__.__name__}"}
    output = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if proc.returncode != 0:
        lowered = output.lower()
        if any(marker in lowered for marker in (
                "no mcp server", "not found", "no server", "does not exist",
                "unknown server")):
            return {"state": "missing", "output": output[:400]}
        return {"state": "error",
                "reason": "claude mcp get failed; this is not proof the server is absent",
                "returncode": proc.returncode, "output": output[:400]}
    record = parse_claude_mcp_get(output)
    if record is None:
        return {"state": "error",
                "reason": "claude mcp get returned an unparsable configuration",
                "output": output[:400]}
    return {"state": "present", "record": record, "output": output[:400]}


def _registration_matches(record, python, skill):
    expected = manual_claude_command(python, skill)
    if not isinstance(record, dict) or not record.get("command"):
        return False
    scope = record.get("scope", "")
    if scope and "user" not in scope:
        return False
    transport = record.get("transport", "")
    if transport and "stdio" not in transport:
        return False
    command = _normalise_command(record["command"])
    args = [str(item) for item in record.get("args") or []]
    actual = command + args
    return actual == expected[9:]


def register_claude(cli=None, python=None, skill=None, env=None):
    """Idempotent user-scoped stdio registration with staged rollback.

    Never overwrites an existing conflicting server and never removes a server
    that this invocation did not create.
    """
    python = python or sys.executable
    skill = Path(skill or SKILL)
    cli = cli or shutil.which("claude")
    manual = manual_claude_command(python, skill)
    if not cli:
        raise RuntimeError(
            "Claude CLI not found; install it or register manually with: "
            + " ".join(shlex.quote(item) for item in manual))
    before = inspect_claude_registration(cli, env=env)
    if before["state"] == "error":
        raise RuntimeError(
            "Cannot inspect existing Claude MCP registration without guessing: "
            + before.get("reason", "unknown error") + ". Manual command: "
            + " ".join(shlex.quote(item) for item in manual))
    if before["state"] == "present":
        if _registration_matches(before["record"], python, skill):
            return {"ok": True, "changed": False, "state": "already_registered",
                    "record": before["record"], "manual": manual,
                    "snippets": manual_claude_snippets(python, skill)}
        raise RuntimeError(
            "A conflicting Claude MCP server is already registered; refusing to "
            "overwrite it. Inspect with `claude mcp get abdullah-orchestrator`. "
            "Existing record: " + json.dumps(before["record"], sort_keys=True))
    try:
        added = subprocess.run([cli] + list(manual[1:]), capture_output=True, text=True,
                               timeout=60, check=False, env=env)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(
            f"Claude MCP registration failed before completion: {exc.__class__.__name__}. "
            "Manual command: " + " ".join(shlex.quote(item) for item in manual))
    if added.returncode != 0:
        raise RuntimeError(
            "Claude MCP registration failed: "
            + ((added.stderr or added.stdout or "").strip()[:600] or "no output")
            + ". Manual command: " + " ".join(shlex.quote(item) for item in manual))
    after = inspect_claude_registration(cli, env=env)
    if after["state"] != "present" or not _registration_matches(after["record"], python, skill):
        rollback = subprocess.run(
            [cli, "mcp", "remove", "--scope", "user", MCP_SERVER_NAME],
            capture_output=True, text=True, timeout=30, check=False, env=env)
        raise RuntimeError(
            "Claude MCP registration could not be verified; rollback of the "
            "artifact created by this invocation was attempted "
            f"(returncode={rollback.returncode}). Inspect with `/mcp`. "
            "Manual command: " + " ".join(shlex.quote(item) for item in manual))
    return {"ok": True, "changed": True, "state": "registered",
            "record": after["record"], "manual": manual,
            "snippets": manual_claude_snippets(python, skill)}


def install(argv=None):
    parser = argparse.ArgumentParser(description="Install Abdullah Orchestrator on WSL")
    parser.add_argument("--no-claude", action="store_true", help="Skip the Claude Code discovery link")
    parser.add_argument("--register-codex", action="store_true",
                        help="Register the stdio MCP supervisor in the local Codex config")
    parser.add_argument("--register-claude", action="store_true",
                        help="Register user-scoped stdio MCP in Claude Code via the official CLI")
    opts = parser.parse_args(argv)
    if sys.platform != "linux":
        print("Warning: designed for WSL/Linux, current platform is", sys.platform, file=sys.stderr)
    targets = [Path.home() / ".agents/skills/abdullah-orchestrator"]
    if not opts.no_claude:
        targets.append(Path.home() / ".claude/skills/abdullah-orchestrator")
    for link in targets:
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.is_symlink():
            if link.resolve() != SKILL:
                raise RuntimeError(f"Will not replace existing skill symlink: {link}")
            print("Already linked:", link)
            continue
        if link.exists():
            if link.resolve() != SKILL:
                raise RuntimeError(f"Will not overwrite existing skill: {link}")
            print("Already installed:", link)
            continue
        link.symlink_to(SKILL, target_is_directory=True)
        print("Installed:", link, "->", SKILL)
    cfg = Path.home() / ".config/abdullah-orchestrator/config.json"
    if not cfg.exists():
        cfg.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SKILL / "scripts/config.example.json", cfg)
        os.chmod(cfg, 0o600)
        print("Created editable model config:", cfg)
    else:
        print("Preserved existing model config:", cfg)
    if opts.register_codex:
        codex = shutil.which("codex")
        if not codex:
            print("Codex CLI not found; register manually with:", file=sys.stderr)
        else:
            existing = subprocess.run([codex, "mcp", "get", MCP_SERVER_NAME],
                                      capture_output=True, text=True, check=False)
            if existing.returncode == 0:
                print("Codex MCP server already registered:", MCP_SERVER_NAME)
            else:
                added = subprocess.run(
                    [codex, "mcp", "add", MCP_SERVER_NAME, "--",
                     sys.executable, str(SKILL / "scripts/orchestrator.py"), "mcp"],
                    capture_output=True, text=True, check=False)
                if added.returncode != 0:
                    raise RuntimeError("Codex MCP registration failed: " +
                                       (added.stderr or added.stdout).strip())
                print("Registered Codex MCP server:", MCP_SERVER_NAME)
    if opts.register_claude:
        result = register_claude()
        print(("Registered" if result["changed"] else "Already registered") +
              " Claude MCP server:", MCP_SERVER_NAME)
        print("Manual command:", result["snippets"]["manual_command"])
        print("Interactive host environment:", result["snippets"]["shell"])
        print("Foreground host settings snippet (destination "
              + result["snippets"]["settings"]["destination"] + "):")
        print(json.dumps(result["snippets"]["settings"]["content"], indent=2))
        print("User MCP server snippet (destination "
              + result["snippets"]["mcp_server"]["destination"] + "):")
        print(json.dumps(result["snippets"]["mcp_server"]["content"], indent=2))
        print("Manual step that installs the timeout:")
        print("  " + result["snippets"]["timeout_command"])
        for item in result["snippets"]["merge_steps"]:
            print("Merge:", item)
        for item in result["snippets"]["verify"]:
            print("Verify:", item)
    print("MCP registration command:")
    print("  codex mcp add", MCP_SERVER_NAME, "--", sys.executable,
          SKILL / "scripts/orchestrator.py", "mcp")
    print("Claude manual registration command:")
    print("  " + " ".join(shlex.quote(item) for item in manual_claude_command()))
    print("Next: check Go model and CLI with python3", SKILL / "scripts/orchestrator.py",
          "doctor --project /absolute/path/to/development/repo")
    print("Open Codex with Luna medium, invoke $abdullah-orchestrator, and give it a goal.")


if __name__ == "__main__":
    try:
        install()
    except (RuntimeError, OSError) as error:
        sys.exit(str(error))
