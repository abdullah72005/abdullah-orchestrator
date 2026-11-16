# E2E recovery Architect review round 01 evidence

Reviewed HEAD: 2ab20309ef4acf039b9e0ccb8806149c18788989.
BASE: 5d0b8be644580d7da7181d1e7ce05c42f8420d3b.

Independent command, Python 3.10.12:
`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts/tests python3 -m unittest test_v31_review_recovery test_checkpoint_b_provenance test_v31_acceptance_integrity -v`
Result: 56 tests, OK, no skips, exit 0, 87.760 s (`focused.log`).

`PYTHONDONTWRITEBYTECODE=1 python3 review_probes.py <absolute-checkout>`
Result: exit 0, two reproduced defects (`review-probes.jsonl`). These are
observations of unsafe transitions, not passing acceptance tests. JSON outcomes
were additionally asserted before recording metadata.

The script uses real disposable Git/verification/report-ingestion fixtures.
It removes a test-owned verification log for F2. For F1 it produces a terminal
Reviewer stream and snapshot with the existing report-ingestion fixture, runs
the real rewind and fresh checks, then applies public recover_report with the
exact acknowledgment in an operator-enabled disposable config. The original
job/dispatch epoch is 0 but recovery is stamped 1; old review advances to accept
without another Reviewer. The synthetic active lease shape matches the public
report-ingestion harness; no real lease or run is edited. No provider calls.

Run this script sequentially after other marker-based tests: fixture run IDs
are shared across tests. Initial diagnostic setup attempts were corrected to
avoid concurrent fixture interference and provide the required synthetic lease;
the saved final execution is complete and successful. They were not product
failures and are not included in acceptance evidence.

The original 227-file preserved incident manifest was revalidated with zero
mismatches. Only Architect review/fix/evidence artifacts were added. See
../../e2e-review-recovery-review-r01.md for findings and the same-batch correction.
Implementer 202-/853-test summaries are reported evidence, not this Architect's
independent execution; request raw logs in the correction delivery.
