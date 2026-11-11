#!/usr/bin/env python3
"""Install the single Orchestrator skill without changing old Abdullah skills."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

SKILL = Path(__file__).resolve().parent.parent


def install():
    parser = argparse.ArgumentParser(description="Install Abdullah Orchestrator on WSL")
    parser.add_argument("--no-claude", action="store_true", help="Skip the Claude Code discovery link")
    parser.add_argument("--register-codex", action="store_true",
                        help="Register the stdio MCP supervisor in the local Codex config")
    opts = parser.parse_args()
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
            existing = subprocess.run([codex, "mcp", "get", "abdullah-orchestrator"],
                                      capture_output=True, text=True, check=False)
            if existing.returncode == 0:
                print("Codex MCP server already registered: abdullah-orchestrator")
            else:
                added = subprocess.run(
                    [codex, "mcp", "add", "abdullah-orchestrator", "--",
                     sys.executable, str(SKILL / "scripts/orchestrator.py"), "mcp"],
                    capture_output=True, text=True, check=False)
                if added.returncode != 0:
                    raise RuntimeError("Codex MCP registration failed: " +
                                       (added.stderr or added.stdout).strip())
                print("Registered Codex MCP server: abdullah-orchestrator")
    print("MCP registration command:")
    print("  codex mcp add abdullah-orchestrator --", sys.executable,
          SKILL / "scripts/orchestrator.py", "mcp")
    print("Next: check Go model and CLI with python3", SKILL / "scripts/orchestrator.py",
          "doctor --project /absolute/path/to/development/repo")
    print("Open Codex with Luna medium, invoke $abdullah-orchestrator, and give it a goal.")


if __name__ == "__main__":
    try:
        install()
    except (RuntimeError, OSError) as error:
        sys.exit(str(error))
