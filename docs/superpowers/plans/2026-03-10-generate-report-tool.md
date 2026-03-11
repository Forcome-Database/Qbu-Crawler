# generate_report MCP Tool 实施计划

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `generate_report` MCP Tool，服务端程序化完成数据查询 → LLM 翻译 → Excel 生成 → 邮件发送。

**Architecture:** 新建 `server/report.py` 模块封装报告生成逻辑，通过 MCP tool 暴露给 agent。翻译使用 OpenAI 兼容 API（配置在 .env），Excel 使用 openpyxl，邮件使用 smtplib。同步执行，在 MCP tool 中直接调用。

**Tech Stack:** Python 3.10+, openpyxl, openai SDK, smtplib (stdlib), FastMCP

---

## File Structure

| 文件 | 操作 | 职责 |
|------|------|------|
| `config.py` | Modify | 新增 LLM 翻译 + SMTP 邮件配置项 |
| `server/report.py` | Create | 报告生成核心模块（查询 + 翻译 + Excel + 邮件） |
| `server/mcp/tools.py` | Modify | 注册 `generate_report` MCP tool |
| `server/openclaw/plugin/index.js` | Modify | 注册新 tool + 修复缺失的 ownership 参数 |
| `pyproject.toml` | Modify | 新增 openpyxl, openai 依赖 |
| `.env.example` | Modify | 新增配置项示例 |
| `tests/test_report.py` | Create | 报告模块单元测试 |

---

## Chunk 1: 配置与依赖

### Task 1: 新增依赖

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: 添加 openpyxl 和 openai 依赖**

```toml
dependencies = [
    "drissionpage",
    "fastapi",
    "fastmcp>=2.0.0",
    "minio",
    "openai>=1.0.0",
    "openpyxl>=3.1.0",
    "python-dotenv",
    "requests",
    "uvicorn[standard]",
]
```

- [ ] **Step 2: 安装依赖**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv sync`
Expected: 成功安装，无报错

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add openpyxl and openai for report generation"
```

### Task 2: 新增配置项

**Files:**
- Modify: `config.py`
- Modify: `.env.example`

- [ ] **Step 1: 在 config.py 中添加 LLM 翻译和 SMTP 配置**

在 `# ── SQL Query Limits` 之前添加：

```python
# ── LLM Translation (OpenAI-compatible) ───────────
LLM_API_BASE = os.getenv("LLM_API_BASE", "")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
LLM_TRANSLATE_BATCH_SIZE = int(os.getenv("LLM_TRANSLATE_BATCH_SIZE", "20"))

# ── Email SMTP ────────────────────────────────────
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "")
SMTP_USE_SSL = os.getenv("SMTP_USE_SSL", "false").lower() == "true"

# ── Report ────────────────────────────────────────
REPORT_DIR = os.getenv("REPORT_DIR", os.path.join(BASE_DIR, "data", "reports"))
os.makedirs(REPORT_DIR, exist_ok=True)
```

- [ ] **Step 2: 更新 .env.example**

追加：

```
# ── LLM Translation (OpenAI-compatible) ──
LLM_API_BASE=https://api.openai.com/v1
LLM_API_KEY=sk-xxx
LLM_MODEL=gpt-4o-mini
LLM_TRANSLATE_BATCH_SIZE=20

# ── Email SMTP ──
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=user@example.com
SMTP_PASSWORD=your-password
SMTP_FROM=noreply@example.com
SMTP_USE_SSL=false

# ── Server ──
SERVER_HOST=0.0.0.0
SERVER_PORT=8000
API_KEY=your-api-key
MAX_WORKERS=3

# ── Report ──
REPORT_DIR=
```

- [ ] **Step 3: Commit**

```bash
git add config.py .env.example
git commit -m "config: add LLM translation and SMTP email settings"
```

---

## Chunk 2: 报告生成核心模块

### Task 3: 创建 server/report.py — 数据查询

**Files:**
- Create: `server/report.py`
- Create: `tests/test_report.py`

- [ ] **Step 1: 写测试 — 数据查询函数**

