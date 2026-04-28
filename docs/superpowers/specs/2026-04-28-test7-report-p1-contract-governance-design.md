# 测试7报告 P1 用户语义契约治理设计

**日期**：2026-04-28
**状态**：设计完成，待实施计划执行
**输入文档**：
- `docs/reviews/2026-04-28-production-test7-report-root-cause-and-remediation.md`
- `docs/superpowers/specs/2026-04-28-test7-report-p0-contract-design.md`
- `docs/devlogs/D021-test7-report-p0-contract-remediation.md`

---

## 1. 背景

P0 已完成测试7最影响信任的止血修复：LLM 产品集合校验、fallback 行动建议差异化、诊断卡图片和 AI 建议展示、heatmap tooltip 与下钻、近30天筛选、竞品中文字段、高风险/需关注口径、delivery deadletter 降级等。

但 P0 仍然是“轻量 contract-first”：`report_user_contract` 还嵌在 `report_common.normalize_deep_report_analytics()` 里，HTML、Excel、邮件仍保留大量兼容读取逻辑。P1 的目标不是再修一个 Tab，而是把报告用户可见语义收口到独立、稳定、可测试的契约层，降低后续 LLM schema、analytics 结构和模板展示互相牵连的风险。

---

## 2. 目标

1. 新增独立 `report_user_contract` 构建层，作为 HTML、Excel、邮件的优先展示输入。
2. 每个用户可见指标声明时间口径、产品集合、分母、bootstrap 状态、置信度和展示解释。
3. 行动建议先由规则层生成 evidence pack；LLM 只改写已锁定事实，不负责决定事实集合。
4. 诊断卡、行动建议、heatmap、竞品启示、bootstrap 首日体验都通过 contract 输出稳定 display 字段。
5. 建立测试7 artifact replay 骨架，用生产样本形态回归 HTML / Excel / 邮件的关键语义。
6. 拆清本地报告生成、邮件送达、workflow 通知送达的状态模型，为后续 DB migration 做准备。

---

## 3. 非目标

- 不重做页面视觉设计。
- 不新增大型数据仓库或完整 BI 层。
- 不把竞品启示的全部产品化体验一次做完；P1 只完成 contract 结构和最小消费者迁移。
- 不要求把测试7完整生产 JSON 原样提交入仓；如体积或隐私不合适，使用脱敏最小 fixture。
- 不在 P1 强制新增 DB migration；delivery 独立字段先完成设计和内存/JSON contract 表达，迁移可单独进入 P2。

---

## 4. 核心设计

### 4.1 新模块边界

新增模块：

`qbu_crawler/server/report_contract.py`

职责：
- 从 snapshot、analytics、normalized analytics、LLM copy 中构建 `report_user_contract`。
- 输出面向展示层的稳定字段。
- 保留字段来源和置信度，不让模板理解底层 schema 细节。
- 提供轻量校验函数，确保用户可见建议有证据或明确标记为证据不足。

`report_common.normalize_deep_report_analytics()` 继续负责历史归一化，但不再承担 contract 的主要组装职责。P1 结束后，`normalize_deep_report_analytics()` 应只调用 contract builder 并把结果挂载回 analytics。

入口约束：
- `build_report_user_contract(snapshot, analytics, ...)` 是最终 contract 的唯一构建入口。
- HTML、Excel、邮件、artifact replay 等最终渲染入口必须传入真实 snapshot 或等价的最小 snapshot 上下文，不能把 `snapshot={}` 产物当作最终用户契约。
- `normalize_deep_report_analytics()` 可以在缺少 snapshot 时挂载临时 contract，但必须标记 `contract_context.snapshot_source = "missing"`；最终渲染前必须刷新为 `snapshot_source = "provided"`。
- 任一 renderer 如果发现 contract 缺少真实 snapshot 上下文，应主动刷新 contract，而不是继续消费旧字段。

### 4.2 Contract 顶层结构

```json
{
  "schema_version": "report_user_contract.v1",
  "mode": "bootstrap",
  "logical_date": "2026-04-28",
  "metric_definitions": {},
  "kpis": {},
  "action_priorities": [],
  "issue_diagnostics": [],
  "heatmap": {},
  "competitor_insights": {},
  "bootstrap_digest": {},
  "delivery": {},
  "validation_warnings": []
}
```

规则：
- `schema_version` 必须存在，模板可以据此判断兼容策略。
- `mode` 只允许 `bootstrap` 或 `incremental`。
- `validation_warnings` 只给内部测试和运维使用，不直接暴露给业务用户。
- 用户可见字段优先来自 contract；旧字段只作为短期兼容 fallback。

### 4.3 指标语义

每个 KPI 和 heatmap 指标都必须有定义：

