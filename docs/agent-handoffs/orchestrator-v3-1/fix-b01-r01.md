# v3.1 single batch — Architect correction round 1

Disposition: CHANGES REQUIRED. Execute as a focused correction to the already approved single batch; no redesign or new campaign features are authorized.
Reviewed base: `1b8e10e5c1b2c08a236b68450cb5b2a1a610416d`.
Correction starting HEAD: `bfd9a8b7a1c75329f039239b983485deadae0ada`, branch `design/orchestrator-v3-1`.
Worktree: `/home/abdullah/.local/src/abdullah-orchestrator-v3-1`.
Authority: original complete batch-01.md and architecture.md. This brief narrows the next implementation round to confirmed review defects. Preserve all previous work and existing handoff documents.

## Review evidence and scope

Architect inspected the baseline-to-HEAD supervisor changes, affected dispatch/state/acceptance/recovery boundaries, installer, new behavioral suites and altered legacy fixtures, documentation and saved full-suite log. Commit sequence and clean tracked tree match the Implementer report. Four original planning files remained untracked; this correction file is an additional Architect artifact.

Independent focused command at reviewed HEAD:
`python3 -m unittest discover -s scripts/tests -p 'test_v31_*.py' -v`
Result: **77 tests passed**, exit 0, 133.198 seconds, Python 3.10.12. Log: `/tmp/ao-v31-architect-tests.log`.
Implementer's saved `/tmp/opencode/v31-evidence/full-suite.log` contains 656 tests, 4 skipped, 290.646 seconds, OK. That full run was inspected, not independently rerun; the four optional binary skips are not passes.

Independent disposable diagnostic scripts and copies: `/tmp/ao-v31-architect-evidence/`. These used temporary Git repositories/config/state/HOME and fake CLIs, not live credentials/model calls. Reproduce their behaviors as permanent regressions; these temporary scripts are not the production test contract and may be absent in a fresh environment. Observed results are specified below. Additional restore probe used a disposable ControlTests fixture and invalid JSON backup. No production source was changed by this review.

Existing tests are green but miss the following defects. All numbered findings block batch approval; no previous invariant may be weakened to repair them.

## F1 — P1: source-mutation handling clears ownership with a live escaped process

Location: `scripts/orchestrator.py:5280–5321`, call_model exception path; associated stage_run/recovery handling.
Evidence: fake read-only Explorer edits app.py, starts a child with a new session inheriting job/run markers, then returns a valid report. Independent probe observed `child_alive: true`, `containment_stopped: false`, `failed_job_status: blocked`, `active_job: null`. Probe child was explicitly killed during cleanup.
Root cause: SourceMutationError, or merely an exited immediate process, forces blocked even when inspect_execution says the execution is not stopped. The subsequent active_job assignment clears the uncertain execution.
Correction: make source integrity and process containment independent gates. Preserve source/report/mutation evidence; use existing termination/inspection machinery on failure as on success. Clear active identity only when the whole relevant execution is proven stopped. Otherwise keep exact uncertain ownership and refuse replay, resume progression, new checkout ownership and retirement as existing contracts require. Do not treat a leader exit or error class as proof.
Required tests: real guarded fake CLI with marked escaped child and source edit; both valid-report and nonzero/malformed-report paths; assert either verified cleanup with no survivors or retained uncertain identity. Test failed cleanup without losing ownership; cleanup every test child even if assertion fails. Clean stopped mutation must still block and preserve edits without requiring phantom reconciliation.

## F2 — P1: arbitrary worker providers inherit Go's grant exemption

Location: `normalize_worker_spec` around 249–286, route_preflight around 1262; migration normalization.
Evidence: configure `opencode-zen/some-model`, `provider: opencode-zen`, `billing: go`, no grants. config accepts it, preflight returns ok, fake worker dispatch completes. Omitting billing also defaults to go for any provider.
Correction: legacy Go consent applies only to a correctly identified unchanged Go route. Reject go billing on non-Go provider/model combinations in config, dispatch defense-in-depth and recorded-route migration. Infer legacy missing fields only for legacy all-Go records, never default a new arbitrary remote provider into subscription authorization. Maintain default Go compatibility; do not infer billing for other providers from their names.
Required tests: explicit go/non-Go mismatch, missing billing/non-Go, fallback mismatch, malformed saved routes and schema migration; all refuse before spawn and call accounting. Existing Go configurations remain valid without new grants. Use actual fake dispatch, not only normalization assertions.

