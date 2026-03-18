# Waltons.com 采集器实施计划

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Qbu-Crawler 新增 waltons.com 采集器，支持产品详情页抓取和分类页 URL 采集。

**Architecture:** 创建 `WaltonsScraper(BaseScraper)` 继承基类，JSON-LD 优先提取产品数据，TrustSpot DOM 提取评论并支持翻页。列表页使用 BigCommerce 标准 URL 分页。

**Tech Stack:** Python 3.10+, DrissionPage, JSON-LD 解析, TrustSpot DOM 选择器

**Spec:** `docs/superpowers/specs/2026-03-14-waltons-scraper-design.md`

---

## Chunk 1: 核心采集器实现

### Task 1: SITE_MAP 注册

**Files:**
- Modify: `scrapers/__init__.py:3-6`

- [ ] **Step 1: 添加 waltons.com 双域名条目到 SITE_MAP**

在 `SITE_MAP` 字典中追加两条记录（`waltons.com` 和 `www.waltons.com`），共享同一 site key `"waltons"`：

```python
SITE_MAP = {
    "www.basspro.com": ("basspro", "scrapers.basspro", "BassProScraper"),
    "www.meatyourmaker.com": ("meatyourmaker", "scrapers.meatyourmaker", "MeatYourMakerScraper"),
    "www.waltons.com": ("waltons", "scrapers.waltons", "WaltonsScraper"),
    "waltons.com": ("waltons", "scrapers.waltons", "WaltonsScraper"),
}
```

- [ ] **Step 2: 验证导入**

Run: `uv run python -c "from scrapers import get_site_key, get_scraper; print(get_site_key('https://waltons.com/test')); print(get_site_key('https://www.waltons.com/test'))"`
Expected: 两行都输出 `waltons`（get_scraper 会因类不存在而失败，这是正常的）

- [ ] **Step 3: Commit**

```bash
git add scrapers/__init__.py
git commit -m "feat(waltons): register waltons.com in SITE_MAP"
```

---

### Task 2: WaltonsScraper 骨架 + JSON-LD 产品数据提取

**Files:**
- Create: `scrapers/waltons.py`

- [ ] **Step 1: 创建 WaltonsScraper 类骨架和 JSON-LD 提取**

创建 `scrapers/waltons.py`，包含：
- `WaltonsScraper(BaseScraper)` 类
- `_extract_jsonld(tab)` 内部方法：通过 `tab.run_js()` 提取所有 JSON-LD，按内容匹配合并 Product 对象
- `scrape(url)` 方法的产品数据提取部分（评论部分暂返回空列表）

