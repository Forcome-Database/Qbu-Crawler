# OpenClaw 集成指南

本目录包含 Qbu-Crawler 在 OpenClaw 中的完整集成配置：MCP 插件、Workspace 文件和分析技能。

## 目录结构

```
server/openclaw/
├── README.md                          ← 本文件（安装指南 + 经验总结）
├── plugin/                            ← MCP 插件（提供 11 个工具的调用能力）
│   ├── index.js                       ← 插件主逻辑（MCP Streamable HTTP 客户端）
│   ├── package.json                   ← 包配置
│   └── openclaw.plugin.json           ← 插件声明
└── workspace/                         ← Workspace 文件（agent 行为配置）
    ├── SOUL.md                        ← 角色设定（每次对话加载）
    ├── TOOLS.md                       ← 工具说明+路由规则+输出规范（每次对话加载）
    └── skills/
        └── qbu-product-data/
            └── SKILL.md               ← 深度分析 SQL 模板（按需加载）
```

## 安装步骤

### 前提条件

- OpenClaw 2026.1.0+
- Qbu-Crawler MCP 服务已启动（`uv run python main.py serve`）

### 第一步：安装 MCP 插件

```bash
# 创建插件目录并复制文件
mkdir -p ~/.openclaw/extensions/mcp-products
cp server/openclaw/plugin/* ~/.openclaw/extensions/mcp-products/
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

> **重要**：endpoint 末尾必须有 `/`，否则会触发 307 重定向导致 406 错误。

### 第三步：安装 Workspace 文件

```bash
# 工具说明和角色设定
cp server/openclaw/workspace/SOUL.md ~/.openclaw/workspace/
cp server/openclaw/workspace/TOOLS.md ~/.openclaw/workspace/

# 深度分析技能
mkdir -p ~/.openclaw/workspace/skills/qbu-product-data
cp server/openclaw/workspace/skills/qbu-product-data/SKILL.md \
   ~/.openclaw/workspace/skills/qbu-product-data/
```

### 第四步：重启验证

```bash
openclaw gateway restart
openclaw doctor
```

应该看到：
```
[plugins] [mcp-products] registered 11 MCP tools against http://...
```

---

## 定时工作流配置

### Cron Job（每日任务提交）

```bash
openclaw cron add --name "daily-scrape-submit" \
  --cron "0 8 * * *" --tz "Asia/Shanghai" \
  --session isolated \
  --message "执行每日爬虫任务提交，使用 daily-scrape-submit 技能" \
  --announce --to "<dingtalk-channel-id>"
```

### Heartbeat（任务监控）

在 `openclaw.json` 中配置：

```json5
{
  agents: {
    defaults: {
      heartbeat: {
        every: "5m",
        lightContext: true,
        target: "none",
        activeHours: {
          start: "07:00",
          end: "23:00",
          timezone: "Asia/Shanghai"
        }
      }
    }
  }
}
```

### 新增 Workspace 文件

安装到 `~/.openclaw/workspace/`：

```bash
# 心跳
cp server/openclaw/workspace/HEARTBEAT.md ~/.openclaw/workspace/

# Skills
for skill in daily-scrape-submit daily-scrape-report csv-management; do
  mkdir -p ~/.openclaw/workspace/skills/$skill
  cp server/openclaw/workspace/skills/$skill/SKILL.md ~/.openclaw/workspace/skills/$skill/
done