## F3 — P1: bounded non-Go subscription grants never consume allowance

Location: `call_model:5062` and SUBSCRIPTION_BILLINGS, route_preflight/reserve_route_grant.
Evidence: non-Go worker with `billing: subscription`, attested grant `max_dispatches=1`; two fake dispatches complete and saved `used` remains 0. Preflight requires a grant but reservation excludes all subscription billing.
Correction: reserve whenever preflight requires a grant, independently of billing label. Exempt only routes explicitly requiring no grant. Bind reservation to the selected exact grant and preserve conservative crash behavior. Keep accounting distinct from entitlement/spend promises.
Required tests: non-Go subscription count=1 allows exactly one attempt, next rejected before spawn; same across reload/resume, failure and correction; other explicitly bounded route classes unchanged. Grant references and consumptions appear in durable evidence, with no secret values.

## F4 — P1: parent Architect overwrites nested Explorer grant consumption

Location: `explore:8338–8348`, reserve_route_grant/save main state and later call_model parent saves.
Evidence: separate fake Codex process invokes the actual supervisor CLI explore, which runs fake OpenCode. Saved grant used becomes 1 after nested completion, then parent call_model completion saves its older state object and resets used to 0. Independent output: `child_exit:0`, `used_after_nested:1`, `used_after_parent_completion:0`. Existing test mocks load to return the same in-memory state object and misses actual process separation.
Correction: persist grant reservations in a durable authority that cannot be lost to parent snapshots. Prefer adapting the existing separate tracker/event merge pattern with exact reservation IDs and fail-closed reconciliation, or a small separately locked grant ledger; do not bolt on an unsafely unlocked read-modify-write to state.json. Inspect parent failure, interruption and crash saves too. Authorization must consult current durable consumption before each nested call, not depend on a later parent merge to enforce the bound. Avoid taking the parent-held supervisor lock from its synchronous child (deadlock).
Required tests: actual separate-process parent→explore CLI path; grant remains consumed after parent completion/failure/restart, second attempt refused, concurrent nested requests cannot exceed count, no duplicate consumption on event replay, no parent active_job overwrite or lost usage. Reviewer isolation and existing explorer budget remain unchanged.

## F5 — P1: routing fingerprint does not represent the effective OpenCode route

Location: `opencode_provider_observation:1129`, routing_fingerprint:3631, model_route/create_run/migrate_run/dispatch/Doctor.
Evidence: change project opencode.json provider endpoint from first.invalid to changed.invalid after pinning an API route. Fingerprint is unchanged and preflight still returns ok. Observer never receives project; it scans only explicit/global files, parses only V1 `provider.*.options`, and fingerprints auth option names/model count rather than effective auth mode/model mapping. Current documented V2 uses `providers.*.settings` and merged project/ancestor/.opencode/system configuration. Migrated schema-2 worker routes may also retain a null fingerprint, disabling the comparison.
Correction: observe effective routing using the selected installed dialect and actual project/child environment, with supported offline CLI introspection where available. Cover applicable config locations/precedence, V1/V2 shapes, JSONC and relevant env expansion/auth selection; hash only redacted material needed to bind endpoint, selected model/variant mapping, credential/auth mode and detectable auxiliary/fallback routes. Unknown/unreadable influential input fails closed, including Go; a parse error must not be a warning that grants Go a bypass. Initialize reviewed routing pins during explicit migration. Do not silently repin an existing run at dispatch, and do not execute inference/credential helpers. Maintain explicit supported boundaries for uninspectable plugins/gateways rather than claiming universal guarantees.
Required tests: real temporary project/global/ancestor settings and both dialect fixtures; V2 providers/settings endpoint override; applicable JSONC; auth-mode/model-mapping change with same option names/model count; project/env/config-directory drift; unreadable settings; migrated pin and later drift. Prove actual Doctor/dispatch agree and refuse before spawning. Do not mock the entire observation function for all drift tests.
Primary references checked 2026-11-14: https://opencode.ai/docs/config/ (locations, merging, JSONC); https://opencode.ai/docs/providers/ (V2 providers/settings and endpoint/model/variant overrides). Recheck against supported installed CLI versions; do not transplant current V2 syntax into V1.

