# 预置分析 SQL 查询

本文档包含 Agent 在执行数据分析时内部使用的 SQL 查询模板。这些查询通过 `execute_sql` 工具执行，结果必须转换为业务洞察后呈现给用户，**永远不要向用户展示 SQL 语句**。

> 所有查询均为 SQLite 语法，只读 SELECT，最多返回 500 行。

---

## 一、评论分析

### 1.1 单产品评分分布

```sql
SELECT
    CAST(rating AS INTEGER) AS star,
    COUNT(*) AS cnt
FROM reviews
WHERE product_id = {product_id}
GROUP BY CAST(rating AS INTEGER)
ORDER BY star DESC
```

**输出格式**：评分分布柱状图（文本）+ 好评率/差评率计算

### 1.2 站点评分分布

```sql
SELECT
    p.site,
    CAST(r.rating AS INTEGER) AS star,
    COUNT(*) AS cnt
FROM reviews r
JOIN products p ON r.product_id = p.id
GROUP BY p.site, star
ORDER BY p.site, star DESC
```

### 1.3 好评率排名（按产品）

```sql
SELECT
    p.id,
    p.name,
    p.site,
    COUNT(*) AS total_reviews,
    SUM(CASE WHEN r.rating >= 4 THEN 1 ELSE 0 END) AS positive,
    ROUND(SUM(CASE WHEN r.rating >= 4 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS positive_rate
FROM reviews r
JOIN products p ON r.product_id = p.id
GROUP BY p.id
HAVING total_reviews >= 5
ORDER BY positive_rate DESC
LIMIT 20
```

### 1.4 差评率排名（关注问题产品）

```sql
SELECT
    p.id,
    p.name,
    p.site,
    COUNT(*) AS total_reviews,
    SUM(CASE WHEN r.rating <= 2 THEN 1 ELSE 0 END) AS negative,
    ROUND(SUM(CASE WHEN r.rating <= 2 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS negative_rate
FROM reviews r
JOIN products p ON r.product_id = p.id
GROUP BY p.id
HAVING total_reviews >= 5
ORDER BY negative_rate DESC
LIMIT 20
```

### 1.5 最近差评（预警）

```sql
SELECT
    r.rating,
    r.author,
    r.headline,
    r.body,
    r.date_published,
    p.name AS product_name,
    p.site
FROM reviews r
JOIN products p ON r.product_id = p.id
WHERE r.rating <= 2
ORDER BY r.scraped_at DESC
LIMIT 20
```

### 1.6 带图评论统计

```sql
SELECT
    p.site,
    COUNT(*) AS total_reviews,
    SUM(CASE WHEN r.images IS NOT NULL AND r.images != '[]' AND r.images != '' THEN 1 ELSE 0 END) AS with_images,
    ROUND(SUM(CASE WHEN r.images IS NOT NULL AND r.images != '[]' AND r.images != '' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS image_rate
FROM reviews r
JOIN products p ON r.product_id = p.id
GROUP BY p.site
```

### 1.7 评论数 Top 产品

```sql
SELECT
    p.id,
    p.name,
    p.site,
    p.review_count,
    p.rating,
    p.price
FROM products p
WHERE p.review_count IS NOT NULL
ORDER BY p.review_count DESC
LIMIT 20
```

### 1.8 评论关键词出现频率（近似）

```sql
SELECT
    p.name,
    p.site,
    COUNT(*) AS mention_count
FROM reviews r
JOIN products p ON r.product_id = p.id
WHERE r.headline LIKE '%{keyword}%' OR r.body LIKE '%{keyword}%'
GROUP BY p.id
ORDER BY mention_count DESC
LIMIT 20
```

---

## 二、价格分析

### 2.1 价格区间分布

```sql
SELECT
    CASE
        WHEN price < 25 THEN '$0-25'
        WHEN price < 50 THEN '$25-50'
        WHEN price < 100 THEN '$50-100'
        WHEN price < 200 THEN '$100-200'
        WHEN price < 500 THEN '$200-500'
        ELSE '$500+'
    END AS price_range,
    COUNT(*) AS cnt
FROM products
WHERE price IS NOT NULL
GROUP BY price_range
ORDER BY MIN(price)
```

