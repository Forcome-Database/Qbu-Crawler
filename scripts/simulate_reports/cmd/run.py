"""python -m scripts.simulate_reports run"""
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path
from .. import config
from ..env_bootstrap import set_env
from ..db import open_db


def _scenario_dirname(sid, sc):
    slug = sc.description.split("（")[0].split(" —")[0]
    slug = (slug.replace(" ", "-").replace("/", "-").replace(":", "-"))[:40]
    return f"{sid}-{sc.logical_date.isoformat()}-{slug}"


def _copy_business_outputs(scenario_dir: Path):
    for src in config.REPORT_WORK_DIR.glob("*"):
        if src.is_file():
            shutil.copy2(src, scenario_dir / src.name)
    # Purge REPORT_WORK_DIR so next scenario starts clean
    for p in config.REPORT_WORK_DIR.glob("*"):
        if p.is_file():
            p.unlink()


def run(argv):
    set_env()
    from ..timeline import TIMELINE, apply_events
    from ..scenarios import SCENARIOS
    from ..runner import call_daily, call_weekly, call_monthly
    from ..notifier_stub import drain_outbox_for_run
    from ..debug_dump import (
        dump_db_state, dump_workflow_run, dump_outbox_rows,
        dump_analytics_tree, dump_top_reviews, dump_html_checksum,
        dump_excel_structure, dump_events_applied,
    )
    from ..manifest import build_manifest, write_manifest, collect_actual
    from ..checkpoint import save as save_checkpoint

    config.SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)
    # Move legacy products in reports/
    config.LEGACY_DIR.mkdir(parents=True, exist_ok=True)
    for p in config.REPORT_ROOT.glob("daily-*.*"):
        shutil.move(str(p), config.LEGACY_DIR / p.name)
    for p in config.REPORT_ROOT.glob("workflow-run-*.*"):
        shutil.move(str(p), config.LEGACY_DIR / p.name)

    cur = config.TIMELINE_START
    while cur <= config.TIMELINE_END:
        sids_today = TIMELINE.get(cur, [])
        if not sids_today:
            cur += timedelta(days=1)
            continue
        # Apply all events for the day once (accumulated across scenarios)
        all_events_applied = []
        # Dump BEFORE state once
        _sample_sid = sids_today[0]
        _tmp_dir = config.SCENARIOS_DIR / f"_day-{cur.isoformat()}"
        _tmp_dir.mkdir(parents=True, exist_ok=True)
        dump_db_state("before", _tmp_dir)

        with open_db(config.SIM_DB) as conn:
            for sid in sids_today:
                sc = SCENARIOS[sid]
                if sc.events:
                    applied = apply_events(conn,
                                           logical_date=cur,
                                           events=sc.events)
                    all_events_applied.extend(applied)
        # Dump AFTER state (once per day)
        dump_db_state("after", _tmp_dir)

        for sid in sids_today:
            sc = SCENARIOS[sid]
            scenario_dir = config.SCENARIOS_DIR / _scenario_dirname(sid, sc)
            shutil.rmtree(scenario_dir, ignore_errors=True)
            scenario_dir.mkdir(parents=True, exist_ok=True)
            # Copy day-level debug into each scenario that day
            shutil.copytree(_tmp_dir / "debug", scenario_dir / "debug",
                            dirs_exist_ok=True)
            dump_events_applied(all_events_applied, scenario_dir)

            print(f"\n=== {sid} {sc.logical_date} ({sc.tier}) ===")
            try:
                if sc.tier == "daily":
                    run_id = call_daily(sc.logical_date)
                elif sc.tier == "weekly":
                    run_id = call_weekly(sc.logical_date)
                elif sc.tier == "monthly":
                    run_id = call_monthly(sc.logical_date)
                else:
                    continue
            except Exception as e:
                import traceback
                (scenario_dir / "ERROR.txt").write_text(
                    traceback.format_exc(), encoding="utf-8"
                )
                print(f"  ERROR: {e}", file=sys.stderr)
                continue

            _copy_business_outputs(scenario_dir)
            dump_workflow_run(run_id, scenario_dir)
            dump_outbox_rows(run_id, scenario_dir)
            dump_analytics_tree(run_id, scenario_dir)
            dump_top_reviews(run_id, scenario_dir)
            dump_html_checksum(scenario_dir)
            dump_excel_structure(scenario_dir)
            drain_outbox_for_run(run_id, scenario_dir)

            actual = collect_actual(run_id=run_id, scenario_dir=scenario_dir,
                                    expected=sc.expected)
            manifest = build_manifest(
                scenario_id=sid, logical_date=sc.logical_date,
                phase=sc.phase, description=sc.description, tier=sc.tier,
                expected=sc.expected, actual=actual,
                artifacts=[p.name for p in scenario_dir.iterdir() if p.is_file()],
            )
            write_manifest(scenario_dir, manifest)
            print(f"  verdict: {manifest['verdict']}")

        # Cleanup day-level tmp
        shutil.rmtree(_tmp_dir, ignore_errors=True)
        # Checkpoint
        save_checkpoint(cur)
        cur += timedelta(days=1)

    print("\nAll done. Run 'index' to build index.html, 'verify' to summarize issues.")
    return 0
