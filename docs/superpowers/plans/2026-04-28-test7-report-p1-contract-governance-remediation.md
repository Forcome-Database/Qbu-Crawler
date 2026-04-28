# Test7 Report P1 Contract Governance Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 P0 的轻量 `report_user_contract` 升级为独立、稳定、可回归的报告用户语义契约层，并推动 HTML、Excel、邮件优先消费该契约。
**Architecture:** 新增 `qbu_crawler/server/report_contract.py` 作为唯一 contract builder；`report_common.normalize_deep_report_analytics()` 只负责归一化和挂载 contract；渲染层逐步从分散字段迁移到 contract；测试7 artifact replay 用脱敏 fixture 固化生产事故样本。
**Tech Stack:** Python 3.10+, pytest, Jinja2, openpyxl, SQLite workflow 状态, existing report snapshot / analytics / HTML / email pipeline.

---

## Entry Context

- 设计文档：`docs/superpowers/specs/2026-04-28-test7-report-p1-contract-governance-design.md`
- 审计文档：`docs/reviews/2026-04-28-production-test7-report-root-cause-and-remediation.md`
- P0 devlog：`docs/devlogs/D021-test7-report-p0-contract-remediation.md`
- P1 原则：
  - 不直接大改视觉。
  - 不新增 DB migration。
  - 不把 P2/P3 的完整报表平台化混入 P1。
  - 所有用户可见建议必须来自 evidence pack。
  - 新增展示逻辑必须优先读 `report_user_contract`。
  - P1 的 artifact replay 只做测试7最小防回归护栏；完整 artifact 管理和 `report_artifacts` 表仍留到 P2/P3。

---

## File Map

| File | Responsibility | Tasks |
|---|---|---|
| `qbu_crawler/server/report_contract.py` | 新增 contract builder、schema 校验、evidence pack、metric definitions、LLM merge | T1, T2, T3, T4, T5, T6 |
| `qbu_crawler/server/report_common.py` | 调用 contract builder，保留旧归一化兼容字段 | T1, T2 |
| `qbu_crawler/server/report_llm.py` | 让 LLM v3 消费 evidence pack，并按 contract 校验文案 | T3 |
| `qbu_crawler/server/report_snapshot.py` | full report 链路在 LLM/deep analysis 合并后刷新 contract | T3, T8 |
| `qbu_crawler/server/report_html.py` | HTML 渲染前使用带真实 snapshot 的 contract | T1, T4, T8 |
| `qbu_crawler/server/report.py` | Excel 和 full email 渲染优先读带真实 snapshot 的 contract | T1, T4, T5 |
| `qbu_crawler/server/report_templates/daily_report_v3.html.j2` | 诊断卡、heatmap、bootstrap 区块优先读 contract | T4, T6 |
| `qbu_crawler/server/report_templates/email_full.html.j2` | KPI 和行动建议优先读 contract | T4 |
| `tests/server/test_report_contract.py` | contract builder 单元测试 | T1, T2, T5, T6 |
| `tests/server/test_report_contract_llm.py` | LLM merge / validation 测试 | T3 |
| `tests/server/test_report_contract_renderers.py` | HTML / Excel / email contract 消费和真实 snapshot 刷新测试 | T1, T4 |
| `tests/fixtures/report_replay/test7_minimal_snapshot.json` | 脱敏测试7 snapshot fixture | T8 |
| `tests/fixtures/report_replay/test7_minimal_analytics.json` | 脱敏测试7 analytics fixture | T8 |
| `tests/server/test_test7_artifact_replay.py` | artifact replay 回归测试 | T8 |
| `docs/devlogs/D022-test7-report-p1-contract-governance.md` | P1 实施记录 | T9 |

---

## Chunk 1: Contract Builder 基础

### Task 1: 新增 `report_contract.py` 和最小 schema

**Files:**
- Create: `qbu_crawler/server/report_contract.py`
- Modify: `qbu_crawler/server/report_common.py`
- Test: `tests/server/test_report_contract.py`

- [ ] **Step 1.1: 写失败测试：contract 顶层字段完整**

在 `tests/server/test_report_contract.py` 新增：

