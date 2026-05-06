import argparse
import json
import random
from contextlib import contextmanager
from datetime import datetime, time, timedelta
from pathlib import Path

from qbu_crawler import config, models

PRODUCT_CATALOG = [
    {
        "site": "basspro",
        "ownership": "own",
        "url": "https://www.basspro.com/shop/en/cabelas-commercial-grade-1hp-carnivore-meat-grinder",
        "sku": "BP-CG-1HP",
        "name": "Cabela's Commercial-Grade 1HP Carnivore Meat Grinder",
        "price": 599.99,
        "rating": 4.3,
        "reviews": 184,
        "risk": 0.28,
    },
    {
        "site": "basspro",
        "ownership": "own",
        "url": "https://www.basspro.com/shop/en/cabelas-heavy-duty-20-lb-meat-mixer",
        "sku": "BP-MM-20",
        "name": "Cabela's Heavy-Duty 20 lb. Meat Mixer",
        "price": 169.99,
        "rating": 3.9,
        "reviews": 96,
        "risk": 0.42,
    },
    {
        "site": "basspro",
        "ownership": "own",
        "url": "https://www.basspro.com/shop/en/cabelas-7-lb-vertical-sausage-stuffer",
        "sku": "BP-VS-7",
        "name": "Cabela's 7 lb. Vertical Sausage Stuffer",
        "price": 249.99,
        "rating": 4.1,
        "reviews": 121,
        "risk": 0.34,
    },
    {
        "site": "basspro",
        "ownership": "own",
        "url": "https://www.basspro.com/shop/en/cabelas-vacuum-sealer",
        "sku": "BP-VAC-12",
        "name": "Cabela's 12 in. Vacuum Sealer",
        "price": 149.99,
        "rating": 4.2,
        "reviews": 210,
        "risk": 0.24,
    },
    {
        "site": "meatyourmaker",
        "ownership": "competitor",
        "url": "https://www.meatyourmaker.com/process/grinders/1-hp-grinder/1117079.html",
        "sku": "MYM-GR-1HP",
        "name": "MEAT! Your Maker 1 HP Grinder",
        "price": 699.99,
        "rating": 4.7,
        "reviews": 438,
        "risk": 0.16,
    },
    {
        "site": "meatyourmaker",
        "ownership": "competitor",
        "url": "https://www.meatyourmaker.com/process/sausage/15-lb-sausage-stuffer/1117085.html",
        "sku": "MYM-ST-15",
        "name": "MEAT! Your Maker 15 lb. Sausage Stuffer",
        "price": 329.99,
        "rating": 4.6,
        "reviews": 287,
        "risk": 0.18,
    },
    {
        "site": "waltons",
        "ownership": "competitor",
        "url": "https://waltons.com/waltons-12-meat-grinder",
        "sku": "WAL-GR-12",
        "name": "Walton's #12 Meat Grinder",
        "price": 429.99,
        "rating": 4.5,
        "reviews": 173,
        "risk": 0.2,
    },
    {
        "site": "waltons",
        "ownership": "competitor",
        "url": "https://waltons.com/waltons-11-lb-sausage-stuffer",
        "sku": "WAL-ST-11",
        "name": "Walton's 11 lb. Sausage Stuffer",
        "price": 219.99,
        "rating": 4.4,
        "reviews": 142,
        "risk": 0.22,
    },
]

NEGATIVE_TEMPLATES = [
    {
        "code": "quality_stability",
        "severity": "high",
        "impact_category": "durability",
        "failure_mode": "material_finish",
        "headline": "Durability did not match the price",
        "body": "After several batches the finish started wearing and the locking parts felt loose.",
        "headline_cn": "耐用性不符合价格预期",
        "body_cn": "用了几批后表面开始磨损，锁紧部件也明显松动。",
    },
    {
        "code": "structure_design",
        "severity": "medium",
        "impact_category": "functional",
        "failure_mode": "casing_assembly",
        "headline": "Hard to keep aligned",
        "body": "The tray and tube take extra effort to line up, especially when the meat is cold.",
        "headline_cn": "对齐比较费劲",
        "body_cn": "托盘和管口需要反复调整，肉比较冷的时候更明显。",
    },
    {
        "code": "cleaning_maintenance",
        "severity": "medium",
        "impact_category": "functional",
        "failure_mode": "cleaning_difficulty",
        "headline": "Cleaning takes longer than expected",
        "body": "Small pieces of meat collect around the seams and require a brush after each use.",
        "headline_cn": "清洁耗时比预期更长",
        "body_cn": "肉屑容易卡在接缝处，每次用完都要用刷子处理。",
    },
    {
        "code": "noise_power",
        "severity": "medium",
        "impact_category": "functional",
        "failure_mode": "noise",
        "headline": "Louder under load",
        "body": "The motor still works, but it becomes noticeably loud during longer grinding sessions.",
        "headline_cn": "负载下噪音偏大",
        "body_cn": "电机还能正常工作，但连续绞肉时噪音明显变大。",
    },
    {
        "code": "packaging_shipping",
        "severity": "low",
        "impact_category": "service",
        "failure_mode": "other",
        "headline": "Box arrived rough",
        "body": "The product worked, but the outer box was crushed and the manual was bent.",
        "headline_cn": "包装到货状态一般",
        "body_cn": "产品能用，但外箱被压坏，说明书也有折痕。",
    },
]

