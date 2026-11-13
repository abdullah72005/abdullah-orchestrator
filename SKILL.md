---
name: abdullah-orchestrator
description: Run or resume Abdullah's durable, quota-aware software engineering workflow from one interactive Codex or Claude conversation. Dispatches a strong Architect plus OpenCode Go Explorer, Implementer and independent Reviewer as visible foreground MCP calls, with safe interruption, evidence-backed recaps, deterministic recovery and recoverable checkpoints.
---

# Abdullah Orchestrator

One interactive conversation is the coordinator. The visible model (Luna Medium in Codex) talks to the user and invokes a bundled Python MCP supervisor. The supervisor owns execution state, process lifecycle, checkpoints, verification and recovery; a separate strong Architect (Sol High in Codex) makes consequential decisions. The **original** `abdullah-architect` and `abdullah-implementer` remain untouched.

## Default mode: one interactive foreground conversation

Interactive foreground mode is the default. The user opens **one Codex CLI chat** with Luna Medium as the visible coordinator, invokes `$abdullah-orchestrator`, and stays in that same conversation.

- The strong Architect remains a separate Sol High worker; the Python supervisor remains deterministic.
- Every engineering stage is one visible foreground MCP invocation.
- Before dispatch, the coordinator announces the worker, its task and the expected output in a compact message.
- Codex renders the tool call, its native running-tool indicator and elapsed time.
- When the call returns, the coordinator summarizes only the structured result and the next stage.
- The coordinator proceeds to the next stage within the same conversation.

Stock Codex does not render an external worker's internal progress, private reasoning, intermediate shell commands or MCP progress notifications continuously. Do not promise that visibility, and do not patch the Codex TUI to fake it.

Legacy detached `start --background` mode is optional, is **not** the default, and must not be selected without the user's explicit authorization. It survives closing a chat only while WSL stays awake; a sleeping host cannot execute jobs.

## Setup

1. Read [operations](references/operation.md), [roles](references/roles.md) and [report contracts](references/contracts.md).
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

   Do not apply this timeout globally. Codex's 300-second default is too short for a legitimate Architect, Implementer or Reviewer stage. Five hours deliberately exceeds the supervisor's four-hour worker, Architect and verification caps so the host cannot race the supervisor at the boundary; it is a communication upper bound, not a stuck-worker detector.
5. Restart Codex, open **one** chat with Luna Medium, and invoke `$abdullah-orchestrator`.

The runtime selects OpenCode V1 or V2 configuration based on the installed CLI version, supports the tested ranges `>=1.18 <2.0` and `>=2.2 <3.0`, and rejects untested versions. It never silently switches from paid Go to free models or from subscription auth to billed API credentials.

## Operations

Use the MCP tools below. Every tool except `orchestrator_start` and `orchestrator_runs` takes `run_id`. Do not invent tool names or bypass these operations with ad-hoc supervisor commands.

