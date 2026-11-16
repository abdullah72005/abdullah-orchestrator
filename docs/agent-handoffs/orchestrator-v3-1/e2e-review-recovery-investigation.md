# E2E recovery blocker — Architect investigation

Date: 2026-11-16. **CHANGES REQUIRED; design user-approved 2026-11-16.**
One cohesive Implementer batch is proposed in
[the complete handoff](e2e-review-recovery-batch-01.md). No production fix or
operational recovery has been performed. No final acceptance is claimed.

## Repository and preserved incident

Development checkout: `/home/abdullah/.local/src/abdullah-orchestrator-v3-1`,
branch `design/orchestrator-v3-1`, HEAD
`5d0b8be644580d7da7181d1e7ce05c42f8420d3b`. Initially clean, no tracked changes.
The commits since approved `0ea5381aa6e1a26e9ee0e1935c494b33800c62ae`
are documentation-only (`37ce70d`, `5d0b8be`). Development and isolated staged
`scripts/orchestrator.py` both hash to
`bb0d4b0b47366cb393ab2d197d726ff5ad53cdc11b0df9d926a6bb83f0e85b31`.

Incident run: `20261116T124500-973e8c02` under
`/home/abdullah/ao-v31-e2e/state/runs/`. Read state, journal, original verification,
dispatch metadata, launcher and preflight report; never invoked the supervisor
against that run or executed checks/models in its project. Its final state is
blocked/review, null active job/check/review, passed verification reference,
preserved implementation and no accepted batches.

## Exact cause

Review admission at `advance` around lines 10141–10164 constructs a verification
package before looking for cached or new Reviewer reports. Its loader around
9729–9786 correctly rejects environment/toolchain drift. There is no local
classified recovery handler. The generic `stage_run` exception path around
12100 calls `pause_with`, which sets status blocked but leaves phase review,
verification and downstream eligibility unchanged. Resume around 11495 only
clears status/reason. Therefore each stage attempt rejects the same old record.

The journal confirms resumed attempts at 12:55:37 and 12:55:52, both ending with
`Verification provenance drifted since the check: environment, toolchain` and
`next_action=orchestrator_resume`. The paused event's `phase=blocked` field is a
journal-field override from `pause_with`'s status parameter, not evidence that
the state-machine phase changed: persisted phase and stage_end remain review.

Acceptance already catches evidence errors, invalidates decisions and calls
`clear_stale_acceptance` to return to verify. Review lacks this behavior. The
existing reconcile retry-verification option handles an uncertain correction
dispatch with an active identity and special evidence; this ownerless blocked
review cannot use it. Manually assigning phase or weakening provenance would
bypass the missing contract rather than fix it.

## Which provenance changed

The original record contains complete version-3 provenance and evidence-v2
checks. Verification ran `python3 -m unittest discover -s tests -t . -v` and its
log records 44 successful tests. The original Reviewer dispatch source has the
same PATH fingerprint as verification.

Fresh read-only comparison from this investigation identifies exactly:

| Field | Recorded | Observed now |
|---|---|---|
| `environment.values.PATH.sha256` | `be9b7af849bb1074c16f93205ded5d48ae28fb8d900c2075322dc210e7a9ccd0` | `394a55a392f528c4f2253845c94938362feda5acc8ee7928ae27277d623555e7` |
| `toolchain.path_sha256` | Same recorded PATH hash | Same current PATH hash |

All other compared environment/toolchain leaves, config, check executable
fingerprints and source signature/write projection match. In particular the
verification tool remains `/usr/bin/python3.10`; Git, Node, Docker and uv
observations are unchanged. Thus the present mismatch is the PATH string bound
twice, not an observed tool upgrade. No raw environment values were saved.

The failing resumed process did not persist its current snapshot/leaf delta.
The exact historical leaf list or PATH contents cannot be recovered from its
dimension-only error. Today's comparison is consistent with the incident but
must not be represented as a historical observation that was never saved.
The proposed structured diagnostics close this evidence gap for future failures.

PATH is process/host context but also a real command/import/subprocess dependency.
The broad toolchain includes tools this particular Python check does not directly
invoke; their unchanged identities did not cause this observed rejection.
Even an empty-directory PATH edit correctly invalidates the recorded environment
under current conservative policy. The fix preserves comparison and obtains new
checks; it does not normalize away the difference or assume semantic equivalence.

## Independent executable evidence

In `evidence/e2e-review-recovery/`:

- `reproduce_review_loop.py <checkout>` creates a temporary fixture with real
  passed supervisor checks and unchanged implementation, prepends an empty PATH
  directory, and exercises stage → resume → stage. Both attempts persist
  blocked/review with the old passed reference. Zero model calls; original
  verification bytes preserved. Exit 0 means the failure was reproduced, not fixed.
- `reproduction.jsonl` records both attempts and safety observations.
- `incident-provenance.json` records the present comparison and explicitly marks
  missing historical leaf-level evidence.
- Baseline command: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts/tests python3 -m unittest test_checkpoint_b_provenance test_v31_acceptance_integrity -v`.
  **33 tests, OK, zero skips, 31.989 seconds, exit 0**, Python 3.10.12.
- Preservation manifests cover 227 regular files under isolated skill, project
  and incident run, before/after diagnostics; all remained identical.

Full suite has not been executed during this design investigation. It is required
after implementation. The isolated preparation report also documents a known
environment-sensitive deadline assertion failure (pre-child expiry despite an
assertion expecting a failed child); do not conflate it with this recovery defect
or silently suppress it if it appears in the required full run.

## Minimal design and alternatives

Recommended: typed evidence rejection + policy-aware review admission, one atomic
invalidation/rewind state save, preserved audit reference, targeted downstream cache
disarming and explicit next-stage diagnostics. Reuse existing locks, state saving,
journal and invalidation patterns. A later stage runs checks; no model executes
during rejection/rewind. Fresh verification requires fresh independent review
and strong acceptance. Preserve implementation, source, grants and batch position.

An operator-only new retry command would add surface and leave normal resume
without the requested transition. Dropping PATH/toolchain comparisons would
weaken evidence and is rejected. Neither is needed for the proposed bounded fix.

Completed/recovered Reviewer caches deserve explicit tests: current eligibility
is mainly source-based, so identical source after fresh checks could otherwise
reuse a pre-invalidation report. Clearing state.review alone is insufficient.
Unknown ownership/config/policy/integrity failures must remain actionable blocks;
the recovery transition cannot grant permission or erase an uncertain owner.

## Existing-run recovery and verdict

No new operational run is inherently necessary for this failure: the existing
schema-3 run retains implementation and evidence and has no active owner. The
proposed corrected review handler can recognize that old blocked shape after
explicit resume without a pre-existing marker or manual state edit. This is a
design expectation requiring executable regression proof, not approval to recover
the actual paused run now.

A new disposable recovery/integration fixture **is required for validation** of
fresh checks → new Reviewer → new Architect acceptance, using fake CLIs during
remediation. Corrected supervisor staging for the preserved E2E run needs separate
authorization, backups, compatibility/config/route checks and successful validation
on an isolated copy first. Never write the real run, project or staged skill here.

**Architect verdict: confirmed recovery defect; CHANGES REQUIRED.** One complete
implementation handoff is prepared and user-approved for development implementation.
Final root-cause closure, crash/concurrency assessment and acceptance will follow
independent review of the actual implementation and required test evidence.
