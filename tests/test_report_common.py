"""Tests for server/report_common.py — shared constants and helpers."""

from datetime import date

import pytest
from qbu_crawler.server.report_common import (
    _LABEL_DISPLAY,
    _SEVERITY_DISPLAY,
    _PRIORITY_DISPLAY,
    _label_display,
    _summary_text,
    normalize_deep_report_analytics,
)


def test_label_display_known_code():
    assert _label_display("quality_stability") == "质量稳定性"


def test_label_display_unknown_code():
    assert _label_display("unknown_xyz") == "unknown_xyz"


def test_summary_text_cn_preferred():
    review = {"headline_cn": "标题", "body_cn": "内容", "headline": "Title", "body": "Content"}
    result = _summary_text(review)
    assert "标题" in result
    assert "内容" in result


def test_normalize_handles_none():
    result = normalize_deep_report_analytics(None)
    assert result["kpis"]["product_count"] == 0
    assert result["mode"] == "baseline"


def test_normalize_exposes_semantic_contract_fields():
    analytics = {
        "mode": "baseline",
        "kpis": {"ingested_review_rows": 5},
    }

    result = normalize_deep_report_analytics(analytics)

    assert result["report_semantics"] == "bootstrap"
    assert result["is_bootstrap"] is True
    assert result["change_digest"] == {}
    assert result["trend_digest"] == {}
    assert result["kpis"]["ingested_review_rows"] == 5


def test_normalize_preserves_trend_digest_contract():
    analytics = {
        "mode": "incremental",
        "kpis": {"ingested_review_rows": 5},
        "trend_digest": {
            "views": ["week", "month", "year"],
            "dimensions": ["sentiment", "issues", "products", "competition"],
            "default_view": "month",
            "default_dimension": "sentiment",
            "data": {
                "month": {
                    "sentiment": {
                        "status": "ready",
                        "status_message": "",
                        "kpis": {"status": "ready", "items": []},
                        "primary_chart": {"status": "ready", "labels": [], "series": []},
                        "table": {"status": "ready", "columns": [], "rows": []},
                    }
                }
            },
        },
    }

    result = normalize_deep_report_analytics(analytics)

    assert result["trend_digest"]["default_view"] == "month"
    assert result["trend_digest"]["default_dimension"] == "sentiment"
    assert result["trend_digest"]["data"]["month"]["sentiment"]["status"] == "ready"


def test_normalize_computes_rates():
    analytics = {"kpis": {"ingested_review_rows": 100, "negative_review_rows": 10, "translated_count": 90}}
    result = normalize_deep_report_analytics(analytics)
    # 修 8: 顶层混合口径已重命名为 all_sample_negative_rate_display
    assert result["kpis"]["all_sample_negative_rate_display"] == "10.0%"
    assert result["kpis"]["translation_completion_rate_display"] == "90.0%"


def test_parse_date_flexible_supports_hours_ago():
    from qbu_crawler.server.report_common import _parse_date_flexible

    anchor = date(2026, 4, 23)

    assert _parse_date_flexible("12 hours ago", anchor_date=anchor) == anchor
    assert _parse_date_flexible("30 hours ago", anchor_date=anchor) == date(2026, 4, 22)


def test_issue_cards_complete_fields():
    """issue_cards must carry all fields required by the P3 template."""
    from qbu_crawler.server.report_common import normalize_deep_report_analytics
    analytics = {
        "logical_date": "2026-04-07",
        "mode": "baseline",
        "snapshot_hash": "abc",
        "kpis": {"ingested_review_rows": 5},
        "self": {
            "risk_products": [],
            "top_negative_clusters": [
                {
                    "label_code": "quality_stability",
                    "review_count": 3,
                    "severity": "high",
                    "affected_product_count": 1,
                    "first_seen": "2026-01-01",
                    "last_seen": "2026-04-01",
                    "image_review_count": 1,
                    "deep_analysis": {
                        "actionable_summary": "优先复核开关耐久与批次质量。",
                        "failure_modes": [{"name": "开关失效", "frequency": 2}],
                        "root_causes": [{"name": "出厂抽检不足"}],
                        "user_workarounds": ["用户反复重启设备"],
                    },
                    "example_reviews": [
                        {"product_name": "P", "rating": 1, "headline": "bad",
                         "headline_cn": "差", "body": "broke", "body_cn": "坏了",
                         "images": ["https://example.com/img1.jpg"],
                         "author": "A", "date_published": "2026-01-01"}
                    ],
                }
            ],
            "recommendations": [],
        },
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
        "appendix": {"image_reviews": []},
        "report_copy": {
            "improvement_priorities": [
                {"label_code": "quality_stability", "full_action": "加强出厂耐久测试", "evidence_count": 3}
            ]
        },
    }
    result = normalize_deep_report_analytics(analytics)
    card = result["self"]["issue_cards"][0]
    assert card["first_seen"] == "2026-01-01"
    assert card["last_seen"] == "2026-04-01"
    # F011 H5 — duration_display retired in favor of frequent_period {start,end}
    assert "duration_display" not in card
    assert card["frequent_period"] == {"start": "2026-01", "end": "2026-04"}
    assert len(card["example_reviews"]) == 1
    assert len(card["image_evidence"]) == 1
    assert card["image_evidence"][0]["url"] == "https://example.com/img1.jpg"
    assert card["image_evidence"][0]["evidence_id"] == "I1"
    assert card["image_evidence"][0]["data_uri"] is None  # data_uri is None pre-render (render_report_html converts it)
    assert card["recommendation"] == "加强出厂耐久测试"
    assert card["ai_recommendation"] == "加强出厂耐久测试"
    assert card["failure_modes"] == [{"name": "开关失效", "frequency": 2}]
    assert card["root_causes"] == [{"name": "出厂抽检不足"}]
    assert card["user_workarounds"] == ["用户反复重启设备"]


def test_humanize_bullets_backfill_notice_survives_truncation():
    """When >50% reviews are backfill, the notice must appear in first 3 bullets."""
    from qbu_crawler.server.report_common import _humanize_bullets

    normalized = {
        "kpis": {
            "ingested_review_rows": 100,
            "recently_published_count": 10,
            "own_negative_review_rows_delta": 0,
            "product_count": 2,
            "own_product_count": 1,
            "competitor_product_count": 1,
            "own_review_rows": 80,
        },
        "self": {"risk_products": [
            {"product_name": "P1", "negative_review_rows": 5, "total_reviews": 50, "top_labels": [{"label_code": "quality_stability", "count": 5}]}
        ]},
        "competitor": {"top_positive_themes": [{"label_display": "易清洗", "review_count": 3}], "gap_analysis": []},
    }
    bullets = _humanize_bullets(normalized)
    assert len(bullets) <= 3
    assert any("历史评论池" in b for b in bullets), f"Backfill notice missing from: {bullets}"


# ---------------------------------------------------------------------------
# Tests for _cluster_summary_items and _risk_products (report_analytics)
# ---------------------------------------------------------------------------

from qbu_crawler.server.report_analytics import _cluster_summary_items, _risk_products


def _make_labeled_review(ownership, polarity, label_code, severity="medium",
                         product_sku="SKU-1", product_name="Product A",
                         date_published="2026-03-01", headline="Title", body="Body",
                         headline_cn="标题", body_cn="正文", images=None):
    return {
        "review": {
            "ownership": ownership, "product_sku": product_sku,
            "product_name": product_name, "date_published": date_published,
            "headline": headline, "body": body,
            "headline_cn": headline_cn, "body_cn": body_cn,
        },
        "labels": [{"label_code": label_code, "label_polarity": polarity, "severity": severity, "confidence": 0.9}],
        "images": images or [],
    }


def test_cluster_has_affected_product_count():
    reviews = [
        _make_labeled_review("own", "negative", "quality_stability", product_sku="A"),
        _make_labeled_review("own", "negative", "quality_stability", product_sku="B"),
        _make_labeled_review("own", "negative", "quality_stability", product_sku="A"),
    ]
    items = _cluster_summary_items(reviews, ownership="own", polarity="negative")
    assert items[0]["affected_product_count"] == 2


def test_cluster_has_timeline():
    reviews = [
        _make_labeled_review("own", "negative", "quality_stability", date_published="2026-02-14"),
        _make_labeled_review("own", "negative", "quality_stability", date_published="2026-03-29"),
    ]
    items = _cluster_summary_items(reviews, ownership="own", polarity="negative")
    assert items[0]["first_seen"] == "2026-02-14"
    assert items[0]["last_seen"] == "2026-03-29"


