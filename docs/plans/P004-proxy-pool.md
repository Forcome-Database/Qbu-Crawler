# 代理池集成实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 遇到 Akamai/Cloudflare Access Denied 时自动从 1024proxy API 获取代理 IP，重启浏览器并重试，支持 IP 轮换

**Architecture:** 新增 `ProxyPool` 单例管理代理 IP 生命周期（获取/缓存/轮换）。`BaseScraper` 新增 `_get_page(url)` 方法封装 `tab.get()` + 封锁检测 + 代理重试。封锁时退出当前浏览器，用新代理重新启动。各站点 scraper 将 `tab.get()` 替换为 `_get_page()` 即可获得代理能力。

**Tech Stack:** DrissionPage (Chrome `--proxy-server` flag), requests (调用代理 API), threading.Lock (线程安全)

---

## 文件变更清单

| 操作 | 文件 | 职责 |
|------|------|------|
| Create | `qbu_crawler/proxy.py` | ProxyPool 单例：调用 1024proxy API 获取/缓存/轮换代理 IP |
| Modify | `qbu_crawler/config.py` | 新增 `PROXY_API_URL`, `PROXY_MAX_RETRIES` 配置 |
| Modify | `qbu_crawler/scrapers/base.py` | 新增 `_get_page()`, `_is_blocked()`, `_create_browser()` |
| Modify | `qbu_crawler/scrapers/basspro.py` | `tab.get(url)` → `self._get_page(url)` |
| Modify | `qbu_crawler/scrapers/waltons.py` | `tab.get(url)` → `self._get_page(url)` |
| Modify | `qbu_crawler/scrapers/meatyourmaker.py` | `tab.get(url)` → `self._get_page(url)` |
| Modify | `.env.example` | 新增代理配置项 |
| Create | `tests/test_proxy.py` | ProxyPool 单元测试 |

## 核心设计决策

### 代理生命周期
```
首次访问 → tab.get(url) → 正常？→ 返回 tab
                          ↓ Access Denied
              proxy_pool.get() → 获取代理 IP
              quit browser → 用代理重启 → tab.get(url) → 正常？→ 返回 tab
                                                        ↓ Access Denied
                                         proxy_pool.rotate() → 新 IP → 重启 → 重试
                                                               ↓ 超过 max_retries
                                                            raise RuntimeError
```

### 为什么需要重启浏览器
Chrome 的 `--proxy-server` 是启动参数，无法运行时修改。每次切换代理必须：
1. `browser.quit()` — 关闭当前浏览器
2. `_create_browser(proxy=new_ip)` — 用新代理启动
3. `browser.latest_tab.get(url)` — 重新导航

### 代理模式与用户数据模式的关系
- 互不冲突，但代理模式解决的是服务器 IP 被封的问题
- 用户数据模式解决的是 cookie/session 复用问题
- 服务器部署推荐用代理模式（数据中心 IP 直接被 Akamai 前置封锁）

---

### Task 1: 配置项 (`config.py`)

**Files:**
- Modify: `qbu_crawler/config.py:30-31` (Chrome 用户数据配置区域后)
- Modify: `.env.example`

- [ ] **Step 1: 在 config.py 添加代理配置**

在 `CHROME_USER_DATA_PATH` 之后添加：

```python
# 代理池 API（遇到反爬封锁时自动获取代理 IP）
# 示例: https://white.1024proxy.com/white/api?region=US&num=1&time=10&format=1&type=txt
PROXY_API_URL = os.getenv("PROXY_API_URL", "")
PROXY_MAX_RETRIES = int(os.getenv("PROXY_MAX_RETRIES", "3"))  # 单个 URL 最大代理轮换次数
```

- [ ] **Step 2: 在 .env.example 添加代理配置**

在 `CHROME_USER_DATA_PATH=` 后添加：

```env
# ── 代理池（遇到反爬封锁时自动获取代理 IP，留空则不使用）──
# 1024proxy API 地址（完整 URL 含参数，返回 ip:port 格式）
PROXY_API_URL=https://white.1024proxy.com/white/api?region=US&num=1&time=10&format=1&type=txt
PROXY_MAX_RETRIES=3
```

- [ ] **Step 3: Commit**

```bash
git add qbu_crawler/config.py .env.example
git commit -m "feat(config): add proxy pool configuration"
```

---

### Task 2: ProxyPool (`proxy.py`)

