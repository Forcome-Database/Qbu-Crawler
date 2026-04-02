---
name: qbu-product-data
description: 产品数据深度分析技能。用于对比、趋势、异常、根因和业务建议，不负责导出产物。
---

# 产品数据深度分析

当问题超出单个基础工具可直接回答的范围时，使用本技能。

本技能的目标不是“多跑几条 SQL”，而是：

- 先判断问题类型
- 再选最小必要证据
- 再给结论、证据、解读、建议

通过 `execute_sql` 执行模板化查询，但不要向用户展示 SQL 原文。

## 这项技能负责什么

负责：

- overview
- comparison
- trend
- anomaly
- root-cause

不负责：

- 抓取任务提交
- CSV 写入
- 导出图片
- 发邮件
- 生成附件

如果用户要的是 `produce` 动作，而当前没有 dedicated tool，应该回到 `AGENTS.md` 的 fail-fast 规则，而不是在这里硬凑结果。

## 核心原则

1. 先判断问题类型，不要一上来就跑 SQL。
2. 先用最小必要证据回答问题，不要一次性堆很多查询。
3. 对比必须有基线，不能只报单点数字。
4. 趋势必须说明方向和幅度，不能只说“有变化”。
5. 根因判断只能基于现有证据给出“更可能 / 主要集中在”这类表述。
6. 证据不足时要明确说“不足以下结论”。
7. 输出必须遵循 `TOOLS.md`，不暴露 SQL。

## 进入条件（Decision Vector）

只有当这轮请求满足以下条件时，才进入本技能：

- `needs_data_read=yes`
- `needs_judgment=yes`

以下情况不要进入本技能：

- 只是精确读取：
  - “库里有多少产品”
  - “库里有多少评论”
  - “最近更新的是谁”
- 只是系统动作：
  - 提交抓取
  - 修改 CSV
- 只是产物交付：
  - 导出图片
  - 发邮件
  - 生成附件

如果请求是复合 ask：

- 先完成最小必要的 `data_read`
- 只有需要比较、归因、趋势判断时才进入本技能
- 如果后面还带 `artifact`，分析完成后回到外层路由，不在本技能里代替 dedicated tool

## Canonical Semantics

- `ingested_review_rows`：`reviews` 表中的已入库评论行数；默认提到“评论数”时，优先指这个口径
- `site_reported_review_total_current`：站点页面当前展示的评论总数，通常来自 `products.review_count`
- `matched_review_product_count`：命中评论条件的产品数，不等于产品总数
- `image_review_rows`：带图评论数

禁止把 `ingested_review_rows` 和 `site_reported_review_total_current` 混称为同一个“评论数”。分析时必须显式说明当前采用的口径。

## Time Axis Rules

- `product_state_time`：产品状态更新时间，适用于价格、库存、评分、站点展示评论总数等当前态信息
- `review_ingest_time`：评论抓取入库时间，适用于“最近抓到什么”“最近新增了多少评论”
- `review_publish_time`：评论在站点上的发布时间，适用于“某时间段用户说了什么”
- `product_count` 绑定当前产品 scope，本身不应被评论时间窗悄悄削减；如果评论条件缩小了产品集合，必须单独写成 `matched_review_product_count`

默认规则：

- “概览”默认看全库
- “最近”不能模糊处理，必须落到明确时间轴；未指明时，优先按问题类型选择 `review_ingest_time` 或 `product_state_time`
- “差评”默认优先看 `rating <= 2`

## Ownership Caveat

- `ownership` 是当前分类字段，不是严格的历史事实快照
- 涉及历史比较时，要提醒用户：当前 own / competitor 归属可能已经被后续修正
- 推荐提醒用语：
  - `按当前归属回看，过去 30 天……`
  - `这里的自有 / 竞品是按当前归属回看，不代表严格的历史归属快照`

## 问题分类（analysis shorthand only）

### 1. Overview

适用：

- “整体情况怎么样”
- “目前库里是什么状态”
- “最近抓取的数据怎么样”

目标：

- 给总体规模、分布、代表性样本

### 2. Comparison

适用：

- 自有 vs 竞品
- Bass Pro vs MYM vs Walton's
- 某产品 vs 某产品

目标：

- 给差异、基线、相对优势或短板

### 3. Trend

适用：

- 价格变化
- 评论量变化
- 评分走势

目标：

- 给方向、幅度、时间窗口

### 4. Anomaly

适用：

- 差评是不是突然变多
- 某站点为什么异常
- 某时间窗为什么评论数激增

目标：

- 先确认是否真异常，再解释可能原因

### 5. Root Cause / Recommendation

适用：

- 差评主要集中在哪些问题
- 用户最不满意什么
- 应该优先改什么

目标：

- 从评论和结构化数据中提炼问题簇
- 给出优先级更高的动作建议

## 工作流

### Step 1: 明确范围

如果这是复合 ask，先用 decision vector 拆成：

