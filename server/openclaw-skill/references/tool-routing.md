# 工具路由详细逻辑

本文档定义了用户意图到 MCP 工具的完整映射规则。Agent 根据用户输入判断意图，选择最合适的工具（或工具组合）。

## 一、意图识别关键词

### 爬虫任务类

| 关键词/短语 | 意图 | 工具 |
|------------|------|------|
| 抓取、爬取、采集、scrape、crawl | 启动抓取 | `start_scrape` / `start_collect` |
| 任务、进度、状态、完成了吗 | 查询任务 | `get_task_status` / `list_tasks` |
| 取消、停止、中断 | 取消任务 | `cancel_task` |
| 最近的任务、任务列表、历史任务 | 任务列表 | `list_tasks` |

### 产品数据类

| 关键词/短语 | 意图 | 工具 |
|------------|------|------|
| 搜索、查找、找、有没有 | 搜索产品 | `list_products` |
| 详情、详细、这个产品 | 产品详情 | `get_product_detail` |
| 多少钱、价格、便宜、贵 | 价格查询 | `list_products` (带价格筛选) |
| 有货、缺货、库存 | 库存查询 | `list_products` (带 stock_status) |
| 评分高、好评、rating | 评分排序 | `list_products` (sort_by=rating) |

### 评论分析类

| 关键词/短语 | 意图 | 工具 |
|------------|------|------|
| 评论、评价、review | 查看评论 | `query_reviews` |
| 差评、1星、2星、不满意 | 差评查询 | `query_reviews` (max_rating=2) |
| 好评、5星、满意 | 好评查询 | `query_reviews` (min_rating=4) |
| 评论分析、评分分布 | 评论统计 | `execute_sql` |
| 带图评论、有图片 | 图片评论 | `query_reviews` (has_images=true) |
| 关于XX的评论 | 关键词搜索 | `query_reviews` (keyword=XX) |

### 价格趋势类

| 关键词/短语 | 意图 | 工具 |
|------------|------|------|
| 价格历史、价格变化、涨了、降了 | 单品价格趋势 | `get_price_history` |
| 价格对比、哪个便宜 | 多品比价 | `execute_sql` |
| 价格波动、价格区间 | 价格分析 | `execute_sql` |

### 统计报告类

| 关键词/短语 | 意图 | 工具 |
|------------|------|------|
| 统计、概览、总共、有多少 | 数据概览 | `get_stats` |
| 报告、分析、汇总 | 综合报告 | `get_stats` + `execute_sql` |
| 对比、比较、VS | 竞品对比 | `execute_sql` |

---

## 二、URL 识别规则

### 产品页 URL（用 `start_scrape`）

特征：URL 中包含产品标识符

```
# Bass Pro Shops 产品页
https://www.basspro.com/shop/en/product-name-12345
https://www.basspro.com/shop/en/some-product/...

# Meat Your Maker 产品页
https://www.meatyourmaker.com/products/product-name
https://www.meatyourmaker.com/product/...
```

### 分类页 URL（用 `start_collect`）

特征：URL 中包含 category、collection、shop 等分类标识

```
# Bass Pro Shops 分类页
https://www.basspro.com/shop/en/fishing-reels/...
https://www.basspro.com/shop/en/category-name

# Meat Your Maker 分类页
https://www.meatyourmaker.com/collections/all
https://www.meatyourmaker.com/collections/grinders
```

### 判断流程

1. 用户发送了 URL？
   - 是 → 识别域名
     - `basspro.com` 或 `meatyourmaker.com` → 支持的站点
     - 其他域名 → 提示不支持
   - 否 → 按关键词匹配意图
2. 识别 URL 类型
   - 产品页 → `start_scrape`
   - 分类页 → `start_collect`，询问是否限制页数
   - 不确定 → 询问用户确认

---

## 三、工具选择决策树

