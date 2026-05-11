# P012 窗口语义重建 · 周一无条件汇报 · 实施计划

- **关联 feature**：[F012](../features/F012-window-semantics-and-weekly-cadence.md)
- **创建日期**：2026-05-11
- **预计工作量**：3.5 ~ 4 人天
- **目标 Release**：`qbu-crawler 0.5.0`

---

## 0. 实施次序总览

```
M1 应急止血（半天）              ← 救 5/15 周报，独立可上线
   └─ FR-4.1 窗口起点收敛守卫
       │
M2 schema + 回填（1 天）          ← 真正解决根因 A
   ├─ reviews/products 加 first_seen_at
   ├─ workflow_runs 加 baseline_logical_date
   ├─ 回填脚本（dry-run + commit 两阶段）
   └─ query_report_data / 各 query 切换字段
       │
M3 周一必发主干化（半天）          ← 解决根因 B
   ├─ EmailDecision.force_send
   ├─ 三种模式处理函数读 force_send
   ├─ 删 report_snapshot.py:1365-1367 补丁
   └─ should_send_quiet_email gate cadence
       │
M4 周报模板（1 天）               ← 解决根因 C
   ├─ weekly_briefing.html.j2
   ├─ 三种数据状态下的渲染分支
   └─ 路由 type=='weekly' → 新模板
       │
M5 兜底告警 + 验收（半天）         ← 收口
   ├─ FR-4.2 灌水告警
   ├─ e2e 验收（AC-1 ~ AC-5）
   └─ 上线 release notes
```

每个 milestone 内部都可以独立提 PR / 发布版本，便于灰度验证。

---

## M1 应急止血（半天 · 优先级 P0）

### 目标
5/15（本周日 / 下周一）那封周报不能再出现"本周新增 ≈ 累计"的换皮内容。在不动 schema 的前提下，加一道窗口起点守卫。

### 任务

**T1.1** `qbu_crawler/server/report_snapshot.py:1013-1051` — `build_windowed_report_snapshot`
- 计算 `data_since` 后，从 DB 读 baseline：
  ```
  baseline = SELECT MIN(logical_date) FROM workflow_runs
             WHERE report_mode='full' AND status='completed'
  ```
- `since = max(data_since, baseline + 1 day)`
- 若 `since >= data_until` → 抛 `WindowCollapsedError`，由调用方在 `workflows.py:full_pending` 分支 catch，强制改走 quiet 模式

**T1.2** `qbu_crawler/server/report_snapshot.py:625-770` — `_scraped_at_in_window`
- 同样应用 baseline 守卫
- 临时改名为 `_window_threshold_dt`，注释里明确"M2 之后会换字段"

**T1.3** `qbu_crawler/server/workflows.py:771-907` — `full_pending` 分支
- 捕获 `WindowCollapsedError` → 把 mode 改成 quiet，给 snapshot 注入 `report_window={"type":"weekly", "label":"本周（窗口收敛）", "days":N, "collapsed":True}`
- 模板临时显示「距离 baseline 不足 7 天，本期改为静默汇报」

**T1.4** 单元测试 `tests/server/test_window_baseline_guard.py`（新建）
- case A：baseline=2026-05-08，logical_date=2026-05-11 → since 收敛到 5/9
- case B：baseline=2026-05-08，logical_date=2026-05-09 → since=5/9，window=[5/9, 5/10) ≤ 0 → 触发 collapse
- case C：无 baseline（首次运行）→ 不应用守卫，行为不变

### 验收
- 5/11 历史 snapshot 喂回去：「本周新增」从 2594 → ≤ 10
- 5/15 模拟 run：「本周新增」反映 5/9 ~ 5/15 真实增量
- 现有 `test_e2e_report_replay.py` 通过

### Release
`qbu-crawler 0.4.x` patch 版本，可在 M2 之前先 `python scripts/publish.py patch` 上线。

---

## M2 schema + 回填（1 天 · 优先级 P1）

### 目标
真正解决根因 A：让"新增/最近 N 天"按"评论首次出现时间"统计，与 bootstrap **以及未来扩监控范围**的入库批次解耦。

