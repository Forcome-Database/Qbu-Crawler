# OpenClaw 定时工作流 + 产品归属字段 设计文档

> 日期：2026-03-10
> 状态：已确认

## 概述

为 Qbu-Crawler 项目新增四项能力：

1. **产品归属字段**：区分自有产品与竞品（`own` / `competitor`）
2. **URL/SKU 验证与 CSV 管理**：OpenClaw agent 验证 URL 后写入 CSV
3. **定时爬虫工作流**：三阶段（Cron 提交 → Heartbeat 监控 → Cron 汇报）
4. **邮件通知 + Excel 报告**：任务完成后生成 Excel 并发送邮件

全部工作流由 OpenClaw Agent 闭环完成，服务端不新增 API。

---

## 模块一：数据库 ownership 字段

### 表结构变更

`products` 表新增列：

```sql
ownership TEXT NOT NULL  -- 值: 'own' | 'competitor'
```

迁移策略：`init_db()` 中用 `ALTER TABLE ADD COLUMN ... DEFAULT 'competitor'`（仅迁移用，应用层不依赖默认值）。

### models.py 变更

- `save_product(data)`：`data` dict 必须包含 `ownership`，INSERT 和 UPDATE 都写入
- `query_products()`：增加 `ownership` 可选过滤参数（`allowed_sorts` 暂不增加 `ownership`，按 ownership 过滤而非排序）
- `query_reviews()`：增加 `ownership` 可选过滤参数（JOIN products 已存在，只需加 WHERE 条件）
- `get_stats()`：返回值增加 `by_ownership` 分组统计（`own` / `competitor` 各自的产品数、评论数、均价、均分）

### MCP Tools 变更

| Tool | 变更 |
|------|------|
| `start_scrape` | 新增 `ownership: str` 必填参数 |
| `start_collect` | 新增 `ownership: str` 必填参数 |
| `list_products` | 新增 `ownership: str` 可选过滤 |
| `get_product_detail` | 返回结果包含 ownership |
| `query_reviews` | 新增 `ownership: str` 可选过滤（JOIN products） |
| `get_stats` | 按 ownership 分组统计 |
| `get_price_history` | 无变更 |
| `execute_sql` | 无变更 |

### HTTP API 变更

- `GET /api/products`：新增 `ownership` query 参数
- `GET /api/products/{id}`：返回包含 ownership
- `POST /api/tasks/scrape`：body 新增 `ownership` 必填
- `POST /api/tasks/collect`：body 新增 `ownership` 必填

### task_manager.py 变更

- `_run_scrape()`：在调用 `models.save_product(product)` 前，先执行 `product["ownership"] = task.params["ownership"]`，将 ownership 从任务参数注入产品数据。爬虫返回的 data 不含 ownership（scrapers 不感知），必须在 task runner 层注入。
- `_run_collect()`：同理，collect 阶段采集到的 URL 最终调用 scrape 时，同样注入 ownership。

### 资源元数据变更

- `db://schema/products`：增加 ownership 列说明
- `db://schema/overview`：更新关系描述

### 不变更

- `scrapers/` 爬虫代码不感知 ownership
- `product_snapshots` 表不加 ownership（通过 JOIN products 获取）
- `reviews` 表不加 ownership（同上）

---

## 模块二：CSV 文件规范 + URL/SKU 验证

### CSV 文件格式

**`data/sku-list-source.csv`**（分类页 URL，用于 `start_collect`）：

```csv
url,ownership
https://www.basspro.com/shop/en/some-category,own
https://www.meatyourmaker.com/some-category,competitor
```

**`data/sku-product-details.csv`**（产品详情页 URL，用于 `start_scrape`）：

```csv
url,ownership
https://www.basspro.com/shop/en/some-product/12345,own
https://www.meatyourmaker.com/some-product.html,competitor
```

规则：
- 两列：`url`、`ownership`（值为 `own` 或 `competitor`）
- 一行一条，有表头
- 累积式管理，服务端 UPSERT 去重
- ownership 不允许为空

### URL 验证规则（agent 侧，仅域名匹配）