```python
import hashlib
import json
import logging
import time
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse

from scrapers.base import BaseScraper
from config import BV_WAIT_TIMEOUT, BV_POLL_INTERVAL, MAX_REVIEWS, PAGE_LOAD_TIMEOUT

logger = logging.getLogger(__name__)


class WaltonsScraper(BaseScraper):

    def scrape(self, url: str) -> dict:
        self._maybe_restart_browser()
        tab = self.browser.latest_tab
        tab.get(url)
        tab.wait.ele_displayed('tag:h1', timeout=15)
        self._check_url_match(tab, url)

        result = {
            "url": url,
            "site": "waltons",
            "name": None,
            "sku": None,
            "price": None,
            "stock_status": None,
            "review_count": None,
            "rating": None,
        }

        # ── JSON-LD 提取（按内容匹配，不依赖位置索引）──
        ld_product, ld_reviews_raw = self._extract_jsonld(tab)

        if ld_product:
            result["name"] = ld_product.get("name")
            result["sku"] = ld_product.get("sku")
            # offers 可能是 dict 或 list（多变体产品）
            offers = ld_product.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            result["price"] = self._to_float(offers.get("price"))
            avail = offers.get("availability", "")
            result["stock_status"] = (
                "in_stock" if "InStock" in avail else "out_of_stock"
            )
            agg = ld_product.get("aggregateRating") or {}
            result["rating"] = self._to_float(agg.get("ratingValue"))
            result["review_count"] = self._to_int(agg.get("reviewCount"))

        # 无评论产品默认值
        if result["review_count"] is None:
            result["review_count"] = 0
        if not result["stock_status"]:
            result["stock_status"] = "unknown"

        # ── DOM 兜底 ──
        if not result["name"]:
            h1 = tab.ele('tag:h1', timeout=3)
            if h1:
                result["name"] = h1.text.strip()

        if not result["sku"]:
            result["sku"] = tab.run_js("""
                const el = document.querySelector('.productView-info-value--sku');
                return el ? el.textContent.trim() : null;
            """)

        if result["price"] is None:
            price_text = tab.run_js("""
                const el = document.querySelector('[data-product-price-without-tax]');
                return el ? el.textContent.trim() : null;
            """)
            if price_text:
                result["price"] = self._to_float(
                    price_text.replace("$", "").replace(",", "")
                )

        # ── 评论提取（Task 3 实现）──
        reviews = self._extract_all_reviews(tab, ld_reviews_raw)
        reviews = self._process_review_images(reviews)

        self._increment_and_delay(tab)
        return {"product": result, "reviews": reviews}

    def _extract_jsonld(self, tab) -> tuple[dict | None, list]:
        """提取并合并多个 Product JSON-LD，返回 (合并后的 product_dict, reviews_list)"""
        raw = tab.run_js("""
            const results = [];
            document.querySelectorAll('script[type="application/ld+json"]').forEach(s => {
                try { results.push(JSON.parse(s.textContent)); } catch(e) {}
            });
            return JSON.stringify(results);
        """)
        jsonlds = json.loads(raw) if isinstance(raw, str) else (raw or [])

        merged = {}
        reviews_raw = []
        for item in jsonlds:
            if not isinstance(item, dict):
                continue
            if item.get("@type") != "Product":
                continue
            # 按字段存在性合并
            if "sku" in item and not merged.get("sku"):
                merged.update(item)
            if "aggregateRating" in item and "aggregateRating" not in merged:
                merged["aggregateRating"] = item["aggregateRating"]
            if "review" in item and not reviews_raw:
                reviews_raw = item["review"] or []
            if "offers" in item and "offers" not in merged:
                merged["offers"] = item["offers"]
            if "name" in item and "name" not in merged:
                merged["name"] = item["name"]

        return (merged if merged else None, reviews_raw)

    def _extract_all_reviews(self, tab, ld_reviews_raw: list) -> list:
        """占位：Task 3 实现"""
        return []

    def collect_product_urls(self, category_url: str, max_pages: int = 0) -> list[str]:
        """占位：Task 4 实现"""
        return []
```

- [ ] **Step 2: 验证产品数据提取**

Run: `uv run python -c "from scrapers.waltons import WaltonsScraper; s = WaltonsScraper(); r = s.scrape('https://waltons.com/waltons-22-meat-grinder/'); print(r['product']); s.close()"`

Expected: 输出包含 `name='Walton's #22 Meat Grinder'`, `sku='192242'`, `price=649.99`, `stock_status='in_stock'`, `rating=4.9`, `review_count=143`

- [ ] **Step 3: Commit**

```bash
git add scrapers/waltons.py
git commit -m "feat(waltons): add WaltonsScraper with JSON-LD product extraction"
```

---

### Task 3: TrustSpot 评论提取 + 翻页

**Files:**
- Modify: `scrapers/waltons.py` — 替换 `_extract_all_reviews` 占位方法

- [ ] **Step 1: 实现评论提取和翻页逻辑**

替换 `_extract_all_reviews` 方法，新增 `_wait_for_trustspot`、`_extract_page_reviews`、`_parse_ld_reviews` 辅助方法：

