import json,os,sys
from pathlib import Path
from unittest.mock import patch

repo=Path(sys.argv[1])
sys.path.insert(0,str(repo/'scripts/tests'))
from test_v31_route_sources import RouteSourceTests,orc
from test_v31_runtime_write_integrity import RuntimeWriteIntegrityTests

def run_route(label,fn):
 t=RouteSourceTests('test_default_legacy_go_stays_a_subscription_without_a_grant')
 try:
  t.setUp();orc.OPENCODE_INSPECTION_CACHE.clear();print(json.dumps({'probe':label,**fn(t)}),flush=True)
 finally:
  t.tearDown();t.doCleanups()

def home_dir(t):
 t.configure('1.18.35')
 t.write_json(t.home/'.opencode/opencode.json',t.provider('https://home-late.invalid/v1',legacy=True))
 r=orc.route_preflight('explorer',t.route(),t.cfg,t.project,t.state,run_dir=t.rundir)
 return {'ok':r['ok'],'classification':r['classification'],'files':r['observed']['effective_files']}

def legacy_order(t):
 t.configure('1.18.35')
 t.write_json(t.home/'.config/opencode/opencode.json',t.provider('https://global-later.invalid/v1',legacy=True))
 t.write_json(t.home/'.config/opencode/config.json',{'provider':{'opencode-go':{'options':{'baseURL':None}}}})
 r=orc.route_preflight('explorer',t.route(),t.cfg,t.project,t.state,run_dir=t.rundir)
 return {'ok':r['ok'],'classification':r['classification'],'endpoint':r['observed'].get('endpoint_sha256')}

def coexistence(t):
 t.configure('2.2.7')
 document=t.provider('https://legacy-retained.invalid/v1',legacy=True)
 document['providers']={'other-provider':{}}
 t.write_json(t.project/'opencode.json',document)
 os.environ['FAKE_OC_MODE']='fail'
 r=orc.route_preflight('explorer',t.route(),t.cfg,t.project,t.state,run_dir=t.rundir)
 return {'ok':r['ok'],'classification':r['classification'],'mode':r['observed']['inspection'],'providers':r['observed']['providers'],'warnings':r['warnings']}

def child_context(t):
 t.configure('2.2.7')
 t.write_json(t.project/'opencode.json',t.provider())
 capture=t.root/'capture.json'
 fake=t.bin_dir/'fake.py'
 fake.write_text(fake.read_text().replace("if 'models' in args:","if 'run' in args:\n    pathlib.Path(os.environ['FAKE_ROUTE_CAPTURE']).write_text(os.environ['OPENCODE_CONFIG_CONTENT'])\nif 'models' in args:"))
 os.environ['FAKE_ROUTE_CAPTURE']=str(capture)
 t.addCleanup(lambda:os.environ.pop('FAKE_ROUTE_CAPTURE',None))
 route=orc.model_route(t.cfg,'codex','explorer',project=t.project)
 t.state['model_routes']={'explorer':route}
 original=orc.source_snapshot
 def snapshot(*args,**kwargs):
  result=original(*args,**kwargs)
  os.environ['OPENCODE_CONFIG_CONTENT']=json.dumps(t.provider('https://after-preflight.invalid/v1'))
  return result
 try:
  with patch.object(orc,'source_snapshot',side_effect=snapshot):
   _,job=orc.call_model(t.rundir,t.state,t.cfg,'explorer','explorer','prompt',t.project)
  outcome='dispatched'
 except Exception as e:outcome=type(e).__name__+': '+str(e)
 inline=json.loads(capture.read_text()) if capture.exists() else {}
 return {'outcome':outcome,'captured_providers':inline.get('providers'),'grant_count':len(t.state.get('route_authorizations',[])),'history':t.history.read_text() if t.history.exists() else ''}

run_route('v1-home-opencode-omitted',home_dir)
run_route('v1-legacy-global-order-reversed',legacy_order)
run_route('v2-fallback-drops-disjoint-legacy-provider',coexistence)
run_route('child-inline-changes-after-recheck',child_context)

t=RuntimeWriteIntegrityTests('test_ignored_python_write_in_a_read_only_stage_is_refused')
try:
 t.setUp()
 t.ignored('.cache/','runtime')
 t.write('.cache/lib/unused.txt','stable\n')
 t.write('.cache/shared.py','value=1\n')
 (t.project/'.cache/lib/module.py').symlink_to('../shared.py')
 (t.project/'runtime').symlink_to('.cache/lib')
 before=orc.source_snapshot(t.project)
 os.environ.update(FAKE_WRITE_MODE='write',FAKE_WRITE_PATH='.cache/shared.py')
 try:t.dispatch('plan');outcome='accepted'
 except Exception as e:outcome=type(e).__name__+': '+str(e)
 after=orc.source_snapshot(t.project)
 print(json.dumps({'probe':'nested-runtime-symlink-target','outcome':outcome,'before_complete':before['runtime_inputs']['complete'],'after_complete':after['runtime_inputs']['complete'],'projection_equal':orc.source_write_projection(before)==orc.source_write_projection(after),'completed':len(t.state['completed_jobs'])}),flush=True)
finally:t.tearDown();t.doCleanups()
