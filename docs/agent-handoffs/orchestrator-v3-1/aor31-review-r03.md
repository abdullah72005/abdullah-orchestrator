# AOR31 — Architect review round 03

**Disposition: CHANGES REQUIRED** at
`2c316d41c9fb281131a6d5196eb2adf20c2c7a2d`.
Correction BASE: `161683d6f51249a99e5964dee9b8c927600fb3e4`.
Original BASE: `b9139946db5684e3e48724b9e1060af355362e82`.
Checkout/branch: `/home/abdullah/.local/src/abdullah-orchestrator-v3-1`,
`design/orchestrator-v3-1`.

Actual-version validation, the previously reproduced native V1 remaps, relative
config paths, active absolute account DB and plugin cases now pass their focused
regressions. Cold version deadline/cancellation handling is corrected. Three
account-storage/ownership defects remain; final acceptance is withheld.
Use the [focused correction brief](aor31-fix-b01-r03.md), which explicitly revises
the implementation approach rather than adding another sampling-only wrapper.

## Repository, scope and evidence inspected

- HEAD matches the Implementer report. Latest local commit:
  `2c316d4 fix: close AOR31 review round 02 version, V1 source and lifecycle gaps`.
  Earlier remediation commits: `7987d2672ceedad7e7785e02914f11f18502849c` and
  `161683d6f51249a99e5964dee9b8c927600fb3e4`.
- Incremental change: 17 tracked files, +2,432/-104 lines, including committed
  evidence; production module diff is 625 changed lines. Inspected the entire
  incremental production/test/doc diff, new 541-line regression module and the
  supplied evidence index/checksums/results. Earlier cumulative changes were
  reviewed in rounds 01/02; unrelated accepted scope was not reopened.
- Tracked worktree clean. Prior Architect inputs/reviews/evidence remain
  untracked and unmodified. This review adds only its review/fix/evidence files;
  no production code changes or commits.
- All 10 supplied `evidence/aor31-r02/SHA256SUMS.txt` entries match. The full
  Python-3.10 log actually records **812 tests, OK, skipped=7, 457.193 s**.
  Red evidence records **26 tests, failures=19, errors=3** at `161683d`.
  These are inspected Implementer logs, distinguished from reruns below.

## Finding-by-finding assessment

| Original requirement / prior correction | Current independent assessment |
|---|---|
| AOR31-01 config/billing; R02-F1 version policy | Actual-version mismatch, unsupported and failed version cases refuse; matching V1/V2 controls pass. **Account store selection still permits unobserved routing: R03-F1.** |
| R02-F2 V1 native sources | The six earlier concrete cases now pass their tests. The newly added store uses wrong relative-path semantics and whole-DB identity; **R03-F1/F2 remain blocking**. |
| R02-F3 inspector ownership/budget | Cold version cancellation/deadline and sampled descendant cases pass. **Fast detached child and durable failed-cleanup ownership fail: R03-F3.** |
| AOR31-02 ignored source writes | Existing ignored/nested/symlink integrity cases pass focused coverage; no new source-write defect identified. Preserve corrected projection. |
| AOR31-03 grant contention | Separate-process contention, capacity, cancellation, crash/replay and nonblocking supervisor coverage pass. Preserve ledger behavior. |
| AOR31-04 deadline assertion | Five invariant tests pass on Python 3.10.12. Full Python 3.12/3.13 runs at this HEAD remain pending; available Docker images were found. |

## Blocking findings

### R03-F1 — P1: selected account DB can be omitted through a relative name

