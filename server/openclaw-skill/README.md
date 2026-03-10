# Qbu-Crawler OpenClaw Skill

产品数据分析助手 — 用于 [OpenClaw](https://github.com/anthropics/openclaw) 的 Agent 技能插件。

通过 MCP 协议连接 Qbu-Crawler 产品数据服务，提供爬虫任务管理、产品搜索、评论分析、价格追踪等能力。

## 功能概览

- 🕷️ **爬虫任务管理** — 提交抓取任务、查看进度、取消任务
- 🔍 **产品搜索浏览** — 多维度筛选产品（站点、价格、库存、评分）
- 💬 **评论分析** — 评分分布、情感洞察、关键词搜索
- 📈 **价格追踪** — 价格历史趋势、波动分析
- 📊 **数据报告** — 统计概览、竞品对比、数据巡检

## 安装

### 前置条件

1. Qbu-Crawler 服务已启动（MCP 端点可用）：

```bash
cd /path/to/Qbu-Crawler
uv run python main.py serve
```

默认服务地址：`http://localhost:8000`，MCP 端点：`http://localhost:8000/mcp`

2. OpenClaw 已安装并可正常运行。

### 安装技能

将技能目录复制（或软链接）到 OpenClaw 的 skills 目录：

```bash
# 方式一：复制
cp -r /path/to/Qbu-Crawler/server/openclaw-skill /path/to/openclaw/skills/qbu-product-data

# 方式二：软链接（推荐，便于同步更新）
ln -s /path/to/Qbu-Crawler/server/openclaw-skill /path/to/openclaw/skills/qbu-product-data
```

### 配置 MCP 服务器连接

在 OpenClaw 的 MCP 配置中添加 Qbu-Crawler 服务：

```json
{
  "mcpServers": {
    "qbu-crawler": {
      "url": "http://localhost:8000/mcp",
      "transport": "streamable-http"
    }
  }
}
```

如果服务启用了 API Key 认证，在请求头中添加：

```json
{
  "mcpServers": {
    "qbu-crawler": {
      "url": "http://localhost:8000/mcp",
      "transport": "streamable-http",
      "headers": {
        "Authorization": "Bearer YOUR_API_KEY"
      }
    }
  }
}
```

## 文件结构

```
openclaw-skill/
├── SKILL.md                          # 主技能文档（Agent 指令）
├── README.md                         # 安装说明（本文件）
└── references/
    ├── tool-routing.md               # 工具路由详细逻辑
    ├── response-formats.md           # 响应格式模板
    └── analysis-queries.md           # 预置分析 SQL 查询
```

## 可用 MCP 工具

| 工具 | 用途 |
|------|------|
| `start_scrape` | 按 URL 列表抓取产品 |
| `start_collect` | 从分类页采集并抓取 |
| `get_task_status` | 查询任务状态 |
| `list_tasks` | 列出任务记录 |
| `cancel_task` | 取消任务 |
| `list_products` | 搜索筛选产品 |
| `get_product_detail` | 产品详情 |
| `query_reviews` | 查询评论 |
| `get_price_history` | 价格历史 |
| `get_stats` | 数据统计 |
| `execute_sql` | 只读 SQL 查询（内部使用，不暴露给用户） |

## 支持站点

- **Bass Pro Shops** (basspro) — www.basspro.com
- **Meat Your Maker** (meatyourmaker) — www.meatyourmaker.com