### 2.2 各站点价格统计

```sql
SELECT
    site,
    COUNT(*) AS product_count,
    ROUND(AVG(price), 2) AS avg_price,
    ROUND(MIN(price), 2) AS min_price,
    ROUND(MAX(price), 2) AS max_price,
    ROUND(AVG(rating), 2) AS avg_rating
FROM products
WHERE price IS NOT NULL
GROUP BY site
```

### 2.3 最贵/最便宜产品

```sql
-- 最贵
SELECT id, name, site, price, rating, review_count
FROM products
WHERE price IS NOT NULL
ORDER BY price DESC
LIMIT 10
```

```sql
-- 最便宜
SELECT id, name, site, price, rating, review_count
FROM products
WHERE price IS NOT NULL AND price > 0
ORDER BY price ASC
LIMIT 10
```

### 2.4 价格变动检测（7 天内有变化的产品）

```sql
SELECT
    p.id,
    p.name,
    p.site,
    p.price AS current_price,
    old_snap.price AS old_price,
    ROUND(p.price - old_snap.price, 2) AS price_change,
    ROUND((p.price - old_snap.price) * 100.0 / old_snap.price, 1) AS change_percent
FROM products p
JOIN (
    SELECT product_id, price, MIN(scraped_at) AS first_at
    FROM product_snapshots
    WHERE scraped_at >= datetime('now', '-7 days')
    GROUP BY product_id
) old_snap ON p.id = old_snap.product_id
WHERE p.price != old_snap.price
ORDER BY ABS(p.price - old_snap.price) DESC
LIMIT 20
```

### 2.5 价格波动最大的产品（历史全量）

```sql
SELECT
    p.id,
    p.name,
    p.site,
    ROUND(MIN(ps.price), 2) AS min_price,
    ROUND(MAX(ps.price), 2) AS max_price,
    ROUND(MAX(ps.price) - MIN(ps.price), 2) AS price_range,
    COUNT(ps.id) AS snapshot_count
FROM product_snapshots ps
JOIN products p ON ps.product_id = p.id
WHERE ps.price IS NOT NULL
GROUP BY ps.product_id
HAVING snapshot_count >= 2 AND price_range > 0
ORDER BY price_range DESC
LIMIT 20
```

### 2.6 降价产品（当前价 < 历史均价）

```sql
SELECT
    p.id,
    p.name,
    p.site,
    p.price AS current_price,
    ROUND(AVG(ps.price), 2) AS avg_historical_price,
    ROUND(p.price - AVG(ps.price), 2) AS diff,
    ROUND((p.price - AVG(ps.price)) * 100.0 / AVG(ps.price), 1) AS diff_percent
FROM products p
JOIN product_snapshots ps ON p.id = ps.product_id
WHERE p.price IS NOT NULL AND ps.price IS NOT NULL
GROUP BY p.id
HAVING current_price < avg_historical_price
ORDER BY diff_percent ASC
LIMIT 20
```

---

## 三、竞品分析

### 3.1 站点综合对比

```sql
SELECT
    site,
    COUNT(*) AS product_count,
    ROUND(AVG(price), 2) AS avg_price,
    ROUND(AVG(rating), 2) AS avg_rating,
    SUM(review_count) AS total_reviews,
    ROUND(AVG(review_count), 1) AS avg_reviews_per_product,
    SUM(CASE WHEN stock_status = 'in_stock' THEN 1 ELSE 0 END) AS in_stock_count,
    ROUND(SUM(CASE WHEN stock_status = 'in_stock' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS in_stock_rate
FROM products
GROUP BY site
```

### 3.2 各站点评分段产品数

```sql
SELECT
    site,
    SUM(CASE WHEN rating >= 4.5 THEN 1 ELSE 0 END) AS excellent,
    SUM(CASE WHEN rating >= 4.0 AND rating < 4.5 THEN 1 ELSE 0 END) AS good,
    SUM(CASE WHEN rating >= 3.0 AND rating < 4.0 THEN 1 ELSE 0 END) AS average,
    SUM(CASE WHEN rating < 3.0 THEN 1 ELSE 0 END) AS poor,
    SUM(CASE WHEN rating IS NULL THEN 1 ELSE 0 END) AS no_rating
FROM products
GROUP BY site
```

