# 测试10 P4 采集真相与报告契约纠偏设计

**日期**：2026-04-29
**状态**：设计完成，待计划审查与实施
**输入依据**：
- 生产测试产物：`C:\Users\leo\Desktop\生产测试\报告\测试10`
- 生产日志：`qbu-crawler@0.4.12 serve`
- P0-P3 设计与实施结果
- `docs/reviews/2026-04-28-production-test7-report-root-cause-and-remediation.md`
- `docs/rules/basspro.md`
- `AGENTS.md` 中 DrissionPage 通用开发注意事项

---

## 1. 背景

测试10暴露的问题已经越过“报告文案错误”的层面：采集链路真实失败，但任务、run log、报告质量摘要没有把失败 URL 作为一等事实保存；报告链路已经有 `report_user_contract`，但 HTML、LLM、Excel 仍存在绕开或半消费 contract 的路径，导致同一份报告里出现“事实正确但展示不对号”的情况。

这次 P4 的核心目标不是视觉改版，也不是把错误藏起来，而是让系统从采集到报告都能回答同一个问题：**这次到底计划采什么、实际采到了什么、哪些地方失败、用户看到的数据是否只来自可信契约。**

---

## 2. 测试10证据基线

### 2.1 采集事实

- 生产版本：`qbu-crawler@0.4.12`
- 报告窗口：`2026-04-29 00:00:00` 到 `2026-04-30 00:00:00`
- DB 实际入库：7 个产品、565 条评论、565 条 `review_analysis`
- 预期 URL：8 个
- 漏采 URL：
  - `https://www.basspro.com/p/cabelas-heavy-duty-20-lb-meat-mixer`
- 失败日志：
  - `KeyError: 'searchId'`
  - 位置：`qbu_crawler/scrapers/basspro.py:116`
  - 触发点：`tab.wait.ele_displayed('tag:h1', timeout=15)`
  - 底层：DrissionPage 通过 `DOM.getSearchResults` 取元素时，CDP 返回结果缺少 `searchId`

### 2.2 浏览器复现事实

- Playwright 普通浏览器直连 BassPro 出现 `Access Denied`，符合 Akamai 防护预期。
- 使用当前项目 `BassProScraper` / DrissionPage 本地复现，目标 URL 可以打开，并能读到：
  - 标题：`Cabela's Heavy-Duty 20-lb. Meat Mixer | Bass Pro Shops`
  - H1：`Cabela's Heavy-Duty 20-lb. Meat Mixer`
  - SKU：`2834842`
  - rating：`4.3`
  - reviewCount：`58`
- 复现时还观察到 BassPro age gate 会异步出现；当前代码只在 `get()` 后立即关闭一次，晚出现时可能挡住或干扰 BV 评论组件。
- BassPro 成功产品也存在低覆盖不稳定：BV Shadow DOM 有时只有标题、0 条 section，或加载到约 60 条后 `Load More` 消失。

### 2.3 报告事实

- HTML 总览“现在该做什么”出现 `影响 0 款 · 证据 30/16/12 条`，但 contract 内 action priorities 对应影响产品数实际是 5/4/5。
- 今日变化 Tab 显示 `当前截面：0 款产品 / 0 条评论`，但 snapshot 实际是 7/565。
- LLM warning：`bullet 中数字 30.0 无法在 kpis/risk_products 中找到来源`。30/16/12 来自 contract evidence count，但 LLM 已知数字集合没有纳入 contract evidence。
- KPI `sample_avg_rating=4.69` 实际是自有产品评论均分，不是全样本均分。DB 全样本均分约 4.36，自有评论均分约 4.688。
- Excel “竞品启示”仍存在产品为空、主题列塞长评论、验证假设重复短板、部分 evidence IDs 为空的问题。

---

## 3. 根因分层

### 3.1 BassPro 页面就绪判断依赖了不稳定的 DrissionPage 元素搜索路径

`tab.wait.ele_displayed('tag:h1')` 会走 DrissionPage 的元素搜索链路。测试10中 CDP 返回缺少 `searchId`，导致 `KeyError`。这不是目标页面必然不可访问，而是浏览器/CDP/动态页面状态下的一次搜索协议异常。直接延长 timeout 不能解决。

### 3.2 age gate 与 BV 评论组件缺少分阶段检测

当前 `_dismiss_age_gate(tab)` 只在导航后调用一次。BassPro 的 age gate、BV summary、reviews shadow root 都可能异步出现。代码没有在 H1 后、BV 前、展开评论前重复做轻量检测，也没有记录“BV 容器存在但 section 为 0”的停止原因。

