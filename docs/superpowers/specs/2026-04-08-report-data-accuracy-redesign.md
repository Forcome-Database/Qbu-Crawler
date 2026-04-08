# 报告数据准确性与指标体系改进设计

**日期**: 2026-04-08
**状态**: 待实施
**范围**: 报告管线全链路（数据层 → 计算层 → 展示层）
**改动级别**: 适度 — 可新增字段/扩展 JSON，不破坏已有字段语义和 API 接口

---

## 1. 背景与问题概述

基于对 workflow-run-1 全量报告产物（HTML/Excel/PDF/JSON）和核心代码的深入分析，发现 9 类问题：

- **数据正确性**：first_seen/last_seen 日期排序错误、Feature Cluster 过度碎片化（100+ 聚类，max count=2）、历史补采提示被截断
- **指标准确性**：采集覆盖率不可见（站点 223 条 vs 入库 148 条）、3 套「负面」定义混用、雷达图退化为二值、相对日期时间漂移
- **增益功能**：趋势数据空置、增量零评论场景无处理、热力图/图片下载/预警级别等呈现问题

## 2. 实施策略

**方案 B — 按优先级分 3 期**：

| 期 | 优先级 | 目标 | 交付物 |
|----|--------|------|--------|
| P0 | 数据正确性 | 报告内容不再错误 | 聚类归并、日期排序、补采提示 |
| P1 | 指标准确性 | 指标可信可解释 | 标签统一、覆盖率、口径标注、雷达图、日期固化 |
| P2 | 增益功能 | 报告更完整有用 | 趋势数据、零评论、热力图、图片并行、预警修正 |

---

## 3. P0 — 数据正确性修复

### 3.1 first_seen/last_seen 日期排序修复

**问题**：`report_analytics.py:569-570` 和 `785-786` 对 `date_published` 字符串做 `min()`/`max()`，字典序比较导致时间逆序（`"2 years ago" < "5 years ago"` 但时间上 5 年前更早）。

**方案**：新增排序辅助函数，使用 `_parse_date_flexible` 解析后排序：

```python
def _date_sort_key(date_str):
    parsed = _parse_date_flexible(date_str)
    return parsed or date(1970, 1, 1)
```

两处 `min(dates)` / `max(dates)` 改为：
```python
sorted_dates = sorted(dates, key=_date_sort_key)
item["first_seen"] = sorted_dates[0] if sorted_dates else None
item["last_seen"] = sorted_dates[-1] if sorted_dates else None
```

注意：`sorted()` 的 key 参数仅用于排序，返回值仍为原始日期字符串。存储值保持可读性，排序正确性由 parse 保证。

**P0/P1 交互说明**：P0 在运行时解析排序（快速修复），P1 的日期固化（4.5）将从根本上消除相对日期问题。两者不冲突 — P1 完成后，dates 列表自然变为 ISO 字符串，字典序排序和日期序排序一致，P0 的 `_date_sort_key` 变为无害的恒等操作。

**涉及文件**：`report_analytics.py`（2 处：`_cluster_summary_items` 第 569-570 行、`_build_feature_clusters` 第 785-786 行）
**影响面**：仅改排序逻辑，输出字段和格式不变

### 3.2 Feature Cluster 聚类归并

**问题**：`_build_feature_clusters` 用 LLM 生成的中文 feature 字符串（`analysis_features`）做聚类键，产生 100+ 碎片聚类（绝大多数 count=1）。相关问题被离散化，严重低估实际规模。

**方案**：增加基于 `analysis_labels[].code` 的二级归并：

1. 仍然按 feature_string 收集原始数据
2. 新增归并步骤：每个 feature 对应 review 的 `analysis_labels` 中取主 label_code（polarity 匹配 + 最高 confidence）
3. 相同 label_code 的 features 合并为一个 cluster
4. cluster 的 `label_display` 使用标准中文名（如 "质量稳定性"）
5. 新增 `sub_features: [{feature: str, count: int}]` 字段保留原始细粒度

**归并前后对比**：

| 归并前 | 归并后 |
|--------|--------|
| 100+ clusters, max count=2 | ~8 clusters |
| "使用寿命短"(2)、"寿命太短(1年)"(1)、"第二天即坏"(1)... 散落 | quality_stability: count≈40, sub_features 列表 |

