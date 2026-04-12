"""Report generation module — query, Excel, email."""

import json
import logging
import os
import smtplib
import time
from dataclasses import asdict
from datetime import datetime, timezone
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from io import BytesIO

import requests
from jinja2 import Environment, FileSystemLoader
from openpyxl import Workbook
from openpyxl.drawing.image import Image as XlImage
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from PIL import Image as PILImage

# ── Conditional formatting fills for analytical sheets ────────────────────────
_RED_FILL = PatternFill(start_color="F2D9D0", end_color="F2D9D0", fill_type="solid")
_YELLOW_FILL = PatternFill(start_color="F5ECD4", end_color="F5ECD4", fill_type="solid")
_GREEN_FILL = PatternFill(start_color="DCE9E3", end_color="DCE9E3", fill_type="solid")

from qbu_crawler import config, models
from qbu_crawler.server.report_common import (  # noqa: F401 — re-export
    _LABEL_DISPLAY,
    _PRIORITY_DISPLAY,
    _SEVERITY_DISPLAY,
    _derive_review_label_codes,
    _fallback_executive_bullets,
    _fallback_hero_headline,
    _join_label_codes,
    _join_label_counts,
    _label_display,
    _summary_text,
    normalize_deep_report_analytics,
)
from qbu_crawler.server.scope import Scope, normalize_scope

logger = logging.getLogger(__name__)

_SMTP_RETRY_ATTEMPTS = 3

# ── Data Query ──────────────────────────────────────────────────────────────


