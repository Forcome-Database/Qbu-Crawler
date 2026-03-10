# 每日爬虫任务提交

定时 Cron Job 触发此技能，读取 CSV 文件并提交爬虫任务。

## 执行步骤

### 1. 读取分类页 CSV

读取 `~/.openclaw/workspace/data/sku-list-source.csv`。

格式：`url,ownership`（有表头）。如果文件不存在或为空（只有表头），跳过此步。

对每一行调用 `start_collect(category_url=url, ownership=ownership)`，记录返回的 task_id。

### 2. 读取产品页 CSV

读取 `~/.openclaw/workspace/data/sku-product-details.csv`。

格式：`url,ownership`（有表头）。如果文件不存在或为空，跳过此步。

按 ownership 分组，对每组调用 `start_scrape(urls=[该组所有URL], ownership=ownership)`，记录 task_id。

### 3. 保存任务状态

将所有 task_id 写入 `~/.openclaw/workspace/state/active-tasks.json`：

```json
{
  "submitted_at": "YYYY-MM-DDTHH:MM:SS",
  "tasks": [
    {"id": "task_id_1", "type": "collect", "ownership": "own"},
    {"id": "task_id_2", "type": "scrape", "ownership": "competitor"}
  ]
}
```

`submitted_at` 使用 UTC 时间，格式 `YYYY-MM-DDTHH:MM:SS`（无时区后缀），与 SQLite CURRENT_TIMESTAMP 格式一致。

### 4. 汇报

输出任务启动通知（参考 TOOLS.md 中的"任务启动通知"格式）。

### 异常处理

- 两个 CSV 都为空 → 输出"无待采集 URL，跳过今日任务"
- CSV 中有无效行（缺少 ownership 或 URL 为空）→ 跳过该行，日志记录
