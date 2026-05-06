"""MCP Resources — expose database schema metadata for LLM context."""

from fastmcp import FastMCP

SCHEMA_OVERVIEW = """
# Qbu-Crawler 数据库结构概览

## 表关系

```
products (产品当前快照)
  ├── product_snapshots (价格/库存/评分历史，FK: product_id，可关联 workflow_run_id)
  └── reviews (用户评论，FK: product_id)
      ├── review_issue_labels (规则/模型标签，FK: review_id)
      └── review_analysis (LLM 评论洞察，FK: review_id)
tasks (爬虫任务记录)
  └── workflow_run_tasks (workflow 与 task 关联)
workflow_runs (每日工作流审计状态)
  ├── report_artifacts (报告产物清单，FK: run_id)
  └── notification_outbox (通知投递 outbox，通过 payload/dedupe_key 关联 workflow/task)
```

## 支持的站点
- basspro (Bass Pro Shops)
- meatyourmaker (Meat Your Maker)
- waltons (Walton's)

## 数据特性
- products 表使用 UPSERT，始终是最新状态
- product_snapshots 每次采集 INSERT，记录变化趋势
- reviews 增量写入，用 (product_id, author, headline, body_hash) 去重
- reviews.translate_status 管理翻译队列（后台线程自动翻译评论为中文）
- reviews.date_published_parsed 是评论发布时间趋势的优先字段；date_published 是原始文本
- products.ownership 区分自有产品(own)和竞品(competitor)
- products.review_count 是站点展示评论总数；ratings_only_count 是仅星级无文字评论数
- tasks 记录任务历史，params/progress/result 为 JSON 字段
- workflow_runs 记录每日工作流、报告阶段、报告生成状态、业务邮件状态和 workflow 通知状态
- notification_outbox 是 must-deliver 通知真值；不能把 hook/HTTP 成功等同最终送达
"""

SCHEMA_PRODUCTS = """
## products 表 — 产品当前快照

每个产品的最新状态，URL 唯一键，每次采集 UPSERT 更新。

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK, AUTO | 产品 ID |
| url | TEXT | UNIQUE, NOT NULL | 产品页 URL |
| site | TEXT | NOT NULL | 站点标识：basspro, meatyourmaker, waltons |
| name | TEXT | | 产品名称 |
| sku | TEXT | | SKU 编号 |
| price | REAL | | 当前价格 (USD) |
| stock_status | TEXT | | 库存状态：in_stock, out_of_stock, unknown |
| review_count | INTEGER | | 评论总数 |
| rating | REAL | | 平均评分 (0-5) |
| scraped_at | TIMESTAMP | | 最后采集时间 |
| ownership | TEXT | NOT NULL, DEFAULT 'competitor' | 产品归属：own(自有) 或 competitor(竞品) |
| ratings_only_count | INTEGER | DEFAULT 0 | 站点展示评论中仅星级、无文字的数量 |
| last_scrape_completeness | REAL | | 最近一次采集完整率 |
| last_scrape_warnings | TEXT | | 最近一次采集诊断 JSON |

### 口径说明
- 默认“评论数”应指 reviews 表已入库行数，而不是 products.review_count。
- products.review_count 应显示为“站点展示评论总数”。
- 可采集文字评论上限通常为 review_count - ratings_only_count。

### 常用查询示例
```sql
SELECT * FROM products WHERE site = 'basspro' AND rating >= 4.5 ORDER BY rating DESC;
SELECT * FROM products WHERE name LIKE '%fishing%' ORDER BY price ASC;
SELECT site, stock_status, COUNT(*) FROM products GROUP BY site, stock_status;
SELECT ownership, COUNT(*), AVG(price) FROM products GROUP BY ownership;
SELECT SUM(review_count) AS site_reported_review_total_current,
       SUM(review_count - COALESCE(ratings_only_count, 0)) AS text_review_total_current
FROM products;
```
"""

