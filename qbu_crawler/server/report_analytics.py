import json
import re
from datetime import date, timedelta

from qbu_crawler import config, models


def _date_sort_key(date_str):
    """Parse date string for chronological sorting. Unparseable → epoch."""
    from qbu_crawler.server.report_common import _parse_date_flexible
    parsed = _parse_date_flexible(date_str)
    return parsed or date(1970, 1, 1)


NEGATIVE_LABELS = (
    "quality_stability",
    "structure_design",
    "assembly_installation",
    "material_finish",
    "cleaning_maintenance",
    "noise_power",
    "packaging_shipping",
    "service_fulfillment",
)

POSITIVE_LABELS = (
    "easy_to_use",
    "solid_build",
    "good_value",
    "easy_to_clean",
    "strong_performance",
    "good_packaging",
)

TAXONOMY_VERSION = "v1"

_POLARITY_WHITELIST = {
    "quality_stability": {"negative"},
    "structure_design": {"negative"},
    "assembly_installation": {"negative"},
    "material_finish": {"negative"},
    "cleaning_maintenance": {"negative"},
    "noise_power": {"negative"},
    "packaging_shipping": {"negative"},
    "service_fulfillment": {"negative", "positive"},  # bidirectional
    "easy_to_use": {"positive"},
    "solid_build": {"positive"},
    "good_value": {"positive"},
    "easy_to_clean": {"positive"},
    "strong_performance": {"positive"},
    "good_packaging": {"positive"},
}

_MAX_LABELS_PER_REVIEW = 3

_NEGATIVE_RULES = {
    "quality_stability": {
        "severity": "high",
        "confidence": 0.95,
        "keywords": (
            "broke",
            "broken",
            "breaks",
            "failed",
            "failure",
            "stopped working",
            "defect",
            "defective",
            "flimsy",
            "not durable",
            "坏了",
            "故障",
            "失灵",
            "不耐用",
            "损坏",
        ),
    },
    "structure_design": {
        "severity": "medium",
        "confidence": 0.9,
        "keywords": (
            "poor design",
            "design flaw",
            "awkward",
            "unstable",
            "wobbly",
            "too small",
            "too big",
            "设计问题",
            "结构问题",
            "不稳",
        ),
    },
    "assembly_installation": {
        "severity": "medium",
        "confidence": 0.9,
        "keywords": (
            "hard to assemble",
            "difficult to assemble",
            "difficult to install",
            "instructions unclear",
            "assembly was difficult",
            "安装困难",
            "组装困难",
            "说明书不清楚",
        ),
    },
    "material_finish": {
        "severity": "medium",
        "confidence": 0.88,
        "keywords": (
            "cheap plastic",
            "rust",
            "rusted",
            "rusting",
            "poor finish",
            "bad finish",
            "finish peeling",
            "finish chipping",
            "scratched",
            "scratch",
            "材料差",
            "做工差",
            "生锈",
            "毛刺",
        ),
    },
    "cleaning_maintenance": {
        "severity": "medium",
        "confidence": 0.88,
        "keywords": (
            "hard to clean",
            "difficult to clean",
            "messy to clean",
            "难清洗",
            "不好清洁",
        ),
    },
    "noise_power": {
        "severity": "high",
        "confidence": 0.92,
        "keywords": (
            "noisy",
            "too loud",
            "weak motor",
            "not powerful",
            "动力不足",
            "噪音",
            "太吵",
        ),
    },
    "packaging_shipping": {
        "severity": "medium",
        "confidence": 0.86,
        "keywords": (
            "damaged on arrival",
            "arrived damaged",
            "shipping damage",
            "packaging was damaged",
            "包装破损",
            "运输损坏",
            "箱子破了",
        ),
    },
    "service_fulfillment": {
        "severity": "low",
        "confidence": 0.82,
        "keywords": (
            "customer service",
            "missing parts",
            "wrong item",
            "late delivery",
            "客服",
            "漏件",
            "少件",
            "发错",
            "送错",
        ),
    },
}

_POSITIVE_RULES = {
    "easy_to_use": {
        "severity": "low",
        "confidence": 0.92,
        "keywords": (
            "easy to use",
            "simple to use",
            "easy setup",
            "easy setup",
            "user friendly",
            "easy assembly",
            "好上手",
            "简单易用",
            "安装简单",
            "使用方便",
        ),
    },
    "solid_build": {
        "severity": "medium",
        "confidence": 0.9,
        "keywords": (
            "solid build",
            "well made",
            "sturdy",
            "durable",
            "做工扎实",
            "结实",
            "质量好",
        ),
    },
    "good_value": {
        "severity": "low",
        "confidence": 0.86,
        "keywords": (
            "good value",
            "worth the money",
            "great value",
            "great price",
            "性价比高",
            "值得",
            "物有所值",
        ),
    },
    "easy_to_clean": {
        "severity": "low",
        "confidence": 0.9,
        "keywords": (
            "easy to clean",
            "cleans easily",
            "easy cleanup",
            "容易清洗",
            "清洗方便",
        ),
    },
    "strong_performance": {
        "severity": "medium",
        "confidence": 0.9,
        "keywords": (
            "works great",
            "great performance",
            "powerful motor",
            "powerful enough",
            "very powerful",
            "performs well",
            "动力强",
            "性能好",
        ),
    },
    "good_packaging": {
        "severity": "low",
        "confidence": 0.84,
        "keywords": (
            "well packaged",
            "packaged well",
            "arrived intact",
            "包装好",
            "包装严实",
        ),
    },
}