### 任务

**T2.0（前置审计·半小时）** 全量 grep `scraped_at` 引用并打标
- 命令：`Grep "scraped_at" qbu_crawler/ tests/ -n`
- 输出 markdown 表 `docs/devlogs/D012-scraped-at-audit.md`：列出每处 `scraped_at` 引用 + 标注分类（"业务窗口（要改）"/"技术运维（不改）"/"排序无关（不改）"/"DDL 不动"）
- 分类依据 = F012 §3.3 字段语义分工矩阵
- 所有"业务窗口（要改）"项必须出现在 T2.4 切换清单里；如有遗漏 → 补到 T2.4
- 测试 fixture 同样输出（含 `tests/` 下的依赖），供 T2.5 实施时逐项迁移

**T2.1** `qbu_crawler/models.py` — schema 演进
- `_init_db` 新增列定义：
  - `reviews.first_seen_at TIMESTAMP DEFAULT NULL`
  - `products.first_seen_at TIMESTAMP DEFAULT NULL`
  - `workflow_runs.baseline_logical_date DATE DEFAULT NULL`
- 在迁移段（参考既有 `ALTER TABLE reviews ADD COLUMN scraped_at` 模式）追加幂等 ALTER

**T2.2** `qbu_crawler/models.py` — INSERT 路径写入（**per-product 基线**）

T2.2.0 前置审计：实际跑下 grep，确认 reviews 去重路径是 `INSERT OR IGNORE` / `ON CONFLICT DO UPDATE` / 还是 SELECT-then-INSERT，三种实现下 first_seen_at 写法不同：

  | 去重实现 | first_seen_at 写法 |
  |---|---|
  | `INSERT OR IGNORE` | INSERT 列表加 first_seen_at 即可，IGNORE 自动跳过冲突行 |
  | `ON CONFLICT(...) DO UPDATE SET col1=..., col2=...` | SET 子句**显式不写** first_seen_at；既有 images 回填的 SET 列表保持原状 |
  | SELECT-then-INSERT | INSERT 分支写 first_seen_at；UPDATE 分支不动 |

T2.2.1 `upsert_products`：INSERT 分支 `first_seen_at = scraped_at`；UPSERT 分支不写

T2.2.2 reviews INSERT 路径（per-product 基线核心逻辑）：

  ```sql
  -- 伪代码：reviews INSERT 时
  INSERT INTO reviews (..., scraped_at, first_seen_at) VALUES (
    ..., :scraped_at,
    -- per-product 基线：如果 product 是同一 Shanghai 日历日入库，则 NULL
    CASE
      WHEN (SELECT date(first_seen_at, '+8 hours') FROM products WHERE id = :product_id)
         = date(:scraped_at, '+8 hours')
      THEN NULL
      ELSE :scraped_at
    END
  )
  ```

  注意：
  - 同事务内 product 必须先 UPSERT，再 INSERT 其下属 reviews，确保 products.first_seen_at 已可读
  - Shanghai TZ 转换：DB 存 UTC 字符串则用 `+8 hours`；存本地时间字符串则直接 `date(...)`
  - 实施前先实测 `scraped_at` 在生产 DB 的实际格式（带不带 TZ 偏移），写对应转换

**T2.3** 回填脚本 `scripts/backfill_first_seen_at.py`（新建·**per-product 基线**）
- 两阶段：
  - `--dry-run`（默认）：输出统计 + 抽样 5 条，**不写入**
  - `--commit`：执行 UPDATE，输出每张表实际更新行数
