#!/usr/bin/env python3
"""Install the single Orchestrator skill without changing old Abdullah skills."""
from __future__ import annotations
import argparse
import copy
import datetime
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

SKILL = Path(__file__).resolve().parent.parent
MCP_SERVER_NAME = "abdullah-orchestrator"
FOREGROUND_ENV = {"CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS": "0"}
RECOMMENDED_SERVER_TIMEOUT_MS = 18_000_000  # 5 hours; >=1000 also raises the idle floor
# A host communication bound must finish strictly after the supervisor's whole
# stage budget.  The margin covers transport startup and the final report write;
# it is not a stuck-worker detector.
SERVER_TIMEOUT_MARGIN_MS = 60_000
MAX_SERVER_TIMEOUT_MS = 86_400_000  # finite: never ask a host to wait a day+
ANTIGRAVITY_SETTINGS_ENV = "ANTIGRAVITY_SETTINGS"
# Candidates are detection hints only.  The installer writes an Antigravity
# settings file only when the path is explicit or an existing candidate is
# found, because the installed `agy` schema has not been verified here.
ANTIGRAVITY_CANDIDATE_SETTINGS = (
    Path.home() / ".gemini/settings.json",
    Path.home() / ".antigravity/settings.json",
)


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


def effective_config_path(config_path=None):
    return Path(config_path or os.environ.get("ABDULLAH_CONFIG")
                or Path.home() / ".config/abdullah-orchestrator/config.json")


def configured_max_stage_seconds(config_path=None):
    """Largest whole-stage budget, from the user's config when it is readable.

    A missing or malformed config falls back to the shipped example so the
    timeout check still happens; the source is returned so the operator can see
    which value was used instead of guessing silently.
    """
    for candidate in (effective_config_path(config_path),
                      SKILL / "scripts/config.example.json"):
        try:
            value = json.loads(Path(candidate).read_text(encoding="utf-8"))
            seconds = value["limits"]["max_stage_seconds"]
            if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
                continue
            if 0 < float(seconds) < MAX_SERVER_TIMEOUT_MS / 1000.0:
                return {"seconds": float(seconds), "source": str(candidate)}
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return {"seconds": 17_000.0, "source": "built-in fallback"}


def server_timeout_bound(*, max_stage_seconds=None, requested_ms=None,
                         config_path=None):
    """Validate a finite host timeout against the whole-stage budget.

    Insufficient, non-numeric, non-finite or absurdly large bounds are refused
    with an actionable minimum; nothing is silently clamped.
    """
    if max_stage_seconds is None:
        observed = configured_max_stage_seconds(config_path)
        max_stage_seconds, source = observed["seconds"], observed["source"]
    else:
        source = "caller"
    required_ms = int(float(max_stage_seconds) * 1000) + SERVER_TIMEOUT_MARGIN_MS
    value = RECOMMENDED_SERVER_TIMEOUT_MS if requested_ms is None else requested_ms
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(float(value)):
        raise ValueError(
            "server timeout must be a finite number of milliseconds, got "
            f"{value!r}")
    if value != int(value) or value <= 0 or value > MAX_SERVER_TIMEOUT_MS:
        raise ValueError(
            "server timeout must be a positive whole number of milliseconds "
            f"no larger than {MAX_SERVER_TIMEOUT_MS}, got {value!r}")
    value = int(value)
    if value < required_ms:
        raise ValueError(
            f"server timeout {value} ms is insufficient: max_stage_seconds="
            f"{max_stage_seconds:g} ({source}) requires at least {required_ms} "
            f"ms so the host cannot time out before the supervisor's last "
            f"stage child. Use a larger finite bound (--timeout-ms).")
    return {"requested_ms": value, "required_ms": required_ms,
            "max_stage_seconds": float(max_stage_seconds),
            "margin_ms": SERVER_TIMEOUT_MARGIN_MS, "source": source,
            "accepted": True}


