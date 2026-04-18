# QBU 报告设计系统 V4 重构设计稿

**日期**：2026-04-18
**作者**：leo.xia（与 Claude 协作）
**状态**：Design — Ready for Implementation Plan
**前序工件**：`docs/plans/P006-*`、`docs/plans/P007-*`（architecture 修复）；`scripts/simulate_reports/`（模拟器产物对照基准）

---

## 1. 背景

当前 QBU 网评监控报告分三个层级：日报（daily）、周报（weekly）、月报（monthly）。经对模拟器 42 天时间轴产物（S01–S11、W0–W5、M1）的 PM 视角审计，发现系统存在三个根本矛盾：

- **矛盾 A**：一个产品在"简报化"与"深度情报"之间摇摆。周报产物 1.9 MB（最厚）、月报 148 KB（最薄但也最潦草）、日报 46–60 KB（中庸但风格混乱），产物强度与业务价值倒挂。
- **矛盾 B**：`full/change/quiet/partial` 四种模式虽然在代码里存在分支，但视觉上没有任何区分。S07（Change）与 S08a（Quiet）两份 HTML 体积完全相同（46760 字节），收件人无法辨识。
- **矛盾 C**：V3 设计系统（`daily_report_v3.css`，1268 行，Editorial 风格）只有周报真正在用；日报引用 V3 CSS 却大量 inline 样式覆盖；月报使用与 V3 JS 不兼容的类名（`.tab-button.active` vs `.tab-btn.tab-active`），Tab 切换彻底失效。

### 1.1 用户诉求

1. 统一设计语言：专业、高级、美观、用户体验友好
2. 从 PM 视角审视数据口径与计算问题，以一目了然的方式呈现
3. 冷启动首日（`is_partial=True`）也给出完整 Full HTML 画像，打上"基线建立中"标签
4. Quiet 模式保留现行的"头 N 天每日 + 之后每周"邮件节奏（`REPORT_QUIET_EMAIL_DAYS`），HTML 每天归档不变

---

## 2. 数据口径审计（12 项问题）

### 2.1 阻断级（影响首屏可信度）

| ID | 问题 | 代码定位 | 修复方式 |
|---|------|---------|---------|
| **D1** | `normalize_deep_report_analytics()` 产生的派生字段（`health_index` / `own_negative_review_rate_display` / `high_risk_count` / `coverage_rate` / `kpi_cards` / `competitive_gap_index`）未持久化到 `analytics.json` | `report_snapshot.py:1941-1944` 写盘前未调 normalize | 写盘前统一调用 normalize 再 `json.dumps`；定义 `AnalyticsEnvelope` schema 作为持久化契约 |
| **D2** | 月报 `kpi_delta` 级联失败：`prev_kpis['health_index']` 因 D1 永远为 None | `report_snapshot.py:1240` | D1 修复后自动解决；增加 guard：`_safe_delta` 在任一方为 None 时返回 None 并在 UI 明确标注"基线缺失" |
| **D3** | `safety_incidents` 未去重：M1 月报显示 105 起，实则 5 次真实事件被重复记录 | 模拟器注入路径 + 生产 LLM 标注链路 | 以 `(review_id, safety_level, failure_mode)` 联合唯一键 upsert；UI 展示按 `review_id` 分组 |
| **D4** | `is_partial` 链路断裂：`_meta["is_partial"]` 生成但未持久化到 `workflow_runs`，briefing 模板未读取 | `report_snapshot.py:72-73`；`_generate_daily_briefing` 全链路 | 增加 `workflow_runs.is_partial` 字段；模板顶部 mode_strip 读取此字段决定分支 |

### 2.2 口径级（PM 会当场质疑）

| ID | 问题 | 建议修复 |
|---|------|---------|
| **D5** | `ingested(2823) ≠ own(1622) + competitor(1021)`，差 180 条 ownership 未分类 | 补 ownership 分类任务；报告 KPI 明细里补一行"未分类 N 条" |
| **D6** | `coverage_rate` 口径不清：公式 `ingested / site_total`，未区分 window / cumulative，未考虑 `MAX_REVIEWS=200` 截断 | 重定义为"最近 30 天站点新增 vs 抓取新增"；tooltip 写公式与数据源 |
| **D7** | `health_confidence` 从不显示 | 每个计算指标右上角加 `🟢 可信 / 🟡 参考 / 🔴 样本不足` 徽章 |
| **D8** | 好评率 / 差评率不成套（3 星中评隐形） | UI 改为好/中/差三段迷你条形图；tooltip 注明"3 星不计入好评" |
| **D9** | `quiet_days` 定义模糊（连续无评论 vs 最后评论距今） | 统一为"连续无新评论天数"；HTML 加上下文说明 |

