# 测试10 P4 采集真相与报告契约纠偏 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 让测试10暴露的 BassPro 漏采、run log 缺失、HTML/Excel/LLM 报告契约偏移得到端到端修复，并用回归测试锁住“计划采集事实”和“用户展示事实”的一致性。
**Architecture:** 以 `report_user_contract` 为唯一展示契约，以 task result/run log 为采集真相契约；BassPro 只做页面就绪、age gate、BV 评论加载的定向稳定性修复，不做站点级重构。workflow quality 从“只看入库 snapshot”升级为“expected URL 与 saved/failed URL 对账”。
**Tech Stack:** Python 3.10+, SQLite, DrissionPage, pytest, Jinja2, openpyxl, existing workflow/report_contract/report_html/report_llm pipeline.

---

## Entry Context

- 设计文档：`docs/superpowers/specs/2026-04-29-test10-p4-scrape-truth-and-report-contract-design.md`
- 生产测试产物：`C:\Users\leo\Desktop\生产测试\报告\测试10`
- 关键失败：BassPro meat mixer URL 在 `tab.wait.ele_displayed('tag:h1')` 触发 `KeyError('searchId')`
- 关键原则：
  - 用户业务报告不展示工程诊断。
  - 技术追踪必须进入 `data/log-run-<run_id>-<yyyymmdd>.log` 和运维邮件。
  - LLM 只允许改写 contract 中锁定的事实。
  - 修 BassPro 时遵守 DrissionPage 现有踩坑：不要依赖不稳定的动态元素搜索，不激进绕防爬，不用共享浏览器状态。

---

## Crawler Safety Gate

所有涉及爬虫行为的修改必须先过以下门槛，未完成不得进入实现步骤：

- **先复现**：优先用测试10产物、生产日志、最小 fake tab 单测或本地浏览器实测复现当前失败；不能复现时必须说明原因，并用最小模拟覆盖失败路径。
- **先确认边界**：至少覆盖成功页面、目标元素晚出现、age gate 晚出现、BV 容器存在但评论为空、load more 消失、CDP search error、站点防护页或访问失败。
- **先评估防爬风险**：修改不得提高请求频率，不得新增激进刷新循环，不得绕过 Akamai/站点访问控制，不得复制真实 Chrome profile；只允许轻量 JS 轮询、有限定向重试和更清晰的诊断记录。
- **先验证再应用**：每一步爬虫修复必须有失败前测试、修复后测试和必要的本地实测记录；本地实测只在网络和防护状态允许时执行，不能为了验证而增加异常访问压力。
- **失败也要有真相**：即使最终采集失败，也必须把 URL、阶段、错误类型、诊断字段写入 task result 和 run log，不能静默丢失。

---

## File Map

| File | Responsibility | Tasks |
|---|---|---|
| `qbu_crawler/scrapers/basspro.py` | BassPro 页面就绪、age gate、BV 诊断与定向重试 | T1 |
| `qbu_crawler/server/task_manager.py` | task result 持久化 expected/saved/failed URL | T2 |
| `qbu_crawler/models.py` | task/workflow 查询补齐 params/result 读取能力 | T2, T3 |
| `qbu_crawler/server/scrape_quality.py` | 从 expected/saved/failed URL 计算采集完整率 | T3 |
| `qbu_crawler/server/run_log.py` | 写入 failed URL、stage、error type、差集原因 | T3 |
| `qbu_crawler/server/workflows.py` | workflow quality 输入改为 tasks + snapshot，运维邮件摘要更新 | T3 |
| `qbu_crawler/server/report_contract.py` | 真实 snapshot 刷新派生字段，补竞品启示字段 | T4, T7 |
| `qbu_crawler/server/report_common.py` | normalize 后 contract 派生字段刷新 | T4 |
| `qbu_crawler/server/report_html.py` | HTML 统一消费 pre-normalized contract | T5 |
| `qbu_crawler/server/report_snapshot.py` | Excel/HTML/邮件共用同一 normalized analytics | T5 |
| `qbu_crawler/server/report_llm.py` | known numbers 纳入 contract evidence facts | T6 |
| `qbu_crawler/server/report_analytics.py` | 修正 `sample_avg_rating` 与 `own_avg_rating` 口径 | T6 |
| `qbu_crawler/server/report.py` | Excel 竞品启示只消费 contract item | T7 |
| `docs/rules/basspro.md` | 记录 BassPro 页面阶段与 BV 诊断规则 | T8 |
| `AGENTS.md` | 记录通用 DrissionPage / run log 经验 | T8 |
| `docs/devlogs/D025-test10-p4-scrape-truth-and-report-contract.md` | P4 实施记录 | T8 |

