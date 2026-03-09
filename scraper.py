import json
import re
import time
from DrissionPage import Chromium, ChromiumOptions
from config import (
    HEADLESS, PAGE_LOAD_TIMEOUT, LOAD_MODE, NO_IMAGES,
    RETRY_TIMES, RETRY_INTERVAL,
    BV_WAIT_TIMEOUT, BV_POLL_INTERVAL,
    REQUEST_DELAY, RESTART_EVERY,
)


class BassProScraper:
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
        """定期重启浏览器，防止长时间运行内存泄漏"""
        if RESTART_EVERY and self._scrape_count > 0 and self._scrape_count % RESTART_EVERY == 0:
            print(f"  [优化] 已抓取 {self._scrape_count} 个产品，重启浏览器释放内存")
            try:
                self.browser.quit()
            except Exception:
                pass
            self.browser = Chromium(self._options)

    def scrape(self, url: str) -> dict:
        self._maybe_restart_browser()

        tab = self.browser.latest_tab
        tab.get(url)
        # eager 模式下 get() 在 DOM 就绪后自动返回
        # 等待页面主要内容加载
        tab.wait.ele_displayed('tag:h1', timeout=15)
        # 等待 BV 组件加载（容器一定会出现，但 JSON-LD 数据只有有评论时才有）
        bv_container = tab.ele('css:.bv_main_container', timeout=10)
        # 滚动到 BV 组件位置，触发懒加载（BV 不在视口内不会注入 reviews-data）
        if bv_container:
            bv_container.scroll.to_see()
        # 轮询等待 BV JSON-LD 数据注入（summary 和 reviews-data 注入时序不确定）
        self._wait_for_bv_data(tab)

        result = {
            "url": url,
            "name": None,
            "sku": None,
            "price": None,
            "stock_status": None,
            "review_count": None,
            "rating": None,
        }

        # 通过 JS 一次性提取所有结构化数据，避免 .text 对 script 标签取不到内容的问题
        raw = tab.run_js("""
            const result = {productLD: null, bvSummary: null};
            document.querySelectorAll('script[type="application/ld+json"]').forEach(s => {
                try {
                    const d = JSON.parse(s.textContent);
                    if (d['@type'] === 'Product') result.productLD = d;
                    // ProductGroup: 取第一个 variant 的价格，用 group 的名称和 SKU
                    if (d['@type'] === 'ProductGroup') {
                        const variant = d.hasVariant?.[0];
                        result.productLD = {
                            '@type': 'Product',
                            name: d.name,
                            sku: d.productGroupID,
                            offers: variant?.offers || null
                        };
                    }
                    // BV summary (无 id 的独立 script)
                    if (d.aggregateRating && !result.bvSummary) result.bvSummary = d;
                } catch(e) {}
            });
            // BV summary (有 id 的 script)
            const bvs = document.querySelector('#bv-jsonld-bvloader-summary');
            if (bvs) try { result.bvSummary = JSON.parse(bvs.textContent); } catch(e) {}
            return JSON.stringify(result);
        """)
        data = json.loads(raw) if isinstance(raw, str) else raw

        # 1. JSON-LD 产品数据
        product_ld = data.get("productLD")
        if product_ld:
            result["name"] = product_ld.get("name")
            result["sku"] = product_ld.get("sku")
            offers = product_ld.get("offers")
            if isinstance(offers, dict):
                result["price"] = self._to_float(offers.get("price"))
            elif isinstance(offers, list) and offers:
                result["price"] = self._to_float(offers[0].get("price"))

        # 2. DOM 兜底：名称
        if not result["name"]:
            h1 = tab.ele('tag:h1', timeout=2)
            if h1:
                result["name"] = h1.text.strip()

        # 3. DOM 兜底：SKU
        if not result["sku"]:
            result["sku"] = self._extract_sku_from_dom(tab)

        # 4. BV 评分汇总
        bv_summary_data = data.get("bvSummary")
        if bv_summary_data:
            agg = bv_summary_data.get("aggregateRating") or bv_summary_data
            result["rating"] = self._to_float(agg.get("ratingValue"))
            result["review_count"] = self._to_int(agg.get("reviewCount"))

        # 5. BV 评论数据（从 Shadow DOM 提取）
        reviews = self._extract_reviews_from_dom(tab)
        reviews = self._process_review_images(reviews)

        # 6. 库存状态（仅从 JSON-LD offers.availability 判断）
        if product_ld:
            avail = (product_ld.get("offers") or {}).get("availability", "")
            if "OutOfStock" in avail:
                result["stock_status"] = "out_of_stock"
            elif "InStock" in avail:
                result["stock_status"] = "in_stock"
        if not result["stock_status"]:
            result["stock_status"] = "unknown"

        self._scrape_count += 1
        # 随机延迟，降低反爬检测风险
        if REQUEST_DELAY:
            tab.wait(REQUEST_DELAY[0], REQUEST_DELAY[1])

        return {"product": result, "reviews": reviews}

    def collect_product_urls(self, category_url: str, max_pages: int = 0) -> list[str]:
        """从分类/列表页采集所有产品 URL
        max_pages: 最大采集页数，0 表示全部
        """
        tab = self.browser.latest_tab
        tab.get(category_url)
        tab.wait.doc_loaded(timeout=PAGE_LOAD_TIMEOUT)
        tab.wait.ele_displayed('tag:h1', timeout=15)

        all_urls = []
        page = 1

        while True:
            # 等待产品列表渲染完成（替代固定 sleep(3)）
            tab.wait.eles_loaded('[class*="ItemDetails"]', timeout=10)

            # 通过 JS 从产品卡片容器中提取链接（class 含 ItemDetails）
            page_urls_raw = tab.run_js("""
                const urls = [];
                const seen = new Set();
                // 方式1: 通过产品卡片容器（class 含 ItemDetails）
                document.querySelectorAll('[class*="ItemDetails"] a[href]').forEach(a => {
                    if (!seen.has(a.href)) { seen.add(a.href); urls.push(a.href); }
                });
                // 方式2: 通过产品卡片容器（class 含 product-card 或 ProductCard）
                if (urls.length === 0) {
                    document.querySelectorAll('[class*="ProductCard"] a[href], [class*="product-card"] a[href]').forEach(a => {
                        if (!seen.has(a.href)) { seen.add(a.href); urls.push(a.href); }
                    });
                }
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

            # 点击下一页（智能点击：优先模拟，被遮挡自动改 JS）
            try:
                next_arrow = tab.ele('css:.iconPagerArrowRight', timeout=3)
                if not next_arrow:
                    break
                next_link = next_arrow.parent()
                if not next_link or next_link.tag != 'a':
                    break
                next_link.click(by_js=None)
                tab.wait.doc_loaded(timeout=PAGE_LOAD_TIMEOUT)
                tab.wait.ele_displayed('tag:h1', timeout=15)
                page += 1
            except Exception:
                break

        # 去重
        seen = set()
        unique = []
        for u in all_urls:
            if u not in seen:
                seen.add(u)
                unique.append(u)

        return unique

    def _wait_for_bv_data(self, tab):
        """轮询等待 BV 评分摘要数据注入（仅 summary，评论从 Shadow DOM 获取）"""
        deadline = time.time() + BV_WAIT_TIMEOUT
        while time.time() < deadline:
            result = tab.run_js(
                "return document.querySelector('#bv-jsonld-bvloader-summary') ? 1 : 0;"
            )
            if result:
                break
            time.sleep(BV_POLL_INTERVAL)

    def _extract_sku_from_dom(self, tab) -> str | None:
        """从 DOM 提取 SKU 号"""
        try:
            sku_ele = tab.ele('text:SKU', timeout=3)
            if sku_ele:
                text = sku_ele.text
                match = re.search(r'SKU[：:\s]*([\w-]+)', text)
                if match:
                    return match.group(1)
        except Exception:
            pass
        return None

    def _click_reviews_tab(self, tab):
        """点击 Reviews Accordion 展开评论区"""
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
        time.sleep(1)

    def _load_all_reviews(self, tab):
        """循环点击 LOAD MORE 按钮，直到加载全部评论
        策略：点击后等待评论数量增加，而不是简单 sleep，避免按钮暂时隐藏导致误判
        """
        max_clicks = 200  # 安全上限
        for i in range(max_clicks):
            # 获取当前评论数 + 点击按钮
            result = tab.run_js("""
                const container = document.querySelector('[data-bv-show="reviews"]');
                if (!container || !container.shadowRoot) return JSON.stringify({clicked: false, count: 0});
                const shadow = container.shadowRoot;
                const count = shadow.querySelectorAll('section').length;
                const btn = shadow.querySelector('button[aria-label*="Load More"]');
                if (btn) {
                    btn.scrollIntoView({block: 'center'});
                    btn.click();
                    return JSON.stringify({clicked: true, count: count});
                }
                return JSON.stringify({clicked: false, count: count});
            """)
            data = json.loads(result) if isinstance(result, str) else (result or {})
            if not data.get("clicked"):
                break
            prev_count = data.get("count", 0)
            # 等待评论数量增加（最多等 5 秒）
            deadline = time.time() + 5
            while time.time() < deadline:
                time.sleep(0.5)
                new_count = tab.run_js("""
                    const c = document.querySelector('[data-bv-show="reviews"]');
                    if (!c || !c.shadowRoot) return 0;
                    return c.shadowRoot.querySelectorAll('section').length;
                """)
                if isinstance(new_count, int) and new_count > prev_count:
                    break

    def _scroll_all_reviews(self, tab):
        """滚动浏览所有评论，触发图片懒加载"""
        total = tab.run_js("""
            const c = document.querySelector('[data-bv-show="reviews"]');
            return c && c.shadowRoot ? c.shadowRoot.querySelectorAll('section').length : 0;
        """)
        if not total:
            return
        # 逐个 section 滚动到视口中央
        for i in range(total):
            tab.run_js(f"""
                const c = document.querySelector('[data-bv-show="reviews"]');
                if (c && c.shadowRoot) {{
                    const s = c.shadowRoot.querySelectorAll('section')[{i}];
                    if (s) s.scrollIntoView({{block: 'center'}});
                }}
            """)
            time.sleep(0.2)
        time.sleep(1)

    def _extract_reviews_from_dom(self, tab) -> list:
        """从 BV Shadow DOM 提取所有评论数据"""
        self._click_reviews_tab(tab)
        self._load_all_reviews(tab)
        self._scroll_all_reviews(tab)

        raw = tab.run_js("""
            const container = document.querySelector('[data-bv-show="reviews"]');
            if (!container || !container.shadowRoot) return '[]';
            const shadow = container.shadowRoot;

            // 只选叶子级评论 section（不包含子 section，排除外层包裹容器）
            const sections = Array.from(shadow.querySelectorAll('section')).filter(
                s => s.querySelector('button[class*="16dr7i1-6"]') && !s.querySelector('section')
            );

            const reviews = [];
            const seen = new Set();
            for (const s of sections) {
                const authorEl = s.querySelector('button[class*="16dr7i1-6"]');
                const author = authorEl ? authorEl.textContent.trim() : '';
                const headlineEl = s.querySelector('h3');
                const headline = headlineEl ? headlineEl.textContent.trim() : '';

                const key = author + '|' + headline;
                if (seen.has(key)) continue;
                seen.add(key);

                const bodyEl = s.querySelector('p');
                const body = bodyEl ? bodyEl.textContent.trim() : '';

                let rating = null;
                const ratingEl = s.querySelector('span[class*="bm6gry"]');
                if (ratingEl) {
                    const m = ratingEl.textContent.match(/(\\d+)\\s+out\\s+of\\s+5/);
                    if (m) rating = parseInt(m[1]);
                }

                const dateEl = s.querySelector('span[class*="g3jej5"]');
                const date = dateEl ? dateEl.textContent.trim() : '';

                const imgs = [];
                s.querySelectorAll('.photos-tile img').forEach(img => {
                    const src = img.getAttribute('src');
                    if (src && src.includes('photos-us.bazaarvoice.com')) {
                        imgs.push(src);
                    }
                });

                reviews.push({author, headline, body, rating, date_published: date, images: imgs});
            }
            return JSON.stringify(reviews);
        """)
        return json.loads(raw) if isinstance(raw, str) else (raw or [])

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

    def close(self):
        try:
            self.browser.quit()
        except Exception:
            pass
