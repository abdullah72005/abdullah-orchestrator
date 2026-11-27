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
| Antigravity Architect model/effort/billing | Yes (opt-in) | `architect.antigravity` is absent by default; effort must stay `high`; a missing `agy`/unsupported value blocks dispatch |
| Configure Models view / future-run defaults | Yes | `orchestrator_models`/`models` is read-only; `set-default` previews then applies atomically with a backup and typed confirmation |
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

The complete, validator-clean starting point is
[`scripts/config.example.json`](../scripts/config.example.json). The excerpt below
shows the fields that matter most; it omits `permissions`, `verification`,
`authorization` and `risk_policy`, which the shipped file includes. Later recipes
show individual keys to merge into your config, not standalone files.

```json
{
  "schema_version": 3,
  "architect": {
    "codex":  {"model": "gpt-6.2-sol", "effort": "high", "auth": "subscription"},
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
    "max_grant_lock_wait_seconds": 5.0,
    "max_context_chars": 200000
  }
}
```

The shipped file is the authoritative complete example; use it directly, then
edit only the values you need.

## Architect models

`architect.codex` is used when a run's host is `codex`; `architect.claude` when
the host is `claude`; `architect.antigravity` when the host is `antigravity`. The
route is:

```text
provider = host
model    = architect.<host>.model
effort   = architect.<host>.effort
billing  = architect.<host>.auth
```

Antigravity is opt-in and **not live-certified**: the shipped example omits
`architect.antigravity`, existing Codex/Claude configs remain valid, and a run
that names `antigravity` without the entry is refused with an actionable error.
The installed `agy` version must advertise the adapter's required headless
tokens; a missing CLI or unsupported model/effort is a blocker, not a fallback.

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
- `effort` is passed to the CLI as its reasoning-effort setting. The persistent
  Architect pin must be `high`: new configured defaults and run/switch
  selections at another effort are refused before any state or billable work.
  Medium is available only through the explicitly scoped
  `ordinary_planning_trial` for an ordinary initial plan. A legacy run pinned
  below High keeps its historical route, but the protected dispatch guard
  refuses acceptance/diagnosis/integration; remediate it with a read-only
  `switch-role` preview/apply to the same model at `high` (or create a new run).

Example — move the Codex Architect to a different high-effort model:

