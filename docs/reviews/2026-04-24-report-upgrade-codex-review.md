# 1. 审查范围与资料

本次为独立只读审查，范围覆盖：

- 权威文档：
  - `docs/superpowers/specs/2026-04-23-report-change-and-trend-governance-design.md:51-68,81-100,146-160,168-203,207-219,430-510,542-580,611-628,655-680`
  - `docs/superpowers/plans/2026-04-23-report-change-and-trend-governance.md:52-59,193-195,329-348`
  - `docs/devlogs/D018-report-change-trend-governance.md:34-44,48-58,81-85`
- 代码：
  - `qbu_crawler/server/report.py`
  - `qbu_crawler/server/report_snapshot.py`
  - `qbu_crawler/server/report_analytics.py`
  - `qbu_crawler/server/report_common.py`
  - `qbu_crawler/server/report_charts.py`
  - `qbu_crawler/server/report_llm.py`
  - `qbu_crawler/server/report_templates/daily_report_v3.html.j2`
  - `qbu_crawler/server/report_templates/email_full.html.j2`
  - `qbu_crawler/server/report_templates/daily_report_v3.js`
  - `qbu_crawler/server/report_templates/daily_report_v3.css`
- 产物：
  - `test1 analytics` = `C:\tmp\qbu-review\test1\reports\workflow-run-1-analytics-2026-04-24.json`
  - `test1 html` = `C:\tmp\qbu-review\test1\reports\workflow-run-1-full-report.html`
  - `test1 xlsx` = `C:\tmp\qbu-review\test1\reports\workflow-run-1-full-report.xlsx`
  - `test2 analytics` = `C:\tmp\qbu-review\test2\reports\workflow-run-1-analytics-2026-04-24.json`
  - `test2 snapshot` = `C:\tmp\qbu-review\test2\reports\workflow-run-1-snapshot-2026-04-24.json`
  - `test2 html` = `C:\tmp\qbu-review\test2\reports\workflow-run-1-full-report.html`
  - `test2 xlsx` = `C:\tmp\qbu-review\test2\reports\workflow-run-1-full-report.xlsx`

审查方法：

- 事实：只引用代码、HTML、JSON、Excel 中直接观测到的内容。
- 推测：只在“根因/影响”里使用，并明确标注为推测。
- `UNVERIFIED`：当前包内没有足够产物或数据库上下文，无法直接验证。

三份权威文档在本轮关键约束上是一致的：spec 要求顶层语义字段、`kpis` 单一展示源、`change_digest` / `trend_digest` 唯一输入、趋势三态、artifact 路径可迁移；plan 和 devlog 也在 `plans:54-59,193-195,329-348` 与 `devlog:36-44,50-58,83-85` 重复确认了同一组目标，没有发现文档之间互相冲突。

# 2. 对齐矩阵

