"""User-facing report contract builder."""

import copy

SCHEMA_VERSION = "report_user_contract.v1"


def _unique_ordered(values):
    result = []
    seen = set()
    for value in values or []:
        text = (value or "").strip() if isinstance(value, str) else value
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _review_id(review):
    return review.get("id") or review.get("review_id")


def _display_body(review):
    return (
        review.get("body_cn")
        or review.get("headline_cn")
        or review.get("body")
        or review.get("headline")
        or review.get("summary_text")
        or ""
    )


def _contract_context(snapshot):
    snapshot = snapshot or {}
    products = snapshot.get("products") or []
    reviews = snapshot.get("reviews") or []
    has_snapshot = bool(snapshot)
    return {
        "snapshot_source": "provided" if has_snapshot else "missing",
        "product_count": len(products),
        "review_count": len(reviews),
    }


def _metric(field, display_name, formula, time_basis, product_scope, denominator, mode, confidence="medium"):
    return {
        "field": field,
        "display_name": display_name,
        "formula": formula,
        "time_basis": time_basis,
        "product_scope": product_scope,
        "denominator": denominator,
        "bootstrap_behavior": "shown_as_current_snapshot" if mode == "bootstrap" else "normal",
        "confidence": confidence,
        "explanation": f"{display_name}按{time_basis}口径计算，分母为{denominator}",
    }


def _build_metric_definitions(kpis, mode):
    return {
        "health_index": _metric(
            "health_index",
            "健康指数",
            "weighted health score from negative rate, risk products and confidence",
            "scraped_at + review analysis",
            "own_products",
            "own_reviews",
            mode,
            "high",
        ),
        "high_risk_count": _metric(
            "high_risk_count",
            "高风险产品数",
            f"count(risk_products where risk_score >= threshold)",
            "scraped_at",
            "own_products",
            "risk_products",
            mode,
            "high",
        ),
        "attention_product_count": _metric(
            "attention_product_count",
            "需关注产品数",
            "count(risk_products where status_lamp in red/yellow)",
            "scraped_at",
            "own_products",
            "risk_products",
            mode,
            "high",
        ),
        "negative_review_rate": _metric(
            "negative_review_rate",
            "差评率",
            "negative_review_rows / review_rows",
            "review analysis",
            "own_products",
            "own_reviews",
            mode,
            "medium",
        ),
        "fresh_review_count": _metric(
            "fresh_review_count",
            "近30天评论数",
            "count(reviews where date_published_parsed in last 30 days)",
            "date_published_parsed",
            "all_products",
            "all_reviews",
            mode,
            "medium",
        ),
        "translation_completion_rate": _metric(
            "translation_completion_rate",
            "翻译完成率",
            "translated_count / ingested_review_rows",
            "scraped_at",
            "all_products",
            "ingested_review_rows",
            mode,
            "high",
        ),
        "scrape_missing_rate": _metric(
            "scrape_missing_rate",
            "采集缺失率",
            "missing_or_low_coverage_products / all_products",
            "scraped_at",
            "all_products",
            "site_reported_review_total_current",
            mode,
            "medium",
        ),
        "heatmap_experience_health": _metric(
            "heatmap_experience_health",
            "heatmap 体验健康度",
            "(positive + 0.5 * mixed) / sample_size",
            "review analysis",
            "product_label_cells",
            "cell_sample_size",
            mode,
            "medium",
        ),
    }


def _priority_actions_by_label(analytics):
    priorities = (analytics.get("report_copy") or {}).get("improvement_priorities") or []
    return {
        item.get("label_code"): item.get("full_action") or item.get("action") or ""
        for item in priorities
        if item.get("label_code")
    }


def _build_issue_diagnostics(analytics):
    clusters = (analytics.get("self") or {}).get("top_negative_clusters") or []
    actions_by_label = _priority_actions_by_label(analytics)
    cards = []
    for cluster in clusters:
        label_code = cluster.get("label_code") or ""
        examples = cluster.get("example_reviews") or []
        review_ids = [_review_id(item) for item in examples if _review_id(item) is not None]
        text_evidence = [
            {
                "review_id": _review_id(item),
                "display_body": _display_body(item),
            }
            for item in examples
            if _review_id(item) is not None or _display_body(item)
        ]
        image_evidence = []
        for item in examples:
            rid = _review_id(item)
            for url in item.get("images") or []:
                if url:
                    image_evidence.append({"review_id": rid, "url": url})
        deep = cluster.get("deep_analysis") or {}
        recommendation = actions_by_label.get(label_code) or deep.get("actionable_summary") or cluster.get("recommendation") or ""
        affected_products = _unique_ordered(cluster.get("affected_products") or cluster.get("products") or [])
        cards.append({
            "label_code": label_code,
            "label_display": cluster.get("label_display") or cluster.get("feature_display") or label_code,
            "severity": cluster.get("severity") or "low",
            "affected_products": affected_products,
            "allowed_products": affected_products,
            "evidence_count": cluster.get("evidence_count") or cluster.get("review_count") or len(review_ids),
            "evidence_review_ids": review_ids,
            "text_evidence": text_evidence,
            "image_evidence": image_evidence,
            "ai_summary": deep.get("actionable_summary") or "",
            "ai_recommendation": recommendation,
            "recommended_action": recommendation,
            "failure_modes": deep.get("failure_modes") or [],
            "root_causes": deep.get("root_causes") or [],
            "user_workarounds": deep.get("user_workarounds") or [],
            "source_cluster_ids": _unique_ordered([cluster.get("cluster_id")]),
            "confidence": cluster.get("confidence") or "medium",
        })
    return cards