### 3.3 Task 层没有持久化“计划 URL 与失败 URL”

单 URL 失败后，`task_manager` 只写日志，整个 task 仍可能 `completed`。结果里没有 `expected_urls`、`failed_urls`、`failed_url_count`、`stage`、`error_type`。因此 workflow 只能从 snapshot products 做质量判断，漏采 URL 不在 snapshot 里，自然无法被质量统计准确识别。

### 3.4 Run log 只看已入库产品，缺少“未入库目标”的差集

P2 run log 已经把低覆盖、deadletter 等工程事实从用户报告中移走，但采集完整率仍主要基于 snapshot products。测试10的关键问题是“目标 URL 没有生成 product summary”，必须从 workflow/task params 与 task result 对比得到。

### 3.5 Contract 刷新仍保留了空 snapshot 派生字段

`report_common.normalize_deep_report_analytics()` 会在缺 snapshot 时生成临时 contract；后续真实 snapshot 渲染 HTML 时，`build_report_user_contract()` 保留已有 `bootstrap_digest`，导致 `当前截面 0/0` 继续留在用户可见区域。

### 3.6 HTML 主链路仍存在 raw analytics 绕行

Excel 与部分邮件路径已经 contract-first，但 HTML 渲染仍会拿 raw analytics 进入 `report_html.py`，legacy adapter 没有完整合并 LLM copy 与 contract 派生字段，导致影响产品数、行动建议、副本内容不一致。

### 3.7 LLM 校验的“已知事实集合”覆盖不完整

P1/P2 已经把 LLM 限制为 evidence-bound，但数字来源只收集 kpis、risk_products、reviews 等，没有把 `report_user_contract.action_priorities[*].evidence_count`、`issue_diagnostics[*].evidence_count` 纳入，因此真实证据数 30/16/12 被误判为幻觉。

### 3.8 指标命名与计算漂移

`sample_avg_rating` 从语义上应表示全样本均分，但当前计算实际使用自有产品评论均分。这是版本迭代中字段复用产生的语义漂移，会让用户误判整体口碑。

### 3.9 竞品启示 contract 分区 item 信息不足

当前 `competitor_insights` 是分区 dict：`learn_from_competitors`、`avoid_competitor_failures`、`validation_hypotheses`。问题不在于分区结构本身，而是分区内 item 没保留稳定的产品字段与 evidence IDs，Excel 只能退化为 `—` 或从旧字段拼接，最终呈现“能读但不可追溯”的启示。

---

## 4. 目标

1. BassPro 采集失败时能准确区分页面不可达、CDP 搜索异常、age gate 干扰、BV summary 缺失、reviews shadow 为空、load more 中断。
2. 单 URL 失败不阻断整批任务，但失败 URL 必须进入 task result、run log、运维邮件和内部 manifest。
3. 用户业务报告不展示工程错误，但所有采集缺失必须能在 `data/log-run-<run_id>-<yyyymmdd>.log` 和技术邮件里追踪。
4. HTML / Excel / 邮件展示层只消费刷新后的 `report_user_contract`，避免 raw analytics 绕开 contract。
5. bootstrap digest、action priority 影响产品数、evidence count 等派生字段在真实 snapshot 到达后必须重算。
6. LLM 数字校验认可 contract evidence facts，继续阻止真正的幻觉数字。
7. KPI 命名和计算恢复一致：全样本均分与自有产品均分分开表达。
8. Excel 竞品启示具备产品、主题、证据评论 ID、验证假设的稳定字段。

---

## 5. 非目标

- 不把低覆盖 SKU、失败 URL、deadletter 等工程诊断放回用户业务报告。
- 不绕过 BassPro/Akamai 防护，不引入更激进的请求频率或规避行为。
- 不改动 CSV 源格式和每日调度时间。
- 不做报告视觉改版。
- 不重构所有 scraper，只修 BassPro 当前暴露的页面就绪与 BV 诊断问题。
- 不把 LLM 重新变成事实决策者；LLM 仍只做 evidence-bound 改写。

---

## 6. 方案设计

### 6.1 BassPro 页面就绪与定向重试

新增 BassPro 内部阶段概念：