```python
# tests/test_report.py
import sqlite3
import os
import tempfile
import pytest

# Patch DB_PATH before importing
@pytest.fixture(autouse=True)
def patch_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr("config.DB_PATH", db_path)
    import models
    models.init_db()
    # Insert test data
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO products (url, site, name, sku, price, stock_status, review_count, rating, ownership) "
        "VALUES ('http://test.com/p1', 'basspro', 'Test Product', 'TP-001', 29.99, 'in_stock', 5, 4.5, 'own')"
    )
    pid = conn.execute("SELECT id FROM products WHERE url='http://test.com/p1'").fetchone()[0]
    conn.execute(
        "INSERT INTO reviews (product_id, author, headline, body, body_hash, rating, date_published) "
        "VALUES (?, 'John', 'Great', 'Really great product', 'abc123', 5.0, '2026-03-10')",
        (pid,)
    )
    conn.commit()
    conn.close()
    yield db_path


def test_query_report_data():
    from server.report import query_report_data
    products, reviews = query_report_data("2020-01-01T00:00:00")
    assert len(products) >= 1
    assert products[0]["name"] == "Test Product"
    assert len(reviews) >= 1
    assert reviews[0]["author"] == "John"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report.py::test_query_report_data -v`
Expected: FAIL (server.report 不存在)

- [ ] **Step 3: 实现数据查询**

```python
# server/report.py
"""Report generation — query, translate, Excel, email."""

import json
import logging
from datetime import datetime, timezone

import config
import models

logger = logging.getLogger(__name__)


def query_report_data(since: str) -> tuple[list[dict], list[dict]]:
    """Query products and reviews added since the given UTC timestamp."""
    conn = models.get_conn()
    try:
        products = [
            dict(r) for r in conn.execute(
                "SELECT url, name, sku, price, stock_status, rating, review_count, "
                "scraped_at, site, ownership FROM products "
                "WHERE scraped_at >= datetime(?) ORDER BY site, ownership",
                (since,),
            ).fetchall()
        ]
        reviews = [
            dict(r) for r in conn.execute(
                "SELECT p.name AS product_name, r.author, r.headline, r.body, "
                "r.rating, r.date_published, r.images, p.ownership "
                "FROM reviews r JOIN products p ON r.product_id = p.id "
                "WHERE r.scraped_at >= datetime(?) ORDER BY p.name",
                (since,),
            ).fetchall()
        ]
        return products, reviews
    finally:
        conn.close()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report.py::test_query_report_data -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/report.py tests/test_report.py
git commit -m "feat(report): add data query for report generation"
```

### Task 4: LLM 翻译功能

**Files:**
- Modify: `server/report.py`
- Modify: `tests/test_report.py`

- [ ] **Step 1: 写测试 — 翻译函数（mock OpenAI）**

追加到 `tests/test_report.py`：

```python
from unittest.mock import patch, MagicMock


def test_translate_reviews_success():
    from server.report import translate_reviews

    reviews = [
        {"headline": "Great product", "body": "I love this item"},
        {"headline": "Bad quality", "body": "Broke after one use"},
    ]

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps([
        {"headline_cn": "很棒的产品", "body_cn": "我喜欢这个产品"},
        {"headline_cn": "质量差", "body_cn": "用了一次就坏了"},
    ])

    with patch("server.report._call_llm", return_value=mock_response):
        result = translate_reviews(reviews)

    assert len(result) == 2
    assert result[0]["headline_cn"] == "很棒的产品"
    assert result[1]["body_cn"] == "用了一次就坏了"


import json

def test_translate_reviews_empty():
    from server.report import translate_reviews
    result = translate_reviews([])
    assert result == []


def test_translate_reviews_partial_failure():
    from server.report import translate_reviews

    reviews = [{"headline": "Good", "body": "Nice"}]

    with patch("server.report._call_llm", side_effect=Exception("API error")):
        result = translate_reviews(reviews)

    assert len(result) == 1
    assert result[0]["headline_cn"] == ""
    assert result[0]["body_cn"] == ""
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report.py -k translate -v`
Expected: FAIL