```python
from qbu_crawler.server.report_contract import build_report_user_contract


def test_build_report_user_contract_has_required_top_level_fields():
    analytics = {
        "report_semantics": "bootstrap",
        "kpis": {"health_index": 96.2},
        "self": {"risk_products": []},
    }
    snapshot = {"logical_date": "2026-04-28", "reviews": [], "products": []}

    contract = build_report_user_contract(snapshot=snapshot, analytics=analytics)

    assert contract["schema_version"] == "report_user_contract.v1"
    assert contract["mode"] == "bootstrap"
    assert contract["logical_date"] == "2026-04-28"
    assert "metric_definitions" in contract
    assert "kpis" in contract
    assert "action_priorities" in contract
    assert "issue_diagnostics" in contract
    assert "heatmap" in contract
    assert "competitor_insights" in contract
    assert "bootstrap_digest" in contract
    assert "delivery" in contract
    assert "validation_warnings" in contract
```

- [ ] **Step 1.2: 运行测试确认失败**

Run:

```bash
uv run pytest tests/server/test_report_contract.py::test_build_report_user_contract_has_required_top_level_fields -v
```

Expected: FAIL，原因是 `report_contract.py` 尚不存在。

- [ ] **Step 1.3: 新增最小 builder**

在 `qbu_crawler/server/report_contract.py` 中实现：

```python
SCHEMA_VERSION = "report_user_contract.v1"


def build_report_user_contract(*, snapshot, analytics, llm_copy=None):
    mode = analytics.get("report_semantics") or analytics.get("mode") or "bootstrap"
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": mode,
        "logical_date": snapshot.get("logical_date") or analytics.get("logical_date"),
        "metric_definitions": {},
        "kpis": dict(analytics.get("kpis") or {}),
        "action_priorities": [],
        "issue_diagnostics": [],
        "heatmap": {},
        "competitor_insights": {},
        "bootstrap_digest": {},
        "delivery": {},
        "validation_warnings": [],
    }
```

- [ ] **Step 1.4: 写失败测试：最终渲染入口必须用真实 snapshot 刷新 contract**

在 `tests/server/test_report_contract_renderers.py` 或 `tests/server/test_report_contract.py` 增加测试，模拟 normalized analytics 已有临时 contract，但 snapshot 为空：

```python
def test_renderer_refreshes_contract_with_real_snapshot_context():
    analytics = {
        "report_semantics": "bootstrap",
        "report_user_contract": {
            "schema_version": "report_user_contract.v1",
            "contract_context": {"snapshot_source": "missing"},
            "issue_diagnostics": [],
        },
    }
    snapshot = {
        "logical_date": "2026-04-28",
        "products": [{"name": "Walton's Quick Patty Maker"}],
        "reviews": [{"id": 101, "product_name": "Walton's Quick Patty Maker"}],
    }

    refreshed = build_report_user_contract(snapshot=snapshot, analytics=analytics)

    assert refreshed["contract_context"]["snapshot_source"] == "provided"
    assert refreshed["contract_context"]["product_count"] == 1
    assert refreshed["contract_context"]["review_count"] == 1
```

- [ ] **Step 1.5: 在 `report_common.py` 挂载临时 contract，但标记缺失 snapshot**

在 `normalize_deep_report_analytics()` 的末尾调用：

```python
from qbu_crawler.server.report_contract import build_report_user_contract

normalized["report_user_contract"] = build_report_user_contract(
    snapshot={},
    analytics=normalized,
)
```

注意：这一步只允许生成临时 contract。builder 必须写入：

```python
"contract_context": {
    "snapshot_source": "missing",
    "product_count": 0,
    "review_count": 0,
}
```

最终 HTML / Excel / 邮件 / replay 渲染入口必须用真实 snapshot 刷新 contract，不能把该临时 contract 当成最终用户契约。

- [ ] **Step 1.6: 在最终渲染入口刷新真实 snapshot contract**

在 `report_html.py`、`report.py`、`report_snapshot.py` 的最终渲染入口确保调用：

```python
analytics["report_user_contract"] = build_report_user_contract(
    snapshot=snapshot,
    analytics=analytics,
    llm_copy=(analytics.get("report_copy") or None),
)
```

如果入口没有 snapshot，就只能使用旧兼容路径，不能声明 contract 已完整。

- [ ] **Step 1.7: 运行测试**

Run:

