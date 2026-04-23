from pathlib import Path

import pytest

from qbu_crawler.scrapers import base as base_module
from qbu_crawler.scrapers.base import BaseScraper


class _FakeTab:
    def __init__(self, tab_id):
        self.tab_id = tab_id
        self.closed = False

    def close(self):
        self.closed = True


class _FakeBrowser:
    def __init__(self, tabs):
        self._tabs = tabs
        self.new_tab_calls = []
        self.fresh_tab = None

    def get_tabs(self):
        return list(self._tabs)

    def new_tab(self, url):
        self.new_tab_calls.append(url)
        self.fresh_tab = _FakeTab("fresh")
        return self.fresh_tab


def test_cleanup_tabs_keeps_new_fresh_tab_and_closes_all_old_tabs():
    tabs = [_FakeTab("tab-1"), _FakeTab("tab-2"), _FakeTab("tab-3")]
    browser = _FakeBrowser(tabs)

    BaseScraper._cleanup_tabs(browser)

    assert browser.new_tab_calls == ["about:blank"]
    assert all(tab.closed for tab in tabs)
    assert browser.fresh_tab is not None
    assert browser.fresh_tab.closed is False


def test_cleanup_tabs_skips_when_only_one_tab():
    tabs = [_FakeTab("tab-1")]
    browser = _FakeBrowser(tabs)

    BaseScraper._cleanup_tabs(browser)

    assert browser.new_tab_calls == []
    assert tabs[0].closed is False


class _TimeoutTab(_FakeTab):
    def __init__(self, tab_id, calls):
        super().__init__(tab_id)
        self._calls = calls

    def close(self):
        self._calls.append(("close", self.tab_id, base_module.socket.getdefaulttimeout()))
        super().close()


class _TimeoutBrowser:
    def __init__(self):
        self.calls = []
        self._tabs = [_TimeoutTab("tab-1", self.calls), _TimeoutTab("tab-2", self.calls)]

    def get_tabs(self):
        self.calls.append(("get_tabs", base_module.socket.getdefaulttimeout()))
        return list(self._tabs)

    def new_tab(self, url):
        self.calls.append(("new_tab", url, base_module.socket.getdefaulttimeout()))
        return _FakeTab("fresh")


def test_cleanup_tabs_uses_temporary_socket_timeouts():
    browser = _TimeoutBrowser()
    old_timeout = base_module.socket.getdefaulttimeout()

    BaseScraper._cleanup_tabs(browser)

    assert ("get_tabs", 5.0) in browser.calls
    assert ("new_tab", "about:blank", 5.0) in browser.calls
    assert ("close", "tab-1", 3.0) in browser.calls
    assert ("close", "tab-2", 3.0) in browser.calls
    assert base_module.socket.getdefaulttimeout() == old_timeout


class _FakeClosableBrowser:
    def quit(self, force=True, timeout=5):
        return None


def test_attach_browser_uses_temporary_socket_timeout(monkeypatch: pytest.MonkeyPatch):
    calls = []

    def fake_chromium(port):
        calls.append((port, base_module.socket.getdefaulttimeout()))
        return "browser"

    monkeypatch.setattr(base_module, "Chromium", fake_chromium)
    old_timeout = base_module.socket.getdefaulttimeout()

    browser = BaseScraper._attach_browser(9222, ws_timeout=4.5)

    assert browser == "browser"
    assert calls == [(9222, 4.5)]
    assert base_module.socket.getdefaulttimeout() == old_timeout


def test_close_persists_dirty_session_profile_back_to_base(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    base_dir = tmp_path / "chrome_profile"
    session_dir = tmp_path / "chrome_profile_sess_1_abcd"
    (base_dir / "Default").mkdir(parents=True)
    (session_dir / "Default").mkdir(parents=True)

    (base_dir / "Default" / "Cookies").write_text("old-cookie", encoding="utf-8")
    (session_dir / "Default" / "Cookies").write_text("new-cookie", encoding="utf-8")
    (session_dir / "Default" / "Cookies-journal").write_text("journal", encoding="utf-8")
    (session_dir / "Default" / "Preferences").write_text("prefs", encoding="utf-8")
    (session_dir / "Local State").write_text("local-state", encoding="utf-8")

    monkeypatch.setattr(base_module, "CHROME_USER_DATA_PATH", str(base_dir))
    monkeypatch.setattr(base_module, "CHROME_USER_DATA_SYNC_FILES", [
        ("Default", "Cookies"),
        ("Default", "Cookies-journal"),
    ])
    monkeypatch.setattr(BaseScraper, "_kill_user_data_chrome", classmethod(lambda cls, port, user_data_dir=None: None))

    scraper = BaseScraper.__new__(BaseScraper)
    scraper.browser = _FakeClosableBrowser()
    scraper._use_user_data = True
    scraper._session_port = 12345
    scraper._session_user_data_dir = str(session_dir)
    scraper._session_profile_dirty = True

    BaseScraper.close(scraper)

    assert (base_dir / "Default" / "Cookies").read_text(encoding="utf-8") == "new-cookie"
    assert (base_dir / "Default" / "Cookies-journal").read_text(encoding="utf-8") == "journal"
    assert not (base_dir / "Default" / "Preferences").exists()
    assert not (base_dir / "Local State").exists()
    assert not session_dir.exists()


def test_close_can_opt_in_to_persist_preferences_and_local_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    base_dir = tmp_path / "chrome_profile"
    session_dir = tmp_path / "chrome_profile_sess_1_abcd"
    (base_dir / "Default").mkdir(parents=True)
    (session_dir / "Default").mkdir(parents=True)

    (base_dir / "Default" / "Cookies").write_text("old-cookie", encoding="utf-8")
    (session_dir / "Default" / "Cookies").write_text("new-cookie", encoding="utf-8")
    (session_dir / "Default" / "Cookies-journal").write_text("journal", encoding="utf-8")
    (session_dir / "Default" / "Preferences").write_text("prefs", encoding="utf-8")
    (session_dir / "Local State").write_text("local-state", encoding="utf-8")

    monkeypatch.setattr(base_module, "CHROME_USER_DATA_PATH", str(base_dir))
    monkeypatch.setattr(base_module, "CHROME_USER_DATA_SYNC_FILES", [
        ("Default", "Cookies"),
        ("Default", "Cookies-journal"),
        ("Default", "Preferences"),
        ("", "Local State"),
    ])
    monkeypatch.setattr(BaseScraper, "_kill_user_data_chrome", classmethod(lambda cls, port, user_data_dir=None: None))

    scraper = BaseScraper.__new__(BaseScraper)
    scraper.browser = _FakeClosableBrowser()
    scraper._use_user_data = True
    scraper._session_port = 12345
    scraper._session_user_data_dir = str(session_dir)
    scraper._session_profile_dirty = True

    BaseScraper.close(scraper)

    assert (base_dir / "Default" / "Cookies").read_text(encoding="utf-8") == "new-cookie"
    assert (base_dir / "Default" / "Cookies-journal").read_text(encoding="utf-8") == "journal"
    assert (base_dir / "Default" / "Preferences").read_text(encoding="utf-8") == "prefs"
    assert (base_dir / "Local State").read_text(encoding="utf-8") == "local-state"
    assert not session_dir.exists()
