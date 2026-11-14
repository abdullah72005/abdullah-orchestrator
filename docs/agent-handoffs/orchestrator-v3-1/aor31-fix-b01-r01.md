# AOR31 — Batch 01 correction round 01

Status: **CHANGES REQUIRED — scoped corrections authorized by the existing
manual Architect/Implementer workflow.** No new design approval is needed.
Checkout: `/home/abdullah/.local/src/abdullah-orchestrator-v3-1`
Branch: `design/orchestrator-v3-1`
Correction base: `7987d2672ceedad7e7785e02914f11f18502849c`.
Original review base: `b9139946db5684e3e48724b9e1060af355362e82`.
Parent contract: [approved batch](aor31-remediation-batch-01.md).
Review/evidence: [round 01 review](aor31-review-r01.md) and
`evidence/aor31-review-r01/`. Use a fresh original Implementer session.

## Outcome and constraints

Close the six concrete gaps below. Preserve passing grant contention, deadline,
ownership, report-v2 and schema-3 behavior. No unrelated refactor or rewrite,
automated orchestrator self-modification, live inference, installation, push,
release, destructive Git operation or mutation of real saved runs/manual skills.
Local cohesive correction commits are authorized. Existing Architect artifacts
remain review inputs; do not overwrite them or their baseline evidence.

## R01-F1 — P1: fallback still approves incorrectly modeled routing

Locations: `_opencode_config_sources` (1425),
`_opencode_normalize_v2_document` (1732), `_opencode_prepared_context` (2026),
`route_preflight` source-adapter warning.

Confirmed cases at the correction base:

1. V1 `HOME/.opencode/opencode.json` supplies a Go custom endpoint, but is never
   discovered; preflight approves `go_subscription` with no effective files.
2. V1 ordinary `config.json` has `baseURL:null` and `opencode.json` has a custom
   endpoint. The adapter loads legacy `config.json` last, unlike the supported
   upstream loader, and approves Go with no endpoint.
3. V2 document has legacy Go custom endpoint plus native **different** provider.
   With inspection unavailable, adapter drops the legacy provider and approves
   Go. Real V2.2.7 retains both providers. The current same-provider coexistence
   test does not cover this disjoint-provider case.

Correction: repair source order/discovery/normalization against pinned upstream
behavior, including child-cwd resolution of relative paths and relevant home
directories. Do not copy one dialect's project walk onto the other. Audit the
bounded adapter against the supported source contracts and add concrete parity
fixtures for these cases. Preserve native precedence on a conflicting provider
id while retaining non-conflicting legacy ids as the actual normalizer does.

An inspector failure, malformed output or plugin skip must not be a generic
authorization fallback. Permit the source adapter only when its complete
influential source boundary can be established for that case. Unknown remote,
account/integration, managed or plugin routing is `unprovable_routing`, not a
warning plus Go approval. A human API grant does not prove unresolved material.
Do not execute arbitrary startup plugins as a workaround. Preserve a demonstrably
clean legacy Go path; do not make fakes or a failed inspector a production bypass.

Tests: reproduce all three cases above, failed/malformed/plugin-skipped inspection
with unobserved routing, and safe legacy controls. Capture real credential-free
V2 disjoint-provider normalization as fixture/parity evidence. Real V1 execution
remains a skip unless a supported binary is already available.

## R01-F2 — P1: cached normalization misses live influential sources

Locations: `_opencode_project_chain` (1406),
`_opencode_inspected_documents` cache lookup (1954–1970),
`opencode_provider_observation` material construction (2375 onward).

Real installed V2.2.7 reproduction: a parent `opencode.json` **above the Git
root** is normalized by the binary but absent from adapter records. After its
endpoint changes, a second observation returns cached old endpoint, identical
pin, and `_route_identity_recheck` returns None. A fresh binary invocation sees
the changed endpoint. An API grant bound to the first endpoint therefore cannot
rely on this recheck.

Correction: match V2's actual discovery boundary and prevent cached output from
standing in for a fresh source observation. Revalidate the complete discovered
source closure, entry identities, expansion inputs and relevant environment;
virtual/remote sources need authoritative freshness or refusal. Removing this
unsafe cache is preferable to guessing dependencies. A cached digest must never
be returned unchanged merely because the adapter did not know its source.

Bind content/source/executable identity even when no selected-provider entry is
present; currently `routing_material_sha256` is built only inside that branch.
Inspector-discovered source additions/removals, absence and normalized default
routes must participate in identity. Missing source coverage cannot become Go.

Tests: actual V2 parent-above-Git-root edit, source appearance/removal, inspector
entries outside adapter records, and material changes with no explicit selected
provider. Verify drift blocks before spawn and cannot retain an old grant.

## R01-F3 — P1: approved context is not the launched context

Locations: `call_model` recheck (6891), `source_snapshot` (6939),
`cli_command` (6960), `opencode_env` / prepared-context callers.

Fake-CLI reproduction: begin with a pinned unchanged Go route. Change ambient
`OPENCODE_CONFIG_CONTENT` during dispatch snapshot preparation, after the recheck.
`cli_command` regenerates environment afterward. The child runs with a custom
Go endpoint and **zero grants**. Its later report rejection does not undo launch.

