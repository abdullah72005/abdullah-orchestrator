# Orchestrator v3.1 campaign architecture

Status: DESIGN APPROVED by Abdullah in chat on 2026-11-13. Abdullah subsequently directed the entire approved campaign to be delivered as ONE implementation batch. All five internal workstreams are authorized within batch-01.md; one independent Architect review follows delivery.
Date: 2026-11-13. Workflow: original manual abdullah-architect → abdullah-implementer; no automated orchestrator dispatch.

## Source and evidence

Development worktree: `/home/abdullah/.local/src/abdullah-orchestrator-v3-1`
Branch: `design/orchestrator-v3-1`
Base: `1b8e10e5c1b2c08a236b68450cb5b2a1a610416d`.
Originating maintained checkout: `/home/abdullah/.local/src/abdullah-orchestrator-remediation`, clean `main` at this base, local origin is the older source checkout; `github` remote is https://github.com/abdullah72005/abdullah-orchestrator.git. GitHub main independently queried with `git ls-remote` matches base. `d80bea0ffe2ae1a66ac01a09bd06541b93b84f98` is an ancestor. Local annotated v3.0.0 resolves to base; remote tag object is db62c535bf333a1104fa9ede81c73ac523d004ab. The supplied audit calls 32c6fdf the published tag commit. Record this discrepancy rather than rewriting history: 32c6fdf..base contains one documentation-only commit and no scripts changes. Acceptance defects therefore apply to identical supervisor/test code. Do not move tags.

Other checkout: `/home/abdullah/.local/src/abdullah-orchestrator` at b71f84e, clean. Installed copy: `/home/abdullah/.local/share/abdullah-orchestrator`. Neither is the development target. No pre-existing changes were present in the maintained checkout or campaign worktree. Preserve original manual skills unchanged.

Authoritative requirements: user's campaign prompt and complete Independent Engineering & Requirements Acceptance Audit supplied in chat on 2026-11-13, read in full. Audit ZIP and original disposable probe scripts were not supplied; audit reproductions are reported evidence, not this Architect's executions. Earlier `docs/audit/*` records describe prior fixes, not closure of AOR-01..07. Raw authenticated pilot evidence remains unavailable. No paid calls authorized.

## Findings independently checked in source

All locations below refer to the campaign baseline; use symbol names after edits.

| Requirement | Actual boundary | Decision |
|---|---|---|
| AOR-01 | `advance` accept/integrate, lines 5940–6100; `load_verification_evidence` 5500; `strong_call` 5024 | Existing evidence validator is reusable. Pre-call checks are insufficient; post-call branches compare source signatures only. Validate complete provenance immediately before acceptance commits. |
| AOR-02 | `call_model` 4308 persists dispatch source and final_snapshot but never compares read-only-stage source; `cached_job_report` 5093 only compares completion to present | Enforce dispatch→completion source preservation and replay the same invariant when consuming recovered reports. |
| AOR-03 | `install_wsl.py:install` only supports --register-codex | Add explicit Claude registration using official CLI, conflict detection and disposable installer tests. |
| AOR-04 | MCP start schema/handler 8130–8230; create/start/CLI default host=codex | Require explicit host on new starts; validate before side effects; saved host persists. |
| AOR-05 | `scrubbed_env` 888; key guards 4362; Doctor 6537 | Shared route preflight must inspect effective child env and applicable settings, including managed/provider routing. Reject unknown/unprovable subscription routing. |
| AOR-06 | Stage MCP is synchronous and cancellation-aware; setup lacks Claude foreground settings | Configure controlling host, not server child. Bound whole stage duration, not just each subprocess. |
| AOR-07 | `active_job` saved at 4357 before billing guard outside try | Validate before recording dispatch; retain rejection diagnostics with no active process claim. |
| Providers | `config` 234, `model_route` 2983, `opencode_env` 3423, inventory parsers 6308, Doctor 6500 | Generalize these boundaries; preserve CLI, permission profiles, reports, containment and usage ingestion. |
| Durability | state/config schema 2; `state_compatibility` 953; `migrate_run` 6715; start records model_routes but dispatch derives current config | Make pinned routes authoritative, preserve strict config-change guard and backup-first migration; never infer old routes from today's defaults. |

