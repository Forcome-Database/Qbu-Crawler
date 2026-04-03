# Daily PDF Report Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 daily workflow 单出口基础上新增可复现的 `analytics JSON + PDF` 产物，并以 `Excel + PDF` 双附件发送每日深度报告，报告主轴聚焦自有产品差评、问题簇和改良建议，竞品章节聚焦好评 benchmark。

**Architecture:** 保持现有 `DailySchedulerWorker -> WorkflowWorker -> report_snapshot` 主链路不变，只扩 full report 产物层。`report_snapshot` 先基于 frozen snapshot 构建 analytics artifact，再分别生成 Excel 和 PDF，并通过兼容旧签名的多附件邮件接口发出；`WorkflowWorker` 只负责持久化新 artifact 路径和通知 payload。标签层采用轻量持久化表 `review_issue_labels`，先用规则分类，预留可选 LLM 归一化入口。

**Tech Stack:** Python 3.10+, SQLite, openpyxl, Jinja2, Playwright(Chromium), matplotlib(SVG 图表), pytest。

---

## File Map

### 核心运行时

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `pyproject.toml` | 增加 `jinja2`、`matplotlib`、`playwright`，并确保模板/CSS 资源可被打包 |
| Modify | `qbu_crawler/config.py:1-180` | 增加 PDF/标签模式最小配置，保持默认值可直接运行 |
| Modify | `qbu_crawler/models.py:28-160,436-548` | 扩展 `workflow_runs` artifact 字段，新增 `review_issue_labels` 表及读写 helper |
| Modify | `qbu_crawler/server/report.py:285-360,646-820` | 邮件改为兼容单附件和多附件；保持 legacy subject/body 不变 |
| Create | `qbu_crawler/server/report_analytics.py` | 标签分类、首日/增量模式判定、风险排序、analytics JSON 组装 |
| Create | `qbu_crawler/server/report_pdf.py` | 图表 SVG 生成、HTML 渲染、Playwright 导出 PDF |
| Create | `qbu_crawler/server/report_templates/daily_report.html.j2` | 主 PDF HTML 模板 |
| Create | `qbu_crawler/server/report_templates/daily_report.css` | A4 print CSS、分页、卡片、图表样式 |
| Modify | `qbu_crawler/server/report_snapshot.py:15-136` | 生成 analytics artifact、调用 PDF/Excel 生成、多附件邮件发送 |
| Modify | `qbu_crawler/server/workflows.py:553-650` | 保存 `analytics_path/pdf_path`，扩展 `workflow_full_report` payload |

### 测试与文档

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `tests/test_report.py` | 多附件邮件兼容性、legacy subject/body 保持不变 |
| Modify | `tests/test_filtered_reports.py` | 过滤报告仍走旧 Excel 单附件路径，不受新签名破坏 |
| Create | `tests/test_report_analytics.py` | 标签分类、模式判定、analytics 结构、风险排序 |
| Create | `tests/test_report_pdf.py` | 模板渲染、SVG 图表、Playwright PDF 调用契约 |
| Modify | `tests/test_report_snapshot.py` | full report 新增 `analytics_path/pdf_path`，邮件附件变更 |
| Modify | `tests/test_workflows.py` | workflow 持久化新 artifact、通知 payload、失败回退 |
| Modify | `tests/test_metric_semantics.py` | analytics 不混淆 `ingested_review_rows` 与 `site_reported_review_total_current` |
| Modify | `README.md` | 增加 PDF 运行依赖、字体/Chromium 安装、排障说明 |
| Modify | `.env.example` | 暴露最小 PDF/标签配置项 |
| Modify | `AGENTS.md` | 同步项目技术栈与报告链路增量 |

---

## Chunk 1: 基础契约、依赖和持久化骨架

### Task 1: 锁定 PDF/标签运行时依赖与最小配置

**Files:**
- Modify: `pyproject.toml`
- Modify: `qbu_crawler/config.py:1-180`
- Modify: `.env.example`
- Modify: `README.md`
- Test: `tests/test_workflows.py`

- [ ] **Step 1: 先写配置失败测试**

在 `tests/test_workflows.py` 增加：

```python
def test_config_report_pdf_defaults(monkeypatch: pytest.MonkeyPatch):
    config = _reload_config(monkeypatch)

    assert config.REPORT_LABEL_MODE == "rule"
    assert config.REPORT_PDF_TIMEOUT_SECONDS == 60
    assert config.REPORT_PDF_FONT_FAMILY == "Noto Sans CJK SC"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_workflows.py::test_config_report_pdf_defaults -v`

