"""Plotly chart builders for QBU PDF reports.

Each builder returns an HTML ``<div>`` fragment (with ``include_plotlyjs=False``)
ready to be embedded into a Jinja2 template that loads plotly.js once globally.
"""

from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio

# ── Design tokens ────────────────────────────────────────────────────────────

_ACCENT = "#93543f"
_GREEN = "#345f57"
_GOLD = "#b0823a"
_PAPER = "#f5f0e8"
_PANEL = "#fffaf3"
_INK = "#201b16"
_MUTED = "#766d62"

_SEVERITY_COLORS = {
    "high": "#6b3328",
    "medium": "#b7633f",
    "low": "#a89070",
}

_CJK_FONT = "Microsoft YaHei, Noto Sans CJK SC, sans-serif"

# ── QBU Plotly template ──────────────────────────────────────────────────────

QBU_THEME = go.layout.Template(
    layout=go.Layout(
        font=dict(family=_CJK_FONT, color=_INK, size=12),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="white",
        margin=dict(l=10, r=10, t=36, b=10),
        title=dict(
            font=dict(size=13, color=_INK),
            x=0,
            xanchor="left",
        ),
        colorway=[_ACCENT, _GREEN, _GOLD, _MUTED, "#6b3328", "#b7633f", "#a89070"],
    )
)


# ── Helper ───────────────────────────────────────────────────────────────────


def _to_html(fig: go.Figure) -> str:
    """Convert a Plotly figure to a compact HTML div string."""
    return pio.to_html(
        fig,
        full_html=False,
        include_plotlyjs=False,
        config={
            "displayModeBar": False,
            "staticPlot": True,
            "responsive": True,
        },
    )


# ── Chart builders ───────────────────────────────────────────────────────────


def _build_health_gauge(
    value: float,
    threshold_red: float = 60,
    threshold_yellow: float = 80,
) -> str:
    """Gauge indicator for overall health index (0-100)."""
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=value,
            number=dict(font=dict(size=42, family=_CJK_FONT, color=_INK)),
            gauge=dict(
                axis=dict(range=[0, 100], tickfont=dict(size=10)),
                bar=dict(color=_ACCENT),
                bgcolor="white",
                steps=[
                    dict(range=[0, threshold_red], color="#f2d9d0"),
                    dict(range=[threshold_red, threshold_yellow], color="#f5ecd4"),
                    dict(range=[threshold_yellow, 100], color="#dce9e3"),
                ],
            ),
        )
    )
    fig.update_layout(
        template=QBU_THEME,
        height=180,
        margin=dict(l=20, r=20, t=20, b=10),
    )
    return _to_html(fig)


def _build_bar_chart(
    labels: list[str],
    values: list[float],
    title: str,
    colors: list[str] | None = None,
) -> str:
    """Horizontal bar chart sorted with highest values at top."""
    # Reverse so highest value appears at top in horizontal layout
    labels_r = list(reversed(labels))
    values_r = list(reversed(values))
    colors_r = list(reversed(colors)) if colors else None

    height = max(160, len(labels) * 36 + 50)

    fig = go.Figure(
        go.Bar(
            x=values_r,
            y=labels_r,
            orientation="h",
            text=[str(v) for v in values_r],
            textposition="outside",
            marker=dict(
                color=colors_r if colors_r else _ACCENT,
            ),
        )
    )
    fig.update_layout(
        template=QBU_THEME,
        title=dict(text=title),
        height=height,
        yaxis=dict(autorange="reversed", automargin=True),
        xaxis=dict(
            showgrid=True,
            gridcolor="#f0ebe3",
            griddash="dash",
        ),
        bargap=0.3,
        margin=dict(l=10, r=40, t=36, b=10, autoexpand=True),
    )
    return _to_html(fig)


