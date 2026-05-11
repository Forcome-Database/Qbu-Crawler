# F011 报告系统重构 · 需求设计文档

- **创建日期**：2026-04-27
- **作者**：Claude Code（基于 7 轮迭代审计文档收口）
- **关联审计**：`docs/reviews/2026-04-26-production-test5-full-report-audit.md`
- **状态**：v1.2（合入路径 B —— 三大块用户视角局部优化）
- **目标 Release**：`qbu-crawler 0.4.0`

### 修订记录

- **v1.3 (2026-05-11)**：**§4.2.4.1 时间口径条款已被 [F012](F012-window-semantics-and-weekly-cadence.md) 取代**。`own_new_negative_reviews` 等所有"窗口/最近 N 天/新增"业务判定不再按 `scraped_at`，改为 `first_seen_at`（per-product 基线，详见 F012 FR-1）。本文档其余条款仍有效。
- v1.0 (2026-04-27 初稿)：基于 7 轮迭代审计文档合成
- v1.1 (2026-04-27 同日)：合入计划-需求边界审查。修订要点：
  - I2 `KPI 灯"需关注产品"`定义统一为 `near_high_risk + 红/黄灯` 逻辑（删除硬编码 25）
  - 新增 §3.3.1 `bootstrap 状态判定函数`明确实现规约
  - 新增 §4.2.4.1 `own_new_negative_reviews` 时间口径声明（按 `scraped_at`）
  - §4.1.2 KPI 灯阈值改为明确开闭区间
  - 扩展 §5.3 数字断言完整覆盖
  - 新增 §5.5 CI 集成
  - 扩展 §6.4 legacy 模板 env 路由
  - 新增 §AC-26 ~ AC-33（性能 / v2v3 共存 / 状态机 / CI）
- v1.2 (2026-04-27 同日)：合入附件 HTML 三大块（全景数据 / 问题诊断 / 竞品启示）局部优化（路径 B 高 ROI 改造）：
  - §4.2.6 全景数据：特征情感热力图优化（维度 Top 8 聚合 / hover 显示 top 评论 / 点击下钻 + 评分分布合并到自有产品状态 / 竞品评分迁移到竞品启示）
  - §4.2.2 自有产品问题诊断：8 张 issue cards **默认折叠 Top 3 之外**（按 evidence_count + severity 排序）；删除 LLM 输出价值低的 `temporal_pattern` 段
  - §4.2.7 竞品启示：新增"竞品弱点 = 我方机会"卡（Top 3 差评主题 + 我方差异化方向）+ benchmark_examples 结构化分类（产品形态 / 营销话术 / 服务模式 三类）
  - 新增 AC-34 ~ AC-36 验收（热力图可下钻 / issue cards Top 3 默认展开 / 弱点机会卡存在）

---

## 1. 背景与目标

### 1.1 现状问题

当前 `qbu-crawler 0.3.25` 的报告体系在生产测试 5 中暴露出三大类核心问题：

1. **数据正确性问题**：差评率分母混用（同一列双口径）；Excel 失效模式列 100% 空（DB 有 561 条数据）；`METRIC_TOOLTIPS["风险分"]` 与实际 5 因子算法严重不同步；`failure_mode` 64.9% 是"无类"占位词污染，无法做任何聚合分析。

2. **用户体验问题**：报告中混入大量"工程视角内部信号"（数据质量、通知失败、采集覆盖率、估算日期占比、bootstrap 占位）；KPI 指标过多（7 张卡含抽象指数）；趋势区 12 panel 视觉过载且首日全空；建议行动标题被 LLM 长 action 截断成半句话；`duration_display "约 8 年"` 被读为"问题持续 8 年"。

3. **架构稳定性问题**：HTML 模板 `row.values()` 依赖 dict 顺序耦合；`_parse_date_published` 与 `_backfill_date_published_parsed` 解析 anchor 不一致；通知 outbox 全 deadletter 但 workflow 仍 `report_phase=full_sent`，状态机分裂；`top_actions[]` 是迁移留下的死字段。

### 1.2 目标

把报告系统从**"AI 撰写的可读分析稿"**升级为**"可信、可决策、可送达的运营仪表盘"**。

核心达成标准：

- **可信**：数据正确性（口径统一、tooltip 与算法一致、字段完整透传），数据质量异常不再静默
- **可决策**：每个用户角色（管理者 / 产品改良 / 设计 / 营销）能在自己关心的深度找到答案
- **可送达**：通知链路状态回写 workflow，业务能感知"送达失败"
- **架构清晰**：4 类产物（邮件正文 / 附件 HTML / Excel / 内部运维）边界清晰，互不污染

### 1.3 非目标

- **不做**：HTML 顶部分角色 tabs（管理者/产品/设计/数据 4 套布局）→ 维护成本与认知摩擦
- **不做**：分角色 Excel 导出（3 份 .xlsx）→ 同上
- **不做**：把 561 评论嵌入移到 Excel 链接 → 附件 HTML 应具备独立下钻能力
- **不做**：把 Excel drawing 嵌图改 hyperlink → 视觉证据原样保留

---

## 2. 用户与使用场景

### 2.1 用户角色

| 角色 | 主要使用场景 | 决策时间 | 主要消费产物 |
|------|------------|---------|------------|
| 管理者 | 每日定时邮件，30 秒判断"今天有事吗" | 30-60 秒 | 邮件正文 |
| 产品改良 | 周会投屏，按问题定位改良方向 | 5-15 分钟 | 附件 HTML |
| 设计 | 用户痛点查阅，按场景理解体验断点 | 5-15 分钟 | 附件 HTML |
| 营销 | 找竞品弱点 + 我方好评素材 | 5-10 分钟 | 附件 HTML / Excel |
| 分析师 | 数据下钻、按 SKU 排序、二次加工 | 15-60 分钟 | Excel |
| 运维 | 数据采集异常、通知失败处置 | 即时 | **内部运维通道**（独立邮件） |

### 2.2 用户核心问答

每个角色应能在对应产物中秒答以下问题：

| 用户问 | 优化后产物中的位置 |
|--------|------------------|
| "今天有事吗？" | 邮件正文：4 KPI 灯 |
| "什么事？" | 邮件正文：Hero 一句话 + Top 3 行动 |
| "我该做什么？" | 附件 HTML：完整 5 行动 + 证据回链 |
| "竞品在干嘛？" | 附件 HTML：竞品启示双名单 |
| "口碑在变好吗？" | 附件 HTML（数据成熟期）：健康度趋势主图 |
| "我之前的改良奏效了吗？" | 附件 HTML：Top 3 问题趋势 ✅ 标记 |
| "数据靠谱吗？" | **不展示给用户**——内部运维通道保证 |

---

## 3. 架构原则

### 3.1 频道分离

**4 类用户产物 + 1 类内部运维**：

| # | 产物 | 模板文件 | 受众 | 触发 | 内容定位 |
|---|------|---------|------|------|---------|
| 1 | 邮件正文 HTML（full） | `email_full.html.j2` | 所有用户 | 每日 full 报告 | 30 秒决策入口 |
| 2 | 邮件正文 HTML（change） | `email_change.html.j2` | 所有用户 | 仅有变化日 | 同上，更短 |
| 3 | 邮件正文 HTML（quiet） | `email_quiet.html.j2` | 所有用户 | 无变化日 | 单卡说明 |
| 4 | **附件 HTML 报告** | `daily_report_v3.html.j2` | 产品改良 / 设计 / 营销 | 每次 full | 5-15 分钟深度阅读 |
| 5 | **Excel 附件** | `_generate_analytical_excel()` | 分析师 | 每次 full | 数据下钻、二次加工 |
| 6 | **内部运维邮件** | `email_data_quality.html.j2` | 仅运维 | 阈值触发 | 完全与用户产物解耦 |

**关键约束**：用户产物（1-5）**不展示**任何工程信号（采集质量、通知状态、estimated_dates、backfill_dominant、本次入库内部数字、tooltip-代码漂移、schema 债务）；这些**全部**由 6 号通道处理。

### 3.2 信息深度自然分层（替代分角色 tabs）

**不分角色，按"决策深度"分层**——每个用户从上往下读，自然在自己关心的深度停下；多人协作看同一份。

