# Model and workflow configuration

All model choices, limits, permissions, and verification policy live in one
JSON file. This page documents every field, what is actually configurable, and
which values the supervisor refuses.

## Where configuration lives

| Location | Purpose |
|---|---|
| `~/.config/abdullah-orchestrator/config.json` | Active configuration (created by the installer) |
| `scripts/config.example.json` | Shipped defaults; also the fallback when no active config exists |
| `ABDULLAH_CONFIG=/path/to/config.json` | Explicit override for one process or environment |

The file is read on every supervisor operation. There is no hidden model
registry: what you write here is what the supervisor uses, subject to the
validation rules below.

Start from the example:

```bash
mkdir -p ~/.config/abdullah-orchestrator
cp scripts/config.example.json ~/.config/abdullah-orchestrator/config.json
chmod 600 ~/.config/abdullah-orchestrator/config.json
```

## What is configurable — and what is not

| Setting | Configurable | Constraint |
|---|---|---|
| Codex Architect model and effort | Yes | Passed through unchanged; confirm it exists in the installed catalog |
| Claude Architect model and effort | Yes | Passed through unchanged; confirm it exists in the installed catalog |
| Explorer / Implementer / Reviewer model | Yes | Must be an `opencode-go/...` model ID |
| Explorer / Implementer / Reviewer variant | Yes | Set per role; `doctor` verifies it on V1 where the catalog exposes variants |
| Worker billing route | Declared as `go` | Other values are rejected |
| Fallback models | Yes (stored) | Automatic fallback is disabled; each use needs explicit operator approval |
| Limits, permissions, risk policy, verification | Yes | Security-critical values have fail-closed minimums |
| Worker **provider** (OpenCode Zen, Anthropic API, etc.) | **No, not in 3.0.0** | Worker routes are hard-wired to OpenCode Go |

This is deliberate: the project's cost model assumes cheap paid-Go workers
separate from the strong subscription Architect. The supervisor fails closed
instead of silently switching a worker to a billed API route. Supporting another
worker provider would be a code change (route construction, model inventory,
billing accounting, permission tests), not just a config edit.

## The configuration shape

```json
{
  "schema_version": 2,
  "architect": {
    "codex":  {"model": "gpt-6.1-sol", "effort": "high", "auth": "subscription"},
    "claude": {"model": "claude-opus-5-5", "effort": "high", "auth": "subscription"}
  },
  "workers": {
    "explorer":    {"model": "opencode-go/deepseek-v4.1-flash", "variant": "low",  "billing": "go"},
    "implementer": {"model": "opencode-go/deepseek-v4.1-flash", "variant": "high", "billing": "go"},
    "reviewer":    {"model": "opencode-go/deepseek-v4.1-flash", "variant": "high", "billing": "go"}
  },
  "fallback": {
    "enabled": false,
    "codex":  {"model": "gpt-6-luna", "effort": "medium"},
    "claude": {"model": "claude-haiku-4-5", "effort": "medium"},
    "require_per_run_consent": true
  },
  "limits": {
    "max_corrections_per_batch": 3,
    "max_batches": 12,
    "max_worker_seconds": 14400,
    "max_architect_seconds": 14400,
    "max_check_seconds": 14400,
    "max_explorer_calls_per_run": 8,
    "max_context_chars": 200000
  }
}
```

The shipped example also contains `permissions`, `verification`, `runtime`,
`authorization`, and `risk_policy` blocks; see the sections below.

## Architect models

`architect.codex` is used when a run's host is `codex`; `architect.claude` when
the host is `claude`. The route is:

```text
provider = host
model    = architect.<host>.model
effort   = architect.<host>.effort
billing  = architect.<host>.auth
```

- `auth` should stay `subscription` for the supported workflow. The supervisor
  fails closed if `OPENAI_API_KEY` (Codex host) or `ANTHROPIC_API_KEY` (Claude
  host) is set while subscription billing is declared.
- Model IDs are passed through unchanged. Verify them against the installed CLI
  catalog rather than guessing.
