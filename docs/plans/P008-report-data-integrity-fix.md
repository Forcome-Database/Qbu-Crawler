# P008 · 每日报告数据口径修复与数据质量监控

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除每日 change/quiet 报告中由爬虫字段缺失引发的噪音和 KPI 展示错误，把"数据质量事件"与"业务变动"分离，并加装数据质量告警。

**Architecture:** 在 `detect_snapshot_changes` 一处引入缺失值护栏（过滤 `None` / `"unknown"` / `""`），让 change 模式只触发于真实业务变动；修正 full/change/quiet 三种模式的 analytics 持久化与邮件 KPI 绑定，确保前后两次 run 读到的都是 normalize 后的完整 KPI；新增 `workflow_runs.scrape_quality` 列落盘每次采集的字段缺失统计，超阈值时追加数据质量告警邮件，与业务变动邮件完全独立。

**Tech Stack:** Python 3.10 + SQLite + jinja2 + pytest（沿用项目现有栈，无新依赖）

---

## 0 · 问题真实性复核（对当前 HEAD `ca5f079 v0.2.0`）

| ID | Bug | 位置（HEAD 现状） | 验证手段 |
|---|---|---|---|
| A | `detect_snapshot_changes` 不过滤 `None` / `"unknown"`，采集缺失被当成评分/库存/价格变动上报 | `qbu_crawler/server/report_snapshot.py:138,142,146,150` | run-4/run-5 change 邮件 5 条变动 0 真实；对照 `data/products.db.product_snapshots` 每天 rating_null=1-3，stock='unknown' 偶发 |
| B | `_generate_full_report` 把 **raw** `analytics` 落盘（而非 `pre_normalized`），下一日 `prev_analytics.kpis` 缺 `health_index`/`high_risk_count`/`own_negative_review_rate_display` | `qbu_crawler/server/report_snapshot.py:907-910` 与 line 880 的 `pre_normalized` 不匹配 | run-3 full analytics JSON 的 `kpis` 只有 18 个 key；本地对 run-4 snapshot rerun `normalize_deep_report_analytics` 能得到 `health_index=95.0` |
| C | `email_change.html.j2` 的 KPI 读 `previous_analytics.kpis` 而非当日的 `analytics.kpis`，导致"评论样本量 1611"始终滞后一天 | `qbu_crawler/server/report_templates/email_change.html.j2:33` | 当日 cumulative 2579，邮件展示 1611（来自前一日 run-3 `own_review_rows`） |
| D | Stock 展示二分映射（非 `in_stock` 一律"缺货"），`unknown`（采集失败）被错误展示为"缺货" | `qbu_crawler/server/report_templates/email_change.html.j2:103-104` | run-4 邮件".5 HP Dual Grind Grinder 缺货→有货"，DB 实际 `unknown → in_stock` |
| E | 生产跑 `0.1.54`，`242b4b3` 修复 commit（4/16 15:55）比邮件发送（15:44）晚 11 分钟，且 run-5 发出时 17h 后仍是 0.1.54 | `workflow_runs.service_version`：run-1=0.1.52 / run-4=0.1.54 / run-5=0.1.54 | 部署流程无 version-gap 检查 |
| G | 爬虫字段缺失无任何出口，每天稳定 3-7% 产品缺 rating 或 stock，无监控无告警 | `workflow_runs` 表无 scrape_quality 类字段 | DB 聚合：2026-04-13..17 每日 rating_null=1/1/3/3/2 |
| I | `review_count_changes` 被收集但不置 `has_changes`、模板也不展示，半死代码 | `qbu_crawler/server/report_snapshot.py:150-151` 与 `email_change.html.j2` 无对应 section | 代码阅读 |

不纳入本计划（优先级 P2/P3，独立推进）：
- H · quiet 模式 `analytics_path` 在 snapshot 无 cumulative 时不写（当前实测已随 P007 cumulative 引入而自愈，仅遗留在 0.1.52 老 snapshot）
- K · `high_risk_count` 绝对阈值对低基数太宽容（需要重做评分模型）
- L · `snapshot_hash` 不覆盖 cumulative（架构层面，风险低）

---

## 1 · 文件布局

| 改动 | 文件 | 职责 |
|---|---|---|
| 修改 | `qbu_crawler/server/report_snapshot.py` | 新增 `_is_missing_value()`；`detect_snapshot_changes` 加护栏；删 `review_count_changes`；`_generate_full_report` 改写 `pre_normalized` |
| 修改 | `qbu_crawler/server/report_templates/email_change.html.j2` | KPI 取自 `analytics`；stock 三态映射 |
| 修改 | `qbu_crawler/server/report_templates/quiet_day_report.html.j2` | stock 三态映射（保持与 email 一致） |
| 修改 | `qbu_crawler/server/report_snapshot.py` 的 `_send_mode_email` | 把当日 `effective_analytics` 显式作为 `analytics` 参数传入 change/quiet 邮件（确认已传，仅需模板改读） |
| 修改 | `qbu_crawler/models.py` | `workflow_runs` 新列 `scrape_quality TEXT`；新增 `update_scrape_quality(run_id, quality_dict)` |
| 修改 | `qbu_crawler/server/workflows.py` | 采集阶段结束后计算字段缺失率，写 `scrape_quality`；超阈值追加独立的数据质量告警邮件 |
| 新建 | `qbu_crawler/server/scrape_quality.py` | 封装"从 snapshot 产品列表统计字段缺失数"的纯函数，便于单测 |
| 修改 | `tests/test_v3_modes.py` | 补齐 `detect_snapshot_changes` 的 None/unknown 护栏测试 |
| 新建 | `tests/test_scrape_quality.py` | 字段缺失统计与告警阈值判定测试 |
| 修改 | `tests/test_report_integration.py` | Full report JSON 含 `health_index` / change 邮件 KPI 对齐当日 |
| 修改 | `CLAUDE.md` | 在"通用架构决策"段追加"缺失值护栏"与"数据质量监控"两项 |
| 新建 | `docs/devlogs/D008-report-data-integrity.md` | 记录本次修复的根因与验证过程 |

---

## 2 · 任务分解

### Task 1：`detect_snapshot_changes` 的缺失值护栏（核心止血）

**Files:**
- Modify: `qbu_crawler/server/report_snapshot.py:102-159`
- Modify: `tests/test_v3_modes.py`（新增测试）

**修复契约：**
- 约定三类"缺失"：`None`、空字符串 `""`、字符串字面量 `"unknown"`（爬虫对 stock 的显式缺失标记）。
- 任何字段从"缺失 → 有值"或"有值 → 缺失"的过渡，一律**不算**业务变动（由数据质量通道处理，见 Task 6）。
- 仅"有值 A → 有值 B 且 A != B"算真变动。

- [ ] **Step 1.1 — 添加失败测试：None/unknown 过渡不应触发变动**

把以下测试追加到 `tests/test_v3_modes.py`（放在现有 `TestDetectSnapshotChanges` 同类测试之后；若无 class，放文件末尾）：

