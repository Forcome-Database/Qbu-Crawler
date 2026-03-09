# 多站点爬虫架构重构 + MeatYourMaker 集成

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将单站点爬虫重构为多站点框架，集成 meatyourmaker.com 作为第二个站点。

**Architecture:** 轻量继承 + 独立实现。BaseScraper 管理浏览器生命周期，各站点子类完全独立实现 scrape/collect。URL 域名自动路由，支持多站点并行。

**Tech Stack:** Python 3.10+, DrissionPage, SQLite, MinIO, ThreadPoolExecutor

**设计文档:** `docs/plans/2026-03-09-multi-site-architecture-design.md`

**注意:** 本项目是浏览器自动化爬虫，无法用传统单元测试。每个 Task 的验证通过实际运行爬虫并检查输出完成。

---

### Task 1: 创建 scrapers 包 + BaseScraper 基类

**Files:**
- Create: `scrapers/__init__.py`
- Create: `scrapers/base.py`

**Step 1: 创建 `scrapers/base.py`**

从 `scraper.py` 提取浏览器管理和通用工具方法到 BaseScraper：

```python
# scrapers/base.py
import json
import time
from DrissionPage import Chromium, ChromiumOptions
from config import (
    HEADLESS, PAGE_LOAD_TIMEOUT, LOAD_MODE, NO_IMAGES,
    RETRY_TIMES, RETRY_INTERVAL, REQUEST_DELAY, RESTART_EVERY,
)


class BaseScraper:
    """浏览器生命周期管理 + 通用工具，不定义抽象方法"""

    def __init__(self):
        self._options = self._build_options()
        self.browser = Chromium(self._options)
        self._scrape_count = 0

    @staticmethod
    def _build_options() -> ChromiumOptions:
        options = ChromiumOptions()
        if HEADLESS:
            options.headless()
        if NO_IMAGES:
            options.no_imgs(True)
        options.set_load_mode(LOAD_MODE)
        options.set_retry(times=RETRY_TIMES, interval=RETRY_INTERVAL)
        options.set_timeouts(base=10, page_load=PAGE_LOAD_TIMEOUT)
        return options

    def _maybe_restart_browser(self):
        if RESTART_EVERY and self._scrape_count > 0 and self._scrape_count % RESTART_EVERY == 0:
            print(f"  [优化] 已抓取 {self._scrape_count} 个产品，重启浏览器释放内存")
            try:
                self.browser.quit()
            except Exception:
                pass
            self.browser = Chromium(self._options)

    def _increment_and_delay(self, tab):
        self._scrape_count += 1
        if REQUEST_DELAY:
            tab.wait(REQUEST_DELAY[0], REQUEST_DELAY[1])

    @staticmethod
    def _to_float(val) -> float | None:
        if val is None:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _to_int(val) -> int | None:
        if val is None:
            return None
        try:
            return int(val)
        except (ValueError, TypeError):
            return None

    def _process_review_images(self, reviews: list) -> list:
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

    def close(self):
        try:
            self.browser.quit()
        except Exception:
            pass
```

说明：`_process_review_images` 也放入基类，因为 MinIO 上传逻辑两站点完全相同。

**Step 2: 创建 `scrapers/__init__.py`**

```python
# scrapers/__init__.py
from urllib.parse import urlparse

SITE_MAP = {
    "www.basspro.com": ("basspro", "scrapers.basspro", "BassProScraper"),
    "www.meatyourmaker.com": ("meatyourmaker", "scrapers.meatyourmaker", "MeatYourMakerScraper"),
}


def get_site_key(url: str) -> str:
    """从 URL 获取站点标识"""
    host = urlparse(url).netloc
    entry = SITE_MAP.get(host)
    if not entry:
        raise ValueError(f"不支持的站点: {host}")
    return entry[0]


def get_scraper(url: str):
    """根据 URL 域名延迟导入并返回对应 scraper 实例"""
    host = urlparse(url).netloc
    entry = SITE_MAP.get(host)
    if not entry:
        raise ValueError(f"不支持的站点: {host}")
    _, module_path, cls_name = entry
    module = __import__(module_path, fromlist=[cls_name])
    return getattr(module, cls_name)()
```

