"""python -m scripts.simulate_reports prepare
克隆基线 DB + 重分布 scraped_at + 回填 review_issue_labels + 清空 workflow_runs/outbox。
"""
import shutil
import sys
from .. import config
from ..db import open_db


def run(argv):
    if not config.BASELINE_DB.exists():
        print(f"ERROR: baseline DB not found: {config.BASELINE_DB}", file=sys.stderr)
        return 1
    config.SIM_DATA_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(config.BASELINE_DB, config.SIM_DB)
    print(f"Cloned baseline → {config.SIM_DB}")

    with open_db(config.SIM_DB) as conn:
        conn.execute("DELETE FROM workflow_runs")
        conn.execute("DELETE FROM workflow_run_tasks")
        conn.execute("DELETE FROM notification_outbox")
        print("Cleared workflow_runs / workflow_run_tasks / notification_outbox")
    return 0