| Stage | 含义 | 成功条件 | 失败记录 |
|---|---|---|---|
| `navigate` | 进入产品页 | URL 加载完成或 DOM 可执行 | HTTP/防护页/浏览器断连 |
| `age_gate` | 处理年龄确认 | 未出现或已关闭 | 出现但无法关闭 |
| `product_identity` | 产品身份就绪 | JS 可读到 `h1` 或标题 | CDP search error / h1 missing |
| `bv_summary` | BV summary 就绪 | 读到 rating/reviewCount 或确认无评论 | summary missing |
| `reviews_open` | 评论区打开 | Reviews tab/section 可见 | tab missing / blocked |
| `reviews_load` | 评论分页加载 | section 数达到站点总数或合理停止 | load_more_missing / shadow_empty / timeout |

关键原则：
- H1 等待改为 `tab.run_js()` 轮询 `document.querySelector('h1')?.innerText`，避开 DrissionPage `DOM.performSearch` 路径。
- 捕获 `KeyError('searchId')`、页面断连和 BV 阶段异常后，只做一次定向 reload 或重建 scraper 重试，避免无限重试。
- `_dismiss_age_gate(tab)` 在导航后、H1 后、BV 前、reviews 展开前重复调用，但每次只做轻量检测，不增加攻击性点击。
- 记录 `BassProScrapeDiagnostics`：`stage`、`age_gate_seen`、`bv_container_seen`、`summary_count`、`shadow_count`、`load_more_state`、`stop_reason`、`attempt`。

### 6.2 Task result 失败契约

`task.result` 增加结构化字段：

```json
{
  "expected_urls": ["..."],
  "saved_urls": ["..."],
  "failed_urls": [
    {
      "url": "https://www.basspro.com/p/cabelas-heavy-duty-20-lb-meat-mixer",
      "site": "basspro",
      "stage": "product_identity",
      "error_type": "KeyError",
      "error_message": "'searchId'",
      "diagnostics": {
        "age_gate_seen": true,
        "bv_container_seen": false,
        "stop_reason": "cdp_search_error"
      }
    }
  ],
  "expected_url_count": 8,
  "saved_url_count": 7,
  "failed_url_count": 1
}
```

兼容原则：
- 旧 task result 没有这些字段时，现有查询不应失败。
- 单 URL 失败后整批仍可继续，但只要 `failed_url_count > 0`，run quality 必须进入 ops alert / internal quality flag 口径。P4 不强制把已生成完整业务报告的 workflow 从 `completed` 改成 `needs_attention`，避免把“报告已生成”和“采集有缺失”再次混为同一个状态。

### 6.3 Workflow 质量统计改为“计划与结果差集”

质量统计输入从 `snapshot.products` 扩展为：

- workflow run 关联 tasks
- task params 中的计划 URL
- task result 中的 saved/failed URL
- snapshot products 中的实际入库产品 URL

判定优先级：
1. `failed_urls` 明确存在：直接记录失败。
2. expected URL 未出现在 saved/result/snapshot 中：记录为 `missing_without_error`。
3. snapshot 存在但评论覆盖低：记录为 `low_coverage`。

`data/log-run-<run_id>-<yyyymmdd>.log` 必须包含：

```text
expected_urls=8
saved_products=7
failed_url_count=1
failed_url[1].url=https://www.basspro.com/p/cabelas-heavy-duty-20-lb-meat-mixer
failed_url[1].stage=product_identity
failed_url[1].error=KeyError: 'searchId'
```

运维邮件只发给 `.env` 中技术收件人，业务报告继续不暴露工程诊断。

### 6.4 Contract 真实 snapshot 刷新

`build_report_user_contract()` 增加明确策略：

- `contract_context.snapshot_fingerprint` 变化时，重算所有依赖 snapshot 的派生字段。
- 不再保留旧的 `bootstrap_digest`、`affected_products_count`、`summary_counts` 这类派生字段。
- 保留 LLM copy 文案，但只在对应 evidence pack 仍匹配时合并。

需要重算的字段：
- `bootstrap_digest.baseline_summary.product_count`
- `bootstrap_digest.baseline_summary.review_count`
- `action_priorities[*].affected_products_count`
- `issue_diagnostics[*].evidence_count`
- `competitor_insights.<section>[*].products`
- `delivery` 中 manifest-derived 字段

### 6.5 Renderer 统一入口

HTML、Excel、邮件都必须使用同一个 pre-normalized analytics：

1. workflow 构建 snapshot
2. `normalize_deep_report_analytics(snapshot, analytics)`
3. 用真实 snapshot 刷新 `report_user_contract`
4. 将刷新后的 analytics 同时传给 Excel、HTML、邮件

禁止新增模板直接消费以下旧字段：
- `report_copy.improvement_priorities`
- `top_negative_clusters`
- `competitor.negative_opportunities`
- `data_quality.low_coverage_products`
- `delivery.deadletter_count`

