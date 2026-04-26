# 生产测试 5 — 报告体系全面审计报告

- **审计日期**：2026-04-26（初稿）/ 2026-04-27（合入 Codex 交叉验证补充）
- **审计对象目录**：`C:\Users\leo\Desktop\生产测试\报告\测试5\`
- **生产环境版本**：`qbu-crawler 0.3.25`（`workflow_runs.service_version`）
- **被审 run**：`run_id=1`，`workflow_type=daily`，`logical_date=2026-04-26`，`report_mode=full`，`report_phase=full_sent`
- **产物清单**：
  - `data/products.db`（1 011 712 B）
  - `reports/workflow-run-1-snapshot-2026-04-26.json`（1 874 502 B）
  - `reports/workflow-run-1-analytics-2026-04-26.json`（1 985 727 B）
  - `reports/workflow-run-1-full-report.html`（449 693 B）
  - `reports/workflow-run-1-full-report.xlsx`（4 521 300 B）
  - `email.png`（邮件展示截图，504 897 B）

> 审计原则：从业务价值、数据逻辑、用户可读性、专业分析合理性四层切入；指标计算逻辑全部反查 `qbu_crawler/server/` 源码并标注 `文件:行号`；所有结论附数据证据。
>
> **2026-04-27 增量合入说明**：本次合入 Codex 独立审查（`2026-04-26-production-test5-full-report-audit-codex.md`）的交叉验证结果。已逐条 SQLite/openpyxl 实测验证 Codex 提出的可证实事实；其中**「产品概览差评率分母不统一」「Excel 失效模式列 100% 空」「outbox 全 deadletter / HTTP 401」「问题标签 sheet 含未规范化 durability/neutral」「44.9% 评论是相对时间表达」「316/561 评论 headline 为空」「review_analysis 已有 (review_id, prompt_version) UNIQUE 约束」**等关键事实已得到 SQL/openpyxl 直接验证，并纠正了初稿的若干误判（详见各章节合并标记 `【交叉验证补充 / 修正】`）。
>
> **2026-04-27 二次互验合入**：在 Codex 阅读本审计报告后给出反向校正与本次第二轮互验的基础上，进一步合入 7 项新发现（N1-N7，标记 `【二次互验】`）：包含 trend status 实际为 4 ready / 8 accumulating + 3 panel 外内不一致（**纠正初稿"全部 accumulating"的过度归纳**）、`top_actions` 是迁移死字段（**纠正初稿"无建议"的判断**）、failure_mode "无类"污染 64.9%（**严重度从 P2 升 P1**）、products 维度首日 1 次 scrape 也判 ready 的逻辑 bug、ready 阈值无统计意义、impact_category × failure_mode × label_code 三字段语义层次未定义、improvement_priorities.action 双职责 schema 是 UI 截断的真根因，以及"AI 互验元洞察"作为 §10.2.2 新章节。
>
> **2026-04-27 第三轮用户视角收口（§11，本文最终决策章节）**：在用户指出"前章建议把内部运维信号、schema 债务、采集质量等无关内容混入用户报告"的核心反馈后，新增 §11 作为本审计的**最终决策依据**。原则：报告产物分两个频道——**用户报告**（HTML/Excel/邮件）只放用户能立即理解并采取行动的信息；**内部运维告警**独立通道接收 scrape_quality / 通知失败 / schema 债务等。§11 包含：（a）频道分离原则；（b）HTML/Excel 元素逐项审视清单（每个元素经"3 秒能懂 + 决策有用"双测）；（c）用户视角终稿结构（HTML 5 章节 / Excel 4 sheets）；（d）内部运维频道独立邮件 mock；（e）对前章 H1/H8/H13/M11/M15 等建议的收口决策（撤回 / 移内部 / 保留）。**§11 优先级高于 §3.4 / §4.5 / §8 中的 UI 类建议**；前章已加前向引用提示。
>
> **2026-04-27 第四轮产物边界澄清（§11.9）**：在用户指出第三轮 §11 把"邮件正文 HTML / 附件 HTML 报告 / Excel 附件"三类产物混为一谈后，新增 §11.9 作为最终边界澄清。经源码核对（`qbu_crawler/server/report_templates/`），确认产品系统已有 4 类独立模板 + 1 类内部告警模板（`email_data_quality.html.j2` 已存在）。§11.9 分别给出：（a）邮件正文 HTML 终稿（30-60 秒决策，640px 受限版面，针对 `email_full.html.j2`）；（b）附件 HTML 报告终稿（5-15 分钟深度阅读，无约束，针对 `daily_report_v3.html.j2`，比邮件正文丰富，**保留全 8 issue cards / 完整 example_reviews / 完整 5 行动建议 + 证据回链**）；（c）Excel 终稿（数据下钻，4 sheets）；（d）内部运维通道（**复用现有 `email_data_quality.html.j2`，无需新建**，仅补强触发条件）。**§11.9 优先级高于 §11.3-§11.4**——后者的 mock 密度对应邮件正文，不适用于附件 HTML 报告。
>
> **2026-04-27 第五轮：撤回分角色 tabs / 分角色 Excel（§11.10）**：用户明确反对原 §9.5"HTML 顶部分管理者/产品改良/设计/数据 4 个 tab" 与 §8.3 L9"角色化 Excel 导出 3 份"。理由：（1）维护成本（4 套 layout / 3 套生成链路）；（2）用户认知摩擦（打开报告先选身份）；（3）"标签即偏见"——硬角色分类无视实际跨角色协作场景；（4）Excel 本质是分析师工具，角色分类无意义。**撤回 §9.5 / §8.3 L9，单一报告 + 信息按"决策深度"分层**——管理者自然停在 Hero/KPI，产品改良/设计自然停在 issue cards，分析师自然下钻到 Excel。所有角色用同一份产物，无需切 tab、无需选附件版本。详见 §11.10。
>
> **2026-04-27 第六轮：保留两项嵌入产物特征**：（1）**附件 HTML 全景数据嵌入保留**——撤回原 §11.9.3 / §11.9.6"全景数据 → 链接 Excel"决策；附件 HTML 应具备**独立下钻能力**，不依赖 Excel；561 条评论行嵌入保留，建议附客户端筛选（归属/评分/有图/新近/标签）。（2）**Excel 评论图片 drawing 嵌入保留**——撤回 DQ-12 / L7"图片单元格改 hyperlink"建议；视觉证据原样保留；机器解析需求由内部消费方自行处理（如改读 `reviews.images` JSON 字段），不影响用户 Excel 形态。其他第五轮决策不变。
>
> **2026-04-27 第七轮：新增 §11.11 — 附件 HTML "今日变化" + "变化趋势" 两区块字段级用户视角审视**：补充 §11.9.3 的总体改造清单，深入到指标语义/对比合理性/用户价值分析，给出 bootstrap 期与数据成熟期的不同呈现方案，含 9 项 PR 拆分实施清单（7-11 天工作量）。核心改动方向：（a）bootstrap 期完全隐藏两区块，单卡替代；（b）"今日变化"从 4 块平铺重排为 🔥 立即关注 / 📈 趋势变化 / 💡 反向利用 三层金字塔，新增 `own_new_negative_reviews` 和 `competitor_new_negative_reviews` 两个 review_signals（当前优先级反了）；（c）"变化趋势"从 4 维度 × 3 窗口 = 12 panel 收敛为 1 主图（健康度自有 vs 竞品双线）+ 3 折叠下钻（Top 3 问题趋势/产品评分/竞品对标），主图带"对比基准 + 偏差%"，时间口径显式切换 `date_published` vs `scraped_at`；（d）样本阈值升级到 ≥30 + ≥7 时间点；（e）`estimated_dates`/`backfill_dominant`/"本次入库"等工程信号移内部运维频道。

---

## 1. 总体结论

### 1.1 整体评价

报告体系是**一个野心勃勃且分析深度可圈可点的"评论智能监控"产品**，已具备 LLM 驱动的洞察生成、贝叶斯小样本修正、多维度（情绪/问题/产品/竞品 × 7d/30d/365d）趋势聚合、双视角（窗口 vs 累计）、四态报告模式（full/change/quiet/bootstrap）等高级能力。但生产首次跑通的产物暴露出**链路耦合不严、口径不统一、数据质量自检缺位、bootstrap 期信息密度低**四类系统性问题。

它能在演示场景下输出令人印象深刻的中文分析，但若每天交到产品改良 / 设计 / 管理三类读者手里，**当前更接近"AI 撰写的可读分析稿"，而不是"可信、可比、可决策的运营仪表盘"**。

### 1.2 核心优点

1. **指标体系丰富**：KPI 卡 7 张 + 风险分 + 差距分 + 健康指数 + 标签聚类覆盖较全。具备小样本贝叶斯先验收缩（防止 0 评论时返 100 分），思想正确（`report_common.py:521-561`）。
2. **LLM 洞察质量高**：`improvement_priorities`（5 条带 evidence_count 排序）/ `top_negative_clusters.deep_analysis.root_causes`（带置信度）等字段产出了高质量、可读性强的产品改良建议。
3. **数据持久化分层清晰**：`workflow_runs` + `snapshot_path` + `analytics_path` + `excel_path` 形成可重放的产物链；带 `snapshot_hash` 可做幂等回放。
4. **产物互补**：HTML（可读）+ Excel（可下钻）+ JSON（机器可读）+ DB（可 SQL）四件套配齐。
5. **双视角设计**（`perspective=dual`）：累计 vs 当日窗口区分到位，理论上能解决"基线后失明"问题。
6. **Schema 规范化得分较高**：`reviews / review_analysis / review_issue_labels` 三层是漂亮的 1:1:N 模型；`workflow_runs` 串联 outputs 思路清晰；`taxonomy_version` / `prompt_version` / `service_version` 三个版本字段已埋点。

### 1.3 核心问题（按严重度由高到低）

| 等级 | 问题摘要 |
|------|---------|
| **P0** | **数据质量监测漏检关键缺口**：SKU `1193465`（`.5 HP Dual Grind Grinder #8`）站点报告 91 条评论、实际入库 0 条；`scrape_quality` 全部 0 missing，**未告警**——`scrape_quality.py` 只检测 products 表字段缺失，**未检测"site_reported vs actual ingested 评论数偏差"** |
| **P0** | **多种"差评率"口径并存且未在 UI 上区分**：`own_negative_review_rate(2.4%)` = 自有 ≤2 星比；`all_sample_negative_rate(11.6%)` = 全样本 ≤2 星比；`low_rating_review_rows(87)` = ≤3 星（含中评！）；`sentiment='negative'`(71) = LLM 判负——四种定义混用，readers 极易误读 |
| **P0** | **本次入库 561 条 ≠ 今日新增 561 条**：99% 是历史补采，仅 3 条 `date_published` 在近 30 天内；首页"本次入库 561"会让管理者误读为"昨夜暴涨"。报告内有"补采 558"小字提示但权重不够 |
| **P1** | **bootstrap 期 HTML 充斥占位区**：近 7 天 / 30 天 / 12 个月 4 个维度的图表（共 12 个区块）全是 `status=accumulating` 空图，但仍占用版面 |
| **P1** | **`duration_display "约 8 年 1 个月"` 是误导**：表面读为"该问题持续了 8 年"，实际只是评论池里最早—最晚的 `date_published` 跨度，问题可能早已修复 |
| **P1【二次互验修正】** | **~~`top_actions = []` 导致"无建议"~~**：实测 `analytics.top_actions=[]` 但 `report_copy.improvement_priorities` 有 5 条满载，HTML 实际渲染了 3 个 action-title 来自后者。**真正问题是"建议来源单一依赖 LLM 无规则降级 + action 字段被截断"**——`top_actions[]` 是迁移留下的死字段，schema 中保留但永远空；一旦 LLM 失败/超时/输出空，HTML 该区块就空白，无降级路径 |
| **P1** | KPI `delta-flat`：bootstrap 期没有同比信号，整个"报告口径"区段 delta 列对管理者价值低 |
| **P1** | **风险分仅评 own，竞品劣势未量化**：竞品差评率 44.6% / 43.9% 在 Excel 列里赤裸裸躺着，但 HTML 没有任何"竞品风险产品"卡片或反向利用建议 |
| **P1** | **risk_score 分母 = `max(site_review_count, ingested)`**：当 ingested=0 但 site>0 时 neg_rate=0，**风险产品反而隐身**（SKU 1193465 即此情况） |
| **P1【二次互验升级】** | **`failure_mode` 字段对产品改良价值约等于零**：实测 258 个唯一值/561 条记录；"无类"占位词聚合 = **364/561 = 64.9%**（"无"=220、"无失效"=18、"无显著失效模式"=17、"无失效问题"=15、"无典型失效模式"=15、"无故障"=9 等），其中 positive sentiment 下 282/282=100% 是"无"变体（LLM 对正面评论强填占位词污染字段语义）；剩余 35.1% 是 258 个分裂自由文本短语（如"齿轮薄弱卡顿"vs"齿轮磨损脱落金属屑"vs"齿轮过载停转"本质同类却被独立计数）。**真正可聚合的失效类目 = 0 条**（任何字符串都凑不出 ≥2 条相同）。严重度从 P2 升 P1 |
| **P2** | **`review_issue_labels source` 中 `rule=2 / llm=949`**：声称 hybrid 实际几乎纯 LLM；规则层未生效但仍标 hybrid 易误导 |
| **P2** | **MAX_REVIEWS=200 致 `.75 HP` 253→109 截断**：覆盖率仅 43%，影响该产品差评率代表性，但 UI 未在产品行级对覆盖率打 warning |
| **P2** | **executive_summary / hero_headline 100% LLM 生成**：可读性强但与下方数字偶有微差，无法回溯，遇到模型幻觉时难以校验；hero `"健康指数 96.2，但缺陷正严重侵蚀核心体验"` 措辞自洽性差 |
| **P2** | **Excel 评论明细"影响类别"列与"标签"列内容雷同**：实测 561/561 完全一致；同时 **"失效模式"列 561 行 100% 空**（DB `review_analysis.failure_mode` / `impact_category` 各 561 条非空），根因是 `query_cumulative_data()` 未 select 这两个字段 — Excel 完全浪费已有 LLM 分析资产 |
| **P2** | **Excel "问题标签" sheet 997 行（去表头）vs DB `review_issue_labels` 951 行**：偏差 46 行；含未规范化值 `durability`(8 行) + 极性 `neutral`(1 行)，证明 Excel 直读 LLM 原始 `review_analysis.labels` 而非消费同步后的规范化表 |
| **P0【交叉验证补充】** | **产品概览"差评率"列分母不统一**：风险产品（如 .75HP）用**站点评论数**分母（9/253=3.56%），非风险/竞品用**采集评论数**分母（如竞品 25/56=44.6%）。**实测**：.75HP 若用采集分母会得 9/109=8.26%，与现展示差 2.3 倍——同列双口径会把风险产品差评率**人为压低**、竞品差评率**人为放大**，直接影响排序与决策判断 |
| **P0【交叉验证补充】** | **`METRIC_TOOLTIPS["风险分"]` 旧描述与实际算法严重不一致**：tooltip 仍是"低分评论×2 + 含图评论×1 + 各标签严重度累加；仅计 ≤3 星评论"；实际 `_risk_products()` 已为 5 因子加权（35% neg_rate + 25% severity_avg + 15% evidence_rate + 15% recency + 10% volume_sig），且差评阈值用 `NEGATIVE_THRESHOLD`(≤2 星)。文档与代码语义债务 |
| **P1【交叉验证补充】** | **运维通知链路全失败但 workflow 状态显示成功**：`notification_outbox` 3 条全 `status=deadletter` / `last_http_status=401` / `last_error="bridge returned HTTP 401"`，但 `workflow_runs.status=completed`、`report_phase=full_sent` — **状态机分裂**，业务读者会以为报告已送达 |
| **P1【交叉验证补充】** | **HTML 总览"建议行动"标题被截断成半句话**：如 `"针对 Walton's #22 Meat Grinder、Walton's General Duty Meat Lug 与 Quick Patty Maker 反馈的肉"` 截于 80 字处。详细问题卡有完整建议，但总览入口直接损失业务语义 |
| **P1【交叉验证补充】** | **`reviews.date_published_parsed` 解析 anchor 不一致**：`models.py::_parse_date_published()` 用**当前日期**作 anchor，`_backfill_date_published_parsed()` 用 `scraped_at` 作 anchor — 同一相对时间字符串走两条路径会落入不同月/年窗口。本次 **252/561 = 44.9%** 评论为相对时间表达，影响 `recently_published_count` 与所有趋势聚合 |
| **P1【交叉验证补充】** | **HTML 趋势模板 `daily_report_v3.html.j2` 用 `row.values()` 输出表格**：依赖 dict 插入顺序而非按 columns key 取值；上游 JSON 字段顺序变化即列值错位，潜在隐性 bug |
| **P1【交叉验证补充】** | **`trend_digest` `ready` 状态嵌套矛盾**：月视图 `sentiment` 内部 KPI `status=ready` 但样本仅 3 条；产品维度外层 `accumulating`、内部 `ready`，模板和读者都难以判断应该展示还是降级 |
| **P2【交叉验证补充】** | **Excel 评论明细"照片"列 561 行单元格全空，但工作簿实际嵌入 82 张 drawing 图片**：机器解析会误判"无图"，影响转发、引用与二次处理 |
| **P2【交叉验证补充】** | **316/561 = 56.3% 评论 headline 为空**：评论明细"标题(原文)"列大量空值，按标题维度分析价值低 |

### 1.4 总体优化方向

1. **优先补齐"数据真实性自检"**：reviews 表实际入库数 vs `products.review_count` 偏差 ≥X% 必须独立告警。
2. **统一并显式声明三类"差评"口径**：rating-based、sentiment-based、severity-based 各取一个，写进 `metric_semantics`。
3. **bootstrap 期专用版面**：折叠所有同比卡 / 趋势空图，集中展示"截面诊断 + 数据质量 + LLM 洞察"。
4. **强化"今日 vs 累计"视觉差异**：把 `本次入库`、`新近 N`、`补采 N` 从二级行变为同等 hero 数字。
5. **把"竞品劣势"视作改良抓手**：增加竞品风险产品卡 + 反向利用建议。
6. **保留 LLM copy 单次生成（成本考虑），但加重试与数字断言后置校验**。
7. **【交叉验证补充】统一报告产物的"分母口径"和"tooltip 与算法同步契约"**：每个指标输出 `numerator / denominator / window / source / confidence` 五元组，并加 CI 测试拦截 tooltip-代码漂移。
8. **【交叉验证补充】把通知链路状态纳入 workflow 质量摘要**：outbox deadletter 时 `report_phase` 必须降级为 `full_sent_local`，邮件/钉钉真正送达才升级为 `full_sent_remote`。

---

## 2. 数据库结构分析

### 2.1 当前结构概述（10 张实表，去 `sqlite_sequence`）

