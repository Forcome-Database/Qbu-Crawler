import json
import logging
import os
import subprocess
import sys
import time
from urllib.parse import urlparse

from DrissionPage import Chromium, ChromiumOptions
from qbu_crawler.config import (
    HEADLESS, PAGE_LOAD_TIMEOUT, LOAD_MODE, NO_IMAGES,
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
        """检查导航后的实际 URL 是否匹配预期，防止重定向或并行任务导致数据错位"""
        actual_url = tab.url
        expected_path = urlparse(expected_url).path.rstrip("/")
        actual_path = urlparse(actual_url).path.rstrip("/")
        if expected_path != actual_path:
            logger.warning(
                f"URL 不匹配！预期: {expected_url} → 实际: {actual_url}"
            )
            raise RuntimeError(
                f"页面 URL 不匹配（可能被重定向或并行任务干扰）: "
                f"预期 {expected_url}, 实际 {actual_url}"
            )

    @staticmethod
    def _is_blocked(tab) -> bool:
        """检测页面是否被反爬系统封锁（Akamai / Cloudflare）或浏览器连接失败"""
        try:
            title = tab.title or ""
            url = tab.url or ""
            html_head = (tab.html or "")[:3000].lower()
            # Chrome 内部错误页面（代理连接失败、DNS 失败、网络不可达等）
            # Chrome 错误页面 URL 可能是 chrome-error:// 或保持原 URL 但 HTML 含 neterror
            if url.startswith("chrome-error://"):
                return True
            if "id=\"main-frame-error\"" in html_head or "neterror" in html_head:
                return True
            # Akamai: "Access Denied" + errors.edgesuite.net
            if "Access Denied" in title:
                return True
            if "errors.edgesuite.net" in url:
                return True
            # Cloudflare challenge 页面
            if "Just a moment" in title and "cloudflare" in html_head:
                return True
            return False
        except Exception:
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
        """导航到 URL，遇到封锁自动切换代理重试。

        代理调度逻辑：
        0. PROXY_SITES 中的站点 → 跳过直连，直接用代理
        1. 白名单优先 → 复用曾经成功的代理 IP
        2. 无可用白名单 → 从 API 获取新 IP（自动跳过黑名单）
        3. 被封 → 当前 IP 加入黑名单 → rotate 获取下一个
        4. 成功 → 当前 IP 加入白名单

        返回已加载页面的 tab 对象。调用者应使用返回的 tab 替代之前的引用。
        """
        from qbu_crawler.proxy import get_proxy_pool
        from qbu_crawler.config import PROXY_MAX_RETRIES

        # ── PROXY_SITES: 指定站点首次直接走代理 ──
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
            # 直连成功，或当前代理仍有效 → 标记白名单
            if self._proxy:
                pool = get_proxy_pool()
                if pool:
                    pool.mark_good(self._proxy)
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
            # 首次: get()（白名单优先）; 后续: rotate()（拉黑当前 + 换新）
            proxy = pool.get() if (attempt == 0 and not self._proxy) else pool.rotate()
            if not proxy:
                logger.error(f"[反爬] 无法获取代理 IP (attempt {attempt + 1})")
                continue

            # 跳过与当前完全相同的代理（避免无意义的浏览器重启）
            if proxy == self._proxy and attempt > 0:
                logger.warning(f"[反爬] 代理未变化 {proxy}，跳过 (attempt {attempt + 1})")
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
                logger.info(f"[反爬] 代理 {proxy} 成功 → 加入白名单")
                pool.mark_good(proxy)
                return tab

        raise RuntimeError(
            f"页面被反爬系统封锁，已尝试 {PROXY_MAX_RETRIES} 个代理均失败: {url}"
        )

    @staticmethod
    def _validate_product(result: dict, url: str):
        """校验抓取结果的关键字段，防止空数据被当作成功保存"""
        product = result.get("product", {})
        if not product.get("name") and not product.get("sku"):
            raise RuntimeError(
                f"抓取结果无效（name 和 sku 均为空），页面可能未正确加载: {url}"
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
