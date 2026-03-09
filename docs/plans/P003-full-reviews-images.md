# 全量评论抓取 + 评论图片存储 实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 从 BV Shadow DOM 提取全部评论（通过 LOAD MORE 循环加载），下载评论图片到 MinIO，并在数据库中记录图片地址。

**Architecture:** 废弃现有 BV JSON-LD 评论提取，改为：点击 Reviews Accordion 展开 → 循环点击 LOAD MORE 加载全部评论 → 从 Shadow DOM 提取评论数据（含图片 URL）→ 下载图片到 MinIO → 保存到 SQLite。产品基本信息和评分/评论数仍从 JSON-LD 获取。

**Tech Stack:** DrissionPage（Shadow DOM 操作）、minio（对象存储）、python-dotenv（环境变量）、requests（图片下载）、SQLite

---

### Task 1: 新增依赖和环境配置

**Files:**
- Modify: `pyproject.toml`
- Create: `.env`
- Create: `.env.example`
- Modify: `config.py`

**Step 1: 更新 pyproject.toml 添加新依赖**

```toml
[project]
name = "basspro-scraper"
version = "0.1.0"
description = "Bass Pro Shops 产品爬虫服务"
requires-python = ">=3.10"
dependencies = [
    "drissionpage",
    "minio",
    "python-dotenv",
    "requests",
]
```

**Step 2: 创建 .env 文件**

```env
MINIO_ENDPOINT=192.168.16.116
MINIO_PORT=9000
MINIO_USE_SSL=false
MINIO_ACCESS_KEY=iG7QoobeCNeXpMwUYJFy
MINIO_SECRET_KEY=wOab6oPSUnkeKXXqqoznGjZBBfWLXd1gh80jjT9P
MINIO_BUCKET=qbu-crawler
MINIO_PUBLIC_URL=https://minio-api.forcome.com
```

**Step 3: 创建 .env.example 文件**

```env
MINIO_ENDPOINT=192.168.16.116
MINIO_PORT=9000
MINIO_USE_SSL=false
MINIO_ACCESS_KEY=your_access_key
MINIO_SECRET_KEY=your_secret_key
MINIO_BUCKET=qbu-crawler
MINIO_PUBLIC_URL=https://minio-api.forcome.com
```

**Step 4: 在 .gitignore 中添加 .env**

确保 `.env` 在 `.gitignore` 中。

**Step 5: 修改 config.py，添加 MinIO 配置**

在 `config.py` 头部加载 dotenv，添加 MinIO 配置项：

```python
import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "products.db")

os.makedirs(DATA_DIR, exist_ok=True)

# ... 原有浏览器配置保持不变 ...

# MinIO 配置
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "192.168.16.116")
MINIO_PORT = int(os.getenv("MINIO_PORT", "9000"))
MINIO_USE_SSL = os.getenv("MINIO_USE_SSL", "false").lower() == "true"
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "qbu-crawler")
MINIO_PUBLIC_URL = os.getenv("MINIO_PUBLIC_URL", "https://minio-api.forcome.com")
```

**Step 6: 安装依赖**

Run: `uv sync`

**Step 7: Commit**

```bash
git add pyproject.toml .env.example config.py .gitignore
git commit -m "feat: 添加 MinIO/dotenv/requests 依赖和环境配置"
```

---

### Task 2: MinIO 客户端模块

**Files:**
- Create: `minio_client.py`

**Step 1: 创建 minio_client.py**

