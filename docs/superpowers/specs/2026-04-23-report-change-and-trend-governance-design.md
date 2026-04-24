# 报表“今日变化”与“变化趋势”语义统一设计

**日期**: 2026-04-23  
**状态**: 已确认，分两期实施  
**范围**: 日报主报表的信息架构、数据契约、时间口径、邮件/HTML/Excel 对齐  
**改动级别**: 中等，新增归一化字段与展示入口，不新增新的报表类型

---

## 1. 背景

围绕每日任务与首次运行产物的检查，已经确认当前报表存在一组会持续放大误解的问题：

- 首跑基线被误表述成“今日新增”
- 邮件 KPI 与 HTML/analytics 不一致
- Excel `产品概览` 的“采集评论数”口径错误
- `今日变化` 在 HTML 中还是空壳，缺少稳定的信息边界
- 趋势能力只有底层数据，没有成为独立的阅读入口
- 评论发布时间、采集时间、快照时间被混用，导致补采和真实新增无法区分

这次改版的目标不是再做一套周报、月报，而是在唯一主报表内把三类阅读任务稳定分开：

- 看最新：`今日变化`
- 看整体：`总览 / 问题诊断 / 产品排行 / 竞品对标 / 全景数据`
- 看走势：`变化趋势`

---

## 2. 设计目标

### 2.1 目标

- 保留当前日报作为唯一主报表，不新增周报、月报产物
- 在单一报表契约下落地 `今日变化` 与 `变化趋势`
- 修正首跑、补采、增量、趋势四类语义混用
- 让 email / HTML / Excel 统一消费同一份归一化契约
- 为后续实现提供不漂移的字段定义、时间口径和边界约束

### 2.2 非目标

- 不拆新的 workflow 类型
- 不改 daily scheduler、trigger_key、调度策略
- 不处理 outbox / deadletter / bridge 401 状态机
- 不改动生产环境既有产物内容本身，但要处理 artifact 路径可迁移性
- 不大改现有视觉风格，只做信息架构和契约层治理

### 2.3 分期策略

本方案按两期实施，但两期共享同一套语义契约；第二期只能增强，不允许另起一套口径。

#### Phase 1：语义治理与止血

- 建立顶层统一字段：`report_semantics`、`is_bootstrap`、`change_digest`、`trend_digest`
- 明确顶层 `kpis` 是唯一展示 KPI 源，禁止 HTML / 邮件 / Excel 直接展示 `cumulative_kpis` 或自行拼 `window.*`
- 修复已确认的当前口径问题：
  - `bootstrap` 被误写成“今日新增”
  - 邮件 / HTML / Excel KPI 不一致
  - Excel `产品概览` “采集评论数”错误
  - Excel “本次新增”列双态语义不完整
- 落地 `今日变化` tab 的正式契约与页面边界
- 落地 `变化趋势` tab 的基础能力：
  - `周 | 月 | 年`
  - `舆情趋势 | 问题趋势 | 产品趋势 | 竞品趋势`
  - `ready | accumulating | degraded` 状态分层
  - 样本不足说明
  - 每个维度至少一组稳定的 KPI / 主图 / 基础表
- 落地 LLM `bootstrap | incremental` 语义输入与 `bootstrap` 下 deterministic fallback
- 落地 artifact resolver，兼容绝对路径、相对路径和生产拷贝后的本地路径

#### Phase 2：趋势深化与阅读增强

- 丰富 `trend_digest` 的细粒度指标、辅图、表格和 Top 实体清单
- 完整铺开四个趋势维度的派生指标与阅读层级
- 增强环比、同比、期初/期末变化等趋势表达
- 在不改变 Phase 1 契约的前提下，增强 HTML / Excel 的趋势阅读体验

---

## 3. 已确认的关键决策

以下内容已在讨论中确认，属于本设计的硬约束：

- 采用单一报表契约方案，不再让邮件、HTML、Excel 各自解释原始字段
- `snapshot` 继续表示“本次 run 实际入库”的 products / reviews，不改变冻结语义
- 顶层需要显式新增语义字段：
  - `report_semantics = bootstrap | incremental`
  - `is_bootstrap`
  - `change_digest`
  - `trend_digest`
