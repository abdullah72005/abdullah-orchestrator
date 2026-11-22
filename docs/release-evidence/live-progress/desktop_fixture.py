#!/usr/bin/env python3
"""Prepare a disposable run for the desktop live-progress acceptance check.

Creates an isolated fake-CLI project, a valid run that has completed its plan,
and an ``env.sh`` that points the supervisor MCP server and the terminal
observer at the same state. No paid model is called by this fixture; the
Implementer stage uses a delayed fixture worker so the observer has a stable
window.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile

HERE = Path(__file__).resolve()
CHECKOUT = HERE.parents[3]
sys.path.insert(0, str(CHECKOUT / "scripts/tests"))
sys.path.insert(0, str(CHECKOUT / "scripts"))

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
    tempfile.mkdtemp(prefix="abdullah-desktop-probe-", dir="/tmp/opencode"))
root.mkdir(parents=True, exist_ok=True)
(root / "home/.local/state").mkdir(parents=True, exist_ok=True)

os.environ.update({
    "ABDULLAH_STATE_DIR": str(root / "runs"),
    "ABDULLAH_CONFIG": str(root / "config.json"),
    "HOME": str(root / "home"),
    "XDG_CONFIG_HOME": "",
    "XDG_DATA_HOME": "",
    "OPENAI_API_KEY": "",
})
os.environ.pop("ABDULLAH_CHECKOUT_REGISTRY", None)

import orchestrator as orc  # noqa: E402
import test_orchestrator as fixtures  # noqa: E402
import test_interactive_recovery as recovery  # noqa: E402

project = fixtures.setup_repo(root)
fakebin = recovery._install_fake_clis(root)
os.environ["PATH"] = str(fakebin) + ":" + os.environ["PATH"]
os.environ["FAKE_HISTORY"] = str(root / "history")

config = orc.read_json(orc.HERE / "config.example.json")
config.setdefault("authorization", {})["sensitive_cli_enabled"] = True
config["verification"]["command_policy"]["exceptions"] = [{
    "argv_regex": r'.*python[0-9.]*","-c".*',
    "reason": "desktop probe containment/provenance",
    "scope": "*", "authorized_by": "probe-operator"}]
orc.atomic_json(root / "config.json", config)

started = orc.start_run(project=str(project),
                        goal="Observe live worker progress in the desktop client",
                        host="codex", skip_doctor=True, interactive=True)
plan = orc.stage_run(started["run_id"])

shared = {
    "ABDULLAH_STATE_DIR": str(root / "runs"),
    "ABDULLAH_CONFIG": str(root / "config.json"),
    "HOME": str(root / "home"),
    "PATH": str(fakebin) + ":" + os.environ["PATH"],
    "FAKE_HISTORY": str(root / "history"),
    "FAKE_SLEEP": "10",
}
env_file = root / "env.sh"
env_file.write_text("".join(
    "export %s=%s\n" % (key, json.dumps(value)) for key, value in shared.items())
    + 'export RUN_ID=%s\nexport PROJECT=%s\n' % (
        json.dumps(started["run_id"]), json.dumps(str(project))))
commands = root / "commands.txt"
commands.write_text(
    "source %s\n"
    "python3 %s status --run \"$RUN_ID\" --follow\n" % (
        env_file, CHECKOUT / "scripts/orchestrator.py"))
print(json.dumps({
    "root": str(root), "project": str(project), "run_id": started["run_id"],
    "phase_after_fixture_plan": plan["phase"],
    "env_file": str(env_file), "commands_file": str(commands),
    "mcp_registration": {
        "command": sys.executable,
        "args": [str(CHECKOUT / "scripts/orchestrator.py"), "mcp"],
        "env": shared,
    },
    "operator_steps": [
        "In the desktop WSL terminal: source %s" % env_file,
        "Run: python3 %s status --run \"$RUN_ID\" --follow" % (
            CHECKOUT / "scripts/orchestrator.py"),
        "In the desktop chat, call orchestrator_stage with run_id \"%s\"" % (
            started["run_id"]),
        "Confirm ticking elapsed/activity, then outcome, measured time and next action",
        "Quit the viewer with Ctrl-C and confirm the stage continues",
    ],
}, indent=2))
