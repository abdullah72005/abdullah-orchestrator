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
| Explorer / Implementer / Reviewer model | Yes | Fully qualified `provider/model-id`; prefix and declared provider must match |
| Explorer / Implementer / Reviewer provider | Yes | Any OpenCode provider; recorded as `worker_provider` |
| Explorer / Implementer / Reviewer variant | Yes | Set per role; `doctor` verifies it on V1 where the catalog exposes variants |
| Worker billing route | Yes | `go`, `subscription`, `api`, `free`, or `local`; `go` only for `opencode-go`; other routes need explicit billing and per-run authorization |
| Worker fallback | Yes (stored) | Complete exact alternate route; separate one-dispatch human consent and, for non-Go, its own `authorize-route --fallback` grant |
| Limits, permissions, risk policy, verification | Yes | Security-critical values have fail-closed minimums |
| Worker **provider** | **Yes, schema 3** | OpenCode remains the sole worker runtime; no native Codex/Claude worker backend |

This keeps the existing Go default while allowing reviewed alternatives. Every
non-Go route needs a human authorization grant before dispatch; an environment
variable is never consent. The supervisor still does not silently switch a
worker to an API-billed or remote route.

## The configuration shape

```json
{
  "schema_version": 3,
  "architect": {
    "codex":  {"model": "gpt-6.1-sol", "effort": "high", "auth": "subscription"},
    "claude": {"model": "claude-opus-5-5", "effort": "high", "auth": "subscription"}
  },
  "workers": {
    "explorer":    {"provider": "opencode-go", "model": "opencode-go/deepseek-v4.1-flash", "variant": "low",  "billing": "go"},
    "implementer": {"provider": "opencode-go", "model": "opencode-go/deepseek-v4.1-flash", "variant": "high", "billing": "go"},
    "reviewer":    {"provider": "opencode-go", "model": "opencode-go/deepseek-v4.1-flash", "variant": "high", "billing": "go"}
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
    "max_stage_seconds": 17000,
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
- For Claude, preflight resolves the effective `CLAUDE_CONFIG_DIR` and inspects
  user/project/local settings plus every configured managed settings file and
  its sibling `managed-settings.d/*.json` policy fragments (base file first,
  then non-hidden JSON alphabetically, including when the base file is absent).
  It rejects provider-managed host control
  (`CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST`), endpoint/token/helper overrides,
  model/fallback routing keys, malformed/non-object fragments and unreadable
  files or directories before spawn. Server/MDM-delivered settings that cannot
  be observed are reported as unverified, not certified. A deliberately
  authorized API/local alternate sets `auth` accordingly and uses the
  route-grant path instead.
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

## Worker models and providers

Each worker role resolves to:

```text
provider       = opencode           # worker runtime discriminator
worker_provider= workers.<role>.provider (or the model prefix)
model          = workers.<role>.model
effort         = workers.<role>.variant
billing        = workers.<role>.billing
routing fingerprint = redacted provider/config material pinned at run creation
```

Validation requires:

1. `model` is fully qualified as `provider/model-id` (split on the first `/`).
2. Any declared `provider` equals the model prefix.
3. `billing` is one of `go`, `subscription`, `api`, `free`, `local`.
4. `variant` is a string and never embedded in `model` with `#`.
5. The three required roles exist and no unknown worker roles/keys appear.
6. `billing: "go"` is accepted only when the worker provider is the unchanged
   `opencode-go` route. A non-Go provider must state `api`, `subscription`,
   `free` or `local` explicitly; missing billing is never defaulted onto an
   arbitrary remote provider.

The legacy Go configuration remains valid: omitting `provider` derives
`opencode-go` from the model prefix, and missing `billing` defaults to `go`
**only** for that provider. Migration of old records infers missing fields only
when every recorded worker route is legacy Go.

### Effective child routing

Preflight, the pinned routing fingerprint, Doctor and the spawned child share
one composition boundary for `OPENCODE_CONFIG_CONTENT`. Documented global,
project and `.opencode` config files are read in precedence order, and supported
top-level routing fields from any ambient inline config (`provider`/`providers`,
`model`, `small_model`, provider enable/disable lists) are carried into the
generated worker block. Generated agent profiles, ordered permissions and
`subagent_depth: 0` are applied last and are never inherited from ambient inline
agents or permission blocks; replaced control keys are reported as preflight
warnings. A project/global config that defines the generated
`abdullah-<role>` agent name is refused before spawn, because its extra keys
could shadow the generated controls. `{env:...}` and `{file:...}` references are
expanded against the child environment and project cwd, so a credential that the
wrapper strips is not observed as available. Malformed or unreadable
influential config still fails closed.

Authentication mode (declared env names plus their availability in the child
environment, configured key/header presence and model/variant auth settings) is
part of every routing fingerprint branch. Adding or removing a provider
credential therefore changes the pin and blocks dispatch until the run is
deliberately reviewed/migrated. Declared auth configuration is not proof of
authenticated entitlement.

For `billing: "go"`, preflight resolves the selected provider, model and variant
endpoint in documented precedence order (provider, then model, then selected
variant) and inspects package/canonical and model/provider remaps. Any custom
endpoint or remap outside the unchanged Go default is classified
`unqualified_go_route` and refused before spawn; the same route can still be
dispatched with explicit `api`/`subscription` billing and an `authorize-route`
grant. The unchanged default (no inspectable override) remains a legacy Go
subscription without a new grant. This is a configuration check, not proof of
Go settlement or entitlement.

### Billing and authorization

| Billing | Dispatch requirement |
|---|---|
| `go` | Existing Go configuration authorization; no new grant, only for the unchanged `opencode-go` route with no inspectable endpoint/package/model remap |
| `subscription` / `free` / `local` | Human `authorize-route` grant with an endpoint/auth-mode attestation; `local` needs a reviewed local endpoint; `free` with a custom endpoint must explicitly attest that endpoint |
| `api` | Human `authorize-route` grant bound to role, run and exact route |
| unknown | Rejected |

A grant is created outside the model context:

```bash
python3 scripts/orchestrator.py authorize-route <RUN_ID> --role implementer \
  --max-dispatches 3 --attest "reviewed local endpoint, no auxiliary calls" \
  --confirm authorize-route:<RUN_ID>
```

Every dispatch that preflight says needs a grant — including non-Go
`subscription`, `free` and `local` routes — atomically reserves exactly one
before spawn. Consumption is persisted in a run-scoped, independently locked
grant ledger (`route-grants/ledger.json`) keyed by grant and reservation ID, so a
parent supervisor snapshot cannot erase a nested Explorer's usage. A crash after
reservation is conservative and is not refunded; replaying the same reservation
ID does not consume twice. Grants bound call attempts, not tokens or
provider-side retries; there is no dollar cap claim. Nested Explorer dispatches
consult current durable usage before authorization and cannot exceed the run's
grant.

`doctor` reports `route_authorization_required` without treating the absence of
a per-run grant as a configuration defect—grants are run-scoped.

### Discovering valid IDs and variants

OpenCode V1 exposes a verbose catalog including variants:

```bash
opencode models --verbose
```

OpenCode V2 lists model IDs but does not expose variants:

```bash
opencode models
```

`doctor` reports:

| Field | Meaning |
|---|---|
| `route_models_listed` | Every configured worker model appeared in the catalog |
| `paid_go_model_listed` | Compatibility alias of the same result |
| `variant_verified` | `true`/`false` on V1; `unavailable` on V2 |
| `provider_availability` | Redacted configuration/availability/auth-observability per role |
| `execution_verified` | Always `false`; Doctor makes no model call |
| `route` | The resolved pinned route for each role |

On V2, `variant_verified: "unavailable"` is expected and is not a failure.
On V1, a missing configured variant makes `doctor` report not-ready.

### Worker fallback

A role may include a complete `fallback` route:

```json
{
  "implementer": {
    "provider": "opencode-go",
    "model": "opencode-go/deepseek-v4.1-flash",
    "variant": "high",
    "billing": "go",
    "fallback": {
      "provider": "opencode-go",
      "model": "opencode-go/glm-5.3",
      "variant": "high",
      "billing": "go"
    }
  }
}
```

Fallback is never automatic on rate limits, provider errors or free quota.
A human authorizes exactly one dispatch, and a non-Go fallback needs its own
separate route grant. Both steps are required; neither implies the other:

```bash
# 1. Authorize the exact configured fallback route (repeat for a non-Go route).
python3 scripts/orchestrator.py authorize-route <RUN_ID> --role implementer \
  --fallback --max-dispatches 1 \
  --attest "reviewed fallback endpoint/auth mode" \
  --confirm authorize-route:<RUN_ID>

# 2. Grant one-dispatch consent to select the fallback.
python3 scripts/orchestrator.py approve-worker-fallback <RUN_ID> --role implementer \
  --confirm approve-worker-fallback:<RUN_ID>
```

The consent is consumed only after the exact fallback passes preflight and its
grant reservation succeeds. A failed or interrupted fallback attempt still
needs new consent. Sessions never continue across routes; the Reviewer always
gets a fresh session. A Go fallback does not need a route grant but still needs
the one-dispatch consent.

### Pinned routes and provider drift

Routes, variants, billing and a redacted routing fingerprint are pinned at run
creation. Dispatch consumes those pins, including nested Explorer calls. The
observer reads the selected installed OpenCode dialect (V1 `provider.options` or
V2 `providers.settings`) and the applicable merged configuration: explicit
`OPENCODE_CONFIG`/`OPENCODE_CONFIG_DIR`, the global config directory, project and
ancestor `opencode.json(c)` files, project `.opencode/opencode.json(c)` files,
`OPENCODE_CONFIG_CONTENT`, and `/etc/opencode`. JSONC comments/trailing commas
and `{env:...}`/`{file:...}` expansion are handled. Unreadable influential
configuration fails closed for every billing class, including Go.

Changing the effective endpoint (provider, selected model or selected variant),
credential/auth mode, selected model/variant mapping or a detectable
auxiliary/fallback route changes the fingerprint. Auth-mode presence is bound in
every branch, and the observer expands references in the same child environment
the spawn receives, so an added/stripped credential is detected rather than
assumed. Preflight then rejects dispatch until the operator reviews/migrates the
run.
Editing the config after creation still makes the run `config_changed`; it never
silently reroutes. Explicit `migrate-run` initializes current routing pins and
records their source, for old schema-2 routes whose fingerprint was null.
Arbitrary plugins/gateways that cannot be inspected remain an explicit
limitation, not a universal proof.

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
| `max_stage_seconds` | One whole foreground stage (all checks plus the strong call); child timeouts are clipped to remaining time |
| `max_explorer_calls_per_run` | Nested Explorer budget |
| `max_context_chars` | Handoff compaction budget |

`max_stage_seconds` should stay below the interactive host's MCP timeout. The
default 17,000 s leaves bounded cleanup inside a five-hour (18,000 s) host
timeout. The previous per-child caps are still enforced independently.

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
    "supervisor_version": "3.1.0",
    "opencode_version": "auto",
    "opencode_supported": [">=1.18 <2.0", ">=2.2 <3.0"]
  }
}
```

- `supervisor_version`, when set, must equal the running supervisor version.
  Upgrading the supervisor therefore requires an explicit config edit; the
  supervisor does not silently reinterpret a pin. Prefer keeping runs and config
  on the same release and migrate paused runs explicitly.
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
| Config schema | Newer than `3`; schema 2 is normalized in memory |
| Supervisor version | When set, anything other than `3.1.0` |
| Worker billing | Not `go`, `subscription`, `api`, `free`, or `local`; `go` on a non-Go provider; missing billing on a non-Go provider |
| Worker model | Not `provider/model-id`, or declared provider mismatch |
| Worker variant | Embedded `#variant` or non-string |
| Fallback | `enabled: true` (strong-host automatic fallback) |
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

## Migrating a schema-2 run

Schema 3 does not reinterpret an old run automatically. Pause it, then run:

```bash
python3 scripts/orchestrator.py compatibility <RUN_ID>
python3 scripts/orchestrator.py migrate-run <RUN_ID> --backup-dir ~/backups/abdullah
```

Migration backs up `state.json` first, reconstructs routes only from the run's
recorded `model_routes`/job routes, and refuses with an actionable error when
that evidence is insufficient. In that case provide a reviewed mapping:

```bash
python3 scripts/orchestrator.py migrate-run <RUN_ID> --routes routes.json
```

`routes.json` must map `architect`, `explorer`, `implementer`, and `reviewer` to
complete historical routes. Migration never uses today's defaults, never
reroutes an active run, and invalidates verification, review, cached decisions
and check progress (including integration). Completed history is preserved and
may require new checks/decisions, not retroactive recertification. Explicit
migration also initializes a current reviewed routing pin for each worker route
(`routing_pin_source: "migration_observation"`) and records the previous value
in `migration_routing_pins`.

Rollback is explicit and uses the exact backup:

```bash
python3 scripts/orchestrator.py restore-run <RUN_ID> \
  --backup <BACKUP_PATH> --acknowledge restore
```

Before touching `state.json`, restore parses the entire backup, requires the
exact run and project identity, rejects newer schemas, and refuses running,
uncertain or active-work backups. It writes through the supervisor's atomic
persistence path and records the previous state under `restores/pre-restore-*.json`
with the backup hash and operator identity. A corrupt backup or simulated write
failure leaves the destination bytes unchanged.

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

Then run `doctor` and confirm `route_models_listed: true`.

### Use a different Claude Architect

```json
{
  "architect": {
    "claude": {"model": "claude-opus-5-5", "effort": "high", "auth": "subscription"}
  }
}
```

### Use a reviewed non-Go Implementer route

```json
{
  "workers": {
    "implementer": {
      "provider": "opencode-zen",
      "model": "opencode-zen/some-model",
      "variant": "high",
      "billing": "api"
    }
  }
}
```

Start the run, then authorize the exact route before the Implementer stage:

```bash
python3 scripts/orchestrator.py authorize-route <RUN_ID> --role implementer \
  --max-dispatches 3 --confirm authorize-route:<RUN_ID>
```

An unapproved route fails in preflight with no active job and no counted model
call.

### Allow a longer stage

```json
{
  "limits": {"max_stage_seconds": 21600,
             "max_worker_seconds": 21600,
             "max_architect_seconds": 21600,
             "max_check_seconds": 21600}
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
