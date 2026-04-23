# D015 - BassPro `_cleanup_tabs()` 回归修复

日期：2026-04-22

相关文件：
- `qbu_crawler/scrapers/base.py`
- `tests/test_base_scraper.py`
- `AGENTS.md`

## 现象

`qbu-crawler@0.3.7` 在创建 `BassProScraper()` 时反复输出：

- `[清理] 关闭 2 个多余标签（共 3 个）`
- `[启动] 浏览器健康探测失败: The connection to the page has been disconnected.`
- `Popen 的 Chrome 已退出 (attempt 40)`

Walton's 仍能抓，BassPro 全挂。

## 根因

BassPro 启用了 `SITE_NEEDS_USER_DATA = True`，会进入用户数据启动链。当前分支里的 `_cleanup_tabs()` 采用：

```python
for tab in tabs[:-1]:
    tab.close()
```

DrissionPage 的 `latest_tab` 实际对应 `tab_ids[0]`。当会话恢复出多个标签页时，直接关闭旧 tabs 会把后续健康探测依赖的 page target 一起关掉，接着读取 `latest_tab.url` 就会报：

```text
The connection to the page has been disconnected.
```

之后启动链误判为 Chrome 僵尸，进入 kill + Popen 重试死循环。

## 修复

把 `_cleanup_tabs()` 改为：

1. 先 `new_tab('about:blank')`
2. 再关闭旧标签
3. 保留 fresh tab 作为后续 `latest_tab` 指向的稳定 target

## 验证

新增回归测试 `tests/test_base_scraper.py`：

- 多标签场景下，必须先创建 fresh `about:blank`
- 所有旧标签都应关闭
- fresh 标签不能被误关
- 单标签场景应跳过清理

执行：

```bash
uv run pytest tests/test_base_scraper.py tests/test_runtime.py -q
```

结果：`4 passed`
