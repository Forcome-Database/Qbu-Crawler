from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from qbu_crawler.server.api.auth import verify_api_key

router = APIRouter(prefix="/api/tasks", dependencies=[Depends(verify_api_key)])


class ScrapeRequest(BaseModel):
    urls: list[str]
    ownership: str
    review_limit: int = 0
    reply_to: str = ""

class CollectRequest(BaseModel):
    category_url: str
    max_pages: int = 0
    review_limit: int = 0
    ownership: str
    reply_to: str = ""


def _get_tm():
    from qbu_crawler.server.app import task_manager
    return task_manager


@router.post("/scrape")
async def create_scrape_task(req: ScrapeRequest):
    if not req.urls:
        raise HTTPException(400, "urls cannot be empty")
    tm = _get_tm()
    task = tm.submit_scrape(
        req.urls,
        ownership=req.ownership,
        review_limit=req.review_limit,
        reply_to=req.reply_to,
    )
    return {"task_id": task.id, "status": task.status.value, "total": len(req.urls)}


@router.post("/collect")
async def create_collect_task(req: CollectRequest):
    tm = _get_tm()
    task = tm.submit_collect(
        req.category_url,
        req.max_pages,
        review_limit=req.review_limit,
        ownership=req.ownership,
        reply_to=req.reply_to,
    )
    return {"task_id": task.id, "status": task.status.value}


@router.get("")
async def list_tasks(status: str | None = None, limit: int = 20, offset: int = 0):
    tm = _get_tm()
    tasks, total = tm.list_tasks(status=status, limit=limit, offset=offset)
    return {"tasks": tasks, "total": total}


@router.get("/{task_id}")
async def get_task(task_id: str):
    tm = _get_tm()
    task = tm.get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return task


@router.delete("/{task_id}")
async def cancel_task(task_id: str):
    tm = _get_tm()
    ok = tm.cancel_task(task_id)
    if not ok:
        raise HTTPException(404, "Task not found or not cancellable")
    return {"task_id": task_id, "status": "cancelled"}