### 3.3 各站点 Top 5 产品（按评分）

```sql
SELECT
    id, name, site, price, rating, review_count
FROM products
WHERE rating IS NOT NULL AND review_count >= 3
ORDER BY rating DESC, review_count DESC
LIMIT 10
```

### 3.4 库存状态对比

```sql
SELECT
    site,
    stock_status,
    COUNT(*) AS cnt,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (PARTITION BY site), 1) AS percentage
FROM products
GROUP BY site, stock_status
ORDER BY site, cnt DESC
```

---

## 四、数据质量与新鲜度

### 4.1 数据完整性检查

```sql
SELECT
    site,
    COUNT(*) AS total,
    SUM(CASE WHEN price IS NULL THEN 1 ELSE 0 END) AS no_price,
    SUM(CASE WHEN rating IS NULL THEN 1 ELSE 0 END) AS no_rating,
    SUM(CASE WHEN review_count IS NULL OR review_count = 0 THEN 1 ELSE 0 END) AS no_reviews,
    SUM(CASE WHEN sku IS NULL OR sku = '' THEN 1 ELSE 0 END) AS no_sku,
    SUM(CASE WHEN stock_status IS NULL OR stock_status = 'unknown' THEN 1 ELSE 0 END) AS unknown_stock
FROM products
GROUP BY site
```

### 4.2 数据新鲜度（最后采集时间分布）

```sql
SELECT
    CASE
        WHEN scraped_at >= datetime('now', '-1 day') THEN '过去 24 小时'
        WHEN scraped_at >= datetime('now', '-7 days') THEN '过去 7 天'
        WHEN scraped_at >= datetime('now', '-30 days') THEN '过去 30 天'
        ELSE '超过 30 天'
    END AS freshness,
    COUNT(*) AS cnt
FROM products
GROUP BY freshness
ORDER BY MIN(scraped_at) DESC
```

### 4.3 采集任务成功率

```sql
SELECT
    type,
    COUNT(*) AS total_tasks,
    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed,
    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed,
    SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled,
    ROUND(SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS success_rate
FROM tasks
GROUP BY type
```

### 4.4 每日采集量趋势

```sql
SELECT
    DATE(scraped_at) AS date,
    COUNT(*) AS products_scraped
FROM products
WHERE scraped_at >= datetime('now', '-30 days')
GROUP BY DATE(scraped_at)
ORDER BY date
```

---

## 五、综合报告查询

### 5.1 性价比排名（高评分低价格）

```sql
SELECT
    id, name, site, price, rating, review_count,
    ROUND(rating / (price / 100.0), 2) AS value_score
FROM products
WHERE price > 0 AND rating IS NOT NULL AND review_count >= 5
ORDER BY value_score DESC
LIMIT 20
```

**value_score 说明**：评分 / (价格/100)，数值越高性价比越好。

### 5.2 评论增长趋势（按月）

```sql
SELECT
    strftime('%Y-%m', scraped_at) AS month,
    COUNT(*) AS new_reviews
FROM reviews
GROUP BY month
ORDER BY month
```

### 5.3 无评论的高价产品（潜在数据缺失）

```sql
SELECT
    id, name, site, price, rating, review_count
FROM products
WHERE (review_count IS NULL OR review_count = 0)
    AND price IS NOT NULL AND price > 50
ORDER BY price DESC
LIMIT 20
```

### 5.4 评分与评论数相关性

```sql
SELECT
    CASE
        WHEN review_count < 5 THEN '0-4 条'
        WHEN review_count < 20 THEN '5-19 条'
        WHEN review_count < 50 THEN '20-49 条'
        WHEN review_count < 100 THEN '50-99 条'
        ELSE '100+ 条'
    END AS review_tier,
    COUNT(*) AS product_count,
    ROUND(AVG(rating), 2) AS avg_rating,
    ROUND(AVG(price), 2) AS avg_price
FROM products
WHERE rating IS NOT NULL
GROUP BY review_tier
ORDER BY MIN(review_count)
```
