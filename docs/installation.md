# Installation

This guide installs Abdullah Orchestrator v1.0.0 from a fresh clone, verifies it
without spending a model call, and shows how to upgrade, roll back and uninstall.

If anything here fails on your platform, treat it as a release blocker rather
than improvising around it — see [Troubleshooting](troubleshooting.md) for the
exact recovery commands.

## 1. Supported environments

| Environment | Status | Notes |
|---|---|---|
| **WSL2 Ubuntu + Codex CLI + OpenCode V2 + OpenCode Go** | **Verified** | The configuration used for the real end-to-end run. |
| Linux (x86_64) + Codex CLI | Supported | Same code paths; specific distributions are not individually certified. |
| Linux/WSL + Claude Code CLI | **Experimental** | Registration, snippets and stage deadlines are fake-CLI tested; authenticated long stages, Esc/cancel and reconnect are not live-certified. |
| OpenCode V1 (`>=1.18 <2.0`) | **Experimental** | Source-backed and fixture-tested; no live V1 binary was available for this release. |
| Alternative OpenCode providers (non-Go) | **Experimental** | Policy, grants and fail-closed routing are tested with fake CLIs; live provider settlement is not. |
| Native Windows (PowerShell/cmd) | Unsupported | Use WSL2. |
| Native macOS | Untested | The supervisor is stdlib Python and may work, but no release validation exists. |
| Managed configuration delivery (system policy files) | Linux only | Not certified on macOS/Windows. |

**Python:** 3.10 or newer. CI runs the deterministic suite on 3.10, 3.12 and
3.13. The primary local validation used 3.10.12.

**No package installation.** The runtime is the Python standard library plus the
external `git`, `codex`/`claude` and `opencode` CLIs you already use. There is no
`pip install`, wheel, npm package or background service.

## 2. Prerequisites

```bash
python3 --version        # 3.10+
git --version
codex --version          # or: claude --version
opencode --version       # must be >=1.18 <2.0 or >=2.2 <3.0
```

Authentication is yours to arrange before preflight:

- **Codex host:** sign in with your ChatGPT/Codex subscription. Keep
  `OPENAI_API_KEY` out of the environment for the orchestrator session if you
  intend to use subscription billing — `doctor` reports this as a billing risk.
- **Claude host:** sign in with the Claude CLI.
- **Workers:** an OpenCode Go subscription (default), or an alternative provider
  you explicitly authorize per run.

The supervisor never reads or stores model credentials. It scrubs API-key
environment variables from worker environments and fails closed when a route
would move work to unexpected API billing.

## 3. Install

```bash
git clone https://github.com/abdullah72005/abdullah-orchestrator.git
cd abdullah-orchestrator
git checkout v1.0.0          # pin the release you intend to run
python3 scripts/install_wsl.py --register-codex
```

What the installer does, and does not do:

| Action | Detail |
|---|---|
| Skill links | `~/.agents/skills/abdullah-orchestrator` and `~/.claude/skills/abdullah-orchestrator` symlink to this checkout. |
| Config | Copies `scripts/config.example.json` to `~/.config/abdullah-orchestrator/config.json` **only if absent**, mode `0600`. |
| Codex registration | With `--register-codex`, runs `codex mcp add` only when the server is not already registered. Restart Codex afterwards. |
| Claude registration | `--register-claude` uses the official CLI, is idempotent, refuses conflicts and rolls back only its own partial artifact. |
| Overwrites | Never overwrites an existing skill, unrelated symlink, config or conflicting MCP server. |
| Network / models | Makes no model call and performs no inference. |

Common variants:

```bash
python3 scripts/install_wsl.py --no-claude            # Codex discovery only
python3 scripts/install_wsl.py --register-claude      # Claude MCP registration
python3 scripts/install_wsl.py --no-claude --register-codex
```

Where the skill lives is exactly the directory you cloned. Moving or deleting
that checkout breaks the symlinks; re-run the installer from the new location.

### Per-server MCP timeout (required for long stages)

Codex defaults to a 300-second tool timeout, which is shorter than a legitimate
Architect or Implementer stage. Add a **server-scoped** timeout and restart
Codex:

```toml
# ~/.codex/config.toml
[mcp_servers.abdullah-orchestrator]
command = "python3"
args = ["/absolute/path/to/abdullah-orchestrator/scripts/orchestrator.py", "mcp"]
tool_timeout_sec = 18000
```

`18000` seconds (five hours) deliberately exceeds the default whole-stage cap
(`limits.max_stage_seconds = 17000`) and per-child caps (`14400`). If you raise
the stage caps, raise this value above them too. Do not set it globally for every
MCP server.

### Claude Code host

```bash
python3 scripts/install_wsl.py --register-claude
```

Then merge the printed snippets yourself:

- `CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS=0` in user settings
  (`~/.claude/settings.json` or `$CLAUDE_CONFIG_DIR/settings.json`), so a
  foreground stage cannot be auto-backgrounded.
- A `"timeout": 18000000` entry for `abdullah-orchestrator` in the user MCP store
  (`~/.claude.json` or `$CLAUDE_CONFIG_DIR/.claude.json`). `claude mcp add` does
  not install a per-server timeout.