```
┌─ 邮件正文（30 秒）──────── 管理者天然停止层
│  4 KPI 灯 · Hero · Top 3 行动 · 产品状态
├─ 附件 HTML（5-15 分钟）──── 产品改良 / 设计 / 营销天然停止层
│  完整 5 行动 · 8 issue cards · 竞品启示 · 全景数据嵌入 561 评论
├─ Excel 附件（15-60 分钟）── 分析师天然停止层
│  4 sheets：核心数据 / 现在该做什么 / 评论原文（drawing 嵌图）/ 竞品启示
└─ 内部运维邮件 ──────────── 工程 / 运维（独立通道，用户无感）
```

### 3.3 bootstrap 期 vs 数据成熟期 双行为

报告状态机的两种模式：

| 模式 | 触发条件 | 与"今日变化"区块行为 | 与"变化趋势"区块行为 |
|------|---------|------------------|------------------|
| **bootstrap** | `report_semantics='bootstrap'`，无可比 baseline run | 完全隐藏，单卡替代："首日基线已建档，对比信号将从下一日起出现" | 完全隐藏，单卡替代："趋势数据正在累积，需 ≥30 样本且每周 ≥7 个有效样本" |
| **数据成熟期** | 已有 ≥1 个可比 baseline run；趋势满足 ≥30 样本 + ≥7 时间点 | 3 层金字塔（🔥 立即关注 / 📈 趋势变化 / 💡 反向利用） | 1 主图 + 3 折叠下钻 |

#### 3.3.1 状态判定函数规约（v1.1 新增）

```python
def determine_report_semantics(conn, current_run_id) -> str:
    """报告状态机：返回 'bootstrap' / 'incremental'。

    判定规则：
    - 若当前 run 之前**没有**任何 status='completed' 的同 workflow_type 的 run → 'bootstrap'
    - 若当前 run 之前有 ≥1 个 status='completed' 的 run → 'incremental'

    边界场景：
    - DB wipe 重建后再次定时触发：之前所有 run 不存在 → 重新进入 'bootstrap'（合理）
    - 手动 + 定时同 logical_date 重复：以最先成功的 run 为准（trigger_key 唯一性已保证）
    - run 之前的 status='failed' run：不算可比 baseline → 仍 'bootstrap'

    本函数被 build_report_analytics 在每次生成报告前调用一次。
    """
```

每个区块（"今日变化" / "变化趋势"）按以下逻辑选择行为：

```python
semantics = determine_report_semantics(conn, run_id)
if semantics == 'bootstrap':
    render_bootstrap_placeholder()
else:
    # 进一步检查趋势区独有阈值
    if trend_digest.primary_chart.confidence in ("low", "no_data"):
        render_trend_accumulating_placeholder()
    else:
        render_full_layout()
```

### 3.4 用户价值优先级原则

**每个元素须经"老板 3 秒能看懂吗 + 决策有用吗"双重测试**：

- 都是 ✅ → 保留并优化
- 一个 ✅ → 改造（语义化、可视化）
- 都是 ❌ → 删除或移内部运维

---

## 4. 功能需求

### 4.1 邮件正文 HTML（`email_full.html.j2`）

#### 4.1.1 布局结构

```
┌─ max-width 640px ─────────────────────────┐
│ 标题区: QBU 评论分析 · YYYY-MM-DD          │
│        副标题: 本期 自有 N 款 / 竞品 N 款 / │
│              共 N 条评论                    │
├──────────────────────────────────────────┤
│ KPI 灯条（4 张语义灯）                       │
│ 🟢 总体口碑 优秀 (96.2)                     │
│ 🟢 好评率 94.7%                             │
│ 🟡 差评率 2.4% (≤2 星 / 自有评论)            │
│ 🟡 需关注产品 1 个 (.75 HP)                 │
├──────────────────────────────────────────┤
│ 关键判断（Hero 一句话 + 3 条 bullets）        │
├──────────────────────────────────────────┤
│ Top 3 行动建议（短标题 + 影响产品数）          │
│   1. [结构设计] 肉饼厚度不可调 · 影响 3 款    │
│   2. [售后履约] 开关失灵 · 影响 1 款          │
│   3. [质量稳定] 金属碎屑 · 影响 2 款          │
├──────────────────────────────────────────┤
│ 自有产品状态（5 行 灯 + 一句原因）             │
│   🟡 .75 HP Grinder       开关失灵 + 售后失联 │
│   🟡 Walton's Quick Patty 肉饼厚度不可调      │
│   🟢 Walton's #22         健康                │
│   🟢 Walton's General Lug 健康                │
│   ⚪ .5 HP Dual Grind     无数据             │
├──────────────────────────────────────────┤
│ ▶ 详情 / 评论原文见附件 HTML                  │
│ ▶ 数据下钻见 Excel 附件                       │
└──────────────────────────────────────────┘
```

#### 4.1.2 元素清单

| 元素 | 数据源 | 展示约束 | bootstrap 期行为 |
|------|--------|---------|----------------|
| 标题副标题 | `analytics.kpis.{own_product_count, competitor_product_count, ingested_review_rows}` | 单行文字 | 同 |
| KPI 灯 ① 总体口碑 | `analytics.kpis.health_index` | 阈值 `≥85 绿` / `70 ≤ x < 85 黄` / `<70 红`（v1.1 明确开闭区间）；显示分数辅助 | 同 |
| KPI 灯 ② 好评率 | `analytics.kpis.own_positive_review_rows / own_review_rows` | 直接展示百分数 | 同 |
| KPI 灯 ③ 差评率 | `analytics.kpis.own_negative_review_rate` | 显示 "X.X% (≤2 星 / 自有评论)" | 同 |
| KPI 灯 ④ 需关注产品 | `count(p in risk_products WHERE p.status_lamp in ('red','yellow'))` — **v1.1 修订**：取黄灯+红灯数（即 `risk_score ≥ HIGH_RISK_THRESHOLD` 或 `near_high_risk=True` 或 `has_negative_issues=True` 的产品总数）；删除原硬编码 25 阈值，统一与 §4.2.3 灯逻辑 | 显示数字 + 第一个产品名 | 同 |
| Hero | `analytics.report_copy.hero_headline` | 经措辞护栏（health_index ≥ 90 不得用"严重"） | 同（首日替换为"基线建档完成"） |
| 3 条 bullets | `analytics.report_copy.executive_bullets[0:3]` | 数字断言后置校验 | 改为 1 条说明 |
| Top 3 行动 | `analytics.report_copy.improvement_priorities[].short_title` + `affected_products_count` | 必须取 short_title 而非 action（依赖 Phase 1 schema 改造） | 隐藏 |
| 自有产品状态 | `analytics.self.product_status[]`（新增字段） | 灯 + 一句原因 | 同 |
| 附件链接 | 文件路径 | mailto / 文件附件 | 同 |

#### 4.1.3 删除的当前元素

| 当前元素 | 删除原因 |
|---------|---------|
| `accent` 巨幅 health_index 数字 hero block | 重复，已在 KPI 灯条 |
| `覆盖产品 N/M` | 内部信号 |
| 4 张范围卡（累计自有/竞品/本次/近30天） | 用户读不出意义 |
| `本次入库 561` 大数字 | 严重误读源 |
| `高风险产品 0` 阈值数字 | 改为"需关注 N 个"语义化 |

#### 4.1.4 客户端兼容约束

- **必须**：max-width 640px / 表格布局 / 内联 CSS（不依赖 `<style>` 块）
- **禁止**：JavaScript / 外部 CSS / 视觉特效 / Web 字体
- **降级**：`@media` 在不支持的客户端会被忽略，需保证不依赖

### 4.2 附件 HTML 报告（`daily_report_v3.html.j2`）

#### 4.2.1 布局结构

