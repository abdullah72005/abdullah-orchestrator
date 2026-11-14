# AOR31 remediation packet — auditor entrypoint

This directory holds the review trail for the v3.1 remediation described in
[`../CHANGELOG.md`](../../../CHANGELOG.md). It is published so an independent
auditor can inspect the corrected source, understand the four original defects,
rerun the regressions, and judge what is still unproven.

**Status of the candidate:** Architect-approved with known limitations at
`0ea5381aa6e1a26e9ee0e1935c494b33800c62ae`. An independent remediation-closure
audit and real end-to-end testing are **pending**. Nothing here certifies
production readiness, authenticated provider compatibility, or a stable release.

## Source identity

| Ref | SHA |
|---|---|
| Accepted candidate (production identical since `1456efa`) | `0ea5381aa6e1a26e9ee0e1935c494b33800c62ae` |
| Earlier audited candidate named by the user | `828202f619209390411c9ed37da5ff2a179242a3` |
| Implementation / review base | `b9139946db5684e3e48724b9e1060af355362e82` |
| Round-03 correction base | `2c316d41c9fb281131a6d5196eb2adf20c2c7a2d` |

`b913994` descends from `828202f` and changes documentation only. From
`1456efa` to the accepted HEAD, `scripts/orchestrator.py` is byte-identical; the
only later code change is a test assertion.

## Read in this order

| # | Document | What it establishes |
|---|---|---|
| 1 | [`aor31-final-architect-review.md`](aor31-final-architect-review.md) | Final verdict, exact commits, finding-by-finding closure matrix, executed verification, limitations |
| 2 | [`aor31-closure-auditor-handoff.md`](aor31-closure-auditor-handoff.md) | The auditor's brief: focus areas, reproduction commands, expected evidence |
| 3 | [`aor31-investigation.md`](aor31-investigation.md) | How the four defects were reproduced and the design decision taken |
| 4 | [`aor31-remediation-batch-01.md`](aor31-remediation-batch-01.md) | Approved implementation brief and invariants |
| 5 | [`aor31-review-r01.md`](aor31-review-r01.md), [`aor31-review-r02.md`](aor31-review-r02.md), [`aor31-review-r03.md`](aor31-review-r03.md) | Three correction rounds; each is `CHANGES REQUIRED` at its own commit, not a final verdict |
| 6 | [`aor31-fix-b01-r01.md`](aor31-fix-b01-r01.md), [`aor31-fix-b01-r02.md`](aor31-fix-b01-r02.md), [`aor31-fix-b01-r03.md`](aor31-fix-b01-r03.md) | Scoped correction handoffs issued to the Implementer |

Historical, superseded documents from the earlier v3.1 build campaign are kept
alongside this packet (`final-architect-review.md`, `independent-auditor-handoff.md`,
`review-r01.md`, `review-r02.md`, `fix-b01-r01.md`…`fix-b01-r03.md`,
`investigation-evidence.md`, `batch-01.md`). They describe the pre-remediation
candidate and are preserved as history, not as the current verdict.

## The four defects

| ID | Original defect | Where the fix lives |
|---|---|---|
| **AOR31-01** | OpenCode configuration precedence could approve or launch a route different from the one actually resolved, and legacy Go consent could survive an endpoint override | Route/source resolution, material pins, launch-byte re-observation in `scripts/orchestrator.py`; tests `test_v31_route_sources.py`, `test_v31_routing_observation.py`, `test_v31_aor31_corrections.py`, `test_v31_aor31_r02.py`, `test_v31_aor31_r03.py` |
| **AOR31-02** | Ignored runtime inputs (executable/config files, nested symlink targets) were outside the write projection, so read-only stages could mutate them undetected | Runtime-input manifest and mutation gates; `test_v31_runtime_write_integrity.py` |
| **AOR31-03** | Concurrent grant-ledger operations could race, letting dispatch capacity be exceeded | Bounded lock wait, reservation replay, separate ledger lock; `test_v31_grant_contention.py`, `test_v31_grant_ledger.py` |
| **AOR31-04** | The deadline regression asserted incidental timeout wording rather than safety behavior | Assertions rewritten to failed verification, unchanged phase, no acceptance, no later worker; `test_v31_stage_deadline.py` |

## Reproduction

Run from the repository root. Use `PYTHONDONTWRITEBYTECODE=1` and execute groups
sequentially: the containment fixtures create disposable process trees.