```python
    def _wait_for_trustspot(self, tab) -> bool:
        """轮询等待 TrustSpot 评论渲染，返回是否加载成功"""
        deadline = time.time() + BV_WAIT_TIMEOUT
        while time.time() < deadline:
            found = tab.run_js(
                "return document.querySelector('.trustspot-widget-review-block') ? 1 : 0;"
            )
            if found:
                return True
            time.sleep(BV_POLL_INTERVAL)
        logger.warning("  [TrustSpot] 评论加载超时，尝试从 JSON-LD 兜底")
        return False

    def _extract_page_reviews(self, tab) -> list[dict]:
        """从当前页 TrustSpot DOM 提取所有评论"""
        raw = tab.run_js("""
            const blocks = document.querySelectorAll('.trustspot-widget-review-block');
            const reviews = [];
            for (const block of blocks) {
                const author = block.querySelector('.result-box-header .user-name')
                    ?.textContent?.trim() || '';
                const dateStr = block.querySelector('.result-box-header .date span')
                    ?.textContent?.trim() || '';
                // 评分：计数填充的星星
                let rating = block.querySelectorAll('.ts-widget-review-star.filled').length;
                // 降级：从 .stars .ts-stars-1 的 title 属性解析（如 "4.9 stars"）
                if (!rating) {
                    const starsEl = block.querySelector('.stars .ts-stars-1[title]');
                    if (starsEl) {
                        const m = starsEl.title.match(/(\\d+(?:\\.\\d+)?)/);
                        if (m) rating = parseFloat(m[1]);
                    }
                }
                // 正文：.comment-box 中排除 aria-label span 后的文本
                const commentBox = block.querySelector('.comment-box');
                let body = '';
                if (commentBox) {
                    const spans = commentBox.querySelectorAll(':scope > span');
                    // 第二个 span 通常是正文（第一个是 aria-label）
                    if (spans.length >= 2) {
                        body = spans[1].textContent.trim();
                    } else {
                        body = commentBox.textContent.trim();
                    }
                }
                // 图片：排除社交/图标/头像图片
                const images = [];
                block.querySelectorAll('.description-block img').forEach(img => {
                    const src = img.src || '';
                    if (src && !src.includes('social/')
                        && !src.includes('star')
                        && !src.includes('icon')
                        && !src.includes('avatar')) {
                        images.push(src);
                    }
                });
                if (body) {
                    reviews.push({
                        author, headline: '', body, rating: rating || null,
                        date_published: dateStr, images
                    });
                }
            }
            return JSON.stringify(reviews);
        """)
        return json.loads(raw) if isinstance(raw, str) else (raw or [])

    @staticmethod
    def _parse_ld_reviews(ld_reviews_raw: list) -> list[dict]:
        """将 JSON-LD review 数组转换为统一格式（兜底用）"""
        reviews = []
        for r in ld_reviews_raw:
            if not isinstance(r, dict):
                continue
            author_obj = r.get("author") or {}
            rating_obj = r.get("reviewRating") or {}
            reviews.append({
                "author": author_obj.get("name", "") if isinstance(author_obj, dict) else str(author_obj),
                "headline": "",
                "body": r.get("reviewBody", ""),
                "rating": float(rating_obj.get("ratingValue")) if rating_obj.get("ratingValue") else None,
                "date_published": r.get("datePublished", ""),
                "images": [],
            })
        return reviews

    def _extract_all_reviews(self, tab, ld_reviews_raw: list) -> list:
        """提取全部评论：优先 TrustSpot DOM 翻页，失败则 JSON-LD 兜底"""
        if not self._wait_for_trustspot(tab):
            return self._parse_ld_reviews(ld_reviews_raw)

        all_reviews = []
        seen = set()
        max_pages = 100

        for page in range(max_pages):
            page_reviews = self._extract_page_reviews(tab)
            new_count = 0
            for r in page_reviews:
                # body_hash 用于去重（与 models.py 一致）
                body_hash = hashlib.md5(r["body"].encode()).hexdigest()[:16]
                key = (r["author"], body_hash)
                if key not in seen:
                    seen.add(key)
                    all_reviews.append(r)
                    new_count += 1

            logger.info(f"  [TrustSpot] 第 {page + 1} 页: 提取 {len(page_reviews)} 条, 新增 {new_count} 条")

            # MAX_REVIEWS 限制
            if MAX_REVIEWS and len(all_reviews) >= MAX_REVIEWS:
                logger.info(f"  [TrustSpot] 已达评论上限 {MAX_REVIEWS}，停止翻页")
                break

            # 翻页：点击 a.next-page
            has_next = tab.run_js("""
                const btn = document.querySelector('a.next-page');
                if (btn) { btn.click(); return true; }
                return false;
            """)
            if not has_next:
                break
            # 等待新一页评论渲染
            time.sleep(2)

        return all_reviews
```

