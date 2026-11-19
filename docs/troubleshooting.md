# Troubleshooting

Every symptom here maps to a real supervisor state or error string. Prefer these
documented commands over editing `state.json` — manual edits defeat the evidence
binding that makes recovery meaningful.

Start with the deterministic view:

```bash
python3 scripts/orchestrator.py runs
python3 scripts/orchestrator.py status <RUN>
python3 scripts/orchestrator.py compatibility <RUN>
python3 scripts/orchestrator.py recap <RUN> --detail developer
```

In a chat, the equivalents are `orchestrator_runs`, `orchestrator_status` and
`orchestrator_recap`. None of them make a model call.

## Installation and preflight

### `doctor` exits 2 / `"ready": false`

Read the failing key rather than retrying:

| Field | Meaning | Fix |
|---|---|---|
| `commands.<cli>` false | A required CLI is missing from `PATH` | Install it or fix `PATH`; re-run in the same shell. |
| `opencode_version_error` | Installed OpenCode is outside `>=1.18 <2.0` / `>=2.2 <3.0` | Install a tested line. Do not widen `runtime.opencode_supported` to silence it. |
| `cli_compatible.*` false | The installed CLI lacks a required flag (`--output-schema`, `--json-schema`, `--standalone`, …) | Upgrade the host/worker CLI. |
| `route_models_listed` false | A configured model is not in the installed catalog | Run `opencode models` and correct `workers.<role>.model`. |
| `api_billing_risk` nonempty | A credential would override subscription/Go billing | Unset `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / provider overrides for the session. |
| `route_authorization_required` nonempty | A non-Go route has no human grant | Grant it in your terminal (not via MCP) with `authorize-route`. |
| `worker_profiles_cli_verified` false | Effective V2 permissions could not be validated | Fix the OpenCode config; do not bypass the inspector. |

### `Configured supervisor version 'X' does not match '3.1.0'`

`runtime.supervisor_version` is an **internal protocol pin**, not the public
release. If you are on a release whose supervisor is still 3.1.0, restore that
value. Setting it to `1.0.0` is incorrect — see [Versioning](versioning.md).

### `Will not overwrite existing skill` / conflicting MCP server

The installer refuses to destroy unrelated state by design. Inspect first:

```bash
ls -l ~/.agents/skills/abdullah-orchestrator
codex mcp list
claude mcp get abdullah-orchestrator
```

Remove only the conflicting entry you actually own, then re-run the installer.
Never delete a skill or server you did not create.

### Codex appears to hang or times out at ~5 minutes

The per-server `tool_timeout_sec` in `~/.codex/config.toml` is too low. Set it
above your largest configured stage cap (default `18000`) and restart Codex. A
running session keeps its old client configuration.

### Claude stage gets auto-backgrounded

Set `CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS=0` in the user settings used by the
interactive host, and add the per-server `"timeout"` to the user MCP store, not
`settings.json`. See [Installation](installation.md#claude-code-host).

## Run lifecycle

### CLI `start` dispatched models immediately

`python3 scripts/orchestrator.py start ...` is **not** state-only. Without
`--background` it creates the run and immediately serves it, dispatching real
workers stage after stage. The MCP tool `orchestrator_start` is the state-only
path used by the interactive workflow.

If this was unintentional:

1. Let the foreground command stop, or interrupt it from another terminal with
   `python3 scripts/orchestrator.py interrupt <RUN> --reason "unintended start"`.
2. Confirm `"stopped": true` and status `paused` (or `uncertain`).
3. `reconcile` if uncertain, then inspect with `status`/`recap`.
4. Preserve or retire the run deliberately; do not delete its artifacts.

This exact mistake happened once during release validation and was contained by
the guard with no surviving processes; the run later recovered normally.

### `Checkout is already used by another non-final run`

One lease per canonical Git checkout. Inspect, then resolve with the printed
owner:

```bash
python3 scripts/orchestrator.py checkout-status --project /absolute/path
```

Only in your own terminal, with `authorization.sensitive_cli_enabled: true`:

```bash
python3 scripts/orchestrator.py retire <OWNER_RUN> --reason "..." --acknowledge <...>
python3 scripts/orchestrator.py checkout-recover --project /absolute/path \
  --owner <OWNER_RUN> --reason "..." --acknowledge <...>
