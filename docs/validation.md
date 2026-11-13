# Validation and evidence

This page records what was actually exercised, what was found, and what remains
unverified. It is intentionally specific so an independent reviewer can
reproduce or challenge the claims.

## 1. Deterministic test suite

```bash
python3 -m unittest discover -s scripts/tests
```

- **656 tests**, 4 opt-in skips, roughly 6 minutes on a laptop (Python 3.10.12;
  CI also targets 3.12/3.13). Counts are from the v3.1 candidate run recorded
  below; `pytest` may show a different skip distribution.
- No model calls. A guard replaces `codex`, `claude`, and `opencode` with fakes
  and raises if a test tries to launch a real model CLI.
- Tests are hermetic: exported `ABDULLAH_CONFIG`, `ABDULLAH_STATE_DIR`, and
  `ABDULLAH_CHECKOUT_REGISTRY` values from a real run are replaced with
  temporary paths, so the suite cannot read or write live state.

Coverage areas:

| Area | Representative tests |
|---|---|
| State machine and phases | plan → implement → verify → review → accept, corrections, amendments |
| Containment | guard sessions, descendants, reused PIDs, zombies, escaped processes, reconciliation |
| Checkout ownership | leases, conflicts, retirement, orphan recovery, adoption, WSL inode fallback |
| Verification provenance | source/env/config/toolchain drift, runtime-input manifests, Docker source proof, legacy evidence |
| Acceptance integrity (AOR-01) | `test_v31_acceptance_integrity.py`: late check-executable/source/env/config/runtime/plan drift, evidence-byte replacement, new-record/new-decision, bound crash recovery |
| Read-only stage invariants (AOR-02) | `test_v31_stage_invariants.py`: real Git/fake CLIs, tracked/staged/untracked/HEAD mutation, malformed/nonzero failure paths, recovered-report mismatch |
| Host and dispatch preflight (AOR-04/05/07) | `test_v31_dispatch_safety.py`: missing host, contradictory resume, provider flags, settings helper/malformed settings, inert AWS creds, durable rejection without a job, spawn-failure distinction, Doctor parity |
| Claude setup and stage deadline (AOR-03/06) | `test_v31_claude_setup.py`, `test_v31_stage_deadline.py`: idempotent/conflicting registration, rollback, foreground snippets, whole-stage clipping |
| Worker providers and migration | `test_v31_worker_routes.py`, `test_v31_route_migration.py`: mixed routes, grants, fallback, session boundaries, endpoint drift, recorded-route migration, rollback, newer schemas |
| Full campaign paths | `test_v31_campaign_integration.py`: fake Codex and Claude multi-batch runs, late drift with fresh checks |
| Command policy | shell wrappers, interpreter strings, indirect Docker, scoped exceptions, bypass acknowledgements |
| Report contracts | strict schemas, contract v2, invalid JSONL, recovery without a model call |
| OpenCode dialects | V1/V2 profile generation, effective-permission validation, glob-overlap rejection |
| Usage accounting | nested OpenCode usage, derived/partial totals, bounded 429 detection |
| MCP surface | nine tools, no approval/grant tools, cancellation, recovery guidance |
| Security regressions | credential env scrubbing, API-billing fail-closed, sensitive CLI gating |

The opt-in real-CLI suite makes no model call:

```bash
ABDULLAH_OPENCODE_V2_BIN=/path/to/opencode-2.2.7 \
  python3 -m unittest discover -s scripts/tests -p "test_opencode_v2_integration.py"
```

It checks generated V2 configuration against the real binary's
`opencode debug agents` output, including that appended `allow` rules cannot
reopen mandatory denies.

## 2. v3.1 candidate evidence

The v3.1 batch was validated entirely offline:

```
python3 -m compileall -q scripts
python3 -m unittest discover -s scripts/tests -v
```

