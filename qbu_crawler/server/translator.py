"""Background translation worker — DB-as-queue pattern.

Polls for untranslated reviews, sends them to LLM in batches,
and persists results back to SQLite. Runs as a daemon thread.
Supports concurrent LLM calls via TRANSLATE_WORKERS config.
"""

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Event, Thread

from json_repair import repair_json
from openai import APIStatusError, APIConnectionError, APITimeoutError, OpenAI

from qbu_crawler import config, models

logger = logging.getLogger(__name__)

# HTTP status codes that indicate transient API errors (not review-specific)
_TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}


def _is_transient_error(exc: Exception) -> bool:
    """Check if an exception is a transient API error that should NOT consume retries."""
    if isinstance(exc, (APIConnectionError, APITimeoutError)):
        return True
    if isinstance(exc, APIStatusError) and exc.status_code in _TRANSIENT_STATUS_CODES:
        return True
    # Empty/HTML response from API gateway (rate limit, auth failure, content filter)
    if isinstance(exc, (ValueError, json.JSONDecodeError)):
        return True
    return False


def _strip_markdown_json(text: str) -> str:
    """Remove ```json ... ``` wrappers if present."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        text = "\n".join(inner).strip()
    return text


# Control characters that are invalid/problematic in JSON strings,
# excluding \t (0x09), \n (0x0A), \r (0x0D) which are legal.
_CONTROL_CHAR_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufffe\uffff]')


def _sanitize_text(text: str | None) -> str:
    """Remove control characters and invalid Unicode from text before LLM prompt."""
    if not text:
        return ""
    # Strip control chars (keep \t \n \r)
    text = _CONTROL_CHAR_RE.sub("", text)
    # Remove surrogate pairs (invalid in JSON)
    text = text.encode("utf-8", errors="ignore").decode("utf-8", errors="ignore")
    return text


_VALID_SENTIMENTS = {"positive", "negative", "mixed", "neutral"}

# Label taxonomy for combined translation + analysis prompt
_LABEL_TAXONOMY = {
    "negative": [
        "quality_stability",
        "structure_design",
        "assembly_installation",
        "material_finish",
        "cleaning_maintenance",
        "noise_power",
        "packaging_shipping",
        "service_fulfillment",
    ],
    "positive": [
        "easy_to_use",
        "solid_build",
        "good_value",
        "easy_to_clean",
        "strong_performance",
        "good_packaging",
    ],
}


class TranslationWorker:
    """Daemon thread that translates reviews in the background.

    Fetches batch_size * concurrency reviews per round, splits into
    sub-batches, and sends them to LLM concurrently.
    """

    # Backoff delays (seconds) for consecutive transient failures
    _BACKOFF_DELAYS = [30, 60, 120, 300]

    _prompt_version = "v2"

    def __init__(self, interval: int = 60, batch_size: int = 20, concurrency: int = 1):
        self._interval = interval
        self._batch_size = batch_size
        self._concurrency = max(1, concurrency)
        self._stop_event = Event()
        self._wake_event = Event()
        self._thread = Thread(target=self._run, daemon=True, name="translation-worker")
        self._client: OpenAI | None = None
        self._consecutive_failures = 0

    def start(self):
        """Start the worker thread. No-op if LLM is not configured."""
        if not config.LLM_API_KEY:
            logger.info("TranslationWorker: LLM_API_KEY not set, skipping start")
            return
        self._client = OpenAI(
            api_key=config.LLM_API_KEY,
            base_url=config.LLM_API_BASE or None,
        )
        self._thread.start()
        logger.info(
            "TranslationWorker: started (interval=%ds, batch=%d, concurrency=%d)",
            self._interval, self._batch_size, self._concurrency,
        )

    def stop(self):
        """Signal the worker to stop."""
        self._stop_event.set()
        self._wake_event.set()  # unblock wait

    def trigger(self):
        """Wake the worker immediately (called after reviews are saved)."""
        self._wake_event.set()

    def _run(self):
        """Main loop: poll → translate → sleep/wait."""
        while not self._stop_event.is_set():
            self._wake_event.clear()
            self._wake_event.wait(timeout=self._interval)

            if self._stop_event.is_set():
                break

            try:
                has_more = self._process_round()
                # If there are more pending reviews, loop immediately
                while has_more and not self._stop_event.is_set():
                    has_more = self._process_round()
            except Exception:
                logger.exception("TranslationWorker: unexpected error in loop")

    def _process_round(self) -> bool:
        """Process one round (multiple concurrent batches).
        Returns True if there may be more pending.
        Returns False on transient API errors or no pending reviews.
        """
        fetch_limit = self._batch_size * self._concurrency
        pending = models.get_pending_translations(limit=fetch_limit)
        if not pending:
            return False

        # Separate empty-content reviews (mark done without LLM call)
        to_translate = []
        for review in pending:
            headline = review.get("headline") or ""
            body = review.get("body") or ""
            if not headline.strip() and not body.strip():
                models.update_translation(review["id"], "", "", "done")
            else:
                to_translate.append(review)

        if not to_translate:
            return len(pending) == fetch_limit

        # Split into sub-batches
        sub_batches = []
        for i in range(0, len(to_translate), self._batch_size):
            sub_batches.append(to_translate[i:i + self._batch_size])

        # Process sub-batches concurrently
        total_translated = 0
        total_skipped = 0
        had_transient_error = False

        if self._concurrency == 1 or len(sub_batches) == 1:
            # Single-threaded fast path
            for batch in sub_batches:
                result = self._translate_batch(batch)
                if result is None:
                    had_transient_error = True
                    break
                total_translated += result[0]
                total_skipped += result[1]
        else:
            with ThreadPoolExecutor(max_workers=self._concurrency) as pool:
                futures = {
                    pool.submit(self._translate_batch, batch): batch
                    for batch in sub_batches
                }
                for future in as_completed(futures):
                    result = future.result()
                    if result is None:
                        had_transient_error = True
                    else:
                        total_translated += result[0]
                        total_skipped += result[1]

        if total_translated > 0 or total_skipped > 0:
            logger.info(
                "TranslationWorker: round done — translated %d, skipped %d (from %d sub-batches)",
                total_translated, total_skipped, len(sub_batches),
            )

        if had_transient_error:
            return False  # break while-has-more loop, let interval provide backoff

        # 如果本轮没有任何实际翻译（全部空输出），中断循环等下一轮，避免死循环
        if total_translated == 0:
            return False

        self._consecutive_failures = 0
        return len(pending) == fetch_limit

    def _build_analysis_prompt(self, items_payload: list[dict]) -> str:
        """Build a combined translation + structured analysis prompt.

        Each item in *items_payload* must have: index, headline, body, rating, product_name.
        Returns a single user-message string asking the LLM for JSON array output.
        """
        return (
            "你是一个产品评论分析专家。请对以下英文产品评论同时完成【翻译】和【结构化分析】。\n\n"
            "Product name and rating are provided per-review for context-aware analysis.\n\n"
            "## 任务\n"
            "1. 将 headline 和 body 翻译为中文（headline_cn, body_cn），保持原意，语言自然流畅。\n"
            "2. 判断整体情感倾向 sentiment（必须为 positive / negative / mixed / neutral 之一）。\n"
            "3. 给出情感强度 sentiment_score（0.0-1.0，1.0 表示极端正面/负面）。\n"
            "4. 从下方标签分类中选择适用的标签（可多选，也可不选）。\n"
            '5. 提取 2-5 个中文特征短语 features（如"做工精良"、"尺寸偏小"）。\n'
            "6. 用一句话总结核心洞察（insight_cn 中文, insight_en 英文）。\n"
            "7. 判断影响类别 impact_category（必须为 safety / functional / durability / cosmetic / service 之一）：\n"
            "   - safety: 涉及人身安全风险（金属碎屑进入食物、使用中断裂、爆炸等）\n"
            "   - functional: 产品无法执行核心功能\n"
            "   - durability: 初期可用但短期内退化/损坏\n"
            "   - cosmetic: 外观问题、轻微美观缺陷\n"
            "   - service: 物流、客服、履约问题\n"
            "8. 提取具体失效模式 failure_mode（一个中文短语，如'齿轮磨损'、'密封圈漏肉'、'主轴金属屑脱落'）。\n\n"
            f"## 情感判断参考\n"
            f"- rating <= {config.NEGATIVE_THRESHOLD} 通常倾向 negative\n"
            f"- rating >= 4 通常倾向 positive\n"
            f"- 但以实际评论内容为准，rating 仅作参考\n\n"
            "## 标签分类（Label Taxonomy）\n"
            f"  负面: {', '.join(_LABEL_TAXONOMY['negative'])}\n"
            f"  正面: {', '.join(_LABEL_TAXONOMY['positive'])}\n\n"
            '## 输出格式\n'
            '返回一个 JSON 对象 {"results": [...]}, 数组中每个元素包含：\n'
            "- index: 对应输入的序号\n"
            "- headline_cn: 中文标题\n"
            "- body_cn: 中文正文\n"
            "- sentiment: positive / negative / mixed / neutral\n"
            "- sentiment_score: 0.0-1.0\n"
            "- labels: [{\"code\": \"LABEL_CODE\", \"polarity\": \"positive|negative\", "
            "\"severity\": \"low|medium|high\", \"confidence\": 0.0-1.0}]\n"
            "- features: [\"中文特征短语\", ...]\n"
            "- insight_cn: 一句话中文洞察\n"
            "- insight_en: 一句话英文洞察\n"
            "- impact_category: safety | functional | durability | cosmetic | service\n"
            "- failure_mode: \"具体失效模式中文短语\"\n\n"
            '不要返回其他内容，只返回 JSON 对象。\n\n'
            f"输入：\n{json.dumps(items_payload, ensure_ascii=False)}"
        )

    def _analyze_and_translate_batch(self, reviews: list, _split_depth: int = 0) -> tuple[int, int] | None:
        """Translate and analyze a single sub-batch in one LLM call.

        Returns (translated_count, skipped_count) on success, None on transient error.
        This replaces the old _translate_batch with a combined translation + analysis prompt.
        Translation saving always takes priority — analysis failure never blocks translation.
        """
        items_payload = [
            {
                "index": i,
                "headline": _sanitize_text(r.get("headline")),
                "body": _sanitize_text(r.get("body")),
                "rating": r.get("rating"),
                "product_name": _sanitize_text(r.get("product_name")),
            }
            for i, r in enumerate(reviews)
        ]
        prompt = self._build_analysis_prompt(items_payload)

        try:
            raw = self._call_llm(self._client, [{"role": "user", "content": prompt}])
            cleaned = _strip_markdown_json(raw)
            try:
                parsed = json.loads(cleaned)
            except json.JSONDecodeError:
                logger.debug("TranslationWorker: raw JSON invalid, attempting repair")
                parsed = json.loads(repair_json(cleaned))
            results = parsed.get("results", parsed) if isinstance(parsed, dict) else parsed
            if not isinstance(results, list):
                raise ValueError(f"Expected list of results, got {type(results).__name__}")

            translated_count = 0
            empty_indices = []
            for item in results:
                if not isinstance(item, dict):
                    continue
                idx = item.get("index")
                if not isinstance(idx, int) or idx < 0 or idx >= len(reviews):
                    continue
                # --- Translation (priority) ---
                headline_cn = (item.get("headline_cn") or "").strip()
                body_cn = (item.get("body_cn") or "").strip()
                if not headline_cn and not body_cn:
                    headline_cn = (item.get("headline") or "").strip()
                    body_cn = (item.get("body") or "").strip()
                review = reviews[idx]
                orig_headline = (review.get("headline") or "").strip()
                orig_body = (review.get("body") or "").strip()
                # 只有翻译结果非空才标记 done；LLM 截断导致的空翻译留给下一轮
                if not headline_cn and not body_cn and (orig_headline or orig_body):
                    empty_indices.append(idx)
                    continue
                models.update_translation(
                    review["id"],
                    headline_cn,
                    body_cn,
                    "done",
                )
                translated_count += 1

                # --- Analysis (best-effort, never blocks translation) ---
                try:
                    sentiment = (item.get("sentiment") or "").strip().lower()
                    if sentiment not in _VALID_SENTIMENTS:
                        logger.debug("Invalid sentiment %r for review %d, skipping analysis", sentiment, review["id"])
                        continue  # skip analysis if sentiment invalid
                    sentiment_score = item.get("sentiment_score")
                    if sentiment_score is not None:
                        sentiment_score = float(sentiment_score)
                    labels = item.get("labels") if isinstance(item.get("labels"), list) else None
                    features = item.get("features") if isinstance(item.get("features"), list) else None
                    insight_cn = (item.get("insight_cn") or "").strip() or None
                    insight_en = (item.get("insight_en") or "").strip() or None
                    impact_category = (item.get("impact_category") or "").strip().lower() or None
                    if impact_category and impact_category not in ("safety", "functional", "durability", "cosmetic", "service"):
                        impact_category = None
                    failure_mode = (item.get("failure_mode") or "").strip() or None

                    models.save_review_analysis(
                        review_id=review["id"],
                        sentiment=sentiment,
                        sentiment_score=sentiment_score,
                        labels=labels,
                        features=features,
                        insight_cn=insight_cn,
                        insight_en=insight_en,
                        llm_model=config.LLM_MODEL,
                        prompt_version=self._prompt_version,
                        impact_category=impact_category,
                        failure_mode=failure_mode,
                    )
                except Exception:
                    logger.debug(
                        "TranslationWorker: analysis save failed for review %d, skipping",
                        review["id"],
                        exc_info=True,
                    )

            skipped = len(reviews) - translated_count
            if empty_indices:
                logger.info(
                    "TranslationWorker: %d/%d reviews got empty LLM output, will retry next round",
                    len(empty_indices), len(reviews),
                )
            self._consecutive_failures = 0
            return (translated_count, skipped)

        except Exception as exc:
            if _is_transient_error(exc):
                self._consecutive_failures += 1
                delay_idx = min(self._consecutive_failures - 1, len(self._BACKOFF_DELAYS) - 1)
                delay = self._BACKOFF_DELAYS[delay_idx]
                logger.warning(
                    "TranslationWorker: transient API error (%s), "
                    "backing off %ds (attempt %d), reviews untouched",
                    exc, delay, self._consecutive_failures,
                )
                self._stop_event.wait(timeout=delay)
                return None  # signal transient error

            # 400 Bad Request with batch > 1: split in half and retry each half
            # This isolates the problematic review(s) without burning retries
            # Depth-limited to prevent excessive API calls (max ~10 levels for batch_size 1024)
            if (isinstance(exc, APIStatusError)
                    and exc.status_code == 400
                    and len(reviews) > 1
                    and _split_depth < 8):
                logger.warning(
                    "TranslationWorker: batch of %d got 400 (depth=%d), splitting to isolate bad review",
                    len(reviews), _split_depth,
                )
                mid = len(reviews) // 2
                r1 = self._analyze_and_translate_batch(reviews[:mid], _split_depth=_split_depth + 1)
                r2 = self._analyze_and_translate_batch(reviews[mid:], _split_depth=_split_depth + 1)
                t = (r1[0] if r1 else 0) + (r2[0] if r2 else 0)
                s = (r1[1] if r1 else mid) + (r2[1] if r2 else len(reviews) - mid)
                return (t, s)

            # Non-transient error (bad JSON, LLM refused, etc.)
            logger.warning("TranslationWorker: batch failed — %s", exc)
            for review in reviews:
                models.increment_translate_retries(
                    review["id"],
                    max_retries=config.TRANSLATE_MAX_RETRIES,
                )
            return (0, len(reviews))

    # Backward compatibility alias
    _translate_batch = _analyze_and_translate_batch

    def _call_llm(self, client: OpenAI | None, messages: list[dict]) -> str:
        """Call the LLM API. Separated for testability.
        Handles both standard OpenAI SDK response objects and raw string/dict
        responses from compatible APIs (e.g. OpenRouter).
        """
        if client is None:
            raise RuntimeError("OpenAI client not initialized")
        response = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=messages,
        )
        # Standard OpenAI SDK response object
        if hasattr(response, "choices"):
            content = (response.choices[0].message.content or "").strip()
            if not content:
                raise ValueError("LLM returned empty content in choices object")
            return content
        # Some compatible APIs return raw dict or JSON string
        if isinstance(response, str):
            if not response.strip():
                raise ValueError("LLM returned empty string response")
            data = json.loads(response)
        elif isinstance(response, dict):
            data = response
        else:
            raise TypeError(f"Unexpected LLM response type: {type(response)}")
        return data["choices"][0]["message"]["content"]