```python
class TestDetectSnapshotChangesMissingValueGuard:
    """Bug A regression — 采集缺失不应被当作业务变动。"""

    def test_rating_none_to_real_is_not_a_change(self):
        previous = {"products": [{"sku": "S1", "name": "P1", "rating": None,
                                   "price": 10.0, "stock_status": "in_stock",
                                   "review_count": 5}]}
        current = {"products": [{"sku": "S1", "name": "P1", "rating": 4.8,
                                  "price": 10.0, "stock_status": "in_stock",
                                  "review_count": 5}]}
        from qbu_crawler.server.report_snapshot import detect_snapshot_changes
        result = detect_snapshot_changes(current, previous)
        assert result["rating_changes"] == []
        assert result["has_changes"] is False

    def test_rating_real_to_none_is_not_a_change(self):
        previous = {"products": [{"sku": "S1", "name": "P1", "rating": 4.8,
                                   "price": 10.0, "stock_status": "in_stock",
                                   "review_count": 5}]}
        current = {"products": [{"sku": "S1", "name": "P1", "rating": None,
                                  "price": 10.0, "stock_status": "in_stock",
                                  "review_count": 5}]}
        from qbu_crawler.server.report_snapshot import detect_snapshot_changes
        result = detect_snapshot_changes(current, previous)
        assert result["rating_changes"] == []
        assert result["has_changes"] is False

    def test_stock_unknown_to_in_stock_is_not_a_change(self):
        previous = {"products": [{"sku": "S1", "name": "P1", "rating": 4.8,
                                   "price": 10.0, "stock_status": "unknown",
                                   "review_count": 5}]}
        current = {"products": [{"sku": "S1", "name": "P1", "rating": 4.8,
                                  "price": 10.0, "stock_status": "in_stock",
                                  "review_count": 5}]}
        from qbu_crawler.server.report_snapshot import detect_snapshot_changes
        result = detect_snapshot_changes(current, previous)
        assert result["stock_changes"] == []
        assert result["has_changes"] is False

    def test_stock_in_stock_to_out_of_stock_is_a_real_change(self):
        previous = {"products": [{"sku": "S1", "name": "P1", "rating": 4.8,
                                   "price": 10.0, "stock_status": "in_stock",
                                   "review_count": 5}]}
        current = {"products": [{"sku": "S1", "name": "P1", "rating": 4.8,
                                  "price": 10.0, "stock_status": "out_of_stock",
                                  "review_count": 5}]}
        from qbu_crawler.server.report_snapshot import detect_snapshot_changes
        result = detect_snapshot_changes(current, previous)
        assert len(result["stock_changes"]) == 1
        assert result["stock_changes"][0]["old"] == "in_stock"
        assert result["stock_changes"][0]["new"] == "out_of_stock"
        assert result["has_changes"] is True

    def test_price_none_to_real_is_not_a_change(self):
        previous = {"products": [{"sku": "S1", "name": "P1", "rating": 4.8,
                                   "price": None, "stock_status": "in_stock",
                                   "review_count": 5}]}
        current = {"products": [{"sku": "S1", "name": "P1", "rating": 4.8,
                                  "price": 19.99, "stock_status": "in_stock",
                                  "review_count": 5}]}
        from qbu_crawler.server.report_snapshot import detect_snapshot_changes
        result = detect_snapshot_changes(current, previous)
        assert result["price_changes"] == []
        assert result["has_changes"] is False

    def test_price_real_to_real_crosses_threshold(self):
        previous = {"products": [{"sku": "S1", "name": "P1", "rating": 4.8,
                                   "price": 10.00, "stock_status": "in_stock",
                                   "review_count": 5}]}
        current = {"products": [{"sku": "S1", "name": "P1", "rating": 4.8,
                                  "price": 12.50, "stock_status": "in_stock",
                                  "review_count": 5}]}
        from qbu_crawler.server.report_snapshot import detect_snapshot_changes
        result = detect_snapshot_changes(current, previous)
        assert len(result["price_changes"]) == 1
        assert result["price_changes"][0]["old"] == 10.00
        assert result["price_changes"][0]["new"] == 12.50
```

- [ ] **Step 1.2 — 运行测试，确认都失败**

```bash
uv run pytest tests/test_v3_modes.py::TestDetectSnapshotChangesMissingValueGuard -v
```

预期：6 条用例中，`test_rating_none_to_real_is_not_a_change` / `test_rating_real_to_none_is_not_a_change` / `test_stock_unknown_to_in_stock_is_not_a_change` / `test_price_none_to_real_is_not_a_change` 失败；另外两条本就通过（行为保留）。

- [ ] **Step 1.3 — 实现护栏**

把 `qbu_crawler/server/report_snapshot.py` 第 102-159 行替换为：

```python
_MISSING_SENTINELS = (None, "", "unknown")


def _is_missing(value) -> bool:
    """判断字段值是否为"采集缺失"（不是真实业务状态）。

    爬虫对三类缺失的约定：
      - None：字段未被提取到（如 rating 无法解析）
      - "unknown"：stock_status 的显式失败标记
      - ""：极少数字段的默认空值
    """
    return value in _MISSING_SENTINELS


def _price_changed(a, b) -> bool:
    """只在双侧都是有效值且差值 >= 0.01 时判定变动。"""
    if _is_missing(a) or _is_missing(b):
        return False
    return abs(float(a) - float(b)) >= 0.01


def _simple_changed(a, b) -> bool:
    """stock / rating 通用：双侧都是有效值且不相等。"""
    if _is_missing(a) or _is_missing(b):
        return False
    return a != b


def detect_snapshot_changes(current_snapshot, previous_snapshot):
    """Compare two snapshots for real business changes.

    Missing values (采集失败) are NOT treated as business changes.
    Data-quality events are surfaced through a separate channel — see
    qbu_crawler/server/scrape_quality.py and workflows.py.

    Returns dict with: has_changes, price_changes, stock_changes,
    rating_changes, new_products, removed_products.
    """
    changes = {
        "has_changes": False,
        "price_changes": [], "stock_changes": [], "rating_changes": [],
        "new_products": [], "removed_products": [],
    }

    if previous_snapshot is None:
        return changes

    prev_by_sku = {p["sku"]: p for p in previous_snapshot.get("products", [])}

    for product in current_snapshot.get("products", []):
        sku = product.get("sku", "")
        prev = prev_by_sku.get(sku)
        if not prev:
            changes["new_products"].append(product)
            changes["has_changes"] = True
            continue

        name = product.get("name", sku)

        if _price_changed(product.get("price"), prev.get("price")):
            changes["price_changes"].append(
                {"sku": sku, "name": name,
                 "old": prev.get("price"), "new": product.get("price")})
            changes["has_changes"] = True

        if _simple_changed(product.get("stock_status"), prev.get("stock_status")):
            changes["stock_changes"].append(
                {"sku": sku, "name": name,
                 "old": prev.get("stock_status"), "new": product.get("stock_status")})
            changes["has_changes"] = True

        if _simple_changed(product.get("rating"), prev.get("rating")):
            changes["rating_changes"].append(
                {"sku": sku, "name": name,
                 "old": prev.get("rating"), "new": product.get("rating")})
            changes["has_changes"] = True

    current_skus = {p.get("sku") for p in current_snapshot.get("products", [])}
    for sku, prev_product in prev_by_sku.items():
        if sku not in current_skus:
            changes["removed_products"].append(prev_product)
            changes["has_changes"] = True

    return changes
```

