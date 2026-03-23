# P005 — 站点感知反爬策略 + 多站点并发安全

## 背景

### 问题现象

basspro 临时任务报告"爬取成功（1 个产品、0 条评论）"，但实际浏览器显示代理连接失败页面。根因分析揭示了一条完整的故障链路。

### 根因链路

1. **代理 API 返回 JSON 错误响应**（`{"ret":1,"msg":""}`）被当作有效 ip:port — proxy.py 格式校验太宽松
2. **`PROXY_SITES=basspro` 杀掉了用户数据 Chrome** — `_get_page()` 中 PROXY_SITES 分支无条件 `browser.quit()` + `_create_browser(proxy)`，抛弃了用户数据模式的 `_abck` cookie
3. **`eager` 加载模式截断 Akamai JS challenge** — BassProScraper 沿用全局 `eager` 模式，Akamai sensor 脚本没时间完成
4. **Chrome 错误页面未被 `_is_blocked()` 识别** — 代理连接失败的 neterror 页面不匹配任何反爬特征
5. **`scrape()` 不校验结果** — name/sku 全为 null 仍返回成功

### 已修复（本次对话前半段）

- `proxy.py`: 严格 IP:port 正则校验
- `base.py`: `_is_blocked()` 增加 `chrome-error://` 和 `neterror` 检测
- 三个 scraper: `_validate_product()` 校验 name+sku 不能同时为空

### 本计划要解决的深层问题

- 用户数据模式与 PROXY_SITES 的配置冲突
- `eager` 模式截断 Akamai challenge
- 浏览器重启丢失 `_abck` cookie
- 代理轮换恶性循环（每次换代理都重建裸浏览器 → 又被封）
- 代理池 `_current` 全局共享的多线程竞争
- 用户数据模式下多 task 并行的端口/标签页冲突

## 设计

### 模块 1：站点级属性声明

每个 Scraper 子类通过类属性声明反爬需求，BaseScraper 根据属性选择策略。

```python
class BaseScraper:
    SITE_LOAD_MODE: str = "eager"       # 页面加载模式（子类可覆盖）
    SITE_NEEDS_USER_DATA: bool = False  # 是否需要 Chrome 用户数据模式
    SITE_RESTART_SAFE: bool = True      # 浏览器重启是否安全（不丢关键 cookie）

class BassProScraper(BaseScraper):
    SITE_LOAD_MODE = "normal"           # Akamai challenge 需要完整加载
    SITE_NEEDS_USER_DATA = True         # 需要用户数据绕过 Akamai
    SITE_RESTART_SAFE = False           # 重启会丢 _abck cookie

class MeatYourMakerScraper(BaseScraper):
    SITE_LOAD_MODE = "normal"           # BV 脚本需要 normal（已有覆写）

class WaltonsScraper(BaseScraper):
    SITE_LOAD_MODE = "normal"           # Cloudflare + TrustSpot 需要 normal（已有覆写）
```

**变更点**：
- `_build_options()` 基类实现从全局 `config.LOAD_MODE` 改为读取 `self.SITE_LOAD_MODE`
- 各子类已有的 `_build_options()` 覆写保持不变
- `_maybe_restart_browser()` 检查 `self.SITE_RESTART_SAFE` 而非 `self._use_user_data`

### 模块 2：`_get_page()` 重构 — 用户数据 + 代理组合

**核心发现**：Chrome 支持 `--user-data-dir` 和 `--proxy-server` 同时使用。`--proxy-server` 通过 HTTP CONNECT 隧道代理，Chrome 到目标站点的 TLS 握手穿过代理但 **JA3 指纹不变**。因此可以同时拥有：

- 用户数据的 `_abck` cookie（通过 Akamai 验证）
- 代理 IP 的住宅地址（避免本机 IP 被封）

#### `_launch_with_user_data(proxy)` 改造

```python
@classmethod
def _launch_with_user_data(cls, proxy: str | None = None) -> Chromium:
    port = cls._USER_DATA_PORT
    # 如果无代理，尝试连接已运行的 Chrome
    if not proxy:
        try:
            return Chromium(port)
        except Exception:
            pass
    else:
        # 有代理时必须重启 Chrome（代理是启动参数，不能运行时切换）
        cls._kill_user_data_chrome(port)

    args = [
        chrome_path,
        f'--remote-debugging-port={port}',
        f'--user-data-dir={CHROME_USER_DATA_PATH}',
        '--profile-directory=Default',
        # ... 其他参数 ...
    ]
    if proxy:
        args.append(f'--proxy-server=http://{proxy}')
    subprocess.Popen(args, ...)
    # 等待就绪...
```

#### Cookie 预热机制 `_warm_up()`

```python
def _warm_up(self, tab):
    """首次使用浏览器时，访问站点首页完成 Akamai challenge"""
    tab.get("https://www.basspro.com/")
    tab.wait(3, 5)  # 给 Akamai sensor 足够时间执行
```

