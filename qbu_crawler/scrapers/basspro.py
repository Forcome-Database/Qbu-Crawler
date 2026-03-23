import json
import logging
import re
import time

from qbu_crawler.scrapers.base import BaseScraper
from qbu_crawler.config import BV_WAIT_TIMEOUT, BV_POLL_INTERVAL, PAGE_LOAD_TIMEOUT

logger = logging.getLogger(__name__)


class BassProScraper(BaseScraper):

    SITE_LOAD_MODE = "normal"       # Akamai challenge 需要完整加载
    SITE_NEEDS_USER_DATA = True     # 需要用户数据绕过 Akamai
    SITE_RESTART_SAFE = False       # 重启会丢 _abck cookie

    def _dismiss_age_gate(self, tab):
        """检测并关闭年龄验证弹窗（部分产品页会触发，如枪械/弹药相关）

        弹窗结构：
        div.styles_DisclosureContent__*
          ├── div.restriction_disclosure_container  (标题+描述+问题)
          └── div.styles_DiscolusreButtonsWrapper__*
              ├── button (Yes) ← 带 DisclosurePrimaryButton class
              └── button (No)

        使用多级备用选择器，防止 CSS Module hash 变化导致失效：
        1. 精确 class（当前有效）
        2. 按钮包装器内首个 button
        3. JS 文本匹配兜底
        """
        try:
            # 先快速检测弹窗是否存在（用稳定的非 hash class）
            gate = tab.ele('css:.restriction_disclosure_container', timeout=2)
            if not gate:
                return

            # 选择器优先级：精确 class > 包装器首个按钮 > JS 文本匹配
            btn = (
                tab.ele('css:button[class*="DisclosurePrimaryButton"]', timeout=1)
                or tab.ele('css:div[class*="DiscolusreButtonsWrapper"] button:first-child', timeout=1)
            )
            if not btn:
                # 兜底：通过 JS 找文本为 Yes/YES 的 button（不区分大小写）
                btn = tab.run_js("""
                    const buttons = document.querySelectorAll('button');
                    for (const b of buttons) {
                        if (b.textContent.trim().toLowerCase() === 'yes') return b;
                    }
                    return null;
                """)

            if btn:
                btn.click()
                logger.info("  [年龄验证] 已自动点击 Yes 关闭弹窗")
                tab.wait(0.5, 1)
            else:
                logger.warning("  [年龄验证] 检测到弹窗但未找到 Yes 按钮")
        except Exception:
            pass  # 无弹窗或异常，正常继续

    def scrape(self, url: str) -> dict:
        self._maybe_restart_browser()

        tab = self._get_page(url)
        # eager 模式下 get() 在 DOM 就绪后自动返回
        self._dismiss_age_gate(tab)
        # 等待页面主要内容加载
        tab.wait.ele_displayed('tag:h1', timeout=15)
        self._check_url_match(tab, url)
        # 等待 BV 组件加载（容器一定会出现，但 JSON-LD 数据只有有评论时才有）
        bv_container = tab.ele('css:.bv_main_container', timeout=10)
        # 滚动到 BV 组件位置，触发懒加载（BV 不在视口内不会注入 reviews-data）
        if bv_container:
            bv_container.scroll.to_see()
        # 轮询等待 BV JSON-LD 数据注入（summary 和 reviews-data 注入时序不确定）
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

        self._increment_and_delay(tab)

        data = {"product": result, "reviews": reviews}
        self._validate_product(data, url)
        return data

    def collect_product_urls(self, category_url: str, max_pages: int = 0) -> list[str]:
        """从分类/列表页采集所有产品 URL
        max_pages: 最大采集页数，0 表示全部
        """
        tab = self._get_page(category_url)
        tab.wait.doc_loaded(timeout=PAGE_LOAD_TIMEOUT)
        self._dismiss_age_gate(tab)
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
        """点击 Reviews Accordion 展开评论区（多选择器降级）"""
        tab.run_js("""
            let clicked = false;
            // S1: CSS Modules 语义前缀 [class*="AccordionWrapper"] > [class*="Title"]
            document.querySelectorAll('[class*="AccordionWrapper"]').forEach(acc => {
                if (clicked) return;
                const title = acc.querySelector('[class*="Title"]');
                if (title && title.textContent.includes('Reviews')) {
                    title.click();
                    clicked = true;
                }
            });
            // S2: ARIA role="region" aria-label="Section Title" 文本为 Reviews
            if (!clicked) {
                document.querySelectorAll('[role="region"][aria-label="Section Title"]').forEach(el => {
                    if (clicked) return;
                    if (el.textContent.trim() === 'Reviews') {
                        // 点击最近的可点击祖先（cursor: pointer）
                        let p = el.parentElement;
                        for (let i = 0; i < 5 && p; i++) {
                            if (window.getComputedStyle(p).cursor === 'pointer') {
                                p.click();
                                clicked = true;
                                break;
                            }
                            p = p.parentElement;
                        }
                    }
                });
            }
        """)
        time.sleep(1)

    def _load_all_reviews(self, tab):
        """循环点击 LOAD MORE 按钮加载评论。
        受 config.MAX_REVIEWS 限制，防止加载过多评论导致浏览器内存耗尽或 JS 超时。
        """
        from qbu_crawler.config import MAX_REVIEWS
        max_clicks = 200  # 安全上限
        for i in range(max_clicks):
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

            # 检查是否达到评论数上限
            if MAX_REVIEWS > 0 and prev_count >= MAX_REVIEWS:
                logger.info(f"已加载 {prev_count} 条评论，达到上限 {MAX_REVIEWS}，停止加载更多")
                break

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
        """批量滚动评论区，触发图片懒加载。
        每 BATCH_SIZE 个 section 滚动一次到最后一个，减少 JS 调用次数。
        滚完后额外对含 .photos-tile 的 section 逐个定向滚动，确保评论照片触发加载。
        """
        BATCH_SIZE = 20
        total = tab.run_js("""
            const c = document.querySelector('[data-bv-show="reviews"]');
            return c && c.shadowRoot ? c.shadowRoot.querySelectorAll('section').length : 0;
        """)
        if not total:
            return
        # 按批次滚动：每批滚到该批最后一个 section，停留足够时间触发懒加载
        for batch_end in range(BATCH_SIZE - 1, total, BATCH_SIZE):
            idx = min(batch_end, total - 1)
            tab.run_js(f"""
                const c = document.querySelector('[data-bv-show="reviews"]');
                if (c && c.shadowRoot) {{
                    const s = c.shadowRoot.querySelectorAll('section')[{idx}];
                    if (s) s.scrollIntoView({{block: 'end'}});
                }}
            """)
            time.sleep(0.3)
        # 确保最后一批也被滚动到
        if (total - 1) % BATCH_SIZE != BATCH_SIZE - 1:
            tab.run_js(f"""
                const c = document.querySelector('[data-bv-show="reviews"]');
                if (c && c.shadowRoot) {{
                    const s = c.shadowRoot.querySelectorAll('section')[{total - 1}];
                    if (s) s.scrollIntoView({{block: 'end'}});
                }}
            """)
            time.sleep(0.3)
        time.sleep(1)

        # 定向滚动：对含 .photos-tile 但图片未加载的 section 逐个滚动，触发懒加载
        photo_indices = tab.run_js("""
            const c = document.querySelector('[data-bv-show="reviews"]');
            if (!c || !c.shadowRoot) return '[]';
            const indices = [];
            c.shadowRoot.querySelectorAll('section').forEach((s, i) => {
                const tile = s.querySelector('.photos-tile');
                if (tile && !tile.querySelector('img[src*="photos-us.bazaarvoice.com"]')) {
                    indices.push(i);
                }
            });
            return JSON.stringify(indices);
        """)
        unloaded = json.loads(photo_indices) if isinstance(photo_indices, str) else (photo_indices or [])
        if unloaded:
            logger.debug(f"  {len(unloaded)} 个评论照片未加载，定向滚动触发懒加载")
            for idx in unloaded:
                tab.run_js(f"""
                    const c = document.querySelector('[data-bv-show="reviews"]');
                    if (c && c.shadowRoot) {{
                        const s = c.shadowRoot.querySelectorAll('section')[{idx}];
                        if (s) s.scrollIntoView({{block: 'center'}});
                    }}
                """)
                time.sleep(0.5)
            time.sleep(1)

    def _extract_reviews_from_dom(self, tab) -> list:
        """从 BV Shadow DOM 提取所有评论数据（分批提取，避免 JS 超时）"""
        try:
            self._click_reviews_tab(tab)
            self._load_all_reviews(tab)
            self._scroll_all_reviews(tab)
        except Exception as e:
            logger.warning(f"评论加载/滚动阶段异常，尝试提取已加载的评论: {e}")

        # 先获取评论总数
        total = tab.run_js("""
            const c = document.querySelector('[data-bv-show="reviews"]');
            if (!c || !c.shadowRoot) return 0;
            return c.shadowRoot.querySelectorAll('section').length;
        """) or 0

        if not total:
            return []

        # 分批提取，每批 50 个 section，避免单次 JS 执行超时
        EXTRACT_BATCH = 50
        all_reviews = []
        seen = set()

        for batch_start in range(0, total, EXTRACT_BATCH):
            batch_end = min(batch_start + EXTRACT_BATCH, total)
            raw = tab.run_js(f"""
                const container = document.querySelector('[data-bv-show="reviews"]');
                if (!container || !container.shadowRoot) return '[]';
                const shadow = container.shadowRoot;
                const allSections = shadow.querySelectorAll('section');
                const sections = [];
                for (let i = {batch_start}; i < {batch_end} && i < allSections.length; i++) {{
                    const s = allSections[i];
                    if (!s.querySelector('section') && (
                        s.querySelector('[data-bv-v="contentItem"]') ||
                        s.querySelector('button[class*="16dr7i1-6"]')
                    )) sections.push(s);
                }}

                function findFirst(root, ...sels) {{
                    for (const sel of sels) {{
                        const el = root.querySelector(sel);
                        if (el) return el;
                    }}
                    return null;
                }}

                const reviews = [];
                for (const s of sections) {{
                    const header = s.querySelector('[data-bv-v="contentHeader"]');
                    const summary = s.querySelector('[data-bv-v="contentSummary"]');

                    const authorEl = findFirst(
                        header || s,
                        'button[class*="16dr7i1-6"]',
                        'button.bv-rnr-action-bar',
                        'button[aria-label^="See"]'
                    );
                    const author = authorEl ? authorEl.textContent.trim() : '';

                    const headlineEl = (header || s).querySelector('h3');
                    const headline = headlineEl ? headlineEl.textContent.trim() : '';

                    let body = '';
                    if (summary && summary.children[0]) {{
                        body = summary.children[0].textContent.trim();
                    }} else {{
                        const pEl = s.querySelector('p');
                        if (pEl) body = pEl.textContent.trim();
                    }}

                    let rating = null;
                    const ratingEl = findFirst(
                        header || s,
                        '[role="img"][aria-label*="out of 5"]',
                        'span[class*="bm6gry"]'
                    );
                    if (ratingEl) {{
                        const label = ratingEl.getAttribute('aria-label') || ratingEl.textContent;
                        const m = label.match(/(\\d+)\\s+out\\s+of\\s+5/);
                        if (m) rating = parseInt(m[1]);
                    }}

                    let date = '';
                    const dateEl = (header || s).querySelector('span[class*="g3jej5"]');
                    if (dateEl) {{
                        date = dateEl.textContent.trim();
                    }} else {{
                        (header || s).querySelectorAll('span').forEach(sp => {{
                            if (!date) {{
                                const t = sp.textContent.trim();
                                if (t.match(/\\d+\\s+(days?|months?|years?)\\s+ago/) ||
                                    t.match(/^a\\s+(day|month|year)\\s+ago$/)) {{
                                    date = t;
                                }}
                            }}
                        }});
                    }}

                    const imgs = [];
                    // 多级降级选择器提取评论图片：
                    // S1: BV data 属性 + URL 域名（最稳定）
                    // S2: 旧版 class 选择器（向后兼容）
                    // S3: URL 域名兜底（最宽泛）
                    let photoEls = s.querySelectorAll('[data-bv-v="contentSummary"] img[src*="photos-us.bazaarvoice.com"]');
                    if (!photoEls.length) photoEls = s.querySelectorAll('.photos-tile img');
                    if (!photoEls.length) photoEls = s.querySelectorAll('img[src*="photos-us.bazaarvoice.com"]');
                    photoEls.forEach(img => {{
                        const src = img.getAttribute('src');
                        if (src && src.includes('bazaarvoice.com')
                            && !src.includes('apps.bazaarvoice.com')
                            && !src.includes('YXR0cmlidXRpb25sb2dv')) {{
                            // 排除 apps.bazaarvoice.com（徽章图标）
                            // 排除 URL 含 base64("attributionlogo") 的归属徽标
                            imgs.push(src);
                        }}
                    }});

                    reviews.push({{author, headline, body, rating, date_published: date, images: imgs}});
                }}
                return JSON.stringify(reviews);
            """)
            batch_reviews = json.loads(raw) if isinstance(raw, str) else (raw or [])
            for r in batch_reviews:
                key = (r.get("author", ""), r.get("headline", ""))
                if key not in seen:
                    seen.add(key)
                    all_reviews.append(r)

        return all_reviews
