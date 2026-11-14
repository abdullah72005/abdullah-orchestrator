# Orchestrator v3.1 — Single implementation batch: complete remediation and multi-provider campaign

Status: APPROVED FOR IMPLEMENTATION by Abdullah in chat on 2026-11-13. Abdullah approved the design and subsequently requested ALL campaign work in ONE batch. Execute all workstreams below through the original manual abdullah-implementer workflow, then return for one independent Architect review. Do not stop between workstreams for routine approval.
Baseline: branch `design/orchestrator-v3-1`, commit `1b8e10e5c1b2c08a236b68450cb5b2a1a610416d`.
Working directory: `/home/abdullah/.local/src/abdullah-orchestrator-v3-1`.
Authority: user's complete v3.1 campaign requirements and supplied independent audit; architecture.md in this directory. User requirements win on conflict. This file supersedes the earlier acceptance-only brief and five-batch execution structure. campaign-plan.md is an index, not an additional approval gate.

## Outcome and exclusions

Deliver the complete v3.1 candidate: close AOR-01 through AOR-07, implement per-role configurable OpenCode providers/models with billing safeguards and saved-run compatibility, and complete cross-cutting regressions, documentation and independent-audit preparation. Preserve the existing supervisor architecture and report contract v2. Exclude native Codex/Claude worker backends, broad rewrites, unrelated features, live paid calls, installation and release publication.

## Required finding coverage

| Finding | Required outcome | Internal workstream |
|---|---|---|
| AOR-01 | Full post-Architect verification provenance and decision binding | 1 |
| AOR-02 | Preserved source and blocked unauthorized stage mutation | 1 |
| AOR-03 | Idempotent user-scoped Claude MCP registration and rollback tests | 3 |
| AOR-04 | Explicit host, durable identity and route reporting | 2 |
| AOR-05 | Shared Claude provider/billing hazard preflight and Doctor checks | 2 |
| AOR-06 | Foreground host setup, stage deadline, cancellation and recovery | 3 |
| AOR-07 | Durable preflight rejection with no phantom active dispatch | 2 |
| Multi-provider | Configurable per-role OpenCode routes, consent, migration and Doctor | 4 |
| Final integration | Full regressions, documentation, closure matrices and auditor handoff | 5 |

## Execution contract for the whole batch

Work only in `/home/abdullah/.local/src/abdullah-orchestrator-v3-1`, branch `design/orchestrator-v3-1`, initial base `1b8e10e5c1b2c08a236b68450cb5b2a1a610416d`. All workstreams share this recorded baseline; internal commits do not require intermediate Architect acceptance. Inspect actual baseline/status before edits; preserve uncommitted handoff files and user changes. A mismatch requires reporting, not reset. Single Implementer preferred because supervisor/config changes overlap. Local cohesive commits required for implementation only. Preserve these handoff documents; do not automatically include them in implementation commits.

Allowed within this approved batch: source/test/doc changes explicitly scoped below, disposable tests, local commits. Forbidden: push/merge/tag/release/install, automated Abdullah Orchestrator, live model calls (including Doctor inference), credential/global config edits, existing run mutations, installed orchestrator changes, original Architect/Implementer skill edits, Sanatry/unrelated projects, destructive Git. Do not relax current security/acceptance checks. Escalate material design deviations. Tests must isolate HOME, config, state and checkout registry in disposable directories; no paid network calls. TDD on behavior using real records/fake executables, not function-name assertions.

Run targeted checks after each affected workstream and the full offline suite after the integrity, dispatch/Claude, and provider milestones, plus final integration, as required by the original campaign. These are verification milestones, not approval gates:

```
python3 -m compileall -q scripts
python3 -m unittest discover -s scripts/tests -v
```

Record interpreter, actual counts/skips/exit code, command output location and code HEAD. Run broader checks again only after material subsequent changes. CI compatibility Python 3.10/3.12/3.13; do not claim unavailable local interpreters were tested. Preserve existing optional V2 introspection tests, report their skips separately.

