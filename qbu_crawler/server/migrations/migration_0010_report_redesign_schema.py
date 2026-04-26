"""F011 Report system redesign — schema migration.

Adds:
- reviews: date_published_estimated, date_parse_method, date_parse_anchor,
           date_parse_confidence, source_review_id
- products: last_scrape_completeness, last_scrape_warnings
- workflow_runs: scrape_completeness_ratio, zero_scrape_count, report_copy_json
- product_snapshots: workflow_run_id
- report_artifacts (new table)
- indexes: idx_artifacts_run, idx_reviews_published_parsed, idx_labels_polarity_severity
"""
import sqlite3

UP_SQL = [
    "ALTER TABLE reviews ADD COLUMN date_published_estimated INTEGER DEFAULT 0",
    "ALTER TABLE reviews ADD COLUMN date_parse_method TEXT",
    "ALTER TABLE reviews ADD COLUMN date_parse_anchor TEXT",
    "ALTER TABLE reviews ADD COLUMN date_parse_confidence REAL",
    "ALTER TABLE reviews ADD COLUMN source_review_id TEXT",

    "ALTER TABLE products ADD COLUMN last_scrape_completeness REAL",
    "ALTER TABLE products ADD COLUMN last_scrape_warnings TEXT",

    "ALTER TABLE workflow_runs ADD COLUMN scrape_completeness_ratio REAL",
    "ALTER TABLE workflow_runs ADD COLUMN zero_scrape_count INTEGER",
    "ALTER TABLE workflow_runs ADD COLUMN report_copy_json TEXT",

    "ALTER TABLE product_snapshots ADD COLUMN workflow_run_id INTEGER REFERENCES workflow_runs(id)",

    """CREATE TABLE IF NOT EXISTS report_artifacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL REFERENCES workflow_runs(id),
        artifact_type TEXT NOT NULL CHECK(artifact_type IN ('html_attachment','xlsx','pdf','snapshot','analytics','email_body')),
        path TEXT NOT NULL,
        hash TEXT,
        template_version TEXT,
        generator_version TEXT,
        bytes INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""",

    "CREATE INDEX IF NOT EXISTS idx_artifacts_run ON report_artifacts(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_reviews_published_parsed ON reviews(date_published_parsed)",
    "CREATE INDEX IF NOT EXISTS idx_labels_polarity_severity ON review_issue_labels(label_polarity, severity)",
]

DOWN_SQL = [
    "DROP INDEX IF EXISTS idx_artifacts_run",
    "DROP INDEX IF EXISTS idx_reviews_published_parsed",
    "DROP INDEX IF EXISTS idx_labels_polarity_severity",
    "DROP TABLE IF EXISTS report_artifacts",
    "ALTER TABLE reviews DROP COLUMN date_published_estimated",
    "ALTER TABLE reviews DROP COLUMN date_parse_method",
    "ALTER TABLE reviews DROP COLUMN date_parse_anchor",
    "ALTER TABLE reviews DROP COLUMN date_parse_confidence",
    "ALTER TABLE reviews DROP COLUMN source_review_id",
    "ALTER TABLE products DROP COLUMN last_scrape_completeness",
    "ALTER TABLE products DROP COLUMN last_scrape_warnings",
    "ALTER TABLE workflow_runs DROP COLUMN scrape_completeness_ratio",
    "ALTER TABLE workflow_runs DROP COLUMN zero_scrape_count",
    "ALTER TABLE workflow_runs DROP COLUMN report_copy_json",
    "ALTER TABLE product_snapshots DROP COLUMN workflow_run_id",
]


def up(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    for sql in UP_SQL:
        try:
            cur.execute(sql)
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e).lower():
                continue
            raise
    conn.commit()


def down(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    for sql in DOWN_SQL:
        try:
            cur.execute(sql)
        except sqlite3.OperationalError:
            continue
    conn.commit()
