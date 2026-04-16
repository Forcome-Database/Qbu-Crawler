# P008 — 三层报告体系 + Bug 修复 + 安全增强

> **关联需求**：诊断发现的 5 个 P0/P1 Bug + 日报警报疲劳 + 缺乏周报/月报 + 安全问题无分级
> **前置条件**：P006（报告 Bug 修复）+ P007（双视角架构）已部分落地
> **优先级**：P0
> **预估工作量**：分 4 个 Phase，总计 3-4 周
> **决策记录**：brainstorming 于 2026-04-16，含批判性/建设性/Codex 三方审查

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
6. **impact_category 管线断裂**：LLM 已产出但累积查询和分析未消费

### 1.3 当前代码已有基础

P006/P007 已部分落地，不是从零开始：
- `workflows.py:632` — Change/Quiet 路由已修复（不再 early return）
- `report_snapshot.py:274` — 双视角快照结构已存在
- `report_analytics.py:1537` — `build_dual_report_analytics()` 已实现
- `report_common.py:493` — 健康指数贝叶斯收缩已实现
- `email_full.html.j2` — 邮件模板已支持累积 KPI

---

## 2. 设计总览

### 2.1 架构选型：层级配置 + 分析模块化（方案 C）

保持现有模块化结构（report.py / report_analytics.py / report_common.py / report_html.py），通过以下改造实现三层报告：

1. **引入 `ReportTier` 配置**：每个层级是配置字典，定义时间窗口、分析维度、模板、投递规则
2. **拆分分析维度为独立模块**：将 `report_analytics.py`（~1600 行）按维度拆分
3. **统一入口**：`generate_report(tier, logical_date)` 一个函数走天下
4. **Bug 修复自然融入**：累积 KPI 成为所有 tier 的共享基础步骤

不采用 OOP 重构（方案 B），因为 3 个层级的差异主要在"分析维度"和"模板"，核心查询和 KPI 计算完全共享。

### 2.2 四层报告体系

```
即时告警 (Alert)          ← 事件驱动，分钟级
  触发：新差评 ≤2星 / safety Level 1 / 价格变动 >15%
  产出：钉钉推送 + 安全告警邮件
  渠道：钉钉 @所有人（安全）/ 钉钉普通（非安全）

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

### 2.3 关键设计决策记录

| # | 决策 | 理由 | 来源 |
|---|------|------|------|
| D1 | report_tier 与 report_mode 分离 | report_mode 已承载 full/change/quiet，再塞 daily/weekly/monthly 会语义混乱 | Codex |
| D2 | 问题生命周期不落表，派生计算 | 现有 compute_cluster_changes()/first_seen/last_seen 足够，避免过早 schema 承诺 | Codex |
| D3 | 状态用 active/receding/dormant/recurrent | "resolved" 暗示确定性，仅靠评论数据无法确认 | Codex + 批判派 |
| D4 | RCW 仅做内部排序，不进外部 KPI | 管理层指标必须简单可解释 | Codex |
| D5 | 品类映射用 CSV 配置，不建表 | 41 个 SKU 规模不需要数据库 | Codex |
| D6 | safety_incidents 表保留（纯审计） | 证据冻结不能事后补，合规需持久化 | 安全派 + 自主判断 |
| D7 | 放弃加权公式，用确定性状态机 | 小样本下加权公式无校准数据支撑，信号共线 | 批判派 + 建设派 |
| D8 | 新增 dormant 状态区分"不知道"和"已解决" | "没有新差评 ≠ 问题解决"，可能是销量下降/季节性 | 批判派 |
| D9 | 安全标签硬规则保护 | safety 问题不允许仅靠沉默判定为 resolved | 批判派 |
| D10 | 三层共享累积数据源 + 各层独有视角 | 数据一致性由共享查询保证，分析深度由 tier 配置控制 | 用户选择 |

---

## 3. Phase 1：Bug 修复 + 基础设施

> 目标：收口现有缺陷，为三层体系打好地基

### 3.1 累积 KPI 所有 tier 永远计算（消灭 N/A）

**问题**：Change/Quiet 模式不执行 `build_report_analytics()`，`cumulative_kpis` 为空，模板渲染 N/A。

**修复**：在报告生成管道的第一步，无条件调用 `compute_cumulative_kpis()`：

```python
def generate_report(tier: str, logical_date: str):
    # Step 1: 累积 KPI — 永远计算，不允许 N/A
    cumulative_data = query_cumulative_data()
    cumulative_kpis = compute_kpis(cumulative_data)
    
    # Step 2: 窗口数据
    window_data = query_window_data(data_since, data_until)
    window_delta = compute_window_delta(window_data, cumulative_kpis)
    
    # Step 3: 按 tier 配置运行分析模块
    analytics = run_analysis_modules(TIER_CONFIGS[tier], cumulative_data, window_data)
    
    # Step 4: 渲染
    ...
