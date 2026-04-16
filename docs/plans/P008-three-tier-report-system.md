# P008 — 三层报告体系 + Bug 修复 + 安全增强

> **关联需求**：诊断发现的 5 个 P0/P1 Bug + 日报警报疲劳 + 缺乏周报/月报 + 安全问题无分级
> **前置条件**：P006（报告 Bug 修复）+ P007（双视角架构）已部分落地
> **优先级**：P0
> **预估工作量**：分 4 个 Phase，总计 3-4 周
> **决策记录**：brainstorming 于 2026-04-16，含批判性/建设性/Codex 三方审查
> **审查记录**：2026-04-16 多角度审查（边界/假设/漂移），修订 v2

---

## 1. 问题陈述

### 1.1 诊断发现（2026-04-16 对 data/reports2 的审查）

4 天运行产出 4 个 workflow run，暴露以下问题：

| Run | 日期 | 模式 | 核心问题 |
|-----|------|------|----------|
| #1 | 04-13 | Full (Baseline) | 正常，26MB Excel |
| #2 | 04-14 | Quiet | KPI 全部 N/A（健康指数、差评率） |
| #3 | 04-15 | Full (2 条窗口评论) | KPI=100 但 LLM 说"3条差评指向质量安全问题"——精神分裂 |
| #4 | 04-16 | Change | KPI N/A + 评分 "None" 被原样渲染 |

### 1.2 根因分析

1. **口径不一致**：KPI 看窗口数据、LLM 看累积数据、Issues Tab 看窗口数据——同一报告三个数据源
2. **模式退化太严重**：Change/Quiet 不计算累积 KPI → 75% 的日报 N/A
3. **报告节奏与品类不匹配**：垂直细分品类每周 0-2 条新评论，日报制度导致绝大多数日子无信息量
4. **安全问题扁平化**：`_SAFETY_KEYWORDS` 是 frozenset，"金属碎屑进入食物"和"外壳不对齐"同等对待
5. **V3 HTML 双视角未收口**：邮件是双视角，HTML Tab 2 是占位符，全景数据 tab 读窗口数据
6. **impact_category 管线端到端断裂**：LLM 已产出，但 `query_cumulative_data()`、`get_reviews_with_analysis()`、`freeze_report_snapshot()` enrichment、下游分析 4 处均未消费

### 1.3 当前代码已有基础

P006/P007 已部分落地，不是从零开始：
- `workflows.py:632` — Change/Quiet 路由已修复（不再 early return）
- `report_snapshot.py:274` — 双视角快照结构已存在
- `report_analytics.py:1537` — `build_dual_report_analytics()` 已实现
- `report_common.py:493` — 健康指数贝叶斯收缩已实现
- `email_full.html.j2` — 邮件模板已支持累积 KPI

### 1.4 数据假设与适用范围

当前"每周 0-2 条新评论"基于 4 天冷启动数据，在垂直细分品类（肉类加工设备，41 SKU，3 站点）中成立。设计必须**向上兼容**——当扩展至 100+ SKU / 多品类时，日报 smart send 永远为 True 不是 bug，是正确行为。周报/月报在高频场景下更有价值（趋势更清晰），无需特殊处理。

---

## 2. 设计总览

### 2.1 架构选型：层级配置 + snapshot-first 演进（方案 C 修订版）

保持现有模块化结构和 **snapshot-first 架构**。不新建入口函数，而是演进现有 `generate_report_from_snapshot()`：

```python
# 演进路径（非替代）
generate_report_from_snapshot(snapshot, tier="daily", ...)
#                                      ^^^^^^ 新增参数
```

改造要点：
1. **引入 `ReportTier` 配置**：每个层级是配置字典，定义时间窗口、分析维度、模板、投递规则
2. **保留 snapshot freeze 合约**：`freeze_report_snapshot()` 加 tier 参数，snapshot 结构不变
3. **Bug 修复自然融入**：累积 KPI 成为所有 tier 的共享基础步骤

**不做的事**：
- 不拆分 `report_analytics.py` 为 8 个模块（独立 Tech Debt 任务，等功能稳定后再做）
- 不新建 `generate_report(tier, logical_date)` 入口（保留 snapshot-first）

### 2.2 四层报告体系

```
即时告警 (Alert)          ← P009 独立项目
  触发：新差评 ≤2星 / safety Level 1 / 价格变动 >15%
  产出：钉钉推送 + 安全告警邮件

每日简报 (Daily)          ← 定时，智能发送
  触发：每日 HH:MM
  产出：简报 HTML（存档）+ 邮件（有内容时）
  内容：累积 KPI 快照 + 窗口 delta + 新评论摘要

周报 (Weekly)             ← 每周一固定发送
  触发：每周一 HH:MM
  产出：V3 HTML + 4-sheet Excel + 邮件
  内容：完整聚类 + 风险排行 + 竞品对标 + 热力图 + 趋势图表

月报 (Monthly)            ← 每月 1 日固定发送
  触发：每月 1 日 HH:MM
  产出：V3 HTML + 6-sheet Excel + 邮件
  内容：周报全部 + 品类对标 + 问题生命周期 + SKU 计分卡 + LLM 高管摘要
```