- 浏览器首次创建/重启后调用一次
- `normal` 模式让 JS challenge 完整执行
- 之后产品页请求带着有效 `_abck` cookie

#### `_get_page()` 三层策略

```
_get_page(url):

  用户数据模式 + SITE_NEEDS_USER_DATA?
    → 用户数据 Chrome + 代理（组合启动）
    → _warm_up() 预热（首次/重启后）
    → tab.get(url)
    → 被封 → rotate 代理 → 重启用户数据 Chrome（保留 cookie + 新代理）→ 重新预热

  PROXY_SITES 中 + 非用户数据模式?
    → 首次直接用代理（现有逻辑）
    → 被封 → 代理轮换

  其他站点?
    → 先直连
    → 被封 → 代理降级
```

### 模块 3：代理池 `_current` 竞争修复

**问题**：`ProxyPool._current` 全局共享，多线程同时 `rotate()` 可能拉黑错误代理。

**修复**：删除 `self._current`，`rotate()` 改为接受参数：

```python
class ProxyPool:
    def rotate(self, current_proxy: str | None = None) -> str | None:
        with self._lock:
            if current_proxy:
                self._add_to_blacklist(current_proxy)
            proxy = self._pick_from_whitelist()
            if proxy:
                return proxy
            return self._fetch_new()

    def get(self) -> str | None:
        with self._lock:
            proxy = self._pick_from_whitelist()
            if proxy:
                return proxy
            return self._fetch_new()
```

调用方（BaseScraper）传入 `self._proxy`：

```python
new_proxy = pool.rotate(current_proxy=self._proxy)
self._proxy = new_proxy
```

### 模块 4：用户数据模式并发安全

**问题**：Chrome 用户数据目录不能被多个进程同时使用（SingletonLock），且固定端口 19222 导致多个 scraper 共享同一 Chrome → `latest_tab` 竞争。

**方案**：用户数据站点加全局 Lock，串行化页面访问。

```python
class BaseScraper:
    _user_data_lock = threading.Lock()

    def _get_page(self, url: str):
        if self._use_user_data and self.SITE_NEEDS_USER_DATA:
            with self._user_data_lock:
                return self._get_page_impl(url)
        return self._get_page_impl(url)
```

**取舍**：basspro 并行度降低（串行），但：
- Chrome 用户数据本身就是单进程限制
- 串行降低请求频率，反而不容易触发 Akamai 行为分析
- waltons/meatyourmaker 不受影响，仍并行

## 并发全景

| 站点 | 浏览器模式 | 并行能力 | 代理 | 加载模式 |
|------|-----------|---------|------|---------|
| basspro | 用户数据 + 代理（端口 19222） | 串行（Lock） | 住宅代理 | normal |
| waltons | 独立浏览器（auto_port） | 并行 | 按需 | normal |
| meatyourmaker | 独立浏览器（auto_port） | 并行 | 不需要 | normal |

定时任务提交 3-6 个 task → `MAX_WORKERS=3` 同时执行 3 个 → 最多 3 个浏览器：
- basspro task 共享 1 个用户数据 Chrome（Lock 串行）
- waltons/meatyourmaker 各自独立浏览器（并行）

## 文件变更清单

| 文件 | 变更 |
|------|------|
| `scrapers/base.py` | 站点属性 + `_build_options()` 读取属性 + `_launch_with_user_data(proxy)` + `_warm_up()` + `_get_page()` 重构 + `_maybe_restart_browser()` 检查 `SITE_RESTART_SAFE` + `_user_data_lock` |
| `scrapers/basspro.py` | 声明 `SITE_LOAD_MODE`/`SITE_NEEDS_USER_DATA`/`SITE_RESTART_SAFE` |
| `scrapers/meatyourmaker.py` | 声明 `SITE_LOAD_MODE`（保持已有覆写） |
| `scrapers/waltons.py` | 声明 `SITE_LOAD_MODE`（保持已有覆写） |
| `proxy.py` | `rotate(current_proxy)` 参数化，删除 `self._current` |

不变：TaskManager、MCP Tools、HTTP API、数据库模型、config.py。

## 实施顺序

1. proxy.py: `_current` 竞争修复（独立，可先合并）
2. base.py: 站点属性 + `_build_options()` 改造
3. 三个 scraper: 声明站点属性
4. base.py: `_launch_with_user_data(proxy)` + `_warm_up()`
5. base.py: `_get_page()` 重构（依赖 1-4）
6. base.py: `_user_data_lock` 并发保护
7. 集成测试：单站点 + 多站点并行

## 风险

- **用户数据 Chrome 重启耗时**：用户数据目录可能数 GB，重启需要 10-20 秒。代理轮换时会有较长停顿。可接受（比恶性循环好）。
- **预热增加每次重启的开销**：额外 3-5 秒。可接受。
- **Lock 串行化降低 basspro 吞吐**：但 basspro 本身请求间有 1-3 秒延迟，串行影响有限。
