<p align="center">
  <img src="assets/icon.svg" width="64" height="64" alt="Abdullah Orchestrator icon">
</p>

# Abdullah Orchestrator

**Durable, quota-aware multi-agent engineering from a single chat — with a deterministic Python supervisor, verified evidence, and recoverable checkpoints.**

[![Tests](https://github.com/abdullah72005/abdullah-orchestrator/actions/workflows/tests.yml/badge.svg)](https://github.com/abdullah72005/abdullah-orchestrator/actions/workflows/tests.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Standard library only](https://img.shields.io/badge/runtime-stdlib%20only-success.svg)](#requirements)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Abdullah Orchestrator turns one interactive Codex or Claude conversation into a
disciplined engineering workflow. A cheap visible coordinator drives a bundled
Python **supervisor**; a strong **Architect** plans and accepts; paid OpenCode Go
**Explorer**, **Implementer**, and independent **Reviewer** workers do the
bounded work. The supervisor — not the language model — owns state, process
lifecycle, verification, and recovery.

Every model identifier is configurable in one JSON file: Architect models per
host, and worker models/variants within the paid OpenCode Go catalog. See
[Model configuration](#configure-models).

It was built for long-running work on a real repository where a dropped chat,
a wrong checkout, or an unverified "it works" is expensive.

```
        you
         │
         ▼
┌──────────────────────────┐        stdio MCP         ┌────────────────────────────┐
│ Visible coordinator      │ ◄──────────────────────► │ Python supervisor (stdlib) │
│ Codex Luna / Claude chat │                          │ state · guard · evidence   │
└──────────────────────────┘                          └─────────────┬──────────────┘
                                                                   │ guarded process sessions
                              ┌────────────────┬───────────────────┼───────────────────┐
                              ▼                ▼                   ▼                   ▼
                       ┌────────────┐   ┌────────────┐      ┌────────────┐      ┌────────────┐
                       │ Architect  │   │ Explorer   │      │ Implementer│      │ Reviewer   │
                       │ strong     │   │ Go, low    │      │ Go, high   │      │ Go, high   │
                       │ plan/accept│   │ read-only  │      │ one writer │      │ read-only  │
                       └────────────┘   └────────────┘      └────────────┘      └────────────┘
```

## Why this exists

Most "agent loops" put state in the model's context. When the chat is
interrupted, the context is compacted, or the wrong worktree is checked out,
the loop silently loses correctness. Abdullah Orchestrator separates the two
concerns:

- **The model decides.** The Architect owns design, invariants, acceptance
  criteria, and the final verdict.
- **The supervisor enforces.** It persists dispatch intent *before* launch,
  binds every verification result to the exact source snapshot, guards worker
  process trees, and fails closed when ownership is uncertain.

That split is what makes the workflow resumable, auditable, and safe to leave
running for hours.

## Highlights

| Capability | What it means in practice |
|---|---|
| **Durable runs** | Every stage, report, log, and checkpoint is on disk under a run ID. Recovery from a new chat is `runs → status → resume`. |
| **Verified evidence** | Acceptance evidence is bound to git HEAD, dirty-file hashes, runtime inputs, environment values, config hash, toolchain identity, verification argv, and plan revision. Change any of them and old evidence is rejected. |
| **Containment** | Workers run in a guarded session/process group with a lease pipe. Interrupt, reconcile, and completion all use one fail-closed containment gate. |
| **Risk-based QA** | Mechanical work can skip the separate reviewer; ordinary work gets an independent review; high-risk work needs two distinct checks and a nonempty verification purpose. |
| **Explicit cost control** | Strong-model calls are reserved for planning, consequential diagnosis, and acceptance. Recaps and status are deterministic and free. |
| **Typed handoffs** | Every worker emits one JSON object against a generated, strict schema. Contract v2 fields are required; legacy reports cannot masquerade as fresh evidence. |
| **OpenCode V1 + V2** | Generates the correct dialect for the installed CLI, validates effective V2 permissions through the real CLI, and refuses untested versions. |
| **Human-only boundaries** | Plan approval, fallback authorization, retirement, and adoption are operator CLI actions — never MCP tools a model can call for itself. |

## How a run works

One conversation, one stage per visible foreground MCP call:

| Stage | Agent | Produces |
|---|---|---|
| `plan` | Architect | Invariants, coherent batches, acceptance criteria, argv checks |
| `explore` | Explorer | Read-only investigation when policy allows it |
| `implement` | Implementer | One bounded batch in the authorized checkout |
| `verify` | Supervisor | Executes the plan's argv against the exact candidate |
| `review` | Reviewer | Independent findings with severity and disposition |
| `accept` | Architect | Evidence-based verdict; correction wave if needed |
| `diagnose` | Architect | Recovery plan for a blocked or uncertain run |
| `integrate` | Architect | Final integration checks and closing assessment |

The coordinator announces the worker, task, and expected output before each
stage, then reports only the structured result. It never hides several stages
inside one call and never claims completion without supervisor evidence.

## Requirements

- Linux or WSL, **Python 3.10+** (standard library only — no pip install)
- `git`
- Codex CLI (Codex host) or Claude Code CLI (Claude host)
- OpenCode CLI with a paid **OpenCode Go** account
- Docker/Compose only for projects whose verification uses containers

## Quick start

```bash
git clone https://github.com/abdullah72005/abdullah-orchestrator.git
cd abdullah-orchestrator
python3 scripts/install_wsl.py
```

The installer links the skill into `~/.agents/skills/abdullah-orchestrator`
(Codex) and `~/.claude/skills/abdullah-orchestrator` (Claude; use `--no-claude`
to skip), refuses to overwrite unrelated files, and creates
`~/.config/abdullah-orchestrator/config.json` without overwriting an existing
config.

Edit the config and confirm the exact model/variant identifiers in your
installed catalog ([full configuration reference](docs/configuration.md)), then
run the preflight:

```bash
python3 scripts/orchestrator.py doctor --project /absolute/path/to/dev/repo
```

`doctor` checks CLI options, configured models/variants, billing route, and — on
OpenCode V2 — the *effective* permissions the CLI reports. It does not launch a
model session or prove entitlement.

Register the stdio supervisor once per Codex profile:

```bash
python3 scripts/install_wsl.py --register-codex
# or manually:
codex mcp add abdullah-orchestrator -- python3 "$PWD/scripts/orchestrator.py" mcp
```

Set the per-server timeout in `~/.codex/config.toml` and restart Codex:

```toml
[mcp_servers.abdullah-orchestrator]
command = "python3"
args = ["/absolute/path/to/abdullah-orchestrator/scripts/orchestrator.py", "mcp"]
tool_timeout_sec = 18000
```

Keep this bound strictly above the largest configured `limits` value. Five
hours deliberately exceeds the supervisor's four-hour stage caps so the client
cannot race the supervisor at the boundary. Do not apply it globally.

Open one Codex chat, invoke `$abdullah-orchestrator`, give it an absolute
project path and a precise goal. Full walkthrough:
[`docs/architecture.md`](docs/architecture.md).

## Configure models

Everything lives in `~/.config/abdullah-orchestrator/config.json` (or
`ABDULLAH_CONFIG`). Routes resolve deterministically:

| Role | Config field | Constraint |
|---|---|---|
| Architect (Codex host) | `architect.codex.model` / `.effort` | Passed through; confirm it is in the Codex catalog |
| Architect (Claude host) | `architect.claude.model` / `.effort` | Passed through; confirm it is in the Claude catalog |
| Explorer | `workers.explorer.model` / `.variant` | `opencode-go/...`, billing `go` |
| Implementer | `workers.implementer.model` / `.variant` | `opencode-go/...`, billing `go` |
| Reviewer | `workers.reviewer.model` / `.variant` | `opencode-go/...`, billing `go` |

Example — pin the Implementer to a different Go model while keeping the cheaper
Explorer:

```json
{
  "workers": {
    "explorer":    {"model": "opencode-go/deepseek-v4.1-flash", "variant": "low",  "billing": "go"},
    "implementer": {"model": "opencode-go/glm-5.3",             "variant": "high", "billing": "go"},
    "reviewer":    {"model": "opencode-go/deepseek-v4.1-flash", "variant": "high", "billing": "go"}
  }
}
```

Discover valid IDs before editing:

```bash
opencode models opencode-go --verbose   # V1: includes variants
opencode models                         # V2: IDs only
```

Then confirm with `doctor`:

```bash
python3 scripts/orchestrator.py doctor --project /absolute/path/to/repo
```

`doctor` reports `paid_go_model_listed`, `variant_verified`, and the resolved
route per role. Worker **providers** are intentionally fixed to paid OpenCode Go
in 3.0.0 — `billing` must be `go` and the model must start with
`opencode-go/`; any other value is rejected rather than silently moving work to
an API-billed route. Architect models and all worker model IDs/variants are
fully editable. Set them before starting a run: changing the config mid-run
marks the run `config_changed` and blocks further stages.

Complete reference, limits, fallback, and recipes:
[`docs/configuration.md`](docs/configuration.md).

## MCP surface

Nine tools, deliberately small:

| Tool | Purpose |
|---|---|
| `orchestrator_start` | Create durable run state. Does **not** dispatch a worker. |
| `orchestrator_stage` | Run exactly one stage in the foreground. |
| `orchestrator_status` | Deterministic compact status. No model call. |
| `orchestrator_recap` | Quick or developer recap from persisted evidence. No model call. |
| `orchestrator_interrupt` | Persist, terminate, and verify an interruption. |
| `orchestrator_amend` | Record a requirement/correction amendment and pause safely. |
| `orchestrator_resume` | Mark a paused run runnable. Does not execute a stage. |
| `orchestrator_reconcile` | Clear an attempt only after containment proves it stopped. |
| `orchestrator_runs` | List recent runs for recovery from a new chat. |

Plan approval and fallback authorization are **not** MCP tools. They run in an
interactive operator terminal and require the exact typed confirmation:

```bash
python3 scripts/orchestrator.py approve-plan <ID> --confirm approve-plan:<ID>
python3 scripts/orchestrator.py approve-fallback <ID> --role implementer \
  --confirm approve-fallback:<ID>
```

A model cannot approve its own plan or authorize its own fallback.

## Interruption, recovery, and uncertainty

```text
running ──interrupt (verified)──► paused ──resume──► running
   │
   └──interrupt (unverified)──► uncertain ──reconcile (all stopped)──► paused
```

- A **verified** stop preserves partial work and leaves the run `paused`.
- An **unverified** stop leaves it `uncertain`. Do not retry and do not launch a
  duplicate worker; reconcile first.
- If no launch identity was ever persisted, the user must inspect the situation
  and run the audited `reconcile <ID> --launch-missing --evidence '...'` path.
- The MCP server has no cancel tool. Interrupt, verify `stopped: true`, then use
  the explicit CLI `cancel` if the user authorizes it.

Details: [`references/operation.md`](references/operation.md).

## State and configuration

| What | Default |
|---|---|
| Run state | `~/.local/state/abdullah-orchestrator/runs/<ID>` |
| Checkout leases | `~/.local/state/abdullah-orchestrator/runs-checkouts` |
| Config | `~/.config/abdullah-orchestrator/config.json` |

Override with `ABDULLAH_STATE_DIR`, `ABDULLAH_CHECKOUT_REGISTRY`, and
`ABDULLAH_CONFIG`. Runtime state, generated configs, and bytecode are not
tracked by Git.

A run directory contains atomic `state.json`, an append-only `journal.jsonl`,
per-job dispatch/report artifacts, verification logs, checkpoints, and the
supervisor lock. The checkout registry names exactly one owner per working
tree and exposes resolution commands instead of retrying a conflicting stage.

## Security model in one paragraph

The Implementer is a broad-trust local development agent: it may edit the
authorized checkout and run local shell/Docker commands. Explorer and Reviewer
are read-only. Generated **V2** OpenCode profiles deny pushes, destructive Git,
`docker compose down -v`, external directories, web access, subagents, and
`.env` reads. Verification executes argv arrays, never `shell=True`, and the
shipped command policy rejects shell wrappers, interpreter string evaluation,
indirect Docker, and arbitrary script files unless an explicit scoped exception
is recorded. **These are application-level permissions, not an OS sandbox.** Use
a dedicated user or container for valuable repositories, and keep production
credentials away from the workflow.

Full threat model: [`docs/security-model.md`](docs/security-model.md).

## Validation

- **579 deterministic tests** in the default suite (4 opt-in skips) covering
  state transitions, containment, provenance, command policy, recovery,
  report ingestion, permissions, and structured output. No model calls; model
  CLIs are replaced with fakes and a guard blocks real `codex`, `claude`, or
  `opencode` processes.
- **A real end-to-end pilot** on 2026-11-13 completed a goal through Architect
  plan → Implementer → supervisor verification (22 tests) → independent review
  → Architect acceptance, using Codex `gpt-6.1-sol` and OpenCode Go
  `deepseek-v4.1-flash` on OpenCode `v2.2.7`. The pilot surfaced three genuine
  defects (invalid strict JSON schema, missing `contract_version`, and report
  ingestion recovery); all were fixed with regression tests and are documented
  in [`docs/validation.md`](docs/validation.md).

Reproduce the deterministic suite:

```bash
python3 -m unittest discover -s scripts/tests
```

The opt-in real-CLI suite makes no model call:

```bash
ABDULLAH_OPENCODE_V2_BIN=/path/to/opencode-2.2.7 \
  python3 -m unittest discover -s scripts/tests -p "test_opencode_v2_integration.py"
```

## Repository layout

```text
.
├── SKILL.md                  # Skill entry point (installation and operation)
├── agents/openai.yaml        # Agent interface metadata
├── scripts/
│   ├── orchestrator.py       # Supervisor CLI + stdio MCP server
│   ├── install_wsl.py        # Installer and Codex MCP registration
│   ├── config.example.json   # Editable model, limit, permission defaults
│   └── tests/                # 579-test deterministic suite and fixtures
├── references/               # Operation, roles, contracts, approved handoff
├── docs/
│   ├── architecture.md       # Components, state model, stage lifecycle
│   ├── configuration.md      # Models, limits, permissions, recipes
│   ├── security-model.md     # Trust boundaries and limitations
│   ├── validation.md         # Test evidence and the real end-to-end pilot
│   ├── maintenance.md        # Distribution, backup, rollback, upgrade
│   └── audit/                # Independent-audit findings and before/after probes
├── assets/icon.svg
├── CHANGELOG.md
├── CONTRIBUTING.md
├── SECURITY.md
└── LICENSE
```

`scripts/orchestrator.py` is intentionally a single standard-library file: the
skill is installed by symlinking the repository directory, and a single module
keeps installation, import, and dependency surface trivial. The trade-off and
module map are documented in [`docs/architecture.md`](docs/architecture.md).

## Documentation

| Document | Contents |
|---|---|
| [`SKILL.md`](SKILL.md) | The agent-facing skill: setup, operations, recovery, principles |
| [`references/operation.md`](references/operation.md) | Detailed operation and trust boundaries |
| [`references/contracts.md`](references/contracts.md) | Exact JSON contracts for plan, worker, reviewer, verdict |
| [`references/roles.md`](references/roles.md) | Role responsibilities and escalation rules |
| [`docs/architecture.md`](docs/architecture.md) | Internal design, state layout, failure handling |
| [`docs/configuration.md`](docs/configuration.md) | Models, limits, permissions, fallback, recipes |
| [`docs/security-model.md`](docs/security-model.md) | Threat model, permissions, operator boundaries |
| [`docs/validation.md`](docs/validation.md) | Test evidence and the real end-to-end pilot |
| [`docs/maintenance.md`](docs/maintenance.md) | Distribution, backup, rollback, OpenCode V1→V2 |
| [`docs/audit/`](docs/audit/) | Audit findings, corrections, and before/after probes |

## Limitations

- Single sequential writer. No nested Implementer agents, daemon installation,
  database, or notifications.
- Same-user trust boundary: the honor system behind human-only actions is real
  but not cryptographic. A shell-capable process with the same OS account can
  still edit config or import the module.
- Application-level permissions are defense in depth, not an OS sandbox.
  A process that clears its environment or changes user can escape the
  verification survivor scan.
- `runtime_inputs.complete` means the discovered/declared inputs were hashed
  without truncation and required inputs were found. It is not a proof of the
  complete runtime dependency graph.
- `doctor` is a preflight check: it does not authenticate, prove entitlement, or
  execute a model.

## Contributing

Contributions are welcome. Read [`CONTRIBUTING.md`](CONTRIBUTING.md) first;
security reports should follow [`SECURITY.md`](SECURITY.md).

## License

[MIT](LICENSE) © Abdullah