Relevant tests: `test_checkpoint_b_provenance.py`, `test_delta_audit_corrections.py`, `test_final_hardening.py`, `test_decision_contract_regressions.py`, `test_checkpoint_d_efficiency.py`, `test_interactive_recovery.py`, `test_report_ingestion.py`, `test_opencode_v2_integration.py`, and baseline `test_orchestrator.py`. CI uses unittest on Python 3.10/3.12/3.13. Existing AcceptanceTransition fixtures sometimes use pathless evidence; completion tests must move to real supervisor-issued records instead of weakening the new gate.

## Approach and rejected alternatives

Recommended: extend deterministic gates and existing route dictionaries in the standard-library supervisor. A small shared validation helper per boundary is justified; splitting the whole module or adding provider SDKs is not. Keep OpenCode as the sole worker runtime.

Alternative: patch only the audit's named branches. Smaller diff, but leaves cached/recovered decisions and configuration injection inconsistent. Reject.

Alternative: new backend interface and service with provider adapters. Larger migration and new failure modes without meeting a current need. Reject. Native Codex/Claude workers, benchmarking campaigns and OS isolation implementation are excluded.

## Acceptance and stage integrity

1. Capture full current source/runtime/env/config/toolchain snapshots at decision boundaries. Revalidate check executable identities using the existing evidence loader. Bind approvals to exact evidence bytes/digest, actual candidate and plan revision/content hash; check both batch and final evidence on the single-batch fast path.
2. Validate before sending evidence and again after Architect return, before accepted_batches append, batch increment or complete. Apply equally to fresh, cached and recovered decisions. A new verification record requires a new Architect decision; invalidate the old decision durably. Audit rejected decisions; do not erase history.
3. Read-only kinds: plan, diagnose, decision, integration, explorer and reviewer. Compare dispatch source projection (HEAD, index, tracked dirty and untracked source) to completion/current source. A pre-existing dirty tree is allowed unchanged; new edits/deletions/staging/commits are not. Runtime inputs retain their existing provenance checks. Do not compare full volatile provenance to decide whether source was written.
4. Unexpected source mutation: preserve every file/artifact, block, describe changed paths/identities without dumping sensitive content, invalidate decision. Use uncertain only if process containment is unproven. No automatic rollback. No write exception is needed in v3.1: legitimate code edits go through an Implementer stage. If a future exception is necessary it requires a new scoped human-authorized contract; no blanket switch now.
5. Non-source provenance drift: discard acceptance eligibility, route batch acceptance back to verify (including review again), or integration back to fresh integration checks. Config/plan changes may additionally require existing compatibility/replan gates. Never silently certify mismatched plan content or missing modern evidence. Old evidence remains readable, but new v3.1 completion requires fresh attestation; a legacy acknowledgement is not a bypass for this invariant.
6. This certifies observed boundary state. Same-user hostile races and transient write-and-revert cannot be prevented by snapshots; do not claim an OS sandbox or continuous filesystem immutability.

## Host, strong route and preflight

Controlling `host` is mandatory for new CLI/MCP/programmatic starts, enum codex|claude. Do not infer it from weak env hints. Resume uses stored host and rejects conflicting host assertions. Output selected host and resolved Architect route separately. Existing configuration `architect[host]` and explicit fallback remain the route selection model; this campaign does not add cross-host Architect routing.

Use one deterministic preflight shared by dispatch and Doctor. Before any active job/dispatch intent or model process: resolve route and authorization, construct effective child environment/settings view, verify billing safety and session binding. A rejection is durable `preflight_rejected` diagnostic plus blocked run, not an active worker or counted model call. Preserve persist-intent-before-spawn after preflight succeeds. Crash after persisted dispatch is still uncertain until proven otherwise.

