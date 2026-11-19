# AOR120-A1 — authenticated Reviewer Read smoke (operator launch)

Prepared 19 November 2026 from correction-1 code/test revision
`ebd55c888aa886c098213e9acc1a2f0e6e01db5b`. Preparation and the read-only
preflight made **no model call**. The single real Reviewer dispatch is the
operator action below; nothing in this file claims its result in advance.

The earlier fixture `/tmp/opencode/abdullah-reviewer-smoke-c04f640` (run
`20261119T153949-a80cff8d`) is **superseded**: its prompt omitted
`contract_version`, its predicate accepted an answer without a proving Read
event, and its delta was not published through the attested writer path. Do not
launch it.

## Prepared root

- Root: `/tmp/opencode/abdullah-reviewer-smoke-ebd55c8`
- Run: `20261119T182217-87d9122d`
- Isolated config: `<root>/config.json`; isolated state `<root>/state/runs`;
  isolated checkout registry `<root>/registry`. Real stored OpenCode Go
  subscription access is used; no API-billed alternate credential is selected.
- Disposable checkout: `<root>/repo` (one commit, one real supervisor writer
  window published through `_record_batch_delta`, one real verification run,
  one digest-bound review projection).

## Candidate and packet identity

| Item | Value |
|---|---|
| Candidate signature | `8e33c3a4819b677ebb1783057064282e431c94893d9b98c3dece3e6900f13401` |
| Verification record SHA-256 | `cdaf4483362e982362cc5992074698bc77ae9783cc0a700c444c1ce2c796f1f8` |
| Projection SHA-256 | `52376d44b8a01819bd7c91b32584abd4d018d9767345a97fa9e36252507719df` |
| Packet binding SHA-256 | `ebbc9b81147537d479f7007d167519c47fca8aa6623aa5fa70879ae32d5ceafd` |
| Manifest SHA-256 | `93e0b1bf7ade2c550d936037f6a90423564a8e21825df61875ac55c88cde70dc` |
| Challenge hunk SHA-256 | `4f96fcbf1ee6a1801ce23d1d311e8dca6f687a5ef7040dd1bfe1fcdf8ad5b0b2` |
| Prompt SHA-256 | `574af5cc9f64ea5cebb0b015505305b7c3231d9e0832657e34a015f16b2b8ed8` |
| Smoke manifest file SHA-256 | `332ecf31fa00ab38b728cb6bc9e69aae35193ca9e5da9a04fa2c0af645dd931a` |

The hunk contains one added `MAGIC_SENTINEL` assignment with a per-run random
integer (recorded in the manifest). The prompt names the hunk path but contains
neither the line, the value, nor the constant name. The value also exists in
fixture source, which is why a bare answer is not evidence.

## Route and readiness

Preflight (read-only, `reviewer-smoke-preflight-r01.json` beside this file)
returned `ok: true`, classification `go_subscription`, dialect `v2`,
installed-agent introspection `true` on OpenCode `v2.2.7`, with normalized
permissions `read: allow`, `shell: deny`, `edit: deny`. Pinned Reviewer route:
`opencode-go/deepseek-v4.1-flash`, effort `high`, billing `go`,
`route_source: pinned`. The prompt declares `contract_version: 2`. Prepared
bindings verified intact at preflight. Entitlement is attested by configuration
only; no inference request was made.

## Exact commands

```bash
# Read-only readiness; no model call.
cd /home/abdullah/abdullah-orchestrator-v1.2.0 && python3 scripts/reviewer_smoke.py preflight --root /tmp/opencode/abdullah-reviewer-smoke-ebd55c8

# Operator action: exactly one real Reviewer dispatch on the pinned Go route.
cd /home/abdullah/abdullah-orchestrator-v1.2.0 && python3 scripts/reviewer_smoke.py launch --root /tmp/opencode/abdullah-reviewer-smoke-ebd55c8

# Recorded evidence and the shared launch/inspect predicate.
cd /home/abdullah/abdullah-orchestrator-v1.2.0 && python3 scripts/reviewer_smoke.py inspect --root /tmp/opencode/abdullah-reviewer-smoke-ebd55c8
```

## What launch requires and records

Launch first revalidates the prepared candidate, hunk, verification, projection
manifest, packet binding and projection files. It then dispatches one Reviewer
with the shipped read-only profile. Success requires all of:

- a completed contract-v2 Reviewer report accepted by the supervisor's real
  OpenCode report ingestion (`extract_cli_report` + normalize/validate);
- a completed, path-matched Read from the producing session whose output
  contains the exact challenge line;
- an unchanged candidate and intact prepared source/hunk/packet/route bindings;
- no executed prohibited tool, with the harmless shell and edit probes `absent`
  or `denied`;
- a valid shipped Reviewer profile and matching installed-agent introspection.

`<root>/evidence.json` records the route/billing, preflight observation,
job/session/exit, report and ingestion diagnostics, redacted Read events
(path, status, producing session, output digest, challenge line/digest), the
negative capability outcomes, normalized rules separately from runtime
outcomes, and before/after signatures plus hunk/manifest/projection/binding/
verification hashes. `launch` and `inspect` use the same predicate; both exit
non-zero on any missing, failed, unrelated or wrong-session Read, blocked
report, drift, or executed write/shell attempt.

## Honest limits

- Static normalized-rule evaluation proves the shipped profile denies
  shell/edit and allows read; the negative probe outcomes are the runtime
  evidence for this specific dispatch. They do not certify provider-side
  permission enforcement beyond the observed session.
- A failed Read is not retried automatically. Record the failure, resolve the
  verified mismatch, and repeat the focused checks and this authorized smoke.
- One subscription model call is billable to the operator's Go account; nothing
  here proves entitlement or billing beyond that configured route.
