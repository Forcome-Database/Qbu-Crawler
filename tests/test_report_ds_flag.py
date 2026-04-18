"""P12 — prove REPORT_DS_VERSION=v3 path still renders (no regression on rollback)."""
from importlib import reload


def test_v3_is_default_when_env_unset(monkeypatch):
    monkeypatch.delenv("REPORT_DS_VERSION", raising=False)
    from qbu_crawler import config
    reload(config)
    assert config.REPORT_DS_VERSION == "v3"


def test_v4_opt_in_via_env(monkeypatch):
    monkeypatch.setenv("REPORT_DS_VERSION", "v4")
    from qbu_crawler import config
    reload(config)
    assert config.REPORT_DS_VERSION == "v4"


def test_v3_fallback_renders_daily_briefing(tmp_path, monkeypatch):
    """Flag=v3 must still invoke the legacy render_daily_briefing path."""
    monkeypatch.setenv("REPORT_DS_VERSION", "v3")
    from qbu_crawler import config
    reload(config)
    from qbu_crawler.server import report_html

    out = tmp_path / "daily.html"
    report_html.render_daily_briefing(
        snapshot={"logical_date": "2026-04-18", "run_id": 1, "reviews": []},
        cumulative_kpis={"health_index": 88, "own_negative_review_rate_display": "2.0%",
                         "high_risk_count": 0, "own_review_rows": 100},
        window_reviews=[], attention_signals=[], changes={},
        output_path=str(out),
    )
    assert out.exists()
    html = out.read_text(encoding="utf-8")
    # Legacy briefing uses the P008 Phase 2 three-block layout — confirm via
    # Chinese label that only the v3 daily_briefing template emits.
    assert "累积快照" in html