**Step 3: 验证**

```bash
uv run python -c "from scrapers.base import BaseScraper; print('BaseScraper OK')"
uv run python -c "from scrapers import SITE_MAP; print(SITE_MAP)"
```

Expected: 两条都无报错，正常输出。

**Step 4: Commit**

```bash
git add scrapers/
git commit -m "refactor: 创建 scrapers 包和 BaseScraper 基类"
```

---

### Task 2: 迁移 BassProScraper 到 scrapers 包

**Files:**
- Create: `scrapers/basspro.py`
- Modify: `main.py`
- Delete: `scraper.py`（迁移完成后）

**Step 1: 创建 `scrapers/basspro.py`**

将 `scraper.py` 中除已提取到 BaseScraper 的方法外，全部迁移到此文件：

```python
# scrapers/basspro.py
import json
import re
import time
from scrapers.base import BaseScraper
from config import BV_WAIT_TIMEOUT, BV_POLL_INTERVAL, PAGE_LOAD_TIMEOUT


class BassProScraper(BaseScraper):

    def scrape(self, url: str) -> dict:
        self._maybe_restart_browser()
        tab = self.browser.latest_tab
        tab.get(url)
        tab.wait.ele_displayed('tag:h1', timeout=15)
        bv_container = tab.ele('css:.bv_main_container', timeout=10)
        if bv_container:
            bv_container.scroll.to_see()
        self._wait_for_bv_data(tab)

        result = {
            "url": url,
            "site": "basspro",
            "name": None,
            "sku": None,
            "price": None,
            "stock_status": None,
            "review_count": None,
            "rating": None,
        }

        # 以下与原 scraper.py 完全相同（JS 提取 JSON-LD + DOM 兜底 + BV 评分）
        raw = tab.run_js("""...""")  # 保持原有 JS 不变
        # ... 原有产品数据提取逻辑 ...
        # ... 原有评论提取逻辑 ...

        self._increment_and_delay(tab)
        return {"product": result, "reviews": reviews}

    def collect_product_urls(self, category_url: str, max_pages: int = 0) -> list[str]:
        # 与原 scraper.py 完全相同
        ...

    # 以下私有方法与原 scraper.py 完全相同，直接搬过来
    def _wait_for_bv_data(self, tab): ...
    def _extract_sku_from_dom(self, tab) -> str | None: ...
    def _click_reviews_tab(self, tab): ...
    def _load_all_reviews(self, tab): ...
    def _scroll_all_reviews(self, tab): ...
    def _extract_reviews_from_dom(self, tab) -> list: ...
```

关键改动点（相比原 scraper.py）：
1. `class BassProScraper(BaseScraper)` — 继承基类
2. `__init__` 删除 — 使用基类的
3. `_build_options`、`_maybe_restart_browser`、`_to_float`、`_to_int`、`_process_review_images`、`close` 删除 — 继承自基类
4. `result` dict 新增 `"site": "basspro"`
5. `self._scrape_count += 1` + 随机延迟 → 替换为 `self._increment_and_delay(tab)`

**Step 2: 更新 `main.py` 导入**

```python
# main.py 改动
# 旧:
from scraper import BassProScraper
# 新:
from scrapers import get_scraper
```

`main()` 中 `scraper = BassProScraper()` 暂时改为 `scraper = get_scraper(first_url)`，详细改动见 Task 4。此步先做最小改动保证能跑：

```python
def main():
    ...
    scraper = None
    try:
        if sys.argv[1] == "-f":
            urls = load_urls_from_file(sys.argv[2])
            scraper = get_scraper(urls[0])
            scrape_urls(scraper, urls)
        elif sys.argv[1] == "-c":
            category_url = sys.argv[2]
            scraper = get_scraper(category_url)
            ...
        else:
            urls = sys.argv[1:]
            scraper = get_scraper(urls[0])
            scrape_urls(scraper, urls)
    finally:
        if scraper:
            scraper.close()
```

