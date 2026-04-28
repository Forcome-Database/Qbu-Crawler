# D023 测试9运行日志与 P2 manifest 修复

日期：2026-04-28

## 背景

测试9生产产物显示业务报告已生成，但日志里出现“采集缺失”类告警。复核后确认：

- 该类问题主要属于运行过程诊断，不应混入用户业务报告；
- 低覆盖 SKU、通知 deadletter、估算日期占比需要可追踪的过程日志；
- P2 的 delivery/manifest 状态需要在通知 deadletter 后回写到 analytics；
- 诊断卡 deep analysis 中 dict 被模板直接渲染为 Python repr。

## 实现

- 新增 `qbu_crawler/server/run_log.py`，按 `data/log-run-<run_id>-<yyyymmdd>.log` 记录 snapshot、质量统计、低覆盖 SKU、通知状态等运行过程。
- `WorkflowWorker` 在 snapshot freeze、scrape quality、full report completed 阶段追加 run log；运维邮件只发送给技术收件人，并附带 run log。
- `TaskManager` 在任务结果中记录 `product_summaries`，包含每个 SKU 的站点评论数、提取数、保存数和 `scrape_meta`。
- `basspro`、`meatyourmaker`、`waltons` 仅基于已有翻页/加载过程记录 `review_extraction.stop_reason`、`pages_seen`、`extracted_review_count`，不增加额外页面请求。
- 新增 `qbu_crawler/server/report_manifest.py`，汇总 artifact、业务邮件送达、workflow 通知送达、deadletter 和内部状态。
- `notifier.downgrade_report_phase_on_deadletter()` 在状态降级后刷新 analytics 中的 `report_manifest` 与 `report_user_contract.delivery`。
- HTML 诊断卡 deep analysis 渲染优先读取 `name` / `mode` / `cause` / `summary`，避免直接展示 dict repr。

## 验证

- `uv run --frozen pytest tests/server/test_run_log.py tests/server/test_report_contract_slots.py tests/server/test_report_manifest.py tests/server/test_attachment_html_issues.py::test_issue_card_deep_analysis_dicts_render_as_text_not_python_repr tests/test_scrape_quality.py::test_data_quality_alert_integration_sends_email -q`
- `uv run --frozen pytest tests/server/test_report_contract.py tests/server/test_report_contract_llm.py tests/server/test_report_contract_renderers.py tests/server/test_internal_ops_alert.py tests/server/test_workflow_ops_alert_wiring.py tests/test_scrape_quality.py -q`
- `uv run --frozen pytest tests/server/test_test7_artifact_replay.py tests/server/test_attachment_html_issues.py tests/server/test_report_manifest.py tests/server/test_run_log.py -q`
- `uv run --frozen python -m py_compile qbu_crawler/server/task_manager.py qbu_crawler/scrapers/meatyourmaker.py qbu_crawler/scrapers/basspro.py qbu_crawler/scrapers/waltons.py qbu_crawler/server/workflows.py qbu_crawler/server/run_log.py qbu_crawler/server/report_manifest.py`
