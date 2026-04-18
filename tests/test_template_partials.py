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