Expected:
- FAIL，提示缺少 `REPORT_LABEL_MODE`、`REPORT_PDF_TIMEOUT_SECONDS`、`REPORT_PDF_FONT_FAMILY`

- [ ] **Step 3: 在 `pyproject.toml` 增加依赖并补齐包资源声明**

新增依赖：

```toml
"jinja2>=3.1.0",
"matplotlib>=3.9.0",
"playwright>=1.54.0",
```

同时把模板/CSS 资源加入打包清单，避免 wheel 环境里找不到：

```toml
[tool.hatch.build.targets.wheel]
packages = ["qbu_crawler"]
include = ["qbu_crawler/server/report_templates/**/*"]

[tool.hatch.build.targets.sdist]
include = [
    "qbu_crawler/**/*.py",
    "qbu_crawler/server/report_templates/**/*",
    "main.py",
    "README.md",
    "LICENSE",
    ".env.example",
]
```

- [ ] **Step 4: 在 `qbu_crawler/config.py` 增加最小配置项**

只加这 3 个，避免配置爆炸：

```python
REPORT_LABEL_MODE = _enum_env("REPORT_LABEL_MODE", "rule", ("rule", "hybrid"))
REPORT_PDF_TIMEOUT_SECONDS = int(os.getenv("REPORT_PDF_TIMEOUT_SECONDS", "60"))
REPORT_PDF_FONT_FAMILY = os.getenv("REPORT_PDF_FONT_FAMILY", "Noto Sans CJK SC").strip()
```

- [ ] **Step 5: 在 `.env.example` 和 `README.md` 写运行前提**

`README.md` 必须明确写出：

```bash
uv sync
uv run playwright install chromium
```

以及两条部署要求：
- 服务器安装统一中文字体
- 模板、CSS、图表资源全部走本地，不走 CDN

- [ ] **Step 6: 安装依赖并做导入烟测**

Run: `uv sync`

Expected:
- 新依赖安装完成，`uv.lock` 更新

Run: `uv run python -c "from jinja2 import Environment; import matplotlib; from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(headless=True); page=b.new_page(); page.set_content('<html><body>ok</body></html>'); print(page.text_content('body')); b.close(); p.stop()"`

Expected:
- 输出 `ok`，说明 Chromium 二进制可真正启动，不只是 import 成功

- [ ] **Step 7: 重新运行配置测试**

Run: `uv run pytest tests/test_workflows.py::test_config_report_pdf_defaults -v`

Expected:
- PASS

- [ ] **Step 8: 提交**

```bash
git add pyproject.toml uv.lock qbu_crawler/config.py .env.example README.md tests/test_workflows.py
git commit -m "feat: 增加日报PDF运行时基础配置"
```

### Task 2: 扩展 `workflow_runs` 并新增 `review_issue_labels`

**Files:**
- Modify: `qbu_crawler/models.py:28-160,436-548`
- Test: `tests/test_workflows.py`

- [ ] **Step 1: 先写 schema 失败测试**

在 `tests/test_workflows.py` 的 `TestWorkflowModels` 中增加：

```python
def test_workflow_run_artifact_columns_exist(self, workflow_db):
    conn = workflow_db()
    cols = {row[1] for row in conn.execute("PRAGMA table_info(workflow_runs)").fetchall()}
    conn.close()

    assert "analytics_path" in cols
    assert "pdf_path" in cols


def test_review_issue_labels_table_roundtrip(self, workflow_db):
    conn = workflow_db()
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()}
    assert "review_issue_labels" in tables


def test_workflow_run_new_artifact_fields_roundtrip(self, workflow_db):
    run = models.create_workflow_run(
        {
            "workflow_type": "daily",
            "status": "pending",
            "logical_date": "2026-03-29",
            "trigger_key": "daily:2026-03-29:artifacts",
            "analytics_path": "a.json",
            "pdf_path": "b.pdf",
        }
    )
    assert run["analytics_path"] == "a.json"
    assert run["pdf_path"] == "b.pdf"

    updated = models.update_workflow_run(run["id"], analytics_path="c.json", pdf_path="d.pdf")
    assert updated["analytics_path"] == "c.json"
    assert updated["pdf_path"] == "d.pdf"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_workflows.py -k "artifact_columns_exist or review_issue_labels_table_roundtrip or workflow_run_new_artifact_fields_roundtrip" -v`

Expected:
- FAIL，提示列/表不存在

- [ ] **Step 3: 在 `models.init_db()` 增加新表和字段**

