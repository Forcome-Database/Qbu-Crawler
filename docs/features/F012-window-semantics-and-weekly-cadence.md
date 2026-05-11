# F012 窗口语义重建 · 周一无条件汇报 · 需求设计文档

- **创建日期**：2026-05-11
- **作者**：Claude Code（基于 5/11 周报换皮事件审计）
- **关联事件**：5/8 bootstrap → 5/11 周报正文与 bootstrap 几乎一字不差
- **关联代码**：`report_snapshot.py:1013-1051` / `report_snapshot.py:625-770` / `report_cadence.py` / `workflows.py:744-907`
- **状态**：v1.0 草稿，待评审
- **目标 Release**：`qbu-crawler 0.5.0`

---

## 1. 背景与现状

### 1.1 触发事件

2026-05-11（周一）业务收件人收到的"产品评论周报"邮件正文：
- 标题数字"本周新增 +2594"，等于数据库累计评论数（实际本周仅 3 条新增）
- 5 条 Voice of Customer 引用、12 款"需关注产品"、Top3 行动建议、健康指数 94.9%——与 5/8 监控起点 bootstrap 邮件几乎一字不差
- 业务方阅读体验：「报告没刷新？为什么和上次一样？」

### 1.2 三层根因

**根因 A：`scraped_at` 被当作"评论新出现的时间"使用**
- DB 中 `reviews.scraped_at` 实际语义是"我们这次抓到这条评论的入库时间戳"
- bootstrap 当天爬虫一次性把目标产品的全部历史评论入库，2592 条 `scraped_at` 全等于 2026-05-08
- 后续 7 天内，任何按 `scraped_at >= today-7d` 过滤的"窗口"都会把 bootstrap 那批评论计入"本周新增"
- 影响范围：`build_windowed_report_snapshot`、`query_report_data(since, until)`、`_scraped_at_in_window`（紧急关注信号）、MCP `query_reviews`/`execute_sql` 的"最近 N 天"模板

**根因 B：周一"必发"逻辑藏在 quiet 子函数内、是隐式补丁**
- `report_snapshot.py:1365-1367` 在 quiet 处理函数里加了一行：当 `snapshot.report_window.type == "weekly"` 时强制覆盖 `should_send_quiet_email` 的频率门
- 该补丁仅覆盖 quiet 路径；change/full 路径分别走自己的发送条件分支
- 触发依赖于 `cadence == "weekly"` 且 `decide_business_email` 返回 `report_window_type == "weekly"`，配置切换或 bootstrap 路径下静默失效
- `should_send_quiet_email` 的"前 3 天连发，第 7/14 天发一次"算法是 daily cadence 时代的兜底逻辑，与 weekly cadence 语义不匹配

**根因 C：weekly 模式复用了 quiet/change 简版模板**
- `quiet_day_report.html.j2` 设计目的是"今日没事，简短交代"
- 用它表达"周一汇报本周真实情况"：版面短、缺周维度净变化数字、缺累计快照展开、标题语气是"今日"
- 业务方在周一收到一封"今日无变化"的邮件无法对齐心理预期

### 1.3 不修的恶性后果时间线

```
5/8  bootstrap → reviews.scraped_at 全打到 5/8（2592 条）  ✓ 合理
5/11 周一 → window=[5/4, 5/12) 含 bootstrap 全部 → "本周新增 +2594" ❌ 已发生
5/15 下周一 → window=[5/8, 5/16) 仍含 bootstrap → 再来一封换皮邮件 ❌
5/22 再下周一 → window=[5/15, 5/23) 不含 bootstrap → "本周新增 +X" 突变到真实值 ❌ 业务方误判"采集挂了"，紧急工单
后续每加一个新 SKU/品类 → 该 SKU 历史评论一次性入库 → 重演灌水 ❌
后续任何故障恢复（如 Akamai 解封后补抓）→ 同样灌水 ❌
```

### 1.4 与 F011 的时间口径冲突

F011 §4.2.4.1 明确写过"`own_new_negative_reviews` 时间口径声明（按 `scraped_at`）"。本 feature 反转该口径，**作废 F011 §4.2.4.1**，时间口径改为 `first_seen_at`（per-product 基线，见 FR-1）。F011 文件顶部需追加 v1.3 修订记录指向本文档。