| spec 硬约束 | 代码证据(file:line) | 产物证据 | 判断 |
| --- | --- | --- | --- |
| 顶层必须新增 `report_semantics` / `is_bootstrap` / `change_digest` / `trend_digest`。`spec:53-54,85-89,168-176` | `qbu_crawler/server/report_analytics.py:1952-1961` `"report_semantics": ... "change_digest": {} "trend_digest": _build_trend_digest(...)`；`qbu_crawler/server/report_common.py:648-658` `normalized = { "report_semantics": ..., "change_digest": ..., "trend_digest": ... }` | `test2 analytics:577-681` 出现 `change_digest`；`test2 analytics:13004-13020` 出现 `trend_digest`；`test2 analytics:2801,3860` 出现 `is_bootstrap` 与 `report_semantics` | PASS |
| 顶层 `kpis` 是唯一展示 KPI 源，展示层不得直接消费 `cumulative_kpis`。`spec:54,91,199-203,642-645` | `qbu_crawler/server/report_templates/email_full.html.j2:9-18` `_kpis = _analytics.get("kpis", {})`；`qbu_crawler/server/report_templates/daily_report_v3.html.j2:38-39,66-79` 只从 `analytics.kpis` 取 Hero/KPI；`qbu_crawler/server/report_templates/email_full.html.j2:238-239` 明写 “KPI 展示统一读取 analytics.kpis” | `test2 analytics:2780-2798` 的 `cumulative_kpis` 没有 `health_index`；`test2 analytics:3787-3804` 的 `kpis.health_index = 94.9`；`test2 html:1605,1613-1614` 页面展示的是 `94.9` | PASS |
| `window.reviews_count` 只能解释成“本次入库评论数”，不得被展示层解释成业务新增。`spec:90,220-226,560-562,666` | `qbu_crawler/server/report_templates/daily_report_v3.html.j2:170-175` 使用 `change_summary.ingested_review_count / fresh_review_count / historical_backfill_count`；`qbu_crawler/server/report_templates/email_full.html.j2:113-117` 同口径；`qbu_crawler/server/report.py:1259-1263` Excel “今日变化”写的是“本次入库评论 / 新近评论 / 历史补采” | `test2 analytics:653-660` `ingested_review_count=593, fresh_review_count=4, historical_backfill_count=589`；`test2 html:1734-1760` 渲染为“本次入库 593 / 新近 4 / 补采 589”；`test2 xlsx[今日变化!B3:C5]` 同口径 | PASS |
| `change_digest.warnings` 必须稳定保留 `translation_incomplete` / `estimated_dates` / `backfill_dominant` 三个键，且只展示已触发项。`spec:349-370,659,667` | `qbu_crawler/server/report_snapshot.py:534-553` 三个 warning 固定出现在 `warnings`；`qbu_crawler/server/report_templates/daily_report_v3.html.j2:157-162` 仅在 `warning.enabled and warning.message` 时渲染；`qbu_crawler/server/report.py:1271-1274` Excel 只写触发项 | `test2 analytics:668-680` 三个键齐全，其中两个 `enabled=true`；`test2 html:1743,1751` 只出现“历史补采为主”“estimated_dates”两条提示，没有空占位 | PASS |
| HTML 必须有 `今日变化` 与 `变化趋势`，`变化趋势` 默认是 `月 + 舆情趋势`。`spec:108-118,128-138,440-447,661-663` | `qbu_crawler/server/report_templates/daily_report_v3.html.j2:53-60` 顶层 tab 固定；`qbu_crawler/server/report_templates/daily_report_v3.html.j2:31-34,266-275` `default_view="month"` / `default_dimension="sentiment"`；`qbu_crawler/server/report_templates/daily_report_v3.js:89-122` 前端切换逻辑基于初始 active 态 | `test2 html:1580-1587` 已有两级入口；`test2 html:1831-1849` 默认激活的是“月 / 舆情趋势” | PASS |
| Excel Phase 1 应为 5 个 sheet，且 `本次新增` 在 `bootstrap` 为 `新近 / 补采`。`spec:539-547,668,671-673` | `qbu_crawler/server/report.py:1076-1084` `bootstrap` 下 `_review_new_flag()` 返回 `新近 / 补采`；`qbu_crawler/server/report.py:1133-1138,1213-1217,1251-1268,1340-1342` 生成 5 个 sheet，新增 `今日变化` | `test1 xlsx` 只有 4 个 sheet；`test2 xlsx` 为 `['评论明细','产品概览','今日变化','问题标签','趋势数据']`；`test2 xlsx[评论明细!B2:B5] = 补采` | PASS |
| `变化趋势` 中的“健康指数趋势”必须和顶层健康指数语义一致。`spec:451-456` | `qbu_crawler/server/report_common.py:54` tooltip 写成 `20%站点评分 + 25%样本评分 + 35%(1−差评率) + 20%(1−高风险占比)`；`qbu_crawler/server/report_common.py:497-533` 实际顶层实现是 `NPS-proxy health index with Bayesian shrinkage`；`qbu_crawler/server/report_analytics.py:1452-1458` 趋势“健康分”却是 `100 - own_negative_rate` | `test2 html:1613-1614` tooltip 仍展示旧加权公式；`test2 analytics:14121-14130` 月度趋势把 `2025-11` 写成 `health_index=0.0`，对应的是 `own_negative_rate=100.0`，而不是顶层贝叶斯健康指数 | FAIL |
| Phase 1 允许 mixed status；产品/竞品趋势不能因为主图未就绪就丢掉已就绪的 KPI/表格。`spec:481-493,503-510,678-681` | `qbu_crawler/server/report_analytics.py:1645-1668` `products` 维度在样本不足时仍返回 `kpis.status="ready"`、`table.status="ready"`；但 `qbu_crawler/server/report_templates/daily_report_v3.html.j2:294-337` 只要 `trend_block.status != "ready"` 就整块只渲染一条状态文案；`qbu_crawler/server/report_analytics.py:1734-1742` `competition` 维度直接整块 `_empty_trend_dimension("accumulating", ...)` | `test2 analytics:13494-13535` `month.products` 明明有 `kpis.items` 和 `table.rows`；`test2 html:2150-2162` 页面只剩“产品快照样本不足”；`test2 analytics:13007-13031` `month.competition` 全部 `accumulating` 且空表 | FAIL |
| artifact resolver 读取侧必须兼容原路径失效后的回退搜索。`spec:611-617,669` | `qbu_crawler/server/report_snapshot.py:76-140` 先取 `REPORT_DIR` / DB 同级 `reports/` / `stored.parent`，再按 `workflow-run-{id}-*.json` glob；`qbu_crawler/server/report_snapshot.py:157-190` `load_previous_report_context()` 经 `_resolve_artifact_path()` 取历史 analytics/snapshot | 当前审查包未提供 `workflow_runs` 行与“路径已失效”的复现场景，读取回退链无法直接演练 | PARTIAL |
| 新 run 写入的 artifact path 不应继续固化为单机绝对路径。`spec:624-628,649,669-670`; `devlog:83-85` | `qbu_crawler/server/report_snapshot.py:707` 只有 `snapshot_path` 经过 `_artifact_db_value()`；但 `qbu_crawler/server/report_snapshot.py:1370-1373` 返回的是原始 `excel_path/analytics_path/html_path`；`qbu_crawler/server/workflows.py:722-727,755-760` 又原样写回 `excel_path/analytics_path/pdf_path` | 当前包里没有 `workflow_runs` 行，无法直接看到 DB 中落库值；但代码路径已表明写入侧未完成统一治理 | FAIL |
| LLM 必须显式感知 `bootstrap`，违规措辞要 deterministic fallback。`spec:563-571,674`；`plan:329-348` | `qbu_crawler/server/report_llm.py:502-509` prompt 注入 `[report_semantics=bootstrap]` 与禁用词提示；`qbu_crawler/server/report_llm.py:680-683` 命中违规时回退 `_fallback_insights()`；但 `qbu_crawler/server/report_common.py:639-642` 与 `qbu_crawler/server/report_templates/email_full.html.j2:220-223` 仍保留“新增评论”兜底文案 | `test1 html:1407` 升级前仍出现“今日新增450条自有评论”；`test2 html:1729-1735` 升级后主路径已切到“监控起点”；兜底分支当前产物未触发 | PARTIAL |

