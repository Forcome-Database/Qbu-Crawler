# 生产测试 5 全量报告产物审计（Codex）

审计对象：`C:\Users\leo\Desktop\生产测试\报告\测试5`

审计日期：2026-04-26

审计范围覆盖：

- 数据库：`data/products.db`
- Snapshot：`reports/workflow-run-1-snapshot-2026-04-26.json`
- Analytics：`reports/workflow-run-1-analytics-2026-04-26.json`
- HTML：`reports/workflow-run-1-full-report.html`
- Excel：`reports/workflow-run-1-full-report.xlsx`
- 邮件截图：`email.png`
- 相关实现：`qbu_crawler/models.py`、`qbu_crawler/server/report_snapshot.py`、`qbu_crawler/server/report_analytics.py`、`qbu_crawler/server/report_common.py`、`qbu_crawler/server/report.py`、`qbu_crawler/server/report_templates/daily_report_v3.html.j2`

## 1. 总体结论

当前报告体系已经具备“生产可运行”的基本闭环：爬虫任务完成后，数据进入 SQLite，生成 snapshot，再进入 analytics、Excel、HTML 和邮件摘要；本次测试 5 中，8 个产品、561 条评论、561 条翻译与分析记录均已入库，Excel 和 HTML 主体产物也已成功生成。报告还正确识别了 `bootstrap` 首次建档语义，并在“今日变化”中提示“本次入库以历史补采为主，占比 99%”以及“相对时间估算较多”，这是非常重要的语义治理进步。

但从“可决策、可追溯、可持续演进”的标准看，当前体系仍不是最佳实现。主要问题不是某一个页面或某一个指标错了，而是多个层面存在口径漂移：标签有 `review_analysis.labels` 和 `review_issue_labels` 两条链路；产品差评率在不同位置混用了“采集评论数分母”和“站点展示评论数分母”；风险分说明和实际算法不一致；趋势页在首日 bootstrap 场景下仍把极小样本呈现为可读趋势。这些问题会让业务读者看到“结果”，但难以判断结果的可信度和行动优先级。

核心优点：

- 数据链路主体完整：`products`、`reviews`、`review_analysis`、`snapshot`、`analytics`、`Excel`、`HTML` 均能串起来。
- 首日建档语义明确：`analytics.report_semantics = bootstrap`，HTML/Excel 均有“监控起点/首次建档/补采为主”的提示。
- 数据覆盖面较宽：本次覆盖 8 个产品、3 个站点、561 条评论，自有评论 418 条，竞品评论 143 条，翻译完成率 100%。
- 报告具有分析雏形：包含健康指数、差评率、样本覆盖率、问题诊断、风险产品、竞品对标、评论全景和图片证据。
- Excel 明细可回溯到评论行：评论 ID、SKU、原文、中文、标签、情感、洞察、评论时间均有输出。

核心问题：

- 标签口径双轨：数据库规范化表 `review_issue_labels` 为 951 行，但 Excel“问题标签”输出 997 行，并泄漏 `durability`、`neutral` 等未规范化值，说明 Excel 仍直接读取原始 LLM labels。
- 趋势可信度不足：首日只有 8 个产品快照点，月视图仅 3 条近 30 天评论，却展示 `ready` 状态；年视图基于多年历史评论发布时间，不代表系统连续监控趋势。
- 风险与差评率口径不统一：风险产品使用站点评论数作为分母，非风险产品回退为采集评论数分母；用户无法从页面直接判断分母差异。
- 数据链路仍有断点：`review_analysis.failure_mode` 在 DB 中有值，但 Excel“失效模式”列 561 行均为空；HTML/Excel 不完整消费已有分析字段。
- HTML 可读性存在明显瑕疵：总览“建议行动”标题被截断成半句话，产品排行徽标显示 5 个自有产品但表格仅列 2 个风险产品，竞品对标缺少分母和差距解释。
- 可追溯性不足：`workflow_runs` 记录了 snapshot、Excel、analytics 路径，但未记录 HTML 路径；`pdf_path` 为 `NULL`，生产目录也未见 PDF，报告产物管理未完全结构化。
- 运维通知链路异常：`notification_outbox` 3 条均为 `deadletter`，错误为 `bridge returned HTTP 401`，说明报告产物生成成功，但外部通知送达链路失败。

总体优化方向：

- 先统一口径，再优化页面。应把标签、风险、差评率、趋势状态、覆盖率等核心指标收口到唯一数据源和唯一公式。
- 对 bootstrap 和历史补采场景做更严格的展示降级：首日报告应该强调“基线建立”和“数据资产盘点”，而不是过早呈现趋势判断。
- 建立指标血缘和报告产物表，让每个 HTML/Excel 单元格能追溯到来源表、公式、时间窗口和样本数。
- 按角色拆分阅读路径：管理者看风险和决策摘要，产品改良人员看问题-证据-SKU-建议闭环，设计人员看场景、体验断点和可验证假设。

## 2. 数据库结构分析

### 当前结构概述

本次 `products.db` 中核心表和数据量如下：

| 表 | 行数 | 主要作用 |
|---|---:|---|
| `products` | 8 | 产品当前状态，包含 URL、站点、SKU、价格、库存、站点评分、站点评论数、归属 |
| `product_snapshots` | 8 | 每次抓取的产品状态快照，用于价格、评分、库存、评论数趋势 |
| `reviews` | 561 | 评论原始数据、中文翻译、发布时间、图片、翻译状态 |
| `review_analysis` | 561 | LLM 分析结果，包含情感、labels、features、insight、impact、failure_mode |
| `review_issue_labels` | 951 | 规范化后的评论问题标签 |
| `tasks` | 3 | 爬虫任务记录 |
| `workflow_runs` | 1 | 日报 workflow run、数据窗口和产物路径 |
| `workflow_run_tasks` | 3 | workflow 与任务的关联 |
| `notification_outbox` | 3 | 通知投递状态 |