- 算法（per-product 基线）：
  ```sql
  -- Step 1：写 workflow_runs.baseline_logical_date（仅供 collapsed 守卫与告警用）
  UPDATE workflow_runs SET baseline_logical_date = (
    SELECT MIN(date(logical_date)) FROM workflow_runs
     WHERE report_mode='full' AND status='completed'
  ) WHERE baseline_logical_date IS NULL;

  -- Step 2：products
  -- 在 BASELINE_DATE_GLOBAL 当天或之前 scrape 过的 product → 视为基线 product
  WITH baseline AS (
    SELECT MIN(date(logical_date)) AS d FROM workflow_runs
     WHERE report_mode='full' AND status='completed'
  )
  UPDATE products SET first_seen_at = NULL
   WHERE date(scraped_at) <= (SELECT d FROM baseline);

  UPDATE products SET first_seen_at = scraped_at
   WHERE first_seen_at IS NULL
     AND date(scraped_at) > (SELECT MIN(date(logical_date)) FROM workflow_runs
                              WHERE report_mode='full' AND status='completed');

  -- Step 3：reviews（per-product 基线，**不**按 reviews.scraped_at 判定）
  UPDATE reviews SET first_seen_at = NULL
   WHERE product_id IN (SELECT id FROM products WHERE first_seen_at IS NULL);

  UPDATE reviews SET first_seen_at = scraped_at
   WHERE first_seen_at IS NULL
     AND product_id IN (SELECT id FROM products WHERE first_seen_at IS NOT NULL);
  ```
- dry-run 输出示例：
  ```
  Baseline date (global, for workflow_runs): 2026-05-08
  ── products ──
    to set NULL: 41 (sample: id=1, site=basspro, sku=ABC, scraped_at=2026-05-08 14:23:11)
    to set scraped_at: 0
  ── reviews (driven by products.first_seen_at IS NULL) ──
    to set NULL: 2592 (sample: id=1, product_id=1, scraped_at=2026-05-08 14:23:11)
    to set scraped_at: 2 (sample: id=2593, product_id=20, scraped_at=2026-05-10 08:11:02)
  ── workflow_runs ──
    baseline_logical_date to set: 4 (all NULL → 2026-05-08)
  Run with --commit to apply.
  ```
- **接受的近似**：bootstrap 当天 product 下属若有真实当日新增评论，会被一并设 NULL。该方案接受这个失真，详见 F012 FR-1.4。

**T2.4** 查询路径切换（按文件分批改 + 显式 negative list）
- **要切换**（业务窗口语义）：
  - `qbu_crawler/server/report.py`
    - `query_report_data(since, until)`：reviews/products WHERE 改 `first_seen_at`
    - `_legacy_query_report_data`：同上
  - `qbu_crawler/server/report_snapshot.py`
    - `_scraped_at_in_window` → 改名 `_first_seen_in_window`，读 `first_seen_at`，NULL 视为 False
    - `build_windowed_report_snapshot`：内部调用同步
  - `qbu_crawler/server/daily_digest.py:104-123`
    - 钉钉摘要的代表评论 sort key 与窗口过滤改 `first_seen_at`，NULL 行不进入候选
  - `qbu_crawler/models.py`
    - `_scope_window_clauses`：alias.scraped_at → alias.first_seen_at
    - `query_reviews` / `get_recent_reviews` / `models.py:1693, 2084` 等 N-days 查询
  - `qbu_crawler/server/mcp/resources.py:102` — 示例 SQL 改成 `first_seen_at`，schema 文档新增字段说明
- **保持不变（negative list）**：
  - `qbu_crawler/server/workflows.py:248-266 _count_pending_translations_for_window` —— 翻译 worker 等待逻辑，必须按 `scraped_at` 算（否则 NULL 行被跳过，bootstrap 报告会全是英文未翻译评论）
  - `qbu_crawler/server/scrape_quality.py summarize_scrape_quality` —— 数据质量分母
  - `qbu_crawler/server/report.py:1538-1598 _query_reviews_with_latest_analysis_for_trend` —— trend 图 fallback
  - `qbu_crawler/server/report.py:723-735` 各 picker 次级 sort key
  - `qbu_crawler/models.py get_product_snapshots*` —— product_snapshots 不动
- **审计规则**：T2.0 输出的 D012-scraped-at-audit.md 中所有"业务窗口（要改）"项必须在本节的"要切换"清单里出现；任何遗漏视为 PR 拒绝条件

