# Structured handoffs

Every model must emit one standalone **JSON object** in the final response; process exit, report validity, evidence and acceptance are distinct.

Emit valid JSON: escape double quotes inside string values; no trailing commas or comments.

## Plan
`{"contract_version":2,"status":"complete|blocked","summary":"...","invariants":["..."],"batches":[{"title":"...","goal":"...","acceptance":["..."],"checks":[["pytest","-q"]],"risk":"mechanical|ordinary|high","verification_purpose":null}],"blocker":"..."}`

Contract v2 requires a nonempty invariant list and nonempty acceptance criteria per batch. Reports without `contract_version: 2` are accepted only as marked legacy evidence. Checks remain argv arrays; wrappers, interpreter code strings and indirect Docker execution are recorded by the supervisor command policy.

`verification_purpose` is part of the batch schema and is always emitted: a specific, nonempty description of what the checks prove for `"risk":"high"` batches, and `null` otherwise. The supervisor rejects a high-risk batch whose purpose is missing, empty or null; a non-high-risk batch may leave it null.

When required exploration is in scope, include `"required_exploration":{"job_id":"...","scope_satisfied":true}` only if the Architect dispatched and consumed that Explorer and it covers the required scope; otherwise use an empty job_id and false.

Each batch should be inspectable and coherent, not split by arbitrary file counts. Checks must be argv arrays (no implicit shell interpolation), with negative behavior cases where appropriate. A batch without verifiable required checks cannot receive unattended acceptance.

## Worker
`{"contract_version":2,"status":"complete|blocked|needs_architect","summary":"...","files":["..."],"tests":["..."],"evidence":["path:symbol"],"unknowns":["..."],"blocker":"..."}`

Contract v2 requires `files`, `tests`, `evidence`, `unknowns` and `blocker`, with nonempty evidence for a completed Implementer. Legacy reports are retained but marked with their contract version and are not treated as newly attested evidence.

For a Reviewer the canonical output is the Worker object above with `status`, `summary`, `files`, `tests`, `evidence`, `unknowns`, `blocker`, and `findings`. `status` describes completion of the review, not an approval verdict. Report actual evidence and limitations; never invent them. Reviewer supplies `"findings":[{"severity":"critical|high|medium|low","location":"path:line","claim":"...","evidence":"...","confidence":"confirmed|probable|uncertain","disposition":"..."}]`. Findings require an explicit disposition. Worker reports cannot override acceptance criteria or authorized verification commands.

## Strong verdict
`{"contract_version":2,"verdict":"approved|changes_required|blocked","reason":"...","inspected":["path:symbol"],"correction":"...","dismissed_findings":[{"location":"path:line","claim":"exact finding claim","reason":"specific direct code evidence for why it is not a defect"}]}`

`contract_version` is mandatory for every newly dispatched report, including the Architect decision. The generated output schema declares and requires it; omitting it is a supervisor/schema defect, not an acceptable legacy report, and is rejected before acceptance.

Approvals require direct examination of behavior, tests and high-risk boundaries, matching git state and supervisor-issued tests. Confirmed high/critical findings require correction or an explicit evidence-based strong disposition using the exact location and claim (never majority voting). A changes-required verdict creates a bounded new correction wave; never silently reset the wave count on compaction.

## Provenance and recovery
Every attempt: unique job ID, model/billing route, source checkout, git HEAD, dirty snapshot, bounded runtime-input manifest, environment/config/toolchain identity, logs, child session ID if available, execution outcome, parsed report and separate verification evidence. Persist dispatch **before** launching. An uncertain write attempt must be reconciled by examining exact session and workspace before any retry. Never promise exactly-once execution.

Verification evidence is versioned (`evidence_version: 2`). It records the source snapshot, runtime input manifest, environment/config hashes and toolchain identity. A truncated or unattested required-input manifest blocks verification. Docker Compose evidence records service, image/build context, bind mounts, working directory, user and environment-variable names (never values). Historical evidence without these fields is marked `legacy_evidence: true`; it is preserved but is not equivalent to newly attested evidence and cannot reach acceptance without re-verification or the audited CLI `acknowledge-legacy-evidence` operator action.

## Tool routing (hybrid)
Use LeanCTX MCP (`ctx_read`, `ctx_search`, `ctx_tree`, `ctx_compose`, `ctx_*`) only for reading, searching and context retrieval. Run Python, tests, Docker/Compose, Git and `orchestrator.py explore` through the host's native shell. Never use `ctx_shell` or `lean-ctx -c` for execution. Never retry through another tool after an explicit LeanCTX security denial; surface it.

## Interactive stage result (MCP `orchestrator_stage`)
`{"ok":true|false,"run_id":"...","stage":"plan|explore|implement|verify|review|accept|diagnose|integrate","agent":"architect|explorer|implementer|reviewer|null","agent_label":"Architect — Sol High","task":"...","expected":"...","status":"running|paused|blocked|uncertain|complete|awaiting_plan_approval","phase":"...","elapsed_seconds":12.3,"summary":"compact one line","report":{...bounded role report...},"error":null,"pause_reason":null,"progress_line":"✓ Implementer | ...","next_action":"orchestrator_stage|orchestrator_resume|orchestrator_reconcile|...","next":{...preview...}}`

`report` is bounded: lists are truncated; never paste full logs or an entire plan into chat. One call executes exactly one stage. `ok` describes whether the tool completed, not whether the Architect approved the work; inspect `status` and the role verdict.

## Recap contract (MCP `orchestrator_recap`)
`{"ok":true,"run_id":"...","detail":"quick|developer","current":true|false,"text":"...","next_action":"...","facts":{...}}`

- `quick`: at most ~12 lines covering phase/agent, completed work, changed files, verification, decisions, outstanding issues and next action.
- `developer`: what was implemented, how it works, why the approach was chosen, important files/symbols, architectural decisions, actual test commands/results, and remaining limitations.
- A recap is deterministic and makes no model call. It is grounded in dispatch reports, the journal, checkpoints, diffs and verification evidence. `current:false` means an execution identity is uncertain; never present it as live state.
- Never claim an LLM's internal reasoning position was restored.

## Interruption and reconciliation contract
`orchestrator_interrupt` returns the persisted reason, the interruption record and termination results (`stopped`, remaining PIDs, method). Only `stopped:true` authorizes a duplicate retry. A verified stop leaves a resumable `paused` state; otherwise the run is `uncertain` and requires `orchestrator_reconcile`.

`orchestrator_reconcile` succeeds only when the recorded session/process tree is proven stopped. It clears `active_job`/`active_check`, records the reconciled attempt, and disarms any stale `retry_session` unless it belongs to the exact reconciled rate-limited attempt. A session must never be reused merely because it was saved.

Every guarded dispatch writes a durable `launch.json` before the child starts. If no launch identity was persisted, normal reconciliation refuses to guess; the operator may inspect the exact environment and use `reconcile RUN_ID --launch-missing --evidence '<inspection>'`, which records an audited resolution and does not execute a model.

Checkout ownership is distinct from worker termination. `retire RUN_ID --reason ... --acknowledge ...` is administrative abandonment of an inactive run; it preserves reports/checkpoints, refuses live or uncertain execution, and records the operator and evidence. `checkout-recover` clears only an orphaned/stale registry record with the same evidence discipline. Neither command proves that an old worker terminated unless the record explicitly contains termination evidence.
