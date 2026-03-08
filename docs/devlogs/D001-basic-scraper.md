# D001 - 基础爬虫开发日志

对应需求：[F001](../features/F001-basic-scraper.md) | 计划：[P001](../plans/P001-basic-scraper.md)

## 版本: v0.1.0

### 实现概要

使用 DrissionPage 控制 Chromium 浏览器访问 Bass Pro Shops 产品页，通过 JSON-LD 和 DOM 提取数据，存入 SQLite。

### 踩过的坑

#### 1. DrissionPage 的 `.text` 无法读取 `<script>` 标签内容

**现象**：`tab.eles('css:script[type="application/ld+json"]')` 获取到元素后，`.text` 返回空字符串。

**原因**：DrissionPage 对 `<script>` 标签的 `.text` 属性行为与浏览器 DOM 不同。

**解决**：改用 `tab.run_js()` 在页面上下文中通过 `document.querySelector().textContent` 提取。一次 JS 调用提取所有 JSON-LD 数据，避免多次调用开销。

#### 2. BV (Bazaarvoice) 评论数据是异步延迟加载的

**现象**：首次实现时评分和评论全部为 None。

**原因**：BV 的 `#bv-jsonld-bvloader-summary` 和 `#bv-jsonld-reviews-data` 是页面加载后异步注入的 script 标签，需要额外等待时间。

**解决**：
- 第一版：`time.sleep(2)` — 不够可靠
- 第二版：轮询 15 秒等两个 BV 元素出现 — 对无评论产品浪费时间
- 最终版：先等 `.bv_main_container` 容器出现（BV 组件加载标志），再轮询 5 秒等 JSON-LD 数据注入

#### 3. JSON-LD 类型不统一：Product vs ProductGroup

**现象**：部分产品 SKU 和价格为 None。

**原因**：有多个变体（颜色、尺码）的产品使用 `ProductGroup` 类型而非 `Product`，价格在 `hasVariant[0].offers` 中。

**解决**：JS 提取逻辑同时处理两种类型：
- `Product`：直接取 `name`、`sku`、`offers`
- `ProductGroup`：取 group 的 `name` 和 `productGroupID`（作为 SKU），第一个 variant 的 `offers`

#### 4. 库存状态误判

**现象**：大量产品被标记为 `out_of_stock`，但实际有货。

**原因**：页面上存在 class 为 `out_of_stock_-_hide_atc_button` 的 `<div>`，这是营销 espot 的 class，不代表真正缺货。

**解决**：移除 DOM class 检测，只使用 JSON-LD `offers.availability` 判断库存状态。无数据时标记为 `unknown`。

#### 5. SKU 文本使用中文冒号

**现象**：DOM 中提取 SKU 失败。

**原因**：页面显示 `SKU：1724696`（中文全角冒号 `：`），而正则只匹配了英文冒号。

**解决**：正则改为 `SKU[：:\s]*(\d+)` 同时匹配中文和英文冒号。

#### 6. `tab.wait` 没有 `.ele()` 方法

**现象**：`tab.wait.ele('#id', timeout=10)` 报错 `'TabWaiter' object has no attribute 'ele'`。

**原因**：DrissionPage 的 `tab.wait` 对象只有 `ele_displayed`、`ele_deleted` 等方法，没有通用的 `ele` 方法。

**解决**：直接用 `tab.ele('#id', timeout=10)` — `tab.ele()` 本身就支持 timeout 参数来等待元素出现。

### 关键数据源分析

| 数据 | JSON-LD 位置 | DOM 兜底 |
|------|-------------|---------|
| 名称 | `Product.name` / `ProductGroup.name` | `h1` 标签 |
| SKU | `Product.sku` / `ProductGroup.productGroupID` | `text:SKU` 元素正则 |
| 价格 | `Product.offers.price` / `ProductGroup.hasVariant[0].offers.price` | - |
| 库存 | `offers.availability` (InStock/OutOfStock) | - |
| 评分 | `#bv-jsonld-bvloader-summary` → `aggregateRating.ratingValue` | - |
| 评论数 | `#bv-jsonld-bvloader-summary` → `aggregateRating.reviewCount` | - |
| 评论 | `#bv-jsonld-reviews-data` → `review[]` | - |