```
┌──────────────────────────────────────────────┐
│ 顶部 KPI 4 张语义灯（同邮件正文）               │
├──────────────────────────────────────────────┤
│ 关键判断（Hero + 3 bullets，与邮件一致）        │
├──────────────────────────────────────────────┤
│ 现在该做什么 — 完整 5 项                       │
│   每项: short_title + 完整 full_action +      │
│         证据评论回链 [#252, #254...] +         │
│         影响 SKU 列表                          │
├──────────────────────────────────────────────┤
│ 自有产品状态（5 行 + 详细风险因子分解 hover）    │
│   .75HP: 因子 neg=0.65×0.35 + sev=0.71×0.25 + │
│            evi=0.30×0.15 + rec=0.20×0.15 +    │
│            vol=0.40×0.10 = 32.6/100           │
├──────────────────────────────────────────────┤
│ 自有产品问题诊断 — Top 3 展开 + 5-8 折叠 (v1.2)│
│   含 actionable_summary / failure_modes /     │
│   root_causes / 高频期 YYYY-MM ~ YYYY-MM /    │
│   example_reviews 文本 + 图评 gallery         │
├──────────────────────────────────────────────┤
│ 竞品启示 (v1.2 扩展)                           │
│   ⚡ 竞品弱点 = 我方机会 卡（Top 3 差评+对应方向）│
│   ✨ 我们能借鉴竞品什么（产品/营销/服务三类）    │
│   📡 多维度对标雷达图（Top 6-8 维度，聚合后）    │
│   📊 竞品评分两极分化（从全景迁移）              │
├──────────────────────────────────────────────┤
│ 今日变化（仅数据成熟期，详见 §4.2.4）            │
├──────────────────────────────────────────────┤
│ 变化趋势（仅数据成熟期，详见 §4.2.5）            │
├──────────────────────────────────────────────┤
│ 全景数据（嵌入 561 评论 + 客户端筛选）           │
│   筛选: 归属 / 评分 / 有图 / 新近 / 标签        │
└──────────────────────────────────────────────┘
```

#### 4.2.2 现在该做什么（重构 `建议行动`）

数据源：`analytics.report_copy.improvement_priorities[]`（schema 改造后）

**字段契约**（Phase 1 改造后）：

```json
{
  "label_code": "structure_design",
  "short_title": "结构设计：肉饼厚度不可调",  // ≤ 20 字
  "full_action": "针对 Walton's #22 Meat Grinder 等 3 款产品反馈的肉饼厚度过大、单次出饼量少、规格不符合预期及厚度不可调节等问题(13条)，建议复核关键成型腔体尺寸与公差，引入多档位厚度调节机构或提供差异化冲压模具...",
  "evidence_count": 13,
  "evidence_review_ids": [252, 254, 260, 263, 268, ...],
  "affected_products": ["Walton's #22 Meat Grinder", "Walton's General Duty Meat Lug", "Walton's Quick Patty Maker"],
  "affected_products_count": 3
}
```

**展示规则**：
- 卡片标题 = `short_title`
- 详情区展开 = `full_action`
- 证据 chip = `evidence_review_ids[].截短(@5)` deeplink 到全景数据 sheet 行
- 影响 SKU 一行展示

#### 4.2.3 自有产品状态（重构 `自有产品排行`）

数据源：`analytics.self.product_status[]`（新增字段）

**字段契约**：

```json
{
  "product_name": ".75 HP Grinder (#12)",
  "product_sku": "1159178",
  "status_lamp": "yellow",  // green / yellow / red / gray (无数据)
  "status_label": "需关注",
  "primary_concern": "开关失灵 + 售后失联",
  "risk_score": 32.6,                  // 仅 hover 显示
  "risk_factors": {                    // 仅 hover 显示
    "neg_rate":  {"value": 0.65, "weight": 0.35, "contribution": 0.228},
    "severity":  {"value": 0.71, "weight": 0.25, "contribution": 0.178},
    "evidence":  {"value": 0.30, "weight": 0.15, "contribution": 0.045},
    "recency":   {"value": 0.20, "weight": 0.15, "contribution": 0.030},
    "volume":    {"value": 0.40, "weight": 0.10, "contribution": 0.040}
  },
  "near_high_risk": false              // 是否接近高风险阈值
}
```

**灯阈值规则**：

| 灯 | 触发条件 |
|----|---------|
| 🔴 红 | `risk_score ≥ HIGH_RISK_THRESHOLD`（默认 35） |
| 🟡 黄 | `0.85 × HIGH_RISK_THRESHOLD ≤ risk_score < HIGH_RISK_THRESHOLD`（接近高风险）OR 有任何负面 issue |
| 🟢 绿 | 健康（无负面 issue 且 risk_score < 阈值） |
| ⚪ 灰 | 采集异常（ingested_reviews = 0 或 coverage < 阈值） |

#### 4.2.3.1 自有产品问题诊断（8 张 issue cards）（v1.2 优化）

**当前问题**：默认 8 张全展开，老板/产品不会全看；与"现在该做什么"区有功能重叠。

**v1.2 优化定位区分**：

| 区块 | 定位 | 内容粒度 |
|------|------|---------|
| 现在该做什么 | **行动建议**（决策层）| Top 5 短标题 + 改良方向 + 影响 SKU |
| 自有产品问题诊断 | **问题深度分析**（理解层）| 8 张 cards 含 failure_modes 频次表 / root_causes 置信度 / 证据评论 + 图 |

**默认展开规则**：

```
按 issue_cards 排序键排序：
  primary  : evidence_count DESC
  secondary: severity rank DESC  (high=3, medium=2, low=1)
  tertiary : affected_product_count DESC

默认展开: Top 3
默认折叠: 4-8（用 <details> 包裹，标题显示卡片摘要）
```

**v1.2 卡内调整**：

| 字段 | v1.1 状态 | v1.2 处理 |
|------|----------|---------|
| `actionable_summary` | 保留 | ✅ 保留（高价值） |
| `failure_modes`（频次表）| 保留 | ✅ 保留（高价值） |
| `root_causes`（置信度）| 保留 | ✅ 保留（高价值） |
| `temporal_pattern` | 保留 | ❌ **删除**（多为模板化文本，价值低） |
| `example_reviews` | 保留 | ✅ 保留（≤3 条） |
| 图评 gallery | 保留 | ✅ 保留 |
| `duration_display "约 8 年"` | 改高频期 | ✅ 已计划（v1.1）|

#### 4.2.4 今日变化（含 bootstrap / 数据成熟期 双模式）

**bootstrap 期**（隐藏整个区块，单卡替代）：

```html
<section class="bootstrap-notice">
  <h2>今日变化</h2>
  <div class="info-card">
    ℹ 首日基线已建档，对比信号将从下一日起出现
  </div>
</section>
```

**数据成熟期**（3 层金字塔）：

数据源：`analytics.change_digest`（schema 改造后）

**字段契约**：

```json
{
  "immediate_attention": {  // 🔥 立即关注（红色）
    "own_new_negative_reviews": [    // ← 新增
      {
        "product_name": ".75 HP Grinder",
        "review_count": 3,
        "primary_problems": ["开关失灵", "售后失联"]
      }
    ],
    "own_rating_drops": [            // ← 新增
      {
        "product_name": ".75 HP Grinder",
        "rating_from": 4.7,
        "rating_to": 4.5,
        "delta": -0.2
      }
    ],
    "own_stock_alerts": [            // ← 新增
      {
        "product_name": "Walton's #22",
        "stock_status": "out_of_stock"
      }
    ]
  },
  "trend_changes": {  // 📈 趋势变化（黄色）
    "new_issues": [...],          // 新增问题
    "escalated_issues": [...],    // 升级问题
    "improving_issues": [...]     // 改善问题
  },
  "competitive_opportunities": {  // 💡 反向利用（蓝色）
    "competitor_new_negative_reviews": [...],  // ← 新增（营销机会）
    "competitor_new_positive_reviews": [...]   // 反向学习（保留但降级）
  }
}
```

**展示规则**：
- 三块**仅在内部非空时显示**（避免空 0 占版面）
- 立即关注 - 红色边框；趋势变化 - 黄色；反向利用 - 蓝色
- 每条带"影响产品 / 主要问题"短描述

#### 4.2.4.1 时间口径明确（v1.1 新增 / 解决 B4）

> **⚠️ 本节已被 [F012](F012-window-semantics-and-weekly-cadence.md) 取代（v1.3 / 2026-05-11）**
>
> 5/11 周报换皮事件证明：以 `scraped_at` 作为"评论新出现"的口径，会被 bootstrap 当天一次性入库与未来扩监控范围两种场景灌水。F012 引入 `reviews.first_seen_at`（per-product 基线，UPSERT 不更新；NULL = 基线），所有"窗口/最近 N 天/新增"业务判定改用 `first_seen_at`。下方 v1.1 写的 `is_new_negative_review` 算法已废弃，新算法请参见 F012 §FR-1.3 切换清单。
>
> 仅技术运维管道（translator 等待、scrape_quality 分母、trend 图 fallback、picker 次级排序）继续使用 `scraped_at`，详见 F012 §3.3 字段语义分工矩阵。

---