_SEVERITY_SCORE = {"high": 3, "medium": 2, "low": 1}

_RECOMMENDATION_MAP = {
    "quality_stability": {
        "possible_cause_boundary": "可能与核心部件耐久性、负载冗余或质检拦截不足有关",
        "improvement_direction": "优先复核高频失效部件寿命、材料和出厂老化测试",
    },
    "structure_design": {
        "possible_cause_boundary": "可能与结构支撑、尺寸匹配或人机设计不顺有关",
        "improvement_direction": "复核关键尺寸、公差和使用姿态，缩短用户完成主任务的步骤",
    },
    "assembly_installation": {
        "possible_cause_boundary": "可能与安装路径复杂、说明表达不足或配件定位不直观有关",
        "improvement_direction": "优先减少装配步骤并补强说明书、装配视频和定位结构",
    },
    "material_finish": {
        "possible_cause_boundary": "可能与外观件材料选择、表面处理或供应稳定性有关",
        "improvement_direction": "加强表面处理一致性和来料外观检验，降低廉价感",
    },
    "cleaning_maintenance": {
        "possible_cause_boundary": "可能与死角过多、拆洗路径不顺或污渍残留有关",
        "improvement_direction": "优化拆洗动线和易藏污部位，减少用户清洁阻力",
    },
    "noise_power": {
        "possible_cause_boundary": "可能与电机功率匹配、振动控制或隔音设计不足有关",
        "improvement_direction": "优先验证动力余量和噪声源，评估减振和隔音方案",
    },
    "packaging_shipping": {
        "possible_cause_boundary": "可能与包装缓冲、防护结构或物流跌落场景覆盖不足有关",
        "improvement_direction": "补强高风险边角防护和跌落测试，减少到货损伤",
    },
    "service_fulfillment": {
        "possible_cause_boundary": "可能与配件齐套、发货校验或售后 SOP 不一致有关",
        "improvement_direction": "复核配件清单和出库校验，压缩售后闭环时间",
    },
}


_NEGATION_WORDS = {"not", "no", "never", "don't", "doesn't", "didn't", "isn't", "wasn't",
                   "won't", "can't", "couldn't", "shouldn't", "wouldn't", "hardly",
                   "没有", "不", "不会", "没", "未", "无"}
_NEGATION_WINDOW = 4

_KEYWORD_PATTERN_CACHE: dict[str, re.Pattern] = {}


def _build_keyword_pattern(keyword: str) -> re.Pattern:
    cjk_chars = sum(1 for c in keyword if '\u4e00' <= c <= '\u9fff')
    if cjk_chars > len(keyword) / 2:
        return re.compile(re.escape(keyword))
    return re.compile(r'\b' + re.escape(keyword) + r'\b', re.IGNORECASE)


def _get_keyword_pattern(keyword: str) -> re.Pattern:
    if keyword not in _KEYWORD_PATTERN_CACHE:
        _KEYWORD_PATTERN_CACHE[keyword] = _build_keyword_pattern(keyword)
    return _KEYWORD_PATTERN_CACHE[keyword]


def _is_negated(text: str, match_start: int, keyword: str) -> bool:
    cjk_chars = sum(1 for c in keyword if '\u4e00' <= c <= '\u9fff')
    if cjk_chars > len(keyword) / 2:
        prefix = text[max(0, match_start - 4):match_start]
        return any(neg in prefix for neg in ("不", "没", "未", "无", "没有", "不会"))
    before_text = text[:match_start]
    words = before_text.split()
    preceding = words[-_NEGATION_WINDOW:] if words else []
    return any(w.lower().rstrip(".,;:!?") in _NEGATION_WORDS for w in preceding)


def _safe_date(value):
    return date.fromisoformat(value)


def _review_text(review):
    parts = [
        review.get("headline") or "",
        review.get("body") or "",
        review.get("headline_cn") or "",
        review.get("body_cn") or "",
    ]
    return " ".join(parts).lower()


def _review_images(review):
    images = review.get("images") or []
    if isinstance(images, str):
        try:
            images = json.loads(images)
        except Exception:
            images = []
    return images


def _product_key(product_name, product_sku):
    if product_sku:
        return product_sku
    return product_name or ""


def _group_products(products):
    grouped = {}
    for product in products:
        grouped[_product_key(product.get("name"), product.get("sku"))] = product
    return grouped


