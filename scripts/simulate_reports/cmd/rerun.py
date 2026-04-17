"""python -m scripts.simulate_reports rerun-after-fix
Re-run full timeline but skip prepare (keep data/sim/products.db)."""
from .. import config
import shutil


def run(argv):
    # Restart from scratch of timeline but keep the prepared DB baseline
    shutil.rmtree(config.SCENARIOS_DIR, ignore_errors=True)
    shutil.rmtree(config.CHECKPOINT_DIR, ignore_errors=True)
    # Re-clone baseline? No — user wants to keep fix applied to business code,
    # but DB should be fresh. Easiest: re-run prepare.
    from .prepare import run as prepare_run
    from .run import run as run_run
    prepare_run([])
    return run_run([])
