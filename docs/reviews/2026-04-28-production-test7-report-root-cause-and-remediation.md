# 测试7生产报告根因分析与产品/架构修复方案

审计对象：`C:\Users\leo\Desktop\生产测试\报告\测试7`

审计日期：2026-04-28

覆盖产物：
- `data/products.db`
- `reports/workflow-run-1-snapshot-2026-04-28.json`
- `reports/workflow-run-1-analytics-2026-04-28.json`
- `reports/workflow-run-1-full-report.html`
- `reports/workflow-run-1-full-report.xlsx`
- `reports/workflow-run-1-email-body.html`
- 报告生成日志片段，尤其是 LLM v3 validation 失败与通知 deadletter

相关代码链路：
- `qbu_crawler/server/report_snapshot.py`
- `qbu_crawler/server/report_analytics.py`
- `qbu_crawler/server/report_common.py`
- `qbu_crawler/server/report_llm.py`
- `qbu_crawler/server/report_html.py`
- `qbu_crawler/server/report.py`
- `qbu_crawler/server/report_templates/daily_report_v3.html.j2`
- `qbu_crawler/server/report_templates/daily_report_v3.js`
- `qbu_crawler/server/workflows.py`
- `qbu_crawler/server/notifier.py`

## 1. 结论摘要

测试7暴露的问题不是单个模板 bug，而是报告系统在“分析事实、LLM 文案、证据包、展示层、交付状态”之间缺少一个稳定的用户级契约。当前链路能成功生成 Excel、HTML 和邮件，但多个位置存在口径错配、字段消费错位和兜底质量不足，导致用户看到的报告在可解释性、可追溯性和行动价值上打折。

从产品经理视角看，报告当前最影响信任的地方有四类：
- 用户看到“改良方向”重复，会判断 AI 建议没有真正理解问题。
- 诊断卡有评论、有图片、有深度分析，但页面没有展示，会让早期版本已有的价值倒退。
- 热力图分数和 tooltip 情绪不一致，会让用户怀疑评分规则本身不可靠。
- Excel 中“竞品启示”出现英文，会破坏“中文业务报告”的交付体验。

从架构师视角看，根因集中在五个层面：
- LLM 输出校验使用的事实边界不一致：prompt 允许按问题簇覆盖产品，校验却只允许 `risk_products`。
- fallback 只保证字段非空，不保证业务差异化、证据可追溯和用户可执行。
- `issue_cards` 不是稳定证据包层，已有的 `image_evidence`、`deep_analysis`、`full_action` 没有统一进入展示契约。
- 指标和 tooltip 没有同一套解释模型，分数、代表评论、下钻筛选各自取值。
- workflow 把“本地报告生成成功”和“外部通知送达成功”混在一个终态里，completed 后不再补偿检查 deadletter。

本轮建议不要继续修零散表面问题，而是按“先契约、再渲染、再体验”的顺序推进。P0 修正误导性和可信度问题；P1 建立报告用户契约层；P2 优化竞品启示和 bootstrap 首日报告体验；P3 建立 artifact replay 回归测试，防止后续报告迭代反复破坏旧问题。

## 2. 测试7事实基线

只读核验结果：

| 项目 | 结果 |
|---|---:|
| 产品数 | 8 |
| 评论数 | 594 |
| `review_analysis` 记录 | 594 |
| 自有产品 | 5 |
| 竞品产品 | 3 |
| 自有评论 | 451 |
| 竞品评论 | 143 |
| 翻译完成率 | 100.0% |
| 近 30 天评论 | 5 |
| 有图评论 | 54 |
| `workflow_runs.status` | `completed` |
| `workflow_runs.report_phase` | `full_sent` |
| `notification_outbox` | 3 条，均 `deadletter`，错误为 `bridge returned HTTP 401` |

关键产物证据：
- `report_copy.improvement_priorities` 共 5 条，但 `full_action` 只有 1 个唯一值，且 5 条 `evidence_review_ids` 全为空。
- `issue_cards` 共 9 张，其中 5 张有 `image_evidence`，但 0 张有 `recommendation`。
- `top_negative_clusters` 中 3 个簇已有 `deep_analysis`，字段包含 `actionable_summary`、`failure_modes`、`root_causes`、`user_workarounds`。
- `competitor.negative_opportunities` 共 5 条，但没有 `headline_cn/body_cn` 字段；数据库中 143 条竞品评论都有中文正文。

## 3. 用户视角的问题地图

### 3.1 管理者

管理者希望在 30 秒内判断“今天是否需要处理”。当前邮件和 HTML 能提供健康指数、差评率、高风险数，但高风险/需关注口径不一致，通知送达失败也没有被终态反映。用户会以为报告已经完整送达，实际外部通知链路失败。

期望体验：
- 一眼区分“报告生成成功”和“通知送达成功”。
- 高风险、需关注、黄灯产品使用同一套口径，文案不互相打架。
- bootstrap 首日明确这是“监控起点”，但仍展示当前需要人工确认的风险。

