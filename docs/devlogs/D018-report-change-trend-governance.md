# D018 - 今日变化与变化趋势语义治理

日期：2026-04-23

相关文件：
- `qbu_crawler/server/report.py`
- `qbu_crawler/server/report_analytics.py`
- `qbu_crawler/server/report_common.py`
- `qbu_crawler/server/report_llm.py`
- `qbu_crawler/server/report_snapshot.py`
- `qbu_crawler/server/report_templates/daily_report_v3.html.j2`
- `qbu_crawler/server/report_templates/daily_report_v3.js`
- `qbu_crawler/server/report_templates/daily_report_v3.css`
- `qbu_crawler/server/report_templates/email_full.html.j2`
- `tests/test_report_snapshot.py`
- `tests/test_v3_excel.py`
- `tests/test_metric_semantics.py`
- `tests/test_v3_mode_semantics.py`
- `AGENTS.md`

## 背景

这轮治理不是新增周报或月报，而是把单日报表内部长期混用的“首次建档 / 本次入库 / 业务新近 / 趋势观察”四类语义拆开，并让 HTML、邮件、Excel 只消费同一份归一化 analytics。

改造前的主要问题：

- 首次建档场景会被误写成“今日新增”
- 邮件、HTML、Excel 分别消费 `window`、`cumulative_kpis`、临时重算值，口径不一致
- Excel `产品概览` 里的“采集评论数”用错口径，没有按真实 review 聚合
- `今日变化` 只是空壳 tab，没有稳定输入契约
- 趋势能力只停留在底层数据，缺少面向阅读的固定入口
- 生产 artifact 从 `C:\Users\User\Desktop\QBU\reports` 拷到别的机器后，旧绝对路径容易失效

## 这次定下来的硬规则

- 顶层语义字段固定为 `report_semantics`、`is_bootstrap`、`change_digest`、`trend_digest`
- 顶层 `kpis` 是唯一展示 KPI 来源
- `change_digest` 是 `今日变化` 的唯一输入
- `trend_digest` 是 `变化趋势` 的唯一输入
- `window.reviews_count` 只表示本次 run 实际入库评论数，不能解释成“业务新增”
- `bootstrap` 下必须展示“监控起点 / 首次建档 / 当前截面”，不能出现“今日新增 / 较昨日 / 较上期”
- `fresh_review_count` 固定为近 30 天业务发布时间口径
- `backfill_dominant` 阈值固定为 70%
- 真实生产报告目录以 `C:\Users\User\Desktop\QBU\reports` 为准；本地拷贝路径只作为参考，不得写回为生产真值

## 实现重点

### 1. 今日变化

- 在 `report_snapshot.py` 统一构建 `change_digest`
- 将“本次入库”“新近评论”“历史补采”“问题变化”“产品状态变化”“warning”“empty_state”全部收口到 digest
- HTML、邮件、Excel 都只读取 `change_digest`

### 2. 变化趋势

- 在 `report_analytics.py` 输出 `trend_digest`
- 固定入口为 `周 / 月 / 年` 和 `sentiment / issues / products / competition`
- 维持 `ready / accumulating / degraded` 状态分层，不因为样本不足砍掉入口

### 3. Excel 治理

- analytical workbook 固化为 5 个 sheet：
  - `评论明细`
  - `产品概览`
  - `今日变化`
  - `问题标签`
  - `趋势数据`
- `评论明细` 的“本次新增”列改为双态语义：
  - `bootstrap`：`新近 / 补采`
  - `incremental`：`新增 / 空`
- `产品概览` 的“采集评论数”改为按真实 review 聚合
- `今日变化` sheet 在 `bootstrap` 下展示监控起点说明，在 `incremental` 下展示 digest 摘要、warning 和空态

### 4. 邮件治理

- `email_full.html.j2` 不再直接读 `cumulative_kpis`、`window`、`changes`
- 改为只消费顶层 `kpis` 与 `change_digest`
- `bootstrap` 邮件显示监控起点，不伪造“今日新增”
- `incremental + 无显著变化` 走显式空态

### 5. artifact 路径治理

- `workflow_runs` 中保存 artifact 时优先写可迁移路径
- 读取 previous context 时允许旧绝对路径失效后，按当前 `REPORT_DIR`、数据库同级 `reports/`、同目录回退查找
- 这样生产目录搬迁或本地拷贝分析时，不会因为路径写死导致 previous context 整体失效

## 额外修复

- `report.py` 里后定义生效的 `_generate_analytical_excel()` 存在 aware/naive datetime 比较问题，导致 bootstrap Excel 生成时报错；已统一在生效定义里将 `report_date` 归一为上海时间的 naive datetime
- 清理了 Excel 相关旧 4-sheet 断言与旧“是/否”语义，统一到 5-sheet 和“新增 / 新近 / 补采”契约

## 验证

执行：

```bash
uv run --extra dev python -m pytest tests\test_report_excel.py tests\test_report_integration.py -v -k "test_generate_analytical_excel_has_five_sheets or test_generate_excel_with_analytics_uses_analytical or test_analytical_excel_empty_data_still_has_headers or test_excel_classifies_bootstrap_rows_when_window_ids_absent or test_generate_analytical_excel_creates_file or test_generate_analytical_excel_has_five_sheets" --basetemp .pytest_tmp\task7-green-repro3

uv run --extra dev python -m pytest tests\test_v3_excel.py tests\test_report_excel.py tests\test_report_integration.py tests\test_report_snapshot.py tests\test_v3_modes.py -v -k "excel or email_full_also_renders_three_state" --basetemp .pytest_tmp\task7-regression-wide2

uv run --extra dev python -m pytest tests\test_metric_semantics.py tests\test_v3_mode_semantics.py -v --basetemp .pytest_tmp\task8-red-green
```

结果：

- Excel 主回归通过
- `今日变化` / `变化趋势` / 邮件 stock three-state 回归通过
- 新增的时间口径与模式语义回归通过

## 结论

这次改动的核心不是“多做一个 tab”，而是先把报表语义固定下来：

- `今日变化` 负责本期观测入口
- `变化趋势` 负责跨周期观察入口
- `总览 / 问题诊断 / 产品排行 / 竞品对标 / 全景数据` 继续负责全量当前态

后续继续深化趋势页时，只能在 `trend_digest` 这层增强，不能再让展示层绕过归一化字段各自解释原始数据。
