# Stage B · Phase 1 P2 Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 best-practice §3 标记的 4 条 P2 建议修（artifact 路径相对化、kpis 字段消歧、trend year 视角语义 banner、LLM low-sample 口径切换到 `change_digest.summary.fresh_review_count`）全部修掉，让 artifact 在数据目录迁移后仍可解析、模板不再误消费混合差评率、年视图给出明确"基于评论发布时间"的语义提示、LLM low-sample 警告改用业务正确的样本数。

**Architecture:**
- **不引入新顶层契约字段**：Stage B 在契约冻结期内，严格不动 `change_digest / trend_digest / kpis` 顶层键名；只能在 `trend_digest` 下加 `view_notes`（次级新增、非顶层、不影响 Phase 2 T9 的 `secondary_charts` 语义）。
- **artifact 路径单一收口在 `_artifact_db_value()`**：`report_snapshot.py` 三个 mode 返回 dict 前过一遍；`workflows.py` 落库前再保险一次（双层防御，向后兼容已有的绝对路径）。
- **kpis 重命名遵守"only own_* 暴露给模板"**：把当前顶层的混合 `negative_review_rate / negative_review_rate_display`（含竞品 12% vs 自有 3.6% 并存）重命名为 `all_sample_negative_rate / all_sample_negative_rate_display`，下游模板 / LLM prompt 改读 `own_negative_review_rate`，legacy email 模板同步迁移。
- **year 视图语义 banner 数据驱动**：在 `_build_trend_digest` 返回值里加 `view_notes: {"year": "..."}`，模板 `<section id="tab-trends">` 的 toolbar 下方按 active view 显隐 banner — 不在 Jinja 里硬编码。
- **LLM low-sample 改读 `change_digest.summary.fresh_review_count`**：bootstrap 永不触发（首次基线本身就是基线，不是样本不足）；incremental 时 `fresh < 5` 才告警，避免 backfill-dominant 场景下 800 条历史补采被错误地用 window 数 = 3 触发。

**Tech Stack:** Python 3.10+, pytest, Jinja2

**Spec:** `docs/superpowers/specs/2026-04-23-report-change-and-trend-governance-design.md`
**Source findings:** `docs/reviews/2026-04-24-report-upgrade-best-practice.md` §3 修 7-10 + §4 测试补强清单 + §5 CI 门禁
**Entry assumption:** `HEAD = 0696624` (Stage A 完成 · v0.3.18-stage-a 已打 tag)；契约冻结期 Day 1，连续 3 个 daily run 不允许改 `change_digest / trend_digest / kpis` 顶层键名；Stage B 与 Phase 2 T9 文件不重叠（Stage B 不动 `report_charts.py`；T9 不动本 plan 涉及的 4 个文件）。

---

## File Map

| File | Responsibility | Tasks |
|------|----------------|-------|
| `qbu_crawler/server/report_snapshot.py` | full / change / quiet 三个 mode return 前 wrap `_artifact_db_value()`；resolver 不变 | T1 |
| `qbu_crawler/server/workflows.py` | `_run_full_report` / `_finish_report` 落库前再 wrap 一次（双层防御） | T1 |
| `qbu_crawler/server/report_common.py` | `normalize_deep_report_analytics` 的 `negative_review_rate / *_display` 重命名为 `all_sample_negative_rate / *_display`；`_fallback_executive_bullets` / `_fallback_hero_headline` 不读混合口径 | T2 |
| `qbu_crawler/server/report_llm.py` | `_build_insights_prompt` L475 改读 `own_negative_review_rate`；low-sample 段（L626-633）改读 `change_digest.summary.fresh_review_count`，bootstrap 跳过 | T2, T4 |
| `qbu_crawler/server/report_analytics.py` | `_build_trend_digest` 返回值追加 `view_notes` 字段 | T3 |
| `qbu_crawler/server/report_templates/daily_report_v3.html.j2` | 趋势 toolbar 下方加 `view_notes` banner（按 active view 显隐） | T3 |
| `qbu_crawler/server/report_templates/daily_report_email.html.j2` | line 97-99 改读 `own_negative_review_rate_display`（删 fallback 链中的混合 rate） | T2 |
| `qbu_crawler/server/report_templates/daily_report_email_body.txt.j2` | line 6 改读 `own_negative_review_rate_display` | T2 |
| `tests/test_report_snapshot.py` | 新增 artifact 落库相对路径回归 + 跨目录迁移恢复 | T1 |
| `tests/test_report_common.py` | 新增 normalize 后顶层键消歧断言 | T2 |
| `tests/test_report_llm.py` | 修改既有 `test_build_insights_prompt_small_window_warning_uses_window_count`（语义改名）；新增 bootstrap 不触发 + fresh<5 触发 + own rate 引用 | T2, T4 |
| `tests/test_report_analytics.py` | 新增 `view_notes` 数据契约断言 | T3 |
| `tests/test_v3_html.py` | 新增 year banner 渲染回归 | T3 |
| `pyproject.toml` / `qbu_crawler/__init__.py` / `uv.lock` | 版本号 bump 0.3.18 → 0.3.19 | T5 |
| `docs/reviews/2026-04-24-report-upgrade-continuity.md` | next_action / status pointer 更新到 Stage B 完成 / Phase 2 T9 准备 | T5 |

---

## Task 1: 修 7 — artifact 写入相对路径

**Files:**
- Modify: `qbu_crawler/server/report_snapshot.py:912-915` (change mode return)
- Modify: `qbu_crawler/server/report_snapshot.py:983-996` (quiet mode return)
- Modify: `qbu_crawler/server/report_snapshot.py:1364-1376` (full mode return)
- Modify: `qbu_crawler/server/workflows.py:716-727` (`_finish_report` analytics_path/excel_path 落库)
- Modify: `qbu_crawler/server/workflows.py:755-762` (`_finish_report` 第二次 update_workflow_run 兜底)
- Test: `tests/test_report_snapshot.py`

- [ ] **Step 1.1: 写失败测试 — 落库相对路径**

加到 `tests/test_report_snapshot.py` 末尾：

