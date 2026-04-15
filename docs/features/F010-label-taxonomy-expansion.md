# F010 — 标签分类体系扩展

## 背景

当前标签体系（`_LABEL_TAXONOMY`）共 14 个标签，硬编码在 `translator.py:66-85`，随 LLM prompt 下发。710 条评论产出 1480 个标签，全部在 taxonomy 范围内，说明 LLM 遵守约束良好。

但存在两个结构性问题需要优化。

## 问题 1：正负面不对称

负面 8 个维度，正面仅 6 个，缺少对称覆盖。

| 负面标签 | 有无正面对应 | 实际正面误标数 |
|----------|-------------|---------------|
| quality_stability | 无 | — |
| structure_design | 无 | — |
| assembly_installation | 无 | 1 条 |
| material_finish | 无 | — |
| cleaning_maintenance | 无 | — |
| noise_power | 无 | **6 条** |
| packaging_shipping | 无 | 1 条 |
| service_fulfillment | 无 | **19 条** |

LLM 在正面评价无处可归时，会"借用"负面标签打正面极性，导致极性与 taxonomy 定义矛盾。`service_fulfillment`（售后好）和 `noise_power`（动力足）是高频场景。

**建议**：为缺失的正面维度补充标签，或将部分标签改为中性维度（同时允许正负极性）。

## 问题 2：缺少常见产品评论维度

当前产品线（绞肉机、灌肠机等肉类加工器具），以下高频话题缺少对应标签：

| 缺失维度 | 现实场景举例 | 目前被归到 |
|----------|-------------|-----------|
| 安全卫生 | 金属碎屑进食物、食品级材料担忧 | quality_stability（不精确） |
| 容量/尺寸 | 容量太小不够用、太大占空间 | structure_design（勉强） |
| 温度/效率 | 肉温升高影响品质、处理速度慢 | noise_power（不准确） |
| 外观/颜色 | 外观好看、颜色满意/不满意 | 无处可归 |
| 配件/附件 | 配件齐全、刀片种类多、缺少配件 | 无处可归 |

## 涉及改动范围

标签扩展不只是加几行 taxonomy，需要同步适配：

1. **`translator.py`** — `_LABEL_TAXONOMY` 扩展 + prompt 更新
2. **`report_common.py`** — `_LABEL_DISPLAY` 中文映射 + `CODE_TO_DIMENSION` 维度归类
3. **`report.py`** — `_LABEL_DISPLAY` import（Excel 已通过映射自动适配）
4. **`report_analytics.py`** — 聚类、gap analysis、heatmap 维度可能需要适配新标签
5. **`report_llm.py`** — insights prompt 中的标签引用
6. **已有数据兼容** — 旧评论的标签不会变，新标签只影响新入库评论

## 当前数据分布（710 条评论，2026-04-08 快照）

```
strong_performance  positive   460 条  ████████████████████████
solid_build         positive   273 条  ██████████████
easy_to_use         positive   182 条  █████████
good_value          positive   147 条  ███████
structure_design    negative    83 条  ████
easy_to_clean       positive    80 条  ████
quality_stability   negative    77 条  ████
service_fulfillment negative    56 条  ███
material_finish     negative    43 条  ██
good_packaging      positive    27 条  █
packaging_shipping  negative    24 条  █
assembly_installation negative  19 条  █
cleaning_maintenance negative   16 条  █
noise_power         negative     3 条  ▏
noise_power         positive     6 条  ▏ (极性矛盾)
service_fulfillment positive    19 条  █ (极性矛盾)
```

## 优先级

中等。当前体系可用，LLM 会用最接近的标签兜底，不会遗漏评论。但随着产品线扩展或评论量增长，标签精度会成为分析质量的瓶颈。
