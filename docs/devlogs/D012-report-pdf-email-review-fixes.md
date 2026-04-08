# D012 — 日报 PDF 与邮件评审修正

## 背景

根据《日报PDF与邮件功能评审报告》回看日报全链路，逐条核对 `report.py`、`report_pdf.py`、`report_analytics.py`、`workflows.py` 和模板实现，确认哪些问题真实存在，哪些建议值得现在采纳。

## 本次采纳

### 1. 邮件发送稳健性

- `send_email()` 增加 3 次重试
- SMTP 连接改为 `finally` 关闭，避免异常时残留连接
- 附件文件名改为 RFC 2231 编码，中文文件名不再乱码

### 2. 日报时间窗口径

- `_report_ts()` 改为先转上海时区再去掉 tzinfo
- `workflows._report_db_ts()` 同步修正
- 只修复“有 `until` 的日报窗口查询”，保留旧 `generate_report()` 无界查询语义，避免改坏 legacy 链路

### 3. 邮件与 PDF 统一 analytics 规范化

- 抽出 `normalize_deep_report_analytics()`
- 邮件正文和 PDF 共用同一套标签展示、证据编号、fallback copy 和 KPI 衍生字段
- 新增 `negative_review_rows`、`negative_review_rate_display`、`translation_completion_rate_display`

### 4. 邮件正文收敛

- 正文改为“基线/增量说明 + 今日要点 + 覆盖摘要 + 附件说明”
- 删除大段章节化正文，把详细分析下沉到 PDF
- 保留基线提示和关键 bullet，兼容现有快照语义

### 5. PDF 可读性和稳定性

- 首页 KPI 改为：产品数 / 新增评论 / 差评数 / 差评率
- 证据图片改为预下载后内联 data URI，避免 PDF 远程破图
- `generate_pdf_report()` 中 `browser.close()` 放进 `finally`

## 本次不采纳

### 1. 生成与投递彻底拆阶段

当前 workflow 已能保留已生成产物，并在 full report 失败时进入 `needs_attention`。彻底拆成独立阶段会影响状态机和重试语义，这轮不做结构性改动。

### 2. 增量 delta、数据质量预检、机会窗口交叉比对

这些建议方向成立，但都属于产品能力扩展，不是这轮 PDF/邮件质量修正。先不在本次评审修复里混入新分析逻辑。

### 3. BCC 策略

这是投递策略决策，不是代码层面的确定性 bug，需要业务侧明确收件人暴露策略后再改。

## 验证

执行：

```bash
uv run python -m py_compile qbu_crawler/server/report.py qbu_crawler/server/report_pdf.py qbu_crawler/server/report_analytics.py qbu_crawler/server/workflows.py
uv run pytest tests/test_report.py tests/test_report_pdf.py tests/test_report_snapshot.py tests/test_workflows.py -q
uv run pytest tests/test_report_analytics.py tests/test_metric_semantics.py -q
```

结果：

- `py_compile` 通过
- `81 passed`
- `10 passed`