注意：即时告警（AlertWorker）从 P008 中分离为独立的 **P009**，因其触发机制、SLA、失败模式与报告体系完全不同。P008 仅在 Phase 1 建立 `safety_incidents` 表作为共享基础设施。

### 2.3 关键设计决策记录

| # | 决策 | 理由 | 来源 |
|---|------|------|------|
| D1 | report_tier 新增列，不改 report_mode 旧值 | 现有 full/change/quiet 被 13+ 处引用，重命名是破坏性迁移 | Codex + 审查 |
| D2 | 问题生命周期不落表，派生计算 | 现有 compute_cluster_changes()/first_seen/last_seen 足够，避免过早 schema 承诺 | Codex |
| D3 | 状态用 active/receding/dormant/recurrent | "resolved" 暗示确定性，仅靠评论数据无法确认 | Codex + 批判派 |
| D4 | RCW 仅做内部排序，不进外部 KPI | 管理层指标必须简单可解释 | Codex |
| D5 | 品类映射用 CSV 配置，不建表 | 41 个 SKU 规模不需要数据库 | Codex |
| D6 | safety_incidents 表保留（纯审计） | 证据冻结不能事后补，合规需持久化 | 安全派 + 自主判断 |
| D7 | 放弃加权公式，用确定性状态机 | 小样本下加权公式无校准数据支撑，信号共线 | 批判派 + 建设派 |
| D8 | 新增 dormant 状态区分"不知道"和"已解决" | "没有新差评 ≠ 问题解决"，可能是销量下降/季节性 | 批判派 |
| D9 | 安全标签硬规则保护 | safety 问题不允许仅靠沉默判定为 dormant | 批判派 |
| D10 | 三层共享累积数据源 + 各层独有视角 | 数据一致性由共享查询保证，分析深度由 tier 配置控制 | 用户选择 |
| D11 | 保留 snapshot-first 架构，演进而非绕过 | snapshot freeze 是现有管线核心合约，P007 双视角建在其上 | 审查 Codex |
| D12 | AlertWorker 分离为 P009 | 事件驱动告警的 SLA/失败模式与报告不同，混合会互相阻塞 | 审查共识 |
| D13 | 模块拆分独立为 Tech Debt | 纯重构操作混在功能交付中风险高、价值低 | 审查共识 |
| D14 | full/change/quiet 渐进退役，不一次删除 | 13+ 触点需迁移清单，Phase 3 周报上线后再退役 quiet weekly_digest | 审查 Codex |
| D15 | SAFETY_TIERS 可配置化 | 当前关键词针对肉类加工设备，扩展品类时需要替换 | 审查批判派 |

### 2.4 时间窗口规范

所有 tier 使用**半开区间** `[since, until)`，与现有 `_logical_date_window()` 一致：

| Tier | since | until | 示例 |
|------|-------|-------|------|
| daily | 当日 00:00 CST | 次日 00:00 CST | [04-16 00:00, 04-17 00:00) |
| weekly | 上周一 00:00 CST | 本周一 00:00 CST | [04-07 00:00, 04-14 00:00) |
| monthly | 上月 1 日 00:00 CST | 本月 1 日 00:00 CST | [03-01 00:00, 04-01 00:00) |

- 所有时间使用 `config.SHANGHAI_TZ`（Asia/Shanghai，无 DST）
- 同一条评论会出现在日报和周报中——**这是设计意图**（weekly/monthly 是 daily 的超集聚合）
- 工具函数：新增 `_tier_date_window(tier, logical_date)` 统一计算所有 tier 的窗口

### 2.5 并发安全

月初周一三个 worker 可能同时触发。保护机制：

1. **序列化报告生成**：daily run 完成后再触发 weekly，weekly 完成后再触发 monthly。通过 WorkflowWorker 在 `_advance_run()` 中检查同日期的下级 run 是否完成实现
2. **周报生成前置条件**：检查窗口内所有 daily run 是否为终态（completed / needs_attention），未完成则等待（带超时）
3. **SQLite 全局 busy_timeout**：在 `get_conn()` 中统一设置 `PRAGMA busy_timeout = 5000`

### 2.6 范围外（独立项目）

| 项目 | 说明 | 状态 |
|------|------|------|
| **P009: 实时告警系统** | AlertWorker + 通知 debounce + 安全分级告警路径 + 价格变动告警 | 待启动 |
| **Tech Debt: 分析模块拆分** | report_analytics.py → 多模块 | 等 P008 Phase 3 稳定后 |
| **Tech Debt: full/change/quiet 完全退役** | 编写 13+ 触点迁移清单后执行 | 等 P008 Phase 3 上线后 |