主外键和唯一约束基本合理：

- `products.url` 唯一，保证同一产品当前态 UPSERT。
- `product_snapshots.product_id -> products.id`，保存每次抓取状态。
- `reviews.product_id -> products.id`，评论归属产品。
- `reviews` 通过 `product_id + author + headline + body_hash` 唯一去重，能避免同一产品重复评论入库。
- `review_analysis.review_id -> reviews.id`，并以 `review_id + prompt_version` 唯一。
- `review_issue_labels.review_id -> reviews.id`，并以 `review_id + label_code + label_polarity` 唯一。
- `workflow_run_tasks.run_id -> workflow_runs.id`、`workflow_run_tasks.task_id -> tasks.id`，能追溯某次报告对应的抓取任务。

本次数据分布：

- 产品：`basspro competitor 3`、`meatyourmaker own 2`、`waltons own 3`。
- 评论：`basspro competitor 143`、`meatyourmaker own 109`、`waltons own 309`。
- 翻译：561 条全部 `translate_status = done`。
- 评论发布时间：561/561 有 `date_published_parsed`，范围为 `2016-11-11` 至 `2026-04-15`。
- 图片：48 条评论有图，Excel 工作簿实际嵌入 82 张图片。
- 通知：3 条 outbox 均 `deadletter`，HTTP 401。

### 表与报告指标映射

| 报告内容/指标 | 主要来源 | 当前实现评价 |
|---|---|---|
| 产品数、自有/竞品数 | `products.site`、`products.ownership` | 基础合理 |
| 站点评分、站点评论数、价格、库存 | `products`、`product_snapshots` | 当前态合理，历史趋势因只有 1 次快照不足 |
| 样本覆盖率 | `reviews` 入库数 / `products.review_count` 合计 | 有业务意义，但需按产品展示覆盖异常 |
| 评论明细 | `reviews` + `review_analysis` | 主体完整，但部分字段未正确透传 |
| 情感、标签、洞察 | `review_analysis` | 可用，但 labels 为 JSON 文本，不利于结构化统计 |
| 问题诊断 | `review_issue_labels` 或 `review_analysis.labels` | 当前有双轨风险 |
| 风险产品 | `reviews`、`review_analysis`、`products.review_count` | 公式较复杂，但展示解释不足 |
| 今日变化 | `workflow_runs.data_since/data_until` + `reviews.scraped_at` + 发布时间 | bootstrap 语义较好 |
| 趋势 | `product_snapshots.scraped_at` + `reviews.date_published_parsed` | 首日数据不足，展示状态过于积极 |
| 报告产物 | `workflow_runs.snapshot_path/excel_path/analytics_path/pdf_path` | 未记录 HTML 路径，PDF 为空 |

### 存在的问题

1. 标签结构存在“原始 labels”和“规范化 labels”双轨

`review_analysis.labels` 是 LLM 原始 JSON，`review_issue_labels` 是同步后的规范化表。理论上报告统计应优先消费规范化表，但 Excel“问题标签”直接遍历 `review.analysis_labels`，导致 Excel 输出 997 行，而规范化表只有 951 行，并出现 `durability` 8 行和 `neutral` 1 行。对应实现位置在 `qbu_crawler/server/report.py` 的 `_generate_analytical_excel()`，问题标签 sheet 仍读取 `analysis_labels`。

影响：同一份报告中“问题诊断”和“问题标签”可能不是同一套标签口径，后续按标签做改良优先级、设计归因或管理汇报时会出现数量不一致。

2. 产品快照表能支持趋势，但当前报告没有足够历史

`product_snapshots` 只有 8 行，与产品数相同，说明每个产品只有当前一次抓取。价格、评分、库存、站点评论数趋势需要多次 run 的快照序列；当前只能形成“当前截面”，不能形成真正的产品状态趋势。

影响：HTML/Excel 中的趋势页容易让读者误认为系统已经有连续监控结论。

3. 报告产物缺少完整 artifact 管理

`workflow_runs` 记录了 `snapshot_path`、`excel_path`、`analytics_path`，但没有 `html_path` 字段；`pdf_path` 为 `NULL`。本次目录有 HTML 和 Excel，但 DB 中无法完整追溯 HTML 产物。

影响：后续审计“某封邮件/某个 HTML 页面到底对应哪次数据、哪版模板、哪版算法”时证据链不完整。

4. 日期解析缺少可信度字段

本次 252 条评论发布时间是相对时间表达，例如 `16 days ago`、`2 years ago`。实现中 `models.py::_parse_date_published()` 使用当前日期作为 anchor，而 `_backfill_date_published_parsed()` 使用 `scraped_at` 作为 anchor，两处 anchor 历史上存在不一致风险。

影响：`fresh_review_count`、近 30 天、近 90 天、年趋势都依赖 `date_published_parsed`。如果相对时间换算不稳定，趋势和新增判断会被放大或错位。

5. 已有分析字段未完整输出

数据库 `review_analysis.failure_mode` 有 561 条非空值，且包含“齿轮磨损脱落金属屑”“接口不兼容”“电机发热”等细粒度信息；但 Excel“失效模式”列 561 行均为空。原因是 `query_cumulative_data()` 查询未选择 `ra.impact_category` 和 `ra.failure_mode`，而 Excel 生成时读取的是 `review.get("failure_mode")`。

影响：对产品改良人员最有价值的“故障模式”没有进入报表明细，用户只能从洞察文本中人工提取。

