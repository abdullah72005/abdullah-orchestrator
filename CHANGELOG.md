# Changelog

All notable changes to Abdullah Orchestrator are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

Nothing yet.

## [1.0.0] — 2026-11-18

**First official public release.** The internal supervisor remains `3.1.0`; state
and configuration schema remain `3`; the worker report contract remains `2`. The
public product version starts at `1.0.0` and does not renumber any internal
identifier. See [docs/versioning.md](docs/versioning.md).

### Added

- `PRODUCT_VERSION = "1.0.0"` and an `orchestrator.py version` command that
  reports the public version separately from the supervisor, state/config schema,
  report contract and evidence formats. `doctor` now reports the same identifiers.
- `docs/installation.md`: supported versus unverified environments, clean install,
  Codex/Claude MCP registration, per-server timeouts, upgrade, rollback and
  uninstall, including a repeatable clean-`HOME` installation check.
- `docs/troubleshooting.md`: symptom → classified cause → exact recovery command
  for preflight, containment, checkout, evidence and report failures.
- `docs/versioning.md`: public/product, protocol, schema, contract and saved-run
  compatibility policy, including the historical v3.x tags.

### Changed

- README restructured for first use: value proposition, architecture diagram,
  capability table, quickstart, configuration, usage, tested behavior, security
  boundaries, documentation index and explicit release status.
- Validation evidence now includes the real Codex + OpenCode Go end-to-end run
  `20261116T124500-973e8c02`: planning, implementation, 44-test verification,
  interrupted Reviewer, containment, stale-provenance rewind, fresh review and
  Architect acceptance.
- Historical `v3.0.0` and `v3.1.0-audit-candidate.1` tags are retained unchanged
  and relabelled as internal milestones in the changelog narrative.

### Fixed

- **Stale-review recovery** — Review admission classifies verification
  rejections at their origin and, for environment/toolchain/check-executable
  drift on current modern evidence, performs one atomic rewind to `verify`.
  Required record/log integrity is checked first, so missing/unreadable/
  malformed artifacts block instead of being laundered into recovery.
  Implementation, source, plan, batch position, accepted history, grants and
  usage are preserved; source/plan/config/runtime/integrity/missing-evidence
  failures stay blocked with actionable diagnostics. Pre-invalidation Reviewer
  and decision caches are disarmed by a durable authority epoch. Report recovery
  is bound to the original failed job/dispatch epoch and cannot promote an old
  Reviewer after invalidation on apply or consumption; valid same-epoch recovery
  remains available.
- **AOR31-02** — Read-only source mutation and process containment are
  independent: a live escaped child retains exact `uncertain` ownership instead
  of being cleared as a blocked job, while a clean stopped mutation still blocks
  without phantom reconciliation. Ignored executable/config inputs and nested
  symlink target content now enter the write projection.
- **AOR31-01** — `billing: "go"` is restricted to the unchanged `opencode-go`
  route; non-Go providers must state billing explicitly in config, preflight and
  migration. A legacy Go consent can no longer authorize an endpoint override.
- **AOR31-03** — Every route that preflight requires a grant for — including
  non-Go `subscription`/`free`/`local` — reserves one dispatch atomically.
- **AOR31-03** — Route-grant usage lives in a separately locked run ledger keyed
  by reservation ID, so a parent Architect save cannot erase nested Explorer
  consumption and concurrent ledgers wait within configured/cancel/deadline
  bounds.
- **AOR31-01** — OpenCode routing fingerprints observe the effective
  selected-dialect V1/V2 configuration (project/ancestor/global/system, JSONC,
  env/file expansion, endpoint/auth/model/variant mapping) and fail closed on
  unreadable input.
- **AOR31-01** — Claude subscription preflight resolves `CLAUDE_CONFIG_DIR`,
  project/local and managed settings, provider-managed host control,
  endpoint/token/helper and model/fallback overrides; explicit authorized
  alternate billing routes remain available.
- **AOR31-04** — The deadline regression asserts failed verification, unchanged
  phase, no acceptance and no later worker instead of incidental timeout
  wording; production wording is retained.
- `authorize-route --fallback` authorizes the exact configured alternate route,
  separate from one-dispatch fallback consent, with a documented command
  sequence.
- Claude foreground setup emits separate destinations for host settings and the
  user-scoped MCP store, including the manual path that installs the per-server
  timeout.
- `restore-run` fully validates a backup before atomic mutation and preserves
  pre-restore state and backup provenance.

### Security

- Release audit found no credentials, private keys, session transcripts, live run
  state or personal operational paths in tracked files. Sanitized fixtures and
  engineering evidence are intentionally included.

## [3.1.0] — internal candidate (2026-11-13)

Internal engineering milestone. Tagged only as `v3.1.0-audit-candidate.1`; never
published as a stable product release. Superseded by `1.0.0`.

Closes audit findings AOR-01 through AOR-07 and adds reviewed multi-provider
OpenCode worker routes. Supervisors report `SUPERVISOR_VERSION 3.1.0`, state and
config schema `3`, and verification evidence `2`. This was an implementation
candidate for independent audit, not a published release.

### Fixed

- **AOR-01**: acceptance/integration approvals are bound before dispatch to exact
  source, plan content/revision, and verification-record bytes, then revalidated
  after return and on cached/recovered consumption. Stale approvals are durably
  invalidated instead of reused.