**Step 3: 验证 — 用 basspro 产品 URL 跑一次**

```bash
uv run python main.py https://www.basspro.com/shop/en/bass-pro-shops-tourney-special-spinning-combo
```

Expected: 与重构前输出一致（名称、SKU、价格、库存、评分、评论）。

**Step 4: 删除旧文件**

```bash
rm scraper.py
```

**Step 5: Commit**

```bash
git add scrapers/basspro.py main.py
git rm scraper.py
git commit -m "refactor: 迁移 BassProScraper 到 scrapers 包"
```

---

### Task 3: 数据层变更 — products 表加 site 字段

**Files:**
- Modify: `models.py`

**Step 1: 修改 `init_db()` 中的建表语句和迁移**

```python
# models.py init_db() 改动

# 1. CREATE TABLE 加 site 列
"""
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE NOT NULL,
    site TEXT NOT NULL DEFAULT 'basspro',
    name TEXT,
    ...
);
"""

# 2. migrations 列表新增
migrations = [
    ...  # 原有的
    "ALTER TABLE products ADD COLUMN site TEXT NOT NULL DEFAULT 'basspro'",
]
```

**Step 2: 修改 `save_product()` SQL**

```python
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
    ...
```

**Step 3: 验证迁移兼容性**

```bash
# 在已有数据库上跑 init_db，确认旧数据自动回填 site='basspro'
uv run python -c "
from models import init_db, get_conn
init_db()
conn = get_conn()
rows = conn.execute('SELECT url, site FROM products LIMIT 3').fetchall()
for r in rows:
    print(r['url'][:60], '|', r['site'])
conn.close()
"
```

Expected: 所有旧数据 site 列为 `basspro`。

**Step 4: Commit**

```bash
git add models.py
git commit -m "feat: products 表新增 site 字段，支持多站点数据存储"
```

---

### Task 4: 重构 main.py — 多站点路由与并行

**Files:**
- Modify: `main.py`

**Step 1: 完整重写 main.py**