6. 缺少源站评论唯一 ID

当前评论去重依赖 `product_id + author + headline + body_hash`。在没有源站 review ID 的情况下，Anonymous、空标题、相同短文本、评论编辑等场景仍可能误合并或无法识别更新。

影响：长期增量监控时，新增、删除、修改、重复评论的判断可靠性不足。

### 合理性评估

当前数据库结构能够支撑“首日全量抓取 + 报告生成”的基本需求，也能支撑短期的产品、评论、翻译和 LLM 分析闭环。但它对“后续分析需求”的支持还不够稳：趋势缺少足够时间序列，标签有双轨，报告产物没有完整血缘，评论日期没有置信度，评论唯一性依赖弱标识。这些问题在数据量小的时候不明显，一旦进入每日增量、跨版本算法迭代、跨角色复盘，就会放大为可信度问题。

### 优化建议

- 建立 `report_artifacts` 表，记录 `run_id`、artifact 类型、路径、hash、生成时间、模板版本、算法版本、输入 snapshot hash。
- 建立 `metric_definitions` 或最小版指标字典，记录指标名、公式、分母、时间窗口、来源字段、是否可展示。
- 将 Excel 和 HTML 的问题统计统一改为消费 `review_issue_labels`，原始 `review_analysis.labels` 只作为调试字段。
- 在 `reviews` 增加 `source_review_id`、`date_parse_method`、`date_parse_confidence`、`date_parse_anchor`。
- 在 `product_snapshots` 增加 `run_id` 或 `workflow_run_id`，让趋势点能直接追溯到报告运行。
- 把 `review_analysis.failure_mode`、`impact_category` 纳入 `query_report_data()` 和 `query_cumulative_data()`。

## 3. HTML 报告分析

### 页面与内容结构分析

HTML 报告结构较完整，包含：

- 总览
- 今日变化
- 变化趋势
- 问题诊断 8
- 产品排行 5
- 竞品对标
- 全景数据 561

总体视觉层次清晰，KPI 卡片、tab、问题卡、产品排行、评论表格的模块边界明确。对首次打开报告的用户来说，可以快速看到健康指数、差评率、累计评论、覆盖率、高风险产品数和关键建议。

但当前 HTML 仍存在两个结构性问题：

- 总览页像“管理摘要”，但同时塞入 KPI、范围、AI 总结、建议行动和风险摘要，信息密度偏高。
- 各 tab 的徽标含义不统一，例如“产品排行 5”使用自有产品数，但表格只展示 2 个有风险产品；“全景数据 561”是本次 snapshot 评论数，而非明确的累计或窗口口径。

### 各项指标分析

| 指标 | 本次值 | 业务含义 | 评价 |
|---|---:|---|---|
| 健康指数 | 96.2 | 基于自有评论好评/差评的综合健康度 | 能表达整体表现，但会掩盖局部产品风险 |
| 自有差评率 | 2.4% | 自有样本中低评分/负面反馈比例 | 有参考价值，但需明确分母为 418 条自有评论 |
| 自有评论 | 418 | 自有产品累计入库评论 | 清晰，但应标明包含历史补采 |
| 竞品评论 | 143 | 竞品累计入库评论 | 可用于对标，但样本量小于自有 |
| 本次入库评论 | 561 | 本次 run 实际入库评论数 | bootstrap 下展示合理，不能解释为“今日新增” |
| 新近评论 | 3 | 按评论发布时间近 30 天识别 | 样本太小，只适合提示，不适合趋势判断 |
| 历史补采 | 558 | 本次入库中非近 30 天评论 | 非常关键，已经在页面提示 |
| 样本覆盖率 | 64% | 入库评论数 / 站点展示评论数 879 | 有价值，但必须按产品暴露低覆盖或 0 覆盖 |
| 高风险产品 | 0 | 风险分 >= 35 的自有产品数量 | 阈值输出清晰，但 `.75 HP Grinder (#12)` 32.6 接近阈值，仍需关注 |
| 竞品差距指数 | 4 | 竞品优势/自有短板综合信号 | 展示过于抽象，缺少公式和分母 |

### 可读性与参考价值评估

有价值的部分：

- “今日变化”明确展示 bootstrap，且提示“新近 3 / 补采 558”，能避免把 561 条误读为今日新增。
- “问题诊断”能展示具体问题、典型评论和建议，例如结构设计、售后与履约、质量稳定性、材料与做工。
- “产品排行”能快速定位两个有风险的自有产品：`.75 HP Grinder (#12)` 风险分 32.6，`Walton's Quick Patty Maker` 风险分 28.9。
- “全景数据”保留评论级证据，便于人工回查。

价值有限或有误导风险的部分：

- 总览“建议行动”标题被截断：HTML 中出现“针对Walton's #22 Meat Grinder、Walton's General Duty Meat Lug与Quick Patty Maker反馈的肉”这类半句话。详细问题卡里有完整建议，但总览入口损失业务语义。
- 产品排行 tab 徽标为 5，但表格只列 2 个风险产品。用户可能误解为缺了 3 条数据。
- `.5 HP Dual Grind Grinder (#8)` 站点评论数 91、采集评论数 0，却没有在 HTML 产品排行中明显提示“覆盖异常/采集失败/无样本”。
- 趋势页默认 `month/sentiment`，但月视图仅 3 条评论就进入 `ready`，容易被管理者误认为“月度趋势可信”。
- 年视图基于评论发布时间横跨多年，反映的是历史评论分布，不是系统上线后的年度监控趋势。
- 问题诊断中“危急”问题大多来自多年历史样本，页面没有足够突出“近 90 天活跃度低/首日补采”的降级语义。
- 竞品对标表主要展示“竞品好评”和“自有差评”，但没有分母、率、样本数、置信度和差距公式，专业判断不足。