说明：上面的实现同时承担了 Task 5（删除 `review_count_changes` 死代码）——已从返回 dict 移除。

- [ ] **Step 1.4 — 运行所有相关测试**

```bash
uv run pytest tests/test_v3_modes.py -v
```

预期：Task 1.1 新增 6 条全部 PASS；原有 `test_v3_modes.py` 其他用例全部 PASS。

若原有用例依赖 `review_count_changes` key：把这类断言改为 `assert "review_count_changes" not in result`，并在同一提交里完成（避免 Task 5 重复改动）。先 grep 确认：

```bash
uv run grep -rn "review_count_changes" tests/
```

若存在结果，同步清理。

- [ ] **Step 1.5 — 提交**

```bash
git add qbu_crawler/server/report_snapshot.py tests/test_v3_modes.py
git commit -m "fix(report): filter missing values in detect_snapshot_changes

采集失败产生的 None/unknown 不再被当成业务变动上报。
- 统一引入 _is_missing(v) 判缺失
- rating/stock/price/review_count 全部改走护栏函数
- 顺带删除未被使用的 review_count_changes 字段

修复 Bug A+I。run-4/run-5 邮件中 7 条抖动误报将在下次运行时消失。"
```

---

### Task 2：Full report 落盘 `pre_normalized` analytics

**Files:**
- Modify: `qbu_crawler/server/report_snapshot.py:907-910`
- Modify: `tests/test_report_integration.py` 或 `tests/test_v3_modes.py`（新增集成测试）

- [ ] **Step 2.1 — 添加失败测试：Full analytics JSON 含 `health_index`**

追加到 `tests/test_v3_modes.py`（继续在 Task 1 的新 class 下一位置）：

```python
class TestFullReportAnalyticsPersistsNormalizedKpis:
    """Bug B regression —  full report JSON 必须含 normalize 后的 KPI。"""

    def test_full_analytics_json_contains_health_index(self, tmp_path, monkeypatch):
        """Full report 落盘的 analytics JSON 应包含 normalize 产物，
        否则下一日 change/quiet 的 KPI 区块会全部回退成 '—'。"""
        from qbu_crawler import config
        monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))

        # 造一个最小但完整的 snapshot（28 own + 13 competitor 量级，
        # 保证 build_report_analytics 内部 health/risk 逻辑不会短路）
        import json
        from pathlib import Path
        from qbu_crawler.server.report_snapshot import generate_full_report_from_snapshot
        snapshot = _build_minimal_full_snapshot(run_id=999, with_cumulative=True)

        # 屏蔽邮件与 LLM（测试只关心 JSON 落盘内容）
        monkeypatch.setattr(
            "qbu_crawler.server.report_snapshot.report.send_email",
            lambda **kw: {"success": True, "recipients": []})
        monkeypatch.setattr(
            "qbu_crawler.server.report_llm.generate_report_insights",
            lambda *a, **kw: {"hero_headline": "", "executive_bullets": []})

        result = generate_full_report_from_snapshot(snapshot, send_email=False)

        analytics_path = result.get("analytics_path")
        assert analytics_path and Path(analytics_path).exists()
        data = json.loads(Path(analytics_path).read_text(encoding="utf-8"))
        kpis = data.get("kpis") or {}
        # 这些字段都是 normalize_deep_report_analytics 的产物
        assert "health_index" in kpis, \
            f"kpis 应含 health_index，当前 keys={sorted(kpis.keys())}"
        assert "high_risk_count" in kpis
        assert "own_negative_review_rate_display" in kpis
        # 同时应有 normalize 产物的顶层字段（用作可回归对照）
        assert "mode_display" in data
        assert "kpi_cards" in data


def _build_minimal_full_snapshot(run_id: int, with_cumulative: bool):
    """复用已有 factory；若无，用最少产品+评论组装一个能通过 build_report_analytics 的 snapshot。"""
    products = [
        {"sku": f"OWN{i}", "name": f"Own {i}", "site": "waltons",
         "url": f"https://x/{i}", "price": 10.0, "stock_status": "in_stock",
         "rating": 4.6, "review_count": 20, "ownership": "own"}
        for i in range(5)
    ] + [
        {"sku": f"CMP{i}", "name": f"Comp {i}", "site": "basspro",
         "url": f"https://y/{i}", "price": 12.0, "stock_status": "in_stock",
         "rating": 4.0, "review_count": 30, "ownership": "competitor"}
        for i in range(3)
    ]
    reviews = [
        {"id": idx, "product_id": None, "product_sku": p["sku"],
         "product_name": p["name"], "site": p["site"], "ownership": p["ownership"],
         "rating": 5, "headline": "ok", "body": "great",
         "body_cn": "不错", "headline_cn": "还行",
         "author": f"u{idx}", "date_published": "2026-04-16",
         "scraped_at": "2026-04-16T12:00:00+08:00", "images": []}
        for idx, p in enumerate(products)
    ]
    snap = {
        "run_id": run_id, "logical_date": "2026-04-16",
        "data_since": "2026-04-16T00:00:00+08:00",
        "data_until": "2026-04-17T00:00:00+08:00",
        "snapshot_at": "2026-04-16T15:00:00+08:00",
        "snapshot_hash": "test-hash",
        "products": products, "products_count": len(products),
        "reviews": reviews, "reviews_count": len(reviews),
        "translated_count": len(reviews), "untranslated_count": 0,
    }
    if with_cumulative:
        snap["cumulative"] = {
            "products": products, "products_count": len(products),
            "reviews": reviews, "reviews_count": len(reviews),
            "translated_count": len(reviews), "untranslated_count": 0,
        }
    return snap
```

- [ ] **Step 2.2 — 运行测试，确认 fail**

```bash
uv run pytest tests/test_v3_modes.py::TestFullReportAnalyticsPersistsNormalizedKpis -v
```

预期：`AssertionError: kpis 应含 health_index，当前 keys=[...]`（缺失） 。

- [ ] **Step 2.3 — 修复 `_generate_full_report`**

打开 `qbu_crawler/server/report_snapshot.py`，定位到第 907-910 行：

```python
        Path(analytics_path).write_text(
            json.dumps(analytics, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
```

替换为：

