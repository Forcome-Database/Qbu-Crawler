# 测试7报告 P2 生产质量治理设计

**日期**：2026-04-28
**状态**：设计完成，待实施计划执行
**输入文档**：
- `docs/reviews/2026-04-28-production-test7-report-root-cause-and-remediation.md`
- `docs/superpowers/specs/2026-04-28-test7-report-p1-contract-governance-design.md`
- `docs/devlogs/D022-test7-report-p1-contract-governance.md`

---

## 1. 背景

P0/P1 已完成测试7的主要信任修复和 `report_user_contract.v1` 契约层：行动建议、诊断卡、竞品启示、bootstrap digest、delivery contract、测试7最小 replay 以及 heatmap 分数组成等关键问题已经进入回归。

P2 不再重复建设 contract builder，也不做视觉重设计。P2 的目标是把“已修复的语义契约”推进到生产质量治理：让 LLM 只能填固定 slot，让渲染层逐步摆脱旧字段漂移，让 artifact replay 从字符串断言升级到浏览器行为验收，并形成可审计的产物/交付 manifest。P3 再处理 DB 状态模型迁移和旧 fallback 移除。

---

## 2. 目标

1. 将 LLM executive copy 改为 slot-based rewrite：代码决定 bullet 数量和事实槽位，LLM 只改写每个 slot 的中文表达。
2. 增加 contract validation：用户可见建议、诊断卡、heatmap、竞品启示和 delivery 必须满足可追溯规则。
3. 建立 renderer contract-consumption guard：新增主路径必须优先消费 `report_user_contract`，旧 analytics 字段只允许作为显式 fallback。
4. 将测试7 artifact replay 升级为浏览器级验收，覆盖 Tab 切换、诊断卡图片/AI 建议、heatmap 下钻、全景筛选和 bootstrap 文案。
5. 建立 report delivery manifest：从 `report_artifacts`、workflow run 和 outbox 汇总本次报告的产物与送达状态，供内部审计和后续 P3 迁移使用。

---

## 3. 非目标

- 不新增大型视觉改版，不调整页面信息架构。
- 不删除所有旧 analytics fallback；P2 只增加 guard 和迁移清单。
- 不做新 DB migration；`report_artifacts` 已存在，P2 只增加读取/汇总层。
- 不把 workflow 状态字段拆成新列；P3 再设计 `report_generation_status` / `delivery_status` 的持久化迁移。
- 不让 LLM 决定产品集合、证据 ID、风险口径、slot 数量或指标数值。

---

## 4. 核心设计

### 4.1 LLM 固定 Slot

新增 contract 层字段：

```json
{
  "executive_slots": [
    {
      "slot_id": "coverage_snapshot",
      "slot_type": "kpi_summary",
      "locked_facts": {
        "product_count": 8,
        "review_count": 561,
        "coverage_rate": 0.6375
      },
      "default_text": "本次覆盖 8 个产品，采集评论 561 条，样本覆盖率 63.8%。",
      "llm_text": "",
      "source": "deterministic",
      "confidence": "high"
    }
  ]
}
```

固定 slot 建议：
- `coverage_snapshot`：产品数、评论数、覆盖率。
- `translation_quality`：翻译完成率、未翻译数。
- `own_product_health`：自有产品评分、差评率、健康指数。
- `negative_feedback`：负向评论、低分评论、Top 问题簇。
- `action_focus`：需关注产品数、首要行动方向。

规则：
- `executive_bullets` 不再由 LLM 自由返回数组长度。
- `executive_bullets` 由 `executive_slots[*].llm_text or default_text` 派生，最多 5 条。
- LLM prompt 只传 `slot_id`、`default_text`、`locked_facts` 和 evidence pack 摘要。
- LLM 输出只能是 `{ "executive_slot_rewrites": [{"slot_id": "...", "text": "..."}] }`。
- 未命中 slot、包含未知数字或引入未锁定事实时，该 slot 使用 `default_text`。

### 4.2 Contract Validation

新增 `validate_report_user_contract(contract)`，返回 warning 列表，不在内部吞错误。

P2 校验范围：
- `action_priorities`：同一 `label_code` 不重复；`source != evidence_insufficient` 时必须有 `evidence_review_ids` 或 `top_complaint`。
- `issue_diagnostics`：有 `image_evidence` 时必须保留 review id 或 evidence id；有 `failure_modes/root_causes` 时必须可被模板消费。
- `heatmap`：每个非灰 cell 必须有完整产品名、label code、sample size、score composition 和 tooltip。
- `competitor_insights`：每条启示必须有中文摘要、样本数、涉及产品数、验证动作。
- `delivery`：`workflow_notification_delivered=false` 或 `deadletter_count>0` 时，内部状态不得展示为完整送达。
- `executive_slots`：slot id 唯一，派生 bullet 不超过 5。

### 4.3 Renderer Consumption Guard

P2 不删除旧 fallback，但新增测试守卫：
- HTML 关键区域在只给 contract、不提供旧字段时仍能渲染。
- Excel “现在该做什么 / 竞品启示”只给 contract 仍能生成完整内容。
- 邮件 KPI 和 Top actions 只给 contract 仍能渲染。
- 对新增主路径，禁止直接依赖 `top_negative_clusters`、`report_copy.improvement_priorities`、`issue_cards`、`deep_analysis`。

