<p align="center">
  <img src="assets/icon.svg" width="72" height="72" alt="Abdullah Orchestrator icon">
</p>

<h1 align="center">Abdullah Orchestrator</h1>

<p align="center"><strong>Strong-model decisions. Cost-conscious execution. Independent verification. One controlling conversation.</strong></p>

<p align="center">
  <a href="docs/release-evidence/v1.2.0/README.md"><img alt="Release v1.2.0 candidate" src="https://img.shields.io/badge/release-v1.2.0%20candidate-2f6f4e"></a>
  <a href="https://github.com/abdullah72005/abdullah-orchestrator/actions/workflows/tests.yml"><img alt="Tests" src="https://github.com/abdullah72005/abdullah-orchestrator/actions/workflows/tests.yml/badge.svg"></a>
  <a href="https://www.python.org/"><img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10%2B-3776ab"></a>
  <a href="#requirements"><img alt="Runtime: standard library only" src="https://img.shields.io/badge/runtime-stdlib%20only-4b5563"></a>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-2f6f4e"></a>
</p>

Abdullah Orchestrator turns one interactive Codex or Claude conversation into a
disciplined engineering workflow. A visible coordinator talks to you and calls a
bundled Python **supervisor**; a strong **Architect** plans, diagnoses and
accepts; OpenCode **Explorer**, **Implementer** and fresh **Reviewer** workers do
the bounded work. The supervisor — not the language model — owns run state,
process ownership, verification and recovery, so an interrupted chat, a drifted
toolchain or an unverified "it works" cannot silently become accepted work.

Every model identifier is configurable: Architect models per host, and worker
provider, model, reasoning variant and billing classification per role. The
default worker route is OpenCode Go.