**Fallback**：feature 的 review 无匹配 polarity 的 label → 归入 `_uncategorized` 分组

**涉及文件**：`report_analytics.py`（`_build_feature_clusters` 函数）
**向后兼容**：cluster 输出结构不变（label_code, review_count, severity 等保留），`sub_features` 是增量字段，现有模板无需修改即可工作

### 3.3 历史补采提示截断修复

**问题**：`_humanize_bullets` 生成最多 4 条 bullets，`return bullets[:3]` 截断后第 4 条补采提示永远不显示。本次报告 148 条评论中 140 条是历史补采，读者完全不知情。

**方案**：将补采检测从函数末尾（第 376-382 行）移到函数开头，作为第 1 条 bullet 插入。具体操作：

1. 删除 `_humanize_bullets` 末尾的补采检测块（第 376-382 行）
2. 在函数开头、Bullet 1 之前插入补采检测：

```python
def _humanize_bullets(normalized):
    bullets = []
    kpis = normalized.get("kpis", {})
    # Backfill disclosure: MUST be first bullet to survive [:3] truncation
    recently_published = kpis.get("recently_published_count", 0)
    ingested = kpis.get("ingested_review_rows", 0)
    if ingested > 0 and recently_published < ingested * 0.5:
        backfill_count = ingested - recently_published
        bullets.append(
            f"注：本期 {ingested} 条评论中有 {backfill_count} 条为历史补采"
            f"（发布于 30 天前），数据含历史积累"
        )
    # Bullet: highest-risk product (existing logic unchanged)
    top = ...
    # return bullets[:3] unchanged
```

截断后保留：补采提示 + 2 条分析要点（或无补采时 3 条分析要点）。

**行为变更注意**：补采提示插入后，邮件/钉钉通知中 bullets[0] 可能从"风险产品摘要"变为"补采声明"。下游消费者不应按位置解析 bullets 语义，但如有此类逻辑需同步调整。

**涉及文件**：`report_common.py`（`_humanize_bullets` 函数，第 331-383 行）

---

## 4. P1 — 指标准确性增强

### 4.1 标签源统一

**问题**：当前两套标签系统并行 — 规则引擎（85 条标签，57% 评论零标签）用于图表/风险评分，LLM（274 条标签，99% 评论覆盖）用于聚类。同一报告内两套数据源导致自相矛盾。

**方案**：LLM `analysis_labels` 作为主源，规则引擎作为 fallback，统一写入 `review_issue_labels` 表。

**统一流程**：
```
review_analysis.labels (LLM)
    ↓ 校验：code 白名单（14 个）+ 极性白名单 + cap 3/review（按 confidence 降序）
    ↓ 通过 → review_issue_labels (source="llm")
    ↓ 不通过或无 LLM 数据 → classify_review_labels(规则) → review_issue_labels (source="rule")
    ↓
_build_labeled_reviews (统一读取 review_issue_labels)
    ↓
全链路：雷达图、热力图、风险评分、问题聚类
```

**极性白名单规则**：
- 负面专属 code（quality_stability, structure_design, assembly_installation, material_finish, cleaning_maintenance, noise_power, packaging_shipping）：仅接受 polarity=negative
- 正面专属 code（easy_to_use, solid_build, good_value, easy_to_clean, strong_performance, good_packaging）：仅接受 polarity=positive
- 双极性 code：service_fulfillment — 允许 negative 和 positive

**Per-review cap**：每条评论最多 3 个标签（不区分极性），按 confidence 降序取 top 3。防止长评论权重过大。Cap 在写入 `review_issue_labels` 前执行。

**`sync_review_labels` 改动细节**：

现有函数签名 `sync_review_labels(snapshot)` 不变。snapshot 中每条 review 已包含 `analysis_labels` 字段（由 `freeze_report_snapshot` → `get_reviews_with_analysis` 预连接）。改动 `sync_review_labels` 内部循环：

```python
def sync_review_labels(snapshot):
    all_labels = {}
    for review in snapshot.get("reviews") or []:
        review_id = _review_id(review)
        if not review_id:
            continue

        # Step 1: Try LLM labels from snapshot (pre-joined from review_analysis)
        llm_labels = _extract_validated_llm_labels(review)

        if llm_labels:
            # Step 2: Cap at 3, sorted by confidence desc
            llm_labels.sort(key=lambda l: -l.get("confidence", 0))
            labels = llm_labels[:3]
            for l in labels:
                l["source"] = "llm"
        else:
            # Step 3: Fallback to rule-based
            labels = classify_review_labels(review)

        models.replace_review_issue_labels(review_id, labels)
        all_labels[review_id] = labels

    return all_labels
```