def test_cluster_example_has_en_and_date():
    reviews = [
        _make_labeled_review("own", "negative", "quality_stability",
                             headline="Broke!", body="Support beam snapped",
                             date_published="2026-03-12"),
    ]
    items = _cluster_summary_items(reviews, ownership="own", polarity="negative")
    ex = items[0]["example_reviews"][0]
    assert ex["headline_en"] == "Broke!"
    assert ex["body_en"] == "Support beam snapped"
    assert ex["date_published"] == "2026-03-12"


def test_cluster_no_dates():
    reviews = [
        _make_labeled_review("own", "negative", "quality_stability", date_published=""),
    ]
    items = _cluster_summary_items(reviews, ownership="own", polarity="negative")
    assert items[0]["first_seen"] is None
    assert items[0]["last_seen"] is None


def test_risk_products_has_total_reviews():
    reviews = [
        _make_labeled_review("own", "negative", "quality_stability",
                             product_sku="SKU-1", severity="high"),
    ]
    items = _risk_products(reviews, snapshot_products=[
        {"sku": "SKU-1", "review_count": 50},
    ])
    assert items[0]["total_reviews"] == 50


def test_risk_products_no_snapshot():
    reviews = [
        _make_labeled_review("own", "negative", "quality_stability",
                             product_sku="SKU-1", severity="high"),
    ]
    items = _risk_products(reviews)
    assert items[0]["total_reviews"] == 0


# ---------------------------------------------------------------------------
# Tests for _competitor_gap_analysis and _compute_kpi_deltas
# ---------------------------------------------------------------------------

from qbu_crawler.server.report_common import (
    _competitor_gap_analysis,
    _compute_kpi_deltas,
)


def test_competitor_gap_analysis_finds_intersection():
    # quality_stability and material_finish both map to "solid_build" via _NEGATIVE_TO_POSITIVE_DIMENSION
    normalized = {
        "self": {"top_negative_clusters": [
            {"label_code": "quality_stability", "review_count": 13},
            {"label_code": "material_finish", "review_count": 7},
        ]},
        "competitor": {"top_positive_themes": [
            {"label_code": "solid_build", "review_count": 69},
        ]},
    }
    gaps = _competitor_gap_analysis(normalized)
    assert len(gaps) == 1
    assert gaps[0]["label_code"] == "solid_build"
    assert gaps[0]["competitor_positive_count"] == 69
    assert gaps[0]["own_negative_count"] == 20  # 13 + 7 aggregated under solid_build


def test_competitor_gap_analysis_one_sided_competitor():
    # service_fulfillment has no positive counterpart in _NEGATIVE_TO_POSITIVE_DIMENSION
    # but solid_build from competitor still appears via union
    normalized = {
        "self": {"top_negative_clusters": [{"label_code": "service_fulfillment", "review_count": 7}]},
        "competitor": {"top_positive_themes": [{"label_code": "solid_build", "review_count": 69}]},
    }
    gaps = _competitor_gap_analysis(normalized)
    assert len(gaps) == 1
    assert gaps[0]["label_code"] == "solid_build"
    assert gaps[0]["own_negative_count"] == 0
    assert gaps[0]["gap_type"] in ("追赶", "监控")  # new algo: no own negatives → catch_up or monitor
    assert gaps[0]["fix_urgency"] == 0  # own_rate = 0


def test_gap_analysis_includes_one_sided_dimensions():
    """Gap analysis should include dimensions where only one side has data."""
    normalized = {
        "kpis": {"competitor_review_rows": 36, "own_review_rows": 112},
        "competitor": {
            "top_positive_themes": [
                {"label_code": "solid_build", "review_count": 9},
            ],
        },
        "self": {
            "top_negative_clusters": [
                {"label_code": "noise_power", "review_count": 8},
            ],
        },
    }
    gaps = _competitor_gap_analysis(normalized)
    # Should include dimensions from BOTH sides
    codes = [g["label_code"] for g in gaps]
    # solid_build from competitor positive, strong_performance from noise_power mapping
    assert "solid_build" in codes
    assert "strong_performance" in codes
    assert len(gaps) >= 2
    # Verify gap_type is present and uses new taxonomy
    for g in gaps:
        assert "gap_type" in g
        assert g["gap_type"] in ("止血", "追赶", "监控")
    # solid_build has only competitor data → 追赶 (catch_up_gap = 9/36 = 25% ≥ 20%)
    sb = next(g for g in gaps if g["label_code"] == "solid_build")
    assert sb["gap_type"] == "追赶"
    assert sb["own_negative_count"] == 0
    # strong_performance has only own negative data → 监控 (own_rate = 8/112 ≈ 7.1% < 10%)
    sp = next(g for g in gaps if g["label_code"] == "strong_performance")
    assert sp["gap_type"] == "监控"
    assert sp["competitor_positive_count"] == 0


def test_compute_kpi_deltas_normal():
    current = {"negative_review_rows": 78, "ingested_review_rows": 636, "product_count": 9}
    prev = {"kpis": {"negative_review_rows": 66, "ingested_review_rows": 500, "product_count": 9}}
    deltas = _compute_kpi_deltas(current, prev)
    assert deltas["negative_review_rows_delta"] == 12
    assert deltas["negative_review_rows_delta_display"] == "+12"
    assert deltas["product_count_delta"] == 0
    assert deltas["product_count_delta_display"] == "—"


def test_compute_kpi_deltas_rounds_health_index():
    current = {"health_index": 50.0}
    prev = {"kpis": {"health_index": 71.4}}
    deltas = _compute_kpi_deltas(current, prev)
    assert deltas["health_index_delta"] == -21.4
    assert deltas["health_index_delta_display"] == "-21.4"


def test_compute_kpi_deltas_no_prev():
    deltas = _compute_kpi_deltas({"negative_review_rows": 78}, None)
    assert deltas == {}


def test_compute_kpi_deltas_missing_field():
    deltas = _compute_kpi_deltas({"negative_review_rows": 10}, {"kpis": {}})
    assert deltas["negative_review_rows_delta"] == 10


# ---------------------------------------------------------------------------
# Tests for _generate_hero_headline, _compute_alert_level, _humanize_bullets
# ---------------------------------------------------------------------------

from qbu_crawler.server.report_common import (
    _generate_hero_headline,
    _compute_alert_level,
    _humanize_bullets,
)


def test_hero_headline_with_delta():
    normalized = {
        "self": {"risk_products": [{"product_name": "Cabela's Stuffer", "negative_review_rows": 18,
                                     "total_reviews": 50, "top_labels": [{"label_code": "quality_stability", "count": 14}]}],
                 "top_negative_clusters": []},
        "competitor": {"top_positive_themes": []},
        "kpis": {"own_negative_review_rows_delta": 12},
    }
    result = _generate_hero_headline(normalized)
    assert "环比" in result
    assert "Cabela's Stuffer" in result
    assert "质量稳定性" in result


def test_hero_headline_no_delta():
    normalized = {
        "self": {"risk_products": [{"product_name": "Stuffer", "negative_review_rows": 18,
                                     "total_reviews": 50, "top_labels": [{"label_code": "quality_stability"}]}]},
        "competitor": {"top_positive_themes": []},
        "kpis": {},
    }
    result = _generate_hero_headline(normalized)
    assert "36%" in result  # 18/50


def test_hero_headline_no_risk():
    normalized = {"self": {"risk_products": []}, "competitor": {"top_positive_themes": []}, "kpis": {}}
    result = _generate_hero_headline(normalized)
    assert "样本不足" in result


def test_alert_level_red():
    # V3: red triggered by health below HEALTH_RED threshold with own reviews present
    normalized = {
        "mode": "incremental",
        "self": {"top_negative_clusters": [{"severity": "high", "review_count": 10, "is_new_or_escalated": True}]},
        "kpis": {"own_review_rows": 100, "health_index": 40.0, "own_negative_review_rows_delta": 0},
    }
    level, _ = _compute_alert_level(normalized)
    assert level == "red"


def test_alert_level_yellow():
    # V3: yellow triggered by positive neg_delta with health above red threshold
    normalized = {
        "mode": "incremental",
        "self": {"top_negative_clusters": []},
        "kpis": {"own_review_rows": 100, "health_index": 70.0, "own_negative_review_rows_delta": 5},
    }
    level, _ = _compute_alert_level(normalized)
    assert level == "yellow"


def test_alert_level_green():
    # V3: green when own reviews present, healthy index, no neg delta
    normalized = {
        "mode": "incremental",
        "self": {"top_negative_clusters": []},
        "kpis": {"own_review_rows": 50, "health_index": 80.0, "own_negative_review_rows_delta": 0},
    }
    level, _ = _compute_alert_level(normalized)
    assert level == "green"


