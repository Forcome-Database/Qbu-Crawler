"""Report generation module — query, translate, Excel, email."""

import json
import logging
import os
import smtplib
from datetime import datetime, timezone
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from openai import OpenAI
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

import config
import models

logger = logging.getLogger(__name__)

# ── Data Query ──────────────────────────────────────────────────────────────


def query_report_data(since: datetime) -> tuple[list[dict], list[dict]]:
    """Query products and reviews added since the given UTC timestamp.

    Returns (products, reviews) — both as lists of dicts.
    """
    since_str = since.strftime("%Y-%m-%d %H:%M:%S")

    conn = models.get_conn()
    try:
        product_rows = conn.execute(
            """
            SELECT url, name, sku, price, stock_status, rating, review_count,
                   scraped_at, site, ownership
            FROM products
            WHERE scraped_at >= ?
            ORDER BY scraped_at DESC
            """,
            (since_str,),
        ).fetchall()
        products = [dict(r) for r in product_rows]

        review_rows = conn.execute(
            """
            SELECT p.name AS product_name,
                   r.author, r.headline, r.body, r.rating,
                   r.date_published, r.images, p.ownership
            FROM reviews r
            JOIN products p ON r.product_id = p.id
            WHERE r.scraped_at >= ?
            ORDER BY r.scraped_at DESC
            """,
            (since_str,),
        ).fetchall()
        reviews = []
        for row in review_rows:
            d = dict(row)
            # Normalise images: may be JSON string or None
            if d.get("images") and isinstance(d["images"], str):
                try:
                    d["images"] = json.loads(d["images"])
                except Exception:
                    pass
            reviews.append(d)
    finally:
        conn.close()

    logger.info(
        "query_report_data: since=%s → %d products, %d reviews",
        since_str,
        len(products),
        len(reviews),
    )
    return products, reviews


# ── LLM Translation ─────────────────────────────────────────────────────────


def _call_llm(messages: list[dict]) -> str:
    """Call the configured OpenAI-compatible API and return the raw text."""
    client = OpenAI(
        api_key=config.LLM_API_KEY,
        base_url=config.LLM_API_BASE or None,
    )
    response = client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=messages,
    )
    return response.choices[0].message.content or ""