```
products(id PK, url, site, name, sku, price, stock_status,
         review_count, rating, ownership, scraped_at)
  └─ product_snapshots(id PK, product_id→FK, price, stock_status,
                        review_count, rating, scraped_at)         # 历史快照
  └─ reviews(id PK, product_id→FK, author, headline, body, body_hash,
             rating, date_published, date_published_parsed,
             images, scraped_at, headline_cn, body_cn,
             translate_status, translate_retries)
        ├─ review_analysis(id PK, review_id→FK, sentiment,
        │                   sentiment_score, labels(JSON),
        │                   features(JSON), insight_cn, insight_en,
        │                   llm_model, prompt_version, token_usage,
        │                   analyzed_at, impact_category, failure_mode)
        └─ review_issue_labels(id PK, review_id→FK, label_code,
                                label_polarity, severity, confidence,
                                source, taxonomy_version, ...)

workflow_runs(id PK, workflow_type, status, report_phase, logical_date,
              trigger_key, data_since, data_until, snapshot_at,
              snapshot_path, snapshot_hash, excel_path, analytics_path,
              pdf_path, requested_by, service_version, created_at,
              updated_at, started_at, finished_at, error,
              report_mode, scrape_quality(JSON))
  └─ workflow_run_tasks(id PK, run_id→FK, task_id→tasks.id,
                         task_type, site, ownership)

tasks(id PK TEXT, type, status, params(JSON), progress(JSON),
      result(JSON), error, worker_token, system_error_code,
      started_at, finished_at, reply_to, notified_at, ...)

notification_outbox(id PK, kind, channel, target, payload,
                     dedupe_key, payload_hash, status, claimed_at,
                     claim_token, lease_until, bridge_request_id,
                     last_http_status, last_exit_code, last_error,
                     attempts, delivered_at, created_at, updated_at)
```

实测行数（生产测试 5）：

| 表 | 行数 |
|----|------|
| products | 8 |
| product_snapshots | 8 |
| reviews | 561 |
| review_analysis | 561 |
| review_issue_labels | 951 |
| workflow_runs | 1 |
| workflow_run_tasks | 3 |
| tasks | 3 |
| notification_outbox | 3 |

### 2.2 表 ↔ 报告指标映射

| 报告指标 | 主源表 | 辅源 / 备注 |
|---------|--------|------------|
| `product_count / own_/competitor_product_count` | `products` | — |
| `ingested_review_rows / negative_review_rows / image_review_rows` | `reviews` | rating, images |
| `sample_avg_rating / own_avg_rating` | `reviews.rating` | — |
| `recently_published_count` | `reviews.date_published_parsed` | last 30 days |
| `coverage_rate` | `reviews COUNT` ÷ `SUM(products.review_count)` | — |
| `sentiment 分布 / impact_category / failure_mode / insight` | `review_analysis` | — |
| `label 聚类 / issue_cards / gap_analysis` | `review_issue_labels` | `review_analysis.labels(JSON)` 冗余 |
| `change_digest.product_changes`（价格/库存/评分） | `product_snapshots` 跨日 diff | — |
| `trend_digest`（sentiment/issues/products/competition） | `reviews.date_published_parsed` + `product_snapshots` | — |
| `scrape_quality` | `products`（rating/stock_status/review_count）缺失率 | **遗漏 reviews 入库量** |

### 2.3 存在的问题

1. **【高】`review_analysis.labels(JSON)` 与 `review_issue_labels` 同时存在**——前者是 JSON blob 冗余冷数据，后者是规范化热数据。聚合时几乎都走 `review_issue_labels`，JSON 列除了在 Excel/snapshot 直接 dump 外没有运算用途，徒增 schema 维护成本和不一致风险。
2. **【高】`reviews.date_published` 保留原始字符串**（`"a year ago"`、`"01/02/2023"`、`"2 years ago"`），与 `date_published_parsed` 共存。Excel 评论明细里"评论时间"列展示的是 parsed 后的日期没问题，但 `change_digest.review_signals` 里仍输出 `date_published: "a year ago"` 字段，对人类阅读不友好。证据：`reviews.date_published MIN/MAX = ('01/01/2024', 'a year ago')`。

   **【二次互验升级 DS-2 严重度】`failure_mode` 字段对聚合分析无可用性**：实测 258 个唯一值 / 561 条记录；"无类"占位词聚合 = 364/561 = 64.9%（positive sentiment 100% 被强填"无"变体）；剩余 35.1% 是分裂的自由文本（`齿轮薄弱卡顿` / `齿轮磨损脱落金属屑` / `齿轮过载停转` 同类问题被独立计数）。**任何 enum 值都凑不出 ≥2 条相同**——产品改良工程师无法做"齿轮问题影响 N 个 SKU"这类基础聚合，唯一可做的是手工 grep。从 P2 升 P1。
3. **【已修正 / 交叉验证】~~`review_analysis.review_id` 缺少 UNIQUE 约束~~** — **初稿误判**。实测 `sqlite_master` 中存在 `sqlite_autoindex_review_analysis_1`（对应 `(review_id, prompt_version)` UNIQUE）以及 `sqlite_autoindex_review_issue_labels_1`（对应 `(review_id, label_code, label_polarity)` UNIQUE），`reviews` 也有 `idx_reviews_dedup` UNIQUE `(product_id, author, headline, body_hash)`。**真正的问题不是缺 UNIQUE**，而是：
   - **`review_id + prompt_version` 复合 UNIQUE 允许同 review 多 prompt 版本并存**——schema 有意为之，但 Excel/HTML 全部按 review_id 1:1 消费，未声明取最新 prompt_version 的策略，未来 `prompt_version=v2 → v3` 升级期会出现 562/561 双计数风险。
   - schema 文档未明示这些 UNIQUE 约束的语义。
4. **【中】`failure_mode` 是自由文本中文短语**：220/561 是"其他"，剩余分布极散（"开关失效模式"、"无电流失效模式"…），无法做归类聚合，应改为 enum 或与 `review_issue_labels.label_code` 合并。
5. **【中】`workflow_runs.scrape_quality` 是 TEXT JSON**：不利于 SQL 直接过滤 / 趋势对比；至少应抽出 `missing_review_count_ratio` 等核心字段为独立列。
6. **【中】`tasks.reply_to=''`**（空字符串非 NULL）：表示来源是 embedded_scheduler 时一致写空串，与"暂未通知"语义重叠，建议 NULL 表示"无回执通道"，空串保留给"显式不回执"。
7. **【低】`products` 与 `product_snapshots` 数据 1:1 重复**（首次运行）：合理，未来快照增长后 products 仍仅保留最新；但应在 `models.py` 注释清楚此约定避免下游重复 join。
8. **【低】无显式 FK ON DELETE 策略**：`reviews.product_id`、`review_analysis.review_id`、`review_issue_labels.review_id` 若 cascade delete 缺失，删除产品将留下孤儿。
9. **【低】`notification_outbox.payload_hash` 与 `dedupe_key` 双键**：两个去重键并存，规则不同——需文档说明二者层次关系。
10. **【高 / 交叉验证补充】缺少"报告产物 artifact 表"**：`workflow_runs` 仅记录 `snapshot_path / excel_path / analytics_path / pdf_path`，**未记录 HTML 路径**；本次目录有 HTML 但 DB 无法追溯。后续审计"某邮件 / 某 HTML 到底对应哪次数据、哪版模板、哪版算法"时证据链断裂。建议新增 `report_artifacts(run_id, artifact_type, path, hash, template_version, generator_version, created_at)`。
11. **【高 / 交叉验证补充】`reviews.date_published_parsed` 解析 anchor 不一致 + 缺置信度字段**：`models.py::_parse_date_published()` 用**当前日期**作 anchor，`_backfill_date_published_parsed()` 用 `scraped_at` 作 anchor——两条路径产生的解析结果可能落入不同月/年窗口。本次 252/561=44.9% 评论是相对时间表达，影响 `recently_published_count`、近 7/30/365 天趋势、change_digest 新增判断。建议增加 `date_parse_method`、`date_parse_anchor`、`date_parse_confidence` 三个字段。
12. **【中 / 交叉验证补充】缺少源站评论唯一 ID**：当前评论去重依赖 `(product_id, author, headline, body_hash)`。Anonymous 作者、空标题（本次 316/561=56.3% 标题为空）、相同短文本、评论编辑等场景下仍可能误合并或无法识别更新。建议在 `reviews` 增加 `source_review_id`，由各站点 scraper 抽取站点原始 review id。
13. **【中 / 交叉验证补充】`product_snapshots` 未绑定 `run_id`**：当前快照通过时间戳和产品 ID 间接关联 workflow_run，趋势图无法精确回放"某次 run 看到的产品状态"。建议加 `workflow_run_id` 外键。
14. **【高 / 二次互验 N4】`impact_category × failure_mode × label_code` 三字段语义层次未定义**：

    | 字段 | 取值类型 | 唯一值数 | 设计本意 |
    |------|---------|---------|---------|
    | `review_analysis.impact_category` | enum 5 类 | 5 | 影响维度（functional/durability/safety/cosmetic/service） |
    | `review_analysis.failure_mode` | 自由文本 | **258** | 具体失效现象 |
    | `review_issue_labels.label_code` | enum 14 类 | 14 | 用户反馈主题（solid_build/quality_stability/…） |

    三字段同源（LLM 同次分析输出）但 schema 与文档**未声明它们的关系**：是"影响维度 → 具体失效 → 用户主题"三层 hierarchy？还是平行三视角？工程师做"durability 类问题分布"时，应聚合 `impact_category` 还是 `label_code`？`impact_category=durability` 的评论可能 `label_code=quality_stability`，也可能 `label_code=solid_build`，二者关系未声明。建议把 `failure_mode` 改为 enum，并定义 `impact_category × failure_mode × label_code` 的三维交叉表（哪些组合合法）。
15. **【中 / 二次互验 N2】`analytics.top_actions[]` 是迁移留下的死字段**：实测永远 `[]`，HTML 实际渲染的"建议行动"区块完全来自 `report_copy.improvement_priorities[]`（LLM 生成）。`top_actions` 字段保留但永远空 → 典型迁移债务。建议**要么激活 top_actions 作为规则降级路径**（当 LLM 失败时回退）、**要么从 schema 删除**。

### 2.4 合理性评估

- **整体规范化得分：B+**。三层 1:1:N 模型清晰；版本化字段（`taxonomy_version` / `prompt_version` / `service_version`）已埋点。
- **扩展性**：跨站点扩展靠 `products.site`，新增维度靠 `taxonomy_version` 升级，OK。
- **可维护性扣分项**：JSON blob 字段（`labels` / `features` / `scrape_quality` / `params` / `progress` / `result`）过多，schema migration 风险高。

### 2.5 优化建议

| 优先级 | 建议 | 预期价值 |
|-------|------|---------|
| 高 | `review_analysis` 添加 `UNIQUE(review_id)`；`labels` / `features` JSON 列改名为 `legacy_labels_json` 标记弃用，所有聚合改走 `review_issue_labels` | 杜绝重复分析；消除字段冗余分歧 |
| 高 | `failure_mode` 归类为 enum（`mechanical_failure / electrical_failure / wear_aging / control_anomaly / sealing_leak / fitment_compatibility / other`），原始短语保留为 `failure_mode_raw` | 39% "其他" 降至可控；可做归类聚合 |
| 高 | `scrape_quality` 增加 `missing_text_review_count = max(0, sum(products.review_count) − count(reviews))` 字段；`workflow_runs` 提取为独立列 `scrape_completeness_ratio REAL` | 让漏抓型故障可被 SQL 监控 |
| 中 | reviews 表新增 `date_published_estimated BOOLEAN` + `date_published_confidence`（解析 "a year ago" 时标 low），趋势聚合时按置信度过滤 | 解决相对时间污染趋势图 |
| 中 | products 表加 `last_scrape_completeness REAL`、`last_scrape_warnings TEXT` (JSON array) | 让产品行直接展示采集质量 |
| 低 | 所有 FK 显式 `ON DELETE CASCADE / SET NULL`；tasks/outbox 表新增 status enum CHECK | 长期数据治理 |
| 低 | 索引建议：`CREATE INDEX idx_reviews_published_parsed ON reviews(date_published_parsed)`；`CREATE INDEX idx_labels_polarity_severity ON review_issue_labels(label_polarity, severity)` | 趋势/聚合 SQL 提速 |
| 高 | **【交叉验证补充】**新增 `report_artifacts` 表（`run_id, artifact_type, path, hash, template_version, generator_version, created_at`）；HTML / PDF / 邮件正文等都要入库 | 解决产物追溯链断裂 |
| 高 | **【交叉验证补充】**新增最小版 `metric_definitions` 字典表：`metric_key, formula, numerator_source, denominator_source, window, confidence_rule` — 让 HTML/Excel 每个指标都能反查公式与口径 | 杜绝 tooltip vs 代码漂移 |
| 高 | **【交叉验证补充】**统一日期解析 anchor：废弃 `_parse_date_published()` 用当前日期为 anchor 的路径，所有相对时间统一以 `scraped_at` 为 anchor，并在 reviews 表新增 `date_parse_method / date_parse_anchor / date_parse_confidence` 三字段 | 杜绝同一字符串两路径解析不一致 |
| 中 | **【交叉验证补充】**`product_snapshots` 增加 `workflow_run_id` 外键；让趋势点和 run 直接绑定，可重放 | 趋势可追溯 |
| 中 | **【交叉验证补充】**`reviews` 增加 `source_review_id`（站点原始评论 ID），增量监控可识别"修改 / 删除 / 新增"，不再依赖弱标识 hash 去重 | 长期增量可靠性 |

---

## 3. HTML 报告分析

### 3.1 页面与内容结构

观察到的章节层级（基于 `<h1>~<h4>` 抽取）：

```
H1 QBU 网评监控智能分析报告
  H3 关键判断（hero + 3 条 executive_bullets）
  H3 报告口径（mode / perspective 说明）
H2 建议行动（improvement_priorities Top N）
H2 今日变化
  H3 监控起点（bootstrap 信息卡）
  H3 问题变化（issue_changes — 当前空）
  H3 产品状态变化（product_changes — 当前空）
  H3 新近评论信号（review_signals — 仅 12 条）
H2 变化趋势（最大版面占比）
  H3 近 7 天   × 4 维度（声量情绪 / 问题 / 产品 / 竞品）  ← 全部 status=accumulating 空图
  H3 近 30 天  × 4 维度
  H3 近 12 个月 × 4 维度
H2 自有产品问题诊断（issue_cards × 8）
H2 自有产品排行（risk_products 表 + 价格-评分象限）
H2 竞品对标（雷达 + gap_analysis）
H2 全景数据（评分分布 / 特征热力图 / 评论明细）
```

### 3.2 各项指标分析（口径 + 价值）

#### 3.2.1 顶部 KPI 横条（7 张卡）

| 指标 | 值 | 公式 | 评价 |
|-----|----|-----|-----|
| 健康指数 | **96.2** | NPS = (promoters − detractors) / own_reviews × 100，映射到 0-100；own < 30 时按 weight = own/30 收缩到先验 50（`report_common.py:521-561`） | ✓ 思想正确；但 5 颗星 promoter / 1-2 星 detractor 的 NPS 用在评论池上口径已与 NPS 原义不同（NPS 应来自调研问卷），命名易误导 |
| 差评率 | **2.4%** | `own_negative_review_rows(10) / own_review_rows(418)`，其中 negative = `rating ≤ NEGATIVE_THRESHOLD`（默认 ≤2 星）（`report_analytics.py:2451-2453`） | ✓ tooltip 写明"≤2 星"；与"好评率 94.7% 含 ≥4 星，3 星算中评"配套自洽 |
| 累计自有评论 | **418** | `reviews WHERE ownership='own' COUNT` | ✓ |
| 好评率 | **94.7%** | `own_positive(396) / own_total(418)`，positive = rating ≥ 4 | ✓ |
| 高风险产品 | **0** | `COUNT(risk_score ≥ 35)`；本案最高 32.6 | ✓ 但与 hero "缺陷正严重侵蚀核心体验" 的措辞矛盾 |
| 总体竞品差距指数 | **4** | 各维度 `(competitor_positive_rate + own_negative_rate)/2 × 100` 的均值（`report_common.py` tooltip + `report_analytics`） | ⚠ tooltip 公式与 `competitive_insight` 文字（"做工与质量差距 13"）不同维度的混用，读者难判 "4" 和 "13" 如何并存 |
| 样本覆盖率 | **64%** | `ingested(561) / SUM(products.review_count)(879)`（`report_common.py:1018`） | ✓ 含原因 tooltip；但应再细到行级（产品 1=0%、产品 7=43%） |

**主要槽点**：

1. `delta_display` 全为空 / `delta-flat`，bootstrap 期 7 张卡顶部都是 "—"，视觉信息密度低。
2. 健康指数与高风险产品数同处一排但口径不同（健康指数用全样本 NPS，高风险用 risk_score 阈值），管理者会下意识对照"健康分高 = 风险产品少 = 没事"，掩盖结构性问题。

#### 3.2.2 评论范围卡（Review Scope）

| 指标 | 值 | 评价 |
|-----|----|-----|
| 累计自有评论 | 418 | ✓ |
| 累计竞品评论 | 143 | ✓ |
| 本次入库评论 | 561 | **⚠ 严重误导**：当 99% 是补采时，"本次入库" hero 数字让人错以为今天新发了 561 条。tooltip "本次入库请看今日变化" 不够强势 |
| 近 30 天评论 | 3 | ✓ 但和 561 摆在一起对比悬殊，应解释 |

#### 3.2.3 关键判断 / Hero

- `hero_headline = "自有产品健康指数 96.2，但结构设计与售后缺陷正严重侵蚀核心体验"` — **修辞冲突**：96.2/100 是 A+，"严重侵蚀"语意上是 D 级，二者并存不能给读者明确判断。
- `executive_bullets[0]` "0.75HP 风险分 32.6/100 且差评率达 4%" — 数字检验：该产品自身 9/253 ≈ 3.6% 取整为 4%，但放在卡里容易被误读为"自有平均"。
- `executive_bullets[2]` "做工与质量差距达 13（竞品好评率 18.9% vs 自有差评率 6.9%）" — 与 KPI 卡"总体竞品差距指数 4"并列出现，两个 4 / 13 的关系无对照表。
- **【交叉验证补充 / 重大 UI bug / 二次互验根因升级】"建议行动"标题被 LLM 输出截断成半句话**：HTML 总览中出现如 `"针对 Walton's #22 Meat Grinder、Walton's General Duty Meat Lug 与 Quick Patty Maker 反馈的肉"` 的句段（截断处恰是 80 字附近）。详细问题卡里其实有完整的多段落建议，但**总览入口直接损失业务语义**。

  **【二次互验 N7 真根因】**：不是单纯模板 bug，而是 **schema 设计要求 LLM 在 `improvement_priorities[].action` 单字段内同时承担"卡片标题"与"段落级建议正文"两个语义层次**。修复必须从 prompt + schema 同步动手，把 action 拆为：

  ```json
  {
    "label_code": "structure_design",
    "short_title": "结构设计：肉饼厚度不可调",          // ≤ 20 字（LLM 输出）
    "full_action": "针对 Walton's #22... ",              // 段落级（LLM 输出）
    "evidence_count": 13,
    "evidence_review_ids": [252, 254, ...]                // 顺带补证据回链
  }
  ```

#### 3.2.4 今日变化（change_digest）

bootstrap 期实际为空：

- `issue_changes` / `product_changes` 全 `[]`，`top_actions=[]`
- 体现为 "本期暂无新增或升级问题。本期暂无价格、库存或评分快照变化。" 占据 3 个卡片版面
- `review_signals.fresh_competitor_positive_reviews` 列出竞品好评 — 但只有 2 条且都是 5/4 星好评，对自有改良意义不大

#### 3.2.5 变化趋势（最大版面 + 最低信息密度）

