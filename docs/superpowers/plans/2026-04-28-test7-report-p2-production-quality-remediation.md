# 测试7报告 P2 生产质量治理 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将测试7报告从 P1 的语义契约治理推进到生产质量治理，固定 LLM 输出结构，增加 contract validation、浏览器 replay 和产物/交付 manifest。

**Architecture:** 继续以 `report_user_contract` 为展示唯一语义入口；新增 executive slot、contract validator 和 report manifest 读取层；渲染层增加 contract-only guard；测试7 replay 从字符串断言升级为浏览器行为验收。

**Tech Stack:** Python 3.10+, pytest, Jinja2, openpyxl, Playwright, SQLite, existing report snapshot / report_artifacts / workflow / notification_outbox pipeline.

---

## Entry Context

- 设计文档：`docs/superpowers/specs/2026-04-28-test7-report-p2-production-quality-design.md`
- 审计文档：`docs/reviews/2026-04-28-production-test7-report-root-cause-and-remediation.md`
- P1 devlog：`docs/devlogs/D022-test7-report-p1-contract-governance.md`
- P2 原则：
  - LLM 只改写固定 slot 文案。
  - 代码决定事实、数量、证据和产品集合。
  - 浏览器 replay 只验证关键路径，不做视觉改版。
  - 不新增 DB migration。
  - 不删除旧 fallback，只增加 guard 和迁移清单。

---

## File Map

| File | Responsibility | Tasks |
|---|---|---|
| `qbu_crawler/server/report_contract.py` | executive slots、slot merge、contract validation | T1, T2 |
| `qbu_crawler/server/report_llm.py` | slot rewrite prompt、slot 输出解析与校验 | T1 |
| `qbu_crawler/server/report_common.py` | 保持 normalized analytics 挂载 P2 contract 字段 | T1, T2 |
| `qbu_crawler/server/report_html.py` | replay 渲染入口和 contract-only guard | T3, T4 |
| `qbu_crawler/server/report.py` | Excel / 邮件 contract-only guard | T3 |
| `qbu_crawler/server/report_manifest.py` | 汇总 artifacts、workflow run、outbox delivery | T5 |
| `tests/server/test_report_contract_slots.py` | executive slot 和 LLM slot merge 测试 | T1 |
| `tests/server/test_report_contract_validation.py` | contract validation 测试 | T2 |
| `tests/server/test_report_contract_renderers.py` | contract-only 渲染守卫补强 | T3 |
| `tests/server/test_test7_artifact_replay_browser.py` | Playwright replay 浏览器验收 | T4 |
| `tests/server/test_report_manifest.py` | manifest 读取层测试 | T5 |
| `docs/devlogs/D023-test7-report-p2-production-quality.md` | P2 实施记录 | T6 |

---

## Chunk 1: Executive Slot

### Task 1: 固定 executive slots，LLM 只改写 slot 文案

**Files:**
- Modify: `qbu_crawler/server/report_contract.py`
- Modify: `qbu_crawler/server/report_llm.py`
- Test: `tests/server/test_report_contract_slots.py`

- [ ] **Step 1.1: 写失败测试：contract 生成固定 executive slots**

Create `tests/server/test_report_contract_slots.py`:

```python
from qbu_crawler.server.report_contract import build_report_user_contract


def test_contract_builds_stable_executive_slots():
    analytics = {
        "report_semantics": "bootstrap",
        "kpis": {
            "product_count": 8,
            "ingested_review_rows": 561,
            "coverage_rate": 0.6375,
            "translation_completion_rate": 1.0,
            "own_negative_review_rate": 0.024,
            "health_index": 96.2,
            "attention_product_count": 0,
        },
        "self": {"top_negative_clusters": []},
    }

    contract = build_report_user_contract(
        snapshot={"logical_date": "2026-04-28", "products": [{}] * 8, "reviews": [{}] * 561},
        analytics=analytics,
    )

    slot_ids = [slot["slot_id"] for slot in contract["executive_slots"]]
    assert slot_ids == [
        "coverage_snapshot",
        "translation_quality",
        "own_product_health",
        "negative_feedback",
        "action_focus",
    ]
    assert len(contract["executive_bullets"]) <= 5
    assert all(slot["default_text"] for slot in contract["executive_slots"])
```

- [ ] **Step 1.2: 运行测试确认失败**

Run:

```bash
uv run --frozen --with pytest pytest tests/server/test_report_contract_slots.py::test_contract_builds_stable_executive_slots -q
```

