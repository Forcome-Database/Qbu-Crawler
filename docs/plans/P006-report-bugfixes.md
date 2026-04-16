# P006 — 报告系统 Bug 修复与基础加固

> **关联需求**：2026-04-15 深度审计发现的 7 个问题
> **优先级**：P0-P2（按修复项分级）
> **预估工作量**：2-3 天
> **前置条件**：无
> **后续**：方案 2（P007 双视角架构升级）依赖本方案的部分修复

---

## 背景

2026-04-15 对每日报告系统做了完整的代码审计和数据核对（对比邮件截图、JSON 产物、生产数据库），发现以下问题：

1. Change/Quiet 报告模式是**死代码**——工作流路由 bug 导致永远跳过
2. LLM 叙述文本的**数据来源与 KPI 不一致**——LLM 看全量 DB，KPI 看当日窗口
3. 健康指数**无最小样本量保护**——1 条好评=100 分满分
4. KPI Delta 计算**已定义但从未调用**——环比趋势无法展示
5. 基线模式**退出条件过严**——quiet run 不计入，可能数周停留在 baseline
6. 竞品差距指数**对样本量极度敏感**——1 条评论导致指数从 5 跳到 50
7. 邮件收件人**来源不一致**——full 模式读环境变量，change/quiet 读文件

---

## 修复项清单

### Fix-1（P0）：激活 Change/Quiet 报告模式

**问题根因**

`workflows.py` 的 `_advance_run()` 方法中，当 `report_phase == "none"` 时：

```python
# workflows.py ~line 632-659
if snapshot.get("reviews_count", 0) == 0:
    update_workflow_run(run_id,
        status="completed",
        report_phase="skipped_no_reviews",
        report_mode="skipped")
    enqueue_notification(kind="workflow_report_skipped", ...)
    return  # ← 直接返回，绕过 generate_report_from_snapshot()
```

`generate_report_from_snapshot()` 内部的 `determine_report_mode()` 能正确路由到 full/change/quiet，但上游的 early return 使其永远不被调用。

**修改方案**

文件：`qbu_crawler/server/workflows.py`

```python
# 移除 early return，统一走报告流程：
# - reviews_count > 0 → fast_pending → full_pending → generate_report_from_snapshot() → "full" 模式
# - reviews_count == 0 → 跳过 fast_pending，直接进入 full_pending → generate_report_from_snapshot() → "change" 或 "quiet" 模式

# 改动点 1：report_phase == "none" 分支
if snapshot.get("reviews_count", 0) == 0:
    # 不再 early return，而是跳过 fast report 阶段，直接进入 full_pending
    update_workflow_run(run_id, report_phase="full_pending")
    # fast report 对 0 评论无意义，跳过
else:
    update_workflow_run(run_id, report_phase="fast_pending")

# 改动点 2：full_pending 分支中，generate_report_from_snapshot() 已能处理 3 种模式
# 无需额外改动，但需确认 change/quiet 的返回值正确更新 workflow_runs 记录

# 改动点 3：通知类型
# change 模式 → 复用 workflow_full_report 通知，payload 中 report_mode="change"
# quiet 模式 → 复用 workflow_full_report 通知，payload 中 report_mode="quiet"
# 或新增 workflow_change_report / workflow_quiet_report 通知模板
```

**验证方法**

1. 模拟一次无新评论但有价格变动的 run → 应触发 change 模式，发送价格变动邮件
2. 模拟一次无新评论且无变动的 run → 应触发 quiet 模式，发送静默邮件
3. 检查 workflow_runs 表的 report_mode 字段：不应再出现 "skipped"

**影响范围**

- `workflows.py`：~30 行改动
- 可能需补充 DingTalk 通知模板（change/quiet 对应的消息格式）
- 需确认 `_render_quiet_or_change_html()` 和 `_send_mode_email()` 在实际运行中正常工作（此前从未被生产调用过）

---

### Fix-2（P0）：统一 LLM 分析的数据上下文

**问题根因**

`report_llm.py` 的 `_select_insight_samples()` 通过 5 次 `models.query_reviews()` 调用从**全量数据库**选取评论样本，不受 snapshot 时间窗口限制。LLM 看到历史差评后生成了与当日 KPI 矛盾的叙述（如 Run-3：KPI 显示 0 差评，LLM 写"3 条 1 星差评"）。

