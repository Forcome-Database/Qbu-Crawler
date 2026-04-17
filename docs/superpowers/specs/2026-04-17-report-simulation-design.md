# 报告模拟脚本 — 设计文档

**日期**：2026-04-17
**分支**：`feature/report-simulation`
**目标**：在**不改业务代码**的前提下，通过构造 SQLite 数据 + 时间冻结 + 调用业务模块，生成 Qbu-Crawler 报告系统**每一种可能的日/周/月报形态**及对应产物（HTML、Excel、JSON snapshot、邮件快照）。

---

## 1. 背景

Qbu-Crawler 报告系统有多维分支：

- **三 tier**：daily / weekly / monthly，各有独立触发、窗口、模板
- **日报三模式**：Full（有新评论）/ Change（无新评论但价格库存评分变动）/ Quiet（都没有；前 N 天发邮件后每周一发）
- **双视角**：`REPORT_PERSPECTIVE=dual` 下窗口 + 累积并存
- **问题生命周期六状态**：R1 active / R2 receding / R3 dormant / R4 recurrent / R5 cold-start / R6 safety-doubled
- **冷启动判据**：`earliest_review_scraped_at > window_start` → `is_partial=true`
- **翻译覆盖率闸门**：<0.7 且 stalled 时走 `needs_attention` 分支（不发邮件、HTML 带预警横幅）
- **月报七 Tab**：评论明细 + 产品概览 + 问题标签 + 趋势 + 品类对标 + SKU 计分卡 + （LLM 高管摘要）

**现状差距**（桌面基线 `C:\Users\leo\Desktop\报告\data\products.db`）：
- 41 产品、2579 评论、99 safety_incidents，**但** `review_issue_labels` 表为空（lifecycle 无数据）
- 评论 `scraped_at` 全部集中在 2026-04-17（典型冷启动形态，但无历史）
- 仅 1 条 daily workflow_run（已 completed），0 条 weekly/monthly
- 仅 1 份日报产物（无 Excel、无周/月报）

需要一套模拟脚本把系统各分支跑满。

---

## 2. 总体架构

### 2.1 运行模式

- **离线、同步、单进程**：直接 `import` 业务模块（`qbu_crawler.server.report`、`qbu_crawler.server.workflows` 等），**不启 FastAPI / FastMCP / NotifierWorker / WorkflowWorker / DailySchedulerWorker / WeeklySchedulerWorker / MonthlySchedulerWorker 线程**
- **时间冻结**：`freezegun.freeze_time()` 包住每次报告调用，让业务代码所有 `datetime.now()` / `date.today()` 返回模拟的当日
- **DB 隔离**：项目内 `data/sim/simulation.db` 作为工作副本，桌面基线 `C:\Users\leo\Desktop\报告\data\products.db` 仅 prepare 阶段读取、永不写入
- **产物隔离**：所有产物落到 `C:\Users\leo\Desktop\报告\reports\scenarios/` 下独立子目录，顶层 `reports/index.html` 汇总卡片导航

### 2.2 脚本结构

```
scripts/simulate_reports/
├── __main__.py         # python -m scripts.simulate_reports <prepare|run|index|reset|run-one SID>
├── config.py           # 常量：基线 DB 路径、工作 DB 路径、产物根、时间轴、场景 ID 列表
├── data_builder.py     # clone_baseline / redistribute_scraped_at / seed_issue_labels / inject_*
├── timeline.py         # TIMELINE = [(date, event_list), ...] 主编排
├── scenarios.py        # 每场景对应的事件工厂函数（纯数据构造，无副作用调用）
├── clock.py            # with_frozen_time(dt) context manager
├── runner.py           # call_daily / call_weekly / call_monthly (绕过 scheduler 直接调)
├── notifier_stub.py    # drain_outbox_to_files(scenario_dir) — 把 payload 写成 email.html
├── report_index.py     # generate_index(scenarios_dir) → reports/index.html
└── manifests.py        # 每场景落 manifest.json（场景 ID / 日期 / 模式 / 触发的生命周期状态 / 产物列表）
```

