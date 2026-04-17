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
- **DB 隔离**：项目内 `data/sim/products.db` 作为工作副本，桌面基线 `C:\Users\leo\Desktop\报告\data\products.db` 仅 prepare 阶段读取、永不写入
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
  1. 复制桌面基线 DB → data/sim/products.db
  2. 重分布评论 scraped_at（下面 3.2 节详述）
  3. 从 review_analysis.labels JSON 回填 review_issue_labels 表
  4. 清空 workflow_runs / notification_outbox（留白从头开始）

run 阶段（顺序执行）:
  for date in TIMELINE (2026-03-20 → 2026-05-01, 42 天):
      events = TIMELINE[date]  # 当天的所有数据注入事件
      for evt in events:
          evt.apply(products.db)  # 插入/更新评论、产品、labels、safety_incidents
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
| DB 工作副本 | `data/sim/products.db`（项目内，不污染桌面） |
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

- [ ] `python -m scripts.simulate_reports prepare` 成功生成 `data/sim/products.db` 且 `review_issue_labels` 已回填
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

---

## 9. 真实性与隔离保证（硬性约束）

### 9.1 不入侵业务代码

- `qbu_crawler/**` 在本 feature 下**零改动**；若需要，实现阶段只能通过 env 变量 + freezegun（进程级临时冻结）影响业务代码的运行行为，**严禁 monkeypatch 业务模块内部**
- 模拟脚本以独立子包形式存在（`scripts/simulate_reports/`），与业务解耦；脚本对业务的依赖只通过 `import` 公开函数
- 脚本不启动任何业务 worker 线程（`NotifierWorker` / `WorkflowWorker` / `*SchedulerWorker` / `TranslationWorker`）
- 模拟脚本不通过 CLI 启 `main.py serve`

### 9.2 不污染现实环境

