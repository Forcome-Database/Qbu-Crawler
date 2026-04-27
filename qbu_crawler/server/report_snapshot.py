"""Immutable report snapshot helpers for workflow-based reporting."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from qbu_crawler import config, models
from qbu_crawler.server import report, report_analytics, report_html, report_llm
from qbu_crawler.server.report_artifacts import record_artifact
from qbu_crawler.server.report_common import BACKFILL_DOMINANT_RATIO

_logger = logging.getLogger(__name__)

_RECIPIENTS_FILE_PATH = os.path.join(
    os.path.dirname(__file__), "openclaw", "workspace", "config", "email_recipients.txt"
)


def _record_artifact_safe(
    run_id, artifact_type: str, path, *, template_version: str | None = None,
) -> None:
    """F011 §5.1 — record one artifact with its own connection, swallowing errors.

    Wired into report-generating code paths where the parent flow must not
    abort if artifact bookkeeping fails.  Skips silently when ``run_id`` or
    ``path`` is falsy (some code paths may pass ``None`` on partial failure).
    """
    if not run_id or not path:
        return
    try:
        conn = models.get_conn()
        try:
            record_artifact(
                conn,
                run_id=int(run_id),
                artifact_type=artifact_type,
                path=str(path),
                template_version=template_version,
            )
        finally:
            conn.close()
    except Exception:
        _logger.warning(
            "record_artifact(%s) failed for run %s path=%s",
            artifact_type, run_id, path, exc_info=True,
        )


def get_email_recipients() -> list[str]:
    """Unified email recipient loader.

    Priority: config.EMAIL_RECIPIENTS (env var) > openclaw file > empty list.
    """
    if config.EMAIL_RECIPIENTS:
        return list(config.EMAIL_RECIPIENTS)

    if os.path.exists(_RECIPIENTS_FILE_PATH):
        return report.load_email_recipients(_RECIPIENTS_FILE_PATH)
    return []


def should_send_quiet_email(run_id):
    """Determine whether to send a quiet-day email or skip.

    Returns (should_send: bool, digest_mode: str | None, consecutive: int).
    digest_mode is "weekly_digest" on day 7, 14, 21...

    Rules (spec 15.5):
    - First N quiet days (default 3): always send
    - Days N+1 to 6: skip
    - Day 7 (and 14, 21...): send as weekly digest
    - Days 8+: repeat 7-day cycle
    """
    threshold = int(os.getenv("REPORT_QUIET_EMAIL_DAYS", "3"))

    conn = models.get_conn()
    try:
        rows = conn.execute(
            """
            SELECT report_mode FROM workflow_runs
            WHERE workflow_type = 'daily' AND status = 'completed' AND id < ?
            ORDER BY id DESC LIMIT 30
            """,
            (run_id,),
        ).fetchall()
    finally:
        conn.close()

    consecutive = 0
    for row in rows:
        if row["report_mode"] == "quiet":
            consecutive += 1
        else:
            break

    if consecutive < threshold:
        return True, None, consecutive
    if (consecutive + 1) % 7 == 0:  # +1 because current run is also quiet
        return True, "weekly_digest", consecutive
    return False, None, consecutive


def _artifact_search_roots(stored_path: str | None = None) -> list[Path]:
    roots: list[Path] = []

    report_dir = getattr(config, "REPORT_DIR", "")
    if report_dir:
        roots.append(Path(report_dir))

    db_path = getattr(config, "DB_PATH", "")
    if db_path:
        roots.append(Path(db_path).resolve().parent / "reports")

    if stored_path:
        stored = Path(stored_path)
        if str(stored.parent) not in {"", "."}:
            roots.append(stored.parent)

    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        unique.append(root)
    return unique


def _artifact_glob_patterns(run_id: int | None, kind: str | None) -> list[str]:
    if not run_id or not kind:
        return []
    if kind == "snapshot":
        return [f"workflow-run-{run_id}-snapshot-*.json"]
    if kind == "analytics":
        return [f"workflow-run-{run_id}-analytics-*.json"]
    if kind == "excel":
        return [f"workflow-run-{run_id}-full-report.xlsx"]
    if kind == "html":
        return [f"workflow-run-{run_id}-full-report.html"]
    return []


def _resolve_artifact_path(
    stored_path: str | None,
    *,
    run_id: int | None = None,
    kind: str | None = None,
) -> str | None:
    if not stored_path:
        return None

    raw = Path(stored_path)
    if raw.is_file():
        return str(raw)

    basename = raw.name
    allow_pattern_fallback = bool(
        run_id and kind and basename.startswith(f"workflow-run-{run_id}-")
    )
    for root in _artifact_search_roots(stored_path):
        if basename:
            candidate = root / basename
            if candidate.is_file():
                return str(candidate)
        if allow_pattern_fallback:
            for pattern in _artifact_glob_patterns(run_id, kind):
                matches = sorted(root.glob(pattern))
                if matches:
                    return str(matches[-1])
    return None


def _artifact_db_value(path: str | None) -> str | None:
    if not path:
        return None

    target = Path(path).resolve()
    for root in _artifact_search_roots(path):
        try:
            relative = target.relative_to(root.resolve())
        except ValueError:
            continue
        return str(relative).replace("\\", "/")
    return str(target)


def load_previous_report_context(run_id):
    """Load most recent completed run's analytics and snapshot.

    Skips runs without analytics (quiet/change mode runs).
    Returns (analytics_dict, snapshot_dict) or (None, None).
    """
    try:
        prev_run = models.get_previous_completed_run(run_id)
    except Exception as e:
        _logger.warning("Failed to locate previous report context: %s", e)
        return None, None
    if not prev_run or not prev_run.get("analytics_path"):
        return None, None

    analytics_path = _resolve_artifact_path(
        prev_run.get("analytics_path"),
        run_id=prev_run.get("id"),
        kind="analytics",
    )
    if not analytics_path:
        return None, None

    try:
        analytics = json.loads(Path(analytics_path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as e:
        _logger.warning("Failed to load previous analytics: %s", e)
        return None, None

    snapshot = None
    if prev_run.get("snapshot_path"):
        snapshot_path = _resolve_artifact_path(
            prev_run.get("snapshot_path"),
            run_id=prev_run.get("id"),
            kind="snapshot",
        )
        if not snapshot_path:
            return analytics, None
        try:
            snapshot = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as e:
            _logger.warning("Failed to load previous snapshot: %s", e)

    return analytics, snapshot


_MISSING_SENTINELS = (None, "", "unknown")


def _is_missing(value) -> bool:
    """判断字段值是否为"采集缺失"（不是真实业务状态）。

    爬虫对三类缺失的约定：
      - None：字段未被提取到（如 rating 无法解析）
      - "unknown"：stock_status 的显式失败标记
      - ""：极少数字段的默认空值
    """
    return value in _MISSING_SENTINELS


def _price_changed(a, b) -> bool:
    """只在双侧都是有效值且差值 >= 0.01 时判定变动。"""
    if _is_missing(a) or _is_missing(b):
        return False
    return abs(float(a) - float(b)) >= 0.01


def _simple_changed(a, b) -> bool:
    """stock / rating 通用：双侧都是有效值且不相等。"""
    if _is_missing(a) or _is_missing(b):
        return False
    return a != b


def detect_snapshot_changes(current_snapshot, previous_snapshot):
    """Compare two snapshots for real business changes.

    Missing values (采集失败) are NOT treated as business changes.
    Data-quality events are surfaced through a separate channel — see
    qbu_crawler/server/scrape_quality.py and workflows.py.

    Returns dict with: has_changes, price_changes, stock_changes,
    rating_changes, new_products, removed_products.
    """
    changes = {
        "has_changes": False,
        "price_changes": [], "stock_changes": [], "rating_changes": [],
        "new_products": [], "removed_products": [],
    }

    if previous_snapshot is None:
        return changes

    prev_by_sku = {p["sku"]: p for p in previous_snapshot.get("products", [])}

    for product in current_snapshot.get("products", []):
        sku = product.get("sku", "")
        prev = prev_by_sku.get(sku)
        if not prev:
            changes["new_products"].append(product)
            changes["has_changes"] = True
            continue

        name = product.get("name", sku)

        if _price_changed(product.get("price"), prev.get("price")):
            changes["price_changes"].append(
                {"sku": sku, "name": name,
                 "old": prev.get("price"), "new": product.get("price")})
            changes["has_changes"] = True

        if _simple_changed(product.get("stock_status"), prev.get("stock_status")):
            changes["stock_changes"].append(
                {"sku": sku, "name": name,
                 "old": prev.get("stock_status"), "new": product.get("stock_status")})
            changes["has_changes"] = True

        if _simple_changed(product.get("rating"), prev.get("rating")):
            changes["rating_changes"].append(
                {"sku": sku, "name": name,
                 "old": prev.get("rating"), "new": product.get("rating")})
            changes["has_changes"] = True

    current_skus = {p.get("sku") for p in current_snapshot.get("products", [])}
    for sku, prev_product in prev_by_sku.items():
        if sku not in current_skus:
            changes["removed_products"].append(prev_product)
            changes["has_changes"] = True

    return changes


def determine_report_mode(snapshot, previous_snapshot, previous_analytics):
    """Central routing for report mode selection.

    Returns:
        mode: "full" | "change" | "quiet"
        context: dict with mode-specific metadata
    """
    has_reviews = bool(snapshot.get("reviews"))

    if has_reviews:
        changes = detect_snapshot_changes(snapshot, previous_snapshot)
        return "full", {"changes": changes}

    changes = detect_snapshot_changes(snapshot, previous_snapshot)
    if changes.get("has_changes"):
        return "change", {"changes": changes}

    return "quiet", {"previous_analytics": previous_analytics}


def compute_cluster_changes(current_clusters, previous_clusters, logical_date):
    """Diff two cluster lists to detect new, escalated, improving, and de-escalated clusters.

    Args:
        current_clusters: list of cluster dicts from current analytics
        previous_clusters: list of cluster dicts from previous analytics (may be None)
        logical_date: date object for "improving" detection

    Returns dict with keys: new, escalated, improving, de_escalated
    """
    from datetime import datetime, timedelta  # noqa: F401 (timedelta imported for completeness)

    prev_by_code = {c["label_code"]: c for c in (previous_clusters or [])}
    sev_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}

    changes = {"new": [], "escalated": [], "improving": [], "de_escalated": []}

    for cluster in current_clusters:
        code = cluster.get("label_code", "")
        prev = prev_by_code.get(code)

        if prev is None:
            changes["new"].append({
                "label_code": code,
                "label_display": cluster.get("label_display", code),
                "review_count": cluster.get("review_count", 0),
                "severity": cluster.get("severity", "low"),
                "affected_product_count": cluster.get("affected_product_count")
                or len(cluster.get("affected_products") or []),
                "affected_products": cluster.get("affected_products", []),
            })
            continue

        delta = cluster.get("review_count", 0) - prev.get("review_count", 0)
        cur_sev = sev_order.get(cluster.get("severity"), 0)
        prev_sev = sev_order.get(prev.get("severity"), 0)

        if delta > 0:
            changes["escalated"].append({
                "label_code": code,
                "label_display": cluster.get("label_display", code),
                "delta": delta,
                "old_count": prev.get("review_count", 0),
                "new_count": cluster.get("review_count", 0),
                "severity": cluster.get("severity", "low"),
                "severity_changed": cur_sev > prev_sev,
                "affected_product_count": cluster.get("affected_product_count")
                or len(cluster.get("affected_products") or []),
            })
        elif cur_sev < prev_sev:
            changes["de_escalated"].append({
                "label_code": code,
                "label_display": cluster.get("label_display", code),
                "old_severity": prev.get("severity"),
                "new_severity": cluster.get("severity"),
                "review_count": cluster.get("review_count", 0),
                "affected_product_count": cluster.get("affected_product_count")
                or len(cluster.get("affected_products") or []),
            })

    # Improving: clusters unchanged for 7+ days
    # TODO(14.9): When has_estimated_dates is true, this last_seen comparison
    # may be unreliable due to relative date parsing. A future enhancement
    # should pass the flag and fall back to scraped_at-based last_seen.
    if isinstance(logical_date, str):
        try:
            from datetime import datetime
            logical_date = datetime.strptime(logical_date, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            logical_date = None

    if logical_date:
        for cluster in current_clusters:
            code = cluster.get("label_code", "")
            prev = prev_by_code.get(code)
            if prev is None:
                continue
            last_seen = cluster.get("last_seen")
            if not last_seen:
                continue
            try:
                from datetime import datetime
                last_seen_date = datetime.strptime(last_seen, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                continue
            days_quiet = (logical_date - last_seen_date).days
            if days_quiet >= 7 and cluster.get("review_count", 0) == prev.get("review_count", 0):
                changes["improving"].append({
                    "label_code": code,
                    "label_display": cluster.get("label_display", code),
                    "days_quiet": days_quiet,
                    "review_count": cluster.get("review_count", 0),
                    "severity": cluster.get("severity", "low"),
                    "affected_product_count": cluster.get("affected_product_count")
                    or len(cluster.get("affected_products") or []),
                })

    return changes


def build_change_digest(snapshot, analytics, previous_snapshot=None, previous_analytics=None):
    from qbu_crawler.server.report_common import _parse_date_flexible, has_estimated_dates

    logical_date_str = snapshot.get("logical_date") or config.now_shanghai().date().isoformat()
    logical_day = date.fromisoformat(logical_date_str)
    cutoff = logical_day - timedelta(days=30)
    reviews = snapshot.get("reviews") or []
    kpis = analytics.get("kpis") or {}
    report_semantics = analytics.get("report_semantics") or (
        "bootstrap" if analytics.get("mode", "baseline") == "baseline" else "incremental"
    )
    baseline_day_index = analytics.get("baseline_day_index") or ((analytics.get("baseline_sample_days") or 0) + 1)
    baseline_display_state = analytics.get("baseline_display_state") or (
        "initial" if baseline_day_index == 1 else "building"
    )
    if report_semantics == "bootstrap" and baseline_display_state == "initial":
        window_meaning = "首次建档，当前结果用于建立监控基线"
    elif report_semantics == "bootstrap":
        window_meaning = f"基线建立期第{baseline_day_index}天，本次入库用于补足基线，不按新增口径解释"
    else:
        window_meaning = "增量监控期，本区块聚焦本次运行变化"

    review_contexts = []
    for review in reviews:
        published = (
            _parse_date_flexible(review.get("date_published_parsed"), anchor_date=logical_day)
            or _parse_date_flexible(review.get("date_published"), anchor_date=logical_day)
        )
        review_contexts.append({"review": review, "published": published})

    fresh_contexts = [
        item for item in review_contexts
        if item["published"] and item["published"] >= cutoff
    ]
    fresh_reviews = [item["review"] for item in fresh_contexts]

    own_reviews = [review for review in reviews if review.get("ownership") == "own"]
    competitor_reviews = [review for review in reviews if review.get("ownership") == "competitor"]
    own_negative_reviews = [
        review for review in own_reviews
        if (review.get("rating") or 5) <= config.NEGATIVE_THRESHOLD
    ]
    fresh_own_negative_contexts = [
        item for item in fresh_contexts
        if item["review"].get("ownership") == "own"
        and (item["review"].get("rating") or 5) <= config.NEGATIVE_THRESHOLD
    ]

    if report_semantics == "bootstrap":
        product_changes = {
            "has_changes": False,
            "price_changes": [],
            "stock_changes": [],
            "rating_changes": [],
            "new_products": [],
            "removed_products": [],
        }
        cluster_changes = {"new": [], "escalated": [], "improving": [], "de_escalated": []}
    else:
        product_changes = detect_snapshot_changes(snapshot, previous_snapshot)
        cluster_changes = compute_cluster_changes(
            ((analytics.get("self") or {}).get("top_negative_clusters") or []),
            ((previous_analytics or {}).get("self") or {}).get("top_negative_clusters") or [],
            logical_date_str,
        )

    issue_changes = {"new": [], "escalated": [], "improving": [], "de_escalated": []}
    for key, change_type in (
        ("new", "new"),
        ("escalated", "escalated"),
        ("improving", "improving"),
        ("de_escalated", "de_escalated"),
    ):
        for item in cluster_changes.get(key, []):
            issue_changes[key].append(
                {
                    "label_code": item.get("label_code"),
                    "label_display": item.get("label_display") or item.get("label_code") or "",
                    "change_type": change_type,
                    "current_review_count": item.get("new_count", item.get("review_count", 0)),
                    "delta_review_count": item.get("delta", item.get("review_count", 0) if key == "new" else 0),
                    "affected_product_count": item.get("affected_product_count", 0),
                    "severity": item.get("severity"),
                    "severity_changed": bool(item.get("severity_changed", False)),
                    "days_quiet": item.get("days_quiet", 0),
                }
            )

    def _state_change_count():
        return sum(
            len(product_changes.get(name, []))
            for name in ("price_changes", "stock_changes", "rating_changes", "new_products", "removed_products")
        )

    def _sort_by_published_desc(item):
        published = item["published"]
        return published.toordinal() if published else -1

    fresh_negative_reviews = sorted(
        fresh_own_negative_contexts,
        key=lambda item: (
            item["review"].get("rating") if item["review"].get("rating") is not None else 5,
            -_sort_by_published_desc(item),
            0 if (item["review"].get("images") or []) else 1,
        ),
    )
    fresh_competitor_positive_reviews = sorted(
        [
            item for item in fresh_contexts
            if item["review"].get("ownership") == "competitor"
            and (item["review"].get("rating") or 0) >= 4
        ],
        key=lambda item: (
            -(item["review"].get("rating") or 0),
            -_sort_by_published_desc(item),
        ),
    )

    review_signals = {
        "fresh_negative_reviews": [
            item["review"] for item in fresh_negative_reviews[:5]
        ],
        "fresh_competitor_positive_reviews": [
            item["review"] for item in fresh_competitor_positive_reviews[:3]
        ],
    }

    ingested_review_count = len(reviews)
    fresh_review_count = len(fresh_reviews)
    historical_backfill_count = ingested_review_count - fresh_review_count
    backfill_ratio = (
        historical_backfill_count / ingested_review_count
        if ingested_review_count
        else 0
    )

    warnings = {
        "translation_incomplete": {
            "enabled": (kpis.get("untranslated_count", snapshot.get("untranslated_count", 0)) or 0) > 0,
            "message": (
                f"{kpis.get('untranslated_count', snapshot.get('untranslated_count', 0)) or 0} 条评论翻译未完成，中文分析可能不完整"
                if (kpis.get("untranslated_count", snapshot.get("untranslated_count", 0)) or 0) > 0
                else ""
            ),
        },
        "estimated_dates": {
            "enabled": has_estimated_dates(reviews, logical_date_str),
            "message": "评论发布时间存在较高比例的相对时间估算，新增与趋势口径可能降级"
            if has_estimated_dates(reviews, logical_date_str)
            else "",
        },
        "backfill_dominant": {
            "enabled": backfill_ratio >= BACKFILL_DOMINANT_RATIO,
            "message": f"本次入库以历史补采为主，占比 {backfill_ratio:.0%}" if backfill_ratio >= BACKFILL_DOMINANT_RATIO else "",
        },
    }

    empty_state_enabled = (
        report_semantics == "incremental"
        and not any(issue_changes[key] for key in issue_changes)
        and _state_change_count() == 0
        and not review_signals["fresh_negative_reviews"]
        and not review_signals["fresh_competitor_positive_reviews"]
    )

    view_state = "bootstrap"
    if report_semantics != "bootstrap":
        view_state = "empty" if empty_state_enabled else "active"

    # ── F011 H22 / B4: 三层金字塔 ──────────────────────────────────────────
    # Window threshold: prefer data_since (run window); fallback to logical_day - 30d.
    # Filter uses scraped_at (ingestion time), NOT date_published.
    # Parse both sides to UTC-normalized datetime for robust tz-aware comparison.
    def _parse_iso_utc(value: str | None):
        """Parse an ISO-8601 string to a UTC-normalized datetime; return None on failure."""
        if not value:
            return None
        s = str(value).strip().replace(" ", "T")
        # Map trailing Z to +00:00 for fromisoformat compatibility (Python <3.11 lacks Z support).
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return None
        # Treat naive datetimes as UTC for comparison.
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt

    data_since_value = snapshot.get("data_since")
    threshold_dt = _parse_iso_utc(data_since_value) if data_since_value else None
    if threshold_dt is None:
        # Fallback: 30 days before logical_day (UTC-normalized)
        threshold_dt = datetime.combine(logical_day - timedelta(days=30), datetime.min.time(), tzinfo=timezone.utc)

    def _scraped_at_in_window(rev) -> bool:
        sa_dt = _parse_iso_utc(rev.get("scraped_at"))
        return bool(sa_dt) and sa_dt >= threshold_dt

    # --- immediate_attention ---
    own_new_neg_by_product: dict = {}
    for r in reviews:
        if r.get("ownership") != "own":
            continue
        if (r.get("rating") or 5) > config.NEGATIVE_THRESHOLD:
            continue
        if not _scraped_at_in_window(r):
            continue
        pname = r.get("product_name") or "(unknown)"
        own_new_neg_by_product.setdefault(pname, []).append(r)

    own_new_negative_reviews = []
    for pname, rev_list in own_new_neg_by_product.items():
        label_codes = []
        for r in rev_list:
            # F011 §4.2.5 I-5 — analysis_labels is a JSON string in DB rows;
            # the old `analysis_labels_parsed` key was phantom (no upstream
            # writer), making this loop silently skip every review.
            raw_labels = r.get("analysis_labels") or "[]"
            if isinstance(raw_labels, list):
                labels_iter = raw_labels
            else:
                parsed = json.loads(raw_labels)
                labels_iter = parsed if isinstance(parsed, list) else []
            for lab in labels_iter:
                if not isinstance(lab, dict):
                    continue
                if (lab.get("polarity") or "").lower() == "negative":
                    if lab.get("code"):
                        label_codes.append(lab["code"])
        own_new_negative_reviews.append({
            "product_name": pname,
            "review_count": len(rev_list),
            "primary_problems": [c for c, _ in Counter(label_codes).most_common(2)],
        })

    # Build sku → ownership map for filtering rating/stock changes.
    # product_changes rows use keys: sku, name, old, new (from detect_snapshot_changes).
    sku_to_ownership = {
        p.get("sku"): p.get("ownership")
        for p in (snapshot.get("products") or [])
        if p.get("sku")
    }

    def _is_own_change(change_row) -> bool:
        sku = change_row.get("sku")
        return sku_to_ownership.get(sku) == "own"

    own_rating_drops = []
    for row in product_changes.get("rating_changes", []):
        if not _is_own_change(row):
            continue
        prev = row.get("old")
        new_val = row.get("new")
        try:
            if prev is not None and new_val is not None and float(new_val) < float(prev):
                own_rating_drops.append({
                    "product_name": row.get("name"),
                    "sku": row.get("sku"),
                    "prev": prev,
                    "new": new_val,
                    "delta": round(float(new_val) - float(prev), 2),
                })
        except (TypeError, ValueError):
            continue

    own_stock_alerts = []
    for row in product_changes.get("stock_changes", []):
        if not _is_own_change(row):
            continue
        new_status = (row.get("new") or "").lower()
        if any(token in new_status for token in ("out", "soldout", "sold_out", "limited")):
            own_stock_alerts.append({
                "product_name": row.get("name"),
                "sku": row.get("sku"),
                "prev_status": row.get("old"),
                "new_status": row.get("new"),
            })

    immediate_attention = {
        "own_new_negative_reviews": own_new_negative_reviews,
        "own_rating_drops": own_rating_drops,
        "own_stock_alerts": own_stock_alerts,
    }

    # --- trend_changes (mirror issue_changes; richer aggregation in follow-up tasks) ---
    # F011 §4.2.4 — keys MUST end in `_issues` to match the template contract
    # (daily_report_v3.html.j2:184-194). Renaming them here would silently break
    # Layer 2 (📈 趋势变化) rendering in production.
    trend_changes = {
        "new_issues": list(issue_changes.get("new", [])),
        "escalated_issues": list(issue_changes.get("escalated", [])),
        "improving_issues": list(issue_changes.get("improving", [])),
        "de_escalated_issues": list(issue_changes.get("de_escalated", [])),
    }

    # --- competitive_opportunities ---
    comp_new_neg_by_product: dict = {}
    for r in reviews:
        if r.get("ownership") != "competitor":
            continue
        if (r.get("rating") or 5) > config.NEGATIVE_THRESHOLD:
            continue
        if not _scraped_at_in_window(r):
            continue
        pname = r.get("product_name") or "(unknown)"
        comp_new_neg_by_product.setdefault(pname, []).append(r)

    competitor_new_negative_reviews = [
        {"product_name": pname, "review_count": len(rev_list)}
        for pname, rev_list in comp_new_neg_by_product.items()
    ]

    competitive_opportunities = {
        "competitor_new_negative_reviews": competitor_new_negative_reviews,
        "competitor_new_positive_reviews": review_signals.get("fresh_competitor_positive_reviews", [])[:3],
    }
    # ── end 三层金字塔 ────────────────────────────────────────────────────────

    return {
        "enabled": True,
        "view_state": view_state,
        "suppressed_reason": "",
        # F011 H22 三层金字塔（新增，向后兼容）
        "immediate_attention": immediate_attention,
        "trend_changes": trend_changes,
        "competitive_opportunities": competitive_opportunities,
        "summary": {
            "ingested_review_count": ingested_review_count,
            "ingested_own_review_count": len(own_reviews),
            "ingested_competitor_review_count": len(competitor_reviews),
            "ingested_own_negative_count": len(own_negative_reviews),
            "fresh_review_count": fresh_review_count,
            "historical_backfill_count": historical_backfill_count,
            "fresh_own_negative_count": len(fresh_own_negative_contexts),
            "issue_new_count": len(issue_changes["new"]),
            "issue_escalated_count": len(issue_changes["escalated"]),
            "issue_improving_count": len(issue_changes["improving"]),
            "state_change_count": _state_change_count(),
            "baseline_day_index": baseline_day_index,
            "baseline_display_state": baseline_display_state,
            "window_meaning": window_meaning,
        },
        "issue_changes": issue_changes,
        "product_changes": {
            "price_changes": product_changes.get("price_changes", []),
            "stock_changes": product_changes.get("stock_changes", []),
            "rating_changes": product_changes.get("rating_changes", []),
            "new_products": product_changes.get("new_products", []),
            "removed_products": product_changes.get("removed_products", []),
        },
        "review_signals": review_signals,
        "warnings": warnings,
        "empty_state": {
            "enabled": empty_state_enabled,
            "title": "本期无显著变化" if empty_state_enabled else "",
            "description": (
                "本次运行未发现需要立即处理的新增问题或明显产品状态变化。"
                if empty_state_enabled
                else ""
            ),
        },
    }


class FullReportGenerationError(RuntimeError):
    def __init__(self, message, *, analytics_path=None, excel_path=None, pdf_path=None):
        super().__init__(message)
        self.analytics_path = analytics_path
        self.excel_path = excel_path
        self.pdf_path = pdf_path  # Legacy — always None in V3


def freeze_report_snapshot(run_id: int, now: str | None = None) -> dict:
    """Freeze a workflow run into a single JSON snapshot artifact."""
    run = models.get_workflow_run(run_id)
    if run is None:
        raise ValueError(f"Workflow run {run_id} not found")

    existing_path = run.get("snapshot_path") or ""
    resolved_existing_path = _resolve_artifact_path(existing_path, run_id=run_id, kind="snapshot")
    if resolved_existing_path:
        snapshot = load_report_snapshot(resolved_existing_path)
        updated = models.update_workflow_run(
            run_id,
            snapshot_at=snapshot.get("snapshot_at"),
            snapshot_path=_artifact_db_value(resolved_existing_path),
            snapshot_hash=snapshot.get("snapshot_hash"),
            report_phase=run.get("report_phase") or "none",
        )
        if updated:
            updated = dict(updated)
            updated["snapshot_path"] = resolved_existing_path
            return updated
        return models.get_workflow_run(run_id) or run

    products, reviews = report.query_report_data(run["data_since"], until=run["data_until"])
    for item in reviews:
        item.setdefault("headline_cn", "")
        item.setdefault("body_cn", "")

    # ── Enrich reviews with review_analysis fields (LLM analysis data) ──
    _review_ids = [r["id"] for r in reviews if r.get("id")]
    if _review_ids:
        _enriched_map = {
            ea["id"]: ea
            for ea in models.get_reviews_with_analysis(review_ids=_review_ids)
        }
        for r in reviews:
            ea = _enriched_map.get(r.get("id"))
            if ea:
                for _key in ("sentiment", "analysis_features", "analysis_labels",
                             "analysis_insight_cn", "analysis_insight_en"):
                    _val = ea.get(_key)
                    if _val is not None:
                        r.setdefault(_key, _val)

    translated_count = sum(1 for item in reviews if item.get("translate_status") == "done")
    snapshot_at = now or config.now_shanghai().isoformat()
    snapshot = {
        "run_id": run["id"],
        "logical_date": run["logical_date"],
        "data_since": run["data_since"],
        "data_until": run["data_until"],
        "snapshot_at": snapshot_at,
        "products": products,
        "reviews": reviews,
        "products_count": len(products),
        "reviews_count": len(reviews),
        "translated_count": translated_count,
        "untranslated_count": len(reviews) - translated_count,
    }

    # ── Dual-perspective: embed cumulative (all-time) data ──
    if config.REPORT_PERSPECTIVE == "dual":
        cum_products, cum_reviews = report.query_cumulative_data()
        cum_translated = sum(1 for r in cum_reviews if r.get("translate_status") == "done")
        snapshot["cumulative"] = {
            "products": cum_products,
            "reviews": cum_reviews,
            "products_count": len(cum_products),
            "reviews_count": len(cum_reviews),
            "translated_count": cum_translated,
            "untranslated_count": len(cum_reviews) - cum_translated,
        }

    # ── Hash excludes cumulative (Correction C) ──
    hash_payload = {k: v for k, v in snapshot.items() if k != "cumulative"}
    snapshot_hash = hashlib.sha1(
        json.dumps(hash_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    snapshot["snapshot_hash"] = snapshot_hash

    os.makedirs(config.REPORT_DIR, exist_ok=True)
    snapshot_path = os.path.join(
        config.REPORT_DIR,
        f"workflow-run-{run_id}-snapshot-{run['logical_date']}.json",
    )
    Path(snapshot_path).write_text(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )

    updated = models.update_workflow_run(
        run_id,
        snapshot_at=snapshot_at,
        snapshot_path=_artifact_db_value(snapshot_path),
        snapshot_hash=snapshot_hash,
    )

    # F011 §5.1 — register snapshot in report_artifacts.
    _record_artifact_safe(run_id, "snapshot", snapshot_path)

    if updated:
        updated = dict(updated)
        updated["snapshot_path"] = snapshot_path
        return updated
    return run


def load_report_snapshot(path: str) -> dict:
    resolved_path = _resolve_artifact_path(path, kind="snapshot")
    if not resolved_path:
        raise FileNotFoundError(path)
    snapshot = json.loads(Path(resolved_path).read_text(encoding="utf-8"))
    if "snapshot_hash" not in snapshot:
        raise ValueError(f"Snapshot at {resolved_path} is missing snapshot_hash")
    return snapshot


def build_fast_report(snapshot: dict) -> dict:
    return {
        "run_id": snapshot["run_id"],
        "logical_date": snapshot["logical_date"],
        "snapshot_hash": snapshot["snapshot_hash"],
        "products_count": snapshot["products_count"],
        "reviews_count": snapshot["reviews_count"],
        "translated_count": snapshot["translated_count"],
        "untranslated_count": snapshot["untranslated_count"],
    }


def _change_report_subject_prefix(changes):
    """Build dynamic subject prefix based on change types."""
    types = []
    if changes.get("price_changes"):
        types.append("价格")
    if changes.get("stock_changes"):
        types.append("库存")
    if changes.get("rating_changes"):
        types.append("评分")
    if changes.get("removed_products") or changes.get("new_products"):
        types.append("产品")
    if len(types) == 1:
        return f"[{types[0]}变动]"
    return "[数据变化]"


def _render_quiet_or_change_html(snapshot, prev_analytics, changes=None):
    """Render the quiet day or change report HTML using the quiet day template."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    template_dir = Path(__file__).parent / "report_templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "j2"]),
    )
    template = env.get_template("quiet_day_report.html.j2")

    css_path = template_dir / "daily_report_v3.css"
    css_text = css_path.read_text(encoding="utf-8") if css_path.exists() else ""

    translate_stats = models.get_translate_stats()

    # Resolve last full report link from the previous completed run
    last_full_report_path = None
    run_id_for_lookup = snapshot.get("run_id", 0)
    prev_run = models.get_previous_completed_run(run_id_for_lookup)
    if prev_run:
        # Construct expected path from run_id (v3 HTML naming convention)
        expected = os.path.join(
            config.REPORT_DIR,
            f"workflow-run-{prev_run['id']}-full-report.html",
        )
        if Path(expected).exists():
            last_full_report_path = expected
            # If REPORT_HTML_PUBLIC_URL is configured, convert to a URL for the link
            if config.REPORT_HTML_PUBLIC_URL:
                last_full_report_path = (
                    f"{config.REPORT_HTML_PUBLIC_URL}/{Path(expected).name}"
                )

    html = template.render(
        logical_date=snapshot.get("logical_date", ""),
        snapshot=snapshot,
        previous_analytics=prev_analytics,
        translate_stats=translate_stats,
        last_full_report_path=last_full_report_path,
        css_text=css_text,
        threshold=config.NEGATIVE_THRESHOLD,
        changes=changes,
    )

    run_id = snapshot.get("run_id", 0)
    mode_tag = "change" if changes else "quiet"
    output_path = os.path.join(
        config.REPORT_DIR,
        f"workflow-run-{run_id}-{mode_tag}-report.html",
    )
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    Path(output_path).write_text(html, encoding="utf-8")
    _logger.info("%s report HTML generated: %s", mode_tag, output_path)
    return output_path


