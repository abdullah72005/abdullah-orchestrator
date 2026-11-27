---
name: abdullah-orchestrator
description: Run or resume Abdullah's durable, quota-aware software engineering workflow from one interactive Codex, Claude Code or Antigravity conversation (CLI or Windows desktop). Dispatches a strong Architect plus OpenCode Go Explorer, Implementer and independent Reviewer as visible foreground MCP calls, with automatic plan progression, safe interruption, evidence-backed recaps, deterministic recovery and recoverable checkpoints.
---

# Abdullah Orchestrator

One interactive conversation is the coordinator. The visible model (Luna Medium in Codex) talks to the user and invokes a bundled Python MCP supervisor. The supervisor owns execution state, process lifecycle, checkpoints, verification and recovery; a separate strong Architect (Sol High in Codex) makes consequential decisions. The **original** `abdullah-architect` and `abdullah-implementer` remain untouched.

Public product version **1.2.1**. The internal supervisor protocol remains
`3.1.0`, state/config schema `3`, and report contract `2`; a public tag never
renumbers them. `python3 scripts/orchestrator.py version` prints all identifiers.
See `docs/versioning.md` for upgrade and compatibility policy.

## Default mode: one interactive foreground conversation

Interactive foreground mode keeps the user in one Codex, Claude Code or
Antigravity chat, in the CLI or the Windows desktop app. For Codex, Luna Medium
is the usual coordinator. Invoke `$abdullah-orchestrator` and stay in the same
conversation.

- The strong Architect remains a separate worker; the Python supervisor remains deterministic.
- Every engineering stage is one visible foreground MCP invocation.
- Before dispatch, the coordinator sends one short chat line with the worker, model and effort, task and expected output.
- During the call, native progress appears on clients that render the supervisor's updates. This varies by client and version.
- When the call returns, the coordinator sends one short chat line with the outcome, measured stage time from `elapsed_seconds`, and next action.
- Every transition names the acting worker or says nobody is active, the current task or outcome, measured elapsed time and the concrete next step. A pending or preflight state says the model has not launched. Verification says no model is active and gives the current safe check ordinal, never check argv. A blocked result states whether the worker launched, the durable reason code, and who acts next; a prelaunch refusal reads as zero launches with an actionable next step.
- The coordinator proceeds to the next stage within the same conversation without asking the user to continue. Valid plans progress automatically unless the user explicitly requested a consultation.

The stage announcement and result belong in the current chat on Codex, Claude
Code and Antigravity, in CLI and desktop. The stage result supplies measured
duration even on clients without live rendering. Claude Code CLI `2.1.247`
showed native updates during testing. Codex CLI `0.169.1` showed tool start and
completion in the tested `exec` session. Antigravity progress rendering is
client-dependent; a bounded `progress.replay` is always returned for replay, and
it never costs an inference call. The read-only terminal observer is optional
and is not desktop GUI integration.

Startup, `status` and the read-only `status --follow` viewer include one
execution-environment line derived from the supervisor process itself, for
example `Running in Ubuntu (WSL2) · Project: /home/abdullah/my-project`. A
Windows desktop chat never makes a WSL supervisor report native Windows.

Legacy detached `start --background` mode is optional, is **not** the default, and must not be selected without the user's explicit authorization. It survives closing a chat only while WSL stays awake; a sleeping host cannot execute jobs.

## Setup

1. You do not need to read the references first; the ordinary loop is below.
   Load them only when needed: [operations and recovery](references/operation.md),
   [role policies](references/roles.md), [report contracts](references/contracts.md).
2. Copy the whole skill directory onto the WSL filesystem and run `python3 scripts/install_wsl.py` from its root. The installer links the skill into `~/.agents/skills/abdullah-orchestrator` (Codex discovery) and `~/.claude/skills/abdullah-orchestrator` (Claude discovery), refuses to overwrite unrelated files, and creates the editable config.
3. Edit `~/.config/abdullah-orchestrator/config.json`; verify the paid Go account and exact model/variant identifiers. Run:
   `python3 scripts/orchestrator.py doctor --project /absolute/dev/project`
