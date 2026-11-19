# AOR120-A1 — authenticated Reviewer Read smoke (operator launch)

Prepared 19 November 2026 from the final candidate code/test revision
`c04f6405f48c5c6422a13662646bdb1f3bca2a08`. Preparation made **no model call**.
The single real Reviewer dispatch is the operator action below; nothing in this
file claims its result in advance.

## Prepared root

- Root: `/tmp/opencode/abdullah-reviewer-smoke-c04f640`
- Run: `20261119T153949-a80cff8d`
- Isolated config: `<root>/config.json`; isolated state `<root>/state/runs`;
  isolated checkout registry `<root>/registry`. Real stored OpenCode Go
  subscription access is used; no API-billed alternate credential is selected.
- Disposable checkout: `<root>/repo` (one commit, one real supervisor writer
  window, one real verification run, one digest-bound review projection).

## Candidate and packet identity

| Item | Value |
|---|---|
| Candidate signature | `64503e9a5bebe0f3ebcf6f649ec8fd24dcdb15cc8941f23995d6344958a46611` |
| Verification record SHA-256 | `40ed49c36ecee5a1fdaac460227557153efbf526901ab3df89f0361ac90d48d3` |
| Projection SHA-256 | `139e42750ab7afe11cce1307fb30b2c443d7ee3d52109b85e6bfa2aa5d34b9f9` |
| Packet binding SHA-256 | `bb272161620efa1c935fc3a1953deafe43bff83001ff14093762a7ba6a933acb` |
| Manifest SHA-256 | `2fca1e879bfa52c66a89f97e6f7d184793e078967cbe96eaf70f7a56461b0b78` |
| Challenge hunk SHA-256 | `e270bca742e32cc54b41d3a96c2aafe806673e8b0e9ec2ff6b495f91528099d5` |
| Prompt SHA-256 | `4557f4c5c367833b63c448dac318f91e277f8817277a01f1d6772dec049dff12` |

The hunk contains the added `MAGIC_SENTINEL = 314159`. The prompt names the
hunk path but deliberately contains neither the line nor the value.

## Route and readiness

Preflight (read-only, `reviewer-smoke-preflight.json` beside this file) returned
`ok: true`, classification `go_subscription`, dialect `v2`, installed-agent
introspection `true` on OpenCode `v2.2.7`, with normalized permissions
`read: allow`, `shell: deny`, `edit: deny`. Codex is `0.169.1`. Entitlement is
attested by configuration only; no inference request was made.

Pinned Reviewer route: `opencode-go/deepseek-v4.1-flash`, effort `high`,
billing `go`, `route_source: pinned`.

## Exact terminal launch pointer

```bash
cd /home/abdullah/abdullah-orchestrator-v1.2.0 && python3 scripts/reviewer_smoke.py launch --root /tmp/opencode/abdullah-reviewer-smoke-c04f640
```

Then inspect the recorded evidence:

```bash
cd /home/abdullah/abdullah-orchestrator-v1.2.0 && python3 scripts/reviewer_smoke.py inspect --root /tmp/opencode/abdullah-reviewer-smoke-c04f640
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
