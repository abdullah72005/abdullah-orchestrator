import unittest
import contextlib
import io
import json
import os
from types import SimpleNamespace
from unittest.mock import patch
from test_orchestrator import ControlTests, orc, dead_process_identity


class QuotaChanges(unittest.TestCase):
    def setUp(self):
        ControlTests.setUp(self)
        self.state['single_batch_fast_path'] = True
    def test_single_batch_accept_runs_final_checks_before_one_decision(self):
        snap = orc.source_snapshot(self.project)
        candidate = orc.signature(snap)
        self.state.update(phase='accept', plan={'batches': [{'title':'one', 'checks':[['true']]}]},
                          verification={'candidate_hash':candidate, 'passed':True},
                          review={'status':'complete', 'findings':[]})
        evidence = {'passed':True, 'candidate_hash':candidate, 'source_unchanged':True, 'commands':[]}
        verdict = {'verdict':'approved', 'reason':'inspected', 'inspected':['app.py'], 'dismissed_findings':[]}
        with patch.object(orc, 'run_checks', return_value=evidence) as checks, patch.object(orc, 'strong_call', return_value=verdict) as strong:
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertTrue(checks.call_args.kwargs['final'])
        self.assertEqual(strong.call_count, 1)
        self.assertEqual(self.state['status'], 'complete')
        self.assertEqual(len(self.state['accepted_batches']), 1)

    def test_explorer_requires_full_evidence(self):
        with self.assertRaises(ValueError):
            orc.validate_report('explorer', {'status':'complete', 'summary':'done'})

    def test_explorer_cli_run_identifiers(self):
        for args in (['explore', 'test-run00', '--task', 'inspect'],
                     ['explore', '--run', 'test-run00', '--task', 'inspect']):
            with self.subTest(args=args), patch.object(orc, 'explore') as explore:
                self.assertEqual(orc.main(args), 0)
                self.assertEqual(explore.call_args.args[0].run, 'test-run00')
        for args in (['explore', '--task', 'inspect'],
                     ['explore', 'one', '--run', 'two', '--task', 'inspect']):
            with self.subTest(args=args), patch.object(orc, 'explore') as explore, contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(orc.main(args), 2)
                self.assertIn('exactly one run ID', err.getvalue())
                explore.assert_not_called()

    def test_architect_explorer_command_uses_positional_id(self):
        self.state['explorer_policy'] = 'on_demand'
        context = orc.architect_context(self.rundir, self.state, 'plan')
        self.assertIn(' explore ' + self.state['id'] + ' --task ', context['explorer_dispatch'])
        self.assertNotIn(' explore --run ', context['explorer_dispatch'])

    def test_handoff_rejects_missing_authorization(self):
        with self.assertRaisesRegex(ValueError, 'authorization'):
            orc.validate_handoff({}, self.project, False)

    def test_context_does_not_repeat_current_batch_in_plan(self):
        batch = {'title':'unique batch', 'goal':'implement', 'acceptance':['x'], 'checks':[['true']], 'risk':'ordinary'}
        self.state['plan'] = {'summary':'plan', 'invariants':['x'], 'batches':[batch]}
        context = orc.architect_context(self.rundir, self.state, 'decision')
        self.assertNotIn('batches', context['approved_plan'])
        self.assertEqual(context['batch'], batch)

    def handoff(self):
        return {'goal':'Add a feature', 'provenance':'Approved by user', 'architectural_decisions':'Keep API stable',
                'execution_restrictions':'No deploy', 'source':orc.source_snapshot(self.project),
                'plan':{'status':'complete', 'summary':'approved', 'invariants':['Keep API stable'], 'blocker':'',
                        'batches':[{'title':'one','goal':'change','acceptance':['works'], 'checks':[['true']], 'risk':'ordinary'}]}}

    def test_handoff_valid_stale_and_incomplete(self):
        handoff = self.handoff()
        self.assertEqual(orc.validate_handoff(handoff, self.project, True, 'Add a feature'), handoff['plan'])
        with self.assertRaises(ValueError):
            orc.validate_handoff(handoff, self.project, True, 'different goal')
        handoff['plan']['batches'][0]['acceptance'] = []
        with self.assertRaises(ValueError):
            orc.validate_handoff(handoff, self.project, True, 'Add a feature')
        handoff = self.handoff()
        (self.project / 'app.py').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'stale'):
            orc.validate_handoff(handoff, self.project, True, 'Add a feature')

    def test_explicit_handoff_start_persists_and_skips_planning(self):
        goal = self.root / 'goal.txt'
        goal.write_text('Add a feature')
        handoff = self.root / 'handoff.json'
        handoff.write_text(json.dumps(self.handoff()))
        args = SimpleNamespace(project=str(self.project), goal_file=str(goal), approved_handoff=str(handoff),
                               authorize_handoff=True, plan_approval=False, require_explorer=False,
                               skip_doctor=True, host='codex', background=False)
        with patch.object(orc, 'DEFAULT_STATE', self.root / 'new-runs'), patch.object(orc, 'serve') as serve, contextlib.redirect_stdout(io.StringIO()):
            orc.begin(args)
            state = orc.read_json(next((self.root / 'new-runs').glob('*/state.json')))
        serve.assert_called_once()
        self.assertEqual(state['phase'], 'implement')
        self.assertTrue(state['handoff_authorization']['explicit_user_authorization'])
        self.assertEqual(state['approved_handoff']['execution_restrictions'], 'No deploy')

    def test_handoff_detects_source_change_after_required_exploration(self):
        self.state.update(phase='implement', handoff_authorization={'explicit_user_authorization':True},
                          baseline=orc.source_snapshot(self.project), plan=self.handoff()['plan'],
                          completed_jobs=[{'role':'explorer'}])
        (self.project / 'app.py').write_text('changed')
        with patch.object(orc, 'call_model') as model:
            orc.advance(self.rundir, self.state, self.cfg)
        model.assert_not_called()
        self.assertEqual(self.state['status'], 'blocked')

    def test_changed_candidate_goes_back_to_verification(self):
        self.state.update(phase='accept', plan={'batches':[{'title':'one','checks':[['true']]}]},
                          verification={'candidate_hash':'old','passed':True}, review={'status':'complete','findings':[]})
        with patch.object(orc, 'strong_call') as strong:
            orc.advance(self.rundir, self.state, self.cfg)
        strong.assert_not_called()
        self.assertEqual(self.state['phase'], 'verify')
        self.assertIsNone(self.state['review'])

    def test_failed_final_checks_do_not_accept(self):
        candidate = orc.signature(orc.source_snapshot(self.project))
        self.state.update(phase='accept', plan={'batches':[{'title':'one','checks':[['false']]}]},
                          verification={'candidate_hash':candidate,'passed':True}, review={'status':'complete','findings':[]})
        with patch.object(orc, 'strong_call') as strong:
            orc.advance(self.rundir, self.state, self.cfg)
        strong.assert_not_called()
        self.assertEqual(self.state['status'], 'blocked')

    def test_incomplete_review_does_not_accept(self):
        candidate = orc.signature(orc.source_snapshot(self.project))
        self.state.update(phase='accept', plan={'batches':[{'title':'one','checks':[['true']]}]},
                          verification={'candidate_hash':candidate,'passed':True}, review={'status':'blocked','findings':[]})
        with patch.object(orc, 'strong_call') as strong:
            orc.advance(self.rundir, self.state, self.cfg)
        strong.assert_not_called()
        self.assertEqual(self.state['status'], 'blocked')

    def test_recovered_decision_is_consumed_without_second_call(self):
        snap = orc.source_snapshot(self.project)
        candidate = orc.signature(snap)
        self.state.update(phase='accept', plan={'batches':[{'title':'one','checks':[['true']]}]},
                          verification={'candidate_hash':candidate,'passed':True}, review={'status':'complete','findings':[]})
        verdict = {'verdict':'approved','reason':'inspected','inspected':['app.py'],'dismissed_findings':[]}
        self.state['single_batch_verification'] = dict(self.state['verification'])
        orc.run_checks(self.rundir, self.state, self.cfg, self.project, {'title':'feature integration','checks':[['true']]}, final=True)
        jobdir = self.rundir / 'jobs' / 'decision-recovered'
        jobdir.mkdir(parents=True)
        orc.atomic_json(jobdir / 'execution.json', {'returncode':0})
        orc.atomic_json(jobdir / 'report.json', verdict)
        orc.atomic_json(jobdir / 'completion.json', {'final_snapshot':snap, 'session_id':None})
        self.state['active_job'] = {'id':'recovered', 'kind':'decision', 'role':'architect', 'path':str(jobdir), 'status':'running', **dead_process_identity()}
        self.assertTrue(orc.recover_finished_dispatch(self.rundir, self.state))
        with patch.object(orc, 'strong_call') as strong:
            orc.advance(self.rundir, self.state, self.cfg)
        strong.assert_not_called()
        self.assertEqual(self.state['status'], 'complete')

    def test_consumed_blocked_decision_gets_new_evidence_aware_call(self):
        snap = orc.source_snapshot(self.project)
        candidate = orc.signature(snap)
        log = self.root / 'test.log'
        log.write_text('tests passed')
        evidence = {'candidate': snap, 'after': snap, 'candidate_hash': candidate,
                    'after_hash': candidate, 'passed': True, 'source_unchanged': True,
                    'commands': [{'argv': ['true'], 'returncode': 0, 'log': str(log)}]}
        path = self.root / 'verification.json'
        orc.atomic_json(path, evidence)
        verdict = {'verdict': 'approved', 'reason': 'inspected',
                   'inspected': ['app.py'], 'dismissed_findings': []}
        self.state.update(
            phase='accept', status='blocked',
            plan={'batches': [{'title': 'one', 'checks': [['true']]}]},
            verification={'path': str(path), 'candidate_hash': candidate, 'passed': True},
            review={'status': 'complete', 'findings': []},
            single_batch_fast_path=True, last_consumed_job_id='decision-old',
            completed_jobs=[{'id': 'decision-old', 'kind': 'decision', 'role': 'architect',
                             'path': str(self.rundir / 'jobs' / 'decision-old'),
                             'status': 'complete'}])
        with patch.object(orc, 'run_checks', return_value=evidence) as checks, \
                patch.object(orc, 'strong_call', return_value=verdict) as strong:
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(strong.call_count, 1)
        self.assertTrue(checks.call_args.kwargs['final'])
        self.assertEqual(self.state['status'], 'complete')
        self.assertEqual(self.state['final_verdict']['verdict'], 'approved')

    def test_serious_finding_cannot_be_silently_accepted(self):
        candidate = orc.signature(orc.source_snapshot(self.project))
        finding = {'severity':'high','confidence':'confirmed','location':'app.py:1','claim':'bug','evidence':'code'}
        self.state.update(phase='accept', plan={'batches':[{'title':'one','checks':[['true']]}]},
                          verification={'candidate_hash':candidate,'passed':True}, review={'status':'complete','findings':[finding]})
        verdict = {'verdict':'approved','reason':'inspected','inspected':['app.py'],'dismissed_findings':[]}
        with patch.object(orc, 'strong_call', return_value=verdict):
            orc.advance(self.rundir, self.state, self.cfg)
        self.assertEqual(self.state['status'], 'blocked')
        self.assertFalse(self.state['accepted_batches'])

    def test_explorer_adapter_tracks_real_fake_process_and_blocks_duplicate_after_interruption(self):
        fake = self.root / 'opencode'
        fake.write_text('''#!/usr/bin/env python3
import json, sys, time
if '--version' in sys.argv:
    print('1.18.35'); sys.exit(0)
assert sys.argv[sys.argv.index('--variant')+1] == 'low'
assert sys.argv[sys.argv.index('--model')+1].startswith('opencode-go/')
if 'interrupt-me' in sys.argv[-1]: time.sleep(5)
report={'status':'complete','summary':'read','files':['app.py'],'tests':[], 'evidence':['app.py:1'], 'unknowns':[], 'blocker':''}
print(json.dumps({'type':'text','sessionID':'ses_fake','part':{'text':json.dumps(report)}}))
''')
        fake.chmod(0o755)
        self.state.update(explorer_policy='on_demand', status='running', phase='plan',
                          active_job={'id': 'parent-job', 'role': 'architect',
                                      'status': 'running'})
        args = SimpleNamespace(run='test-run00', task='inspect app',
                               parent_job='parent-job')
        with patch.object(orc, 'load', return_value=(self.rundir, self.state)), patch.object(orc, 'config', return_value=self.cfg), patch.dict(os.environ, {'PATH':str(self.root)+':'+os.environ['PATH']}), contextlib.redirect_stdout(io.StringIO()):
            orc.explore(args)
            tracker = self.rundir / 'explorations' / 'tracker'
            state = orc.read_json(tracker / 'state.json')
            self.assertEqual(state['completed_jobs'][-1]['session_id'], 'ses_fake')
            self.cfg['limits']['max_worker_seconds'] = 0.1
            args.task = 'interrupt-me'
            with self.assertRaises(TimeoutError):
                orc.explore(args)
            with self.assertRaisesRegex(RuntimeError, 'reconciliation'):
                orc.explore(args)
            orc.reconcile_explorer('test-run00')
            self.assertIsNone(orc.read_json(tracker / 'state.json')['active_job'])