def test_humanize_bullets_with_rate_and_delta():
    normalized = {
        "self": {"risk_products": [{"product_name": "Stuffer", "negative_review_rows": 18,
                                     "total_reviews": 50, "top_labels": [{"label_code": "quality_stability"}]}]},
        "competitor": {"top_positive_themes": [{"label_display": "做工扎实", "review_count": 69, "label_code": "solid_build"}],
                       "gap_analysis": []},
        # recently_published_count >= 50% of ingested so backfill notice does NOT fire
        "kpis": {"product_count": 9, "ingested_review_rows": 636, "recently_published_count": 636,
                 "untranslated_count": 0, "own_negative_review_rows_delta": 5,
                 "translation_completion_rate": 1.0},
    }
    bullets = _humanize_bullets(normalized)
    assert len(bullets) == 3
    assert "36%" in bullets[0]
    assert "新增 5 条" in bullets[0]


def test_humanize_bullets_low_translation():
    normalized = {
        "self": {"risk_products": []},
        "competitor": {"top_positive_themes": [], "gap_analysis": []},
        "kpis": {"product_count": 5, "ingested_review_rows": 100,
                 "untranslated_count": 40, "translation_completion_rate": 0.6},
    }
    bullets = _humanize_bullets(normalized)
    assert any("翻译未完成" in b for b in bullets)


# ---------------------------------------------------------------------------
# Tests for compute_health_index and compute_competitive_gap_index
# ---------------------------------------------------------------------------

from qbu_crawler.server import report_common


def test_compute_health_index_perfect():
    # NPS-proxy: all promoters → NPS=100 — but only 10 reviews so shrinkage applies
    analytics = {
        "kpis": {
            "own_review_rows": 10,
            "own_positive_review_rows": 10,
            "own_negative_review_rows": 0,
        },
    }
    health, confidence = report_common.compute_health_index(analytics)
    # weight=10/30, health = 10/30*100 + 20/30*50 = 66.67
    assert 66.0 <= health <= 67.5
    assert confidence == "medium"


def test_compute_health_index_worst():
    # NPS-proxy: all detractors → NPS=-100 — but only 10 reviews so shrinkage applies
    analytics = {
        "kpis": {
            "own_review_rows": 10,
            "own_positive_review_rows": 0,
            "own_negative_review_rows": 10,
        },
    }
    health, confidence = report_common.compute_health_index(analytics)
    # weight=10/30, health = 10/30*0 + 20/30*50 = 33.33
    assert 33.0 <= health <= 34.0
    assert confidence == "medium"


def test_compute_competitive_gap_index():
    gaps = [
        {"competitor_positive_count": 10, "own_negative_count": 5,
         "competitor_total": 100, "own_total": 100},
        {"competitor_positive_count": 8, "own_negative_count": 3,
         "competitor_total": 100, "own_total": 100},
    ]
    # dim1: (10/100 + 5/100) / 2 = 0.075
    # dim2: (8/100 + 3/100) / 2 = 0.055
    # avg = (0.075 + 0.055) / 2 = 0.065 → round(6.5) = 6
    assert report_common.compute_competitive_gap_index(gaps) == 6


def test_compute_competitive_gap_index_empty():
    assert report_common.compute_competitive_gap_index([]) == 0


def test_competitive_gap_index_normalized():
    """Gap index should be rate-based, not inflated by sample size."""
    from qbu_crawler.server.report_common import compute_competitive_gap_index

    small_sample = [
        {"competitor_positive_count": 5, "own_negative_count": 3,
         "competitor_total": 10, "own_total": 10},
    ]
    large_sample = [
        {"competitor_positive_count": 50, "own_negative_count": 30,
         "competitor_total": 100, "own_total": 100},
    ]
    idx_small = compute_competitive_gap_index(small_sample)
    idx_large = compute_competitive_gap_index(large_sample)
    # Same proportions → same index
    assert idx_small == idx_large, \
        f"Same proportions should yield equal index: {idx_small} vs {idx_large}"


# ---------------------------------------------------------------------------
# Tests for normalize injecting health_index, kpi_cards, issue_cards
# ---------------------------------------------------------------------------


def test_normalize_injects_health_index():
    analytics = {
        "kpis": {
            "ingested_review_rows": 100,
            "negative_review_rows": 10,
            "translated_count": 90,
            "own_product_count": 2,
            "own_avg_rating": 4.5,
        },
        "self": {"risk_products": [], "top_negative_clusters": [], "recommendations": []},
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
    }
    result = normalize_deep_report_analytics(analytics)
    assert "health_index" in result["kpis"]
    assert isinstance(result["kpis"]["health_index"], float)
    assert result["kpis"]["health_index"] > 0


def test_normalize_injects_kpi_cards():
    analytics = {
        "kpis": {"ingested_review_rows": 50, "negative_review_rows": 5, "translated_count": 50},
        "self": {"risk_products": [], "top_negative_clusters": [], "recommendations": []},
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
    }
    result = normalize_deep_report_analytics(analytics)
    assert "kpi_cards" in result
    # F011 v1.3 — 顶部 KPI 行只保留健康/信号指标；累计自有评论由 review_scope_cards 展示
    assert len(result["kpi_cards"]) == 6
    labels = [c["label"] for c in result["kpi_cards"]]
    assert "健康指数" in labels
    assert "竞品差距分" in labels
    assert "样本覆盖率" in labels
    # 移除：累计自有评论不应出现在顶部 KPI 行（避免与下方 review_scope_cards 重复）
    assert "累计自有评论" not in labels


def test_normalize_labels_cumulative_and_window_review_metrics():
    analytics = {
        "kpis": {
            "ingested_review_rows": 593,
            "own_review_rows": 450,
            "competitor_review_rows": 143,
            "recently_published_count": 1,
            "negative_review_rows": 12,
            "translated_count": 593,
        },
        "change_digest": {
            "summary": {
                "ingested_review_count": 32,
                "fresh_review_count": 1,
            }
        },
        "self": {"risk_products": [], "top_negative_clusters": [], "recommendations": []},
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
    }

    result = normalize_deep_report_analytics(analytics)

    labels = [card["label"] for card in result["kpi_cards"]]
    # F011 v1.3 — 顶部 KPI 行不再展示 "累计自有评论"（移到 review_scope_cards 避免重复）
    assert "累计自有评论" not in labels
    assert "自有评论" not in labels

    scope = {card["label"]: card["value"] for card in result["review_scope_cards"]}
    assert scope["累计自有评论"] == 450
    assert scope["累计竞品评论"] == 143
    assert scope["基线样本评论"] == 32
    assert scope["近30天评论"] == 1


def test_normalize_injects_issue_cards():
    analytics = {
        "kpis": {"ingested_review_rows": 10, "translated_count": 10},
        "self": {
            "risk_products": [],
            "top_negative_clusters": [
                {"label_code": "quality_stability", "severity": "high", "review_count": 5, "example_reviews": []},
            ],
            "recommendations": [],
        },
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
    }
    result = normalize_deep_report_analytics(analytics)
    assert "issue_cards" in result["self"]
    assert result["self"]["issue_cards"][0]["label_display"] == "质量稳定性"


def test_alert_level_red_on_low_health(monkeypatch):
    from qbu_crawler import config as _config
    monkeypatch.setattr(_config, "HEALTH_RED", 60)
    normalized = {
        "mode": "incremental",
        "self": {"top_negative_clusters": []},
        "kpis": {"own_review_rows": 100, "own_negative_review_rows_delta": 0, "health_index": 50},
    }
    level, text = _compute_alert_level(normalized)
    assert level == "red"
    assert "健康指数" in text


def test_alert_level_yellow_on_moderate_health(monkeypatch):
    from qbu_crawler import config as _config
    monkeypatch.setattr(_config, "HEALTH_YELLOW", 80)
    monkeypatch.setattr(_config, "HEALTH_RED", 60)
    normalized = {
        "mode": "incremental",
        "self": {"top_negative_clusters": []},
        "kpis": {"own_review_rows": 100, "own_negative_review_rows_delta": 0, "health_index": 70},
    }
    level, text = _compute_alert_level(normalized)
    assert level == "yellow"
    assert "健康指数" in text


# ---------------------------------------------------------------------------
# Tests for _risk_products rating_avg / negative_rate / top_features_display
# ---------------------------------------------------------------------------


