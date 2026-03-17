import json
import logging
import os
import sys
from urllib.parse import urlparse

from DrissionPage import Chromium, ChromiumOptions
from config import (
    HEADLESS, PAGE_LOAD_TIMEOUT, LOAD_MODE, NO_IMAGES,
    RETRY_TIMES, RETRY_INTERVAL, REQUEST_DELAY, RESTART_EVERY,
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


class BaseScraper:
    def __init__(self):
        if HEADLESS and not _has_display():
            _ensure_virtual_display()
        self._options = self._build_options()
        self.browser = Chromium(self._options)
        self._scrape_count = 0

    @staticmethod
    def _build_options() -> ChromiumOptions:
        options = ChromiumOptions()
        options.auto_port()  # 每个实例使用独立端口，防止并行任务共享浏览器
        if HEADLESS:
            if _has_display():
                # Windows / Linux 桌面：正常无头模式
                options.headless()
            # else: Linux 服务器无显示 → 已通过 _ensure_virtual_display() 启动 Xvfb，
            #        使用有头模式运行在虚拟显示上，完全绕过反无头检测
            options.set_argument('--window-size=1920,1080')
        else:
            options.set_argument('--start-maximized')
        if NO_IMAGES:
            options.no_imgs(True)
        options.set_load_mode(LOAD_MODE)
        options.set_retry(times=RETRY_TIMES, interval=RETRY_INTERVAL)
        options.set_timeouts(base=10, page_load=PAGE_LOAD_TIMEOUT)
        # 自动拒绝所有浏览器权限弹窗（位置、通知等），防止原生弹窗遮挡 DOM 交互
        options.set_argument('--deny-permission-prompts')
        # 禁用自动化检测特征，绕过 Akamai/Cloudflare 等反爬 bot 检测
        options.set_argument('--disable-blink-features=AutomationControlled')
        return options

    def _maybe_restart_browser(self):
        """定期重启浏览器，防止长时间运行内存泄漏"""
        if RESTART_EVERY and self._scrape_count > 0 and self._scrape_count % RESTART_EVERY == 0:
            print(f"  [优化] 已抓取 {self._scrape_count} 个产品，重启浏览器释放内存")
            try:
                self.browser.quit()
            except Exception:
                pass
            self.browser = Chromium(self._options)

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

    def _increment_and_delay(self, tab):
        """递增抓取计数并执行随机延迟"""
        self._scrape_count += 1
        if REQUEST_DELAY:
            tab.wait(REQUEST_DELAY[0], REQUEST_DELAY[1])

    def _process_review_images(self, reviews: list) -> list:
        """下载评论图片到 MinIO，将 BV URL 替换为 MinIO URL"""
        from minio_client import upload_image

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
