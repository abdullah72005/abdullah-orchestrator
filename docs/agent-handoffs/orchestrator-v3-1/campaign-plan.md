# v3.1 campaign — one implementation batch

Status: APPROVED FOR IMPLEMENTATION. Abdullah approved the design, then requested that all work be delivered in one batch. This supersedes the earlier five-batch approval structure.

Authoritative complete brief: [batch-01.md](batch-01.md).
Approved architecture: [architecture.md](architecture.md).
Initial investigation: [investigation-evidence.md](investigation-evidence.md).

The single batch contains five internal workstreams in dependency order:

1. Acceptance integrity and source-stage invariants (AOR-01/02).
2. Explicit host and dispatch billing preflight (AOR-04/05/07).
3. Claude installation and foreground lifecycle (AOR-03/06).
4. Configurable OpenCode providers, billing authorization, pinned routes and migration.
5. Cross-cutting integration, documentation and independent-audit preparation.

The Implementer completes all five without intermediate Architect approval gates, makes focused local commits, and returns one consolidated evidence-rich report. The Architect then independently reviews the full baseline-to-HEAD diff, commits, tests, security/billing controls and final integration. Consequential design deviations still require escalation. No automated Abdullah Orchestrator, live model calls, push, merge, release, install, global configuration mutation or existing-run modification is authorized.

Baseline: `1b8e10e5c1b2c08a236b68450cb5b2a1a610416d`.
Worktree: `/home/abdullah/.local/src/abdullah-orchestrator-v3-1`.
Branch: `design/orchestrator-v3-1`.