### 存在的问题

1. 展示语义与用户预期不完全一致

`bootstrap` 已经提示，但趋势、危急问题、产品排行仍沿用接近“成熟监控期”的表达方式。首日报告最应该回答“当前数据资产是什么、覆盖哪里不足、有哪些历史风险待确认”，而不是暗示已经形成稳定趋势。

2. 指标解释不够贴近业务决策

例如健康指数 96.2 很高，但 `.75 HP Grinder (#12)` 仍有开关失灵、售后失联、金属碎屑等高严重度问题。如果只看健康指数，管理者可能低估局部风险。

3. 信息优先级需要重排

对产品改良人员来说，问题-产品-SKU-证据-建议才是主路径；对管理者来说，覆盖异常、接近阈值风险、通知失败也需要进入摘要；对设计人员来说，场景和体验断点应优先于标签数量。

4. 模板存在稳定性风险

`daily_report_v3.html.j2` 中趋势表使用 `row.values()` 输出，依赖 dict 插入顺序，而不是按 columns key 输出。只要上游 dict 结构变化，列和值可能错位。

### 优化建议

- 总览页新增“本次报告可信度条”：基线期、历史补采占比、覆盖率、相对日期占比、低覆盖产品数。
- 将“建议行动”标题改为短标题 + 完整建议，不要用 80 字截断后的长句当标题。
- 产品排行 tab 徽标改为“有风险 2 / 自有 5”，并增加“无样本产品”提示区。
- 趋势页在 bootstrap 首日默认显示“趋势尚未形成”，将月/年图表折叠为“历史评论分布”。
- 竞品对标增加样本数、分母、率、差距计算说明和置信度。
- 全景数据增加筛选入口：按归属、产品、问题标签、低评分、有图、新近/补采筛选。

## 4. Excel 数据分析

### 数据内容与字段分析

本次 Excel 包含 5 个 sheet：

| Sheet | 行数 | 列数 | 内容 |
|---|---:|---:|---|
| 评论明细 | 562 | 18 | 561 条评论明细 + 表头 |
| 产品概览 | 9 | 12 | 8 个产品 + 表头 |
| 今日变化 | 14 | 4 | bootstrap 状态、入库/新近/补采、提示、评论信号 |
| 问题标签 | 998 | 6 | 997 行标签明细 + 表头 |
| 趋势数据 | 603 | 11 | 产品快照与趋势 digest 导出 |

评论明细核心分布：

- 窗口归属：558 条 `本次入库·补采`，3 条 `本次入库·新近`。
- 归属：自有 418，竞品 143。
- 情感：正面 436，负面 71，复杂 50，中性 4。
- 标题原文：316 条为空。
- 照片列：单元格 561 行为空，但工作簿实际嵌入 82 张图片。
- 失效模式：561 行为空。

产品概览关键行：

- `.75 HP Grinder (#12)`：站点评论数 253，采集评论数 109，差评数 9，差评率 3.56%，风险分 32.6。
- `Walton's Quick Patty Maker`：站点评论数 94，采集评论数 94，差评数 1，差评率 1.06%，风险分 28.9。
- `.5 HP Dual Grind Grinder (#8)`：站点评论数 91，采集评论数 0，差评率为空，风险分为空。
- 竞品 `Cabela's Heavy-Duty Sausage Stuffer`：站点评论数 80，采集评论数 56，差评数 25，差评率 44.64%。

今日变化：

- 状态：`bootstrap`。
- 本次入库评论：561。
- 新近评论：3。
- 历史补采：558。
- 自有新近差评：0。
- 提示：`estimated_dates` 已触发，`backfill_dominant` 已触发。
- 评论信号：2 条竞品新近好评。

问题标签：

- Excel 输出 997 行标签。
- Top 标签：性能强 265、做工扎实 148、易上手 124、性价比高 101、结构设计 90、易清洗 68、质量稳定性 52、售后与履约 52。
- 出现未规范化标签：`durability` 8 行。
- 极性出现未翻译/未映射值：`neutral` 1 行。

趋势数据：

- 产品快照明细只有 8 个当前快照点。
- 近 7 天评论声量与情绪为 `accumulating`。
- 近 30 天情绪 KPI 显示窗口评论量 3、自有差评数 0、自有差评率 0.0%、有效时间点 3。
- 年视图情绪显示窗口评论量 50、自有差评数 3、自有差评率 10.3%、有效时间点 11。

### 数据质量与一致性分析

准确性较好的部分：

- 产品、评论、翻译、情感、窗口归属的数量与 DB/analytics 基本一致。
- 今日变化 sheet 与 HTML 今日变化一致，都明确了 bootstrap、561 入库、3 新近、558 补采。
- 产品概览中的站点评分、站点评论数、采集评论数与 DB 当前态一致。
- 图片虽然单元格为空，但工作簿确实嵌入了图片证据。

存在风险的部分：

1. 问题标签与规范化表不一致

DB `review_issue_labels` 为 951 行，Excel“问题标签”为 997 行。Excel 直接消费 `review_analysis.labels`，没有消费同步后的规范化标签表，因此会出现标签数量、标签名称、极性值不一致。

2. 失效模式列为空

DB 中 `review_analysis.failure_mode` 有值，但 Excel 没有输出。这个字段对产品改良非常关键，当前报表浪费了已有分析资产。

3. 照片列表现不直观

照片单元格为空，但图片实际作为 drawing 嵌入。对于后续机器解析或二次汇总来说，“单元格为空”会被误判为无图。应同时保留图片 URL 或图片数量字段。