---

## 3. Phase 1：日报正确性修复

> 目标：修复当前日报中所有已知 bug，不引入新功能

### 3.1 impact_category / failure_mode 端到端修复

**问题**：LLM 已产出这两个字段，但 4 处未消费。

**修复点**：

| # | 文件 | 位置 | 修改内容 |
|---|------|------|----------|
| 1 | `report.py` | `query_cumulative_data()` ~L1069 | SELECT 增加 `ra.impact_category, ra.failure_mode` |
| 2 | `models.py` | `get_reviews_with_analysis()` ~L1912 | SELECT 增加同上两字段 |
| 3 | `report_snapshot.py` | `freeze_report_snapshot()` enrichment ~L297 | 将这两个字段写入 snapshot review 记录 |
| 4 | `report_analytics.py` | `compute_cluster_severity()` | `impact_category == "safety"` 作为 severity 加分因子 |

### 3.2 累积 KPI 所有模式永远计算（消灭 N/A）

**问题**：Change/Quiet 模式不执行 `build_report_analytics()`，`cumulative_kpis` 为空，模板渲染 N/A。

**修复**：在 `generate_report_from_snapshot()` 中，无论 report_mode 是什么，都调用 `compute_kpis()` 基于累积数据计算 KPI。Change/Quiet 模板接收 `cumulative_kpis` 变量并渲染。

### 3.3 V3 HTML 双视角收口

**修复**：
- Tab 2 "今日变化" 填充窗口数据：新评论列表 + 价格/库存/评分变动表
- "全景数据" tab 改读 `snapshot.cumulative.reviews`
- 与邮件模板使用相同数据源，消除分裂

### 3.4 None 渲染人话化

**修复**：
- 模板中所有可能为 None 的字段统一用 Jinja2 过滤器：`{{ value|default("—", true) }}`
- 评分变化中 None → "已下架 / 无评分"（根据 stock_status 判断）

### 3.5 产物版本戳 `_meta`

每个 snapshot / analytics / HTML 产物增加 `_meta` 字段：

```python
"_meta": {
    "schema_version": "3",           # snapshot 结构版本（从 2 升到 3）
    "generator_version": __version__,
    "taxonomy_version": "v1",        # 已有
    "report_tier": "daily",          # 当前固定 daily，Phase 2 扩展
}
```

### 3.6 safety_incidents 表（纯审计，P008/P009 共享基础设施）

```sql
CREATE TABLE IF NOT EXISTS safety_incidents (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id         INTEGER NOT NULL REFERENCES reviews(id),
    product_sku       TEXT NOT NULL,
    safety_level      TEXT NOT NULL,        -- critical / high / moderate
    failure_mode      TEXT,
    evidence_snapshot TEXT NOT NULL,        -- JSON: 冻结的评论原文+图片+产品信息
    evidence_hash     TEXT NOT NULL,        -- SHA-256(evidence_snapshot)
    detected_at       TEXT NOT NULL,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
```

写入时机：翻译分析完成后，检测到安全关键词或 `impact_category == "safety"` → 立即写入。**关键词检测在原始英文文本上运行**，不依赖翻译成功——LLM 翻译失败时仍然冻结证据（安全优先于翻译）。

注：此表为审计日志，不含状态流转。行不可 UPDATE/DELETE（pre-compliance，完整 immutability 约束留待合规 epic）。

### 3.7 安全三级分级（可配置）

将 `_SAFETY_KEYWORDS: frozenset` 替换为可配置的分级 dict，默认从 `data/safety_tiers.json` 加载（fallback 到内置默认值）：

```json
{
  "critical": [
    "metal shaving", "metal debris", "metal particle", "metal flake",
    "grease in food", "oil contamination", "black substance",
    "contamina", "foreign object", "foreign material",
    "injury", "injured", "cut myself", "sliced finger",
    "burned", "electric shock", "exploded", "shattered"
  ],
  "high": [
    "rust on blade", "rust on plate", "rusty", "corrosion",
    "worn blade", "chipped blade", "blade broke",
    "motor overheating", "smoking", "burning smell",
    "seal failure", "leaking grease"
  ],
  "moderate": [
    "misaligned", "not aligned", "loose screw",
    "bolt came off", "wobbles", "tips over", "unstable"
  ]
}
```

新增 env var `SAFETY_TIERS_PATH=data/safety_tiers.json`。

severity 加分：critical +5, high +3, moderate +1（替代现有统一 +3）。

### 3.8 标签一致性检查

翻译入库后检测 sentiment_score 与 label polarity 矛盾，异常存入 `review_analysis.label_anomaly_flags`（新增 TEXT 列）。Phase 1 只做检测+存储，报告展示推到 Phase 3 周报的"标签质量"小节。

