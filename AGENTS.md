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
- **openpyxl** — Excel 报告生成
- **Jinja2 + matplotlib + Playwright** — HTML/CSS 模板、SVG 图表和 PDF 导出
- **openai SDK** — LLM 翻译（OpenAI 兼容 API）

## 项目结构

```
Qbu-Crawler/
├── AGENTS.md
├── pyproject.toml
├── .env / .env.example
├── config.py          # 配置（数据库、浏览器、MinIO、等待/重试/反爬参数）
├── models.py          # SQLite 数据层（products + product_snapshots + reviews + tasks 表）
├── minio_client.py    # MinIO 图片上传客户端
├── main.py            # CLI 入口（多站点路由 + 并行采集 + serve 子命令）
├── server/
│   ├── __init__.py
│   ├── app.py              # FastAPI + FastMCP 组装 + Uvicorn 启动
│   ├── report.py           # 报告生成（数据查询 + LLM翻译 + Excel + 邮件）
│   ├── report_analytics.py # 日报分析层（标签分类 + analytics JSON 组装）
│   ├── report_pdf.py       # HTML/CSS 模板渲染 + SVG 图表 + Playwright PDF 导出
│   ├── report_templates/   # 日报 PDF 模板和 print CSS
│   ├── task_manager.py     # 爬虫任务生命周期管理（线程池 + 取消 + 持久化）
│   ├── translator.py       # 后台翻译守护线程（DB-as-Queue + LLM 批量翻译）
│   ├── api/
│   │   ├── __init__.py
│   │   ├── auth.py         # API Key 认证中间件
│   │   ├── tasks.py        # 任务管理 endpoints
│   │   └── products.py     # 数据查询 endpoints
│   ├── mcp/
│   │   ├── __init__.py
│   │   ├── tools.py        # MCP Tools（任务操作 + 数据查询 + SQL + 报告生成）
│   │   └── resources.py    # MCP Resources（数据库元数据）
│   └── openclaw/
│       ├── README.md
│       ├── plugin/                 # MCP 插件
│       └── workspace/
│           ├── AGENTS.md           # 操作规范（URL路由、ownership、安全边界）
│           ├── SOUL.md             # 身份定义（豆沙）
│           ├── TOOLS.md            # 工具参数参考 + 输出格式模板
│           ├── HEARTBEAT.md        # 心跳检查清单
│           ├── USER.md             # 用户信息
│           ├── IDENTITY.md         # Agent 身份
│           ├── state/              # 运行时状态
│           ├── config/             # 邮件收件人等配置
│           ├── reports/            # Excel 报告输出
│           ├── data/               # CSV（分类页+产品页 URL）
│           └── skills/
│               ├── qbu-product-data/    # 深度数据分析 SQL 模板
│               ├── daily-scrape-submit/ # 定时任务提交
│               ├── daily-scrape-report/ # 任务完成汇报
│               └── csv-management/      # URL/SKU 管理
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

### LLM 翻译配置（.env）

| 配置 | 默认值 | 说明 |
|------|--------|------|
| `LLM_API_BASE` | （必填） | OpenAI 兼容 API 地址 |
| `LLM_API_KEY` | （必填） | API 密钥 |
| `LLM_MODEL` | `gpt-4o-mini` | 翻译模型 |
| `LLM_TRANSLATE_BATCH_SIZE` | `20` | 每批翻译评论数 |

### 翻译 Worker 配置（.env）

| 配置 | 默认值 | 说明 |
|------|--------|------|
| `TRANSLATE_INTERVAL` | `60` | 翻译轮询间隔（秒） |
| `TRANSLATE_MAX_RETRIES` | `3` | 单条评论最大重试次数，超过标记 skipped |
| `TRANSLATE_WORKERS` | `3` | 翻译并发线程数，每轮取 batch_size × workers 条评论并行翻译 |

### 邮件 SMTP 配置（.env）

| 配置 | 默认值 | 说明 |
|------|--------|------|
| `SMTP_HOST` | （必填） | SMTP 服务器地址 |
| `SMTP_PORT` | `587` | SMTP 端口 |
| `SMTP_USER` | — | SMTP 登录用户 |
| `SMTP_PASSWORD` | — | SMTP 登录密码 |
| `SMTP_FROM` | — | 发件人地址 |
| `SMTP_USE_SSL` | `false` | 使用 SMTP_SSL（true）还是 STARTTLS（false） |

### 报告配置（.env）

| 配置 | 默认值 | 说明 |
|------|--------|------|
| `REPORT_DIR` | `data/reports` | Excel / PDF / analytics JSON 报告输出目录 |
| `REPORT_LABEL_MODE` | `rule` | 日报标签模式：`rule` 或 `hybrid` |
| `REPORT_PDF_TIMEOUT_SECONDS` | `60` | Playwright 导出 PDF 超时（秒） |
| `REPORT_PDF_FONT_FAMILY` | `Noto Sans CJK SC` | 日报 PDF 默认中文字体 |

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
- MCP Tools 提供语义化查询（list_products, query_reviews 等）+ 只读 SQL + 报告生成（generate_report）
- `generate_report` Tool：查询新增数据（含已翻译的中文）→ openpyxl 生成 Excel → smtplib 发送邮件，翻译由后台线程自动完成
- `report_snapshot` 的 full report 链路扩展为：snapshot → analytics JSON → Excel → PDF → 多附件邮件；`report_pdf.py` 只负责本地模板渲染和导出，不吞系统边界错误
- PDF 运行前必须执行 `uv run playwright install chromium`，Linux 部署机还必须安装统一中文字体；如果 PDF 导出失败，workflow 层必须把 run 状态改为 `needs_attention`，并把 `report_phase` 回退到 `fast_sent`
- `TranslationWorker` 守护线程：DB-as-Queue 模式，轮询未翻译评论 → LLM 批量翻译 → 持久化到 reviews 表，与爬虫并行执行
- MCP Resources 暴露表结构元数据（`db://schema/{table}`），提升 LLM 查询准确率

