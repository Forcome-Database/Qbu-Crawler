from urllib.parse import urlparse

SITE_MAP = {
    "www.basspro.com": ("basspro", "scrapers.basspro", "BassProScraper"),
    "www.meatyourmaker.com": ("meatyourmaker", "scrapers.meatyourmaker", "MeatYourMakerScraper"),
}


def get_site_key(url: str) -> str:
    host = urlparse(url).netloc
    entry = SITE_MAP.get(host)
    if not entry:
        raise ValueError(f"不支持的站点: {host}")
    return entry[0]


def get_scraper(url: str):
    host = urlparse(url).netloc
    entry = SITE_MAP.get(host)
    if not entry:
        raise ValueError(f"不支持的站点: {host}")
    _, module_path, cls_name = entry
    module = __import__(module_path, fromlist=[cls_name])
    return getattr(module, cls_name)()
