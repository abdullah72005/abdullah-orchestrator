# Final delta-audit corrections (2026-11-13)

Scope: close the five independently reproduced acceptance blockers from the
Principal Engineer delta audit. No push, merge, install, deployment, live-config
change, paid model call or real-run modification was performed.

## 1. Baseline and ZIP revision mismatch

- Development checkout: `~/.local/src/abdullah-orchestrator-remediation`
- Audit start HEAD: `9cda888c83f90afce6ae08166bbed25a02b14817` (`main`)
- Expected last code commit: `814758baae0fbe1cd6760c53e4d2370f3660591a`
- Certified correction commit: `2438d32` (`fix: close final delta-audit acceptance blockers`)

`9cda888` is a merge commit with parents `b71f84e` and `814758b`. Its tree is
**byte-identical** to `814758b`:

```
git rev-parse 814758b^{tree} 9cda888^{tree}
ee8cfcb7baddf664dfb7036e79a92c730dae4712
ee8cfcb7baddf664dfb7036e79a92c730dae4712
git diff --stat 814758b 9cda888      # empty
```

The ZIP build therefore included the merge commit created after the audited
code commit, not a different source revision. All audit findings reproduce
against `814758b`, and the pre-fix worktree used for before/after probes was
created from that exact commit.

## 2. Fixes

### P1-01 — toolchain caching / stale evidence
- `toolchain_identity()` now keys its cache on a bounded stat fingerprint
  (resolved path, device, inode, size, mtime, ctime) for `git`, `docker`,
  `node`, `uv` and the Python executable. An in-place upgrade produces a new
  cache key without changing `PATH`.
- `check_toolchain_identity()` fingerprints the executables named by the
  approved verification argv (for example `pytest`), stores them in the
  evidence provenance, and rejects reuse when they change.
- Evidence reuse validates the binding through the shared
  `load_verification_evidence()` at review/accept and for recovered cached
  decisions. A stale accept binding is recoverable: the run resets to
  `verify` instead of pausing in a dead end.
- Legacy records without the new fingerprint fields compare only the original
  identity fields, preserving existing-run compatibility.
- Command execution remains bounded (`timeout=5` for version probes,
  `timeout=60` for V2 agent introspection).

### P1-02 — critical context preservation
- `_bounded_context()` distinguishes mandatory decision evidence from bulk.
  Independent-review findings, user amendments, material amendments,
  corrections, failure/diagnosis notes, accepted batches, exploration,
  explorer findings, acceptance evidence, source identity and durable artifact
  references are never replaced by an opaque hash.
- Review/accept evidence remains inline with: `verification_path` +
  `verification_sha256`, per-command `log_path` + `log_sha256` + `log_bytes`,
  bounded output tails, source hashes and toolchain identity. Large
  `runtime_inputs.files` and large dirty-tree `changed` maps are condensed to
  count + canonical digest; full data remains in the durable record.
- `approved_handoff.source` and the production reviewer key `verification`
  receive the same evidence/source compaction.
- Small optional stage inputs stay inline; only optional bulk above 2,000
  characters becomes a validated reference.
- If mandatory evidence genuinely cannot fit, the handoff raises
  `Essential handoff context exceeds the configured budget...` and refuses to
  drop requirements, findings, evidence, amendments or source identity.

### P1-03 — OpenCode V2 effective permissions
- `validate_v2_effective_permissions()` validates the actual ordered rules the
  CLI returns with two independent, fail-closed gates:
  - **Structural:** the sequence must contain the exact generated role profile,
    optionally preceded by the known v2.2.7 global defaults, and followed only
    by deny-only hardening that still preserves every required capability
    (reading `src/app.py`, `.env.example`, implementer pytest/git-status shell).
    Any unexpected later `allow`/`ask` is rejected, whether or not its glob
    looks disjoint. Unrecognized action names fail.
  - **Semantic:** every `allow`/`ask` whose winning region may overlap an
    explicit mandatory deny must be neutralised by a later deny. Overlap is
    decided by a product walk over the glob patterns (including OpenCode's
    optional trailing-space rewrite), never by a finite list of sample paths.
- `probe_opencode_config()` uses this evaluator instead of set membership and
  requires exactly one matching agent whose `mode`, `system` and `description`
  match the generated role. Missing, malformed, duplicate-id, contradictory or
  unvalidatable normalized permissions make Doctor fail.
- A fixture captured from the real v2.2.7 binary keeps all three role profiles
  accepted, and real Doctor introspection reports `ready: true`. A wrapper that
  appends `read src/* allow` to the genuine output makes all three CLI profile
  checks and Doctor's readiness fail. Application permissions are explicitly
  **not** claimed as OS-level isolation.
- Scope note: this closes ordering/overlap certification. It does not change
  tool-level semantics (for example, `grep` asserts its pattern rather than
  each file it reads) or widen the existing shell deny globs; those are separate
  policy/tool contracts, not exceptions to this validator.

### P2-01 — partial token totals
- `total_status` now distinguishes `reported`, `derived` and `partial` for
  OpenCode steps and generic provider output.
