# Installation

This guide installs the published `v1.0.0` release or the current `v1.2.2`
release from a fresh clone. It
verifies the installation without spending a model call, and shows how to
upgrade, roll back and uninstall.

If anything here fails on your platform, treat it as a release blocker rather
than improvising around it — see [Troubleshooting](troubleshooting.md) for the
exact recovery commands.

## 1. Supported environments

| Environment | Status | Notes |
|---|---|---|
| **WSL2 Ubuntu + Codex CLI + OpenCode V2 + OpenCode Go** | **Verified** | The configuration used for the real end-to-end run. |
| Windows Codex desktop with its agent in WSL | Stage execution smoke-tested | Planning and implementation completed on a disposable WSL supervisor. Desktop Stop and fresh-thread recovery remain unverified. |
| Native Windows Codex desktop + WSL2 supervisor | GUI smoke pending | The native Codex backend discovered the skill and connected to WSL MCP. Desktop stage controls still require live validation. |
| Linux (x86_64) + Codex CLI | Supported | Same code paths; specific distributions are not individually certified. |
| Linux/WSL + Claude Code CLI | **Experimental** | Installed CLI registration and a headless stage passed with local fixtures. Authenticated interactive stages, Esc/cancel and reconnect remain unverified. |
| Linux/WSL + Antigravity CLI (`agy`) | **Not live-certified** | Opt-in guarded dispatch, capability-gated argv, stdin UTF-8 transport, terminal-report validation and conflict-safe registration are fixture-tested. `agy` was absent from the validation shell; no authenticated stage has run. |
| Windows Antigravity desktop + WSL2 supervisor | **Not live-certified** | Setup emits the verified distro/Python/checkout/state paths and a `wsl.exe` bridge; desktop registration, >180 s stage, rendering, interruption, reconnect and resume remain unverified. |
| OpenCode V1 (`>=1.18 <2.0`) | **Experimental** | Source-backed and fixture-tested; no live V1 binary was available for this release. |
| Alternative OpenCode providers (non-Go) | **Experimental** | Policy, grants and fail-closed routing are tested with fake CLIs; live provider settlement is not. |
| Supervisor running directly on Windows | Unsupported | Run the supervisor in WSL2. |
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
- **Antigravity host (opt-in, fixture-tested; live acceptance pending):** install
  and authenticate the
  Antigravity CLI. Verify `agy --version` and `agy --help`, the model catalogue,
  supported effort levels and billing classification yourself; the supervisor
  refuses dispatch unless the installed help advertises the required headless
  tokens. `agy` was not available in this release's validation shell.
- **Workers:** an OpenCode Go subscription (default), or an alternative provider
  you explicitly authorize per run.

The supervisor never reads or stores model credentials. It scrubs API-key
environment variables from worker environments and fails closed when a route
would move work to unexpected API billing.

## 3. Install

```bash
git clone https://github.com/abdullah72005/abdullah-orchestrator.git
cd abdullah-orchestrator
git checkout v1.2.2          # the current release tag
python3 scripts/install_wsl.py --register-codex
```

> **`v1.2.2` is the current release tag.**
> Check out `v1.2.2` for a reproducible install, or `main` for the latest state.
> Install the older `v1.0.0` tag only when you specifically need that tagged
> release.

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

### Windows Codex desktop with its agent in WSL

When the desktop app's **Agent environment** is WSL, use the Linux skill
location and the WSL CLI's MCP registration shown above. Open the project from
its WSL distribution, confirm skill discovery and check `/mcp` in a fresh
desktop thread. Use the Linux absolute path for `orchestrator_start`. The
Windows-native setup below includes a `wsl.exe` registration example.