def supervisor_mcp_entry(python=None, skill=None, timeout_ms=None,
                         config_path=None):
    """The stdio MCP server entry the hosts register, with a validated bound."""
    python = str(Path(python or sys.executable).resolve())
    supervisor = str((Path(skill or SKILL) / "scripts/orchestrator.py").resolve())
    bound = server_timeout_bound(requested_ms=timeout_ms, config_path=config_path)
    return {"command": python, "args": [supervisor, "mcp"],
            "timeout": bound["requested_ms"], "timeout_bound": bound}


def antigravity_settings_candidates():
    configured = os.environ.get(ANTIGRAVITY_SETTINGS_ENV)
    if configured and configured.strip():
        return [Path(configured).expanduser()]
    return [Path(item) for item in ANTIGRAVITY_CANDIDATE_SETTINGS]


def antigravity_manual_snippets(python=None, skill=None, timeout_ms=None,
                                config_path=None):
    entry = supervisor_mcp_entry(python, skill, timeout_ms, config_path)
    candidates = [str(item) for item in antigravity_settings_candidates()]
    return {
        "server_name": MCP_SERVER_NAME,
        "server_entry": {"command": entry["command"], "args": entry["args"],
                         "timeout": entry["timeout"]},
        "timeout_bound": entry["timeout_bound"],
        "settings_candidates": candidates,
        "manual_steps": [
            f"Confirm `agy --help` advertises a stdio MCP registration command; "
            f"this installer does not invent one. Register {MCP_SERVER_NAME} "
            f"with command {entry['command']} and args {entry['args']}.",
            f"Ensure the server-scoped timeout is {entry['timeout']} ms "
            f"(>= {entry['timeout_bound']['required_ms']} ms); do not apply it "
            "globally and do not lower it below the whole-stage budget.",
            "Keep unrelated MCP servers and settings untouched.",
        ],
        "manual_limit": (
            "The installed Antigravity CLI/desktop schema and version were not "
            "available in this environment, so only conflict-safe merging into "
            "an existing mcpServers file is implemented. A missing file or a "
            "different schema is reported, never guessed."),
    }


def inspect_antigravity_settings(path):
    """Classify one candidate settings file without creating or guessing it."""
    path = Path(path)
    if not path.exists():
        return {"state": "missing_file", "path": str(path)}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"state": "invalid", "path": str(path),
                "reason": exc.__class__.__name__}
    if not isinstance(value, dict):
        return {"state": "invalid", "path": str(path),
                "reason": "settings root is not a JSON object"}
    servers = value.get("mcpServers", {})
    if not isinstance(servers, dict):
        return {"state": "unsupported", "path": str(path),
                "reason": "mcpServers is not an object"}
    return {"state": "usable", "path": str(path), "value": value,
            "record": servers.get(MCP_SERVER_NAME)}


def _entry_matches(record, entry):
    if not isinstance(record, dict):
        return False
    command = record.get("command")
    args = record.get("args") or []
    try:
        same_command = Path(str(command)).resolve() == Path(entry["command"])
    except (OSError, ValueError):
        same_command = str(command) == entry["command"]
    return (same_command and isinstance(args, list)
            and [str(item) for item in args] == entry["args"])


def _atomic_write_json(path, value, backup_dir=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if path.exists():
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y%m%dT%H%M%S%fZ")
        directory = Path(backup_dir) if backup_dir else path.parent
        directory.mkdir(parents=True, exist_ok=True)
        backup = directory / f"{path.name}.{stamp}.bak"
        backup.write_bytes(path.read_bytes())
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                     dir=path.parent, prefix=".mcp-",
                                     delete=False) as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
        temporary = Path(stream.name)
    os.replace(temporary, path)
    try:
        descriptor = os.open(path.parent, os.O_RDONLY)
    except OSError:
        descriptor = None
    if descriptor is not None:
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    return backup


