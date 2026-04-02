import json
import time
from DrissionPage import ChromiumOptions
from qbu_crawler.scrapers.base import BaseScraper
from qbu_crawler.config import (
    HEADLESS, PAGE_LOAD_TIMEOUT, NO_IMAGES,
    RETRY_TIMES, RETRY_INTERVAL,
    BV_WAIT_TIMEOUT, BV_POLL_INTERVAL,
)


class MeatYourMakerScraper(BaseScraper):

    SITE_LOAD_MODE = "normal"  # BV 脚本需要 normal 模式

    @staticmethod
    def _build_options() -> ChromiumOptions:
        """覆盖基类：使用 normal 模式，meatyourmaker 的 BV 在 eager 模式下无法初始化"""
        options = ChromiumOptions()
        options.auto_port()  # 每个实例使用独立端口，防止并行任务共享浏览器
        if HEADLESS:
            options.headless()
        if NO_IMAGES:
            options.no_imgs(True)
        options.set_load_mode("normal")
        options.set_retry(times=RETRY_TIMES, interval=RETRY_INTERVAL)
        options.set_timeouts(base=10, page_load=PAGE_LOAD_TIMEOUT)
        return options

    def scrape(self, url: str, review_limit: int | None = None) -> dict:
        self._maybe_restart_browser()
        tab = self._get_page(url)
        tab.wait.ele_displayed('tag:h1', timeout=15)
        self._check_url_match(tab, url)

        # meatyourmaker 的 BV 需要先展开 Reviews 区域才会加载
        # 先点击 Reviews toggler，再等待 BV 数据
        self._click_reviews_tab(tab)
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

        # 3. 价格: 主产品区域的 .price-sales（排除推荐产品 tile）
        price_text = tab.run_js("""
            const el = document.querySelector('.product-price.c-product__price .price-sales');
            return el ? el.textContent.trim() : null;
        """)
        if price_text:
            result["price"] = self._to_float(price_text.replace("$", "").replace(",", ""))

        # 4. 库存: .availability-msg 和 .not-available-div 互斥显示
        stock = tab.run_js("""
            const inStock = document.querySelector('.availability-msg');
            const oos = document.querySelector('.not-available-div');
            if (inStock && window.getComputedStyle(inStock).display !== 'none') return 'in_stock';
            if (oos && window.getComputedStyle(oos).display !== 'none') return 'out_of_stock';
            return 'unknown';
        """)
        result["stock_status"] = stock or "unknown"

        # 5. BV 评分摘要
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

        # 6. 评论提取（Task 6 实现）
        reviews = self._extract_all_reviews(tab, review_limit=review_limit)
        reviews = self._process_review_images(reviews)

        self._increment_and_delay(tab)
        data = {"product": result, "reviews": reviews}
        self._validate_product(data, url)
        return data

    def _wait_for_bv_data(self, tab):
        """轮询等待 BV 评分摘要数据注入"""
        deadline = time.time() + BV_WAIT_TIMEOUT
        while time.time() < deadline:
            found = tab.run_js(
                "return document.querySelector('#bv-jsonld-bvloader-summary') ? 1 : 0;"
            )
            if found:
                break
            time.sleep(BV_POLL_INTERVAL)

    def _click_reviews_tab(self, tab):
        """点击 Reviews toggler 展开评论区（先等待 toggler 渲染）"""
        # 等待 toggler 元素出现（最多 10 秒）
        deadline = time.time() + 10
        while time.time() < deadline:
            clicked = tab.run_js("""
                const togglers = document.querySelectorAll('.c-toggler__element');
                for (const el of togglers) {
                    if (el.textContent.trim() === 'Reviews') {
                        el.click();
                        return true;
                    }
                }
                return false;
            """)
            if clicked:
                break
            time.sleep(0.5)
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
        """逐个滚动评论 section 到视口，触发图片懒加载"""
        total = tab.run_js("""
            const c = document.querySelector('[data-bv-show="reviews"]');
            if (!c || !c.shadowRoot) return 0;
            const shadow = c.shadowRoot;
            const container = Array.from(shadow.querySelectorAll('section'))
                .find(s => s.querySelector('section'));
            return container ? container.querySelectorAll(':scope > section').length : 0;
        """)
        if not total:
            return
        for i in range(total):
            tab.run_js(f"""
                const c = document.querySelector('[data-bv-show="reviews"]');
                if (c && c.shadowRoot) {{
                    const container = Array.from(c.shadowRoot.querySelectorAll('section'))
                        .find(s => s.querySelector('section'));
                    if (container) {{
                        const s = container.querySelectorAll(':scope > section')[{i}];
                        if (s) s.scrollIntoView({{block: 'center'}});
                    }}
                }}
            """)
            time.sleep(0.3)
        time.sleep(1)

    def _extract_page_reviews(self, tab) -> list:
        """从当前页 Shadow DOM 提取评论"""
        self._scroll_review_sections(tab)
        raw = tab.run_js("""
            const c = document.querySelector('[data-bv-show="reviews"]');
            if (!c || !c.shadowRoot) return '[]';
            const shadow = c.shadowRoot;
            const container = Array.from(shadow.querySelectorAll('section'))
                .find(s => s.querySelector('section'));
            if (!container) return '[]';
            const cards = Array.from(container.querySelectorAll(':scope > section'));
            const reviews = [];
            for (const s of cards) {
                let authorEl = s.querySelector('button.bv-rnr-action-bar')
                            || s.querySelector('button[aria-label^="See"]');
                const author = authorEl ? authorEl.textContent.trim() : '';
                const h3 = s.querySelector('h3');
                const headline = h3 ? h3.textContent.trim() : '';
                let rating = null;
                const ratingEl = s.querySelector('[role="img"][aria-label*="out of 5"]');
                if (ratingEl) {
                    const m = ratingEl.getAttribute('aria-label').match(/(\\d+(?:\\.\\d+)?)\\s+out\\s+of\\s+5/);
                    if (m) rating = parseFloat(m[1]);
                }
                let date = '';
                const dateEl = s.querySelector('span[class*="g3jej5"]');
                if (dateEl) {
                    date = dateEl.textContent.trim();
                } else {
                    for (const sp of s.querySelectorAll('span')) {
                        const t = sp.textContent.trim();
                        if (t.match(/\\d+\\s+(days?|months?|years?)\\s+ago/) ||
                            t.match(/^a\\s+(day|month|year)\\s+ago$/)) {
                            date = t;
                            break;
                        }
                    }
                }
                let body = '';
                const allDivs = Array.from(s.querySelectorAll('div')).filter(d => {
                    const t = d.textContent.trim();
                    return t.length > 30 && !d.querySelector('div') && !d.querySelector('button');
                });
                if (allDivs.length > 0) {
                    body = allDivs[0].textContent.trim();
                }
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

    def _extract_all_reviews(self, tab, review_limit: int | None = None) -> list:
        """逐页翻页提取全部评论（Reviews 已在 scrape() 中展开）"""
        if not self._wait_for_shadow_root(tab):
            return []

        all_reviews = []
        seen = set()
        max_pages = 100

        for _ in range(max_pages):
            page_reviews = self._extract_page_reviews(tab)
            for r in page_reviews:
                key = (r.get("author", ""), r.get("headline", ""))
                if key not in seen:
                    seen.add(key)
                    all_reviews.append(r)
                    if review_limit and review_limit > 0 and len(all_reviews) >= review_limit:
                        return all_reviews[:review_limit]

            has_next = tab.run_js("""
                const c = document.querySelector('[data-bv-show="reviews"]');
                if (!c || !c.shadowRoot) return false;
                const next = c.shadowRoot.querySelector('a.next');
                if (next) { next.click(); return true; }
                return false;
            """)
            if not has_next:
                break
            time.sleep(2)

        if review_limit and review_limit > 0:
            return all_reviews[:review_limit]
        return all_reviews

    def collect_product_urls(self, category_url: str, max_pages: int = 0) -> list[str]:
        """从分类页采集产品 URL — 无限滚动（请求 data-grid-url）"""
        tab = self._get_page(category_url)
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

            tab = self._get_page(next_url)
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