POSITIVE_TEMPLATES = [
    {
        "code": "solid_build",
        "headline": "Feels solid on the counter",
        "body": "The frame stays stable and the parts feel heavier than the cheaper models I used before.",
        "headline_cn": "放在台面上很稳",
        "body_cn": "机身很稳，配件也比以前用过的低价型号更厚实。",
    },
    {
        "code": "strong_performance",
        "headline": "Plenty of power for home processing",
        "body": "It handled trimmed venison and pork shoulder without slowing down.",
        "headline_cn": "家用处理动力充足",
        "body_cn": "处理鹿肉和猪肩肉都比较顺畅，没有明显降速。",
    },
    {
        "code": "easy_to_use",
        "headline": "Simple setup",
        "body": "Assembly was straightforward and the controls were easy to understand.",
        "headline_cn": "安装很简单",
        "body_cn": "组装步骤直观，控制按钮也容易理解。",
    },
    {
        "code": "easy_to_clean",
        "headline": "Cleans up quickly",
        "body": "Most parts rinse clean quickly if they are washed right after use.",
        "headline_cn": "清洁比较快",
        "body_cn": "用完马上清洗的话，大部分配件很快就能冲干净。",
    },
    {
        "code": "good_value",
        "headline": "Good value for seasonal batches",
        "body": "For a few large batches each season, it delivers enough capacity without feeling overbuilt.",
        "headline_cn": "季节性批量处理性价比不错",
        "body_cn": "每季做几次大批量处理时容量够用，也不会显得配置过度。",
    },
]


def build_logical_dates(days, today=None):
    if days <= 0:
        raise ValueError("days must be greater than 0")
    today = today or config.now_shanghai().date()
    start = today - timedelta(days=days - 1)
    return [start + timedelta(days=i) for i in range(days)]