### 3.2 产品改良负责人

产品改良负责人需要“问题-产品-SKU-证据-图片-AI建议”闭环。当前诊断卡有问题簇和典型评论，但图片证据、深度分析和 AI 建议没有完整展示；Excel 的“改良方向”又重复，导致最该被执行的部分变得像模板文案。

期望体验：
- 每张诊断卡展示代表图片、典型评论、失效模式、可能根因、用户 workaround 和改良建议。
- “现在该做什么”里的每条行动必须有不同 `label_code`、不同 `full_action`、明确证据数和评论 ID。
- 没有高质量 LLM 文案时，规则 fallback 也必须从真实证据生成差异化建议。

### 3.3 数据分析人员

数据分析人员需要知道指标分母、时间窗口、样本数和下钻结果是否一致。当前热力图分数和 tooltip 的代表评论选择规则不一致；产品名被截断后用于下钻，导致点击单元格时产品筛选失效；近 30 天筛选在 HTML 中不读 `date_published_parsed`，会把可识别的新近评论过滤掉。

期望体验：
- tooltip 解释的是当前分数形成原因，而不是随便挑一条最高星级评论。
- 点击热力图能准确筛到同一产品、同一标签、同一代表评论。
- 每个筛选条件使用与 KPI 一致的时间字段和产品标识。

### 3.4 运维与交付

运维人员需要确认 workflow 的真实状态。当前 `notification_outbox` 已全部 deadletter，但 `workflow_runs` 仍是 `completed/full_sent`，这使“报告已生成”和“通知已送达”被混淆。

期望体验：
- 外部通知失败时，report phase 降级为 `full_sent_local` 或单独记录 delivery 状态。
- completed run 仍能被 outbox deadletter 补偿扫描。
- scrape quality 与 delivery quality 分开统计。

## 4. 问题清单与根因

### P0-1：LLM v3 日志报错不是接口失败，而是本地事实校验失败

现象：
- 日志中 HTTP 请求均返回 `200 OK`。
- 随后出现 3 次 `LLM v3 attempt failed`：
  `improvement_priorities[0].affected_products 包含未知产品名: "Walton's #22 Meat Grinder"，应在 risk_products 中: [...]`
- 第 3 次后记录 `LLM v3 generation failed after 3 attempts`。

影响：
- LLM 实际返回了内容，但被本地校验拒绝。
- 链路进入 fallback，导致后续“改良方向”重复、证据 ID 为空、HTML 诊断卡建议缺失。

根因：
- `report_llm.assert_consistency()` 把 `improvement_priorities[].affected_products` 限定为 `risk_products` 中的产品名。
- 但 prompt 中的 `improvement_priorities` 是按“主要问题/问题簇”生成的，问题簇可能覆盖非高风险产品，例如 `Walton's #22 Meat Grinder`。
- 也就是说，LLM 输出契约的事实边界是“问题簇涉及产品”，校验边界却是“风险产品列表”。这是契约错配，不是模型幻觉。

代码位置：
- `qbu_crawler/server/report_llm.py:223`：`assert_consistency()`
- `qbu_crawler/server/report_llm.py:293`：`affected_products` 必须在 `risk_products`
- `qbu_crawler/server/report_llm.py:363`：校验时传入 `analytics.self.risk_products`
- `qbu_crawler/server/report_snapshot.py:1408`：调用 v3 LLM 生成报告文案

修复方案：
- 把 `affected_products` 的合法集合改为 `issue_clusters[label_code].affected_products ∪ risk_products ∪ snapshot products`，其中优先使用同 `label_code` 的问题簇集合。
- 校验错误信息改为“超出当前 label_code 证据产品集合”，并输出 `label_code`，便于定位。
- prompt 中明确：`affected_products` 必须来自对应问题簇的产品集合，不要求必须是高风险产品。
- 单测覆盖：一个非高风险但属于问题簇的产品应通过校验；一个完全不存在于 snapshot 的产品仍应失败。

### P0-2：图一/Excel“改良方向”完全一样，是 fallback 质量不足

现象：
- `report_copy.improvement_priorities` 有 5 条。
- 5 条 `full_action` 完全相同。
- 5 条 `evidence_review_ids` 均为空。
- Excel “现在该做什么”读取 `full_action`，所以“改良方向”全部一样。

影响：
- 用户会认为 AI 建议是复制粘贴，无法指导实际改良。
- 这类重复建议比空建议更危险，因为它看起来像正式结论。

根因：
- LLM v3 被校验拒绝后返回 `_fallback_insights()`，其 `improvement_priorities` 为空。
- `report_snapshot.py` 检测为空后调用 `report_analytics.build_fallback_priorities()`。
- `build_fallback_priorities()` 内部只有一个 `fallback_full_action`，所有产品/问题簇复用同一段长文案。
- fallback 没有消费 `top_complaint`、`example_reviews`、`deep_analysis`、`self.recommendations`、`evidence_review_ids` 等已有证据。