```python
def test_workflow_run_stores_relative_artifact_paths(snapshot_db, monkeypatch):
    """修 7: report_snapshot.* 返回 dict 中的 analytics_path / excel_path /
    html_path 必须是相对 REPORT_DIR 的相对路径，便于跨机器迁移后 resolver 仍能恢复。"""
    from qbu_crawler.server import report_snapshot

    # Stub all heavyweight collaborators — we only test the path-shaping behavior
    monkeypatch.setattr(report_snapshot.report, "query_report_data", lambda *a, **kw: ([], []))
    monkeypatch.setattr(report_snapshot.report, "query_cumulative_data", lambda *a, **kw: ([], []))
    monkeypatch.setattr(report_snapshot, "_render_full_email_html", lambda *a, **kw: "<html></html>")
    monkeypatch.setattr(report_snapshot.report, "send_email", lambda **kw: {"success": True, "recipients": []})

    snapshot = report_snapshot.freeze_report_snapshot(
        snapshot_db["run"]["id"], now="2026-04-25T12:00:00+08:00"
    )
    # Inject minimal cumulative + reviews so generate_report_from_snapshot picks "full" mode
    snapshot["reviews"] = [{"id": 1, "rating": 5, "ownership": "own"}]
    snapshot["cumulative"] = {
        "products": [], "reviews": [{"id": 1, "rating": 5, "ownership": "own"}],
        "products_count": 0, "reviews_count": 1, "translated_count": 0, "untranslated_count": 1,
    }

    result = report_snapshot.generate_report_from_snapshot(snapshot, send_email=False)

    # The on-disk file MUST live under config.REPORT_DIR
    from qbu_crawler import config
    report_root = Path(config.REPORT_DIR).resolve()

    for key in ("analytics_path", "excel_path", "html_path"):
        stored = result.get(key)
        if stored is None:
            continue  # change/quiet modes legitimately omit some keys
        # Stored value must be relative (no drive letter, no leading slash)
        assert not Path(stored).is_absolute(), f"{key} must be relative, got {stored!r}"
        # Joining with REPORT_DIR must point to an existing file
        resolved = (report_root / stored).resolve()
        assert resolved.is_file(), f"{key}={stored!r} did not resolve to an existing file"
```

- [ ] **Step 1.2: 写失败测试 — resolver 跨机器迁移恢复**

继续追加：

```python
def test_artifact_resolver_recovers_when_original_path_moved(snapshot_db, monkeypatch, tmp_path):
    """修 7 补强：旧 run 的 analytics_path 已经是绝对路径（Stage A 之前生成），
    机器迁移后 REPORT_DIR 改了位置，resolver 应当通过 basename glob 找回 artifact。"""
    from qbu_crawler import config, models
    from qbu_crawler.server.report_snapshot import _resolve_artifact_path

    # 1. 模拟旧机器的 absolute path（写到 DB）
    legacy_abs = r"D:\OldServer\reports\workflow-run-42-analytics-2026-03-20.json"

    # 2. 当前机器的实际 REPORT_DIR
    Path(config.REPORT_DIR).mkdir(parents=True, exist_ok=True)
    actual_path = Path(config.REPORT_DIR) / "workflow-run-42-analytics-2026-03-20.json"
    actual_path.write_text('{"kpis": {}}', encoding="utf-8")

    # 3. resolver 必须找到当前 REPORT_DIR 下的同名文件
    resolved = _resolve_artifact_path(legacy_abs, run_id=42, kind="analytics")
    assert resolved is not None, "resolver should fall back to basename in REPORT_DIR"
    assert Path(resolved).is_file()
    assert Path(resolved).name == actual_path.name
```

- [ ] **Step 1.3: 跑失败测试**

Run: `uv run --extra dev python -m pytest tests/test_report_snapshot.py -v -k "relative_artifact_paths or resolver_recovers"`
Expected: 2 个 FAIL（第一个会断言 `Path(stored).is_absolute()`；第二个目前 resolver 已支持 basename glob，可能直接通过 — 如果通过则保留为回归锁）

- [ ] **Step 1.4: 实现 — change mode 相对路径**

`qbu_crawler/server/report_snapshot.py:910-924` `_generate_change_report` 的 analytics_path 写入段，把 `analytics_path` 落入返回 dict 之前过一遍 `_artifact_db_value()`。具体改 L943-955 的 return：

```python
    return {
        "mode": "change",
        "status": "completed",
        "run_id": run_id,
        "snapshot_hash": snapshot.get("snapshot_hash", ""),
        "products_count": snapshot.get("products_count", 0),
        "reviews_count": 0,
        "html_path": _artifact_db_value(html_path),
        "excel_path": None,
        "analytics_path": _artifact_db_value(analytics_path),
        "cumulative_computed": cumulative_computed,
        "email": email_result,
    }
```

- [ ] **Step 1.5: 实现 — quiet mode 相对路径**

同理改 `_generate_quiet_report` 的 return（L1020-1034）：

```python
    return {
        "mode": "quiet",
        "status": "completed_no_change",
        "run_id": run_id,
        "snapshot_hash": snapshot.get("snapshot_hash", ""),
        "products_count": snapshot.get("products_count", 0),
        "reviews_count": 0,
        "html_path": _artifact_db_value(html_path),
        "excel_path": None,
        "analytics_path": _artifact_db_value(analytics_path),
        "cumulative_computed": cumulative_computed,
        "email": email_result,
        "email_skipped": not should_send,
        "digest_mode": digest_mode,
    }
```

- [ ] **Step 1.6: 实现 — full mode 相对路径**

改 `qbu_crawler/server/report_snapshot.py` 内部的 full report 生成函数 return 段（L1364-1376）：

```python
    return {
        "run_id": snapshot["run_id"],
        "snapshot_hash": snapshot["snapshot_hash"],
        "products_count": snapshot["products_count"],
        "reviews_count": snapshot["reviews_count"],
        "translated_count": snapshot["translated_count"],
        "untranslated_count": snapshot["untranslated_count"],
        "excel_path": _artifact_db_value(excel_path),
        "analytics_path": _artifact_db_value(analytics_path),
        "pdf_path": pdf_path,  # always None in V3
        "html_path": _artifact_db_value(html_path),
        "email": email_result,
    }
```

注意：FullReportGenerationError 的 attrs（L1339-1340）也要 wrap，否则异常路径里的部分 artifact 是绝对路径：

```python
        raise FullReportGenerationError(
            str(exc),
            analytics_path=_artifact_db_value(analytics_path) if os.path.isfile(analytics_path) else None,
            excel_path=_artifact_db_value(excel_path) if excel_path and os.path.isfile(excel_path) else None,
            pdf_path=None,
        ) from exc
```

- [ ] **Step 1.7: 实现 — workflows.py 落库再保险**

改 `qbu_crawler/server/workflows.py:716-727`（第一次 `update_workflow_run`）：

```python
            excel_path = full_report.get("excel_path")
            analytics_path = full_report.get("analytics_path")
            pdf_path = full_report.get("pdf_path")
            html_path = full_report.get("html_path") or full_report.get("v3_html_path")
            email = full_report.get("email")
            email_ok = (email or {}).get("success")
            # Stage B 修 7: 双层防御 — report_snapshot 已 wrap，但 incremental fix 期间
            # 可能存在没 wrap 的旧调用路径，落库前再过一次 _artifact_db_value()
            from qbu_crawler.server.report_snapshot import _artifact_db_value
            models.update_workflow_run(
                run_id,
                excel_path=_artifact_db_value(excel_path),
                analytics_path=_artifact_db_value(analytics_path),
                pdf_path=_artifact_db_value(pdf_path),
            )
```

同理改 L755-762 的第二次落库：

