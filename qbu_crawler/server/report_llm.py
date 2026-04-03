import copy

from qbu_crawler.server import report_analytics


def _review_id(review):
    return review.get("id") or review.get("review_id")


def _review_images(review):
    return report_analytics._review_images(review)


def _review_labels(review, polarity):
    return [
        label
        for label in report_analytics.classify_review_labels(review)
        if label.get("label_polarity") == polarity
    ]


def build_candidate_pools(snapshot, analytics):
    own_negative_candidates = []
    competitor_positive_candidates = []
    own_negative_image_candidates = []
    competitor_negative_opportunity_candidates = []

    for review in snapshot.get("reviews") or []:
        ownership = review.get("ownership")
        rating = float(review.get("rating") or 0)
        negative_labels = _review_labels(review, "negative")
        positive_labels = _review_labels(review, "positive")
        images = _review_images(review)

        if ownership == "own" and (rating <= 2 or (rating <= 3 and negative_labels)):
            own_negative_candidates.append(review)
            if images:
                own_negative_image_candidates.append(review)

        if ownership == "competitor" and rating >= 4 and positive_labels:
            competitor_positive_candidates.append(review)

        if ownership == "competitor" and rating <= 2 and negative_labels:
            competitor_negative_opportunity_candidates.append(review)

    return {
        "own_negative_candidates": own_negative_candidates,
        "competitor_positive_candidates": competitor_positive_candidates,
        "own_negative_image_candidates": own_negative_image_candidates,
        "competitor_negative_opportunity_candidates": competitor_negative_opportunity_candidates,
    }


def classify_review_batch(pool_name, reviews):
    polarity = "positive" if pool_name == "competitor_positive_candidates" else "negative"
    items = []
    for review in reviews:
        labels = _review_labels(review, polarity)
        if not labels:
            continue
        items.append(
            {
                "review_id": _review_id(review),
                "polarity": polarity,
                "label_codes": [label["label_code"] for label in labels],
                "severity": max(labels, key=lambda label: report_analytics._SEVERITY_SCORE[label["severity"]])["severity"],
                "confidence": max(label["confidence"] for label in labels),
                "summary_text": (review.get("headline_cn") or review.get("headline") or "").strip(),
                "source": "deterministic",
            }
        )
    return items


def classify_candidate_pools(candidate_pools):
    return {
        pool_name: classify_review_batch(pool_name, reviews)
        for pool_name, reviews in candidate_pools.items()
    }


def _cluster_items(reviews, polarity):
    grouped = {}
    for review in reviews:
        labels = _review_labels(review, polarity)
        for label in labels:
            cluster = grouped.setdefault(
                label["label_code"],
                {
                    "label_code": label["label_code"],
                    "label_polarity": polarity,
                    "review_count": 0,
                    "image_review_count": 0,
                    "severity": label["severity"],
                    "severity_score": report_analytics._SEVERITY_SCORE[label["severity"]],
                    "example_reviews": [],
                    "supporting_review_ids": [],
                },
            )
            cluster["review_count"] += 1
            cluster["supporting_review_ids"].append(_review_id(review))
            images = _review_images(review)
            if images:
                cluster["image_review_count"] += 1
            if report_analytics._SEVERITY_SCORE[label["severity"]] > cluster["severity_score"]:
                cluster["severity"] = label["severity"]
                cluster["severity_score"] = report_analytics._SEVERITY_SCORE[label["severity"]]
            if len(cluster["example_reviews"]) < 3:
                example = dict(review)
                example["images"] = images
                cluster["example_reviews"].append(example)

    items = list(grouped.values())
    items.sort(
        key=lambda item: (
            -item["review_count"],
            -item["image_review_count"],
            -item["severity_score"],
            item["label_code"],
        )
    )
    for item in items:
        item.pop("severity_score")
    return items


def _benchmark_examples(reviews):
    items = []
    for review in reviews:
        labels = _review_labels(review, "positive")
        if not labels:
            continue
        items.append(
            {
                "review_id": _review_id(review),
                "product_name": review.get("product_name"),
                "product_sku": review.get("product_sku"),
                "author": review.get("author"),
                "rating": review.get("rating"),
                "headline": review.get("headline"),
                "body": review.get("body"),
                "headline_cn": review.get("headline_cn"),
                "body_cn": review.get("body_cn"),
                "images": _review_images(review),
                "label_codes": [label["label_code"] for label in labels],
            }
        )
    items.sort(key=lambda item: (-(item.get("rating") or 0), -(len(item["label_codes"])), item.get("product_sku") or ""))
    return items[:5]


