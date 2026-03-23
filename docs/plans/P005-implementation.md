# P005 站点感知反爬策略 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 basspro Akamai 反爬失效问题，实现站点感知的浏览器/代理/加载策略，保障多站点并发安全。

**Architecture:** 每个 Scraper 子类通过类属性声明反爬需求（加载模式、是否需要用户数据、是否可安全重启），BaseScraper 根据属性自动选择浏览器创建方式和代理策略。用户数据模式与代理可组合使用（Chrome 同时接受 `--user-data-dir` 和 `--proxy-server`）。代理池的 `_current` 从全局移到每个 scraper 实例上，消除多线程竞争。

**Tech Stack:** Python 3.10+, DrissionPage, threading

**Spec:** `docs/plans/P005-anti-bot-and-concurrency.md`

---

### Task 1: 代理池 `_current` 竞争修复

**Files:**
- Modify: `qbu_crawler/proxy.py:28-79` — 删除 `self._current`，`rotate()` 接受参数
- Modify: `tests/test_proxy.py` — 更新测试适配新签名

- [ ] **Step 1: 更新 `rotate()` 签名和 `get()` 实现**

`qbu_crawler/proxy.py` — 删除 `__init__` 中的 `self._current`，`get()` 不再写 `_current`，`rotate()` 改为接受 `current_proxy` 参数，`_fetch_new()` 不再写 `_current`：

```python
# __init__ 中删除:
#     self._current: str | None = None

# get() 改为:
def get(self) -> str | None:
    """获取代理：白名单优先 → API 获取新 IP"""
    with self._lock:
        proxy = self._pick_from_whitelist()
        if proxy:
            return proxy
        return self._fetch_new()

# rotate() 改为:
def rotate(self, current_proxy: str | None = None) -> str | None:
    """指定代理被封，拉黑后获取新代理"""
    with self._lock:
        if current_proxy:
            self._add_to_blacklist(current_proxy)
        proxy = self._pick_from_whitelist()
        if proxy:
            return proxy
        return self._fetch_new()

# _fetch_new() 中删除:
#     self._current = ip_port  (第 139 行)
```

- [ ] **Step 2: 更新测试适配新签名**

`tests/test_proxy.py` — 所有引用 `pool._current` 和 `pool.rotate()` 的测试改为使用新签名：

```python
# test_rotate_blacklists_current:
#   pool.get() 不再设置 _current，rotate() 需要传参
def test_rotate_blacklists_current(self):
    """rotate(current_proxy) 将指定 IP 加入黑名单"""
    pool = ProxyPool(API_URL)
    with patch("qbu_crawler.proxy.requests.get") as mock_get:
        mock_get.side_effect = [
            _mock_resp("1.1.1.1:8080\n"),
            _mock_resp("2.2.2.2:9090\n"),
        ]
        first = pool.get()
        assert first == "1.1.1.1:8080"
        second = pool.rotate(current_proxy="1.1.1.1:8080")
        assert "1.1.1.1" in pool._blacklist
        assert second == "2.2.2.2:9090"

# test_rotate_removes_from_whitelist:
def test_rotate_removes_from_whitelist(self):
    """rotate() 拉黑时同时从白名单移除"""
    pool = ProxyPool(API_URL)
    pool.mark_good("1.1.1.1:8080")
    with patch("qbu_crawler.proxy.requests.get") as mock_get:
        mock_get.return_value = _mock_resp("3.3.3.3:7070\n")
        pool.rotate(current_proxy="1.1.1.1:8080")
        assert "1.1.1.1:8080" not in pool._whitelist
        assert "1.1.1.1" in pool._blacklist

# test_blacklist_same_ip_different_port:
def test_blacklist_same_ip_different_port(self):
    """同 IP 不同端口也视为黑名单"""
    pool = ProxyPool(API_URL)
    with patch("qbu_crawler.proxy.requests.get") as mock_get:
        mock_get.side_effect = [
            _mock_resp("1.1.1.1:9090\n"),
            _mock_resp("2.2.2.2:7070\n"),
        ]
        proxy = pool.rotate(current_proxy="1.1.1.1:8080")
        assert proxy == "2.2.2.2:7070"

# test_whitelist_then_blacklist_flow:
def test_whitelist_then_blacklist_flow(self):
    """完整流程：成功→白名单→后来被封→黑名单→换新"""
    pool = ProxyPool(API_URL)
    pool.mark_good("1.1.1.1:8080")
    assert "1.1.1.1:8080" in pool._whitelist
    with patch("qbu_crawler.proxy.requests.get") as mock_get:
        mock_get.return_value = _mock_resp("3.3.3.3:7070\n")
        proxy = pool.rotate(current_proxy="1.1.1.1:8080")
        assert proxy == "3.3.3.3:7070"
        assert "1.1.1.1" in pool._blacklist
        assert "1.1.1.1:8080" not in pool._whitelist
```