**为什么单独 `notifier_stub`**：业务代码把邮件 payload 写进 `notification_outbox`，真实投递由 NotifierWorker 线程跑。我们不启该线程，而是**报告生成后立即 drain 该运行关联的新 outbox 行**，把 payload 里的 HTML 正文写成 `<scenario_dir>/emails/*.html`、`.txt`；仍保留 outbox 行（标记 status=`delivered` 并写 `delivered_at`），让下一次查询看到合理终态。

**为什么单独 `runner`**：业务的 scheduler worker 包含大量循环轮询逻辑（workflow_runs 状态机推进）。我们提炼最短路径：`submit_daily_run(logical_date)` → 循环调 `advance_workflow(run_id)` 直到 `status IN (completed, needs_attention, failed)` 为止。这段 adapter 代码完全不碰业务逻辑，只是手动串联它们。

### 2.3 执行流程

```
prepare 阶段（一次性）:
  1. 复制桌面基线 DB → data/sim/simulation.db
  2. 重分布评论 scraped_at（下面 3.2 节详述）
  3. 从 review_analysis.labels JSON 回填 review_issue_labels 表
  4. 清空 workflow_runs / notification_outbox（留白从头开始）

run 阶段（顺序执行）:
  for date in TIMELINE (2026-03-20 → 2026-05-01, 42 天):
      events = TIMELINE[date]  # 当天的所有数据注入事件
      for evt in events:
          evt.apply(simulation.db)  # 插入/更新评论、产品、labels、safety_incidents
      with freeze_time(date + 09:30):
          if is_monday(date):
              run_id = runner.call_weekly(date)
              export_scenario_artifacts("WEEK-{YYYY}W{WW}", run_id)
          if date.day == 1:
              run_id = runner.call_monthly(date)
              export_scenario_artifacts("MONTH-{YYYY}-{MM}", run_id)
          run_id = runner.call_daily(date)
          scenario_id = timeline_metadata[date].scenario_id   # S01, S02, ...
          export_scenario_artifacts(scenario_id, run_id)

index 阶段:
  扫描 scenarios/*/manifest.json → 生成 reports/index.html（按 ID 排序，每张卡片含日期/类型/KPI 摘要/产物链接）
```

### 2.4 export_scenario_artifacts 做什么

1. 根据 run_id 从 workflow_runs 读取 `snapshot_path`、`analytics_path`、`excel_path`，**复制**到场景目录
2. 读取业务生成的 HTML（由 `REPORT_DIR` env 重定向到临时目录）→ 复制到场景目录
3. `notifier_stub.drain_outbox_to_files(scenario_dir, run_id)` 抽出该 run 关联的 outbox 行，写成 HTML/MD 邮件文件
4. 写 `manifest.json`，包含：scenario_id、logical_date、tier、report_mode、lifecycle_state（若有）、kpi 摘要、产物相对路径列表

---

## 3. 时间轴与数据构造

### 3.1 42 天时间轴（2026-03-20 → 2026-05-01）