---

## Chunk 1: BassPro 页面就绪与诊断

### Task 1: 避开 DrissionPage `DOM.performSearch` 路径并补充分阶段诊断

**Files:**
- Modify: `qbu_crawler/scrapers/basspro.py`
- Test: `tests/test_basspro_scraper.py` 或新增 `tests/scrapers/test_basspro_readiness.py`

- [x] **Step 1.0: 复现与防爬风险确认**

先完成以下核对，记录到任务笔记或 devlog 草稿：

- 用测试10日志确认原始失败点是 `tab.wait.ele_displayed('tag:h1')` 触发 `KeyError('searchId')`。
- 用最小 fake tab 复现 CDP search error 路径，避免每次都访问生产站点。
- 如需要本地实测，只访问 meat mixer 单 URL，不做高频刷新，不扩大 URL 集合。
- 确认修复方向仅为 JS 轻量轮询、有限定向重试、分阶段诊断，不增加反爬风险。

- [x] **Step 1.1: 写失败测试，模拟 H1 元素搜索触发 `KeyError('searchId')`**

测试目标：BassPro 产品身份等待不能依赖 `tab.wait.ele_displayed('tag:h1')`；当旧路径触发 CDP search error 时，应归类为 `cdp_search_error` 并允许定向重试。

```python
def test_basspro_product_identity_handles_cdp_search_error():
    scraper = BassProScraper()
    tab = FakeTab(js_results=["", "Cabela's Heavy-Duty 20-lb. Meat Mixer"])

    title = scraper._wait_product_identity(tab, timeout=3)

    assert title == "Cabela's Heavy-Duty 20-lb. Meat Mixer"
    assert tab.run_js_called
```

- [x] **Step 1.2: 运行测试确认失败**

Run:

```bash
uv run --frozen pytest tests/scrapers/test_basspro_readiness.py::test_basspro_product_identity_handles_cdp_search_error -q
```

Expected: FAIL，`_wait_product_identity` 不存在或仍走旧等待路径。

- [x] **Step 1.3: 实现 JS 轮询版产品身份等待**

在 `basspro.py` 内部新增私有方法，保持简洁，不抽成跨站点工具：

```python
def _wait_product_identity(self, tab, timeout=15):
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            text = tab.run_js("return document.querySelector('h1')?.innerText || document.title || ''")
            if text and text.strip():
                return text.strip()
        except KeyError as exc:
            if str(exc).strip("'") == "searchId":
                last_error = exc
            else:
                raise
        time.sleep(0.5)
    if last_error:
        raise RuntimeError("basspro product_identity cdp_search_error") from last_error
    raise TimeoutError("basspro product_identity timeout")
```

注意：具体异常类型与消息可按现有代码风格微调，不新增无关 type hint。

- [x] **Step 1.4: 替换 scrape 中的 H1 等待调用**

将 `tab.wait.ele_displayed('tag:h1', timeout=15)` 替换为 `_wait_product_identity(tab, timeout=15)`。

- [x] **Step 1.5: 写失败测试，age gate 晚出现时会多阶段关闭**