Every Implementer returns a copyable chat report: batch/path/status; baseline/branch/HEAD; all commits and full changed-file list; clean/dirty/untracked state; requirement→code/test matrix; failing-before/passing-after evidence; exact verification commands/results/time/skips; preserved source/artifacts; compatibility/security/billing assessment; deviations/limitations; unresolved decisions. This is evidence for review, not approval. Architect examines entire batch diff and relevant actual tests before a disposition.


## Workstream 1 — Acceptance integrity and source-stage contracts

Complete this correctness work first, then proceed directly to Workstreams 2–5. The locations and invariants below describe this workstream; the remaining workstreams extend the final deliverable.

### Source locations and existing contracts

`scripts/orchestrator.py`: source_snapshot/signature, provenance_drift, load_verification_evidence, verification_evidence_package; call_model; strong_call; cached_job_report/cached_recovered_job_report/recover_report/recover_finished_dispatch; advance plan/diagnose/review/explore/accept/integrate; migrate_run only if needed to prevent cache bypass. STAGES and existing job records already describe roles; dispatch.json.source and completion.json.final_snapshot exist. Report contract v2 remains unchanged.

Tests to consult: test_checkpoint_b_provenance.py, test_delta_audit_corrections.py ToolchainRefreshTests, test_decision_contract_regressions.py AcceptanceTransition, test_checkpoint_d_efficiency.py, test_interactive_recovery.py, test_report_ingestion.py. Prefer new `scripts/tests/test_v31_acceptance_integrity.py` and `test_v31_stage_invariants.py` to keep this batch reviewable; update old fixtures only when their evidence shortcuts violate the strengthened contract.

### Decisions and invariants

- Reuse existing snapshot/evidence validators; add small common helpers rather than duplicate accept/integrate logic. Fresh snapshots include runtime declarations, environment, configuration and toolchain; additionally compare check_toolchain_identity for the actual approved argv.
- At accept before accepted_batches/batch_index mutation and at every complete branch, validate the exact supervisor-issued verification reference(s) after the Architect returns. Single fast path validates original batch and final checks; integrate validates its final record. Bind to current plan content/hash/revision, not just a nullable string. Reject missing modern evidence/provenance/check-tool binding for new completion. Historical data remains readable; it cannot bypass fresh attestation via legacy acknowledgement.
- Capture an acceptance binding before Architect dispatch: source identity, current plan identity, evidence reference plus SHA256 of evidence bytes (batch and final when applicable). Recompute after return and on cache/recovery consumption. An approval for an older record must not become usable after new checks produce another record, even if candidate unchanged. Add optional metadata to durable job/decision artifacts, keeping model report unchanged. Old jobs without sufficient binding cannot approve new transitions; preserve and invalidate/recompute safely.
- A stale decision is not consumed as valid, accepted, or complete. Preserve its artifacts with invalidation reason. Non-source drift clears verification eligibility/review/check_progress/single_batch_verification as applicable and routes batch to verify; integration clears check progress and reruns integration checks, then obtains a fresh decision. Config/plan inconsistencies must respect existing compatibility/replan gates; never silently mutate the approved plan. No stale cached report may be reused after invalidation.
- All non-writer kinds (plan, diagnose, decision, integration, explorer, reviewer) compare dispatch source to completion and before consuming recovered reports. Only Implementer edits source. Compare source identity excluding irrelevant volatile provenance; preserve runtime checks independently. A valid report does not excuse edits. No source-write exception in this campaign; legitimate corrections go through Implementer.
- Read-only mutation blocks and preserves source, reports, snapshots and minimal path/hash diagnostics. Use uncertain only if execution containment remains unproven, otherwise blocked. No rollback/reset/clean/revert. A dirty baseline unchanged across stage is valid. Detect tracked modifications/deletion, untracked creation/edit/delete, staged content/index changes and HEAD changes; ignored runtime inputs retain existing declarations/provenance behavior. Do not invent a guarantee for all arbitrary ignored files or transient edits reverted before observation.
- Enforce failure paths too: mutation plus invalid report/nonzero exit must not silently retry planning on the modified tree. Cached/recovered reports must compare original dispatch to completion, not just completion to now. Missing historical integrity metadata fails closed for progression and preserves diagnostics.
- Keep leases, process containment, journal, cancellation, independent Reviewer isolation, report ingestion and correction quotas intact. Source checks are application acceptance gates, not OS write prevention.