def _negative_opportunities(reviews):
    items = []
    for review in reviews:
        labels = _review_labels(review, "negative")
        if not labels:
            continue
        items.append(
            {
                "review_id": _review_id(review),
                "product_name": review.get("product_name"),
                "product_sku": review.get("product_sku"),
                "author": review.get("author"),
                "rating": review.get("rating"),
                "headline": review.get("headline"),
                "body": review.get("body"),
                "headline_cn": review.get("headline_cn"),
                "body_cn": review.get("body_cn"),
                "images": _review_images(review),
                "label_codes": [label["label_code"] for label in labels],
            }
        )
    items.sort(key=lambda item: ((item.get("rating") or 5), item.get("product_sku") or ""))
    return items[:5]


def _recommendations(analytics, validated_clusters):
    allowed = {item["label_code"]: item["review_count"] for item in validated_clusters}
    items = []
    for recommendation in (analytics.get("self") or {}).get("recommendations") or []:
        label_code = recommendation.get("label_code")
        if label_code not in allowed:
            continue
        item = dict(recommendation)
        item["evidence_count"] = allowed[label_code]
        items.append(item)
    return items


def run_llm_report_analysis(snapshot, analytics):
    candidate_pools = build_candidate_pools(snapshot, analytics)
    llm_findings = {"classified_reviews": classify_candidate_pools(candidate_pools)}
    return {
        "candidate_pools": candidate_pools,
        "llm_findings": llm_findings,
        "report_copy": {},
    }


def validate_findings(snapshot, analytics, llm_result):
    candidate_pools = (llm_result or {}).get("candidate_pools") or build_candidate_pools(snapshot, analytics)
    own_negative_candidates = candidate_pools.get("own_negative_candidates") or []
    competitor_positive_candidates = candidate_pools.get("competitor_positive_candidates") or []
    own_negative_image_candidates = candidate_pools.get("own_negative_image_candidates") or []
    competitor_negative_opportunity_candidates = candidate_pools.get("competitor_negative_opportunity_candidates") or []

    self_negative_clusters = _cluster_items(own_negative_candidates, "negative")
    competitor_positive_themes = _cluster_items(competitor_positive_candidates, "positive")
    own_image_evidence = []
    for review in own_negative_image_candidates:
        item = dict(review)
        item["images"] = _review_images(review)
        own_image_evidence.append(item)

    return {
        "self_negative_clusters": self_negative_clusters,
        "competitor_positive_themes": competitor_positive_themes,
        "own_image_evidence": own_image_evidence[:10],
        "competitor_negative_opportunities": _negative_opportunities(competitor_negative_opportunity_candidates),
        "competitor_benchmark_examples": _benchmark_examples(competitor_positive_candidates),
        "recommendations": _recommendations(analytics, self_negative_clusters),
    }


def merge_final_analytics(analytics, llm_result, validated_result):
    merged = copy.deepcopy(analytics)
    merged.setdefault("self", {})
    merged.setdefault("competitor", {})
    merged.setdefault("appendix", {})

    merged["self"]["top_negative_clusters"] = validated_result.get("self_negative_clusters") or []
    merged["self"]["recommendations"] = validated_result.get("recommendations") or []
    merged["competitor"]["top_positive_themes"] = validated_result.get("competitor_positive_themes") or []
    merged["competitor"]["benchmark_examples"] = validated_result.get("competitor_benchmark_examples") or []
    merged["competitor"]["negative_opportunities"] = validated_result.get("competitor_negative_opportunities") or []
    merged["appendix"]["image_reviews"] = validated_result.get("own_image_evidence") or []
    merged["candidate_pools"] = (llm_result or {}).get("candidate_pools") or {}
    merged["llm_findings"] = (llm_result or {}).get("llm_findings") or {}
    merged["validated_findings"] = validated_result or {}
    merged["report_copy"] = (llm_result or {}).get("report_copy") or {}
    return merged