```bash
uv run pytest tests/server/test_report_contract.py tests/server/test_report_contract_renderers.py tests/test_report_common.py -v
```

Expected: PASS。

---

### Task 2: 指标定义和 evidence pack

**Files:**
- Modify: `qbu_crawler/server/report_contract.py`
- Test: `tests/server/test_report_contract.py`

- [ ] **Step 2.1: 写失败测试：关键 KPI 有 metric definitions**

```python
def test_metric_definitions_describe_time_basis_scope_and_denominator():
    analytics = {
        "report_semantics": "bootstrap",
        "kpis": {
            "health_index": 96.2,
            "fresh_review_count": 5,
            "high_risk_count": 2,
            "attention_product_count": 3,
            "negative_review_rate": 0.18,
            "translation_completion_rate": 1.0,
            "scrape_missing_rate": 0.12,
        },
    }
    contract = build_report_user_contract(
        snapshot={"logical_date": "2026-04-28"},
        analytics=analytics,
    )

    required_fields = [
        "health_index",
        "high_risk_count",
        "attention_product_count",
        "negative_review_rate",
        "fresh_review_count",
        "translation_completion_rate",
        "scrape_missing_rate",
        "heatmap_experience_health",
    ]
    for field in required_fields:
        definition = contract["metric_definitions"][field]
        assert definition["field"] == field
        assert definition["formula"]
        assert definition["time_basis"]
        assert definition["product_scope"]
        assert definition["denominator"]
        assert definition["bootstrap_behavior"]
        assert definition["confidence"]
        assert definition["explanation"]
```

- [ ] **Step 2.2: 写失败测试：issue cluster 生成 evidence pack**

```python
def test_issue_clusters_become_evidence_packs():
    analytics = {
        "report_semantics": "bootstrap",
        "self": {
            "top_negative_clusters": [{
                "label_code": "structure_design",
                "label_display": "结构设计",
                "affected_products": ["Walton's Quick Patty Maker"],
                "evidence_count": 2,
                "example_reviews": [
                    {"id": 101, "body_cn": "肉饼太大", "images": ["https://example.test/a.jpg"]}
                ],
                "deep_analysis": {
                    "actionable_summary": "复核成型尺寸",
                    "failure_modes": [{"name": "尺寸不匹配"}],
                    "root_causes": [{"name": "模具约束不足"}],
                    "user_workarounds": ["手工修整"],
                },
            }]
        },
    }
    contract = build_report_user_contract(snapshot={"logical_date": "2026-04-28"}, analytics=analytics)
    card = contract["issue_diagnostics"][0]
    assert card["label_code"] == "structure_design"
    assert card["affected_products"] == ["Walton's Quick Patty Maker"]
    assert card["evidence_review_ids"] == [101]
    assert card["image_evidence"]
    assert card["failure_modes"]
    assert card["root_causes"]
    assert card["recommended_action"] == "复核成型尺寸"
```

- [ ] **Step 2.3: 运行测试确认失败**

Run:

```bash
uv run pytest tests/server/test_report_contract.py -v
```

Expected: 新测试失败。

- [ ] **Step 2.4: 实现 metric definitions**

在 `report_contract.py` 中添加最小字典构建，不新增复杂类，必须覆盖设计文档列出的 8 个指标：

```python
def _build_metric_definitions(kpis, mode):
    definitions = {}
    # 逐个覆盖 health_index / high_risk_count / attention_product_count /
    # negative_review_rate / fresh_review_count / translation_completion_rate /
    # scrape_missing_rate / heatmap_experience_health
    return definitions
```

- [ ] **Step 2.5: 实现 evidence pack 到 `issue_diagnostics`**

在 builder 内从：

```python
(analytics.get("self") or {}).get("top_negative_clusters") or []
```

生成 `issue_diagnostics`，字段优先级：
- `recommended_action`: `deep_analysis.actionable_summary`
- `evidence_review_ids`: `example_reviews[].id` 或 `review_id`
- `text_evidence`: 中文优先
- `image_evidence`: review `images` 列表展开

- [ ] **Step 2.6: 运行测试**

Run:

```bash
uv run pytest tests/server/test_report_contract.py -v
```

Expected: PASS。

---

## Chunk 2: LLM 只改写锁定事实

