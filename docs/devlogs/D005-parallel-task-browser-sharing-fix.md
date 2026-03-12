# D005 - 修复并行任务共享浏览器导致数据错位

日期：2026-03-11

## 背景

用户通过 OpenClaw agent 同时提交两个爬虫任务（竞品 + 自有产品），4 个 URL 分别分配到 2 个并行任务中。结果发现 2 个产品的采集数据与 URL 不匹配：

| URL | 预期产品 | 实际采到 |
|-----|---------|---------|
| `.5-hp-dual-grind-grinder-8/1193465` | .5 HP Dual Grind Grinder (#8) | 1 HP Grinder (#22)（另一个任务的产品） |
| `0.75hp-dual-grind-8-throat-attachment/1202187` | 0.75HP Dual Grind #8 Throat Attachment | 40 LB Meat Lug（另一个任务的产品） |

## 根因

**DrissionPage 的 `Chromium()` 默认连接到同一端口（9222）的浏览器进程。**

当 `TaskManager` 的线程池同时执行两个任务时：

1. Task A 创建 `scraper_a` → `Chromium()` → 启动/连接端口 9222 的浏览器
2. Task B 创建 `scraper_b` → `Chromium()` → 连接到**同一个**端口 9222 的浏览器
3. 两个 scraper 的 `self.browser.latest_tab` 指向**同一个标签页**
4. `tab.get(url_a)` 和 `tab.get(url_b)` 在同一标签页上竞争
5. 后执行的导航覆盖前者，先到的任务读到了后到任务的页面数据

时序示例：
```
Task A: tab.get(.5hp-dual-grind)  →  被 Task B 覆盖  →  读到 "1 HP Grinder" 数据
Task B: tab.get(1-hp-grinder)     →  正常加载        →  读到 "1 HP Grinder" 数据 ✓
```

## 修复方案

### 1. `auto_port()` — 根治（`scrapers/base.py` + `scrapers/meatyourmaker.py`）

在所有 `_build_options()` 中添加 `options.auto_port()`，让每个 `Chromium()` 实例自动选择空闲端口，启动独立的浏览器进程。

### 2. `_check_url_match()` — 防御（`scrapers/base.py`）

在 `BaseScraper` 中新增 URL 匹配校验方法，在 `tab.get()` + `wait.ele_displayed()` 之后调用。比较导航后的 `tab.url` 路径与预期 URL 路径，不匹配时抛出 `RuntimeError`，防止错误数据入库。

此检查同时能防御：
- 站点服务端重定向（产品下架跳转到其他产品）
- 浏览器进程意外共享的残余风险

## 影响范围

- `scrapers/base.py` — `auto_port()` + `_check_url_match()`
- `scrapers/basspro.py` — `scrape()` 中调用 `_check_url_match()`
- `scrapers/meatyourmaker.py` — `_build_options()` 加 `auto_port()` + `scrape()` 中调用 `_check_url_match()`

## 经验总结

**DrissionPage 并行使用必须 `auto_port()`**。这是一个容易忽视但后果严重的坑：
- 单线程环境下完全正常
- 多线程环境下默默共享浏览器，不报错，只是数据错位
- 表现为"有些产品数据正确、有些错误"，难以排查
