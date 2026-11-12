# Maintained source and distribution

This Git repository is the canonical source. A common machine-local layout keeps
the working source at `~/.local/src/abdullah-orchestrator` and the active
installation at `~/.local/share/abdullah-orchestrator`; keep both copies in sync
when making changes. A fresh clone can also be installed in place, because
`scripts/install_wsl.py` links whichever directory contains it. Back up both
copies before an update if that layout is in use:

The checkout registry is `<state-root>-checkouts` (or `ABDULLAH_CHECKOUT_REGISTRY`).
Back it up with the runs; never delete it while any run is active.

```bash
mkdir -p ~/.local/state/abdullah-orchestrator/backups/<stamp>
tar -czf ~/.local/state/abdullah-orchestrator/backups/<stamp>/source.tar.gz -C ~/.local/src abdullah-orchestrator
tar -czf ~/.local/state/abdullah-orchestrator/backups/<stamp>/installed.tar.gz -C ~/.local/share abdullah-orchestrator
```

Run the full suite from the source directory before distributing:

```bash
python3 -m unittest discover -s scripts/tests
```

Then copy the files into the installed directory (never overwrite the separate
run-state or configuration directories) and rerun the same suite there.

The installer links the directory containing `scripts/install_wsl.py`; it does
not upgrade an existing installation or replace an unrelated skill symlink.

## Interactive MCP registration

Register the stdio supervisor once per Codex profile:

```bash
codex mcp add abdullah-orchestrator -- python3 ~/.local/share/abdullah-orchestrator/scripts/orchestrator.py mcp
```

`python3 scripts/install_wsl.py --register-codex` performs the same step when
explicitly requested. Restart Codex after registration. `codex mcp list` should
show the server; use `codex mcp remove abdullah-orchestrator` to unregister it.

Set the per-server tool timeout in `~/.codex/config.toml`; do not set it
globally for every MCP server:

```toml
[mcp_servers.abdullah-orchestrator]
command = "python3"
args = ["<SKILL_DIR>/scripts/orchestrator.py", "mcp"]
tool_timeout_sec = 18000
```

`tool_timeout_sec` is Codex's maximum wait for one foreground `tools/call`. The
previously observed 300-second default is too short for a legitimate Architect,
Implementer or Reviewer stage. 18,000 seconds (five hours) deliberately exceeds
the supervisor's four-hour `max_worker_seconds`, `max_architect_seconds` and
`max_check_seconds` caps, so the client cannot race the supervisor at the
four-hour boundary. This is a communication upper bound, not a stuck-worker
detector: those `limits` bound execution, while the guard, process-session
liveness checks, interruption and reconciliation handle exits, hangs and
uncertain ownership.

For unusual workloads, keep `tool_timeout_sec` strictly above the largest
configured stage cap. Raise the corresponding `limits` values first, then the
MCP timeout, and keep all values finite. Restart Codex after every change; a
running session keeps its old client configuration.

## Run-state safety

Do not reset, clean, reconcile, resume, or launch workers for an existing run
unless the user explicitly authorizes recovery of that run. Preserve its
reports, checkpoints, journal and checkout. Development and verification should
use isolated disposable repositories and synthetic runs.

## Rollback

Restore both copies from the pre-change archive (replace `<stamp>` with the
backup you want):

```bash
rm -rf ~/.local/src/abdullah-orchestrator ~/.local/share/abdullah-orchestrator
tar -xzf ~/.local/state/abdullah-orchestrator/backups/<stamp>/source.tar.gz -C ~/.local/src
tar -xzf ~/.local/state/abdullah-orchestrator/backups/<stamp>/installed.tar.gz -C ~/.local/share
```

Run the restored suite, then re-run `scripts/install_wsl.py` if the skill link
target moved. Run state and `~/.config/abdullah-orchestrator/config.json` are
separate and are not part of these archives; never delete them during rollback.
