# E2E stale-review verification recovery — batch 01

Status: **APPROVED FOR IMPLEMENTATION — user-approved 2026-11-16.**
Architect date: 2026-11-16. Manual original Architect → separate Implementer.
Checkout: `/home/abdullah/.local/src/abdullah-orchestrator-v3-1`
Branch / actual BASE: `design/orchestrator-v3-1`,
`5d0b8be644580d7da7181d1e7ce05c42f8420d3b`.
User-approved runtime baseline: `0ea5381aa6e1a26e9ee0e1935c494b33800c62ae`.
The two intervening commits change documentation only; production is unchanged.
Tracked worktree was clean. Preserve this new untracked brief/investigation/evidence.

## Outcome and scope

User constraint: **deliver all remediation in this one cohesive implementation
batch**. Classification, rewind/persistence, cache safety, diagnostics/docs and
the entire regression matrix are one handoff and one Implementer delivery, not
successive planned batches. Architect review follows that delivery; any actual
review blocker still requires correction before acceptance.

Fix resumed-review rejection of stale verification so the supervisor exposes a
safe, durable path to fresh checks, fresh independent review and new strong
Architect acceptance, without repeating completed implementation. Preserve strict
provenance validation, source integrity, ownership, grants, schema 3 and report v2.

Incident: `20261116T124500-973e8c02`, preserved under
`/home/abdullah/ao-v31-e2e/state/runs/`. The isolated project, skill, run, config
and launcher are evidence only. Read [investigation](e2e-review-recovery-investigation.md)
and `evidence/e2e-review-recovery/`. Original user requirements in this session
govern any conflict; do not expand this into an orchestration redesign.

## Confirmed root cause and reproduction

`advance` review context calls `reviewer_verification_package` →
`verification_evidence_package` → `load_verification_evidence` before any cached
or new Reviewer. That loader correctly raises on drift, but review has no
classified invalidation/rewind handler. `stage_run` catches the generic error,
blocks and persists the same review phase and passed verification reference.
`modify_locked(..., 'resume')` clears status/reason, not phase/reference. Repeats
hit the identical gate. `reconcile --retry-verification` is a special uncertain
correction path requiring an active owner, not applicable here. Acceptance already
has related invalidation and `clear_stale_acceptance` mechanisms.

The historical journal records `environment, toolchain` only. Fresh read-only
comparison against the preserved verification identifies exactly two differing
leaves: `environment.values.PATH.sha256` and `toolchain.path_sha256`, both from
`be9b7af8...a9ccd0` to `394a55a3...555e7`. All other environment/toolchain fields,
the actual `python3` check fingerprint, configuration and source projection match.
No executable replacement is observed. The original failing process did not save
its current leaf snapshot: do not present today's comparison as proof of every
historical leaf. PATH affects command/import/dependency lookup and remains a real
verification dependency even when selected tools currently resolve identically.
Do not drop PATH, toolchain fields or hashes to make evidence pass.

Execute the saved disposable `reproduce_review_loop.py <checkout>` at BASE.
It produces real passed checks, prepends an empty PATH directory, and demonstrates
two persisted blocked-review attempts with zero model dispatch, unchanged
implementation and unchanged historical record. It intentionally asserts the old
failure; add proper red/green recovery tests rather than weakening this diagnostic.

## Approved design

1. **Classify evidence rejection at its origin.** Add a small structured rejection
   compatible with existing ValueError callers (or equivalent existing pattern).
   Carry reason codes/dimensions and safe field-level identities, distinguishing
   environment/toolchain/check-executable drift from source/plan/config/policy
   changes, incomplete manifests, missing/corrupt/failed evidence and unknowns.
   Do not parse English exception text. Preserve all rejection checks. Persist
   names/presence/hashes, never environment values or credentials.
2. **Handle review admission locally, before cache/model use.** Use one coherent
   current observation. If modern previously passed evidence has unchanged source,
   complete inputs, current plan/config and approved checks/risk policy, and only
   environment/toolchain/check-executable drift, invalidate current authority and
   rewind to `verify`. Re-evaluate current executable resolution and command policy:
   a newly disallowed/unavailable/unprovable command requires a precise block and
   an actionable existing authorization/config-repair path, not automatic consent.
   Source/plan/config/integrity/unknown rejection must not be laundered into fresh
   authority. Keep it blocked with classified cause and concrete next action.
   Existing explicit compatibility/migration and route gates remain in force.
3. **Atomic durable transition.** Under the existing exclusive supervisor lock and
   checkout lease admission, preserve the old evidence file/logs and audit its
   reference/hash, reason, batch/plan identity and safe before/after differences.
   In one state commit clear current verification/check-progress/single-batch
   verification, downstream review/Architect authority and stale retry eligibility;
   preserve implementation/report/source, batch position, plan, prior accepted
   batches and grants/usage. Set phase `verify`, status `running`, with a recovery
   explanation and next action `orchestrator_stage`. Return from this stage without
   executing checks or models in the same call. Journal the explicit recovery
   transition with an idempotent identifier linked to durable state. Crash before
   state commit retains rejection; crash after commit cannot resurrect authority.
   State is authoritative if journal append is interrupted; retain audit data in
   the same commit and avoid duplicate invalidation on retry.