```json
{
  "field": "fresh_review_count",
  "display_name": "近30天评论",
  "formula": "count(reviews where date_published_parsed in last 30 days)",
  "time_basis": "date_published_parsed",
  "product_scope": "all_products",
  "denominator": "all_reviews",
  "bootstrap_behavior": "shown_as_current_snapshot",
  "confidence": "medium",
  "explanation": "按评论发布时间估算，无法解析日期的评论不计入近30天"
}
```

P1 必须覆盖这些指标：
- 健康指数
- 高风险产品数
- 需关注产品数
- 差评率
- 近30天评论数
- 翻译完成率
- 采集缺失率
- heatmap 体验健康度

验收时不得只抽测部分 KPI。上述指标都必须在 `metric_definitions` 中具备 `field`、`formula`、`time_basis`、`product_scope`、`denominator`、`bootstrap_behavior`、`confidence` 和 `explanation`。

### 4.4 Evidence Pack

行动建议和诊断卡共享同一 evidence pack：

```json
{
  "label_code": "structure_design",
  "label_display": "结构设计",
  "allowed_products": [],
  "affected_products": [],
  "evidence_count": 0,
  "evidence_review_ids": [],
  "text_evidence": [],
  "image_evidence": [],
  "failure_modes": [],
  "root_causes": [],
  "user_workarounds": [],
  "source_cluster_ids": [],
  "confidence": "high"
}
```

LLM 输入只能引用 evidence pack 中已锁定的事实。LLM 输出的 `affected_products`、`evidence_review_ids`、`label_code` 必须回到对应 pack 校验；校验失败时，不能把无证据文案展示为正式建议。

实现约束：
- LLM prompt payload 必须由 `report_user_contract.issue_diagnostics` 或等价 evidence pack 派生。
- LLM prompt 不得直接序列化完整 `analytics.self`、`top_negative_clusters`、`risk_products` 或原始 reviews。
- 如果为了兼容暂时保留旧函数签名，函数内部也必须先收敛到 evidence payload，再生成 prompt。
- 测试必须断言 prompt payload 中不存在未经过 evidence pack 收敛的全量分析字段。

### 4.5 行动建议

`action_priorities` 是“现在该做什么”的唯一来源：

```json
{
  "priority": 1,
  "label_code": "structure_design",
  "short_title": "复核进料口适配路径",
  "full_action": "围绕结构设计问题，优先复核...",
  "source": "llm_rewrite|deep_analysis|rule_fallback|evidence_insufficient",
  "affected_products": [],
  "evidence_review_ids": [],
  "top_complaint": "...",
  "confidence": "high"
}
```

验收要求：
- 同一报告中不允许多条 `full_action` 完全相同。
- `source != evidence_insufficient` 时必须有 `evidence_review_ids` 或 `top_complaint`。
- Excel、HTML、邮件不再直接读取 `report_copy.improvement_priorities`。

### 4.6 诊断卡

`issue_diagnostics` 是问题诊断 Tab 的唯一来源：

```json
{
  "label_code": "quality_stability",
  "label_display": "质量稳定性",
  "severity": "high",
  "affected_products": [],
  "evidence_count": 12,
  "text_evidence": [],
  "image_evidence": [],
  "ai_summary": "...",
  "recommended_action": "...",
  "failure_modes": [],
  "root_causes": [],
  "user_workarounds": [],
  "confidence": "high"
}
```

模板不再理解 `top_negative_clusters`、`deep_analysis`、`report_copy` 的内部关系，只渲染 contract 提供的 display 字段。

### 4.7 Heatmap

`heatmap` contract 输出完整产品名、显示名、分数组成和代表评论：

```json
{
  "metric_name": "体验健康度",
  "formula": "(positive + 0.5 * mixed) / sample_size",
  "x_labels": [],
  "y_items": [
    {"product_name": "完整产品名", "display_label": "短显示名"}
  ],
  "cells": []
}
```

每个 cell 必须包含：
- `score`
- `sample_size`
- `positive_count`
- `mixed_count`
- `negative_count`
- `neutral_count`
- `tooltip`
- `top_review_id`
- `top_review_excerpt`
- `drilldown_product_name`
- `drilldown_label_code`

### 4.8 竞品启示

P1 将竞品启示收口到 contract，但只做最小产品化：

```json
{
  "learn_from_competitors": [],
  "avoid_competitor_failures": [],
  "validation_hypotheses": []
}
```

每条启示必须包含：
- 样本数
- 涉及产品数
- 中文摘要
- 对自有产品的启发
- 建议验证动作
- 证据 review ID

长评论全文仍保留在“评论原文”sheet，竞品启示页只展示摘要和动作。

### 4.9 Bootstrap 首日体验

`bootstrap_digest` 替代把首日简单塞进“今日变化”：

