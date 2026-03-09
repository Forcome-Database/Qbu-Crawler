import sys
import os
from models import init_db, save_product, save_snapshot, save_reviews
from scraper import BassProScraper

USAGE = """用法:
  python main.py <产品URL> [产品URL2 ...]     抓取指定产品页
  python main.py -f <文件路径>                 从文件读取 URL 列表（每行一个）
  python main.py -c <分类页URL> [最大页数]     从分类页自动采集产品链接并抓取
"""


def load_urls_from_file(filepath: str) -> list[str]:
    if not os.path.exists(filepath):
        print(f"文件不存在: {filepath}")
        sys.exit(1)
    with open(filepath, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]


def scrape_urls(scraper: BassProScraper, urls: list[str]):
    success = 0
    failed_urls = []

    for i, url in enumerate(urls, 1):
        print(f"\n[{i}/{len(urls)}] 正在抓取: {url}")
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

    print(f"\n抓取完成! 成功 {success}/{len(urls)}")
    if failed_urls:
        print(f"失败的 URL ({len(failed_urls)} 个):")
        for u in failed_urls:
            print(f"  {u}")


def main():
    if len(sys.argv) < 2:
        print(USAGE)
        sys.exit(1)

    print("初始化数据库...")
    init_db()

    scraper = BassProScraper()
    try:
        if sys.argv[1] == "-f":
            # 从文件读取 URL
            if len(sys.argv) < 3:
                print("请指定文件路径")
                sys.exit(1)
            urls = load_urls_from_file(sys.argv[2])
            print(f"从文件加载 {len(urls)} 个 URL")
            scrape_urls(scraper, urls)

        elif sys.argv[1] == "-c":
            # 从分类页采集
            if len(sys.argv) < 3:
                print("请指定分类页 URL")
                sys.exit(1)
            category_url = sys.argv[2]
            max_pages = int(sys.argv[3]) if len(sys.argv) > 3 else 0
            print(f"正在从分类页采集产品链接: {category_url}")
            urls = scraper.collect_product_urls(category_url, max_pages)
            print(f"\n共采集到 {len(urls)} 个产品链接，开始抓取详情...")
            scrape_urls(scraper, urls)

        else:
            # 直接传入产品 URL
            urls = sys.argv[1:]
            scrape_urls(scraper, urls)
    finally:
        scraper.close()


if __name__ == "__main__":
    main()
