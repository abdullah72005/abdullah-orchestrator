# AOR31 — Final Architect acceptance

**Disposition: APPROVED WITH KNOWN LIMITATIONS.** Reviewed 2026-11-14.
Candidate: `0ea5381aa6e1a26e9ee0e1935c494b33800c62ae` on
`design/orchestrator-v3-1`, checkout
`/home/abdullah/.local/src/abdullah-orchestrator-v3-1`.

The four reported findings and the reproduced blockers from three Architect
correction rounds are closed within the supported, offline-verifiable boundary.
No further Implementer correction is required. This is source/test acceptance
of this exact local candidate, not installation, release, authenticated-provider
certification, or approval to dispatch a paid route. Freeze the reviewed scope;
the next step is an independent focused closure audit using the saved handoff.

## Baselines, commits and preservation

Original user-named candidate:
`828202f619209390411c9ed37da5ff2a179242a3`.
Implementation/review BASE:
`b9139946db5684e3e48724b9e1060af355362e82`.
The latter descends from the original candidate and changes documentation only;
the runtime baseline is the same. Round-03 correction BASE:
`2c316d41c9fb281131a6d5196eb2adf20c2c7a2d`.

Exact remediation commits, oldest first:

| Commit | Purpose |
|---|---|
| `7987d2672ceedad7e7785e02914f11f18502849c` | Initial routing, runtime-write, grant-contention and deadline remediation |
| `161683d6f51249a99e5964dee9b8c927600fb3e4` | Round-01 routing, prepared context, material grants, nested links and cancellation fixes |
| `2c316d41c9fb281131a6d5196eb2adf20c2c7a2d` | Actual-version validation, V1 sources and inspection lifecycle corrections |
| `1456efad4bfddabe5931c36ae4628c333ed6ef57` | Correct account-store selection/projection and guarded durable inspection ownership |
| `c315ef3b5420870d2ee55781c7fbf15839d434d6` | Round-03 verification evidence |
| `d4497203edee06e0e48cdc3d05eae4e48a35d57c` | Assert a subsequent dispatch after session writes with the original pin |
| `0ea5381aa6e1a26e9ee0e1935c494b33800c62ae` | Refresh final verification evidence |

The Implementer report omitted `c315ef3`; it is present in the actual history
and included above. Production `scripts/orchestrator.py` is byte-identical from
`1456efa` through the accepted HEAD. The later code/test difference is the final
eight-line dispatch assertion in `test_v31_aor31_r03.py`; other later changes
are evidence. The tracked worktree was clean on entry and remains clean.
Earlier Architect briefs, reviews and evidence remain untracked and unchanged;
their four JSON checksum manifests (31 entries total) were revalidated.
This Architect review adds only review/audit/evidence artifacts, uncommitted.
No production edits, push, install, release, deploy, reset, live-run changes,
manual-skill edits, or automated orchestrator self-modification were performed.

## Finding-by-finding closure matrix

| Finding | Result and invariant | Evidence |
|---|---|---|
| **AOR31-01, P1 — config precedence / billing** | **Closed for the supported boundary.** Dialect comes from the resolved executable's validated actual version. Ordered V1 source accounting and authoritative fresh V2 normalized documents cover the supported global/explicit/custom/project/inline/Linux-managed sources. Source presence, content/expansions, normalization and executable identity bind material pins and grants. Missing/stale pins, unsupported/uninspectable routing, plugin/account hazards and inspection failures refuse; generated launch bytes are immutable and re-observed before spawn. Legacy Go consent cannot authorize an endpoint override. | Fresh 135-test run; real V2 7-test run; all six saved routing reconstructions; current account and containment probes. R2/R4/R5 refuse, R1/R3/R6 retain benign Go; R2/R5 endpoint edits change pins. |
| **AOR31-02, P2 — ignored runtime writes** | **Closed at observed boundaries.** Relevant ignored executable/config inputs and nested symlink target content enter the write projection; incomplete/unprovable manifests block. Planning/review/acceptance/failure/recovery checks preserve changed bytes and block unauthorized writes without rollback. Content, rather than volatile environment observations, determines the mutation check. | Fresh runtime-integrity/correction suites; original saved boundary reconstruction rejects ignored `.py` mutation, records zero completed jobs and preserves the changed file; acceptance/provenance reruns. |
| **AOR31-03, P2 — ledger contention** | **Closed.** Independent ledger operations wait within configured/cancel/deadline bounds while atomic accounting and reservation replay remain intact. Lock timeout differs from exhausted grant capacity; the supervisor ownership lock remains nonblocking. | Fresh separate-process grant-contention suite, including cancellation/deadline/crash/replay/capacity; saved two-process capacity-2 reconstruction: both succeed, final consumption exactly 2. |
| **AOR31-04, P3 — deadline assertion** | **Closed.** Tests assert failed verification, unchanged phase, no acceptance and no later Reviewer/worker, without requiring incidental timeout wording. Correct production wording was retained. | Fresh five-test deadline module in the focused run; saved expired-budget scenario returns blocked/verify, null verification, zero completed jobs and no active job; complete Python 3.13 evidence inspected. |