```python
        # Write the normalized analytics (with health_index / high_risk_count /
        # own_negative_review_rate_display etc.). The raw `analytics` object is
        # kept in memory for downstream Excel/V3-HTML calls, but the on-disk
        # JSON must match what the next run's `prev_analytics` consumer
        # (email_change.html.j2 / quiet_day_report.html.j2) expects.
        Path(analytics_path).write_text(
            json.dumps(pre_normalized, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
```

注意：`pre_normalized` 已由第 880 行 `pre_normalized = normalize_deep_report_analytics(analytics)` 算好，无需重复 normalize。`analytics` 对象后续仍作为 raw 传给 `report.generate_excel(...)` 和 `report_html.render_v3_html(...)`，它们各自内部会再 normalize 一次，行为不变。

- [ ] **Step 2.4 — 运行测试验证通过**

```bash
uv run pytest tests/test_v3_modes.py::TestFullReportAnalyticsPersistsNormalizedKpis -v
uv run pytest tests/ -k "report" -x
```

预期：新测试 PASS；已有 report 相关测试全部 PASS。

- [ ] **Step 2.5 — 提交**

```bash
git add qbu_crawler/server/report_snapshot.py tests/test_v3_modes.py
git commit -m "fix(report): persist normalized analytics for full reports

之前 full report 落盘的是 raw analytics，导致下一日 change/quiet
模式从 prev_analytics.kpis 读 health_index 时返回 None，邮件 KPI
全部退化成 '—'。

修复 Bug B。change/quiet 邮件的 KPI 区块下次 full run 完成后恢复正常。"
```

---

### Task 3：Change/Quiet 邮件 KPI 绑当日累积，不再滞后一天

**Files:**
- Modify: `qbu_crawler/server/report_templates/email_change.html.j2:33`
- Modify: `qbu_crawler/server/report_templates/quiet_day_report.html.j2`（对照位置）
- Modify: `tests/test_v3_modes.py`（集成校验）

**修复契约：** change/quiet 邮件展示的"当前健康快照"必须来自当日 `analytics`（`effective_analytics` 已传）；仅在 `analytics` 完全缺失时才回退 `previous_analytics`。

- [ ] **Step 3.1 — 确认当日 analytics 已作为 `analytics=` 传给模板**

阅读 `_send_mode_email`（`report_snapshot.py:459-513`）确认以下 dict key 存在：

```python
body_html = template.render(
    ...
    analytics=analytics or prev_analytics or {},
    previous_analytics=prev_analytics,
    ...
)
```

已确认。此步骤无代码改动，仅核实。

- [ ] **Step 3.2 — 添加失败测试：change 邮件 KPI 来自当日 cumulative**

追加到 `tests/test_v3_modes.py`：

```python
class TestChangeEmailKpiBindsToCurrentAnalytics:
    """Bug C regression — change 邮件 KPI 必须反映当日，而不是前一日。"""

    def test_change_email_uses_current_own_review_rows(self, monkeypatch, tmp_path):
        from qbu_crawler import config
        monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path))
        # 前一日 own=100，当日 cumulative own=250
        prev = {"kpis": {"own_review_rows": 100, "health_index": 80,
                         "own_negative_review_rate_display": "2.0%",
                         "high_risk_count": 0}}
        cur = {"kpis": {"own_review_rows": 250, "health_index": 92,
                        "own_negative_review_rate_display": "1.2%",
                        "high_risk_count": 1}}
        snapshot = {"logical_date": "2026-04-16",
                    "snapshot_at": "2026-04-16T15:00:00+08:00"}
        changes = {"rating_changes": [], "price_changes": [],
                   "stock_changes": []}

        from jinja2 import Environment, FileSystemLoader, select_autoescape
        from pathlib import Path as _P
        tpl_dir = _P("qbu_crawler/server/report_templates")
        env = Environment(
            loader=FileSystemLoader(str(tpl_dir)),
            autoescape=select_autoescape(["html", "j2"]))
        template = env.get_template("email_change.html.j2")
        html = template.render(
            logical_date="2026-04-16",
            snapshot=snapshot, analytics=cur, previous_analytics=prev,
            changes=changes, threshold=2)

        # 当日 own=250 应出现；昨天 own=100 不应出现
        assert ">250<" in html, "评论总量应展示当日 250"
        assert ">100<" not in html, "不应再展示昨天的 100"
        # health_index 同理
        assert ">92<" in html
        assert ">80<" not in html
```

- [ ] **Step 3.3 — 运行测试，确认 fail**

```bash
uv run pytest tests/test_v3_modes.py::TestChangeEmailKpiBindsToCurrentAnalytics -v
```

预期：`assert ">250<" in html` 失败，因为模板当前读的是 `previous_analytics`。

- [ ] **Step 3.4 — 修复 `email_change.html.j2`**

打开 `qbu_crawler/server/report_templates/email_change.html.j2`，定位到第 33 行：

```jinja
  {% set _kpis = (previous_analytics or {}).get("kpis", {}) %}
```

替换为：

```jinja
  {# KPI 快照优先取当日 analytics（effective_analytics）；
     仅当当日 analytics 生成失败时回退到昨日，避免展示空白。 #}
  {% set _kpis = (analytics or previous_analytics or {}).get("kpis", {}) %}
```

- [ ] **Step 3.5 — 同步修复 `quiet_day_report.html.j2`（如有类似绑定）**

搜索 `quiet_day_report.html.j2` 中是否有 `previous_analytics.get("kpis")` 直接绑定：

```bash
uv run grep -n "previous_analytics" qbu_crawler/server/report_templates/quiet_day_report.html.j2
```

把所有"展示当前快照 KPI"的取值统一改成 `(analytics or previous_analytics or {}).get("kpis", {})`。**注意**：quiet 模板中 `outstanding issues`（遗留问题）原本就该读昨天的 `previous_analytics.self.top_negative_clusters`，**不要动**那部分。

- [ ] **Step 3.6 — 运行测试**

```bash
uv run pytest tests/test_v3_modes.py::TestChangeEmailKpiBindsToCurrentAnalytics -v
uv run pytest tests/ -k "email or render" -x
```

预期：新测试 PASS；已有模板渲染测试 PASS。

- [ ] **Step 3.7 — 提交**

```bash
git add qbu_crawler/server/report_templates/email_change.html.j2 \
        qbu_crawler/server/report_templates/quiet_day_report.html.j2 \
        tests/test_v3_modes.py
git commit -m "fix(report): change/quiet 邮件 KPI 绑当日 analytics

原先模板永远读 previous_analytics.kpis，导致邮件展示的
评论总量/健康指数始终滞后一天。现改为优先读当日 analytics，
仅在当日 analytics 缺失时回退。

修复 Bug C。"
```

---

### Task 4：Stock 状态三态展示

**Files:**
- Modify: `qbu_crawler/server/report_templates/email_change.html.j2:103-104`
- Modify: `qbu_crawler/server/report_templates/quiet_day_report.html.j2`（对照位置）

