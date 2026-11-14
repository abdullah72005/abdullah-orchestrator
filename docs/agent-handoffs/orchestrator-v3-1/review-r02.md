# Architect review — v3.1 correction round 2

Date: 2026-11-14.
Verdict: **CHANGES REQUIRED** — one P1 remains in F5c's V2 selected-variant handling.
Base: 96dd58ebe0258100c06cbe9f6b71c6564ba9d739.
HEAD: 7bd998a45515a7e07384df803c71b2fced8f65fe.
Commits: 2d324b0 and 7bd998a. Six changed files match report, tracked tree clean, seven prior untracked Architect documents preserved. This review and fix-b01-r03.md are additional uncommitted Architect documents. No production source changes by Architect.

## Independent review and checks

Inspected the complete correction source diff, affected observation/child-environment/Go-qualification/managed-source paths, new tests, and documentation against fix-b01-r02.md. F5a child-config preservation, F5b authentication-mode pin inclusion and F6 local policy fragments satisfy their scoped corrections. F1–F4/F7–F9 remain accepted from the preceding scoped review; no unrelated re-audit/polish added. The genuine staged-binary result below requires correcting only the remaining V2 variant shape under F5c.

Independently executed, Python 3.10.12:
- `python3 -m unittest discover -s scripts/tests -p 'test_v31_routing_observation.py' -v`: 13 tests, OK, 6.527 seconds, exit 0. /tmp/ao-r02-architect-routing.log.
- `python3 -m unittest discover -s scripts/tests -p 'test_v31_dispatch_safety.py' -v`: 27 tests, OK, 3.752 seconds, exit 0. /tmp/ao-r02-architect-dispatch.log.
- Existing optional `test_opencode_v2_integration.py`, ABDULLAH_OPENCODE_V2_BIN=/tmp/ocv2/opencode, wrapped in a disposable credential-free HOME/XDG environment: 4 tests, OK, 13.248 seconds, exit 0. /tmp/ao-r02-architect-v2-introspection.log. This proves only version/help/generated-profile/permission introspection, not provider calls or billing.
- Staged binary version: opencode v2.2.7. Actual `debug config --standalone` with separate temporary HOME/XDG/environment and no credentials, once with array variants and once with dict variants: both exit 0; normalized array output preserves provider/model/selected endpoint, dict output contains providers={}. Configuration acceptance requires examining normalized output, not exit code alone.

Inspected Implementer /tmp/opencode/ao-r02-v31.log: 129 tests, OK, 141.562 seconds; /tmp/opencode/ao-r02-full.log: 708 tests, 4 optional binary skips, OK, 365.975 seconds. Did not redundantly rerun all 708 tests. Saved red logs were supplied; no implication that all runtime/schema assumptions in fake tests are valid merely because the suite passes.

## Remaining defect

`_opencode_route_layers` at scripts/orchestrator.py:1570 reads model.variants only as a dict. Supported V2 uses an array of variant objects with id. Its selected variant is consequently omitted from effective endpoint, auth observation and Go qualification.

Independent disposable probe /tmp/ao-r02-variant-probe.py (copy /tmp/ao-r02-architect-evidence/), reviewed HEAD:

```
providers.opencode-go.models.go-model.variants = [
  {id: low, settings: {baseURL: https://override.invalid/v1}}
]
route = opencode-go/go-model#low, billing go, no grant
preflight_ok: true
classification: go_subscription
endpoint_source: null
go_qualification: {qualified: true, reasons: []}
```

The staged supported CLI preserves this array configuration. The supervisor's V2 negative fixture instead uses a dict which the real CLI drops. This leaves the original no-silent-billing exemption requirement unsatisfied. No actual inference, provider charge, model entitlement or authenticated session was tested or claimed.

Sources rechecked: https://opencode.ai/docs/models/ (Variants array with id, selected-layer precedence); https://opencode.ai/docs/providers/ (settings/baseURL/model/variant options).

## Plan correction and acceptance

After repeated routing corrections, the approach is revised toward dialect fixtures captured from actual supported-CLI normalization, plus explicit validation/fail-closed handling for uninspectable influential shapes. This is a bounded schema correction, not a supervisor/backend rewrite. See fix-b01-r03.md for exact scope, actual reproduction and test requirements. No permission question is needed for this correction within the approved campaign; the human still manually starts the Implementer.

Campaign: AOR-05's requested inspectable Claude policy fix now passes offline/source review. AOR-01/02/04/07 and offline AOR-03/06 remain maintained. Multi-provider billing acceptance stays OPEN only for the confirmed F5c case in this review. Original batch, release and live use are not approved. Authenticated Claude/Codex/provider E2E, V1 real-binary variant introspection, Python 3.12/3.13, real Docker source evidence, remote/MDM/macOS policy and provider settlement retain their explicitly unverified status. Do not infer a spending cap or OS sandbox.
