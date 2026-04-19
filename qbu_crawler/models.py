import hashlib
import json as _json
import sqlite3
from datetime import date, datetime, timedelta, timezone

from qbu_crawler.config import DB_PATH, now_shanghai
from qbu_crawler.server.scope import Scope

# SQLite CURRENT_TIMESTAMP is always UTC.
# Use this expression for Asia/Shanghai (UTC+8) timestamps.
_NOW_SHANGHAI = "datetime('now', '+8 hours')"
_TIME_AXIS_FIELDS = {
    "product_state_time": "products.scraped_at",
    "snapshot_time": "product_snapshots.scraped_at",
    "review_ingest_time": "reviews.scraped_at",
    "review_publish_time": "reviews.date_published",
}


import calendar as _calendar
import re as _re


def _parse_date_published(value):
    """Parse date_published to ISO string. Handles MM/DD/YYYY and relative formats.

    Lightweight inline version to avoid importing from server.report_common.
    """
    if not value:
        return None
    s = value.strip()
    # ISO: "2026-01-01"
    try:
        return date.fromisoformat(s[:10]).isoformat()
    except (ValueError, IndexError):
        pass
    # MM/DD/YYYY: "01/18/2024"
    try:
        return datetime.strptime(s, "%m/%d/%Y").date().isoformat()
    except ValueError:
        pass
    # Relative: "3 months ago", "a year ago"
    today = date.today()
    m = _re.match(r"(?:(\d+)|a|an)\s+(day|week|month|year)s?\s+ago", s, _re.IGNORECASE)
    if m:
        amount = int(m.group(1)) if m.group(1) else 1
        unit = m.group(2).lower()
        if unit == "day":
            return (today - timedelta(days=amount)).isoformat()
        if unit == "week":
            return (today - timedelta(weeks=amount)).isoformat()
        if unit == "month":
            month = today.month - amount
            year = today.year
            while month <= 0:
                month += 12
                year -= 1
            max_day = _calendar.monthrange(year, month)[1]
            return date(year, month, min(today.day, max_day)).isoformat()
        if unit == "year":
            try:
                return today.replace(year=today.year - amount).isoformat()
            except ValueError:
                return today.replace(year=today.year - amount, day=28).isoformat()
    return None


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE NOT NULL,
            site TEXT NOT NULL DEFAULT 'basspro',
            name TEXT,
            sku TEXT,
            price REAL,
            stock_status TEXT,
            review_count INTEGER,
            rating REAL,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ownership TEXT NOT NULL DEFAULT 'competitor'
        );

        CREATE TABLE IF NOT EXISTS product_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            price REAL,
            stock_status TEXT,
            review_count INTEGER,
            rating REAL,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            author TEXT,
            headline TEXT,
            body TEXT,
            body_hash TEXT,
            rating REAL,
            date_published TEXT,
            images TEXT,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id           TEXT PRIMARY KEY,
            type         TEXT NOT NULL,
            status       TEXT NOT NULL DEFAULT 'pending',
            params       TEXT NOT NULL,
            progress     TEXT,
            result       TEXT,
            error        TEXT,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_progress_at TIMESTAMP,
            worker_token TEXT,
            system_error_code TEXT,
            started_at   TIMESTAMP,
            finished_at  TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS workflow_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_type TEXT NOT NULL,
            status TEXT NOT NULL,
            report_phase TEXT NOT NULL DEFAULT 'none',
            logical_date TEXT NOT NULL,
            trigger_key TEXT NOT NULL UNIQUE,
            data_since TIMESTAMP,
            data_until TIMESTAMP,
            snapshot_at TIMESTAMP,
            snapshot_path TEXT,
            snapshot_hash TEXT,
            excel_path TEXT,
            analytics_path TEXT,
            pdf_path TEXT,
            requested_by TEXT,
            service_version TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            started_at TIMESTAMP,
            finished_at TIMESTAMP,
            error TEXT
        );

        CREATE TABLE IF NOT EXISTS review_issue_labels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            review_id INTEGER NOT NULL,
            label_code TEXT NOT NULL,
            label_polarity TEXT NOT NULL,
            severity TEXT NOT NULL,
            confidence REAL NOT NULL,
            source TEXT NOT NULL,
            taxonomy_version TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(review_id, label_code, label_polarity),
            FOREIGN KEY (review_id) REFERENCES reviews(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS review_analysis (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            review_id       INTEGER NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
            sentiment       TEXT NOT NULL,
            sentiment_score REAL,
            labels          TEXT NOT NULL DEFAULT '[]',
            features        TEXT NOT NULL DEFAULT '[]',
            insight_cn      TEXT,
            insight_en      TEXT,
            llm_model       TEXT,
            prompt_version  TEXT NOT NULL,
            token_usage     INTEGER,
            analyzed_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(review_id, prompt_version)
        );

        CREATE TABLE IF NOT EXISTS workflow_run_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            task_id TEXT NOT NULL,
            task_type TEXT,
            site TEXT,
            ownership TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(run_id, task_id),
            FOREIGN KEY (run_id) REFERENCES workflow_runs(id) ON DELETE CASCADE,
            FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS notification_outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            channel TEXT NOT NULL,
            target TEXT NOT NULL,
            payload TEXT NOT NULL,
            dedupe_key TEXT NOT NULL UNIQUE,
            payload_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            claimed_at TIMESTAMP,
            claim_token TEXT,
            lease_until TIMESTAMP,
            bridge_request_id TEXT,
            last_http_status INTEGER,
            last_exit_code INTEGER,
            last_error TEXT,
            attempts INTEGER NOT NULL DEFAULT 0,
            delivered_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    # 兼容旧表：添加缺失的列
    migrations = [
        "ALTER TABLE reviews ADD COLUMN images TEXT",
        "ALTER TABLE reviews ADD COLUMN body_hash TEXT",
        "ALTER TABLE reviews ADD COLUMN scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "ALTER TABLE products ADD COLUMN site TEXT NOT NULL DEFAULT 'basspro'",
        "ALTER TABLE products ADD COLUMN ownership TEXT NOT NULL DEFAULT 'competitor'",
        "ALTER TABLE reviews ADD COLUMN headline_cn TEXT",
        "ALTER TABLE reviews ADD COLUMN body_cn TEXT",
        "ALTER TABLE reviews ADD COLUMN translate_retries INTEGER DEFAULT 0",
        "ALTER TABLE tasks ADD COLUMN reply_to TEXT",
        "ALTER TABLE tasks ADD COLUMN notified_at TIMESTAMP",
        "ALTER TABLE tasks ADD COLUMN updated_at TIMESTAMP",
        "ALTER TABLE tasks ADD COLUMN last_progress_at TIMESTAMP",
        "ALTER TABLE tasks ADD COLUMN worker_token TEXT",
        "ALTER TABLE tasks ADD COLUMN system_error_code TEXT",
        "ALTER TABLE workflow_runs ADD COLUMN report_phase TEXT NOT NULL DEFAULT 'none'",
        "ALTER TABLE workflow_runs ADD COLUMN analytics_path TEXT",
        "ALTER TABLE workflow_runs ADD COLUMN pdf_path TEXT",
        "ALTER TABLE notification_outbox ADD COLUMN delivered_at TIMESTAMP",
        "ALTER TABLE reviews ADD COLUMN date_published_parsed TEXT",
        "ALTER TABLE workflow_runs ADD COLUMN report_mode TEXT",
        "ALTER TABLE review_analysis ADD COLUMN impact_category TEXT",
        "ALTER TABLE review_analysis ADD COLUMN failure_mode TEXT",
        "ALTER TABLE workflow_runs ADD COLUMN scrape_quality TEXT",
    ]
    for sql in migrations:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass  # 列已存在
    # 回填旧数据的 body_hash（迁移兼容）
    # 先删除旧索引（如果存在），避免回填时冲突
    try:
        conn.execute("DROP INDEX IF EXISTS idx_reviews_dedup")
    except sqlite3.OperationalError:
        pass
    conn.execute("""
        UPDATE reviews SET body_hash = ''
        WHERE body_hash IS NULL AND (body IS NULL OR body = '')
    """)
    rows = conn.execute("SELECT id, body FROM reviews WHERE body_hash IS NULL AND body IS NOT NULL AND body != ''").fetchall()
    for row in rows:
        bh = _body_hash(row["body"])
        conn.execute("UPDATE reviews SET body_hash = ? WHERE id = ?", (bh, row["id"]))
    if rows:
        conn.commit()
    # 删除回填后产生的重复评论（保留 id 最小的）
    conn.execute("""
        DELETE FROM reviews WHERE id NOT IN (
            SELECT MIN(id) FROM reviews GROUP BY product_id, author, headline, body_hash
        )
    """)
    conn.commit()
    # 创建唯一索引（增量去重用）
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_reviews_dedup
        ON reviews (product_id, author, headline, body_hash)
    """)

    # ── Translation status column + one-time backfill ──
    _needs_translate_backfill = False
    try:
        conn.execute("ALTER TABLE reviews ADD COLUMN translate_status TEXT")
        _needs_translate_backfill = True
    except sqlite3.OperationalError:
        pass  # Column already exists

    if _needs_translate_backfill:
        conn.execute("UPDATE reviews SET translate_status = 'skipped' WHERE translate_status IS NULL")
        conn.commit()

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_reviews_translate_status
        ON reviews (translate_status)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_tasks_status_updated_at
        ON tasks (status, updated_at)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_outbox_status_created_at
        ON notification_outbox (status, created_at)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_products_sku
        ON products (sku)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_products_site
        ON products (site)
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ra_review ON review_analysis(review_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ra_sentiment ON review_analysis(sentiment)")

    # Backfill date_published_parsed for existing reviews
    _backfill_date_published_parsed(conn)

    conn.close()


def _backfill_date_published_parsed(conn):
    """One-time backfill of date_published_parsed from date_published + scraped_at anchor."""
    from qbu_crawler.server.report_common import _parse_date_flexible

    rows = conn.execute(
        "SELECT id, date_published, scraped_at FROM reviews "
        "WHERE date_published_parsed IS NULL AND date_published IS NOT NULL"
    ).fetchall()
    if not rows:
        return
    for row in rows:
        anchor = None
        if row["scraped_at"]:
            try:
                anchor = datetime.fromisoformat(
                    str(row["scraped_at"]).replace(" ", "T")
                ).date()
            except (ValueError, TypeError):
                pass
        parsed = _parse_date_flexible(row["date_published"], anchor_date=anchor)
        if parsed:
            conn.execute(
                "UPDATE reviews SET date_published_parsed = ? WHERE id = ?",
                (parsed.isoformat(), row["id"]),
            )
    conn.commit()


def _body_hash(body: str | None) -> str:
    """正文 MD5 前 16 位，用于去重"""
    if not body:
        return ""
    return hashlib.md5(body.encode()).hexdigest()[:16]


def _decode_json_fields(row: sqlite3.Row | None, fields: tuple[str, ...] = ()) -> dict | None:
    if row is None:
        return None
    data = dict(row)
    for field in fields:
        if data.get(field):
            data[field] = _json.loads(data[field])
    return data


def save_product(data: dict) -> int:
    conn = get_conn()
    now = _NOW_SHANGHAI
    cursor = conn.execute(f"""
        INSERT INTO products (url, site, name, sku, price, stock_status, review_count, rating, ownership, scraped_at)
        VALUES (:url, :site, :name, :sku, :price, :stock_status, :review_count, :rating, :ownership, {now})
        ON CONFLICT(url) DO UPDATE SET
            site = excluded.site,
            name = excluded.name,
            sku = excluded.sku,
            price = excluded.price,
            stock_status = excluded.stock_status,
            review_count = excluded.review_count,
            rating = excluded.rating,
            ownership = excluded.ownership,
            scraped_at = {now}
    """, data)
    product_id = cursor.lastrowid
    if product_id == 0:
        row = conn.execute("SELECT id FROM products WHERE url = ?", (data["url"],)).fetchone()
        product_id = row["id"]
    conn.commit()
    conn.close()
    return product_id


def save_snapshot(product_id: int, data: dict):
    """保存产品快照（价格/库存/评分/评论数变化历史）"""
    conn = get_conn()
    conn.execute(f"""
        INSERT INTO product_snapshots (product_id, price, stock_status, review_count, rating, scraped_at)
        VALUES (?, ?, ?, ?, ?, {_NOW_SHANGHAI})
    """, (product_id, data.get("price"), data.get("stock_status"),
          data.get("review_count"), data.get("rating")))
    conn.commit()
    conn.close()


def save_reviews(product_id: int, reviews: list) -> int:
    """增量保存评论，用 product_id + author + headline + body_hash 去重
    已存在的评论如果有新图片则更新 images 字段
    返回新增评论数
    """
    conn = get_conn()
    new_count = 0
    for r in reviews:
        body = r.get("body") or ""
        bh = _body_hash(body)
        images = r.get("images")
        date_pub = r.get("date_published")
        # Parse date_published at insert time — inline to avoid cross-layer import
        date_parsed = _parse_date_published(date_pub)
        try:
            conn.execute(f"""
                INSERT INTO reviews (product_id, author, headline, body, body_hash, rating,
                                     date_published, date_published_parsed, images, scraped_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, {_NOW_SHANGHAI})
            """, (product_id, r.get("author"), r.get("headline"), body, bh,
                  r.get("rating"), date_pub, date_parsed, images))
            new_count += 1
        except sqlite3.IntegrityError:
            # 已存在：如果新数据有图片而旧数据没有，更新图片
            if images:
                conn.execute("""
                    UPDATE reviews SET images = ?
                    WHERE product_id = ? AND author = ? AND headline = ? AND body_hash = ?
                    AND (images IS NULL OR images = '')
                """, (images, product_id, r.get("author"), r.get("headline"), bh))
    conn.commit()
    conn.close()
    return new_count


# ---------------------------------------------------------------------------
# Task persistence
# ---------------------------------------------------------------------------

def save_task(task_dict: dict) -> None:
    """INSERT or UPDATE a task record."""
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO tasks (id, type, status, params, progress, result, error,
                                  created_at, updated_at, last_progress_at, worker_token,
                                  system_error_code, started_at, finished_at, reply_to, notified_at)
               VALUES (:id, :type, :status, :params, :progress, :result, :error,
                       :created_at, :updated_at, :last_progress_at, :worker_token,
                       :system_error_code, :started_at, :finished_at, :reply_to, :notified_at)
               ON CONFLICT(id) DO UPDATE SET
                   status=excluded.status, progress=excluded.progress,
                   result=excluded.result, error=excluded.error,
                   updated_at=excluded.updated_at,
                   last_progress_at=excluded.last_progress_at,
                   worker_token=excluded.worker_token,
                   system_error_code=excluded.system_error_code,
                   started_at=excluded.started_at, finished_at=excluded.finished_at,
                   notified_at=excluded.notified_at
            """,
            {
                "id": task_dict["id"],
                "type": task_dict["type"],
                "status": task_dict["status"],
                "params": _json.dumps(task_dict.get("params")),
                "progress": _json.dumps(task_dict.get("progress")),
                "result": _json.dumps(task_dict.get("result")),
                "error": task_dict.get("error"),
                "created_at": task_dict.get("created_at"),
                "updated_at": task_dict.get("updated_at"),
                "last_progress_at": task_dict.get("last_progress_at"),
                "worker_token": task_dict.get("worker_token"),
                "system_error_code": task_dict.get("system_error_code"),
                "started_at": task_dict.get("started_at"),
                "finished_at": task_dict.get("finished_at"),
                "reply_to": task_dict.get("reply_to"),
                "notified_at": task_dict.get("notified_at"),
            },
        )
        conn.commit()
    finally:
        conn.close()