- [ ] **Step 3: 运行测试验证**

Run: `cd "E:/Project/ForcomeAiTools/Qbu-Crawler" && uv run pytest tests/test_proxy.py -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add qbu_crawler/proxy.py tests/test_proxy.py
git commit -m "fix: 代理池 rotate() 参数化，消除 _current 多线程竞争"
```

---

### Task 2: BaseScraper 站点级属性 + `_build_options()` 改造

**Files:**
- Modify: `qbu_crawler/scrapers/base.py:63-102` — 添加类属性，`_build_options()` 改为实例方法读取 `self.SITE_LOAD_MODE`

- [ ] **Step 1: 添加站点级类属性**

`qbu_crawler/scrapers/base.py` — 在 `BaseScraper` 类定义中、`_USER_DATA_PORT` 下方添加：

```python
class BaseScraper:
    _USER_DATA_PORT = 19222

    # ── 站点级属性（子类可覆盖）──
    SITE_LOAD_MODE: str = "eager"       # 页面加载模式
    SITE_NEEDS_USER_DATA: bool = False  # 是否需要 Chrome 用户数据模式
    SITE_RESTART_SAFE: bool = True      # 浏览器重启是否安全（不丢关键 cookie）
```

- [ ] **Step 2: `_build_options()` 从 `@staticmethod` 改为普通方法**

将 `_build_options` 从 `@staticmethod` 改为实例方法，读取 `self.SITE_LOAD_MODE`：

```python
def _build_options(self) -> ChromiumOptions:
    options = ChromiumOptions()
    options.auto_port()
    if HEADLESS:
        if _has_display():
            options.headless()
        options.set_argument('--window-size=1920,1080')
    else:
        options.set_argument('--start-maximized')
    if NO_IMAGES:
        options.no_imgs(True)
    options.set_load_mode(self.SITE_LOAD_MODE)  # 读取站点属性而非全局配置
    options.set_retry(times=RETRY_TIMES, interval=RETRY_INTERVAL)
    options.set_timeouts(base=10, page_load=PAGE_LOAD_TIMEOUT)
    options.set_argument('--deny-permission-prompts')
    options.set_argument('--disable-blink-features=AutomationControlled')
    return options
```

注意：`LOAD_MODE` 的 import 可以保留（不影响），或删除（更干净）。

- [ ] **Step 3: `_maybe_restart_browser()` 使用 `SITE_RESTART_SAFE`**

```python
def _maybe_restart_browser(self):
    """定期重启浏览器，防止长时间运行内存泄漏"""
    if not self.SITE_RESTART_SAFE:
        return  # 站点声明重启不安全（如 Akamai _abck cookie）
    if RESTART_EVERY and self._scrape_count > 0 and self._scrape_count % RESTART_EVERY == 0:
        print(f"  [优化] 已抓取 {self._scrape_count} 个产品，重启浏览器释放内存")
        try:
            self.browser.quit()
        except Exception:
            pass
        self.browser = self._create_browser(proxy=self._proxy)
```

- [ ] **Step 4: Commit**

```bash
git add qbu_crawler/scrapers/base.py
git commit -m "refactor: BaseScraper 站点级属性 + _build_options 读取 SITE_LOAD_MODE"
```

---

