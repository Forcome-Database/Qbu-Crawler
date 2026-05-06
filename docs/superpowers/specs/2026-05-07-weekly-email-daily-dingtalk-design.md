# 每周邮件与每日钉钉摘要设计

**日期**: 2026-05-07
**状态**: 已确认方向，待实施
**范围**: daily workflow 的业务通知频率、周报邮件语义、钉钉日报摘要、报告窗口命名
**改动级别**: 中等，不取消每日采集，不新增站点采集逻辑

---

## 1. 背景

当前系统每天运行 daily workflow，并在报告链路完成后发送业务邮件。测试和生产使用后确认：完整 HTML / Excel 每天发到邮箱太频繁，邮件适合沉淀为周报；但评论监控仍需要每天有轻量通知，避免错过新增差评、竞品好评或无新增状态。

本设计将通知层分成两类：

- 每日钉钉摘要：短、固定模板、带分析，只看当天窗口。
- 每周邮件报告：完整 HTML / Excel 附件，展示本周变化 + 累计全景。

每日采集、翻译、snapshot 冻结、analytics 本地产物仍保留，避免为了降低邮件频率而牺牲追溯能力。

---

## 2. 现状证据

### 2.1 调度与报告链路

- `qbu_crawler/server/workflows.py::submit_daily_run()` 每天创建 `workflow_runs.workflow_type='daily'`，并设置 `data_since/data_until`。
- `qbu_crawler/server/report_snapshot.py::freeze_report_snapshot()` 用 `report.query_report_data(data_since, until=data_until)` 冻结当天窗口，并在 `REPORT_PERSPECTIVE=dual` 下附加 `snapshot.cumulative`。
- `qbu_crawler/server/report_snapshot.py::generate_report_from_snapshot()` 按 full/change/quiet 三模式生成报告。
- `qbu_crawler/server/workflows.py::_should_send_workflow_email()` 目前总是返回 True，实际邮件节流只在 quiet 模式内部处理。
- full 模式只要当天有新增评论，就会走完整报告邮件。

### 2.2 钉钉通知链路

- `notification_outbox` 是通知事实来源。
- `qbu_crawler/server/notifier.py::OpenClawBridgeSender` 将 outbox payload 映射到 bridge template vars。
- `qbu_crawler/server/openclaw/bridge/app.py::DEFAULT_TEMPLATES` 当前模板偏流程状态：
  - `workflow_started`
  - `workflow_fast_report`
  - `workflow_full_report`
  - `workflow_attention`
- 当前 `workflow_fast_report` 只展示产品数、评论数、翻译进度，不承载业务判断。

### 2.3 数据字段能力

现有字段足够支撑每日摘要和周报窗口：

- `reviews.scraped_at`：本次入库时间，可做今日/本周窗口。
- `reviews.date_published_parsed/date_published`：评论发布时间，可做新近/补采解释。
- `products.ownership`：区分自有和竞品。
- `products.sku/name/site/url`：展示 SKU、产品、站点。
- `reviews.rating/headline/body/headline_cn/body_cn`：展示评分和原文/中文。
- `review_analysis.sentiment/labels/features/insight_cn/impact_category/failure_mode`：生成“问题/亮点/分析”。
- `workflow_runs.report_mode/email_delivery_status/workflow_notification_status`：表达 full/change/quiet 和邮件/通知状态。

不需要为第一版新增业务表。若后续要记录“某周已发邮件”或支持补发审计，可新增专门字段或 outbox kind 的 dedupe key 约束。

---

## 3. 设计目标

### 3.1 目标

- 首次运行仍发送全量邮件，建立监控基线。
- 后续邮件默认每周发送一次。
- 每天任务完成后都向钉钉发送业务摘要。
- 有新增评论时，钉钉摘要包含自有 TOP3、竞品 TOP3 和分析。
- 无新增评论时，钉钉摘要显示“今日无新增评论”，并可补充是否有产品状态变化。
- 周报邮件正文和 HTML tab 将“今日变化”调整为“本周变化”。
- 所有分析必须来自当天/本周窗口内真实评论和现有标签/LLM 分析，不扩大事实。
- 每日钉钉摘要与每周邮件都必须区分窗口数据和累计数据。

### 3.2 非目标

- 不取消每日采集。
- 不取消每日本地产物生成。
- 不把 daily workflow 改成 weekly workflow。
- 不新增站点 scraper 行为。
- 不让 LLM 自行编造不存在的 SKU、评论、标签或数量。
- 不把运维质量告警混进业务钉钉摘要；运维异常仍走独立技术通知和 run log。

---

## 4. 推荐架构

采用“每日采集 + 每日钉钉业务摘要 + 每周邮件报告”。

### 4.1 每日采集不变

daily scheduler 仍每天触发。每个 run 继续：

1. 提交采集任务。
2. 等待任务完成和翻译。
3. 冻结当天 snapshot。
4. 生成本地 analytics / HTML / Excel。
5. 入 outbox 发钉钉业务摘要。
6. 仅在邮件策略允许时发送业务邮件。

### 4.2 邮件策略

新增集中策略函数，例如：

