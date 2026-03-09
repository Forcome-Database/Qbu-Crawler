# D002 - 多站点架构重构 + MeatYourMaker 集成

**日期**: 2026-03-09

## 概述

将单站点 Bass Pro Shops 爬虫重构为多站点框架，并集成 meatyourmaker.com 作为第二个站点。

## 架构决策

- **方案**：轻量继承 + 独立实现（BaseScraper 管浏览器，子类各自实现）
- **原则**：可扩展性、便利性 > 复用
- **BV 评论逻辑不共用**：两站点 BV 版本和行为差异大（Load More vs 翻页），各自内联

## 关键踩坑记录

### 1. eager 模式导致 BV 不初始化

**现象**：meatyourmaker 页面 BV 脚本存在但 `.bv_main_container` 永远不出现，评分和评论全部为 None。

**排查**：
- Chrome 浏览器正常 → DrissionPage 问题
- `normal` 模式正常，`eager` 模式失败
- 同一 `eager` 模式下 basspro 正常

**根因**：meatyourmaker 使用 SFCC/Demandware 平台，BV 脚本依赖的某些资源在 `eager` 模式下未加载完就被中断。

**修复**：MeatYourMakerScraper 覆盖 `_build_options()` 使用 `normal` 模式。

### 2. BV 需展开 Reviews 后才加载

**现象**：即使用 `normal` 模式，等待 20 秒 BV 仍未加载。

**根因**：meatyourmaker 的 BV 组件在 Reviews toggler 展开后才初始化（basspro 不需要展开）。

**修复**：`scrape()` 中先 `_click_reviews_tab()` 再 `_wait_for_bv_data()`。

### 3. toggler 点击静默失败

**现象**：分类页批量抓取时，部分产品评分/评论为 None。

**根因**：`_click_reviews_tab` 的 JS 在 toggler 未渲染时执行，`querySelectorAll` 找不到元素，无报错。

**修复**：改为轮询等待 toggler 出现（最多 10 秒）再点击。

### 4. lazy image 同步滚动无效

**现象**：网站显示 13 条评论有图片，爬虫只提取到 3 条。

**根因**：`forEach + scrollIntoView` 同步执行，每个 section 在视口中停留时间为 0，`loading="lazy"` 图片来不及触发。

**修复**：Python 循环逐个 section 滚动 + `time.sleep(0.3)` 延时。

### 5. 增量去重丢弃图片数据

**现象**：提取到 13 条图片但落库只有 3 条。

**根因**：首次抓取时图片滚动不充分，reviews 以 `images=NULL` 入库。修复滚动后再次抓取，`INSERT` 因唯一约束被跳过，新图片数据丢弃。

**修复**：`save_reviews` 在 `IntegrityError` 时检查是否有新图片，有则 `UPDATE images` 回填。

### 6. 库存检测逻辑反了

**现象**：产品实际 In Stock 显示为 out_of_stock。

**根因**：meatyourmaker 用两个互斥 div（`.availability-msg` 和 `.not-available-div`）显示库存状态，只检查一个的 `display` 不够。

**修复**：同时检查两个 div 的可见性。

## 最终验证结果

| 测试项 | 结果 |
|--------|------|
| 10" Meat Slicer 产品数据 | 名称/SKU/价格/库存/评分 全部正确 |
| 10" Meat Slicer 评论 | 93/189 条，13 条有图片（与网站一致） |
| 分类页采集 (meat-slicers) | 4 个产品全部成功 |
| 数据库 site 字段 | basspro/meatyourmaker 正确区分 |
| 图片入库 | 13 条全部有 MinIO URL |