`workflow_runs` 新增：
- `analytics_path`
- `pdf_path`

新增表：

```sql
CREATE TABLE IF NOT EXISTS review_issue_labels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id INTEGER NOT NULL,
    label_code TEXT NOT NULL,
    label_polarity TEXT NOT NULL,
    severity TEXT NOT NULL,
    confidence REAL NOT NULL,
    source TEXT NOT NULL,
    taxonomy_version TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(review_id, label_code, label_polarity),
    FOREIGN KEY (review_id) REFERENCES reviews(id) ON DELETE CASCADE
);
```

旧库迁移项补充：

```sql
ALTER TABLE workflow_runs ADD COLUMN analytics_path TEXT
ALTER TABLE workflow_runs ADD COLUMN pdf_path TEXT
```

- [ ] **Step 4: 扩展 `create_workflow_run()` / `update_workflow_run()` 允许新字段**

把 `analytics_path` 和 `pdf_path` 加入 insert/update allowlist。

- [ ] **Step 5: 增加标签层 helper**

在 `models.py` 增加最小 helper：

```python
def replace_review_issue_labels(review_id: int, labels: list[dict]) -> None
def list_review_issue_labels(review_ids: list[int]) -> dict[int, list[dict]]
```

要求：
- 同一评论先删后插，保证 artifact 可重复生成
- 内部只做 DB 写入，不做业务推断

- [ ] **Step 6: 补一条 roundtrip 行为测试**

在 `tests/test_workflows.py` 继续加：

```python
def test_review_issue_labels_helpers_replace_and_list(self, workflow_db):
    conn = workflow_db()
    conn.execute(
        "INSERT INTO products (url, site, ownership) VALUES ('https://example.com/p/1', 'basspro', 'own')"
    )
    product_id = conn.execute("SELECT id FROM products").fetchone()[0]
    conn.execute(
        "INSERT INTO reviews (product_id, author, headline, body, body_hash) VALUES (?, 'a', 'h', 'b', 'hash')",
        (product_id,),
    )
    review_id = conn.execute("SELECT id FROM reviews").fetchone()[0]
    conn.commit()
    conn.close()

    models.replace_review_issue_labels(review_id, [
        {"label_code": "quality_stability", "label_polarity": "negative", "severity": "high",
         "confidence": 0.9, "source": "rule", "taxonomy_version": "v1"},
    ])
    labels = models.list_review_issue_labels([review_id])
    assert labels[review_id][0]["label_code"] == "quality_stability"

    models.replace_review_issue_labels(review_id, [
        {"label_code": "easy_to_use", "label_polarity": "positive", "severity": "low",
         "confidence": 0.7, "source": "rule", "taxonomy_version": "v1"},
    ])
    labels = models.list_review_issue_labels([review_id])
    assert [item["label_code"] for item in labels[review_id]] == ["easy_to_use"]
```

- [ ] **Step 7: 运行测试确认通过**

Run: `uv run pytest tests/test_workflows.py -k "artifact_columns_exist or review_issue_labels or workflow_run_new_artifact_fields_roundtrip" -v`

Expected:
- PASS

- [ ] **Step 8: 提交**

```bash
git add qbu_crawler/models.py tests/test_workflows.py
git commit -m "feat: 增加日报分析产物和标签层存储"
```

### Task 3: 让邮件接口兼容单附件和多附件

**Files:**
- Modify: `qbu_crawler/server/report.py:305-360`
- Modify: `tests/test_report.py`
- Modify: `tests/test_filtered_reports.py`

- [ ] **Step 1: 先写失败测试**

在 `tests/test_report.py` 增加：

```python
def test_send_email_supports_multiple_attachments(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(config, "SMTP_PORT", 587)
    monkeypatch.setattr(config, "SMTP_USE_SSL", False)

    first = tmp_path / "a.xlsx"
    second = tmp_path / "b.pdf"
    first.write_text("a", encoding="utf-8")
    second.write_text("b", encoding="utf-8")

    mock_smtp_instance = MagicMock()

    with patch("smtplib.SMTP", return_value=mock_smtp_instance):
        from qbu_crawler.server.report import send_email
        result = send_email(
            recipients=["r@example.com"],
            subject="Test",
            body_text="Body",
            attachment_paths=[str(first), str(second)],
        )

    assert result["success"] is True
    raw_message = mock_smtp_instance.sendmail.call_args.args[2]
    assert 'filename="a.xlsx"' in raw_message
    assert 'filename="b.pdf"' in raw_message


def test_send_email_attachment_path_still_works(monkeypatch, tmp_path):
    ...
    result = send_email(..., attachment_path=str(tmp_path / "legacy.xlsx"))
    raw_message = mock_smtp_instance.sendmail.call_args.args[2]
    assert 'filename="legacy.xlsx"' in raw_message
```