**T2.5** 测试
- `tests/test_first_seen_semantics.py`（新建）
  - case A：INSERT 新 product + 5 条 reviews（同 scrape session）→ 5 条 reviews.first_seen_at 全 NULL；products.first_seen_at = scraped_at
  - case B：第二天 scrape 同 product，又来 3 条新 reviews → 3 条 first_seen_at = scraped_at；既有 5 条仍 NULL；product 的 first_seen_at 不变
  - case C：UPSERT 既有 review（更新 body 或回填 images）→ first_seen_at 不变
  - case D：query_report_data(since=baseline+1, until=now) 不返回 baseline 期 reviews
  - case E：cumulative 查询返回全部 reviews（NULL + 非 NULL）
- T2.0 输出的"测试 fixture 待迁移清单"逐项处理；每项迁移后跑相关测试确认绿
- e2e fixture：`tests/server/test_e2e_report_replay.py` 用 5/8 + 5/11 真实 snapshot 回放，断言 AC-3.3 三项硬指标

**T2.6** OpenClaw skill 文档同步
- `qbu_crawler/server/openclaw/workspace/skills/qbu-product-data/SKILL.md`
- `qbu_crawler/server/openclaw/workspace/TOOLS.md`
- `qbu_crawler/server/openclaw/old/workspace/skills/qbu-crawler-analytics/references/sql-playbook.md`
- 把所有"最近 N 天 = `scraped_at >= datetime('now','-N days')`"改成 `first_seen_at`，加注释说明字段含义
- 在 schema 资源 `mcp/resources.py` 新增 `first_seen_at` 列说明（TIMESTAMP DEFAULT NULL，语义 = 评论首次出现时间，NULL = 基线）

### 验收
- AC-1.1 ~ AC-1.4 全部通过
- 在生产 DB 副本上 dry-run 输出符合预期，commit 后 5/11 周报重新生成「本周新增 = 2 条」

### Release
`qbu-crawler 0.5.0-rc1`，先在测试环境跑一周，确认无回归再切生产。

---

## M3 周一必发主干化（半天 · 优先级 P1）

### 目标
把"周一必发"从 quiet 子函数的隐式补丁提到 workflow 主干，删除 `should_send_quiet_email` 在 weekly cadence 下的误用。

### 任务

**T3.1** `qbu_crawler/server/report_cadence.py` — `EmailDecision`
- 新增字段 `force_send: bool`
- `decide_business_email` 计算逻辑：
  - bootstrap 路径 → `force_send=True`
  - cadence=='weekly' 且 today 等于 `REPORT_WEEKLY_EMAIL_WEEKDAY` → `force_send=True`
  - 其他 → `force_send=False`

**T3.2** `qbu_crawler/server/workflows.py:803-807` — 透传 force_send
- 在调用 `generate_report_from_snapshot` 时增加参数 `force_send=decision.force_send`
- `generate_report_from_snapshot` 签名增加 `force_send=False`，向下透传到三种模式处理函数

**T3.3** `qbu_crawler/server/report_snapshot.py`
- `_generate_full_report` 顶部：`if force_send and not send_email: send_email = True`（理论上 full 不会遇到 send_email=False，但保留对称）
- `_generate_change_report` 顶部：同上
- `_generate_quiet_report`：
  - 删掉 1365-1367 行的 weekly 隐式补丁
  - 改为：`if force_send: should_send=True; digest_mode='weekly'`
- `should_send_quiet_email` 函数顶部新增：
  - 读 `config.REPORT_EMAIL_CADENCE`
  - 若 `cadence != 'daily'` → `return True, None, 0`（不再用 daily 频率算法）

**T3.4** 测试
- `tests/server/test_force_send_decision.py`（新建）
  - 周一 + weekly cadence + quiet → email_delivery_status=sent
  - 周二 + weekly cadence + quiet → skipped
  - 周一 + weekly cadence + change → sent
  - daily cadence + quiet 第 4 天 → 按原算法 skip
  - bootstrap → sent

