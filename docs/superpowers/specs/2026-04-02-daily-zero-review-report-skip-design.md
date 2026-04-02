# 每日任务零评论跳过完整报告设计

> 日期：2026-04-02
> 状态：已确认，待实现

## 背景

当前每日工作流在任务全部终态后，会统一进入 snapshot 驱动的两阶段汇报：

1. 先发送 `workflow_fast_report`
2. 再生成 Excel、发送邮件，并发送 `workflow_full_report`

现有实现默认“只要进入 `full_pending` 就生成 Excel 并尝试发邮件”。这与新的业务规则不一致：

- 当本次 run 的新增评论数为 0 时，不应该再生成 Excel
- 当本次 run 的新增评论数为 0 时，不应该再发送邮件
- 仍然需要通过钉钉给出一次真实、明确的完成通知

这个变更不是单纯的“邮件策略调整”，而是“0 评论场景不再进入完整报告产物阶段”。

## 目标

1. 当 `reviews_count == 0` 时，工作流直接结束，不生成 Excel，不发送邮件
2. 钉钉通知语义必须真实，不能继续使用“完整报告已生成”描述未生成的报告
3. 保留 snapshot 作为 authoritative 数据边界，避免口径漂移
4. 尽量把决策收敛在 workflow 层，不污染通用报表生成能力

## 非目标

- 不改动普通 `generate_report()` 或 `send_filtered_report()` 的通用行为
- 不重构现有报表模块的数据查询与 Excel 生成逻辑
- 不改变有新增评论时的 fast report / full report 主流程

## 方案对比

### 方案 A：保留 `workflow_full_report`，仅把邮件状态标记为跳过

做法：

- 继续进入 `full_pending`
- 不发送邮件，`email_status` 标记为“已跳过”
- 视情况生成或不生成 Excel

优点：

- 改动最小

缺点：

- 语义失真，`workflow_full_report` 与模板都在表达“完整报告已生成”
- 如果 Excel 也跳过，通知内容与事实不符
- 会把“是否有完整报告产物”与“邮件是否发送”混在一起

结论：不推荐

### 方案 B：保留 fast report，再新增一条“完整报告已跳过”通知

做法：

- 先正常发送 `workflow_fast_report`
- 在 full 阶段发现 `reviews_count == 0` 后，发送新的 skip 通知并结束 run

优点：

- 保持现有快报阶段不变
- 改动相对局部

缺点：

- 0 评论场景会出现两条钉钉消息
- 第一条快报模板仍带有“完整版报告生成后会继续通知”的预期，需要额外修补
- 对用户来说噪音偏大

结论：可行，但不是最优

### 方案 C：snapshot 冻结后直接分流，0 评论只发一条最终跳过通知

做法：

- 任务完成后仍先冻结 snapshot
- 读取 snapshot 后，若 `reviews_count == 0`，直接将 run 标记完成
- 不进入 fast report / full report
- 发送一条新的最终通知，明确说明“新增评论为 0，已跳过 Excel 与邮件”

优点：

- 语义最真实
- 0 评论场景只有一条完成通知，噪音最低
- 决策收敛在 workflow 状态机，报表模块无需承担业务分支
- 仍保留 snapshot 作为可追溯边界

缺点：

- 需要新增一个 notification kind 和对应模板
- 需要引入新的 `report_phase` 终态

结论：推荐

## 推荐设计

采用方案 C。

### 状态机调整

现有路径：

`none -> fast_pending -> fast_sent -> full_pending -> full_sent`

新增分支：

- 在 snapshot 冻结完成后，优先读取 snapshot
- 如果 `snapshot["reviews_count"] == 0`：
  - `status = completed`
  - `report_phase = skipped_no_reviews`
  - `excel_path = NULL`
  - 不调用 full report 生成
  - 不发送邮件
  - 不触发 AI digest
  - 发送 `workflow_report_skipped`
- 如果 `snapshot["reviews_count"] > 0`：
  - 继续现有 fast report / full report 流程