在 `tests/test_filtered_reports.py` 保留旧调用方式，增加一条兼容断言：

```python
assert captured["attachment_path"] == str(excel_path)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_report.py::test_send_email_supports_multiple_attachments tests/test_filtered_reports.py::test_send_filtered_report_reuses_legacy_email_contract -v`

Expected:
- 第一个 FAIL，提示 `send_email()` 不接受 `attachment_paths`
- 第二个仍 PASS，作为兼容基线

- [ ] **Step 3: 最小改动实现多附件**

把 `send_email()` 改成：

```python
def send_email(..., attachment_path: str | None = None, attachment_paths: list[str] | None = None):
    paths = [path for path in (attachment_paths or []) if path]
    if attachment_path:
        paths.insert(0, attachment_path)
```

要求：
- 旧调用只传 `attachment_path` 时行为不变
- 过滤报告无需改调用点
- 返回值结构保持不变

- [ ] **Step 4: 处理 MIME 附件循环**

每个路径都要：
- 读取文件
- 附加正确文件名
- 不因 PDF 新增而改动 subject/body 模板

- [ ] **Step 5: 运行回归测试**

Run: `uv run pytest tests/test_report.py tests/test_filtered_reports.py -k "send_email or legacy_email_contract" -v`

Expected:
- PASS，且 legacy 相关断言不变

- [ ] **Step 6: 提交**

```bash
git add qbu_crawler/server/report.py tests/test_report.py tests/test_filtered_reports.py
git commit -m "feat: 支持日报多附件邮件发送"
```

---

## Chunk 2: analytics 层与标签分类

### Task 4: 新建 analytics 模块并先跑通规则分类与模式判定

**Files:**
- Create: `qbu_crawler/server/report_analytics.py`
- Create: `tests/test_report_analytics.py`
- Modify: `tests/test_metric_semantics.py`

- [ ] **Step 1: 先写 analytics 失败测试**

创建 `tests/test_report_analytics.py`，先覆盖 4 个核心行为：

```python
def test_build_report_analytics_uses_baseline_mode_without_prior_runs(...):
    ...
    assert analytics["mode"] == "baseline"


def test_build_report_analytics_uses_incremental_mode_with_prior_runs(...):
    ...
    assert analytics["mode"] == "incremental"


def test_self_products_focus_on_negative_clusters(...):
    ...
    assert analytics["self"]["top_negative_clusters"][0]["label_code"] == "quality_stability"


def test_competitor_focus_on_positive_themes(...):
    ...
    assert analytics["competitor"]["top_positive_themes"][0]["label_code"] == "easy_to_use"
```

在 `tests/test_metric_semantics.py` 增加一条语义测试：

```python
def test_report_analytics_keeps_ingested_and_site_total_separate(metric_db):
    ...
    assert analytics["kpis"]["ingested_review_rows"] == 2
    assert analytics["kpis"]["site_reported_review_total_current"] == 10
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_report_analytics.py tests/test_metric_semantics.py -k "report_analytics or baseline_mode or site_total" -v`

Expected:
- FAIL，提示模块不存在

- [ ] **Step 3: 在 `report_analytics.py` 固化一期 taxonomy**

文件顶部先写常量：

```python
NEGATIVE_LABELS = (
    "quality_stability",
    "structure_design",
    "assembly_installation",
    "material_finish",
    "cleaning_maintenance",
    "noise_power",
    "packaging_shipping",
    "service_fulfillment",
)

POSITIVE_LABELS = (
    "easy_to_use",
    "solid_build",
    "good_value",
    "easy_to_clean",
    "strong_performance",
    "good_packaging",
)
```

并定义稳定版本：

```python
TAXONOMY_VERSION = "v1"
```

- [ ] **Step 4: 实现规则分类器**

最小 public API：

```python
def classify_review_labels(review: dict) -> list[dict]
def build_report_analytics(snapshot: dict) -> dict
```

规则要求：
- 自有产品优先提取负向标签
- 竞品优先提取正向标签
- 允许一条评论命中多个标签
- 没命中时返回空列表，不伪造标签

每个标签 dict 必须显式包含：