**T3.5** 兜底告警实现（FR-2.4）
- 在 `workflows.py` 周一邮件失败的 catch 分支：
  - 收件人：`config.SCRAPE_QUALITY_ALERT_RECIPIENTS`
  - 主题：`[P0][周报投递失败] {logical_date} (run #{run_id})`
  - dedupe key：`weekly:{logical_date}:email_failure`
  - 正文包含：失败原因 stack trace 摘要（前 500 字符）+ run_log_path
- 通道复用 `_send_data_quality_alert` 的 SMTP 调用
- 测试：`tests/server/test_weekly_email_failure_alert.py`
  - 模拟 weekly_briefing 模板渲染抛 RuntimeError → 收到告警邮件
  - 第二次重试同一 dedupe key → 不再发送

### 验收
- AC-2.1 ~ AC-2.4、AC-4.4 全部通过

---

## M4 周报模板（1 天 · 优先级 P2）

### 目标
让周一邮件无论数据是热闹还是静默，都长成"本周汇报"模样。

### 任务

**T4.1** 新模板 `qbu_crawler/server/report_templates/weekly_briefing.html.j2`
- 复用 `daily_report_v3.html.j2` 的 CSS 与外壳
- 结构：
  ```
  ├ Hero（顶部数字）：本周新增 / 累计
  ├ [可选] 语义迁移 banner（FR-3.4，env REPORT_SHOW_SEMANTIC_MIGRATION_BANNER_UNTIL 控制）
  ├ [可选] collapsed 横幅（FR-4.1，report_window.collapsed=True 时显示）
  ├ 本周净变化（FR-3.1 表格）
  │   ├ 新评论 K 条
  │   ├ 价格变动 K 项
  │   ├ 库存翻牌 N 个
  │   └ 评分波动 M 款
  ├ 累计快照（始终展示）
  │   ├ 健康指数 + 信心度
  │   ├ 好评率 / 差评率
  │   └ Top 风险产品 5 款
  ├ Top VOC 引用（标注本周 / 非本周）
  ├ 翻译进度
  └ 静默提示（仅静默周）
  ```

**T4.2** `qbu_crawler/server/report.py` 渲染函数
- 新增 `render_weekly_briefing(snapshot, analytics, changes=None)`
- 自动判断三种数据状态（active / silent_change / silent_quiet）选择区块显示
- 对 cumulative analytics 做空值兜底（首次运行 cumulative 可能为空）

**T4.3** 路由
- `_send_mode_email("quiet"|"change"|"full", snapshot, ...)` 当 `snapshot.report_window.type == "weekly"` → 改用 `render_weekly_briefing`
- 邮件主题统一改成 `产品评论周报 YYYY-MM-DD — {代表产品} 等 N 个产品`

**T4.4** 模板单元测试
- `tests/server/test_weekly_briefing_template.py`（新建）
  - 三种数据状态下分别渲染，断言关键字段都出现
  - 静默周断言"本周确实静默"提示出现

**T4.5** 视觉回归
- 用 5/8 / 5/11 / 5/15 / 5/22 历史 snapshot 渲染出 4 封邮件，截图人工对比，确认：
  - 5/8 仍然是 bootstrap 模板（无变化）
  - 5/11 / 5/15 / 5/22 走 weekly 模板，标题语气一致

### 验收
- AC-3.1 ~ AC-3.3 全部通过

---

## M5 兜底告警 + 验收（半天 · 优先级 P2）

### 目标
确保任何隐藏遗漏（query 路径漏改、回填遗漏、新型 bootstrap 场景）都能在生产侧立即被发现。

### 任务

**T5.1** `qbu_crawler/server/scrape_quality.py`
- 在 `summarize_scrape_quality` 输出新增字段：
  - `weekly_added`（来自调用方传入）
  - `cumulative_total`
  - `weekly_to_cumulative_ratio`

**T5.2** `qbu_crawler/server/notifier.py:_evaluate_ops_alert_triggers`
- 新增触发：`weekly_to_cumulative_ratio > 0.7` 且 `cumulative_total > 100` → severity=P1，触发运维告警邮件

