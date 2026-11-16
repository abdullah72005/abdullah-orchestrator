# E2E recovery — Architect review round 01

**Disposition: CHANGES REQUIRED** at
`2ab20309ef4acf039b9e0ccb8806149c18788989`.
BASE: `5d0b8be644580d7da7181d1e7ce05c42f8420d3b`.
Checkout/branch: `/home/abdullah/.local/src/abdullah-orchestrator-v3-1`,
`design/orchestrator-v3-1`. One implementation commit, `2ab2030`.

The original ownerless blocked-review loop is corrected for isolated compatible
drift. Classified diagnostics, atomic rewind and cache epochs are appropriate
within the approved design. Two reproduced acceptance-path defects remain.
Use the [same-batch correction brief](e2e-review-recovery-fix-b01-r01.md).
No new feature batch or design expansion is proposed.

## Review basis and verification

Actual HEAD/branch match the Implementer report; tracked worktree clean. The
original Architect brief/investigation/evidence remain untracked. Inspected the
production diff (636 diff lines), new regression module and maintained docs.
No production edits or commits were made by the Architect.

Independently executed:

`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts/tests python3 -m unittest test_v31_review_recovery test_checkpoint_b_provenance test_v31_acceptance_integrity -v`

Result: **56 tests, OK, 0 skips, exit 0, 87.760 s**, Python 3.10.12.
This includes the real-check/fake-model fresh pipeline, original incident-shaped
rewind, policy rejection, ownership, crash, cache and separate-process tests.
The earlier investigation independently reproduced the old loop on the exact
runtime baseline. Additional independent disposable probes at this HEAD reproduce
the two failures below. Their exits indicate reproduced defects, not acceptance.

Evidence: `evidence/e2e-review-recovery-review-r01/`, checksummed.
All 227 regular files in the preserved E2E project, staged supervisor and incident
run match the investigation's preservation manifest. No operational run commands,
actual models, installs, push, global settings or unrelated repositories changed.

The 202-test and 853-test results in the Implementer report are **reported
Implementer executions**, not independent Architect reruns. No full-suite raw
log was supplied in the tracked delivery; the maintained validation page records
the summary. A new full run is deferred while blockers remain. The stated final
test-only strengthening does not invalidate unchanged production coverage, but
the next delivery must include inspectable logs and revision identities.

## F1 — P1: late report recovery promotes stale Reviewer authority

Location: `recover_report`, especially state append at `orchestrator.py:9696`,
and `cached_recovered_job_report` at 9708 onward.

New recovery records are stamped with **latest state.authority_epoch**, not the
epoch of the failed job/dispatch that produced the report. An old Reviewer that
was not recovered before invalidation can therefore be recovered afterward and
appear new to the cache filter. Existing tests cover recoveries already applied
before rewind; they do not exercise this late application path.

Independent public-path reproduction:

1. Produce passed checks and a valid terminal, successful-process Reviewer event
   stream whose report ingestion failed, original job/dispatch epoch 0. All data
   are synthetic; the snapshot is checked against a real disposable Git tree.
2. PATH drift triggers the real rewind to epoch 1; fresh real verification returns
   to review. No new Reviewer has executed.
3. Pause the synthetic run and call public `recover_report(..., apply=True)` with
   the exact acknowledgment and permitted fixture operator configuration.
4. The old report is applied with recovered epoch 1. The cache accepts it; resume
   and review advance to **accept with zero fresh Reviewer calls**.

Observed JSON: `original_job_epoch=0`, `run_epoch=1`, `recovered_epoch=1`,
`old_report_cache_eligible=true`, `phase_after_review=accept`,
`new_reviewer_calls=0`.

This is an explicit fresh-review invariant violation, even though report recovery
requires an operator acknowledgment. That acknowledgment permits extraction of
preserved text; it does not authorize resurrecting invalidated review authority.
Source equality cannot repair the missing relationship to the fresh verification.

Smallest correction: bind recovery authority to the original producing job/dispatch
epoch, reject old/missing-after-invalidation authority both on apply and consumption,
and revalidate epoch/phase/current identity under the exclusive commit lock.
Preserve historical extraction and same-epoch legitimate recovery without granting
an old report new authority. Do not disable recovery wholesale.

## F2 — P2: drift masks missing verification artifacts

Location: `load_verification_evidence:9904`, package construction around 9947,
and `_review_recovery_precondition:10131`.

The loader raises recoverable provenance drift before the package loads command
logs. The precondition checks commands/policy but never checks those logs. A missing
log by itself blocks (`log_missing`), as the new test shows; the same missing log
plus an empty-directory PATH change is classified as recoverable and rewinds.

Independent probe: create a real passed verification, remove its command log,
prepend an empty PATH entry, invoke stage with model dispatch forbidden. Actual
state becomes **running/verify**, `review_recovery` present and rejection null.
Expected under the approved contract: **blocked/review**, classified missing-log
cause, no recovery authority and zero check/model calls. Original record and any
remaining artifacts must remain intact.

Fresh checks would not directly accept the missing old log, but this still
launders an explicitly nonrecoverable integrity failure into an automatic recovery
transition. The requirement says compatible provenance drift only; a concurrent
artifact failure must take precedence.

Smallest correction: validate required non-provenance record/package integrity
before deciding drift is the only rejection, without executing checks/models or
ignoring drift. Add combined-failure tests rather than reorder away the original
strict checks. Cover missing/unreadable/log-reference failures plus drift.

## Remaining disposition

| Contract | Assessment |
|---|---|
| Original loop, source/implementation preservation, compatible drift rewind | Focused tests pass; basic correction retained |
| New verification → genuinely fresh independent Reviewer | **Blocked by F1** |
| Missing/corrupt/integrity failures stay blocked alongside drift | **Blocked by F2** |
| Existing active/uncertain ownership, atomic state save, journal interruption | Focused regressions pass; preserve behavior |
| Existing billing/grants and schema/report versions | No weakening identified in inspected changes; preserve focused and full-suite checks |
| Existing paused run recoverability | Plausible design remains, but not operationally approved while these blockers remain |

Do not touch the preserved E2E run or stage a corrected supervisor yet. No new
operational run is inherently needed to retain its implementation; a disposable
fresh-pipeline validation is still required after correction. Final acceptance
is withheld pending the focused same-batch fixes and independent re-review.