def _strip_markdown_json(text: str) -> str:
    """Remove ```json ... ``` wrappers if present."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Drop first line (``` or ```json) and last line (```)
        inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        text = "\n".join(inner).strip()
    return text


def translate_reviews(reviews: list[dict]) -> list[dict]:
    """Translate review headlines and bodies to Chinese.

    Each review gets ``headline_cn`` and ``body_cn`` fields added in-place.
    Never raises — on any failure the Chinese fields are set to empty strings.
    Returns the same list (mutated).
    """
    if not reviews:
        return reviews

    batch_size = config.LLM_TRANSLATE_BATCH_SIZE
    for start in range(0, len(reviews), batch_size):
        batch = reviews[start : start + batch_size]
        # Initialise defaults in case of error
        for r in batch:
            r.setdefault("headline_cn", "")
            r.setdefault("body_cn", "")

        try:
            items_payload = [
                {"index": i, "headline": r.get("headline") or "", "body": r.get("body") or ""}
                for i, r in enumerate(batch)
            ]
            prompt = (
                "请将以下英文产品评论的 headline 和 body 翻译为中文，"
                "保持原意，语言自然流畅。\n"
                "以 JSON 数组形式返回，每个元素包含 index、headline_cn、body_cn 三个字段。\n"
                "不要返回其他内容。\n\n"
                f"输入：\n{json.dumps(items_payload, ensure_ascii=False)}"
            )
            raw = _call_llm([{"role": "user", "content": prompt}])
            cleaned = _strip_markdown_json(raw)
            results = json.loads(cleaned)

            for item in results:
                idx = item.get("index")
                if idx is None or idx >= len(batch):
                    continue
                batch[idx]["headline_cn"] = item.get("headline_cn", "")
                batch[idx]["body_cn"] = item.get("body_cn", "")

            logger.info(
                "translate_reviews: batch [%d:%d] translated %d items",
                start,
                start + len(batch),
                len(results),
            )
        except Exception as exc:
            logger.warning(
                "translate_reviews: batch [%d:%d] failed — %s",
                start,
                start + len(batch),
                exc,
            )
            # Defaults already set above; just continue

    return reviews


# ── Excel Generation ─────────────────────────────────────────────────────────


def _cell_value(v):
    """Convert a value to something Excel can store."""
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    return v


def generate_excel(
    products: list[dict],
    reviews: list[dict],
    report_date: datetime | None = None,
) -> str:
    """Generate an Excel report and return the file path.

    Creates ``config.REPORT_DIR/scrape-report-YYYY-MM-DD.xlsx``.
    Empty data still produces a valid file with headers.
    """
    if report_date is None:
        report_date = datetime.now(timezone.utc)

    os.makedirs(config.REPORT_DIR, exist_ok=True)
    filename = f"scrape-report-{report_date.strftime('%Y-%m-%d')}.xlsx"
    filepath = os.path.join(config.REPORT_DIR, filename)

    wb = Workbook()

    # ── Header styling helpers ────────────────────────
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(fill_type="solid", fgColor="4472C4")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

    def _write_sheet(ws, headers: list[str], rows: list[list]):
        # Write header
        ws.append(headers)
        for col_idx, _ in enumerate(headers, start=1):
            cell = ws.cell(row=1, column=col_idx)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_align

        # Write data rows
        for row_data in rows:
            ws.append([_cell_value(v) for v in row_data])

        # Auto-adjust column widths
        for col in ws.columns:
            max_len = 0
            col_letter = col[0].column_letter
            for cell in col:
                try:
                    cell_len = len(str(cell.value)) if cell.value is not None else 0
                    max_len = max(max_len, cell_len)
                except Exception:
                    pass
            ws.column_dimensions[col_letter].width = min(max(max_len + 2, 10), 60)

    # ── 产品 sheet ────────────────────────────────────
    ws_products = wb.active
    ws_products.title = "产品"
    product_headers = [
        "产品地址", "产品名称", "SKU", "售价$", "库存状态",
        "综合评分", "评论数量", "抓取时间", "站点", "归属",
    ]
    product_keys = [
        "url", "name", "sku", "price", "stock_status",
        "rating", "review_count", "scraped_at", "site", "ownership",
    ]
    product_rows = [[p.get(k) for k in product_keys] for p in products]
    _write_sheet(ws_products, product_headers, product_rows)

    # ── 评论 sheet ────────────────────────────────────
    ws_reviews = wb.create_sheet("评论")
    review_headers = [
        "产品名称", "评论人", "标题（原文）", "内容（原文）",
        "标题（中文）", "内容（中文）", "打分", "评论时间", "照片",
    ]
    review_keys = [
        "product_name", "author", "headline", "body",
        "headline_cn", "body_cn", "rating", "date_published", "images",
    ]
    review_rows = [[r.get(k) for k in review_keys] for r in reviews]
    _write_sheet(ws_reviews, review_headers, review_rows)

    wb.save(filepath)
    logger.info("generate_excel: saved to %s", filepath)
    return filepath


# ── Email ────────────────────────────────────────────────────────────────────


def load_email_recipients(filepath: str) -> list[str]:
    """Read email addresses from a file, one per line.

    Lines starting with ``#`` (after stripping) are treated as comments.
    Returns a list of non-empty email addresses.
    """
    recipients: list[str] = []
    try:
        with open(filepath, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    recipients.append(stripped)
    except FileNotFoundError:
        logger.warning("load_email_recipients: file not found — %s", filepath)
    except Exception as exc:
        logger.warning("load_email_recipients: error reading %s — %s", filepath, exc)
    return recipients


def send_email(
    recipients: list[str],
    subject: str,
    body_text: str,
    attachment_path: str | None = None,
) -> dict:
    """Send an email via SMTP.

    Returns a dict with keys:
    - success (bool)
    - error (str | None)
    - recipients (int) — number of addresses the message was sent to
    """
    if not recipients:
        return {"success": False, "error": "No recipients provided", "recipients": 0}

    if not config.SMTP_HOST:
        return {"success": False, "error": "SMTP_HOST not configured", "recipients": 0}

    try:
        msg = MIMEMultipart()
        msg["From"] = config.SMTP_FROM or config.SMTP_USER
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = subject
        msg.attach(MIMEText(body_text, "plain", "utf-8"))

        if attachment_path and os.path.isfile(attachment_path):
            with open(attachment_path, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f"attachment; filename={os.path.basename(attachment_path)}",
            )
            msg.attach(part)

        if config.SMTP_USE_SSL:
            smtp = smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT)
        else:
            smtp = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT)
            smtp.starttls()

        if config.SMTP_USER and config.SMTP_PASSWORD:
            smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)

        smtp.sendmail(msg["From"], recipients, msg.as_string())
        smtp.quit()

        logger.info("send_email: sent to %d recipients — %s", len(recipients), subject)
        return {"success": True, "error": None, "recipients": len(recipients)}

    except Exception as exc:
        logger.warning("send_email: failed — %s", exc)
        return {"success": False, "error": str(exc), "recipients": 0}


# ── Pipeline ─────────────────────────────────────────────────────────────────

# Alias before defining generate_report so the parameter name doesn't shadow it
_send_email_impl = send_email


def generate_report(
    since: datetime,
    send_email: bool = True,
    recipients_file: str | None = None,
) -> dict:
    """Full report pipeline: query → translate → Excel → email.

    Parameters
    ----------
    since:
        Only include data scraped on or after this UTC timestamp.
    send_email:
        Whether to send the Excel report by email.
    recipients_file:
        Path to the recipients file.  Defaults to
        ``~/.openclaw/workspace/config/email-recipients.txt``.

    Returns a summary dict with keys:
    - products_count
    - reviews_count
    - translated_count
    - excel_path
    - email (result dict from send_email, or None if skipped)
    """
    # 1. Query
    products, reviews = query_report_data(since)

    # 2. Translate (only when LLM is configured)
    translated_count = 0
    llm_configured = bool(config.LLM_API_KEY)
    if llm_configured and reviews:
        translate_reviews(reviews)
        translated_count = sum(
            1 for r in reviews if r.get("headline_cn") or r.get("body_cn")
        )
    else:
        # Ensure Chinese fields exist even when not translated
        for r in reviews:
            r.setdefault("headline_cn", "")
            r.setdefault("body_cn", "")

    # 3. Excel
    excel_path = generate_excel(products, reviews, report_date=since)

    # 4. Email
    email_result = None
    if send_email:
        if recipients_file is None:
            recipients_file = str(
                Path.home() / ".openclaw" / "workspace" / "config" / "email-recipients.txt"
            )
        recipients = load_email_recipients(recipients_file)
        since_str = since.strftime("%Y-%m-%d")
        subject = f"Qbu 每日抓取报告 {since_str}"
        body = (
            f"您好，\n\n"
            f"以下是 {since_str} 的 Qbu 产品抓取报告汇总：\n"
            f"  - 产品数：{len(products)}\n"
            f"  - 评论数：{len(reviews)}\n"
            f"  - 已翻译评论：{translated_count}\n\n"
            f"详细数据请查阅附件 Excel 文件。\n"
        )
        email_result = _send_email_impl(
            recipients=recipients,
            subject=subject,
            body_text=body,
            attachment_path=excel_path,
        )

    return {
        "products_count": len(products),
        "reviews_count": len(reviews),
        "translated_count": translated_count,
        "excel_path": excel_path,
        "email": email_result,
    }
