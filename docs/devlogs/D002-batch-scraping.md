# D002 - 批量抓取开发日志

对应需求：[F002](../features/F002-batch-scraping.md) | 计划：[P002](../plans/P002-batch-scraping.md)

## 版本: v0.2.0

### 实现概要

新增分类页自动采集和文件批量读取两种批量抓取方式。

### 踩过的坑

#### 1. 分类页 URL 格式变化

**现象**：`/c/hunting/game-processing/seasonings-cures` 返回 404。

**原因**：Bass Pro Shops 网站 URL 结构重构，旧的 `/c/` 分类路径已失效。

**解决**：使用 `/l/` 格式的列表页 URL（如 `/l/spinning-combos`），从网站导航菜单可获取。

#### 2. DrissionPage 原生方法无法匹配产品卡片

**现象**：`tab.eles('css:a[href*="/shop/en/"]')` + 检查 parent class 含 `ItemDetails` 匹配不到任何产品链接。

**原因**：DrissionPage 获取的元素 class 与浏览器 DevTools 看到的可能不一致（CSS Modules 动态 class 名）。兜底的连字符计数法（`path.count('-') >= 2`）匹配到了导航链接。

**解决**：改用 `tab.run_js()` 在页面上下文中执行 JS 选择器 `[class*="ItemDetails"] a[href]`，与 Chrome DevTools 验证结果一致。

#### 3. 去重逻辑放置位置错误

**现象**：采集 4 页共 38 个链接，去重后只剩 10 个（且全是导航链接）。

**原因**：当 ItemDetails 匹配失败时，兜底方法把每页都存在的导航链接（如 `/shop/en/knife-and-tool-headquarters`）重复采集，去重后只保留这些公共链接。

**解决**：修复产品链接提取后，去重逻辑正常工作。

#### 4. 搜索页 URL 被重定向

**现象**：`/shop/en/search?q=xxx` 和 `/s?q=xxx` 都被重定向到首页。

**发现**：Bass Pro Shops 的搜索功能是 SPA 内部路由，不支持直接 URL 访问。批量采集应使用分类列表页。

### 分类页关键选择器

```
产品卡片容器:  [class*="ItemDetails"]
产品链接:      [class*="ItemDetails"] a[href]
分页导航:      nav.styles_pagerContainer__ULou2
页码按钮:      a.styles_pageButton__4s00q
下一页箭头:    .iconPagerArrowRight（其父级 <a> 可点击）
每页条数切换:  .styles_ResultsPerPageBtn__xPbb8
```

### 分页参数

```
第1页: /l/spinning-combos （无参数）
第2页: /l/spinning-combos?page=2&firstResult=36
第3页: /l/spinning-combos?page=3&firstResult=72
```

默认每页 36 条，可选 72 / 108。
