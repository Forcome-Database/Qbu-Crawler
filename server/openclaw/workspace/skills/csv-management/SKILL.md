---
name: csv-management
description: URL/SKU 验证与 CSV 写入技能。当用户提供 URL 或 SKU 需要加入定时任务时使用。验证域名、确认 ownership、写入对应 CSV 文件。
---

# URL/SKU 验证与 CSV 管理

IMPORTANT: 此技能仅处理"加入定时任务"的写入操作。URL 路由判断在 AGENTS.md 中。

## 步骤 1：判断输入类型并验证

- `http://` 或 `https://` 开头 → URL，提取域名匹配支持站点
- 其他 → SKU，用 brave 搜索 `site:basspro.com {SKU}` 和 `site:meatyourmaker.com {SKU}` 找产品页 URL
- SKU 搜索找不到 → 告知用户"无法找到该 SKU 对应的产品页"，**流程结束**

支持站点：`www.basspro.com`、`www.meatyourmaker.com`

## 步骤 2：确认 ownership

IMPORTANT: ownership 必须明确为 `own` 或 `competitor`，不可省略。

- 已指定 → 继续
- 未指定 → 追问："这是自有产品还是竞品？"
- 用户无法回答 → 告知"无法确定归属，暂不加入定时任务"，**流程结束**

## 步骤 3：判断目标 CSV 并写入

- 产品详情页 URL → 写入 `~/.openclaw/workspace/data/sku-product-details.csv`
- 分类页/列表页 URL → 写入 `~/.openclaw/workspace/data/sku-list-source.csv`

判断方式：分类页通常包含 `/c/`、`/l/`、`/shop/en/` 等路径但无具体产品名。

先检查该 URL 是否已存在于目标 CSV 中。已存在 → 告知用户"该 URL 已在定时任务中"，**流程结束**。

不存在 → 追加一行：`{url},{ownership}`。如文件不存在先创建并写表头 `url,ownership`。

写入后告知："已将 {url} 加入定时任务（归属：{ownership}）"

## 非支持站点

不可写入 CSV、不可调用 start_scrape/start_collect、不可写入数据库。可用搜索/浏览器临时获取信息。