- `needs_data_read`
- `needs_judgment`
- `needs_system_action`
- `needs_artifact`
- `needs_confirmation`
- `needs_clarification`

本技能只负责其中的 judgment 层，不负责把整条复合请求一次做完。

先明确：

- 对象：单产品 / 单站点 / ownership / 全库
- 时间：当前快照 / 最近 24 小时 / 最近 7 天 / 指定范围
- 指标：价格 / 评分 / 评论量 / 低分评论 / 库存 / 翻译状态

默认规则：

- “概览”默认看全库
- “最近”先明确是 `review_ingest_time`、`review_publish_time` 还是 `product_state_time`
- “差评”默认优先看 `rating <= 2`

### Step 2: 先用基础工具，再补 SQL

优先顺序：

1. 现成基础工具：
   - `get_stats`
   - `list_products`
   - `get_product_detail`
   - `query_reviews`
   - `get_price_history`
2. 只有需要聚合、排行、交叉维度比较时再用 `execute_sql`

### Step 3: 做判断

区分三层：

- **事实**
  - 当前平均评分是多少
  - 哪个站点评论量更多
- **对比**
  - 高于谁 / 低于谁
  - 贵多少 / 便宜多少
- **解释**
  - 哪种现象最主要
  - 证据支持到什么程度

### Step 4: 输出

默认结构：

```md
## 核心结论

- {结论 1}
- {结论 2}

## 证据

- {关键证据 1}
- {关键证据 2}

## 业务解读

- {这意味着什么}

## 建议动作

- {action_1}
- {action_2}
```

如果问题只需要概览，可简化，但至少保留：

- 结论
- 证据

## 什么时候用 playbook，什么时候自由查询

### 优先用 playbook

当问题属于：

- overview
- comparison
- trend
- anomaly
- root-cause

且现有模板足够支撑时，优先用本技能。

### 可以自由查询

当出现以下情况时，可自由组合基础工具和 `execute_sql`：

- 问题超出当前 playbook 覆盖范围
- 标准证据不够回答问题
- 需要临时构造新的分组维度
- 需要更细的钻取

即使自由查询，也必须保持：

- 不暴露 SQL
- 先结论后证据
- 最终单次收口
- 明确说明本轮使用的指标口径与时间轴

## 证据不足时怎么说

推荐表述：

- “目前证据更像是初步信号，还不足以下确定结论。”
- “从现有样本看，问题主要集中在……，但样本量还不大。”
- “价格有波动，但缺少更长时间窗口，不宜过度解释。”

## 常用分析模板

### 评分分布（单产品）

```sql
SELECT CAST(rating AS INTEGER) AS star, COUNT(*) AS cnt
FROM reviews
WHERE product_id = {product_id}
GROUP BY star
ORDER BY star DESC
```

### 好评率排行

```sql
SELECT p.name, p.site, COUNT(*) AS total,
       ROUND(SUM(CASE WHEN r.rating >= 4 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS rate
FROM reviews r
JOIN products p ON r.product_id = p.id
GROUP BY p.id
HAVING total >= 5
ORDER BY rate DESC
LIMIT 15
```

### 差评预警

```sql
SELECT r.rating, r.author, r.headline, SUBSTR(r.body, 1, 100) AS preview, p.name, p.site
FROM reviews r
JOIN products p ON r.product_id = p.id
WHERE r.rating <= 2
ORDER BY r.scraped_at DESC
LIMIT 10
```

### 关键词提及

```sql
SELECT p.name, p.site, COUNT(*) AS mentions
FROM reviews r
JOIN products p ON r.product_id = p.id
WHERE r.headline LIKE '%{keyword}%' OR r.body LIKE '%{keyword}%'
GROUP BY p.id
ORDER BY mentions DESC
LIMIT 15
```

### 价格区间分布

```sql
SELECT CASE
         WHEN price < 25 THEN '$0-25'
         WHEN price < 50 THEN '$25-50'
         WHEN price < 100 THEN '$50-100'
         WHEN price < 200 THEN '$100-200'
         WHEN price < 500 THEN '$200-500'
         ELSE '$500+'
       END AS range,
       COUNT(*) AS cnt
FROM products
WHERE price IS NOT NULL
GROUP BY range
ORDER BY MIN(price)
```

### 站点综合对比

```sql
SELECT site,
       COUNT(*) AS products,
       ROUND(AVG(price), 2) AS avg_price,
       ROUND(AVG(rating), 2) AS avg_rating,
       SUM(review_count) AS site_reported_review_total_current
FROM products
GROUP BY site
```

### 自有 vs 竞品

```sql
SELECT ownership,
       COUNT(*) AS products,
       ROUND(AVG(price), 2) AS avg_price,
       ROUND(AVG(rating), 2) AS avg_rating,
       SUM(review_count) AS site_reported_review_total_current
FROM products
GROUP BY ownership
```