**修改方案**

文件：`qbu_crawler/server/report_llm.py`

```python
# 当前 _select_insight_samples() 签名：
def _select_insight_samples(analytics: dict, snapshot: dict) -> list[dict]:
    # 5 次 DB 查询（无时间过滤）
    ...

# 修改为：从 snapshot["reviews"] 中选样，不再查 DB
def _select_insight_samples(analytics: dict, snapshot: dict) -> list[dict]:
    reviews = snapshot.get("reviews", [])
    samples = []
    seen_ids = set()

    def _add(r):
        rid = r.get("id")
        if rid and rid not in seen_ids:
            seen_ids.add(rid)
            samples.append(r)

    # 1. 风险产品差评（从 snapshot reviews 中按 SKU + rating 排序）
    risk_skus = [rp["product_sku"]
                 for rp in analytics.get("self", {}).get("risk_products", [])[:3]]
    for sku in risk_skus:
        sku_neg = sorted(
            [r for r in reviews
             if r.get("product_sku") == sku
             and (r.get("rating") or 5) <= config.NEGATIVE_THRESHOLD],
            key=lambda r: r.get("rating") or 5)
        for r in sku_neg[:2]:
            _add(r)

    # 2. 带图差评
    img_neg = [r for r in reviews
               if r.get("ownership") == "own"
               and r.get("images")
               and (r.get("rating") or 5) <= config.NEGATIVE_THRESHOLD]
    for r in sorted(img_neg, key=lambda r: r.get("rating") or 5)[:3]:
        _add(r)

    # 3. 竞品好评
    comp_pos = [r for r in reviews
                if r.get("ownership") == "competitor"
                and (r.get("rating") or 0) >= 5]
    for r in sorted(comp_pos, key=lambda r: r.get("scraped_at") or "", reverse=True)[:3]:
        _add(r)

    # 4. 混合情感
    mixed = [r for r in reviews if r.get("sentiment") == "mixed"]
    for r in mixed[:2]:
        _add(r)

    # 5. 最近发表
    recent = sorted(reviews,
                    key=lambda r: r.get("date_published_parsed") or "", reverse=True)
    for r in recent[:2]:
        _add(r)

    return samples
```

**同时修改** `_build_insights_prompt()` 中的兜底逻辑：当 snapshot 中评论极少（<3 条）时，明确告诉 LLM "本期新增评论仅 N 条，请仅基于这些数据生成分析，不要推测或扩展"。

```python
# _build_insights_prompt() 中追加：
if kpis.get("ingested_review_rows", 0) < 5:
    prompt += "\n\n⚠️ 重要：本期新增评论仅 {n} 条，样本极少。"
    prompt += "请仅基于上述数据做事实性记录，禁止做趋势推断或问题严重度判定。"
    prompt += "hero_headline 应体现'样本不足'。"
```

**验证方法**

1. 用 Run-3 的快照数据重新生成报告 → LLM 输出不应引用 snapshot 以外的评论
2. 对比 LLM 文本中的数字与 KPI 卡片数字 → 应一致
3. 当评论数 < 5 时，hero_headline 应包含"样本不足"或类似措辞

---

### Fix-3（P1）：健康指数增加样本量修正

**问题根因**

`report_common.py` 的 `compute_health_index()` 对 `own_reviews >= 1` 不做样本量修正。1 条 5 星评论 → NPS=100 → Health=100.0。

**修改方案**

文件：`qbu_crawler/server/report_common.py`

```python
# 修改 compute_health_index() 的返回值为 tuple
def compute_health_index(analytics: dict) -> tuple[float, str]:
    """
    返回 (health_index, confidence)
    confidence: "high" (>=30 reviews), "medium" (5-29), "low" (<5), "no_data" (0)
    """
    kpis = analytics.get("kpis", analytics)
    own_reviews = kpis.get("own_review_rows", 0)

    if own_reviews == 0:
        return 50.0, "no_data"

    promoters = kpis.get("own_positive_review_rows", 0)
    detractors = kpis.get("own_negative_review_rows", 0)
    raw_nps = ((promoters - detractors) / own_reviews) * 100
    raw_health = (raw_nps + 100) / 2

    # 贝叶斯收缩：样本不足时向先验值（50.0）收缩
    MIN_RELIABLE = 30
    PRIOR = 50.0
    if own_reviews < MIN_RELIABLE:
        weight = own_reviews / MIN_RELIABLE
        health = weight * raw_health + (1 - weight) * PRIOR
        confidence = "low" if own_reviews < 5 else "medium"
    else:
        health = raw_health
        confidence = "high"

    return round(max(0.0, min(100.0, health)), 1), confidence
```

