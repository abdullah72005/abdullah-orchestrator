# v3.1 single batch — Architect correction round 2

Disposition: CHANGES REQUIRED, narrowed to remaining F5/F6 boundaries from fix-b01-r01.md. Do not reopen unrelated accepted corrections or add new features.
Correction base: `96dd58ebe0258100c06cbe9f6b71c6564ba9d739`.
Original campaign base: `1b8e10e5c1b2c08a236b68450cb5b2a1a610416d`.
Worktree `/home/abdullah/.local/src/abdullah-orchestrator-v3-1`, branch `design/orchestrator-v3-1`.
Authorities: batch-01.md, approved architecture.md and fix-b01-r01.md. User requirements prevail. The original single-batch manual workflow remains in force; no extra approval between the fixes below.

## Review disposition and evidence

Reviewed all three correction commits and the affected source, new ledger/observation tests, migration/restore/installer changes, documentation and saved suite evidence. Tracked tree clean, original five untracked planning/correction files preserved. R01 produced substantial progress: F1/F2/F3/F4/F7/F8/F9 pass the scoped code/behavior review, subject to maintaining their regression checks in the next complete candidate. F5 and F6 remain incomplete for the specific cases below. These are the original routing/managed-source requirements, not a new provider-adapter or OS-isolation project.

Implementer's saved full run `/tmp/opencode/ao-v31-r01-full-suite-final2.log`: 695 tests, 4 optional binary skips, OK, 354.540 seconds. Saved focused run: 116 tests, OK, 139.822 seconds. Architect independent focused rerun and any qualifications are recorded in review-r01.md in this directory. No model calls, installed configuration changes or production edits occurred during review.

Disposable Architect probes: `/tmp/ao-r01-routing-probes.py`, `/tmp/ao-r01-child-config-probe.py` (copies under `/tmp/ao-r01-architect-evidence/`). They use temporary config/HOME/Git/state and fake CLIs. The following outputs are independently observed; implement permanent regressions that reproduce behavior rather than depending on temporary scripts.

## F5a — P1: observed routing differs from the actual child configuration

Locations: `scripts/orchestrator.py:1391` opencode_provider_observation, `opencode_env:4674`, cli_command/call_model, routing pins and Doctor.
Root cause: observation merges ambient OPENCODE_CONFIG_CONTENT, but opencode_env replaces that variable entirely with generated role/profile configuration. The provider that preflight approved can disappear before dispatch.
Evidence from a full fake local dispatch: ambient inline V1 provider defines `local/probe` and loopback baseURL; reviewed local grant succeeds. Saved job billing is local, preflight endpoint is present, dispatch completes, but fake child capture contains no local provider or endpoint. Equivalent direct V2 observation/child-env probe shows the same mismatch. This proves a configuration-boundary bug, not actual paid execution.
Correction: derive observation/pin/Doctor and execution from the same effective child routing configuration and dialect. Preserve supported routing fields when composing generated profile configuration, while ensuring generated permission/agent/subagent controls retain authority. Alternatively refuse an unsupported influential override explicitly before dispatch; do not approve and then silently discard it. Resolve paths and expansion against the same actual cwd/environment. Keep existing V1/V2 adapters and no SDK additions. A shared small configuration-composition/resolution boundary is preferable to independently parsing two different configurations.
Required tests: actual fake CLI captures its argv and OPENCODE_CONFIG_CONTENT for V1 and V2; inline custom local/API providers retain the approved endpoint/model, or fail closed before spawn with clear diagnostic. Assert preflight routing digest matches child routing material; generated ordered permissions and subagent restrictions cannot be overwritten by ambient inline agents/settings. Include pinning, reload, Doctor and nested Explorer callers.

## F5b — P1: authentication-mode observation is omitted from the fingerprint

Locations: opencode_provider_observation around 1477, routing_material_sha256 around 1499 and routing_fingerprint:1535.
Root cause: the observer computes auth_mode_sha256 including credential env availability, but when routing_material_sha256 exists, routing_fingerprint omits auth_mode_sha256. The hashed provider entry contains env names, not their availability. Thus an observed auth-mode change is not pinned.
Independent evidence: V2 provider with env [REVIEW_ROUTE_KEY], no direct apiKey. Pin when variable absent, then set a dummy value with unchanged config. `auth_observation_changed:true` but `routing_pin_changed:false`.
Correction: bind relevant effective authentication mode/material in every fingerprint branch. Include actual resolved child env/auth selection without exposing credentials; do not equate a declared env name with the effective authenticated mode. A separate hash or redacted presence/mode indicator is acceptable when it detects this concrete transition. Never log raw keys. Preserve the distinction between configured auth and authenticated entitlement, which remains unverified.
Required tests: both dialects, absent→present and present→absent provider credentials with unchanged config/model count/option names; pinned preflight blocks drift before spawn. Stable unchanged auth remains usable; expose only redacted evidence. Do not mock away the observation/fingerprint branch exercised by the regression.

## F5c — P1: Go billing exemption overlooks selected model/variant endpoint overrides