```python
{
    "label_code": "...",
    "label_polarity": "negative" | "positive",
    "severity": "low" | "medium" | "high",
    "confidence": 0.0,
    "source": "rule",
    "taxonomy_version": TAXONOMY_VERSION,
}
```

一期先用关键词/短语规则，不引入 embedding。

- [ ] **Step 5: 实现首日/增量模式判定**

同模块内提供：

```python
def detect_report_mode(run_id: int, logical_date: str) -> dict
```

判定规则：
- 历史上没有已完成且带 `analytics_path` 的 daily run -> `baseline`
- 最近 30 天可用历史 run 少于 3 个 -> `baseline`
- 否则 -> `incremental`

返回值至少包含：
- `mode`
- `baseline_run_ids`
- `baseline_sample_days`

- [ ] **Step 6: 实现 analytics 输出结构**

`build_report_analytics(snapshot)` 至少输出：

```python
{
    "run_id": ...,
    "logical_date": ...,
    "snapshot_hash": ...,
    "mode": "baseline" | "incremental",
    "taxonomy_version": "v1",
    "label_mode": "rule" | "hybrid",
    "generated_at": "...",
    "metric_semantics": {
        "ingested_review_rows": "reviews 实际入库行数",
        "site_reported_review_total_current": "products.review_count 当前站点展示总评论数",
    },
    "kpis": {...},
    "self": {
        "risk_products": [...],
        "top_negative_clusters": [...],
        "recommendations": [...],
    },
    "competitor": {
        "top_positive_themes": [...],
        "benchmark_examples": [...],
        "negative_opportunities": [...],
    },
    "appendix": {
        "image_reviews": [...],
        "coverage": {...},
    },
}
```

注意：
- `kpis` 里明确拆开 `ingested_review_rows` 和 `site_reported_review_total_current`
- 推荐动作只能写“可能原因边界 + 改良方向”，不能写工程根因结论

- [ ] **Step 7: 运行测试确认通过**

Run: `uv run pytest tests/test_report_analytics.py tests/test_metric_semantics.py -v`

Expected:
- PASS

- [ ] **Step 8: 提交**

```bash
git add qbu_crawler/server/report_analytics.py tests/test_report_analytics.py tests/test_metric_semantics.py
git commit -m "feat: 增加日报分析层和问题簇计算"
```

### Task 5: 把标签落库，并加可选 hybrid 归一化入口

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py`
- Modify: `qbu_crawler/models.py`
- Modify: `tests/test_report_analytics.py`

- [ ] **Step 1: 先写失败测试**

在 `tests/test_report_analytics.py` 增加：

```python
def test_sync_review_labels_persists_rule_labels(...):
    ...
    assert stored[review_id][0]["source"] == "rule"


def test_hybrid_label_mode_can_replace_source_with_llm(monkeypatch, ...):
    monkeypatch.setattr(config, "REPORT_LABEL_MODE", "hybrid")
    ...
    assert stored[review_id][0]["source"] == "llm"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_report_analytics.py -k "sync_review_labels or hybrid_label_mode" -v`

Expected:
- FAIL，提示函数缺失

- [ ] **Step 3: 增加标签同步入口**

在 `report_analytics.py` 实现：

```python
def sync_review_labels(snapshot: dict) -> dict[int, list[dict]]
```

要求：
- 遍历 snapshot 中所有 review
- 规则结果先写 `source="rule"`
- 调用 `models.replace_review_issue_labels(...)`
- 再读回 `models.list_review_issue_labels(...)`

- [ ] **Step 4: 增加 hybrid 模式的可选归一化**

只在 `REPORT_LABEL_MODE == "hybrid"` 时调用 `_maybe_normalize_labels_with_llm()`。

要求：
- 没配置 LLM 凭证时直接跳过，不报错
- 测试里通过 monkeypatch 假造返回，不做真实网络请求
- 归一化只允许修正已有候选标签，不允许生成 taxonomy 之外的新 code
- 只允许处理代表性样本，单次 run 上限 20 条评论，优先取：
  - 自有产品高风险负向评论
  - 竞品高价值正向评论
- 归一化结果必须回写 `review_issue_labels`，不能只算不存

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/test_report_analytics.py -k "sync_review_labels or hybrid_label_mode" -v`

Expected:
- PASS

- [ ] **Step 6: 提交**

```bash
git add qbu_crawler/server/report_analytics.py qbu_crawler/models.py tests/test_report_analytics.py
git commit -m "feat: 持久化日报标签并预留混合归一化"
```

---

## Chunk 3: PDF 渲染、图表与版式

### Task 6: 先做模板渲染和 SVG 图表资产