```python
def test_basspro_dismisses_age_gate_at_multiple_stages(monkeypatch):
    scraper = BassProScraper()
    calls = []
    monkeypatch.setattr(scraper, "_dismiss_age_gate", lambda tab: calls.append("dismiss"))

    scraper._prepare_after_navigation(FakeTab())

    assert len(calls) >= 2
```

- [x] **Step 1.6: 实现轻量阶段 hook**

在不大改结构的前提下，在以下点调用 `_dismiss_age_gate(tab)`：
- `tab.get(url)` 后
- `_wait_product_identity()` 后
- BV summary 前
- reviews 展开前

边界要求：
- 每个阶段只做轻量检测和必要点击，不新增循环点击。
- age gate 未出现时必须快速返回。
- age gate 出现但关闭失败时记录 diagnostics，不允许无限重试。

- [x] **Step 1.7: 写失败测试，BV shadow 为空时记录 stop reason**

```python
def test_basspro_reviews_shadow_empty_records_diagnostics():
    scraper = BassProScraper()
    tab = FakeTab(shadow_count=0, bv_container=True)

    reviews, diagnostics = scraper._load_all_reviews(tab, return_diagnostics=True)

    assert reviews == []
    assert diagnostics["stop_reason"] == "shadow_empty"
```

- [x] **Step 1.8: 实现 BassPro diagnostics 字段**

最小字段：
- `stage`
- `age_gate_seen`
- `bv_container_seen`
- `summary_count`
- `shadow_count`
- `load_more_state`
- `stop_reason`

不要引入复杂类层级；可以先用 dict。

- [x] **Step 1.9: 跑 BassPro 定向测试**

Run:

```bash
uv run --frozen pytest tests/scrapers/test_basspro_readiness.py -q
```

Expected: PASS。

- [x] **Step 1.10: 爬虫边界验证清单**

在应用到主链路前，确认以下场景都有测试或明确验证记录：

- H1 正常出现：成功返回产品身份。
- H1 晚出现：JS 轮询等待后成功。
- H1 始终不出现：超时并记录 `product_identity` 阶段。
- `KeyError('searchId')`：归类为 `cdp_search_error`，只允许有限定向重试。
- age gate 晚出现：后续阶段仍能检测并关闭。
- BV 容器缺失：记录 `bv_container_missing`。
- BV 容器存在但 shadow section 为 0：记录 `shadow_empty`。
- load more 消失或不可点：记录停止原因，不伪装为完整采集。

---

## Chunk 2: Task result 采集真相契约

### Task 2: 保存 expected/saved/failed URL

**Files:**
- Modify: `qbu_crawler/server/task_manager.py`
- Modify: `qbu_crawler/models.py`
- Test: `tests/server/test_task_manager_failed_urls.py`

- [x] **Step 2.1: 写失败测试，单 URL 失败进入 task result**

```python
def test_task_result_records_failed_url(monkeypatch, tmp_path):
    manager = TaskManager(max_workers=1)
    url = "https://www.basspro.com/p/cabelas-heavy-duty-20-lb-meat-mixer"

    monkeypatch.setattr("qbu_crawler.server.task_manager.get_scraper", failing_scraper_factory)

    task = manager.submit_scrape([url])
    wait_until_task_finished(task.id)

    saved_task = models.get_task(task.id)
    result = saved_task["result"]
    assert result["expected_url_count"] == 1
    assert result["failed_url_count"] == 1
    assert result["failed_urls"][0]["url"] == url
    assert result["failed_urls"][0]["error_type"] == "KeyError"
```

测试内新增 `wait_until_task_finished(task_id)` 小 helper，通过 `models.get_task(task_id)` 轮询到 `completed/failed/cancelled`，不要要求生产 `TaskManager` 新增测试专用 API。

- [x] **Step 2.2: 运行测试确认失败**

Run:

```bash
uv run --frozen pytest tests/server/test_task_manager_failed_urls.py::test_task_result_records_failed_url -q
```

