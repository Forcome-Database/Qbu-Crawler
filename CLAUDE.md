# Qbu-Crawler — 多站点产品数据爬虫

## 项目概述

基于 DrissionPage 的多站点产品数据爬虫框架，抓取产品详情（名称、SKU、价格、库存、评分、评论）并存储到 SQLite。支持通过 HTTP API 和 MCP 协议远程管理爬虫任务和查询数据。

当前支持站点：
- **Bass Pro Shops** — 规则文档：`docs/rules/basspro.md`
- **Meat Your Maker** — 规则文档：`docs/rules/meatyourmaker.md`

## 技术栈

- **Python 3.10+**，依赖管理使用 **uv**（`pyproject.toml` + `uv.lock`）
- **DrissionPage** — 浏览器自动化（绕过反爬 403）
- **SQLite** — 数据存储（`data/products.db`）
- **MinIO** — 评论图片对象存储
- **python-dotenv** — 环境变量管理（`.env`）
- **FastAPI + Uvicorn** — HTTP API 服务
- **FastMCP** — MCP 协议服务（Streamable HTTP 传输）

## 项目结构

```
Qbu-Crawler/
├── CLAUDE.md
├── pyproject.toml
├── .env / .env.example
├── config.py          # 配置（数据库、浏览器、MinIO、等待/重试/反爬参数）
├── models.py          # SQLite 数据层（products + product_snapshots + reviews + tasks 表）
├── minio_client.py    # MinIO 图片上传客户端
├── main.py            # CLI 入口（多站点路由 + 并行采集 + serve 子命令）
├── server/
│   ├── __init__.py
│   ├── app.py              # FastAPI + FastMCP 组装 + Uvicorn 启动
│   ├── task_manager.py     # 爬虫任务生命周期管理（线程池 + 取消 + 持久化）
│   ├── api/
│   │   ├── __init__.py
│   │   ├── auth.py         # API Key 认证中间件
│   │   ├── tasks.py        # 任务管理 endpoints
│   │   └── products.py     # 数据查询 endpoints
│   ├── mcp/
│   │   ├── __init__.py
│   │   ├── tools.py        # MCP Tools（任务操作 + 数据查询 + SQL）
│   │   └── resources.py    # MCP Resources（数据库元数据）
│   └── openclaw/
│       ├── README.md
│       ├── plugin/                 # MCP 插件
│       └── workspace/
│           ├── SOUL.md
│           ├── TOOLS.md
│           ├── HEARTBEAT.md        # 心跳检查清单
│           ├── state/              # 运行时状态
│           ├── config/             # 邮件收件人等配置
│           ├── reports/            # Excel 报告输出
│           ├── data/               # CSV（分类页+产品页 URL）
│           └── skills/
│               ├── qbu-product-data/
│               ├── daily-scrape-submit/
│               ├── daily-scrape-report/
│               └── csv-management/
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

# 启动 HTTP API + MCP 服务
uv run python main.py serve
uv run python main.py serve --host 0.0.0.0 --port 9000

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
| `MAX_REVIEWS` | `200` | 单产品最多加载评论数，`0` 不限（大量评论会导致浏览器崩溃） |

### 服务器配置（.env）

| 配置 | 默认值 | 说明 |
|------|--------|------|
| `SERVER_HOST` | `0.0.0.0` | 服务监听地址 |
| `SERVER_PORT` | `8000` | 服务监听端口 |
| `API_KEY` | （必填） | HTTP API 认证密钥 |
| `MAX_WORKERS` | `3` | 爬虫任务线程池大小 |
| `SQL_QUERY_TIMEOUT` | `5` | execute_sql 超时（秒） |
| `SQL_QUERY_MAX_ROWS` | `500` | execute_sql 最大返回行数 |

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
- **tasks** 表：记录通过 API/MCP 提交的爬虫任务历史，params/progress/result 为 JSON 字段
- **products.ownership**：产品归属字段，值为 `own`（自有）或 `competitor`（竞品），通过任务参数传入，爬虫不感知

### HTTP API + MCP 服务架构

单进程 ASGI 服务，`main.py serve` 启动：
- **FastAPI** 处理 `/api/*`（RESTful，Bearer Token 认证）
- **FastMCP** 挂载到 `/mcp`（Streamable HTTP 传输）
- **TaskManager** 单例，HTTP 和 MCP 共享，管理爬虫任务生命周期
- 爬虫在 `ThreadPoolExecutor` 中同步执行，支持 URL 粒度取消
- MCP Tools 提供语义化查询（list_products, query_reviews 等）+ 只读 SQL
- MCP Resources 暴露表结构元数据（`db://schema/{table}`），提升 LLM 查询准确率

### OpenClaw 定时工作流

三阶段架构：
1. **Cron Job（每日定时，isolated）**：读取 CSV → 提交 start_scrape/start_collect → 存 task_id 到 state/active-tasks.json → DingTalk 通知
2. **Heartbeat（每 5 分钟，main session，lightContext）**：检查 active-tasks.json → 轮询 get_task_status → 全部完成则触发阶段 3
3. **Cron Job（一次性，isolated）**：查新增数据 → 翻译评论 → xlsx 生成 Excel → himalaya 发邮件 → DingTalk 汇报 → 清除状态

CSV 文件存放在 OpenClaw workspace `~/.openclaw/workspace/data/`，与项目 `data/`（products.db）物理分离。

### 稳定性机制

- **内置重试**：`ChromiumOptions.set_retry(times=3, interval=2)` 处理网络抖动
- **标签页复用**：使用 `latest_tab` 复用同一标签页，避免频繁开关
- **定期重启**：每 N 个产品重启浏览器，防止内存泄漏（`RESTART_EVERY` 配置）
- **随机延迟**：请求间随机等待（`REQUEST_DELAY` 配置），降低反爬检测
- **智能点击**：翻页使用 `click(by_js=None)`，优先模拟，被遮挡自动改 JS
- **评论加载上限**：`MAX_REVIEWS` 限制单产品最多加载 200 条评论，防止 DOM 膨胀导致 JS 超时和浏览器崩溃
- **分批提取 + 分批滚动**：评论提取每批 50 个 section，滚动每批 20 个，避免单次 JS 调用超时
- **评论异常容错**：评论加载/滚动阶段的异常不会导致整个产品抓取失败，会尝试提取已加载的评论

### 图片存储

评论图片下载后上传到 MinIO，路径格式 `images/YYYY-MM/{url_md5_hash}.{ext}`，存储桶 `qbu-crawler`。

## DrissionPage 通用开发注意事项

- **不要用 `ele.text` 读取 `<script>` 标签**：DrissionPage 对 script 标签的 `.text` 可能返回空，必须用 `tab.run_js()` 通过 `s.textContent` 提取
- **不要用共享数据库连接 + `executescript()`**：`executescript()` 会破坏连接的事务状态，导致后续操作出现 FOREIGN KEY 错误。使用独立连接（每次操作开关）
- **不要每次 scrape 创建/关闭标签页**：`new_tab()` + `close()` 开销大且不必要，用 `latest_tab` 复用即可
- **不要用 `wait.eles_loaded()` 等动态注入的 script 标签**：对动态注入的 `<script>` 标签不可靠，必须用 `tab.run_js()` 轮询 `document.querySelector()`
- **不要用 `wait.url_change()` 等翻页**：该方法需要 `text` 参数（URL 片段），翻页时 URL 变化不可预测，应使用 `wait.doc_loaded()`
- **NO_IMAGES=True 不影响图片 URL 获取**：禁用图片只阻止浏览器下载图片资源，滚动触发懒加载后 img 标签和 src 属性仍会渲染
- **lazy image 必须批量滚动而非逐个**：`loading="lazy"` 的图片需要元素在视口中停留足够时间才触发。逐个 `scrollIntoView` 在评论数超过 200 时会导致 JS 超时和视口抽搐。改用每 20 个 section 批量滚动一次（`block: 'end'` 单向向下），1000 条评论从 200 秒降到 15 秒
- **大量评论会导致浏览器崩溃**：1000+ 条评论全部加载到 Shadow DOM 后，DOM 节点爆炸导致 `querySelectorAll` 变慢、JS 执行超时（30 秒限制），最终浏览器进程内存耗尽崩溃，后续所有产品都失败。必须用 `MAX_REVIEWS` 限制加载数量
- **Shadow DOM 大量节点提取必须分批**：在 Shadow DOM 中一次性遍历 1000+ section 提取数据（每个做多次 querySelector + 正则匹配）会超过 DrissionPage 的 30 秒 JS 超时。改用每批 50 个 section 分批执行，Python 端做跨批次去重
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