For Claude subscription routes inspect environment and effective settings for alternate credentials, API-key helpers, endpoint/base URLs, provider flags (Bedrock, Vertex, Foundry, Anthropic AWS, Mantle), provider-managed-by-host and fallback/model routing overrides. Inspect user/project/local plus applicable managed sources and settings env, respecting actual CLI version/precedence. Do not execute credential helpers to inspect them. Unknown/unreadable influential settings fail closed with a redacted reason. Ambient AWS credentials alone do not prove a selected provider; avoid blocking unrelated inert credentials. Do not strip a dangerous override silently and then claim subscription safety. Doctor must report the same policy outcome. Never log secret values, raw settings, credential contents, or credential-bearing URLs.

Explicit non-subscription Architect routes already expressible by config must remain available when accurately classified and human-authorized; an environment variable is not consent. Reuse the route-scoped authorization contract from worker work for usage-billed routes, without adding native worker adapters. Do not promise subscription entitlement merely because configuration passed. Check supported settings/version introspection before claiming effective-route proof; unresolved managed routing is a blocker, not a guessed route.

## Claude installation and one conversation

Register only when explicitly requested: `claude mcp add --scope user --transport stdio abdullah-orchestrator -- <python> <absolute-source>/scripts/orchestrator.py mcp`. Inspect existing normalized command/args/scope: identical is no-op; conflicting server is an error, never overwritten. A failed invocation must not be treated as 'not found' without distinguishing CLI/config errors. Preserve unrelated servers and all standalone skills. Rollback removes only artifacts created by that installer invocation; never run a destructive remove/re-add on an existing server. Provide manual commands and /mcp verification.

Official documentation checked 2026-11-13:
- https://code.claude.com/docs/en/mcp : user scope; per-server timeout in milliseconds; foreground auto-background env; cancellation/idle semantics.
- https://code.claude.com/docs/en/env-vars : provider/endpoint/authentication/host-management controls.
- https://code.claude.com/docs/en/settings : settings precedence, managed overrides, settings env.
- https://opencode.ai/docs/models/ and https://opencode.ai/docs/providers/ : provider/model selectors, variants, custom endpoints, subscription/local routes.

Set `CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS=0` in the environment/settings of the interactive Claude host before launch, not merely MCP server env. Recommend per-server `timeout: 18000000` (5 hours). Current docs say >=1000 also raises the idle floor. Keep Codex's existing compatible timeout setup. Do not automatically rewrite host settings; provide exact mergeable snippets/manual setup and isolated fixtures.

Challenge to audit assumption: max_*_seconds=14400 limits individual children/checks, not necessarily the whole MCP stage (single acceptance can run several checks plus a strong call). Add a real whole-stage deadline using existing cancellation/guard paths, with child timeouts clipped to remaining time, so stage cap plus bounded cleanup fits the 5-hour host timeout. No detached polling/service redesign. Progress visible at stage boundaries remains baseline; test cancellation transport and state. Actual Claude foreground/Esc/reconnect UX requires separately authorized authenticated E2E.

## Worker route contract

Retain `provider: opencode` in resolved job routes as the existing runtime discriminator, add `worker_provider` for actual OpenCode provider ID. Config per role adds `provider`; retains canonical full `model: provider/model-id`, `variant`, and `billing`. Reject prefix/provider mismatch, embedded #variant conflicts, malformed IDs, missing roles and wrong types. Split full model ID only on first slash. No model-name allowlist. Legacy missing provider derives prefix; `billing: go` remains supported and means Go subscription. Other explicit billing values: subscription, api, free, local. Billing is policy/attestation, not inferred from name.

Resolved route retains existing `model`, `effort` (variant), `billing`; adds worker_provider and a redacted routing/config fingerprint. Empty variant omits variant flags. Probe installed catalog/capabilities without inference requests. Unsupported known variants fail; unavailable variant metadata stays explicitly unverified. Execution may reject unsupported variants; never substitute another model/variant.

