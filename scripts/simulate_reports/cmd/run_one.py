"""python -m scripts.simulate_reports run-one <SID>"""
from datetime import timedelta
from .. import config


def run(argv):
    if not argv:
        print("Usage: run-one <SID>"); return 2
    sid = argv[0]
    # Lazy imports
    from ..scenarios import SCENARIOS
    if sid not in SCENARIOS:
        print(f"Unknown SID: {sid}"); return 2
    sc = SCENARIOS[sid]
    target_date = sc.logical_date
    day_before = target_date - timedelta(days=1)

    from ..checkpoint import restore_before
    restored = restore_before(target_date)
    if restored is None:
        print("No checkpoint available; run full 'run' first or run from scratch.")
        return 2
    print(f"Restored checkpoint @ {restored} (target {target_date})")

    # Replay days between restored+1 and day_before using timeline,
    # then run the target day's scenarios.
    from ..timeline import TIMELINE
    from .run import run as run_full  # reuse partial of run logic
    # Simplest approach: monkey-patch TIMELINE_START/END to [restored+1, target]
    orig_start, orig_end = config.TIMELINE_START, config.TIMELINE_END
    config.TIMELINE_START = restored + timedelta(days=1)
    config.TIMELINE_END = target_date
    try:
        run_full([])
    finally:
        config.TIMELINE_START = orig_start
        config.TIMELINE_END = orig_end
    return 0
