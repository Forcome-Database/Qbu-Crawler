# D006 — Waltons 采集器开发 & 反爬对抗升级

**日期**：2026-03-14 ~ 2026-03-17
**涉及站点**：waltons.com, basspro.com
**涉及文件**：`scrapers/waltons.py`, `scrapers/base.py`, `scrapers/__init__.py`, `config.py`, `server/task_manager.py`

## 新增 WaltonsScraper

### 站点特征

- 平台：BigCommerce (Stencil)
- 评论系统：TrustSpot / RaveCapture（普通 DOM，无 Shadow DOM）
- 反爬：Cloudflare

### 踩坑记录

#### 1. eager 模式阻止 TrustSpot 初始化

**现象**：`aggregateRating` 和评论数据在 JSON-LD 中找不到。

**原因**：TrustSpot 的 JSON-LD（含 `aggregateRating` 和 `review` 数组）是由 TrustSpot 的 JS 动态注入的，不是 BigCommerce 服务端渲染的。`eager` 模式在 DOM 就绪后立即停止加载，TrustSpot 脚本还没执行。

**解决**：覆盖 `_build_options()`，切换到 `normal` 加载模式。和 meatyourmaker 的 BV 脚本问题一样。

#### 2. TrustSpot 评论和 Q&A 混在同一选择器

**现象**：采集到 200 条"评论"，但其中 95 条正文为空。

**原因**：`.trustspot-widget-review-block` 同时匹配评论（有 `.comment-box`）和 Q&A 问答（有 `.ts-qa-wrapper`）。Q&A 没有 `.comment-box`，所以 body 提取为空。页面显示 "12 Questions, 12 Answers"，但 Q&A 的提问和回答各占一个 block = 24 个空记录。

**解决**：在 JS 提取逻辑开头加过滤：
```javascript
if (!block.querySelector('.comment-box')) return;
if (block.querySelector('.ts-qa-wrapper')) return;
```

#### 3. TrustSpot 翻页无限循环

**现象**：评论翻页卡住不停止，一直循环。

**原因**：TrustSpot 的 `a.next-page` 按钮**永远存在**，翻过最后一页后循环回第一页，不像 Bazaarvoice 的按钮会消失。原代码用 `has_next = false` 作为终止条件，但它永远为 `true`。

**解决**：改用"本页无新增评论"检测翻完——每页提取后按 `(author, body_hash)` 去重，`new_count == 0` 即停止。

#### 4. Cloudflare 拦截 DrissionPage

**现象**：页面返回 "Sorry, you have been blocked"。

**原因**：Cloudflare 检测 `navigator.webdriver` 属性。

**解决**：覆盖 `_build_options()`，添加 `--disable-blink-features=AutomationControlled` + 自定义 User-Agent。

## 反爬对抗升级（全局）

### 基类添加反自动化检测

在 `BaseScraper._build_options()` 中全局添加 `--disable-blink-features=AutomationControlled`，所有采集器受益。

### Chrome 用户数据模式（Akamai 绕过）

**背景**：Bass Pro Shops 使用 Akamai 反爬，检测层次远超 Cloudflare：
- JS 层：`navigator.webdriver`（`--disable-blink-features` 可绕过）
- TLS 层：JA3/JA4 指纹（检测自动化浏览器的 TLS 握手特征）
- CDP 层：检测 Chrome DevTools Protocol 调试端口的存在

**关键发现**：
- 正常 Chrome（无调试端口）→ 访问正常
- Chrome + `--remote-debugging-port`（DrissionPage 必需）→ Akamai 检测到 CDP → 拦截
- 但如果 Chrome 有之前通过 JS challenge 获得的 `_abck` cookie → 即使有 CDP 也能通过

**解决方案**：`CHROME_USER_DATA_PATH` 环境变量，复用正常 Chrome 的用户数据目录：

```python
# config.py
CHROME_USER_DATA_PATH = os.getenv("CHROME_USER_DATA_PATH", "")
```

实现要点：
- `auto_port()` 会覆盖用户数据目录 → 不能用，改用 `set_local_port()`
- DrissionPage 的 `set_user_data_path()` 在大目录（数 GB）下启动超时 → 用 `subprocess.Popen` 预启动 Chrome，轮询等待调试端口就绪
- 固定端口 19222，首次 `Chromium(port)` 失败则启动新 Chrome 进程
- 用户数据模式下禁用浏览器定期重启（保留 cookie/session）

## 即时通知机制（OpenClaw 心跳优化）

### 问题

任务完成后需要等 1~6 分钟才收到钉钉通知（5 分钟心跳轮询 + 1 分钟 cron 延迟）。

### 原因链路

```
任务完成 → 等心跳轮询（0~5min）→ 心跳创建 cron（1min 延迟）→ cron 发通知
```

### 解决方案

1. **服务端主动触发心跳**：`task_manager.py` 在任务完成后 HTTP POST 到 OpenClaw 的 `/hooks/wake`（`mode=now`），即时唤醒心跳
2. **心跳直接发通知**：HEARTBEAT.md 中去掉 `openclaw cron add --at 1m` 中间层，直接在心跳内发送

**改造后**：任务完成 → webhook 触发即时心跳 → 直接发通知 → **~10 秒内收到**

**配置**：
```env
OPENCLAW_HOOK_URL=http://<openclaw-ip>:18789/hooks/wake
OPENCLAW_HOOK_TOKEN=<hooks-token>
```

注意 `hooks.token` 不能和 `gateway.auth.token` 相同（OpenClaw 安全要求）。