**Files:**
- Create: `qbu_crawler/server/report_pdf.py`
- Create: `qbu_crawler/server/report_templates/daily_report.html.j2`
- Create: `qbu_crawler/server/report_templates/daily_report.css`
- Create: `tests/test_report_pdf.py`

- [ ] **Step 1: 先写失败测试**

在 `tests/test_report_pdf.py` 先写两条：

```python
def test_render_report_html_contains_required_sections(tmp_path):
    ...
    assert "自有产品差评总览" in html
    assert "竞品好评 benchmark" in html


def test_build_chart_assets_outputs_svg_files(tmp_path):
    ...
    assert all(path.suffix == ".svg" for path in chart_paths)


def test_render_report_html_uses_only_local_assets(tmp_path):
    ...
    assert "https://" not in html
    assert "http://" not in html
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_report_pdf.py -k "render_report_html or build_chart_assets" -v`

Expected:
- FAIL，提示模块不存在

- [ ] **Step 3: 实现模板渲染入口**

在 `report_pdf.py` 先实现：

```python
def render_report_html(snapshot: dict, analytics: dict, asset_dir: str) -> str
def build_chart_assets(analytics: dict, output_dir: str) -> dict[str, str]
def write_report_html_preview(snapshot: dict, analytics: dict, output_path: str) -> str
```

要求：
- 模板只吃 `snapshot + analytics + chart_paths`
- 图表一律生成本地 SVG
- HTML 中引用本地 CSS 和本地 SVG 路径
- `build_chart_assets()` 的 key 写死为：
  - `self_risk_products`
  - `self_negative_clusters`
  - `competitor_positive_themes`
  - `coverage_summary`

- [ ] **Step 4: 在模板中固定章节结构**

模板必须包含：
- 执行摘要
- 自有产品差评总览
- 自有产品问题簇深挖
- 改良建议与优先级
- 竞品好评 benchmark
- 竞品差评与机会窗口
- 附录与口径

不要在模板里写复杂 Python 逻辑，所有分组和排序都由 `report_analytics.py` 提前完成。

- [ ] **Step 5: 在 CSS 中固定 print 规则**

`daily_report.css` 要写死：

```css
@page {
  size: A4;
  margin: 14mm 12mm 16mm 12mm;
}
```

并明确：
- `body { font-family: var(--report-font-family); }`
- 图表卡片和表格不要跨页乱切
- 标题不能单独落在页尾
- 只用一套中性色 + 一套强调色

- [ ] **Step 6: 运行测试确认通过**

Run: `uv run pytest tests/test_report_pdf.py -k "render_report_html or build_chart_assets" -v`

Expected:
- PASS

- [ ] **Step 6a: 增加 HTML 预览烟测**

Run: `uv run python -c "from pathlib import Path; import tempfile; from qbu_crawler.server.report_pdf import write_report_html_preview; out = Path(tempfile.gettempdir()) / 'daily-report-preview.html'; result = write_report_html_preview({'run_id': 1, 'logical_date': '2026-04-02', 'snapshot_hash': 'hash'}, {'mode': 'baseline', 'kpis': {}, 'self': {}, 'competitor': {}, 'appendix': {}}, str(out)); print(Path(result).is_file())"`

Expected:
- 输出 `True`
- 后续实现阶段可直接用 `snapshot + analytics` 生成本地 HTML 预览再人工确认版式

- [ ] **Step 7: 提交**

```bash
git add qbu_crawler/server/report_pdf.py qbu_crawler/server/report_templates/daily_report.html.j2 qbu_crawler/server/report_templates/daily_report.css tests/test_report_pdf.py
git commit -m "feat: 增加日报PDF模板和图表资产生成"
```

### Task 7: 用 Playwright 导出 PDF，并把兼容性约束写进文档

**Files:**
- Modify: `qbu_crawler/server/report_pdf.py`
- Modify: `tests/test_report_pdf.py`
- Modify: `README.md`
- Modify: `AGENTS.md`

- [ ] **Step 1: 先写失败测试**

在 `tests/test_report_pdf.py` 增加：

```python
def test_generate_pdf_uses_playwright_print_contract(monkeypatch, tmp_path):
    calls = {}
    ...
    assert calls["pdf"]["format"] == "A4"
    assert calls["pdf"]["print_background"] is True
    assert calls["pdf"]["prefer_css_page_size"] is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_report_pdf.py::test_generate_pdf_uses_playwright_print_contract -v`

Expected:
- FAIL，提示 `generate_pdf_report()` 不存在