- [ ] **Step 3: 实现翻译功能**

追加到 `server/report.py`：

```python
from openai import OpenAI


def _get_llm_client() -> OpenAI | None:
    """Get OpenAI-compatible client, or None if not configured."""
    if not config.LLM_API_KEY or not config.LLM_API_BASE:
        return None
    return OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_API_BASE)


def _call_llm(prompt: str, system: str = "You are a translator."):
    """Call LLM API."""
    client = _get_llm_client()
    if not client:
        raise RuntimeError("LLM not configured (LLM_API_BASE / LLM_API_KEY missing)")
    return client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
    )


def translate_reviews(reviews: list[dict]) -> list[dict]:
    """Translate review headlines and bodies to Chinese.

    Returns a new list with headline_cn and body_cn added to each review.
    Never raises — on failure, Chinese fields are empty strings.
    """
    if not reviews:
        return []

    result = []
    batch_size = config.LLM_TRANSLATE_BATCH_SIZE

    for i in range(0, len(reviews), batch_size):
        batch = reviews[i:i + batch_size]
        batch_input = [
            {"index": j, "headline": r.get("headline", ""), "body": r.get("body", "")}
            for j, r in enumerate(batch)
        ]

        try:
            prompt = (
                "将以下英文评论的 headline 和 body 翻译为中文，保持原意，简洁自然。\n"
                "返回 JSON 数组，每个元素包含 headline_cn 和 body_cn。\n"
                "只返回 JSON，不要其他内容。\n\n"
                + json.dumps(batch_input, ensure_ascii=False)
            )
            resp = _call_llm(prompt)
            content = resp.choices[0].message.content.strip()
            # Handle markdown code blocks
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            translations = json.loads(content)

            for j, r in enumerate(batch):
                cn = translations[j] if j < len(translations) else {}
                result.append({
                    **r,
                    "headline_cn": cn.get("headline_cn", ""),
                    "body_cn": cn.get("body_cn", ""),
                })
        except Exception as e:
            logger.warning(f"Translation batch {i//batch_size} failed: {e}")
            for r in batch:
                result.append({**r, "headline_cn": "", "body_cn": ""})

    return result
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report.py -k translate -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add server/report.py tests/test_report.py
git commit -m "feat(report): add LLM review translation with batch processing"
```

### Task 5: Excel 生成

**Files:**
- Modify: `server/report.py`
- Modify: `tests/test_report.py`

- [ ] **Step 1: 写测试 — Excel 生成**

追加到 `tests/test_report.py`：

```python
from openpyxl import load_workbook


def test_generate_excel(tmp_path):
    from server.report import generate_excel

    products = [
        {"url": "http://test.com", "name": "Product A", "sku": "A-1",
         "price": 29.99, "stock_status": "in_stock", "rating": 4.5,
         "review_count": 10, "scraped_at": "2026-03-10", "site": "basspro",
         "ownership": "own"},
    ]
    reviews = [
        {"product_name": "Product A", "author": "John", "headline": "Good",
         "body": "Nice product", "headline_cn": "好的", "body_cn": "好产品",
         "rating": 5.0, "date_published": "2026-03-10", "images": None,
         "ownership": "own"},
    ]

    path = generate_excel(products, reviews, output_dir=str(tmp_path))
    assert os.path.exists(path)
    assert path.endswith(".xlsx")

    wb = load_workbook(path)
    assert "产品" in wb.sheetnames
    assert "评论" in wb.sheetnames

    ws_products = wb["产品"]
    assert ws_products.cell(1, 1).value == "产品地址"
    assert ws_products.cell(2, 2).value == "Product A"

    ws_reviews = wb["评论"]
    assert ws_reviews.cell(1, 1).value == "产品名称"
    assert ws_reviews.cell(2, 5).value == "好的"  # headline_cn


def test_generate_excel_empty(tmp_path):
    from server.report import generate_excel

    path = generate_excel([], [], output_dir=str(tmp_path))
    assert os.path.exists(path)
    wb = load_workbook(path)
    # Should have headers but no data rows
    assert wb["产品"].max_row == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report.py -k excel -v`
