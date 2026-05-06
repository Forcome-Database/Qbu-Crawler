# D030 周报邮件与每日钉钉摘要

日期：2026-05-07

## 背景

每日完整邮件在生产使用中频率偏高，但每日采集和新增评论提醒仍需要保留。本次改动将业务邮件调整为“首次全量基线 + 每周周报”，同时每天在钉钉群发送轻量摘要。

## 实现摘要

- 新增 `qbu_crawler/server/report_cadence.py`，集中判断业务邮件是否发送、发送原因、窗口类型和周报窗口天数。
- 新增 `qbu_crawler/server/daily_digest.py`，基于当日 snapshot 构建钉钉摘要，包含新增评论数、自有 TOP3、竞品 TOP3 和确定性分析。
- `WorkflowWorker` 每天都会入队 `workflow_daily_digest`；非周报日仍生成本地报告产物，但业务邮件以 `weekly_cadence_skip` 跳过。
- 周报日使用 `build_windowed_report_snapshot()` 派生 7 天窗口 snapshot，保证“本周变化”来自近 7 天入库评论。
- 首次基线不使用周报窗口，继续发送全量基线邮件，并通过 `report_window.type=bootstrap` 展示“监控起点”语义。
- HTML 和邮件模板通过 `report_window` 决定“今日变化 / 本周变化 / 监控起点”文案。
- 全景页优先消费 `snapshot.cumulative.products/reviews`，周报窗口不会把全景数据退化成当天或本周数据。
- `workflow_daily_digest` 不参与完整报告通知状态同步，避免日摘要 deadletter 污染 full report 状态。

## 配置

新增配置：

```env
REPORT_EMAIL_CADENCE=weekly
REPORT_WEEKLY_EMAIL_WEEKDAY=1
REPORT_WEEKLY_WINDOW_DAYS=7
REPORT_EMAIL_SEND_BOOTSTRAP=true
```

模拟脚本新增内部开关 `REPORT_EMAIL_FORCE_DISABLED`，在禁外发模拟时强制跳过业务邮件，避免测试环境因 SMTP/收件人配置缺失产生误报。

## 验证

已运行：

```bash
uv run pytest tests/server/test_weekly_email_cadence.py tests/server/test_daily_dingtalk_digest.py tests/server/test_weekly_report_window.py -v
uv run pytest tests/server/test_email_full_template.py tests/server/test_report_contract_renderers.py tests/server/test_historical_report_paths.py tests/server/test_historical_trend_template.py tests/server/test_workflow_ops_alert_wiring.py -v
uv run pytest tests/server/test_test14_report_regressions.py tests/server/test_simulate_daily_report_script.py -v
```

结果：

- 新增周报/钉钉测试：17 passed。
- 报告、通知、历史趋势回归：35 passed。
- 测试14与模拟脚本回归：11 passed。

## 30 天模拟

使用隔离数据库和报告目录执行：

```bash
uv run python scripts/simulate_daily_report.py 30 --output-dir data/simulations/weekly-email-dingtalk-30days-rerun
```

模拟结果：

- 生成 30 条 workflow run。
- 禁外发模式下 30 条业务邮件状态均为 `email_delivery_status=skipped`，`delivery_last_error=email_disabled`。
- 生成 30 条 `workflow_daily_digest` outbox 记录。
- 抽样核对：第 1 天窗口评论数与累计评论数一致；后续 run 的窗口评论数为当期/周报窗口数据，累计评论数持续增长。

## 生产注意事项

- 默认生产邮件频率为首次基线 + 每周一次。
- 希望改成周五发送时，只需设置 `REPORT_WEEKLY_EMAIL_WEEKDAY=5`。
- 非周报日邮件 skipped 是预期状态；钉钉日摘要才是每日业务提醒入口。
- 周报“本周变化”是 7 天窗口；“全景数据”仍是累计视角。