def register_antigravity(settings_path, python=None, skill=None,
                         timeout_ms=None, config_path=None, write=None):
    """Idempotently merge the supervisor into an Antigravity settings file.

    The path is mandatory: an absent file, invalid JSON or a different schema is
    reported instead of creating a guessed location.  Unrelated servers and
    keys are preserved, conflicts are refused without modification, and an
    existing file is backed up before an actual rewrite.
    """
    entry = supervisor_mcp_entry(python, skill, timeout_ms, config_path)
    state = inspect_antigravity_settings(settings_path)
    if state["state"] == "missing_file":
        raise RuntimeError(
            f"No Antigravity settings file at {state['path']}. Create or select "
            "it with --antigravity-settings, or register manually: "
            + " / ".join(antigravity_manual_snippets(
                python, skill, timeout_ms, config_path)["manual_steps"][:1]))
    if state["state"] == "invalid":
        raise RuntimeError(
            f"Refusing to rewrite unparsable Antigravity settings at "
            f"{state['path']} ({state['reason']}); fix it or choose another "
            "path.")
    if state["state"] == "unsupported":
        raise RuntimeError(
            f"Refusing to guess the Antigravity schema at {state['path']}: "
            f"{state['reason']}. Register manually with the printed entry.")
    existing = state["record"]
    value = copy.deepcopy(state["value"])
    servers = value.setdefault("mcpServers", {})
    if existing is not None and not _entry_matches(existing, entry):
        raise RuntimeError(
            "A conflicting MCP server is already registered as "
            f"{MCP_SERVER_NAME}; refusing to overwrite it. Existing entry: "
            + json.dumps(existing, sort_keys=True))
    unchanged = (_entry_matches(existing, entry)
                 and existing.get("timeout") == entry["timeout"])
    if unchanged:
        return {"ok": True, "changed": False, "state": "already_registered",
                "path": state["path"], "entry": existing, "backup": None,
                "timeout_bound": entry["timeout_bound"]}
    servers[MCP_SERVER_NAME] = {"command": entry["command"],
                                "args": entry["args"],
                                "timeout": entry["timeout"]}
    if write is False:
        return {"ok": True, "changed": True, "state": "preview",
                "path": state["path"], "entry": value["mcpServers"][MCP_SERVER_NAME],
                "backup": None, "timeout_bound": entry["timeout_bound"]}
    backup = _atomic_write_json(settings_path, value)
    return {"ok": True, "changed": True, "state": "registered",
            "path": state["path"],
            "entry": value["mcpServers"][MCP_SERVER_NAME],
            "backup": str(backup) if backup else None,
            "timeout_bound": entry["timeout_bound"]}


def desktop_setup(python=None, skill=None, config_path=None, distro=None,
                  state_dir=None):
    """WSL identity and the Windows-side launch bridge for the desktop app.

    Everything here is observed on this Linux side.  A Windows desktop chat is
    only a coordinator; running the CLI in its integrated terminal is not GUI
    integration.
    """
    python = str(Path(python or sys.executable).resolve())
    skill = Path(skill or SKILL).resolve()
    supervisor = str((skill / "scripts/orchestrator.py").resolve())
    distro = distro or os.environ.get("WSL_DISTRO_NAME") or None
    opencode = shutil.which("opencode")
    agy = shutil.which("agy")
    config_file = str(Path(effective_config_path(config_path)).expanduser().resolve())
    state_root = str(Path(state_dir or os.environ.get(
        "ABDULLAH_STATE_DIR",
        Path.home() / ".local/state/abdullah-orchestrator/runs")).expanduser().resolve())
    entry = supervisor_mcp_entry(python, skill, config_path=config_path)
    linux_entry = {"command": python, "args": [supervisor, "mcp"],
                   "timeout": entry["timeout"]}
    path_entries = []
    for executable in (opencode, agy):
        if executable:
            path_entries.append(str(Path(executable).resolve().parent))
    path_entries += ["/usr/local/bin", "/usr/bin", "/bin"]
    launch_env = {"PATH": ":".join(dict.fromkeys(path_entries)),
                  "ABDULLAH_CONFIG": config_file,
                  "ABDULLAH_STATE_DIR": state_root}
    windows_args = []
    if distro:
        windows_args += ["-d", distro]
    windows_args += ["--cd", str(skill), "--exec", "/usr/bin/env"]
    windows_args += [f"{key}={value}" for key, value in launch_env.items()]
    windows_args += [python, supervisor, "mcp"]
    blockers = []
    if not distro:
        blockers.append(
            "WSL_DISTRO_NAME is unset; select the Ubuntu distro explicitly and "
            "do not assume the default distribution.")
    if not agy:
        blockers.append(
            "agy is not on PATH in this shell; Antigravity Architect dispatch "
            "and CLI live validation stay blocked until the installed CLI is "
            "verified.")
    if not opencode:
        blockers.append(
            "opencode is not on PATH; worker routes cannot dispatch until the "
            "installed CLI is available.")
    return {
        "ok": not blockers,
        "distro": distro,
        "python": python,
        "checkout": str(skill),
        "supervisor": supervisor,
        "config": str(effective_config_path(config_path)),
        "state": str(Path(state_dir or os.environ.get(
            "ABDULLAH_STATE_DIR",
            Path.home() / ".local/state/abdullah-orchestrator/runs"))),
        "opencode": opencode,
        "agy": agy,
        "linux_entry": linux_entry,
        "windows_launch": {"command": "C:/Windows/System32/wsl.exe",
                           "args": windows_args,
                           "env": launch_env,
                           "timeout": entry["timeout"]},
        "timeout_bound": entry["timeout_bound"],
        "blockers": blockers,
        "notes": [
            "Register the server in the desktop application's own MCP settings, "
            "not only in a terminal.",
            "The desktop conversation model is managed by the desktop app; the "
            "dispatched Architect route comes from the supervisor config.",
            "Integrated-terminal CLI execution does not satisfy desktop "
            "integration.",
        ],
    }