注意：`hashlib` 已在文件顶部导入（Task 2 Step 1）。

- [ ] **Step 2: 验证评论提取**

Run: `uv run python -c "from scrapers.waltons import WaltonsScraper; s = WaltonsScraper(); r = s.scrape('https://waltons.com/waltons-22-meat-grinder/'); print(f'Reviews: {len(r[\"reviews\"])}'); print(r['reviews'][:2] if r['reviews'] else 'No reviews'); s.close()"`

Expected: 输出 `Reviews: 143`（或接近），前两条评论包含 author/body/rating/date_published

- [ ] **Step 3: 测试 eager 模式下 TrustSpot 是否正常加载**

在 Step 2 的输出中验证：
- 如果 reviews 数量 > 15 → TrustSpot DOM 加载正常，eager 模式 OK
- 如果 reviews 数量 ≤ 15 且日志有 `[TrustSpot] 评论加载超时` → 需要覆盖 `_build_options()` 切换 `normal` 模式

如果需要切换 `normal` 模式，参考 `scrapers/meatyourmaker.py:14-26` 的 `_build_options` 覆盖实现。

- [ ] **Step 4: Commit**

```bash
git add scrapers/waltons.py
git commit -m "feat(waltons): add TrustSpot review extraction with pagination"
```

---

### Task 4: 分类页 URL 采集

**Files:**
- Modify: `scrapers/waltons.py` — 替换 `collect_product_urls` 占位方法

- [ ] **Step 1: 实现分类页采集逻辑**

替换 `collect_product_urls` 方法：

```python
    def collect_product_urls(self, category_url: str, max_pages: int = 0) -> list[str]:
        """从分类页采集产品 URL — BigCommerce 标准 URL 分页"""
        tab = self.browser.latest_tab
        # 追加 limit=100 减少翻页，使用 urllib.parse 安全拼接
        parsed = urlparse(category_url)
        params = parse_qs(parsed.query)
        params["limit"] = ["100"]
        new_query = urlencode(params, doseq=True)
        start_url = urlunparse(parsed._replace(query=new_query))

        tab.get(start_url)
        tab.wait.doc_loaded(timeout=PAGE_LOAD_TIMEOUT)

        all_urls = []
        page = 1

        while True:
            page_urls = tab.run_js("""
                const urls = [];
                const seen = new Set();
                document.querySelectorAll('.productGrid .product .card-title a[href]').forEach(a => {
                    const href = a.href;
                    if (href && !seen.has(href)) { seen.add(href); urls.push(href); }
                });
                return JSON.stringify(urls);
            """)
            page_urls = json.loads(page_urls) if isinstance(page_urls, str) else (page_urls or [])

            if not page_urls:
                print(f"  第 {page} 页: 未找到产品链接")
                break

            all_urls.extend(page_urls)
            print(f"  第 {page} 页: 获取 {len(page_urls)} 个产品链接")

            if max_pages and page >= max_pages:
                break

            # 翻页：读取 .pagination-item--next a 的 href
            next_url = tab.run_js("""
                const a = document.querySelector('.pagination-item--next a');
                return a ? a.href : null;
            """)
            if not next_url:
                break

            tab.get(next_url)
            tab.wait.doc_loaded(timeout=PAGE_LOAD_TIMEOUT)
            self._increment_and_delay(tab)
            page += 1

        # 去重
        seen = set()
        unique = []
        for u in all_urls:
            if u not in seen:
                seen.add(u)
                unique.append(u)
        return unique
```

