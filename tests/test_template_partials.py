"""Smoke tests for V4 shared partials."""
from pathlib import Path
from jinja2 import Environment, FileSystemLoader


def _env():
    tpl_dir = Path(__file__).parent.parent / "qbu_crawler" / "server" / "report_templates"
    return Environment(loader=FileSystemLoader(str(tpl_dir)))


def test_mode_strip_renders_all_modes():
    env = _env()
    for mode in ("partial", "full", "change", "quiet", "weekly", "monthly"):
        out = env.get_template("_partials/mode_strip.html.j2").render(
            mode=mode, kicker=f"TEST {mode.upper()}", meta="Run #1",
        )
        assert f"mode-strip--{mode}" in out
        assert f"TEST {mode.upper()}" in out


def test_kpi_bar_caps_at_5_items():
    env = _env()
    items = [{"label": f"K{i}", "value": i} for i in range(10)]
    out = env.get_template("_partials/kpi_bar.html.j2").render(kpi_items=items)
    assert out.count("kpi-bar-item") == 5


def test_head_renders_title_and_css():
    env = _env()
    out = env.get_template("_partials/head.html.j2").render(
        page_title="Test Report", css_text="body { margin: 0; }"
    )
    assert "<title>Test Report</title>" in out
    assert "body { margin: 0; }" in out


def test_footer_renders_threshold_and_version():
    env = _env()
    out = env.get_template("_partials/footer.html.j2").render(
        threshold=2, generated_at="2026-04-18T10:00", version="v4"
    )
    assert "评分 ≤ 2 星" in out
    assert "2026-04-18T10:00" in out
    assert "v4" in out


def test_kpi_grid_renders_confidence_and_missing_delta():
    env = _env()
    cards = [
        {"label": "健康指数", "value": 68, "delta_display": "+4", "delta_class": "delta-up", "confidence": "medium"},
        {"label": "差评率", "value": "5.9%", "delta_missing": True, "confidence": "high"},
    ]
    out = env.get_template("_partials/kpi_grid.html.j2").render(cards=cards)
    assert "conf-badge--medium" in out
    assert "conf-badge--high" in out
    assert "基线建立中" in out


def test_tab_nav_marks_active_and_disabled():
    env = _env()
    tabs = [
        {"id": "overview", "label": "总览"},
        {"id": "changes", "label": "变化", "badge": 3},
        {"id": "other", "label": "其他", "disabled": True},
    ]
    out = env.get_template("_partials/tab_nav.html.j2").render(tabs=tabs, active="overview")
    assert 'data-tab="overview"' in out and "tab-active" in out
    assert "tab-disabled" in out
    assert "tab-badge" in out


def test_hero_renders_confidence_badge_and_bullets():
    env = _env()
    out = env.get_template("_partials/hero.html.j2").render(
        kicker="DAILY INTELLIGENCE",
        title="QBU网评监控智能分析报告",
        headline="健康指数 88",
        meta="Run #1",
        health_index=88,
        confidence="high",
        bullets=["新评论 12 条", "差评率 3%"],
        actions=None,
    )
    assert "conf-badge--high" in out
    assert "可信" in out
    assert "新评论 12 条" in out
    assert 'data-health="88"' in out


def test_review_quote_renders_polarity_class():
    env = _env()
    r = {"headline": "Great grinder", "body": "Love it", "author": "Bob",
         "rating": 5, "product_name": "X", "date_published_parsed": "2026-04-18"}
    out = env.get_template("_partials/review_quote.html.j2").render(r=r)
    assert "quote-positive" in out
    assert "★★★★★" in out
    assert "Bob" in out

    r["rating"] = 1
    out = env.get_template("_partials/review_quote.html.j2").render(r=r)
    assert "quote-negative" in out


def test_empty_state_defaults():
    env = _env()
    out = env.get_template("_partials/empty_state.html.j2").render(
        title="暂无数据", body="本周期无新评论记录。"
    )
    assert "§" in out  # default icon
    assert "暂无数据" in out
    assert "本周期无新评论记录。" in out


def test_issue_card_renders_lifecycle_and_quotes():
    env = _env()
    card = {
        "label_display": "质量稳定性",
        "state": "active",
        "review_count": 8,
        "first_seen": "2026-04-01",
        "last_seen": "2026-04-17",
        "history": [],
        "example_reviews": [
            {"headline": "Broken", "body": "Stopped working",
             "author": "Alice", "rating": 1, "product_name": "G1"}
        ],
        "competitor_reference": None,
    }
    out = env.get_template("_partials/issue_card.html.j2").render(card=card)
    assert "ls-active" in out
    assert "活跃" in out
    assert "质量稳定性" in out
    assert "Alice" in out  # review_quote rendered inside


def test_email_base_renders_mode_color():
    """Email base must map mode → banner color."""
    env = _env()
    # email_base uses {% block content %} so we test via a minimal extending child
    from jinja2 import Template
    out = env.get_template("_email_base.html.j2").render(
        page_title="TestEmail",
        mode="monthly",
        kicker="MONTHLY EXECUTIVE BRIEF · 2026年04月",
        brand="QBU 网评监控",
        kpi_items=[{"label": "健康", "value": 68}, {"label": "差评", "value": "5.9%"}],
        report_url="https://example.com/report",
        generated_at="2026-05-01T10:00:00",
        threshold=2,
    )
    # monthly maps to #1e1b4b
    assert "#1e1b4b" in out
    assert "MONTHLY EXECUTIVE BRIEF" in out
    assert "68" in out
    assert "https://example.com/report" in out


def test_email_base_no_content_when_block_empty():
    env = _env()
    out = env.get_template("_email_base.html.j2").render(
        page_title="X", mode="full", kicker="K", brand="B",
        kpi_items=[], report_url="", generated_at="t", threshold=2,
    )
    # Must still produce a valid-looking shell even with empty content block
    assert "<html" in out and "</html>" in out
    assert "K" in out