```python
# main.py
import sys
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
from models import init_db, save_product, save_snapshot, save_reviews
from scrapers import get_scraper, get_site_key, SITE_MAP

USAGE = """用法:
  python main.py <产品URL> [产品URL2 ...]     抓取指定产品页
  python main.py -f <文件路径>                 从文件读取 URL 列表（每行一个）
  python main.py -c <分类页URL> [最大页数]     从分类页自动采集产品链接并抓取
  python main.py -c <URL1> -c <URL2>          多站点分类页并行采集

支持站点: """ + ", ".join(SITE_MAP.keys())


def load_urls_from_file(filepath: str) -> list[str]:
    if not os.path.exists(filepath):
        print(f"文件不存在: {filepath}")
        sys.exit(1)
    with open(filepath, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]


def group_urls_by_site(urls: list[str]) -> dict[str, list[str]]:
    """按域名对 URL 分组，忽略不支持的站点"""
    groups = {}
    for url in urls:
        try:
            site = get_site_key(url)
            groups.setdefault(site, []).append(url)
        except ValueError as e:
            print(f"  [跳过] {e}")
    return groups


def scrape_urls(scraper, urls: list[str], site: str = ""):
    """抓取一组 URL（单站点）"""
    prefix = f"[{site}] " if site else ""
    success = 0
    failed_urls = []

    for i, url in enumerate(urls, 1):
        print(f"\n{prefix}[{i}/{len(urls)}] 正在抓取: {url}")
        try:
            data = scraper.scrape(url)
            product = data["product"]
            reviews = data["reviews"]

            product_id = save_product(product)
            save_snapshot(product_id, product)
            new_reviews = save_reviews(product_id, reviews)

            print(f"  名称: {product['name']}")
            print(f"  SKU: {product['sku']}")
            print(f"  价格: {product['price']}")
            print(f"  库存: {product['stock_status']}")
            print(f"  评分: {product['rating']}")
            review_count = product['review_count'] or 0
            scraped = len(reviews)
            if review_count == 0:
                print(f"  评论: 无")
            elif scraped > 0:
                print(f"  评论: {scraped}/{review_count} 条 (新增 {new_reviews})")
            else:
                print(f"  评论: 0/{review_count} 条 (BV未注入详情数据)")
            success += 1
        except Exception as e:
            failed_urls.append(url)
            print(f"  抓取失败: {e}")

    print(f"\n{prefix}抓取完成! 成功 {success}/{len(urls)}")
    if failed_urls:
        print(f"失败的 URL ({len(failed_urls)} 个):")
        for u in failed_urls:
            print(f"  {u}")


def run_site(site: str, urls: list[str]):
    """单站点任务：创建 scraper → 采集 → 关闭"""
    scraper = get_scraper(urls[0])
    try:
        scrape_urls(scraper, urls, site)
    finally:
        scraper.close()


def run_category_site(category_url: str, max_pages: int):
    """单站点分类采集：创建 scraper → 采集链接 → 抓取详情 → 关闭"""
    site = get_site_key(category_url)
    scraper = get_scraper(category_url)
    try:
        print(f"[{site}] 正在从分类页采集产品链接: {category_url}")
        urls = scraper.collect_product_urls(category_url, max_pages)
        print(f"[{site}] 共采集到 {len(urls)} 个产品链接，开始抓取详情...")
        scrape_urls(scraper, urls, site)
    finally:
        scraper.close()


def main():
    if len(sys.argv) < 2:
        print(USAGE)
        sys.exit(1)

    print("初始化数据库...")
    init_db()

    args = sys.argv[1:]

    # 解析 -c 参数（支持多个）
    if "-c" in args:
        categories = []
        max_pages = 0
        i = 0
        while i < len(args):
            if args[i] == "-c" and i + 1 < len(args):
                categories.append(args[i + 1])
                i += 2
            else:
                # 最后一个非 -c 参数当 max_pages
                try:
                    max_pages = int(args[i])
                except ValueError:
                    pass
                i += 1

        if not categories:
            print("请指定分类页 URL")
            sys.exit(1)

        if len(categories) == 1:
            run_category_site(categories[0], max_pages)
        else:
            # 多站点并行
            with ThreadPoolExecutor(max_workers=len(categories)) as pool:
                futures = {
                    pool.submit(run_category_site, cat, max_pages): cat
                    for cat in categories
                }
                for future in as_completed(futures):
                    cat = futures[future]
                    try:
                        future.result()
                    except Exception as e:
                        print(f"[错误] {cat}: {e}")

    elif args[0] == "-f":
        if len(args) < 2:
            print("请指定文件路径")
            sys.exit(1)
        urls = load_urls_from_file(args[1])
        print(f"从文件加载 {len(urls)} 个 URL")
        site_groups = group_urls_by_site(urls)

        if len(site_groups) == 1:
            site, site_urls = next(iter(site_groups.items()))
            run_site(site, site_urls)
        else:
            # 多站点并行
            with ThreadPoolExecutor(max_workers=len(site_groups)) as pool:
                futures = {
                    pool.submit(run_site, site, site_urls): site
                    for site, site_urls in site_groups.items()
                }
                for future in as_completed(futures):
                    site = futures[future]
                    try:
                        future.result()
                    except Exception as e:
                        print(f"[错误] {site}: {e}")

    else:
        # 直接传入产品 URL
        urls = args
        site_groups = group_urls_by_site(urls)
        if len(site_groups) == 1:
            site, site_urls = next(iter(site_groups.items()))
            run_site(site, site_urls)
        else:
            with ThreadPoolExecutor(max_workers=len(site_groups)) as pool:
                futures = {
                    pool.submit(run_site, site, site_urls): site
                    for site, site_urls in site_groups.items()
                }
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        print(f"[错误] {e}")


if __name__ == "__main__":
    main()
```