**Files:**
- Create: `qbu_crawler/proxy.py`
- Create: `tests/test_proxy.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_proxy.py
import time
from unittest.mock import patch, MagicMock
import pytest

from qbu_crawler.proxy import ProxyPool, get_proxy_pool


class TestProxyPool:
    def test_get_fetches_from_api(self):
        """首次 get() 应调用 API 获取代理"""
        pool = ProxyPool("https://example.com/api?region=US&num=1&time=10&format=1&type=txt")
        with patch("qbu_crawler.proxy.requests.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                text="105.33.13.23:8080\n"
            )
            proxy = pool.get()
            assert proxy == "105.33.13.23:8080"
            mock_get.assert_called_once()

    def test_get_returns_cached(self):
        """TTL 内 get() 应返回缓存，不重复调用 API"""
        pool = ProxyPool("https://example.com/api?region=US&num=1&time=10&format=1&type=txt")
        with patch("qbu_crawler.proxy.requests.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200, text="1.2.3.4:8080\n")
            p1 = pool.get()
            p2 = pool.get()
            assert p1 == p2
            assert mock_get.call_count == 1

    def test_rotate_fetches_new(self):
        """rotate() 应强制获取新 IP"""
        pool = ProxyPool("https://example.com/api?region=US&num=1&time=10&format=1&type=txt")
        with patch("qbu_crawler.proxy.requests.get") as mock_get:
            mock_get.side_effect = [
                MagicMock(status_code=200, text="1.1.1.1:8080\n"),
                MagicMock(status_code=200, text="2.2.2.2:9090\n"),
            ]
            p1 = pool.get()
            p2 = pool.rotate()
            assert p1 == "1.1.1.1:8080"
            assert p2 == "2.2.2.2:9090"

    def test_get_returns_none_on_api_error(self):
        """API 异常时 get() 返回 None"""
        pool = ProxyPool("https://example.com/api?region=US&num=1&time=10&format=1&type=txt")
        with patch("qbu_crawler.proxy.requests.get", side_effect=Exception("timeout")):
            assert pool.get() is None

    def test_get_auto_refreshes_on_expiry(self):
        """TTL 过期后 get() 应自动刷新"""
        pool = ProxyPool("https://example.com/api?region=US&num=1&time=10&format=1&type=txt")
        with patch("qbu_crawler.proxy.requests.get") as mock_get:
            mock_get.side_effect = [
                MagicMock(status_code=200, text="1.1.1.1:8080\n"),
                MagicMock(status_code=200, text="3.3.3.3:7070\n"),
            ]
            pool.get()
            # 手动过期
            pool._expires_at = time.time() - 1
            p2 = pool.get()
            assert p2 == "3.3.3.3:7070"
            assert mock_get.call_count == 2


class TestGetProxyPool:
    def test_returns_none_when_no_url(self, monkeypatch):
        """未配置 PROXY_API_URL 时返回 None"""
        import qbu_crawler.proxy as proxy_mod
        monkeypatch.setattr(proxy_mod, "_pool", None)
        monkeypatch.setattr("qbu_crawler.config.PROXY_API_URL", "")
        assert get_proxy_pool() is None

    def test_returns_pool_when_configured(self, monkeypatch):
        """配置了 PROXY_API_URL 时返回 ProxyPool 实例"""
        import qbu_crawler.proxy as proxy_mod
        monkeypatch.setattr(proxy_mod, "_pool", None)
        monkeypatch.setattr("qbu_crawler.config.PROXY_API_URL", "https://example.com/api")
        pool = get_proxy_pool()
        assert isinstance(pool, ProxyPool)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_proxy.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'qbu_crawler.proxy'`

- [ ] **Step 3: Write the implementation**