```python
            models.update_workflow_run(
                run_id,
                status="completed",
                report_phase="full_sent",
                excel_path=_artifact_db_value(excel_path),
                analytics_path=_artifact_db_value(analytics_path),
                pdf_path=_artifact_db_value(pdf_path),
                finished_at=now,
                error=None,
            )
```

`_artifact_db_value()` 对相对路径是 idempotent — 它先 `Path(path).resolve()`，然后尝试 `relative_to(root.resolve())`，相对路径解析后仍然落回 REPORT_DIR 下，所以二次 wrap 无副作用。

- [ ] **Step 1.8: 跑测试验证通过**

Run: `uv run --extra dev python -m pytest tests/test_report_snapshot.py -v -k "relative_artifact_paths or resolver_recovers or load_previous_report_context"`
Expected: 3 个 PASS（含已存在的 `test_load_previous_report_context_resolves_stale_absolute_artifact_paths`，确保旧路径回退仍工作）

- [ ] **Step 1.9: 跑全量回归**

Run: `uv run --extra dev python -m pytest tests/test_report_snapshot.py tests/test_workflows.py -v`
Expected: 全绿（如有失败必须先排查再 commit）

- [ ] **Step 1.10: 提交**

```bash
git add qbu_crawler/server/report_snapshot.py qbu_crawler/server/workflows.py tests/test_report_snapshot.py
git commit -m "fix(report): wrap artifact paths through _artifact_db_value before persistence (T-B-1 · Stage B 修 7)"
```

---

## Task 2: 修 8 — kpis 字段消歧（顶层混合 rate 重命名）

**Files:**
- Modify: `qbu_crawler/server/report_common.py:765-783` (`normalize_deep_report_analytics` 顶层 KPI 计算段)
- Modify: `qbu_crawler/server/report_llm.py:475` (`_build_insights_prompt` 改读 own rate)
- Modify: `qbu_crawler/server/report_templates/daily_report_email.html.j2:97-99`
- Modify: `qbu_crawler/server/report_templates/daily_report_email_body.txt.j2:6`
- Test: `tests/test_report_common.py`
- Test: `tests/test_report_llm.py`

- [ ] **Step 2.1: 写失败测试 — kpis 顶层不再暴露 ambiguous `negative_review_rate`**

加到 `tests/test_report_common.py` 末尾：

```python
def test_normalize_kpis_renames_ambiguous_negative_review_rate():
    """修 8: 顶层 kpis 不能同时暴露混合 rate（含竞品）和 own rate，
    重命名为 all_sample_negative_rate 让模板/LLM 不会误消费。"""
    from qbu_crawler.server.report_common import normalize_deep_report_analytics

    raw = {
        "kpis": {
            "ingested_review_rows": 100,
            "negative_review_rows": 12,        # mixed (含竞品)
            "own_review_rows": 80,
            "own_negative_review_rows": 3,     # own only
            "own_negative_review_rate": 0.0375,
            "translated_count": 50,
            "own_product_count": 5,
            "competitor_product_count": 3,
        },
        "self": {"risk_products": [], "top_negative_clusters": [],
                 "top_positive_clusters": [], "recommendations": []},
        "competitor": {"top_positive_themes": [], "benchmark_examples": [],
                       "negative_opportunities": [], "gap_analysis": []},
        "appendix": {"image_reviews": [], "coverage": {}},
        "report_semantics": "incremental",
    }
    out = normalize_deep_report_analytics(raw)
    kpis = out["kpis"]

    # ambiguous 旧键必须不再出现
    assert "negative_review_rate" not in kpis, (
        "顶层 kpis 的 ambiguous 'negative_review_rate' 必须重命名为 all_sample_negative_rate"
    )
    assert "negative_review_rate_display" not in kpis

    # 新键替代
    assert "all_sample_negative_rate" in kpis
    assert kpis["all_sample_negative_rate"] == 0.12  # 12/100
    assert kpis["all_sample_negative_rate_display"] == "12.0%"

    # own rate 不变
    assert kpis["own_negative_review_rate"] == 0.0375
    assert kpis["own_negative_review_rate_display"] == "3.8%"
```

- [ ] **Step 2.2: 写失败测试 — LLM prompt 不读 ambiguous rate**

加到 `tests/test_report_llm.py` 末尾：

```python
def test_build_insights_prompt_uses_own_rate_not_mixed_rate():
    """修 8: LLM prompt 必须叙述 own 自有差评率，不能引用 ambiguous 的混合 rate。"""
    from qbu_crawler.server.report_llm import _build_insights_prompt

    analytics = {
        "kpis": {
            "own_product_count": 5, "competitor_product_count": 3,
            "ingested_review_rows": 100, "own_review_rows": 80,
            "own_negative_review_rows": 3,
            "own_negative_review_rate": 0.0375,        # 3.8%
            "all_sample_negative_rate": 0.12,           # 12%（含竞品）
            "negative_review_rows": 12,
            "competitor_review_rows": 20, "health_index": 90,
        },
        "self": {"risk_products": [], "top_negative_clusters": [], "recommendations": []},
        "competitor": {"gap_analysis": [], "benchmark_examples": []},
        "report_semantics": "incremental",
        "perspective": "dual",
        "change_digest": {"summary": {
            "ingested_review_count": 100, "fresh_review_count": 50,
            "historical_backfill_count": 50, "fresh_own_negative_count": 0,
        }},
    }
    prompt = _build_insights_prompt(analytics)
    # prompt 引用的应当是 own 口径（3.8%），不是混合口径（12%）
    assert "3.8%" in prompt or "3.7%" in prompt, "应叙述 own_negative_review_rate"
    # 不应直接出现 12% 的"自有差评率"误引用
    assert "自有差评率 12" not in prompt
```

- [ ] **Step 2.3: 跑失败测试**

Run: `uv run --extra dev python -m pytest tests/test_report_common.py::test_normalize_kpis_renames_ambiguous_negative_review_rate tests/test_report_llm.py::test_build_insights_prompt_uses_own_rate_not_mixed_rate -v`
Expected: 2 个 FAIL — 第一个 `assert "negative_review_rate" not in kpis` 失败；第二个会因 `_build_insights_prompt` 仍读 `kpis.get("negative_review_rate", 0)` 取到 0 而走偏（具体断言取决于 fallback 值）

- [ ] **Step 2.4: 实现 — `report_common.py` 重命名**

改 `qbu_crawler/server/report_common.py:765-783`：

