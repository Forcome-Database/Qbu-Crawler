from qbu_crawler import config
from qbu_crawler.server import report_snapshot


def _snapshot():
    return {
        "run_id": 1,
        "logical_date": "2026-04-29",
        "data_since": "2026-04-29T00:00:00+08:00",
        "data_until": "2026-04-30T00:00:00+08:00",
        "snapshot_hash": "hash",
        "products": [{"url": "https://example.com/own", "site": "basspro", "name": "Own", "sku": "SKU-OWN", "ownership": "own"}],
        "reviews": [{"id": 1, "ownership": "own", "rating": 5, "date_published_parsed": "2026-04-29"}],
        "products_count": 1,
        "reviews_count": 1,
        "translated_count": 0,
        "untranslated_count": 0,
        "cumulative": {
            "products": [{"url": "https://example.com/own", "site": "basspro", "name": "Own", "sku": "SKU-OWN", "ownership": "own"}],
            "reviews": [{"id": 1, "ownership": "own", "rating": 5, "date_published_parsed": "2026-04-29"}],
            "products_count": 1,
            "reviews_count": 1,
            "translated_count": 0,
            "untranslated_count": 0,
        },
    }


def _trend_history():
    return {
        "products": [{"url": "https://example.com/own", "site": "basspro", "name": "Own", "sku": "SKU-OWN", "ownership": "own"}],
        "reviews": [{"id": 1, "ownership": "own", "rating": 5, "date_published_parsed": "2026-04-29"}],
        "product_series": [],
        "until": "2026-04-30T00:00:00+08:00",
    }


def test_full_report_passes_historical_trend_history(tmp_path, monkeypatch):
    from qbu_crawler.server import report, report_analytics, report_html, report_llm

    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    monkeypatch.setattr(config, "REPORT_CLUSTER_ANALYSIS", False)
    monkeypatch.setattr(report_snapshot, "load_previous_report_context", lambda *_a, **_k: (None, None))
    monkeypatch.setattr(report_snapshot, "_record_artifact_safe", lambda *a, **k: None)
    monkeypatch.setattr(report_llm, "generate_report_insights_with_validation", lambda *a, **k: {})
    monkeypatch.setattr(report_analytics, "build_fallback_priorities", lambda *a, **k: [])
    monkeypatch.setattr(report, "generate_excel", lambda *a, **k: str(tmp_path / "report.xlsx"))
    monkeypatch.setattr(report, "query_trend_history", lambda *a, **k: (_trend_history()["products"], _trend_history()["reviews"]))
    monkeypatch.setattr(report_analytics, "build_historical_product_trend_series", lambda *a, **k: [])

    captured = {}

    def fake_render_v3_html(snapshot, analytics, output_path=None):
        captured["analytics"] = analytics
        path = tmp_path / "report.html"
        path.write_text("<html></html>", encoding="utf-8")
        return str(path)

    monkeypatch.setattr(report_html, "render_v3_html", fake_render_v3_html)

    report_snapshot.generate_full_report_from_snapshot(
        _snapshot(),
        send_email=False,
        output_path=str(tmp_path / "report.xlsx"),
    )

    assert "workspace" in captured["analytics"]["trend_digest"]


def test_change_report_builds_historical_trend_history(tmp_path, monkeypatch):
    from qbu_crawler.server import report, report_analytics

    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    monkeypatch.setattr(report, "query_trend_history", lambda *a, **k: (_trend_history()["products"], _trend_history()["reviews"]))
    monkeypatch.setattr(report_analytics, "build_historical_product_trend_series", lambda *a, **k: [])
    monkeypatch.setattr(report_snapshot, "_render_quiet_or_change_html", lambda *a, **k: str(tmp_path / "change.html"))

    result = report_snapshot._generate_change_report(
        _snapshot(),
        send_email=False,
        prev_analytics=None,
        context={"changes": {"rating_changes": [{"sku": "SKU-OWN"}]}},
    )

    analytics_path = tmp_path / "workflow-run-1-analytics-2026-04-29.json"
    assert result["analytics_path"]
    assert '"workspace"' in analytics_path.read_text(encoding="utf-8")


def test_quiet_report_builds_historical_trend_history(tmp_path, monkeypatch):
    from qbu_crawler.server import report, report_analytics

    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    monkeypatch.setattr(report, "query_trend_history", lambda *a, **k: (_trend_history()["products"], _trend_history()["reviews"]))
    monkeypatch.setattr(report_analytics, "build_historical_product_trend_series", lambda *a, **k: [])
    monkeypatch.setattr(report_snapshot, "_render_quiet_or_change_html", lambda *a, **k: str(tmp_path / "quiet.html"))
    monkeypatch.setattr(report_snapshot, "should_send_quiet_email", lambda *_a, **_k: (True, None, 0))

    result = report_snapshot._generate_quiet_report(
        _snapshot(),
        send_email=False,
        prev_analytics=None,
    )

    analytics_path = tmp_path / "workflow-run-1-analytics-2026-04-29.json"
    assert result["analytics_path"]
    assert '"workspace"' in analytics_path.read_text(encoding="utf-8")
