# 测试7报告 P3 状态模型与旧 fallback 下线设计

**日期**：2026-04-28
**状态**：设计完成，待计划审查
**输入文档**：
- `docs/reviews/2026-04-28-production-test7-report-root-cause-and-remediation.md`
- `docs/superpowers/specs/2026-04-28-test7-report-p2-production-quality-design.md`
- `docs/devlogs/D023-test9-run-log-and-p2-manifest.md`

---

## 1. 背景

P0/P1/P2 已经完成测试7报告可信度修复、`report_user_contract` 契约层、run log、运维日志邮件和 manifest 读取/回写。当前剩余的结构性风险是：

- `workflow_runs.report_phase` 仍同时表达业务阶段、本地产物生成状态和外部通知状态。
- P2 manifest 能把 delivery 状态写回 analytics，但 DB 里没有正式、可查询、可迁移的状态列。
- HTML / Excel / 邮件虽然优先消费 contract，但旧 analytics fallback 仍散落在部分适配和模板路径中，后续改动仍可能绕开 contract。

P3 的目标不是继续补模板，也不是做视觉改版，而是把“状态模型”和“展示契约”真正收口。

---

## 2. 目标

1. 将报告运行状态拆成独立 DB 字段：
   - `report_generation_status`
   - `email_delivery_status`
   - `workflow_notification_status`
   - `delivery_last_error`
   - `delivery_checked_at`
2. 新增幂等 migration 和 backfill，把历史 `report_phase`、artifact、outbox 状态迁移到新状态字段。
3. 让 workflow / notifier / manifest 统一读写新状态字段，`report_phase` 只表示报告阶段，不再表示“已送达”。
4. 下线隐式旧 fallback：旧 analytics 字段只能在一个 adapter 层转换为 `report_user_contract`，renderer 和模板不得直接绕开 contract。
5. 增加严格回归：状态字段、manifest、analytics delivery、业务报告展示必须一致。

---

## 3. 非目标

- 不新增大型 UI 或运营后台。
- 不更换钉钉 / OpenClaw bridge 通知机制。
- 不删除旧测试 fixture；旧 fixture 必须通过 adapter 转为 contract。
- 不做视觉重设计，不调整报告信息架构。
- 不在用户业务报告中展示运维错误；运维错误继续通过 run log、技术邮件和内部 manifest/status 查询追踪。

---

## 4. 状态模型设计

### 4.1 新增字段

在 `workflow_runs` 增加：

| 字段 | 类型 | 值域 | 含义 |
|---|---|---|---|
| `report_generation_status` | TEXT | `unknown/pending/generated/failed/skipped` | 本地 snapshot/analytics/Excel/HTML/email body 是否生成 |
| `email_delivery_status` | TEXT | `unknown/pending/sent/failed/skipped` | 业务邮件发送结果 |
| `workflow_notification_status` | TEXT | `unknown/pending/sent/deadletter/partial/skipped` | workflow 外部通知送达结果 |
| `delivery_last_error` | TEXT | 任意文本 | 最近一次外部通知或邮件失败摘要 |
| `delivery_checked_at` | TEXT | ISO datetime | 最近一次 delivery reconcile 时间 |

`status` 继续表示 workflow 总体生命周期；`report_phase` 只表示报告阶段，例如 `none/fast_pending/fast_sent/full_pending/full_sent/full_sent_local`，不再被解释成“外部通知已送达”。

### 4.2 Backfill 规则

历史 run 回填按可证明事实推导：

- `report_generation_status=generated`：存在 `report_artifacts` 或 `workflow_runs.excel_path/analytics_path/pdf_path` 任一产物。
- `report_generation_status=failed`：`status='needs_attention'` 且 `error` 非空。
- `email_delivery_status=sent`：`workflow_full_report.payload.email_status == "success"`。
- `email_delivery_status=failed`：payload 中 `email_status == "failed"`。
- `email_delivery_status=skipped`：payload 中 `email_status == "skipped"` 或 quiet/change mode 未发送。
- `workflow_notification_status=deadletter`：任一当前 run 的 `notification_outbox.status='deadletter'`。
- `workflow_notification_status=sent`：当前 run 的 workflow 通知均为 `sent`。
- `workflow_notification_status=partial`：同时存在 `sent` 和 `pending/failed/claimed/deadletter`。
- `workflow_notification_status=pending`：存在 pending/claimed/failed，但没有 deadletter。

Backfill 必须幂等，重复执行不能覆盖更新的实时状态，除非状态仍为 `unknown` 或显式传入 `force=True`。

---

## 5. 状态同步设计

### 5.1 Workflow 写入

`WorkflowWorker` 在以下节点写状态：

