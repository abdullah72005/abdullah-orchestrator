# Live progress evidence and desktop fixture

This directory holds the operator fixture for the post-v1.2.0 live-progress
acceptance check. It creates an isolated disposable project and run that has
already completed its plan; the next `orchestrator_stage` call runs the
Implementer with a delayed fixture worker, so a desktop client has a stable
window to display progress. No paid model is called by the fixture.

## Prepare

From this checkout (WSL):

```bash
python3 docs/release-evidence/live-progress/desktop_fixture.py /tmp/opencode/desktop-live-progress
```

The command prints JSON with `run_id`, an `env.sh` path and the MCP registration
that the desktop client must use (the same command, args and environment). The
run is left at phase `implement`.

## Register the MCP server in the desktop client

Use the printed registration in the Windows-side Codex configuration when the
desktop agent runs in WSL, including every printed environment entry, for
example:

```toml
[mcp_servers.abdullah-orchestrator]
command = "/usr/bin/python3"
args = ["<CHECKOUT>/scripts/orchestrator.py", "mcp"]
startup_timeout_sec = 30
tool_timeout_sec = 18000

[mcp_servers.abdullah-orchestrator.env]
ABDULLAH_STATE_DIR = "/tmp/opencode/desktop-live-progress/runs"
ABDULLAH_CONFIG = "/tmp/opencode/desktop-live-progress/config.json"
HOME = "/tmp/opencode/desktop-live-progress/home"
PATH = "/tmp/opencode/desktop-live-progress/bin:<existing PATH>"
FAKE_HISTORY = "/tmp/opencode/desktop-live-progress/history"
FAKE_SLEEP = "10"
```

## Observe (Codex desktop, WSL agent)

1. Open the desktop app's integrated WSL terminal in the fixture project.
2. Run `source /tmp/opencode/desktop-live-progress/env.sh`.
3. Run `python3 <CHECKOUT>/scripts/orchestrator.py status --run "$RUN_ID" --follow`.
   The view must first show the next stage's role, route, task and expected
   output.
4. In the desktop chat, call `orchestrator_stage` with the printed `RUN_ID`.
5. Pass criteria: elapsed seconds tick while the worker is silent, activity
   changes (worker launched → running/check running → report received), and the
   final block shows the outcome, measured elapsed time and next action. The
   Codex desktop chat itself is not expected to render MCP progress
   notifications; the integrated terminal is the supported view.
6. Press Ctrl-C in the viewer. The stage must keep running and complete normally.

## Observe (Claude desktop)

Claude desktop has no assumed integrated WSL terminal. Open any adjacent
terminal, repeat steps 2–3 and confirm the same criteria while starting the
stage from the Claude desktop chat. Record a screenshot of the observer and the
client's own stage display.

## Recording the result

Record the client name and version, the WSL distribution, the checkout revision
(`git rev-parse HEAD`), the run ID, whether native progress was displayed, and
the observed observer lines. Do not mark a surface verified from a headless tool
response alone.

Deterministic checks for the same behaviours live in
`scripts/tests/test_live_stage_progress.py`.