Expected: FAIL，result 缺少 failed URL 字段。

- [x] **Step 2.3: 在 task_manager 聚合 expected/saved/failed URL**

实现要求：
- `expected_urls` 从提交参数或当前 URL 列表取得。
- 每个 URL 成功保存后进入 `saved_urls`。
- 每个 URL 捕获异常后进入 `failed_urls`，包括 `url/site/stage/error_type/error_message/diagnostics`。
- 不改变“部分 URL 失败后继续跑后续 URL”的现有行为。

- [x] **Step 2.4: 给失败异常补 stage**

如果 scraper 抛出的异常没有 stage，task_manager 默认使用当前阶段：
- scraper 构造失败：`scraper_init`
- scrape 调用失败：`scrape`
- 保存失败：`persist`

- [x] **Step 2.5: models 查询保持兼容**

如现有 `models.list_workflow_run_tasks()` 没有返回 `params/result`，补齐字段；旧调用方不应受影响。

- [x] **Step 2.6: 跑 task result 测试**

Run:

```bash
uv run --frozen pytest tests/server/test_task_manager_failed_urls.py -q
```

Expected: PASS。

---

## Chunk 3: Workflow quality、run log 与运维邮件

### Task 3: 用 expected URL 与 saved/failed URL 对账

**Files:**
- Modify: `qbu_crawler/server/scrape_quality.py`
- Modify: `qbu_crawler/server/run_log.py`
- Modify: `qbu_crawler/server/workflows.py`
- Test: `tests/server/test_scrape_quality.py`
- Test: `tests/server/test_run_log.py`
- Test: `tests/server/test_workflow_ops_alert_wiring.py`

- [x] **Step 3.1: 写失败测试，expected 8 saved 7 failed 1**

```python
def test_scrape_quality_uses_expected_and_failed_urls():
    summary = summarize_scrape_quality(
        products=[{"url": "u1"}, {"url": "u2"}],
        tasks=[{
            "params": {"urls": ["u1", "u2", "u3"]},
            "result": {
                "saved_urls": ["u1", "u2"],
                "failed_urls": [{"url": "u3", "stage": "product_identity", "error_type": "KeyError"}],
            },
        }],
    )

    assert summary["expected_url_count"] == 3
    assert summary["saved_product_count"] == 2
    assert summary["failed_url_count"] == 1
    assert summary["failed_urls"][0]["url"] == "u3"
```

- [x] **Step 3.2: 修改 `summarize_scrape_quality()` 签名**

兼容旧调用：

```python
def summarize_scrape_quality(products, *, low_coverage_threshold=0.6, tasks=None):
```

当 `tasks is None` 时保持旧逻辑；当 tasks 存在时优先用 expected/saved/failed URL 对账。

- [x] **Step 3.3: 写失败测试，run log 写入失败 URL 明细**

```python
def test_run_log_records_failed_url_details(tmp_path):
    lines = build_quality_log_lines({
        "expected_url_count": 8,
        "saved_product_count": 7,
        "failed_url_count": 1,
        "failed_urls": [{
            "url": "https://www.basspro.com/p/cabelas-heavy-duty-20-lb-meat-mixer",
            "stage": "product_identity",
            "error_type": "KeyError",
            "error_message": "'searchId'",
        }],
    })

    text = "\n".join(lines)
    assert "expected_urls=8" in text
    assert "saved_products=7" in text
    assert "failed_url_count=1" in text
    assert "product_identity" in text
    assert "searchId" in text
```

- [x] **Step 3.4: 更新 run log 输出**

保持文本简洁，加入：
- expected URLs
- saved products
- failed URL count
- missing without error count
- failed URL 明细，最多输出前 20 个

- [x] **Step 3.5: workflow 传入 tasks**

在 `_advance_run()` 质量统计处读取当前 run 的 tasks，把 tasks 与 snapshot products 一起传给 `summarize_scrape_quality()`。