def run_simulation(
    days,
    output_dir=None,
    today=None,
    seed=42,
    use_llm=False,
    send_email=False,
    image_urls=None,
):
    output_dir = Path(output_dir) if output_dir else _default_output_dir()
    report_dir = output_dir / "reports"
    db_path = output_dir / "products.db"
    if db_path.exists():
        raise FileExistsError(f"模拟数据库已存在: {db_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    rng = random.Random(seed)
    logical_dates = build_logical_dates(days, today=today)

    with _isolated_runtime(db_path, report_dir, use_llm=use_llm, send_email=send_email):
        models.init_db()
        templates = _load_review_templates(use_llm) or {
            "positive": POSITIVE_TEMPLATES,
            "negative": NEGATIVE_TEMPLATES,
        }
        state = _initial_product_state()
        runs = []

        for day_index, logical_date in enumerate(logical_dates):
            run = _create_workflow_run(logical_date)
            saved = _write_daily_data(
                run,
                logical_date,
                day_index,
                state,
                templates,
                rng,
                image_urls or [],
            )
            _save_completed_tasks(run["id"], logical_date, saved)
            report_result = _advance_workflow(run["id"], logical_date, send_email)
            _sync_run_from_report(run["id"], logical_date, report_result)
            runs.append(_run_summary(run["id"], logical_date, report_result, report_dir))

    return {
        "db_path": str(db_path.resolve()),
        "report_dir": str(report_dir.resolve()),
        "runs": runs,
    }


def _default_output_dir():
    stamp = config.now_shanghai().strftime("%Y%m%d-%H%M%S")
    return Path(config.DATA_DIR) / "simulations" / f"daily-report-{stamp}"


@contextmanager
def _isolated_runtime(db_path, report_dir, use_llm, send_email):
    original = {
        "config_db_path": config.DB_PATH,
        "models_db_path": models.DB_PATH,
        "report_dir": config.REPORT_DIR,
        "email_recipients": list(config.EMAIL_RECIPIENTS),
        "smtp_host": config.SMTP_HOST,
        "ops_recipients": list(config.SCRAPE_QUALITY_ALERT_RECIPIENTS),
        "llm_api_base": config.LLM_API_BASE,
        "llm_api_key": config.LLM_API_KEY,
        "report_cluster_analysis": config.REPORT_CLUSTER_ANALYSIS,
        "ai_digest_mode": config.AI_DIGEST_MODE,
        "openclaw_hook_url": config.OPENCLAW_HOOK_URL,
    }
    config.DB_PATH = str(db_path)
    models.DB_PATH = str(db_path)
    config.REPORT_DIR = str(report_dir)
    config.SCRAPE_QUALITY_ALERT_RECIPIENTS = []
    config.AI_DIGEST_MODE = "off"
    config.OPENCLAW_HOOK_URL = ""
    if not send_email:
        config.EMAIL_RECIPIENTS = []
        config.SMTP_HOST = ""
    if not use_llm:
        config.LLM_API_BASE = ""
        config.LLM_API_KEY = ""
        config.REPORT_CLUSTER_ANALYSIS = False
    try:
        yield
    finally:
        config.DB_PATH = original["config_db_path"]
        models.DB_PATH = original["models_db_path"]
        config.REPORT_DIR = original["report_dir"]
        config.EMAIL_RECIPIENTS = original["email_recipients"]
        config.SMTP_HOST = original["smtp_host"]
        config.SCRAPE_QUALITY_ALERT_RECIPIENTS = original["ops_recipients"]
        config.LLM_API_BASE = original["llm_api_base"]
        config.LLM_API_KEY = original["llm_api_key"]
        config.REPORT_CLUSTER_ANALYSIS = original["report_cluster_analysis"]
        config.AI_DIGEST_MODE = original["ai_digest_mode"]
        config.OPENCLAW_HOOK_URL = original["openclaw_hook_url"]


def _initial_product_state():
    state = {}
    for item in PRODUCT_CATALOG:
        state[item["sku"]] = {
            "review_count": item["reviews"],
            "rating": item["rating"],
            "price": item["price"],
            "ratings_only_count": max(0, int(item["reviews"] * 0.18)),
        }
    return state


def _load_review_templates(use_llm):
    if not use_llm:
        return None
    if not config.LLM_API_BASE or not config.LLM_API_KEY:
        print("LLM 未配置，使用内置模拟模板。")
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_API_BASE)
        response = client.chat.completions.create(
            model=config.LLM_MODEL,
            temperature=0.7,
            messages=[
                {
                    "role": "system",
                    "content": "你只输出 JSON，不输出解释。",
                },
                {
                    "role": "user",
                    "content": (
                        "生成肉类加工设备电商评论模板，要求客观真实，包含 positive 和 negative 两组。"
                        "每组 5 条，每条字段为 code, headline, body, headline_cn, body_cn。"
                        "negative 还要有 severity, impact_category, failure_mode。"
                        "code 只能使用 quality_stability, structure_design, cleaning_maintenance, "
                        "noise_power, packaging_shipping, solid_build, strong_performance, "
                        "easy_to_use, easy_to_clean, good_value。"
                    ),
                },
            ],
        )
        content = response.choices[0].message.content or ""
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            from json_repair import repair_json
            data = json.loads(repair_json(content))
        if isinstance(data.get("positive"), list) and isinstance(data.get("negative"), list):
            return data
    except Exception as exc:
        print(f"LLM 生成模拟数据失败，使用内置模板: {exc}")
    return None


def _create_workflow_run(logical_date):
    data_since = f"{logical_date.isoformat()}T00:00:00+08:00"
    data_until = f"{(logical_date + timedelta(days=1)).isoformat()}T00:00:00+08:00"
    created_at = datetime.combine(logical_date, time(8, 50)).isoformat()
    return models.create_workflow_run(
        {
            "workflow_type": "daily",
            "status": "submitted",
            "logical_date": logical_date.isoformat(),
            "trigger_key": f"simulation:daily:{logical_date.isoformat()}",
            "data_since": data_since,
            "data_until": data_until,
            "requested_by": "simulation",
            "service_version": "simulation",
            "created_at": created_at,
            "updated_at": created_at,
        }
    )