def _review_id(review):
    return review.get("id") or review.get("review_id")


def _match_rule(text: str, rule: dict) -> bool:
    for keyword in rule["keywords"]:
        pattern = _get_keyword_pattern(keyword)
        for m in pattern.finditer(text):
            if not _is_negated(text, m.start(), keyword):
                return True
    return False


def _label_item(label_code, label_polarity, rule):
    return {
        "label_code": label_code,
        "label_polarity": label_polarity,
        "severity": rule["severity"],
        "confidence": rule["confidence"],
        "source": "rule",
        "taxonomy_version": TAXONOMY_VERSION,
    }


def classify_review_labels(review):
    text = _review_text(review)
    negative = []
    positive = []
    for label_code, rule in _NEGATIVE_RULES.items():
        if _match_rule(text, rule):
            negative.append(_label_item(label_code, "negative", rule))
    for label_code, rule in _POSITIVE_RULES.items():
        if _match_rule(text, rule):
            positive.append(_label_item(label_code, "positive", rule))

    ownership = review.get("ownership") or ""
    labels = positive + negative if ownership == "competitor" else negative + positive
    labels.sort(
        key=lambda item: (
            0 if ownership == "competitor" and item["label_polarity"] == "positive" else 1
            if ownership == "competitor"
            else 0 if item["label_polarity"] == "negative" else 1,
            -_SEVERITY_SCORE[item["severity"]],
            -item["confidence"],
            item["label_code"],
        )
    )
    return labels


def detect_report_mode(run_id, logical_date):
    current_date = _safe_date(logical_date)
    since_date = (current_date - timedelta(days=30)).isoformat()
    conn = models.get_conn()
    try:
        rows = conn.execute(
            """
            SELECT id, logical_date
            FROM workflow_runs
            WHERE workflow_type = 'daily'
              AND status = 'completed'
              AND analytics_path IS NOT NULL
              AND analytics_path != ''
              AND logical_date >= ?
              AND logical_date < ?
              AND id != ?
            ORDER BY logical_date ASC, id ASC
            """,
            (since_date, logical_date, run_id),
        ).fetchall()
    finally:
        conn.close()

    baseline_run_ids = [row["id"] for row in rows]
    baseline_sample_days = len(rows)
    return {
        "mode": "incremental" if baseline_sample_days >= 3 else "baseline",
        "baseline_run_ids": baseline_run_ids,
        "baseline_sample_days": baseline_sample_days,
    }


def _maybe_normalize_labels_with_llm(review_labels):
    return {}


def _sanitize_hybrid_labels(candidate_labels, llm_labels):
    if not llm_labels:
        return []

    allowed_codes = {item["label_code"] for item in candidate_labels}
    sanitized = []
    for item in llm_labels:
        if item.get("label_code") not in allowed_codes:
            continue
        if item.get("label_polarity") not in {"negative", "positive"}:
            continue
        if item.get("severity") not in _SEVERITY_SCORE:
            continue
        sanitized.append(
            {
                "label_code": item["label_code"],
                "label_polarity": item["label_polarity"],
                "severity": item["severity"],
                "confidence": item.get("confidence", 0.9),
                "source": item.get("source", "llm"),
                "taxonomy_version": TAXONOMY_VERSION,
            }
        )
    return sanitized


def _extract_validated_llm_labels(review):
    """Extract and validate LLM labels from review's analysis_labels field.

    Maps LLM field names (code/polarity) to downstream names (label_code/label_polarity).
    Filters by polarity whitelist and caps at _MAX_LABELS_PER_REVIEW by confidence.
    """
    raw = review.get("analysis_labels") or "[]"
    if isinstance(raw, str):
        try:
            items = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
    else:
        items = raw

    if not isinstance(items, list):
        return []

    validated = []
    for item in items:
        if not isinstance(item, dict):
            continue
        code = item.get("code", "")
        polarity = item.get("polarity", "")
        allowed = _POLARITY_WHITELIST.get(code)
        if not allowed or polarity not in allowed:
            continue
        validated.append({
            "label_code": code,
            "label_polarity": polarity,
            "severity": item.get("severity", "low"),
            "confidence": item.get("confidence", 0.5),
            "source": "llm",
            "taxonomy_version": TAXONOMY_VERSION,
        })

    validated.sort(key=lambda l: -l["confidence"])
    return validated[:_MAX_LABELS_PER_REVIEW]


