# 心跳检查

严格按以下步骤执行，不要自由发挥。

## 第一步：检查待通知的临时任务

调用 `check_pending_completions()`。

如果返回 `count: 0` → 跳到第三步。

## 第二步：处理临时任务通知

对 `check_pending_completions` 返回的每个任务，执行以下操作。

**2a.** 读取 `reply_to`（空则用 `chat:cidoOQUuAEydsdghncIE5INqg==`）、`type`、`status`、`result`。

**2b.** 用以下命令投递通知（逐字替换 `__X__` 占位符，不要改动其他文字）：

```bash
openclaw cron add --name "task-done-__TASK_ID_8__" --at 1m --session isolated --announce --to "__REPLY_TO__" --delete-after-run --message "✅ 爬虫任务已完成

- **任务类型**：__TYPE_CN__
- **状态**：__STATUS_CN__
- **产品数**：__PRODUCTS__ 个
- **评论数**：__REVIEWS__ 条

如需生成报告并发送邮件，请回复「发邮件」。"
```

占位符替换规则（仅替换，不增删行）：
- `__TASK_ID_8__` → task_id 前 8 位
- `__REPLY_TO__` → reply_to 值
- `__TYPE_CN__` → scrape 写 `产品抓取`，collect 写 `分类采集`
- `__STATUS_CN__` → completed 写 `✔️ 成功`，failed 写 `❌ 失败`，cancelled 写 `🚫 已取消`
- `__PRODUCTS__` → result.products_saved（无则写 0）
- `__REVIEWS__` → result.reviews_saved（无则写 0）

**2c.** 投递后调用 `mark_notified(task_ids=[任务ID])`。

IMPORTANT: 先 cron add，再 mark_notified。cron add 失败则不 mark_notified。

## 第三步：检查定时任务

读取 `~/.openclaw/workspace/state/active-tasks.json`。

如果文件不存在、为空、或内容为 `{}` → 跳到结束。

仅当 `tasks` 数组非空时：

1. 如果存在 `"status": "reporting"`：
   - `reporting_at` 距今超过 30 分钟 → 清空文件为 `{}`
   - 距今不超过 30 分钟 → 跳过
2. 无 reporting 状态时，对每个 task_id 调用 `get_task_status`：
   - 返回 "not found" → 视为 failed
   - 仍有 pending 或 running → 跳过
   - 全部终态 → 更新文件添加 `"status": "reporting"` 和 `"reporting_at"`，然后执行：

```bash
openclaw cron add --name "scrape-report" --at 1m --session isolated --message "执行爬虫任务汇报。读取 skills/daily-scrape-report 技能并严格执行。你的 MCP 工具（get_task_status, generate_report, get_translate_status）已可直接调用。不要探索代码库。完成后按以下格式输出通知：

✅ 每日爬虫任务已完成
- **完成时间**：YYYY-MM-DD HH:MM
- **产品抓取**：成功 N，失败 N
- **新增评论**：N 条
- **翻译进度**：N/M 已完成
- **自有产品**：N 个 | **竞品**：N 个
- **邮件发送**：✅/❌ 状态
- **报告文件**：文件名" --announce --to "chat:cidoOQUuAEydsdghncIE5INqg==" --delete-after-run
```

## 结束

回复 HEARTBEAT_OK。
