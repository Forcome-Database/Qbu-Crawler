# D021 测试7报告 P0 语义契约修复

日期：2026-04-28

## 背景

测试7生产报告暴露出报告语义层缺失导致的多处用户可见矛盾：LLM 行动建议产品集合校验错配、fallback 建议重复、诊断卡缺证据展示、热力图提示与分数不一致、近30天筛选口径错误、竞品短板回退英文，以及 outbox deadletter 后 workflow 仍显示 full_sent。

## 本次收口

- `report_llm.py`：`affected_products` 校验改为按 `label_code` 的问题簇产品集合优先，其次全量产品，最后兼容旧的 `risk_products`。
- `report_analytics.py`：fallback priorities 按标签生成差异化建议，绑定 `evidence_review_ids`、`top_complaint`，无证据时标记 `evidence_insufficient`。
- `report_common.py`：补齐 `report_user_contract.action_priorities`、`issue_diagnostics`、`kpi_semantics`；区分 `high_risk_count` 和 `attention_product_count`；`top_actions` 兼容稀疏 cluster。
- `report_snapshot.py`：LLM/fallback/deep_analysis 合并后重新刷新 normalized analytics，Excel 改为消费带 contract 的 `pre_normalized`。
- `daily_report_v3.html.j2/css/js`：诊断卡展示图片证据、AI 建议和 deep analysis；图片证据增加尺寸约束；热力图下钻使用完整产品名。
- `report_html.py`：全景近30天筛选优先使用 `date_published_parsed`。
- `email_full.html.j2`：需关注产品数优先消费 `kpis.attention_product_count`，避免模板内重新计算出不同口径。
- `notifier.py` / `workflows.py`：新增 full_sent deadletter reconcile，`WorkflowWorker.process_once()` 会扫描已完成的 `full_sent` run 并降级到 `full_sent_local`。

## 验证

- `uv run pytest tests/server/test_llm_assert_consistency.py tests/server/test_fallback_priorities.py tests/test_report_common.py tests/server/test_attachment_html_issues.py tests/server/test_heatmap_optimization.py tests/test_v3_html.py tests/server/test_competitor_insights_v12.py tests/server/test_excel_sheets.py tests/server/test_email_full_template.py tests/server/test_workflow_ops_alert_wiring.py tests/server/test_internal_ops_alert.py -q`
  - 191 passed
- `uv run pytest tests/test_v3_excel.py tests/test_v3_html.py tests/test_report_snapshot.py tests/test_report_common.py -v`
  - 133 passed, 2 skipped

## 注意

本次仍是 P0 轻量 contract-first 修复，没有做完整报表语义层重构。后续 P1 可继续把邮件、HTML、Excel 的所有用户可见字段统一收口到单独的 `report_user_contract` 构建层，并把 delivery 状态拆成独立字段。