SCHEMA_SNAPSHOTS = """
## product_snapshots 表 — 价格/库存/评分历史

每次采集 INSERT 一条，用于趋势分析和价格追踪。

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK, AUTO | 快照 ID |
| product_id | INTEGER | FK → products.id, CASCADE | 关联产品 |
| price | REAL | | 采集时价格 (USD) |
| stock_status | TEXT | | 采集时库存状态 |
| review_count | INTEGER | | 采集时评论数 |
| rating | REAL | | 采集时评分 |
| scraped_at | TIMESTAMP | | 采集时间 |
| ratings_only_count | INTEGER | DEFAULT 0 | 采集时仅星级评论数 |
| workflow_run_id | INTEGER | FK → workflow_runs.id | 归属 workflow run（如有） |

### 常用查询示例
```sql
SELECT scraped_at, price FROM product_snapshots WHERE product_id = 1 ORDER BY scraped_at;
SELECT DISTINCT ps.product_id, p.name
FROM product_snapshots ps JOIN products p ON ps.product_id = p.id
WHERE ps.scraped_at >= datetime('now', '-7 days')
GROUP BY ps.product_id HAVING MAX(ps.price) != MIN(ps.price);
```
"""

SCHEMA_REVIEWS = """
## reviews 表 — 用户评论

增量写入，(product_id, author, headline, body_hash) 联合唯一键去重。

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK, AUTO | 评论 ID |
| product_id | INTEGER | FK → products.id, CASCADE | 关联产品 |
| author | TEXT | | 评论作者 |
| headline | TEXT | | 评论标题 |
| body | TEXT | | 评论正文 |
| body_hash | TEXT | | MD5(body) 前16位，用于去重 |
| rating | REAL | | 评论评分 (0-5) |
| date_published | TEXT | | 站点原始发布日期文本 |
| date_published_parsed | TEXT | | 解析后的发布日期，评论发布时间趋势优先使用 |
| date_published_estimated | INTEGER | DEFAULT 0 | 发布日期是否为估算 |
| date_parse_method | TEXT | | 日期解析方法 |
| date_parse_anchor | TEXT | | 相对日期解析锚点 |
| date_parse_confidence | REAL | | 日期解析置信度 |
| source_review_id | TEXT | | 站点原始评论 ID |
| images | TEXT | | JSON 数组，MinIO 图片 URL 列表 |
| scraped_at | TIMESTAMP | | 采集时间 |
| headline_cn | TEXT | | 评论标题中文翻译 |
| body_cn | TEXT | | 评论正文中文翻译 |
| translate_status | TEXT | | 翻译状态：NULL=待翻译, done=完成, failed=重试中, skipped=跳过 |
| translate_retries | INTEGER | DEFAULT 0 | 翻译失败重试次数 |

### 常用查询示例
```sql
SELECT * FROM reviews WHERE product_id = 1 AND rating <= 2 ORDER BY date_published_parsed DESC;
SELECT r.*, p.name FROM reviews r JOIN products p ON r.product_id = p.id
WHERE r.images IS NOT NULL AND r.images != '[]';
SELECT p.name, p.rating as product_rating, AVG(r.rating) as avg_review_rating
FROM products p JOIN reviews r ON p.id = r.product_id GROUP BY p.id;
```

### ⚠ JOIN 聚合注意
products 与 reviews 是一对多关系。按站点/归属统计产品数时，必须在 products 表上直接聚合：
```sql
-- ✅ 正确：直接在 products 上 COUNT
SELECT site, COUNT(*) FROM products GROUP BY site;

-- ❌ 错误：JOIN reviews 后 COUNT(*) 会按评论数膨胀
-- 一个有 50 条评论的产品会被计为 50 而非 1
SELECT p.site, COUNT(*) FROM products p JOIN reviews r ON p.id = r.product_id GROUP BY p.site;

-- ✅ 如需统计每站点评论数，应以 reviews 为主表
SELECT p.site, COUNT(*) FROM reviews r JOIN products p ON r.product_id = p.id GROUP BY p.site;
```
"""