### Task 3: LLM copy merge 到 contract 并校验

**Files:**
- Modify: `qbu_crawler/server/report_contract.py`
- Modify: `qbu_crawler/server/report_llm.py`
- Modify: `qbu_crawler/server/report_snapshot.py`
- Test: `tests/server/test_report_contract_llm.py`

- [ ] **Step 3.1: 写失败测试：LLM action 必须落在 evidence pack allowed products 内**

```python
from qbu_crawler.server.report_contract import merge_llm_copy_into_contract


def test_merge_llm_copy_rejects_product_outside_evidence_pack():
    contract = {
        "action_priorities": [],
        "issue_diagnostics": [{
            "label_code": "structure_design",
            "allowed_products": ["Walton's Quick Patty Maker"],
            "affected_products": ["Walton's Quick Patty Maker"],
            "evidence_review_ids": [101],
        }],
        "validation_warnings": [],
    }
    llm_copy = {
        "improvement_priorities": [{
            "label_code": "structure_design",
            "short_title": "复核结构",
            "full_action": "复核结构尺寸",
            "affected_products": ["Unknown Product"],
            "evidence_review_ids": [101],
        }]
    }

    merged = merge_llm_copy_into_contract(contract, llm_copy)

    assert merged["action_priorities"][0]["source"] == "evidence_insufficient"
    assert merged["validation_warnings"]
```

- [ ] **Step 3.2: 写失败测试：合法 LLM copy 进入 `action_priorities`**

断言：

```python
assert merged["action_priorities"][0]["source"] == "llm_rewrite"
assert merged["action_priorities"][0]["full_action"] == "复核结构尺寸"
```

- [ ] **Step 3.3: 写失败测试：LLM prompt payload 只能包含 evidence pack**

在 `tests/server/test_report_contract_llm.py` 增加测试，要求 prompt 构建前先收敛为 evidence payload。函数名可按实现调整，但必须有等价断言：

```python
import json

from qbu_crawler.server.report_llm import _build_llm_evidence_payload


def test_llm_payload_excludes_raw_analytics_and_uses_evidence_pack_only():
    analytics = {
        "self": {
            "risk_products": [{"product_name": "Raw Risk Product"}],
            "top_negative_clusters": [{"label_code": "raw_cluster"}],
        },
        "reviews": [{"id": 999, "body": "raw review should not be serialized"}],
        "report_user_contract": {
            "issue_diagnostics": [{
                "label_code": "structure_design",
                "allowed_products": ["Walton's Quick Patty Maker"],
                "affected_products": ["Walton's Quick Patty Maker"],
                "evidence_review_ids": [101],
                "text_evidence": [{"review_id": 101, "display_body": "肉饼太大"}],
            }]
        },
    }

    payload = _build_llm_evidence_payload(analytics)
    payload_text = json.dumps(payload, ensure_ascii=False)

    assert "structure_design" in payload_text
    assert "肉饼太大" in payload_text
    assert "Raw Risk Product" not in payload_text
    assert "raw_cluster" not in payload_text
    assert "raw review should not be serialized" not in payload_text
```

- [ ] **Step 3.4: 运行测试确认失败**

Run:

```bash
uv run pytest tests/server/test_report_contract_llm.py -v
```

Expected: FAIL。

- [ ] **Step 3.5: 实现 `merge_llm_copy_into_contract()`**

规则：
- 按 `label_code` 找对应 `issue_diagnostics`。
- `affected_products` 必须是 `allowed_products` 或 card `affected_products` 子集。
- `evidence_review_ids` 必须是 card evidence 子集。
- 不合法时保留 label，但输出 `source="evidence_insufficient"`，并写 `validation_warnings`。
- 合法时输出 `source="llm_rewrite"`。

- [ ] **Step 3.6: 调整 `report_llm.py` prompt 输入**

将 v3 prompt 中的行动建议事实源从散落 analytics 调整为 evidence pack 摘要。保持函数签名兼容，但函数内部必须先调用 `_build_llm_evidence_payload()` 或等价收敛逻辑，只允许序列化 `report_user_contract.issue_diagnostics` 派生出的字段。不能直接把完整 `analytics.self`、`risk_products`、`top_negative_clusters` 或原始 reviews 写进 prompt。

