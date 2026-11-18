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
- Batch 1 final corrections (r03, this candidate): code and tests at
  `52e52879cb708cdc97a03c3adc2b76cdcbdd4abb`; the evidence commit is its
  documentation-only child. The r03 suite ran from that exact code/test tree.
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
