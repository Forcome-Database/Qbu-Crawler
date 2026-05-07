# D031 钉钉与周报邮件证据化文案

日期：2026-05-07

## 背景

周报邮件改为每周发送后，日常触达主要依赖钉钉摘要。用户希望钉钉和邮件正文保留评论原文，避免只有系统分析而缺少可核验证据。

## 实现

- `workflow_daily_digest` 的评论条目拆分为 `原文` 和 `译文`：
  - `原文` 使用 `reviews.body/headline`
  - `译文` 使用 `reviews.body_cn/headline_cn`
  - 翻译缺失时显示“翻译中”
- 钉钉摘要按新增评论信号动态切换区块：
  - 自有有差评：`自有风险 TOP3`
  - 自有无差评但有好评：`自有亮点 TOP3`
  - 竞品有好评：`竞品亮点 TOP3`
  - 竞品无好评但有差评：`竞品机会 TOP3`
- 邮件正文新增“代表性原文证据”区，最多展示自有和竞品各 2 条代表性评论，完整明细继续由 HTML / Excel 附件承载。
- 邮件主题按 `snapshot.report_window.type` 区分 `产品评论周报`、`产品评论监控起点` 和 `产品评论日报`。

## 验证

- `uv run pytest tests/server/test_daily_dingtalk_digest.py tests/server/test_email_full_template.py tests/server/test_weekly_report_window.py tests/server/test_weekly_email_cadence.py tests/test_report.py::test_build_daily_deep_report_email_keeps_only_core_summary tests/test_report.py::test_build_daily_deep_report_email_subject_uses_report_window tests/test_report_snapshot.py::test_email_full_in_production_pipeline_renders_health_index -q`
- 使用 30 天模拟产物 `workflow-run-30-snapshot-2026-05-07.json` 人工渲染钉钉摘要，确认真实原文、译文和动态区块可见。
