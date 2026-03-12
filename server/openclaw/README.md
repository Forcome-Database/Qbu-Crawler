# OpenClaw 集成指南

本目录包含 Qbu-Crawler 在 OpenClaw 中的完整集成配置：MCP 插件、Workspace 文件和分析技能。

## 目录结构

```
server/openclaw/
├── README.md                          ← 本文件（安装指南 + 经验总结）
├── plugin/                            ← MCP 插件（提供 14 个工具的调用能力）
│   ├── index.js                       ← 插件主逻辑（MCP Streamable HTTP 客户端）
│   ├── package.json                   ← 包配置
│   └── openclaw.plugin.json           ← 插件声明
└── workspace/                         ← Workspace 文件（按 OpenClaw 最佳实践编排）
    ├── AGENTS.md                      ← 意图路由 + 工作流 SOP（核心调度文件）
    ├── SOUL.md                        ← 纯身份定义（豆沙）
    ├── TOOLS.md                       ← 工具参数速查（精简版）
    ├── HEARTBEAT.md                   ← 心跳检查清单
    ├── USER.md                        ← 用户信息（时区、语言）
    ├── IDENTITY.md                    ← Agent 身份（豆沙）
    ├── state/
    │   ├── active-tasks.json          ← 定时任务状态（Cron 写入，Heartbeat 读取）
    │   └── adhoc-tasks.json           ← 临时任务状态（主会话写入，Heartbeat 读取）
    ├── config/
    │   └── email-recipients.txt       ← 邮件收件人列表
    ├── data/
    │   ├── sku-list-source.csv        ← 分类页 URL 列表（start_collect 用）
    │   └── sku-product-details.csv    ← 产品详情页 URL 列表（start_scrape 用）
    ├── reports/                       ← Excel 报告输出目录
    └── skills/
        ├── qbu-product-data/
        │   └── SKILL.md               ← 深度分析 SQL 模板（含 ownership 维度）
        ├── daily-scrape-submit/
        │   └── SKILL.md               ← 每日任务提交（Cron Job 阶段 1）
        ├── daily-scrape-report/
        │   └── SKILL.md               ← 任务汇报（调用 generate_report Tool，阶段 3）
        ├── csv-management/
        │   └── SKILL.md               ← URL/SKU 验证与 CSV 管理
        └── output-formats/
            └── SKILL.md               ← 钉钉输出格式模板（所有结构化输出必须参考）
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

### 第二步：在 openclaw.json 中启用插件并开放工具权限

编辑 `~/.openclaw/openclaw.json`，配置插件和工具权限：

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
  },
  "tools": {
    "profile": "coding",
    "alsoAllow": [
      "start_scrape", "start_collect", "get_task_status", "list_tasks", "cancel_task",
      "list_products", "get_product_detail", "query_reviews", "get_price_history",
      "get_stats", "execute_sql", "generate_report", "trigger_translate", "get_translate_status"
    ]
  }
}
```