Correction: carry the immutable prepared executable/cwd/routing-relevant env and
generated inline bytes through authorization and launch; do not regenerate them
from ambient globals after approval. Compare the actual prepared launch context
and material sources at the final launch boundary after preparatory work. Keep
raw environments private in memory, never in persisted preflight diagnostics.
Inspector must use the same full generated inline controls and routing bytes,
not the routing-only subset currently returned by `_opencode_inline_source`.
Account for authorized free-route controls consistently.

Tests: mutate ambient inline/endpoint/auth environment during preparation and
capture actual fake-child argv/env. It must either use the approved bytes or
reject before launch; it must never launch the changed ungranted route. Include
material source edits during preparation and preserve proper unlaunched refunds.
Do not claim atomic defense against arbitrary outside filesystem writes without
isolation; this finding concerns re-reading mutable in-process launch inputs.

## R01-F4 — P1: public authorization still creates label-only grants

Locations: `route_authorization_sha` (2483), `authorize_route_run` (11410),
`route_preflight` optional-pin branch.

Public-helper reproduction: current schema-3 saved worker route lacks a
`routing_fingerprint`; authorize two API calls through `authorize_route_run`,
change its endpoint, and preflight still says `ok=true`, `authorized=true`.
The new `grant_binding` marker does not bind material when the pin is absent.

Correction: require a valid resolved material binding for new OpenCode grants
and their consumption, including fallback and legacy/unpinned state paths.
Missing or stale pins must block with explicit safe new-run/migration guidance;
do not auto-repin or have a new marker grandfather unbound grants. A strong-host
route's different identity contract must remain intact. Keep usage immutable
and conservative across explicit migration/re-authorization.

Tests: the public-helper case above, absent/blank/stale material pins, fallback,
old grants, schema-3 legacy records and explicit migration; prove an endpoint
change cannot use prior authorization. Update test fixtures to use real valid
bindings rather than preserving an unbound production exception for convenience.

## R01-F5 — P2: nested runtime symlink content can escape write detection

Location: `_bounded_tree_digest` (3692), especially symlink handling (3712).

Reproduction: ignore `.cache/` and `runtime`; `runtime -> .cache/lib`, and
`.cache/lib/module.py -> ../shared.py`. Change ignored `.cache/shared.py` in a
fake planning child. Both manifests remain complete, projections equal, and one
completed plan is accepted. The linked-directory digest hashes only link text.

Correction: bind relevant nested symlink target content or mark the projection
unprovable and block. Use cycle-safe in-project rules, handle chains/dangling/
outside links, and apply file-count as well as byte budgets to linked traversal.
Do not bypass target content because it is reached through an ignored/skipped
directory. Do not revert files. Preserve unchanged dirty/ignored controls and
the explicit boundary-observation limitation.

Tests: this exact nested-link case, target-only edits/retargeting, cycles,
unreadable/outside cases and budget exhaustion at planning and cached/recovered
consumption. Acceptance/integration must share the corrected projection.

## R01-F6 — P2: inspection ignores cancellation and launches afterward

Locations: `_opencode_run_bounded` (1888) and `call_model` pre-spawn boundary.

Production-boundary fake test: request cancel while the inspector is running.
The helper blocks on `communicate`, then falls back and repeats inspection.
`_spawn_guarded` is called once **after cancel**; only the child-monitor loop
raises `InterruptedError`. Even a reduced 0.4-second inspector limit took ~2 s.
The helper has no cancellation context despite its “cancellable” docstring.

Correction: thread owning-run cancellation and the monotonic whole-stage deadline
through inspection and version/normalization work, poll promptly, clean up the
owned inspector tree, and forbid inference spawn after cancellation/expiry.
Recompute remaining budget immediately before spawn, after snapshots/preparation.
Never turn cancellation/expiry into a source-adapter authorization success.
Keep diagnostics separate from model-call accounting and preserve uncertain
ownership if inspector containment cannot be proven. No shared daemon.

Tests: cancel/pause and deadline during inspection and preparation, no inference
spawn/history/grant consumption afterward, plus inspector descendant cleanup.
Retain existing bounded ledger cancellation and supervisor nonblocking tests.

## Documentation, verification and delivery

- Update maintained configuration/security/validation documentation for the new
  wait option, supported source boundary, strengthened source/grant identities,
  legacy pin/evidence handling and honest inspector limitations. The first
  commit changed no maintained docs; the example config alone is insufficient.
- First add meaningful failing regressions at `7987d26` in a disposable copy;
  convert the saved diagnostics into assertions about safe outcomes. Do not
  mistake their zero diagnostic-script exits for passing safety assertions.
- Run focused affected tests, saved original reconstructed route/boundary probes,
  and new review probes. After they pass, run the full offline suite on available
  Python 3.10/3.12/3.13 and credential-free V2 introspection as the parent brief
  requires. Preserve complete command/version/result logs and list skips.
  Real V1, authenticated providers and the absent literal auditor scripts remain
  explicitly unexecuted unless evidence becomes available.
- Return a copyable Architect report with original BASE, correction BASE, exact
  local commits/HEAD/worktree state, six-finding closure matrix, red/green
  evidence, test logs/counts/skips, deviations and a focused auditor pointer.
  No push; no automatic Architect acceptance. Further review checks corrected
  boundaries and affected integrations, without reopening unrelated scope.