```python
# qbu_crawler/proxy.py
"""代理池管理 — 从 API 获取代理 IP，支持缓存和轮换。

典型 API（1024proxy）:
  https://white.1024proxy.com/white/api?region=US&num=1&time=10&format=1&type=txt
  返回: 105.33.13.23:8080
"""

import logging
import re
import threading
import time

import requests

from qbu_crawler import config

logger = logging.getLogger(__name__)


class ProxyPool:
    def __init__(self, api_url: str):
        self._api_url = api_url
        self._lock = threading.Lock()
        self._current: str | None = None
        self._expires_at: float = 0
        # 从 API URL 解析会话时长（time 参数），用于 TTL
        self._session_minutes = self._parse_session_time(api_url)

    @staticmethod
    def _parse_session_time(api_url: str) -> int:
        """从 API URL 的 time 参数解析会话时长（分钟），默认 10"""
        m = re.search(r'[?&]time=(\d+)', api_url)
        return int(m.group(1)) if m else 10

    def get(self) -> str | None:
        """获取当前代理（未过期则返回缓存，否则重新获取）"""
        with self._lock:
            if self._current and time.time() < self._expires_at:
                return self._current
            return self._fetch()

    def rotate(self) -> str | None:
        """强制获取新代理 IP"""
        with self._lock:
            return self._fetch()

    def _fetch(self) -> str | None:
        """调用 API 获取新的代理 IP"""
        try:
            resp = requests.get(self._api_url, timeout=10)
            resp.raise_for_status()
            ip_port = resp.text.strip().split('\n')[0].strip()
            if not ip_port or ':' not in ip_port:
                logger.error(f"[代理] API 返回格式异常: {resp.text!r}")
                return None
            self._current = ip_port
            # TTL = 会话时长 - 30秒缓冲（提前刷新避免过期瞬间还在用）
            self._expires_at = time.time() + max((self._session_minutes * 60) - 30, 60)
            logger.info(f"[代理] 获取新 IP: {ip_port} (有效 {self._session_minutes} 分钟)")
            return self._current
        except Exception as e:
            logger.error(f"[代理] API 请求失败: {e}")
            return None


# ── 单例 ──────────────────────────────────────
_pool: ProxyPool | None = None
_pool_lock = threading.Lock()


def get_proxy_pool() -> ProxyPool | None:
    """获取全局 ProxyPool 单例，未配置则返回 None"""
    global _pool
    if not config.PROXY_API_URL:
        return None
    with _pool_lock:
        if _pool is None:
            _pool = ProxyPool(config.PROXY_API_URL)
    return _pool
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_proxy.py -v
```

Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/proxy.py tests/test_proxy.py
git commit -m "feat(proxy): add ProxyPool with API fetching, caching and rotation"
```

---

### Task 3: BaseScraper 集成代理 (`base.py`)

**Files:**
- Modify: `qbu_crawler/scrapers/base.py`

- [ ] **Step 1: 添加 `_create_browser` 方法**

替换 `__init__` 中直接创建浏览器的逻辑，支持可选代理参数：

```python
# __init__ 改为:
def __init__(self):
    if HEADLESS and not _has_display():
        _ensure_virtual_display()
    self._use_user_data = bool(CHROME_USER_DATA_PATH)
    self._proxy = None  # 当前使用的代理 (ip:port)
    if self._use_user_data:
        self.browser = self._launch_with_user_data()
    else:
        self.browser = self._create_browser()
    self._scrape_count = 0

def _create_browser(self, proxy: str | None = None) -> Chromium:
    """创建浏览器实例，可选代理"""
    options = self._build_options()
    if proxy:
        options.set_argument(f'--proxy-server=http://{proxy}')
    return Chromium(options)
```

- [ ] **Step 2: 修改 `_maybe_restart_browser` 使用 `_create_browser`**

```python
def _maybe_restart_browser(self):
    if self._use_user_data:
        return
    if RESTART_EVERY and self._scrape_count > 0 and self._scrape_count % RESTART_EVERY == 0:
        print(f"  [优化] 已抓取 {self._scrape_count} 个产品，重启浏览器释放内存")
        try:
            self.browser.quit()
        except Exception:
            pass
        self.browser = self._create_browser(proxy=self._proxy)
```

- [ ] **Step 3: 添加 `_is_blocked` 方法**

```python
@staticmethod
def _is_blocked(tab) -> bool:
    """检测页面是否被反爬系统封锁（Akamai / Cloudflare）"""
    try:
        title = tab.title or ""
        url = tab.url or ""
        # Akamai: "Access Denied" + errors.edgesuite.net
        if "Access Denied" in title:
            return True
        if "errors.edgesuite.net" in url:
            return True
        # Cloudflare: challenge 页面
        if "Just a moment" in title and "cloudflare" in (tab.html or "").lower()[:2000]:
            return True
        return False
    except Exception:
        return False