def sync_review_labels(snapshot):
    all_labels = {}
    for review in snapshot.get("reviews") or []:
        review_id = _review_id(review)
        if not review_id:
            continue

        # Primary: validated LLM labels
        labels = _extract_validated_llm_labels(review)

        if not labels:
            # Fallback: rule-based classification
            labels = classify_review_labels(review)

        models.replace_review_issue_labels(review_id, labels)
        all_labels[review_id] = labels

    # Keep hybrid branch for future use (currently no-op)
    if config.REPORT_LABEL_MODE == "hybrid" and all_labels:
        sample_review_ids = [rid for rid, labels in all_labels.items() if labels][:20]
        normalized_labels = _maybe_normalize_labels_with_llm(
            {rid: all_labels[rid] for rid in sample_review_ids}
        )
        for rid in sample_review_ids:
            llm_labels = _sanitize_hybrid_labels(all_labels[rid], normalized_labels.get(rid))
            if llm_labels:
                models.replace_review_issue_labels(rid, llm_labels)

    return models.list_review_issue_labels(list(all_labels))


def _build_labeled_reviews(snapshot, synced_labels=None):
    products = _group_products(snapshot.get("products") or [])
    labeled_reviews = []
    for review in snapshot.get("reviews") or []:
        product_key = _product_key(review.get("product_name"), review.get("product_sku"))
        product = products.get(product_key, {})
        # Use synced labels if available, otherwise classify
        review_id = _review_id(review)
        if synced_labels and review_id and review_id in synced_labels:
            labels = synced_labels[review_id]
        else:
            labels = classify_review_labels(review)
        labeled_reviews.append(
            {
                "review": review,
                "labels": labels,
                "product": product,
                "images": _review_images(review),
            }
        )
    return labeled_reviews


def _cluster_summary_items(labeled_reviews, *, ownership, polarity):
    grouped = {}
    for item in labeled_reviews:
        review = item["review"]
        if review.get("ownership") != ownership:
            continue
        for label in item["labels"]:
            if label["label_polarity"] != polarity:
                continue
            cluster = grouped.setdefault(
                label["label_code"],
                {
                    "label_code": label["label_code"],
                    "label_polarity": label["label_polarity"],
                    "review_count": 0,
                    "image_review_count": 0,
                    "severity": label["severity"],
                    "severity_score": _SEVERITY_SCORE[label["severity"]],
                    "example_reviews": [],
                    "affected_products": set(),
                    "dates": [],
                },
            )
            cluster["review_count"] += 1
            cluster["affected_products"].add(review.get("product_sku") or review.get("product_name"))
            if review.get("date_published"):
                cluster["dates"].append(review["date_published"])
            if item["images"]:
                cluster["image_review_count"] += 1
            cluster["severity_score"] = max(cluster["severity_score"], _SEVERITY_SCORE[label["severity"]])
            if _SEVERITY_SCORE[label["severity"]] > _SEVERITY_SCORE[cluster["severity"]]:
                cluster["severity"] = label["severity"]
            if len(cluster["example_reviews"]) < 3:
                cluster["example_reviews"].append(
                    {
                        "product_name": review.get("product_name"),
                        "product_sku": review.get("product_sku"),
                        "author": review.get("author"),
                        "rating": review.get("rating"),
                        "headline": review.get("headline"),
                        "body": review.get("body"),
                        "headline_cn": review.get("headline_cn"),
                        "body_cn": review.get("body_cn"),
                        "headline_en": review.get("headline", ""),
                        "body_en": review.get("body", ""),
                        "date_published": review.get("date_published", ""),
                        "images": item["images"],
                    }
                )

    items = list(grouped.values())
    items.sort(
        key=lambda item: (
            -item["review_count"],
            -item["severity_score"],
            -item["image_review_count"],
            item["label_code"],
        )
    )
    from qbu_crawler.server.report_common import _LABEL_DISPLAY

    for item in items:
        item.pop("severity_score")
        item["label_display"] = _LABEL_DISPLAY.get(item["label_code"], item["label_code"])
        item["severity_display"] = {"high": "高", "medium": "中", "low": "低"}.get(item["severity"], item["severity"])
        item["affected_product_count"] = len(item.pop("affected_products"))
        dates = item.pop("dates")
        sorted_dates = sorted(dates, key=_date_sort_key)
        item["first_seen"] = sorted_dates[0] if sorted_dates else None
        item["last_seen"] = sorted_dates[-1] if sorted_dates else None
    return items


