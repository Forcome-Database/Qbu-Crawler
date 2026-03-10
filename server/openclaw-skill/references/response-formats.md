# 响应格式模板

本文档为每种工具返回定义标准的输出格式模板。Agent 在接收到工具返回的 JSON 数据后，必须按照以下模板转换为用户友好的 Markdown。

---

## 通用规则

### 数字格式化

| 数据类型 | 格式 | 示例 |
|---------|------|------|
| 价格 | `$X.XX` | $129.99 |
| 评分 | `X.X/5 ⭐` | 4.5/5 ⭐ |
| 百分比 | `XX.X%` | 75.2% |
| 数量 | 千分位分隔 | 3,842 |
| 日期 | `YYYY-MM-DD HH:MM` 或相对时间 | 2024-01-15 08:30 / 2 小时前 |

### 库存状态映射

| 原始值 | 显示 |
|--------|------|
| `in_stock` | ✅ 有货 |
| `out_of_stock` | ❌ 缺货 |
| `unknown` | ❓ 未知 |

### 任务状态映射

| 原始值 | 显示 |
|--------|------|
| `pending` | ⏳ 等待中 |
| `running` | 🔄 进行中 |
| `completed` | ✅ 已完成 |
| `failed` | ❌ 失败 |
| `cancelled` | 🚫 已取消 |

### 站点名称映射

| 原始值 | 显示 |
|--------|------|
| `basspro` | 🏪 Bass Pro Shops |
| `meatyourmaker` | 🥩 Meat Your Maker |

### 评分星级显示

| 评分 | 显示 |
|------|------|
| 5.0 | ⭐⭐⭐⭐⭐ |
| 4.0-4.9 | ⭐⭐⭐⭐ |
| 3.0-3.9 | ⭐⭐⭐ |
| 2.0-2.9 | ⭐⭐ |
| 0-1.9 | ⭐ |

---

## 工具响应模板

### 1. `start_scrape` 响应

**成功**：
```markdown
## 🚀 抓取任务已启动

- **任务 ID**: `{task_id}`
- **产品数量**: {total} 个
- **状态**: ⏳ 等待中

提交的产品链接：
1. {url_1}
2. {url_2}
...

> 💡 可以随时问我「任务 `{task_id_short}` 进展如何」查看进度。
```

### 2. `start_collect` 响应

**成功**：
```markdown
## 🕷️ 分类采集任务已启动

- **任务 ID**: `{task_id}`
- **分类页**: {category_url}
- **采集范围**: {pages_info}
- **状态**: ⏳ 等待中

> 💡 系统将自动从分类页收集所有产品链接，然后逐一抓取详情和评论。
> 可以随时查看任务进度。
```

### 3. `get_task_status` 响应

**进行中**：
```markdown
## 📊 任务进度

- **任务 ID**: `{task_id}`
- **类型**: {type_display}
- **状态**: 🔄 进行中
- **进度**: {completed}/{total}（{percentage}%）
- **当前**: 正在采集 {current_url_short}...
- **已耗时**: {elapsed}

{progress_bar}
```

**已完成**：
```markdown
## ✅ 任务完成

- **任务 ID**: `{task_id}`
- **类型**: {type_display}
- **结果**:
  - 📦 保存产品: **{products_saved}** 个
  - 💬 保存评论: **{reviews_saved}** 条
- **总耗时**: {duration}
```

**失败**：
```markdown
## ❌ 任务失败

- **任务 ID**: `{task_id}`
- **错误原因**: {error_message_friendly}

> 💡 是否需要重新提交任务？
```

### 4. `list_tasks` 响应

```markdown
## 📋 任务列表（共 {total} 个）

| # | 任务 ID | 类型 | 状态 | 进度 | 创建时间 |
|---|--------|------|------|------|---------|
| 1 | `{id_short}` | 产品抓取 | ✅ 已完成 | 5/5 | 01-15 08:30 |
| 2 | `{id_short}` | 分类采集 | 🔄 进行中 | 12/30 | 01-15 07:00 |
| 3 | `{id_short}` | 产品抓取 | ❌ 失败 | 0/3 | 01-14 20:00 |

> 💡 点击任务 ID 或告诉我任务 ID 查看详细进度。
```

### 5. `cancel_task` 响应

**成功**：
```markdown
## 🚫 任务已取消

- **任务 ID**: `{task_id}`

> ⚠️ 当前正在处理的产品会完成采集，后续产品不再执行。
```