**模板改动**

文件：`report_templates/email_full.html.j2`

```html
<!-- Hero 区块增加置信度视觉反馈 -->
<div class="hero" style="background: {{ '#dc2626' if alert_level == 'red'
    else '#a16207' if alert_level == 'yellow'
    else '#9ca3af' if health_confidence in ('low', 'no_data')
    else '#16a34a' }};">
  {{ analytics.kpis.health_index }}
  {% if health_confidence == 'low' %}
    <div style="font-size:12px; opacity:0.8;">⚠ 样本仅 {{ analytics.kpis.own_review_rows }} 条，置信度低</div>
  {% elif health_confidence == 'medium' %}
    <div style="font-size:12px; opacity:0.8;">样本量 {{ analytics.kpis.own_review_rows }} 条</div>
  {% endif %}
</div>
```

**调用方改动**

所有调用 `compute_health_index()` 的地方需要解包 tuple：
- `normalize_deep_report_analytics()` 中
- `_compute_alert_level()` 中
- 模板渲染时传入 `health_confidence`

**验证方法**

| 场景 | own_reviews | raw_health | 修正后 health | confidence |
|------|------------|-----------|--------------|------------|
| Run-3（1 条好评） | 1 | 100.0 | 51.7 | low |
| 5 条全好评 | 5 | 100.0 | 58.3 | medium |
| Run-1（1610 条） | 1610 | 95.0 | 95.0 | high |
| 0 条评论 | 0 | N/A | 50.0 | no_data |

---

### Fix-4（P1）：激活 KPI Delta 计算

**问题根因**

`report_common.py` 的 `_compute_kpi_deltas()` 已完整实现但从未被调用。Delta 字段（`*_delta`, `*_delta_display`）在模板中被引用但永远为空。

**修改方案**

文件：`qbu_crawler/server/report_analytics.py`

```python
# 在 build_report_analytics() 末尾（return 之前）追加：
from .report_snapshot import load_previous_report_context
from .report_common import _compute_kpi_deltas

# ... 已有的 analytics 构建逻辑 ...

# 新增：计算 KPI delta
if mode_info["mode"] != "baseline":
    prev_analytics, _ = load_previous_report_context(run_id)
    if prev_analytics and prev_analytics.get("kpis"):
        deltas = _compute_kpi_deltas(analytics["kpis"], prev_analytics["kpis"])
        analytics["kpis"].update(deltas)
```

**需确认**：`_compute_kpi_deltas()` 的实现是否正确：
- delta = current - previous
- delta_display = "+N" / "-N" / "—"
- 需要检查是否处理了 None/缺失字段的情况

**注意事项**：
- 在方案 2（双视角）之前，delta 是"当日窗口 vs 上次窗口"，值可能很大（如 1610→2）
- 在方案 2 之后，delta 变为"当日累积 vs 昨日累积"，值合理（如 2579→2581）
- 方案 1 阶段可在 delta_display 后标注口径："较上次报告"

**验证方法**

1. 生成增量报告（非 baseline）→ KPI 卡片应显示 delta 箭头和数值
2. baseline 模式 → delta 应显示为 "---"（现有逻辑不变）
3. 检查 delta 正负方向是否正确（差评增加=红色↑，健康指数下降=红色↓）

---

### Fix-5（P1）：修复基线模式退出条件

**问题根因**

`report_analytics.py` 的 `detect_report_mode()` SQL 要求 `analytics_path IS NOT NULL AND analytics_path != ''`。quiet/skipped run 没有 analytics_path → 不计入 3 次阈值 → 系统可能长期停留在 baseline。

**修改方案**

文件：`qbu_crawler/server/report_analytics.py`

