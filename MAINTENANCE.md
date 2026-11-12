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

## OpenCode V1 to V2 upgrade handoff

The supervisor supports the tested OpenCode lines `>=1.18 <2.0` and
`>=2.2 <3.0`. It refuses unknown majors rather than claiming forward
compatibility. On 2026-11-12 the verified latest stable V2 release was
**v2.2.7**. The GitHub `releases/latest` endpoint still reported `v1.19.5`, so
`opencode upgrade` without a target will not reach V2. Always pass the target.

Observed installation on this machine: the curl installer, executable
`~/.opencode/bin/opencode`, detected version `1.18.35`.

Before upgrading, back up configuration, credentials and session state. V2
keeps the same locations:

```bash
stamp=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p ~/.local/state/abdullah-orchestrator/backups/$stamp
tar -czf ~/.local/state/abdullah-orchestrator/backups/$stamp/opencode-config.tar.gz \
  -C "$HOME" .config/opencode
tar -czf ~/.local/state/abdullah-orchestrator/backups/$stamp/opencode-data.tar.gz \
  -C "$HOME" .local/share/opencode
tar -czf ~/.local/state/abdullah-orchestrator/backups/$stamp/opencode-state.tar.gz \
  -C "$HOME" .local/state/opencode
```

Do not delete sessions, authentication or history. V2's terminal client migrates
supported global `tui.json` settings to `~/.config/opencode/cli.json` on first
start; leave the V1 files in place until the upgrade is accepted.

Upgrade only with explicit authorization:

```bash
opencode upgrade 2.2.7 --method curl
opencode --version   # expect 2.2.7
python3 scripts/orchestrator.py doctor --project /absolute/path/to/dev/repo
```

`doctor` must report `opencode_dialect: v2`, a satisfied version policy,
compatible generated commands and validated worker profiles. On V2.2.x it
verifies effective permissions with `opencode debug agents`. It does not prove
authenticated model execution or entitlement; run one small authorized worker
check separately if required.

Expected compatibility changes: native `agents`/`permissions` configuration,
`provider/model#variant` model references, `--standalone` sessions, and explicit
`external_directory`/`.env` denials because V2 allows external directories by
default. Existing V1 configuration remains readable by V2, but the supervisor
generates native V2 shapes when it detects a V2 binary.

Rollback if the upgrade fails:

```bash
opencode upgrade 1.18.35 --method curl
```

Then restore the archives above only if configuration was damaged, and rerun
`doctor`. Tests that require a real globally upgraded V2 CLI are the opt-in
suite:

```bash
ABDULLAH_OPENCODE_V2_BIN=$(command -v opencode) \
  python3 -m pytest scripts/tests/test_opencode_v2_integration.py
```

No step in this handoff upgrades the global CLI automatically, replaces the
maintained orchestrator, or touches live runs.