**Step 2: 验证单站点（basspro）**

```bash
uv run python main.py https://www.basspro.com/shop/en/bass-pro-shops-tourney-special-spinning-combo
```

Expected: 与之前输出一致。

**Step 3: Commit**

```bash
git add main.py
git commit -m "refactor: main.py 支持多站点路由和并行采集"
```

---

### Task 5: 实现 MeatYourMakerScraper — 产品详情

**Files:**
- Create: `scrapers/meatyourmaker.py`

**Step 1: 创建 `scrapers/meatyourmaker.py`，先实现产品数据提取（不含评论）**

```python
# scrapers/meatyourmaker.py
import json
import time
from scrapers.base import BaseScraper
from config import BV_WAIT_TIMEOUT, BV_POLL_INTERVAL, PAGE_LOAD_TIMEOUT


class MeatYourMakerScraper(BaseScraper):

    def scrape(self, url: str) -> dict:
        self._maybe_restart_browser()
        tab = self.browser.latest_tab
        tab.get(url)
        tab.wait.ele_displayed('tag:h1', timeout=15)

        # 等待 BV 容器加载
        bv_container = tab.ele('css:.bv_main_container', timeout=10)
        if bv_container:
            bv_container.scroll.to_see()
        self._wait_for_bv_data(tab)

        result = {
            "url": url,
            "site": "meatyourmaker",
            "name": None,
            "sku": None,
            "price": None,
            "stock_status": None,
            "review_count": None,
            "rating": None,
        }

        # 1. 名称: h1
        h1 = tab.ele('tag:h1', timeout=5)
        if h1:
            result["name"] = h1.text.strip()

        # 2. SKU: [data-pid] 属性
        result["sku"] = tab.run_js("""
            const el = document.querySelector('[data-pid]');
            return el ? el.getAttribute('data-pid') : null;
        """)

        # 3. 价格: 主产品区域的 .price-sales（排除推荐产品）
        price_text = tab.run_js("""
            const el = document.querySelector('.product-price.c-product__price .price-sales');
            return el ? el.textContent.trim() : null;
        """)
        if price_text:
            result["price"] = self._to_float(price_text.replace("$", "").replace(",", ""))

        # 4. 库存: .availability-msg 可见性
        stock = tab.run_js("""
            const msg = document.querySelector('.availability-msg');
            if (!msg) return 'unknown';
            return window.getComputedStyle(msg).display !== 'none' ? 'in_stock' : 'out_of_stock';
        """)
        result["stock_status"] = stock or "unknown"

        # 5. BV 评分摘要（与 basspro 相同逻辑）
        bv_raw = tab.run_js("""
            const bvs = document.querySelector('#bv-jsonld-bvloader-summary');
            return bvs ? bvs.textContent : null;
        """)
        if bv_raw:
            try:
                bv_data = json.loads(bv_raw)
                agg = bv_data.get("aggregateRating") or bv_data
                result["rating"] = self._to_float(agg.get("ratingValue"))
                result["review_count"] = self._to_int(agg.get("reviewCount"))
            except (json.JSONDecodeError, AttributeError):
                pass

        # 6. 评论（Task 6 实现）
        reviews = self._extract_all_reviews(tab)
        reviews = self._process_review_images(reviews)

        self._increment_and_delay(tab)
        return {"product": result, "reviews": reviews}

    def _wait_for_bv_data(self, tab):
        deadline = time.time() + BV_WAIT_TIMEOUT
        while time.time() < deadline:
            found = tab.run_js(
                "return document.querySelector('#bv-jsonld-bvloader-summary') ? 1 : 0;"
            )
            if found:
                break
            time.sleep(BV_POLL_INTERVAL)

    def _extract_all_reviews(self, tab) -> list:
        """占位 — Task 6 实现"""
        return []

    def collect_product_urls(self, category_url: str, max_pages: int = 0) -> list[str]:
        """占位 — Task 7 实现"""
        return []
```