4. Register the interactive MCP server once (or use `install_wsl.py --register-codex`):
   `codex mcp add abdullah-orchestrator -- python3 <SKILL_DIR>/scripts/orchestrator.py mcp`
   Then set the per-server timeout in `~/.codex/config.toml` and restart Codex:

   ```toml
   [mcp_servers.abdullah-orchestrator]
   command = "python3"
   args = ["<SKILL_DIR>/scripts/orchestrator.py", "mcp"]
   tool_timeout_sec = 18000
   ```

   Do not apply this timeout globally. Codex's 300-second default is too short for a legitimate Architect, Implementer or Reviewer stage. Five hours deliberately exceeds the default whole-stage (`max_stage_seconds`, 17,000 s) and per-child caps so the host cannot race the supervisor at the boundary; it is a communication upper bound, not a stuck-worker detector.

   For Claude Code, register the same server in the project/user MCP
   configuration with a server-scoped timeout in milliseconds, for example:

   ```json
   {"mcpServers": {"abdullah-orchestrator": {
     "command": "python3",
     "args": ["<SKILL_DIR>/scripts/orchestrator.py", "mcp"],
     "timeout": 18000000}}}
   ```

   `18000000` ms is five hours. Registration only configures the host's
   communication bound; it does not apply a timeout by itself.
5. Restart Codex, open **one** chat with Luna Medium, and invoke `$abdullah-orchestrator`.

### Antigravity CLI in WSL2

The Antigravity CLI host is opt-in and **not yet live-certified**. The supervisor
refuses dispatch unless the installed `agy --help` advertises the exact headless
tokens its adapter requires (`--print`, `--model`, `--output-format`, plus
`--effort`/`--session` when those features are used). `agy` is not on PATH in the
candidate's validation shell, so treat a missing CLI as an actionable blocker,
not as success.

1. Verify the installed CLI yourself: `agy --version` and `agy --help`; keep the
   output for the run record.
2. Add `architect.antigravity` to your own config with a verified model id and
   `effort: "high"`, plus `auth` (`subscription`, `api`, `go`, `free` or
   `local`). Final acceptance still requires High; the shipped example
   deliberately has no Antigravity entry so existing Codex/Claude configs keep
   working.
3. Register the stdio MCP server in the installed CLI's settings, or merge it
   safely with an explicit path:
   `python3 scripts/install_wsl.py --register-antigravity --antigravity-settings <PATH>`.
   The writer refuses a missing/invalid/conflicting file, preserves unrelated
   servers, backs up before rewriting and never invents a schema.
4. Keep a **server-scoped** communication timeout above `max_stage_seconds`
   with margin. The shipped bound is 18,000,000 ms (5 h) against a 17,000 s
   budget; `install_wsl.py` rejects an insufficient bound. Do not apply it
   globally. Per-tool foreground configuration on the installed `agy` is
   unverified in this environment.
5. Prompts, including large Arabic UTF-8 text, travel on **stdin**, never as
   argv. A structured terminal report is required; a clean process exit alone is
   not acceptance.

### Antigravity Windows desktop connected to WSL2

Run everything on the Linux side. The desktop conversation is only the
coordinator; running `agy` in its integrated terminal is not GUI integration.

```bash
python3 scripts/install_wsl.py --setup-desktop
```

The output records the actual `WSL_DISTRO_NAME`, absolute Python, checkout,
config, run-state, `opencode` and `agy` paths plus the Windows `wsl.exe` launch
bridge. Register that entry in the **desktop application's own MCP settings**,
not only in a terminal. If `agy`/`opencode` or the distro is unknown, the output
lists blockers; do not relabel a WSL supervisor as native Windows.

The runtime selects OpenCode V1 or V2 configuration based on the installed CLI version, supports the tested ranges `>=1.18 <2.0` and `>=2.2 <3.0`, and rejects untested versions. It never silently switches from paid Go to free models or from subscription auth to billed API credentials.

## Operations

Use the MCP tools below. Every tool except `orchestrator_start` and `orchestrator_runs` takes `run_id`. Do not invent tool names or bypass these operations with ad-hoc supervisor commands.