---

## 2. 目标

1. **修正窗口语义**：让"本周新增 / 本月新增 / 最近 N 天"准确反映"业务侧真实新出现的评论数"，与 bootstrap 入库批次解耦
2. **保证周一无条件汇报**：每周一无论评论是否新增、产品状态是否变动，业务方都能稳定收到一封"本周状态汇报"邮件
3. **统一周报视觉**：weekly 路径不再复用 quiet/change 简版，提供一份能在静默周与活跃周通用的"本周汇报"模板
4. **可观测**：当窗口被 baseline 截断、当窗口疑似被入库批次灌水时，运维能立即看到告警

## 3. 范围

### 3.1 In Scope

- `reviews` 表新增 `first_seen_at` 列，UPSERT 时只在 INSERT 路径写入；去重命中不更新
- `products` 表新增 `first_seen_at` 列，同样 INSERT 一次写入，UPSERT 不更新
- **per-product 基线语义**：评论 INSERT 时若所属 product 是同 logical_date 内首次入库（products.first_seen_at 与 review.scraped_at 落在同一 Shanghai 日历日）→ review.first_seen_at = NULL（视为该 product 的基线评论），否则 = scraped_at
- 历史数据回填：所有 `products.first_seen_at` 设为 NULL 的 product 下属的全部 `reviews.first_seen_at` 设为 NULL；其余按 `scraped_at` 回填
- 报告查询路径切换：所有"窗口/最近 N 天/新增"业务判定从 `scraped_at` 切到 `first_seen_at`，但**技术运维管道（translator、scrape quality）保持 scraped_at**（详见 FR-1.3 negative list 与 §3.3 字段语义分工矩阵）
- `workflow_runs` 新增 `baseline_logical_date` 字段，记录首次成功 `report_mode='full'` 的日期（仅作 collapsed 守卫与告警用，不再作为全局 NULL 回填的依据——回填已改为 per-product）
- 周一无条件发邮件的逻辑从 quiet 子函数提到 workflow 主干，统一为显式 `force_send` 决策
- 新模板 `weekly_briefing.html.j2`（或在现有 v3 模板中新增 weekly 分支），覆盖 full/change/quiet 三种数据状态下的周一邮件
- 兜底守卫：当窗口起点早于 baseline，自动收敛；当 `weekly_added > 0.7 * cumulative` 触发运维告警
- `daily_digest.py`（钉钉每日摘要）的代表评论排序与选取一并迁移到 `first_seen_at`（防止每天循环抽到同一批 bootstrap 评论）

### 3.2 Out of Scope

- 不重构 `scraped_at` 字段本身（保留作为"最后采集时间"语义）
- 不改 daily cadence 下的 quiet 频率算法（仍用 `should_send_quiet_email`）
- 不引入新的 KPI 指标，仅修正现有 KPI 的窗口口径
- 不改 product_snapshots 的写入策略（每日 INSERT，已正确）
- 不改翻译 worker 的窗口（`_count_pending_translations_for_window` 继续按 scraped_at 工作正确，详见 FR-1.3）
- 不修复 trend 图按 `COALESCE(date_published_parsed, scraped_at)` 时 fallback 到 scraped_at 引发的 bootstrap 当天虚假尖峰——该问题影响低、修复成本高，留待后续 F013/D013 处理

### 3.3 字段语义分工矩阵

| 用途 | 用 `scraped_at` | 用 `first_seen_at` |
|---|:---:|:---:|
| 翻译 worker 等待逻辑（`_count_pending_translations_for_window`） | ✓ | |
| 数据质量统计（`summarize_scrape_quality` / scrape_quality 告警分母） | ✓ | |
| 趋势图 x 轴 `COALESCE` fallback（F013 前保持现状） | ✓ | |
| 排序展示用次级 sort key（`report.py:723-735` 的 picker 次级排序、Excel 默认 ORDER BY） | ✓ | |
| 报告"本周/本月新增"窗口（`build_windowed_report_snapshot`、`query_report_data`） | | ✓ |
| MCP "最近 N 天"模板（`query_reviews`、`execute_sql`、`scope_window_clauses`） | | ✓ |
| 紧急关注信号窗口（`_scraped_at_in_window` → 改名 `_first_seen_in_window`） | | ✓ |
| Excel 中"窗口标识"列 | | ✓ |
| 钉钉每日摘要的代表评论选取与排序 | | ✓ |

