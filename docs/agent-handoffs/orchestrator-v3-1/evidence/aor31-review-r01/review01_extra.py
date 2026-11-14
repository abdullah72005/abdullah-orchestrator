import json,os,sys,time,threading
from pathlib import Path
from unittest.mock import patch
repo=Path(sys.argv[1]);sys.path.insert(0,str(repo/'scripts/tests'))
from test_v31_route_sources import RouteSourceTests,orc
from test_v31_grant_ledger import FakeTTY

t=RouteSourceTests('test_grant_identity_binds_material_not_only_the_label')
try:
 t.setUp();t.configure('1.18.35');orc.OPENCODE_INSPECTION_CACHE.clear()
 t.write_json(t.project/'opencode.json',t.provider('https://grant-first.invalid/v1',legacy=True))
 route=t.route('api');t.state['model_routes']={'explorer':route};orc.save(t.rundir,t.state)
 with patch.object(orc.sys,'stdin',FakeTTY()):
  grant=orc.authorize_route_run('test-run00','explorer',max_dispatches=2,confirmation='authorize-route:test-run00')
 state=orc.read_json(t.rundir/'state.json')
 t.write_json(t.project/'opencode.json',t.provider('https://grant-second.invalid/v1',legacy=True))
 result=orc.route_preflight('explorer',route,t.cfg,t.project,state,run_dir=t.rundir)
 print(json.dumps({'probe':'public-grant-on-unpinned-route','grant_recorded':grant['ok'],'route_has_pin':bool(route.get('routing_fingerprint')),'changed_endpoint_ok':result['ok'],'authorized':result.get('authorization',{}).get('authorized'),'endpoint_observed':result['observed'].get('endpoint_sha256')}),flush=True)
finally:t.tearDown();t.doCleanups()

t=RouteSourceTests('test_inspector_is_bounded_and_fully_cleaned_up')
thread=None
try:
 t.setUp();t.configure('2.2.7');orc.OPENCODE_INSPECTION_CACHE.clear()
 t.write_json(t.project/'opencode.json',t.provider())
 os.environ['FAKE_OC_MODE']='sleep';pid=t.root/'inspector.pid';os.environ['FAKE_OC_PID']=str(pid)
 def cancel():
  deadline=time.monotonic()+5
  while not pid.exists() and time.monotonic()<deadline:time.sleep(.005)
  orc.atomic_json(t.rundir/'control.json',{'action':'cancel'})
 thread=threading.Thread(target=cancel);thread.start();start=time.monotonic()
 with patch.object(orc,'OPENCODE_INSPECTION_TIMEOUT',.4),patch.object(orc,'_spawn_guarded',wraps=orc._spawn_guarded) as spawn:
  try:orc.call_model(t.rundir,t.state,t.cfg,'explorer','explorer','prompt',t.project,route=t.route());outcome='completed'
  except Exception as exc:outcome=type(exc).__name__+': '+str(exc)
  count=spawn.call_count
 print(json.dumps({'probe':'cancel-during-inspection','outcome':outcome,'elapsed':time.monotonic()-start,'inference_spawn_calls_after_cancel':count,'control':orc.control(t.rundir)}),flush=True)
finally:
 if thread:thread.join(timeout=6)
 t.tearDown();t.doCleanups()
