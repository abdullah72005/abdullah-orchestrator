# v1.2.0 release evidence

Prepared 18 November 2026 for the local v1.2.0 release candidate.

- Candidate base: `7c050ee75d90efb22b96c5c7fafa35e7f04712f7`
- Initial candidate: `49f2b626baf8e8fb495cb990ad4e2cb5d9345acc`
- Corrected candidate (Batch 1 review):
  `26f515b60801582cdc9d6c4261628d7874d3d7bb` (implementation, tests and
  changelog).
- Batch 1 follow-up corrections (r02): code and tests at
  `345ddb43b62226e03d995f02bba8d46d2f385dab`; the evidence commit is its
  documentation-only child. The full suite below ran from the r02 code tree.
  The follow-up evidence commit changes documentation, logs and test/evidence
  assertions only.
- Batch 1 final corrections (r03): code and tests at
  `52e52879cb708cdc97a03c3adc2b76cdcbdd4abb`; the evidence commit is its
  documentation-only child. The r03 suite ran from that exact code/test tree.
- Batch 1 delta-binding correction (r04): code and tests at
  `c575199a8fd627812d52686bc318e964a91ffe86`; the evidence commit is its
  documentation-only child. The r04 suite ran from that exact code/test tree.
- Batch 1 reconstruction-attestation correction (r05): code and tests at
  `4a00126143ed5ab6f9a1ad08afa66754d0f3aeed`; the evidence commit is its
  documentation-only child. The r05 suite ran from that exact code/test tree.
- Batch 1 crash-safe delta publication (r06, this candidate): code and tests at
  `58857664be23653c6fb45fa5412cb2998f3c72f2`; the evidence commit is its
  documentation-only child. The r06 suite ran from that exact code/test tree.
- Public product version: `1.2.0`
- Internal identifiers: supervisor `3.1.0`, state/config schema `3`,
  report contract `2`, verification evidence `2`

This directory records the deterministic evidence produced from the candidate
root. It is a local candidate record, not a publication claim.

## Commands

```bash
PYTHONPATH=scripts/tests python3 -m unittest -v \
  test_v120_release_workflow test_interactive_recovery test_quota_changes \
  test_v31_review_recovery test_v31_acceptance_integrity test_v31_stage_invariants \
  test_v31_stage_deadline test_v31_dispatch_safety test_v31_worker_routes \
  test_v31_campaign_integration test_v31_route_migration \
  test_structured_output_schemas test_v31_claude_setup test_release_version

python3 -m unittest discover -s scripts/tests -v
python3 -m compileall -q scripts
python3 scripts/orchestrator.py version
ABDULLAH_CONFIG="$PWD/scripts/config.example.json" python3 -B -c \
  'import sys; sys.path.insert(0, "scripts"); import orchestrator as o; c = o.config(); o.validate_workflow(); print([o.risk_policy(r, c) for r in ("mechanical", "ordinary", "high")])'
git diff --check 7c050ee75d90efb22b96c5c7fafa35e7f04712f7
```

## Batch 1 follow-up corrections (r02 code `345ddb4`)

The r02 correction closes the four remaining review findings in the same batch:

- Batch deltas capture and compare the real index separately from worktree
  bytes, so staged-only changes and pre-existing staging appear as labelled
  hunks (or a precise unavailable reason). Attempt-chain evidence compares the
  previous completion signature with the next dispatch boundary and records
  explicit uncertainty when that evidence is missing or changed. A Git error
  identifying the dispatch HEAD is reported as unreadable, never as absence.
- Review handoffs are compacted against the selected transport's byte limit
  before admission, preserving the verified packet manifest, delta index and
  check-evidence paths. Truly oversized mandatory context is refused before any
  child is created, with zero model-call counts and consent unspent.
- The exact review packet is validated before launch, at admission and before a
  completed/recovered report gains authority. New-format jobs require the
  producing dispatch binding; historical packet-less jobs keep their old
  behavior. Cleanup quarantines unrecognized files instead of deleting them,
  and linked-worktree exclusions trust only independently validated artifacts.
- Installation guidance distinguishes the published `v1.0.0` tag from the local
  v1.2.0 candidate. The installed V2 read test now generates its hunk through
  the actual supervisor delta path rather than a hand-written patch fixture.

