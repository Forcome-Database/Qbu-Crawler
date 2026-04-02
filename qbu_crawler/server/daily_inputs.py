"""Deterministic parsing for daily workflow CSV inputs."""

from __future__ import annotations

import csv
from dataclasses import dataclass

from qbu_crawler.scrapers import get_site_key


_OWNERSHIP_VALUES = {"own", "competitor"}
_REQUIRED_HEADERS = ("url", "ownership")


class DailyInputValidationError(ValueError):
    """Raised when daily workflow CSV files contain invalid rows."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


@dataclass(frozen=True)
class CollectRequest:
    category_url: str
    site: str
    ownership: str
    max_pages: int = 0
    review_limit: int = 0


@dataclass(frozen=True)
class ScrapeRequest:
    site: str
    ownership: str
    urls: list[str]
    review_limit: int = 0


@dataclass(frozen=True)
class DailyInputsBundle:
    collect_requests: list[CollectRequest]
    scrape_requests: list[ScrapeRequest]
    summary: dict


def _validate_headers(fieldnames: list[str] | None, path: str, allow_max_pages: bool) -> None:
    expected = set(_REQUIRED_HEADERS)
    actual = set(fieldnames or [])
    optional = {"review_limit"}
    if allow_max_pages:
        optional.add("max_pages")
    if not expected.issubset(actual):
        missing = ", ".join(sorted(expected - actual))
        raise DailyInputValidationError([f"{path}: missing required headers: {missing}"])
    extra = actual - expected - optional
    if extra:
        raise DailyInputValidationError([f"{path}: unexpected headers: {', '.join(sorted(extra))}"])


def _normalize_ownership(path: str, line_no: int, value: str) -> str:
    ownership = (value or "").strip().lower()
    if ownership not in _OWNERSHIP_VALUES:
        raise DailyInputValidationError(
            [f"{path}: line {line_no}: invalid ownership {value!r}; expected one of own, competitor"]
        )
    return ownership


def _normalize_site(path: str, line_no: int, url: str) -> str:
    try:
        return get_site_key(url)
    except Exception as exc:
        raise DailyInputValidationError([f"{path}: line {line_no}: {exc}"]) from exc


def _parse_max_pages(path: str, line_no: int, value: str) -> int:
    raw = (value or "").strip()
    if not raw:
        return 0
    try:
        parsed = int(raw)
    except ValueError as exc:
        raise DailyInputValidationError([f"{path}: line {line_no}: invalid max_pages {value!r}"]) from exc
    if parsed < 0:
        raise DailyInputValidationError([f"{path}: line {line_no}: max_pages must be >= 0"])
    return parsed


def _parse_review_limit(path: str, line_no: int, value: str) -> int:
    raw = (value or "").strip()
    if not raw:
        return 0
    try:
        parsed = int(raw)
    except ValueError as exc:
        raise DailyInputValidationError([f"{path}: line {line_no}: invalid review_limit {value!r}"]) from exc
    if parsed < 0:
        raise DailyInputValidationError([f"{path}: line {line_no}: review_limit must be >= 0"])
    return parsed


def load_daily_inputs(source_csv: str, detail_csv: str) -> DailyInputsBundle:
    """Load, validate, and group the daily workflow CSV inputs."""
    collect_requests, source_errors = _load_collect_requests(source_csv)
    scrape_requests, detail_errors = _load_scrape_requests(detail_csv)

    errors = source_errors + detail_errors
    if errors:
        raise DailyInputValidationError(errors)

    summary = {
        "collect_count": len(collect_requests),
        "scrape_group_count": len(scrape_requests),
        "scrape_url_count": sum(len(group.urls) for group in scrape_requests),
    }
    return DailyInputsBundle(
        collect_requests=collect_requests,
        scrape_requests=scrape_requests,
        summary=summary,
    )


def _load_collect_requests(path: str) -> tuple[list[CollectRequest], list[str]]:
    requests: list[CollectRequest] = []
    errors: list[str] = []
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        _validate_headers(reader.fieldnames, path, allow_max_pages=True)
        for line_no, row in enumerate(reader, start=2):
            url = (row.get("url") or "").strip()
            if not url:
                continue
            try:
                ownership = _normalize_ownership(path, line_no, row.get("ownership", ""))
                site = _normalize_site(path, line_no, url)
                max_pages = _parse_max_pages(path, line_no, row.get("max_pages", ""))
                review_limit = _parse_review_limit(path, line_no, row.get("review_limit", ""))
                requests.append(
                    CollectRequest(
                        category_url=url,
                        site=site,
                        ownership=ownership,
                        max_pages=max_pages,
                        review_limit=review_limit,
                    )
                )
            except DailyInputValidationError as exc:
                errors.extend(exc.errors)
    return requests, errors


def _load_scrape_requests(path: str) -> tuple[list[ScrapeRequest], list[str]]:
    grouped: dict[tuple[str, str, int], list[str]] = {}
    errors: list[str] = []
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        _validate_headers(reader.fieldnames, path, allow_max_pages=False)
        for line_no, row in enumerate(reader, start=2):
            url = (row.get("url") or "").strip()
            if not url:
                continue
            try:
                ownership = _normalize_ownership(path, line_no, row.get("ownership", ""))
                site = _normalize_site(path, line_no, url)
                review_limit = _parse_review_limit(path, line_no, row.get("review_limit", ""))
                grouped.setdefault((site, ownership, review_limit), [])
                if url not in grouped[(site, ownership, review_limit)]:
                    grouped[(site, ownership, review_limit)].append(url)
            except DailyInputValidationError as exc:
                errors.extend(exc.errors)

    grouped_requests = [
        ScrapeRequest(site=site, ownership=ownership, urls=urls, review_limit=review_limit)
        for (site, ownership, review_limit), urls in grouped.items()
    ]
    return grouped_requests, errors
