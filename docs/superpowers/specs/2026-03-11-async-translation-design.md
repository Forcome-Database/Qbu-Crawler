# 异步翻译解耦设计

## 背景

当前 `generate_report()` 管道是同步阻塞的：`查询 → 翻译(阻塞) → Excel → 邮件`。翻译 200 条评论需要 1-5 分钟，阻塞报告生成和邮件发送。翻译结果也是"用完即弃"，不持久化，同一条评论每次报告都要重新翻译。

## 目标

1. 翻译与采集并行执行，不阻塞爬虫、报告生成、邮件发送
2. 翻译结果持久化到数据库，一次翻译永久复用
3. 失败自动重试，毒丸评论自动跳过，进程重启不丢状态
4. 轻量实现，零外部依赖，契合现有 SQLite + threading 架构

## 方案：DB-as-Queue + 后台守护线程

### 核心思路

- `reviews` 表本身充当翻译队列，新增翻译状态列
- 后台 `TranslationWorker` 守护线程定时轮询未翻译的行
- 爬虫保存评论后主动 `trigger()` 唤醒翻译线程，不等轮询
- `generate_report` 直接从 DB 读取已翻译内容，秒级完成

### 时间线对比

**现在（串行）：**
```
0-30min  爬虫（翻译空闲）
30-35min 翻译（阻塞）
35min    报告
```

**改后（并行）：**
```
0min   爬虫开始，陆续写入 reviews
1min   TranslationWorker 发现新评论 → 翻译
2min   又有新 reviews → 翻译
...
30min  爬虫结束，此时 95%+ 评论已翻好
31min  最后一批翻完
31min  generate_report → 全量中文，零等待
```

## 数据库变更

### reviews 表新增 4 列

| 列名 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `headline_cn` | TEXT | NULL | 翻译后的标题 |
| `body_cn` | TEXT | NULL | 翻译后的正文 |
| `translate_status` | TEXT | NULL | NULL=待翻译, done=完成, failed=待重试, skipped=跳过 |
| `translate_retries` | INTEGER | 0 | 失败重试次数，>=3 自动标记 skipped |

### 新增索引

```sql
CREATE INDEX IF NOT EXISTS idx_reviews_translate_status ON reviews (translate_status);
```

避免评论量增长后队列查询变成全表扫描。

### 迁移策略

在 `init_db()` 的 migrations 列表中追加 4 条 ALTER TABLE（与现有 body_hash 迁移模式一致，使用独立 `execute()` 调用，不用 `executescript()`）。

ALTER TABLE 完成后，执行回填 UPDATE（在同一个 `init_db()` 函数中，仿照 body_hash 回填模式）：
```sql
UPDATE reviews SET translate_status = 'skipped' WHERE translate_status IS NULL;
```
将所有历史评论标记为 `skipped`，避免启动时翻译雪崩。

**时序保证：** `translator.start()` 在 `init_db()` 之后调用（见 app.py 变更），确保迁移和回填完成后翻译线程才开始轮询。

用户可通过 `trigger_translate(reset_skipped="true")` MCP Tool 手动重置 skipped 评论并补翻历史。

### 翻译队列查询

```sql
SELECT id, headline, body FROM reviews
WHERE translate_status IS NULL
   OR (translate_status = 'failed' AND translate_retries < 3)
ORDER BY scraped_at DESC
LIMIT 20
```

## TranslationWorker 设计

### 新文件：`server/translator.py`

```python
class TranslationWorker:
    def __init__(self, interval=60, batch_size=20):
        self._interval = interval          # 轮询间隔（秒）
        self._batch_size = batch_size       # 每批翻译条数
        self._stop_event = Event()          # 优雅停止
        self._wake_event = Event()          # 手动触发唤醒
        self._thread = Thread(daemon=True)  # 守护线程
        self._client = None                 # 复用 OpenAI client

    def start(self)    # 启动守护线程（LLM 未配置时直接 return）
    def stop(self)     # 设置 stop_event，优雅退出
    def trigger(self)  # 外部调用，立即唤醒不等轮询
```

### 轮询循环逻辑

