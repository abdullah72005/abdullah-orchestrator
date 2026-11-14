# AOR31 — Batch 01 correction round 03

Status: **CHANGES REQUIRED — within the existing approved remediation scope.**
Checkout: `/home/abdullah/.local/src/abdullah-orchestrator-v3-1`
Branch: `design/orchestrator-v3-1`
Correction BASE: `2c316d41c9fb281131a6d5196eb2adf20c2c7a2d`.
Original BASE: `b9139946db5684e3e48724b9e1060af355362e82`.
Parent: [approved batch](aor31-remediation-batch-01.md).
Review/evidence: [round 03 review](aor31-review-r03.md),
`evidence/aor31-review-r03/`. Use a fresh original Implementer session.

## Outcome and revised implementation approach

Close the three reproduced defects below. Preserve the passing actual-version,
native V1 remap, relative config-directory, plugin, cache, grant, nested-source,
deadline and contention corrections. No unrelated audit or refactor.

Repeated inspection/account corrections show that adding individual guesses or
more polling is not converging on the approved invariant. Change the approach:

1. Resolve account storage from the pinned upstream storage contract, and bind
   the stable account-routing metadata that was authorized, not the whole mutable
   session database. Keep physical observation/audit details separate from the
   route-material projection where appropriate.
2. Use the existing guarded execution, inherited identity markers, durable launch
   records and reconciliation machinery for inspection ownership. A sampled PID
   list plus successful leader exit is not proof of stopped execution. Do not
   attempt another fix by extending the poll interval, adding sleeps, or retaining
   only an exception string. No new independent executor/framework is approved.

If this cannot be integrated within the existing ownership architecture, stop
and report that architectural blocker before attempting another substitute.
This is the required reassessment after recurring failures, not a change to the
user's security contract or permission to rewrite unrelated subsystems.

No automated orchestrator self-modification, live inference/account requests,
plugin execution, install, push, release, deploy, destructive Git, real saved-run
mutation or manual-skill edits. Disposable fixtures/processes only. Cohesive local
commits are authorized. Preserve all Architect artifacts and existing user files.
Keep model report v2 and schema 3; additive internal ownership metadata must be
backwards-compatible and must not recertify old approvals.

## R03-F1 — P1: relative account DB resolves to the wrong store

Location: `_opencode_account_store:2437`, `_opencode_data_dir`, source boundary
and fingerprint callers.

