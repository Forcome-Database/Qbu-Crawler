# Waltons.com 采集器设计

## 概述

为 Qbu-Crawler 新增 waltons.com 站点采集器，基于 BigCommerce (Stencil) 平台 + TrustSpot/RaveCapture 评论系统。

## 技术栈分析

| 维度 | Waltons.com |
|------|-------------|
| **电商平台** | BigCommerce (Stencil 主题) |
| **评论系统** | TrustSpot / RaveCapture（普通 DOM，无 Shadow DOM） |
| **结构化数据** | 丰富 JSON-LD（Product + BreadcrumbList + reviews） |
| **反爬机制** | 无明显反爬（无年龄弹窗、无 Cloudflare） |

## 架构决策

### 继承模式

```
BaseScraper (scrapers/base.py)
  └── WaltonsScraper (scrapers/waltons.py)
```

- 继承 `BaseScraper` 的浏览器管理、重启、延迟、图片上传机制
- 使用默认 `eager` 加载模式（BigCommerce 服务端渲染，无需等第三方脚本初始化）
- **不需要**覆盖 `_build_options()`

### 数据提取策略：JSON-LD 优先 + DOM 兜底

**产品结果字段**（与现有 scraper 保持一致）：

```python
{
    "url": url,           # 产品页 URL（UPSERT 键）
    "site": "waltons",    # 站点标识（硬编码）
    "name": ...,          # 产品名称
    "sku": ...,           # SKU 编号
    "price": ...,         # 价格（float）
    "stock_status": ...,  # 库存状态（"In Stock" / "Out of Stock"）
    "review_count": ...,  # 评论总数（int）
    "rating": ...,        # 平均评分（float）
    # ownership 由调用方设置，scraper 不感知
}
```

**数据来源**（JSON-LD 优先）：

| 数据 | JSON-LD 路径 | DOM 兜底选择器 |
|------|-------------|----------------|
| 名称 | `Product.name` | `h1` |
| SKU | `Product.sku` | `.productView-info-value--sku` |
| 价格 | `offers.price` | `[data-product-price-without-tax]` |
| 库存 | `offers.availability` 含 `InStock` | Add to Cart 按钮存在性 |
| 评分 | `aggregateRating.ratingValue` | TrustSpot `.ts-stars-1[title]` |
| 评论数 | `aggregateRating.reviewCount` | `.review-score` 文本 |

JSON-LD 特点：
- 页面有多个 JSON-LD script：BreadcrumbList、Product（含 reviews 数组）、Product（含 sku + offers）
- **按内容匹配**，不依赖位置索引：遍历所有 `@type: Product` 的 JSON-LD，按字段存在性合并
  - 含 `aggregateRating` 的 → 评分、评论数、部分评论（~15 条）
  - 含 `sku` 的 → SKU
  - 含 `offers` 的 → 价格、库存
- 合并策略：优先取含 `sku` 的完整 Product，再从其他 Product 补充 `aggregateRating`/`review`

**无评论产品处理**：若无 `aggregateRating`，返回 `rating=None, review_count=0, reviews=[]`

### 评论提取（TrustSpot DOM）

**无 Shadow DOM**，直接从普通 DOM 提取。

| 数据 | 选择器 |
|------|--------|
| 评论容器 | `.trustspot-widget-review-block` |
| 作者 | `.result-box-header .user-name` |
| 日期 | `.result-box-header .date span`（格式 `MM/DD/YYYY`） |
| 评分 | `.ts-widget-review-star.filled` 计数（预期 1-5），降级：`.stars .ts-stars-1[title]` 解析 title 属性 |
| 正文 | `.comment-box` 文本（过滤掉 `aria-label` span 后取剩余文本） |
| 标题 | **无**（TrustSpot 不支持评论标题，headline 为空） |
| 图片 | `.description-block img`（排除 `src` 含 `social/`、`star`、`icon`、`avatar` 的图标，仅保留用户上传图片） |
| 认证买家 | `.buyer` 存在性 |
| 地点 | `.ts-location` |

**评论翻页**：
- 翻页按钮：`a.next-page`（链接到 `#trustspot-widget-wrapper`）
- 机制：JS 点击翻页，页面内替换评论内容（非整页刷新）
- 每页约 54 条评论
- 受 `MAX_REVIEWS` 配置限制

**评论去重**：
- 复用现有 `(product_id, author, headline, body_hash)` 联合唯一键
- 由于 TrustSpot 无 headline，使用空字符串作为 headline
- body_hash = `MD5(body)[:16]`

