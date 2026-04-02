"""Crawler task lifecycle manager.

Manages scrape/collect tasks in a thread pool, tracks progress,
supports cancellation, and persists task history to SQLite.
"""

import json as _json
import hashlib
import re
from urllib.parse import unquote, urlparse
import urllib.request
import uuid
import logging
from datetime import datetime
from enum import Enum
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import Any

from qbu_crawler import config, models
from qbu_crawler.scrapers import get_scraper, get_site_key

logger = logging.getLogger(__name__)

_SITE_DISPLAY = {
    "basspro": "Bass Pro",
    "meatyourmaker": "Meat Your Maker",
    "waltons": "Walton's",
}

_OWNERSHIP_DISPLAY = {
    "own": "自有",
    "competitor": "竞品",
}

_TASK_TYPE_DISPLAY = {
    "scrape": "产品页抓取",
    "collect": "分类页采集",
}


class TaskStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class Task:
    def __init__(self, type: str, params: dict, reply_to: str = ""):
        self.id = uuid.uuid4().hex
        self.type = type
        self.status = TaskStatus.pending
        self.params = params
        self.reply_to = reply_to
        self.created_at = config.now_shanghai().isoformat()
        self.started_at: str | None = None
        self.finished_at: str | None = None
        self.updated_at: str = self.created_at
        self.last_progress_at: str | None = None
        self.worker_token: str | None = None
        self.system_error_code: str | None = None
        self.progress: dict = {}
        self.result: dict | None = None
        self.error: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "status": self.status.value,
            "params": self.params,
            "reply_to": self.reply_to,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "updated_at": self.updated_at,
            "last_progress_at": self.last_progress_at,
            "worker_token": self.worker_token,
            "system_error_code": self.system_error_code,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
            "notified_at": None,
        }