def test_risk_products_has_rating_avg_and_negative_rate():
    """_risk_products via normalize returns rating_avg, negative_rate, top_features_display."""
    from qbu_crawler.server.report_analytics import _risk_products
    labeled_reviews = [
        {
            "review": {"product_sku": "SKU1", "product_name": "P1", "ownership": "own", "rating": 1},
            "labels": [{"label_code": "quality_stability", "label_polarity": "negative",
                        "severity": "high", "confidence": 0.9}],
            "images": [],
        },
        {
            "review": {"product_sku": "SKU1", "product_name": "P1", "ownership": "own", "rating": 5},
            "labels": [],
            "images": [],
        },
    ]
    snapshot_products = [{"sku": "SKU1", "rating": 3.5, "review_count": 20}]
    result = _risk_products(labeled_reviews, snapshot_products=snapshot_products)
    assert len(result) == 1
    p = result[0]
    assert p["rating_avg"] == 3.5          # from snapshot_products
    # F011 H6: denominator is ingested (2 reviews), not site total (20)
    assert p["negative_rate"] == pytest.approx(1 / 2)   # 1 negative / 2 ingested
    assert p["negative_rate_ingested"] == pytest.approx(1 / 2)
    assert p["negative_rate_site"] == pytest.approx(1 / 20)  # site denominator preserved for reference
    assert "top_features_display" in p


def test_risk_products_has_coverage_rate():
    """_risk_products should compute per-product coverage_rate (ingested/total)."""
    from qbu_crawler.server.report_analytics import _risk_products

    labeled_reviews = [
        {
            "review": {"product_sku": "SKU1", "product_name": "P1", "ownership": "own", "rating": 1},
            "labels": [{"label_code": "quality_stability", "label_polarity": "negative",
                        "severity": "high", "confidence": 0.9}],
            "images": [],
        },
        {
            "review": {"product_sku": "SKU1", "product_name": "P1", "ownership": "own", "rating": 5},
            "labels": [],
            "images": [],
        },
        {
            "review": {"product_sku": "SKU1", "product_name": "P1", "ownership": "own", "rating": 4},
            "labels": [{"label_code": "easy_to_use", "label_polarity": "positive",
                        "severity": "low", "confidence": 0.8}],
            "images": [],
        },
    ]
    snapshot_products = [{"sku": "SKU1", "rating": 3.5, "review_count": 100}]
    result = _risk_products(labeled_reviews, snapshot_products=snapshot_products)
    assert len(result) == 1
    p = result[0]
    # ingested = 3 (all own reviews for SKU1), total = 100 (site-reported)
    assert p["ingested_reviews"] == 3
    assert p["coverage_rate"] == pytest.approx(3 / 100)


def test_risk_products_coverage_rate_none_when_no_total():
    """coverage_rate should be None when site-reported total is 0."""
    from qbu_crawler.server.report_analytics import _risk_products

    labeled_reviews = [
        {
            "review": {"product_sku": "SKU1", "product_name": "P1", "ownership": "own", "rating": 1},
            "labels": [{"label_code": "quality_stability", "label_polarity": "negative",
                        "severity": "high", "confidence": 0.9}],
            "images": [],
        },
    ]
    result = _risk_products(labeled_reviews, snapshot_products=[])
    assert len(result) == 1
    assert result[0]["coverage_rate"] is None


def test_gap_analysis_has_gap_and_priority_display():
    """Gap analysis items must include 'gap' and 'priority_display'."""
    # material_finish maps to solid_build via _NEGATIVE_TO_POSITIVE_DIMENSION
    normalized = {
        "competitor": {
            "top_positive_themes": [
                {"label_code": "solid_build", "review_count": 10}
            ]
        },
        "self": {
            "top_negative_clusters": [
                {"label_code": "material_finish", "review_count": 6, "severity": "high"}
            ]
        },
    }
    gaps = _competitor_gap_analysis(normalized)
    assert len(gaps) == 1
    g = gaps[0]
    assert "gap" in g
    assert "priority_display" in g
    assert g["competitor_positive_count"] == 10
    assert g["own_negative_count"] == 6
    assert g["gap"] == 10 - 6
    assert g["priority_display"] in ("高", "中", "低")


# ---------------------------------------------------------------------------
# Tests for _duration_display with relative dates and MM/DD/YYYY
# ---------------------------------------------------------------------------


def test_duration_display_relative_dates():
    """_duration_display handles relative dates like 'X months ago'."""
    from qbu_crawler.server.report_common import _duration_display
    # Relative dates: "a year ago" is ~365 days, "2 months ago" is ~60 days → ~10 months apart
    result = _duration_display("a year ago", "2 months ago")
    assert result is not None
    assert "月" in result or "年" in result

    # MM/DD/YYYY dates: 01/01/2025 to 06/15/2025 → ~5 months
    result2 = _duration_display("01/01/2025", "06/15/2025")
    assert result2 is not None
    assert "月" in result2

    # Mixed formats: MM/DD/YYYY and ISO
    result3 = _duration_display("01/01/2025", "2026-06-15")
    assert result3 is not None

    # None inputs still return None
    assert _duration_display(None, "2026-01-01") is None
    assert _duration_display("2026-01-01", None) is None


def test_duration_display_year_display():
    """_duration_display renders '约 X 年' for long durations."""
    from qbu_crawler.server.report_common import _duration_display
    # 2 years apart
    result = _duration_display("2023-01-01", "2025-01-01")
    assert result is not None
    assert "年" in result


def test_duration_display_abs_order_invariant():
    """_duration_display returns same result regardless of argument order."""
    from qbu_crawler.server.report_common import _duration_display
    r1 = _duration_display("2026-01-01", "2026-04-01")
    r2 = _duration_display("2026-04-01", "2026-01-01")
    assert r1 == r2
    assert r1 is not None


def test_kpi_cards_value_class_health_index():
    """KPI cards should assign status color classes based on health_index threshold."""
    # Create analytics with conditions that result in low health (< 60)
    analytics = {
        "kpis": {
            "ingested_review_rows": 10,
            "negative_review_rows": 10,
            "translated_count": 10,
            "own_product_count": 1,
            "own_review_rows": 10,
            "own_negative_review_rate": 0.9,  # Very high negative rate
            "own_avg_rating": 1.0,  # Very low rating
        },
        "self": {
            "risk_products": [
                {"risk_score": 10},  # High risk product to lower health
            ],
            "top_negative_clusters": [],
            "recommendations": [],
        },
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
    }
    result = normalize_deep_report_analytics(analytics)
    health_card = [c for c in result["kpi_cards"] if c["label"] == "健康指数"][0]
    # Verify that the card has value_class set (it should be one of the severity classes)
    assert health_card["value_class"] in ["severity-high", "severity-medium", "severity-low"]


# ---------------------------------------------------------------------------
# Tests for _parse_date_flexible month/year precision
# ---------------------------------------------------------------------------


def test_parse_date_flexible_month_precision():
    """'5 months ago' from 2026-04-07 should be 2025-11-07, not 2025-11-08 (timedelta drift)."""
    from unittest.mock import patch
    from datetime import date as real_date
    from qbu_crawler.server import report_common

    class FakeDate(real_date):
        @classmethod
        def today(cls):
            return real_date(2026, 4, 7)

    with patch.object(report_common, "date", FakeDate):
        result = report_common._parse_date_flexible("5 months ago")

    assert result is not None
    assert result == real_date(2025, 11, 7), \
        f"Expected 2025-11-07 but got {result}"

    # Create analytics with high raw health (NPS-proxy: 9 promoters, 1 detractor → raw=90)
    # But only 10 reviews → Bayesian shrinkage: weight=10/30, health≈63.3 → severity-medium
    analytics2 = {
        "kpis": {
            "ingested_review_rows": 10,
            "negative_review_rows": 1,
            "translated_count": 10,
            "own_product_count": 1,
            "own_review_rows": 10,
            "own_positive_review_rows": 9,  # 9 promoters
            "own_negative_review_rows": 1,  # 1 detractor → raw health=90, shrunk ≈63.3
            "own_negative_review_rate": 0.1,
            "own_avg_rating": 4.8,
        },
        "self": {
            "risk_products": [],
            "top_negative_clusters": [],
            "recommendations": [],
        },
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
    }
    result2 = normalize_deep_report_analytics(analytics2)
    health_card2 = [c for c in result2["kpi_cards"] if c["label"] == "健康指数"][0]
    # Small sample shrinkage pulls 90→~63.3, which is severity-medium (60-80 range)
    assert health_card2["value_class"] in ["severity-medium", "severity-low", ""]


