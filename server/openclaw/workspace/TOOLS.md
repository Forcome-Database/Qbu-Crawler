# 工具参考

## 支持站点

- 🏪 **Bass Pro Shops**（basspro）— `www.basspro.com` — 户外运动装备
- 🥩 **Meat Your Maker**（meatyourmaker）— `www.meatyourmaker.com` — 肉类加工设备

## 工具参数速查

### 任务管理

| 工具 | 必填参数 | 可选参数 |
|------|---------|---------|
| `start_scrape` | urls, ownership | — |
| `start_collect` | category_url, ownership | max_pages（0=全部） |
| `get_task_status` | task_id | — |
| `list_tasks` | — | status, limit |
| `cancel_task` | task_id | — |

### 数据查询

| 工具 | 必填参数 | 可选参数 |
|------|---------|---------|
| `list_products` | — | site, search, min_price, max_price, stock_status, ownership, sort_by, order, limit, offset |
| `get_product_detail` | product_id 或 url 或 sku | — |
| `query_reviews` | — | product_id, sku, site, ownership, min_rating, max_rating, author, keyword, has_images, sort_by, order, limit, offset |
| `get_price_history` | product_id | days（默认30） |
| `get_stats` | — | — |
| `execute_sql` | sql | — |
| `generate_report` | since | send_email（默认 true） |

### 参数说明

- `ownership`：`own`（自有）或 `competitor`（竞品），start_scrape/start_collect 中**必填**
- `min_price`/`max_price`/`min_rating`/`max_rating`：`-1` 表示不限制
- `max_pages`：`0` 表示采集全部页
- `has_images`：字符串 `"true"` 或 `"false"`
- `execute_sql`：仅 SELECT，500 行上限，5 秒超时
- `generate_report`：`since` 为 UTC 时间戳（`YYYY-MM-DDTHH:MM:SS`），`send_email` 字符串 `"true"`/`"false"`

## CSV 文件

- 分类页：`~/.openclaw/workspace/data/sku-list-source.csv`
- 产品页：`~/.openclaw/workspace/data/sku-product-details.csv`
- 格式：`url,ownership`（有表头），一行一条

## 邮件收件人

`~/.openclaw/workspace/config/email-recipients.txt`（一行一个邮箱，`#` 为注释）

## 任务状态文件

`~/.openclaw/workspace/state/active-tasks.json`

---

## 输出格式规范

IMPORTANT: 以下格式规范必须严格遵守，特别是钉钉渠道的限制。

### 基本原则

- **绝不**向用户展示 JSON、SQL、代码或工具名称
- 价格：**$XX.XX** | 评分：**X.X/5** ⭐ | 库存：✅ 有货 / ❌ 缺货
- 任务状态：⏳ 进行中 / ✔️ 完成 / ❌ 失败 / 🚫 已取消
- 给完结果后**主动建议下一步**
- **标题、加粗、列表**用得恰到好处，格式工整

### 钉钉渠道排版（必须遵守）

IMPORTANT: 钉钉不支持 Markdown 表格，会显示为乱码。

**钉钉支持**：标题（# ## ###）、加粗（**粗体**）、列表（- 和 1.）、嵌套列表、引用（>）、链接、分隔线（---）、代码块

**钉钉不支持**：❌ 表格 | ❌ 删除线

**排版规则**：
1. **禁止表格** — 用列表代替
2. **标题分隔板块** — 每个维度用 ### + emoji
3. **加粗关键数据** — 每个要点一行
4. **一段文字不超过 3 行** — 超过就拆成列表

### 产品列表

```
## 🔍 搜索结果：共 **15** 个产品

### 1. Product Name A
- **价格**：$129.99
- **评分**：4.5/5 ⭐（128 条评论）
- **库存**：✅ 有货
- **站点**：Bass Pro Shops
```

### 评分分布

```
## 📊 评分分布（共 573 条）

- ⭐⭐⭐⭐⭐ **5星**：334 条（58.3%）████████████
- ⭐⭐⭐⭐ **4星**：87 条（15.2%）█████
- ⭐⭐⭐ **3星**：36 条（6.3%）██
- ⭐⭐ **2星**：37 条（6.5%）██
- ⭐ **1星**：79 条（13.8%）████
```

### 任务状态

```
## 🚀 任务已启动

- **任务 ID**：xxxxxxxx
- **类型**：产品抓取（3 个产品）
- **状态**：⏳ 等待执行

稍后可以问我"任务进度"查看采集状态。
```

### 任务进度

```
## 📊 任务进度

- **任务 ID**：xxxxxxxx
- **状态**：⏳ 采集中（2/5 完成，1 失败）
- **当前**：正在采集 Product Name...
- **耗时**：2 分 30 秒
- **进度**：▓▓▓▓▓▓░░░░ 40%
```

### 产品详情

```
## 📦 Product Full Name

- **SKU**：ABC-12345
- **价格**：$129.99
- **评分**：4.5/5 ⭐（128 条评论）
- **库存**：✅ 有货
- **站点**：Bass Pro Shops
- **最后更新**：2026-01-15

---

### 💬 最近评论

1. ⭐⭐⭐⭐⭐ **John D.**："Great product!" — 2026-01-10
2. ⭐⭐⭐⭐ **Jane S.**："Good but pricey" — 2026-01-08

---

### 📈 近30天价格

- 01-15：**$129.99** ✅
- 01-10：$139.99 ✅
- 01-05：$129.99 ✅

> 30天价格波动：$129.99 ~ $139.99
```

### 数据总览

```
## 📊 数据总览

- 📦 **产品总数**：245
- 💬 **评论总数**：3,842
- 💰 **平均价格**：$87.50
- ⭐ **平均评分**：4.1/5
- 🕐 **最后采集**：2026-01-15

---

### 站点分布

- 🏪 **Bass Pro Shops**：180 个产品
- 🥩 **Meat Your Maker**：65 个产品

### 产品归属

- 🏠 **自有产品**：N 个
- 🎯 **竞品**：N 个
```

### 差评分析

```
## 🔍 差评分析

### 1. Product Name（42 条差评）

**核心问题：**

- **精度不足**：多条差评反映读数偏差大
- **电源故障**：按钮无法开机，需反复拔插电池

**改良建议：**

- [x] 提升传感器精度并增加校准功能
- [x] 改用弹簧扣式电池盖
```

### 竞品对比

```
## 🏪 Bass Pro Shops vs 🥩 Meat Your Maker

### Bass Pro Shops
- **产品数**：180
- **平均价格**：$67.50
- **平均评分**：4.3/5 ⭐
- **评论总数**：2,841

### Meat Your Maker
- **产品数**：65
- **平均价格**：$142.80
- **平均评分**：3.8/5 ⭐
- **评论总数**：1,001

---

**结论**：Bass Pro 产品更多、均价更低、评分更高。Meat Your Maker 定位高端但评分偏低，建议关注差评原因。
```

### 定时任务启动通知

```
🚀 每日爬虫任务已启动

- **提交时间**：YYYY-MM-DD HH:MM
- **分类采集**：N 个任务
- **产品抓取**：N 个任务（N 个产品）
- **任务 ID**：xxx, yyy

将自动监控任务进度，完成后汇报。
```

### 定时任务完成通知

```
✅ 每日爬虫任务已完成

- **完成时间**：YYYY-MM-DD HH:MM
- **产品抓取**：成功 N，失败 N
- **新增评论**：N 条
- **自有产品**：N 个 | **竞品**：N 个
- **邮件发送**：✅ 已发送至 N 位收件人
- **报告文件**：scrape-report-YYYY-MM-DD.xlsx
```