> 任何新增查询路径必须按本矩阵分类决定字段，不得混用。

## 4. 需求清单

### FR-1 `first_seen_at` 字段语义（窗口口径修正）

**FR-1.1** `reviews.first_seen_at TIMESTAMP` 新增列（**per-product 基线**）
- products 表先 UPSERT，得到 `product.first_seen_at`（INSERT 分支才写入，UPSERT 不动）
- reviews INSERT 时：
  - 若 `date(product.first_seen_at, "Shanghai") == date(review.scraped_at, "Shanghai")`（即 product 是同 logical_date 内首次入库）→ `review.first_seen_at = NULL`（视为该 product 的基线评论）
  - 否则 → `review.first_seen_at = review.scraped_at`
- UPSERT 命中去重键路径：**不更新**该字段（保留首次值），SET 子句必须显式排除 first_seen_at
- 既有数据：默认 NULL；通过迁移脚本回填（见 FR-1.4）
- **设计动因**：解决"扩监控范围（加新 SKU）后再次灌水"——5/20 加新 SKU，当天 INSERT 的产品 first_seen_at=5/20，其下属一次性入库的全部历史评论都打 NULL，5/27 周报不会把它们算进"本周新增"

**FR-1.2** `products.first_seen_at TIMESTAMP` 新增列
- INSERT 分支：`first_seen_at = scraped_at`
- UPSERT 命中：不更新
- 解决"产品本周/本月新增"无法表达的现状（FR-1.1 也依赖该字段做 per-product 基线判定）

**FR-1.3** 报告查询统一改用 `first_seen_at`
- 切换清单（按文件）：
  - `report.py::query_report_data(since, until)`：reviews 与 products 的窗口过滤
  - `report.py::_legacy_query_report_data`：同上
  - `report_snapshot.py::_scraped_at_in_window` → 改名 `_first_seen_in_window`
  - `models.py::_scope_window_clauses` / `query_reviews` / `get_recent_reviews` / `models.py:1693, 2084` 等 reviews 的 N-days 查询
  - `daily_digest.py:104-123` 钉钉摘要排序与代表评论选取
  - `mcp/resources.py:102` 示例 SQL 与 schema 文档
  - `openclaw/workspace/skills/qbu-product-data/SKILL.md`、`openclaw/workspace/TOOLS.md`、`openclaw/old/.../sql-playbook.md` 文档示例
- **Negative list（保持 scraped_at，不切换）**：
  - `workflows.py::_count_pending_translations_for_window`（翻译 worker 等待逻辑——若切换则 NULL 行被跳过，bootstrap 报告会全是英文未翻译评论）
  - `scrape_quality.py::summarize_scrape_quality`（数据质量分母）
  - `report.py::_query_reviews_with_latest_analysis_for_trend`（trend 图 fallback，留待 F013 处理）
  - `report.py:723-735` 各 review picker 的次级排序 key
  - `models.py::get_product_snapshots*`（product_snapshots 不受灌水影响，且 product_snapshots 表不会新增 first_seen_at 列）
- 任何遗漏路径必须按 §3.3 字段语义分工矩阵重新分类

**FR-1.4** 历史数据回填策略（**per-product 基线**）
- 算法（详细 SQL 见 P012 T2.3）：
  1. 计算 `BASELINE_DATE_GLOBAL = min(workflow_runs.logical_date WHERE report_mode='full')`，仅作 `workflow_runs.baseline_logical_date` 字段写入用
  2. `products` 表：所有 `date(scraped_at) <= BASELINE_DATE_GLOBAL` 的行 → `first_seen_at = NULL`；其余 `first_seen_at = scraped_at`
  3. `reviews` 表：所有"product.first_seen_at IS NULL"的 product 下属评论 → `first_seen_at = NULL`；其余按 reviews 自身 scraped_at 写入 first_seen_at