# 数据和配置模板
mkdir -p ~/.openclaw/workspace/{data,config,state,reports}
cp server/openclaw/workspace/data/*.csv ~/.openclaw/workspace/data/
cp server/openclaw/workspace/config/email-recipients.txt ~/.openclaw/workspace/config/
cp server/openclaw/workspace/state/active-tasks.json ~/.openclaw/workspace/state/
```

### 新增 Skills 说明

- `daily-scrape-submit` — 每日定时任务提交（Cron Job 使用）
- `daily-scrape-report` — 任务完成汇报（含翻译 + Excel + 邮件）
- `csv-management` — URL/SKU 验证与 CSV 管理

### ownership 字段

products 表新增 `ownership` 字段（`own`/`competitor`），区分自有产品与竞品。
`start_scrape` 和 `start_collect` 工具的 `ownership` 参数为必填。

---

## OpenClaw 架构经验

### Workspace 文件体系

OpenClaw 用以下文件定义 agent 行为，**每次对话都注入到上下文中**（消耗 token）：

- **`SOUL.md`** — 角色设定、人格、语气、边界
- **`AGENTS.md`** — 操作规则、记忆策略、自主行为规范（OpenClaw 自带，一般不改）
- **`TOOLS.md`** — 本地工具说明和使用惯例（**MCP 工具说明放这里**）
- **`USER.md`** — 用户身份和偏好
- **`IDENTITY.md`** — Agent 名称和风格

`skills/` 目录下的技能**按需加载**（agent 决定读取时才消耗 token）。

**关键决策**：
- MCP 工具的基本说明、路由规则、输出格式 → 放 `TOOLS.md`（始终可见）
- 深度分析的 SQL 模板、多步骤工作流 → 放 `skills/`（按需加载，省 token）

### Bootstrap 文件大小限制

- 单个文件最大：`bootstrapMaxChars`（默认 20,000 字符）
- 所有文件合计：`bootstrapTotalMaxChars`（默认 150,000 字符）
- 超出会被截断，所以 TOOLS.md 要控制在合理范围内

### 主 Agent vs 子 Agent

- 主 agent 加载所有 bootstrap 文件：AGENTS.md, SOUL.md, TOOLS.md, IDENTITY.md, USER.md
- 子 agent 只加载 AGENTS.md 和 TOOLS.md
- 所以 MCP 工具说明放 TOOLS.md 确保子 agent 也能使用

---

## MCP 插件开发经验

### plugin 文件结构

OpenClaw 插件需要 3 个文件：

- `openclaw.plugin.json` — 插件声明（id、name、kind、configSchema）
- `package.json` — Node.js 包配置（`"type": "module"` 必须）
- `index.js` — 插件逻辑（`export default { id, register(api) {...} }`）

### 关键约束

1. **`register()` 必须是同步函数** — OpenClaw 不支持 async register，返回 Promise 会被忽略并报警告
2. **plugin id 必须一致** — `openclaw.plugin.json` 的 `id`、`package.json` 的 `name`、`register()` 导出的 `id`、以及 `openclaw.json` 中 `plugins.entries` 的 key 必须全部一致，否则报 id mismatch 警告
3. **插件目录名应与 id 一致** — 放在 `~/.openclaw/extensions/{id}/`

### MCP Streamable HTTP 客户端开发要点

1. **Accept header 必须包含两种类型**：`application/json, text/event-stream`（MCP 协议要求）
2. **SSE 响应解析**：FastMCP 返回 SSE 格式（`text/event-stream`），用 `\n\n` 分割事件
3. **找到匹配响应后立即 `reader.cancel()`** — FastMCP 不会主动关闭 SSE 连接，不 cancel 会导致长连接挂起
4. **流结束时处理剩余 buffer** — `reader.read()` 返回 `{done: true}` 时，buffer 中可能还有未处理的数据，需要补 `\n\n` 触发解析
5. **Session 管理**：保存 `Mcp-Session-Id` header，后续请求带上。session 失效（404）时重新 initialize
6. **notifications/initialized** 通知发送后不需要解析响应体，服务端返回 202

### OpenAI 函数调用 Schema 兼容性

OpenClaw 会将 MCP 工具转换为 OpenAI function calling 格式，以下 JSON Schema 特性会导致错误：

- ❌ `"type": "object"` 没有 `"properties"` 字段 → "object schema missing properties"
- ❌ `"anyOf": [{"type":"string"}, {"type":"null"}]`（Optional 类型）→ OpenAI 不支持
- ❌ `"additionalProperties": false` 在嵌套对象中 → 可能被拒绝

**解决方案**（在 MCP 服务端）：
- 工具参数用简单类型（str, int, float, bool），不用 Optional/Enum
- 返回类型用 `str`（json.dumps），不用 `dict`（避免生成 outputSchema）
- 用默认值代替 None：空字符串 `""` 代替 `None`，`-1` 代替 `None`

**解决方案**（在插件端）：
- 注册工具时手动定义完整的 `parameters` schema，确保每个 `type: "object"` 都有 `properties`
- 或用 `sanitizeSchema()` 函数递归清理从 MCP 获取的 schema

---

## 钉钉渠道排版经验

### 钉钉支持的 Markdown

- ✅ 标题（# ## ### ####）
- ✅ 加粗（**粗体**）
- ✅ 无序列表（- 项目）
- ✅ 有序列表（1. 项目）
- ✅ 嵌套列表
- ✅ 任务列表（- [x] / - [ ]）
- ✅ 引用（> 内容）
- ✅ 行内代码和代码块
- ✅ 链接
- ✅ 分隔线（---）

### 钉钉不支持的 Markdown

- ❌ **表格**（会显示为乱码）
- ❌ 删除线

### 排版最佳实践

- 用**列表 + 加粗**代替表格
- 每个板块用 `###` + emoji 标题隔开
- 评分分布用列表 + `█` 字符可视化
- 产品列表每个产品一个 `###` 小节
- 一段文字不超过 3 行，超过就拆成列表
- 关键数据（价格、评分、数量）始终加粗

---

## 可用工具（11 个）

- **start_scrape** — 提交产品 URL 抓取任务
- **start_collect** — 从分类页采集产品
- **get_task_status** — 查询任务进度
- **list_tasks** — 列出任务记录
- **cancel_task** — 取消任务
- **list_products** — 搜索/筛选产品
- **get_product_detail** — 产品详情
- **query_reviews** — 查询评论
- **get_price_history** — 价格历史
- **get_stats** — 数据统计
- **execute_sql** — 只读 SQL 查询

## 自定义配置

在 `openclaw.json` 的 `plugins.entries.mcp-products.config` 中可配置：

- **endpoint** — MCP 服务地址（默认 `http://8.153.109.16:15087/mcp/`）
- **protocolVersion** — MCP 协议版本（默认 `2025-03-26`）
- **timeoutMs** — 工具调用超时毫秒（默认 `60000`）

## 故障排查

### plugin id mismatch

`openclaw.plugin.json` 的 `id`、`package.json` 的 `name`、`openclaw.json` 的 entry key 必须一致。

### Invalid schema for function

OpenAI 模型不接受某些 JSON Schema 特性，参考上方"Schema 兼容性"章节。

### SSE stream ended before JSON-RPC response

插件解析 SSE 响应时未正确处理流结束。确保 `index.js` 中 `reader.read()` 返回 `done: true` 时处理了剩余 buffer，且匹配到响应后调用了 `reader.cancel()`。

### 307 Temporary Redirect → 406 Not Acceptable

endpoint URL 缺少尾斜杠。`/mcp` 会被重定向到 `/mcp/`，重定向后丢失 Accept header。解决：endpoint 配置为 `http://host:port/mcp/`。

### loaded without install/load-path provenance

手动安装的插件会有此警告，不影响功能。可在 `openclaw.json` 中 `plugins.allow` 添加插件 id 消除。
