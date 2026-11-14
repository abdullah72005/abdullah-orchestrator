# Orchestrator v3.1 — independent auditor handoff

Status: implementation candidate for independent review. **Not** Architect-approved,
production-ready, or published. No tag, release, install, push or paid model call
was performed by the Implementer.

- Worktree: `/home/abdullah/.local/src/abdullah-orchestrator-v3-1`
- Branch: `design/orchestrator-v3-1`
- Review baseline: `1b8e10e5c1b2c08a236b68450cb5b2a1a610416d`
- Candidate source/evidence HEAD: branch tip on `design/orchestrator-v3-1`. Round 2
  correction implementation commit is `2d324b0`, followed by this documentation
  commit. Round 1 correction commits were `740db1c` and `190d7fb`. Use the branch
  tip for review.
- Candidate commits: `e223ca1` (acceptance integrity), `076caeb` (host/preflight),
  `e6cab3c` (Claude setup/stage deadline), `a3f6202` (worker routes/migration),
  `9eb49ef` (integration evidence/docs), plus the Round 1 correction commits
  listed in the delivery report.
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
| AOR-05 | Shared Claude provider/billing hazard preflight and Doctor checks | `claude_billing_hazards`, `codex_billing_hazards`, `_managed_settings_entries`, `opencode_provider_observation`, `route_preflight`, `doctor` | `test_v31_dispatch_safety.py`, `test_checkpoint_c_security.py`, `test_v31_routing_observation.py` (API keys, provider flags incl AWS/Mantle, endpoints, settings helper/malformed settings, managed drop-ins, effective child routing, inert AWS creds, runtime env change after Doctor, secret-free diagnostics, Doctor parity) |
| AOR-06 | Foreground host setup, stage deadline, cancellation and recovery | `manual_claude_snippets`, `FOREGROUND_ENV`, `RECOMMENDED_SERVER_TIMEOUT_MS`, `stage_deadline`, `remaining_budget`, clipped `call_model`/`run_checks` | `test_v31_claude_setup.py`, `test_v31_stage_deadline.py`, existing `test_interactive_recovery.py`, `test_checkpoint_a_containment.py` (whole-stage clipping, decision timeout, no next stage, cancellation) |
| AOR-07 | Durable preflight rejection with no phantom active dispatch | `call_model` rejection path writes `preflight-*.json`, `preflight_rejection`, no `active_job`, no usage accounting | `test_v31_dispatch_safety.py` (rejection before spawn, repeated rejection, no reconciliation work, spawn failure distinct) |
| Multi-provider | Per-role routes, consent, migration, Doctor | Schema-3 config/state, `normalize_worker_spec`, `model_route`, `routing_fingerprint`, `route_authorization_status`, `reserve_route_grant`, `approve_worker_fallback_run`, `migrate_run`, `restore_run`, generalized inventory, Doctor fields | `test_v31_worker_routes.py`, `test_v31_route_migration.py`, existing V1/V2/report/usage suites |
| Final integration | Regressions, docs, closure matrices | This file, `docs/validation.md`, `CHANGELOG.md`, configuration/security/contracts/operation/maintenance docs, version `3.1.0` | `test_v31_campaign_integration.py` (fake Codex and Claude multi-batch, late drift recovery) plus full offline suite |

## Round 1 correction matrix (Architect fix-b01-r01)