- [ ] **Step 3.7: 在 full report 链路刷新 contract**

在 `report_snapshot.py` 中，LLM copy、fallback 和 deep analysis 合并后调用：

```python
analytics["report_user_contract"] = build_report_user_contract(
    snapshot=snapshot,
    analytics=analytics,
    llm_copy=insights,
)
```

- [ ] **Step 3.8: 运行测试**

Run:

```bash
uv run pytest tests/server/test_report_contract_llm.py tests/server/test_llm_assert_consistency.py tests/test_report_snapshot.py -v
```

Expected: PASS。

---

## Chunk 3: 渲染消费者迁移

### Task 4: HTML / Excel / 邮件优先消费 contract

**Files:**
- Modify: `qbu_crawler/server/report.py`
- Modify: `qbu_crawler/server/report_html.py`
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.html.j2`
- Modify: `qbu_crawler/server/report_templates/email_full.html.j2`
- Test: `tests/server/test_report_contract_renderers.py`

- [ ] **Step 4.1: 写失败测试：Excel 行动建议只用 contract 也能生成**

构造 analytics：只放 `report_user_contract.action_priorities`，不放 `report_copy.improvement_priorities`。生成 workbook 后断言“现在该做什么”sheet 包含 `full_action`。

- [ ] **Step 4.2: 写失败测试：HTML 诊断卡只用 contract 也能显示图片和建议**

构造 analytics：只放 `report_user_contract.issue_diagnostics`，不放 `issue_cards`。渲染 HTML 后断言：

```python
assert "issue-image-evidence" in html
assert "复核结构尺寸" in html
```

- [ ] **Step 4.3: 写失败测试：邮件 Top actions 只用 contract**

构造 analytics：只放 `report_user_contract.action_priorities` 和 `report_user_contract.kpis`。渲染 email 后断言 action 文案出现。

- [ ] **Step 4.4: 写失败测试：renderer 不消费缺少 snapshot 的临时 contract**

构造 analytics 中已有 `report_user_contract.contract_context.snapshot_source="missing"`，同时传入真实 snapshot 渲染 HTML。断言渲染前后使用的是刷新后的 contract：

```python
assert "snapshot_source=\"provided\"" in html or "Walton's Quick Patty Maker" in html
assert "stale temporary card" not in html
```

如果 HTML 不适合暴露 `snapshot_source`，测试可以 monkeypatch `build_report_user_contract()`，断言 renderer 调用了 builder 且传入真实 snapshot。

- [ ] **Step 4.5: 运行测试确认失败**

Run:

```bash
uv run pytest tests/server/test_report_contract_renderers.py -v
```

Expected: FAIL。

- [ ] **Step 4.6: 修改 Excel 消费逻辑**

在 `report.py` 中，所有行动建议读取统一走：

```python
contract = analytics.get("report_user_contract") or {}
priorities = contract.get("action_priorities") or ...
```

不要新增一次性 helper；只在当前使用处保持简洁。

- [ ] **Step 4.7: 修改 HTML 模板消费逻辑**

在 `daily_report_v3.html.j2` 中：
- 问题诊断优先循环 `report_user_contract.issue_diagnostics`。
- heatmap 优先读取 `report_user_contract.heatmap`。
- contract 缺失时 fallback 到 P0 字段。

- [ ] **Step 4.8: 修改邮件模板消费逻辑**

在 `email_full.html.j2` 中：
- KPI 优先 `report_user_contract.kpis`。
- Top actions 优先 `report_user_contract.action_priorities`。

- [ ] **Step 4.9: 运行测试**

Run:

```bash
uv run pytest tests/server/test_report_contract_renderers.py tests/server/test_excel_sheets.py tests/server/test_attachment_html_issues.py tests/server/test_email_full_template.py -v
```

Expected: PASS。

---

### Task 5: 竞品启示 contract

**Files:**
- Modify: `qbu_crawler/server/report_contract.py`
- Modify: `qbu_crawler/server/report.py`
- Test: `tests/server/test_report_contract.py`
- Test: `tests/server/test_report_contract_renderers.py`

- [ ] **Step 5.1: 写失败测试：竞品启示分为三类**

```python
def test_competitor_insights_contract_has_three_sections():
    analytics = {
        "competitor": {
            "positive_patterns": [{
                "summary_cn": "竞品安装步骤清晰",
                "review_ids": [201],
                "product_count": 2,
                "sample_size": 8,
            }],
            "negative_opportunities": [{
                "body_cn": "竞品包装容易破损",
                "review_ids": [301],
                "product_count": 1,
                "sample_size": 3,
            }],
        }
    }
    contract = build_report_user_contract(snapshot={"logical_date": "2026-04-28"}, analytics=analytics)
    insights = contract["competitor_insights"]
    assert "learn_from_competitors" in insights
    assert "avoid_competitor_failures" in insights
    assert "validation_hypotheses" in insights