> **重要**：
> - endpoint 末尾必须有 `/`，否则会触发 307 重定向导致 406 错误
> - 必须用 **`alsoAllow`**（追加模式），不能用 `allow`（替换模式会覆盖 coding profile 的核心工具集）
> - OpenClaw 不原生支持远程 MCP 客户端（[Issue #29053](https://github.com/openclaw/openclaw/issues/29053)），通过插件桥接是推荐做法

### 第三步：安装 Workspace 文件

```bash
# 核心文件
cp server/openclaw/workspace/AGENTS.md ~/.openclaw/workspace/
cp server/openclaw/workspace/TOOLS.md ~/.openclaw/workspace/
cp server/openclaw/workspace/SOUL.md ~/.openclaw/workspace/
cp server/openclaw/workspace/HEARTBEAT.md ~/.openclaw/workspace/

# 所有 Skills
for skill in daily-scrape-submit daily-scrape-report csv-management qbu-product-data output-formats; do
  mkdir -p ~/.openclaw/workspace/skills/$skill
  cp server/openclaw/workspace/skills/$skill/SKILL.md ~/.openclaw/workspace/skills/$skill/
done

# 数据和配置模板
mkdir -p ~/.openclaw/workspace/{data,config,state,reports}
cp server/openclaw/workspace/data/*.csv ~/.openclaw/workspace/data/
cp server/openclaw/workspace/config/email-recipients.txt ~/.openclaw/workspace/config/
echo '{}' > ~/.openclaw/workspace/state/active-tasks.json
echo '{}' > ~/.openclaw/workspace/state/adhoc-tasks.json
```

### 第四步：重启验证

```bash
openclaw gateway restart
openclaw doctor
```

应该看到：
```
[plugins] [mcp-products] registered 14 MCP tools against http://...
```

---

## 定时工作流配置

### Cron Job（每日任务提交）

```bash
openclaw cron add --name "daily-scrape-submit" --cron "0 8 * * *" --tz "Asia/Shanghai" --session isolated --message "读取 skills/daily-scrape-submit/SKILL.md 技能并严格执行。你的 MCP 工具（start_scrape, start_collect）已可直接调用，不要探索环境或寻找替代方案。" --announce --to "<dingtalk-channel-id>"
```

> **注意**：一行写完，不要换行，避免 `\n` 混入 message。

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

### 注意事项

- Cron Job 中的 `<dingtalk-channel-id>` 需替换为实际钉钉群会话 ID，格式为 `chat:cidXXXXXX==`
- 获取群 ID：在钉钉群 @机器人 发消息后，执行 `openclaw logs --follow --json | grep conversationId`
- HEARTBEAT.md 中的群 ID 也需要一并替换
- `openclaw.json` 中需添加 `"cron": {"enabled": true}` 以启用定时任务
- Cron job 删除用 `openclaw cron remove <jobId>`（先 `openclaw cron list` 获取 ID）

---

## 可用工具（14 个）

### 任务管理
- **start_scrape** — 提交产品 URL 抓取任务
- **start_collect** — 从分类页采集产品
- **get_task_status** — 查询任务进度
- **list_tasks** — 列出任务记录
- **cancel_task** — 取消任务

### 数据查询
- **list_products** — 搜索/筛选产品
- **get_product_detail** — 产品详情（仅接受 product_id/url/sku，无 site 参数）
- **query_reviews** — 查询评论
- **get_price_history** — 价格历史
- **get_stats** — 数据统计
- **execute_sql** — 只读 SQL 查询

### 报告翻译
- **generate_report** — 生成报告（查询 + Excel + 邮件，服务端程序化执行）
- **trigger_translate** — 手动触发翻译线程
- **get_translate_status** — 查询翻译进度

---

## 更新日志

### 2026-03-12：tools.allow → alsoAllow 修复插件工具不可用

**问题**：群聊中 agent 无法调用 MCP 插件工具（start_scrape、generate_report 等），说"拿不到抓取提交能力"。私聊正常。MCP 服务端无任何请求到达。

**根因**：`tools.allow` 是**替换模式**——它替换 profile 的工具集而非追加（[Issue #2377](https://github.com/openclaw/openclaw/issues/2377)）。配置 `tools.profile: "coding"` + `tools.allow: [14个MCP工具]` 的实际效果是：agent **只有** MCP 工具，coding profile 的核心工具（read/write/bash）被替换掉，导致工具系统异常。

**修复**：将 `tools.allow` 改为 `tools.alsoAllow`（追加模式，[PR #1742](https://github.com/openclaw/openclaw/issues/2377)）：
```json
"tools": {
  "profile": "coding",
  "alsoAllow": ["start_scrape", "start_collect", ...]
}
```
`alsoAllow` = coding 核心工具 + MCP 插件工具，全部可用。

**备选方案**：如果 agent 只服务单一用途，可直接 `tools.profile: "full"` 移除所有限制。

**关键教训**：
- OpenClaw 不原生支持远程 MCP 客户端（[Issue #29053](https://github.com/openclaw/openclaw/issues/29053)），插件桥接是推荐方式
- 插件注册的工具受 `tools.profile` 过滤，不会自动绕过
- `tools.allow` 和 `tools.alsoAllow` 语义完全不同——前者替换，后者追加
- 2026.3.2 起默认 profile 从 `full` 改为 `coding`（[Issue #40239](https://github.com/openclaw/openclaw/issues/40239)），升级后需注意

---

### 2026-03-12：Agent 可靠性优化 + 插件补全

**问题**：Cron isolated session 间歇性偏离——agent 不按 skill 执行，改为探索代码库寻找 CLI 入口。

**根因分析**：
1. **Skill 路径隐式**：AGENTS.md 未写明 `skills/{name}/SKILL.md` 路径约定，agent 靠猜
2. **工具列表不在 AGENTS.md**：isolated session 冷启动时 agent 不知道有哪些 MCP 工具可用
3. **AGENTS.md 信噪比低**：108 行混合了所有场景的规则，注意力稀释
4. **TOOLS.md 过长**：253 行每次加载，200 行输出模板大多数场景用不到
5. **意图分类缺失**：无决策树，agent 不知道该进哪个流程
6. **插件缺工具**：trigger_translate 和 get_translate_status 未注册，AGENTS.md 声称可用但调用必失败

**改动内容**：

AGENTS.md 重构：
- 新增「可用工具」列表（首位，锚定 MCP 工具，封堵 CLI 探索）
- 新增「技能路径约定」（显式写明 `skills/{name}/SKILL.md`）
- 新增「输出规则」（通用规则，所有结构化输出必须按 output-formats 格式化）
- 新增「意图识别」决策树（6 种意图 + 上下文切换协议）
- 意图 1 从"消息含 URL"改为"用户意图是抓取"，避免数据查询含 URL 时误触发抓取
- Isolated session 快速路径：指定技能名 → 直接读取执行，跳过初始化
- 临时任务追加语义明确：新任务追加到 tasks 数组，submitted_at/reply_to 更新为最新值
- 安全边界中"不暴露技术细节"移至输出规则（单一规则源）

TOOLS.md 瘦身：
- 从 253 行减至 ~60 行
- 输出格式模板拆到 `skills/output-formats/SKILL.md`（按需加载）
- 新增统一时间戳规范（上海时间，无时区后缀）

插件补全：
- 新增 trigger_translate、get_translate_status 两个工具定义（12 → 14 个）
- get_product_detail 描述加 `additionalProperties: false` + "Accepts ONLY these parameters"，防止跨工具参数幻觉（agent 曾传入不存在的 `site` 参数）
- generate_report 描述中 "UTC" → "Shanghai" 与服务端保持一致

技能文件更新：
- `daily-scrape-submit`：新增工具锚定 + 禁止探索声明
- `daily-scrape-report`：输出引用 output-formats
- `csv-management`：新增 URL 去重检查
- `output-formats`：**新增**，包含所有钉钉输出格式模板

HEARTBEAT.md：
- Cron 消息内联工具列表
- Reporting 异常记录到 memory 日志

Cron job 消息优化：
- 包含显式文件路径 `skills/daily-scrape-submit/SKILL.md`
- 声明工具已可用 + 负向约束"不要探索"
- 一行写完避免换行符混入

### 2026-03-12：Excel 报告评论 sheet 新增 SKU 列

- SQL 查询新增 `p.sku AS product_sku`
- 评论 sheet 列顺序：产品名称 → **SKU** → 评论人 → 标题原文 → 内容原文 → 标题中文 → 内容中文 → 打分 → 评论时间 → 照片
- 图片列索引动态计算（`len(review_headers)`），无硬编码

---

## OpenClaw 架构经验

### Workspace 文件体系

OpenClaw 用以下文件定义 agent 行为，**每次对话都注入到上下文中**（消耗 token）：

- **`AGENTS.md`** — 意图路由 + 工作流 SOP。**最关键的文件**，所有流程的入口
- **`SOUL.md`** — 纯身份定义（个性、价值观、沟通风格），不含操作规则
- **`TOOLS.md`** — 工具参数速查（精简，~60 行），不含输出模板
- **`HEARTBEAT.md`** — 极简心跳检查清单，用 `IMPORTANT:` 标记触发命令
- **`USER.md`** — 用户信息（时区、语言偏好）
- **`IDENTITY.md`** — Agent 身份（名称、风格、emoji）

**设计原则**：
- **分层注意力**：AGENTS.md 路由（做什么）→ TOOLS.md 参数（怎么调）→ Skills 执行（怎么做）
- AGENTS.md 中工具列表置顶，确保 isolated session 冷启动时第一时间看到
- 输出格式模板放 skill（按需加载），不放 TOOLS.md（每次加载太重）
- HEARTBEAT.md 尽量少步骤（"Cheap Checks First"原则）
- Skill 步骤不超过 5 步，关键步骤用 `IMPORTANT:` 标记
- 生产环境删除 BOOTSTRAP.md

`skills/` 目录下的技能**按需加载**（agent 决定读取时才消耗 token）。所有 skill 必须有 frontmatter（name + description）。

### Agent 可靠性经验

**Isolated session 可靠性**：
- Cron 消息中包含显式 skill 文件路径 + 可用工具列表 + 负向约束
- AGENTS.md 提供 isolated session 快速路径（跳过初始化直接执行 skill）
- Skill 内重复声明工具可用（belt and suspenders）

**意图分类**：
- 基于用户意图而非消息内容分类（"含 URL"≠"要抓取"）
- 上下文切换时重新按意图进入流程，可从上文推断参数但 ownership 需确认

**工具参数幻觉防御**：
- 插件 tool description 中用"Accepts ONLY"排他性描述
- `additionalProperties: false` 在 JSON Schema 层面拒绝多余参数
- 不同工具的参数集差异要在描述中明确提示

**输出格式一致性**：
- AGENTS.md 中一条通用规则："确保已读取 output-formats 技能"
- 措辞用"确保已读取"而非"先读取"——首次必读，上下文中已有则不重复读

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
- 对只接受特定参数的工具加 `additionalProperties: false`，防止参数幻觉

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

### 插件工具注册成功但 agent 调不了（"拿不到能力"）

插件日志显示 `registered 14 MCP tools` 但 agent 说没有工具。原因是 `tools.allow` 是替换模式，会覆盖 profile 的核心工具集。改用 `tools.alsoAllow`（追加模式）。参考更新日志 2026-03-12。

诊断命令：
```bash
# 检查 allow vs alsoAllow
cat ~/.openclaw/openclaw.json | grep -E "allow|alsoAllow"
# 检查是否有 unknown entries 警告
openclaw logs 2>&1 | grep "unknown entries"
```

### Agent 在 isolated session 中探索代码库而非执行 skill

Cron 消息中缺少显式 skill 路径或工具锚定。确保消息包含：1) skill 文件路径 2) 可用工具名 3) "不要探索"负向约束。参考更新日志 2026-03-12。

### get_product_detail 传入不存在的 site 参数

Agent 从其他工具（list_products、query_reviews）推断 get_product_detail 也有 site 参数。已在插件中加 `additionalProperties: false` + 排他性描述修复。

---

## 工作流设计经验

### AGENTS.md 作为意图路由器

**问题**：AGENTS.md 作为单一 SOP 文件试图覆盖所有场景，信噪比低，agent 注意力稀释。

**解决**：AGENTS.md 重构为**意图路由器**——先分类用户意图（抓取/查询/任务操作/邮件/CSV/自由对话），再路由到对应流程。详细执行逻辑下放到 skill 中。

### Skill 与 TOOLS.md 的职责划分

- **AGENTS.md**：意图路由（什么意图 → 什么流程）、工具列表、全局规则
- **TOOLS.md**：参数速查。**每次对话都加载**，必须精简（~60 行）
- **Skill**：具体流程指令（step-by-step）、SQL 模板、输出格式模板。**按需加载**，可以详细

### 三阶段定时工作流的选型理由

- **阶段 1（Cron → isolated）**：定时提交，独立 session 不影响用户对话
- **阶段 2（Heartbeat → main session, lightContext）**：轻量检查，无事则 `HEARTBEAT_OK` 静默，省 token
- **阶段 3（Cron → isolated, 由 Heartbeat 触发）**：重活（翻译 + Excel + 邮件）放独立 session，不阻塞用户

**不选"单一 Cron 内联轮询"的原因**：爬虫任务可能运行 30 分钟+，isolated session 有 timeoutSeconds 限制，且持续轮询浪费 token。

**不选"Heartbeat 内直接汇报"的原因**：翻译几千条评论 + 生成 Excel + 发邮件很耗时，放在 main session 会阻塞用户交互。

### ownership 字段设计要点

- `ownership` 在 **task_manager 层注入**（`product["ownership"] = task.params["ownership"]`），scrapers 不感知
- MCP tools 层做值校验（只接受 `own` / `competitor`），防止外部调用传入无效值
- CLI 路径（`main.py`）用 `setdefault("competitor")` 兜底，保持向后兼容
- products 表用 `NOT NULL DEFAULT 'competitor'` 做迁移兼容，但应用层不依赖默认值

---

## 爬虫稳定性经验（高评论量产品）

### 问题现象

当产品有 1000+ 条评论时：
1. Load More 加载全部评论 → Shadow DOM 节点爆炸
2. `querySelectorAll('section')` 越来越慢
3. 单次 JS 遍历全部评论超过 30 秒 → DrissionPage 超时
4. 浏览器内存耗尽 → 连接断开 → 后续所有产品级联失败

### 解决方案

| 措施 | 配置/代码 | 效果 |
|------|----------|------|
| 评论加载上限 | `config.MAX_REVIEWS = 200` | 防止 DOM 膨胀 |
| 分批滚动 | 每 20 个 section 滚一次，`block: 'end'` | 15 秒 vs 原 200 秒 |
| 分批提取 | 每 50 个 section 一次 JS 调用 | 单次 1-2 秒 vs 原 30 秒+ |
| 异常容错 | try/except 包裹加载/滚动阶段 | 超时不丢失已加载数据 |

### 配置建议

- `MAX_REVIEWS = 200`：覆盖大多数分析需求，浏览器稳定
- `MAX_REVIEWS = 500`：需要更多评论时，配合 `RESTART_EVERY = 20` 降低崩溃风险
- `MAX_REVIEWS = 0`：不限制（不推荐，仅在明确知道评论量不大时使用）
