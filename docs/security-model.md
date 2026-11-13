# Security model

This document states what the workflow enforces, what it only *discourages*,
and where the trust boundary actually sits. It is deliberately conservative:
if a control is not enforced by the supervisor or the underlying CLI, it is
described as a limitation.

## Trust boundaries

| Boundary | Controlled by | Strength |
|---|---|---|
| User ↔ coordinator | Chat | User intent; coordinator cannot approve its own plan or fallback |
| Coordinator ↔ supervisor | stdio MCP | Small typed surface; nine tools |
| Supervisor ↔ workers | Guarded process session + environment markers | Strong for same-user process trees; not an OS sandbox |
| Workers ↔ project files | Generated OpenCode/Claude permissions | Application-level allow/deny; CLI-enforced |
| Worker ↔ credentials | Scrubbed environment + `.env` denies | Defense in depth; not complete isolation |
| Operator actions | CLI + typed confirmation + config gate | Same-user honor system, explicitly not cryptographic |
| Verification ↔ evidence | Provenance binding | Strong against stale or unrelated checkouts |

## What the supervisor enforces

- **No self-approval.** Plan approval and fallback authorization are not MCP
  tools. The MCP server rejects `orchestrator_approve_plan` and
  `orchestrator_approve_fallback`. Approval requires an interactive operator
  terminal and the exact typed confirmation. This is a process boundary, not
  cryptographic proof: a same-user process that allocates a TTY and types the
  token can pass it.
- **One writer per checkout.** A lease registry names one owning run per
  canonical checkout. Conflicting stages return the owner and resolution
  commands rather than racing.
- **No unguarded execution.** Model calls and verification run under a guard
  that is a session/process-group leader. If the lease pipe closes, the guard
  kills the tree.
- **No stale acceptance.** Verification evidence is bound to source, runtime
  inputs, environment, config, toolchain, argv, and plan revision. Drift
  invalidates it.
- **Decisions are bound to exact bytes.** Before an acceptance/integration
  Architect dispatch, the supervisor records source identity, plan hash/
  revision, and the SHA256 of each supervisor verification record. The binding
  is revalidated before any accepted batch, completion, cached decision or
  recovered decision. A new verification record cannot reuse an older approval;
  a stale approval is durably recorded and discarded, and fresh checks/decision
  are required.
- **Read-only stages cannot write source.** Planner, diagnosis, decision,
  integration, Explorer and Reviewer dispatches compare HEAD, index, tracked
  dirty files and untracked source between dispatch and completion (and again
  when consuming cached/recovered reports). A mutation blocks progression,
  preserves every artifact and reports changed paths/hashes without content or
  automatic rollback. A pre-existing dirty tree is allowed if unchanged. This
  is boundary observation, not OS write prevention: a same-user write restored
  to identical bytes before observation is not detected.
- **Explicit host and shared billing preflight.** New runs require an explicit
  `codex` or `claude` host; resume refuses a contradictory host. One
  deterministic preflight is shared by dispatch and `doctor`. It rejects
  observable subscription overrides (API keys, endpoints, Bedrock/Vertex/
  Foundry/Mantle/AWS provider flags, settings helpers, unreadable settings)
  and unapproved non-Go worker routes before an active job or model call is
  recorded. Rejections are durable `preflight_rejected` diagnostics with no
  phantom job.
- **Worker routes are pinned and granted.** Per-role OpenCode providers are
  allowed only with explicit billing classification. API/usage routes need a
  human-only, per-run grant; reservations are consumed atomically before spawn
  and collapse conservatively after a crash. Effective provider configuration
  changes are detected by a redacted fingerprint and require operator review.
  There is no dollar/token cap claim and no automatic fallback.
- **No silent downgrade.** A missing model, variant, subscription, or supported
  CLI version fails visibly; the supervisor does not fall back to a free model
  or an API-billed route.
- **No model-owned sensitive actions.** `adopt`, `retire`,
  `checkout-recover`, `acknowledge-legacy-evidence`, `migrate-run`, `restore-run`,
  `cancel`, `approve-plan`, `approve-fallback`, `authorize-route`,
  `approve-worker-fallback`, and `--launch-missing` refuse to run when
  `ABDULLAH_JOB_ID`, `ABDULLAH_RUN_ID`, `ABDULLAH_CHECK_TOKEN`, or parent-job
  markers show a worker context. Sensitive CLI commands are also disabled by
  default via `authorization.sensitive_cli_enabled: false`; human-only approvals
  additionally require an interactive TTY and exact typed confirmation.

## Worker permissions

Generated profiles are role-specific.

**Read-only roles (Explorer, Reviewer)**

- allow: read, glob, grep
- deny: edit, shell/bash, subagent/task, external directories, web fetch/search,
  questions (V2)
- deny reads of `.env` and `.env.*`; `.env.example` remains readable

**Implementer**

- broad local trust: file edits, shell, Docker, and test commands
- denies: `git push`, `git clean`, `git reset --hard`, `git filter-branch`,
  `git gc --prune`, `docker compose down -v`, `docker ... push`, external
  directories, web access, subagents, `.env` reads
