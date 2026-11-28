#!/usr/bin/env python3
"""Run one exact ``unittest`` group and record machine-readable outcomes.

``run_tests_parallel.py`` uses this child for each group so its counts come
from the ``TestResult`` object instead of from the log text.  A test may run a
nested suite or print its own ``Ran N tests`` summary; that output stays in the
group log for humans but cannot change the runner's own accounting.  Verbose
output is still written to stderr, so the log keeps the normal transcript.

Usage::

    python3 _unittest_group.py RESULT.json TEST_ID [TEST_ID ...]
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


class RecordingResult(unittest.TextTestResult):
    """Text result that also records each test id's terminal outcome."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.outcomes = {}
        self.skip_reasons = {}

    def _record(self, test, status, reason=None):
        test_id = test.id()
        self.outcomes[test_id] = status
        if reason is not None:
            self.skip_reasons[test_id] = reason

    def addSuccess(self, test):
        super().addSuccess(test)
        self._record(test, "success")

    def addError(self, test, err):
        super().addError(test, err)
        self._record(test, "error")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._record(test, "failure")

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        # setUpClass/setUpModule skips use ids like
        # ``setUpClass (module.Class)``.  They are kept verbatim so the parent
        # can expand them over the selected tests they cover.
        self._record(test, "skipped", reason)

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self._record(test, "expected_failure")

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self._record(test, "unexpected_success")


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 2:
        print("usage: _unittest_group.py RESULT.json TEST_ID [...]",
              file=sys.stderr)
        return 2
    result_path = Path(args[0])
    names = args[1:]
    payload = {
        "names": names,
        "ran": 0,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "outcomes": {},
        "skip_reasons": {},
        "loaded": False,
        "success": False,
        "error": None,
    }
    try:
        suite = unittest.defaultTestLoader.loadTestsFromNames(names)
        payload["loaded"] = True
        result = unittest.TextTestRunner(
            verbosity=2, resultclass=RecordingResult).run(suite)
        payload.update({
            "ran": result.testsRun,
            "failures": len(result.failures),
            "errors": len(result.errors),
            "skipped": len(result.skipped),
            "outcomes": dict(result.outcomes),
            "skip_reasons": dict(result.skip_reasons),
            "success": result.wasSuccessful(),
        })
    except BaseException as exc:  # noqa: BLE001 - recorded, then reported
        payload["error"] = "%s: %s" % (type(exc).__name__, exc)
    finally:
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(payload, sort_keys=True) + "\n",
                               encoding="utf-8")
    return 0 if payload["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
