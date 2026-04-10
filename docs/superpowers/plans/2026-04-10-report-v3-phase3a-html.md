# Report V3 Phase 3a — HTML Template + Chart.js Migration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the V3 interactive HTML report template with Chart.js, tab navigation, collapsible cards, lightbox, and table sort/filter. Runs in parallel with existing PDF output.

**Architecture:** New Jinja2 template + CSS + vanilla JS. Chart generation refactored from Plotly dicts to Chart.js config objects. Existing PDF pipeline untouched (parallel output).

**Tech Stack:** Jinja2, Chart.js 4.x (CDN), vanilla JavaScript, CSS custom properties

**Spec Reference:** `docs/superpowers/specs/2026-04-10-report-v3-redesign.md` — Sections 4.2, 5.1–5.6, 15.7–15.8

**Prerequisite:** Phase 1 and Phase 2 complete (V3 metrics and LLM fields available in analytics).

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `qbu_crawler/server/report_templates/daily_report_v3.html.j2` | Create | Main interactive HTML template (6 tabs) |
| `qbu_crawler/server/report_templates/daily_report_v3.css` | Create | Responsive styles with print media |
| `qbu_crawler/server/report_templates/daily_report_v3.js` | Create | ~300 lines: tabs, collapse, lightbox, table sort/filter, sticky KPI |
| `qbu_crawler/server/report_charts.py` | Modify | Replace Plotly builders with Chart.js config generators |
| `qbu_crawler/server/report_pdf.py` | Modify | Add V3 HTML render path alongside existing PDF |
| `tests/test_v3_html.py` | Create | Template rendering and chart config tests |

---

### Task 1: Create Chart.js config generators

**Files:**
- Modify: `qbu_crawler/server/report_charts.py`
- Test: `tests/test_v3_html.py` (create)

- [ ] **Step 1: Write Chart.js config tests**

```python
# tests/test_v3_html.py
"""Tests for Report V3 HTML template and Chart.js generation (Phase 3a)."""

from qbu_crawler.server.report_charts import build_chartjs_configs


class TestChartJsConfigs:
    def test_returns_dict_of_configs(self):
        analytics = {
            "kpis": {"health_index": 57.4},
            "_radar_data": {
                "categories": ["A", "B", "C"],
                "own_values": [0.5, 0.3, 0.8],
                "competitor_values": [0.7, 0.6, 0.9],
            },
            "_sentiment_distribution_own": {
                "categories": ["Prod1"],
                "positive": [10], "neutral": [3], "negative": [5],
            },
        }
        configs = build_chartjs_configs(analytics)
        assert isinstance(configs, dict)
        # Should have at least health gauge and radar
        assert "health_gauge" in configs or "radar" in configs

    def test_handles_empty_analytics(self):
        configs = build_chartjs_configs({})
        assert isinstance(configs, dict)

    def test_labels_not_truncated_in_radar(self):
        analytics = {
            "_radar_data": {
                "categories": ["耐久性与质量", "设计与使用", "清洁便利性"],
                "own_values": [0.5, 0.3, 0.8],
                "competitor_values": [0.7, 0.6, 0.9],
            },
        }
        configs = build_chartjs_configs(analytics)
        if "radar" in configs:
            labels = configs["radar"]["data"]["labels"]
            # Labels should be present (Chart.js handles wrapping)
            assert len(labels) == 3
```

- [ ] **Step 2: Implement `build_chartjs_configs`**

Add a new function to `report_charts.py` (keep existing Plotly functions for Phase 3a parallel output):

```python
def build_chartjs_configs(analytics):
    """Build Chart.js configuration dicts for all report charts.

    Returns dict of {chart_name: chartjs_config_dict}.
    Configs are JSON-serializable and injected into the HTML template as:
        <canvas id="chart-{name}"></canvas>
        <script>new Chart(ctx, {{ config | tojson }});</script>
    """
    configs = {}

    # Health gauge (doughnut)
    health = analytics.get("kpis", {}).get("health_index")
    if health is not None:
        configs["health_gauge"] = _chartjs_health_gauge(health)

    # Radar (own vs competitor)
    radar = analytics.get("_radar_data")
    if radar and len(radar.get("categories", [])) >= 3:
        configs["radar"] = _chartjs_radar(radar)

    # Sentiment distribution (own + competitor)
    for key, name in [("_sentiment_distribution_own", "sentiment_own"),
                       ("_sentiment_distribution_competitor", "sentiment_comp")]:
        dist = analytics.get(key)
        if dist and dist.get("categories"):
            configs[name] = _chartjs_stacked_bar(dist, name)

    # Scatter (price-rating)
    products = analytics.get("_products_for_charts")
    if products and len(products) >= 2:
        configs["scatter"] = _chartjs_scatter(products)

    # Heatmap (via chartjs-chart-matrix or custom)
    heatmap = analytics.get("_heatmap_data")
    if heatmap and len(heatmap.get("y_labels", [])) >= 3:
        configs["heatmap"] = _chartjs_heatmap(heatmap)

    return configs
```