```json
{
  "architect": {
    "codex": {"model": "gpt-6.2-sol", "effort": "high", "auth": "subscription"}
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

Preflight and the spawned child share one immutable prepared launch context:
the resolved executable/version identity, project cwd, scrubbed child
environment, generated `OPENCODE_CONFIG_CONTENT`, and the effective routing
observation. `cli_command` does not regenerate inline bytes from ambient
variables after approval; a final source re-observation after dispatch
snapshots blocks and refunds an attempt whose material changed.

The supported source boundary is version-aware:

- **V1.18.35** uses the bounded source adapter, matching the pinned upstream
  loader: global `config.json` then `opencode.json` then `opencode.jsonc`;
  explicit `OPENCODE_CONFIG`; project `opencode.json(c)` from the Git worktree
  root downward; project `.opencode` directories nearest-first (outermost wins);
  `$HOME/.opencode`; late `OPENCODE_CONFIG_DIR`; inline content; Linux managed
  files. Relative explicit/custom-directory paths are resolved against the
  child's project cwd, not the supervisor's cwd. V1 `debug` initialization can
  write schema/dependency files, so it is not executed for billing inspection.
  The adapter accounts for native provider/model `api` URLs, `npm`/SDK and
  `modelID`/`id` remaps, and refuses nested provider routing shapes it does not
  model. The SQLite account store is resolved with the supported V1
  database-path contract: an absolute `OPENCODE_DB` is used as-is, a relative
  one is joined under `Global.Path.data` (`XDG_DATA_HOME` verbatim, otherwise
  `$HOME/.local/share`, plus `opencode`), `:memory:` is an ephemeral store, and
  the default name follows the compiled channel (`opencode.db` for release
  channels, `opencode-<channel>.db` for preview builds;
  `OPENCODE_DISABLE_CHANNEL_DB` forces `opencode.db`). Variables upstream does
  not honor, including `OPENCODE_DATA_DIR`, cannot divert the scan; an
  unresolvable boundary is `unprovable_routing`. The store is opened read-only
  and only routing-relevant account metadata (account id/email/url, active
  account/organization, legacy control-account presence/active) is projected
  into the route pin. Session/history rows, SQLite layout and whole-file churn
  remain separate physical audit observations; token column values are never
  selected or decoded, and the whole-file audit digest never enters a route pin.
  Automatic plugin files under applicable
  global/project `.opencode/plugin(s)` directories are discovered, hashed and
  refused as uninspectable code. A declared plugin list alone is not a complete
  plugin boundary.
- **V2.2.7** uses the installed binary's ordered, non-inference
  `debug config --standalone` documents. That normalizer walks project config
  from the filesystem root (including a parent above the Git root), applies
  ordered provider settings/model/variant overlays, and retains disjoint legacy
  and native provider ids. A failed, malformed, timed-out or plugin-skipped
  inspection is `unprovable_routing`; it is never a source-adapter authorization
  fallback. Account/remote/integration or managed routing that cannot be
  observed is likewise unprovable rather than an implicit default route. On
  macOS, managed preferences are included only through the supported normalizer.
- The source adapter's ordered presence/absence, raw file digests, expansion
  dependencies, inline routing bytes, normalized routing, inspector entry
  identities and executable identity are all bound into the routing material.
  Inspection results are never reused from a cache across observations.
- Supported top-level routing fields from ambient inline config
  (`provider`/`providers`, `model`, `small_model`, enable/disable lists) are
  carried into the generated worker block. Generated agent profiles, ordered
  permissions and `subagent_depth: 0` are applied last and are never inherited
  from ambient inline agents or permission blocks; replaced control keys are
  reported as preflight warnings. A project/global config that defines the
  generated `abdullah-<role>` agent name is refused before spawn.
  `{env:...}` and `{file:...}` references are expanded against the child
  environment and project cwd; an unresolved endpoint/remap expansion is
  unprovable, while a stripped credential is not observed as available.
  Malformed or unreadable influential config fails closed.

Authentication mode (declared env names plus their availability in the child
environment, configured key/header presence and model/variant auth settings) is
part of every routing fingerprint branch. Adding or removing a provider
credential therefore changes the pin and blocks dispatch until the run is
deliberately reviewed/migrated. Declared auth configuration is not proof of
authenticated entitlement.

For `billing: "go"`, preflight resolves the selected provider, model and variant
endpoint in documented precedence order (provider, then model, then selected
variant) and inspects package/canonical, native V1 `api`/`npm`, and
`modelID`/`id`/provider remaps. Any custom endpoint or remap outside the
unchanged Go default is classified `unqualified_go_route` and refused before
spawn; the same route can still be dispatched with explicit
`api`/`subscription` billing and an `authorize-route` grant. The unchanged
default (no inspectable override) remains a legacy Go subscription without a new
grant only when the applicable source boundary — including account metadata and
automatic plugin sources — is fully observed. A V2 inspector failure, a
plugin/account hazard or any version-boundary failure is `unprovable_routing`; it
never becomes a Go approval. This is a configuration check, not proof of Go
settlement or entitlement.

Variant configuration is dialect-specific. V1 keeps a dictionary keyed by
variant id; supported V2 uses an array of objects such as
`{"id": "low", "settings": {"baseURL": "..."}}`, and the selected entry is
applied last. A present-but-uninspectable `variants` value (wrong type,
non-object entries, missing/blank ids or duplicate ids) fails closed as
`unprovable_routing`; it is never treated as an unchanged Go default. When a
well-formed array simply lacks the selected id, there is no variant override to
apply; the documented V2 behavior is a model-resolution error, not a silent
repoint of the route.

### Billing and authorization

| Billing | Dispatch requirement |
|---|---|
| `go` | Existing Go configuration authorization; no new grant, only for the unchanged `opencode-go` route with no inspectable endpoint/package/model remap |
| `subscription` / `free` / `local` | Human `authorize-route` grant with an endpoint/auth-mode attestation; `local` needs a reviewed local endpoint; `free` with a custom endpoint must explicitly attest that endpoint |
| `api` | Human `authorize-route` grant bound to role, run and exact route |
| unknown | Rejected |

Every new OpenCode grant must bind a resolved material pin. An unpinned or stale
schema-3 route is refused with guidance to create a new run or explicitly run
`migrate-run`; the supervisor never auto-repins or grandfathers a label-only
grant. A strong-host (`codex`/`claude`) route keeps its separate label identity
contract. The same binding is required at grant consumption, including worker
fallback.

A grant is created outside the model context:

```bash
python3 scripts/orchestrator.py authorize-route <RUN_ID> --role implementer \
  --max-dispatches 3 --attest "reviewed local endpoint, no auxiliary calls" \
  --confirm authorize-route:<RUN_ID>