**修复契约：** 即使 Task 1 的护栏会过滤掉 `unknown` 过渡，模板也要显式支持三态，以防：
  1. 后续新增其他采集失败标记（如 `"error"`）；
  2. 历史快照落地的 `unknown` 被手动排障时看到；
  3. `out_of_stock` → `in_stock` 的真实变动仍用绿色"有货"高亮。

- [ ] **Step 4.1 — 失败测试：stock 三态渲染**

追加到 `tests/test_v3_modes.py`：

```python
class TestStockStatusThreeStateDisplay:
    """Bug D regression — stock 模板不再把 unknown 显示为'缺货'。"""

    def _render_change_email(self, stock_changes):
        from jinja2 import Environment, FileSystemLoader, select_autoescape
        from pathlib import Path as _P
        tpl_dir = _P("qbu_crawler/server/report_templates")
        env = Environment(
            loader=FileSystemLoader(str(tpl_dir)),
            autoescape=select_autoescape(["html", "j2"]))
        return env.get_template("email_change.html.j2").render(
            logical_date="2026-04-16",
            snapshot={"logical_date": "2026-04-16",
                      "snapshot_at": "2026-04-16T15:00:00+08:00"},
            analytics={"kpis": {"own_review_rows": 100, "health_index": 80}},
            previous_analytics=None,
            changes={"stock_changes": stock_changes,
                     "price_changes": [], "rating_changes": []},
            threshold=2)

    def test_out_of_stock_to_in_stock_shows_huoqi_green(self):
        html = self._render_change_email([
            {"sku": "S1", "name": "P1",
             "old": "out_of_stock", "new": "in_stock"}])
        assert "有货" in html
        assert "缺货" in html   # 旧状态展示

    def test_unknown_old_state_renders_as_weizhi(self):
        """如果因为历史数据带着 unknown 走到模板，应显示'未知'。"""
        html = self._render_change_email([
            {"sku": "S1", "name": "P1",
             "old": "unknown", "new": "in_stock"}])
        assert "未知" in html
        # 关键：不应出现"缺货"（这是 Bug D 的核心错误展示）
        assert "缺货" not in html
```

- [ ] **Step 4.2 — 运行测试确认 fail**

```bash
uv run pytest tests/test_v3_modes.py::TestStockStatusThreeStateDisplay -v
```

预期：`test_unknown_old_state_renders_as_weizhi` 失败（当前模板会展示"缺货"）。

- [ ] **Step 4.3 — 修复 `email_change.html.j2` 的 stock 映射**

定位到 `email_change.html.j2` 第 100-106 行（Task 1 完成后行号可能漂移，按 `📦 库存变动` 锚定）。找到两处 `{{ "有货" if ... else "缺货" }}` 表达式。

在模板 `{% if _stock %}` 块正下方（`<div style="font-size:10px...">📦 库存变动...</div>` 之前）插入一个宏：

```jinja
      {% set _stock_display = {"in_stock": "有货", "out_of_stock": "缺货"} %}
      {% macro _stock_cell(status) -%}
        {{ _stock_display.get(status, "未知") }}
      {%- endmacro %}
```

然后把两处 `<td>` 改为：

```jinja
          <td style="padding:6px 10px;border-bottom:1px solid #e5e4e0;text-align:center;color:#8e8ea0;">{{ _stock_cell(item.get("old")) }}</td>
          <td style="padding:6px 10px;border-bottom:1px solid #e5e4e0;text-align:center;font-weight:700;color:{% if item.get('new') == 'in_stock' %}#047857{% elif item.get('new') == 'out_of_stock' %}#b91c1c{% else %}#8e8ea0{% endif %};">{{ _stock_cell(item.get("new")) }}</td>
```

要点：
- "未知" 对应 `color:#8e8ea0`（中性灰），避免红色带来恐慌
- 真实业务变动 `in_stock` 仍绿色 / `out_of_stock` 仍红色
- 有了 Task 1 的护栏后，实际上 `unknown` 不会出现在 `stock_changes` 里；这个改动主要是防御与未来兼容

- [ ] **Step 4.4 — 同步修复 `quiet_day_report.html.j2`**

搜索并同样替换：

```bash
uv run grep -n '"有货" if\|"缺货"' qbu_crawler/server/report_templates/quiet_day_report.html.j2
```

对每处都套同一套 `_stock_display` 策略。

- [ ] **Step 4.5 — 运行测试**

```bash
uv run pytest tests/test_v3_modes.py::TestStockStatusThreeStateDisplay -v
uv run pytest tests/ -k "template or email or render" -x
```

预期：PASS。

- [ ] **Step 4.6 — 提交**

```bash
git add qbu_crawler/server/report_templates/email_change.html.j2 \
        qbu_crawler/server/report_templates/quiet_day_report.html.j2 \
        tests/test_v3_modes.py
git commit -m "fix(report): stock 状态三态展示（in_stock/out_of_stock/未知）

原先非 in_stock 一律显示为'缺货'，把采集失败（unknown）误报成缺货。
改为显式 map + 默认'未知'+中性灰，消除用户误判。

修复 Bug D。"
```

---

### Task 5：删除 `review_count_changes` 死代码

在 Task 1 的 Step 1.3 中已随 `detect_snapshot_changes` 改写一并删除。本任务仅作收尾与清理。

- [ ] **Step 5.1 — 确认无其他引用**

```bash
uv run grep -rn "review_count_changes" qbu_crawler/ tests/ docs/
```

预期：无结果（Task 1 已清理）。若有残留，逐个删除。

- [ ] **Step 5.2 — 更新 CLAUDE.md 的架构决策段**

打开 `CLAUDE.md`，在"通用架构决策 · 数据存储策略"段落末尾追加一行：

```markdown
- **snapshot 变动检测使用"有效值闭区间"语义**：`detect_snapshot_changes` 仅在双侧字段都不是 `None`/`""`/`"unknown"` 时判定业务变动；采集缺失（数据质量事件）由独立告警通道（见下文"数据质量监控"）处理，不污染 change 邮件。
```

- [ ] **Step 5.3 — 提交**（若有改动）

```bash
git add CLAUDE.md
git commit -m "docs: document missing-value guard in change detection"
```

如果没有任何文件改动，跳过此 step。

---

### Task 6：数据质量监控（字段缺失统计 + 独立告警邮件）

**Files:**
- Create: `qbu_crawler/server/scrape_quality.py`
- Create: `tests/test_scrape_quality.py`
- Modify: `qbu_crawler/models.py`（ALTER TABLE + 读写函数）
- Modify: `qbu_crawler/server/workflows.py`（采集结束后汇总 + 触发告警）
- Modify: `.env.example`（新增阈值配置）
- Modify: `qbu_crawler/config.py`（读取阈值）
- Create: `qbu_crawler/server/report_templates/email_data_quality.html.j2`
- Modify: `CLAUDE.md`

