# D028 MCP 与 OpenClaw schema 同步

## 背景

OpenClaw workspace 的产品分析规则已经开始使用 canonical 指标和时间轴，但 MCP resources 仍只暴露旧的五张表，缺少 workflow、通知、报告产物和评论分析相关 schema，容易让 Agent 在 SQL 分析和状态解释时拿不到最新上下文。

## 变更

- 补齐 MCP resources：`workflow_runs`、`workflow_run_tasks`、`notification_outbox`、`report_artifacts`、`review_analysis`、`review_issue_labels`。
- 将 `review_publish_time` 的权威字段同步为 `reviews.date_published_parsed`，并在统计 latest 时兼容回退原始 `date_published`。
- 更新 OpenClaw `TOOLS.md`，拆开报告产物、业务邮件和 workflow 通知三类状态。
- 更新 `qbu-product-data` skill，加入 `ratings_only_count`、文字评论覆盖率、解析发布时间趋势、问题标签和 LLM 洞察 SQL 模板。
- 更新 OpenClaw bridge/plugin 的 workflow 摘要，避免把本地报告生成、业务邮件发送和外部通知送达混成一个状态。

## 验证

```bash
uv run pytest tests/test_tool_contract.py tests/test_notifier.py tests/test_mcp_tools.py tests/test_metric_semantics.py -q
```

结果：`60 passed`。