### 等待 TrustSpot 加载

TrustSpot widget 通过外部 JS 异步加载。需要：
1. 等待页面 DOM 就绪（`eager` 模式自动处理）
2. 轮询等待 `.trustspot-widget-review-block` 出现（表示评论已渲染）
3. 超时兜底：如果 TrustSpot 未加载，仍可从 JSON-LD 获取部分评论（~15 条）

### 列表页采集

| 数据 | 选择器 |
|------|--------|
| 产品卡片 | `.productGrid .product` |
| 产品链接 | `.card-title a[href]` |
| 下一页 | `.pagination-item--next a`（标准 `<a>` 链接） |

**翻页策略**：
- 在分类 URL 追加 `?limit=100` 一次加载最多产品
- 通过 `.pagination-item--next a` 的 `href` 属性获取下一页 URL
- 直接 `tab.get(next_url)` 导航（标准 URL 翻页，非 JS 点击）
- `max_pages` 参数限制最大翻页数

### URL 匹配

域名：`www.waltons.com` 和 `waltons.com`（需同时匹配）

**SITE_MAP 实现**：在 `scrapers/__init__.py` 中添加两条记录，共享同一 site key：
```python
"www.waltons.com": ("waltons", "scrapers.waltons", "WaltonsScraper"),
"waltons.com": ("waltons", "scrapers.waltons", "WaltonsScraper"),
```

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `scrapers/waltons.py` | **新增** | WaltonsScraper 实现（~200-250 行） |
| `scrapers/__init__.py` | **修改** | SITE_MAP 新增 waltons.com 条目 |
| `docs/rules/waltons.md` | **新增** | 站点采集规则文档 |
| `CLAUDE.md` | **修改** | 支持站点列表 + 项目结构更新 |

## scrape() 方法流程

```
0. _maybe_restart_browser()  ← 复用基类定期重启机制
1. tab.get(url)
2. _check_url_match(tab, url)  ← 检测重定向/404
3. _increment_and_delay(tab)  ← 计数 + 随机延迟
4. 提取所有 JSON-LD，按内容匹配合并 Product 对象
5. 从合并后的 JSON-LD 解析产品信息（name, sku, price, availability, rating, review_count）
6. DOM 兜底：如 JSON-LD 缺失字段，从 DOM 补充
7. 等待 TrustSpot 评论加载（轮询 .trustspot-widget-review-block，超时使用 BV_WAIT_TIMEOUT 配置）
8. 如果评论已加载：
   a. 提取当前页所有评论
   b. 循环点击 a.next-page 翻页（受 MAX_REVIEWS 限制）
   c. 每页提取后按 (author, body_hash) 去重
9. 如果 TrustSpot 未加载：从 JSON-LD review 数组提取（~15 条兜底）
10. 处理评论图片（_process_review_images）
11. 返回 {"product": {url, site, name, sku, price, stock_status, review_count, rating}, "reviews": [...]}
```

## collect_product_urls() 方法流程

```
1. 使用 urllib.parse 正确追加/更新 limit=100 参数（处理已有 query string 的情况）
2. tab.get(category_url)
3. _increment_and_delay(tab)
4. 提取 .productGrid .product 下的 .card-title a[href]
5. 检查 .pagination-item--next a 是否存在
6. 如存在且未达 max_pages：导航到下一页 URL，重复 3-5
7. URL 去重后返回
```

## 风险与应对

| 风险 | 应对 |
|------|------|
| TrustSpot 加载慢或失败 | JSON-LD 兜底（~15 条评论），不阻塞产品数据 |
| `eager` 模式阻止 TrustSpot 初始化 | **中等风险**：TrustSpot 是第三方异步脚本。实现后需早期测试，如确认失败则覆盖 `_build_options()` 切换 `normal` 模式 |
| JSON-LD 结构变化 | DOM 兜底选择器作为第二优先级 |
| 评论翻页按钮 `a.next-page` 变化 | 降级到只提取首页评论 + JSON-LD 评论 |
| 分类 URL 已含 query 参数 | 使用 `urllib.parse` 正确合并参数，避免拼接错误 |
| 无评论产品 | `rating=None, review_count=0, reviews=[]`，不报错 |

## 预估

- **代码量**：~200-250 行（远低于 basspro 525 行和 meatyourmaker 314 行）
- **复杂度**：低（无 Shadow DOM、无年龄弹窗、无特殊加载模式需求）