| Phase | 日期 | 事件 | 场景 ID | 备注 |
|---|---|---|---|---|
| P1 | D01 2026-03-20 周五 | 首日部署，仅 15% 评论 scraped_at 覆盖 | **S01** cold-start | `is_partial=true` |
| | D02 2026-03-21 周六 | +新评论 12 条 | **S02** normal Full | 首个完整 Full |
| | D03 2026-03-22 周日 | +新评论 8 条 | S02b | |
| | D04 2026-03-23 周一 | +新评论 15 条 | S02c | **W0** Weekly（覆盖 D01-D03 单日，仍 run） |
| | D05 2026-03-24 | +新评论 10 条 | S02d | |
| | D06 2026-03-25 | +新评论 9 条 | S02e | |
| | D07 2026-03-26 周四 | +10 条 critical safety 差评（failure_mode=foreign_object） | **S03** safety | R6 silence×2 |
| P2 | D08 2026-03-27 | `quality_stability` label 竞品差评 ×6 集中 | **S04** R1 active | 标 `analysis_labels` |
| | D09 2026-03-28 | 同 label 差评 ×3 | S04b | R1 强化 |
| | D10 2026-03-29 | 同 label 差评 ×2 + 其他 label 评论 ×5 | S04c | |
| | D11 2026-03-30 周一 | 同 label 差评 ×2 | S04d | **W1** Weekly #1 |
| | D12 2026-03-31 | `quality_stability` 好评 ×8（其中 3+ 正向） | **S05** R2 receding | 负正比 ≤ 1:1 |
| | D13 2026-04-01 周三 | +杂项评论 | S02f | 仍 Full |
| | D14 2026-04-02 | +杂项评论 | S02g | |
| P3 | D15 2026-04-03 周五 | `quality_stability` 零评论起点（开始静默） | **S06** R3 dormant 背景 | Full 其他 label 照常 |
| | D16 2026-04-04 周六 | **0 评论**，但某产品 price -15% + stock_status=out_of_stock | **S07** daily-change | 仅产品变动 |
| | D17 2026-04-05 周日 | **0 评论 + 0 变动** | **S08a** quiet email #1 | 发邮件 |
| | D18 2026-04-06 周一 | 同上 | **S08b** quiet email #2 | 发邮件，**W2** Weekly #2 |
| | D19 2026-04-07 | 同上 | **S08c** quiet email #3 | 发邮件（N=3 结束） |
| | D20 2026-04-08 | 同上 | **S09a** quiet silent #1 | 停发邮件 |
| | D21 2026-04-09 | 同上 | S09b | |
| | D22 2026-04-10 | 同上 | S09c | |
| | D23 2026-04-11 周六 | +新评论恢复（非 quality_stability label） | S02h | Full 恢复但 quality_stability 仍静默，累计 8 天静默 |
| P4 | D24 2026-04-12 周日 | +杂项评论（`quality_stability` 仍静默） | S02ha | 累计静默 10 天 |
| | D25 2026-04-13 周一 | +杂项评论 | S02i | **W3** Weekly #3；quality_stability 累计静默 11 天 |
| | D26 2026-04-14 | `quality_stability` 新差评 ×4 **再现**（距 D11 last-active = 15 天 ≥ silence_window 14） | **S10** R4 recurrent | 依赖 silence_window=14 |
| | D27 2026-04-15 | 强制 30% 当日评论 `translate_status=pending` + 翻译 stalled 标志 | **S11** needs-attention | 覆盖率 <0.7，HTML 带预警 |
| | D28 2026-04-16 | 翻译恢复 + 新评论 | S02j | |
| P5 | D29 2026-04-17 周五 | +新评论（与现实基线日期对齐） | S02l | |
| | D30 2026-04-18 | +新评论 | S02m | |
| | D31 2026-04-19 周日 | +新评论 | S02n | |
| | D32 2026-04-20 周一 | +新评论 | S02o | **W4** Weekly #4 |
| | D33–D41 2026-04-21 → 2026-04-29 | 常规 Full / 混合若干 Change | S02p–S02w | |
| | D42 2026-04-27 周一 | — | — | **W5** Weekly #5 |
| | **D43 2026-05-01 周五** | 触发月报 | **M1** Monthly 2026-04 | 七 Tab + 品类对标 + LLM 高管摘要 |

总产物：
- **S01–S11**：11 个不同类型的 daily 产物（含重复类型 S02 的变体若干，为了时间轴连续性；但 manifest 区分）
- 加上 S02 常规 Full 的重复日，合计约 **30+ 个 daily 产物**
- **W0–W5**：5~6 个 weekly
- **M1**：1 个 monthly

（粒度可按实现进度动态压缩：若构造成本过高，P5 的 S02p–S02w 合并成每 2 天 1 个代表场景即可。）

### 3.2 scraped_at 重分布策略

基线 DB 的 2579 条评论 `scraped_at` 全部是 2026-04-17，无法体现历史抓取节奏。prepare 阶段按以下规则重分布：