- **AOR-02**: read-only stages (`plan`, `diagnose`, `decision`, `integration`,
  `explorer`, `reviewer`) cannot mutate source across dispatch/completion;
  mutations block with preserved artifacts and diagnostics, including failure
  and recovery paths.
- **AOR-03**: explicit user-scoped Claude MCP registration with conflict
  detection and rollback of only the created artifact.
- **AOR-04**: new runs require an explicit controlling host; status reports host
  and resolved route separately; resume rejects contradictory hosts.
- **AOR-05**: one redacted billing/route preflight shared by Doctor and dispatch
  fails closed on subscription overrides and unreadable settings.
- **AOR-06**: Claude foreground host snippets and a whole-stage deadline that
  clips sequential checks and the strong call to remaining time.
- **AOR-07**: preflight rejection is durable with no active job or counted model
  call.

### Added

- Per-role OpenCode provider routes, exact-route variants, pinned routing
  fingerprints, and one-dispatch fallback consent.
- Human-only per-run API route grants with atomic reservations.
- Generalized model-inventory parsing and Doctor billing/auth/availability
  reporting.
- Backup-first schema-3 migration with recorded-route reconstruction, explicit
  mapping fallback, approval/check invalidation, and `restore-run`.
- Offline adversarial suites for acceptance integrity, stage invariants,
  dispatch safety, Claude setup, stage deadlines, worker routes, migration and
  full fake Claude/Codex campaign paths.

### Compatibility

- Existing Go configuration is normalized in memory; no global rewrite.
- Schema-2 paused runs require explicit migration. Historical completed history
  is preserved but is not retroactively recertified.
- Report contract v2 is unchanged.

## [3.0.0] — 2026-11-13

Early preview tag from the development series, now superseded by the `1.0.0`
public release. First supervisor to pass a real end-to-end pilot (run
`20261113T104752-32561af8`). Supervisors report `SUPERVISOR_VERSION 3.0.0`,
state schema `2`, config schema `2`, verification evidence `2`.

### Added

- Durable run state with atomic writes, an append-only engineering journal, and
  per-job dispatch/report/log artifacts.
- Nine-tool stdio MCP server: `start`, `stage`, `status`, `recap`, `interrupt`,
  `amend`, `resume`, `reconcile`, `runs`.
- Guarded process sessions with a lease pipe, descendant termination, PID-reuse
  detection, and a unified fail-closed containment gate.
- Risk-based QA: mechanical, ordinary, and high-risk policies with independent
  review and multi-check requirements.
- Verification provenance bound to source, runtime inputs, environment, config,
  toolchain fingerprints, argv, and plan revision.
- Command policy rejecting shell wrappers, interpreter strings, indirect
  Docker, and arbitrary scripts, with scoped, audited exceptions.
- Checkout lease registry with explicit `checkout-status`, `retire`,
  `checkout-recover`, and `adopt` operator paths.
- OpenCode V2 support: native `agents`/`permissions`/`shell`/`subagent`
  generation, `provider/model#variant`, `--standalone`, and effective-permission
  validation against the installed CLI.
- `recover-report` for deterministic recovery of preserved worker reports
  without a model call.
- Installer with Codex MCP registration and non-destructive skill linking.

### Changed

- Plan approval and fallback authorization are operator CLI actions, not MCP
  tools.
- Sensitive CLI actions are disabled by default and refuse model-owned worker
  contexts.
- OpenCode versions outside the tested lines (`>=1.18 <2.0`, `>=2.2 <3.0`) are
  rejected instead of assumed compatible.
- Evidence reuse re-validates provenance at review and acceptance; stale accept
  evidence resets the run to verification instead of dead-ending.
- Large optional context is compacted, but mandatory findings, amendments,
  evidence, and source identity are never replaced by hashes.

### Fixed

- Strict structured-output schemas now declare every property they require,
  including `verification_purpose` (`4a23a00`).
- The Architect decision schema now declares and requires `contract_version`,
  so strict mode can satisfy the validator (`f35e14f`).
- OpenCode report ingestion failures are classified and recoverable instead of
  collapsing into a generic error (`d80bea0`).
- V2 permission validation rejects any later `allow`/`ask` that reopens a
  mandatory deny through glob overlap.
- Toolchain identity is keyed on executable fingerprints, so an in-place
  upgrade invalidates old evidence.
- Partial token totals are marked `partial` instead of being reported as
  complete.

### Security

- Worker environments scrub common credential variables.
- Subscription billing fails closed when a provider API key is present.
- Implementer profiles deny push, destructive Git, `docker compose down -v`,
  external directories, web access, subagents, and `.env` reads.
- Verification records escaped-process scans; a survivor fails the check.

### Documentation

- Rewritten README, architecture, security model, validation, maintenance, and
  audit index.
- Added a model and workflow configuration guide covering configurable
  architect/worker models, the paid-Go worker constraint, limits, fallback, and
  recipes.
- Added MIT license, contribution guide, security policy, changelog, CI, and
  issue/PR templates.

[Unreleased]: https://github.com/abdullah72005/abdullah-orchestrator/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/abdullah72005/abdullah-orchestrator/releases/tag/v1.0.0
[3.1.0]: https://github.com/abdullah72005/abdullah-orchestrator/compare/v3.0.0...main
[3.0.0]: https://github.com/abdullah72005/abdullah-orchestrator/releases/tag/v3.0.0