Expected: FAIL

- [ ] **Step 3: 实现 Excel 生成**

追加到 `server/report.py`：

```python
import os

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill


def generate_excel(
    products: list[dict],
    reviews: list[dict],
    output_dir: str | None = None,
) -> str:
    """Generate Excel report with Products and Reviews sheets. Returns file path."""
    if output_dir is None:
        output_dir = config.REPORT_DIR

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filename = f"scrape-report-{today}.xlsx"
    filepath = os.path.join(output_dir, filename)

    wb = Workbook()

    # ── Sheet 1: Products ──
    ws1 = wb.active
    ws1.title = "产品"
    product_headers = [
        "产品地址", "产品名称", "SKU", "售价$", "库存状态",
        "综合评分", "评论数量", "抓取时间", "站点", "归属",
    ]
    product_keys = [
        "url", "name", "sku", "price", "stock_status",
        "rating", "review_count", "scraped_at", "site", "ownership",
    ]
    _write_sheet(ws1, product_headers, products, product_keys)

    # ── Sheet 2: Reviews ──
    ws2 = wb.create_sheet("评论")
    review_headers = [
        "产品名称", "评论人", "标题（原文）", "内容（原文）",
        "标题（中文）", "内容（中文）", "打分", "评论时间", "照片",
    ]
    review_keys = [
        "product_name", "author", "headline", "body",
        "headline_cn", "body_cn", "rating", "date_published", "images",
    ]
    _write_sheet(ws2, review_headers, reviews, review_keys)

    wb.save(filepath)
    logger.info(f"Excel report saved to {filepath}")
    return filepath


def _write_sheet(ws, headers: list[str], data: list[dict], keys: list[str]):
    """Write headers + data rows to a worksheet with basic styling."""
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")

    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")

    for row_idx, item in enumerate(data, 2):
        for col_idx, key in enumerate(keys, 1):
            value = item.get(key)
            if isinstance(value, (list, dict)):
                value = json.dumps(value, ensure_ascii=False) if value else ""
            ws.cell(row=row_idx, column=col_idx, value=value)

    # Auto-adjust column widths (approximate)
    for col in range(1, len(headers) + 1):
        max_len = len(str(headers[col - 1]))
        for row in range(2, min(len(data) + 2, 52)):  # Sample first 50 rows
            val = ws.cell(row=row, column=col).value
            if val:
                max_len = max(max_len, min(len(str(val)), 60))
        ws.column_dimensions[ws.cell(1, col).column_letter].width = max_len + 2
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report.py -k excel -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add server/report.py tests/test_report.py
git commit -m "feat(report): add Excel report generation with openpyxl"
```

### Task 6: 邮件发送

**Files:**
- Modify: `server/report.py`
- Modify: `tests/test_report.py`

- [ ] **Step 1: 写测试 — 邮件发送（mock SMTP）**

追加到 `tests/test_report.py`：

```python
def test_send_email_success(tmp_path):
    from server.report import send_email

    # Create a dummy file
    dummy_file = tmp_path / "report.xlsx"
    dummy_file.write_bytes(b"fake excel content")

    recipients = ["test@example.com"]
    subject = "Test Report"
    body_text = "Test body"

    with patch("server.report.smtplib.SMTP") as mock_smtp_cls:
        mock_smtp = MagicMock()
        mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_smtp)
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = send_email(recipients, subject, body_text, str(dummy_file))

    assert result["success"] is True
    assert result["recipients"] == 1


def test_send_email_no_config():
    from server.report import send_email

    with patch.object(config, "SMTP_HOST", ""):
        result = send_email(["a@b.com"], "sub", "body")

    assert result["success"] is False
    assert "not configured" in result["error"]


def test_send_email_no_recipients():
    from server.report import send_email
    result = send_email([], "sub", "body")
    assert result["success"] is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report.py -k email -v`
Expected: FAIL

- [ ] **Step 3: 实现邮件发送**

追加到 `server/report.py`：