def test_kpi_cards_value_class_negative_rate():
    """KPI cards should assign status colors based on negative_review_rate thresholds."""
    analytics = {
        "kpis": {
            "ingested_review_rows": 10,
            "negative_review_rows": 5,
            "translated_count": 10,
            "own_product_count": 1,
            "own_review_rows": 10,
            "own_negative_review_rate": 0.25,  # 25% → severity-high
            "own_avg_rating": 3.0,
        },
        "self": {"risk_products": [], "top_negative_clusters": [], "recommendations": []},
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
    }
    result = normalize_deep_report_analytics(analytics)
    rate_card = [c for c in result["kpi_cards"] if c["label"] == "差评率"][0]
    assert rate_card["value_class"] == "severity-high"

    # Test middle range: 10% < rate < 20% → severity-medium
    analytics["kpis"]["own_negative_review_rate"] = 0.15  # 15%
    result = normalize_deep_report_analytics(analytics)
    rate_card = [c for c in result["kpi_cards"] if c["label"] == "差评率"][0]
    assert rate_card["value_class"] == "severity-medium"

    # Test good range: rate <= 10% → no class
    analytics["kpis"]["own_negative_review_rate"] = 0.05  # 5%
    result = normalize_deep_report_analytics(analytics)
    rate_card = [c for c in result["kpi_cards"] if c["label"] == "差评率"][0]
    assert rate_card["value_class"] == ""


def test_kpi_cards_value_class_high_risk_products():
    """KPI cards should assign severity-high for high_risk_count > 0."""
    from qbu_crawler import config as _config

    # Create analytics with high-risk products (risk_score >= HIGH_RISK_THRESHOLD)
    analytics = {
        "kpis": {
            "ingested_review_rows": 10,
            "negative_review_rows": 5,
            "translated_count": 10,
            "own_product_count": 1,
            "own_review_rows": 10,
            "own_negative_review_rate": 0.1,
            "own_avg_rating": 3.5,
        },
        "self": {
            "risk_products": [
                {"risk_score": _config.HIGH_RISK_THRESHOLD},  # Meets threshold
            ],
            "top_negative_clusters": [],
            "recommendations": [],
        },
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
    }
    result = normalize_deep_report_analytics(analytics)
    risk_card = [c for c in result["kpi_cards"] if c["label"] == "高风险产品"][0]
    assert risk_card["value_class"] == "severity-high"

    # Test with no high-risk products
    analytics2 = {
        "kpis": {
            "ingested_review_rows": 10,
            "negative_review_rows": 5,
            "translated_count": 10,
            "own_product_count": 1,
            "own_review_rows": 10,
            "own_negative_review_rate": 0.1,
            "own_avg_rating": 3.5,
        },
        "self": {
            "risk_products": [
                {"risk_score": _config.HIGH_RISK_THRESHOLD - 1},  # Below threshold
            ],
            "top_negative_clusters": [],
            "recommendations": [],
        },
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
    }
    result2 = normalize_deep_report_analytics(analytics2)
    risk_card2 = [c for c in result2["kpi_cards"] if c["label"] == "高风险产品"][0]
    assert risk_card2["value_class"] == ""


def test_normalize_separates_high_risk_and_attention_product_counts():
    from qbu_crawler import config as _config

    analytics = {
        "kpis": {
            "ingested_review_rows": 10,
            "negative_review_rows": 5,
            "translated_count": 10,
            "own_product_count": 3,
            "own_review_rows": 10,
            "own_negative_review_rate": 0.1,
        },
        "self": {
            "risk_products": [
                {"risk_score": _config.HIGH_RISK_THRESHOLD},
            ],
            "product_status": [
                {"product_name": "A", "risk_score": _config.HIGH_RISK_THRESHOLD, "status_lamp": "red"},
                {"product_name": "B", "risk_score": _config.HIGH_RISK_THRESHOLD - 1, "status_lamp": "yellow"},
                {"product_name": "C", "risk_score": 0, "status_lamp": "green"},
                {"product_name": "D", "risk_score": 0, "status_lamp": "gray"},
            ],
            "top_negative_clusters": [],
            "recommendations": [],
        },
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
    }

    result = normalize_deep_report_analytics(analytics)

    assert result["kpis"]["high_risk_count"] == 1
    assert result["kpis"]["attention_product_count"] == 2
    assert result["report_user_contract"]["kpi_semantics"]["attention_product_count"] == 2


def test_alert_level_ignores_competitor_negative_delta():
    """Competitor negative review growth must NOT trigger own-product yellow/red alert."""
    from qbu_crawler.server.report_common import _compute_alert_level

    # V3: build normalized dict directly with healthy own-product state.
    # own_negative_review_rows_delta=0 and high health means green, even if
    # total negative_review_rows_delta is large (competitor-driven).
    normalized = {
        "mode": "incremental",
        "self": {"top_negative_clusters": []},
        "kpis": {
            "own_review_rows": 100,
            "health_index": 80.0,
            "own_negative_review_rows_delta": 0,
            "negative_review_rows_delta": 10,  # competitor driven — should be ignored
        },
    }

    level, _ = _compute_alert_level(normalized)
    assert level == "green", f"Expected green but got {level} — competitor delta is inflating alert"


# ---------------------------------------------------------------------------
# Tests for _parse_date_flexible anchor_date parameter
# ---------------------------------------------------------------------------


def test_parse_date_flexible_anchor_date():
    """Relative dates should use anchor_date, not today."""
    from datetime import date
    from qbu_crawler.server.report_common import _parse_date_flexible

    anchor = date(2026, 4, 1)
    result = _parse_date_flexible("3 months ago", anchor_date=anchor)
    assert result == date(2026, 1, 1)

    # "a year ago" from anchor 2026-04-01
    result2 = _parse_date_flexible("a year ago", anchor_date=anchor)
    assert result2 == date(2025, 4, 1)

    # Without anchor, uses today (existing behavior preserved)
    result3 = _parse_date_flexible("2026-01-15")
    assert result3 == date(2026, 1, 15)


# ---------------------------------------------------------------------------
# Tests for date_published_parsed DB migration
# ---------------------------------------------------------------------------


def test_date_published_parsed_column_exists(tmp_path, monkeypatch):
    """After init_db, reviews table should have date_published_parsed column."""
    from qbu_crawler import config, models
    import sqlite3

    db_file = str(tmp_path / "test_migration.db")
    monkeypatch.setattr(config, "DB_PATH", db_file)

    def _get_conn():
        conn = sqlite3.connect(db_file)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(models, "get_conn", _get_conn)
    models.init_db()

    conn = _get_conn()
    # Should not raise
    conn.execute("SELECT date_published_parsed FROM reviews LIMIT 1")
    conn.close()


def test_date_published_parsed_backfill(tmp_path, monkeypatch):
    """init_db should backfill date_published_parsed from date_published + scraped_at anchor."""
    from qbu_crawler import config, models
    import sqlite3

    db_file = str(tmp_path / "test_backfill.db")
    monkeypatch.setattr(config, "DB_PATH", db_file)

    def _get_conn():
        conn = sqlite3.connect(db_file)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(models, "get_conn", _get_conn)
    models.init_db()

    # Insert a product and a review with date_published but no date_published_parsed
    conn = _get_conn()
    conn.execute(
        "INSERT INTO products (url, site, name, sku, price, stock_status, rating, review_count, ownership) "
        "VALUES ('http://x.com/p1', 'basspro', 'P1', 'S1', 10, 'in_stock', 4.0, 5, 'own')"
    )
    conn.execute(
        "INSERT INTO reviews (product_id, author, headline, body, body_hash, rating, date_published, scraped_at) "
        "VALUES (1, 'A1', 'H1', 'B1', 'h1', 5, '3 months ago', '2026-03-15 10:00:00')"
    )
    conn.commit()
    conn.close()

    # Re-run init_db to trigger backfill
    models.init_db()

    conn = _get_conn()
    row = conn.execute("SELECT date_published_parsed FROM reviews WHERE id = 1").fetchone()
    conn.close()
    assert row["date_published_parsed"] is not None
    assert row["date_published_parsed"] == "2025-12-15"


def test_cluster_summary_prefers_date_published_parsed():
    """_cluster_summary_items should prefer date_published_parsed over date_published."""
    from qbu_crawler.server.report_analytics import _cluster_summary_items

    labeled_reviews = [
        {
            "review": {
                "product_sku": "SKU1",
                "product_name": "P1",
                "ownership": "own",
                "rating": 1,
                "date_published": "3 months ago",
                "date_published_parsed": "2026-01-08",
            },
            "labels": [
                {"label_code": "quality_stability", "label_polarity": "negative",
                 "severity": "high", "confidence": 0.9}
            ],
            "images": [],
        },
    ]
    items = _cluster_summary_items(labeled_reviews, ownership="own", polarity="negative")
    assert len(items) == 1
    # The parsed date should be used instead of the relative string
    assert items[0]["first_seen"] == "2026-01-08"
    assert items[0]["last_seen"] == "2026-01-08"


