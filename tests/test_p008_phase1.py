"""P008 Phase 1 — safety_incidents, busy_timeout, label_anomaly_flags, three-tier safety."""

from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest

from qbu_crawler import config, models


def _get_test_conn(db_file: str):
    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture()
def db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "p008.db")
    monkeypatch.setattr(config, "DB_PATH", db_file)
    monkeypatch.setattr(models, "get_conn", lambda: _get_test_conn(db_file))
    models.init_db()
    return db_file


# ── busy_timeout ──────────────────────────────────────────────


def test_busy_timeout_is_set(tmp_path, monkeypatch):
    """get_conn() must set PRAGMA busy_timeout >= 5000."""
    db_file = str(tmp_path / "timeout.db")
    monkeypatch.setattr(config, "DB_PATH", db_file)
    # Call the REAL get_conn (not the monkeypatched one used by the db fixture)
    conn = models.get_conn()
    row = conn.execute("PRAGMA busy_timeout").fetchone()
    assert row[0] >= 5000, f"busy_timeout too low: {row[0]}"
    conn.close()


# ── safety_incidents table ────────────────────────────────────


def test_safety_incidents_table_exists(db):
    """init_db() must create the safety_incidents table."""
    conn = sqlite3.connect(db)
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "safety_incidents" in tables
    conn.close()


def test_safety_incidents_columns(db):
    """safety_incidents must have all expected columns."""
    conn = sqlite3.connect(db)
    info = conn.execute("PRAGMA table_info(safety_incidents)").fetchall()
    columns = {r[1] for r in info}
    expected = {
        "id",
        "review_id",
        "product_sku",
        "safety_level",
        "failure_mode",
        "evidence_snapshot",
        "evidence_hash",
        "detected_at",
        "created_at",
    }
    assert expected.issubset(columns), f"Missing columns: {expected - columns}"
    conn.close()


# ── label_anomaly_flags column ────────────────────────────────


def test_review_analysis_has_label_anomaly_flags(db):
    """review_analysis must include the label_anomaly_flags column."""
    conn = sqlite3.connect(db)
    info = conn.execute("PRAGMA table_info(review_analysis)").fetchall()
    columns = {r[1] for r in info}
    assert "label_anomaly_flags" in columns
    conn.close()


# ── Three-tier safety grading (Task 2) ──────────────────────────


def test_load_safety_tiers_from_json(tmp_path):
    cfg = {"critical": ["metal shaving"], "high": ["rust"], "moderate": ["loose screw"]}
    path = tmp_path / "tiers.json"
    path.write_text(json.dumps(cfg))
    from qbu_crawler.server.report_common import load_safety_tiers
    tiers = load_safety_tiers(str(path))
    assert tiers["critical"] == ["metal shaving"]
    assert tiers["high"] == ["rust"]


def test_load_safety_tiers_fallback():
    """Non-existent path falls back to built-in defaults."""
    from qbu_crawler.server.report_common import load_safety_tiers
    tiers = load_safety_tiers("/nonexistent/path.json")
    assert "critical" in tiers
    assert len(tiers["critical"]) > 0


def test_detect_safety_level_critical():
    from qbu_crawler.server.report_common import detect_safety_level
    assert detect_safety_level("Found metal shaving in my ground beef") == "critical"


def test_detect_safety_level_high():
    from qbu_crawler.server.report_common import detect_safety_level
    assert detect_safety_level("The blade is rusty after 2 months") == "high"


def test_detect_safety_level_moderate():
    from qbu_crawler.server.report_common import detect_safety_level
    assert detect_safety_level("Motor housing is misaligned with the body") == "moderate"


def test_detect_safety_level_none():
    from qbu_crawler.server.report_common import detect_safety_level
    assert detect_safety_level("Great product, works perfectly") is None


def test_detect_safety_level_returns_highest():
    """When multiple tiers match, return the highest."""
    from qbu_crawler.server.report_common import detect_safety_level
    assert detect_safety_level("Rusty blade caused injury to my hand") == "critical"


# ── impact_category / failure_mode pipeline (Task 3) ────────────


