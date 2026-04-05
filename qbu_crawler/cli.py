#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Qbu-Crawler 统一启动入口

通过 uvx / pip install 后可直接运行:
    qbu-crawler <product-url>
    qbu-crawler -f urls.txt
    qbu-crawler -c <category-url>
    qbu-crawler serve [--host 0.0.0.0] [--port 9000]
    qbu-crawler workflow daily-submit [--logical-date YYYY-MM-DD] [--dry-run]
    qbu                             # 短别名
"""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def load_env_config():
    """
    加载环境变量配置
    优先级：当前工作目录 .env > 用户主目录 .qbu-crawler/.env > 系统环境变量
    """
    # 1. 当前工作目录
    cwd_env = Path.cwd() / ".env"
    if cwd_env.exists():
        load_dotenv(cwd_env, override=True)
        return

    # 2. 用户主目录下的配置目录
    home_env = Path.home() / ".qbu-crawler" / ".env"
    if home_env.exists():
        load_dotenv(home_env, override=True)
        return

    # 3. 没有找到 .env 文件，使用系统环境变量
    print("[配置] 未找到 .env 文件，使用系统环境变量")
    print(f"[提示] 可在以下位置创建 .env 文件:")
    print(f"       - {cwd_env}")
    print(f"       - {home_env}")


def main():
    """CLI 主入口 — uvx / pip install 后的命令行入口"""
    load_env_config()

    from concurrent.futures import ThreadPoolExecutor, as_completed
    from qbu_crawler.models import init_db, save_product, save_snapshot, save_reviews
    from qbu_crawler.scrapers import get_scraper, get_site_key, SITE_MAP

    USAGE = """用法:
  qbu-crawler <产品URL> [产品URL2 ...]     抓取指定产品页
  qbu-crawler -f <文件路径>                 从文件读取 URL 列表（每行一个）
  qbu-crawler -c <分类页URL> [最大页数]     从分类页自动采集产品链接并抓取
  qbu-crawler -c <URL1> -c <URL2>          多站点分类页并行采集
  qbu-crawler serve [--host HOST] [--port PORT]  启动 HTTP API + MCP 服务
  qbu-crawler workflow daily-submit         从本机 CSV 提交每日批次（幂等）

支持站点: """ + ", ".join(SITE_MAP.keys())

    def load_urls_from_file(filepath):
        if not os.path.exists(filepath):
            print(f"文件不存在: {filepath}")
            sys.exit(1)
        with open(filepath, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip() and not line.startswith("#")]

    def group_urls_by_site(urls):
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
                product.setdefault("ownership", "competitor")

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

    # ── serve 子命令 ──────────────────────────────────
    if len(sys.argv) >= 2 and sys.argv[1] == "serve":
        from qbu_crawler.server.app import start_server
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

    if len(sys.argv) >= 3 and sys.argv[1] == "workflow" and sys.argv[2] == "daily-submit":
        from qbu_crawler import config
        from qbu_crawler.server.workflows import LocalHttpTaskSubmitter, submit_daily_run

        logical_date = None
        dry_run = False
        source_csv = config.DAILY_SOURCE_CSV_PATH
        detail_csv = config.DAILY_PRODUCT_CSV_PATH
        source_csv_url = config.DAILY_SOURCE_CSV_URL
        detail_csv_url = config.DAILY_PRODUCT_CSV_URL
        args = sys.argv[3:]
        i = 0
        while i < len(args):
            if args[i] == "--logical-date" and i + 1 < len(args):
                logical_date = args[i + 1]
                i += 2
            elif args[i] == "--source-csv" and i + 1 < len(args):
                source_csv = args[i + 1]
                i += 2
            elif args[i] == "--detail-csv" and i + 1 < len(args):
                detail_csv = args[i + 1]
                i += 2
            elif args[i] == "--dry-run":
                dry_run = True
                i += 1
            else:
                print(f"未知参数: {args[i]}")
                sys.exit(1)

        print("初始化数据库...")
        logical_date = logical_date or config.now_shanghai().date().isoformat()
        init_db()
        result = submit_daily_run(
            submitter=LocalHttpTaskSubmitter(),
            source_csv=source_csv,
            detail_csv=detail_csv,
            source_csv_url=source_csv_url,
            detail_csv_url=detail_csv_url,
            logical_date=logical_date,
            requested_by="cli",
            dry_run=dry_run,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
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