4. **Disarm downstream caches.** Clearing state.review alone is insufficient:
   `cached_job_report` and `cached_recovered_job_report` currently use source-based
   eligibility. Prevent pre-invalidation Reviewer/recovered review/decision reports
   from being reused after fresh verification of identical source. Reuse existing
   invalidation patterns and the smallest targeted generation/reference binding
   needed; preserve job/report history. Do not reset implementation eligibility or
   globally alter amendment epochs. New verification must lead to a new independent
   Reviewer when policy requires it, then a new strong acceptance. An incomplete
   interrupted Reviewer never becomes a reusable completion.
5. **Existing blocked runs.** No pre-existing recovery marker is required: after
   explicit resume, the corrected review admission reevaluates the old reference
   and performs the same classified transition. Active/uncertain ownership always
   takes precedence; never clear it to recover provenance. Keep resume free of
   inference and avoid a new operator command unless an unavoidable blocker is
   escalated. Update maintained recovery docs and next-stage diagnostics.

Prefer extending `load_verification_evidence`, review admission and existing
invalidation/cache helpers. Keep acceptance/integration protections at least as
strict; adapt shared callers only where the new classified contract requires it.
No new execution framework, automatic environment restoration, schema migration,
provider fallback, grant or implicit re-authorization is approved.

## Acceptance / executable regression matrix

- [ ] Actual saved failure reproduced at BASE and recovery passes after the fix;
  strict loader still refuses old evidence. Original evidence bytes preserved.
- [ ] Environment-only/PATH drift, actual verification executable replacement,
  and broader toolchain drift classified separately. Current policy allows safe
  rerun; disallowed/unresolved tools produce actionable block without executing.
- [ ] Interrupted Reviewer then drift, no active job/check; no partial report reused.
- [ ] Repeated resume/stage, including an existing markerless blocked schema-3 state,
  durably reaches verify once, without re-implementing or consuming grants/models.
- [ ] Fresh checks followed by a fresh fake independent Reviewer and fresh fake
  strong acceptance. Include both unconsumed completed and recovered old caches.
- [ ] Unknown, failed/missing/corrupt evidence, source/runtime/config/plan/policy
  changes cannot become implicitly accepted. Incomplete manifests remain blocking.
- [ ] Any uncertain or active job/check blocks admission/recovery. Containment and
  reconciliation remain authoritative, including a stopped-but-unreconciled owner.
- [ ] Crash seams before/after atomic state save and during journal append; restart
  cannot recover stale authority or repeat implementation. Transition audit is
  recoverable/idempotent. Use genuine separate-process concurrent stage/resume
  contention to verify existing single-owner serialization.
- [ ] Single- and multi-batch runs preserve batch position/prior accepted history;
  next batch does not inherit old review/decision authority. Integration still
  revalidates every required reference; no blanket trust of earlier records.
- [ ] Model dispatch spies/fake CLIs prove zero calls on rejection/rewind, no
  ungranted alternative route, no grant/usage inflation. Source/dirty/ignored
  content and implementation reports remain byte-identical across recovery.

## Verification and delivery

Use disposable fixtures, fake model CLIs and real local verification subprocesses.
Never dispatch actual paid or subscription models, including version/config
inspection paths that are unnecessary for these offline regressions.
Add a focused recovery module and run relevant existing modules:
`test_checkpoint_b_provenance`, `test_v31_acceptance_integrity`,
`test_v31_stage_invariants`, `test_interactive_recovery`,
`test_v31_campaign_integration`, `test_v31_route_migration`,
`test_checkpoint_a_containment` and affected billing/cache tests. Then run one full
offline `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts/tests -v`.
Report actual interpreters/skips/results. The incident preflight report documents
a pre-existing timing-sensitive deadline-test failure; if it recurs, distinguish
it from this fix, preserve evidence, and do not change correct runtime or silently
claim a full pass. Escalate unrelated required corrections rather than refactor.

Single worker preferred. Authorized touch points: development supervisor module,
focused tests/fixtures and maintained recovery/validation docs. Cohesive local
implementation commits are authorized **after design approval**, no push. Do not
commit or alter Architect artifacts except explicit new verification evidence.
Do not write anywhere in `/home/abdullah/ao-v31-e2e/`, installed/global settings,
Sanatry or prior pilots. Rebased incident copies must not retain live original
project/output/control paths; synthetic fixtures are preferred. No install,
staging over the isolated skill, deploy, merge, reset, real state edits or automated
orchestrator self-modification. A future operational recovery needs separate
authorization, backup and validation on a disposable copy first.

Return a copyable original Architect report: BASE/HEAD/branch/worktree, exact
commits, root cause and minimal changes, every acceptance row/evidence, red/green
and full-suite results including skips/failures, crash/concurrency proof, source/
state/grant preservation, compatibility assessment for the paused schema-3 run,
whether a fresh disposable integration is required, deviations and open blockers.
Architect will independently inspect the diff and rerun the failure before final
acceptance. **This brief authorizes development implementation, not final acceptance or permission
to recover the preserved operational run.**