4. 差评率分母不统一

产品概览中风险产品差评率来自 `risk.negative_rate`，即差评数 / 站点评论数；非风险产品如果没有 risk 对象，则回退为差评数 / 采集评论数。竞品行也使用采集评论数分母。这会导致同列数据口径不同。

5. `.5 HP Dual Grind Grinder (#8)` 覆盖异常没有被突出

该产品站点评论数 91，但采集评论数 0。Excel 有记录，但没有显著标记为“覆盖异常”。该产品仍参与自有产品数和站点评论数分母，会影响覆盖率和自有概览解释。

6. 趋势 sheet 混合了快照趋势和评论发布时间分布

同一个 sheet 中既有 `product_snapshots.scraped_at` 的产品状态点，又有按 `date_published_parsed` 聚合的评论趋势。两类时间轴含义不同，放在同一 sheet 容易被误读。

### 与 HTML 报告的一致性验证

一致的地方：

- HTML 和 Excel 都显示本次入库 561、新近 3、补采 558。
- HTML 和 Excel 都体现 bootstrap 监控起点。
- 产品概览中两个风险产品与 HTML 产品排行一致。
- 核心 KPI 如健康指数 96.2、自有差评率 2.4%、样本覆盖率 64% 与 analytics 一致。

不一致或表达不充分的地方：

- HTML“问题诊断”有 8 个问题卡；Excel“问题标签”是 997 行原始标签，两者标签来源不完全一致。
- HTML 产品排行只展示 2 个风险产品；Excel 产品概览展示 8 个产品，但没有解释 HTML 为什么少 3 个自有产品。
- HTML 中图片作为评论证据可见；Excel 图片嵌入但照片单元格为空，不利于数据再利用。
- HTML 展示完整问题建议在问题详情区，但总览行动建议被截断；Excel 没有对应的完整行动建议 sheet。

### 存在的问题

- Excel 更像“数据导出”，还不是“可分析工作簿”。缺少数据字典、指标说明、公式说明和异常标记。
- 部分字段有数据但分析价值没有释放，例如 `failure_mode` 没输出，`impact_category` 没稳定展示。
- 部分统计有结果但难以指导业务，例如趋势数据在首日 bootstrap 场景下导出大量分段，但没有足够样本稳定性说明。
- 图片证据对业务很有价值，但当前 Excel 不保留可复制 URL，影响转发、引用和二次处理。

### 优化建议

- 增加“指标说明”sheet，列出每个指标的来源表、字段、公式、分母、时间窗口、适用场景。
- 增加“数据质量”sheet，列出 0 覆盖产品、低覆盖产品、相对日期占比、翻译失败、分析失败、通知失败。
- “问题标签”sheet 改为基于 `review_issue_labels`，并保留原始标签到单独“LLM 原始标签”调试 sheet。
- “评论明细”补充 `failure_mode`、`impact_category`、`图片数量`、`图片URL`、`date_parse_method`。
- “趋势数据”拆分为“产品状态快照趋势”和“评论发布时间分布”，避免时间轴混用。

## 5. 角色视角价值评估

### 产品改良人员

有价值的内容：

- 问题诊断中的结构设计、质量稳定性、材料与做工、售后与履约等标签，能够帮助定位产品改良方向。
- 风险产品排行直接指出 `.75 HP Grinder (#12)` 和 `Walton's Quick Patty Maker`。
- 评论明细提供原文、中文、评分、标签、洞察和图片证据，便于查看真实用户表达。
- 典型问题如肉饼厚度过大、开关接触不良、金属碎屑、喉道生锈、噪音过大，都具备工程改良意义。

价值有限的内容：

- 健康指数 96.2 对产品改良人员价值有限，因为它过于总体，不能直接指向哪个零部件、哪个场景、哪个批次。
- 高风险产品数为 0 可能削弱改良紧迫感，但 `.75 HP Grinder (#12)` 风险分 32.6 已接近阈值，且有高严重度证据。
- 趋势页在首日基线期不能用于验证改进效果。

缺失内容：

- 缺少按 SKU 的“问题-部件-场景-严重度-证据-建议”矩阵。
- 缺少失效模式字段输出，虽然 DB 已有 `failure_mode`。
- 缺少问题是否近期活跃、是否复发、是否改良后下降的判断。
- 缺少覆盖异常提醒，例如 `.5 HP Dual Grind Grinder (#8)` 无采集评论。

改进建议：

- 为产品改良人员新增“改良工作台”视图：SKU、问题标签、失效模式、证据评论、图片、建议动作、样本数、近 90 天活跃度。
- 把“风险分”拆成可解释因子：差评率、严重度、图片证据、近 90 天、差评量显著性。
- 对首日历史问题标记“待验证”，进入后续 run 后再判断是否仍然活跃。

### 设计人员

有价值的内容：

- 评论洞察和特征短语能帮助理解体验断点，例如厚度不可调、说明书模糊、清洁维护、适配困难。
- 竞品好评能提示设计优势，例如易清洁、反向停转、结构扎实。
- 图片评论能补充用户实际使用场景。

价值有限的内容：

- 情感比例和健康指数对设计决策帮助有限，不能直接转化为界面、结构、说明书或包装设计动作。
- 问题标签偏“数据分类”，缺少场景化表达，例如“用户在首次组装时遇到什么”“高强度连续作业时哪里不舒服”。
- 竞品对标没有把竞品设计亮点转化为可借鉴设计原则。

缺失内容：

