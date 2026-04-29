# D020 测试6日报报告问题修复

- 日期：2026-04-27
- 范围：日报 full report 的数据契约、LLM 断言、fallback 文案、附件 HTML 全景数据、竞品启示结构

## 根因

1. `scrape_quality` 依赖 `products[].ingested_count`，但 snapshot 没有写入该字段，导致实际 594 条评论入库仍被判定为 8/8 zero scrape。
2. `TranslationWorker` 仍以 `v2` prompt 保存 LLM 自由文本 `failure_mode`，没有进入 9 类 enum 分类链路。
3. LLM 数字断言只收集比例原值，未收集百分比形态；同时会把产品编号 `#8` 当成指标数字。
4. fallback priorities 在 label 缺少 display 时直接暴露英文 code，并把“规则降级 / LLM 失败”文案暴露到用户报告。
5. 全景数据行使用 `data-rating`，被星级初始化的全局 `[data-rating]` 选择器命中，浏览器渲染时整行内容被星级文本覆盖。
6. 热力图点击只应用标签筛选，没有应用产品筛选。
7. `benchmark_examples` 仍是扁平 list，未按产品形态 / 营销话术 / 服务模式三类输出。

## 修复

- 在 `freeze_report_snapshot()` 中按 snapshot reviews 回填 `products[].ingested_count`。
- `TranslationWorker` 升级为 `prompt_version=v3`，保存前用 `classify_failure_mode()` 归类，原文写入 `failure_mode_raw`。
- LLM 数字断言同时登记比例和百分比形态，并跳过 `#8` 这类产品编号。
- fallback priorities 统一使用中文 label 映射，用户侧文案改为可执行建议，不暴露工程降级状态。
- 全景表格行改用 `data-rating-value`，评分单元格独立渲染星级 `<span data-rating>`。
- 增加产品筛选器，热力图点击同时应用 `product + label`。
- `benchmark_examples` 改为 `{product_design, marketing_message, service_model}` 三类结构，HTML / Excel 兼容消费。
- 用户产物文案统一为“基线样本 / 历史评论池 / 近30天样本”，移除“本次入库 / 历史补采”工程口径。

## 验证

- `uv run pytest -q`：893 passed, 3 skipped。
- 用当前代码重渲染测试6 HTML 后，Chrome 验证：
  - 全景数据 594 行，首行保留 6 个 `td`。
  - 点击热力图格子后同时设置标签筛选和产品筛选。
- 用测试6 snapshot 复算采集质量：
  - `zero_scrape_count=0`
  - `scrape_completeness_ratio=0.675`
  - `low_coverage_skus=['1159178', '1193465', '2834842']`

## 明确未处理

- Excel 内嵌图片不压缩，按用户要求忽略文件大小超限。
- outbox 401 / deadletter 不修复，按用户说明属于生产环境 token 配置错误。