The desktop smoke used a separate MCP registration that launched the disposable
WSL supervisor through `wsl.exe`. The GUI completed planning and implementation
and displayed the stage tool card. See the
[desktop smoke evidence](release-evidence/v1.2.0/README.md#native-windows-codex-desktop-compatibility).

For live worker detail, keep a WSL integrated terminal beside the desktop chat
and run the read-only observer against the same run:

```bash
python3 <SKILL_DIR>/scripts/orchestrator.py status --run <RUN_ID> --follow
```

The post-v1.2.0 Windows Codex desktop smoke verified live progress in the
integrated WSL terminal. When the terminal cannot resolve the supervisor's
fixture path directly, use `wsl.exe` with the supervisor's distribution and
run-state environment to launch the observer. Native desktop tool-card
progress remains unverified. The adjacent terminal for Claude desktop awaits a
desktop smoke. [Windows desktop result](release-evidence/live-progress/README.md#windows-codex-desktop-result)

Prepare a disposable check with
`docs/release-evidence/live-progress/desktop_fixture.py`; its README records the
exact desktop operator steps and pass criteria.

Live progress and chat reporting need no extra installation. Every stage keeps
its short before/after line in the same controlling chat, and the bounded plan
view, Reviewer findings and Architect verdict arrive as ordinary tool results.
Native in-flight rendering depends on the host: Claude Code CLI renders MCP
progress natively, while Codex CLI and Claude desktop need the adjacent
observer; Codex desktop tool-card progress is unverified. Opt-in design
consultation is a start-time choice (`plan_approval: true`), described in the
[README](../README.md#usage). See
[validation](validation.md#post-v120-follow-up-2026-11-22--2026-11-23) for the
exact observed client behavior.

### Native Windows Codex desktop

The Windows-native agent reads Windows-side Codex configuration. Keep the
supervisor and its run state in WSL. Set up the WSL CLI as above, then register
the same supervisor using Windows `wsl.exe` in a trusted desktop project's
`.codex/config.toml` or the Windows user's `%USERPROFILE%\.codex\config.toml`.
Use the actual Windows executable path, WSL distribution and Linux checkout
path. A project-local copy of the complete skill under
`.agents/skills/abdullah-orchestrator/` makes it visible to the Windows-native
agent. [Windows desktop and WSL](https://learn.chatgpt.com/docs/windows/windows-app)

```toml
[mcp_servers.abdullah-orchestrator]
command = "C:/Windows/System32/wsl.exe"
args = [
  "-d", "Ubuntu", "--cd", "/home/your-user",
  "--exec", "/usr/bin/env",
  "PATH=/home/your-user/path-to-codex-bin:/home/your-user/.opencode/bin:/usr/local/bin:/usr/bin:/bin",
  "/usr/bin/python3", "/home/your-user/abdullah-orchestrator/scripts/orchestrator.py", "mcp",
]
startup_timeout_sec = 30
tool_timeout_sec = 18000
```

In WSL, use `command -v codex` and `command -v opencode` to identify the
directories for `PATH`. The non-interactive launch can miss directories
installed by a shell startup script, such as an NVM bin directory. Restart
the desktop app after saving a user-level registration, or open the trusted
project in a fresh thread for a project-level registration. Confirm discovery
with `$abdullah-orchestrator` and `/mcp`. Pass the **Linux absolute path** of
the target project to `orchestrator_start` because it runs in WSL. The desktop
model is the coordinator. Architect and worker model choices come from the
WSL supervisor's configuration. [Codex MCP registration](https://learn.chatgpt.com/docs/extend/mcp)

Skill discovery, MCP registration, stage execution and backend interruption and
fresh-thread recovery passed through the native Windows backend. A separate
Windows-to-WSL stdio run passed host cancellation, reconnect and resume with
local fixture workers. In the desktop GUI, the stage tool card and whole-turn
duration appeared, but in-app Stop, live worker activity and fresh-thread
recovery were not exercised; the operator deferred the desktop Stop retest.
Backend/stdio cancellation evidence does not attest those UI controls.

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
[Claude Code CLI validation evidence](release-evidence/v1.2.0/README.md#claude-code-cli-compatibility)

### Antigravity CLI in WSL2 (opt-in)

Antigravity is a third controlling host. It is **fixture-tested in this release;
authenticated live acceptance is pending**. The supervisor keeps a separate
adapter: `agy` is checked against its
installed `--help` for `--print`, `--model` and `--output-format` (and
`--effort`/`--session` when used), prompts travel on stdin, and acceptance
requires a structured terminal report with a matching session, not just exit 0.

1. Confirm the installed CLI: `agy --version`, `agy --help`, a real model id,
   supported effort, authentication and billing. Keep the output for the run
   record. If `agy` is missing, Antigravity dispatch remains blocked.
2. Add an opt-in `architect.antigravity` entry yourself (the shipped example
   omits it so existing configs stay valid):

   ```json
   "antigravity": {"model": "<verified-id>", "effort": "high", "auth": "subscription"}
   ```

   Final acceptance requires `high`. Do not guess a model id or a billing class.
3. Register the stdio server in the CLI's settings file, or merge it with an
   explicit path:

   ```bash
   python3 scripts/install_wsl.py --register-antigravity \
     --antigravity-settings ~/.gemini/settings.json
   ```

   The writer only edits an existing parseable `mcpServers` object, preserves
   unrelated servers, backs up first, is idempotent and refuses conflicts. It
   does not create a guessed location or schema.
4. Keep a server-scoped timeout above `max_stage_seconds` + margin (shipped
   18,000,000 ms vs 17,000 s). `install_wsl.py` rejects an insufficient or
   non-finite bound. Do not apply it globally. The installed `agy` version's
   per-tool foreground setting could not be verified here; until it is, a
   foreground stage depends on the server bound and a real desktop stage above
   180 s remains undemonstrated.
5. Run `doctor --host antigravity` and confirm `cli_compatible.antigravity`,
   `billing_preflight` and the resolved routes before any paid dispatch.

### Antigravity Windows desktop connected to WSL2

The desktop application's own conversation must reach the supervisor inside the
Ubuntu distro. Running `agy` in the integrated terminal is **not** GUI
integration.

```bash
python3 scripts/install_wsl.py --setup-desktop
```

The output records the actual `WSL_DISTRO_NAME`, absolute WSL Python, checkout,
`~/.config` and run-state paths, and the `opencode`/`agy` executables. Register
the printed `wsl.exe -d <distro> --exec /usr/bin/env PATH=... ABDULLAH_CONFIG=...
ABDULLAH_STATE_DIR=... <python> <supervisor> mcp` entry in the desktop
application's **own MCP settings**, so a non-login shell still uses the same
isolated configuration, state and worker executables. Missing distro or CLIs are
listed as blockers; never relabel a WSL supervisor as native Windows.

Keep the desktop chat in the same conversation and let the coordinator follow
`next_action` automatically. Long-stage, progress-rendering, interruption,
reconnect and resume behavior for the desktop host are unverified until an
authenticated run passes; keep the run state for that validation.

## 4. Configure

The installer already copied `scripts/config.example.json` to
`~/.config/abdullah-orchestrator/config.json`. Edit the model IDs there; this
complete example is the minimum that passes the shipped validator:

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

Inspect every role in one place without changing anything:

```bash
python3 scripts/orchestrator.py models            # defaults and architect hosts
python3 scripts/orchestrator.py models <RUN_ID>   # effective pins for one run
```

The same view is the MCP `orchestrator_models` tool. It separates the
host-managed conversation model from the dispatched Architect. Change defaults
only for future runs, pass per-run `routes` for one new run, or use the existing
`switch-role` preview/apply at a safe boundary; none of these silently reroutes
an existing pinned run.

## 5. First run

Open one Codex chat (the verified configuration uses Luna Medium as the visible
coordinator and `gpt-6.2-sol` high as the Architect) and invoke:

```text
$abdullah-orchestrator
```

Provide an absolute project path and a precise goal. The skill will call
`orchestrator_start` once, then exactly one stage per foreground call. You do not
need to paste supervisor commands yourself. A valid plan progresses
automatically; the coordinator does not ask you to approve it unless you
explicitly requested design consultation. Startup and `status` show one real
execution-environment line such as
`Running in Ubuntu (WSL2) · Project: /home/abdullah/my-project`.

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
git fetch --tags origin
git status --short                 # stop if you have local changes you care about
git checkout v1.2.2                # current release tag; use main for latest state
python3 -m unittest discover -s scripts/tests
python3 scripts/orchestrator.py doctor --project /absolute/path/to/dev/repo
```

Release tags are `v1.0.0` and `v1.2.2`. The v1.2.2 changes, approval and evidence
are recorded in the [changelog](../CHANGELOG.md#122--2026-11-28); `main` may be
ahead of the tag as later documentation or fixes land.

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