class TaskManager:
    def __init__(self, max_workers: int = 3, translator=None):
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._tasks: dict[str, Task] = {}
        self._cancel_flags: dict[str, Event] = {}
        self._translator = translator

    def submit_scrape(
        self,
        urls: list[str],
        ownership: str = "competitor",
        review_limit: int = 0,
        reply_to: str = "",
    ) -> Task:
        task = Task(
            type="scrape",
            params={"urls": urls, "ownership": ownership, "review_limit": review_limit},
            reply_to=reply_to,
        )
        task.progress = {"total": len(urls), "completed": 0, "failed": 0, "current_url": None}
        self._tasks[task.id] = task
        self._cancel_flags[task.id] = Event()
        self._persist(task)
        self._executor.submit(self._run_scrape, task.id)
        return task

    def submit_collect(
        self,
        category_url: str,
        max_pages: int = 0,
        review_limit: int = 0,
        ownership: str = "competitor",
        reply_to: str = "",
    ) -> Task:
        task = Task(
            type="collect",
            params={
                "category_url": category_url,
                "max_pages": max_pages,
                "review_limit": review_limit,
                "ownership": ownership,
            },
            reply_to=reply_to,
        )
        task.progress = {"phase": "collecting", "urls_found": 0, "completed": 0, "failed": 0}
        self._tasks[task.id] = task
        self._cancel_flags[task.id] = Event()
        self._persist(task)
        self._executor.submit(self._run_collect, task.id)
        return task

    def cancel_task(self, task_id: str) -> bool:
        flag = self._cancel_flags.get(task_id)
        task = self._tasks.get(task_id)
        if not flag or not task:
            return False
        if task.status not in (TaskStatus.pending, TaskStatus.running):
            return False
        flag.set()
        # Don't mutate task state here — let the worker thread handle it
        # to avoid race conditions between API thread and worker thread.
        return True

    def get_task(self, task_id: str) -> dict | None:
        task = self._tasks.get(task_id)
        if task:
            return task.to_dict()
        return models.get_task(task_id)

    def list_tasks(self, status: str | None = None, limit: int = 20, offset: int = 0) -> tuple[list[dict], int]:
        return models.list_tasks(status=status, limit=limit, offset=offset)

    def _run_scrape(self, task_id: str):
        task = self._tasks[task_id]
        flag = self._cancel_flags[task_id]
        task.status = TaskStatus.running
        task.worker_token = uuid.uuid4().hex
        task.started_at = config.now_shanghai().isoformat()
        self._persist(task)

        urls = task.params["urls"]
        products_saved = 0
        reviews_saved = 0
        scraper = None

        try:
            for i, url in enumerate(urls):
                if flag.is_set():
                    break

                task.progress["current_url"] = url
                self._persist(task)

                try:
                    if scraper is None or get_site_key(url) != getattr(scraper, '_current_site', None):
                        if scraper:
                            scraper.close()
                        scraper = get_scraper(url)
                        scraper._current_site = get_site_key(url)

                    effective_review_limit = self._resolve_review_limit(
                        url,
                        task.params.get("review_limit", 0),
                    )
                    data = scraper.scrape(url, review_limit=effective_review_limit)
                    product = data.get("product", {})
                    product["ownership"] = task.params["ownership"]
                    reviews = data.get("reviews", [])

                    pid = models.save_product(product)
                    models.save_snapshot(pid, product)
                    rc = models.save_reviews(pid, reviews)
                    if rc > 0 and self._translator:
                        self._translator.trigger()

                    products_saved += 1
                    reviews_saved += rc
                    task.progress["completed"] = i + 1

                except Exception as e:
                    logger.error(f"[Task {task_id}] Failed {url}: {e}")
                    task.progress["failed"] = task.progress.get("failed", 0) + 1
                    task.progress["completed"] = i + 1

                self._persist(task)

            if flag.is_set():
                task.status = TaskStatus.cancelled
            else:
                task.status = TaskStatus.completed
                task.result = {"products_saved": products_saved, "reviews_saved": reviews_saved}

        except Exception as e:
            task.status = TaskStatus.failed
            task.error = str(e)
            logger.exception(f"[Task {task_id}] Fatal error")
        finally:
            if scraper:
                scraper.close()
            task.finished_at = config.now_shanghai().isoformat()
            task.progress["current_url"] = None
            self._persist(task)
            if task.reply_to:
                self._notify_completion(task_id)
            self._tasks.pop(task_id, None)
            self._cancel_flags.pop(task_id, None)

    def _run_collect(self, task_id: str):
        task = self._tasks[task_id]
        flag = self._cancel_flags[task_id]
        task.status = TaskStatus.running
        task.worker_token = uuid.uuid4().hex
        task.started_at = config.now_shanghai().isoformat()
        self._persist(task)

        category_url = task.params["category_url"]
        max_pages = task.params.get("max_pages", 0)
        requested_review_limit = task.params.get("review_limit", 0)
        scraper = None

        try:
            scraper = get_scraper(category_url)

            urls = scraper.collect_product_urls(category_url, max_pages=max_pages)
            task.progress = {
                "phase": "scraping",
                "urls_found": len(urls),
                "total": len(urls),
                "completed": 0,
                "failed": 0,
                "current_url": None,
            }
            self._persist(task)

            if flag.is_set():
                task.status = TaskStatus.cancelled
                return

            products_saved = 0
            reviews_saved = 0

            for i, url in enumerate(urls):
                if flag.is_set():
                    break

                task.progress["current_url"] = url
                self._persist(task)

                try:
                    effective_review_limit = self._resolve_review_limit(url, requested_review_limit)
                    data = scraper.scrape(url, review_limit=effective_review_limit)
                    product = data.get("product", {})
                    product["ownership"] = task.params["ownership"]
                    reviews = data.get("reviews", [])

                    pid = models.save_product(product)
                    models.save_snapshot(pid, product)
                    rc = models.save_reviews(pid, reviews)
                    if rc > 0 and self._translator:
                        self._translator.trigger()

                    products_saved += 1
                    reviews_saved += rc
                    task.progress["completed"] = i + 1

                except Exception as e:
                    logger.error(f"[Task {task_id}] Failed {url}: {e}")
                    task.progress["failed"] = task.progress.get("failed", 0) + 1
                    task.progress["completed"] = i + 1

                self._persist(task)

            if flag.is_set():
                task.status = TaskStatus.cancelled
            else:
                task.status = TaskStatus.completed
                task.result = {"products_saved": products_saved, "reviews_saved": reviews_saved}

        except Exception as e:
            task.status = TaskStatus.failed
            task.error = str(e)
            logger.exception(f"[Task {task_id}] Fatal error")
        finally:
            if scraper:
                scraper.close()
            task.finished_at = config.now_shanghai().isoformat()
            task.progress["current_url"] = None
            self._persist(task)
            if task.reply_to:
                self._notify_completion(task_id)
            self._tasks.pop(task_id, None)
            self._cancel_flags.pop(task_id, None)

    def _resolve_review_limit(self, url: str, requested_limit: int | None) -> int | None:
        limit = requested_limit or 0
        if limit <= 0:
            return None
        if models.get_product_by_url(url) is None:
            return None
        return limit

    def _persist(self, task: Task):
        try:
            now = config.now_shanghai().isoformat()
            task.updated_at = now
            if task.status == TaskStatus.running:
                task.last_progress_at = now
            models.save_task(task.to_dict())
        except Exception as e:
            logger.error(f"Failed to persist task {task.id}: {e}")

    def _notify_completion(self, task_id: str):
        """任务完成后通过 /hooks/agent 直接投递通知到钉钉。
        服务端组装通知内容 + 投递 + 标记已通知，不依赖心跳或 HEARTBEAT.md。
        失败时静默（不影响主流程，回退到定时心跳轮询兜底）。"""
        mode = getattr(config, "NOTIFICATION_MODE", "legacy")
        hook_url = config.OPENCLAW_HOOK_URL
        hook_token = config.OPENCLAW_HOOK_TOKEN

        task = self._tasks.get(task_id)
        if not task:
            return

        # 组装通知内容
        type_cn = _TASK_TYPE_DISPLAY.get(task.type, task.type)
        status_map = {
            "completed": "成功",
            "failed": "失败",
            "cancelled": "已取消",
        }
        status_cn = status_map.get(task.status.value, task.status.value)
        site_key = _task_site_key(task)
        site_cn = _SITE_DISPLAY.get(site_key, "未知站点")
        ownership = str(task.params.get("ownership") or "").strip()
        ownership_cn = _OWNERSHIP_DISPLAY.get(ownership, ownership or "未知")
        target_summary = _task_target_summary(task)
        result_summary = _task_result_summary(task)
        failed_summary = _task_failed_summary(task)
        product_count = _task_product_count(task)
        review_count = _task_review_count(task)

        if task.status == TaskStatus.completed:
            title = "✅ 抓取完成" if task.type == "scrape" else "✅ 采集完成"
        elif task.status == TaskStatus.failed:
            title = "❌ 抓取失败" if task.type == "scrape" else "❌ 采集失败"
        else:
            title = "🚫 抓取已取消" if task.type == "scrape" else "🚫 采集已取消"

        lines = [
            title,
            "",
            f"- **目标**：{target_summary}",
            f"- **站点**：{site_cn}",
            f"- **归属**：{ownership_cn}",
            f"- **任务类型**：{type_cn}",
            f"- **结果**：{result_summary}",
            "",
            "### 本次产出",
            f"- **产品记录**：{product_count} 个",
            f"- **新增评论**：{review_count} 条",
            f"- **失败项**：{failed_summary}",
            "",
            f"- **任务 ID**：{task.id}",
        ]
        if task.status == TaskStatus.failed and task.error:
            lines.append(f"- **错误详情**：{task.error[:200]}")
        lines.append("")
        lines.append("如需，我可以继续做差评总结、价格变化或邮件报告。")
        notification = "\n".join(lines)

        if mode in {"shadow", "outbox"}:
            payload = {
                "task_id": task.id,
                "task_type": task.type,
                "status": task.status.value,
                "reply_to": task.reply_to,
                "message": notification,
                "result": task.result or {},
                "error": task.error,
                "site": site_key,
                "ownership": ownership,
                "target_summary": target_summary,
                "result_summary": result_summary,
                "failed_summary": failed_summary,
                "product_count": product_count,
                "review_count": review_count,
                "task_heading": title,
            }
            payload_hash = hashlib.sha1(
                _json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest()
            models.enqueue_notification(
                {
                    "kind": "task_completed",
                    "channel": "dingtalk",
                    "target": task.reply_to,
                    "payload": payload,
                    "dedupe_key": f"task:{task.id}:{task.status.value}",
                    "payload_hash": payload_hash,
                }
            )
            logger.info(f"[Task {task_id}] Completion notification queued to outbox (mode={mode})")

        if mode == "outbox":
            return
        if not hook_url:
            return

        # POST /hooks/agent 直接投递
        base = hook_url.rstrip("/").removesuffix("/hooks/wake").removesuffix("/hooks/agent")
        agent_url = f"{base}/hooks/agent"

        payload = {
            "message": f"IMPORTANT: 原样输出以下内容，不要修改、添加、删除或解释任何内容。\n\n{notification}",
            "deliver": True,
            "channel": "dingtalk",
            "to": task.reply_to,
            "name": f"task-done-{task_id[:8]}",
            "thinking": "low",
        }

        try:
            data = _json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                agent_url,
                data=data,
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    **({"Authorization": f"Bearer {hook_token}"} if hook_token else {}),
                },
            )
            urllib.request.urlopen(req, timeout=10)
            models.mark_task_notified([task_id])
            logger.info(f"[Task {task_id}] Notification delivered via /hooks/agent")
        except Exception as e:
            logger.warning(f"[Task {task_id}] Failed to deliver notification: {e}")


