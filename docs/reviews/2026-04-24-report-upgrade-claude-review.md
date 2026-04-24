# Daily Report 升级审查报告（Claude 独立视角）

**审查时间**：2026-04-24
**审查范围**：本轮"今日变化 + 变化趋势语义治理"升级（Phase 1）
**审查人**：Claude（Opus 4.7 · 1M）
**对标设计**：`docs/superpowers/specs/2026-04-23-report-change-and-trend-governance-design.md`
**对标计划**：`docs/superpowers/plans/2026-04-23-report-change-and-trend-governance.md`
**对标 Devlog**：`docs/devlogs/D018-report-change-trend-governance.md`

---

## 1. 审查范围与资料

| 维度 | 资料 |
|------|------|
| 需求 / 设计 | `docs/superpowers/specs/2026-04-23-...-design.md`（703 行硬约束） |
| 实施计划 | `docs/superpowers/plans/2026-04-23-...-governance.md`（922 行，11 任务） |
| 开发日志 | `docs/devlogs/D018-report-change-trend-governance.md` |
| 核心代码 | `qbu_crawler/server/report*.py` + `report_templates/` |
| 生产产物 | `C:\Users\leo\Desktop\生产测试\报告\{测试1, 测试2}`，每轮含 `snapshot / analytics / full-report.html / .xlsx / 警告.png / 邮件正文.png` |

**关键事实**：两轮产物分别代表升级前（测试1，14:37/14:41）与升级后（测试2，17:09/17:12）。

---

## 2. 需求 / 计划 / 实现 / 产物对齐矩阵