- **接受的近似**：bootstrap 当天若有真实当日新增评论（用户当天才发的），会被一并设 NULL。考虑到 bootstrap 当天的真实新增 ≪ 灌水量，业务可接受。
- NULL 语义：不属于任何"新增"窗口，仅出现在 cumulative 视图

**FR-1.5** 窗口查询的 NULL 处理
- 任何 `WHERE first_seen_at >= ? AND first_seen_at < ?` 查询自动跳过 NULL（SQL 三值逻辑）
- cumulative 查询不加 first_seen_at 过滤，行为保持不变

### FR-2 周一无条件发邮件（主干化）

**FR-2.1** `EmailDecision` 增加 `force_send` 字段
- `decide_business_email` 计算结果：
  - 当 `cadence=="weekly"` 且 today 等于 `REPORT_WEEKLY_EMAIL_WEEKDAY` → `force_send=True`
  - 当判定为 bootstrap → `force_send=True`
  - 其余 → `force_send=False`

**FR-2.2** 主干传递 `force_send` 到三种模式处理函数
- `workflows.py` 在调用 `generate_report_from_snapshot` 时把 `force_send` 透传
- `_generate_full_report` / `_generate_change_report` / `_generate_quiet_report` 顶部统一判断：若 `force_send=True`，覆盖各自的发送频率门
- 删除 `report_snapshot.py:1365-1367` 的隐式 weekly 补丁

**FR-2.3** `should_send_quiet_email` 仅在 daily cadence 下生效
- 函数顶部加门：`if cadence != "daily": return True, None, 0`
- 或由调用方判断 cadence 后决定是否走该函数

**FR-2.4** 兜底告警
- 当 `force_send=True` 但邮件投递失败（SMTP 异常、模板渲染异常）→ 进入 `needs_attention`，独立运维告警邮件
- 实现要点：复用 `_send_data_quality_alert` 投递通道，收件人复用 `config.SCRAPE_QUALITY_ALERT_RECIPIENTS`，dedupe key = `weekly:{logical_date}:email_failure`
- 主题前缀 `[P0][周报投递失败]`，区别于 daily quiet 失败的告警等级
- 告警邮件正文需包含：失败 run_id / logical_date / 失败原因 stack trace 摘要（前 500 字符）/ 相关日志路径

### FR-3 周报模板统一

**FR-3.1** 新模板 `weekly_briefing.html.j2`（或现有 v3 模板的 weekly 分支）必须承载

| 区块 | 静默周（无新评论无变动） | 活跃周（有新评论或变动） |
|---|---|---|
| 顶部数字 | 本周新增 0 / 累计 N | 本周新增 K / 累计 N |
| 本周净变化 | "本周监控范围内未出现新评论与状态变化" | 价格变动 K 项 / 库存翻牌 N 个 / 评分波动 M 款 / 新冒出问题聚类 |
| 累计快照 | 健康指数、好评率、差评率（基于 cumulative） | 同左 + delta 标注 |
| Top 风险产品 | 5 款（基于 cumulative） | 同左 |
| Top VOC 引用 | 上次累计快照里的代表性差评（标注"非本周新增"） | 本周新增 + 累计 Top（明确区分） |
| 翻译进度 | 累计翻译完成率 | 本周翻译完成率 + 累计翻译完成率 |
| 静默周明示提示 | "本周确实静默，以下为累计快照" | 不显示 |

**FR-3.2** 标题语气
- 主题：`产品评论周报 YYYY-MM-DD — {代表产品} 等 N 个产品`
- 顶部 eyebrow：`QBU · WEEKLY BRIEFING`
- 静默周不写"今日"字样

**FR-3.3** 路由规则
- `report_window.type == "weekly"` → 一律走 weekly_briefing 模板
- `type == "weekly" 且 collapsed == True`（窗口被 baseline 守卫收敛，详见 FR-4.1）→ 仍走 weekly_briefing 模板，但 hero 区追加横幅文案：「本期统计窗口仅 N 天（基线生效中），完整 7 天周报将于 YYYY-MM-DD 起出」
- `type == "bootstrap"` → 走现有 bootstrap 分支不变
- `type == "daily"` → 走现有 daily 模板不变