def query_report_data(since: datetime) -> tuple[list[dict], list[dict]]:
    """Query products and reviews added since the given timestamp (Asia/Shanghai).

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
            SELECT r.id AS id, p.name AS product_name, p.sku AS product_sku,
                   r.author, r.headline, r.body, r.rating,
                   r.date_published, r.date_published_parsed, r.images,
                   p.ownership,
                   r.headline_cn, r.body_cn, r.translate_status
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



# ── Excel Generation ─────────────────────────────────────────────────────────


def _cell_value(v):
    """Convert a value to something Excel can store."""
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    return v


_IMG_THUMB_HEIGHT = 80   # 缩略图高度（像素）
_IMG_THUMB_SPACING = 5   # 多张图片间距（像素）
_IMG_COL_WIDTH = 17      # 照片列宽度（字符数，约 120px）
_IMG_DOWNLOAD_TIMEOUT = 10  # 单张图片下载超时（秒）


def _download_and_resize(url: str) -> XlImage | None:
    """Download an image and return an openpyxl Image with thumbnail display size.

    Keeps original resolution for clarity when zoomed in;
    only sets the display dimensions to thumbnail size in Excel.
    """
    try:
        for _attempt in range(2):
            try:
                resp = requests.get(url, timeout=_IMG_DOWNLOAD_TIMEOUT)
                resp.raise_for_status()
                break
            except requests.RequestException:
                if _attempt == 1:
                    raise
        buf = BytesIO(resp.content)
        # Read original dimensions for aspect ratio calculation
        img = PILImage.open(buf)
        ratio = _IMG_THUMB_HEIGHT / img.height
        display_width = int(img.width * ratio)
        # Create openpyxl Image from original bytes (no pixel resize)
        buf.seek(0)
        xl_img = XlImage(buf)
        # Set display size only — original resolution preserved
        xl_img.width = display_width
        xl_img.height = _IMG_THUMB_HEIGHT
        return xl_img
    except Exception as exc:
        logger.warning("_download_and_resize: failed for %s — %s", url[:80], exc)
        return None


def _download_images_parallel(urls: list[str], global_timeout: float = 60) -> dict:
    """Download multiple images in parallel. Returns {url: Image_or_None}."""
    if not urls:
        return {}

    from concurrent.futures import ThreadPoolExecutor, as_completed

    results = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        future_to_url = {pool.submit(_download_and_resize, url): url for url in urls}
        try:
            for future in as_completed(future_to_url, timeout=global_timeout):
                url = future_to_url[future]
                try:
                    results[url] = future.result()
                except Exception:
                    results[url] = None
        except TimeoutError:
            # Global timeout reached — fill remaining with None
            for future, url in future_to_url.items():
                if url not in results:
                    results[url] = None
                    future.cancel()

    return results


def generate_excel(
    products: list[dict],
    reviews: list[dict],
    report_date: datetime | None = None,
) -> str:
    """Generate an Excel report and return the file path.

    Creates ``config.REPORT_DIR/scrape-report-YYYY-MM-DD.xlsx``.
    Empty data still produces a valid file with headers.
    Review images are downloaded and embedded as thumbnails in cells.
    """
    if report_date is None:
        report_date = config.now_shanghai()

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
        "产品名称", "SKU", "评论人", "标题（原文）", "内容（原文）",
        "标题（中文）", "内容（中文）", "打分", "评论时间", "照片",
    ]
    # Write header
    ws_reviews.append(review_headers)
    for col_idx, _ in enumerate(review_headers, start=1):
        cell = ws_reviews.cell(row=1, column=col_idx)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align

    images_col = len(review_headers)  # "照片" is the last column
    images_col_letter = get_column_letter(images_col)

    # Pre-fetch all review images in parallel
    _all_image_urls = set()
    for _r in reviews:
        for _url in (_r.get("images") or []):
            if isinstance(_url, str) and _url.startswith("http"):
                _all_image_urls.add(_url)
    _prefetched = _download_images_parallel(list(_all_image_urls)) if _all_image_urls else {}

    # Write review rows with embedded images
    for row_idx, r in enumerate(reviews, start=2):
        ws_reviews.cell(row=row_idx, column=1, value=_cell_value(r.get("product_name")))
        ws_reviews.cell(row=row_idx, column=2, value=_cell_value(r.get("product_sku")))
        ws_reviews.cell(row=row_idx, column=3, value=_cell_value(r.get("author")))
        ws_reviews.cell(row=row_idx, column=4, value=_cell_value(r.get("headline")))
        ws_reviews.cell(row=row_idx, column=5, value=_cell_value(r.get("body")))
        ws_reviews.cell(row=row_idx, column=6, value=_cell_value(r.get("headline_cn")))
        ws_reviews.cell(row=row_idx, column=7, value=_cell_value(r.get("body_cn")))
        ws_reviews.cell(row=row_idx, column=8, value=_cell_value(r.get("rating")))
        ws_reviews.cell(row=row_idx, column=9, value=_cell_value(r.get("date_published")))

        # Embed images as thumbnails
        image_urls = r.get("images") or []
        if isinstance(image_urls, str):
            try:
                image_urls = json.loads(image_urls)
            except Exception:
                image_urls = []

        embedded_count = 0
        for img_idx, url in enumerate(image_urls):
            xl_img = _prefetched.get(url) if isinstance(url, str) else None
            if xl_img is None and isinstance(url, str) and url.startswith("http"):
                xl_img = _download_and_resize(url)
            if xl_img:
                y_offset = img_idx * (_IMG_THUMB_HEIGHT + _IMG_THUMB_SPACING)
                from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, OneCellAnchor
                from openpyxl.drawing.xdr import XDRPositiveSize2D
                from openpyxl.utils.units import pixels_to_EMU
                marker = AnchorMarker(
                    col=images_col - 1,  # 0-indexed
                    row=row_idx - 1,     # 0-indexed
                    colOff=0,
                    rowOff=pixels_to_EMU(y_offset),
                )
                size = XDRPositiveSize2D(
                    pixels_to_EMU(xl_img.width),
                    pixels_to_EMU(xl_img.height),
                )
                xl_img.anchor = OneCellAnchor(_from=marker, ext=size)
                ws_reviews.add_image(xl_img)
                embedded_count += 1

        if embedded_count > 0:
            # Adjust row height to fit stacked images
            row_height_px = embedded_count * (_IMG_THUMB_HEIGHT + _IMG_THUMB_SPACING)
            ws_reviews.row_dimensions[row_idx].height = row_height_px * 0.75  # px to points
        elif image_urls:
            # Fallback: write URLs as text (only if non-empty)
            ws_reviews.cell(row=row_idx, column=images_col, value=_cell_value(image_urls))

    # Auto-adjust non-image column widths
    for col in ws_reviews.columns:
        col_letter = col[0].column_letter
        if col_letter == images_col_letter:
            ws_reviews.column_dimensions[col_letter].width = _IMG_COL_WIDTH
            continue
        max_len = 0
        for cell in col:
            try:
                cell_len = len(str(cell.value)) if cell.value is not None else 0
                max_len = max(max_len, cell_len)
            except Exception:
                pass
        ws_reviews.column_dimensions[col_letter].width = min(max(max_len + 2, 10), 60)

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
    body_html: str | None = None,
    attachment_path: str | None = None,
    attachment_paths: list[str] | None = None,
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

    attachments = [path for path in (attachment_paths or []) if path]
    if attachment_path:
        attachments.insert(0, attachment_path)

    last_error = None
    for attempt in range(_SMTP_RETRY_ATTEMPTS):
        smtp = None
        try:
            msg = MIMEMultipart("mixed")
            msg["From"] = config.SMTP_FROM or config.SMTP_USER
            if config.EMAIL_BCC_MODE:
                msg["To"] = config.SMTP_FROM or config.SMTP_USER
                msg["Bcc"] = ", ".join(recipients)
            else:
                msg["To"] = ", ".join(recipients)
            msg["Subject"] = subject

            body_part = MIMEMultipart("alternative")
            body_part.attach(MIMEText(body_text, "plain", "utf-8"))
            if body_html:
                body_part.attach(MIMEText(body_html, "html", "utf-8"))
            msg.attach(body_part)

            for path in attachments:
                if not os.path.isfile(path):
                    continue
                with open(path, "rb") as f:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    "attachment",
                    filename=("utf-8", "", os.path.basename(path)),
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
            logger.info("send_email: sent to %d recipients — %s", len(recipients), subject)
            return {"success": True, "error": None, "recipients": len(recipients)}
        except Exception as exc:
            last_error = exc
            logger.warning(
                "send_email: attempt %d/%d failed — %s",
                attempt + 1,
                _SMTP_RETRY_ATTEMPTS,
                exc,
            )
            if attempt + 1 < _SMTP_RETRY_ATTEMPTS:
                time.sleep(2**attempt)
        finally:
            if smtp is not None:
                try:
                    smtp.quit()
                except Exception:
                    close = getattr(smtp, "close", None)
                    if callable(close):
                        try:
                            close()
                        except Exception:
                            pass

    return {"success": False, "error": str(last_error), "recipients": 0}


def _report_template_dir():
    return Path(__file__).with_name("report_templates")


def _report_template_env():
    return Environment(
        loader=FileSystemLoader(str(_report_template_dir())),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_daily_email_html(snapshot, analytics):
    """Render the HTML email template."""
    normalized = normalize_deep_report_analytics(analytics)
    _ensure_humanized_bullets(normalized)
    env = _report_template_env()
    template = env.get_template("daily_report_email.html.j2")
    return template.render(
        snapshot=snapshot,
        analytics=normalized,
        threshold=config.NEGATIVE_THRESHOLD,
    )


def _build_email_subject(normalized, logical_date):
    """Generate a dynamic email subject line with alert level prefix."""
    from qbu_crawler.server.report_common import _compute_alert_level
    alert_level, _ = _compute_alert_level(normalized)
    prefix = {"red": "[需关注] ", "yellow": "[注意] ", "green": ""}[alert_level]
    top = (normalized.get("self", {}).get("risk_products") or [None])[0]
    top_name = top["product_name"] if top else ""
    count = normalized.get("kpis", {}).get("product_count", 0)
    return f"{prefix}产品评论日报 {logical_date} — {top_name} 等 {count} 个产品"


def _ensure_humanized_bullets(normalized):
    """Ensure executive_bullets_human exists in normalized analytics."""
    from qbu_crawler.server.report_common import _humanize_bullets
    report_copy = normalized.setdefault("report_copy", {})
    if not report_copy.get("executive_bullets_human"):
        report_copy["executive_bullets_human"] = _humanize_bullets(normalized)


def build_daily_deep_report_email(snapshot, analytics):
    normalized = normalize_deep_report_analytics(analytics)
    _ensure_humanized_bullets(normalized)
    subject = _build_email_subject(normalized, snapshot["logical_date"])
    template_env = _report_template_env()
    body = template_env.get_template("daily_report_email_body.txt.j2").render(
        snapshot=snapshot,
        analytics=normalized,
        threshold=config.NEGATIVE_THRESHOLD,
    ).strip()
    return subject, f"{body}\n"


def build_legacy_report_email(
    products: list[dict],
    reviews: list[dict],
    since_str: str,
    translated_count: int,
    untranslated_count: int,
) -> tuple[str, str]:
    """Build the original report email subject/body template."""
    site_names = {"basspro": "Bass Pro Shops", "meatyourmaker": "Meat Your Maker"}
    sites_in_report = set()
    own_count = 0
    competitor_count = 0
    for product in products:
        sites_in_report.add(product.get("site", ""))
        if product.get("ownership") == "own":
            own_count += 1
        else:
            competitor_count += 1

    negative_reviews = [item for item in reviews if (item.get("rating") or 5) <= 2]
    site_display = "、".join(
        site_names.get(site, site) for site in sorted(sites_in_report) if site
    ) or "多站点"

    subject = f"【网评监控】{site_display} 产品评论报告 {since_str}"
    body = (
        f"各位好，\n\n"
        f"附件是 {since_str} 从 {site_display} 抓取的最新产品网评报告，请查阅。\n\n"
        f"【数据概览】\n"
        f"  - 涉及产品：{len(products)} 个"
    )
    if own_count or competitor_count:
        body += f"（自有 {own_count}，竞品 {competitor_count}）"
    body += (
        f"\n"
        f"  - 新增评论：{len(reviews)} 条（已翻译 {translated_count} 条）\n"
    )
    if untranslated_count > 0:
        body += f"  - 注：{untranslated_count} 条评论翻译进行中，中文列暂时为空\n"

    if negative_reviews:
        body += (
            f"\n"
            f"【差评预警】共 {len(negative_reviews)} 条差评（≤2星），请重点关注并更新改进措施。\n"
        )

    body += (
        f"\n"
        f"详细数据见附件 Excel（产品 + 评论两个 Sheet）。\n"
        f"如有疑问请随时沟通，谢谢！\n"
    )
    return subject, body


# ── Pipeline ─────────────────────────────────────────────────────────────────

# Alias before defining generate_report so the parameter name doesn't shadow it
_send_email_impl = send_email


def generate_report(
    since: datetime,
    send_email: bool = True,
) -> dict:
    """Report pipeline: query (with pre-translated data) → Excel → email.

    Translation is handled by the background TranslationWorker.
    Reviews that haven't been translated yet will have empty Chinese fields.
    """
    # 1. Query (includes headline_cn/body_cn from DB)
    products, reviews = query_report_data(since)

    # 2. Count translation status
    translated_count = sum(
        1 for r in reviews if r.get("translate_status") == "done"
    )
    untranslated_count = len(reviews) - translated_count

    # Ensure Chinese fields exist for Excel generation
    for r in reviews:
        r.setdefault("headline_cn", "")
        r.setdefault("body_cn", "")

    # 3. Excel
    excel_path = generate_excel(products, reviews, report_date=since)

    # 4. Email
    email_result = None
    if send_email:
        recipients = config.EMAIL_RECIPIENTS
        since_str = since.strftime("%Y-%m-%d")
        subject, body = build_legacy_report_email(
            products=products,
            reviews=reviews,
            since_str=since_str,
            translated_count=translated_count,
            untranslated_count=untranslated_count,
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
        "untranslated_count": untranslated_count,
        "excel_path": excel_path,
        "email": email_result,
    }


_legacy_query_report_data = query_report_data
_legacy_generate_excel = generate_excel


# ── 4-Sheet Data-Oriented Excel ──────────────────────────────────────────────


def _generate_analytical_excel(
    products: list[dict],
    reviews: list[dict],
    analytics: dict | None = None,
    report_date: datetime | None = None,
) -> str:
    """Generate a 4-sheet data-oriented Excel workbook.

    Sheets: 评论明细, 产品概览, 问题标签, 趋势数据.

    If *analytics* is ``None``, falls back to the legacy 2-sheet format for
    backward compatibility.

    Returns the file path of the generated ``.xlsx``.
    """
    if analytics is None:
        return _legacy_generate_excel(products, reviews, report_date=report_date)

    if report_date is None:
        report_date = config.now_shanghai()

    os.makedirs(config.REPORT_DIR, exist_ok=True)
    filename = f"scrape-report-{report_date.strftime('%Y-%m-%d')}.xlsx"
    filepath = os.path.join(config.REPORT_DIR, filename)

    wb = Workbook()

    # ── Shared styling helpers ────────────────────────────────────────────
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(fill_type="solid", fgColor="4472C4")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

    def _write_headers(ws, headers):
        ws.append(headers)
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_align

    def _auto_widths(ws, min_w=10, max_w=60):
        for col in ws.columns:
            letter = col[0].column_letter
            max_len = max((len(str(c.value or "")) for c in col), default=0)
            ws.column_dimensions[letter].width = min(max(max_len + 2, min_w), max_w)

    # ── Sheet 1: 评论明细 ──────────────────────────────────────────────────
    ws1 = wb.active
    ws1.title = "评论明细"
    review_headers = [
        "ID", "产品名称", "SKU", "归属", "评分", "情感", "标签", "影响类别", "失效模式",
        "标题(原文)", "标题(中文)", "内容(原文)", "内容(中文)",
        "特征短语", "洞察", "评论时间", "照片",
    ]
    _write_headers(ws1, review_headers)
    images_col = len(review_headers)  # "照片" column (1-indexed)

    # Collect all image URLs for parallel pre-fetch
    _all_img_urls = set()
    for r in reviews:
        _imgs = r.get("images") or []
        if isinstance(_imgs, str):
            try:
                _imgs = json.loads(_imgs)
            except Exception:
                _imgs = []
        if isinstance(_imgs, list):
            for u in _imgs:
                if isinstance(u, str) and u.startswith("http"):
                    _all_img_urls.add(u)
    _prefetched = _download_images_parallel(list(_all_img_urls)) if _all_img_urls else {}

    for r in reviews:
        # Parse images
        images_raw = r.get("images")
        if isinstance(images_raw, str):
            try:
                images_list = json.loads(images_raw)
            except Exception:
                images_list = []
            if not isinstance(images_list, list):
                images_list = []
        elif isinstance(images_raw, list):
            images_list = images_raw
        else:
            images_list = []

        # Parse labels
        labels_raw = r.get("analysis_labels") or "[]"
        if isinstance(labels_raw, str):
            try:
                labels_list = json.loads(labels_raw)
            except Exception:
                labels_list = []
            if not isinstance(labels_list, list):
                labels_list = []
        else:
            labels_list = labels_raw if isinstance(labels_raw, list) else []
        labels_text = ", ".join(lbl.get("code", "") for lbl in labels_list if isinstance(lbl, dict))

        # Parse features
        features_raw = r.get("analysis_features") or r.get("features") or "[]"
        if isinstance(features_raw, str):
            try:
                features_list = json.loads(features_raw)
            except Exception:
                features_list = []
            if not isinstance(features_list, list):
                features_list = []
        else:
            features_list = features_raw if isinstance(features_raw, list) else []
        features_text = ", ".join(str(f) for f in features_list)

        ws1.append([
            r.get("id"),
            r.get("product_name"),
            r.get("product_sku"),
            r.get("ownership"),
            r.get("rating"),
            r.get("sentiment"),
            labels_text,
            r.get("impact_category"),
            r.get("failure_mode"),
            r.get("headline"),
            r.get("headline_cn"),
            r.get("body"),
            r.get("body_cn"),
            features_text,
            r.get("analysis_insight_cn") or r.get("insight_cn") or "",
            r.get("date_published_parsed") or r.get("date_published") or "",
            "",  # placeholder for images column
        ])

        # Embed images as thumbnails (same approach as legacy Excel)
        row_idx = ws1.max_row
        embedded_count = 0
        for img_idx, url in enumerate(images_list):
            xl_img = _prefetched.get(url) if isinstance(url, str) else None
            if xl_img is None and isinstance(url, str) and url.startswith("http"):
                xl_img = _download_and_resize(url)
            if xl_img:
                y_offset = img_idx * (_IMG_THUMB_HEIGHT + _IMG_THUMB_SPACING)
                from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, OneCellAnchor
                from openpyxl.drawing.xdr import XDRPositiveSize2D
                from openpyxl.utils.units import pixels_to_EMU
                marker = AnchorMarker(
                    col=images_col - 1,
                    row=row_idx - 1,
                    colOff=0,
                    rowOff=pixels_to_EMU(y_offset),
                )
                size = XDRPositiveSize2D(
                    pixels_to_EMU(xl_img.width),
                    pixels_to_EMU(xl_img.height),
                )
                xl_img.anchor = OneCellAnchor(_from=marker, ext=size)
                ws1.add_image(xl_img)
                embedded_count += 1

        if embedded_count > 0:
            row_height_px = embedded_count * (_IMG_THUMB_HEIGHT + _IMG_THUMB_SPACING)
            ws1.row_dimensions[row_idx].height = row_height_px * 0.75
        elif images_list:
            # Fallback: write URLs as text
            images_text = "\n".join(str(u) for u in images_list)
            ws1.cell(row=row_idx, column=images_col, value=images_text)

    _auto_widths(ws1)
    # Set images column width
    from openpyxl.utils import get_column_letter
    ws1.column_dimensions[get_column_letter(images_col)].width = _IMG_COL_WIDTH

    # ── Sheet 2: 产品概览 ──────────────────────────────────────────────────
    ws2 = wb.create_sheet("产品概览")
    product_headers = [
        "产品名称", "SKU", "站点", "归属", "售价", "库存状态",
        "站点评分", "站点评论数", "采集评论数", "差评数", "差评率", "风险分",
    ]
    _write_headers(ws2, product_headers)

    risk_by_sku = {
        p["product_sku"]: p
        for p in (analytics.get("self") or {}).get("risk_products") or []
        if p.get("product_sku")
    }
    for p in products:
        risk = risk_by_sku.get(p.get("sku", ""), {})
        ws2.append([
            p.get("name"),
            p.get("sku"),
            p.get("site"),
            p.get("ownership"),
            p.get("price"),
            p.get("stock_status"),
            p.get("rating"),
            p.get("review_count"),
            risk.get("ingested_reviews", 0),
            risk.get("negative_review_rows", 0),
            risk.get("negative_rate"),
            risk.get("risk_score"),
        ])

    _auto_widths(ws2)

    # ── Sheet 3: 问题标签 ──────────────────────────────────────────────────
    ws3 = wb.create_sheet("问题标签")
    label_headers = ["review_id", "product_sku", "label_code", "label_polarity", "severity", "confidence"]
    _write_headers(ws3, label_headers)

    for r in reviews:
        labels_raw = r.get("analysis_labels") or "[]"
        if isinstance(labels_raw, str):
            try:
                labels = json.loads(labels_raw)
            except Exception:
                labels = []
            if not isinstance(labels, list):
                labels = []
        else:
            labels = labels_raw if isinstance(labels_raw, list) else []
        for label in labels:
            if isinstance(label, dict):
                ws3.append([
                    r.get("id"),
                    r.get("product_sku"),
                    label.get("code"),
                    label.get("polarity"),
                    label.get("severity"),
                    label.get("confidence"),
                ])

    _auto_widths(ws3)

    # ── Sheet 4: 趋势数据 ──────────────────────────────────────────────────
    ws4 = wb.create_sheet("趋势数据")
    trend_headers = ["日期", "SKU", "产品名称", "价格", "评分", "评论数", "库存状态"]
    _write_headers(ws4, trend_headers)

    for ts in analytics.get("_trend_series") or []:
        for point in ts.get("series") or []:
            ws4.append([
                point.get("date"),
                ts.get("product_sku"),
                ts.get("product_name"),
                point.get("price"),
                point.get("rating"),
                point.get("review_count"),
                point.get("stock_status"),
            ])

    _auto_widths(ws4)

    wb.save(filepath)
    logger.info("V3 4-sheet Excel generated: %s", filepath)
    return filepath


def _report_ts(value: datetime | str) -> str:
    """Normalize report cutoffs to the naive timestamp format stored in SQLite."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is not None:
        value = value.astimezone(config.SHANGHAI_TZ).replace(tzinfo=None)
    return value.strftime("%Y-%m-%d %H:%M:%S")