- 缺少用户任务场景：组装、首次使用、连续加工、清洗、收纳、售后、配件购买。
- 缺少体验旅程：购买前预期、开箱、安装、使用、清洁、维护、求助。
- 缺少正负反馈对照：同一设计点在自有和竞品中的表现差异。

改进建议：

- 新增“体验场景”视图，把评论归类到任务阶段。
- 对每个问题输出“设计假设”和“可验证改动”，例如厚度调节、说明书图示、快拆清洗结构。
- 竞品对标增加“可借鉴设计亮点”，而不是只列好评主题。

### 管理者

有价值的内容：

- 总览 KPI 能快速看到整体健康：健康指数 96.2、自有差评率 2.4%、样本覆盖率 64%、高风险产品 0。
- bootstrap 和历史补采提示能帮助理解本次报告不是日常增量报告。
- 风险产品和问题诊断能提示资源投入方向。
- 样本覆盖率能提示数据质量和采集完整性。

价值有限的内容：

- 竞品差距指数 4 缺少定义，难以直接用于资源分配。
- 趋势页在首日场景下对管理判断价值有限。
- 全景数据 561 条过细，不适合管理层直接阅读。

缺失内容：

- 缺少“本期必须处理的 3 件事”和“需要观察的 3 件事”。
- 缺少数据质量红黄绿灯，例如覆盖异常、通知失败、趋势不足。
- 缺少风险分接近阈值但未达到高风险的预警。
- 缺少报告送达状态，本次通知 outbox 实际失败。

改进建议：

- 管理摘要中增加“结论可信度”和“数据风险”。
- 把 `.75 HP Grinder (#12)` 标为“接近高风险阈值”，而不是只显示高风险产品 0。
- 对 bootstrap 报告明确写成“基线报告”，管理者只做盘点和立项，不做趋势判断。

## 6. 指标计算逻辑与数据链路分析

### 数据流转过程

当前链路可以概括为：

1. 爬虫任务写入 `products`、`product_snapshots`、`reviews`。
2. 翻译 Worker 更新 `reviews.headline_cn`、`reviews.body_cn`、`translate_status`。
3. LLM 分析写入 `review_analysis`。
4. 标签同步生成 `review_issue_labels`。
5. `freeze_report_snapshot()` 按 `workflow_runs.data_since/data_until` 查询窗口产品和评论，同时嵌入 cumulative 数据。
6. `build_report_analytics()` 生成 KPI、问题、风险、趋势、竞品分析。
7. `build_change_digest()` 生成“今日变化”语义。
8. Excel 由 `_generate_analytical_excel()` 输出。
9. HTML 由 `daily_report_v3.html.j2` 渲染。
10. 邮件摘要消费顶层 KPI 与 change digest。

### 核心指标追溯

| 指标/内容 | 数据来源 | 计算逻辑 | 输出位置 | 评价 |
|---|---|---|---|---|
| 本次入库评论 | `reviews.scraped_at` 落在 run 窗口 | count | HTML 今日变化、Excel 今日变化、KPI | 合理 |
| 新近评论 | `date_published_parsed` 近 30 天 | count | HTML/Excel 今日变化 | 合理但受相对日期估算影响 |
| 历史补采 | 本次入库 - 新近 | count | HTML/Excel 今日变化 | 合理，且已触发 99% 警告 |
| 健康指数 | 自有评论 rating | promoters/detractors 的 NPS proxy，样本不足时向 50 收缩 | HTML KPI | 公式合理，但需解释局部风险不等于整体健康 |
| 自有差评率 | 自有评论 rating <= 阈值 | 自有差评数 / 自有评论数 | HTML/Excel/analytics | 基本合理 |
| 样本覆盖率 | 入库评论数、站点评论数 | 561 / 879 = 64% | HTML KPI | 有价值，但需产品级覆盖异常 |
| 风险分 | 自有低分评论、严重度、图片、近 90 天、显著性 | 5 因子加权后 0-100 | HTML 产品排行、Excel 产品概览 | 算法有价值，解释不足 |
| 高风险产品 | 风险分 >= 35 | count | HTML KPI | 阈值清晰，但接近阈值产品需预警 |
| 问题诊断 | `review_issue_labels` / labels 聚合 | 按标签聚类、样本、严重度、证据 | HTML 问题诊断 | 有价值，但活跃度/补采语义不足 |
| 问题标签明细 | `review_analysis.labels` | 逐条展开 JSON | Excel 问题标签 | 不应作为正式口径 |
| 趋势 | `reviews.date_published_parsed` 与 `product_snapshots.scraped_at` | 按周/月/年聚合 | HTML 趋势、Excel 趋势数据 | 首日不应过度 ready |
| 产品概览差评率 | 风险对象或采集评论回退 | 风险产品用站点评论数分母，其他用采集评论数分母 | Excel 产品概览 | 口径不统一 |

### 数据链路合理性评估

完整闭环已经成立，但不是完全可追溯闭环。能追溯的部分包括：评论 ID、产品 SKU、run 窗口、snapshot、analytics、Excel/HTML 的多数 KPI。不能稳定追溯的部分包括：某个 HTML 展示值到底使用原始 labels 还是规范化 labels、风险分各因子的中间值、趋势状态为什么 ready、HTML artifact 与 workflow_run 的结构化绑定。

### 潜在风险与问题

1. 标签同步后没有统一消费

`generate_full_report_from_snapshot()` 中有标签同步步骤，但 Excel 仍使用 `analysis_labels`。这会导致“同步成功”不等于“报告已使用同步结果”。

2. 风险分说明与实现不一致