---

## 4. Phase 2：日报重构 + 基础设施

### 4.1 report_tier 列

```sql
ALTER TABLE workflow_runs ADD COLUMN report_tier TEXT DEFAULT 'daily';
```

- **不修改** `report_mode` 现有值（full/change/quiet/baseline 保持不变）
- 新 daily run 使用 `report_mode = 'standard'`，旧值通过代码兼容
- `update_workflow_run()` 的 `allowed` 白名单增加 `"report_tier"`

### 4.2 日报智能发送

替代现有 full/change/quiet 三模式路由：

```python
def should_send_daily_email(window_data) -> bool:
    if window_data["new_review_count"] > 0:
        return True
    if window_data["price_changes"] or window_data["stock_changes"] or window_data["rating_changes"]:
        return True
    return False  # 无变化不发，HTML 仍存档
```

现有 `detect_report_mode()` 和三分支渲染逻辑暂保留（不删除），通过 `report_tier == 'daily'` 走新路径，旧 run 走旧路径。渐进迁移，非一刀切。

### 4.3 日报内容结构——三区块设计

日报简报包含三个区块，前两个始终存在，第三个条件触发：

```
┌─ 日报简报 ────────────────────────────────────────────────┐
│                                                            │
│  ① 累积快照（始终存在）                                      │
│  健康指数: 72.3   差评率: 4.2%   高风险: 2   评论总量: 2581  │
│                                                            │
│  ② 今日变化（有内容时展示）                                  │
│  新评论:                                                    │
│  ★☆☆☆☆ 1HP Grinder #22 — "black oily substance..."        │
│    📸 3张图 · 587字详评 · ⚠安全关键词                        │
│    → 高关注度评论                                           │
│                                                            │
│  ★★★★★ Walton's #32 — "Best grinder I've owned"            │
│    47字 · 无图                                              │
│    → 常规好评                                               │
│                                                            │
│  库存变化: .5 HP Grinder 缺货 → 有货                        │
│                                                            │
│  ③ 需注意（条件触发，无事不显示）                             │
│  • ⚠ 安全: #22 Grinder 评论提及"black substance"            │
│  • 📉 竞品: Cabela's 3/4HP Grinder 评分 4.6→4.3 (-0.3)     │
│  • ✓ 静默观察: 质量稳定性问题已 14 天无新投诉                │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

#### "需注意"信号触发规则

所有信号均从现有数据推导，不需要新的数据采集：

| 信号 | 触发条件 | 数据来源 | 说明 |
|------|----------|----------|------|
| **安全关键词命中** | 新评论匹配 SAFETY_TIERS 任何级别 | review body + safety_tiers.json | 最高优先级 |
| **图片证据** | 新评论包含图片 | reviews.images | 有图差评可信度远高于无图 |
| **竞品评分异动** | 竞品产品评分单日变化 ≥ 0.3 | product_snapshots delta | 竞品出问题 = 机会窗口 |
| **连续差评** | 同一 SKU 7 天内 ≥ 2 条差评（≤2星） | reviews 近 7 天窗口 | 单条是噪声，连续是信号 |
| **自有产品缺货** | 自有产品从 in_stock → out_of_stock | product_snapshots delta | 直接影响销售 |
| **静默好消息** | 已知活跃问题 14+ 天无新投诉 | cumulative clusters last_seen | "没有坏消息"本身是好消息 |

无事发生的日子，"需注意"区块不渲染——日报就是 ① 累积快照一行，3 秒扫完。

#### 新评论"重量"标签

日报中每条新评论附带人话化的重量标签，帮管理层 5 秒判断是否值得点进去看：

```python
def review_attention_label(review, safety_level):
    """生成人话化重量标签，不暴露 RCW 分数"""
    signals = []
    if safety_level:
        signals.append(f"⚠安全关键词({safety_level})")
    images = review.get("images") or []
    if images:
        signals.append(f"📸 {len(images)}张图")
    body_len = len(review.get("body", ""))
    if body_len > 300:
        signals.append(f"{body_len}字详评")
    elif body_len < 50:
        signals.append("短评")

    if safety_level == "critical" or (review["rating"] <= 2 and len(images) > 0):
        label = "高关注度评论"
    elif review["rating"] <= 2:
        label = "差评"
    elif review["rating"] >= 4:
        label = "常规好评"
    else:
        label = "中评"

    return {"signals": signals, "label": label}