1. **Start a run** — `orchestrator_start` with the absolute `project` and a precise `goal`. Optional arguments: `host` (`codex`|`claude`), `plan_approval`, `require_explorer`, `allow_explorer`, `explorer_policy` (`none`|`on_demand`|`required`), `approved_handoff` plus `authorize_handoff`, `skip_doctor`. New and legacy runs default to `explorer_policy=none` unless permission is explicit. It creates durable state and does **not** dispatch a worker.
2. **Execute one stage** — `orchestrator_stage` with `run_id`. It runs exactly one of plan, explore, implement, verify, review, accept, diagnose or integrate. Announce the agent, task and expected output first. Never hide several stages in one call.
3. **Inspect status** — `orchestrator_status` with `run_id`. Deterministic compact status, active job/check, next action and run directory; makes no model call.
4. **Interrupt or pause** — `orchestrator_interrupt` with `run_id` and a short `reason`. Persists the interruption, terminates the process session and descendants, verifies termination and preserves changes. A verified stop leaves `paused`; an unverified stop leaves `uncertain`.
5. **Quick recap** — `orchestrator_recap` with `detail: "quick"` (the default). About 5–12 lines covering phase/agent, completed work, changed files, verification, decisions, outstanding issues and next action.
6. **Detailed developer explanation** — `orchestrator_recap` with `detail: "developer"`. What was implemented, how it works, why that approach was chosen, important files/symbols, actual test commands and results, and remaining limitations. Makes no model call.
7. **Amend requirements** — `orchestrator_amend` with `amendment` (exact text), `kind` and `architect_review`. `kind` defaults to `requirement`, which replans and invalidates affected evidence; use `kind: "correction"` only for a bounded implementation detail. It interrupts active work first when needed and leaves the run paused.
8. **Resume the same conversation** — `orchestrator_resume` with `run_id`, then continue with `orchestrator_stage`. Resume only marks the paused run runnable; it does not execute a stage.
9. **Attach from a new conversation** — `orchestrator_runs` to list recent runs, then `orchestrator_status` for the chosen `run_id`, then `orchestrator_resume` when the state is safe.
10. **Reconcile an uncertain run** — `orchestrator_reconcile` with `run_id`. It succeeds only when the unified containment gate proves the recorded session, launch record, job/run markers, check token, descendants and escaped processes are all stopped. It clears the stale active job/check and disarms unrelated retry sessions; it fails closed when any marked survivor remains. Never retry before reconciliation. If no launch identity was ever persisted, the **user** must inspect the exact situation and run the CLI `reconcile RUN_ID --launch-missing --evidence '<inspection>'`; this writes an audited resolution and does not execute a model.
11. **Plan approval or authorized fallback** — these are human-only actions and are **not** MCP tools. Ask the user to run `orchestrator.py approve-plan <ID> --confirm approve-plan:<ID>` or `approve-fallback <ID> --role <role> --confirm approve-fallback:<ID>` in their own interactive terminal. A model cannot approve its own plan or authorize its own fallback.
12. **Resolve checkout ownership** — a `checkout_conflict` result or `orchestrator_status` conflict is not retried. Inspect `orchestrator_runs` and the CLI `checkout-status --project PATH`. An inactive conflicting run may be retired with `retire RUN_ID --reason ... --acknowledge ...`; an orphaned registry record may be cleared with `checkout-recover --project PATH --owner RUN_ID --reason ... --acknowledge ...`; a legacy run may be adopted with `adopt RUN_ID`. These are **user-executed CLI actions**, not MCP tools and not routine stage calls. The coordinator must show the exact command and wait; it must not claim to have performed a protected action. Sensitive CLI actions are disabled by default (`authorization.sensitive_cli_enabled: false`); the user must enable them in the local config. An initializing owner only gets retry/status guidance, never retirement or adoption advice.
13. **Cancel a run** — the MCP server exposes no cancel tool. Interrupt first with `orchestrator_interrupt` (or the host's Esc cancel) and verify `stopped: true`. Then, only with explicit user authorization and after enabling `authorization.sensitive_cli_enabled`, run `python3 <SKILL_DIR>/scripts/orchestrator.py cancel <ID>` in the native shell; it writes a cancellation control request that a running supervisor consumes. A paused run is preserved for audit, not deleted.

## The workflow

For every engineering task use this loop:

1. Call `orchestrator_start` with the absolute project path and precise goal.
2. Call `orchestrator_stage` once per stage. Announce first, in a compact message, exactly what the user's example shows:

   **Starting Architect — Sol High**
   - Task: inspect the project and design the plan.
   - Expected output: invariants, batches, acceptance criteria and check argv.

3. `orchestrator_stage` is one foreground tool call. Codex shows its native running-tool indicator and elapsed time; when it returns, report only the compact result and the next stage. Never hide several stages inside one call.
4. Repeat `orchestrator_stage` until the run is complete, paused, blocked or uncertain.

Do not poll with a model; status and recap are deterministic. Do not select the legacy background mode in an interactive chat.

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
- Architect can synchronously dispatch and consume cheap Explorer findings during planning or diagnosis through `orchestrator.py explore`, only when the run's explicit `explorer_policy` permits it. Missing/legacy policy means no nested dispatch.
- Risk-based QA: one fresh Reviewer for ordinary behavior, targeted finding verification when useful, no fixed jury, no endless debate.
- Supervisor runs the approved checks and records the actual worktree fingerprint and Docker source identity. Never accept a green run against a stale or unrelated checkout.
- Size handoffs comfortably for worker contexts. New workers for batches and substantial corrections; coherent briefs, bounded retries, no context-rot loops.
- Optimize quota: strong calls only for planning, consequential diagnosis and acceptance/amendment reassessment—not heartbeats, log transport, routine recaps or repeated completed phases.
- **Fallbacks require explicit approval**: after a genuine rate limit or model blocker, ask the user before one Codex Luna / Claude Haiku dispatch. There is no automatic fallback; approval covers one attempt only.
- Trusted *development* mode allows local Docker/test commands and local `.env` edits unattended; never implicitly push/deploy, operate on production, or perform broad destructive actions.
- **Tool routing (hybrid)**: use LeanCTX MCP (`ctx_read`, `ctx_search`, `ctx_tree`, `ctx_compose`) for reading/search/context; run Python, tests, Docker, Git, `orchestrator.py`, and Explorer dispatch through the native shell. Never route execution through `ctx_shell`.
- A worker process is not a terminal UI. Codex displays the tool call, its running indicator, elapsed time and returned result, not the worker's private reasoning or MCP progress notifications. Do not patch Codex's TUI to fake that visibility.

## CLI fallback

The MCP tools are the primary interface. The same durable operations remain available if MCP is unavailable:

```bash
python3 <SKILL_DIR>/scripts/orchestrator.py start --project <PROJECT> --goal-file <GOAL_FILE> --host codex
python3 <SKILL_DIR>/scripts/orchestrator.py stage <ID>
python3 <SKILL_DIR>/scripts/orchestrator.py status <ID>
python3 <SKILL_DIR>/scripts/orchestrator.py recap <ID> --detail developer
python3 <SKILL_DIR>/scripts/orchestrator.py interrupt <ID> --reason "user stop"
python3 <SKILL_DIR>/scripts/orchestrator.py amend <ID> --text "requirement change" --architect-review
python3 <SKILL_DIR>/scripts/orchestrator.py resume <ID>
python3 <SKILL_DIR>/scripts/orchestrator.py reconcile <ID>
python3 <SKILL_DIR>/scripts/orchestrator.py runs
python3 <SKILL_DIR>/scripts/orchestrator.py pause <ID>
python3 <SKILL_DIR>/scripts/orchestrator.py cancel <ID>
```

`start --background` is the optional detached legacy mode described above; omit it for the interactive workflow. `pause` and `cancel` write control requests consumed by a running supervisor; they are not substitutes for a verified `interrupt`.

All run commands accept either a positional `<ID>` or `--run <ID>`, never both. For example `resume <ID>` and `resume --run <ID>` are equivalent.

## Model configuration

All model routes are read from `~/.config/abdullah-orchestrator/config.json` (or `ABDULLAH_CONFIG`) on every operation:

- **Architect** — `architect.codex` and `architect.claude` select the model and effort for each host. The value is passed through unchanged, so confirm it against the installed Codex/Claude catalog; keep `auth: "subscription"`.
- **Workers** — `workers.explorer`, `workers.implementer` and `workers.reviewer` select `model` and `variant`. The model must be an `opencode-go/...` ID with `billing: "go"`; variant selects the reasoning effort. Different roles may use different Go models.
- **Discovery** — `opencode models opencode-go --verbose` (V1, includes variants) or `opencode models` (V2, IDs only), then `python3 scripts/orchestrator.py doctor --project <abs>` to confirm `paid_go_model_listed`, `variant_verified` and resolved routes.

Worker **providers** are fixed to paid OpenCode Go in 3.0.0: any other billing value or model prefix is rejected rather than silently moving work to API billing. Do not claim otherwise, do not edit the config on the user's behalf, and do not bypass validation. Configuration is user-owned: show exact values and ask before changing it. Set routes before `orchestrator_start`; editing the config mid-run marks the run `config_changed` and blocks further stages. Full reference: `docs/configuration.md`.