def _seed_product_review_analysis(db_file):
    """Insert a product + review + analysis with impact_category/failure_mode."""
    conn = _get_test_conn(db_file)
    conn.execute(
        "INSERT INTO products (url, name, sku, site) VALUES (?, ?, ?, ?)",
        ("http://test.com/p1", "Test Product", "SKU001", "test"),
    )
    conn.execute(
        "INSERT INTO reviews (product_id, author, headline, body, rating)"
        " VALUES (?, ?, ?, ?, ?)",
        (1, "Tester", "Title", "Body text", 4.0),
    )
    conn.execute(
        """INSERT INTO review_analysis
           (review_id, sentiment, sentiment_score, labels, features,
            insight_cn, insight_en, impact_category, failure_mode, llm_model, prompt_version)
           VALUES (1, 'negative', 0.2, '[]', '[]', '', '',
                   'safety', 'rust_corrosion', 'test', 'v1')"""
    )
    conn.commit()
    conn.close()


def test_query_cumulative_data_includes_impact_category(db):
    from qbu_crawler.server import report
    _seed_product_review_analysis(db)
    products, reviews = report.query_cumulative_data()
    assert len(reviews) >= 1
    assert reviews[0]["impact_category"] == "safety"
    assert reviews[0]["failure_mode"] == "rust_corrosion"


def test_get_reviews_with_analysis_includes_impact_fields(db):
    _seed_product_review_analysis(db)
    reviews = models.get_reviews_with_analysis([1])
    assert len(reviews) == 1
    assert reviews[0]["impact_category"] == "safety"
    assert reviews[0]["failure_mode"] == "rust_corrosion"


def test_freeze_snapshot_enriches_impact_fields(db):
    """freeze enrichment must copy impact_category/failure_mode into snapshot reviews."""
    _seed_product_review_analysis(db)
    enriched = models.get_reviews_with_analysis([1])
    # Simulate the enrichment loop from report_snapshot.py
    review = {"id": 1, "product_id": 1}
    ea = enriched[0]
    for _key in ("sentiment", "analysis_features", "analysis_labels",
                 "analysis_insight_cn", "analysis_insight_en",
                 "impact_category", "failure_mode"):
        _val = ea.get(_key)
        if _val is not None:
            review.setdefault(_key, _val)
    assert review["impact_category"] == "safety"
    assert review["failure_mode"] == "rust_corrosion"


# ── Cumulative KPI always computed (Task 4) ──────────────────────