```

### 3.2 V3 HTML 双视角收口

**问题**：
- Tab 2 "今日变化" 仍是占位符（`daily_report_v3.html.j2:140`）
- "全景数据" tab 读 `snapshot.reviews`（窗口数据），不是累积视角

**修复**：
- Tab 2 填充窗口数据：新评论列表 + 价格/库存/评分变动表
- "全景数据" tab 改读 `snapshot.cumulative.reviews`
- 与邮件模板使用相同数据源，消除分裂

### 3.3 impact_category / failure_mode 带入累积查询

**问题**：`query_cumulative_data()` 的 JOIN 缺少这两个字段，安全链路阻塞。

**修复**：在 `report.py:1048` 的 `query_cumulative_data()` SQL 中增加：

```sql
SELECT ...
    ra.impact_category,
    ra.failure_mode,
    ...
FROM reviews r
LEFT JOIN review_analysis ra ON r.id = ra.review_id
...
```

### 3.4 None 渲染人话化

**问题**：评分从 3.6 变为 Python None 时，模板原样渲染 "None"。

**修复**：
- 模板中所有可能为 None 的字段统一用 Jinja2 过滤器：`{{ value|default("—", true) }}`
- 评分变化中 None → "已下架 / 无评分"（根据 stock_status 判断）

### 3.5 report_tier 与 report_mode 拆分

**问题**：`workflow_runs.report_mode` 已承载 full/change/quiet/baseline。

**修复**：
- 新增 `workflow_runs.report_tier` 列：`daily / weekly / monthly`
- `report_mode` 简化为 `standard / baseline`（daily 层不再区分 full/change/quiet）
- baseline 判断：该 tier 的首次 run（如 weekly 的首次 run、monthly 的首次 run）
- 旧值兼容：遇到 `report_mode in (full, change, quiet)` 的旧 run 时，`report_tier` 默认推断为 `daily`，`report_mode` 映射为 `standard`

```sql
ALTER TABLE workflow_runs ADD COLUMN report_tier TEXT DEFAULT 'daily';
```

### 3.6 产物版本戳

**修复**：每个 snapshot / analytics / HTML 产物增加 `_meta` 字段：

```python
"_meta": {
    "schema_version": "3",           # snapshot 结构版本（从 2 升到 3）
    "generator_version": __version__,
    "taxonomy_version": "v1",        # 已有
    "report_tier": tier,             # daily/weekly/monthly
    "git_commit": get_git_commit(),  # 可选，部署环境可能无 git
}
```

### 3.7 安全三级分级

**修复**：将 `_SAFETY_KEYWORDS: frozenset` 替换为分级 dict：

```python
SAFETY_TIERS = {
    "critical": [   # Level 1: 食品污染 + 人身伤害
        "metal shaving", "metal debris", "metal particle", "metal flake",
        "grease in food", "oil contamination", "black substance",
        "contamina", "foreign object", "foreign material",
        "injury", "injured", "cut myself", "sliced finger",
        "burned", "electric shock", "exploded", "shattered",
    ],
    "high": [       # Level 2: 设备退化风险
        "rust on blade", "rust on plate", "rusty", "corrosion",
        "worn blade", "chipped blade", "blade broke",
        "motor overheating", "smoking", "burning smell",
        "seal failure", "leaking grease",
    ],
    "moderate": [   # Level 3: 装配/设计缺陷
        "misaligned", "not aligned", "loose screw",
        "bolt came off", "wobbles", "tips over", "unstable",
    ],
}
```

`compute_cluster_severity()` 中根据最高匹配级别给不同加分：critical +5, high +3, moderate +1。

同时将 LLM 已产出的 `impact_category == "safety"` 作为补充信号：
- 关键词匹配 + LLM 同时命中 → 使用关键词级别
- 仅 LLM 命中 → 默认 moderate
- 仅关键词命中 → 使用关键词级别

### 3.8 impact_category 闭环

将 `impact_category` 接入下游管线：
- `compute_cluster_severity()` 中 `impact_category == "safety"` 给额外加分
- `_risk_products()` 的风险评分增加安全因子
- V3 HTML 和邮件模板中 safety 评论加红色安全标记

### 3.9 safety_incidents 表（纯审计）

```sql
CREATE TABLE IF NOT EXISTS safety_incidents (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id         INTEGER NOT NULL REFERENCES reviews(id),
    product_sku       TEXT NOT NULL,
    safety_level      TEXT NOT NULL,        -- critical / high / moderate
    failure_mode      TEXT,                 -- 从 review_analysis 复制
    evidence_snapshot TEXT NOT NULL,        -- JSON: 冻结的评论原文+图片+产品信息
    evidence_hash     TEXT NOT NULL,        -- SHA-256(evidence_snapshot)
    detected_at       TEXT NOT NULL,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
```

入库时机：翻译完成 → 检测到安全关键词或 `impact_category == "safety"` → 立即写入。
不含状态流转字段——这是审计日志，不是工作流。

### 3.10 标签一致性检查

翻译入库后检测 sentiment_score 与 label polarity 的矛盾：

```python
def check_label_consistency(review, labels):
    for label in labels:
        if label["polarity"] == "negative" and review.sentiment_score > 0.7:
            flag_anomaly(review.id, label["code"], "sentiment_label_mismatch")
        if label["polarity"] == "positive" and review.sentiment_score < 0.3:
            flag_anomaly(review.id, label["code"], "sentiment_label_mismatch")
```

异常记录存入 `review_analysis.label_anomaly_flags`（新增 TEXT 列，JSON 数组），周报中展示"标签质量"小节。

---

## 4. Phase 2：日报重构 + 即时告警

### 4.1 统一报告入口

```python
TIER_CONFIGS = {
    "daily": {
        "window":      "24h",
        "cumulative":  True,
        "dimensions":  ["kpi", "clusters", "competitive_gap"],
        "template":    "daily_briefing.html.j2",
        "excel":       False,
        "delivery": {
            "email": "smart",    # 有内容才发
            "dingtalk": False,
            "archive": True,
        },
    },
    "weekly": { ... },
    "monthly": { ... },
}

def generate_report(tier: str, logical_date: str, **kwargs):
    """统一入口，替代现有的模式分支"""
    config = TIER_CONFIGS[tier]
    ...
```

### 4.2 日报智能发送

替代现有 full/change/quiet 三模式：

```python
def should_send_daily_email(window_data) -> bool:
    if window_data["new_review_count"] > 0:
        return True
    if window_data["price_changes"] or window_data["stock_changes"] or window_data["rating_changes"]:
        return True
    return False  # 无变化不发，HTML 仍存档
```

### 4.3 退役 full/change/quiet 模式

- 删除 `detect_report_mode()` 中的三分支逻辑
- `report_mode` 列对日报 tier 统一设为 `standard`
- 保留 `baseline` 模式判断（首次运行时的特殊处理）

### 4.4 AlertWorker：即时告警

```python
class AlertWorker:
    """事件驱动，不走 workflow run"""
    
    def on_review_analyzed(self, review, analysis):
        """翻译+分析完成后回调"""
        safety_level = detect_safety_level(review, analysis)
        
        # Safety Level 1: 即时告警
        if safety_level == "critical":
            self._send_safety_alert(review, analysis, safety_level)
        
        # 新差评即时告警
        if review.rating <= 2 and review.ownership == "own":
            self._send_negative_alert(review, analysis)
        
        # 价格剧变告警（>15%）
        price_change = detect_price_change(review.product_sku)
        if price_change and abs(price_change.pct) > 0.15:
            self._send_price_alert(price_change)
    
    def _send_safety_alert(self, review, analysis, level):
        # 写入 safety_incidents
        freeze_safety_evidence(review, analysis, level)
        # 钉钉：独立安全告警模板
        enqueue_notification(kind="safety_alert", channel="dingtalk", ...)
        # 邮件：安全专用收件人
        send_safety_email(SAFETY_ALERT_RECIPIENTS, review, analysis)
```

触发时机：在 `TranslationWorker._analyze_and_translate_batch()` 中每条评论翻译+分析完成后同步调用 `AlertWorker.on_review_analyzed()`。AlertWorker 不是独立线程，而是 TranslationWorker 的回调——评论分析完成时立即检查是否需要告警，不依赖后续的报告生成流程。如果翻译失败但关键词匹配命中 safety critical，仍然触发告警（安全优先于翻译）。

### 4.5 收件人分通道

```env
# .env
EMAIL_RECIPIENTS=product@company.com,rd@company.com    # 所有报告
EMAIL_RECIPIENTS_EXEC=ceo@company.com                   # 周报/月报摘要
EMAIL_RECIPIENTS_SAFETY=safety@company.com              # 安全告警
```

加载优先级：env vars > config file（沿用现有 `_get_email_recipients()` 的 fallback 链）。

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
        
        return submit_weekly_run(logical_date)
```

weekly run 的 `data_since` 和 `data_until` 跨上一自然周（上周一 00:00 CST → 本周一 00:00 CST）。所有时间使用上海时区 (`config.SHANGHAI_TZ`)。

### 5.2 周报模板

沿用 V3 设计语言（CSS 变量、Tab 导航、Gauge 组件），Tab 结构：

```
Tab 1: 总览        — 累积 KPI + 本周 delta + Hero Headline + AI Bullets
Tab 2: 本周变化    — 新增评论列表 + 价格/库存/评分变动
Tab 3: 问题诊断    — 完整聚类分析（累积数据）+ 严重度排序
Tab 4: 产品排行    — 风险产品 TOP 5 + 所有产品评分/评论数
Tab 5: 竞品对标    — 差距指数维度明细 + 基准示例
Tab 6: 全景数据    — 热力图 + 趋势图表（周度）
```

### 5.3 退役 quiet weekly_digest

`should_send_quiet_email()` 中"第 7 天发 weekly_digest"逻辑删除。正式周报完全替代。

### 5.4 跨 SKU 扩散度检测

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

报告呈现：issue 卡片右上角标注 badge（"系统性" / "个体" / "待观察"）。

### 5.5 RCW 内部排序

```python
def credibility_weight(review):
    w = 1.0
    body_len = len(review.get("body", ""))
    if body_len > 500: w *= 1.5
    elif body_len < 50: w *= 0.6
    images = review.get("images") or []
    if images: w *= 1.0 + min(len(images), 3) * 0.15
    days_old = (today - parse_date(review["date_published"])).days
    w *= 0.5 ** (days_old / 180)  # 半衰期 6 个月
    return w
```

用于：issue 卡片中"关键评论"排序、状态机 R1 的低可信度过滤。不进入外部 KPI。

### 5.6 周报 Excel（4-sheet 分析版）

与现有 analytical Excel 结构一致，但数据源改为全量累积评论 + "本周新增"标记列：

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

monthly run 的 `data_since` 和 `data_until` 跨上月整月（上月 1 日 00:00 → 本月 1 日 00:00），不是固定 30 天，以避免跨月边界问题。

### 6.2 月报模板——分层阅读

月报面向多受众，采用渐进式信息架构：

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
sku,category,sub_category
1159178,grinder,single_grind
1193465,grinder,dual_grind
1237342,grinder,dual_grind
192238,slicer,
192236,slicer,
192237,slicer,
192234,mixer,
192233,mixer,
1200642,stuffer,motorized
192252,stuffer,electric
1117120,saw,
1159181,accessory,pedal
1219604,accessory,lug
1202188,accessory,attachment
1202187,accessory,attachment
```

`price_band` 根据产品价格自动计算：

```python
PRICE_BANDS = {
    "budget":  (0, 200),
    "mid":     (200, 600),
    "premium": (600, float("inf")),
}
```

月报品类对标卡片结构：

```
┌─ Grinder 品类 ─────────────────────────────────────────┐
│                                                         │
│  自有 (8 SKU)              竞品 (5 SKU)                 │
│  ├ 均价: $621              ├ 均价: $580                  │
│  ├ 均分: 4.6               ├ 均分: 4.2                  │
│  ├ 差评率: 2.1%            ├ 差评率: 8.7%               │
│  └ 主要问题: 质量稳定性    └ 主要问题: 结构设计          │
│                                                         │
│  价格段对比:                                             │
│  ├ Budget (<$200):  无自有     竞品均分 3.9              │
│  ├ Mid ($200-600):  自有 4.7   竞品 4.4                  │
│  └ Premium (>$600): 自有 4.5   竞品 3.8                  │
│                                                         │
│  → 高端产品我们评分优势明显(+0.7)，中端接近持平          │
└─────────────────────────────────────────────────────────┘
```

### 6.4 问题生命周期（派生计算）

#### 状态定义

| 状态 | 含义 | 颜色 | 报告呈现 |
|------|------|------|----------|
| `active` | 近期有负面评论命中 | 红 | 需要行动 |
| `receding` | 负面频率下降或出现正面对冲 | 黄 | 持续观察 |
| `dormant` | 长期无新信号，状态未知 | 灰 | 信息不足 |
| `recurrent` | 曾经 dormant 但又出现负面 | 深红 | 高优先级 |

注意：没有 "resolved" 状态。仅靠评论数据无法确认问题已解决。

#### 转移规则（确定性，每次报告生成时从 reviews 历史派生）

```
R1: 新负面评论命中（RCW > 0.5）→ active
    （低可信度评论不单独触发）
R2: active + 正面对冲评论出现 + 近 30 天 neg/pos 比 ≤ 1:1 → receding
R3: active/receding + 连续 silence_window 天无新负面 → dormant
R4: dormant + 新负面评论 → recurrent（非 active，标记为复发）
R5: recurrent 后续行为与 active 相同（可进入 receding/dormant）
```

安全硬规则：
```
R6: safety_level = critical 的问题，silence_window 翻倍
    （安全问题需要更长的观察期才能判定为 dormant）
```

#### 动态沉默窗口

```python
def silence_window(label_code, ownership):
    """根据该标签的历史评论频率计算沉默等待天数"""
    avg_interval = avg_days_between_reviews(label_code, ownership)
    return clamp(avg_interval * 2, min_val=14, max_val=60)
```

#### 派生计算函数

```python
def derive_issue_lifecycle(label_code, ownership, all_reviews, window_end):
    """从完整评论历史派生当前状态，不依赖持久化"""
    relevant = [r for r in all_reviews 
                if label_code in extract_labels(r) and r["ownership"] == ownership]
    relevant.sort(key=lambda r: r["scraped_at"])
    
    if not relevant:
        return {"status": "dormant", "confidence": "no_data"}
    
    # 回放状态机
    state = "active"
    last_negative_at = None
    was_dormant = False
    
    for review in relevant:
        if is_negative(review, label_code):
            if state == "dormant":
                state = "recurrent"
                was_dormant = True
            else:
                state = "active"
            last_negative_at = parse_date(review["scraped_at"])
        elif is_positive_counter(review, label_code):
            if state == "active":
                # 检查 neg/pos 比
                recent_neg = count_recent(relevant, label_code, "negative", days=30)
                recent_pos = count_recent(relevant, label_code, "positive", days=30)
                if recent_pos >= recent_neg:
                    state = "receding"
    
    # 检查沉默窗口
    if last_negative_at:
        days_silent = (window_end - last_negative_at).days
        sw = silence_window(label_code, ownership)
        if days_silent >= sw and state in ("active", "receding"):
            state = "dormant"
    
    return {
        "status": state,
        "first_seen": relevant[0]["scraped_at"],
        "last_seen": relevant[-1]["scraped_at"],
        "total_reviews": len(relevant),
        "was_recurrent": was_dormant,
        "days_active": (window_end - parse_date(relevant[0]["scraped_at"])).days,
    }
```

#### 月报呈现：问题卡片

```
┌──────────────────────────────────────────────────────────┐
│  🔴 质量稳定性 (quality_stability) — active              │
│  ──────────────────────────────────────────────────────── │
│  影响范围：系统性（5 个 SKU）                              │
│  持续时间：47 天（首次: 2/28, 最近: 4/12）                │
│  安全级别：Level 2 (设备退化风险)                         │
│                                                          │
│  时间线：                                                │
│  2/28 ━━━━━ 3/15 ━━━━━ 4/1 ━━━━━ 4/12                   │
│   ▼ 差评x3   ▼ 差评x1    ▼ 好评x1   ▼ 差评x1            │
│   "漏水"     "还是漏"    "好了"     "又漏"               │
│                                                          │
│  竞品参照：Cabela's 同期有 2 条同类投诉                   │
│  → 分类：品类通病（自有 + 竞品均有）                      │
│                                                          │
│  趋势：本月 2 条 vs 上月 4 条，频率下降但未消失           │
└──────────────────────────────────────────────────────────┘
```

#### 月报问题概览矩阵

```
问题维度          自有     竞品     状态        分类
─────────────────────────────────────────────────────
质量稳定性        🔴       🔴       active      品类通病
结构设计          🟡       🔴       receding    竞品更严重
售后与履约        🔴       ⚪       active      我们独有
材料与做工        ⚪       ⚪       dormant     沉寂中
安装装配          🟡       ⚪       receding    持续改善
─────────────────────────────────────────────────────
🔴=active/recurrent 🟡=receding ⚪=dormant
```

### 6.5 SKU 健康计分卡

月报独有。每个 SKU 一行，展示红黄绿灯 + 关键指标 + 趋势方向：

```
SKU 健康计分卡
───────────────────────────────────────────────────────────────────
SKU             品类      价格     评分    差评率   风险分   趋势   灯
───────────────────────────────────────────────────────────────────
1159179 #22     grinder   $389     4.7     1.5%     12      ↗     🟢
1159178 #12     grinder   $549     4.7     2.8%     28      ↘     🟡
1193673 #42     grinder   $1199    4.4     5.2%     35      →     🔴
192234 Mixer50  mixer     $389     4.8     0.5%     3       →     🟢
...
───────────────────────────────────────────────────────────────────

灯判定：
  🟢 风险分 < 15 且差评率 < 3%
  🟡 风险分 15-35 或差评率 3-8%
  🔴 风险分 > 35 或差评率 > 8% 或有 safety Level 1/2 事件
```

### 6.6 LLM 高管摘要

月报独有。调用 LLM 生成 3 段式摘要：

```
Prompt 输入：
- 累积 KPI（本月 vs 上月 delta）
- TOP 3 活跃问题（含生命周期状态）
- 品类对标结果
- 安全事件（如有）

输出：
1. 态势判断（一句话）："本月质量态势稳中向好，核心问题从 3 个降至 2 个"
2. 关键发现（3 条 bullet）
3. 建议行动（2-3 条，按优先级）
```

### 6.7 月报 Excel（6-sheet 扩展版）

在周报 4-sheet 基础上增加：
- Sheet 5: 品类对标（每品类一组，含价格段细分）
- Sheet 6: SKU 计分卡（全量 SKU 的健康指标 + 灯号 + 趋势）

---

## 7. 分析模块拆分

将 `report_analytics.py`（~1600 行）拆分为独立模块：

### 7.1 共享模块（所有 tier 使用）

| 模块 | 来源 | 职责 |
|------|------|------|
| `analytics_kpi.py` | 从 report_analytics.py 提取 | 健康指数、差评率、风险评分、KPI delta |
| `analytics_clusters.py` | 从 report_analytics.py 提取 | 标签聚类、严重度计算、sub-features |
| `analytics_competitive.py` | 从 report_analytics.py 提取 | 竞品差距指数、基准示例、差距分类 |
| `analytics_heatmap.py` | 从 report_analytics.py 提取 | 产品×属性热力图矩阵 |

### 7.2 月报独有模块（新增）

| 模块 | 职责 |
|------|------|
| `analytics_lifecycle.py` | 问题生命周期派生（derive_issue_lifecycle）+ 概览矩阵 + 品类通病检测 |
| `analytics_category.py` | 品类对标（读取 CSV 映射 + 价格段计算 + 品类间对比） |
| `analytics_scorecard.py` | SKU 健康计分卡（红黄绿灯 + 趋势方向） |
| `analytics_executive.py` | LLM 高管摘要生成 |

### 7.3 Tier 配置驱动模块加载

```python
TIER_DIMENSIONS = {
    "daily": ["kpi", "clusters", "competitive_gap"],
    "weekly": ["kpi", "clusters", "competitive_gap", 
               "risk_ranking", "heatmap", "trend_charts"],
    "monthly": ["kpi", "clusters", "competitive_gap",
                "risk_ranking", "heatmap", "trend_charts",
                "category_benchmark", "issue_lifecycle",
                "product_scorecard", "executive_summary"],
}

DIMENSION_MODULES = {
    "kpi":                 "analytics_kpi",
    "clusters":            "analytics_clusters",
    "competitive_gap":     "analytics_competitive",
    "heatmap":             "analytics_heatmap",
    "category_benchmark":  "analytics_category",
    "issue_lifecycle":     "analytics_lifecycle",
    "product_scorecard":   "analytics_scorecard",
    "executive_summary":   "analytics_executive",
    # risk_ranking 和 trend_charts 内嵌于 kpi 模块
}
```

---

## 8. 数据库变更汇总

### 新增表

```sql
-- 安全审计日志
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
-- workflow_runs: 新增 tier 列
ALTER TABLE workflow_runs ADD COLUMN report_tier TEXT DEFAULT 'daily';

-- review_analysis: 新增标签异常标记
ALTER TABLE review_analysis ADD COLUMN label_anomaly_flags TEXT;
```

### 不新增的表

- ~~issue_lifecycle~~ — 派生计算，不持久化
- ~~product_category_map~~ — CSV 配置文件

---

## 9. 新增 / 修改文件清单

### Phase 1

| 操作 | 文件 | 说明 |
|------|------|------|
| 修改 | `qbu_crawler/server/report.py` | query_cumulative_data() 增加 impact_category/failure_mode |
| 修改 | `qbu_crawler/server/report_common.py` | SAFETY_TIERS 替换 _SAFETY_KEYWORDS，compute_cluster_severity() |
| 修改 | `qbu_crawler/server/report_snapshot.py` | 产物版本戳 _meta，report_tier 支持 |
| 修改 | `qbu_crawler/server/report_html.py` | V3 HTML 双视角收口 |
| 修改 | `qbu_crawler/server/report_templates/daily_report_v3.html.j2` | Tab 2 填充 + 全景 tab 改读累积 |
| 修改 | `qbu_crawler/server/report_templates/email_change.html.j2` | None 人话化 |
| 修改 | `qbu_crawler/server/report_templates/email_quiet.html.j2` | 累积 KPI 永远显示 |
| 修改 | `qbu_crawler/models.py` | safety_incidents 表 + 字段变更 |
| 修改 | `qbu_crawler/server/translator.py` | 标签一致性检查 + 安全检测回调 |

### Phase 2

| 操作 | 文件 | 说明 |
|------|------|------|
| 新增 | `qbu_crawler/server/alert_worker.py` | 即时告警 Worker |
| 修改 | `qbu_crawler/server/report.py` | generate_report(tier, logical_date) 统一入口 |
| 修改 | `qbu_crawler/server/workflows.py` | report_tier 支持 + 日报智能发送 |
| 修改 | `qbu_crawler/server/app.py` | AlertWorker 注册启动 |
| 修改 | `qbu_crawler/config.py` | 收件人分组 + 新 env vars |

### Phase 3

| 操作 | 文件 | 说明 |
|------|------|------|
| 新增 | `qbu_crawler/server/analytics_kpi.py` | 从 report_analytics.py 提取 |
| 新增 | `qbu_crawler/server/analytics_clusters.py` | 从 report_analytics.py 提取 |
| 新增 | `qbu_crawler/server/analytics_competitive.py` | 从 report_analytics.py 提取 |
| 新增 | `qbu_crawler/server/analytics_heatmap.py` | 从 report_analytics.py 提取 |
| 新增 | `qbu_crawler/server/report_templates/weekly_report.html.j2` | 周报模板 |
| 新增 | `qbu_crawler/server/report_templates/email_weekly.html.j2` | 周报邮件模板 |
| 修改 | `qbu_crawler/server/workflows.py` | WeeklySchedulerWorker |
| 修改 | `qbu_crawler/server/report_snapshot.py` | 退役 quiet weekly_digest |
| 新增 | `data/category_map.csv` | 品类映射配置 |

### Phase 4

| 操作 | 文件 | 说明 |
|------|------|------|
| 新增 | `qbu_crawler/server/analytics_lifecycle.py` | 问题生命周期派生 |
| 新增 | `qbu_crawler/server/analytics_category.py` | 品类对标 |
| 新增 | `qbu_crawler/server/analytics_scorecard.py` | SKU 计分卡 |
| 新增 | `qbu_crawler/server/analytics_executive.py` | LLM 高管摘要 |
| 新增 | `qbu_crawler/server/report_templates/monthly_report.html.j2` | 月报模板 |
| 新增 | `qbu_crawler/server/report_templates/email_monthly.html.j2` | 月报邮件模板 |
| 修改 | `qbu_crawler/server/workflows.py` | MonthlySchedulerWorker |

---

## 10. 环境变量新增

```env
# 周报/月报调度时间
WEEKLY_SCHEDULER_TIME=09:30
MONTHLY_SCHEDULER_TIME=09:30

# 收件人分组
EMAIL_RECIPIENTS_EXEC=           # 高管（周报/月报摘要）
EMAIL_RECIPIENTS_SAFETY=         # 安全告警

# 即时告警
ALERT_PRICE_CHANGE_THRESHOLD=15  # 价格变动告警阈值（百分比）

# 品类映射
CATEGORY_MAP_PATH=data/category_map.csv
```

---

## 11. 验收标准

### Phase 1

- [ ] 所有报告中健康指数和差评率永远有值（不出现 N/A）
- [ ] V3 HTML 的"今日变化" Tab 展示窗口数据，"全景数据" Tab 展示累积数据
- [ ] 评分变为 None 时显示"—"或"已下架"
- [ ] 安全相关评论在报告中有红色标记
- [ ] safety_incidents 表有证据冻结记录
- [ ] 标签一致性异常被标记

### Phase 2

- [ ] 无变化的日子不发邮件，HTML 仍存档
- [ ] Safety Level 1 评论触发即时钉钉 + 安全邮件
- [ ] 新差评（≤2星）触发即时钉钉告警
- [ ] 不同收件人收到不同级别的报告

### Phase 3

- [ ] 每周一自动生成周报 HTML + Excel + 邮件
- [ ] 周报包含完整聚类分析、风险排行、竞品对标
- [ ] issue 卡片标注"系统性"/"个体"扩散度

### Phase 4

- [ ] 每月 1 日自动生成月报
- [ ] 月报第 1 屏包含高管摘要（态势 + 3 bullet + 行动建议）
- [ ] 品类对标按 Grinder/Slicer/Mixer 等分组，含价格段
- [ ] 问题生命周期展示 active/receding/dormant/recurrent 四状态
- [ ] SKU 计分卡展示红黄绿灯 + 趋势方向
