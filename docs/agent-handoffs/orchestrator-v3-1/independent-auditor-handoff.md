# Orchestrator v3.1 — independent auditor handoff

Status: implementation candidate for independent review. **Not** Architect-approved,
production-ready, or published. No tag, release, install, push or paid model call
was performed by the Implementer.

- Worktree: `/home/abdullah/.local/src/abdullah-orchestrator-v3-1`
- Branch: `design/orchestrator-v3-1`
- Review baseline: `1b8e10e5c1b2c08a236b68450cb5b2a1a610416d`
- Candidate source/evidence HEAD: `9eb49ef` (docs: finalize v3.1.0 integration
  evidence and audit handoff). This handoff-file update is a docs-only child of
  that commit; use the branch tip for review.
- Candidate commits: `e223ca1` (acceptance integrity), `076caeb` (host/preflight),
  `e6cab3c` (Claude setup/stage deadline), `a3f6202` (worker routes/migration),
  `9eb49ef` (integration evidence/docs).
- Authoritative brief: `docs/agent-handoffs/orchestrator-v3-1/batch-01.md`
- Approved design: `docs/agent-handoffs/orchestrator-v3-1/architecture.md`

## Review commands

```bash
git -C /home/abdullah/.local/src/abdullah-orchestrator-v3-1 status --short
git -C /home/abdullah/.local/src/abdullah-orchestrator-v3-1 log --oneline 1b8e10e..HEAD
git -C /home/abdullah/.local/src/abdullah-orchestrator-v3-1 diff --stat 1b8e10e..HEAD
git -C /home/abdullah/.local/src/abdullah-orchestrator-v3-1 diff 1b8e10e..HEAD -- scripts/orchestrator.py
python3 -m compileall -q scripts
python3 -m unittest discover -s scripts/tests -v
```

The optional installed-CLI suite may be skipped when its binary is absent:

```bash
ABDULLAH_OPENCODE_V2_BIN=/path/to/opencode-2.2.7 \
  python3 -m unittest discover -s scripts/tests -p 'test_opencode_v2_integration.py'
```

## AOR closure matrix

| Finding | Required outcome | Source | Executable evidence |
|---|---|---|---|
| AOR-01 | Full post-Architect verification provenance and decision binding | `make_decision_binding`, `decision_binding_drift`, `cached_decision_report`, `validate_acceptance_references`, `strong_call`, `advance` accept/integrate | `test_v31_acceptance_integrity.py` (single/intermediate/integrate late drift, evidence-byte replacement, new record/new decision, missing binding, changed plan, bound crash recovery, env/config/runtime drift) |
| AOR-02 | Preserved source and blocked unauthorized stage mutation | `source_write_projection`, `source_mutation`, `_read_only_source_violation`, `call_model` dispatch/completion checks, `validate_preserved_stage_source`, `cached_job_report`, `cached_recovered_job_report`, `recover_finished_dispatch` | `test_v31_stage_invariants.py` (real Git + fake CLIs; plan/diagnose/decision/integration/explorer/reviewer; tracked/staged/untracked/HEAD; pre-existing dirty; malformed/nonzero; recovered mismatch; guarded `stage_run`) |
| AOR-03 | Idempotent user-scoped Claude MCP registration and rollback tests | `install_wsl.register_claude`, `inspect_claude_registration`, `_registration_matches`, manual snippets | `test_v31_claude_setup.py` (fresh/repeat/conflict/scope/malformed/missing CLI/add failure/unverified rollback/unrelated server preservation/host snippet) |
| AOR-04 | Explicit host, durable identity and route reporting | `create_run` host validation, `start_run`, `resume_run`, MCP start/resume schemas, `route_report`, `status_run`, `stage_payload` | `test_v31_dispatch_safety.py` (missing/invalid host, no state write, MCP required host, contradictory resume, distinct host/route, legacy host persistence) |
| AOR-05 | Shared Claude provider/billing hazard preflight and Doctor checks | `claude_billing_hazards`, `codex_billing_hazards`, `opencode_provider_observation`, `route_preflight`, `doctor` | `test_v31_dispatch_safety.py`, `test_checkpoint_c_security.py` (API keys, provider flags incl AWS/Mantle, endpoints, settings helper/malformed settings, inert AWS creds, runtime env change after Doctor, secret-free diagnostics, Doctor parity) |
| AOR-06 | Foreground host setup, stage deadline, cancellation and recovery | `manual_claude_snippets`, `FOREGROUND_ENV`, `RECOMMENDED_SERVER_TIMEOUT_MS`, `stage_deadline`, `remaining_budget`, clipped `call_model`/`run_checks` | `test_v31_claude_setup.py`, `test_v31_stage_deadline.py`, existing `test_interactive_recovery.py`, `test_checkpoint_a_containment.py` (whole-stage clipping, decision timeout, no next stage, cancellation) |
| AOR-07 | Durable preflight rejection with no phantom active dispatch | `call_model` rejection path writes `preflight-*.json`, `preflight_rejection`, no `active_job`, no usage accounting | `test_v31_dispatch_safety.py` (rejection before spawn, repeated rejection, no reconciliation work, spawn failure distinct) |
| Multi-provider | Per-role routes, consent, migration, Doctor | Schema-3 config/state, `normalize_worker_spec`, `model_route`, `routing_fingerprint`, `route_authorization_status`, `reserve_route_grant`, `approve_worker_fallback_run`, `migrate_run`, `restore_run`, generalized inventory, Doctor fields | `test_v31_worker_routes.py`, `test_v31_route_migration.py`, existing V1/V2/report/usage suites |
| Final integration | Regressions, docs, closure matrices | This file, `docs/validation.md`, `CHANGELOG.md`, configuration/security/contracts/operation/maintenance docs, version `3.1.0` | `test_v31_campaign_integration.py` (fake Codex and Claude multi-batch, late drift recovery) plus full offline suite |

