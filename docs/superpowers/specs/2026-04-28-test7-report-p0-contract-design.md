# 测试7报告 P0 轻量语义契约修复设计

**日期**: 2026-04-28  
**状态**: 已选择 B 方案，待实施计划执行  
**范围**: 测试7审计暴露的 P0 信任问题；轻量 contract-first，不做完整报表重构  
**输入文档**: `docs/reviews/2026-04-28-production-test7-report-root-cause-and-remediation.md`

---

## 1. 背景

测试7报告已能成功产出 DB、snapshot、analytics、HTML、Excel 和邮件正文，但用户侧看到的结果存在明显信任断点：

- LLM 请求 HTTP 200，但本地 `assert_consistency()` 因产品集合契约错配连续失败。
- LLM 失败后 fallback 继续生成报告，但“改良方向”多行完全相同，且缺证据 ID。
- 诊断卡底层已有图片证据和 `deep_analysis`，HTML 没有展示，AI 建议为空。
- 热力图分数、tooltip 代表评论、点击下钻筛选使用不同语义，导致 100% 分数能弹出抱怨内容。
- Excel“竞品启示”已有中文翻译却回退英文。
- 全景近 30 天筛选不读 `date_published_parsed`，与 KPI 不一致。
- 邮件“需关注产品”和 HTML“高风险产品”口径不同。
- `notification_outbox` deadletter 后 workflow 仍显示 `completed/full_sent`。

这些问题共同说明：报告系统缺少一层稳定的“用户语义契约”。本设计采用 B 方案：先做轻量 contract-first 的 P0 止血，不立刻重构完整报表系统。

---

## 2. 目标

### 2.1 P0 目标

- 恢复用户对报告的基本信任：数字、tooltip、建议、图片、中文和送达状态不互相矛盾。
- 建立最小 `report_user_contract`，先覆盖 P0 所需的行动建议、诊断卡、热力图、KPI 辅助字段。
- 保持现有 HTML / Excel / 邮件主体结构不大改，只让它们优先消费稳定字段。
- 保持现有 `report_semantics = bootstrap | incremental` 约束，不新增第三种语义。
- 所有用户可见建议都能追溯到证据；无证据时不能伪装成正式建议。

### 2.2 非目标

- 不在 P0 中完整重构报表信息架构。
- 不新增完整 `metric_definitions` 表。
- 不重做全部 Tab 的视觉设计。
- 不把 P1/P2 的竞品启示产品化、artifact 管理和长期指标血缘一次做完。
- 不修复生产环境 bridge 401 配置本身，只修内部状态表达和 deadletter reconcile。

---

## 3. 关键决策

### 3.1 采用轻量 `report_user_contract`

P0 不另起一条大管线，而是在现有 analytics 归一化链路中补充一个稳定子结构：

```json
{
  "report_user_contract": {
    "action_priorities": [],
    "issue_diagnostics": [],
    "heatmap": {},
    "kpi_semantics": {},
    "delivery": {}
  }
}
```

该结构优先服务 P0 展示和测试。为了降低改动风险，短期内继续保留旧字段：

- `report_copy.improvement_priorities`
- `issue_cards`
- `_heatmap_data`
- `kpis.high_risk_count`

但模板和 Excel 新增逻辑应优先读取 contract 字段；旧字段作为兼容 fallback。

### 3.2 LLM 只改写事实，不决定事实集合

行动建议的事实边界由规则层先生成：

- `label_code`
- `allowed_products`
- `affected_products`
- `evidence_review_ids`
- `top_complaint`
- `image_evidence`
- `deep_analysis`

LLM 负责把这些事实写成业务建议，不负责扩展产品集合或创造证据。校验也必须按每条 priority 的 `label_code` 和 `allowed_products` 判断，而不是全局套用 `risk_products`。

### 3.3 fallback 是正式体验

LLM 不可用或校验失败时，fallback 仍会进入生产报告。P0 要求 fallback 至少满足：

- 每条建议 `full_action` 不完全重复。
- 每条建议绑定 `evidence_review_ids` 或明确为“证据不足”。
- 每条建议有 `top_complaint` 或典型原话。
- 每条建议的 `affected_products` 来自真实问题簇或风险产品。
- 不在用户可见文案中出现“规则降级”“LLM 失败”等工程词。

### 3.4 时间口径固定

- 入库窗口：`scraped_at`
- 新近评论 / 近 30 天：优先 `date_published_parsed`
- 原始日期展示：`date_published`
- 估算日期：保留估算提示，不作为绝对精确事实夸大

### 3.5 风险口径拆字段

- `high_risk_count`：红灯 / 高风险产品数。
- `attention_product_count`：红灯 + 黄灯 / 需关注产品数。

HTML 和邮件不再分别临时计算同类指标；统一从 normalized analytics 或 `report_user_contract.kpi_semantics` 读取。

