# P009 · 报告内容与投递频率解耦

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 打破 "新评论 ⇒ full 报告" 的朴素二元规则，让**完整分析每天必算**、而**邮件投递按日历 / 事件 / 兜底 / 按需四驾马车独立决策**，彻底解决"低频评论品类首跑后再也收不到完整分析"的设计缺陷。

**Architecture:** 把现在的 `report_mode ∈ {full, change, quiet}` 单维决策拆成两层——`analysis_depth`（恒为 full，产出 analytics.json + excel）和 `delivery_plan`（决定今天发哪套 template、发不发、为啥）。在 `report_snapshot.py` 前置一个新的 `delivery.py` 做投递决策，复用现有三套 HTML 模板作为渲染层，同时新增 `events.py` 做语义化事件检测（断货 / 崩价 / 评分暴跌）。迁移走 feature flag + 双写 3~7 天验证，老路径保留到新路径产出稳定再下线。

**Tech Stack:** Python 3.10 + SQLite + jinja2 + pytest（沿用现有栈，零新依赖）

---

## 0 · 现状复核（对当前 HEAD `bc6505d`）

| ID | 问题 | 位置 | 严重度 |
|---|---|---|---|
| A | `determine_report_mode` 唯一触发 full 的条件是 `bool(snapshot["reviews"])`，评论更新频率低的品类首跑后几乎永远落到 change/quiet | `qbu_crawler/server/report_snapshot.py:188-205` | P0 |
| B | `report_mode` 单字段同时承担"算什么"和"发什么"两件事，无法独立调度 | `report_snapshot.py:709-752` + `workflow_runs.report_mode` 列 | P1 |
| C | Excel 附件仅在 full 分支产出（`_generate_change_report`/`_generate_quiet_report` 都返回 `excel_path=None`），运营想看累计 KPI 必须临时查库 | `report_snapshot.py:622, 700` | P1 |
| D | 断货、崩价这类真实业务事件被埋没在"价格/库存任意变动 ⇒ change"的粗粒度里，没有严重度分级，也没有立即触达的通道 | `detect_snapshot_changes` → change 模式，全部同等对待 | P1 |
| E | `should_send_quiet_email` 只能按 quiet 连续天数兜底，无法覆盖"连续 10 天 change 但从没发过 full"的场景 | `report_snapshot.py:35-73` | P2 |
| F | `report_phase` 五态（`none → fast_pending → fast_sent → full_pending → full_sent`）语义和将要新增的投递节奏冲突，fast/full 耦合在 phase 机上 | `workflows.py:654-768` | P2 |

**不纳入本计划**（独立推进）：
- 事件检测阈值的 LLM 自适应（先用硬阈值上线，一月后据日志调参）
- 钉钉卡片模板优化（属于渲染层样式迭代）

---

## 1 · 核心设计

### 1.1 概念模型

```
         ┌──────────────────┐
snapshot │ analyze (恒 full)│ → analytics.json + excel（永远产出）
         └────────┬─────────┘
                  │
                  ▼
         ┌──────────────────┐
         │ detect_events()  │ → List[Event] (critical/major/minor)
         └────────┬─────────┘
                  │
                  ▼
         ┌──────────────────┐
         │ plan_delivery()  │ → DeliveryPlan{template, send, reason}
         └────────┬─────────┘
                  │
                  ▼
         ┌──────────────────┐
         │ render & notify  │ → HTML + outbox 通知
         └──────────────────┘
```

### 1.2 DeliveryPlan 决策规则（落到配置）

按以下优先级**从上到下**评估，第一个命中即返回：

| 优先级 | 条件 | template | send | reason |
|---|---|---|---|---|
| 1 | 存在 `severity=critical` 事件（断货 / 崩价 ≥ 40% / 评分跌破 3.0） | `alert` | true | `event:{kind}` |
| 2 | `logical_date.day == 1`（月初） | `monthly` | true | `calendar:monthly` |
| 3 | `logical_date.weekday == 0`（周一） | `weekly` | true | `calendar:weekly` |
| 4 | 存在 `severity=major` 事件（降价 20~40% / 新品 / 评分降 ≥ 0.3） | `daily` | true | `event:{kind}` |
| 5 | 存在 `severity=minor` 事件（小幅价格变动 / 小量新评论） | `daily` | true | `event:{kind}` |
| 6 | 距离上次**发出**的邮件 ≥ `DELIVERY_SILENT_MAX_DAYS`（默认 7） | `daily` | true | `silence_breaker` |
| 7 | 其他 | `daily` | false | `quiet` |

