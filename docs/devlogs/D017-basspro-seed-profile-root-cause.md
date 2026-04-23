# D017 - BassPro seed profile 根因与 cookies-only 修复

日期：2026-04-23

相关文件：
- `qbu_crawler/config.py`
- `qbu_crawler/scrapers/base.py`
- `.env.example`
- `tests/test_base_scraper.py`
- `AGENTS.md`

## 现象

同样的 `qbu-crawler@0.3.12`：

- `C:\Users\leo\...` 本地能正常进入 `[预热]`
- `C:\Users\User\...` 线上稳定卡在：
  - `[启动] attach_browser 成功`
  - `[启动] cleanup_tabs 开始`
  - 后续无 `cleanup_tabs 完成` / `probe_browser_alive` / `[预热]`

用户已验证：

- 删除 `QBU\chrome_profile` 无效
- 强制 `--python=3.11` 无效
- 注释 `CHROME_USER_DATA_SEED=...User Data` 后恢复正常

## 根因

问题不在 `QBU\chrome_profile` 历史残留，而在 seed 来源：

- `CHROME_USER_DATA_SEED=C:\Users\User\AppData\Local\Google\Chrome\User Data`

旧逻辑会把真实 Chrome profile 里的这些文件复制到爬虫专属目录：

- `Default/Cookies`
- `Default/Cookies-journal`
- `Default/Preferences`
- `Local State`

其中真正对 BassPro 有价值的是 `Cookies`（Akamai `_abck` 等 cookie）。

`Preferences` 和 `Local State` 带进来的却是“个人浏览器状态”，包括但不限于：

- 启动页/会话恢复偏好
- 标签页恢复状态
- 扩展和 profile 元信息
- 其它与真实桌面浏览器相关的 UI / startup 状态

而爬虫 profile 并没有完整复制真实 profile 的配套文件（如完整 session 数据、扩展目录、各种运行态状态），于是形成“半个真实 profile”。

在 `leo` 机器上，这份半 profile 还能启动；
在 `User` 机器上，attach 成功后 tab 清理阶段直接卡死，于是只看到白板 `about:blank`。

## 为什么删 `QBU\chrome_profile` 没用

因为每次启动前虽然删掉了目标目录，但启动时又会从 seed 目录把 `Preferences` / `Local State` 重新复制回来。

所以“坏状态”每次都会被重新注入。

## 修复策略

把 `CHROME_USER_DATA_SEED` 明确降级成“cookie 种子”，默认只同步：

- `Default/Cookies`
- `Default/Cookies-journal`

不再默认同步：

- `Default/Preferences`
- `Local State`

这样爬虫专属目录的定位就清晰了：

- 它是 cookie jar
- 不是半个真实桌面 profile

## 兼容处理

保留两个显式开关，只有在用户明确需要时才同步偏好文件：

- `CHROME_USER_DATA_COPY_PREFERENCES=true`
- `CHROME_USER_DATA_COPY_LOCAL_STATE=true`

默认都为 `false`。

## 验证

执行：

```bash
uv run pytest tests/test_base_scraper.py tests/test_runtime.py
```

结果：

- `tests/test_base_scraper.py` 6 通过
- `tests/test_runtime.py` 2 通过

并新增测试覆盖：

- 默认只回写 cookies
- 显式开启时仍可回写 `Preferences` / `Local State`

## 结论

BassPro 这次“白板但非反爬”的真正根因是：

- 把真实 Chrome 的 `Preferences` / `Local State` 当成 seed 同步到了爬虫 profile

长期正确做法是：

- 默认只同步 cookies
- 把爬虫 profile 当成 automation cookie jar
- 不要把真实桌面浏览器状态直接带入自动化环境