```
loop:
  1. _wake_event.clear() 然后 _wake_event.wait(timeout=interval)
     （clear 在 wait 前，丢失一次 trigger 无影响，60s 后自动补上）
  2. 查询未翻译/失败的评论（LIMIT batch_size, ORDER BY scraped_at DESC）
  3. 跳过 headline+body 都为空的（直接标记 done）
  4. 调用 LLM 批量翻译（复用现有 prompt 逻辑）
  5. 逐条 UPDATE（非批量）：
     - LLM 返回了该条 → UPDATE headline_cn, body_cn, translate_status='done'
     - LLM 未返回该条（部分成功）→ 保持 NULL，下轮自动捞出
  6. 整批 LLM 调用异常 → 该批所有评论 translate_retries += 1，>=3 则标记 'skipped'
  7. 如果还有剩余未翻译的，立即进入下一轮（不等 interval）
  8. 全部翻完才进入 wait 等待
```

### 部分批次成功的处理

LLM 批量翻译 20 条，可能只返回 15 条结果。处理策略：
- 返回的 15 条：按 `index` 匹配，逐条 UPDATE 为 `done`
- 未返回的 5 条：保持 `translate_status IS NULL`，下轮轮询自动捞出重试
- 这与 `failed`（整批异常）不同：`failed` 会增加 `translate_retries` 计数，而未返回的不增加

### 关键设计决策

- **OpenAI Client 复用**：初始化时创建一次，避免每批新建 HTTP 连接
- **最新优先**：`ORDER BY scraped_at DESC`，确保今天的报告数据先翻好
- **毒丸防护**：`translate_retries >= 3` 自动标记 `skipped`，不卡队列
- **空内容跳过**：headline+body 都为空时直接标记 `done`，不浪费 API 调用
- **进程崩溃恢复**：DB-as-queue 天然支持，翻译到一半挂了重启自动续翻

## 爬虫集成

### TaskManager 变更

`TaskManager.__init__` 接收 `translator` 参数（TranslationWorker 实例）。

在 `_run_scrape`（约 line 137）和 `_run_collect`（约 line 216）中，每次 `save_reviews()` 返回 `rc > 0` 后调用 `self._translator.trigger()`。两处逻辑完全相同：

```python
# _run_scrape 和 _run_collect 中都需要加这段
rc = models.save_reviews(pid, reviews)
if rc > 0 and self._translator:
    self._translator.trigger()
```

评论入库后几秒内即开始翻译，爬虫结束时绝大部分评论已翻完。

## 报告生成流程变更

### report.py 变更

- `generate_report()` 移除翻译步骤，直接从 DB 读取 `headline_cn`/`body_cn`
- `query_report_data()` 的 SQL 加上 `r.headline_cn, r.body_cn, r.translate_status`
- 返回值新增 `untranslated_count` 字段
- 邮件正文：如果 `untranslated_count > 0`，附注"X 条评论翻译进行中"
- `translate_reviews()` 及其辅助函数 `_call_llm()`, `_strip_markdown_json()` 从 `report.py` 移至 `translator.py`

### generate_report 返回值

```python
{
    "products_count": 25,
    "reviews_count": 150,
    "translated_count": 145,
    "untranslated_count": 5,    # 新增
    "excel_path": "data/reports/scrape-report-2026-03-11.xlsx",
    "email": {"success": True, ...},
}
```

## MCP 层变更

### generate_report Tool 更新

描述改为："查询新增数据（含已翻译的中文）→ 生成 Excel → 发送邮件"。不再包含翻译步骤。

### 新增 Tool：trigger_translate

```python
@mcp.tool
def trigger_translate(reset_skipped: str = "false") -> str:
    """手动触发翻译，立即唤醒后台翻译线程处理未翻译的评论。
    reset_skipped: "true" 时先将所有 skipped 评论重置为待翻译（用于补翻历史数据），
    "false"（默认）只触发现有待翻译队列。
    返回当前待翻译数量。"""
```

### 新增 Tool：get_translate_status

```python
@mcp.tool
def get_translate_status(since: str = "") -> str:
    """查询翻译进度：总评论数、已翻译、待翻译、失败数、跳过数。
    since: 可选，上海时间戳（YYYY-MM-DDTHH:MM:SS），只统计该时间之后的评论。
    留空则返回全量统计。"""
```

## 服务启动流程变更

### app.py 变更

```python
from server.translator import TranslationWorker

translator = TranslationWorker(
    interval=60,
    batch_size=config.LLM_TRANSLATE_BATCH_SIZE,
)
task_manager = TaskManager(max_workers=config.MAX_WORKERS, translator=translator)

def start_server(...):
    models.init_db()
    translator.start()  # 启动翻译守护线程
    ...
```

## OpenClaw Workspace 文档更新

