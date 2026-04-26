import sqlite3
import pytest
from qbu_crawler.server.report_analytics import determine_report_semantics

@pytest.fixture
def conn(tmp_path):
    db = tmp_path / "test.db"
    c = sqlite3.connect(str(db))
    c.executescript("""
        CREATE TABLE workflow_runs (
            id INTEGER PRIMARY KEY,
            workflow_type TEXT,
            status TEXT,
            logical_date TEXT,
            trigger_key TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    yield c
    c.close()

def test_first_run_is_bootstrap(conn):
    """首次运行：之前无 completed run → bootstrap"""
    cur = conn.cursor()
    cur.execute("INSERT INTO workflow_runs (workflow_type,status,logical_date,trigger_key) VALUES ('daily','running','2026-04-26','daily:2026-04-26')")
    run_id = cur.lastrowid
    conn.commit()
    assert determine_report_semantics(conn, run_id) == "bootstrap"

def test_second_run_with_prior_completed_is_incremental(conn):
    """已有 completed run → incremental"""
    cur = conn.cursor()
    cur.execute("INSERT INTO workflow_runs (workflow_type,status,logical_date,trigger_key) VALUES ('daily','completed','2026-04-26','daily:2026-04-26')")
    cur.execute("INSERT INTO workflow_runs (workflow_type,status,logical_date,trigger_key) VALUES ('daily','running','2026-04-27','daily:2026-04-27')")
    run_id = cur.lastrowid
    conn.commit()
    assert determine_report_semantics(conn, run_id) == "incremental"

def test_failed_prior_runs_dont_count(conn):
    """之前的 failed run 不算 baseline → 仍 bootstrap"""
    cur = conn.cursor()
    cur.execute("INSERT INTO workflow_runs (workflow_type,status,logical_date,trigger_key) VALUES ('daily','failed','2026-04-26','daily:2026-04-26')")
    cur.execute("INSERT INTO workflow_runs (workflow_type,status,logical_date,trigger_key) VALUES ('daily','running','2026-04-27','daily:2026-04-27')")
    run_id = cur.lastrowid
    conn.commit()
    assert determine_report_semantics(conn, run_id) == "bootstrap"

def test_different_workflow_type_dont_count(conn):
    """同库但不同 workflow_type 的 completed 不算 baseline"""
    cur = conn.cursor()
    cur.execute("INSERT INTO workflow_runs (workflow_type,status,logical_date,trigger_key) VALUES ('weekly','completed','2026-04-26','weekly:2026-04-26')")
    cur.execute("INSERT INTO workflow_runs (workflow_type,status,logical_date,trigger_key) VALUES ('daily','running','2026-04-27','daily:2026-04-27')")
    run_id = cur.lastrowid
    conn.commit()
    assert determine_report_semantics(conn, run_id) == "bootstrap"

def test_db_wipe_rebuilds_to_bootstrap(conn):
    """DB wipe 后重建 → 第一个新 run 也是 bootstrap"""
    cur = conn.cursor()
    cur.execute("DELETE FROM workflow_runs")
    cur.execute("INSERT INTO workflow_runs (workflow_type,status,logical_date,trigger_key) VALUES ('daily','running','2026-05-01','daily:2026-05-01')")
    run_id = cur.lastrowid
    conn.commit()
    assert determine_report_semantics(conn, run_id) == "bootstrap"