- [x] **Step 3.6: 运维邮件摘要改用 failed URL 事实**

业务报告不变。运维邮件中加入：
- `计划 8 个 URL，入库 7 个产品，失败 1 个 URL`
- `失败：BassPro product_identity KeyError 'searchId'`
- run log 路径

状态边界：
- P4 不强制把已成功生成完整业务报告的 workflow 改成 `needs_attention`。
- `failed_url_count > 0` 必须触发 ops alert / internal quality flag，并进入 run log、运维邮件和 manifest/analytics 内部字段。
- 如果报告生成本身失败，仍沿用已有 `needs_attention` 语义。

- [x] **Step 3.7: 跑质量与运维测试**

Run:

```bash
uv run --frozen pytest tests/server/test_scrape_quality.py tests/server/test_run_log.py tests/server/test_workflow_ops_alert_wiring.py -q
```

Expected: PASS。

---

## Chunk 4: Contract 真实 snapshot 刷新

### Task 4: 禁止空 snapshot 派生字段污染最终 HTML

**Files:**
- Modify: `qbu_crawler/server/report_contract.py`
- Modify: `qbu_crawler/server/report_common.py`
- Test: `tests/server/test_report_contract.py`
- Test: `tests/server/test_report_contract_renderers.py`

- [x] **Step 4.1: 写失败测试，bootstrap digest 从真实 snapshot 重算**

```python
def test_contract_refresh_rebuilds_bootstrap_digest_from_real_snapshot():
    analytics = {
        "report_semantics": "bootstrap",
        "report_user_contract": {
            "contract_context": {"snapshot_fingerprint": "empty"},
            "bootstrap_digest": {
                "baseline_summary": {"product_count": 0, "review_count": 0}
            },
        },
    }
    snapshot = {
        "products": [{"id": i} for i in range(7)],
        "reviews": [{"id": i} for i in range(565)],
    }

    contract = build_report_user_contract(snapshot=snapshot, analytics=analytics)

    summary = contract["bootstrap_digest"]["baseline_summary"]
    assert summary["product_count"] == 7
    assert summary["review_count"] == 565
```

- [x] **Step 4.2: 实现 snapshot fingerprint 与派生字段重算**

重算字段：
- `bootstrap_digest`
- `action_priorities[*].affected_products_count`
- `issue_diagnostics[*].evidence_count`
- `competitor_insights.<section>[*].products/evidence_count`

保留字段：
- LLM 改写后的 `full_action` / `short_action`，但 evidence IDs 必须仍匹配。

- [x] **Step 4.3: normalize 阶段刷新 contract**

`normalize_deep_report_analytics()` 在有真实 snapshot 参数时必须调用刷新逻辑。没有真实 snapshot 时只能标记临时 context，不得让临时 context 被最终渲染误认为真实。

- [x] **Step 4.4: 跑 contract 测试**

Run:

```bash
uv run --frozen pytest tests/server/test_report_contract.py tests/server/test_report_contract_renderers.py -q
```

Expected: PASS。

---

## Chunk 5: Renderer 统一 pre-normalized analytics

### Task 5: HTML / Excel / 邮件共用同一 contract-first 输入

**Files:**
- Modify: `qbu_crawler/server/report_snapshot.py`
- Modify: `qbu_crawler/server/report_html.py`
- Modify: `qbu_crawler/server/report.py`
- Test: `tests/server/test_report_contract_renderers.py`
- Test: `tests/server/test_attachment_html_issues.py`
- Test: `tests/test_v3_excel.py`

- [x] **Step 5.1: 写失败测试，HTML 行动建议影响产品数不为 0**