### Task 3: 三个 Scraper 声明站点属性

**Files:**
- Modify: `qbu_crawler/scrapers/basspro.py:12` — 添加 3 个类属性
- Modify: `qbu_crawler/scrapers/meatyourmaker.py:12` — 添加 `SITE_LOAD_MODE`
- Modify: `qbu_crawler/scrapers/waltons.py:18` — 添加 `SITE_LOAD_MODE`

- [ ] **Step 1: BassProScraper 声明属性**

`qbu_crawler/scrapers/basspro.py` — 在 `class BassProScraper(BaseScraper):` 下方添加：

```python
class BassProScraper(BaseScraper):
    SITE_LOAD_MODE = "normal"       # Akamai challenge 需要完整加载
    SITE_NEEDS_USER_DATA = True     # 需要用户数据绕过 Akamai
    SITE_RESTART_SAFE = False       # 重启会丢 _abck cookie
```

- [ ] **Step 2: MeatYourMakerScraper 声明属性**

`qbu_crawler/scrapers/meatyourmaker.py` — 在类定义下方添加：

```python
class MeatYourMakerScraper(BaseScraper):
    SITE_LOAD_MODE = "normal"  # BV 脚本需要 normal 模式
```

注意：其 `_build_options()` 覆写保持不变（它有自己的简化实现），`SITE_LOAD_MODE` 属性仅供基类 `_build_options()` 使用，如果子类覆写了 `_build_options()` 则属性不会生效，但声明它有助于自文档化。

- [ ] **Step 3: WaltonsScraper 声明属性**

`qbu_crawler/scrapers/waltons.py` — 在类定义下方添加：

```python
class WaltonsScraper(BaseScraper):
    SITE_LOAD_MODE = "normal"  # Cloudflare + TrustSpot 需要 normal 模式
```

同理，其 `_build_options()` 覆写保持不变。

- [ ] **Step 4: Commit**

```bash
git add qbu_crawler/scrapers/basspro.py qbu_crawler/scrapers/meatyourmaker.py qbu_crawler/scrapers/waltons.py
git commit -m "feat: 三个 Scraper 声明站点级反爬属性"
```

---

### Task 4: `_launch_with_user_data(proxy)` 改造 + `_warm_up()`

**Files:**
- Modify: `qbu_crawler/scrapers/base.py:67-76` — `__init__` 适配新启动逻辑
- Modify: `qbu_crawler/scrapers/base.py:104-141` — `_launch_with_user_data` 支持 proxy 参数
- Add method: `_kill_user_data_chrome()`, `_warm_up()`

- [ ] **Step 1: 添加 `_kill_user_data_chrome()` 方法**

在 `_launch_with_user_data` 前添加：

```python
@classmethod
def _kill_user_data_chrome(cls, port: int):
    """关闭占用指定调试端口的 Chrome 进程"""
    try:
        import urllib.request
        urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2)
        # 端口有响应，说明 Chrome 在运行，通过 CDP 关闭
        browser = Chromium(port)
        browser.quit()
    except Exception:
        pass  # 端口无响应，Chrome 已关闭
```

- [ ] **Step 2: `_launch_with_user_data` 支持 proxy 参数**

改造 `_launch_with_user_data` 签名和逻辑：

```python
@classmethod
def _launch_with_user_data(cls, proxy: str | None = None) -> Chromium:
    """使用 Chrome 用户数据启动浏览器，可选代理。
    Chrome 支持 --user-data-dir + --proxy-server 同时使用，
    代理通过 HTTP CONNECT 隧道，JA3 指纹不变。"""
    port = cls._USER_DATA_PORT

    if proxy:
        # 代理是启动参数，切换代理必须重启 Chrome
        cls._kill_user_data_chrome(port)
    else:
        # 无代理时尝试连接已运行的 Chrome
        try:
            return Chromium(port)
        except Exception:
            pass

    chrome_path = _find_chrome()
    args = [
        chrome_path,
        f'--remote-debugging-port={port}',
        f'--user-data-dir={CHROME_USER_DATA_PATH}',
        '--profile-directory=Default',
        '--disable-blink-features=AutomationControlled',
        '--deny-permission-prompts',
        '--no-first-run',
        '--no-default-browser-check',
        'about:blank',
    ]
    if proxy:
        args.append(f'--proxy-server=http://{proxy}')
    if HEADLESS and _has_display():
        args.append('--headless=new')
    args.append('--disable-session-crashed-bubble')
    args.append('--restore-last-session=false')
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(20):
        time.sleep(1)
        try:
            return Chromium(port)
        except Exception:
            continue
    raise RuntimeError(f"Chrome with user data failed to start on port {port}")
```

