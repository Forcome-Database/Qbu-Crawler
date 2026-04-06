# D013 — 日报 PDF 与邮件重设计

> 日期：2026-04-06
> 分支：feature/report-redesign-v2

## 改动概述

将日报 PDF 从 11 页压缩到约 5 页，信息密度提升 2 倍。同时升级邮件系统支持 HTML 富文本。

## 主要改动

### PDF 模板重设计
- **流式排版**：去掉 `min-height:274mm` 和 `break-after:page`，内容自然流入
- **证据内嵌**：10 条证据不再独占 6 页附录，改为缩略图（100x80px）内嵌到问题簇卡片中
- **问题簇事实化**：移除"可能与...有关"式空泛建议，改为纯事实呈现（差评数 + 涉及产品数 + 时间线 + 中英双语评论）
- **issue-grid 改 block**：Chromium `break-inside:avoid` 在 grid 子项中不可靠，改为 block 纵向堆叠

### 数据层增强
- `_cluster_summary_items` 补充 `affected_product_count`、`first_seen`/`last_seen` 时间线、英文原文
- `_risk_products` 补充 `total_reviews`（差评率的分母）
- 新增 `_competitor_gap_analysis`：找出"竞品被夸但我们被骂"的交集主题

### Hero 页数据化
- `_generate_hero_headline`：主标题从静态模板改为数据驱动（含环比趋势语言）
- `_compute_alert_level`：三档行动信号灯（红/黄/绿）
- `_humanize_bullets`：3 条自然语言结论（含差评率、delta、gap analysis 对比）

### KPI Delta
- `models.get_previous_completed_run()`：查询前一次 completed run
- `_load_previous_analytics` + `_compute_kpi_deltas`：对比前日 KPI

### 邮件升级
- 纯文本从 15 行数据罗列精简为 6 行人话
- 新增 HTML 邮件模板（table 布局、KPI 卡片、TOP3 风险表格）
- `send_email` 支持 `body_html`（MIMEMultipart alternative）
- 动态主题行含 alert level 前缀
- BCC 配置选项

### 图表改进
- 所有条形图加数据标签
- Y 轴标签视觉宽度感知截断（CJK=2, ASCII=1）
- 问题簇图表按严重度分色（high=#6b3328, medium=#b7633f, low=#a89070）
- 风险矩阵散点图（数据 >= 6 个产品时启用）

### PDF 渲染
- `prefer_css_page_size=False` + `displayHeaderFooter`（float 布局页眉页脚）
- 图片 Pillow 缩放（300x240, JPEG quality=75）防止 PDF 体积暴涨

### 代码重构
- `report_common.py`：从 report.py 提取共享常量和 normalize 函数
- 时区处理改用 `ZoneInfo("Asia/Shanghai")`

## 踩坑经验

1. **Playwright `prefer_css_page_size=True` 与 `margin` 参数互斥**：当 `prefer_css_page_size=True` 时，Python 侧传入的 margin 被忽略，由 CSS `@page` 控制。需设为 False 才能从 Python 侧控制 margin。

2. **Playwright headerTemplate 中 flex 宽度计算不准**：改用 `float:left`/`float:right` 更可靠。

3. **Chromium `break-inside:avoid` 在 grid/flex 子项中是已知 bug**：默认使用 block 布局作为安全方案。

4. **Windows 上 `ZoneInfo` 需要 `tzdata` 包**：Windows 不自带 IANA 时区数据，需要在 pyproject.toml 中加 `tzdata>=2024.1; sys_platform == 'win32'`。

5. **图片 base64 内嵌不缩放会导致 PDF 体积暴涨**：手机照片 3000x2000 直接编码可达数 MB，必须用 Pillow 先缩放到 300x240。

## 文件清单

| 文件 | 操作 |
|------|------|
| `qbu_crawler/server/report_common.py` | 新建 |
| `qbu_crawler/server/report_templates/daily_report_email.html.j2` | 新建 |
| `tests/test_report_common.py` | 新建 |
| `qbu_crawler/server/report_templates/daily_report.css` | 修改 |
| `qbu_crawler/server/report_templates/daily_report.html.j2` | 修改 |
| `qbu_crawler/server/report_templates/daily_report_email_body.txt.j2` | 修改 |
| `qbu_crawler/server/report_pdf.py` | 修改 |
| `qbu_crawler/server/report.py` | 修改 |
| `qbu_crawler/server/report_analytics.py` | 修改 |
| `qbu_crawler/server/report_snapshot.py` | 修改 |
| `qbu_crawler/models.py` | 修改 |
| `qbu_crawler/config.py` | 修改 |
| `pyproject.toml` | 修改 |
| `qbu_crawler/server/report_templates/daily_report_email_subject.txt.j2` | 删除 |