def _build_heatmap(
    z: list[list[float]],
    x_labels: list[str],
    y_labels: list[str],
    title: str,
) -> str:
    """Feature x Product sentiment heatmap with diverging colors."""
    # Truncate long y-axis labels for readability
    max_label_len = 30
    display_labels = [
        (label[: max_label_len - 1] + "\u2026" if len(label) > max_label_len else label)
        for label in y_labels
    ]

    # Dynamic left margin based on longest displayed label
    longest = max((len(label) for label in display_labels), default=5)
    left_margin = max(40, min(longest * 7, 220))

    # Build annotation text (1 decimal)
    annotations = []
    for i, row in enumerate(z):
        for j, val in enumerate(row):
            annotations.append(
                dict(
                    x=x_labels[j],
                    y=display_labels[i],
                    text=f"{val:.1f}",
                    showarrow=False,
                    font=dict(size=11, color=_INK),
                )
            )

    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=x_labels,
            y=display_labels,
            zmid=0,
            zmin=-1,
            zmax=1,
            colorscale=[
                [0.0, "#c0392b"],
                [0.5, _PAPER],
                [1.0, _GREEN],
            ],
            colorbar=dict(
                title=dict(text="情感倾向", font=dict(size=11)),
                tickvals=[-1, 0, 1],
                ticktext=["负面", "中性", "正面"],
                len=0.8,
            ),
        )
    )
    height = max(200, len(y_labels) * 36 + 80)
    fig.update_layout(
        template=QBU_THEME,
        title=dict(text=title),
        height=height,
        annotations=annotations,
        xaxis=dict(side="bottom"),
        margin=dict(l=left_margin, r=10, t=36, b=10),
    )
    return _to_html(fig)


def _build_radar_chart(
    categories: list[str],
    own_values: list[float],
    competitor_values: list[float],
    title: str,
) -> str:
    """Radar (polar) chart comparing own vs competitor scores."""
    # Close polygon by appending first point
    cats = list(categories) + [categories[0]]
    own = list(own_values) + [own_values[0]]
    comp = list(competitor_values) + [competitor_values[0]]

    fig = go.Figure()
    fig.add_trace(
        go.Scatterpolar(
            r=own,
            theta=cats,
            fill="toself",
            fillcolor="rgba(147,84,63,0.15)",
            line=dict(color=_ACCENT, width=2),
            name="自有产品",
        )
    )
    fig.add_trace(
        go.Scatterpolar(
            r=comp,
            theta=cats,
            fill="toself",
            fillcolor="rgba(52,95,87,0.15)",
            line=dict(color=_GREEN, width=2),
            name="竞品",
        )
    )
    fig.update_layout(
        template=QBU_THEME,
        title=dict(text=title),
        height=280,
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 1], showticklabels=False),
            bgcolor="white",
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
        margin=dict(l=40, r=40, t=50, b=20),
    )
    return _to_html(fig)