`own_new_negative_reviews` / `competitor_new_negative_reviews` 等"新"信号的判定**必须按 `scraped_at` 而非 `date_published`**：

```python
def is_new_negative_review(review, run_data_since: str) -> bool:
    """系统视角的"新"——本次 run 首次采集到的差评。"""
    return (
        review["scraped_at"] >= run_data_since      # 本次 run 窗口内首次入库
        and (review.get("rating") or 0) <= 2         # ≤2 星
    )
```

**理由**：
- 老板关心"今天系统看到了什么新差评"——这是 `scraped_at` 视角
- 用户写于多年前但今天首次采到的负面评论，**仍是我方今天该处理的事**
- 避免歧义："new" 在用户视角 = 用户最近写的，但在运营视角 = 系统最近采到的
- 报告以**运营视角**为准，因此用 `scraped_at`

`date_published` 仅用于：
- §4.2.5 变化趋势的"发表时间"口径切换（用户活跃度视角）
- "近 30 天发表" 这类用户写作时间的统计

#### 4.2.5 变化趋势（含 bootstrap / 数据成熟期 双模式）

**bootstrap 期**（隐藏 12 panel，单卡替代）：

```html
<section class="bootstrap-notice">
  <h2>变化趋势</h2>
  <div class="info-card">
    ℹ 趋势数据正在累积，需 ≥30 样本且每周 ≥7 个有效样本
  </div>
</section>
```

**数据成熟期**（1 主图 + 3 折叠下钻）：

数据源：`analytics.trend_digest`（schema 改造后）

**主图：口碑健康度趋势**

```
┌─ 主视图 ────────────────────────────────────┐
│  口碑健康度趋势                               │
│  ─ 自有产品健康度 (绿线)                      │
│  ─ 竞品平均健康度 (红线)                      │
│                                              │
│  当前 96.2 ↓ 1.2pt vs 上 30 天平均           │
│  竞品 78.3 ↓ 0.5pt vs 上 30 天平均           │
│                                              │
│  时间切换: [7 天] [30 天 ★] [12 月]          │
│  口径切换: [发表时间] [采集时间 ★]            │
└────────────────────────────────────────────┘
```

**3 折叠下钻**：

1. **Top 3 问题随时间变化**：每个标签的样本数随时间曲线 + ↑/↓ 标记
2. **产品评分变化**：5 个自有产品评分随时间，含变化标记
3. **竞品对标雷达**：截面 vs 上月对比（双层雷达）

**字段契约**（trend_digest）：

```json
{
  "primary_chart": {
    "kind": "health_trend",
    "default_window": "30d",
    "default_anchor": "scraped_at",
    "windows_available": ["7d", "30d", "12m"],
    "anchors_available": ["scraped_at", "date_published"],
    "series_own": [{"date": "2026-04-01", "value": 95.4, "sample_size": 35}, ...],
    "series_competitor": [...],
    "comparison": {
      "own_vs_prior_window": {
        "current": 96.2,
        "prior": 97.4,
        "delta": -1.2,
        "delta_pct": -1.23
      }
    },
    "confidence": "high",       // high / medium / low / no_data
    "min_sample_warning": null  // 不足时填入说明
  },
  "drill_downs": [
    {"id": "top_issues", "title": "Top 3 问题随时间", "data": {...}},
    {"id": "product_ratings", "title": "产品评分变化", "data": {...}},
    {"id": "competitor_radar", "title": "竞品对标雷达", "data": {...}}
  ]
}
```

**Ready 阈值规则**（统一）：
- `sample_size ≥ 30` AND `time_points ≥ 7` → `confidence = high`
- `sample_size ≥ 15` AND `time_points ≥ 5` → `confidence = medium`，附 warning
- 否则 → `confidence = low / no_data`，**不画线，单卡说明**

#### 4.2.6 全景数据（v1.2 重构子板块定位）

**v1.2 新结构**：

```
H2 全景数据
├─ 评论明细 561 行（保留嵌入 + 客户端筛选）
└─ 特征情感热力图（v1.2 优化）
```

**移除**：
- ❌ 自有产品评分分布 → **合并到"自有产品状态"卡**（每行加迷你评分分布条形图）
- ❌ 竞品评分分布 → **迁移到"竞品启示"区作为"竞品评分两极分化"卡**

##### 4.2.6.1 评论明细嵌入 + 客户端筛选

**保留**：嵌入 561 评论行（不改链接到 Excel）

**新增**：客户端筛选（vanilla JS，无外部依赖）

```html
<section class="panorama">
  <div class="panorama-filters">
    <select name="ownership"><option>全部</option><option>自有</option><option>竞品</option></select>
    <select name="rating"><option>全部</option><option>≤2 星</option><option>3 星</option><option>≥4 星</option></select>
    <input type="checkbox" name="has_images"> 仅含图
    <input type="checkbox" name="recent"> 近 30 天
    <select name="label"><option>全部</option><option>structure_design</option>...</select>
  </div>
  <table class="panorama-table">
    <!-- 561 行评论数据 -->
  </table>
</section>
```

**改造**：当前模板趋势区使用的 `row.values()` 改为按 `columns` key 输出（健壮性 fix）。

##### 4.2.6.2 特征情感热力图（v1.2 优化）

**当前问题**：14 标签 × 8 产品 = 112 格子，密度过高，老板看不懂；无 hover 解释；点击格子无下钻。

**v1.2 优化**：

| 改造点 | 详情 |
|-------|------|
| **维度聚合** | 标签轴从 14 个聚合到 Top 8（按 mention 数 + has_data 评分），其余维度合并为 "其他"；产品轴保持 8 个不变 |
| **格子可读性** | 每格颜色阈值固化：绿 (>0.7) / 黄 (0.4-0.7) / 红 (<0.4) / 灰（无样本）；旁附颜色 legend |
| **Hover 解释** | 鼠标悬停每格显示：`产品 × 标签` 概要 + Top 1 评论原文（≤80 字） |
| **点击下钻** | 点击任一格跳转到全景数据"评论明细"区域，并自动应用筛选（`产品=X` + `标签=Y`），高亮对应行 |
| **样本不足处理** | 单格样本 <3 条时显示灰色 + "样本不足" hover 提示 |

**数据契约**（`analytics._heatmap_data` 改造）：

```json
{
  "x_labels": ["性能", "做工", "易用", "清洁", "安装", "售后", "结构", "其他"],
  "y_labels": [".75 HP", "Quick Patty", ...],
  "z": [
    [{"score": 0.85, "sample_size": 12, "top_review_id": 506, "top_review_excerpt": "..."}, ...],
    ...
  ]
}
```

#### 4.2.7 竞品启示（v1.2 扩展）

**v1.2 新结构**——4 子板块，按用户价值优先级排列：

```
H2 竞品启示

┌── ⚡ 竞品弱点 = 我方机会 ────────────────────┐
│ Top 3 差评主题:                              │
│   • 齿轮强度不足 → 我方做工差异化              │
│   • 售后响应慢 → 我方 SLA 营销                │
│   • 性价比偏低 → 我方价值定位                 │
└─────────────────────────────────────────────┘

┌── ✨ 我们能借鉴竞品什么 ────────────────────┐
│ 产品形态:                                    │
│   • 反向停转设计 (引用评论 #506)             │
│ 营销话术:                                    │
│   • DIY 友好定位                            │
│ 服务模式:                                    │
│   • 图文操作指引                            │
└─────────────────────────────────────────────┘

┌── 📡 多维度对标雷达（核心 6-8 维）─────────┐
│   [雷达图 自有 vs 竞品]                     │
│   维度: 性能/做工/易用/清洁/安装/售后...    │
└─────────────────────────────────────────────┘

┌── 📊 竞品评分两极分化（v1.2 从全景迁移）────┐
│  Cabela's HD Stuffer    : ▍▍▍▍▍▍ 5★ 30%   │
│                          ▏▏▏▏ 1★ 28%      │
│  Cabela's Commercial   : ...               │
│  ↗ 启示：竞品在做工/质量上明显短板          │
└─────────────────────────────────────────────┘
```

##### 4.2.7.1 竞品弱点机会卡（v1.2 新增）

**数据契约**：`analytics.competitor.weakness_opportunities`（新增字段）