```

Every dispatch that preflight says needs a grant — including non-Go
`subscription`, `free` and `local` routes — atomically reserves exactly one
before spawn. Ledger waits are bounded by `limits.max_grant_lock_wait_seconds`
(default 5 seconds) and the remaining stage deadline, poll at most every 50 ms,
and distinguish lock contention, stage expiry and cancellation from missing or
exhausted authorization. Consumption is persisted in a run-scoped, independently locked
grant ledger (`route-grants/ledger.json`) keyed by grant and reservation ID, so a
parent supervisor snapshot cannot erase a nested Explorer's usage. A crash after
reservation is conservative and is not refunded; replaying the same reservation
ID does not consume twice. Grants bound call attempts, not tokens or
provider-side retries; there is no dollar cap claim. Nested Explorer dispatches
consult current durable usage before authorization and cannot exceed the run's
grant.

The grouped permission preflight uses the actual route policy: default host
subscription and unchanged OpenCode Go routes need no new grant, while API and
non-Go OpenCode `subscription`/`free`/`local` routes do. It also checks route and
approved-check executables under the scrubbed check environment, role/writer
skill tools, pinned skill artifacts, check argv policy and parallel prerequisites.
Plan approval checks the whole approved run; resume blocks only on pending-stage
requirements, so a completed paid role's exhausted grant is visible as deferred
rather than blocking unrelated acceptance work. A parallel fan-out must reserve
one run-ledger reservation per admitted lane before any lane starts; a failed
reservation releases prior reservations whose launch was never attempted and
produces zero launches. The surfaced parallel-grant remedy requests one new
exact-route grant covering the full admitted writer count.

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

On V2, `variant_verified: "unavailable"` is expected and is not a failure: the
V2 `models` command does not list variants. Configured variants are still read
by preflight from the V2 array form above. On V1, a missing configured variant
makes `doctor` report not-ready.

Metadata boundaries:

- Model/effort checks use bounded, read-only probes and never a model turn:
  Codex `app-server` `model/list`, OpenCode V2 `api --standalone get /api/model`,
  OpenCode V1 `models --verbose`, and the Claude `--effort` help contract.
- A probe runs in the project it describes. A Codex catalogue observed in one
  project is never reused for another project or host; the short-lived cache is
  scoped by host, resolved project, executable identity and dialect.
- Pagination is bounded. If the page budget ends before the catalogue is
  exhausted, absence of a model from the visited pages is reported `unavailable`
  — never `unsupported`.
- A nonempty effort/variant must match a canonical effort name or an exact
  provider-defined variant name in the catalogue. A typo is `unsupported` and is
  refused before a run is created or a route is switched, including with
  `--allow-unverified-metadata`; that flag only covers genuinely missing
  metadata.
- Confirmed, unsupported and unavailable stay distinct. Missing metadata is
  never treated as proof of support, and no probe changes credentials.

### Per-run routes and role switches

Inspect every role and effective pin without changing anything:

```bash
python3 scripts/orchestrator.py models            # defaults + architect hosts
python3 scripts/orchestrator.py models <RUN_ID>   # this run's effective pins
```

The same data is the MCP `orchestrator_models` tool. It distinguishes the
host-managed conversation model from the dispatched Architect and reports
provider, model, effort/variant, billing and metadata availability. Three
operations stay separate: change shared defaults with the validated
`set-default` preview/apply below (future runs only; existing pins and valid
evidence are untouched), pass per-run `routes` for one new run, or use
the preview/apply switch below at an existing safe boundary. A stale preview, an
active-stage switch, an unsupported selection or an unauthorized provider/billing
change is rejected.

```bash
# Future-run default: read-only preview first, then apply atomically with a backup.
python3 scripts/orchestrator.py set-default --role implementer \
  --route '{"model":"opencode-go/glm-5.3","variant":"high","billing":"go"}'