- [ ] **Step 3: 添加 `_warm_up()` 方法**

在 `_launch_with_user_data` 后添加：

```python
def _warm_up(self):
    """访问站点首页完成 Akamai challenge，建立有效 _abck cookie。
    仅在浏览器首次创建/重启后调用一次。"""
    # 子类可覆盖提供站点首页 URL，默认不预热
    pass

# BassProScraper 中覆盖（Task 5 实现）
```

- [ ] **Step 4: 更新 `__init__` — 用户数据模式传入代理**

```python
def __init__(self):
    if HEADLESS and not _has_display():
        _ensure_virtual_display()
    self._use_user_data = bool(CHROME_USER_DATA_PATH) and self.SITE_NEEDS_USER_DATA
    self._proxy = None
    self._warmed_up = False  # 是否已完成 cookie 预热
    if self._use_user_data:
        # 用户数据模式：检查是否需要代理
        proxy = self._get_initial_proxy()
        self._proxy = proxy
        self.browser = self._launch_with_user_data(proxy=proxy)
    else:
        self.browser = self._create_browser()
    self._scrape_count = 0
```

添加 `_get_initial_proxy()` 辅助方法：

```python
def _get_initial_proxy(self) -> str | None:
    """初始化时获取代理（如果站点配置了 PROXY_SITES）"""
    from qbu_crawler.proxy import get_proxy_pool
    pool = get_proxy_pool()
    if pool:
        proxy = pool.get()
        if proxy:
            logger.info(f"[初始化] 用户数据模式 + 代理: {proxy}")
            return proxy
    return None
```

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/scrapers/base.py
git commit -m "feat: _launch_with_user_data 支持代理参数 + cookie 预热机制"
```

---

### Task 5: `_get_page()` 重构 + BassProScraper `_warm_up`

**Files:**
- Modify: `qbu_crawler/scrapers/base.py:207-288` — 三层策略重写
- Modify: `qbu_crawler/scrapers/basspro.py` — 覆盖 `_warm_up()`

- [ ] **Step 1: `_get_page()` 重写为三层策略**

```python
_user_data_lock = threading.Lock()

def _get_page(self, url: str):
    """导航到 URL，根据站点属性选择反爬策略。

    三层策略：
    1. 用户数据 + 代理（Akamai 站点）：保留 cookie + 代理 IP
    2. PROXY_SITES 直接代理（无用户数据时）
    3. 直连 → 被封降级代理（默认）
    """
    if self._use_user_data and self.SITE_NEEDS_USER_DATA:
        with self._user_data_lock:
            return self._get_page_user_data(url)
    return self._get_page_default(url)