- freeze snapshot 后：`report_generation_status=pending`。
- full report 成功生成产物后：`report_generation_status=generated`。
- report generation 异常且最终进入 attention：`report_generation_status=failed`，`delivery_last_error=error`。
- 业务邮件发送结果从 `full_report["email"]` 写入 `email_delivery_status`。
- workflow full notification 入队后：`workflow_notification_status=pending`。

### 5.2 Notifier 写入

`NotificationWorker` 或 delivery reconcile 在 outbox 状态变化后同步：

- 全部 workflow 通知 sent：`workflow_notification_status=sent`。
- 任一 deadletter：`workflow_notification_status=deadletter`，并保留 `delivery_last_error`。
- 部分 sent、部分 pending/failed：`workflow_notification_status=partial`。

`downgrade_report_phase_on_deadletter()` 保留 `full_sent -> full_sent_local` 降级，但新状态字段才是内部审计的主判断来源。

### 5.3 Manifest 读取

`report_manifest.build_report_manifest()` 优先读取新 DB 状态字段；如果字段不存在或为 `unknown`，才从 artifact/outbox 现场推导。

analytics 回写结构保持：

```json
{
  "report_manifest": {
    "delivery": {
      "report_generated": true,
      "email_delivered": true,
      "workflow_notification_delivered": false,
      "deadletter_count": 3,
      "internal_status": "full_sent_local",
      "db_status": {
        "report_generation_status": "generated",
        "email_delivery_status": "sent",
        "workflow_notification_status": "deadletter"
      }
    }
  }
}
```

---

## 6. 旧 fallback 下线设计

### 6.1 单一 Adapter 边界

允许读取旧 analytics 字段的唯一入口是：

- `report_common.normalize_deep_report_analytics()`
- `report_contract.build_report_user_contract()`

renderer 不再直接拼接以下用户可见内容：

- `top_negative_clusters`
- `report_copy.improvement_priorities`
- `issue_cards`
- `deep_analysis`
- `competitor.negative_opportunities`

这些旧字段只能作为 adapter 输入，转换成 `report_user_contract` 后再渲染。

### 6.2 Strict Mode

新增配置 `REPORT_CONTRACT_STRICT_MODE`：

- 默认 `true`。
- `true`：renderer 缺少 `report_user_contract` 时先自动 adapter，adapter 后仍缺关键字段则记录 validation warning；用户可见区域只消费 contract。
- `false`：允许旧 fallback 渲染，用于紧急兼容旧产物。

### 6.3 Fallback 质量要求

保留 fallback，但改变语义：

- fallback 不再是“模板文案占位”，而是 evidence-bound contract adapter。
- 没有证据的建议不展示为“改良方向”，只进入 `validation_warnings` 或 `evidence_insufficient`。
- LLM 失败不允许让用户看到全量重复建议。

---

## 7. 测试策略

### 7.1 Migration / Status

- 新库初始化应包含 P3 状态字段。
- 旧库执行 migration 后应增加字段。
- backfill 能从 artifacts/outbox 推导 generated/sent/deadletter。
- deadletter 后 `report_phase=full_sent_local`，且 `workflow_notification_status=deadletter`。
- manifest 优先读 DB 状态，字段不存在时回退现场推导。

### 7.2 Renderer Strict

- contract-only analytics 能渲染 HTML / Excel / 邮件。
- 缺 contract 的旧 analytics 先走 adapter，而不是模板直接消费旧字段。
- 模板中不得出现新增的 direct legacy access。
- fallback 建议没有证据时不进入用户可见行动建议。

### 7.3 Artifact Replay

继续使用测试7 replay fixture：

- 断言业务报告不显示运维 deadletter、低覆盖 SKU、估算日期占比。
- 断言 analytics 内部 manifest/status 能看到 deadletter。
- 断言 `report_user_contract.delivery.db_status` 与 DB 状态一致。

---

## 8. 验收标准

1. `workflow_runs` 中可以直接查询本地报告生成、业务邮件发送、workflow 通知送达三个状态。
2. `notification_outbox.deadletter` 出现后，不允许 DB、manifest 或 analytics contract 显示 workflow 通知已送达。
3. 用户业务报告不展示运维诊断；技术人员可通过 run log、运维邮件、manifest/status 追踪。
4. renderer 主路径只消费 `report_user_contract`；旧字段只在 adapter 层出现。
5. 全量测试通过，并新增 migration/status/strict fallback 回归。

---

## 9. P3 后续可选扩展

P3 完成后再考虑：

- 内部 API/MCP：查询某个 run 的 `report_manifest`、run log 路径和 delivery 状态。
- 生产端自动截图归档：将关键 tab 截图作为 `report_artifacts` 记录。
- 简单运维页面：按 logical_date 查看 run、artifact、delivery、deadletter。