- `window.reviews_count` 不再解释成“今日新增评论”，只能解释成“本次入库评论数”
- 顶层 `kpis` 是唯一展示 KPI 源，`cumulative_kpis` 只保留给分析层，不允许直接被展示层消费
- `bootstrap` 时，邮件 / HTML / Excel 统一使用建档/基线话术，禁止出现“今日新增 X 条”
- `今日变化` 作为“本期观察入口”，在 `incremental` 下解释增量，在 `bootstrap` 下展示监控起点态
- `变化趋势` 作为跨周期入口，入口常驻，内容按样本状态分层
- 不新增周报、月报产物；跨周期能力统一吸收到 `变化趋势`
- `变化趋势` 的主交互为 `周 | 月 | 年`
- `fresh` 的业务窗口固定为近 30 天
- `backfill_dominant` 阈值固定为 70%
- LLM prompt 必须感知 `bootstrap | incremental`，`bootstrap` 下如果输出“今日新增/今日暴增”类措辞，必须回退到 deterministic fallback
- 真实生产报告目录以 `C:\Users\User\Desktop\QBU\reports` 为准；`C:\Users\leo\Desktop\pachong` 仅作为本地拷贝参考，不得把它写回设计为生产真值

---

## 4. 信息架构

### 4.1 顶层 tab

主报表 tab 调整为：

- `总览`
- `今日变化`
- `变化趋势`
- `问题诊断`
- `产品排行`
- `竞品对标`
- `全景数据`

上述命名与顺序属于展示契约；实现阶段不得随意改名、换序或按载体裁剪出第二套顶层导航。

### 4.2 每个 tab 的职责

#### 总览

- 只看当前整体状态
- 包含 hero、KPI、关键判断、报告口径、行动建议
- 不再承担“今天新增了什么”

#### 今日变化

- 只看本期增量信号
- 只回答“这一期相比上一期，有什么值得立刻看”
- 不放持续关注、全量排行、全量风险摘要

#### 变化趋势

- 只看跨周期走势
- 只回答“过去几周/几月/几年在变好还是变坏”
- 不承担日级事件流

#### 问题诊断 / 产品排行 / 竞品对标 / 全景数据

- 继续按全量当前视角展示
- 允许加“新出现/已升级”标记
- 不改成增量页

### 4.3 模式规则

- `bootstrap`
  - `今日变化` 入口保留，展示“监控起点”态
  - 禁止使用“今日新增/较昨日/较上期”类增量措辞
  - `变化趋势` 入口保留，并按各维度样本状态展示 `ready | accumulating | degraded`
- `incremental`
  - 显示 `今日变化`
  - `变化趋势` 按各维度样本充足程度决定展示完整图表或状态说明

补充约束：

- 顶层 tab 不因数据不足被裁掉，只允许内容进入不同状态
- “功能不砍”指入口与信息架构常驻，不代表在样本不足时伪造趋势或伪造增量
- 任一模块在 `accumulating` 或 `degraded` 状态下，都必须给出明确解释文案

---

## 5. 统一语义模型

### 5.1 顶层语义字段

在 analytics 顶层新增：

```json
{
  "report_semantics": "bootstrap",
  "is_bootstrap": true,
  "change_digest": {},
  "trend_digest": {}
}
```

定义：

- `report_semantics`
  - `bootstrap`: 首次建档 / 基线期
  - `incremental`: 已有历史样本，可解释增量与趋势
- `is_bootstrap`
  - `report_semantics == "bootstrap"` 的便捷布尔值

### 5.2 原始结构保留规则

- `snapshot`
  - 保留为 run 级冻结产物
  - 只表示本次入库窗口
- `window`
  - 继续作为底层中间态保留
  - 不允许模板直接绑定 UI 文案
- `cumulative_kpis`
  - 保留为分析辅助结构
  - 不允许邮件 / HTML / Excel 直接消费

### 5.3 KPI 单一展示源