```

注意：这使用了 RCW 的**信号因子**（图片、长度、安全关键词），但**不展示 RCW 数值本身**（遵守 D4 决策）。

### 4.4 安全三级分级闭环

将 `impact_category` 接入下游管线（基于 Phase 1 的端到端修复）：
- `compute_cluster_severity()` 中 `impact_category == "safety"` 给额外加分
- `_risk_products()` 的风险评分增加安全因子
- V3 HTML 和邮件模板中 safety 评论加红色安全标记

### 4.4 收件人分通道

```env
EMAIL_RECIPIENTS_EXEC=           # 高管（周报/月报摘要）
EMAIL_RECIPIENTS_SAFETY=         # 安全告警（P009 使用）
```

### 4.5 Tier 配置数据结构

```python
TIER_CONFIGS = {
    "daily": {
        "window":      "24h",
        "cumulative":  True,
        "dimensions":  ["kpi", "clusters", "competitive_gap",
                        "attention_signals"],  # 需注意信号（条件触发）
        "template":    "daily_briefing.html.j2",
        "excel":       False,
        "delivery":    {"email": "smart", "archive": True},
    },
    "weekly": {
        "window":      "7d",
        "cumulative":  True,
        "dimensions":  ["kpi", "clusters", "competitive_gap",
                        "risk_ranking", "heatmap", "trend_charts"],
        "template":    "weekly_report.html.j2",
        "excel":       True,
        "delivery":    {"email": "always", "archive": True},
    },
    "monthly": {
        "window":      "month",
        "cumulative":  True,
        "dimensions":  ["kpi", "clusters", "competitive_gap",
                        "risk_ranking", "heatmap", "trend_charts",
                        "category_benchmark", "issue_lifecycle",
                        "product_scorecard", "executive_summary"],
        "template":    "monthly_report.html.j2",
        "excel":       True,
        "delivery":    {"email": "always", "archive": True},
    },
}
```

---

## 5. Phase 3：周报

### 5.1 WeeklySchedulerWorker

```python
class WeeklySchedulerWorker:
    """每周一 HH:MM 触发"""
    
    def process_once(self):
        now = now_shanghai()
        if now.weekday() != 0:  # 0 = Monday
            return False
        logical_date = now.date().isoformat()
        trigger_key = f"weekly:{logical_date}"
        if models.get_workflow_run_by_trigger_key(trigger_key):
            return False  # 幂等
        
        # 前置检查：窗口内所有 daily run 已完成
        if not _all_daily_runs_terminal(since, until):
            return False  # 等待，下次轮询重试
        
        return submit_weekly_run(logical_date)
```

窗口：上一自然周 `[上周一 00:00 CST, 本周一 00:00 CST)`。

### 5.2 _advance_run() 改造

现有 `_advance_run()` 的 fast_pending → full_pending 级联是 daily 专属。周报/月报使用**简化单阶段管线**（跳过 fast report，直接生成完整报告）：

```python
def _advance_run(self, run_id):
    run = get_workflow_run(run_id)
    
    if run["report_tier"] == "daily":
        return self._advance_daily_run(run)  # 现有逻辑
    else:
        return self._advance_periodic_run(run)  # 新增简化路径

def _advance_periodic_run(self, run):
    """周报/月报：无 fast report，直接 full"""
    # 1. 等翻译完成（复用现有翻译等待逻辑）
    # 2. freeze snapshot
    # 3. generate_report_from_snapshot(snapshot, tier=run["report_tier"])
    # 4. 发送邮件 + 完成
```

### 5.3 get_previous_completed_run() 支持 tier 参数

```python
def get_previous_completed_run(workflow_type="daily", report_tier=None):
    """查找同 tier 的上一个已完成 run，用于 KPI delta 计算"""
    sql = "WHERE workflow_type = ? AND status = 'completed'"
    if report_tier:
        sql += " AND report_tier = ?"
    sql += " ORDER BY logical_date DESC LIMIT 1"
```

### 5.4 周报模板

沿用 V3 设计语言，Tab 结构：

```
Tab 1: 总览        — 累积 KPI + 本周 delta + Hero Headline + AI Bullets
Tab 2: 本周变化    — 新增评论列表 + 价格/库存/评分变动
Tab 3: 问题诊断    — 完整聚类分析（累积数据）+ 严重度排序
Tab 4: 产品排行    — 风险产品 TOP 5 + 所有产品评分/评论数
Tab 5: 竞品对标    — 差距指数维度明细 + 基准示例
Tab 6: 全景数据    — 热力图 + 趋势图表（周度）
```

### 5.5 退役 quiet weekly_digest

`should_send_quiet_email()` 中"第 7 天发 weekly_digest"逻辑删除。正式周报完全替代。

### 5.6 冷启动保护

首次周报可能不满一周。在 `_meta` 中标记：

```python
"_meta": {
    ...
    "is_partial": True,           # 数据不满完整周期
    "expected_days": 7,
    "actual_days": 4,
}
```

模板中渲染提示："本周报覆盖 4/7 天数据，为部分周期报告"。

月报同理：品类对标和生命周期分析的最小数据门槛：
- 生命周期分析：需 ≥ 30 天历史数据，否则显示"数据积累中"
- 品类对标：需每品类 ≥ 3 个 SKU（同一 ownership），否则该品类显示"样本不足"

### 5.7 跨 SKU 扩散度检测

周报的 issue 卡片增加 `dispersion_type` 标注：

```python
def compute_dispersion(label_code, ownership, reviews):
    affected_skus = set(r["product_sku"] for r in reviews if label_code in r["labels"])
    total_skus = count_skus_by_ownership(ownership)
    ldi = len(affected_skus) / total_skus if total_skus > 0 else 0
    
    if ldi > 0.2:
        return "systemic", affected_skus   # 系统性问题（供应链/设计）
    elif ldi < 0.1 and len(affected_skus) <= 2:
        return "isolated", affected_skus   # 个体问题（批次）
    else:
        return "uncertain", affected_skus  # 待观察
