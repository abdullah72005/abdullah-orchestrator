# Versioning and compatibility

Abdullah Orchestrator has **five independent version identifiers**. Confusing
them is the most likely way to break an installation, so this page states exactly
what each one controls.

| Identifier | Current value | Where it lives | What breaks if you change it |
|---|---|---|---|
| **Public product version** | `1.2.2` | Git tag / GitHub release / `PRODUCT_VERSION` / `orchestrator.py version` | Nothing at runtime. It names the published release. |
| **Supervisor protocol version** | `3.1.0` | `SUPERVISOR_VERSION`; pinned in `runtime.supervisor_version` | A pin mismatch refuses to run; saved runs record it and report `supervisor_changed`. |
| **State schema version** | `3` | `state.json` → `schema_version` | Older state needs an explicit, backup-first `migrate-run`; newer state is refused. |
| **Config schema version** | `3` | `config.json` → `schema_version` | A newer config schema is refused rather than silently reinterpreted. |
| **Worker report contract** | `2` | report JSON `contract_version` | Legacy or wrong-contract reports cannot masquerade as fresh evidence. |

Two additional internal formats are versioned for evidence only:
`SOURCE_PROVENANCE_VERSION = 3` and `VERIFICATION_EVIDENCE_VERSION = 2`.

Check them on any installation:

```bash
python3 scripts/orchestrator.py version
```

```json
{
  "product": "abdullah-orchestrator",
  "product_version": "1.2.2",
  "supervisor_version": "3.1.0",
  "state_schema_version": 3,
  "config_schema_version": 3,
  "report_contract_version": 2
}
```

## Why the public version starts at 1.0.0

Earlier tags (`v3.0.0`, `v3.1.0-audit-candidate.1`) were **internal engineering
milestones** used while the protocol and the safety model were still being
audited. The first release intended for public use is therefore `v1.0.0`.

That reset applies to the *product*, not to the machinery:

- The internal supervisor remains `3.1.0`, because existing configuration pins
  that value and saved runs record it.
- State/config schema stay `3`, so no migration is triggered by the release.
- The worker report contract stays `2`, so live workers and fixtures remain
  compatible.
- Verification evidence format stays `2`, so prior evidence keeps its meaning.

No production code compares Git tags. There is no update check, no "latest
release" lookup and no version ordering between the public and internal numbers.
A `v1.0.0` checkout therefore cannot be treated as "older than v3.0.0" by the
supervisor. The only version comparison that exists is the strict equality pin
between `runtime.supervisor_version` and `SUPERVISOR_VERSION`, plus state/config
schema ordering.

## Historical tags are immutable

| Tag | Meaning | Status |
|---|---|---|
| `v3.0.0` | First complete internal workflow, validated by a real pilot | Preserved; never moved |
| `v3.1.0-audit-candidate.1` | Internal v3.1 audit candidate | Preserved; never moved |
| `final-audit-baseline`, `final-hardening-checkpoint` | Internal checkpoints | Preserved; never moved |
| **`v1.0.0`** | **First public release** | Immutable release tag |
| **`v1.2.2`** | **Antigravity, autonomous progression and bounded test fan-out** | Release tag and GitHub Release published |
| `v1.2.1` | Verified parallel orchestration | Historical; published on `main` without a tag |
| `v1.2.0` | Workflow and review-evidence release candidate | Historical local candidate; never moved |

Tags are never force-moved or deleted. If a release must be corrected, publish a
new patch tag rather than rewriting an existing one.

## What a public release does *not* change

Upgrading from an internal v3.x checkout to `v1.0.0`:

- keeps `~/.config/abdullah-orchestrator/config.json` valid as-is;
- keeps existing `state.json` runs at schema 3;
- keeps the same CLI and MCP tool names;
- keeps the same tested OpenCode ranges (`>=1.18 <2.0`, `>=2.2 <3.0`);
- does not rename, delete or rewrite run directories.

What you should update is your **checkout**: prune and check out the release tag,
then rerun `doctor`. See [Installation](installation.md#7-upgrade).

## Compatibility status values

`python3 scripts/orchestrator.py compatibility <RUN>` is read-only and returns:

| Status | Meaning | Safe action |
|---|---|---|
| `current` | Supervisor, config and state versions all match | Continue. |
| `legacy` | Older schema or supervisor, migration possible | Plan a backup-first `migrate-run`. |
| `migration_required` | Schema must be migrated before staging | `migrate-run`, then inspect the backup path. |
| `supervisor_changed` | State was written by a different supervisor version | Finish the run with its original checkout, or accept the documented risk; do not mix versions silently. |
| `config_changed` | Config was edited after the run started | Restore the pinned config or start a new run. |
| `unsupported_newer` | State is newer than this supervisor | Upgrade the code; do not downgrade the state. |

## Version policy going forward

- **Patch (`1.0.x`)** — documentation, tests and non-behavioral fixes. No schema
  or contract change.
- **Minor (`1.x.0`)** — additive features; may add optional config fields. Any
  state/config migration ships with `migrate-run` and a rollback path.
- **Major (`2.0.0`)** — breaking changes to CLI/MCP surface, schemas or contracts.

The supervisor protocol version may advance independently of the public version.
When it does, the release notes state the new pin and any migration step; the
public tag alone is never the source of truth for compatibility.
