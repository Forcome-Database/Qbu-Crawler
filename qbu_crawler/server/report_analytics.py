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

_SEVERITY_SCORE = {"critical": 4, "high": 3, "medium": 2, "low": 1}

_SAFETY_KEYWORDS = frozenset({
    "metal shaving", "metal debris", "metal flake", "metal particle",
    "broke", "broken", "snapped", "shattered", "exploded",
    "dangerous", "hazard", "injury", "hurt", "unsafe",
    "rust", "rusted", "corrosion",
    "金属屑", "金属碎", "断裂", "爆裂", "危险", "安全", "锈",
})


def compute_cluster_severity(cluster, reviews_in_cluster, logical_date):
    """Compute severity at cluster level from volume, breadth, recency, safety.

    Args:
        cluster: dict with review_count, affected_product_count, review_dates
        reviews_in_cluster: list of review dicts (for safety keyword scan)
        logical_date: date object for recency calculation

    Returns one of: "critical", "high", "medium", "low".
    """
    from datetime import datetime, timedelta

    review_count = cluster.get("review_count", 0)
    affected_products = cluster.get("affected_product_count", 0)

    # Recency: count reviews from last 90 days
    recent_cutoff = logical_date - timedelta(days=90)
    recent_count = 0
    for d in cluster.get("review_dates", []):
        try:
            if datetime.strptime(d, "%Y-%m-%d").date() >= recent_cutoff:
                recent_count += 1
        except (ValueError, TypeError):
            pass
    recency_rate = recent_count / max(review_count, 1)

    # Safety signal
    has_safety = False
    for r in reviews_in_cluster:
        text = f"{r.get('headline', '')} {r.get('body', '')}".lower()
        if any(kw in text for kw in _SAFETY_KEYWORDS):
            has_safety = True
            break

    score = 0
    if review_count >= 20:
        score += 3
    elif review_count >= 10:
        score += 2
    elif review_count >= 5:
        score += 1

    if affected_products >= 3:
        score += 2
    elif affected_products >= 2:
        score += 1

    if recency_rate >= 0.30:
        score += 2
    elif recency_rate >= 0.10:
        score += 1

    if has_safety:
        score += 3

    if score >= 7:
        return "critical"
    if score >= 5:
        return "high"
    if score >= 3:
        return "medium"
    return "low"


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
            pub_date = review.get("date_published_parsed") or review.get("date_published")
            if pub_date:
                cluster["dates"].append(pub_date)
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
        from qbu_crawler.server.report_common import _SEVERITY_DISPLAY
        item["label_display"] = _LABEL_DISPLAY.get(item["label_code"], item["label_code"])
        item["severity_display"] = _SEVERITY_DISPLAY.get(item["severity"], item["severity"])
        item["affected_product_count"] = len(item.pop("affected_products"))
        dates = item.pop("dates")
        sorted_dates = sorted(dates, key=_date_sort_key)
        item["first_seen"] = sorted_dates[0] if sorted_dates else None
        item["last_seen"] = sorted_dates[-1] if sorted_dates else None
        item["review_dates"] = sorted_dates  # needed by compute_cluster_severity recency factor
    return items


