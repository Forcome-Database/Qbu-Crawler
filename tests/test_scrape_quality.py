"""字段缺失统计与告警阈值判定。"""
from qbu_crawler.server.scrape_quality import (
    summarize_scrape_quality,
    should_raise_alert,
)


def test_summarize_counts_null_rating():
    rows = [
        {"sku": "A", "rating": 4.5, "stock_status": "in_stock", "review_count": 10},
        {"sku": "B", "rating": None, "stock_status": "in_stock", "review_count": 10},
        {"sku": "C", "rating": None, "stock_status": "in_stock", "review_count": 10},
    ]
    q = summarize_scrape_quality(rows)
    assert q["total"] == 3
    assert q["missing_rating"] == 2
    assert q["missing_stock"] == 0
    assert q["missing_review_count"] == 0
    assert abs(q["missing_rating_ratio"] - 2/3) < 1e-6


def test_summarize_counts_unknown_stock_and_empty_review_count():
    rows = [
        {"sku": "A", "rating": 4.5, "stock_status": "unknown", "review_count": 10},
        {"sku": "B", "rating": 4.5, "stock_status": "",        "review_count": 10},
        {"sku": "C", "rating": 4.5, "stock_status": None,      "review_count": None},
    ]
    q = summarize_scrape_quality(rows)
    assert q["missing_stock"] == 3
    assert q["missing_review_count"] == 1


def test_alert_threshold_triggered():
    quality = {"total": 100, "missing_rating": 15, "missing_stock": 0,
               "missing_review_count": 0,
               "missing_rating_ratio": 0.15, "missing_stock_ratio": 0.0,
               "missing_review_count_ratio": 0.0}
    assert should_raise_alert(quality, threshold=0.10) is True
    assert should_raise_alert(quality, threshold=0.20) is False


def test_alert_not_triggered_on_empty():
    quality = {"total": 0, "missing_rating": 0, "missing_stock": 0,
               "missing_review_count": 0,
               "missing_rating_ratio": 0.0, "missing_stock_ratio": 0.0,
               "missing_review_count_ratio": 0.0}
    assert should_raise_alert(quality, threshold=0.10) is False


def test_update_and_readback_scrape_quality(tmp_path, monkeypatch):
    import sqlite3
    from qbu_crawler import config, models
    db = tmp_path / "t.db"
    monkeypatch.setattr(config, "DB_PATH", str(db))
    monkeypatch.setattr(models, "DB_PATH", str(db))
    models.init_db()
    # 手插一条 run
    with sqlite3.connect(str(db)) as conn:
        conn.execute(
            "INSERT INTO workflow_runs (workflow_type, status, logical_date, "
            "trigger_key) VALUES ('daily','running','2026-04-19','t:2026-04-19')"
        )
        rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    q = {"total": 10, "missing_rating": 2, "missing_stock": 0,
         "missing_review_count": 0,
         "missing_rating_ratio": 0.2, "missing_stock_ratio": 0.0,
         "missing_review_count_ratio": 0.0}
    models.update_scrape_quality(rid, q)
    loaded = models.get_scrape_quality(rid)
    assert loaded == q