**weekly / monthly template** 都包含完整 KPI + 趋势 + Excel 附件；**daily template** 是轻量 HTML 只带今日增量和事件卡片；**alert template** 只展示事件本身 + 必要上下文。

### 1.3 Event 语义化分级

| kind | critical | major | minor |
|---|---|---|---|
| price_change | 跌 ≥ 40% | 跌 20~40% | 跌 5~20% |
| stock | in_stock → out_of_stock | out → in | — |
| rating | 跌破 3.0（绝对值）| 单次跌 ≥ 0.3 | 跌 0.1~0.3 |
| review | — | 单日新评论 ≥ 50 条 | 有新评论但 < 50 |
| product | — | 新品上架 / 下架 | — |

阈值全部走 `.env` 可调（`EVENT_PRICE_CRITICAL_PCT` 等），首次上线用默认值跑 2 周，据日志调参。

### 1.4 与旧 `report_mode` 的兼容性

- 新字段 `delivery_template`（weekly / monthly / daily / alert）写入 `workflow_runs`，老 `report_mode` 在迁移期**双写**（保留 full/change/quiet 语义用于 dashboard 对照）
- 老的 `report_phase` 简化为 `analyzing → delivering → completed`（5 态 → 3 态），fast/full 分阶段改由 delivery_plan 负责
- `REPORT_MODE` feature flag 扩展一个取值 `decoupled`，生效时走新路径；保留 `snapshot_fast_full` 做回滚

---

## 2 · 文件布局

| 改动 | 文件 | 职责 |
|---|---|---|
| 新建 | `qbu_crawler/server/events.py` | `detect_events(snapshot, previous) -> List[Event]`，语义化分级 |
| 新建 | `qbu_crawler/server/delivery.py` | `plan_delivery(snapshot, events, history, calendar) -> DeliveryPlan`，纯函数 |
| 修改 | `qbu_crawler/server/report_snapshot.py` | 保留 `generate_report_from_snapshot` 作为入口；新增 `_generate_decoupled_report()` 分支；`determine_report_mode` 在 `decoupled` flag 下被旁路 |
| 修改 | `qbu_crawler/server/report_html.py`（或新建） | 新增 `render_weekly_email()` / `render_monthly_email()` / `render_daily_email()` / `render_alert_email()` |
| 新建 | `qbu_crawler/server/report_templates/email_weekly.html.j2` | 周度完整报告模板（基于现 `email_full.html.j2` 精简） |
| 新建 | `qbu_crawler/server/report_templates/email_monthly.html.j2` | 月度深度模板（加月环比区块） |
| 新建 | `qbu_crawler/server/report_templates/email_daily.html.j2` | 轻量日简报模板（基于现 `email_change.html.j2`） |
| 新建 | `qbu_crawler/server/report_templates/email_alert.html.j2` | 事件告警模板（参考 P008 `email_data_quality.html.j2`） |
| 修改 | `qbu_crawler/models.py` | `workflow_runs` 新列 `delivery_template`, `delivery_sent`, `delivery_reason`, `events`（JSON） |
| 修改 | `qbu_crawler/server/workflows.py` | phase 机精简为 3 态；`full_pending` 分支改调新的决策入口 |
| 修改 | `qbu_crawler/config.py` | 扩展 `REPORT_MODE` 枚举；新增 `DELIVERY_SILENT_MAX_DAYS`、`EVENT_*_PCT` 一族阈值 |
| 新建 | `tests/test_events.py` | 事件检测分级单测 |
| 新建 | `tests/test_delivery.py` | `plan_delivery` 6 种决策路径单测 |
| 修改 | `tests/test_report_integration.py` | 新增 decoupled 模式端到端测试 |
| 修改 | `CLAUDE.md` | "V3 报告模式系统"段补 decoupled 新模型 |
| 新建 | `docs/devlogs/D009-report-decoupling.md` | 迁移与调参记录 |

