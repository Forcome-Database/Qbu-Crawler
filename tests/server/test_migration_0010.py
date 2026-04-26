import sqlite3
import pytest
from qbu_crawler.server.migrations import migration_0010_report_redesign_schema as mig

@pytest.fixture
def fresh_db(tmp_path):
    db = tmp_path / "test.db"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE reviews (
          id INTEGER PRIMARY KEY,
          product_id INTEGER,
          date_published TEXT,
          date_published_parsed TEXT
        );
        CREATE TABLE products (
          id INTEGER PRIMARY KEY,
          sku TEXT
        );
        CREATE TABLE workflow_runs (
          id INTEGER PRIMARY KEY,
          status TEXT
        );
        CREATE TABLE product_snapshots (
          id INTEGER PRIMARY KEY,
          product_id INTEGER
        );
        CREATE TABLE review_issue_labels (
          id INTEGER PRIMARY KEY,
          review_id INTEGER,
          label_polarity TEXT,
          severity TEXT
        );
    """)
    conn.commit()
    yield conn
    conn.close()

def test_up_adds_required_columns(fresh_db):
    mig.up(fresh_db)
    cur = fresh_db.cursor()

    columns = [r[1] for r in cur.execute("PRAGMA table_info(reviews)").fetchall()]
    assert "date_published_estimated" in columns
    assert "date_parse_method" in columns
    assert "date_parse_anchor" in columns
    assert "date_parse_confidence" in columns
    assert "source_review_id" in columns

    columns = [r[1] for r in cur.execute("PRAGMA table_info(products)").fetchall()]
    assert "last_scrape_completeness" in columns
    assert "last_scrape_warnings" in columns

    columns = [r[1] for r in cur.execute("PRAGMA table_info(workflow_runs)").fetchall()]
    assert "scrape_completeness_ratio" in columns
    assert "zero_scrape_count" in columns
    assert "report_copy_json" in columns

    columns = [r[1] for r in cur.execute("PRAGMA table_info(product_snapshots)").fetchall()]
    assert "workflow_run_id" in columns

    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    assert "report_artifacts" in tables

def test_down_reverts_changes(fresh_db):
    mig.up(fresh_db)
    mig.down(fresh_db)
    cur = fresh_db.cursor()
    columns = [r[1] for r in cur.execute("PRAGMA table_info(reviews)").fetchall()]
    assert "date_published_estimated" not in columns
    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    assert "report_artifacts" not in tables

def test_up_is_idempotent(fresh_db):
    """Re-applying up() must not raise even when columns already exist."""
    mig.up(fresh_db)
    mig.up(fresh_db)  # should be a no-op
    cur = fresh_db.cursor()
    columns = [r[1] for r in cur.execute("PRAGMA table_info(reviews)").fetchall()]
    assert "date_published_estimated" in columns
