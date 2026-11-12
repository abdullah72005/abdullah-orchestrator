import contextlib
import io
import subprocess
import sys
from unittest.mock import patch

from test_orchestrator import ControlTests, orc


class SmokeRegressions(ControlTests):
    def test_real_unittest_bytecode_does_not_invalidate_checks(self):
        (self.project / 'test_sample.py').write_text('import unittest\nclass TestSample(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n')
        evidence = orc.run_checks(self.rundir, self.state, self.cfg, self.project,
                                  {'title': 'tests', 'checks': [[sys.executable, '-m', 'unittest', 'discover', '-v']]})
        self.assertTrue(evidence['passed'])
        self.assertEqual(evidence['commands'][0]['returncode'], 0)
        self.assertTrue((self.project / '__pycache__').is_dir())

    def test_check_that_changes_source_still_fails_integrity(self):
        self.state.update(phase='verify', plan={'batches': [{'title': 'x', 'checks': [[
            sys.executable, '-c',
            "from pathlib import Path; Path('new_source.py').write_text('changed')"]]}]})
        orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(self.state['status'], 'blocked')
        self.assertEqual(self.state['corrections'], 0)
        self.assertFalse(orc.read_json(__import__('pathlib').Path(self.state['verification']['path']))['source_unchanged'])

    def test_untracked_bytecode_ignored_but_source_and_tracked_bytecode_detected(self):
        baseline = orc.signature(orc.source_snapshot(self.project))
        cache = self.project / '__pycache__'
        cache.mkdir()
        (cache / 'app.cpython-310.pyc').write_bytes(b'generated')
        self.assertEqual(baseline, orc.signature(orc.source_snapshot(self.project)))
        (cache / 'source.py').write_text('changed')
        self.assertNotEqual(baseline, orc.signature(orc.source_snapshot(self.project)))
        subprocess.run(['git', 'add', '-f', '__pycache__/app.cpython-310.pyc'], cwd=self.project, check=True)
        staged = orc.signature(orc.source_snapshot(self.project))
        (cache / 'app.cpython-310.pyc').write_bytes(b'changed')
        self.assertNotEqual(staged, orc.signature(orc.source_snapshot(self.project)))

    def test_verification_integrity_error_blocks_without_correction(self):
        self.state.update(phase='verify', plan={'batches': [{'title': 'x', 'checks': [['true']]}]})
        with patch.object(orc, 'run_checks', return_value={'passed': False, 'error': 'source changed', 'commands': []}):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(self.state['status'], 'blocked')
        self.assertEqual(self.state['corrections'], 0)
        self.assertEqual(self.state['phase'], 'verify')

    def test_explicit_explorer_runs_before_implementation(self):
        plan = {'status': 'complete', 'batches': [{'title': 'x', 'goal': 'x', 'checks': [['true']]}]}
        self.state['require_explorer'] = True
        with patch.object(orc, 'strong_call', return_value=plan), patch.object(orc, 'call_model', return_value=({'status': 'complete', 'summary': 'inspected'}, {'id': 'explorer'})) as worker:
            orc.advance(self.rundir, self.state, self.cfg)
            self.assertEqual(self.state['phase'], 'explore')
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(self.state['phase'], 'implement')
        self.assertEqual(worker.call_args.args[3], 'explorer')

    def test_status_accepts_positional_id(self):
        with patch.object(orc, 'do_status') as status, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(orc.main(['status', 'test-run00']), 0)
        status.assert_called_once_with('test-run00')

    def test_interrupted_correction_reconciles_back_to_verification(self):
        snapshot = orc.source_snapshot(self.project)
        jobdir = self.rundir / 'jobs' / 'correction'
        jobdir.mkdir(parents=True)
        orc.atomic_json(jobdir / 'dispatch.json', {'source': snapshot})
        verification = self.rundir / 'verification.json'
        orc.atomic_json(verification, {'candidate': snapshot, 'error': 'Tracked or untracked files changed during verification; evidence is stale'})
        self.state.update(status='running', phase='implement', implementation={'status': 'complete'},
                          implementation_job='done', corrections=1, correction='bad verification',
                          active_job={'id': 'interrupted', 'status': 'running', 'pid': 99999999, 'path': str(jobdir)},
                          verification={'path': str(verification), 'passed': False})
        orc.modify_locked(self.rundir, self.state, 'test-run00', 'reconcile', retry_verification=True)
        self.assertEqual(self.state['status'], 'paused')
        self.assertEqual(self.state['phase'], 'verify')
        self.assertIsNone(self.state['active_job'])
        self.assertEqual(self.state['failed_jobs'][-1]['status'], 'reconciled_incomplete')
        self.assertEqual(self.state['implementation_job'], 'done')

    def test_correction_reconciliation_refuses_changed_checkout(self):
        jobdir = self.rundir / 'jobs' / 'correction'
        jobdir.mkdir(parents=True)
        orc.atomic_json(jobdir / 'dispatch.json', {'source': orc.source_snapshot(self.project)})
        (self.project / 'app.py').write_text('changed')
        self.state.update(status='uncertain', active_job={'id': 'interrupted', 'pid': 99999999, 'path': str(jobdir)})
        with self.assertRaisesRegex(RuntimeError, 'changed'):
            orc.modify_locked(self.rundir, self.state, 'test-run00', 'reconcile', retry_verification=True)