def _build_quadrant_scatter(
    products: list[dict],
    title: str,
) -> str:
    """Price vs Rating scatter with median reference lines."""
    own = [p for p in products if p.get("ownership") == "own"]
    comp = [p for p in products if p.get("ownership") != "own"]

    fig = go.Figure()

    def _truncate(name: str, max_len: int = 20) -> str:
        return name[:max_len - 1] + "\u2026" if len(name) > max_len else name

    if own:
        fig.add_trace(
            go.Scatter(
                x=[p["price"] for p in own],
                y=[p["rating"] for p in own],
                mode="markers+text",
                marker=dict(symbol="triangle-up", size=12, color=_ACCENT),
                text=[_truncate(p["name"]) for p in own],
                textposition="top center",
                textfont=dict(size=10),
                name="自有产品",
            )
        )
    if comp:
        fig.add_trace(
            go.Scatter(
                x=[p["price"] for p in comp],
                y=[p["rating"] for p in comp],
                mode="markers+text",
                marker=dict(symbol="circle", size=10, color=_GREEN),
                text=[_truncate(p["name"]) for p in comp],
                textposition="bottom center",
                textfont=dict(size=10),
                name="竞品",
            )
        )

    # Median reference lines
    all_prices = [p["price"] for p in products]
    all_ratings = [p["rating"] for p in products]
    if all_prices and all_ratings:
        med_price = sorted(all_prices)[len(all_prices) // 2]
        med_rating = sorted(all_ratings)[len(all_ratings) // 2]
        fig.add_hline(
            y=med_rating,
            line_dash="dot",
            line_color=_MUTED,
            line_width=1,
        )
        fig.add_vline(
            x=med_price,
            line_dash="dot",
            line_color=_MUTED,
            line_width=1,
        )

    fig.update_layout(
        template=QBU_THEME,
        title=dict(text=title),
        height=280,
        xaxis=dict(title="价格 ($)", gridcolor="#f0ebe3", griddash="dash"),
        yaxis=dict(title="评分", gridcolor="#f0ebe3", griddash="dash"),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
        margin=dict(l=50, r=20, t=50, b=40),
    )
    return _to_html(fig)


def _build_trend_line(
    dates: list[str],
    values: list[float],
    title: str,
    y_label: str = "",
) -> str:
    """Simple line + markers trend chart."""
    fig = go.Figure(
        go.Scatter(
            x=dates,
            y=values,
            mode="lines+markers",
            line=dict(color=_ACCENT, width=2),
            marker=dict(size=6, color=_ACCENT),
        )
    )
    fig.update_layout(
        template=QBU_THEME,
        title=dict(text=title),
        height=200,
        yaxis=dict(
            title=y_label,
            gridcolor="#f0ebe3",
            griddash="dash",
        ),
        xaxis=dict(gridcolor="#f0ebe3", griddash="dash"),
        margin=dict(l=50, r=20, t=36, b=30),
    )
    return _to_html(fig)


def _build_stacked_bar(
    categories: list[str],
    positive: list[float],
    neutral: list[float],
    negative: list[float],
    title: str,
) -> str:
    """Stacked bar chart for sentiment distribution."""
    totals = [p + n + ne for p, n, ne in zip(positive, neutral, negative)]

    def _pct_text(values: list[float], _totals: list[float]) -> list[str]:
        return [
            f"{v / t * 100:.0f}%" if t > 0 and v / t >= 0.10 else ""
            for v, t in zip(values, _totals)
        ]

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=categories,
            y=positive,
            name="好评(\u22654\u661f)",
            marker=dict(color=_GREEN),
            text=_pct_text(positive, totals),
            textposition="inside",
            textfont=dict(size=9, color="white"),
        )
    )
    fig.add_trace(
        go.Bar(
            x=categories,
            y=neutral,
            name="中评(3\u661f)",
            marker=dict(color=_GOLD),
            text=_pct_text(neutral, totals),
            textposition="inside",
            textfont=dict(size=9),
        )
    )
    fig.add_trace(
        go.Bar(
            x=categories,
            y=negative,
            name="差评(\u22642\u661f)",
            marker=dict(color=_ACCENT),
            text=_pct_text(negative, totals),
            textposition="inside",
            textfont=dict(size=9, color="white"),
        )
    )
    fig.update_layout(
        template=QBU_THEME,
        title=dict(text=title),
        barmode="stack",
        height=240,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="center",
            x=0.5,
        ),
        xaxis=dict(gridcolor="#f0ebe3", griddash="dash"),
        yaxis=dict(gridcolor="#f0ebe3", griddash="dash"),
        margin=dict(l=40, r=20, t=50, b=30),
    )
    return _to_html(fig)


# ── Main entry point ─────────────────────────────────────────────────────────