- Known components are preserved; an incomplete derivation is marked
  `partial`, including legacy usage records with no status.
- `record_usage`, `merge_usage`, `usage_report` and the human usage line
  propagate the status (`~` for derived, `(partial)` for incomplete).
- No subscription quota or monetary spend is inferred.

### P2-02 — scoped command exceptions
- A scoped exception is ignored when no project identity is supplied; the
  command remains rejected (`policy: explicit`). Global `scope: "*"` behavior
  is unchanged.

## 3. Before/after reproduction (same long-lived process, fake Node)

Probe: `/tmp/opencode/delta-probe/probe.py` against `814758b` and the current
tree. No model calls.

| Finding | Before (`814758b`) | After |
|---|---|---|
| P1-01 | `toolchain_changed: false` (Node v1 hash reused after in-place v2 upgrade) | `true` |
| P1-02 | findings/evidence/amendments/source `omitted` | all preserved; evidence paths/hashes retained |
| P1-03 | adversarial later-allow profile `accepted: true` | `false` |
| P2-01 | `tokens=13`, `total_status: null` | `tokens=13`, `total_status: partial` |
| P2-02 | scoped exception allowed without project | rejected (`explicit`) |

The new regression file also fails 24/28 tests on `814758b` (missing APIs and
reproduced behavior) and passes on the correction commit.

## 4. Tests

- Offline suite (no model CLI execution):
  `485 passed, 4 skipped, 80 subtests passed`
- Full suite with real V2.2.7 introspection
  (`ABDULLAH_OPENCODE_V2_BIN=/tmp/ocv2/opencode`):
  `489 passed, 86 subtests passed`
- New regressions: `scripts/tests/test_delta_audit_corrections.py`
  (33 tests, 10 subtests) covering all five findings, large dirty trees,
  production reviewer context, cached accept decisions, check-tool replacement,
  legacy compatibility and adversarial permission ordering.

## 5. Real OpenCode V2 Doctor

Disposable repo; isolated config copy; no model session, no paid call.

```json
{
  "ready": true,
  "opencode_dialect": "v2",
  "worker_profiles": {"explorer": true, "implementer": true, "reviewer": true},
  "worker_profiles_cli": {"explorer": true, "implementer": true, "reviewer": true},
  "worker_profiles_cli_verified": true,
  "model_inventory": "listed",
  "paid_go_model_listed": true,
  "variant_verified": "unavailable",
  "api_billing_risk": []
}
```

Version: `opencode v2.2.7`. `variant_verified` remains `unavailable` because
V2 `models` exposes no variant catalog.

## 6. Changed files

- `scripts/orchestrator.py`
- `scripts/tests/test_delta_audit_corrections.py` (new)
- `scripts/tests/test_final_hardening.py`
- `scripts/tests/test_opencode_v2_integration.py`
- `AUDIT-EVIDENCE.md`, `DELTA-AUDIT.md` (evidence updates)

## 7. Compatibility assessment

Verified unchanged: checkout locking, process reconciliation, source-bound
verification, model routing/billing, strong Architect acceptance, material
replanning, dirty working-tree protection, existing-state compatibility and
foreground MCP control. Regression suites include `test_orchestrator`,
`test_interactive_recovery`, `test_checkpoint_*`, `test_reliability_repair`,
`test_batch1_*`, `test_final_hardening` and the delta suite.

## 8. Residual risks (non-blocking)

- V2 resource matching assumes `*` crosses path separators (`fnmatch`
  semantics). The real binary exposes no offline permission evaluator; the
  opt-in suite validates the normalized rule order, not file-system
  enforcement. This is documented in Doctor's note.
- Toolchain identity uses stat metadata (not full binary hashing) for
  performance; check executables are additionally bound per verification argv.
- Application permissions are not OS-level isolation and are not claimed as
  such.

## 9. Export the verified commit

```
git -C ~/.local/src/abdullah-orchestrator-remediation archive \
  --format=zip --prefix=abdullah-orchestrator-verified/ \
  -o /tmp/abdullah-orchestrator-verified.zip HEAD
```

`HEAD` is the final documentation commit whose tree contains code commit
`2438d32`; both are local only.

## 10. Independent delta-review handoff

Review target: `git -C ~/.local/src/abdullah-orchestrator-remediation diff
814758b..HEAD`.

Priorities:
1. Re-run `/tmp/opencode/delta-probe/probe.py` against `814758b` and `HEAD`.
2. Confirm `_bounded_context` never replaces findings/evidence/amendments with
   hashes and fails closed only when mandatory content cannot fit.
3. Confirm `validate_v2_effective_permissions` rejects later allows for
   unenumerated actions and narrow patterns, while accepting real v2.2.7
   output.
4. Confirm cached accept/integration decisions cannot reuse drifted evidence
   and that accept recovers by resetting to `verify`.
5. Confirm no changes to checkout locking, reconciliation, routing/billing,
   acceptance, replanning, dirty-tree protection or MCP surfaces.
