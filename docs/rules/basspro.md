# Bass Pro Shops 采集规则

## 站点信息

- **域名**：`www.basspro.com`
- **产品 URL 格式**：`/shop/en/xxx` 或 `/p/xxx`（后者是规范化路径）
- **分类 URL 格式**：`/l/category-slug`

## 站点专属配置

| 配置 | 默认值 | 说明 |
|------|--------|------|
| `BV_WAIT_TIMEOUT` | `10` | Bazaarvoice 数据等待超时（秒） |
| `BV_POLL_INTERVAL` | `0.5` | Bazaarvoice 数据轮询间隔（秒） |

## 数据提取策略（优先级）

1. **JSON-LD** (`script[type="application/ld+json"]`) — 产品数据主要来源，通过 `tab.run_js()` 提取
2. **Bazaarvoice JSON-LD** (`#bv-jsonld-bvloader-summary`) — 评分和评论数
3. **BV Shadow DOM** — 评论详情（作者、标题、正文、评分、日期、图片），通过点击 Reviews Accordion 展开 + 循环 LOAD MORE 加载全部评论后从 Shadow DOM 提取
4. **DOM 元素** — 兜底方案（如 `h1` 取名称、`text:SKU` 取 SKU）

## 页面类型处理

- **`Product`** 类型：直接取 `name`、`sku`、`offers.price`
- **`ProductGroup`** 类型：取 group 的 `name` 和 `productGroupID` 作为 SKU，第一个 variant 的 `offers.price`

## 等待策略

使用 `eager` 加载模式（DOM 就绪即停，不等图片等资源），配合分阶段等待：

1. `tab.get(url)` — eager 模式下 DOM 就绪自动返回
2. `tab.wait.ele_displayed('tag:h1')` — 等主内容渲染
3. `tab.ele('css:.bv_main_container')` — 等 BV 组件容器加载
4. `_wait_for_bv_data(tab)` — JS 轮询等待 BV JSON-LD 注入（见下文）

**BV 数据轮询机制**（`_wait_for_bv_data`）：

仅等待 `#bv-jsonld-bvloader-summary`（评分摘要），评论详情改从 Shadow DOM 获取。

## 评论提取流程（Shadow DOM）

1. `_click_reviews_tab(tab)` — 点击 Reviews Accordion 展开（`.styles_AccordionWrapper__JYyM_` 中文本含 "Reviews" 的标题）
2. `_load_all_reviews(tab)` — 循环点击 Shadow DOM 内 `button[aria-label*="Load More"]` 直到消失（安全上限 200 次），每次点击后等待评论数量增加
3. `_scroll_all_reviews(tab)` — 批量滚动 + 定向滚动触发图片懒加载（见下文）
4. `_extract_reviews_from_dom(tab)` — 从 Shadow DOM 的叶子级 `section` 元素提取评论数据
5. `_process_review_images(reviews)` — 下载评论图片到 MinIO，替换为公开 URL

### Shadow DOM 选择器

均在 `[data-bv-show="reviews"].shadowRoot` 内，每个元素有多级降级：

| 元素 | S1（优先） | S2 降级 | S3 降级 |
|------|-----------|---------|---------|
| 评论卡片 | `section` 含 `[data-bv-v="contentItem"]` 且无子 section | `section` 含 `button[class*="16dr7i1-6"]` | — |
| 作者 | `[data-bv-v="contentHeader"] button[class*="16dr7i1-6"]` | `button.bv-rnr-action-bar` | `button[aria-label^="See"]` |
| 标题 | `[data-bv-v="contentHeader"] h3` | — | — |
| 评分 | `[data-bv-v="contentHeader"] [role="img"][aria-label*="out of 5"]`（ARIA） | `span[class*="bm6gry"]` | — |
| 日期 | `[data-bv-v="contentHeader"] span[class*="g3jej5"]` | span 文本匹配 `/\d+ (days\|months\|years) ago/` | — |
| 正文 | `[data-bv-v="contentSummary"].children[0]` | `querySelector('p')` | — |
| 图片 | `[data-bv-v="contentSummary"] img[src*="photos-us.bazaarvoice.com"]` | `.photos-tile img` | `img[src*="photos-us.bazaarvoice.com"]`（兜底） |
| Load More | `button[aria-label*="Load More"]`（ARIA，稳定） | — | — |

