"""Background translation worker — DB-as-queue pattern.

Polls for untranslated reviews, sends them to LLM in batches,
and persists results back to SQLite. Runs as a daemon thread.
"""

import json
import logging
from threading import Event, Thread

from openai import OpenAI

import config
import models

logger = logging.getLogger(__name__)


def _strip_markdown_json(text: str) -> str:
    """Remove ```json ... ``` wrappers if present."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        text = "\n".join(inner).strip()
    return text


class TranslationWorker:
    """Daemon thread that translates reviews in the background."""

    def __init__(self, interval: int = 60, batch_size: int = 20):
        self._interval = interval
        self._batch_size = batch_size
        self._stop_event = Event()
        self._wake_event = Event()
        self._thread = Thread(target=self._run, daemon=True, name="translation-worker")
        self._client: OpenAI | None = None

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
        logger.info("TranslationWorker: started (interval=%ds, batch=%d)", self._interval, self._batch_size)

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
                has_more = self._process_batch()
                # If there are more pending reviews, loop immediately
                while has_more and not self._stop_event.is_set():
                    has_more = self._process_batch()
            except Exception:
                logger.exception("TranslationWorker: unexpected error in loop")

    def _process_batch(self) -> bool:
        """Process one batch. Returns True if there may be more pending."""
        pending = models.get_pending_translations(limit=self._batch_size)
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
            return len(pending) == self._batch_size

        # Build LLM prompt
        items_payload = [
            {"index": i, "headline": r.get("headline") or "", "body": r.get("body") or ""}
            for i, r in enumerate(to_translate)
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

            # Track which indices were returned
            translated_indices = set()
            for item in results:
                idx = item.get("index")
                if idx is None or idx >= len(to_translate):
                    continue
                review = to_translate[idx]
                models.update_translation(
                    review["id"],
                    item.get("headline_cn", ""),
                    item.get("body_cn", ""),
                    "done",
                )
                translated_indices.add(idx)

            # Reviews NOT returned by LLM stay as NULL — picked up next round
            logger.info(
                "TranslationWorker: batch translated %d/%d reviews",
                len(translated_indices),
                len(to_translate),
            )

        except Exception as exc:
            # Entire batch failed — increment retries for all
            logger.warning("TranslationWorker: batch failed — %s", exc)
            for review in to_translate:
                models.increment_translate_retries(
                    review["id"],
                    max_retries=config.TRANSLATE_MAX_RETRIES,
                )

        return len(pending) == self._batch_size

    def _call_llm(self, client: OpenAI | None, messages: list[dict]) -> str:
        """Call the LLM API. Separated for testability."""
        if client is None:
            raise RuntimeError("OpenAI client not initialized")
        response = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=messages,
        )
        return response.choices[0].message.content or ""
