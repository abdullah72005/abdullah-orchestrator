# Batch 01 acceptance evidence

**Architect verdict — CONDITIONAL PASS.** The local candidate passed the
complete deterministic gate and independent review of the material findings.
Authenticated end-to-end host evidence remains open for this candidate.

| Git identity | Revision |
| --- | --- |
| Starting checkout and observed GitHub main | `70d7c3773e883e97a45e29c665adafccc218ff1e` |
| Accepted chat-reporting follow-up in that baseline | `720dd7c` |
| Final candidate on `feat/verified-parallel-orchestration` | `bfa77f2407900e0155aceaa66b3d1398e63bdbc6` |
| Verified scripts tree | `697ed99589a626f23bba7a31605c4d90422350eb` |

The baseline contains v1.2.0 and its chat-reporting follow-up. It already
provided model pins, replanning, review attribution, verification, the stage
viewer, checkout containment, and scoped billing. Batch 01 extends those
components and keeps the existing supervisor, state and config schemas and
report contract. At acceptance it kept the packaged product version 1.2.0; the
v1.2.1 publication changes only that public version.

## Engineering outcome

- **Verification.** The formal supervisor result can satisfy final acceptance
  when the approved commands, candidate, plan, environment, executable and
  command logs still match. Source changes, missing or altered evidence,
  explicit repeat requirements, or uncovered checks force fresh verification.
  The Reviewer can request focused checks and corrections. An integrated
  parallel result gets one formal check on the combined canonical source.
- **Progress.** Existing journal, terminal and stage payloads show observed
  milestones, role and assignment, elapsed time, the last observation, and
  next action. Worker reports are distinguished from supervisor outcomes.
  Quiet intervals use coalesced heartbeats and the informational 45-minute
  checkpoint. The observer and replay paths make no model dispatches.
- **Parallel writers.** One writer is the default. The run can authorize up
  to three, and the Architect assigns the smallest useful set. The supervisor
  binds isolated worktrees to a pinned base, checks actual patch ownership,
  and integrates exact bytes under a durable before/after proof. Tests cover
  two and three writers, one-writer selection, dirty checkout fallback,
  overlap, blocked and failed siblings, cancellation with three active
  lanes, exact-after resume, same-ID replans, preserved evidence, and one
  fresh review of the combined checkout. Recovery fails visibly when it
  cannot prove safe continuation. Unreproducible dirty bases use one writer.
- **Skills.** Explicit selections are resolved by role or writer, shown once
  and pinned to run-scoped content. Deterministic fixtures exercise bundle
  expansion, missing and changed artifacts, effective tool capabilities,
  resumed writers, and a fresh read-only Reviewer. Delivery uses the
  existing prompt transport with bounded pinned instructions.
- **Authority.** Preflight groups missing grants and tools before dispatch
  and uses the effective route. Known approved paths are noninteractive.
  A recognized authorization prompt becomes a durable blocker with scoped
  next steps. Tests exercise real local check and child containment, exact
  ledger accounting, one-shot fallback, no-child refusal replay and resume
  with completed sibling work preserved. Provider billing is represented by
  fixtures.

The implementation stays in the current supervisor and its run artifacts.
Prepared integration evidence and final checkout scans add local work to
support an exact recovery boundary. Stable proof reuse avoids additional
scratch work on ordinary matching recovery.

## Verification and independent disposition

```bash
env -u ABDULLAH_OPENCODE_V2_BIN PYTHONDONTWRITEBYTECODE=1 \
  python3 -m unittest discover -s scripts/tests -v
PYTHONPYCACHEPREFIX=/tmp/abdullah-v121-pycache/manual-bfa77f2 \
  python3 -m compileall -q scripts
git diff --check 70d7c37..bfa77f2
git diff --exit-code bfa77f2 -- scripts
```

The full gate exited 0 in 2,338.90 seconds. Unittest discovered 1,342 cases,
with 1,332 passes, zero failures or errors, and ten documented OpenCode V2
binary opt-in skips. Compileall and both Git checks passed. The full gate
completed once on the final source. Five earlier revisions had interrupted
full attempts while material findings were open.

Earlier findings covered false integration completion, missing recovery
identities, lost prior lane evidence, late dispatch binding, prior proof
access, and malformed coordinates. The final Reviewer independently
confirmed the four focused R14 recovery cases, including preservation and
corrected resume, and reported no confirmed product blocker. The concurrent
group's combined lifecycle case failed once at verification. Three runs with
unique disposable run IDs passed in 29.383 seconds and the unmodified case
passed inside the full gate. Shared fixture run IDs are a plausible cause.
The failed check's log was unavailable after cleanup, so the cause remains
unconfirmed.

## Host coverage and timing

The Linux terminal observer rendered while a fixture worker was active. The
probe captured 21 samples and exactly one fixture call each for Architect
planning and implementation. The full suite exercised MCP progress before
completion, quiet periods, cancellation, resumed stages, and replay. Prior
real CLI and desktop host behavior is recorded in the
[live-progress evidence](../live-progress/README.md). Candidate authenticated
host rendering, native pinned skill loading and provider credential
interactions remain unverified.

The ordinary comparison used the same disposable starting commit
`c39df5ba80214163c312d7015100e63dd28a6c18` and resulting tracked diff SHA-256
`f682389e28968088a02afefaafb0bce5fd3fc4f05cdec14b66d9489ce3816d81`.
Both versions reached approval with the same five fixture role calls. Each
used a real supervisor check with a deliberate three-second delay.

| Fixture measurement | Baseline | Candidate |
| --- | ---: | ---: |
| Active wall time including fixture setup | 26.209 s | 25.596 s |
| Human wait | 0 s | 0 s |
| Architect planning | 1.53 s | 1.76 s |
| Architect acceptance stage | 6.21 s | 2.97 s |
| Explorer | 2.88 s | 3.29 s |
| Implementer | 3.74 s | 4.48 s |
| Reviewer | 3.58 s | 3.86 s |
| Formal verification stage | 4.03 s | 4.13 s |
| Parallel integration and correction | 0 s | 0 s |
| Required suite executions through acceptance | 2 | 1 |

The acceptance stage includes any final verification it performs. The
candidate avoided one redundant execution. These single fixture samples ran
under different load. They establish check reuse and the approval outcome.

The candidate's two-writer recovery fixture completed in 8.719 seconds, with
no human waiting. Implementation stages measured 2.20 seconds before the
blocked result and 2.66 seconds for resumed work including integration.
The final integration recorded 1.30 seconds for the writer interval and
0.40 seconds of integration work. Verification took 1.04 seconds, review
1.14 seconds, and strong acceptance 0.96 seconds. The three-writer
implementation fixture recorded 2.60 seconds of writer wall time and
0.47 seconds of integration. Elapsed time uses the writer group interval
so overlapping attempts count once.

An authenticated disposable baseline previously reached approval with two
executions of its three-test required check. A comparable authenticated
candidate run was outside the manual handback. Live or parallel speedup
remains unmeasured.

## Local handback and publication

At acceptance the candidate commits were local, GitHub main was at the observed
baseline, and no push, deployment or release publication had occurred. This
note remains the acceptance-time record with the verified code/test revision
intact. The v1.2.1 publication to GitHub main uses this accepted candidate plus
the public version constant, its assertions and documentation, as recorded in
[`CHANGELOG.md`](../../../CHANGELOG.md). No tag, GitHub Release or deployment is
part of that action.