- `kpis` 是所有载体唯一允许展示的 KPI 源
- 总览 Hero、邮件摘要卡、HTML KPI 卡、Excel 摘要区必须都从顶层 `kpis` 取值
- 任何“为了方便”而从 `cumulative_kpis`、`window`、`snapshot` 临时重算展示 KPI 的实现，都视为违背设计

---

## 6. 时间口径

### 6.1 两类时间

必须严格区分两类时间：

- 业务时间
  - 来源：`date_published_parsed`
  - 用于评论新增、问题热度、舆情趋势
- 状态时间
  - 来源：`scraped_at` / `logical_date`
  - 用于价格、评分、库存、评论总数等产品状态变化

### 6.2 业务新增定义

- `fresh_review_count`
  - 本次入库评论中，发布时间在 `logical_date` 前 30 天内的评论数
- `historical_backfill_count`
  - `ingested_review_count - fresh_review_count`
- `fresh_own_negative_count`
  - 本次入库评论中，自有、近 30 天、评分小于等于阈值的评论数

### 6.3 趋势聚合规则

- 周视角
  - 最近 12 周，按周聚合，显示环比上周
- 月视角
  - 最近 12 个月，按月聚合，显示环比上月
- 年视角
  - 最近 5 年，按年聚合，显示同比去年

附加规则：

- 未结束周期必须标记 `进行中`
- 比例类指标必须按分子分母重算
- 状态类指标默认取期末值，并展示期初到期末变化

---

## 7. 今日变化设计

### 7.1 唯一契约

`今日变化` 的唯一输入是 `change_digest`

```json
{
  "change_digest": {
    "enabled": true,
    "view_state": "bootstrap",
    "suppressed_reason": "",
    "summary": {},
    "issue_changes": {},
    "product_changes": {},
    "review_signals": {},
    "warnings": {},
    "empty_state": {}
  }
}
```

### 7.2 summary 字段

```json
{
  "summary": {
    "ingested_review_count": 0,
    "ingested_own_review_count": 0,
    "ingested_competitor_review_count": 0,
    "ingested_own_negative_count": 0,
    "fresh_review_count": 0,
    "historical_backfill_count": 0,
    "fresh_own_negative_count": 0,
    "issue_new_count": 0,
    "issue_escalated_count": 0,
    "issue_improving_count": 0,
    "state_change_count": 0
  }
}
```

约束：

- `ingested_*` 都是“本次入库”
- `fresh_*` 才是业务新增
- 模板禁止把 `ingested_review_count` 文案写成“今日新增评论”
- `bootstrap` 时 `summary` 仍必须有值，用于监控起点说明，不能因为没有上期对比而整体置空

### 7.3 issue_changes

四类变化：

- `new`
- `escalated`
- `improving`
- `de_escalated`

内部 item 统一字段：

- `label_code`
- `label_display`
- `change_type`
- `current_review_count`
- `delta_review_count`
- `affected_product_count`
- `severity`
- `severity_changed`
- `days_quiet`

### 7.4 product_changes

包含：

- `price_changes`
- `stock_changes`
- `rating_changes`
- `new_products`
- `removed_products`

每类 item 至少保留：

- `sku`
- `name`
- `old`
- `new`

### 7.5 review_signals

只服务行动，不服务统计：

- `fresh_negative_reviews`
  - 自有、近 30 天、差评
  - 默认前 5 条
- `fresh_competitor_positive_reviews`
  - 竞品、近 30 天、好评
  - 默认前 3 条

排序原则：

- 自有差评：评分升序、发布时间降序、带图优先
- 竞品好评：评分降序、发布时间降序

### 7.6 warnings

包含：

- `translation_incomplete`
- `estimated_dates`
- `backfill_dominant`

定义：

- `translation_incomplete`
  - 翻译未全部完成
- `estimated_dates`
  - 相对日期估算比例过高
- `backfill_dominant`
  - `historical_backfill_count / ingested_review_count >= 0.7`

约束：

- `warnings` 必须显式保留上述三个键，即使当前未触发也不能在契约层消失
- 展示层只渲染已触发 warning，未触发 warning 不得输出空占位
- `translation_incomplete` 与 `estimated_dates` 必须允许携带说明文案，避免用户只看到布尔值
- `estimated_dates` 不仅用于“估算比例过高”，也用于“相对时间解析失败后进入降级口径”的提示