```python
    ingested_review_rows = normalized["kpis"].get("ingested_review_rows") or 0
    negative_review_rows = normalized["kpis"].get("negative_review_rows")
    if negative_review_rows is None:
        negative_review_rows = normalized["kpis"].get("low_rating_review_rows") or 0
    translated_count = normalized["kpis"].get("translated_count") or 0
    normalized["kpis"]["negative_review_rows"] = negative_review_rows
    # 修 8: 把混合口径（含竞品）从 negative_review_rate 重命名为 all_sample_negative_rate，
    # 让模板 / LLM prompt 不再误消费。展示用一律走 own_negative_review_rate*。
    normalized["kpis"]["all_sample_negative_rate"] = (
        negative_review_rows / ingested_review_rows if ingested_review_rows else 0
    )
    normalized["kpis"]["all_sample_negative_rate_display"] = (
        f"{normalized['kpis']['all_sample_negative_rate'] * 100:.1f}%"
    )
    normalized["kpis"]["translation_completion_rate"] = (
        translated_count / ingested_review_rows if ingested_review_rows else 0
    )
    normalized["kpis"]["translation_completion_rate_display"] = (
        f"{normalized['kpis']['translation_completion_rate'] * 100:.1f}%"
    )
```

注意：删除原本的 `normalized["kpis"]["negative_review_rate"]` 与 `negative_review_rate_display` 写入；不要保留 backwards-compat alias（按 CLAUDE.md "no backwards-compatibility shims"）。

- [ ] **Step 2.5: 实现 — LLM prompt 改读 own rate**

改 `qbu_crawler/server/report_llm.py:475`：

```python
    rate = kpis.get("own_negative_review_rate", 0)
```

注意：`rate` 在 L558 用于 prompt 文本 `"全量评论 {total} 条..."` 的下一行—翻看上下文：

```python
prompt = f"""...
- 自有评论 {own_reviews} 条，自有差评 {own_neg} 条（自有差评率 {own_rate * 100:.1f}%）
- 全量评论 {total} 条（含竞品 {comp_reviews} 条），全量差评 {neg} 条
"""
```

`rate` 实际只在 L475 取出但不直接用（`own_rate * 100` 才是 prompt 引用的），所以 L475 的 `rate` 可能死代码 — 改成 own rate 让其不再读 ambiguous 字段，避免未来重构者误以为该字段还在。或者干脆删掉 L475 的 `rate = ...`。**保留改名**（删除会扩大改动面、可能触发上下游 KeyError）。

- [ ] **Step 2.6: 实现 — legacy email 模板迁移**

改 `qbu_crawler/server/report_templates/daily_report_email.html.j2:97-99`：

```jinja2
            <div style="font-size:26px;font-weight:800;color:#201b16;line-height:1;">{{ analytics.kpis.own_negative_review_rate_display | default('—') }}</div>
            {% if analytics.kpis.own_negative_review_rate_delta_display is defined and analytics.kpis.own_negative_review_rate_delta_display %}
            <div style="font-size:11px;color:#766d62;margin-top:4px;">{{ analytics.kpis.own_negative_review_rate_delta_display }}</div>
```

改 `qbu_crawler/server/report_templates/daily_report_email_body.txt.j2:6`：

```
差评率: {{ analytics.kpis.own_negative_review_rate_display }}
```

- [ ] **Step 2.7: 跑测试验证通过**

Run: `uv run --extra dev python -m pytest tests/test_report_common.py tests/test_report_llm.py -v -k "renames_ambiguous or uses_own_rate"`
Expected: 2 个 PASS

- [ ] **Step 2.8: 跑全量回归（重点排查现有用例对旧键名的依赖）**

Run: `uv run --extra dev python -m pytest tests/test_report_common.py tests/test_report_analytics.py tests/test_report_llm.py tests/test_v3_html.py tests/test_report_integration.py -v 2>&1 | tail -50`
Expected: 全绿。如果有现有用例 grep `negative_review_rate_display` 或 `kpis["negative_review_rate"]`，必须更新到 `all_sample_negative_rate*` 或 `own_negative_review_rate*`（取决于该测试的语义意图）。

- [ ] **Step 2.9: grep 残留**

Run: `grep -rn "negative_review_rate" qbu_crawler/ --include="*.py" --include="*.j2" --include="*.txt" | grep -v "own_negative_review_rate\|all_sample_negative_rate"`
Expected: 0 命中（所有引用都已显式 own / all_sample 限定）。如有命中必须改完才 commit。

- [ ] **Step 2.10: 提交**

```bash
git add qbu_crawler/server/report_common.py qbu_crawler/server/report_llm.py qbu_crawler/server/report_templates/daily_report_email.html.j2 qbu_crawler/server/report_templates/daily_report_email_body.txt.j2 tests/test_report_common.py tests/test_report_llm.py
git commit -m "refactor(report): rename ambiguous kpis.negative_review_rate -> all_sample_negative_rate; templates use own_* (T-B-2 · Stage B 修 8)"
```

---

## Task 3: 修 9 — trend year 视图语义 banner

**Files:**
- Modify: `qbu_crawler/server/report_analytics.py:1848-1867` (`_build_trend_digest` 追加 `view_notes` 字段)
- Modify: `qbu_crawler/server/report_templates/daily_report_v3.html.j2:262-285` (toolbar 下方加 banner)
- Test: `tests/test_report_analytics.py`
- Test: `tests/test_v3_html.py`

- [ ] **Step 3.1: 写失败测试 — `view_notes` 数据契约**

加到 `tests/test_report_analytics.py` 末尾：

```python
def test_build_trend_digest_emits_year_view_note():
    """修 9: trend_digest 必须在 year 视角下提供语义 banner，
    告诉用户 year 维度基于评论发布时间聚合，不代表监控运行年限。"""
    from qbu_crawler.server.report_analytics import _build_trend_digest

    snapshot = {
        "logical_date": "2026-04-25",
        "products": [],
        "reviews": [],
    }
    digest = _build_trend_digest(snapshot, labeled_reviews=[], trend_series={})

    assert "view_notes" in digest, "trend_digest 必须暴露 view_notes 用于年视图 banner"
    assert "year" in digest["view_notes"]
    note = digest["view_notes"]["year"]
    assert "评论发布时间" in note or "发布时间" in note
    assert "监控" in note  # 必须强调"非监控运行年限"
    # week / month 可以为 None 或 ""（不需要 banner）
    assert digest["view_notes"].get("week") in (None, "")
    assert digest["view_notes"].get("month") in (None, "")
```

- [ ] **Step 3.2: 写失败测试 — HTML 渲染 year banner**

加到 `tests/test_v3_html.py` 末尾：

