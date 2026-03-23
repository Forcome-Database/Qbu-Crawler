---
name: qbu-product-data
description: 产品数据深度分析技能。当需要评论分析、竞品对比、价格趋势分析或生成数据报告时使用。提供 SQL 查询模板和分析工作流。
---

# 产品数据深度分析

当需要进行评论分析、竞品对比、价格趋势分析或生成数据报告时，使用以下模板。

通过 `execute_sql` 执行以下查询，**绝不向用户展示 SQL**，只呈现分析结果。

---

## 评论分析

### 评分分布（单产品）

```sql
SELECT CAST(rating AS INTEGER) AS star, COUNT(*) AS cnt FROM reviews WHERE product_id = {product_id} GROUP BY star ORDER BY star DESC
```

### 好评率排名

```sql
SELECT p.name, p.site, COUNT(*) AS total, ROUND(SUM(CASE WHEN r.rating >= 4 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS rate FROM reviews r JOIN products p ON r.product_id = p.id GROUP BY p.id HAVING total >= 5 ORDER BY rate DESC LIMIT 15
```

### 差评预警

```sql
SELECT r.rating, r.author, r.headline, SUBSTR(r.body, 1, 100) AS preview, p.name, p.site FROM reviews r JOIN products p ON r.product_id = p.id WHERE r.rating <= 2 ORDER BY r.scraped_at DESC LIMIT 10
```

### 评论关键词搜索

```sql
SELECT p.name, p.site, COUNT(*) AS mentions FROM reviews r JOIN products p ON r.product_id = p.id WHERE r.headline LIKE '%{keyword}%' OR r.body LIKE '%{keyword}%' GROUP BY p.id ORDER BY mentions DESC LIMIT 15
```

---

## 价格分析

### 价格区间分布

```sql
SELECT CASE WHEN price < 25 THEN '$0-25' WHEN price < 50 THEN '$25-50' WHEN price < 100 THEN '$50-100' WHEN price < 200 THEN '$100-200' WHEN price < 500 THEN '$200-500' ELSE '$500+' END AS range, COUNT(*) AS cnt FROM products WHERE price IS NOT NULL GROUP BY range ORDER BY MIN(price)
```

### 降价产品

```sql
SELECT p.name, p.site, p.price AS current, ROUND(AVG(ps.price), 2) AS avg_hist, ROUND((p.price - AVG(ps.price)) * 100.0 / AVG(ps.price), 1) AS diff_pct FROM products p JOIN product_snapshots ps ON p.id = ps.product_id WHERE p.price IS NOT NULL AND ps.price IS NOT NULL GROUP BY p.id HAVING current < avg_hist ORDER BY diff_pct ASC LIMIT 15
```

---

## 竞品分析

### 站点综合对比

```sql
SELECT site, COUNT(*) AS products, ROUND(AVG(price), 2) AS avg_price, ROUND(AVG(rating), 2) AS avg_rating, SUM(review_count) AS total_reviews, SUM(CASE WHEN stock_status = 'in_stock' THEN 1 ELSE 0 END) AS in_stock FROM products GROUP BY site
```

### 性价比排名

```sql
SELECT name, site, price, rating, review_count, ROUND(rating / (price / 100.0), 2) AS value_score FROM products WHERE price > 0 AND rating IS NOT NULL AND review_count >= 5 ORDER BY value_score DESC LIMIT 15
```

---

## 归属分析

### 自有 vs 竞品对比

```sql
SELECT ownership, COUNT(*) AS products, ROUND(AVG(price), 2) AS avg_price, ROUND(AVG(rating), 2) AS avg_rating, SUM(review_count) AS total_reviews FROM products GROUP BY ownership
```

### 自有产品差评预警

```sql
SELECT r.rating, r.author, r.headline, SUBSTR(r.body, 1, 100) AS preview, p.name, p.site FROM reviews r JOIN products p ON r.product_id = p.id WHERE p.ownership = 'own' AND r.rating <= 2 ORDER BY r.scraped_at DESC LIMIT 15
```

### 按时间范围查新增

```sql
SELECT url, name, sku, price, stock_status, rating, review_count, scraped_at, site, ownership FROM products WHERE scraped_at >= datetime('{start_time}') ORDER BY site, ownership
```

---

## 数据质量

### 完整性

```sql
SELECT site, COUNT(*) AS total, SUM(CASE WHEN price IS NULL THEN 1 ELSE 0 END) AS no_price, SUM(CASE WHEN rating IS NULL THEN 1 ELSE 0 END) AS no_rating FROM products GROUP BY site
```

### 新鲜度

```sql
SELECT CASE WHEN scraped_at >= datetime('now', '-1 day') THEN '24小时内' WHEN scraped_at >= datetime('now', '-7 days') THEN '7天内' ELSE '超过7天' END AS freshness, COUNT(*) AS cnt FROM products GROUP BY freshness
```

---

## 输出原则

1. **先结论后数据** — "Bass Pro 整体评分优于 Meat Your Maker（4.3 vs 3.8）"
2. **对比有参照** — "低于平均价 $120，便宜 17.5%"
3. **趋势有方向** — "价格近 7 天下降 8%"
4. **给出行动建议** — "建议关注这 3 个降价产品"
