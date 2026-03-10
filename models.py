import hashlib
import json as _json
import sqlite3
from config import DB_PATH


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
            started_at   TIMESTAMP,
            finished_at  TIMESTAMP
        );
    """)
    # 兼容旧表：添加缺失的列
    migrations = [
        "ALTER TABLE reviews ADD COLUMN images TEXT",
        "ALTER TABLE reviews ADD COLUMN body_hash TEXT",
        "ALTER TABLE reviews ADD COLUMN scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "ALTER TABLE products ADD COLUMN site TEXT NOT NULL DEFAULT 'basspro'",
        "ALTER TABLE products ADD COLUMN ownership TEXT NOT NULL DEFAULT 'competitor'",
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
    conn.close()


def _body_hash(body: str | None) -> str:
    """正文 MD5 前 16 位，用于去重"""
    if not body:
        return ""
    return hashlib.md5(body.encode()).hexdigest()[:16]


def save_product(data: dict) -> int:
    conn = get_conn()
    cursor = conn.execute("""
        INSERT INTO products (url, site, name, sku, price, stock_status, review_count, rating, ownership, scraped_at)
        VALUES (:url, :site, :name, :sku, :price, :stock_status, :review_count, :rating, :ownership, CURRENT_TIMESTAMP)
        ON CONFLICT(url) DO UPDATE SET
            site = excluded.site,
            name = excluded.name,
            sku = excluded.sku,
            price = excluded.price,
            stock_status = excluded.stock_status,
            review_count = excluded.review_count,
            rating = excluded.rating,
            ownership = excluded.ownership,
            scraped_at = CURRENT_TIMESTAMP
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
    conn.execute("""
        INSERT INTO product_snapshots (product_id, price, stock_status, review_count, rating)
        VALUES (?, ?, ?, ?, ?)
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
        try:
            conn.execute("""
                INSERT INTO reviews (product_id, author, headline, body, body_hash, rating, date_published, images)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (product_id, r.get("author"), r.get("headline"), body, bh,
                  r.get("rating"), r.get("date_published"), images))
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
                                  created_at, started_at, finished_at)
               VALUES (:id, :type, :status, :params, :progress, :result, :error,
                       :created_at, :started_at, :finished_at)
               ON CONFLICT(id) DO UPDATE SET
                   status=excluded.status, progress=excluded.progress,
                   result=excluded.result, error=excluded.error,
                   started_at=excluded.started_at, finished_at=excluded.finished_at
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
                "started_at": task_dict.get("started_at"),
                "finished_at": task_dict.get("finished_at"),
            },
        )
        conn.commit()
    finally:
        conn.close()


def get_task(task_id: str) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        for k in ("params", "progress", "result"):
            if d.get(k):
                d[k] = _json.loads(d[k])
        return d
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
            d = dict(row)
            for k in ("params", "progress", "result"):
                if d.get(k):
                    d[k] = _json.loads(d[k])
            tasks.append(d)
        return tasks, total
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
        total_products = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        total_reviews = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]

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
