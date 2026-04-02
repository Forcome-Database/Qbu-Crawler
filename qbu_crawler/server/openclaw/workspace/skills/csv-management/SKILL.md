---
name: csv-management
description: 维护 daily CSV 的写入规则。用于把商品页 URL、分类页 URL 或 SKU 搜索结果加入或更新到定时任务清单。
---

# CSV Management

只处理“加入或更新 daily CSV”的写入操作，不直接替代抓取任务提交。

## 支持站点

- `www.basspro.com`
- `www.meatyourmaker.com`
- `www.waltons.com`
- `waltons.com`

## 这项技能负责什么

负责：

- 判断输入是 URL 还是 SKU
- 确认 ownership
- 判断应写入哪个 CSV
- 新增或更新 CSV 记录
- 给出清晰确认回执

不负责：

- 直接调用 `start_scrape`
- 直接调用 `start_collect`
- 做深度分析
- 代替 daily workflow

## Step 1: 判断输入类型

- 以 `http://` 或 `https://` 开头：按 URL 处理
- 其他输入：按 SKU 处理，先搜索出商品页 URL，再继续流程

如果 SKU 搜索不到商品页，直接告知无法加入，不要猜测。

## Step 2: 确认 ownership

- `ownership` 必须明确为 `own` 或 `competitor`
- 未明确时必须追问
- ownership 未确认前，不写入 CSV

## Step 3: 判断目标 CSV

- 商品详情页 URL
  - 写入 `~/.openclaw/workspace/data/sku-product-details.csv`
- 分类页或列表页 URL
  - 写入 `~/.openclaw/workspace/data/sku-list-source.csv`

## Step 4: 表头与字段规则

- `sku-product-details.csv`
  - `url,ownership,review_limit`
- `sku-list-source.csv`
  - `url,ownership,max_pages,review_limit`

字段语义：

- `max_pages`
  - 仅用于分类页
  - `0` 或留空表示全页
- `review_limit`
  - `0` 或留空表示评论全量
  - 首次成功抓取该 URL 仍然全量
  - 后续再抓取才按上限截断

## Step 5: 写入与更新规则

1. 先检查目标 CSV 是否已存在该 URL
2. 若不存在，新增一行，并补齐默认列
3. 若已存在，只更新用户明确要求修改的字段
4. 如果旧表头缺少新列，先补表头，再保留原有数据
5. 如果 URL 已存在且字段值没变化，明确告知“已存在，无需重复写入”

默认值：

- 商品页：
  - `review_limit=0`
- 分类页：
  - `max_pages=0`
  - `review_limit=0`

## Step 6: 输出确认

成功时明确说明：

- 写入到了哪个 CSV
- `ownership` 是什么
- `max_pages` 的最终值
- `review_limit` 的最终值
- 是新增还是更新

如果 `review_limit > 0`，顺带提醒：

- 首次成功抓取仍然全量
- 之后再次抓取才按该值限制评论

输出要简洁、确定，不要把 CSV 原始行直接抛给用户。

## 禁止事项

- 不要直接调用 `start_scrape` 或 `start_collect`
- 不要把不支持站点的 URL 写入 CSV
- 不要在 `ownership` 未确认时写入
- 不要为补字段而覆盖已有配置
- 不要把 CSV 维护结果伪装成“已开始抓取”