- [ ] **Step 3: 实现 Playwright PDF 导出**

在 `report_pdf.py` 增加：

```python
def generate_pdf_report(snapshot: dict, analytics: dict, output_path: str) -> str
```

调用要求：

```python
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.set_content(html, wait_until="load")
    page.emulate_media(media="print")
    page.pdf(
        path=output_path,
        format="A4",
        print_background=True,
        prefer_css_page_size=True,
    )
```

注意：
- 不允许依赖在线资源
- PDF 文件名固定到 run 维度，避免重复生成覆盖错误 artifact

- [ ] **Step 4: 在 `README.md` 与 `AGENTS.md` 写兼容性要求**

必须同步：
- `uv run playwright install chromium`
- Linux 服务器要安装统一中文字体
- PDF 渲染失败属于系统边界错误，`report_pdf.py` 直接抛错；workflow 层必须把 run 状态改成 `needs_attention`，不是 `completed`，同时只把 `report_phase` 回退到 `fast_sent`

- [ ] **Step 5: 运行测试**

Run: `uv run pytest tests/test_report_pdf.py -v`

Expected:
- PASS

- [ ] **Step 6: 本地做一次非测试烟测**

Run: `uv run python -c "from qbu_crawler.server import report_pdf; print(hasattr(report_pdf, 'generate_pdf_report'))"`

Expected:
- 输出 `True`

- [ ] **Step 7: 提交**

```bash
git add qbu_crawler/server/report_pdf.py tests/test_report_pdf.py README.md AGENTS.md
git commit -m "feat: 接入Playwright导出日报PDF"
```

---

## Chunk 4: snapshot/workflow 集成与总回归

### Task 8: 在 `report_snapshot` 中生成 analytics JSON 和 PDF

**Files:**
- Modify: `qbu_crawler/server/report_snapshot.py:15-136`
- Modify: `tests/test_report_snapshot.py`

- [ ] **Step 1: 先写失败测试**

在 `tests/test_report_snapshot.py` 增加：

```python
def test_generate_full_report_from_snapshot_returns_analytics_and_pdf_paths(tmp_path, monkeypatch):
    ...
    assert result["analytics_path"].endswith(".json")
    assert result["pdf_path"].endswith(".pdf")


def test_generate_full_report_from_snapshot_sends_excel_and_pdf(monkeypatch, tmp_path):
    ...
    assert captured["attachment_paths"] == [str(excel_path), str(pdf_path)]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_report_snapshot.py -k "analytics_and_pdf_paths or sends_excel_and_pdf" -v`

Expected:
- FAIL，提示返回结构或邮件参数不匹配

- [ ] **Step 3: 在 `report_snapshot.py` 增加 analytics artifact 生成**

建议新增私有流程：

```python
analytics = report_analytics.build_report_analytics(snapshot)
analytics_path = os.path.join(config.REPORT_DIR, f"workflow-run-{run_id}-analytics-{logical_date}.json")
```

写文件时要求：
- `ensure_ascii=False`
- `sort_keys=True`
- `indent=2`

- [ ] **Step 4: 接 Excel 和 PDF 生成**

full report 顺序固定：
1. build analytics
2. save analytics JSON
3. generate Excel
4. generate PDF
5. send email

如果步骤 4 失败，但步骤 2/3 已成功，必须抛出带 partial artifact 的异常，例如：

```python
class FullReportGenerationError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        analytics_path: str | None = None,
        excel_path: str | None = None,
        pdf_path: str | None = None,
    ):
        ...
```

返回值扩展为：

```python
{
    ...,
    "excel_path": excel_path,
    "analytics_path": analytics_path,
    "pdf_path": pdf_path,
    "email": email_result,
}
```

- [ ] **Step 5: 保持 legacy subject/body 完全不变**

邮件正文不改，只改附件列表。`build_legacy_report_email()` 不动。

- [ ] **Step 6: 运行测试确认通过**

Run: `uv run pytest tests/test_report_snapshot.py -v`

Expected:
- PASS

- [ ] **Step 7: 提交**

```bash
git add qbu_crawler/server/report_snapshot.py tests/test_report_snapshot.py
git commit -m "feat: 在快照报告中生成分析JSON和PDF"
```

### Task 9: 在 `WorkflowWorker` 持久化新 artifact 并扩展通知 payload

**Files:**
- Modify: `qbu_crawler/server/workflows.py:553-650`
- Modify: `tests/test_workflows.py`

- [ ] **Step 1: 先写失败测试**

