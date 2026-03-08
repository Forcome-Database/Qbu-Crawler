# P002 - 批量抓取实施计划

对应需求：[F002](../features/F002-batch-scraping.md)

## 实施步骤

### Step 1: main.py 支持多种输入模式
- `-f <文件路径>` — 从文件读取 URL
- `-c <分类页URL> [最大页数]` — 分类页自动采集
- 直接传入多个 URL

### Step 2: scraper.py 新增 collect_product_urls 方法
- 打开分类页，等待产品列表渲染
- 通过 JS 从 `[class*="ItemDetails"] a` 提取产品链接
- 点击下一页箭头翻页，循环采集
- 去重后返回 URL 列表

### Step 3: 采集完成后调用已有的 scrape_urls 逐个抓取

## 页面分析过程

通过 Chrome 浏览器实际分析分类页结构（详见 [D002](../devlogs/D002-batch-scraping.md)）。
