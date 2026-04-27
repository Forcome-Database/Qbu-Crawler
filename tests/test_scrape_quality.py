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


def test_data_quality_alert_integration_sends_email(tmp_path, monkeypatch):
    """End-to-end: a snapshot with >threshold missing rating triggers
    _send_data_quality_alert, which renders the template and calls report.send_email."""
    import sqlite3
    from qbu_crawler import config, models
    from qbu_crawler.server import workflows
    # Isolated DB
    db = tmp_path / "t.db"
    monkeypatch.setattr(config, "DB_PATH", str(db))
    monkeypatch.setattr(models, "DB_PATH", str(db))
    monkeypatch.setattr(config, "SCRAPE_QUALITY_ALERT_RATIO", 0.10)
    monkeypatch.setattr(config, "SCRAPE_QUALITY_ALERT_RECIPIENTS", ["ops@example.com"])
    models.init_db()

    captured = {}
    def fake_send_email(*, recipients, subject, body_text, body_html):
        captured["recipients"] = recipients
        captured["subject"] = subject
        captured["body_html"] = body_html
        return {"success": True, "recipients": recipients}

    # Patch the exact `report.send_email` the workflow helper imports lazily
    from qbu_crawler.server import report as _report
    monkeypatch.setattr(_report, "send_email", fake_send_email)

    quality = {"total": 10, "missing_rating": 2, "missing_stock": 0,
               "missing_review_count": 0,
               "missing_rating_ratio": 0.20, "missing_stock_ratio": 0.0,
               "missing_review_count_ratio": 0.0}

    workflows._send_data_quality_alert(
        run_id=42, logical_date="2026-04-19", quality=quality)

    assert captured["recipients"] == ["ops@example.com"]
    assert "数据质量告警" in captured["subject"]
    assert "2026-04-19" in captured["subject"]
    # Template rendered with the threshold-driven highlight
    assert "20.0%" in captured["body_html"]  # rating ratio as %
    assert "QBU 采集数据质量告警" in captured["body_html"]


# ──────────────────────────────────────────────────────────────────────────
# F011 Critical B-1 — email_data_quality template defensive against missing
#                     v3 quality keys
# ──────────────────────────────────────────────────────────────────────────


def _render_data_quality_template(quality: dict, **kwargs) -> str:
    """Render email_data_quality.html.j2 with the supplied quality dict."""
    from pathlib import Path
    from jinja2 import Environment, FileSystemLoader, StrictUndefined

    tpl_dir = (
        Path(__file__).resolve().parent.parent
        / "qbu_crawler" / "server" / "report_templates"
    )
    env = Environment(
        loader=FileSystemLoader(str(tpl_dir)),
        undefined=StrictUndefined,  # match Jinja default; surfaces UndefinedError
        autoescape=True,
    )
    template = env.get_template("email_data_quality.html.j2")
    ctx = {
        "logical_date": "2026-04-27",
        "run_id": 99,
        "threshold": 0.10,
        "severity": kwargs.get("severity"),
        "quality": quality,
    }
    return template.render(**ctx)


def test_email_data_quality_renders_with_legacy_dict_no_completeness():
    """F011 Critical B-1 — legacy quality dict (pre-F011 fields only) must
    render without UndefinedError. Previously crashed on
    ``quality.scrape_completeness_ratio is not none`` because Jinja resolves
    missing keys to ``Undefined`` (not ``None``)."""
    legacy_quality = {
        "total": 10,
        "missing_rating": 1,
        "missing_stock": 0,
        "missing_review_count": 0,
        "missing_rating_ratio": 0.10,
        "missing_stock_ratio": 0.0,
        "missing_review_count_ratio": 0.0,
    }
    html = _render_data_quality_template(legacy_quality)
    assert "QBU 采集数据质量告警" in html
    # Optional v3 panels must NOT render when the keys are absent
    assert "采集完整率" not in html
    assert "P0 · 零采集 SKU" not in html
    assert "P1 · 通知 deadletter" not in html
    assert "估算日期占比" not in html


def test_email_data_quality_renders_with_full_v3_dict():
    """F011 Critical B-1 — full v3 dict renders all panels including
    severity badge and zero_scrape_skus list."""
    v3_quality = {
        "total": 20,
        "missing_rating": 2,
        "missing_stock": 1,
        "missing_review_count": 0,
        "missing_rating_ratio": 0.10,
        "missing_stock_ratio": 0.05,
        "missing_review_count_ratio": 0.0,
        "scrape_completeness_ratio": 0.55,  # < 0.6 → red
        "zero_scrape_skus": ["SKU-A", "SKU-B", "SKU-C"],
        "outbox_deadletter_count": 4,
        "estimated_date_ratio": 0.42,  # > 0.3 → orange
    }
    html = _render_data_quality_template(v3_quality, severity="P0")
    # severity badge
    assert "P0" in html
    # all v3 panels rendered
    assert "采集完整率" in html
    assert "55.0%" in html
    assert "P0 · 零采集 SKU" in html
    assert "SKU-A" in html
    assert "P1 · 通知 deadletter" in html
    assert "4 条" in html
    assert "估算日期占比" in html
    assert "42.0%" in html