```python
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders


def send_email(
    recipients: list[str],
    subject: str,
    body_text: str,
    attachment_path: str | None = None,
) -> dict:
    """Send email with optional attachment. Returns {"success": bool, ...}."""
    if not recipients:
        return {"success": False, "error": "No recipients", "recipients": 0}

    if not config.SMTP_HOST:
        return {"success": False, "error": "SMTP not configured", "recipients": 0}

    try:
        msg = MIMEMultipart()
        msg["From"] = config.SMTP_FROM or config.SMTP_USER
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = subject
        msg.attach(MIMEText(body_text, "plain", "utf-8"))

        if attachment_path and os.path.exists(attachment_path):
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
            with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT) as server:
                if config.SMTP_USER and config.SMTP_PASSWORD:
                    server.login(config.SMTP_USER, config.SMTP_PASSWORD)
                server.sendmail(msg["From"], recipients, msg.as_string())
        else:
            with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                if config.SMTP_USER and config.SMTP_PASSWORD:
                    server.login(config.SMTP_USER, config.SMTP_PASSWORD)
                server.sendmail(msg["From"], recipients, msg.as_string())

        logger.info(f"Email sent to {len(recipients)} recipients")
        return {"success": True, "recipients": len(recipients), "error": None}

    except Exception as e:
        logger.error(f"Email failed: {e}")
        return {"success": False, "error": str(e), "recipients": 0}


def load_email_recipients(filepath: str) -> list[str]:
    """Load email recipients from a text file (one per line, # for comments)."""
    if not os.path.exists(filepath):
        return []
    recipients = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                recipients.append(line)
    return recipients
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report.py -k email -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add server/report.py tests/test_report.py
git commit -m "feat(report): add email sending with SMTP and attachment support"
```

---

## Chunk 3: 主入口函数 + MCP Tool 注册

### Task 7: generate_report 主函数

**Files:**
- Modify: `server/report.py`
- Modify: `tests/test_report.py`

- [ ] **Step 1: 写测试 — generate_report 主函数**

追加到 `tests/test_report.py`：

```python
def test_generate_report_full(tmp_path, monkeypatch):
    from server.report import generate_report

    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    monkeypatch.setattr(config, "LLM_API_KEY", "")  # Skip translation
    monkeypatch.setattr(config, "SMTP_HOST", "")  # Skip email

    result = generate_report("2020-01-01T00:00:00", send_email=False)

    assert "products_count" in result
    assert "reviews_count" in result
    assert "excel_path" in result
    assert result["products_count"] >= 1
    assert os.path.exists(result["excel_path"])


def test_generate_report_with_email(tmp_path, monkeypatch):
    from server.report import generate_report

    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
    monkeypatch.setattr(config, "LLM_API_KEY", "")
    monkeypatch.setattr(config, "SMTP_HOST", "")

    result = generate_report("2020-01-01T00:00:00", send_email=True)
    # Email should fail gracefully (SMTP not configured)
    assert result["email"]["success"] is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report.py -k "generate_report" -v`
Expected: FAIL

- [ ] **Step 3: 实现 generate_report 主函数**

追加到 `server/report.py`：

