# Final hardening notes (2026-11-12)
- Baseline b71f84e, 400 tests pass, tag final-audit-baseline.
- Installed opencode 1.18.35 at ~/.opencode/bin/opencode (curl method).
- Latest stable V2 = v2.2.7 (2026-11-10). GitHub 'latest' API still points at v1.19.5,
  so `opencode upgrade` alone will NOT reach V2; must pass target 2.2.7.
- V2 CLI verified: `run` supports --auto --agent --model provider/model#variant
  --format json --session --standalone. `models` has no --verbose and no provider arg.
- Existing code already has v2 dialect/profile/cli groundwork; gaps: pinned 1.18 blocks v2,
  doctor probe_opencode_config returns False for v2, model inventory parser v1-only,
  no --standalone (V2 background service can escape containment).
- config.example.json command_policy reject_* all false -> audit finding #3.
- signature() hashes source only; acceptance compares provenance source only -> env drift accepted (#4).
- runtime_input_manifest patterns exclude ignored *.py (#4b).
- approve_plan/approve_fallback exposed as MCP tools (#6).
- amend_run treats omitted architect_review as minor (#7).
- _bounded_context silently truncates JSON (#7b).