| 文件 | 改动 | 详情 |
|------|------|------|
| `TOOLS.md` | 修改 | 工具参数速查表新增 `trigger_translate` 和 `get_translate_status` 行；通知模板新增翻译进度行 |
| `AGENTS.md` | 不改 | 临时任务"发邮件"流程逻辑不变（`generate_report` 参数不变），只是响应变快 |
| `skills/daily-scrape-report/SKILL.md` | 修改 | 步骤 2 描述从"查询+翻译+Excel+邮件"改为"查询(含翻译)+Excel+邮件"；新增可选步骤：先 `get_translate_status(since=submitted_at)` 检查翻译完成度 |
| `HEARTBEAT.md` | 不改 | 心跳只检查爬虫任务状态，翻译由后台线程自动处理，不需要心跳额外关注 |

## OpenClaw 阶段 3 新流程

```
爬虫全部完成
  → get_translate_status 看一眼
  → 未翻译 == 0？直接 generate_report
  → 未翻译 > 0？等 1 分钟再看（最多等 3 轮）
  → 超时仍有残留？照常发报告，邮件注明 "X 条翻译中"
```

## 配置项

### 新增配置（config.py / .env）

| 配置 | 默认值 | 说明 |
|------|--------|------|
| `TRANSLATE_INTERVAL` | `60` | 翻译轮询间隔（秒） |
| `TRANSLATE_MAX_RETRIES` | `3` | 单条评论最大重试次数 |

### 现有配置复用

| 配置 | 说明 |
|------|------|
| `LLM_API_BASE` | OpenAI 兼容 API 地址 |
| `LLM_API_KEY` | API 密钥（为空时翻译线程不启动） |
| `LLM_MODEL` | 翻译模型 |
| `LLM_TRANSLATE_BATCH_SIZE` | 每批翻译条数 |

## 风险及应对

| 风险 | 级别 | 应对 |
|------|------|------|
| 毒丸评论卡死队列 | 高 | translate_retries >= 3 自动标记 skipped |
| 历史数据雪崩 | 高 | 迁移时历史评论标记 skipped，最新优先翻译 |
| 部分批次成功 | 中 | 逐条 UPDATE，未返回的保持 NULL 下轮重试 |
| SQLite 写竞争 | 低 | WAL 模式，单次 UPDATE <10ms |
| 进程崩溃丢失 | 无 | DB-as-queue 天然恢复 |
| LLM Client 重复创建 | 低 | Worker 初始化时创建一次复用 |
| 空内容浪费 API | 低 | headline+body 都空时直接标记 done |
| 报告翻译统计来源 | 中 | 从 DB 查 translate_status 统计 |
| wake_event 竞态 | 低 | clear() 在 wait() 前，丢失一次 trigger 60s 后自动补上 |
| 无 translate_status 索引 | 中 | 迁移中创建索引，避免全表扫描 |

## 改动文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `server/translator.py` | 新建 | TranslationWorker 守护线程（~120 行） |
| `models.py` | 修改 | 新增 4 列迁移 + 翻译相关查询/更新函数 |
| `server/app.py` | 修改 | 初始化 TranslationWorker，传入 TaskManager |
| `server/task_manager.py` | 修改 | 接收 translator，save_reviews 后 trigger |
| `server/report.py` | 修改 | 移除翻译步骤，query 加中文列，邮件加未翻译提示 |
| `server/mcp/tools.py` | 修改 | 更新 generate_report 描述，新增 trigger_translate / get_translate_status tool |
| `server/mcp/resources.py` | 修改 | SCHEMA_REVIEWS 新增 headline_cn, body_cn, translate_status, translate_retries 列说明 |
| `config.py` | 修改 | 新增 TRANSLATE_INTERVAL / TRANSLATE_MAX_RETRIES |
| `.env.example` | 修改 | 新增 TRANSLATE_INTERVAL / TRANSLATE_MAX_RETRIES 示例 |
| `tests/test_report.py` | 修改 | 移除翻译相关测试（translate_reviews 系列），更新 generate_report 测试 |
| `tests/test_translator.py` | 新建 | TranslationWorker 单元测试（轮询、重试、skipped、trigger） |
| `CLAUDE.md` | 修改 | 更新架构说明、配置表、项目结构（新增 translator.py） |
| `server/openclaw/workspace/TOOLS.md` | 修改 | 新增 trigger_translate / get_translate_status 参数说明，通知模板加翻译进度 |
| `server/openclaw/workspace/skills/daily-scrape-report/SKILL.md` | 修改 | 步骤 2 描述更新，新增可选翻译检查步骤 |