在 `tests/test_workflows.py::TestWorkflowReconcile` 增加/修改：

```python
assert refreshed["analytics_path"] == str(tmp_path / "analytics.json")
assert refreshed["pdf_path"] == str(tmp_path / "full.pdf")
assert full_report["payload"]["pdf_path"] == str(tmp_path / "full.pdf")
assert full_report["payload"]["analytics_path"] == str(tmp_path / "analytics.json")
```

并补一条失败回退测试：

```python
def test_pdf_generation_failure_keeps_run_at_fast_sent(...):
    ...
    assert refreshed["report_phase"] == "fast_sent"
    assert refreshed["status"] == "needs_attention"
    assert refreshed["analytics_path"] == str(tmp_path / "analytics.json")
    assert refreshed["excel_path"] == str(tmp_path / "full.xlsx")


def test_smtp_failure_keeps_generated_pdf_artifact(...):
    ...
    assert refreshed["status"] == "needs_attention"
    assert refreshed["pdf_path"] == str(tmp_path / "full.pdf")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_workflows.py -k "full_sent or pdf_generation_failure or smtp_failure" -v`

Expected:
- FAIL，提示新字段/新 payload 缺失

- [ ] **Step 3: 修改 `workflows.py` 的 full_pending 分支**

在 `_advance_run()` 中：
- 接收 `full_report["analytics_path"]`
- 接收 `full_report["pdf_path"]`
- 在 `workflow_full_report` payload 中追加 `pdf_path` 和 `analytics_path`
- `models.update_workflow_run()` 一次性写入 `excel_path`、`analytics_path`、`pdf_path`

- [ ] **Step 4: 保持失败回退语义**

如果 analytics/PDF/SMTP 任一步抛异常：
- run 进入 `needs_attention`
- `report_phase` 回退到 `fast_sent`
- 已有 snapshot 保持不变
- 如果异常携带 partial artifact，优先保留并写入所有已成功生成的路径：`analytics_path`、`excel_path`、`pdf_path`

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/test_workflows.py -k "reconcile_advances_reporting_run_to_full_sent or pdf_generation_failure or smtp_failure" -v`

Expected:
- PASS

- [ ] **Step 6: 提交**

```bash
git add qbu_crawler/server/workflows.py tests/test_workflows.py
git commit -m "feat: 持久化日报分析和PDF产物"
```

### Task 10: 文档同步与全量回归

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `.env.example`
- Verify: `docs/superpowers/specs/2026-04-02-daily-pdf-report-design.md`

- [ ] **Step 1: 对照 spec 做实现后核对**

核对这 6 点是否都已经落地：
- `Excel + PDF` 双附件
- 自有差评/问题簇/改良建议主轴
- 竞品好评 benchmark 主轴
- 首日 baseline / 后续 incremental 双模式
- `review_issue_labels` 正负标签层
- `analytics_path/pdf_path` 持久化
- `report_analytics.py` 只负责分析与标签、`report_pdf.py` 只负责模板/图表/导出，`report_snapshot.py` 不吞分析和渲染细节

- [ ] **Step 2: 运行完整回归**

Run:

```bash
uv run pytest \
  tests/test_report.py \
  tests/test_filtered_reports.py \
  tests/test_report_snapshot.py \
  tests/test_report_analytics.py \
  tests/test_report_pdf.py \
  tests/test_workflows.py \
  tests/test_metric_semantics.py -v
```

Expected:
- 全绿

- [ ] **Step 3: 运行 lint**

Run: `uv run ruff check qbu_crawler tests`

Expected:
- 无新告警

- [ ] **Step 4: 检查工作区只包含预期文件**

Run: `git status --short`

Expected:
- 只看到本计划涉及的代码、测试、文档改动
- 不要误覆盖用户已有脏改动

- [ ] **Step 5: 最终提交**

```bash
git add README.md AGENTS.md .env.example qbu_crawler tests
git commit -m "feat: 完成每日深度PDF报告链路"
```

---

## 执行备注

- 实施时必须使用 `@superpowers:subagent-driven-development`，按 task 粒度派发，不要把整个计划一次性交给一个 worker。
- 每个 task 完成后都先跑该 task 的局部测试，再进入下一 task。
- 不要在实现阶段顺手改 legacy Excel 模板、邮件文案或 filtered report 业务逻辑；这些都不在本计划范围内。
- 如果 Playwright 或字体在部署机缺失，按系统边界错误处理，保留 `snapshot + analytics + excel`，并让 workflow 进入 `needs_attention`，不要静默降级为“报告成功”。
