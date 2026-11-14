# AOR31 — Architect review round 02

**Disposition: CHANGES REQUIRED** at
`161683d6f51249a99e5964dee9b8c927600fb3e4`.
Incremental BASE: `7987d2672ceedad7e7785e02914f11f18502849c`.
Original BASE: `b9139946db5684e3e48724b9e1060af355362e82`.
Checkout/branch: `/home/abdullah/.local/src/abdullah-orchestrator-v3-1`,
`design/orchestrator-v3-1`. HEAD and tracked diff match the delivery report.

The first correction addresses the six recorded concrete cases and adds useful
coverage. Three boundaries still violate the approved contract. They are
reproducible, not hypothetical requests for extra hardening. Continue through
the focused [round 02 correction brief](aor31-fix-b01-r02.md).

## Actual changes reviewed

- New commit `161683d fix: close AOR31 review round 01 routing and integrity gaps`;
  16 tracked files, +1,551/-373 lines from correction BASE. Inspected the complete
  production diff, all added/changed tests/fixtures and maintained docs, in the
  context of the already reviewed first implementation commit `7987d26`.
- Before this review, only prior Architect handoffs/reviews/evidence were
  untracked; tracked worktree clean. This review changes no production code and
  adds only Architect correction/review/evidence files. No commit, push, install,
  provider inference, live saved-run mutation or manual-skill edit.
- Maintained configuration, security and validation docs now describe the new
  behavior. `references/contracts.md` was listed as updated in the chat report
  but is not changed by this commit; that reporting discrepancy is not an
  additional code blocker.

## Prior correction matrix

| Prior item | Independent result at HEAD | Remaining gate |
|---|---|---|
| R01-F1 source fallback | Home directory and global legacy ordering cases now reject Go overrides; V2 failed inspection refuses rather than authorizing; disjoint-provider parity passes real V2. | V1 completeness/native-route issues remain as R02-F2. |
| R01-F2 freshness | Cache reuse removed; filesystem-root V2 source discovery and parent-above-Git freshness pass; material identity present without a selected provider. | Concrete finding corrected. |
| R01-F3 launched inline | Saved ambient mutation now blocks before child/history; immutable prepared inline test passes. | Prepared dialect introduces version-validation bypass, R02-F1. |
| R01-F4 unpinned grants | Public unpinned grant and grant-required dispatch tests refuse; existing pin drift tests pass. | Concrete missing-pin finding corrected; retain unchanged. |
| R01-F5 nested links | Saved exact nested target mutation raises SourceMutationError, preserves bytes, completes zero jobs. Nested traversal/cycle/budget tests pass. | Concrete finding corrected; retain unchanged. |
| R01-F6 cancellation | Config-inspection cancellation/deadline and running-parent descendant tests pass. | Exited-leader containment and cold version work still fail, R02-F3. |

Original AOR31-01 remains open (R02-F1/F2 and inspector lifecycle). AOR31-02's
reviewed content-mutation gaps now pass focused checks. AOR31-03's separate
ledger contention/capacity/crash tests pass. AOR31-04's five safety-invariant
tests pass. None of these component results constitutes final batch acceptance.

## Blocking findings

### R02-F1 — P1: prepared launch bypasses actual version policy

`_opencode_dialect_for_observation:1516` returns the configured pin's major
without validating the actual version. `cli_command:6268` now trusts that
prepared dialect and bypasses its earlier `opencode_dialect()` call.

Diagnostic: pin V1.18.35, fake binary reports V2.2.7, native V2 custom Go endpoint,
empty variant. Normal version policy refuses the mismatch. `call_model` instead
successfully dispatches the fake child with V1 controls and no `--standalone`;
the native V2 endpoint is missed by V1 observation. History records `run`.
This breaks both billing/permission parity and V2 private-server ownership.
It is an introduced integration regression, not a request to expand support.

### R02-F2 — P1: V1 source boundary still certifies unknown routing

