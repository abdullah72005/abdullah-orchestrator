"""Architect diagnostics only: no run/serve inference, credentials, or live config."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

REPO = Path(sys.argv[1])
BINARY = Path(sys.argv[2]).resolve()
spec = importlib.util.spec_from_file_location('aor31_probe', REPO / 'scripts/orchestrator.py')
orc = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = orc
spec.loader.exec_module(orc)

def config(endpoint='absent', legacy=False):
    entry = {'models': {}}
    if endpoint != 'absent':
        entry['options' if legacy else 'settings'] = {'baseURL': endpoint}
    return {'$schema': 'https://opencode.ai/config.json',
            'provider' if legacy else 'providers': {'opencode-go': entry}}

def run(label, glob, explicit=None, custom=None, project=None, inline=None):
    with tempfile.TemporaryDirectory(prefix='aor31-route-') as tmp:
        root = Path(tmp)
        home = root / 'home'
        repo = root / 'repo'
        repo.mkdir()
        home.mkdir()
        subprocess.run(['git', 'init', '-q', str(repo)], check=True)
        env = {'PATH': os.environ['PATH'], 'HOME': str(home),
               'XDG_CONFIG_HOME': str(home / 'config'),
               'XDG_DATA_HOME': str(home / 'data'),
               'XDG_CACHE_HOME': str(home / 'cache'),
               'XDG_STATE_HOME': str(home / 'state'),
               'OPENCODE_DISABLE_AUTOUPDATE': 'true',
               'OPENCODE_DISABLE_MODELS_FETCH': 'true',
               'OPENCODE_DISABLE_FREE_MODELS': '1'}
        for path, data in [(home / 'config/opencode/opencode.json', glob),
                           (root / 'explicit.json', explicit),
                           (root / 'custom/opencode.json', custom),
                           (repo / 'opencode.json', project)]:
            if data is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(data))
        if explicit is not None: env['OPENCODE_CONFIG'] = str(root / 'explicit.json')
        if custom is not None: env['OPENCODE_CONFIG_DIR'] = str(root / 'custom')
        if inline is not None: env['OPENCODE_CONFIG_CONTENT'] = json.dumps(inline)
        cfg = json.loads((REPO / 'scripts/config.example.json').read_text())
        cfg['runtime']['opencode_version'] = '2.2.7'
        route = {'provider': 'opencode', 'worker_provider': 'opencode-go',
                 'model': 'opencode-go/deepseek-v4.1-flash', 'effort': 'low', 'billing': 'go'}
        with patch.dict(os.environ, env, clear=True):
            observation = orc.opencode_provider_observation(route, repo, 'v2', cfg, 'explorer')
            preflight = orc.route_preflight('explorer', route, cfg, repo)
            child = orc.opencode_env('explorer', 'v2')
        child.update(env)
        # Preserve the generated inline controls, exactly as the worker receives them.
        with patch.dict(os.environ, env, clear=True):
            child['OPENCODE_CONFIG_CONTENT'] = orc.opencode_env('explorer', 'v2')['OPENCODE_CONFIG_CONTENT']
        proc = subprocess.run([str(BINARY), 'debug', 'config', '--standalone'],
                              cwd=repo, env=child, capture_output=True, text=True, timeout=40)
        output = {'probe': label, 'exit': proc.returncode,
                  'preflight_ok': preflight['ok'], 'classification': preflight['classification'],
                  'observed_endpoint_sha256': observation.get('endpoint_sha256'),
                  'observed_files': observation.get('effective_files'),
                  'reasons': preflight['reasons']}
        if proc.returncode == 0:
            output['normalized_documents'] = [x for x in json.loads(proc.stdout) if x.get('type') == 'document']
        else: output['stderr'] = proc.stderr[-1000:]
        if explicit is not None:
            with patch.dict(os.environ, env, clear=True):
                old_pin = orc.routing_fingerprint(route, cfg, project=repo, dialect='v2', role='explorer')
                (root / 'explicit.json').write_text(json.dumps(config('https://changed.invalid/v1')))
                new_pin = orc.routing_fingerprint(route, cfg, project=repo, dialect='v2', role='explorer')
            output['explicit_endpoint_edit_pin_unchanged'] = old_pin == new_pin
        print(json.dumps(output), flush=True)

run('R1-global-retained-with-custom-dir', config('https://global.invalid/v1'), custom={})
run('R2-explicit-after-global', config(None), explicit=config('https://explicit.invalid/v1'))
run('R3-custom-dir-versus-project', config(), custom=config('https://custom.invalid/v1'), project=config(None))
run('R4-legacy-provider-global-normalization', config('https://legacy.invalid/v1', legacy=True))
run('R5-explicit-after-custom-global-root', None, custom=config(None), explicit=config('https://explicit-custom.invalid/v1'))
run('R6-unchanged-legacy-go', config(legacy=True))