---

## 3 · 任务分解

### Task 1：事件检测模块 `events.py`（纯函数 + 全单测）

**Files:**
- Create: `qbu_crawler/server/events.py`
- Create: `tests/test_events.py`
- Modify: `qbu_crawler/config.py`（新增阈值）

**契约：**
- `Event` 是 dataclass，字段 `kind, severity, subject_sku, subject_name, payload, logical_date`
- `detect_events(snapshot, previous) -> List[Event]` 是纯函数，只读 snapshot，不访问 DB
- 严重度优先级 `critical > major > minor`，同一 sku 同一 kind 取最严重
- 采集缺失（遵循 P008 `_is_missing` 语义）**不产生事件**

- [ ] **Step 1.1 — 写失败测试**：为每种 kind × severity 组合写一条断言，包含"缺失值不产生事件"回归用例
- [ ] **Step 1.2 — 实现 `detect_events`**：遍历 snapshot.products，与 previous 对比，按阈值分级
- [ ] **Step 1.3 — 配置项入库**：`config.py` 追加 `EVENT_PRICE_CRITICAL_PCT=40`, `EVENT_PRICE_MAJOR_PCT=20`, `EVENT_RATING_CRITICAL_ABS=3.0`, `EVENT_RATING_MAJOR_DELTA=0.3` 等

### Task 2：投递决策模块 `delivery.py`（纯函数 + 全单测）

**Files:**
- Create: `qbu_crawler/server/delivery.py`
- Create: `tests/test_delivery.py`
- Modify: `qbu_crawler/config.py`（`DELIVERY_SILENT_MAX_DAYS`）

**契约：**
- `DeliveryPlan` dataclass：`template: Literal["weekly","monthly","daily","alert"], send: bool, reason: str`
- `plan_delivery(logical_date, events, last_delivery_at, calendar_config) -> DeliveryPlan`
- 不访问 DB、不做 IO；`last_delivery_at` 由 workflow 层查好传入
- 决策顺序严格遵循 1.2 的 7 条规则

- [ ] **Step 2.1 — 写失败测试**：7 条决策路径各一条测试，外加"周一 + critical 事件 → alert 优先"这类组合用例
- [ ] **Step 2.2 — 实现 `plan_delivery`**：纯 if-elif 链，每个分支打印 reason
- [ ] **Step 2.3 — DB 查询辅助**：在 `models.py` 新增 `get_last_delivered_run()`（查 `delivery_sent=1` 的最近一条），workflow 层用

### Task 3：表结构与迁移

**Files:**
- Modify: `qbu_crawler/models.py:134-156`（表定义）+ `:236-248`（ALTER 段）
- Modify: `qbu_crawler/models.py:692-730`（update 函数白名单）

**契约：**
- 新列全部 nullable，老数据回填 NULL 不影响
- `events` 列存 JSON 数组字符串；读出时需 `json.loads` 容错

- [ ] **Step 3.1** — 建表语句追加 4 列：`delivery_template TEXT`、`delivery_sent INTEGER DEFAULT 0`、`delivery_reason TEXT`、`events TEXT`
- [ ] **Step 3.2** — `_MIGRATIONS` 列表追加对应 `ALTER TABLE` 语句（幂等）
- [ ] **Step 3.3** — `update_workflow_run` 的字段白名单加入新列
- [ ] **Step 3.4** — 新增 `get_last_delivered_run()` 和 `set_delivery_outcome(run_id, template, sent, reason, events)`
- [ ] **Step 3.5** — 跑 `pytest tests/test_models.py` 确认迁移幂等（新老 DB 都能升到 head）

### Task 4：渲染层新模板

**Files:**
- Create: `report_templates/email_weekly.html.j2`, `email_monthly.html.j2`, `email_daily.html.j2`, `email_alert.html.j2`
- Modify or Create: `qbu_crawler/server/report_html.py`（新增 `render_{weekly|monthly|daily|alert}_email`）