**Step 2: 验证产品数据提取（不含评论）**

```bash
uv run python main.py https://www.meatyourmaker.com/process/grinders/.5-hp-grinder-8/1117073.html
```

Expected 输出：
```
名称: .5 HP Grinder (#8)
SKU: 1117073
价格: 539.99
库存: in_stock
评分: 4.8
评论: 0/396 条 (BV未注入详情数据)
```

**Step 3: Commit**

```bash
git add scrapers/meatyourmaker.py
git commit -m "feat: MeatYourMakerScraper 产品详情提取（不含评论）"
```

---

### Task 6: MeatYourMakerScraper — 评论翻页提取

**Files:**
- Modify: `scrapers/meatyourmaker.py`

**Step 1: 实现评论展开 + 翻页 + 提取**

替换 `_extract_all_reviews` 占位方法：

```python
def _click_reviews_tab(self, tab):
    """点击 Reviews toggler 展开评论区"""
    tab.run_js("""
        const togglers = document.querySelectorAll('.c-toggler__element');
        for (const el of togglers) {
            if (el.textContent.trim() === 'Reviews') {
                el.click();
                break;
            }
        }
    """)
    time.sleep(2)

def _wait_for_shadow_root(self, tab, timeout=10):
    """等待 BV reviews Shadow DOM 加载"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        has_shadow = tab.run_js("""
            const c = document.querySelector('[data-bv-show="reviews"]');
            return c && c.shadowRoot ? 1 : 0;
        """)
        if has_shadow:
            return True
        time.sleep(0.5)
    return False

def _scroll_review_sections(self, tab):
    """滚动所有评论 section 触发图片懒加载"""
    tab.run_js("""
        const c = document.querySelector('[data-bv-show="reviews"]');
        if (!c || !c.shadowRoot) return;
        const shadow = c.shadowRoot;
        // 找外层容器（有子 section 的 section）
        const container = Array.from(shadow.querySelectorAll('section'))
            .find(s => s.querySelector('section'));
        if (!container) return;
        container.querySelectorAll(':scope > section').forEach(s => {
            s.scrollIntoView({block: 'center'});
        });
    """)
    time.sleep(1)

def _extract_page_reviews(self, tab) -> list:
    """从当前页 Shadow DOM 提取评论"""
    self._scroll_review_sections(tab)

    raw = tab.run_js("""
        const c = document.querySelector('[data-bv-show="reviews"]');
        if (!c || !c.shadowRoot) return '[]';
        const shadow = c.shadowRoot;

        // 找外层容器 section（有子 section 的）
        const container = Array.from(shadow.querySelectorAll('section'))
            .find(s => s.querySelector('section'));
        if (!container) return '[]';

        const cards = Array.from(container.querySelectorAll(':scope > section'));
        const reviews = [];

        for (const s of cards) {
            // 作者: button.bv-rnr-action-bar，降级 button[aria-label^="See"]
            let authorEl = s.querySelector('button.bv-rnr-action-bar')
                        || s.querySelector('button[aria-label^="See"]');
            const author = authorEl ? authorEl.textContent.trim() : '';

            // 标题: h3
            const h3 = s.querySelector('h3');
            const headline = h3 ? h3.textContent.trim() : '';

            // 评分: [role="img"][aria-label*="out of 5"]
            let rating = null;
            const ratingEl = s.querySelector('[role="img"][aria-label*="out of 5"]');
            if (ratingEl) {
                const m = ratingEl.getAttribute('aria-label').match(/(\\d+(?:\\.\\d+)?)\\s+out\\s+of\\s+5/);
                if (m) rating = parseFloat(m[1]);
            }

            // 日期: span[class*="g3jej5"]，降级文本正则
            let date = '';
            const dateEl = s.querySelector('span[class*="g3jej5"]');
            if (dateEl) {
                date = dateEl.textContent.trim();
            } else {
                s.querySelectorAll('span').forEach(sp => {
                    if (!date) {
                        const t = sp.textContent.trim();
                        if (t.match(/\\d+\\s+(days?|months?|years?)\\s+ago/) ||
                            t.match(/^a\\s+(day|month|year)\\s+ago$/)) {
                            date = t;
                        }
                    }
                });
            }

            // 正文: 位置优先 — 排除已知元素后的第一个长文本 div
            let body = '';
            const allDivs = Array.from(s.querySelectorAll('div')).filter(d => {
                const t = d.textContent.trim();
                return t.length > 30 && !d.querySelector('div') && !d.querySelector('button');
            });
            if (allDivs.length > 0) {
                body = allDivs[0].textContent.trim();
            }

            // 图片: .photos-tile img
            const imgs = [];
            s.querySelectorAll('.photos-tile img').forEach(img => {
                const src = img.getAttribute('src');
                if (src && src.includes('bazaarvoice.com')) imgs.push(src);
            });

            if (headline || body) {
                reviews.push({author, headline, body, rating, date_published: date, images: imgs});
            }
        }
        return JSON.stringify(reviews);
    """)
    return json.loads(raw) if isinstance(raw, str) else (raw or [])

def _extract_all_reviews(self, tab) -> list:
    """展开评论区 → 逐页翻页提取"""
    self._click_reviews_tab(tab)
    if not self._wait_for_shadow_root(tab):
        return []

    all_reviews = []
    seen = set()
    max_pages = 100  # 安全上限

    for _ in range(max_pages):
        page_reviews = self._extract_page_reviews(tab)
        for r in page_reviews:
            key = (r.get("author", ""), r.get("headline", ""))
            if key not in seen:
                seen.add(key)
                all_reviews.append(r)

        # 点击 next 翻页
        has_next = tab.run_js("""
            const c = document.querySelector('[data-bv-show="reviews"]');
            if (!c || !c.shadowRoot) return false;
            const next = c.shadowRoot.querySelector('a.next');
            if (next) { next.click(); return true; }
            return false;
        """)
        if not has_next:
            break

        # 等待新评论加载（h3 文本变化）
        time.sleep(2)

    return all_reviews
```