| Check | Command | Result |
|---|---|---|
| Focused gate | `PYTHONPATH=scripts/tests python3 -m unittest -v test_v120_release_workflow test_v31_review_recovery test_v31_dispatch_safety test_v31_acceptance_integrity` | exit 0 — **157 tests, OK** (`focused-b01-r02.txt`) |
| Full suite | `python3 -m unittest discover -s scripts/tests -v` | exit 0 — **953 tests, OK, 8 skipped** in 945.5 s (`suite-b01-r02.txt`) |
| Installed OpenCode V2 module | `ABDULLAH_OPENCODE_V2_BIN="$(command -v opencode)" python3 -m unittest discover -s scripts/tests -p test_opencode_v2_integration.py -v` | exit 0 — **8 tests, OK** on `opencode v2.2.7` (`opencode-v2-b01-r02.txt`) |
| Compile / version / diff | `compileall`, `orchestrator.py version`, `git diff --check 7c050ee..HEAD` | exit 0; `1.2.0` / `3.1.0` / schema `3` / contract `2` (`version-b01-r02.json`) |

The eight full-suite skips are the same opt-in OpenCode V2 tests, run separately
above. The installed read test proves only that the binary's filesystem endpoint
returns the exact bytes of a supervisor-generated projection hunk. It does not
attest a real Reviewer Read-tool invocation, model transport, permission
enforcement or native terminal behavior.

## Batch 1 crash-safe delta publication (r06 code `5885766`)

The r06 correction makes rebuilt delta publication crash-safe:

- `finalize_batch_delta(..., stage=True)` writes a rebuilt index and its hunks
  under a unique `after/staging-<id>/` tree. It never overwrites hunks
  referenced by an already-published index.
- `_record_batch_delta()` publishes the reusable `after/index.json` with one
  atomic replace only after dispatch/completion identity, hunk identity,
  before/after source attestation and artifact-set checks all pass. The durable
  index carries a versioned `attestation` binding the dispatch signature,
  completion signature, projection, source before/after and exact hunk set.
- Reuse requires that attestation. Prior-format indexes without it are treated
  as unproven, preserved aside as `index.prior-<id>.json`, and rebuilt from the
  recorded stopped completion when possible; otherwise the counted incomplete
  attempt and Reviewer limitation are retained. A drifted provisional index is
  left under staging for audit and is invisible to the durable reuse path.
- Interruptions after staging but before post-scan validation, after validation
  but before publish, and after publish but before the state commit are covered.
  The published-but-not-committed case reuses the same attested index checksum
  without duplicating the record.

| Check | Command | Result |
|---|---|---|
| r03–r06 regressions | `PYTHONPATH=scripts/tests python3 -m unittest -v ...BatchCorrectionsR03Tests ...R04Tests ...R05Tests ...R06Tests` | **Ran 27 tests in 57.305s, OK** |
| Focused gate | `PYTHONPATH=scripts/tests python3 -m unittest -v test_v120_release_workflow test_orchestrator test_v31_review_recovery test_v31_dispatch_safety` | exit 0 — **196 tests, OK** in 273.0 s (`focused-b01-r06.txt`) |
| Full suite (single stabilized run) | `python3 -m unittest discover -s scripts/tests -v` | exit 0 — **980 tests, OK, 8 skipped** in 1030.1 s (`suite-b01-r06.txt`) |
| Installed OpenCode V2 module | `ABDULLAH_OPENCODE_V2_BIN="$(command -v opencode)" python3 -m unittest discover -s scripts/tests -p test_opencode_v2_integration.py -v` | exit 0 — **8 tests, OK** in 32.6 s on `opencode v2.2.7` (`opencode-v2-b01-r06.txt`) |
| Isolated timing-sensitive test | `test_v31_stage_deadline...test_decision_child_is_clipped_to_the_remaining_stage_budget` | **Ran 1 test, OK** |
| Compile / version / diff | `python3 -m compileall -q scripts`, `orchestrator.py version`, `git diff --check 7c050ee..HEAD` | exit 0; `1.2.0` / `3.1.0` / schema `3` / contract `2` (`version-b01-r06.json`) |

The eight skips remain the opt-in OpenCode V2 module.

## Batch 1 reconstruction attestation (r05 code `4a00126`)

The r05 correction closes the rebuild-drift gap in `_record_batch_delta()`:

- Rebuilding a delta samples the live checkout. The source identity is now
  observed under the shared projection before sampling, compared with the
  recorded completion signature, and observed again after the index and hunks
  are prepared. Any mismatch, unavailable identity, or change during
  reconstruction yields one counted incomplete attempt with the reason
  `writer delta reconstruction not attributable` (detail distinguishes
  pre-rebuild drift from mid-reconstruction drift).
- A prepared index from a drifted scan is renamed to
  `after/index.drifted-<id>.json`, so it can never later pass an
  exact-completion reuse check. User source bytes and recoverable hunk
  artifacts are preserved.