### Reviews Accordion 选择器（主 DOM）

| S1 | `[class*="AccordionWrapper"]` > `[class*="Title"]` 含文本 "Reviews" |
|---|---|
| S2 | `[role="region"][aria-label="Section Title"]` 文本为 "Reviews"，向上找 cursor:pointer 祖先 |

## 评论输出状态区分

| 状态 | 输出示例 | 含义 |
|------|----------|------|
| 无评论 | `评论: 无` | `review_count == 0`，产品确实无评论 |
| 成功抓取 | `评论: 5/12 条 (新增 3)` | 有评论且成功抓到部分/全部，显示本次新增数 |
| Shadow DOM 限制 | `评论: 0/2 条 (BV未注入详情数据)` | 有评论但 Shadow DOM 无法获取 |

## 分类页采集

- 产品卡片选择器：`[class*="ItemDetails"] a[href]`
- 翻页：点击 `.iconPagerArrowRight` 的父级 `<a>`
- 分页参数格式：`?page=N&firstResult=(N-1)*pageSize`
- 等待产品列表渲染：`wait.eles_loaded('[class*="ItemDetails"]')` 替代固定 `sleep(3)`

## 站点专属注意事项

- **不要用 DOM class 判断库存**：`out_of_stock_-_hide_atc_button` 是营销 espot 的 class，不代表真正缺货；应使用 JSON-LD `offers.availability`
- **BV 数据是异步加载的**：不能在页面加载后立即提取，需等待 BV 容器和 JSON-LD 注入完成
- **BV 评论在 Shadow DOM 中**：`[data-bv-show="reviews"]` 使用 Shadow DOM，必须通过 `shadowRoot` 访问内部元素，普通 CSS 选择器无法穿透
- **BV Shadow DOM 选择器基于 hash class**：如 `16dr7i1-6`、`bm6gry`、`g3jej5` 等，BV 版本升级可能变化，需注意维护
- **BV 评论去重**：Shadow DOM 中同一评论可能重复渲染（如 featured + normal），用 `author|headline` 组合键去重
- **LOAD MORE 点击后等评论数量变化**：不能用固定 sleep，应检测 section 数量增加，最多等 5 秒
- **评论图片需滚动触发懒加载**：BV 评论图片有两种渲染位置——`[data-bv-v="contentSummary"]` 内和 `.photos-tile` 容器。`.photos-tile` 内的 `<IMG>` 标签需要该 section 在视口内停留才会触发懒加载。批量滚动（BATCH_SIZE=20）在评论数较少时会直接跳到末尾，导致中间 section 的图片来不及加载。解决方案：批量滚动后，额外查找含 `.photos-tile` 但图片未加载的 section，逐个定向滚动（`scrollIntoView({block: 'center'})`）并等待 0.5 秒
- **排除外层 section 容器**：选取评论 section 时必须排除包含子 section 的外层容器（如顶部 "Customer Images and Videos" 轮播所在的 section），否则会把轮播图片误归到第一条评论
- **并行任务必须使用独立浏览器**：`auto_port()` 确保每个 scraper 实例启动独立浏览器进程，否则并行任务共享 `latest_tab` 导致数据错位
- **导航后校验 URL**：`_check_url_match()` 检测实际 URL 是否匹配预期，及时发现重定向或并行干扰
- **SKU 文本用中文冒号**：正则需兼容 `SKU：` 和 `SKU:`，且 SKU 可能含字母（正则 `[\w-]+`）
- **产品 URL 两种格式**：`/shop/en/xxx` 和 `/p/xxx`（后者是规范化后的路径）