# 3. 发现

## P1-1 健康指数/健康分已经分裂成三套公式

- 现象：
  - 同一个“健康指数/健康分”标签，当前系统同时存在三套互不相同的计算语义：tooltip 里的旧加权公式、顶层 KPI 的贝叶斯 NPS 代理公式、趋势页的 `100 - 差评率` 简化公式。
- 证据：
  - `qbu_crawler/server/report_common.py:52-55`：`"健康指数": "综合评分 = 20%站点评分 + 25%样本评分 + 35%(1−差评率) + 20%(1−高风险占比)，满分100"`
  - `qbu_crawler/server/report_common.py:497-533`：`"""NPS-proxy health index with Bayesian shrinkage for small samples."""`
  - `qbu_crawler/server/report_analytics.py:1452-1458`：`own_negative_rates = ...`，`health_scores = [round(100 - rate, 1) ...]`
  - `test2 html:1613-1614`：页面 tooltip 明确展示旧加权公式，同时卡片值为 `94.9`
  - `test2 analytics:14121-14130`：`2025-11` 的趋势行写成 `health_index = 0.0`、`own_negative_rate = 100.0`、`review_count = 5`
- 根因：
  - 事实：健康指标没有单一 source-of-truth；历史 tooltip 文案、顶层 KPI 计算、趋势计算分别走了三条路径。
  - 推测：Phase 1 引入贝叶斯健康指数时，只替换了顶层 KPI 计算，没有同步清理 tooltip 和趋势维度实现。