- 12 个 panel × 4 个维度 = 48 个图位，**首日全部 `status=accumulating`**
- "近 30 天 / 评论声量与情绪" 表格区有数据但只 2-3 行（因为 `recently_published_count=3`）
- "近 12 个月" 维度勉强能画图（基于 `date_published` 历史聚合），但里面 50%+ 数据点来自被估算的 "a year ago" / "2 years ago"，**精度无声明**（实测：252/561=44.9% 评论使用相对时间表达）
- **【交叉验证补充 / 二次互验精确化】`trend_digest.ready` 状态实测分布**：

  | view | dimension | outer status | inner KPI status | 嵌套 |
  |------|-----------|--------------|------------------|------|
  | month | competition | accumulating | accumulating | ✓ |
  | month | issues | accumulating | accumulating | ✓ |
  | month | **products** | accumulating | **ready** | **⚠** |
  | month | sentiment | ready | ready | ✓（但样本仅 3 条） |
  | week | competition / issues / sentiment | accumulating | accumulating | ✓ |
  | week | **products** | accumulating | **ready** | **⚠** |
  | year | competition / issues / sentiment | ready | ready | ✓ |
  | year | **products** | accumulating | **ready** | **⚠** |

  汇总：**outer = 8 accumulating + 4 ready；inner = 5 accumulating + 7 ready**。**初稿"全部 accumulating"的判断需修正**——实际 12 个 panel 中 4 个 outer ready，但更深的问题是 **3 个 products 维度 panel 外内 status 不一致**（outer accumulating 但 inner ready）

- **【二次互验 N1 / 新 P1】products 维度 ready 状态在首日 1 次 scrape 下也判 ready**：products 维度按 `product_snapshots.scraped_at` 聚合，首日只有 1 次 scrape → 8 个数据点；理论上不可能形成趋势，但 week/month/year 三个 view 的 inner KPI status 全部 `ready`。**根因**：inner KPI 的 ready 判定逻辑只看"可比时间点 ≥ 1"，outer primary_chart 看"图能不能画"，二者未联动 → 同一 panel 出现"折线图画不出但 KPI 说 ready"的精神分裂

- **【二次互验 N5】trend ready 阈值无统计意义**：实测 `month/sentiment` 仅 3 条样本就进 ready；阈值可能等同"样本 ≥ 1"。如果样本是 1 条 LLM 误判 negative 的评论，"近 30 天差评率 100%" 就会被吓人地展示为 ready trend。建议至少 **样本 ≥ 30 + 时间点 ≥ 7** 才允许 ready
- **【交叉验证补充】HTML 趋势模板 `daily_report_v3.html.j2` 用 `row.values()` 输出表格行**：依赖 dict 插入顺序而非按 columns key 取值。一旦上游 trend_digest JSON 字段顺序变化（如 Python 字典 hash 随机化、或字段重排），列与值会**静默错位**——稳定性风险

#### 3.2.6 自有产品问题诊断（issue_cards × 8）

- 内容质量很高：`actionable_summary` + `failure_modes`(频次+严重度) + `root_causes`(置信度) + `temporal_pattern`
- **严重缺陷**：`duration_display "约 8 年 1 个月"` 在卡片头部突出展示，读者会读为"问题持续 8 年"——实际只是评论池中最早—最晚 `date_published` 跨度（`report_common.py:422-440`），**与"问题是否仍在发生"无关**

#### 3.2.7 自有产品排行

- 表格只展示 2 个产品（仅有 `negative_review_rows>0` 或 `risk_score>0` 的 own 产品）
- **标题"自有产品排行"误导**：5 个 own 产品中 3 个不见踪影：
  - `Walton's #22 Meat Grinder`（144 条评论 / 0 差评）
  - `Walton's General Duty Meat Lug`（71 条 / 0 差评）
  - `.5 HP Dual Grind Grinder #8`（91 中 0 抓取 — 实为数据故障）
- 应改为"自有产品风险榜（含负面评论的 N 个）"并附"无负面：3 个产品"补充

#### 3.2.8 竞品对标

- 雷达图 + gap_analysis 表格
- `gap_rate=13`（做工与质量）显著但 `priority='low'` — 优先级算法值得复核
- **竞品自身的差评率 44.6% / 43.9%（Bass Pro 两款）在该区段没有展示** — 对自有产品营销策略而言，这是巨大反向机会，被埋没
- **【交叉验证补充】竞品对标表缺少分母、率、样本量、置信度和差距公式**：当前只展示"竞品好评 / 自有差评"主题与百分比，但未列竞品总样本（143）、自有总样本（418）、差距公式（`(comp_pos_rate + own_neg_rate)/2 × 100`）。专业读者无法独立判断"差距 13"是高是低

#### 3.2.9 全景数据

- 评分分布、热力图、评论明细 — 标准全景，OK
- "评论明细" 嵌入 HTML 实际可能仅 sample（HTML 367KB 规模看不像全部 561 条全嵌），需确认是否分页

### 3.3 可读性与参考价值评估

- **设计感 / 视觉**：B+，分级清晰、tooltip 丰富
- **首日信息密度**：D（占地大但实质信息少）
- **稳态运行预期信息密度**：B（依赖未来 7-30 天积累）
- **可解释性**：B-，多个口径并存但缺统一术语对照表

### 3.4 优化建议

> ⚠ **前向引用**：本节的"在 HTML 顶部加数据质量卡 / 通知状态卡 / 覆盖率卡"等"工程视角内部信号"建议已被 **§11 用户视角再审视**收口或撤回——这些信号应移到内部运维频道，不在用户报告中展示。请以 §11 为最终决策依据。

| 优先级 | 建议 |
|-------|------|
| 高 | bootstrap / change-only / quiet 模式应有专属 layout，**HTML 模板按 `report_mode` 折叠区段**，首日不要展示全是空的 12 个图 |
| 高 | "本次入库 561" 改为 "本次新增 3 / 历史补采 558"，hero 数字突出 3 |
| 高 | issue card 的 `duration_display` 重命名为"评论时间跨度"或"高频期 YYYY-MM ~ YYYY-MM"，避免误读 |
| 高 | 顶部 KPI 卡片增加"⚠ 数据质量警示"专属一卡：当 SKU 采集 0 / 覆盖率 < 50% / 估算日期占比 > 30% 时显示 |
| 中 | "自有产品排行" 改为 "自有产品风险榜"，下方再展 "无负面/无信号产品 N 个 (折叠)" |
| 中 | "总体竞品差距指数 4" 与 cluster 段的 "差距 13" 用同一公式 / 同一缩放 / 同一颜色锚点；KPI 卡 hover 列出维度 Top3 分解 |
| 中 | 竞品对标新增"竞品风险产品"卡（用同一 risk_score 公式跑竞品） |
| 低 | hero_headline LLM 输出后做后置一致性校验：高健康分 + 措辞含"严重"时回退为温和 fallback（**一次 prompt 内 instruction 化即可，不增加调用次数**） |

---

## 4. Excel 数据分析

### 4.1 Sheet 概览

| Sheet | 行 × 列 | 数据源（基于 `report.py` 审计） | 评价 |
|-------|---------|-------------------------------|------|
| 评论明细 | 562 × 18 | `snapshot["reviews"]` 拼接 review_analysis（`report.py:752-888`） | ✓ 内容详实，列设计合理 |
| 产品概览 | 9 × 12 | products + 聚合 reviews（差评数=≤2 星计数；风险分=risk_score）（`report.py:891-920`） | ⚠ SKU 1193465 全空但无标记 |
| 今日变化 | 14 × 4 | change_digest 摘要 + warnings 文本 | ⚠ 列设计粗糙，分类用文本枚举 |
| 问题标签 | 998 × 6 | review_issue_labels（label_code 翻译为中文）（`report.py:923-950`） | ⚠ 998 vs DB 951 偏差 47 行 |
| 趋势数据 | 603 × 11 | trend_digest 各维度 KPI/表格平铺（`report.py:952-985`） | ⚠ 同表混合多种结构，列复用造成稀疏 |

### 4.2 字段定义与数据内容

#### 4.2.1 评论明细（18 列）

列：`ID, 窗口归属, 产品名称, SKU, 归属, 评分, 情感, 标签, 影响类别, 失效模式, 标题(原文), 标题(中文), 内容(原文), 内容(中文), 特征短语, 洞察, 评论时间, 照片`

- 所有 561 条都展开了原文 + 翻译 + 标签 + 失效模式 + 洞察 → **可下钻可信度高**
- **问题 1【已实测验证】**：`标签` 与 `影响类别` 列内容**561/561 行完全相同**（如 "做工扎实, 易清洗"）— 影响类别本应是 `review_analysis.impact_category`（functional/durability/service/cosmetic/safety enum）但被错误填成了 labels 中文化字符串。**根因**：`query_cumulative_data()` 未 select `ra.impact_category`，Excel 生成时回退到 labels
- **问题 2【交叉验证 — 修正初稿】**：`失效模式` 列**561 行 100% 全空**（初稿误判为"对部分负面评论显示中文短语"，那是 DB 字段值，不是 Excel 列内容）。但 DB `review_analysis.failure_mode` 实际有 561/561 条非空数据。**根因同问题 1**：query 未 select `ra.failure_mode`。这是**对产品改良人员最有价值的字段，被实现 bug 直接屏蔽**——属于"已生成但未透传"的资产浪费
- **问题 3【交叉验证补充】**：`照片` 列 561 行单元格全空，但**工作簿实际嵌入 82 张 drawing 图片**（openpyxl image embed）。机器解析仅看单元格会误判"无图"；建议同时保留 URL / 图片数量到单元格
- **问题 4【交叉验证补充】**：`标题(原文)` 列 316/561=56.3% 为空（站点本身就有大量无标题评论），按标题维度做分析价值有限
- **问题 5**：`评论时间` 列已统一用 `date_published_parsed`（如 `2026-04-10`）— 比原始 `date_published` 字符串好；但 252/561=44.9% 来自相对时间解析，列内未标注估算置信度

#### 4.2.2 产品概览（9 行 = 1 表头 + 8 产品）

| 行 | SKU | 归属 | 站点评论数 | 采集评论数 | 差评数 | 差评率 | 风险分 |
|---|-----|------|---------|----------|------|------|------|
| R1 | 2834849 | 竞品 | 80 | 56 | 25 | 0.4464 | · |
| R2 | 1159178 | 自有 | 253 | 109 | 9 | 0.0356 | 32.6 |
| R3 | 100865703 | 竞品 | 88 | 57 | 25 | 0.4386 | · |
| R4 | 192235 | 自有 | 94 | 94 | 1 | 0.0106 | 28.9 |
| R5 | 250855 | 自有 | 71 | 71 | 0 | 0 | · |
| R6 | 2834842 | 竞品 | 58 | 30 | 5 | 0.1667 | · |
| R7 | 192242 | 自有 | 144 | 144 | 0 | 0 | · |
| R8 | **1193465** | **自有** | **91** | **0** | **0** | **·** | **·** |

