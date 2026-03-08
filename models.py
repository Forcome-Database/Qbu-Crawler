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
            name TEXT,
            sku TEXT,
            price REAL,
            stock_status TEXT,
            review_count INTEGER,
            rating REAL,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            author TEXT,
            headline TEXT,
            body TEXT,
            rating REAL,
            date_published TEXT,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
        );
    """)
    conn.close()


def save_product(data: dict) -> int:
    conn = get_conn()
    cursor = conn.execute("""
        INSERT INTO products (url, name, sku, price, stock_status, review_count, rating, scraped_at)
        VALUES (:url, :name, :sku, :price, :stock_status, :review_count, :rating, CURRENT_TIMESTAMP)
        ON CONFLICT(url) DO UPDATE SET
            name = excluded.name,
            sku = excluded.sku,
            price = excluded.price,
            stock_status = excluded.stock_status,
            review_count = excluded.review_count,
            rating = excluded.rating,
            scraped_at = CURRENT_TIMESTAMP
    """, data)
    # 获取产品 ID（无论是插入还是更新）
    product_id = cursor.lastrowid
    if product_id == 0:
        row = conn.execute("SELECT id FROM products WHERE url = ?", (data["url"],)).fetchone()
        product_id = row["id"]
    conn.commit()
    conn.close()
    return product_id


def save_reviews(product_id: int, reviews: list):
    conn = get_conn()
    # 先删除该产品的旧评论
    conn.execute("DELETE FROM reviews WHERE product_id = ?", (product_id,))
    for r in reviews:
        conn.execute("""
            INSERT INTO reviews (product_id, author, headline, body, rating, date_published)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (product_id, r.get("author"), r.get("headline"), r.get("body"),
              r.get("rating"), r.get("date_published")))
    conn.commit()
    conn.close()