### 3.6 运维状态拆语义

P0 不新增 DB migration，优先复用已有 `report_phase='full_sent_local'` 表达“本地 full report 已生成，但外部通知失败”。同时补充 completed run 的 deadletter reconcile，避免 `deadletter` 被伪装成 `full_sent`。

---

## 4. 设计结构

### 4.1 `action_priorities`

来源：

- 首选：通过校验的 LLM v3 `report_copy.improvement_priorities`
- 次选：基于 `top_negative_clusters`、`risk_products`、`deep_analysis` 的规则 fallback

字段：

```json
{
  "label_code": "structure_design",
  "short_title": "缩短、明确的行动标题",
  "full_action": "差异化行动建议",
  "source": "llm|rule_fallback|evidence_insufficient",
  "allowed_products": ["完整产品名"],
  "affected_products": ["完整产品名"],
  "affected_products_count": 1,
  "evidence_count": 3,
  "evidence_review_ids": [1, 2, 3],
  "top_complaint": "典型中文原话或摘要"
}
```

校验规则：

- `affected_products ⊆ allowed_products`
- `allowed_products` 按 `label_code` 从问题簇取；缺失时退到 snapshot 全量产品。
- `evidence_count >= len(evidence_review_ids)`。
- `source != evidence_insufficient` 时必须有证据 ID 或典型原话。

### 4.2 `issue_diagnostics`

来源：

- `self.top_negative_clusters`
- `report_copy.improvement_priorities`
- `deep_analysis`
- `example_reviews.images`

字段：

```json
{
  "label_code": "structure_design",
  "label_display": "结构设计",
  "severity": "high",
  "evidence_count": 18,
  "affected_products": ["完整产品名"],
  "text_evidence": [],
  "image_evidence": [],
  "ai_recommendation": "优先展示 full_action，其次 actionable_summary",
  "failure_modes": [],
  "root_causes": [],
  "user_workarounds": []
}
```

兼容策略：

- `issue_cards` 继续存在。
- `issue_cards.recommendation` 改为读取 `full_action` 或 `ai_recommendation`。
- HTML 诊断卡先读 `card.image_evidence`、`card.ai_recommendation`、`card.failure_modes` 等字段。

### 4.3 `heatmap`

P0 不改变热力图的主体布局，但修正分数解释和下钻。

字段补充：

```json
{
  "metric_name": "体验健康度",
  "formula": "(positive + 0.5 * mixed) / sample_size",
  "x_labels": [],
  "y_items": [{"product_name": "完整产品名", "display_label": "短名"}],
  "z": [[{}]]
}
```

cell 字段：

```json
{
  "score": 0.75,
  "sample_size": 8,
  "positive_count": 5,
  "mixed_count": 2,
  "negative_count": 1,
  "neutral_count": 0,
  "color_class": "green",
  "top_review_id": 123,
  "top_review_excerpt": "用于解释当前颜色的代表评论",
  "tooltip": "体验健康度 75%：正向 5，混合 2，负向 1，样本 8"
}
```

选择代表评论的规则：

- 红色：优先负向评论。
- 黄色：优先 mixed 或边界评论。
- 绿色：优先正向评论；如 mixed 参与计分，tooltip 必须解释 mixed 数量。

### 4.4 `kpi_semantics`

P0 只补两个字段：

```json
{
  "high_risk_count": 2,
  "attention_product_count": 3,
  "risk_threshold": 35,
  "attention_rule": "red + yellow status_lamp"
}
```

HTML、邮件、Excel 后续展示“高风险”和“需关注”时必须使用这两个字段，避免模板自行计算。

### 4.5 `delivery`

P0 先不改用户邮件正文，只修内部状态：

```json
{
  "report_generated": true,
  "email_delivered": true,
  "workflow_notification_delivered": false,
  "deadletter_count": 3
}
```

在 DB 层优先复用：

- `workflow_runs.report_phase='full_sent'`：本地生成且外部通知未发现 deadletter。
- `workflow_runs.report_phase='full_sent_local'`：本地生成成功，但 outbox 有 deadletter。

---

## 5. 数据流

### 5.1 Full report 生成

1. `report_snapshot.py` 生成 snapshot。
2. `report_analytics.py` 生成 analytics。
3. `report_common.normalize_deep_report_analytics()` 归一化 KPI、问题簇、诊断卡。
4. `report_llm.generate_report_insights_with_validation()` 生成或 fallback 行动建议。
5. `report_snapshot.py` 合并 `deep_analysis`。
6. 重新构建轻量 `report_user_contract`。
7. Excel / HTML / 邮件优先读取 contract 或同步后的兼容字段。

### 5.2 HTML 渲染

