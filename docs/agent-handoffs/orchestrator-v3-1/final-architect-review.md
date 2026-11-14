# Abdullah Orchestrator v3.1 — final Architect review and auditor entrypoint

**Verdict: APPROVED WITH KNOWN LIMITATIONS.** The reviewed source and offline engineering gates pass for this exact candidate. The candidate is ready for a further independent audit and separately authorized controlled testing. Authenticated host/provider parity, production readiness and stable release are not certified. No remaining blocking source defect was found within the reviewed contract.
Reviewed candidate: `828202f619209390411c9ed37da5ff2a179242a3`.
Original baseline: `1b8e10e5c1b2c08a236b68450cb5b2a1a610416d`.
Date: 2026-11-14. Branch `design/orchestrator-v3-1`.
Source worktree: `/home/abdullah/.local/src/abdullah-orchestrator-v3-1`.
Workflow: original manual Architect/Implementer; all implementation delivered as one batch with three focused correction rounds. No automated Abdullah Orchestrator was used to modify itself.

## Review basis and source identity

The complete independent v3.0.0 audit and user's AOR-01…07/multi-provider requirements were read before design. Initial baseline included d80bea0, matched then-current GitHub main and peeled v3.0.0, and was script-identical to the audit's 32c6fdf. The recorded tag discrepancy was not rewritten. Older checkout, installed orchestrator, existing runs and original manual skills were excluded from development.

The source campaign spans 13 local commits and 36 tracked files, +7,787/-370 lines relative to baseline. Most additions are regression tests/documentation; supervisor grew approximately 2,700 lines. Commits reviewed across the campaign:

- e223ca1 — acceptance/evidence and read-only stages
- 076caeb — explicit host and preflight
- e6cab3c — Claude setup/whole-stage deadline
- a3f6202 — configurable worker providers/schema 3
- 9eb49ef, bfd9a8b — integration documentation
- 740db1c — containment, durable billing grants, effective routing, restore
- 190d7fb, 96dd58e — split Claude stores and correction evidence
- 2d324b0, 7bd998a — shared child routing and managed drop-ins
- b979350, 828202f — dialect-correct variants, captured V2 schema and evidence

The Architect inspected actual code/diffs and relevant executable tests on each round, not only Implementer summaries. Confirmed defects produced saved correction contracts fix-b01-r01/r02/r03.md. Reviews review-r01/r02.md retain prior failures and their evidence; they are historical decisions, not contradictory final verdicts. Exact reviewed candidate is the full SHA above; subsequent source edits require a new review.

## Architecture and scope assessment

Preserved: deterministic Python supervisor, stdio MCP coordinator, strong Architect gates, OpenCode CLI workers, existing JSONL/report contract v2, checkout leases, guarded process ownership and recovery. No provider SDKs, new daemon, native Codex/Claude worker adapters, or speculative backend hierarchy were added. Shared preflight/config composition and an independently locked grant ledger serve concrete correctness/durability boundaries. The large single module and hand-modeled CLI configuration remain maintenance risks; version-specific normalized fixtures/introspection are required when broadening supported CLI behavior. A broad rewrite is not justified by this campaign.

New behavior is limited to the seven corrections, per-role OpenCode provider/model/variant/billing/fallback configuration, pinned routes, human grants, Doctor, migration/restore, installer/host setup and their integration/documentation. Source version is 3.1.0; config/state schema 3; model report contract remains v2. Nothing authorizes installation, tag publication, push, merge, deployment, credential changes or live inference.

## Audit closure matrix

All entries below pass the source/offline engineering review supported by final verification; they are not authenticated host/product certification.

| Finding | Reviewed behavior | Primary executable evidence |
|---|---|---|
| AOR-01 | Exact evidence/plan/candidate decision binding; fresh full provenance/check-executable validation after strong return and cached/recovered consumption; stale approval cannot advance batch or complete | test_v31_acceptance_integrity.py; test_delta_audit_corrections.py; test_decision_contract_regressions.py; campaign integration |
| AOR-02 | Dispatch→completion source preservation for all non-writer stages, including dirty/index/untracked/HEAD and failure/recovery; files preserved, blocked only when containment proven, uncertain otherwise | test_v31_stage_invariants.py; test_checkpoint_a_containment.py; recovery suites |
| AOR-03 | Explicit user-scoped Claude MCP registration, idempotence/conflict handling, manual timeout configuration and rollback evidence; original skills preserved by installer contract | test_v31_claude_setup.py; installer source review |
| AOR-04 | Required explicit host on new runs, stored host/route summary, contradictory resume host refused | test_v31_dispatch_safety.py; MCP/CLI schemas |
| AOR-05 | Shared redacted billing preflight; alternate config directory, provider flags/endpoints/helpers/model routes and observable managed files/drop-ins inspected before dispatch; unknown remote policy not certified | test_v31_dispatch_safety.py; test_checkpoint_c_security.py |
| AOR-06 | Separate host foreground settings/user MCP store, documented timeout; real whole-stage budget and cancellation/containment paths | test_v31_stage_deadline.py; test_v31_claude_setup.py; test_interactive_recovery.py. Authenticated interactive UX pending |
| AOR-07 | Preflight rejection persists diagnostics without dispatched PID-less active job or model-call accounting | test_v31_dispatch_safety.py; worker-route negative cases |