| Spec 硬约束 | 代码证据 | 测试2 产物证据 | 判断 |
|---|---|---|---|
| §5.1 顶层固化 `report_semantics`、`is_bootstrap`、`change_digest`、`trend_digest` | `report_analytics.py:1953-1961`、`report_common.py:648-658` 顶层透传 | `analytics.report_semantics="bootstrap"`、`is_bootstrap=true`、两 digest 均非空（测试1缺失） | ✅ 合格 |
| §5.3 顶层 `kpis` 是唯一展示 KPI 源 | `email_full.html.j2:9,10` 只读 `analytics.kpis`；`daily_report_v3.html.j2` 无 `cumulative_kpis`/`window.*` 引用 | 邮件 hero 94.9、差评率 3.6%、自有评论 450 全部与 `kpis` 一致；`cumulative_kpis` 未被渲染 | ✅ 合格 |
| §4.1 顶层 tab 名称与顺序 `总览/今日变化/变化趋势/问题诊断/产品排行/竞品对标/全景数据` | `daily_report_v3.html.j2:52-60` 按序产出 7 个 `tab-btn` | HTML `<nav class="tab-nav">` 正是 7 个 tab，顺序完全一致 | ✅ 合格 |
| §6.2 `fresh_review_count` = 近 30 天业务新增 | `report_snapshot.py:412-432` 用 `logical_day - 30d` + `date_published_parsed` 过滤 | `change_digest.summary.fresh_review_count=4`、`historical_backfill_count=589` | ✅ 合格 |
| §7.6 `backfill_dominant` 阈值 0.7 | `report_snapshot.py:549-551` 硬编码 `backfill_ratio >= 0.7` | 99% → 触发，message "本次入库以历史补采为主，占比 99%" | ✅ 合格 |
| §7.6 warnings 三键 `translation_incomplete / estimated_dates / backfill_dominant` 稳定保留 | `report_snapshot.py:534-553` 三键硬编码，message 在未触发时为 `""` | 三键齐全，未触发项 `enabled=false` | ✅ 合格 |
| §7.7 `empty_state` 只用于 `incremental + 无显著变化`，不与 bootstrap 复用 | `report_snapshot.py:555-565` 条件严格区分 `view_state` 三态 | bootstrap 下 `empty_state.enabled=false, title=""`；`view_state="bootstrap"` | ✅ 合格 |
| §7.9 bootstrap 下 `今日变化` 显示监控起点，禁止"今日新增" | `daily_report_v3.html.j2:145-148`、`email_full.html.j2:96-101` 都走 bootstrap 分支 | HTML tab-changes 文案："监控起点 / 首次建档 ... 不按增量口径解释"；`今日新增`= 0 次 | ✅ 合格 |
| §8.2 `trend_digest` 固定 `周\|月\|年 × sentiment/issues/products/competition` | `report_analytics.py:1822-1832` `_build_trend_digest`；views/dimensions/default_* 全部硬编码 | `trend_digest.views=['week','month','year']`、`dimensions=['sentiment','issues','products','competition']`、`default_view='month'`、`default_dimension='sentiment'` | ✅ 合格 |
| §8.5 首日允许混合就绪态 | `_build_trend_dimension` 让 KPI/primary_chart 子组件独立判 ready/accumulating | `week/products.status=accumulating` 但 `kpis.status=ready`；`month/sentiment=ready`、`month/products=accumulating` | ✅ 合格 |
| §9.3 Excel 五个 sheet | `report.py` `_generate_analytical_excel` 构建 5 sheet | 测试2 Excel 为 `评论明细 / 产品概览 / 今日变化 / 问题标签 / 趋势数据`（测试1 仅 4 sheet） | ✅ 合格 |
| §9.3 `产品概览.采集评论数` 按真实 review 聚合 | `report.py:1213-1249` 用 `review_counts_by_sku` | 测试1 竞品 `采集评论数=0`（bug），测试2 竞品 = 56/57（实际值） | ✅ 修复生效 |
| §9.3 `评论明细.本次新增` bootstrap 下 `新近/补采` | `report.py:1077-1081` bootstrap 分支按 `fresh_cutoff` 判定 | 测试2 594 行分布 `补采:589 / 新近:4`，无 `None` | ✅ 合格 |
| §10.1 bootstrap 不得出现"今日新增" | prompt `report_llm.py:502-508` 显式禁止；`_has_bootstrap_language_violation` L280-298 | HTML 全局 `今日新增` 命中 0 次；LLM 输出 `report_copy.hero_headline`、`executive_summary`、`competitive_insight` 无违禁词 | ✅ 合格 |
| §10.3 LLM prompt 感知语义 + deterministic fallback | `report_llm.py:376-541`，bootstrap 分支显式注入；fallback L563-581 + L681-683 | bootstrap 路径通顺，`report_copy.*` 内容真实准确（1%/4%/7% 差评率与 `risk_products.negative_rate` 对得上） | ✅ 合格（但有隐患，见 §3-P2-a） |
| §11 artifact resolver 回退链 + 写入相对路径 | `report_snapshot.py:76-140` 多级搜索；`_artifact_db_value` 转相对路径 | （未跑路径迁移回归；但 resolver 函数存在且非空） | ⚠️ 未在产物中直接验证 |
| §6.1 业务时间 vs 状态时间分流 | `_build_sentiment_trend / _build_product_trend` 分别使用 `date_published_parsed` / `scraped_at`（Grep 命中） | 两种时间轴在 trend 数据中各司其职；`month/products` accumulating（因连续 run 快照不足） | ✅ 合格 |
| §11 `has_estimated_dates` → `estimated_dates` warning | `report_snapshot.py:543-548` + `report_common.py has_estimated_dates` | 测试2 enabled=true，message "评论发布时间存在较高比例的相对时间估算..." | ✅ 合格 |
| §12 防漂移：模板不直接解释 window/cumulative_kpis | `daily_report_v3.html.j2` / `email_full.html.j2` grep 不到 `cumulative_kpis` 和 `window.reviews_count` | 无残留 | ✅ 合格 |
| §7.6 数据质量告警与业务变动邮件解耦（CLAUDE.md Task 6） | `scrape_quality.py`（52 行）+ 独立模板 `email_data_quality.html.j2` | 测试2 `警告.png` 是独立告警邮件：主题 "[数据质量告警] 采集缺失率超阈值"，不混入主报告 | ✅ 合格 |

### 未实现 / 待观察
- ❎ Phase 2 `trend_digest` 扩展辅图 + 表格（计划 T9/T10）尚未执行，属分期范畴，不算漂移。
- ⚠️ artifact 路径迁移（生产目录搬迁）在线上实际场景下的回归未在两轮测试中验证，但 resolver 代码具备。

---

## 3. 主要发现（按严重度分级）

