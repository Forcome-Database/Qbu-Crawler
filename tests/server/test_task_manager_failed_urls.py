import time

from qbu_crawler import config, models
from qbu_crawler.server import task_manager as task_manager_module


class FailingScraper:
    def scrape(self, _url, review_limit=None):
        raise KeyError("searchId")

    def close(self):
        pass


def wait_until_task_finished(task_id, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = models.get_task(task_id)
        if task and task["status"] in {"completed", "failed", "cancelled"}:
            return task
        time.sleep(0.05)
    raise AssertionError(f"task {task_id} did not finish")


def test_task_result_records_failed_url(monkeypatch, tmp_path):
    db = tmp_path / "tasks.db"
    monkeypatch.setattr(config, "DB_PATH", str(db))
    monkeypatch.setattr(models, "DB_PATH", str(db))
    models.init_db()

    url = "https://www.basspro.com/p/cabelas-heavy-duty-20-lb-meat-mixer"
    monkeypatch.setattr(task_manager_module, "get_scraper", lambda _url: FailingScraper())

    manager = task_manager_module.TaskManager(max_workers=1)
    try:
        task = manager.submit_scrape([url])
        saved_task = wait_until_task_finished(task.id)
    finally:
        manager._executor.shutdown(wait=True)

    result = saved_task["result"]
    assert saved_task["status"] == "completed"
    assert result["expected_url_count"] == 1
    assert result["saved_url_count"] == 0
    assert result["failed_url_count"] == 1
    assert result["failed_urls"][0]["url"] == url
    assert result["failed_urls"][0]["site"] == "basspro"
    assert result["failed_urls"][0]["stage"] == "scrape"
    assert result["failed_urls"][0]["error_type"] == "KeyError"
    assert result["failed_urls"][0]["error_message"] == "'searchId'"