Locations: opencode_provider_observation around 1463–1498 and route_preflight Go branch around 1868.
Root cause: endpoint_sha256 is derived only from provider settings/options. The selected model/variant may override provider-package settings including baseURL; hashing the override does not establish that it is a Go subscription route. Preflight still uses the provider-only endpoint field for its no-grant exemption.
Independent evidence: V2 `providers.opencode-go.models.go-model.settings.baseURL` points to a custom proxy. Preflight returns `ok:true`, `classification:go_subscription`, provider endpoint appears absent, and no new grant is required. The official models reference states provider values apply first, then model values, then selected variant, and settings include baseURL.
Correction: resolve effective selected provider/model/variant routing before applying subscription/free/local classification. Reject or explicitly authorize a custom endpoint/remapped route that cannot qualify for legacy Go consent. Validate inspectable package/canonical routing overrides insofar as they affect that exemption; do not assume the opencode-go name proves subscription. Maintain the unchanged real Go default and do not hardcode model names. Fingerprinting and classification must use the same effective material. No attempt to prove arbitrary plugin settlement is required; retain that explicit limitation.
Required tests: V1 and V2 provider/model/selected-variant endpoint precedence, including benign unchanged Go and custom endpoint under Go; latter fails before spawn or requires accurately classified explicit authorization. Include supported model mapping/package changes where applicable. Tests must assert classification/consent, not only different digests.
Official references checked 2026-11-14: https://opencode.ai/docs/models/ (Options and provider/model/variant precedence), https://opencode.ai/docs/providers/ (provider settings and custom routes), https://opencode.ai/docs/config/ (configuration locations/shapes). Match syntax to the supported installed dialect; no copying V2 fields into V1.

## F6 — P1: observable local Claude managed drop-ins remain unchecked

Locations: CLAUDE_MANAGED_SETTINGS_FILES:1086, _claude_settings_paths:1104, claude_billing_hazards and Doctor.
Root cause: only managed-settings.json is enumerated. Claude also reads sibling managed-settings.d/*.json even when the main file is absent. This is an inspectable local source, unlike the explicitly unobserved remote/MDM mechanisms.
Independent reproduction: in a disposable managed directory, omit managed-settings.json and create managed-settings.d/10-route.json containing env.ANTHROPIC_BASE_URL with a custom endpoint. Point the existing test-replaceable managed-file tuple at that directory's base file. Preflight returns ok and no reasons; it enumerates user/project/local/base managed file only.
Correction: enumerate applicable local drop-ins in documented order (base file then non-hidden *.json alphabetically), including when the base file is absent. Apply existing redacted hazard/parse/read validation to each. Preserve missing-vs-unreadable distinction and reject influential unreadable files/directories instead of silently declaring no hazards. Do not execute policy or credential helpers to inspect them. Keep remote/MDM/macOS unobservability explicitly limited; no new platform-management implementation is requested. Doctor and dispatch share the same classification.
Required tests: dangerous drop-in with base absent/present, helper/provider/endpoint keys, malformed/non-object JSON, unreadable file/directory (simulate permission failure without changing real /etc), ordering, hidden/non-JSON ignored, clean subscription, authorized alternate billing. Assert rejection precedes spawn/active_job, keeps diagnostics and never includes the endpoint/credential value.
Official reference: https://code.claude.com/docs/en/managed-settings (Where each mechanism stores policy; Split a file-based policy across teams). This documents Linux/WSL /etc/claude-code/managed-settings.d and merge order.

## Verification and scope control

Add red regressions for the four cases above, then minimal corrections. Avoid extending the parser to speculative inputs; align the supported effective child route instead. If supported effective routing cannot be established without an architectural change, stop and explain the concrete blocker rather than starting a rewrite.

Run in isolation: temporary fixtures use the shared test-run00 marker, so simultaneous suites/containment probes may signal each other's fake processes. Do not run process-creating diagnostic suites alongside one another. Keep fixture HOME/state/config/registry disposable and all model binaries fake.

```
python3 -m unittest discover -s scripts/tests -p 'test_v31_routing_observation.py' -v
python3 -m unittest discover -s scripts/tests -p 'test_v31_dispatch_safety.py' -v
python3 -m unittest discover -s scripts/tests -p 'test_v31_*.py' -v
python3 -m unittest discover -s scripts/tests -p 'test_p1_03_permission_overlap.py' -v
python3 -m unittest discover -s scripts/tests -p 'test_checkpoint_a_containment.py' -v
python3 -m compileall -q scripts
python3 -m unittest discover -s scripts/tests -v
```

One full suite after completed fixes, no paid requests. Preserve targeted F1–F4/F7–F9 tests, acceptance/cached-decision, migration, context, report, leases, independent reviewer and grant limits. Update documentation/closure matrices only to match actual evidence; authenticated E2E and unavailable Python versions stay unverified. Do not change original manual skills, installed orchestrator, global config, credentials, existing runs or Sanatry. No push/merge/tag/release/install/destructive Git; local focused commits permitted. Preserve untracked Architect docs and do not auto-commit them.

Return one copyable report with baseline/final HEAD, commits/diff/status, F5a/b/c and F6→code/test matrix, captured red/green outputs, exact commands/results/skips/exit codes, captured child-config evidence, compatibility/permission/billing impact and residual limits. The Architect will independently inspect the next diff; this correction is not release approval.
