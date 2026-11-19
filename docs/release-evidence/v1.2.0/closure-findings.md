# v1.2.0 closure findings and dispositions

Prepared 19 November 2026 for the local v1.2.0 release closure
(`release-closure-batch-01.md` §4.3 and §4.4). This note covers the three
independently attributable low-severity observations and the
environment-sensitive fixture assumptions. It does not replace or rewrite any
archived evidence: the logs, suites and reports already in this directory are
preserved byte-for-byte.

All three observations are **Low**. C1 and C3 were accepted with the reasons
below; C2 was fixed with a focused regression. Archived evidence is preserved
byte-for-byte. None of them carries an authority impact, and none changes what
is reported about a run.

| ID | Observation | Source landmark | Class |
|---|---|---|---|
| C1 | Runtime-only continuity can be labelled `worktree_content` | `_delta_chain_evidence()` in `scripts/orchestrator.py` | Low |
| C2 | Secondary retained-index rejection reason could be omitted | `_record_batch_delta()` near the quarantine branch | Low (fixed in closure) |
| C3 | Installed V2 hunk test verifies the filesystem endpoint, not attested publish | `test_opencode_v2_integration.py` | Low |

## C1 — runtime-only continuity labelled `worktree_content`

- **Observation.** Since r03 the attempt-chain comparison uses one shared source
  identity projection that includes discovered ignored runtime inputs. A change
  confined to such a runtime input is reported as a mismatch whose `evidence`
  field is `worktree_content`, even though no worktree byte changed.
- **Source landmark.** `_delta_chain_evidence()` in `scripts/orchestrator.py`
  (the `final_snapshot_signature` versus dispatch `source_signature` comparison,
  which appends the `{"evidence": "worktree_content", ...}` entry).
- **Test landmark.** `test_runtime_input_change_between_attempts_is_not_discarded`
  in `scripts/tests/test_v120_release_workflow.py` asserts `evidence ==
  "worktree_content"` for a runtime-input-only change.
- **Disposition.** Label imprecision only. The change is still reported, the
  limitation text still names unaccounted changes between writer windows, and
  the continuity comparison itself is unchanged. No authority, admission or
  reuse decision depends on the label. Accepted, not fixed, so that the emitted
  evidence shape does not change inside the release closure.

## C2 — secondary retained-index rejection reason can be omitted

- **Observation.** In `_record_batch_delta()`, when retained-index reuse is
  rejected and reconstruction also fails, the quarantine note records the
  rebuild failure with the retained-index reason appended where one exists, but
  the resulting writer limitation selects the primary rebuild failure first.
  The secondary retained-index rejection reason can therefore be absent from the
  limitation detail that reaches the packet.
- **Source landmark.** `_record_batch_delta()` in `scripts/orchestrator.py` near
  the quarantine branch (`_quarantine_delta_index(...)` followed by `problem =
  rebuild_problem`) and the `_record_writer_limitation(..., detail=...)` call.
- **Test landmark.** `test_tampered_retained_hunk_is_not_accepted_as_complete`
  and the r05 reconstruction tests (`test_pre_rebuild_drift_is_not_attributed_to_the_completion`,
  `test_write_during_reconstruction_is_detected_and_never_reusable`) in
  `scripts/tests/test_v120_release_workflow.py`.
- **Disposition.** Fixed in this closure (was Low). The writer limitation detail
  now appends `(retained-index: …)` when both retained reuse and reconstruction
  fail, so the review packet preserves both diagnostics. The primary failure
  reason, the counted incomplete attempt and the Reviewer limitation remain, and
  no attempt is reported complete on this path. Regression:
  `WriterLimitationDiagnosticsTests::test_dual_failure_preserves_the_secondary_retained_reason`
  in `scripts/tests/test_v120_release_closure.py`.

## C3 — installed V2 hunk test and the endpoint boundary

- **Observation.** `test_installed_binary_fs_read_returns_supervisor_generated_hunk`
  in `scripts/tests/test_opencode_v2_integration.py` builds its hunk through
  `capture_batch_boundary` → `finalize_batch_delta` with `stage` at its default
  `False`, projects it for review, and verifies that the installed V2 binary's
  filesystem endpoint returns the exact bytes. It does not exercise
  `_record_batch_delta`'s attested, crash-safe publication path.
- **Source landmark.** `finalize_batch_delta(..., stage=False)` and
  `_record_batch_delta()` / `_attest_and_publish_delta_index()` in
  `scripts/orchestrator.py`.
- **Test landmark.** `BatchCorrectionsR06Tests` in
  `scripts/tests/test_v120_release_workflow.py` (crash before post-check,
  before publish, and after publish before state commit) plus the r06 recovery
  regressions in `test_v120_release_workflow` / `test_v31_review_recovery`.
- **Disposition.** Endpoint boundary clarified: the installed test is filesystem
  read evidence for a supervisor-generated hunk, and r06 regression evidence is
  the authority for attested publication. No claim of a model-driven Read-tool
  invocation, permission enforcement or publish attestation is made from the
  installed test. Accepted, documented, not fixed.

## Environment-sensitive fixture assumptions

- Architect reran the five named tests on base `626d8c6` under WSL2 Python
  3.10.12; all five passed in 10.644 s. The run is recorded in
  `closure-baseline-environment.log` beside the closure brief:
  `test_inspector_descendant_tree_is_cleaned_up` (`test_v31_aor31_corrections`),
  `test_post_snapshot_fast_detached_child_is_contained`
  (`test_v31_aor31_r03`), `test_inspector_is_bounded_and_fully_cleaned_up`
  (`test_v31_route_sources`), and
  `test_already_started_check_is_terminated_at_clipped_deadline` /
  `test_each_child_fits_but_checks_plus_decision_do_not`
  (`test_v31_stage_deadline`).
- The independent audit's Python 3.13.5 container run was red, and its 11 skips
  are historical. Both results are preserved as recorded; neither is a
  candidate result.
- The deterministic fixture assumptions are hardened in those four test files:
  test-only synchronization of child start/completion with bounded waits, and an
  explicit pre-spawn branch where a pre-spawn timeout is the case under test.
  Where cleanup is the requirement, the child/descendant is established as
  started before the timeout or cancel is triggered.
- Verification of that hardening on code revision `b0d88f3` (unchanged in the
  final revision): the five named tests passed twice independently (21.286 s
  and 21.277 s), and the complete `test_v31_stage_deadline` module passed in
  19.767 s. The final 1017-test closure suite on `c04f640` covers the same test
  files; see `README.md` and `suite-closure.txt`.
- No live exact identity (PID/PGID/session) is accepted without cleanup proof;
  terminated/zombie and reaped states stay distinct, and PID reuse is rejected
  by comparing the recorded start time.