### P1 · LLM `incremental` 提示词仍把 `window.reviews_count` 叙述为"今日新增评论"

**证据**：`qbu_crawler/server/report_llm.py:531-539`

```python
if report_semantics != "bootstrap" and window.get("reviews_count", 0) > 0:
    prompt += f"\n\n--- 今日变化 ---"
    prompt += f"\n今日新增评论 {window['reviews_count']} 条"
    prompt += f"（自有 {window.get('own_reviews_count', 0)}，竞品 {window.get('competitor_reviews_count', 0)}）"
    ...
    prompt += "\n请在 executive_bullets 中提及今日新增变化（如有值得关注的新评论）。"
```

**违反**：spec §5.2 明确约定"`window.reviews_count` 不再解释成'今日新增评论'，只能解释成'本次入库评论数'"；spec §10.2 再次强调"`ingested_review_count` 不得被解释为业务新增"。此处在 incremental 分支里把 `window.reviews_count`（= 本次入库，可能 99% 是 backfill）直接喂成"今日新增评论"给 LLM，LLM 大概率会在非 bootstrap 日（首轮之后每天）产生名实不符的 headline。

**根因**：Task 4 落地时只针对 bootstrap 做了硬禁令和校验，但 incremental 路径的 prompt 没同步迁移到 `change_digest.summary.fresh_review_count`。

**影响**：当前 bootstrap 不触发，生产测试未暴露；Phase 1 投产第二天起，一旦进入 incremental 且 `window.reviews_count > 0`，此 prompt 立即注入，LLM headline 重新漂移回 Week-1 之前的状态。

**建议修复**：改写为

```python
summary = change_digest.get("summary") or {}
fresh = summary.get("fresh_review_count", 0)
backfill = summary.get("historical_backfill_count", 0)
if report_semantics != "bootstrap" and summary:
    prompt += (
        f"\n\n--- 今日变化 ---"
        f"\n本次入库评论 {summary.get('ingested_review_count', 0)} 条"
        f"（近30天业务新增 {fresh} 条，历史补采 {backfill} 条）"
    )
    if summary.get("fresh_own_negative_count", 0) > 0:
        prompt += f"\n其中自有新近差评 {summary['fresh_own_negative_count']} 条"
    if backfill / max(fresh + backfill, 1) >= 0.7:
        prompt += "\n本次入库以历史补采为主，禁止把补采计入业务新增叙述。"
```

并把禁忌短语 `今日新增` 从 prompt 内部彻底抹除（现在的 prompt 531-539 自己就在教模型说这句话）。

---

### P1 · `_has_bootstrap_language_violation` 扫描面过窄，`improvement_priorities / competitive_insight / benchmark_takeaway` 漏网

**证据**：`report_llm.py:284-298`

```python
texts = [
    result.get("hero_headline", ""),
    result.get("executive_summary", ""),
    *[str(item) for item in (result.get("executive_bullets") or [])],
]
```

**违反**：Spec §10.3 要求"`bootstrap` 下如果模型输出'今日新增''今日暴增'等措辞，必须回退到 deterministic fallback"。但此校验仅覆盖三个字段，`improvement_priorities[*].action`、`competitive_insight`、`benchmark_takeaway` 不在扫描范围。生产 `report_copy.competitive_insight` 生动展示了竞品长文本；若 LLM 把"较昨日 / 环比"写进去，当前没有兜底。

**影响**：潜在长文本字段可能出现违禁措辞，读者可见但系统不回退。

**建议修复**：把所有文本类 LLM 输出字段都纳入 merged 扫描：

```python
texts = [
    result.get("hero_headline", ""),
    result.get("executive_summary", ""),
    result.get("competitive_insight", ""),
    result.get("benchmark_takeaway", ""),
    *[str(item) for item in (result.get("executive_bullets") or [])],
    *[str((p or {}).get("action", "")) for p in (result.get("improvement_priorities") or [])],
]
```

并在 CI 里补一条 snapshot 回归：`bootstrap + LLM stub 返回 competitive_insight 带 "今日新增" → fallback 触发`。

---

### P2 · 邮件 fallback 文案仍写"新增评论 X 条"

**证据**：`report_templates/email_full.html.j2:221-223`