Final correction: `_opencode_selected_variant` uses V1 dictionary keys and V2 array unique ids. Selected endpoint/auth/remap feeds the final layer; malformed influential arrays fail closed. Sanitized fixture `scripts/tests/fixtures/opencode-v2.2.7-variant-config.json` is checked both offline and by the staged binary's normalized `debug config` output. Exit status alone is not schema acceptance evidence. Invalid V2 dict fixtures were replaced rather than accepted as runtime truth.

## Multi-provider compatibility matrix

| Route/case | Reviewed contract | Evidence/remaining gate |
|---|---|---|
| Legacy all-Go | Missing provider derives Go; unchanged Go billing/route retains original consent; non-Go cannot inherit Go exemption | Offline config/migration/dispatch regressions; Go entitlement not independently live-verified |
| Explicit API | Exact run/role/route human grant; atomic durable reservation per attempt; exhaustion blocks before launch | Fake CLI/ledger/concurrency tests; new live API provider pending |
| Non-Go subscription | Explicit human endpoint/auth-mode attestation and bounded grant, consumption preserved across reload and failure | Offline only; settlement/entitlement pending |
| Free/local | Explicit classification/attestation/grant; local endpoint observed; no inference during Doctor | Fake mixed-provider path; actual provider pending |
| Reasoning variants | V1 keyed/V2 id-array selected layer; known malformed shapes refused; empty variant omitted | Real V2.2.7 normalized config + fake dispatch. V1 real-binary and other V2 builds pending |
| Fallback | Complete configured exact alternate, separate one-dispatch consent and --fallback grant; fresh session across route changes | Public-helper fake tests, including missing/exhausted/failed alternatives |
| Mid-run changes | Recorded routes authoritative, relevant routing/auth changes block; no silent repin/fallback | Config/pinning tests; changing provider for future work uses a new run |
| Nested Explorer | Independently locked ledger survives parent snapshots, concurrent reservations bounded and replay idempotent | Separate-process regression and independent diagnostic |
| Reviewer | Fresh independent OpenCode context, unchanged report/permission contract | Worker/isolation/report regression suites |
| Usage | Historical worker cheap_calls count retained without price claims; reported/derived/partial/unavailable semantics maintained | Usage/rate-limit regressions |

Grants bound supervisor attempts, not provider internal retries, token consumption, tariff changes or dollar spend. Unknown provider billing cannot become Go consent by label. Arbitrary plugins/gateways/auxiliary settlement are outside certification; inspectable selected route overrides are bound and classified.

## Saved-run and installation assessment

Schema-2 routes migrate explicitly and backup-first from recorded routes/jobs or reviewed mappings, never current defaults. Active/uncertain work is not silently migrated. Verification, review, cached decisions and check progress are invalidated, including integration. Historical completed records are preserved, not recertified. Restores validate before atomic mutation and retain pre-restore audit evidence. Legacy evidence remains readable but cannot newly certify v3.1 completion through acknowledgement alone. Supervisor-version pins require explicit upgrade handling; existing global config is not rewritten.

Config and operations documentation explains defaults, mixed routes, grants, fallback, host setup, schema migration and rollback. Relevant maintained docs: README.md, SKILL.md, docs/configuration.md, docs/security-model.md, docs/maintenance.md, docs/validation.md, references/contracts.md, references/operation.md and CHANGELOG.md. Detailed prior implementation evidence lives in independent-auditor-handoff.md; any earlier 'Architect pending' statement there records its creation stage. This finalized review at its named SHA supersedes those historical pending-approval entries for the source/offline acceptance gate.

## Final verification

Independent final verification completed at the named candidate, sequentially with no concurrent process-marked probes:

| Command/check | Actual result |
|---|---|
| `python3 -m unittest discover -s scripts/tests -p 'test_v31_routing_observation.py' -v` | 19 tests, OK, exit 0, 8.258 seconds |
| `python3 -m unittest discover -s scripts/tests -v` | 715 tests run, OK, 5 optional binary tests skipped, exit 0, 380.860 seconds |
| `test_opencode_v2_integration.py` with staged V2.2.7 in separate disposable credential-free HOME/XDG/settings environment | All 5 tests run, OK, exit 0, 12.928 seconds; no inference |
| `python3 -m compileall -q scripts` | Exit 0 |

The full suite executed 710 tests and skipped 5; the five optional tests were then independently executed and passed, not miscounted as passes in the offline run. The independent results confirm the Implementer's final-suite evidence. Only Python 3.10.12 was run locally.

The binary check command was `python3 /tmp/ao-v31-final-introspection.py`; it runs `python3 -m unittest discover -s scripts/tests -p test_opencode_v2_integration.py -v` with `ABDULLAH_OPENCODE_V2_BIN=/tmp/ocv2/opencode`, a minimal credential-free environment and temporary HOME/XDG directories. It checks version/help/config/agent permissions and normalized fixture acceptance, not model entitlement or execution.