Expected: FAIL，`executive_slots` 尚不存在。

- [ ] **Step 1.3: 实现 deterministic slots**

在 `report_contract.py` 中新增：

```python
def _build_executive_slots(snapshot, analytics, kpis, issue_diagnostics):
    return [...]
```

要求：
- 固定 5 个 slot。
- 每个 slot 有 `slot_id`、`slot_type`、`locked_facts`、`default_text`、`source`、`confidence`。
- `executive_bullets` 从 slot 派生，最多 5 条。

- [ ] **Step 1.4: 写失败测试：LLM 不能新增未知 slot**

```python
from qbu_crawler.server.report_contract import merge_llm_slot_rewrites


def test_llm_slot_rewrite_rejects_unknown_slot():
    contract = {
        "executive_slots": [
            {"slot_id": "coverage_snapshot", "default_text": "覆盖 8 个产品", "locked_facts": {"product_count": 8}},
        ],
        "validation_warnings": [],
    }
    llm_copy = {
        "executive_slot_rewrites": [
            {"slot_id": "unknown_slot", "text": "编造的额外结论"},
        ]
    }

    merged = merge_llm_slot_rewrites(contract, llm_copy)

    assert merged["executive_slots"][0].get("llm_text", "") == ""
    assert merged["executive_bullets"] == ["覆盖 8 个产品"]
    assert merged["validation_warnings"]
```

- [ ] **Step 1.5: 写失败测试：LLM 文案数字漂移时使用 default_text**

```python
def test_llm_slot_rewrite_keeps_default_text_on_fact_drift():
    contract = {
        "executive_slots": [
            {"slot_id": "coverage_snapshot", "default_text": "覆盖 8 个产品", "locked_facts": {"product_count": 8}},
        ],
        "validation_warnings": [],
    }
    llm_copy = {
        "executive_slot_rewrites": [
            {"slot_id": "coverage_snapshot", "text": "本次覆盖 9 个产品"},
        ]
    }

    merged = merge_llm_slot_rewrites(contract, llm_copy)

    assert merged["executive_bullets"] == ["覆盖 8 个产品"]
    assert "fact drift" in " ".join(merged["validation_warnings"])
```

- [ ] **Step 1.6: 实现 `merge_llm_slot_rewrites()`**

规则：
- 只接受已存在 `slot_id`。
- 文案中的数字必须能在 `locked_facts` 中找到。
- 非法 rewrite 不进入用户可见 bullet。
- 合法 rewrite 写入 `slot["llm_text"]`。

- [ ] **Step 1.7: 改造 v3 prompt 为 slot rewrite**

在 `report_llm.py` 新增 `_build_slot_rewrite_payload()` 和 `_build_slot_rewrite_prompt()`。

输出 schema：

```json
{
  "executive_slot_rewrites": [
    {"slot_id": "coverage_snapshot", "text": "..."}
  ],
  "improvement_priorities": []
}
```

保留旧 `normalize_llm_copy_shape()` 作为兼容 fallback，但主路径优先 slot rewrite。

- [ ] **Step 1.8: 运行 slot 测试**

Run:

```bash
uv run --frozen --with pytest pytest tests/server/test_report_contract_slots.py tests/server/test_report_contract_llm.py -q
```

Expected: PASS。

---

## Chunk 2: Contract Validation

### Task 2: 增加 contract validation，发现证据和交付状态矛盾

**Files:**
- Modify: `qbu_crawler/server/report_contract.py`
- Test: `tests/server/test_report_contract_validation.py`

- [ ] **Step 2.1: 写失败测试：无证据 action 被标记**

```python
from qbu_crawler.server.report_contract import validate_report_user_contract


def test_validate_contract_flags_action_without_evidence():
    contract = {
        "action_priorities": [{
            "label_code": "structure_design",
            "source": "llm_rewrite",
            "full_action": "复核结构",
            "evidence_review_ids": [],
            "top_complaint": "",
        }],
        "issue_diagnostics": [],
        "heatmap": {},
        "competitor_insights": {},
        "delivery": {},
        "executive_slots": [],
    }

    warnings = validate_report_user_contract(contract)

    assert any("action without evidence" in item for item in warnings)
```

- [ ] **Step 2.2: 写失败测试：heatmap 缺完整产品名被标记**