def _risk_products(labeled_reviews, snapshot_products=None):
    sku_to_review_count = {}
    sku_to_rating = {}
    for p in (snapshot_products or []):
        sku = p.get("sku") or ""
        sku_to_review_count[sku] = p.get("review_count") or 0
        sku_to_rating[sku] = p.get("rating")

    grouped = {}
    for item in labeled_reviews:
        review = item["review"]
        if review.get("ownership") != "own":
            continue
        # Rating gate: only reviews at or below threshold contribute to risk
        rating = float(review.get("rating") or 0)
        if rating > config.LOW_RATING_THRESHOLD:
            continue
        negative_labels = [label for label in item["labels"] if label["label_polarity"] == "negative"]
        if not negative_labels:
            continue
        key = _product_key(review.get("product_name"), review.get("product_sku"))
        product = grouped.setdefault(
            key,
            {
                "product_name": review.get("product_name"),
                "product_sku": review.get("product_sku"),
                "negative_review_rows": 0,
                "image_review_rows": 0,
                "risk_score": 0,
                "total_reviews": sku_to_review_count.get(review.get("product_sku", ""), 0),
                "rating_avg": sku_to_rating.get(review.get("product_sku", "")),
                "negative_rate": None,
                "top_labels": {},
            },
        )
        product["negative_review_rows"] += 1
        if item["images"]:
            product["image_review_rows"] += 1
        rating = review.get("rating") or 0
        product["risk_score"] += 2 if rating and float(rating) <= 2 else 1
        if item["images"]:
            product["risk_score"] += 1
        for label in negative_labels:
            product["risk_score"] += _SEVERITY_SCORE[label["severity"]]
            product["top_labels"][label["label_code"]] = product["top_labels"].get(label["label_code"], 0) + 1

    items = list(grouped.values())
    items.sort(
        key=lambda item: (
            -item["risk_score"],
            -item["negative_review_rows"],
            -item["image_review_rows"],
            item["product_sku"] or "",
        )
    )
    from qbu_crawler.server.report_common import _join_label_counts

    for item in items:
        label_counts = item.pop("top_labels")
        item["top_labels"] = [
            {"label_code": code, "count": count}
            for code, count in sorted(label_counts.items(), key=lambda pair: (-pair[1], pair[0]))
        ]
        total = item.get("total_reviews") or 0
        neg = item.get("negative_review_rows", 0)
        item["negative_rate"] = neg / total if total else None
        item["top_features_display"] = _join_label_counts(item["top_labels"])
    return items


def _recommendations(top_negative_clusters):
    items = []
    for cluster in top_negative_clusters[:5]:
        content = _RECOMMENDATION_MAP.get(cluster["label_code"])
        if not content:
            continue

        # Extract concrete evidence from example reviews
        examples = cluster.get("example_reviews") or []
        top_complaint = ""
        affected_products = []
        seen_products = set()
        for ex in examples:
            if not top_complaint:
                top_complaint = (
                    (ex.get("headline_cn") or ex.get("headline") or "")
                    + "："
                    + (ex.get("body_cn") or ex.get("body") or "")
                ).strip().rstrip("：")[:120]
            pname = ex.get("product_name") or ""
            if pname and pname not in seen_products:
                seen_products.add(pname)
                affected_products.append(pname)

        items.append(
            {
                "label_code": cluster["label_code"],
                "priority": "high" if cluster["severity"] == "high" else "medium",
                "possible_cause_boundary": content["possible_cause_boundary"],
                "improvement_direction": content["improvement_direction"],
                "evidence_count": cluster["review_count"],
                "top_complaint": top_complaint,
                "affected_products": affected_products[:3],
            }
        )
    return items


def _benchmark_examples(labeled_reviews):
    items = []
    for item in labeled_reviews:
        review = item["review"]
        if review.get("ownership") != "competitor":
            continue
        positive_labels = [label["label_code"] for label in item["labels"] if label["label_polarity"] == "positive"]
        if not positive_labels:
            continue
        items.append(
            {
                "product_name": review.get("product_name"),
                "product_sku": review.get("product_sku"),
                "author": review.get("author"),
                "rating": review.get("rating"),
                "headline": review.get("headline"),
                "body": review.get("body"),
                "headline_cn": review.get("headline_cn"),
                "body_cn": review.get("body_cn"),
                "label_codes": positive_labels,
            }
        )
    items.sort(key=lambda item: (-(item["rating"] or 0), len(item["label_codes"]) * -1, item["product_sku"] or ""))
    return items[:5]


def _negative_opportunities(labeled_reviews):
    items = []
    for item in labeled_reviews:
        review = item["review"]
        if review.get("ownership") != "competitor":
            continue
        negative_labels = [label["label_code"] for label in item["labels"] if label["label_polarity"] == "negative"]
        if not negative_labels:
            continue
        items.append(
            {
                "product_name": review.get("product_name"),
                "product_sku": review.get("product_sku"),
                "rating": review.get("rating"),
                "headline": review.get("headline"),
                "body": review.get("body"),
                "label_codes": negative_labels,
            }
        )
    items.sort(key=lambda item: ((item["rating"] or 5), item["product_sku"] or ""))
    return items[:5]


