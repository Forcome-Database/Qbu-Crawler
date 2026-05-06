# D029 测试14报表语义与采集质量修复

日期：2026-05-06

## 背景

测试14生产产物中，run6 本期只新增 1 条竞品差评，但邮件和 HTML 同时展示累计诊断、本期变化和运维质量，导致“本期 / 累计 / 采集健康”语义混用。run5 quiet 报告还出现高风险数从 5 跳到 0 的不一致。用户随后确认全景数据只有第一次是全量，后续报告只显示当天数据。

## 根因

1. `REPORT_PERSPECTIVE=dual` 下主 analytics 是累计视角，但邮件副标题仍用“本期”展示累计评论数。
2. V3 总览把 `change_digest.summary.ingested_review_count` 标成“基线样本评论”，实际是本期入库评论。
3. 采集质量用新增保存数 `ingested_count` 计算完整率，增量日大量评论去重后 saved=0，被误判低覆盖。
4. `ratings_only_count` 在 scraper 未能提取时落 0，并在产品 UPSERT 中覆盖历史有效值。
5. quiet/change 路径没有像 full 路径一样传入同步后的 `analysis_labels`，导致风险 severity 使用规则分类降级。
6. 趋势查询依赖 `date_published_parsed` 或绝对日期字符串，旧数据中的 `a hour ago` 无法进入趋势。
7. quiet/change 路径生成 analytics/html 文件后未登记 `report_artifacts`。
8. V3 全景页的评论表、徽标、说明文字和产品筛选直接消费 `snapshot.reviews` / `snapshot.products`；在 full/dual 报告中该字段是本期窗口，累计数据实际在 `snapshot.cumulative`。

## 修复

- 邮件副标题改为累计评论 + 本期新增评论并列展示。
- V3 总览与 `review_scope_cards` 将该指标命名为“本期入库评论”。
- `_parse_date_published()` 支持 minute/hour 相对时间。
- 趋势查询对不可解析发布时间回退到 `scraped_at` 日期，兼容已入库的旧相对时间数据。
- `summarize_scrape_quality()` 优先读取 task `product_summaries[].extracted_review_count` 作为采集完整率分子；新增保存数不再驱动低覆盖。
- `save_product()` 在本次未提供 `ratings_only_count` 时保留旧值，避免 shadow root 失败污染分母。
- quiet/change 路径构建累计 analytics 前同步 review labels，并登记 analytics/html artifact。
- `sync_review_labels()` 在 DB-as-label-store 不可用或 replay 场景下回退本轮内存标签。
- HTML 渲染入口为 V3 模板注入 `panorama` 数据集：优先使用 `snapshot.cumulative.products/reviews`，缺失时回退本期窗口；全景 tab 徽标、说明、产品筛选和评论表统一消费该数据集。

## 验证

新增 `tests/server/test_test14_report_regressions.py` 覆盖测试14关键回归。

已运行：

```bash
uv run pytest tests/server/test_test14_report_regressions.py tests/server/test_historical_report_paths.py tests/server/test_historical_trend_queries.py tests/server/test_email_full_template.py tests/server/test_scrape_quality_zero_scrape.py tests/test_scrape_quality.py tests/test_report_common.py::test_date_published_parsed_backfill tests/server/test_test10_artifact_replay.py tests/server/test_run_log.py tests/server/test_report_manifest.py tests/server/test_internal_ops_alert.py tests/server/test_workflow_ops_alert_wiring.py -q
uv run pytest tests/server/test_report_contract.py tests/server/test_report_contract_renderers.py tests/server/test_attachment_html_today_changes.py tests/test_v3_html.py tests/test_v3_excel.py -q
uv run pytest tests/server/test_historical_report_paths.py tests/server/test_test10_artifact_replay.py tests/server/test_run_log.py tests/server/test_report_manifest.py tests/server/test_internal_ops_alert.py tests/server/test_workflow_ops_alert_wiring.py tests/server/test_report_artifacts.py -q
uv run pytest tests/server/test_test14_report_regressions.py tests/server/test_historical_trend_queries.py tests/server/test_email_full_template.py tests/server/test_scrape_quality_zero_scrape.py tests/test_scrape_quality.py tests/test_report_common.py::test_date_published_parsed_backfill tests/server/test_historical_report_paths.py tests/server/test_test10_artifact_replay.py tests/server/test_run_log.py tests/server/test_report_manifest.py tests/server/test_internal_ops_alert.py tests/server/test_workflow_ops_alert_wiring.py tests/server/test_report_artifacts.py tests/server/test_report_contract.py tests/server/test_report_contract_renderers.py tests/server/test_attachment_html_today_changes.py tests/server/test_attachment_html_other.py tests/test_v3_html.py tests/test_v3_excel.py -q
```

## 后续

站点 scraper 仍无法区分 `ratings_only_count=0` 是真实 0 还是提取失败。本次先在存储层保留历史值避免污染；如果后续要精细化，应让站点 scraper 返回三态或携带 ratings-only 提取诊断。
