# Meat Your Maker 采集规则

## 站点信息

- **域名**：`www.meatyourmaker.com`
- **平台**：Salesforce Commerce Cloud (Demandware)
- **产品 URL 格式**：`/{category}/{subcategory}/{product-name}/{product-id}.html`
- **分类 URL 格式**：`/{category}/{subcategory}/`

## 产品数据提取（DOM，无 JSON-LD Product）

| 字段 | 选择器/方法 | 说明 |
|------|------------|------|
| 名称 | `h1` | 页面标题 |
| SKU | `[data-pid]` 属性 | Demandware 产品 ID |
| 价格 | `.product-price.c-product__price .price-sales` | 限定主产品区域，排除推荐产品 |
| 库存 | `.availability-msg` + `.not-available-div` 互斥可见性 | 两个 div 互斥显示，需同时检查 |
| 评分 | `#bv-jsonld-bvloader-summary` | BV JSON-LD，与 Bass Pro 相同 |
| 评论数 | `#bv-jsonld-bvloader-summary` | aggregateRating.reviewCount |

## 评论提取流程

**关键**：BV 数据仅在 Reviews 区域展开后才开始加载（与 basspro 不同），因此 `scrape()` 中必须先展开再等 BV。

1. `_click_reviews_tab(tab)` — 点击 `div.c-toggler__element` 文本为 "Reviews" 的元素展开评论区
2. `_wait_for_bv_data(tab)` — 展开后轮询等待 `#bv-jsonld-bvloader-summary` 注入（评分摘要）
3. `_wait_for_shadow_root(tab)` — 等待 `[data-bv-show="reviews"]` 的 Shadow DOM 加载
4. `_extract_page_reviews(tab)` — 从当前页 Shadow DOM 提取评论
5. 循环点击 `a.next`（Shadow DOM 内）翻页，每页提取后合并
6. `_process_review_images(reviews)` — 下载评论图片到 MinIO

### Shadow DOM 选择器

均在 `[data-bv-show="reviews"].shadowRoot` 内：

| 元素 | S1（优先） | S2 降级 |
|------|-----------|---------|
| 评论容器 | 有子 section 的外层 section | — |
| 评论卡片 | 容器的 `:scope > section` | — |
| 作者 | `button.bv-rnr-action-bar` | `button[aria-label^="See"]` |
| 标题 | `h3` | — |
| 评分 | `[role="img"][aria-label*="out of 5"]` | — |
| 日期 | `span[class*="g3jej5"]` | span 匹配 `/\d+ (days\|months\|years) ago/` |
| 正文 | 排除 button/div 后第一个长文本 div（>30字符） | — |
| 图片 | `.photos-tile img`（src 含 `bazaarvoice.com`） | — |
| 翻页 | `a.next` / `a.prev`（或 `button.prev` disabled） | — |

### 翻页机制

- 每页替换评论内容（非累积加载）
- 第一页：`button.prev`（disabled）+ `a.next`
- 中间页：`a.prev` + `a.next`
- 最后页：`a.prev`，无 `a.next`
- URL 格式：`?bvstate=pg:N/ct:r`

## 分类页采集

- 产品卡片选择器：`.product-tile a[href$=".html"]`
- 翻页方式：无限滚动（非传统分页）
- 下一页 URL：`.infinite-scroll-placeholder` 的 `data-grid-url` 属性
- 分页参数格式：`?start=N&sz=12&format=page-element`
- 无分页箭头（不同于 Bass Pro 的 `.iconPagerArrowRight`）

## 站点专属注意事项

- **无 JSON-LD Product**：产品数据全部从 DOM 提取，不能复用 basspro 的 JSON-LD 策略
- **Reviews 需要展开**：页面加载后评论区默认折叠，必须先点击 toggler
- **BV 翻页非累积**：与 basspro 的 Load More（累积）不同，每次翻页替换当前评论
- **BV Shadow DOM 无 `data-bv-v`**：不能用 `data-bv-v="contentItem"` 等属性定位，需用 section 层级
- **正文提取用位置关系**：无语义属性标记正文 div，靠排除法找第一个长文本叶子 div
- **价格选择器需限定区域**：页面底部有推荐产品也有 `.price-sales`，必须限定 `.c-product__price` 父级
- **无限滚动的 data-grid-url**：直接 GET 请求返回的是 HTML 片段，不是完整页面
- **必须使用 `normal` 加载模式**：meatyourmaker 的 BV 脚本在 `eager` 模式下无法初始化（`.bv_main_container` 永远不出现），必须覆盖 `_build_options` 使用 `normal` 模式。basspro 可以用 `eager`，这是两站点的关键差异
- **BV 必须展开后才加载**：与 basspro 不同，meatyourmaker 的 BV 脚本在 Reviews toggler 展开后才初始化，`scrape()` 中必须先 `_click_reviews_tab` 再 `_wait_for_bv_data`，否则 BV summary 和 Shadow DOM 永远不会出现
- **toggler 需等待渲染**：`_click_reviews_tab` 必须轮询等待 `.c-toggler__element` 出现再点击，否则 JS 静默失败
- **库存判断用两个互斥 div**：`.availability-msg`（In Stock）和 `.not-available-div`（Out of stock）互斥显示，不能只检查一个的 display 状态
- **无评论产品的 BV 不加载**：部分新产品没有评论时，BV summary 不会注入，`_wait_for_bv_data` 会超时，这是预期行为，评分和评论数保持 None
- **评论翻页等待时间**：当前每页翻页后 `time.sleep(2)`，评论多的产品（396 条）实测可获取约 209 条，可能需要增加等待或检测页面内容变化来提高覆盖率