```

- [ ] **Step 5.2: 写失败测试：每条启示有中文摘要、验证动作和证据 ID**

断言每条 item 包含：

```python
assert item["summary_cn"]
assert item["self_product_implication"]
assert item["suggested_validation"]
assert item["evidence_review_ids"]
assert item["sample_size"] >= 1
assert item["product_count"] >= 1
```

- [ ] **Step 5.3: 运行测试确认失败**

Run:

```bash
uv run pytest tests/server/test_report_contract.py -v
```

Expected: FAIL。

- [ ] **Step 5.4: 实现 `_build_competitor_insights()`**

最小规则：
- `positive_patterns` -> `learn_from_competitors`
- `negative_opportunities` -> `avoid_competitor_failures`
- 从前两类生成少量 `validation_hypotheses`
- 中文字段优先：`summary_cn`、`body_cn`、`headline_cn`
- 每条 item 必须补齐 `self_product_implication`，把竞品事实转成对自有产品的启发；不能只堆评论摘要

- [ ] **Step 5.5: Excel 竞品 sheet 优先读 contract**

在 `report.py` 的“竞品启示”sheet 中优先读取：

```python
(analytics.get("report_user_contract") or {}).get("competitor_insights")
```

- [ ] **Step 5.6: 运行测试**

Run:

```bash
uv run pytest tests/server/test_report_contract.py tests/server/test_report_contract_renderers.py tests/server/test_competitor_insights_v12.py tests/server/test_excel_sheets.py -v
```

Expected: PASS。

---

### Task 6: Bootstrap digest contract

**Files:**
- Modify: `qbu_crawler/server/report_contract.py`
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.html.j2`
- Test: `tests/server/test_report_contract.py`
- Test: `tests/server/test_report_contract_renderers.py`

- [ ] **Step 6.1: 写失败测试：bootstrap digest 不含增量措辞**

```python
def test_bootstrap_digest_forbids_incremental_terms():
    contract = build_report_user_contract(
        snapshot={"logical_date": "2026-04-28", "reviews": [1, 2], "products": [1]},
        analytics={"report_semantics": "bootstrap", "kpis": {"attention_product_count": 3}},
    )
    text = str(contract["bootstrap_digest"])
    assert "较昨日" not in text
    assert "较上期" not in text
    assert "新增增长" not in text
    assert "监控起点" in text or contract["bootstrap_digest"]["baseline_summary"]
```

- [ ] **Step 6.2: 写失败测试：bootstrap 仍展示 immediate attention**

构造 risk products / issue diagnostics，断言 `bootstrap_digest.immediate_attention` 非空。

- [ ] **Step 6.3: 写失败测试：bootstrap digest 包含当前截面和数据质量**

```python
def test_bootstrap_digest_contains_baseline_and_data_quality():
    snapshot = {
        "logical_date": "2026-04-28",
        "products": [{"name": "A"}, {"name": "B"}],
        "reviews": [{"id": 1}, {"id": 2}, {"id": 3}],
    }
    analytics = {
        "report_semantics": "bootstrap",
        "kpis": {
            "coverage_rate": 0.75,
            "translation_completion_rate": 1.0,
            "historical_backfill_ratio": 0.8,
            "estimated_date_ratio": 0.2,
        },
        "data_quality": {
            "low_coverage_products": ["B"],
        },
    }

    contract = build_report_user_contract(snapshot=snapshot, analytics=analytics)
    digest = contract["bootstrap_digest"]

    assert digest["baseline_summary"]["product_count"] == 2
    assert digest["baseline_summary"]["review_count"] == 3
    assert digest["baseline_summary"]["coverage_rate"] == 0.75
    assert digest["baseline_summary"]["translation_completion_rate"] == 1.0
    assert digest["data_quality"]["historical_backfill_ratio"] == 0.8
    assert digest["data_quality"]["estimated_date_ratio"] == 0.2
    assert digest["data_quality"]["low_coverage_products"] == ["B"]
```