def _task_site_key(task: Task) -> str:
    candidates = []
    if task.type == "scrape":
        candidates.extend(task.params.get("urls") or [])
    elif task.type == "collect":
        category_url = task.params.get("category_url")
        if category_url:
            candidates.append(category_url)

    for candidate in candidates:
        try:
            return get_site_key(candidate)
        except Exception:
            continue
    return ""


def _humanize_slug(value: str) -> str:
    text = re.sub(r"\.[a-zA-Z0-9]+$", "", value.strip())
    text = re.sub(r"[-_]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text.title()


def _task_target_summary(task: Task) -> str:
    if task.type == "scrape":
        urls = task.params.get("urls") or []
        if not urls:
            return "未提供目标"
        if len(urls) > 1:
            return f"{len(urls)} 个产品链接"
        parsed = urlparse(urls[0])
        segments = [segment for segment in parsed.path.split("/") if segment]
        slug = unquote(segments[-1]) if segments else parsed.netloc
        return _humanize_slug(slug) or urls[0]

    category_url = str(task.params.get("category_url") or "").strip()
    if not category_url:
        return "未提供分类页"
    parsed = urlparse(category_url)
    segments = [segment for segment in parsed.path.split("/") if segment]
    slug = unquote(segments[-1]) if segments else parsed.netloc
    return _humanize_slug(slug) or category_url


def _task_product_count(task: Task) -> int:
    result = task.result or {}
    if result.get("products_saved") is not None:
        return int(result.get("products_saved") or 0)
    if result.get("products_collected") is not None:
        return int(result.get("products_collected") or 0)
    return 0


def _task_review_count(task: Task) -> int:
    result = task.result or {}
    return int(result.get("reviews_saved") or 0)


def _task_failed_summary(task: Task) -> str:
    if task.status == TaskStatus.failed:
        return "1 项失败"
    return "无"


def _task_result_summary(task: Task) -> str:
    if task.status == TaskStatus.failed:
        return "任务执行失败"
    if task.status == TaskStatus.cancelled:
        return "任务已取消"

    result = task.result or {}
    if task.type == "collect":
        collected = int(result.get("products_collected") or 0)
        if collected > 0:
            return f"分类采集完成，发现 {collected} 个产品链接"
        return "分类采集完成，未发现新的产品链接"

    products = int(result.get("products_saved") or 0)
    reviews = int(result.get("reviews_saved") or 0)
    if products > 0 and reviews > 0:
        return f"产品信息已刷新，并发现 {reviews} 条新评论"
    if products > 0 and reviews == 0:
        return "产品信息已刷新，未发现新评论"
    if products == 0 and reviews > 0:
        return f"发现 {reviews} 条评论更新"
    return "任务完成，但未抓到新的有效数据"