```python
def test_html_action_priorities_use_contract_affected_count():
    analytics = {
        "report_user_contract": {
            "action_priorities": [{
                "full_action": "复核结构设计问题",
                "affected_products": ["A", "B", "C", "D", "E"],
                "affected_products_count": 5,
                "evidence_count": 30,
                "evidence_review_ids": [1, 2],
            }]
        }
    }

    html = render_attachment_html(snapshot_with_products_reviews(), analytics)

    assert "影响 5 款" in html
    assert "影响 0 款" not in html
```

- [x] **Step 5.2: 让 report_snapshot 只传 pre-normalized analytics**

full report 链路中，Excel、HTML、邮件使用同一个 normalized analytics 对象，不再 Excel 用 pre-normalized、HTML 用 raw analytics。

- [x] **Step 5.3: report_html legacy adapter 合并 LLM copy**

如果 HTML 入口仍需要兼容旧 analytics，必须先 adapter 成 contract，再渲染。不得在模板里直接拼旧 `report_copy.improvement_priorities`。

- [x] **Step 5.4: 模板静态测试**

新增或扩展测试，断言主模板不新增以下直接依赖：
- `low_coverage_products`
- `deadletter_count`
- `estimated_date_ratio`

- [x] **Step 5.5: 跑 renderer 测试**

Run:

```bash
uv run --frozen pytest tests/server/test_report_contract_renderers.py tests/server/test_attachment_html_issues.py tests/test_v3_excel.py -q
```

Expected: PASS。

---

## Chunk 6: LLM 数字校验与 KPI 语义

### Task 6: 扩展 known numbers 并修正评分口径

**Files:**
- Modify: `qbu_crawler/server/report_llm.py`
- Modify: `qbu_crawler/server/report_analytics.py`
- Test: `tests/server/test_report_contract_llm.py`
- Test: `tests/test_metric_semantics.py`

- [x] **Step 6.1: 写失败测试，contract evidence count 被视为已知事实**

```python
def test_llm_known_numbers_include_contract_evidence_counts():
    analytics = {
        "kpis": {},
        "report_user_contract": {
            "action_priorities": [{"evidence_count": 30, "affected_products_count": 5}],
            "issue_diagnostics": [{"evidence_count": 16}],
            "competitor_insights": {
                "avoid_competitor_failures": [{"evidence_count": 12}]
            },
        },
    }

    numbers = _collect_known_numbers(analytics)

    assert 30.0 in numbers
    assert 16.0 in numbers
    assert 12.0 in numbers
    assert 5.0 in numbers
```

- [x] **Step 6.2: 实现 known numbers 扩展**

只从 contract/kpis 中收集，不从 LLM 输出反向收集。

- [x] **Step 6.3: 写失败测试，sample_avg_rating 是全样本均分**

```python
def test_sample_avg_rating_uses_all_reviews_and_own_avg_is_separate():
    analytics = build_report_analytics({
        "products": [own_product, competitor_product],
        "reviews": [
            {"product_id": own_product["id"], "rating": 5},
            {"product_id": competitor_product["id"], "rating": 1},
        ],
    })

    assert analytics["kpis"]["sample_avg_rating"] == 3.0
    assert analytics["kpis"]["own_avg_rating"] == 5.0
```

- [x] **Step 6.4: 修正 report_analytics KPI 计算**

要求：
- `sample_avg_rating` 使用全量 reviews。
- `own_avg_rating` 使用自有产品 reviews。
- 如旧模板仍读取自有均分，迁移为 `own_avg_rating`。

- [x] **Step 6.5: 跑 LLM 与指标测试**

Run:

```bash
uv run --frozen pytest tests/server/test_report_contract_llm.py tests/test_metric_semantics.py -q
```

Expected: PASS。

---

## Chunk 7: Excel 竞品启示可追溯

### Task 7: contract competitor insights 分区 item 补字段并改 Excel 消费

**Files:**
- Modify: `qbu_crawler/server/report_contract.py`
- Modify: `qbu_crawler/server/report.py`
- Test: `tests/server/test_report_contract.py`
- Test: `tests/test_v3_excel.py`