python3 scripts/orchestrator.py adopt <LEGACY_RUN>
```

If the conflicting run is actually still working, stop it — never retire live
work.

### `Uncertain active dispatch: reconcile exact process/session/checkout first`

An interruption could not prove every marked process stopped. Do **not** retry or
launch a duplicate worker:

```bash
python3 scripts/orchestrator.py interrupt <RUN> --reason "inspect"
python3 scripts/orchestrator.py reconcile <RUN>
```

`reconcile` succeeds only when the containment gate proves the session, launch
record, run/job markers, check token, descendants and escaped processes are all
stopped. If no launch identity was ever persisted, you must inspect personally and
use the audited `reconcile <RUN> --launch-missing --evidence '...'` form.

### `config_changed`

The current execution policy differs from the run's recorded policy, or a
legacy run needs its original config to establish that identity. Restore the
matching policy or resolve the incompatibility using the documented adoption
or migration path. Once the run is compatible and no stage is active, an
operator can preview and apply a worker provider change with `switch-role`.
[Configuration changes and role switching](configuration.md#changing-configuration-during-a-run)

### Stage is blocked with `verification_rejection`

`status` exposes the classified cause. Stable codes include:
`provenance_drift`, `source_changed`, `plan_changed`, `config_changed`,
`runtime_inputs_changed`, `route_identity_drift`, `batch_invalid`,
`evidence_incomplete`, `record_missing`, `record_unreadable`, `reference_missing`,
`log_missing`, `log_unreadable`.

- **`provenance_drift`** (environment/toolchain/check-executable only) with
  intact evidence: `resume` then `stage`. The supervisor rewinds once to
  `verify`, keeps the old evidence for audit, and requires fresh checks plus a
  new Reviewer and acceptance.
- **Everything else**: repair the actual cause — restore the file, regenerate
  verification, restore the config, or re-plan. Recovery never manufactures
  missing evidence or reuses stale artifacts.
- If the cause is a genuinely missing artifact (for example a deleted log), treat
  it as nonrecoverable: re-run verification deliberately, do not edit the record.

Do not hand-edit `phase`, `verification`, `review` or `verification_rejection`.

### Report was rejected as unparseable

The raw worker stream is preserved. Inspect it, then let the operator run the
audited recovery only when the content is genuinely complete:

```bash
python3 scripts/orchestrator.py recover-report <RUN> <JOB>          # dry run
python3 scripts/orchestrator.py recover-report <RUN> <JOB> --apply \
  --acknowledge recover-report:<RUN>:<JOB>
```

Recovery is bound to the report's original job/dispatch authority epoch. After a
verification rewind, a late or re-applied old Reviewer report is refused even
with the exact acknowledgment — a fresh independent Reviewer is required. This is
intentional.

### `plan exceeds configured batch budget` / correction budget exhausted

The Architect produced more work than the configured limits allow, or corrections
kept failing. Raise `limits.max_batches` / `max_corrections_per_batch` deliberately,
or reduce scope. Do not loop unbounded.

### A run says `blocked` but I expected `paused`

`blocked` means the supervisor refused to proceed without new information
(evidence rejection, plan approval, diagnosis, exhausted budget). `paused` means
work stopped cleanly and is safe to resume. Read `pause_reason`; it usually names
the exact next command.

## Evidence and verification

### Verification fails although tests pass locally

Check the recorded command and its log:

```bash
python3 scripts/orchestrator.py recap <RUN> --detail developer
```

Common causes: a different interpreter (`python3` vs a venv), missing env value,
ignored runtime inputs that changed, a toolchain upgrade, or a plan argv that
differs from what you ran by hand. Evidence is bound to the *exact* recorded
snapshot; a green manual run elsewhere is not equivalent.

### `legacy_evidence`

The verification record predates evidence version 2. Re-verify, or use the
explicit audited operator command `acknowledge-legacy-evidence` with a reason. A
legacy record never reaches acceptance silently.

### Docker-based verification fails

`doctor` only reports whether `docker` exists. The supervisor additionally
requires Docker source proof (Compose/Dockerfile inputs hashed). If the project
switches Compose files or uses an indirect Docker invocation, the command policy
or provenance binding will reject it. Keep verification argv direct, for example
`docker compose run --rm test <cmd>`.

## Tests and development

```bash
# deterministic suite, no model calls
python3 -m unittest discover -s scripts/tests -v

# one module
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts/tests \
  python3 -m unittest test_v31_review_recovery -v

# opt-in real OpenCode introspection (still no inference)
ABDULLAH_OPENCODE_V2_BIN="$(command -v opencode)" \
  python3 -m unittest discover -s scripts/tests -p "test_opencode_v2_integration.py"
```

Seven skips in the default suite are expected: they are the opt-in module above.
A skip is never a pass. If the suite tries to launch a real `codex`, `claude` or
`opencode`, that is a test bug — the guard should have replaced it.

## When to stop and report

Stop and open an issue (or a private security report) if:

- containment reports a survivor it cannot kill;
- evidence is accepted after a source or runtime-input change;
- a non-Go route is dispatched without a human grant;
- a run state is newer than the supervisor supports;
- the installer overwrites something it did not create.

Do not work around these locally. See [SECURITY.md](../SECURITY.md).
