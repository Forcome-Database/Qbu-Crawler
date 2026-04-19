# D008 · 每日报告数据口径修复与数据质量监控

**时间：** 2026-04-19
**分支：** `feat/P008-report-integrity`
**计划：** `docs/plans/P008-report-data-integrity-fix.md`

## 根因回顾

2026-04-16 与 2026-04-17 两天的 change 邮件连续出现 5+3 条评分/库存"变动"，对照生产 DB 发现 100% 为爬虫当天采集失败（rating=None / stock_status=unknown）被 `detect_snapshot_changes` 误判为业务变动。同时 KPI 区块显示 `N/A` / `—`，也是爬虫层噪音向上游传染的结果。

列清单：
- Bug A：`detect_snapshot_changes` 未过滤 None / "" / "unknown"
- Bug B：`_generate_full_report` 落盘 raw analytics（缺 `health_index` 等 normalize 产物）
- Bug C：change/quiet 邮件模板读 `previous_analytics.kpis`，滞后一天
- Bug D：stock 模板二分映射，`unknown` 被错显为"缺货"
- Bug E：修复已 commit 但生产未部署，`workflow_runs.service_version` 长期落后
- Bug G：字段缺失无监控出口，每日稳定 3-7% 缺失率无告警
- Bug I：`review_count_changes` 半死代码

## 取舍记录

### `_MISSING_SENTINELS = (None, "", "unknown")`

选这三类而不是更激进的模式（例如把负价格、非数字字符也算缺失）是因为：
- 爬虫层返回的"采集失败"目前只有这三种形态
- 业务字段一旦过滤过多会把真实异常（如促销把价格改成 $0）也吞掉
- 下游报告追求"false negative 容忍、false positive 零容忍"

### 为什么 `scrape_quality.py` 再复制一份 sentinel 常量而不共享

- 报告流程（`report_snapshot.py`）与采集质量（`scrape_quality.py`）在语义上是两个独立关注点
- 跨模块共享常量会让读者以为它们的演化绑定；实际两者将来可能分别扩展（比如 stock 加一个 `"geoblocked"` 仅用于质量监控）
- 复制的一行常量维护成本低于引入一个新模块

### 为什么数据质量告警走独立邮件而不是并入业务报告

- 收件人角色不同：业务变动 → 运营；数据质量 → 运维/爬虫作者
- 频率可能不同：业务日报 vs 异常时随时告警
- 合并会让"评分变动 None → 5.0"这类噪音继续污染业务侧阅读

## 修复验证

- 测试：600 passed（从 591 增长，新增 9 条回归）
- 端到端：回放 run-4 snapshot（4/16 当天数据），`generate_report_from_snapshot` 返回 `mode="quiet"`（原为 change 并带 5 条假变动）
- 部署守护：`scripts/publish.py` 末尾加部署提醒 + `CLAUDE.md` 发布自检段

## 留给后续的 P2/P3

- `high_risk_count` 绝对阈值改百分位（K）
- `snapshot_hash` 覆盖 cumulative（L）
- 爬虫层显式三态 `(value, confidence)` 替代 None 混用

## Commit chain

- `18deff8` Bug A+I（护栏 + 清理死代码）
- `07cd20c` Bug B（full report 写 pre_normalized）
- `8f2153f` Task 2 hardening（label_code 匹配）
- `62a6d6e` Bug C（change/quiet 邮件 KPI 源）
- `2365ea7` Task 3 follow-up（quiet 模板 + 测试覆盖）
- `43b4764` Bug D（stock 三态）
- `7d4dc4a` Task 4 follow-up（email_full 同步）
- `8fad8fe` Task 5 文档
- `732b522` Bug G（数据质量监控 + 告警邮件）
- `d8ac89d` Task 6 hardening（幂等 + 公共 API + 集成测试）
- `<本次>` Task 7（部署守护 + devlog）
