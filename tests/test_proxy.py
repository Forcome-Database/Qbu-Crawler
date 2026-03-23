"""Tests for proxy pool: blacklist/whitelist, API fetching, rotation, singleton."""

import time
from unittest.mock import patch, MagicMock

import pytest

from qbu_crawler.proxy import ProxyPool, get_proxy_pool


API_URL = "https://example.com/api?region=US&num=1&time=10&format=1&type=txt"


def _mock_resp(text):
    return MagicMock(status_code=200, text=text)


class TestProxyPool:
    def test_get_fetches_from_api(self):
        """无白名单时 get() 从 API 获取"""
        pool = ProxyPool(API_URL)
        with patch("qbu_crawler.proxy.requests.get") as mock_get:
            mock_get.return_value = _mock_resp("105.33.13.23:8080\n")
            proxy = pool.get()
            assert proxy == "105.33.13.23:8080"
            assert mock_get.call_count == 1

    def test_get_prefers_whitelist(self):
        """白名单有可用 IP 时优先返回，不调 API"""
        pool = ProxyPool(API_URL)
        pool.mark_good("1.2.3.4:8080")
        with patch("qbu_crawler.proxy.requests.get") as mock_get:
            proxy = pool.get()
            assert proxy == "1.2.3.4:8080"
            mock_get.assert_not_called()

    def test_whitelist_expires(self):
        """白名单 IP 过期后不再使用"""
        pool = ProxyPool(API_URL)
        pool.mark_good("1.2.3.4:8080")
        # 手动过期
        pool._whitelist["1.2.3.4:8080"] = time.time() - pool._session_seconds
        with patch("qbu_crawler.proxy.requests.get") as mock_get:
            mock_get.return_value = _mock_resp("5.6.7.8:9090\n")
            proxy = pool.get()
            assert proxy == "5.6.7.8:9090"

    def test_rotate_blacklists_current(self):
        """rotate() 将指定 IP 加入黑名单"""
        pool = ProxyPool(API_URL)
        with patch("qbu_crawler.proxy.requests.get") as mock_get:
            mock_get.return_value = _mock_resp("2.2.2.2:9090\n")
            proxy = pool.rotate(current_proxy="1.1.1.1:8080")
            assert "1.1.1.1" in pool._blacklist
            assert proxy == "2.2.2.2:9090"

    def test_rotate_removes_from_whitelist(self):
        """rotate() 拉黑时同时从白名单移除"""
        pool = ProxyPool(API_URL)
        pool.mark_good("1.1.1.1:8080")
        with patch("qbu_crawler.proxy.requests.get") as mock_get:
            mock_get.return_value = _mock_resp("3.3.3.3:7070\n")
            pool.rotate(current_proxy="1.1.1.1:8080")
            assert "1.1.1.1:8080" not in pool._whitelist
            assert "1.1.1.1" in pool._blacklist

    def test_blacklist_same_ip_different_port(self):
        """同 IP 不同端口也视为黑名单"""
        pool = ProxyPool(API_URL)
        with patch("qbu_crawler.proxy.requests.get") as mock_get:
            mock_get.side_effect = [
                _mock_resp("1.1.1.1:9090\n"),  # 同 IP 不同端口 → 黑名单
                _mock_resp("2.2.2.2:7070\n"),  # 不同 IP → 可用
            ]
            proxy = pool.rotate(current_proxy="1.1.1.1:8080")
            assert proxy == "2.2.2.2:7070"

    def test_fetch_skips_blacklisted(self):
        """API 返回黑名单 IP 时自动重新获取"""
        pool = ProxyPool(API_URL)
        pool._blacklist.add("1.1.1.1")
        with patch("qbu_crawler.proxy.requests.get") as mock_get:
            mock_get.side_effect = [
                _mock_resp("1.1.1.1:8080\n"),  # 黑名单
                _mock_resp("1.1.1.1:9090\n"),  # 黑名单（不同端口）
                _mock_resp("2.2.2.2:8080\n"),  # 可用
            ]
            proxy = pool.get()
            assert proxy == "2.2.2.2:8080"
            assert mock_get.call_count == 3

    def test_get_returns_none_on_api_error(self):
        """API 异常时返回 None"""
        pool = ProxyPool(API_URL)
        with patch("qbu_crawler.proxy.requests.get", side_effect=Exception("timeout")):
            assert pool.get() is None

    def test_mark_good_adds_to_whitelist(self):
        """mark_good 添加到白名单"""
        pool = ProxyPool(API_URL)
        pool.mark_good("1.2.3.4:8080")
        assert "1.2.3.4:8080" in pool._whitelist

    def test_mark_good_skips_blacklisted(self):
        """已拉黑的 IP 不加白名单"""
        pool = ProxyPool(API_URL)
        pool._blacklist.add("1.2.3.4")
        pool.mark_good("1.2.3.4:8080")
        assert "1.2.3.4:8080" not in pool._whitelist

    def test_whitelist_then_blacklist_flow(self):
        """完整流程：成功→白名单→后来被封→黑名单→换新"""
        pool = ProxyPool(API_URL)
        # 第一次成功
        pool.mark_good("1.1.1.1:8080")
        assert "1.1.1.1:8080" in pool._whitelist

        # 后来被封了
        with patch("qbu_crawler.proxy.requests.get") as mock_get:
            mock_get.return_value = _mock_resp("3.3.3.3:7070\n")
            proxy = pool.rotate(current_proxy="1.1.1.1:8080")
            assert proxy == "3.3.3.3:7070"
            assert "1.1.1.1" in pool._blacklist
            assert "1.1.1.1:8080" not in pool._whitelist

    def test_parse_session_time_default(self):
        """无 time 参数时默认 10 分钟"""
        pool = ProxyPool("https://example.com/api?region=US")
        assert pool._session_seconds == 600

    def test_parse_session_time_custom(self):
        """解析 URL 中的 time 参数"""
        pool = ProxyPool("https://example.com/api?region=US&time=5&format=1")
        assert pool._session_seconds == 300

    def test_append_sid_unique(self):
        """_append_sid 每次生成不同的 sid"""
        url = "https://example.com/api?region=US&num=1"
        url1 = ProxyPool._append_sid(url)
        url2 = ProxyPool._append_sid(url)
        assert "sid=" in url1
        assert url1 != url2


class TestGetProxyPool:
    def test_returns_none_when_no_url(self, monkeypatch):
        import qbu_crawler.proxy as proxy_mod
        monkeypatch.setattr(proxy_mod, "_pool", None)
        monkeypatch.setattr("qbu_crawler.config.PROXY_API_URL", "")
        assert get_proxy_pool() is None

    def test_returns_pool_when_configured(self, monkeypatch):
        import qbu_crawler.proxy as proxy_mod
        monkeypatch.setattr(proxy_mod, "_pool", None)
        monkeypatch.setattr("qbu_crawler.config.PROXY_API_URL", "https://example.com/api")
        pool = get_proxy_pool()
        assert isinstance(pool, ProxyPool)