def build_chart_html_fragments(analytics: dict) -> dict[str, str]:
    """Build all applicable chart HTML fragments from an analytics dict.

    Returns a mapping of chart name -> HTML ``<div>`` string.
    Only charts whose input data exists are built.
    """
    fragments: dict[str, str] = {}

    kpis = analytics.get("kpis") or {}
    self_data = analytics.get("self") or {}
    competitor_data = analytics.get("competitor") or {}

    # ── Health gauge (always) ────────────────────────────────────────────────
    health_index = kpis.get("health_index")
    if health_index is None:
        health_index = 50  # sensible default
    fragments["health_gauge"] = _build_health_gauge(health_index)

    # ── Self: risk products bar chart (top 6) ────────────────────────────────
    risk_products = self_data.get("risk_products") or []
    if risk_products:
        top6 = risk_products[:6]
        labels = [p.get("product_name") or p.get("product_sku") or "?" for p in top6]
        values = [p.get("risk_score") or p.get("negative_review_rows") or 0 for p in top6]
        fragments["self_risk_products"] = _build_bar_chart(
            labels=labels,
            values=values,
            title="自有产品风险排名",
        )

    # ── Self: negative clusters bar chart (top 6, severity-colored) ──────────
    neg_clusters = self_data.get("top_negative_clusters") or []
    if neg_clusters:
        top6 = neg_clusters[:6]
        labels = [c.get("label_display") or c.get("label_code") or "?" for c in top6]
        values = [c.get("review_count") or 0 for c in top6]
        colors = [
            _SEVERITY_COLORS.get(c.get("severity"), _MUTED)
            for c in top6
        ]
        fragments["self_negative_clusters"] = _build_bar_chart(
            labels=labels,
            values=values,
            title="差评问题簇",
            colors=colors,
        )

    # ── Competitor: positive themes bar chart (top 6, green) ─────────────────
    pos_themes = competitor_data.get("top_positive_themes") or []
    if pos_themes:
        top6 = pos_themes[:6]
        labels = [t.get("label_display") or t.get("label_code") or "?" for t in top6]
        values = [t.get("review_count") or 0 for t in top6]
        colors = [_GREEN] * len(top6)
        fragments["competitor_positive_themes"] = _build_bar_chart(
            labels=labels,
            values=values,
            title="竞品好评主题",
            colors=colors,
        )

    # ── Price-rating quadrant scatter ────────────────────────────────────────
    products_for_charts = analytics.get("_products_for_charts") or []
    if len(products_for_charts) >= 3:
        fragments["price_rating_quadrant"] = _build_quadrant_scatter(
            products=products_for_charts,
            title="价格-评分象限图",
        )

    # ── Feature heatmap ──────────────────────────────────────────────────────
    heatmap_data = analytics.get("_heatmap_data")
    if heatmap_data:
        fragments["feature_heatmap"] = _build_heatmap(
            z=heatmap_data["z"],
            x_labels=heatmap_data["x_labels"],
            y_labels=heatmap_data["y_labels"],
            title="特征情感热力图",
        )

    # ── Competitive radar ────────────────────────────────────────────────────
    radar_data = analytics.get("_radar_data")
    if radar_data:
        fragments["competitive_radar"] = _build_radar_chart(
            categories=radar_data["categories"],
            own_values=radar_data["own_values"],
            competitor_values=radar_data["competitor_values"],
            title="竞品对标雷达图",
        )

    # ── Sentiment distribution (own) ────────────────────────────────
    sentiment_own = analytics.get("_sentiment_distribution_own")
    if sentiment_own:
        fragments["sentiment_distribution_own"] = _build_stacked_bar(
            categories=sentiment_own["categories"],
            positive=sentiment_own["positive"],
            neutral=sentiment_own["neutral"],
            negative=sentiment_own["negative"],
            title="自有产品评分分布",
        )

    # ── Sentiment distribution (competitor) ─────────────────────────
    sentiment_comp = analytics.get("_sentiment_distribution_competitor")
    if sentiment_comp:
        fragments["sentiment_distribution_competitor"] = _build_stacked_bar(
            categories=sentiment_comp["categories"],
            positive=sentiment_comp["positive"],
            neutral=sentiment_comp["neutral"],
            negative=sentiment_comp["negative"],
            title="竞品评分分布",
        )

    # ── Rating trend line (from _trend_series per-product data) ────────────
    trend_series = analytics.get("_trend_series") or []
    # Build chart from own products with ≥2 data points
    for ts in trend_series:
        series = ts.get("series") or []
        if len(series) >= 2:
            dates = [s.get("date", "")[:10] for s in series]
            values = [s.get("rating") or 0 for s in series]
            fragments["rating_trend"] = _build_trend_line(
                dates=dates,
                values=values,
                title=f"评分趋势 — {ts.get('product_name', '')}",
                y_label="评分",
            )
            break  # show first product with enough data

    return fragments


# ── Chart.js config builders (V3 HTML report) ──────────────────────────────

def build_chartjs_configs(analytics):
    """Build Chart.js configuration dicts for the V3 HTML report.

    Returns dict of {chart_name: chartjs_config_dict}.
    Each config is a JSON-serializable dict matching Chart.js constructor args.
    """
    configs = {}

    health = (analytics.get("kpis") or {}).get("health_index")
    if health is not None:
        configs["health_gauge"] = _chartjs_health_gauge(health)

    radar = analytics.get("_radar_data")
    if radar and len(radar.get("categories", [])) >= 3:
        configs["radar"] = _chartjs_radar(radar)

    for key, name in [("_sentiment_distribution_own", "sentiment_own"),
                       ("_sentiment_distribution_competitor", "sentiment_comp")]:
        dist = analytics.get(key)
        if dist and dist.get("categories"):
            configs[name] = _chartjs_stacked_bar(dist, name)

    products = analytics.get("_products_for_charts")
    if products and len(products) >= 2:
        configs["scatter"] = _chartjs_scatter(products)

    heatmap = analytics.get("_heatmap_data")
    if heatmap and len(heatmap.get("y_labels", [])) >= 3:
        configs["heatmap"] = _chartjs_heatmap_table(heatmap)

    return configs