def _get_page_user_data(self, url: str):
    """用户数据模式：保留 cookie，代理轮换时重启 Chrome 但保留用户数据"""
    from qbu_crawler.proxy import get_proxy_pool
    from qbu_crawler.config import PROXY_MAX_RETRIES

    # 预热：首次或重启后访问首页完成 Akamai challenge
    if not self._warmed_up:
        self._warm_up()
        self._warmed_up = True

    tab = self.browser.latest_tab
    tab.get(url)

    if not self._is_blocked(tab):
        if self._proxy:
            pool = get_proxy_pool()
            if pool:
                pool.mark_good(self._proxy)
        return tab

    # 被封 → 轮换代理，重启用户数据 Chrome
    pool = get_proxy_pool()
    if not pool:
        raise RuntimeError(
            f"用户数据模式下仍被封锁: {url}。"
            "请手动用 Chrome 访问 basspro.com 刷新 cookie，"
            "或配置 PROXY_API_URL 启用代理池。"
        )

    for attempt in range(PROXY_MAX_RETRIES):
        new_proxy = pool.rotate(current_proxy=self._proxy)
        if not new_proxy:
            logger.error(f"[反爬] 无法获取代理 IP (attempt {attempt + 1})")
            continue
        if new_proxy == self._proxy:
            logger.warning(f"[反爬] 代理未变化 {new_proxy}，跳过")
            continue

        self._proxy = new_proxy
        logger.warning(
            f"[反爬] 被封 → 用户数据 + 代理 {new_proxy} "
            f"(attempt {attempt + 1}/{PROXY_MAX_RETRIES})"
        )
        # 重启用户数据 Chrome（保留 cookie + 新代理）
        self.browser = self._launch_with_user_data(proxy=new_proxy)
        self._warmed_up = False
        self._warm_up()
        self._warmed_up = True

        tab = self.browser.latest_tab
        tab.get(url)

        if not self._is_blocked(tab):
            pool.mark_good(new_proxy)
            return tab

    raise RuntimeError(
        f"用户数据模式下已尝试 {PROXY_MAX_RETRIES} 个代理均失败: {url}"
    )

def _get_page_default(self, url: str):
    """默认策略：直连或 PROXY_SITES 代理，被封后轮换"""
    from qbu_crawler.proxy import get_proxy_pool
    from qbu_crawler.config import PROXY_MAX_RETRIES

    # PROXY_SITES: 首次直接走代理
    if not self._proxy and self._site_needs_proxy(url):
        pool = get_proxy_pool()
        if pool:
            proxy = pool.get()
            if proxy:
                self._proxy = proxy
                logger.info(f"[反爬] 站点配置直接走代理: {proxy}")
                try:
                    self.browser.quit()
                except Exception:
                    pass
                self.browser = self._create_browser(proxy=proxy)

    tab = self.browser.latest_tab
    tab.get(url)

    if not self._is_blocked(tab):
        if self._proxy:
            pool = get_proxy_pool()
            if pool:
                pool.mark_good(self._proxy)
        return tab

    # 代理重试
    pool = get_proxy_pool()
    if not pool:
        raise RuntimeError(
            f"页面被反爬系统封锁: {url}。"
            "请配置 PROXY_API_URL 环境变量启用代理池。"
        )

    for attempt in range(PROXY_MAX_RETRIES):
        new_proxy = (
            pool.get() if (attempt == 0 and not self._proxy)
            else pool.rotate(current_proxy=self._proxy)
        )
        if not new_proxy:
            logger.error(f"[反爬] 无法获取代理 IP (attempt {attempt + 1})")
            continue
        if new_proxy == self._proxy and attempt > 0:
            logger.warning(f"[反爬] 代理未变化 {new_proxy}，跳过")
            continue

        self._proxy = new_proxy
        logger.warning(
            f"[反爬] Access Denied → 代理 {new_proxy} "
            f"(attempt {attempt + 1}/{PROXY_MAX_RETRIES})"
        )
        try:
            self.browser.quit()
        except Exception:
            pass
        self.browser = self._create_browser(proxy=new_proxy)
        tab = self.browser.latest_tab
        tab.get(url)

        if not self._is_blocked(tab):
            pool.mark_good(new_proxy)
            return tab

    raise RuntimeError(
        f"页面被反爬系统封锁，已尝试 {PROXY_MAX_RETRIES} 个代理均失败: {url}"
    )
```

注意：需要在文件顶部 `import threading`（已有 `import time` 等，确认是否需要新增）。

- [ ] **Step 2: BassProScraper 覆盖 `_warm_up()`**

`qbu_crawler/scrapers/basspro.py` — 在站点属性下方添加：

```python
def _warm_up(self):
    """访问 basspro 首页完成 Akamai challenge，建立有效 _abck cookie"""
    tab = self.browser.latest_tab
    logger.info("[预热] 访问 basspro.com 首页完成 Akamai challenge...")
    tab.get("https://www.basspro.com/")
    tab.wait(3, 5)  # 给 Akamai sensor 足够时间执行
    if self._is_blocked(tab):
        logger.warning("[预热] 首页访问被封锁，_abck cookie 可能无效")
    else:
        logger.info("[预热] Akamai challenge 完成")
