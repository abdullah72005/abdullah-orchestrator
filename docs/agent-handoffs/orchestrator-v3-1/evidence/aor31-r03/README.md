# AOR31 correction round 03 evidence

Baseline: original `b9139946db5684e3e48724b9e1060af355362e82`;
correction base `2c316d41c9fb281131a6d5196eb2adf20c2c7a2d`.
Implementation commit: `1456efa` (`fix: bind V1 account store metadata and
inspection ownership`). Evidence commit follows it and changes no code.

All tests are offline/disposable. No inference, account request, plugin
execution, install into the host, push, deploy or saved-run mutation was made.
Container preparation added `git` only inside disposable test containers
(`apk add --no-cache git`); the checkout was mounted read-only.

## Red evidence at the correction base

The corrected test tree was copied over an archive of `2c316d4` (production
code untouched there).

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts/tests python3 -m unittest test_v31_aor31_r03 -v`
  → 18 tests, **8 failures, 6 errors, 4 pass**; `red-r03.log`.
  The four passing cases (absolute path, explicit XDG root, account-row and
  active-org refusal) were already correct at the base.
- Saved `review03.py` probe at `2c316d4` → `red-review03.log`:
  relative DB hidden (`ok=true, go_subscription, account_record=null`),
  ordinary session title write invalidates the pinned route
  (`before_ok=true, after_ok=false`), post-snapshot detached child alive after
  a successful `0/[]` return.

## Green evidence at the implementation commit

| Check | Result | Log |
|---|---|---|
| Focused AOR31 + routing/integrity/stage/grant suites | 135 tests, OK, 189.7 s | `r03-final-focused.log` |
| Full offline suite, Python 3.10.12 (host) | 830 tests, OK, skipped=7, 736.1 s | `r03-final-py310.log` |
| Full offline suite, Python 3.12.16 (`orchestrator-integration-3ornvc:latest`) | 830 tests, OK, skipped=9, 833.8 s | `r03-final-py312.log` |
| Full offline suite, Python 3.13.18 (`python:3.13-alpine`) | 830 tests, OK, skipped=9, 834.0 s | `r03-final-py313.log` |
| Real V2.2.7 opt-in suite, credential-free HOME/all XDG roots | 7 tests, OK, 17.7 s | `r03-final-v2.log` |
| Saved `review03.py` probe | all three defects closed | `r03-final-review03.jsonl` |
| Supplementary production ownership probe | uncertain `active_check`, exact PID/SID/launch/token, cleanup verified | `r03-final-probe-ownership.jsonl` |

The skipped tests are the documented platform-specific skips; the opt-in real
V2 suite is skipped in the full-suite counts unless `ABDULLAH_OPENCODE_V2_BIN`
is set, and was run separately above.

Real V2 binary: `/home/abdullah/.opencode/bin/opencode`, `v2.2.7`,
`sha256 589253d36810f21217edd51545cd435b328cdc3cf4f451fbe0cce6f88afcf5e1`.

## Saved ownership probe interpretation

`review03_ownership.py` uses a sleeping config inspector with a 0.1 s
inspection timeout. Under the corrected guarded ownership the guard itself
proves containment, so the saved probe observes a proven-stopped timeout
(`status=blocked`, no live inspector) instead of losing a live owner:
`r03-final-review03-ownership.jsonl`.

The remaining live-owner branch is exercised by
`probe_r03_ownership.py`: an inspector escapes into a new session and
supervisor-side termination is denied. Observations:
`inspection_containment_unproven`, `status=uncertain`, no `active_job`,
`active_check.kind=opencode_inspection`, exact PID/SID/launch file recorded,
the escaped PID is listed, `next_action=orchestrator_reconcile`, no history,
no capture, empty grant ledger, and the diagnostic child is verifiably stopped.
The non-run Doctor observation keeps the same exact metadata without a run
state.