```json
{
  "weakness_opportunities": [
    {
      "competitor_complaint_theme": "齿轮强度不足",
      "competitor_evidence_count": 7,
      "competitor_products_affected": ["Cabela's HD Stuffer", "Cabela's Commercial"],
      "our_advantage_direction": "我方做工差异化",
      "our_evidence_label": "solid_build",
      "our_positive_count": 147
    },
    ...
  ]
}
```

**生成逻辑**：在 `report_analytics.py` 中：
1. 取竞品评论的 negative labels Top 3（按 evidence_count）
2. 对每个 negative label，找自有产品的对应 positive label
3. 若自有 positive_count > 阈值（如 ≥10），生成"机会"条目
4. LLM 生成 `our_advantage_direction` 短句（一句 ≤20 字）

##### 4.2.7.2 benchmark_examples 结构化分类（v1.2）

**当前**：LLM 输出大段文本块。

**v1.2**：要求 LLM 输出按 3 类结构化：

```json
{
  "benchmark_examples": {
    "product_design": [
      {"point": "反向停转设计", "evidence_review_ids": [506], "competitor_product": "Cabela's HD Stuffer"}
    ],
    "marketing_message": [
      {"point": "DIY 友好定位", "evidence_review_ids": [510], "competitor_product": "..."}
    ],
    "service_model": [
      {"point": "图文操作指引", "evidence_review_ids": [...], "competitor_product": "..."}
    ]
  }
}
```

##### 4.2.7.3 雷达图维度聚合（v1.2）

**当前**：14 个 label_code 全部展示，肉眼难辨。

**v1.2**：

| 改造点 | 详情 |
|-------|------|
| 维度数 | 14 → **Top 6-8**（按 has_data + 总 mention 数） |
| 聚合规则 | 选取自有 + 竞品两侧总 mention ≥ 5 的标签；不足 6 时降到 5；超过 8 时仅取 Top 8 |
| 其余标签 | 合并为"其他"轴 |
| 双层 | 保留自有（实线）vs 竞品（虚线）|

##### 4.2.7.4 删除 benchmark_takeaways（v1.2）

`benchmark_takeaways`（"用户持续认可做工扎实"等抽象短句）与可借鉴名单功能重叠且更抽象，**删除**。

### 4.3 Excel 附件

#### 4.3.1 4 个 sheets 终稿

| Sheet | 行数（预估） | 列数 | 内容 |
|-------|------------|------|------|
| **核心数据** | 9（1 表头 + 8 产品） | 14 | 8 产品概览 + 状态灯 + 主要问题一句话 |
| **现在该做什么** | 6-21（1 表头 + 5-20 行动） | 7 | improvement_priorities 完整列表 |
| **评论原文** | 562（1 表头 + 561 评论） | 18 | 561 评论 + drawing 嵌图 + 失效模式 enum + impact_category enum |
| **竞品启示** | ~10（1 表头 + 6-8 主题） | 5 | 竞品好评 Top 3 + 差评 Top 3 主题 |

#### 4.3.2 sheet 列设计

**核心数据**（14 列）：

| 列 | 数据 | 改造点 |
|----|------|-------|
| 产品名称 | products.name | — |
| SKU | products.sku | — |
| 站点 | products.site | — |
| 归属 | products.ownership 翻译为 自有/竞品 | — |
| 售价 | products.price | — |
| 库存 | products.stock_status 翻译 | — |
| 站点评分 | products.rating | — |
| 站点评论数 | products.review_count | — |
| 采集评论数 | reviews COUNT | — |
| 覆盖率 | 采集 / 站点 | **新增** |
| 差评数 | reviews ≤2 ★ COUNT | — |
| 差评率(站点分母) | 差评 / 站点评论 | **新增** |
| 差评率(采集分母) | 差评 / 采集评论 | **新增**（替代当前混用） |
| 状态灯 | risk_score 计算（H6 改 ingested_only 分母） | **新增** |
| 主要问题 | 该产品 Top 1 negative label 中文 | **新增** |

**现在该做什么**（7 列）：

| 列 | 数据 |
|----|------|
| 序号 | 1, 2, 3 ... |
| 短标题 | improvement_priorities[].short_title |
| 影响产品数 | affected_products_count |
| 影响产品列表 | affected_products[] join "、" |
| 用户原话（典型） | top_complaint |
| 改良方向 | full_action |
| 证据数 | evidence_count |

**评论原文**（18 列，整改后）：

| 列 | 数据 | 改造点 |
|----|------|-------|
| ID | reviews.id | — |
| 窗口归属 | window_label | — |
| 产品名称 / SKU / 归属 / 评分 / 情感 | — | — |
| 标签（中文） | review_issue_labels.label_code 翻译 | **改造**：消费规范化表，去 durability/neutral |
| 影响类别 | review_analysis.impact_category 翻译 | **修复**（H12）：填真 enum，不再与"标签"列雷同 |
| 失效模式 | review_analysis.failure_mode（H19 enum 化后） | **修复**（H12 + H19）：填 enum 9 类，positive 时填"无" |
| 标题(原文/中文) | reviews.headline / headline_cn | — |
| 内容(原文/中文) | reviews.body / body_cn | — |
| 特征短语 | review_analysis.features 翻译 | — |
| 洞察 | review_analysis.insight_cn | — |
| 评论时间 | date_published_parsed（含置信度标记） | — |
| 照片 | drawing 嵌入（保留） | **保留**（不改 hyperlink） |

**竞品启示**（5 列）：

| 列 | 数据 |
|----|------|
| 类型 | "可借鉴" / "短板" |
| 主题 | benchmark_examples 主题中文 |
| 证据数 | example_reviews len |
| 典型评论（中文） | example_reviews[0].body_cn |
| 涉及产品 | competitor_product_names |

#### 4.3.3 删除的当前 sheets

| sheet | 删除原因 |
|-------|---------|
| 今日变化 | bootstrap 期全空；数据质量信号移内部运维 |
| 问题标签 | 用户读不懂英文 label_code；规范化标签已在"评论原文"列 |
| 趋势数据 | bootstrap 期全空；603 行混杂结构；数据成熟期再决定恢复 |

### 4.4 内部运维通道（`email_data_quality.html.j2` 扩展）

**已存在**模板，47 行。本项目仅做触发条件补强 + 收件人配置。

#### 4.4.1 触发条件

| 条件 | 阈值 | 严重度 |
|------|------|-------|
| `zero_scrape_skus` 非空 | 任一 SKU `ingested_reviews=0` 但 `site_review_count > 0` | **P0** |
| `scrape_completeness_ratio < 0.6` | 全局覆盖率 < 60% | P1 |
| `estimated_date_ratio > 0.3` | 相对时间评论占比 > 30% | P2 |
| `outbox_deadletter_count > 0` | outbox 有 deadletter | P1 |
| `tooltip_code_drift_detected` | CI 检测 tooltip 与代码不同步 | P2 |

#### 4.4.2 邮件结构

```
[内部] QBU 报告生成监控 · YYYY-MM-DD
────────────────────────────────────
✅ 生成成功: HTML + Excel + Snapshot + Analytics
⚠ 数据质量警示:
   • SKU 1193465: 站点 91 / 采集 0 (需重抓)
   • 评论日期估算占比: 44.9% (252/561)
   • 样本覆盖率: 64% (MAX_REVIEWS=200 截断)
❌ 通知送达失败:
   • DingTalk 401 (检查 hooks.token)
   • outbox 3 条进 deadletter
🔧 内部修复待办:
   • [若 CI 检测到] tooltip 与算法漂移

服务版本: 0.4.0
```

#### 4.4.3 收件人配置

`.env` 新增：

```
OPS_ALERT_EMAIL_TO=ops@example.com,dev@example.com
OPS_ALERT_TRIGGER_THRESHOLD_LEVEL=P1  # 仅 P1+ 触发邮件，P2 累积日报
```

---

## 5. 数据契约

### 5.1 数据库 Schema 改动

#### 5.1.1 新增字段

