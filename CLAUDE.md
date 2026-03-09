# Qbu-Crawler — 多站点产品数据爬虫

## 项目概述

基于 DrissionPage 的多站点产品数据爬虫框架，抓取产品详情（名称、SKU、价格、库存、评分、评论）并存储到 SQLite。

当前支持站点：
- **Bass Pro Shops** — 规则文档：`docs/rules/basspro.md`
- **Meat Your Maker** — 规则文档：`docs/rules/meatyourmaker.md`

## 技术栈

- **Python 3.10+**，依赖管理使用 **uv**（`pyproject.toml` + `uv.lock`）
- **DrissionPage** — 浏览器自动化（绕过反爬 403）
- **SQLite** — 数据存储（`data/products.db`）
- **MinIO** — 评论图片对象存储
- **python-dotenv** — 环境变量管理（`.env`）

## 项目结构

```
Qbu-Crawler/
├── CLAUDE.md
├── pyproject.toml
├── .env / .env.example
├── config.py          # 配置（数据库、浏览器、MinIO、等待/重试/反爬参数）
├── models.py          # SQLite 数据层（products + product_snapshots + reviews 表）
├── minio_client.py    # MinIO 图片上传客户端
├── main.py            # CLI 入口（多站点路由 + 并行采集）
├── scrapers/
│   ├── __init__.py    # 工厂函数 get_scraper() + SITE_MAP
│   ├── base.py        # BaseScraper 基类（浏览器管理 + 通用工具）
│   ├── basspro.py     # BassProScraper — Bass Pro Shops
│   └── meatyourmaker.py  # MeatYourMakerScraper — Meat Your Maker
├── data/
│   └── products.db
└── docs/
    ├── rules/         # 各站点采集规则
    ├── features/      # 需求文档
    ├── plans/         # 实施计划
    └── devlogs/       # 开发日志
```

## 常用命令

```bash
# 安装依赖
uv sync

# 抓取单个产品（自动识别站点）
uv run python main.py <product-url>

# 从文件批量抓取（支持混合站点 URL，自动分组并行）
uv run python main.py -f urls.txt

# 从分类页自动采集并抓取（可限制页数）
uv run python main.py -c <category-url>
uv run python main.py -c <category-url> 3

# 多站点分类页并行采集
uv run python main.py -c <basspro-category> -c <meat-category>

# 查询数据库（按站点）
uv run python -c "import sqlite3; c=sqlite3.connect('data/products.db'); print(c.execute('SELECT site,name,sku,price,rating FROM products').fetchall())"
```

## 多站点架构

采用**轻量继承 + 独立实现**模式：

- `BaseScraper`（`scrapers/base.py`）：仅管理浏览器生命周期和通用工具（类型转换、随机延迟、MinIO 图片上传），不定义抽象方法
- 各站点子类完全独立实现 `scrape()` 和 `collect_product_urls()`，互不影响
- `scrapers/__init__.py`：工厂函数 `get_scraper(url)` 根据 URL 域名自动路由到对应子类
- `main.py`：支持单站点直接运行和多站点 `ThreadPoolExecutor` 并行（每站点独立浏览器实例）
- 子类可覆盖 `_build_options()` 定制浏览器选项（如 meatyourmaker 需要 `normal` 加载模式）

新增站点：创建 `scrapers/{site}.py` → `SITE_MAP` 加一行 → `docs/rules/{site}.md`

## 通用配置项（config.py）

| 配置 | 默认值 | 说明 |
|------|--------|------|
| `HEADLESS` | `False` | 无头模式 |
| `PAGE_LOAD_TIMEOUT` | `30` | 页面加载超时（秒） |
| `LOAD_MODE` | `"eager"` | 加载策略：eager=DOM就绪即停，不等图片 |
| `NO_IMAGES` | `True` | 禁止加载图片，减少带宽 |
| `RETRY_TIMES` | `3` | 页面加载失败重试次数 |
| `RETRY_INTERVAL` | `2` | 重试间隔（秒） |
| `REQUEST_DELAY` | `(1, 3)` | 请求间随机延迟范围（秒），`None` 禁用 |
| `RESTART_EVERY` | `50` | 每 N 个产品重启浏览器防内存泄漏，`0` 禁用 |

### MinIO 配置（.env）

| 配置 | 说明 |
|------|------|
| `MINIO_ENDPOINT` | MinIO 服务地址 |
| `MINIO_PORT` | MinIO 端口 |
| `MINIO_USE_SSL` | 是否使用 SSL |
| `MINIO_ACCESS_KEY` | 访问密钥 |
| `MINIO_SECRET_KEY` | 秘密密钥 |
| `MINIO_BUCKET` | 存储桶名称 |
| `MINIO_PUBLIC_URL` | 公开访问域名 |