python3 scripts/orchestrator.py set-default --role implementer \
  --route '{"model":"opencode-go/glm-5.3","variant":"high","billing":"go"}' \
  --apply --confirm 'set-default:implementer:<PROPOSAL_SHA12>'
```

A billing-route change additionally requires `--accept-billing-change`. The
Architect default must stay High, and `set-default` refuses a model-owned worker
context; a configuration edited after the preview makes the confirmation stale.

Configuration holds defaults. A run pins its resolved routes at creation;
changing the config later does not rewrite them. To select different routes for
one run, pass the same role-keyed object at creation:

```json
{
  "architect": {"model": "gpt-6.2-sol", "effort": "high", "billing": "subscription"},
  "implementer": {"model": "opencode-go/glm-5.3", "effort": "high", "billing": "go"},
  "reviewer": {"model": "opencode-go/deepseek-v4.1-flash", "effort": "max", "billing": "go"}
}
```

```bash
python3 scripts/orchestrator.py start --project /absolute/repo --host codex \
  --goal-file goal.txt --routes routes.json
```

`start` begins the run immediately; the MCP `orchestrator_start` tool accepts
the same `routes` object and creates the run without dispatching a model.

Omitted fields inherit the current pinned route during a switch, not the current
global defaults. A provider change requires a complete route (model, provider,
effort, billing) so consent is never inherited by accident.

Role switching is human-only and works at a safe boundary (no active job/check,
no uncertain state, no unreconciled retry or exploration), and only while the
run's saved execution policy is compatible with the current configuration. A
genuine policy change (`limits`, permissions, verification, unknown keys) is
refused at preview and again under the apply lock; resolve it with
`compatibility` and, when appropriate, `migrate-run` or
`adopt-config-policy`. Preference-only changes do not block a switch.

```bash
# 1. Read-only preview: proposed vs pinned route, metadata, downstream effects
python3 scripts/orchestrator.py switch-role <RUN_ID> --role reviewer \
  --route '{"model":"opencode-go/deepseek-v4.1-flash","effort":"max","billing":"go"}'

# 2. Apply with the exact confirmation value from the preview
python3 scripts/orchestrator.py switch-role <RUN_ID> --role reviewer \
  --route '{"model":"opencode-go/deepseek-v4.1-flash","effort":"max","billing":"go"}' \
  --apply --confirm 'switch-role:<RUN_ID>:reviewer:<PROPOSAL_SHA12>'
