# 心跳检查清单

1. 读取 `~/.openclaw/workspace/state/active-tasks.json`
2. 如果文件不存在、为空或内容为 `{}` → 回复 HEARTBEAT_OK
3. 如果有活跃任务：
   - 逐个调用 `get_task_status` 检查每个 task_id
   - 如果某个 task_id 返回 "not found" → 视为失败
   - 如果所有任务仍在运行（pending/running）→ 回复 HEARTBEAT_OK
   - 如果所有任务都有终态（completed/failed/cancelled/not found）→ 执行以下命令触发汇报：

```
openclaw cron add --name "scrape-report" --at +0m --session isolated --message "执行爬虫任务汇报，使用 daily-scrape-report 技能" --announce --to "<dingtalk-channel-id>" --delete-after-run
```

触发后回复 HEARTBEAT_OK