```python
def test_year_trend_panel_shows_view_note_banner(tmp_path):
    """修 9: 年视图必须渲染数据驱动的语义 banner（来自 trend_digest.view_notes.year）。
    模板必须按 active view 控制显隐：默认 month 不显示，year 切换后显示。"""
    from qbu_crawler.server.report_html import render_v3_html

    snapshot = {
        "logical_date": "2026-04-25",
        "run_id": 99,
        "products": [], "reviews": [], "snapshot_at": "2026-04-25T12:00:00+08:00",
    }
    analytics = {
        "kpis": {
            "ingested_review_rows": 0, "own_review_rows": 0, "own_negative_review_rows": 0,
            "own_product_count": 0, "competitor_product_count": 0, "competitor_review_rows": 0,
            "health_index": 50, "negative_review_rows": 0, "low_rating_review_rows": 0,
        },
        "self": {"risk_products": [], "top_negative_clusters": [],
                 "top_positive_clusters": [], "recommendations": []},
        "competitor": {"top_positive_themes": [], "benchmark_examples": [],
                       "negative_opportunities": [], "gap_analysis": []},
        "appendix": {"image_reviews": [], "coverage": {}},
        "trend_digest": {
            "views": ["week", "month", "year"],
            "dimensions": ["sentiment"],
            "default_view": "month",
            "default_dimension": "sentiment",
            "view_notes": {
                "year": "年度视角基于评论发布时间聚合。历史数据源于站点用户的历史发布时间跨度，不代表本监控系统的实际运行年限。",
                "week": None, "month": None,
            },
            "data": {
                "week": {"sentiment": {"status": "accumulating", "status_message": "积累中",
                                       "kpis": {"status": "accumulating"}, "table": {"status": "accumulating"},
                                       "primary_chart": {"status": "accumulating"}}},
                "month": {"sentiment": {"status": "accumulating", "status_message": "积累中",
                                        "kpis": {"status": "accumulating"}, "table": {"status": "accumulating"},
                                        "primary_chart": {"status": "accumulating"}}},
                "year": {"sentiment": {"status": "accumulating", "status_message": "积累中",
                                       "kpis": {"status": "accumulating"}, "table": {"status": "accumulating"},
                                       "primary_chart": {"status": "accumulating"}}},
            },
        },
        "report_semantics": "incremental",
    }
    out_path = render_v3_html(snapshot, analytics, output_path=str(tmp_path / "report.html"))
    html_text = Path(out_path).read_text(encoding="utf-8")

    # banner 内容必须存在于 HTML（不要求默认可见，但 DOM 中必有）
    assert "年度视角基于评论发布时间聚合" in html_text
    # banner 必须用 data-trend-view="year" 标记，让前端按 active view 显隐
    assert 'data-trend-view-note="year"' in html_text
```

- [ ] **Step 3.3: 跑失败测试**

Run: `uv run --extra dev python -m pytest tests/test_report_analytics.py::test_build_trend_digest_emits_year_view_note tests/test_v3_html.py::test_year_trend_panel_shows_view_note_banner -v`
Expected: 2 个 FAIL（`view_notes` key 不存在；HTML 中无 banner）

- [ ] **Step 3.4: 实现 — `_build_trend_digest` 追加 `view_notes`**

改 `qbu_crawler/server/report_analytics.py:1848-1867`：

```python
def _build_trend_digest(snapshot, labeled_reviews, trend_series):
    logical_day = date.fromisoformat(snapshot["logical_date"])
    data = {}
    snapshot_products = snapshot.get("products") or []

    for view in _TREND_VIEWS:
        data[view] = {
            "sentiment": _build_trend_dimension(_build_sentiment_trend, view, logical_day, labeled_reviews),
            "issues": _build_trend_dimension(_build_issue_trend, view, logical_day, labeled_reviews),
            "products": _build_trend_dimension(_build_product_trend, view, logical_day, trend_series, snapshot_products),
            "competition": _build_trend_dimension(_build_competition_trend, view, logical_day, labeled_reviews),
        }

    return {
        "views": list(_TREND_VIEWS.keys()),
        "dimensions": list(_TREND_DIMENSIONS),
        "default_view": "month",
        "default_dimension": "sentiment",
        "data": data,
        # 修 9: 年视图基于 date_published_parsed（评论发布时间），跨越历史数年；
        # 用户容易误以为是"监控系统已运行 N 年"，所以给出语义提示。
        "view_notes": {
            "week": None,
            "month": None,
            "year": (
                "年度视角基于评论发布时间聚合。历史数据源于站点用户的历史发布时间跨度，"
                "不代表本监控系统的实际运行年限。"
            ),
        },
    }
```

- [ ] **Step 3.5: 实现 — 模板渲染 banner**

改 `qbu_crawler/server/report_templates/daily_report_v3.html.j2`，在 L266 `<div class="trend-toolbar">` 之后、L279 `{% for view in trend_views %}` 之前加：

```jinja2
      {% set trend_view_notes = trend_digest.view_notes or {} %}
      {% for view, note in trend_view_notes.items() %}
        {% if note %}
        <div class="trend-view-note" data-trend-view-note="{{ view }}"{% if view != default_view %} hidden{% endif %}>
          <span class="trend-view-note-icon">ⓘ</span>
          <span class="trend-view-note-text">{{ note }}</span>
        </div>
        {% endif %}
      {% endfor %}
```

注意定位：紧跟 `</div>` 闭合 `<div class="trend-toolbar">`（L277）之后、`{% for view in trend_views %}` 循环（L279）之前。

- [ ] **Step 3.6: 实现 — 前端 JS 切换 banner**

Stage B 不引入新功能，但前端切换 view 时已经有 `data-trend-view` 处理逻辑，需要顺手把 `data-trend-view-note` 也 wire 进去。改 `qbu_crawler/server/report_templates/daily_report_v3.js`：

先 grep 现有的 view 切换处理点：

```bash
grep -n "data-trend-view\|trend-active" qbu_crawler/server/report_templates/daily_report_v3.js
```

在切换 view 的 click handler 里，遍历所有 `[data-trend-view-note]` 元素，根据 `dataset.trendViewNote === activeView` 切换 `hidden` 属性。具体改法（follow 现有代码风格）：

```javascript
// 在原有 view 切换 handler 中追加
document.querySelectorAll('[data-trend-view-note]').forEach((el) => {
  el.hidden = el.dataset.trendViewNote !== activeView;
});
```

如果 JS 文件结构复杂、不确定切换点：用 `MutationObserver` 监听 `.trend-view-btn` 的 `trend-active` class 切换作为兜底，但首选是直接改现有 click handler。

- [ ] **Step 3.7: 加最小 CSS（可选，为了 banner 可见性）**

`qbu_crawler/server/report_templates/daily_report_v3.css` 末尾加：

```css
.trend-view-note {
  margin: 8px 0 16px;
  padding: 10px 14px;
  background: #f4ebd9;
  border-left: 3px solid #c8a96b;
  border-radius: 4px;
  font-size: 13px;
  color: #4a3f30;
  line-height: 1.5;
}
.trend-view-note[hidden] { display: none; }
.trend-view-note-icon { margin-right: 6px; font-weight: 600; color: #c8a96b; }
```

- [ ] **Step 3.8: 跑测试验证通过**

Run: `uv run --extra dev python -m pytest tests/test_report_analytics.py::test_build_trend_digest_emits_year_view_note tests/test_v3_html.py::test_year_trend_panel_shows_view_note_banner -v`
Expected: 2 个 PASS

- [ ] **Step 3.9: 跑相关回归**

Run: `uv run --extra dev python -m pytest tests/test_report_analytics.py tests/test_v3_html.py -v 2>&1 | tail -30`
Expected: 全绿（视图列表 / digest 结构相关测试不应受影响）

- [ ] **Step 3.10: 提交**

