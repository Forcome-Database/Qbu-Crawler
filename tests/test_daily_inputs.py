"""Tests for daily input CSV parsing."""

from pathlib import Path

import pytest


def _write_csv(path: Path, lines: list[str]) -> str:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def test_load_daily_inputs_empty_files(tmp_path):
    from qbu_crawler.server.daily_inputs import load_daily_inputs

    source_csv = _write_csv(tmp_path / "source.csv", ["url,ownership"])
    detail_csv = _write_csv(tmp_path / "detail.csv", ["url,ownership"])

    bundle = load_daily_inputs(source_csv, detail_csv)

    assert bundle.collect_requests == []
    assert bundle.scrape_requests == []
    assert bundle.summary["collect_count"] == 0
    assert bundle.summary["scrape_group_count"] == 0


def test_load_daily_inputs_rejects_invalid_ownership(tmp_path):
    from qbu_crawler.server.daily_inputs import DailyInputValidationError, load_daily_inputs

    source_csv = _write_csv(
        tmp_path / "source.csv",
        [
            "url,ownership",
            "https://www.basspro.com/shop/en/camping,hacker",
        ],
    )
    detail_csv = _write_csv(tmp_path / "detail.csv", ["url,ownership"])

    with pytest.raises(DailyInputValidationError) as exc:
        load_daily_inputs(source_csv, detail_csv)

    assert "ownership" in str(exc.value)
    assert "hacker" in str(exc.value)


def test_load_daily_inputs_groups_mixed_sites(tmp_path):
    from qbu_crawler.server.daily_inputs import load_daily_inputs

    source_csv = _write_csv(tmp_path / "source.csv", ["url,ownership"])
    detail_csv = _write_csv(
        tmp_path / "detail.csv",
        [
            "url,ownership",
            "https://www.basspro.com/shop/en/example-product-1,own",
            "https://www.meatyourmaker.com/en-US/p/example-product-2,own",
        ],
    )

    bundle = load_daily_inputs(source_csv, detail_csv)
    groups = {(group.site, group.ownership): group.urls for group in bundle.scrape_requests}

    assert ("basspro", "own") in groups
    assert ("meatyourmaker", "own") in groups
    assert len(groups[("basspro", "own")]) == 1
    assert len(groups[("meatyourmaker", "own")]) == 1


def test_load_daily_inputs_groups_by_ownership_and_task_type(tmp_path):
    from qbu_crawler.server.daily_inputs import load_daily_inputs

    source_csv = _write_csv(
        tmp_path / "source.csv",
        [
            "url,ownership,max_pages",
            "https://www.basspro.com/shop/en/camping,own,2",
            "https://www.basspro.com/shop/en/fishing,competitor,0",
        ],
    )
    detail_csv = _write_csv(
        tmp_path / "detail.csv",
        [
            "url,ownership",
            "https://www.basspro.com/shop/en/example-product-1,own",
            "https://www.basspro.com/shop/en/example-product-2,own",
            "https://www.basspro.com/shop/en/example-product-3,competitor",
        ],
    )

    bundle = load_daily_inputs(source_csv, detail_csv)

    assert len(bundle.collect_requests) == 2
    assert bundle.collect_requests[0].max_pages == 2
    assert bundle.collect_requests[1].ownership == "competitor"

    groups = {(group.site, group.ownership): group.urls for group in bundle.scrape_requests}
    assert len(groups[("basspro", "own")]) == 2
    assert len(groups[("basspro", "competitor")]) == 1
    assert bundle.summary["collect_count"] == 2
    assert bundle.summary["scrape_group_count"] == 2
