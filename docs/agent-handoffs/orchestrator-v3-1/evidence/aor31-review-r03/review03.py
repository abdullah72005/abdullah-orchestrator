"""Final-boundary review diagnostics; disposable databases and owned fakes only."""
import json,os,signal,sqlite3,sys,tempfile,time
from pathlib import Path
from unittest.mock import patch
repo=Path(sys.argv[1]);sys.path.insert(0,str(repo/'scripts/tests'))
from test_v31_aor31_r02 import V1SourceBoundaryTests,orc

def fixture(label,fn):
 t=V1SourceBoundaryTests('test_clean_legacy_go_controls_remain_subscription')
 try:t.setUp();t.configure('1.18.35');t.clean_v1();print(json.dumps({'probe':label,**fn(t)}),flush=True)
 finally:t.tearDown();t.doCleanups()

def relative_db(t):
 original=t.account_db(active=True)
 actual=t.home/'.local/share/opencode/selected.db';actual.parent.mkdir(parents=True)
 original.rename(actual)
 os.environ['OPENCODE_DB']='selected.db';t.addCleanup(lambda:os.environ.pop('OPENCODE_DB',None))
 r=t.preflight(t.route())
 return {'actual_upstream_store':str(actual),'project_shadow_exists':(t.project/'selected.db').exists(),'ok':r['ok'],'classification':r['classification'],'account_record':r['observed']['boundary'].get('account_store'),'hazards':r['observed']['boundary']['external_hazards']}

def session_write(t):
 db=t.root/'session-store.db';con=sqlite3.connect(db)
 con.executescript('''CREATE TABLE account(id TEXT PRIMARY KEY);
CREATE TABLE account_state(id INTEGER PRIMARY KEY,active_account_id TEXT,active_org_id TEXT);
INSERT INTO account_state VALUES(1,NULL,NULL);
CREATE TABLE session(id TEXT PRIMARY KEY,title TEXT);
INSERT INTO session VALUES('test-session','first');''');con.commit();con.close()
 os.environ['OPENCODE_DB']=str(db);t.addCleanup(lambda:os.environ.pop('OPENCODE_DB',None))
 route=t.route();first=orc.opencode_provider_observation(route,t.project,cfg=t.cfg,role='explorer')
 route['routing_fingerprint']=orc.routing_fingerprint(route,t.cfg,project=t.project,observation=first,role='explorer')
 before=orc.route_preflight('explorer',route,t.cfg,t.project,t.state,run_dir=t.rundir)
 con=sqlite3.connect(db);con.execute("UPDATE session SET title='ordinary-session-write'");con.commit();con.close()
 after=orc.route_preflight('explorer',route,t.cfg,t.project,t.state,run_dir=t.rundir)
 a=before['observed']['boundary']['account_store'];b=after['observed']['boundary']['account_store']
 return {'before_ok':before['ok'],'after_ok':after['ok'],'reason':after['reasons'],'account_counts':[a['accounts'],b['accounts']],'active_flags':[a['active'],b['active']],'tables_same':a['tables']==b['tables'],'db_digest_changed':a['sha256']!=b['sha256']}

fixture('v1-relative-database-hidden-account',relative_db)
fixture('unrelated-session-write-invalidates-route',session_write)

with tempfile.TemporaryDirectory(prefix='aor31-fast-exit-') as tmp:
 root=Path(tmp);release=root/'release';pidfile=root/'child.pid'
 parent=r'''import pathlib,subprocess,sys,time
while not pathlib.Path(sys.argv[1]).exists(): time.sleep(.001)
child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],start_new_session=True,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
pathlib.Path(sys.argv[2]).write_text(str(child.pid))
print('[]')
'''
 original=orc._opencode_track_descendants;pid=None
 def scan_then_release(leader,tracked):
  original(leader,tracked)
  release.write_text('after-empty-snapshot')
 try:
  with patch.object(orc,'_opencode_track_descendants',side_effect=scan_then_release):
   try:rc,out,_=orc._opencode_run_bounded([sys.executable,'-c',parent,str(release),str(pidfile)],root,{'PATH':os.environ['PATH']},2);outcome={'returncode':rc,'stdout':out.strip()}
   except Exception as exc:outcome={'error':type(exc).__name__+': '+str(exc)}
  pid=int(pidfile.read_text());stat=orc.process_stat(pid)
  alive=bool(stat and stat['state']not in {'Z','X','x'})
  print(json.dumps({'probe':'detached-child-after-ownership-snapshot',**outcome,'child_alive_after_return':alive,'scheduling_seam':'real empty descendant scan, then release parent to spawn/exit within communicate interval'}),flush=True)
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