```sql
-- reviews 表：解析方式与置信度
ALTER TABLE reviews ADD COLUMN date_published_estimated INTEGER DEFAULT 0;
ALTER TABLE reviews ADD COLUMN date_parse_method TEXT;          -- absolute / relative_now / relative_scraped_at
ALTER TABLE reviews ADD COLUMN date_parse_anchor TEXT;          -- 解析基准时间
ALTER TABLE reviews ADD COLUMN date_parse_confidence REAL;       -- 0.0-1.0
ALTER TABLE reviews ADD COLUMN source_review_id TEXT;            -- 站点原始评论 ID（增量更新依赖）

-- products 表：行级采集质量
ALTER TABLE products ADD COLUMN last_scrape_completeness REAL;
ALTER TABLE products ADD COLUMN last_scrape_warnings TEXT;       -- JSON array

-- workflow_runs 表：核心质量字段独立列化
ALTER TABLE workflow_runs ADD COLUMN scrape_completeness_ratio REAL;
ALTER TABLE workflow_runs ADD COLUMN zero_scrape_count INTEGER;
ALTER TABLE workflow_runs ADD COLUMN report_copy_json TEXT;      -- LLM 输出回写

-- product_snapshots 表：绑定 run_id（趋势可重放）
ALTER TABLE product_snapshots ADD COLUMN workflow_run_id INTEGER REFERENCES workflow_runs(id);

-- 新建报告产物 artifact 表
CREATE TABLE report_artifacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL REFERENCES workflow_runs(id),
  artifact_type TEXT CHECK(artifact_type IN ('html_attachment','xlsx','pdf','snapshot','analytics','email_body')),
  path TEXT NOT NULL,
  hash TEXT,
  template_version TEXT,
  generator_version TEXT,
  bytes INTEGER,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_artifacts_run ON report_artifacts(run_id);
```

#### 5.1.2 新增索引

```sql
CREATE INDEX idx_reviews_published_parsed ON reviews(date_published_parsed);
CREATE INDEX idx_labels_polarity_severity ON review_issue_labels(label_polarity, severity);
```

#### 5.1.3 数据迁移

**M1: failure_mode enum 化**

`review_analysis.failure_mode` 自由文本归类到 9 类 enum：

| enum 值 | 归并规则 |
|--------|---------|
| `none` | "无"、"无失效"、"无显著失效模式"、"无故障"、"无失效问题"、"无典型失效模式"、"无/运行正常"、含"无"字符的占位短语 |
| `gear_failure` | 含"齿轮"且语义负面 |
| `motor_anomaly` | 含"电机"、"马达"、"过载"、"停转"、"温升" |
| `casing_assembly` | 含"壳体"、"装配"、"喉道"、"密封"、"漏液"、"接口" |
| `material_finish` | 含"材料"、"涂层"、"碎屑"、"剥落"、"生锈"、"裂纹" |
| `control_electrical` | 含"开关"、"电气"、"按键"、"接触" |
| `noise` | 含"噪音"、"声"、"嗡" |
| `cleaning_difficulty` | 含"清洁"、"清洗"困难类 |
| `other` | 其他无法归类 |

迁移脚本通过 LLM 二次归类（`prompt_version=v3`）一次性回填；同时**保留** `failure_mode_raw` 字段存原始文本供 audit。

### 5.2 Analytics 字段改动

#### 5.2.1 `improvement_priorities` schema 改造

**当前**：

```json
{
  "label_code": "structure_design",
  "evidence_count": 13,
  "action": "针对 ... (80+ 字段段)"
}
```

**改造后**：

```json
{
  "label_code": "structure_design",
  "label_display": "结构设计",
  "short_title": "结构设计：肉饼厚度不可调",     // ≤ 20 字
  "full_action": "针对 Walton's #22... (完整段落)",
  "evidence_count": 13,
  "evidence_review_ids": [252, 254, 260, ...],   // 新增证据回链
  "affected_products": ["...", "..."],
  "affected_products_count": 3,
  "priority": "high",
  "priority_display": "高"
}
```

LLM Prompt 同步要求输出三字段；JSON schema 校验失败重试 N 次。

#### 5.2.2 `change_digest` schema 改造

**新增 `review_signals` 子项**：

```json
{
  "review_signals": {
    "own_new_negative_reviews": [...],         // 新增（最高优先级）
    "competitor_new_negative_reviews": [...],  // 新增
    "own_new_positive_reviews": [...],
    "fresh_competitor_positive_reviews": [...] // 保留但降级
  }
}
```

**新增 `immediate_attention` / `trend_changes` / `competitive_opportunities` 三层金字塔字段**：

```json
{
  "immediate_attention": {
    "own_new_negative_reviews": [...],
    "own_rating_drops": [...],
    "own_stock_alerts": [...]
  },
  "trend_changes": {
    "new_issues": [...],
    "escalated_issues": [...],
    "improving_issues": [...]
  },
  "competitive_opportunities": {
    "competitor_weakness": [...],
    "competitor_strength_to_learn": [...]
  }
}
```

#### 5.2.3 `kpis` 字段调整

**新增**：

```json
{
  "near_high_risk_count": 1,        // 0.85 × HIGH_RISK ≤ score < HIGH_RISK
  "rating_negative_2star_rate": 0.024,    // 显式命名（替代多义"差评率"）
  "sentiment_negative_rate": 0.127,       // LLM 判读
  "severity_high_rate": 0.043             // 高严重度标签占比
}
```

**保留**（用于内部 / 调试）：

```json
{
  "low_rating_review_rows": 87,           // ≤3 星（含中评）
  "negative_review_rows": 65,             // ≤2 星
  "all_sample_negative_rate": 0.116
}
```

#### 5.2.4 `trend_digest` schema 改造

见 §4.2.5；核心变化：
- 主图 `primary_chart` 替代 12 panel
- 双时间口径切换（`scraped_at` / `date_published`）
- `confidence` + `min_sample_warning` 字段

#### 5.2.5 `risk_score` 因子分解输出

```json
{
  "risk_score": 32.6,
  "risk_factors": {
    "neg_rate":  {"raw": 0.65, "weight": 0.35, "weighted": 0.228},
    "severity":  {"raw": 0.71, "weight": 0.25, "weighted": 0.178},
    "evidence":  {"raw": 0.30, "weight": 0.15, "weighted": 0.045},
    "recency":   {"raw": 0.20, "weight": 0.15, "weighted": 0.030},
    "volume":    {"raw": 0.40, "weight": 0.10, "weighted": 0.040}
  },
  "near_high_risk": false
}
```

#### 5.2.6 `top_actions` 字段处置

**决策**：从 schema 删除（迁移死字段，HTML 完全依赖 `improvement_priorities`）。

替代方案（运维降级）：在 `improvement_priorities` 为空时，用规则 fallback：

```python
def build_fallback_priorities(risk_products, issue_clusters):
    """LLM improvement_priorities 失败时的规则降级路径。"""
    priorities = []
    # 规则 1: 高风险产品的 Top labels
    for p in risk_products[:3]:
        for label in p.top_labels[:1]:
            priorities.append({
                "label_code": label.code,
                "short_title": f"{label.display}：{p.product_name}",
                "full_action": "请查看附件中的详细问题诊断卡",
                ...
            })
    return priorities[:5]
```

### 5.3 LLM Prompt 契约

#### 5.3.1 措辞护栏（写入 system prompt）

```
措辞规则（必须遵守）：
1. 若 health_index ≥ 90，hero_headline 禁止使用"严重"/"侵蚀"/"重灾区"
   等强负面词；改用"仍存在结构性短板"/"局部需要关注"等温和措辞
2. executive_bullets 中的所有数字必须能在 kpis / risk_products 中找到
   原始来源；不得自行计算或外推
3. 若 high_risk_count = 0，禁止使用"高风险产品"作为主语
4. improvement_priorities[].short_title 必须 ≤ 20 字（中文计字）；
   full_action 必须 ≥ 80 字
```

#### 5.3.2 重试 + 数字断言（v1.1 完整化）

```python
def generate_report_insights_with_validation(kpis, clusters, gap, risk_products, reviews, ...):
    for attempt in range(MAX_RETRIES):
        try:
            copy_json = llm_call(build_insights_prompt(...))
            copy = parse_and_validate_schema(copy_json)
            assert_consistency(copy, kpis, risk_products, reviews)  # v1.1 扩展
            validate_tone_guards(copy, kpis)
            return copy
        except (SchemaError, AssertionError, ToneGuardError) as e:
            log.warning(f"LLM attempt {attempt} failed: {e}")
            time.sleep(2 ** attempt)
    return template_fallback(kpis, clusters)  # 模板兜底
```

**`assert_consistency` 完整覆盖（v1.1）**：