```
用户输入
├── 包含 URL？
│   ├── 是：单个产品 URL → start_scrape(urls=[url])
│   ├── 是：多个产品 URL → start_scrape(urls=[url1, url2, ...])
│   ├── 是：分类页 URL → start_collect(category_url=url)
│   └── 是：非支持站点 → 提示不支持
│
├── 关于任务？
│   ├── 提到具体任务 ID → get_task_status(task_id)
│   ├── "最近/所有任务" → list_tasks()
│   ├── "进行中的任务" → list_tasks(status="running")
│   └── "取消任务" → cancel_task(task_id)
│
├── 关于产品？
│   ├── 提到具体产品 ID → get_product_detail(product_id)
│   ├── 提到具体 SKU → get_product_detail(sku=sku)
│   ├── 提到具体 URL → get_product_detail(url=url)
│   ├── 关键词搜索 → list_products(search=keyword)
│   ├── 价格筛选 → list_products(min_price/max_price)
│   ├── 按站点 → list_products(site=site)
│   └── 需排名/对比 → execute_sql
│
├── 关于评论？
│   ├── 某产品的评论 → query_reviews(product_id=id)
│   ├── 按评分筛选 → query_reviews(min_rating/max_rating)
│   ├── 搜索关键词 → query_reviews(keyword=keyword)
│   ├── 评分分布统计 → execute_sql (GROUP BY rating)
│   └── 跨产品评论分析 → execute_sql
│
├── 关于价格？
│   ├── 单品价格历史 → get_price_history(product_id, days)
│   ├── 价格变化检测 → execute_sql (快照对比)
│   └── 多品比价 → execute_sql
│
├── 关于统计？
│   ├── 整体概览 → get_stats()
│   ├── 自定义统计 → execute_sql
│   └── 综合报告 → get_stats + execute_sql 组合
│
└── 不明确 → 询问用户具体需求
```

---

## 四、组合查询模式

某些用户需求需要组合使用多个工具：

### 模式 A：产品全景分析

```
步骤 1: get_product_detail(product_id=X)      → 基础信息
步骤 2: query_reviews(product_id=X, limit=50) → 评论列表
步骤 3: execute_sql(评分分布 SQL)              → 评分统计
步骤 4: get_price_history(product_id=X)        → 价格趋势
输出: 综合分析报告
```

### 模式 B：站点对比分析

```
步骤 1: get_stats()                           → 整体数据
步骤 2: execute_sql(按站点聚合 SQL)            → 站点维度统计
步骤 3: execute_sql(各站点 Top 产品 SQL)       → 各站点明星产品
输出: 对比报告
```

### 模式 C：差评预警

```
步骤 1: execute_sql(近期低分评论 SQL)          → 最近差评
步骤 2: query_reviews(max_rating=2, limit=10)  → 差评详情
输出: 差评预警报告 + 建议
```

### 模式 D：价格监控

```
步骤 1: execute_sql(价格变动检测 SQL)          → 有变动的产品
步骤 2: get_price_history(product_id=X)        → 逐个查看趋势
输出: 价格变动报告
```

---

## 五、参数推断规则

当用户没有明确指定参数时，使用以下默认策略：

| 参数 | 默认推断 |
|------|---------|
| `site` | 不筛选（两个站点都查） |
| `limit` | 列表默认 20，详情分析默认 50 |
| `days` | 价格历史默认 30 天 |
| `sort_by` | 产品默认按 `scraped_at`，评论默认按 `scraped_at` |
| `order` | 默认降序 `desc`（最新在前） |
| `max_pages` | 分类采集默认 0（全部页），但建议用户确认 |

### 上下文继承

当用户在对话中已经提到了某个产品或站点，后续查询应自动继承上下文：

- 用户先查了产品 A 的详情 → 再说"看看评论" → 自动用产品 A 的 ID
- 用户先搜了 Bass Pro 的产品 → 再说"价格最高的" → 自动加 site=basspro