- [ ] **Step 6.4: 运行测试确认失败**

Run:

```bash
uv run pytest tests/server/test_report_contract.py -v
```

Expected: FAIL。

- [ ] **Step 6.5: 实现 `_build_bootstrap_digest()`**

输出：
- `baseline_summary`
- `data_quality`
- `immediate_attention`
- `forbidden_change_terms`

- [ ] **Step 6.6: HTML 今日变化 Tab 优先读 bootstrap digest**

在模板中 bootstrap 分支优先读取 contract 的 `bootstrap_digest`，不再只显示单张说明卡。

- [ ] **Step 6.7: 运行测试**

Run:

```bash
uv run pytest tests/server/test_report_contract.py tests/server/test_report_contract_renderers.py tests/test_v3_mode_semantics.py -v
```

Expected: PASS。

---

## Chunk 4: Delivery 与 Replay

### Task 7: Delivery contract 语义固化

**Files:**
- Modify: `qbu_crawler/server/report_contract.py`
- Test: `tests/server/test_report_contract.py`
- Test: `tests/server/test_workflow_ops_alert_wiring.py`

- [ ] **Step 7.1: 写失败测试：delivery 区分本地生成和外部送达**

```python
def test_delivery_contract_distinguishes_generated_and_delivered():
    analytics = {
        "delivery": {
            "report_generated": True,
            "email_delivered": True,
            "workflow_notification_delivered": False,
            "deadletter_count": 3,
            "internal_status": "full_sent_local",
        }
    }
    contract = build_report_user_contract(snapshot={"logical_date": "2026-04-28"}, analytics=analytics)
    delivery = contract["delivery"]
    assert delivery["report_generated"] is True
    assert delivery["workflow_notification_delivered"] is False
    assert delivery["internal_status"] == "full_sent_local"
```

- [ ] **Step 7.2: 运行测试确认失败**

Run:

```bash
uv run pytest tests/server/test_report_contract.py -v
```

Expected: FAIL。

- [ ] **Step 7.3: 实现 `_build_delivery()`**

优先从 `analytics.delivery` 读取；缺失时从已有 workflow/report phase 字段推导保守值。

- [ ] **Step 7.4: 运行测试**

Run:

```bash
uv run pytest tests/server/test_report_contract.py tests/server/test_workflow_ops_alert_wiring.py -v
```

Expected: PASS。

---

### Task 8: 测试7 artifact replay 最小 fixture

**Files:**
- Create: `tests/fixtures/report_replay/test7_minimal_snapshot.json`
- Create: `tests/fixtures/report_replay/test7_minimal_analytics.json`
- Create: `tests/server/test_test7_artifact_replay.py`
- Modify if needed: `qbu_crawler/server/report_html.py`
- Modify if needed: `qbu_crawler/server/report.py`

- [ ] **Step 8.1: 建立脱敏 fixture**

从测试7事实抽取最小样本，不提交隐私或大体积原始产物。fixture 必须覆盖：
- 2 个自有产品，1 个竞品产品。
- 至少 1 条带图片评论。
- 至少 1 条 parsed 日期在近30天内的评论。
- 至少 1 个 `deep_analysis`。
- 至少 2 个不同 label 的 action priority。
- 1 个 competitor negative opportunity，带中文字段。
- delivery deadletter 场景。

- [ ] **Step 8.2: 写 replay 测试：contract 层**

```python
def test_test7_replay_contract_preserves_user_semantics():
    snapshot, analytics = load_fixture()
    contract = build_report_user_contract(snapshot=snapshot, analytics=analytics)

    actions = [item["full_action"] for item in contract["action_priorities"]]
    assert len(set(actions)) == len(actions)
    assert any(card["image_evidence"] for card in contract["issue_diagnostics"])
    assert contract["competitor_insights"]["avoid_competitor_failures"]
    assert contract["delivery"]["workflow_notification_delivered"] is False
```