**Step 2: 验证评论提取**

```bash
uv run python main.py https://www.meatyourmaker.com/process/grinders/.5-hp-grinder-8/1117073.html
```

Expected: 评论数量大于 0，输出类似 `评论: N/396 条 (新增 N)`。

再测评论多的产品（触发翻页）：

```bash
uv run python main.py https://www.meatyourmaker.com/process/grinders/.75-hp-grinder-22/1159178.html
```

Expected: 253 条评论，需要多页翻页才能全部获取。

**Step 3: Commit**

```bash
git add scrapers/meatyourmaker.py
git commit -m "feat: MeatYourMakerScraper 评论翻页提取"
```

---

### Task 7: MeatYourMakerScraper — 分类页无限滚动采集

**Files:**
- Modify: `scrapers/meatyourmaker.py`

**Step 1: 实现 `collect_product_urls`**

替换占位方法：

```python
def collect_product_urls(self, category_url: str, max_pages: int = 0) -> list[str]:
    """从分类页采集产品 URL — 无限滚动（请求 data-grid-url）"""
    tab = self.browser.latest_tab
    tab.get(category_url)
    tab.wait.doc_loaded(timeout=PAGE_LOAD_TIMEOUT)
    tab.wait.ele_displayed('tag:h1', timeout=15)

    all_urls = []
    page = 1

    while True:
        # 提取当前页产品链接
        page_urls_raw = tab.run_js("""
            const urls = [];
            const seen = new Set();
            document.querySelectorAll('.product-tile a[href$=".html"]').forEach(a => {
                const href = a.href;
                if (!seen.has(href)) { seen.add(href); urls.push(href); }
            });
            return JSON.stringify(urls);
        """)
        page_urls = json.loads(page_urls_raw) if isinstance(page_urls_raw, str) else (page_urls_raw or [])

        if not page_urls:
            print(f"  第 {page} 页: 未找到产品链接")
            break

        all_urls.extend(page_urls)
        print(f"  第 {page} 页: 获取 {len(page_urls)} 个产品链接")

        if max_pages and page >= max_pages:
            break

        # 获取下一页 URL（无限滚动占位符）
        next_url = tab.run_js("""
            const ph = document.querySelector('.infinite-scroll-placeholder');
            return ph ? ph.getAttribute('data-grid-url') : null;
        """)
        if not next_url:
            break

        # 请求下一页
        tab.get(next_url)
        tab.wait.doc_loaded(timeout=PAGE_LOAD_TIMEOUT)
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

**Step 2: 验证分类页采集**

```bash
# 小分类（4 个产品，无翻页）
uv run python main.py -c https://www.meatyourmaker.com/prepare/meat-slicers/

