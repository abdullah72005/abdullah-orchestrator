# AOR31 — Architect review round 01

**Disposition: CHANGES REQUIRED.** Review of implementation commit
`7987d2672ceedad7e7785e02914f11f18502849c` against
`b9139946db5684e3e48724b9e1060af355362e82` and the user-approved
[batch brief](aor31-remediation-batch-01.md).

The four original findings have useful fixes and passing regressions, but the
billing gate still approves or launches routes without the required material
binding, and nested ignored runtime content remains undetected. These are
acceptance-path defects, not accepted limitations. Execute the focused
[correction handoff](aor31-fix-b01-r01.md) in a fresh original Implementer session.

## Actual repository and review coverage

- Checkout `/home/abdullah/.local/src/abdullah-orchestrator-v3-1`, branch
  `design/orchestrator-v3-1`; HEAD matches the Implementer's reported SHA.
- One implementation commit: `7987d26 fix: bind effective routing material and
  runtime writes`; 9 tracked files, +2,341/-151 lines. The full diff from BASE
  was inspected, including all changed production code, new regression modules,
  test-fixture changes and the example config.
- Before review, only the prior Architect brief/investigation/evidence were
  untracked. No tracked working-tree differences. This review adds only new
  Architect review/correction/evidence artifacts; production code is unchanged.
- Maintained documentation was not updated in the implementation commit despite
  changed configuration, authorization, provenance and compatibility behavior.
- No push, installation, release, real run mutation, authenticated provider
  request or automated orchestrator self-modification was performed by this
  review. Dispatch tests use test-owned fake CLIs; real binary calls use only
  credential-free, disposable `debug config --standalone` normalization.

## Finding-by-finding closure matrix at reviewed HEAD

| Original finding | Independent assessment | Status |
|---|---|---|
| AOR31-01 P1 config/billing | Saved R2/R4/R5 now reject Go overrides, but source-adapter, freshness, launch-context and unpinned-grant gaps remain. | **OPEN — R01-F1/F2/F3/F4**, plus inspector cancellation F6. |
| AOR31-02 P2 ignored runtime inputs | Original ignored-Python planning probe now blocks and preserves the edit. Nested linked runtime input still passes with complete equal projections. | **OPEN — R01-F5**. |
| AOR31-03 P2 grant contention | Separate-process saved probe now consumes exactly two allowed reservations successfully. Submitted 16-test contention module passes; source retains independent lock, atomic accounting, conservative crash behavior and nonblocking supervisor lock. | Focused source/Python-3.10 evidence passes; retain and recheck affected integration after fixes. No new ledger-contention defect identified. |
| AOR31-04 P3 deadline test | String dependency removed; 5 submitted tests pass on Python 3.10.12. Pre-child expiry and clipped-child paths assert safety outcomes. | Focused test-contract fix passes. Implementer reports full 3.13 success; this review did not independently rerun or inspect complete per-interpreter logs. Final gate remains pending. |

## Blocking review findings

| ID | Severity / location at 7987d26 | Concrete failure and impact |
|---|---|---|
| R01-F1 | P1 — `_opencode_config_sources:1425`, `_opencode_normalize_v2_document:1732`, source-adapter fallback | V1 home `.opencode` config is omitted; V1 legacy global `config.json` order is reversed. Both reconstructed cases approve a custom endpoint as Go. V2 fallback drops a disjoint legacy Go provider when a native different provider exists; actual V2.2.7 retains both. Generic failed/malformed/plugin-skipped inspection only warns about unobserved external sources and still authorizes. |
| R01-F2 | P1 — `_opencode_project_chain:1406`, inspection cache `1968` | Real V2.2.7 loads a config above the Git root; adapter records omit it. Editing that endpoint returns the cached original endpoint and identical pin; final recheck returns None. A fresh binary sees the replacement endpoint. A prior grant can therefore be checked against stale material. Source identity is also absent from the fingerprint's material branch when no selected provider entry exists. |
| R01-F3 | P1 — `call_model:6891`, `6939`, `6960` | Inline routing is re-read after preflight/recheck. Changing ambient inline during dispatch-snapshot preparation launches the fake worker with a custom Go endpoint and zero grants. The later report-schema rejection does not undo the unauthorized launch. Inspector receives a routing-only inline subset, while actual dispatch regenerates full controls. |
| R01-F4 | P1 — `route_authorization_sha:2483`, `authorize_route_run:11410` | Public helper creates a new grant for an unpinned schema-3 worker route. After endpoint changes, preflight remains `ok=true`, `authorized=true`. Adding a new grant-format marker while allowing missing material does not close label-only authorization. |
| R01-F5 | P2 — `_bounded_tree_digest:3712` | For ignored `runtime -> .cache/lib` with `module.py -> ../shared.py`, a fake planner changes `.cache/shared.py`. Both manifests remain complete, projections equal and one completed job is accepted. Only nested link text is hashed. |
| R01-F6 | P2 — `_opencode_run_bounded:1888`, model launch boundary | Cancellation during fake inspection is not polled; inspection times out, falls back/repeats, then `_spawn_guarded` is called after cancel. Only model monitoring raises `InterruptedError`. The “cancellable” helper has no cancellation context. |