```

### 5.8 RCW 内部排序

```python
def credibility_weight(review):
    w = 1.0
    body_len = len(review.get("body", ""))
    if body_len > 500: w *= 1.5
    elif body_len < 50: w *= 0.6
    images = review.get("images") or []
    if images: w *= 1.0 + min(len(images), 3) * 0.15
    # 优先使用已解析的日期，fallback 到 days_old=0（无法解析视为最新）
    parsed = review.get("date_published_parsed")
    if parsed:
        days_old = (today - parse_date(parsed)).days
        w *= 0.5 ** (days_old / 180)  # 半衰期 6 个月
    return w
```

用于 issue 卡片"关键评论"排序、状态机 R1 低可信度过滤。不进入外部 KPI。

### 5.9 标签质量小节

周报中展示 Phase 1 存储的 `label_anomaly_flags` 统计：可疑标注数量 + 涉及标签 + 建议操作。

### 5.10 周报 Excel（4-sheet 分析版）

数据源改为全量累积评论 + "本周新增"标记列：
- Sheet 1: 评论明细（全量，"本次新增"列标记本周评论）
- Sheet 2: 产品概览（含风险评分）
- Sheet 3: 问题标签（exploded）
- Sheet 4: 趋势数据（周度）

---

## 6. Phase 4：月报

### 6.1 MonthlySchedulerWorker

```python
class MonthlySchedulerWorker:
    """每月 1 日 HH:MM 触发"""
    def process_once(self):
        now = now_shanghai()
        if now.day != 1:
            return False
        logical_date = now.date().isoformat()
        trigger_key = f"monthly:{logical_date}"
        if models.get_workflow_run_by_trigger_key(trigger_key):
            return False
        return submit_monthly_run(logical_date)
```

窗口：上月整月 `[上月 1 日 00:00, 本月 1 日 00:00)`。用 `max(data_since, earliest_review_scraped_at)` 处理部署不满一月的情况。

### 6.2 月报模板——分层阅读

```
第 1 屏（高管）:
  - 本月质量态势一句话（"稳中向好 / 需要关注 / 紧急行动"）
  - 3 个核心 KPI 卡片（健康指数 + 差评率 + 高风险产品）+ delta
  - AI 高管摘要（3 条 bullet）
  - 安全事件摘要（如有）

Tab 1: 总览        — 完整 KPI 矩阵 + 月度 delta + 4 周趋势线
Tab 2: 本月变化    — 新增评论汇总 + 重大变动
Tab 3: 问题诊断    — 聚类分析 + 问题生命周期卡片
Tab 4: 品类对标    — 品类矩阵（自有 vs 竞品，按 Grinder/Slicer/Mixer 等分组）
Tab 5: 产品计分卡  — 每个 SKU 的红黄绿灯 + 风险评分变化
Tab 6: 竞品对标    — 差距指数趋势 + 维度明细
Tab 7: 全景数据    — 热力图 + 月度趋势图表
```

### 6.3 品类对标（CSV 配置驱动）

配置文件 `data/category_map.csv`：

```csv
sku,category,sub_category,price_band_override
1159178,grinder,single_grind,
1193465,grinder,dual_grind,
192238,slicer,,
192234,mixer,,
1200642,stuffer,motorized,
1117120,saw,,
1159181,accessory,pedal,
```

- `price_band_override` 为空时按价格自动计算（budget <$200 / mid $200-600 / premium >$600）
- 有值时使用覆盖值（支持未来多品类不同价格段）
- 品类对标最小门槛：每品类 ≥ 3 个 SKU（同 ownership），不足时显示"样本不足"

### 6.4 问题生命周期（派生计算）

#### 状态定义

| 状态 | 含义 | 颜色 | 报告呈现 |
|------|------|------|----------|
| `active` | 近期有负面评论命中 | 红 | 需要行动 |
| `receding` | 负面频率下降或出现正面对冲 | 黄 | 持续观察 |
| `dormant` | 长期无新信号，状态未知 | 灰 | 信息不足 |
| `recurrent` | 曾经 dormant 但又出现负面 | 深红 | 高优先级（复发） |

注意：没有 "resolved" 状态。仅靠评论数据无法确认问题已解决。

#### 转移规则

```
R1: 新负面评论命中（RCW > 0.5）→ active
    （低可信度评论不单独触发状态转移）
