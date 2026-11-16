# E2E review recovery — final Architect acceptance

**Verdict: APPROVED WITH KNOWN LIMITATIONS.**
This accepts the single development remediation batch, including its focused
correction. It does not authorize staging, installation, model calls or mutation
of the preserved operational E2E run.

Accepted HEAD: `b9819a75c10433d9e8d082e049c2a31084d0e416`.
Checkout: `/home/abdullah/.local/src/abdullah-orchestrator-v3-1`.
Branch: `design/orchestrator-v3-1`.
Original batch BASE: `5d0b8be644580d7da7181d1e7ce05c42f8420d3b`;
correction BASE: `2ab20309ef4acf039b9e0ccb8806149c18788989`.
The original batch BASE has the same runtime as the user-approved
`0ea5381aa6e1a26e9ee0e1935c494b33800c62ae`; intervening changes are docs only.

Exact implementation/delivery commits:

| Commit | Purpose |
|---|---|
| `2ab20309ef4acf039b9e0ccb8806149c18788989` | Classified review admission, atomic verification rewind, authority epoch and regressions |
| `66033a82ce75e08242988b01254c2621e4cb28f4` | Bind recovered authority to producing job; retain artifact-integrity precedence; correction tests/docs |
| `b9819a75c10433d9e8d082e049c2a31084d0e416` | Inspectable verification logs/checksums only |

Production and tests are unchanged between `66033a8` and accepted HEAD. Actual
source/test SHA256 identities match the supplied evidence index. Tracked worktree
was clean on review entry and remains clean. Historical Architect briefs/reviews/
evidence remain untracked; this final review adds only uncommitted Architect
documents and evidence. No production edits or commits were made by Architect.

## Exact root cause and minimal correction

The preserved run `20261116T124500-973e8c02` reached review after completed
implementation and passed local verification. Interrupted Reviewer execution
was contained. On resume, review constructed its evidence package before any
cache/model use. The evidence loader correctly rejected provenance drift, but
review had no classified invalidation/rewind handler. Generic stage error handling
persisted blocked status while retaining phase review and the passed reference.
Resume cleared status/reason only, producing the repeated same rejection.
The acceptance stage already had related invalidation behavior; the special
uncertain-correction reconcile path was inapplicable without an active owner.

The investigation's read-only incident comparison found only two differing leaves:
`environment.values.PATH.sha256` and `toolchain.path_sha256`. All other compared
environment/toolchain fields, actual verification executable, configuration and
source matched. The failing process saved dimensions only, not a leaf snapshot;
the exact historical leaf list cannot be proven retrospectively. PATH remains
a real lookup dependency and was deliberately not ignored or normalized away.

The fix introduces a ValueError-compatible structured evidence rejection and
review admission that distinguishes compatible environment/toolchain/check-tool
drift from integrity/source/plan/config/runtime/unknown failures. Compatible drift
requires current plan/config/check/risk policy, complete runtime inputs, approved
resolvable executables and intact evidence/logs. Under existing ownership locks,
one atomic state save archives the old reference/hash and safe drift identities,
invalidates current/downstream authority, preserves implementation/source/batch/
plan/history/grants, and sets running/verify. It returns without dispatching checks
or models in that call. A subsequent stage performs fresh verification, then a
fresh required independent Reviewer and a new strong Architect acceptance.

## Finding-by-finding closure

| Finding / invariant | Final assessment |
|---|---|
| Original ownerless resumed-review loop | **Closed.** Markerless old schema-3 blocked runs can resume into classified admission and one durable rewind rather than repeat the same review rejection. |
| Strict provenance/source/config/plan/runtime/policy checks | **Preserved.** Compatible drift obtains new checks; unknown/integrity/unapproved changes remain classified blocks. No comparison or authorization is weakened. |
| Preserve completed implementation and historical evidence | **Verified in offline fixtures.** Source/dirty/ignored/untracked bytes, report, plan/batch position, accepted history and old verification/logs survive; no re-implementation on rewind. |
| Review-r01 F1: late recovery re-stamps an old Reviewer | **Closed.** Producing job/dispatch epoch binds apply and consumption. Old/legacy-unprovable-after-invalidation reports cannot acquire current authority. Commit-lock checks revalidate epoch/phase/batch/identity. Legitimate same-epoch and initial-epoch legacy controls pass. |
| Review-r01 F2: drift masks a missing verification log | **Closed.** Required record/log integrity is checked before authorizing recovery from drift. Missing/unreadable/log-reference failures take precedence and retain masked-drift diagnostics. |
| Fresh review and strong acceptance | **Verified with fakes.** Old completed/recovered/stamped caches cannot bypass a new Reviewer; fresh strong acceptance is required. No real provider inference used. |
| Crash/idempotence/concurrent invocation | **Focused tests pass.** One atomic state commit invalidates authority and changes phase; failed pre-commit retains rejection. State audit remains authoritative after journal interruption. Existing nonblocking supervisor ownership serializes separate processes. |
| Active/uncertain execution | **Preserved.** Recovery does not clear owners; containment/reconciliation must precede admission. Stopped-but-unreconciled identities stay guarded. |
| Single-/multi-batch, source acceptance and integration | **Regression coverage passes.** Batch position/prior history remain; later acceptance/integration revalidate required evidence. |
| Billing and compatibility | **No weakening identified.** No new grant, provider fallback or authorization is created. State/config schema 3 and model report v2 remain unchanged. |