## Correction-round disposition

All blockers in [round 01](aor31-review-r01.md),
[round 02](aor31-review-r02.md) and [round 03](aor31-review-r03.md)
are closed by the reviewed cumulative changes and retained regressions:

| Prior blockers | Final assessment |
|---|---|
| R01-F1/F2 source order, normalization fallback, cache/parent coverage | Correct dialect-specific ordering; no V2 adapter authorization on inspector failure; every normalization is fresh; parent-above-Git-root and disjoint legacy/native parity pass real V2 tests. |
| R01-F3/F4 approved-versus-launched context, unpinned public grants | Full prepared inline bytes and resolved identity reach launch; last-boundary drift blocks. New OpenCode grants require a current material pin; no automatic re-pin or label-only consent. |
| R01-F5/F6 nested linked runtime content, inspector cancellation | Nested target edits/cycles/outside/unprovable traversal are covered; cold version and config inspection obey cancellation/deadline admission and owned cleanup. |
| R02-F1/F2 actual dialect and omitted V1 native/config/account/plugin inputs | Actual-version mismatch/failure refuses; matching controls dispatch with the corresponding permission dialect. Native `api`/SDK/model remaps, child-cwd config paths and automatic plugins are accounted for/refused as appropriate. |
| R02-F3 / R03-F3 descendant ownership | Existing guarded execution, inherited markers, durable launch records and `inspect_execution` replace sampled ancestry as the stopping proof. A fast detached child is killed. Denied cleanup retains exact `uncertain active_check`, blocks dispatch/stage/resume, and reconciles only after stopped proof. No phantom inference job/grant use. Non-run observations retain exact ownership metadata. |
| R03-F1 selected account store | Relative `OPENCODE_DB` resolves beneath actual V1 data root; absolute/default/channel/`:memory:` cases are covered. Unhonored `OPENCODE_DATA_DIR` cannot divert inspection. Unknown/malformed/unreadable routing refuses. |
| R03-F2 session churn versus account material | Only canonical account-routing metadata affects the route pin. Missing-to-empty initialization and session/history changes retain the same pin and allow a subsequent fake dispatch; account/active-org changes refuse. Whole-file DB digest is physical audit evidence only, excluded from pins. Token columns are not selected/decoded. |

The round-03 approach follows the approved reassessment: use the upstream
storage contract and the existing guarded ownership/reconciliation machinery,
not another independent normalizer or polling-only executor.

## Independently executed verification at accepted HEAD

Durable outputs: [final Architect evidence](evidence/aor31-final-architect/README.md),
with `SHA256SUMS.json`. All commands exited 0. Diagnostic script exits alone are
not safety assertions; their JSON outcomes were inspected as described below.

| Execution | Result |
|---|---|
| Eight focused modules: round-01/02/03 corrections, route sources/observation, runtime integrity, grant contention, deadline | **135 tests, OK, 0 skips, 194.271 s**, host Python 3.10.12 |
| Campaign integration, acceptance integrity, checkpoint-B provenance, route migration, structured schemas, decision contracts | **89 tests, OK, 0 skips, 128.150 s**, host Python 3.10.12; includes fake Claude/Codex, mixed providers and real authorization helpers |
| Real OpenCode V2 integration in disposable credential-free HOME and all four XDG roots | **7 tests, OK, 0 skips, 18.502 s**; no inference or plugins |
| Saved `route_probe.py` against installed binary | Six normalizer commands exit 0. R2/R4/R5: `unqualified_go_route`, endpoint observed; R2/R5 edited endpoint changes pin. R1/R3/R6: `go_subscription`. |
| Saved `boundary_probe.py` | Ignored planning mutation raises `SourceMutationError`, zero completed jobs, edit preserved. Two overlapping eligible reservations succeed, final usage 2. |
| Saved `review03.py` | Correct relative DB observed and refused; ordinary session edit keeps before/after preflight valid; fast post-snapshot detached child dead after successful `0/[]` inspection result. |
| Supplied `probe_r03_ownership.py` independently rerun | Denied escaped-child cleanup retains uncertain active check, exact identity/launch/token and reconciliation action; no model history/capture/job or grant; diagnostic cleanup verified. Non-run observation retains metadata. |
| Saved deadline scenario | Blocked at verify; wording `Whole-stage deadline exceeded before the next child`; verification null, no completed jobs or active job. Only obsolete unittest fixture method name is adapted by a saved wrapper; original script unchanged. |
| Static/repository checks | Python source compiles in memory; `git diff --check` passes; tracked worktree clean; binary identity and all supplied round-03 evidence checksums match. |

