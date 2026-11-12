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
`orchestrator_amend`, `orchestrator_resume`, `orchestrator_reconcile` and
`orchestrator_runs`.

Plan approval and fallback authorization are deliberately **not** MCP tools. A
model cannot approve its own plan or authorize its own fallback. Run them from
an interactive operator terminal:

```bash
python3 scripts/orchestrator.py approve-plan <ID> --confirm approve-plan:<ID>
python3 scripts/orchestrator.py approve-fallback <ID> --role implementer   --confirm approve-fallback:<ID>
```

The supervisor requires a TTY and the exact typed confirmation and records the
actor, method and time in the journal. This is an operator-controlled boundary,
not cryptographic proof: a same-user process that allocates a TTY and types the
token can still pass it. Do not treat a typed message, an ordinary MCP call, or
a model-authored shell command as human authorization.

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
resolution; `adopt` is the legacy state-adoption path. Sensitive CLI actions are
disabled by default and must be enabled explicitly in the local config. These commands never launch a
model and never kill live work.

## Verification security and provenance

Verification runs only the plan's argv, never `shell=True`. The shipped policy
rejects shell wrappers (`bash -lc`), interpreter expressions (`python3 -c`,
`node -e`), indirect Docker execution and script-file execution by default.
Legitimate commands such as `pytest -q`, `python3 -m unittest`,
`git status --porcelain` and direct `docker compose run ...` remain usable.

Unusual checks require an explicit, scoped exception in
`verification.command_policy.exceptions` with `argv_regex`, `reason`, `scope`
and a non-model `authorized_by`. Exceptions are recorded with the exact command
in the evidence. Disabling a rejection requires the documented
`unsafe_acknowledged` string; it is never silent.

Command filtering is **not** filesystem, network or credential isolation. It
only prevents known-obfuscated invocation forms. Use a dedicated user or
container when real isolation is required.

Acceptance evidence is bound to the source snapshot, git HEAD, runtime-input
manifest, environment values, configuration hash, toolchain identity,
verification argv, plan revision and candidate hash. Changing `NODE_ENV`, the
toolchain, the config or an ignored executable invalidates old evidence instead
of reusing it. `runtime_inputs.complete` means every discovered/declared input
was hashed without truncation and every `required` input was found; it is not a
proof of the complete runtime dependency graph. Declare project-specific inputs
in `.abdullah/runtime-inputs.json` (`include`, `required`, `exclude`).

## Trust boundary

The Implementer may edit the authorized project and run local shell/Docker
commands, but generated OpenCode profiles explicitly deny pushes, destructive
Git operations, `docker compose down -v`, external directories, web access,
subagents and `.env` reads. Explorer and Reviewer are read-only. These are
application-level permissions, not an OS sandbox; a malicious project can still
abuse an allowed command. Push, deploy, production access, broad deletion and
billing changes are never authorized by starting a run. Keep the workflow away
from production credentials and sensitive host files.

## OpenCode version support

The supervisor supports the tested lines `>=1.18 <2.0` and `>=2.2 <3.0`
(configurable with `runtime.opencode_supported`). It refuses unknown majors and
untested ranges instead of claiming forward compatibility. For V2 it generates
native `agents`/`permissions`/`shell`/`subagent` configuration, joins the
variant into `provider/model#variant`, and adds `--standalone` so the model
session stays inside the guarded process tree.

`doctor` reports the detected version, dialect, version-policy result, generated
command compatibility and effective worker profiles. On V2.2.x it verifies
effective permissions with `opencode debug agents`; on V1 it uses
`opencode debug agent`. Model execution and entitlement remain unverified by
`doctor`.

## Tests

```bash
python3 -m unittest discover -s scripts/tests
```

The suite makes no real model calls; model CLIs are replaced with fakes and a
guard prevents a real `codex`, `claude` or `opencode` process from launching.
To exercise the real V2 CLI without a model call, point the opt-in suite at an
isolated binary:

```bash
ABDULLAH_OPENCODE_V2_BIN=/path/to/opencode-2.2.7 \
  python3 -m pytest scripts/tests/test_opencode_v2_integration.py
```

## Maintenance

See [`MAINTENANCE.md`](MAINTENANCE.md) for distribution, backup, rollback and
MCP registration details.