```json
{
  "baseline_summary": {},
  "data_quality": {},
  "immediate_attention": [],
  "forbidden_change_terms": ["较昨日", "较上期", "今日新增增长"]
}
```

bootstrap 下允许展示当前风险和立即关注项，但禁止使用增量措辞。incremental 下才展示变化、趋势和归因。

`baseline_summary` 至少包含产品数、评论数、覆盖率、翻译率；`data_quality` 至少包含历史补采占比、估算日期占比、低覆盖产品；`immediate_attention` 至少覆盖红/黄灯产品、Top 问题簇和需人工确认项。

### 4.10 Delivery 状态

contract 中先表达三类状态：

```json
{
  "report_generated": true,
  "email_delivered": true,
  "workflow_notification_delivered": false,
  "deadletter_count": 3,
  "internal_status": "full_sent_local"
}
```

P1 不强制 DB migration，但文档和测试要把语义固化：`completed/full_sent` 不能被解释为所有外部通知均已送达。

---

## 5. 数据流

1. `report_snapshot.py` 生成 snapshot。
2. `report_analytics.py` 生成 analytics。
3. `report_common.normalize_deep_report_analytics()` 做历史归一化。
4. `report_contract.build_report_user_contract()` 构建 evidence pack、指标定义和展示字段。
5. `report_llm.py` 只接收 evidence pack，返回文案改写。
6. `report_contract.merge_llm_copy()` 将 LLM 文案回填到 contract，并执行校验。
7. HTML、Excel、邮件优先消费 contract。
8. artifact replay 使用 snapshot + analytics fixture 重放 contract 和渲染结果。

最终渲染链路必须满足：snapshot 与 analytics 同时进入 contract builder；如果上游只传入 normalized analytics，renderer 需要用当前 snapshot 刷新 contract 后再渲染。

---

## 6. 兼容策略

P1 允许短期双写：
- contract 写入 `analytics["report_user_contract"]`
- 旧字段保留，以免现有测试和旧模板立即断裂

但新增模板逻辑必须遵守：
- 优先读 `report_user_contract`
- 缺失时才 fallback 到旧字段
- fallback 分支需要测试覆盖，并在后续 P2 移除

P1 中的 artifact replay 只承担测试7最小防回归护栏：用脱敏 fixture 固化本次事故样本。完整 artifact 管理、`report_artifacts` 表和跨 run 产物血缘仍留到 P2/P3。

---

## 7. 测试策略

### 7.1 单元测试

- contract schema 必填字段。
- metric definitions 覆盖关键 KPI。
- evidence pack 校验产品集合、证据 ID 和置信度。
- action priorities 不重复且可追溯。
- issue diagnostics 含图片、AI 摘要、failure modes、root causes。
- heatmap cell 含完整下钻字段。
- competitor insights 输出三类摘要。
- bootstrap digest 禁止增量措辞。
- delivery contract 区分本地生成和外部送达。

### 7.2 渲染测试

- HTML 问题诊断 Tab 只依赖 contract 即可渲染。
- Excel “现在该做什么”只依赖 `action_priorities`。
- Excel “竞品启示”只展示中文摘要和验证动作。
- 邮件 Top actions 和 KPI 只读 contract。

### 7.3 Artifact Replay

建立脱敏测试7 fixture：
- snapshot 最小字段
- analytics 最小字段
- reviews 中保留可验证的图片、中文、日期、label、产品名

回归断言：
- 改良方向不全重复。
- 有图片 evidence 时 HTML 出现图片区。
- 有 deep analysis 时 HTML 出现 AI 摘要。
- 近30天 KPI 与全景筛选一致。
- heatmap 下钻使用完整产品名。
- 竞品启示不回退英文正文。
- delivery deadletter 不显示成完整送达。

---

## 8. 验收标准

1. `qbu_crawler/server/report_contract.py` 成为 report contract 的唯一构建入口。
2. HTML、Excel、邮件的新增逻辑优先消费 `report_user_contract`。
3. 用户可见行动建议全部可追溯到 evidence pack。
4. 指标字段具备时间口径、产品集合、分母、bootstrap 行为和置信度说明。
5. 测试7 replay fixture 能覆盖 P0 已暴露的关键问题。
6. P1 不引入新的生产 DB migration；delivery 独立字段进入后续迁移计划。

---

## 9. 推进建议

P1 应按“小步迁移”执行：

1. 先建立 contract builder 和 schema 测试。
2. 再迁移 HTML 诊断卡、Excel 行动建议、邮件 KPI。
3. 再补 competitor/bootstrap/heatmap 的 contract display 字段。
4. 最后加入测试7 artifact replay，锁住这次事故样本。

这样可以避免把 P1 变成一次不可控的大重构，同时真正解决测试7暴露的根因：展示层缺少稳定的用户语义契约。