### 2.3 呈现级（影响一目了然）

| ID | 问题 | 建议修复 |
|---|------|---------|
| **D10** | 日报 window / cumulative 同屏混用，无视觉分隔 | 改为"累积视角 ↔ 今日增量"双列对比卡 |
| **D11** | 月报 `safety_incidents` 只有 SKU + failure_mode，无法追溯评论 | 展开可链接到原评论 + 时间线 |
| **D12** | `competitive_gap_index` 样本 <20 时显示 "—" 但不解释 | 加"样本累积中 X/20"状态条 |

---

## 3. V4 设计系统

### 3.1 设计语言 — "Editorial Intelligence"

**核心原则**：

- **双字体组合**：Playfair Display（头条 Serif）+ DM Sans（正文 Sans）+ DM Mono（数字等宽）+ Noto Serif SC（中文 Serif）
- **克制色系**：
  - 底色：`#f7f7f5`（米白纸）
  - 主色：`#4f46e5` 靛紫
  - 严重度四级：`#b91c1c` 红 / `#c2410c` 橙 / `#a16207` 黄 / `#047857` 绿
  - 禁用：任何紫色渐变、鲜艳蓝渐变、纯黑底
- **编辑态 Hero**：大字号 Serif 标题 + 小字 Kicker + 副标题人话 + 数据徽章；**不用**渐变横幅
- **数据密度金字塔**：首屏 3 核心 KPI（Hero 区）→ 9 卡 KPI Grid → Tab 内深度明细
- **置信度永远可见**：每个计算指标右上角 confidence 徽章
- **Emoji 降级**：💰📦⭐ 只能用作次级标签；主区块使用 CSS icon 或 Serif 章节编号

### 3.2 设计令牌（扩展 `daily_report_v3.css`）

新增 token 组：

```css
/* Mode colors — 6 种 tier/mode 组合 */
--mode-partial:  #8e8ea0;  /* 灰 */
--mode-full:     #4f46e5;  /* 靛（与 accent 同） */
--mode-change:   #c2410c;  /* 琥珀 */
--mode-quiet:    #047857;  /* 淡绿 */
--mode-weekly:   #4338ca;  /* 深靛 */
--mode-monthly:  #1e1b4b;  /* 靛夜 */

/* Confidence badges */
--conf-high:     #047857;  /* 🟢 */
--conf-medium:   #a16207;  /* 🟡 */
--conf-low:      #b91c1c;  /* 🔴 */
--conf-none:     #8e8ea0;  /* 灰 */
```

---

## 4. 共享组件库（Jinja Partials）

```
qbu_crawler/server/report_templates/
├── _partials/
│   ├── head.html.j2          # <head> + fonts + css_text 注入
│   ├── kpi_bar.html.j2       # Sticky 顶栏（tier 无关）
│   ├── mode_strip.html.j2    # 模式识别条（6 色）
│   ├── hero.html.j2          # Serif 标题 + Gauge + kicker + bullets
│   ├── kpi_grid.html.j2      # 9 卡 KPI（含 confidence 徽章 + Δ）
│   ├── tab_nav.html.j2       # 统一 .tab-btn.tab-active
│   ├── issue_card.html.j2    # 问题卡（含 lifecycle badge）
│   ├── review_quote.html.j2  # 评论引用块（中英对照 + 作者 + 评分）
│   ├── empty_state.html.j2   # 空态插画 + 人话解释
│   └── footer.html.j2        # 定义 / 版本 / 生成时间
├── daily.html.j2             # ~80 行装配器（替代 daily_briefing.html.j2）
├── weekly.html.j2            # ~80 行装配器（替代 daily_report_v3.html.j2 的 weekly 路径）
└── monthly.html.j2           # ~80 行装配器（替代 monthly_report.html.j2）
```

**迁移规则**：

- 所有 inline `style=""` 迁移到 `daily_report_v3.css` 新组件类
- 所有 tab DOM 统一 `data-tab + .tab-btn.tab-active`，`daily_report_v3.js` 保持不变
- 三份顶层模板仅做 include 装配 + tab 集合差异

---

## 5. Mode 即视觉语言

