# AOR120-A1 — same-session Reviewer Read and permission evidence (operator launch)

Prepared 20 November 2026 from code/test revision
`fb88c50bf0c09ff1a8814d2a56336aebe4ff3ba2`. Preparation and the read-only
preflight made **no model call**. The single authenticated Reviewer dispatch is
the operator action below; nothing in this file claims its result in advance.

This fixture supersedes the `f59a2cd` fixture for the same-session permission
question. The earlier run remains valid Read evidence and remains recorded as
unverified for shell/edit; it is not promoted.

## What is new

- OpenCode v2.2.7 genuinely has no tool-inventory surface. `opencode debug
  agents` returns `description`, `hidden`, `id`, `mode`, `name`, `permissions`,
  `request`, and `system` — no tool list. The HTTP agent operations return the
  same normalized `Agent.Info`. Trace logging and the JSONL event stream do not
  carry the request's tool definitions. The provider-bound request does, but
  capturing it would require the Go credential or TLS interception; neither is
  acceptable here.
- The runtime does return an exact, per-session response when a model emits a
  call to a tool that is not in that request's inventory:
  `No tool named "<tool>" is currently available. Please use a tool from the
  available tool list.`
- `scripts/reviewer_smoke.py` now classifies that response as **absent** only
  when the event tool, the tool named by the runtime, the exact prepared probe
  input, and the producing session all match. Any other error stays
  `generic_error`/`unverified`. Mixed denials and absences stay unverified. The
  negative is still optional and is re-derived from the digest-verified raw
  stream on `inspect`.
- The prompt now requires the model to emit both calls even though the tools are
  absent from its list, and to copy the exact runtime message into `evidence`.
  It still never reveals the challenge line.

The isolated credential-free loopback beside this file shows all four calls:
Read completed, and the shell/edit calls rejected as unavailable, with the
classifier proving both negatives and creating no file. That is a profile/runtime
demonstration, not authenticated-session evidence.

## Prepared root

- Root: `/tmp/opencode/abdullah-reviewer-smoke-fb88c50`
- Run: `20261120T151504-dc79fb44`
- Isolated config `<root>/config.json`; isolated state `<root>/state/runs`;
  isolated checkout registry `<root>/registry`.
- Disposable checkout `<root>/repo`: one commit, one attested supervisor writer
  delta, one real verification run, one digest-bound review projection.
- Authorized channel: `isolated_opencode_go_v2_subscription_readonly`.
- Installed runtime: OpenCode `v2.2.7`; dialect `v2`.

## Fixture identity

| Item | Value |
|---|---|
| Candidate signature | `a5f6f13027fcfb377c8cd11b5c3a77e8e072aca324e2098404cbc64d08cc69dd` |
| Verification record SHA-256 | `e97852fe030e1822de508707a35856bfaf074f260f4f8978041ffa132f9dbdf4` |
| Projection SHA-256 | `d25c727de2dda36f5ed0c0f855992b6cb5d9a6cfc02138e3c429082d0ab633ea` |
| Projection manifest SHA-256 | `b7771b306363ad2914f893a345c2ff35df1c84bca0691135b2e13282b7dfc2ef` |
| Packet binding SHA-256 | `ad892e3f5d5d14817b02ddfc97136f4a7c3ae46b6a1cf9786d640fdc40806bb1` |
| Challenge hunk SHA-256 | `f261986b836871e47f9d4bc656da817853559a331d262d2a5af22b404e67641b` |
| Prompt SHA-256 | `4129e62ff0a876a5664b605d2b00a51426548ef4f326ea0ac493f7306758c6a9` |
| Route identity SHA-256 | `22ef6afaf5b041baece89c053f63bf129b668c29319a8e1c38ee46b10d398f34` |
| Reviewer profile SHA-256 | `797b224b2d61888f88c53fb50f9edec057471e94184cc8955bd93559aab524a5` |
| Execution-policy SHA-256 | `18cdc3b99b38a13ead5875cd1de1e045f9de75a931d758e9eb5a7eaab6b42685` |
| Prepared manifest SHA-256 | `f9f36e8c8b9eb4e01865a8f227afa080b7d3d3668457ab8716eaef7f759dcdeb` |

Preflight (`reviewer-smoke-preflight-fb88c50.json` beside this file) returned
`ok: true` with `route_bound`, `prompt_bound`, and `policy_compatible` all true:
policy `current`, installed-agent introspection `true`, read allowed,
shell/edit denied in the static profile, prepared bindings intact. The pinned and
effective route is `opencode-go/deepseek-v4.1-flash`, High, billing `go`.

## Exact commands

```bash
# Read-only readiness; no model call.
cd /home/abdullah/abdullah-orchestrator-v1.2.0 && python3 scripts/reviewer_smoke.py preflight --root /tmp/opencode/abdullah-reviewer-smoke-fb88c50

# Operator action: exactly one real Reviewer dispatch on the pinned Go route.
cd /home/abdullah/abdullah-orchestrator-v1.2.0 && python3 scripts/reviewer_smoke.py launch --root /tmp/opencode/abdullah-reviewer-smoke-fb88c50

# Recorded evidence; re-derives from the digest-verified raw stream.
cd /home/abdullah/abdullah-orchestrator-v1.2.0 && python3 scripts/reviewer_smoke.py inspect --root /tmp/opencode/abdullah-reviewer-smoke-fb88c50
```

## How to read the result

`launch` and `inspect` print `read_verified` and `negative_evidence_verified`
separately from the combined `ok`.

- `read_verified: true` requires a completed, path-matched Read from the
  producing session whose output carries the exact challenge line.
- `negative_evidence_verified: true` now requires, for each probe, an exact
  producing-session event whose classification is `denied` (policy refusal) or
  `absent` (the exact runtime unavailable-tool response) — or an authoritative
  inventory.
- If the model emits no shell/edit call, or emits an unclassified error, that
  probe stays `unverified` and the combined result stays false. This is the
  expected conditional outcome, not a harness failure to hide.

## Honest limits

- A successful negative attests only the exact called tool in that exact
  session. It is not a provider-wide enforcement proof.
- The authenticated model may decline to emit a call to a tool it cannot see.
  If it does, no same-session capability evidence exists without an inventory
  surface; retain the conditional verdict and record the limitation.
- One subscription model call is billable to the operator's Go account.