The final candidate run and exact counts are recorded in the delivery report and
`docs/agent-handoffs/orchestrator-v3-1/independent-auditor-handoff.md`. Fake
`codex`, `claude`, and `opencode` executables exercise real supervisor code,
temporary Git checkouts, real `run_checks` records and real process containment.
They do **not** prove authenticated model behavior.

Evidence classes are kept separate:

| Class | What it establishes | v3.1 status |
|---|---|---|
| Source inspection | Code paths and guards exist as described | Performed by Implementer; independent Architect review pending |
| Offline fake-CLI tests | Deterministic supervisor behavior and failure paths | Executed; see counts above |
| Installed-CLI introspection | Generated argv/help and V2 agent/permission shapes | Optional suite; skipped when the binary is absent |
| Historical pilot claims | A real v3.0.0 run completed | Historical, not v3.1 recertification |
| Authenticated E2E | Real Claude/Codex stages, Esc/reconnect, new provider routes | **Not executed**; requires separate bounded human authorization |

## 3. Historical real end-to-end pilot (v3.0.0)

This pilot predates v3.1 and is retained as historical evidence, not as proof
that the v3.1 acceptance-binding, host-gating, stage-deadline, installer, or
provider-route changes were exercised live.

On **2026-11-13**, the complete implementation ran a real goal through a real
Codex conversation on an isolated copy of the repository. Nothing was installed
globally for the pilot; MCP registration, config, state, and the disposable
project were all pilot-local.

| Item | Value |
|---|---|
| Run ID | `20261113T104752-32561af8` |
| Host | Interactive Codex CLI `0.169.0`, ChatGPT subscription auth |
| Architect | `gpt-6.1-sol`, high effort |
| Workers | OpenCode `v2.2.7`, Go billing, `deepseek-v4.1-flash` high |
| Explorer policy | `none` (no Explorer dispatch) |
| Goal | Implement a standard-library duration parser (`1h30m → 5400`) in a disposable Git repo |
| Verification | `python3 -m unittest discover -s tests -t . -v` |
| Outcome | **complete**, Architect verdict `approved` |

Actual stage evidence from the run:

| Stage | Result |
|---|---|
| Architect plan | Completed; plan version recorded, one batch, risk `ordinary` |
| Implementer | Completed; `duration.py` + `tests/test_duration.py`, contract v2 report |
| Supervisor verification | Exit 0 against candidate `9bbc5756…`; evidence version 2 |
| Independent Reviewer | Completed; findings recorded with dispositions |
| One correction cycle | Used; long-quantity chunk bug found and fixed |
| Architect acceptance | Approved after direct inspection of code, diff, evidence, and a fresh 22-test run |
| Total | 5 strong calls, 4 cheap calls; 6 h 3 min elapsed, 755.8 s of recorded model time |

Recorded usage: 110,216 input tokens, 10,768 output tokens, 13,539 reasoning
tokens, 490,112 cache-read tokens. Cost is reported as `0.0` for subscription +
Go; no quota is inferred.

### Defects the pilot exposed

The pilot was valuable precisely because it failed twice before succeeding.
Each failure produced a permanent regression test.

| # | Symptom | Root cause | Fix |
|---|---|---|---|
| 1 | Codex returned HTTP 400 `invalid_json_schema` before planning | Generated strict schema omitted `verification_purpose` from `required` while declaring it | `4a23a00` — emit strict-compatible schemas and require every declared key |
| 2 | A valid `changes_required` verdict was rejected at acceptance | Decision schema omitted `contract_version`, which the validator required and strict mode could not add | `f35e14f` — declare and require `contract_version` in the decision schema |
| 3 | OpenCode reports with escaped/unparseable JSON could not be recovered | Ingestion failure was generic and lost the distinction between transport and report failure | `d80bea0` — classify ingestion failures and add `recover-report` with preserved artifacts |

Regression fixtures are copied byte-for-byte from the failed jobs and are
referenced by SHA-256 in the test docstrings:

