"""Replay saved Architect failures; assert the corrected outcomes."""
from pathlib import Path
import sys
repo = Path(sys.argv[1]).resolve()
original = repo / 'docs/agent-handoffs/orchestrator-v3-1/evidence/e2e-review-recovery-review-r01/review_probes.py'
source = original.read_text()
tail = 'fixture(missing_log)\nfixture(late_recovery)\n'
assert source.endswith(tail)
namespace = {'__name__': 'saved_review_probes'}
exec(compile(source[:-len(tail)], str(original), 'exec'), namespace)

def missing_log_safe(test):
    result = namespace['missing_log'](test)
    assert result['phase'] == 'review' and result['status'] == 'blocked'
    assert not result['recovery'] and result['rejection']['code'] == 'log_missing'
    assert result['rejection']['masked_code'] == 'provenance_drift'
    return {'probe': 'missing-log-and-path-drift', 'phase': result['phase'],
            'status': result['status'], 'code': result['rejection']['code'],
            'recovery': False, 'masked_code': result['rejection']['masked_code']}

def late_recovery_safe(test):
    try:
        namespace['late_recovery'](test)
    except RuntimeError as exc:
        assert 'invalidated authority epoch' in str(exc), str(exc)
        state = test.state_file()
        assert state['authority_epoch'] == 1 and state['phase'] == 'review'
        assert not state.get('report_recoveries')
        assert not (test.job_dir / 'recovered-report.json').exists()
        return {'probe': 'recover-old-review-after-invalidation', 'refused': True,
                'error': str(exc), 'run_epoch': state['authority_epoch'],
                'phase': state['phase'], 'recovery_records': 0}
    raise AssertionError('Old review was unexpectedly authorized')

namespace['fixture'](missing_log_safe)
namespace['fixture'](late_recovery_safe)
