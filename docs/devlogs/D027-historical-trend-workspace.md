# D027 历史口径变化趋势页

## 背景

变化趋势页需要和产品趋势一样基于历史库，而不是只消费本次新采集评论。旧实现的趋势主图主要来自当前 analytics 输入和 `_build_trend_data()`，产品历史查询使用 `datetime('now')`，旧报告回放会随当前时间漂移。

## 实现

- 新增 `report.query_trend_history(until, lookback_days)`，按报告 `data_until` 同时截断 `reviews.scraped_at` 和评论发布时间。
- 新增 `models.get_product_snapshots_until()`，优先用 `product_url` 查询，只有缺少 URL 时才退回 `sku + site`。
- 在现有 `trend_digest` 内增加 `workspace`，不新增平行顶层字段。
- `workspace` 固定三种时间视图和四个维度：口碑趋势、问题趋势、产品趋势、竞品对比。
- full / change / quiet 报告路径都通过 `_build_trend_history_for_snapshot()` 注入历史趋势输入。
- V3 HTML 趋势页优先消费 `trend_digest.workspace`，没有 workspace 时保留旧 `primary_chart + drill_downs` fallback。

## 口径注意

- 评论趋势按评论发布时间分桶，但只允许使用报告截止前已经入库的评论。
- 产品趋势按 `product_snapshots.scraped_at` 分桶，不能用 `products` 当前截面推历史趋势。
- 产品差评率变化来自历史评论按 SKU 聚合，不从 `product_snapshots` 推断。
- 用户可见文案禁用“快照”“声浪”“声量”“上期”，对比统一写成明确窗口。

## 验证

- `uv run pytest tests/server/test_historical_trend_queries.py tests/server/test_historical_trend_digest.py tests/server/test_historical_report_paths.py tests/server/test_historical_trend_template.py tests/server/test_attachment_html_trends.py tests/server/test_trend_digest_thresholds.py tests/test_report_charts.py tests/test_v3_html.py tests/server/test_simulate_daily_report_script.py -q`
- `uv run pytest tests/test_report_snapshot.py tests/server/test_report_contract_renderers.py tests/test_v3_modes.py -q`
- `uv run python scripts\simulate_daily_report.py 30`

30 天模拟产物确认最后一天 `trend_digest.workspace` 存在，近30天四个维度均为 ready，每个维度 3 个 KPI。