代码位置：
- `qbu_crawler/server/report_snapshot.py:1423`：LLM 空结果时回填 fallback priorities
- `qbu_crawler/server/report_analytics.py:3462`：`build_fallback_priorities()`
- `qbu_crawler/server/report_analytics.py:3481`：单一 `fallback_full_action`
- `qbu_crawler/server/report.py:1005`：Excel 读取 `improvement_priorities`
- `qbu_crawler/server/report.py:1014`：Excel 写入 `full_action`

修复方案：
- fallback 不应再写固定长文案；应按 `label_code` 生成差异化行动：
  - `structure_design`：围绕结构尺寸、适配性、使用路径。
  - `quality_stability`：围绕故障模式、耐久验证、批次追踪。
  - `service_fulfillment`：围绕发货、换货、客服闭环。
  - `material_finish`：围绕材料、表面处理、清洁维护。
  - `assembly_installation`：围绕安装步骤、转接件、说明书。
- fallback 优先取 `deep_analysis.actionable_summary`，其次取 `self.recommendations`，再退回标签模板。
- 每条 priority 必须带 `top_complaint`、`evidence_count`、`evidence_review_ids`、`affected_products`。
- 如果没有证据 ID，不生成“正式建议”，而是显示“证据不足，需补采/人工确认”。

### P0-3：图二诊断卡没有显示评论图片和 AI 建议，是证据包透传与模板消费断裂

现象：
- `issue_cards` 共有 9 张。
- 其中 5 张已有 `image_evidence`：结构设计 2、质量稳定性 1、售后与履约 1、材料与做工 3、安装装配 3。
- `top_negative_clusters` 中 3 个簇已有 `deep_analysis`。
- HTML 模板只渲染 `example_reviews`，没有渲染 `image_evidence` 和 `deep_analysis`。
- `issue_cards.recommendation` 全部为空，所以模板中的 AI 建议框不显示。

影响：
- 用户看到的诊断卡比底层 analytics 少了最有说服力的图片证据和 AI 深度分析。
- 早期版本已有的“评论图片 + AI建议”体验在新版链路中退化。

根因：
- `report_common.normalize_deep_report_analytics()` 构造 `issue_cards` 时，`recommendation` 从 `p.get("action")` 取值。
- 当前 v3 schema 已改为 `full_action`，不是 `action`，因此匹配到 label 后仍得到空字符串。
- `report_snapshot._merge_post_normalize_mutations()` 能把 `deep_analysis` 合并回 `top_negative_clusters`，但 `issue_cards` 没有把这些深度分析字段纳入稳定展示契约。
- 模板 `daily_report_v3.html.j2` 只渲染文字 blockquote，没有渲染 `image_evidence`。

代码位置：
- `qbu_crawler/server/report_common.py:1100`：从 `improvement_priorities` 匹配诊断卡建议
- `qbu_crawler/server/report_common.py:1120`：构造 `image_evidence`
- `qbu_crawler/server/report_common.py:1146`：写入 `issue_cards.image_evidence`
- `qbu_crawler/server/report_common.py:1147`：`recommendation` 使用旧字段
- `qbu_crawler/server/report_snapshot.py:1341`：`deep_analysis` 合并回问题簇
- `qbu_crawler/server/report_snapshot.py:1445`：生成 `deep_analysis`
- `qbu_crawler/server/report_templates/daily_report_v3.html.j2:312`：只渲染评论文本
- `qbu_crawler/server/report_templates/daily_report_v3.html.j2:322`：只有 `card.recommendation` 非空才显示 AI 建议

修复方案：
- `issue_cards` 增加稳定字段：
  - `ai_recommendation`: 优先 `priority.full_action`，其次 `deep_analysis.actionable_summary`，再其次规则 fallback。
  - `failure_modes`: 来自 `deep_analysis.failure_modes`。
  - `root_causes`: 来自 `deep_analysis.root_causes`。
  - `user_workarounds`: 来自 `deep_analysis.user_workarounds`。
  - `image_evidence`: 继续保留，模板必须消费。
- 模板在每张诊断卡中增加“图片证据”区域，最多展示 3 张缩略图，并保留评论 ID/证据编号。
- AI 建议框不直接依赖旧字段 `action`，统一读 `ai_recommendation`。
- 没有图片时显示文本证据；有图片但加载失败时显示图片 URL 或证据编号，不让证据静默消失。

### P0-4：图三热力图 tooltip 与分数不匹配，是评分规则、代表评论和下钻标识三者不一致

现象：
- 热力图中部分单元格显示 100%，但 tooltip 可能出现带明显抱怨语义的评论。
- 例如 `Walton's General Duty Meat Lug` 的售后与履约单元格为 100%，代表评论内容包含“1个到货时就损坏了，不过他们很快补发”，这是一条 mixed 评论。
- `Walton's Quick Patty Maker` 的结构设计分数较高，但代表评论也可能是“肉饼太大”的混合抱怨。
- 点击热力图下钻时，`data-product` 使用截断名，例如 `Walton's Quick Patty`，而全景筛选下拉使用完整产品名 `Walton's Quick Patty Maker`，导致产品筛选无法命中，只剩标签筛选生效。

