# Report V3 Phase 4 — Excel Redesign + Cleanup

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace 6-sheet analytical Excel with 4-sheet data-oriented format. Remove PDF pipeline and deprecated templates. Final cleanup.

**Architecture:** Excel becomes a data tool (raw reviews, product overview, labels, trends). PDF generation removed entirely — V3 HTML is the primary report. Playwright dependency removed.

**Tech Stack:** Python 3.10+, openpyxl, pytest

**Spec Reference:** `docs/superpowers/specs/2026-04-10-report-v3-redesign.md` — Sections 9, 10.3, 10.4, 15.10

**Prerequisite:** Phase 3a and 3b complete. V3 HTML is the primary report format and has been validated.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `qbu_crawler/server/report.py` | Modify | Replace `generate_excel` with 4-sheet version |
| `qbu_crawler/server/report_pdf.py` | Delete | PDF generation no longer needed |
| `qbu_crawler/server/report_templates/daily_report.html.j2` | Delete | Replaced by V3 template |
| `qbu_crawler/server/report_templates/daily_report.css` | Delete | Replaced by V3 CSS |
| `qbu_crawler/server/report_templates/daily_report_email.html.j2` | Delete | Replaced by 3 email templates |
| `qbu_crawler/server/report_templates/daily_report_email_body.txt.j2` | Delete | Replaced |
| `pyproject.toml` | Modify | Remove `playwright` from dependencies |
| `tests/test_report_pdf.py` | Delete | No longer applicable |
| `tests/test_v3_cleanup.py` | Create | Verify 4-sheet Excel structure |

---

### Task 1: Replace generate_excel with 4-sheet data format

**Files:**
- Modify: `qbu_crawler/server/report.py` (`generate_excel`)
- Test: `tests/test_v3_cleanup.py` (create)

**Spec ref:** Section 9.2

- [ ] **Step 1: Write 4-sheet Excel tests**

```python
# tests/test_v3_cleanup.py
"""Tests for Report V3 Phase 4 — Excel redesign + cleanup."""

import openpyxl
import pytest
from qbu_crawler.server.report import generate_excel


class TestExcel4Sheet:
    def test_produces_4_sheets(self, tmp_path):
        products = [{"name": "P1", "sku": "S1", "site": "test", "ownership": "own",
                      "price": 99.99, "stock_status": "in_stock", "rating": 4.0,
                      "review_count": 10, "scraped_at": "2026-04-10"}]
        reviews = [{"id": 1, "product_name": "P1", "product_sku": "S1", "author": "user",
                     "headline": "Great", "body": "Nice product", "headline_cn": "好",
                     "body_cn": "好产品", "rating": 5.0, "date_published_parsed": "2026-04-01",
                     "ownership": "own", "sentiment": "positive", "images": None,
                     "translate_status": "done"}]
        path = generate_excel(products, reviews, output_path=str(tmp_path / "test.xlsx"))
        wb = openpyxl.load_workbook(path)
        assert set(wb.sheetnames) == {"评论明细", "产品概览", "问题标签", "趋势数据"}

    def test_review_sheet_has_correct_columns(self, tmp_path):
        products = [{"name": "P1", "sku": "S1", "site": "test", "ownership": "own",
                      "price": 99.99, "stock_status": "in_stock", "rating": 4.0,
                      "review_count": 10, "scraped_at": "2026-04-10"}]
        reviews = [{"id": 1, "product_name": "P1", "product_sku": "S1", "author": "user",
                     "headline": "Great", "body": "Nice", "headline_cn": "好",
                     "body_cn": "好", "rating": 5.0, "date_published_parsed": "2026-04-01",
                     "ownership": "own", "sentiment": "positive", "images": None,
                     "translate_status": "done"}]
        path = generate_excel(products, reviews, output_path=str(tmp_path / "test.xlsx"))
        wb = openpyxl.load_workbook(path)
        ws = wb["评论明细"]
        headers = [cell.value for cell in ws[1]]
        assert "ID" in headers
        assert "产品名称" in headers
        assert "评分" in headers
        assert "标题(中文)" in headers

    def test_no_embedded_images(self, tmp_path):
        """V3 Excel uses URL links, not embedded images."""
        products = []
        reviews = [{"id": 1, "product_name": "P1", "product_sku": "S1", "author": "user",
                     "headline": "Great", "body": "Nice", "headline_cn": "好",
                     "body_cn": "好", "rating": 5.0, "date_published_parsed": "2026-04-01",
                     "ownership": "own", "sentiment": "positive",
                     "images": '["https://example.com/img.jpg"]',
                     "translate_status": "done"}]
        path = generate_excel(products, reviews, output_path=str(tmp_path / "test.xlsx"))
        wb = openpyxl.load_workbook(path)
        ws = wb["评论明细"]
        # Should have no openpyxl images
        assert len(ws._images) == 0
```

- [ ] **Step 2: Rewrite generate_excel**

Replace the existing `generate_excel` function in `report.py` with a 4-sheet version:

- Sheet 1 "评论明细": Flat table of all reviews with columns from spec Section 9.2
- Sheet 2 "产品概览": Product metadata with risk_score
- Sheet 3 "问题标签": Pivot-ready review_id × label_code table
- Sheet 4 "趋势数据": Time series from product_snapshots