def _build_feature_clusters(reviews_with_analysis, ownership="own", polarity="negative"):
    """Aggregate reviews into clusters grouped by ``label_code``.

    Instead of clustering by free-text feature strings (which creates 100+
    fragmented clusters), this groups reviews by their primary
    ``analysis_labels[].code`` — a fixed 14-code taxonomy.  Original feature
    strings are preserved in ``sub_features``.

    Reviews whose labels have no ``code`` matching the target *polarity* fall
    into the ``_uncategorized`` bucket.
    """
    from collections import defaultdict
    from qbu_crawler.server.report_common import _LABEL_DISPLAY

    clusters = defaultdict(lambda: {
        "reviews": [],
        "products": set(),
        "severities": [],
        "sub_features": defaultdict(int),
    })

    for r in reviews_with_analysis:
        if r.get("ownership") != ownership:
            continue
        sentiment = r.get("sentiment") or ""
        if polarity == "negative" and sentiment not in ("negative", "mixed"):
            continue
        if polarity == "positive" and sentiment not in ("positive", "mixed"):
            continue

        raw_features = r.get("analysis_features") or r.get("features") or "[]"
        raw_labels = r.get("analysis_labels") or r.get("labels") or "[]"
        features = json.loads(raw_features) if isinstance(raw_features, str) else raw_features
        labels = json.loads(raw_labels) if isinstance(raw_labels, str) else raw_labels

        if not features:
            continue

        # Find primary label_code: highest-confidence label matching target polarity
        primary_code = None
        primary_severity = "low"
        best_confidence = -1.0
        for label in labels:
            if not isinstance(label, dict):
                continue
            code = label.get("code") or label.get("label_code")
            lab_polarity = label.get("polarity") or label.get("label_polarity")
            if not code:
                continue
            if lab_polarity and lab_polarity != polarity:
                continue
            confidence = label.get("confidence", 0.0)
            if confidence > best_confidence:
                best_confidence = confidence
                primary_code = code
                primary_severity = label.get("severity", "low")

        # Fallback: if no polarity-matching label found, use _uncategorized
        if not primary_code:
            primary_code = "_uncategorized"
            # Still extract max severity from all labels
            for label in labels:
                if isinstance(label, dict):
                    sev = label.get("severity", "low")
                    if _SEVERITY_SCORE.get(sev, 0) > _SEVERITY_SCORE.get(primary_severity, 0):
                        primary_severity = sev

        bucket = clusters[primary_code]
        bucket["reviews"].append(r)
        bucket["products"].add(r.get("product_sku") or r.get("product_name", ""))
        bucket["severities"].append(primary_severity)

        for feat in features:
            feat = feat.strip() if isinstance(feat, str) else str(feat)
            if feat:
                bucket["sub_features"][feat] += 1

    result = []
    for code, data in clusters.items():
        reviews = data["reviews"]
        dates = [r.get("date_published") for r in reviews if r.get("date_published")]
        max_sev = max(data["severities"], key=lambda s: _SEVERITY_SCORE.get(s, 0), default="low")
        display = _LABEL_DISPLAY.get(code, code)

        sub_features = [
            {"feature": feat, "count": cnt}
            for feat, cnt in sorted(data["sub_features"].items(), key=lambda x: -x[1])
        ]

        result.append({
            "label_code": code,
            "feature_display": display,
            "label_display": display,
            "label_polarity": polarity,
            "review_count": len(reviews),
            "affected_product_count": len(data["products"]),
            "severity": max_sev,
            "severity_display": {"high": "高", "medium": "中", "low": "低"}.get(max_sev, max_sev),
            "first_seen": sorted(dates, key=_date_sort_key)[0] if dates else None,
            "last_seen": sorted(dates, key=_date_sort_key)[-1] if dates else None,
            "example_reviews": sorted(reviews, key=lambda r: r.get("rating", 5))[:3],
            "image_review_count": sum(1 for r in reviews if r.get("images")),
            "sub_features": sub_features,
        })

    result.sort(key=lambda c: (
        -c["review_count"],
        -_SEVERITY_SCORE.get(c["severity"], 0),
        -c["image_review_count"],
    ))
    return result


def _has_review_analysis_data(reviews):
    """Check if any review in the snapshot has analysis_features populated."""
    for r in reviews:
        features = r.get("analysis_features") or r.get("features")
        if features and features != "[]":
            return True
    return False