影响：
- 用户会质疑“100%为什么弹出差评”。
- 点击热力图后看到的全景数据不一定是当前单元格对应产品，削弱可追溯性。

根因：
- `_classify_review_positive()` 把 `positive` 和 `mixed` 都算作正向，因此含抱怨但总体好评的 mixed 评论会推高分数。
- `_build_heatmap_cell()` 的代表评论选择规则是“最高星级 + 正文最长”，不是“最能解释当前分数的评论”。
- tooltip 展示的是单条 `top_review_excerpt`，没有告诉用户该单元格的正/混/负构成。
- 模板把截断后的 `y_label` 写进 `data-product`，JS 直接用它设置全景筛选器。

代码位置：
- `qbu_crawler/server/report_analytics.py:1841`：`_classify_review_positive()`
- `qbu_crawler/server/report_analytics.py:1858`：`mixed` 计入正向
- `qbu_crawler/server/report_analytics.py:1896`：代表评论按最高评分和最长正文选择
- `qbu_crawler/server/report_templates/daily_report_v3.html.j2:581`：热力图单元格
- `qbu_crawler/server/report_templates/daily_report_v3.html.j2:582`：`data-product="{{ y_label }}"`
- `qbu_crawler/server/report_templates/daily_report_v3.js:701`：`productSelect.value = product`
- `qbu_crawler/server/report_templates/daily_report_v3.html.j2:613`：全景筛选使用完整产品名

这是规则问题还是 bug：
- `mixed` 计入正向本身是一个产品规则选择，不一定错；但当前页面没有解释这个规则。
- tooltip 选取和下钻产品截断是实现 bug，会直接造成解释错位。
- 最佳修复不是简单把 mixed 改成负向，而是把热力图指标定义从“正向率”升级成“体验健康度”，并展示构成。

修复方案：
- 热力图 cell 增加 `positive_count`、`mixed_count`、`negative_count`、`neutral_count`、`sample_size`。
- tooltip 改为：
  - `体验健康度 100%：正向 X 条，混合 Y 条，负向 0 条，样本 N 条`。
  - 代表评论按解释目标选择：绿色显示正向代表，黄色优先显示 mixed/边界评论，红色显示负向代表。
- `mixed` 默认建议按 0.5 权重计入健康度，而不是 1.0。公式示例：
  `score = (positive_count + 0.5 * mixed_count) / sample_size`
- 如果业务希望 mixed 继续算正向，页面必须把 legend 改成“正向/混合占比”，不能叫“正向率”。
- 热力图数据结构中保留完整 `product_name` 和展示用 `product_label`，模板 `data-product` 使用完整名，单元格文本使用短名。
- 点击下钻后验证 product select、label select、review highlight 三者同时命中。

### P0-5：Excel“竞品启示”部分英文，是中文字段在 analytics 层丢失

现象：
- 数据库中 143 条竞品评论都有 `body_cn`。
- `competitor.negative_opportunities` 共 5 条，但每条都没有 `headline_cn/body_cn`。
- Excel `_theme_example()` 优先中文，没有中文才回退英文，因此短板行显示英文。

影响：
- 破坏中文日报体验。
- 用户需要自行翻译竞品短板评论，降低报告可用性。

根因：
- `report_analytics._negative_opportunities()` 构造竞品短板时只保留 `headline/body`，未保留 `headline_cn/body_cn`。
- Excel 侧逻辑是正确的，但上游字段缺失。

代码位置：
- `qbu_crawler/server/report_analytics.py:1406`：`_negative_opportunities()`
- `qbu_crawler/server/report_analytics.py:1415`：写入竞品短板字段
- `qbu_crawler/server/report.py:1126`：`_theme_example()` 优先中文字段

修复方案：
- `_negative_opportunities()` 保留 `headline_cn`、`body_cn`。
- 所有面向用户的示例评论统一使用 `display_headline`、`display_body`，由 analytics 层先完成中英文降级。
- 增加回归测试：当 DB 有中文翻译时，Excel “竞品启示/短板”不得出现英文正文。

### P0-6：全景“近30天”筛选与 KPI 口径不一致

现象：
- 顶部 KPI 显示近 30 天评论 5。
- HTML 全景数据行 `data-recent` 由 `_annotate_reviews()` 计算。
- `_annotate_reviews()` 只读取 `date_published`，不读取 `date_published_parsed`。
- 测试7中很多日期依赖 `date_published_parsed` 才能判断近 30 天，导致勾选近 30 天后可能筛不出正确行。

影响：
- KPI 和可下钻数据不一致。
- 用户点击筛选后会以为近 30 天评论不存在。

