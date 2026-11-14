# AOR31 — correction round 02 Implementer evidence

Base: `161683d6f51249a99e5964dee9b8c927600fb3e4`
Original base: `b9139946db5684e3e48724b9e1060af355362e82`
Branch: `design/orchestrator-v3-1`

All commands are offline and use test-owned fakes or disposable processes.
No inference, plugin execution, provider account request, install, push or
live-run mutation was performed.

## Red at correction base

The new `scripts/tests/test_v31_aor31_r02.py` was copied into a disposable
`git archive 161683d…` tree and run there:

```
git archive 161683d6f51249a99e5964dee9b8c927600fb3e4 | tar -x -C <tmp>
cp scripts/tests/test_v31_aor31_r02.py <tmp>/scripts/tests/
cd <tmp>
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts/tests \
  python3 -m unittest test_v31_aor31_r02 -v
```

Result: **22 failures/errors** covering all three findings
(`red-at-161683d.log`). Representative failures:

- pinned V1/binary V2 and pinned V2/binary V1 dispatched instead of refusing;
- V1 native `api`/`npm`/`id` remaps still qualified for Go; relative paths,
  account metadata and automatic plugins were not observed;
- a successful inspector leader left a live child; cold `--version` work
  returned a generic preflight failure instead of a deadline outcome.

## Green after correction

```
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts/tests \
  python3 -m unittest test_v31_aor31_corrections test_v31_aor31_r02 \
  test_v31_route_sources test_v31_routing_observation \
  test_v31_runtime_write_integrity test_v31_grant_contention \
  test_v31_stage_deadline -v
```

`focused.log`: 117 tests, OK, 71.735 s, Python 3.10.12.

```
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts/tests -v
```

`py310-full.log`: 812 tests, OK (7 skipped opt-in V2), 457.193 s.

```
env -i PATH=… HOME=<disposable> XDG_CONFIG_HOME=… XDG_DATA_HOME=… \
  XDG_CACHE_HOME=… XDG_STATE_HOME=… \
  PYTHONDONTWRITEBYTECODE=1 \
  ABDULLAH_OPENCODE_V2_BIN=/home/abdullah/.opencode/bin/opencode \
  PYTHONPATH=scripts/tests python3 -m unittest test_opencode_v2_integration -v
```

`v2-2.2.7-integration.log`: 7 tests, OK, 16.410 s, installed `opencode v2.2.7`.
Disposable credential-free HOME and all XDG roots; update/models fetch disabled.

## Saved Architect probes re-run against the corrected checkout

- `review02.py` → `review02.jsonl`: version-mismatch dispatch now refuses with
  zero commands; all three V1 native remap forms are `unqualified_go_route`;
  the cold version probe reports `TimeoutError` at ~0.086 s under an 0.08 s
  budget; the exited leader's child is not alive after success.
- `review02_sources.py` → `review02-sources.jsonl`: relative explicit config is
  read from the child cwd; account-store and automatic-plugin hazards are
  observed and refused.
- `review01.py` → `review01-prior.jsonl`: the five round-01 concrete cases keep
  their safe outcomes.
- `boundary_probe.py` → `boundary-probe.jsonl`: ignored planning mutation is
  refused with bytes preserved and zero completed jobs; two overlapping
  capacity-two reservations succeed and end at usage 2.

## Unexecuted

- Python 3.12 and 3.13: not installed; not installed under this authorization.
- Real V1.18.35 binary execution: unavailable; V1 checks are source-backed
  fakes/fixtures, not a compatibility claim.
- Literal independent-auditor probes: not present in this checkout.
- Authenticated providers, live account requests, plugin execution and billing
  settlement: intentionally not exercised.