```bash
git add qbu_crawler/server/report_analytics.py qbu_crawler/server/report_templates/daily_report_v3.html.j2 qbu_crawler/server/report_templates/daily_report_v3.css qbu_crawler/server/report_templates/daily_report_v3.js tests/test_report_analytics.py tests/test_v3_html.py
git commit -m "feat(report): add year view semantic banner via trend_digest.view_notes (T-B-3 · Stage B 修 9)"
```

---

## Task 4: 修 10 — LLM low-sample 改读 `change_digest.summary.fresh_review_count`

**Files:**
- Modify: `qbu_crawler/server/report_llm.py:626-633` (low-sample warning 段)
- Modify: `tests/test_report_llm.py:714-740` (既有 `test_build_insights_prompt_small_window_warning_uses_window_count` 改名 + 改语义)
- Test: `tests/test_report_llm.py` (新增 3 条用例)

- [ ] **Step 4.1: 写失败测试 — bootstrap 不触发 low-sample warning**

加到 `tests/test_report_llm.py` 末尾：

```python
def test_build_insights_prompt_bootstrap_does_not_trigger_low_sample_warning():
    """修 10: bootstrap 是首次基线，定义上不存在'样本不足'问题；
    low-sample warning 应当跳过，避免与 bootstrap 文案冲突。"""
    from qbu_crawler.server.report_llm import _build_insights_prompt

    analytics = {
        "report_semantics": "bootstrap",
        "kpis": {
            "ingested_review_rows": 3,         # 极少，但是 bootstrap 不该触发 warning
            "own_review_rows": 3, "own_negative_review_rows": 0,
            "own_negative_review_rate": 0.0,
            "own_product_count": 1, "competitor_product_count": 1,
            "competitor_review_rows": 0, "health_index": 50,
            "all_sample_negative_rate": 0, "negative_review_rows": 0,
        },
        "window": {"reviews_count": 3},
        "change_digest": {"summary": {
            "ingested_review_count": 3,
            "fresh_review_count": 3,           # bootstrap 下 fresh = ingested
            "historical_backfill_count": 0,
        }},
        "self": {"risk_products": [], "top_negative_clusters": [], "recommendations": []},
        "competitor": {"gap_analysis": [], "benchmark_examples": []},
    }
    prompt = _build_insights_prompt(analytics)
    # bootstrap 文案在；low-sample warning 不该出现
    assert "首次基线" in prompt
    assert "样本极少" not in prompt, "bootstrap 不该触发 low-sample warning"


def test_build_insights_prompt_low_sample_uses_change_digest_fresh_count():
    """修 10: incremental 路径下，low-sample warning 必须基于
    change_digest.summary.fresh_review_count，不再读 window.reviews_count。
    backfill-dominant 场景：window=800 但 fresh=4 应当触发。"""
    from qbu_crawler.server.report_llm import _build_insights_prompt

    analytics = {
        "report_semantics": "incremental",
        "perspective": "dual",
        "kpis": {
            "ingested_review_rows": 800,        # 大量入库（含 backfill）
            "own_review_rows": 600, "own_negative_review_rows": 30,
            "own_negative_review_rate": 0.05,
            "own_product_count": 5, "competitor_product_count": 3,
            "competitor_review_rows": 200, "health_index": 70,
            "all_sample_negative_rate": 0.04, "negative_review_rows": 32,
        },
        "window": {"reviews_count": 800},        # 旧逻辑会用这个，不该触发 warning
        "change_digest": {"summary": {
            "ingested_review_count": 800,
            "fresh_review_count": 4,             # 业务真实新增很少
            "historical_backfill_count": 796,
            "fresh_own_negative_count": 0,
        }},
        "self": {"risk_products": [], "top_negative_clusters": [], "recommendations": []},
        "competitor": {"gap_analysis": [], "benchmark_examples": []},
    }
    prompt = _build_insights_prompt(analytics)
    assert "样本极少" in prompt, "fresh<5 时必须触发 low-sample warning"
    # 提示文本应当叙述 fresh 的数字，不能再用 ingested 的 800
    assert "近30天业务新增仅 4 条" in prompt or "近 30 天业务新增仅 4 条" in prompt


def test_build_insights_prompt_low_sample_skips_when_fresh_above_threshold():
    """修 10: fresh_review_count >= 5 不触发 warning。"""
    from qbu_crawler.server.report_llm import _build_insights_prompt

    analytics = {
        "report_semantics": "incremental",
        "perspective": "dual",
        "kpis": {
            "ingested_review_rows": 100,
            "own_review_rows": 80, "own_negative_review_rows": 5,
            "own_negative_review_rate": 0.0625,
            "own_product_count": 3, "competitor_product_count": 2,
            "competitor_review_rows": 20, "health_index": 80,
            "all_sample_negative_rate": 0.05, "negative_review_rows": 5,
        },
        "window": {"reviews_count": 100},
        "change_digest": {"summary": {
            "ingested_review_count": 100,
            "fresh_review_count": 5,             # 刚到阈值
            "historical_backfill_count": 95,
            "fresh_own_negative_count": 1,
        }},
        "self": {"risk_products": [], "top_negative_clusters": [], "recommendations": []},
        "competitor": {"gap_analysis": [], "benchmark_examples": []},
    }
    prompt = _build_insights_prompt(analytics)
    assert "样本极少" not in prompt, "fresh>=5 不该触发 low-sample warning"
```

- [ ] **Step 4.2: 改既有测试 `test_build_insights_prompt_small_window_warning_uses_window_count`**

`tests/test_report_llm.py:714-740` 既有测试用 `window.reviews_count=3` 期望触发 warning。该用例的设计目标本身已经过时（修 10 改完后 warning 改读 fresh_count）。不做整体删除，改为：**保留测试名 + 改语义为现在的 fresh_count**：

```python
def test_build_insights_prompt_small_window_warning_uses_window_count():
    """修 10 之后：warning 基于 change_digest.summary.fresh_review_count，
    不再读 window.reviews_count。保留测试名作为历史回归锁。"""
    from qbu_crawler.server.report_llm import _build_insights_prompt

    analytics = {
        "kpis": {
            "own_product_count": 5, "competitor_product_count": 3,
            "ingested_review_rows": 800,
            "negative_review_rows": 10,
            "own_review_rows": 500, "own_negative_review_rows": 8,
            "own_negative_review_rate": 0.016, "competitor_review_rows": 300,
            "all_sample_negative_rate": 0.0125,
        },
        "self": {"risk_products": [], "top_negative_clusters": [], "recommendations": []},
        "competitor": {"gap_analysis": [], "benchmark_examples": []},
        "window": {
            "reviews_count": 3,
            "own_reviews_count": 2,
            "competitor_reviews_count": 1,
            "new_negative_count": 0,
        },
        "change_digest": {"summary": {
            "ingested_review_count": 3,
            "fresh_review_count": 3,             # 修 10: 基于 fresh，3 < 5 仍触发
            "historical_backfill_count": 0,
            "fresh_own_negative_count": 0,
        }},
        "perspective": "dual",
        "report_semantics": "incremental",
    }
    prompt = _build_insights_prompt(analytics)
    assert "样本极少" in prompt, "Small sample warning should fire when fresh < 5"
```

