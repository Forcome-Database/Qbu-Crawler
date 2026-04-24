# Daily Report 升级 — 最佳实践方案（交叉复核 V2）

**日期**：2026-04-24
**来源**：
- Claude 独立审查：`docs/reviews/2026-04-24-report-upgrade-claude-review.md`
- Codex 独立审查：`docs/reviews/2026-04-24-report-upgrade-codex-review.md`
- 对标设计：`docs/superpowers/specs/2026-04-23-report-change-and-trend-governance-design.md`
- 对标计划：`docs/superpowers/plans/2026-04-23-report-change-and-trend-governance.md`
- Devlog：`docs/devlogs/D018-report-change-trend-governance.md`

---

## 0. 两位审查人结论对比

|  | Claude | Codex |
|---|---|---|
| 可上线判断 | ✅ 可上线（次日 P1 必修） | ⚠️ **不建议直接上线**（3 条 P1 当前 bootstrap 下就已影响用户判断） |
| 主要 P1 类型 | "incremental 路径"潜伏问题（上线第二天才暴露） | "用户当下就能看到的错"（tooltip / 丢表 / LLM 排序错） |
| 相互覆盖 | 违禁词扫描面窄、fallback 文案"新增评论"残留、写入侧绝对路径 | 同左 |

**合并判断**：采用 Codex 的更严格结论 — **不建议直接上线**，因为 Codex 发现的 3 条 P1（§1 第 A/B/C 条）在当前 测试2 产物里已经用户可见，且会直接**误导判断**（LLM 说最低风险是"领跑"、趋势页吞掉已就绪数据、同一卡片的 tooltip 与实际值语义不一致）。

---

## 1. 合并 P1 清单（6 条，按影响面排序）

### P1-A · 健康指数/健康分分裂成 3 套公式（Codex 独家发现）

**现场证据**：

1. **Tooltip**（用户 hover 看到的定义）：`qbu_crawler/server/report_common.py:54`
   ```python
   "健康指数": "综合评分 = 20%站点评分 + 25%样本评分 + 35%(1−差评率) + 20%(1−高风险占比)，满分100"
   ```
2. **顶层 KPI 实际算法**：`qbu_crawler/server/report_common.py:497-533` 贝叶斯 NPS 代理（`((promoters - detractors) / own_reviews) × 100` 的线性映射 + 小样本向先验 50 收缩）。
3. **趋势页"健康分"算法**：`qbu_crawler/server/report_analytics.py:1458`
   ```python
   health_scores = [round(100 - rate, 1) if own_total_by_bucket[label] else 0
                    for label, rate in zip(labels, own_negative_rates)]
   ```
   即 `100 - 自有差评率`。
4. **产物**：
   - `test2 html:1613-1614` tooltip 展示的是旧加权公式，卡片值 `94.9`（贝叶斯 NPS 结果）
   - `test2 analytics:14121-14130` 月度 `2025-11` 桶写成 `health_index=0.0`，对应 `own_negative_rate=100.0`，不是贝叶斯健康指数

**影响**：用户在总览看到 `94.9/100`，在趋势页看到某月 `0.0`，在 tooltip 看到第三套解释 — 同名指标三种语义。小样本桶位会被趋势页放大成 `0.0` 极端值。

**根因**：Phase 1 引入贝叶斯健康指数时只改了顶层 KPI，tooltip 字典与趋势聚合函数没同步迁移。

### P1-B · HTML 模板按"维度级 status"一刀切，吞掉已就绪 KPI/表格（Codex 独家发现）

**现场证据**：

- **后端已输出组件级 status**：`qbu_crawler/server/report_analytics.py:1645-1668` — products 维度在样本不足时返回 `block.status="accumulating"` 但 `kpis.status="ready"` + `table.status="ready"`。
- **产物验证**（`test2 analytics:13494-13535` → `trend_digest.data.month.products`）：
  ```
  block.status = accumulating
  kpis.status = ready, kpis.items count = 4    ← 有数据
  primary_chart.status = accumulating
  table.status = ready, table.rows count = 5   ← 有数据
  ```
- **模板整块 if 截断**：`qbu_crawler/server/report_templates/daily_report_v3.html.j2:294-337`
  ```jinja2
  {% if trend_block.status == "ready" %}
    {# 只有这里才渲染 kpis / chart / table #}
  {% else %}
    <div class="trend-status ...">{{ trend_block.status_message ... }}</div>
  {% endif %}
  ```
