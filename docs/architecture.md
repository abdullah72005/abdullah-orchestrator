# Architecture

This document describes the implementation that ships in `scripts/orchestrator.py`
(supervisor version **3.1.0**, state/config schema 3). It is written for someone who needs to modify,
audit, or debug the workflow — not as marketing material.

## Design goals

1. **The model decides; the supervisor enforces.** Engineering judgment
   (design, invariants, acceptance criteria, verdicts) belongs to the strong
   Architect. State transitions, process ownership, command execution, evidence
   binding, and recovery belong to deterministic Python.
2. **Persist intent before acting.** A dispatch is written durably before a
   child process starts, so a crash can be reconstructed rather than guessed.
3. **Fail closed.** Unproven ownership is `uncertain`, not "probably stopped".
   Missing evidence is a rejection, not a warning.
4. **Cheap where possible.** Status, recaps, verification, and recovery make no
   model calls. Strong calls are spent on planning, diagnosis, and acceptance.
5. **Install nothing.** One stdlib-only module, installed by symlinking the
   repository directory.

## Components

| Component | Implementation | Responsibility |
|---|---|---|
| Visible coordinator | Codex Luna Medium / Claude chat | Talk to the user; call MCP tools; summarize results |
| Supervisor | `scripts/orchestrator.py` | State machine, guards, verification, evidence, recovery |
| MCP server | `orchestrator.py mcp` | Nine foreground tools over stdio JSON-RPC |
| Guard | `orchestrator.py _guard` | Session/process-group leader; kills the tree if the lease closes |
| Architect | Codex `gpt-6.1-sol` or Claude Opus, high effort | Plan, diagnose, integrate, accept |
| Explorer | OpenCode Go, low variant | Read-only investigation |
| Implementer | OpenCode Go, high variant | One bounded writer per batch |
| Reviewer | OpenCode Go, high variant, fresh context | Independent findings |

The Architect and workers are external CLIs. The supervisor never imports them;
it builds argv, launches them under a guard, parses structured output, and
records provenance.

## Repository and runtime layout

```text
repository/
├── SKILL.md                     # skill manifest and operator instructions
├── agents/openai.yaml           # agent interface metadata
├── scripts/
│   ├── orchestrator.py          # supervisor + MCP server (single stdlib module)
│   ├── install_wsl.py           # installer / MCP registration
│   ├── config.example.json      # default configuration
│   └── tests/                   # deterministic tests and fixtures
└── references/                  # contracts, roles, operation details
```

```text
$ABDULLAH_STATE_DIR/<run-id>/
├── state.json                   # atomic authoritative run state
├── journal.jsonl                # append-only engineering journal
├── control.json                 # pause/cancel control request
├── supervisor.lock              # one supervisor per run
└── jobs/
    ├── plan-<id>/
    │   ├── dispatch.json        # role, route, source snapshot (before launch)
    │   ├── launch.json          # guard identity, child identity, exit phase
    │   ├── events.log           # raw worker stream
    │   ├── raw_report.json      # extracted final message
    │   ├── normalization.json   # extraction/repair record
    │   ├── report.json          # validated contract-v2 report
    │   └── completion.json      # outcome and process evidence
    ├── check-<batch>-<n>-<id>.log
    └── verification-<batch>-<id>.json
```

Checkout leases live in a sibling directory (`<state-root>-checkouts` by default,
or `ABDULLAH_CHECKOUT_REGISTRY`). One lease record names exactly one owning run
for a canonical Git checkout identity.

## Stage lifecycle

`STAGES` maps eight stage names to roles:

| Stage | Role | Model call | Produces |
|---|---|---|---|
| `plan` | Architect | yes | versioned plan |
| `explore` | Explorer | optional | investigation |
| `implement` | Implementer | yes | dirty worktree + worker report |
| `verify` | Supervisor | no | verification evidence |
| `review` | Reviewer | yes | findings |
| `accept` | Architect | yes | verdict |
| `diagnose` | Architect | yes | recovery plan |
| `integrate` | Architect | yes | final assessment |

`orchestrator_stage` performs exactly one transition. A typical ordinary-risk
run is:

```text
plan ─► implement ─► verify ─► review ─► accept ─► integrate ─► complete
                                │
                                └─ changes_required ─► implement (correction)
```

