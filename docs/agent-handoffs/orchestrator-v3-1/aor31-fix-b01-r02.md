# AOR31 — Batch 01 correction round 02

Status: **CHANGES REQUIRED — existing approved remediation scope.**
Checkout: `/home/abdullah/.local/src/abdullah-orchestrator-v3-1`
Branch: `design/orchestrator-v3-1`
Correction BASE: `161683d6f51249a99e5964dee9b8c927600fb3e4`.
Original BASE: `b9139946db5684e3e48724b9e1060af355362e82`.
Parent: [approved batch](aor31-remediation-batch-01.md).
Evidence/disposition: [round 02 review](aor31-review-r02.md),
`evidence/aor31-review-r02/`. Use a fresh original Implementer session.

## Outcome and architectural reassessment

Close only the three remaining boundaries below. The original six correction
cases now pass their focused tests; preserve the fixes for source ordering,
fresh V2 inspection, immutable inline, material-bound grants, nested symlinks,
grant contention and deadline assertions. Do not reopen those for optional polish.

The V1 adapter and independent inspector wrapper have needed repeated correction.
Do not add another speculative general normalizer or more permissive fallbacks.
Reduce the accepted V1 boundary to routing whose influence is actually accounted
for; refuse unsupported/unknown material. Reuse the existing version-policy and
process-ownership primitives instead of bypassing them with prepared state or a
second leader-only execution wrapper. This revises the implementation approach,
not the approved security/product contract. Escalate before coding if a broader
architecture change is required; do not waive the billing or ownership gates.

No automated orchestrator self-modification, live inference, install, push,
release, deploy, destructive Git, live saved-run mutation or manual-skill edits.
Use disposable fake/real-normalization fixtures only. Local cohesive correction
commits are authorized. Keep report v2 and schema 3, preserve existing dirty and
ignored user files and all Architect evidence.

## R02-F1 — P1: prepared launch bypasses actual CLI version/pin validation

Locations at BASE: `_opencode_dialect_for_observation:1516`,
`_opencode_launch_context:2365`, `cli_command:6268`, `call_model:7215`.

Reproduction in `review02.py`: configure exact pin `1.18.35`, have the test-owned
binary report `2.2.7`, supply a V2-only custom Go endpoint, and use an intentionally
empty variant. The normal `opencode_dialect(version='2.2.7', cfg=...)` refuses
the mismatch, but `call_model` dispatches successfully, generates V1 controls,
does not observe the native V2 endpoint and omits `--standalone`. The fake
history records `run`. This is both billing/permission mismatch and a bypass of
the private-V2-server ownership invariant. No real inference was invoked.

Correction: validate the **actual resolved executable's** version against the
existing support ranges and configured pin before generating/authorizing the
prepared profile. A pin is a constraint, not evidence of the installed dialect.
Carry the validated executable/dialect through the prepared command. No actual
version mismatch/unsupported/failed version query may fall back to a pinned
dialect. Preserve existing configurable support/pin semantics and empty variants.
Coordinate version execution with F3's budget and containment handling.

Tests: real dispatch-boundary fakes for pinned V1/binary V2, pinned V2/binary V1,
unsupported actual version, unreadable/failed version, and matching controls.
Assert zero inference spawn/accounting/grant use on refusal, full matching
permission dialect, and mandatory `--standalone` whenever the real binary is V2.
Include a native endpoint that the wrong dialect would otherwise overlook.

## R02-F2 — P1: V1 fallback still certifies unmodeled routing and sources

Locations: `_opencode_config_sources:1428`, `_opencode_external_routing_hazards:2182`,
V1 eligibility in `_opencode_prepared_context:2219`,
`_opencode_effective_endpoint:2478` / `_opencode_go_qualification:2487`.

Reproduced supervisor outcomes at BASE:

| Input | Unsafe result |
|---|---|
| V1 `provider.opencode-go.api` custom URL with selected model | Go subscription, endpoint absent, qualified=true |
| V1 selected `models.model.provider.api` custom URL | Same |
| V1 provider `npm: '@ai-sdk/anthropic'` package remap | Same |
| `OPENCODE_CONFIG=relative.json`; benign file in supervisor cwd, custom endpoint in child project cwd | Reads the supervisor's file and approves Go |
| Synthetic SQLite account DB selected by `OPENCODE_DB`, active account/org rows | adapter_complete=true, no hazards; DB unobserved; approves Go |
| Auto-discovered `.opencode/plugins/local.ts`, no top-level plugin setting | adapter_complete=true, plugin_config_present=false; approves Go |