- **产物**：`test2 html:2150-2162` 月度/产品区只剩文案"产品快照样本不足，连续状态趋势仍在积累"，4 个 KPI items + 5 行 table 完全丢失。
- **competition 维度后端本身也一刀切**：`report_analytics.py:1734-1742` 用 `_empty_trend_dimension("accumulating", ...)` 清空所有子组件，产物 `month.competition` KPI/table 全空。

**影响**：设计明确要求 Phase 1 允许"同一维度内部部分组件 ready、部分组件 accumulating"（spec §8.5），结果 JSON 层做到了，HTML 层把它又砍回去了。用户失去"虽然主图还不稳，但已经有几个 SKU 在跟踪 / 已经有几个评分点"的**可用趋势审计信息**。

### P1-C · LLM `executive_bullets` 出现事实性排序/关系词错误（Codex 独家发现）

**现场证据**：

- `test2 analytics` `report_copy.executive_bullets[0]`：
  > "高危型号需紧急干预：.5 HP Dual Grind Grinder (#8)以29.6分风险值**领跑**..."
- 实际 `risk_products` 从高到低（`test2 analytics:4874-4962`）：
  ```
  Walton's Quick Patty Maker     : risk_score = 35.1 ← 真正的第一
  .75 HP Grinder (#12)           : risk_score = 33.3
  .5 HP Dual Grind Grinder (#8)  : risk_score = 29.6 ← Bullet 说 "领跑"
  ```
- `executive_bullets[1]`：
  > "17条结构设计缺陷...与12条质量稳定性问题...**并列首位**"
- 实际（`test2 analytics:3966 / 4091`）：`17 ≠ 12`，不是并列。
- **校验器只截 `evidence_count` 上限**：`qbu_crawler/server/report_llm.py:623-637`
  ```python
  for p in result.get("improvement_priorities") or []:
      claimed = int(p.get("evidence_count", 0) or 0)
      p["evidence_count"] = min(claimed, total_negative)
  # 不校验 top/排序/并列/领先/落后
  ```

**影响**：用户会被 Bullet 1 引导去"冻结 #8 发货"，但真正应该优先处理的是 `Walton's Quick Patty Maker` — **这是一个会直接导致错误业务决策的幻觉**。

### P1-D · LLM incremental prompt 仍直写 "今日新增评论 {window.reviews_count}"（Claude 独家发现）

**现场证据**：`qbu_crawler/server/report_llm.py:531-541`（L510-521 已改造为读 `change_digest.summary` 的正确写法，但 L531-541 这第二段遗留代码仍在注入）：

```python
# Window summary section (P007 Task 5) ← 老版注释，未清理
window = analytics.get("window", {})
if report_semantics != "bootstrap" and window.get("reviews_count", 0) > 0:
    prompt += f"\n\n--- 今日变化 ---"
    prompt += f"\n今日新增评论 {window['reviews_count']} 条"         # ← 违反 spec §5.2
    prompt += f"（自有 ..., 竞品 ...）"
    if window.get("new_negative_count", 0) > 0:
        prompt += f"\n注意：新增自有差评 {window['new_negative_count']} 条"
    prompt += "\n请在 executive_bullets 中提及今日新增变化..."
```

两段 `--- 今日变化 ---` 都会注入（incremental 时），后一段会覆盖前一段的正确口径。bootstrap 下产物未激活，所以 Codex 只看到 L510-521 的正确版本，没看到 L531-541 的残留（这也说明了"独立审查"的价值 — 两个人覆盖面互补）。

**影响**：首个 incremental run 起 LLM headline 立即回到"今日新增 X 条"漂移。

### P1-E · bootstrap 违禁词检测字段面过窄 + 模式词不够宽（两审共识）

**现场证据**：`qbu_crawler/server/report_llm.py:284-298`

```python
texts = [
    result.get("hero_headline", ""),
    result.get("executive_summary", ""),
    *[str(item) for item in (result.get("executive_bullets") or [])],
]
# ❌ 未覆盖：competitive_insight / benchmark_takeaway / improvement_priorities[*].action
forbidden_patterns = (r"今日新增", r"今日暴增", r"较昨日", r"较上期", r"环比", r"今日.*新增")
# ❌ 未覆盖：新增评论 / 新增 N 条评论 / 同比
```