支持站点域名列表：
- `www.basspro.com` → basspro
- `www.meatyourmaker.com` → meatyourmaker

验证流程：提取 URL 域名 → 匹配列表 → 通过则可写入 CSV，不通过则告知用户。

### SKU → URL 转换

1. Agent 用 brave 搜索 `site:{domain} {SKU}`
2. 从结果中找到产品详情页 URL
3. 找不到则尝试 firecrawl
4. 成功 → 写入 `sku-product-details.csv`
5. 失败 → 告知用户

### ownership 交互流程

```
用户给 URL/SKU
  → 验证域名
  → 通过：
     ├─ 已指定 ownership → 写入 CSV
     └─ 未指定 → 追问 → 回答则写入，无法回答则不写入
  → 不通过：
     └─ 告知"该站点不支持定时任务"
     └─ 用户仍需要 → agent 用浏览器/搜索技能临时获取内容返回
        （不走 MCP 任务流，不写 CSV，不写数据库）
```

### 文件位置

### 文件位置（统一规范）

所有 workspace 文件的基准路径为 `~/.openclaw/workspace/`（以下简称 `$WS`）。全文中引用的路径统一为：

- CSV 文件：`$WS/data/sku-list-source.csv`、`$WS/data/sku-product-details.csv`
- 状态文件：`$WS/state/active-tasks.json`
- 配置文件：`$WS/config/email-recipients.txt`
- 报告文件：`$WS/reports/scrape-report-YYYY-MM-DD.xlsx`

与项目源码 `data/`（存 products.db）物理分离。

---

## 模块三：定时任务三阶段工作流

### 阶段 1：每日任务提交（Cron Job, isolated）

**Cron 配置：**

```json
{
  "name": "daily-scrape-submit",
  "cron": "0 8 * * *",
  "tz": "Asia/Shanghai",
  "session": "isolated",
  "agentTurn": {
    "message": "执行每日爬虫任务提交，使用 daily-scrape-submit 技能",
    "model": "sonnet",
    "timeoutSeconds": 300
  },
  "delivery": {
    "announce": true,
    "to": "<dingtalk-channel-id>"
  }
}
```

**执行流程：**

1. 读取 `~/.openclaw/workspace/data/sku-list-source.csv`，逐行调用 `start_collect(category_url=url, ownership=ownership)`（每行一次调用，因为 `start_collect` 只接受单个 URL）
2. 读取 `~/.openclaw/workspace/data/sku-product-details.csv`，按 ownership 分组，调用 `start_scrape(urls=[...], ownership=ownership)`（每组一次调用，`start_scrape` 接受 URL 列表）
3. 将所有 task_id 写入 `~/.openclaw/workspace/state/active-tasks.json`：

```json
{
  "submitted_at": "2026-03-10T00:00:00",
  "tasks": [
    {"id": "abc123", "type": "collect", "ownership": "own"},
    {"id": "bcd234", "type": "collect", "ownership": "competitor"},
    {"id": "def456", "type": "scrape", "ownership": "own"},
    {"id": "efg567", "type": "scrape", "ownership": "competitor"}
  ]
}
```

> **注意**：`submitted_at` 使用 UTC 时间，不带时区后缀（与 SQLite `CURRENT_TIMESTAMP` 格式一致 `YYYY-MM-DDTHH:MM:SS`），确保后续 SQL 时间比较正确。

4. Announce 到 DingTalk（任务已启动通知）

### 阶段 2：心跳监控（Heartbeat, main session）

**Heartbeat 配置：**

```json5
{
  every: "5m",
  lightContext: true,
  target: "none",
  activeHours: {
    start: "07:00",
    end: "23:00",
    timezone: "Asia/Shanghai"
  }
}
```

**HEARTBEAT.md 检查清单：**

1. 检查 `~/.openclaw/workspace/state/active-tasks.json` 是否有活跃任务
2. 无任务或文件为空 `{}` → HEARTBEAT_OK
3. 有任务 → 调用 `get_task_status` 逐个检查
4. 全部未完成 → HEARTBEAT_OK
5. 某个 task_id 返回 "not found"（服务重启等原因）→ 视为失败，继续检查其他任务
6. 全部有终态（completed/failed/cancelled/not found）→ 触发阶段 3 Cron：

