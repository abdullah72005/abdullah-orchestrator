# Audit trail

These documents are preserved from the pre-release engineering and audit work.
They are evidence of what was reproduced and corrected, not a claim that the
implementation is defect-free.

| Document | Date | Purpose |
|---|---|---|
| [`final-hardening-notes.md`](final-hardening-notes.md) | 2026-11-12 | Baseline findings, OpenCode V2 investigation, initial gap list |
| [`final-audit-evidence.md`](final-audit-evidence.md) | 2026-11-12 | Before/after probes: command policy, provenance drift, MCP approvals, acceptance gates |
| [`delta-audit.md`](delta-audit.md) | 2026-11-13 | Five reproduced acceptance blockers (P1-01…P2-02) and their certified fixes |
| [`../agent-handoffs/orchestrator-v3-1/`](../agent-handoffs/orchestrator-v3-1/) | 2026-11-14 → 2026-11-18 | AOR31 remediation: investigation, batch brief, three review rounds, final Architect acceptance, closure-audit handoff, and saved evidence |

## Current review gate

The AOR31 remediation and the stale-review recovery correction are
**Architect-accepted with known limitations** at
`b9819a75c10433d9e8d082e049c2a31084d0e416`, and the real end-to-end milestone
run completed on 2026-11-18. A separate third-party security/closure audit has
**not** been performed, and broader live compatibility remains unverified. Start
from the
[final E2E review](../agent-handoffs/orchestrator-v3-1/e2e-review-recovery-final-architect-review.md)
and [validation](../validation.md).

## How to read them

- **Baseline** refers to tag `final-audit-baseline` (`b71f84e`).
- **Current** in those documents refers to the tree at the time of writing;
  later commits (`4a23a00`, `f35e14f`, `d80bea0`) are recorded in
  [`../validation.md`](../validation.md).
- Probe outputs are intentionally short excerpts, not full logs. The durable
  evidence lives in the repository tests and fixtures.
- Paths such as `/tmp/probe.py` and staged binary locations describe the
  original audit environment; they are not required to reproduce the findings.

## Relationship to the test suite

Every fixed finding has a regression test. The audit documents explain *why* a
control exists; the tests prove it still works. If the two disagree after a
change, the test suite is authoritative and the document should be updated.