- 影响：
  - 用户在总览看到的 `94.9/100`，和趋势页看到的“健康分”不是同一含义。
  - 小样本桶位会被趋势页夸大波动。`test2 analytics:14127-14130` 的 `2025-11` 只有一个自有差评样本，却被渲染成 `0.0` 的极端值。
- 修复建议：
  - 先决定唯一健康指标定义。
  - 如果趋势页故意只展示 `100 - 差评率`，应立刻改名，不要继续叫 `健康分/健康指数`。
  - 如果要统一为贝叶斯健康指数，则趋势页要按桶位复用同一公式，tooltip 也同步改成真实公式。

## P1-2 趋势 mixed-state 契约只做了一半，HTML 把已就绪数据直接丢掉了

- 现象：
  - 后端已经能为 `products` 维度产出“主图 accumulating，但 KPI/表格 ready”的 mixed-state 数据；前端模板却按维度总状态一刀切，导致已就绪内容完全不渲染。
  - `competition` 维度的后端也仍然是整维度 `accumulating` / `ready`，没有按子组件分层。
- 证据：
  - `spec:481-493,503-510`：Phase 1 明确允许“同一维度内部部分组件 ready、部分组件 accumulating”，且 `competition` 不应“一刀切成同一状态”。
  - `qbu_crawler/server/report_analytics.py:1645-1668`：`products` 维度在 `ready_series is None` 时返回 `status="accumulating"`，但 `kpis.status="ready"`、`table.status="ready"`。
  - `qbu_crawler/server/report_templates/daily_report_v3.html.j2:294-337`：模板只有 `trend_block.status == "ready"` 才渲染 KPI/表格，否则只输出 `trend-status` 文案。
  - `test2 analytics:13494-13535`：`month.products` 已有 `kpis.items` 和 `table.rows`
  - `test2 html:2150-2162`：同一块页面只剩“产品快照样本不足，连续状态趋势仍在积累”
  - `qbu_crawler/server/report_analytics.py:1734-1742`：`competition` 维度只要 `shared_points == 0` 就整块 `_empty_trend_dimension("accumulating", ...)`
  - `test2 analytics:13007-13031`：`month.competition` 整块 `accumulating`，KPI/table 全空
- 根因：
  - 事实：后端 payload 已经支持组件级状态，但模板仍按维度级 `trend_block.status` 粗粒度分支。
  - 事实：`competition` builder 本身也还没有实现组件级 mixed-state。
- 影响：
  - Phase 1 承诺的“功能不砍”只在 JSON 层成立，HTML 实际阅读体验仍在砍信息。
  - 首日/低样本场景下，用户看不到“已有多少跟踪产品、已有多少快照点”这类已经可用的趋势审计信息。
- 修复建议：
  - 模板按 `kpis.status`、`primary_chart.status`、`table.status` 分开渲染，而不是只看 `trend_block.status`。
  - `competition` 维度改成组件级输出，至少让“样本说明 + 可用 KPI/基础表”可以共存。

## P1-3 `report_copy` 已出现事实性排序错误，但校验器抓不住

- 现象：
  - 本轮 `test2` 的 `report_copy.executive_bullets` 中，至少有两处“数字本身对得上，但结论关系错了”的 LLM 漂移。
- 证据：
  - `qbu_crawler/server/report_llm.py:623-637`：当前只校验 `improvement_priorities[].evidence_count` 上限，没有校验 Hero/summary/bullets 的排序、比较和归因。
  - `test2 analytics:3825-3828`：
    - Bullet 1：`".5 HP Dual Grind Grinder (#8)以29.6分风险值领跑"`
    - Bullet 2：`"17条结构设计缺陷 ... 与12条质量稳定性问题 ... 并列首位"`
  - `test2 analytics:4874-4890`：`Walton's Quick Patty Maker` 的 `risk_score = 35.1`
  - `test2 analytics:4915-4923`：`.75 HP Grinder (#12)` 的 `risk_score = 33.3`
  - `test2 analytics:4954-4962`：`.5 HP Dual Grind Grinder (#8)` 的 `risk_score = 29.6`
  - `test2 analytics:3962-3966`：`结构设计` `review_count = 17`
  - `test2 analytics:4087-4091`：`质量稳定性` `review_count = 12`
