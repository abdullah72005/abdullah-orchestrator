"""Denied containment at the production call boundary; clean up owned PID."""
import json,os,signal,sys,time
from pathlib import Path
from unittest.mock import patch
repo=Path(sys.argv[1]);sys.path.insert(0,str(repo/'scripts/tests'))
from test_v31_aor31_r02 import InspectorLifecycleTests,orc
t=InspectorLifecycleTests('test_denied_termination_retains_ownership_and_fails_closed')
real_kill=os.kill;real_killpg=os.killpg;pid=None
try:
 t.setUp();t.configure('2.2.7');t.clean_v2()
 os.environ['FAKE_OC_MODE']='sleep';pidfile=t.root/'config-inspector.pid';os.environ['FAKE_OC_PID']=str(pidfile)
 with patch.object(orc,'OPENCODE_INSPECTION_TIMEOUT',.1),patch.object(orc.os,'kill',side_effect=PermissionError),patch.object(orc.os,'killpg',side_effect=PermissionError):
  try:orc.call_model(t.rundir,t.state,t.cfg,'explorer','explorer','prompt',t.project,route=t.route());outcome='completed'
  except Exception as exc:outcome=type(exc).__name__+': '+str(exc)
 pid=int(pidfile.read_text());stat=orc.process_stat(pid)
 alive=bool(stat and stat['state']not in {'Z','X','x'})
 state=orc.read_json(t.rundir/'state.json')
 print(json.dumps({'probe':'denied-containment-loses-run-ownership','outcome':outcome,'inspector_alive':alive,'status':state['status'],'active_job':state.get('active_job'),'active_check':state.get('active_check'),'inspector_pid_retained_in_state':str(pid)in json.dumps(state),'preflight_reason':state.get('preflight_rejection',{}).get('observed',{}).get('inspection_reason')}),flush=True)
finally:
 if pid:
  try:real_killpg(pid,signal.SIGKILL)
  except OSError:pass
  try:real_kill(pid,signal.SIGKILL)
  except OSError:pass
  until=time.monotonic()+3
  while time.monotonic()<until:
   stat=orc.process_stat(pid)
   if not stat or stat['state']in {'Z','X','x'}:break
   time.sleep(.01)
  assert not stat or stat['state']in {'Z','X','x'},'Diagnostic inspector survived cleanup'
 t.tearDown();t.doCleanups()
