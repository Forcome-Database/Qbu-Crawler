"""Crawler task lifecycle manager.

Manages scrape/collect tasks in a thread pool, tracks progress,
supports cancellation, and persists task history to SQLite.
"""

import uuid
import logging
from datetime import datetime, timezone
from enum import Enum
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import Any

import models
from scrapers import get_scraper, get_site_key

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class Task:
    def __init__(self, type: str, params: dict):
        self.id = uuid.uuid4().hex
        self.type = type
        self.status = TaskStatus.pending
        self.params = params
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.started_at: str | None = None
        self.finished_at: str | None = None
        self.progress: dict = {}
        self.result: dict | None = None
        self.error: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "status": self.status.value,
            "params": self.params,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
        }


class TaskManager:
    def __init__(self, max_workers: int = 3):
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._tasks: dict[str, Task] = {}
        self._cancel_flags: dict[str, Event] = {}

    def submit_scrape(self, urls: list[str]) -> Task:
        task = Task(type="scrape", params={"urls": urls})
        task.progress = {"total": len(urls), "completed": 0, "failed": 0, "current_url": None}
        self._tasks[task.id] = task
        self._cancel_flags[task.id] = Event()
        self._persist(task)
        self._executor.submit(self._run_scrape, task.id)
        return task

    def submit_collect(self, category_url: str, max_pages: int = 0) -> Task:
        task = Task(type="collect", params={"category_url": category_url, "max_pages": max_pages})
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
        task.status = TaskStatus.cancelled
        task.finished_at = datetime.now(timezone.utc).isoformat()
        self._persist(task)
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
        task.started_at = datetime.now(timezone.utc).isoformat()
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

                    data = scraper.scrape(url)
                    product = data.get("product", {})
                    reviews = data.get("reviews", [])

                    pid = models.save_product(product)
                    models.save_snapshot(pid, product)
                    rc = models.save_reviews(pid, reviews)

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
            task.finished_at = datetime.now(timezone.utc).isoformat()
            task.progress["current_url"] = None
            self._persist(task)

    def _run_collect(self, task_id: str):
        task = self._tasks[task_id]
        flag = self._cancel_flags[task_id]
        task.status = TaskStatus.running
        task.started_at = datetime.now(timezone.utc).isoformat()
        self._persist(task)

        category_url = task.params["category_url"]
        max_pages = task.params.get("max_pages", 0)
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
                    data = scraper.scrape(url)
                    product = data.get("product", {})
                    reviews = data.get("reviews", [])

                    pid = models.save_product(product)
                    models.save_snapshot(pid, product)
                    rc = models.save_reviews(pid, reviews)

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
            task.finished_at = datetime.now(timezone.utc).isoformat()
            task.progress["current_url"] = None
            self._persist(task)

    def _persist(self, task: Task):
        try:
            models.save_task(task.to_dict())
        except Exception as e:
            logger.error(f"Failed to persist task {task.id}: {e}")
