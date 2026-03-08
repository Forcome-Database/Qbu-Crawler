# P001 - 基础爬虫实施计划

对应需求：[F001](../features/F001-basic-scraper.md)

## 实施步骤

### Step 1: 项目初始化
- 创建 `pyproject.toml`，配置 uv 依赖管理
- 添加 DrissionPage 依赖
- `uv sync` 安装依赖

### Step 2: 配置模块 (config.py)
- 数据库文件路径：`data/products.db`
- 自动创建 data 目录
- DrissionPage 浏览器选项（headless 开关、超时时间）

### Step 3: 数据库模块 (models.py)
- `init_db()` 建表（products + reviews）
- `save_product()` UPSERT（以 url 为唯一键）
- `save_reviews()` 先删旧评论再批量插入

### Step 4: 爬虫核心 (scraper.py)
- `BassProScraper` 类，管理 Chromium 浏览器生命周期
- `scrape(url)` 方法：打开页面 → 等待加载 → 提取数据 → 返回结构化字典
- 数据提取优先使用 JSON-LD，DOM 作为兜底

### Step 5: CLI 入口 (main.py)
- 解析命令行参数
- 初始化数据库 → 创建爬虫 → 遍历 URL → 保存数据 → 打印摘要

## 验证方式

运行示例 URL 并检查数据库内容。
