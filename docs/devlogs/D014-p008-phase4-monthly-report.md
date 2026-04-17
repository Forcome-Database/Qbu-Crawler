# D014 — P008 Phase 4: 月报系统

**日期**: 2026-04-17
**相关计划**: `docs/plans/P008-phase4-implementation.md`
**关联 commits**: Tasks 1–15，合计 ~18 commits（`master` 分支）

## 概述

实现每月 1 日自动生成月报，含高管首屏 + 7 Tab V3 风格 HTML + 6-sheet Excel + 高管摘要邮件。沿用 Phase 3 的 tier 路由架构（`generate_report_from_snapshot` 的 `run_tier == "monthly"` 分支）和 `_advance_periodic_run` 管线。新增 4 个独立分析模块，严格单一职责。

## 核心实现

### 问题生命周期完整状态机（`analytics_lifecycle.py`）

四态 active/receding/dormant/recurrent + R1-R6 转移规则。关键设计决策：

- **R3 沉默检测只在负面事件时触发**（不是每个事件）— 正面评论不应该被视为"沉默"
- **`last_negative_date` 追踪所有负面**（不只是 RCW ≥ 0.5 的）— 否则 R4 (dormant → recurrent) 无法触发
- **`credibility_weight(today=window_end)`** — 确保历史报告结果确定性（非当前日期相关）
- **`_SILENCE_DEFAULT_INSUFFICIENT = 30`** — 单事件时默认 30 天沉默窗口，避免过早 dormant
- **R3 gate 包含 recurrent 状态**（R5 parity）— 修复 recurrent → 长沉默 → 新负面应再次 dormant → recurrent

### 品类对标（`analytics_category.py`）

CSV 配置驱动（`data/category_map.csv`）。≥ 3 SKUs/ownership 门槛，不足显示"样本不足"。空 map 自动降级为直接竞品配对（最近价格匹配）。

### SKU 计分卡（`analytics_scorecard.py`）

红黄绿灯阈值：
- 绿 `risk_score < 15 AND negative_rate < 3%`
- 黄 `risk_score 15-35 OR negative_rate 3-8%`
- 红 `risk_score > 35 OR negative_rate > 8% OR critical/high safety`

趋势：对比上月 risk_score，±3 deadband。None-SKU 守卫避免安全事件误标记。

### LLM 高管摘要（`analytics_executive.py`）

OpenAI 兼容 API + 确定性 fallback。输出 `stance/stance_text/3 bullets/2-3 actions`。fallback 保证最少 2 actions（设计要求）。

## 月报模板与邮件

- `report_templates/monthly_report.html.j2` — V3 风格 HTML，高管首屏（健康指数 + 趋势 + LLM 摘要）+ 7 Tab（品类对标、SKU 计分卡、生命周期、评论分析、价格/库存、竞品对比、原始数据）
- `report_templates/email_monthly.html.j2` — 高管首屏摘要邮件（stance card + 3 bullets + actions）

## 序列化并发保护

MonthlySchedulerWorker 在月 1 日触发前依次检查：
1. `_all_daily_runs_terminal(since, until)` — 覆盖月窗口的 daily run 必须终态
2. `_all_weekly_runs_terminal(since, until)` — 使用部分重叠 SQL（跨月边界的周）

防止月初恰逢周一时三个 scheduler（Daily/Weekly/Monthly）争抢数据导致状态错乱。

## 设计偏差登记

| 偏差 | 理由 |
|------|------|
| 月报独立 `monthly_report.html.j2`（非复用 V3 日报模板） | 7 Tab + 高管首屏 + 4 个新 Tab 超出 V3 结构，共享模板会导致条件分支过多 |
| 月报不走 `completed_no_change` 早退 | 月报必出报——高管摘要/品类对标基于累积数据，与当日是否有变化无关 |
| 6-sheet Excel 通过 load + create_sheet 追加（非重写） | DRY：复用现有 4-sheet 基础，只追加月报专属 2 sheet |
| 生命周期 < 30 天历史时显示"数据积累中" | 避免冷启动阶段数据点过少导致状态判断误导高管 |

## 测试

`tests/test_p008_phase4.py`: 44 tests，全部通过。涵盖：

- 配置 + trigger key（3）
- `submit_monthly_run` + Jan wrap（3）
- MonthlySchedulerWorker + 并发序列化（5）
- Runtime 注册（3）
- 品类映射 CSV（3）
- 品类对标 + unknown ownership 守卫（5）
- SKU 计分卡 + None-SKU 守卫（6）
- 生命周期状态机 R1-R6 + recurrent 循环（8）
- LLM 执行摘要 fallback + stance 分类（2）
- 月报模板 + 冷启动提示（2）
- 邮件模板（1）
- 月报路由 + 集成测试（3）
- 6-sheet Excel（1）

Phase 1-3 regression：全部通过（179/179 总计）。

## 文件清单

| 文件 | 操作 |
|------|------|
| `qbu_crawler/server/analytics_lifecycle.py` | 新建 |
| `qbu_crawler/server/analytics_category.py` | 新建 |
| `qbu_crawler/server/analytics_scorecard.py` | 新建 |
| `qbu_crawler/server/analytics_executive.py` | 新建 |
| `qbu_crawler/server/report_templates/monthly_report.html.j2` | 新建 |
| `qbu_crawler/server/report_templates/email_monthly.html.j2` | 新建 |
| `data/category_map.csv` | 新建 |
| `tests/test_p008_phase4.py` | 新建 |
| `qbu_crawler/server/workflows.py` | 修改（MonthlySchedulerWorker + submit_monthly_run + 序列化检查） |
| `qbu_crawler/server/report.py` | 修改（monthly tier 路由 + 6-sheet Excel） |
| `qbu_crawler/server/runtime.py` | 修改（MonthlySchedulerWorker 注册） |
| `qbu_crawler/config.py` | 修改（MONTHLY_SCHEDULER_TIME + CATEGORY_MAP_PATH） |

## 遗留事项

- `data/category_map.csv` 仅覆盖 dev DB 的 9 SKU；生产扩展到 41 SKU 时需补全
- Plotly 图表 (`report_charts.py`) 与 V3 Chart.js 是两条独立管线；P008 Phase 4 月报使用 Chart.js
- recurrent → receding via R2 和 recurrent → dormant via R3 无显式测试（代码路径已验证，场景较低频）