Durable local evidence copies, deliberately uncommitted with Architect artifacts:

- `docs/agent-handoffs/orchestrator-v3-1/evidence/architect-full-suite.log` — SHA256 `e40c5e506b9cca753d3d9945f6e8d7fd4a7393f62b866ae8789b38c5ed4ce2ed`.
- `docs/agent-handoffs/orchestrator-v3-1/evidence/architect-v2-introspection.log` — SHA256 `32252de23552a8abca266dccce6d1142944eeea9313f3a0d7ad727a2265a7a04`.
- `docs/agent-handoffs/orchestrator-v3-1/evidence/architect-r03-routing.log` — SHA256 `c5eaf3b7ee39d381aa2baaf1d70679719b00d392f2a716eee2963a2985b00f80`.

## Final review categories

| Category | Engineering assessment |
|---|---|
| AOR closure | All seven corrected within observable source/offline boundary; live Claude UX separate |
| Multi-provider | Existing CLI generalized; explicit billing/grants/pinning and negative cases covered |
| Backward compatibility | Explicit schema migration and preserved Go routes/history; no live upgrade performed |
| Source/evidence integrity | Post-decision provenance, decision binding, stage-source and recovery gates reviewed |
| Security/billing | No silent model-owned authorization; process ownership and durable grants retained; no OS sandbox/spend guarantee |
| Host compatibility | Codex/Claude controlling hosts and strong routes supported offline; authenticated parity unverified |
| Execution/recovery | Guard/lease/interruption, report recovery, ledger and restore regressions maintained |
| Configuration | Per-role routes and dialect-specific variants documented; evolving CLI semantics remain a versioned risk |
| Test quality | Real temporary Git/check records/processes plus fake model CLIs; final supported V2 fixture binary-backed |
| Docs/install | Setup/grants/migration/limitations present; installation not applied to user machine |
| Maintainability | Existing design retained; stdlib-only; single large supervisor requires focused changes and fixtures |
| Remaining risks | Listed below; no fabricated authenticated or economic evidence |

## Known limitations and controlled-test gates

- Authenticated Claude/Codex/OpenCode sessions, Claude foreground long-stage/Esc/reconnect and new API/local/free/subscription routes have not been tested live for v3.1. A fake CLI does not prove actual interactive UX or billing.
- Staged OpenCode V2.2.7 introspection is version-specific. V1 real-binary variants and other V2 builds need independent validation; unknown selected variant ids in well-formed metadata rely on documented CLI model-resolution failure, not a demonstrated inference call.
- Server-delivered/MDM/macOS managed policy and executable helpers cannot be certified by local file inspection. No such policy is silently described as observed.
- Same-user protection is not an OS sandbox; hostile races/write-and-restore between snapshots and arbitrary credential access cannot be ruled out. No exactly-once external side-effect guarantee.
- Runtime-input provenance is bounded/heuristic; Docker evidence in the offline suite is synthetic. Declare/review project dependencies for important real workflows.
- No hard dollar/token cap, subscription-quota savings or strong-only quality parity is established. Provider retry/plugin/gateway settlement lies outside the supervisor attempt budget.
- Python 3.12/3.13 have not run locally; authorized CI or equivalent isolated execution is still needed. This review does not grant push permission.

After independent audit, a separately authorized bounded pilot can use a disposable no-secret repository, fixed acceptance checks and fixed route/call budgets. Record actual host/provider versions, foreground/cancel/reconnect observations, exact source/run/evidence identities, attempts and any provider usage actually observable. A source/offline approval is not authority to make paid requests, install or release.

## Independent-auditor handoff

Use this file as entrypoint with independent-auditor-handoff.md for detailed test matrices and historical correction evidence. Audit exactly baseline `1b8e10e5c1b2c08a236b68450cb5b2a1a610416d` to candidate `828202f619209390411c9ed37da5ff2a179242a3`, plus the actual current working-tree status. Inspect final code and negative paths rather than treating this verdict as proof. The original supplied audit's raw probe/pilot ZIP artifacts remain unavailable; historical E2E claims are secondary evidence.

Review commands from the source worktree:

```
git status --short --branch
git log --reverse --oneline 1b8e10e..828202f
git diff --stat 1b8e10e..828202f
git diff 1b8e10e..828202f -- scripts/orchestrator.py scripts/install_wsl.py scripts/config.example.json
python3 -m compileall -q scripts
python3 -m unittest discover -s scripts/tests -v
```

Run the optional real V2 suite only in a disposable credential-free environment with ABDULLAH_OPENCODE_V2_BIN targeting a staged supported binary; do not run installed user Doctor or authenticate as part of an ordinary audit. Transfer this report and original untracked brief/design/review files when handing the task to an auditor outside this shared worktree. These documents and the evidence/ logs are deliberately uncommitted Architect artifacts and are not present in git archive of the candidate. Include them when exporting an audit package; no commit or export is performed by this review.