```python
import hashlib
import io
from datetime import datetime

import requests
from minio import Minio
from config import (
    MINIO_ENDPOINT, MINIO_PORT, MINIO_USE_SSL,
    MINIO_ACCESS_KEY, MINIO_SECRET_KEY,
    MINIO_BUCKET, MINIO_PUBLIC_URL,
)


def _get_client() -> Minio:
    return Minio(
        f"{MINIO_ENDPOINT}:{MINIO_PORT}",
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=MINIO_USE_SSL,
    )


def upload_image(image_url: str) -> str | None:
    """下载图片并上传到 MinIO，返回公开访问 URL。
    如果下载或上传失败，返回 None。
    """
    try:
        resp = requests.get(image_url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"  [MinIO] 图片下载失败: {e}")
        return None

    # 用 URL hash 做文件名，避免重复上传
    url_hash = hashlib.md5(image_url.encode()).hexdigest()
    # 检测图片格式
    content_type = resp.headers.get("Content-Type", "image/jpeg")
    ext = "jpg"
    if "png" in content_type:
        ext = "png"
    elif "webp" in content_type:
        ext = "webp"

    month = datetime.now().strftime("%Y-%m")
    object_name = f"images/{month}/{url_hash}.{ext}"

    client = _get_client()
    # 确保 bucket 存在
    if not client.bucket_exists(MINIO_BUCKET):
        client.make_bucket(MINIO_BUCKET)

    data = io.BytesIO(resp.content)
    try:
        client.put_object(
            MINIO_BUCKET,
            object_name,
            data,
            length=len(resp.content),
            content_type=content_type,
        )
    except Exception as e:
        print(f"  [MinIO] 上传失败: {e}")
        return None

    public_url = f"{MINIO_PUBLIC_URL}/{MINIO_BUCKET}/{object_name}"
    return public_url
```

**Step 2: 验证 MinIO 连接**

Run: `uv run python -c "from minio_client import _get_client; c = _get_client(); print('Buckets:', [b.name for b in c.list_buckets()])"`

Expected: 能看到 bucket 列表（含 `qbu-crawler`）

**Step 3: Commit**

```bash
git add minio_client.py
git commit -m "feat: 添加 MinIO 客户端，支持图片上传和 URL 去重"
```

---

### Task 3: 数据库 reviews 表添加 images 字段

**Files:**
- Modify: `models.py`

**Step 1: 修改 init_db，添加 images 字段**

在 `init_db()` 的 reviews 表 CREATE 语句中添加 `images TEXT`（JSON 数组）：

```sql
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    author TEXT,
    headline TEXT,
    body TEXT,
    rating REAL,
    date_published TEXT,
    images TEXT,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
);
```

同时在 `init_db()` 末尾添加兼容旧表的 ALTER：

```python
# 兼容已有数据库：如果 images 列不存在则添加
try:
    conn.execute("ALTER TABLE reviews ADD COLUMN images TEXT")
except sqlite3.OperationalError:
    pass  # 列已存在
```

**Step 2: 修改 save_reviews，保存 images 字段**

```python
def save_reviews(product_id: int, reviews: list):
    conn = get_conn()
    conn.execute("DELETE FROM reviews WHERE product_id = ?", (product_id,))
    for r in reviews:
        conn.execute("""
            INSERT INTO reviews (product_id, author, headline, body, rating, date_published, images)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (product_id, r.get("author"), r.get("headline"), r.get("body"),
              r.get("rating"), r.get("date_published"), r.get("images")))
    conn.commit()
    conn.close()
```

**Step 3: 验证数据库迁移**

Run: `uv run python -c "from models import init_db; init_db(); print('OK')"`

**Step 4: Commit**

```bash
git add models.py
git commit -m "feat: reviews 表添加 images 字段存储评论图片 URL"
```

---

### Task 4: 重写评论提取逻辑（Shadow DOM）

**Files:**
- Modify: `scraper.py`

这是核心改动。废弃 `_parse_bv_reviews()` 和 `_wait_for_bv_data()` 中等待 `reviews-data` 的逻辑，新增从 Shadow DOM 提取评论的方法。

**Step 1: 新增 `_click_reviews_tab(tab)` 方法**

点击 Reviews Accordion 展开评论区：

```python
def _click_reviews_tab(self, tab):
    """点击 Reviews Accordion 展开评论区"""
    # Reviews 在第 9 个 slot（styles_Slot9__njiM6）
    tab.run_js("""
        const accordions = document.querySelectorAll('.styles_AccordionWrapper__JYyM_');
        for (const acc of accordions) {
            const title = acc.querySelector('.styles_Title__zBr7o');
            if (title && title.textContent.includes('Reviews')) {
                title.click();
                break;
            }
        }
    """)
    # 等待内容展开（Body 不再含 Closed class）
    time.sleep(1)
```