- [ ] **Step 2: 验证分类页采集**

Run: `uv run python -c "from scrapers.waltons import WaltonsScraper; s = WaltonsScraper(); urls = s.collect_product_urls('https://waltons.com/categories/equipment/waltons-equipment'); print(f'Total: {len(urls)}'); print(urls[:3]); s.close()"`

Expected: 输出 `Total: 32`（该分类约 32 个产品），前几个 URL 如 `https://waltons.com/waltons-8-meat-grinder/`

- [ ] **Step 3: 验证带分页的分类页（强制小 limit 测试翻页）**

Run: `uv run python -c "from scrapers.waltons import WaltonsScraper; s = WaltonsScraper(); urls = s.collect_product_urls('https://waltons.com/categories/equipment/waltons-equipment', max_pages=1); print(f'Page 1 only: {len(urls)}'); s.close()"`

Expected: 限制 1 页时产品数应少于总数（使用 `limit=100` 实际上该分类不需翻页，但 max_pages 逻辑应正确生效）

- [ ] **Step 4: Commit**

```bash
git add scrapers/waltons.py
git commit -m "feat(waltons): add category page URL collection with BigCommerce pagination"
```

---

### Task 5: CLI 端到端测试

**Files:** 无修改（使用现有 `main.py` CLI）

- [ ] **Step 1: 通过 CLI 测试单个产品抓取**

Run: `uv run python main.py https://waltons.com/waltons-22-meat-grinder/`

Expected:
- 成功抓取产品信息并输出摘要
- 数据写入 `data/products.db`（products + reviews 表）
- 无错误/异常

- [ ] **Step 2: 验证数据库数据**

Run: `uv run python -c "import sqlite3; c=sqlite3.connect('data/products.db'); c.row_factory=sqlite3.Row; print('Product:', dict(c.execute('SELECT site,name,sku,price,rating,review_count FROM products WHERE site=\"waltons\"').fetchone() or {})); print('Reviews:', c.execute('SELECT COUNT(*) FROM reviews r JOIN products p ON r.product_id=p.id WHERE p.site=\"waltons\"').fetchone()[0])"`

Expected: 产品数据正确，评论数量合理（>15 说明 TrustSpot 翻页成功）

- [ ] **Step 3: 通过 CLI 测试分类页采集（快速验证）**

Run: `uv run python main.py -c https://waltons.com/categories/equipment/waltons-equipment 1`

Expected: 采集第 1 页产品 URL 并抓取（`max_pages=1`，避免全量采集耗时过长）

注：完整分类采集（`uv run python main.py -c https://waltons.com/categories/equipment/waltons-equipment`）约 32 个产品，预计 10-20 分钟，可在验证基本功能后选择性执行。

---

## Chunk 2: 文档更新

### Task 6: 站点采集规则文档

**Files:**
- Create: `docs/rules/waltons.md`

- [ ] **Step 1: 编写采集规则文档**

基于浏览器分析和实际采集验证结果，创建 `docs/rules/waltons.md`，包含：
- 站点概述（BigCommerce + TrustSpot）
- 产品数据选择器（JSON-LD 优先 + DOM 兜底）
- 评论选择器（TrustSpot DOM，完整列表）
- 翻页机制（评论 `a.next-page` + 列表页 BigCommerce 分页）
- 已知限制和注意事项

参考现有 `docs/rules/basspro.md` 的格式和详细程度。

- [ ] **Step 2: Commit**

```bash
git add docs/rules/waltons.md
git commit -m "docs(waltons): add site scraping rules"
```

---

### Task 7: 更新 CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: 更新支持站点列表**

在"当前支持站点"部分追加：
```
- **Walton's** — 规则文档：`docs/rules/waltons.md`
```

- [ ] **Step 2: 更新项目结构图**

在 `scrapers/` 部分追加：
```
│   ├── waltons.py     # WaltonsScraper — Walton's
```

在 `docs/rules/` 部分确认 `waltons.md` 已列出。

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add waltons.com to supported sites and project structure"
```
