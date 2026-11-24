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
> A **post-v1.2.0 follow-up** adds live stage progress and richer single-chat
> reporting. It is not a new release and does not recertify v1.2.0. Native
> in-chat progress was observed only on Claude Code CLI; Codex CLI and Claude
> desktop lack a verified in-chat live view, and Codex desktop tool-card progress
> remains unverified.
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
| **Informative chat** | One short before/after line per stage in the controlling chat, a bounded plan view, material-first review findings and the canonical Architect verdict with its reason; opt-in design consultation without weakening human plan approval. |
| **Live stage progress** | Read-only `stage_progress` in status, advisory MCP progress where the client renders it, and an optional `status --follow` terminal observer; none of them can mutate or stop the stage. |
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
| `orchestrator_reconcile` | Clear a parent job/check or lane-only attempt only after containment proves it stopped. |
| `orchestrator_runs` | List recent runs for recovery from a new chat. |

The stage loop is:

```text
plan → implement → verify → review → accept → complete
                        └── changes_required ──► implement (correction)
```

The planning response and `orchestrator_status` include a bounded `plan_view`:
revision and approval state, summary rationale, main invariants, and each
displayed batch's title, goal, acceptance, risk and verification purpose. It
counts omitted entries and points to `orchestrator_recap detail=developer`, the
no-model read-only detail path that lists every current-plan batch, invariant
and acceptance criterion plus every recorded Reviewer finding with location,
evidence, confidence and disposition. That plan and finding detail has no
pagination bound; other developer-recap lists keep their labeled bounds, and the
compact preview and quick recap stay bounded. Returned artifact references
resolve inside the run directory. Raw check argv stays out of routine previews.
Review previews put critical, high, medium and low findings first, preserve the
recorded order within a severity, and report `findings_omitted_count`; the
stored report is never reordered or truncated. The canonical Architect verdict
and reason remain visible even when the run routes directly to a correction;
the acceptance line presents that verdict as **PASS**, **CHANGES REQUIRED** or
**BLOCKED**. A completed Implementer is not the same as verified tests:
the coordinator says verification is pending until the supervisor runs it, and
after each successful Implementer milestone adds a short developer summary of
what changed, how it works, key paths, worker test notes and pending
verification. Reviewer findings and Architect verdicts are summarized from the
recorded report; role prompts, private reasoning and raw worker output are not
replayed into routine chat.

Plan approval is opt-in and the default stays automated. An ordinary request to
see the plan is not an approval pause. Start with `plan_approval: true` only for
an explicit request such as “Ask me about architecture and design choices before
you finalize the plan.” The Architect then puts concise rationale in the plan
summary, flags consequential forks with trade-offs and its recommendation, and
uses the blocker for a question that must be answered before a valid plan is
possible. The coordinator presents that actual proposal or question. If the
reply answers a blocking question or materially changes the design or
requirements, it records the exact reply with `orchestrator_amend` and obtains a
versioned revised plan; if the user accepts the unchanged plan, it shows the
existing human approval action without a needless replan. Chat discussion never
grants execution authority, and approval of an earlier plan cannot authorize its
revision. Once an amendment supersedes a blocked question, status reports
replanning pending rather than the answered question.

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

## Live progress and chat reporting (post-v1.2.0)

This follow-up is recorded separately from the v1.2.0 evidence below. It keeps
the public `1.2.0` version and internal identifiers; it is not a release.

Every stage records one durable attempt with its route, task, expected output,
clock and supervisor identity. Reading progress is additive and read-only: it
takes no write lock, never repairs or advances a run, and never changes the stage
outcome.

The single controlling chat is the primary surface. Before each call the
coordinator posts one short line with the worker, model and effort, task and
expected output. After the call it posts one short line with the outcome,
measured duration and next action. On the same chat it also:

- presents the bounded `plan_view` when a plan is created or status is
  inspected, and the current blocking question when planning is blocked;
- reports material Reviewer findings first and says how many were omitted;
- states the canonical Architect verdict and reason, including a
  `changes_required` verdict that routes straight to correction;