R2: active + 正面对冲评论 + 近 30 天 neg/pos ≤ 1:1
    + 30 天窗口内 ≥ 3 条评论 → receding
    （最小样本量门槛：避免 1:1 = 1 条 vs 1 条的虚假转换）
R3: active/receding + 连续 silence_window 天无新负面 → dormant
R4: dormant + 新负面评论 → recurrent（标记为复发）
R5: recurrent 后续行为与 active 相同（可进入 receding/dormant）
R6: safety_level = critical 的问题，silence_window 翻倍
```

#### 动态沉默窗口

```python
def silence_window(label_code, ownership):
    avg_interval = avg_days_between_reviews(label_code, ownership)
    return clamp(avg_interval * 2, min_val=14, max_val=60)
```

#### 性能优化

```python
def derive_all_lifecycles(all_reviews, window_end):
    """预分组后逐 label 回放，避免 O(labels × reviews)"""
    # Step 1: 按 (label_code, ownership) 预分组 — O(reviews)
    label_index = defaultdict(list)
    for r in all_reviews:
        for label in extract_labels(r):
            key = (label["code"], r["ownership"])
            label_index[key].append(r)
    
    # Step 2: 逐 label 回放状态机 — O(relevant_reviews)
    results = {}
    for (label_code, ownership), relevant in label_index.items():
        results[(label_code, ownership)] = derive_issue_lifecycle(
            label_code, ownership, relevant, window_end
        )
    return results
