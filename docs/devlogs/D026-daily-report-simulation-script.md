# D026 每日报告模拟脚本

## 背景

为了在不触碰生产数据库和真实爬虫任务的前提下验证每日报告效果，新增独立模拟脚本。脚本写入与生产一致的 SQLite 表结构，并复用真实 workflow / snapshot / report 生成链路。

## 实现

- 新增 `scripts/simulate_daily_report.py`
- 默认输出到 `data/simulations/daily-report-<timestamp>/`
- 每次模拟生成独立 `products.db` 和 `reports/`
- 写入 `products`、`product_snapshots`、`reviews`、`review_analysis`、`tasks`、`workflow_runs`
- 通过 `WorkflowWorker.process_once()` 推进真实报告流程
- 默认禁用业务邮件、AI digest、OpenClaw hook 和运维告警外发
- `--use-llm` 可使用已配置的 OpenAI 兼容 LLM 生成评论模板
- `--image-url` 可复用旧评论图片 URL

## 使用

```bash
uv run python scripts/simulate_daily_report.py 7
uv run python scripts/simulate_daily_report.py 7 --use-llm
uv run python scripts/simulate_daily_report.py 7 --image-url https://example.com/review-image.jpg
```

## 验证

```bash
uv run pytest tests/server/test_simulate_daily_report_script.py -q
uv run ruff check scripts/simulate_daily_report.py tests/server/test_simulate_daily_report_script.py
uv run python scripts/simulate_daily_report.py 3 --seed 13
```
