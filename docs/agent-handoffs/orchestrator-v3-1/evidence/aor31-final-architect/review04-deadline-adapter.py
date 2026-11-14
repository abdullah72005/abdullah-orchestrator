"""Replay saved deadline scenario; adapt only the renamed unittest fixture method."""
from pathlib import Path
import sys
repo = Path(sys.argv[1])
original = repo / "docs/agent-handoffs/orchestrator-v3-1/evidence/aor31/deadline_probe.py"
text = original.read_text()
old = "test_sequential_checks_are_clipped_to_one_stage_deadline"
new = "test_expired_budget_before_next_child_blocks_verification"
assert text.count(old) == 1
exec(compile(text.replace(old, new), str(original), "exec"), {"__name__": "__main__"})
