# D022 测试7报告 P1 语义契约治理

日期：2026-04-28

## 背景

测试7暴露的问题不是单个 Tab 或单次 LLM 输出异常，而是报告展示层缺少统一的用户语义契约：产品集合、时间口径、风险口径、证据评论、LLM 文案和送达状态在 HTML、Excel、邮件中分别取数，导致同一份报告出现互相矛盾的解释。

P0 已先修复最容易伤害用户判断的语义错配；P1 的目标是把轻量 `report_user_contract` 升级为独立、可回归、可逐步迁移的 contract builder。

## 实现范围

- 新增 `qbu_crawler/server/report_contract.py`，固定 `schema_version=report_user_contract.v1`。
- contract 顶层字段包括：`metric_definitions`、`kpis`、`action_priorities`、`issue_diagnostics`、`heatmap`、`competitor_insights`、`bootstrap_digest`、`delivery`、`validation_warnings`。
- `issue_diagnostics` 从 `self.top_negative_clusters` 生成 evidence pack，保留图片证据、典型评论 ID、失效模式、可能根因和用户应对。
- LLM v3 prompt 改为只消费 `report_user_contract.issue_diagnostics` 派生出的 evidence payload；LLM copy merge 只允许落在对应 label 的 allowed products 和 evidence review ids 内。
- `report_common.normalize_deep_report_analytics()` 只挂载缺少 snapshot 的临时 contract；HTML 最终渲染入口会用真实 snapshot 刷新 contract。
- HTML、Excel、邮件开始优先消费 contract：行动建议、问题诊断、竞品启示、bootstrap 摘要和邮件 KPI 已迁移，旧字段保留 fallback。
- `competitor_insights` 拆成 `learn_from_competitors`、`avoid_competitor_failures`、`validation_hypotheses`，每条补齐中文摘要、对自有产品启发、验证动作、证据 ID、样本数、涉及产品数。
- `bootstrap_digest` 固化“监控起点 / 当前截面 / 数据质量 / 立即关注”，避免 bootstrap 下出现“较昨日 / 较上期 / 新增增长”之类增量措辞。
- `delivery` 拆分 `report_generated`、`email_delivered`、`workflow_notification_delivered`、`deadletter_count` 和 `internal_status`。

## 回归护栏

- 新增 `tests/server/test_report_contract.py` 覆盖 contract builder 的字段、指标定义、证据包、竞品启示、bootstrap digest 和 delivery。
- 新增 `tests/server/test_report_contract_llm.py` 覆盖 LLM evidence-only payload 和 copy merge 校验。
- 新增 `tests/server/test_report_contract_renderers.py` 覆盖 HTML / Excel / 邮件只给 contract 时仍能渲染。
- 新增 `tests/fixtures/report_replay/` 和 `tests/server/test_test7_artifact_replay.py`，用脱敏最小测试7样本固定图片证据、行动建议去重、竞品启示、delivery deadletter 和三类渲染消费者。

## 未纳入 P1

- 不新增 DB migration，也不引入 `report_artifacts` 表。
- 不做 HTML 视觉重设计。
- 不做完整生产 artifact 管理平台。
- 不把所有旧 analytics 字段一次性删除；当前阶段保留 fallback，后续 P2/P3 再逐步收口。

## 2026-04-28 生产 P1 回归修复

生产 P1 日志显示 LLM HTTP 请求均为 200，失败发生在本地 schema 校验：`executive_bullets` 稳定返回 6 条，超过 v3 schema 的 `maxItems=5`。根因是 P1 evidence-only prompt 删除了旧示例里的数量约束，而 evidence payload KPI 较多，模型倾向逐项复述指标。

本次修复：

- `report_llm.normalize_llm_copy_shape()` 在 schema 校验前做确定性结构归一，`executive_bullets` 超过 5 条时本地截断，避免把可修复格式问题交给 retry。
- v3 prompt 明确 `executive_bullets <= 5; recommended 3`，并要求合并相关指标，不逐项复述 KPI。
- `report_common` 生成的 rich `issue_cards` 补齐 `text_evidence`，确保 LLM evidence payload 能拿到典型用户原话。
- `merge_llm_copy_into_contract()` 不再把非法 LLM action 原样展示为 `evidence_insufficient`；改为回退到对应诊断卡的锁定证据 action，并标记 `source=evidence_fallback`。
- `_merge_post_normalize_mutations()` 支持传入真实 snapshot，full report 的 Excel / 邮件路径也能拿到 `snapshot_source=provided` 的最终 contract。
- bootstrap 标题兼容“首日基线已建档”和“监控起点已建立”两种既有产品语义。

验证：

- 报告回归：`452 passed, 3 skipped`
- 全量回归：`933 passed, 3 skipped`