| Finding | Correction | Permanent evidence |
|---|---|---|
| F1 escaped source mutation | `call_model` success/failure paths inspect containment independently; only a proven-stopped whole execution clears active identity. Live escaped child stays exact `uncertain`. | `test_v31_stage_invariants.py::test_escaped_child_*`, `test_failed_cleanup_never_clears_uncertain_ownership`, `test_clean_stopped_mutation_blocks_without_phantom_reconciliation`; baseline probe `containment` |
| F2 inherited Go consent | `validate_worker_billing` / `normalize_worker_spec` / `_normalize_recorded_route` / preflight reject `go` on non-Go provider and require explicit billing; legacy missing fields only for all-Go records. | `test_v31_worker_routes.py::test_go_billing_is_only_valid...`, `test_go_route_defense_in_depth...`, `test_non_go_missing_billing...`, `test_invalid_route_configurations...`; baseline probe `go` |
| F3 non-Go subscription grants | Reservation happens whenever preflight requires a grant, independent of billing; exact grant/route and durable consumption. | `test_non_go_subscription_grant_allows_exactly_one_attempt`, `test_subscription_grant_is_consumed_even_when_the_attempt_fails`; baseline probe `subscription` |
| F4 nested grant overwrite | `route-grants/ledger.json` with its own lock, exact reservation IDs, idempotent replay, and `save()` usage mirroring. Authorization consults live durable usage. | `test_v31_grant_ledger.py` (real separate-process parent→`explore`, stale parent save, concurrent processes, replay); baseline probe `nested` |
| F5 effective route fingerprint | `opencode_provider_observation` merges selected-dialect V1/V2 config locations, JSONC, env/file expansion, endpoint/auth/model/variant/auxiliary material; unreadable fails closed; migration initializes pins. | `test_v31_routing_observation.py` (V1/V2, JSONC, auth/model mapping, env/config-dir, unreadable, migrated pin, Doctor/dispatch); baseline probe `observation` |
| F6 Claude settings sources | `_claude_settings_paths` resolves `CLAUDE_CONFIG_DIR` + user/project/local/managed; provider-managed host, endpoint/token/helper/model/fallback keys fail closed; authorized alternate billing preserved. | `test_v31_dispatch_safety.py::test_claude_*`, `test_provider_managed_host...`, `test_managed_settings...`, `test_post_doctor_contamination...`, `test_clean_subscription...`; baseline probe `claude` |
| F7 API fallback authorization | `authorize-route --fallback` targets the exact configured alternate; consent is consumed only after preflight+reservation; changed alternate/exhausted grant refuse before spawn. | `test_v31_grant_ledger.py::test_public_authorize_route_fallback...`, `test_missing_alternate_grant...`, `test_changed_alternate...`; baseline probe `fallback` |
| F8 Claude destination split | `manual_claude_snippets` returns separate settings and user MCP-store destinations/content, `add-json` timeout command, merge/verify steps; no real file mutation. | `test_v31_claude_setup.py::test_manual_snippets_use_separate...`, `test_disposable_settings_and_user_mcp_stores...`, `test_repeated_registration...`; baseline `claude-setup` probe |
| F9 restore validation | `validate_restore_backup` checks full JSON identity/project/schema/inactive state before mutation; atomic write under lock; pre-restore audit. | `test_v31_route_migration.py::test_corrupt_backup...`, `test_wrong_identity...`, `test_write_failure...`, `test_valid_restore...`; baseline `restore` probe |

## Round 2 correction matrix (Architect fix-b01-r02)

Remaining F5/F6 boundaries only; accepted Round 1 corrections were preserved and
re-exercised by the same suites.

