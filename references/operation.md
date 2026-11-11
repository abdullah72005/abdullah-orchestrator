# Interactive operation and trust boundaries

Copy the **entire** skill directory onto the WSL filesystem. Run `python3 scripts/install_wsl.py`, edit `~/.config/abdullah-orchestrator/config.json`, then `python3 scripts/orchestrator.py doctor --project /abs/dev/repo`. Requires Python 3.10+, git, Codex CLI, OpenCode CLI, and Docker/Compose for Docker projects; Claude Code CLI only for Claude mode. No extra Python dependencies.

The installer links this one skill into `~/.agents/skills/abdullah-orchestrator` (Codex) and `~/.claude/skills/abdullah-orchestrator` (Claude), refuses to overwrite unrelated files, and never modifies the user's original two skills or global OpenCode settings.

## One conversation, visible stages

Interactive foreground mode is the default. The user opens **one Codex chat** with Luna medium as the visible coordinator and invokes `$abdullah-orchestrator`. The strong Architect remains a separate Sol High worker, and each engineering stage runs as its own visible foreground MCP call. Register the bundled stdio MCP server once:

```bash
codex mcp add abdullah-orchestrator -- python3 /abs/path/to/abdullah-orchestrator/scripts/orchestrator.py mcp
```

`install_wsl.py --register-codex` can perform that registration. The MCP server exposes small foreground tools:

| Tool | Purpose |
|---|---|
| `orchestrator_start` | Create durable run state; no worker dispatch |
| `orchestrator_stage` | Run exactly one stage in the foreground |
| `orchestrator_status` | Deterministic compact status; no model call |
| `orchestrator_recap` | Quick or developer recap from persisted evidence; no model call |
| `orchestrator_interrupt` | Persist, terminate and verify an interruption |
| `orchestrator_amend` | Persist an amendment; interrupt first if needed |
| `orchestrator_resume` | Mark a paused run runnable; does not execute a stage |
| `orchestrator_reconcile` | Clear a proven-stopped uncertain attempt; fails closed |
| `orchestrator_approve_plan` | Approve a run awaiting human plan approval |
| `orchestrator_approve_fallback` | One explicit, user-approved fallback dispatch |
| `orchestrator_runs` | List recent runs for new-chat recovery |

Each `orchestrator_stage` call runs one of: plan, required explore, implement, verify, review, accept, diagnose, integrate. Codex displays the tool call, its native running indicator and elapsed time, then the structured result. Codex does **not** display an external worker's private reasoning, intermediate tool calls, or MCP progress notifications; do not patch the TUI to pretend otherwise. A stage tool call may run for several minutes; it must never contain several stages or an entire hours-long run.

Codex waits at most `mcp_servers.abdullah-orchestrator.tool_timeout_sec` for one `tools/call`. Configure it per server in `~/.codex/config.toml` and restart Codex:

```toml
[mcp_servers.abdullah-orchestrator]
command = "python3"
args = ["<SKILL_DIR>/scripts/orchestrator.py", "mcp"]
tool_timeout_sec = 18000
```

The previously observed 300-second default is too short for a legitimate foreground stage. Five hours deliberately exceeds the supervisor's four-hour `max_worker_seconds`, `max_architect_seconds` and `max_check_seconds` caps, so the client cannot race the supervisor at the boundary; keep the MCP bound strictly above the largest configured stage cap. This is a **communication** upper bound, not a stuck-worker detector. The supervisor's `limits.max_worker_seconds`, `max_architect_seconds` and `max_check_seconds` bound execution; the guard, process-session liveness checks, user interruption and reconciliation handle exits, hangs and uncertain ownership. A running Codex session keeps its old client configuration, so restart after editing the file.

