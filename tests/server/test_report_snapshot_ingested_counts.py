from qbu_crawler.server.report_snapshot import _attach_ingested_counts
from qbu_crawler.server.scrape_quality import summarize_scrape_quality


def test_attach_ingested_counts_prevents_false_zero_scrape():
    products = [
        {"sku": "A", "review_count": 10},
        {"sku": "B", "review_count": 5},
    ]
    reviews = [
        {"product_sku": "A"},
        {"product_sku": "A"},
        {"product_sku": "B"},
    ]

    _attach_ingested_counts(products, reviews)

    assert products[0]["ingested_count"] == 2
    assert products[1]["ingested_count"] == 1

    quality = summarize_scrape_quality(products, low_coverage_threshold=0.1)
    assert quality["zero_scrape_skus"] == []
    assert quality["scrape_completeness_ratio"] == 0.2