Each finding has bounded corrections and regression requirements in the saved
fix brief. F1–F4 block billing acceptance; F5 blocks read-only integrity; F6
blocks cancellation/ownership acceptance. Missing maintained docs and full
closure evidence must also be completed without rewriting historical reviews.

## Independent evidence actually executed

All durable files are in `evidence/aor31-review-r01/`, with SHA256SUMS.json.
Diagnostic scripts emit observations and normally exit 0 even when they expose
a defect; they are not automatically passing regression tests.

1. `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts/tests python3 -m unittest
   test_v31_route_sources test_v31_runtime_write_integrity
   test_v31_grant_contention test_v31_stage_deadline -v`
   — **50 tests, 0 skips, OK, 32.064 s, exit 0**, Python 3.10.12.
   Log: `review01-focused.log`.
2. Saved `evidence/aor31/route_probe.py`, installed
   `/home/abdullah/.opencode/bin/opencode` V2.2.7 — six CLI exits 0;
   R2/R4/R5 now `ok=false`, `unqualified_go_route`; R2/R5 edits change pins;
   R1/R3/R6 remain benign. Log: `review01-saved-route.jsonl`.
3. Saved `evidence/aor31/boundary_probe.py` — original ignored Python mutation
   now raises SourceMutationError, completes zero jobs and preserves changed
   bytes. Both overlapping grant reservations succeed, final usage 2.
   Log: `review01-saved-boundary.jsonl`.
4. `review01.py <checkout>` — five additional disposable fake/source tests:
   omitted V1 home config, reversed V1 global legacy order, V2 fallback
   coexistence, changed post-recheck child inline, and nested symlink mutation.
   Log: `review01.jsonl`.
5. `review01_binary.py <checkout> /home/abdullah/.opencode/bin/opencode` —
   real V2.2.7 normalization and parent-config cache reproduction; also confirms
   real disjoint legacy/native provider retention. No inference/plugins;
   temporary HOME and CONFIG/DATA/CACHE/STATE XDG roots; update/models fetch
   disabled. Fresh CLI exits 0. Log: `review01-binary.jsonl`.
6. `review01_extra.py <checkout>` — public unpinned grant accepts the changed
   endpoint; cancel during 0.4-second-limited fake inspection still calls model
   spawn once afterward (~2.027 s until InterruptedError).
   Log: `review01-extra.jsonl`.
7. `git diff --check` passes; `git diff HEAD -- scripts` is empty.

The installed binary identity remains the V2.2.7 binary recorded by the initial
investigation (SHA256 `589253d36810f21217edd51545cd435b328cdc3cf4f451fbe0cce6f88afcf5e1`).
The V1 adapter findings are reproduced supervisor outcomes checked against pinned
upstream source, not real V1 binary executions. Source authority:
[V1 loader](https://github.com/anomalyco/opencode/blob/v1.18.35/packages/opencode/src/config/config.ts),
[V1 directory sources](https://github.com/anomalyco/opencode/blob/v1.18.35/packages/opencode/src/config/paths.ts),
[V2 discovery](https://github.com/anomalyco/opencode/blob/v2.2.7/packages/core/src/config/discovery.ts),
[V2 normalization](https://github.com/anomalyco/opencode/blob/v2.2.7/packages/core/src/config/normalize.ts).

## Limits and next review gate

Implementer reports complete suites of 761 tests on 3.10, 3.12 and 3.13 and five
real V2 tests. These are reported evidence, not this review's executed checks;
complete durable per-interpreter logs were not supplied in the handoff. This
review did not duplicate those full suites while confirmed blockers remain.
After corrections, preserve complete commands/versions/logs/skips against the
final HEAD and fill the parent contract's final verification matrix.

The independent auditor's three literal probe scripts were not supplied; saved
Architect reconstructions remain distinguished from originals. Real V1,
macOS/Windows managed settings, authenticated providers, billing settlement and
long unattended operation remain unverified. Unknown influential routing cannot
be relabeled a nonblocking limitation while preflight authorizes it.

**Final Architect acceptance is withheld.** Continue through the saved correction
brief, then independently re-review the actual cumulative changes and corrected
integration boundaries. Focused closure auditor should start with F1–F6 and
their saved scripts, then the final regression/evidence matrix; no need to
reopen unrelated architecture.