- adds a short Implementer summary at a successful milestone, without claiming
  tests passed;
- holds the opt-in design conversation only after an explicit `plan_approval`
  request.

Native in-flight updates depend on the client, and the terminal observer is
optional.

- `orchestrator_status` now carries `stage_progress`: attempt identity, current
  stage, effective role/model/effort, batch, sanitized task and expected output,
  elapsed seconds (live monotonic time while the recorded owner is proven alive,
  recorded duration after completion), latest observed activity, outcome and next
  action. Legacy journals without attempt identity stay readable.
- The same status and the plan stage carry `plan_view`, a bounded structured
  plan for reconnect from a fresh chat. A blocked plan reports its current
  question and rationale with a verified report reference; an older proposal or
  a superseded question is never substituted, and an amendment shows replanning
  pending. Review previews prioritize material findings and count omissions.
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

What each client actually does while a stage runs (verified on the follow-up
revision):

| Surface | Observed behaviour |
|---|---|
| Claude Code CLI `2.1.247` | Renders native MCP progress in the TUI. A real 38.6 s stage showed the role, route, batch, activity and ticking seconds, then `Called orchestrator` and `Crunched for 39s`. |
| Codex CLI `0.169.1` | Supplies an integer progress token and receives the notifications, but its terminal prints only `mcp: … started` / `(completed)`. The adjacent `status --follow` pane ticked elapsed time, activity, measured duration and next action during the same 36.4 s stage. |
| Codex desktop (Windows + WSL agent) | Verified the `status --follow` view in the integrated terminal during a 32.92 s Implementer stage. It showed live elapsed time, activity, outcome and the next stage. Native tool-card progress and in-app Stop remain unverified. [Smoke evidence](docs/release-evidence/live-progress/README.md#windows-codex-desktop-result) |
| Claude desktop | No suitable desktop session was available in this batch; use an adjacent terminal observer with the same fixture. |

Native notifications never replace the guarded foreground stage: a progress
failure cannot advance, cancel or delay it.

Remaining unverified client behavior:

- Codex CLI `0.169.1` received the notifications but printed no in-chat progress
  text, so its live view depends on the adjacent observer.
- Codex desktop tool-card progress, in-app Stop and fresh-thread recovery were
  not exercised; only the integrated WSL terminal observer was verified.
- Claude desktop in-chat progress and its adjacent terminal observer were not
  tested.
- Authenticated long Claude stages and native Claude desktop stop/reconnect
  behavior remain unverified.

## Verified verification reuse, parallel writers, skills and preflight

This v1.2.1-phase work is additive: existing state/protocol versions, manual
plan approval, model pins, billing controls and the independent Reviewer are
unchanged. Defaults keep one writer and no explicitly selected skill.

### Reuse the one formal verification

The Implementer request boundary remains the formal `verify` stage. Normally the
final acceptance gate and integration reuse its supervisor-owned evidence
instead of executing the same required argv again. Reuse fails closed unless the
complete ordered command set, plan/batch/revision and amendment/recovery epochs,
source and runtime-input identity, environment, toolchain, configuration,
command policy, containment and per-command log digests still match. The same
rule is re-applied after the Architect returns and before completion, including
for a derived reuse record, which must still bind its original records and logs,
and for every formal record included in the Architect decision (for example the
original batch record alongside an explicit-repeat final record). The Reviewer
packet is refused before assembly if the formal record or any recorded command
log no longer matches its supervisor digest; a recomputed digest from altered
bytes cannot replace the recorded authority. The record bytes that are hashed
are the exact bytes parsed. A changed candidate, tampered/removed/replaced record
or log, environment drift, explicit `repeat_checks: true` (honored for single-
and multi-batch integration), `fresh_verification_required`, or an uncovered
final check executes the checks again. Worker prose and arbitrary local test
claims are never authority. Old evidence records stay readable with legacy
validation but cannot silently certify a new completion.

### Opt-in parallel writers

Parallel writing is a per-run permission, not an implicit model choice:

- `orchestrator_start` / `start` accepts `max_parallel_writers: 1..3`
  (CLI: `--max-parallel-writers 1..3`). The default is one.
- The strong Architect may put an optional `writers` array on a batch. Each
  assignment has a stable ID, goal, exact literal paths and/or unambiguous
  component prefixes, completion criteria and the Implementer role. Pairwise
  overlap, duplicate IDs, unsafe paths and more than three writers fail before
  launch.
- The effective count is the smallest of permission and plan, and the same
  resolver decision governs preflight, approval, resume and implementation. An
  explicit one-writer assignment uses the ordinary single-writer path. A dirty,
  untracked, ignored-runtime, sparse, submodule-bearing or otherwise
  unreproducible base, a proposal above the run's writer permission, or a pending
  one-shot route fallback selects one writer with a durable reason. Plan approval
  reports that approved single-writer fallback instead of blocking on
  parallel-only worktree or grant prerequisites; those prerequisites are checked
  only when parallel dispatch is actually selected. Missing authority on the
  route that will actually run still blocks.
- With permission, each writer gets an isolated Git worktree on the same pinned
  clean base, its own persisted execution slot/job artifacts and the existing
  route grant, quota, cancellation and containment controls. One transaction
  source identity (HEAD plus exact tree/index provenance) is admitted once and
  reused across resume; an operator commit or unexpected index/worktree change
  preserves every lane and blocks with an explicit reconciliation path instead of
  starting a lane or applying a patch against a new base. Lane intent, attempt
  identity, run/plan/revision/epoch/batch/assignment/base provenance are
  journaled and saved before the thread can launch; a durable result is only
  promoted when its provenance and stopped execution still match.
- Authority for every admitted lane is reserved in the run-scoped ledger before
  any model dispatch. Each reservation carries its exact run, route, role
  generation, batch, lane attempt and owning grant. Route preflight admits that
  held slot instead of searching for a second unused one, launch records the
  one-way reserved→launched transition before spawn, and a launched slot is never
  refunded automatically. A positively proven no-exec failure (for example an
  `E2BIG` refusal before any child exists) may refund only that exact slot. Public
  resume accounts for the next actual action: a resumed writer may reuse its held
  slot, a finished lane whose durable result only awaits parent collection needs
  no new capacity, an exact integration checkpoint needs no new writer grant, and
  only uncovered launches need capacity. A later same-route grant never re-homes
  or re-books an existing reservation; exact rejected-slot cleanup resolves the
  slot's owning grant before refunding. Insufficient or wrong-scope authority
  produces zero launches; invalid, mismatched, released and already-launched
  slots stay denied, and unrelated grants are untouched.
- Host and configured worker fallback consent belongs to the parent run and is
  never copied into a parallel lane. Before admission a one-shot fallback may
  select the ordinary single-writer path; after admission the pinned primary is
  resolved first, and any route change or single-writer collapse is an explicit
  parent-owned recovery transition. Preflight validates the exact route the
  pending single writer will use and its one-shot authority without consuming it;
  an unused primary remains advisory, while an invalid or missing fallback
  authorization blocks. At most one fallback dispatch is spent per approval,
  including across restart.
- A lane is promoted only for a `complete` report. A valid `blocked` report
  preserves its partial worktree/patch and exact report but never enters the
  verification candidate; a completed sibling is preserved for reuse and is not
  redispatched. A `needs_architect` report goes to strong diagnosis with its
  original question, evidence and unknowns. Resume re-runs only the blocked or
  unfinished lanes, and an explicit one-writer plan stays on the ordinary path.
  Durable lane execution uncertainty is checked even when the parent label says
  failed; no cleanup, integration, fallback or replacement launch occurs until
  the exact old execution is proven stopped. `orchestrator_reconcile` discovers
  lane-only uncertainty even when no parent `active_job`/`active_check` exists,
  proves every applicable lane execution stopped, keeps completed siblings, and
  persists a paused resume point without clearing a pending scoped authorization
  requirement.
- The supervisor inspects actual tracked/untracked/rename/delete/mode and index
  changes, rejects unowned paths or HEAD changes, generates a binary patch per
  lane and proves a dry integration in scratch before touching the canonical
  checkout. A full integration is recorded with the exact approved writer set,
  transaction intent and expected before/after tree/index identities. Recovery
  classifies the canonical identity against the durable manifest: exact after
  finishes bookkeeping and full integration attribution with zero second applies
  or dispatches, exact before continues that recorded apply, and an unrecognized
  intermediate or divergent identity stays blocked with preserved evidence. A
  pending single-writer or route fallback cannot bypass that recovery decision.
- If one sibling fails after another completes, the completed patch is applied
  only as a separately identified sibling-only recovery after the single-writer
  intent is saved. That partial apply can never authorize verification; a crash
  after a sibling patch but before its durable apply record leaves a divergent
  identity that blocks instead of dispatching a writer, while an exact before
  identity continues only the sibling apply. A finalized sibling manifest is
  revalidated against its scope, intent and exact canonical after/source identity
  before its first single-writer correction is admitted, and the admission marker
  alone never bypasses that check on a later retry. The first single writer's
  prompt and expected dispatch source are frozen from that same validated sibling
  snapshot and bound to the manifest digest, so an edit during context
  construction, preflight or launch admission blocks before any child starts
  while preserving the worktree and manifest. The final no-child gate rechecks the
  frozen source signature together with the exact checkout tree/index/file-mode
  digest and re-hashes and parses the same manifest bytes it validated, for the
  first and every subsequent correction attempt. A preflight refusal or missing
  launch is not a proven attempt; external divergence stays blocked. Once an
  attempt has a durable source-bound job/launch, its continuation remains tied to
  the approved batch, revision, epoch and sibling manifest. The next writer starts
  from the last exact source boundary (source plus tree/index/mode) recorded by
  that attempt's failure, completion or operator reconciliation evidence.
  Reconciliation preserves an already-attested boundary and surfaces any later
  edit as a visible source conflict through reconcile, resume and dispatch; an
  edit after that boundary requires explicit amendment/replan, while unchanged
  partial worker output resumes through the ordinary source-bound gate. The
  unfinished lane's worktree stays inspectable. Ownership
  conflicts, unplanned dependencies or integration conflicts preserve every lane
  and route to strong diagnosis.
- The combined canonical candidate then goes through supervisor checks, one
  fresh independent Reviewer and the strong Architect decision. Timing records
  lane wall/sum, integration and review separately; concurrent durations are
  reported as wall time, not added together. A fast lane's completion is
  observable while a quiet sibling is still running, and the bounded milestone
  list is replayed after the call when inline rendering is unavailable.

### Explicit skill routing

Start input may name skills per role and per stable writer ID, for example
`{"architect": ["systematic-debugging"], "implementer": ["django-testing"],
"reviewer": ["code-review"], "writers": {"w1": ["superpowers"]}}`. The mapping,
content digests and bounded artifacts persist across retries, recovery,
corrections and fresh review. A small deterministic bundle alias expands
`superpowers` to the four documented skills; a missing member fails visibly.
Resolution is bounded to configured/known roots with exact content digests and
path/symlink checks.

Skill text is delivered as bounded prompt material with explicit precedence:
supervisor and role policy override it, and it never grants permissions,
approval, shell access, routing, billing or scope. Native per-role loading is not
claimed for the supported adapters; the prompt-injection fallback is recorded in
state. Required tools are checked against what the exact role can be offered on
its adapter, not just the supervisor's PATH: a Reviewer/Explorer skill that needs
shell, edit, network or subagent access fails visibly, and an OpenCode Implementer
skill is bound to that adapter's explicit deny rules (for example subagent or
network access) rather than the host's broader capability. Missing, changed or
over-budget pinned artifacts fail before the affected stage; changing the
original source after start does not mutate the pinned run-local copy. Task
keywords never select a skill.