def _chartjs_health_gauge(health_value):
    """Doughnut chart simulating a gauge (0-100)."""
    remaining = max(100 - health_value, 0)
    if health_value >= 60:
        color = _GREEN
    elif health_value >= 45:
        color = _GOLD
    else:
        color = _ACCENT
    return {
        "type": "doughnut",
        "data": {
            "datasets": [{
                "data": [health_value, remaining],
                "backgroundColor": [color, "#e8e0d4"],
                "borderWidth": 0,
            }],
        },
        "options": {
            "cutout": "75%",
            "rotation": -90,
            "circumference": 180,
            "plugins": {
                "legend": {"display": False},
                "tooltip": {"enabled": False},
            },
            "responsive": True,
            "maintainAspectRatio": True,
        },
    }


def _chartjs_radar(radar_data):
    """Radar chart comparing own vs competitor across dimensions."""
    return {
        "type": "radar",
        "data": {
            "labels": radar_data["categories"],
            "datasets": [
                {
                    "label": "自有",
                    "data": radar_data["own_values"],
                    "backgroundColor": "rgba(147, 84, 63, 0.15)",
                    "borderColor": _ACCENT,
                    "borderWidth": 2,
                    "pointRadius": 3,
                },
                {
                    "label": "竞品",
                    "data": radar_data["competitor_values"],
                    "backgroundColor": "rgba(52, 95, 87, 0.15)",
                    "borderColor": _GREEN,
                    "borderWidth": 2,
                    "pointRadius": 3,
                },
            ],
        },
        "options": {
            "scales": {"r": {"beginAtZero": True, "max": 1.0, "ticks": {"display": False}}},
            "plugins": {"legend": {"position": "bottom"}},
            "responsive": True,
        },
    }


def _chartjs_stacked_bar(dist_data, chart_id):
    """Stacked bar chart for sentiment distribution."""
    return {
        "type": "bar",
        "data": {
            "labels": dist_data["categories"],
            "datasets": [
                {"label": "好评(≥4星)", "data": dist_data.get("positive", []), "backgroundColor": _GREEN},
                {"label": "中评(3星)", "data": dist_data.get("neutral", []), "backgroundColor": _GOLD},
                {"label": "差评(≤2星)", "data": dist_data.get("negative", []), "backgroundColor": _ACCENT},
            ],
        },
        "options": {
            "scales": {
                "x": {"stacked": True, "ticks": {"maxRotation": 45}},
                "y": {"stacked": True, "beginAtZero": True},
            },
            "plugins": {"legend": {"position": "bottom"}},
            "responsive": True,
        },
    }


def _chartjs_scatter(products):
    """Scatter chart: price (x) vs rating (y) with ownership coloring."""
    own = [p for p in products if p.get("ownership") == "own"]
    comp = [p for p in products if p.get("ownership") != "own"]

    def _points(product_list):
        return [{"x": p.get("price", 0), "y": p.get("rating", 0), "label": p.get("name", "")[:18]}
                for p in product_list]

    return {
        "type": "scatter",
        "data": {
            "datasets": [
                {
                    "label": "自有",
                    "data": _points(own),
                    "backgroundColor": _ACCENT,
                    "pointStyle": "triangle",
                    "pointRadius": 8,
                },
                {
                    "label": "竞品",
                    "data": _points(comp),
                    "backgroundColor": _GREEN,
                    "pointStyle": "circle",
                    "pointRadius": 6,
                },
            ],
        },
        "options": {
            "scales": {
                "x": {"title": {"display": True, "text": "价格 ($)"}},
                "y": {"title": {"display": True, "text": "评分"}, "min": 0, "max": 5},
            },
            "plugins": {
                "legend": {"position": "bottom"},
                "tooltip": {"enabled": True},
            },
            "responsive": True,
        },
    }


def _chartjs_heatmap_table(heatmap_data):
    """Heatmap data as a table structure (Chart.js doesn't have native heatmap).

    Returns data for rendering as an HTML table with colored cells, not a chart.
    """
    return {
        "type": "table",  # Custom: rendered as HTML table, not Chart.js canvas
        "x_labels": heatmap_data.get("x_labels", []),
        "y_labels": heatmap_data.get("y_labels", []),
        "z": heatmap_data.get("z", []),
    }
