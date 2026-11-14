import json,os,sqlite3,sys
from pathlib import Path
repo=Path(sys.argv[1]);sys.path.insert(0,str(repo/'scripts/tests'))
from test_v31_aor31_corrections import CorrectionTests,orc

def probe(label,fn):
 t=CorrectionTests('test_clean_legacy_go_paths_remain_subscription')
 try:
  t.setUp();t.configure('1.18.35');print(json.dumps({'probe':label,**fn(t)}),flush=True)
 finally:t.tearDown();t.doCleanups()

def relative(t):
 t.write_json(t.root/'relative.json',{'provider':{'opencode-go':{'models':{'model':{}}}}})
 t.write_json(t.project/'relative.json',{'provider':{'opencode-go':{'options':{'baseURL':'https://child-relative.invalid/v1'},'models':{'model':{}}}}})
 os.environ['OPENCODE_CONFIG']='relative.json';prior=Path.cwd()
 try:os.chdir(t.root);result=t.preflight(t.route())
 finally:os.chdir(prior)
 return {'ok':result['ok'],'classification':result['classification'],'endpoint':result['observed'].get('endpoint_sha256'),'effective_files':result['observed']['effective_files']}

def account(t):
 db=t.root/'account.db'
 con=sqlite3.connect(db)
 con.executescript('''CREATE TABLE account(id TEXT PRIMARY KEY,email TEXT NOT NULL,url TEXT NOT NULL,access_token TEXT NOT NULL,refresh_token TEXT NOT NULL,token_expiry INTEGER,time_created INTEGER,time_updated INTEGER);
CREATE TABLE account_state(id INTEGER PRIMARY KEY,active_account_id TEXT,active_org_id TEXT);
INSERT INTO account VALUES('synthetic-account','test@example.invalid','https://org.invalid','dummy-access','dummy-refresh',4102444800000,0,0);
INSERT INTO account_state VALUES(1,'synthetic-account','synthetic-org');''');con.commit();con.close()
 os.environ['OPENCODE_DB']=str(db);t.addCleanup(lambda:os.environ.pop('OPENCODE_DB',None))
 result=t.preflight(t.route())
 return {'ok':result['ok'],'classification':result['classification'],'boundary':result['observed'].get('boundary'),'account_store_in_sources':any(x.get('path')==str(db) for x in result['observed']['source_identity'])}

def plugin(t):
 p=t.project/'.opencode/plugins/local.ts';p.parent.mkdir(parents=True)
 p.write_text('export const Local = async () => ({})\n')
 result=t.preflight(t.route())
 return {'ok':result['ok'],'classification':result['classification'],'boundary':result['observed'].get('boundary')}

probe('v1-relative-explicit-config-resolved-in-wrong-cwd',relative)
probe('v1-active-account-store-unobserved',account)
probe('v1-discovered-plugin-unobserved',plugin)
