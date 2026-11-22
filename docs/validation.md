# Validation and evidence

This page records what was actually exercised, what was found, and what remains
unverified. It is intentionally specific so an independent reviewer can
reproduce or challenge the claims.

## 1. Deterministic test suite

```bash
python3 -m unittest discover -s scripts/tests
```

- **870 tests**, 461–471 s per CI job (Python 3.10, 3.12 and 3.13), with
  opt-in/platform-gated skips: 7 on the maintainer host and 8 on GitHub runners.
  The main opt-in module is the real-OpenCode introspection suite, which runs
  only when `ABDULLAH_OPENCODE_V2_BIN` is set; the remaining skip is
  platform-gated. `pytest` may show a different skip distribution.
- No model calls. A guard replaces `codex`, `claude`, and `opencode` with fakes
  and raises if a test tries to launch a real model CLI.
- Tests are hermetic: exported `ABDULLAH_CONFIG`, `ABDULLAH_STATE_DIR`, and
  `ABDULLAH_CHECKOUT_REGISTRY` values from a real run are replaced with
  temporary paths, so the suite cannot read or write live state.

**Validation policy.** The 870-test row above is historical baseline evidence
for base `7c050ee` on Python 3.10.12 and CI 3.10/3.12/3.13; it is not a result
of the current candidate. During development, run directly affected tests,
negative cases and fast compile/config/link checks; expand to integration
modules when state, recovery, billing, grants, verification authority or
cross-module behavior changes. Run **one complete local suite** on the exact
finalized code/test revision. Do not repeat the full suite for every edit, and
do not treat CI as a replacement for that local gate. A documentation-only
follow-up needs documentation/version checks plus proof that the tested
code/test tree is byte-identical.

Coverage areas:
| Area | Representative tests |
|---|---|
| State machine and phases | plan → implement → verify → review → accept, corrections, amendments |
| Containment | guard sessions, descendants, reused PIDs, zombies, escaped processes, reconciliation |
| Checkout ownership | leases, conflicts, retirement, orphan recovery, adoption, WSL inode fallback |
| Verification provenance | source/env/config/toolchain drift, runtime-input manifests, Docker source proof, legacy evidence |
| Acceptance integrity (AOR-01) | `test_v31_acceptance_integrity.py`: late check-executable/source/env/config/runtime/plan drift, evidence-byte replacement, new-record/new-decision, bound crash recovery |
| Stale-review recovery | `test_v31_review_recovery.py`: incident-shaped PATH drift rewind, environment/check-executable/toolchain classification, unavailable/disallowed checks without execution, nonrecoverable source/plan/config/runtime/incomplete/missing/corrupt/failed/unknown rejection, required record/log integrity before drift recovery, late/re-applied recovery authority binding, current-epoch recovery, active/uncertain ownership, atomic crash seams and idempotent journal audit, completed/recovered Reviewer and decision cache disarming, multi-batch history, separate-process stage/resume contention |
| Read-only stage invariants (AOR-02) | `test_v31_stage_invariants.py`: real Git/fake CLIs, tracked/staged/untracked/HEAD mutation, malformed/nonzero failure paths, recovered-report mismatch |
| Host and dispatch preflight (AOR-04/05/07) | `test_v31_dispatch_safety.py`: missing host, contradictory resume, provider flags, settings helper/malformed settings, inert AWS creds, durable rejection without a job, spawn-failure distinction, Doctor parity; alternate `CLAUDE_CONFIG_DIR`, provider-managed host, managed settings, fallback/model routing keys, post-Doctor contamination, authorized alternate billing |
| Claude setup and stage deadline (AOR-03/06) | `test_v31_claude_setup.py`, `test_v31_stage_deadline.py`: idempotent/conflicting registration, rollback, separate settings/MCP-store destinations and timeout path, whole-stage clipping, genuine accept-stage checks+decision timeout |
| Worker providers and migration | `test_v31_worker_routes.py`, `test_v31_route_migration.py`: mixed routes, non-Go `go`/missing-billing rejection before spawn, bounded non-Go subscription grants, fallback, session boundaries, effective V1/V2 project routing drift, JSONC/env expansion, unreadable config fail-closed, migration pins, restore validation/write-failure, rollback, newer schemas |
| Durable grants across processes | `test_v31_grant_ledger.py`: real separate-process parent→`explore` path, stale parent save, concurrent reservation bound, replay idempotence, public `authorize-route --fallback` sequence; `test_v31_grant_contention.py`: bounded/cancellable separate-process lock, capacity, crash/replay, deadline, nonblocking supervisor ownership |
| AOR31 correction round 01 | `test_v31_aor31_corrections.py`: V1 home/legacy source order, V2 disjoint legacy/native providers and inspector-failure refusal, inspector freshness/parent-above-root drift, prepared-launch inline immutability, unpinned/stale grants, nested symlink content/cycles/budgets, inspector cancel/deadline/descendant cleanup |
| AOR31 correction round 02 | `test_v31_aor31_r02.py`: resolved-executable version/pin validation and matching V1/V2 controls, V1 native `api`/`npm`/model-id remaps, child-cwd relative paths, read-only account-store metadata (active/absent/malformed/unreadable), automatic plugin discovery before V1 and V2 authorization, leader-exit/escaping/regrouped descendant containment, denied termination, and cold version probes under auto/pinned deadline and cancellation |
| AOR31 correction round 03 | `test_v31_aor31_r03.py`: supported V1 DB selection (relative/absolute/`:memory:`/default/XDG/channel selector, unhonored `OPENCODE_DATA_DIR`), routing-metadata projection stable across session writes and benign empty-store initialization, account/active-org change refusal, post-snapshot fast detached inspection containment, detached child after a polling boundary, denied cleanup retaining `uncertain` `active_check` through dispatch/stage/resume/reconcile, and non-run Doctor inspection metadata |
| Full campaign paths | `test_v31_campaign_integration.py`: fake Codex and Claude multi-batch runs, mixed API/free/Go routes through real human authorization helpers, late drift with fresh checks |
| Command policy | shell wrappers, interpreter strings, indirect Docker, scoped exceptions, bypass acknowledgements |
| Report contracts | strict schemas, contract v2, invalid JSONL, recovery without a model call |
| OpenCode dialects | V1/V2 profile generation, effective-permission validation, glob-overlap rejection; version-aware source discovery and authoritative V2 normalization |
| Usage accounting | nested OpenCode usage, derived/partial totals, bounded 429 detection |
| MCP surface | nine tools, no approval/grant tools, cancellation, recovery guidance |
| Release identity | `test_release_version.py`: public version separated from supervisor/schema/contract identifiers, version command, pinned example config |
| Security regressions | credential env scrubbing, API-billing fail-closed, sensitive CLI gating |