```python
def assert_consistency(copy, kpis, risk_products, reviews):
    """全字段数字断言。"""
    # 1. hero_headline 中的 health_index
    _assert_hero_health_match(copy.get("hero_headline", ""), kpis)

    # 2. executive_bullets 中的所有数字
    for bullet in copy.get("executive_bullets", []):
        _assert_numbers_traceable(bullet, kpis, risk_products)
        # 数字必须能在 kpis 或 risk_products 中找到原始来源；偏差 ≤ 0.5（绝对）/ 1%（相对）

    # 3. improvement_priorities[].evidence_count
    for item in copy.get("improvement_priorities", []):
        if item.get("evidence_count", 0) < 1:
            raise AssertionError(f"evidence_count must be ≥1: {item}")
        _assert_evidence_count_traceable(item, clusters)

    # 4. improvement_priorities[].evidence_review_ids 必须存在于 reviews
    review_id_set = {r["id"] for r in reviews}
    for item in copy.get("improvement_priorities", []):
        invalid_ids = [rid for rid in item.get("evidence_review_ids", []) if rid not in review_id_set]
        if invalid_ids:
            raise AssertionError(f"evidence_review_ids 包含未知 review id: {invalid_ids}")

    # 5. improvement_priorities[].affected_products 必须 ⊆ 实际产品名
    actual_products = {p.product_name for p in risk_products}
    for item in copy.get("improvement_priorities", []):
        unknown = set(item.get("affected_products", [])) - actual_products
        if unknown:
            raise AssertionError(f"affected_products 包含未知: {unknown}")
```

**断言失败处理**：
- attempt < MAX_RETRIES：重试
- attempt = MAX_RETRIES：调 `template_fallback(kpis, clusters)` 走规则降级（H20 保留的 fallback）
- 重要：每次失败 + 输出原文 + 失败类型记入 metrics（运维可观测）

#### 5.3.3 Prompt version

`prompt_version=v3`（v2 → v3 升级）。`review_analysis.prompt_version` 同步标记。

### 5.4 `METRIC_TOOLTIPS` 文案与代码同步

新建 CI 检查（`tests/test_metric_tooltips_sync.py`）：

```python
def test_risk_score_tooltip_matches_implementation():
    """tooltip 公式必须明确提及 5 因子加权（35/25/15/15/10）"""
    tooltip = METRIC_TOOLTIPS["风险分"]
    assert "5 因子" in tooltip or "差评率 35" in tooltip
    assert "≤2 星" in tooltip  # 与 NEGATIVE_THRESHOLD 一致
```

### 5.5 CI 集成（v1.1 新增）

将关键的口径同步检查接入 CI，**任意 PR 不通过则阻断合并**：

#### 5.5.1 GitHub Actions（推荐）

新建 `.github/workflows/contract-checks.yml`：

```yaml
name: Contract Checks
on: [push, pull_request]
jobs:
  tooltip-code-sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.10'
      - run: pip install -e .[test]
      - name: Tooltip vs algorithm sync check
        run: pytest tests/server/test_metric_tooltips_sync.py -v
      - name: LLM prompt schema check
        run: pytest tests/server/test_llm_prompt_v3.py -v
      - name: failure_mode classifier boundary check
        run: pytest tests/server/test_failure_mode_enum.py -v
```

#### 5.5.2 Pre-commit hook（备选）

`.pre-commit-config.yaml`：

```yaml
repos:
  - repo: local
    hooks:
      - id: contract-checks
        name: Report contract checks
        entry: pytest tests/server/test_metric_tooltips_sync.py tests/server/test_llm_prompt_v3.py
        language: system
        pass_filenames: false
        stages: [pre-push]
```

#### 5.5.3 检查覆盖

| 检查项 | 测试文件 |
|--------|---------|
| tooltip 与 risk_score 算法同步 | `tests/server/test_metric_tooltips_sync.py` |
| LLM v3 prompt schema 完整性 | `tests/server/test_llm_prompt_v3.py` |
| failure_mode 9 类 enum 边界 | `tests/server/test_failure_mode_enum.py` |
| 验收 AC-22 schema 迁移有 down | `tests/server/test_migration_0010.py::test_down_reverts_changes` |

---

## 6. 非功能需求

### 6.1 性能

| 指标 | 当前 | 目标 |
|------|------|-----|
| 邮件正文 HTML 大小 | 未测 | ≤ 50KB（邮件客户端兼容） |
| 附件 HTML 文件大小 | 449KB | ≤ 1MB（含 561 评论嵌入 + 图片） |
| Excel 文件大小 | 4.4MB | ≤ 5MB（含 drawing 嵌图） |
| 报告生成耗时 | 未测 | ≤ 30 秒（不含爬虫） |
| 客户端筛选 561 评论响应 | N/A | ≤ 200ms |

### 6.2 兼容性

- 邮件正文：Outlook 365 / Gmail / 钉钉邮件
- 附件 HTML：Chrome / Edge / Safari 最近 2 版
- Excel：Office 2016+ / WPS / LibreOffice

### 6.3 可观测性

- LLM 调用：成功 / 重试 / 兜底次数 metrics
- 模板渲染：渲染时间 / 失败次数 metrics
- 内部运维邮件：触发次数 / 收件人确认 metrics

### 6.4 向后兼容

- 旧版 `prompt_version=v2` 数据：需保留可读，不强制重新分析
  - 实现：`build_report_analytics` 消费 `review_analysis` 时按 `prompt_version` 路由不同 schema parser；v2 字段缺失项用 None 填充
  - 测试：见 §AC-23 / 新增 e2e 测试场景"DB 含 v2+v3 混合数据"
- `daily_report_v3.html.j2`：保留为 `daily_report_v3_legacy.html.j2` 一个 release，便于回滚
- DB schema 迁移：所有 `ALTER TABLE` 提供回滚脚本

#### 6.4.1 Legacy 模板 env 路由（v1.1 新增）

实现 `qbu_crawler/server/report.py::_select_template()`：

```python
def _select_template(env_template_version: str = None) -> str:
    """根据 env 选择附件 HTML 模板。

    REPORT_TEMPLATE_VERSION 取值：
    - "v3"（默认）→ daily_report_v3.html.j2
    - "v3_legacy" → daily_report_v3_legacy.html.j2（回滚用）

    其他值 / 不存在文件 → fallback 到 v3 + WARNING 日志。
    """
    version = env_template_version or os.environ.get("REPORT_TEMPLATE_VERSION", "v3")
    template_map = {
        "v3": "daily_report_v3.html.j2",
        "v3_legacy": "daily_report_v3_legacy.html.j2",
    }
    if version not in template_map:
        log.warning(f"Unknown REPORT_TEMPLATE_VERSION={version}, fallback to v3")
        return template_map["v3"]
    template_path = REPORT_TEMPLATE_DIR / template_map[version]
    if not template_path.exists():
        log.warning(f"Template {template_path} missing, fallback to v3")
        return template_map["v3"]
    return template_map[version]
```

`.env.example` 加：

```
# REPORT_TEMPLATE_VERSION: v3 (default) / v3_legacy (rollback to old layout)
# REPORT_TEMPLATE_VERSION=v3
```

---

## 7. bootstrap 期 vs 数据成熟期 行为对照

| 区块 | bootstrap 期 | 数据成熟期 | 触发切换条件 |
|------|------------|----------|------------|
| 顶部 KPI | 显示（含 health_index 当前值） | 显示 + 对比基准 | 有 ≥1 baseline run |
| Hero | 改"基线建档完成" | LLM 生成 + 措辞护栏 | 同 |
| Top 3 行动 | 显示（仅截面分析） | 显示 + 对比维度 | 同 |
| 自有产品状态 | 显示（仅截面） | 显示 + 趋势箭头 | 同 |
| 8 issue cards | 显示（仅截面 + 高频期） | 显示 | 同 |
| 竞品启示 | 显示（仅截面） | 显示 + 趋势 | 同 |
| **今日变化** | **隐藏，单卡替代** | 3 层金字塔 | 有 ≥1 baseline run AND 有真变化 |
| **变化趋势** | **隐藏，单卡替代** | 1 主图 + 3 折叠 | sample ≥ 30 AND time_points ≥ 7 |
| 全景数据 | 显示 561 评论 | 显示 + 客户端筛选 | 同 |

---

## 8. 验收标准（Definition of Done）

### 8.1 数据正确性