根因：
- 分析层用 `date_published_parsed` 计算 `recently_published_count`。
- HTML 注解层只用原始 `date_published`。

代码位置：
- `qbu_crawler/server/report_html.py:22`：`_annotate_reviews()`
- `qbu_crawler/server/report_templates/daily_report_v3.html.j2:649`：全景行写入 `data-recent`

修复方案：
- `_annotate_reviews()` 优先读取 `date_published_parsed`，再回退 `date_published`。
- 如果日期是估算值，应额外写入 `date_estimated`，前端可以显示“估算日期”提示。
- 增加测试：KPI 近 30 天数量应等于全景 `data-recent=1` 行数。

### P0-7：高风险产品和需关注产品口径不一致

现象：
- HTML KPI “高风险产品”按 `risk_score >= HIGH_RISK_THRESHOLD` 计算。
- 邮件“需关注产品”按红灯 + 黄灯产品计算。
- 测试7中 HTML 顶部高风险产品为 2，邮件需关注产品为 3，用户看起来像报告互相矛盾。

影响：
- 管理者无法判断到底有几款产品需要处理。
- 跨邮件、HTML、Excel 的指标一致性受损。

根因：
- `high_risk_count` 是严格红线指标。
- `attention_count` 是运营关注指标。
- 两者都是有价值的，但当前文案没有明确区分。

代码位置：
- `qbu_crawler/server/report_common.py:996`：`high_risk_count`
- `qbu_crawler/server/report_templates/email_full.html.j2:73`：需关注产品按黄灯 + 红灯计算
- `qbu_crawler/server/report_analytics.py:1183`：产品 `status_lamp` 判定

修复方案：
- 指标命名统一：
  - `high_risk_count`：红灯产品数。
  - `attention_product_count`：红灯 + 黄灯产品数。
  - `watchlist_product_count`：可作为 `attention_product_count` 的显示别名。
- 邮件和 HTML 同时展示时用同一组字段，不在模板里各自临时计算。
- KPI 卡片文案改为“高风险产品 2 / 需关注产品 3”，并提供 tooltip 解释阈值。

### P0-8：通知 deadletter 后 workflow 仍显示 full_sent，是状态机边界不完整

现象：
- `notification_outbox` 3 条均为 `deadletter`，错误为 `bridge returned HTTP 401`。
- `workflow_runs.status = completed`，`report_phase = full_sent`。
- 代码已有 `downgrade_report_phase_on_deadletter()`，但实际没有降级。

影响：
- 运维层误以为外部通知已送达。
- 后续告警、复盘和自动重试依据不可靠。

根因：
- `WorkflowWorker.process_once()` 只扫描 active statuses：`submitted/running/reporting`。
- run 进入 `completed` 后，不再进入 `_advance_run()`，因此补偿检查没有机会执行。
- `scrape_quality` 统计关注采集质量，不应承担完整 delivery 状态判断。

代码位置：
- `qbu_crawler/server/workflows.py:508`：只处理 active statuses
- `qbu_crawler/server/workflows.py:566`：deadletter 降级检查位于 `_advance_run()`
- `qbu_crawler/server/notifier.py:343`：`downgrade_report_phase_on_deadletter()`

修复方案：
- 把 delivery reconcile 从 `_advance_run()` 中拆出，独立扫描最近 N 天 `report_phase='full_sent'` 且存在 outbox 的 run。
- 或者让 `NotificationWorker` 在写入 `deadletter` 时同步调用降级函数。
- 最佳方案是增加独立字段：
  - `report_generation_status`: local artifact 生成状态。
  - `delivery_status`: pending/sent/deadletter/partial。
  - `report_phase` 只保留业务阶段，不承载外部投递结果。
- completed 不代表 delivery 成功，邮件和运维界面必须区分。

### P1-1：诊断卡和行动建议缺少统一的 `report_user_contract`

现象：
- `top_negative_clusters` 有问题簇。
- `report_copy.improvement_priorities` 有行动建议。
- `issue_cards` 有展示卡。
- `self.recommendations`、`deep_analysis`、`image_evidence` 分散在不同层。
- 模板直接消费这些分散字段，字段名一变就断。

影响：
- 每次迭代 LLM schema 或 analytics 结构，都可能造成 HTML/Excel 部分缺字段。
- 用户看到的报告不是底层事实的完整呈现。

根因：
- 缺少“面向用户的证据包契约层”。
- `normalize_deep_report_analytics()` 同时承担归一化、展示组装、字段降级、文案桥接，边界过宽。

修复方案：
- 新增稳定契约 `report_user_contract`，作为 HTML/Excel/邮件的唯一展示输入之一。
- 建议结构：

