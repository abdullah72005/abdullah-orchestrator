"""Exercise genuine expired-budget branch with only test-owned state and CLIs."""
import json
from pathlib import Path
import sys

repo = Path(sys.argv[1])
sys.path.insert(0, str(repo / 'scripts/tests'))
from test_v31_stage_deadline import StageDeadlineTests, orc

test = StageDeadlineTests('test_sequential_checks_are_clipped_to_one_stage_deadline')
try:
    test.setUp()
    test.configure_stage(0.001)
    plan = {'contract_version': 2, 'status': 'complete', 'summary': 'plan',
            'invariants': ['Keep behavior'], 'blocker': '',
            'batches': [{'title': 'one', 'goal': 'g', 'acceptance': ['a'],
                         'risk': 'ordinary', 'checks': [[sys.executable, '-c', 'pass']]}]}
    test.state.update(phase='verify', plan=plan, plan_version=orc.content_hash(plan),
                      batch_index=0, single_batch_fast_path=False)
    orc.save(test.rundir, test.state)
    result = orc.stage_run('test-run00')
    state = orc.read_json(test.rundir / 'state.json')
    print(json.dumps({'ok': result['ok'], 'stage': result['stage'],
                      'pause_reason': result.get('pause_reason'),
                      'phase': state['phase'], 'status': state['status'],
                      'verification': state.get('verification'),
                      'completed_jobs': len(state['completed_jobs']),
                      'active_job': state.get('active_job')}))
finally:
    test.tearDown()
    test.doCleanups()