**Step 2: 新增 `_load_all_reviews(tab)` 方法**

循环点击 LOAD MORE 直到消失：

```python
def _load_all_reviews(self, tab):
    """循环点击 LOAD MORE 按钮，直到加载全部评论"""
    max_clicks = 100  # 安全上限，防止无限循环
    for i in range(max_clicks):
        has_more = tab.run_js("""
            const container = document.querySelector('[data-bv-show="reviews"]');
            if (!container || !container.shadowRoot) return false;
            const btn = container.shadowRoot.querySelector('button[aria-label*="Load More"]');
            if (btn && btn.offsetHeight > 0) {
                btn.scrollIntoView({block: 'center'});
                btn.click();
                return true;
            }
            return false;
        """)
        if not has_more:
            break
        time.sleep(1.5)  # 等待新评论加载
```

**Step 3: 新增 `_extract_reviews_from_dom(tab)` 方法**

从 Shadow DOM 提取全部评论数据：

```python
def _extract_reviews_from_dom(self, tab) -> list:
    """从 BV Shadow DOM 提取所有评论数据"""
    self._click_reviews_tab(tab)
    self._load_all_reviews(tab)

    raw = tab.run_js("""
        const container = document.querySelector('[data-bv-show="reviews"]');
        if (!container || !container.shadowRoot) return '[]';
        const shadow = container.shadowRoot;

        // 找所有含作者按钮的 section（即评论卡片）
        const sections = Array.from(shadow.querySelectorAll('section')).filter(
            s => s.querySelector('button[class*="16dr7i1-6"]')
        );

        const reviews = [];
        const seen = new Set();  // 用 author+headline 去重（BV 有时重复渲染）
        for (const s of sections) {
            const authorEl = s.querySelector('button[class*="16dr7i1-6"]');
            const author = authorEl ? authorEl.textContent.trim() : '';
            const headlineEl = s.querySelector('h3');
            const headline = headlineEl ? headlineEl.textContent.trim() : '';

            const key = author + '|' + headline;
            if (seen.has(key)) continue;
            seen.add(key);

            // 正文
            const bodyEl = s.querySelector('p');
            const body = bodyEl ? bodyEl.textContent.trim() : '';

            // 评分：从 "X out of 5 stars." 提取
            const ratingEl = s.querySelector('span[class*="bm6gry"]');
            let rating = null;
            if (ratingEl) {
                const m = ratingEl.textContent.match(/(\\d+)\\s+out\\s+of\\s+5/);
                if (m) rating = parseInt(m[1]);
            }

            // 日期
            const dateEl = s.querySelector('span[class*="g3jej5"]');
            const date = dateEl ? dateEl.textContent.trim() : '';

            // 图片：评论内的 .photos-tile img
            const imgs = [];
            s.querySelectorAll('.photos-tile img').forEach(img => {
                const src = img.getAttribute('src');
                if (src && src.includes('photos-us.bazaarvoice.com')) {
                    imgs.push(src);
                }
            });

            reviews.push({author, headline, body, rating, date, images: imgs});
        }
        return JSON.stringify(reviews);
    """)
    return json.loads(raw) if isinstance(raw, str) else (raw or [])
```

**Step 4: 新增 `_process_review_images(reviews)` 方法**

下载图片到 MinIO，替换 URL：

```python
def _process_review_images(self, reviews: list) -> list:
    """下载评论图片到 MinIO，将 BV URL 替换为 MinIO URL"""
    from minio_client import upload_image

    for review in reviews:
        bv_urls = review.get("images", [])
        if not bv_urls:
            review["images"] = None
            continue
        minio_urls = []
        for url in bv_urls:
            minio_url = upload_image(url)
            if minio_url:
                minio_urls.append(minio_url)
        review["images"] = json.dumps(minio_urls) if minio_urls else None
    return reviews
```

**Step 5: 修改 `scrape()` 方法**

