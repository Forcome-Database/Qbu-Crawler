# Walton's 采集规则

## 站点信息

- **域名**：`waltons.com` / `www.waltons.com`
- **电商平台**：BigCommerce (Stencil 主题)
- **评论系统**：TrustSpot / RaveCapture（普通 DOM，无 Shadow DOM）
- **产品 URL 格式**：`/product-slug/`（如 `/waltons-22-meat-grinder/`）
- **分类 URL 格式**：`/categories/parent/child`（如 `/categories/equipment/waltons-equipment`）

## 站点专属配置

| 配置 | 值 | 说明 |
|------|-----|------|
| 加载模式 | `normal` | TrustSpot 脚本在 eager 模式下无法初始化 |
| UA | 自定义 Chrome 131 | Cloudflare bot 检测需要真实 UA |
| `--disable-blink-features` | `AutomationControlled` | 绕过 Cloudflare 自动化检测 |

## 反爬机制

waltons.com 使用 **Cloudflare** 保护，需要：
1. `--disable-blink-features=AutomationControlled` 禁用自动化标记
2. 自定义 User-Agent（避免默认 Chrome headless UA）
3. `normal` 加载模式（让 Cloudflare JS challenge 有机会执行）

## 数据提取策略（优先级）

1. **JSON-LD** (`script[type="application/ld+json"]`) — 产品数据主要来源
2. **TrustSpot DOM** — 评论详情（普通 DOM，无 Shadow DOM）
3. **DOM 元素** — 兜底方案

### JSON-LD 结构

页面包含多个 JSON-LD script（由 BigCommerce 和 TrustSpot 分别注入）：

| JSON-LD | 来源 | 包含字段 |
|---------|------|----------|
| BreadcrumbList | BigCommerce | 面包屑导航 |
| Product（含 sku + offers） | BigCommerce | name, sku, url, description, image, offers |
| Product（含 aggregateRating + review） | TrustSpot | aggregateRating, review 数组（~15 条） |

**合并策略**：按内容匹配（不依赖位置索引），含 `sku` 的 Product 为权威源，其他 Product 补充 `aggregateRating`/`review`。

### 产品字段选择器

| 数据 | JSON-LD 路径 | DOM 兜底选择器 |
|------|-------------|----------------|
| 名称 | `Product.name` | `h1` |
| SKU | `Product.sku` | `[data-product-sku]` |
| 价格 | `offers.price` | `.productView-price .price--withoutTax` |
| 库存 | `offers.availability` 含 `InStock`/`OutOfStock` | — |
| 评分 | `aggregateRating.ratingValue` | — |
| 评论数 | `aggregateRating.reviewCount` | — |

注：`offers` 可能是 dict 或 list（多变体产品），取第一个元素。

## 评论提取（TrustSpot DOM）

**无 Shadow DOM**，直接从普通 DOM 提取。

### 选择器

| 数据 | 选择器 |
|------|--------|
| 评论容器 | `.trustspot-widget-review-block` |
| 作者 | `.result-box-header .user-name` |
| 日期 | `.result-box-header .date span`（格式 `MM/DD/YYYY`） |
| 评分 | `.ts-widget-review-star.filled` 计数（降级：`.stars .ts-stars-1[title]`） |
| 正文 | `.comment-box span`（第 2 个 span，第 1 个是 aria-label） |
| 标题 | **无**（TrustSpot 不支持评论标题，headline 为空字符串） |
| 图片 | `.description-block img`（排除 social/star/icon/avatar 图标） |

### 翻页机制

- 翻页按钮：`a.next-page`（JS 点击，页面内替换评论内容）
- 每页约 54 条评论
- 翻页后等待 2 秒供 TrustSpot 重新渲染
- 受 `MAX_REVIEWS`（默认 200）限制

### 评论去重

- 使用 `(author, body_hash)` 组合去重
- `body_hash = MD5(body)[:16]`
- TrustSpot 无 headline，所有评论 headline 为空字符串

## 分类页采集

### 选择器

| 数据 | 选择器 |
|------|--------|
| 产品卡片 | `.productGrid .product` |
| 产品链接 | `.card-title a[href]` |
| 下一页 | `.pagination-item--next a`（标准 `<a>` 链接，读 `href` 直接导航） |

### 翻页策略

- 在分类 URL 追加 `?limit=100` 减少翻页次数
- 使用 `urllib.parse` 安全拼接参数（处理已有 query string）
- 通过 `.pagination-item--next a` 的 `href` 直接导航
- BigCommerce URL 模式：`{category_url}?limit=100&page=N`

### 每页数量选项

BigCommerce 支持：8, 12, 16, 20, 40, 100

## 已知限制

1. **部分评论无正文**：TrustSpot 允许纯评分评论（无文字），约 50% 评论可能没有正文
2. **TrustSpot JSON-LD 仅含 ~15 条评论**：兜底数据有限，完整评论依赖 DOM 翻页
3. **Cloudflare 可能升级检测**：如果当前绕过方式失效，需要更新反检测参数
4. **aggregateRating 依赖 TrustSpot 加载**：必须用 `normal` 模式，否则评分和评论数无法获取
