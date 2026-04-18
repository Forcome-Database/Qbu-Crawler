# scripts/simulate_reports

报告系统的离线模拟器。以**不改业务代码**为前提，生成日/周/月报的所有典型形态产物，并附带逐场景 debug 产物 + 期望 vs 实际对照，用于分析与改代码后复验。

## 快速开始

```bash
# 1. 首次：克隆桌面基线 DB + 重分布 scraped_at + 回填 labels
uv run python -m scripts.simulate_reports prepare

# 2. 跑完整 42 天时间轴（约 15~30 分钟）
uv run python -m scripts.simulate_reports run

# 3. 生成顶层 index.html
uv run python -m scripts.simulate_reports index

# 4. 查 fail 列表 + 生成 issues.md
uv run python -m scripts.simulate_reports verify

# 5. 改业务代码后，只重跑一个场景（需已有 checkpoint）
uv run python -m scripts.simulate_reports run-one S07

# 6. 或全量重跑（重置 scenarios + checkpoints，保留 DB 基础）
uv run python -m scripts.simulate_reports rerun-after-fix

# 7. 清零一切（DB + scenarios + index + issues）
uv run python -m scripts.simulate_reports reset

# 分析工具
uv run python -m scripts.simulate_reports show S10     # 打印某场景 manifest + debug 列表
uv run python -m scripts.simulate_reports diff S04 S10 # 对比两场景 actual 字段
```

## 产物位置

- **顶层索引**：`C:\Users\leo\Desktop\报告\reports\index.html`
- **每场景**：`C:\Users\leo\Desktop\报告\reports\scenarios\S01-2026-03-20-.../`
  - `manifest.json` — 期望/实际/verdict
  - `*.html` / `*.xlsx` — 业务真实产物
  - `*.json` — snapshot + analytics
  - `emails/` — 从 outbox 抽出的邮件 payload
  - `debug/` — 9 个诊断文件（db_state_before/after、workflow_run、outbox_rows、analytics_tree、top_reviews、html_checksum、excel_structure、events_applied）
- **Issues 汇总**：`C:\Users\leo\Desktop\报告\reports\issues.md`

## 架构与隔离保证

详见 spec `docs/superpowers/specs/2026-04-17-report-simulation-design.md` 第 9 节。核心硬约束：

- `qbu_crawler/**` **业务代码零改动**
- 工作 DB 在项目内 `data/sim/products.db`（gitignore）
- 桌面基线 DB 只读
- 不启任何业务后台线程（`WorkflowWorker` / `NotifierWorker` / Scheduler workers）
- `SMTP_HOST` / `OPENCLAW_HOOK_URL` / `OPENCLAW_BRIDGE_URL` 被清空防止真实外发

## 时间轴

42 天（2026-03-20 → 2026-05-01）包含：
- **S01** cold-start（冷启动 is_partial=true）
- **S02** 常规 Full（多天变体）
- **S03** safety（R6 silence×2）
- **S04** R1 active / **S05** R2 receding / **S06** R3 dormant / **S10** R4 recurrent
- **S07** daily-change（0 评论 + 价格变动）
- **S08a/b/c** quiet-email / **S09a/b/c** quiet-silent
- **S11** needs-attention（翻译 stalled）
- **W0–W5** 6 份周报
- **M1** 月报（7 Tab + 品类对标 + LLM 高管摘要）

## 已知 follow-ups

改 scenarios.py 的 `expected` 字段逐步收紧期望。典型已知问题：
- `is_partial` 检测需从 analytics_tree.json 特定路径读取，当前 `collect_actual` 返回 None
- S08/S09 quiet 判定依赖业务下游 report_mode 区分，P008 后 daily 统一为 `standard`，需改看其他字段