- 按 `date_published_parsed` 排序所有评论
- 最早 15% → `scraped_at = 2026-03-20 09:00`（D01 部署那天一次性抓到的历史）
- 接下来每 3~5% → 按时间轴节点分布（例如 D04、D08、D11 各一批）
- 最后 ~20% → 2026-04-17 以后（保留一部分在时间轴末端）

目的：让 D01 的 `earliest_review_scraped_at = 2026-03-20`，相对任何更早的窗口都是 `is_partial=true`（冷启动）；后续天数则有真实历史可对比。

### 3.3 review_issue_labels 回填

从 `review_analysis.labels` JSON 字段（2579 条都有，格式如 `[{"code":"quality_stability","polarity":"negative","severity":"medium","confidence":0.85}]`）一次性全量回填到 `review_issue_labels` 表。

### 3.4 事件注入函数

`data_builder.py` 提供：

- `inject_new_reviews(date, product_sku_or_filter, count, label_codes, polarity, rating_range)` — 插入新评论 + 关联 review_analysis + review_issue_labels（rating、body 用模板生成，translate_status=done）
- `inject_safety_incidents(date, count, level, failure_mode)` — 插入 safety_incidents 关联现有评论
- `mutate_product(sku, price_delta_pct, stock_status, rating)` — 更新 products + product_snapshots
- `force_translation_stall(date, pending_ratio)` — 把当日新评论一部分标 `translate_status=pending`，并写 `translate_retries=3`（触发 stalled 语义）
- `seed_dormant_pattern(label_code, silent_days)` — 保证某 label 过去 N 天无评论（静默），由时间轴上 D15–D23 自然完成

---

## 4. 关键技术决策（定稿）

| 决策 | 选择 |
|---|---|
| 触发方式 | 纯离线 `import` 业务模块 |
| 时间冻结 | `freezegun.freeze_time(date + 09:30)` 包住每次报告调用 |
| DB 工作副本 | `data/sim/simulation.db`（项目内，不污染桌面） |
| Scheduler 线程 | 不启；`runner.py` 手动串联 `submit_*_run()` + `advance_workflow()` |
| Notifier 线程 | 不启；`notifier_stub.drain_outbox_to_files()` 抽 payload 写 `emails/*.html` + 标 delivered |
| 产物位置 | `C:\Users\leo\Desktop\报告\reports\scenarios/<SID>/` + 顶层 `index.html` |
| Labels | prepare 阶段从 `review_analysis.labels` 回填 `review_issue_labels` |
| 月报 LLM | **真调用**（走 `.env` 里 `LLM_API_*`）；若网络/密钥失败，自然降级走确定性摘要，**两种情况下产物都算成功** |
| 环境变量 | `QBU_DATA_DIR=<work_dir>/data/sim/`、`REPORT_DIR=<temp>/reports_raw/` 运行前设置；业务代码读到 |

---

## 5. 风险与缓解

| 风险 | 缓解 |
|---|---|
| `silence_window = max(14, min(60, avg_interval × 2))` 取决于历史 `quality_stability` label 评论间隔。若 prepare 阶段未先喂历史，D26 复发不会被识别为 R4 | prepare 阶段在 D08 前注入 **≥5 条 quality_stability 历史评论**（间隔约 5~7 天），使 avg_interval ≈ 6，silence_window = 14 天（floor）；D11 last-active 2026-03-30 → D26 复发 2026-04-14 距离 15 天，≥ 14 触发 R4。实现阶段预跑 `analytics_lifecycle` 校验实际触发点，如阈值与预估有出入，时间轴微调 |
| 业务代码硬编码 DB 路径 | 用 `QBU_DATA_DIR` env 覆盖；如果仍硬编码，实现阶段加 monkeypatch |
| freezegun 不生效于 C 扩展或子进程 | 实现时全 Python、单进程，不 fork |
| outbox 在没 NotifierWorker 时会堆积 | `notifier_stub` 每次报告结束后立即 drain |
| LLM 真调超时/额度 | Runner 加 30s 超时 try/except，失败日志记录后继续，月报自然走确定性摘要分支 |
| 产物目录命名与已有 `daily-2026-04-17.html` 冲突 | 实现阶段先重命名或移走已有文件到 `reports/_legacy/` |