def query_report_data(
    since: datetime | str,
    until: datetime | str | None = None,
) -> tuple[list[dict], list[dict]]:
    """Query products and reviews inside a bounded report window."""
    if until is None:
        return _legacy_query_report_data(since if isinstance(since, datetime) else datetime.fromisoformat(since))

    since_str = _report_ts(since)
    until_str = _report_ts(until)

    conn = models.get_conn()
    try:
        product_rows = conn.execute(
            """
            SELECT url, name, sku, price, stock_status, rating, review_count,
                   scraped_at, site, ownership
            FROM products
            WHERE scraped_at >= ?
              AND scraped_at < ?
            ORDER BY scraped_at DESC
            """,
            (since_str, until_str),
        ).fetchall()
        products = [dict(r) for r in product_rows]

        review_rows = conn.execute(
            """
            SELECT r.id AS id, p.name AS product_name, p.sku AS product_sku,
                   r.author, r.headline, r.body, r.rating,
                   r.date_published, r.date_published_parsed, r.images,
                   p.ownership,
                   r.headline_cn, r.body_cn, r.translate_status
            FROM reviews r
            JOIN products p ON r.product_id = p.id
            WHERE r.scraped_at >= ?
              AND r.scraped_at < ?
            ORDER BY r.scraped_at DESC
            """,
            (since_str, until_str),
        ).fetchall()
        reviews = []
        for row in review_rows:
            data = dict(row)
            if data.get("images") and isinstance(data["images"], str):
                try:
                    data["images"] = json.loads(data["images"])
                except Exception:
                    pass
            reviews.append(data)
    finally:
        conn.close()

    logger.info(
        "query_report_data: since=%s until=%s -> %d products, %d reviews",
        since_str,
        until_str,
        len(products),
        len(reviews),
    )
    return products, reviews


