# 心跳检查

IMPORTANT: 严格按以下步骤执行，不要跳过或简化。

## 一、定时任务监控

1. 读取 `~/.openclaw/workspace/state/active-tasks.json`
2. 如果文件不存在、为空、内容为 `{}`、或 `tasks` 数组为空 → 跳到第二部分
3. IMPORTANT: 如果存在 `"status": "reporting"` 字段：
   - 检查 `reporting_at` 时间戳，如果距今 **超过 30 分钟** → 视为汇报异常，清空文件为 `{}`，跳到第二部分
   - 如果距今 **不超过 30 分钟** → 汇报正在执行中，不重复触发，跳到第二部分
4. 如果有任务列表（tasks 数组非空且无 reporting 状态）：
   - 对每个 task_id 调用 `get_task_status`
   - 如果某个 task_id 返回 "not found" → 视为 failed
   - 如果仍有 pending 或 running 状态 → 跳到第二部分
   - IMPORTANT: 如果所有任务都已终态（completed / failed / cancelled / not found）：
     a. **先更新** `active-tasks.json`，添加 `"status": "reporting"` 和 `"reporting_at": "<当前UTC时间>"`，保留原有 tasks 和 submitted_at
     b. **再执行**以下命令触发汇报（仅一次）：

```bash
openclaw cron add --name "scrape-report" --at +0m --session isolated --message "执行爬虫任务汇报，读取 skills/daily-scrape-report 技能并严格执行" --announce --to "chat:cidoOQUuAEydsdghncIE5INqg==" --delete-after-run
```

## 二、临时任务监控

1. 读取 `~/.openclaw/workspace/state/adhoc-tasks.json`
2. 如果文件不存在、为空、内容为 `{}` → 回复 HEARTBEAT_OK，结束
3. 对每个 task_id 调用 `get_task_status`
4. 如果仍有 pending 或 running 状态 → 回复 HEARTBEAT_OK，结束
5. IMPORTANT: 如果所有任务都已终态，**直接在当前会话中反馈**（不创建 cron）：
   - 汇总每个任务的结果：成功/失败、产品数、评论数
   - 如果有新增数据（products_saved > 0 或 reviews_saved > 0），追问用户："有新增数据，需要生成报告并发送邮件吗？"
   - 清空 `adhoc-tasks.json` 为 `{}`
6. 回复 HEARTBEAT_OK