### Authorization preflight and blocked recovery

`orchestrator_start` response and state include a grouped permission preflight
for the actual route/billing policy (default host subscription and OpenCode Go
need no new grant; API/OpenCode subscription/free/local do), route and check
executables under the check environment, role/writer skill tools and pinned
artifacts, approved check argv policy and parallel worktree/grant prerequisites.
Plan approval checks the whole approved run; resume blocks only on pending stage
requirements, so an exhausted grant for an already-completed paid role is shown
as deferred instead of stopping unrelated acceptance work. The effective route is
resolved before capabilities are checked for every fallback-capable pending role
(Architect, Explorer, Implementer and Reviewer): an approved one-shot fallback
owns the blocking executable, grant and skill-tool checks for the pending stage,
while an unused primary's missing CLI or exhausted grant is advisory. An admitted
parallel Implementer remains pinned to its primary. A parallel fan-out
reserves one run-ledger reservation per admitted lane before any model dispatch;
an insufficient grant or a failed reservation produces zero launches and
releases reservations whose launch was never attempted, while a held slot whose
launch was never attempted is reused rather than charged again. When a grant is
short, the surfaced remedy requests one new exact-route grant for the full
admitted count because admission does not combine multiple grants.
`authorize-route` remains the human billing grant; `approve-plan`, fallback,
destructive changes and deployment keep their existing gates.

