# TOOLS.md

## Purpose

本文件只负责 3 类内容：

- MCP 工具速查
- 对外输出契约
- 常用查询、状态与分析回复模板

不要把路由逻辑、支持矩阵、ownership 判断、reply_to 规则、运行时真值说明写回这里；这些分别归 `AGENTS.md` 或 MCP contract / spec。

## Supported Sites

- `www.basspro.com`
- `www.meatyourmaker.com`
- `www.waltons.com`
- `waltons.com`

## Task Submission Tools

- `start_scrape(urls, ownership, review_limit=0, reply_to)`
- `start_collect(category_url, ownership, max_pages=0, review_limit=0, reply_to="")`

参数真值、支持边界和运行时真值说明以 MCP server contract 为准；本文件只保留工具名和用户可见输出模板。

## Workflow and Notification Inspection

- `get_workflow_status(run_id | trigger_key)`
- `list_workflow_runs(status="", limit=20)`
- `list_pending_notifications(status="", limit=20)`

关键状态：

- workflow `status`
  - `submitted`
  - `running`
  - `reporting`
  - `completed`
  - `failed`
  - `needs_attention`
- workflow `report_phase`
  - `none`
  - `fast_pending`
  - `fast_sent`
  - `full_pending`
  - `full_sent`
  - `full_sent_local`
- workflow `report_generation_status`
  - `unknown`
  - `pending`
  - `generated`
  - `failed`
  - `skipped`
- workflow `email_delivery_status`
  - `unknown`
  - `pending`
  - `sent`
  - `failed`
  - `skipped`
- workflow `workflow_notification_status`
  - `unknown`
  - `pending`
  - `sent`
  - `deadletter`
  - `partial`
  - `skipped`
- notification `status`
  - `pending`
  - `claimed`
  - `failed`
  - `sent`
  - `deadletter`

解释规则：

- `task execution status`
- `notification delivery status`
- `report generation status`

这三类必须拆开说，不要混成一句“已经完成”。

补充语义：

- `report_generation_status` 只表示本地报告产物是否生成。
- `email_delivery_status` 只表示业务日报邮件是否送达。
- `workflow_notification_status` 只表示 workflow 外部通知是否送达。
- `full_sent_local + workflow_notification_status=deadletter` 是本地报告/业务邮件可成功、外部通知失败的降级态，不等于业务日报失败。

## Data and Report Tools

- `list_products`
- `get_product_detail`
- `query_reviews`
- `get_price_history`
- `get_stats`
- `execute_sql`
- `generate_report(since, send_email="true")`
- `trigger_translate()`
- `get_translate_status()`

For ad-hoc email/report requests:

- Prefer `preview_scope` first when the request spans multiple products, URLs, or filters.
- Then use `send_filtered_report`.
- `scope.products` may use `ids`, `urls`, `skus`, `names`, `sites`, `ownership`, `price`, `rating`, and `review_count`.
- `delivery.subject` may override the default legacy email subject for one-off emails.

### Single-product artifact flow

- Once a product has already been confirmed by `get_product_detail`, the later report scope must stay locked to the same explicit `url` or `sku`.
- Do not widen the scope back to `name`, `site`, `ownership`, or other broader selectors after the single product is known.
- If preview comes back with more than 1 product, treat that as scope drift and fix the scope first; do not continue to `send_filtered_report`.

### 报告模式说明（P006+P007）

`get_workflow_status` 返回的 `report_mode` 字段：
- `full` — 有新评论，完整分析已生成
- `change` — 无新评论但有价格/库存变动
- `quiet` — 无变化，静默日
- `skipped` — 旧模式（已废弃，P006 后不再出现）

`REPORT_PERSPECTIVE` 环境变量控制分析视角：
- `dual` — 累积全景 + 增量双视角（默认）
- `window` — 仅当日窗口

邮件发送规则：
- full/change：始终发送
- quiet：前 3 天每天发（`REPORT_QUIET_EMAIL_DAYS` 可配），之后每周发一次

## Output Contract

### Basic Principles

