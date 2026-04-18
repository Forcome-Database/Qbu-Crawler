# D017 — QBU 报告设计系统 V4 重构

**日期**：2026-04-18
**分支**：`feature/report-simulation`
**Spec**：`docs/superpowers/specs/2026-04-18-qbu-report-ds-v4-design.md`
**Plan**：`docs/superpowers/plans/2026-04-18-qbu-report-ds-v4.md`

## 背景

42 天模拟器产物审计暴露三个根本矛盾：
- 周报 1.9 MB、月报 148 KB（潦草）、日报 46 KB —— 产物强度与业务价值倒挂
- `partial/full/change/quiet` 四种模式存在于代码但 HTML 完全看不出区别
- V3 设计系统（Editorial Intelligence）只有周报真正在用

## 核心变更

### Phase 1 · 数据契约（阻断级 D1-D4）
- `AnalyticsEnvelope v4` schema：`kpis_raw + kpis_normalized + mode + mode_context` 同时落盘
- `generate_full_report_from_snapshot` 写盘前强制 normalize，月报 re-load 防御访问
- `workflow_runs.is_partial` + `reviews_count` 列新增 + `freeze_report_snapshot` 两条路径都写
- `safety_incidents` 复合 UNIQUE 索引 `(review_id, safety_level, failure_mode)`，与 `evidence_hash` 并存

### Phase 2 · 设计基建
- `daily_report_v3.css` 扩展：6 色 mode token + 3 级 confidence 徽章 + section-divider 数字眉头 + rate-bar 三段
- 10 个 `_partials/` Jinja 共享组件：head / kpi_bar / mode_strip / footer / hero / kpi_grid / tab_nav / issue_card / review_quote / empty_state
- `REPORT_DS_VERSION` 环境变量（默认 `v3`，simulator 默认 `v4`）+ v3 回滚回归测试

### Phase 3 · 三报告装配
- `daily.html.j2` 装配：mode 四分支视觉（灰 partial / 靛 full / 橙 change / 绿 quiet），cold-start "基线建立中"说明卡
- `weekly.html.j2` 装配：5 tab（总览 / 本周变化 / 问题诊断 / 产品排行 / 全景）
- `monthly.html.j2` 重构：7 tab（高管视图 / 本月变化 / 生命周期 / 品类 / 计分卡 / 竞品 / 全景）+ safety_incidents 按 review_id 去重分组
- 42 天模拟器切 v4 默认，核心 mode strip 验证：S01→partial / S02→full / S07/S08a→quiet / W0-W2→weekly

### Phase 4 · 邮件 + 口径呈现
- 邮件体系收敛：1 `_email_base.html.j2` + 3 变体（daily/weekly/monthly），`{% extends %}` 模式，删除 `email_full/change/quiet.html.j2`
- 6 个 Python caller 重构到新 base 契约（`_build_email_base_context` 帮助函数）
- KPI tooltip 补公式/数据源/置信度三段；CSS `white-space: pre-line` 支持多行
- 9 张 KPI 卡带 confidence 徽章（🟢 可信 / 🟡 参考 / 🔴 样本不足）
- 差评率卡附"好/中/差"三段 rate bar（D8）
- 自有评论卡 tooltip 附"未分类 N 条"（D5）
- 竞品差距指数 <20 样本时显示 `累积中 X/20`（D12）

## 踩坑

1. **`freeze_report_snapshot` cache-hit 路径**：首次发现是 sim 重复 run 时 `is_partial` 总为 0。根因是函数有 cache-hit 提前返回路径，没传播 is_partial 到 DB。加 cache-hit 补丁，首次 review 标 symmetry 风险被命中
2. **Simulator `env_bootstrap` 未 init_db**：新增的列在 sim DB 永远缺失。加 `models.init_db()` 调用
3. **Monthly 7 tab 类名不匹配 V3 JS**：原 `.tab-button.active` 改为统一 `.tab-btn.tab-active`
4. **`normalize_deep_report_analytics` 非幂等风险**：daily 渲染链路调用两次，目前数值无害但未来修改可能造成 list 累加。Code review 标为 latent，未来如有新派生字段需注意
5. **GBK 控制台编码**：windows 终端对 emoji 崩溃，测试中的 `path.write_text` 显式 `encoding="utf-8"`

## 回归状态

- 全量 pytest：789 通过，2 个已知 pre-existing 失败（`tests/test_v3_modes.py::test_change_mode_*`）
- 42 天模拟器部分覆盖（17 天，受限于 pre-existing `review_issue_labels UNIQUE` 冲突），所有触达场景的 V4 mode strip 渲染正确
- v3 回滚路径测试：`REPORT_DS_VERSION=v3` 仍产生旧 briefing HTML（无 mode-strip，含"累积快照"sentinel）

## 后续

- `review_issue_labels UNIQUE` 冲突修复（让 42 天 sim 完整跑通）
- `normalize_deep_report_analytics` 显式幂等性保证
- Panorama tab 接入 Chart.js（当前仅占位）
- 移除 v3 旧模板（`daily_briefing.html.j2` / `monthly_report.html.j2` / `daily_report_v3.html.j2`），确认 v4 生产稳定后

## 受益文件清单

- 新增：`qbu_crawler/server/analytics_safety.py`、`daily.html.j2`、`weekly.html.j2`、`monthly.html.j2`、`_email_base.html.j2`、10 个 `_partials/*.html.j2`
- 新增测试：`tests/test_analytics_envelope.py`、`tests/test_safety_dedup.py`、`tests/test_template_partials.py`、`tests/test_report_ds_flag.py`
- 修改：`report_common.py`（envelope helpers + tooltip + confidence）、`report_snapshot.py`（freeze / generate / email dispatch）、`report_html.py`（3 个 v4 renderers + `_write_template`）、`models.py`（2 列 + 复合索引）、`daily_report_v3.css`（+400 行 V4 扩展）、`config.py`（flag）、`env_bootstrap.py`（init_db + v4 默认）
- 删除：`email_full.html.j2`、`email_change.html.j2`、`email_quiet.html.j2`
