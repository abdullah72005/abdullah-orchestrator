# Changelog

All notable changes to Abdullah Orchestrator are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
uses [Semantic Versioning](https://semver.org/).

## [Unreleased] — 2026-11-19

### v1.2.0 release closure

Same public `1.2.0` version and internal identifiers (supervisor `3.1.0`,
state/config schema `3`, report contract `2`, verification evidence `2`).
Additive state fields keep older runs readable.

### Added

- Versioned semantic config-policy provenance. A preference-only or
  formatting-only config edit no longer invalidates run admission or
  source-bound verification provenance; behaviour-bearing and unknown keys stay
  fail-closed. Pre-policy runs adopt metadata only from a matching old raw
  digest or an operator-supplied old config whose SHA-256 matches.
- Authoritative model metadata checks for Codex (`app-server` initialized
  `model/list`), OpenCode V1 (`models --verbose`), OpenCode V2
  (`api --standalone get /api/model`) and the Claude `--effort` contract.
  Confirmed, unsupported and unavailable stay distinct; missing metadata is
  never support.
- Run-scoped role-keyed route overrides at start (CLI `--routes`, MCP `routes`),
  with explicit billing on provider changes and metadata validation before any
  state, lease or billable work.
- Human-only `switch-role` with a read-only preview, exact-route confirmation,
  backup-first state copy, role-generation bump, journaling and invalidation of
  incompatible continuation, pending verdict/cache/recovery and fallback
  consent.
- `adopt-config-policy` backup-first operator adoption for pre-policy runs.
- Per-role generation binding for cached/recovered reports, route grants and
  fallback consent, including A→B→A switch protection.

### Fixed

- Preserve both the retained-index and rebuild rejection reasons in a writer
  limitation when both fail.
- Host fallback consent is bound to the exact pinned effective route and role
  generation instead of re-reading the current global fallback model.

### v1.2.0 release closure · correction 1

- The authenticated Reviewer smoke now asks for the real contract-v2 report and
  proves its claim from one predicate used by both launch and inspect: a
  completed, path-matched Read from the producing session carrying the hidden
  challenge line, supervisor OpenCode ingestion, unchanged candidate and intact
  prepared bindings. Missing, failed, unrelated or wrong-session Reads, blocked
  reports, drift and executed write/shell capabilities fail closed; harmless
  negative capability probes distinguish runtime refusal from normalized rules.
  The fixture is built through the attested writer-delta publication path.
- A nonempty effort/variant is matched against canonical and exact
  provider-defined catalogue names, so a typo is `unsupported` before run
  creation or switch, including with `--allow-unverified-metadata`. Model
  catalogue probes run in the target project, are cached per host/project, and
  an unfinished page budget yields `unavailable`, never authoritative rejection.
  New Architect selections lacking catalogue-confirmed High are refused at
  admission or switch.
- The ordinary planning trial validates Medium and High on the exact resolved
  run route and pins that route's provider/model/effort/billing. An explicit
  Architect switch marks a pending trial `ineligible_route_drift` in the preview
  and saved state immediately.
- Role switches inherit omitted fields from the pinned run route, refuse a
  currently incompatible preflight while distinguishing a separately required
  grant, and preserve mechanical-batch supervisor acceptance and phase when
  independent review is exempt. Ordinary/high batches still rerun the dependent
  review and decision on preserved deterministic verification.

### Changed

- The ordinary planning trial no longer uses a Sol-version literal; it requires
  catalogue-confirmed Medium and High support on the selected Codex model.
- Contributor validation guidance now uses focused checks during development
  and one complete local suite on the finalized candidate.

### v1.2.0 release closure · correction 2

- The Reviewer smoke now distinguishes an unobserved negative from a denied or
  absent capability. Only an exact shell/edit probe denied in the producing
  session, or an authoritative runtime inventory proving absence, counts; a
  generic error, another session or an unrelated command stays unverified.
  Static profile introspection is reported separately, and authenticated Read
  success remains separately attestable. Read paths resolve against the
  prepared repository to the exact hunk, not a foreign suffix.
- Launch is bound to the prepared prompt digest and the exact isolated OpenCode
  Go V2 subscription route: current pinned/effective route, policy identity,
  dialect, shipped profile, installed profile, route preflight and prepared
  evidence must all agree before inference. The completed job's dispatched
  route must match. Inspection re-derives Read and negative evidence from the
  digest-verified raw event stream, never from saved summaries alone.
- Role switching now requires compatible saved/current execution policy at
  preview and again under the apply lock, using one fresh config observation for
  the under-lock proposal and route preflight. A stale policy refusal leaves
  routes, generations, grants and evidence untouched. Preference-only changes
  still permit a switch.
- Every new persistent Architect route, including a configured default or an
  early-stage switch, must use High and a catalogue-confirmed High-capable
  model. Medium remains scoped to the explicit ordinary planning trial;
  historical under-effort pins keep the fail-closed protected dispatch guard and
  have a documented switch-to-High remediation.

## [1.2.0] — 2026-11-18

**Local release candidate.** Discrete workflow and evidence improvements over
`1.0.0`. Internal identifiers are unchanged: supervisor protocol `3.1.0`,
state/config schema `3`, worker report contract `2`, verification evidence `2`.

### Added

- Explicit Implementer `needs_architect` now routes directly to durable strong
  diagnosis carrying the question, evidence, unknowns, batch and plan identity.
  Routine attributable check failures retain one bounded cheap retry.
- User requirement amendments create a versioned strong replan. Prior plan
  authority, verification, review, verdicts, decision bindings, batch-delta
  chain and worker continuation are invalidated under the existing lock; plan,
  accepted-batch and delta artifacts remain archived and inspectable.
- Implementer and Reviewer receive one canonical `requirements` block with the
  user's exact goal and ordered amendments (IDs and kind), distinct from the
  Architect's interpretation. A plan that omits a requirement cannot replace it.
- Supervisor-owned batch boundaries capture retrievable before-images for dirty
  tracked and pre-existing untracked paths, use the recorded HEAD for pristine
  tracked paths, compare against commits/staged/worktree state, and record
  observed per-file hunks with explicit pre-existing/overlap/attribution limits.
- A digest-bound, checkout-local read-only review projection exposes acceptance
  criteria, requirements, the delta index, readable hunks and independent check
  results to the Reviewer without Implementer conclusions or raw reports.
- Codex `codex exec … -` and Claude print-mode prompts are delivered on stdin
  through the existing guard. OpenCode retains its supported positional prompt
  with byte-aware per-string and combined argv/environment checks and a
  pre-dispatch refusal path.
- Foreground stage previews and results carry local start time with offset,
  role, configured and effective model/effort, batch identity, task, expected
  output, monotonic elapsed time, outcome, blocker and next action. Recap and
  status expose the last stage.
- Run-creation `ordinary_planning_trial` opt-in (MCP and CLI) for a task declared
  ordinary before dispatch: the pinned Codex Sol 6.2 subscription route uses
  Medium for the initial plan only. High-risk trial plans are not admitted;
  replans, diagnosis, integration and acceptance stay High.
- The shipped Codex Architect default is `gpt-6.2-sol` at `high`, subscription.
- An `## Active orchestrator run` policy is delivered in each worker's effective
  input (OpenCode V1/V2 profile or Codex/Claude inline), scoping out
  `writing-plans`, `executing-plans` and `subagent-driven-development` while
  retaining systematic debugging and focused TDD.

### Changed

- A user requirement amendment no longer takes an intermediate diagnosis hop;
  a material correction that needs investigation keeps it.
- Minor-correction text references the amendment ID; the raw text stays in the
  single canonical requirements block.
- OpenCode probes validate help on the real option shape without treating the
  stdin `-` marker as an option.
- The entry skill's startup reads are optional for the ordinary loop; detailed
  operations, role and contract references are loaded on demand.

### Fixed

- Material corrections now pause at diagnosis and return to a new versioned plan
  when diagnosis finds changes required; a correction never reaches
  implementation with a null/unapproved plan, and a correction arriving while a
  clear requirement replan is pending preserves that route and both verbatim
  entries.
- Review verification recovery keeps the unchanged approved plan usable for
  fresh checks and review while still invalidating every pre-invalidation cached
  or recovered Reviewer/decision artifact.
- Review packets are bound to the exact candidate, plan revision and verification
  record, validate indexed paths/sizes/digests before reuse, are staged privately
  and published complete, and record the producing packet identity at dispatch.
- Batch-delta evidence now tracks presence/type/mode independently of bytes,
  records readable deletions, labels restored HEAD bytes as overlap, marks
  uncaptured dirty paths unavailable instead of clean, and survives an
  unreachable dispatch HEAD or comparison failure.
- Protected High acceptance/diagnosis rejects a Medium default, fallback or legacy
  decision route before dispatch without consuming one-shot consent.
- Compacted Reviewer prompts retain the verified packet root, manifest digest,
  delta-index path and check evidence; only bulky per-file lists are bounded.
- Foreground stages report the route attempted before the transition and use one
  outcome for the result, end journal and recap; the next stage comes from the
  existing preview.
- Nested Explorer uses the route-aware prompt path with canonical requirements;
  duplicate goal/amendment text is removed from Architect and Explorer contexts.

### Preserved

- Checkout ownership, guarded process containment, cancellation/reconciliation,
  route and billing preflight, one-shot fallback consent, mechanical review
  exemption, independent review for ordinary/high risk, the two-check high-risk
  minimum, source-bound acceptance and recovery of historical runs.
- Historical model pins and saved-route compatibility are not rewritten.

### Verification

- Focused v1.2.0 workflow cases plus the full deterministic suite and compile,
  version, config-policy, installation and MCP smoke checks. Exact commands,
  counts and skip reasons are recorded in
  [docs/release-evidence/v1.2.0/README.md](docs/release-evidence/v1.2.0/README.md).
  Live Medium/High quota comparisons and native terminal UX were not measured in
  this offline candidate; see that evidence file for the explicit limitations.

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

[Unreleased]: https://github.com/abdullah72005/abdullah-orchestrator/compare/v1.0.0...main
[1.2.0]: docs/release-evidence/v1.2.0/README.md
[1.0.0]: https://github.com/abdullah72005/abdullah-orchestrator/releases/tag/v1.0.0
[3.1.0]: https://github.com/abdullah72005/abdullah-orchestrator/compare/v3.0.0...main
[3.0.0]: https://github.com/abdullah72005/abdullah-orchestrator/releases/tag/v3.0.0
