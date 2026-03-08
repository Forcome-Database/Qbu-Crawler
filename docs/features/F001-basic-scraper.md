# F001 - Bass Pro Shops 产品详情页爬虫

## 需求描述

抓取 Bass Pro Shops 产品详情页的关键数据并存储到 SQLite。

## 目标数据字段

| 字段 | 说明 | 必选 |
|------|------|------|
| 商品名称 | 产品标题 | 是 |
| SKU | 产品编号 | 是 |
| 价格 | 当前售价（USD） | 是 |
| 库存状态 | in_stock / out_of_stock / unknown | 是 |
| 评论数量 | 用户评论总数 | 否 |
| 评分 | 平均评分（1-5） | 否 |
| 评论内容 | 评论详情（作者、标题、正文、评分、日期） | 否 |
| 销售数量 | 页面不展示此数据，无法获取 | - |

## 输入

- 一个或多个 Bass Pro Shops 产品详情页 URL
- URL 格式：`https://www.basspro.com/p/{product-slug}` 或 `https://www.basspro.com/shop/en/{product-slug}`

## 输出

- SQLite 数据库（`data/products.db`）
- 两张表：`products`（产品基础信息）、`reviews`（评论详情）
- 终端打印抓取摘要

## 约束

- 网站有反爬保护（直接 HTTP 请求返回 403），必须使用浏览器自动化
- 使用 DrissionPage 库
- 数据存储使用 Python 内置 sqlite3，不引入 ORM
