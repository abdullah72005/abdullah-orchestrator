# AOR31 independent audit — Architect investigation

Date: 2026-11-14. Disposition: **findings substantiated; design approved by user**.
This is investigation evidence, not remediation closure or provider certification.

## Source identity and preservation

- Active candidate: `/home/abdullah/.local/src/abdullah-orchestrator-v3-1`,
  branch `design/orchestrator-v3-1`, HEAD
  `b9139946db5684e3e48724b9e1060af355362e82`, initially clean.
- Audit baseline `828202f619209390411c9ed37da5ff2a179242a3` is its parent.
  `git rev-list --left-right --count <baseline>...HEAD` returned `0 1`.
  `git diff <baseline> HEAD -- scripts` is empty: the added commit publishes
  README and campaign review/evidence documentation, not runtime changes.
- Read-only remote check `git ls-remote github refs/heads/main` returned the
  exact same `b913994…` SHA. The v3.1 candidate is on GitHub main; the older
  checkout `/home/abdullah/.local/src/abdullah-orchestrator` at `b71f84e…`
  is not the development target. Other worktrees were not modified.
- No Git fetch/reset/branch/commit/push, installer, real run mutation, provider
  inference or release was performed. No automated workflow modified itself.
  Diagnostics used temporary repositories, config, ledgers and fake model CLIs.
  Only this planning brief/evidence were added to the candidate checkout.
- LeanCTX initially bound the older checkout and denied sibling access. The
  user explicitly instructed “ignore lean”; native source inspection resumed
  under that later authorization. No Lean security setting was changed.

## Finding-by-finding investigation matrix

| Finding | Technical basis / reproduced result | Closure status |
|---|---|---|
| AOR31-01, P1 | `_opencode_config_files:1380` loads explicit before global, models custom-dir as one global replacement for both dialects, and omits supported sources. `_opencode_child_config:1524` puts managed files before inline. `opencode_provider_observation:1673` only reads the selected dialect's raw provider container. Installed V2.2.7 probes R2/R4/R5 returned `go_subscription`, `ok=true`, endpoint unobserved, despite authoritative normalized documents carrying a custom selected-provider endpoint. R2/R5 endpoint edits also left the pin unchanged. | Confirmed, open; version-aware observation and source identity fix required. |
| AOR31-02, P2 | `source_write_projection:3514` explicitly excludes runtime manifests. A valid fake Codex planning child changed ignored `ignored_helper.py`; manifest hashes changed but projection stayed equal, `source_mutation.mutated=false`, and one completed job was accepted. The changed file was preserved. | Confirmed, open; extend common integrity projection and replay boundaries. |
| AOR31-03, P2 | `_reserve_in_ledger:1939` calls `exclusive:405` with default `LOCK_NB`. Two independent eligible processes, capacity 2: first held the ledger critical section for 0.5 seconds, second failed in ~0.0002 seconds with “Another supervisor owns this run”; first then succeeded, final usage 1. No oversubscription observed; unnecessary contention failure is reproduced. | Confirmed, open; dedicated bounded/cancellable ledger waiting. |
| AOR31-04, P3 | Assertion at `test_v31_stage_deadline.py:57` requires `timed out`. `remaining_budget:192` safely raises the alternative text. With a genuine 0.001-second budget, production `stage_run` returned `ok=false`, verify/blocked, “Whole-stage deadline exceeded before the next child”, no verification, no completed/active model job. Existing four-test module passes on Python 3.10.12; the reported Python 3.13 failure was not run here. | Assertion fragility and safe alternative path confirmed; Python 3.13 evidence pending. |

## OpenCode source authority and important dialect distinction

Available binary `/home/abdullah/.opencode/bin/opencode` reports
`opencode v2.2.7`; SHA256:
`589253d36810f21217edd51545cd435b328cdc3cf4f451fbe0cce6f88afcf5e1`.
The staged `/tmp/ocv2/opencode` also reports V2.2.7; no supported V1 binary was
located in the examined executable locations. Python on PATH is 3.10.12;
`python3.12` and `python3.13` are absent there. No tools were installed.

Primary upstream sources inspected at release tags (not a guessed common order):

