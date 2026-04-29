# D024 测试7 P3 报告状态模型与契约收口

## 背景

测试7 P0/P1/P2 已经把用户可见报告收口到 `report_user_contract`，并补充了 run log、运维告警和 manifest 回写。但 `workflow_runs.report_phase` 仍同时承载报告阶段、本地产物状态和外部通知状态，历史 fallback 也仍可能让 renderer 绕过 contract 直接消费旧 analytics 字段。

P3 的目标是拆开状态语义，并让用户业务报告只消费 contract，运维问题继续通过 run log、技术邮件、manifest/status 追踪。

## 实现内容

新增 `migration_0012_report_status_columns`，在 `workflow_runs` 增加：

- `report_generation_status`
- `email_delivery_status`
- `workflow_notification_status`
- `delivery_last_error`
- `delivery_checked_at`

迁移支持幂等执行和历史 backfill：

- 发现 Excel / analytics / report_artifacts 时回填 `report_generation_status=generated`
- 从 `workflow_full_report.payload.email_status` 回填业务邮件状态
- 从 `notification_outbox` 回填 workflow 通知状态，`sent` 和历史兼容值 `delivered` 都视为送达
- 发现 deadletter 时回填 `workflow_notification_status=deadletter`，并将旧 `report_phase=full_sent` 降级为 `full_sent_local`

新增 `report_status.py` 作为状态同步层：

- `derive_email_delivery_status()`
- `derive_workflow_notification_status()`
- `sync_workflow_report_status()`

Workflow 接入点：

- snapshot freeze 后写 `report_generation_status=pending`
- full report 成功后写 `generated / sent|failed|skipped / pending`
- full report 最终失败后写 `report_generation_status=failed` 和错误摘要

Notifier 接入点：

- outbox 发送成功后同步 workflow 通知状态
- outbox deadletter 后同步 DB 状态，并继续执行 `full_sent -> full_sent_local` 降级

Manifest 接入点：

- 优先读取 DB 状态字段生成 delivery 语义
- DB 状态 unknown 时才回退现场 artifact/outbox 推导
- 支持普通 sqlite tuple row 和 `sqlite3.Row`
- delivery 中新增 `db_status`，供内部审计追踪

Contract strict 收口：

- 新增 `REPORT_CONTRACT_STRICT_MODE`
- `report_user_contract.contract_source` 标记 `provided / legacy_adapter / generated`
- legacy adapter 下，无证据的旧 `report_copy.improvement_priorities` 不再进入用户可见行动建议
- HTML、Excel、邮件的行动建议主路径只消费 `report_user_contract.action_priorities`
- 用户业务 HTML 不展示 deadletter、低覆盖 SKU、估算日期占比等运维诊断

## 验证

新增并通过以下回归：

- `tests/server/test_report_status_migration.py`
- `tests/server/test_report_status_sync.py`
- `tests/server/test_report_manifest.py`
- `tests/server/test_report_contract_strict_mode.py`
- `tests/server/test_test7_artifact_replay_p3.py`

定向验证命令：

```bash
uv run --frozen python -m pytest tests/server/test_report_status_migration.py tests/server/test_report_status_sync.py tests/server/test_report_manifest.py tests/server/test_report_contract_strict_mode.py tests/server/test_report_contract_renderers.py tests/server/test_test7_artifact_replay.py tests/server/test_test7_artifact_replay_p3.py tests/test_workflows.py::TestWorkflowReconcile::test_reconcile_advances_reporting_run_to_full_sent tests/test_workflows.py::TestWorkflowReconcile::test_full_report_failure_leaves_fast_sent_snapshot_intact -q
```

结果：`32 passed`。