`should_send_business_email(run, snapshot, mode, previous_context) -> (bool, reason, cadence)`

规则：

- 首次可报告 run：发送邮件，`cadence=bootstrap`。首次判断必须基于历史已完成报告上下文，不能依赖 `run_id == 1`。
- 每周固定一天发送邮件，默认周一或可配置 `REPORT_WEEKLY_EMAIL_WEEKDAY`。
- 手动补发或显式参数可绕过策略。
- 非周报日：仍生成本地产物，但 `send_email=False`，`email_delivery_status=skipped`，reason 标为 `weekly_cadence_skip`。
- quiet/change/full 都受同一邮件策略约束，避免 full 模式继续每天发。
- 周报日即使当天无新增评论并进入 quiet 模式，也必须发送周报邮件；旧 `should_send_quiet_email()` 只能在 legacy/daily cadence 下生效，不能拦截 weekly cadence。

推荐新增配置：

```env
REPORT_EMAIL_CADENCE=weekly
REPORT_WEEKLY_EMAIL_WEEKDAY=1
REPORT_WEEKLY_WINDOW_DAYS=7
REPORT_EMAIL_SEND_BOOTSTRAP=true
```

`REPORT_WEEKLY_EMAIL_WEEKDAY` 建议用 ISO weekday：1=周一，7=周日。若你希望周五收周报，配置 5。

### 4.3 周报窗口

周报不是取消 daily snapshot，而是在周报日生成报告时把窗口从一天扩展成近 7 天。

推荐做法：

- daily run 仍有当天 `data_since/data_until`。
- 周报生成时构造一个 weekly snapshot：
  - `data_since = data_until - 7 days`
  - `data_until = 当前 run.data_until`
  - `reviews = 最近 7 天入库评论`
  - `products = 最近 7 天有刷新或有关联评论的产品`，其中“有关联评论”必须按窗口内 reviews 反查产品，不能只依赖 `products.scraped_at`
  - `cumulative = 全量产品 + 全量评论`
  - `report_window = {"type": "weekly", "label": "本周", "days": 7}`
- HTML / Excel / 邮件消费 weekly snapshot。

这样可以让“本周变化”真的基于 7 天评论，而不是只把今日文案改名。

### 4.4 钉钉每日摘要

新增业务通知 kind：

`workflow_daily_digest`

payload 建议包含：

```json
{
  "run_id": 30,
  "logical_date": "2026-05-07",
  "new_review_count": 5,
  "own_new_count": 3,
  "own_negative_count": 2,
  "competitor_new_count": 2,
  "competitor_positive_count": 1,
  "own_top": [],
  "competitor_top": [],
  "analysis": "..."
}
```

TOP 选择规则：

- 自有 TOP3：
  - 优先 `rating <= NEGATIVE_THRESHOLD` 的差评。
  - 同分时优先高 severity 标签、最近入库、有中文分析的评论。
  - 若无差评，可展示低分/中性或“暂无自有差评”。
- 竞品 TOP3：
  - 优先 5 星或 sentiment=positive 的好评，用于借鉴。
  - 若无好评，再展示竞品差评作为机会点。
- 原文：
  - 优先展示中文 `body_cn`，并可附英文原文摘要。
  - 如果没有中文，展示 `body`。
- 问题/亮点：
  - 优先 `analysis_labels[0].code` 映射中文标签。
  - fallback 到 `impact_category/failure_mode`。
  - 再 fallback 到 headline。
- 分析：
  - 优先 `review_analysis.insight_cn`。
  - 若缺失，规则化生成一句分析，不调用 LLM 编造。

### 4.5 无新增评论通知

当 `snapshot.reviews_count == 0`：

```md
## QBU 今日评论监控 · 2026-05-07

今日无新增评论。

当前累计样本：自有 X 条 / 竞品 Y 条。
如有价格、库存、评分变化，会在本周邮件报告中汇总。
```

如果当天有 price/stock/rating 变化，可加一行：

`检测到产品状态变化 N 项，已纳入本周变化跟踪。`

---

## 5. 邮件正文调整

### 5.1 标题

首次：

`QBU 评论分析基线 · 2026-05-07`

周报：

`QBU 网评周报 · 2026-05-01 至 2026-05-07`

### 5.2 正文结构

周报邮件正文建议：

1. 本周概览
   - 本周新增评论
   - 自有新增差评
   - 竞品新增好评
   - 本周需关注产品
2. 关键判断
   - 只引用本周窗口事实和累计健康事实。
3. TOP 3 行动建议
   - evidence_review_ids 必须来自本周或累计已存在评论。
4. 累计健康快照
   - 累计自有/竞品评论、健康指数、差评率。
5. 附件说明
   - HTML 看全景/趋势/问题诊断。
   - Excel 看明细和证据评论。

### 5.3 HTML 标题

当前 `daily_report_v3.html.j2` 中 tab 文案为“今日变化”。需要由 `report_window` 驱动：

- `report_window.type == "daily"`：今日变化
- `report_window.type == "weekly"`：本周变化
- `bootstrap`：监控起点

