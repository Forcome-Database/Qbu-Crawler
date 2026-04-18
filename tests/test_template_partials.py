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
