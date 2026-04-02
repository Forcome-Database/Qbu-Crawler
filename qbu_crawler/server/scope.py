"""Server-owned scope normalization and preview helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass
class RangeFilter:
    min: float | int | None = None
    max: float | int | None = None


@dataclass
class ProductScope:
    ids: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    skus: list[str] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
    sites: list[str] = field(default_factory=list)
    ownership: list[str] = field(default_factory=list)
    price: RangeFilter = field(default_factory=RangeFilter)
    rating: RangeFilter = field(default_factory=RangeFilter)
    review_count: RangeFilter = field(default_factory=RangeFilter)


@dataclass
class ReviewScope:
    sentiment: str = "all"
    rating: RangeFilter = field(default_factory=RangeFilter)
    keyword: str = ""
    has_images: bool | None = None

    @property
    def max_rating(self) -> float | int | None:
        return self.rating.max

    @max_rating.setter
    def max_rating(self, value: float | int | None) -> None:
        self.rating.max = value


@dataclass
class WindowScope:
    since: str | None = None
    until: str | None = None


@dataclass
class Scope:
    products: ProductScope = field(default_factory=ProductScope)
    reviews: ReviewScope = field(default_factory=ReviewScope)
    window: WindowScope = field(default_factory=WindowScope)


_SUPPORTED_ARTIFACT_TYPES = {"report", "review_images"}


def _as_list(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    return [str(value).strip() for value in values if str(value).strip()]


def _as_range(values: Any) -> RangeFilter:
    if not isinstance(values, dict):
        return RangeFilter()
    return RangeFilter(min=values.get("min"), max=values.get("max"))


def _as_bool(values: Any) -> bool | None:
    if values is None or isinstance(values, bool):
        return values
    if isinstance(values, str):
        lowered = values.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    return None


def normalize_scope(
    products: dict[str, Any] | None = None,
    reviews: dict[str, Any] | None = None,
    window: dict[str, Any] | None = None,
) -> Scope:
    """Normalize the supported product, review, and window filters."""
    products = products or {}
    reviews = reviews or {}
    window = window or {}

    product_scope = ProductScope(
        ids=_as_list(products.get("ids")),
        urls=_as_list(products.get("urls")),
        skus=_as_list(products.get("skus")),
        names=_as_list(products.get("names")),
        sites=[site.lower() for site in _as_list(products.get("sites"))],
        ownership=[owner.lower() for owner in _as_list(products.get("ownership"))],
        price=_as_range(products.get("price")),
        rating=_as_range(products.get("rating")),
        review_count=_as_range(products.get("review_count")),
    )

    review_scope = ReviewScope(
        sentiment=str(reviews.get("sentiment", "all")).strip().lower() or "all",
        rating=_as_range(reviews.get("rating")),
        keyword=str(reviews.get("keyword", "")).strip(),
        has_images=_as_bool(reviews.get("has_images")),
    )
    if review_scope.sentiment == "negative" and review_scope.rating.max is None:
        review_scope.max_rating = 2

    return Scope(
        products=product_scope,
        reviews=review_scope,
        window=WindowScope(
            since=_normalize_date(window.get("since")),
            until=_normalize_date(window.get("until")),
        ),
    )


def needs_preview(scope: Scope) -> bool:
    """Return True when the scope is broad enough to require confirmation."""
    if _window_requires_preview(scope):
        return True
    if _single_product_scope(scope) and not _multi_site_scope(scope) and not _multi_ownership_scope(scope):
        return False
    return True


def preview_hint(scope: Scope, artifact_type: str = "report") -> str:
    """Return a preview outcome for the requested artifact type."""
    if artifact_type not in _SUPPORTED_ARTIFACT_TYPES:
        return "unsupported"
    return "requires_confirmation" if needs_preview(scope) else "safe_to_continue"


def _single_product_scope(scope: Scope) -> bool:
    explicit_product_lists = (
        scope.products.ids,
        scope.products.urls,
        scope.products.skus,
        scope.products.names,
    )
    present_lists = [values for values in explicit_product_lists if values]
    return bool(present_lists) and all(len(values) == 1 for values in present_lists)


def _multi_site_scope(scope: Scope) -> bool:
    return len(scope.products.sites) > 1


def _multi_ownership_scope(scope: Scope) -> bool:
    return len(scope.products.ownership) > 1


def _window_requires_preview(scope: Scope) -> bool:
    if not scope.window.since or not scope.window.until:
        return False
    try:
        since = date.fromisoformat(scope.window.since)
        until = date.fromisoformat(scope.window.until)
    except ValueError:
        return True
    return until < since or (until - since).days > 7


def _normalize_date(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        try:
            return datetime.fromisoformat(value).date().isoformat()
        except ValueError:
            return value