- 不向用户展示 JSON、SQL、原始 tool schema、部署细节
- 优先用简洁业务中文输出，产品名可保留英文原文
- 关键数字加粗
- 用列表替代表格
- 时间统一按上海时间表述
- 先给结论，再给证据，再给下一步建议
- 默认一问一答只产出一条最终回复
- 用户追问“你是怎么查的”时，只能复述本轮真实调用过的工具和依据，不得补写未执行过的 SQL 或查询步骤
- 默认“评论数”口径指已入库 `reviews` 行数；如果引用站点页面展示的评论总数，必须显式写成“站点展示评论总数”

### Canonical Metric Wording

- `product_count`：产品数
- `ingested_review_rows`：已入库评论数
- `site_reported_review_total_current`：站点展示评论总数
- `matched_review_product_count`：命中评论产品数
- `image_review_rows`：带图评论数
- `preview_scope.counts.products` 只是兼容旧展示的别名；一旦涉及评论过滤，分析和解释优先显式使用 `product_count` 与 `matched_review_product_count`

### User Phrasing → Canonical Mapping

- "评论数 / 多少条评论 / 评论有多少" → `ingested_review_rows`（默认口径）
- "页面上写的评论数 / 站点显示的" → `site_reported_review_total_current`（需显式标注）
- "有多少产品 / 产品数" → `product_count`
- "带图的 / 有图评论" → `image_review_rows`
- "差评 / 低分 / 吐槽" → 不是单独 metric，是 `max_rating=2` 的筛选条件
- "好评率" → 需 `execute_sql` 计算，基础工具不直接提供
- 歧义时默认走 `ingested_review_rows`

### Canonical Time Wording

- `product_state_time`：最近更新时间
- `review_ingest_time`：最近抓取时间 / 按抓取时间
- `review_publish_time`：站点发布时间 / 按发布时间，优先使用 `date_published_parsed`
- 任何带时间窗的结论，一旦不是显然的当前态概览，就要把时间轴名字说出来，不能只说“最近”

### Style Preference

- 可保留少量 icon 作为版块提示
- icon 只用于增强扫读，不堆砌
- 标题 + 列表 + 分隔线优先
- 适配钉钉 Markdown，可读性优先

### Status Semantics

- “已提交”只表示进入系统
- “处理中”只表示仍在执行
- “已完成”只表示任务或 workflow 执行结束
- “已通知”只表示 outbox 或 delivery 明确成功
- “已发送邮件”只表示 email 结果明确成功

### Forbidden

- 不要把工具原始错误原样抛给用户
- 不要把 `pending` 说成成功
- 不要在未确认时说“已经发到钉钉”或“邮件已发送”
- 不要在最终回复后追加原始工具结果或重复摘要
- 不要用 Markdown 表格

## Display Budget

除非用户明确要求全量展开，否则默认：

- 产品列表：最多 5 个
- 评论样本：最多 3 条
- 差评样本：最多 5 条
- workflow / notification 明细：最多 5 条
- 结果很多时先摘要，再询问是否继续展开

## When to Summarize vs Expand

- 用户问“有哪些 / 看下 / 概览 / 最近抓了什么”
  - 默认摘要 + 样本
- 用户明确说“全部 / 全量 / 完整清单”
  - 再展开
- 用户目标是判断或决策
  - 优先结论，不先堆明细

## Routing-Aware Output Guidance

### Exact inspect ask

如果这轮只有 `needs_data_read=yes`，而且问题是精确查询：

- 直接给精确结果
- 不附带样本、推断、排名、建议
- 典型例子：
  - “库里有多少产品”
  - “库里有多少评论”
  - “最近更新的是谁”

### Analysis ask

如果是 `needs_data_read=yes` 且 `needs_judgment=yes`：

- 输出顺序保持：
  - 结论
  - 证据
  - 解读
  - 建议
- 明确 metric 口径和 time axis
- 不把样本误写成结论

### Composite ask

如果是 `needs_data_read + needs_judgment + needs_artifact` 的复合 ask：

- 先给 preview / scope / 风险说明
- 再等确认
- 最后再给 artifact 结果
- 不要把 preview、分析、交付结果揉成一段