# 大分类（>12 个产品，有翻页）限 2 页
uv run python main.py -c https://www.meatyourmaker.com/process/grinders/ 2
```

Expected:
- meat-slicers: 采集 4 个产品链接
- grinders 限 2 页: 采集约 24 个链接

**Step 3: Commit**

```bash
git add scrapers/meatyourmaker.py
git commit -m "feat: MeatYourMakerScraper 分类页无限滚动采集"
```

---

### Task 8: 更新文档和配置

**Files:**
- Modify: `CLAUDE.md`
- Create: `docs/rules/meatyourmaker.md`
- Modify: `config.py`（如有新增配置）

**Step 1: 更新 CLAUDE.md 项目结构和支持站点**

更新项目结构图（`scraper.py` → `scrapers/` 包），支持站点列表加入 meatyourmaker。

**Step 2: 创建 `docs/rules/meatyourmaker.md`**

记录 meatyourmaker 站点的所有选择器、提取策略、翻页机制、踩坑经验。

内容要点：
- 站点信息（域名、URL 格式、平台 SFCC/Demandware）
- 产品数据提取（DOM，无 JSON-LD Product）
- 评论展开（`div.c-toggler__element` 文本 "Reviews"）
- 评论翻页（Shadow DOM 内 `a.next` / `a.prev`，每页替换）
- 评论正文提取（位置优先 — 排除 header 后第一个长文本 div）
- 分类页（`.product-tile`、无限滚动 `data-grid-url`）
- 注意事项

**Step 3: Commit**

```bash
git add CLAUDE.md docs/rules/meatyourmaker.md
git commit -m "docs: 新增 meatyourmaker 站点规则文档，更新 CLAUDE.md"
```

---

### Task 9: 端到端验证

**Step 1: 单站点 basspro 回归**

```bash
uv run python main.py https://www.basspro.com/shop/en/bass-pro-shops-tourney-special-spinning-combo
```

**Step 2: 单站点 meatyourmaker**

```bash
uv run python main.py https://www.meatyourmaker.com/process/grinders/.5-hp-grinder-8/1117073.html
```

**Step 3: 分类页采集**

```bash
uv run python main.py -c https://www.meatyourmaker.com/prepare/meat-slicers/
```

**Step 4: 多站点并行（-f 文件混合 URL）**

创建 `test_urls.txt`:
```
https://www.basspro.com/shop/en/bass-pro-shops-tourney-special-spinning-combo
https://www.meatyourmaker.com/process/grinders/.5-hp-grinder-8/1117073.html
```

```bash
uv run python main.py -f test_urls.txt
```

Expected: 两个站点各自输出结果，互不影响。

**Step 5: 验证数据库 site 字段**

```bash
uv run python -c "
import sqlite3
c = sqlite3.connect('data/products.db')
for row in c.execute('SELECT site, COUNT(*) FROM products GROUP BY site').fetchall():
    print(f'{row[0]}: {row[1]} 个产品')
c.close()
"
```

**Step 6: 清理测试文件，最终 Commit**

```bash
rm -f test_urls.txt
git add -A
git commit -m "feat: 完成多站点架构重构 + meatyourmaker.com 集成"
```