- 根因：
  - 事实：当前 post-validation 只做字段类型和 `evidence_count` 截断，不做排序与比较关系校验。
  - 推测：LLM 在“解释性句子”里把“存在的数字”拼对了，但把“谁第一 / 是否并列”这类关系词说错了。
- 影响：
  - 用户会被 Bullet 1 错误引导，把 `.5 HP Dual Grind Grinder (#8)` 当成最高风险 SKU；实际风险分最高的是 `Walton's Quick Patty Maker`。
  - Bullet 2 会夸大 `质量稳定性` 的优先级，把 `17` 和 `12` 说成“并列首位”。
- 修复建议：
  - 对 `report_copy` 增加 deterministic 对账层，至少校验：
    - Top 风险产品是否真的是最大 `risk_score`
    - “并列/领先/落后/最高/最低”这类关系词是否和排序一致
  - 更稳妥的做法是把 Top-N 排序句改为模板化生成，不交给 LLM自由发挥。

## P2-1 artifact 路径治理只补了读取侧，写入侧还在继续扩散绝对路径

- 现象：
  - `snapshot_path` 已经过 `_artifact_db_value()` 归一化，但 `analytics_path` / `excel_path` / `html_path` 返回值和 workflow 落库仍是原始绝对路径。
- 证据：
  - `spec:624-628,649,669-670`：新 run 的 `snapshot_path` / `analytics_path` / `html_path` / `excel_path` / `pdf_path` 都应优先持久化为相对路径。
  - `qbu_crawler/server/report_snapshot.py:143-154`：已经有 `_artifact_db_value()`
  - `qbu_crawler/server/report_snapshot.py:707`：`snapshot_path=_artifact_db_value(snapshot_path)`
  - `qbu_crawler/server/report_snapshot.py:1370-1373`：`"excel_path": excel_path, "analytics_path": analytics_path, "html_path": html_path`
  - `qbu_crawler/server/workflows.py:722-727,755-760`：`models.update_workflow_run(... excel_path=excel_path, analytics_path=analytics_path, pdf_path=pdf_path ...)`
- 根因：
  - 事实：路径可迁移治理目前只打到了 snapshot 写入路径，没有贯穿 full report 产物返回值与 workflow 持久化边界。
- 影响：
  - 读取侧 resolver 现在能兜住一部分问题，但新 run 仍在把单机绝对路径继续写回系统状态。
  - 这会让“路径可迁移”长期依赖 fallback 搜索，而不是从源头杜绝扩散。
- 修复建议：
  - 在 full report 返回前或 `workflows.py` 落库前，对全部 artifact path 统一跑 `_artifact_db_value()`。
  - 保持 resolver 兼容旧绝对路径，但新写入值不再继续固化单机目录。
- 备注：
  - 当前审查包里没有 `workflow_runs` 行，产物侧只能给出 `UNVERIFIED`；这是代码层直接观察到的问题。

## P2-2 bootstrap 兜底文案仍留有“增量措辞”逃逸口

- 现象：
  - 主路径已经修复，但 fallback/空 bullets 分支仍可能在 `bootstrap` 场景输出“新增评论”。
- 证据：
  - `qbu_crawler/server/report_common.py:639-642`：fallback bullet 默认文案是 `当前纳入分析产品 ... 新增评论 ...`
  - `qbu_crawler/server/report_templates/email_full.html.j2:220-223`：邮件无 bullets 时也会回落到 `新增评论 {{ _summary.get("ingested_review_count", 0) }} 条`
  - `qbu_crawler/server/report_llm.py:290-297`：bootstrap 违规词检查只拦 `今日新增 / 今日暴增 / 较昨日 / 较上期 / 环比`，没有覆盖更宽泛的 `新增评论`
  - `test1 html:1407`：升级前真实产物确实曾输出 `今日新增450条自有评论`
  - `test2 html:1729-1735`：升级后主路径已切到 `监控起点`