### Unsupported-nearby produce ask

如果用户要的动作和已支持能力很接近，但仍然不在当前 dedicated tool 范围内：

- 明确说当前不支持该动作
- 给最近替代方案
- 不要输出“像是快成功了”的措辞

## Standard Templates

### Task Submitted

```md
## 🚀 已接收任务

- **目标**：{target_summary}
- **归属**：{ownership}
- **任务类型**：{scrape_or_collect}
- **当前阶段**：已入队，开始抓取后会继续反馈

完成后会继续反馈：
- 是否已入库或已刷新
- 是否发现新评论
- 如有需要，可继续做差评总结、价格变化或邮件报告
```

### Task Progress

```md
## ⏳ 任务进度

- **任务 ID**：{task_id}
- **执行状态**：{status}
- **当前进度**：{progress_summary}
- **已完成**：{done_count}
- **失败**：{failed_count}

如需，我可以继续跟进直到完成。
```

### Task Completed

```md
## ✅ 抓取完成

- **目标**：{target_summary}
- **站点**：{site}
- **归属**：{ownership}
- **任务类型**：{scrape_or_collect}
- **结果**：{result_summary}

### 本次产出
- **产品记录**：{product_count}
- **新增评论**：{review_count}
- **失败项**：{failed_summary}

- **任务 ID**：{task_id}

如需，我可以继续做差评总结、价格变化或邮件报告。
```

### Workflow Status

```md
## 🔄 Workflow 状态

- **workflow**：{run_id_or_trigger_key}
- **执行状态**：{workflow_status}
- **报告阶段**：{report_phase}
- **报告产物**：{report_generation_status}
- **业务邮件**：{email_delivery_status}
- **workflow 通知**：{workflow_notification_status}
- **关联任务数**：{task_count}
- **开始时间**：{started_at}
- **结束时间**：{finished_at}

### 说明

- {workflow_takeaway}
```

### Notification Anomaly

```md
## ⚠️ 通知投递异常

- **记录数**：{notification_count}
- **主要状态**：{status_summary}

### 异常项

- **{kind_1}**：{status_1}（{error_1}）
- **{kind_2}**：{status_2}（{error_2}）

### 影响

- {impact_summary}

### 下一步建议

- {next_step_1}
- {next_step_2}
```

### Product Detail

```md
## 📦 产品详情

### {product_name}

- **SKU**：{sku}
- **价格**：{price}
- **评分**：{rating}/5
- **站点展示评论总数**：{review_count}
- **库存**：{stock_status}
- **站点**：{site}
- **归属**：{ownership}
- **最近更新时间**：{updated_at}

### 重点结论

- {key_takeaway_1}
- {key_takeaway_2}
```

### Product List / Search Result

```md
## 📋 搜索结果

- **命中产品数**：{total}
- **当前视图**：展示前 {shown_count} 个

### 样本产品

1. **{product_name_1}**
   - 站点：{site_1}
   - 归属：{ownership_1}
   - 价格：{price_1}
   - 评分：{rating_1}
   - 站点展示评论总数：{review_count_1}

2. **{product_name_2}**
   - 站点：{site_2}
   - 归属：{ownership_2}
   - 价格：{price_2}
   - 评分：{rating_2}
   - 站点展示评论总数：{review_count_2}

如需，我可以继续展开其余结果，或按站点 / 归属 / 价格区间继续筛选。
```

### Data Overview

```md
## 📊 数据概览

- **产品总数**：{product_count}
- **已入库评论数**：{review_count}
- **平均价格**：{avg_price}
- **平均评分**：{avg_rating}
- **最后更新**：{last_updated}

### 分布

- **自有产品**：{own_count}
- **竞品**：{competitor_count}
- **Bass Pro**：{basspro_count}
- **Meat Your Maker**：{mym_count}
- **Walton's**：{waltons_count}
```

### Data Overview + Sample Products

