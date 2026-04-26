from qbu_crawler.server.scrape_quality import summarize_scrape_quality


def test_zero_scrape_skus_detected():
    """有产品站点报告 N>0 但实际入库 0 时，应在 zero_scrape_skus 列出。"""
    products = [
        {"sku": "A", "review_count": 91, "ingested_count": 0},
        {"sku": "B", "review_count": 100, "ingested_count": 95},
        {"sku": "C", "review_count": 0, "ingested_count": 0},
    ]
    quality = summarize_scrape_quality(products)
    assert "A" in quality["zero_scrape_skus"]
    assert "B" not in quality["zero_scrape_skus"]
    assert "C" not in quality["zero_scrape_skus"]  # 站点本身就 0，不算异常


def test_completeness_ratio():
    products = [
        {"sku": "A", "review_count": 100, "ingested_count": 50},
        {"sku": "B", "review_count": 100, "ingested_count": 80},
    ]
    quality = summarize_scrape_quality(products)
    assert quality["scrape_completeness_ratio"] == 0.65  # (50+80)/(100+100)


def test_low_coverage_skus():
    products = [
        {"sku": "A", "review_count": 100, "ingested_count": 50},
        {"sku": "B", "review_count": 100, "ingested_count": 95},
    ]
    quality = summarize_scrape_quality(products, low_coverage_threshold=0.6)
    assert "A" in quality["low_coverage_skus"]
    assert "B" not in quality["low_coverage_skus"]


# Backward-compat regression: existing keys must still be present.
def test_existing_keys_still_present():
    products = [
        {"sku": "A", "review_count": 100, "ingested_count": 50, "rating": 4.5, "stock_status": "in_stock"},
        {"sku": "B"},  # missing fields
    ]
    quality = summarize_scrape_quality(products)
    for key in [
        "total", "missing_rating", "missing_stock", "missing_review_count",
        "missing_rating_ratio", "missing_stock_ratio", "missing_review_count_ratio",
    ]:
        assert key in quality, f"{key} must be preserved for backward compat"


def test_completeness_ratio_when_site_total_zero():
    """When site_total = 0 (no products report any reviews), completeness = 1.0 (vacuously satisfied)."""
    products = [
        {"sku": "A", "review_count": 0, "ingested_count": 0},
        {"sku": "B", "review_count": 0, "ingested_count": 0},
    ]
    quality = summarize_scrape_quality(products)
    assert quality["scrape_completeness_ratio"] == 1.0


def test_missing_ingested_count_defaults_to_zero():
    """Producers that don't yet supply ingested_count must not crash; missing key → 0."""
    products = [
        {"sku": "A", "review_count": 50},  # no ingested_count
    ]
    quality = summarize_scrape_quality(products)
    # site_total=50 with ingested_total=0 → A is a zero_scrape SKU
    assert quality["zero_scrape_skus"] == ["A"]
    assert quality["scrape_completeness_ratio"] == 0.0