**影响**：Spec §10.3 "bootstrap 下违规必须 fallback" 的守门员有两个洞 — 字段洞（长文本字段漏扫）+ 模式洞（`新增评论` 这种 fallback 自己都写的措辞不拦截）。

### P1-F · fallback 与邮件兜底文案仍写 "新增评论 X 条"（两审共识）

**现场证据**：

- `qbu_crawler/server/report_common.py:639-642`
  ```python
  bullets.append(
      f"当前纳入分析产品 {normalized['kpis']['product_count']} 个，"
      f"新增评论 {normalized['kpis']['ingested_review_rows']} 条。"
  )
  ```
- `qbu_crawler/server/report_templates/email_full.html.j2:221-223`
  ```jinja2
  当前纳入分析产品 {{ _kpis.get("own_product_count", 0) }} 个，
  新增评论 {{ _summary.get("ingested_review_count", 0) }} 条。
  ```
- fallback 自己既不感知 `report_semantics`，也不在 P1-E 的违禁词拦截范围内 → **三重失守**：LLM 违规 → 触发 fallback → fallback 本身还是违规文案。

---

## 2. P2/P3 清单（Phase 2 前修完）

| # | 问题 | 来源 |
|---|---|---|
| P2-G | artifact 写入侧 `analytics_path / excel_path / html_path / pdf_path` 仍固化单机绝对路径（`report_snapshot.py:1370-1373`、`workflows.py:722-727,755-760`），只有 `snapshot_path` 过了 `_artifact_db_value()` | 两审共识 |
| P2-H | 顶层 `kpis` 同时暴露 `negative_review_rate`（含竞品 12%）与 `own_negative_review_rate`（自有 3.6%），下游模板易误消费 | Claude |
| P2-I | trend `year` 视角首日即 `ready`（基于 `date_published_parsed` 横跨历史），需加"历史发布时间回顾 vs 监控期走势"语义 banner | Claude |
| P2-J | LLM low-sample 安全词（`report_llm.py:522-529`）看 `window.reviews_count`（测试2 = 593 不触发），应改看 `change_digest.summary.fresh_review_count`（实际 = 4） | Claude |
| P3-K | `fresh_review_count` 在 `date_published_parsed` 缺失时回退用 `date_published` 原始串，应同步打 `estimated` 标让 `has_estimated_dates` 更精确 | Claude |
| P3-L | Chart.js `data` 数组中 `null`（中断点）为合法值，不改，但需在 CI 违禁词白名单里显式排除 | Claude |

---

## 3. 上线门禁（逐条可执行）

### 必修（P1-A/B/C/D/E/F 全部完成才能开启 Phase 1 正式上线）

#### 修 1 · 统一健康指数唯一来源（P1-A）

**原则**：顶层贝叶斯 NPS 健康指数是唯一权威，tooltip 与趋势页必须复用同一公式或明确改名。

- **A 方案（推荐）**：把 `report_analytics.py:1450-1458` 的趋势"健康分"重写为逐桶复用 `compute_health_index`（每个 bucket 的 reviews 作为 analytics 子集，调同一函数）；tooltip `report_common.py:54` 改成"贝叶斯 NPS 代理（promoters − detractors / own_reviews），样本 < 30 向先验 50 收缩"的真实文案。
- **B 方案（保底）**：如果趋势页不想承担贝叶斯小样本收缩，就**改名**为"满意度指数"或"反向差评率"，不再叫"健康分"，并单独给 tooltip。

门禁测试：
```python
def test_health_index_consistency():
    # tooltip text contains actual formula keywords
    from qbu_crawler.server.report_common import METRIC_TOOLTIPS
    assert "贝叶斯" in METRIC_TOOLTIPS["健康指数"] or "NPS" in METRIC_TOOLTIPS["健康指数"]

def test_trend_health_score_uses_same_formula():
    # small-sample bucket should shrink toward prior, not hit 0
    tiny = {...}  # 1 negative review only
    bucket_health = _compute_bucket_health(tiny)
    assert 30 < bucket_health < 70  # not 0, not 100
```

#### 修 2 · 模板按组件级 status 分别渲染（P1-B）

**文件**：`qbu_crawler/server/report_templates/daily_report_v3.html.j2:294-337`