```

- [ ] **Step 3: 确认 `import threading` 存在**

`qbu_crawler/scrapers/base.py` 顶部检查是否有 `import threading`，没有则添加。

- [ ] **Step 4: Commit**

```bash
git add qbu_crawler/scrapers/base.py qbu_crawler/scrapers/basspro.py
git commit -m "feat: _get_page 三层策略重构 + basspro cookie 预热"
```

---

### Task 6: 清理与文档同步

**Files:**
- Modify: `qbu_crawler/scrapers/base.py` — 删除不再需要的 `LOAD_MODE` import
- Modify: `docs/rules/basspro.md` — 更新反爬策略描述
- Modify: `CLAUDE.md` — 更新通用配置和架构决策

- [ ] **Step 1: 清理 base.py 的 import**

`LOAD_MODE` 从 import 列表中移除（如果基类 `_build_options()` 不再使用它）：

```python
from qbu_crawler.config import (
    HEADLESS, PAGE_LOAD_TIMEOUT, NO_IMAGES,  # 删除 LOAD_MODE
    RETRY_TIMES, RETRY_INTERVAL, REQUEST_DELAY, RESTART_EVERY,
    CHROME_USER_DATA_PATH,
)
```

- [ ] **Step 2: 更新 basspro.md 反爬策略章节**

在 `docs/rules/basspro.md` 的"解决方案"部分追加用户数据+代理组合说明：

```markdown
### 解决方案：用户数据 + 代理组合

当同时配置 `CHROME_USER_DATA_PATH` 和 `PROXY_API_URL` 时，BassProScraper 会：

1. 启动 Chrome 同时带 `--user-data-dir` 和 `--proxy-server` 参数
2. 首次访问时执行 cookie 预热（`_warm_up`），访问 basspro.com 首页完成 Akamai challenge
3. 后续产品页请求带着有效 `_abck` cookie + 住宅代理 IP
4. 代理被封时：轮换代理 → 重启 Chrome（保留用户数据）→ 重新预热
5. `PROXY_SITES=basspro` 配置在用户数据模式下被忽略（初始化时已处理代理）
```

- [ ] **Step 3: 更新 CLAUDE.md 架构决策**

在"通用架构决策"中添加"站点感知反爬策略"小节，记录类属性机制和三层策略。

- [ ] **Step 4: Commit**

```bash
git add qbu_crawler/scrapers/base.py docs/rules/basspro.md CLAUDE.md
git commit -m "docs: 同步更新反爬策略文档和架构说明"
```

---

### Task 7: 集成验证

- [ ] **Step 1: 运行全部单元测试**

Run: `cd "E:/Project/ForcomeAiTools/Qbu-Crawler" && uv run pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 2: 单站点手动验证 — basspro（用户数据+代理）**

```bash
uv run python main.py https://www.basspro.com/p/cabelas-heavy-duty-sausage-stuffer
```

验证点：
- 日志应出现 `[初始化] 用户数据模式 + 代理: x.x.x.x:port`
- 日志应出现 `[预热] 访问 basspro.com 首页完成 Akamai challenge...`
- 日志应出现 `[预热] Akamai challenge 完成`
- 产品数据正常抓取（name/sku/price 非空）

- [ ] **Step 3: 单站点手动验证 — waltons（独立浏览器）**

```bash
uv run python main.py https://www.waltons.com/brisket-flat
```

验证点：
- 不触发用户数据模式
- 正常抓取

- [ ] **Step 4: 多站点并行验证（通过 API 提交）**

通过 MCP 或 HTTP API 同时提交 basspro + waltons 任务，确认：
- basspro 使用用户数据 Chrome（端口 19222）
- waltons 使用独立浏览器（随机端口）
- 两者互不干扰