**修复契约：**
- 每次 workflow run 结束后，读当日 `product_snapshots`，统计 rating/stock/review_count 缺失数与百分比；
- 写入 `workflow_runs.scrape_quality`（JSON 列）；
- 百分比超过 `SCRAPE_QUALITY_ALERT_RATIO`（默认 0.10，即 10%）时，发一封独立的"数据质量告警"邮件，**不**在业务变动邮件里掺杂。

- [ ] **Step 6.1 — 添加失败测试：统计函数**

创建 `tests/test_scrape_quality.py`：

```python
"""字段缺失统计与告警阈值判定。"""
from qbu_crawler.server.scrape_quality import (
    summarize_scrape_quality,
    should_raise_alert,
)


def test_summarize_counts_null_rating():
    rows = [
        {"sku": "A", "rating": 4.5, "stock_status": "in_stock", "review_count": 10},
        {"sku": "B", "rating": None, "stock_status": "in_stock", "review_count": 10},
        {"sku": "C", "rating": None, "stock_status": "in_stock", "review_count": 10},
    ]
    q = summarize_scrape_quality(rows)
    assert q["total"] == 3
    assert q["missing_rating"] == 2
    assert q["missing_stock"] == 0
    assert q["missing_review_count"] == 0
    assert abs(q["missing_rating_ratio"] - 2/3) < 1e-6


def test_summarize_counts_unknown_stock_and_empty_review_count():
    rows = [
        {"sku": "A", "rating": 4.5, "stock_status": "unknown", "review_count": 10},
        {"sku": "B", "rating": 4.5, "stock_status": "",        "review_count": 10},
        {"sku": "C", "rating": 4.5, "stock_status": None,      "review_count": None},
    ]
    q = summarize_scrape_quality(rows)
    assert q["missing_stock"] == 3
    assert q["missing_review_count"] == 1


def test_alert_threshold_triggered():
    quality = {"total": 100, "missing_rating": 15, "missing_stock": 0,
               "missing_review_count": 0,
               "missing_rating_ratio": 0.15, "missing_stock_ratio": 0.0,
               "missing_review_count_ratio": 0.0}
    assert should_raise_alert(quality, threshold=0.10) is True
    assert should_raise_alert(quality, threshold=0.20) is False


def test_alert_not_triggered_on_empty():
    quality = {"total": 0, "missing_rating": 0, "missing_stock": 0,
               "missing_review_count": 0,
               "missing_rating_ratio": 0.0, "missing_stock_ratio": 0.0,
               "missing_review_count_ratio": 0.0}
    assert should_raise_alert(quality, threshold=0.10) is False
```

- [ ] **Step 6.2 — 运行测试确认 fail**

```bash
uv run pytest tests/test_scrape_quality.py -v
```

预期：`ModuleNotFoundError: No module named 'qbu_crawler.server.scrape_quality'`

- [ ] **Step 6.3 — 实现 `scrape_quality.py`**

创建 `qbu_crawler/server/scrape_quality.py`：

```python
"""采集字段缺失统计与告警阈值判定。

与 report_snapshot.detect_snapshot_changes 共享 missing-value 约定（None/""/"unknown"）。
"""

from typing import Iterable

MISSING_SENTINELS = (None, "", "unknown")


def _is_missing(v) -> bool:
    return v in MISSING_SENTINELS


def summarize_scrape_quality(products: Iterable[dict]) -> dict:
    """对一次采集的产品列表统计字段缺失。

    入参每条 dict 至少含 rating / stock_status / review_count。
    返回 dict（JSON-safe）：
        total, missing_rating, missing_stock, missing_review_count,
        missing_rating_ratio, missing_stock_ratio, missing_review_count_ratio
    """
    products = list(products)
    total = len(products)
    missing_rating = sum(1 for p in products if _is_missing(p.get("rating")))
    missing_stock = sum(1 for p in products if _is_missing(p.get("stock_status")))
    missing_rc = sum(1 for p in products if _is_missing(p.get("review_count")))

    def _ratio(n: int) -> float:
        return n / total if total > 0 else 0.0

    return {
        "total": total,
        "missing_rating": missing_rating,
        "missing_stock": missing_stock,
        "missing_review_count": missing_rc,
        "missing_rating_ratio": _ratio(missing_rating),
        "missing_stock_ratio": _ratio(missing_stock),
        "missing_review_count_ratio": _ratio(missing_rc),
    }


def should_raise_alert(quality: dict, threshold: float) -> bool:
    """任一字段缺失率超过阈值即告警。total=0 时不告警（采集为空另行处理）。"""
    if (quality.get("total") or 0) == 0:
        return False
    return any(
        (quality.get(key) or 0.0) >= threshold
        for key in ("missing_rating_ratio",
                    "missing_stock_ratio",
                    "missing_review_count_ratio")
    )
```

- [ ] **Step 6.4 — 运行测试验证通过**

```bash
uv run pytest tests/test_scrape_quality.py -v
```

预期：4/4 PASS。

- [ ] **Step 6.5 — 新增配置项**

在 `.env.example` 末尾追加：

```bash
# 数据质量告警阈值（任一字段缺失率 ≥ 此值触发独立告警邮件）
SCRAPE_QUALITY_ALERT_RATIO=0.10
# 数据质量告警收件人（留空则沿用 EMAIL_RECIPIENTS）
SCRAPE_QUALITY_ALERT_RECIPIENTS=
```

在 `qbu_crawler/config.py` 中 `REPORT_DIR = ...` 附近追加：

```python
SCRAPE_QUALITY_ALERT_RATIO = float(os.getenv("SCRAPE_QUALITY_ALERT_RATIO", "0.10"))
SCRAPE_QUALITY_ALERT_RECIPIENTS = [
    s.strip() for s in os.getenv("SCRAPE_QUALITY_ALERT_RECIPIENTS", "").split(",")
    if s.strip()
]
```

- [ ] **Step 6.6 — 数据库迁移：新增 `scrape_quality` 列**

打开 `qbu_crawler/models.py`，定位到 `migrations = [...]` 列表（line 230-247），在最后一项之前追加：

```python
        "ALTER TABLE workflow_runs ADD COLUMN scrape_quality TEXT",
```

（SQLite 不支持 ALTER 加 JSON 类型，使用 TEXT 存 `json.dumps(dict)` 即可。）

在 `models.py` 的 `update_workflow_run(...)` 附近新增两个函数：

```python
def update_scrape_quality(run_id: int, quality: dict) -> None:
    """把字段缺失统计写入 workflow_runs.scrape_quality（JSON 字符串）。"""
    import json
    with _connect() as conn:
        conn.execute(
            "UPDATE workflow_runs SET scrape_quality = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (json.dumps(quality, ensure_ascii=False), run_id),
        )


def get_scrape_quality(run_id: int) -> dict | None:
    import json
    with _connect() as conn:
        row = conn.execute(
            "SELECT scrape_quality FROM workflow_runs WHERE id = ?", (run_id,)
        ).fetchone()
    if not row or not row[0]:
        return None
    try:
        return json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        return None
```