```python
# Default recipients file path (OpenClaw workspace convention)
_DEFAULT_RECIPIENTS_FILE = os.path.expanduser(
    "~/.openclaw/workspace/config/email-recipients.txt"
)


def generate_report(
    since: str,
    send_email: bool = True,
    recipients_file: str | None = None,
) -> dict:
    """Generate a full scrape report: query → translate → Excel → email.

    Args:
        since: UTC timestamp (YYYY-MM-DDTHH:MM:SS), query data since this time.
        send_email: Whether to send email with the report.
        recipients_file: Path to recipients file. Defaults to OpenClaw workspace config.

    Returns:
        Summary dict with counts, paths, and email result.
    """
    logger.info(f"Generating report for data since {since}")

    # 1. Query data
    products, reviews = query_report_data(since)
    logger.info(f"Found {len(products)} products, {len(reviews)} reviews")

    # 2. Translate reviews
    translated_count = 0
    translated_reviews = reviews  # Default: no translation
    if reviews and config.LLM_API_KEY and config.LLM_API_BASE:
        try:
            translated_reviews = translate_reviews(reviews)
            translated_count = sum(
                1 for r in translated_reviews if r.get("headline_cn")
            )
            logger.info(f"Translated {translated_count}/{len(reviews)} reviews")
        except Exception as e:
            logger.error(f"Translation failed: {e}")
            translated_reviews = [{**r, "headline_cn": "", "body_cn": ""} for r in reviews]
    else:
        translated_reviews = [{**r, "headline_cn": "", "body_cn": ""} for r in reviews]
        if reviews:
            logger.warning("LLM not configured, skipping translation")

    # 3. Generate Excel
    excel_path = generate_excel(products, translated_reviews)

    # 4. Send email (optional)
    email_result = {"success": False, "error": "Email sending disabled", "recipients": 0}
    if send_email:
        rfile = recipients_file or _DEFAULT_RECIPIENTS_FILE
        recipients = load_email_recipients(rfile)
        if recipients:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            own_count = sum(1 for p in products if p.get("ownership") == "own")
            comp_count = len(products) - own_count

            email_result = send_email_report(
                recipients=recipients,
                subject=f"[Qbu-Crawler] 每日爬虫报告 {today}",
                body_text=(
                    f"每日爬虫报告\n\n"
                    f"新增产品：{len(products)} 个（自有 {own_count}，竞品 {comp_count}）\n"
                    f"新增评论：{len(reviews)} 条\n"
                    f"翻译完成：{translated_count} 条\n\n"
                    f"详见附件 Excel 报告。"
                ),
                attachment_path=excel_path,
            )
        else:
            email_result = {"success": False, "error": "No recipients configured", "recipients": 0}

    return {
        "products_count": len(products),
        "reviews_count": len(reviews),
        "translated_count": translated_count,
        "excel_path": excel_path,
        "email": email_result,
    }


# Alias to avoid name collision with the send_email function
send_email_report = send_email
```

注意：需要把前面定义的 `send_email` 函数重命名处理。实际上更好的做法是在 `generate_report` 函数定义前就将 `send_email` 重命名为 `send_email_report`：

在文件顶部定义区域之后、`generate_report` 之前，加入：
```python
# Re-export for internal use (avoid shadowing by generate_report's parameter name)
send_email_report = send_email
```

然后删除函数末尾的那行重复赋值。

- [ ] **Step 4: 运行全部测试**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/test_report.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add server/report.py tests/test_report.py
git commit -m "feat(report): add generate_report main function with full pipeline"
```

### Task 8: 注册 MCP Tool

**Files:**
- Modify: `server/mcp/tools.py`

- [ ] **Step 1: 在 `register_tools` 函数末尾添加 generate_report tool**

在 `execute_sql` tool 之后、函数结束之前添加：

```python
    # ── Report Generation ─────────────────────────────

    @mcp.tool
    def generate_report(since: str, send_email: str = "true") -> str:
        """生成爬虫数据报告：查询新增数据 → 翻译评论为中文 → 生成 Excel → 发送邮件。
        - since: UTC 时间戳（YYYY-MM-DDTHH:MM:SS），查询该时间之后的新增数据
        - send_email: 是否发送邮件，"true" 或 "false"
        返回报告摘要：新增产品数、评论数、翻译数、Excel 路径、邮件发送结果。"""
        from server.report import generate_report as _generate_report
        try:
            result = _generate_report(
                since=since,
                send_email=(send_email.lower() == "true"),
            )
            return _json.dumps(result, default=str, ensure_ascii=False)
        except Exception as e:
            return _json.dumps({"error": f"Report generation failed: {e}"})