SCHEMA_TASKS = """
## tasks 表 — 爬虫任务记录

记录所有通过 API/MCP 提交的爬虫任务历史。

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | TEXT | PK | 任务 UUID |
| type | TEXT | NOT NULL | 任务类型：scrape（按URL抓取）, collect（分类页采集） |
| status | TEXT | NOT NULL | 状态：pending, running, completed, failed, cancelled |
| params | TEXT (JSON) | NOT NULL | 任务参数，scrape: {"urls": [...]}, collect: {"category_url": "...", "max_pages": N} |
| progress | TEXT (JSON) | | 进度信息 {"total": N, "completed": N, "failed": N, "current_url": "..."} |
| result | TEXT (JSON) | | 完成结果 {"products_saved": N, "reviews_saved": N} |
| error | TEXT | | 失败时的错误信息 |
| created_at | TIMESTAMP | | 创建时间 |
| updated_at | TIMESTAMP | | 更新时间 |
| last_progress_at | TIMESTAMP | | 最近进度更新时间 |
| worker_token | TEXT | | worker 租约 token |
| system_error_code | TEXT | | 系统错误分类 |
| started_at | TIMESTAMP | | 开始执行时间 |
| finished_at | TIMESTAMP | | 完成时间 |
| reply_to | TEXT | | ad-hoc 任务完成通知目标 |
| notified_at | TIMESTAMP | | 临时任务通知标记时间 |

### result URL 级采集真相
scrape 任务 result 应优先读取：
- expected_urls：计划抓取 URL
- saved_urls：成功入库或刷新的 URL
- failed_urls：失败 URL 及阶段/错误类型

collect 任务可能先发现 URL 再抓取，需结合 result 和 workflow_run_tasks 判断完整链路。

### 常用查询示例
```sql
SELECT id, type, status, progress, result, created_at FROM tasks ORDER BY created_at DESC LIMIT 10;
SELECT status, COUNT(*) FROM tasks GROUP BY status;
```
"""

SCHEMA_WORKFLOW_RUNS = """
## workflow_runs 表 — 每日工作流审计状态

记录 embedded scheduler / WorkflowWorker 创建和推进的每日 run。它是每日任务、报告产物和 delivery 内部状态的主审计入口。

| 列名 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | workflow run ID |
| workflow_type | TEXT | 通常为 daily |
| status | TEXT | submitted, running, reporting, completed, failed, needs_attention |
| report_phase | TEXT | 报告阶段：none, fast_pending, fast_sent, full_pending, full_sent, full_sent_local |
| logical_date | TEXT | 业务日期 |
| trigger_key | TEXT UNIQUE | 幂等键，如 daily:2026-04-30 |
| data_since / data_until | TIMESTAMP | 本次数据窗口 |
| snapshot_at | TIMESTAMP | snapshot 时间 |
| snapshot_path / snapshot_hash | TEXT | immutable snapshot 产物 |
| excel_path / analytics_path / pdf_path | TEXT | 报告产物路径 |
| report_mode | TEXT | full, change, quiet |
| scrape_quality | TEXT (JSON) | 采集完整率和失败 URL 诊断 |
| scrape_completeness_ratio | REAL | 采集完整率 |
| zero_scrape_count | INTEGER | 零采集计数 |
| report_copy_json | TEXT | 报告文案 JSON |
| report_generation_status | TEXT | unknown, pending, generated, failed, skipped |
| email_delivery_status | TEXT | unknown, pending, sent, failed, skipped |
| workflow_notification_status | TEXT | unknown, pending, sent, deadletter, partial, skipped |
| delivery_last_error | TEXT | 最近 delivery 错误 |
| delivery_checked_at | TEXT | delivery 状态检查时间 |
| requested_by / service_version | TEXT | 调用来源和版本 |
| created_at / updated_at / started_at / finished_at | TIMESTAMP | 生命周期时间 |
| error | TEXT | 失败原因 |

### 状态语义
- report_generation_status 只表达本地报告产物是否生成。
- email_delivery_status 只表达业务日报邮件是否送达。
- workflow_notification_status 只表达 workflow 外部通知是否送达。
- full_sent_local + workflow_notification_status=deadletter 不代表业务日报失败，只代表 workflow 外部通知失败。
"""

SCHEMA_WORKFLOW_RUN_TASKS = """
## workflow_run_tasks 表 — workflow 与爬虫任务关联

| 列名 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 关联记录 ID |
| run_id | INTEGER | workflow_runs.id |
| task_id | TEXT | tasks.id |
| task_type | TEXT | scrape 或 collect |
| site | TEXT | 站点 |
| ownership | TEXT | own 或 competitor |
| created_at | TIMESTAMP | 创建时间 |

常用于从 workflow run 追踪所有 collect/scrape 子任务，再读取 tasks.result 的 expected_urls/saved_urls/failed_urls。
"""