1. **Start a run** — `orchestrator_start` with the absolute `project`, a precise `goal`, and the required controlling `host` (`codex`, `claude` or `antigravity`). Other optional arguments: `plan_approval`, `require_explorer`, `allow_explorer`, `explorer_policy` (`none`|`on_demand`|`required`), `approved_handoff` plus `authorize_handoff`, `skip_doctor`, and `ordinary_planning_trial` (with `planning_trial_risk: "ordinary"`). New and legacy runs default to `explorer_policy=none` unless permission is explicit. It creates durable state and does **not** dispatch a worker.

   `orchestrator_start` also accepts `max_parallel_writers: 1..3` (default 1)
   and an explicit `skills` object keyed by role and stable writer ID. Pass
   `skills` only with names the user actually requested. Show the resolved skill
   mapping and the permission-preflight `missing`/`advisories` from the start
   response. Parallel writers are an operator permission; the Architect chooses
   the actual count on the plan and the supervisor falls back to one with a
   durable reason when the base is not reproducible. An explicit one-writer
   assignment uses the ordinary single-writer path. Skill text never grants
   tools, permissions or scope; required tools are checked against the exact
   role's effective adapter profile, so an OpenCode Implementer skill cannot
   require a denied subagent/network action.

   The ordinary planning trial is an explicit, run-scoped opt-in for a task the
   operator declares ordinary before dispatch. It uses the pinned Codex Sol 6.2
   route at Medium effort for the **initial plan only**. If that plan contains
   high-risk work it is not admitted; resume for a fresh High plan. Replans,
   consequential diagnosis, integration and final acceptance always use the
   pinned High route. Do not opt in when the risk is unknown.
