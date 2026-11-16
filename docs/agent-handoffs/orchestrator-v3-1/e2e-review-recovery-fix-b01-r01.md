# E2E recovery — same-batch correction round 01

Status: **CHANGES REQUIRED — within the existing user-approved single batch.**
BASE: `2ab20309ef4acf039b9e0ccb8806149c18788989`.
Checkout: `/home/abdullah/.local/src/abdullah-orchestrator-v3-1`
Branch: `design/orchestrator-v3-1`.
Parent: [approved complete batch](e2e-review-recovery-batch-01.md).
Evidence/findings: [Architect review](e2e-review-recovery-review-r01.md),
`evidence/e2e-review-recovery-review-r01/`.

Keep the original approved single-batch scope. Correct these two verified gaps
in one fresh original Implementer session. Retain the passing basic rewind,
typed diagnostics, preservation, crash and process-ownership behavior. This is
review correction of the existing batch, not a new planned feature batch.

## F1 — old Reviewer authority must not be refreshed by report recovery

- Public `recover_report` currently applies an epoch-0 Reviewer report under the
  latest epoch 1 after fresh checks. Consumption accepts it and advances to accept
  with zero new Reviewer calls. Run the saved `review_probes.py` to observe this.
- Bind authority to the original producing job/dispatch, never to application
  time. Once invalidated, an old report cannot acquire current authority, even
  through a newly applied or re-applied recovery record. Legacy missing epochs
  may mean 0 only where compatible with unchanged initial authority.
- Enforce this on recovery application **and** consumption. Validate the latest
  original job identity, epoch, phase and batch under the exclusive commit lock;
  a race after preliminary validation cannot promote an old report. Preserve
  audit/extraction, exact operator acknowledgment and valid same-epoch recovery.
- Add regressions through the public recovery API using a real terminal event
  stream/snapshot: recover old failed review only after invalidation/fresh checks;
  reapply an old recovery; race the epoch change during apply; legacy epoch 0
  controls; current-epoch recovery still works. After blocked old recovery, a
  genuinely fresh fake Reviewer and strong acceptance must be required.

## F2 — simultaneous integrity failure must not be masked by drift

- A missing command log alone blocks, but alongside PATH drift currently rewinds
  to verify. Required evidence integrity must be established before declaring
  provenance drift the only issue eligible for automatic recovery.
- Validate required record/package/log integrity without running checks/models.
  Nonrecoverable missing/unreadable/malformed required artifacts take precedence
  over compatible drift. Keep strict source/config/plan/runtime comparisons and
  old evidence bytes; do not bypass drift, manufacture logs or weaken the gate.
- Add combined PATH/environment/toolchain/check-executable drift plus missing
  log, missing log reference and unreadable log cases where permissions allow.
  Assert blocked/review, classified actionable error, unchanged authority epoch,
  no automatic recovery, zero checks/models and preserved remaining artifacts.
  Retain clean drift → verify and clean evidence → fresh review controls.

## Verification, permissions and delivery

Allowed touch points: production recovery/evidence/cache helpers and focused tests,
plus maintained documentation only where semantics/evidence need correction.
No unrelated refactor, new recovery command, blanket recovery disablement, weaker
ownership/provenance/billing checks, schema bump or report-v2 change.

Run the new cases red at this BASE and green after correction, the complete
`test_v31_review_recovery`, `test_report_ingestion`, provenance/acceptance/cache/
interactive recovery regressions, then the full offline suite once. Supply raw
logs with commands, interpreter, exact source/test revision and checksums; do not
substitute summary text for inspectable evidence. Distinguish skips, passes and
pre-existing failures. No need to repeat a lengthy same-code full run for a final
test-only assertion if that exact changed test is rerun and disclosed.

Use disposable fixtures/fake model paths only, sequentially with marker-based
tests to avoid fixture run-ID interference. No real models, live run changes,
staging/install, push, merge, deploy, global settings, manual-skill edits or
automated orchestrator self-modification. Preserve the original E2E environment
and all Architect artifacts; validate its 227-file manifest read-only.

Commit cohesive local corrections; do not push. Return the standard copyable
Architect report with exact BASE/HEAD/commits, root causes, acceptance mapping,
actual test/red/green/full results, preservation and remaining limitations.
No operational recovery or final acceptance is authorized by this correction.