- The same shared rebuild path serves normal completion, failed/interrupted
  attempts and crash recovery. Exact retained-index reuse, r04 completion
  binding, containment, verification provenance, packet binding and retry
  checks are unchanged.

Regressions (real Git, controlled workers): pre-rebuild drift (`value = 2`
recorded completion, current `value = 3`), a write during reconstruction with
matching initial source, and an unchanged reconstruction that projects the
correct `+value = 2` hunk. Incomplete diagnostics are asserted in the actual
projected `delta/index.json` and Reviewer limitations.

| Check | Command | Result |
|---|---|---|
| Focused gate | `PYTHONPATH=scripts/tests python3 -m unittest -v test_v120_release_workflow test_orchestrator test_v31_review_recovery test_v31_dispatch_safety` | exit 0 — **192 tests, OK** in 261.7 s (`focused-b01-r05.txt`) |
| Full suite (single stabilized run) | `python3 -m unittest discover -s scripts/tests -v` | exit 0 — **976 tests, OK, 8 skipped** in 1014.2 s (`suite-b01-r05.txt`) |
| Installed OpenCode V2 module | `ABDULLAH_OPENCODE_V2_BIN="$(command -v opencode)" python3 -m unittest discover -s scripts/tests -p test_opencode_v2_integration.py -v` | exit 0 — **8 tests, OK** in 31.7 s on `opencode v2.2.7` (`opencode-v2-b01-r05.txt`) |
| Compile / version / diff | `python3 -m compileall -q scripts`, `orchestrator.py version`, `git diff --check 7c050ee..HEAD` | exit 0; `1.2.0` / `3.1.0` / schema `3` / contract `2` (`version-b01-r05.json`) |

The prior r04 timing-sensitive `test_decision_child_is_clipped_to_the_remaining_stage_budget`
failure remains a separate, pre-existing full-suite flake; it passed its exact
isolated command on this tree and the single recorded r05 full run passed. The
eight skips remain the opt-in OpenCode V2 module.

## Batch 1 delta completion binding (r04 code `c575199`)

The r04 correction closes the remaining delta-record binding gap:

- A writer-delta record can no longer be reported complete without an attested
  completion source identity. `_record_batch_delta(..., final_snapshot=None)`
  persists one counted incomplete attempt with the reason
  `writer completion not attested`, which reaches `batch_delta_index()`,
  `delta/index.json` and the Reviewer-visible limitations.
- Retained durable indexes are reused only when their job, attempt, batch/plan,
  dispatch HEAD, dispatch signature, expected completion signature, completion
  projection and every referenced hunk's size/digest agree. A mismatched or
  tampered index is rebuilt from the preserved boundary and matching completion
  when that evidence supports it; otherwise the incomplete-attempt record and
  precise reason are retained.
- Normal completion records the delta only after the existing containment gate
  proves the writer stopped and no source violation blocks completion. A failed
  or interrupted child re-samples the completion after the stop gate; if the
  stop is unproven or the post-stop snapshot fails, no complete evidence is
  produced. Job-id idempotency and already-recorded evidence are preserved.

Probes exercised: missing completion, wrong completion against a valid retained
index, tampered retained hunk, valid retained-index reuse with the actual hunk,
guarded failed worker, unproven stop, and crash-recovered/repeated recovery.

| Check | Command | Result |
|---|---|---|
| Focused gate | `PYTHONPATH=scripts/tests python3 -m unittest -v test_v120_release_workflow test_orchestrator test_v31_review_recovery test_v31_dispatch_safety` | exit 0 — **189 tests, OK** in 323.4 s (`focused-b01-r04.txt`) |
| Full suite | `python3 -m unittest discover -s scripts/tests -v` | exit 0 — **973 tests, OK, 8 skipped** in 1251.4 s (`suite-b01-r04.txt`) |
| Installed OpenCode V2 module | `ABDULLAH_OPENCODE_V2_BIN="$(command -v opencode)" python3 -m unittest discover -s scripts/tests -p test_opencode_v2_integration.py -v` | exit 0 — **8 tests, OK** in 32.1 s on `opencode v2.2.7` (`opencode-v2-b01-r04.txt`) |
| Compile / version / diff | `python3 -m compileall -q scripts`, `orchestrator.py version`, `git diff --check 7c050ee..HEAD` | exit 0; `1.2.0` / `3.1.0` / schema `3` / contract `2` (`version-b01-r04.json`) |

