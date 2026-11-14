# Initial Architect investigation evidence

Date: 2026-11-13. Scope: source investigation and disposable diagnostics only. No production edits or model calls.

Worktree `/home/abdullah/.local/src/abdullah-orchestrator-v3-1`, branch `design/orchestrator-v3-1`, HEAD `1b8e10e5c1b2c08a236b68450cb5b2a1a610416d`. Source clean at start. New planning documents are uncommitted. Upstream GitHub main matched HEAD on read-only ls-remote. Expected d80bea0 is ancestor; scripts byte-identical between audit's 32c6fdf and current base.

## Offline baseline

Command: `python3 -m pytest -q scripts/tests`
Interpreter: Python 3.10.12.
Exit: 0.
Actual output: `575 passed, 4 skipped, 235 subtests passed in 207.45s (0:03:27)`.
Not the same skip distribution as supplied audit (574/5); collected total remains 579. No claim that other interpreters or opt-in installed-CLI tests ran. CI's canonical runner remains unittest; implementation briefs require it.

## Independent disposable probes

Command: `python3 /tmp/ao-v31-probe.py`, exit 0. Script imports the baseline ControlTests fixture, uses its temporary Git repo/state/config/registry, runs real supervisor checks, patches only strong_call to supply a decision and mutate a fake node executable outside project source, then cleans up. No real model binary launched. This is a diagnostic reproduction, not a newly implemented regression test.

AOR-01: set integrate with a two-batch plan; combined checks run `git status --porcelain`; fake strong approval rewrites temporary node on the unchanged PATH. Observed:

```
status: complete
load_verification_evidence on same record/current snapshot:
Verification provenance drifted since the check: toolchain. Re-run verification instead of reusing stale evidence.
```

This independently reproduces multi-batch final stale completion on baseline. Single/intermediate late-drift cases are source-confirmed and audit-reported, not separately executed in this initial investigation; Batch 1 must add executable coverage for all.

AOR-07: same isolated fixture, clear active_job; set disposable OPENAI_API_KEY; call architect plan through call_model with Codex route. Guard rejects before spawn. Observed:

```
error: OPENAI_API_KEY is set: verify subscription billing before launching Codex Architect
active_job.status: dispatched
active_job.pid: null
```

Confirms phantom active job independently, including the Codex equivalent of the audit's Claude reproduction. No key value emitted. AOR-02..06 verified by source inspection and official documentation where relevant; no claim of separate live reproductions or authenticated compatibility.

## Review readiness and unresolved evidence

Full independent audit received in chat and read completely. Its original ZIP/probe scripts and authenticated pilot raw artifacts remain unavailable. The historical in-repo audit documents were examined for existing compatibility/provenance/permission controls. Architecture document records authoritative sources and boundary locations. Drafts were checked for missing placeholders, contradictory approvals, unintended production diffs and forbidden actions. No implementation commits, push, install, release, existing-run writes or skill modifications performed.

All AOR findings remain OPEN pending implemented regressions and independent batch review. New OpenCode provider routes remain DESIGN ONLY. Real authenticated Claude foreground/cancel/reconnect and new provider routes remain UNVERIFIED and need separately authorized bounded tests.
