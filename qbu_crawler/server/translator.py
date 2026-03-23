"""Background translation worker — DB-as-queue pattern.

Polls for untranslated reviews, sends them to LLM in batches,
and persists results back to SQLite. Runs as a daemon thread.
Supports concurrent LLM calls via TRANSLATE_WORKERS config.
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Event, Thread

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


class TranslationWorker:
    """Daemon thread that translates reviews in the background.

    Fetches batch_size * concurrency reviews per round, splits into
    sub-batches, and sends them to LLM concurrently.
    """

    # Backoff delays (seconds) for consecutive transient failures
    _BACKOFF_DELAYS = [30, 60, 120, 300]

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

    def _translate_batch(self, reviews: list) -> tuple[int, int] | None:
        """Translate a single sub-batch.
        Returns (translated_count, skipped_count) on success, None on transient error.
        """
        items_payload = [
            {"index": i, "headline": r.get("headline") or "", "body": r.get("body") or ""}
            for i, r in enumerate(reviews)
        ]
        prompt = (
            "请将以下英文产品评论的 headline 和 body 翻译为中文，"
            "保持原意，语言自然流畅。\n"
            "以 JSON 数组形式返回，每个元素包含 index、headline_cn、body_cn 三个字段。\n"
            "不要返回其他内容。\n\n"
            f"输入：\n{json.dumps(items_payload, ensure_ascii=False)}"
        )

        try:
            raw = self._call_llm(self._client, [{"role": "user", "content": prompt}])
            cleaned = _strip_markdown_json(raw)
            results = json.loads(cleaned)

            translated_count = 0
            empty_indices = []
            for item in results:
                idx = item.get("index")
                if idx is None or idx >= len(reviews):
                    continue
                # 兼容 LLM 返回 headline_cn/body_cn 或 headline/body 字段名
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

            # Non-transient error (bad JSON, LLM refused, etc.)
            logger.warning("TranslationWorker: batch failed — %s", exc)
            for review in reviews:
                models.increment_translate_retries(
                    review["id"],
                    max_retries=config.TRANSLATE_MAX_RETRIES,
                )
            return (0, len(reviews))

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
            content = response.choices[0].message.content or ""
            if not content.strip():
                raise ValueError(f"LLM returned empty content in choices object")
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
