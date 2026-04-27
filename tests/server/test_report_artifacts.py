"""F011 §5.1 — tests for report_artifacts CRUD helpers."""
from __future__ import annotations

import sqlite3

import pytest

from qbu_crawler.server.migrations import migration_0010_report_redesign_schema as mig
from qbu_crawler.server.report_artifacts import list_artifacts, record_artifact


def _setup_minimal_schema(db: sqlite3.Connection) -> None:
    """Create the minimum tables required by migration 0010, then apply it.

    The migration touches reviews / products / workflow_runs / product_snapshots
    via ALTER TABLE; we provide just enough for ALTERs to succeed and for
    report_artifacts (the table under test) to be created.
    """
    db.executescript(
        """
        CREATE TABLE workflow_runs (
            id INTEGER PRIMARY KEY,
            logical_date TEXT
        );
        CREATE TABLE reviews (
            id INTEGER PRIMARY KEY,
            date_published TEXT,
            date_published_parsed TEXT
        );
        CREATE TABLE products (id INTEGER PRIMARY KEY);
        CREATE TABLE product_snapshots (id INTEGER PRIMARY KEY);
        """
    )
    db.commit()
    mig.up(db)


def test_record_artifact_basic(tmp_path):
    """record_artifact writes to report_artifacts table with hash + bytes + version."""
    db = sqlite3.connect(":memory:")
    _setup_minimal_schema(db)
    cur = db.cursor()
    cur.execute("INSERT INTO workflow_runs (id, logical_date) VALUES (1, '2026-04-27')")
    db.commit()

    artifact_file = tmp_path / "test.html"
    artifact_file.write_text("<html>x</html>", encoding="utf-8")

    rowid = record_artifact(
        db,
        run_id=1,
        artifact_type="html_attachment",
        path=str(artifact_file),
        template_version="v3.0",
    )
    assert rowid is not None

    arts = list_artifacts(db, run_id=1)
    assert len(arts) == 1
    art = arts[0]
    assert art["artifact_type"] == "html_attachment"
    assert art["template_version"] == "v3.0"
    assert art["generator_version"]  # qbu_crawler.__version__
    assert art["hash"]
    assert len(art["hash"]) == 16
    assert art["bytes"] == len("<html>x</html>".encode("utf-8"))
    assert art["path"] == str(artifact_file)


def test_record_artifact_missing_file_returns_none(tmp_path):
    db = sqlite3.connect(":memory:")
    _setup_minimal_schema(db)
    cur = db.cursor()
    cur.execute("INSERT INTO workflow_runs (id, logical_date) VALUES (1, '2026-04-27')")
    db.commit()

    rowid = record_artifact(
        db,
        run_id=1,
        artifact_type="snapshot",
        path=str(tmp_path / "nonexistent.json"),
    )
    assert rowid is None
    assert list_artifacts(db, run_id=1) == []


def test_list_artifacts_orders_by_id(tmp_path):
    """Multiple artifacts for same run returned in insert (id-asc) order."""
    db = sqlite3.connect(":memory:")
    _setup_minimal_schema(db)
    cur = db.cursor()
    cur.execute("INSERT INTO workflow_runs (id, logical_date) VALUES (1, '2026-04-27')")
    db.commit()

    paths = []
    for i, kind in enumerate(["snapshot", "xlsx", "html_attachment"]):
        p = tmp_path / f"a{i}.bin"
        p.write_text(f"content-{i}", encoding="utf-8")
        paths.append((kind, p))
        record_artifact(db, run_id=1, artifact_type=kind, path=str(p))

    arts = list_artifacts(db, run_id=1)
    assert [a["artifact_type"] for a in arts] == ["snapshot", "xlsx", "html_attachment"]
    assert [a["id"] for a in arts] == sorted(a["id"] for a in arts)


def test_artifact_type_check_constraint_rejects_unknown(tmp_path):
    """report_artifacts CHECK constraint enforces enum."""
    db = sqlite3.connect(":memory:")
    _setup_minimal_schema(db)
    cur = db.cursor()
    cur.execute("INSERT INTO workflow_runs (id, logical_date) VALUES (1, '2026-04-27')")
    db.commit()

    bad = tmp_path / "bad.bin"
    bad.write_text("x", encoding="utf-8")

    with pytest.raises(sqlite3.IntegrityError):
        record_artifact(db, run_id=1, artifact_type="bogus", path=str(bad))
