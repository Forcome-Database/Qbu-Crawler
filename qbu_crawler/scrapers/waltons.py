import hashlib
import json
import logging
import time
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse

from DrissionPage import ChromiumOptions
from qbu_crawler.scrapers.base import BaseScraper, _has_display
from qbu_crawler.config import (
    HEADLESS, PAGE_LOAD_TIMEOUT, LOAD_MODE, NO_IMAGES,
    RETRY_TIMES, RETRY_INTERVAL,
    BV_WAIT_TIMEOUT, BV_POLL_INTERVAL, MAX_REVIEWS,
)

logger = logging.getLogger(__name__)


class WaltonsScraper(BaseScraper):

    SITE_LOAD_MODE = "normal"  # Cloudflare + TrustSpot 需要 normal 模式

    @staticmethod
    def _build_options() -> ChromiumOptions:
        """覆盖基类：添加反自动化检测参数，绕过 Cloudflare bot 检测"""
        options = ChromiumOptions()
        options.auto_port()
        if HEADLESS:
            if _has_display():
                options.headless()
            options.set_argument('--window-size=1920,1080')
        else:
            options.set_argument('--start-maximized')
        if NO_IMAGES:
            options.no_imgs(True)
        # waltons.com 的 TrustSpot 脚本在 eager 模式下无法初始化，
        # 评分/评论的 JSON-LD 由 TrustSpot 动态注入，必须用 normal 模式
        options.set_load_mode("normal")
        options.set_retry(times=RETRY_TIMES, interval=RETRY_INTERVAL)
        options.set_timeouts(base=10, page_load=PAGE_LOAD_TIMEOUT)
        options.set_argument('--deny-permission-prompts')
        # waltons.com 使用 Cloudflare，需要禁用自动化检测特征
        options.set_argument('--disable-blink-features=AutomationControlled')
        options.set_user_agent(
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/131.0.0.0 Safari/537.36'
        )
        return options

    def scrape(self, url: str, review_limit: int | None = None) -> dict:
        self._maybe_restart_browser()

        tab = self._get_page(url)
        tab.wait.ele_displayed('tag:h1', timeout=15)
        self._check_url_match(tab, url)

        # Extract JSON-LD structured data
        ld_product, ld_reviews_raw = self._extract_jsonld(tab)

        result = {
            "url": url,
            "site": "waltons",
            "name": None,
            "sku": None,
            "price": None,
            "stock_status": "unknown",
            "review_count": 0,
            "rating": None,
        }

        # 1. Parse product data from JSON-LD
        if ld_product:
            result["name"] = ld_product.get("name")
            result["sku"] = ld_product.get("sku")

            offers = ld_product.get("offers")
            if isinstance(offers, dict):
                result["price"] = self._to_float(offers.get("price"))
                avail = offers.get("availability", "")
                if "OutOfStock" in avail:
                    result["stock_status"] = "out_of_stock"
                elif "InStock" in avail:
                    result["stock_status"] = "in_stock"
            elif isinstance(offers, list) and offers:
                result["price"] = self._to_float(offers[0].get("price"))
                avail = offers[0].get("availability", "")
                if "OutOfStock" in avail:
                    result["stock_status"] = "out_of_stock"
                elif "InStock" in avail:
                    result["stock_status"] = "in_stock"

            agg = ld_product.get("aggregateRating")
            if agg:
                result["rating"] = self._to_float(agg.get("ratingValue"))
                result["review_count"] = self._to_int(agg.get("reviewCount")) or 0

        # 2. DOM fallback for missing fields
        if not result["name"]:
            h1 = tab.ele('tag:h1', timeout=2)
            if h1:
                result["name"] = h1.text.strip()

        if not result["sku"]:
            sku_val = tab.run_js("""
                const el = document.querySelector('[data-product-sku]');
                if (el) return el.getAttribute('data-product-sku');
                const meta = document.querySelector('meta[itemprop="sku"]');
                if (meta) return meta.getAttribute('content');
                return null;
            """)
            if sku_val:
                result["sku"] = str(sku_val).strip()

        if result["price"] is None:
            price_text = tab.run_js("""
                const el = document.querySelector('.productView-price .price--withoutTax');
                return el ? el.textContent.trim() : null;
            """)
            if price_text:
                result["price"] = self._to_float(
                    price_text.replace("$", "").replace(",", "")
                )

        # 3. Extract reviews
        self._last_review_extraction_meta = {}
        reviews = self._extract_all_reviews(tab, ld_reviews_raw, review_limit=review_limit)
        reviews = self._process_review_images(reviews)

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

    def _extract_jsonld(self, tab):
        """Extract all JSON-LD scripts and merge Product blocks.

        Returns (merged_product_dict | None, reviews_list).
        The sku-bearing Product is authoritative; other Product blocks
        supplement missing aggregateRating / offers / name.
        """
        raw = tab.run_js("""
            const items = [];
            document.querySelectorAll('script[type="application/ld+json"]').forEach(s => {
                try {
                    const d = JSON.parse(s.textContent);
                    if (Array.isArray(d)) {
                        d.forEach(x => items.push(x));
                    } else {
                        items.push(d);
                    }
                } catch(e) {}
            });
            return JSON.stringify(items);
        """)
        items = json.loads(raw) if isinstance(raw, str) else (raw or [])

        products = [it for it in items if isinstance(it, dict) and it.get("@type") == "Product"]
        if not products:
            return None, []

        # Find the sku-bearing product as authoritative base
        merged = {}
        sku_product = None
        for p in products:
            if p.get("sku"):
                sku_product = p
                break

        # Start with any product, then overlay the sku-bearing one
        for p in products:
            if p is not sku_product:
                # Supplement fields from non-authoritative products
                for key in ("aggregateRating", "offers", "name"):
                    if key in p and key not in merged:
                        merged[key] = p[key]
                # Copy all fields as base
                for k, v in p.items():
                    if k not in merged:
                        merged[k] = v

        # Authoritative product overwrites
        if sku_product:
            merged.update(sku_product)
        elif products:
            # No sku-bearing product found, use first one
            merged.update(products[0])

        # Extract reviews from JSON-LD
        ld_reviews = []
        for p in products:
            if "review" in p:
                revs = p["review"]
                if isinstance(revs, list):
                    ld_reviews.extend(revs)
                elif isinstance(revs, dict):
                    ld_reviews.append(revs)

        return merged, ld_reviews

    def _wait_for_trustspot(self, tab) -> bool:
        """Poll for TrustSpot review widget to load."""
        deadline = time.time() + BV_WAIT_TIMEOUT
        while time.time() < deadline:
            found = tab.run_js(
                "return document.querySelector('.trustspot-widget-review-block') ? 1 : 0;"
            )
            if found:
                return True
            time.sleep(BV_POLL_INTERVAL)
        logger.warning("TrustSpot widget did not load within timeout")
        return False

    def _extract_page_reviews(self, tab) -> list:
        """Extract reviews from TrustSpot DOM (no Shadow DOM)."""
        raw = tab.run_js("""
            const blocks = document.querySelectorAll('.trustspot-widget-review-block');
            const reviews = [];
            blocks.forEach(block => {
                // 跳过 Q&A 条目：TrustSpot 的 .trustspot-widget-review-block 同时
                // 包含评论和问答，Q&A 有 .ts-qa-wrapper 或 h4 问题标题，无 .comment-box
                if (!block.querySelector('.comment-box')) return;
                if (block.querySelector('.ts-qa-wrapper')) return;

                // Author
                const userEl = block.querySelector('.result-box-header .user-name');
                const author = userEl ? userEl.textContent.trim() : '';

                // Date (MM/DD/YYYY)
                const dateEl = block.querySelector('.result-box-header .date span');
                const date_published = dateEl ? dateEl.textContent.trim() : '';

                // Rating: count filled stars
                let rating = null;
                const filledStars = block.querySelectorAll('.ts-widget-review-star.filled');
                if (filledStars.length > 0) {
                    rating = filledStars.length;
                } else {
                    // Fallback: parse title from .stars .ts-stars-1
                    const starEl = block.querySelector('.stars .ts-stars-1[title]');
                    if (starEl) {
                        const m = starEl.getAttribute('title').match(/(\\d+(?:\\.\\d+)?)/);
                        if (m) rating = parseFloat(m[1]);
                    }
                }

                // Body: .comment-box spans, 2nd span is body (1st is aria-label)
                let body = '';
                const spans = block.querySelectorAll('.comment-box span');
                if (spans.length >= 2) {
                    body = spans[1].textContent.trim();
                } else if (spans.length === 1) {
                    body = spans[0].textContent.trim();
                }

                // Images: .description-block img, exclude icons/social/star/avatar
                const images = [];
                block.querySelectorAll('.description-block img').forEach(img => {
                    const src = img.getAttribute('src') || '';
                    if (src &&
                        !src.includes('social') &&
                        !src.includes('star') &&
                        !src.includes('icon') &&
                        !src.includes('avatar')) {
                        images.push(src);
                    }
                });

                // headline is always empty for TrustSpot
                if (body || author) {
                    reviews.push({
                        author: author,
                        headline: '',
                        body: body,
                        rating: rating,
                        date_published: date_published,
                        images: images
                    });
                }
            });
            return JSON.stringify(reviews);
        """)
        return json.loads(raw) if isinstance(raw, str) else (raw or [])

    @staticmethod
    def _parse_ld_reviews(ld_reviews_raw: list) -> list:
        """Convert JSON-LD review array to standard format (fallback)."""
        reviews = []
        for r in ld_reviews_raw:
            if not isinstance(r, dict):
                continue
            author = ""
            author_field = r.get("author")
            if isinstance(author_field, dict):
                author = author_field.get("name", "")
            elif isinstance(author_field, str):
                author = author_field

            rating = None
            rating_field = r.get("reviewRating")
            if isinstance(rating_field, dict):
                try:
                    rating = float(rating_field.get("ratingValue", 0))
                except (ValueError, TypeError):
                    pass

            body = r.get("reviewBody") or r.get("description") or ""
            date_published = r.get("datePublished", "")

            reviews.append({
                "author": author,
                "headline": "",
                "body": body,
                "rating": rating,
                "date_published": date_published,
                "images": [],
            })
        return reviews

    def _extract_all_reviews(self, tab, ld_reviews_raw: list, review_limit: int | None = None) -> list:
        """Extract all reviews: try TrustSpot DOM first, fallback to JSON-LD."""
        self._last_review_extraction_meta = {
            "stop_reason": "unknown",
            "pages_seen": 0,
            "review_limit": review_limit,
            "extracted_review_count": 0,
        }
        trustspot_loaded = self._wait_for_trustspot(tab)
        effective_limit = review_limit if review_limit and review_limit > 0 else MAX_REVIEWS

        if not trustspot_loaded:
            logger.info("TrustSpot not loaded, falling back to JSON-LD reviews")
            parsed_reviews = self._parse_ld_reviews(ld_reviews_raw)
            if effective_limit > 0:
                parsed_reviews = parsed_reviews[:effective_limit]
            self._last_review_extraction_meta.update({
                "stop_reason": "trustspot_not_loaded_jsonld_fallback",
                "extracted_review_count": len(parsed_reviews),
            })
            return parsed_reviews

        all_reviews = []
        seen = set()
        max_pages = 100

        for page_num in range(max_pages):
            self._last_review_extraction_meta["pages_seen"] = page_num + 1
            page_reviews = self._extract_page_reviews(tab)
            new_count = 0
            for r in page_reviews:
                body_hash = hashlib.md5(r.get("body", "").encode()).hexdigest()[:16]
                key = (r.get("author", ""), body_hash)
                if key not in seen:
                    seen.add(key)
                    all_reviews.append(r)
                    new_count += 1
                    self._last_review_extraction_meta["extracted_review_count"] = len(all_reviews)

            logger.info(
                f"  [TrustSpot] 第 {page_num + 1} 页: "
                f"提取 {len(page_reviews)} 条, 新增 {new_count} 条, "
                f"累计 {len(all_reviews)} 条"
            )

            # TrustSpot 的 next-page 按钮永远存在，翻过最后一页后会循环显示重复评论。
            # 因此不能依赖按钮是否存在来终止，必须用"本页无新增评论"来判断已翻完。
            if new_count == 0:
                logger.info("  [TrustSpot] 本页无新增评论，已翻完所有页")
                self._last_review_extraction_meta["stop_reason"] = "no_new_reviews"
                break

            # Check MAX_REVIEWS limit
            if effective_limit > 0 and len(all_reviews) >= effective_limit:
                logger.info(
                    f"  [TrustSpot] 已达评论上限 {effective_limit}，停止翻页"
                )
                all_reviews = all_reviews[:effective_limit]
                self._last_review_extraction_meta.update({
                    "stop_reason": "review_limit",
                    "extracted_review_count": len(all_reviews),
                })
                break

            # Try to click next page
            has_next = tab.run_js("""
                const nextLink = document.querySelector('a.next-page');
                if (nextLink) { nextLink.click(); return true; }
                return false;
            """)
            if not has_next:
                self._last_review_extraction_meta["stop_reason"] = "no_next"
                break
            time.sleep(2)
        else:
            self._last_review_extraction_meta["stop_reason"] = "max_pages"

        return all_reviews

    def collect_product_urls(self, category_url: str, max_pages: int = 0) -> list[str]:
        """Collect product URLs from a BigCommerce category page."""
        # Append limit=100 to URL
        parsed = urlparse(category_url)
        qs = parse_qs(parsed.query)
        qs["limit"] = ["100"]
        new_query = urlencode(qs, doseq=True)
        start_url = urlunparse(parsed._replace(query=new_query))

        tab = self._get_page(start_url)
        tab.wait.doc_loaded(timeout=PAGE_LOAD_TIMEOUT)
        tab.wait.ele_displayed('tag:h1', timeout=15)

        all_urls = []
        page = 1

        while True:
            page_urls_raw = tab.run_js("""
                const urls = [];
                const seen = new Set();
                document.querySelectorAll('.productGrid .product .card-title a[href]').forEach(a => {
                    const href = a.href;
                    if (href && !seen.has(href)) { seen.add(href); urls.push(href); }
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

            # Find next page link
            next_href = tab.run_js("""
                const next = document.querySelector('.pagination-item--next a');
                return next ? next.href : null;
            """)
            if not next_href:
                break

            tab = self._get_page(next_href)
            tab.wait.doc_loaded(timeout=PAGE_LOAD_TIMEOUT)
            tab.wait.ele_displayed('tag:h1', timeout=15)
            page += 1

        # Deduplicate
        seen = set()
        unique = []
        for u in all_urls:
            if u not in seen:
                seen.add(u)
                unique.append(u)
        return unique