### 7.7 empty_state

`今日变化` 在 `incremental` 且“无显著变化”时，必须走显式空态而不是渲染空模块。

最小结构：

```json
{
  "empty_state": {
    "enabled": true,
    "title": "本期无显著变化",
    "description": "本次运行未发现需要立即处理的新增问题或明显产品状态变化。"
  }
}
```

约束：

- `empty_state.enabled = true` 时，问题变化 / 产品变化 / 评论信号模块可以折叠或弱化，但不能输出空表或 `None`
- `empty_state` 只表示“本期无显著变化”，不能和 `bootstrap` 复用

### 7.8 页面结构

`今日变化` HTML 固定四段：

- 变化摘要
- 问题变化
- 产品状态变化
- 新近评论信号

明确禁止放入：

- 持续关注产品
- 全量风险排行
- 全量问题摘要
- 评论全量明细

并且必须遵守：

- 不得把“持续关注产品”“全量风险排行”“问题诊断全量摘要”等现有全量模块直接搬进 `今日变化`
- warning 和 empty_state 只能作为顶部提示或说明，不能把 `今日变化` 重新演化成“总览第二页”

### 7.9 模式行为

- `bootstrap`
  - `enabled = true`
  - `view_state = "bootstrap"`
  - 可以抑制“对上期变化”子模块，但不能隐藏 tab
  - 顶部主文案固定为“监控起点 / 首次建档 / 当前截面”，不得写成增量变化
- `incremental + backfill_dominant`
  - tab 仍显示
  - 顶部醒目标记“本次以历史补采为主”
- `incremental + 无显著变化`
  - 显示空状态“本期无显著变化”

---

## 8. 变化趋势设计

### 8.1 唯一契约

`变化趋势` 的唯一输入是 `trend_digest`

它是一个“时间视角 × 数据维度”的二维结构。

### 8.2 交互结构

- 一级切换：`周 | 月 | 年`
- 二级切换：`舆情趋势 | 问题趋势 | 产品趋势 | 竞品趋势`
- 默认视图：`月 + 舆情趋势`

约束：

- HTML 初始渲染和前端 JS 默认选中态都必须是 `月 + 舆情趋势`
- 默认视图属于体验契约，不能因为实现方便改成别的组合

### 8.3 四个维度

#### 舆情趋势

- 评论量趋势
- 自有差评数趋势
- 自有差评率趋势
- 健康指数趋势

#### 问题趋势

- Top 问题簇热度趋势
- 受影响 SKU 数趋势
- 新增 / 升级 / 缓解问题数趋势

#### 产品趋势

- 重点 SKU 评分趋势
- 重点 SKU 价格趋势
- 评论总数趋势
- 库存状态变化

#### 竞品趋势

- 自有 vs 竞品平均评分趋势
- 自有差评率 vs 竞品好评率趋势
- 差距指数趋势

### 8.4 分期落地结构

#### Phase 1

- 每个维度至少提供：
  - 1 组稳定趋势 KPI
  - 1 张主图
  - 1 张基础表
- `周 | 月 | 年` 与四个维度切换完整可用
- 每个可视组件必须显式携带 `status = ready | accumulating | degraded`
- 样本不足时只能展示说明，不能伪造图表
- 同一维度内部允许部分组件 `ready`、部分组件 `accumulating`
- 首日监控场景必须允许混合就绪态：
  - `舆情趋势` / `问题趋势` 可仅凭 `date_published_parsed` 进入 `ready`
  - `产品趋势` 中依赖连续 `product_snapshots` 的组件进入 `accumulating`
  - `竞品趋势` 允许按子组件混合状态输出，不能整维度一刀切成同一状态

#### Phase 2

- 每个维度扩展为：
  - 顶部 4 个趋势 KPI
  - 中间 1 张主图
  - 下方 2 张辅图
  - 底部 1 张表
- 支持更完整的派生趋势、排名表、对比表

### 8.5 行为约束