- 根因：
  - 事实：主路径 prompt/fallback 已按 `bootstrap` 分流，但 fallback bullet/email 兜底文案还沿用旧增量说法。
- 影响：
  - 在 `LLM unavailable`、`executive_bullets` 为空、或未来出现极稀疏 clean run 时，bootstrap 仍可能重新冒出增量话术。
- 修复建议：
  - 把 bootstrap 全部兜底文案统一成 `本次入库 / 监控起点 / 当前截面`。
  - bootstrap 违规词检测至少补上 `新增评论`、`新增 X 条评论` 这类通用模式。

# 4. LLM 可靠性专章

## 4.1 prompt 结构

- `qbu_crawler/server/report_llm.py:502-509` 已显式注入 `[report_semantics=bootstrap]`，并明确要求“不要写‘今日新增’‘较昨日’‘较上期’‘环比’等增量措辞”。
- `qbu_crawler/server/report_llm.py:513-520` 在 `incremental` 下改为注入 `本次入库评论 / 近30天业务新增 / 历史补采`。
- `qbu_crawler/server/report_llm.py:522-529` 低样本提示改看 `window.reviews_count`，不再回退到累计口径。
- `qbu_crawler/server/report_llm.py:680-683` 已具备 bootstrap 违规后回退 `_fallback_insights()` 的主逻辑。

判断：

- 主路径比升级前明显收敛，`test1 html:1407` 的 bootstrap 违规句在 `test2 html:1729-1735` 已消失。
- 但 fallback 支路仍不彻底，详见 `P2-2`。

## 4.2 bootstrap 违禁词 fallback

- 正向证据：
  - `qbu_crawler/server/report_llm.py:280-298` 有 bootstrap 违规检测。
  - `qbu_crawler/server/report_llm.py:681-683` 违规后直接 `return _fallback_insights(analytics)`。
- 边界缺口：
  - 检测范围只覆盖 `hero_headline` / `executive_summary` / `executive_bullets`，未覆盖 `competitive_insight` 等其他字段。
  - 检测模式没有覆盖更宽泛的 `新增评论`。

结论：

- 当前可判定为“主路径可用，兜底不够严”，所以是 `PARTIAL`，不是完全闭环。

## 4.3 `report_copy.*` 数字对账表

| `report_copy` 字段 | 产物片段 | analytics 来源 | 对账 |
| --- | --- | --- | --- |
| `hero_headline` | `test2 analytics:3831` `自有5款产品健康指数达94.9` | `test2 analytics:3788,3801` `health_index=94.9`、`own_product_count=5` | PASS |
| `executive_summary` | `test2 analytics:3830` `基于593条全量评论基线扫描 ... 1% / 4% / 7%` | `test2 analytics:3791` `ingested_review_rows=593`；`test2 analytics:4885,4918,4957` 三个 SKU 的 `negative_rate` 分别约为 `1% / 4% / 7%` | PASS |
| `executive_bullets[0]` 数字 | `test2 analytics:3826` `29.6分 ... 7% ... 质量稳定性(4条)、售后履约(3条)` | `test2 analytics:4956-4973` `risk_score=29.6`、`negative_rate=0.0659`、`quality_stability=4`、`service_fulfillment=3` | PASS |
| `executive_bullets[0]` 关系词 | `test2 analytics:3826` `29.6分风险值领跑` | `test2 analytics:4890,4923,4962` 三个风险分是 `35.1 > 33.3 > 29.6` | FAIL |
| `executive_bullets[1]` 数字 | `test2 analytics:3827` `17条结构设计缺陷`、`12条质量稳定性问题` | `test2 analytics:3962-3966` `结构设计=17`；`test2 analytics:4087-4091` `质量稳定性=12` | PASS |
| `executive_bullets[1]` 关系词 | `test2 analytics:3827` `并列首位` | `test2 analytics:3966,4091` 是 `17` 与 `12`，不是并列 | FAIL |
| `executive_bullets[2]` | `test2 analytics:3828` `11条售后与履约投诉` | `test2 analytics:4195-4199` `售后与履约 review_count=11` | PASS |

