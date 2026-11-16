# E2E review recovery — same-batch correction r01 evidence

Correction brief: `docs/agent-handoffs/orchestrator-v3-1/e2e-review-recovery-fix-b01-r01.md`
Architect review: `docs/agent-handoffs/orchestrator-v3-1/e2e-review-recovery-review-r01.md`

Code/test revision for all logs: commit
`66033a82ce75e08242988b01254c2621e4cb28f4`
(branch `design/orchestrator-v3-1`; parent/red BASE
`2ab20309ef4acf039b9e0ccb8806149c18788989`). Interpreter: **Python 3.10.12**.
This evidence-only commit does not change production or test code.

| Artifact | SHA-256 |
|---|---|
| `scripts/orchestrator.py` | `79746cc2cad454cd1ab7c4b32f4753574269ad46755903694bc70f42558708de` |
| `scripts/tests/test_v31_review_recovery.py` | `68052ca746c72defd9ebb4a3a78e91d93a857afc080eb85bc5bcea383bde4d20` |

## Red at BASE (2ab2030)

The final correction test module was copied into a disposable `git archive` of
BASE. Existing controls remained green; the new F1/F2 cases failed:

```bash
cd /tmp/opencode-verify/base-r01   # git archive 2ab20309...
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts/tests \
  python3 -m unittest test_v31_review_recovery -v
```

- `review-recovery-red-base-r01.log` — 36 tests, 10 failures, 1 error, 74.6 s.
- `review-probes-at-base-r01.jsonl` — saved Architect probe output at BASE:
  - `missing-log-and-path-drift`: phase `verify`, status `running`, recovery true,
    rejection null (defect F2).
  - `recover-old-review-after-invalidation`: applied true, original job epoch 0,
    run epoch 1, recovered epoch 1, cache eligible true, phase after review
    `accept`, zero new Reviewer calls (defect F1).
- `review-probes-at-base-r01.err` — empty.

## Green after correction (66033a8)

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts/tests \
  python3 -m unittest test_v31_review_recovery -v
```

- `review-recovery-green-b01-r01.log` — **36 tests, OK, 0 skips, 84.2 s**.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts/tests \
  python3 -m unittest test_v31_review_recovery test_report_ingestion \
  test_checkpoint_b_provenance test_v31_acceptance_integrity \
  test_interactive_recovery test_quota_changes test_v31_stage_invariants -v
```

- `requested-regressions-b01-r01.log` — **203 tests, OK, 0 skips, 269.7 s**.

```bash
PYTHONDONTWRITEBYTECODE=1 \
  python3 -m unittest discover -s scripts/tests -t scripts/tests -v
```

- `full-suite-b01-r01.log` — **866 tests, OK, 7 opt-in skips, 819.8 s**.
  The seven skips are the real-OpenCode introspection module, which requires
  `ABDULLAH_OPENCODE_V2_BIN`.

## What the new cases establish

F1: public `recover_report` bound to original job/dispatch epoch; dry-run remains
inspectable with `authority_eligible: false`; apply refuses late explicit-epoch
and legacy-missing-epoch Reviewer recovery after invalidation; re-application is
refused; an epoch race inside the commit lock is refused; a current-epoch
recovery still consumes without a model; a maliciously re-stamped old record is
not consumed and fresh independent review is dispatched.

F2: missing logs combined with PATH, environment, toolchain or check-executable
drift remain blocked/review with the missing-log classification; missing log
references and unreadable logs behave the same; authority epoch, model calls and
check execution are unchanged and remaining evidence artifacts are preserved.
Clean drift still rewinds, and clean evidence still reaches review.