Mechanical risk may skip `review`; high risk requires a separate review and at
least two distinct verification checks. An accepted batch becomes an immutable
snapshot in `accepted_batches`; later work preserves it as history.

## Dispatch and report pipeline

1. **Source snapshot.** Capture resolved project path, git HEAD, dirty files and
   hashes, runtime-input manifest, environment values (hashed), config hash, and
   toolchain identity.
2. **Intent.** Write `dispatch.json` (role, route, source) before launch.
3. **Guard.** Spawn `_guard`, which becomes a session/process-group leader,
   holds a lease pipe from the supervisor, writes `launch.json` *before* the
   child starts, then execs the worker.
4. **Model call.** The worker receives a bounded prompt plus the generated JSON
   schema. Contract v2 fields are required.
5. **Extraction.** Read the final message, normalize JSONL/structured output,
   and preserve raw artifacts. Unparseable output is a typed ingestion failure;
   the raw evidence remains available to `recover-report`.
6. **Validation.** Reject missing fields, wrong contract versions, unknown
   roles, and reports that contradict the recorded job.
7. **Accounting.** Record usage (reported/derived/partial tokens, never inferred
   quota), elapsed time, and failed attempts.

## Containment gate

Every completion, interruption, reconciliation, retirement, and checkout
recovery uses one inspection gate. It checks:

- the recorded guard session and process group;
- `launch.json` child identity, not just the parent PID;
- `ABDULLAH_RUN_ID` / `ABDULLAH_JOB_ID` environment markers on surviving
  processes;
- the per-check `ABDULLAH_CHECK_TOKEN` survivors;
- recorded descendants and escaped processes from `/proc`;
- whether the artifact's completion snapshot still matches the checkout.

A dead PID is never sufficient proof: zombies are not live, reused PIDs are a
different execution, and a marked survivor fails closed. Verification records
the containment result inside its evidence. If a survivor is detected, the
verification fails even if containment killed it.

The guard's lease pipe is the crash safety net: if the supervisor or host
connection dies, the pipe closes and the guard kills the worker tree.

## Verification provenance

Verification executes only the plan's argv, never `shell=True`. Before and
after each command the supervisor records:

- candidate hash and source snapshot;
- runtime-input manifest (`complete`, file hashes, truncation state);
- environment variable names and value hashes;
- configuration hash and toolchain fingerprints (including argv executables);
- plan revision and `verification_purpose`;
- per-command log path, SHA-256, byte count, return code, and bounded output
  tail;
- containment result and escaped-process scan.

Acceptance re-loads this evidence and compares every binding. A changed
environment, toolchain, config, ignored executable, or source invalidates the
evidence. The run resets to `verify` instead of accepting stale results.

`evidence_version: 2` marks the current format. Historical records without the
new fields are `legacy_evidence` and cannot reach acceptance without
re-verification or the explicit, audited
`acknowledge-legacy-evidence` operator command.

## Command policy

The shipped policy rejects, by default:

- shell wrappers (`bash -lc`, `sh -c`) and wrapper binaries (`env`, `timeout`,
  `sudo`);
- interpreter string evaluation (`python3 -c`, `node -e`);
- indirect Docker execution and script-file execution;
- malformed argv.

Allowed commands such as `pytest -q`, `python3 -m unittest`, `git status
--porcelain`, and direct `docker compose run ...` remain usable. An exception
must be declared in `verification.command_policy.exceptions` with
`argv_regex`, `reason`, `scope`, and a non-model `authorized_by`. A scoped
exception without a project identity is ignored. Disabling a rejection requires
the documented `unsafe_acknowledged` value.

Command filtering is **not** filesystem, network, or credential isolation.

## Recovery state machine

```text
                 interrupt verified
   running ─────────────────────────────► paused ──resume──► running
      │                                     ▲
      │ interrupt unverified                │ reconcile (gate proves stopped)
      ▼                                     │
   uncertain ───────────────────────────────┘
```

- `paused` is safe to resume; partial work is preserved.
- `uncertain` forbids new dispatches until reconciliation.
- If no launch identity exists, only the operator can record an audited
  `--launch-missing` resolution after inspecting the situation.
- `compatibility` is read-only and reports `current`, `legacy`,
  `migration_required`, `supervisor_changed`, `config_changed`, or
  `unsupported_newer`. Migrations are explicit and backup-first.

## Checkout ownership

