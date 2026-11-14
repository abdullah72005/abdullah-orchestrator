"""Disposable production-boundary mutation and separate-process ledger probes."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

REPO = Path(sys.argv[1])
sys.path.insert(0, str(REPO / 'scripts/tests'))
from test_v31_stage_invariants import StageInvariantTests, orc

test = StageInvariantTests('test_plan_mutation_blocks_and_preserves_source_report_and_diagnostics')
try:
    test.setUp()
    (test.project / '.gitignore').write_text('ignored_helper.py\n')
    helper = test.project / 'ignored_helper.py'
    helper.write_text('value = 7\n')
    fake = test.fakebin / 'fake_cli.py'
    fake.write_text(fake.read_text().replace("app = pathlib.Path('app.py')",
                                           "app = pathlib.Path('ignored_helper.py')"))
    os.environ['FAKE_MUTATION'] = 'tracked'
    before = orc.source_snapshot(test.project)
    try:
        result = test.dispatch('plan')
        outcome = 'accepted'
    except Exception as exc:
        outcome = type(exc).__name__ + ': ' + str(exc)
    after = orc.source_snapshot(test.project)
    print(json.dumps({'probe': 'ignored-python-planning', 'outcome': outcome,
                      'helper_before': before['runtime_inputs']['files'].get('ignored_helper.py'),
                      'helper_after': after['runtime_inputs']['files'].get('ignored_helper.py'),
                      'projection_equal': orc.source_write_projection(before) == orc.source_write_projection(after),
                      'mutated': orc.source_mutation(before, after)['mutated'],
                      'completed_jobs': len(test.state['completed_jobs']),
                      'preserved_mutation': '# mutated' in helper.read_text()}), flush=True)
finally:
    test.tearDown()
    test.doCleanups()

CHILD = r'''
import importlib.util,json,sys,time
from pathlib import Path
src,run,identity,ready=sys.argv[1:]
s=importlib.util.spec_from_file_location('ledger_probe',src)
o=importlib.util.module_from_spec(s);sys.modules[s.name]=o;s.loader.exec_module(o)
entry=json.loads((Path(run)/'entry.json').read_text())
if ready:
    original=o._save_grant_ledger
    def slow_save(folder,ledger):
        Path(ready).write_text('locked')
        time.sleep(0.5)
        original(folder,ledger)
    o._save_grant_ledger=slow_save
start=time.monotonic()
try:
    used,_=o._reserve_in_ledger(Path(run),entry,identity,'explorer','route')
    print(json.dumps({'id':identity,'ok':True,'used':used,'seconds':time.monotonic()-start}))
except Exception as exc:
    print(json.dumps({'id':identity,'ok':False,'error':str(exc),'seconds':time.monotonic()-start}))
'''
with tempfile.TemporaryDirectory(prefix='aor31-ledger-') as tmp:
    folder = Path(tmp)
    entry = {'id': 'grant', 'role': 'explorer', 'route_sha256': 'route',
             'max_dispatches': 2, 'used': 0, 'run_id': 'diagnostic'}
    (folder / 'entry.json').write_text(json.dumps(entry))
    orc.register_route_grant(folder, entry)
    ready = folder / 'ready'
    args = [sys.executable, '-c', CHILD, str(REPO / 'scripts/orchestrator.py'), str(folder)]
    first = subprocess.Popen(args + ['one', str(ready)], stdout=subprocess.PIPE, text=True)
    until = time.monotonic() + 10
    while not ready.exists():
        if time.monotonic() >= until: raise TimeoutError('holder did not acquire lock')
        time.sleep(0.01)
    second = subprocess.run(args + ['two', ''], capture_output=True, text=True, timeout=10, check=True)
    out, _ = first.communicate(timeout=10)
    ledger = orc.load_grant_ledger(folder)
    print(json.dumps({'probe': 'two-eligible-reservations-capacity-two',
                      'first': json.loads(out), 'second': json.loads(second.stdout),
                      'final_used': orc._grant_usage(ledger['grants']['grant'])}), flush=True)