SCHEMA_NOTIFICATION_OUTBOX = """
## notification_outbox 表 — 通知投递 outbox

must-deliver 通知真值来源。通知是否送达以这里的 status/delivered_at/last_error 为准。

| 列名 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | outbox ID |
| kind | TEXT | task_completed, workflow_started, workflow_fast_report, workflow_full_report, workflow_attention |
| channel | TEXT | 通知渠道 |
| target | TEXT | 目标会话或用户 |
| payload | TEXT (JSON) | 模板变量和业务 payload |
| dedupe_key | TEXT UNIQUE | 幂等键 |
| payload_hash | TEXT | payload hash |
| status | TEXT | pending, claimed, failed, sent, deadletter |
| claimed_at / claim_token / lease_until | TIMESTAMP/TEXT | worker 租约 |
| bridge_request_id | TEXT | bridge/openclaw 侧请求 ID |
| last_http_status / last_exit_code | INTEGER | 最近投递状态 |
| last_error | TEXT | 最近错误 |
| attempts | INTEGER | 尝试次数 |
| delivered_at | TIMESTAMP | 成功送达时间 |
| created_at / updated_at | TIMESTAMP | 生命周期时间 |
"""

SCHEMA_REPORT_ARTIFACTS = """
## report_artifacts 表 — 报告产物清单

| 列名 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | artifact ID |
| run_id | INTEGER | workflow_runs.id |
| artifact_type | TEXT | html_attachment, xlsx, pdf, snapshot, analytics, email_body |
| path | TEXT | 产物路径 |
| hash | TEXT | 文件 hash |
| template_version | TEXT | 模板版本 |
| generator_version | TEXT | 生成器版本 |
| bytes | INTEGER | 文件大小 |
| created_at | TIMESTAMP | 生成时间 |

用于审计本地报告产物是否生成。workflow_runs 的 *_path 字段是常用快捷入口。
"""

SCHEMA_REVIEW_ANALYSIS = """
## review_analysis 表 — 评论分析结果

| 列名 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 分析记录 ID |
| review_id | INTEGER | reviews.id |
| sentiment | TEXT | 情绪分类 |
| sentiment_score | REAL | 情绪分 |
| labels | TEXT (JSON) | 标签列表 |
| features | TEXT (JSON) | 产品特征列表 |
| impact_category | TEXT | 影响分类 |
| failure_mode | TEXT | 归一化失败模式 |
| insight_cn / insight_en | TEXT | 中英文洞察 |
| llm_model | TEXT | 模型名 |
| prompt_version | TEXT | prompt 版本 |
| token_usage | INTEGER | token 用量 |
| analyzed_at | TEXT | 分析时间 |

适合做问题聚类、根因解释和竞品机会总结。事实口径仍应回到 reviews/products 原始字段。
"""

SCHEMA_REVIEW_ISSUE_LABELS = """
## review_issue_labels 表 — 评论问题标签

| 列名 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 标签记录 ID |
| review_id | INTEGER | reviews.id |
| label_code | TEXT | 问题标签编码 |
| label_polarity | TEXT | positive 或 negative |
| severity | TEXT | 严重度 |
| confidence | REAL | 置信度 |
| source | TEXT | rule 或 llm |
| taxonomy_version | TEXT | 标签体系版本 |
| created_at / updated_at | TIMESTAMP | 生命周期时间 |

常用于差评问题 TopN、问题趋势和问题样本钻取。聚合时注意按 review_id 去重。
"""

SCHEMAS = {
    "overview": SCHEMA_OVERVIEW,
    "products": SCHEMA_PRODUCTS,
    "product_snapshots": SCHEMA_SNAPSHOTS,
    "reviews": SCHEMA_REVIEWS,
    "tasks": SCHEMA_TASKS,
    "workflow_runs": SCHEMA_WORKFLOW_RUNS,
    "workflow_run_tasks": SCHEMA_WORKFLOW_RUN_TASKS,
    "notification_outbox": SCHEMA_NOTIFICATION_OUTBOX,
    "report_artifacts": SCHEMA_REPORT_ARTIFACTS,
    "review_analysis": SCHEMA_REVIEW_ANALYSIS,
    "review_issue_labels": SCHEMA_REVIEW_ISSUE_LABELS,
}


def register_resources(mcp: FastMCP):
    """Register all schema resources on the MCP server."""

    @mcp.resource("db://schema/{table_name}")
    def get_schema(table_name: str) -> str:
        """获取数据库表的结构说明，包含列定义、约束、业务语义和示例 SQL。
        可用的 table_name: overview, products, product_snapshots, reviews, tasks,
        workflow_runs, workflow_run_tasks, notification_outbox, report_artifacts,
        review_analysis, review_issue_labels。
        使用 overview 查看所有表的关系概览。"""
        content = SCHEMAS.get(table_name)
        if not content:
            return f"Unknown table: {table_name}. Available: {', '.join(SCHEMAS.keys())}"
        return content