**契约：**
- 所有模板消费同一份 `analytics.json`，区别只在**展示哪些区块**
- `weekly/monthly` 必须含 Excel 附件链接占位符
- `daily/alert` 不含 Excel，HTML 内联所有关键信息
- 模板继承现有样式（reuse `email_base.html.j2` 如存在，否则直接从 `email_full.html.j2` 拷样式段）

- [ ] **Step 4.1** — 抽出公共 `_email_base.html.j2`（从 `email_full.html.j2` 提公共 header/footer/样式）
- [ ] **Step 4.2** — 实现 4 个模板，各有 jinja2 snapshot 测试
- [ ] **Step 4.3** — `report_html.py` 新增 4 个 render 函数，签名统一为 `render_X_email(analytics, snapshot, events) -> html_str`

### Task 5：Workflow 接入 + 新路径主干

**Files:**
- Modify: `qbu_crawler/server/workflows.py:654-768`
- Modify: `qbu_crawler/server/report_snapshot.py:709-752`（`generate_report_from_snapshot` 入口）
- 新增: `qbu_crawler/server/report_snapshot.py:_generate_decoupled_report()`

**契约：**
- 保留老 phase（`none→fast_pending→fast_sent→full_pending→full_sent`）；新分支走新 phase（`analyzing→delivering→completed`）
- 进入分支由 `config.REPORT_MODE == "decoupled"` 控制
- 新路径永远产出 analytics_path + excel_path（不管最后发不发邮件）
- 通知 outbox kind 由 `workflow_full_report` 细化为 `workflow_delivery`（payload 带 template）

- [ ] **Step 5.1 — 加 feature flag 分支**：`config.py` 的 `REPORT_MODE` 枚举追加 `decoupled`；`generate_report_from_snapshot` 头部判断是否走新路径
- [ ] **Step 5.2 — 实现 `_generate_decoupled_report(snapshot, send_email)`**：
  - 调 `generate_full_report_from_snapshot`（强制 full 算分析 + 落 excel）
  - 调 `detect_events` 得事件列表
  - 调 `plan_delivery` 得 DeliveryPlan
  - 按 `plan.template` 选对应 render 函数生成 HTML
  - `plan.send=True` 时发邮件；无论发不发都 `set_delivery_outcome` 写审计
- [ ] **Step 5.3 — `workflows.py` 新路径 phase 精简**：decoupled flag 下跳过 fast_pending，`none` 直接进 `full_pending`（沿用老列名，值改为 "delivering" 在 run 维度表达）。保留旧路径不动。
- [ ] **Step 5.4 — 通知 payload**：`_enqueue_workflow_notification` 的 payload 新增 `delivery_template`、`delivery_reason`、`events_count` 字段

### Task 6：双写验证期（影子模式）

**Files:**
- Modify: `config.py` 新增 `REPORT_DECOUPLE_SHADOW=true/false`
- Modify: `report_snapshot.py` 在 legacy 路径里追加 shadow 分支

**契约：**
- shadow 模式下：**legacy 路径照旧发邮件**；同时**调用新的 `detect_events` + `plan_delivery` 只记录不发**
- 新路径的 `delivery_template`/`delivery_reason` 双写入库作对比
- 每日生成差异报告：老路径 report_mode vs 新路径 delivery_template

- [ ] **Step 6.1** — shadow 分支实现（不产出文件、不发邮件、只落库）
- [ ] **Step 6.2** — 新增 CLI `uv run python -m qbu_crawler.scripts.delivery_shadow_diff`，读最近 7 天 workflow_runs 产出对照表
- [ ] **Step 6.3** — 跑影子 3~7 天，人工 review 差异（每日运营群发一份对照）

### Task 7：切流 + 下线 legacy

**执行顺序：**

- [ ] **Step 7.1** — 影子验证通过后，生产 `.env` 改 `REPORT_MODE=decoupled`，重启服务
- [ ] **Step 7.2** — 观察 2 周，`workflow_runs` 监控 `delivery_sent=0` 占比 & reason 分布，据实调参阈值
- [ ] **Step 7.3** — 确认稳定后删除 `_generate_change_report` / `_generate_quiet_report` / `should_send_quiet_email` 相关代码（保留 DB 列作历史）
- [ ] **Step 7.4** — 更新 `CLAUDE.md` 的"V3 报告模式系统"段落，标注 legacy 已下线
- [ ] **Step 7.5** — 发 PyPI patch 版本