允许的旧字段读取：
- `normalize_deep_report_analytics()` 内部兼容。
- renderer 的 fallback 分支。
- 旧测试 fixture。

### 4.4 浏览器级 Artifact Replay

当前 replay 主要是 HTML 字符串和 Excel 内容断言。P2 增加 Playwright 浏览器验收：
- 打开测试7最小 HTML artifact。
- 逐一点击 Tab：总览、今日变化、问题诊断、产品排行、竞品对标、全景数据、热力图。
- 验证诊断卡图片区域可见。
- 验证 AI 建议、失效模式、可能根因可见。
- 点击 heatmap cell 后，全景产品筛选和标签筛选命中完整产品名。
- 勾选近 30 天筛选时，`data-recent=1` 行数与 contract/KPI 一致。
- bootstrap 下不出现“较昨日 / 较上期 / 今日新增增长”等增量措辞。

浏览器测试不做像素级视觉审美判断，只验证用户关键路径和证据可见性。

### 4.5 Report Delivery Manifest

新增读取层 `qbu_crawler/server/report_manifest.py`，不新增 DB migration。

输入：
- `workflow_runs`
- `report_artifacts`
- `notification_outbox`
- 当前 analytics contract delivery 字段

输出：

```json
{
  "run_id": 1,
  "logical_date": "2026-04-28",
  "generation": {
    "status": "generated",
    "artifacts": [
      {"artifact_type": "snapshot", "path": "...", "bytes": 123, "sha256": "..."}
    ]
  },
  "delivery": {
    "email_delivered": true,
    "workflow_notification_delivered": false,
    "deadletter_count": 3,
    "internal_status": "full_sent_local"
  },
  "warnings": []
}
```

用途：
- 内部审计可以看到“报告已生成，但 workflow 通知未送达”。
- 后续 P3 可以把 manifest 的字段迁移到正式 DB 状态列。
- 用户日报不直接暴露工程失败，但内部状态不能把 deadletter 伪装成 full sent。

---

## 5. 数据流

1. `report_snapshot.py` 生成 snapshot / analytics / Excel / HTML / email body。
2. `_record_artifact_safe()` 继续记录产物到 `report_artifacts`。
3. `report_contract.build_report_user_contract()` 构建 P1 contract。
4. P2 在 contract 中补 `executive_slots` 并校验 contract warnings。
5. `report_llm.py` 只接收 slot rewrite payload，返回 slot 文案。
6. renderer 从 contract 派生 executive bullets、行动建议、诊断卡和 heatmap。
7. `report_manifest.build_report_manifest()` 从 DB 汇总产物和 delivery 状态。
8. replay 浏览器测试用 fixture 重放 HTML 行为。

---

## 6. P2/P3 边界

P2 完成：
- LLM slot-based rewrite。
- contract validation。
- renderer contract-only guard。
- browser replay。
- report manifest 读取层。

P3 延后：
- DB migration：`report_generation_status`、`delivery_status`、`delivery_last_error`。
- 移除旧 analytics fallback。
- report artifact 管理 API / UI。
- 长期指标血缘 catalog 和跨 run diff 审计。
- 生产端自动浏览器截图归档。

---

## 7. 测试策略

### 单元测试

- `test_contract_builds_stable_executive_slots`
- `test_llm_slot_rewrite_rejects_unknown_slot`
- `test_llm_slot_rewrite_keeps_default_text_on_fact_drift`
- `test_validate_contract_flags_action_without_evidence`
- `test_validate_contract_flags_heatmap_cell_without_drilldown_product`
- `test_report_manifest_separates_artifacts_and_delivery`

### 渲染测试

- `test_html_contract_only_renders_all_key_sections`
- `test_excel_contract_only_has_actions_and_competitor_insights`
- `test_email_contract_only_uses_delivery_and_kpis`

### 浏览器 Replay

- `test_test7_replay_browser_tabs_have_expected_content`
- `test_test7_replay_heatmap_click_filters_panorama`
- `test_test7_replay_recent_filter_matches_kpi`

---

## 8. 验收标准

1. LLM 返回 6 条 executive bullet 不再触发重试；正式输出由固定 slots 派生。
2. LLM 不能新增 slot、产品、review id 或未锁定数字。
3. contract validation 能发现证据缺失、heatmap 下钻缺字段和 delivery 状态矛盾。
4. HTML / Excel / 邮件只给 contract 时关键内容仍完整。
5. Playwright replay 能覆盖测试7关键 Tab 和 heatmap 下钻。
6. manifest 能从现有 DB 表汇总 artifacts 与 delivery，且区分本地生成和外部送达。

---

## 9. 推进建议

P2 应先做 LLM slot 和 contract validation，再做 replay 浏览器测试。原因是浏览器 replay 会稳定暴露用户路径问题，如果 contract 还允许自由结构，浏览器测试会反复追着渲染层补洞。

P2 完成后再进入 P3。P3 的核心不是继续补模板，而是做状态模型和旧 fallback 下线：这需要 DB migration、迁移脚本和更长的灰度周期。