def query_scope_report_data(scope: Scope) -> tuple[list[dict], list[dict]]:
    """Query products and reviews for a normalized scope."""
    conn = models.get_conn()
    try:
        review_clauses, review_params = models._scope_review_clauses(  # noqa: SLF001
            scope,
            review_alias="r",
            product_alias="p",
        )
        review_where = f"WHERE {' AND '.join(review_clauses)}" if review_clauses else ""

        if models._scope_has_review_constraints(scope):  # noqa: SLF001
            product_rows = conn.execute(
                f"""
                SELECT DISTINCT
                       p.url, p.name, p.sku, p.price, p.stock_status, p.rating, p.review_count,
                       p.scraped_at, p.site, p.ownership
                FROM reviews r
                JOIN products p ON r.product_id = p.id
                {review_where}
                ORDER BY p.scraped_at DESC, p.id DESC
                """,
                review_params,
            ).fetchall()
        else:
            product_clauses, product_params = models._scope_product_clauses(scope, alias="p")  # noqa: SLF001
            product_where = f"WHERE {' AND '.join(product_clauses)}" if product_clauses else ""
            product_rows = conn.execute(
                f"""
                SELECT url, name, sku, price, stock_status, rating, review_count,
                       scraped_at, site, ownership
                FROM products p
                {product_where}
                ORDER BY p.scraped_at DESC, p.id DESC
                """,
                product_params,
            ).fetchall()
        products = [dict(r) for r in product_rows]

        review_rows = conn.execute(
            f"""
            SELECT p.name AS product_name, p.sku AS product_sku,
                   r.author, r.headline, r.body, r.rating,
                   r.date_published, r.date_published_parsed, r.images,
                   p.ownership,
                   r.headline_cn, r.body_cn, r.translate_status
            FROM reviews r
            JOIN products p ON r.product_id = p.id
            {review_where}
            ORDER BY r.scraped_at DESC, r.id DESC
            """,
            review_params,
        ).fetchall()
        reviews = []
        for row in review_rows:
            data = dict(row)
            if data.get("images") and isinstance(data["images"], str):
                try:
                    data["images"] = json.loads(data["images"])
                except Exception:
                    pass
            reviews.append(data)
    finally:
        conn.close()

    logger.info(
        "query_scope_report_data: %d products, %d reviews",
        len(products),
        len(reviews),
    )
    return products, reviews


