# D003 - 性能优化与稳定性提升

日期：2026-03-08

## 背景

基于 DrissionPage 官方文档的深度调研，对爬虫进行全面优化，提升抓取效率、成功率和稳定性。

## 调研发现

### DrissionPage 高级特性（可直接应用）

| 特性 | 原状态 | 优化价值 |
|------|--------|---------|
| `eager` 加载模式 | 未使用（默认 `normal`） | DOM 就绪即停，不等图片/字体 |
| `no_imgs()` | 未使用 | 减少带宽和加载时间 |
| `set_retry()` | 无重试 | 网络抖动自动恢复 |
| `click(by_js=None)` | 未使用 | 被遮挡自动切 JS 点击 |
| `tab.wait(min, max)` | 无随机延迟 | 降低反爬检测 |

## 实施的优化

### 1. 浏览器配置优化（config.py）

新增配置项：
- `LOAD_MODE = "eager"` — 页面 DOM 就绪即停，不等图片/字体/CSS
- `NO_IMAGES = True` — 禁止加载图片
- `RETRY_TIMES = 3, RETRY_INTERVAL = 2` — 内置网络重试
- `BV_WAIT_TIMEOUT = 10, BV_POLL_INTERVAL = 0.5` — BV 数据等待参数
- `REQUEST_DELAY = (1, 3)` — 随机延迟反爬
- `RESTART_EVERY = 50` — 定期重启浏览器防内存泄漏

### 2. BV 数据等待机制重写（scraper.py）

**问题**：原始代码用 `time.sleep(1)` 循环 5 次轮询 BV summary，但：
- `#bv-jsonld-reviews-data` 比 `#bv-jsonld-bvloader-summary` 加载更晚
- `wait.eles_loaded()` 对动态注入的 `<script>` 标签不可靠
- BV 注入时序不稳定，有时出现有时不出现

**解决方案**：新增 `_wait_for_bv_data()` 方法，用 JS 轮询同时检测 summary 和 reviews-data：
```python
result = tab.run_js(
    "return (document.querySelector('#bv-jsonld-bvloader-summary') ? 1 : 0)"
    " + (document.querySelector('#bv-jsonld-reviews-data') ? 2 : 0);"
)
```
- reviews-data 出现立即停止（不浪费时间）
- summary 出现但 reviews-data 未到，继续等待
- 超时后优雅退出，不影响后续提取

### 3. 分类页等待优化（scraper.py）

- `sleep(3)` → `wait.eles_loaded('[class*="ItemDetails"]')` — 产品列表渲染完再提取
- `click()` → `click(by_js=None)` — 翻页智能点击，被遮挡自动改 JS

### 4. 浏览器资源管理（scraper.py）

- 新增 `_maybe_restart_browser()` — 每 50 个产品重启浏览器释放内存
- 每次请求后随机延迟 1-3 秒 — `tab.wait(1, 3)` 替代固定延迟

### 5. 评论状态区分（main.py）

- `review_count == 0` → 显示"无"
- `review_count > 0 && scraped > 0` → 显示 "N/M 条"
- `review_count > 0 && scraped == 0` → 显示 "0/M 条 (BV未注入详情数据)"

### 6. SKU 正则增强（scraper.py）

`r'SKU[：:\s]*(\d+)'` → `r'SKU[：:\s]*([\w-]+)'`，支持字母+数字混合 SKU

## 踩坑记录

### 踩坑 1：`wait.url_change()` 需要 text 参数

`tab.wait.url_change(timeout=10)` 会报错 `missing 1 required positional argument: 'text'`。翻页时 URL 变化不可预测，应使用 `wait.doc_loaded()` 替代。

### 踩坑 2：共享数据库连接 + `executescript()` 导致 FK 错误

尝试用模块级共享连接优化性能，但 `executescript()` 会改变连接的事务状态，导致后续 INSERT 出现 `FOREIGN KEY constraint failed`。

**结论**：SQLite 使用独立连接（每次操作开关），性能差异可忽略。

### 踩坑 3：每次 scrape 创建/关闭标签页不合理

`new_tab()` + `close()` 模式看似安全但开销大，且关闭标签页后 `latest_tab` 指向可能不确定。用 `latest_tab` 复用同一标签页更高效稳定。

### 踩坑 4：`wait.eles_loaded()` 对动态 script 标签不可靠

`tab.wait.eles_loaded('#bv-jsonld-reviews-data')` 有时检测不到 BV 动态注入的 `<script>` 标签。必须用 `tab.run_js("document.querySelector(...)")` 轮询。

### 踩坑 5：BV reviews-data 注入有阈值

通过 Chrome 浏览器实际调研发现：
- BV 通过 **easyXDM 跨域 iframe** 通信获取评论数据，不走常规 XHR/Fetch
- `#bv-jsonld-reviews-data` 仅为 SEO 目的注入，最多包含 8 条评论
- 评论数极少的产品（约 < 3 条），BV 可能完全不注入 `reviews-data`
- 这是 BV 平台行为，无法从爬虫侧解决

## 效果

| 指标 | 优化前 | 优化后 |
|------|--------|--------|
| 页面加载 | 等所有资源 | DOM 就绪即停 + 禁图片 |
| BV 等待 | 固定 sleep(1)×5 | JS 轮询 0.5s 间隔，最多 10s |
| 网络失败 | 无重试 | 自动重试 3 次 |
| 内存管理 | 无 | 每 50 个产品重启浏览器 |
| 反爬 | 无延迟 | 随机 1-3 秒 |
| 评论抓取 | 只等 summary | 同时等 summary + reviews-data |
| 评论状态 | 不区分 | 区分无评论/成功/BV限制 |