```jinja2
{# 替代当前 L294-337 的整块 if #}
{% set _kpi_ready = trend_kpis.get("status") == "ready" and trend_kpis.get("items") %}
{% set _chart_ready = trend_block.primary_chart and trend_block.primary_chart.get("status") == "ready" %}
{% set _table_ready = trend_table.get("status") == "ready" and trend_table.get("rows") %}

{% if not (_kpi_ready or _chart_ready or _table_ready) %}
  <div class="trend-status trend-status-{{ trend_block.status or 'degraded' }}">
    {{ trend_block.status_message or "样本暂未就绪，请继续积累日报样本。" }}
  </div>
{% else %}
  {% if trend_block.status_message %}
    <div class="trend-partial-note">{{ trend_block.status_message }}</div>
  {% endif %}
  {% if _kpi_ready %}
  <div class="trend-kpi-grid">
    {% for item in trend_kpis["items"] %}
    <article class="trend-kpi-card">
      <span class="trend-kpi-label">{{ item.label or "" }}</span>
      <strong class="trend-kpi-value">{{ item.value if item.value is not none else "-" }}</strong>
    </article>
    {% endfor %}
  </div>
  {% endif %}
  {% if _chart_ready and chart_key in charts %}
  <div class="chart-container trend-chart-container">...</div>
  {% elif trend_block.primary_chart %}
  <div class="trend-chart-placeholder">{{ trend_block.primary_chart.get("status_message") or "主图积累中" }}</div>
  {% endif %}
  {% if _table_ready %}
  <div class="table-wrap trend-table-wrap">...</div>
  {% endif %}
{% endif %}
```

**同时改后端** `report_analytics.py:1734-1742` 的 `competition` 维度：不要整块 `_empty_trend_dimension`，改成组件级分别判断（类似 products 的写法）。

#### 修 3 · 对 `report_copy.*` 加 deterministic 对账（P1-C）

**文件**：`qbu_crawler/server/report_llm.py` 的 `_validate_insights`（L610-637）

```python
def _validate_insights(llm_output: dict, analytics: dict) -> dict:
    result = dict(llm_output)
    # ... 原有截断逻辑保留 ...

    # 新增：关系词对账
    risks = (analytics.get("self") or {}).get("risk_products") or []
    clusters = (analytics.get("self") or {}).get("top_negative_clusters") or []

    top_risk_name = risks[0].get("product_name") if risks else None
    top_cluster_count = clusters[0].get("review_count") if clusters else None

    rel_words = ("领跑", "最高", "第一", "榜首", "首位", "登顶", "最严重")
    tied_words = ("并列", "打平", "持平")

    # 扫描所有 LLM 文本输出
    texts_with_source = {
        "hero_headline": result.get("hero_headline", ""),
        "executive_summary": result.get("executive_summary", ""),
        "competitive_insight": result.get("competitive_insight", ""),
        "benchmark_takeaway": result.get("benchmark_takeaway", ""),
    }
    for i, b in enumerate(result.get("executive_bullets") or []):
        texts_with_source[f"bullet_{i}"] = str(b)

    violations = []
    for source, text in texts_with_source.items():
        for word in rel_words:
            # 如果说 X "领跑"/"最高"，但 X 不是 risks[0]
            if word in text and top_risk_name:
                for r in risks[1:]:  # 非 top
                    if r.get("product_name") and r["product_name"] in text:
                        # 该句同时提到非 top SKU + 关系词，高概率错
                        violations.append(
                            f"{source}: 关系词'{word}'指向了非 top SKU {r['product_name']}"
                        )
        for word in tied_words:
            # 如果说两类问题"并列"，检查两个 cluster count 是否真的相等
            if word in text and len(clusters) >= 2:
                c1, c2 = clusters[0].get("review_count", 0), clusters[1].get("review_count", 0)
                if c1 != c2:
                    violations.append(f"{source}: 关系词'{word}'与真实计数不符 ({c1} vs {c2})")

    if violations:
        logger.warning("LLM report_copy relation violations: %s", violations)
        # 触发 fallback（可配置：strict = drop bullet；lenient = 只记日志）
        return _fallback_insights(analytics)
    return result
```

**更稳妥的做法**（长期）：Top-N 排序句改成模板化生成，不让 LLM 自由发挥。
例如：`hero_headline = f"{risks[0].product_name} 风险最高（{risks[0].risk_score}/100），建议优先处理。"`

#### 修 4 · 清理 LLM `report_llm.py` 重复的 `--- 今日变化 ---` 段（P1-D）

**删除**：`qbu_crawler/server/report_llm.py:531-541` 全段（从 `# Window summary section (P007 Task 5)` 到 `elif report_semantics != "bootstrap" and analytics.get("perspective") == "dual": ...` 之前）。

