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
        tab.ele('css:.bv_main_container', timeout=10)
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
            const result = {productLD: null, bvSummary: null, bvReviews: null};
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
            // BV reviews (有 id 的 script 或无 id 的 review script)
            const bvr = document.querySelector('#bv-jsonld-reviews-data');
            if (bvr) try { result.bvReviews = JSON.parse(bvr.textContent); } catch(e) {}
            if (!result.bvReviews) {
                document.querySelectorAll('script[type="application/ld+json"]').forEach(s => {
                    try {
                        const d = JSON.parse(s.textContent);
                        if (d.review && !result.bvReviews) result.bvReviews = d;
                    } catch(e) {}
                });
            }
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

        # 5. BV 评论数据
        reviews = self._parse_bv_reviews(data.get("bvReviews"))

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
        """轮询等待 BV JSON-LD 数据注入
        BV 异步注入两个 script 标签：
        - #bv-jsonld-bvloader-summary (评分摘要，先注入)
        - #bv-jsonld-reviews-data (评论详情，后注入，且不一定会注入)
        注入时序不稳定，用轮询方式更可靠
        """
        deadline = time.time() + BV_WAIT_TIMEOUT
        has_summary = False
        has_reviews = False
        while time.time() < deadline:
            result = tab.run_js(
                "return (document.querySelector('#bv-jsonld-bvloader-summary') ? 1 : 0)"
                " + (document.querySelector('#bv-jsonld-reviews-data') ? 2 : 0);"
            )
            has_summary = bool(result & 1)
            has_reviews = bool(result & 2)
            if has_reviews:
                break  # reviews-data 出现说明 BV 数据已完全注入
            if has_summary:
                # summary 已出现但 reviews-data 还没有，再多等一会儿
                time.sleep(BV_POLL_INTERVAL)
                continue
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

    def _parse_bv_reviews(self, data) -> list:
        """解析 BV 评论数据"""
        if not data:
            return []
        raw_reviews = []
        if isinstance(data, list):
            raw_reviews = data
        elif isinstance(data, dict) and "review" in data:
            raw_reviews = data["review"]
        elif isinstance(data, dict) and "@graph" in data:
            raw_reviews = data["@graph"]

        reviews = []
        for r in raw_reviews:
            if not isinstance(r, dict):
                continue
            review = {
                "author": None,
                "headline": r.get("headline") or r.get("name"),
                "body": r.get("reviewBody") or r.get("description"),
                "rating": None,
                "date_published": r.get("datePublished"),
            }
            author = r.get("author")
            if isinstance(author, dict):
                review["author"] = author.get("name")
            elif isinstance(author, str):
                review["author"] = author
            rating = r.get("reviewRating")
            if isinstance(rating, dict):
                review["rating"] = self._to_float(rating.get("ratingValue"))
            elif r.get("ratingValue"):
                review["rating"] = self._to_float(r["ratingValue"])
            reviews.append(review)
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