- [ ] **AC-1**：差评率分母统一——产品概览 sheet 同列不再出现两种分母（实测 R1 R2 R3 R4 用同口径）
- [ ] **AC-2**：Excel 评论原文 sheet 中"影响类别"列填 `impact_category` enum 而非 labels 重复（562/562 正确）
- [ ] **AC-3**：Excel 评论原文 sheet 中"失效模式"列非空率 ≥ 95%（H19 enum 化后） — _口径：基于 `review_analysis` 已分析的评论；如有 review 未 LLM 分析（review_analysis 缺失），分母不含这部分_
- [ ] **AC-4**：`failure_mode` 9 类 enum 分布合理（"none" ≤ 50%，其他 8 类有数据）
- [ ] **AC-5**：`METRIC_TOOLTIPS["风险分"]` 文案明确 5 因子（CI 测试通过）
- [ ] **AC-6**：scrape_quality 自检在 SKU 0 抓取时触发独立内部邮件
- [ ] **AC-7**：outbox deadletter 时 `workflow_runs.report_phase` 降级为 `full_sent_local`

### 8.2 UI / 模板

- [ ] **AC-8**：邮件正文 mock 与 §4.1.1 设计一致（截图比对）
- [ ] **AC-9**：附件 HTML 的"今日变化" + "变化趋势" 在 bootstrap 期显示单卡，不展示空区块
- [ ] **AC-10**：附件 HTML 的"建议行动"标题不再被截断（取 `short_title` ≤ 20 字）
- [ ] **AC-11**：附件 HTML 全景数据嵌入 561 评论 + 5 个筛选器可用
- [ ] **AC-12**：附件 HTML 自有产品状态显示灯 + 一句原因，hover 显示因子分解
- [ ] **AC-13**：Excel 4 sheets，删除原 3 sheets（今日变化 / 问题标签 / 趋势数据）
- [ ] **AC-14**：Excel 评论原文 sheet 的 drawing 嵌图保留（不改 hyperlink）

### 8.3 用户问答检验

- [ ] **AC-15**：管理者从邮件正文 30 秒内能回答"今天有事吗？什么事？"
- [ ] **AC-16**：产品改良从附件 HTML 5 分钟内能回答"哪些问题在恶化？我之前的改良奏效了吗？"
- [ ] **AC-17**：营销从附件 HTML 5 分钟内能回答"竞品出问题了吗？我们能蹭机会吗？"

### 8.4 工程质量

- [ ] **AC-18**：所有 H 项问题（H1, H2, H6, H10, H11, H12, H14, H15, H16, H17, H18, H19, H20, H21）的对应单元测试通过
- [ ] **AC-19**：报告生成耗时 ≤ 30 秒（snapshot 已 freeze 后）
- [ ] **AC-20**：邮件正文 ≤ 50KB；附件 HTML ≤ 1MB；Excel ≤ 5MB
- [ ] **AC-21**：CI 检查 `tooltip-代码同步` 测试通过
- [ ] **AC-22**：所有数据库 schema 迁移有回滚脚本

### 8.5 兼容性

- [ ] **AC-23**：旧版 `prompt_version=v2` 数据可读、不报错；v2/v3 共存时分析层路由正确（e2e 测试用 fixture 注入 v2 行）
- [ ] **AC-24**：邮件正文在 Outlook 365 / Gmail / 钉钉邮件中渲染正确
- [ ] **AC-25**：附件 HTML 在 Chrome / Edge 最近 2 版中渲染正确

### 8.6 v1.1 新增验收标准

- [ ] **AC-26**：`determine_report_semantics(conn, run_id)` 状态判定函数测试覆盖三种场景：首日 / 已有 baseline / DB wipe 重建（详见 §3.3.1）
- [ ] **AC-27**：性能测试通过——附件 HTML ≤ 1MB / Excel ≤ 5MB / 报告生成时间 ≤ 30 秒（不含爬虫）
- [ ] **AC-28**：客户端筛选 561 评论响应时间 ≤ 200ms（Chrome 最新版）
- [ ] **AC-29**：CI workflow `contract-checks.yml` 在每个 PR 自动运行；任一检查失败阻断合并
- [ ] **AC-30**：env `REPORT_TEMPLATE_VERSION=v3_legacy` 切换后能渲染旧模板（回滚验证）
- [ ] **AC-31**：内部运维邮件触发逻辑——`OPS_ALERT_EMAIL_TO` 为空时静默跳过（不抛错）；`zero_scrape_skus` 非空时必触发
- [ ] **AC-32**：`failure_mode` 分类器边界覆盖——"无齿轮问题"、"无电机过载"、"未发现齿轮问题" 等含负面 keyword 但有 negation 前缀的，正确归类为 `none`
- [ ] **AC-33**：同 logical_date 重复触发幂等——`trigger_key` UNIQUE 约束防重复创建 run

### 8.7 v1.2 新增验收标准（路径 B 三大块用户视角优化）

- [ ] **AC-34**：附件 HTML 特征情感热力图——X 轴标签数 ≤ 8（聚合后）；每格可 hover 显示 top 评论；点击格子能跳到全景数据并预筛选 `产品=X & 标签=Y`
- [ ] **AC-35**：附件 HTML 自有产品问题诊断——默认展开 Top 3 issue cards（按 evidence_count + severity 排序），4-8 张折叠在 `<details>` 中；卡内不再含 `temporal_pattern` 段
- [ ] **AC-36**：附件 HTML 竞品启示——含"竞品弱点 = 我方机会"卡（取自 `competitor.weakness_opportunities`，至少 1 条）；benchmark_examples 按产品/营销/服务三类分组；`benchmark_takeaways` 不再展示

---

## 9. 风险与回滚

### 9.1 主要风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| LLM Prompt v2 → v3 切换期 schema 变化导致旧数据不可用 | 高 | 保留 `prompt_version` 字段；分析层按版本号路由消费 |
| `failure_mode` enum 化迁移失败（LLM 二次归类） | 中 | 失败时保留 `failure_mode_raw` 原值；分批迁移可回滚 |
| HTML 模板大改造后旧报告不可重放 | 中 | 保留 `daily_report_v3_legacy.html.j2` 一个 release |
| Excel 删除 3 sheets 影响下游脚本 | 中 | 调研下游消费者；提前 1 周通知 |
| 客户端筛选 561 评论性能问题 | 低 | 性能测试：DOM 排序≤200ms |
| 内部运维邮件触发条件过严/过松 | 低 | 阈值可配置（`.env`） |

### 9.2 回滚方案

**Tier 1（紧急回滚）**：
- DB schema 改动有 `down` 脚本；analytics.json schema 兼容旧消费者
- 模板回退：env 切换 `REPORT_TEMPLATE_VERSION=v3_legacy` 走旧模板
- LLM prompt 回退：`LLM_PROMPT_VERSION=v2` env

**Tier 2（数据回滚）**：
- `failure_mode` enum 化失败：从 `failure_mode_raw` 恢复
- Schema 迁移失败：执行 `down` 脚本
- 历史 workflow_runs 不影响（保留兼容字段）

**Tier 3（部分回滚）**：
- 某 PR 上线后发现问题，独立 revert 该 PR；其他 PR 不受影响（PR 间松耦合）

---

## 10. 与审查文档的对应关系

本 F011 文档基于 `docs/reviews/2026-04-26-production-test5-full-report-audit.md` 第 7 轮迭代版的最终决策合成。关键章节对应：

| F011 章节 | 来源 |
|----------|------|
| §3.1 频道分离 | 审查 §11.1, §11.9 |
| §3.2 信息深度分层 | 审查 §11.10 |
| §3.3 双行为模式 | 审查 §11.11 |
| §4.1 邮件正文 | 审查 §11.9.2 |
| §4.2 附件 HTML | 审查 §11.9.3, §11.11 |
| §4.3 Excel | 审查 §11.4, §11.9.4 |
| §4.4 内部运维 | 审查 §11.5, §11.9.5 |
| §5 数据契约 | 审查 §6.4 优化建议 + H10-H21 |
| §6 非功能 | 审查 §6.4 + 第二轮 N5/N6 |

**未纳入 F011 的审查内容**：
- 7 轮迭代过程的"撤回 / 修正"历史（PRD 是前向文档）
- 工程视角的"问题清单"（已转化为功能需求）
- AI 互验元洞察（属于审查方法论，非产品需求）

---

## 11. 后续文档

实施计划见 `docs/superpowers/plans/2026-04-27-report-system-redesign.md`，按 4 个 Phase 组织 PR 拆分友好的 TDD 任务。

---

**文档版本**：v1.0（2026-04-27 定稿）