## F6 — P1: Claude subscription preflight overlooks actual settings sources/overrides

Location: CLAUDE_BILLING_ENV/CLAUDE_SETTINGS_FILES, _inspect_json_settings and claude_billing_hazards around 1005–1126; cli_command child environment; Doctor.
Evidence: set CLAUDE_CONFIG_DIR to a disposable alternative directory with settings.json env ANTHROPIC_BASE_URL selecting a custom endpoint. route_preflight still returns ok and the child environment retains the selector. CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST is also unexamined; the approved design explicitly required investigating this control. Settings fallback/model-routing keys are not inspected; only a small fixed list and env names are checked.
Correction: resolve or explicitly reject unprovable supported alternate config/provider-management mechanisms before claiming subscription. Inspect applicable effective user/project/local/managed sources and documented routing settings for the supported Claude CLI, respecting precedence. Detect documented endpoint/token/helper/provider and fallback overrides from the actual child route. Do not claim unseen managed settings are certified; give an actionable redacted blocked/unverified result when effective routing cannot be established. Do not run credential helpers or indiscriminately reject inert AWS credentials. Use the same result in Doctor and dispatch. Preserve explicitly human-authorized alternate billing routes.
Required tests: temporary alternate config directory with dangerous endpoint/helper/provider setting, inherited provider-managed control, influential managed settings fixture, fallback routing settings, malformed/unreadable effective input, post-Doctor contamination, legitimate unmodified subscription case, authorized explicit alternate route. Every refusal precedes spawn/active_job and does not leak values.
Primary references: https://code.claude.com/docs/en/env-vars and https://code.claude.com/docs/en/settings . Version-pin assumptions where mechanisms differ.

## F7 — P2: API fallback has no public authorization path

Location: authorize_route_run around 9413; approve_worker_fallback_run and CLI definitions; worker fallback docs.
Evidence: configure Go Explorer primary with API-billed fallback, call public authorize_route_run then approve_worker_fallback_run. Grant always hashes the primary route; fallback dispatch is rejected for lacking its own grant. There is no CLI argument selecting the alternate. Tests exercise Go fallback only.
Correction: let the human authorize the exact configured fallback via an explicit selector (for example --fallback on authorize-route) or an equally narrow route-hash target validated against pinned primary/fallback. Keep one-dispatch fallback consent separate from the grant; neither silently authorizes the other. Document the complete usable command sequence. Reject arbitrary replacement routes and preserve fresh sessions.
Required tests: public CLI/helper path for API fallback authorized and dispatched once; missing alternate grant/consent, exhausted grant, changed alternate, retry/failure and second dispatch cannot silently fall back. No manually injected fallback grant as the sole integration coverage.

## F8 — P2: Claude foreground setup conflates two configuration files

Location: install_wsl.py:manual_claude_snippets/install output around 251; references/operation.md:37; test_v31_claude_setup.py last fixture.
Evidence: installer prints one 'Mergeable host snippet' combining settings env and mcpServers. Documentation likewise offers a combined object without separate destination paths; the test merges mcpServers into .claude/settings.json. Official MCP user registrations are in ~/.claude.json; foreground env belongs in ~/.claude/settings.json or the interactive host environment. The test proves dictionary construction rather than valid host configuration. Registration through mcp add does not itself install the recommended timeout.
Correction: emit separately labeled exact destination snippets and manual merge/verification steps: host foreground environment/settings versus user-scoped MCP server entry/timeout in its real store (respect custom config directory). Preserve unrelated configuration and don't mutate real files during this correction. Ensure the registered server actually has the documented manual path to receive its timeout. Do not add automated host-settings editing without authorization.
Required tests: disposable settings and user MCP stores, env in the former and server timeout in the latter; unrelated content preserved, repeated registration and correct destination instructions. Authenticated foreground/Esc/reconnect remains explicitly pending.
Primary reference: https://code.claude.com/docs/en/mcp (scope/store and timeout) and settings documentation.

