"""代理池管理 — 黑白名单 + API 获取，智能代理 IP 调度。

工作流:
  1. 优先使用白名单 IP（曾经成功的代理）
  2. 白名单无可用 → 从 API 获取新 IP
  3. API 返回黑名单 IP → 自动重新获取
  4. 代理被封 → 加入黑名单，从白名单移除
  5. 代理成功 → 加入白名单

黑名单按 ip:port 精确匹配（同 IP 不同端口视为不同代理通道）。
白名单按 ip:port 存储（Chrome --proxy-server 需要完整地址），带 TTL 过期。
"""

import logging
import re
import threading
import time
import uuid
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import requests

from qbu_crawler import config

logger = logging.getLogger(__name__)


class ProxyPool:
    # API 连续返回黑名单 IP 的最大重试次数
    _MAX_FETCH_RETRIES = 5

    def __init__(self, api_url: str):
        self._api_url = api_url
        self._lock = threading.Lock()
        self._session_seconds = self._parse_session_time(api_url) * 60
        # 黑名单：被封的代理 ip:port（精确匹配，同 IP 不同端口可独立使用）
        self._blacklist: set[str] = set()
        # 白名单：成功过的代理 ip:port -> 获取时间戳
        self._whitelist: dict[str, float] = {}

    @staticmethod
    def _parse_session_time(api_url: str) -> int:
        """从 API URL 的 time 参数解析会话时长（分钟），默认 10"""
        m = re.search(r'[?&]time=(\d+)', api_url)
        return int(m.group(1)) if m else 10

    @staticmethod
    def _ip_of(ip_port: str) -> str:
        """提取 ip:port 中的 IP 部分"""
        return ip_port.rsplit(':', 1)[0]

    @staticmethod
    def _append_sid(api_url: str) -> str:
        """给 API URL 追加随机 sid 参数，强制分配新会话/新 IP"""
        parsed = urlparse(api_url)
        qs = parse_qs(parsed.query)
        qs["sid"] = [uuid.uuid4().hex[:8]]
        return urlunparse(parsed._replace(query=urlencode(qs, doseq=True)))

    def get(self) -> str | None:
        """获取代理：白名单优先 → API 获取新 IP"""
        with self._lock:
            proxy = self._pick_from_whitelist()
            if proxy:
                return proxy
            return self._fetch_new()

    def rotate(self, current_proxy: str | None = None) -> str | None:
        """指定代理被封，拉黑后获取新代理"""
        with self._lock:
            if current_proxy:
                self._add_to_blacklist(current_proxy)
            proxy = self._pick_from_whitelist()
            if proxy:
                return proxy
            return self._fetch_new()

    def mark_good(self, ip_port: str):
        """标记代理成功 → 加入白名单"""
        with self._lock:
            if ip_port in self._blacklist:
                return  # 已被拉黑的不加白名单
            if ip_port not in self._whitelist:
                self._whitelist[ip_port] = time.time()
                logger.info(
                    f"[代理] 白名单 +{ip_port} "
                    f"(白名单 {len(self._whitelist)}, 黑名单 {len(self._blacklist)})"
                )

    def _add_to_blacklist(self, ip_port: str):
        """拉黑代理（按 ip:port 精确匹配），同时从白名单移除"""
        self._blacklist.add(ip_port)
        self._whitelist.pop(ip_port, None)
        logger.info(
            f"[代理] 黑名单 +{ip_port} "
            f"(白名单 {len(self._whitelist)}, 黑名单 {len(self._blacklist)})"
        )

    def _pick_from_whitelist(self) -> str | None:
        """从白名单中选取一个未过期、未拉黑的代理"""
        now = time.time()
        expired = []
        result = None
        for ip_port, obtained_at in self._whitelist.items():
            # 过期检查（会话时长 - 30秒缓冲）
            if now - obtained_at > self._session_seconds - 30:
                expired.append(ip_port)
                continue
            if ip_port in self._blacklist:
                expired.append(ip_port)
                continue
            if result is None:
                result = ip_port
        # 清理过期/拉黑条目
        for ip_port in expired:
            del self._whitelist[ip_port]
        if result:
            logger.info(f"[代理] 复用白名单: {result}")
        return result

    def _fetch_new(self) -> str | None:
        """从 API 获取新代理，跳过黑名单"""
        for attempt in range(self._MAX_FETCH_RETRIES):
            url = self._append_sid(self._api_url)
            ip_port = self._call_api(url)
            if not ip_port:
                return None
            if ip_port not in self._blacklist:
                return ip_port
            logger.warning(
                f"[代理] API 返回黑名单 IP {ip_port}，重新获取 ({attempt + 1}/{self._MAX_FETCH_RETRIES})"
            )
            time.sleep(0.5)
        logger.error(f"[代理] 连续 {self._MAX_FETCH_RETRIES} 次获取到黑名单 IP，放弃")
        return None

    @staticmethod
    def _is_valid_ip_port(text: str) -> bool:
        """验证字符串是否为合法的 ip:port 格式"""
        return bool(re.match(r'^\d{1,3}(\.\d{1,3}){3}:\d{2,5}$', text))

    def _call_api(self, api_url: str) -> str | None:
        """调用代理 API，返回 ip:port 或 None"""
        try:
            resp = requests.get(api_url, timeout=10)
            resp.raise_for_status()
            ip_port = resp.text.strip().split('\n')[0].strip()
            if not ip_port or not self._is_valid_ip_port(ip_port):
                logger.error(f"[代理] API 返回格式异常（非 ip:port）: {resp.text!r}")
                return None
            logger.info(f"[代理] API 返回: {ip_port}")
            return ip_port
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