```bash
python3 -m compileall -q scripts

# focused remediation regressions (135 tests)
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts/tests python3 -m unittest \
  test_v31_aor31_r03 test_v31_aor31_corrections test_v31_aor31_r02 \
  test_v31_route_sources test_v31_routing_observation \
  test_v31_runtime_write_integrity test_v31_grant_contention \
  test_v31_stage_deadline -v

# integration / provenance / migration (89 tests)
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts/tests python3 -m unittest \
  test_v31_campaign_integration test_v31_acceptance_integrity \
  test_checkpoint_b_provenance test_v31_route_migration \
  test_structured_output_schemas test_decision_contract_regressions -v

# full offline suite (830 tests; 7 opt-in skips)
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts/tests -v
```

Optional real-binary introspection (no provider inference, no credentials):

```bash
ABDULLAH_OPENCODE_V2_BIN=/path/to/opencode-2.2.7 \
  python3 -m unittest discover -s scripts/tests -p "test_opencode_v2_integration.py"
```

The tested binary was OpenCode V2.2.7, SHA256
`589253d36810f21217edd51545cd435b328cdc3cf4f451fbe0cce6f88afcf5e1`. V2.2.7 is
not required to reproduce the offline suite.

Saved diagnostic scripts accept the checkout as their first argument:

| Script | Purpose |
|---|---|
| [`evidence/aor31/route_probe.py`](evidence/aor31/route_probe.py) | Six normalization cases against a real binary; second argument is the binary path |
| [`evidence/aor31/boundary_probe.py`](evidence/aor31/boundary_probe.py) | Ignored-file mutation and overlapping capacity-2 reservations |
| [`evidence/aor31-review-r03/review03.py`](evidence/aor31-review-r03/review03.py) | Account-store selection, session churn, fast detached child |
| [`evidence/aor31-r03/probe_r03_ownership.py`](evidence/aor31-r03/probe_r03_ownership.py) | Denied cleanup ownership retention |
| [`evidence/aor31-final-architect/review04-deadline-adapter.py`](evidence/aor31-final-architect/review04-deadline-adapter.py) | Expired-budget deadline scenario |

These are **reconstructions**. The literal independent-auditor scripts were
never supplied, so no claim is made that they ran.

## Evidence inventory

| Directory | Contents |
|---|---|
| [`evidence/aor31/`](evidence/aor31/) | Original Architect probes and saved outputs, `SHA256SUMS.json` |
| [`evidence/aor31-review-r01/`](evidence/aor31-review-r01/) | Round-01 probes, focused log, checksums |
| [`evidence/aor31-review-r02/`](evidence/aor31-review-r02/) | Round-02 probes, focused and real-V2 logs, checksums |
| [`evidence/aor31-review-r03/`](evidence/aor31-review-r03/) | Round-03 probes, verification record, checksums |
| [`evidence/aor31-final-architect/`](evidence/aor31-final-architect/) | Independent Architect run at the accepted HEAD: focused/contracts/V2 logs, route, boundary, ownership and deadline JSONL, metadata, checksums |
| [`evidence/aor31-r02/`](evidence/aor31-r02/) | Implementer round-02 full-suite and red logs |
| [`evidence/aor31-r03/`](evidence/aor31-r03/) | Implementer round-03 full-suite logs for Python 3.10/3.12/3.13, red logs, ownership probe |

Integrity: each `SHA256SUMS.json` / `SHA256SUMS.txt` covers the files beside it.
Verify one directory with:

```bash
cd docs/agent-handoffs/orchestrator-v3-1/evidence/aor31-final-architect
python3 - <<'PY'
import hashlib, json, pathlib
sums = json.load(open("SHA256SUMS.json"))
bad = [name for name, digest in sums.items()
       if hashlib.sha256(pathlib.Path(name).read_bytes()).hexdigest() != digest]
print("OK" if not bad else f"FAILED: {bad}")
PY
```

## Known limitations carried forward

1. No real OpenCode V1.18.x binary was available; V1 is source- and
   fixture-verified only.
2. macOS/Windows managed configuration delivery is not certified.
3. Pins bind absolute source and executable identities: moving the checkout,
   upgrading the binary, or changing a route requires explicit migration or
   re-authorization rather than automatic re-pinning.
4. Boundary snapshots cannot detect transient write-and-restore activity, and
   application-level guards are not OS isolation.
5. No authenticated provider, billing outcome, plugin execution, account
   refresh, or long unattended stability was tested.

## What is deliberately not published

This packet contains review documents, saved probe scripts, JSONL/JSON outputs,
test logs and checksums only. It excludes private session transcripts, operator
credentials, OpenCode/Codex/Claude auth stores, `.env` files, local run state,
customer data, and provider account metadata. Logs are the bounded outputs of
`unittest` and the saved probes; no prompt/response transcript is included.