### Implementation sequence

1. Confirm baseline/branch/status and isolate all test config/state/registry paths using existing ControlTests conventions. Preserve the uncommitted planning files.
2. Add adversarial failing regression tests using real temporary Git repositories, real run_checks records, fake check executables and fake Architect responses. Prove the late-drift defects fail on baseline for single, intermediate and multi-batch final acceptance. Do not mock the evidence validator to green or merely assert a helper is called.
3. Implement common acceptance binding/revalidation and durable decision invalidation. Cover crashes before/after decision completion and fresh/cached/recovered report paths. Require newly recorded evidence and plan identities; adapt test fixtures using actual records. Keep rejected artifacts inspectable.
4. Add and implement source-stage invariants at dispatch/consumption boundaries, including malformed reports, nonzero exit and process cleanup paths. Extend prompts only if useful; deterministic checks are authoritative. Validate directly through stage_run and at least one guarded fake-CLI path rather than testing only helpers.
5. Add brief behavior/recovery documentation in references/contracts.md and docs/security-model.md or operation.md where appropriate. Explicitly describe blocked mutation vs stale verification, preserved work and legacy decision limitations.
6. Run focused tests and the offline suite below. Inspect full diff for weakened checks or unrelated edits. Commit coherent implementation changes locally; leave drafts uncommitted unless Abdullah separately authorizes including them.

### Executable acceptance matrix

- [ ] Actual temporary PATH executable is rewritten in place during strong approval after successful real verification. Single fast path, intermediate batch acceptance and multi-batch integrate cannot accept; diagnostics identify toolchain/check executable drift. Include a named check executable outside the small generic toolchain list.
- [ ] Parameterized late drift: allowlisted environment value, config bytes, runtime declaration/file, plan content/version, candidate tracked/staged/untracked source. None reaches complete or appends a stale accepted batch.
- [ ] Cached and report-recovered decisions: drift before reuse; replacement of evidence file/bytes; fresh checks for same source; changed plan; missing decision binding. Old approval never authorizes new evidence. Unchanged correctly bound crash recovery works without duplicate model call.
- [ ] After drift, approved checks genuinely execute again; new review/decision is required as applicable; stale check_progress and decisions cannot short-circuit this. Multi-batch integration rechecks combined checks.
- [ ] Fake Architect valid plan plus tracked edit blocks with file retained and no implement transition. Repeat for diagnose/decision/integration; include explorer/reviewer non-writing policy. Untracked creation/edit/delete, staged changes, HEAD commit and pre-existing dirty tree mutation are detected. Unchanged dirty baseline passes.
- [ ] Mutation plus malformed report/nonzero child exit preserves artifacts and blocks or remains uncertain based on proven containment; no silent automatic stage replay. Recovered planning report with dispatch→completion mutation cannot advance even when completion→current matches.
- [ ] Clean single and multi completion still work. Reviewer findings/dispositions, corrections, amendments, report ingestion, check-process containment and leases retain behavior. Existing historical evidence is readable but cannot newly certify complete without required re-verification.

### Verification commands

Run from the campaign worktree, no real model CLIs. New tests must be nonempty and behavioral.

```
python3 -m unittest discover -s scripts/tests -p 'test_v31_acceptance_integrity.py' -v
python3 -m unittest discover -s scripts/tests -p 'test_v31_stage_invariants.py' -v
python3 -m unittest discover -s scripts/tests -p 'test_checkpoint_b_provenance.py' -v
python3 -m unittest discover -s scripts/tests -p 'test_delta_audit_corrections.py' -v
python3 -m unittest discover -s scripts/tests -p 'test_decision_contract_regressions.py' -v
python3 -m unittest discover -s scripts/tests -p 'test_interactive_recovery.py' -v
python3 -m unittest discover -s scripts/tests -p 'test_report_ingestion.py' -v
python3 -m compileall -q scripts
python3 -m unittest discover -s scripts/tests -v
```