（`_connect()` 是项目已有的连接工厂；如实际命名不同，按 `qbu_crawler/models.py` 当前风格调整。若该文件里用 `sqlite3.connect(DB_PATH)` 直接打开，则照抄同样模式。）

- [ ] **Step 6.7 — 告警邮件模板**

创建 `qbu_crawler/server/report_templates/email_data_quality.html.j2`：

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f7f7f5;font-family:'Microsoft YaHei','PingFang SC',Arial,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f7f7f5;"><tr><td align="center" style="padding:20px 10px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.06);">

  <tr><td style="background:#b45309;padding:16px 24px;color:#fff;">
    <div style="font-size:12px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;">QBU 采集数据质量告警</div>
    <div style="font-size:11px;opacity:0.75;margin-top:4px;">{{ logical_date }} · run #{{ run_id }}</div>
  </td></tr>

  <tr><td style="padding:20px 24px;">
    <p style="margin:0 0 12px;font-size:13px;color:#1a1a2e;line-height:1.6;">
      本次采集共 <strong>{{ quality.total }}</strong> 个产品，存在字段缺失超过阈值
      <strong>{{ '%.0f' % (threshold * 100) }}%</strong>，可能由反爬命中、选择器失效或目标站改版导致。
      请检查爬虫日志后决定是否重跑。
    </p>

    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;font-size:12px;margin-top:8px;">
      <tr style="background:#f0efed;color:#555770;">
        <td style="padding:8px 10px;font-weight:700;border-radius:4px 0 0 0;">字段</td>
        <td style="padding:8px 10px;font-weight:700;text-align:center;">缺失数</td>
        <td style="padding:8px 10px;font-weight:700;text-align:center;border-radius:0 4px 0 0;">缺失率</td>
      </tr>
      {% for label, key_n, key_r in [
          ("rating",        "missing_rating",        "missing_rating_ratio"),
          ("stock_status",  "missing_stock",         "missing_stock_ratio"),
          ("review_count",  "missing_review_count",  "missing_review_count_ratio"),
      ] %}
      {% set ratio = quality.get(key_r, 0.0) %}
      <tr>
        <td style="padding:8px 10px;border-bottom:1px solid #e5e4e0;color:#1a1a2e;">{{ label }}</td>
        <td style="padding:8px 10px;border-bottom:1px solid #e5e4e0;text-align:center;font-family:monospace;">{{ quality.get(key_n, 0) }}</td>
        <td style="padding:8px 10px;border-bottom:1px solid #e5e4e0;text-align:center;font-weight:700;color:{% if ratio >= threshold %}#b91c1c{% else %}#8e8ea0{% endif %};">{{ '%.1f' % (ratio * 100) }}%</td>
      </tr>
      {% endfor %}
    </table>

    <p style="margin:12px 0 0;font-size:11px;color:#8e8ea0;line-height:1.6;">
      该邮件由采集数据质量守护自动发出，不等于业务数据变动。业务变动邮件另行推送。
    </p>
  </td></tr>

</table>
</td></tr></table>
</body></html>
```

- [ ] **Step 6.8 — workflow 集成：采集完成后汇总 + 触发告警**

打开 `qbu_crawler/server/workflows.py`，找到 snapshot 持久化后、开始 report 生成之前的位置（通常在 `models.update_workflow_run(run_id, snapshot_path=..., snapshot_hash=..., ...)` 调用之后）。搜索锚点：

```bash
uv run grep -n "snapshot_hash" qbu_crawler/server/workflows.py | head -5
```

在该调用返回后、进入 report 阶段前，追加：

```python
            # ── 数据质量统计与独立告警（P008 Task 6） ────────────────────
            try:
                from qbu_crawler.server.scrape_quality import (
                    summarize_scrape_quality, should_raise_alert,
                )
                # snapshot["products"] 就是本次采集的产品列表
                quality = summarize_scrape_quality(snapshot.get("products", []))
                models.update_scrape_quality(run_id, quality)
                if should_raise_alert(quality, config.SCRAPE_QUALITY_ALERT_RATIO):
                    _send_data_quality_alert(
                        run_id=run_id,
                        logical_date=run["logical_date"],
                        quality=quality,
                    )
            except Exception:
                logger.exception(
                    "WorkflowWorker: scrape-quality summary/alert failed "
                    "(non-fatal, run %s continues)", run_id)
```

然后在 `workflows.py` 文件末尾（或顶部辅助函数区）加入 `_send_data_quality_alert`：

```python
def _send_data_quality_alert(*, run_id: int, logical_date: str, quality: dict) -> None:
    """独立于业务报告的数据质量告警。"""
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    from pathlib import Path
    from qbu_crawler.server import report as _report
    from qbu_crawler.server import report_snapshot as _rs

    template_dir = Path(__file__).parent / "report_templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "j2"]),
    )
    body_html = env.get_template("email_data_quality.html.j2").render(
        logical_date=logical_date,
        run_id=run_id,
        quality=quality,
        threshold=config.SCRAPE_QUALITY_ALERT_RATIO,
    )

    recipients = (
        config.SCRAPE_QUALITY_ALERT_RECIPIENTS
        or _rs._get_email_recipients()
    )
    if not recipients:
        logger.info("Data-quality alert skipped: no recipients configured")
        return

    subject = f"[数据质量告警] 采集缺失率超阈值 {logical_date} (run #{run_id})"
    try:
        _report.send_email(
            recipients=recipients, subject=subject,
            body_text=subject, body_html=body_html,
        )
    except Exception:
        logger.exception("Data-quality alert email send failed")
```

- [ ] **Step 6.9 — 为集成点加烟雾测试**

在 `tests/test_scrape_quality.py` 末尾追加：

```python
def test_update_and_readback_scrape_quality(tmp_path, monkeypatch):
    import sqlite3
    from qbu_crawler import config, models
    db = tmp_path / "t.db"
    monkeypatch.setattr(config, "DB_PATH", str(db))
    models.init_db()
    # 手插一条 run
    with sqlite3.connect(str(db)) as conn:
        conn.execute(
            "INSERT INTO workflow_runs (workflow_type, status, logical_date, "
            "trigger_key) VALUES ('daily','running','2026-04-19','t:2026-04-19')"
        )
        rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    q = {"total": 10, "missing_rating": 2, "missing_stock": 0,
         "missing_review_count": 0,
         "missing_rating_ratio": 0.2, "missing_stock_ratio": 0.0,
         "missing_review_count_ratio": 0.0}
    models.update_scrape_quality(rid, q)
    loaded = models.get_scrape_quality(rid)
    assert loaded == q
```

- [ ] **Step 6.10 — 运行全部新测试**

```bash
uv run pytest tests/test_scrape_quality.py -v
uv run pytest tests/ -k "workflow" -x
```

预期：新测试全部 PASS；已有 workflow 测试不回归。

- [ ] **Step 6.11 — CLAUDE.md 文档更新**

在 `CLAUDE.md` 的"通用架构决策"段末尾追加：

```markdown
### 数据质量监控（P008）