| Mode | Strip 色 | Kicker | Hero 副标 | 可见 Tabs |
|------|---------|--------|---------|---------|
| **Daily · Partial**（冷启动） | 灰 `--mode-partial` | BASELINE BUILDING · Day N/7 | "样本积累中，本日数据置信度：样本不足" | 全部 tab 可见，加"贝叶斯先验解释卡" |
| **Daily · Full** | 靛 `--mode-full` | DAILY INTELLIGENCE · Day N | LLM hero_headline | 总览 / 今日变化 / 问题诊断 / 全景 |
| **Daily · Change** | 琥珀 `--mode-change` | CHANGE ONLY · 无新评但有产品变动 | "今日 N 个产品发生价格/库存/评分变化" | 总览 + 今日变化 |
| **Daily · Quiet** | 淡绿 `--mode-quiet` | QUIET · 连续 N 天无新评论 | "已连续静默 N 天，累积指标稳定" | 总览（其余灰态占位） |
| **Weekly** | 深靛 `--mode-weekly` | WEEKLY REPORT · Week N | 周 hero_headline | V3 全套 + 周对比 tab |
| **Monthly** | 靛夜 `--mode-monthly` | MONTHLY EXECUTIVE BRIEF | LLM stance_text | 高管视图 / 本月变化 / 生命周期 / 品类 / 计分卡 / 竞品 / 全景 |

**冷启动首日决策**（B1 已确认）：

- 即使 `is_partial=True`，也直接走 Full V3 骨架
- mode_strip 显示"BASELINE BUILDING · Day N/7"
- 所有指标右上角强制显示 confidence 徽章（多数为 🟡/🔴）
- 首屏加一张"贝叶斯先验解释卡"：`样本 < 30 时，健康指数向先验值 50 收缩，以避免小样本虚高虚低`

**Quiet 模式邮件节奏**（B2 已确认）：

- 保留现行 `REPORT_QUIET_EMAIL_DAYS`（默认头 3 天每日 + 之后每周）
- HTML 每天归档不变

---

## 6. KPI 重新设计

### 6.1 首屏 3 核心 KPI（Hero 区）

- **健康指数**：大字号 + Gauge + confidence 徽章 + Δ vs 上期
- **差评率**：好/中/差三段迷你条形图 + Δ
- **高风险产品数**：数字 + Top 3 产品名小卡

### 6.2 KPI Grid 9 卡（3×3）

```
┌─────────────┬─────────────┬─────────────┐
│ 健康指数    │ 差评率      │ 好评率      │
│ 94.8  🟢   │ 3.6% ↓0.4  │ 87.2%      │
├─────────────┼─────────────┼─────────────┤
│ 自有评论    │ 高风险产品  │ 竞品差距    │
│ 1622 +18   │ 3  ↑1      │ 42  🟡     │
├─────────────┼─────────────┼─────────────┤
│ 样本覆盖率  │ 翻译完成度  │ 安全事件    │
│ 67%  🟢    │ 97%  🟢    │ 5 起  ⚠    │
└─────────────┴─────────────┴─────────────┘
```

**每卡统一结构**：`label + value + delta + confidence + tooltip`。

**tooltip 内容规范**：
- 计算公式（人话 + 数学表达）
- 数据源窗口（window/cumulative/比较期）
- 置信度说明（样本量、贝叶斯修正阈值）

### 6.3 数据契约（`AnalyticsEnvelope`）

```python
# 持久化 schema（analytics.json 写盘格式）
{
  "_schema_version": "v4",
  "kpis_raw": { ... },                    # build_report_analytics 产出
  "kpis_normalized": {                    # normalize_deep_report_analytics 产出
    "health_index": 94.8,
    "health_confidence": "high",
    "own_negative_review_rate_display": "3.6%",
    "high_risk_count": 3,
    "coverage_rate": 0.67,
    "competitive_gap_index": 42,
    "kpi_cards": [ ... 9 项 ... ],
    ...
  },
  "self": { ... },
  "competitor": { ... },
  "report_copy": { ... },
  "mode": "partial|full|change|quiet|weekly|monthly",
  "mode_context": { "quiet_days": 3, "is_partial": false, ... },
  ...
}
```

**所有 render 函数只读 `kpis_normalized`**；legacy `analytics.get("kpis")` 读 `kpis_raw` 保留兼容。

---

## 7. 月报重构

### 7.1 首屏（30 秒可知命脉）

```
┌ [MONTHLY EXECUTIVE BRIEF · 2026年04月]       ← mode_strip 靛夜
│
│ Executive Stance: 需要关注                   ← stance kicker
│
│ 安全风险高发，需立即升级处置                 ← Serif hero headline
│
│ [Gauge 68]  健康指数 68  🟢 +4 vs 上月
│            差评率 5.9%   ↑0.3
│            高风险产品 3   ↑1
│
│ · 3 条 executive bullets（人话）
│
│ ── 建议行动 Top 3 ──（可点击跳转）
└
```

### 7.2 7 个 Tab

1. **高管视图**：executive 完整内容（stance / bullets / actions）
2. **本月变化**：新增评论 top 30 + 价格/库存/评分变动
3. **问题生命周期**：lifecycle_cards（R1-R6 状态机，cold-start 不足 30 天则显示"数据积累中"占位卡）
4. **品类对标**：category_benchmark（含 fallback 直接配对模式）
5. **产品计分卡**：SKU scorecard（🟢🟡🔴 + 趋势箭头）
6. **竞品对标**：benchmark_examples
7. **全景数据**：Chart.js 热力图 + 情感分布

