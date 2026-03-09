from fastapi import APIRouter, Depends, HTTPException

import models
from server.api.auth import verify_api_key

router = APIRouter(prefix="/api", dependencies=[Depends(verify_api_key)])


@router.get("/products")
async def list_products(
    site: str | None = None,
    search: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    stock_status: str | None = None,
    sort_by: str = "scraped_at",
    order: str = "desc",
    limit: int = 20,
    offset: int = 0,
):
    items, total = models.query_products(
        site=site, search=search, min_price=min_price, max_price=max_price,
        stock_status=stock_status, sort_by=sort_by, order=order,
        limit=limit, offset=offset,
    )
    return {"items": items, "total": total}


@router.get("/products/{product_id}")
async def get_product(product_id: int):
    product = models.get_product_by_id(product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    reviews, _ = models.query_reviews(product_id=product_id, limit=5)
    snapshots, _ = models.get_snapshots(product_id=product_id, days=30, limit=10)
    return {**product, "recent_reviews": reviews, "recent_snapshots": snapshots}


@router.get("/products/{product_id}/reviews")
async def get_product_reviews(
    product_id: int,
    min_rating: float | None = None,
    max_rating: float | None = None,
    sort_by: str = "scraped_at",
    order: str = "desc",
    limit: int = 20,
    offset: int = 0,
):
    items, total = models.query_reviews(
        product_id=product_id, min_rating=min_rating, max_rating=max_rating,
        sort_by=sort_by, order=order, limit=limit, offset=offset,
    )
    return {"items": items, "total": total}


@router.get("/products/{product_id}/snapshots")
async def get_product_snapshots(product_id: int, days: int = 30, limit: int = 100, offset: int = 0):
    items, total = models.get_snapshots(product_id=product_id, days=days, limit=limit, offset=offset)
    return {"items": items, "total": total}


@router.get("/stats")
async def get_stats():
    return models.get_stats()