```python
# 方案 A（推荐）：放宽条件，所有完成的 daily run 都计入
# detect_report_mode() 中的 SQL：

sql = """
    SELECT id, logical_date
    FROM workflow_runs
    WHERE workflow_type = 'daily'
      AND status = 'completed'
      AND logical_date >= ?
      AND logical_date < ?
      AND id != ?
    ORDER BY logical_date ASC, id ASC
"""
# 移除 AND analytics_path IS NOT NULL AND analytics_path != ''

# 方案 B（保守）：首次有 analytics 的 run 完成后，后续一律 incremental
# 查询是否存在任意一次有 analytics 的已完成 run
sql_any_full = """
    SELECT COUNT(*) FROM workflow_runs
    WHERE workflow_type = 'daily' AND status = 'completed'
      AND analytics_path IS NOT NULL AND analytics_path != ''
      AND id != ?
"""
# 如果 count >= 1 → incremental；count == 0 → baseline
```

推荐方案 A，因为逻辑更简单且符合语义："系统已经稳定运行 3 天以上"。

**验证方法**

1. 在有 1 次 full run + 2 次 quiet/skipped run 后 → 第 4 次应为 incremental
2. 检查 analytics JSON 中的 mode 字段

---

### Fix-6（P1）：竞品差距指数增加最小样本量保护

**问题根因**

`report_common.py` 中 `compute_competitive_gap_index()` 不检查样本量。1 条评论的标签分布被放大到 0-100 的指数。

**修改方案**

文件：`qbu_crawler/server/report_common.py`

```python
def compute_competitive_gap_index(analytics: dict) -> float | None:
    """返回 0-100 的差距指数，样本不足时返回 None"""
    kpis = analytics.get("kpis", analytics)
    total = kpis.get("own_review_rows", 0) + kpis.get("competitor_review_rows", 0)

    MIN_GAP_SAMPLE = 20  # 最少需要 20 条评论才计算差距指数
    if total < MIN_GAP_SAMPLE:
        return None

    # ... 现有计算逻辑 ...
```

**模板改动**

所有引用 `competitive_gap_index` 的模板：

```html
{% if analytics.kpis.competitive_gap_index is not none %}
  {{ analytics.kpis.competitive_gap_index }}
{% else %}
  <span style="color:#9ca3af;">—</span>
  <span style="font-size:10px;">样本不足</span>
{% endif %}
```

**验证方法**

1. Run-3（total=2）→ 差距指数显示 "—"
2. Run-1（total=2577）→ 差距指数显示 5

---

### Fix-7（P2）：统一邮件收件人来源

**问题根因**

| 模式 | 收件人来源 | 代码位置 |
|------|----------|---------|
| full | `config.EMAIL_RECIPIENTS` | report_snapshot.py:762 |
| change/quiet | `openclaw/.../email_recipients.txt` | report_snapshot.py:482-485 |

**修改方案**

文件：`qbu_crawler/server/report_snapshot.py`

```python
def _get_email_recipients() -> list[str]:
    """统一获取邮件收件人，优先环境变量，fallback 到文件"""
    if config.EMAIL_RECIPIENTS:
        return config.EMAIL_RECIPIENTS

    txt_path = Path(__file__).parent / "openclaw" / "workspace" / "config" / "email_recipients.txt"
    if txt_path.exists():
        return [line.strip() for line in txt_path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.startswith("#")]
    return []
```

将 full/change/quiet 三处发邮件的代码统一调用 `_get_email_recipients()`。

**验证方法**

1. 设置 `EMAIL_RECIPIENTS` 环境变量 → 三种模式都发给同一收件人列表
2. 清空环境变量，写入 txt 文件 → 三种模式 fallback 到文件

---

## 执行顺序

```
Fix-1 (激活 change/quiet) ─── 影响最大，先做
  ↓
Fix-2 (LLM 数据统一)     ─── 消除核心矛盾
  ↓
Fix-3 (健康指数修正)      ─── 与 Fix-2 协同
Fix-4 (KPI delta)        ─── 可与 Fix-3 并行
Fix-5 (基线退出)          ─── 可与 Fix-3 并行
Fix-6 (差距指数保护)      ─── 可与 Fix-3 并行
  ↓
Fix-7 (收件人统一)        ─── 最后做，验证 change/quiet 邮件
```

## 测试计划