| Finding | Correction | Permanent evidence |
|---|---|---|
| F5a child-configuration mismatch | `opencode_child_inline` / `_opencode_child_config` compose the effective `OPENCODE_CONFIG_CONTENT` from documented files plus supported ambient routing fields, then apply generated agent/permission/subagent controls last. Preflight, fingerprint, Doctor and `opencode_env` share this boundary; references expand in the child environment and project cwd. A file-defined `abdullah-<role>` agent is refused before spawn. | `test_v31_routing_observation.py::test_fake_child_receives_the_approved_provider_for_both_dialects` (fake CLI captures argv + env for V1/V2; pin reproducible from captured bytes), `::test_inline_expansion_uses_the_child_environment_and_project_cwd`, `::test_ambient_inline_controls_cannot_weaken_generated_profile`, `::test_file_defined_worker_agent_conflict_fails_closed_before_spawn` |
| F5b auth mode omitted from pin | `auth_mode_sha256` (declared env names, child-env availability, configured key/header presence, model/variant auth settings) is bound in every `routing_fingerprint` branch. | `::test_auth_environment_availability_is_part_of_the_pin_for_both_dialects` (absent→present→absent, V1/V2, pinned drift blocks; red baseline showed equal pins) |
| F5c Go model/variant override | `_opencode_effective_endpoint` resolves provider→selected model→selected variant endpoints; `_opencode_go_qualification` rejects endpoint, package/canonical and model/provider remaps with classification `unqualified_go_route`. Unchanged Go remains `go_subscription` without a new grant; the same route with explicit `api` billing plus grant is accepted as accurately classified. | `::test_go_route_model_and_variant_endpoint_overrides_are_not_subscription` (V1/V2, model/variant/remap), `::test_unchanged_go_route_remains_a_subscription_without_a_grant`; red baseline approved all overrides |
| F6 managed drop-ins | `_managed_settings_entries` enumerates each configured managed base file then non-hidden sibling `managed-settings.d/*.json` alphabetically, including when the base is absent. Every fragment gets the existing redacted hazard/parse validation; unreadable files/directories and listed-but-vanished files fail closed; hidden/non-JSON entries are ignored. Doctor and dispatch share the classification. | `test_v31_dispatch_safety.py::test_managed_dropin_is_inspected_when_base_file_is_absent` (incl. no spawn/active job, secret-free diagnostics), `::test_managed_dropins_are_ordered_and_hidden_or_non_json_ignored`, `::test_malformed_and_non_object_managed_dropins_fail_closed`, `::test_unreadable_managed_dropin_fails_closed`, `::test_unreadable_managed_directory_fails_closed`, `::test_clean_dropin_and_authorized_alternate_classification`; red baseline returned `ok` with no hazards |

Captured child-configuration evidence (temporary probe, not a production test):
`/tmp/opencode/ao-r02-child-config-capture.log` shows a V1 local dispatch whose
captured `OPENCODE_CONFIG_CONTENT` retains the approved provider/endpoint and
generated `abdullah-explorer` profile with `subagent_depth: 0`, and whose
recomputed pin equals the pinned preflight digest. Red regressions are preserved
in `/tmp/opencode/ao-red-r02/`.

Also replaced the old “checks fit” deadline test with a genuine single-batch
accept stage where a final check (0.8 s) and fake decision (1.5 s) each fit a 2 s
stage but together time out without completion, and added a mixed
API/free/Go fake stage path driven through the real human authorization helpers
(`test_v31_campaign_integration.py`).

## Provider compatibility matrix

| Route form | Config | Dispatch policy | Evidence status |
|---|---|---|---|
| OpenCode Go (default) | `provider: opencode-go`, `billing: go` | Existing Go authorization; no new grant; only this provider may inherit Go, and only without an inspectable endpoint/package/model remap | Offline fake-CLI; historical v3.0.0 live pilot used Go |
| OpenCode paid API | fully qualified `provider/model`, `billing: api` | Human `authorize-route` grant; durable ledger reservation before spawn | Offline fake-CLI only; not live-verified |
| Non-Go subscription | explicit route, attestation | Human grant with endpoint/auth attestation; reservation actually consumed | Offline fake-CLI policy/dispatch tests |
| Free route | explicit route, attestation | Human grant; free-model guard removed only for the authorized route; custom endpoint must be attested | Offline policy tests only |
| Local route | explicit route + reviewed endpoint | Human grant; endpoint required in effective config | Offline policy tests only; a provider named “ollama” is not automatically local |
| Per-role fallback | complete `fallback` object | `authorize-route --fallback` for the exact alternate grant plus separate one-dispatch `approve-worker-fallback` consent | Offline fake-CLI tests incl missing/changed/exhausted alternate |
| Schema-2 recorded routes | `migrate-run` | Reconstructed only from recorded routes/jobs or explicit mapping; explicit migration initializes routing pins | Offline migration tests incl rollback |
| Effective routing | V1/V2 config locations | One composition boundary for files + preserved ambient inline routing + generated controls; JSONC, child-env/file expansion; unreadable fails closed; auth mode and model/variant endpoints pinned | Offline temporary configs plus captured fake-child `OPENCODE_CONFIG_CONTENT`; arbitrary plugins/gateways unverified |
| Authenticated Claude/Codex E2E | real host | Not executed | **Unverified** |