- `变化趋势` 不承担“今天发生了什么”
- 历史样本不足时展示说明，不伪造趋势
- 以评论发布时间聚合即可成立的趋势，应优先进入 `ready`
- 依赖连续 run / `product_snapshots` 的状态趋势，在样本不足时进入 `accumulating`
- 读取历史上下文失败、产物路径失配或字段缺失时进入 `degraded`，并显式提示原因
- 不同指标不得为了“统一展示”被强行拉到同一时间轴；竞品维度尤其要区分评论发布时间类指标与状态快照类指标
- `年` 视角前期允许为空，但入口保留

---

## 9. 各载体分工

### 9.1 邮件

只做摘要型表达：

- 总览摘要
- 今日变化摘要
- 关键风险提醒

禁止在邮件中展开完整趋势页或全量明细。

### 9.2 HTML

承担完整阅读体验：

- 完整 tab 结构
- `今日变化` 与 `变化趋势` 的主要交互入口

### 9.3 Excel

承担明细与审计：

- 保留全量明细
- 新增 `今日变化` sheet
- 保留并增强 `趋势数据` sheet

Excel 特别规则：

- `产品概览` 的“采集评论数”必须按真实 review 聚合
- “本次新增”列：
  - `bootstrap`: `新近 / 补采`
  - `incremental`: `新增 / 空`

---

## 10. 文案与 LLM 规则

### 10.1 bootstrap

- 邮件、HTML、Excel 统一使用建档/基线话术
- 禁止出现“今日新增 X 条”

### 10.2 incremental

- 允许使用“今日变化”叙述
- 但 `ingested_review_count` 不得被解释为业务新增

### 10.3 LLM 语义安全

- prompt 必须显式传入 `report_semantics = bootstrap | incremental`
- prompt 必须显式区分：
  - `bootstrap` = 建档/基线期
  - `incremental` = 可解释本期变化
- `bootstrap` 下不得向模型注入“今日新增评论”类 prompt 片段
- `bootstrap` 下如果模型输出“今日新增”“今日暴增”等措辞，必须回退到 deterministic fallback
- deterministic fallback 生成的文案也必须遵循同一套 `bootstrap` 话术

### 10.4 文案卫生

- 邮件 / HTML / Excel 均不得直接输出 `None`、`null`、空字典、空数组或其他内部占位串
- 缺失数据必须通过三种方式之一处理：
  - 隐藏模块
  - 使用明确空态文案
  - 使用已定义的 warning / sample status 说明
- 任何“持续 None”“未知 None”之类文案都视为实现回归

### 10.5 富化字段回退

- `impact_category_display` 必须遵循：
  - 优先使用 `impact_category`
  - 否则回退到 `failure_mode`
  - 再否则回退到可读的标签/主题摘要
- `headline_display` 必须遵循：
  - 优先使用 `headline_cn`
  - 否则回退到 `headline`
  - 再否则回退到 `body_cn` / `body` 摘要
  - 如仅有图片证据，可回退为“图片证据”
- 原始字段允许为空，但 display 字段不得把空值直接透传到 HTML、邮件或 Excel

---

## 11. 数据层补齐要求

为支撑本设计，report 查询层必须补齐 review 结果字段：

- `scraped_at`
- `site`
- 推荐补 `product_url`

原因：

- `scraped_at` 用于 `今日变化` 中“本次证据”排序和状态核对
- `site` 用于站点维度诊断与明细导出
- `product_url` 用于 HTML / 邮件跳转和行动链接

此外，必须补一层 artifact resolver，用于 previous context 与历史 analytics/snapshot 的可迁移读取：

- 优先读取 `workflow_runs` 中记录的原路径
- 若原路径失效，则回退到当前 `REPORT_DIR`
- 若仍失效，则回退到数据库所在目录旁的 `reports/`
- 必要时允许按 `workflow-run-{id}-*.json` 做同目录兜底搜索

说明：

- 当前真实生产目录为 `C:\Users\User\Desktop\QBU\reports`
- `C:\Users\leo\Desktop\pachong` 是从生产拷贝到本机的参考目录，只用于诊断与本地复盘
- 设计目标不是改写历史产物，而是让读取逻辑具备路径可迁移性

写入侧也必须同步治理：