- **【P0】R8 是核弹级数据漏洞**：`.5 HP Dual Grind Grinder #8` 应该有 91 条评论，实际 0 条入库；`差评率` 列填 "·" 而非 "0/0=N/A" 任何醒目标记；后续"自有产品排行"和 KPI 都把它当成"无差评好产品"对待
- 数字格式不一致：差评率有时 0、有时 0.4464285714285715（15 位小数）、有时 ·
- "风险分" 仅填 own 产品；竞品全 `·`，列定义不明（应改名"自有风险分"或新增"竞品差评率分"）
- 价格、库存这一日同一时间快照，**没有变动信号**（合理：首次运行）
- **【P0 / 交叉验证补充 — 严重】"差评率"列分母不统一**：实测显示

  | 产品 | 归属 | 站点评论 | 采集 | 差评 | Excel 差评率 | 差评/站点 | 差评/采集 | 实际用了哪个分母 |
  |------|------|---------|-----|------|------------|----------|----------|----------------|
  | Cabela's HD Sausage Stuffer | 竞品 | 80 | 56 | 25 | **44.64%** | 31.25% | 44.64% | **采集** ✓ |
  | .75 HP Grinder (#12) | 自有（**风险**） | 253 | 109 | 9 | **3.56%** | 3.56% | 8.26% | **站点** ✓ |
  | Cabela's Commercial Sausage | 竞品 | 88 | 57 | 25 | **43.86%** | 28.41% | 43.86% | **采集** ✓ |
  | Walton's Quick Patty Maker | 自有（**风险**） | 94 | 94 | 1 | 1.06% | 1.06% | 1.06% | 二者相同 |
  | Cabela's HD 20-lb. Mixer | 竞品 | 58 | 30 | 5 | **16.67%** | 8.62% | 16.67% | **采集** ✓ |

  **结论**：风险产品（有 `risk` 对象）使用 `risk.negative_rate`（分母 = 站点评论数 = `max(site, ingested)`），非风险/竞品回退为差评数 / 采集评论数。**同一列双口径**会让风险产品差评率被人为压低（.75HP 的 3.56% 用站点分母，若用采集分母则 8.26%，差距 2.3 倍），竞品差评率被人为放大。这是**直接误导排序与决策**的硬 bug

#### 4.2.3 今日变化（14 行 × 4 列）

```
R1  状态     监控起点          bootstrap   首次建档，当前结果用于建立监控基线
R2  摘要     本次入库评论       561         ·
R3  摘要     新近评论          3           ·
R4  摘要     历史补采          558         ·
R5  摘要     自有新近差评       0           ·
R6  摘要     新增问题          0           ·
R7  摘要     升级问题          0           ·
R8  摘要     改善问题          0           ·
R9  摘要     产品状态变更       0           ·
R10 提示     estimated_dates   已触发      评论发布时间存在较高比例的相对时间估算...
R11 提示     backfill_dominant 已触发      本次入库以历史补采为主，占比 99%
R12 评论信号  工作表现极佳...    5           竞品新近好评 / 做工扎实, 易清洗
R13 评论信号  运转良好如预期     4           竞品新近好评 / 做工扎实
```

- 内容精炼但模板化
- R10/R11 的 `estimated_dates` / `backfill_dominant` 提示是**关键告警**，但夹在中间且无颜色 / 严重度区分，容易被忽略

#### 4.2.4 问题标签（998 行含表头 = 997 数据行 × 6 列）

- 与 DB `review_issue_labels` 表（951 行）行数不匹配（**997 vs 951，偏差 46 行**）
- **【交叉验证 — 根因已定位】**：实测 Top 标签里出现 **`durability`(8 行) 这一英文未规范化值**，极性分布出现 **`neutral`(1 行) 这一未翻译/未映射极性值**（其他都是中文 `正面/负面`）。这证明 Excel"问题标签"sheet **直接遍历 `review.analysis_labels`（即 `review_analysis.labels` JSON）**，而非消费同步后的规范化表 `review_issue_labels`。Codex 报告也已定位到 `qbu_crawler/server/report.py::_generate_analytical_excel()` 中的相应逻辑
- **业务影响**：同一份报告中"问题诊断（HTML 8 张卡）"消费规范化表，"问题标签 sheet"消费原始 LLM JSON，**两套口径并存**，按标签做改良优先级 / 设计归因 / 管理汇报时数量、命名、极性都可能对不上
- 实测 Top 标签：`性能强(265) 做工扎实(148) 易上手(124) 性价比高(101) 结构设计(90) 易清洗(68) 质量稳定性(52) 售后与履约(52) 材料与做工(24) 包装到位(20) 噪音与动力(19) 包装运输(12) 安装装配(11) durability(8) 清洁维护(3)`

#### 4.2.5 趋势数据（603 行）

**结构混乱**：单 sheet 拼接了：
- 产品快照明细（8 行）
- 近 7 天 × 4 维度（KPI + 表格） × 2
- 近 30 天 × 4 维度
- 近 12 个月 × 4 维度
- 各 section 通过 A 列文本标记（如 "近30天 / 评论声量与情绪 / KPI"）切分

**问题**：

- 同列在不同段含义不同（A 列时而是日期、时而是分组名、时而是空），破坏 SQL 直接读取的可能
- 行数 603 大部分是空行（status=accumulating 的 KPI 段也写"可比时间点 0 / 最新评分差 —"）
- Excel pivot / 透视表无法直接用，仅能阅读

### 4.3 数据质量与一致性

| 维度 | 评估 |
|------|------|
| 完整性 | ❌ SKU 1193465 全空、未告警；产品概览少 1 行有效数据；**【交叉验证】Excel 失效模式列 561 行 100% 空（DB 有 561 条非空）；影响类别列被 labels 覆盖（561/561 雷同）** |
| 准确性 | ⚠ 抽样校验大体一致（R2 0.75HP 109 抓取 / 9 差评 / 风险分 32.6 ≡ analytics）；**【交叉验证】但产品概览"差评率"列分母不统一，风险产品用站点分母、其他用采集分母 — 列内含两种口径** |
| 一致性（与 HTML） | ⚠ KPI 数字一致；但 HTML 自有产品排行 2 行 vs Excel 产品概览 8 行（含竞品+无负面 own），口径不同需说明；**【交叉验证】HTML 问题诊断（8 张卡，规范化标签）vs Excel 问题标签 sheet（997 行，原始 LLM 标签）口径不一** |
| 异常值标记 | ❌ `0` / `0/0` / `N/A` / `·` 各种表达混用，无统一异常值标记 |
| 可解释性 | ✓ 列名用中文且业务化（"采集评论数"而非 reviews_ingested） |

### 4.4 与 HTML 一致性验证（抽样）

| 项目 | HTML 值 | Excel 值 | analytics.json | 一致性 |
|-----|---------|---------|----------------|--------|
| 健康指数 | 96.2 | （无） | 96.2 | ✓ |
| 自有差评率 | 2.4% | 加总 R2+R4+R5+R7+R8 差评 = 10/418 ✓ | 2.4% | ✓ |
| 累计自有评论 | 418 | 109+94+71+144+0=418 ✓ | 418 | ✓ |
| 0.75HP 风险分 | 32.6 | 32.6 | 32.6 | ✓ |
| 本次入库 | 561 | 561 | 561 | ✓ |
| 近 30 天 | 3 | （无该 KPI） | 3 | ⚠ Excel 缺 |

**结论**：HTML / Excel / analytics.json 在数字层面相互一致，没有发现"显示错位 / 计算偏差"的硬 bug；但 **Excel 缺失若干 HTML 上的关键 KPI（如近 30 天评论数、健康指数、覆盖率）**，使得 Excel 单独使用时无法完整复现 HTML 摘要。

### 4.5 优化建议

> ⚠ **前向引用**：本节中关于"新增指标说明 sheet / 数据质量 sheet"的建议已被 **§11 用户视角再审视**撤回——这些是工程视角内容，用户不关心；最终 Excel 形态见 §11.4（4 sheets：核心数据 / 现在该做什么 / 评论原文 / 竞品启示）。请以 §11 为最终决策依据。

| 优先级 | 建议 |
|-------|------|
| 高 | 评论明细的"影响类别"列修复为真正的 `impact_category`（functional/durability/safety...）而非 labels 重复 |
| 高 | **【交叉验证补充】评论明细"失效模式"列修复**：在 `query_report_data()` / `query_cumulative_data()` SELECT 语句中加入 `ra.failure_mode, ra.impact_category`；Excel 生成时按字段透传 |
| 高 | **【交叉验证补充】产品概览"差评率"列拆为两列：`差评率(站点分母)` 与 `差评率(采集分母)`** — 避免同列双口径；或在数值后加 `(站点)` / `(采集)` 标签 |
| 高 | **【交叉验证补充】Excel 问题标签 sheet 改为消费 `review_issue_labels` 规范化表**；原始 `review_analysis.labels` 移到独立调试 sheet "LLM 原始标签"；从根本上消除 `durability / neutral` 这类未规范化值 |
| 高 | 产品概览 SKU 1193465 行加红底/告警列"采集异常 - 站点 91 条实际 0 条"，差评率列标 "N/A (无样本)" |
| 高 | 产品概览统一数字精度：差评率保留 4 位百分数（44.64%）；空值统一用 "—" |
| 中 | "趋势数据" sheet 拆为独立 sheet（趋势_产品快照 / 趋势_情绪 / 趋势_问题 / 趋势_竞品），每 sheet 列结构一致；**【交叉验证补充】产品快照趋势（按 `scraped_at`）与评论发布时间趋势（按 `date_published_parsed`）必须分 sheet，时间轴含义完全不同，混用易误读** |
| 中 | 新增 "KPI 总览" sheet，单独复刻 HTML 顶部 7 张卡 + 评论范围 4 张卡，便于独立看 |
| 中 | **【交叉验证补充】新增"指标说明"sheet**：列每个指标的来源表、字段、公式、分母、时间窗口、适用场景、置信度规则——把 metric_definitions 字典随报表交付 |
| 中 | **【交叉验证补充】新增"数据质量"sheet**：列 0 覆盖产品、低覆盖产品、相对日期占比、翻译失败、分析失败、通知失败（outbox deadletter）等所有报告级风险 |
| ~~低~~ | ~~评论明细照片列改为 hyperlink~~ → **【第六轮收口 撤回】**：用户明确保留 drawing 嵌入，不改 URL/hyperlink |
| 低 | "今日变化" sheet 增加 "严重度" 列，把 estimated_dates / backfill_dominant 的告警可识别 |

---

## 5. 角色视角价值评估

### 5.1 产品改良人员

| 类别 | 内容 |
|------|------|
| **有价值** | issue_cards × 8 的 `actionable_summary / failure_modes / root_causes` 中文分析（深度可比咨询报告）；`improvement_priorities` 5 条按 evidence_count 排序的改良建议；评论明细可下钻原文+翻译+特征短语 |
| **价值有限** | hero_headline / executive_summary 偏管理语气，对工程师不直接；`competitive_gap_index "4"` 这类指数缺乏与具体改良动作的连接 |
| **缺失** | ① 失效模式按零部件 / 工序拆分（电机 / 开关 / 壳体 / 装配 / 售后流程）的归因表；② 改良前后对比（验证效果），首日未具备但需在 schema 上预留 `recommendation_id` 让后续 run 跟踪；③ 竞品已实现的"反例" benchmark — 当前只有少量 `benchmark_examples` 但未结构化对照 |
| **改进建议** | • 增加 "Top 失效模式 → 影响 SKU → 涉及部件 → 改良方向 → 历史是否提及" 五维改良追踪表<br>• 每条 `improvement_priorities` 标注 `evidence_review_ids[]` 直接 deeplink 到原始评论<br>• 加 "竞品做对了什么" 反向 benchmark 模块 |

> ⚠ **§5 角色视角章节范围澄清（2026-04-27 第四轮）**：本章逐角色列"有价值/缺失/建议"是为了**审视当前报告对各角色的覆盖度**，**不意味着要为每个角色建独立 tab/导出**——后者已被 §11.10 明确撤回。最终单一报告通过"决策深度分层"自然满足所有角色，详见 §11.9 / §11.10。

### 5.2 设计人员

| 类别 | 内容 |
|------|------|
| **有价值** | 特征短语（"肉饼厚度过大"、"无反转设计"、"中空壳体易积水"）能直接映射到设计决策；图片评论（48 条 image_review_rows）部分有原图链接可视化检查 |
| **价值有限** | KPI 体系偏运营 / 营销，缺乏"用户操作步骤数"、"装配时长"、"清洁难度"等设计专用指标 |
| **缺失** | ① 用户使用旅程（开箱→装配→使用→清洗→维护）的痛点分布；② UX/工业设计可复用的"用户原话证据墙"——当前 `example_reviews` 是 JSON 字符串需要打开才看；③ 图评聚类（"金属碎屑"图、"装配错位"图）按类目展示 |
| **改进建议** | • 新增 "用户旅程分阶段问题热力图"（X=旅程阶段，Y=问题极性，颜色=频次）<br>• 图评单独 gallery（缩略图墙）按问题分类<br>• 把 `assembly_installation`、`cleaning_maintenance`、`structure_design` 三个 label 合并为"使用体验" tab |

### 5.3 管理者

| 类别 | 内容 |
|------|------|
| **有价值** | 顶部 KPI 7 卡 + hero_headline 一句话结论 + executive_bullets 3 条；自有产品风险榜（高 / 低风险一目了然） |
| **价值有限** | bootstrap 首日所有 delta 都是 flat → 趋势对管理者意义最大但当前为零；竞品差距指数与维度差距同时是 "4" 与 "13" 让管理者无法判断"是好是坏"；很多 tooltip 是公式而非"该指标 80 分以上属健康" |
| **缺失** | ① 同期上月 / 上年 / 行业基准对比（缺）；② 资源分配建议（如"应优先投入研发预算到 0.75HP 系列"）—— LLM 已能给但分散在 issue_cards 内；③ 一页 PDF 的"管理者快讯"压缩版 |
| **改进建议** | • 邮件中嵌入 ≤200 字的"高管摘要" + 单图（自有 vs 竞品差评率红黑对比）<br>• 顶部 KPI 加"健康度色彩"（绿/黄/红）阈值锚定<br>• 增加"本期需要管理者关注的 N 件事"区块，自动从 risk_products + improvement_priorities + scrape_quality_alerts 合成 |

---

## 6. 指标计算逻辑与数据链路分析

### 6.1 核心指标链路（结合源码定位）

| 指标 | 原始数据 | 加工链 | 公式 / 关键代码 |
|-----|---------|--------|----------------|
| `health_index` (96.2) | `reviews.rating WHERE ownership='own'` | promoters=≥4★, detractors=≤2★, NPS = (P-D)/own × 100 → /2+50；own < 30 时按 weight=own/30 收缩到先验 50 | `report_common.py:521-561`（`compute_health_index` + `_bayesian_bucket_health`） |
| `own_negative_review_rate` (2.4%) | `reviews.rating ≤2 ∩ ownership='own'` | / `own_total` | `report_analytics.py:2451-2453`（rating ≤ `NEGATIVE_THRESHOLD`） |
| `all_sample_negative_rate` (11.6%) | `reviews.rating ≤2 across all` | 65/561 | 同上但不限 ownership |
| `low_rating_review_rows` (87) | `reviews.rating ≤3 across all` | **包括 3 星中评！** | 与 `negative_review_rows` 不同口径，作为 KPI 候补字段 |
| `sentiment_dist (negative=71)` | `review_analysis.sentiment` | LLM 分类，独立于评分 | `translator.py:258` |
| `risk_score` (32.6) | 5 因子加权（不超 100） | 35% neg_rate + 25% severity_avg + 15% evidence_rate + 15% recency + 10% volume_sig | `report_analytics.py:836-844`；其中 neg_rate 分母是 `max(site_review_count, ingested)` — 故 SKU 1193465 (91, 0) 跑出 neg_rate=0/91=0，跳过风险评分 |
| `coverage_rate` (64%) | reviews count / SUM(products.review_count) | 561 / 879 | `report_common.py:1018` |
| `recently_published_count` (3) | `reviews.date_published_parsed ≥ today − 30d` | COUNT | `report_analytics.py:2400-2401` |
| `competitive_gap_index` (4) | 各 label_code 的 gap_rate 平均 | gap_rate = (comp_pos_rate + own_neg_rate)/2 × 100 | `report_common.py` tooltip 定义 + `report_analytics` 维度循环 |
| `issue_cards` / clusters | `review_issue_labels GROUP BY label_code` | 取 `label_polarity='negative'` 聚类，example_reviews 取 ≤2★ + 有图优先（≤3 条） | `report_analytics.py:649-723` |
| `executive_summary` / `hero_headline` | KPI + clusters + gap 综合 prompt | LLM 一次调用（`model=qwen3.6-flash`, `prompt_version=v2`） | `report_llm.py:751-791`（`generate_report_insights`） + `report_llm.py:468+`（`_build_insights_prompt`） |
| `change_digest.product_changes` | `product_snapshots` 跨日 diff | INNER JOIN 上一 baseline run | `report.py:1520+`，bootstrap 期跳过 |
| `trend_digest` | `reviews.date_published_parsed` × label / sentiment / `scraped_at`（产品快照） | 各维度按 week/month/year 桶 | `report_analytics.py:1389-1495, 2261-2290`；维度 = `["sentiment", "issues", "products", "competition"]`（`report_analytics.py:2268-2271`） |
| `scrape_quality` | products(rating, stock_status, review_count) 缺失统计 | missing_X / total | `scrape_quality.py:15-52` |
| `duration_display` | `review_analysis.example_reviews` 的 `date_published_parsed` min/max | 跨度天 → 年/月格式化 | `report_common.py:422-440` |
| `high_risk_count` 阈值 | `risk_score ≥ HIGH_RISK_THRESHOLD`（默认 35） | COUNT | `report_common.py:92` 周边 |
| `top_actions` 为空根因 | bootstrap 第一次 run | `skip_delta=True`（`report_analytics.py:2524`），所有 KPI 无前期对比，`delta_display=""` | `report_analytics.py:2488-2496`；`report_common.py:1040-1054, 1122-1150` |

### 6.2 数据链路完整性

- ✓ **可追溯**：每条 KPI 都能从 `analytics.json → DB SQL` 反向回放；`snapshot_hash` 让产物可校验
- ✓ **可重放**：`workflow_runs` 完整记录 paths，删除产物可由原始 DB 重新生成
- ⚠ **不闭环**：`report_copy` 由 LLM 生成后**未写回 DB**（如 `workflow_runs.report_copy_json`），下次复盘必须翻 analytics.json 文件
- ⚠ **中间态泄漏**：`analytics.json` 中的 `_heatmap_data / _radar_data / _trend_series / _products_for_charts / _sentiment_distribution_*` 等下划线字段（说明是私有/内部用）出现在持久化产物里，未经 schema 化

### 6.3 主要风险点

| 风险 | 影响 | 证据 |
|------|------|------|
| **scrape_quality 不检查"实际抓取数 vs 站点 review_count"** | SKU 0 抓取漏报，下游所有指标失真 | `workflow_runs.scrape_quality.missing_review_count_ratio = 0.0`，但实际产品 1 全空 |
| **多种 negative 口径混存** | 同一份报告内"差评"含义不一（≤2★ vs ≤3★ vs sentiment-negative），用户 / Excel / KPI / cluster 间易冲突 | `negative_review_rows=65 ≠ low_rating_review_rows=87 ≠ sentiment.negative=71` |
| **date_published_parsed 解析含相对时间估算** | "2 years ago" → 当日减 2 年，trend_digest 12 个月图含此类近似点 | analytics.json 中 `id=436` body_published="4 years ago" 解析为 2022-04-26 |
| **risk_score 分母是 max(site, ingested)** | 当 ingested=0 但 site>0 时 neg_rate=0，**风险产品反而隐身** | SKU 1193465 case |
| **failure_mode 自由文本** | 39% "其他"，无聚合价值 | `review_analysis.failure_mode` 分布 |
| **LLM 一次性出 5 段长 copy** | 单次失败全文降级；可能微数字与底表偏差 | `report_llm.py` 单次 `generate_report_insights` |
| **review_issue_labels source rule=2 vs llm=949** | 声称 hybrid 实际 99.8% LLM | DB 直接验证 |
| **【交叉验证补充】`METRIC_TOOLTIPS["风险分"]` 与 `_risk_products()` 实现严重不同步** | tooltip 显示给用户的旧公式（"低分×2 + 含图×1 + 严重度累加；仅计 ≤3 星"）与实际 5 因子加权完全不同；用户基于 tooltip 解读 32.6 分时会得到错误结论 | `report_common.py::METRIC_TOOLTIPS` vs `report_analytics.py:836-844` |
| **【交叉验证补充】产品概览差评率分母混用** | 风险产品 → `risk.negative_rate`（站点分母）；非风险/竞品 → 差评数 / 采集分母。同列双口径 | 实测 5 行验证（详见 4.2.2） |
| **【交叉验证补充】通知链路状态与 workflow 状态分裂** | outbox 全 deadletter 但 `workflow_runs.report_phase=full_sent`；运维和业务都看不到送达失败 | `notification_outbox.status` 实测 |
| **【交叉验证补充】`_parse_date_published()` vs `_backfill_date_published_parsed()` anchor 不一致** | 前者用当前日期、后者用 scraped_at 作 anchor；同一相对时间字符串走两条路径会落入不同月/年；本次 252/561=44.9% 评论受影响 | `models.py` 两处定义对比 |
| **【交叉验证补充】HTML 趋势模板 `row.values()` 顺序耦合** | 上游 dict 字段顺序变化即列值错位；隐性 bug | `daily_report_v3.html.j2` |
| **【交叉验证补充】trend_digest ready 状态嵌套矛盾** | 维度外层 `accumulating` 但内部 KPI `ready`；3 条样本仍被标 ready | `report_analytics.py` trend digest builder |
| **【交叉验证补充】`review_id + prompt_version` 复合 UNIQUE 在多 prompt 版本并存时会导致下游 1:1 假设破裂** | 当前 v2 单版本巧合 1:1，未来 v2→v3 升级期会双计数 | `models.py` review_analysis 表定义 |

### 6.4 优化建议

> ⚠ **本节经用户确认**：**保留单次 LLM 调用**，不拆分为多次以避免增加请求成本。改用"重试 + 数字断言后置校验"兜底。

1. **新增 `scrape_completeness_ratio = ingested / site_reported`**，<阈值告警，作为独立邮件
2. **统一并显式 3 类 negative 命名**：`rating_low_2star`、`rating_low_3star`、`sentiment_negative_llm`，KPI 卡只展示 1 种 + tooltip 说明
3. **risk_score 分母改为 ingested_only**（覆盖率不足时单独标 warning），不再隐藏 0 抓取产品
4. **LLM copy 保留 1 次调用**，但增加：
   - **重试**：解析失败 / JSON schema 不合时自动重试 N 次（指数退避）
   - **数字断言后置校验**：从 LLM 输出中抽取关键数字（health_index、风险分、差评率）与底表数据比对，偏差 > ε 时回退到模板 fallback
   - **prompt 内 instruction 化措辞冲突**：在 system prompt 中加 "若 health_index ≥ 90，hero_headline 不得使用『严重』『侵蚀』『重灾区』等强负面词；改用『仍存在结构性短板』" 等护栏
5. **failure_mode 在写入前过 LLM 归类映射** 到 6-8 个 enum
6. **`_underscore` 字段**统一移到 `analytics["__charts__"]` 子字典，明确"渲染辅助、非业务事实"
7. **【交叉验证补充】统一标签消费源**：定义"正式展示指标只消费 `analytics` 顶层字段和规范化表 `review_issue_labels`"为硬规则，加 CI 测试拦截"Excel/HTML 直读 `review_analysis.labels`"
8. **【交叉验证补充】tooltip-代码同步契约**：`METRIC_TOOLTIPS` 改为从代码注释（公式来源）自动派生，或建立 CI 检查（指标公式变更必须同步更新 tooltip 文本）
9. **【交叉验证补充】指标输出五元组化**：每个 KPI 输出 `value / display / numerator / denominator / window / source / confidence`，让 HTML/Excel 每格都能反查
10. **【交叉验证补充】风险分输出因子分解**：把 32.6 拆为 `neg_rate=0.65*0.35 + severity=0.71*0.25 + evidence=0.30*0.15 + recency=0.20*0.15 + volume=0.40*0.10`，让用户能看懂"为什么是 32.6 而不是 50"
11. **【交叉验证补充】trend_digest 加 `min_sample_size` 与 `confidence` 字段**：bootstrap / 低样本时强制降级为 `accumulating`，杜绝外层/内层状态分裂
12. **【交叉验证补充】通知链路状态回写 workflow**：outbox deadletter 时 `report_phase` 必须降级；新增独立"运维状态"卡，明确"报告生成完成 ≠ 报告送达"

---

## 7. 当前主要问题清单

### 7.1 数据结构问题

| # | 问题 |
|---|------|
| DS-1 | `review_analysis.labels(JSON)` 与 `review_issue_labels` 同时存在，重复且口径偶不一 |
| DS-2 | `failure_mode` 自由文本，39% 是"其他" |
| DS-3 | `reviews.date_published` 保留原始相对时间字符串，下游需重复处理 |
| DS-4 | `workflow_runs.scrape_quality` 是 TEXT JSON，难以查询趋势 |
| ~~DS-5~~ | ~~缺少 `review_analysis.review_id` UNIQUE 约束~~ → **已修正**：实测存在 `(review_id, prompt_version)` UNIQUE；真正问题是 prompt_version 多版本并存时下游 1:1 假设破裂 |
| DS-6 | `_heatmap_data / _trend_series` 等下划线"私有"字段进入持久化产物 |
| **DS-7【交叉验证】** | 缺少 `report_artifacts` 表：HTML 路径未入 `workflow_runs`，PDF 为空，产物追溯链断裂 |
| **DS-8【交叉验证】** | `product_snapshots` 未绑定 `workflow_run_id`，趋势点和 run 间接关联 |
| **DS-9【交叉验证】** | `reviews` 缺 `source_review_id`：316/561 标题为空时去重弱标识可靠性不足 |
| **DS-10【交叉验证】** | `reviews.date_published_parsed` 缺解析方式 / anchor / 置信度字段；`_parse_date_published()` 用当前日期、`_backfill_date_published_parsed()` 用 scraped_at，两路径 anchor 不一致 |
| **DS-11【二次互验 N4】** | `impact_category × failure_mode × label_code` 三字段语义层次未定义（5 enum × 258 自由文本 × 14 enum）；hierarchy / 平行视角关系不明，工程师不知该聚合哪个 |

### 7.2 指标设计问题

| # | 问题 |
|---|------|
| MT-1 | **【P0】"差评率"四种口径并用未声明**（≤2★ / ≤3★ / sentiment / severity） |
| MT-2 | **【P0】"competitive_gap_index" vs 维度内 "gap_rate" vs "catch_up_gap" / "fix_urgency"** 四个相关字段，无统一术语对照 |
| MT-3 | health_index 借用 NPS 名义但样本不是问卷应答，命名易误导 |
| MT-4 | risk_score 分母 `max(site, ingested)` 在 ingested=0 时静默隐藏风险 |
| MT-5 | high_risk_count 阈值 35 与 risk_products 实际显示阈值不一致（产品 32.6 仍在排行） |
| MT-6 | "duration_display 约 X 年" 概念上是评论池跨度，非"问题持续时长" |
| MT-7 | coverage_rate 只在全局展示，缺产品行级版本（产品 1=0%、产品 7=43%） |
| **MT-8【交叉验证 P0】** | **产品概览"差评率"列分母不统一**：风险产品用站点分母、非风险用采集分母，同列双口径 |
| **MT-9【交叉验证 P0】** | **`METRIC_TOOLTIPS["风险分"]` 与 `_risk_products()` 实际算法严重不同步**：tooltip 是旧公式（×2/×1 加和），代码已迁移到 5 因子加权 |
| **MT-10【交叉验证 P1】** | trend_digest `ready` 状态阈值过低 + 内外层状态嵌套矛盾（外 accumulating 内 ready；3 条样本 ready） |
| **MT-11【交叉验证 P1】** | risk_score 缺因子分解输出，无法解释 32.6 的来源 |
| **MT-12【交叉验证 P1】** | 接近高风险阈值预警缺失：`.75HP=32.6` vs 阈值 35，差 2.4 分但 KPI"高风险产品=0"，管理者会误判无紧迫性 |
| **MT-13【二次互验 N1 P1】** | products 维度 trend 在首日 1 次 scrape 下 3 个 view 全 inner=ready；inner KPI 阈值（"可比时间点 ≥ 1"）与 outer chart"图能不能画"判定逻辑不联动 |
| **MT-14【二次互验 N5 P1】** | trend ready 阈值无统计意义（实测样本 3 条即 ready）；建议至少样本 ≥ 30 + 时间点 ≥ 7 |

### 7.3 数据质量问题

| # | 问题 |
|---|------|
| DQ-1 | **【P0】SKU 1193465 站点 91 条 → 实际入库 0 条**，无任何告警 |
| DQ-2 | **【P0】scrape_quality 模块未检测"site_reported vs actual"评论数偏差** |
| DQ-3 | 99% 评论是历史补采，但 hero 数字"本次入库 561"误导 |
| DQ-4 | date_published 含相对时间（"a year ago"）解析精度低，trend 图含估算值；**【交叉验证】实测 252/561=44.9% 评论是相对时间表达** |
| DQ-5 | MAX_REVIEWS=200 截断了 .75HP（253 → 109，仅 43% 覆盖），未在产品行级警告 |
| DQ-6 | `review_issue_labels source` 名义 hybrid 但 99.8% LLM |
| DQ-7 | Excel 问题标签 997 数据行 vs DB 951 行，**根因已定位**：Excel 直读 `review_analysis.labels(JSON)`，含 `durability(8)` 未规范化 / `neutral(1)` 未翻译极性 |
| DQ-8 | Excel 评论明细"影响类别"列与"标签"列**实测 561/561 雷同**（应是 impact_category 但 query 未 select）|
| **DQ-9【交叉验证 P0】** | **Excel 评论明细"失效模式"列 561 行 100% 空**（DB `review_analysis.failure_mode` 561 条非空），实现 bug：`query_cumulative_data()` 未 select `ra.failure_mode` |
| **DQ-10【交叉验证 P1】** | **outbox 3 条全 `deadletter` / HTTP 401**：报告生成成功但通知送达全部失败，业务读者无法感知 |
| **DQ-11【交叉验证 P1】** | **316/561=56.3% 评论 headline 为空**：标题维度分析价值低；评论去重弱标识 `(product_id, author, headline, body_hash)` 在大量空标题下可靠性不足 |
| ~~DQ-12~~ | ~~**Excel 照片单元格 561 全空但工作簿嵌入 82 张 drawing 图片**：机器解析误判"无图"~~ → **【第六轮收口 撤回】**：用户明确保留 drawing 嵌入（视觉证据原样），不改 URL。机器解析需求由内部消费方自行处理（如改读 `reviews.images` JSON 字段），不影响用户 Excel 形态 |

### 7.4 展示表达问题

| # | 问题 |
|---|------|
| UI-1 | bootstrap 首日 12 个空趋势图占用大量版面 |
| UI-2 | hero_headline 措辞冲突（"96.2 健康优秀" + "严重侵蚀"） |
| UI-3 | "自有产品排行" 标题误导（实际仅展示有差评的 2/5 个） |
| UI-4 | KPI delta 全 flat，bootstrap 体验差 |
| UI-5 | Excel 趋势数据 sheet 单表混合 4+ 种结构，列复用造成稀疏 |
| UI-6 | 数字精度不一致（0.4464285714285715 vs 0） |
| UI-7 | 异常值表示混乱（·、空、0/0、—、N/A 并存） |
| UI-8 | Excel 缺失 HTML 顶部多个 KPI（健康指数、覆盖率、近 30 天） |
| **UI-9【交叉验证 P1】** | **HTML 总览"建议行动"标题被截断成半句话**（"针对 Walton's #22... 反馈的肉"），LLM 长 action 文本被当作短标题渲染 |
| **UI-10【交叉验证 P2】** | **邮件截图中出现实现说明式文案**（如"KPI 展示统一读取 analytics.kpis"），不适合业务读者 |
| **UI-11【交叉验证 P2】** | 竞品对标表缺分母、率、样本量、置信度和差距公式，专业判断不足 |
| **UI-12【交叉验证 P2】** | 趋势 sheet 同 sheet 内混合 `product_snapshots.scraped_at` 趋势 与 `date_published_parsed` 评论分布——两类时间轴含义不同，混用易误读 |

### 7.5 用户理解问题

| # | 问题 |
|---|------|
| UX-1 | tooltip 多为公式，缺"健康分 / 80 分对应"语义阈值 |
| UX-2 | "今日变化"在 bootstrap 期全部空状态仍占 4 个区块 |
| UX-3 | 竞品差评率 44.6% / 43.9% 在 KPI 区不可见 |
| UX-4 | 估算日期占比、覆盖率不足等"次级警示"被埋在文字里 |

### 7.6 数据链路问题

| # | 问题 |
|---|------|
| DL-1 | LLM 生成的 report_copy 未回写 DB |
| DL-2 | trend_digest 在 bootstrap 期与 cumulative 共用同源数据但状态各异，逻辑分支多易出 bug |
| DL-3 | notification_outbox / tasks.reply_to 双链路 + 空字符串 vs NULL 混用 |
| **DL-4【交叉验证】** | **DB `review_analysis.failure_mode / impact_category` 有值但 Excel 未输出**——典型"已生成但未透传"链路断点 |
| **DL-5【交叉验证】** | **Excel 问题标签 sheet 不消费规范化 `review_issue_labels`**——"标签同步"完成 ≠ "报告已使用同步结果"，链路无强制契约 |
| **DL-6【交叉验证】** | **HTML 全景数据使用 `snapshot.reviews`、Excel 使用 cumulative**：未来增量期窗口数据与累计数据并存时，二者口径可能漂移 |
| **DL-7【交叉验证】** | **HTML 趋势模板用 `row.values()` 顺序耦合**：上游字段顺序变化即列值错位，依赖 dict 插入顺序而非 columns key |
| **DL-8【交叉验证】** | **运维通知链路与 workflow 状态分裂**：outbox deadletter 不触发 workflow 状态降级，业务读者无感 |

### 7.7 实现方式问题

| # | 问题 |
|---|------|
| IM-1 | analytics.json 1.9MB 持久化（包含图表预渲染数据）跨日重复存储 |
| IM-2 | `taxonomy_version=v1` + `prompt_version=v2` 跨表语义版本未协同管理 |
| IM-3 | report_phase / report_mode / mode_display / perspective 4 个状态字段交叉，需 state machine 文档化 |
| **IM-4【交叉验证】** | **`METRIC_TOOLTIPS["风险分"]` 与 `_risk_products()` 算法严重不同步**：tooltip 仍是旧公式，tooltip 是用户唯一能看到的"指标定义"渠道 |
| **IM-5【交叉验证】** | **`_parse_date_published()` vs `_backfill_date_published_parsed()` anchor 不一致**：两条路径解析同一相对时间字符串结果不同，潜在长期数据正确性 bug |
| **IM-6【交叉验证】** | Excel 生成函数 `_generate_analytical_excel()` 中存在新旧版本覆盖痕迹（labels 双轨、impact_category 误填、失效模式漏 select），维护成本高 |
| **IM-7【交叉验证】** | 报告查询层（`query_report_data` / `query_cumulative_data`）没有统一字段契约，导致已有分析字段（failure_mode、impact_category）遗漏 |
| **IM-8【交叉验证】** | bootstrap 模式下部分模块仍按"成熟监控期"展示（趋势 ready / 接近高风险预警缺失），模板层和 analytics 层 ready / accumulating 职责边界需要更清晰 |
| **IM-9【二次互验 N2】** | `analytics.top_actions[]` 是迁移留下的死字段：永远 `[]`，HTML 实际渲染来自 `report_copy.improvement_priorities[]`（LLM 生成），无规则降级路径 |
| **IM-10【二次互验 N7】** | `improvement_priorities[].action` 字段双职责设计（卡片标题 + 段落正文同字段）是 HTML 截断 bug 的 schema 层根因；UI-9 仅是表象 |

> **注**：原"LLM 单次调用风险大"问题已根据用户决策从清单中移除，改以"重试 + 数字断言"兜底。

---

## 8. 优化建议（按优先级）

### 8.1 高优先级（必须修，<2 周内）

> ⚠ **前向引用**：本节 H1 / H8 / H13 等"在用户 HTML 加数据质量卡 / 通知状态条"的建议已被 **§11 用户视角再审视**收口为**内部运维频道**实施（用户无感）。涉及收口的建议在 §11.6 有明确决策表。**最终用户报告 UI 形态以 §11.3 为准**；本节剩余的"工程层 / 数据层"建议（H10 分母统一 / H11 tooltip / H14 short_title / H17 模板 / H19 enum 化 / H20 top_actions / H21 schema）继续有效。

| # | 建议 | 解决问题 | 预期价值 |
|---|------|---------|---------|
| H1 | 在 `scrape_quality.py` 增加 `missing_text_review_count = max(0, sum(products.review_count) − count(reviews))` 并设阈值告警；workflow_runs 抽出独立列 `scrape_completeness_ratio` | DQ-1, DQ-2 | 杜绝 0 抓取产品静默通过；让"采集事故"独立邮件 |
| H2 | 报告体系内统一术语：`rating_negative_2star_rate`、`sentiment_negative_rate`、`severity_high_rate` 三种口径并行命名；KPI 卡只展示一种 + tooltip 列出全部三个 | MT-1 | 消除"差评率"歧义 |
| H3 | hero "本次入库 561" 改为 "今日新增 3 + 历史补采 558"，前者作为大数字，后者作为说明色块；Excel 今日变化 sheet 把 estimated_dates / backfill_dominant 升级为红色 warning 行 | DQ-3 | 防止管理者误读 |
| H4 | bootstrap 模式下 HTML 折叠 12 个空趋势图区块，仅展示"截面诊断 + 数据质量 + LLM 洞察"三大块；模板按 `report_mode` 路由 layout | UI-1, UI-4 | 首日页面信噪比从 D 升至 B |
| H5 | issue_card 的"约 X 年 Y 个月"重命名为"评论时间跨度（首次—最近一次提及）"；或改为"高频期：YYYY-MM ~ YYYY-MM" | MT-6 | 消除"问题持续 8 年"误读 |
| H6 | risk_score 分母改为 `ingested_only`；当 coverage <50% 时附 `low_coverage_warning=true` 字段，UI 显示带 ⚠ 图标 | MT-4 | 让 SKU 1193465 这类产品风险显形 |
| H7 | Excel "产品概览" SKU 1193465 行标红 + "采集异常"列；"影响类别"列修复为真实 `impact_category` enum；统一 NA / 0 表示 | DQ-1, DQ-8, UI-7 | Excel 即时可信 |
| H8 | 顶部 KPI 增加"数据质量"卡（综合 coverage_rate + estimated_date_ratio + zero_scrape_count），<阈值变红 | UX-4 | 数据风险显性化 |
| H9 | LLM `generate_report_insights` 增加：① JSON schema 校验失败时**重试 N 次**（指数退避）；② 解析后做"数字断言"（health_index / 风险分 / 差评率 等关键数字与底表数据比对，偏差 > 1% 时回退到模板 fallback）；③ system prompt 内增加措辞护栏（health_index ≥ 90 时不得使用"严重"等强负面词） | UI-2 | **保留单次调用、降低成本**；同时杜绝幻觉数字与措辞冲突 |
| **H10【交叉验证 P0】** | **修复产品概览"差评率"列分母不统一**：要么拆为两列 `差评率(站点分母) / 差评率(采集分母)`，要么所有产品统一用同一口径（推荐采集分母 = `risk.negative_rate` 改为 `neg / ingested`）；HTML 风险榜同步对齐 | MT-8, DQ-9 同源 | 杜绝排序与决策被错口径误导 |
| **H11【交叉验证 P0】** | **修复 `METRIC_TOOLTIPS["风险分"]` 文案与 `_risk_products()` 算法对齐**：把 tooltip 改为"5 因子加权（差评率 35% + 严重度 25% + 图证 15% + 近期度 15% + 显著性 10%），≥35 为高风险"；同时输出因子分解 JSON 供前端 hover 展开 | MT-9, IM-4 | 用户能看懂 32.6 的来源 |
| **H12【交叉验证 P0】** | **修复 Excel `query_cumulative_data()` SELECT 语句**：补 `ra.impact_category, ra.failure_mode`；评论明细列分别透传；同时把 Excel "问题标签" sheet 改为消费 `review_issue_labels` 规范化表 | DQ-7, DQ-8, DQ-9, DL-4, DL-5 | 不再浪费已有 LLM 分析资产；消除双轨标签 |
| **H13【交叉验证 P1】** | **运维通知链路状态回写**：outbox deadletter 时 `workflow_runs.report_phase` 必须降级为 `full_sent_local`（仅本地 artifact 完成），bridge 真送达才升 `full_sent_remote`；HTML 顶部数据质量卡新增"通知状态"小标 | DQ-10, DL-8 | 业务和运维能感知"报告未送达" |
| **H14【交叉验证 P1 / 二次互验根因升级】** | **修复 HTML "建议行动"标题截断 — schema 层根治**：拆 `improvement_priorities[]` 为 `short_title`（≤20 字 LLM 输出）+ `full_action`（段落级 LLM 输出）+ `evidence_review_ids[]`（顺带补证据回链 deep-link）；prompt 内强制要求三字段；模板用 short 作标题、full 作展开 | UI-9, IM-10 | 消除半句话标题 + 解决 schema 双职责 + 补 M9 证据回链 |
| **H15【交叉验证 P1】** | **统一相对时间解析 anchor**：废弃 `_parse_date_published()` 用当前日期为 anchor 的路径；所有相对时间统一以 `scraped_at` 为 anchor；reviews 表新增 `date_parse_method / date_parse_anchor / date_parse_confidence` | DS-10, IM-5 | 杜绝同字符串两路径结果不一致 |
| **H16【交叉验证 P1 / 二次互验加严】** | **trend_digest 状态联动 + 阈值升级**：（1）outer 与 inner status 必须同源——同一 panel 不允许出现 outer accumulating + inner ready；（2）阈值从"可比时间点 ≥ 1"升级到 **"样本量 ≥ 30 且时间点 ≥ 7"** 才允许 ready；不达阈值强制 `accumulating_with_preview`，附置信度水印；（3）products 维度首日仅 1 次 scrape 时禁止任何 ready | MT-10, MT-13, MT-14, IM-8 | 杜绝外内嵌套矛盾 + 杜绝 3 条样本被标 ready |
| **H17【交叉验证 P1】** | **HTML 趋势表模板改为按 `columns` key 输出**：用 `{% for col in columns %}{{ row[col] }}{% endfor %}` 替代 `row.values()` | DL-7 | 消除字段顺序耦合隐患 |
| **H18【交叉验证 P1】** | **接近高风险阈值预警**：增加 `near_high_risk_count = COUNT(0.85*HIGH_RISK ≤ risk_score < HIGH_RISK)`，KPI 卡显示 "高风险 0 / 接近 1"，让 .75HP=32.6 这种"差 2.4 分"被显化 | MT-12 | 管理者不被"高风险=0"误导 |
| **H19【二次互验 P1】** | **`failure_mode` 改为 enum**：在 LLM prompt 中要求输出 `failure_mode ∈ {无 \| 齿轮失效 \| 电机异常 \| 壳体/装配 \| 密封漏液 \| 控制电气 \| 表面材料 \| 噪音 \| 其他}` 9 类 enum，原始自由文本保留 `failure_mode_raw`；同时 LLM 对 positive sentiment 强制写 `无` 而非各种"无"变体，杜绝 64.9% 占位词污染 | DS-2, DS-11 | failure_mode 字段从 0 可用性升级为可聚合 |
| **H20【二次互验 P1】** | **激活或删除 `top_actions[]` 死字段**：（A 推荐）在 `report_analytics.py` 中由规则逻辑（`risk_score ≥ 阈值 + evidence_count ≥ N`）生成 `top_actions`，作为 LLM `improvement_priorities` 失败的降级路径；HTML 模板优先 LLM、兜底规则；（B 备选）从 schema 删除并清理 analytics.json 字段 | IM-9 | 消除迁移死字段 + 提供 LLM 失败降级路径 |
| **H21【二次互验 P1】** | **三字段语义层次声明**：在 schema/文档明确 `impact_category`（影响维度，5 enum）→ `failure_mode`（具体失效，9 enum 后）→ `label_code`（用户主题，14 enum）三层 hierarchy 关系；定义合法交叉表（如 `impact_category=safety` 不能配 `label_code=good_value`） | DS-11 | 工程师能清晰判断该聚合哪个维度 |

### 8.2 中优先级（2-6 周）

| # | 建议 | 解决问题 |
|---|------|---------|
| M1 | failure_mode 改为 enum + raw 双字段，写入前 LLM 归类化 | DS-2 |
| M2 | competitor 也跑 risk_score 和 issue_cards，HTML 增加"竞品风险产品"卡 | UX-3 |
| M3 | 行级覆盖率：每产品行展示"采集 / 站点 = 43%"小标 | DQ-5, MT-7 |
| M4 | Excel "趋势数据" sheet 拆为 4 个独立 sheet | UI-5 |
| M5 | 评论明细 `照片` 列改 hyperlink；移除"影响类别"或填真实 enum | DQ-8 |
| M6 | review_analysis.labels JSON 列标 deprecated；所有聚合走 review_issue_labels | DS-1 |
| M7 | tooltip 增加"健康分语义阈值"（≥85 健康，70-85 关注，<70 风险） | UX-1 |
| M8 | `competitive_gap_index` 与维度 `gap_rate / catch_up_gap / fix_urgency` 加术语对照表（HTML 报告底部 + 独立 wiki 页） | MT-2 |
| M9 | report_copy 生成后**回写 `workflow_runs.report_copy_json` 列**；分析师后续可 SQL 直接读 | DL-1 |
| **M10【交叉验证】** | 建立 `report_artifacts` 表：`run_id, artifact_type, path, hash, template_version, generator_version, created_at`；HTML/PDF/邮件正文都入库 | DS-7 |
| **M11【交叉验证】** | 建立最小版 `metric_definitions` 字典表：每指标 `key, formula, numerator_source, denominator_source, window, confidence_rule`；HTML/Excel 每格可反查 | MT-2, IM-4 |
| **M12【交叉验证】** | `product_snapshots` 增加 `workflow_run_id` 外键，让趋势点可重放到具体 run | DS-8 |
| **M13【交叉验证】** | `reviews` 增加 `source_review_id` 字段（站点原始评论 ID），消除空标题去重弱标识隐患 | DS-9, DQ-11 |
| **M14【交叉验证】** | Excel "趋势数据" sheet 拆为"产品快照趋势"和"评论发布时间分布"两个独立 sheet，时间轴含义不混 | UI-12 |
| **M15【交叉验证】** | Excel 新增"指标说明"和"数据质量"两个 sheet，把 metric_definitions 字典 + 报告级风险随报表交付 | DL-4, DL-5 |

### 8.3 低优先级（>6 周或随版本演进）

| # | 建议 | 解决问题 |
|---|------|---------|
| L1 | analytics.json 中 `_underscore` 字段独立到 `__charts__`；reduce 持久化体积 | DS-6, IM-1 |
| L2 | review_analysis 加 UNIQUE(review_id)；reviews FK 加 ON DELETE CASCADE | DS-5 |
| L3 | review_issue_labels source 重命名为 `pipeline`（llm/rule/manual）；加权 hybrid 时记录组合权重 | DQ-6 |
| L4 | health_index 命名改为 `voice_of_customer_score` 或 `vo_c_index`，与 NPS 解耦 | MT-3 |
| L5 | report_phase / report_mode / mode_display 文档化 state machine | IM-3 |
| L6 | `taxonomy_version` × `prompt_version` × `service_version` 协同矩阵文档（哪些组合兼容） | IM-2 |
| ~~L7~~ | ~~Excel 评论明细照片列同时保留 URL + 嵌入图，避免机器解析误判~~ → **【第六轮收口 撤回】**：用户明确保留 drawing 嵌入，不动 | DQ-12 |
| **L8【交叉验证】** | Excel 增加冻结窗格、自动筛选、按归属/风险/有图筛选；561 全景 sheet 浏览效率提升 | — |
| ~~L9~~ | ~~角色化 Excel 导出：`*_管理者.xlsx` / `*_产品改良.xlsx` / `*_设计.xlsx`~~ **已撤回**（见 §11.10）：用户反对——维护成本 3 套生成链路 + 收件人矩阵；附件命名歧义；Excel 本质是分析师工具，角色分类无意义。**替代方案**：单一 Excel + 4 sheets（核心数据 / 现在该做什么 / 评论原文 / 竞品启示），需要的人按 sheet 找 | — |
| **L10【交叉验证】** | 邮件正文清理实现说明式文案（"统一读取 analytics.kpis"等技术语）；改为业务化复述 | UI-10 |

---

## 9. 更优实现方案（部分关键改进）

### 9.1 数据质量自检体系（替代当前 scrape_quality）

```text
新增 workflow_runs 列：
  scrape_completeness_ratio  REAL   -- ingested / SUM(products.review_count)
  zero_scrape_skus           TEXT   -- JSON list, ingested=0 但 site>0
  low_coverage_skus          TEXT   -- JSON list, coverage < 50%
  estimated_date_ratio       REAL   -- date_published_estimated=true 的比例

告警规则（独立邮件 / 钉钉）：
  - zero_scrape_skus 非空                   → P0
  - scrape_completeness_ratio < 0.6         → P1
  - estimated_date_ratio > 0.3              → P2 (趋势图精度告警)
```

### 9.1.5 【交叉验证补充】指标五元组化与产物 artifact 表

```text
所有 KPI 输出 7 元组（替代当前裸 value）：
  {
    metric_key: "own_negative_review_rate",
    value: 0.024,
    display: "2.4%",
    numerator: 10,
    denominator: 418,
    window: "cumulative",
    source: "reviews WHERE ownership='own' AND rating<=2",
    confidence: "high"
  }

新增 report_artifacts 表（让 HTML 也可追溯）：
  CREATE TABLE report_artifacts (
    id INTEGER PRIMARY KEY,
    run_id INTEGER FK -> workflow_runs(id),
    artifact_type TEXT CHECK(artifact_type IN ('html','xlsx','pdf','snapshot','analytics','email')),
    path TEXT NOT NULL,
    hash TEXT,
    template_version TEXT,
    generator_version TEXT,
    bytes INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  );

新增 metric_definitions 字典表：
  CREATE TABLE metric_definitions (
    metric_key TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    formula TEXT NOT NULL,
    numerator_source TEXT,
    denominator_source TEXT,
    window TEXT,
    confidence_rule TEXT,
    tooltip_zh TEXT,
    code_ref TEXT,                 -- 'report_analytics.py:836-844'
    last_synced_at TIMESTAMP
  );
  -- CI 检查：报告生成前比对 METRIC_TOOLTIPS 与 metric_definitions.tooltip_zh
```

### 9.2 指标体系重构（差评率统一）

```text
KPI 卡只用 1 种核心口径 + 副指标：
  「差评率(评分)」 = ≤2★ / total                            ← 核心，硬指标
  「负面情感占比」 = sentiment=negative / total              ← 副，反映 LLM 判读
  「高严重度占比」 = severity=high labels / total reviews     ← 副，反映重大问题密度

KPI 卡展示其一，tooltip 同时显示三个数值与差异说明。
"差评率" 从 metric 名 → 改为 KPI 卡 label，公式标在 tooltip。
```

【交叉验证补充】产品概览"差评率"列分母统一方案（解决 H10）：

```text
方案 A（推荐）：拆为两列，列名显式声明分母
  | 产品                | 差评率(采集分母) | 差评率(站点分母) |
  | .75 HP Grinder #12  | 8.26% (9/109)   | 3.56% (9/253)    |
  | Cabela's Stuffer    | 44.64% (25/56)  | 31.25% (25/80)   |

方案 B：单列统一用采集分母（更保守、更可比）
  - 风险产品的 risk.negative_rate 改为 neg / ingested
  - HTML 风险榜同步对齐
  - 影响：自有 .75HP 差评率从 3.56% → 8.26%（更悲观、但与竞品同口径）
```

### 9.3 Bootstrap 期专用版面

```text
HTML by report_mode:
  bootstrap → [hero截面] + [issue_cards 8 张] + [risk_products]
              + [data_quality_panel] + [appendix]
  full      → 当前完整版（含 12 个趋势图）
  change    → 当前 change-only 版
  quiet     → 单一句"无变化" + 数据质量小卡
```

### 9.4 LLM Copy 生成（保留单次调用，加重试与断言）

> ⚠ **决策已确认**：**不拆分为 5 次调用**（成本考虑）。改为：

```python
# 单次 prompt 生成 5 段（与现状一致），增加重试与后置校验
for attempt in range(MAX_RETRIES):
    try:
        copy_json = llm_call(build_insights_prompt(kpis, clusters, gap, ...))
        copy = parse_and_validate_schema(copy_json)  # JSON schema 校验

        # 数字断言：抽取 LLM 输出中的关键数字与底表比对
        assert_consistency(copy.hero_headline, kpis,
                           keys=["health_index", "own_negative_rate"])
        assert_consistency(copy.executive_bullets, kpis + risk_products)

        # 措辞护栏后置校验（system prompt 内已 instruction 化）
        validate_tone_guards(copy, kpis)
        break
    except (SchemaError, AssertionError, ToneGuardError) as e:
        log.warning(f"LLM copy attempt {attempt} failed: {e}")
        if attempt == MAX_RETRIES - 1:
            copy = template_fallback(kpis, clusters)  # 模板兜底
```

**system prompt 内的措辞护栏示例**（写在原 prompt 里，不增加调用次数）：

```text
措辞规则（必须遵守）：
1. 若 health_index ≥ 90，hero_headline 禁止使用"严重"/"侵蚀"/"重灾区"
   等强负面词；改用"仍存在结构性短板"/"局部需要关注"等温和措辞
2. executive_bullets 中的所有数字必须能在 kpis / risk_products 中找到
   原始来源；不得自行计算或外推
3. 若 high_risk_count = 0，禁止使用"高风险产品"作为主语
```

### 9.5 ~~角色分层视图~~（**已撤回**，见 §11.10）

> ⚠ **撤回**：第四轮 review 中用户明确反对"分角色 tabs"，理由：维护成本（4 套 layout）+ 用户认知摩擦（先选身份再读）+ 标签即偏见（硬分类无视实际工作场景）。**正确解法是单一报告 + 信息层次按"决策深度"分层**——管理者天然停在顶部 KPI/Hero，产品改良/设计天然停在中段 issue cards，分析师天然下钻到 Excel。详见 §11.10。

```text
[已撤回] HTML 顶部 tabs:
  「管理者视图」/「产品改良视图」/「设计视图」/「数据视图」
```

### 9.6 数据库优化 SQL

```sql
-- 唯一约束
ALTER TABLE review_analysis ADD CONSTRAINT uq_review UNIQUE(review_id);

-- 解析置信度字段
ALTER TABLE reviews ADD COLUMN date_published_estimated INTEGER DEFAULT 0;
ALTER TABLE reviews ADD COLUMN date_published_confidence REAL;

-- 产品行级采集质量
ALTER TABLE products ADD COLUMN last_scrape_completeness REAL;
ALTER TABLE products ADD COLUMN last_scrape_warnings TEXT;  -- JSON array

-- workflow_runs 提取核心质量字段
ALTER TABLE workflow_runs ADD COLUMN scrape_completeness_ratio REAL;
ALTER TABLE workflow_runs ADD COLUMN zero_scrape_count INTEGER;

-- LLM copy 回写
ALTER TABLE workflow_runs ADD COLUMN report_copy_json TEXT;

-- 索引
CREATE INDEX idx_reviews_published_parsed ON reviews(date_published_parsed);
CREATE INDEX idx_labels_polarity_severity
  ON review_issue_labels(label_polarity, severity);
```

---

## 10. 收尾说明

### 10.1 风险点与未验证项

- ⚠ `failure_mode` 中文乱码：**原始 JSON 是 UTF-8 正常**，控制台展示是 Windows 终端编码原因，**非数据问题**
- ✓ Excel "问题标签" 997 vs DB 951 偏差：**【交叉验证已定位】**Excel 直读 `review_analysis.labels(JSON)`，含 `durability(8)` 未规范化与 `neutral(1)` 极性
- ✓ Excel "影响类别" 列与"标签"列雷同：**【交叉验证已确认】**实测 561/561 完全雷同；根因 `query_cumulative_data()` 未 select `ra.impact_category`
- ✓ Excel "失效模式" 列：**【交叉验证已确认】**561 行 100% 空（DB 有 561 条非空），同根因
- ⚠ HTML 评论明细嵌入完整度：HTML 367KB 看不像全部 561 条全嵌，需确认是否分页或 sample
- ⚠ **【交叉验证补充】HTML 总览"建议行动"标题截断**：本审计未在 HTML diff 中精确指出截断起止位置，但 Codex 报告与我的 grep 结果都包含该 80 字截断字符串，根因需在 `daily_report_v3.html.j2` 模板中确认 `improvement_priorities[].action` 渲染逻辑
- ⚠ **【交叉验证补充】`_parse_date_published()` vs `_backfill_date_published_parsed()` anchor 不一致**：本审计未在 `models.py` 内逐行核对两处 anchor 写法，但 Codex 报告明确指出，建议作为 P1 实现项独立验证修复
- ⚠ **【交叉验证补充】HTML 趋势模板 `row.values()` 顺序耦合**：本审计未直接打开 `daily_report_v3.html.j2` 验证，建议作为 P1 实现项独立验证修复

### 10.2 已确认的设计决策

| 项 | 决策 | 备注 |
|----|------|------|
| LLM `generate_report_insights` 是否拆为多次调用 | **否** | 用户确认：保持单次调用以控制成本，改用"重试 + 数字断言 + 措辞护栏"兜底 |

### 10.2.1 与 Codex 独立审查的交叉验证总结（2026-04-27 增量）

**已合入的 Codex 关键发现（按价值排序）**：

| # | Codex 发现 | 严重度 | 验证状态 | 落地章节 |
|---|----------|-------|---------|---------|
| 1 | 产品概览"差评率"列分母不统一（风险用站点 / 非风险用采集） | P0 | ✓ openpyxl 实测 | 1.3, 4.2.2, MT-8, H10 |
| 2 | `METRIC_TOOLTIPS["风险分"]` 与 `_risk_products()` 算法不同步 | P0 | 文档证据 | 1.3, 6.3, MT-9, IM-4, H11 |
| 3 | Excel 失效模式列 561 行 100% 空（DB 有数据） | P0 | ✓ openpyxl 实测 | 4.2.1, DQ-9, H12 |
| 4 | outbox 3 条全 deadletter / HTTP 401，workflow 仍 completed | P1 | ✓ SQL 实测 | 1.3, 6.3, DQ-10, DL-8, H13 |
| 5 | HTML "建议行动" 标题被截断成半句话 | P1 | grep 间接证据 | 3.2.3, UI-9, H14 |
| 6 | `_parse_date_published()` vs `_backfill_date_published_parsed()` anchor 不一致 | P1 | 文档证据 | 2.3, 6.3, DS-10, IM-5, H15 |
| 7 | trend_digest ready 状态嵌套矛盾（外 accumulating 内 ready） | P1 | 间接证据 | 3.2.5, 6.3, MT-10, H16 |
| 8 | HTML 趋势模板 `row.values()` 顺序耦合 | P1 | 文档证据 | 3.2.5, DL-7, H17 |
| 9 | 问题标签 sheet 含 `durability`(8) + `neutral`(1) 未规范化值（直读 LLM JSON） | P2 | ✓ openpyxl 实测 | 4.2.4, DQ-7, H12 |
| 10 | 252/561=44.9% 评论是相对时间表达 | 量化补强 | ✓ SQL 实测 | DQ-4 |
| 11 | 316/561=56.3% 评论 headline 为空 | 量化补强 | ✓ SQL 实测 | DQ-11 |
| 12 | Excel 照片列空但工作簿嵌入 82 张图片 | P2 | 文档证据 | 1.3, DQ-12, L7 |
| 13 | 邮件正文出现实现说明式文案 | P2 | 文档证据 | UI-10, L10 |
| 14 | 缺少 report_artifacts 表（HTML 路径不入 DB / pdf_path 空） | 中 | ✓ SQL 实测 | DS-7, M10 |
| 15 | review_analysis 已有 `(review_id, prompt_version)` UNIQUE | **修正初稿** | ✓ sqlite_master 验证 | DS-5 |
| 16 | product_snapshots 未绑定 run_id；reviews 缺 source_review_id | 中 | 文档证据 | DS-8, DS-9, M12, M13 |

**初稿误判的纠正**：
- ❌ "review_analysis 缺 UNIQUE 约束" → ✓ 已存在 `(review_id, prompt_version)` UNIQUE
- ❌ "Excel 失效模式列对部分负面评论显示中文短语" → ✓ 561 行 100% 空（误把 DB 字段值当 Excel 列内容）

**Codex 未涉及而本审计独有的洞察**（保留作为本文核心论点）：
- 多种"差评率"语义口径并存（≤2★ vs ≤3★ vs sentiment vs severity）— 见 MT-1, 6.4-§2
- failure_mode 39% 是"其他"即使有数据也聚合价值低 — 见 DS-2
- review_issue_labels source rule=2/llm=949 名义 hybrid 实际 99.8% LLM — 见 DQ-6
- duration_display "8 年" 被读为问题持续时长 — 见 MT-6, H5
- top_actions=[] + 全部 KPI delta-flat 在 bootstrap 期管理视角问题 — 见 UI-4
- LLM 单次调用 vs 多次调用的成本权衡（保留单次 + 重试 + 断言 + 护栏）— 见 9.4, H9
- health_index 借用 NPS 名义但样本不是问卷应答的命名误导 — 见 MT-3, L4
- hero_headline `"96.2 健康优秀 + 严重侵蚀"` 措辞自洽性问题 — 见 UI-2

**两份审查融合后**：从 35 项问题 → 65 项；从 24 条建议 → 45+ 条；P0 关键问题从 5 项扩展到 9 项，覆盖**实现层 bug 定位**（Codex 强项）+ **指标语义 / 角色价值层**（本审计强项）。

### 10.2.2 二次互验元洞察（AI 审计的 canary 信号）

本次合并经历了两轮 AI 互验：

**第一轮**：Claude（本审计）+ Codex（独立审查）→ 各自发现的 P0/P1 互补合入。

**第二轮**：Codex 阅读 Claude 合入版后回校三处具体数据：

| # | Claude 第一轮判断 | Codex 第二轮校正 | Claude 第二轮实测 | 最终结论 |
|---|------------------|----------------|------------------|---------|
| 1 | trend "全部 status=accumulating" | "实际 4 ready / 8 accumulating" | **4 ready outer / 7 ready inner / 3 panel 外内不一致** | 三轮才统一 |
| 2 | "top_actions=[] 等同无建议" | "HTML 实际有 3 个 action-title，来自 improvement_priorities" | top_actions 是迁移死字段；improvement_priorities 单职责 schema 是 UI 截断真根因 | 修正 + 升级 |
| 3 | "failure_mode 39% 是其他" | "实测'无'=220 / 同类合并 363/561" | **258 唯一值 / 364 = 64.9% 无类污染 / positive 100% 被填占位词** | Codex 方向对，问题更严重 |

**元洞察 N6**：
- trend_digest 的 status 字段连两个独立 AI 审计都得迭代 2 轮才能统一结论。如果"AI 审计员各看出不同结论"，**业务用户更不可能判断**。
- 这是一个强信号：**当前 `trend_digest.status` 字段复杂度本身已超出"展示性指标"应有的认知负荷**。
- 建议简化为单一 enum + 置信度评分，并在 panel 上强制显示样本数 N：

```text
trend_status ∈ {
  accumulating       // 样本不足（< 30 或时间点 < 7），不绘制趋势线
  ready_with_warning // 满足 ready 但 estimated_date_ratio > 30%
  ready              // 完全可信
}
display: "ready (N=109, conf=high)" 或 "accumulating (N=3)"
```

**元洞察 N6 衍生建议**：把"trend status 字段简化"列入 H16 子项，作为长期 schema 治理目标。当任意两个独立审计员（人或 AI）对一个字段的解读出现分歧时，应把这视作**用户体验 canary**，触发该字段的简化重构。

### 10.3 结论

当前报告体系已具备 **B+ 级别"AI 评论智能分析"能力**，但要达到"可信生产仪表盘"还需补齐（**已合并 Codex 交叉验证补充**）：

1. **数据质量自检**（H1, H6, H7, H8）
2. **统一负面口径**（H2）+ **统一差评率分母**（H10）
3. **Bootstrap 期版面**（H4）+ **趋势状态联动**（H16）
4. **Excel/HTML 角色分层**（M2-M5, M14, M15）
5. **LLM 输出兜底**（H9，单次调用 + 重试 + 断言）+ **建议行动文案双字段**（H14）
6. **【交叉验证补充】实现层 bug 修复**（H10 分母 / H11 tooltip / H12 Excel query / H17 模板 / H15 anchor）
7. **【交叉验证补充】运维链路状态可见**（H13）+ **接近高风险预警**（H18）

**优先级排序后修 H1-H21 即可在 2-3 周内消除主要 P0/P1 问题**。其中 H1-H9 是初稿建议（侧重指标语义和数据质量），**H10-H18 是 Codex 交叉验证后新增**（侧重实现 bug 定位和工程债务），**H19-H21 是二次互验后新增**（failure_mode enum 化 / top_actions 死字段处置 / 三字段语义层次声明）。三部分互补后，生产报告才能从"AI 撰写的可读分析稿"真正升级为"可信、可比、可决策、可送达、可追溯、可聚合分析的运营仪表盘"。

---

---

## 11. 用户视角再审视（2026-04-27 第三轮收口 — **覆盖前章 UI 建议**）

> **背景**：前 10 章在两轮 AI 互验后形成了完整的"工程视角问题清单"，但混入了大量本应属于**内部运维**的信号（数据质量、通知失败、采集覆盖率、tooltip 与代码漂移、top_actions 死字段、三字段 schema 等）。用户在第三轮 review 时指出：**这些内容不应该出现在用户报告里**——用户（产品改良 / 设计 / 管理）只关心"我能从中获得什么决策依据"。
>
> **本章原则**：**报告产物分两个频道**——用户报告（HTML/Excel/邮件）只放用户能立即理解并采取行动的信息；运维信号、schema 债务、口径修复等全部移到独立的内部运维通道。本章的设计决策**优先级高于第 §3.4 / §4.5 / §8 章的 UI 类建议**——后两者中标记为"用户报告 UI 改造"的项被本章**收口或撤回**。

### 11.1 频道分离原则

| 频道 | 受众 | 内容 | 触发条件 |
|------|------|------|---------|
| **用户报告**（HTML+Excel+邮件） | 老板 / 产品 / 设计 | "我能从中获得什么决策依据" | 每日定时 |
| **内部运维告警**（独立邮件 / 钉钉运维群） | 开发 / 运维 | scrape_quality 自检失败、SKU 0 抓取、outbox deadletter、相对日期占比、覆盖率不足、tooltip-代码漂移 CI 警报、top_actions 死字段、三字段 schema 债务等 | 阈值触发，不必每日 |

**关键判定**：SKU 1193465 抓取 0 条、outbox 401、44.9% 估算日期、64% 覆盖率、scrape_quality 漏检——**这些是工程团队的事**，老板看到只会困惑"这跟我什么关系？"，应**完全从用户报告中移除**。

### 11.2 用户视角元素审视清单（HTML）

每个元素经"老板 3 秒能看懂吗？能告诉他下一步做什么吗？"双重测试：

| 当前元素 | 3 秒能懂？ | 决策有用？ | 决定 |
|---------|----------|----------|------|
| 健康指数 96.2 | ❌（NPS 公式不懂） | ⚠ | **保留+改语义**：`🟢 总体口碑 优秀 (96.2)` 四档红黄绿灯 |
| 差评率 2.4% | ⚠（分母不明） | ✓ | **保留**，tooltip 写 "≤2 星 / 自有评论" |
| 累计自有评论 418 | ❌ | ❌ | **删除**或并入副标题 |
| 好评率 94.7% | ✓ | ✓ | **保留** |
| 高风险产品 0 | ❌（阈值 35 不懂） | ⚠ | **改为**"需关注产品 1 个"（数字直接、去阈值） |
| 总体竞品差距指数 4 | ❌ | ❌ | **删除** |
| 样本覆盖率 64% | ❌ | ❌ | **删除**（移内部运维） |
| 评论范围 4 张卡（累计/本次/近30天） | ❌ | ❌ | **简化**为副标题一行："本期: 自有 5 款 / 竞品 3 款 / 共 561 条评论" |
| Hero 一句话 | ✓ | ✓ | **保留**+ 措辞护栏（H9 仍有效） |
| 3 条 executive_bullets | ✓ | ✓ | **保留**+ 数字校验 |
| 今日变化 4 区块（首日全空） | ❌ | ❌ | **删除**（首日不展示，正常运行后才上） |
| 变化趋势 12 panel | ❌（老板看不完） | ❌ | **简化**为 1 张总趋势图 + 折叠详情；首日完全折叠 |
| 问题诊断 8 张卡 | ⚠（太多） | ✓ | **首屏只显示 Top 3**，其余折叠 |
| `duration_display "约 8 年"` | ❌（严重误导） | ❌ | **改为"问题持续被反馈"或移除** |
| 自有产品排行 risk_score=32.6 | ❌（数字不懂） | ⚠ | **改为**🟢 健康 / 🟡 需关注 / ⚪ 无数据 三档 + 一句原因 |
| 竞品对标 gap_rate=13 | ❌ | ❌ | **替换为**"我们能借鉴 3 件 / 竞品的明显短板 3 件"双名单 |
| 全景数据嵌入 561 评论 | ❌（太多） | ❌ | **移 Excel**，HTML 仅留链接 |
| 数据质量卡 / 通知状态 / 估算日期占比 | ❌ | ❌ | **全部移内部运维频道**（撤回 H1/H8/H13 中"在 HTML 加卡"的部分） |
| top_actions 死字段 / 三字段 schema | — | — | **不在 UI 露出**（属内部修复，不在用户报告） |

### 11.3 用户视角 HTML 终稿结构

> ⚠ **范围澄清（2026-04-27 第四轮）**：本节早期版本未区分"邮件正文 HTML"和"附件 HTML 报告"两类产物，误把单一 mock 套到所有 HTML 上。**本节 mock 的密度对应邮件正文（30-60 秒决策）**；**附件 HTML 报告应保留更多深度**（全 8 issue cards / 完整 example_reviews / 完整 5 行动建议 / 详细产品因子分解）。两者的精确边界与各自的"删除/改写/保留"清单见 §11.9。


```
┌──────────────────────────────────────────────────┐
│ QBU 评论分析报告 · 2026-04-26                    │
│ 本期: 自有 5 款 · 竞品 3 款 · 共 561 条评论       │
├──────────────────────────────────────────────────┤
│ 🟢 总体口碑   优秀 (96.2)                         │
│ 🟢 好评率     94.7%                               │
│ 🟡 差评率     2.4%   (1-2 星 / 自有评论)          │
│ 🟡 需关注产品  1 个   (.75 HP Grinder)            │
├──────────────────────────────────────────────────┤
│ 关键判断 (Hero 一句话 + 3 条 bullets)              │
├──────────────────────────────────────────────────┤
│ 现在该做什么 (Top 3 + 折叠剩余)                    │
│   1. [结构设计] 肉饼厚度不可调  影响 3 款 [详情▼]  │
│   2. [售后履约] 开关失灵+客服失联 影响 1 款 [详情▼] │
│   3. [质量稳定] 金属碎屑+材料剥落 影响 2 款 [详情▼] │
│   [查看全部 5 项 →]                                │
├──────────────────────────────────────────────────┤
│ 自有产品状态 (5 行 + 灯 + 一句原因)                │
├──────────────────────────────────────────────────┤
│ 竞品启示                                           │
│   ┌─ 我们能借鉴竞品什么 (3 条)                    │
│   └─ 竞品的明显短板 (3 条)                        │
├──────────────────────────────────────────────────┤
│ 全部评论明细 → 见 Excel 附件                      │
└──────────────────────────────────────────────────┘
```

**对比初稿（10 大章节）→ 用户视角终稿（5 大章节）**：

- 删除：`今日变化`、`变化趋势`（首日）、`样本覆盖率`、`总体竞品差距指数`、`累计评论数`、`数据质量`、`通知状态` 等所有"工程视角"内容
- 重写：`自有产品排行` → `自有产品状态` 三档灯；`竞品对标` → `竞品启示` 双名单
- 折叠：`问题诊断` 从 8 张默认全开 → Top 3 默认 + 全部折叠
- 保留：`Hero / executive_bullets / 现在该做什么 / 自有产品状态 / 竞品启示`

### 11.4 用户视角 Excel 终稿（5 sheets → 4 sheets）

| Sheet | 受众 | 内容 |
|-------|------|------|
| **核心数据** | 所有人 | 8 产品一目了然：名称 / 归属 / 当前评分 / 差评数 / 状态灯 / 主要问题（一句话） |
| **现在该做什么** | 产品改良 | Top N 行动：问题 / 影响产品 / 用户原话 / 改良方向（**不展示** risk_score、evidence_count、label_code 英文） |
| **评论原文** | 设计 / 改良 | 561 条：产品 / 评分 / 中文翻译 / 用户原文 / **图片 drawing 嵌入（保留视觉证据原样，第六轮决策）** |
| **竞品启示** | 产品 / 营销 | 竞品好评 Top 3 主题 + 竞品差评 Top 3 主题 |

**删除的 sheets**（撤回前章建议）：
- ~~问题标签 sheet~~（998 行 label_code 英文，用户读不懂） — 撤回 H12 中"改 sheet 数据源"的实施，但内部仍消费规范化表
- ~~趋势数据 sheet~~（首日全空，603 行混杂） — 撤回 §4.5 中"拆 4 sheet" 建议；正常运行 30 天后再决定
- ~~指标说明 sheet~~（用户不关心公式） — **撤回** §4.5 / M11
- ~~数据质量 sheet~~（用户不关心采集质量） — **撤回** §4.5 / M15

### 11.5 内部运维频道（用户完全无感）

独立邮件 / 钉钉运维群，**与用户报告解耦**：

```
[内部] QBU 报告生成监控 · 2026-04-26
────────────────────────────────────
✅ 生成成功: HTML + Excel + Snapshot + Analytics
⚠ 数据质量警示:
   • SKU 1193465: 站点 91 / 采集 0 (需重抓)
   • 评论日期估算占比: 44.9% (252/561)
   • 样本覆盖率: 64% (MAX_REVIEWS=200 截断)
❌ 通知送达失败:
   • DingTalk 401 (检查 hooks.token)
   • outbox 3 条进 deadletter
🔧 内部修复待办:
   • top_actions 死字段处置
   • METRIC_TOOLTIPS 风险分文案与算法漂移
   • _parse_date_published anchor 不一致
   • impact_category × failure_mode × label_code 三字段语义层次
   • HTML 模板 row.values() 顺序耦合
   • product_snapshots 未绑定 run_id

服务版本: 0.3.25
```

### 11.6 对前章建议的收口决策

| 建议项 | 原归属 | 新归属 |
|-------|--------|-------|
| H1 数据质量自检告警 | 用户报告 KPI 卡 | **移内部运维**（独立告警邮件） |
| H6 risk_score 分母改采集 | 用户报告显示 | **保留**（影响数字本身） |
| H7 Excel 1193465 标红 | Excel 视觉 | **改为**"核心数据"sheet 的状态灯：⚪ 无数据 |
| H8 数据质量卡 | 顶部 KPI 加卡 | **移内部运维**（撤回） |
| H11 风险分 tooltip 与算法对齐 | 用户报告 tooltip | **保留**（用户能看到） |
| H13 outbox 状态 → 用户 HTML | 顶部状态条 | **移内部运维**（撤回） |
| H17 模板 row.values 改 columns key | 实现层 | **保留**（健壮性内部修复） |
| H20 top_actions 激活 / 删除 | 用户报告显示 | **走删除路径**（用户根本看不到此字段） |
| H21 三字段 schema 层次声明 | 内部 schema | **保留**但不在用户报告露出 |
| M11 指标说明 sheet | Excel | **撤回** |
| M15 数据质量 sheet | Excel | **撤回** |
| L10 邮件清理实现说明文案 | 邮件正文 | **保留**（用户能看到） |

### 11.7 用户视角的核心问答检验

| 用户问 | 优化后能秒答吗？ |
|--------|----------------|
| "今天有事吗？" | ✅ 🟡 1 个产品需要关注 |
| "什么事？" | ✅ 0.75 HP 开关失灵 + 客服失联 |
| "我该做什么？" | ✅ 升级开关耐久性 + 建立工单 SLA |
| "竞品在干嘛？" | ✅ 他们清洁设计强，我们要学 |
| "数据靠谱吗？" | ✅ 不展示给用户，由内部运维告警保证质量 |

### 11.9 第四轮收口：4 类产物边界澄清（**最终决策**）

> **背景**：第三轮 §11 中"用户视角 HTML 终稿"未区分邮件正文 HTML 与附件 HTML 报告，二者设计目标完全不同。第四轮经源码核对（`qbu_crawler/server/report_templates/`）确认产品系统已有的产物边界，并按各自约束分别给出终稿。

#### 11.9.1 当前生产产物 4 频道（基于源码实测）

| # | 产物 | 模板 / 行 | 触发 | 受众使用场景 | 设计约束 |
|---|------|----------|------|------------|---------|
| 1 | 邮件正文 HTML（full） | `email_full.html.j2` (267) | 每日 full 报告 | Outlook / 钉钉 / Gmail 内联，30-60 秒 | max-width 640px / 表格布局 / 无 JS / 内联 CSS |
| 2 | 邮件正文 HTML（change） | `email_change.html.j2` (148) | 仅价格/库存/评分变动日 | 同上，更短 | 同上 |
| 3 | 邮件正文 HTML（quiet） | `email_quiet.html.j2` (142) | 无变化日 | 同上，最短 | 同上 |
| 4 | **附件 HTML 报告** | `daily_report_v3.html.j2` (637) | 每次 full | 浏览器深度阅读 5-15 分钟，会议投屏 | 无约束 / 完整 CSS+JS / charts / tabs |
| 5 | Excel 附件 | `_generate_analytical_excel()` | 每次 full | 数据下钻 / sort / filter / 二次加工 | sheets 多列；行级数据 |
| 6 | **数据质量告警邮件** | `email_data_quality.html.j2` (47) | scrape_quality 阈值 | **已存在的内部运维通道** ✅ | 简短，仅运维 |
| 7 | 邮件正文纯文本 | `daily_report_email_body.txt.j2` (15) | HTML 邮件并存 | 不支持 HTML 客户端 | 极简 |

**关键事实**：`email_data_quality.html.j2` 已存在——这正是 §11.5 设想的"内部运维通道"，无需新建，只需补强触发条件（H1）。

#### 11.9.2 邮件正文 HTML 终稿（30-60 秒决策）

**目标**：让用户决定"打开附件深入看 vs 已了解可以走"。

```
┌─ 邮件正文（max-width 640px）─────────────────┐
│ QBU 评论分析 · 2026-04-26                    │
│ 本期: 自有 5 款 / 竞品 3 款 / 共 561 条评论    │
├──────────────────────────────────────────────┤
│ 🟢 总体口碑 优秀  🟡 需关注产品 1 个           │
│ 好评率 94.7%      差评率 2.4%                 │
├──────────────────────────────────────────────┤
│ 关键判断（Hero 一句话 + 3 条 bullets）         │
├──────────────────────────────────────────────┤
│ Top 3 行动建议（短标题 + 影响产品数）          │
├──────────────────────────────────────────────┤
│ 自有产品状态（5 行 灯 + 一句原因）             │
├──────────────────────────────────────────────┤
│ ▶ 详情 / 评论原文见附件 HTML                   │
│ ▶ 数据下钻见 Excel 附件                        │
└──────────────────────────────────────────────┘
```

**对 `email_full.html.j2` 的具体改动**：
- ❌ 删除：`覆盖产品 N/M`（覆盖率内部信号）
- ❌ 删除：`累计自有/竞品评论数字卡`（用户不关心总数）
- ❌ 删除：`本次入库`大数字（应改"新近 3 / 补采 558"文字解释）
- 🔄 改写：`高风险产品 0` → `需关注产品 1 个 (.75 HP)`（去阈值数字）
- 🔄 改写：`健康指数 96.2`（顶部巨幅数字） → `🟢 总体口碑 优秀 (96.2)`（语义灯主导）
- ➕ 加入：Top 3 行动 short_title + 影响产品数（依赖 H14 拆 short_title 后才能短到塞进邮件）
- ✅ 已无内部运维信号（生产正常，只需保持）

#### 11.9.3 附件 HTML 报告终稿（5-15 分钟深度阅读）

**目标**：周会投屏；产品改良工程师 / 设计师下钻具体问题；保留全部分析深度。**比邮件正文丰富得多**。

```
┌─ 附件 HTML（浏览器全屏）────────────────────────────┐
│ 顶部 KPI 4 张语义灯（同邮件）                        │
├──────────────────────────────────────────────────────┤
│ Hero + 3 条 bullets（同邮件）                         │
├──────────────────────────────────────────────────────┤
│ 现在该做什么 — 完整 5 项                              │
│   每项: short_title + 完整 full_action +              │
│         证据评论回链 [#252, #254...] + 影响 SKU 列表   │
├──────────────────────────────────────────────────────┤
│ 自有产品状态（5 行 + 详细风险因子分解 hover/展开）     │
│   .75HP: 因子 neg35+sev25+evi15+rec15+vol10           │
├──────────────────────────────────────────────────────┤
│ 自有产品问题诊断 — 全部 8 张 issue cards               │
│   含 actionable_summary / failure_modes / root_causes │
│   含 example_reviews 文本 + 图评 gallery              │
├──────────────────────────────────────────────────────┤
│ 竞品启示                                              │
│   完整可借鉴 5 条 + 完整短板 5 条 + 雷达图             │
├──────────────────────────────────────────────────────┤
│ [仅数据成熟期] 变化趋势（bootstrap 期完全折叠）        │
│   且过 H16 阈值（N≥30 + 时间点≥7）才显示 ready        │
├──────────────────────────────────────────────────────┤
│ 全景数据（保留嵌入 561 评论行）                       │ ← 第六轮决策：保留嵌入
│   含筛选: 归属 / 评分 / 有图 / 新近 / 标签             │
└──────────────────────────────────────────────────────┘
```

**对 `daily_report_v3.html.j2` 的具体改动**：
- ❌ 删除：`变化趋势 12 panel`（bootstrap 期折叠 / 数据成熟期才显示，且过 H16 阈值才 ready）
- ❌ 删除：`今日变化 4 区块`（首日全空区段不显示）
- ❌ 删除：`总体竞品差距指数 4`、`样本覆盖率 64%`、`累计评论 418` 等抽象/纯数字卡
- ✅ **保留**：嵌入 561 行评论明细全景数据（**第六轮决策**——附件 HTML 应具备独立下钻能力，不依赖 Excel；建议加客户端筛选：归属/评分/有图/新近/标签）
- 🔄 改写：`自有产品排行` → `自有产品状态` 灯 + 一句原因 + hover 展开因子分解（H11）
- 🔄 改写：`竞品对标 gap_rate=13` → `竞品启示`双名单（保留分母与置信度，比邮件多）
- 🔄 改写：`duration_display "约 8 年"` → `高频期 YYYY-MM ~ YYYY-MM`（H5）
- 🔄 修复：`建议行动`截断（H14 拆字段后，附件可显示完整 full_action）
- ✅ 保留：全 8 个 issue cards 的深度内容（这是用户开附件的核心理由）
- ✅ 保留：example_reviews 原文 + 图评 + 风险因子分解
- 🚫 **不在附件中露出**：scrape_quality 自检 / outbox 状态 / 估算日期占比 / top_actions / schema 债务

#### 11.9.4 Excel 附件终稿（数据下钻）

与 §11.4 一致，4 sheets：核心数据 / 现在该做什么 / 评论原文 / 竞品启示。**撤回**指标说明 sheet 与数据质量 sheet。

#### 11.9.5 内部运维通道（复用 `email_data_quality.html.j2` + 扩展）

- ✅ **复用现有 `email_data_quality.html.j2`**（系统已有此通道，无需新建）
- 🔧 补强触发条件（H1）：`zero_scrape_skus` 非空 / `scrape_completeness_ratio < 0.6` / `estimated_date_ratio > 0.3` / outbox deadletter / tooltip-代码 CI 漂移
- 🔧 收件人：仅运维群（与用户报告收件人解耦）

#### 11.9.6 4 频道改动量对照

| 改动项 | 邮件正文 HTML | 附件 HTML 报告 | Excel | 内部运维 |
|-------|-------------|--------------|-------|---------|
| 顶部 KPI | 4 灯（极简） | 4 灯 + tooltip | 单独 sheet（撤回） | — |
| Hero + bullets | ✓ 简版 | ✓ 完整 | — | — |
| 行动建议 | Top 3 短标题 | 完整 5 项 + 证据回链 | "现在该做什么" sheet | — |
| 产品状态 | 5 行灯 + 一句原因 | 5 行 + 详细因子分解 | "核心数据" sheet | — |
| 8 issue cards | ❌ 不展示 | ✅ 完整保留 | — | — |
| 评论原文 | ❌ | **嵌入 561 行 + 客户端筛选**（第六轮） | "评论原文" sheet 561 行（drawing 嵌图保留） | — |
| 竞品启示 | ❌ | 双名单 + 雷达图 | "竞品启示" sheet | — |
| 趋势 | ❌ | 数据成熟期才显示 | 撤回 | — |
| 数据质量信号 | ❌ | ❌ | ❌ | ✅ 独立邮件 |
| 通知失败信号 | ❌ | ❌ | ❌ | ✅ 独立邮件 |
| schema 债务 | ❌ | ❌ | ❌ | ✅ 内部修复待办 |

**核心原则**：邮件正文是"决策入口"，附件 HTML 是"深度分析"，Excel 是"数据下钻"，内部运维通道是"工程信号"——四者**目标受众重叠但内容不应重复堆叠**。

### 11.10 不做"分角色 tabs / 分角色 Excel"（**撤回 §9.5 / §8.3 L9**）

> **背景**：第三轮 §9.5 提出"HTML 顶部 tabs：管理者 / 产品改良 / 设计 / 数据视图"；§8.3 L9 提出"角色化 Excel 导出：*_管理者.xlsx / *_产品改良.xlsx / *_设计.xlsx"。第四轮 review 中用户明确反对这两个方向，理由充分。

#### 11.10.1 撤回理由

**分角色 HTML tabs 的两层成本**：

| 维度 | 成本 |
|------|------|
| 维护成本 | 4 套 layout + 4 套数据透传契约 + 4 套测试；每次指标变更要改 4 处 |
| 用户认知成本 | 打开报告先要选"我是谁" → 第一步即认知摩擦；周会投屏时大家在不同 tab 上指认；跨角色协作时需要互相切换 |
| 分类本身的问题 | 产品经理也想看竞品启示；设计师也想看数据明细；管理者不会主动切到"产品改良 tab"——**标签即偏见**，硬分类无视实际工作场景 |

**分角色 Excel 导出的两层成本**：

| 维度 | 成本 |
|------|------|
| 维护成本 | 3 个生成函数 + 3 套发送链路 + 收件人配置矩阵；附件路径管理复杂 |
| 用户认知成本 | 附件命名歧义"哪个版本最新？"；跨角色复用时还要互要文件；多文件版本极易对不上 |
| 分类本身的问题 | Excel 本质是"分析师工具"——一个工作簿就够，需要的人按 sheet 找，**角色分类对 Excel 无意义** |

#### 11.10.2 正确替代方案：单一报告 + 信息层次按"决策深度"分层

```
┌── 顶部（管理者 30 秒就走）─────────────────┐
│  4 KPI 灯 · Hero · 3 bullets · Top 3 行动    │ ← 老板这层就够
├── 中段（产品改良 / 设计 多读 5 分钟）────────┤
│  自有产品状态 · 8 issue cards · 竞品启示       │ ← 工程师/设计师停在此层
├── 下段（分析师 / 想下钻 → Excel）─────────────┤
│  全景数据 → 链接 Excel 附件                   │ ← 需要 561 评论的人去 Excel
└────────────────────────────────────────────┘
```

**架构原则**：**按"决策深度"分层，不按"角色身份"切分**。每个用户从上往下读，自然在自己关心的深度停下；多人协作时大家看的是同一份。

#### 11.10.3 收口决策

| 原建议 | 决策 |
|-------|------|
| §9.5 「HTML 顶部 tabs：管理者/产品改良/设计/数据」 | **撤回** |
| §8.3 L9 「角色化 Excel 导出 *_管理者/*_产品改良/*_设计.xlsx」 | **撤回** |
| 替代方案 | 单一报告（同邮件正文 / 附件 HTML / Excel 各一份），按决策深度自上而下分层 |

#### 11.10.4 验证：现有 §11.9 设计已经满足"自然分层"

- 邮件正文 → 30 秒决策 → 管理者天然停止层
- 附件 HTML → 5-15 分钟深度 → 产品改良 / 设计天然停止层
- Excel → 数据下钻 → 分析师天然停止层

**单一架构 + 自然分层**已经覆盖所有角色需求，不需再叠加"显式角色 tab"。

---

### 11.11 附件 HTML 中"今日变化"与"变化趋势"两区块用户视角深度审视

> **范围**：本节专门针对附件 HTML 报告（`daily_report_v3.html.j2`）中的"今日变化"和"变化趋势"两个 H2 区块做字段级用户视角审视。补充 §11.9.3 的总体改造清单，深入到"哪些指标该展示 / 哪些对比该做 / bootstrap 期与数据成熟期的不同行为"。其他区块（Hero / KPI / issue cards / 竞品启示）已在 §11.9.3 收口。

#### 11.11.1 今日变化区块审视

##### A. 当前结构

```
H2 今日变化
├── H3 监控起点（bootstrap 状态卡 + 提示）
├── H3 问题变化（issue_changes: new / escalated / improving / de_escalated 4 桶）
├── H3 产品状态变化（product_changes: price_changes / stock_changes / rating_changes / new_products / removed_products 5 桶）
└── H3 新近评论信号（review_signals: fresh_competitor_positive_reviews 等）
```

实测 bootstrap 期数据：4 桶 + 5 桶全空 `[]`；新近评论信号仅 12 条（其中只展示了"竞品好评"）；提示信息含工程概念 `estimated_dates / backfill_dominant`。

##### B. 数据指标的语义混乱（用户视角）

| 当前指标 | 真正含义 | 用户读到的 | 问题 |
|---------|---------|----------|------|
| 本次入库 561 | 系统今天写入 DB 的评论行数（含历史补采） | "今天 561 条新评论？" | **严重误读**——99% 是补采 |
| 新近 3 | `date_published` 在近 30 天内 | 模糊 | 应改为"今日新增" |
| 补采 558 | 系统首次抓到但用户早就发过 | 工程概念 | 用户不关心，应淡化 |
| 自有新近差评 0 | 近 30 天内 ≤2 星 | "今天没新差评" | ✅ 有价值，但单独 0 没语境 |
| 新增/升级/改善问题 0 | 跨 run 对比 | 一堆 0 | bootstrap 期占版面 |
| 产品状态变更 0 | 价格/库存/评分跨日 diff | 0 | 同上 |
| `estimated_dates 已触发` | 评论日期估算占比超阈值 | "什么是估算日期？" | **完全是工程信号** |
| `backfill_dominant 占比 99%` | 本次入库以补采为主 | "和我有什么关系？" | **完全是工程信号** |

##### C. 数据对比的合理性问题

1. **bootstrap 期没有可比 run**：所有"变化"建立在跨 run 对比上，首日纯粹是占位。当前实现把空状态当结果展示（"新增 0 / 升级 0 / 改善 0"），**应直接隐藏**而非展示零值。
2. **四维平铺没区分用户优先级**：监控起点 / 问题变化 / 产品状态 / 评论信号 同等版面，但价值差异巨大。
3. **`fresh_competitor_positive_reviews` 优先级反了**：当前唯一被突出的是"竞品好评"，但用户决策价值排序应是：
   - ⭐⭐⭐ 我方新差评（要立即处理）→ **当前未独立展示**
   - ⭐⭐⭐ 竞品新差评（我方营销机会）→ **当前未独立展示**
   - ⭐⭐ 我方新好评（鼓舞）
   - ⭐ 竞品新好评（反向学习）→ 唯一被突出的，价值反而最低

##### D. 给用户带来的价值（按角色）

| 角色 | 当前价值 | 应有价值 |
|------|---------|---------|
| 管理者 | 接近零（一堆 0 + 工程提示） | "今天有事吗？哪个产品哪个问题？" |
| 产品改良 | 中 | "哪些问题在恶化？哪些在改善？验证改进生效了吗？" |
| 设计 | 零 | "用户最近在抱怨什么新场景？" |
| 营销 | 零 | "竞品出问题了吗？我们能蹭机会吗？" |

##### E. 优化方案

**E.1 bootstrap 期：隐藏整个"今日变化"区块**

首日 delta 全 0 是**伪信息**。改为单卡：

```
ℹ 首日基线已建档，对比信号将从下一日起出现
```

不展示空的 4 个 H3 子区。

**E.2 数据成熟期：4 块平铺 → 3 层金字塔**

```
今日变化（仅在有真变化时显示）

🔥 立即关注（红色，老板/产品都该看）
  • 我方新差评 5 条 (.75 HP 3 / Quick Patty 2)
    主要问题: 开关失灵, 肉饼厚度
  • .75 HP 评分 4.7 → 4.5 (-0.2)
  • Walton's #22 缺货警告

📈 趋势变化（黄色，产品改良该看）
  • 新增问题: hd_durability +5 条
  • 升级问题: structure_design (medium → high)
  • ✅ 改善问题: noise_power -3 条（验证之前改良生效）

💡 反向利用（蓝色，营销/产品该看）
  • 竞品 Cabela's HD Stuffer 收到 7 条新差评
    主要问题: 齿轮强度不足 → 我方做工可作差异化
  • 竞品新好评 3 条 → 反向学习: 反转停转设计

(折叠) 静态信号 — 仅"想知道更多"的人展开
```

**E.3 删除工程信号到内部运维频道**

`estimated_dates` / `backfill_dominant` / `本次入库` 等**全部移到 `email_data_quality.html.j2`**。用户报告里只留"我方新差评 N / 自有评分变化 N"等业务可读信号。

#### 11.11.2 变化趋势区块审视

##### A. 当前结构

```
H2 变化趋势（4 维度 × 3 时间窗口 = 12 panel）
├── 近 7 天:   情绪 / 问题 / 产品 / 竞品
├── 近 30 天:  情绪 / 问题 / 产品 / 竞品
└── 近 12 月:  情绪 / 问题 / 产品 / 竞品

默认: month/sentiment
```

实测：12 panel 中 4 个 outer ready + 7 个 inner ready（3 个外内不一）；近 30 天 sentiment 仅 3 条样本就 ready；年视图基于 252/561=44.9% 估算日期画线。

##### B. 时间窗口设计合理性

| 窗口 | 适合维度 | 当前是否合理 |
|------|---------|------------|
| 7 天 | 紧急响应（库存、客服 SLA） | ⚠ 用于情绪/问题维度 → 样本太少（自有 1 周可能 2-3 条） |
| 30 天 | 产品改良迭代周期 | ✅ 合适，但要过样本阈值 |
| 12 个月 | 战略 / 年度复盘 | ⚠ 当前混入 44.9% 估算日期 → 失真严重 |

**结论**：3 个窗口本身合理，但 4 维度 × 3 窗口 = 12 panel 一刀切是**错配**——不是每个维度在每个窗口都有意义。

##### C. 4 维度的冗余性

| 维度 | 实质 | 与其他维度重叠 |
|------|------|--------------|
| 评论声量与情绪 | 评论数 + 差评率随时间 | 是"问题结构"的总量视图 |
| 问题结构 | Top 标签随时间变化 | "声量"的细分版 |
| 产品状态 | 价格、评分、库存随时间 | 与"竞品对标"是绝对/相对关系 |
| 竞品对标 | 自有 vs 竞品差距随时间 | "产品状态"的相对版 |

**真正的核心维度只有 2 个**：
1. **健康度趋势**（声量+情绪+问题 的综合表达）
2. **自有 vs 竞品对照趋势**

当前 4 维度是**工程视角的"指标穷举"**，对用户决策反而稀释了核心判断。

##### D. 数据对比合理性的 4 个核心问题

**D.1 基于 `date_published` 聚合的语义陷阱**

- 当前所有趋势按"评论发表时间"聚合
- 意味着 2018 年用户写的评论显示在 2018 年的数据点上
- **对用户**：他以为"近 12 月趋势"是过去 12 个月发生的事，实际是历史评论分布
- **正确的趋势聚合应有两套**：
  - 按 `date_published`：反映用户活跃度的历史模式（人类视角）
  - 按 `scraped_at`：反映系统监控期内看到的变化（运营视角）
- 当前 12 panel 全是前者；后者反被埋没（仅 products 维度涉及 scraped_at）

**D.2 缺乏对比基准**

- "近 30 天差评率 10.3%"——和谁比？vs 上 30 天？vs 同期前年？vs 竞品同期？
- 当前是**孤立数字**，没对照系，用户无法判断"是否异常"
- 应每个数字都有 `对比基准 + 偏差%`

**D.3 样本不足时强行画线**

- 月视图 sentiment 3 条样本就 ready
- 1 条 LLM 误判 negative → 显示"近 30 天差评率 100%"惊吓
- 应阈值 ≥30 + 时间点 ≥7 才允许显示趋势线

**D.4 12 panel 视觉过载**

- 即便都数据合理，12 张图同时呈现，老板**看完一张就累了**
- 用户的真实需求："给我一张图，告诉我口碑总体在变好还是变坏"

##### E. 给用户带来的价值（按角色）

| 角色 | 当前价值 | 应有价值 |
|------|---------|---------|
| 管理者 | 接近零（12 panel 看不完） | "口碑趋势图一张" + "对比上期 +N%" |
| 产品改良 | 中（问题结构维度有用，但被埋没） | "Top 3 问题随时间变化"（一张图显示哪个问题在涨） |
| 设计 | 零 | "用户痛点的演变" |
| 营销 | 低 | "我方 vs 竞品 健康度对照" |

##### F. 优化方案

**F.1 bootstrap 期：完全隐藏整个"变化趋势"区块**

数据成熟前不展示任何趋势——单卡：

```
ℹ 趋势数据正在累积，需至少 30 天且每周 ≥7 个有效样本
```

撤销当前 12 个 status=accumulating 的空 panel 占用版面。

**F.2 数据成熟期：12 panel → 1 主图 + 3 折叠下钻**

```
变化趋势（仅数据成熟期显示）

┌── 主视图（默认）─────────────────────────┐
│  口碑健康度趋势                           │
│  ─ 自有产品健康度 (绿线)                  │
│  ─ 竞品平均健康度 (红线)                  │
│                                          │
│  当前 96.2 ↓ 1.2pt vs 上 30 天平均        │ ← 对比基准
│  竞品 78.3 ↓ 0.5pt vs 上 30 天平均        │
│                                          │
│  时间切换: [7 天] [30 天 ★] [12 月]       │ ← 用户主动选
│  口径切换: [发表时间] [采集时间 ★]         │ ← 语义澄清
└─────────────────────────────────────────┘

[展开 ▼] Top 3 问题随时间变化（产品改良关心）
   - structure_design: 升 (+3 / 30 天)
   - service_fulfillment: 持平
   - quality_stability: 降 (-2 / 30 天) ✅ 验证改良生效

[展开 ▼] 产品评分变化（运营关心）
   - .75HP: 4.7 → 4.5  ⚠
   - Quick Patty: 4.7 → 4.7
   - …其他持平

[展开 ▼] 竞品对标（雷达图，截面 + 对比上月）
   - 做工与质量: 我方 ↑ 竞品 ↓ → 差距收窄
   - 售后履约: 我方 ↑ 竞品 = → 差距扩大
```

**F.3 关键数据对比改造**

| 改造点 | 旧 | 新 |
|-------|----|----|
| 数据指标 | 孤立数字 | 数字 + 对比基准 + 偏差 % |
| 时间维度 | 3 窗口并列展示 | 用户主动切换（默认 30 天） |
| 时间口径 | 混用 date_published / scraped_at | 显式切换 + 标签说明含义 |
| 样本阈值 | 1 条就 ready | ≥30 样本 + ≥7 时间点才画线 |
| 维度冗余 | 4 维度 × 3 窗口 = 12 panel | 1 主图 + 3 折叠 |
| 对比对象 | 无 | 上期 / 同期 / 竞品 三选一 |

##### G. 真正给用户带来的价值

| 用户问 | 优化后能秒答 |
|--------|------------|
| 口碑在变好还是变坏？ | ✅ 主图一眼绿线方向 |
| 比上个月好/差多少？ | ✅ 主图右上对比基准 |
| 哪个具体问题在恶化？ | ✅ 展开 Top 3 问题趋势 |
| 我们 vs 竞品差距在变化吗？ | ✅ 展开雷达图 + 对比上月 |
| 我之前的改良奏效了吗？ | ✅ Top 3 问题中标 ✅ "降幅 / 30 天" |

#### 11.11.3 综合优化原则

| 原则 | 应用 |
|------|------|
| **bootstrap 期完全隐藏 delta 区块** | 不展示伪信息（一堆 0） |
| **数据成熟期按用户价值优先级排列** | 立即关注 / 趋势变化 / 反向利用 三层 |
| **维度从穷举 → 收敛到核心 1-2 个** | 12 panel → 1 主图 + 3 下钻 |
| **每个数字都附对比基准** | 孤立数字 → 数字+基准+偏差% |
| **时间口径显式区分** | `date_published`（用户活跃）vs `scraped_at`（系统监控）必须标签化 |
| **样本不足拒绝画线** | 阈值 ≥30 + 时间点 ≥7 |
| **工程信号全部移内部运维** | `estimated_dates` / `backfill_dominant` / `本次入库` 等不进用户报告 |
| **新差评/竞品差评 优先于 竞品好评** | 当前 review_signals 优先级反了 |

#### 11.11.4 实施改造清单（PR 拆分友好）

| # | 改造项 | 涉及文件 | 工作量 |
|---|-------|---------|--------|
| 1 | "今日变化"区块加 bootstrap 期判断，全空时单卡替代 4 子区 | `daily_report_v3.html.j2` | 0.5 天 |
| 2 | 数据成熟期"今日变化"重排为 3 层金字塔（立即关注/趋势变化/反向利用） | `daily_report_v3.html.j2` + `change_digest` 数据契约 | 1-2 天 |
| 3 | `change_digest` 增加 `own_new_negative_reviews` / `competitor_new_negative_reviews` 两个新 review_signals | `report_analytics.py` | 0.5 天 |
| 4 | "变化趋势"区块加 bootstrap 期判断，全空时单卡替代 12 panel | `daily_report_v3.html.j2` | 0.5 天 |
| 5 | 数据成熟期"变化趋势"重构为 1 主图 + 3 折叠 | `daily_report_v3.html.j2` + `trend_digest` 数据契约 + `daily_report_v3.js` | 2-3 天 |
| 6 | 趋势主图加"对比基准"字段 | `report_analytics.py` `trend_digest` 计算逻辑 | 1 天 |
| 7 | 趋势按 `date_published` / `scraped_at` 双口径切换 | `report_analytics.py` + 前端 toggle | 1-2 天 |
| 8 | 趋势 ready 阈值升级到 ≥30 + ≥7（联动 H16） | `report_analytics.py` | 0.5 天 |
| 9 | `estimated_dates` / `backfill_dominant` 等工程信号移到 `email_data_quality.html.j2` | 多文件 | 0.5 天 |
| **总计** | | | **7-11 天** |

---

### 11.8 整改计划优先级重排（基于用户视角）

**P0 用户价值类**（直接影响读者决策）：
- H10 差评率分母统一（影响数字正确性）
- H11 风险分 tooltip 与算法对齐
- H14 建议行动 short_title + full_action（消除半句话标题）
- H5 duration_display 重命名或移除
- 11.3 全屏布局重构（KPI 4 张语义灯 + 风险榜状态灯 + 竞品双名单）

**P0 内部修复类**（用户无感，保证产品长期可信）：
- H1+H6 scrape_quality 自检 + risk_score 分母（数字正确性）
- H6 outbox 状态回写 workflow
- H17 模板 row.values 改 columns key（健壮性）
- H19 failure_mode enum 化（让聚合分析可用）
- H20 top_actions 走删除路径
- 三字段 schema 层次声明

**P1 / P2** 中低优依然按原序，但所有"在用户报告露出"的项被收口为"内部修复"或"撤回"。

---

**审计人**：Claude Code（初稿）+ Codex（独立交叉审查）+ 用户（用户视角最终收口）
**审计完成时间**：2026-04-26（初稿）/ 2026-04-27（合入 Codex 交叉验证 + 二次互验 + 用户视角再审视）
**关联文档**：
- `docs/reviews/2026-04-25-production-test3-phase1-phase2-alignment-review.md`（前置 Phase 2 一致性审查）
- `docs/reviews/2026-04-26-production-test5-full-report-audit-codex.md`（Codex 独立审查，本文已合入其关键发现）
- `docs/superpowers/plans/2026-04-26-report-production-p0-p2-remediation.md`（待生成的整改计划，应基于本合并版 §11 用户视角终稿 + H1-H21 选择性执行）
