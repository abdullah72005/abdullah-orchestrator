# AOR120-A1 — authenticated Reviewer Read smoke (operator launch)

The launch instructions below are historical. That run reproduced the inherited
`PWD` failure. The corrected authenticated run and the remaining
same-session permission limit are recorded in the
[checkout-binding release evidence](README.md#opencode-checkout-binding-and-authenticated-reviewer-evidence).

Prepared 19 November 2026 from correction-2 code/test revision
`b72a772ec7446d63f9d616daf9aecbd0a3788baf`. Preparation and the read-only
preflight made **no model call**. The single real Reviewer dispatch is the
operator action below; nothing in this file claims its result in advance.

The earlier fixtures `/tmp/opencode/abdullah-reviewer-smoke-c04f640` and
`/tmp/opencode/abdullah-reviewer-smoke-ebd55c8` are **superseded**. They predate
the corrected negative-capability classification and route/prompt binding. Do
not launch them.

## Prepared root

- Root: `/tmp/opencode/abdullah-reviewer-smoke-b72a772`
- Run: `20261119T193923-901988fd`
- Isolated config: `<root>/config.json`; isolated state `<root>/state/runs`;
  isolated checkout registry `<root>/registry`. Real stored OpenCode Go
  subscription access is used; no API-billed alternate credential is selected.
- Disposable checkout: `<root>/repo` (one commit, one real supervisor writer
  window published through `_record_batch_delta`, one real verification run,
  one digest-bound review projection).
- Authorized channel: `isolated_opencode_go_v2_subscription_readonly`.

## Candidate and packet identity

| Item | Value |
|---|---|
| Candidate signature | `e5a7da4d7113b0089bd98e9b69eacff0e6b0beaea3b649854f8662c42f19644e` |
| Verification record SHA-256 | `e1178f5945d601636534959bade40f8bafb01f0c6534617c3b5d77898b3eab88` |
| Projection SHA-256 | `96fb2b42a01d58fc1bd889dbf7354e93fda53278a32097a704ebc9fe6add53dd` |
| Packet binding SHA-256 | `83cbe1056b40e629a92dc3db998ac1035ded8f598eed230c4b3fc491a4da4dce` |
| Projection manifest SHA-256 | `aef3c78778142fcbb78002707962b921c298dd329a7347974132bba19852867d` |
| Challenge hunk SHA-256 | `570b9d938d0b70070bf544f983d5266481f3a646255a7497863bd13399f12f04` |
| Prompt SHA-256 | `1e42f94e62dcd8ef4e434f41d559f550f16fbdea735d48b78e3123fa441e51cf` |
| Route identity SHA-256 | `ea05a70f9d50ff7df8a3df70335e6c8ebb1da1bb2603d4262574c568fa0a177c` |
| Reviewer profile SHA-256 | `797b224b2d61888f88c53fb50f9edec057471e94184cc8955bd93559aab524a5` |
| Execution-policy SHA-256 | `18cdc3b99b38a13ead5875cd1de1e045f9de75a931d758e9eb5a7eaab6b42685` |
| Smoke manifest file SHA-256 | `4a0e337124ae4cbd24b147fdab585ada856f3a9b3c24ed5f8ffcb313e146787c` |

The hunk contains one added `MAGIC_SENTINEL` assignment with a per-run random
integer (recorded only in the manifest). The prompt names the hunk path but
contains neither the line, the value, nor the constant name. The value also
exists in fixture source, which is why a bare answer is not evidence.

## Route and readiness

Preflight (`reviewer-smoke-preflight-r02.json` beside this file) returned
`ok: true` with `route_bound`, `prompt_bound` and `policy_compatible` all true:
policy `current`, dialect `v2`, installed-agent introspection `true` on OpenCode
`v2.2.7`, classification `go_subscription`, read allowed, shell/edit denied in
the static profile. Pinned/effective Reviewer route:
`opencode-go/deepseek-v4.1-flash`, High variant, billing `go`. Prepared
bindings verified intact. Entitlement is attested by configuration only; no
inference request was made.

## Exact commands

```bash
# Read-only readiness; no model call.
cd /home/abdullah/abdullah-orchestrator-v1.2.0 && python3 scripts/reviewer_smoke.py preflight --root /tmp/opencode/abdullah-reviewer-smoke-b72a772

# Operator action: exactly one real Reviewer dispatch on the pinned Go route.
cd /home/abdullah/abdullah-orchestrator-v1.2.0 && python3 scripts/reviewer_smoke.py launch --root /tmp/opencode/abdullah-reviewer-smoke-b72a772

# Recorded evidence; re-derives from the digest-verified raw stream.
cd /home/abdullah/abdullah-orchestrator-v1.2.0 && python3 scripts/reviewer_smoke.py inspect --root /tmp/opencode/abdullah-reviewer-smoke-b72a772
```

## What launch requires and records

Before inference, launch rechecks the prepared prompt digest and contract-v2
shape, the exact pinned/effective OpenCode Go V2 subscription route, no
fallback consent, the current execution-policy identity, the shipped and
installed Reviewer profile, route preflight, and every prepared source/hunk/
packet/verification digest. Any drift refuses the launch.

Success requires all of:

- a completed contract-v2 Reviewer report accepted by the supervisor's real
  OpenCode report ingestion;
- a completed Read whose path resolves against the prepared repository to the
  **exact** hunk (a foreign absolute path ending in the same suffix is
  rejected), from the producing session, whose output carries the exact
  challenge line;
- the completed job's dispatched route matching the prepared route;
- an unchanged candidate and intact bindings;
- both harmless probes proven: an exact shell command and exact edit path each
  explicitly denied in the producing session, or an authoritative runtime
  inventory proving the capability absent.

An unobserved probe, a generic failure, an unrelated command, or an attempt in
another session is **unverified**, not denied. This OpenCode binary exposes
normalized agents/permissions but no authoritative tool inventory, so a missing
event stays unverified. Static profile introspection is reported separately and
is not presented as runtime enforcement.

`<root>/evidence.json` records the route/prompt/policy readiness, dispatched
job route, report ingestion, redacted exact probe attempts and their
classification, Read events (path, status, producing session, output digest,
challenge line), the raw stream digest, and before/after signatures plus
hunk/manifest/projection/binding/verification hashes. `inspect` re-derives Read
and negative evidence from the digest-verified raw stream and fails if that
stream is missing or changed.

## Output reading

`launch` / `inspect` print `read_verified` and `negative_evidence_verified`
separately from the combined `ok`. Authenticated Read success can therefore be
attested while the negative capability result remains unverified; the combined
result is not promoted in that case.

## Honest limits

- Runtime denial is proven only for the exact observed probe in the producing
  session; it does not certify provider-side enforcement beyond that session.
- A failed Read is not retried automatically. Record the failure, resolve the
  verified mismatch, and repeat the focused checks and this authorized smoke.
- One subscription model call is billable to the operator's Go account.