---

## 6. 产物清单（期望）

```
C:\Users\leo\Desktop\报告\reports\
├── index.html                                      # 汇总卡片导航
├── _legacy/                                        # 旧产物归档（避免冲突）
└── scenarios/
    ├── S01-daily-full-cold-start-2026-03-20/
    │   ├── manifest.json
    │   ├── daily.html
    │   ├── daily.xlsx
    │   ├── snapshot.json
    │   ├── analytics.json
    │   └── emails/
    │       ├── workflow_started.html
    │       └── workflow_full_report.html
    ├── S02-daily-full-normal-2026-03-21/
    ├── S03-daily-safety-2026-03-26/
    ├── S04-daily-r1-active-2026-03-27/
    ├── S05-daily-r2-receding-2026-03-31/
    ├── S06-daily-r3-dormant-2026-04-03/
    ├── S07-daily-change-2026-04-04/
    ├── S08a-daily-quiet-email-1-2026-04-05/
    ├── S08b-daily-quiet-email-2-2026-04-06/
    ├── S08c-daily-quiet-email-3-2026-04-07/
    ├── S09a-daily-quiet-silent-1-2026-04-08/
    ├── S09b-daily-quiet-silent-2-2026-04-09/
    ├── S09c-daily-quiet-silent-3-2026-04-10/
    ├── S10-daily-r4-recurrent-2026-04-14/
    ├── S11-daily-needs-attention-2026-04-15/
    ├── W0-weekly-2026W13/
    ├── W1-weekly-2026W14/
    ├── W2-weekly-2026W15/
    ├── W3-weekly-2026W16/
    ├── W4-weekly-2026W17/
    ├── W5-weekly-2026W18/
    └── M1-monthly-2026-04/
        ├── monthly.html             # 7 Tab
        ├── monthly.xlsx             # 6 Sheet
        ├── executive_summary.txt    # LLM 真调产物
        └── emails/email_monthly.html
```

约 **20+ 个 daily + 6 个 weekly + 1 个 monthly = 27+ 场景产物**。

---

## 7. 验收标准

- [ ] `python -m scripts.simulate_reports prepare` 成功生成 `data/sim/simulation.db` 且 `review_issue_labels` 已回填
- [ ] `python -m scripts.simulate_reports run` 无异常跑完 42 天，生成 ≥20 个 daily + ≥4 个 weekly + 1 个 monthly 产物
- [ ] 每场景目录含 `manifest.json` + `*.html` + （Full/Weekly/Monthly 场景）`*.xlsx`
- [ ] S01 产物含 `is_partial=true` 标记
- [ ] S03 HTML 体现 safety 事件（`safety_incidents` 表非空且在报告中呈现）
- [ ] S04 / S05 / S06 / S10 manifest 的 `lifecycle_state` 分别为 active / receding / dormant / recurrent
- [ ] S07 产物为 Change 模式（change-summary HTML，无 Excel）
- [ ] S08a/b/c 场景目录含 `emails/*.html`（邮件被抽出），S09a/b/c 目录 `emails/` 为空
- [ ] S11 HTML 含翻译预警横幅，outbox 对应行 status != delivered（不发邮件）
- [ ] M1 产物含 6 Sheet Excel + LLM 或降级高管摘要
- [ ] `reports/index.html` 可在浏览器打开，每张卡片能跳转到对应 HTML
- [ ] `git diff qbu_crawler/` 为空（**业务代码完全未改**）

---

## 8. 范围外（本次不做）

- 不改业务代码（包括 bug 修复也不做）
- 不测真实投递（钉钉/邮件）
- 不覆盖 FastAPI/MCP HTTP 链路（离线 import）
- 不改桌面基线 DB
- 不跑 scrape 爬虫
