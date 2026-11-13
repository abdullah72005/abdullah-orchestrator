import sys
import json
import os
import subprocess
import unittest
from unittest.mock import patch

import test_orchestrator as baseline
orc = baseline.orc


class HardeningTests(unittest.TestCase):
    setUp = baseline.ControlTests.setUp
    def test_doctor_rejects_config_that_drops_worker_permissions(self):
        with patch.object(orc.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, stdout='{"agent":{"abdullah-explorer":{}}}')):
            self.assertFalse(orc.probe_opencode_config(self.project, 'explorer', 'v1'))

    def test_resume_cannot_overwrite_active_supervisor_checkpoint(self):
        with patch.object(orc, 'load', return_value=(self.rundir, self.state)), patch.object(orc, 'detach') as detach:
            with orc.exclusive(self.rundir):
                with self.assertRaisesRegex(RuntimeError, 'Another supervisor'):
                    orc.modify('test-run00', 'resume')
        detach.assert_not_called()

    def test_interrupted_worker_remains_uncertain(self):
        fake = self.root / 'opencode'
        fake.write_text('#!/bin/sh\nif [ "$1" = "--version" ]; then echo 1.18.35; exit; fi\nsleep 30\n')
        fake.chmod(0o755)
        orc.atomic_json(self.rundir / 'control.json', {'action':'pause'})
        with patch.dict(os.environ, {'PATH':str(self.root) + ':' + os.environ['PATH']}):
            with self.assertRaises(InterruptedError):
                orc.call_model(self.rundir, self.state, self.cfg, 'implementer', 'implementer', 'task', self.project)
        restored = orc.read_json(self.rundir / 'state.json')
        self.assertEqual(restored['active_job']['status'], 'uncertain')
        self.assertEqual(len(restored['failed_jobs']), 1)

    def test_fallback_worker_response_uses_worker_contract(self):
        fake = self.root / 'codex'
        fake.write_text('''#!/usr/bin/env python3
import json, pathlib, sys
output = pathlib.Path(sys.argv[sys.argv.index('--output-last-message') + 1])
output.write_text(json.dumps({'status':'complete','summary':'fallback complete'}))
''')
        fake.chmod(0o755)
        self.state['fallback_authorization'] = {'role':'implementer'}
        with patch.dict(os.environ, {'PATH':str(self.root) + ':' + os.environ['PATH'], 'OPENAI_API_KEY':''}):
            report, _ = orc.call_model(self.rundir, self.state, self.cfg, 'implementer', 'implementer', 'task', self.project)
        self.assertEqual(report['status'], 'complete')

    def test_recovered_success_clears_retry_session(self):
        jobdir = self.rundir / 'jobs/implementer-done'
        jobdir.mkdir(parents=True)
        orc.atomic_json(jobdir / 'execution.json', {'returncode': 0})
        orc.atomic_json(jobdir / 'report.json', {'status':'complete', 'summary':'done'})
        orc.atomic_json(jobdir / 'completion.json', {'final_snapshot':orc.source_snapshot(self.project), 'session_id':'old-session'})
        self.state['active_job'] = {'id':'done', 'kind':'implementer', 'role':'implementer', 'path':str(jobdir), 'status':'running', **baseline.dead_process_identity()}
        self.state['retry_session'] = {'role':'implementer', 'session_id':'old-session'}
        self.assertTrue(orc.recover_finished_dispatch(self.rundir, self.state))
        self.assertIsNone(self.state['retry_session'])

    def test_rate_limited_worker_reconciles_and_continues_same_session(self):
        fake = self.root / 'opencode'
        fake.write_text('''#!/usr/bin/env python3
import json, sys
if '--version' in sys.argv:
    print('1.18.35'); sys.exit(0)
if '--session' not in sys.argv:
    print(json.dumps({'sessionID':'ses_retry','type':'text','part':{'text':'partial'}}))
    print('429 rate limit'); sys.exit(2)
assert sys.argv[sys.argv.index('--session') + 1] == 'ses_retry'
print(json.dumps({'sessionID':'ses_retry','type':'text','part':{'text':json.dumps({'status':'complete','summary':'resumed'})}}))
print(json.dumps({'sessionID':'ses_retry','type':'step_finish','part':{'reason':'stop'}}))
''')
        fake.chmod(0o755)
        self.state['phase'] = 'implement'
        with patch.dict(os.environ, {'PATH': str(self.root) + ':' + os.environ['PATH']}):
            with self.assertRaises(RuntimeError):
                orc.call_model(self.rundir, self.state, self.cfg, 'implementer', 'implementer', 'task', self.project)
            with patch.object(orc, 'load', return_value=(self.rundir, self.state)):
                orc.serve('test-run00')
                self.assertEqual(self.state['status'], 'uncertain')
                orc.modify('test-run00', 'reconcile')
                report, job = orc.call_model(self.rundir, self.state, self.cfg, 'implementer', 'implementer', 'task', self.project)
        self.assertEqual(report['summary'], 'resumed')
        self.assertEqual(job['continued_session'], 'ses_retry')
        self.assertIsNone(self.state['retry_session'])

    def test_unknown_future_opencode_major_fails_closed(self):
        with self.assertRaises(RuntimeError):
            orc.opencode_dialect('3.0.0')

    def test_verbose_inventory_checks_exact_configured_variants(self):
        inventory = 'opencode-go/model-a\n' + json.dumps({'variants': {'low': {}, 'high': {}}}) + '\n'
        models = orc.parse_model_inventory(inventory)
        self.assertEqual(set(models['opencode-go/model-a']['variants']), {'low', 'high'})
        self.assertNotIn('opencode-go/model-b', models)

    def test_invalid_review_and_decision_shapes_are_rejected(self):
        with self.assertRaises(ValueError):
            orc.validate_report('reviewer', {'status':'complete', 'summary':'review', 'findings':['not a finding']})
        with self.assertRaises(ValueError):
            orc.validate_report('decision', {'verdict':'approved', 'reason':'yes', 'inspected':'not a list'})

    def test_snapshot_detects_staged_changes(self):
        baseline = orc.signature(orc.source_snapshot(self.project))
        (self.project / 'app.py').write_text('value = 42\n')
        subprocess.run(['git', 'add', 'app.py'], cwd=self.project, check=True)
        self.assertNotEqual(baseline, orc.signature(orc.source_snapshot(self.project)))

    def test_recovery_requires_snapshot_captured_at_completion(self):
        jobdir = self.rundir / 'jobs/implementer-crash'
        jobdir.mkdir(parents=True)
        orc.atomic_json(jobdir / 'execution.json', {'returncode': 0})
        orc.atomic_json(jobdir / 'report.json', {'status':'complete', 'summary':'done'})
        self.state['active_job'] = {'id':'crash', 'kind':'implementer', 'role':'implementer', 'path':str(jobdir), 'status':'running'}
        self.assertFalse(orc.recover_finished_dispatch(self.rundir, self.state))
        self.assertIsNotNone(self.state['active_job'])

    def test_diagnosis_intent_persists_before_call_and_restarts(self):
        self.state['phase'] = 'accept'
        self.state['corrections'] = 1
        orc.handle_repair(self.rundir, self.state, self.cfg, 'second failure')
        restored = orc.read_json(self.rundir / 'state.json')
        self.assertEqual(restored['phase'], 'diagnose')
        self.assertEqual(restored['corrections'], 2)
        verdict = {'verdict':'changes_required', 'reason':'diagnosed', 'correction':'fix', 'inspected':['app.py']}
        with patch.object(orc, 'strong_call', return_value=verdict):
            orc.advance(self.rundir, restored, self.cfg)
        self.assertEqual(restored['phase'], 'implement')
        self.assertEqual(restored['corrections'], 2)
        self.assertEqual(restored['correction'], 'fix')

    def test_timeout_check_requires_reconciliation(self):
        batch = {'title': 'check', 'checks': [[sys.executable, '-c',
                                              'import time; time.sleep(5)']]}
        self.cfg['limits']['max_check_seconds'] = 0.3
        with self.assertRaises(TimeoutError):
            orc.run_checks(self.rundir, self.state, self.cfg, self.project, batch)
        saved = orc.read_json(self.rundir / 'state.json')['active_check']
        self.assertIsNotNone(saved)
        self.assertIsNotNone(saved.get('pid'))
        self.assertIsNotNone(saved.get('sid'))

    def test_example_config_allows_long_engineering_stages(self):
        limits = orc.read_json(orc.HERE / 'config.example.json')['limits']
        for key in ('max_worker_seconds', 'max_architect_seconds', 'max_check_seconds'):
            with self.subTest(key=key):
                self.assertIsInstance(limits[key], int)
                self.assertGreaterEqual(limits[key], 3600, key)
                self.assertLessEqual(limits[key], 86400, key)

    def test_recovered_rate_limited_writer_requires_reconciliation(self):
        jobdir = self.rundir / 'jobs/implementer-rate'
        jobdir.mkdir(parents=True)
        orc.atomic_json(jobdir / 'execution.json', {'returncode': 2})
        (jobdir / 'events.log').write_text('{"sessionID":"ses_1"}\n429 rate limit\n')
        self.state['active_job'] = {'id':'rate', 'kind':'implementer', 'role':'implementer', 'path':str(jobdir), 'status':'running', **baseline.dead_process_identity()}
        self.assertTrue(orc.recover_finished_dispatch(self.rundir, self.state))
        self.assertEqual(self.state['status'], 'uncertain')
        self.assertIsNotNone(self.state['active_job'])
        self.assertEqual(self.state['retry_session']['session_id'], 'ses_1')

    def test_doctor_rejects_generated_unknown_option(self):
        original = orc.cli_command
        def broken(*args, **kwargs):
            command, env, fmt = original(*args, **kwargs)
            if command[0] == 'codex':
                command.insert(-1, '--unsupported-future-option')
            return command, env, fmt
        with patch.object(orc, 'cli_command', side_effect=broken):
            self.assertFalse(orc.validate_cli_arguments(['codex', 'exec', '--model', 'x', '--unsupported-future-option', 'prompt'], '  --model <MODEL>'))

    def test_crash_during_verification_stays_uncertain(self):
        batch = {'title': 'check', 'checks': [[sys.executable, '-c',
                                              'import time; time.sleep(5)']]}
        with patch.object(orc, 'control', side_effect=KeyboardInterrupt('supervisor crash')):
            with self.assertRaises(KeyboardInterrupt):
                orc.run_checks(self.rundir, self.state, self.cfg, self.project, batch)
        restored = orc.read_json(self.rundir / 'state.json')
        self.assertIsNotNone(restored.get('active_check'))
        self.assertIsNotNone(restored['active_check'].get('pid'))
        self.assertIs(orc.job_liveness(restored['active_check'])['alive'], False)
        with patch.object(orc, 'load', return_value=(self.rundir, restored)), patch.object(orc, 'advance') as advance:
            orc.serve('test-run00')
        self.assertEqual(restored['status'], 'uncertain')
        advance.assert_not_called()

    def test_complete_workflow_with_real_adapters_fake_clis_and_correction(self):
        self.state['single_batch_fast_path'] = True
        fakebin = self.root / 'bin'
        fakebin.mkdir()
        fake = fakebin / 'fake_cli.py'
        fake.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