## Provider compatibility matrix

| Route form | Config | Dispatch policy | Evidence status |
|---|---|---|---|
| OpenCode Go (default) | `provider: opencode-go`, `billing: go` | Existing Go authorization; no new grant | Offline fake-CLI; historical v3.0.0 live pilot used Go |
| OpenCode paid API | fully qualified `provider/model`, `billing: api` | Human `authorize-route` grant, atomic per-dispatch reservation | Offline fake-CLI only; not live-verified |
| Non-Go subscription | explicit route, attestation | Human grant with endpoint/auth attestation | Offline policy tests only |
| Free route | explicit route, attestation | Human grant; free-model guard removed only for the authorized route; custom endpoint must be attested | Offline policy tests only |
| Local route | explicit route + reviewed endpoint | Human grant; endpoint required in effective config | Offline policy tests only; a provider named “ollama” is not automatically local |
| Per-role fallback | complete `fallback` object | Separate one-dispatch human consent; exact route hash; non-Go still needs its own grant | Offline fake-CLI tests |
| Schema-2 recorded routes | `migrate-run` | Reconstructed only from recorded routes/jobs or explicit mapping | Offline migration tests incl rollback |
| Authenticated Claude/Codex E2E | real host | Not executed | **Unverified** |

`subscription` entitlement, provider settlement, auxiliary provider calls and
tariff changes are **not** proven. Route grants bound supervisor dispatch
attempts, not tokens or dollars. There is no hard spend-cap claim.

## Verification snapshot

Last full offline run before the final documentation/handoff commit:

- Interpreter: Python 3.10.12
- `python3 -m compileall -q scripts`: exit 0
- `python3 -m unittest discover -s scripts/tests`: **656 tests**, 4 skipped,
  exit 0, ~291–379 s across recorded runs
- The 4 skips are the optional installed-CLI V2 introspection suite; they are
  reported separately and are not counted as passed.
- No paid requests, authenticated E2E, real installer execution or Doctor
  against live config were performed.

Final counts are re-recorded in the Implementer's chat report. Do not treat this
document as Architect approval.

## Preserved artifacts and safety

- Read-only source mutation tests keep the modified source, report, dispatch,
  completion and `source-mutation.json`; there is no rollback, reset or clean.
- Stale decisions are preserved in `invalidated_decisions`/failed-job history,
  not erased, and cannot authorize a transition.
- Migration backups are byte copies of the pre-migration `state.json`;
  `restore-run` uses the exact backup.
- Installer tests use disposable `HOME`/config/state and fake CLIs; the real
  Claude/Codex configuration is not edited.
- Report contract v2 and existing permission profiles are unchanged.

## Residual limits and pending evidence

1. Real authenticated Claude long-stage, Esc/cancel/reconnect and `/mcp` UX are
   not verified; only fake-CLI registration/CLI contracts and deterministic
   cancellation/deadline tests exist.
2. New provider routes, API grants and fallback are not live-verified; billing
   is policy/attestation, not provider settlement.
3. Same-user hostile races and write-and-restore between snapshots are not
   preventable; this is observed boundary state, not an OS sandbox.
4. `doctor` never executes inference and cannot prove entitlement; managed
   settings that cannot be observed safely fail closed.
5. Exactly-once side effects, price/quota accuracy and arbitrary plugin/gateway
   behavior remain outside the supervisor's guarantees.
6. CI compatibility targets Python 3.10/3.12/3.13; only 3.10.12 was available
   locally. CI must run under separately authorized push.
7. Docker verification evidence is synthetic in the offline suite.

## Recommended review focus

1. Read the full `scripts/orchestrator.py` diff, especially decision binding,
   rejection paths and migration invalidation.
2. Re-run the adversarial suites and inspect that no validator was mocked green.
3. Confirm preflight cannot create `active_job` or count a model call on
   rejection, and that spawn failure remains distinct.
4. Confirm migration never infers routes from today's config and cannot be run
   on active work.
5. Label every claim by evidence class before any release decision.