Per-role `fallback` defaults disabled; when configured it specifies a complete alternate worker route and requires one-dispatch human consent. Keep existing strong fallback separate. Never automatic fallback on rate limit, provider failure or free quota exhaustion. An authorized fallback remains an OpenCode call; do not route worker through strong CLI. Retry session is reusable only for exact same pinned route and reconciled attempt; fallback/new route uses fresh session. Reviewer always fresh.

Pin run routes and applicable limits/authorization policy at creation; job records exact runtime/provider/model/variant/billing/fingerprint and consent reference. Dispatch consumes pinned routes, including nested Explorer. Preserve strict config hash checks: external config changes pause/require explicit migration, never silently change a run. Preflight checks actual current effective OpenCode provider configuration/endpoints/auth mode against the pinned routing fingerprint; changed route material requires operator review. No secrets embedded in state; hash normalized sensitive routing values when necessary.

New API/usage-billed routes require an explicit CLI-only human authorization (existing require_human_operator discipline, not MCP/model tool). Bind run, role, route hash, maximum dispatch count; record actor/time/scope. Reserve one call atomically before spawn; release only if launch is proven never attempted. Crash after reservation is conservative, never automatically refunded. Corrections, retries, nested exploration and report-repair calls consume grants when they dispatch. Existing global iteration/time limits remain. Non-Go subscription/free/local routes also require explicit route classification/endpoint/auth-mode attestation; provider name alone is insufficient. Unknown/remote ambiguous billing defaults to requiring API authorization. Local classification requires an explicitly reviewed local endpoint; a provider named ollama may serve remote/cloud models. Preserve Go configuration's existing opt-in as legacy authorization only for the unchanged Go route; no inherited consent for a new provider.

No hard dollar cap claim: call budgets bound supervisor dispatch attempts, not token cost, CLI internal retries, auxiliary provider calls or tariff changes. Disable detectable provider-side fallback/auxiliary remote model routes or require that the grant covers them explicitly; unresolved routing blocks unbilled claims. Arbitrary custom plugins/gateways can defeat application-level assurances; report supported/inspectable boundaries accurately rather than claiming every plugin is certified. Doctor sends no inference, no credential helper requests; readiness may be observable/unverified/blocked separately from configuration validity. Preserve usage reported/derived/partial/unavailable distinctions; keep historical cheap_calls as worker-call count, not a price guarantee.

## Compatibility

The integrity workstream adds optional decision-binding/stage-integrity metadata without changing report contract v2. Unbound historical decisions are readable but cannot authorize new transitions; rerun verification and decision. Preserve archived completed runs; do not retroactively rewrite them as certified.

The provider workstream advances configuration/state schema to 3 using the existing explicit backup-first migration, rejecting newer versions. Normalize old Go config in memory, no global rewrite; handle old supervisor-version pin explicitly in migration instructions (no blanket disabling of pin checks). Old saved routes are reconstructed from their recorded model_routes/dispatch data only. If insufficient or inconsistent, block and require a reviewed explicit mapping, never take today's defaults. Migration invalidates verification/review/cached decisions and check progress, including integrate; preserves source, host, history, leases and usage. Refuse active/uncertain execution migration. Changing providers requires a new run; do not expand migration into a live rerouting feature. Version release finalization belongs to the final integration workstream; no install or tag publication.

## Execution and review

See batch-01.md for the complete single implementation brief and campaign-plan.md for its index. The Implementer executes all internal workstreams in dependency order without intermediate Architect approval gates, then returns one consolidated report. Keep focused local commits and durable progress notes so context compaction or session recovery does not lose work. Material design deviations still require escalation; ordinary workstream transitions do not. No Implementer auto-start. Independent final review must separate source inspection, offline fake-CLI tests, optional installed CLI introspection, historical developer pilot claims and authenticated E2E.
