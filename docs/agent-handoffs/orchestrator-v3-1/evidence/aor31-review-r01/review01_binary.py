"""Credential-free real V2 normalization/cache checks; no inference."""
import importlib.util,json,os,subprocess,sys,tempfile
from pathlib import Path
from unittest.mock import patch
repo=Path(sys.argv[1]);binary=str(Path(sys.argv[2]).resolve())
s=importlib.util.spec_from_file_location('aor31_review_binary',repo/'scripts/orchestrator.py')
o=importlib.util.module_from_spec(s);sys.modules[s.name]=o;s.loader.exec_module(o)
cfg=json.loads((repo/'scripts/config.example.json').read_text());cfg['runtime']['opencode_version']='2.2.7'
route={'provider':'opencode','worker_provider':'opencode-go','model':'opencode-go/go-model','effort':'low','billing':'api'}
def provider(url):return {'providers':{'opencode-go':{'settings':{'baseURL':url},'models':{}}}}
with tempfile.TemporaryDirectory(prefix='aor31-review-binary-') as tmp:
 root=Path(tmp);home=root/'home';home.mkdir();project=root/'repo';project.mkdir()
 subprocess.run(['git','init','-q',str(project)],check=True)
 env={'PATH':str(Path(binary).parent)+':'+os.environ['PATH'],'HOME':str(home),
      **{'XDG_'+name+'_HOME':str(home/name.lower()) for name in ['CONFIG','DATA','CACHE','STATE']},
      'OPENCODE_DISABLE_AUTOUPDATE':'1','OPENCODE_DISABLE_MODELS_FETCH':'1','OPENCODE_DISABLE_FREE_MODELS':'1'}
 parent=root/'opencode.json';parent.write_text(json.dumps(provider('https://parent-first.invalid/v1')))
 with patch.dict(os.environ,env,clear=True):
  first=o.opencode_provider_observation(route,project=project,cfg=cfg,role='explorer')
  first_pin=o.routing_fingerprint(route,cfg,project=project,role='explorer',observation=first)
  parent.write_text(json.dumps(provider('https://parent-second.invalid/v1')))
  second=o.opencode_provider_observation(route,project=project,cfg=cfg,role='explorer')
  second_pin=o.routing_fingerprint(route,cfg,project=project,role='explorer',observation=second)
  recheck=o._route_identity_recheck(dict(route,routing_fingerprint=first_pin),{'observed':first},cfg,project,'explorer')
  child=o.opencode_env('explorer','v2')
  real=subprocess.run([binary,'debug','config','--standalone'],cwd=project,env=child,capture_output=True,text=True,timeout=40)
  entries=json.loads(real.stdout) if real.returncode==0 else []
  endpoints=[x.get('info',{}).get('providers',{}).get('opencode-go',{}).get('settings',{}).get('baseURL') for x in entries if x.get('type')=='document']
  print(json.dumps({'probe':'real-v2-parent-config-cache','first_mode':first['inspection'],'first_endpoint':first.get('endpoint_sha256'),'second_endpoint':second.get('endpoint_sha256'),'pin_unchanged':first_pin==second_pin,'recheck_error':recheck,'real_exit':real.returncode,'fresh_binary_endpoints':endpoints,'source_records_include_parent':any(x.get('path')==str(parent) for x in first['source_identity'])}),flush=True)
  parent.unlink();o.OPENCODE_INSPECTION_CACHE.clear()
  mixed={'provider':{'opencode-go':{'options':{'baseURL':'https://legacy-retained.invalid/v1'}}},'providers':{'other-provider':{}}}
  (project/'opencode.json').write_text(json.dumps(mixed))
  actual=subprocess.run([binary,'debug','config','--standalone'],cwd=project,env=child,capture_output=True,text=True,timeout=40)
  documents=[x['info'].get('providers') for x in json.loads(actual.stdout) if x.get('type')=='document'] if actual.returncode==0 else []
  print(json.dumps({'probe':'real-v2-disjoint-native-legacy-normalization','real_exit':actual.returncode,'normalized_provider_documents':documents,'adapter_providers':o._opencode_normalize_v2_document(mixed).get('providers')}),flush=True)