- [ ] **Step 4.3: 跑失败测试**

Run: `uv run --extra dev python -m pytest tests/test_report_llm.py -v -k "low_sample or small_window_warning"`
Expected:
- `test_build_insights_prompt_bootstrap_does_not_trigger_low_sample_warning` FAIL（当前 bootstrap 也会触发，因为 window.reviews_count=3）
- `test_build_insights_prompt_low_sample_uses_change_digest_fresh_count` FAIL（当前用 window.reviews_count=800 不会触发；修 10 后 fresh=4 应当触发）
- `test_build_insights_prompt_low_sample_skips_when_fresh_above_threshold` 当前可能 PASS（window=100 ≥ 5）— 也可能 FAIL，取决于实现细节，作为前向回归锁
- `test_build_insights_prompt_small_window_warning_uses_window_count` PASS（current 实现仍能命中）

- [ ] **Step 4.4: 实现 — low-sample 段改读 fresh_count**

改 `qbu_crawler/server/report_llm.py:626-633`：

```python
    # Low-sample warning (Stage B 修 10): 改读 change_digest.summary.fresh_review_count，
    # 避免 backfill-dominant 场景被 ingested/window 的大数掩盖业务真实新增不足。
    # bootstrap 不触发：首次基线本身就是基线，"样本不足"不是有意义的概念。
    if report_semantics != "bootstrap":
        _summary = (change_digest.get("summary") or {})
        _fresh_count = _summary.get("fresh_review_count", 0)
        if _fresh_count < 5:
            prompt += (
                f"\n\n⚠️ 本期近30天业务新增仅 {_fresh_count} 条，样本极少。"
                "请仅基于上述数据做事实性记录，禁止做趋势推断或问题严重度判定。"
                "hero_headline 应体现「样本不足」或「数据有限」。"
            )
```

注意：该段紧跟在 `--- 今日变化 ---` 段之后（L621 之后）；保留 L635-642 的 dual-perspective fresh=0 fallback 段不动（功能上互补：一个改写 hero，一个改写 bullets 焦点）。

- [ ] **Step 4.5: 跑测试验证通过**

Run: `uv run --extra dev python -m pytest tests/test_report_llm.py -v -k "low_sample or small_window_warning or bootstrap_does_not"`
Expected: 4 个 PASS

- [ ] **Step 4.6: 跑全量 LLM + 集成回归**

Run: `uv run --extra dev python -m pytest tests/test_report_llm.py tests/test_report_integration.py tests/test_v3_llm.py -v 2>&1 | tail -50`
Expected: 全绿（其它现有用例不应被该改动影响 — bootstrap 走 bootstrap 分支、incremental fresh ≥ 5 不触发 warning）

- [ ] **Step 4.7: 提交**

```bash
git add qbu_crawler/server/report_llm.py tests/test_report_llm.py
git commit -m "fix(report_llm): low-sample warning reads change_digest.summary.fresh_review_count, skip on bootstrap (T-B-4 · Stage B 修 10)"
```

---

## Task 5: Stage B 联测 + 版本号 bump + Continuity 推进

**Files:**
- Modify: `pyproject.toml:7` (`version = "0.3.18"` → `"0.3.19"`)
- Modify: `qbu_crawler/__init__.py:8` (`__version__ = "0.3.18"` → `"0.3.19"`)
- Modify: `uv.lock` (uv 自动同步)
- Modify: `docs/reviews/2026-04-24-report-upgrade-continuity.md`（status / next_action / 进度日志追加）
- Test: 全量 pytest + grep 门禁

- [ ] **Step 5.1: 跑 best-practice §5 grep 门禁全绿（Stage A 已绿，复跑确认 Stage B 没引入回归）**

Run（每条独立检查，任一失败必须排查后才能进入下一步）:

```bash
# 门禁 1: 源码不得再用 "今日新增"（违禁词表除外）
grep -rn "今日新增" qbu_crawler/ | grep -vE "forbidden_patterns|禁止|不得|不要使用"

# 门禁 2: 模板不得出现 "新增评论 "
grep -rn "新增评论" qbu_crawler/server/report_templates/ qbu_crawler/server/report_common.py qbu_crawler/server/report_llm.py | grep -v "本次入库"

# 门禁 3: 模板不得直接解释 window.reviews_count / cumulative_kpis
grep -rn "cumulative_kpis\|window\.reviews_count\|_cumulative" qbu_crawler/server/report_templates/

# 门禁 4: trend 模板必须按组件 status 分支（Stage A 已绿）
grep -n 'trend_block.status == "ready"' qbu_crawler/server/report_templates/daily_report_v3.html.j2

# 门禁 5: 健康指数 tooltip 必须含"贝叶斯"或"NPS"
grep '"健康指数"' qbu_crawler/server/report_common.py | grep -E "贝叶斯|NPS"
```

Expected: 1/2/3/4 命中数 0；5 命中数 ≥ 1。

- [ ] **Step 5.2: Stage B 新增门禁（修 8 后）**

```bash
# 门禁 6: kpis 顶层不得再有 ambiguous 'negative_review_rate'（only own_* / all_sample_*）
grep -rn 'kpis\["negative_review_rate"\]\|kpis\.negative_review_rate[^_]' qbu_crawler/server/

# 门禁 7: 模板不得读 negative_review_rate_display（应改用 own_negative_review_rate_display）
grep -rn "kpis.negative_review_rate_display\|kpis\[\"negative_review_rate_display\"\]" qbu_crawler/server/report_templates/
```

Expected: 6/7 命中数 0。

- [ ] **Step 5.3: 跑 report 相关 11 个测试文件全绿**

Run: `uv run --extra dev python -m pytest tests/test_report_analytics.py tests/test_report_charts.py tests/test_report_common.py tests/test_report_excel.py tests/test_report_integration.py tests/test_report_llm.py tests/test_report_snapshot.py tests/test_report.py tests/test_v3_algorithms.py tests/test_v3_html.py tests/test_v3_llm.py tests/test_v3_mode_semantics.py tests/test_v3_modes.py -v 2>&1 | tail -40`
Expected: 全绿（与 Stage A 同一基线；如果有 pre-existing 失败用例（继承自 Stage A），列出并标注非本 Stage 引入）。

- [ ] **Step 5.4: 跑全量 pytest 兜底**

Run: `uv run --extra dev python -m pytest -x --tb=short 2>&1 | tail -20`
Expected: 全绿。`-x` 在第一条失败处即停止，便于定位。

- [ ] **Step 5.5: 版本号 bump 0.3.18 → 0.3.19**

Edit `pyproject.toml:7`:

```toml
version = "0.3.19"
```

