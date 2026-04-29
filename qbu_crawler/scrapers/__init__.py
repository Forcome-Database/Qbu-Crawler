from urllib.parse import urlparse

# 主线程启动期预热所有 scraper 模块及其 DrissionPage 依赖。
# 不预热的话，task_manager 在 ThreadPoolExecutor 里 MAX_WORKERS 个线程并发首次
# 调用 get_scraper(url) → 各自 __import__ 触发 basspro/waltons/meatyourmaker
# 模块首次加载，三条导入链在 `_ModuleLock('DrissionPage._functions.settings')`
# 上 lock-invert，抛 `_DeadlockError` / `KeyError: 'DrissionPage'`，整批失败。
# 已在生产 2026-04-29 复现（service v0.4.13 之后引入 DrissionPage.errors 二级
# 导入后暴露）。预热后并发 get_scraper 只是 sys.modules 字典查表，无锁竞争。
from qbu_crawler.scrapers import basspro as _preload_basspro  # noqa: F401
from qbu_crawler.scrapers import meatyourmaker as _preload_mym  # noqa: F401
from qbu_crawler.scrapers import waltons as _preload_waltons  # noqa: F401
# 顺手预热常用的 DrissionPage 子模块（basspro 的 ContextLost 重试要用）
import DrissionPage.errors as _preload_dp_errors  # noqa: F401

SITE_MAP = {
    "www.basspro.com": ("basspro", "qbu_crawler.scrapers.basspro", "BassProScraper"),
    "www.meatyourmaker.com": ("meatyourmaker", "qbu_crawler.scrapers.meatyourmaker", "MeatYourMakerScraper"),
    "www.waltons.com": ("waltons", "qbu_crawler.scrapers.waltons", "WaltonsScraper"),
    "waltons.com": ("waltons", "qbu_crawler.scrapers.waltons", "WaltonsScraper"),
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