Then implement each `_chartjs_*` helper. Each returns a plain dict matching Chart.js config schema. Example for radar:

```python
def _chartjs_radar(radar_data):
    return {
        "type": "radar",
        "data": {
            "labels": radar_data["categories"],
            "datasets": [
                {
                    "label": "自有",
                    "data": radar_data["own_values"],
                    "backgroundColor": "rgba(147, 84, 63, 0.15)",
                    "borderColor": "#93543f",
                    "borderWidth": 2,
                },
                {
                    "label": "竞品",
                    "data": radar_data["competitor_values"],
                    "backgroundColor": "rgba(52, 95, 87, 0.15)",
                    "borderColor": "#345f57",
                    "borderWidth": 2,
                },
            ],
        },
        "options": {
            "scales": {"r": {"beginAtZero": True, "max": 1.0}},
            "plugins": {"legend": {"position": "bottom"}},
        },
    }
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/test_v3_html.py -v`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add qbu_crawler/server/report_charts.py tests/test_v3_html.py
git commit -m "feat(report): add Chart.js config generators for V3 HTML report

build_chartjs_configs produces JSON configs for: health gauge, radar,
stacked bar (sentiment), scatter (price-rating), heatmap.
Existing Plotly functions retained for parallel output."
```

---

### Task 2: Create CSS design system

**Files:**
- Create: `qbu_crawler/server/report_templates/daily_report_v3.css`

- [ ] **Step 1: Write CSS file**

Port the existing design tokens from `daily_report.css` (color palette, spacing, typography) into a new file with responsive enhancements. Key additions:
- Tab navigation styles
- Collapsible card styles (`.card-collapsed .card-body { display: none }`)
- Lightbox overlay styles
- Sticky KPI bar (`position: sticky; top: 0; z-index: 100`)
- `@media print` rules (expand all collapsed sections, hide interactive controls)
- Responsive breakpoints for mobile

- [ ] **Step 2: Commit**

```bash
git add qbu_crawler/server/report_templates/daily_report_v3.css
git commit -m "feat(report): V3 CSS design system — responsive, print, tabs, lightbox"
```

---

### Task 3: Create vanilla JS for interactivity

**Files:**
- Create: `qbu_crawler/server/report_templates/daily_report_v3.js`

- [ ] **Step 1: Write JS file (~300 lines)**

Implement:

1. **Tab navigation** (~30 lines): Click handler on `.tab-nav button` toggles `data-tab` sections
2. **Collapsible cards** (~30 lines): Click handler on `.card-header` toggles `.card-collapsed` class
3. **Evidence lightbox** (~50 lines): Click on `.evidence-img` shows `#lightbox` overlay with full image
4. **Table sort** (~60 lines): Click on `th[data-sortable]` sorts table rows
5. **Table filter** (~50 lines): Input event on `.filter-input` filters visible rows
6. **Sticky KPI** (~10 lines): CSS handles this, JS adds scroll shadow class
7. **Print** (~10 lines): `#btn-print` click handler calls `window.print()`
8. **Chart initialization** (~60 lines): For each `<canvas data-chart>`, parse config from `data-config` attribute and create Chart instance

- [ ] **Step 2: Commit**

```bash
git add qbu_crawler/server/report_templates/daily_report_v3.js
git commit -m "feat(report): V3 vanilla JS — tabs, collapse, lightbox, sort, filter, print"
```

---

### Task 4: Create V3 HTML template

**Files:**
- Create: `qbu_crawler/server/report_templates/daily_report_v3.html.j2`
- Test: `tests/test_v3_html.py` (append render test)

- [ ] **Step 1: Write template render test**

```python
class TestV3TemplateRender:
    def test_renders_without_error(self):
        """V3 template renders with minimal analytics data."""
        from jinja2 import Environment, FileSystemLoader
        import os
        
        template_dir = os.path.join(
            os.path.dirname(__file__), "..", "qbu_crawler", "server", "report_templates"
        )
        env = Environment(loader=FileSystemLoader(template_dir))
        template = env.get_template("daily_report_v3.html.j2")
        
        html = template.render(
            logical_date="2026-04-10",
            mode="baseline",
            snapshot={"snapshot_at": "2026-04-10T06:00:00"},
            analytics={"kpis": {"health_index": 57.4, "own_review_rows": 141}},
            charts={},
            alert_level="yellow",
            alert_text="测试",
            report_copy={},
            css_text="",
            js_text="",
        )
        assert "产品评论" in html
        assert "57.4" in html
        assert "_uncategorized" not in html
```

- [ ] **Step 1.5: Build "Top Actions" data structure** (P3a-02 fix)

The template's Action Board tab needs a `top_actions` list. Add to `normalize_deep_report_analytics` in `report_common.py`:

