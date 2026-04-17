"""python -m scripts.simulate_reports reset — wipe all sim artifacts."""
import shutil
from .. import config


def run(argv):
    shutil.rmtree(config.SIM_DATA_DIR, ignore_errors=True)
    shutil.rmtree(config.SCENARIOS_DIR, ignore_errors=True)
    for p in (config.INDEX_HTML, config.ISSUES_MD):
        if p.exists():
            p.unlink()
    print("Reset complete.")
    return 0