One initial full-suite attempt under load failed the pre-existing timing-sensitive
`test_decision_child_is_clipped_to_the_remaining_stage_budget` on
`failed_jobs`; it passed three standalone runs and the clean full rerun above
produced the recorded 973-test result. No r04 code path is involved in that plan
stage. The eight full-suite skips remain the opt-in OpenCode V2 module.

## Batch 1 final corrections (r03 code `52e5287`)

The r03 correction closes the remaining Batch 1 findings in the same batch:

- Every writer attempt that can reach review is accounted for. Recovery reuses
  a valid preserved delta index or finalizes the exact attempt from its durable
  dispatch boundary; repeated recovery does not append the attempt twice. When
  the boundary, manifest or finalization evidence is missing or unprovable, the
  attempt is still counted and a structured limitation flows through
  `delta/index.json` and the review projection instead of an empty clean list.
  Consumed recovered Implementer reports follow the same exact-attribution rule.
- Dispatch and completion now share one explicit source identity projection
  that includes discovered ignored runtime inputs. An unchanged runtime input
  keeps attempt-chain continuity, a real change is reported as unaccounted, and
  a historical capture without the projection is uncertainty rather than a
  false mismatch.
- Staged bytes outside the capture budget are no longer reconstructed from
  HEAD. The staged hunk and affirmative attribution are suppressed and a
  reviewer-visible limitation names the uncaptured dispatch index state.
- A file removed only from the index now yields a staged deletion hunk while
  the worktree state stays distinct; already-staged and empty deletions are
  explicit, and evidence collection leaves the real index unchanged.
- A crash-recovered Reviewer restores its producing packet/verification
  binding only after the source, packet and process-stop checks, so a still
  current review is reusable once; invalid or changed evidence keeps reuse
  rejected.

| Check | Command | Result |
|---|---|---|
| Focused gate | `PYTHONPATH=scripts/tests python3 -m unittest -v test_v120_release_workflow test_orchestrator test_v31_review_recovery test_v31_acceptance_integrity test_v31_dispatch_safety` | exit 0 — **195 tests, OK** in 284.4 s (`focused-b01-r03.txt`) |
| Full suite | `python3 -m unittest discover -s scripts/tests -v` | exit 0 — **967 tests, OK, 8 skipped** in 1011.3 s (`suite-b01-r03.txt`) |
| Installed OpenCode V2 module | `ABDULLAH_OPENCODE_V2_BIN="$(command -v opencode)" python3 -m unittest discover -s scripts/tests -p test_opencode_v2_integration.py -v` | exit 0 — **8 tests, OK** in 44.8 s on `opencode v2.2.7` (`opencode-v2-b01-r03.txt`) |
| Compile / version / diff | `python3 -m compileall -q scripts`, `orchestrator.py version`, `git diff --check 7c050ee..HEAD` | exit 0; `1.2.0` / `3.1.0` / schema `3` / contract `2` (`version-b01-r03.json`) |

The eight full-suite skips remain the opt-in OpenCode V2 module, run separately
above. The installed test still proves only that the binary's filesystem
endpoint returns the exact bytes of a supervisor-generated hunk under the
checkout review projection. It is distinct from an authenticated Reviewer Read
tool, native terminal lifecycle, model transport, permission enforcement and any
live quality or quota evaluation. All new r03 fixtures use real Git for
staged/worktree behavior and controlled fake workers for dispatch; no live
dispatch occurred.

## Correction cycle results (corrected candidate `26f515b`)

The Batch 1 review correction commit is
`26f515b60801582cdc9d6c4261628d7874d3d7bb` on `feat/orchestrator-v1-2`.
It fixes F1–F5, F7–F10 and A1–A4 without changing the public version or internal
identifiers. The original candidate evidence below is preserved as historical
evidence.

| Check | Command | Result |
|---|---|---|
| Focused gate | `PYTHONPATH=scripts/tests python3 -m unittest -v test_v120_release_workflow test_v31_review_recovery test_v31_acceptance_integrity test_interactive_recovery test_v31_dispatch_safety test_v31_worker_routes test_v31_stage_invariants test_v31_claude_setup test_release_version` | exit 0 — **241 tests, OK** (`focused-correction.txt`) |
| Full suite | `python3 -m unittest discover -s scripts/tests -v` | exit 0 — **940 tests, OK, 8 skipped** (`suite-correction.txt`) |
| Installed OpenCode V2 module | `ABDULLAH_OPENCODE_V2_BIN="$(command -v opencode)" python3 -m unittest discover -s scripts/tests -p test_opencode_v2_integration.py -v` | exit 0 — **8 tests, OK** on `opencode v2.2.7` (`opencode-v2.txt`) |
| Compile / version / diff | `compileall`, `orchestrator.py version`, `git diff --check 7c050ee..HEAD` | exit 0; `1.2.0` / `3.1.0` / schema `3` / contract `2` |

