# Bass Pro Shops Product Scraper

## 项目概述

基于 DrissionPage 的 Bass Pro Shops 产品数据爬虫，抓取产品详情（名称、SKU、价格、库存、评分、评论）并存储到 SQLite。

## 技术栈

- **Python 3.10+**，依赖管理使用 **uv**（`pyproject.toml` + `uv.lock`）
- **DrissionPage** — 浏览器自动化（绕过反爬 403）
- **SQLite** — 数据存储（`data/products.db`）

## 项目结构

```
pachong/
├── CLAUDE.md          # 本文件 - 项目指南
├── pyproject.toml     # 项目配置和依赖
├── config.py          # 配置（数据库路径、浏览器选项、等待/重试/反爬参数）
├── models.py          # SQLite 数据层（products + reviews 表）
├── scraper.py         # 爬虫核心（BassProScraper 类）
├── main.py            # CLI 入口
├── data/              # 数据目录（.gitignore）
│   └── products.db    # SQLite 数据库
└── docs/              # 项目文档
    ├── features/      # 需求文档
    ├── plans/         # 实施计划
    └── devlogs/       # 开发日志和踩坑记录
```

## 常用命令

```bash
# 安装依赖
uv sync

# 抓取单个产品
uv run python main.py https://www.basspro.com/p/product-slug

# 从文件批量抓取
uv run python main.py -f urls.txt

# 从分类页自动采集并抓取（可限制页数）
uv run python main.py -c https://www.basspro.com/l/category-slug
uv run python main.py -c https://www.basspro.com/l/category-slug 3

# 查询数据库
uv run python -c "import sqlite3; c=sqlite3.connect('data/products.db'); print(c.execute('SELECT name,sku,price,rating FROM products').fetchall())"
```

## 配置项（config.py）

| 配置 | 默认值 | 说明 |
|------|--------|------|
| `HEADLESS` | `False` | 无头模式 |
| `PAGE_LOAD_TIMEOUT` | `30` | 页面加载超时（秒） |
| `LOAD_MODE` | `"eager"` | 加载策略：eager=DOM就绪即停，不等图片 |
| `NO_IMAGES` | `True` | 禁止加载图片，减少带宽 |
| `RETRY_TIMES` | `3` | 页面加载失败重试次数 |
| `RETRY_INTERVAL` | `2` | 重试间隔（秒） |
| `BV_WAIT_TIMEOUT` | `10` | BV 数据等待超时（秒） |
| `BV_POLL_INTERVAL` | `0.5` | BV 数据轮询间隔（秒） |
| `REQUEST_DELAY` | `(1, 3)` | 请求间随机延迟范围（秒），`None` 禁用 |
| `RESTART_EVERY` | `50` | 每 N 个产品重启浏览器防内存泄漏，`0` 禁用 |

## 核心架构决策

### 数据提取策略（优先级）

1. **JSON-LD** (`script[type="application/ld+json"]`) — 主要数据源，通过 `tab.run_js()` 提取
2. **Bazaarvoice JSON-LD** (`#bv-jsonld-bvloader-summary`, `#bv-jsonld-reviews-data`) — 评分和评论
3. **DOM 元素** — 兜底方案（如 `h1` 取名称、`text:SKU` 取 SKU）

### 页面类型处理

- **`Product`** 类型：直接取 `name`、`sku`、`offers.price`
- **`ProductGroup`** 类型：取 group 的 `name` 和 `productGroupID` 作为 SKU，第一个 variant 的 `offers.price`

### 等待策略

使用 `eager` 加载模式（DOM 就绪即停，不等图片等资源），配合分阶段等待：

1. `tab.get(url)` — eager 模式下 DOM 就绪自动返回
2. `tab.wait.ele_displayed('tag:h1')` — 等主内容渲染
3. `tab.ele('css:.bv_main_container')` — 等 BV 组件容器加载
4. `_wait_for_bv_data(tab)` — JS 轮询等待 BV JSON-LD 注入（见下文）

**BV 数据轮询机制**（`_wait_for_bv_data`）：

BV 异步注入两个 `<script>` 标签，时序不确定且不稳定：
- `#bv-jsonld-bvloader-summary`（评分摘要，通常先注入）
- `#bv-jsonld-reviews-data`（评论详情，后注入，且不一定会注入）