def test_quiet_template_no_na_with_cumulative_kpis():
    """quiet_day_report template must use cumulative_kpis instead of N/A."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    from pathlib import Path

    template_dir = Path(__file__).resolve().parent.parent / "qbu_crawler" / "server" / "report_templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "j2"]),
    )
    template = env.get_template("quiet_day_report.html.j2")

    css_path = template_dir / "daily_report_v3.css"
    css_text = css_path.read_text(encoding="utf-8") if css_path.exists() else ""

    # Provide cumulative_kpis but empty previous_analytics
    html = template.render(
        logical_date="2026-04-15",
        snapshot={"logical_date": "2026-04-15", "products": [], "reviews": []},
        previous_analytics=None,
        cumulative_kpis={
            "health_index": 72.5,
            "health_confidence": "medium",
            "own_review_rows": 42,
            "own_negative_review_rate_display": "12.0%",
            "high_risk_count": 1,
        },
        translate_stats={},
        last_full_report_path=None,
        css_text=css_text,
        threshold=2,
        changes=None,
    )
    assert "N/A" not in html, "Template should not contain N/A when cumulative_kpis provided"
    assert "72.5" in html, "Health index from cumulative_kpis must appear"


# ── V3 HTML Tab 2 + Panorama (Task 5) ───────────────────────────


def test_v3_html_tab2_not_placeholder():
    """Tab 2 must not contain placeholder text."""
    from pathlib import Path
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    template_dir = Path(__file__).resolve().parent.parent / "qbu_crawler" / "server" / "report_templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "j2"]),
    )
    template = env.get_template("daily_report_v3.html.j2")

    css_path = template_dir / "daily_report_v3.css"
    js_path = template_dir / "daily_report_v3.js"

    snapshot = {
        "logical_date": "2026-04-15",
        "reviews": [{"id": 1, "rating": 5.0, "ownership": "own", "product_sku": "SKU1",
                      "product_name": "Test", "headline": "Good", "body": "Works",
                      "author": "Tester", "date_published": "2026-04-15"}],
        "cumulative": {
            "products": [{"name": "Test", "sku": "SKU1", "ownership": "own", "rating": 4.5,
                          "review_count": 10, "site": "test", "price": 100}],
            "reviews": [{"id": 1, "rating": 5.0, "ownership": "own", "product_sku": "SKU1",
                          "product_name": "Test", "headline": "Good", "body": "Works",
                          "author": "Tester", "date_published": "2026-04-15"}],
        },
    }
    analytics = {
        "mode": "incremental",
        "kpis": {"own_review_rows": 1, "ingested_review_rows": 1, "product_count": 1,
                 "own_product_count": 1, "competitor_product_count": 0,
                 "competitor_review_rows": 0, "own_negative_review_rows": 0,
                 "own_positive_review_rows": 1},
        "self": {"risk_products": [], "top_negative_clusters": [], "recommendations": [],
                 "top_positive_clusters": []},
        "competitor": {"top_positive_themes": [], "benchmark_examples": [],
                       "negative_opportunities": []},
        "appendix": {"image_reviews": []},
    }

    html = template.render(
        logical_date="2026-04-15",
        mode="incremental",
        snapshot=snapshot,
        analytics=analytics,
        charts={"heatmap": None, "sentiment_own": None, "sentiment_comp": None},
        alert_level="green",
        alert_text="",
        report_copy={},
        css_text=css_path.read_text(encoding="utf-8") if css_path.exists() else "",
        js_text=js_path.read_text(encoding="utf-8") if js_path.exists() else "",
        threshold=2,
        cumulative_kpis={},
        window={},
    )
    assert "变化追踪将在后续版本中启用" not in html, "Placeholder text must be gone"


# ── Snapshot _meta version stamp (Task 7) ────────────────────────


def test_inject_meta_adds_version_fields():
    """_inject_meta must add schema_version, generator_version, taxonomy_version."""
    from qbu_crawler.server.report_snapshot import _inject_meta
    snapshot = {"logical_date": "2026-04-16", "products": [], "reviews": []}
    enriched = _inject_meta(snapshot)
    assert "_meta" in enriched
    assert enriched["_meta"]["schema_version"] == "3"
    assert "generator_version" in enriched["_meta"]
    assert enriched["_meta"]["taxonomy_version"] == "v1"


# ── Label consistency + safety evidence (Task 8) ─────────────────


def test_label_consistency_detects_mismatch():
    """Flag when negative label has high sentiment_score."""
    from qbu_crawler.server.report_common import check_label_consistency
    labels = [{"code": "quality_stability", "polarity": "negative", "confidence": 0.9}]
    anomalies = check_label_consistency(sentiment_score=0.85, labels=labels)
    assert len(anomalies) == 1
    assert anomalies[0]["type"] == "sentiment_label_mismatch"


def test_label_consistency_no_false_positive():
    """No flag when negative label has low sentiment_score (consistent)."""
    from qbu_crawler.server.report_common import check_label_consistency
    labels = [{"code": "quality_stability", "polarity": "negative", "confidence": 0.9}]
    anomalies = check_label_consistency(sentiment_score=0.2, labels=labels)
    assert len(anomalies) == 0


def test_save_safety_incident(db):
    """Safety incidents are stored with frozen evidence and SHA-256 hash."""
    # Need a review for FK constraint
    conn = _get_test_conn(db)
    conn.execute("INSERT INTO products (url, name, sku, site) VALUES (?, ?, ?, ?)",
                 ("http://test.com/p1", "Grinder", "SKU001", "test"))
    conn.execute("INSERT INTO reviews (product_id, author, headline, body, rating)"
                 " VALUES (1, 'A', 'H', 'B', 1.0)")
    conn.commit()
    conn.close()

    evidence = {"review_text": "metal shavings in food", "product": "Grinder #22"}
    evidence_json = json.dumps(evidence, sort_keys=True)
    evidence_hash = hashlib.sha256(evidence_json.encode()).hexdigest()

    models.save_safety_incident(
        review_id=1, product_sku="SKU001", safety_level="critical",
        failure_mode="metal_contamination",
        evidence_snapshot=evidence_json, evidence_hash=evidence_hash,
    )

    conn = _get_test_conn(db)
    rows = conn.execute("SELECT * FROM safety_incidents WHERE review_id = 1").fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0]["safety_level"] == "critical"
    assert rows[0]["evidence_hash"] == evidence_hash


def test_update_review_analysis_flags(db):
    """update_review_analysis_flags must store anomaly flags."""
    conn = _get_test_conn(db)
    conn.execute(
        "INSERT INTO products (url, name, sku, site) VALUES (?, ?, ?, ?)",
        ("http://test.com/p1", "Test", "SKU001", "test"),
    )
    conn.execute(
        "INSERT INTO reviews (product_id, author, headline, body, rating)"
        " VALUES (1, 'A', 'H', 'B', 3.0)",
    )
    conn.execute(
        """INSERT INTO review_analysis
           (review_id, sentiment, sentiment_score, labels, features,
            insight_cn, insight_en, llm_model, prompt_version)
           VALUES (1, 'negative', 0.2, '[]', '[]', '', '', 'test', 'v1')"""
    )
    conn.commit()
    conn.close()

    flags = json.dumps([{"type": "sentiment_label_mismatch"}])
    models.update_review_analysis_flags(1, flags)

    conn = _get_test_conn(db)
    row = conn.execute(
        "SELECT label_anomaly_flags FROM review_analysis WHERE review_id = 1"
    ).fetchone()
    conn.close()
    assert row["label_anomaly_flags"] == flags


# ── Integration test (Task 9) ────────────────────────────────────


def test_p008_phase1_integration(db):
    """End-to-end: a safety review goes through the full pipeline correctly."""
    # 1. Insert a product
    conn = _get_test_conn(db)
    conn.execute(
        "INSERT INTO products (url, name, sku, site, ownership)"
        " VALUES (?, ?, ?, ?, ?)",
        ("http://test.com/p1", "1HP Grinder #22", "1159179", "meatyourmaker", "own"),
    )

    # 2. Insert a safety-relevant review
    conn.execute(
        """INSERT INTO reviews (product_id, author, headline, body, rating)
           VALUES (1, 'TestUser', 'Dangerous metal debris',
           'Found metal shaving in my ground beef after using this grinder', 1.0)""",
    )

    # 3. Insert analysis with impact_category = safety
    conn.execute(
        """INSERT INTO review_analysis
           (review_id, sentiment, sentiment_score, labels, features,
            insight_cn, insight_en, impact_category, failure_mode, llm_model, prompt_version)
           VALUES (1, 'negative', 0.05,
           '[{"code":"quality_stability","polarity":"negative","severity":"critical","confidence":0.95}]',
           '["metal debris in food"]', '食品中发现金属碎屑', 'Metal debris found in food',
           'safety', 'metal_contamination', 'test', 'v1')"""
    )
    conn.commit()
    conn.close()

    # 4. Verify impact_category in cumulative query
    from qbu_crawler.server.report import query_cumulative_data
    products, reviews = query_cumulative_data()
    assert reviews[0]["impact_category"] == "safety"

    # 5. Verify safety detection
    from qbu_crawler.server.report_common import detect_safety_level
    level = detect_safety_level("Found metal shaving in my ground beef")
    assert level == "critical"

    # 6. Verify safety_incidents table can be written
    evidence = json.dumps({"text": "metal shaving"}, sort_keys=True)
    models.save_safety_incident(
        review_id=1, product_sku="1159179", safety_level="critical",
        failure_mode="metal_contamination",
        evidence_snapshot=evidence,
        evidence_hash=hashlib.sha256(evidence.encode()).hexdigest(),
    )

    conn = _get_test_conn(db)
    incidents = conn.execute("SELECT * FROM safety_incidents").fetchall()
    conn.close()
    assert len(incidents) == 1
    assert incidents[0]["safety_level"] == "critical"

    # 7. Verify label consistency check
    from qbu_crawler.server.report_common import check_label_consistency
    labels = [{"code": "quality_stability", "polarity": "negative", "confidence": 0.95}]
    anomalies = check_label_consistency(sentiment_score=0.05, labels=labels)
    assert len(anomalies) == 0  # consistent: negative label + low score

    # 8. Verify _inject_meta
    from qbu_crawler.server.report_snapshot import _inject_meta
    snapshot = {"logical_date": "2026-04-16"}
    enriched = _inject_meta(snapshot)
    assert enriched["_meta"]["schema_version"] == "3"