The eight full-suite skips are all opt-in OpenCode V2 tests in
`test_opencode_v2_integration`; they are run separately above and all pass.

The installed V2 module now also proves, with an isolated `HOME` and no model
transport, that the binary's filesystem read path returns the exact bytes of a
supervisor-generated hunk under the checkout's `.git` review projection. That is
the precise boundary verified; it is **not** a model-driven Read-tool invocation
and does not by itself attest agent permission enforcement (the profile test
still asserts effective `read` allow / `external_directory`, `edit`, `shell` and
`subagent` deny). Actual Reviewer tool calls and model transport remain
unevaluated offline.

## Initial candidate results (historical, `49f2b62`)

| Check | Command | Result |
|---|---|---|
| Focused v1.2.0 modules | `PYTHONPATH=scripts/tests python3 -m unittest -v test_v120_release_workflow test_interactive_recovery test_quota_changes test_v31_review_recovery test_v31_acceptance_integrity test_v31_stage_invariants test_v31_stage_deadline test_v31_dispatch_safety test_v31_worker_routes test_v31_campaign_integration test_v31_route_migration test_structured_output_schemas test_v31_claude_setup test_release_version` | exit 0 — **300 tests, OK** (`focused.txt`) |
| Full suite | `python3 -m unittest discover -s scripts/tests -v` | exit 0 — **911 tests, OK, 7 skipped** (`suite.txt`) |
| Compile | `python3 -m compileall -q scripts` | exit 0 |
| Version | `python3 scripts/orchestrator.py version` | `1.2.0` / supervisor `3.1.0` / schema `3` / contract `2` (`version-command.json`) |
| Config/risk policy | `ABDULLAH_CONFIG=... validate_workflow()` + `risk_policy` | mechanical/ordinary/high normalized as expected |
| Diff hygiene | `git diff --check 7c050ee...` | exit 0 |
| Installation smoke | `install_wsl.py --register-codex --register-claude` twice with temporary `HOME`, isolated Codex/Claude fake CLIs | exit 0 both runs; links created once, config created then preserved, Codex/Claude registration idempotent (`install-smoke.txt`) |
| MCP smoke | initialize, `tools/list`, state-only `orchestrator_start` (`skip_doctor`) | 9 tools; start returned `ok: true`, phase `plan`, no model call (`mcp-smoke.txt`) |

The seven skips are all the same opt-in module:
`test_opencode_v2_integration` requires
`ABDULLAH_OPENCODE_V2_BIN` pointed at an isolated tested V2 binary.

## What the offline evidence establishes

- Real supervisor transitions for escalation, bounded retry, versioned replans,
  stale-authority rejection and the high-risk trial gate.
- Real guarded-launcher delivery: exact UTF-8 stdin bytes for Codex/Claude, exact
  OpenCode argv bytes, and pre-dispatch refusal for an oversized OpenCode argv.
- Reviewer independence and attribution: verbatim requirements, no Implementer
  conclusions in the initial packet, exact pre-existing/unstaged/untracked delta
  separation, and a readable checkout-local projection.
- Foreground preview/result/recap fields, including local offset and
  pre-transition batch identity.
- Route/billing safeguards, mechanical exemption, high-risk check minimum,
  historical pin compatibility, version identity and documentation presence.

## Operator activation (not applied automatically)

The shared active configuration at
`/home/abdullah/.config/abdullah-orchestrator/config.json` was **not** modified
by this candidate. Before using v1.2.0 against the installed supervisor, the
operator should check for saved runs that depend on the old config fingerprint
and then make the single documented field change:

```json
{"architect": {"codex": {"model": "gpt-6.2-sol"}}}
```

Leave `effort: "high"` and `auth: "subscription"` unchanged. Do not auto-migrate
installed config or rewrite saved routes; `scripts/config.example.json` already
ships the new default for new installations.

## Explicit limitations

- No live model calls, subscription usage, token savings, wall-clock quota
  comparison, native terminal duration/Esc/reconnect behavior or real host
  acceptance were measured in this offline candidate.
- Native OpenCode V2 read-policy proof depends on an installed isolated binary;
  the deterministic test mirrors the effective policy but is not a substitute
  for that installed-binary check.
- Claude Code remains at its demonstrated fake-CLI/registration support level.
- OpenCode V1 remains experimental.
