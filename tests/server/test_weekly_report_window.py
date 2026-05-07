def test_build_weekly_snapshot_uses_7_day_window_and_review_products(monkeypatch):
    from qbu_crawler.server import report_snapshot

    calls = {}

    def fake_query_report_data(since, until=None):
        calls["since"] = since
        calls["until"] = until
        return (
            [{"url": "https://example.com/refreshed", "sku": "REF", "site": "basspro"}],
            [{"id": 1, "product_url": "https://example.com/commented", "product_sku": "CMT", "site": "basspro"}],
        )

    monkeypatch.setattr("qbu_crawler.server.report.query_report_data", fake_query_report_data)

    base_snapshot = {
        "run_id": 20,
        "logical_date": "2026-05-07",
        "data_until": "2026-05-08T00:00:00+08:00",
        "cumulative": {
            "products": [
                {"url": "https://example.com/refreshed", "sku": "REF", "site": "basspro"},
                {"url": "https://example.com/commented", "sku": "CMT", "site": "basspro"},
            ],
            "reviews": [{"id": 9}],
            "products_count": 2,
            "reviews_count": 1,
        },
    }
    snapshot = report_snapshot.build_windowed_report_snapshot(
        base_snapshot,
        window_type="weekly",
        window_days=7,
    )

    assert snapshot["report_window"]["type"] == "weekly"
    assert snapshot["reviews_count"] == 1
    assert snapshot["cumulative"]["reviews_count"] == 1
    assert {p["sku"] for p in snapshot["products"]} == {"REF", "CMT"}
    assert calls["until"] == "2026-05-08T00:00:00+08:00"
    assert str(calls["since"]).startswith("2026-05-01")


def test_html_uses_weekly_change_title():
    from qbu_crawler.server.report_html import _render_v3_html_string

    html = _render_v3_html_string(
        {"logical_date": "2026-05-07", "report_window": {"type": "weekly", "label": "本周"}},
        {"report_semantics": "incremental", "change_digest": {}, "kpis": {}},
    )

    assert "本周变化" in html
    assert "今日变化" not in html


def test_email_full_uses_weekly_language():
    from qbu_crawler.server.report import render_email_full

    html = render_email_full(
        {
            "logical_date": "2026-05-07",
            "data_since": "2026-05-01T00:00:00+08:00",
            "data_until": "2026-05-08T00:00:00+08:00",
            "report_window": {"type": "weekly", "label": "本周", "days": 7},
        },
        {"kpis": {"ingested_review_rows": 8}, "report_user_contract": {"kpis": {}}},
    )

    assert "本周" in html
    assert "今日新增" not in html


def test_weekly_quiet_report_bypasses_quiet_email_throttle(tmp_path, monkeypatch):
    from qbu_crawler import config
    from qbu_crawler.server import report_snapshot

    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    monkeypatch.setattr(report_snapshot, "should_send_quiet_email", lambda run_id: (False, "weekly", 8))
    monkeypatch.setattr(report_snapshot, "_render_quiet_or_change_html", lambda *a, **k: str(tmp_path / "quiet.html"))
    monkeypatch.setattr(report_snapshot, "_record_artifact_safe", lambda *a, **k: None)
    monkeypatch.setattr(report_snapshot, "_send_mode_email", lambda *a, **k: {"success": True, "recipients": ["a@example.com"]})

    result = report_snapshot._generate_quiet_report(
        {
            "run_id": 22,
            "logical_date": "2026-05-04",
            "snapshot_hash": "hash",
            "products": [],
            "reviews": [],
            "products_count": 0,
            "reviews_count": 0,
            "report_window": {"type": "weekly", "label": "本周", "days": 7},
        },
        send_email=True,
        prev_analytics={},
    )

    assert result["email"]["success"] is True
    assert result["email_skipped"] is False


def test_weekly_quiet_email_uses_weekly_subject_and_body(monkeypatch):
    from qbu_crawler.server import report_snapshot

    captured = {}
    monkeypatch.setattr(report_snapshot, "get_email_recipients", lambda: ["a@example.com"])
    monkeypatch.setattr(report_snapshot.report, "send_email", lambda **kwargs: captured.update(kwargs) or {"success": True})
    monkeypatch.setattr(report_snapshot.models, "get_translate_stats", lambda: {})

    result = report_snapshot._send_mode_email(
        "quiet",
        {
            "logical_date": "2026-05-04",
            "snapshot_at": "2026-05-04T01:00:00+08:00",
            "report_window": {"type": "weekly", "label": "本周", "days": 7},
        },
        {"kpis": {}},
        consecutive_quiet=7,
    )

    assert result["success"] is True
    assert "产品评论周报" in captured["subject"]
    assert "本周无新增评论" in captured["body_html"]


def test_weekly_change_email_uses_weekly_subject(monkeypatch):
    from qbu_crawler.server import report_snapshot

    captured = {}
    monkeypatch.setattr(report_snapshot, "get_email_recipients", lambda: ["a@example.com"])
    monkeypatch.setattr(report_snapshot.report, "send_email", lambda **kwargs: captured.update(kwargs) or {"success": True})

    result = report_snapshot._send_mode_email(
        "change",
        {
            "logical_date": "2026-05-04",
            "snapshot_at": "2026-05-04T01:00:00+08:00",
            "report_window": {"type": "weekly", "label": "本周", "days": 7},
        },
        {"kpis": {}},
        changes={"has_changes": True, "price_changes": [{"sku": "A"}]},
    )

    assert result["success"] is True
    assert "产品评论周报" in captured["subject"]