Cancellation is not an MCP tool. Interrupt first with `orchestrator_interrupt` (or the host's Esc cancel) and confirm `stopped: true`; then, only with explicit user authorization, the CLI `cancel <ID>` writes a cancellation control request that a running supervisor consumes. A paused run is preserved for audit.

The legacy CLI `start --background` is an optional detached mode for unattended operation. It is **not** the default and must not be selected without the user's explicit authorization. Its supervisor survives closing a chat only while WSL stays awake; a sleeping laptop cannot execute jobs.

## Supervisor ownership and interruption

The Python supervisor remains authoritative. It persists dispatch intent before launch, records the model/billing route, source snapshot, git HEAD, changed-file hashes, logs, worker session ID, parsed report and separate verification evidence.

Every worker is launched under a **guard** process that is a session and process-group leader and holds a lease pipe from the supervisor:

- liveness scans `/proc` for the whole session/process group and checks start time, not only `os.kill(pid, 0)`;
- zombies are not treated as live;
- a reused PID is rejected as a different execution;
- termination records descendants before killing the parent, sends SIGTERM then SIGKILL, and verifies the session is stopped;
- if the host connection or supervisor dies, the lease pipe closes and the guard kills the worker tree;
- an operation whose ownership cannot be proven is marked `uncertain`; no duplicate worker may be launched.

A queued chat message cannot preempt an already-running foreground tool. The user must use the host's cancel/interrupt action (for example Esc in Codex); the MCP server receives the cancellation notification, stops the process session and finalizes the safe state before returning.

`orchestrator_interrupt` writes the interruption request, signals the active execution, verifies termination, preserves partial work and returns a developer recap. A verified stop leaves the run `paused`; an unverified stop leaves it `uncertain`. Resume and reconcile are separate steps. An uncertain session is never reused until reconciliation proves the previous attempt stopped.

At any time the user may interrupt and ask what happened, what was implemented, how it works, why it was done that way, which files changed, which tests passed and what remains. The coordinator answers from `orchestrator_status` and `orchestrator_recap` (`quick` for short summaries, `developer` when the user asks how or why), citing recorded files, commands and results and admitting missing evidence. Routine summaries stay short. After an interruption the coordinator never blindly repeats completed work; it resumes the same run or reconciles an uncertain termination first.

Amendments are persisted in run state and the journal. A requirement/architecture amendment can route through the strong Architect (`diagnose`); an implementation-only amendment becomes a bounded correction. Accepted batches and on-disk work are preserved; affected verification/review evidence is invalidated.

## Recovery guarantees and limits

State is stored on WSL Linux disk in `~/.local/state/abdullah-orchestrator/runs/<ID>`. Each run has immutable dispatch artifacts, a durable `journal.jsonl`, checkpoints, reports and verification logs. Recovery from a new chat uses `orchestrator_runs`, `orchestrator_status`, then `orchestrator_resume`.

A completed artifact is only recovered as complete when its recorded process session is proven stopped and its completion snapshot matches the current checkout. Artifacts alone are not proof. Reports written before process exit with live descendants, missing reports, contradictory snapshots, reused PIDs, and legacy jobs without process identity fail closed.

The guarantee is recovery from persisted, verified checkpoints without blindly repeating completed work. It is **not** restoration of an LLM's exact internal reasoning, and it is **not** exactly-once external side effects. A daemonized descendant that escapes its session (for example by calling `setsid` after its parent exits) may be undetectable without OS cgroups; such a case must be treated as a limitation and reconciled by an operator.

## Verification and security

The worker Implementer is a broad-trust local dev agent: local `.env`, Docker and shell edits do not trigger routine approval. Explorer/Reviewer have OpenCode read-only tool permissions, but shell/Docker permissions are **not** a complete OS sandbox. Keep this away from production credentials, deploy privileges and sensitive host files. Push/deploy, broad deletion, production access and billing changes are not authorized merely by starting a run.

Supervisor verification uses exactly the plan's argv arrays, never `shell=True`. For Compose it proves the service mounts and runs inside the exact candidate checkout. It fingerprints the source before and after checks and rejects stale evidence. Verification commands and model calls are interruptible in interactive mode through the same guard/process-session mechanism.

Doctor checks generated CLI options using the installed help, runs the generated options with `--help`, and checks configured models/variants against the verbose local catalog. It does not launch a model session, verify authentication or entitlement, or prove runtime execution; its `ready` result is a preflight result. DeepSeek on Go may require enabling **Global** under OpenCode Console → Settings → Privacy → Regions. API keys in the environment can silently change billing behavior: fail closed unless deliberately authorized.

For a required Explorer, the planning Architect can certify a completed, source-matched synchronous investigation by recording its job ID and scope satisfaction in the plan; otherwise the supervisor schedules its own investigation. Reviewer verification is provided as bounded source-checked command evidence in the prompt without widening filesystem permissions. Raw model reports and normalization records are retained with the job.

Synchronous Explorer attempts use `python3 scripts/orchestrator.py explore RUN_ID --task 'targeted investigation'` and keep a separate tracker under `explorations/tracker` so the Architect can wait while the supervisor holds the run lock. Before `reconcile-explorer ID`, inspect its tracker, dispatch archive, process session and descendants, logs, session and checkout. Reconciliation may recover a completed report or mark the attempt incomplete; it never automatically starts a replacement.

Current scope: single sequential writer, independent Reviewer, strong acceptance, bounded corrections, final integration checks; no nested Implementer agents, no daemon service installation, no database or notifications. Check the user's actual CLI version with `doctor` before any long unattended run.