def _filtered_report_date(scope: Scope) -> datetime:
    if scope.window.since:
        return datetime.fromisoformat(scope.window.since)
    if scope.window.until:
        return datetime.fromisoformat(scope.window.until)
    return config.now_shanghai()


def _validate_scope_window(scope: Scope) -> str | None:
    parsed = {}
    for label, value in (("since", scope.window.since), ("until", scope.window.until)):
        if not value:
            continue
        try:
            parsed[label] = datetime.fromisoformat(value)
        except ValueError:
            return f"Invalid scope window: {label} must be ISO date or datetime"
    if parsed.get("since") and parsed.get("until") and parsed["since"] > parsed["until"]:
        return "Invalid scope window: since must be on or before until"
    return None


def send_filtered_report(scope: dict, delivery: dict | None = None) -> dict:
    """Generate a filtered report while preserving the legacy email contract."""
    delivery = delivery or {}
    scope_obj = normalize_scope(
        products=scope.get("products"),
        reviews=scope.get("reviews"),
        window=scope.get("window"),
    )
    output_format = str(delivery.get("format", "excel") or "excel").strip().lower()
    subject_override = str(delivery.get("subject", "") or "").strip()
    if "recipients" in delivery:
        recipients = delivery.get("recipients")
    else:
        recipients = config.EMAIL_RECIPIENTS

    window_error = _validate_scope_window(scope_obj)
    if window_error:
        return {
            "scope": asdict(scope_obj),
            "data": {
                "products_count": 0,
                "reviews_count": 0,
                "translated_count": 0,
                "untranslated_count": 0,
            },
            "artifact": {
                "success": False,
                "format": "excel",
                "excel_path": None,
                "error": window_error,
            },
            "email": None,
        }

    products, reviews = query_scope_report_data(scope_obj)

    translated_count = sum(1 for r in reviews if r.get("translate_status") == "done")
    untranslated_count = len(reviews) - translated_count
    for review in reviews:
        review.setdefault("headline_cn", "")
        review.setdefault("body_cn", "")

    data_result = {
        "products_count": len(products),
        "reviews_count": len(reviews),
        "translated_count": translated_count,
        "untranslated_count": untranslated_count,
    }

    report_date = _filtered_report_date(scope_obj)
    output_path = delivery.get("output_path")
    artifact_result = {
        "success": False,
        "format": "excel",
        "excel_path": None,
    }
    try:
        excel_path = generate_excel(
            products,
            reviews,
            report_date=report_date,
            output_path=output_path,
        )
        artifact_result = {
            "success": True,
            "format": "excel",
            "excel_path": excel_path,
        }
    except Exception as exc:
        artifact_result["error"] = str(exc)
        return {
            "scope": asdict(scope_obj),
            "data": data_result,
            "artifact": artifact_result,
            "email": None,
        }

    email_result = None
    if output_format == "email":
        since_str = report_date.strftime("%Y-%m-%d")
        subject, body = build_legacy_report_email(
            products=products,
            reviews=reviews,
            since_str=since_str,
            translated_count=translated_count,
            untranslated_count=untranslated_count,
        )
        if subject_override:
            subject = subject_override
        email_result = _send_email_impl(
            recipients=recipients,
            subject=subject,
            body_text=body,
            attachment_path=artifact_result["excel_path"],
        )

    return {
        "scope": asdict(scope_obj),
        "data": data_result,
        "artifact": artifact_result,
        "email": email_result,
    }


def generate_excel(
    products: list[dict],
    reviews: list[dict],
    report_date: datetime | None = None,
    output_path: str | None = None,
    analytics: dict | None = None,
) -> str:
    """Generate an Excel report, optionally to an immutable output path.

    When *analytics* is provided, produces the 6-sheet analytical workbook;
    otherwise falls back to the legacy 2-sheet format.
    """
    if analytics:
        generated_path = _generate_analytical_excel(
            products, reviews, analytics=analytics, report_date=report_date,
        )
    else:
        generated_path = _legacy_generate_excel(products, reviews, report_date=report_date)

    if not output_path:
        return generated_path

    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    if os.path.abspath(generated_path) != os.path.abspath(output_path):
        Path(generated_path).replace(output_path)
    return output_path
