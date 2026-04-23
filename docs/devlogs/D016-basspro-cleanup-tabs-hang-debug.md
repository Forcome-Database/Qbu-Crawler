# D016 - BassPro `_cleanup_tabs()` 挂起定位与启动链超时兜底

日期：2026-04-23

相关文件：
- `qbu_crawler/scrapers/base.py`
- `tests/test_base_scraper.py`
- `AGENTS.md`

## 现象

线上 `qbu-crawler@0.3.12` 的 BassPro 任务日志停在：

- `[启动] cleanup_tabs 开始: port=...`

之后没有：

- `[启动] cleanup_tabs 完成`
- `[启动] probe_browser_alive 开始`
- `[预热] 访问 basspro.com 首页完成 Akamai challenge...`

与此同时 Chrome 可见窗口只剩一个白板 `about:blank`，Walton's / MeatYourMaker 正常。

## 已定位根因

这次白板不是反爬，也不是 Chrome `Popen` / `attach` 失败。

从分段日志可以确认：

1. `BassProScraper()` 已经进入用户数据启动链
2. `Chromium(port)` attach 成功
3. 卡死发生在 `_cleanup_tabs()` 内部的 tab 级 CDP 调用

也就是说，根因已经从“浏览器没起来”收敛为：

- attach 后的 `get_tabs()` / `new_tab()` / `tab.close()` 之一在用户现场无超时挂住

这和 0.3.7 的回归不一样。0.3.7 是 `_cleanup_tabs()` 跑完后把 page target 关坏；这次是 `_cleanup_tabs()` 自己没有返回。

## 为什么用户现场更容易中招

BassPro 走 `SITE_NEEDS_USER_DATA = True`，会带用户数据目录启动 Chrome。

这条链路有两个额外风险：

1. 会话启动后可能恢复出旧标签，必须做 tab 清理
2. DrissionPage 的 tab 级 websocket 调用默认没有我们自己的超时兜底

所以只要某一步卡住，整个 scraper 构造阶段就会永远停在白板，任务层面也看不到 traceback。

## 修复

本次修复只动启动链，不动抓取规则：

1. 给 `_cleanup_tabs()` 里的 `get_tabs()` / `new_tab()` / `tab.close()` 增加临时 socket 超时
2. 给 `_probe_browser_alive()` 增加临时 socket 超时
3. 给 `_cleanup_tabs()` 增加更细粒度 debug 日志：
   - `get_tabs 开始/完成`
   - `new_tab 开始/完成`
   - `关闭旧标签开始/完成/失败`
4. 把 `--restore-last-session=false` 加回 Chrome 启动参数，尽量减少旧会话标签恢复

## 验证

执行：

```bash
uv run pytest tests/test_base_scraper.py tests/test_runtime.py
```

结果：

- `tests/test_base_scraper.py` 5 通过
- `tests/test_runtime.py` 2 通过

另做本地冒烟：

- `BassProScraper()` 能正常完成 `attach -> cleanup_tabs -> probe_browser_alive`
- 本地日志显示 `get_tabs 完成: 共 1 个`，说明在正常环境下不会引入额外副作用

## 结论

当前已确认：

- 不是 `basspro.com` 反爬把页面拦成白板
- 不是 wheel 漏打包
- 不是 `Python 3.14` 单独导致

当前最核心的根因是：

- 用户数据模式下，DrissionPage attach 成功后，tab 清理阶段的 websocket 调用无超时挂死

下一次线上验证时，日志会进一步明确卡在：

- `get_tabs`
- `new_tab`
- 还是某个 `tab.close()`