- 桌面基线 DB（`C:\Users\leo\Desktop\报告\data\products.db`）**只读**：prepare 时复制到 `data/sim/products.db`，后续所有写操作都作用在工作副本
- `data/sim/` 加入 `.gitignore`
- 任何 env 变量（`QBU_DATA_DIR` / `REPORT_DIR` / `DB_PATH`）只在模拟脚本的 Python 进程内 `os.environ` 设置，进程退出即消失；不写 `.env`、不改 shell rc
- 桌面 `C:\Users\leo\Desktop\报告\reports\` 下的已有产物移动到 `_legacy/` 再写新产物，避免覆盖

### 9.3 报告本体必须生产级真实

以下路径**必须走业务代码本尊**，不可 mock / 绕过：

| 环节 | 约束 |
|---|---|
| HTML 渲染 | 使用 `qbu_crawler/server/report_templates/*.html.j2` 原模板 |
| Excel 生成 | 使用 `qbu_crawler/server/report.py` 中 `_generate_*_excel()` 原函数 |
| 分析计算 | `analytics_lifecycle` / `analytics_category` / `analytics_scorecard` / `analytics_executive` 全部真实调用 |
| 报告编排 | `submit_daily_run` / `submit_weekly_run` / `submit_monthly_run` + `advance_workflow` 循环推进 |
| 月报 LLM 高管摘要 | **真调** `.env` 中配置的 LLM API；失败才走确定性降级 |
| 邮件 payload | 业务代码写入 `notification_outbox` 的 payload 原样保留；notifier_stub 仅读取、落盘、标记 delivered 状态，**不修改 payload** |

### 9.4 合成数据真实性

注入到 DB 的新增数据必须遵守：

1. **评论文本复用**：新评论 `body` / `headline` 从现有基线评论池按 `label_code` + `polarity` 筛选后克隆，**不得用字符串模板编造**
2. **时间不变式**：`scraped_at ≥ date_published_parsed`（抓取时间不得早于发布时间）
3. **body_hash 唯一**：克隆评论时 `body_hash = MD5(body + "|" + synthetic_salt)[:16]`，避免与原评论冲突
4. **ownership 不变**：新评论关联的 product 继承基线 `ownership` 字段
5. **review_analysis 配套写入**：每条新评论必须同步写入 `review_analysis`（sentiment / labels / impact_category 等），保持与真实爬取后的状态一致
6. **review_issue_labels 回填**：从 `review_analysis.labels` JSON 一对多展开，不凭空新增 label
7. **safety_incidents 参照克隆**：复用现有 99 条的 failure_mode 分布，不新造分类

### 9.5 时间冻结的边界

- `freezegun.freeze_time(date + T09:30)` 仅作用于业务代码调用栈（with 块内）
- 不冻结模拟脚本自身的数据构造（`data_builder` 里的时间戳由脚本显式计算，不走 `datetime.now()`）
- 一次报告调用完整结束后 freezegun 退出，线程/进程环境还原

### 9.6 失败模式

任何一项违反上述约束即视为实现 bug，应：
- 阻断实现并在本文档追加注释说明
- 优先调整模拟脚本适配业务代码，而非反过来

---

## 10. 分析友好性（核心可用性要求）

报告产出后必须便于**逐场景审阅 + 快速定位问题 + 改业务代码后低成本复验**。本节落成硬性交付项。

### 10.1 每场景 `debug/` 目录

每个场景目录下新增 `debug/` 子目录，固定文件清单：

| 文件 | 内容 | 回答的问题 |
|---|---|---|
| `db_state_before.json` | 应用事件前 DB 关键计数（products / reviews / review_issue_labels / safety_incidents 按 site/ownership 分组）+ 关键行样本 | 当天输入状态 |
| `db_state_after.json` | 应用事件后同构 | 事件生效校验 |
| `events_applied.json` | 当天编排事件列表（human-readable，含参数） | 这一天做了什么 |
| `workflow_run.json` | `workflow_runs` 表该 run 完整行（含 status/phase/error/snapshot_path） | 走到哪个阶段、是否 error |
| `outbox_rows.json` | 该 run 关联的 `notification_outbox` 全部行（payload 含摘要，原文在 `emails/`） | 邮件编排逻辑 |
| `analytics_tree.json` | 业务代码输出的完整 analytics dict（含 window + cumulative + lifecycle + category + scorecard + executive） | 所有 KPI 如何算出 |
| `top_reviews.json` | 报告里展示的"关键评论"对应的原始 `reviews` + `review_analysis` 联合行 | 哪些评论驱动了这张报告 |
| `html_checksum.txt` | HTML 渲染后的结构指纹（标签计数 + 关键元素 sha1） | 改代码后产物是否变化 |
| `excel_structure.json` | Excel 的 sheet 清单 + 每 sheet 行数 / 列名 | Excel 结构快照 |

### 10.2 `manifest.json` 升级（期望 vs 实际）

每场景在 `scenarios.py` 里声明 `expected`，runner 跑完后采集 `actual` 并对比，写入 manifest：

```jsonc
{
  "scenario_id": "S10",
  "logical_date": "2026-04-14",
  "phase": "P4",
  "description": "quality_stability 复发触发 R4",
  "expected": {
    "tier": "daily",
    "report_mode": "standard",
    "lifecycle_states_must_include": ["recurrent"],
    "is_partial": false,
    "html_must_contain": ["复发", "quality_stability"],
    "excel_must_have_sheets": ["评论明细", "产品概览"],
    "email_count_min": 1,
    "email_must_not_contain": ["翻译未完成"]
  },
  "actual": {
    "tier": "daily",
    "report_mode": "standard",
    "lifecycle_states_seen": ["recurrent", "active"],
    "is_partial": false,
    "html_contains": {"复发": true, "quality_stability": true},
    "excel_sheets": ["评论明细", "产品概览", "风险打分"],
    "email_count": 2,
    "email_must_not_contain_check": true
  },
  "verdict": "PASS",
  "failures": [],
  "warnings": [],
  "artifacts": ["daily.html", "daily.xlsx", "snapshot.json", "analytics.json", "emails/...", "debug/..."],
  "git_sha": "ab1c724",
  "spec_version": "2026-04-17",
  "executed_at": "2026-04-17T23:45:12"
}
```

`verdict` 取值：
- `PASS` — 所有 expected 断言通过
- `WARN` — 辅助断言未过但核心断言过（例如 email_count 多了 1 封但内容对）
- `FAIL` — 关键断言未过（例如 report_mode 不对 / lifecycle 缺失）

### 10.3 顶层 `reports/index.html` 升级

- 顶部汇总徽章：`✅ N PASS  ⚠️ N WARN  ❌ N FAIL  共 27`
- 左侧过滤器：tier / mode / lifecycle_state / verdict（多选）
- 每张卡片：
  - 标题（场景 ID + 描述）+ 徽章
  - 核心 KPI 摘要（新评论数、风险产品数、lifecycle_states）
  - 展开区：`expected vs actual` 对照表
  - 产物链接（HTML / Excel / snapshot.json / analytics.json / emails/ / debug/）
- 支持按 `git_sha` 分组展示（同场景多次 rerun 的产物并列，便于对比改代码前后）

### 10.4 CLI 子命令

模拟脚本入口扩展为多子命令：

| 命令 | 作用 |
|---|---|
| `python -m scripts.simulate_reports prepare` | 克隆基线 DB、重分布 scraped_at、回填 labels |
| `python -m scripts.simulate_reports run` | 跑完整 42 天时间轴 |
| `python -m scripts.simulate_reports run-one <SID>` | 从最近 checkpoint 回滚并只跑指定场景（秒级迭代） |
| `python -m scripts.simulate_reports rerun-after-fix` | 全量重跑（不做 prepare，复用已重分布的 DB 基础） |
| `python -m scripts.simulate_reports show <SID>` | 打印 manifest + debug 关键指标 |
| `python -m scripts.simulate_reports diff <SID1> <SID2>` | 对比两场景的 analytics/HTML/Excel 结构差异 |
| `python -m scripts.simulate_reports verify` | 重跑所有断言，输出彩色 PASS/FAIL 列表 |
| `python -m scripts.simulate_reports issues` | 汇总 FAIL/WARN 到 `reports/issues.md` |
| `python -m scripts.simulate_reports index` | 仅重建顶层 index.html（产物未变时快速重绘） |
| `python -m scripts.simulate_reports reset` | 删除工作副本 DB + checkpoints + scenarios/ |

### 10.5 Checkpoint 机制

- `run` 过程中每完成一天末尾：拷贝 `data/sim/products.db` → `data/sim/checkpoints/<YYYY-MM-DD>.db`
- `run-one <SID>` 逻辑：查出该场景对应日期 D、上一天 D-1；若 `checkpoints/D-1.db` 存在，直接复制为 `products.db`，应用当天事件后跑报告；否则从最近可用 checkpoint 顺推到 D-1
- 单场景迭代成本从全量跑（分钟级）压到秒级

### 10.6 `reports/issues.md` 自动生成

`verify` 或 `issues` 命令扫描所有 `manifest.json` 的 `failures` + `warnings`，按严重度分组输出 markdown：

```md
# Simulation Issues — <git_sha> run @ 2026-04-17T23:45

## ❌ FAIL (2)
### S07 daily-change (2026-04-04)
- expected `report_mode=change`, actual `standard`
- 可能原因：`determine_report_mode()` 未把"0 新评论 + 价格变化"识别为 Change
- 相关文件：qbu_crawler/server/report_snapshot.py
- 重现：`python -m scripts.simulate_reports run-one S07`

### S11 daily-needs-attention (2026-04-15)
...

## ⚠️ WARN (1)
### M1 monthly
- 月报 executive_summary 字符数 < 200（期望 ≥ 500）
- 可能是 LLM 超时降级到确定性摘要，检查 debug/workflow_run.json.error
```

### 10.7 业务代码迭代工作流

落成后的典型使用链：

1. `run` 跑完 → 打开 `index.html` 审阅所有产物
2. 发现 S07 产物不对 → 点开 S07 卡片看 `expected vs actual` → 展开 `debug/analytics_tree.json` 定位哪段数据异常
3. 判断是业务 bug → 改业务代码（`qbu_crawler/`）
4. `run-one S07` 秒级复验 → 如果 verdict=PASS 且视觉 OK，继续
5. `rerun-after-fix` 全量复跑确保没回归
6. 所有 PASS 后 `verify` 输出绿色全通过

### 10.8 新增验收标准（补充第 7 节）

- [ ] 每场景目录含完整 `debug/` 9 个文件
- [ ] 每个 `manifest.json` 含 `expected` + `actual` + `verdict` + `git_sha`
- [ ] `verify` 命令可独立于 `run` 运行并给出彩色输出
- [ ] `run-one <SID>` 能在 ≤ 30 秒内完成单场景复验（利用 checkpoint）
- [ ] `diff <SID1> <SID2>` 能列出 analytics 关键字段差异（至少字段级）
- [ ] `issues.md` 在存在 FAIL 时自动生成且给出可能原因提示
- [ ] `index.html` 含徽章 + 过滤 + expected/actual 对照展开
- [ ] 整套工作流文档化进 `scripts/simulate_reports/README.md`