### 报表语义治理（2026-04-23）

- 顶层语义字段固定为 `report_semantics`、`is_bootstrap`、`change_digest`、`trend_digest`
- `report_semantics` 只允许 `bootstrap`（首次建档/基线期）和 `incremental`（增量期）
- 顶层 `kpis` 是唯一允许给 HTML / 邮件 / Excel 展示的 KPI 来源；`cumulative_kpis`、`window`、`snapshot` 只作为分析中间态，不能直接拿去拼展示文案
- `change_digest` 是 `今日变化` 的唯一输入；`trend_digest` 是 `变化趋势` 的唯一输入
- `window.reviews_count` 只表示本次 run 实际入库评论数，不能解释成“今日新增评论”
- `bootstrap` 下必须展示“监控起点 / 首次建档 / 当前截面”语义，禁止出现“今日新增 / 较昨日 / 较上期”类措辞
- `今日变化` 入口常驻，但 `bootstrap` 下展示监控起点态，`incremental + 无显著变化` 下展示 `empty_state`
- `fresh_review_count` 基于评论发布时间（`date_published_parsed` / `date_published`）按近 30 天口径计算；价格、评分、库存、评论总数等产品状态趋势基于 `scraped_at`
- `backfill_dominant` 阈值固定为 `historical_backfill_count / ingested_review_count >= 0.7`
- 真实生产报告目录以 `C:\Users\User\Desktop\QBU\reports` 为准；旧拷贝路径 `C:\Users\leo\Desktop\pachong` 只用于参考，artifact 解析必须兼容绝对路径失效后的回退查找
- `report_user_contract` 是 HTML / Excel / 邮件展示层的用户语义契约；用户可见的 KPI、行动建议、问题诊断、竞品启示、bootstrap 摘要和 delivery 状态应优先消费该字段，旧 analytics 字段只作为兼容 fallback
- `report_common.normalize_deep_report_analytics()` 只能挂载缺少 snapshot 的临时 contract；最终渲染入口必须用真实 snapshot 刷新 `report_user_contract.contract_context`
- LLM 只允许改写 contract evidence pack 中已锁定的事实，不能自行扩大产品集合、证据评论 ID 或风险口径

### OpenClaw 定时工作流

当前采用“**服务内嵌调度 + 确定性工作流**”架构：
1. **Crawler Service（`qbu-crawler serve`）**：启动 HTTP API / MCP，同时带起 translator、notifier、workflow worker 和 `DailySchedulerWorker`
2. **DailySchedulerWorker（每日定时，embedded）**：按 `.env` 中的 `DAILY_SCHEDULER_TIME` 检查是否到点；到点后直接读取 CSV，并调用 `submit_daily_run()` 创建当日 workflow run
3. **WorkflowWorker（后台推进）**：处理 stale task reconcile、报表阶段推进和 run 状态流转；定时提交是否已经跑过由 `workflow_runs.trigger_key` 幂等控制

