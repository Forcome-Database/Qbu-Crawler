# D014 — Bass Pro Chrome 僵尸进程与启动路径修复

> 日期：2026-04-20
> 相关文件：`qbu_crawler/scrapers/base.py`, `qbu_crawler/server/task_manager.py`

## 问题起源

生产环境 2026-04-20 daily run 日志显示，13 个 basspro 产品全部失败：
- 首单：`list index out of range`（只有 14ms 即抛，远快于任何网络请求）
- 后续 12 单：`HTTPConnection(host='127.0.0.1', port=19222): Connection refused`

同一 run 里 walton's / meatyourmaker 有部分成功，但报告 snapshot 只收到 7 个历史产品的 56 条评论（全部是之前某次跑进库的，今天并没刷新）。

## 根因分析

### Bug 1：`_cleanup_tabs` 的 tab 关闭逻辑把 page target 全清空

`scrapers/base.py` 里原写法：
```python
tabs = browser.get_tabs()          # 返回 MixTab 对象列表
for tab_id in tabs[:-1]:
    try:
        tab = browser.get_tab(tab_id)  # 把 MixTab 对象塞进期望 str/int 的参数
        tab.close()
    except Exception:
        pass
logger.info(f"[清理] 关闭 {len(tabs) - 1} 个多余标签")  # 无脑按 len 打印
```

问题：
1. `get_tabs()` 返回的就是可直接 `.close()` 的 MixTab 对象，多此一举的 `browser.get_tab(obj)` 二次查询行为未定义，可能把所有 page target 都关掉
2. 日志骗人：只是按 `len(tabs)-1` 计数，不代表真关了这么多
3. 清完没有校验

当所有 page target 都被关掉，`browser.latest_tab` 内部走 `self.tab_ids[0]`（DrissionPage `_base/chromium.py:181`），空列表 → `IndexError: list index out of range`。basspro `_warm_up` 第一行 `tab = self.browser.latest_tab` 就炸。

### Bug 2：Chrome 僵尸进程 + SingletonLock 阻断新实例启动

日志显示首单失败后，port 19222 变成 Connection refused。两种机制叠加：
1. Chrome 进程异常退出但端口监听残留（CDP 半死僵尸）
2. 用户数据目录 (`CHROME_USER_DATA_PATH`) 下 `SingletonLock` 还在，Chrome 再次启动时会把命令 IPC 给"锁持有者"后自己退出

此时 `_launch_with_user_data` 里的 subprocess.Popen 实际没把新 Chrome 成功拉起来，retry 循环里 `Chromium(19222)` 连到的还是原来那个僵尸。

### Bug 3：`_kill_user_data_chrome` 的 netstat 解析不兼容 Windows 11 新版

原写法：
```python
if parts[-2] == 'LISTENING':
    pid = parts[-1]
```

但 Windows 11 24H2 的 `netstat -ano` 输出多了一列 `Offload State`（InHost/Offloaded），变成：
```
TCP  127.0.0.1:19222  0.0.0.0:0  LISTENING  12345  InHost
```
此时 `parts[-2]` 是 PID 而不是 'LISTENING'，整个分支 fall-through，兜底 taskkill 从未触发。

### Bug 4：task_manager 的 URL 级失败不销毁 scraper

`_run_scrape` / `_run_collect` 同站点复用 scraper 实例到任务结束；单个 URL 失败（哪怕 Chrome 已死）也不 close、不重建，导致第一单炸完之后剩余 12 单全部走同一个已死 browser，连锁全挂。

### Bug 5：错误日志丢了 traceback

```python
logger.error(f"[Task {task_id}] Failed {url}: {e}")
```
只记了异常文本，没 `exc_info=True`。生产上这次就是因为栈丢了，只能靠 14ms 间隔推理。

## 修复方案

### `_cleanup_tabs` 重写
用 MixTab 对象自己的 `.close()`，按实际关闭数计数：
```python
for tab in tabs[:-1]:
    try:
        tab.close()
        closed += 1
    except Exception:
        pass
logger.info(f"[清理] 关闭 {closed} 个多余标签（共 {len(tabs)} 个）")
```

### 健康探测 + 僵尸识别
新增 `_probe_browser_alive`：`new_tab('about:blank')` + `latest_tab.url` 双重验证 CDP 真能干活。`_launch_with_user_data` 的"复用旧 Chrome"分支探测失败就强杀 + fall through 到 subprocess 启动分支；subprocess 的 retry 循环也加探测，防止 page target 未就绪时返回半死浏览器。