- [x] **Step 7.1: 写失败测试，competitor insight 分区 item 保留 products 和 evidence IDs**

```python
def test_contract_competitor_insights_include_products_and_evidence_ids():
    contract = build_report_user_contract(
        snapshot=snapshot,
        analytics=analytics_with_competitor_reviews(),
    )
    item = contract["competitor_insights"]["avoid_competitor_failures"][0]

    assert item["products"]
    assert item["evidence_review_ids"]
    assert item["evidence_count"] == len(item["evidence_review_ids"])
```

- [x] **Step 7.2: 写失败测试，Excel 竞品启示不再显示产品为 `—`**

```python
def test_excel_competitor_insights_use_contract_products(tmp_path):
    path = generate_excel_with_contract(tmp_path, contract_with_competitor_insights())
    wb = load_workbook(path)
    ws = wb["竞品启示"]

    rows = list(ws.iter_rows(values_only=True))
    assert any("Cabela" in str(cell) for row in rows for cell in row)
    assert not all(row[1] == "—" for row in rows[1:])
```

- [x] **Step 7.3: 补齐 contract competitor insight 分区 item 字段**

字段：
- `label_code`
- `theme`
- `products`
- `evidence_review_ids`
- `evidence_count`
- `competitor_signal`
- `validation_hypothesis`

- [x] **Step 7.4: Excel 按分区只消费 contract item**

Excel 列建议：
- 主题
- 涉及竞品
- 证据数
- 证据评论 ID
- 竞品信号
- 验证假设

保留现有分区：`learn_from_competitors`、`avoid_competitor_failures`、`validation_hypotheses`。不要把长评论正文塞进主题列。

- [x] **Step 7.5: 跑 Excel 测试**

Run:

```bash
uv run --frozen pytest tests/server/test_report_contract.py tests/test_v3_excel.py -q
```

Expected: PASS。

---

## Chunk 8: 测试10 Replay、文档与最终验证

### Task 8: 补 replay、防回归文档和最终验证

**Files:**
- Create/Modify: `tests/fixtures/report_replay/test10_minimal/`
- Create: `docs/devlogs/D025-test10-p4-scrape-truth-and-report-contract.md`
- Modify: `docs/rules/basspro.md`
- Modify: `AGENTS.md`
- Test: `tests/server/test_test10_artifact_replay.py`

- [x] **Step 8.1: 建测试10最小 fixture**

包含：
- 7 个入库产品
- 565 条评论统计摘要
- 1 个 failed URL
- 空 snapshot 派生 contract 样本
- contract evidence counts：30/16/12

- [x] **Step 8.2: 写 replay 测试**

```python
def test_test10_replay_keeps_business_report_and_ops_log_separate():
    html, run_log = replay_test10_fixture()

    assert "当前截面：7 款产品 / 565 条评论" in html
    assert "影响 0 款" not in html
    assert "cabelas-heavy-duty-20-lb-meat-mixer" not in html
    assert "cabelas-heavy-duty-20-lb-meat-mixer" in run_log
    assert "KeyError" in run_log
```

- [x] **Step 8.3: 更新 BassPro 规则文档**

记录：
- 页面阶段
- age gate 多阶段轻量检测
- BV summary/shadow/load more 诊断
- `KeyError('searchId')` 归类与定向重试策略

- [x] **Step 8.4: 更新 AGENTS.md**

记录通用经验：
- DrissionPage 元素搜索可能出现 `DOM.getSearchResults` 缺 `searchId`，关键页面就绪判断优先用 JS 轮询。
- 批量采集必须持久化 expected/saved/failed URL，不得只看入库 snapshot 判断完整率。

- [x] **Step 8.5: 写 devlog**

记录：
- 测试10根因
- BassPro 修复点
- task/run log 契约
- report contract 修复点
- 验证命令与结果

- [x] **Step 8.6: 跑定向测试**