The opt-in real-CLI suite makes no model call:

```bash
ABDULLAH_OPENCODE_V2_BIN=/path/to/opencode-2.2.7 \
  python3 -m unittest discover -s scripts/tests -p "test_opencode_v2_integration.py"
```

It checks generated V2 configuration against the real binary's
`opencode debug agents` output, including that appended `allow` rules cannot
reopen mandatory denies. It also checks credential-free `debug config`
normalization for a parent config above the Git root and disjoint legacy/native
provider retention. A failed or unavailable V2 normalizer is intentionally not a
substitute source of authorization.

## 2. v3.1 internal candidate evidence (historical)

The v3.1 batch was validated entirely offline:

```
python3 -m compileall -q scripts
python3 -m unittest discover -s scripts/tests -v
```

The final candidate run and exact counts are recorded in the delivery report and
`docs/agent-handoffs/orchestrator-v3-1/independent-auditor-handoff.md`. Fake
`codex`, `claude`, and `opencode` executables exercise real supervisor code,
temporary Git checkouts, real `run_checks` records and real process containment.
They do **not** prove authenticated model behavior.

### AOR31 remediation (final candidate `0ea5381`)

An independent Architect review of the v3.1 candidate raised four findings. All
four are closed in the current candidate; the exact fix commits, closure matrix,
and limitations are in the
[AOR31 final Architect review](agent-handoffs/orchestrator-v3-1/aor31-final-architect-review.md).

| Finding | Defect | Correction | Regression module |
|---|---|---|---|
| **AOR31-01** | OpenCode configuration precedence could authorize a route that differed from the one actually launched, and legacy Go consent could survive an endpoint override | Dialect comes from the resolved executable's validated actual version; ordered V1 sources and a fresh authoritative V2 normalized document are bound into pins and grants; launch bytes are immutable and re-observed before spawn; unknown, stale, or uninspectable routing refuses | `test_v31_route_sources.py`, `test_v31_routing_observation.py`, `test_v31_aor31_corrections.py`, `test_v31_aor31_r02.py`, `test_v31_aor31_r03.py` |
| **AOR31-02** | Ignored runtime inputs could be mutated by read-only stages without detection because they were outside the write projection | Relevant ignored executable/config inputs and nested symlink target content enter the projection; incomplete manifests block; success, failure, acceptance and recovery paths preserve changed bytes and block without rollback | `test_v31_runtime_write_integrity.py` |
| **AOR31-03** | Concurrent grant-ledger operations could contend or race, allowing capacity to be exceeded | Independent ledger operations wait within configured/cancel/deadline bounds; atomic accounting and reservation replay stay intact; lock timeout is distinct from exhausted capacity; the supervisor ownership lock stays nonblocking | `test_v31_grant_contention.py`, `test_v31_grant_ledger.py` |
| **AOR31-04** | The deadline regression asserted incidental timeout wording instead of safety behavior | Tests assert failed verification, unchanged phase, no acceptance and no later Reviewer/worker; production wording is retained | `test_v31_stage_deadline.py` |

