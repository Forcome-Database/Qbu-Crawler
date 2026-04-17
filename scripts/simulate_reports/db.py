"""Simple sqlite3 adapter for simulation.db.
Used by prepare/data_builder which run BEFORE business modules import.
"""
import sqlite3
from pathlib import Path
from contextlib import contextmanager


@contextmanager
def open_db(path: Path):
    conn = sqlite3.connect(str(path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def row_counts(conn: sqlite3.Connection) -> dict:
    tables = [
        "products", "product_snapshots", "reviews",
        "review_analysis", "review_issue_labels",
        "safety_incidents", "tasks", "workflow_runs",
        "notification_outbox",
    ]
    out = {}
    for t in tables:
        try:
            out[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except sqlite3.OperationalError:
            out[t] = None  # table missing
    return out
