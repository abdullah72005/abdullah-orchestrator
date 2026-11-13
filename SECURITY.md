# Security policy

## Supported versions

| Version | Supported |
|---|---|
| `3.0.x` | Yes |
| `< 3.0` | No |

Security fixes are applied to the latest release line. This is a local
developer tool that can run shell commands and Docker through a worker; treat
it accordingly.

## Reporting a vulnerability

**Please do not open a public issue for a suspected vulnerability.**

Use one of these private channels:

1. GitHub **Security → Report a vulnerability** (private advisory) for this
   repository, or
2. Email **abdullahhesham005@gmail.com** with a clear subject such as
   `[security] abdullah-orchestrator`.

Include:

- affected version or commit;
- platform (Linux/WSL, Python, Codex/Claude/OpenCode versions);
- a minimal reproduction or exact commands;
- the impact you believe is possible;
- whether the issue requires a malicious project, a malicious model response,
  or an already-compromised same-user process.

You can expect an acknowledgement within a few days. Please allow time for a
fix and a coordinated disclosure before publishing details.

## Scope

In scope:

- containment failures (worker survives interrupt/reconcile, PID-reuse or
  descendant handling);
- stale or forged verification evidence reaching acceptance;
- checkout-lease bypasses or cross-project ownership confusion;
- command-policy bypasses that execute a materially different command;
- permission-generation bugs that reopen a mandatory deny;
- credential leakage through logs, reports, environment capture, or prompts;
- self-approval or model-invoked sensitive operator actions;
- path traversal or symlink issues in state/artifact handling;
- report parsing that lets invalid evidence be treated as valid.

Out of scope or explicitly limited by design:

- **Application-level permissions are not an OS sandbox.** A malicious project
  abusing a command that the Implementer is allowed to run is expected behavior;
  use a dedicated user/container.
- **Same-user trust.** A process with the same OS account can edit
  `~/.config/abdullah-orchestrator/config.json`, import the module, or type an
  approval token in a TTY. The project documents this rather than claiming
  cryptographic authorization.
- **Prompt injection from project content.** Models are expected to be
  influenced by repository content; the supervisor limits *impact* through
  permissions and evidence, not through prompt immunity.
- **Unsupported CLI versions.** The supervisor refuses untested OpenCode
  ranges; reports against a version it explicitly rejects are not security
  findings unless the rejection can be bypassed.
- **Provider billing or quota behavior.** The project fails closed when it
  detects an API-key ambiguity, but it cannot control provider-side billing.

## What the project does to reduce risk

- Persists dispatch intent before launch and guards every external process.
- Binds acceptance to the exact source, environment, config, and toolchain.
- Executes verification argv directly, never through a shell.
- Scrubs credential-shaped environment variables from workers and checks.
- Removes plan/fallback approval from the MCP tool surface.
- Disables sensitive CLI actions by default and blocks them in worker contexts.
- Denies push, destructive Git, external directories, web access, subagents, and
  `.env` reads in generated worker profiles where the CLI supports it.

Full threat model: [`docs/security-model.md`](docs/security-model.md).

## Safe deployment reminder

Do not run this workflow with production credentials or deploy privileges on
the same account. Keep `allow_push`, `allow_deploy`, and `allow_production`
false, and use a dedicated WSL/Linux user or container for valuable
repositories.

## Acknowledgements

Responsible reports that improve containment, provenance, or permission
correctness are credited in the release notes unless you prefer to remain
anonymous.
