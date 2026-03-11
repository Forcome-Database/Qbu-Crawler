---
name: daily-scrape-report
description: 爬虫任务完成后的汇报技能。由 Heartbeat 检测到所有任务终态后触发。汇总任务结果、调用 generate_report 生成报告和发送邮件、在钉钉输出完成通知。
---

# 每日爬虫任务汇报

由 Heartbeat 检测到任务完成后触发。

IMPORTANT: 严格按以下步骤执行，不可跳过。

## 步骤 0：前置校验（防重复执行）

读取 `~/.openclaw/workspace/state/active-tasks.json`。

IMPORTANT: 如果文件不存在、为空、内容为 `{}`、或缺少 `submitted_at` 字段、或 `tasks` 数组为空 → **静默退出，不输出任何内容，不发送钉钉消息**。这说明状态已被另一次汇报清空，当前是重复触发。

## 步骤 1：汇总任务结果

从 `active-tasks.json` 获取 `submitted_at` 和 `tasks` 列表。

对每个 task_id 调用 `get_task_status`，统计：
- 成功数（status = completed）
- 失败数（status = failed / cancelled / not found）
- 产品数和评论数（从 result 中提取）

## 步骤 2：生成报告并发送邮件

IMPORTANT: 你**必须**使用 `generate_report` 工具（这是 mcp-products 插件提供的 MCP 工具，和 `start_scrape`、`get_task_status` 是同一套工具）。不要说"无法调用"——如果你能调用 `get_task_status`，你就能调用 `generate_report`。

**可选：检查翻译完成度**

调用 `get_translate_status(since=submitted_at)` 查看翻译进度。如果 `pending > 0`，可等待 1-2 分钟后再生成报告。最多等 3 轮（每轮 1 分钟），超时则直接生成报告（邮件中会标注未翻译数量）。

调用方式：
```
工具名：generate_report
参数：
  since: "<active-tasks.json 中的 submitted_at 值，上海时间格式>"
  send_email: "true"
```

该工具由服务端程序化执行：查询新增数据（含已翻译的中文）→ 生成 Excel → SMTP 发送邮件。翻译由后台线程在爬虫采集期间自动完成。不需要你本地做任何事。

从返回结果中提取：
- 新增产品数、评论数
- 翻译成功数
- Excel 文件路径
- 邮件发送状态（成功/失败及原因）

## 步骤 3：钉钉汇报 + 清理状态

输出任务完成通知（参考 TOOLS.md 中的"定时任务完成通知"格式），包含：
- 任务执行结果（成功/失败数）
- 新增数据量
- 邮件发送状态
- 报告文件名

IMPORTANT: 最后将 `~/.openclaw/workspace/state/active-tasks.json` 清空为 `{}`。

## 异常处理

- `generate_report` 返回错误 → 在钉钉通知中标注失败原因，仍然清理状态
- 部分任务失败 → 仍然执行报告生成（只汇报成功任务的数据）