结论：

- 当前 `report_copy` 的“数字抽取”总体可回账。
- 当前 `report_copy` 的“排序/比较/归因”仍然不可靠，且代码里没有足够的 deterministic 校验器兜底。

# 5. 两轮产物 diff

| 字段级差异 | test1（升级前，14:40） | test2（升级后，17:12） | 观察 |
| --- | --- | --- | --- |
| 顶层语义字段 | `test1 analytics` 无 `report_semantics` / `is_bootstrap` / `change_digest` / `trend_digest` | `test2 analytics:577-681,2801,3860,13004-13020` 全部出现 | Phase 1 顶层契约已落地 |
| HTML `今日变化` | `test1 html:1457-1464` 只有 `TAB 2: 今日变化 (Changes)` 注释，没有正文 | `test2 html:1724-1760` 有“监控起点”、摘要卡、warning | 空壳 tab 已被填实 |
| HTML `变化趋势` | `test1` 无该入口 | `test2 html:1582-1583,1828-1849` 有顶层入口、`周/月/年`、四个维度切换 | 入口与默认选中态已落地 |
| bootstrap 文案 | `test1 html:1407` 仍写 `今日新增450条自有评论` | `test2 html:1729-1735` 改成 `监控起点`、`本次入库 593 / 新近 4 / 补采 589` | 主路径语义修复明显 |
| Excel sheet 数 | `test1 xlsx` 4 个 sheet：`评论明细 / 产品概览 / 问题标签 / 趋势数据` | `test2 xlsx` 5 个 sheet：新增 `今日变化` | Excel 结构对齐 spec |
| `评论明细` 的“本次新增” | `test1 xlsx[评论明细!B2:B5] = 是 / 是 / 是 / 是` | `test2 xlsx[评论明细!B2:B5] = 补采 / 补采 / 补采 / 补采` | `bootstrap = 新近 / 补采` 契约已生效 |
| `产品概览` 竞品“采集评论数” | `test1 xlsx[产品概览]` 中两条竞品行分别是 `0 / 0` | `test2 xlsx[产品概览]` 同两条竞品行变成 `56 / 57` | “采集评论数按真实 review 聚合”已体现到产物 |
| 数据量 | `test1 analytics:2320-2332` `product_count=7`、`ingested_review_rows=563` | `test2 analytics:3787-3805` `product_count=8`、`ingested_review_rows=593` | 事实：17:12 的样本比 14:40 多 1 个竞品 SKU、30 条评论；原因是数据漂移还是抓取范围变化，`UNVERIFIED` |
| 新增产品 | `test1 snapshot` 无 `2834842` | `test2 snapshot` 新增 `('2834842', "Cabela's Heavy-Duty 20-lb. Meat Mixer", 'competitor')` | 事实存在新增竞品 SKU；这会影响 test1/test2 的绝对值对比 |

# 6. 结论

结论：不建议把当前实现视为“Phase 1 已完整达标并可直接上线”。`今日变化`、`变化趋势` 入口、Excel 5-sheet、bootstrap 主路径话术、warning 契约这些核心止血项已经基本落地，但仍有 3 个会直接影响用户判断的 P1 问题没有收口：

- 健康指数语义分裂：tooltip、顶层 KPI、趋势“健康分”不是同一个指标。
- 趋势 mixed-state 未在 HTML 闭环：已有 KPI/表格被模板直接吞掉。
- `report_copy` 已出现事实性排序错误：最高风险 SKU 和“并列首位”都说错了。

必修清单：

- 统一“健康指数/健康分”的唯一公式与命名，并同步修正 tooltip 与趋势计算。
- 按组件级 `status` 渲染趋势页，至少把已就绪 KPI/表格放出来。
- 给 `report_copy` 加 deterministic 对账，尤其是 Top 风险 SKU、排序、并列/领先/落后等关系词。

建议修清单：

- 把 `analytics_path` / `excel_path` / `html_path` / `pdf_path` 的写入也统一改成相对 artifact path。
- 清理 bootstrap fallback 中残留的“新增评论”话术，并扩大 LLM 违规词检测范围。