```bash
openclaw cron add --name "scrape-report" --at +0m --session isolated \
  --message "执行爬虫任务汇报，使用 daily-scrape-report 技能" \
  --announce --to "<dingtalk-channel-id>" --delete-after-run
```

### 阶段 3：任务汇报（一次性 Cron, isolated）

**Step 1 — 汇总任务结果：**
- 读取 `state/active-tasks.json`
- 调用 `get_task_status` 获取每个任务的 result

**Step 2 — 查询新增数据（execute_sql）：**

> **时间格式**：`submitted_at` 已按 UTC 存储（格式 `YYYY-MM-DDTHH:MM:SS`），与 SQLite `CURRENT_TIMESTAMP` 一致，可直接用 `>=` 比较。

```sql
-- 新增产品
SELECT url, name, sku, price, stock_status, rating, review_count,
       scraped_at, site, ownership
FROM products
WHERE scraped_at >= datetime('{submitted_at}')
ORDER BY site, ownership

-- 新增评论
SELECT p.name, r.author, r.headline, r.body, r.rating,
       r.date_published, r.images, p.ownership
FROM reviews r
JOIN products p ON r.product_id = p.id
WHERE r.scraped_at >= datetime('{submitted_at}')
ORDER BY p.name
```

**Step 3 — 翻译评论：**
- 按批次（每批 30-50 条）用低端模型翻译 headline 和 body 为中文
- 翻译结果暂存内存，不回写数据库

**Step 4 — 生成 Excel（xlsx 技能）：**

Sheet1 — 产品：产品地址、产品名称、SKU、售价$、库存状态、综合评分、评分数量、抓取时间、站点、归属

Sheet2 — 评论：产品名称、评论人、标题（原文）、内容（原文）、标题（中文）、内容（中文）、打分、评论时间、照片

文件路径：`~/.openclaw/workspace/reports/scrape-report-YYYY-MM-DD.xlsx`（绝对路径）

**Step 5 — 发送邮件（himalaya 技能）：**
- 收件人：从 `~/.openclaw/workspace/config/email-recipients.txt` 读取
- 主题：`[Qbu-Crawler] 每日爬虫报告 YYYY-MM-DD`
- 正文：简要统计
- 附件：使用绝对路径 `~/.openclaw/workspace/reports/scrape-report-YYYY-MM-DD.xlsx`

**Step 6 — DingTalk 汇报（announce）：**

```
✅ 每日爬虫任务已完成

- **完成时间**：YYYY-MM-DD HH:MM
- **产品抓取**：成功 N，失败 N
- **新增评论**：N 条
- **自有产品**：N 个 | **竞品**：N 个
- **邮件发送**：✅ 已发送至 N 位收件人
- **报告文件**：scrape-report-YYYY-MM-DD.xlsx
```

**Step 7 — 清理状态：**
- 清空 `state/active-tasks.json`
- Cron Job 配置了 `--delete-after-run`，自动删除

### 异常处理

| 场景 | 处理方式 |
|------|---------|
| CSV 文件为空 | 阶段 1 跳过提交，Announce "无待采集 URL" |
| 全部任务失败 | 阶段 3 仍执行，Excel 为空表，DingTalk 汇报失败详情 |
| 邮件发送失败 | DingTalk 汇报标注 "❌ 邮件发送失败：{原因}" |
| 翻译部分失败 | Excel 中文列留空，不阻断流程 |
| 部分任务失败部分完成 | 等全部有终态后触发阶段 3 |
| task_id 不存在（服务重置） | 视为失败，继续检查其他任务 |
| 大批量 URL（数百个） | `start_scrape` 按原样提交整个 URL 列表（服务端逐个处理），不做客户端分片 |

---

## 模块四：OpenClaw 配置文件变更

### 修改现有文件