- `effort` is passed to the CLI as its reasoning-effort setting.

Example — move the Codex Architect to a different high-effort model:

```json
{
  "architect": {
    "codex": {"model": "gpt-6.1-sol", "effort": "high", "auth": "subscription"}
  }
}
```

## Worker models

Each worker role resolves to:

```text
provider = opencode
model    = workers.<role>.model
effort   = workers.<role>.variant
billing  = workers.<role>.billing
```

Validation requires both:

1. `workers.<role>.billing == "go"`
2. `workers.<role>.model` starts with `opencode-go/`

A different model **within OpenCode Go** is fully supported. For example, if
your catalog lists `opencode-go/glm-5.3`:

```json
{
  "workers": {
    "explorer":    {"model": "opencode-go/glm-5.3", "variant": "low",  "billing": "go"},
    "implementer": {"model": "opencode-go/glm-5.3", "variant": "high", "billing": "go"},
    "reviewer":    {"model": "opencode-go/glm-5.3", "variant": "high", "billing": "go"}
  }
}
```

Roles may use different models. A typical quota split is a cheap low-variant
Explorer and the stronger high-variant Implementer/Reviewer.

### Discovering valid IDs and variants

OpenCode V1 exposes a verbose Go catalog including variants:

```bash
opencode models opencode-go --verbose
```

OpenCode V2 lists model IDs but does not expose variants:

```bash
opencode models
```

`doctor` uses the command matching the detected dialect and reports:

| Field | Meaning |
|---|---|
| `paid_go_model_listed` | Every configured worker model appeared in the catalog |
| `variant_verified` | `true`/`false` on V1; `unavailable` on V2 |
| `model_inventory` | `listed`, `failed`, or `unavailable` |
| `route` | The exact resolved route for each role |

On V2, `variant_verified: "unavailable"` is expected and is not a failure —
variants are still passed as `provider/model#variant`, but the CLI cannot
confirm them. On V1, a missing variant makes `doctor` report not-ready.

### Why Go-only

The worker provider restriction is a safety property, not an oversight:

- paid Go is a separate, capped quota from the strong subscription Architect;
- an accidental API-key environment variable cannot silently move workers to
  billed API calls;
- usage accounting can label `go` versus `subscription` honestly.

If you need a different worker provider, treat it as a design change rather than
a config edit. It must also extend route construction, `doctor` inventory,
billing labels, and permission tests.

## Fallback models

`fallback.enabled` must remain `false`. Automatic fallback is prohibited. The
stored fallback entries are used only after a genuine rate limit or model
blocker, and only for **one** attempt explicitly authorized by the user:

```bash
python3 scripts/orchestrator.py approve-fallback <RUN_ID> --role implementer \
  --confirm approve-fallback:<RUN_ID>
```

`require_per_run_consent` documents that expectation. Approval is not an MCP
tool.

## Limits

| Key | Meaning |
|---|---|
| `max_corrections_per_batch` | Bounded correction waves before escalation |
| `max_batches` | Maximum planned batches |
| `max_worker_seconds` | Hard cap for one worker stage |
| `max_architect_seconds` | Hard cap for one Architect call |
| `max_check_seconds` | Hard cap for one verification command |
| `max_explorer_calls_per_run` | Nested Explorer budget |
| `max_context_chars` | Handoff compaction budget |

Keep the Codex MCP `tool_timeout_sec` strictly above the largest of the three
stage caps. Raising a stage cap without raising the MCP timeout lets the client
race the supervisor at the boundary.

## Permissions and risk

`permissions.allow_push`, `allow_deploy`, and `allow_production` must be
`false`. Enabling any of them fails configuration validation: those actions
require separately scoped authorization, not a blanket config flag.

`risk_policy` controls QA depth per batch risk class:

| Risk | Independent review | Minimum distinct checks |
|---|---|---|
| `mechanical` | optional | 1 |
| `ordinary` | required | 1 |
| `high` | required | 2, with a nonempty `verification_purpose` |

Unknown risk classes fail closed.

## Verification settings