- V2 uses ordered rules and the supervisor validates the CLI's *effective*
  permission set. Any later `allow`/`ask` that reopens a mandatory deny —
  including through glob overlap — makes `doctor` fail.

V1 cannot express every pattern-level denial. V1 relies on the documented tool
restrictions plus OS isolation for credential files. The supervisor refuses to
generate a profile for an unrecognized version rather than guessing.

**Claude host.** Architect and Implementer runs use
`--permission-mode bypassPermissions`; read-only roles use `plan`. This is a
Claude CLI capability boundary, not an OS sandbox; use a dedicated account for
valuable repositories.

## Environment scrubbing

Worker and verification environments remove variables whose names end in
`API_KEY`, `_TOKEN`, `_SECRET`, `_PASSWORD`, `_PASSWD`, `PRIVATE_KEY`,
`CLIENT_SECRET`, `SECRET_ACCESS_KEY`, `SESSION_TOKEN`, `_ACCESS_KEY_ID`,
`_DATABASE_URL`, or `_REDIS_URL`, plus known exact names (`DATABASE_URL`,
`REDIS_URL`, `MONGO_URL`, `MONGODB_URI`, `DOCKER_AUTH_CONFIG`, `SSH_AUTH_SOCK`,
`PYPI_TOKEN`). Credential-bearing URL variables are removed too.

If `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` is set while subscription billing is
configured, the supervisor fails closed rather than risk silent API billing.
`doctor` reports the same risk.

## Command policy

Verification runs argv arrays with no shell. The shipped policy rejects:

- shell wrappers and wrapper binaries (`bash -lc`, `sh -c`, `env`, `timeout`,
  `sudo`);
- interpreter string evaluation (`python3 -c`, `node -e`);
- indirect Docker execution and arbitrary script files;
- malformed argv.

Unusual checks require an explicit, scoped exception with a non-model
`authorized_by`. Exceptions are recorded in evidence with the exact command.
Disabling a rejection requires the documented `unsafe_acknowledged` string.

**This filters known-obfuscated invocation forms only.** It does not prevent an
allowed command from touching files, the network, or credentials.

## Secret handling in the repository

- `.env`, `.env.*`, runtime configs, run state, logs, and bytecode are
  gitignored.
- `scripts/config.example.json` contains model identifiers and limits, no
  credentials.
- Test fixtures come from a real isolated pilot run. They contain paths under
  the original operator's home directory but no secrets; they are immutable
  evidence with recorded SHA-256 values.
- The test suite never launches a real `codex`, `claude`, or `opencode`
  process; a guard raises if a test tries.

## Known limitations

1. **Same-user trust.** A shell-capable process with the same OS account can
   edit the config, import the module, or invoke the CLI. Stronger isolation
   requires a dedicated user or container.
2. **Application permissions.** OpenCode/Claude permission rules are enforced
   by those CLIs, not the kernel. A malicious project can still abuse an
   allowed command.
3. **Containment detection is same-user and `/proc`-based.** A process that
   clears its environment, changes user, or hides in another namespace may
   escape the survivor scan. Container-internal survivors are not visible on
   the host unless the token is passed and the namespace is shared.
4. **`runtime_inputs.complete` is bounded.** It means discovered/declared inputs
   were hashed without truncation and required inputs were found. It is not a
   proof of the complete runtime dependency graph.
5. **No exactly-once side effects.** Recovery restores state and preserves work;
   it cannot undo an external action already taken.
6. **Daemonized descendants.** A child that calls `setsid` after its parent exits
   may be undetectable without cgroups; treat it as a limitation and reconcile
   by hand.
7. **`doctor` is preflight.** It does not authenticate, prove entitlement, or
   execute a model. Provider availability/auth observability are redacted and
   may be unavailable; `execution_verified` remains false.
8. **Billing enforcement is application-level.** Route grants bound supervisor
   dispatch attempts. They do not bound token cost, provider-internal retries,
   auxiliary provider calls, custom plugins/gateways, or tariff changes. A
   provider named `ollama` may serve a remote/cloud model; local classification
   requires an explicitly reviewed endpoint attestation. Do not claim a hard
   dollar cap or universal provider-side fallback prevention.
9. **Boundary snapshots are not continuous immutability.** A same-user process
   can write and restore identical bytes between observations. Read-only source
   checks certify observed dispatch/completion state, not an OS sandbox.

## Recommended deployment

For anything valuable:

- run under a dedicated WSL/Linux user without production credentials;
- keep the repository and run state inside that user's home;
- use a container or VM for untrusted projects;
- leave `allow_push`, `allow_deploy`, and `allow_production` false;
- review the plan's checks before approval;
- keep the MCP timeout above the largest configured stage cap.

## Reporting a vulnerability

Do **not** open a public issue for a suspected vulnerability. Follow
[`SECURITY.md`](../SECURITY.md).