替换评论提取逻辑：

```python
# 删除这行：
# reviews = self._parse_bv_reviews(data.get("bvReviews"))

# 替换为：
reviews = self._extract_reviews_from_dom(tab)
reviews = self._process_review_images(reviews)
```

同时 `_wait_for_bv_data()` 简化为只等 `bvloader-summary`（评分摘要仍需要），不再等 `reviews-data`。

**Step 6: 更新评论输出格式**

`date_published` 字段对齐：Shadow DOM 中的日期格式为相对时间如 "10 days ago"，直接存入 `date_published`。

评论字典结构变为：
```python
{
    "author": "Hershel",
    "headline": "Great scales...",
    "body": "Yes, I recommend...",
    "rating": 4.0,
    "date_published": "10 days ago",
    "images": '["https://minio-api.forcome.com/qbu-crawler/images/2026-03/abc.jpg"]'  # JSON string or None
}
```

**Step 7: Commit**

```bash
git add scraper.py
git commit -m "feat: 从 Shadow DOM 提取全量评论，支持 LOAD MORE 和图片下载"
```

---

### Task 5: 更新 config.py 禁用 NO_IMAGES 说明 & _wait_for_bv_data 简化

**Files:**
- Modify: `scraper.py`（`_wait_for_bv_data` 方法）

**Step 1: 简化 `_wait_for_bv_data`**

只等 `bvloader-summary`（评分/评论数），不再等 `reviews-data`：

```python
def _wait_for_bv_data(self, tab):
    """轮询等待 BV 评分摘要数据注入（仅 summary，reviews 从 DOM 获取）"""
    deadline = time.time() + BV_WAIT_TIMEOUT
    while time.time() < deadline:
        result = tab.run_js(
            "return document.querySelector('#bv-jsonld-bvloader-summary') ? 1 : 0;"
        )
        if result:
            break
        time.sleep(BV_POLL_INTERVAL)
```

**Step 2: 删除 `_parse_bv_reviews` 方法**

不再使用，可以直接删除。

**Step 3: 清理 `scrape()` 中的 bvReviews 相关代码**

JS 提取脚本中 `bvReviews` 相关代码可保留（不影响功能）或删除（更干净）。

**Step 4: Commit**

```bash
git add scraper.py
git commit -m "refactor: 简化 BV 等待逻辑，移除 JSON-LD 评论解析"
```

---

### Task 6: 端到端测试

**Step 1: 测试有 LOAD MORE + 有图片的产品**

Run: `uv run python main.py https://www.basspro.com/p/bass-pro-shops-xps-digital-fish-scale`

Expected:
- 所有评论被加载（远超之前的 8 条限制）
- 带图片的评论显示 MinIO URL
- 数据库 reviews 表中 images 字段有值

**Step 2: 测试无 LOAD MORE 的产品**

Run: `uv run python main.py https://www.basspro.com/p/rapala-fishermans-multi-tool`

Expected:
- 4 条评论正常提取
- 无图片的评论 images 为 NULL

**Step 3: 验证数据库**

Run: `uv run python -c "import sqlite3; c=sqlite3.connect('data/products.db'); [print(r) for r in c.execute('SELECT author, headline, images FROM reviews LIMIT 10').fetchall()]"`

**Step 4: 验证 MinIO 图片可访问**

检查输出中的 MinIO URL 是否可以在浏览器中打开。

**Step 5: Commit（如有修复）**

```bash
git add -A
git commit -m "fix: 端到端测试修复"
```

---

### Task 7: 更新 CLAUDE.md 文档

**Files:**
- Modify: `CLAUDE.md`

更新以下内容：
- 项目结构中添加 `minio_client.py` 和 `.env`
- 数据提取策略中添加 Shadow DOM 评论提取说明
- 开发注意事项中添加 Shadow DOM 相关注意事项
- 配置项表中添加 MinIO 配置

**Commit:**

```bash
git add CLAUDE.md
git commit -m "docs: 更新 CLAUDE.md，添加 Shadow DOM 评论和 MinIO 说明"
```