这样 0 评论场景将不再进入“快报”和“完整报告”语义，而是直接走“已完成但报告跳过”的终态。

### 通知语义

新增通知种类：`workflow_report_skipped`

建议 payload 至少包含：

- `run_id`
- `logical_date`
- `snapshot_hash`
- `products_count`
- `reviews_count`
- `reason = "no_new_reviews"`

钉钉模板语义应明确表达：

- 每日任务已完成
- 本次涉及产品数
- 新增评论数为 0
- 已跳过 Excel 生成
- 已跳过邮件发送

模板不应再出现“完整报告已生成”“附件路径”等字样。

### 为什么仍然保留 snapshot

即使 0 评论时跳过报告产物，snapshot 仍有价值：

- 它是 run 的 authoritative 数据边界
- 可以证明“本次确实统计为 0 评论”
- 后续如需排查工作流状态，可依赖 `snapshot_hash` 与 snapshot 文件

因此该方案不是“任务完成就立刻跳过”，而是“先冻结，再基于冻结结果决定跳过”。

### 为什么不把逻辑下沉到 report 层

`report.py` 和 `report_snapshot.py` 当前职责是：

- 读取既定数据范围
- 生成 Excel
- 按参数决定是否发送邮件

“当每日 run 的评论数为 0 时，是否进入完整报告阶段”属于 workflow 编排决策，不属于通用报表能力。

因此推荐把条件判断放在 `WorkflowWorker._advance_run()`，而不是改 `generate_full_report_from_snapshot()` 的内部语义。

## 影响面

### 代码

- `qbu_crawler/server/workflows.py`
  - 在 snapshot 冻结后增加 `reviews_count == 0` 的终态分支
  - 新增 `skipped_no_reviews` 的 `report_phase`
  - 入队 `workflow_report_skipped`
- `qbu_crawler/server/openclaw/bridge/app.py`
  - 新增 `workflow_report_skipped` 模板
- `qbu_crawler/server/openclaw/workspace/TOOLS.md`
  - 同步新的通知模板与语义说明

### 不应改动

- `qbu_crawler/server/report.py`
- `qbu_crawler/server/report_snapshot.py`
- MCP 过滤报表能力

除非实现中发现必须补充一个很小的返回值字段，否则不应把 0 评论分支扩散到这些通用模块。

## 测试策略

至少补以下测试：

1. `tests/test_workflows.py`
   - snapshot `reviews_count == 0` 时：
     - run 最终为 `completed`
     - `report_phase == "skipped_no_reviews"`
     - 不调用 `generate_full_report_from_snapshot`
     - 入队 `workflow_report_skipped`
2. `tests/test_notifier.py`
   - bridge 能正确渲染 `workflow_report_skipped` 模板
3. 回归保护
   - `reviews_count > 0` 的现有 fast/full report 流程保持不变

## 风险与约束

### 风险 1：0 评论时没有快报，用户是否会觉得少了一条通知

这是有意选择。

在 0 评论场景中，“快报”与“最终结果”没有必要拆成两条消息。保留单条最终通知，更符合“只在钉钉里通知即可”的业务意图，也更少噪音。

### 风险 2：新增 `report_phase` 会不会影响已有查询

现有 `report_phase` 本质是字符串状态，不依赖 enum 约束。新增 `skipped_no_reviews` 的风险可控，但需要补测试，避免依赖 `full_sent` 的逻辑误判。

### 风险 3：AI digest 是否需要在 0 评论时触发

不需要。

AI digest 依附于 full report 的后续解释价值。0 评论场景下既无完整报告，也没有值得单独摘要的评论数据，直接跳过即可。

## 最终决策

采用“冻结 snapshot 后直接分流”的方案：

- `reviews_count == 0`：完成 run，只发一条 `workflow_report_skipped` 钉钉通知
- `reviews_count > 0`：维持现有 fast report / full report 流程

这是当前需求与现有架构下语义最真实、噪音最低、维护成本最小的方案。
