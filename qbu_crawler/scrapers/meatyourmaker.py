import json
import logging
import time
from qbu_crawler.scrapers.base import BaseScraper
from qbu_crawler.config import (
    BV_WAIT_TIMEOUT, BV_POLL_INTERVAL,
)

logger = logging.getLogger(__name__)


class MeatYourMakerScraper(BaseScraper):

    SITE_LOAD_MODE = "normal"  # BV 脚本需要 normal 模式

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
        self._last_review_extraction_meta = {}
        reviews = self._extract_all_reviews(tab, review_limit=review_limit)
        reviews = self._process_review_images(reviews)

        # 6b. 提取 BV 的 "X Ratings-Only Reviews" 数量（与 basspro 同语义）。
        # mym 的 BV widget 同样会把 ratings-only（仅星级）评论塞进 reviewCount，
        # 但 scraper 不可能抓到没文字内容的评论。该数据让覆盖率统计能正确扣减分母。
        result["ratings_only_count"] = self._extract_ratings_only_count(tab)

        self._increment_and_delay(tab)
        data = {
            "product": result,
            "reviews": reviews,
            "scrape_meta": {
                "review_extraction": self._last_review_extraction_meta,
            },
        }
        self._validate_product(data, url)
        return data

    @staticmethod
    def _extract_ratings_only_count(tab) -> int:
        """从 BV reviews shadow root 读 "X Ratings-Only Reviews" 文字，无则返 0。
        见 BassProScraper._extract_ratings_only_count 的注释，逻辑完全一致。"""
        try:
            n = tab.run_js("""
                const c = document.querySelector('[data-bv-show="reviews"]');
                if (!c || !c.shadowRoot) return 0;
                const text = (c.shadowRoot.querySelector('#bv_review_maincontainer')?.textContent
                             || c.shadowRoot.textContent || '');
                const m = text.match(/(\\d+)\\s+Ratings[-\\s]?Only\\s+Reviews/i);
                return m ? parseInt(m[1], 10) : 0;
            """)
            return int(n or 0)
        except Exception:
            return 0

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
        """强制展开 Reviews toggler section。

        ⚠ 通过浏览器实地验证（2026-04-29，1193465）发现，单纯 `el.click()` 是不可靠的：
        1. SFCC c-toggler 折叠机制：`.c-toggler__content { max-height: 0; overflow: hidden }`，
           BV widget 被剪到 0 高度，IntersectionObserver 收不到 visible 信号 → BV 永远
           不 fetch reviews，shadow root 永远不注入 review section。
        2. click() 行为是 *toggle*：section 起始可能已经处于 expanded 状态（DOM 上带有
           `c-toggler--expanded` 类），盲 click 会反向把它 collapse 掉
           （生产 0.4.17 第 13 轮日志：parent_h=95、inner_len=771、sections=0 即此故障）。
        3. 即便 click 加上了 `c-toggler--expanded` 类，对应站点 CSS 在冷启动会话下也未必
           及时把 max-height 改成 none，content offsetHeight 仍卡在 0。

        因此改为：直接通过 JS 把 toggler 强制设为展开态——
        - outer `.c-toggler` 容器加 `c-toggler--expanded` 类
        - inner `.c-toggler__content` 设 inline style `max-height:none; overflow:visible`
        这一组改动等价于"用户点击 + CSS 应用完成"，且与站点交互保持幂等：
        即使 React 后续重设 inline style，我们也只是不会撤销原本应展开的状态。

        匹配 toggler 文本时容忍后缀（如 "Reviews (92)"）以兼容站点未来变化。"""
        deadline = time.time() + 10
        while time.time() < deadline:
            result = tab.run_js("""
                const togglers = document.querySelectorAll('.c-toggler__element');
                let target = null;
                for (const el of togglers) {
                    const t = (el.textContent || '').trim();
                    if (t === 'Reviews' || t.startsWith('Reviews')) { target = el; break; }
                }
                if (!target) return JSON.stringify({found: false});
                const outer = target.closest('.c-toggler')
                              || target.parentElement;
                const bv = document.querySelector('[data-bv-show="reviews"]');
                const content = bv ? bv.parentElement : null;
                if (!outer || !content) return JSON.stringify({found: true, expanded: false, error: 'no_outer_or_content'});
                outer.classList.add('c-toggler--expanded');
                content.style.maxHeight = 'none';
                content.style.overflow = 'visible';
                return JSON.stringify({
                    found: true,
                    expanded: content.offsetHeight > 100,
                    content_h: content.offsetHeight,
                });
            """)
            try:
                data = json.loads(result) if isinstance(result, str) else (result or {})
            except Exception:
                data = {}
            if data.get("expanded"):
                break
            # toggler 还没渲染上来；继续等
            time.sleep(0.5)
        # React 重渲染窗口期：让强制设的 inline style 稳定下来
        time.sleep(1)

    def _wait_for_shadow_root(self, tab, timeout=30):
        """等待 BV reviews Shadow DOM 加载并真正注入内容。

        ⚠ BV reviews widget 是**视口懒加载 + 网络异步获取**：
        - shadow root 早早创建（仅 host 出现就建）
        - 内部 review section 需要 host 进入视口触发 IntersectionObserver
        - 触发后 BV 还要 fetch reviews API 才能渲染 section

        过去 timeout=10s 在生产冷启动会话下不够：Chrome 刚 attach、cookies 与 BV 缓存
        都是空，要走 bv-loader.js 下载 → BV API 调用 → 渲染整个链路，叠加代理 / 反爬
        延迟会超过 10s（生产 2026-04-29 SKU 1193465 失败：no_shadow_root, pages_seen=0）。

        现在改为：
        1) timeout 默认 30s（覆盖冷启动 + 慢代理）
        2) 轮询期间每 ~3s 重做 scroll-to-see + 重申"强制展开" inline style，
           应对 React 重渲染抹掉 max-height 或 host 飘出视口
        3) 超时时打 diagnostic log，便于后续定位是 host 缺失 / shadow 未建 / 内容未注入
        """
        host_selector = 'css:[data-bv-show="reviews"]'

        def scroll_into_view():
            try:
                host = tab.ele(host_selector, timeout=2)
                if host:
                    host.scroll.to_see(center=True)
            except Exception:
                pass

        def reaffirm_expand():
            """重申"强制展开"：对抗 React 重渲染时把 max-height 抹回 0。"""
            try:
                tab.run_js("""
                    const togglers = document.querySelectorAll('.c-toggler__element');
                    let target = null;
                    for (const el of togglers) {
                        const t = (el.textContent || '').trim();
                        if (t === 'Reviews' || t.startsWith('Reviews')) { target = el; break; }
                    }
                    if (!target) return 0;
                    const outer = target.closest('.c-toggler') || target.parentElement;
                    const bv = document.querySelector('[data-bv-show="reviews"]');
                    const content = bv ? bv.parentElement : null;
                    if (outer) outer.classList.add('c-toggler--expanded');
                    if (content) {
                        content.style.maxHeight = 'none';
                        content.style.overflow = 'visible';
                    }
                    return 1;
                """)
            except Exception:
                pass

        reaffirm_expand()
        scroll_into_view()
        deadline = time.time() + timeout
        last_reaffirm_t = time.time()
        while time.time() < deadline:
            populated = tab.run_js("""
                const c = document.querySelector('[data-bv-show="reviews"]');
                if (!c || !c.shadowRoot) return 0;
                const sr = c.shadowRoot;
                // 任一信号：review section、a.next、bv 内容容器
                if (sr.querySelector('section')) return 1;
                if (sr.querySelector('a.next')) return 1;
                if (sr.querySelector('[data-bv-rid]')) return 1;
                return 0;
            """)
            if populated:
                return True
            # 每 3s 重申强制展开 + 重新滚 host 进视口，对抗 React 抹回 inline style
            # 与 IntersectionObserver 一次性触发后失效
            if time.time() - last_reaffirm_t >= 3:
                reaffirm_expand()
                scroll_into_view()
                last_reaffirm_t = time.time()
            time.sleep(0.5)

        # 超时诊断：抓取当前实际状态便于追踪
        try:
            diag = tab.run_js("""
                const c = document.querySelector('[data-bv-show="reviews"]');
                if (!c) return JSON.stringify({host: false});
                const sr = c.shadowRoot;
                if (!sr) return JSON.stringify({host: true, shadow: false});
                const rect = c.getBoundingClientRect();
                return JSON.stringify({
                    host: true, shadow: true,
                    sections: sr.querySelectorAll('section').length,
                    has_a_next: !!sr.querySelector('a.next'),
                    has_bv_rid: !!sr.querySelector('[data-bv-rid]'),
                    parent_h: c.parentElement ? c.parentElement.offsetHeight : 0,
                    rect_top: Math.round(rect.top),
                    visible: rect.top < window.innerHeight && rect.bottom > 0,
                    inner_len: (sr.innerHTML || '').length
                });
            """)
            logger.warning(f"[mym] _wait_for_shadow_root timeout after {timeout}s; diag={diag}")
        except Exception:
            pass
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
        self._last_review_extraction_meta = {
            "stop_reason": "unknown",
            "pages_seen": 0,
            "review_limit": review_limit,
            "extracted_review_count": 0,
        }
        if not self._wait_for_shadow_root(tab):
            self._last_review_extraction_meta["stop_reason"] = "no_shadow_root"
            return []

        all_reviews = []
        seen = set()
        max_pages = 100

        for page_num in range(max_pages):
            self._last_review_extraction_meta["pages_seen"] = page_num + 1
            page_reviews = self._extract_page_reviews(tab)
            for r in page_reviews:
                key = (r.get("author", ""), r.get("headline", ""))
                if key not in seen:
                    seen.add(key)
                    all_reviews.append(r)
                    self._last_review_extraction_meta["extracted_review_count"] = len(all_reviews)
                    if review_limit and review_limit > 0 and len(all_reviews) >= review_limit:
                        self._last_review_extraction_meta["stop_reason"] = "review_limit"
                        return all_reviews[:review_limit]

            has_next = tab.run_js("""
                const c = document.querySelector('[data-bv-show="reviews"]');
                if (!c || !c.shadowRoot) return false;
                const next = c.shadowRoot.querySelector('a.next');
                if (next) { next.click(); return true; }
                return false;
            """)
            if not has_next:
                self._last_review_extraction_meta["stop_reason"] = "no_next"
                break
            time.sleep(2)
        else:
            self._last_review_extraction_meta["stop_reason"] = "max_pages"

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
