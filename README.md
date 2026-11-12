# Abdullah Orchestrator

A durable, quota-aware software engineering workflow for one interactive Codex
or Claude conversation. A visible coordinator talks to the user and drives a
bundled Python MCP supervisor. The supervisor owns execution state, process
lifecycle, checkpoints, verification and recovery, while a separate strong
Architect makes consequential decisions and cheap OpenCode Go workers perform
exploration, implementation and independent review.

The supervisor is standard-library Python. It persists dispatch intent before
launch, runs approved checks against the exact candidate checkout, records
provenance, and fails closed when process ownership is uncertain.

## Components

| Path | Purpose |
|---|---|
| `SKILL.md` | Main skill discovered as `$abdullah-orchestrator` |
| `agents/openai.yaml` | Agent interface metadata |
| `scripts/orchestrator.py` | Supervisor CLI, stage workflow and stdio MCP server |
| `scripts/install_wsl.py` | Installer and optional Codex MCP registration |
| `scripts/config.example.json` | Editable default model, limit and permission config |
| `references/` | Operation, role, contract and approved-handoff details |
| `scripts/tests/` | Deterministic supervisor test suite and fixtures |
| `MAINTENANCE.md` | Distribution, registration, backup and rollback notes |

## Requirements

- Linux or WSL, Python 3.10+
- `git`
- Codex CLI for Codex host mode; Claude Code CLI for Claude host mode
- OpenCode CLI with a paid OpenCode Go account
- Docker/Compose for projects whose verification uses containers

No extra Python packages are required.

## Install

Clone the repository anywhere on the Linux/WSL filesystem, then run the
installer from the clone root:

```bash
git clone <REPOSITORY_URL> abdullah-orchestrator
cd abdullah-orchestrator
python3 scripts/install_wsl.py
```

The installer:

- links the skill into `~/.agents/skills/abdullah-orchestrator` for Codex
  discovery;
- links it into `~/.claude/skills/abdullah-orchestrator` for Claude discovery
  (disable with `--no-claude`);
- refuses to overwrite unrelated files or symlinks;
- creates `~/.config/abdullah-orchestrator/config.json` from the example,
  without overwriting an existing config.

## Configure

Edit `~/.config/abdullah-orchestrator/config.json`. Confirm the paid Go account
and the exact model and variant identifiers available in the installed catalog.
The runtime fails visibly instead of silently downgrading models or switching
billing routes.

Validate the environment before a run:

```bash
python3 scripts/orchestrator.py doctor --project /absolute/path/to/dev/repo
```

`doctor` checks generated CLI options, configured models/variants and billing
risk. It is a preflight check, not a model call.

## Register the MCP server

Register the stdio supervisor once per Codex profile:

```bash
python3 scripts/install_wsl.py --register-codex
```

Or register it manually:

```bash
codex mcp add abdullah-orchestrator -- python3 <SKILL_DIR>/scripts/orchestrator.py mcp
```

Set the per-server timeout in `~/.codex/config.toml`, then restart Codex:

```toml
[mcp_servers.abdullah-orchestrator]
command = "python3"
args = ["<SKILL_DIR>/scripts/orchestrator.py", "mcp"]
tool_timeout_sec = 18000
```

Do not apply this timeout globally. Five hours deliberately exceeds the
supervisor's four-hour stage caps so the client cannot race the supervisor at
the boundary; it is a communication bound, not a stuck-worker detector. Keep it
strictly above the largest configured `limits` value.

## Use

Open one Codex chat with the visible coordinator model, invoke
`$abdullah-orchestrator`, and give it an absolute project path and precise goal.
The coordinator calls `orchestrator_start` once, then `orchestrator_stage` once
per engineering stage. Every stage is a separate visible foreground MCP call.

Available MCP tools: `orchestrator_start`, `orchestrator_stage`,
`orchestrator_status`, `orchestrator_recap`, `orchestrator_interrupt`,
`orchestrator_amend`, `orchestrator_resume`, `orchestrator_reconcile`,
`orchestrator_approve_plan`, `orchestrator_approve_fallback` and
`orchestrator_runs`.

Recovery from a new conversation is `orchestrator_runs` ->
`orchestrator_status` -> `orchestrator_resume`, followed by
`orchestrator_stage`. A verified interruption leaves the run `paused`; an
unverified one leaves it `uncertain` and requires `orchestrator_reconcile`
before any retry.

The same operations are available from the CLI when MCP is unavailable:

```bash
python3 scripts/orchestrator.py start --project /abs/project --goal-file goal.txt --host codex
python3 scripts/orchestrator.py stage <ID>
python3 scripts/orchestrator.py status <ID>
python3 scripts/orchestrator.py recap <ID> --detail quick
```

See [`SKILL.md`](SKILL.md) and [`references/`](references/) for the complete
workflow and contracts.

## State and configuration

- Run state: `~/.local/state/abdullah-orchestrator/runs/<ID>`
- Checkout lease registry: `~/.local/state/abdullah-orchestrator/runs-checkouts`
- Configuration: `~/.config/abdullah-orchestrator/config.json`

Override these with `ABDULLAH_STATE_DIR`, `ABDULLAH_CHECKOUT_REGISTRY` and
`ABDULLAH_CONFIG`. Runtime state, generated configs and bytecode are not tracked
by Git.

Checkout conflicts expose the owner run ID and resolution commands. Use
`checkout-status`, `retire` and `checkout-recover` for explicit operator
resolution; `adopt` is the legacy adoption path. These commands never launch a
model and never kill live work.

## Trust boundary

The Implementer is a broad-trust local development agent: local `.env`, Docker
and shell edits do not trigger routine approval. Explorer and Reviewer have
read-only OpenCode tool permissions, but that is not a complete OS sandbox.
Push, deploy, production access, broad deletion and billing changes are not
authorized by starting a run. Keep the workflow away from production
credentials and sensitive host files.

## Tests

```bash
python3 -m unittest discover -s scripts/tests
```

The suite makes no real model calls; model CLIs are replaced with fakes and a
guard prevents a real `codex`, `claude` or `opencode` process from launching.

## Maintenance

See [`MAINTENANCE.md`](MAINTENANCE.md) for distribution, backup, rollback and
MCP registration details.
