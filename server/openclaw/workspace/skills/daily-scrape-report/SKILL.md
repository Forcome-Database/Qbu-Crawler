# 每日爬虫任务汇报

由 Heartbeat 检测到任务完成后触发，生成报告、发送邮件并汇报结果。

## 执行步骤

### 1. 汇总任务结果

读取 `~/.openclaw/workspace/state/active-tasks.json`，获取 task_id 列表和 submitted_at。

对每个 task_id 调用 `get_task_status`，记录：
- 成功的产品数（result.products_saved）
- 成功的评论数（result.reviews_saved）
- 失败数（progress.failed）

### 2. 查询新增数据

使用 `execute_sql` 查询本次新增的产品和评论：

产品查询：
```sql
SELECT url, name, sku, price, stock_status, rating, review_count, scraped_at, site, ownership FROM products WHERE scraped_at >= datetime('{submitted_at}') ORDER BY site, ownership
```

评论查询：
```sql
SELECT p.name, r.author, r.headline, r.body, r.rating, r.date_published, r.images, p.ownership FROM reviews r JOIN products p ON r.product_id = p.id WHERE r.scraped_at >= datetime('{submitted_at}') ORDER BY p.name
```

将 `{submitted_at}` 替换为 active-tasks.json 中的值（UTC 格式）。

### 3. 翻译评论

将评论的 headline 和 body 翻译为中文。

翻译规则：
- 每批 30-50 条，使用低端模型
- 指令："将以下英文评论标题和内容翻译为中文，保持原意，简洁自然"
- 翻译结果暂存，不回写数据库
- 翻译失败的条目中文列留空

### 4. 生成 Excel

使用 xlsx 技能创建 `~/.openclaw/workspace/reports/scrape-report-YYYY-MM-DD.xlsx`。

Sheet1 — 产品：
- 产品地址（url）
- 产品名称（name）
- SKU（sku）
- 售价$（price）
- 库存状态（stock_status）
- 综合评分（rating）
- 评分数量（review_count）
- 抓取时间（scraped_at）
- 站点（site）
- 归属（ownership）

Sheet2 — 评论：
- 产品名称（p.name）
- 评论人（author）
- 标题（原文）（headline）
- 内容（原文）（body）
- 标题（中文）（翻译结果）
- 内容（中文）（翻译结果）
- 打分（rating）
- 评论时间（date_published）
- 照片（images URL）

### 5. 发送邮件

从 `~/.openclaw/workspace/config/email-recipients.txt` 读取收件人列表（一行一个邮箱，# 开头为注释）。

使用 himalaya 技能发送邮件：
- 主题：`[Qbu-Crawler] 每日爬虫报告 YYYY-MM-DD`
- 正文：简要统计（新增 N 个产品，N 条评论，自有 N 个，竞品 N 个）
- 附件：Excel 文件（使用绝对路径 `~/.openclaw/workspace/reports/scrape-report-YYYY-MM-DD.xlsx`）

记录邮件发送结果（成功/失败+原因）。

### 6. DingTalk 汇报

输出任务完成通知（参考 TOOLS.md 中的"任务完成通知"格式），包含邮件发送状态。

### 7. 清理状态

将 `~/.openclaw/workspace/state/active-tasks.json` 内容清空为 `{}`。

### 异常处理

- 无新增数据 → Excel 保留表头但数据行为空，仍发送邮件
- 邮件发送失败 → DingTalk 汇报中标注 "❌ 邮件发送失败：{原因}"
- 翻译部分失败 → Excel 中对应中文列留空，不阻断流程
- 所有任务都失败 → 仍执行汇报流程，Excel 为空，DingTalk 列出失败详情