1. `report_html._annotate_reviews()` 用 `date_published_parsed` 标注近 30 天。
2. 诊断卡显示图片证据、AI 建议、失效模式、根因。
3. 热力图使用完整产品名做 `data-product`，短名只用于显示。
4. tooltip 显示分数组成，不只显示单条评论。

### 5.3 Excel 生成

1. “现在该做什么”读取 `action_priorities` 或同步后的 `report_copy.improvement_priorities`。
2. “竞品启示”短板行保留并优先展示 `headline_cn/body_cn`。
3. “评论原文”继续作为证据全文承载，不在 P0 中改结构。

### 5.4 Workflow 状态

1. `NotificationWorker` 或 `WorkflowWorker` 检测 deadletter。
2. completed run 也能被 delivery reconcile 扫描。
3. 有 deadletter 时把 `full_sent` 降级到 `full_sent_local`。

---

## 6. 文件边界

| 文件 | P0 责任 |
|---|---|
| `qbu_crawler/server/report_llm.py` | 修正 `affected_products` 校验边界，支持按 label 的 allowed products |
| `qbu_crawler/server/report_analytics.py` | fallback priorities 差异化、保留竞品中文字段、热力图 cell 增强 |
| `qbu_crawler/server/report_common.py` | 生成轻量 `report_user_contract`，同步 issue card 推荐、图片和 deep analysis 字段 |
| `qbu_crawler/server/report_snapshot.py` | 在 LLM / fallback / deep analysis 合并后刷新 contract |
| `qbu_crawler/server/report_html.py` | 近 30 天标注改用 `date_published_parsed` |
| `qbu_crawler/server/report.py` | Excel 优先消费中文竞品字段和证据化 action priorities |
| `qbu_crawler/server/report_templates/daily_report_v3.html.j2` | 诊断卡展示图片和 AI 建议；热力图完整产品名下钻 |
| `qbu_crawler/server/report_templates/daily_report_v3.js` | 热力图点击筛选保持完整产品名和 label 过滤 |
| `qbu_crawler/server/report_templates/email_full.html.j2` | 使用统一需关注产品字段 |
| `qbu_crawler/server/workflows.py` | completed run 的 delivery deadletter reconcile |
| `qbu_crawler/server/notifier.py` | 提供可复用 deadletter 统计/降级入口 |

---

## 7. 测试策略

P0 必须先写失败测试，再改实现。

### 7.1 单元测试

- LLM 校验允许问题簇产品，不允许未知产品。
- fallback priorities 不允许所有 `full_action` 完全相同。
- issue cards 能使用 `full_action`、图片证据和 deep analysis。
- heatmap cell 输出分数组成和解释性 tooltip。
- negative opportunities 保留中文字段。
- `_annotate_reviews()` 优先 `date_published_parsed`。
- high risk / attention count 分离。
- completed run 有 deadletter 时可降级。

### 7.2 渲染测试

- HTML 诊断卡出现图片证据区域。
- HTML 诊断卡出现 AI 建议或 deep analysis 摘要。
- heatmap cell 的 `data-product` 是完整产品名。
- 全景近 30 天筛选能命中 parsed 日期评论。
- 邮件“需关注产品”使用统一字段。

### 7.3 Excel 测试

- “现在该做什么”中改良方向不全相同。
- “现在该做什么”有典型原话或证据 ID。
- “竞品启示”短板行优先中文。

### 7.4 Replay 测试

P0 可以先用小型 fixture，不必把测试7 2MB JSON 全量纳入仓库。若后续允许增加 fixture，再补 artifact replay。

---

## 8. 验收标准

- LLM v3 不再因为“问题簇产品不在 risk_products”而失败。
- 测试7同类数据下，“改良方向”至少按 label 差异化。
- 诊断卡能展示已有图片证据和 AI 深度摘要。
- 热力图 tooltip 解释分数组成，点击单元格能筛中完整产品。
- KPI 近 30 天数量与全景筛选一致。
- Excel 竞品短板评论优先中文。
- HTML / 邮件不再让用户混淆高风险产品和需关注产品。
- outbox deadletter 存在时，workflow 不再停留在纯 `full_sent`。

---

## 9. 风险与取舍

- 轻量 contract 会与旧字段短期共存，存在双写风险；P0 要通过测试保证同步。
- heatmap mixed 权重如果改为 0.5，历史截图颜色可能变化；这是更符合用户解释的产品选择，需要在 tooltip 中明确。
- completed run reconcile 如果扫描范围过大可能有性能成本；P0 可限制最近 N 天或 `report_phase='full_sent'` 的 run。
- 不新增 DB migration 会限制 delivery 状态表达粒度；P0 先复用 `full_sent_local`，P1 再考虑独立字段。

---

## 10. 后续

本设计完成后，进入实施计划：

`docs/superpowers/plans/2026-04-28-test7-report-p0-contract-remediation.md`

实施计划只覆盖 P0，不包含 P1/P2/P3 的完整重构。