```json
{
  "issue_diagnostics": [
    {
      "label_code": "structure_design",
      "label_display": "结构设计",
      "severity": "high",
      "affected_products": ["..."],
      "evidence_count": 18,
      "evidence_review_ids": [1, 2, 3],
      "text_evidence": [{"review_id": 1, "display_body": "..."}],
      "image_evidence": [{"review_id": 2, "url": "..."}],
      "ai_summary": "...",
      "failure_modes": [],
      "root_causes": [],
      "recommended_action": "..."
    }
  ],
  "action_priorities": [
    {
      "label_code": "structure_design",
      "short_title": "...",
      "full_action": "...",
      "source": "llm|deep_analysis|rule_fallback",
      "evidence_review_ids": [1, 2, 3],
      "affected_products": ["..."]
    }
  ],
  "heatmap": {
    "metric_name": "体验健康度",
    "formula": "(positive + 0.5 * mixed) / sample_size",
    "cells": []
  }
}
```

验收标准：
- 模板不直接从 `top_negative_clusters` 拼诊断卡。
- Excel 不直接猜 `action/full_action`，只读 `action_priorities.full_action`。
- 任一用户可见建议都能追溯到 `evidence_review_ids`。

### P1-2：竞品启示需要从“评论堆砌”升级为“可借鉴/需避坑/可验证假设”

现象：
- 当前“竞品启示”混合展示竞品好评和竞品差评。
- 长评论直接进 Excel，用户需要自行提炼。
- `weakness_opportunities` 与 `gap_analysis` 口径不同，但 UI 没解释。

影响：
- 竞品页看起来有信息，但不够像产品决策材料。
- 用户很难把竞品评论转成自有产品动作。

修复方案：
- 竞品启示分三类：
  - `可借鉴`：竞品被反复认可的产品形态、卖点或服务。
  - `需避坑`：竞品差评暴露的设计或履约风险。
  - `可验证假设`：自有产品下一轮要验证的机会点。
- 每条启示必须包含：
  - 样本数、涉及产品数、代表评论中文摘要。
  - 对自有产品的启发。
  - 建议验证动作，例如“检查说明书是否覆盖转接件兼容性”。
- Excel 中长评论只保留摘要，另在评论原文 sheet 保留全文和 review ID。

### P1-3：bootstrap 首日报告应从“今日变化”改为“监控起点 + 当前风险”

现象：
- 当前 `bootstrap` 下“今日变化”已经避免使用“今日新增”措辞，这是正确的。
- 但页面只显示单卡，隐藏了已经计算出的 `immediate_attention`，首日用户仍需要知道当前风险。

影响：
- 首日报告对管理者不够有行动价值。
- 用户可能误以为首日不需要处理任何问题。

修复方案：
- `bootstrap` 下保留“监控起点”主语，但展示三类内容：
  - 当前截面：产品数、评论数、覆盖率、翻译率。
  - 数据质量：历史补采占比、估算日期占比、低覆盖产品。
  - 即时关注：红/黄灯产品、Top 问题簇、需人工确认项。
- 禁止出现“较昨日、较上期、新增增长”等增量措辞。
- 增量期才展示真正的变化趋势和变化归因。

### P2-1：指标血缘和 artifact replay 回归测试需要产品化

现象：
- 同一个指标在邮件、HTML、Excel 中可能由不同模板直接计算。
- 产物问题主要在渲染与字段契约层，普通单元测试不容易覆盖。

修复方案：
- 建立 artifact replay 测试：用测试7 snapshot/analytics 的脱敏 fixture 重放 HTML/Excel 渲染。
- 回归断言：
  - `improvement_priorities.full_action` 不允许全量重复。
  - `issue_cards` 有 `image_evidence` 时 HTML 必须出现图片区域。
  - 有 `deep_analysis` 时 HTML 必须出现 AI 分析摘要。
  - `negative_opportunities` 有中文源数据时 Excel 不得回退英文。
  - heatmap 点击使用完整产品名。
  - KPI 近 30 天数量等于全景筛选数量。
  - outbox deadletter 后 delivery 状态不可显示为完全送达。
- 对核心指标建立 `metric_definitions` 或最小指标字典：字段名、公式、分母、时间窗口、来源、展示位置。

## 5. 推荐实施顺序

### 第一阶段：P0 可信度修复

目标：消除会直接误导用户的报告问题。

任务：
1. 修复 LLM `affected_products` 校验边界，避免正确输出被拒绝。
2. 重写 `build_fallback_priorities()`，保证 fallback 建议差异化且带证据。
3. 修复 `issue_cards.recommendation` 字段，使用 `full_action`，并透传 `deep_analysis`。
4. HTML 诊断卡展示图片证据和 AI 建议。
5. 修复热力图完整产品名下钻、tooltip 代表评论和分数组成。
6. `_negative_opportunities()` 保留中文字段。
7. `_annotate_reviews()` 使用 `date_published_parsed`。
8. delivery deadletter 降级从 active workflow 中拆出。

建议验收：
- 用测试7产物重放后，“改良方向”不再完全重复。
- 诊断卡至少展示 5 组图片证据，3 组 AI 深度分析。
- Excel “竞品启示/短板”中文率为 100%。
- 热力图点击 `Walton's Quick Patty Maker` 能筛中完整产品。
- `notification_outbox.deadletter` 存在时，不允许 `delivery_status=sent`。

