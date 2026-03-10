# URL/SKU 验证与 CSV 管理

当用户提供产品 URL、分类页 URL 或 SKU 时，验证后写入定时任务 CSV。

## 支持站点

- `www.basspro.com` → basspro
- `www.meatyourmaker.com` → meatyourmaker

## 处理流程

### 1. 判断输入类型

- 以 `http://` 或 `https://` 开头 → URL
- 其他 → 视为 SKU

### 2. URL 验证（仅域名匹配）

提取 URL 的域名部分，与支持站点列表匹配。

- 匹配 → 继续下一步
- 不匹配 → 告知用户："该站点（{域名}）不在定时任务支持范围内。我可以用搜索技能帮你获取相关信息，但无法加入定时任务。"

### 3. SKU → URL 转换

如果输入是 SKU：

1. 用 brave 搜索 `site:basspro.com {SKU}` 和 `site:meatyourmaker.com {SKU}`
2. 从搜索结果中找到产品详情页 URL
3. 找不到 → 尝试 firecrawl
4. 仍然找不到 → 告知用户"无法找到该 SKU 对应的产品页"，不写入 CSV

### 4. 确认 ownership

检查用户是否已指定产品归属（自有/竞品）。

- 已指定 → 继续
- 未指定 → 追问："这是自有产品还是竞品？请告知以便正确分类。"
- 用户无法回答 → 告知"无法确定归属，暂不加入定时任务"，不写入 CSV

### 5. 判断目标 CSV

- 产品详情页 URL（含具体产品路径）→ 写入 `~/.openclaw/workspace/data/sku-product-details.csv`
- 分类页/列表页 URL → 写入 `~/.openclaw/workspace/data/sku-list-source.csv`

判断方式：由 agent 根据 URL 结构判断。分类页通常包含 `/c/`、`/l/`、`/shop/en/` 等路径但无具体产品名。

### 6. 写入 CSV

追加一行到对应 CSV 文件：`{url},{ownership}`

如果文件不存在，先创建并写入表头 `url,ownership`。

写入后告知用户："已将 {url} 加入定时任务（归属：{ownership}）"。

## 非支持站点处理

用户要求获取非支持站点的产品信息时：
- 可以用 brave 搜索或浏览器技能获取信息并返回给用户
- 不调用 start_scrape / start_collect
- 不写入 CSV
- 不写入数据库