def install(argv=None):
    parser = argparse.ArgumentParser(description="Install Abdullah Orchestrator on WSL")
    parser.add_argument("--no-claude", action="store_true", help="Skip the Claude Code discovery link")
    parser.add_argument("--register-codex", action="store_true",
                        help="Register the stdio MCP supervisor in the local Codex config")
    parser.add_argument("--register-claude", action="store_true",
                        help="Register user-scoped stdio MCP in Claude Code via the official CLI")
    parser.add_argument("--register-antigravity", action="store_true",
                        help="Merge the stdio MCP server into an existing Antigravity settings file")
    parser.add_argument("--antigravity-settings", metavar="PATH",
                        help="Antigravity CLI settings JSON to inspect/merge; never guessed")
    parser.add_argument("--setup-desktop", action="store_true",
                        help="Print the verified WSL identity and Windows desktop launch bridge")
    parser.add_argument("--timeout-ms", type=int, default=None,
                        help="Server-scoped timeout in milliseconds (must exceed the whole-stage budget)")
    opts = parser.parse_args(argv)
    # Reject a host bound that cannot outlast the configured stage budget before
    # any registration snippet is printed.
    server_timeout_bound(requested_ms=opts.timeout_ms)
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
    if opts.setup_desktop:
        print("Windows Antigravity desktop -> WSL supervisor setup:")
        print(json.dumps(desktop_setup(), indent=2, ensure_ascii=False))
    if opts.register_antigravity:
        settings = opts.antigravity_settings
        if not settings:
            existing = [item for item in antigravity_settings_candidates()
                        if item.exists()]
            settings = str(existing[0]) if existing else None
        if not settings:
            snippets = antigravity_manual_snippets(timeout_ms=opts.timeout_ms)
            print("No Antigravity settings file was found; not guessing one.")
            print(json.dumps(snippets, indent=2, ensure_ascii=False))
            raise RuntimeError(
                "Pass --antigravity-settings PATH for the installed CLI's "
                "settings file, then re-run.")
        merged = register_antigravity(settings, timeout_ms=opts.timeout_ms)
        print(("Registered" if merged["changed"] else "Already registered") +
              " Antigravity MCP server:", MCP_SERVER_NAME)
        print("Settings:", merged["path"])
        print("Server entry:", json.dumps(merged["entry"], sort_keys=True))
        if merged.get("backup"):
            print("Backup:", merged["backup"])
        print("Verify that the installed `agy` version reads this file and "
              "advertises the expected stdio MCP schema; that live check is "
              "not performed by this installer.")
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
    except (RuntimeError, OSError, ValueError) as error:
        sys.exit(str(error))