```md
## 📊 数据概览

- **产品总数**：{product_count}
- **已入库评论数**：{review_count}
- **平均价格**：{avg_price}
- **平均评分**：{avg_rating}

### 样本产品

1. **{product_name_1}** · {site_1} · {ownership_1} · {price_1} · {rating_1} · 站点展示评论 {review_count_1}
2. **{product_name_2}** · {site_2} · {ownership_2} · {price_2} · {rating_2} · 站点展示评论 {review_count_2}
3. **{product_name_3}** · {site_3} · {ownership_3} · {price_3} · {rating_3} · 站点展示评论 {review_count_3}

如需完整清单，我可以继续展开。
```

### Review Result / Negative Samples

```md
## 💬 评论结果

- **命中评论数**：{total}
- **当前视图**：展示前 {shown_count} 条

### 评论样本

1. **{product_name_1}** · {rating_1}/5 · {author_1}
   - {headline_or_preview_1}

2. **{product_name_2}** · {rating_2}/5 · {author_2}
   - {headline_or_preview_2}

如需，我可以继续按关键词、评分段或站点展开。
```

### Scope Preview

```md
## 🔎 范围预览

- **命中产品数**：{product_count}
- **命中评论数**：{review_count}
- **带图评论数**：{image_review_count}
- **下一步建议**：{next_action_hint}

### 说明

- 如需区分“当前产品 scope 总量”和“被评论条件缩小后的产品数”，必须显式写出 `product_count` 与 `matched_review_product_count`
- {preview_summary}
```

### Filtered Report Preview

```md
## 📄 报告预览

- **目标范围**：{scope_summary}
- **预计命中产品**：{product_count}
- **预计命中评论**：{review_count}
- **交付方式**：{delivery_summary}

### 风险或限制

- {constraint_1}
- {constraint_2}
```

### Report Delivery Result

```md
## ✅ 报告处理结果

- **范围**：{scope_summary}
- **产品数**：{product_count}
- **命中评论数**：{review_count}
- **附件结果**：{artifact_status}
- **邮件结果**：{email_status}

### 说明

- {delivery_takeaway}
```

### Unsupported Produce Request

```md
## ℹ️ 当前还不支持这个动作

- **请求类型**：{request_type}
- **原因**：{unsupported_reason}

### 目前可行的替代方案

- {alternative_1}
- {alternative_2}
```

### Empty Result

当查询返回 0 条结果时：

- 说明查询条件（"按 SKU=XXX 查询"）
- 给出可能原因（1-2 条，不超过 2 句）
- 给出建议（放宽条件 / 确认拼写 / 先抓取）
- 保持 2-3 句，不展开成完整模板填充

### Rating Distribution

```md
## ⭐ 评分分布

- **5 星**：{star_5_count}（{star_5_pct}%）
- **4 星**：{star_4_count}（{star_4_pct}%）
- **3 星**：{star_3_count}（{star_3_pct}%）
- **2 星**：{star_2_count}（{star_2_pct}%）
- **1 星**：{star_1_count}（{star_1_pct}%）

### 解读

- {distribution_takeaway}
```

### Negative Review Analysis

```md
## 🔍 差评分析

### 核心问题

- **问题 1**：{issue_1}
- **问题 2**：{issue_2}

### 影响判断

- {impact_summary}

### 建议动作

- {action_1}
- {action_2}
```

### Competitive Comparison

```md
## 🆚 竞品对比

### 自有产品

- **产品数**：{own_product_count}
- **平均价格**：{own_avg_price}
- **平均评分**：{own_avg_rating}
- **站点展示评论总数**：{own_review_count}

### 竞品

- **产品数**：{competitor_product_count}
- **平均价格**：{competitor_avg_price}
- **平均评分**：{competitor_avg_rating}
- **站点展示评论总数**：{competitor_review_count}

### 结论

- {comparison_takeaway_1}
- {comparison_takeaway_2}
```

## Runtime Output Guardrail

运行时模板必须保持：

- 简单查询先给精确结论，不把样本和推断混进去
- 需要样本时再展示有限样本，不全量倾倒
- 评论相关字段必须使用明确口径，不再回到泛化“评论数”
- 方法说明只能引用真实工具调用，不补写不存在的 SQL 或流程