```jinja2
<div ...>
  当前纳入分析产品 {{ _kpis.get("own_product_count", 0) }} 个，新增评论 {{ _summary.get("ingested_review_count", 0) }} 条。
</div>
```

当 `_bullets` 为空时走 fallback，把 `ingested_review_count` 叫作"新增评论"。Spec §5.2/§10 要求它只能叫"本次入库评论"。bootstrap 下会把 589 条 backfill 呈现为"新增评论 593 条"。生产测试2 因 `report_copy.executive_bullets` 有值，该分支没暴露，但逻辑违反契约。

**建议修复**：改文案为"本次入库评论"，并在 bootstrap 下额外加一句"当前结果用于建立监控基线"。

---

### P2 · `negative_review_rate_display` 顶层 KPI 存在口径混淆

**证据**：`analytics.kpis`

```
negative_review_rate_display = "12.0%"   # 71/593 全量（含竞品）
own_negative_review_rate_display = "3.6%"  # 16/450 自有
```

测试2 邮件/HTML 的 KPI 卡展示的是 3.6%（自有），但顶层 `kpis` 仍保留了 12% 的"负面率"字段；若未来模板或下游系统 misconsume，这两个字段的业务含义极易踩坑（自有 vs 全量）。spec §5.3 约定 kpis 是唯一展示源，故顶层字段同时存在两套定义会造成 KPI 语义不明确。

**建议修复**：在 `report_analytics.py` 里明确顶层 KPI 只保留 `own_*` 口径，全量 `negative_review_rate` 降级为内部字段（加 `_` 前缀或挪到 `appendix`），避免被误消费。

---

### P2 · trend_digest `year` 视角在首日即 `ready` 可能误导读者

**证据**：测试2 产物 `year/sentiment.status=ready`、`year/competition.status=ready`。代码按 `date_published_parsed` 跨年聚合，若 593 条评论的发布日期横跨 5+ 年（LLM issue_cards 中出现"约 5 年 4 个月"），则年度分桶确有数据，判 ready 无算法错误。

**潜在风险**：读者看到年度 "舆情趋势 ready" 容易误读为"我方监控系统已经跑了若干年"；但真实语义是"所有评论发布时间跨越若干年"，是对品类历史的横截面回顾，而非组织化监控历史。

**建议修复**：在 year 视图顶部加 banner 文案区分"历史发布时间回顾 vs 监控期走势"；或在 `status_message` 上把"ready"再细分为 `ready_by_published_date` / `ready_by_monitor`。

---

### P3 · Chart.js `data` 数组里的 `null` 值

**证据**：测试2 HTML 中 4 处 `null`，全部在 `data: [..., null, ...]` 的 Chart.js 数据数组中（中断点）。

**判断**：Chart.js 原生语义，`null` 表示中断线段，属于数据层合法值，非用户可见文本；spec §10.4 禁止的"输出 None/null"指用户侧可见占位串。不建议修改。记录以防 CI 过严校验误伤。

---

### P3 · `fresh_review_count` 回退解析 `date_published` 存在解析歧义

**证据**：`report_snapshot.py:422-425`

```python
published = (
    _parse_date_flexible(review.get("date_published_parsed"), anchor_date=logical_day)
    or _parse_date_flexible(review.get("date_published"), anchor_date=logical_day)
)
```

当 `date_published_parsed` 缺失时，直接用 `date_published` 原始字符串（可能是"2 months ago"或"March 2026"）再跑一次 `_parse_date_flexible`。若解析失败仍算 "相对 `logical_day`"；若解析成功但时间不准，会把一个本应进 `estimated_dates` 的评论也纳入 `fresh_review_count`。

**建议修复**：回退路径只用于填充 `published`，但应把这些"回退解析"的评论同步打标，让 `has_estimated_dates` 能更精确触发。现在 `estimated_dates` 依赖于 `has_estimated_dates(reviews, logical_date_str)`，回退标记语义不够明显。

---

## 4. AI 分析可靠性专章

### 4.1 LLM 数据流

