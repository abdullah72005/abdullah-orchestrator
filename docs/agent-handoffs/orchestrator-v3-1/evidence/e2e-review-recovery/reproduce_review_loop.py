"""Offline reproduction using a disposable test fixture; never opens incident state."""
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

repo = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(repo / 'scripts/tests'))
from test_v31_acceptance_integrity import AcceptanceIntegrityTests, make_plan, orc

test = AcceptanceIntegrityTests('test_cached_decision_evidence_byte_replacement_is_rejected')
try:
    test.setUp()
    evidence = test.prepare(make_plan(), phase='review', review=False)
    original_bytes = Path(evidence['path']).read_bytes()
    implementation = {'status': 'complete', 'summary': 'already implemented'}
    test.state['implementation'] = implementation
    orc.save(test.rundir, test.state)
    empty = test.root / 'empty-path-entry'
    empty.mkdir()
    attempts = []
    with patch.dict(os.environ, {'PATH': str(empty) + os.pathsep + os.environ['PATH']}), \
         patch.object(orc, 'call_model', side_effect=AssertionError('unexpected model dispatch')) as model:
        for index in range(2):
            if index:
                state = orc.read_json(test.rundir / 'state.json')
                orc.modify_locked(test.rundir, state, state['id'], 'resume')
            result = orc.stage_run(test.state['id'])
            state = orc.read_json(test.rundir / 'state.json')
            attempts.append({'phase': state['phase'], 'status': state['status'],
                             'error': result.get('error'),
                             'next_action': result.get('next_action'),
                             'verification_still_passed': state['verification']['passed'],
                             'active_job': state.get('active_job'),
                             'active_check': state.get('active_check')})
            assert state['phase'] == 'review' and state['status'] == 'blocked'
            assert 'environment, toolchain' in result.get('error', '')
            assert state['implementation'] == implementation
        assert model.call_count == 0
    assert Path(evidence['path']).read_bytes() == original_bytes
    print(json.dumps({'reproduced_review_livelock': True, 'attempts': attempts,
                      'model_dispatches': 0, 'historical_record_preserved': True}))
finally:
    test.tearDown()
    test.doCleanups()
