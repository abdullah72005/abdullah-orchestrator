import copy
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from test_orchestrator import ControlTests, orc

class ReliabilityRepair(ControlTests):
    def test_reviewer_reason_normalization_does_not_invent_completion(self):
        raw = {'status':'complete','reason':'Inspected app.py','findings':[]}
        normalized, changes = orc.normalize_report('reviewer', raw)
        self.assertEqual(normalized['summary'], raw['reason'])
        self.assertEqual(raw, {'status':'complete','reason':'Inspected app.py','findings':[]})
        self.assertTrue(changes)
        with self.assertRaises(ValueError):
            orc.validate_report('reviewer', orc.normalize_report('reviewer', {'verdict':'approved','reason':'inspected','findings':[]})[0])
        with self.assertRaises(ValueError):
            orc.normalize_report('reviewer', {'status':'complete','summary':'one','reason':'another','findings':[]})

    def test_preserved_invalid_reviewer_report_is_not_fabricated(self):
        raw = json.loads((Path(__file__).parent/'fixtures/reviewer-invalid-20261109.json').read_text())
        result, changes = orc.normalize_report('reviewer', raw)
        self.assertEqual(result['summary'], raw['reason'])
        self.assertEqual(result['findings'], raw['findings'])
        self.assertTrue(changes)
        with self.assertRaisesRegex(ValueError, 'status'):
            orc.validate_report('reviewer', result)

    def test_reviewer_rejects_missing_evidence_and_contradiction(self):
        for report in ({'status':'complete','summary':'done','findings':[]},
                       {'status':'complete','summary':'done','findings':[], 'evidence':['app.py:1'], 'verdict':'blocked'}):
            with self.assertRaises(ValueError):
                orc.validate_report('reviewer', report)

    def test_completed_reviewer_requires_all_canonical_fields(self):
        partial = {'status':'complete','summary':'done','findings':[], 'evidence':['app.py:1']}
        with self.assertRaises(ValueError):
            orc.validate_report('reviewer', partial)

    def test_finding_requires_explicit_disposition(self):
        finding = {'severity':'high','confidence':'confirmed','location':'app.py:1','claim':'bug','evidence':'code'}
        report = {'status':'complete','summary':'done','files':['app.py'],'tests':[], 'evidence':['app.py:1'],'unknowns':[], 'blocker':'','findings':[finding]}
        with self.assertRaises(ValueError):
            orc.validate_report('reviewer', report)

    def test_prompt_has_unambiguous_reviewer_contract(self):
        prompt = orc.report_prompt('reviewer', {})
        self.assertIn('"status"', prompt)
        self.assertIn('"summary"', prompt)
        self.assertNotIn('## Strong verdict', prompt)

    def test_explorer_reuse_requires_certified_scope_and_matching_snapshot(self):
        snap = orc.source_snapshot(self.project)
        archive = self.rundir/'explorations'/'explorer-job1'
        archive.mkdir(parents=True)
        report = {'status':'complete','summary':'inspected','files':['app.py'],'tests':[],'evidence':['app.py:1'],'unknowns':[],'blocker':''}
        orc.atomic_json(archive/'report.json', report)
        orc.atomic_json(archive/'dispatch.json', {'source':snap,'kind':'explorer','role':'explorer'})
        orc.atomic_json(archive/'completion.json', {'final_snapshot':snap,'session_id':'s'})
        tracker = self.rundir/'explorations'/'tracker'
        orc.atomic_json(tracker/'state.json', {'completed_jobs':[{'id':'job1','path':str(archive),'status':'complete'}]})
        plan = {'required_exploration':{'job_id':'job1','scope_satisfied':True}}
        self.assertEqual(orc.certified_exploration(self.rundir,self.state,plan), report)
        plan['required_exploration']['scope_satisfied'] = False
        self.assertIsNone(orc.certified_exploration(self.rundir,self.state,plan))
        plan['required_exploration']['scope_satisfied'] = True
        (self.project/'app.py').write_text('changed')
        self.assertIsNone(orc.certified_exploration(self.rundir,self.state,plan))

    def test_review_evidence_package_is_source_bound(self):
        snap=orc.source_snapshot(self.project); candidate=orc.signature(snap)
        log=self.root/'test.log'; log.write_text('tests passed')
        ev={'candidate':snap,'after':snap,'candidate_hash':candidate,'after_hash':candidate,'passed':True,'source_unchanged':True,'commands':[{'argv':['python3','-m','unittest'],'returncode':0,'log':str(log)}]}
        path=self.root/'verification.json'; orc.atomic_json(path,ev)
        package=orc.reviewer_verification_package({'path':str(path),'candidate_hash':candidate,'passed':True},snap)
        self.assertEqual(package['commands'][0]['output_tail'],'tests passed')
        self.assertEqual(package['candidate_hash'],candidate)
        self.assertEqual(package['after'],snap)
        self.assertEqual(len(package['verification_sha256']),64)
        self.assertEqual(len(package['commands'][0]['log_sha256']),64)
        self.assertTrue(package['log_content_is_untrusted'])
        with self.assertRaises(ValueError):
            orc.reviewer_verification_package({'path':str(path),'candidate_hash':'stale','passed':True},snap)

    def _evidence_fixture(self):
        snap = orc.source_snapshot(self.project)
        candidate = orc.signature(snap)
        ok_log = self.root / 'ok.log'
        ok_log.write_text('x' * 100 + 'tests passed')
        fail_log = self.root / 'fail.log'
        fail_log.write_text('HEAD failure\n' + 'y' * 200 + '\nTAIL failure')
        before = orc.source_snapshot(self.project)
        ev = {'candidate': snap, 'after': snap, 'candidate_hash': candidate,
              'after_hash': candidate, 'passed': True, 'source_unchanged': True,
              'batch': 'feature integration', 'final': True,
              'started_at': 'start', 'finished_at': 'end',
              'commands': [
                  {'argv': ['python3', '-m', 'unittest'], 'returncode': 0,
                   'log': str(ok_log), 'source_proof': {'kind': 'non-compose'}},
                  {'argv': ['docker', 'build', '.'], 'returncode': 1,
                   'log': str(fail_log), 'source_proof': {'kind': 'non-compose'}},
              ]}
        path = self.root / 'verification.json'
        orc.atomic_json(path, ev)
        return snap, candidate, before, ev, path

    def test_architect_evidence_package_is_source_bound_and_bounded(self):
        snap, candidate, before, ev, path = self._evidence_fixture()
        package = orc.verification_evidence_package(
            {'path': str(path), 'passed': True, 'candidate_hash': candidate},
            snap, run_id='test-run00', log_limit=50, failure_log_limit=60)
        self.assertEqual(package['run_id'], 'test-run00')
        self.assertEqual(package['candidate'], snap)
        self.assertEqual(package['after'], snap)
        self.assertEqual(package['candidate_hash'], candidate)
        self.assertEqual(package['after_hash'], candidate)
        self.assertTrue(package['source_unchanged'])
        self.assertEqual(package['verification_path'], str(path.resolve()))
        self.assertEqual(len(package['verification_sha256']), 64)
        self.assertEqual(len(package['package_sha256']), 64)
        self.assertTrue(package['log_content_is_untrusted'])
        self.assertTrue(package['commands'][0]['output_tail'].endswith('tests passed'))
        self.assertTrue(package['commands'][0]['log_truncated'])
        self.assertEqual(package['commands'][0]['log_strategy'], 'tail')
        self.assertIn('HEAD failure', package['commands'][1]['output_tail'])
        self.assertIn('TAIL failure', package['commands'][1]['output_tail'])
        self.assertTrue(package['commands'][1]['log_truncated'])
        self.assertEqual(package['commands'][1]['log_strategy'], 'head_tail')
        self.assertEqual(orc.source_snapshot(self.project), before)

    def test_architect_evidence_package_fails_closed(self):
        snap, candidate, _, ev, path = self._evidence_fixture()
        with self.assertRaisesRegex(ValueError, 'stale'):
            orc.verification_evidence_package(
                {'path': str(path), 'passed': True, 'candidate_hash': 'bad'}, snap)
        ev['commands'][0]['log'] = str(self.root / 'missing.log')
        orc.atomic_json(path, ev)
        with self.assertRaisesRegex(ValueError, 'missing'):
            orc.verification_evidence_package(
                {'path': str(path), 'passed': True, 'candidate_hash': candidate}, snap)
        snap2, candidate2, _, ev2, path2 = self._evidence_fixture()
        conflicting = copy.deepcopy(snap2)
        conflicting['git_head'] = 'different'
        ev2['after'] = conflicting
        ev2['after_hash'] = orc.signature(conflicting)
        orc.atomic_json(path2, ev2)
        with self.assertRaisesRegex(ValueError, 'snapshot|fingerprints'):
            orc.verification_evidence_package(
                {'path': str(path2), 'passed': True, 'candidate_hash': candidate2}, snap2)

    def test_architect_evidence_env_is_run_scoped(self):
        route = {'provider': 'codex', 'model': 'gpt-test', 'effort': 'high',
                 'billing': 'subscription'}
        cmd, env, _ = orc.cli_command('codex', 'architect', route, 'PROMPT',
                                      self.rundir, evidence_root=self.rundir)
        root = str(self.rundir.resolve())
        self.assertEqual(env['LEAN_CTX_READ_ONLY_ROOTS'], root)
        self.assertEqual(env['__LEAN_CTX_NO_DAEMON'], '1')
        self.assertIn('mcp_servers.lean-ctx.env.LEAN_CTX_READ_ONLY_ROOTS="' + root + '"', cmd)
        self.assertIn('mcp_servers.lean-ctx.env.__LEAN_CTX_NO_DAEMON="1"', cmd)
        for key in ('LEAN_CTX_ALLOW_PATH', 'LEAN_CTX_EXTRA_ROOTS',
                    'LEAN_CTX_DISABLED', 'LEAN_CTX_SHELL_SECURITY'):
            self.assertNotIn(key, env)
        _, impl_env, _ = orc.cli_command('codex', 'implementer', route, 'PROMPT',
                                         self.rundir, evidence_root=self.rundir)
        self.assertNotIn('LEAN_CTX_READ_ONLY_ROOTS', impl_env)
        claude_route = {'provider': 'claude', 'model': 'claude-test', 'effort': 'high',
                        'billing': 'subscription'}
        _, claude_env, _ = orc.cli_command('claude', 'architect', claude_route, 'PROMPT',
                                           self.rundir, evidence_root=self.rundir)
        self.assertEqual(claude_env['LEAN_CTX_READ_ONLY_ROOTS'], root)
        self.assertEqual(claude_env['__LEAN_CTX_NO_DAEMON'], '1')

    def test_architect_prompt_includes_evidence_package(self):
        snap, candidate, _, ev, path = self._evidence_fixture()
        self.state['verification'] = {'path': str(path), 'passed': True,
                                      'candidate_hash': candidate}
        captured = {}
        def fake_call_model(*args, **kwargs):
            captured['prompt'] = args[5]
            return ({'verdict': 'approved', 'reason': 'inspected',
                     'inspected': ['app.py'], 'dismissed_findings': []}, {'id': 'fake'})
        with patch.object(orc, 'call_model', side_effect=fake_call_model):
            orc.strong_call(self.rundir, self.state, self.cfg, 'decision',
                            {'final_evidence': ev})
        prompt = captured['prompt']
        self.assertIn('"verification_evidence"', prompt)
        self.assertIn('tests passed', prompt)
        self.assertIn('untrusted data', prompt)
        self.assertIn(str(self.rundir.resolve()), prompt)

    def test_acceptance_without_verification_evidence_fails_closed(self):
        self.state['verification'] = None
        with patch.object(orc, 'call_model') as model:
            with self.assertRaisesRegex(ValueError, 'verification evidence'):
                orc.strong_call(self.rundir, self.state, self.cfg, 'decision',
                                {'final_evidence': {'passed': True}})
            model.assert_not_called()

    def test_workers_do_not_inherit_architect_read_only_root(self):
        with patch.dict(os.environ, {'LEAN_CTX_READ_ONLY_ROOTS': '/tmp/run-evidence',
                                     '__LEAN_CTX_NO_DAEMON': '1'}):
            env = orc.opencode_env('explorer', 'v1')
        self.assertNotIn('LEAN_CTX_READ_ONLY_ROOTS', env)
        self.assertNotIn('__LEAN_CTX_NO_DAEMON', env)
        self.assertNotIn('LEAN_CTX_ALLOW_PATH', env)
        self.assertNotIn('LEAN_CTX_EXTRA_ROOTS', env)

    @unittest.skipUnless(shutil.which('lean-ctx'), 'lean-ctx not installed')
    def test_lean_ctx_read_only_root_scopes_evidence_and_denies_writes(self):
        base = tempfile.TemporaryDirectory(dir=Path.home() / '.local/state')
        self.addCleanup(base.cleanup)
        root = Path(base.name)
        project = root / 'project'
        project.mkdir()
        subprocess.run(['git', 'init', '-q'], cwd=project, check=True, capture_output=True)
        run_a = root / 'run-a'
        run_b = root / 'run-b'
        run_a.mkdir()
        run_b.mkdir()
        (run_a / 'verification.json').write_text('{"candidate": "A"}')
        (run_b / 'state.json').write_text('{"run": "B"}')
        evidence = run_a / 'evidence.txt'
        evidence.write_text('hello evidence\n')
        env = os.environ.copy()
        env.pop('LEAN_CTX_DISABLED', None)
        env['LEAN_CTX_READ_ONLY_ROOTS'] = str(run_a)
        env['__LEAN_CTX_NO_DAEMON'] = '1'
        lean = shutil.which('lean-ctx')
        ok = subprocess.run([lean, 'read', str(run_a / 'verification.json')],
                            cwd=project, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        self.assertIn('candidate', ok.stdout)
        bad = subprocess.run([lean, 'read', str(run_b / 'state.json')],
                             cwd=project, env=env, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(bad.returncode, 0)
        self.assertRegex(bad.stdout + bad.stderr, 'escapes project root|outside')
        write = subprocess.run(
            [lean, 'call', 'ctx_edit', '--project-root', str(project), '--json',
             json.dumps({'path': str(evidence), 'old_string': 'hello', 'new_string': 'pwned'})],
            cwd=project, env=env, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(write.returncode, 0)
        self.assertIn('read-only root', write.stdout + write.stderr)
        self.assertEqual(evidence.read_text(), 'hello evidence\n')