Run:

```bash
uv run --frozen pytest tests/scrapers/test_basspro_readiness.py tests/server/test_task_manager_failed_urls.py tests/server/test_scrape_quality.py tests/server/test_run_log.py tests/server/test_report_contract.py tests/server/test_report_contract_renderers.py tests/server/test_report_contract_llm.py tests/test_metric_semantics.py tests/test_v3_excel.py tests/server/test_test10_artifact_replay.py -q
```

Expected: PASS。

- [x] **Step 8.7: 可选本地 BassPro 实测**

只在网络和防护状态允许时执行：

```bash
$env:DB_PATH = Join-Path $PWD "data\\p4-basspro-smoke.db"
$env:REPORT_DIR = Join-Path $PWD "data\\p4-smoke-reports"
uv run python main.py "https://www.basspro.com/p/cabelas-heavy-duty-20-lb-meat-mixer"
```

Expected:
- 不再在 H1 阶段抛 `KeyError('searchId')`。
- 如果站点防护或 BV 失败，task result / run log 有结构化失败原因。
- 实测过程中不扩大 URL 集合、不高频刷新、不新增绕防爬行为。
- 实测写入隔离 DB / report 目录，不污染默认生产拷贝数据。

- [x] **Step 8.8: 跑全量测试**

Run:

```bash
uv run --frozen pytest -q
```

Expected: PASS。

- [x] **Step 8.9: 提交**

在确认没有混入用户未授权改动后提交：

```bash
git add qbu_crawler/scrapers/basspro.py qbu_crawler/server/task_manager.py qbu_crawler/models.py qbu_crawler/server/scrape_quality.py qbu_crawler/server/run_log.py qbu_crawler/server/workflows.py qbu_crawler/server/report_contract.py qbu_crawler/server/report_common.py qbu_crawler/server/report_html.py qbu_crawler/server/report_snapshot.py qbu_crawler/server/report_llm.py qbu_crawler/server/report_analytics.py qbu_crawler/server/report.py tests/scrapers/test_basspro_readiness.py tests/server/test_task_manager_failed_urls.py tests/server/test_scrape_quality.py tests/server/test_run_log.py tests/server/test_report_contract.py tests/server/test_report_contract_renderers.py tests/server/test_report_contract_llm.py tests/test_metric_semantics.py tests/test_v3_excel.py tests/server/test_test10_artifact_replay.py tests/fixtures/report_replay/test10_minimal docs/rules/basspro.md AGENTS.md docs/devlogs/D025-test10-p4-scrape-truth-and-report-contract.md
git commit -m "修复：测试10采集真相与报告契约纠偏"
```

---

## Review Checklist

- [x] 所有爬虫修改均已先复现或最小模拟复现，再进入实现。
- [x] 爬虫修复覆盖成功、晚出现、空数据、CDP 异常、站点防护页等边界情况。
- [x] 爬虫修复没有提高请求频率，没有新增激进刷新循环，没有绕过 Akamai/站点访问控制。
- [x] BassPro H1 就绪判断不再依赖 `tab.wait.ele_displayed('tag:h1')`。
- [x] age gate 在多个关键阶段轻量检测，不增加激进防爬风险。
- [x] task result 能回答 expected/saved/failed URL。
- [x] run log 能追踪失败 URL、阶段、错误类型和诊断字段。
- [x] 运维邮件有简要失败摘要，用户业务报告没有工程诊断。
- [x] HTML / Excel / 邮件共用刷新后的 `report_user_contract`。
- [x] bootstrap digest 不再保留空 snapshot 派生值。
- [x] LLM known numbers 包含 contract evidence counts。
- [x] `sample_avg_rating` 与全样本口径一致，`own_avg_rating` 单独存在。
- [x] Excel 竞品启示具备产品和 evidence IDs。
- [x] 测试10 replay 覆盖漏采、报告契约和运维隔离。