```

### 6.5 SKU 健康计分卡

月报独有。灯号判定：
- 🟢 风险分 < 15 且差评率 < 3%
- 🟡 风险分 15-35 或差评率 3-8%
- 🔴 风险分 > 35 或差评率 > 8% 或有 safety Level 1/2 事件

### 6.6 LLM 高管摘要

月报独有。输入：累积 KPI delta + TOP 3 问题 + 品类对标 + 安全事件。输出：态势判断 + 3 bullet + 2-3 建议行动。

### 6.7 月报 Excel（6-sheet 扩展版）

周报 4-sheet + Sheet 5 品类对标 + Sheet 6 SKU 计分卡。

---

## 7. 数据库变更汇总

### 新增表

```sql
CREATE TABLE IF NOT EXISTS safety_incidents (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id         INTEGER NOT NULL REFERENCES reviews(id),
    product_sku       TEXT NOT NULL,
    safety_level      TEXT NOT NULL,
    failure_mode      TEXT,
    evidence_snapshot TEXT NOT NULL,
    evidence_hash     TEXT NOT NULL,
    detected_at       TEXT NOT NULL,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### 现有表变更

```sql
-- Phase 2: workflow_runs 新增 tier 列（Phase 1 不改）
ALTER TABLE workflow_runs ADD COLUMN report_tier TEXT DEFAULT 'daily';

-- Phase 1: review_analysis 新增标签异常标记
ALTER TABLE review_analysis ADD COLUMN label_anomaly_flags TEXT;
```

### 全局 SQLite 配置

```python
# 在 get_conn() 中统一设置
conn.execute("PRAGMA busy_timeout = 5000")
```

### update_workflow_run() 白名单

Phase 2 中将 `"report_tier"` 加入 `models.py:update_workflow_run()` 的 `allowed` set。

---

## 8. 修改文件清单

### Phase 1（日报正确性修复）

| 操作 | 文件 | 说明 |
|------|------|------|
| 修改 | `report.py` | query_cumulative_data() 增加 impact_category/failure_mode |
| 修改 | `models.py` | get_reviews_with_analysis() 增加同上 + safety_incidents 建表 + busy_timeout + label_anomaly_flags 列 |
| 修改 | `report_snapshot.py` | freeze enrichment 增加字段 + _meta 版本戳 |
| 修改 | `report_common.py` | SAFETY_TIERS 替换 _SAFETY_KEYWORDS + severity 加分调整 |
| 修改 | `report_html.py` | V3 HTML Tab 2 填充 + 全景 tab 改读累积 |
| 修改 | `daily_report_v3.html.j2` | 同上模板修改 |
| 修改 | `email_change.html.j2` | None 人话化 + 累积 KPI 显示 |
| 修改 | `email_quiet.html.j2` | 累积 KPI 永远显示 |
| 修改 | `translator.py` | 标签一致性检查 + 安全关键词检测→写 safety_incidents |
| 修改 | `config.py` | SAFETY_TIERS_PATH env var |
| 新增 | `data/safety_tiers.json` | 安全关键词配置 |

### Phase 2（日报重构 + 基础设施）

| 操作 | 文件 | 说明 |
|------|------|------|
| 修改 | `models.py` | report_tier 列 + update_workflow_run 白名单 |
| 修改 | `report_snapshot.py` | generate_report_from_snapshot(tier=) 参数 + 日报智能发送 |
| 修改 | `workflows.py` | report_tier 支持 + _advance_run 新旧路径分流 |
| 修改 | `config.py` | 收件人分组 + tier 调度时间 |
| 修改 | `report_common.py` | impact_category 闭环到风险评分 |

### Phase 3（周报）

| 操作 | 文件 | 说明 |
|------|------|------|
| 修改 | `workflows.py` | WeeklySchedulerWorker + _advance_periodic_run |
| 修改 | `models.py` | get_previous_completed_run(report_tier=) |
| 修改 | `report_snapshot.py` | 退役 quiet weekly_digest |
| 新增 | `report_templates/weekly_report.html.j2` | 周报 V3 模板 |
| 新增 | `report_templates/email_weekly.html.j2` | 周报邮件模板 |

### Phase 4（月报）

| 操作 | 文件 | 说明 |
|------|------|------|
| 修改 | `workflows.py` | MonthlySchedulerWorker |
| 新增 | `analytics_lifecycle.py` | 问题生命周期派生 |
| 新增 | `analytics_category.py` | 品类对标 |
| 新增 | `analytics_scorecard.py` | SKU 计分卡 |
| 新增 | `analytics_executive.py` | LLM 高管摘要 |
| 新增 | `report_templates/monthly_report.html.j2` | 月报模板 |
| 新增 | `report_templates/email_monthly.html.j2` | 月报邮件模板 |
| 新增 | `data/category_map.csv` | 品类映射配置 |

---

## 9. 环境变量新增

```env
# Phase 1
SAFETY_TIERS_PATH=data/safety_tiers.json

# Phase 2
WEEKLY_SCHEDULER_TIME=09:30
MONTHLY_SCHEDULER_TIME=09:30
EMAIL_RECIPIENTS_EXEC=
EMAIL_RECIPIENTS_SAFETY=

# Phase 4
CATEGORY_MAP_PATH=data/category_map.csv
```

---

## 10. 验收标准

### Phase 1

- [ ] 所有报告中健康指数和差评率永远有值（不出现 N/A）
- [ ] V3 HTML Tab 2 展示窗口数据，全景 Tab 展示累积数据
- [ ] 评分变为 None 时显示"—"或"已下架"
- [ ] impact_category/failure_mode 在 snapshot 和分析中可见
- [ ] safety_incidents 表有证据冻结记录（安全关键词命中时）
- [ ] 标签一致性异常被检测并存储

### Phase 2

- [ ] 无变化的日子不发邮件，HTML 仍存档
- [ ] report_tier 列正确填充
- [ ] 安全评论在报告中有分级红色标记
- [ ] 不同收件人列表可独立配置
- [ ] 日报三区块结构：累积快照 + 今日变化 + 需注意（条件触发）
- [ ] 新评论附带人话化重量标签（高关注度 / 差评 / 常规好评）
- [ ] "需注意"区块在安全命中/竞品异动/连续差评/缺货/静默好消息时出现
- [ ] 无事日不渲染"需注意"区块

### Phase 3

- [ ] 每周一自动生成周报 HTML + Excel + 邮件
- [ ] 周报生成前确认窗口内 daily run 已完成
- [ ] 不完整周期在报告中有提示
- [ ] issue 卡片标注"系统性"/"个体"扩散度
- [ ] KPI delta 正确基于上次同 tier 的 run 计算

### Phase 4

- [ ] 每月 1 日自动生成月报
- [ ] 月报第 1 屏含高管摘要（态势 + 3 bullet + 行动建议）
- [ ] 品类对标按 Grinder/Slicer/Mixer 等分组
- [ ] 样本不足的品类显示"样本不足"而非误导性数据
- [ ] 问题生命周期展示 active/receding/dormant/recurrent
- [ ] 问题卡片展示时间线 + 评论原文片段 + 竞品参照
- [ ] SKU 计分卡展示红黄绿灯 + 趋势方向

---

## 11. 测试策略

### 时间注入

复用现有 `logical_date` 和 `now` 参数注入机制（`workflows.py:128, 389`），周报/月报 Worker 同样支持：

```python
# 测试周报不需要等一周
submit_weekly_run(logical_date="2026-04-14", now_override=...)
submit_monthly_run(logical_date="2026-05-01", now_override=...)
```

### 快照对比

每个 Phase 的验收测试使用 `data/reports2/` 中的现有产物作为对比基准，验证修复效果（如 N/A 消除、None 渲染修复）。
