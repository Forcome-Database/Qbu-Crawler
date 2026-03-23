---
name: daily-scrape-submit
description: 每日定时爬虫任务提交技能。由 Cron Job 触发，读取 CSV 文件提交爬虫任务并保存状态。
---

# 每日爬虫任务提交

定时 Cron Job 触发此技能，读取 CSV 文件并提交爬虫任务。

IMPORTANT: 严格按以下步骤执行，不要做任何步骤之外的事。

**你需要使用的工具**（均为已加载的 MCP 工具，直接调用即可）：
- `start_collect` — 提交分类页采集任务
- `start_scrape` — 提交产品页抓取任务

**禁止**：不要搜索命令行入口、不要探索代码库、不要寻找替代方案。工具已就绪。

## 步骤 1：读取并提交分类页任务

读取 `~/.openclaw/workspace/data/sku-list-source.csv`（格式：`url,ownership`，有表头）。

如果文件不存在或只有表头 → 跳过此步。

对每一行调用 `start_collect(category_url=url, ownership=ownership, reply_to="chat:cidoOQUuAEydsdghncIE5INqg==")`，记录返回的 task_id。

- 无效行（缺少 ownership 或 URL 为空）→ 跳过并记录

## 步骤 2：读取并提交产品页任务

读取 `~/.openclaw/workspace/data/sku-product-details.csv`（格式同上）。

如果文件不存在或只有表头 → 跳过此步。

按 ownership 分组，对每组调用 `start_scrape(urls=[该组所有URL], ownership=ownership, reply_to="chat:cidoOQUuAEydsdghncIE5INqg==")`，记录 task_id。

## 步骤 3：保存状态并汇报

如果两个 CSV 都为空 → 输出"无待采集 URL，跳过今日任务"，**流程结束**。

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

`submitted_at` 使用上海时间（Asia/Shanghai），格式 `YYYY-MM-DDTHH:MM:SS`（无时区后缀）。

## 步骤 4：输出启动通知

按以下格式输出（替换实际值）：

```
🚀 每日爬虫任务已启动

- **提交时间**：YYYY-MM-DD HH:MM
- **分类采集**：N 个任务
- **产品抓取**：N 个任务（N 个产品）
- **任务 ID**：xxx, yyy

将自动监控任务进度，完成后汇报。
```

**自检**：
- ✅ 所有 start_collect/start_scrape 调用都传入了 reply_to
- ✅ active-tasks.json 已写入
- ✅ 启动通知已输出
