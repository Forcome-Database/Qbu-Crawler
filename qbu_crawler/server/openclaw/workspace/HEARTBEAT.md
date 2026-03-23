# 心跳检查

严格按以下步骤执行，不要自由发挥。

临时任务通知由服务端自动投递，心跳不处理。

## 第一步：检查定时任务

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