`report_common.py` 中 `METRIC_TOOLTIPS["风险分"]` 仍是旧说明：“低分评论×2 + 含图评论×1 + 各标签严重度累加；仅计 ≤3星评论”。实际 `_risk_products()` 是 5 因子加权，且差评阈值使用 `config.NEGATIVE_THRESHOLD`，本项目当前低分阈值为 <=2。说明文档与算法不一致。

3. 趋势状态存在嵌套不一致

trend digest 中月视图 `sentiment` status 为 `ready`，但样本仅 3 条；产品维度外层 status 为 `accumulating`，内部 KPI status 又为 `ready`。这会让模板和用户都难以判断应该展示还是降级。

4. 日期估算影响新增与趋势

本次 252 条评论包含相对时间表达，analytics 已触发 `estimated_dates` 警告。只要日期 anchor 变化，历史评论可能落入不同月/年窗口。

5. HTML 表格输出依赖 dict 顺序

模板中趋势表使用 `row.values()`，不是按列定义取值。上游 JSON 字段顺序变化时，列和值可能错位。

6. 通知链路没有纳入报告质量状态

workflow run 显示 `completed/full_sent`，但 outbox 全部 deadletter。报告生成链路和送达链路状态没有在用户报告中合并表达。

### 优化建议

- 定义“正式展示指标只消费 analytics 顶层字段和规范化表”的硬规则，并加测试。
- 每个核心指标输出 `value`、`display`、`numerator`、`denominator`、`window`、`source`、`confidence`。
- 风险分输出因子分解，便于解释为什么 32.6 接近高风险。
- trend digest 增加 `min_sample_size` 和 `confidence`，bootstrap 时默认 `accumulating`。
- 把通知失败纳入 workflow 质量摘要，而不是只在 outbox 中沉默。

## 7. 当前存在的主要问题清单

### 数据结构问题

- 缺少 `report_artifacts` 表，HTML/PDF 产物不能完整追溯。
- `product_snapshots` 未绑定 `run_id`，趋势点和 workflow 的关系不够直接。
- 缺少源站评论 ID，评论去重和长期增量更新可靠性不足。
- `reviews.date_published_parsed` 缺少解析方式、置信度和 anchor。
- `review_analysis.labels` 与 `review_issue_labels` 并存，但没有强制报告消费规范化结果。

### 指标设计问题

- 健康指数过于总体，容易掩盖局部产品风险。
- 竞品差距指数缺少公式说明和分母。
- 风险分阈值与“接近高风险”的预警机制不足。
- 趋势 ready 条件过低，首日 3 条近 30 天评论也被展示为 ready。
- 产品差评率同列混用不同分母。

### 数据质量问题

- `.5 HP Dual Grind Grinder (#8)` 站点评论数 91，采集评论数 0，属于覆盖异常。
- 252 条评论存在相对时间表达，新增和趋势需要降级解释。
- 316 条评论标题为空，标题维度分析价值有限。
- 通知 outbox 3 条 deadletter，报告送达链路失败。

### 展示表达问题

- 总览建议行动标题被截断成半句话。
- 产品排行 tab 徽标显示 5，但表格只显示 2 个风险产品。
- 竞品对标缺少样本数、分母、率和置信度。
- 邮件截图中出现“KPI 展示统一读取 analytics.kpis，今日变化统一读取 analytics.change_digest”这类实现说明式文案，不适合业务读者。
- Excel 图片列为空但实际嵌图，机器读取时会误判无图。

### 用户理解问题

- bootstrap 首日、历史补采、趋势不足之间的关系没有贯穿所有模块。
- “危急”问题没有充分标记是否近期活跃，容易造成当前风险误判。
- 管理者看到“高风险产品 0”可能忽视接近阈值产品。
- 设计人员难以从标签直接还原用户任务场景。

### 数据链路问题

- DB 中 `failure_mode` 有值，但 Excel 未输出。
- Excel 问题标签不使用规范化标签表。
- HTML 全景数据使用 `snapshot.reviews`，未来增量期可能与 Excel cumulative 口径不一致。
- 趋势表模板依赖 dict 顺序，存在展示错位风险。

### 实现方式问题

- 风险分 tooltip 与实际 `_risk_products()` 算法不一致。
- Excel 生成函数中存在新旧版本覆盖痕迹，维护成本高。
- 报告查询层没有统一字段契约，导致已有分析字段遗漏。
- bootstrap 下部分模块仍按成熟监控期展示，模板层和 analytics 层职责边界需要更清晰。

## 8. 优化建议

### 高优先级建议

1. 统一标签正式口径

解决问题：`review_analysis.labels` 与 `review_issue_labels` 双轨导致 Excel 997 行、规范化表 951 行不一致。

做法：HTML、Excel、analytics 中所有正式问题统计都消费 `review_issue_labels`；原始 labels 只保留到调试 sheet。

价值：保证问题数量、问题名称、极性、严重度全报告一致。

2. 修复 Excel 分析字段透传

解决问题：`failure_mode` 和 `impact_category` 已在 DB 中存在，但 Excel 明细为空。

做法：在 `query_report_data()`、`query_cumulative_data()` 中选择 `ra.impact_category`、`ra.failure_mode`，Excel 按统一字段输出。

价值：直接提升产品改良人员的可用性。

3. 修正风险分和差评率口径说明

解决问题：风险分 tooltip 过时，产品概览差评率分母混用。

做法：风险分输出因子分解；产品差评率明确拆成“采集样本差评率”和“站点总量归一差评率”，不要混在一列。

价值：避免管理层和产品团队误读风险排序。

4. bootstrap 下趋势展示降级

解决问题：首日 3 条近 30 天评论被展示为 ready 趋势。

做法：当 `report_semantics = bootstrap` 或有效样本低于阈值时，趋势页默认展示“趋势尚未形成”，图表标为历史分布或折叠。