### 第二阶段：P1 契约层治理

目标：把用户可见报告从散落字段改为稳定证据包。

任务：
1. 设计并实现 `report_user_contract`。
2. HTML、Excel、邮件统一消费 contract。
3. 将 `issue_cards`、`action_priorities`、`heatmap` 的 display 字段在 analytics 层一次性生成。
4. 对竞品启示进行信息架构改造。
5. bootstrap 首日报告改为“监控起点 + 当前风险”。

建议验收：
- 模板不再直接判断 `action`/`full_action` 等 schema 版本差异。
- 每条用户可见建议有 `source` 和 `evidence_review_ids`。
- 每个用户可见指标有公式和分母说明。

### 第三阶段：P2/P3 质量体系

目标：让报告迭代具备持续可验证能力。

任务：
1. 建立测试7 artifact replay fixture。
2. 增加 HTML DOM 断言和 Excel 内容断言。
3. 增加 Playwright 截图检查关键 tab。
4. 建立指标字典和报告产物表 `report_artifacts`。
5. 把 delivery 状态从 workflow phase 中拆分出来。

建议验收：
- 每次报告改动都能用固定产物重放。
- UI 回归能覆盖“图片证据、AI建议、热力图下钻、近30天筛选、竞品中文”。
- workflow run 可以完整追踪 snapshot、analytics、Excel、HTML、邮件 body、delivery 结果。

## 6. 关键设计原则

### 6.1 报告不能只保证“生成成功”，还要保证“解释可信”

当前链路已经能生成产物，但用户真正需要的是可信的解释闭环。只要存在“100% 却弹差评”“AI建议重复”“有图片但不显示”这类体验，用户就会怀疑整份报告。P0 修复应优先处理这类信任破坏点。

### 6.2 fallback 也是正式产品体验

LLM 不可用或被校验拒绝时，fallback 会直接进入日报。它不能只是兜底占位，而必须满足最低产品质量：差异化、证据化、可执行、可追溯。否则 fallback 产物会在生产中制造更大的误导。

### 6.3 展示层不要理解分析层内部结构

HTML 和 Excel 不应知道 `action`、`full_action`、`deep_analysis`、`top_negative_clusters` 哪个字段在哪一层。展示层应该消费 `report_user_contract` 中已经整理好的字段。这样未来 LLM schema 变更，不会让页面静默丢失建议。

### 6.4 指标必须带分母、窗口和解释规则

热力图、高风险、近 30 天、覆盖率、健康指数都需要明确：
- 计算对象是谁。
- 时间窗口是什么。
- 分母是什么。
- mixed/neutral 如何计分。
- 是否为 bootstrap 基线期。

只展示结果数字，不展示规则，会导致用户在看到边界案例时误判系统出错。

## 7. 测试清单

### 单元测试

- `test_llm_assert_consistency_allows_issue_cluster_products`
- `test_llm_assert_consistency_rejects_unknown_snapshot_product`
- `test_fallback_priorities_are_distinct_and_evidence_bound`
- `test_issue_cards_use_full_action_not_legacy_action`
- `test_issue_cards_include_deep_analysis_fields`
- `test_negative_opportunities_preserve_cn_fields`
- `test_annotate_reviews_uses_date_published_parsed`
- `test_heatmap_cell_score_counts_mixed_weight`
- `test_heatmap_cell_uses_full_product_name_for_filter`
- `test_outbox_deadletter_downgrades_completed_run_delivery_status`

### Artifact replay 测试

- 使用测试7 snapshot/analytics fixture 渲染 HTML。
- 断言诊断卡图片区域存在。
- 断言 AI 建议区域存在且非空。
- 断言“改良方向”不全相同。
- 断言热力图单元格 `data-product` 为完整产品名。
- 断言近 30 天筛选行数与 KPI 一致。
- 使用测试7 fixture 渲染 Excel。
- 断言“竞品启示”短板行不出现英文正文。

### 浏览器验收

逐一打开 HTML 各 tab：
- 总览：高风险/需关注口径解释一致。
- 今日变化：bootstrap 首日不出现增量误导措辞。
- 问题诊断：图片证据、AI建议、失效模式可见。
- 产品排行：红/黄灯产品与 KPI 数一致。
- 竞品对标：启示有中文摘要、样本数、验证动作。
- 全景数据：近 30 天、有图、产品、标签筛选准确。
- 热力图：tooltip 解释分数组成，点击能筛中对应行。

## 8. 最终建议

建议将测试7问题作为报告系统一次“小型架构治理”处理，而不是分散修模板。优先级如下：

1. 先修 P0，恢复用户对报告的基本信任：LLM 校验、fallback、诊断卡、热力图、中文字段、近 30 天、delivery 状态。
2. 再做 P1，把 `report_user_contract` 作为 HTML/Excel/邮件共同输入，减少 schema 演进造成的展示断裂。
3. 最后补 P2/P3，用 artifact replay 固化这次事故样本，避免后续优化再次引入“底层有数据，页面不显示”的回归。