## F9 — P2: restore overwrites valid state before validating backup

Location: restore_run around 8016–8042.
Evidence: paused disposable run, restore from `{invalid` file. JSONDecodeError occurs after copy2, leaving state.json containing `{invalid` and destroying prior readable state. Copying directly also bypasses the supervisor's atomic persistence pattern. Current tests cover valid restore only.
Correction: parse and validate backup completely before mutation (run/project identity and allowed inactive state included); refuse mismatched/corrupt/running/uncertain state. Apply through atomic persistence under the lock and preserve the pre-restore state/audit evidence. Do not truncate state on validation or write failure. Retain explicit human operation and backup provenance; no unrelated restore-system redesign.
Required tests: corrupt JSON, wrong run/project, running/active/uncertain source or destination, simulated write failure, valid restore and compatibility classification. Invalid restore leaves original state bytes unchanged; backup and historical artifacts remain inspectable.

## Required verification and evidence corrections

Add failing tests for each finding before fixes; keep red output. Existing green tests are insufficient evidence of these boundaries. Update matrices and independent-auditor-handoff.md to cite the new tests, correct destination paths, actual authorization/reservation/pinning behavior and remaining unverified live paths. No closure claim until corrected behavior passes.

Also replace `test_each_check_fits_but_checks_plus_decision_do_not`: it currently runs only the verify stage with a five-second budget, never a decision, and asserts successful advancement. Add a genuine single acceptance stage with checks plus fake strong decision where each child separately fits but the total exceeds the stage budget. Ensure it times out without completion and preserves containment. Add a full mixed-provider fake stage path using the real human authorization helpers (test-only operator identity), not only normalization/all-Go paths. These tests fulfill existing batch requirements; no new feature is introduced.

Commands from worktree:

```
python3 -m unittest discover -s scripts/tests -p 'test_v31_*.py' -v
python3 -m unittest discover -s scripts/tests -p 'test_checkpoint_a_containment.py' -v
python3 -m unittest discover -s scripts/tests -p 'test_checkpoint_c_security.py' -v
python3 -m unittest discover -s scripts/tests -p 'test_interactive_recovery.py' -v
python3 -m unittest discover -s scripts/tests -p 'test_usage_rate_limit_regressions.py' -v
python3 -m compileall -q scripts
python3 -m unittest discover -s scripts/tests -v
```

Run the full offline suite once after the complete correction set, and again only if subsequent changes require it. Keep fresh temp paths for HOME/config/state/registry; no paid model calls, live installation, live Doctor, credentials or existing-run changes. Python matrix limitations remain explicit. Re-run fixture hermetic-override checks if shared test setup changes.

## Permissions and delivery

One correction round for the complete original batch; continue through findings without intermediate approval. Preserve architecture: existing deterministic supervisor, OpenCode CLI workers, original report contracts and human-only authorization. Local focused commits permitted; do not commit original Architect planning drafts automatically. No push, merge, install, release, tag, destructive Git, global config/skill changes, Sanatry access or paid requests. Do not use the automated orchestrator to repair itself. Escalate consequential design deviations; targeted helper/ledger changes needed for F4/F5 are authorized within the approved durability/routing design.

Return one copyable chat report with starting/final branch/HEAD, ordered commits, complete diff scope/status, F1–F9→code/test matrix, red/green evidence and exact commands/counts/skips/exit codes, separate-process nested/containment evidence, compatibility/billing assessment, updated doc paths and limitations. Do not call the correction approved; the Architect will review actual code and evidence. Original batch acceptance remains blocked until these defects are closed.