def _send_mode_email(mode, snapshot, prev_analytics, changes=None,
                     report_url=None, analytics=None, risk_products=None,
                     consecutive_quiet=0):
    """Send email for any report mode using the appropriate template."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    template_dir = Path(__file__).parent / "report_templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "j2"]),
    )

    logical_date = snapshot.get("logical_date", "")
    kpis = (  # noqa: F841 — kept for future template use
        (prev_analytics or {}).get("kpis", {}) if mode != "full"
        else (analytics or {}).get("kpis", {})
    )

    # Build subject
    if mode == "full":
        subject = f"产品评论日报 {logical_date}"
    elif mode == "change":
        prefix = _change_report_subject_prefix(changes or {})
        subject = f"{prefix} 产品监控简报 {logical_date}"
    else:
        subject = f"[无变化] 产品监控简报 {logical_date}"

    # Render email template
    template_name = f"email_{mode}.html.j2"
    try:
        template = env.get_template(template_name)
    except Exception:
        _logger.warning("Email template %s not found, skipping", template_name)
        return {"success": False, "error": f"Template {template_name} not found", "recipients": []}

    try:
        body_html = template.render(
            logical_date=logical_date,
            snapshot=snapshot,
            analytics=analytics or prev_analytics or {},
            previous_analytics=prev_analytics,
            changes=changes,
            report_url=report_url,
            risk_products=risk_products or [],
            threshold=config.NEGATIVE_THRESHOLD,
            alert_level=(analytics or {}).get("alert_level", ("green", ""))[0] if analytics else "green",
            alert_text=(analytics or {}).get("alert_level", ("green", ""))[1] if analytics else "",
            report_copy=(analytics or {}).get("report_copy", {}),
            translate_stats=models.get_translate_stats() if mode == "quiet" else None,
            consecutive_quiet_days=consecutive_quiet,
        )
    except Exception as e:
        _logger.exception("Email template rendering failed for mode %s", mode)
        return {"success": False, "error": f"Template render error: {e}", "recipients": []}

    # Load recipients and send
    recipients = get_email_recipients()

    if not recipients:
        return {"success": True, "error": "No recipients configured", "recipients": []}

    try:
        result = report.send_email(
            recipients=recipients,
            subject=subject,
            body_text=subject,  # Plain text fallback
            body_html=body_html,
        )
        return result
    except Exception as e:
        _logger.warning("Email send failed: %s", e)
        return {"success": False, "error": str(e), "recipients": recipients}


def _generate_change_report(snapshot, send_email, prev_analytics, context):
    """Generate a change report (no new reviews, but price/stock/rating changed)."""
    run_id = snapshot.get("run_id", 0)
    changes = context.get("changes", {})

    # ── Cumulative analytics: compute from snapshot["cumulative"] when available ──
    cum_analytics = None
    analytics_path = None
    cumulative_computed = False
    if snapshot.get("cumulative"):
        try:
            cum_snapshot = {
                "run_id": run_id,
                "logical_date": snapshot.get("logical_date", ""),
                "data_since": snapshot.get("data_since", ""),
                "data_until": snapshot.get("data_until", ""),
                "snapshot_hash": snapshot.get("snapshot_hash", ""),
                **snapshot["cumulative"],
            }
            cum_analytics = report_analytics.build_report_analytics(cum_snapshot)
            from qbu_crawler.server.report_common import normalize_deep_report_analytics
            cum_analytics = normalize_deep_report_analytics(cum_analytics)
            os.makedirs(config.REPORT_DIR, exist_ok=True)
            analytics_path = os.path.join(
                config.REPORT_DIR,
                f"workflow-run-{run_id}-analytics-{snapshot.get('logical_date', 'unknown')}.json",
            )
            Path(analytics_path).write_text(
                json.dumps(cum_analytics, ensure_ascii=False, sort_keys=True, indent=2),
                encoding="utf-8",
            )
            cumulative_computed = True
            _logger.info("Change report: cumulative analytics computed and saved to %s", analytics_path)
        except Exception:
            _logger.exception("Change report: cumulative analytics computation failed")
            cum_analytics = None
            analytics_path = None

    # Use cumulative analytics when available, fall back to prev_analytics
    effective_analytics = cum_analytics or prev_analytics

    # Render quiet day HTML with change info
    html_path = None
    try:
        html_path = _render_quiet_or_change_html(snapshot, effective_analytics, changes=changes)
    except Exception:
        _logger.exception("Change report HTML generation failed")

    # Send email
    email_result = None
    if send_email:
        try:
            email_result = _send_mode_email("change", snapshot, effective_analytics, changes=changes)
        except Exception as e:
            email_result = {"success": False, "error": str(e), "recipients": []}

    return {
        "mode": "change",
        "status": "completed",
        "run_id": run_id,
        "snapshot_hash": snapshot.get("snapshot_hash", ""),
        "products_count": snapshot.get("products_count", 0),
        "reviews_count": 0,
        "html_path": _artifact_db_value(html_path),
        "excel_path": None,
        "analytics_path": _artifact_db_value(analytics_path),
        "cumulative_computed": cumulative_computed,
        "email": email_result,
    }


def _generate_quiet_report(snapshot, send_email, prev_analytics):
    """Generate a quiet day report (no new reviews, no changes)."""
    run_id = snapshot.get("run_id", 0)

    # Check if we should send this quiet-day email (also returns consecutive count)
    should_send, digest_mode, consecutive = should_send_quiet_email(run_id)

    # ── Cumulative analytics: compute from snapshot["cumulative"] when available ──
    cum_analytics = None
    analytics_path = None
    cumulative_computed = False
    if snapshot.get("cumulative"):
        try:
            cum_snapshot = {
                "run_id": run_id,
                "logical_date": snapshot.get("logical_date", ""),
                "data_since": snapshot.get("data_since", ""),
                "data_until": snapshot.get("data_until", ""),
                "snapshot_hash": snapshot.get("snapshot_hash", ""),
                **snapshot["cumulative"],
            }
            cum_analytics = report_analytics.build_report_analytics(cum_snapshot)
            from qbu_crawler.server.report_common import normalize_deep_report_analytics
            cum_analytics = normalize_deep_report_analytics(cum_analytics)
            os.makedirs(config.REPORT_DIR, exist_ok=True)
            analytics_path = os.path.join(
                config.REPORT_DIR,
                f"workflow-run-{run_id}-analytics-{snapshot.get('logical_date', 'unknown')}.json",
            )
            Path(analytics_path).write_text(
                json.dumps(cum_analytics, ensure_ascii=False, sort_keys=True, indent=2),
                encoding="utf-8",
            )
            cumulative_computed = True
            _logger.info("Quiet report: cumulative analytics computed and saved to %s", analytics_path)
        except Exception:
            _logger.exception("Quiet report: cumulative analytics computation failed")
            cum_analytics = None
            analytics_path = None

    # Use cumulative analytics when available, fall back to prev_analytics
    effective_analytics = cum_analytics or prev_analytics

    html_path = None
    try:
        html_path = _render_quiet_or_change_html(snapshot, effective_analytics)
    except Exception:
        _logger.exception("Quiet report HTML generation failed")

    email_result = None
    if send_email and should_send:
        try:
            email_result = _send_mode_email(
                "quiet", snapshot, effective_analytics,
                consecutive_quiet=consecutive,
            )
        except Exception as e:
            email_result = {"success": False, "error": str(e), "recipients": []}
    elif not should_send:
        email_result = {"success": True, "error": "Skipped (quiet day frequency)", "recipients": []}
        _logger.info("Quiet-day email skipped (consecutive quiet: reached skip window)")

    return {
        "mode": "quiet",
        "status": "completed_no_change",
        "run_id": run_id,
        "snapshot_hash": snapshot.get("snapshot_hash", ""),
        "products_count": snapshot.get("products_count", 0),
        "reviews_count": 0,
        "html_path": _artifact_db_value(html_path),
        "excel_path": None,
        "analytics_path": _artifact_db_value(analytics_path),
        "cumulative_computed": cumulative_computed,
        "email": email_result,
        "email_skipped": not should_send,
        "digest_mode": digest_mode,
    }


def generate_report_from_snapshot(snapshot, send_email=True, output_path=None):
    """Generate report for any mode (full/change/quiet).

    Replaces generate_full_report_from_snapshot with 3-mode routing.

    Returns dict with:
        mode: "full" | "change" | "quiet"
        status: "completed" | "completed_no_change"
        run_id, products_count, reviews_count
        html_path, excel_path, analytics_path (None for non-full modes)
        email: {success, error, recipients}
    """
    run_id = snapshot.get("run_id", 0)

    # Load previous context
    prev_analytics, prev_snapshot = load_previous_report_context(run_id)

    # Determine mode
    mode, context = determine_report_mode(snapshot, prev_snapshot, prev_analytics)

    # Write report_mode to workflow_runs
    try:
        models.update_workflow_run(run_id, report_mode=mode)
    except Exception:
        _logger.debug("Could not update report_mode for run %d", run_id, exc_info=True)

    _logger.info("Report mode: %s for run %d", mode, run_id)

    try:
        if mode == "full":
            # Entry point for 3-mode routing. workflows.py calls this function
            # instead of generate_full_report_from_snapshot directly.
            # Delegate to existing function (which handles its own email)
            result = generate_full_report_from_snapshot(
                snapshot, send_email=send_email, output_path=output_path,
            )
            result["mode"] = "full"
            # Full-mode email now uses email_full.html.j2 via report.render_email_full()
            result.setdefault("status", "completed")
            return result
        elif mode == "change":
            return _generate_change_report(snapshot, send_email, prev_analytics, context)
        else:
            return _generate_quiet_report(snapshot, send_email, prev_analytics)
    except Exception as e:
        _logger.exception("Report generation failed for run %d", run_id)
        # Send failure notification
        try:
            recipients = get_email_recipients()
            if recipients:
                report.send_email(
                    recipients=recipients,
                    subject=f"[报告失败] 产品监控 {snapshot.get('logical_date', '')}",
                    body_text=f"报告生成失败: {str(e)[:200]}\n请检查服务日志。",
                )
        except Exception:
            _logger.exception("Failed to send failure notification")
        raise


def _merge_post_normalize_mutations(normalized: dict, raw: dict) -> None:
    """Copy post-normalize mutations from raw analytics onto the already-normalized copy.

    After generate_full_report_from_snapshot calls normalize_deep_report_analytics(),
    it mutates raw analytics further (adds LLM insights as report_copy, cluster
    deep_analysis, window_review_ids). Those mutations need to ride along on the
    on-disk JSON. Matches clusters by label_code (not position) to survive future
    reordering / filtering in normalize_deep_report_analytics.
    """
    normalized["report_copy"] = raw.get("report_copy", normalized.get("report_copy"))
    if "window_review_ids" in raw:
        normalized["window_review_ids"] = raw["window_review_ids"]

    raw_clusters = (raw.get("self") or {}).get("top_negative_clusters") or []
    raw_by_label = {
        c.get("label_code"): c
        for c in raw_clusters
        if isinstance(c, dict)
    }
    for nc in (normalized.get("self") or {}).get("top_negative_clusters") or []:
        if not isinstance(nc, dict):
            continue
        match = raw_by_label.get(nc.get("label_code"))
        if match and "deep_analysis" in match:
            nc["deep_analysis"] = match["deep_analysis"]


def generate_full_report_from_snapshot(
    snapshot: dict,
    send_email: bool = True,
    output_path: str | None = None,
) -> dict:
    if not snapshot.get("reviews") and not snapshot.get("cumulative"):
        return {"status": "completed_no_change", "reason": "No new reviews"}

    report_date = datetime.fromisoformat(
        snapshot.get("data_since") or f"{snapshot['logical_date']}T00:00:00+08:00"
    )
    if output_path is None:
        output_path = os.path.join(
            config.REPORT_DIR,
            f"workflow-run-{snapshot['run_id']}-full-report.xlsx",
        )

    os.makedirs(config.REPORT_DIR, exist_ok=True)
    analytics_path = os.path.join(
        config.REPORT_DIR,
        f"workflow-run-{snapshot['run_id']}-analytics-{snapshot['logical_date']}.json",
    )
    html_output_path = os.path.join(
        config.REPORT_DIR,
        f"workflow-run-{snapshot['run_id']}-full-report.html",
    )
    excel_path = None
    pdf_path = None
    html_path = None

    try:
        # Correction F: sync labels on cumulative reviews (superset), call once
        if snapshot.get("cumulative"):
            _label_snapshot = {
                "reviews": snapshot["cumulative"]["reviews"],
            }
        else:
            _label_snapshot = snapshot
        synced_labels = report_analytics.sync_review_labels(_label_snapshot)

        # Use dual analytics when cumulative data exists
        if snapshot.get("cumulative"):
            analytics = report_analytics.build_dual_report_analytics(
                snapshot, synced_labels=synced_labels,
            )
        else:
            analytics = report_analytics.build_report_analytics(
                snapshot, synced_labels=synced_labels,
            )

        # Pre-normalize so LLM gets gap_analysis, enriched clusters, and top_symptoms
        from qbu_crawler.server.report_common import normalize_deep_report_analytics
        pre_normalized = normalize_deep_report_analytics(analytics)
        prev_analytics_ctx, prev_snapshot = load_previous_report_context(snapshot.get("run_id", 0))
        change_digest = build_change_digest(
            snapshot,
            pre_normalized,
            previous_snapshot=prev_snapshot,
            previous_analytics=prev_analytics_ctx,
        )
        analytics["change_digest"] = change_digest
        pre_normalized["change_digest"] = change_digest

        # F011 Critical A-1: route through v3 orchestrator (prompt v3 + schema +
        # tone guards + assert_consistency + retry + fallback). When the LLM
        # output yields empty improvement_priorities (LLM disabled, persistent
        # validation failure, or sparse fallback), backfill via the rule-based
        # `build_fallback_priorities` so the email_full Top 3 行动 block always
        # has something to render (AC-10 / AC-18 / §5.3).
        insights = report_llm.generate_report_insights_with_validation(
            pre_normalized, snapshot=snapshot
        )
        if not (insights or {}).get("improvement_priorities"):
            risk_products = (pre_normalized.get("self") or {}).get("risk_products") or []
            top_negative_clusters = (
                (pre_normalized.get("self") or {}).get("top_negative_clusters") or []
            )
            insights = dict(insights or {})
            insights["improvement_priorities"] = report_analytics.build_fallback_priorities(
                risk_products, top_negative_clusters,
            )
        analytics["report_copy"] = insights

        # Cluster deep analysis (top N clusters with ≥5 reviews)
        if config.REPORT_CLUSTER_ANALYSIS:
            from qbu_crawler.server.report_llm import analyze_cluster_deep
            top_clusters = analytics.get("self", {}).get("top_negative_clusters", [])
            for cluster in top_clusters[:config.REPORT_MAX_CLUSTER_ANALYSIS]:
                if cluster.get("review_count", 0) >= 5:
                    try:
                        cluster_reviews = models.query_cluster_reviews(
                            label_code=cluster["label_code"],
                            ownership="own",
                            limit=30,
                        )
                    except Exception:
                        _logger.warning("Failed to load cluster reviews for deep analysis", exc_info=True)
                        continue
                    deep = analyze_cluster_deep(cluster, cluster_reviews)
                    if deep:
                        cluster["deep_analysis"] = deep

        # Attach window_review_ids so Excel can mark newly-added reviews (Correction H)
        if snapshot.get("cumulative"):
            analytics["window_review_ids"] = [
                r.get("id") for r in snapshot.get("reviews", []) if r.get("id")
            ]

        # Write the normalized analytics (with health_index / high_risk_count /
        # own_negative_review_rate_display etc.). The raw `analytics` object is
        # kept in memory for downstream Excel/V3-HTML calls, but the on-disk
        # JSON must match what the next run's `prev_analytics` consumer
        # (email_change.html.j2 / quiet_day_report.html.j2) expects.
        # `pre_normalized` was computed before LLM insights / cluster deep
        # analysis / window_review_ids were attached to the raw analytics,
        # so re-attach those post-normalization fields here instead of
        # normalizing a second time. Cluster deep_analysis is matched by
        # label_code (not position) to survive future reordering in normalize.
        _merge_post_normalize_mutations(pre_normalized, analytics)
        Path(analytics_path).write_text(
            json.dumps(pre_normalized, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        _record_artifact_safe(
            snapshot.get("run_id"),
            "analytics",
            analytics_path,
            template_version=None,
        )

        # Excel uses cumulative reviews when available, with window ID marking
        if snapshot.get("cumulative"):
            _excel_products = snapshot["cumulative"]["products"]
            _excel_reviews = snapshot["cumulative"]["reviews"]
        else:
            _excel_products = snapshot["products"]
            _excel_reviews = snapshot["reviews"]
        excel_path = report.generate_excel(
            _excel_products,
            _excel_reviews,
            report_date=report_date,
            output_path=output_path,
            analytics=analytics,
        )
        _record_artifact_safe(
            snapshot.get("run_id"),
            "xlsx",
            excel_path,
            template_version="f011-4sheets-v1",
        )

        # V3 HTML report (replaces V2 PDF + HTML pipeline)
        html_path = report_html.render_v3_html(snapshot, analytics, output_path=html_output_path)
        _record_artifact_safe(
            snapshot.get("run_id"),
            "html_attachment",
            html_path,
            template_version="f011-v3.0",
        )
    except Exception as exc:
        if isinstance(exc, FullReportGenerationError):
            raise
        raise FullReportGenerationError(
            str(exc),
            analytics_path=_artifact_db_value(analytics_path) if os.path.isfile(analytics_path) else None,
            excel_path=_artifact_db_value(excel_path) if excel_path and os.path.isfile(excel_path) else None,
            pdf_path=None,
        ) from exc

    email_result = None
    if send_email:
        subject, body = report.build_daily_deep_report_email(snapshot, analytics)
        # Render email_full.html.j2 (replaces legacy daily_report_email.html.j2)
        # F011 Critical A-2: email_full.html.j2 reads kpis.health_index /
        # own_negative_review_rate_display etc., which are written by
        # normalize_deep_report_analytics. The raw `analytics` object lacks
        # these fields and the template falls back to ⚪ "无数据" for all 4
        # KPI lights. `pre_normalized` is the normalized copy and already
        # carries the post-normalize mutations (report_copy / window_review_ids /
        # cluster deep_analysis) via _merge_post_normalize_mutations(), so it
        # is safe and intentional to render the email body from it.
        try:
            body_html = report.render_email_full(snapshot, pre_normalized)
        except Exception:
            _logger.warning("email_full.html.j2 render failed, falling back to legacy", exc_info=True)
            body_html = report.render_daily_email_html(snapshot, analytics)

        # F011 §5.1 — persist the email body to disk so it can be tracked in
        # report_artifacts.  Failure here is non-fatal: we still send the email.
        try:
            email_body_path = os.path.join(
                config.REPORT_DIR,
                f"workflow-run-{snapshot['run_id']}-email-body.html",
            )
            Path(email_body_path).write_text(body_html or "", encoding="utf-8")
            _record_artifact_safe(
                snapshot.get("run_id"),
                "email_body",
                email_body_path,
                template_version="f011-v3.0",
            )
        except Exception:
            _logger.warning("email_body artifact persist failed", exc_info=True)

        try:
            email_result = report.send_email(
                recipients=get_email_recipients(),
                subject=subject,
                body_text=body,
                body_html=body_html,
                attachment_paths=[excel_path, html_path],
            )
        except Exception as exc:
            email_result = {"success": False, "error": str(exc), "recipients": 0}

    return {
        "run_id": snapshot["run_id"],
        "snapshot_hash": snapshot["snapshot_hash"],
        "products_count": snapshot["products_count"],
        "reviews_count": snapshot["reviews_count"],
        "translated_count": snapshot["translated_count"],
        "untranslated_count": snapshot["untranslated_count"],
        "excel_path": _artifact_db_value(excel_path),
        "analytics_path": _artifact_db_value(analytics_path),
        "pdf_path": pdf_path,  # always None in V3
        "html_path": _artifact_db_value(html_path),
        "email": email_result,
    }