```

- [ ] **Step 2: 验证服务能启动**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run python -c "from server.mcp.tools import register_tools; print('OK')"`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add server/mcp/tools.py
git commit -m "feat(mcp): register generate_report tool"
```

---

## Chunk 4: OpenClaw Plugin 修复 + 文档更新

### Task 9: 修复 plugin index.js — 添加缺失的 ownership 参数 + 新 tool

**Files:**
- Modify: `server/openclaw/plugin/index.js`

- [ ] **Step 1: 修复 start_scrape — 添加 ownership 必填参数**

将 `start_scrape` 的 tool 定义替换为：

```javascript
{
    name: "start_scrape",
    description: "Submit product URLs for scraping. Params: urls (array of URL strings), ownership (required: 'own' or 'competitor').",
    parameters: {
      type: "object",
      properties: {
        urls: { type: "array", items: { type: "string" }, description: "Product page URLs to scrape" },
        ownership: { type: "string", description: "Product ownership: 'own' or 'competitor' (required)" }
      },
      required: ["urls", "ownership"]
    }
},
```

- [ ] **Step 2: 修复 start_collect — 添加 ownership 必填参数**

```javascript
{
    name: "start_collect",
    description: "Collect products from a category page then scrape each. Params: category_url (string), ownership (required: 'own' or 'competitor'), max_pages (int, 0=all).",
    parameters: {
      type: "object",
      properties: {
        category_url: { type: "string", description: "Category page URL" },
        ownership: { type: "string", description: "Product ownership: 'own' or 'competitor' (required)" },
        max_pages: { type: "integer", description: "Max pages to collect, 0 for all" }
      },
      required: ["category_url", "ownership"]
    }
},
```

- [ ] **Step 3: 修复 list_products — 添加 ownership 可选参数**

在 `list_products` 的 properties 中添加：

```javascript
ownership: { type: "string", description: "Ownership filter: own or competitor" },
```

- [ ] **Step 4: 修复 query_reviews — 添加 ownership + sku 可选参数**

在 `query_reviews` 的 properties 中添加：

```javascript
sku: { type: "string", description: "Filter by product SKU" },
ownership: { type: "string", description: "Ownership filter: own or competitor" },
```

- [ ] **Step 5: 添加 generate_report tool**

在 TOOLS 数组末尾（execute_sql 之后）添加：

```javascript
{
    name: "generate_report",
    description: "Generate scrape report: query new data since timestamp, translate reviews to Chinese, generate Excel, send email. Returns summary with counts and email status.",
    parameters: {
      type: "object",
      properties: {
        since: { type: "string", description: "UTC timestamp (YYYY-MM-DDTHH:MM:SS), query data after this time" },
        send_email: { type: "string", description: "Send email with report: 'true' or 'false', default 'true'" }
      },
      required: ["since"]
    }
},
```

- [ ] **Step 6: Commit**

```bash
git add server/openclaw/plugin/index.js
git commit -m "fix(plugin): add missing ownership params + register generate_report tool"
```

### Task 10: 更新文档

**Files:**
- Modify: `CLAUDE.md`
- Modify: `server/openclaw/README.md`

- [ ] **Step 1: 更新 CLAUDE.md**

在项目结构中添加 `server/report.py` 和 `tests/test_report.py`。
在 MCP 服务架构部分添加 `generate_report` tool 说明。
在配置表中添加 LLM 和 SMTP 配置项。

- [ ] **Step 2: 更新 server/openclaw/README.md**

在工具列表中添加 `generate_report`。
更新 workspace 文件说明（AGENTS.md 替代旧模板、BOOTSTRAP.md 已删除等）。

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md server/openclaw/README.md
git commit -m "docs: update CLAUDE.md and openclaw README for generate_report tool"
```

### Task 11: 最终验证

- [ ] **Step 1: 运行所有测试**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && uv run pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 2: 验证服务启动**

Run: `cd E:/Project/ForcomeAiTools/Qbu-Crawler && timeout 5 uv run python main.py serve || true`
Expected: 服务正常启动，输出 MCP 和 HTTP API 地址

- [ ] **Step 3: 验证 workspace 文件完整性**

检查所有 workspace 文件存在且格式正确：
- AGENTS.md, SOUL.md, TOOLS.md, HEARTBEAT.md, USER.md, IDENTITY.md
- skills/ 下所有 SKILL.md 都有 frontmatter
- BOOTSTRAP.md 已删除