**T5.3** `_send_data_quality_alert` 模板 `email_data_quality.html.j2`
- 新增段落：「检测到本期窗口评论占累计 X%，可能存在批量入库或 first_seen_at 回填遗漏」

**T5.4** e2e 验收
- 跑 AC-1 ~ AC-5 全部
- 用生产 DB 副本回放 5/8 ~ 5/22 完整时间线，输出 8 封邮件 HTML，人工 review 后归档到 `docs/devlogs/D012-weekly-cadence-replay.md`

**T5.5** Release notes
- 撰写 `docs/devlogs/D012-window-semantics-rebuild.md`：
  - 事件复盘
  - 修复策略
  - schema 变更与回填指引
  - 运维操作 checklist（生产升级前必做：备份 DB → 跑 dry-run → 人工确认 → commit → 重启服务）

### 验收
- AC-4.1 ~ AC-4.2 全部通过
- 生产升级 checklist 经至少一次模拟演练

---

## 上线 checklist（M5 完成后）

1. [ ] 在生产 DB 副本上跑 `python scripts/backfill_first_seen_at.py --dry-run`，输出符合预期
2. [ ] `python scripts/publish.py minor` 发布 0.5.0
3. [ ] **备份生产 DB**（升级前必做）：
   ```bash
   STAMP=$(date +%Y%m%d-%H%M)
   cp "$QBU_DATA_DIR/products.db" "$QBU_DATA_DIR/products.db.bak.$STAMP"
   ls -lh "$QBU_DATA_DIR/products.db.bak.$STAMP"   # 确认大小与原文件一致
   ```
4. [ ] SSH 生产，停服务 → `pip install -U qbu-crawler==0.5.0` → 暂不重启
5. [ ] 在生产 DB 上 dry-run 二次确认：
   ```bash
   python scripts/backfill_first_seen_at.py --dry-run
   ```
   - 输出与第 1 步一致 → 继续；不一致 → 回滚 `pip install qbu-crawler==0.4.x`，从备份恢复 DB
6. [ ] 在生产 DB 上正式回填：
   ```bash
   python scripts/backfill_first_seen_at.py --commit
   ```
7. [ ] [可选] 设置语义迁移 banner 失效日期：
   ```bash
   echo "REPORT_SHOW_SEMANTIC_MIGRATION_BANNER_UNTIL=2026-05-25" >> .env
   ```
8. [ ] 重启服务 `systemctl restart qbu-crawler`
9. [ ] 触发一次手动 run（5/12 ~ 5/14 任一天）→ 验证：
   ```bash
   sqlite3 $QBU_DATA_DIR/products.db \
     "SELECT id, service_version, report_mode, baseline_logical_date,
             email_delivery_status, delivery_last_error
        FROM workflow_runs ORDER BY id DESC LIMIT 3"
   ```
   - `service_version=0.5.0`
   - `baseline_logical_date='2026-05-08'`
10. [ ] 5/15 自动周报发出后，人工 review 邮件正文：
    - 本周新增数字真实（不再是 ≈ 累计）
    - 模板是 weekly_briefing 长相
    - 静默或活跃情况下都有邮件
    - 顶部出现"语义迁移"banner（如配了 FR-3.4）
11. [ ] 一周后回看 `notification_outbox` 与 `workflow_runs.delivery_last_error`，确认无新增异常
12. [ ] 7 天后清理备份：`rm "$QBU_DATA_DIR/products.db.bak.$STAMP"`（确认无回滚需求后）

## 回滚预案

- M1 / M3 / M4 / M5 都是纯代码改动，回滚 = `pip install qbu-crawler==0.4.x`，无数据风险
- M2 schema 变更回滚：
  - 新增的 `first_seen_at` / `baseline_logical_date` 列在 SQLite 下 `ALTER TABLE DROP COLUMN` 受限，建议保留列但回退查询路径到 `scraped_at`
  - 提供 `scripts/rollback_first_seen_at.py`：把所有 `first_seen_at IS NULL` 的行回填为 `scraped_at`，恢复"老语义"行为