## 通用架构决策

### 数据存储策略

- **products** 表：UPSERT，始终反映最新状态（当前快照）
- **product_snapshots** 表：每次抓取 INSERT 一条，记录价格/库存/评分/评论数变化历史，用于趋势分析
- **reviews** 表：增量 INSERT，用 `product_id + author + headline + body_hash` 联合唯一键去重，`body_hash` 为 `MD5(body)[:16]`，防止 Anonymous 同标题评论误去重；已存在评论如有新图片则回填 `images` 字段（解决首次无图入库后图片丢失问题）

### 稳定性机制

- **内置重试**：`ChromiumOptions.set_retry(times=3, interval=2)` 处理网络抖动
- **标签页复用**：使用 `latest_tab` 复用同一标签页，避免频繁开关
- **定期重启**：每 N 个产品重启浏览器，防止内存泄漏（`RESTART_EVERY` 配置）
- **随机延迟**：请求间随机等待（`REQUEST_DELAY` 配置），降低反爬检测
- **智能点击**：翻页使用 `click(by_js=None)`，优先模拟，被遮挡自动改 JS

### 图片存储

评论图片下载后上传到 MinIO，路径格式 `images/YYYY-MM/{url_md5_hash}.{ext}`，存储桶 `qbu-crawler`。

## DrissionPage 通用开发注意事项

- **不要用 `ele.text` 读取 `<script>` 标签**：DrissionPage 对 script 标签的 `.text` 可能返回空，必须用 `tab.run_js()` 通过 `s.textContent` 提取
- **不要用共享数据库连接 + `executescript()`**：`executescript()` 会破坏连接的事务状态，导致后续操作出现 FOREIGN KEY 错误。使用独立连接（每次操作开关）
- **不要每次 scrape 创建/关闭标签页**：`new_tab()` + `close()` 开销大且不必要，用 `latest_tab` 复用即可
- **不要用 `wait.eles_loaded()` 等动态注入的 script 标签**：对动态注入的 `<script>` 标签不可靠，必须用 `tab.run_js()` 轮询 `document.querySelector()`
- **不要用 `wait.url_change()` 等翻页**：该方法需要 `text` 参数（URL 片段），翻页时 URL 变化不可预测，应使用 `wait.doc_loaded()`
- **NO_IMAGES=True 不影响图片 URL 获取**：禁用图片只阻止浏览器下载图片资源，滚动触发懒加载后 img 标签和 src 属性仍会渲染
- **lazy image 必须逐个 section 慢滚动**：`loading="lazy"` 的图片需要元素在视口中停留足够时间才触发，`forEach + scrollIntoView` 同步执行太快无效，必须用 Python 循环逐个滚动 + `time.sleep(0.3)` 延时
- **`eager` 加载模式可能阻止第三方脚本初始化**：某些站点（如 SFCC/Demandware 平台）的 BV 脚本在 `eager` 模式下无法初始化，需改用 `normal` 模式。各站点子类可通过覆盖 `_build_options()` 定制

## 工作流程规范

### 文档同步要求

每次重构或优化经验证通过后，**必须**同步更新相关文档和记录：

1. **更新站点规则**：如果改动涉及站点专属逻辑（选择器、提取策略等），更新 `docs/rules/{站点}.md`
2. **更新 CLAUDE.md**：如果改动涉及通用架构、配置项或 DrissionPage 经验，更新本文件
3. **记录开发日志**：在 `docs/devlogs/` 中记录实现细节和踩坑经验
4. **更新项目结构**：如果新增/删除/重命名了文件，更新本文件的项目结构图

### 经验沉淀机制

当发现具有**通用性**且**重要**的爬虫开发经验时（如 DrissionPage 新的坑、反爬通用技巧、浏览器自动化最佳实践等），应主动询问用户是否需要更新 `drissionpage` 技能文档，以便跨项目复用。

判断标准：
- **通用性**：不局限于某个站点，其他爬虫项目也会遇到
- **重要性**：能避免重大踩坑或显著提升效率

## 文档规范

项目文档存放在 `docs/` 目录下：

- **`docs/rules/`** — 各站点采集规则。命名：`{站点标识}.md`（如 `basspro.md`）
- **`docs/features/`** — 需求文档。命名：`F{序号}-{简述}.md`（如 `F001-basic-scraper.md`）
- **`docs/plans/`** — 实施计划。命名：`P{序号}-{简述}.md`（如 `P001-basic-scraper.md`），与 feature 序号对应
- **`docs/devlogs/`** — 开发日志。命名：`D{序号}-{简述}.md`（如 `D001-basic-scraper.md`），记录实现细节和踩坑