价值：提高专业可信度，避免用历史补采推断当前趋势。

5. 暴露覆盖异常

解决问题：`.5 HP Dual Grind Grinder (#8)` 站点评论数 91，采集 0，但未被突出。

做法：新增数据质量卡和 Excel 数据质量 sheet，列出 0 覆盖、低覆盖、相对日期高占比等问题。

价值：让业务知道哪些产品结论暂不可用。

### 中优先级建议

1. 建立报告 artifact 表

解决问题：HTML 产物未进入 DB，PDF 路径为空，产物不可完整追溯。

价值：后续审计、重发、归档、版本比对更可靠。

2. 增加指标血缘字段

解决问题：指标公式、分母、窗口、来源不透明。

价值：让 HTML/Excel 每个指标都能反查来源和计算方法。

3. 优化 HTML 总览

解决问题：行动建议截断、信息堆叠、产品排行徽标误导。

价值：提升管理者和业务用户的第一屏理解效率。

4. 拆分趋势数据时间轴

解决问题：产品快照趋势和评论发布时间趋势混在一起。

价值：降低误读，便于后续做真正的连续监控。

5. 修复通知链路状态表达

解决问题：workflow completed 但通知 deadletter。

价值：让运维和业务都知道报告是否真正送达。

### 低优先级建议

1. Excel 增加筛选和冻结窗格优化

解决问题：561 条全景数据浏览效率低。

价值：提高人工分析效率。

2. 图片列同时保留缩略图和 URL

解决问题：单元格为空不利于二次处理。

价值：便于转发证据和机器解析。

3. 增加角色化导出

解决问题：一份报告同时服务三类角色，信息密度和重点不匹配。

价值：让管理者、产品、设计各自拿到更适合的版本。

4. 模板表格按 columns key 输出

解决问题：`row.values()` 依赖 dict 顺序。

价值：降低未来结构调整导致展示错位的风险。

## 9. 更优实现方案（如适用）

### 更优的数据结构设计方式

建议在现有结构上做增量治理，而不是重建：

- `report_runs` 或沿用 `workflow_runs`：保留 run 级窗口、模式、状态、质量摘要。
- 新增 `report_artifacts`：`run_id`、`artifact_type`、`path`、`hash`、`template_version`、`generator_version`、`created_at`。
- 新增 `metric_snapshots`：`run_id`、`metric_key`、`value`、`display_value`、`numerator`、`denominator`、`window_start`、`window_end`、`source_tables`、`confidence`。
- 扩展 `reviews`：`source_review_id`、`date_parse_method`、`date_parse_anchor`、`date_parse_confidence`。
- 扩展 `product_snapshots`：`run_id`、`source_quality`。
- 将 `review_issue_labels` 作为正式标签事实表，`review_analysis.labels` 只作为原始 LLM 输出。

### 更优的指标体系设计方式

建议把指标分成四层：

1. 数据质量指标

- 覆盖率、0 覆盖产品数、低覆盖产品数、翻译完成率、分析完成率、相对日期占比、通知送达状态。

2. 业务健康指标

- 自有平均评分、自有差评率、健康指数、自有低分评论数、高风险/近高风险产品数。

3. 问题诊断指标

- 问题标签数量、影响产品数、近 90 天活跃度、有图证据数、严重度、复发次数、首次/最近出现时间。

4. 竞争对标指标

- 竞品好评主题、自有差评主题、样本分母、差距率、可借鉴亮点、需修复短板。

每个指标必须同时输出公式和置信度。对于 bootstrap，应默认标记为“基线值”；对于 incremental，才允许展示“较上期变化”。

### 更优的 HTML 报告展示方式

建议按角色和阅读路径重构：

- 第一屏：报告状态、数据质量、核心风险、推荐动作，不展示过多图表。
- 今日变化：bootstrap 下显示“建档盘点”，incremental 下显示“新增/变化/升级/改善”。
- 产品改良：按 SKU 展示问题矩阵、失效模式、证据、建议。
- 设计体验：按用户任务阶段展示体验断点和竞品亮点。
- 管理摘要：展示红黄绿灯、近高风险、资源建议、覆盖异常。
- 数据附录：保留全量评论、标签、图片、公式和血缘。

### 更优的数据加工与计算链路

推荐链路：

1. 原始抓取层：只负责产品、评论、图片、源站元数据。
2. 标准化层：统一日期、归属、评论唯一 ID、图片 URL、评分、站点字段。
3. 分析层：LLM 输出原始 JSON，并同步到规范化事实表。
4. 指标层：只从标准化表和事实表计算，输出 metric snapshot。
5. 展示层：HTML/Excel/邮件只消费 metric snapshot、change digest、trend digest 和标准化明细，不重复计算。
6. 审计层：记录 artifact、hash、模板版本、算法版本、输入数据窗口。

### 更适合不同角色的呈现方案

产品改良人员：

- 默认进入“SKU 风险与问题证据”。
- 每个 SKU 显示风险因子、失效模式、评论证据、图片、建议验证项。

设计人员：

- 默认进入“用户任务场景与体验断点”。
- 用场景标签替代纯问题标签，例如组装、连续加工、清洁、收纳、售后。

管理者：

- 默认进入“一页摘要”。
- 只保留整体健康、数据可信度、风险产品、覆盖异常、资源建议和通知状态。

最终判断：当前测试 5 报告已经可以作为“首次建档基线报告”使用，但不宜作为成熟的趋势分析报告或最终管理决策报告。下一步应优先做口径收口、字段透传、趋势降级和数据质量显性化。完成这些后，报告体系才会从“能生成”升级到“可信、可解释、能驱动行动”。
