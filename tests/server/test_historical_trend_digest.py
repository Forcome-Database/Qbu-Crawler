import json

from qbu_crawler.server import report_analytics


def _review(
    *,
    day,
    ownership="own",
    rating=5,
    sku="SKU-1",
    product_name="Product 1",
    labels=None,
    body="easy to use",
):
    return {
        "id": f"{sku}-{day}-{rating}-{ownership}",
        "product_name": product_name,
        "product_sku": sku,
        "product_url": f"https://example.com/{sku}",
        "site": "basspro",
        "ownership": ownership,
        "rating": rating,
        "date_published": day,
        "date_published_parsed": day,
        "scraped_at": f"{day} 10:00:00",
        "headline": body,
        "body": body,
        "analysis_labels": json.dumps(labels or []),
    }


def _trend_history():
    reviews = []
    for day in ["2026-04-01", "2026-04-05", "2026-04-10"]:
        reviews.append(_review(day=day, ownership="own", rating=5, body="easy to use"))
        reviews.append(_review(day=day, ownership="competitor", rating=4, body="solid build"))
    for day in ["2026-04-20", "2026-04-25", "2026-04-29"]:
        reviews.append(_review(
            day=day,
            ownership="own",
            rating=2,
            sku="SKU-1",
            body="broke and noisy",
            labels=[{"code": "quality_stability", "polarity": "negative"}],
        ))
        reviews.append(_review(
            day=day,
            ownership="competitor",
            rating=5,
            sku="SKU-C",
            product_name="Competitor 1",
            body="solid build",
            labels=[{"code": "solid_build", "polarity": "positive"}],
        ))
    return {
        "products": [
            {"url": "https://example.com/SKU-1", "name": "Product 1", "sku": "SKU-1", "site": "basspro", "ownership": "own"},
            {"url": "https://example.com/SKU-C", "name": "Competitor 1", "sku": "SKU-C", "site": "basspro", "ownership": "competitor"},
        ],
        "reviews": reviews,
        "product_series": [
            {
                "product_name": "Product 1",
                "product_sku": "SKU-1",
                "product_url": "https://example.com/SKU-1",
                "ownership": "own",
                "series": [
                    {"date": "2026-04-01 09:00:00", "rating": 4.5, "review_count": 10},
                    {"date": "2026-04-29 09:00:00", "rating": 4.0, "review_count": 16},
                ],
            }
        ],
        "until": "2026-04-30T00:00:00+08:00",
    }


def _snapshot():
    return {
        "run_id": 1,
        "logical_date": "2026-04-29",
        "data_until": "2026-04-30T00:00:00+08:00",
        "snapshot_hash": "hash",
        "products": [],
        "reviews": [],
        "products_count": 0,
        "reviews_count": 0,
        "translated_count": 0,
        "untranslated_count": 0,
    }


def test_trend_digest_keeps_legacy_and_adds_workspace():
    analytics = report_analytics.build_report_analytics(_snapshot(), trend_history=_trend_history())
    digest = analytics["trend_digest"]

    assert "primary_chart" in digest
    assert "drill_downs" in digest
    assert digest["workspace"]["views"] == ["week", "month", "year"]
    assert digest["workspace"]["dimensions"] == ["reputation", "issues", "products", "competition"]


def test_reputation_trend_uses_historical_reviews_and_explicit_comparison():
    workspace = report_analytics.build_report_analytics(
        _snapshot(),
        trend_history=_trend_history(),
    )["trend_digest"]["workspace"]
    panel = workspace["data"]["month"]["reputation"]

    assert panel["title"] == "近30天 / 口碑趋势"
    assert [item["label"] for item in panel["kpis"]["items"]] == ["自有平均评分", "自有差评率", "与竞品评分差"]
    assert len(panel["kpis"]["items"]) <= 3
    assert [item["name"] for item in panel["primary_chart"]["series"]] == ["自有平均评分", "竞品平均评分"]
    assert panel["comparison"]["label"] == "较前30天"
    assert "上期" not in json.dumps(panel, ensure_ascii=False)


def test_year_trend_labels_end_at_logical_month_not_future_data_until_month():
    snapshot = {
        **_snapshot(),
        "logical_date": "2026-04-30",
        "data_until": "2026-05-01T00:00:00+08:00",
    }
    history = {
        **_trend_history(),
        "until": "2026-05-01T00:00:00+08:00",
    }
    workspace = report_analytics.build_report_analytics(
        snapshot,
        trend_history=history,
    )["trend_digest"]["workspace"]
    labels = workspace["data"]["year"]["reputation"]["primary_chart"]["labels"]

    assert labels[-1] == "2026-04"
    assert "2026-05" not in labels


def test_issue_trend_uses_own_negative_labels_only():
    panel = report_analytics.build_report_analytics(
        _snapshot(),
        trend_history=_trend_history(),
    )["trend_digest"]["workspace"]["data"]["month"]["issues"]

    assert panel["primary_chart"]["title"] == "Top 3 问题评论占比趋势"
    assert [item["label"] for item in panel["kpis"]["items"]] == ["问题评论占比", "Top 1 问题", "影响产品数"]
    assert panel["table"]["columns"] == ["问题", "当前评论数", "占比", "对比变化", "影响 SKU"]
    assert panel["table"]["rows"][0]["问题"] == "质量稳定性"


def test_product_trend_combines_snapshots_and_review_history():
    panel = report_analytics.build_report_analytics(
        _snapshot(),
        trend_history=_trend_history(),
    )["trend_digest"]["workspace"]["data"]["month"]["products"]

    assert [item["label"] for item in panel["kpis"]["items"]] == ["评分下降产品数", "差评率上升产品数", "评论增长但评分下降产品数"]
    assert panel["table"]["columns"] == ["产品", "当前评分", "评分变化", "当前差评率", "差评率变化", "评论增长数"]
    assert "快照" not in json.dumps(panel, ensure_ascii=False)
    assert panel["table"]["rows"][0]["产品"] == "Product 1"


def test_competition_trend_uses_deterministic_matching():
    panel = report_analytics.build_report_analytics(
        _snapshot(),
        trend_history=_trend_history(),
    )["trend_digest"]["workspace"]["data"]["month"]["competition"]

    assert panel["primary_chart"]["title"] == "评分差趋势"
    assert [item["label"] for item in panel["kpis"]["items"]] == ["当前评分差", "差评率差", "竞品优势主题 Top 1"]
    assert panel["table"]["columns"] == ["竞品优势主题", "竞品好评数", "自有相关问题", "启示"]
    assert panel["table"]["rows"][0]["竞品优势主题"] == "做工与质量"