Record expected-red failures before production edits and actual green results after; do not invent counts. Real CLI introspection tests may remain opt-in/skipped with reasons. No paid requests, authenticated E2E, real installer execution, Doctor against live config, or existing-run testing. Installer testing in later workstreams uses disposable configurations and fake CLIs only.

## Workstream 2 — Explicit host and dispatch billing preflight

Outcome: AOR-04/05/07 closed with a shared fail-closed preflight used by Doctor and dispatch. Changes: orchestrator.py `create_run/start_run`, MCP_TOOLS/_mcp_tool_call/main, model_route/cli_command/call_model, scrubbed_env, doctor, stage_run and focused fake-CLI tests `test_v31_dispatch_safety.py` (new). Docs: SKILL.md host examples, security-model.md, configuration.md and contracts.md as needed. Do not change installer or OpenCode worker providers yet.

Tasks: require and validate host before state/lease/job writes; report persisted host and route distinctly; resume rejects contradictions. Inventory actual Claude CLI-supported provider/auth/settings precedence using official docs and fake settings. Implement redacted shared route preflight for subscription, explicit other billing and unknown overrides, executed before active_job. Preserve authorized existing alternate configurations accurately; use existing human-only gate pattern for consent rather than treating env as consent. Persist preflight rejection diagnostics without active job or model-call accounting. Keep actual dispatch journal before spawn. Test runtime env changes after Doctor.

Acceptance/adversarial: missing/invalid host even with skip_doctor; contradictory resume host; explicit Claude/Codex; secrets absent from all artifacts; provider flags incl AWS/Mantle/host-managed, endpoint and token/helper contamination from env and settings; malformed/unreadable influential settings; inert unrelated credentials; explicit authorized alternate route; rejection before spawn/active_job; repeated rejection no reconciliation; spawn failure still distinct from preflight; existing containment/rate-limit paths unchanged. Doctor produces same hazard classification without requesting credentials or inference. No silent scrubbing/reclassification.

Verification:
```
python3 -m unittest discover -s scripts/tests -p 'test_v31_dispatch_safety.py' -v
python3 -m unittest discover -s scripts/tests -p 'test_checkpoint_c_security.py' -v
python3 -m unittest discover -s scripts/tests -p 'test_interactive_recovery.py' -v
```
Then the applicable full-suite verification milestone from the execution contract. Keep old saved host; no migration from today's host defaults. Persisted non-secret policy metadata additive. Permission/reporting: execution contract. Escalate if effective managed settings cannot be observed safely; do not claim subscription proof.

## Workstream 3 — Claude installation and foreground stage lifecycle

Outcome: AOR-03/06 closed offline; authenticated host UX explicitly pending. Dependencies: completed host/preflight and integrity workstreams in this same implementation batch. Touch install_wsl.py, orchestrator.py stage_run/cancellation/time-budget propagation, SKILL.md, README.md, operation.md/maintenance.md, new tests `test_v31_claude_setup.py` and `test_v31_stage_deadline.py`. Preserve Codex setup and existing MCP protocol.

Tasks: --register-claude user-scoped stdio through official CLI; distinguish exact existing registration, conflict, missing and CLI failure; staged creation/rollback ownership; print manual equivalents and /mcp checks. Supply interactive host foreground env and 5-hour per-server timeout snippets without editing real settings. Prove actual whole-stage deadline including sequential checks and Architect, using remaining-time clipping and existing guarded cleanup; no detached background supervisor changes. Record version support assumptions. Maintain visible stage order, cancellation and recoverable durable state.

Acceptance/adversarial: fake CLI fresh/repeat/conflicting registration, wrong scope/path, malformed config, missing CLI, partial failure/rollback, unrelated servers unchanged bytewise where possible, config and manual skills untouched; foreground value set in host configuration fixture, not only child; combined checks+Architect exceed total deadline though each child individually fits; timeout during checks/decision, MCP cancel/EOF, process survivors and reconnect, no next stage after cancellation. False completion must remain blocked by Workstream 1. Fake tests do not establish interactive UX.