- `fixtures/architect-plan-schema-pre-fix.json`
- `fixtures/decision-schema-pre-fix.json`
- `fixtures/decision-report-pre-fix.json`
- `fixtures/opencode-v2-implementer-invalid-json.jsonl`

No verdict was hand-edited into the run to bypass provenance. The failed
decision artifact was preserved, the schema was fixed, and a new Architect
decision call was made — acceptance did not silently reuse a failed job.

### Why this is meaningful

- The same supervisor code path ran: real MCP server, real guard, real CLI
  processes, real Git worktree, real verification logs.
- The supervisor, not the model, executed the checks and bound the evidence.
- The independent Reviewer found a real defect, the correction was bounded, and
  the final Architect decision inspected the actual diff and re-ran the tests.
- Recovery was exercised: the run survived two supervisor restarts and resumed
  from persisted state without repeating completed stages.

## 4. Independent audit trail

The implementation was audited in stages before this release. Documents are
preserved in [`docs/audit/`](audit/):

| Document | Contents |
|---|---|
| [`final-hardening-notes.md`](audit/final-hardening-notes.md) | Baseline findings, OpenCode V2 discovery, initial gap list |
| [`final-audit-evidence.md`](audit/final-audit-evidence.md) | Before/after probes for command policy, provenance, MCP approvals, acceptance gates |
| [`delta-audit.md`](audit/delta-audit.md) | Five reproduced acceptance blockers and their fixes, with the exact commits |

Highlights of what changed as a result:

- Plan approval and fallback authorization removed from the MCP surface.
- V2 permission validation rewritten to evaluate ordered rules by glob overlap,
  not by sampling paths.
- Toolchain identity keyed on file fingerprints so an in-place upgrade
  invalidates evidence.
- Mandatory decision context (findings, amendments, evidence, source identity)
  can no longer be replaced by an opaque hash.
- Partial token totals are labelled instead of being reported as complete.
- Scoped command exceptions require a project identity.

## 5. What is not verified

Be explicit with reviewers and users:

- **Authenticated model execution is not covered by the default suite.** The
  historical pilot proves one real v3.0.0 path; it is not a compatibility matrix
  and does not recertify v3.1.
- **Claude host mode** was not exercised end-to-end. Registration, rollback,
  snippets, flags and a whole-stage deadline are covered by fake-CLI tests; no
  real Claude long stage, Esc/cancel/reconnect or `/mcp` UX is part of this
  evidence.
- **OpenCode V1** profile generation is unit-tested; the pilot used V2.2.7.
- **New provider routes and fallback** are exercised with fake CLIs and route
  policy tests, not with paid/local provider accounts. Billing classifications
  are attested policy, not provider settlement; no dollar/token cap is proven.
- **Installed-CLI introspection** is optional and may be skipped when the binary
  is absent; `test_opencode_v2_integration.py` keeps those skips separate.
- **OS isolation is not provided.** Permissions and containment are
  application-level; a dedicated user/container remains the operator's job.
- **Long-duration behavior** (multi-hour stages, host sleep, network partition)
  is covered by design and deterministic timing tests, not by a timed production
  run. Same-user write-and-restore between snapshots is not detectable.
- **Docker verification** was unit-tested with synthetic Compose evidence; the
  pilot project did not use containers.
- **`doctor`** does not authenticate, prove entitlement, or run a model.

## 6. Reproducing the checks

```bash
# deterministic suite (offline)
python3 -m unittest discover -s scripts/tests

# compile check
python3 -m compileall -q scripts

# optional: real V2 CLI introspection, no model call
ABDULLAH_OPENCODE_V2_BIN=/path/to/opencode-2.2.7 \
  python3 -m unittest discover -s scripts/tests -p "test_opencode_v2_integration.py"

# preflight on a real project
python3 scripts/orchestrator.py doctor --project /absolute/path/to/repo
```

A clean-room validation from a fresh clone is the authoritative check for a
release ZIP: install nothing globally, run the suite, then inspect the
repository tree against `git ls-files`.
