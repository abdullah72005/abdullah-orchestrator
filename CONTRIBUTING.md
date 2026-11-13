# Contributing

Thanks for taking the time to improve Abdullah Orchestrator. This project
handles process lifecycles, repository checkouts, and evidence that other
agents rely on, so changes are reviewed with a bias toward **fail-closed
behavior and reproducible tests**.

## Development setup

No build step and no Python dependencies are required.

```bash
git clone https://github.com/abdullah72005/abdullah-orchestrator.git
cd abdullah-orchestrator
python3 --version   # 3.10+
```

Run the deterministic suite:

```bash
python3 -m unittest discover -s scripts/tests
```

The suite is hermetic: it replaces `codex`, `claude`, and `opencode` with fakes
and redirects `ABDULLAH_CONFIG`, `ABDULLAH_STATE_DIR`, and the checkout registry
to temporary paths. Exporting those variables for a real run must not change
the result.

Run one module while iterating:

```bash
python3 -m unittest discover -s scripts/tests -p "test_checkpoint_a_containment.py"
```

## Ground rules

1. **Never weaken a security control to make a test pass.** If a test exposes a
   real limitation, document it and add a regression test for the intended
   behavior.
2. **Add a regression test with every bug fix.** Tests live in
   `scripts/tests/test_*.py`; fixtures go in `scripts/tests/fixtures/` and
   should record their provenance.
3. **Preserve fail-closed defaults.** Uncertain ownership, missing evidence, and
   unrecognized CLI versions must produce an explicit error, not a guess.
4. **Do not add runtime dependencies** without a compelling reason. A skill that
   installs by symlink should not need a package manager.
5. **Do not edit real run state.** Use temporary directories and synthetic runs.
   Never reconcile, retire, or cancel a live run to test a change.
6. **Keep the MCP surface small.** New tools expand what a model can do; prefer
   operator CLI commands for sensitive actions.

## Code style

- Python 3.10+, standard library only.
- Follow the surrounding style: explicit names, small helpers, deterministic
  output, no hidden I/O.
- Prefer typed, structured results (`dict` contracts) over printed prose for
  anything a caller consumes.
- Keep comments about *why*, especially around process ownership, provenance,
  and permission ordering.
- Validate argv and paths at the boundary; never build a shell string.

## Commit messages

Use conventional-style prefixes and a short imperative subject:

```text
fix: reject V2 permission glob overlaps that defeat denies
test: add exclusion and architect-review amendment regressions
docs: record delta-audit corrections and verification evidence
feat: add verification provenance and command policy
```

Explain *what was observed* and *why the change is safe* in the body. Reference
the relevant test module when behavior changes.

## Pull request checklist

- [ ] `python3 -m unittest discover -s scripts/tests` passes.
- [ ] `python3 -m compileall -q scripts` passes.
- [ ] New behavior has a regression test (including a failure path).
- [ ] No new runtime dependency, credential, or personal path is introduced.
- [ ] Documentation is updated where behavior or contracts changed.
- [ ] The change does not weaken containment, provenance, or permission checks.
- [ ] If the OpenCode/Codex CLI contract changed, `doctor` and the dialect
      tests were updated together.

## Documentation

- Agent-facing operation: `SKILL.md` and `references/`.
- Human-facing design: `docs/`.
- Audit history: `docs/audit/`. Do not rewrite past findings; add a new entry.

## License

By contributing, you agree that your contribution is licensed under the
[MIT License](LICENSE).