Verification:
```
python3 -m unittest discover -s scripts/tests -p 'test_v31_claude_setup.py' -v
python3 -m unittest discover -s scripts/tests -p 'test_v31_stage_deadline.py' -v
python3 -m unittest discover -s scripts/tests -p 'test_interactive_recovery.py' -v
python3 -m unittest discover -s scripts/tests -p 'test_checkpoint_a_containment.py' -v
```
Then the applicable full-suite verification milestone from the execution contract. Compatibility: no host settings overwrite or server replacement; previous registrations remain valid or get actionable conflict report. Security/billing/reporting/permissions: execution contract. Real authenticated Claude long stage/Esc/reconnect and Codex comparison are pending separate authorization.

## Workstream 4 — Generalized OpenCode routes, authorization and durable pins

Outcome: per-role configurable compatible OpenCode providers/models with explicit billing and fallback; legacy all-Go default retained. Dependencies: prior preflight, host and integrity gates. No new native backend/SDK. Files: config.example.json, orchestrator.py config/model_route/cli_command/opencode_env, inventory/Doctor, create_run/call_model/explore/continuation, usage display, state_compatibility/migrate_run and human-only authorization commands. Tests `test_v31_worker_routes.py` and `test_v31_route_migration.py` (new), existing V1/V2 fixtures. Docs configuration/security/contracts/operation and examples.

Tasks: implement architecture.md route schema and normalization; provider-qualified model validation; per-role optional variants/fallback and existing applicable limits; immutable resolved routes and routing-config fingerprint; API call-count grants bound to role/run/route via human-only CLI; conservative atomic reservations and explicit fallback per dispatch; guard effective provider config/hidden fallback/auxiliary routes; generalized inventory parsing for both supported dialects; remove unconditional free-model disabling only for explicitly authorized free route policy. Doctor independently reports configuration, availability, auth observability, variant, billing and execution-unverified. Keep roles/permissions/report ingestion/containment unchanged. Schema 3 and explicit backup-first conversion, version pins, migration from recorded routes, no live rerouting.

Acceptance/adversarial: legacy Go; mixed Go/API/local/free; non-Go subscription with reviewed classification; unapproved API fails before spawn; approved bounded API dispatch, retry/correction grant exhaustion; provider prefix mismatch/model absent, variant absent/unsupported/unobservable; provider unavailable/error/interruption; endpoint/auth change after run admission; config drift; fallback missing consent/authorized exact alternate; no session continuation across routes; fresh reviewer; nested Explorer grant consumption; aux paid route cannot hide behind free/local label; old state with recorded routes vs insufficient historical route information; active migration refused; rollback via backup; newer schemas rejected; report/session/usage accounting preserved including partial/unavailable cost. No hard spend-cap claim.

Verification:
```
python3 -m unittest discover -s scripts/tests -p 'test_v31_worker_routes.py' -v
python3 -m unittest discover -s scripts/tests -p 'test_v31_route_migration.py' -v
python3 -m unittest discover -s scripts/tests -p 'test_report_ingestion.py' -v
python3 -m unittest discover -s scripts/tests -p 'test_usage_rate_limit_regressions.py' -v
python3 -m unittest discover -s scripts/tests -p 'test_opencode_v2_integration.py' -v
```
Then the applicable full-suite verification milestone from the execution contract. Security: no credentials in routes/logs; no inference in Doctor; no automatic route switch; preserve explicit consent across resume without broadening it. Compatibility/report/permissions: execution contract and architecture.md. Escalate uninspectable provider routing instead of claiming universal billing enforcement.

## Workstream 5 — Integration, documentation and independent audit readiness

Outcome: coherent candidate for a new independent audit, no publication. Dependencies: all preceding workstreams implemented and their required checks passing. No intermediate Architect approval is required. Scope: cross-boundary tests `test_v31_campaign_integration.py` (new), docs/validation.md, CHANGELOG.md/version constants/configuration examples/CI only as necessary. Targeted fixes require evidence; architecture changes return for review.