---

## 4 · 验证计划

### 4.1 单测覆盖（必过）

| 测试文件 | 最少用例数 | 覆盖点 |
|---|---|---|
| `test_events.py` | ≥ 12 | 5 种 kind × 3 档严重度 + 缺失值回归 + 同 sku 取最严重 |
| `test_delivery.py` | ≥ 10 | 7 条规则路径 + 3 条组合优先级 |
| `test_report_integration.py` | +3 | decoupled 路径端到端（有评论 / 无评论但有事件 / 纯静默）|

### 4.2 影子对照（上线前）

跑 7 天，生成的对照表必须满足：
- **所有 legacy full** 在新路径对应 `weekly` 或 `alert`（保证"该发的还在发"）
- **≥ 1 次 weekly** 从 legacy quiet 升级而来（证明解决了"永远 quiet"的核心痛点）
- **critical 事件日** 新路径必产 `alert`，legacy 路径可能是 change（证明事件触达升级）

### 4.3 生产观察（切流后 2 周）

监控 SQL：
```sql
SELECT delivery_template, delivery_reason, COUNT(*) 
FROM workflow_runs 
WHERE created_at > date('now', '-14 days') AND workflow_type='daily'
GROUP BY delivery_template, delivery_reason;
```

期望分布（假设 14 天观察窗）：
- `weekly` = 2（两个周一）
- `monthly` = 0~1
- `alert` = 0~3
- `daily` with `event:*` reason = 3~7
- `daily` with `silence_breaker` reason = 0~1
- `quiet` (send=0) = 剩余

---

## 5 · 风险与回滚

| 风险 | 概率 | 缓解 |
|---|---|---|
| 事件阈值设得太敏感，alert 邮件轰炸 | 中 | 影子期不发邮件，只记录；上线首周降一档阈值灵敏度 |
| `detect_events` 性能在大 SKU 库下退化 | 低 | 纯 Python 字典对比，产品数 < 10k 量级无忧；极端情况加 profile |
| Excel 生成量翻倍（从"仅 full 日"到"每日"）导致磁盘膨胀 | 低 | Excel 单文件 < 2 MB，每日一份全年 ~700 MB，可接受；加 `REPORT_DIR` 清理脚本到独立 plan |
| 老模板用户习惯了 change 邮件的样式，daily 样式变化引发困惑 | 低 | daily 模板继承 change 的视觉语言，仅重排区块顺序 |

**回滚开关**：`REPORT_MODE=snapshot_fast_full`（老值）重启即回滚，DB 新列留空不影响。

---

## 6 · 不做的事（边界声明）

- **不改分析算法**：KPI 口径、健康指数计算、聚类逻辑一律沿用 P007 定义
- **不改通知链路**：notification_outbox + NotifierWorker + bridge 架构不动，只改 payload 字段
- **不引入 cron 调度**：日历判断是 `logical_date.weekday()` 本地计算，不依赖外部调度器
- **不改任务 / 爬虫层**：collect / scrape / snapshot freeze 一律不动
- **不改 AI digest**：`_maybe_trigger_ai_digest` 保持原逻辑（它读 analytics_path，新路径保证该文件恒存在）

---

## 7 · 完成标准（Definition of Done）

- [ ] 所有新建文件有单测且 `pytest -q` 全绿
- [ ] 影子对照报告连跑 7 天，新老路径差异可解释
- [ ] 生产切流后 14 天内：至少收到 2 封 weekly、0~3 封 alert、日均邮件数 ≤ legacy 的 120%
- [ ] `workflow_runs.delivery_template` 列空值率 = 0（所有新 run 都写入）
- [ ] `CLAUDE.md` 和 `docs/devlogs/D009-*.md` 已更新
- [ ] PyPI 新版本发布且生产 `service_version` 已对齐