**保留并完善**：L510-521 已有 `change_digest` 正确读法，只需在 backfill 占比高时追加禁令：

```python
else:
    summary = change_digest.get("summary") or {}
    if summary:
        ingested = summary.get("ingested_review_count", 0)
        fresh = summary.get("fresh_review_count", 0)
        backfill = summary.get("historical_backfill_count", 0)
        prompt += "\n\n--- 今日变化 ---"
        prompt += f"\n本次入库评论 {ingested} 条（近30天业务新增 {fresh} 条、历史补采 {backfill} 条）"
        if summary.get("fresh_own_negative_count", 0) > 0:
            prompt += f"\n近30天自有差评 {summary['fresh_own_negative_count']} 条，请在 executive_bullets 中优先体现"
        if ingested > 0 and backfill / ingested >= 0.7:
            prompt += "\n⚠ 本次入库以历史补采为主。禁止把补采评论计入业务新增；只能叙述'本次入库'或'近30天业务新增'。"
```

#### 修 5 · 扩大违禁词守护（P1-E）

`qbu_crawler/server/report_llm.py:280-298`：

```python
def _has_bootstrap_language_violation(result, analytics):
    if _report_semantics(analytics) != "bootstrap":
        return False

    priorities = result.get("improvement_priorities") or []
    texts = [
        result.get("hero_headline", ""),
        result.get("executive_summary", ""),
        result.get("competitive_insight", ""),
        result.get("benchmark_takeaway", ""),
        *[str(item) for item in (result.get("executive_bullets") or [])],
        *[str((p or {}).get("action", "")) for p in priorities],
    ]
    merged = "\n".join(texts)
    forbidden_patterns = (
        r"今日新增",
        r"今日暴增",
        r"较昨日",
        r"较上期",
        r"环比",
        r"同比",
        r"今日.*新增",
        r"本日.*新增",
        r"新增\s*\d+\s*条\s*评论",   # 宽泛模式，覆盖 P1-F 场景
    )
    return any(re.search(p, merged) for p in forbidden_patterns)
```

#### 修 6 · fallback 与邮件兜底感知 `report_semantics`（P1-F）

**`report_common.py:616-643` `_fallback_executive_bullets`**：

```python
def _fallback_executive_bullets(normalized):
    bullets = []
    semantics = normalized.get("report_semantics") or "incremental"
    is_boot = bool(normalized.get("is_bootstrap")) or semantics == "bootstrap"
    top_product = (normalized["self"]["risk_products"] or [None])[0]
    # ... 保留原有 3 条 bullet 生成逻辑 ...
    if not bullets:
        ingested = normalized["kpis"]["ingested_review_rows"]
        products = normalized["kpis"]["product_count"]
        if is_boot:
            bullets.append(
                f"当前纳入分析产品 {products} 个，本次入库评论 {ingested} 条，用于建立监控基线。"
            )
        else:
            digest_summary = (normalized.get("change_digest") or {}).get("summary", {}) or {}
            fresh = digest_summary.get("fresh_review_count", 0)
            backfill = digest_summary.get("historical_backfill_count", 0)
            bullets.append(
                f"当前纳入分析产品 {products} 个，本次入库评论 {ingested} 条"
                f"（近30天业务新增 {fresh}，历史补采 {backfill}）。"
            )
    return bullets[:3]
```

同步改 `_fallback_hero_headline`（L600-613）：bootstrap 下无 top_product 时返回 "首次基线扫描 X 条评论完成，开始监控"。

**`email_full.html.j2:220-224`**：

```jinja2
{% else %}
  {% if _semantics == "bootstrap" or _view_state == "bootstrap" %}
    <div style="...">首次基线已完成，本次入库评论 {{ _summary.get("ingested_review_count", 0) }} 条，用于建立监控基线。</div>
  {% else %}
    {% set _fresh = _summary.get("fresh_review_count", 0) %}
    {% set _backfill = _summary.get("historical_backfill_count", 0) %}
    <div style="...">本次入库评论 {{ _summary.get("ingested_review_count", 0) }} 条（近30天业务新增 {{ _fresh }}，历史补采 {{ _backfill }}）。</div>
  {% endif %}
{% endif %}
```

---

### 建议修（Phase 2 前，P2 全修）

#### 修 7 · 统一 artifact 写入相对路径（P2-G）