- `verification.require_checks` and `require_docker_source_proof` must stay
  `true`; disabling source-bound verification is rejected.
- `verification.environment_names` lists variables whose presence and value
  hash are recorded (never raw values).
- `verification.runtime_inputs` controls the bounded manifest: `patterns`,
  `declared`, `required`, `exclude`, `max_files`, `max_total_bytes`.
- `verification.command_policy` rejects shell wrappers, interpreter strings,
  indirect Docker, and arbitrary scripts by default. Add a scoped exception only
  when necessary; see [`security-model.md`](security-model.md).

## Runtime and OpenCode versions

```json
{
  "runtime": {
    "supervisor_version": "3.0.0",
    "opencode_version": "auto",
    "opencode_supported": [">=1.18 <2.0", ">=2.2 <3.0"]
  }
}
```

- `supervisor_version`, when set, must equal the running supervisor version.
- `opencode_version` is `auto` or an explicit pin such as `2.2.7`; a pin must
  match the installed CLI.
- `opencode_supported` is the tested range list. Unknown majors and untested
  ranges are refused; the supervisor does not generate a permission contract it
  cannot verify.

## Authorization

`authorization.sensitive_cli_enabled` defaults to `false`. Enable it only when
you intend to run operator commands such as `retire`, `checkout-recover`,
`migrate-run`, `cancel`, or `--launch-missing`. `isolation_profile` must be
`host`; container isolation is not implemented and is rejected rather than
silently ignored.

## Validation rules at a glance

| Rule | Rejected value |
|---|---|
| Config schema | Newer than `2` |
| Supervisor version | When set, anything other than `3.0.0` |
| Worker billing | Not `"go"` |
| Worker model | Not prefixed `opencode-go/` |
| Fallback | `enabled: true` |
| Push/deploy/production | Any `true` |
| Verification gates | `require_checks: false` or `require_docker_source_proof: false` |
| Isolation | `isolation_profile` other than `"host"`, or container profile enabled |
| OpenCode version | Unsupported range, or a pin that does not match |

Errors are explicit and fail closed. There is no "best effort" mode.

## Changing configuration during a run

Do this **before** `orchestrator_start` whenever possible. A run records the
config hash at creation. Editing the file afterwards makes
`orchestrator.py compatibility <RUN_ID>` report `config_changed`, and the
supervisor refuses to stage or resume that run until the incompatibility is
resolved. This is intentional: acceptance evidence is bound to the
configuration that produced it.

If you must change models for future work, finish or retire the current run and
start a new one.

## Recipes

### Use a different Go model for implementation only

```json
{
  "workers": {
    "explorer":    {"model": "opencode-go/deepseek-v4.1-flash", "variant": "low",  "billing": "go"},
    "implementer": {"model": "opencode-go/glm-5.3",             "variant": "high", "billing": "go"},
    "reviewer":    {"model": "opencode-go/deepseek-v4.1-flash", "variant": "high", "billing": "go"}
  }
}
```

Then run `doctor` and confirm `paid_go_model_listed: true`.

### Use a different Claude Architect

```json
{
  "architect": {
    "claude": {"model": "claude-opus-5-5", "effort": "high", "auth": "subscription"}
  }
}
```

### Allow a longer stage

```json
{
  "limits": {"max_worker_seconds": 21600, "max_architect_seconds": 21600}
}
```

Also raise `tool_timeout_sec` in `~/.codex/config.toml` above 21,600 seconds and
restart Codex.

### Point at a separate config

```bash
ABDULLAH_CONFIG=/path/to/experiment.json \
  python3 scripts/orchestrator.py doctor --project /abs/repo
```

Keep the experiment file out of Git (the default `.gitignore` excludes
`config.json`).

## Verifying a configuration

```bash
python3 scripts/orchestrator.py doctor --project /absolute/path/to/repo
```

`doctor` is a preflight check. It validates configuration shape, CLI
compatibility, generated argv, worker permission contracts, model inventory, and
structured-output schemas. It does not authenticate, prove entitlement, or run
a model.