Architect-executed verification at the accepted HEAD (Python 3.10.12):

| Execution | Result |
|---|---|
| Eight focused remediation modules | 135 tests, OK, 0 skips, 194.3 s |
| Integration, provenance, migration, schema and decision-contract modules | 89 tests, OK, 0 skips, 128.2 s |
| Real OpenCode V2.2.7 introspection in a disposable credential-free HOME | 7 tests, OK, 0 skips, 18.5 s (no inference) |
| Full offline suite, Python 3.10 / 3.12 / 3.13 | 830 tests, OK, 731.0 / 833.8 / 834.0 s; 7 skips on the host, 9 in the containers |

The 3.12/3.13 matrices ran before a final eight-line test assertion; production
source is identical across that range, and the changed test was rerun singly on
both interpreters. Those runs are inspected evidence, not an Architect
full-matrix rerun. Reproduce any group with:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts/tests python3 -m unittest \
  test_v31_aor31_r03 test_v31_aor31_corrections test_v31_aor31_r02 \
  test_v31_route_sources test_v31_routing_observation \
  test_v31_runtime_write_integrity test_v31_grant_contention \
  test_v31_stage_deadline -v
```

### Stale-review verification recovery (2026-11-16)

Implementer verification at the batch HEAD (Python 3.10.12), no model calls:

| Execution | Result |
|---|---|
| New recovery module `test_v31_review_recovery.py` | 36 tests, OK, 0 skips, 84.2 s |
| Requested regression set (recovery, report ingestion, provenance, acceptance, interactive recovery, quota/cache, stage invariants) | 203 tests, OK, 0 skips, 269.7 s |
| Full offline suite | 866 tests, OK, 819.8 s, 7 opt-in skips |
| Original saved reproduction at BASE `5d0b8be` | Exit 0: two blocked/review attempts, 0 model dispatches, old evidence bytes preserved |
| Same reproduction against the fixed tree | Exit 1 because verification is now `None` and the run has rewound to `verify`; green recovery is covered by the new module |

Same-batch correction round r01 closes two review findings. Report recovery now
binds authority to the original failed job/dispatch epoch, rejects late or
re-applied old recovery on both apply and consumption, and revalidates job
identity, epoch, phase and batch under the exclusive commit lock. Required
verification record/log integrity is checked before compatible provenance drift
can trigger automatic recovery, so missing, unreadable or malformed artifacts
block instead of being laundered into a rewind. Controls confirm clean drift
still rewinds, clean evidence still reaches fresh review, and current-epoch
recovery still consumes without a model call.

Both findings were subsequently accepted at `b9819a7`, and the preserved
operational run recovered and completed on 2026-11-18 (see section 3).

### Correction round r01

The Architect's nine-blocking-finding correction round was reproduced on the
baseline (`bfd9a8b`) with disposable probes, then covered by permanent tests:
escaped-child source mutation/containment, non-Go `billing: go` and missing
billing, non-Go subscription grant consumption, separate-process nested grant
durability, effective V1/V2 routing/fingerprint drift, Claude alternate
config-dir/provider-managed/managed/fallback hazards, public API fallback
authorization, separate Claude settings/user-MCP destinations, and restore
validation. Exact red/green commands and counts are in the Implementer report and
auditor handoff; temporary probes are evidence, not the production test contract.

Evidence classes are kept separate:

| Class | What it establishes | v3.1 status |
|---|---|---|
| Source inspection | Code paths and guards exist as described | Performed by the Implementer; independently reviewed by the Architect at `0ea5381` |
| Offline fake-CLI tests | Deterministic supervisor behavior and failure paths | Executed; see counts above |
| Installed-CLI introspection | Generated argv/help and V2 agent/permission shapes | Optional suite; skipped when the binary is absent |
| Historical pilot claims | A real v3.0.0 run completed | Historical, not v3.1 recertification |
| Authenticated E2E | Real Claude/Codex stages, Esc/reconnect, new provider routes | **Not executed**; requires separate bounded human authorization |

## 3. v1.0.0 release validation (2026-11-18)

Release preparation was verified independently of the earlier Implementer report.
Checks that do not execute the test suite ran as a non-root user on WSL2 Ubuntu
22.04.5 with Python 3.10.12. No model call, subscription inference or paid request
was made.

Test execution for the release commit is delegated to continuous integration,
which runs the full deterministic suite on Python 3.10, 3.12 and 3.13. The
accepted pre-release revision `b9819a7` carries the last local full-suite
evidence (866 tests, section 2); v1.0.0 adds four release-identity tests and
additive version reporting.

```bash
python3 -m compileall -q scripts
python3 scripts/orchestrator.py version
python3 scripts/orchestrator.py doctor --project /path/to/disposable/repo
```

| Check | Result |
|---|---|
| Compile | OK |
| `doctor` against a disposable Git repo | `ready: true`, dialect `v2`, Go routes, no API billing risk |
| MCP handshake | `serverInfo` 3.1-interactive, 9 tools, no stderr |
| MCP `orchestrator_start` + `orchestrator_status` | state created, `phase: plan`, no dispatch, isolated state root |
| Fresh-`HOME` install | links created, config `0600`, idempotent second run |
| Conflicting pre-existing skill | refused, existing content preserved |
| Example configuration | parses; pins supervisor `3.1.0` and schema `3` |
| Documentation links | 68 relative links, 0 broken files or anchors |
| Credential scan | no keys, tokens, auth databases, env files or private transcripts in tracked files |
| Full deterministic suite | 870 tests, all green in CI on Python 3.10/3.12/3.13 (461–471 s per job) |

Skipped tests are opt-in/platform-gated (8 on the CI runner). The main one is the
real-OpenCode introspection module, which requires `ABDULLAH_OPENCODE_V2_BIN`.
The release environment has OpenCode V2.2.7 installed, and `doctor` performed
real configuration normalization without inference.

### v1.2.0 release candidate (2026-11-18)

Candidate base `7c050ee`; offline worktree with Python 3.10.12 on WSL2. No live
model call, subscription usage, paid request or native terminal session was
measured. Published installation remains the `v1.0.0` tag; v1.2.0 is a local
candidate identified by the revision in
[release evidence](release-evidence/v1.2.0/README.md), not a published tag.

The original candidate (`49f2b62`) evidence is preserved in the release-evidence
directory, as are the r01 (`26f515b`), r02 (`345ddb4`), r03 (`52e5287`), r04
(`c575199`) and r05 (`4a00126`) correction logs. The r06 correction (`5885766`,
code and tests) stages rebuilt indexes and publishes a reusable index atomically
only after the dispatch/completion, hunk and post-scan source checks, with a
durable attestation bound to the exact artifact set; its evidence commit only
adds documentation and logs. No live model call was made by any of these gates.

| Check | Result |
|---|---|
| Focused v1.2.0 modules (original candidate `49f2b62`) | exit 0 — 300 tests, OK |
| Full deterministic suite (original candidate `49f2b62`) | exit 0 — **911 tests, OK, 7 skipped** |
| Focused correction gate r01 (`26f515b`) | exit 0 — **241 tests, OK** |
| Focused correction gate r02 (`345ddb4`) | exit 0 — **157 tests, OK** |
| Focused correction gate r03 (`52e5287`) | exit 0 — **195 tests, OK** |
| Focused correction gate r04 (`c575199`) | exit 0 — **189 tests, OK** |
| Focused correction gate r05 (`4a00126`) | exit 0 — **192 tests, OK** |
| Focused correction gate r06 (`5885766`) | exit 0 — **196 tests, OK** |
| Full deterministic suite (corrected candidate) | exit 0 — **953 tests, OK, 8 skipped** |
| Full deterministic suite (r03 candidate) | exit 0 — **967 tests, OK, 8 skipped** |
| Full deterministic suite (r04 candidate) | exit 0 — **973 tests, OK, 8 skipped** |
| Full deterministic suite (r05 candidate) | exit 0 — **976 tests, OK, 8 skipped** |
| Full deterministic suite (r06 candidate) | exit 0 — **980 tests, OK, 8 skipped** |
| Installed OpenCode V2 compatibility module (r06) | exit 0 — **8 tests, OK** on installed `opencode v2.2.7`, isolated `HOME`, no model transport |
| Installed OpenCode V2 compatibility module (r02) | exit 0 — **8 tests, OK** on installed `opencode v2.2.7`, isolated `HOME`, no model transport |
| Full deterministic suite (final candidate `16a0816`, run at `9a150de`) | exit 0 — **1,069 tests, 1,059 passed, 10 skipped**, 1,779.655 s |
| Installed OpenCode V2 compatibility module (final candidate) | exit 0 — **10 tests, OK**, 45.636 s on installed `opencode v2.2.7`, isolated `HOME`, no model transport |
| Compile | exit 0 |
| `orchestrator.py version` | product `1.2.0`; supervisor `3.1.0`; schema `3`; contract `2` |
| Config/risk policy | valid; mechanical 1 check/no review, ordinary 1 check/review, high 2 checks/review |
| `git diff --check` against base | exit 0 |
| Fresh-`HOME` install, twice | exit 0; links created once; config created then preserved; Codex/Claude registration idempotent |
| MCP initialize/tools/state-only start | 9 tools; start `ok: true`, phase `plan`, no dispatch |

The r06 run skipped eight full-suite cases and the final candidate skipped ten;
all are the opt-in `test_opencode_v2_integration` module, which requires
`ABDULLAH_OPENCODE_V2_BIN`; it is run separately above. Detailed logs are in
[release-evidence/v1.2.0](release-evidence/v1.2.0/README.md).

The installed V2 read test now generates its hunk through the actual supervisor
delta path (`capture_batch_boundary` -> `finalize_batch_delta` ->
`prepare_review_projection`) instead of a hand-written patch fixture. It proves
only that the installed binary's filesystem endpoint returns the exact bytes of
that supervisor-generated hunk under the checkout review projection. It does
**not** attest a real Reviewer Read-tool invocation, model transport, agent
permission enforcement or native terminal lifecycle. The separate authenticated
Reviewer Read and its unobserved shell/edit probes are recorded in the release
evidence.

Not measured in this candidate: live Medium-vs-High planning quality/cost,
token or wall-time savings, native terminal duration/Esc/reconnect behavior,
authenticated Claude stages, provider-backed Claude workers, and live
alternative providers. The one authenticated OpenCode Go Reviewer Read is
recorded separately; its shell/edit probes stayed unobserved, so same-session
capability remains unverified. Fake-CLI and fake-host fixtures establish
supervisor behavior only.

### Post-v1.2.0 follow-up (2026-11-22 → 2026-11-23)

This follow-up adds live stage progress and richer single-chat reporting. It is
kept separate from the v1.2.0 candidate above: the public version, internal
identifiers and release evidence are unchanged, and no tag or release was
created.

| Check | Result |
|---|---|
| Full deterministic suite at `720dd7c` | exit 0 — **1,183 tests, OK, 10 skipped**, 1,715.570 s on Python 3.10.12 |
| Focused follow-up gate before the final revision | exit 0 — **326 tests, OK**, 694.272 s |
| `git diff --check` on the documentation commit | exit 0 |
| Documentation commit `scripts/` tree | byte-identical to `720dd7c` |

The 1,183-test result belongs to the accepted feature revision
`720dd7c2e4c0b404cccc430e14f40c1f1385dd04`. It does not replace the v1.2.0
result of 1,069 tests at `16a0816` (recorded at `9a150de`), and it is not a
v1.2.0 or CI recertification. The 10 skips remain the opt-in
`test_opencode_v2_integration` module; its separate installed-CLI run is
unchanged by this follow-up.

Deterministic coverage for the chat reporting itself is in
`scripts/tests/test_chat_reporting.py`: bounded plan views, material-first
finding previews without mutating the report, completed-Implementer versus
verified-test wording, current blocked questions, default automation versus
explicit consultation, a material reply carried into a versioned revised plan,
earlier approval not authorizing a revision, canonical verdict retention,
developer-recap detail, amendment superseding a question, and digest/job/scope
binding that rejects foreign or stale planning artifacts.

Live progress coverage is in `scripts/tests/test_live_stage_progress.py`:
attempt identity and matching end records, live versus recorded elapsed time,
side-effect-free reads, bounded and terminal-safe activity, verification
argv exclusion, admission-bound progress notifications, nonblocking sink
closure, containment during stalled writes, malformed tokens and `_meta`, and
the terminal viewer's waiting, ticking, reattachment, plain-mode and narrow
output paths.

Client behavior verified on this follow-up: Claude Code CLI `2.1.247` rendered
native MCP progress in its TUI; Codex CLI `0.169.1` received notifications but
printed only tool start/completion, so the adjacent `status --follow` observer
was used; the Windows Codex desktop with a WSL agent verified the observer in
the integrated terminal during a 32.92 s Implementer stage. Remaining
unverified: Claude desktop in-chat progress and its observer, Codex desktop
tool-card progress and in-app Stop, fresh-thread recovery in the desktop UI,
and authenticated long Claude stages.

### Real end-to-end milestone (2026-11-16 → 2026-11-18)

Run `20261116T124500-973e8c02`, on a dedicated isolated Codex profile, config,
state root and disposable project:

| Stage | Route | Observed |
|---|---|---|
| plan | Codex subscription, `gpt-6.1-sol` high | Completed, plan versioned |
| implement | OpenCode Go `deepseek-v4.1-flash` high | Completed, `duration.py` implemented |
| verify | `python3 -m unittest discover -s tests -t . -v` | Exit 0, **44 tests OK** |
| review #1 | OpenCode Go, high | Interrupted by an operator command timeout at ~85 s; guard contained it, `stopped: true`, no survivors |
| review #2 | — | Blocked: stale verification provenance (PATH/toolchain drift), then rewound once to `verify` after the r01 correction |
| verify #2 | same command | Exit 0, 44 tests OK against the unchanged candidate |
| review #3 | New independent OpenCode Go Reviewer | Completed with findings and dispositions |
| accept | Codex `gpt-6.1-sol` | `approved`; evidence and decision binding revalidated |
| Final state | — | `complete`, no active job/check, no checkout conflict |

Recorded usage: 2 strong calls, 2 cheap calls, 0 API-billed dispatches, reported
provider cost `0.0` (subscription/Go). Model time ~402 s; elapsed wall clock
spanned operator pauses and is **not** endurance evidence.

The run began on `0ea5381`; its interrupted-review recovery and acceptance were
completed on 2026-11-18 with the accepted recovery implementation (`b9819a7`).
The initial `start` invocation unintentionally used the CLI form, which serves
the run immediately; that is documented as an operator footgun in
[troubleshooting](troubleshooting.md#cli-start-dispatched-models-immediately).
Containment, route pinning and billing classification behaved as designed.

## 4. Historical real end-to-end pilot (v3.0.0)

This pilot predates v3.1 and is retained as historical evidence, not as proof
that the v3.1 acceptance-binding, host-gating, stage-deadline, installer, or
provider-route changes were exercised live.

On **2026-11-13**, the complete implementation ran a real goal through a real
Codex conversation on an isolated copy of the repository. Nothing was installed
globally for the pilot; MCP registration, config, state, and the disposable
project were all pilot-local.

| Item | Value |
|---|---|
| Run ID | `20261113T104752-32561af8` |
| Host | Interactive Codex CLI `0.169.0`, ChatGPT subscription auth |
| Architect | `gpt-6.1-sol`, high effort |
| Workers | OpenCode `v2.2.7`, Go billing, `deepseek-v4.1-flash` high |
| Explorer policy | `none` (no Explorer dispatch) |
| Goal | Implement a standard-library duration parser (`1h30m → 5400`) in a disposable Git repo |
| Verification | `python3 -m unittest discover -s tests -t . -v` |
| Outcome | **complete**, Architect verdict `approved` |

Actual stage evidence from the run:

| Stage | Result |
|---|---|
| Architect plan | Completed; plan version recorded, one batch, risk `ordinary` |
| Implementer | Completed; `duration.py` + `tests/test_duration.py`, contract v2 report |
| Supervisor verification | Exit 0 against candidate `9bbc5756…`; evidence version 2 |
| Independent Reviewer | Completed; findings recorded with dispositions |
| One correction cycle | Used; long-quantity chunk bug found and fixed |
| Architect acceptance | Approved after direct inspection of code, diff, evidence, and a fresh 22-test run |
| Total | 5 strong calls, 4 cheap calls; 6 h 3 min elapsed, 755.8 s of recorded model time |

Recorded usage: 110,216 input tokens, 10,768 output tokens, 13,539 reasoning
tokens, 490,112 cache-read tokens. Cost is reported as `0.0` for subscription +
Go; no quota is inferred.

### Defects the pilot exposed

The pilot was valuable precisely because it failed twice before succeeding.
Each failure produced a permanent regression test.

| # | Symptom | Root cause | Fix |
|---|---|---|---|
| 1 | Codex returned HTTP 400 `invalid_json_schema` before planning | Generated strict schema omitted `verification_purpose` from `required` while declaring it | `4a23a00` — emit strict-compatible schemas and require every declared key |
| 2 | A valid `changes_required` verdict was rejected at acceptance | Decision schema omitted `contract_version`, which the validator required and strict mode could not add | `f35e14f` — declare and require `contract_version` in the decision schema |
| 3 | OpenCode reports with escaped/unparseable JSON could not be recovered | Ingestion failure was generic and lost the distinction between transport and report failure | `d80bea0` — classify ingestion failures and add `recover-report` with preserved artifacts |

Regression fixtures are copied byte-for-byte from the failed jobs and are
referenced by SHA-256 in the test docstrings:

- `fixtures/architect-plan-schema-pre-fix.json`
- `fixtures/decision-schema-pre-fix.json`
- `fixtures/decision-report-pre-fix.json`
- `fixtures/opencode-v2-implementer-invalid-json.jsonl`

No verdict was hand-edited into the run to bypass provenance. The failed
decision artifact was preserved, the schema was fixed, and a new Architect
decision call was made — acceptance did not silently reuse a failed job.

### Why this is meaningful

- The same supervisor code path ran: real MCP server, real guard, real CLI
  processes, real Git worktree, real verification logs.
- The supervisor, not the model, executed the checks and bound the evidence.
- The independent Reviewer found a real defect, the correction was bounded, and
  the final Architect decision inspected the actual diff and re-ran the tests.
- Recovery was exercised: the run survived two supervisor restarts and resumed
  from persisted state without repeating completed stages.

## 5. Independent audit trail

The implementation was audited in stages before this release. Documents are
preserved in [`docs/audit/`](audit/):

| Document | Contents |
|---|---|
| [`final-hardening-notes.md`](audit/final-hardening-notes.md) | Baseline findings, OpenCode V2 discovery, initial gap list |
| [`final-audit-evidence.md`](audit/final-audit-evidence.md) | Before/after probes for command policy, provenance, MCP approvals, acceptance gates |
| [`delta-audit.md`](audit/delta-audit.md) | Five reproduced acceptance blockers and their fixes, with the exact commits |

Highlights of what changed as a result:

- Plan approval and fallback authorization removed from the MCP surface.
- V2 permission validation rewritten to evaluate ordered rules by glob overlap,
  not by sampling paths.
- Toolchain identity keyed on file fingerprints so an in-place upgrade
  invalidates evidence.
- Mandatory decision context (findings, amendments, evidence, source identity)
  can no longer be replaced by an opaque hash.
- Partial token totals are labelled instead of being reported as complete.
- Scoped command exceptions require a project identity.

## 6. What is not verified

Be explicit with reviewers and users:

- **A separate third-party closure audit has not happened.** The AOR31
  remediation received a final independent Architect acceptance
  (“APPROVED WITH KNOWN LIMITATIONS”, accepted HEAD
  `b9819a75c10433d9e8d082e049c2a31084d0e416`) and the real E2E below. That is not
  the same as an external security audit.
- **The literal independent-auditor scripts were never supplied.** Saved
  Architect reconstructions and regression equivalents were rerun; no claim is
  made that the unavailable scripts ran.
- **OpenCode V1 has no runtime verification.** V1 behavior is source-backed and
  tested with fixtures and fakes against the pinned upstream contracts; no V1
  binary was available, so no V1 compatibility claim is made. V2.2.7 was tested
  for normalization and permissions, not for provider inference.
- **Authenticated model execution is not covered by the default suite.** Two
  historical real paths exist: the v3.0.0 pilot and the v1.0.0 milestone run,
  both Codex + OpenCode Go. Neither is a compatibility matrix. A separate
  authenticated OpenCode Go Reviewer Read is recorded in the v1.2.0 release
  evidence; its shell/edit probes were not observed, so same-session capability
  remains unverified.
- **Claude host mode.** The installed CLI connected to the stdio server and
  completed a headless planning stage with local fixtures. Automated tests cover
  registration, rollback, flags, deadlines and a Claude-hosted workflow with
  fixture workers. Interactive Escape, reconnect, `/mcp` and authenticated
  long stages remain unverified. [Claude Code CLI evidence](release-evidence/v1.2.0/README.md#claude-code-cli-compatibility)
- **Windows desktop UI controls.** The Windows Codex desktop with its agent in
  WSL discovered the skill and completed planning and implementation through
  the disposable supervisor. In-app Stop, live worker activity and fresh-thread
  recovery were not exercised in the UI; the operator deferred the desktop Stop
  retest. Native backend and Windows-to-WSL stdio cancellation/recovery are
  separate evidence. [Windows desktop evidence](release-evidence/v1.2.0/README.md#native-windows-codex-desktop-compatibility)
- **New provider routes and fallback** are exercised with fake CLIs and route
  policy tests, not with paid/local provider accounts. Billing classifications
  are attested policy, not provider settlement; no dollar/token cap is proven.
- **Installed-CLI introspection** is optional and may be skipped when the binary
  is absent; `test_opencode_v2_integration.py` keeps those skips separate.
- **OS isolation is not provided.** Permissions and containment are
  application-level; a dedicated user/container remains the operator's job.
- **Long-duration behavior** (multi-hour stages, host sleep, network partition)
  is covered by design and deterministic timing tests, not by a timed production
  run. The milestone run's elapsed time was wall-clock idle plus ~7 minutes of
  recorded model/verification time, so it is not endurance evidence.
- **Docker verification** was unit-tested with synthetic Compose evidence; the
  milestone project did not use containers.
- **Linux-only managed configuration.** Managed OpenCode/Claude files are
  covered on Linux; macOS and Windows managed delivery is not certified.
- **`doctor`** does not authenticate, prove entitlement, or run a model.

## 7. Reproducing the checks

```bash
# deterministic suite (offline)
python3 -m unittest discover -s scripts/tests

