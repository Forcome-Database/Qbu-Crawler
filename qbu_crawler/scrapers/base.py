import json
import logging
import os
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse

from DrissionPage import Chromium, ChromiumOptions
from qbu_crawler.config import (
    HEADLESS, PAGE_LOAD_TIMEOUT, NO_IMAGES,
    RETRY_TIMES, RETRY_INTERVAL, REQUEST_DELAY, RESTART_EVERY,
    CHROME_USER_DATA_PATH,
)

logger = logging.getLogger(__name__)


def _has_display() -> bool:
    """检测当前环境是否有可用的显示服务（X11/Wayland/Windows）"""
    if sys.platform == 'win32':
        return True
    return bool(os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'))


def _ensure_virtual_display():
    """Linux 无显示环境时，自动启动 Xvfb 虚拟显示。
    需要安装：apt install xvfb + pip install PyVirtualDisplay
    """
    if sys.platform == 'win32' or _has_display():
        return
    try:
        from pyvirtualdisplay import Display
        display = Display(visible=0, size=(1920, 1080))
        display.start()
        logger.info(f"已启动虚拟显示 (DISPLAY={os.environ.get('DISPLAY')})")
    except ImportError:
        logger.warning(
            "Linux 无显示环境且未安装 PyVirtualDisplay，"
            "请运行: pip install PyVirtualDisplay && apt install xvfb"
        )


def _find_chrome() -> str:
    """查找 Chrome 可执行文件路径"""
    if sys.platform == 'win32':
        for path in [
            os.path.expandvars(r'%ProgramFiles%\Google\Chrome\Application\chrome.exe'),
            os.path.expandvars(r'%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe'),
            os.path.expandvars(r'%LocalAppData%\Google\Chrome\Application\chrome.exe'),
        ]:
            if os.path.isfile(path):
                return path
    else:
        for name in ['google-chrome', 'google-chrome-stable', 'chromium-browser', 'chromium']:
            import shutil
            path = shutil.which(name)
            if path:
                return path
    raise FileNotFoundError("Chrome executable not found")


class BaseScraper:
    # 用户数据模式下 Chrome 使用的固定调试端口
    _USER_DATA_PORT = 19222

    # ── 站点级属性（子类可覆盖）──
    SITE_LOAD_MODE: str = "eager"       # 页面加载模式
    SITE_NEEDS_USER_DATA: bool = False  # 是否需要 Chrome 用户数据模式
    SITE_RESTART_SAFE: bool = True      # 浏览器重启是否安全（不丢关键 cookie）
    _user_data_lock = threading.Lock()

    def __init__(self):
        if HEADLESS and not _has_display():
            _ensure_virtual_display()
        self._use_user_data = bool(CHROME_USER_DATA_PATH) and self.SITE_NEEDS_USER_DATA
        self._proxy = None  # 当前使用的代理 (ip:port)
        self._warmed_up = False
        if self._use_user_data:
            self._proxy = self._get_initial_proxy()
            self.browser = self._launch_with_user_data(proxy=self._proxy)
        else:
            self.browser = self._create_browser()
        self._scrape_count = 0

    def _create_browser(self, proxy: str | None = None) -> Chromium:
        """创建浏览器实例，可选代理"""
        options = self._build_options()
        if proxy:
            options.set_argument(f'--proxy-server=http://{proxy}')
        return Chromium(options)

    def _build_options(self) -> ChromiumOptions:
        options = ChromiumOptions()
        options.auto_port()  # 每个实例使用独立端口，防止并行任务共享浏览器
        if HEADLESS:
            if _has_display():
                options.headless()
            options.set_argument('--window-size=1920,1080')
        else:
            options.set_argument('--start-maximized')
        if NO_IMAGES:
            options.no_imgs(True)
        options.set_load_mode(self.SITE_LOAD_MODE)
        options.set_retry(times=RETRY_TIMES, interval=RETRY_INTERVAL)
        options.set_timeouts(base=10, page_load=PAGE_LOAD_TIMEOUT)
        options.set_argument('--deny-permission-prompts')
        options.set_argument('--disable-blink-features=AutomationControlled')
        return options

    @classmethod
    def _kill_user_data_chrome(cls, port: int):
        """关闭占用指定调试端口的 Chrome 进程"""
        try:
            browser = Chromium(port)
            browser.quit()
        except Exception:
            pass

    @classmethod
    def _try_connect_chrome(cls, port: int) -> "Chromium | None":
        """连接到指定端口的 Chrome，主动验证 socket + DevTools HTTP 都活着。
        失败返回 None。避免 DrissionPage Chromium() 是 lazy 的导致返回伪 browser。"""
        import socket
        import urllib.request
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=1):
                pass
        except OSError:
            return None
        try:
            with urllib.request.urlopen(
                f'http://127.0.0.1:{port}/json/version', timeout=2,
            ) as resp:
                if resp.status != 200:
                    return None
        except Exception:
            return None
        try:
            browser = Chromium(port)
            cls._cleanup_tabs(browser)
            return browser
        except Exception:
            return None

    @classmethod
    def _launch_with_user_data(cls, proxy: str | None = None) -> Chromium:
        """使用 Chrome 用户数据启动浏览器，可选代理。
        Chrome 支持 --user-data-dir + --proxy-server 同时使用，
        代理通过 HTTP CONNECT 隧道，JA3 指纹不变。"""
        port = cls._USER_DATA_PORT

        if proxy:
            # 代理是启动参数，切换代理必须重启 Chrome
            cls._kill_user_data_chrome(port)
            time.sleep(1)  # 等旧 Chrome 释放 user_data 文件锁
        else:
            # 无代理时尝试复用已运行的 Chrome
            browser = cls._try_connect_chrome(port)
            if browser is not None:
                return browser

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
        # Launch Chrome. Drain stderr continuously in a daemon thread so the
        # ~64KB pipe buffer cannot block Chrome in write() and mask a hung
        # startup as a silent 60s timeout.
        proc = subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        stderr_buf: list[bytes] = []
        stderr_buf_lock = threading.Lock()

        def _drain_stderr(pipe, buf, lock):
            try:
                for chunk in iter(lambda: pipe.read(4096), b""):
                    with lock:
                        buf.append(chunk)
                        # Cap at 1 MB by dropping oldest chunks
                        total = sum(len(c) for c in buf)
                        while total > 1_000_000 and len(buf) > 1:
                            dropped = buf.pop(0)
                            total -= len(dropped)
            except Exception:
                pass

        drain_thread = threading.Thread(
            target=_drain_stderr,
            args=(proc.stderr, stderr_buf, stderr_buf_lock),
            daemon=True,
        )
        drain_thread.start()

        for _ in range(60):
            time.sleep(1)
            if proc.poll() is not None:
                drain_thread.join(timeout=1)
                with stderr_buf_lock:
                    tail = (b"".join(stderr_buf) or b"").decode(
                        "utf-8", errors="ignore",
                    )[-500:]
                raise RuntimeError(
                    f"Chrome exited early (code={proc.returncode}). "
                    f"Likely cause: user_data_dir locked by another Chrome instance. "
                    f"Close all Chrome windows using profile "
                    f"{CHROME_USER_DATA_PATH!r} and retry. stderr: {tail}"
                )
            browser = cls._try_connect_chrome(port)
            if browser is not None:
                return browser
        raise RuntimeError(
            f"Chrome with user data failed to start on port {port} within 60s. "
            f"Profile may be too large; check {CHROME_USER_DATA_PATH!r}."
        )

    @staticmethod
    def _cleanup_tabs(browser):
        """关闭多余标签，只保留一个。防止用户数据 Chrome 会话恢复导致标签堆积。"""
        try:
            tabs = browser.get_tabs()
            if len(tabs) <= 1:
                return
            # 保留最后一个标签，关闭其余
            for tab_id in tabs[:-1]:
                try:
                    tab = browser.get_tab(tab_id)
                    tab.close()
                except Exception:
                    pass
            logger.info(f"[清理] 关闭 {len(tabs) - 1} 个多余标签")
        except Exception:
            pass

    def _warm_up(self):
        """访问站点首页完成反爬 challenge（如 Akamai _abck cookie）。
        子类可覆盖提供站点特定的预热逻辑。默认不做任何事。"""
        pass

    def _get_initial_proxy(self) -> str | None:
        """初始化时获取代理 IP（如果站点需要代理）"""
        from qbu_crawler.proxy import get_proxy_pool
        pool = get_proxy_pool()
        if pool:
            proxy = pool.get()
            if proxy:
                logger.info(f"[初始化] 用户数据模式 + 代理: {proxy}")
                return proxy
        return None

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

    @staticmethod
    def _check_url_match(tab, expected_url: str):
        """检查导航后的实际 URL 是否匹配预期，防止并行任务导致数据错位。
        允许站点内分类路径重定向（如 /process/product → /nwtf/product），
        只要域名和最终产品标识（路径末段）一致即可。"""
        actual_url = tab.url
        expected_parsed = urlparse(expected_url)
        actual_parsed = urlparse(actual_url)
        # 域名必须一致
        if expected_parsed.netloc != actual_parsed.netloc:
            logger.warning(f"URL 域名不匹配！预期: {expected_url} → 实际: {actual_url}")
            raise RuntimeError(
                f"页面域名不匹配（可能被重定向到其他站点）: "
                f"预期 {expected_url}, 实际 {actual_url}"
            )
        # 最终路径段（产品标识）必须一致，允许中间分类路径变化
        expected_slug = expected_parsed.path.rstrip("/").rsplit("/", 1)[-1]
        actual_slug = actual_parsed.path.rstrip("/").rsplit("/", 1)[-1]
        if expected_slug != actual_slug:
            logger.warning(f"URL 产品标识不匹配！预期: {expected_url} → 实际: {actual_url}")
            raise RuntimeError(
                f"页面产品标识不匹配（可能被重定向或并行任务干扰）: "
                f"预期 {expected_url}, 实际 {actual_url}"
            )
        if expected_parsed.path != actual_parsed.path:
            logger.info(f"URL 路径重定向: {expected_parsed.path} → {actual_parsed.path}（产品标识一致，继续）")

    @staticmethod
    def _is_cloudflare(tab) -> bool:
        """检测当前页面是否是 Cloudflare challenge/Turnstile 页面"""
        try:
            title = tab.title or ""
            html_head = (tab.html or "")[:5000].lower()
            # 标题匹配（多语言）
            if ("just a moment" in title.lower() or "请稍候" in title) \
                    and "cloudflare" in html_head:
                return True
            # Turnstile 页面结构特征（不依赖标题）
            if "challenges.cloudflare.com" in html_head:
                return True
            if "cf-turnstile" in html_head or "cf-chl-widget" in html_head:
                return True
            return False
        except Exception:
            return False

    @staticmethod
    def _is_blocked(tab) -> bool:
        """检测页面是否被反爬系统封锁（Akamai / Cloudflare / Chrome 错误）"""
        try:
            title = tab.title or ""
            url = tab.url or ""
            html_head = (tab.html or "")[:5000].lower()
            # Chrome 内部错误页面（代理连接失败、DNS 失败、网络不可达等）
            if url.startswith("chrome-error://"):
                return True
            if "id=\"main-frame-error\"" in html_head or "neterror" in html_head:
                return True
            # Akamai: "Access Denied" + errors.edgesuite.net
            if "Access Denied" in title:
                return True
            if "errors.edgesuite.net" in url:
                return True
            # Cloudflare（所有形态）
            if ("just a moment" in title.lower() or "请稍候" in title):
                return True
            if "challenges.cloudflare.com" in html_head:
                return True
            if "cf-turnstile" in html_head or "cf-chl-widget" in html_head:
                return True
            return False
        except Exception:
            return False

    def _wait_and_solve_cloudflare(self, tab, timeout=20) -> bool:
        """Cloudflare 等待 + 自动解决。

        完整流程：
        1. 等待 Cloudflare 自动验证（"正在验证..." 阶段，最多 10 秒）
        2. 如果自动通过 → 返回 True
        3. 如果出现 Turnstile 复选框 → 尝试点击
        4. 等待验证完成 → 返回结果

        必须在 _is_blocked() 返回 True 后调用。
        """
        if not self._is_cloudflare(tab):
            return False

        logger.info("[反爬] 检测到 Cloudflare challenge，等待自动验证...")

        # ── 阶段1：等待自动验证（Cloudflare 先显示 "正在验证..." spinner）──
        for i in range(10):
            tab.wait(1)
            if not self._is_cloudflare(tab):
                logger.info(f"[反爬] Cloudflare 自动验证通过（{i + 1}s）")
                return True

        # ── 阶段2：自动验证未通过，尝试点击 Turnstile 复选框 ──
        logger.info("[反爬] Cloudflare 自动验证未通过，尝试点击 Turnstile...")

        clicked = False

        # 方法1: DrissionPage CDP 穿透 closed shadow root
        try:
            checkbox = tab.ele('@type=checkbox', timeout=3)
            if checkbox:
                checkbox.click()
                logger.info("[反爬] CDP 穿透找到 checkbox 并点击")
                clicked = True
        except Exception:
            pass

        # 方法2: 坐标定位点击
        if not clicked:
            try:
                pos = tab.run_js("""
                    // Turnstile iframe 在 closed shadow root 内，
                    // 但容器 div (display:grid) 可访问
                    const divs = document.querySelectorAll('div');
                    for (const d of divs) {
                        const style = window.getComputedStyle(d);
                        const rect = d.getBoundingClientRect();
                        if (style.display === 'grid'
                            && rect.height > 50 && rect.height < 100
                            && rect.width > 200) {
                            return JSON.stringify({
                                x: rect.left, y: rect.top,
                                w: rect.width, h: rect.height
                            });
                        }
                    }
                    return null;
                """)
                if pos:
                    data = json.loads(pos)
                    click_x = int(data['x']) + 30
                    click_y = int(data['y'] + data['h'] / 2)
                    tab.actions.move(click_x, click_y, duration=0.3).click()
                    logger.info(f"[反爬] 坐标点击 Turnstile ({click_x}, {click_y})")
                    clicked = True
            except Exception as e:
                logger.warning(f"[反爬] Turnstile 坐标点击失败: {e}")

        if not clicked:
            logger.warning("[反爬] 未能找到 Turnstile 复选框")
            return False

        # ── 阶段3：等待点击后的验证完成 ──
        remaining = max(timeout - 10, 10)
        for i in range(remaining):
            tab.wait(1)
            if not self._is_cloudflare(tab):
                logger.info(f"[反爬] Cloudflare Turnstile 验证通过（点击后 {i + 1}s）")
                return True

        logger.warning("[反爬] Cloudflare Turnstile 点击后验证未通过")
        return False

    @staticmethod
    def _site_needs_proxy(url: str) -> bool:
        """检查 URL 对应的站点是否配置为直接使用代理"""
        from qbu_crawler.config import PROXY_SITES
        if not PROXY_SITES:
            return False
        try:
            from qbu_crawler.scrapers import get_site_key
            return get_site_key(url) in PROXY_SITES
        except ValueError:
            return False

    def _get_page(self, url: str):
        """导航到 URL，根据站点属性选择反爬策略。

        三层策略：
        1. 用户数据 + 代理（SITE_NEEDS_USER_DATA 站点）：Lock 串行，保留 cookie
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

        # Cloudflare: 等待自动验证 + 尝试点击 Turnstile，不需要换代理
        if self._wait_and_solve_cloudflare(tab):
            if self._proxy:
                pool = get_proxy_pool()
                if pool:
                    pool.mark_good(self._proxy)
            return tab

        # 被封 → 轮换代理，重启用户数据 Chrome（保留 cookie + 新 IP）
        pool = get_proxy_pool()
        if not pool:
            raise RuntimeError(
                f"用户数据模式下仍被封锁: {url}。"
                "请手动用 Chrome 访问目标站点刷新 cookie，"
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

        # Cloudflare: 等待自动验证 + 尝试点击 Turnstile，不需要换代理
        if self._wait_and_solve_cloudflare(tab):
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

    @staticmethod
    def _validate_product(result: dict, url: str):
        """校验抓取结果的关键字段，防止空数据或反爬页面数据被当作成功保存"""
        product = result.get("product", {})
        name = product.get("name") or ""
        sku = product.get("sku")
        price = product.get("price")

        # name 和 sku 都为空 → 完全没提取到数据
        if not name and not sku:
            raise RuntimeError(
                f"抓取结果无效（name 和 sku 均为空），页面可能未正确加载: {url}"
            )
        # name 是反爬页面特征 → Cloudflare/Akamai 页面被当产品提取了
        blocked_names = {"waltons.com", "basspro.com", "meatyourmaker.com",
                         "access denied", "just a moment", "请稍候", "执行安全验证"}
        if name.lower().strip() in blocked_names:
            raise RuntimeError(
                f"抓取结果无效（name 为反爬页面标识 '{name}'），Cloudflare/Akamai 未通过: {url}"
            )
        # 有 name 但没有 sku 和 price → 可能是不完整的页面
        if name and not sku and price is None:
            raise RuntimeError(
                f"抓取结果不完整（有 name 但 sku 和 price 均为空），页面可能未正确加载: {url}"
            )

    def _increment_and_delay(self, tab):
        """递增抓取计数并执行随机延迟"""
        self._scrape_count += 1
        if REQUEST_DELAY:
            tab.wait(REQUEST_DELAY[0], REQUEST_DELAY[1])

    def _process_review_images(self, reviews: list) -> list:
        """下载评论图片到 MinIO，将 BV URL 替换为 MinIO URL"""
        from qbu_crawler.minio_client import upload_image

        for review in reviews:
            bv_urls = review.get("images", [])
            if not bv_urls:
                review["images"] = None
                continue
            minio_urls = []
            for url in bv_urls:
                minio_url = upload_image(url)
                if minio_url:
                    minio_urls.append(minio_url)
            review["images"] = json.dumps(minio_urls) if minio_urls else None
        return reviews

    @staticmethod
    def _to_float(val) -> float | None:
        if val is None:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _to_int(val) -> int | None:
        if val is None:
            return None
        try:
            return int(val)
        except (ValueError, TypeError):
            return None

    def close(self):
        try:
            self.browser.quit()
        except Exception:
            pass