新增辅助函数 `_extract_validated_llm_labels(review)`：
1. 从 `review.get("analysis_labels")` 解析 JSON（若为字符串）
2. 逐条校验 code 在 14 个规范 code 内
3. 逐条校验极性符合白名单（负面 code 只接受 negative，正面 code 只接受 positive，service_fulfillment 接受双极性）
4. 丢弃不合规标签，返回合规列表

**现有 `hybrid` 模式处理**：`REPORT_LABEL_MODE == "hybrid"` 分支（第 466-476 行）保留但不再生效 — 因为 LLM 标签已在 Step 1 优先使用，`_maybe_normalize_labels_with_llm` 仍为空函数。如果未来实现 hybrid 二次校准，该分支可复用。

**改动点**：
- `report_analytics.py`：重写 `sync_review_labels` 循环体，新增 `_extract_validated_llm_labels` 函数
- `review_issue_labels` 表：无 schema 变更，`source` 字段已存在，值从 "rule" 扩展为 "rule" | "llm"
- 下游代码（`_build_labeled_reviews`、`_compute_chart_data`、`_risk_products`）：零改动 — 它们从 `review_issue_labels` 读，不感知 source

### 4.2 采集覆盖率展示

**问题**：站点显示 223 条总评论，实际入库 148 条（覆盖率 66%），但报告中无任何展示。读者可能误以为差评率基于全量数据。

**方案**：

**a) 全局 KPI 卡片**：在 `kpi_cards` 列表中新增第 6 张：

公式：`coverage_rate = ingested_review_rows / max(site_reported_review_total_current, 1)`

其中 `site_reported_review_total_current` = 所有产品（自有+竞品）的 `product.review_count` 之和，`ingested_review_rows` = 实际入库评论行数。

```python
{
    "label": "样本覆盖率",
    "value": f"{coverage_rate:.0%}",  # 66%
    "tooltip": "实际入库评论数 ÷ 站点展示总评论数。受 MAX_REVIEWS 上限和翻页限制影响，部分产品覆盖率 <100% 属正常",
}
```

**b) 产品级覆盖率**：`risk_products` 每个条目新增 `coverage_rate` 字段 = 该产品入库评论数 / 该产品 `review_count`。Product Scorecard sheet 新增一列。`coverage_rate < 50%` 时标黄提醒。

**c) 差评率注脚**：差评率 tooltip 追加 `"（基于 {coverage_rate:.0%} 的采样）"`。

**涉及文件**：`report_common.py`（KPI 卡片构建）、`report_analytics.py`（`_risk_products` 增加 coverage 字段）

### 4.3 指标口径标注

**问题**：3 套「负面」定义混用（rating≤2 / LLM sentiment / rating≤3），读者无法理解指标间差异。

**方案**：不合并定义（它们服务于不同目的），在报告中明确标注口径：

| 指标 | 标注方式 |
|------|---------|
| KPI 差评率 | tooltip: "≤2星评论 ÷ 自有评论总数"（已有，保持） |
| 情感分布图 | 图表标题改为「评分分布」，图例改为「好评(≥4星)/中评(3星)/差评(≤2星)」 |
| 问题聚类 | 区域标题旁增加注脚：「基于 AI 语义分析，包含差评和中性偏负面评论」 |
| 风险评分 | tooltip 标注 "计入 ≤3星评论" |

**涉及文件**：`report_common.py`（METRIC_TOOLTIPS 扩展）、HTML 模板（图表标题修正）

### 4.4 雷达图修复

**问题**：正面和负面标签是独立 code，每个维度只有单一极性，ratio 坍缩为 0/1 二值。实际数据确认自有和竞品雷达完全重叠 `[1.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0]`。

**方案**：

**a) 5 个统一维度**：

| # | 维度 | 负面 code | 正面 code |
|---|------|-----------|-----------|
| 1 | 耐久性与质量 | quality_stability + material_finish | solid_build |
| 2 | 设计与使用 | structure_design + assembly_installation | easy_to_use |
| 3 | 清洁便利性 | cleaning_maintenance | easy_to_clean |
| 4 | 性能表现 | noise_power | strong_performance |
| 5 | 售后与履约 | service_fulfillment(neg) | service_fulfillment(pos) |

