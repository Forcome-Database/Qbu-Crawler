# 每日深度 PDF 报告设计

> 日期：2026-04-02
> 状态：已确认，待评审

## 背景

当前每日任务工作流已经稳定运行，主链路为：

1. `DailySchedulerWorker` 定时触发 daily run
2. `submit_daily_run()` 提交抓取任务并写入 `workflow_runs`
3. `WorkflowWorker` 等待任务完成并冻结 snapshot
4. 基于 snapshot 发送 `workflow_fast_report`
5. 生成 full report，当前仅产出 Excel 并通过 SMTP 发送
6. 发送 `workflow_full_report` 通知

现有 full report 的正式出口位于：

- [qbu_crawler/server/workflows.py](/e:/Project/ForcomeAiTools/Qbu-Crawler/qbu_crawler/server/workflows.py#L583)
- [qbu_crawler/server/report_snapshot.py](/e:/Project/ForcomeAiTools/Qbu-Crawler/qbu_crawler/server/report_snapshot.py#L95)

当前问题是：

- 报告正式产物只有 Excel，适合明细查询，不适合管理层和研发直接阅读
- 自有产品差评、问题簇、改良建议没有结构化沉淀
- 竞品分析没有形成稳定的“好评 benchmark”视角
- 首日全量与后续增量共用 Excel 明细，但缺少适配两种场景的高层报告
- 当前 `send_email()` 只支持单附件，无法正式发送 `Excel + PDF`
- snapshot 只冻结原始 `products/reviews`，没有冻结分析结果，重复生成报告时可能产生口径漂移

业务侧已经明确新的日报目标：

- 自有产品：以差评分析、问题簇、改良建议为主
- 竞品：以好评分析为主，差评为辅
- 读者：以工厂产品研发为主，兼顾产品与运营、售后、管理层
- 产物：保留 Excel 明细，同时新增 1 份适合正式阅读的 PDF

## 目标

1. 在不破坏现有 daily workflow 主控制流的前提下，新增 `Excel + PDF` 双附件日报
2. 让 PDF 成为正式阅读产物，突出自有产品差评、问题簇、改良建议
3. 让竞品章节稳定输出正向主题、卖点排行和借鉴点
4. 让同一模板同时适配“首日全量建基线”和“后续增量监控”
5. 固化分析结果，确保同一 run 的 PDF 具备可追溯和可重复性
6. 为后续问题簇增强、趋势分析和异常检测预留演进空间

## 非目标

- 一期不生成多份正式报告类型
- 一期不生成对外客户版 PDF
- 一期不在 full report 阶段对全量评论做开放式自由 LLM 分析
- 一期不承诺“工程根因结论”，只输出基于评论证据的“问题现象、可能原因边界、改良建议”
- 一期不把所有指标都做成长趋势图
- 一期不重构 `DailySchedulerWorker -> WorkflowWorker -> report_snapshot` 主编排结构

## 设计原则

1. 单出口：daily workflow 仍保持一次 snapshot、一次 full report 的正式出口
2. 分层阅读：主 PDF 面向不同角色分层，不把所有内容平铺堆砌
3. 主次分明：自有产品负向分析为主，竞品正向 benchmark 为辅
4. 可重复：报告使用冻结后的 snapshot 和 analytics artifact，避免报表时现算漂移
5. 范围收敛：一期做轻量 taxonomy，不做开放式大规模自由归类
6. 兼容现有：尽量复用现有 `report.py`、`report_snapshot.py`、`workflow_runs`
7. 性能优先：面对上百产品、几万评论，一期避免同步全量 LLM 深描

## 读者与使用场景

### 主要读者

- 工厂产品研发

### 次要读者

- 产品与运营
- 售后
- 管理层

### 使用场景

- 每日自动发送给内部固定收件人
- 研发晨会或日会中快速定位高优问题
- 产品与运营跟踪自有产品口碑风险
- 管理层快速了解风险、改良方向和竞品借鉴点

## 产物形态

每日 full report 产出以下三个 artifact：

1. `snapshot JSON`
   authoritative 原始数据边界
2. `analytics JSON`
   固化当次聚合指标、问题簇结果、代表性样本和建议输入
3. `Excel + PDF`
   - Excel：明细与筛选
   - PDF：正式阅读与决策

一期不引入新的正式报告类型，只在当前 full report 上扩展产物。

## 报告核心逻辑

### 自有产品

主线为：

- 差评总览
- 风险产品排序
- 问题簇深挖
- 改良建议与优先级

### 竞品

主线为：

- 好评卖点排行
- 正向主题簇
- 代表性好评证据
- 少量差评补充，用于识别机会窗口

这样做的原因是：

- 自有产品最有价值的是定位问题并推动改良
- 竞品最有价值的是学习用户认可的设计与体验点
- 如果竞品和自有都平均做差评分析，会稀释研发重点

## 报告权重与章节结构

### 权重

- 自有产品差评总览 + 风险产品：20%
- 自有产品问题簇深挖：30%
- 改良建议与优先级：25%
- 竞品好评 benchmark：15%
- 竞品差评与机会窗口：5%
- 附录与口径：5%

### 固定章节

#### 1. 执行摘要

面向管理层和负责人，只保留最重要的 5 到 8 条结论。

包含：

- 今日抓取产品数
- 今日新增评论数
- 自有产品高风险 SKU 数
- 今日新增高优问题簇
- 竞品最值得借鉴的 1 到 3 个卖点
- 今日建议优先动作

图表：

- KPI 卡片
- 风险等级条

#### 2. 自有产品差评总览

只聚焦 `ownership = own` 的产品。

包含：

- 自有产品低分评论量
- 自有产品低分评论占比
- 图片差评数
- 受影响产品数
- Top 风险 SKU

图表：

- Top 风险产品条形图
- 低分评论占比图
- 图片差评占比图

#### 3. 自有产品问题簇深挖

这是整份 PDF 的主章节。

每个问题簇输出：

- 问题簇名称
- 涉及产品数
- 涉及评论数
- 严重度
- 是否较近 30 天基线升温
- 代表性评论证据
- 是否存在图片证据

图表：

- 问题簇排行条形图
- 严重度热力图
- 产品 x 问题簇矩阵

#### 4. 改良建议与优先级

按问题簇输出建议，不按单条评论输出。

每条建议包含：

- 问题现象
- 证据摘要
- 可能原因边界
- 建议改良方向
- 优先级
- 影响面
- 推荐协作方

建议类型分为：

- 设计改良
- 质量改良
- 说明与售后改良

#### 5. 竞品好评 benchmark

只聚焦竞品正向价值。

包含：

- 竞品好评卖点排行
- 竞品正向主题簇
- 竞品代表性好评证据
- 值得借鉴的设计/体验点

图表：

- 竞品卖点主题排行
- 正向主题簇占比图
- 好评主题站点/产品分布图

#### 6. 竞品差评与机会窗口

只保留少量内容，不抢主篇幅。

包含：

- 竞品高频短板
- 与我方改良方向相关的机会窗口
- 少量代表性差评样本

#### 7. 图片与证据附录

包含：

- 高价值带图评论
- 原文/译文摘录
- 对应产品、SKU、站点、发布时间
- 标签与问题簇

#### 8. 数据口径与范围说明

必须显式说明：

- `ingested_review_rows` 与 `site_reported_review_total_current` 的区别
- 时间轴口径
- 首日全量与后续增量模式的区别
- 当前报告是否全量覆盖还是样本覆盖
- 翻译覆盖率与标签覆盖率

## 双模式渲染

### 模式 A：首日全量建基线

触发条件：

- 当前 `logical_date` 之前，不存在已完成且带 `analytics_path` 的历史 daily run
- 或者存在历史 daily run，但过去 30 天可用 daily run 少于 3 个，无法形成最低限度基线

特点：

- 以全量现状为主
- 不强讲长期趋势
- 风险判断以当前横截面为主
- 建立问题簇和卖点的初始基线

### 模式 B：后续增量监控 + 30 天基线对比

触发条件：

- 当前 `logical_date` 之前，至少存在 1 个已完成且带 `analytics_path` 的历史 daily run
- 过去 30 天内至少有 3 个可用 daily run，可形成滚动基线

特点：

- 以当日新增评论和新增风险为主
- 用近 30 天滚动基线判断是否异常
- 报告内容压缩到“今天值得处理的变化”

### 稀疏日策略

当日新增评论很少时：

- 保留同样模板
- 压缩展开内容
- 显式写明“今日无显著新增风险”或“仅出现局部新增信号”
- 用存量高风险项和基线变化托底

### 基线计算规则

- 基线窗口默认取当前 `logical_date` 之前 30 个自然日
- 基线不包含当前 run
- 如果历史 run 数量不足 3 个：
  - 报告继续生成
  - 但在口径说明中标记为“基线样本不足”
  - 趋势结论降级为观察性结论，不输出强异常判断

## 数据口径与语义

### 评论相关

- `ingested_review_rows`
  指 `reviews` 表中实际入库评论行数
- `site_reported_review_total_current`
  指站点页面显示的当前评论总数，通常来自 `products.review_count`

报告中禁止把这两个口径混称为同一个“评论数”。

### 时间轴

- `product_state_time`
  用于当前产品价格、库存、评分、站点显示评论总数
- `review_ingest_time`
  用于“今天抓到了什么”
- `review_publish_time`
  用于“用户在什么时间发表了什么”

默认：

- 当日新增报告主要看 `review_ingest_time`
- 趋势和主题变化在必要时参考 `review_publish_time`

### ownership

报告中的 `自有/竞品` 默认按当前 `products.ownership` 口径解释。
如果做历史回看，需要在口径说明中明确这是“按当前归属回看”，不是严格历史归属快照。

## 标签层设计

### 目标

为 PDF 提供稳定、可复用的问题簇和正向主题数据，避免每次报表现算导致结果漂移。

标签层只负责 `review 级别的结构化标注`，不负责整份日报聚合，不负责生成最终建议文案。

### 新增表

建议新增 `review_issue_labels`，字段如下：

- `id`
- `review_id`
- `label_code`
- `label_polarity`
- `severity`
- `confidence`
- `source`
- `taxonomy_version`
- `created_at`
- `updated_at`

### 字段语义

- `label_code`
  稳定标签编码
- `label_polarity`
  `negative` / `positive`
- `severity`
  `low` / `medium` / `high`
- `confidence`
  0 到 1 的浮点值
- `source`
  `rule` / `llm` / `human`
- `taxonomy_version`
  用于兼容后续 taxonomy 演进

### 一期 taxonomy

#### 负向标签

- `quality_stability`
- `structure_design`
- `assembly_installation`
- `material_finish`
- `cleaning_maintenance`
- `noise_power`
- `packaging_shipping`
- `service_fulfillment`

#### 正向标签

- `easy_to_use`
- `solid_build`
- `good_value`
- `easy_to_clean`
- `strong_performance`
- `good_packaging`

### 标签生成策略

一期采用 `规则 + LLM 归一化` 的混合模式。

规则负责：

- 快速筛出明显主题
- 控制成本
- 保证稳定性

LLM 负责：

- 对规则结果归一化
- 对未命中的评论补标
- 生成短摘要，供建议层使用

### 一期执行方式

为避免首日全量场景下的同步放大，一期采用分层执行：

1. 对当前 report scope 内评论先做同步规则标注
2. 对规则未命中或高优样本，做有上限的 LLM 归一化
3. 对首日全量场景：
   - 全量评论至少具备规则标签
   - LLM 只处理高影响样本和代表性样本，不追求首日全量 LLM 覆盖
4. 标签结果落库到 `review_issue_labels`

### analytics 与标签层边界

- `review_issue_labels`
  行级事实层，粒度是“某条评论具备某个标签”
- `analytics JSON`
  run 级 artifact，粒度是“本次日报的聚合结果和样本证据”

禁止让 analytics 反向替代标签层长期存储，也禁止只用 analytics 支撑问题簇复用。

### 一期约束

- 不做开放式自由问题簇生成
- 不允许 taxonomy 每日漂移
- 对全量历史评论不在 full report 阶段同步补标

## 分析 artifact 设计

### 新增 analytics JSON

在 snapshot 冻结后、生成 PDF 前，新增一个分析 artifact。

建议内容包括：

- `run_id`
- `logical_date`
- `mode`
- `snapshot_hash`
- 核心 KPI
- 自有产品风险排序
- 自有产品问题簇统计
- 改良建议列表
- 竞品好评主题排行
- 竞品代表性好评样本
- 高价值图片评论索引
- 口径元数据

### 目的

- 保证 PDF 结果可复现
- 避免同一 run 多次生成时出现分析漂移
- 方便后续 AI digest 或额外产物复用

### 与 snapshot 的关系

- `snapshot`
  冻结原始输入边界
- `analytics`
  冻结基于 snapshot 和已落库标签计算出的聚合输出

同一 run 的 PDF 只能基于同一份 snapshot 和 analytics 生成，不能再次对原始表自由重算。

## 工作流接入设计

### 现有主链路

- snapshot 冻结
- fast report
- full report

### 一期调整

不改变主控制流，只扩展 full report 产物层。

在 [qbu_crawler/server/report_snapshot.py](/e:/Project/ForcomeAiTools/Qbu-Crawler/qbu_crawler/server/report_snapshot.py#L95) 的 `generate_full_report_from_snapshot()` 中扩展：

1. 读取 snapshot
2. 生成 analytics JSON
3. 生成 Excel
4. 生成 PDF
5. 多附件发送邮件
6. 返回 `excel_path + pdf_path + analytics_path`

### workflow_runs 扩展

建议新增字段：

- `pdf_path`
- `analytics_path`

当前只有 `excel_path` 不足以表达完整产物。

### 通知兼容

`workflow_full_report` 现有 payload 保留不变字段，同时追加：

- `pdf_path`
- 可选 `analytics_path`

不能修改现有 `excel_path` 语义，避免 bridge 和模板震荡。

### 邮件契约最小变更

当前 [qbu_crawler/server/report.py](/e:/Project/ForcomeAiTools/Qbu-Crawler/qbu_crawler/server/report.py#L305) 的 `send_email()` 只支持单附件。

一期最小变更为：

- 将 `attachment_path` 扩展为 `attachment_paths`
- 保持旧调用兼容：
  - 传单字符串时按单附件处理
  - 传列表时按多附件处理
- full report 正式使用：
  - Excel
  - PDF

邮件正文一期仍保持文本正文，不引入 HTML 邮件。

### AI digest

一期继续保持兼容，不要求 AI digest 解析 PDF。
如果需要，可优先使用 analytics JSON 和现有 snapshot_hash。

## 模块职责调整

### `qbu_crawler/server/report.py`

新增职责：

- 构建 analytics 聚合结果
- 渲染 PDF
- 支持多附件邮件发送

保留职责：

- 查询产品和评论
- 生成 Excel
- 组装邮件基础内容

### `qbu_crawler/server/report_snapshot.py`

新增职责：

- 基于 snapshot 生成 analytics artifact
- 协调 Excel + PDF 双产物
- 返回扩展后的 full report 结果

### `qbu_crawler/server/workflows.py`

保留职责：

- 编排 full report 阶段
- 更新 workflow 状态
- 派发通知

只做必要的返回字段扩展，不承担复杂分析逻辑。

## PDF 技术路线

### 推荐路线

采用 `HTML 模板 -> headless 浏览器导出 PDF`。

### 原因

- 图表、图片、分页和中文排版稳定
- 适合复杂图文混排
- 适合做“分层阅读”的正式版式
- 后续可复用 HTML 做预览页

### 部署前提

当前项目依赖中没有现成 PDF 渲染依赖，因此一期必须显式补齐以下运行前提之一：

1. Python 侧引入可控的 headless 浏览器依赖，并由项目负责安装
2. 服务运行环境预装 Chromium/Chrome，并通过配置提供可执行路径

无论采用哪种方式，都必须满足：

- 支持无头渲染
- 支持中文字体
- 支持本地图片和嵌入式图表输出

### 失败策略

如果 PDF 渲染前提不满足：

- full report 视为失败
- run 进入 `needs_attention`
- 不允许静默降级成“只发 Excel 但冒充成功”

## 依赖与技术选型

### 目标

技术选型必须同时满足：

- PDF 版式优雅、干净、稳定
- 图表和图片支持良好
- 中文排版可控
- 首次开发速度快
- 与当前 daily workflow 集成成本低
- 后续维护成本可控

### 方案对比

#### 方案 A：Jinja2 + HTML/CSS + Playwright + 静态图表

优点：

- 最适合做高质量版式
- 浏览器打印结果稳定
- 易于调试，先看 HTML 再导出 PDF
- 适合图文混排、分页控制、页眉页脚、封面设计
- 与现有项目“浏览器自动化”能力模型接近

缺点：

- 需要新增浏览器渲染依赖
- 部署机必须具备 Chromium 运行前提

结论：

一期推荐采用

#### 方案 B：Jinja2 + HTML/CSS + WeasyPrint + 静态图表

优点：

- Python 侧整合更纯
- 适合静态 HTML 到 PDF 渲染

缺点：

- 对系统字体和依赖环境较敏感
- 面对复杂页面还原、长文分页和部分样式细节时弹性不如 Chromium
- 当前项目没有现成相关依赖和运行经验

结论：

作为备选，不作为一期主路线

#### 方案 C：ReportLab 直接生成 PDF

优点：

- 底层可控
- 不依赖浏览器

缺点：

- 开发成本高
- 做出“优雅、干净、漂亮”的日报排版成本明显更高
- 不适合频繁调整版式

结论：

不适合作为一期主路线

#### 方案 D：DOCX 作为主产物，再转 PDF

优点：

- 可编辑

缺点：

- 转换链更长
- 版式一致性和自动化部署复杂度更高
- 不适合每日自动发送的正式主产物

结论：

不采用

### 一期依赖建议

推荐新增依赖：

- `jinja2`
  用于 HTML 模板渲染
- `playwright`
  用于 headless Chromium 打印 PDF
- `matplotlib`
  用于生成基础静态图表，优先输出 SVG

可选依赖：

- `seaborn`
  如果热力图、统计图样式需要更快成型

一期不建议引入：

- `plotly + kaleido`
  视觉更强，但依赖和运行前提更重，可留到二期
- `weasyprint`
  不作为一期主路线
- `reportlab`
  不作为日报主产物路线

### 选型结论

一期技术选型固定为：

- 模板层：`Jinja2`
- 图表层：`matplotlib` 输出 `SVG/PNG`
- PDF 渲染层：`Playwright + Chromium`
- 数据边界：`snapshot + analytics`

这套组合在“美观度、稳定性、迭代速度、兼容性、维护成本”之间最均衡。

## PDF 版式设计原则

### 视觉方向

日报必须满足：

- 干净
- 稳定
- 易扫描
- 适合打印和移动端预览

不追求炫技风格，不使用过重视觉元素。

### 版式规则

- 纸张固定为 A4
- 使用统一页边距
- 统一页眉页脚
- 控制单页信息密度
- 标题层级不超过 3 层
- 正文只放重点图表和重点表格
- 大明细全部留给 Excel

### 视觉 token

应在模板层固化：

- 字体族
- 标题字号
- 正文字号
- 行高
- 颜色体系
- 卡片边框
- 圆角
- 页内间距
- 图表默认色板

### 图表规则

- 优先使用 `SVG`
- 每份日报图表总数建议控制在 6 到 8 张
- 统一颜色语义：
  - 风险/负向：红或橙
  - 正向/竞品优势：绿或蓝
  - 中性/基线：灰
- 避免 3D 图、饼图堆砌、装饰性阴影

### 分页规则

通过 print CSS 控制：

- 避免标题孤行
- 避免卡片被硬切页
- 图片评论卡片尽量整块分页
- 长表格只出现在附录或 Excel，不在正文跨多页铺开

## 模块设计

### 新增模块建议

#### `qbu_crawler/server/report_analytics.py`

职责：

- 从 snapshot 和标签层生成 analytics JSON
- 汇总自有产品风险排序
- 汇总问题簇统计
- 汇总竞品正向主题
- 生成 PDF 所需的结构化视图数据

说明：

不要把这部分继续堆进 `report.py`，否则职责会越来越混。

#### `qbu_crawler/server/report_pdf.py`

职责：

- 渲染 HTML
- 生成静态图表
- 调用 Playwright 打印 PDF
- 管理模板、样式、字体和静态资源

说明：

PDF 生成是独立能力，应与 Excel 生成分离。

### 现有模块调整

#### `qbu_crawler/server/report.py`

保留：

- 查询 products/reviews
- 生成 Excel
- 邮件发送

新增最小职责：

- 多附件邮件发送兼容

不建议在这里堆积复杂 PDF 模板逻辑。

#### `qbu_crawler/server/report_snapshot.py`

新增编排职责：

- 在 full report 阶段串联：
  - analytics 生成
  - Excel 生成
  - PDF 生成
  - 多附件发送

### 模块边界结论

- `report.py`
  偏数据查询和 Excel/email 能力
- `report_analytics.py`
  偏 run 级聚合和分析逻辑
- `report_pdf.py`
  偏 HTML/PDF 渲染能力
- `report_snapshot.py`
  偏 full report artifact 编排

## PDF 生成流程

### 运行时流程

1. `WorkflowWorker` 进入 `full_pending`
2. `generate_full_report_from_snapshot(snapshot)` 被调用
3. 调用 `report_analytics.py` 生成 analytics JSON
4. 调用 `report.py` 生成 Excel
5. 调用 `report_pdf.py`：
   - 生成图表资源
   - 渲染 HTML
   - 由 Playwright 导出 PDF
6. 调用多附件邮件发送
7. 更新 `workflow_runs` 的 artifact 路径
8. 派发 `workflow_full_report`

### 本地调试流程

开发阶段应支持：

1. 单独输入 snapshot/analytics
2. 先产出 HTML 预览
3. 人工确认版式
4. 再导出 PDF

这样可以显著降低调试成本。

### 不推荐的一期路线

- 直接用 Python 原生 PDF 库做复杂排版
- 直接走 DOCX 作为正式主产物

旧的 Node `docx` 样例仅作为章节结构参考，不作为一期主路线。

## 性能与规模约束

目标规模是：

- 上百产品
- 几万评论

因此一期必须遵守以下约束：

- full report 阶段不对全量评论做自由式同步 LLM 深描
- 报告正文只展示 Top 风险产品、Top 问题簇、Top 借鉴卖点
- Excel 承接大明细
- 标签层优先做增量补标，历史回填留到二期
- 趋势图只覆盖少数核心指标

## 错误处理与降级策略

### PDF 生成失败

- full report 失败，run 进入 `needs_attention`
- 保留 snapshot 和 analytics（如果已生成）
- 不冒充成功发送

### 标签层未完全覆盖

- PDF 允许显式标注“标签覆盖中”
- 不阻塞 Excel 产出
- 不生成过强建议

### 历史数据不足

- 自动降级为“建基线版”
- 不输出强趋势结论

### 附件发送失败

- workflow_full_report 仍可写入 artifact 路径
- 邮件状态显式标记失败
- 不掩盖错误

### schema 兼容

你给的最新数据库样本显示，生产库 schema 可能比当前迁移版本更轻。

因此一期必须满足：

- 新字段通过 migration 追加，不依赖重建库
- 报表查询对缺失字段做兼容判断
- 标签层新增表必须是向后兼容扩展
- 不假设所有环境都已经拥有 `created_at` 一类审计字段

## 测试策略

至少新增或覆盖以下测试：

1. `tests/test_report.py`
   - 多附件邮件发送
   - PDF artifact 路径产出
   - analytics JSON 结构
2. `tests/test_report_snapshot.py`
   - 从 snapshot 生成 `excel + pdf + analytics`
   - 双模式渲染选择
3. `tests/test_workflows.py`
   - full report payload 增加 `pdf_path`
   - workflow_runs 持久化 `pdf_path / analytics_path`
4. 新增标签层测试
   - taxonomy 约束
   - review 到标签的落库
   - 正向/负向标签共存
5. 回归测试
   - 现有 Excel full report 不被破坏
   - 不影响 fast report 和现有通知语义

## 一期范围

一期必须完成：

- `workflow_runs` 增加 `pdf_path`、`analytics_path`
- `send_email()` 支持多附件
- snapshot 后生成 analytics JSON
- 生成主 PDF
- 自有产品差评主轴
- 竞品好评 benchmark
- 轻量正负标签层
- 同模板双模式渲染

一期不做：

- 多份正式日报
- 外部客户版 PDF
- 全量历史标签回填
- 开放式自由 taxonomy
- 全维度长期趋势
- 深度根因承诺

## 二期演进

二期可以扩展：

- 更细 taxonomy
- 历史评论回填标签
- 日级聚合表
- 更丰富的趋势与异常检测
- 更强的建议生成
- 外部轻量版 PDF

## 实施顺序建议

1. 数据结构扩展
   - `workflow_runs` 新字段
   - `review_issue_labels`
2. analytics 生成
3. 多附件邮件
4. PDF 渲染
5. full report 接入
6. 回归测试

## 最终决策

采用以下方案：

- daily workflow 保持单出口
- 正式产物升级为 `snapshot + analytics + Excel + PDF`
- 自有产品：差评、问题簇、改良建议为主
- 竞品：好评 benchmark 为主，差评为辅
- 同一模板双模式渲染
- 一期即上线轻量正负标签层

这是当前需求、代码结构和真实数据规模下，语义最真实、重点最清晰、可维护性最强的一期设计。