```

Apply is opt-in with `--apply`; omitting it is a read-only preview. Apply is
backup-first, generation-bound and preserves plan, checks, accepted history
and unaffected grants. It refuses a route whose current preflight is
incompatible (for example unprovable OpenCode routing or invalid billing). A
grant that must be obtained separately is reported as `requires_grant`; obtain
it with `authorize-route` after the switch, because grants bind the exact route
and role generation.

A Reviewer switch discards pending review/decision authority and repeats review
on the pinned evidence. For a batch whose effective risk policy exempts
independent review (mechanical), the supervisor-generated verification and
acceptance phase are preserved; only the dependent acceptance decision is
reissued. An Architect switch requires High for protected decisions, clears
pending verdicts and bumps the authority epoch. If it changes the pinned route
while an ordinary Medium planning trial is still pending, the preview and the
saved state both mark that trial `ineligible_route_drift` immediately; the
Architect route itself is not changed by the trial.

The ordinary planning trial is available only for a Codex-host run declared
ordinary. It validates Medium and High on the exact resolved subscription
model, pins that route's provider/model/effort/billing, uses Medium only for the
initial plan, and keeps acceptance, replans, diagnosis and integration on the
pinned High route.

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
Editing execution policy after creation makes the run `config_changed`.
Role-selection defaults can change while existing runs keep their pinned routes.
Explicit `migrate-run` initializes current routing pins and records their source
for old schema-2 routes whose fingerprint was null.
Arbitrary plugins/gateways that cannot be inspected remain an explicit
limitation, not a universal proof.

## Automatic progression and consultation

Automatic progression is supervisor policy for ordinary runs and does not depend
on risk, complexity or writer count. A valid plan is admitted and the coordinator
continues through `next_action` without a user approval step. Corrections,
verification, replanning and supported recoverable failures do not ask the user
to continue. Explicit pause/cancel, unresolved sensitive authorization,
credentials/external access and irreducible technical blockers remain stopping
conditions.

`plan_approval: true` at start (or an explicit later request) is the only
consultation gate. The user's exact reply is recorded in the controlling
conversation:

```bash
python3 scripts/orchestrator.py consult <RUN_ID> --response "Use SQLite." --decision amend
python3 scripts/orchestrator.py consult <RUN_ID> --response "Looks good."       # classified
```

MCP equivalent: `orchestrator_consult`. A material reply creates a versioned
amended plan; accepting the unchanged proposal needs no `approve-plan` command.
A reply bound to a superseded plan revision or amendment epoch is rejected.
Consultation never grants paid-route, destructive, deployment, credential or
external-access authority.

`status`, `stage` and `resume` expose the same bounded `progression` view:
`automatic`, `consultation_required`, recovery classification and the recorded
next action.

### Run-scoped routine-check exceptions

The supervisor may admit an ordinary non-destructive plan check (for example
`python3 -m unittest ...`) through a run-scoped exception bound to the run,
checkout, plan revision and exact argv, with recorded provenance. It revalidates
relevant executable/runtime identities before use, and it never edits shared
configuration or another saved run. It cannot authorize paid routes, destructive
actions, deployment, credentials or external access; shell wrappers are never
auto-excepted. A manual exception is a human-only action: `authorize-check`
requires an interactive operator terminal, refuses a model-owned worker context,
and accepts only the exact typed confirmation shown below.

```bash
python3 scripts/orchestrator.py check-exceptions <RUN_ID>
python3 scripts/orchestrator.py authorize-check <RUN_ID> --argv '["python3","-m","unittest"]' \
  --reason "planned deterministic check" --authorized-by "operator" \
  --confirm check-exception:<RUN_ID>:<SHA12>