1. **单元测试**：为 `compute_health_index()`、`compute_competitive_gap_index()`、`_compute_kpi_deltas()` 写参数化测试
2. **集成测试**：用生产 DB 的副本（`data/reports/data/products.db`），模拟 3 种报告模式：
   - 有新评论 → full 模式 → 验证健康指数、delta、LLM 文本
   - 无新评论但价格变动 → change 模式 → 验证变动邮件
   - 无任何变化 → quiet 模式 → 验证静默邮件
3. **回归测试**：确认现有的 full 模式报告输出不因修改而退化

---

## 审查修正（2026-04-15 代码对齐审查）

对照实际代码逐项核实后，发现以下**必须修正**的问题和遗漏：

### Fix-1 审查修正

#### 修正 1A（严重）：`_should_send_workflow_email()` 会阻止 change/quiet 邮件发送

`workflows.py` 中 `_should_send_workflow_email()`（约 line 823-829）在 `reviews_count == 0` 时返回 `False`，导致 `generate_report_from_snapshot(snapshot, send_email=False)` 被调用——change/quiet 的邮件**永远不会发送**。

**必须同步修改**：

```python
def _should_send_workflow_email(task_rows, snapshot):
    # 改为：只要走到这里就允许发邮件，具体是否发送由
    # generate_report_from_snapshot 内部决定
    # （quiet 模式有自己的 should_send_quiet_email() 频率控制）
    return True
```

或更精细：检查是否有 snapshot changes，有则发邮件：

```python
def _should_send_workflow_email(task_rows, snapshot):
    reviews_saved = _workflow_reviews_saved(task_rows)
    if reviews_saved is not None and reviews_saved > 0:
        return True  # 有新评论 → 发
    # 0 评论时也返回 True，让下游决定
    return True
```

#### 修正 1B（中等）：DingTalk 通知模板对 change/quiet 模式显示不正确

`workflow_full_report` 通知模板中 `{excel_path}` 在 change/quiet 模式下为 `None`，会渲染为 `"附件：None"`。

**方案**：在 `_template_vars_for()` 中根据 `report_mode` 做条件处理：

```python
# notifier.py _template_vars_for()
if payload.get("report_mode") in ("change", "quiet"):
    vars["excel_path"] = "（无 Excel 附件）"
```

或者增加 `workflow_change_report` / `workflow_quiet_report` 通知模板。

#### 修正 1C（低）：change/quiet 返回值缺少 `snapshot_hash` 字段

`_generate_change_report()` 和 `_generate_quiet_report()` 的返回 dict 不含 `snapshot_hash`。通知 payload 的 `full_report.get("snapshot_hash", "")` 虽不会崩溃但为空字符串。

**方案**：在返回 dict 中补充 `"snapshot_hash": snapshot.get("snapshot_hash", "")`。

---

### Fix-2 审查修正

#### 修正 2A（中等）：参数顺序写反

计划中写的签名 `_select_insight_samples(analytics, snapshot)` 与实际代码 `_select_insight_samples(snapshot, analytics)` **参数顺序相反**。执行时必须按实际代码的顺序 `(snapshot, analytics)`。

#### 修正 2B（低）：DB 查询实际是 3 次而非 5 次

计划说"5 次 DB 查询"，实际是 3 次 DB 查询（风险产品差评、带图差评、竞品好评）+ 2 次 snapshot 内存过滤（混合情感、最近发表）。修正描述，不影响改动方案。

---

### Fix-3 审查修正

#### 修正 3A（严重）：返回 tuple 会破坏所有下游消费者

计划改 `compute_health_index()` 返回 `tuple[float, str]`，但唯一调用方在 `normalize_deep_report_analytics()` 中直接赋值给 `kpis["health_index"]`。如果存入 tuple，会导致：
- 7+ 个模板渲染出 `(95.0, 'high')` 而非 `95.0`
- `_compute_alert_level()` 中 `health < config.HEALTH_RED` 抛出 `TypeError`
- `_compute_kpi_deltas()` 中 `curr - prev` 对 tuple 抛出 `TypeError`
- `report_charts.py` 中仪表盘数值错误
- `report_llm.py` 的 prompt 中出现 tuple 文本

**正确做法**：在调用方解包，分别存储：

```python
# normalize_deep_report_analytics() 中
health, confidence = compute_health_index(normalized)
normalized["kpis"]["health_index"] = health
normalized["kpis"]["health_confidence"] = confidence
```

所有模板继续用 `health_index`（float），新增 `health_confidence` 字段用于条件渲染。