### 7.3 关键修复

- 统一类名 `.tab-btn.tab-active`（删 `.tab-button.active`）
- 引用同一份 `daily_report_v3.js`（tab 切换 / Gauge 动画 / KPI reveal 全部复用）
- `safety_incidents` 按 `review_id` 去重 + 按 `failure_mode` 分组展示 + 可点击跳原评论
- KPI Δ 修复（D1+D2 级联修复后自动生效）
- 删除自定义 `<style>` 段，改用 V3 token

---

## 8. 邮件体系收敛

现有 6 个邮件模板（`email_daily/full/change/quiet/weekly/monthly`）→ 统一为：

```
_email_base.html.j2       # header 色带 + Brand + Mode Strip + Footer + 外联按钮
├── email_daily.html.j2   # extends base，按 mode 切换 strip
├── email_weekly.html.j2  # extends base
└── email_monthly.html.j2 # extends base，高管首屏摘要卡
```

**视觉连续性**：所有邮件共享同一 header 色带（靛紫 → 白）、同一 Brand 位、同一 Footer；`mode_strip` 作为第一屏顶部带，与网页版对齐。

---

## 9. 实现路线图（4 个 PR）

### PR 1：数据契约修复（最小阻断级改动）

- `AnalyticsEnvelope` schema 定义
- `generate_full_report_from_snapshot` 写盘前强制 normalize
- `workflow_runs.is_partial` 字段 + `_meta["is_partial"]` 落库
- `safety_incidents` 联合唯一键 upsert
- 模拟器产物重跑，`verify` 应全部 PASS

**验收**：M1 月报 KPI 不再为空；S01 manifest `is_partial=True`。

### PR 2：设计系统基础设施

- 扩展 `daily_report_v3.css`：mode tokens + confidence tokens + section dividers
- 抽出 10 个 Jinja partials（`_partials/` 目录）
- 保持现有 `daily_briefing / daily_report_v3 / monthly_report` 可运行，用 feature flag 切换

**验收**：新旧两套模板可通过环境变量切换；CSS/JS 共享；模拟器两轮产物 diff <20%。

### PR 3：三张报告重构

- `daily.html.j2` / `weekly.html.j2` / `monthly.html.j2` 装配式重写
- mode_strip 对接 6 种 mode
- KPI Grid 9 卡组件落地 + confidence 徽章
- 月报首屏 Hero + 7 tab 重写

**验收**：S01/S02/S07/S08a 四份 daily HTML 视觉可辨；M1 月报首屏 30 秒可读。

### PR 4：邮件收敛 + 数据一目了然

- `_email_base.html.j2` + 3 变体落地
- KPI tooltip 补全公式 / 数据源 / 置信度说明
- `safety_incidents` 按 review 分组 + 深链
- 三段饼图替代差评率/好评率并列卡
- `quiet_days`、`coverage_rate`、`competitive_gap_index` 文案与样本状态条落地

**验收**：PM 首次打开任一报告，3 个核心 KPI 的公式/窗口/置信度不需要问工程师就能解释。

---

## 10. 验收对照表

每个 scenario 一行期望（全部通过模拟器 `verify` 命令自动校验）：

| SID | tier | mode | 期望视觉特征 | 期望 KPI 状态 |
|-----|------|------|------------|------------|
| S01 | daily | partial | 灰 strip + "BASELINE BUILDING · Day 1/7" | 所有 KPI 含 🟡/🔴 confidence 徽章 |
| S02 | daily | full | 靛 strip + "DAILY INTELLIGENCE · Day 2" | health_index > 90 🟢，Δ 首次可见 |
| S07 | daily | change | 琥珀 strip + "CHANGE ONLY" | 0 新评论但价格/库存变动区块高亮 |
| S08a | daily | quiet | 淡绿 strip + "QUIET · 连续 1 天" | 累积 KPI 稳定，其余灰态占位 |
| W0 | weekly | weekly | 深靛 strip + "WEEKLY · 2026W13" | 周对比 tab + 完整 V3 hero |
| M1 | monthly | monthly | 靛夜 strip + "MONTHLY EXECUTIVE BRIEF" | 首屏 30 秒可读、safety_incidents 按 review 分组 |

---

## 11. 非目标（明确不做）

- 不做 SPA 化（邮件是核心分发渠道，HTML 单文件不变）
- 不重构 analytics 算法本身（health_index / gap_index 公式保持 V3）
- 不新增 KPI 指标（只修现有口径与呈现）
- 不改动 Excel 产物结构（仅跟随 KPI 口径修复）