def _competitor_summary(item):
    return (
        item.get("summary_cn")
        or item.get("body_cn")
        or item.get("headline_cn")
        or item.get("summary")
        or item.get("body")
        or item.get("headline")
        or item.get("label_display")
        or item.get("topic")
        or ""
    )


def _competitor_review_ids(item):
    ids = item.get("review_ids") or item.get("evidence_review_ids") or []
    if not ids and _review_id(item) is not None:
        ids = [_review_id(item)]
    return [rid for rid in ids if rid is not None]


def _competitor_product_count(item):
    if item.get("product_count") is not None:
        return int(item.get("product_count") or 0)
    products = item.get("products") or item.get("affected_products") or []
    if products:
        return len(products)
    return 1 if item.get("product_name") or item.get("product_sku") else 0


def _competitor_sample_size(item, evidence_ids):
    return int(
        item.get("sample_size")
        or item.get("evidence_count")
        or len(evidence_ids)
        or 1
    )


def _competitor_contract_item(item, source, kind):
    summary = _competitor_summary(item)
    evidence_ids = _competitor_review_ids(item)
    if kind == "avoid":
        implication = f"自有产品需避免复现：{summary}" if summary else "自有产品需避免复现竞品短板"
        validation = "抽样复核对应设计、包装和售后触点"
    else:
        implication = f"自有产品可借鉴并转化为检查项：{summary}" if summary else "自有产品可借鉴竞品正面体验"
        validation = "抽查页面表达、说明书和客服问答是否覆盖该体验"
    return {
        "summary_cn": summary,
        "self_product_implication": item.get("self_product_implication") or implication,
        "suggested_validation": item.get("suggested_validation") or validation,
        "evidence_review_ids": evidence_ids,
        "sample_size": _competitor_sample_size(item, evidence_ids),
        "product_count": _competitor_product_count(item),
        "source": source,
    }


def _flatten_benchmark_examples(raw):
    if isinstance(raw, dict):
        items = []
        for values in raw.values():
            items.extend(values or [])
        return items
    return raw or []


def _build_competitor_insights(analytics):
    competitor = analytics.get("competitor") or {}
    positive_items = (
        competitor.get("positive_patterns")
        or _flatten_benchmark_examples(competitor.get("benchmark_examples"))
        or []
    )
    negative_items = competitor.get("negative_opportunities") or []
    learn = [
        _competitor_contract_item(item, "positive_patterns", "learn")
        for item in positive_items[:3]
    ]
    avoid = [
        _competitor_contract_item(item, "negative_opportunities", "avoid")
        for item in negative_items[:3]
    ]
    hypotheses = []
    for item in (avoid + learn)[:3]:
        hypotheses.append({
            "summary_cn": f"验证：{item.get('summary_cn')}",
            "self_product_implication": item.get("self_product_implication") or "",
            "suggested_validation": item.get("suggested_validation") or "",
            "evidence_review_ids": item.get("evidence_review_ids") or [],
            "sample_size": item.get("sample_size") or 0,
            "product_count": item.get("product_count") or 0,
            "source": "validation_hypothesis",
        })
    return {
        "learn_from_competitors": learn,
        "avoid_competitor_failures": avoid,
        "validation_hypotheses": hypotheses,
    }


def _build_bootstrap_digest(snapshot, analytics, kpis, action_priorities, issue_diagnostics, mode):
    if mode != "bootstrap":
        return {}
    context = _contract_context(snapshot)
    data_quality = analytics.get("data_quality") or {}
    immediate_attention = []
    for item in action_priorities[:3]:
        title = item.get("short_title") or item.get("full_action") or item.get("label_display")
        if title:
            immediate_attention.append(title)
    if not immediate_attention:
        for item in issue_diagnostics[:3]:
            title = item.get("recommended_action") or item.get("ai_recommendation") or item.get("label_display")
            if title:
                immediate_attention.append(title)
    if not immediate_attention and (kpis.get("attention_product_count") or 0) > 0:
        immediate_attention.append(f"需关注产品 {kpis.get('attention_product_count')} 个")
    return {
        "baseline_summary": {
            "headline": "监控起点已建立",
            "product_count": context["product_count"],
            "review_count": context["review_count"],
            "coverage_rate": kpis.get("coverage_rate"),
            "translation_completion_rate": kpis.get("translation_completion_rate"),
        },
        "data_quality": {
            "historical_backfill_ratio": kpis.get("historical_backfill_ratio"),
            "estimated_date_ratio": kpis.get("estimated_date_ratio"),
            "low_coverage_products": data_quality.get("low_coverage_products") or [],
        },
        "immediate_attention": immediate_attention,
        "change_terms_blocked": True,
    }


