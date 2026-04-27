# Changelog

All notable changes to qbu-crawler are documented here.

## v0.4.0 (2026-04-27) — F011 报告系统重构

### 新增
- F011 报告系统重构：4 频道分离（邮件正文 / 附件 HTML / Excel / 内部运维邮件）
- H1 `scrape_quality` 自检 + 内部运维邮件触发（`_evaluate_ops_alert_triggers` P0/P1/P2）
- H6 + H10 差评率分母统一为 ingested-only；核心数据 sheet 输出双分母列
- H11 `risk_score` 5 因子分解输出（neg_rate / severity / evidence / recency / volume）
- H13 `notification_outbox` deadletter 触发 `report_phase` 降级（`full_sent` → `full_sent_local`）
- H14 `improvement_priorities` 拆 `short_title` + `full_action` + `evidence_review_ids`
- H16 `trend_digest` 单主图 + 3 折叠下钻 + ready/medium/low 阈值统一
- H18 接近高风险阈值预警（`near_high_risk` 因子）
- H19 `failure_mode` 9 类 enum 化（迁移 0011 自动回填历史数据）
- H22 `change_digest` 三层金字塔（立即关注 / 趋势变化 / 反向利用）
- §4.1 邮件正文：4 KPI 灯条 + Hero + Top 3 行动 + 自有产品状态 5 行
- §4.2.3 自有产品状态灯（绿/黄/红/灰）替代 risk_score 数字排行
- §4.2.3.1 issue cards Top 3 默认展开 + 4-N 折叠
- §4.2.4 三层金字塔（bootstrap 单卡 / 数据成熟期分层）
- §4.2.5 趋势区从 12 panel → 1 主图 + 3 折叠（Top 3 问题 / 产品评分 / 竞品对标）
- §4.2.6 全景数据 5 个客户端筛选器（归属 / 评分 / 有图 / 近 30 天 / 标签）
- §4.2.6.2 v1.2 特征情感热力图：维度聚合 Top 8 + 每格 top_review hover + 点击下钻
- §4.2.7 v1.2 竞品启示扩展：弱点机会卡 + 雷达 Top 6-8 维度聚合 + 评分分布迁移
- §4.3 Excel 4 sheets 重构（核心数据 / 现在该做什么 / 评论原文 / 竞品启示）
- §4.4 内部运维邮件 `email_data_quality.html.j2` severity 字段
- §5.1 新建 `report_artifacts` 表（snapshot / analytics / xlsx / html_attachment / email_body）
- §5.3 LLM prompt v3 + JSON schema + tone guards + retry + assert_consistency 全字段断言
- v3 `build_fallback_priorities` 规则化兜底（LLM 输出为空时自动生成）

### 修复
- H12 `query_cumulative_data` SELECT 漏失字段
- H15 `date_published` 解析 anchor 不一致
- H17 模板 `row.values()` → `columns` key（不依赖 dict 顺序）
- H20 `build_fallback_priorities` 规则化 stub
- 评论 `analysis_labels_parsed` phantom field 修复（drill-down `top_issues` / `competitor_radar` 正确聚合标签）
- LLM `temporal_pattern` 字段移除（v1.2 卡内调整）

### 撤销
- 12 panel 趋势布局
- 5 sheets Excel（评论 / 产品概览 / 今日变化 / 问题标签 / 趋势数据 → 4 sheets）
- 角色分层 tabs / 角色化 Excel 导出
- 报告中混入工程信号（覆盖率 / 本次入库 N / estimated_dates / backfill_dominant）
- email body legacy `change_digest` 大区块（4 stat cards / 3 change-blocks）
- issue cards `duration_display`（"约 8 年" 误读，改"高频期 YYYY-MM ~ YYYY-MM"）

### 兼容性
- 旧版 `prompt_version=v2` 数据可读（loader 用 `MAX(analyzed_at)` 取最新行，不区分 prompt_version）
- `daily_report_v3_legacy.html.j2` 保留作为 env 切换 fallback（Task 4.6）
- legacy `_duration_display` / `top_actions` / `_chartjs_heatmap_table` 标记 deprecated，下个版本移除