1. **Prompt 构建入口**：`report_llm.generate_report_insights(analytics, snapshot)`
2. **Sample 选择**：`_select_insight_samples(snapshot, analytics)`：从 `snapshot.cumulative.reviews ?? snapshot.reviews` 里按 5 档策略挑 20 条（自有差评 / 带图差评 / 竞品好评 / mixed / 最近）。
3. **Prompt 拼装**：顶层 KPI 摘要 + `top_negative_clusters`（含 sub_features 高频表现）+ `recommendations` + `gap_analysis` + `benchmark_examples` + `risk_products`。
4. **语义分支**：`bootstrap` 分支（L502-508）显式声明"首次基线，不要'今日新增'等增量措辞"；`incremental` 分支（L510-521 与 L533-539 两段并存）当前有 P1 漂移风险。
5. **输出校验**：`_parse_llm_response` → `_validate_insights`（截断 headline、限 bullets=3、`evidence_count` 不超过真实 `total_negative`）→ `_has_bootstrap_language_violation`（仅 3 字段）→ fallback。

### 4.2 Prompt 输入数据正确性

- 样本池优先 `cumulative` 是合理的（KPI 统计用 cumulative，样本也取 cumulative，口径一致）。
- Body 使用 `body_cn or body`，中英文混合仅发生在部分评论未翻译场景；测试2 `translation_completion_rate = 100%`，风险为零；若 `translation_incomplete=true`，prompt 会把原文与中文混合，LLM 可能产生英式句式的中文洞察。

### 4.3 生产 LLM 输出准确性（测试2 交叉核对）

| LLM 文案 | 实际 analytics 数据 | 判断 |
|---|---|---|
| "自有5款机型整体健康指数为94.9/100" | `kpis.health_index=94.9`、`own_product_count=5` | ✅ 一致 |
| "竞品在'做工与质量'维度拉开13点的差距指数" | `gap_analysis[0].gap_rate=13` | ✅ 一致 |
| "18.9%的高好评率（27/143）" | `competitor_positive_count=27, competitor_total=143` → 18.88% | ✅ 一致（四舍五入） |
| "自有产品8.0%差评率（36/450）" | `own_negative_count=36, own_total=450`（solid_build 类目） | ✅ 一致，但可能误读为整体差评率（实际整体 3.6%） |
| "Walton's Quick Patty Maker 差评率 1%" | `risk_products[0].negative_rate=0.0106` | ✅ 一致 |
| ".75 HP Grinder (#12) 差评率 4%" | 0.0356 | ✅ 一致（四舍五入） |
| ".5 HP Dual Grind Grinder (#8) 差评率 7%" | 0.0659 | ✅ 一致（四舍五入） |
| "17条结构设计缺陷" | `top_negative_clusters[0].review_count=17` | ✅ 一致 |
| "12条质量稳定性问题" | `top_negative_clusters[1].review_count=12` | ✅ 一致 |

**整体结论**：测试2 LLM 输出无幻觉，所有引用的数字都能在 analytics 里对回去。唯一语义陷阱是 "8.0% 差评率 (36/450)" 是 solid_build **类目专属**差评率，不是整体；但因为上下文里明确是"做工与质量维度"，逻辑自洽。

### 4.4 潜在幻觉风险

1. **incremental prompt 的"今日新增"误导**（P1，见 §3）。
2. **Bootstrap 漏检字段**（P1，见 §3）。
3. **样本 < 5 条的 warning**（`report_llm.py:523-529`）触发会要求 headline 体现"样本不足"；但目前 `analytics.window.reviews_count` 和 `change_digest.summary.fresh_review_count` 口径不一，L523 用 `window.reviews_count`（测试2 该值 = 593 不触发），真正 fresh=4 却未触发 low-sample 安全词。建议把这里改成 `fresh_review_count`。

---

## 5. 两轮生产产物 diff 与回归风险