如果只允许短期交付一个版本，建议最小可行修复范围为：
- 修复 LLM `affected_products` 校验边界。
- fallback priorities 差异化并绑定证据。
- 诊断卡展示 `image_evidence` 和 `deep_analysis.actionable_summary`。
- 热力图使用完整产品名下钻，并把 tooltip 改成“分数组成 + 代表评论”。
- `_negative_opportunities()` 保留中文字段。
- outbox deadletter 触发 completed run 的 delivery 降级。

这 6 项覆盖了用户已明确指出的核心问题，也能最大程度恢复报告的专业可信度。

## 9. 与当前修复要求的逐项对照

本节用于把测试7最新问题总结中的修复要求，明确映射到本文档中的落地方案，避免后续实施时只修表面症状。

| 修复要求 | 是否覆盖 | 文档落点 | 说明 |
|---|---|---|---|
| 不把问题归因成某个 Tab 写错或 LLM 偶发胡说，而是上升到统一用户语义契约 | 已覆盖 | 第 1 节、第 6 节、P1-1 | 文档明确把根因定义为分析事实、LLM 文案、证据包、展示层、交付状态之间缺少稳定契约。 |
| 新增 `report_user_contract`，让邮件、HTML、Excel 只消费统一语义层 | 已覆盖 | P1-1 | 已给出 `issue_diagnostics`、`action_priorities`、`heatmap` 的建议结构。 |
| 每个字段声明时间口径、产品集合、分母、bootstrap 状态、置信度 | 已覆盖，但需要实施时细化字段 schema | 第 6.4 节、P1-1、P2-1 | 文档已要求指标带分母、窗口、解释规则，并建议建立 `metric_definitions`；实施计划中应把这些字段写进 contract schema。 |
| 行动建议先由规则层生成 evidence pack，LLM 只负责把锁定事实写成人话 | 已覆盖，建议实施时作为硬约束 | P0-2、P1-1、第 6.2 节 | 已要求 fallback 和 action priorities 绑定 `label_code`、证据评论 ID、典型原话、图片证据、失效模式和根因。后续编码时应禁止 LLM 自行决定事实集合。 |
| `affected_products` 按每条 priority 的 `allowed_products` 校验，而不是全局套用 `risk_products` | 已覆盖 | P0-1 | 文档建议合法集合改为 `issue_clusters[label_code].affected_products ∪ risk_products ∪ snapshot products`，优先按同 label 的问题簇校验。 |
| fallback 必须产出差异化行动建议、证据 ID 和典型原话 | 已覆盖 | P0-2、第 7 节 | 已要求每条 priority 带 `top_complaint`、`evidence_count`、`evidence_review_ids`、`affected_products`，并增加回归测试。 |
| 没有证据就不展示成建议，而展示为“证据不足” | 已覆盖 | P0-2、第 6.2 节 | 文档明确要求无证据 ID 时不生成正式建议。 |
| 时间字段统一：入库窗口看 `scraped_at`，近 30 天看 `date_published_parsed`，原始 `date_published` 只展示 | 已覆盖 | P0-6、第 6.4 节 | 已定位 `_annotate_reviews()` 只读原始日期的问题，并要求优先读 `date_published_parsed`。 |
| 风险口径统一：高风险和需关注拆成不同字段，不在模板里各算各的 | 已覆盖 | P0-7 | 已建议新增 `attention_product_count`，并区分 `high_risk_count` 与红黄灯关注产品。 |
| 运维状态拆开：报告生成、邮件送达、workflow 通知送达分别记录 | 已覆盖 | P0-8、P2-1 | 已建议拆成 `report_generation_status`、`delivery_status`，并建立 artifact / delivery 追踪。 |
| 用户报告不暴露工程失败，但内部状态不能把 deadletter 伪装成 full sent | 已覆盖，需实施时区分内外展示 | P0-8、3.4 | 文档强调 completed 不代表 delivery 成功；后续可以在内部运维视图展示 deadletter，对外日报只提示“本地报告已生成”。 |
| HTML 各 Tab 的体验问题：总览口径、今日变化 bootstrap、问题诊断缺深度、竞品启示堆砌、全景近 30 天筛选失效 | 已覆盖 | P0-3、P0-6、P1-2、P1-3、第 7 节 | 已逐项拆成诊断卡、全景筛选、竞品启示、bootstrap 首日报告和浏览器验收清单。 |
| 终端日志中 HTTP 200 但本地 LLM 校验失败 | 已覆盖 | P0-1 | 已明确这不是接口失败，而是 `assert_consistency()` 的事实边界错配。 |

结论：当前文档已经覆盖这段总结中的修复方向。后续如果进入编码阶段，建议先把第 9 节转成实施计划 checklist，并以 P0-1 到 P0-8 作为第一批最小修复范围。