| 文件 | 变更 |
|------|------|
| `workspace/SOUL.md` | 增加任务管理者、数据验证者角色描述和交互边界 |
| `workspace/TOOLS.md` | ownership 参数说明 + URL 验证规则 + CSV 规范 + 汇报格式 |
| `workspace/skills/qbu-product-data/SKILL.md` | 增加 ownership 维度 SQL 模板 |

### 新建文件

| 文件 | 用途 |
|------|------|
| `workspace/HEARTBEAT.md` | 心跳检查清单 |
| `workspace/skills/daily-scrape-submit/SKILL.md` | 阶段 1 任务提交技能 |
| `workspace/skills/daily-scrape-report/SKILL.md` | 阶段 3 汇报技能（含翻译+Excel+邮件） |
| `workspace/skills/csv-management/SKILL.md` | URL/SKU 验证与 CSV 管理技能 |
| `workspace/data/sku-list-source.csv` | 空模板（含表头） |
| `workspace/data/sku-product-details.csv` | 空模板（含表头） |
| `workspace/config/email-recipients.txt` | 邮件收件人列表 |
| `workspace/state/active-tasks.json` | 活跃任务状态（初始为 `{}`） |

### 目录结构

```
workspace/
├── SOUL.md                            # 修改
├── TOOLS.md                           # 修改
├── HEARTBEAT.md                       # 新建
├── state/
│   └── active-tasks.json              # 新建
├── config/
│   └── email-recipients.txt           # 新建
├── reports/                           # 新建（Excel 输出）
├── data/
│   ├── sku-list-source.csv            # 新建
│   └── sku-product-details.csv        # 新建
└── skills/
    ├── qbu-product-data/
    │   └── SKILL.md                   # 修改
    ├── daily-scrape-submit/
    │   └── SKILL.md                   # 新建
    ├── daily-scrape-report/
    │   └── SKILL.md                   # 新建
    └── csv-management/
        └── SKILL.md                   # 新建
```

---

## 模块五：完整变更清单与执行顺序

### 服务端改动

| 序号 | 文件 | 改动 |
|------|------|------|
| S1 | `models.py` | products 表增加 ownership 列 + 迁移 + save_product/query_products 更新 |
| S2 | `server/task_manager.py` | _run_scrape/_run_collect 注入 ownership |
| S3 | `server/mcp/tools.py` | MCP tools 增加 ownership 参数 |
| S4 | `server/mcp/resources.py` | schema 元数据更新 |
| S5 | `server/api/products.py` | API 增加 ownership 参数 |
| S6 | `server/api/tasks.py` | POST body schema 更新 |

### OpenClaw 配置改动

| 序号 | 文件 | 操作 |
|------|------|------|
| O1 | `workspace/SOUL.md` | 修改 |
| O2 | `workspace/TOOLS.md` | 修改 |
| O3 | `workspace/skills/qbu-product-data/SKILL.md` | 修改 |
| O4 | `workspace/HEARTBEAT.md` | 新建 |
| O5 | `workspace/skills/daily-scrape-submit/SKILL.md` | 新建 |
| O6 | `workspace/skills/daily-scrape-report/SKILL.md` | 新建 |
| O7 | `workspace/skills/csv-management/SKILL.md` | 新建 |
| O8-O11 | data/, config/, state/ 文件 | 新建 |

### 执行顺序

```
第一阶段：服务端基础
  S1 → S2 → S3 → S4 → S5 → S6

第二阶段：OpenClaw 配置（S3 完成后可开始）
  O1-O3（修改现有文件，可并行）
  O4-O7（新建 Skill 和 HEARTBEAT，可并行）
  O8-O11（新建数据/配置文件，可并行）

第三阶段：部署与验证
  1. 部署服务端，重启服务
  2. 安装 workspace 文件
  3. 配置 Cron Job + Heartbeat
  4. 端到端测试
```

### 文档同步

| 文档 | 更新内容 |
|------|---------|
| `CLAUDE.md` | 项目结构图 + ownership 说明 |
| `server/openclaw/README.md` | Cron/Heartbeat 配置 + 新增 Skill 说明 |
