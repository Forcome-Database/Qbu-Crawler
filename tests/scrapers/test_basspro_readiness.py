import json

from qbu_crawler.scrapers.basspro import BassProScraper


class FakeIdentityTab:
    def __init__(self, results):
        self.results = list(results)
        self.run_js_called = False

    def run_js(self, _script):
        self.run_js_called = True
        value = self.results.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


class FakeReviewsTab:
    def __init__(self, payload):
        self.payload = payload

    def run_js(self, _script):
        return json.dumps(self.payload)


def _scraper(monkeypatch):
    scraper = BassProScraper.__new__(BassProScraper)
    monkeypatch.setattr("qbu_crawler.scrapers.basspro.time.sleep", lambda *_args, **_kwargs: None)
    return scraper


def test_basspro_product_identity_uses_js_polling_after_cdp_search_error(monkeypatch):
    scraper = _scraper(monkeypatch)
    tab = FakeIdentityTab([KeyError("searchId"), "", "Cabela's Heavy-Duty 20-lb. Meat Mixer"])

    title = scraper._wait_product_identity(tab, timeout=3)

    assert title == "Cabela's Heavy-Duty 20-lb. Meat Mixer"
    assert tab.run_js_called


def test_basspro_age_gate_checkpoint_records_multiple_stages(monkeypatch):
    scraper = _scraper(monkeypatch)
    calls = []

    monkeypatch.setattr(scraper, "_dismiss_age_gate", lambda _tab: calls.append("dismiss") or True)
    diagnostics = {}

    scraper._age_gate_checkpoint(object(), diagnostics, "after_get")
    scraper._age_gate_checkpoint(object(), diagnostics, "before_bv")

    assert calls == ["dismiss", "dismiss"]
    assert diagnostics["age_gate_seen"] is True
    assert diagnostics["age_gate_stages"] == ["after_get", "before_bv"]


def test_basspro_reviews_shadow_empty_records_diagnostics(monkeypatch):
    scraper = _scraper(monkeypatch)
    tab = FakeReviewsTab({
        "clicked": False,
        "count": 0,
        "container_seen": True,
        "shadow_seen": True,
        "load_more_state": "missing",
    })

    diagnostics = scraper._load_all_reviews(tab)

    assert diagnostics["stop_reason"] == "shadow_empty"
    assert diagnostics["bv_container_seen"] is True
    assert diagnostics["shadow_count"] == 0