def test_health_index_sensitive_to_negative_spike():
    """Health index should drop significantly when detractor count spikes (NPS-proxy)."""
    from qbu_crawler.server.report_common import compute_health_index

    # Baseline: 19 promoters, 1 detractor out of 20 → NPS=90, health=95
    baseline = {
        "kpis": {
            "own_review_rows": 20,
            "own_positive_review_rows": 19,
            "own_negative_review_rows": 1,
        },
    }
    # Spiked: 14 promoters, 6 detractors out of 20 → NPS=40, health=70
    spiked = {
        "kpis": {
            "own_review_rows": 20,
            "own_positive_review_rows": 14,
            "own_negative_review_rows": 6,
        },
    }
    idx_baseline, _ = compute_health_index(baseline)
    idx_spiked, _ = compute_health_index(spiked)
    assert idx_baseline - idx_spiked > 15, \
        f"Index drop too small: {idx_baseline} → {idx_spiked} (diff {idx_baseline - idx_spiked})"


def test_kpi_cards_value_class_competitive_gap():
    """KPI cards should assign status colors based on competitive_gap_index thresholds (0-100 scale)."""
    # severity-high: index > 60
    # Rate-based: (80/100 + 70/100) / 2 = 0.75 → 75 > 60 → severity-high
    # own_review_rows + competitor_review_rows = 10 + 10 = 20 → meets MIN_GAP_SAMPLE
    analytics = {
        "kpis": {
            "ingested_review_rows": 10,
            "negative_review_rows": 5,
            "translated_count": 10,
            "own_product_count": 1,
            "own_review_rows": 10,
            "competitor_review_rows": 10,
            "own_negative_review_rate": 0.1,
            "own_avg_rating": 3.5,
        },
        "self": {"risk_products": [], "top_negative_clusters": [], "recommendations": []},
        "competitor": {
            "top_positive_themes": [],
            "benchmark_examples": [],
            "negative_opportunities": [],
            "gap_analysis": [
                {"competitor_positive_count": 80, "own_negative_count": 70,
                 "competitor_total": 100, "own_total": 100},
            ],
        },
    }
    result = normalize_deep_report_analytics(analytics)
    gap_card = [c for c in result["kpi_cards"] if c["label"] == "竞品差距分"][0]
    assert gap_card["value_class"] == "severity-high"

    # severity-medium: 30 < index <= 60
    # Rate-based: (40/100 + 30/100) / 2 = 0.35 → 35 → severity-medium
    analytics2 = {
        "kpis": {
            "ingested_review_rows": 10,
            "negative_review_rows": 5,
            "translated_count": 10,
            "own_product_count": 1,
            "own_review_rows": 10,
            "competitor_review_rows": 10,
            "own_negative_review_rate": 0.1,
            "own_avg_rating": 3.5,
        },
        "self": {"risk_products": [], "top_negative_clusters": [], "recommendations": []},
        "competitor": {
            "top_positive_themes": [],
            "benchmark_examples": [],
            "negative_opportunities": [],
            "gap_analysis": [
                {"competitor_positive_count": 40, "own_negative_count": 30,
                 "competitor_total": 100, "own_total": 100},
            ],
        },
    }
    result2 = normalize_deep_report_analytics(analytics2)
    gap_card2 = [c for c in result2["kpi_cards"] if c["label"] == "竞品差距分"][0]
    assert gap_card2["value_class"] == "severity-medium"

    # no class: index <= 30
    # Rate-based: (8/100 + 7/100) / 2 = 0.075 → 8 → no class
    analytics3 = {
        "kpis": {
            "ingested_review_rows": 10,
            "negative_review_rows": 5,
            "translated_count": 10,
            "own_product_count": 1,
            "own_review_rows": 10,
            "competitor_review_rows": 10,
            "own_negative_review_rate": 0.1,
            "own_avg_rating": 3.5,
        },
        "self": {"risk_products": [], "top_negative_clusters": [], "recommendations": []},
        "competitor": {
            "top_positive_themes": [],
            "benchmark_examples": [],
            "negative_opportunities": [],
            "gap_analysis": [
                {"competitor_positive_count": 8, "own_negative_count": 7,
                 "competitor_total": 100, "own_total": 100},
            ],
        },
    }
    result3 = normalize_deep_report_analytics(analytics3)
    gap_card3 = [c for c in result3["kpi_cards"] if c["label"] == "竞品差距分"][0]
    assert gap_card3["value_class"] == ""


def test_competitive_gap_kpi_uses_overall_label_and_tooltip():
    analytics = {
        "kpis": {
            "ingested_review_rows": 10,
            "negative_review_rows": 5,
            "translated_count": 10,
            "own_product_count": 1,
            "own_review_rows": 10,
            "competitor_review_rows": 10,
        },
        "self": {"risk_products": [], "top_negative_clusters": [], "recommendations": []},
        "competitor": {
            "top_positive_themes": [],
            "benchmark_examples": [],
            "negative_opportunities": [],
            "gap_analysis": [
                {"competitor_positive_count": 40, "own_negative_count": 20,
                 "competitor_total": 100, "own_total": 100},
            ],
        },
    }

    result = normalize_deep_report_analytics(analytics)
    labels = [card["label"] for card in result["kpi_cards"]]
    gap_card = next(card for card in result["kpi_cards"] if card["label"] == "竞品差距分")

    assert "竞品差距指数" not in labels
    assert "跨维度平均" in gap_card["tooltip"]


def test_baseline_mode_suppresses_deltas():
    """In baseline mode, KPI deltas should show '—' and baseline_note should exist."""
    from qbu_crawler.server.report_common import normalize_deep_report_analytics

    analytics = {
        "mode": "baseline",
        "baseline_sample_days": 1,
        "kpis": {
            "ingested_review_rows": 50,
            "negative_review_rows": 5,
            "own_negative_review_rows": 3,
            "translated_count": 50,
            "negative_review_rows_delta": 5,
            "negative_review_rows_delta_display": "+5",
            "own_negative_review_rows_delta": 3,
            "own_negative_review_rows_delta_display": "+3",
            "ingested_review_rows_delta": 10,
            "ingested_review_rows_delta_display": "+10",
        },
        "self": {"risk_products": [], "top_negative_clusters": [], "recommendations": []},
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
    }
    normalized = normalize_deep_report_analytics(analytics)
    assert normalized.get("baseline_note"), "Baseline mode should include explanatory note"
    # All delta displays should be suppressed
    assert normalized["kpis"]["negative_review_rows_delta_display"] == "—"
    assert normalized["kpis"]["own_negative_review_rows_delta_display"] == "—"
    assert normalized["kpis"]["ingested_review_rows_delta_display"] == "—"
    # Delta values should be 0
    assert normalized["kpis"]["negative_review_rows_delta"] == 0
    assert normalized["kpis"]["own_negative_review_rows_delta"] == 0


def test_evidence_refs_use_primary_label():
    """Image evidence should be linked to its primary (first) label, not all labels."""
    from qbu_crawler.server.report_common import normalize_deep_report_analytics

    analytics = {
        "kpis": {"ingested_review_rows": 5},
        "self": {
            "risk_products": [
                {"product_name": "P1", "product_sku": "S1",
                 "negative_review_rows": 3, "risk_score": 10,
                 "top_labels": [{"label_code": "quality_stability", "count": 3}]},
            ],
            "top_negative_clusters": [
                {"label_code": "quality_stability", "review_count": 3,
                 "severity": "high", "affected_product_count": 1,
                 "example_reviews": [], "image_review_count": 1},
                {"label_code": "material_finish", "review_count": 1,
                 "severity": "medium", "affected_product_count": 1,
                 "example_reviews": [], "image_review_count": 0},
            ],
            "recommendations": [],
        },
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
        "appendix": {
            "image_reviews": [
                {"product_name": "P1", "product_sku": "S1", "ownership": "own",
                 "rating": 1, "headline": "Motor burned out", "body": "broke and rusted",
                 "images": ["http://example.com/img1.jpg"],
                 "label_codes": ["quality_stability", "material_finish"]},
            ],
        },
    }
    normalized = normalize_deep_report_analytics(analytics)

    # quality_stability (primary/first label) should have the evidence ref
    qs_cluster = [c for c in normalized["self"]["top_negative_clusters"]
                  if c.get("label_code") == "quality_stability"][0]
    assert qs_cluster["evidence_refs"], "Primary label cluster should have evidence"

    # material_finish (secondary label) should NOT have the same evidence
    mf_cluster = [c for c in normalized["self"]["top_negative_clusters"]
                  if c.get("label_code") == "material_finish"][0]
    assert not mf_cluster["evidence_refs"], \
        "Secondary label cluster should NOT have evidence from primary-only linking"


