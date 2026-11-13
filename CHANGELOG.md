# Changelog

All notable changes to Abdullah Orchestrator are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [3.0.0] — 2026-11-13

First public release of the supervisor that passed the real end-to-end pilot
(run `20261113T104752-32561af8`). Supervisors report `SUPERVISOR_VERSION 3.0.0`,
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
- Added MIT license, contribution guide, security policy, changelog, CI, and
  issue/PR templates.

[Unreleased]: https://github.com/abdullah72005/abdullah-orchestrator/compare/v3.0.0...HEAD
[3.0.0]: https://github.com/abdullah72005/abdullah-orchestrator/releases/tag/v3.0.0