Edit `qbu_crawler/__init__.py:8`:

```python
__version__ = "0.3.19"
```

Run: `uv lock` 让 uv.lock 同步新版本。
Expected: uv.lock 中 `qbu-crawler` 条目 version 字段更新为 `0.3.19`。

- [ ] **Step 5.6: 更新 Continuity 文件**

> **占位填写规则**：下方 `<...>` 占位必须在执行 Step 5.7 commit 之前替换为真实值。`<T-B-N hash>` 用 `git log --oneline | head -10` 找到对应 commit；`last_updated` 用 `date '+%Y-%m-%d %H:%M'` 取本地时间。Continuity 是跨会话契约，留 `<...>` 即代表执行未完成。

改 `docs/reviews/2026-04-24-report-upgrade-continuity.md`：

1. **当前 Stage 指针**（替换整段）：

```
status:         Stage-B-COMPLETE · Phase2-T9-PLAN-NOT-WRITTEN
last_updated:   <YYYY-MM-DD HH:MM>
last_commit:    <T-B-5 commit hash short>
last_tag:       v0.3.19-stage-b
next_action:    Phase 2 T9 implementation plan via superpowers:writing-plans (trend_digest.data.[view].[dim].secondary_charts 数据层扩展)
next_stage:     Phase 2 T9 · trend_digest 数据层扩展（契约冻结期 Day 5+ 触发，视前 3 天 daily run 观测情况）
blocked_by:     契约冻结期观测中（Day 1 起算 → Day 5 解锁 T9）
```

2. **进度日志最上方追加**：

```markdown
### 2026-04-26 第 1 session (Stage B 执行)
- **Who**：Claude (Opus 4.7 1M · subagent-driven-development)
- **Done**：
  - Task 1: <hash> · artifact 路径相对化（report_snapshot 三 mode + workflows 双层防御）
  - Task 2: <hash> · kpis 字段消歧（negative_review_rate → all_sample_negative_rate；模板/LLM 改读 own_*）
  - Task 3: <hash> · trend year 视图语义 banner（trend_digest.view_notes 数据驱动）
  - Task 4: <hash> · LLM low-sample 改读 change_digest.summary.fresh_review_count（bootstrap 跳过）
  - Task 5: <hash> · 版本号 bump 0.3.18 → 0.3.19 + Continuity 推进 + tag v0.3.19-stage-b
  - 5 + 2 条 grep 门禁全绿（Stage A 5 条 + Stage B 新增 2 条）
  - report 相关 13 个测试文件全绿
  - subagent-driven → TDD → spec review → code quality review → finishing 全流程
- **Carry-over（follow-up，不阻塞 Phase 2 T9）**：
  - HTML banner JS wire 是否完整（front-end 切 view 时 banner 显隐）需要预发肉眼验收
  - artifact 路径迁移在生产数据库的影子库回归（参见 Continuity §5 遗留事项）
- **Next**：契约冻结期 Day 5（连续 3 个 daily run 观测 OK 后）开 Phase 2 T9 implementation plan
```

3. **遗留事项**（§5）将"Stage B 修 7 需要预发一条失效 analytics_path"标 ✅ 完成（已在 T-B-1 测试覆盖）。

4. 文件总行数仍需 ≤ 300：检查并精简最早的 session 进度日志（2026-04-24 第 1 session 改成 1 行摘要 + 链接到 D018 devlog）。

- [ ] **Step 5.7: 提交版本 bump 与 Continuity（独立 commit，便于回滚）**

```bash
git add pyproject.toml qbu_crawler/__init__.py uv.lock docs/reviews/2026-04-24-report-upgrade-continuity.md
git commit -m "chore: bump version 0.3.18 -> 0.3.19 (Stage B 完成 · 修 7-10)"
```

- [ ] **Step 5.8: 打 tag**

```bash
git tag -a v0.3.19-stage-b -m "Stage B · Phase 1 P2 remediation complete (修 7-10)"
git tag --list 'v0.3.*'
```

Expected: tag 列表包含 `v0.3.17-t0-hotfix / v0.3.18-stage-a / v0.3.19-stage-b`。

- [ ] **Step 5.9: （可选）push to remote — 等用户确认**

不自动执行。等用户审完 plan 与 commit 历史后由用户手动 `git push origin master --tags`。

---

## 验收清单（完成 Stage B 后必须 Yes 的项目）

- [ ] best-practice §3 修 7-10 全部代码改动落地
- [ ] best-practice §4 测试补强清单中 Stage B 范畴 4 条用例新增（`test_workflow_run_stores_relative_artifact_paths`、`test_artifact_resolver_recovers_when_original_path_moved`、`test_kpis_exposes_own_rate_only_to_templates`（即本 plan 的 `test_normalize_kpis_renames_ambiguous_negative_review_rate`）、`test_year_trend_has_semantic_banner`）
- [ ] best-practice §5 CI 门禁 5 条 + Stage B 新增 2 条全绿
- [ ] 报告相关 13 个测试文件全绿
- [ ] 版本号 0.3.19 + tag `v0.3.19-stage-b`
- [ ] Continuity `next_action` 已切换到 Phase 2 T9 plan
- [ ] 契约冻结期"`change_digest / trend_digest / kpis` 顶层键名"未被改动（`trend_digest.view_notes` 是次级新增，不算顶层；`kpis.negative_review_rate*` 删除是合规调整 — 但需要在 commit message 显式声明 "P2 K-rename, not Phase 1 schema change"，让契约冻结期审计可追溯）

---

## Stage B 与 Phase 2 T9 的并行边界（重申）

**禁动文件**（T9 启动前不允许 Stage B 触碰，Stage B 启动后不允许 T9 触碰）：

| Stage B 改的文件 | T9 改的文件（计划） |
|---|---|
| `qbu_crawler/server/report_snapshot.py` | `qbu_crawler/server/report_charts.py` |
| `qbu_crawler/server/workflows.py` | `qbu_crawler/server/report_analytics.py` 的 `secondary_charts` 段 |
| `qbu_crawler/server/report_common.py` 顶层 KPI 段 | — |
| `qbu_crawler/server/report_llm.py` low-sample 段 | — |
| `qbu_crawler/server/report_analytics.py` `_build_trend_digest` 末尾 view_notes | `report_analytics.py` 内 trend_dimension 子函数（构 secondary_charts） |
| `daily_report_v3.html.j2` toolbar 段 / .css / .js | `daily_report_v3.html.j2` panel 内 secondary_chart 段（T10） |

冲突处理：如果 Phase 2 T9 在 Stage B 执行期间提前启动（不应该但有可能），优先合 Stage B（小改动、文件少、grep 门禁可独立验证），T9 在 rebase 后单独处理冲突。`report_analytics._build_trend_digest` 是潜在冲突点 — Stage B 加 `view_notes`，T9 加 `secondary_charts`，二者都是 dict 顶层平级新键，rebase 时通常无冲突；如有冲突手动合并保留两者。