每次 workflow run 在 snapshot 持久化后计算 `scrape_quality`（rating/stock/review_count 缺失数与比率），写入 `workflow_runs.scrape_quality`。任一字段缺失率超过 `SCRAPE_QUALITY_ALERT_RATIO`（默认 0.10）触发独立的 **数据质量告警邮件**（模板 `email_data_quality.html.j2`），与业务变动邮件完全解耦——后者只消费 `detect_snapshot_changes` 产出的真实业务事件。
```

- [ ] **Step 6.12 — 提交**

```bash
git add qbu_crawler/server/scrape_quality.py \
        qbu_crawler/server/report_templates/email_data_quality.html.j2 \
        qbu_crawler/server/workflows.py \
        qbu_crawler/models.py \
        qbu_crawler/config.py \
        .env.example \
        tests/test_scrape_quality.py \
        CLAUDE.md
git commit -m "feat(report): scrape-quality monitoring +独立告警邮件

每次 run 统计 rating/stock/review_count 缺失率，写 workflow_runs.scrape_quality；
任一字段缺失率超 SCRAPE_QUALITY_ALERT_RATIO（默认 10%）发独立告警邮件。
业务变动邮件与数据质量告警完全分流，杜绝抖动污染。

修复 Bug G。"
```

---

### Task 7：发布/部署守护（Bug E 非代码层）

**Files:**
- Modify: `scripts/publish.py`（如存在版本检查 hook）
- Modify: `CLAUDE.md`（追加部署自检清单）
- Create: `docs/devlogs/D008-report-data-integrity.md`

- [ ] **Step 7.1 — 在 publish 脚本里加 HEAD-vs-released 检查**

阅读 `scripts/publish.py`（项目已有），在版本 bump 之后、上传 PyPI 之前加一段提示：

```python
def _print_deploy_reminder(new_version: str) -> None:
    print()
    print("=" * 60)
    print(f"  包已发布：qbu-crawler == {new_version}")
    print("=" * 60)
    print("⚠️  别忘了把生产服务器升级到同版本，并重启进程。")
    print("    生产版本写在 workflow_runs.service_version 列。")
    print("    部署后请查询：")
    print("      sqlite3 $QBU_DATA_DIR/products.db \\")
    print("        'SELECT id, service_version FROM workflow_runs ORDER BY id DESC LIMIT 3'")
    print("=" * 60)
```

在 `main()` 发布成功分支末尾调用 `_print_deploy_reminder(new_version)`。如 `publish.py` 没有合适位置，跳过并只做 Step 7.2。

- [ ] **Step 7.2 — 在 CLAUDE.md 加 "发布与部署自检" 段**

```markdown
## 发布与部署自检

1. 本地改动合并进 master 后，用 `python scripts/publish.py patch|minor` 发布到 PyPI
2. SSH 生产服务器，`pip install -U qbu-crawler`（或 uvx 拉新版），重启服务
3. 触发一次手动 run 或等待次日定时 run 后，验证：
   ```bash
   sqlite3 $QBU_DATA_DIR/products.db \
     "SELECT id, service_version, report_mode, report_phase FROM workflow_runs ORDER BY id DESC LIMIT 3"
   ```
4. `service_version` 应等于 `qbu_crawler/__init__.py` 里的 `__version__`；不一致说明没重启成功
```

- [ ] **Step 7.3 — 新增 devlog**

创建 `docs/devlogs/D008-report-data-integrity.md`，记录：
- 2026-04-19 基于 run-4/run-5 报告产物做的审计发现
- 7 个 Bug 的真实性验证方法（quoted SQL + snapshot diff）
- 修复取舍：为什么用 `_MISSING_SENTINELS = (None, "", "unknown")` 而不是更激进的模式
- 修复验证：下次 full + change 运行后，如何确认 KPI 与邮件展示正确

内容 ≤ 200 行即可，重点在"为什么这样修"，而不是复述代码。

- [ ] **Step 7.4 — 提交**

```bash
git add scripts/publish.py CLAUDE.md docs/devlogs/D008-report-data-integrity.md
git commit -m "docs: 发布自检 + P008 devlog"
```

---

## 3 · 端到端验证（所有 Task 完成后一次性跑）

- [ ] **Step E1 — 跑完整测试套件**

```bash
uv run pytest tests/ -x
```

预期：全绿。

- [ ] **Step E2 — 用当下生产 snapshot 做回放**

写一个临时脚本 `scripts/replay_run4.py`（完成后删除，不入仓库），把 `C:/Users/leo/Desktop/新建文件夹 (3)/reports/workflow-run-4-snapshot-2026-04-16.json` 喂给 `generate_report_from_snapshot(...)`：

```python
import json
from pathlib import Path
from qbu_crawler.server.report_snapshot import generate_report_from_snapshot

snap = json.loads(Path(r"C:/Users/leo/Desktop/新建文件夹 (3)/reports/workflow-run-4-snapshot-2026-04-16.json").read_text(encoding="utf-8"))
result = generate_report_from_snapshot(snap, send_email=False)
print(result["mode"], result["html_path"], result.get("analytics_path"))
```

期望：
- `result["mode"] == "quiet"`（Bug A 修掉后，4/16 的 5 条全部为假变动 → quiet）
- 生成的 `quiet-report.html` 中 KPI 读到的是**当日** `own_review_rows=1611`（Task 3 已让模板读 analytics，虽然当前 run 没 analytics，但回放会生成 cum_analytics）
- 生成的 HTML 中 stock 区块不再出现"缺货"字样（因为变动清单为空）

- [ ] **Step E3 — 部署到生产并在下一次 daily run 后验证**

按 Task 7.2 的部署自检清单做。

---

## 4 · 自检清单（作者手动过一遍）

- [x] 所有 Bug（A/B/C/D/E/G/I）都有对应 Task
- [x] 每个 Task 均遵循 TDD：失败测试 → 实现 → 通过 → 提交
- [x] 无"TODO"、"后续再说"等占位符
- [x] 所有代码块都是完整的、可复制即运行的
- [x] 新函数 `_is_missing` / `_price_changed` / `_simple_changed` / `summarize_scrape_quality` / `should_raise_alert` / `_send_data_quality_alert` / `update_scrape_quality` / `get_scrape_quality` 全部在文中定义
- [x] 模板改动前后的 jinja 代码都给出
- [x] 数据库迁移通过 ALTER TABLE 保证向后兼容
- [x] 不处理超范围问题（H/K/L 明确排除）

---

## 5 · 执行交接

**方案已保存至 `docs/plans/P008-report-data-integrity-fix.md`。两种执行模式：**

1. **Subagent-Driven（推荐）**：每个 Task 派一个全新 subagent，两阶段 review，隔离执行
2. **Inline Execution**：当前 session 按 Task 顺序批量执行，checkpoint 处 review

请选择执行方式。