Tasks: fake full Claude and Codex-hosted stage paths with mixed workers; single/multi completion after drift and recovery; migration plus billing consent and installer rollback; verify lease/context/permissions/report/rate-limit regressions. Finalize v3.1.0 source version and version-pin upgrade/rollback guidance, not Git tags. Reconcile doc counts with actual runner results. Produce AOR closure matrix (test and source references), provider compatibility matrix and independent-auditor-handoff.md including full review baseline/HEAD/commits, diff commands, evidence paths and residual limits. Do not list fake routes as live verified.

Acceptance/adversarial: full required campaign matrix in user's prompt accounted for by executable tests; no stale final approval after cached/recovered decisions or config migrations; no phantom job on host/provider preflight; no secrets or global side effects in installer/test paths; migration backups recover original bytes; existing completed history preserved without recertification. Doctor unknowns honest. Full source inspection confirms no weakened existing guard. Version/example/docs consistent; optional integration skips explained.

Verification:
```
python3 -m unittest discover -s scripts/tests -p 'test_v31_campaign_integration.py' -v
python3 -m compileall -q scripts
python3 -m unittest discover -s scripts/tests -v
```
Repeat CI's hermetic-override checks with all paths in a fresh disposable directory. Run available supported Python matrix or record missing local versions and await CI under separately authorized push. No paid requests. Real authenticated Claude UX, new provider routes and representative workload benchmark remain pending bounded human authorization; release is not contingent on inventing evidence.

Delivery/report/permissions: execution contract. Final Architect verdict evaluates all twelve final-review categories from user requirements, labels source/offline/introspection/authenticated evidence separately, and does not authorize stable release. An independent audit can reject the candidate; documentation must retain known sandbox, heuristic-provenance, exactly-once, price and quota limitations.

## Final compatibility, permissions and reporting

Integrity metadata is additive; the provider workstream performs the approved state/config schema-3 migration and final integration updates the source version to v3.1.0. Keep report contract v2 unchanged. On old saved unconsumed decisions, refuse approval reuse with actionable diagnostics and require new checks/decision; never rewrite historical completed acceptance. Preserve explicit migration/legacy read contracts without permitting weaker final certification. Do not widen existing command exceptions to make new tests pass.

One primary Implementer owns the complete batch; no automatic delegation required. Keep focused local commits by logical change, not one giant commit. Preserve a concise durable progress record with completed workstreams, current HEAD, remaining tests and blockers when context recovery is needed. Single worker preferred. No auto-dispatch or extra workers required. Production edits belong to the manually started Implementer under this approved complete brief. Permitted: scoped source/test/docs, disposable verification, focused local commits. Forbidden: push/merge/release/install/tag, destructive Git, global config/credentials/skills changes, installed orchestrator/existing runs/Sanatry access, live model calls, unrelated refactors. Implement the human-only route authorization mechanism specified in architecture.md and Workstream 4. Escalate consequential deviations from that contract; do not stop for ordinary internal workstream transitions.

Return in chat, copyable:
1. Batch ID, disposition proposed for review and authoritative brief path.
2. Starting branch/base, final HEAD, ordered commits, complete changed-file list, status including untracked and pre-existing changes.
3. Complete AOR-01 through AOR-07 closure matrix and multi-provider compatibility matrix, mapping every acceptance criterion to actual code and executable tests.
4. Red/green commands, results, counts, exits, runtime and saved evidence paths; full suite skips and interpreter.
5. Recovery/cache/legacy compatibility behavior; preserved mutation artifacts; security and billing impact.
6. Design deviations, remaining risks, unverified behavior and decisions needed.
7. Updated configuration/install/migration documentation, independent-auditor-handoff.md, and explicit separation of offline fake-CLI, installed-CLI introspection, historical claims and authenticated E2E evidence.

Do not call the batch approved. The Architect will inspect the actual entire diff and evidence independently.