`checkout_identity()` resolves the canonical Git top level and hashes
`st_dev:st_ino` (falling back to the resolved path when inode is 0, as on some
WSL mounts). The registry distinguishes `initializing`, `active`, `final`,
orphaned, and conflicting owners.

A conflict returns the owner run ID and the exact resolution commands instead of
retrying. Resolution is operator-only:

- `checkout-status --project PATH` — inspect;
- `retire RUN_ID ...` — retire an inactive run without killing live work;
- `checkout-recover --project PATH --owner RUN_ID ...` — clear a genuinely
  orphaned record;
- `adopt RUN_ID` — adopt a legacy run into lease ownership.

Sensitive CLI actions are disabled by default
(`authorization.sensitive_cli_enabled: false`) and refuse to run inside a
model-owned worker context.

## Model and CLI compatibility

Every route is resolved from configuration at call time:

```text
architect -> provider = host, model = architect.<host>.model,
             effort = architect.<host>.effort, billing = .auth
worker    -> provider = "opencode", worker_provider = workers.<role>.provider
             (or model prefix), model = workers.<role>.model,
             effort = workers.<role>.variant, billing = .billing
```

Architect models may be any catalog model for the selected host. Worker model
IDs are fully qualified `provider/model-id`, split on the first slash; a declared
provider must match the prefix. The default remains `opencode-go/...` with
`billing: "go"`. Schema 3 accepts `subscription`, `api`, `free`, and `local`
billing only with explicit human authorization: non-Go dispatch requires a
per-run `authorize-route` grant (attestation for non-API classifications), and
the grant is consumed atomically before spawn. Routes, variants, billing and a
redacted provider/config fingerprint are pinned per run. Route-scoped fallback
is opt-in, one dispatch, and never inherits a session from another route.

`doctor` checks configured models (and, on V1, variants) against the installed
inventory, reports redacted provider availability/auth observability, and never
executes inference. Billing is policy/attestation, not inferred from a model
name; there is no hard dollar cap.

The supervisor supports tested OpenCode lines `>=1.18 <2.0` and `>=2.2 <3.0`
(configurable). It refuses unknown majors and untested ranges. On V2 it:

- generates native `agents`, `permissions`, `shell`, and `subagent`
  configuration;
- joins variants as `provider/model#variant`;
- adds `--standalone` so the model session stays inside the guarded tree;
- verifies effective permissions with `opencode debug agents` and rejects any
  later `allow`/`ask` that re-opens a mandatory deny, including glob-overlap
  cases.

`doctor` reports the detected version, dialect, policy result, generated command
compatibility, and worker profiles. It is a preflight check, not proof of
entitlement or execution.

## Version identifiers

| Identifier | Value | Meaning |
|---|---|---|
| `SUPERVISOR_VERSION` | `3.1.0` | Release version of the supervisor |
| `STATE_SCHEMA_VERSION` | `3` | On-disk run state shape |
| `CONFIG_SCHEMA_VERSION` | `3` | Configuration shape |
| `VERIFICATION_EVIDENCE_VERSION` | `2` | Verification evidence shape |
| `MCP_SERVER_VERSION` | `3.1-interactive` | MCP tool-surface revision, reported in `serverInfo` |

The MCP version describes the protocol/tool surface and is intentionally not the
release version. `compatibility` compares the supervisor, config, and state
versions; it refuses newer state schemas.

## Why one large module?

`orchestrator.py` is ~8.6k lines. The alternative — a package — would require
import-path handling for a directory that is symlinked into `~/.agents/skills`
and `~/.claude/skills`, plus a build/install step the project deliberately
avoids. A single module means:

- `install_wsl.py` only creates symlinks;
- `codex mcp add ... python3 <path>/orchestrator.py mcp` always works;
- there is no packaging metadata to drift from the shipped code;
- tests import the exact file that runs in production.

The cost is weak physical separation. Logical sections are marked with banner
comments (state, process/containment, reports, prompts, verification, MCP) and
the functions are grouped by concern. This is a deliberate trade-off, not an
accident; a future split should preserve the symlink-install property and add
tests before moving code.

## Non-goals

- No daemon installation, database, queue, or notification service.
- No nested Implementer agents.
- No exactly-once guarantee for external side effects.
- No OS-level sandbox. Dedicated users or containers remain the operator's
  responsibility.