- [ ] **Step 8.3: 写 replay 测试：HTML / Excel / 邮件**

断言：
- HTML 出现图片证据区。
- HTML 出现 AI 摘要。
- heatmap `data-product` 使用完整产品名。
- Excel “现在该做什么”行动建议不全重复。
- Excel “竞品启示”出现中文摘要、样本数、涉及产品数和对自有产品的启发。
- 邮件 KPI 使用 contract 值。

- [ ] **Step 8.4: 运行测试确认失败或暴露缺口**

Run:

```bash
uv run pytest tests/server/test_test7_artifact_replay.py -v
```

Expected: 初次可能 FAIL，根据失败点补齐 contract 或消费者迁移。

- [ ] **Step 8.5: 补齐 replay 暴露的缺口**

只修 P1 contract 和消费者迁移问题；不要扩展视觉、不改业务阈值。

- [ ] **Step 8.6: 运行 replay 和报告核心回归**

Run:

```bash
uv run pytest tests/server/test_test7_artifact_replay.py tests/test_v3_html.py tests/test_v3_excel.py tests/test_report_common.py tests/test_report_snapshot.py -v
```

Expected: PASS。

---

## Chunk 5: 收口

### Task 9: 文档和开发日志

**Files:**
- Create: `docs/devlogs/D022-test7-report-p1-contract-governance.md`
- Optional modify: `AGENTS.md` if the contract layer becomes a lasting architecture rule.

- [ ] **Step 9.1: 新增 devlog**

记录：
- P1 新增的 `report_contract.py` 边界。
- contract schema 关键字段。
- HTML / Excel / 邮件迁移范围。
- artifact replay fixture 覆盖点。
- 未完成的 P2/P3 项。

- [ ] **Step 9.2: 判断是否更新 AGENTS.md**

如果 P1 已经确立“报告展示层必须优先消费 `report_user_contract`”为长期规则，则在 AGENTS.md 的“报表语义治理”增量里增加一条。若只是局部实现，不更新。

- [ ] **Step 9.3: 运行定向回归**

Run:

```bash
uv run pytest ^
  tests/server/test_report_contract.py ^
  tests/server/test_report_contract_llm.py ^
  tests/server/test_report_contract_renderers.py ^
  tests/server/test_test7_artifact_replay.py ^
  tests/test_report_common.py ^
  tests/test_report_snapshot.py ^
  tests/test_v3_html.py ^
  tests/test_v3_excel.py ^
  -v
```

Expected: PASS。

- [ ] **Step 9.4: 运行报告相关扩展回归**

Run:

```bash
uv run pytest tests/server/test_*report* tests/test_*report* tests/test_v3_html.py tests/test_v3_excel.py -v
```

Expected: PASS 或仅保留已知 skip。

- [ ] **Step 9.5: 检查旧字段依赖**

Run:

```bash
rg -n "report_copy|issue_cards|top_negative_clusters|deep_analysis|positive_patterns|negative_opportunities" qbu_crawler/server/report.py qbu_crawler/server/report_html.py qbu_crawler/server/report_templates
```

Expected:
- 允许 fallback 分支存在。
- 新增主路径应优先读取 `report_user_contract`。
- 若模板直接读取旧字段，必须有注释或测试说明兼容原因。

---

## Execution Notes

- 当前工作树已有大量 P0 未提交改动，执行 P1 前必须先确认 P0 改动状态，不要回滚。
- 每个 task 都按 TDD 顺序推进：先失败测试，再最小实现，再回归。
- 不要为了 contract builder 引入复杂类层级；简单 dict builder 足够。
- 不要把 DB migration、完整竞品产品化和视觉改版塞进 P1。
- 若 replay fixture 涉及生产评论内容，必须脱敏或缩短为可验证片段。

---

## Ready Criteria

执行前确认：

- [ ] P0 已合并或当前工作树状态已被用户接受。
- [ ] 用户确认 P1 只做 contract governance，不做视觉重设计。
- [ ] 执行者已阅读设计文档和本计划。
- [ ] 执行者准备使用 `superpowers:executing-plans` 或 `superpowers:subagent-driven-development`。

完成后必须提供：

- 变更摘要。
- 测试命令和结果。
- 新增/修改文件清单。
- 剩余 P2/P3 建议。