The installer deliberately never rewrites host settings. Verify with
`claude mcp get abdullah-orchestrator` and `/mcp` inside Claude Code.

## 4. Configure

The installer already copied `scripts/config.example.json` to
`~/.config/abdullah-orchestrator/config.json`. Edit the model IDs there; this
complete example is the minimum that passes the shipped validator:

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
  "fallback": {"enabled": false},
  "limits": {"max_stage_seconds": 17000, "max_worker_seconds": 14400},
  "permissions": {"allow_push": false, "allow_deploy": false, "allow_production": false},
  "verification": {"require_checks": true, "require_docker_source_proof": true},
  "runtime": {"supervisor_version": "3.1.0", "opencode_supported": [">=1.18 <2.0", ">=2.2 <3.0"]}
}
```

Do not change `runtime.supervisor_version` to the public release number: it pins
the internal protocol version (`3.1.0`). See [Versioning](versioning.md).

Resolve real model IDs, then preflight:

```bash
opencode models opencode-go --verbose   # V1
opencode models                         # V2
python3 scripts/orchestrator.py doctor --project /absolute/path/to/dev/repo
python3 scripts/orchestrator.py version
```

Expected `doctor` fields on a ready host: `"ready": true`, `"api_billing_risk":
[]`, `"route_authorization_required": []`, `"opencode_dialect": "v2"` and one
resolved route per role. Full reference: [configuration.md](configuration.md).

## 5. First run

Open one Codex chat (the verified configuration uses Luna Medium as the visible
coordinator and `gpt-6.1-sol` high as the Architect) and invoke:

```text
$abdullah-orchestrator
```

Provide an absolute project path and a precise goal. The skill will call
`orchestrator_start` once, then exactly one stage per foreground call. You do not
need to paste supervisor commands yourself.

> [!WARNING]
> Do not use `orchestrator.py start` from a shell for this step. Unlike the MCP
> tool, the CLI form runs the supervisor loop and dispatches real models
> immediately unless `--background` is given. See
> [troubleshooting](troubleshooting.md#cli-start-dispatched-models-immediately).

## 6. Verify the installation without spending a model call

```bash
cd /path/to/abdullah-orchestrator
python3 -m compileall -q scripts
python3 -m unittest discover -s scripts/tests -v      # offline, fake CLIs
python3 scripts/orchestrator.py version
python3 scripts/orchestrator.py doctor --project /absolute/path/to/dev/repo
```

Optional, still no inference — real OpenCode binary introspection:

```bash
ABDULLAH_OPENCODE_V2_BIN="$(command -v opencode)" \
  python3 -m unittest discover -s scripts/tests -p "test_opencode_v2_integration.py"
```

### Clean-environment check

The following was executed for this release and is safe to repeat; it proves the
installer does not touch your real home or global Codex/Claude configuration:

```bash
tmp=$(mktemp -d)
HOME="$tmp/home" XDG_CONFIG_HOME="$tmp/home/.config" \
  python3 scripts/install_wsl.py --no-claude
HOME="$tmp/home" python3 scripts/orchestrator.py version
HOME="$tmp/home" python3 -m unittest discover -s scripts/tests -p "test_release_version.py"
rm -rf "$tmp"
```

## 7. Upgrade

The installation is a symlink to your checkout, so upgrading is a Git operation
followed by a preflight. Your config and run state are separate and untouched.

```bash
cd /path/to/abdullah-orchestrator
git fetch --tags
git status --short                 # stop if you have local changes you care about
git checkout v1.0.0                # or a newer release tag
python3 -m unittest discover -s scripts/tests
python3 scripts/orchestrator.py doctor --project /absolute/path/to/dev/repo
```

Finish or migrate active runs before changing versions. `python3
scripts/orchestrator.py compatibility <RUN>` reports `current`, `legacy`,
`migration_required`, `supervisor_changed`, `config_changed` or
`unsupported_newer`. Schema migrations are explicit, backup-first, and refused
for active or uncertain runs.

## 8. Roll back

```bash
cd /path/to/abdullah-orchestrator
git checkout <previous-tag-or-commit>
python3 -m unittest discover -s scripts/tests
python3 scripts/orchestrator.py doctor --project /absolute/path/to/dev/repo
```

If the rollback changes the state schema expectations, restore a migrated run
only from its exact backup:

```bash
python3 scripts/orchestrator.py restore-run <RUN_ID> \
  --backup <BACKUP_JSON> --acknowledge restore
```

Keep `~/.config/abdullah-orchestrator/config.json` and the state directory intact
during code rollback. See [maintenance.md](maintenance.md) for archives.

## 9. Uninstall

```bash
codex mcp remove abdullah-orchestrator          # if registered
claude mcp remove abdullah-orchestrator --scope user   # if registered
rm ~/.agents/skills/abdullah-orchestrator
rm ~/.claude/skills/abdullah-orchestrator
rm -r ~/.config/abdullah-orchestrator
rm -r ~/.local/state/abdullah-orchestrator
rm -r ~/.local/state/abdullah-orchestrator-checkouts
```

Then delete the checkout. Back up anything under the state directory that you
need to audit first; it contains run journals, reports and verification logs.
Nothing else on the system was modified by the installer.