```

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

## Parallel writer permission and explicit skills

`max_parallel_writers` is a **start-time per-run permission**, not a config
default: `orchestrator_start` accepts `max_parallel_writers: 1..3` and the CLI
accepts `--max-parallel-writers 1..3`. The default is one. The strong Architect
still chooses the actual count (one to three) through optional per-batch
`writers` assignments; the effective count is capped by the permission and falls
back to one with a durable reason when the starting checkout is not reproducible.
Batch `writers` entries are validated for stable IDs, nonempty goal/completion
criteria, exact relative paths or component prefixes and pairwise overlap. An
explicit one-writer assignment uses the ordinary single-writer path. Isolated
worktrees, per-lane intent/attempt provenance, one admitted transaction source
identity, integration identities and recovery artifacts live under the run
directory; the canonical checkout is written only after a scratch dry run over
the exact tree/index state. A recorded completed full apply is never repeated; an
unrecognized, unreadable or foreign transaction blocks before model dispatch. An
operator commit or unexpected index/worktree change after admission preserves
every lane and blocks for explicit reconciliation instead of starting a lane on a
new base. Only a `complete` lane report may enter the candidate;
`blocked`/`needs_architect` reports preserve their partial work and are retried or
diagnosed without granting a partial patch candidate authority. Durable lane
execution uncertainty is checked even when the parent label says failed, so no
cleanup, fallback or replacement launch occurs until the old execution is proven
stopped.

A sibling-only apply after a writer failure is recorded as `sibling_recovery` with
the full expected writer set; it can never authorize verification. A crash before
the normal single-writer recovery save resumes through single-writer recovery.

A parallel fan-out reserves one run-ledger reservation per admitted lane before
any model dispatch, replays the same reservation id idempotently inside the lane,
and releases reservations whose launch was never attempted. A short grant
requests one new exact-route grant for the full admitted count because admission
does not combine multiple grants.

The optional `skills` config object bounds explicit skill routing:

```json
"skills": {
  "roots": ["/absolute/path/to/skills"],
  "max_skills_per_role": 6,
  "max_instruction_bytes": 32768,
  "max_resource_bytes": 131072,
  "max_total_bytes": 163840,
  "bundles": {
    "superpowers": [
      "using-superpowers",
      "brainstorming",
      "writing-plans",
      "verification-before-completion"
    ]
  }
}
```

`roots` is optional; the supervisor also checks `ABDULLAH_SKILLS_ROOT`, the
project's `.abdullah/skills`, the skill directory and configured user roots.
Skills are only resolved when explicitly named in the start request. Missing,
ambiguous, oversized, changed or path-escaping content fails visibly. Required
tools are checked against the exact role and adapter capability, not just the
supervisor's PATH: Reviewer/Explorer roles are read-only, so a skill requiring
shell, edit, network or subagent access fails there, and an OpenCode Implementer
is bound to its deployed deny rules for subagent/network/restricted shell actions
rather than being treated as full-access. Skill prose never authorizes a tool.
Selected content is copied into the run with SHA-256 identities and injected into
the role/writer prompt; changing the original source after start does not change
the pinned copy, and a missing/changed pinned artifact fails preflight for the
affected pending role. Native per-adapter skill loading is not claimed; the
fallback is explicit and persisted.

## Ordinary planning trial

`orchestrator_start` / `orchestrator.py start` accepts
`ordinary_planning_trial: true` (CLI: `--ordinary-planning-trial`) with
`planning_trial_risk: "ordinary"` (CLI: `--planning-trial-risk`). This is an
explicit declaration made **before** dispatch, not an automatic downgrade:

- it requires a pinned Codex Architect route at `high` with `subscription`
  billing and catalogue confirmation that its model supports Medium and High;
- only the initial plan uses Medium effort; the Architect route itself is not
  mutated and saved runs keep the route they pinned;
- a plan containing high-risk batches is not admitted — resume for a fresh High
  plan;
- replans, consequential diagnosis, integration and final acceptance remain
  High, and a Medium fallback cannot satisfy them.

If the risk is unknown, do not opt in. Historical runs and expressly pinned
routes keep their existing behavior.

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
  match the installed CLI. The supervisor validates the **resolved executable's**
  reported version against the tested ranges and the pin before it generates or
  authorizes a prepared permission profile. A pin is a constraint, not evidence
  of the installed dialect: a mismatch, unsupported actual version, failed version
  query or missing executable is `unprovable_routing` and never falls back to the
  pinned dialect.
- `opencode_supported` is the tested range list. Unknown majors and untested
  ranges are refused; the supervisor does not generate a permission contract it
  cannot verify. Cold version and configuration inspection run inside the same
  whole-stage deadline, cancellation and process-tree containment as dispatch.

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

Do this **before** `orchestrator_start` whenever possible. A run records both
the raw config digest and a semantic policy fingerprint at creation.

- **Role-selection preferences are excluded from execution policy.** Changing an
  Architect model/effort/auth default, a worker `provider`/`model`/`variant`/
  `billing`/`fallback`, or a fallback model does not change the policy
  fingerprint: those values are already pinned per run and are not silently
  adopted. The raw digest remains recorded for audit.
- **Any other key is policy**, including unknown keys and formatting-sensitive
  values. Editing limits, permissions, verification, runtime or an unrecognized
  key makes `orchestrator.py compatibility <RUN_ID>` report `config_changed`,
  and the supervisor refuses to stage or resume that run until it is resolved.
  This is intentional: acceptance evidence is bound to the configuration that
  produced it.

For future work, use a per-run route override (§ Per-run routes and role
switches) or switch one role at a safe boundary. You do not have to retire a
run merely to choose different models.

A run created before config-policy identity existed can adopt its exact old
config without rewriting pinned routes. This is backup-first and requires the
exact old bytes:

```bash
python3 scripts/orchestrator.py adopt-config-policy <RUN_ID> \
  --old-config /path/to/retained-old-config.json \
  --acknowledge "old config retained at /path" \
  --backup-dir ~/backups/abdullah
```

Adoption requires the old file's raw digest to match the run's recorded
digest. It records the old policy and preserves the pinned routes. If the old
policy differs from the current one, the result reports
`equivalent_to_current: false` and execution remains blocked until the policy
incompatibility is resolved.

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
python3 scripts/orchestrator.py version
python3 scripts/orchestrator.py doctor --project /absolute/path/to/repo
```

`version` prints the public release, internal supervisor, schema and contract
identifiers separately ([versioning](versioning.md)). `doctor` is a preflight
check. It validates configuration shape, CLI compatibility, generated argv,
worker permission contracts, model inventory, and structured-output schemas. It
does not authenticate, prove entitlement, or run a model.