## Independently executed verification

Evidence: [final Architect evidence](evidence/e2e-review-recovery-final-architect/README.md),
with checksums and exact output files.

| Execution | Actual result |
|---|---|
| `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts/tests python3 -m unittest test_v31_review_recovery test_report_ingestion test_checkpoint_b_provenance test_v31_acceptance_integrity -v` | **100 tests, OK, 0 skips, exit 0, 111.764 s**, Python 3.10.12 |
| Original saved `reproduce_review_loop.py` against disposable archive of exact BASE `5d0b8be` | Exit 0: reproduced two blocked/review attempts, no active job/check, old passed reference, zero model dispatches and preserved record bytes. This establishes failure, not acceptance. |
| Saved missing-log/PATH probe against accepted HEAD, with safe-outcome wrapper | **Blocked/review, log_missing, no recovery**, masked provenance drift retained; zero model dispatch. |
| Saved late public-recovery probe against accepted HEAD, with safe-outcome wrapper | **Old epoch 0 refused at run epoch 1**; phase stays review, no recovery record or new recovered report artifact. |
| Supplied source/test/evidence identity checks | All **7 evidence file checksums** match. Source/test digests match `66033a8`; evidence-only HEAD has no scripts diff. |
| Preservation/static checks | Original **227-file** incident/staged/project manifest matches; `git diff --check` passes; tracked tree unchanged. |

The wrappers leave original diagnostic scripts untouched and assert corrected
outcomes rather than treating an expected early refusal as a test failure. The
fresh-pipeline/same-epoch/race/corruption tests were executed as part of the
100-test run. No real model CLI, staged run command or original project check
was executed.

## Full-suite and red/green evidence independently inspected

Raw logs and manifest are committed under
`evidence/e2e-review-recovery-fix-b01-r01/`. Actual summaries, Python 3.10.12:

| Implementer execution at unchanged code/test revision `66033a8` | Inspected result |
|---|---|
| Correction tests at disposable correction BASE `2ab2030` | 36 tests; **10 failures, 1 error**, 74.603 s; controls also present |
| Green correction module | **36 tests, OK, no skips**, 84.239 s |
| Requested recovery/ingestion/provenance/acceptance/interactive/quota/stage regressions | **203 tests, OK, no skips**, 269.694 s |
| Complete offline suite | **866 tests, OK, 7 skipped**, 819.787 s |

These are inspected Implementer executions, not another Architect full-suite
run. A costly same-code repeat was unnecessary after identity verification and
the fresh focused/probe executions above. The seven skips are the opt-in real
OpenCode V2 integration tests; they are not passes. The permission-dependent
unreadable-log correction test ran, rather than being skipped. No claim of
Python 3.12/3.13 matrix or real Docker verification is made for this batch.

## State-machine safety and operational recovery

The development recovery path now provides an actionable next stage while
invalidating old authority atomically. No model/check runs during rejection or
rewind, and a crash cannot turn an invalid old reference into accepted evidence.
Historical records stay inspectable. Producing-epoch validation prevents delayed
or concurrent report extraction from resurrecting an old review. Strict route,
command policy, lease and compatibility gates remain independent prerequisites.

**The existing paused E2E run can recover in principle using an appropriately
staged corrected supervisor; restarting implementation is not inherently needed.**
Its schema-3/ownerless blocked-review shape is explicitly covered. This conclusion
is conditional on current compatibility, source/plan/config/policy, process and
route checks. It does not claim that the real run has been recovered.

**A disposable staged-copy validation is still required before operational
recovery.** Offline synthetic fresh-check → fresh-review → fresh-acceptance
validation has passed. Before touching the preserved run, obtain separate user
authorization, back up its state/artifacts/checkout, validate a truly isolated
copy with original live output/control paths rebased, and check supervisor,
configuration and billing-route compatibility. Any actual subscription-model
validation requires explicit authorization; none was performed here. Do not
manually edit the real phase/reference to force progress.

## Limits and final disposition

- No authenticated provider, live billing, real-model resumed E2E or long
  unattended behavior was tested during remediation.
- Original failing-process leaf provenance was not persisted; exact historical
  environment contents cannot be reconstructed from hashes/dimension-only logs.
- Legacy missing-epoch review recovery after invalidation is conservatively
  refused; explicit old epochs retain dry-run extraction without authority.
- Boundary snapshots/process markers retain documented limits; no OS isolation
  or transient write-and-restore detection is claimed.
- No install, staging, push, merge, deploy, global settings, Sanatry, prior pilot,
  manual-skill modification or automated orchestrator self-modification occurred.

The approved single implementation batch is complete at this source/test gate.
No further Implementer correction is required. **Final Architect verdict:
APPROVED WITH KNOWN LIMITATIONS; operational recovery remains a separate gate.**
