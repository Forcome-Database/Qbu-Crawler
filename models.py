import hashlib
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
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
    """)
    # 兼容旧表：添加缺失的列
    migrations = [
        "ALTER TABLE reviews ADD COLUMN images TEXT",
        "ALTER TABLE reviews ADD COLUMN body_hash TEXT",
        "ALTER TABLE reviews ADD COLUMN scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "ALTER TABLE products ADD COLUMN site TEXT NOT NULL DEFAULT 'basspro'",
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
        INSERT INTO products (url, site, name, sku, price, stock_status, review_count, rating, scraped_at)
        VALUES (:url, :site, :name, :sku, :price, :stock_status, :review_count, :rating, CURRENT_TIMESTAMP)
        ON CONFLICT(url) DO UPDATE SET
            site = excluded.site,
            name = excluded.name,
            sku = excluded.sku,
            price = excluded.price,
            stock_status = excluded.stock_status,
            review_count = excluded.review_count,
            rating = excluded.rating,
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
    返回新增评论数
    """
    conn = get_conn()
    new_count = 0
    for r in reviews:
        body = r.get("body") or ""
        bh = _body_hash(body)
        try:
            conn.execute("""
                INSERT INTO reviews (product_id, author, headline, body, body_hash, rating, date_published, images)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (product_id, r.get("author"), r.get("headline"), body, bh,
                  r.get("rating"), r.get("date_published"), r.get("images")))
            new_count += 1
        except sqlite3.IntegrityError:
            pass  # 已存在，跳过
    conn.commit()
    conn.close()
    return new_count
