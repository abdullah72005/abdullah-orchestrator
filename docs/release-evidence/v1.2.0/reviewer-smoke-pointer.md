# AOR120-A1 — authenticated Reviewer Read smoke (operator launch)

Prepared 19 November 2026 from candidate revision
`b0d88f32d2182c2d35c72ab9cf69af66117257f6`. Preparation made **no model call**.
The single real Reviewer dispatch is the operator action below; nothing in this
file claims its result in advance.

## Prepared root

- Root: `/tmp/opencode/abdullah-reviewer-smoke-b0d88f3`
- Run: `20261119T151052-af70fb81`
- Isolated config: `<root>/config.json`; isolated state `<root>/state/runs`;
  isolated checkout registry `<root>/registry`. Real stored OpenCode Go
  subscription access is used; no API-billed alternate credential is selected.
- Disposable checkout: `<root>/repo` (one commit, one real supervisor writer
  window, one real verification run, one digest-bound review projection).

## Candidate and packet identity

| Item | Value |
|---|---|
| Candidate signature | `31d8c5136feed071bbb9d97d1d6a57ff846adab4dd5279805cf7b60d2cf37b04` |
| Verification record SHA-256 | `259f4294a4f80f6939f644d14d013e6c2aa212ae6b3327e436f4feb3be613ab5` |
| Projection SHA-256 | `ef720f402e16c00d2bebdaa6ef63c3a914caeb79ed4552731091c12d554b194f` |
| Packet binding SHA-256 | `41f9d989f570f8c81c68c6c5933ecbb07e5ab11c3b01c76d249b449ca588f305` |
| Manifest SHA-256 | `7c1a9dd38486b51dd3c1b6190dbbe4b6f5c19c2e13d3fc180958ecf6b838064c` |
| Challenge hunk SHA-256 | `e270bca742e32cc54b41d3a96c2aafe806673e8b0e9ec2ff6b495f91528099d5` |
| Prompt SHA-256 | `ebe6f85b33f9a332b637c4f253ae0d64f6876c3a1e3274dfc3f154939114139f` |

The hunk contains the added `MAGIC_SENTINEL = 314159`. The prompt names the
hunk path but deliberately contains neither the line nor the value.

## Route and readiness

Preflight (read-only, `/tmp/opencode/smoke-preflight.json`, copied beside this
file) returned `ok: true`, classification `go_subscription`, dialect `v2`,
installed-agent introspection `true` on OpenCode `v2.2.7`, with normalized
permissions `read: allow`, `shell: deny`, `edit: deny`. Codex is `0.169.1`.
Entitlement is attested by configuration only; no inference request was made.

Pinned Reviewer route: `opencode-go/deepseek-v4.1-flash`, effort `high`,
billing `go`, `route_source: pinned`.

## Exact terminal launch pointer

```bash
cd /home/abdullah/abdullah-orchestrator-v1.2.0 && python3 scripts/reviewer_smoke.py launch --root /tmp/opencode/abdullah-reviewer-smoke-b0d88f3
```

Then inspect the recorded evidence:

```bash
cd /home/abdullah/abdullah-orchestrator-v1.2.0 && python3 scripts/reviewer_smoke.py inspect --root /tmp/opencode/abdullah-reviewer-smoke-b0d88f3
```

## What the launch records

`<root>/evidence.json` contains: the exact route and billing, preflight
observation, job/session/exit, the model's report, whether the sentinel answer
was found, bounded Read-tool event digests, normalized effective permission
evaluation, installed-agent introspection, and before/after checkout signatures
plus hunk/manifest/projection/binding/verification hashes. `launch` exits
non-zero when the answer is missing, the Read tool produced no event, or the
checkout changed.

## Honest limits

- Static normalized-rule evaluation proves the shipped profile denies
  shell/edit and allows read; it does not by itself prove the model runtime
  enforced those rules. The unchanged-checkout check is the runtime evidence
  for no write.
- A failed Read tool is not retried automatically. Record the failure, fix the
  verified mismatch, and repeat the focused checks and this authorized smoke.