```python
def test_validate_contract_flags_heatmap_cell_without_drilldown_product():
    contract = {
        "action_priorities": [],
        "issue_diagnostics": [],
        "heatmap": {
            "x_labels": ["结构设计"],
            "y_items": [{"display_label": "Short"}],
            "z": [[{"score": 0.5, "sample_size": 3, "tooltip": "体验健康度 50%"}]],
        },
        "competitor_insights": {},
        "delivery": {},
        "executive_slots": [],
    }

    warnings = validate_report_user_contract(contract)

    assert any("heatmap drilldown product" in item for item in warnings)
```

- [ ] **Step 2.3: 写失败测试：deadletter 不能显示完整送达**

```python
def test_validate_contract_flags_delivery_deadletter_conflict():
    contract = {
        "action_priorities": [],
        "issue_diagnostics": [],
        "heatmap": {},
        "competitor_insights": {},
        "delivery": {
            "workflow_notification_delivered": True,
            "deadletter_count": 2,
            "internal_status": "full_sent",
        },
        "executive_slots": [],
    }

    warnings = validate_report_user_contract(contract)

    assert any("delivery conflict" in item for item in warnings)
```

- [ ] **Step 2.4: 实现 `validate_report_user_contract()`**

要求：
- 返回 `list[str]`。
- 不抛异常，避免报告生成被 validation 阻断。
- `build_report_user_contract()` 调用 validator，并把结果合并进 `validation_warnings`。

- [ ] **Step 2.5: 运行 validation 测试**

Run:

```bash
uv run --frozen --with pytest pytest tests/server/test_report_contract_validation.py tests/server/test_report_contract.py -q
```

Expected: PASS。

---

## Chunk 3: Renderer Guard

### Task 3: 补强 contract-only 渲染守卫

**Files:**
- Modify: `qbu_crawler/server/report_html.py`
- Modify: `qbu_crawler/server/report.py`
- Test: `tests/server/test_report_contract_renderers.py`

- [ ] **Step 3.1: 写失败测试：HTML contract-only 覆盖所有关键区块**

在现有 `_contract()` fixture 基础上增加 `executive_slots`、`bootstrap_digest`、`delivery`，构造 analytics 只包含 `report_user_contract`。

断言：

```python
assert "issue-image-evidence" in html
assert "rec-full-action" in html
assert "热力图" in html
assert "监控起点" in html or "首日基线" in html
```

- [ ] **Step 3.2: 写失败测试：Excel contract-only 不读旧 report_copy**

构造 analytics：

```python
analytics = {"report_user_contract": contract, "report_copy": {"improvement_priorities": []}}
```

断言 “现在该做什么” 和 “竞品启示” sheet 仍有 contract 内容。

- [ ] **Step 3.3: 写失败测试：邮件 contract-only 使用 KPI 和 delivery**

断言邮件里出现 contract 的 `attention_product_count` 和 action title。

- [ ] **Step 3.4: 实现最小 renderer guard**

如果现有逻辑已通过，保持代码不动，只保留测试作为 guard。若失败，只在对应渲染入口补 contract 优先读取，不做模板重构。

- [ ] **Step 3.5: 运行渲染测试**

Run:

```bash
uv run --frozen --with pytest pytest tests/server/test_report_contract_renderers.py tests/server/test_test7_artifact_replay.py -q
```

Expected: PASS。

---

## Chunk 4: Browser Replay

### Task 4: 用 Playwright 验证测试7 HTML 关键路径

**Files:**
- Create: `tests/server/test_test7_artifact_replay_browser.py`
- Modify if needed: `tests/fixtures/report_replay/test7_minimal_snapshot.json`
- Modify if needed: `tests/fixtures/report_replay/test7_minimal_analytics.json`

- [ ] **Step 4.1: 写浏览器测试 skeleton**

Create `tests/server/test_test7_artifact_replay_browser.py`:

```python
import json
from pathlib import Path

from qbu_crawler.server.report_html import render_v3_html

FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "report_replay"


def _load_fixture():
    snapshot = json.loads((FIXTURE_DIR / "test7_minimal_snapshot.json").read_text(encoding="utf-8"))
    analytics = json.loads((FIXTURE_DIR / "test7_minimal_analytics.json").read_text(encoding="utf-8"))
    return snapshot, analytics
```

- [ ] **Step 4.2: 写失败测试：Tab 内容可见**

使用 Playwright 打开 `render_v3_html()` 生成的本地 HTML，逐个点击：