def _compute_chart_data(labeled_reviews, snapshot):
    """Compute chart-specific analytics data for Plotly visualizations."""
    from qbu_crawler.server.report_common import _LABEL_DISPLAY

    # All label codes that appear in labeled reviews
    DIMENSIONS = list(set(
        label["label_code"]
        for item in labeled_reviews
        for label in item["labels"]
    ))
    if not DIMENSIONS:
        return {}

    result = {}

    # ── Radar data: own vs competitor positive ratio per dimension ─────
    own_dim_pos = {}
    own_dim_total = {}
    comp_dim_pos = {}
    comp_dim_total = {}
    for item in labeled_reviews:
        ownership = item["review"].get("ownership")
        for label in item["labels"]:
            code = label["label_code"]
            if ownership == "own":
                own_dim_total[code] = own_dim_total.get(code, 0) + 1
                if label["label_polarity"] == "positive":
                    own_dim_pos[code] = own_dim_pos.get(code, 0) + 1
            else:
                comp_dim_total[code] = comp_dim_total.get(code, 0) + 1
                if label["label_polarity"] == "positive":
                    comp_dim_pos[code] = comp_dim_pos.get(code, 0) + 1

    # Only include dimensions that have data from BOTH sides
    radar_dims = [d for d in DIMENSIONS if own_dim_total.get(d, 0) > 0 and comp_dim_total.get(d, 0) > 0]
    if len(radar_dims) >= 3:
        result["_radar_data"] = {
            "categories": [_LABEL_DISPLAY.get(d, d) for d in radar_dims],
            "own_values": [
                round(own_dim_pos.get(d, 0) / max(own_dim_total.get(d, 1), 1), 2)
                for d in radar_dims
            ],
            "competitor_values": [
                round(comp_dim_pos.get(d, 0) / max(comp_dim_total.get(d, 1), 1), 2)
                for d in radar_dims
            ],
        }

    # ── Sentiment distribution: split by ownership ─────────────────
    products = snapshot.get("products") or []
    for ownership_tag in ("own", "competitor"):
        product_names = []
        pos_counts = []
        neu_counts = []
        neg_counts = []
        for p in products:
            if p.get("ownership", "competitor") != ownership_tag:
                continue
            pname = p.get("name") or p.get("sku") or "?"
            psku = p.get("sku") or ""
            pos = neu = neg = 0
            for item in labeled_reviews:
                r = item["review"]
                if (r.get("product_sku") or "") == psku or (r.get("product_name") or "") == pname:
                    rating = float(r.get("rating") or 0)
                    if rating >= 4:
                        pos += 1
                    elif rating <= 2:
                        neg += 1
                    else:
                        neu += 1
            if pos + neu + neg > 0:
                product_names.append(pname[:20])
                pos_counts.append(pos)
                neu_counts.append(neu)
                neg_counts.append(neg)

        if len(product_names) >= 2:
            key = f"_sentiment_distribution_{ownership_tag}"
            result[key] = {
                "categories": product_names,
                "positive": pos_counts,
                "neutral": neu_counts,
                "negative": neg_counts,
            }

    # ── Heatmap: product × dimension sentiment score (-1 to 1) ─────────
    # Only for own products with at least some labels
    own_products = [p for p in products if p.get("ownership") == "own"]
    heatmap_dims = sorted(set(
        label["label_code"]
        for item in labeled_reviews
        if item["review"].get("ownership") == "own"
        for label in item["labels"]
    ))
    if len(own_products) >= 2 and len(heatmap_dims) >= 2:
        y_labels = []
        z = []
        for p in own_products:
            psku = p.get("sku") or ""
            pname = p.get("name") or "?"
            row = []
            has_data = False
            for dim in heatmap_dims:
                pos = neg = 0
                for item in labeled_reviews:
                    r = item["review"]
                    if (r.get("product_sku") or "") != psku:
                        continue
                    for label in item["labels"]:
                        if label["label_code"] == dim:
                            if label["label_polarity"] == "positive":
                                pos += 1
                            else:
                                neg += 1
                total = pos + neg
                if total > 0:
                    has_data = True
                    row.append(round((pos - neg) / total, 2))
                else:
                    row.append(0.0)
            if has_data:
                y_labels.append(pname[:25])
                z.append(row)

        if len(y_labels) >= 2:
            result["_heatmap_data"] = {
                "z": z,
                "x_labels": [_LABEL_DISPLAY.get(d, d) for d in heatmap_dims],
                "y_labels": y_labels,
            }

    return result