name = pathlib.Path(sys.argv[0]).name
if '--version' in args:
    print('1.18.35'); sys.exit(0)
history = pathlib.Path(os.environ['FAKE_HISTORY'])
if name == 'codex':
    output = pathlib.Path(args[args.index('--output-last-message') + 1])
    kind = output.parent.name.split('-')[0]
    previous = history.read_text().splitlines() if history.exists() else []
    with history.open('a') as f: f.write(kind + '\\n')
    if kind == 'plan':
        report = {'contract_version':2, 'status':'complete', 'summary':'plan', 'invariants':['Keep behavior'], 'blocker':'',
                  'batches':[{'title':'batch', 'goal':'change', 'acceptance':['done'],
                              'checks':[['true']], 'risk':'ordinary'}]}
    else:
        verdict = 'changes_required' if kind == 'decision' and 'decision' not in previous else 'approved'
        report = {'contract_version':2, 'verdict':verdict, 'reason':'inspected', 'inspected':['app.py'],
                  'correction':'fix candidate', 'dismissed_findings':[]}
    output.write_text(json.dumps(report))
else:
    role = args[args.index('--agent') + 1].replace('abdullah-', '')
    with history.open('a') as f: f.write(role + '\\n')
    if role == 'implementer':
        p = pathlib.Path('app.py')
        p.write_text(p.read_text() + '# implemented\\n')
    report = {'contract_version':2, 'status':'complete', 'summary':role, 'findings':[], 'evidence':['app.py:1'], 'files':['app.py'], 'tests':[], 'unknowns':[], 'blocker':''} if role == 'reviewer' else {'contract_version':2, 'status':'complete', 'summary':role, 'files':['app.py'], 'tests':[], 'evidence':['app.py:1'], 'unknowns':[], 'blocker':''}
    if role == 'explorer': report.update(files=['app.py'], tests=[], evidence=['app.py:1'], unknowns=[], blocker='')
    print(json.dumps({'type':'text','sessionID':'fake-session', 'part':{'text':json.dumps(report)}}))
    print(json.dumps({'type':'step_finish','sessionID':'fake-session', 'part':{'reason':'stop'}}))
