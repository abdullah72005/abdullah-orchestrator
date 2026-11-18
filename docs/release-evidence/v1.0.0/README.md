# v1.0.0 release evidence

Checks executed during release preparation on 2026-11-18 (WSL2 Ubuntu 22.04.5,
Python 3.10.12, non-root). No model call, subscription inference or paid request
was made. Test-suite execution for the release commit is handled by GitHub
Actions; see the workflow run on the tagged commit.

| File | Content |
|---|---|
| `version.json` | `orchestrator.py version` output: public, supervisor, schema and contract identifiers |
| `doctor-real.json` | Real `doctor` preflight against a disposable Git repository using the installed Codex + OpenCode V2 + Go configuration; no inference |
| `mcp-handshake.jsonl` | stdio MCP `initialize` + `tools/list`: `serverInfo` and the nine-tool surface |
| `install-first-run.log` | Fresh `HOME` install with a stateful fake Codex CLI: links, `0600` config, MCP registration |
| `install-second-run.log` | Second identical run: links/config preserved, registration not repeated |
| `install-conflict-refusal.log` | Pre-existing unrelated skill refused; content preserved |
| `link-check.txt` | Relative documentation link/anchor check |
| `check_links.py` | The checker used (reproducible) |
| `security-scan.txt` | Credential-pattern and auth-file scan over tracked files |

Environment highlights from `doctor-real.json`: `ready: true`, dialect `v2`,
`route_models_listed: true`, empty `api_billing_risk` and
`route_authorization_required`, `variant_verified: "unavailable"` (V2 model
inventory does not expose variants), and `execution_verified: false` (Doctor never
runs a model).

The disposable project, MCP server and installer tests used isolated temporary
directories. The preserved real E2E run and the maintainer's global Codex/Claude
configuration were not modified.