An unexpected recognized structured permission/approval request, or a documented
noninteractive credential prompt, is observed while the worker or supervisor
check is still active and stops it ahead of the normal stage/check deadline. Only
bounded prompt classes, safe action identifiers and fixed reasons are persisted;
arbitrary structured message/action/reason text and adjacent plaintext excerpts
never reach authorization state, the journal, status or recap. Running sibling
lanes see the shared pause and are contained through the existing guard/interrupt
paths before a blocked state is claimed; completed edits and verified evidence
are preserved. The run reports **blocked**, not a retry loop. After the scoped
authorization/authentication is corrected,
`orchestrator_resume` re-runs preflight and continues from the preserved boundary
without repeating completed work. Unknown causes are labelled unknown; raw
credential text is not persisted.

Fixture coverage is distinguished from live host rendering: the Codex CLI
received MCP notifications but printed no in-chat text in the recorded run, so
its adjacent viewer/replay remains the fallback.

## What changed in 1.2.0

The live-progress and chat-reporting work above is post-v1.2.0 follow-up, not
part of this v1.2.0 list.

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

**Post-v1.2.0 follow-up suite (offline, no model calls):** the accepted feature
revision `720dd7c2e4c0b404cccc430e14f40c1f1385dd04` (`720dd7c`) ran **1,183
tests, OK, 10 skipped** in 1,715.570 s on Python 3.10.12. The 10 skips are the
same opt-in OpenCode introspection module. The documentation-only commit after it
does not change `scripts/`. Earlier follow-up gates also passed; the 1,183 result
is the final one. This is follow-up evidence, not a new v1.2.0 suite result.

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

**Follow-up client evidence:** native in-chat progress was observed on Claude
Code CLI `2.1.247`. Codex CLI `0.169.1` received notifications but rendered only
tool start/completion, so its live view needs the adjacent observer. Codex
desktop was verified only through the integrated WSL terminal during a 32.92 s
Implementer stage. Claude desktop in-chat progress and observer, Codex desktop
tool-card progress and in-app Stop, and authenticated long Claude stages remain
unverified. The follow-up did not measure quota savings or provider settlement.

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
| [docs/release-evidence/live-progress/](docs/release-evidence/live-progress/README.md) | Follow-up live-progress evidence, desktop fixture and operator steps |
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
A post-v1.2.0 follow-up adds live stage progress, the read-only `status --follow`
observer and richer single-chat reporting. Its 1,183-test evidence belongs to
revision `720dd7c`, is kept separate from the v1.2.0 result, and is not a new
release or tag.
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