# ---------------------------------------------------------------------------
# Task 6: Coverage rate KPI card and metric caliber annotations
# ---------------------------------------------------------------------------

def test_normalize_adds_coverage_rate_kpi():
    """KPI cards should include a coverage rate card."""
    from qbu_crawler.server.report_common import normalize_deep_report_analytics

    analytics = {
        "kpis": {
            "ingested_review_rows": 148,
            "site_reported_review_total_current": 223,
            "translated_count": 148,
        },
    }
    result = normalize_deep_report_analytics(analytics)
    card_labels = [c["label"] for c in result["kpi_cards"]]
    assert "样本覆盖率" in card_labels
    coverage_card = next(c for c in result["kpi_cards"] if c["label"] == "样本覆盖率")
    assert coverage_card["value"] == "66%"


def test_coverage_rate_missing_site_total():
    """When site_reported_review_total_current is absent, show '—'."""
    from qbu_crawler.server.report_common import normalize_deep_report_analytics

    analytics = {
        "kpis": {
            "ingested_review_rows": 100,
            "translated_count": 100,
        },
    }
    result = normalize_deep_report_analytics(analytics)
    coverage_card = next((c for c in result["kpi_cards"] if c["label"] == "样本覆盖率"), None)
    assert coverage_card is not None
    assert coverage_card["value"] == "—"


def test_risk_score_tooltip_mentions_threshold():
    """Risk score tooltip should specify the rating threshold used."""
    from qbu_crawler.server.report_common import METRIC_TOOLTIPS
    tooltip = METRIC_TOOLTIPS.get("风险分", "")
    assert "≤" in tooltip or "星" in tooltip, f"Risk tooltip missing threshold info: {tooltip}"


def test_alert_level_green_for_baseline():
    """Baseline mode with healthy product should return green and mention 基线."""
    from qbu_crawler.server.report_common import _compute_alert_level

    normalized = {
        "mode": "baseline",
        "kpis": {"own_review_rows": 100, "own_negative_review_rows_delta": 0, "health_index": 80.0},
        "self": {"top_negative_clusters": []},
    }
    level, text = _compute_alert_level(normalized)
    assert level == "green"
    assert "基线" in text


# ---------------------------------------------------------------------------
# Task 4: trend_display populated from _trend_series
# ---------------------------------------------------------------------------


def test_risk_product_trend_display_populated():
    """trend_display should show direction arrow when _trend_series has data."""
    from qbu_crawler.server.report_common import normalize_deep_report_analytics
    analytics = {
        "mode": "baseline",
        "kpis": {"ingested_review_rows": 10},
        "self": {
            "risk_products": [
                {"product_name": "P", "product_sku": "SKU1", "risk_score": 80,
                 "top_labels": [], "negative_rate": 0.4, "rating_avg": 3.5},
            ],
            "top_negative_clusters": [],
            "recommendations": [],
        },
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
        "appendix": {"image_reviews": []},
        "report_copy": {"improvement_priorities": []},
        "_trend_series": [
            {
                "product_sku": "SKU1",
                "product_name": "P",
                "series": [
                    {"date": "2026-03-01", "rating": 3.0, "review_count": 80, "price": 100, "stock_status": "in_stock"},
                    {"date": "2026-04-01", "rating": 3.5, "review_count": 100, "price": 100, "stock_status": "in_stock"},
                ],
            }
        ],
    }
    result = normalize_deep_report_analytics(analytics)
    product = result["self"]["risk_products"][0]
    assert product["trend_display"] != "—"
    assert product["trend_display"] != ""
    assert "↑" in product["trend_display"] or "↓" in product["trend_display"] or "→" in product["trend_display"]


def test_issue_card_recency_display():
    """issue_card should show 90-day recency based on logical_date."""
    analytics = {
        "logical_date": "2026-04-08",
        "mode": "baseline",
        "kpis": {"ingested_review_rows": 5},
        "self": {
            "risk_products": [],
            "top_negative_clusters": [{
                "label_code": "quality_stability",
                "review_count": 3,
                "severity": "high",
                "affected_product_count": 1,
                "example_reviews": [],
                "review_dates": ["2025-01-01", "2026-02-15", "2026-03-20"],
            }],
            "recommendations": [],
        },
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
        "appendix": {"image_reviews": []},
        "report_copy": {"improvement_priorities": []},
    }
    result = normalize_deep_report_analytics(analytics)
    card = result["self"]["issue_cards"][0]
    assert "recency_display" in card
    # 2026-02-15 and 2026-03-20 are within 90 days of 2026-04-08
    assert "2" in card["recency_display"]


def test_issue_card_translation_warning():
    """Issue card should show translation warning when coverage < 50%."""
    from qbu_crawler.server.report_common import normalize_deep_report_analytics
    analytics = {
        "mode": "baseline",
        "kpis": {"ingested_review_rows": 5},
        "self": {
            "risk_products": [],
            "top_negative_clusters": [{
                "label_code": "quality_stability",
                "review_count": 4,
                "severity": "high",
                "affected_product_count": 1,
                "example_reviews": [],
                "translated_rate": 0.25,
            }],
            "recommendations": [],
        },
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
        "appendix": {"image_reviews": []},
        "report_copy": {"improvement_priorities": []},
    }
    result = normalize_deep_report_analytics(analytics)
    card = result["self"]["issue_cards"][0]
    assert card["translation_warning"] is True
    assert card["translated_rate_display"] == "25%"


def test_kpi_cards_include_positive_rate():
    """KPI cards should include a positive rate card."""
    analytics = {
        "mode": "baseline",
        "kpis": {
            "ingested_review_rows": 100,
            "own_review_rows": 80,
            "own_positive_review_rows": 50,
        },
        "self": {"risk_products": [], "top_negative_clusters": [], "recommendations": []},
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
        "appendix": {"image_reviews": []},
        "report_copy": {"improvement_priorities": []},
    }
    result = normalize_deep_report_analytics(analytics)
    labels = [c["label"] for c in result["kpi_cards"]]
    assert "好评率" in labels
    pos_card = next(c for c in result["kpi_cards"] if c["label"] == "好评率")
    assert pos_card["value"] == "62.5%"


# ---------------------------------------------------------------------------
# Tests for competitive_gap_index sample protection (Fix-6)
# ---------------------------------------------------------------------------


def test_normalize_sets_gap_index_none_when_low_sample():
    """When total reviews < 20, competitive_gap_index should be None."""
    analytics = {
        "kpis": {
            "ingested_review_rows": 5,
            "negative_review_rows": 1,
            "translated_count": 5,
            "own_product_count": 1,
            "own_avg_rating": 4.5,
            "own_review_rows": 3,
            "competitor_review_rows": 2,
        },
        "self": {"risk_products": [], "top_negative_clusters": [], "recommendations": []},
        "competitor": {
            "top_positive_themes": [],
            "benchmark_examples": [],
            "negative_opportunities": [],
            "gap_analysis": [
                {"competitor_positive_count": 2, "own_negative_count": 1,
                 "competitor_total": 2, "own_total": 3},
            ],
        },
    }
    result = normalize_deep_report_analytics(analytics)
    assert result["kpis"]["competitive_gap_index"] is None


def test_normalize_computes_gap_index_when_sufficient_sample():
    """When total reviews >= 20, competitive_gap_index should be computed normally."""
    analytics = {
        "kpis": {
            "ingested_review_rows": 40,
            "negative_review_rows": 5,
            "translated_count": 40,
            "own_product_count": 2,
            "own_avg_rating": 4.0,
            "own_review_rows": 20,
            "competitor_review_rows": 20,
        },
        "self": {"risk_products": [], "top_negative_clusters": [], "recommendations": []},
        "competitor": {
            "top_positive_themes": [],
            "benchmark_examples": [],
            "negative_opportunities": [],
            "gap_analysis": [
                {"competitor_positive_count": 10, "own_negative_count": 5,
                 "competitor_total": 20, "own_total": 20},
            ],
        },
    }
    result = normalize_deep_report_analytics(analytics)
    assert result["kpis"]["competitive_gap_index"] is not None
    assert isinstance(result["kpis"]["competitive_gap_index"], (int, float))


# ---------------------------------------------------------------------------
# Tests for compute_health_index Bayesian shrinkage (Fix-3)
# ---------------------------------------------------------------------------


def test_compute_health_index_returns_tuple():
    """compute_health_index should return (health, confidence) tuple."""
    analytics = {
        "kpis": {
            "own_review_rows": 10,
            "own_positive_review_rows": 10,
            "own_negative_review_rows": 0,
        },
    }
    result = report_common.compute_health_index(analytics)
    assert isinstance(result, tuple)
    assert len(result) == 2
    health, confidence = result
    assert isinstance(health, float)
    assert confidence in ("high", "medium", "low", "no_data")


