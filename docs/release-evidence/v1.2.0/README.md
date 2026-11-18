# v1.2.0 release evidence

Prepared 18 November 2026 for the local v1.2.0 release candidate.

- Candidate base: `7c050ee75d90efb22b96c5c7fafa35e7f04712f7`
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

## Results

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