```python
# Build top_actions from improvement_priorities (LLM) + top_negative_clusters
top_actions = []
priorities = analytics.get("report_copy", {}).get("improvement_priorities", [])
clusters_by_code = {c["label_code"]: c for c in normalized.get("self", {}).get("top_negative_clusters", [])}
for i, p in enumerate(priorities[:3]):
    cluster = clusters_by_code.get(p.get("label_code", ""))
    top_actions.append({
        "rank": i + 1,
        "title": p.get("action", "")[:80],
        "evidence_summary": f"{cluster['review_count']}条投诉" if cluster else "",
        "affected_products": cluster.get("affected_products", []) if cluster else [],
        "recommendation": p.get("action", ""),
        "linked_cluster": p.get("label_code", ""),
    })
normalized["top_actions"] = top_actions
```

- [ ] **Step 2: Build the template**

Create `daily_report_v3.html.j2` following the structure from spec Section 4.2.4:
- `<header>` with sticky KPI bar
- `<nav>` with 6 tab buttons
- 6 `<section>` tab panels (overview, changes, issues, products, competitive, panorama)
- `<div id="lightbox">` overlay
- Chart.js CDN script with `onerror` fallback (spec 14.11)
- Inline JS from `daily_report_v3.js`
- Data freshness timestamp in hero (spec 15.8)

Each tab panel uses Jinja2 conditionals to handle missing data gracefully.

- [ ] **Step 3: Run template test**

Run: `uv run pytest tests/test_v3_html.py::TestV3TemplateRender -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add qbu_crawler/server/report_templates/daily_report_v3.html.j2 tests/test_v3_html.py
git commit -m "feat(report): V3 interactive HTML template — 6 tabs, full content structure"
```

---

### Task 5: Wire V3 HTML rendering into report pipeline (parallel with PDF)

**Files:**
- Modify: `qbu_crawler/server/report_pdf.py` (add `render_v3_html`)
- Modify: `qbu_crawler/server/report_snapshot.py` (generate V3 HTML alongside PDF)

- [ ] **Step 1: Add V3 HTML render function**

In `report_pdf.py`, add:

```python
def render_v3_html(snapshot, analytics, output_path=None):
    """Render the V3 interactive HTML report.

    Returns the file path of the generated HTML file.
    """
    from qbu_crawler.server.report_charts import build_chartjs_configs

    normalized = normalize_deep_report_analytics(analytics)
    charts = build_chartjs_configs(analytics)

    # Load template
    template_dir = Path(__file__).parent / "report_templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)))
    template = env.get_template("daily_report_v3.html.j2")

    css_text = (template_dir / "daily_report_v3.css").read_text(encoding="utf-8")
    js_text = (template_dir / "daily_report_v3.js").read_text(encoding="utf-8")

    html = template.render(
        logical_date=snapshot.get("logical_date", ""),
        mode=normalized.get("mode", "baseline"),
        snapshot=snapshot,
        analytics=normalized,
        charts=charts,
        alert_level=normalized.get("alert_level", ("green", ""))[0],
        alert_text=normalized.get("alert_level", ("green", ""))[1],
        report_copy=analytics.get("report_copy", {}),
        css_text=css_text,
        js_text=js_text,
    )

    if output_path is None:
        run_id = snapshot.get("run_id", 0)
        logical_date = snapshot.get("logical_date", "unknown")
        output_path = os.path.join(config.REPORT_DIR, f"workflow-run-{run_id}-report-v3.html")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    Path(output_path).write_text(html, encoding="utf-8")
    return output_path
```

- [ ] **Step 2: Call from report pipeline**

In `report_snapshot.py::generate_full_report_from_snapshot`, after the existing PDF generation, add:

```python
# V3 HTML output (parallel with PDF during Phase 3a)
try:
    v3_html_path = report_pdf.render_v3_html(snapshot, analytics)
    logger.info("V3 HTML report generated: %s", v3_html_path)
except Exception:
    logger.exception("V3 HTML generation failed (non-blocking)")
    v3_html_path = None
```

Add `v3_html_path` to the return dict.

- [ ] **Step 3: Run all tests**

Run: `uv run pytest tests/ -x -q --ignore=tests/test_report_charts.py`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add qbu_crawler/server/report_pdf.py qbu_crawler/server/report_snapshot.py
git commit -m "feat(report): wire V3 HTML render into pipeline (parallel with PDF)

V3 HTML generated alongside existing PDF. Non-blocking: PDF output unaffected
if V3 rendering fails."
```

---

## Phase 3a Completion Checklist

- [ ] `daily_report_v3.html.j2` renders all 6 tabs
- [ ] `daily_report_v3.css` includes responsive + print styles
- [ ] `daily_report_v3.js` implements tabs, collapse, lightbox, sort, filter, print
- [ ] `build_chartjs_configs` returns configs for all chart types
- [ ] V3 HTML generated in parallel with PDF (both in report output)
- [ ] Charts render correctly in browser
- [ ] No `_uncategorized` in rendered HTML
- [ ] Data freshness timestamp visible in hero section
- [ ] Print-to-PDF produces clean output via `@media print`
- [ ] All existing tests pass