- [V1.18.35 config loader](https://github.com/anomalyco/opencode/blob/v1.18.35/packages/opencode/src/config/config.ts):
  `loadGlobal` reads `Global.Path.config` including legacy `config.json`, then
  explicit file, project files, config directories, inline, account and managed
  layers. Managed settings can supersede inline.
- [V1 global paths](https://github.com/anomalyco/opencode/blob/v1.18.35/packages/core/src/global.ts)
  and [directory discovery](https://github.com/anomalyco/opencode/blob/v1.18.35/packages/opencode/src/config/paths.ts):
  static `Global.Path.config` remains ordinary XDG config; the custom directory
  is appended separately. The service's alternate config path does not erase
  the loader's explicit use of the static path.
- [V2.2.7 server environment mapping](https://github.com/anomalyco/opencode/blob/v2.2.7/packages/cli/src/server-process.ts)
  replaces the global root with `OPENCODE_CONFIG_DIR`. Its
  [discovery](https://github.com/anomalyco/opencode/blob/v2.2.7/packages/core/src/config/discovery.ts)
  and [loader](https://github.com/anomalyco/opencode/blob/v2.2.7/packages/core/src/config.ts)
  expose ordered normalized entries: managed policies, integration/well-known,
  global, explicit, direct project, supplementary project directories, content,
  managed settings. Policy evaluation is separate from setting precedence.
- [V2 normalization](https://github.com/anomalyco/opencode/blob/v2.2.7/packages/core/src/config/normalize.ts)
  accepts supported V1 fields too, including legacy provider material.
  [Provider overlay](https://github.com/anomalyco/opencode/blob/v2.2.7/packages/core/src/config/plugin/provider.ts)
  applies ordered settings, models and variants; debug entries are not one
  already-folded generic dictionary.
- [V2 debug config](https://github.com/anomalyco/opencode/blob/v2.2.7/packages/cli/src/commands/handlers/debug/config.ts)
  returns entries through a server; [connection selection](https://github.com/anomalyco/opencode/blob/v2.2.7/packages/cli/src/services/server-connection.ts)
  explains why private `--standalone` is required. Its
  [redaction](https://github.com/anomalyco/opencode/blob/v2.2.7/packages/cli/src/commands/handlers/debug/redact.ts)
  can mask secret-bearing URLs, which must not become an implicit default route.
- [V1 debug config](https://github.com/anomalyco/opencode/blob/v1.18.35/packages/opencode/src/cli/cmd/debug/config.ts)
  returns a resolved object. V1 loader initialization can write schema/dependency
  files, so “debug” alone is not a guarantee of side-effect-free inspection.

The broad statement “custom directory replaces global config” is therefore
correct for the installed V2 binary, not for the examined supported V1 loader.
Do not repair one dialect by forcing its order onto the other.

## Reconstructed config diagnostics

All six actual V2 commands exited 0 and used `debug config --standalone`, with
the same generated inline controls as an Explorer worker, a temporary Git cwd,
credential-free HOME and all four XDG roots, disabled update/model fetching and
no plugins. Synthetic `.invalid` endpoints were never contacted for inference.
All probes currently return supervisor `ok=true` / `go_subscription`.

| Saved probe | Configuration and normalized observation | Interpretation |
|---|---|---|
| R1 (`global-retained-with-custom-dir`, historical probe label) | Ordinary global endpoint + empty custom directory; V2 loads only the custom root and generated inline, not the ordinary global file. | Negative control: global replacement is correct for V2. V1 retention is source-validated only. |
| R2 | Ordinary global `baseURL:null`, explicit file custom endpoint; normalized entries put global before explicit. Supervisor folds them in reverse and loses the endpoint. Editing the explicit endpoint does not change its pin. | Reproduced unsafe approval. |
| R3 | Custom global root endpoint + project `baseURL:null`; normalized entries put custom-root global before project. | Precedence control, not counted as another unsafe reproduction. |
| R4 | V1 legacy `provider.opencode-go.options.baseURL` in global config under V2. Normalized output contains `providers.opencode-go.settings.baseURL`; supervisor sees no provider override. | Reproduced unsafe approval / legacy normalization gap. |
| R5 | Custom global root `baseURL:null` plus explicit endpoint. Binary puts the custom global root before explicit; supervisor reverses them. Endpoint edit leaves pin unchanged. | Reproduced unsafe approval including custom-dir + explicit. |
| R6 | Benign legacy Go provider with no custom endpoint. Normalized V2 provider retains benign legacy material. | Legacy compatibility control that must remain valid. |

The user-supplied report lists three original audit probes but contains no
literal scripts, commands or complete fixtures. These are **Architect
reconstructions**, not claims to have rerun those exact original scripts.
Preserve that distinction in implementation and closure reports. Exact original
probe parity remains an evidence item for the independent closure auditor.

## Reproducible evidence and commands actually executed

Files under `evidence/aor31/` are sanitized diagnostic artifacts, not production
tests or fixes. Scripts accept the checkout path, so rerun them against the
future implementation and inspect outcomes; a zero script exit alone is not
remediation success. The route log contains only temporary synthetic config.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 docs/agent-handoffs/orchestrator-v3-1/evidence/aor31/route_probe.py "$PWD" /home/abdullah/.opencode/bin/opencode
PYTHONDONTWRITEBYTECODE=1 python3 docs/agent-handoffs/orchestrator-v3-1/evidence/aor31/boundary_probe.py "$PWD"
PYTHONDONTWRITEBYTECODE=1 python3 docs/agent-handoffs/orchestrator-v3-1/evidence/aor31/deadline_probe.py "$PWD"
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts/tests -p 'test_v31_stage_deadline.py' -v
```

Executed from the candidate checkout (the initial diagnostics lived in
`/tmp/ao-aor31-architect/`, then copied here). Outcomes:

- `route-probes.jsonl`: six binary normalizations, all CLI exit 0; three unsafe
  supervisor classifications as above, two unchanged pins after endpoint edits.
- `boundary-probes.jsonl`: ignored mutation accepted; process contention rejected
  despite capacity. These are reproduced defects, not passing safety tests.
- `deadline-expired.json`: safe exhausted-budget alternative, no model launch.
- `deadline-python310.log`: **4 tests, 0 skipped, OK**, 7.942 seconds, exit 0.

Not executed in this investigation: complete offline suite, Python 3.12/3.13,
real V1 binary, authenticated providers, live billing or unattended operation.
Those are not implied by the diagnostic results. Final acceptance requires the
verification matrix in [the approved handoff](aor31-remediation-batch-01.md).

## Proposed architecture and gate

One bounded implementation batch: shared version-aware routing observation and
launch identity; content-only runtime projection; independent ledger wait with
deadlines/cancellation; deadline invariant assertions. Preserve existing stage
ownership, contract v2, schema 3 and conservative crash accounting. New route
identity must not grandfather a changed endpoint through an old label-only grant.

Current implementation commits: **none**. All findings remain open. The user
explicitly approved the single-batch design in the Architect conversation on
2026-11-14. The next step is a separate original Implementer session. Architect
acceptance follows actual diff and evidence review.