def get_task(task_id: str) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return _decode_json_fields(row, ("params", "progress", "result"))
    finally:
        conn.close()


def list_tasks(status: str | None = None, limit: int = 20, offset: int = 0) -> tuple[list[dict], int]:
    conn = get_conn()
    try:
        where = "WHERE status = ?" if status else ""
        params = [status] if status else []

        total = conn.execute(f"SELECT COUNT(*) FROM tasks {where}", params).fetchone()[0]

        rows = conn.execute(
            f"SELECT * FROM tasks {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()

        tasks = []
        for row in rows:
            tasks.append(_decode_json_fields(row, ("params", "progress", "result")))
        return tasks, total
    finally:
        conn.close()


def list_stale_running_tasks(stale_before: str, limit: int = 100) -> list[dict]:
    """Return running tasks whose liveness timestamp is older than ``stale_before``."""
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT * FROM tasks
            WHERE status = 'running'
              AND COALESCE(last_progress_at, updated_at, started_at, created_at) < ?
            ORDER BY COALESCE(last_progress_at, updated_at, started_at, created_at) ASC
            LIMIT ?
            """,
            (stale_before, limit),
        ).fetchall()
        return [_decode_json_fields(row, ("params", "progress", "result")) for row in rows]
    finally:
        conn.close()


def mark_task_lost(
    task_id: str,
    error_code: str = "worker_lost",
    error_message: str = "Task lost during execution",
    finished_at: str | None = None,
) -> bool:
    """Mark a stale running task as failed so it can be reconciled."""
    conn = get_conn()
    try:
        finished_at = finished_at or _NOW_SHANGHAI
        cursor = conn.execute(
            """
            UPDATE tasks
            SET status = 'failed',
                error = ?,
                system_error_code = ?,
                finished_at = ?,
                updated_at = ?
            WHERE id = ?
              AND status = 'running'
            """,
            (error_message, error_code, finished_at, finished_at, task_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def create_workflow_run(run_dict: dict) -> dict:
    """Create a workflow run or return the existing row for the same trigger key."""
    conn = get_conn()
    try:
        cursor = conn.execute(
            """
            INSERT INTO workflow_runs (
                workflow_type, status, report_phase, logical_date, trigger_key,
                data_since, data_until, snapshot_at, snapshot_path,
                snapshot_hash, excel_path, analytics_path, pdf_path, requested_by, service_version,
                created_at, updated_at, started_at, finished_at, error
            ) VALUES (
                :workflow_type, :status, :report_phase, :logical_date, :trigger_key,
                :data_since, :data_until, :snapshot_at, :snapshot_path,
                :snapshot_hash, :excel_path, :analytics_path, :pdf_path, :requested_by, :service_version,
                :created_at, :updated_at, :started_at, :finished_at, :error
            )
            ON CONFLICT(trigger_key) DO NOTHING
            """,
            {
                "workflow_type": run_dict["workflow_type"],
                "status": run_dict.get("status", "pending"),
                "report_phase": run_dict.get("report_phase", "none"),
                "logical_date": run_dict["logical_date"],
                "trigger_key": run_dict["trigger_key"],
                "data_since": run_dict.get("data_since"),
                "data_until": run_dict.get("data_until"),
                "snapshot_at": run_dict.get("snapshot_at"),
                "snapshot_path": run_dict.get("snapshot_path"),
                "snapshot_hash": run_dict.get("snapshot_hash"),
                "excel_path": run_dict.get("excel_path"),
                "analytics_path": run_dict.get("analytics_path"),
                "pdf_path": run_dict.get("pdf_path"),
                "requested_by": run_dict.get("requested_by"),
                "service_version": run_dict.get("service_version"),
                "created_at": run_dict.get("created_at"),
                "updated_at": run_dict.get("updated_at"),
                "started_at": run_dict.get("started_at"),
                "finished_at": run_dict.get("finished_at"),
                "error": run_dict.get("error"),
            },
        )
        conn.commit()
        if cursor.rowcount == 0:
            row = conn.execute(
                "SELECT * FROM workflow_runs WHERE trigger_key = ?",
                (run_dict["trigger_key"],),
            ).fetchone()
            data = dict(row)
            data["created"] = False
            return data
        row = conn.execute(
            "SELECT * FROM workflow_runs WHERE trigger_key = ?",
            (run_dict["trigger_key"],),
        ).fetchone()
        data = dict(row)
        data["created"] = True
        return data
    finally:
        conn.close()


def get_workflow_run_by_trigger_key(trigger_key: str) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM workflow_runs WHERE trigger_key = ?",
            (trigger_key,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_workflow_run(run_id: int) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM workflow_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_workflow_run(run_id: int, **fields) -> dict:
    allowed = {
        "status",
        "report_phase",
        "data_since",
        "data_until",
        "snapshot_at",
        "snapshot_path",
        "snapshot_hash",
        "excel_path",
        "analytics_path",
        "pdf_path",
        "requested_by",
        "service_version",
        "updated_at",
        "started_at",
        "finished_at",
        "error",
        "report_mode",
    }
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        row = get_workflow_run(run_id)
        if row is None:
            raise ValueError(f"Workflow run {run_id} not found")
        return row

    conn = get_conn()
    try:
        assignments = ", ".join(f"{key} = ?" for key in updates)
        params = list(updates.values())
        if "updated_at" not in updates:
            assignments += ", updated_at = ?"
            params.append(now_shanghai().isoformat())
        params.append(run_id)
        cursor = conn.execute(
            f"UPDATE workflow_runs SET {assignments} WHERE id = ?",
            params,
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise ValueError(f"Workflow run {run_id} not found")
        row = conn.execute(
            "SELECT * FROM workflow_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def update_scrape_quality(run_id: int, quality: dict) -> None:
    """把字段缺失统计写入 workflow_runs.scrape_quality（JSON 字符串）。"""
    import json as _json_local
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE workflow_runs SET scrape_quality = ?, updated_at = ? "
            "WHERE id = ?",
            (
                _json_local.dumps(quality, ensure_ascii=False),
                now_shanghai().isoformat(),
                run_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_scrape_quality(run_id: int) -> dict | None:
    import json as _json_local
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT scrape_quality FROM workflow_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row or not row[0]:
        return None
    try:
        return _json_local.loads(row[0])
    except (_json_local.JSONDecodeError, TypeError):
        return None


def replace_review_issue_labels(review_id: int, labels: list[dict]) -> None:
    conn = get_conn()
    try:
        conn.execute("DELETE FROM review_issue_labels WHERE review_id = ?", (review_id,))
        for item in labels:
            conn.execute(
                """
                INSERT INTO review_issue_labels (
                    review_id, label_code, label_polarity, severity,
                    confidence, source, taxonomy_version, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review_id,
                    item["label_code"],
                    item["label_polarity"],
                    item["severity"],
                    item["confidence"],
                    item["source"],
                    item["taxonomy_version"],
                    now_shanghai().isoformat(),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def list_review_issue_labels(review_ids: list[int]) -> dict[int, list[dict]]:
    if not review_ids:
        return {}

    conn = get_conn()
    try:
        placeholders = ",".join("?" for _ in review_ids)
        rows = conn.execute(
            f"""
            SELECT review_id, label_code, label_polarity, severity,
                   confidence, source, taxonomy_version, created_at, updated_at
            FROM review_issue_labels
            WHERE review_id IN ({placeholders})
            ORDER BY review_id ASC, id ASC
            """,
            review_ids,
        ).fetchall()
    finally:
        conn.close()

    result = {review_id: [] for review_id in review_ids}
    for row in rows:
        result[row["review_id"]].append(
            {
                "label_code": row["label_code"],
                "label_polarity": row["label_polarity"],
                "severity": row["severity"],
                "confidence": row["confidence"],
                "source": row["source"],
                "taxonomy_version": row["taxonomy_version"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )
    return result


def get_previous_completed_run(current_run_id: int) -> dict | None:
    """Return the most recent completed daily workflow run before *current_run_id*."""
    conn = get_conn()
    try:
        row = conn.execute(
            """
            SELECT * FROM workflow_runs
            WHERE workflow_type = 'daily'
              AND status = 'completed'
              AND analytics_path IS NOT NULL
              AND analytics_path != ''
              AND id < ?
            ORDER BY id DESC LIMIT 1
            """,
            (current_run_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def query_cluster_reviews(label_code: str, ownership: str | None = None, limit: int = 50) -> list[dict]:
    """Fetch reviews tagged with a given label_code from the full corpus."""
    conn = get_conn()
    try:
        query = """
            SELECT r.id, r.headline, r.body, r.rating, r.author,
                   r.date_published_parsed, r.images, r.scraped_at,
                   r.headline_cn, r.body_cn,
                   p.name AS product_name, p.sku AS product_sku,
                   p.ownership, p.site
            FROM reviews r
            JOIN products p ON r.product_id = p.id
            JOIN review_issue_labels ril ON ril.review_id = r.id
            WHERE ril.label_code = ?
        """
        params: list = [label_code]
        if ownership:
            query += " AND p.ownership = ?"
            params.append(ownership)
        query += " ORDER BY r.scraped_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def list_workflow_runs(
    statuses: list[str] | tuple[str, ...] | None = None,
    limit: int = 100,
) -> list[dict]:
    conn = get_conn()
    try:
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            rows = conn.execute(
                f"""
                SELECT * FROM workflow_runs
                WHERE status IN ({placeholders})
                ORDER BY created_at ASC, id ASC
                LIMIT ?
                """,
                [*statuses, limit],
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM workflow_runs
                ORDER BY created_at ASC, id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def list_workflow_run_tasks(run_id: int) -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT wrt.*, t.status, t.error, t.result, t.updated_at, t.finished_at, t.system_error_code
            FROM workflow_run_tasks wrt
            JOIN tasks t ON t.id = wrt.task_id
            WHERE wrt.run_id = ?
            ORDER BY wrt.id ASC
            """,
            (run_id,),
        ).fetchall()
        return [_decode_json_fields(row, ("result",)) for row in rows]
    finally:
        conn.close()


def list_notifications(
    statuses: list[str] | tuple[str, ...] | None = None,
    limit: int = 100,
) -> list[dict]:
    conn = get_conn()
    try:
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            rows = conn.execute(
                f"""
                SELECT * FROM notification_outbox
                WHERE status IN ({placeholders})
                ORDER BY created_at ASC, id ASC
                LIMIT ?
                """,
                [*statuses, limit],
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM notification_outbox
                ORDER BY created_at ASC, id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_decode_json_fields(row, ("payload",)) for row in rows]
    finally:
        conn.close()


def attach_task_to_workflow(
    run_id: int,
    task_id: str,
    task_type: str = "",
    site: str = "",
    ownership: str = "",
) -> dict:
    """Attach a task to a workflow run, returning the existing row on duplicates."""
    conn = get_conn()
    try:
        conn.execute(
            """
            INSERT INTO workflow_run_tasks (run_id, task_id, task_type, site, ownership)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(run_id, task_id) DO NOTHING
            """,
            (run_id, task_id, task_type, site, ownership),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM workflow_run_tasks WHERE run_id = ? AND task_id = ?",
            (run_id, task_id),
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Data query functions (used by HTTP API and MCP Tools)
# ---------------------------------------------------------------------------

def query_products(
    site: str | None = None,
    search: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    stock_status: str | None = None,
    ownership: str | None = None,
    sort_by: str = "scraped_at",
    order: str = "desc",
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict], int]:
    conn = get_conn()
    try:
        conditions, params = [], []
        if site:
            conditions.append("site = ?"); params.append(site)
        if search:
            conditions.append("name LIKE ?"); params.append(f"%{search}%")
        if min_price is not None:
            conditions.append("price >= ?"); params.append(min_price)
        if max_price is not None:
            conditions.append("price <= ?"); params.append(max_price)
        if stock_status:
            conditions.append("stock_status = ?"); params.append(stock_status)
        if ownership:
            conditions.append("ownership = ?"); params.append(ownership)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        allowed_sorts = {"price", "rating", "review_count", "scraped_at", "name"}
        if sort_by not in allowed_sorts:
            sort_by = "scraped_at"
        order_dir = "ASC" if order.lower() == "asc" else "DESC"

        total = conn.execute(f"SELECT COUNT(*) FROM products {where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM products {where} ORDER BY {sort_by} {order_dir} LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        return [dict(r) for r in rows], total
    finally:
        conn.close()


def get_product_by_id(product_id: int) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_product_by_url(url: str) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM products WHERE url = ?", (url,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_product_by_sku(sku: str) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM products WHERE sku = ?", (sku,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def query_reviews(
    product_id: int | None = None,
    sku: str | None = None,
    site: str | None = None,
    ownership: str | None = None,
    min_rating: float | None = None,
    max_rating: float | None = None,
    author: str | None = None,
    keyword: str | None = None,
    has_images: bool | None = None,
    sort_by: str = "scraped_at",
    order: str = "desc",
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict], int]:
    conn = get_conn()
    try:
        conditions, params = [], []
        if product_id is not None:
            conditions.append("r.product_id = ?"); params.append(product_id)
        if sku:
            conditions.append("p.sku = ?"); params.append(sku)
        if site:
            conditions.append("p.site = ?"); params.append(site)
        if ownership:
            conditions.append("p.ownership = ?"); params.append(ownership)
        if min_rating is not None:
            conditions.append("r.rating >= ?"); params.append(min_rating)
        if max_rating is not None:
            conditions.append("r.rating <= ?"); params.append(max_rating)
        if author:
            conditions.append("r.author LIKE ?"); params.append(f"%{author}%")
        if keyword:
            conditions.append("(r.headline LIKE ? OR r.body LIKE ?)")
            params.extend([f"%{keyword}%", f"%{keyword}%"])
        if has_images is True:
            conditions.append("r.images IS NOT NULL AND r.images != '[]' AND r.images != ''")
        elif has_images is False:
            conditions.append("(r.images IS NULL OR r.images = '[]' OR r.images = '')")

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        allowed_sorts = {"rating": "r.rating", "scraped_at": "r.scraped_at", "date_published": "r.date_published"}
        sort_col = allowed_sorts.get(sort_by, "r.scraped_at")
        order_dir = "ASC" if order.lower() == "asc" else "DESC"

        total = conn.execute(
            f"SELECT COUNT(*) FROM reviews r JOIN products p ON r.product_id = p.id {where}",
            params,
        ).fetchone()[0]

        rows = conn.execute(
            f"""SELECT r.*, p.name as product_name, p.site as product_site
                FROM reviews r JOIN products p ON r.product_id = p.id
                {where} ORDER BY {sort_col} {order_dir} LIMIT ? OFFSET ?""",
            params + [limit, offset],
        ).fetchall()

        results = []
        for row in rows:
            d = dict(row)
            if d.get("images"):
                d["images"] = _json.loads(d["images"]) if isinstance(d["images"], str) else d["images"]
            results.append(d)
        return results, total
    finally:
        conn.close()


def _scope_window_clauses(scope: Scope, column: str) -> tuple[list[str], list]:
    clauses: list[str] = []
    params: list = []

    since = scope.window.since
    if since:
        clauses.append(f"{column} >= ?")
        params.append(since)

    until = scope.window.until
    if until:
        until_exclusive = until
        try:
            until_exclusive = (date.fromisoformat(until) + timedelta(days=1)).isoformat()
        except ValueError:
            pass
        clauses.append(f"{column} < ?")
        params.append(until_exclusive)

    return clauses, params


def _scope_product_clauses(
    scope: Scope,
    alias: str = "p",
    *,
    include_window: bool = True,
) -> tuple[list[str], list]:
    clauses: list[str] = []
    params: list = []

    if scope.products.ids:
        placeholders = ",".join("?" for _ in scope.products.ids)
        clauses.append(f"CAST({alias}.id AS TEXT) IN ({placeholders})")
        params.extend(scope.products.ids)
    if scope.products.urls:
        placeholders = ",".join("?" for _ in scope.products.urls)
        clauses.append(f"{alias}.url IN ({placeholders})")
        params.extend(scope.products.urls)
    if scope.products.skus:
        placeholders = ",".join("?" for _ in scope.products.skus)
        clauses.append(f"{alias}.sku IN ({placeholders})")
        params.extend(scope.products.skus)
    if scope.products.names:
        placeholders = ",".join("?" for _ in scope.products.names)
        clauses.append(f"{alias}.name IN ({placeholders})")
        params.extend(scope.products.names)
    if scope.products.sites:
        placeholders = ",".join("?" for _ in scope.products.sites)
        clauses.append(f"LOWER({alias}.site) IN ({placeholders})")
        params.extend(scope.products.sites)
    if scope.products.ownership:
        placeholders = ",".join("?" for _ in scope.products.ownership)
        clauses.append(f"LOWER({alias}.ownership) IN ({placeholders})")
        params.extend(scope.products.ownership)
    if scope.products.price.min is not None:
        clauses.append(f"{alias}.price >= ?")
        params.append(scope.products.price.min)
    if scope.products.price.max is not None:
        clauses.append(f"{alias}.price <= ?")
        params.append(scope.products.price.max)
    if scope.products.rating.min is not None:
        clauses.append(f"{alias}.rating >= ?")
        params.append(scope.products.rating.min)
    if scope.products.rating.max is not None:
        clauses.append(f"{alias}.rating <= ?")
        params.append(scope.products.rating.max)
    if scope.products.review_count.min is not None:
        clauses.append(f"{alias}.review_count >= ?")
        params.append(scope.products.review_count.min)
    if scope.products.review_count.max is not None:
        clauses.append(f"{alias}.review_count <= ?")
        params.append(scope.products.review_count.max)

    if include_window:
        window_clauses, window_params = _scope_window_clauses(scope, f"{alias}.scraped_at")
        clauses.extend(window_clauses)
        params.extend(window_params)

    return clauses, params


def _scope_review_clauses(
    scope: Scope,
    review_alias: str = "r",
    product_alias: str = "p",
    image_only: bool = False,
) -> tuple[list[str], list]:
    clauses, params = _scope_product_clauses(scope, alias=product_alias, include_window=False)

    if scope.reviews.rating.min is not None:
        clauses.append(f"{review_alias}.rating >= ?")
        params.append(scope.reviews.rating.min)
    if scope.reviews.rating.max is not None:
        clauses.append(f"{review_alias}.rating <= ?")
        params.append(scope.reviews.rating.max)
    if scope.reviews.keyword:
        clauses.append(f"({review_alias}.headline LIKE ? OR {review_alias}.body LIKE ?)")
        params.extend([f"%{scope.reviews.keyword}%", f"%{scope.reviews.keyword}%"])
    if scope.reviews.has_images is True:
        clauses.append(f"{review_alias}.images IS NOT NULL AND {review_alias}.images != '[]' AND {review_alias}.images != ''")
    elif scope.reviews.has_images is False:
        clauses.append(f"({review_alias}.images IS NULL OR {review_alias}.images = '[]' OR {review_alias}.images = '')")
    if image_only:
        clauses.append(f"{review_alias}.images IS NOT NULL AND {review_alias}.images != '[]' AND {review_alias}.images != ''")

    window_clauses, window_params = _scope_window_clauses(scope, f"{review_alias}.scraped_at")
    clauses.extend(window_clauses)
    params.extend(window_params)

    return clauses, params


def _scope_has_review_constraints(scope: Scope) -> bool:
    return any(
        (
            scope.reviews.rating.min is not None,
            scope.reviews.rating.max is not None,
            bool(scope.reviews.keyword),
            scope.reviews.has_images is not None,
            bool(scope.window.since),
            bool(scope.window.until),
        )
    )


def _fetch_scalar(conn, sql: str, params: list | tuple | None = None, default=0):
    value = conn.execute(sql, params or []).fetchone()[0]
    return default if value is None else value


def _metric_product_count(conn, where: str = "", params: list | tuple | None = None) -> int:
    return int(_fetch_scalar(conn, f"SELECT COUNT(*) FROM products p {where}", params, default=0))


def _metric_ingested_review_rows(conn, where: str = "", params: list | tuple | None = None) -> int:
    return int(
        _fetch_scalar(
            conn,
            f"SELECT COUNT(*) FROM reviews r JOIN products p ON r.product_id = p.id {where}",
            params,
            default=0,
        )
    )


def _metric_site_reported_review_total_current(conn, where: str = "", params: list | tuple | None = None) -> int:
    return int(_fetch_scalar(conn, f"SELECT COALESCE(SUM(p.review_count), 0) FROM products p {where}", params, default=0))


def _metric_matched_review_product_count(conn, where: str = "", params: list | tuple | None = None) -> int:
    return int(
        _fetch_scalar(
            conn,
            f"SELECT COUNT(DISTINCT p.id) FROM reviews r JOIN products p ON r.product_id = p.id {where}",
            params,
            default=0,
        )
    )


def _metric_image_review_rows(conn, where: str = "", params: list | tuple | None = None) -> int:
    return int(
        _fetch_scalar(
            conn,
            f"SELECT COUNT(*) FROM reviews r JOIN products p ON r.product_id = p.id {where}",
            params,
            default=0,
        )
    )


def get_time_axis_semantics() -> dict:
    """Return canonical time axes with backing fields and latest observed values."""
    conn = get_conn()
    try:
        latest_values = {
            "product_state_time": _fetch_scalar(conn, "SELECT MAX(scraped_at) FROM products", default=None),
            "snapshot_time": _fetch_scalar(conn, "SELECT MAX(scraped_at) FROM product_snapshots", default=None),
            "review_ingest_time": _fetch_scalar(conn, "SELECT MAX(scraped_at) FROM reviews", default=None),
            "review_publish_time": _fetch_scalar(conn, "SELECT MAX(date_published) FROM reviews", default=None),
        }
        return {
            axis: {
                "field": field,
                "latest": latest_values.get(axis),
            }
            for axis, field in _TIME_AXIS_FIELDS.items()
        }
    finally:
        conn.close()


def preview_scope_counts(scope: Scope) -> dict:
    """Return matched product/review counts for a normalized scope."""
    conn = get_conn()
    try:
        product_clauses, product_params = _scope_product_clauses(scope, alias="p", include_window=False)
        product_where = f"WHERE {' AND '.join(product_clauses)}" if product_clauses else ""
        product_count = _metric_product_count(conn, product_where, product_params)
        site_reported_review_total_current = _metric_site_reported_review_total_current(
            conn, product_where, product_params
        )

        review_clauses, review_params = _scope_review_clauses(scope, review_alias="r", product_alias="p")
        review_where = f"WHERE {' AND '.join(review_clauses)}" if review_clauses else ""
        ingested_review_rows = _metric_ingested_review_rows(conn, review_where, review_params)
        matched_review_product_count = _metric_matched_review_product_count(conn, review_where, review_params)
        matched_product_count = matched_review_product_count if _scope_has_review_constraints(scope) else product_count

        image_clauses, image_params = _scope_review_clauses(
            scope,
            review_alias="r",
            product_alias="p",
            image_only=True,
        )
        image_where = f"WHERE {' AND '.join(image_clauses)}" if image_clauses else ""
        image_review_rows = _metric_image_review_rows(conn, image_where, image_params)

        return {
            "product_count": product_count,
            "ingested_review_rows": ingested_review_rows,
            "site_reported_review_total_current": site_reported_review_total_current,
            "matched_review_product_count": matched_review_product_count,
            "image_review_rows": image_review_rows,
            "matched_product_count": matched_product_count,
            "matched_review_count": ingested_review_rows,
            "matched_image_review_count": image_review_rows,
        }
    finally:
        conn.close()


def list_review_images_for_scope(scope: Scope, limit: int) -> list[dict]:
    """Return image-bearing review rows filtered by a normalized scope."""
    if limit <= 0:
        return []

    conn = get_conn()
    try:
        clauses, params = _scope_review_clauses(scope, review_alias="r", product_alias="p", image_only=True)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = conn.execute(
            f"""
            SELECT
                r.id,
                r.product_id,
                r.author,
                r.headline,
                r.body,
                r.body_hash,
                r.rating,
                r.date_published,
                r.images,
                r.scraped_at,
                p.url AS product_url,
                p.name AS product_name,
                p.sku AS product_sku,
                p.site AS product_site,
                p.ownership AS product_ownership
            FROM reviews r
            JOIN products p ON r.product_id = p.id
            {where}
            ORDER BY r.scraped_at DESC, r.id DESC
            LIMIT ?
            """,
            params + [limit],
        ).fetchall()

        results = []
        for row in rows:
            data = dict(row)
            if data.get("images") and isinstance(data["images"], str):
                try:
                    data["images"] = _json.loads(data["images"])
                except Exception:
                    pass
            results.append(data)
        return results
    finally:
        conn.close()


def get_snapshots(
    product_id: int,
    days: int = 30,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict], int]:
    conn = get_conn()
    try:
        total = conn.execute(
            "SELECT COUNT(*) FROM product_snapshots WHERE product_id = ? AND scraped_at >= datetime('now', ?)",
            (product_id, f"-{days} days"),
        ).fetchone()[0]
        rows = conn.execute(
            """SELECT * FROM product_snapshots
               WHERE product_id = ? AND scraped_at >= datetime('now', ?)
               ORDER BY scraped_at ASC LIMIT ? OFFSET ?""",
            (product_id, f"-{days} days", limit, offset),
        ).fetchall()
        return [dict(r) for r in rows], total
    finally:
        conn.close()


def get_stats() -> dict:
    conn = get_conn()
    try:
        total_products = _metric_product_count(conn)
        total_reviews = _metric_ingested_review_rows(conn)
        site_reported_review_total_current = _metric_site_reported_review_total_current(conn)

        by_site = {}
        for row in conn.execute("SELECT site, COUNT(*) as cnt FROM products GROUP BY site").fetchall():
            by_site[row["site"]] = row["cnt"]

        last_scrape = conn.execute("SELECT MAX(scraped_at) FROM products").fetchone()[0]

        avg_price = conn.execute("SELECT AVG(price) FROM products WHERE price IS NOT NULL").fetchone()[0]
        avg_rating = conn.execute("SELECT AVG(rating) FROM products WHERE rating IS NOT NULL").fetchone()[0]

        by_ownership = {}
        for row in conn.execute("SELECT ownership, COUNT(*) as cnt FROM products GROUP BY ownership").fetchall():
            by_ownership[row["ownership"]] = row["cnt"]

        return {
            "product_count": total_products,
            "ingested_review_rows": total_reviews,
            "site_reported_review_total_current": site_reported_review_total_current,
            "avg_price_current": round(avg_price, 2) if avg_price else None,
            "avg_rating_current": round(avg_rating, 2) if avg_rating else None,
            "time_axes": {
                "product_state_time": {
                    "field": _TIME_AXIS_FIELDS["product_state_time"],
                    "latest": last_scrape,
                },
                "snapshot_time": {
                    "field": _TIME_AXIS_FIELDS["snapshot_time"],
                    "latest": _fetch_scalar(conn, "SELECT MAX(scraped_at) FROM product_snapshots", default=None),
                },
                "review_ingest_time": {
                    "field": _TIME_AXIS_FIELDS["review_ingest_time"],
                    "latest": _fetch_scalar(conn, "SELECT MAX(scraped_at) FROM reviews", default=None),
                },
                "review_publish_time": {
                    "field": _TIME_AXIS_FIELDS["review_publish_time"],
                    "latest": _fetch_scalar(conn, "SELECT MAX(date_published) FROM reviews", default=None),
                },
            },
            "total_products": total_products,
            "total_reviews": total_reviews,
            "by_site": by_site,
            "by_ownership": by_ownership,
            "last_scrape_at": last_scrape,
            "avg_price": round(avg_price, 2) if avg_price else None,
            "avg_rating": round(avg_rating, 2) if avg_rating else None,
        }
    finally:
        conn.close()


def execute_readonly_sql(sql: str, timeout: int = 5, max_rows: int = 500) -> dict:
    """Execute a read-only SQL query. Raises ValueError for non-SELECT statements."""
    stripped = sql.strip().rstrip(";").strip()
    if not stripped.upper().startswith("SELECT"):
        raise ValueError("Only SELECT statements are allowed")

    conn = get_conn()
    try:
        conn.execute(f"PRAGMA busy_timeout = {timeout * 1000}")
        cursor = conn.execute(stripped)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchmany(max_rows + 1)
        truncated = len(rows) > max_rows
        if truncated:
            rows = rows[:max_rows]
        return {
            "columns": columns,
            "rows": [list(r) for r in rows],
            "row_count": len(rows),
            "truncated": truncated,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Translation queue functions
# ---------------------------------------------------------------------------

def get_pending_translations(limit: int = 20) -> list[dict]:
    """Fetch reviews needing translation, newest first.

    Returns dicts with id, headline, body, rating, product_name, product_sku.
    """
    from qbu_crawler import config as _cfg
    max_retries = _cfg.TRANSLATE_MAX_RETRIES
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT r.id, r.headline, r.body, r.rating,
                      p.name AS product_name, p.sku AS product_sku
               FROM reviews r JOIN products p ON r.product_id = p.id
               WHERE r.translate_status IS NULL
                  OR (r.translate_status = 'failed' AND r.translate_retries < ?)
               ORDER BY r.scraped_at DESC
               LIMIT ?""",
            (max_retries, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_translation(review_id: int, headline_cn: str, body_cn: str, status: str) -> None:
    """Mark a review as translated."""
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE reviews SET headline_cn = ?, body_cn = ?, translate_status = ? WHERE id = ?",
            (headline_cn, body_cn, status, review_id),
        )
        conn.commit()
    finally:
        conn.close()


def increment_translate_retries(review_id: int, max_retries: int = 3) -> None:
    """Increment retry counter; mark 'skipped' if max reached."""
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE reviews SET translate_retries = translate_retries + 1 WHERE id = ?",
            (review_id,),
        )
        conn.execute(
            "UPDATE reviews SET translate_status = 'skipped' WHERE id = ? AND translate_retries >= ?",
            (review_id, max_retries),
        )
        conn.execute(
            "UPDATE reviews SET translate_status = 'failed' WHERE id = ? AND translate_retries < ?",
            (review_id, max_retries),
        )
        conn.commit()
    finally:
        conn.close()


def reset_skipped_translations() -> int:
    """Reset all skipped reviews back to pending (NULL). Returns count."""
    conn = get_conn()
    try:
        cursor = conn.execute(
            "UPDATE reviews SET translate_status = NULL, translate_retries = 0 WHERE translate_status = 'skipped'"
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def get_translate_stats(since: str | None = None) -> dict:
    """Return translation status counts. Optional since filter (YYYY-MM-DD or full timestamp)."""
    conn = get_conn()
    try:
        where = ""
        params: list = []
        if since:
            where = "WHERE scraped_at >= ?"
            params = [since]

        total = conn.execute(f"SELECT COUNT(*) FROM reviews {where}", params).fetchone()[0]

        def _count(status_val, is_null=False):
            if is_null:
                cond = "translate_status IS NULL"
                p = list(params)
            else:
                cond = "translate_status = ?"
                p = list(params) + [status_val]
            w = f"WHERE {cond}" if not where else f"{where} AND {cond}"
            return conn.execute(f"SELECT COUNT(*) FROM reviews {w}", p).fetchone()[0]

        return {
            "total": total,
            "done": _count("done"),
            "pending": _count(None, is_null=True),
            "failed": _count("failed"),
            "skipped": _count("skipped"),
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Task completion tracking
# ---------------------------------------------------------------------------

def get_pending_completions() -> list[dict]:
    """Return terminal tasks that haven't been notified yet.
    Includes tasks with empty reply_to (agent forgot to pass it) —
    heartbeat will use a default notification target for those."""
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT id, type, status, params, result, error,
                      created_at, finished_at, reply_to
               FROM tasks
               WHERE status IN ('completed', 'failed', 'cancelled')
                 AND notified_at IS NULL
                 AND finished_at >= datetime('now', '-24 hours')
               ORDER BY finished_at ASC""",
        ).fetchall()
        tasks = []
        for row in rows:
            d = dict(row)
            for k in ("params", "result"):
                if d.get(k):
                    d[k] = _json.loads(d[k])
            tasks.append(d)
        return tasks
    finally:
        conn.close()


def mark_task_notified(task_ids: list[str]) -> int:
    """Mark tasks as notified. Returns count of updated rows."""
    if not task_ids:
        return 0
    conn = get_conn()
    try:
        placeholders = ",".join("?" for _ in task_ids)
        cursor = conn.execute(
            f"UPDATE tasks SET notified_at = {_NOW_SHANGHAI} WHERE id IN ({placeholders})",
            task_ids,
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def enqueue_notification(notification: dict) -> dict:
    """Insert an outbox row or return the existing row for the same dedupe key."""
    conn = get_conn()
    try:
        conn.execute(
            """
            INSERT INTO notification_outbox (
                kind, channel, target, payload, dedupe_key, payload_hash,
                status, claimed_at, claim_token, lease_until, bridge_request_id,
                last_http_status, last_exit_code, last_error, attempts, delivered_at,
                created_at, updated_at
            ) VALUES (
                :kind, :channel, :target, :payload, :dedupe_key, :payload_hash,
                :status, :claimed_at, :claim_token, :lease_until, :bridge_request_id,
                :last_http_status, :last_exit_code, :last_error, :attempts, :delivered_at,
                :created_at, :updated_at
            )
            ON CONFLICT(dedupe_key) DO NOTHING
            """,
            {
                "kind": notification["kind"],
                "channel": notification.get("channel", "dingtalk"),
                "target": notification["target"],
                "payload": _json.dumps(notification.get("payload")),
                "dedupe_key": notification["dedupe_key"],
                "payload_hash": notification["payload_hash"],
                "status": notification.get("status", "pending"),
                "claimed_at": notification.get("claimed_at"),
                "claim_token": notification.get("claim_token"),
                "lease_until": notification.get("lease_until"),
                "bridge_request_id": notification.get("bridge_request_id"),
                "last_http_status": notification.get("last_http_status"),
                "last_exit_code": notification.get("last_exit_code"),
                "last_error": notification.get("last_error"),
                "attempts": notification.get("attempts", 0),
                "delivered_at": notification.get("delivered_at"),
                "created_at": notification.get("created_at"),
                "updated_at": notification.get("updated_at"),
            },
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM notification_outbox WHERE dedupe_key = ?",
            (notification["dedupe_key"],),
        ).fetchone()
        return _decode_json_fields(row, ("payload",))
    finally:
        conn.close()


def get_notification(notification_id: int) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM notification_outbox WHERE id = ?",
            (notification_id,),
        ).fetchone()
        return _decode_json_fields(row, ("payload",))
    finally:
        conn.close()


def claim_next_notification(
    claim_token: str,
    claimed_at: str,
    lease_until: str,
) -> dict | None:
    """Claim the oldest pending outbox row for a notifier worker."""
    conn = get_conn()
    try:
        row = conn.execute(
            """
            SELECT * FROM notification_outbox
            WHERE status IN ('pending', 'failed')
            ORDER BY created_at ASC, id ASC
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return None

        cursor = conn.execute(
            """
            UPDATE notification_outbox
            SET status = 'claimed',
                claimed_at = ?,
                claim_token = ?,
                lease_until = ?,
                updated_at = ?
            WHERE id = ?
              AND status IN ('pending', 'failed')
            """,
            (claimed_at, claim_token, lease_until, claimed_at, row["id"]),
        )
        conn.commit()
        if cursor.rowcount == 0:
            return None
        claimed = conn.execute(
            "SELECT * FROM notification_outbox WHERE id = ?",
            (row["id"],),
        ).fetchone()
        return _decode_json_fields(claimed, ("payload",))
    finally:
        conn.close()


def reclaim_stale_notifications(now: str) -> int:
    """Return expired claims back to pending so another worker can retry them."""
    conn = get_conn()
    try:
        cursor = conn.execute(
            """
            UPDATE notification_outbox
            SET status = 'pending',
                claim_token = NULL,
                claimed_at = NULL,
                lease_until = NULL,
                updated_at = ?
            WHERE status = 'claimed'
              AND lease_until IS NOT NULL
              AND lease_until < ?
            """,
            (now, now),
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def mark_notification_sent(
    notification_id: int,
    delivered_at: str,
    bridge_request_id: str = "",
    http_status: int | None = None,
) -> bool:
    conn = get_conn()
    try:
        cursor = conn.execute(
            """
            UPDATE notification_outbox
            SET status = 'sent',
                delivered_at = ?,
                bridge_request_id = ?,
                last_http_status = ?,
                claim_token = NULL,
                claimed_at = NULL,
                lease_until = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (delivered_at, bridge_request_id or None, http_status, delivered_at, notification_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def mark_notification_failure(
    notification_id: int,
    failed_at: str,
    error_message: str,
    retryable: bool,
    max_attempts: int,
    http_status: int | None = None,
    exit_code: int | None = None,
) -> str:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT attempts FROM notification_outbox WHERE id = ?",
            (notification_id,),
        ).fetchone()
        attempts = (row["attempts"] if row else 0) + 1
        next_status = "failed" if retryable and attempts < max_attempts else "deadletter"
        conn.execute(
            """
            UPDATE notification_outbox
            SET status = ?,
                attempts = ?,
                last_error = ?,
                last_http_status = ?,
                last_exit_code = ?,
                claim_token = NULL,
                claimed_at = NULL,
                lease_until = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (next_status, attempts, error_message, http_status, exit_code, failed_at, notification_id),
        )
        conn.commit()
        return next_status
    finally:
        conn.close()


def cleanup_old_notifications(retention_days: int = 30) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    conn = get_conn()
    try:
        cursor = conn.execute(
            """
            DELETE FROM notification_outbox
            WHERE status IN ('delivered', 'deadletter')
              AND updated_at < ?
            """,
            (cutoff,),
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Review analysis CRUD
# ---------------------------------------------------------------------------

def save_review_analysis(
    review_id: int,
    sentiment: str,
    sentiment_score: float | None = None,
    labels: list | None = None,
    features: list | None = None,
    insight_cn: str | None = None,
    insight_en: str | None = None,
    llm_model: str | None = None,
    prompt_version: str = "v1",
    token_usage: int | None = None,
    analyzed_at: str | None = None,
    impact_category: str | None = None,      # NEW
    failure_mode: str | None = None,          # NEW
) -> None:
    """UPSERT a review analysis row. Conflicts on (review_id, prompt_version) update all fields.

    analyzed_at: explicit timestamp string (e.g. "2026-01-01 00:00:00"). When omitted,
    defaults to the current local time formatted as "%Y-%m-%d %H:%M:%S".
    """
    ts = analyzed_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn()
    try:
        conn.execute(
            """
            INSERT INTO review_analysis
                (review_id, sentiment, sentiment_score, labels, features,
                 insight_cn, insight_en, llm_model, prompt_version, token_usage, analyzed_at,
                 impact_category, failure_mode)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(review_id, prompt_version) DO UPDATE SET
                sentiment       = excluded.sentiment,
                sentiment_score = excluded.sentiment_score,
                labels          = excluded.labels,
                features        = excluded.features,
                insight_cn      = excluded.insight_cn,
                insight_en      = excluded.insight_en,
                llm_model       = excluded.llm_model,
                token_usage     = excluded.token_usage,
                analyzed_at     = excluded.analyzed_at,
                impact_category = excluded.impact_category,
                failure_mode    = excluded.failure_mode
            """,
            (
                review_id,
                sentiment,
                sentiment_score,
                _json.dumps(labels or [], ensure_ascii=False),
                _json.dumps(features or [], ensure_ascii=False),
                insight_cn,
                insight_en,
                llm_model,
                prompt_version,
                token_usage,
                ts,
                impact_category,    # NEW
                failure_mode,       # NEW
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_review_analysis(review_id: int) -> dict | None:
    """Return the latest analysis row for a review, or None."""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM review_analysis WHERE review_id = ? ORDER BY analyzed_at DESC LIMIT 1",
            (review_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_reviews_with_analysis(
    review_ids: list[int] | None = None,
    since: str | None = None,
) -> list[dict]:
    """Bulk query reviews joined with products and latest review_analysis.

    Returns dicts with fields from reviews, products, and review_analysis tables.
    """
    conditions: list[str] = []
    params: list = []

    if review_ids:
        placeholders = ",".join("?" for _ in review_ids)
        conditions.append(f"r.id IN ({placeholders})")
        params.extend(review_ids)

    if since:
        conditions.append("r.scraped_at >= ?")
        params.append(since)

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    sql = f"""
        SELECT
            r.id,
            r.headline,
            r.body,
            r.rating,
            r.date_published,
            r.images,
            r.headline_cn,
            r.body_cn,
            p.name  AS product_name,
            p.sku   AS product_sku,
            p.site,
            p.ownership,
            p.price,
            ra.sentiment,
            ra.sentiment_score,
            ra.labels   AS analysis_labels,
            ra.features AS analysis_features,
            ra.insight_cn AS analysis_insight_cn,
            ra.insight_en AS analysis_insight_en
        FROM reviews r
        JOIN products p ON r.product_id = p.id
        LEFT JOIN review_analysis ra ON ra.review_id = r.id
            AND ra.analyzed_at = (
                SELECT MAX(ra2.analyzed_at)
                FROM review_analysis ra2
                WHERE ra2.review_id = r.id
            )
        {where_clause}
        ORDER BY r.scraped_at DESC
    """
    conn = get_conn()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_product_snapshots(sku, days=30):
    """Get recent product snapshots by SKU, ordered chronologically."""
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT ps.price, ps.stock_status, ps.review_count, ps.rating, ps.scraped_at
            FROM product_snapshots ps
            JOIN products p ON ps.product_id = p.id
            WHERE p.sku = ?
              AND ps.scraped_at >= datetime('now', ? || ' days')
            ORDER BY ps.scraped_at ASC
            """,
            (sku, f"-{days}"),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
