"""Run: uv run python -m scripts.simulate_reports.dev_smoke
Goal: prepare DB + run one daily on 2026-03-21 end-to-end."""
from datetime import date
from pathlib import Path
import shutil
from .env_bootstrap import set_env
from . import config

def main():
    set_env()
    from .runner import call_daily
    from .notifier_stub import drain_outbox_for_run

    scenario_dir = config.SCENARIOS_DIR / "_smoke-2026-03-21"
    shutil.rmtree(scenario_dir, ignore_errors=True)
    scenario_dir.mkdir(parents=True, exist_ok=True)

    run_id = call_daily(date(2026, 3, 21))
    print("run_id =", run_id)

    # Copy business outputs
    for p in config.REPORT_WORK_DIR.glob("*.html"):
        shutil.copy2(p, scenario_dir / p.name)
    for p in config.REPORT_WORK_DIR.glob("*.xlsx"):
        shutil.copy2(p, scenario_dir / p.name)
    for p in config.REPORT_WORK_DIR.glob("*.json"):
        shutil.copy2(p, scenario_dir / p.name)

    drained = drain_outbox_for_run(run_id, scenario_dir)
    print("drained outbox:", drained)


if __name__ == "__main__":
    main()