`_opencode_account_store:2437` resolves a relative `OPENCODE_DB` against project
cwd. The supported
[V1 database path function](https://github.com/anomalyco/opencode/blob/v1.18.35/packages/core/src/database/database.ts)
resolves it under `Global.Path.data`. The
[V1 global-path implementation](https://github.com/anomalyco/opencode/blob/v1.18.35/packages/core/src/global.ts)
defines that data root from XDG data location.

Disposable reproduction: put active account/org metadata at
`$HOME/.local/share/opencode/selected.db`, export `OPENCODE_DB=selected.db`,
leave project/selected.db absent. Preflight returns **ok=true, go_subscription,
account_store=null, hazards=[]**. The safety scan inspected the wrong location;
it cannot certify no influential account routing. No account request or actual
provider inference was performed. This is a remaining source-resolution defect,
not a request to expand provider support.

### R03-F2 — P2: session history is incorrectly treated as route material

`_opencode_account_store` hashes the entire DB at `_sha256_file(path)` and places
that digest in the source identity used by route pins. A private DB with empty
account metadata and an unrelated `session` row qualifies for Go. Update only
the session title, keeping account count 0, inactive selection and table set
identical: the next preflight rejects the unchanged pinned route because its
material changed.

The supported [session schema](https://github.com/anomalyco/opencode/blob/v1.18.35/packages/core/src/session/sql.ts)
is stored through the same database service. This is an ordinary CLI state
change that fake worker scripts do not naturally simulate. The resulting pin
invalidations break valid legacy Go continuation. Account-routing metadata must
remain bound without treating all history/SQLite-layout bytes as billing config.
Do not solve it by auto-repinning or dropping real account/route drift checks.

### R03-F3 — P1: sampling misses detached execution; uncertainty is not durable

`_opencode_run_bounded:2175` and tracking/containment at 2109–2172 still depend on
sampling descendants while their parent relation exists. A coordinated fixture
holds the parent until **after a real empty descendant scan**, then starts a
closed-stdio child in a new session and exits before the next communication
interval. The helper returns **0 / valid JSON while the child is alive**.
The fixture does not fake process state, liveness or a stopped result; it
deterministically exercises a valid scheduling window. The diagnostic explicitly
kills and verifies its own surviving child afterward.

Production-boundary denied-cleanup reproduction: a config inspector remains live
after both signal APIs deny termination. `call_model` returns a generic billing
preflight rejection, saves `status=blocked`, null active_job/active_check, and no
inspector PID in state. `inspection_containment_unproven` is only a reason string.
The exact owner/launch/descendant identity is not retained for reconciliation or
subsequent admission checks. The helper unit test's exception assertion does not
prove its “retains ownership” title.

This remains the same whole-execution ownership requirement from the previous
brief, not OS isolation or a new hardening feature. Use inherited ownership
markers/guarded launch records and durable uncertainty; more polling cannot
establish the missing parent relation after it disappears.

## Independent execution at this HEAD

Durable files: `evidence/aor31-review-r03/`, SHA256SUMS.json.

| Command/check | Actual result |
|---|---|
| `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts/tests python3 -m unittest test_v31_aor31_corrections test_v31_aor31_r02 test_v31_route_sources test_v31_routing_observation test_v31_runtime_write_integrity test_v31_grant_contention test_v31_stage_deadline -v` | **117 tests, 0 skips, OK, exit 0, 78.067 s**, Python 3.10.12; `review03-focused.log`. |
| Credential-free real V2 opt-in suite | **7 tests, 0 skips, OK, exit 0, 16.148 s**; `review03-v2.log`. Installed V2.2.7; disposable HOME and all XDG roots, minimal environment, update/model fetch disabled; no plugins/inference. |
| `review03.py <checkout>` | Relative account DB hidden; ordinary session update invalidates route; post-snapshot detached child survives a successful result. `review03.jsonl`. |
| `review03_ownership.py <checkout>` | Live inspector with discarded durable ownership after denied termination. `review03-ownership.jsonl`. Diagnostic performs and verifies cleanup after restoring real signal APIs. |
| Supplied evidence checksums and summary inspection | All supplied checksums match; full/red/real-V2 results verified as recorded, not misrepresented as independent reruns. |
| `git diff --check`, `git diff HEAD -- scripts` | Pass; production worktree unchanged by Architect. |

Diagnostic exits are observations, not passing safety assertions. New DB cases
are source-backed V1 supervisor tests using synthetic SQLite; no real V1 binary,
account request, plugin execution or authenticated provider call was performed.
No live saved run, installed version, manual skill or unrelated repository was
modified. Only read-only Docker image discovery was performed.

## Remaining validation and next step

Python 3.12/3.13 were not rerun while reproduced blockers remain. Host interpreter
commands may be absent, but existing images were independently observed:
`python:3.13-alpine` (`sha256:9ef1a599…`) and
`orchestrator-integration-3ornvc:latest` (`sha256:10a19599…`). The next final
verification must use available test environments or report a concrete missing
prerequisite, not categorically mark these interpreters unavailable. No host
interpreter installation or image replacement is needed to use existing images.

The literal independent-auditor scripts are still absent. Preserve the distinction
between their scenarios and saved Architect reconstructions. Authenticated
provider compatibility, actual billing and unattended stability remain outside
the evidence; no such claims are made.

The correction brief changes strategy for the recurring weak boundary: align
storage selection/metadata identity with its upstream contract, and use existing
guarded/durable ownership instead of another independent sampling loop. Freeze
the corrected version/source/grant/symlink paths except necessary integration.
**Final Architect acceptance remains withheld.** A focused closure auditor
should start with the two new scripts and three findings, then verify preserved
prior fixes and the final offline/interpreter/binary matrix at the corrected SHA.