# compile check
python3 -m compileall -q scripts

# optional: real V2 CLI introspection, no model call
ABDULLAH_OPENCODE_V2_BIN=/path/to/opencode-2.2.7 \
  python3 -m unittest discover -s scripts/tests -p "test_opencode_v2_integration.py"

# preflight on a real project
python3 scripts/orchestrator.py doctor --project /absolute/path/to/repo
```

A clean-room validation from a fresh clone is the authoritative check for a
release ZIP: install nothing globally, run the suite, then inspect the
repository tree against `git ls-files`.

## Post-v1.2.0 TODO

- [x] Implement live worker progress for the active Orchestrator worker: before
  launch show the worker and model, batch task, and expected output; while it
  runs show elapsed time and the latest reported activity when available;
  preserve the existing foreground stage and interruption behavior.
  Implemented with `orchestrator_status.stage_progress`, MCP progress
  notifications and the read-only `status --follow` observer. The full
  deterministic result is 1,183 tests at `720dd7c`; evidence below.
- [x] Verify the Windows Codex desktop WSL terminal observer during a live
  Implementer stage. In-app Stop and native tool-card progress remain unverified.
- [ ] Complete client-level live progress across every CLI and GUI host.
  Verified: Claude Code CLI native TUI progress and the Windows Codex desktop
  integrated-terminal observer. Unverified: Codex CLI in-chat rendering, Codex
  desktop tool-card progress, in-app Stop and fresh-thread recovery, Claude
  desktop in-chat progress and observer, and authenticated long Claude stages.
- [ ] Verify the Claude desktop presentation with the adjacent terminal observer.

### Live progress evidence (post-v1.2.0)

Client protocol probes used disposable repositories and a fixture MCP server
whose slow tool emits progress only when the client supplies a token. They
establish what each installed client does with notifications; they do not
replace the orchestrator-level checks below.

| Surface | Version | Evidence |
|---|---|---|
| Claude Code CLI | `2.1.247` | Fixture probe: `progressToken: 2` and native TUI ticks. Correction rerun (real orchestrator MCP, disposable repo, delayed fixture worker, loopback model): the TUI rendered `Implementer — DeepSeek opencode-go/deepseek-v4.1-flash · implement · Batch 1/1 … preparing the stage · 1s`, ticking to `30s`, then `step finished · 33s`, `Called orchestrator`. The recorded attempt end is 33.75 s on the containment candidate (`d724f28`). Native rendering confirmed. |
| Codex CLI | `0.169.1` | Fixture probe: integer `progressToken: 1`, six ordered notifications during a three-second call, terminal printed only `mcp: probe/probe_wait started` / `(completed)`. Containment-candidate rerun (real orchestrator MCP, loopback model, 33.7 s delayed stage): `mcp: orchestrator/orchestrator_stage started` … `(completed)` with no progress text. The adjacent `status --follow` pty observer ticked `elapsed 1.0s` … `33.3s`, ended `measured 33.7s`, `outcome: complete`, and showed the next stage's safe task (`Run supervisor verification checks`) and expected output. |
| Codex desktop, WSL agent | `26.1111.2228.0` Windows package | The desktop chat ran one Implementer stage. The integrated-terminal observer showed elapsed time at 0.8, 2.3, 17.3 and 32.4 s before showing completion at a measured 32.92 s. The run reached `verify` with the edit present and no active job or check. [Smoke evidence](release-evidence/live-progress/README.md#windows-codex-desktop-result) |
| Claude desktop | n/a | No suitable desktop profile was available in this batch. Pending. |

The fixture and the exact operator steps are recorded with the batch evidence.
Stage-level checks (real supervisor, disposable repository, delayed fake worker)
cover multiple notifications before the final stage response, no trailing or
cross-request notifications, tokenless and invalid-token silence, cancellation,
attach during a stage, and a viewer that ticks while the worker runs without
changing its outcome.

**Single-chat presentation.** The chat workflow on all four surfaces uses a
visible stage announcement and measured result. Native in-flight updates are
verified in Claude Code CLI. A model-driven turn on Codex app-server `0.169.1`
completed the fixture MCP call after six valid progress notifications, with
zero `item/mcpToolCall/progress` events forwarded to the app-server client.
This isolates the forwarding limit on that build and probe. The Codex desktop
operator saw the tool card and result in chat. The terminal viewer is optional.
An in-chat desktop MCP App card and the experimental Codex CLI MCP status line
are candidate presentation paths that still need client-level tests.

The containment correction adds deterministic coverage for cancellation and
host EOF entering containment/emergency stop while a progress write is stalled,
nonblocking sink closure, and injected failure of advisory activity writes
during admission, worker launch/report handling and verification (same stage
outcome, matching end, no stale attempt or context, preserved edit and
verification evidence).

The correction batch adds deterministic coverage for exact admission binding
(two requests to one run with different tokens and a refused concurrent
admission), a progress read held beyond the final response, cancellation closing
the sink, malformed `_meta` and invalid tokens, verification argv exclusion for
recorded and upcoming verify stages, attempt-scoped lifecycle observations,
unproven owner identity, C1/ANSI sanitization, malformed structured worker
records, bounded heartbeat reads, a full-journal recap preserved beside the
bounded heartbeat tail, the plain-mode heartbeat, final-save-before-journal
ordering, and narrow/shrinking terminal rendering. A runnable desktop fixture
and operator steps are in
[docs/release-evidence/live-progress](release-evidence/live-progress/README.md).
