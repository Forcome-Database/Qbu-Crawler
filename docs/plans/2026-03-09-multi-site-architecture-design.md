# 多站点爬虫架构设计

## 背景

项目从 Bass Pro Shops 单站点爬虫扩展为多站点框架，第二个站点为 meatyourmaker.com。设计原则：**可扩展性、便利性 > 复用**。

## 架构方案：轻量继承 + 独立实现（方案 C）

### 目录结构

```
Qbu-Crawler/
├── config.py              # 通用配置 + 各站点专属配置（分 section）
├── models.py              # 数据层（products 加 site 字段）
├── minio_client.py        # MinIO 图片上传（不变）
├── main.py                # CLI 入口（URL 域名自动路由 + 多站点并行）
├── scrapers/
│   ├── __init__.py        # get_scraper_by_site() 工厂函数 + SCRAPER_MAP
│   ├── base.py            # BaseScraper — 浏览器管理 + 通用工具
│   ├── basspro.py         # BassProScraper(BaseScraper)
│   └── meatyourmaker.py   # MeatYourMakerScraper(BaseScraper)
└── docs/rules/
    ├── basspro.md
    └── meatyourmaker.md
```

### BaseScraper 基类（scrapers/base.py）

仅包含：
- 浏览器构建（`_build_options`）、重启（`_maybe_restart_browser`）、关闭（`close`）
- 通用工具：`_to_float`、`_to_int`、`_random_delay`、`_increment_and_delay`
- **不定义抽象方法**，不强制接口

### 数据层变更（models.py）

- `products` 表新增 `site TEXT NOT NULL DEFAULT 'basspro'`
- 迁移兼容：`ALTER TABLE products ADD COLUMN site ...`，现有数据自动回填 `basspro`
- `save_product(data)` 接口中 data dict 新增 `site` 字段
- `product_snapshots` 和 `reviews` 不加 site，通过 product_id 外键关联

### CLI 与多站点并行（main.py）

- 输入 URL 按域名分组
- 单站点：当前进程直接跑
- 多站点：ThreadPoolExecutor 并行，每站点一个 scraper 实例（独立浏览器）
- `-c` 支持多次指定不同站点的分类页

### MeatYourMakerScraper 要点

**产品数据提取（无 JSON-LD Product）**：
- 名称: `h1`
- SKU: `[data-pid]` 属性
- 价格: `.c-product__price .price-sales`（限定主产品区域）
- 库存: `.availability-msg` 可见性判断
- 评分: `#bv-jsonld-bvloader-summary`（同 basspro）

**评论提取（与 basspro 最大差异）**：
- 展开: 点击 `div.c-toggler__element` 文本 "Reviews"
- 翻页: 循环点击 Shadow DOM 内 `a.next`（每页替换，非累积）
- 正文: 位置优先（排除 header 后第一个长文本 div），hash class 降级
- 评论卡片: 外层容器 section > 子 section（无 `data-bv-v`）

**分类页采集**：
- 产品卡片: `.product-tile a[href$=".html"]`
- 翻页: 请求 `.infinite-scroll-placeholder` 的 `data-grid-url`（`?start=N&sz=12&format=page-element`）

### 两站点 BV 共性（不抽共享模块，各自内联）

| 选择器 | 说明 |
|--------|------|
| `#bv-jsonld-bvloader-summary` | 评分摘要 JSON-LD |
| `[data-bv-show="reviews"].shadowRoot` | 评论 Shadow DOM 宿主 |
| `button.bv-rnr-action-bar` | 作者 |
| `h3` | 标题 |
| `[role="img"][aria-label*="out of 5"]` | 评分 |
| `span[class*="g3jej5"]` | 日期 |
| `.photos-tile img` | 评论图片 |