旧字段只允许在 adapter 层读取并转换为 contract。

### 6.6 LLM 已知事实集合扩展

`report_llm._collect_known_numbers()` 需要纳入：

- `report_user_contract.action_priorities[*].evidence_count`
- `report_user_contract.action_priorities[*].affected_products_count`
- `report_user_contract.issue_diagnostics[*].evidence_count`
- `report_user_contract.competitor_insights.<section>[*].evidence_count`
- `report_user_contract.bootstrap_digest.baseline_summary.product_count`
- `report_user_contract.bootstrap_digest.baseline_summary.review_count`

仍然不允许 LLM 使用未在 contract/kpis 中出现的数字。

### 6.7 KPI 语义修正

保留兼容字段但纠正含义：

- `sample_avg_rating`：全样本评论均分。
- `own_avg_rating`：自有产品评论均分。
- `competitor_avg_rating`：竞品评论均分。

展示层如需要“自有产品均分”，必须使用 `own_avg_rating`，不得再拿 `sample_avg_rating` 表达自有口径。

### 6.8 竞品启示分区 item 字段补齐

保留当前 `competitor_insights` 分区结构，不改成列表。每个分区 item 统一包含：

```json
{
  "label_code": "structure_design",
  "theme": "结构设计",
  "products": ["Cabela's Heavy-Duty 20-lb. Meat Mixer"],
  "evidence_review_ids": [101, 102],
  "evidence_count": 2,
  "competitor_signal": "竞品差评集中在安装与清洁成本",
  "validation_hypothesis": "验证自有产品说明书和配件包是否降低同类摩擦"
}
```

Excel “竞品启示”按分区消费以上字段，不再把整段评论塞进主题列。

---

## 7. 测试策略

### 7.1 BassPro 单元与轻量集成

- fake tab 触发 `KeyError('searchId')`，断言被归类为 `cdp_search_error` 并触发一次定向重试。
- fake tab 模拟 age gate 晚出现，断言多个阶段都会调用 `_dismiss_age_gate()`。
- fake tab 模拟 BV shadow root 为 0，断言 diagnostics 记录 `shadow_empty`，而不是静默返回成功。
- 本地可选实测 meat mixer URL，验证 H1、SKU、rating、reviewCount 可读。

### 7.2 Task / workflow / run log

- task 单 URL 失败后 result 包含 `failed_urls`。
- workflow quality 使用 expected URL 与 saved URL 差集识别漏采。
- run log 写入 failed URL、stage、error type。
- 运维邮件包含简短失败摘要，业务 HTML 不包含失败 URL。

### 7.3 Contract / renderer

- 真实 snapshot 刷新后，bootstrap digest 从 0/0 变为实际 7/565。
- HTML “现在该做什么”显示正确影响产品数。
- LLM 允许 contract evidence count 30/16/12。
- `sample_avg_rating` 全样本口径与 DB 一致。
- Excel 竞品启示包含产品名与 evidence IDs。

### 7.4 Replay

- 基于测试10最小脱敏 fixture 回放：7/565 + 1 failed URL。
- 断言用户报告不暴露工程错误。
- 断言内部 run log / manifest / ops mail 能追踪失败。

---

## 8. 验收标准

1. 测试10 meat mixer 类似失败再次出现时，run log 能明确记录失败 URL、阶段、错误类型和诊断字段。
2. 采集完整率不再只按入库产品计算，能识别“计划 URL 没有入库”的漏采。
3. BassPro `KeyError('searchId')` 不再直接导致 URL 静默丢失；至少会定向重试一次，并在最终失败时结构化记录。
4. HTML 今日变化不再出现 `当前截面 0 款产品 / 0 条评论` 这类空 snapshot 派生字段。
5. HTML 行动建议影响产品数与 contract evidence pack 一致。
6. LLM 不再把 contract evidence count 误判为幻觉数字。
7. `sample_avg_rating` 与全样本 DB 均分一致，自有均分使用 `own_avg_rating`。
8. Excel 竞品启示的产品、主题、证据、验证假设可追溯。
9. 用户业务报告不展示工程诊断；技术人员通过 run log 与运维邮件获取简要问题摘要。

---

## 9. 后续可选扩展

- 为 BassPro 关键阶段保存内部截图 artifact，只进入技术目录，不进入业务报告。
- 增加 MCP/API：按 run id 查询 expected/saved/failed URL。
- 对 MeatYourMaker / Waltons 复用同一 task failure contract，但不在 P4 中强行重构 scraper。