临时任务追踪：`start_scrape`/`start_collect` 传入 `reply_to` 参数，服务端自动持久化到 tasks 表（`reply_to` + `notified_at` 列）。通知链路以 `notification_outbox` 为准，避免把 hook/HTTP 成功误记成“已送达”。`Heartbeat` 仅用于轻量巡检和 AI sidecar，不再承担每日主调度。

Workspace 文件体系：
- `AGENTS.md` — 操作规范 SOP（硬规则前置 + 步骤自检 + URL 路由 + 安全边界）
- `SOUL.md` — 纯身份定义（豆沙），不含操作规则
- `TOOLS.md` — 工具参数参考 + 服务端能力概览 + 输出格式模板（钉钉 Markdown 规范）
- `HEARTBEAT.md` — 心跳检查清单（巡检 translation / workflow / notification 异常）
- `USER.md` / `IDENTITY.md` — 用户和 agent 身份信息

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

- **attach 后的 `get_tabs()` / `new_tab()` / `latest_tab.url` 也可能无超时卡死**：`Chromium(port)` 握手成功不代表后续 tab 级 CDP 调用一定健康，尤其是用户数据目录启动、会话恢复出旧标签时。对这些调用要加临时 socket 超时，避免 scraper 构造阶段永远挂在白板
- **不要默认把真实 Chrome 的 `Preferences` / `Local State` seed 到爬虫 profile**：这类文件会带入启动页、会话恢复、扩展状态等“个人浏览器状态”。爬虫只需要 `Cookies` 继承反爬 cookie，默认应做成 cookie jar，而不是半个真实 profile
- **不要用 `ele.text` 读取 `<script>` 标签**：DrissionPage 对 script 标签的 `.text` 可能返回空，必须用 `tab.run_js()` 通过 `s.textContent` 提取
- **不要用共享数据库连接 + `executescript()`**：`executescript()` 会破坏连接的事务状态，导致后续操作出现 FOREIGN KEY 错误。使用独立连接（每次操作开关）
- **不要每次 scrape 创建/关闭标签页**：`new_tab()` + `close()` 开销大且不必要，用 `latest_tab` 复用即可
- **清理会话恢复出来的多标签时，必须先新建一个 `about:blank` 再关旧标签**：DrissionPage 的 `latest_tab` 对应 `tab_ids[0]`，直接关闭旧 tabs 可能把当前 page target 一起关掉，随后访问 `latest_tab.url` 会报 `The connection to the page has been disconnected`
- **不要用 `wait.eles_loaded()` 等动态注入的 script 标签**：对动态注入的 `<script>` 标签不可靠，必须用 `tab.run_js()` 轮询 `document.querySelector()`
- **不要用 `wait.url_change()` 等翻页**：该方法需要 `text` 参数（URL 片段），翻页时 URL 变化不可预测，应使用 `wait.doc_loaded()`
- **NO_IMAGES=True 不影响图片 URL 获取**：禁用图片只阻止浏览器下载图片资源，滚动触发懒加载后 img 标签和 src 属性仍会渲染
- **lazy image 必须批量滚动而非逐个**：`loading="lazy"` 的图片需要元素在视口中停留足够时间才触发。逐个 `scrollIntoView` 在评论数超过 200 时会导致 JS 超时和视口抽搐。改用每 20 个 section 批量滚动一次（`block: 'end'` 单向向下），1000 条评论从 200 秒降到 15 秒
- **大量评论会导致浏览器崩溃**：1000+ 条评论全部加载到 Shadow DOM 后，DOM 节点爆炸导致 `querySelectorAll` 变慢、JS 执行超时（30 秒限制），最终浏览器进程内存耗尽崩溃，后续所有产品都失败。必须用 `MAX_REVIEWS` 限制加载数量
- **Shadow DOM 大量节点提取必须分批**：在 Shadow DOM 中一次性遍历 1000+ section 提取数据（每个做多次 querySelector + 正则匹配）会超过 DrissionPage 的 30 秒 JS 超时。改用每批 50 个 section 分批执行，Python 端做跨批次去重
- **`eager` 加载模式可能阻止第三方脚本初始化**：某些站点（如 SFCC/Demandware 平台）的 BV 脚本在 `eager` 模式下无法初始化，需改用 `normal` 模式。各站点子类可通过覆盖 `_build_options()` 定制
- **批量滚动可能跳过中间元素的懒加载**：`scrollIntoView` 批量滚动（如每 20 个跳一次）在元素总数少于批大小时，会一步跳到末尾，中间元素一闪而过无法触发懒加载。需要额外做一轮定向滚动，逐个滚动到含懒加载内容但未加载的元素
- **`Chromium()` 默认共享浏览器进程**：DrissionPage 的 `Chromium()` 默认连接到同一端口（9222）的浏览器进程。多线程并行创建多个 scraper 实例时，所有实例共享同一个浏览器和标签页，导致 `tab.get()` 竞争、数据错位。**必须在 `ChromiumOptions` 中调用 `auto_port()`** 让每个实例使用独立端口和独立浏览器进程

