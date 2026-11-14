"""Residual correction review: only test-owned CLIs and disposable processes."""
import json,os,signal,subprocess,sys,tempfile,time
from pathlib import Path
from unittest.mock import patch
repo=Path(sys.argv[1]);sys.path.insert(0,str(repo/'scripts/tests'))
from test_v31_aor31_corrections import CorrectionTests,orc

def with_fixture(label,fn):
 t=CorrectionTests('test_clean_legacy_go_paths_remain_subscription')
 try:t.setUp();print(json.dumps({'probe':label,**fn(t)}),flush=True)
 finally:t.tearDown();t.doCleanups()

def mismatch(t):
 t.configure('1.18.35');os.environ['FAKE_OC_VERSION']='2.2.7'
 t.write_json(t.project/'opencode.json',{'providers':{'opencode-go':{'settings':{'baseURL':'https://v2-only.invalid/v1'},'models':{'model':{}}}}})
 route=t.route();route['effort']='';t.state['model_routes']={'explorer':route};orc.save(t.rundir,t.state)
 try:orc.opencode_dialect(version='2.2.7',cfg=t.cfg);expected='accepted'
 except Exception as e:expected=type(e).__name__+': '+str(e)
 commands=[];original=orc._spawn_guarded
 def spawn(cmd,*args,**kw):commands.append(cmd[:]);return original(cmd,*args,**kw)
 with patch.object(orc,'_spawn_guarded',side_effect=spawn):
  try:_,job=orc.call_model(t.rundir,t.state,t.cfg,'explorer','explorer','prompt',t.project);outcome='dispatched'
  except Exception as e:outcome=type(e).__name__+': '+str(e)
 return {'normal_version_gate':expected,'call_model':outcome,'commands':commands,'has_private_standalone':any('--standalone'in c for c in commands),'history':t.history.read_text() if t.history.exists() else ''}

def native_v1(t):
 t.configure('1.18.35');out=[]
 for label,entry in [
  ('provider.api',{'api':'https://provider-api.invalid/v1','models':{'model':{}}}),
  ('model.provider.api',{'models':{'model':{'provider':{'api':'https://model-api.invalid/v1'}}}}),
  ('provider.npm',{'npm':'@ai-sdk/anthropic','models':{'model':{}}})]:
  t.write_json(t.project/'opencode.json',{'provider':{'opencode-go':entry}})
  result=t.preflight(t.route())
  out.append({'field':label,'ok':result['ok'],'classification':result['classification'],'endpoint':result['observed'].get('endpoint_sha256'),'qualified':result['observed'].get('go_route')})
 return {'cases':out}

def version_deadline(t):
 t.configure('2.2.7');script=t.bin_dir/'fake.py'
 script.write_text(script.read_text().replace("if '--version' in args:","if '--version' in args:\n    time.sleep(0.6)"))
 t.write_json(t.project/'opencode.json',{'providers':{'opencode-go':{'models':{}}}})
 start=time.monotonic()
 try:orc.call_model(t.rundir,t.state,t.cfg,'explorer','explorer','prompt',t.project,route=t.route(),deadline=start+.08);outcome='completed'
 except Exception as e:outcome=type(e).__name__+': '+str(e)
 return {'elapsed':time.monotonic()-start,'stage_budget':.08,'outcome':outcome,'history':t.history.exists()}

with_fixture('prepared-launch-bypasses-version-pin',mismatch)
with_fixture('v1-native-routing-fields',native_v1)
with_fixture('version-inspection-overruns-stage-budget',version_deadline)

with tempfile.TemporaryDirectory(prefix='aor31-orphan-') as tmp:
 pidfile=Path(tmp)/'child.pid'
 parent=r'''import pathlib,subprocess,sys
child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
pathlib.Path(sys.argv[1]).write_text(str(child.pid))
print('[]')
'''
 pid=None
 try:
  result=orc._opencode_run_bounded([sys.executable,'-c',parent,str(pidfile)],Path(tmp),{'PATH':os.environ['PATH']},2)
  pid=int(pidfile.read_text());stat=orc.process_stat(pid)
  alive=bool(stat and stat['state']not in {'Z','X','x'})
  print(json.dumps({'probe':'inspector-leader-exits-with-live-child','returncode':result[0],'stdout':result[1].strip(),'child_alive_after_success':alive,'child_pgid':os.getpgid(pid) if alive else None}),flush=True)
 finally:
  if pid:
   try:os.kill(pid,signal.SIGKILL)
   except ProcessLookupError:pass
   until=time.monotonic()+3
   while time.monotonic()<until:
    stat=orc.process_stat(pid)
    if not stat or stat['state']in {'Z','X','x'}:break
    time.sleep(.01)
   assert not stat or stat['state']in {'Z','X','x'},'Diagnostic child survived cleanup'