def _write_daily_data(run, logical_date, day_index, state, templates, rng, image_urls):
    scraped_at = datetime.combine(logical_date, time(9, 15)).strftime("%Y-%m-%d %H:%M:%S")
    saved = []
    conn = models.get_conn()
    try:
        for product in PRODUCT_CATALOG:
            sku = product["sku"]
            daily_reviews = _build_reviews_for_product(product, logical_date, day_index, templates, rng, image_urls)
            _update_product_state(state[sku], daily_reviews, day_index, rng)
            product_id = _upsert_product(conn, product, state[sku], scraped_at)
            _insert_product_snapshot(conn, product_id, state[sku], scraped_at)
            review_ids = _insert_reviews(conn, product_id, product, daily_reviews, scraped_at)
            saved.append({
                "product": product,
                "reviews": daily_reviews,
                "review_ids": review_ids,
                "scraped_at": scraped_at,
                "state": dict(state[sku]),
            })
        conn.commit()
    finally:
        conn.close()
    return saved


def _build_reviews_for_product(product, logical_date, day_index, templates, rng, image_urls):
    if day_index == 0:
        count = rng.randint(6, 12)
    else:
        count = max(0, int(rng.gauss(2.4, 1.5)))
    reviews = []
    negative_rate = product["risk"] + (0.05 if product["ownership"] == "own" else -0.04)
    for index in range(count):
        is_negative = rng.random() < negative_rate
        source = rng.choice(templates["negative"] if is_negative else templates["positive"])
        rating = rng.choice([1, 2, 2, 3]) if is_negative else rng.choice([4, 4, 5, 5, 5])
        published = logical_date - timedelta(days=rng.randint(0, 28))
        suffix = f"{logical_date.strftime('%Y%m%d')}-{product['sku']}-{index + 1}"
        images = []
        if image_urls and rng.random() < 0.18:
            images = [rng.choice(image_urls)]
        reviews.append({
            "author": _author_name(rng),
            "headline": source["headline"],
            "body": f"{source['body']} Product: {product['name']}. Batch {suffix}.",
            "headline_cn": source["headline_cn"],
            "body_cn": f"{source['body_cn']} 产品：{product['name']}。样本 {suffix}。",
            "rating": rating,
            "date_published": published.isoformat(),
            "images": images,
            "label": _label_from_template(source, is_negative),
            "sentiment": "negative" if is_negative else "positive",
            "sentiment_score": round(rng.uniform(0.05, 0.32), 2) if is_negative else round(rng.uniform(0.72, 0.96), 2),
            "impact_category": source.get("impact_category", "functional" if is_negative else "none"),
            "failure_mode": source.get("failure_mode", "none"),
        })
    return reviews


def _label_from_template(source, is_negative):
    return {
        "code": source["code"],
        "polarity": "negative" if is_negative else "positive",
        "severity": source.get("severity", "low"),
        "confidence": 0.9,
    }


def _author_name(rng):
    first = ["Chris", "Morgan", "Taylor", "Jordan", "Casey", "Riley", "Drew", "Pat", "Jamie", "Alex"]
    last = ["H.", "M.", "K.", "S.", "T.", "B.", "R.", "L."]
    return f"{rng.choice(first)} {rng.choice(last)}"


