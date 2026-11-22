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
[mcp_servers.abdullah-live-progress-smoke]
command = "/usr/bin/python3"
args = ["<CHECKOUT>/scripts/orchestrator.py", "mcp"]
startup_timeout_sec = 30
tool_timeout_sec = 18000

[mcp_servers.abdullah-live-progress-smoke.env]
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
6. While the worker is still active, press Ctrl-C to close the observer; confirm
   the stage keeps running. Reattach with the same `status --follow` command
   before completion and confirm the live view resumes and reaches the measured
   outcome. Observation and stopping must be independent.

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

## Windows Codex desktop result

The operator ran one Implementer stage from Windows Codex desktop with its
agent in Ubuntu WSL. The registered Windows package was `26.1111.2228.0`.
The supervisor checkout was `435012e`, with the same runtime and tests as
`d724f28`. The integrated terminal opened the observer through the Windows
`wsl.exe` launcher because the fixture's `/tmp` path gave a file-not-found
error when invoked directly.

- Run `20261122T150221-f56c5bfd`, attempt `8b06414f5fa841e1`.
- The viewer showed the next Implementer, task and expected report before
  dispatch. During the stage, the operator saw `elapsed 0.8s`, `elapsed 2.3s`,
  `elapsed 17.3s` and `elapsed 32.4s`, including `worker running` and `worker
  step finished`. The final block reported `complete`, `measured 32.9s` and
  the supervisor verification task and expected output.
- An independent read of the run journal confirmed one matching Implementer
  start/end pair with a measured 32.92 s. The run reached `verify` with the
  fixture edit in `app.py` and no active worker or verification check.
  Journal SHA-256 `7565a0faf960400934ed1e5f927558edcb9f5c8ab63ed85dd213c95bf35a0364`.

This checks the terminal fallback in the actual Codex desktop. Native
tool-card progress, desktop Stop and viewer reattachment during this stage
remain unverified. The documented programmatic interruption and observer
tests cover their respective supervisor paths. Claude desktop remains open.

## Verification

The accepted follow-up revision
`720dd7c2e4c0b404cccc430e14f40c1f1385dd04` ran **1,183 tests, OK, 10 skipped** in
1,715.570 s on Python 3.10.12. The 10 skips are the opt-in OpenCode V2
introspection module. A documentation commit after it does not change
`scripts/`. This follow-up result is separate from the original v1.2.0 result of
1,069 tests at `16a0816` (recorded at `9a150de`), which remains unchanged.

Verified client behavior: Claude Code CLI `2.1.247` rendered native MCP progress
in its TUI; Codex CLI `0.169.1` received the notifications but showed only tool
start/completion, so the adjacent observer was used; the Windows Codex desktop
WSL agent showed the observer in the integrated terminal. Unverified: Codex CLI
in-chat progress, Codex desktop tool-card progress, in-app Stop and fresh-thread
recovery, Claude desktop in-chat progress and observer, and authenticated long
Claude stages.