**FR-3.4** 首两次切换的语义说明 banner（一次性）
- 在 `first_seen_at` 上线后的第一与第二个周报，weekly_briefing 模板顶部固定追加一行解释：「数据口径已优化：统计窗口由'入库时间'切换为'评论首次出现时间'，本周数字更准确，与历史报告不可直接比较」
- 触发条件：`workflow_runs.service_version` 跨越含本次 schema 升级的版本边界，且发出后第三周自动消失
- 实现可用一个 env `REPORT_SHOW_SEMANTIC_MIGRATION_BANNER_UNTIL=YYYY-MM-DD`，到期后自动隐藏

### FR-4 兜底守卫与可观测

**FR-4.1** 窗口起点收敛
- `build_windowed_report_snapshot` 计算 `since` 时：
  - `since = max(data_until - window_days, baseline_logical_date + 1d)`
  - `baseline_logical_date` 从 `workflow_runs` 表读，可被 env `QBU_BASELINE_LOGICAL_DATE_OVERRIDE` 覆盖（详见 FR-4.3）
  - 若 `since >= data_until`（窗口被完全收敛掉）→ 在 snapshot 注入 `report_window={"type":"weekly", "label":"本周（窗口收敛）", "days":N, "collapsed":True, "baseline_recovery_date":"YYYY-MM-DD"}`，仍走 weekly_briefing 模板（FR-3.3）
- `_first_seen_in_window`（即 `_scraped_at_in_window` 改名后）类似处理
- collapsed 周仍发邮件（不静默），保持"周一必有邮件"承诺

**FR-4.2** 灌水告警
- 在 `WorkflowWorker._advance_run` 计算 `scrape_quality` 时，新增检测项：
  - `weekly_added = window reviews count`
  - `cumulative = cumulative reviews count`
  - 当 `cumulative > 0 且 weekly_added / cumulative > 0.7` → 触发运维告警邮件
  - 告警内容：「检测到本周窗口内的评论数占累计的 X%，可能存在批量入库或 first_seen_at 回填遗漏」

**FR-4.3** `workflow_runs` 新增 `baseline_logical_date` 字段 + env override
- 字段类型：DATE
- 写入时机：每次 run 完成时，若 `report_mode='full'` 且本字段为 NULL → 写入 logical_date
- 用途：FR-4.1 的窗口起点计算
- **env override**：`QBU_BASELINE_LOGICAL_DATE_OVERRIDE`（格式 YYYY-MM-DD）非空时，FR-4.1 计算 `since` 直接采用该值，跳过 DB 检测
- 应用场景：未来某次大型 schema/数据迁移导致 baseline 检测失效；ops 需临时强制 baseline 推迟以容纳新一批 bootstrap

## 5. 验收标准

### AC-1 窗口语义正确性

- **AC-1.1** 在 5/11 当天的生产 DB 上回填 `first_seen_at` 后，重新生成 5/11 周报：「本周新增」≤ 10 条（实际新爬到的真实增量）
- **AC-1.2** 5/15 周报：「本周新增」反映 5/9 ~ 5/15 的真实增量（不含 bootstrap）
- **AC-1.3** 加入新 SKU 后第一周的周报：「本周新增产品 K 款（基线评论 X 条不计入"本周新增评论"）」；模拟 5/20 加入 5 个新 SKU 各带 200 条历史评论 → 5/27 周报「本周新增评论」≤ 真实增量（不含这 1000 条），「本周新增产品 5 款」明示
- **AC-1.4** MCP `query_reviews(window=7)` 返回 ≤ 10 条（与 AC-1.1 一致）
- **AC-1.5** 钉钉每日摘要（`daily_digest.py`）在 bootstrap 后第二天起，代表评论与 bootstrap 当天摘要的代表评论 review_id 集合**重合度 ≤ 30%**（防止每天循环抽到同一批 bootstrap 评论）

### AC-2 周一必发