```

- [ ] **Step 4: 添加 `_get_page` 方法 — 核心：导航 + 封锁检测 + 代理重试**

```python
def _get_page(self, url: str):
    """导航到 URL，遇到封锁自动切换代理重试。
    返回已加载页面的 tab 对象。调用者应使用返回的 tab 替代之前的引用。
    """
    from qbu_crawler.proxy import get_proxy_pool
    from qbu_crawler.config import PROXY_MAX_RETRIES

    tab = self.browser.latest_tab
    tab.get(url)

    if not self._is_blocked(tab):
        return tab

    # ── 触发代理重试 ──
    pool = get_proxy_pool()
    if not pool:
        logger.error("[反爬] Access Denied 且未配置代理池 (PROXY_API_URL)")
        raise RuntimeError(
            f"页面被反爬系统封锁: {url}。"
            "请配置 PROXY_API_URL 环境变量启用代理池。"
        )

    for attempt in range(PROXY_MAX_RETRIES):
        # 首次用 get()（可能返回缓存），后续用 rotate() 强制换 IP
        proxy = pool.get() if (attempt == 0 and not self._proxy) else pool.rotate()
        if not proxy:
            logger.error(f"[反爬] 无法获取代理 IP (attempt {attempt + 1})")
            continue

        self._proxy = proxy
        logger.warning(
            f"[反爬] Access Denied → 代理 {proxy} (attempt {attempt + 1}/{PROXY_MAX_RETRIES})"
        )

        try:
            self.browser.quit()
        except Exception:
            pass
        self.browser = self._create_browser(proxy=proxy)
        tab = self.browser.latest_tab
        tab.get(url)

        if not self._is_blocked(tab):
            logger.info(f"[反爬] 代理 {proxy} 成功")
            return tab

    raise RuntimeError(
        f"页面被反爬系统封锁，已尝试 {PROXY_MAX_RETRIES} 个代理均失败: {url}"
    )
```

- [ ] **Step 5: Commit**

```bash
git add qbu_crawler/scrapers/base.py
git commit -m "feat(base): add proxy retry on Access Denied detection"
```

---

### Task 4: 各站点 Scraper 接入 (`basspro.py`, `waltons.py`, `meatyourmaker.py`)

**Files:**
- Modify: `qbu_crawler/scrapers/basspro.py:62-63, 167-168`
- Modify: `qbu_crawler/scrapers/waltons.py:52, 380, 417`
- Modify: `qbu_crawler/scrapers/meatyourmaker.py:31, 265`

改动规则：所有 `tab.get(url)` 的**首次导航**替换为 `tab = self._get_page(url)`。
翻页 click 不需要替换（click 不经过 tab.get）。

- [ ] **Step 1: 修改 basspro.py**

`scrape()` 方法 (line 62-63):
```python
# Before:
tab = self.browser.latest_tab
tab.get(url)

# After:
tab = self._get_page(url)
```

`collect_product_urls()` 方法 (line 167-168):
```python
# Before:
tab = self.browser.latest_tab
tab.get(category_url)

# After:
tab = self._get_page(category_url)
```

- [ ] **Step 2: 修改 waltons.py**

`scrape()` 方法 (line 51-52):
```python
# Before:
tab = self.browser.latest_tab
tab.get(url)

# After:
tab = self._get_page(url)
```

`collect_product_urls()` 方法 (line 380-381):
```python
# Before:
tab = self.browser.latest_tab
tab.get(start_url)

# After:
tab = self._get_page(start_url)
```

翻页导航 (line 417):
```python
# Before:
tab.get(next_href)

# After:
tab = self._get_page(next_href)
```

- [ ] **Step 3: 修改 meatyourmaker.py**

`scrape()` 方法 (line 30-31):
```python
# Before:
tab = self.browser.latest_tab
tab.get(url)

# After:
tab = self._get_page(url)
```

`collect_product_urls()` 方法 (line 264-265):
```python
# Before:
tab = self.browser.latest_tab
tab.get(category_url)

# After:
tab = self._get_page(category_url)
```

翻页导航 (line 302):
```python
# Before:
tab.get(next_url)

# After:
tab = self._get_page(next_url)
```

- [ ] **Step 4: Commit**

```bash
git add qbu_crawler/scrapers/basspro.py qbu_crawler/scrapers/waltons.py qbu_crawler/scrapers/meatyourmaker.py
git commit -m "feat(scrapers): integrate proxy fallback in all site scrapers"
```

---

### Task 5: 更新文档

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: 更新 CLAUDE.md 配置表和架构说明**

在「通用配置项」表格中添加代理相关配置行。
在「稳定性机制」列表中添加代理降级说明。

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add proxy pool configuration and architecture notes"
```

---

## 手动验证清单

部署后按以下步骤验证：

1. **设置 .env**: 添加 `PROXY_API_URL=https://white.1024proxy.com/white/api?region=US&num=1&time=10&format=1&type=txt`
2. **服务器测试 Bass Pro**:
   ```bash
   uv run python main.py https://www.basspro.com/shop/en/cabelas-heavy-duty-20-lb-meat-mixer
   ```
   预期：首次 Access Denied → 日志显示 `[反爬] Access Denied → 代理 x.x.x.x:port` → 代理成功 → 正常抓取
3. **验证 Walton's 不触发代理**: 如果 Walton's 在服务器上直连正常，代理逻辑不应触发
4. **验证代理轮换**: 连续抓取多个 Bass Pro URL，观察代理是否在 TTL 内复用