- `qbu_crawler/server/report_snapshot.py:1370-1373` 返回值前跑一遍 `_artifact_db_value()`
- `qbu_crawler/server/workflows.py:722-727,755-760` 落库前再保险一次（防止上游未处理）
- resolver 继续兼容旧绝对路径

#### 修 8 · kpis 字段消歧（P2-H）

`report_analytics.py` 在构建顶层 kpis 时：
- 展示用 `own_*` 口径明确保留（`own_negative_review_rate / own_negative_review_rate_display`）
- 全量 rate（含竞品）重命名或下沉：`all_sample_negative_rate` 或移入 `analytics.appendix`

#### 修 9 · trend `year` 视图语义 banner（P2-I）

`daily_report_v3.html.j2` 的 `变化趋势` tab 下 year 切换时增加：

> 年度视角基于评论发布时间聚合。历史数据源于站点用户的历史发布时间跨度，不代表本监控系统的实际运行年限。

#### 修 10 · low-sample 口径（P2-J）

`report_llm.py:522-529`：

```python
summary = change_digest.get("summary") or {}
fresh_count = summary.get("fresh_review_count", 0)
if fresh_count < 5:
    prompt += (
        f"\n\n⚠️ 本期近30天业务新增仅 {fresh_count} 条，样本极少。"
        "hero_headline 应体现'样本不足'或'数据有限'，不做趋势推断或严重度升级。"
    )
```

---

## 4. 测试补强清单

新增 / 加强以下测试（按文件分组）：

| 测试文件 | 用例 |
|---|---|
| `tests/test_report_analytics.py` | `test_trend_health_score_uses_bayesian`（修 1） |
| `tests/test_report_common.py` | `test_metric_tooltip_health_index_matches_implementation`（修 1） |
| `tests/test_report_common.py` | `test_fallback_bullets_bootstrap_uses_baseline_wording`（修 6） |
| `tests/test_report_common.py` | `test_fallback_bullets_incremental_cites_change_digest`（修 6） |
| `tests/test_v3_html.py` | `test_trend_panel_shows_ready_kpis_even_when_block_accumulating`（修 2） |
| `tests/test_v3_html.py` | `test_trend_panel_competition_mixed_state_rendering`（修 2） |
| `tests/test_v3_html.py` | `test_email_fallback_bootstrap_no_new_review_wording`（修 6） |
| `tests/test_v3_html.py` | `test_year_trend_has_semantic_banner`（修 9） |
| `tests/test_report_llm.py` | `test_incremental_prompt_drops_window_today_new_segment`（修 4 — 断言 prompt 中不再同时出现两段 `--- 今日变化 ---`） |
| `tests/test_report_llm.py` | `test_incremental_prompt_uses_change_digest_fields`（修 4） |
| `tests/test_report_llm.py` | `test_bootstrap_violation_covers_all_text_fields`（修 5） |
| `tests/test_report_llm.py` | `test_backfill_dominant_prompt_forbids_business_new_wording`（修 4） |
| `tests/test_report_llm.py` | `test_report_copy_relation_word_cross_check_rejects_wrong_top_sku`（修 3） |
| `tests/test_report_llm.py` | `test_report_copy_tied_words_require_equal_counts`（修 3） |
| `tests/test_report_integration.py` | `test_kpis_exposes_own_rate_only_to_templates`（修 8） |
| `tests/test_report_snapshot.py` | `test_workflow_run_stores_relative_artifact_paths`（修 7） |
| `tests/test_report_snapshot.py` | `test_artifact_resolver_recovers_when_original_path_moved`（修 7 补） |

---

## 5. CI 硬门禁（grep 级）

```bash
# 1. 源码不得再用 "今日新增"（除违禁词表）
grep -rn "今日新增" qbu_crawler/ | grep -vE "forbidden_patterns|禁止|不得"
# 期望：0 命中

# 2. 模板不得出现 "新增评论 "
grep -rn "新增评论" qbu_crawler/server/report_templates/ qbu_crawler/server/report_common.py qbu_crawler/server/report_llm.py | grep -v "本次入库"
# 期望：0 命中

# 3. 模板不得直接解释 window.reviews_count / cumulative_kpis
grep -rn "cumulative_kpis\|window\.reviews_count\|_cumulative" qbu_crawler/server/report_templates/
# 期望：0 命中

# 4. trend 模板必须按组件 status 分支
grep -n 'trend_block.status == "ready"' qbu_crawler/server/report_templates/daily_report_v3.html.j2
# 期望：0 命中（因为应改为 kpis/chart/table 独立判断）

# 5. 健康指数 tooltip 必须含"贝叶斯"或"NPS"
grep '"健康指数"' qbu_crawler/server/report_common.py | grep -E "贝叶斯|NPS"
# 期望：1+ 命中
```