''')
        fake.chmod(0o755)
        (fakebin / 'codex').symlink_to(fake)
        (fakebin / 'opencode').symlink_to(fake)
        history = self.root / 'history'
        env = {'PATH': str(fakebin) + ':' + os.environ['PATH'], 'FAKE_HISTORY': str(history), 'OPENAI_API_KEY': ''}
        with patch.dict(os.environ, env), patch.object(orc, 'load', return_value=(self.rundir, self.state)), patch.object(orc, 'config', return_value=self.cfg):
            report, _ = orc.call_model(self.rundir, None, self.cfg, 'explorer', 'explorer', 'explore', self.project, archive=self.rundir / 'explorations')
            self.assertEqual(report['summary'], 'explorer')
            orc.serve('test-run00')
        self.assertEqual(self.state['status'], 'complete')
        self.assertEqual(history.read_text().splitlines(), ['explorer', 'plan', 'implementer', 'reviewer', 'decision', 'implementer', 'reviewer', 'decision'])
        self.assertEqual(len(self.state['accepted_batches']), 1)
        self.assertTrue(self.state['final_verdict']['inspected'])

    def test_empty_checks_rejected(self):
        plan = {"status": "complete", "summary": "x", "batches": [{"title": "x", "goal": "x", "acceptance": [], "checks": [], "risk": "ordinary"}]}
        with self.assertRaises(ValueError):
            orc.validate_report("plan", plan)

    def test_failed_writer_requires_reconciliation(self):
        fake = self.root / 'opencode'
        fake.write_text('#!/bin/sh\nif [ "$1" = "--version" ]; then echo 1.18.35; exit; fi\necho "invalid response"\nexit 0\n')
        fake.chmod(0o755)
        with patch.dict(orc.os.environ, {'PATH': str(self.root) + ':' + orc.os.environ['PATH']}):
            with self.assertRaises(ValueError):
                orc.call_model(self.rundir, self.state, self.cfg, 'implementer', 'implementer', 'task', self.project)
        self.assertIsNotNone(self.state['active_job'])
        self.assertEqual(self.state['active_job']['status'], 'uncertain')
        orc.save(self.rundir, self.state)
        with patch.object(orc, 'load', return_value=(self.rundir, self.state)), patch.object(orc, 'advance') as advance:
            orc.serve('test-run00')
        advance.assert_not_called()
        self.assertEqual(self.state['status'], 'uncertain')

    def test_completed_check_results_are_reused_after_restart(self):
        batch = {'title': 'check', 'checks': [[sys.executable, '-c', 'pass']]}
        first = orc.run_checks(self.rundir, self.state, self.cfg, self.project, batch)
        self.assertTrue(first['passed'])
        state = orc.read_json(self.rundir / 'state.json')
        with patch.object(orc.subprocess, 'run', wraps=orc.subprocess.run) as run:
            second = orc.run_checks(self.rundir, state, self.cfg, self.project, batch)
        self.assertEqual(first['commands'], second['commands'])
        self.assertFalse(any(args.args[0] == batch['checks'][0] for args in run.call_args_list))

    def test_missing_role_mapping_is_rejected(self):
        with patch.dict(orc.STAGES, {'plan': {'role': 'missing', 'kind': 'plan'}}, clear=False):
            with self.assertRaises(ValueError):
                orc.validate_workflow()