### 强杀逻辑健壮化
- 新增 `_find_pids_on_port`：按 `LISTENING` 关键字定位 PID、本地地址严格以 `:{port}` 结尾，兼容带 Offload State 列的新版 netstat
- `_kill_user_data_chrome` 5 轮 poll + `taskkill /F /T` 杀进程树（Chrome 有大量子进程）
- 新增 `_clean_singleton_locks`：Popen 前清理 `SingletonLock`/`SingletonCookie`/`SingletonSocket`，避免"锁持有者已死但锁还在"困局

### 防雪崩
`_run_scrape` / `_run_collect` 的 except 块新增：
```python
if scraper:
    try: scraper.close()
    except Exception: pass
    scraper = None
```
下次迭代通过 `scraper is None` 分支自动重建。`_run_collect` 的 try 块补 `if scraper is None: scraper = get_scraper(url)` 重建分支。

### 可观测性
两处 `logger.error` 加 `exc_info=True`。

### close 端强化
`BaseScraper.close()` 在用户数据模式下追加 `_kill_user_data_chrome`，保证下次启动看不到僵尸。DrissionPage 对 attach 进来的 Chrome 只发 CDP close，不保证真正终止进程。

## 关键约束

**本地用户数据模式必须保留**——basspro 用 Akamai，`_abck` cookie 存在 `CHROME_USER_DATA_PATH/Default/Cookies` SQLite 里，新 Chrome 进程读同一目录就能复用，无需每次挑战。所有修复都只动进程生命周期和 tab 管理，`--user-data-dir` + `--profile-directory=Default` 启动参数完全不变。

## 验证

冒烟测试 `uv run python main.py https://www.basspro.com/p/igloo-trailmate-50-quart-cooler`：
- 第 1 次：检测到僵尸 → 重启 → 成功抓到 31/61 条评论
- 第 2、3 次（初版修复）：subprocess 启动的 Chrome 返回时 page target 未就绪 → IndexError → 追加 subprocess 路径的健康探测
- 第 4 次（加 netstat 修复）：子进程树强杀 + SingletonLock 清理 → 首页 Akamai 秒过 → 成功

`chrome://version` 核对 `个人资料路径` 确认确实用的本地 Chrome profile：
```
C:\Users\leo\AppData\Local\Google\Chrome\User Data\Default
```

## 复用经验（已源码 + 行为双重验证）

### 1. `Chromium(int_port)` 在端口空闲时会悄悄拉白板 Chrome
源码：`_functions/browser.py` 的 `connect_browser` 判断 `port_is_using == False` 时调 `_run_browser(port, browser_path, args)` 用 DrissionPage 默认参数启动 Chrome。
影响：自定义 `--user-data-dir` / `--proxy-server` 等启动参数被 DrissionPage 默认参数完全覆盖，每次运行多一次白板 Chrome 浪费。
正确做法：attach 之前先 `_find_pids_on_port(port)` 自己探测，空端口直接 fall through 到 `subprocess.Popen` 分支。

### 2. `browser.quit()` 默认 `force=False` 不杀进程
源码：`_base/chromium.py:253` 的 `def quit(self, timeout=5, force=False, del_data=False)`，默认只发 CDP `Browser.close` + detach WebSocket。attach 进来的 Chrome 进程不会被终止（加上 Chrome 的后台保持运行机制），port 继续 LISTEN，下次启动见"僵尸"。
正确做法：必须 `browser.quit(force=True)`，走 `SystemInfo.getProcessInfo` + `psutil.Process.kill()` 路径。

### 3. `Chromium(port)` attach 握手成功 ≠ page target 就绪
行为：subprocess 起的 Chrome 1 秒内 CDP 就 ready，但 `browser.tab_ids[0]` 还可能是空列表，`browser.latest_tab` 直接 IndexError。
正确做法：attach 后做"干活探测"：`new_tab('about:blank')` + `latest_tab.url` 任一失败就继续等。

### 4. 辅助经验（防御性）
- Windows 杀 Chrome 必须 `taskkill /F /T` 带 `/T`，主进程 + 一堆 renderer/GPU/utility 子进程要整棵树一起杀
- Chrome 异常退出的 `SingletonLock`/`SingletonCookie`/`SingletonSocket` 残留，Popen 前主动 `os.remove` 防死锁
- netstat 解析用 `parts.index('LISTENING')` 关键字定位 PID，不要用 `parts[-2]` 位置偏移（列数随 Windows 版本变化）