`subscription` entitlement, provider settlement, auxiliary provider calls and
tariff changes are **not** proven. Route grants bound supervisor dispatch
attempts, not tokens or dollars. There is no hard spend-cap claim.

## Verification snapshot

Round 2 correction evidence (offline; no paid model, install or live Doctor):

- Interpreter: Python 3.10.12
- `python3 -m compileall -q scripts`: exit 0
- Routing regressions:
  `python3 -m unittest discover -s scripts/tests -p 'test_v31_routing_observation.py' -v`
  — **13 tests**, exit 0.
- Claude dispatch regressions:
  `python3 -m unittest discover -s scripts/tests -p 'test_v31_dispatch_safety.py' -v`
  — **27 tests**, exit 0.
- Focused v3.1: `python3 -m unittest discover -s scripts/tests -p 'test_v31_*.py' -v`
  — **129 tests**, exit 0, 141.6 s.
- `test_p1_03_permission_overlap.py` 23 and `test_checkpoint_a_containment.py` 25 —
  both exit 0. Round 1 targeted F1–F4/F7–F9 suites remain inside the v3.1 and
  full runs.
- Full offline suite:
  `python3 -m unittest discover -s scripts/tests -v` — **708 tests**,
  4 skipped, exit 0, 366.0 s.
- The 4 skips are the optional installed-CLI V2 introspection suite; they are
  reported separately and are not counted as passed.
- Baseline red probes from Round 1 are preserved under
  `/tmp/opencode/ao-red-evidence/`; Round 2 red runs are under
  `/tmp/opencode/ao-red-r02/`. Temporary evidence is not a production test
  contract.
- No paid requests, authenticated E2E, real installer execution or Doctor
  against live config were performed.

Final counts are re-recorded in the Implementer's chat report. Do not treat this
document as Architect approval.

## Preserved artifacts and safety

- Read-only source mutation tests keep the modified source, report, dispatch,
  completion and `source-mutation.json`; there is no rollback, reset or clean.
  A live escaped child retains exact uncertain ownership.
- Route grant reservations/consumptions are preserved in
  `route-grants/ledger.json`; no parent snapshot resets them.
- Stale decisions are preserved in `invalidated_decisions`/failed-job history,
  not erased, and cannot authorize a transition.
- Migration backups are byte copies of the pre-migration `state.json`;
  `restore-run` validates before mutation and preserves the previous state under
  `restores/` with the backup hash.
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
4. `doctor` never executes inference and cannot prove entitlement; local Claude
   user/project/local settings and `managed-settings.d/*.json` fragments are
   inspected, but server/MDM-delivered managed settings, macOS managed
   preferences and executable policy helpers remain explicitly
   unobserved/unverified.
5. Exactly-once side effects, price/quota accuracy and arbitrary
   plugin/gateway/auxiliary route behavior remain outside the supervisor's
   guarantees; the routing fingerprint covers inspectable configuration only.
6. CI compatibility targets Python 3.10/3.12/3.13; only 3.10.12 was available
   locally. CI must run under separately authorized push.
7. Docker verification evidence is synthetic in the offline suite.

## Recommended review focus

1. Read the full `scripts/orchestrator.py` diff, especially containment/source
   independence, durable grant ledger, effective routing observation, Claude
   settings resolution and restore validation.
2. Re-run the adversarial suites and inspect that no validator was mocked green.
3. Confirm F1 escaped-child paths retain or clean exact ownership, and a clean
   stopped mutation blocks without phantom reconciliation.
4. Confirm F2/F3 billing and grant rules before spawn, and that nested Explorer
   consumption survives a stale parent save from a real separate process.
5. Confirm F5/F6 read actual temporary config/settings and fail closed, and that
   migration initializes pins without dispatch-time repinning.
6. Confirm F7’s complete command sequence and that neither grant nor consent
   silently authorizes the other.
7. Confirm F9 leaves destination bytes unchanged on invalid backup/write failure.
8. Label every claim by evidence class before any release decision.