### 6. `list_products` 响应

**有结果**（列表形式）：
```markdown
## 🔍 {context_description}

共找到 **{total}** 个产品{filter_description}

| # | 产品名称 | 价格 | 评分 | 评论数 | 库存 | 站点 |
|---|---------|------|------|--------|------|------|
| 1 | {name} | **${price}** | {rating}/5 ⭐ | {review_count} | {stock_icon} | {site_icon} |
...

{pagination_info}
```

**无结果**：
```markdown
没有找到符合条件的产品。

{suggestions}
```

### 7. `get_product_detail` 响应

```markdown
## 📦 {product_name}

| 信息 | 详情 |
|------|------|
| 🏷️ SKU | {sku} |
| 💰 价格 | **${price}** |
| ⭐ 评分 | {rating}/5（{review_count} 条评论） |
| 📦 库存 | {stock_display} |
| 🏪 站点 | {site_display} |
| 🔗 链接 | [查看原页面]({url}) |
| 🕐 更新时间 | {scraped_at} |

---

### 💬 最近评论

{reviews_table_or_empty}

### 📈 价格快照

{snapshots_table_or_empty}

{price_insight}
```

### 8. `query_reviews` 响应

**评论列表**：
```markdown
## 💬 {context_description}

共 **{total}** 条评论{filter_description}

| 评分 | 作者 | 标题 | 产品 | 日期 | 图片 |
|------|------|------|------|------|------|
| {stars} | {author} | {headline} | {product_name} | {date} | {has_img} |
...

{selected_review_body_if_few}
{pagination_info}
```

**单条评论详情**（当结果少于 3 条时展开正文）：
```markdown
### {stars} — "{headline}"
**作者**: {author} | **日期**: {date} | **产品**: {product_name}

> {body}

{images_if_any}
```

### 9. `get_price_history` 响应

```markdown
## 📈 价格历史（最近 {days} 天）

**产品 ID**: {product_id} | **数据点**: {data_points} 个

| 日期 | 价格 | 库存 | 评分 | 评论数 |
|------|------|------|------|--------|
| {date} | ${price} | {stock} | {rating} | {count} |
...

### 📊 价格趋势

- **最高价**: ${max_price}（{max_date}）
- **最低价**: ${min_price}（{min_date}）
- **当前价**: ${current_price}
- **波动幅度**: ${diff}（{diff_percent}%）
- **趋势**: {trend_description}
```

### 10. `get_stats` 响应

```markdown
## 📊 数据总览

| 指标 | 数值 |
|------|------|
| 📦 产品总数 | **{total_products}** |
| 💬 评论总数 | **{total_reviews}** |
| 💰 平均价格 | **${avg_price}** |
| ⭐ 平均评分 | **{avg_rating}/5** |
| 🕐 最后采集 | {last_scrape_at} |

### 🏪 站点分布

{per_site_breakdown}
```

### 11. `execute_sql` 响应

**重要：永远不要展示 SQL 语句本身**

根据查询目的，将结果转换为业务洞察：

```markdown
## 📊 {analysis_title}

{insight_summary}

{data_table_or_chart}

### 🔑 发现

- {finding_1}
- {finding_2}

{recommendation_if_applicable}
```

---

## 进度条生成规则

根据完成百分比生成文本进度条：

```
 0%: ░░░░░░░░░░░░░░░░░░░░ 0%
25%: ▓▓▓▓▓░░░░░░░░░░░░░░░ 25%
50%: ▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░ 50%
75%: ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░ 75%
100%: ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ 100%
```

每个 `▓` 代表 5%，共 20 格。

---

## 分页提示

当结果超过单页时，添加分页提示：

```markdown
> 📄 显示第 {offset+1}-{offset+count} 条，共 {total} 条 | 说「下一页」查看更多
```

---

## 空数据处理

不同场景的空数据提示：

| 场景 | 提示语 |
|------|--------|
| 无产品 | 暂无产品数据。是否需要启动一个采集任务？ |
| 无评论 | 该产品暂无评论记录。 |
| 无价格历史 | 该产品只有一次采集记录，暂无价格变化数据。持续采集后可查看趋势。 |
| 无任务 | 还没有任务记录。可以发送产品链接或分类页链接开始采集。 |
| 搜索无结果 | 没有找到匹配「{keyword}」的产品。试试换个关键词？ |
