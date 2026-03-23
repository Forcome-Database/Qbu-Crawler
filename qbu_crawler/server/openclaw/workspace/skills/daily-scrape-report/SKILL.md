---
name: daily-scrape-report
description: 爬虫任务完成后的汇报技能。由 Heartbeat 检测到所有定时任务终态后触发。汇总结果、生成报告、发送邮件、通知完成。
---

# 每日爬虫任务汇报

由 Heartbeat 检测到定时任务完成后触发。

IMPORTANT: 严格按以下步骤执行，不可跳过。

## 步骤 0：前置校验（防重复执行）

读取 `~/.openclaw/workspace/state/active-tasks.json`。

如果文件不存在、为空、内容为 `{}`、或缺少 `submitted_at` 字段、或 `tasks` 数组为空 → **静默退出，不输出任何内容**。

## 步骤 1：汇总任务结果

从 `active-tasks.json` 获取 `submitted_at` 和 `tasks` 列表。

对每个 task_id 调用 `get_task_status`，统计：
- 成功数（status = completed）
- 失败数（status = failed / cancelled / not found）
- 产品数和评论数（从 result 中提取）

## 步骤 2：检查翻译进度

调用 `get_translate_status(since=submitted_at)` 查看翻译进度。

- 如果 `pending > 0`，等待 1 分钟后再次检查，最多等 3 轮
- 如果 `pending = 0` 或已等 3 轮 → 继续下一步

## 步骤 3：生成报告并发送邮件

调用 `generate_report(since=submitted_at, send_email="true")`。

从返回结果中提取：新增产品数、评论数、翻译成功数、Excel 文件路径、邮件发送状态。

## 步骤 4：输出完成通知

按以下格式输出（替换实际值）：

```
✅ 每日爬虫任务已完成

- **完成时间**：YYYY-MM-DD HH:MM
- **产品抓取**：成功 N，失败 N
- **新增评论**：N 条
- **翻译进度**：N/M 已完成
- **自有产品**：N 个 | **竞品**：N 个
- **邮件发送**：✅ 已发送至 N 位收件人 / ❌ 发送失败：原因
- **报告文件**：scrape-report-YYYY-MM-DD.xlsx
```

## 步骤 5：清理状态

清空 `~/.openclaw/workspace/state/active-tasks.json` 为 `{}`。

## 异常处理

- `generate_report` 返回错误 → 通知中标注失败原因，仍然执行步骤 5 清理
- 部分任务失败 → 仍然生成报告（汇报成功任务数据）

**自检**：
- ✅ generate_report 已调用
- ✅ 完成通知已输出
- ✅ active-tasks.json 已清空为 {}