```python
def test_test7_replay_browser_tabs_have_expected_content(tmp_path, page):
    snapshot, analytics = _load_fixture()
    html_path = render_v3_html(snapshot, analytics, output_path=str(tmp_path / "report.html"))
    page.goto(Path(html_path).as_uri())

    for tab_name in ["总览", "今日变化", "问题诊断", "产品排行", "竞品对标", "全景数据"]:
        page.get_by_role("tab", name=tab_name).click()
        assert page.get_by_role("tabpanel").is_visible()

    page.get_by_role("tab", name="问题诊断").click()
    assert page.locator(".issue-image-evidence").count() >= 1
    assert page.locator(".ai-recommendation, .rec-full-action").count() >= 1
```

如果项目没有 pytest Playwright fixture，则用现有 Playwright wrapper 或跳过条件：

```python
pytest.importorskip("playwright.sync_api")
```

- [ ] **Step 4.3: 写失败测试：heatmap 点击筛选全景**

```python
def test_test7_replay_heatmap_click_filters_panorama(tmp_path, page):
    snapshot, analytics = _load_fixture()
    html_path = render_v3_html(snapshot, analytics, output_path=str(tmp_path / "report.html"))
    page.goto(Path(html_path).as_uri())

    page.locator(".heatmap-cell[data-product]").first.click()
    product_value = page.locator("#panoramaProductFilter").input_value()
    assert "Walton" in product_value
```

根据实际 select id 调整测试，但必须验证完整产品名命中。

- [ ] **Step 4.4: 写失败测试：近 30 天筛选与 KPI 一致**

在浏览器中触发近 30 天筛选，断言可见行数等于 fixture 中 contract/KPI 的近 30 天数量。

- [ ] **Step 4.5: 实现缺口**

只修浏览器测试暴露的实际交互缺口：
- tab role 不可访问时补 role/aria。
- heatmap click 没有完整产品名时改 data-product。
- recent filter 选择器不稳定时补稳定 id。

- [ ] **Step 4.6: 运行 browser replay**

Run:

```bash
uv run --frozen --with pytest pytest tests/server/test_test7_artifact_replay_browser.py -q
```

Expected: PASS 或在缺少 Playwright 依赖时 skip，不能 error。

---

## Chunk 5: Report Manifest

### Task 5: 增加 report manifest 读取层

**Files:**
- Create: `qbu_crawler/server/report_manifest.py`
- Test: `tests/server/test_report_manifest.py`

- [ ] **Step 5.1: 写失败测试：manifest 区分 artifacts 和 delivery**

Create `tests/server/test_report_manifest.py`:

```python
import json
import sqlite3

from qbu_crawler.server.report_manifest import build_report_manifest


def test_report_manifest_separates_artifacts_and_delivery(tmp_path):
    db = tmp_path / "test.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
    CREATE TABLE workflow_runs (
        id INTEGER PRIMARY KEY,
        logical_date TEXT,
        status TEXT,
        report_phase TEXT
    );
    CREATE TABLE report_artifacts (
        id INTEGER PRIMARY KEY,
        run_id INTEGER,
        artifact_type TEXT,
        path TEXT,
        bytes INTEGER,
        sha256 TEXT,
        template_version TEXT
    );
    CREATE TABLE notification_outbox (
        id INTEGER PRIMARY KEY,
        status TEXT,
        payload TEXT
    );
    """)
    conn.execute(
        "INSERT INTO workflow_runs (id, logical_date, status, report_phase) VALUES (1, '2026-04-28', 'completed', 'full_sent_local')"
    )
    conn.execute(
        "INSERT INTO report_artifacts (run_id, artifact_type, path, bytes, sha256, template_version) VALUES (1, 'html_attachment', 'r.html', 10, 'abc', 'v')"
    )
    conn.execute(
        "INSERT INTO notification_outbox (status, payload) VALUES ('deadletter', ?)",
        (json.dumps({"run_id": 1, "kind": "workflow"}),),
    )
    conn.commit()

    manifest = build_report_manifest(conn, run_id=1)

    assert manifest["generation"]["status"] == "generated"
    assert manifest["generation"]["artifacts"][0]["artifact_type"] == "html_attachment"
    assert manifest["delivery"]["workflow_notification_delivered"] is False
    assert manifest["delivery"]["deadletter_count"] == 1
    assert manifest["delivery"]["internal_status"] == "full_sent_local"
```

- [ ] **Step 5.2: 实现 `report_manifest.py`**