def _build_delivery(analytics):
    delivery = analytics.get("delivery") or {}
    report_generated = delivery.get("report_generated")
    if report_generated is None:
        report_generated = bool(analytics.get("report_generated"))
    email_delivered = delivery.get("email_delivered")
    if email_delivered is None:
        email_delivered = bool(analytics.get("email_delivered"))
    workflow_delivered = delivery.get("workflow_notification_delivered")
    if workflow_delivered is None:
        workflow_delivered = bool(delivery.get("notification_delivered"))
    return {
        "report_generated": bool(report_generated),
        "email_delivered": bool(email_delivered),
        "workflow_notification_delivered": bool(workflow_delivered),
        "deadletter_count": int(delivery.get("deadletter_count") or analytics.get("deadletter_count") or 0),
        "internal_status": (
            delivery.get("internal_status")
            or analytics.get("report_phase")
            or analytics.get("workflow_status")
            or "unknown"
        ),
    }


def build_report_user_contract(*, snapshot, analytics, llm_copy=None):
    snapshot = snapshot or {}
    analytics = analytics or {}
    existing = analytics.get("report_user_contract") or {}
    mode = analytics.get("report_semantics") or analytics.get("mode") or "bootstrap"
    if mode == "baseline":
        mode = "bootstrap"
    if mode not in {"bootstrap", "incremental"}:
        mode = "bootstrap"
    kpis = dict(analytics.get("kpis") or existing.get("kpis") or {})
    issue_diagnostics = existing.get("issue_diagnostics") or _build_issue_diagnostics(analytics) or []
    action_priorities = (
        existing.get("action_priorities")
        or ((analytics.get("report_copy") or {}).get("improvement_priorities"))
        or []
    )

    contract = {
        "schema_version": SCHEMA_VERSION,
        "mode": mode,
        "logical_date": snapshot.get("logical_date") or analytics.get("logical_date"),
        "contract_context": _contract_context(snapshot),
        "metric_definitions": _build_metric_definitions(kpis, mode),
        "kpis": kpis,
        "kpi_semantics": existing.get("kpi_semantics") or {},
        "action_priorities": action_priorities,
        "issue_diagnostics": issue_diagnostics,
        "heatmap": existing.get("heatmap") or {},
        "competitor_insights": existing.get("competitor_insights") or _build_competitor_insights(analytics),
        "bootstrap_digest": (
            existing.get("bootstrap_digest")
            or _build_bootstrap_digest(snapshot, analytics, kpis, action_priorities, issue_diagnostics, mode)
        ),
        "delivery": existing.get("delivery") or _build_delivery(analytics),
        "validation_warnings": list(existing.get("validation_warnings") or []),
    }
    if llm_copy:
        contract = merge_llm_copy_into_contract(contract, llm_copy)
    return contract


def merge_llm_copy_into_contract(contract, llm_copy):
    merged = copy.deepcopy(contract or {})
    merged.setdefault("action_priorities", [])
    warnings = list(merged.get("validation_warnings") or [])
    diagnostics = {
        item.get("label_code"): item
        for item in merged.get("issue_diagnostics") or []
        if item.get("label_code")
    }
    actions = []
    for item in (llm_copy or {}).get("improvement_priorities") or []:
        action = dict(item)
        label_code = action.get("label_code")
        diagnostic = diagnostics.get(label_code) or {}
        allowed_products = set(diagnostic.get("allowed_products") or diagnostic.get("affected_products") or [])
        allowed_review_ids = set(diagnostic.get("evidence_review_ids") or [])
        affected_products = set(action.get("affected_products") or [])
        evidence_review_ids = set(action.get("evidence_review_ids") or [])
        valid_products = bool(allowed_products) and affected_products.issubset(allowed_products)
        valid_evidence = not evidence_review_ids or evidence_review_ids.issubset(allowed_review_ids)
        if diagnostic and valid_products and valid_evidence:
            action["source"] = "llm_rewrite"
        else:
            action["source"] = "evidence_insufficient"
            warnings.append(
                f"priority {label_code or '<missing>'} failed evidence validation"
            )
        action.setdefault("evidence_count", len(action.get("evidence_review_ids") or []))
        action.setdefault("affected_products_count", len(action.get("affected_products") or []))
        if not action.get("top_complaint"):
            text_evidence = diagnostic.get("text_evidence") or []
            if text_evidence:
                action["top_complaint"] = text_evidence[0].get("display_body") or ""
        actions.append(action)
    merged["action_priorities"] = actions
    merged["validation_warnings"] = warnings
    return merged
