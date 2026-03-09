import sys
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from models import init_db, save_product, save_snapshot, save_reviews
from scrapers import get_scraper, get_site_key, SITE_MAP

USAGE = """用法:
  python main.py <产品URL> [产品URL2 ...]     抓取指定产品页
  python main.py -f <文件路径>                 从文件读取 URL 列表（每行一个）
  python main.py -c <分类页URL> [最大页数]     从分类页自动采集产品链接并抓取
  python main.py -c <URL1> -c <URL2>          多站点分类页并行采集

支持站点: """ + ", ".join(SITE_MAP.keys())


def load_urls_from_file(filepath):
    if not os.path.exists(filepath):
        print(f"文件不存在: {filepath}")
        sys.exit(1)
    with open(filepath, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]


def group_urls_by_site(urls):
    """按域名对 URL 分组，忽略不支持的站点"""
    groups = {}
    for url in urls:
        try:
            site = get_site_key(url)
            groups.setdefault(site, []).append(url)
        except ValueError as e:
            print(f"  [跳过] {e}")
    return groups


def scrape_urls(scraper, urls, site=""):
    prefix = f"[{site}] " if site else ""
    success = 0
    failed_urls = []

    for i, url in enumerate(urls, 1):
        print(f"\n{prefix}[{i}/{len(urls)}] 正在抓取: {url}")
        try:
            data = scraper.scrape(url)
            product = data["product"]
            reviews = data["reviews"]

            product_id = save_product(product)
            save_snapshot(product_id, product)
            new_reviews = save_reviews(product_id, reviews)

            print(f"  名称: {product['name']}")
            print(f"  SKU: {product['sku']}")
            print(f"  价格: {product['price']}")
            print(f"  库存: {product['stock_status']}")
            print(f"  评分: {product['rating']}")
            review_count = product['review_count'] or 0
            scraped = len(reviews)
            if review_count == 0:
                print(f"  评论: 无")
            elif scraped > 0:
                print(f"  评论: {scraped}/{review_count} 条 (新增 {new_reviews})")
            else:
                print(f"  评论: 0/{review_count} 条 (BV未注入详情数据)")
            success += 1
        except Exception as e:
            failed_urls.append(url)
            print(f"  抓取失败: {e}")

    print(f"\n{prefix}抓取完成! 成功 {success}/{len(urls)}")
    if failed_urls:
        print(f"失败的 URL ({len(failed_urls)} 个):")
        for u in failed_urls:
            print(f"  {u}")


def run_site(site, urls):
    scraper = get_scraper(urls[0])
    try:
        scrape_urls(scraper, urls, site)
    finally:
        scraper.close()


def run_category_site(category_url, max_pages):
    site = get_site_key(category_url)
    scraper = get_scraper(category_url)
    try:
        print(f"[{site}] 正在从分类页采集产品链接: {category_url}")
        urls = scraper.collect_product_urls(category_url, max_pages)
        print(f"[{site}] 共采集到 {len(urls)} 个产品链接，开始抓取详情...")
        scrape_urls(scraper, urls, site)
    finally:
        scraper.close()


def main():
    # ── serve 子命令 ──────────────────────────────────
    if len(sys.argv) >= 2 and sys.argv[1] == "serve":
        from server.app import start_server
        host = None
        port = None
        args = sys.argv[2:]
        i = 0
        while i < len(args):
            if args[i] == "--host" and i + 1 < len(args):
                host = args[i + 1]; i += 2
            elif args[i] == "--port" and i + 1 < len(args):
                port = int(args[i + 1]); i += 2
            else:
                i += 1
        start_server(host=host, port=port)
        return

    if len(sys.argv) < 2:
        print(USAGE)
        sys.exit(1)

    print("初始化数据库...")
    init_db()

    args = sys.argv[1:]

    if "-c" in args:
        categories = []
        max_pages = 0
        i = 0
        while i < len(args):
            if args[i] == "-c" and i + 1 < len(args):
                categories.append(args[i + 1])
                i += 2
            else:
                try:
                    max_pages = int(args[i])
                except ValueError:
                    pass
                i += 1

        if not categories:
            print("请指定分类页 URL")
            sys.exit(1)

        if len(categories) == 1:
            run_category_site(categories[0], max_pages)
        else:
            with ThreadPoolExecutor(max_workers=len(categories)) as pool:
                futures = {
                    pool.submit(run_category_site, cat, max_pages): cat
                    for cat in categories
                }
                for future in as_completed(futures):
                    cat = futures[future]
                    try:
                        future.result()
                    except Exception as e:
                        print(f"[错误] {cat}: {e}")

    elif args[0] == "-f":
        if len(args) < 2:
            print("请指定文件路径")
            sys.exit(1)
        urls = load_urls_from_file(args[1])
        print(f"从文件加载 {len(urls)} 个 URL")
        site_groups = group_urls_by_site(urls)

        if len(site_groups) == 1:
            site, site_urls = next(iter(site_groups.items()))
            run_site(site, site_urls)
        else:
            with ThreadPoolExecutor(max_workers=len(site_groups)) as pool:
                futures = {
                    pool.submit(run_site, site, site_urls): site
                    for site, site_urls in site_groups.items()
                }
                for future in as_completed(futures):
                    site = futures[future]
                    try:
                        future.result()
                    except Exception as e:
                        print(f"[错误] {site}: {e}")

    else:
        urls = args
        site_groups = group_urls_by_site(urls)
        if len(site_groups) == 1:
            site, site_urls = next(iter(site_groups.items()))
            run_site(site, site_urls)
        else:
            with ThreadPoolExecutor(max_workers=len(site_groups)) as pool:
                futures = {
                    pool.submit(run_site, site, site_urls): site
                    for site, site_urls in site_groups.items()
                }
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        print(f"[错误] {e}")


if __name__ == "__main__":
    main()
