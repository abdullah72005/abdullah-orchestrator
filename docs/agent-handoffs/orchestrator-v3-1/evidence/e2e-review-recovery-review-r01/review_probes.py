import json, os, sys
from pathlib import Path
from unittest.mock import patch
repo=Path(sys.argv[1]);sys.path.insert(0,str(repo/'scripts/tests'))
from test_v31_review_recovery import ReviewRecoveryTests,make_plan,orc
from test_report_ingestion import RecoveryRegressions,REVIEWER

def fixture(fn):
 t=ReviewRecoveryTests('test_saved_incident_shape_rewinds_once_and_fresh_pipeline_completes')
 try:t.setUp();print(json.dumps(fn(t)),flush=True)
 finally:t.tearDown();t.doCleanups()

def missing_log(t):
 t.prepare(make_plan(),phase='review',review=False)
 v=orc.read_json(Path(t.state_file()['verification']['path']))
 Path(v['commands'][0]['log']).unlink()
 with t.drifting_path(),patch.object(orc,'call_model',side_effect=AssertionError('unexpected model')):
  stage_result=t.stage('review')
 s=t.state_file()
 return {'probe':'missing-log-and-path-drift','phase':s['phase'],'status':s['status'],'recovery':bool(s.get('review_recovery')),'rejection':s.get('verification_rejection'),'stage_result':stage_result}

def late_recovery(t):
 cfg=orc.read_json(orc.CONFIG_PATH);cfg.setdefault('authorization',{})['sensitive_cli_enabled']=True;orc.atomic_json(orc.CONFIG_PATH,cfg);t.cfg=orc.config();t.state['config_sha256']=orc.configuration_provenance()['sha256'];orc.save(t.rundir,t.state)
 t.data_root=t.root/'opencode-data';t.tree=RecoveryRegressions._commit_candidate(t)
 t.prepare_blocked_review()
 t.job_id='oldreview01';t.job_dir=t.rundir/'jobs'/('reviewer-'+t.job_id);t.job_dir.mkdir(parents=True)
 RecoveryRegressions._write_job(t,json.dumps(REVIEWER),'stop')
 t.state['failed_jobs'][0].update(kind='reviewer',role='reviewer',authority_epoch=0)
 orc.atomic_json(t.job_dir/'dispatch.json',{'kind':'reviewer','role':'reviewer','source':orc.source_snapshot(t.project),'authority_epoch':0})
 t.state['project_lease']={'status':'active','run_id':t.state['id'],'project':str(t.project)};t.state['status']='running';orc.save(t.rundir,t.state)
 with t.drifting_path():
  t.stage('review');t.stage('verify')
  s=t.state_file();s['status']='paused';orc.save(t.rundir,s)
  result=orc.recover_report(s['id'],t.job_id,apply=True,acknowledge=f"recover-report:{s['id']}:{t.job_id}",data_root=t.data_root)
  s=t.state_file();cached=orc.cached_recovered_job_report(t.rundir,s,'reviewer')
  t.resume()
  with patch.object(orc,'call_model',side_effect=AssertionError('unexpected new model')) as model:t.stage('review')
  final=t.state_file()
  return {'probe':'recover-old-review-after-invalidation','applied':result['applied'],'original_job_epoch':s['failed_jobs'][0]['authority_epoch'],'run_epoch':s['authority_epoch'],'recovered_epoch':s['report_recoveries'][-1].get('authority_epoch'),'old_report_cache_eligible':bool(cached),'phase_after_review':final['phase'],'new_reviewer_calls':model.call_count}
fixture(missing_log)
fixture(late_recovery)