`_opencode_effective_endpoint:2478` observes only `options` endpoints in V1;
Go qualification at 2487 ignores native `api`/`npm`/model-provider remaps.
All three supervisor tests approve Go, report no endpoint and qualified=true:
provider `api`, selected model `provider.api`, and provider `npm` remap.
The supported [V1 provider implementation](https://github.com/anomalyco/opencode/blob/v1.18.35/packages/opencode/src/provider/provider.ts)
uses those URL/package values for the selected model.

Additional source-boundary reproductions:

- Relative `OPENCODE_CONFIG` reads a benign file in the supervisor cwd while
  the child cwd contains a custom-endpoint file at that same relative path;
  preflight approves Go. Relative path resolution was explicitly required in
  the first correction brief and is still missing.
- A synthetic account DB selected with `OPENCODE_DB` contains active account
  and organization metadata. Preflight reports adapter_complete=true, no hazards
  and Go approval; the DB is not inspected. The supported
  [database path selection](https://github.com/anomalyco/opencode/blob/v1.18.35/packages/core/src/database/database.ts),
  [account tables](https://github.com/anomalyco/opencode/blob/v1.18.35/packages/core/src/account/sql.ts)
  and [account repository](https://github.com/anomalyco/opencode/blob/v1.18.35/packages/opencode/src/account/repo.ts)
  show that account state is not limited to `auth.json`.
- `.opencode/plugins/local.ts` is present, with no declared plugin list.
  Preflight reports plugin_config_present=false and adapter_complete=true, and
  approves Go. The supported
  [plugin discovery](https://github.com/anomalyco/opencode/blob/v1.18.35/packages/opencode/src/config/plugin.ts)
  loads automatic plugin files too. The diagnostic does not execute that file.

The latter cases demonstrate unobserved influential sources, not a claim to have
contacted an account endpoint or tested authenticated V1. A clean auth.json and
absence of declared plugins do not establish a complete source boundary.

### R02-F3 — P2: leader exit and version work escape lifecycle checks

`_opencode_run_bounded:2014` only attempts cleanup when the leader is still
running. A disposable parent starts a child with closed stdio, prints valid
JSON and exits 0. The helper returns success while the child remains alive in
its original group. The diagnostic explicitly kills and verifies termination
of its own child afterward. No escaped-session trick is needed.

`_opencode_binary_version_cached:1968` still uses an independent 10-second
`subprocess.run`, and auto-dialect selection has another such path. With a fake
0.6-second version query and an 0.08-second whole-stage budget, `call_model`
takes roughly 0.68 seconds and returns generic preflight failure. Cold version
work does not receive the stage deadline/cancellation context. The previous fix
brief expressly included version work in this boundary.

## Independently executed evidence

All durable scripts/logs/results: `evidence/aor31-review-r02/`, with checksums.

| Check | Actual result |
|---|---|
| `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts/tests python3 -m unittest test_v31_aor31_corrections test_v31_route_sources test_v31_runtime_write_integrity test_v31_grant_contention test_v31_stage_deadline -v` | **72 tests, 0 skips, OK, exit 0, 41.188 s**, Python 3.10.12; `review02-focused.log`. |
| Real opt-in `test_opencode_v2_integration.py`, installed V2.2.7 | **7 tests, 0 skips, OK, exit 0, 15.150 s**; `review02-v2.log`. Disposable HOME and all CONFIG/DATA/CACHE/STATE XDG roots, minimal env, update/models fetch disabled; no inference/plugins. |
| Saved round-01 `review01.py <checkout>` | All five previously failing concrete cases now produce safe outcomes; `review02-prior-cases.jsonl`. |
| Saved original `boundary_probe.py <checkout>` | Ignored planning mutation refused, zero completed jobs, bytes preserved; two overlapping capacity-two reservations succeed, final usage 2; `review02-saved-boundary.jsonl`. |
| New `review02.py <checkout>` | Actual-version mismatch still dispatches; three native V1 routing overrides still qualify for Go; cold version exceeds budget; helper returns success with live child. `review02.jsonl`. |
| New `review02_sources.py <checkout>` | Relative config, active account DB, automatic plugin cases still approve Go; `review02-sources.jsonl`. |
| `git diff --check`, tracked worktree check | Pass; production worktree unchanged by Architect. |

The new diagnostic scripts report observations and may exit 0 while exposing
unsafe behavior. Their zero exit is not a passing safety assertion. The V1
cases are supervisor/fake/source-backed reproductions; no real supported V1
binary, plugin execution, live account request or inference was used.

The Implementer reports full 786-test runs on Python 3.10/3.12/3.13 and seven V2
tests. This review independently executed the focused and real-binary checks
above; it did not duplicate complete suites while blockers remain. Full
multi-interpreter evidence, the absent literal auditor scripts, authenticated
providers and long unattended operation must not be inferred from these checks.

## Next step and scope freeze

The saved correction brief reassesses the repeated weak boundaries: restrict
fallback eligibility to proven forms, validate actual versions with the existing
policy, and use whole-execution ownership rather than adding another partial
wrapper. No unrelated refactor or universal config reimplementation is approved.
Keep the corrected cache/grant/symlink paths frozen except necessary integration.

**Final Architect acceptance is withheld.** A focused closure auditor should
start with R02-F1/F2/F3 and these scripts, then verify preservation of the now-safe
round-01 cases and the original final verification matrix after correction.