Installed binary: `/home/abdullah/.opencode/bin/opencode`, tested **V2.2.7**,
SHA256 `589253d36810f21217edd51545cd435b328cdc3cf4f451fbe0cce6f88afcf5e1`.
The real-binary suite checks actual normalization, parent-source freshness,
legacy/native providers, generated permission profiles and supported CLI flags;
it does not dispatch provider inference.

## Complete-suite evidence inspected, not re-executed by this Architect

All 18 entries in the Implementer's final round-03 checksum manifest match.
Actual logs in [round-03 evidence](evidence/aor31-r03/README.md) record:

| Interpreter/environment | Complete offline suite | Skips |
|---|---|---|
| Python 3.10.12, host, final test tree | **830 tests, OK, 731.032 s** | 7 opt-in real-V2 tests |
| Python 3.12.16, disposable existing container | **830 tests, OK, 833.763 s** | 7 opt-in V2; LeanCTX unavailable; root ignores file permissions |
| Python 3.13.18, disposable existing container | **830 tests, OK, 834.021 s** | Same 9 skips as 3.12 |

The full 3.12/3.13 matrices ran before the last eight-line dispatch assertion;
production is identical to HEAD. That changed test was then rerun on each
interpreter (one test, OK on both). Full 3.10 was rerun on the final test tree.
This precise evidence coverage is accepted rather than represented as a fresh
Architect full-matrix execution. The evidence README's 736.1-second host summary
is stale; the actual final host log above records 731.032 seconds.
Containers installed git only inside disposable containers, with the checkout
read-only; no host interpreter or installed version was changed.

Red evidence inspected at correction BASE `2c316d4`: 18 tests, 8 failures,
6 errors, 4 passes, plus saved diagnostic observations of all three original
round-03 defects. Errors caused by newly introduced helper interfaces are not
misrepresented as fourteen independent behavioral reproductions. Prior red
records and original diagnostic baselines remain preserved in historical evidence.

## Contract and boundary checks

- State/config schema remain **3**. Existing migration tests preserve historical
  readability, invalidate stale bindings and require explicit migration/new
  authorization; old approvals are not silently recertified.
- Model **report contract v2** and structured-output schemas are unchanged.
  Ownership and source bindings are internal job/state metadata. Fresh schema,
  decision-contract, provenance and acceptance tests pass.
- Clean legacy Go, multi-provider/explicit authorization, and fake Claude/Codex
  campaign paths pass. Unqualified overrides, unknown normalization and unresolved
  account/plugin routing cannot inherit legacy Go authorization.
- Ledger ownership and inspection ownership remain separate from model usage:
  rejected/unlaunched inference does not create a model completion or silently
  consume a new grant. Unprovable cleanup keeps the execution owner, rather than
  treating a successful leader exit as stopped proof.
- Maintained docs/config were updated for source boundaries, material grants,
  ledger waiting, runtime manifests, database routing projection and inspection
  recovery (`docs/configuration.md`, `docs/security-model.md`, `docs/validation.md`,
  `references/contracts.md`, `references/operation.md`, example config).

## Known limitations and ownership

1. **Literal independent-auditor scripts were never supplied.** Saved Architect
   reconstructions and regression equivalents were rerun; no claim is made that
   the unavailable exact scripts ran. Closure auditor/user owns supplying and
   repeating those scripts if available.
2. **Real V1.18.35 binary unavailable.** V1 behavior is source-backed and tested
   with fixtures/fakes, including the pinned upstream configuration/database
   contracts. No actual V1 runtime compatibility claim. A future V1 binary audit
   belongs to the closure auditor/maintainer; do not infer it from V2 results.
3. Unsupported/uninspectable routing fails closed: V2 requires successful
   supported-binary normalization; plugin/account/remote hazards are refused.
   Linux managed files are covered; macOS/Windows managed delivery is not
   certified. Extending that boundary requires a separate approved change.
4. Pins bind absolute source/executable identities. Moves, binary upgrades or
   route changes require explicit migration/re-authorization, not automatic pins.
   A refund that cannot finish within the remaining deadline may conservatively
   retain consumption, as documented; no allowance expansion is permitted.
5. Boundary snapshots do not detect transient write-and-restore activity.
   Guards/markers are not OS isolation or resistance to same-user identity/
   environment tampering. No authenticated provider, actual billing outcome,
   plugin execution, account refresh or long unattended stability was tested.

These limits bound the acceptance claim; they do not waive the reproduced
authorization, mutation, contention or ownership invariants. No scoped blocking
finding remains. Independent closure audit is the next review gate; deployment
and installation remain unauthorized.