要求：
- 接收 sqlite connection 和 `run_id`。
- 查询 `workflow_runs`。
- 查询 `report_artifacts`。
- 查询 `notification_outbox` deadletter，匹配 payload 中 `run_id`。
- 输出纯 dict，不依赖 FastAPI。
- 表不存在时返回 warning，不抛出到调用者。

- [ ] **Step 5.3: 写测试：表缺失时 manifest 可降级**

```python
def test_report_manifest_handles_missing_artifacts_table(tmp_path):
    ...
    assert manifest["warnings"]
```

- [ ] **Step 5.4: 运行 manifest 测试**

Run:

```bash
uv run --frozen --with pytest pytest tests/server/test_report_manifest.py tests/server/test_report_artifacts.py tests/server/test_internal_ops_alert.py -q
```

Expected: PASS。

---

## Chunk 6: 收口文档和回归

### Task 6: 文档、回归和提交

**Files:**
- Create: `docs/devlogs/D023-test7-report-p2-production-quality.md`
- Optional modify: `AGENTS.md` only if P2 新增长期规则。

- [ ] **Step 6.1: 新增 devlog**

记录：
- executive slots 设计和 LLM 约束。
- contract validation 覆盖范围。
- 浏览器 replay 覆盖路径。
- manifest 输出字段。
- P3 剩余项。

- [ ] **Step 6.2: 运行 P2 定向回归**

Run:

```bash
uv run --frozen --with pytest pytest ^
  tests/server/test_report_contract_slots.py ^
  tests/server/test_report_contract_validation.py ^
  tests/server/test_report_contract_llm.py ^
  tests/server/test_report_contract_renderers.py ^
  tests/server/test_test7_artifact_replay.py ^
  tests/server/test_test7_artifact_replay_browser.py ^
  tests/server/test_report_manifest.py ^
  -q
```

Expected: PASS，或 browser replay 在缺少 Playwright 时明确 skip。

- [ ] **Step 6.3: 运行报告回归**

Run:

```bash
$files = @((Get-ChildItem tests/server/test_*report*.py).FullName) + @((Get-ChildItem tests/test_*report*.py).FullName) + @('tests/test_v3_html.py','tests/test_v3_excel.py','tests/test_v3_llm.py','tests/test_report_snapshot.py','tests/test_v3_modes.py'); uv run --frozen --with pytest pytest @files -q
```

Expected: PASS 或仅保留已知 skip。

- [ ] **Step 6.4: 检查本次文件 diff**

Run:

```bash
git diff --check -- qbu_crawler/server/report_contract.py qbu_crawler/server/report_llm.py qbu_crawler/server/report_manifest.py tests/server/test_report_contract_slots.py tests/server/test_report_contract_validation.py tests/server/test_test7_artifact_replay_browser.py tests/server/test_report_manifest.py docs/devlogs/D023-test7-report-p2-production-quality.md
```

Expected: 无输出。

- [ ] **Step 6.5: 提交 P2**

只 stage P2 文件，不能混入当前工作区已有无关改动。

```bash
git add qbu_crawler/server/report_contract.py qbu_crawler/server/report_llm.py qbu_crawler/server/report_manifest.py tests/server/test_report_contract_slots.py tests/server/test_report_contract_validation.py tests/server/test_report_contract_renderers.py tests/server/test_test7_artifact_replay_browser.py tests/server/test_report_manifest.py docs/devlogs/D023-test7-report-p2-production-quality.md
git commit -m "修复：测试7 P2 报告生产质量治理"
```

---

## P3 Handoff

P2 完成后再进入 P3。P3 应单独设计和计划，重点是：

- 新增 DB migration，持久化 `report_generation_status`、`delivery_status`、`delivery_last_error`。
- 移除或收紧旧 analytics fallback。
- 为 `report_manifest` 提供内部查询 API 或 MCP tool。
- 建立长期 metric catalog 和跨 run artifact diff。
- 生产环境按 run 归档浏览器截图。

---

## Ready Criteria

执行前确认：

- [ ] P1 hotfix 已提交。
- [ ] 用户接受 P2 只做生产质量治理，不做视觉重设计和 DB migration。
- [ ] 执行者已阅读 P2 设计文档和本计划。
- [ ] 执行者准备使用 `superpowers:executing-plans` 或按 TDD 在当前会话执行。

完成后必须提供：

- 变更摘要。
- 测试命令和结果。
- 新增/修改文件清单。
- P3 剩余建议。
