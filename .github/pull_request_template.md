## What changed

<!-- One paragraph: the behavior, why it was wrong or missing, and the fix. -->

## Verification

<!-- Paste the exact commands and the result, not a summary. -->

```text
$ python3 -m unittest discover -s scripts/tests
Ran ... tests ...
OK
```

## Safety review

- [ ] Containment, provenance, or permission checks were not weakened.
- [ ] New behavior has a regression test, including a failure path.
- [ ] No secrets, credentials, or personal paths were added.
- [ ] Docs/contracts updated if behavior changed.
- [ ] The change does not add a model-invokable sensitive action.

## Related issues

<!-- Fixes #... -->