Saved reproduction: active account/org DB at
`$HOME/.local/share/opencode/selected.db`; `OPENCODE_DB=selected.db`; child
project has no file of that name. Preflight returns `ok=true`,
`go_subscription`, `account_store=null`, no hazards. The supported V1 loader
resolves relative DB names under **Global.Path.data**, not project cwd:
[upstream path()](https://github.com/anomalyco/opencode/blob/v1.18.35/packages/core/src/database/database.ts).

Correction: implement the actual supported DB-selection rules, including
relative/absolute/special/default cases and relevant channel/data-root behavior.
Do not reuse explicit-config path rules for a different upstream contract.
Variables that upstream does not honor must not divert the safety scan from the
child's actual store. Refuse an unresolved storage boundary rather than treating
the wrong missing file as proof of no account routing. Do not fetch or refresh
accounts or migrate/write a real database.

Tests: exact saved relative case, absolute path, default data root, explicit data
root and channel selector cases within supported behavior, missing/unreadable/
malformed stores, and clean legacy Go. Assert the inspected store is the one the
child will use, and active account metadata refuses before inference/grant use.
Use pinned source-backed fixtures; do not claim real V1 execution.

## R03-F2 — P2: ordinary session writes invalidate an unchanged Go route

Location: `_opencode_account_store` raw `_sha256_file(path)` and its insertion
into `source_identity` / route material.

Saved reproduction: one SQLite DB has empty account tables and an unrelated
`session` row. First pinned Go preflight succeeds. Only update the session title;
second preflight refuses with “pinned ... routing material changed”. Account
count, active selection and table set are identical. The whole-DB hash changes.
OpenCode stores sessions and account metadata in the same DB, so normal CLI
session activity can break subsequent valid legacy Go dispatches. Fake CLIs do
not naturally exercise this activity.

Correction: derive a deterministic content identity of the **routing-relevant
account metadata** observed read-only. Do not put a whole mutable history DB
digest into the route pin. Avoid unrelated table names/session rows/SQLite layout
or checkpoint churn becoming material routing. Preserve DB path/source selection
identity and fail closed for account/active-org changes or uninspectable metadata.
Do not auto-repin or relax actual route drift detection. Correct the misleading
claim that token columns are never hashed while the entire DB is hashed.

Tests: unchanged account-routing metadata across session create/update, other
ordinary history writes and benign empty-store initialization keeps the pinned
route valid; an account row or active-org change still refuses before spawn.
Exercise the real pin/preflight/second-dispatch boundary with disposable SQLite,
not a mock claiming a stable fingerprint. Preserve existing label-only grant
refusal, material drift and credential-free diagnostics. No real V1 inference.

## R03-F3 — P1: escaped inspection and failed cleanup lose ownership

Locations: `_opencode_run_bounded:2175`, descendant polling/containment at
2109–2172, `InspectionContainmentError` handling at 2284 and callers.

Two confirmed cases:

- A parent has no descendants at the real ownership snapshot, then starts a
  closed-stdio child with `start_new_session=True` and exits inside the next
  communicate interval. The helper returns 0/valid JSON while the child is alive.
  The saved test uses a readiness seam that releases the parent **after a real
  empty descendant scan**; it does not fake a stopped process. Existing escape
  tests hold the parent alive for 0.4 s and therefore miss this window.
- Deny termination during `call_model` config inspection. A live inspector
  remains, but saved run status is `blocked`, `active_job`/`active_check` are null,
  and its PID is absent from saved state. Only
  `inspection_reason=inspection_containment_unproven` remains. The helper-level
  test named “retains ownership” checks only an exception; it does not verify
  durable ownership or progression gates.

Correction: establish an owned inspection execution **before** its child can
spawn, using the existing guard/marker/launch protocol. Scan inherited exact
markers as well as sessions and recorded descendants after leader exit, including
normal success, regrouping and setsid. Persist exact identity (PID/start/session/
group, launch references, tracked descendants as applicable) where recovery can
find it. Use the existing identity fields and protocol. Raw secrets and full
child environments must not enter diagnostics.

If cleanup is unproven, retain durable **uncertain ownership** and block further
execution/admission until exact termination/reconciliation is proven. Do not turn
that failure into an ordinary route rejection and discard its owner. Preserve
the no-phantom-inference-job and zero-model-accounting contracts; use a distinct
owned preflight/check execution as appropriate within existing machinery.
Cancellation, resume/retry, recovery and administrative ownership gates must
respect it. For non-run Doctor inspection, preserve enough exact metadata for
failure handling rather than claiming containment from a dead leader.

Tests: the exact post-snapshot fast detached-child case, leader-exits-first,
regrouped/setsid children, child after a polling boundary, and denied termination
through the **production dispatch/stage boundary**. Assert durable identity and
uncertain status, no next inspector/model dispatch, explicit recovery after proven
cleanup, and no grant/model-call consumption. Recheck cold-version deadline/cancel
and successful real V2 normalization with the guarded path. Verify test-owned
processes are stopped even when a regression exposes a leak. Do not claim OS
isolation or resistance to arbitrary same-user identity tampering.

## Verification and delivery

- Add meaningful red regressions at `2c316d4` in a disposable archive/copy, then
  green at the correction HEAD. The saved diagnostic scripts emit observations;
  exit 0 alone is not a safety pass.
- Run the affected focused suites and saved original/round-01/round-02/round-03
  probes. Once they pass, finish the parent brief's full offline suite and real
  supported V2 checks. Retain exact commands, versions, counts, skips, logs and
  hashes against the final commit.
- Python 3.12/3.13 are absent as host commands, but existing Docker images were
  found read-only: `orchestrator-integration-3ornvc:latest` and
  `python:3.13-alpine`. Use disposable test containers where suitable rather than
  declaring these interpreters categorically unavailable. Preserve other
  containers/images; no host interpreter or orchestrator installation. If a
  concrete image prerequisite prevents a run, report that exact unmet prerequisite.
- Update maintained docs for the actual account identity and uncertainty/recovery
  contract. Do not broaden unrelated features or rewrite historical evidence.
- Return a copyable report: original/correction BASEs, exact local commits and
  HEAD/worktree, three-finding closure matrix, red/green evidence with log paths,
  full final verification matrix/skips, deviations and remaining limitations.
  No push; Architect acceptance remains independent and pending.