排除 good_value（无自然负面对应，且"性价比"是综合判断非独立可改善属性）和 packaging_shipping/good_packaging（总数据仅 8 条）。

**b) 按评论计数而非标签计数**：每条评论在每个维度最多贡献 1 次，防止长评论多标签权重放大。

**极性冲突解决策略**：同一评论可能在同一统一维度内同时拥有正面标签（如 `solid_build/positive`）和负面标签（如 `quality_stability/negative`）。解决规则：**负面优先（悲观策略）** — 只要该维度有任一负面标签，该评论在该维度计为负面。理由：报告服务于品控决策，漏报风险的代价大于误报。

```python
for item in labeled_reviews:
    ownership = item["review"].get("ownership")
    # Phase 1: Determine per-dimension polarity for this review
    dim_polarity = {}  # dim -> "positive" | "negative"
    for label in item["labels"]:
        dim = CODE_TO_DIMENSION.get(label["label_code"])
        if not dim:
            continue
        if dim not in dim_polarity:
            dim_polarity[dim] = label["label_polarity"]
        elif label["label_polarity"] == "negative":
            dim_polarity[dim] = "negative"  # negative wins

    # Phase 2: Count once per dimension
    for dim, polarity in dim_polarity.items():
        dim_total[ownership][dim] += 1
        if polarity == "positive":
            dim_pos[ownership][dim] += 1
```

**c) 净正面率**：`score = dim_pos / max(dim_total, 1)`，即 `positive_reviews / (positive_reviews + negative_reviews)`

**涉及文件**：`report_analytics.py`（`_compute_chart_data` 雷达部分，约 30 行替换）

### 4.5 快照阶段固化相对日期

**问题**：`date_published` 存储原始字符串（"3 months ago"），`_parse_date_flexible` 每次以 `date.today()` 解析，快照数据不可复现。

**方案**：

**a) reviews 表新增字段**：
```sql
ALTER TABLE reviews ADD COLUMN date_published_parsed TEXT;
```

**写入时机**：在 `models.save_reviews()` 中，每条评论入库时立即解析 `date_published` 并写入 `date_published_parsed`（ISO 格式如 "2026-01-08"）。对于相对日期（"3 months ago"），以入库时的 `scraped_at` 作为锚定时间（而非 `date.today()`），确保解析结果准确反映评论发布时间。

**历史数据回填**：在 `models.py` 的 `init_db()` 中增加一次性迁移逻辑：
```python
# Backfill date_published_parsed for existing reviews
rows = conn.execute("SELECT id, date_published, scraped_at FROM reviews WHERE date_published_parsed IS NULL").fetchall()
for row in rows:
    anchor = datetime.fromisoformat(row["scraped_at"]).date() if row["scraped_at"] else date.today()
    parsed = _parse_date_flexible(row["date_published"], anchor_date=anchor)
    if parsed:
        conn.execute("UPDATE reviews SET date_published_parsed = ? WHERE id = ?", (parsed.isoformat(), row["id"]))
```

这要求 `_parse_date_flexible` 增加可选参数 `anchor_date`（默认 `date.today()`），相对日期解析以 `anchor_date` 为基准而非当天。

**b) 快照固化**：`freeze_report_snapshot` 时每条 review 增加 `date_published_parsed` 字段。优先从数据库取，数据库无值时以 snapshot 生成时间为锚点运行时解析并回写。

**c) 全链路使用 parsed 日期**：
- `_build_feature_clusters` / `_cluster_summary_items` 的 dates 列表改用 `date_published_parsed`
- `recently_published_count` 计算改用 parsed 日期
- `_duration_display` 改用 parsed 日期

**向后兼容**：`date_published` 原始字段保留。现有快照 JSON 无 `date_published_parsed` 字段时，fallback 到 `_parse_date_flexible(date_published)`。

**涉及文件**：`models.py`（ALTER TABLE + 写入/回填逻辑）、`report_common.py`（`_parse_date_flexible` 增加 `anchor_date` 参数、`_duration_display` 适配）、`report_snapshot.py`（固化逻辑）、`report_analytics.py`（读取逻辑）

---

## 5. P2 — 增益功能