> [!IMPORTANT]
> **Project status — v1.2.0 release candidate.** Codex + OpenCode V2 is
> the primary route; Codex + OpenCode Go end-to-end execution and
> interrupted-run recovery are demonstrated. OpenCode V1 remains experimental.
> Claude Code has passed installed-CLI registration and a headless
> fixture-backed planning stage, and the Windows Codex desktop with a WSL agent
> completed planning and implementation through the disposable supervisor.
> Authenticated long Claude stages, desktop Stop controls and same-session
> Reviewer shell/edit capability remain unverified.
> Broader live compatibility and long-duration endurance testing remain ongoing.
> See [Tested behavior](#tested-behavior) and
> [Security and limitations](#security-and-limitations).

---

## Architecture

```text
        You
         |
         v
+--------------------------------------+
| Codex / Claude conversation          |
| visible coordinator  |  stdio MCP    |
+------------------+-------------------+
                   |
                   v
+--------------------------------------+
| Python supervisor                    |
| state | containment | evidence       |
+------------------+-------------------+
                   |
                   v
+--------------------------------------+
| 1  Strong Architect .... plan        |
| 2  Explorer (optional) . read-only   |
| 3  Implementer ......... one writer  |
| 4  Verification ........ argv checks |
| 5  Reviewer ............ fresh eyes  |
| 6  Architect ........... verdict     |
+------------------+-------------------+
                   |
      approved ----+---- changes required
         |                       |
         v                       +--> repeat 3-6, bounded
      complete
```

Every stage is one visible foreground call. The coordinator announces the worker
and expected output first, then reports only the structured result. Nothing is
hidden inside a single "do everything" call.

The supervisor, not a model, owns `state.json`, the journal, dispatch records,
process containment and verification. Explorer is skipped unless the run's policy
allows it. The correction loop is bounded by configured limits. Human-only
actions (`approve-plan`, `authorize-route`, `approve-fallback`, `retire`) are
operator CLI commands — never MCP tools.

**The split that matters:** the model decides, and the supervisor enforces.

| Concern | Owner |
|---|---|
| Design, invariants, acceptance criteria, final verdict | Strong Architect |
| State transitions, checkpoints, process ownership, command execution, evidence binding, recovery | Deterministic Python supervisor |
| Exploration, implementation, independent review | Worker models with bounded briefs |

## Why this exists

Most agent loops keep correctness in the model's context. When the chat is
compacted, the host sleeps, the worktree changes or a toolchain is upgraded, the
loop loses its footing and keeps going. Abdullah Orchestrator separates durable
engineering state from conversational state:

- Dispatch intent is written to disk **before** a process starts.
- Verification evidence is bound to the exact source snapshot, runtime inputs,
  environment, config and toolchain that produced it.
- Ownership that cannot be proven is `uncertain`, never "probably stopped".
- Acceptance checks the evidence again instead of trusting a previous message.

That is what makes a run resumable from a new chat, auditable after the fact and
safe to leave running for hours.

## Key capabilities

| Capability | What it means in practice |
|---|---|
| **Strong Architect ownership** | Planning, consequential diagnosis, integration and final acceptance use a strong model; routine status and recaps make no model call. |
| **Optional cheap exploration** | Explorer runs only when the run's explicit policy allows it (`none` by default). |
| **Configurable worker providers** | Each worker role has its own `provider/model`, `variant` and `billing`; OpenCode Go is the default. |
| **Per-role models and variants** | Pin a cheaper Explorer and a stronger Implementer/Reviewer without touching code. |
| **Deterministic verification** | The supervisor executes the approved argv (never `shell=True`) and records exit codes, logs, hashes and containment. |
| **Fresh independent review** | Ordinary work gets a separate Reviewer context; high-risk work needs two distinct checks. Review/decision authority is invalidated when verification is redone. |
| **Source-bound acceptance** | Evidence is rejected if HEAD, dirty files, runtime inputs, environment, config, toolchain, plan revision or checked executable changed. |
| **Correction cycles** | A `changes_required` verdict returns to a bounded Implementer correction instead of restarting the batch. |
| **Informative chat** | A bounded plan view, material-first review findings and the canonical Architect verdict with its reason; opt-in design consultation without weakening human plan approval. |
| **Durable run state** | Atomic `state.json`, append-only journal, per-job artifacts and verification logs under one run ID. |
| **Crash and interruption recovery** | Verified interrupt → `paused`; unverified → `uncertain` → reconcile only after containment proves every marked process stopped. |
| **Stale-provenance recovery** | Compatible environment/toolchain drift on intact evidence rewinds once to `verify`, preserving implementation and history, and disarms pre-invalidation review authority. |
| **Explicit billing authorization** | Non-Go routes require a human `authorize-route` grant bound to role, run and exact route material; unknown routes refuse rather than silently bill an API. |
| **Fallback safety** | Fallback is never automatic and never inherited from another route. |
| **Checkout ownership** | One lease per canonical Git checkout; conflicts return resolution commands instead of retrying. |
| **Codex and Claude host integration** | stdio MCP server plus installer registration for both hosts; Claude has installed-CLI registration and a headless fixture-backed stage, but authenticated long stages are not yet certified. |

Implemented behavior and *live-validated* behavior are deliberately separated.
See [Tested behavior](#tested-behavior) and [docs/validation.md](docs/validation.md).

## Requirements

| Requirement | Detail |
|---|---|
| OS | **Linux or WSL2 (Ubuntu)** — the verified platform. Native macOS/Windows and managed configuration delivery are not certified. |
| Python | **3.10+**, standard library only (no `pip install`, no virtualenv required). CI runs 3.10, 3.12 and 3.13. |
| Git | Any reasonably current `git`; verification uses real checkouts and worktrees. |
| Host CLI | Codex CLI **or** Claude Code CLI, both authenticated for your own account. |
| Worker CLI | OpenCode on a tested line: `>=1.18 <2.0` or `>=2.2 <3.0`. Other versions are refused instead of guessed. |
| Worker account | **OpenCode Go** subscription by default, or another OpenCode provider with an explicit, human-authorized billing route. |
| Docker | Only for projects whose verification needs containers. |

`doctor` verifies the installed CLIs, supported OpenCode line, generated argv,
configured model IDs, route/billing classification and (on OpenCode V2) effective
application permissions. It never launches inference.

## Quick start

```bash
git clone https://github.com/abdullah72005/abdullah-orchestrator.git
cd abdullah-orchestrator
python3 scripts/install_wsl.py --register-codex
```

The v1.2.0 candidate is available on `main` without a v1.2.0 release tag.
To install a specific candidate, check out its recorded commit and run the
installer:

```bash
cd /path/to/abdullah-orchestrator
git rev-parse HEAD
python3 scripts/install_wsl.py --register-codex
```

The last published release instructions remain
[the existing `v1.0.0` tag](https://github.com/abdullah72005/abdullah-orchestrator/tree/v1.0.0).
The candidate's deterministic evidence is in
[docs/release-evidence/v1.2.0/](docs/release-evidence/v1.2.0/README.md).
Do not assume a public `v1.2.0` tag or release exists.

The installer is idempotent and refuses to overwrite unrelated skills or
servers. It:

1. links the skill into `~/.agents/skills/abdullah-orchestrator` (Codex) and
   `~/.claude/skills/abdullah-orchestrator` (Claude; `--no-claude` to skip);
2. creates `~/.config/abdullah-orchestrator/config.json` from the example
   **without overwriting an existing config**;
3. with `--register-codex`, registers the stdio supervisor if it is absent.

Edit the config for your catalog, then preflight a real project:

```bash
python3 scripts/orchestrator.py doctor --project /absolute/path/to/dev/repo
python3 scripts/orchestrator.py version
```

Add the **per-server** timeout to `~/.codex/config.toml`, then restart Codex:

```toml
[mcp_servers.abdullah-orchestrator]
command = "python3"
args = ["/absolute/path/to/abdullah-orchestrator/scripts/orchestrator.py", "mcp"]
tool_timeout_sec = 18000
```

Keep this strictly above the largest configured `limits` value; do not apply it
globally. Open **one** Codex chat and invoke the skill:

```text
$abdullah-orchestrator
```

Then give it an absolute project path and a precise goal. The detailed,
verified installation walkthrough — including a clean-environment test, Claude
Code setup, upgrades, rollback and uninstall — is in
**[docs/installation.md](docs/installation.md)**.

## Configuration

One file: `~/.config/abdullah-orchestrator/config.json` (or `ABDULLAH_CONFIG`), or
start from `scripts/config.example.json`. The full reference is
[docs/configuration.md](docs/configuration.md). This complete example passes the
shipped validator:

```json
{
  "schema_version": 3,
  "architect": {
    "codex":  {"model": "gpt-6.2-sol", "effort": "high", "auth": "subscription"},
    "claude": {"model": "claude-opus-5-5", "effort": "high", "auth": "subscription"}
  },
  "workers": {
    "explorer":    {"provider": "opencode-go", "model": "opencode-go/deepseek-v4.1-flash", "variant": "low",  "billing": "go"},
    "implementer": {"provider": "opencode-go", "model": "opencode-go/deepseek-v4.1-flash", "variant": "high", "billing": "go"},
    "reviewer":    {"provider": "opencode-go", "model": "opencode-go/deepseek-v4.1-flash", "variant": "high", "billing": "go"}
  },
  "fallback": {"enabled": false},
  "limits": {"max_stage_seconds": 17000, "max_worker_seconds": 14400},
  "permissions": {"allow_push": false, "allow_deploy": false, "allow_production": false},
  "verification": {"require_checks": true, "require_docker_source_proof": true},
  "runtime": {"supervisor_version": "3.1.0", "opencode_supported": [">=1.18 <2.0", ">=2.2 <3.0"]}
}
```

| Role | Field | Notes |
|---|---|---|
| Architect (Codex) | `architect.codex.model` / `.effort` | Passed through; confirm it exists in your Codex catalog. |
| Architect (Claude) | `architect.claude.model` / `.effort` | Same, for the Claude host. |
| Explorer | `workers.explorer` | Optional read-only investigation. |
| Implementer | `workers.implementer` | The only writer. |
| Reviewer | `workers.reviewer` | Fresh independent context. |

The shipped Codex Architect default is `gpt-6.2-sol` at `high` on subscription
billing. The persistent Architect pin must stay `high` so acceptance,
diagnosis and integration remain dispatchable; a configured default or new
selection at another effort is refused during admission or switch. Final
acceptance always uses that High route. A run may explicitly opt into
`ordinary_planning_trial` at creation to use Medium for the **initial plan
only** on a task declared ordinary. The trial is validated against the exact
resolved Architect route for that run — the same subscription model must have
catalogue-confirmed Medium and High variants — and its pin records that route's
provider, model, effort and billing. A high-risk plan from the trial is not
admitted; replans, diagnosis, integration and acceptance stay High. An explicit
Architect switch before the first plan marks a pending trial ineligible
immediately; it never silently changes the trial's effort. A legacy run pinned
below High keeps its historical route and is blocked by the existing protected
dispatch guard; remediate it with a `switch-role` preview/apply to High or a new
run.

Discover valid worker IDs before editing:

```bash
opencode models opencode-go --verbose   # V1: includes variants
opencode models                         # V2: IDs only
python3 scripts/orchestrator.py doctor --project /absolute/path/to/repo
```

Rules the supervisor enforces:

- `billing: "go"` is valid only for the unchanged `opencode-go` route.
- Any other provider/billing needs an explicit human grant in the run's
  operator terminal: `orchestrator.py authorize-route <RUN> --role <role> ...`.
- A run pins its resolved routes. Changing role defaults mid-run does not
  reroute it; use a per-run `routes` override at creation or a human
  `switch-role` preview/apply. Behaviour-bearing policy changes (limits,
  permissions, verification, unknown keys) still mark the run `config_changed`
  and block stages until resolved. See
  [docs/configuration.md](docs/configuration.md#changing-configuration-during-a-run).
- New runs must state their host (`codex` or `claude`); there is no implicit
  default.

## Usage

Inside the Codex/Claude chat, the skill drives nine MCP tools:

| Tool | Purpose |
|---|---|
| `orchestrator_start` | Create durable run state (does not dispatch a worker). |
| `orchestrator_stage` | Run exactly one stage in the foreground. |
| `orchestrator_status` | Deterministic compact status, bounded plan view and canonical verdict; no model call. |
| `orchestrator_recap` | Quick or developer recap from recorded evidence. |
| `orchestrator_interrupt` | Persist, terminate and verify an interruption. |
| `orchestrator_amend` | Record a requirement/correction amendment and pause safely. |
| `orchestrator_resume` | Mark a paused run runnable (does not execute a stage). |
| `orchestrator_reconcile` | Clear an attempt only after containment proves it stopped. |
| `orchestrator_runs` | List recent runs for recovery from a new chat. |

The stage loop is:

```text
plan → implement → verify → review → accept → complete
                        └── changes_required ──► implement (correction)
```

The planning response and `orchestrator_status` include a bounded `plan_view`:
revision and approval state, summary rationale, main invariants, and each
displayed batch's title, goal, acceptance, risk and verification purpose. It
counts omitted entries and points to the developer recap or the durable report
for the rest; raw check argv stays out of the chat view. Review previews put
material findings first and count what was omitted. The canonical Architect
verdict and reason remain visible even when the run routes directly to a
correction. A completed Implementer is not the same as verified tests: the
coordinator says verification is pending until the supervisor runs it.

Plan approval is opt-in and the default stays automated. An ordinary request to
see the plan is not an approval pause. Start with `plan_approval: true` only for
an explicit request such as “Ask me about architecture and design choices before
you finalize the plan.” The Architect then puts concise rationale in the plan
summary, flags consequential forks with trade-offs and its recommendation, and
uses the blocker for a question that must be answered before a valid plan is
possible. The coordinator presents that actual proposal or question, records
the user's reply with `orchestrator_amend`, and obtains a versioned revised
plan. Chat discussion never grants execution authority, and approval of an
earlier plan cannot authorize its revision.

Human-only actions are **not** MCP tools and run in your own terminal:

```bash
python3 scripts/orchestrator.py approve-plan <RUN> --confirm approve-plan:<RUN>
python3 scripts/orchestrator.py authorize-route <RUN> --role implementer ...
python3 scripts/orchestrator.py approve-fallback <RUN> --role implementer --confirm approve-fallback:<RUN>
```

> [!WARNING]
> The CLI `start` command is **not** the state-only `orchestrator_start` tool.
> Without `--background`, `orchestrator.py start` runs the supervisor loop in the
> foreground and dispatches real models immediately. Use the MCP tool for the
> interactive workflow; use the CLI form only when you intend to run the legacy
> supervised loop. See [troubleshooting](docs/troubleshooting.md#cli-start-dispatched-models-immediately).

Pause, resume and recover:

```text
running ──verified interrupt──► paused ──resume──► running
   │
   └──unverified interrupt──► uncertain ──reconcile (all stopped)──► paused
```

- Never retry an `uncertain` run before `orchestrator_reconcile` proves
  containment.
- Attach from a new chat with `orchestrator_runs` → `orchestrator_status` →
  `orchestrator_resume`.
- A blocked stale-verification run recovers by `resume` + `stage`: the supervisor
  rewinds once to `verify`, keeps the old evidence inspectable, and requires a new
  Reviewer and a new acceptance.

Operations reference: [references/operation.md](references/operation.md).
Day-to-day recovery: [docs/troubleshooting.md](docs/troubleshooting.md).

## Live worker progress

Every stage records one durable attempt with its route, task, expected output,
clock and supervisor identity. Reading progress is additive and read-only: it
takes no write lock, never repairs or advances a run, and never changes the stage
outcome.

The coordinator posts one short line in the current chat before each call with
the worker, model and effort, task and expected output. After the call it posts
one short line with the outcome, measured duration and next action. Native
in-flight updates depend on the client, and the terminal observer is optional.

- `orchestrator_status` now carries `stage_progress`: attempt identity, current
  stage, effective role/model/effort, batch, sanitized task and expected output,
  elapsed seconds (live monotonic time while the recorded owner is proven alive,
  recorded duration after completion), latest observed activity, outcome and next
  action. Legacy journals without attempt identity stay readable.
- The same status and the plan stage carry `plan_view`, a bounded structured
  plan for reconnect from a fresh chat. A blocked plan reports its current
  question and rationale with a report reference; an older proposal is never
  substituted. Review previews prioritize material findings and count omissions.
- When the MCP client supplies a `progressToken`, the `orchestrator_stage` call
  also emits advisory `notifications/progress` updates about once per second for
  the attempt that call admitted. They carry a bounded human-readable message, a
  strictly increasing `progress` value and no `total`. Tokenless and refused
  calls emit nothing; cancellation and teardown stop them immediately.
- The terminal observer is read-only and follows a run across stages:

```bash
python3 scripts/orchestrator.py status --run <RUN_ID> --follow
```

While waiting it shows the next stage's role, route, task and expected output.
During a stage it ticks elapsed time and the latest activity; on return it shows
the outcome, measured elapsed time and next action. It keeps following until the
run reaches a final state, and `Ctrl-C` only closes the viewer. Redirected output
uses a plain-text mode instead of in-place redraws.

What each client actually does while a stage runs (verified in this batch):

| Surface | Observed behaviour |
|---|---|
| Claude Code CLI `2.1.247` | Renders native MCP progress in the TUI. A real 38.6 s stage showed the role, route, batch, activity and ticking seconds, then `Called orchestrator` and `Crunched for 39s`. |
| Codex CLI `0.169.1` | Supplies an integer progress token and receives the notifications, but its terminal prints only `mcp: … started` / `(completed)`. The adjacent `status --follow` pane ticked elapsed time, activity, measured duration and next action during the same 36.4 s stage. |
| Codex desktop (Windows + WSL agent) | Verified the `status --follow` view in the integrated terminal during a 32.92 s Implementer stage. It showed live elapsed time, activity, outcome and the next stage. Native tool-card progress and in-app Stop remain unverified. [Smoke evidence](docs/release-evidence/live-progress/README.md#windows-codex-desktop-result) |
| Claude desktop | No suitable desktop session was available in this batch; use an adjacent terminal observer with the same fixture. |

Native notifications never replace the guarded foreground stage: a progress
failure cannot advance, cancel or delay it.

## What changed in 1.2.0

- An explicit Implementer `needs_architect` routes straight to durable strong
  diagnosis with its question, evidence and unknowns, not to a cheap retry.
  Routine, attributable check failures keep one bounded cheap attempt.
- A user requirement amendment triggers a versioned strong replan; prior plan,
  checks, review, approval, decision bindings and worker continuation are
  invalidated while artifacts and audit history remain readable.
- Implementer and Reviewer receive the user's verbatim goal and amendments once,
  separate from the Architect's interpretation. The fresh Reviewer also receives
  acceptance criteria, an observed batch-delta index and supervisor-generated
  check results through a digest-bound read-only projection inside the checkout.
- Codex and Claude receive the full request on stdin (no positional prompt);
  OpenCode keeps its supported positional transport behind byte-aware exec
  checks. Stable policy is delivered once per effective route.
- Each foreground stage announces local time, role, exact configured/effective
  model and effort, batch identity, task and expected output, then reports
  elapsed time, outcome and next action.
- Active orchestrator workers bypass the overlapping Superpowers
  `writing-plans`, `executing-plans` and `subagent-driven-development` skills
  while retaining systematic debugging and focused TDD.

## Tested behavior

**Deterministic suite (offline, no model calls):** the final v1.2.0
candidate ran **1,069 tests, with 1,059 passing and 10 skipped** on Python
3.10.12 (1,779.7 s) at the stabilized code/test revision `16a0816`; the
documentation-only follow-up preserves the tested tree. The earlier `f59a2cd`
stabilization ran 1,065 tests (10 skipped); the r06 candidate ran 980, the
initial v1.2.0 candidate 911 (7 skipped), and the previous v1.0.0 baseline 870.
All 10 skips are the opt-in OpenCode introspection module, which runs only when
`ABDULLAH_OPENCODE_V2_BIN` is set; it passes all 10 tests against the installed
`opencode v2.2.7` separately. A guard replaces real `codex`, `claude` and
`opencode` processes with fakes. CI configuration for Python 3.10, 3.12 and
3.13 is unchanged; this candidate's local evidence is Python 3.10 only.

**Real end-to-end milestone (2026-11-16 → 2026-11-18):**

| Item | Value |
|---|---|
| Run | `20261116T124500-973e8c02` |
| Host / coordinator | Codex CLI on a dedicated isolated profile |
| Architect | `gpt-6.1-sol`, effort `high` (subscription) — historical v1.0.0 run |
| Workers | OpenCode `v2.2.7`, OpenCode Go `deepseek-v4.1-flash` (implementation `high`, review `high`) |
| Explorer | Not dispatched (`explorer_policy: none`) |
| Real work | Implemented a duration-parsing contract in a disposable fixture repo |
| Supervisor verification | `python3 -m unittest discover -s tests -t . -v` → exit 0, **44 tests OK** |
| Incident | The Reviewer was interrupted mid-stage by an operator command timeout |
| Recovery | Verified interrupt → `paused`; later resume detected stale verification provenance and rewound once to `verify` |
| Fresh completion | New verification, **new independent Reviewer**, Architect inspection and `approved` verdict, status `complete` |
| Accounting | 2 strong + 2 cheap calls; OpenCode Go reported `cost: 0`; no API-billed route |

What this demonstrates: real planning, real implementation, deterministic
verification, interruption containment, stale-provenance recovery, fresh review
and source-bound acceptance — with no surviving jobs or checkout conflicts.

What it does **not** demonstrate: uninterrupted multi-hour operation, measured
quota savings, strong-only quality parity, provider monetary settlement,
authenticated Claude Code compatibility, or live alternative-provider support.
The run began on `0ea5381`; its recovery and acceptance were completed on
2026-11-18 with the accepted recovery build (`b9819a7`).

Reproduce the deterministic suite:

```bash
python3 -m compileall -q scripts
python3 -m unittest discover -s scripts/tests -v
```

Details, historical pilot evidence and explicit non-claims:
[docs/validation.md](docs/validation.md).

## Security and limitations

The Implementer is a broad-trust local development agent: it may edit the
authorized checkout and run local shell/Docker commands. Explorer and Reviewer
are read-only. Generated OpenCode V2 profiles deny pushes, destructive Git,
`docker compose down -v`, external directories, web access, subagents and `.env`
reads; verification executes argv arrays, never a shell string.

**These are application-level permissions, not an OS sandbox.** A process that
shares your OS account, clears its environment or changes user can escape these
controls. Use a dedicated user, VM or container for valuable repositories, and
keep production credentials away from the workflow.

Other limitations:

- Single sequential writer; no daemon, database, queue or notifications.
- Same-user trust boundary: human-only CLI gates are real but not cryptographic.
- `runtime_inputs.complete` means declared/discovered inputs were hashed without
  truncation — not a proof of the complete runtime dependency graph.
- Billing classifications are policy/attestation; there is no hard dollar cap and
  no inference of provider-side settlement.
- `doctor` does not authenticate, prove entitlement or execute a model.
- OpenCode V1 has no live runtime verification. Claude Code has installed-CLI
  registration and a headless fixture-backed stage; interactive controls,
  authentication and provider-backed Claude workers are not live-certified.
  The Windows Codex desktop with a WSL agent completed planning and
  implementation, but in-app Stop, live worker activity and fresh-thread
  recovery were not exercised. macOS/Windows managed configuration is not
  certified.

Full threat model: [docs/security-model.md](docs/security-model.md).
Reporting: [SECURITY.md](SECURITY.md).

## Documentation

| Document | Contents |
|---|---|
| [docs/installation.md](docs/installation.md) | Supported environments, clean install, MCP registration, upgrades, rollback, uninstall |
| [docs/configuration.md](docs/configuration.md) | Models, providers, variants, billing grants, fallback, limits, permissions |
| [docs/architecture.md](docs/architecture.md) | Components, state layout, stage lifecycle, containment, provenance |
| [references/operation.md](references/operation.md) | Detailed operator workflow and recovery semantics |
| [references/contracts.md](references/contracts.md) | Exact JSON contracts for plan, worker, reviewer and verdict reports |
| [references/roles.md](references/roles.md) | Role responsibilities and escalation rules |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Symptom → cause → exact recovery command |
| [docs/versioning.md](docs/versioning.md) | Public release vs supervisor, schema and contract versions |
| [docs/validation.md](docs/validation.md) | Test evidence, E2E milestone, explicit non-claims |
| [docs/security-model.md](docs/security-model.md) | Trust boundaries, permissions, limitations |
| [docs/maintenance.md](docs/maintenance.md) | Distribution, backup, rollback, OpenCode V1→V2 handoff |
| [docs/audit/](docs/audit/) | Independent audit findings and before/after probes |
| [SKILL.md](SKILL.md) | The agent-facing skill definition |

## Project status

**v1.2.0 release candidate.** Adds immediate escalation, versioned
requirement replans, verbatim user requirements for workers, independent review
evidence with batch-delta attribution, stdin prompt transport for Codex/Claude,
byte-aware OpenCode exec checks, foreground stage announcements, the ordinary
Medium planning trial, the `gpt-6.2-sol` Codex Architect default, and scoped
Superpowers instructions for active runs. The candidate suite result is recorded
in [docs/release-evidence/v1.2.0/](docs/release-evidence/v1.2.0/README.md).
Codex + OpenCode Go E2E and interrupted-run recovery demonstrated at v1.0.0.
Broader live compatibility and endurance testing remain ongoing. Earlier
internal tags (`v3.0.0`, `v3.1.0-audit-candidate.1`) are historical engineering
milestones and are preserved; the public product version is independent of the
internal supervisor, schema and contract versions. See
[docs/versioning.md](docs/versioning.md).

## Contributing

Contributions are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) first; security
reports follow [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE) © Abdullah