## 工作流程规范

### 文档同步要求

每次重构或优化经验证通过后，**必须**同步更新相关文档和记录：

1. **更新站点规则**：如果改动涉及站点专属逻辑（选择器、提取策略等），更新 `docs/rules/{站点}.md`
2. **更新 AGENTS.md**：如果改动涉及通用架构、配置项或 DrissionPage 经验，更新本文件
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

## 2026-03-29 结构增量

本次 OpenClaw 混合自动化重构新增的核心文件和目录：

- `qbu_crawler/server/notifier.py` — outbox worker 和 OpenClaw bridge sender
- `qbu_crawler/server/workflows.py` — daily workflow orchestration 和 reconcile
- `qbu_crawler/server/report_snapshot.py` — immutable snapshot + fast/full report helpers
- `qbu_crawler/server/runtime.py` — translator / notifier / workflow worker 的统一生命周期
- `qbu_crawler/server/openclaw/bridge/app.py` — OpenClaw Host 上的 hardened notify bridge
- `qbu_crawler/server/workflows.py::DailySchedulerWorker` — crawler-host 内嵌 daily scheduler
- `deploy/openclaw/` — OpenClaw host 的 `openclaw.json` 模板、sync 脚本、bridge service

## 2026-04-23 报表治理增量

本次“今日变化 / 变化趋势”治理相关的核心文件和目录：

- `qbu_crawler/server/report_snapshot.py` — artifact resolver、`change_digest` 构建和 full email 渲染收口
- `qbu_crawler/server/report_analytics.py` — 顶层 `report_semantics` / `trend_digest` 统一输出
- `qbu_crawler/server/report_common.py` — 归一化透传顶层 `kpis`、`change_digest`、`trend_digest`
- `qbu_crawler/server/report_llm.py` — `bootstrap` 语义守卫与 deterministic fallback
- `qbu_crawler/server/report.py` — governed Excel 导出，新增 `今日变化` sheet 与双态“本次新增”列
- `qbu_crawler/server/report_templates/daily_report_v3.html.j2` — 顶层 `今日变化 / 变化趋势` tab
- `qbu_crawler/server/report_templates/daily_report_v3.js` — 趋势页 `周 / 月 / 年` 与四维度切换
- `qbu_crawler/server/report_templates/daily_report_v3.css` — `今日变化 / 变化趋势` 的布局和状态样式
- `qbu_crawler/server/report_templates/email_full.html.j2` — 邮件只消费顶层 `kpis` 与 `change_digest`
- `tests/test_metric_semantics.py` — 时间口径与 `change_digest` 指标语义回归
- `tests/test_v3_excel.py` — `今日变化` / `趋势数据` / “本次新增”契约回归
- `tests/test_v3_mode_semantics.py` — bootstrap / incremental 邮件模式语义回归

## 2026-04-28 测试7 P1 报表契约治理增量

- `qbu_crawler/server/report_contract.py` — 独立构建 `report_user_contract.v1`，收口 metric definitions、evidence pack、LLM copy merge、竞品启示、bootstrap digest 和 delivery contract
- `qbu_crawler/server/report_common.py` — 归一化阶段挂载临时 contract，并保留已有 contract-only 字段
- `qbu_crawler/server/report_html.py` — HTML 最终渲染前用真实 snapshot 刷新 contract，并同步诊断卡、heatmap、行动建议兼容字段
- `qbu_crawler/server/report.py` — Excel / 邮件优先消费 contract 的行动建议、竞品启示和 KPI
- `tests/server/test_report_contract.py` — contract builder、指标定义、证据包、竞品启示、bootstrap digest、delivery 语义回归
- `tests/server/test_report_contract_llm.py` — LLM evidence-only prompt 和 copy merge 校验回归
- `tests/server/test_report_contract_renderers.py` — HTML / Excel / 邮件 contract-only 消费回归
- `tests/server/test_test7_artifact_replay.py` 与 `tests/fixtures/report_replay/` — 测试7脱敏最小 artifact replay 防回归
