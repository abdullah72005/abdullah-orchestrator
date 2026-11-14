# v3.1 single batch — correction round 3: V2 variant schema

Disposition: CHANGES REQUIRED. One remaining P1 under original F5c.
Base: `7bd998a45515a7e07384df803c71b2fced8f65fe`.
Worktree: `/home/abdullah/.local/src/abdullah-orchestrator-v3-1`, branch `design/orchestrator-v3-1`.
Authority: approved batch-01.md, architecture.md, fix-b01-r02.md. This brief supersedes only the unfinished V2 selected-variant portion of F5c; preserve all accepted corrections and the manual single-batch workflow.

## Revised approach after repeated routing corrections

The remaining failure comes from fixtures modeling the wrong V2 configuration shape. Stop extending the observer against self-invented V2 inputs. Use configuration captured from the actual supported staged binary/schema for the next correction, with the documented model shape as a cross-check. No SDK, service, module rewrite or new authorization system is required. Keep V1 and V2 parsing explicitly dialect-specific and reject uninspectable input rather than approving an absent override.

## Confirmed defect and evidence

Location: scripts/orchestrator.py `_opencode_route_layers`, around 1578–1584; effective endpoint/auth/Go qualification consumers. It reads variants only when isinstance(variants, dict), ignoring V2's documented array of objects keyed by id. Test `test_go_route_model_and_variant_endpoint_overrides_are_not_subscription` builds the same dictionary for both dialects, so its V2 negative case is not a valid supported-V2 fixture.

Exact influential V2 input:

```json
{
  "providers": {
    "opencode-go": {
      "models": {
        "go-model": {
          "variants": [
            {"id": "low", "settings": {"baseURL": "https://override.invalid/v1"}}
          ]
        }
      }
    }
  }
}
```

Route: runtime opencode, worker_provider opencode-go, model opencode-go/go-model, effort low, billing go, no grant. Independent preflight returns `ok:true`, `classification:go_subscription`, `endpoint_source:null`, Go qualified true. It must refuse the custom selected endpoint under legacy Go consent.

Independent source/schema evidence at review HEAD:
- `python3 /tmp/ao-r02-variant-probe.py` uses disposable test config/state and then a separate credential-free temporary HOME/XDG environment for real binary diagnostics. Script copied under /tmp/ao-r02-architect-evidence/.
- `/tmp/ocv2/opencode --version`: `opencode v2.2.7`.
- Real `debug config --standalone` preserves the provider/model with the array above. The dictionary-shaped equivalent yields `providers:{}`. Exit 0 alone does not establish config acceptance; inspect normalized output.
- No inference, auth operation, model request, installed config modification or real project access was performed. This proves configuration shape, not a real provider charge.
- Official reference checked 2026-11-14: https://opencode.ai/docs/models/ (Variants: array with id; Options: provider→model→variant precedence), https://opencode.ai/docs/providers/ (settings/baseURL and model/variant overrides).

## Required correction

1. Resolve the selected V2 variant from its actual array entries by id. Keep V1 handling consistent with its supported dictionary syntax. Apply the selected layer to endpoint precedence, auth-mode observation, model/provider/package remap checks and Go qualification. Unselected variants must not override selected routing.
2. Validate influential shape. Wrong-type, malformed, missing-id or ambiguous duplicate-id variant entries must not silently qualify as unchanged Go. Match documented/runtime behavior where established; otherwise reject as unprovable routing before spawn. Do not infer harmlessness from CLI exit 0 or dropped invalid input.
3. Replace invalid V2 dict fixtures with valid array fixtures. Keep a separate invalid-shape refusal test instead of treating dictionary input as successful V2 execution. Preserve unchanged default Go and explicit accurately classified API authorization.
4. Add a captured, sanitized V2.2.7 configuration-source fixture from the real binary (no secrets). A permanent offline test must use that fixture to prove the resolver sees the selected endpoint. Add an opt-in binary check of normalized fixture acceptance, rather than assertions solely against the Python observer. Preserve/extend the existing opt-in suite; never execute inference.
5. Update relevant closure/evidence documentation to distinguish executable offline regressions, staged-binary config introspection and still-unverified authenticated runtime behavior. Make no live billing/entitlement claim.

## Acceptance cases

- [ ] Valid V2 array selected custom endpoint → `unqualified_go_route`, no grant exemption or spawn.
- [ ] Selected variant overrides provider/model endpoints; different unselected variant does not win.
- [ ] Selected variant auth availability/remap influences the same observation/fingerprint/classification path.
- [ ] Missing/wrong-type/duplicate-id/malformed influential entries fail closed or follow independently established supported-CLI semantics without hiding a route override.
- [ ] Valid V2 array with benign reasoning settings and unchanged Go remains usable without new grant.
- [ ] Same custom route with explicit API billing and exact human grant works through fake CLI; no silent fallback/session reuse change.
- [ ] V1 existing variant behavior, generated ordered permissions, source/evidence integrity, ledger, migration, restore and Claude policy tests remain passing.

## Verification

Use isolated disposable HOME/config/state/registry for every executable. Do not run process-marked suites concurrently (shared fixture test-run00 markers can interfere). Run new red tests at this exact base before production edits and preserve output.

```
python3 -m unittest discover -s scripts/tests -p 'test_v31_routing_observation.py' -v
python3 -m unittest discover -s scripts/tests -p 'test_v31_*.py' -v
python3 -m unittest discover -s scripts/tests -p 'test_p1_03_permission_overlap.py' -v
python3 -m compileall -q scripts
python3 -m unittest discover -s scripts/tests -v
```

Also run the opt-in `test_opencode_v2_integration.py` against `/tmp/ocv2/opencode` with disposable host environment and HOME/XDG directories and ABDULLAH_OPENCODE_V2_BIN pointing at that staged binary. Do not let introspection read real user settings/credentials. Real debug config/agents/help is authorized for these disposable fixtures; model execution is not. Record skipped/unavailable binaries honestly if the staged path is absent. One full offline run after completed corrections; repeat only if later changes justify it.

## Permissions and report

Implement only this bounded correction, focused local commits permitted. Preserve original manual skills, installed orchestrator, global settings/credentials, existing runs, Sanatry and all Architect handoff files. No push, merge, tag, release, install, destructive Git or paid/authenticated model calls. No automated orchestrator. If supported schema cannot be established from actual artifacts, report that blocker instead of inventing another fixture or broadening the observer.

Return one copyable report: baseline/HEAD/commits/diff/status, selected-variant schema and normalization evidence, red/green commands/counts/exit/skips, endpoint/auth/remap/negative-shape cases, preserved earlier regressions and remaining limitations. Architect approval still requires independent inspection of the next actual diff. Do not claim the batch or stable release approved.