### 5.1 产品快照趋势数据

**问题**：`product_snapshots` 表有数据但报告未使用，Excel Trend Data sheet 显示 "数据积累中"。

**方案**：`build_report_analytics` 中新增 `_build_trend_data` 函数，从 `product_snapshots` 查询最近 30 天历史，构建趋势序列。输出到 analytics JSON 的 `_trend_data` 字段。

**展示内容**：价格变动、评分趋势、评论增速、库存状态变化。

**边界**：首次 run 仅 1 个快照点时不画趋势线，显示积累提示。

**涉及文件**：`report_analytics.py`（新增函数）、`models.py`（查询方法）、`report.py`（Excel Trend sheet 渲染）

### 5.2 增量报告零评论场景

**问题**：增量采集无新评论时，所有指标为 0/空。

**方案**：零评论时切换为快照变更报告模式 — 对比当前与上期快照检测价格/库存/评分变化。有变化生成精简报告，无变化记录 `completed_no_change` 状态不发邮件。

**涉及文件**：`report_snapshot.py`（入口分支判断）

### 5.3 热力图改进

**问题**：z 值坍缩为 -1/0/1，y 轴标签截断。

**方案**：

- 改为按评论计数（与雷达图一致），分母为该产品总评论数，产生连续值
- y 轴标签动态截取：去掉品牌前缀（如 "Cabela's"），保留型号部分

**涉及文件**：`report_analytics.py`（`_compute_chart_data` 热力图部分）

### 5.4 图片下载并行化

**问题**：串行下载 40+ 张图片，极端情况 400+ 秒。

**方案**：`ThreadPoolExecutor(max_workers=5)` 并行下载，全局超时 60 秒，超时降级为 URL 文本。

**涉及文件**：`report.py`（图片嵌入部分）

### 5.5 附件图片证据扩展

**问题**：`appendix.image_reviews` 硬编码 `[:10]`，24 条含图评论丢弃 14 条。

**方案**：上限改为 20，按信息价值排序（负面 > 正面，自有 > 竞品，低分 > 高分）。

**涉及文件**：`report_analytics.py`（image_reviews 排序和截断）

### 5.6 邮件预警级别基线修正

**问题**：首次全量采集 50 条历史差评触发 red alert，虚假告警。

**方案**：`_compute_alert_level` 通过 `normalized.get("mode")` 检测 baseline（该字段由 `normalize_deep_report_analytics` 从 analytics 的 `mode` 字段传递，值为 `"baseline"` 或 `"incremental"`）。baseline 模式下跳过所有 red/yellow 判断：

```python
def _compute_alert_level(normalized):
    if normalized.get("mode") == "baseline":
        return "green", "首次基线采集完成，环比预警将在第 4 期后启用"
    # ... existing red/yellow/green logic unchanged
```

**涉及文件**：`report_common.py`（`_compute_alert_level`，第 244 行起）

---

## 6. 改动文件清单

| 文件 | P0 | P1 | P2 |
|------|:--:|:--:|:--:|
| `report_analytics.py` | 聚类归并、日期排序 | 标签统一(sync)、雷达图、日期读取 | 趋势数据、热力图、图片证据 |
| `report_common.py` | 补采提示 | KPI卡片、口径标注、雷达维度映射、`_parse_date_flexible` anchor 参数 | 预警基线修正 |
| `report_snapshot.py` | — | 日期固化 | 零评论分支 |
| `report.py` | — | — | 图片并行 |
| `models.py` | — | ALTER TABLE + 回填 (date_published_parsed) | 趋势查询 |
| HTML 模板 | — | 图表标题、注脚 | — |

## 7. 向后兼容保证

- `products` / `reviews` / `product_snapshots` 核心字段语义不变
- `review_issue_labels` 表结构不变，`source` 字段区分 "rule" / "llm"
- 快照 JSON 新增字段（`date_published_parsed`、`sub_features`、`coverage_rate`、`_trend_data`），旧快照缺失时 fallback
- analytics JSON 新增字段，已有字段含义不变
- API 接口签名不变
- workflow_runs schema 不变
- **行为变更**：P0 3.3 实施后，`_humanize_bullets` 返回的 bullets[0] 在首次全量采集时可能从"风险产品摘要"变为"历史补采声明"。下游消费者（邮件正文、钉钉通知）不应按位置解析 bullets 语义
