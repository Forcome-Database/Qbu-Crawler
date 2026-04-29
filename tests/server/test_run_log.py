import json
import sqlite3

from qbu_crawler.server.run_log import (
    append_run_log,
    build_quality_log_lines,
    get_run_log_path,
)


def test_run_log_path_stays_under_data_dir(tmp_path, monkeypatch):
    from qbu_crawler import config

    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))

    path = get_run_log_path(run_id=7, logical_date="2026-04-28")

    assert path.parent == tmp_path
    assert path.name == "log-run-7-20260428.log"


def test_append_run_log_writes_clear_process_lines(tmp_path, monkeypatch):
    from qbu_crawler import config

    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))

    path = append_run_log(
        run_id=1,
        logical_date="2026-04-28",
        event="snapshot_frozen",
        lines=["products=8", "reviews=594"],
        now="2026-04-28T16:31:37+08:00",
    )

    text = path.read_text(encoding="utf-8")
    assert "[2026-04-28T16:31:37+08:00] snapshot_frozen" in text
    assert "- products=8" in text
    assert "- reviews=594" in text


def test_quality_log_lines_include_low_coverage_task_meta():
    snapshot = {
        "products": [
            {
                "sku": "1193465",
                "name": ".5 HP Dual Grind Grinder (#8)",
                "site": "meatyourmaker",
                "review_count": 92,
                "ratings_only_count": 59,
                "ingested_count": 33,
            }
        ]
    }
    quality = {
        "scrape_completeness_ratio": 0.675,
        "low_coverage_skus": ["1193465"],
        "outbox_deadletter_count": 1,
        "estimated_date_ratio": 0.4393,
    }
    task_rows = [{
        "result": {
            "product_summaries": [{
                "sku": "1193465",
                "url": "https://example.test/p",
                "site_review_count": 92,
                "extracted_review_count": 33,
                "saved_review_count": 33,
                "scrape_meta": {
                    "review_extraction": {
                        "stop_reason": "no_next",
                        "pages_seen": 3,
                    }
                },
            }]
        }
    }]

    lines = build_quality_log_lines(snapshot, quality, task_rows)
    text = "\n".join(lines)

    assert "scrape_completeness_ratio=67.5%" in text
    assert "sku=1193465" in text
    assert "site_total=92" in text
    assert "ratings_only=59" in text
    assert "text_total=33" in text
    assert "scrape_completeness=100.0%" in text
    assert "stop_reason=no_next" in text
    assert "outbox_deadletter_count=1" in text
    assert "estimated_date_ratio=43.9%" in text


def test_quality_log_lines_include_failed_url_details():
    snapshot = {"products": [{"url": "u1", "sku": "S1"}]}
    quality = {
        "scrape_completeness_ratio": 0.875,
        "expected_url_count": 8,
        "saved_product_count": 7,
        "failed_url_count": 1,
        "failed_urls": [{
            "url": "https://www.basspro.com/p/cabelas-heavy-duty-20-lb-meat-mixer",
            "site": "basspro",
            "stage": "product_identity",
            "error_type": "KeyError",
            "error_message": "'searchId'",
        }],
    }

    lines = build_quality_log_lines(snapshot, quality, [])
    text = "\n".join(lines)

    assert "expected_urls=8" in text
    assert "saved_products=7" in text
    assert "failed_url_count=1" in text
    assert "failed_url[1].url=https://www.basspro.com/p/cabelas-heavy-duty-20-lb-meat-mixer" in text
    assert "failed_url[1].stage=product_identity" in text
    assert "failed_url[1].error=KeyError: 'searchId'" in text