用 JS 轮询（每 0.5 秒）同时检测两个元素，`reviews-data` 出现立即停止。`wait.eles_loaded()` 对动态注入的 `<script>` 标签不可靠，必须用轮询。

### 稳定性机制

- **内置重试**：`ChromiumOptions.set_retry(times=3, interval=2)` 处理网络抖动
- **标签页复用**：使用 `latest_tab` 复用同一标签页，避免频繁开关
- **定期重启**：每 50 个产品重启浏览器，防止内存泄漏（`RESTART_EVERY` 配置）
- **随机延迟**：请求间 1-3 秒随机等待（`REQUEST_DELAY` 配置），降低反爬检测
- **智能点击**：翻页使用 `click(by_js=None)`，优先模拟，被遮挡自动改 JS

### 评论输出状态区分

| 状态 | 输出示例 | 含义 |
|------|----------|------|
| 无评论 | `评论: 无` | `review_count == 0`，产品确实无评论 |
| 成功抓取 | `评论: 5/12 条` | 有评论且成功抓到部分/全部 |
| BV 限制 | `评论: 0/2 条 (BV未注入详情数据)` | 有评论但 BV 未注入 `reviews-data` |

### 分类页采集

- 产品卡片选择器：`[class*="ItemDetails"] a[href]`
- 翻页：点击 `.iconPagerArrowRight` 的父级 `<a>`
- 分页参数格式：`?page=N&firstResult=(N-1)*pageSize`
- 等待产品列表渲染：`wait.eles_loaded('[class*="ItemDetails"]')` 替代固定 `sleep(3)`

## 开发注意事项

- **不要用 `ele.text` 读取 `<script>` 标签**：DrissionPage 对 script 标签的 `.text` 可能返回空，必须用 `tab.run_js()` 通过 `s.textContent` 提取
- **不要用 DOM class 判断库存**：`out_of_stock_-_hide_atc_button` 是营销 espot 的 class，不代表真正缺货；应使用 JSON-LD `offers.availability`
- **BV 数据是异步加载的**：不能在页面加载后立即提取，需等待 BV 容器和 JSON-LD 注入完成
- **BV reviews-data 注入不稳定**：`#bv-jsonld-reviews-data` 的注入时序不确定，有时出现有时不出现，必须用 JS 轮询方式等待。BV 通过 easyXDM 跨域 iframe 通信获取数据，无法通过网络拦截获取
- **BV 评论详情有阈值**：评论数极少的产品，BV 可能不注入 `reviews-data`（已知限制）。此时仅能获取评分和评论数（来自 `bvloader-summary`），无法获取评论正文
- **不要用 `wait.eles_loaded()` 等 BV script 标签**：对动态注入的 `<script>` 标签不可靠，必须用 `tab.run_js()` 轮询 `document.querySelector()`
- **不要用 `wait.url_change()` 等翻页**：该方法需要 `text` 参数（URL 片段），翻页时 URL 变化不可预测，应使用 `wait.doc_loaded()`
- **不要用共享数据库连接 + `executescript()`**：`executescript()` 会破坏连接的事务状态，导致后续操作出现 FOREIGN KEY 错误。使用独立连接（每次操作开关）
- **不要每次 scrape 创建/关闭标签页**：`new_tab()` + `close()` 开销大且不必要，用 `latest_tab` 复用即可
- **SKU 文本用中文冒号**：正则需兼容 `SKU：` 和 `SKU:`，且 SKU 可能含字母（正则 `[\w-]+`）
- **产品 URL 两种格式**：`/shop/en/xxx` 和 `/p/xxx`（后者是规范化后的路径）

## 文档规范

项目文档存放在 `docs/` 目录下，分三个子目录：

- **`docs/features/`** — 需求文档。命名：`F{序号}-{简述}.md`（如 `F001-basic-scraper.md`）
- **`docs/plans/`** — 实施计划。命名：`P{序号}-{简述}.md`（如 `P001-basic-scraper.md`），与 feature 序号对应
- **`docs/devlogs/`** — 开发日志。命名：`D{序号}-{简述}.md`（如 `D001-basic-scraper.md`），记录实现细节和踩坑