- **AC-2.1** 在测试库构造场景：5/11 窗口内 0 新评论 + 0 业务变动 → run 完成后 `email_delivery_status='sent'`
- **AC-2.2** 在测试库构造场景：5/11 窗口内 0 新评论 + 仅价格变动 → run 完成后 `email_delivery_status='sent'`，邮件正文显示价格变动
- **AC-2.3** 切换 `cadence='daily'` 配置，5/11 仍每天发邮件，且 quiet 频率门正常工作（前 3 天连发、第 7 天发）
- **AC-2.4** 删除 `report_snapshot.py:1365-1367` 的补丁后，AC-2.1 仍然通过

### AC-3 模板统一

- **AC-3.1** AC-2.1 静默周邮件正文包含：累计 N 条、健康指数、Top 风险产品 5 款、"本周确实静默"提示
- **AC-3.2** AC-2.2 变动周邮件正文包含：净变化区块（价格变动列表）+ 累计快照
- **AC-3.3** 5/11 活跃周邮件正文与 5/8 bootstrap 邮件的硬指标对比（在 `test_e2e_report_replay.py` 加断言）：
  - 双方正文中出现的 **review_id 集合**：交集 / 并集 ≤ 30%
  - 双方正文中出现的 **cluster label_code 集合**：交集 / 并集 ≤ 50%
  - 双方"需关注产品"列表的 **product sku 集合**：交集 / 并集 ≤ 50%
  - 任一项超阈值即测试失败（语义相似度软指标不作为唯一判据）

### AC-4 可观测

- **AC-4.1** 在测试库构造场景：手动 INSERT 1500 条 `first_seen_at` 在过去 7 天的评论 + cumulative 仅 1600 → run 完成后运维告警邮件被发送（FR-4.2）
- **AC-4.2** 在测试库构造场景：当前 logical_date 距离 baseline ≤ 6 天 → 周一 run 走 weekly_briefing 模板 + 邮件正文出现「本期统计窗口仅 N 天（基线生效中），完整 7 天周报将于 YYYY-MM-DD 起出」横幅；且 `email_delivery_status='sent'`（不静默）
- **AC-4.3** 设置 env `QBU_BASELINE_LOGICAL_DATE_OVERRIDE=2026-05-25` → 5/27 周报的窗口起点取 5/26（覆盖 DB 检测的 5/8）
- **AC-4.4** 在测试库构造场景：周一 weekly_briefing 模板渲染抛异常 → 收到运维告警邮件主题以 `[P0][周报投递失败]` 开头，dedupe key 命中第二次重试不再重复发送

### AC-5 回滚安全

- **AC-5.1** schema 迁移可重入：重复执行不报错，不重复回填
- **AC-5.2** 回滚（删除 `first_seen_at` 列）后，所有查询路径仍能 fallback 到 `scraped_at`（短期容错）

## 6. 非目标 / 显式不做

- 不重新设计 KPI 算法（健康指数、好评率、差评率公式不变）
- 不引入"产品 cohort 分析"等新维度
- 不改 daily 报告频率（仍每天一次）
- 不为周报生成独立 PDF（HTML + Excel 已足够）
- 不在本期处理"月报 / 季报"需求

## 7. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 回填脚本误判 baseline，把真实早期评论也设为 NULL | 回填前 dry-run，输出"将被设 NULL 的评论数 + 抽样 5 条"，人工确认后再执行 |
| 周一模板渲染失败导致零邮件发出 | FR-2.4 的兜底告警 + 模板单元测试覆盖三种数据状态 |
| 切换查询字段后某些遗漏路径仍用 scraped_at 输出错误数字 | FR-4.2 的灌水告警可在生产侧暴露遗漏；上线前用 grep 全量审计 `scraped_at` 引用并加 PR 评论说明每处选择 |
| `first_seen_at` 字段在并发 INSERT 下存在竞争 | UPSERT 逻辑包在事务里；INSERT 路径的 `first_seen_at = scraped_at` 由 SQLite default 子句保证原子性 |

## 8. 里程碑（详见 P012）

- M1（半天）：应急止血——FR-4.1 守卫上线，5/15 周报先救回来
- M2（1 天）：FR-1 schema + 回填 + 查询切换
- M3（半天）：FR-2 主干化 + FR-2.3 quiet 频率门收敛
- M4（1 天）：FR-3 weekly_briefing 模板
- M5（半天）：FR-4.2 灌水告警 + AC-1 ~ AC-5 验收