def _risk_products(labeled_reviews, snapshot_products=None, logical_date=None):
    """Compute per-product risk scores using a 5-factor weighted algorithm.

    Factors (weights):
      neg_rate    (35%): negative reviews / total reviews (site-reported)
      severity    (25%): average severity of negative reviews, normalised 0–1
      evidence    (15%): image-bearing negatives / total negatives
      recency     (15%): proportion of negatives from last 90 days
      volume_sig  (10%): min(neg_count / 10, 1.0) — statistical significance

    A review is "negative" when rating <= config.NEGATIVE_THRESHOLD (default 2).
    Reviews without labels still count toward neg_rate.
    """
    from qbu_crawler.server.report_common import _join_label_counts, _parse_date_flexible

    # Reference date for recency calculation
    if logical_date:
        try:
            ref_date = date.fromisoformat(logical_date) if isinstance(logical_date, str) else logical_date
        except (ValueError, TypeError):
            ref_date = date.today()
    else:
        ref_date = date.today()
    recency_window = timedelta(days=90)

    # Severity weights for the severity factor (normalised against max = "critical")
    max_severity_score = float(_SEVERITY_SCORE.get("critical", max(_SEVERITY_SCORE.values())))

    sku_to_review_count = {}
    sku_to_rating = {}
    for p in (snapshot_products or []):
        sku = p.get("sku") or ""
        sku_to_review_count[sku] = p.get("review_count") or 0
        sku_to_rating[sku] = p.get("rating")

    # First pass: group ALL own reviews by SKU
    by_sku = {}
    for item in labeled_reviews:
        review = item["review"]
        if review.get("ownership") != "own":
            continue
        sku = review.get("product_sku", "")
        if not sku:
            continue
        entry = by_sku.setdefault(sku, {
            "product_name": review.get("product_name"),
            "product_sku": sku,
            "all_items": [],
            "negative_items": [],
            "image_negative_count": 0,
            "top_labels": {},
        })
        entry["all_items"].append(item)
        rating = float(review.get("rating") or 0)
        if rating <= config.NEGATIVE_THRESHOLD:
            entry["negative_items"].append(item)
            if item.get("images"):
                entry["image_negative_count"] += 1
            for label in item.get("labels", []):
                if label.get("label_polarity") == "negative":
                    lc = label["label_code"]
                    entry["top_labels"][lc] = entry["top_labels"].get(lc, 0) + 1

    # Second pass: compute 5-factor score per SKU
    items = []
    for sku, entry in by_sku.items():
        all_count = len(entry["all_items"])
        neg_items = entry["negative_items"]
        neg_count = len(neg_items)
        total_reviews = sku_to_review_count.get(sku, 0)

        # ── factor 1: neg_rate (35%) ──────────────────────────────
        # Use site-reported total when available; fall back to ingested count
        denom = total_reviews if total_reviews > 0 else all_count
        neg_rate = (neg_count / denom) if denom > 0 else 0.0

        if neg_count == 0:
            risk_score_raw = 0.0
        else:
            # ── factor 2: severity_avg (25%) ─────────────────────
            # Per-review-max: take max severity per review, normalise, then average
            severity_scores = []
            for neg_item in neg_items:
                neg_labels = [l for l in neg_item.get("labels", []) if l.get("label_polarity") == "negative"]
                if neg_labels:
                    max_sev = max(_SEVERITY_SCORE.get(l.get("severity", "low"), 1) for l in neg_labels)
                else:
                    max_sev = 2 if float(neg_item["review"].get("rating", 0)) <= 1 else 1
                severity_scores.append(max_sev / max_severity_score)
            severity_avg = sum(severity_scores) / len(severity_scores) if severity_scores else 0.0

            # ── factor 3: evidence_rate (15%) ────────────────────
            evidence_rate = entry["image_negative_count"] / neg_count

            # ── factor 4: recency (15%) ──────────────────────────
            recent_neg = 0
            for neg_item in neg_items:
                review = neg_item["review"]
                raw_parsed = review.get("date_published_parsed")
                pub_date = _parse_date_flexible(raw_parsed) if raw_parsed else None
                if pub_date is None:
                    pub_date = _parse_date_flexible(review.get("date_published"))
                if pub_date and (ref_date - pub_date) <= recency_window:
                    recent_neg += 1
            recency = recent_neg / neg_count

            # ── factor 5: volume_sig (10%) ───────────────────────
            volume_sig = min(neg_count / 10.0, 1.0)

            # ── weighted combination ──────────────────────────────
            risk_score_raw = (
                0.35 * neg_rate
                + 0.25 * severity_avg
                + 0.15 * evidence_rate
                + 0.15 * recency
                + 0.10 * volume_sig
            )

        risk_score = round(min(risk_score_raw, 1.0) * 100, 1)

        label_counts = entry["top_labels"]
        top_labels = [
            {"label_code": code, "count": count}
            for code, count in sorted(label_counts.items(), key=lambda pair: (-pair[1], pair[0]))
        ]

        ingested = all_count
        negative_review_rows = neg_count
        image_review_rows = entry["image_negative_count"]

        items.append({
            "product_name": entry["product_name"],
            "product_sku": sku,
            "negative_review_rows": negative_review_rows,
            "image_review_rows": image_review_rows,
            "risk_score_raw": risk_score_raw,
            "risk_score": risk_score,
            "total_reviews": total_reviews,
            "ingested_reviews": ingested,
            "rating_avg": sku_to_rating.get(sku),
            "negative_rate": neg_count / total_reviews if total_reviews else None,
            "coverage_rate": ingested / total_reviews if total_reviews else None,
            "top_labels": top_labels,
            "top_features_display": _join_label_counts(top_labels),
        })

    items.sort(
        key=lambda item: (
            -item["risk_score"],
            -item["negative_review_rows"],
            -item["image_review_rows"],
            item["product_sku"] or "",
        )
    )
    # Exclude zero-risk products (no negative reviews) from output
    items = [item for item in items if item["risk_score"] > 0]
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

        # Use top sub_features for product-specific actionable detail
        sub_features = cluster.get("sub_features") or []
        top_symptoms = "、".join(
            sf["feature"] for sf in sub_features[:5] if sf.get("feature")
        )

        items.append(
            {
                "label_code": cluster["label_code"],
                "priority": "high" if cluster["severity"] == "high" else "medium",
                "possible_cause_boundary": content["possible_cause_boundary"],
                "improvement_direction": content["improvement_direction"],
                "top_symptoms": top_symptoms,
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


def _select_diverse_examples(reviews, max_count=3):
    """Select diverse example reviews: lowest-rated + with-image + mid-range."""
    if len(reviews) <= max_count:
        return sorted(reviews, key=lambda r: r.get("rating", 5))

    selected = []
    remaining = list(reviews)

    # 1. Lowest rated
    remaining.sort(key=lambda r: r.get("rating", 5))
    selected.append(remaining.pop(0))

    # 2. Prefer one with images (if not already selected)
    img_candidates = [r for r in remaining if r.get("images")]
    if img_candidates:
        pick = min(img_candidates, key=lambda r: r.get("rating", 5))
        selected.append(pick)
        remaining.remove(pick)
    elif remaining:
        selected.append(remaining.pop(0))

    # 3. Highest-rated among remaining (for diversity)
    if remaining and len(selected) < max_count:
        pick = max(remaining, key=lambda r: r.get("rating", 5))
        selected.append(pick)

    return selected[:max_count]


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
    from qbu_crawler.server.report_common import _LABEL_DISPLAY, _SEVERITY_DISPLAY

    clusters = defaultdict(lambda: {
        "reviews": [],
        "products": set(),
        "product_names": set(),
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
        # Also validates against _POLARITY_WHITELIST to reject LLM mis-assignments
        # (e.g., strong_performance/negative — strong_performance is positive-only)
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
            # Reject codes that don't belong to the target polarity per taxonomy
            allowed = _POLARITY_WHITELIST.get(code)
            if allowed and polarity not in allowed:
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
        bucket["product_names"].add(r.get("product_name") or "")
        bucket["severities"].append(primary_severity)

        for feat in features:
            feat = feat.strip() if isinstance(feat, str) else str(feat)
            if feat:
                bucket["sub_features"][feat] += 1

    from collections import Counter

    result = []
    for code, data in clusters.items():
        reviews = data["reviews"]
        dates = [r.get("date_published_parsed") or r.get("date_published") for r in reviews if r.get("date_published_parsed") or r.get("date_published")]
        max_sev = max(data["severities"], key=lambda s: _SEVERITY_SCORE.get(s, 0), default="low")
        display = _LABEL_DISPLAY.get(code, code)

        sub_features = [
            {"feature": feat, "count": cnt}
            for feat, cnt in sorted(data["sub_features"].items(), key=lambda x: -x[1])
        ]

        rating_counts = Counter(r.get("rating", 0) for r in reviews)

        translated = sum(1 for r in reviews if r.get("body_cn") or r.get("headline_cn"))

        result.append({
            "label_code": code,
            "feature_display": display,
            "label_display": display,
            "label_polarity": polarity,
            "review_count": len(reviews),
            "affected_product_count": len(data["products"]),
            "severity": max_sev,
            "severity_display": _SEVERITY_DISPLAY.get(max_sev, max_sev),
            "first_seen": sorted(dates, key=_date_sort_key)[0] if dates else None,
            "last_seen": sorted(dates, key=_date_sort_key)[-1] if dates else None,
            "example_reviews": _select_diverse_examples(reviews, max_count=3),
            "rating_breakdown": {f"{star}星": rating_counts.get(star, 0) for star in range(1, 6) if rating_counts.get(star, 0) > 0},
            "image_review_count": sum(1 for r in reviews if r.get("images")),
            "translated_rate": translated / max(len(reviews), 1),
            "sub_features": sub_features,
            "affected_products": sorted(data["product_names"] - {""})[:5],
            "review_dates": sorted(dates),
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

    # ── Radar data: own vs competitor using unified dimensions ─────
    from qbu_crawler.server.report_common import CODE_TO_DIMENSION

    # Phase 1: For each review, determine per-dimension polarity (negative wins)
    dim_pos = {"own": {}, "competitor": {}}
    dim_total = {"own": {}, "competitor": {}}

    for item in labeled_reviews:
        ownership = item["review"].get("ownership") or "competitor"
        if ownership not in ("own", "competitor"):
            ownership = "competitor"

        # Determine per-dimension polarity for this review
        dim_polarity = {}  # dim -> "positive" | "negative"
        for label in item["labels"]:
            dim = CODE_TO_DIMENSION.get(label["label_code"])
            if not dim:
                continue
            if dim not in dim_polarity:
                dim_polarity[dim] = label["label_polarity"]
            elif label["label_polarity"] == "negative":
                dim_polarity[dim] = "negative"  # negative wins

        # Phase 2: Count once per dimension
        for dim, polarity in dim_polarity.items():
            dim_total[ownership][dim] = dim_total[ownership].get(dim, 0) + 1
            if polarity == "positive":
                dim_pos[ownership][dim] = dim_pos[ownership].get(dim, 0) + 1

    # Only include dimensions with data from BOTH sides
    all_dims = sorted(set(dim_total["own"]) & set(dim_total["competitor"]))
    if len(all_dims) >= 3:
        result["_radar_data"] = {
            "categories": all_dims,
            "own_values": [
                round(dim_pos["own"].get(d, 0) / max(dim_total["own"].get(d, 1), 1), 2)
                for d in all_dims
            ],
            "competitor_values": [
                round(dim_pos["competitor"].get(d, 0) / max(dim_total["competitor"].get(d, 1), 1), 2)
                for d in all_dims
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

    # Display hints for templates consuming chart data
    result["_sentiment_chart_title"] = "评分分布"
    result["_sentiment_chart_legend"] = {
        "positive": "好评(≥4星)",
        "neutral": "中评(3星)",
        "negative": "差评(≤2星)",
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
    # Build SKU → review_count lookup from snapshot products
    sku_review_count = {}
    for p in own_products:
        sku_review_count[p.get("sku", "")] = p.get("review_count", 0) or 0
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
                if pos + neg > 0:
                    has_data = True
                    total_reviews = max(sku_review_count.get(psku, pos + neg), pos + neg)
                    row.append(round((pos - neg) / total_reviews, 2))
                else:
                    row.append(0.0)
            if has_data:
                # Smart truncation: remove brand prefix, truncate at word boundary
                short_name = pname
                for prefix in ("Cabela's ", "Cabela\u2019s "):
                    if short_name.startswith(prefix):
                        short_name = short_name[len(prefix):]
                        break
                if len(short_name) > 25:
                    short_name = short_name[:25].rsplit(" ", 1)[0]
                y_labels.append(short_name)
                z.append(row)

        if len(y_labels) >= 2:
            result["_heatmap_data"] = {
                "z": z,
                "x_labels": [_LABEL_DISPLAY.get(d, d) for d in heatmap_dims],
                "y_labels": y_labels,
            }

    return result


def _build_trend_data(products, days=30):
    """Build per-product time series from product_snapshots.

    Returns a list of per-product series dicts. Each consumer is responsible
    for flattening to its own format (e.g., Excel rows, chart points).
    Stored under ``_trend_series`` key — NOT ``_trend_data`` which is
    reserved for ``report_charts.py``'s line chart format.
    """
    result = []
    for product in products:
        sku = product.get("sku", "")
        name = product.get("name", "")
        snapshots = models.get_product_snapshots(sku, days=days) if sku else []
        result.append({
            "product_name": name,
            "product_sku": sku,
            "series": [
                {
                    "date": s.get("scraped_at", ""),
                    "price": s.get("price"),
                    "rating": s.get("rating"),
                    "review_count": s.get("review_count"),
                    "stock_status": s.get("stock_status"),
                }
                for s in snapshots
            ],
        })
    return result


_TREND_VIEWS = {
    "week": {"days": 7, "grain": "day"},
    "month": {"days": 30, "grain": "day"},
    "year": {"days": 365, "grain": "month"},
}

_TREND_DIMENSIONS = ("sentiment", "issues", "products", "competition")


def _shift_month(year_value, month_value, delta):
    total = year_value * 12 + (month_value - 1) + delta
    shifted_year = total // 12
    shifted_month = total % 12 + 1
    return shifted_year, shifted_month


def _trend_bucket_labels(logical_day, view):
    config_view = _TREND_VIEWS[view]
    if config_view["grain"] == "day":
        start = logical_day - timedelta(days=config_view["days"] - 1)
        labels = [(start + timedelta(days=index)).isoformat() for index in range(config_view["days"])]

        def _bucket_for(day_value):
            if not day_value or day_value < start or day_value > logical_day:
                return None
            return day_value.isoformat()

        return labels, _bucket_for

    labels = []
    for offset in range(11, -1, -1):
        year_value, month_value = _shift_month(logical_day.year, logical_day.month, -offset)
        labels.append(f"{year_value:04d}-{month_value:02d}")

    label_set = set(labels)

    def _bucket_for(day_value):
        if not day_value:
            return None
        label = f"{day_value.year:04d}-{day_value.month:02d}"
        return label if label in label_set else None

    return labels, _bucket_for


def _review_publish_date(review, logical_day):
    from qbu_crawler.server.report_common import _parse_date_flexible

    raw = review.get("date_published_parsed") or review.get("date_published")
    return _parse_date_flexible(raw, anchor_date=logical_day) if raw else None


def _scraped_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _empty_comparison():
    """Phase 2 T9: comparison 永远是稳定 3 段 shape，
    数据不足时 current/previous/start/end 为 None，change_pct 同步 None。"""
    return {
        "period_over_period": {
            "label": "",
            "current": None,
            "previous": None,
            "change_pct": None,
        },
        "year_over_year": {
            "label": "",
            "current": None,
            "previous": None,
            "change_pct": None,
        },
        "start_vs_end": {
            "label": "",
            "start": None,
            "end": None,
            "change_pct": None,
        },
    }


def _trend_dimension_payload(
    *,
    status,
    message,
    kpis,
    primary_chart,
    table,
    secondary_charts=None,
    comparison=None,
):
    return {
        "status": status,
        "status_message": message,
        "kpis": kpis,
        "primary_chart": primary_chart,
        # Phase 2 T9: schema 永远齐全；ready 状态由各 _build_*_trend 主函数填充
        "secondary_charts": list(secondary_charts) if secondary_charts else [],
        "comparison": comparison if comparison is not None else _empty_comparison(),
        "table": table,
    }


def _empty_trend_dimension(status, message, chart_title, table_columns,
                            kpi_placeholder_labels=None):
    """Phase 2 T9: accumulating / degraded 状态也必须给出 4 个 KPI 占位项（label 固定，
    value 显示 "—"），不再返回空 items 列表。"""
    placeholder_labels = list(kpi_placeholder_labels or ["—", "—", "—", "—"])
    # 兜底：长度不足 4 时用 "—" 补齐
    while len(placeholder_labels) < 4:
        placeholder_labels.append("—")
    placeholder_items = [
        {"label": label, "value": "—"} for label in placeholder_labels[:4]
    ]
    return _trend_dimension_payload(
        status=status,
        message=message,
        kpis={"status": status, "items": placeholder_items},
        primary_chart={
            "status": status,
            "chart_type": "line",
            "title": chart_title,
            "labels": [],
            "series": [],
        },
        table={
            "status": status,
            "columns": table_columns,
            "rows": [],
        },
        secondary_charts=[],
        comparison=_empty_comparison(),
    )


def _build_sentiment_trend(view, logical_day, labeled_reviews):
    from qbu_crawler.server.report_common import _bayesian_bucket_health

    labels, bucket_for = _trend_bucket_labels(logical_day, view)
    review_count_by_bucket = {label: 0 for label in labels}
    own_total_by_bucket = {label: 0 for label in labels}
    own_negative_by_bucket = {label: 0 for label in labels}
    own_positive_by_bucket = {label: 0 for label in labels}

    for item in labeled_reviews:
        review = item["review"]
        bucket = bucket_for(_review_publish_date(review, logical_day))
        if not bucket:
            continue
        review_count_by_bucket[bucket] += 1
        if review.get("ownership") != "own":
            continue
        own_total_by_bucket[bucket] += 1
        rating = float(review.get("rating") or 0)
        if rating <= config.NEGATIVE_THRESHOLD:
            own_negative_by_bucket[bucket] += 1
        elif rating >= 4:
            own_positive_by_bucket[bucket] += 1

    review_counts = [review_count_by_bucket[label] for label in labels]
    own_negative_counts = [own_negative_by_bucket[label] for label in labels]
    own_negative_rates = [
        round((own_negative_by_bucket[label] / own_total_by_bucket[label]) * 100, 1)
        if own_total_by_bucket[label]
        else None
        for label in labels
    ]
    health_scores = [
        _bayesian_bucket_health(
            own_total=own_total_by_bucket[label],
            own_neg=own_negative_by_bucket[label],
            own_pos=own_positive_by_bucket[label],
        )
        for label in labels
    ]

    non_zero_points = sum(1 for value in review_counts if value > 0)
    ready = sum(review_counts) > 0 and (view != "year" or non_zero_points >= 2)
    if not ready:
        return _empty_trend_dimension(
            "accumulating",
            "评论发布时间样本仍在积累，当前不足以形成稳定趋势。",
            "舆情趋势",
            ["日期", "评论量", "自有差评", "自有差评率", "健康分"],
        )

    rows = []
    for label in labels:
        if review_count_by_bucket[label] <= 0:
            continue
        rows.append(
            {
                "bucket": label,
                "review_count": review_count_by_bucket[label],
                "own_negative_count": own_negative_by_bucket[label],
                "own_negative_rate": own_negative_rates[labels.index(label)],
                "health_index": health_scores[labels.index(label)],
            }
        )

    total_own_reviews = sum(own_total_by_bucket.values())
    total_own_negative = sum(own_negative_by_bucket.values())
    total_own_negative_rate = round((total_own_negative / total_own_reviews) * 100, 1) if total_own_reviews else 0

    return _trend_dimension_payload(
        status="ready",
        message="",
        kpis={
            "status": "ready",
            "items": [
                {"label": "窗口评论量", "value": sum(review_counts)},
                {"label": "自有差评数", "value": total_own_negative},
                {"label": "自有差评率", "value": f"{total_own_negative_rate:.1f}%"},
                {"label": "有效时间点", "value": non_zero_points},
            ],
        },
        primary_chart={
            "status": "ready",
            "chart_type": "line",
            "title": "舆情趋势",
            "labels": labels,
            "series": [
                {"name": "评论量", "data": review_counts},
                {"name": "自有差评数", "data": own_negative_counts},
                {"name": "健康分", "data": health_scores},
            ],
        },
        table={
            "status": "ready",
            "columns": ["日期", "评论量", "自有差评", "自有差评率", "健康分"],
            "rows": rows,
        },
    )


def _build_issue_trend(view, logical_day, labeled_reviews):
    from qbu_crawler.server.report_common import _label_display

    labels, bucket_for = _trend_bucket_labels(logical_day, view)
    counts_by_label: dict[str, dict[str, int]] = {}
    affected_products: dict[str, set[str]] = {}

    for item in labeled_reviews:
        review = item["review"]
        if review.get("ownership") != "own":
            continue
        bucket = bucket_for(_review_publish_date(review, logical_day))
        if not bucket:
            continue
        product_marker = review.get("product_sku") or review.get("product_name") or ""
        for label in item.get("labels") or []:
            if label.get("label_polarity") != "negative":
                continue
            code = label.get("label_code") or "_uncategorized"
            counts_by_label.setdefault(code, {name: 0 for name in labels})
            counts_by_label[code][bucket] += 1
            affected_products.setdefault(code, set()).add(product_marker)

    if not counts_by_label:
        return _empty_trend_dimension(
            "accumulating",
            "问题标签样本仍在积累，当前不足以形成稳定趋势。",
            "问题趋势",
            ["问题", "评论数", "影响产品数"],
        )

    ranked_codes = sorted(
        counts_by_label,
        key=lambda code: (-sum(counts_by_label[code].values()), code),
    )[:3]
    non_zero_points = sum(
        1
        for label in labels
        if sum(counts_by_label[code].get(label, 0) for code in ranked_codes) > 0
    )
    ready = non_zero_points > 0 and (view != "year" or non_zero_points >= 2)
    if not ready:
        return _empty_trend_dimension(
            "accumulating",
            "问题标签时间分布仍在积累，当前不足以形成年度趋势。",
            "问题趋势",
            ["问题", "评论数", "影响产品数"],
        )

    rows = []
    for code in ranked_codes:
        rows.append(
            {
                "label_code": code,
                "label_display": _label_display(code),
                "review_count": sum(counts_by_label[code].values()),
                "affected_product_count": len([name for name in affected_products.get(code, set()) if name]),
            }
        )

    top_code = ranked_codes[0]
    return _trend_dimension_payload(
        status="ready",
        message="",
        kpis={
            "status": "ready",
            "items": [
                {"label": "问题信号数", "value": sum(sum(counts_by_label[code].values()) for code in ranked_codes)},
                {"label": "活跃问题数", "value": len(ranked_codes)},
                {"label": "头号问题", "value": _label_display(top_code)},
                {"label": "涉及产品数", "value": rows[0]["affected_product_count"]},
            ],
        },
        primary_chart={
            "status": "ready",
            "chart_type": "line",
            "title": "问题趋势",
            "labels": labels,
            "series": [
                {
                    "name": _label_display(code),
                    "data": [counts_by_label[code].get(label, 0) for label in labels],
                }
                for code in ranked_codes
            ],
        },
        table={
            "status": "ready",
            "columns": ["问题", "评论数", "影响产品数"],
            "rows": rows,
        },
    )


def _build_product_trend(view, logical_day, trend_series, snapshot_products):
    labels, bucket_for = _trend_bucket_labels(logical_day, view)
    own_products = [product for product in snapshot_products if product.get("ownership") == "own"]
    rows = []
    ready_series = None

    for product in own_products:
        sku = product.get("sku") or ""
        matching = next((item for item in trend_series if item.get("product_sku") == sku), None) or {}
        filtered = []
        for point in matching.get("series") or []:
            point_day = _scraped_date(point.get("date"))
            bucket = bucket_for(point_day)
            if not bucket:
                continue
            filtered.append({**point, "bucket": bucket})
        rows.append(
            {
                "sku": sku,
                "name": product.get("name") or sku,
                "current_rating": product.get("rating"),
                "current_review_count": product.get("review_count"),
                "snapshot_points": len(filtered),
                "scraped_at": product.get("scraped_at"),
            }
        )
        if ready_series is None and len(filtered) >= 2:
            ready_series = {
                "product_name": product.get("name") or sku,
                "points": filtered,
            }

    if ready_series is None:
        return _trend_dimension_payload(
            status="accumulating",
            message="产品快照样本不足，连续状态趋势仍在积累。",
            kpis={
                "status": "ready" if rows else "accumulating",
                "items": [
                    {"label": "跟踪产品数", "value": len(own_products)},
                    {"label": "有快照产品数", "value": sum(1 for row in rows if row["snapshot_points"] > 0)},
                    {"label": "可成图产品数", "value": 0},
                    {"label": "快照点数", "value": sum(row["snapshot_points"] for row in rows)},
                ],
            },
            primary_chart={
                "status": "accumulating",
                "chart_type": "line",
                "title": "产品评分趋势",
                "labels": [],
                "series": [],
            },
            table={
                "status": "ready" if rows else "accumulating",
                "columns": ["SKU", "产品", "当前评分", "当前评论总数", "快照点数", "最新抓取时间"],
                "rows": rows,
            },
        )

    bucket_to_rating = {label: None for label in labels}
    bucket_to_review_count = {label: None for label in labels}
    for point in ready_series["points"]:
        bucket_to_rating[point["bucket"]] = point.get("rating")
        bucket_to_review_count[point["bucket"]] = point.get("review_count")

    return _trend_dimension_payload(
        status="ready",
        message="",
        kpis={
            "status": "ready",
            "items": [
                {"label": "跟踪产品数", "value": len(own_products)},
                {"label": "有快照产品数", "value": sum(1 for row in rows if row["snapshot_points"] > 0)},
                {"label": "可成图产品数", "value": 1},
                {"label": "快照点数", "value": len(ready_series["points"])},
            ],
        },
        primary_chart={
            "status": "ready",
            "chart_type": "line",
            "title": f"产品趋势 - {ready_series['product_name']}",
            "labels": labels,
            "series": [
                {"name": "评分", "data": [bucket_to_rating[label] for label in labels]},
                {"name": "评论总数", "data": [bucket_to_review_count[label] for label in labels]},
            ],
        },
        table={
            "status": "ready",
            "columns": ["SKU", "产品", "当前评分", "当前评论总数", "快照点数", "最新抓取时间"],
            "rows": rows,
        },
    )


def _build_competition_trend(view, logical_day, labeled_reviews):
    labels, bucket_for = _trend_bucket_labels(logical_day, view)
    own_ratings = {label: [] for label in labels}
    competitor_ratings = {label: [] for label in labels}
    own_total = {label: 0 for label in labels}
    own_negative = {label: 0 for label in labels}
    competitor_total = {label: 0 for label in labels}
    competitor_positive = {label: 0 for label in labels}

    for item in labeled_reviews:
        review = item["review"]
        bucket = bucket_for(_review_publish_date(review, logical_day))
        if not bucket:
            continue
        rating = float(review.get("rating") or 0)
        if review.get("ownership") == "own":
            own_ratings[bucket].append(rating)
            own_total[bucket] += 1
            if rating <= config.NEGATIVE_THRESHOLD:
                own_negative[bucket] += 1
        elif review.get("ownership") == "competitor":
            competitor_ratings[bucket].append(rating)
            competitor_total[bucket] += 1
            if rating >= 4:
                competitor_positive[bucket] += 1

    shared_points = sum(1 for label in labels if own_total[label] > 0 and competitor_total[label] > 0)
    chart_ready = shared_points > 0 and (view != "year" or shared_points >= 2)
    own_points = sum(1 for label in labels if own_total[label] > 0)
    competitor_points = sum(1 for label in labels if competitor_total[label] > 0)
    any_side_has_data = own_points > 0 or competitor_points > 0

    if not any_side_has_data:
        # Neither side has data → integral accumulating is correct.
        return _empty_trend_dimension(
            "accumulating",
            "自有与竞品的可比样本仍在积累，当前不足以形成稳定趋势。",
            "竞品趋势",
            ["日期", "自有均分", "竞品均分", "自有差评率", "竞品好评率"],
        )

    own_avg_rating = [
        round(sum(own_ratings[label]) / len(own_ratings[label]), 2) if own_ratings[label] else None
        for label in labels
    ]
    competitor_avg_rating = [
        round(sum(competitor_ratings[label]) / len(competitor_ratings[label]), 2) if competitor_ratings[label] else None
        for label in labels
    ]
    own_negative_rate = [
        round((own_negative[label] / own_total[label]) * 100, 1) if own_total[label] else None
        for label in labels
    ]
    competitor_positive_rate = [
        round((competitor_positive[label] / competitor_total[label]) * 100, 1) if competitor_total[label] else None
        for label in labels
    ]

    rows = []
    for label in labels:
        if own_total[label] <= 0 and competitor_total[label] <= 0:
            continue
        rows.append(
            {
                "bucket": label,
                "own_avg_rating": own_avg_rating[labels.index(label)],
                "competitor_avg_rating": competitor_avg_rating[labels.index(label)],
                "own_negative_rate": own_negative_rate[labels.index(label)],
                "competitor_positive_rate": competitor_positive_rate[labels.index(label)],
            }
        )

    latest_row = rows[-1] if rows else {}
    rating_gap = None
    if latest_row.get("own_avg_rating") is not None and latest_row.get("competitor_avg_rating") is not None:
        rating_gap = round(latest_row["competitor_avg_rating"] - latest_row["own_avg_rating"], 2)

    kpis_ready = shared_points > 0
    kpi_status = "ready" if kpis_ready else "accumulating"
    top_status = "ready" if chart_ready else "accumulating"
    top_message = "" if chart_ready else "可比样本仍在积累，图表暂未稳定但已有数据点可查。"

    _own_neg = latest_row.get("own_negative_rate") if latest_row else None
    _comp_pos = latest_row.get("competitor_positive_rate") if latest_row else None

    return _trend_dimension_payload(
        status=top_status,
        message=top_message,
        kpis={
            "status": kpi_status,
            "items": [
                {"label": "可比时间点", "value": shared_points},
                {"label": "最新评分差", "value": rating_gap if rating_gap is not None else "—"},
                {"label": "最新自有差评率", "value": f"{_own_neg:.1f}%" if _own_neg is not None else "—"},
                {"label": "最新竞品好评率", "value": f"{_comp_pos:.1f}%" if _comp_pos is not None else "—"},
            ],
        },
        primary_chart={
            "status": "ready" if chart_ready else "accumulating",
            "chart_type": "line",
            "title": "竞品趋势",
            "labels": labels if chart_ready else [],
            "series": [
                {"name": "自有均分", "data": own_avg_rating},
                {"name": "竞品均分", "data": competitor_avg_rating},
            ] if chart_ready else [],
        },
        table={
            "status": "ready" if any_side_has_data else "accumulating",
            "columns": ["日期", "自有均分", "竞品均分", "自有差评率", "竞品好评率"],
            "rows": rows,
        },
    )


def _build_trend_dimension(builder, *args):
    try:
        return builder(*args)
    except Exception as exc:
        return _empty_trend_dimension(
            "degraded",
            f"趋势数据生成失败：{exc}",
            "趋势",
            [],
        )


def _build_trend_digest(snapshot, labeled_reviews, trend_series):
    logical_day = date.fromisoformat(snapshot["logical_date"])
    data = {}
    snapshot_products = snapshot.get("products") or []

    for view in _TREND_VIEWS:
        data[view] = {
            "sentiment": _build_trend_dimension(_build_sentiment_trend, view, logical_day, labeled_reviews),
            "issues": _build_trend_dimension(_build_issue_trend, view, logical_day, labeled_reviews),
            "products": _build_trend_dimension(_build_product_trend, view, logical_day, trend_series, snapshot_products),
            "competition": _build_trend_dimension(_build_competition_trend, view, logical_day, labeled_reviews),
        }

    return {
        "views": list(_TREND_VIEWS.keys()),
        "dimensions": list(_TREND_DIMENSIONS),
        "default_view": "month",
        "default_dimension": "sentiment",
        "data": data,
        # 修 9: 年视图基于 date_published_parsed（评论发布时间），跨越历史数年；
        # 用户容易误以为是"监控系统已运行 N 年"，所以给出语义提示。
        "view_notes": {
            "week": None,
            "month": None,
            "year": (
                "年度视角基于评论发布时间聚合。历史数据源于站点用户的历史发布时间跨度，"
                "不代表本监控系统的实际运行年限。"
            ),
        },
    }


def build_report_analytics(snapshot, synced_labels=None, skip_delta=False):
    mode_info = detect_report_mode(snapshot.get("run_id", 0), snapshot["logical_date"])
    labeled_reviews = _build_labeled_reviews(snapshot, synced_labels=synced_labels)

    # Determine if review_analysis data is available for feature-based clustering
    snapshot_reviews = snapshot.get("reviews") or []
    use_feature_clusters = _has_review_analysis_data(snapshot_reviews)

    if use_feature_clusters:
        top_negative_clusters = _build_feature_clusters(snapshot_reviews, ownership="own", polarity="negative")
        top_positive_themes = _build_feature_clusters(snapshot_reviews, ownership="competitor", polarity="positive")
        # Own positive clusters (for gap analysis catch_up_gap)
        own_positive_clusters = _build_feature_clusters(snapshot_reviews, ownership="own", polarity="positive")
    else:
        top_negative_clusters = _cluster_summary_items(labeled_reviews, ownership="own", polarity="negative")
        top_positive_themes = _cluster_summary_items(labeled_reviews, ownership="competitor", polarity="positive")
        # Own positive clusters (for gap analysis catch_up_gap)
        own_positive_clusters = _cluster_summary_items(labeled_reviews, ownership="own", polarity="positive")

    # Override cluster severity with computed V3 severity (4-factor: volume/breadth/recency/safety)
    from datetime import datetime as _dt
    _logical_date = _dt.strptime(snapshot.get("logical_date", "2026-01-01"), "%Y-%m-%d").date()
    for cluster in top_negative_clusters:
        # Collect reviews matching this cluster for safety scan
        _cluster_reviews = [
            item["review"] for item in labeled_reviews
            if any(
                l["label_code"] == cluster["label_code"] and l["label_polarity"] == "negative"
                for l in item["labels"]
            )
            and item["review"].get("ownership") == "own"
        ]
        cluster["severity"] = compute_cluster_severity(cluster, _cluster_reviews, _logical_date)
        from qbu_crawler.server.report_common import _SEVERITY_DISPLAY
        cluster["severity_display"] = _SEVERITY_DISPLAY.get(cluster["severity"], cluster["severity"])

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

    # Trend data from product_snapshots (stored as _trend_series, NOT _trend_data)
    _trend_series = _build_trend_data(snapshot.get("products") or [], days=30)

    # Compute recently_published_count: reviews published within 30 days of logical_date
    from qbu_crawler.server.report_common import _parse_date_flexible
    from datetime import date as _date, timedelta as _timedelta
    logical = _date.fromisoformat(snapshot["logical_date"])
    recent_cutoff = logical - _timedelta(days=30)
    recently_published_count = 0
    for review in snapshot_reviews:
        raw_parsed = review.get("date_published_parsed")
        pub_date = (_parse_date_flexible(raw_parsed) if raw_parsed else None) or _parse_date_flexible(review.get("date_published"))
        if pub_date and pub_date >= recent_cutoff:
            recently_published_count += 1

    analytics = {
        "run_id": snapshot.get("run_id"),
        "logical_date": snapshot["logical_date"],
        "snapshot_hash": snapshot["snapshot_hash"],
        "mode": mode_info["mode"],
        "report_semantics": "bootstrap" if mode_info["mode"] == "baseline" else "incremental",
        "is_bootstrap": mode_info["mode"] == "baseline",
        "baseline_run_ids": mode_info["baseline_run_ids"],
        "baseline_sample_days": mode_info["baseline_sample_days"],
        "taxonomy_version": TAXONOMY_VERSION,
        "label_mode": config.REPORT_LABEL_MODE,
        "generated_at": config.now_shanghai().isoformat(),
        "change_digest": {},
        "trend_digest": _build_trend_digest(snapshot, labeled_reviews, _trend_series),
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
            "own_positive_review_rows": sum(
                1 for r in own_reviews if (r.get("review", {}).get("rating") or 0) >= 4
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
            "risk_products": _risk_products(labeled_reviews, snapshot_products=snapshot.get("products", []),
                                            logical_date=snapshot.get("logical_date")),
            "top_negative_clusters": top_negative_clusters,
            "top_positive_clusters": own_positive_clusters,
            "recommendations": _recommendations(top_negative_clusters),
        },
        "competitor": {
            "top_positive_themes": top_positive_themes,
            "benchmark_examples": _benchmark_examples(labeled_reviews),
            "negative_opportunities": _negative_opportunities(labeled_reviews),
        },
        "appendix": {
            "image_reviews": sorted(
                image_reviews,
                key=lambda r: (
                    0 if r.get("ownership") == "own" else 1,
                    r.get("rating") or 5,
                ),
            )[:20],
            "coverage": {
                "own_products": len(own_products),
                "competitor_products": len(competitor_products),
                "own_reviews": len(own_reviews),
                "competitor_reviews": len(competitor_reviews),
            },
        },
        **chart_data,
        "_trend_series": _trend_series,
    }

    # ── KPI delta computation (Fix-4) ────────────────────────────────────
    if not skip_delta and mode_info["mode"] != "baseline":
        from .report_snapshot import load_previous_report_context  # lazy import
        from .report_common import _compute_kpi_deltas

        _run_id = snapshot.get("run_id", 0)
        prev_analytics, _ = load_previous_report_context(_run_id)
        if prev_analytics:
            deltas = _compute_kpi_deltas(analytics["kpis"], prev_analytics)
            analytics["kpis"].update(deltas)

    return analytics


def build_dual_report_analytics(snapshot, synced_labels=None):
    """Dual-perspective analytics: cumulative (main) + window (delta).

    If snapshot has no 'cumulative' field (old format), degrades to single
    perspective by calling build_report_analytics() directly.
    """
    if not snapshot.get("cumulative"):
        return build_report_analytics(snapshot, synced_labels=synced_labels)

    cum = snapshot["cumulative"]
    cumulative_snapshot = {
        "run_id": snapshot["run_id"],
        "logical_date": snapshot["logical_date"],
        "snapshot_hash": snapshot.get("snapshot_hash", ""),
        "products": cum["products"],
        "reviews": cum["reviews"],
        "products_count": cum["products_count"],
        "reviews_count": cum["reviews_count"],
        "translated_count": cum.get("translated_count", 0),
        "untranslated_count": cum.get("untranslated_count", 0),
    }

    # Cumulative analytics (main body) — skip_delta=True: outer block handles delta correctly
    cum_analytics = build_report_analytics(cumulative_snapshot, synced_labels=synced_labels, skip_delta=True)

    # Window analytics — skip delta (F3: avoids meaningless window-vs-cumulative comparison)
    window_analytics = None
    if snapshot.get("reviews"):
        window_analytics = build_report_analytics(
            snapshot, synced_labels=synced_labels, skip_delta=True)

    # Window summary
    window_reviews = snapshot.get("reviews", [])
    own_window = [r for r in window_reviews if r.get("ownership") == "own"]
    neg_threshold = config.NEGATIVE_THRESHOLD

    merged = {
        **cum_analytics,
        "perspective": "dual",
        "cumulative_kpis": cum_analytics["kpis"],
        "window": {
            "reviews_count": len(window_reviews),
            "own_reviews_count": len(own_window),
            "competitor_reviews_count": len(window_reviews) - len(own_window),
            "new_negative_count": sum(
                1 for r in own_window
                if (r.get("rating") or 5) <= neg_threshold),
            "new_reviews": window_reviews,
            "analytics": window_analytics,
        },
    }

    # KPI delta: cumulative vs previous cumulative
    if cum_analytics.get("mode") != "baseline":
        from .report_snapshot import load_previous_report_context
        from .report_common import _compute_kpi_deltas

        _run_id = snapshot.get("run_id", 0)
        prev_analytics, _ = load_previous_report_context(_run_id)
        if prev_analytics:
            prev_kpis_source = prev_analytics
            if prev_analytics.get("cumulative_kpis"):
                prev_kpis_source = {"kpis": prev_analytics["cumulative_kpis"]}
            deltas = _compute_kpi_deltas(merged["cumulative_kpis"], prev_kpis_source)
            merged["cumulative_kpis"].update(deltas)
            merged["kpis"].update(deltas)

    return merged
