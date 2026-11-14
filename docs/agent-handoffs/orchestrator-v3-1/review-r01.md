# Architect review — v3.1 correction round 1

Date: 2026-11-14.
Verdict: **CHANGES REQUIRED**. Original single-batch acceptance remains blocked by F5 and F6; no release/install/push authorization.
Reviewed correction base: bfd9a8b7a1c75329f039239b983485deadae0ada.
Reviewed HEAD: 96dd58ebe0258100c06cbe9f6b71c6564ba9d739.
Campaign baseline: 1b8e10e5c1b2c08a236b68450cb5b2a1a610416d.
Worktree/branch: /home/abdullah/.local/src/abdullah-orchestrator-v3-1, design/orchestrator-v3-1.
Commits: 740db1c, 190d7fb, 96dd58e. 18 files changed. Tracked tree clean; original five untracked handoff files preserved. This review and fix-b01-r02.md add Architect documents only. No production changes by Architect.

## Evidence checked

Inspected the full supervisor correction diff, changed installer, affected ledger/route/preflight/containment/migration/restore paths, relevant new/updated tests, documentation and saved red/green logs. Review is scoped to correction findings and affected integration edges; unchanged accepted source was not repeatedly audited for unrelated polish.

Independent final isolated command:
`python3 -m unittest discover -s scripts/tests -p 'test_v31_*.py' -v`
Result: **116 tests, OK, exit 0, 141.511 seconds**, Python 3.10.12.
Log: /tmp/ao-r01-architect-tests-isolated.log.
Independent `python3 -m compileall -q scripts`: exit 0.

Initial independent run: 116 tests with one worker error (exit -15). A simultaneous disposable containment probe reused the fixtures' test-run00 marker, making it a contaminated run; it is not cited as a product regression. No process-creating diagnostic probes ran alongside the successful isolated rerun. The older containment script also failed to produce its expected PID file during that interference, so no closure claim relies on it.

Independent separate-process nested probe after the correction: child_exit=0, used_after_nested=1, used_after_parent_completion=1. This confirms the original parent-save loss is repaired, alongside permanent ledger tests.

Inspected Implementer full-suite log /tmp/opencode/ao-v31-r01-full-suite-final2.log: 695 tests, 4 optional installed-CLI skips, OK, 354.540 seconds. This full suite was not redundantly rerun by Architect. All skipped binary tests remain unverified, not passed. Saved focused Implementer log: 116 tests, OK, 139.822 seconds. Red baseline log /tmp/opencode/ao-red-evidence/baseline-probes.log contains the original reproduced failures.

## Finding dispositions

| Finding | Scoped review disposition |
|---|---|
| F1 | PASS: source mutation no longer substitutes for containment proof; escaped valid/malformed/nonzero and failed-cleanup tests passed in isolated run. |
| F2 | PASS: Go/non-Go billing mismatch and missing non-Go billing refused; legacy Go retained; config/preflight/migration covered. |
| F3 | PASS: grant-required subscription dispatch consumes allowance; reload and failed attempt regression checks passed. |
| F4 | PASS: independently locked durable ledger survives parent saves; separate-process probe plus concurrent/idempotent permanent tests passed. |
| F5 | FAIL: fingerprint and classification still differ from actual effective child route in three concrete cases below. |
| F6 | FAIL: inspectable managed-settings.d local policy fragments still omitted. Alternate user directory/provider-host checks otherwise improved. |
| F7 | PASS: public --fallback grant selector and separate one-dispatch consent work; missing/failed/changed/exhausted alternate cases passed. |
| F8 | PASS for offline setup contract: separate settings/MCP destinations and timeout command documented/tested; authenticated UX remains pending. |
| F9 | PASS: backup validation precedes atomic restore, pre-restore audit retained; corrupt/identity/activity/write-failure regression tests passed. |

PASS applies to the named scoped correction, not overall batch/release approval. Preserve these accepted corrections and rerun affected integration tests after F5/F6 fixes.

## Remaining independent reproductions

1. Authentication environment transition: V2 provider env list stays unchanged; dummy credential becomes present. Observer auth_mode_sha256 changes but routing_fingerprint stays identical. The branch with routing_material_sha256 omits computed auth_mode_sha256.
2. Actual child configuration mismatch: authorized local provider exists only in ambient OPENCODE_CONFIG_CONTENT. Preflight sees its loopback endpoint and a full fake dispatch completes with billing=local, but the captured child configuration has no local provider. opencode_env overwrites the inline config that observation merged.
3. Go model endpoint classification: V2 selected Go model has settings.baseURL set to a custom proxy. Observer provider endpoint is absent and preflight still approves go_subscription without a new grant. Official model settings allow provider→model→variant overrides; hashing an override is not a billing attestation.
4. Claude local managed drop-in: main managed-settings.json absent; sibling managed-settings.d/10-route.json contains env.ANTHROPIC_BASE_URL. Disposable managed-path fixture returns preflight ok with no hazards; directory fragments are never enumerated.

No real provider request/charge or authenticated behavior was exercised by these probes. Scripts for the OpenCode cases: /tmp/ao-r01-routing-probes.py and /tmp/ao-r01-child-config-probe.py, copied to /tmp/ao-r01-architect-evidence/. Claude case used temporary paths and the existing replaceable managed-path tuple, no write to /etc.

Required next action: execute fix-b01-r02.md. It contains minimal corrections, exact regression/verification commands and redacted evidence requirements. The design is preserved; no new SDK/backend/service project is authorized.

## Campaign acceptance status

AOR-01/02 and AOR-04/07: scoped offline/source checks pass, maintained regression gate required.
AOR-03/06: offline registration/foreground/deadline contract reviewed; real Claude /mcp, long-stage, Esc and reconnect pending separate bounded authorization.
AOR-05: OPEN due to remaining inspectable local managed-source hazard.
Multi-provider/billing pins: OPEN due to F5 effective child-route, auth-mode and Go-exemption defects. Default/mixed/grant/fallback positive offline cases do not close the negative cases above.
Durability/report/permissions: existing tested contracts retained; no claim of OS isolation, exactly-once external side effects or hard dollar/token ceilings.
Python 3.12/3.13, optional real binary introspection, real Docker source evidence and authenticated new-provider execution remain unverified. No live installation/model use/release is approved by this review.