- 新生成的 `snapshot_path`、`analytics_path`、`html_path`、`excel_path`、`pdf_path` 应优先持久化为相对产物路径
- 读取侧必须继续兼容历史绝对路径，不能因治理写入策略而打断旧 run
- 不允许继续把“当前机器绝对目录”当成唯一真值扩散到新数据

相对时间解析规则也必须补齐：

- 至少覆盖 `hours ago` 这类小时级相对时间
- 解析成功时写入 `date_published_parsed`
- 解析失败时不得静默吞掉，必须通过 `estimated_dates` 或同类降级说明暴露

---

## 12. 防漂移约束

后续实现必须遵守：

- 模板不直接解释 `window.*`
- 模板不直接混读 `changes + window + raw kpis`
- HTML / 邮件 / Excel 一律消费 `change_digest` / `trend_digest`
- HTML / 邮件 / Excel 的展示 KPI 一律消费顶层 `kpis`
- `今日变化` 不得承载全量模块
- `变化趋势` 不得演化成“全景数据第二页”
- 字段名与业务含义必须一一对应
- 新写入的 artifact 路径不得继续固化为单机绝对路径真值
- 富化字段必须先归一化出 display 字段，再进入展示层
- Phase 2 不得绕开 Phase 1 已建立的统一契约

---

## 13. Phase 1 验收标准

- `bootstrap` 报表中不再出现“今日新增”类表述
- HTML `今日变化` 不再是空壳；`bootstrap` 下展示监控起点态，`incremental` 下展示增量信息
- `change_digest.warnings` 的三类 warning 有稳定契约，触发时可展示，未触发时不输出空占位
- `incremental + 无显著变化` 时，`今日变化` 走显式 `empty_state`，不输出空表或空卡片
- HTML `变化趋势` 具备 `周 | 月 | 年` 与四个维度入口
- HTML `变化趋势` 默认视图固定为 `月 + 舆情趋势`
- 样本不足时 `变化趋势` 明确说明，不伪造图表，且组件具备 `ready | accumulating | degraded` 状态
- 邮件、HTML、Excel 对同一 run 的核心 KPI 和变化摘要保持一致
- 顶层 `kpis` 成为唯一展示 KPI 源
- `window.reviews_count` 不再被任何载体解释成业务新增
- 当补采占比 >= 70% 时，报表明确提示“以历史补采为主”
- `产品概览` 的“采集评论数”改为真实 review 聚合
- previous context 在绝对路径、相对路径和生产拷贝路径下都能被稳定解析
- 新 run 写入的 artifact 路径不再继续固化单机绝对路径
- Excel “本次新增”列同时满足：
  - `bootstrap = 新近 / 补采`
  - `incremental = 新增 / 空`
- LLM 文案在 `bootstrap` 模式下能稳定回退到确定性话术
- 任一载体中不再出现 `None` / `null` / 内部空占位串
- `impact_category_display` 与 `headline_display` 的回退链稳定可用
- 相对时间解析失败会被显式暴露，不会静默污染 freshness / 趋势口径
- 首日监控场景下，`变化趋势` 至少表现为：
  - `舆情趋势` / `问题趋势` 可 `ready`
  - `产品趋势` 至少部分组件 `accumulating`
  - `竞品趋势` 允许混合状态

---

## 14. Phase 2 验收标准

- `trend_digest` 四个维度均具备稳定的扩展图表和基础表格
- `变化趋势` 的 `周 | 月 | 年` 视角均有清晰的环比 / 同比 / 期初期末表达
- HTML / Excel 趋势页具备更完整的主图、辅图、表格组合
- Phase 2 的增强没有引入第二套 KPI、第二套趋势口径或模板侧重算逻辑

---

## 15. 结论

本设计并不是“加两个 tab”，而是一次报表语义治理：

- 用统一契约修正口径
- 用 `今日变化` 承接增量入口
- 用 `变化趋势` 承接跨周期入口

实现阶段必须先建立统一数据契约，再接模板与导出层；禁止直接在模板里继续拼装旧字段。Phase 1 先止血、先统一语义；Phase 2 再在同一契约上做趋势深化。