| 对比项 | 测试1（14:41 · pre） | 测试2（17:12 · post） | 结论 |
|---|---|---|---|
| 顶层 `report_semantics / is_bootstrap / change_digest / trend_digest` | 4 字段 MISSING | 全部齐全 | ✅ 核心契约落地 |
| HTML `tab-nav` | 仅 2 个 tab（`总览 / 竞品对标`），`今日变化 / 变化趋势` 未渲染 | 7 个 tab 齐全 | ✅ Phase 1 IA 完成 |
| HTML `今日新增` | 1 次（文案漂移） | 0 次 | ✅ 修复生效 |
| Excel sheets | 4（缺 `今日变化`） | 5（含 `今日变化`） | ✅ 落地 |
| Excel `产品概览.采集评论数` 竞品 | 80 / 88（来自站点报告）但 `采集评论数=0, 差评=0` | 80/88 与真实采集 56/57 | ✅ 口径 bug 修复 |
| 产品数 | 7（snapshot）→ email title "等 7 个" | 8（snapshot + kpis）→ email title "等 8 个" | ✅（非 report 层，新增 1 个竞品 SKU 导致） |
| `警告.png`（数据质量告警邮件） | 已有独立通道 | 仍是独立通道（8 个产品 / stock_status 缺失 12.5%） | ✅ 与业务变动邮件解耦 |
| HTML 文件大小 | 410 KB | 338 KB（更紧凑：tab 裁成 4 个 panel） | — |

**回归风险**：测试1 的 HTML 结构（仅 2 tab）应当是老版本；测试2 结构是 Phase 1 完成态，没有明显回归。两轮产物均来自 bootstrap，incremental 路径（尤其 LLM prompt P1 问题）不会在当前产物中被触发。

---

## 6. 结论

### 总体判断
- **Phase 1 设计目标基本达成**。设计文档 §13 的 22 条验收标准中，除"artifact 路径迁移"未在产物层直接验证外，其他均由代码 + 测试2 产物证据闭合。
- **升级 vs 产物对齐度**：~95%。最严重问题是 LLM `incremental` 路径里"今日新增"直写，这是 P1 级潜在漂移，但目前 bootstrap 没有激活，所以产物里看不到，**上线第二天起就会触发**。

### 建议行动
**P1 必修（上线第二天前）**
1. 修 `report_llm.py:531-539` incremental prompt，改用 `change_digest.summary.fresh_review_count / historical_backfill_count`，并明示"禁止把补采计入业务新增"。
2. 扩大 `_has_bootstrap_language_violation` 扫描面至 `competitive_insight / benchmark_takeaway / improvement_priorities[*].action`，补 snapshot 回归。
3. 把 LLM low-sample 安全词（`report_llm.py:523`）的计数改成 `fresh_review_count`。

**P2 建议修**
4. 邮件 fallback 文案"新增评论"→"本次入库评论"（`email_full.html.j2:222`）。
5. `negative_review_rate`（全量）从顶层 kpis 降级到内部/appendix，避免被下游误消费。
6. trend `year` 视图加一句语义 banner（"历史发布时间回顾"），与未来真实"监控期年同比"区分。
7. artifact resolver 上线一轮手工回归：把生产 `analytics_path` 改成一条失效绝对路径，确认次日 run 仍能从 `REPORT_DIR` / `db/reports` 恢复 previous context。

**P3 记录**
8. `fresh_review_count` 回退解析 `date_published` 的 `estimated_dates` 标签化。
9. Chart.js `null` 中断点不改，记入 CI 白名单。

### 是否可上线
- **可以上线**。Phase 1 的所有展示层硬契约都在 测试2 产物里兑现，用户可见层无违规。
- **但强烈建议在第二天（首个 incremental run）之前修复 P1-a/b**，否则 LLM headline 将再次漂移，新用户对本次治理的信任很快会反弹。

---

## 附录：关键代码位置索引

| 功能 | 文件:行 |
|---|---|
| `report_semantics / is_bootstrap` 生成 | `report_analytics.py:1953-1954` |
| `change_digest / trend_digest` 顶层透传 | `report_common.py:648-658` |
| `build_change_digest` | `report_snapshot.py:408-603` |
| `_build_trend_digest` | `report_analytics.py:1822-1832` |
| `compute_health_index` 贝叶斯修正 | `report_common.py:497-533` |
| artifact resolver | `report_snapshot.py:76-140` |
| LLM prompt | `report_llm.py:376-560` |
| bootstrap 违禁词检测 | `report_llm.py:280-298` |
| LLM fallback | `report_llm.py:563-581`、`640-688` |
| Excel 5-sheet | `report.py:981-1358` |
| HTML bootstrap 话术 | `daily_report_v3.html.j2:142-158` |
| 邮件 bootstrap 话术 | `email_full.html.j2:96-109` |
