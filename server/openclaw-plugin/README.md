# MCP Products — OpenClaw 插件安装指南

## 前提条件

- OpenClaw 2026.1.0+
- Qbu-Crawler MCP 服务已启动（`uv run python main.py serve`）

## 安装步骤

### 第一步：安装 MCP 插件（提供工具调用能力）

```bash
# 创建插件目录
mkdir -p ~/.openclaw/extensions/mcp-products

# 复制 3 个文件到插件目录
cp index.js ~/.openclaw/extensions/mcp-products/
cp package.json ~/.openclaw/extensions/mcp-products/
cp openclaw.plugin.json ~/.openclaw/extensions/mcp-products/
```

### 第二步：在 openclaw.json 中启用插件

编辑 `~/.openclaw/openclaw.json`，在 `plugins.entries` 中添加：

```json
{
  "plugins": {
    "entries": {
      "mcp-products": {
        "enabled": true,
        "config": {
          "endpoint": "http://你的服务器IP:端口/mcp/"
        }
      }
    }
  }
}
```

> 注意：endpoint 末尾必须有 `/`

### 第三步：安装 Skill（教 agent 怎么用工具）

```bash
cp qbu-product-data.md ~/.openclaw/skills/
```

### 第四步：重启 OpenClaw

```bash
openclaw gateway restart
```

### 第五步：验证

```bash
openclaw doctor
```

应该看到：
```
[plugins] [mcp-products] registered 11 MCP tools against http://...
```

## 自定义配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `endpoint` | `http://8.153.109.16:15087/mcp/` | MCP 服务地址 |
| `protocolVersion` | `2025-03-26` | MCP 协议版本 |
| `timeoutMs` | `60000` | 工具调用超时（毫秒） |

## 文件清单

```
~/.openclaw/
├── extensions/
│   └── mcp-products/          ← MCP 插件（3 个文件）
│       ├── index.js           ← 插件主逻辑
│       ├── package.json       ← 包配置
│       └── openclaw.plugin.json ← 插件声明
├── skills/
│   └── qbu-product-data.md   ← Agent 行为指导
└── openclaw.json              ← 需要启用 mcp-products 插件
```

## 可用工具（11 个）

| 工具 | 功能 |
|------|------|
| start_scrape | 提交产品 URL 抓取任务 |
| start_collect | 从分类页采集产品 |
| get_task_status | 查询任务进度 |
| list_tasks | 列出任务记录 |
| cancel_task | 取消任务 |
| list_products | 搜索/筛选产品 |
| get_product_detail | 产品详情 |
| query_reviews | 查询评论 |
| get_price_history | 价格历史 |
| get_stats | 数据统计 |
| execute_sql | 只读 SQL 查询 |