周报里“本周变化”看 7 天窗口；“全景数据”仍看累计数据。

---

## 6. 状态与审计

### 6.1 workflow_runs

不强制新增字段。第一版可通过现有字段表达：

- `report_mode`: full/change/quiet
- `email_delivery_status`: sent/skipped/failed
- `workflow_notification_status`: sent/pending/deadletter
- `delivery_last_error`: 记录邮件跳过原因或失败原因

可选增强：

- 新增 `report_cadence`：daily/weekly/bootstrap
- 新增 `report_window_type`：daily/weekly

第一版建议不加，先减少迁移风险。

### 6.2 notification_outbox

新增 kind：

- `workflow_daily_digest`

dedupe key：

- `workflow:{run_id}:daily-digest`

周报邮件不需要单独 notification kind，但 full report 钉钉状态消息需要把“业务邮件：已发送/已跳过（周报频率）”说清楚。

`workflow_daily_digest` 是业务摘要通知，不应污染完整报告送达状态。若 daily digest 进入 deadletter，只能进入独立通知/运维观测，不应触发 `workflow_runs.report_phase` 从 `full_sent` 降级到 `full_sent_local`。

---

## 7. 影响面

### 需要修改

- `qbu_crawler/config.py`
  - 新增邮件频率和周报窗口配置。
- `qbu_crawler/server/workflows.py`
  - full_pending 阶段调用邮件策略。
  - 在 snapshot 冻结后或 report 完成后 enqueue `workflow_daily_digest`。
  - `workflow_fast_report` 可保留为内部状态，也可以降级为不发送。
- `qbu_crawler/server/report_snapshot.py`
  - 增加 weekly snapshot 构建或 report window 注入。
  - `generate_report_from_snapshot()` 支持 weekly window。
- `qbu_crawler/server/report.py`
  - 复用 `query_report_data(since, until)` 查询周窗口。
  - 周窗口产品查询需要补齐“窗口评论关联产品”。
  - 调整邮件 subject / body builder。
- `qbu_crawler/server/report_html.py`
  - 传入 `report_window` 给模板。
- `qbu_crawler/server/report_templates/daily_report_v3.html.j2`
  - “今日变化”改为窗口化标题。
- `qbu_crawler/server/report_templates/email_full.html.j2`
  - 周报邮件正文调整。
- `qbu_crawler/server/notifier.py`
  - 为 `workflow_daily_digest` 准备 template vars。
- `qbu_crawler/server/openclaw/bridge/app.py`
  - 新增 `workflow_daily_digest` 钉钉模板。

### 需要新增

- `qbu_crawler/server/daily_digest.py`
  - 构建钉钉摘要 payload。
  - TOP3 选择和 deterministic 分析。
- `tests/server/test_weekly_email_cadence.py`
- `tests/server/test_daily_dingtalk_digest.py`
- `tests/server/test_weekly_report_window.py`

### 需要更新文档

- `AGENTS.md`
- `.env.example`
- `docs/devlogs/D030-weekly-email-daily-dingtalk.md`

---

## 8. 验收标准

1. 首次 run 发送全量邮件。
2. 非周报日有新增评论：不发业务邮件，发钉钉每日摘要。
3. 非周报日无新增评论：不发业务邮件，发“今日无新增评论”钉钉摘要。
4. 周报日：发送邮件，邮件标题和正文使用“本周”语义。
5. 周报 HTML 中 tab 为“本周变化”，不是“今日变化”。
6. 周报窗口评论数等于近 7 天入库评论数。
7. 周报全景数据仍等于累计评论数。
8. 钉钉 TOP3 中展示的 SKU、评分、原文、问题和分析均来自真实 DB/snapshot 字段。
9. 运维质量告警仍走独立通知，不进入业务摘要。
10. 原有 full/change/quiet 本地产物生成能力不回退。

---

## 9. 风险与缓解

- 风险：周报窗口和累计窗口再次混淆。
  - 缓解：引入 `report_window`，模板只通过该字段决定“今日/本周”文案；全景继续消费 `snapshot.cumulative`。
- 风险：钉钉摘要过长。
  - 缓解：TOP3 每条限制原文长度，最多自有 3 条 + 竞品 3 条。
- 风险：当天评论未翻译完成时摘要空白。
  - 缓解：优先中文，缺失时用英文原文；分析用现有标签 deterministic fallback。
- 风险：weekly snapshot 改动影响日报。
  - 缓解：daily snapshot 冻结语义不变，weekly 仅在邮件生成入口构造派生 snapshot。
- 风险：已有 tests 认为 quiet 前 3 天发邮件。
  - 缓解：用新配置默认 weekly 覆盖旧 quiet 节流，保留旧函数兼容或改测试明确新策略。
- 风险：每日业务摘要 deadletter 被现有 workflow 通知状态同步当成完整报告通知失败。
  - 缓解：状态同步和 deadletter 降级只统计完整报告相关通知，`workflow_daily_digest` 单独观测。
- 风险：实施计划里的模拟命令与脚本参数漂移。
  - 缓解：模拟命令必须使用当前脚本真实参数，或先把脚本参数扩展纳入实现。