2. **Execute one stage** — `orchestrator_stage` with `run_id`. It runs exactly one of plan, explore, implement, verify, review, accept, diagnose or integrate. Announce the agent, task and expected output first. Never hide several stages in one call. A parallel `implement` stage still shows one role line; its result includes the per-writer assignment statuses and a fast lane can appear complete before a quiet sibling. If the host displayed no inline milestones, replay the bounded `progress.replay` list after the call. Only a `complete` writer report can enter the candidate; a `blocked` report preserves its partial work and stops for correction, and `needs_architect` routes to strong diagnosis. A blocked stage includes `permission_blocked` (authority) or `parallel_blocked` (writer report) with the exact action and resume step; correct that scoped authority/blocker, then resume. A prompt detected while a worker or check is still running stops it ahead of the normal deadline. Do not relaunch a completed sibling. If an operator commit or checkout change invalidates the admitted parallel source, stop for explicit reconciliation; do not reset or start a new writer against the new base. Plan approval reports an approved single-writer fallback (dirty base, proposal above permission, or pending route fallback) instead of demanding parallel-only prerequisites; when that fallback is reported, proceed with the ordinary single-writer path.
3. **Inspect status** — `orchestrator_status` with `run_id`. Deterministic compact status, bounded `plan_view`, active job/check, canonical verdict and reason, next action and run directory; makes no model call.
4. **Interrupt or pause** — `orchestrator_interrupt` with `run_id` and a short `reason`. Persists the interruption, terminates the process session and descendants, verifies termination and preserves changes. A verified stop leaves `paused`; an unverified stop leaves `uncertain`.
5. **Quick recap** — `orchestrator_recap` with `detail: "quick"` (the default). About 5–12 lines covering phase/agent, completed work, changed files, verification, decisions, outstanding issues and next action.
6. **Detailed developer explanation** — `orchestrator_recap` with `detail: "developer"`. What was implemented, how it works, why that approach was chosen, important files/symbols, actual test commands and results, and remaining limitations. It also returns every current-plan batch, invariant and acceptance criterion plus every recorded Reviewer finding with evidence, confidence and disposition, and resolvable run-scoped artifact references. Makes no model call.
7. **Amend requirements** — `orchestrator_amend` with `amendment` (exact text), `kind` and `architect_review`. `kind` defaults to `requirement`, which replans and invalidates affected evidence; use `kind: "correction"` only for a bounded implementation detail. It interrupts active work first when needed and leaves the run paused.
8. **Resume the same conversation** — `orchestrator_resume` with `run_id`, then continue with `orchestrator_stage`. Resume only marks the paused run runnable; it does not execute a stage. Pending-stage preflight can still block resume and lists the exact actions; a completed paid role's exhausted grant is shown as deferred rather than blocking unrelated work. Finished lanes whose durable results await collection and exact integration checkpoints need no new grant; a pending approved fallback is preflighted against the route it will actually use, so an unused primary does not block it. Do not bypass the gate or start a parallel lane before its authority reservation succeeds.
9. **Attach from a new conversation** — `orchestrator_runs` to list recent runs, then `orchestrator_status` for the chosen `run_id`, then `orchestrator_resume` when the state is safe.
10. **Reconcile an uncertain run** — `orchestrator_reconcile` with `run_id`. It succeeds only when the unified containment gate proves the recorded session, launch record, job/run markers, check token, descendants and escaped processes are all stopped. It also discovers parallel lanes whose execution is uncertain even when the parent has no `active_job`/`active_check`; completed siblings and any pending scoped authorization are preserved. It clears the stale active job/check and disarms unrelated retry sessions; it fails closed when any marked survivor remains. Never retry before reconciliation. If no launch identity was ever persisted, the **user** must inspect the exact situation and run the CLI `reconcile RUN_ID --launch-missing --evidence '<inspection>'`; this writes an audited resolution and does not execute a model.
11. **Plan approval / consultation** — automatic progression is the default: a valid plan goes to implementation without an approval gate regardless of risk, complexity or writer count. Only an explicit user request for design consultation (`plan_approval: true` at start, or an explicit ask later) creates a gate; the user answers **in the controlling conversation**, and the coordinator records that exact reply with `orchestrator_consult` (`run_id`, `response`, optional `decision: "accept" | "amend"`). A material reply creates a versioned amended plan; accepting the unchanged proposal needs no separate terminal command. `approve-plan` remains a human-only CLI action for legacy/manual use and is never an MCP tool; `approve-fallback` and `authorize-route` are likewise human-only. A model cannot approve its own plan or authorize its own paid route.
12. **Configure models** — `orchestrator_models` (optional `run_id`) is the discoverable configure-models entry point; CLI: `orchestrator.py models [ID]`. It shows provider, model, effort/variant, billing, metadata availability and effective pins for Architect, Explorer, Implementer and Reviewer, distinguishes the host-managed conversation model from the dispatched Architect, and lists which architect hosts are configured. Changes reuse config validation, the run `routes` override, `switch-role` preview/apply and `authorize-route`; unsupported or paid routes are refused before dispatch.
13. **Inspect run-scoped check exceptions** — `orchestrator_check_exceptions` with `run_id` lists automatic/scoped exceptions bound to this run, checkout, plan revision and exact argv. They never change shared configuration or another saved run, and never authorize paid routes, destructive actions, credentials or external access.
14. **Resolve checkout ownership** — a `checkout_conflict` result or `orchestrator_status` conflict is not retried. Inspect `orchestrator_runs` and the CLI `checkout-status --project PATH`. An inactive conflicting run may be retired with `retire RUN_ID --reason ... --acknowledge ...`; an orphaned registry record may be cleared with `checkout-recover --project PATH --owner RUN_ID --reason ... --acknowledge ...`; a legacy run may be adopted with `adopt RUN_ID`. These are **user-executed CLI actions**, not MCP tools and not routine stage calls. The coordinator must show the exact command and wait; it must not claim to have performed a protected action. Sensitive CLI actions are disabled by default (`authorization.sensitive_cli_enabled: false`); the user must enable them in the local config. An initializing owner only gets retry/status guidance, never retirement or adoption advice.
15. **Cancel a run** — the MCP server exposes no cancel tool. Interrupt first with `orchestrator_interrupt` (or the host's Esc cancel) and verify `stopped: true`. Then, only with explicit user authorization and after enabling `authorization.sensitive_cli_enabled`, run `python3 <SKILL_DIR>/scripts/orchestrator.py cancel <ID>` in the native shell; it writes a cancellation control request that a running supervisor consumes. A paused run is preserved for audit, not deleted.

## The workflow

For every engineering task use this loop:

1. Call `orchestrator_start` with the absolute project path, precise goal, and explicit `host`.
2. Before each `orchestrator_stage` call, post one short line using the
   returned `next` preview. Use `orchestrator_status` to get it when attaching
   to an existing run.

   **14:32 · Architect / gpt-6.2-sol High · Review webhook retries · Expected verdict**

   Use the local time, role, effective model and effort, short task, and
   expected output. Include the batch when it distinguishes work. For a
   supervisor check, use its role and task without a model label. When
   `config_route_differs` is true, include the configured and effective routes.

3. Call `orchestrator_stage` once in the foreground. Then post one short line
   with the outcome, measured `elapsed_seconds`, and the next action (`next`
   or `next_action`). Include a reason if the run is blocked or paused.

   **Review complete · 32.9s · Next acceptance**

   **Paused · 32.9s · Check timed out · Next reconcile**

   Use a concise clause for each detail. Expand only when the user needs to
   decide or act. Keep one stage per call.

   At milestones, include the useful engineering fact, not just status. A
   Reviewer result includes finding counts and material findings with severity,
   location, impact and requested correction; if the preview is capped, say how
   many were omitted and use `orchestrator_recap detail=developer` for all
   findings. An Architect acceptance line starts with its actual **PASS**,
   **CHANGES REQUIRED** or **BLOCKED** verdict, gives the reason, and states what
   happens next. A completed Implementer is not verified tests: say verification
   is pending until the supervisor has run the checks.

   After each successful Implementer milestone, add the short developer summary
   the user requested, in addition to the ordinary before/after stage lines:
   what changed, how it works, one or two key paths or symbols, the Implementer's
   observed test notes attributed to the worker, and whether supervisor
   verification is still pending. Keep it concise; expand only on request.
4. Repeat `orchestrator_stage` while the recorded next action is runnable, without
   asking the user to continue. Handle normal corrections, replanning,
   verification and supported recoverable failures yourself; do not replay
   completed work. Keep a safely observable running stage monitored rather than
   ending the turn. Stop only for explicit pause/cancel, unresolved sensitive
   authorization, credentials/external access or an irreducible technical
   blocker, and report the exact recorded next action.

The status/recap payload includes a bounded `progression` view with
`automatic`, `consultation_required` and a recovery classification plus the
recorded next action. Follow it consistently from `stage`, `status` and `resume`
instead of reconstructing policy in chat.

Run-scoped routine-check exceptions are created by the supervisor for ordinary
non-destructive checks in the approved plan (for example
`python3 -m unittest ...`). They are bound to this run, checkout, plan revision
and exact argv, revalidate executable identities before use, and are visible via
`orchestrator_check_exceptions`. They never edit shared configuration, affect
another saved run, or authorize paid routes, destructive actions, deployment,
credentials or external access. Shell wrappers and arbitrary downloads are
never auto-excepted; use the human-only `authorize-check` in your own
interactive terminal when a narrow check genuinely needs it. The supervisor
refuses it from a model-owned worker context or without the exact typed
confirmation.

On completion, give the short final handback: delivered behavior, verification
evidence, Architect verdict, material limitations and the final run state.

The planning result and `orchestrator_status` carry a bounded `plan_view`:
revision and approval state, summary rationale, main invariants, and each shown
batch's title, goal, acceptance, risk and verification purpose. Omitted counts
and the recap/report reference point to the full durable plan. Raw check argv is
not part of the chat view.

Do not poll with a model; status and recap are deterministic. Do not select the legacy background mode in an interactive chat.

## Automatic progression and design consultation (opt-in)

Automatic progression is supervisor policy, not coordinator self-approval. A
valid plan proceeds to exploration/implementation without asking the user, and
risk, complexity and writer count never create an approval requirement. Do not
manufacture a consultation pause for an ordinary request to see the plan,
rationale or progress.

Use `plan_approval: true` only when the user explicitly asks for design
consultation before the plan is finalized, for example: “Ask me about
architecture and design choices before you finalize the plan.” The Architect may
then ask only about genuinely consequential ambiguity, and must not seek routine
confirmation.

With that opt-in, the strong Architect puts the proposed direction and concise
rationale in the plan `summary`, flags each consequential fork with its
trade-off and recommendation, and uses `blocker` only for a question that must
be answered before a valid plan can exist. Present the proposed plan and the
actual questions in chat. Then handle the user's reply **in the controlling
conversation**:

- A material answer or requirement change: record the exact reply with
  `orchestrator_consult` (`response`, `decision: "amend"`), which creates a
  versioned amended plan; then `orchestrator_resume` and `orchestrator_stage` to
  obtain it. The amendment carries the user's verbatim text.
- Acceptance of the unchanged proposal: record it with `orchestrator_consult`
  (`decision: "accept"`, or the default classification when it is unambiguous).
  No separate terminal command is required and the run becomes runnable.
- A stale reply (older plan revision or amendment epoch) is rejected; answer
  the current revision.

Consultation is separate from sensitive authorization. Chat discussion and
answers inform the plan but cannot grant paid-route, destructive-operation,
deployment, credential or external-access authority. Approval of an earlier plan
never authorizes a revision. An unapproved consultation-gated plan cannot start
a writer through `orchestrator_stage` or `orchestrator_resume`.

## Interruption, questions and amendment

If a foreground tool call is still running, the user must use the host's cancel/interrupt action (for example Esc in Codex). A queued chat message cannot preempt an already-running tool. The MCP server receives the host cancellation notification and performs the same verified stop; it then returns the safe state.

At any point the user may interrupt and ask:

- What happened?
- What did you implement?
- How does it work?
- Why was it implemented this way?
- Which files changed?
- What tests passed?
- What remains?

Answer from `orchestrator_status` and `orchestrator_recap`. Keep routine summaries short. Give a developer-level explanation with source references, test commands and technical reasoning only when the user asks how or why, or when the change is consequential. If something is not recorded, say so; never invent live worker state.

If work was active when the interruption happened:

1. Call `orchestrator_interrupt` with a short reason (unless the host already cancelled the tool call).
2. Report the returned termination status. Never claim a worker stopped unless the result says `stopped: true`.
3. Call `orchestrator_recap` with `detail: "quick"`.

Never blindly repeat previously completed work after an interruption. A verified stop leaves the run `paused`; use `orchestrator_resume` before the next stage. If termination is uncertain, call `orchestrator_reconcile` and do not launch a duplicate worker until it succeeds.

If the user changes requirements:

1. Call `orchestrator_amend` with the exact amendment.
2. Use `kind: "requirement"` (the default) when the change affects requirements, acceptance, architecture or risk; use `kind: "correction"` only for a bounded implementation detail.
3. Call `orchestrator_resume`, then continue with `orchestrator_stage`.
4. Never replay completed valid work. The supervisor preserves accepted batches, changed files, reports and checkpoints and invalidates only affected downstream evidence.

Recovery from a new chat: `orchestrator_runs` → `orchestrator_status` → `orchestrator_resume`.

## Recaps

- Default answer: `orchestrator_recap` with `detail: "quick"` (about 5–10 lines).
- For “how did you implement this?”, “why this design?”, “what tests?”, “what files?”: use `detail: "developer"`.
- Answer from the returned evidence. Cite files, test commands and log paths. If something is not recorded, say so. Do not generate generic explanations or spend a strong-model call on routine recaps.
- A difficult technical question that genuinely requires new reasoning may be escalated explicitly; routine status never is.

## Engineering principles

- Strong Architect owns difficult invariants, critical code inspection, conflict resolution and final acceptance. Cheap workers handle exploration, implementation and independent review. A serious Reviewer finding cannot be voted away by multiple cheap agents.
- The user's verbatim goal and amendments are handed once to Implementer and Reviewer as a `requirements` block, separate from the Architect's interpretation. A plan that omits a user requirement does not replace it.
- The fresh Reviewer receives the acceptance criteria, the observed batch delta index and the supervisor's independent check results through a digest-bound read-only projection inside the checkout. It does not receive the Implementer's conclusions.
- An explicit Implementer `needs_architect` goes straight to strong diagnosis with its question and evidence. A routine, attributable check failure gets at most one cheap retry before diagnosis. A clear new user requirement triggers a versioned strong replan and leaves nothing stale authorized.
- **Superpowers scoping:** inside an active orchestrator stage, do not use the `writing-plans`, `executing-plans` or `subagent-driven-development` skills: the supervisor already owns plans, sequencing and dispatch. Keep `systematic-debugging` for real failures and focused test-driven development for the behavior being changed. Brainstorming may precede an unsettled run. The standalone manual `abdullah-architect` and `abdullah-implementer` skills are unaffected and remain separate tools.
- Architect can synchronously dispatch and consume cheap Explorer findings during planning or diagnosis through `orchestrator.py explore`, only when the run's explicit `explorer_policy` permits it. Missing/legacy policy means no nested dispatch.
- No recursive supervisor dispatch: every dispatched worker is marked (`ABDULLAH_AGENT_CONTEXT`, and the Architect also `ABDULLAH_PARENT_JOB`), and `create_run` refuses to start another run from that context before reading config or writing state. Only the controlling host conversation creates runs; a worker that needs more work returns its report instead.
- Risk-based QA: one fresh Reviewer for ordinary behavior, targeted finding verification when useful, no fixed jury, no endless debate.
- Supervisor runs the approved checks and records the actual worktree fingerprint and Docker source identity. Never accept a green run against a stale or unrelated checkout.
- Size handoffs comfortably for worker contexts. New workers for batches and substantial corrections; coherent briefs, bounded retries, no context-rot loops.
- Optimize quota: strong calls only for planning, consequential diagnosis and acceptance/amendment reassessment—not heartbeats, log transport, routine recaps or repeated completed phases.
- **Fallbacks require explicit approval**: after a genuine rate limit or model blocker, ask the user before one Codex Luna / Claude Haiku dispatch. There is no automatic fallback; approval covers one attempt only. Fallback consent belongs to the parent run: a parallel lane never copies or spends it, an admitted transaction resolves containment and the pinned primary first, and any lane-to-single switch is an explicit parent-owned recovery transition.
- Trusted *development* mode allows local Docker/test commands and local `.env` edits unattended; never implicitly push/deploy, operate on production, or perform broad destructive actions.
- **Tool routing (hybrid)**: use LeanCTX MCP (`ctx_read`, `ctx_search`, `ctx_tree`, `ctx_compose`) for reading/search/context; run Python, tests, Docker, Git, `orchestrator.py`, and Explorer dispatch through the native shell. Never route execution through `ctx_shell`.
- The optional read-only observer `python3 <SKILL_DIR>/scripts/orchestrator.py status --run <ID> --follow` shows the next stage before dispatch, ticks elapsed time and observed activity, then shows the outcome, measured time and next action. The normal chat workflow uses the stage announcement and result above.

## CLI fallback

The MCP tools are the primary interface. The same durable operations remain available if MCP is unavailable:

```bash
python3 <SKILL_DIR>/scripts/orchestrator.py stage <ID>
python3 <SKILL_DIR>/scripts/orchestrator.py status <ID>
python3 <SKILL_DIR>/scripts/orchestrator.py status --run <ID> --follow   # read-only live observer
python3 <SKILL_DIR>/scripts/orchestrator.py models [ID]                  # configure-models view
python3 <SKILL_DIR>/scripts/orchestrator.py consult <ID> --response "..." [--decision amend|accept]
python3 <SKILL_DIR>/scripts/orchestrator.py check-exceptions <ID>
python3 <SKILL_DIR>/scripts/orchestrator.py authorize-check <ID> --argv '["python3","-m","unittest"]' --reason "..." --authorized-by "operator" --confirm check-exception:<ID>:<sha12>
python3 <SKILL_DIR>/scripts/orchestrator.py recap <ID> --detail developer
python3 <SKILL_DIR>/scripts/orchestrator.py interrupt <ID> --reason "user stop"
python3 <SKILL_DIR>/scripts/orchestrator.py amend <ID> --text "requirement change" --architect-review
python3 <SKILL_DIR>/scripts/orchestrator.py resume <ID>
python3 <SKILL_DIR>/scripts/orchestrator.py reconcile <ID>
python3 <SKILL_DIR>/scripts/orchestrator.py runs
python3 <SKILL_DIR>/scripts/orchestrator.py pause <ID>
python3 <SKILL_DIR>/scripts/orchestrator.py cancel <ID>
```

**Danger: the CLI `start` command is not state-only.** Unlike the MCP
`orchestrator_start` tool, `orchestrator.py start` creates the run and then runs
the supervisor loop in the foreground when `--background` is absent, dispatching
real workers immediately:

```bash
# This dispatches real models as soon as it starts:
python3 <SKILL_DIR>/scripts/orchestrator.py start \
  --project <ABSOLUTE_PROJECT> --goal-file <GOAL_FILE> --host codex
```

Use the MCP `orchestrator_start` tool (state only) for the interactive workflow.
Only an operator who explicitly wants the legacy supervised loop should run the
CLI form, and `--background` detaches it instead. This distinction caused a real
incident during the 2026-11-16 E2E run: a timeout-bounded foreground `start`
dispatched plan and implement before being interrupted. The supervisor contained
it correctly, but quota was spent without intent.

`pause` and `cancel` write control requests consumed by a running supervisor;
they are not substitutes for a verified `interrupt`.

All run commands accept either a positional `<ID>` or `--run <ID>`, never both. For example `resume <ID>` and `resume --run <ID>` are equivalent.

## Model configuration

One discoverable entry point shows every role: MCP `orchestrator_models`
(optional `run_id`) or CLI `python3 <SKILL_DIR>/scripts/orchestrator.py models
[ID]`. It distinguishes the **host-managed conversation model** from the
**dispatched Architect**, and reports provider, model, supported effort/variant,
billing route, metadata availability and effective pins for Architect, Explorer,
Implementer and Reviewer. `architect_hosts` shows which of `codex`, `claude` and
`antigravity` are configured; an unconfigured Antigravity entry is a normal
state for existing installations.

All model routes are read from `~/.config/abdullah-orchestrator/config.json` (or `ABDULLAH_CONFIG`) on every operation:

- **Architect** — `architect.codex`, `architect.claude` and (opt-in) `architect.antigravity` select the model and effort for each host. The shipped default is `gpt-6.2-sol` at `high` for Codex and `claude-opus-5-5` at `high` for Claude. The value is passed through unchanged, so confirm it against the installed host catalogue; keep `auth: "subscription"` unless the user authorized another explicit billing route. Final Architect acceptance always uses the High route, including after an ordinary Medium planning trial; an Antigravity default below High is refused.
- **Workers** — `workers.explorer`, `workers.implementer` and `workers.reviewer` select a fully qualified `provider/model` ID, an optional `provider` (must match the prefix), `variant`, and `billing`. The default remains `opencode-go/...` with `billing: "go"`. Non-Go routes (`subscription`, `api`, `free`, `local`) require an explicit human `authorize-route` grant bound to the role, run and exact route; a route-scoped fallback needs separate one-dispatch consent.
- **Discovery** — `opencode models --verbose` (V1, includes variants) or `opencode models` (V2, IDs only), then `python3 scripts/orchestrator.py doctor --project <abs>` to confirm `route_models_listed`, `variant_verified`, `billing_preflight`, `provider_availability` and resolved routes.

Three safe operations: change **defaults** for future runs with the validated,
backup-first CLI `set-default --role ROLE --route JSON` (preview; add `--apply`
and its `--confirm`, plus `--accept-billing-change` for a billing change) —
existing run pins are untouched and existing evidence stays valid; override
routes for **one new run** via `orchestrator_start` `routes` or `start
--routes`; change a role at an **existing safe boundary** with the existing
`switch-role` preview/apply plus `--confirm`. A stale preview, an active-stage
switch, an unsupported selection or an unauthorized provider/billing change is
rejected. `set-default` is human-only and refuses a model-owned worker context.

Worker routes are pinned at creation with a redacted provider/config fingerprint. The supervisor never silently switches provider, model, variant or billing, and never claims a dollar cap. Do not edit the config on the user's behalf or bypass validation. Configuration is user-owned: show exact values and ask before changing it. Set routes before `orchestrator_start`; editing the config mid-run marks the run `config_changed` and blocks further stages. A new run requires an explicit `host: "codex"` or `"claude"`. Full reference: `docs/configuration.md`.
