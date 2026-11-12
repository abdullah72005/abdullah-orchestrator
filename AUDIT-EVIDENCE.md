# Final audit evidence (before/after)

Generated: 2026-11-12

Baseline: `b71f84e` (tag `final-audit-baseline`).
After: final hardening commit on `remediation/batch1-safety`.

Probe: `/tmp/probe.py` executed against a detached baseline worktree and the
current scripts directory with the shipped `config.example.json`.

## Reproduced findings

| Probe | Baseline | Current |
|---|---|---|
| policy | `{"bash_lc": {"allowed": true, "policy": "explicit", "reasons": null}, "direct_docker": {"allowed": true, "policy": "direct", "reasons": null}, "env_path_wrapper": {"allowed": true, "policy": "explicit", "reasons": nul...` | `{"bash_lc": {"allowed": false, "policy": "explicit", "reasons": ["shell_wrapper", "arbitrary_script"]}, "direct_docker": {"allowed": true, "policy": "direct", "reasons": []}, "env_path_wrapper": {"allowed": false, "po...` |
| ignored_executable_invalidates | `false` | `true` |
| project_local_executable | `{"allowed": true, "reasons": null}` | `{"allowed": false, "reasons": ["arbitrary_script"]}` |
| env_drift | `"accepted (stale evidence reused)"` | `"rejected: Verification provenance drifted since the check"` |
| plan_revision_reuse | `"rejected: verification_evidence_package() got an unexpected keyword argument 'plan_version'"` | `"rejected: Verification evidence belongs to a different plan revision; re-run verification for the current plan"` |
| blank_acceptance | `"accepted"` | `"rejected: Contract v2 batch requires nonempty acceptance criteria"` |
| high_risk_duplicate | `"accepted"` | `"rejected: High-risk batches require at least 2 distinct verification checks; duplicates do not count"` |
| high_risk_trivial | `"accepted"` | `"rejected: High-risk batch contains trivial checks [('true',)] that cannot verify acceptance"` |
| mcp_approve_tools | `["orchestrator_approve_fallback", "orchestrator_approve_plan"]` | `[]` |
| plain_exception_blocks_wrapper | `false` | `true` |
| opencode_2_2_7 | `"v2"` | `"v2"` |

### Full current policy probe

```json
{
  "bash_lc": {
    "allowed": false,
    "policy": "explicit",
    "reasons": [
      "shell_wrapper",
      "arbitrary_script"
    ]
  },
  "direct_docker": {
    "allowed": true,
    "policy": "direct",
    "reasons": []
  },
  "env_path_wrapper": {
    "allowed": false,
    "policy": "explicit",
    "reasons": [
      "wrapper"
    ]
  },
  "legit_pytest": {
    "allowed": true,
    "policy": "direct",
    "reasons": []
  },
  "python_c": {
    "allowed": false,
    "policy": "explicit",
    "reasons": [
      "interpreter_string",
      "arbitrary_script"
    ]
  },
  "sudo_wrapper": {
    "allowed": false,
    "policy": "explicit",
    "reasons": [
      "wrapper"
    ]
  },
  "timeout_wrapper": {
    "allowed": false,
    "policy": "explicit",
    "reasons": [
      "wrapper"
    ]
  },
  "wrapped_docker": {
    "allowed": false,
    "policy": "explicit",
    "reasons": [
      "shell_wrapper",
      "arbitrary_script"
    ]
  }
}
```

## Real OpenCode V2.2.7 evidence

Binary: `opencode v2.2.7` staged at `/tmp/ocv2/opencode` (not installed globally).

- `opencode run --help` exposes `--agent --model --format --auto --session --standalone`.
- `opencode debug agents --standalone` accepts the generated native V2 config and reports
  effective denies for explorer/reviewer/implementer (see `test_opencode_v2_integration.py`).
- `doctor` against the staged binary and a disposable repo:

```json
{
  "cli_compatible": {
    "codex": true,
    "opencode_run": true,
    "opencode_version": true
  },
  "model_inventory": "listed",
  "opencode_dialect": "v2",
  "opencode_version_error": null,
  "paid_go_model_listed": true,
  "ready": true,
  "variant_verified": "unavailable",
  "worker_profiles": {
    "explorer": true,
    "implementer": true,
    "reviewer": true
  },
  "worker_profiles_cli": {
    "explorer": true,
    "implementer": true,
    "reviewer": true
  },
  "worker_profiles_cli_verified": true
}
```

`variant_verified` is `unavailable` because V2 `models` does not expose variants;
this is reported rather than claimed. Authenticated model execution was not tested.

## Test suite

```
436 passed, 70 subtests passed (includes opt-in V2 binary suite)
```

All model CLIs remain faked in the default suite; the V2 suite makes no model call.