def test_compute_health_index_shrinks_small_sample():
    """1 perfect review: raw=100, but should shrink toward 50."""
    analytics = {
        "kpis": {
            "own_review_rows": 1,
            "own_positive_review_rows": 1,
            "own_negative_review_rows": 0,
        },
    }
    health, confidence = report_common.compute_health_index(analytics)
    # weight = 1/30, health = 1/30 * 100 + 29/30 * 50 = 51.67
    assert 51.0 <= health <= 52.5
    assert confidence == "low"


def test_compute_health_index_medium_confidence():
    """10 reviews: medium confidence, partial shrinkage."""
    analytics = {
        "kpis": {
            "own_review_rows": 10,
            "own_positive_review_rows": 10,
            "own_negative_review_rows": 0,
        },
    }
    health, confidence = report_common.compute_health_index(analytics)
    # weight = 10/30, health = 10/30 * 100 + 20/30 * 50 = 66.67
    assert 66.0 <= health <= 67.5
    assert confidence == "medium"


def test_compute_health_index_high_confidence():
    """30+ reviews: no shrinkage, high confidence."""
    analytics = {
        "kpis": {
            "own_review_rows": 100,
            "own_positive_review_rows": 90,
            "own_negative_review_rows": 5,
        },
    }
    health, confidence = report_common.compute_health_index(analytics)
    # NPS = (90-5)/100 * 100 = 85, health = (85+100)/2 = 92.5
    assert health == 92.5
    assert confidence == "high"


def test_compute_health_index_no_data():
    analytics = {"kpis": {"own_review_rows": 0}}
    health, confidence = report_common.compute_health_index(analytics)
    assert health == 50.0
    assert confidence == "no_data"


def test_normalize_injects_health_confidence():
    """normalize_deep_report_analytics should set health_confidence alongside health_index."""
    analytics = {
        "kpis": {
            "ingested_review_rows": 2,
            "negative_review_rows": 1,
            "translated_count": 2,
            "own_product_count": 1,
            "own_avg_rating": 3.0,
            "own_review_rows": 2,
            "competitor_review_rows": 0,
        },
        "self": {"risk_products": [], "top_negative_clusters": [], "recommendations": []},
        "competitor": {"top_positive_themes": [], "benchmark_examples": [], "negative_opportunities": []},
    }
    result = normalize_deep_report_analytics(analytics)
    assert "health_confidence" in result["kpis"]
    assert result["kpis"]["health_confidence"] in ("low", "medium", "high", "no_data")
    assert isinstance(result["kpis"]["health_index"], float)


def test_bayesian_bucket_health_empty_returns_none():
    from qbu_crawler.server.report_common import _bayesian_bucket_health
    assert _bayesian_bucket_health(own_total=0, own_neg=0, own_pos=0) is None


def test_bayesian_bucket_health_large_sample_is_raw_nps():
    from qbu_crawler.server.report_common import _bayesian_bucket_health
    # 100 reviews, 90 promoters, 5 detractors → NPS = (90-5)/100*100 = 85
    # raw_health = (85+100)/2 = 92.5, sample >= 30 so no shrinkage
    assert _bayesian_bucket_health(own_total=100, own_neg=5, own_pos=90) == 92.5


def test_bayesian_bucket_health_small_sample_shrinks_toward_prior():
    from qbu_crawler.server.report_common import _bayesian_bucket_health
    # 10 reviews, 10 detractors, 0 promoters → NPS = -100, raw = 0
    # weight = 10/30, shrunk = 10/30*0 + 20/30*50 = 33.33
    result = _bayesian_bucket_health(own_total=10, own_neg=10, own_pos=0)
    assert 33.0 <= result <= 34.0


def test_bayesian_bucket_health_single_positive_review_not_perfect():
    from qbu_crawler.server.report_common import _bayesian_bucket_health
    # Should not be 100 — shrinkage must pull toward 50
    result = _bayesian_bucket_health(own_total=1, own_neg=0, own_pos=1)
    assert result is not None
    assert result < 70, f"1 promoter should not yield health > 70, got {result}"


def test_health_index_tooltip_reflects_bayesian_formula():
    from qbu_crawler.server.report_common import METRIC_TOOLTIPS
    tooltip = METRIC_TOOLTIPS["健康指数"]
    # Old weighted formula must be gone
    assert "20%站点评分" not in tooltip
    assert "25%样本评分" not in tooltip
    # New Bayesian-NPS description must be present
    assert "NPS" in tooltip or "贝叶斯" in tooltip
    assert "50" in tooltip  # prior mentioned
    assert "30" in tooltip  # min-reliable sample mentioned


def test_fallback_executive_bullets_bootstrap_uses_baseline_wording():
    """spec §10.3：deterministic fallback 在 bootstrap 下禁用「新增评论」
    措辞，改用「建立监控基线」话术。"""
    from qbu_crawler.server.report_common import _fallback_executive_bullets
    normalized = {
        "report_semantics": "bootstrap",
        "is_bootstrap": True,
        "kpis": {"product_count": 5, "ingested_review_rows": 593},
        "self": {"risk_products": []},
        "competitor": {"top_positive_themes": [], "negative_opportunities": []},
        "change_digest": {"summary": {}},
    }
    bullets = _fallback_executive_bullets(normalized)
    merged = "\n".join(bullets)
    assert "新增评论" not in merged, "bootstrap fallback 仍在写「新增评论」"
    assert "基线" in merged or "监控起点" in merged


def test_fallback_executive_bullets_incremental_cites_change_digest_fields():
    from qbu_crawler.server.report_common import _fallback_executive_bullets
    normalized = {
        "report_semantics": "incremental",
        "is_bootstrap": False,
        "kpis": {"product_count": 5, "ingested_review_rows": 100},
        "self": {"risk_products": []},
        "competitor": {"top_positive_themes": [], "negative_opportunities": []},
        "change_digest": {"summary": {
            "fresh_review_count": 3, "historical_backfill_count": 97,
        }},
    }
    bullets = _fallback_executive_bullets(normalized)
    merged = "\n".join(bullets)
    assert "基线样本评论" in merged
    assert "近30天样本" in merged or "近 30 天样本" in merged


def test_fallback_hero_headline_bootstrap_falls_back_to_baseline_when_no_risk():
    from qbu_crawler.server.report_common import _fallback_hero_headline
    normalized = {
        "report_semantics": "bootstrap",
        "is_bootstrap": True,
        "kpis": {"ingested_review_rows": 593},
        "self": {"risk_products": [], "top_negative_clusters": []},
        "competitor": {"top_positive_themes": []},
    }
    headline = _fallback_hero_headline(normalized)
    assert "基线" in headline or "监控起点" in headline
    assert "今日新增" not in headline


def test_normalize_kpis_renames_ambiguous_negative_review_rate():
    """修 8: 顶层 kpis 不能同时暴露混合 rate（含竞品）和 own rate，
    重命名为 all_sample_negative_rate 让模板/LLM 不会误消费。"""
    from qbu_crawler.server.report_common import normalize_deep_report_analytics

    raw = {
        "kpis": {
            "ingested_review_rows": 100,
            "negative_review_rows": 12,        # mixed (含竞品)
            "own_review_rows": 80,
            "own_negative_review_rows": 3,     # own only
            "own_negative_review_rate": 0.0375,
            "translated_count": 50,
            "own_product_count": 5,
            "competitor_product_count": 3,
        },
        "self": {"risk_products": [], "top_negative_clusters": [],
                 "top_positive_clusters": [], "recommendations": []},
        "competitor": {"top_positive_themes": [], "benchmark_examples": [],
                       "negative_opportunities": [], "gap_analysis": []},
        "appendix": {"image_reviews": [], "coverage": {}},
        "report_semantics": "incremental",
    }
    out = normalize_deep_report_analytics(raw)
    kpis = out["kpis"]

    # ambiguous 旧键必须不再出现
    assert "negative_review_rate" not in kpis, (
        "顶层 kpis 的 ambiguous 'negative_review_rate' 必须重命名为 all_sample_negative_rate"
    )
    assert "negative_review_rate_display" not in kpis

    # 新键替代
    assert "all_sample_negative_rate" in kpis
    assert kpis["all_sample_negative_rate"] == 0.12  # 12/100
    assert kpis["all_sample_negative_rate_display"] == "12.0%"

    # own rate 不变
    assert kpis["own_negative_review_rate"] == 0.0375
    assert kpis["own_negative_review_rate_display"] == "3.8%"