---

## 6. 上线计划（分两阶段）

### Stage A：P1 修复 PR（阻塞上线）
- 分支：`fix/report-p1-governance-round2`
- 6 条修改合并为一个 PR（修 1~修 6）
- CI：上文门禁 grep 全绿 + 新增单测全绿 + 现有全量 pytest 全绿
- 预发回归：
  1. 触发一次真实 bootstrap run，核对 HTML `变化趋势/产品` 页是否展示 KPI + 表格
  2. 核对 LLM `executive_bullets` 是否无排序错误（人工肉眼校验 `risk_products[0]` 是否被称为 "领跑/最高/第一"）
  3. 核对 tooltip "健康指数" 文案与顶层 `94.x` 卡片口径一致

### Stage B：P2 + Phase 2 深化
- 修 7~10 合并为独立 PR
- 完成后再推进 Phase 2（`trend_digest` 扩展辅图 + 表格）

### 回滚策略
- 如果上线后发现 LLM 关系词仍漂移：把 `_validate_insights` 的 `violations` 触发条件改为"非空立即走 fallback"（严格模式）
- 如果健康指数迁移后某些历史产物渲染异常：保留一个 env 变量 `REPORT_HEALTH_FORMULA=legacy|bayesian` 做灰度，默认 `bayesian`

---

## 7. Phase 2 前置准备

Phase 2 的 T9/T10（`trend_digest` 扩展辅图 + 表格）**必须在 P1 全部修复后再启动**，否则：

1. P1-A 的健康指数三公式问题会扩散到更多趋势子组件
2. P1-B 的模板一刀切会让 Phase 2 新增的辅图同样被吞掉
3. P1-C 的 LLM 关系词漂移会在更复杂的 Phase 2 洞察文案里放大

额外前置项：
- **明确 `competitive_gap_index` 取值范围**（产物里 `kpis.competitive_gap_index=5` vs LLM 引用 "13点的差距指数"，同时 `gap_analysis[0].gap_rate=13` — 顶层聚合 vs 类目粒度并存，容易混淆）
- **trend `primary_chart` 在 `accumulating` 状态的 UI 设计评审**（修 2 后新增的 `trend-chart-placeholder` 需要人工视觉验收）

---

## 8. 最终结论

> 升级设计质量高、主路径语义修复明显（`今日变化` / `变化趋势` / Excel 5-sheet / bootstrap 话术 / warning 契约都已落地），但仍有 **6 条 P1 问题**需要在 Phase 1 正式上线前收口，其中 3 条（P1-A/B/C）在当前 bootstrap 产物里已经**用户可见并影响业务判断**。
>
> **建议**：不要直接上线，**先合并 Stage A 的 P1 修复 PR**（6 条修改一起），CI 门禁 + 预发回归通过后再开量。

---

## 附录：P1 严重度与用户可见性矩阵

| # | 现象 | 当前是否可见 | 可见后果 | 触发条件 | 严重度 |
|---|---|---|---|---|---|
| P1-A | 健康指数三公式 | ✅ 已可见（tooltip vs 卡片值 vs 趋势 `0.0`） | 同名指标语义混乱 | 任何 run | **严重** |
| P1-B | 趋势页吞掉已就绪 KPI/表格 | ✅ 已可见（`月/产品` 空白） | 设计承诺的"功能不砍"被砍 | 任何 mixed 状态 | **严重** |
| P1-C | LLM 排序错误（29.6 分"领跑"） | ✅ 已可见 | 误导优先处理低风险 SKU | bootstrap + 多风险 SKU | **严重** |
| P1-D | incremental prompt 重复段 "今日新增" | ⏳ 次日激活 | LLM headline 再次漂移 | 首个 incremental | **高** |
| P1-E | 违禁词扫描窄 | ⏳ 条件触发 | 违规绕过 fallback | LLM 幻觉 + 长文本字段 | **高** |
| P1-F | fallback "新增评论" | ⏳ 罕见触发 | 建档口径漏出 | LLM 不可用 + 空 bullets | **中** |