def _update_product_state(state, reviews, day_index, rng):
    new_review_count = len(reviews) + rng.randint(0, max(1, len(reviews) // 3 + 1))
    old_total = max(1, state["review_count"])
    new_total = old_total + new_review_count
    if reviews:
        average_new_rating = sum(r["rating"] for r in reviews) / len(reviews)
        state["rating"] = round(((state["rating"] * old_total) + (average_new_rating * len(reviews))) / (old_total + len(reviews)), 2)
    state["review_count"] = new_total
    state["ratings_only_count"] += max(0, new_review_count - len(reviews))
    if day_index and rng.random() < 0.18:
        state["price"] = round(max(19.99, state["price"] + rng.choice([-20, -10, 10, 15])), 2)


def _upsert_product(conn, product, state, scraped_at):
    conn.execute(
        """
        INSERT INTO products (url, site, name, sku, price, stock_status, review_count,
                              rating, scraped_at, ownership, ratings_only_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(url) DO UPDATE SET
            site=excluded.site,
            name=excluded.name,
            sku=excluded.sku,
            price=excluded.price,
            stock_status=excluded.stock_status,
            review_count=excluded.review_count,
            rating=excluded.rating,
            scraped_at=excluded.scraped_at,
            ownership=excluded.ownership,
            ratings_only_count=excluded.ratings_only_count
        """,
        (
            product["url"],
            product["site"],
            product["name"],
            product["sku"],
            state["price"],
            "in_stock",
            state["review_count"],
            state["rating"],
            scraped_at,
            product["ownership"],
            state["ratings_only_count"],
        ),
    )
    row = conn.execute("SELECT id FROM products WHERE url=?", (product["url"],)).fetchone()
    return row["id"]


def _insert_product_snapshot(conn, product_id, state, scraped_at):
    conn.execute(
        """
        INSERT INTO product_snapshots (product_id, price, stock_status, review_count,
                                       rating, ratings_only_count, scraped_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            product_id,
            state["price"],
            "in_stock",
            state["review_count"],
            state["rating"],
            state["ratings_only_count"],
            scraped_at,
        ),
    )


def _insert_reviews(conn, product_id, product, reviews, scraped_at):
    review_ids = []
    for review in reviews:
        body_hash = models._body_hash(review["body"])
        parsed, meta = models._parse_date_published(
            review["date_published"],
            scraped_at=scraped_at,
            return_meta=True,
        )
        cursor = conn.execute(
            """
            INSERT INTO reviews (product_id, author, headline, body, body_hash, rating,
                                 date_published, date_published_parsed,
                                 date_parse_method, date_parse_anchor, date_parse_confidence,
                                 date_published_estimated, images, scraped_at,
                                 headline_cn, body_cn, translate_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                product_id,
                review["author"],
                review["headline"],
                review["body"],
                body_hash,
                review["rating"],
                review["date_published"],
                parsed,
                meta["method"],
                meta["anchor"],
                meta["confidence"],
                1 if meta["method"].startswith("relative") else 0,
                json.dumps(review["images"], ensure_ascii=False),
                scraped_at,
                review["headline_cn"],
                review["body_cn"],
                "done",
            ),
        )
        review_id = cursor.lastrowid
        review_ids.append(review_id)
        _insert_review_analysis(conn, review_id, review, scraped_at)
    return review_ids


def _insert_review_analysis(conn, review_id, review, scraped_at):
    conn.execute(
        """
        INSERT INTO review_analysis (review_id, sentiment, sentiment_score, labels,
                                     features, insight_cn, insight_en, prompt_version,
                                     llm_model, analyzed_at, impact_category, failure_mode)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            review_id,
            review["sentiment"],
            review["sentiment_score"],
            json.dumps([review["label"]], ensure_ascii=False),
            json.dumps([review["label"]["code"]], ensure_ascii=False),
            review["body_cn"],
            review["body"],
            "simulation-v1",
            "simulation",
            scraped_at,
            review["impact_category"],
            review["failure_mode"],
        ),
    )


def _save_completed_tasks(run_id, logical_date, saved):
    grouped = {}
    for item in saved:
        product = item["product"]
        grouped.setdefault((product["site"], product["ownership"]), []).append(item)
    for (site, ownership), items in grouped.items():
        task_id = f"simulation-{logical_date.strftime('%Y%m%d')}-{site}-{ownership}"
        urls = [item["product"]["url"] for item in items]
        reviews_saved = sum(len(item["review_ids"]) for item in items)
        finished_at = datetime.combine(logical_date, time(9, 40)).isoformat()
        models.save_task(
            {
                "id": task_id,
                "type": "scrape",
                "status": "completed",
                "params": {"urls": urls, "ownership": ownership, "review_limit": 0},
                "progress": {"total": len(urls), "completed": len(urls), "failed": 0, "current_url": None},
                "result": {
                    "products_saved": len(items),
                    "reviews_saved": reviews_saved,
                    "product_summaries": [
                        {
                            "url": item["product"]["url"],
                            "site": item["product"]["site"],
                            "sku": item["product"]["sku"],
                            "name": item["product"]["name"],
                            "site_review_count": item["state"]["review_count"],
                            "extracted_review_count": len(item["reviews"]),
                            "saved_review_count": len(item["review_ids"]),
                            "scrape_meta": {"source": "simulation"},
                        }
                        for item in items
                    ],
                    "expected_urls": urls,
                    "saved_urls": urls,
                    "failed_urls": [],
                    "expected_url_count": len(urls),
                    "saved_url_count": len(urls),
                    "failed_url_count": 0,
                },
                "error": None,
                "created_at": datetime.combine(logical_date, time(9, 0)).isoformat(),
                "updated_at": finished_at,
                "last_progress_at": finished_at,
                "worker_token": "simulation",
                "system_error_code": None,
                "started_at": datetime.combine(logical_date, time(9, 5)).isoformat(),
                "finished_at": finished_at,
                "reply_to": "",
                "notified_at": None,
            }
        )
        models.attach_task_to_workflow(
            run_id=run_id,
            task_id=task_id,
            task_type="scrape",
            site=site,
            ownership=ownership,
        )


def _advance_workflow(run_id, logical_date, send_email):
    from qbu_crawler.server import workflows

    original_should_send = workflows._should_send_workflow_email
    original_send_quality_alert = workflows._send_data_quality_alert
    if not send_email:
        workflows._should_send_workflow_email = lambda task_rows, snapshot: False
    workflows._send_data_quality_alert = lambda *args, **kwargs: None
    try:
        worker = workflows.WorkflowWorker(interval=1, task_stale_seconds=3600)
        now = f"{logical_date.isoformat()}T10:30:00+08:00"
        while worker.process_once(now=now):
            pass
    finally:
        workflows._should_send_workflow_email = original_should_send
        workflows._send_data_quality_alert = original_send_quality_alert

    run = models.get_workflow_run(run_id) or {}
    return {
        "run_id": run_id,
        "logical_date": logical_date.isoformat(),
        "status": run.get("status"),
        "report_phase": run.get("report_phase"),
        "html_path": _latest_artifact(run_id, "html_attachment"),
        "excel_path": run.get("excel_path"),
        "analytics_path": run.get("analytics_path"),
        "snapshot_path": run.get("snapshot_path"),
        "report_mode": run.get("report_mode"),
    }


def _latest_artifact(run_id, artifact_type):
    conn = models.get_conn()
    try:
        row = conn.execute(
            """
            SELECT path FROM report_artifacts
            WHERE run_id=? AND artifact_type=?
            ORDER BY id DESC LIMIT 1
            """,
            (run_id, artifact_type),
        ).fetchone()
        return row["path"] if row else None
    finally:
        conn.close()


def _sync_run_from_report(run_id, logical_date, report_result):
    run = models.get_workflow_run(run_id) or {}
    fields = {
        "status": report_result.get("status") or "completed",
        "report_phase": report_result.get("report_phase") or "full_sent",
        "excel_path": report_result.get("excel_path"),
        "analytics_path": report_result.get("analytics_path"),
        "pdf_path": report_result.get("pdf_path"),
        "error": None,
    }
    if not run.get("finished_at"):
        fields["finished_at"] = f"{logical_date.isoformat()}T10:30:00+08:00"
    models.update_workflow_run(run_id, **fields)


def _run_summary(run_id, logical_date, report_result, report_dir):
    return {
        "run_id": run_id,
        "logical_date": logical_date.isoformat(),
        "status": report_result.get("status"),
        "report_phase": report_result.get("report_phase"),
        "report_mode": report_result.get("report_mode"),
        "snapshot_path": _resolve_artifact_path(report_result.get("snapshot_path"), report_dir),
        "analytics_path": _resolve_artifact_path(report_result.get("analytics_path"), report_dir),
        "excel_path": _resolve_artifact_path(report_result.get("excel_path"), report_dir),
        "html_path": _resolve_artifact_path(report_result.get("html_path"), report_dir),
    }


def _resolve_artifact_path(value, report_dir):
    if not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return str(path)
    return str((Path(report_dir) / path).resolve())


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="模拟连续多天采集数据并生成每日报告。")
    parser.add_argument("days", type=int, help="模拟天数，从当前日期往前连续生成。")
    parser.add_argument("--output-dir", help="模拟输出目录，默认写入 data/simulations/ 下的新目录。")
    parser.add_argument("--seed", type=int, default=42, help="随机种子。")
    parser.add_argument("--use-llm", action="store_true", help="使用已配置的 LLM 生成评论模板。")
    parser.add_argument("--send-email", action="store_true", help="允许发送业务邮件，默认禁用。")
    parser.add_argument("--image-url", action="append", default=[], help="可重复传入旧评论图片 URL。")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    result = run_simulation(
        days=args.days,
        output_dir=args.output_dir,
        seed=args.seed,
        use_llm=args.use_llm,
        send_email=args.send_email,
        image_urls=args.image_url,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