The native V1 URL/npm fields, relative-path dispatch context, database-backed
account configuration and auto-discovered plugin files are supported upstream
influences. Only local fakes/metadata were used; no plugin or account endpoint
was executed. Source links and exact scripts are in the review. The report's
claim that account/plugin hazards are gated is broader than the actual checks.

Correction:

- Account for V1 native provider/model URL, SDK/package and API-model-id remaps,
  and supported cross-dialect lowering where accepted by V1. A remap cannot be
  Go consent. Prefer explicit unprovable refusal to ignoring a routing form not
  implemented by the bounded adapter. Preserve clean legacy Go controls.
- Resolve relative explicit/custom-directory paths in the child's cwd, not the
  supervisor's cwd. Discover, read, hash and launch against that same resolution.
- Establish the actual V1 account/plugin boundary before claiming completeness.
  Inspect relevant database *metadata read-only* (including supported DB-path
  selection) or fail closed if it cannot be established. No credentials in logs,
  no account refresh/fetch, no database migration or real store mutation.
  A hazard helper's docstring is not evidence of source coverage.
- Discover applicable automatic plugin sources as well as declared plugin lists;
  unknown code that may alter routing must refuse before it executes. Do not run
  plugins to prove their safety. Bind source presence/absence and identities.
  Apply the same rule anywhere V2 pre-inspection eligibility relies on that scan.

Tests: all six cases above, clean controls, absent/unreadable/malformed account
metadata, explicit DB selection, automatic plugin directories, relative paths
with different supervisor/child cwd, and provider/model native remap forms.
Use pinned source-backed fixtures for V1; do not claim real V1 compatibility
without its binary. Do not turn arbitrary active account/plugin routes into
accepted known limitations. Stay within the existing fail-closed contract.

## R02-F3 — P2: inspector leader exit and version work escape ownership/budget

Locations: `_opencode_binary_version_cached:1968`,
`_opencode_run_bounded:2014`, and version auto-detection callers.

Two reproduced cases in `review02.py`:

1. An inspector parent starts a child with all stdio closed, prints valid `[]`
   and exits 0. The helper returns success while the child remains alive in the
   parent's original process group. `finally` skips cleanup because `poll()`
   sees an exited leader. The diagnostic kills only its own child afterward.
   The passing descendant regression only covers a still-running parent.
2. A cold `--version` probe sleeping 0.6 s is entered with an 0.08 s stage budget.
   `call_model` takes ~0.678 s and returns generic unprovable/preflight failure,
   not a deadline outcome. Its cached `subprocess.run(timeout=10)` and the auto
   version path do not receive stage deadline/cancellation context.

Correction: use whole-execution ownership/containment for inspection, including
successful leader exit, timeout, cancellation and errors. Check descendants
independently of leader liveness. Clean up every owned process or retain exact
unproven ownership and block further work; never report success or discard the
identity because the leader exited. Do not create a phantom inference job or
count inspection as a model call. Existing guard/identity machinery should be
preferred to another incomplete process wrapper.

Thread monotonic deadline and owning-run cancellation through cold version
queries, including auto-dialect detection, and configuration inspection. Cached
version metadata may be reused for an unchanged executable, but uncached work
must fit the remaining budget and clean up its process tree. Deadline/cancel
must remain distinct outcomes, not generic fallback authorization. Keep the
final pre-spawn check/refund behavior and nonblocking supervisor lock intact.

Tests: parent-exits-first with closed-stdio child; inherited and escaped/session
descendants using existing ownership mechanisms; leader success, error and
cancel; denied termination with retained ownership; cold version query under
deadline/cancel for auto and pinned modes; no next inference child/accounting.
Use recorded PIDs and deterministic readiness, and clean up test-owned processes.

## Verification and delivery

Add targeted regressions red at `161683d` in a disposable copy. Run focused
correction/routing/ownership/grant suites and saved source/route/boundary probes.
Once these gates pass, complete the parent brief's full offline Python
3.10/3.12/3.13 and credential-free supported V2 verification; preserve exact
commands, versions, logs, counts, skips and commit identities. Do not fabricate
the absent literal independent-auditor probes or real V1 results.

Update maintained docs only as necessary to describe the corrected supported
boundary and truthful lifecycle guarantees. No unrelated documentation churn.
Return a copyable report with original/correction BASEs, exact commits/HEAD,
three-finding closure matrix, red/green evidence, log paths, unexecuted checks
and remaining limitations. State architectural deviations before proceeding.
Architect acceptance remains withheld until actual changes and evidence pass.