def build_report_analytics(snapshot, synced_labels=None):
    mode_info = detect_report_mode(snapshot.get("run_id", 0), snapshot["logical_date"])
    labeled_reviews = _build_labeled_reviews(snapshot, synced_labels=synced_labels)

    # Determine if review_analysis data is available for feature-based clustering
    snapshot_reviews = snapshot.get("reviews") or []
    use_feature_clusters = _has_review_analysis_data(snapshot_reviews)

    if use_feature_clusters:
        top_negative_clusters = _build_feature_clusters(snapshot_reviews, ownership="own", polarity="negative")
        top_positive_themes = _build_feature_clusters(snapshot_reviews, ownership="competitor", polarity="positive")
    else:
        top_negative_clusters = _cluster_summary_items(labeled_reviews, ownership="own", polarity="negative")
        top_positive_themes = _cluster_summary_items(labeled_reviews, ownership="competitor", polarity="positive")
    image_reviews = []
    for item in labeled_reviews:
        if item["images"]:
            review = item["review"]
            image_reviews.append(
                {
                    "product_name": review.get("product_name"),
                    "product_sku": review.get("product_sku"),
                    "ownership": review.get("ownership"),
                    "rating": review.get("rating"),
                    "headline": review.get("headline"),
                    "body": review.get("body"),
                    "images": item["images"],
                }
            )

    own_products = [product for product in snapshot.get("products") or [] if product.get("ownership") == "own"]
    competitor_products = [
        product for product in snapshot.get("products") or [] if product.get("ownership") == "competitor"
    ]
    own_reviews = [item for item in labeled_reviews if item["review"].get("ownership") == "own"]
    competitor_reviews = [item for item in labeled_reviews if item["review"].get("ownership") == "competitor"]

    # Compute own_avg_rating from own products
    own_ratings = [p.get("rating") for p in own_products if p.get("rating")]
    own_avg_rating = round(sum(own_ratings) / len(own_ratings), 2) if own_ratings else 0

    # sample_avg_rating: average from actual reviews in this window (leading)
    own_review_ratings = [
        float(r["review"].get("rating") or 0) for r in own_reviews
        if r["review"].get("rating")
    ]
    sample_avg_rating = round(sum(own_review_ratings) / len(own_review_ratings), 2) if own_review_ratings else own_avg_rating

    # Use config.NEGATIVE_THRESHOLD for negative review counting
    negative_threshold = config.NEGATIVE_THRESHOLD

    # _products_for_charts: used by price-rating quadrant chart
    products_for_charts = [
        {
            "name": p.get("name", ""),
            "sku": p.get("sku", ""),
            "price": float(p.get("price") or 0),
            "rating": float(p.get("rating") or 0),
            "ownership": p.get("ownership", "competitor"),
        }
        for p in (snapshot.get("products") or [])
        if p.get("price") and p.get("rating")
    ]

    # Chart-specific analytics data (radar, heatmap, sentiment distribution)
    chart_data = _compute_chart_data(labeled_reviews, snapshot)

    # Compute recently_published_count: reviews published within 30 days of logical_date
    from qbu_crawler.server.report_common import _parse_date_flexible
    from datetime import date as _date, timedelta as _timedelta
    logical = _date.fromisoformat(snapshot["logical_date"])
    recent_cutoff = logical - _timedelta(days=30)
    recently_published_count = 0
    for review in snapshot_reviews:
        pub_date = _parse_date_flexible(review.get("date_published"))
        if pub_date and pub_date >= recent_cutoff:
            recently_published_count += 1

    return {
        "run_id": snapshot.get("run_id"),
        "logical_date": snapshot["logical_date"],
        "snapshot_hash": snapshot["snapshot_hash"],
        "mode": mode_info["mode"],
        "baseline_run_ids": mode_info["baseline_run_ids"],
        "baseline_sample_days": mode_info["baseline_sample_days"],
        "taxonomy_version": TAXONOMY_VERSION,
        "label_mode": config.REPORT_LABEL_MODE,
        "generated_at": config.now_shanghai().isoformat(),
        "_products_for_charts": products_for_charts,
        "metric_semantics": {
            "ingested_review_rows": "reviews 实际入库行数（按 scraped_at 窗口，含历史补采）",
            "recently_published_count": "其中 date_published 在近 30 天内的评论数",
            "site_reported_review_total_current": "products.review_count 当前站点展示总评论数",
        },
        "kpis": {
            "product_count": len(snapshot.get("products") or []),
            "ingested_review_rows": len(snapshot.get("reviews") or []),
            "site_reported_review_total_current": sum((product.get("review_count") or 0) for product in snapshot.get("products") or []),
            "translated_count": snapshot.get("translated_count", 0),
            "untranslated_count": snapshot.get("untranslated_count", 0),
            "own_product_count": len(own_products),
            "competitor_product_count": len(competitor_products),
            "own_review_rows": len(own_reviews),
            "competitor_review_rows": len(competitor_reviews),
            "image_review_rows": len(image_reviews),
            "own_avg_rating": own_avg_rating,
            "sample_avg_rating": sample_avg_rating,
            "negative_review_rows": sum(
                1 for review in snapshot_reviews if (review.get("rating") or 0) <= negative_threshold
            ),
            "own_negative_review_rows": sum(
                1 for r in own_reviews if (r.get("review", {}).get("rating") or 0) <= negative_threshold
            ),
            "own_negative_review_rate": (
                sum(1 for r in own_reviews if (r.get("review", {}).get("rating") or 0) <= negative_threshold)
                / max(len(own_reviews), 1)
            ),
            "low_rating_review_rows": sum(
                1 for review in snapshot_reviews if (review.get("rating") or 0) <= config.LOW_RATING_THRESHOLD
            ),
            "recently_published_count": recently_published_count,
        },
        "self": {
            "risk_products": _risk_products(labeled_reviews, snapshot_products=snapshot.get("products", [])),
            "top_negative_clusters": top_negative_clusters,
            "recommendations": _recommendations(top_negative_clusters),
        },
        "competitor": {
            "top_positive_themes": top_positive_themes,
            "benchmark_examples": _benchmark_examples(labeled_reviews),
            "negative_opportunities": _negative_opportunities(labeled_reviews),
        },
        "appendix": {
            "image_reviews": image_reviews[:10],
            "coverage": {
                "own_products": len(own_products),
                "competitor_products": len(competitor_products),
                "own_reviews": len(own_reviews),
                "competitor_reviews": len(competitor_reviews),
            },
        },
        **chart_data,
    }