#### 修正 3B（中等）：模板改动范围不止 email_full.html.j2

需要处理 `health_confidence` 的模板清单（至少需检查 hero/仪表盘区域）：
1. `email_full.html.j2`（hero 区）
2. `daily_report_v3.html.j2`（仪表盘 + 已有 `own_review_rows < 5` 警告）
3. `email_quiet.html.j2`（KPI 卡片区）
4. `email_change.html.j2`（KPI 卡片区）
5. `quiet_day_report.html.j2`（KPI 卡片区）
6. `daily_report_email.html.j2`（legacy 的 hero 区）

对于 quiet/change 模板：它们使用的是 `previous_analytics` 中的健康指数，该值已经是 float，无需改动。只需在 full 模式和 V3 报告中处理 confidence。

---

### Fix-4 审查修正

#### 修正 4A（严重）：`_compute_kpi_deltas` 第二个参数类型错误

计划写：
```python
deltas = _compute_kpi_deltas(analytics["kpis"], prev_analytics["kpis"])
```

但 `_compute_kpi_deltas` 内部实现是：
```python
def _compute_kpi_deltas(current_kpis, prev_analytics):
    prev_kpis = prev_analytics.get("kpis", {})  # ← 期望传入完整 analytics dict
```

传入 `prev_analytics["kpis"]` 会导致 `prev_kpis = {}`（在 kpis dict 中找 "kpis" key 必然失败），所有 delta = current 值。

**正确调用**：
```python
deltas = _compute_kpi_deltas(analytics["kpis"], prev_analytics)  # 传完整 dict
```

#### 修正 4B（严重）：`run_id` 变量未定义

`build_report_analytics()` 中没有 `run_id` 局部变量。应使用：
```python
run_id = snapshot.get("run_id", 0)
```

#### 修正 4C（严重）：循环导入

`report_analytics.py` 不能在模块顶层 `from .report_snapshot import load_previous_report_context`，因为 `report_snapshot` 已在顶层导入了 `report_analytics`。

**必须使用函数内懒导入**：
```python
def build_report_analytics(snapshot, synced_labels=None):
    ...
    # 在函数末尾（非模块顶层）
    if mode_info["mode"] != "baseline":
        from .report_snapshot import load_previous_report_context  # 懒导入
        run_id = snapshot.get("run_id", 0)
        prev_analytics, _ = load_previous_report_context(run_id)
        if prev_analytics:
            deltas = _compute_kpi_deltas(analytics["kpis"], prev_analytics)
            analytics["kpis"].update(deltas)
```

#### 修正 4D（低）：`competitive_gap_index` 不在 delta 计算列表中

`_compute_kpi_deltas` 的 delta key 列表不含 `competitive_gap_index`，但模板引用了 `competitive_gap_index_delta_display`。可接受（显示为空），但记录为已知限制。

---

### Fix-6 审查修正

#### 修正 6A（严重）：函数签名与实际不符

计划改签名为 `compute_competitive_gap_index(analytics: dict)`，但实际签名是 `compute_competitive_gap_index(gap_analysis: list[dict])`，参数是 gap 分析列表而非完整 analytics dict。

**正确做法**：保持原签名，在调用方做样本量检查：

```python
# normalize_deep_report_analytics() 中（调用方）
total = (normalized.get("kpis", {}).get("own_review_rows", 0)
         + normalized.get("kpis", {}).get("competitor_review_rows", 0))

if total < 20:
    normalized["kpis"]["competitive_gap_index"] = None
else:
    normalized["kpis"]["competitive_gap_index"] = compute_competitive_gap_index(
        normalized.get("competitor", {}).get("gap_analysis") or [])
```

这样不改 `compute_competitive_gap_index` 的签名，不破坏现有测试。

#### 修正 6B（中等）：模板中 None 值的渲染

多数模板用 `_kpis.get("competitive_gap_index", "---")`，当 dict 中存了 `None` 时 `.get()` 返回 `None`（不触发默认值），模板会渲染文字 `"None"`。

**正确做法**：模板中用 Jinja2 的 `| default("—", true)` 或 `{% if val is not none %}`：

```html
{{ _kpis.get("competitive_gap_index") | default("—", true) }}
```

需检查并修改**所有引用该字段的模板**（至少 5 个）。