Remove image downloading (no more `_download_images_parallel`, `_download_and_resize`). Images are URL strings only.

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/test_v3_cleanup.py -v`
Expected: All pass

- [ ] **Step 4: Fix existing Excel tests**

Run: `uv run pytest tests/test_report_excel.py -v`
Update any tests that assert old sheet names or embedded image behavior.

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/server/report.py tests/test_v3_cleanup.py tests/test_report_excel.py
git commit -m "feat(report): 4-sheet data-oriented Excel — reviews, products, labels, trends

Removes embedded images (URL links only). Removes analytical sheets
(Executive Summary, Issue Analysis, etc.) — now handled by HTML report."
```

---

### Task 2: Remove PDF pipeline + deprecated templates

**Files:**
- Delete: `qbu_crawler/server/report_pdf.py`
- Delete: `qbu_crawler/server/report_templates/daily_report.html.j2`
- Delete: `qbu_crawler/server/report_templates/daily_report.css`
- Delete: `qbu_crawler/server/report_templates/daily_report_email.html.j2`
- Delete: `qbu_crawler/server/report_templates/daily_report_email_body.txt.j2`
- Delete: `tests/test_report_pdf.py`
- Modify: `qbu_crawler/server/report_snapshot.py` (remove PDF generation call)
- Modify: `pyproject.toml` (remove playwright)

- [ ] **Step 1: Remove PDF call from report pipeline**

In `report_snapshot.py::generate_full_report_from_snapshot` (or the new `_generate_full_report`), remove:
```python
# Remove these lines:
pdf_path = report_pdf.generate_pdf_report(snapshot, analytics, ...)
```

Move `render_v3_html` from `report_pdf.py` to `report_snapshot.py` or a new `report_html.py` before deleting `report_pdf.py`.

- [ ] **Step 2: Remove import of report_pdf**

In `report_snapshot.py`, remove `from qbu_crawler.server import report_pdf` and any references.

- [ ] **Step 3: Delete files**

```bash
git rm qbu_crawler/server/report_pdf.py
git rm qbu_crawler/server/report_templates/daily_report.html.j2
git rm qbu_crawler/server/report_templates/daily_report.css
git rm qbu_crawler/server/report_templates/daily_report_email.html.j2
git rm qbu_crawler/server/report_templates/daily_report_email_body.txt.j2
git rm tests/test_report_pdf.py
```

- [ ] **Step 4: Remove playwright from pyproject.toml**

In `pyproject.toml`, remove `playwright` from the dependencies list.

- [ ] **Step 5: Run all tests**

Run: `uv run pytest tests/ -x -q --ignore=tests/test_report_charts.py`
Expected: All pass (test_report_pdf.py deleted, no dangling imports)

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore(report): remove PDF pipeline + deprecated templates

Delete report_pdf.py, old Jinja2 templates, test_report_pdf.py.
Remove playwright dependency from pyproject.toml.
V3 HTML is now the sole report format."
```

---

### Task 3: Final end-to-end validation

- [ ] **Step 1: Run complete test suite**

```bash
uv run pytest tests/ -x -q
```

Expected: All tests pass (the pre-existing `test_report_charts.py` failure may now be resolved since Plotly functions may have been replaced).

- [ ] **Step 2: Generate a test report**

```bash
uv run python -c "
from qbu_crawler.server.report_snapshot import generate_report_from_snapshot
import json
snapshot = json.load(open('data/reports/workflow-run-1-snapshot-2026-04-08.json'))
result = generate_report_from_snapshot(snapshot, send_email=False)
print(json.dumps(result, indent=2, ensure_ascii=False))
"
```

Verify: HTML file generated, Excel file generated, analytics JSON generated.

- [ ] **Step 3: Open HTML in browser and verify**

- All 6 tabs render
- Charts are interactive (hover, zoom)
- Issue cards collapse/expand
- Evidence images open in lightbox
- Review table sorts and filters
- Print-to-PDF produces clean output

- [ ] **Step 4: Simulate quiet day**

```bash
uv run python -c "
from qbu_crawler.server.report_snapshot import generate_report_from_snapshot
snapshot = {'run_id': 99, 'logical_date': '2026-04-10', 'products': [...], 'reviews': [], 'snapshot_at': '2026-04-10T08:00:00+08:00'}
# ... load previous analytics ...
result = generate_report_from_snapshot(snapshot, previous_analytics=prev, previous_snapshot=prev_snap, send_email=False)
print(result['mode'])  # Should be 'quiet'
"
```

- [ ] **Step 5: Commit final validation**

```bash
git commit --allow-empty -m "chore(report): V3 Phase 4 complete — end-to-end validated"
```

---

## Phase 4 Completion Checklist

- [ ] Excel has exactly 4 sheets: 评论明细, 产品概览, 问题标签, 趋势数据
- [ ] No embedded images in Excel (URLs only)
- [ ] `report_pdf.py` deleted
- [ ] Old templates deleted
- [ ] `playwright` removed from pyproject.toml
- [ ] `test_report_pdf.py` deleted
- [ ] All tests pass
- [ ] HTML report renders correctly in browser
- [ ] Quiet day report generates from previous analytics
- [ ] Email sends for all 3 modes
