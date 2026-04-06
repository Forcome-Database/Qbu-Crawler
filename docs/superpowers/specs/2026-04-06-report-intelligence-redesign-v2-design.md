# Report Intelligence Redesign V2 — Design Spec

> **Date**: 2026-04-06
> **Status**: Reviewed (approved with minor issues, all critical fixes applied)
> **Branch**: feature/report-redesign-v2
> **Replaces**: 2026-04-06-report-redesign-design.md (visual-only redesign)

## 1. Problem Statement

The current report system (2,705 lines across 6 modules) has completed three iterations (initial Excel → D012 review fixes → D013 visual redesign) but suffers from fundamental data quality and analytical depth issues that limit its value for product optimization:

1. **LLM underutilization**: LLM is only used for translation. Classification relies on keyword matching (`report_analytics.py:29-227`) with only 44.5% review coverage. Recommendations are hardcoded in `_RECOMMENDATION_MAP` (14 static entries).
2. **No trend analysis**: `product_snapshots` table exists but is never used in reports. KPI delta is partially implemented (model layer only, no frontend display).
3. **Superficial competitive analysis**: Only shows competitor positive themes. No cross-dimensional gap analysis, no competitor weakness exploitation, no competitive radar.
4. **Reports lack actionability**: Issue labels are abstract ("quality_stability") instead of specific ("handle loosens after 3 months"). R&D cannot act on abstract labels.
5. **Excel is a raw data dump**: 2 sheets (products, reviews), no summary, no conditional formatting, no analysis.
6. **Single audience architecture**: Same content for executives and R&D, differing only in format (email vs PDF).

## 2. Goals

- **G1**: Achieve 95%+ review analysis coverage by piggybacking structured LLM analysis on the existing translation pipeline (near-zero marginal cost).
- **G2**: Generate reports with specific, actionable product insights (concrete features like "handle loosens" instead of abstract labels like "quality_stability").
- **G3**: Serve two distinct audiences: executives (email = decision dashboard) and R&D (PDF = diagnostic manual).
- **G4**: Support true full/incremental differentiation with trend analysis, delta indicators, and issue emergence/resolution tracking.
- **G5**: Professional, data-dense PDF with modern chart visualizations (Plotly replacing Matplotlib).
- **G6**: Analytical Excel workbook (6 sheets) with conditional formatting and summaries.
- **G7**: Configurable thresholds (negative review definition, health index ranges, risk score cutoffs).

## 3. Non-Goals

- Real-time dashboards or web UI (reports remain batch-generated artifacts)
- Replacing the existing scraper or translation worker architecture
- Multi-language reports (Chinese-only for now)
- Interactive PDF (static PDF remains the output)

## 4. Target Audiences

| Audience | Artifact | Decision Context | Time Budget |
|----------|----------|-----------------|-------------|
| **Executives / Business** | Email (HTML) | "Do I need to intervene?" | 30 seconds |
| **R&D / Product / QA** | PDF + Excel | "What's broken, where, and how to fix it?" | 5-15 minutes |

## 5. Architecture Overview

### 5.1 Two-Phase Delivery

```
Phase 1: Translation++ Pipeline (Data Layer Enhancement)
  ├─ Modify translator.py: translation + structured analysis in one LLM call
  ├─ New table: review_analysis (sentiment, labels, features, insight)
  └─ Report-level LLM call for executive summary + recommendations

Phase 2: Report Output Redesign
  ├─ PDF: 5-7 page diagnostic manual (Plotly charts, Jinja2, Playwright)
  ├─ Email: executive decision dashboard (HTML, 6 KPIs + 3 action items)
  └─ Excel: 6-sheet analytical workbook (openpyxl, conditional formatting)
```

### 5.2 Data Flow

```
Review ingested by scraper
       ↓
translator.py: _analyze_and_translate_batch()
  ├─ Input: headline + body + product_name + rating
  ├─ Single LLM call (structured JSON output)
  ├─ Output: translation + sentiment + labels + features + insight
  ├─ Write: reviews table (headline_cn, body_cn)
  └─ Write: review_analysis table (full structured analysis)
       ↓
Report generation triggered (MCP tool / workflow)
       ↓
report_analytics.py: build_report_analytics()
  ├─ Read: review_analysis (primary) / review_issue_labels (fallback)
  ├─ Aggregate: features frequency, sentiment by product×dimension
  ├─ Compute: KPIs, risk scores, gap analysis, health index
  └─ Output: analytics dict
       ↓
report_llm.py: generate_report_insights()
  ├─ Single LLM call with aggregated analytics
  └─ Output: executive_summary, hero_headline, improvement_priorities
       ↓
Three output renderers (parallel):
  ├─ report_pdf.py → PDF (Plotly charts + Jinja2 + Playwright)
  ├─ report.py → Excel (openpyxl, 6 sheets)
  └─ report.py → Email HTML (Jinja2 template)
```

## 6. Phase 1: Translation++ Pipeline

### 6.1 LLM Prompt Design

Each review batch (20 reviews) uses a single structured JSON prompt that produces translation + analysis:

```
You are a product quality analyst. Analyze the following product reviews and return structured JSON.

Product: {product_name}
Category: Meat processing equipment

Review:
  Title: {headline}
  Body: {body}
  Rating: {rating}/5

Return JSON:
{
  "headline_cn": "Chinese title translation",
  "body_cn": "Chinese body translation",
  "sentiment": "positive|negative|mixed|neutral",
  "sentiment_score": 0.0-1.0,
  "labels": [
    {"code": "from_taxonomy", "polarity": "negative|positive",
     "severity": "high|medium|low", "confidence": 0.0-1.0}
  ],
  "features": ["specific product features in Chinese, e.g. '手柄松动'"],
  "insight_cn": "One-line Chinese summary of the review's core message",
  "insight_en": "One-line English summary"
}

Label taxonomy (multi-select):
  Negative: quality_stability, structure_design, assembly_installation,
            material_finish, cleaning_maintenance, noise_power,
            packaging_shipping, service_fulfillment
  Positive: easy_to_use, solid_build, good_value, easy_to_clean,
            strong_performance, good_packaging
If the review mentions issues not covered by the taxonomy, describe them in features.
```

**Batch processing**: 20 reviews per prompt, output as JSON array. Maintains current `TRANSLATE_WORKERS=3` concurrency.

**Cost estimate**: ~28% more tokens per review vs translation-only. At 636 reviews × 350 tokens avg = ~222K tokens per full run (~$0.07 with gpt-4o-mini).

**Failure degradation**: If JSON parsing fails for a review, fall back to translation-only mode for that review. Translation must never be blocked by analysis failure.

### 6.2 New Table: review_analysis

```sql
CREATE TABLE review_analysis (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id       INTEGER NOT NULL REFERENCES reviews(id),
    sentiment       TEXT NOT NULL,       -- positive/negative/mixed/neutral
    sentiment_score REAL,                -- 0.0~1.0
    labels          TEXT NOT NULL,       -- JSON: [{code, polarity, severity, confidence}]
    features        TEXT NOT NULL,       -- JSON: ["手柄松动", "电机噪音大"]
    insight_cn      TEXT,                -- One-line Chinese insight
    insight_en      TEXT,                -- One-line English insight
    llm_model       TEXT,                -- Model used
    prompt_version  TEXT NOT NULL,       -- Prompt version for A/B testing
    token_usage     INTEGER,            -- Tokens consumed
    analyzed_at     TEXT NOT NULL,
    UNIQUE(review_id, prompt_version)
);
CREATE INDEX idx_ra_review ON review_analysis(review_id);
CREATE INDEX idx_ra_sentiment ON review_analysis(sentiment);
```

**Relationship with existing `review_issue_labels`**:
- `review_issue_labels` retained as rule-engine output (`source=rule`), backward compatible
- `review_analysis` is LLM output, richer data
- Report generation prefers `review_analysis`, falls back to `review_issue_labels` when missing

### 6.3 Translator Modification

Current: `_translate_batch()` → save `headline_cn`/`body_cn`
New: `_analyze_and_translate_batch()` → save translations + analysis

```python
# translator.py modification (pseudocode)
def _analyze_and_translate_batch(self, reviews: list[dict]) -> None:
    prompt = self._build_analysis_prompt(reviews)  # structured JSON prompt
    response = self._call_llm(prompt)

    for review, result in zip(reviews, response):
        # Always save translation (even if analysis parsing fails)
        self._save_translation(review["id"], result["headline_cn"], result["body_cn"])

        # Save analysis (with error handling)
        try:
            self._save_analysis(review["id"], result)
        except (KeyError, json.JSONDecodeError) as e:
            logger.warning("Analysis parse failed for review %s: %s", review["id"], e)
            # Translation still saved — analysis failure is non-blocking
```

### 6.4 Report-Level LLM Call

One additional LLM call at report generation time, using aggregated analytics data:

**Input**: KPIs, top issues with counts, gap analysis results, product risk scores
**Output**:
```json
{
  "executive_summary": "3-5 sentence executive summary in Chinese",
  "hero_headline": "One-line core conclusion",
  "risk_assessment": "Current biggest risk and recommended action",
  "improvement_priorities": [
    {"rank": 1, "target": "product_name", "issue": "specific feature",
     "action": "specific recommendation", "evidence_count": 12, "severity": "high"}
  ],
  "competitive_insight": "Key competitive takeaway"
}
```

This replaces the hardcoded `_RECOMMENDATION_MAP` and mechanical `_generate_hero_headline()`.

## 7. Configurable Thresholds

All report thresholds are configurable via `.env`, eliminating hardcoded magic numbers:

```env
# ── Report Thresholds ──
REPORT_NEGATIVE_THRESHOLD=2          # Reviews rated ≤ this are "negative" (default: 2)
REPORT_LOW_RATING_THRESHOLD=3        # Reviews rated ≤ this are "low rating" (default: 3)
REPORT_HEALTH_RED=60                 # Health index < this = red alert
REPORT_HEALTH_YELLOW=80              # Health index < this = yellow
REPORT_HIGH_RISK_THRESHOLD=8         # Risk score ≥ this = high risk product
```

All KPI calculations, LLM prompts, PDF templates, and Excel conditional formatting reference `config.NEGATIVE_THRESHOLD` etc. PDF footer auto-annotates: `"差评定义：≤ {threshold} 星"`.

## 8. KPI System

### 8.1 Three-Tier KPI Pyramid

```
Tier 1: Decision (email + PDF hero) — "Do I need to act?"
  6 KPIs for executives

Tier 2: Operational (PDF sections) — "What to fix and where?"
  Product-level + Issue-level metrics for R&D

Tier 3: Analytical (PDF deep dive + Excel) — "Why and how to fix?"
  Feature-level sentiment, trends, competitive positioning
```

### 8.2 Tier 1: Decision KPIs (6)

| # | KPI | Calculation | Baseline Mode | Incremental Mode |
|---|-----|-------------|---------------|------------------|
| 1 | **Product Health Index** | Weighted: avg_rating×40% + (1-negative_rate)×35% + (1-high_risk_ratio)×25%, scaled 0-100 | Absolute | Absolute + △ trend arrow |
| 2 | **Negative Review Count** | Reviews with rating ≤ `NEGATIVE_THRESHOLD` | Absolute | Absolute + △ vs previous |
| 3 | **Negative Review Rate** | Negative count / total × 100% | Percentage | Percentage + △ percentage points |
| 4 | **High-Risk Products** | Own products with risk_score ≥ `HIGH_RISK_THRESHOLD` | Absolute | Absolute + △ + new/resolved markers |
| 5 | **Competitive Gap Index** | Count of reviews where competitor praised AND own criticized on same dimension | Absolute | Absolute + △ |
| 6 | **New Reviews** | Reviews ingested in this period | Absolute | Absolute + △ |

### 8.3 Tier 2: Operational KPIs

**Per-product health card**:
- Risk score, negative rate, avg rating, rating trend (from snapshots)
- Top 3 specific issues (from `review_analysis.features` aggregation)
- Image evidence count, price positioning vs competitors

**Per-issue diagnostic card**:
- Specific feature description (e.g. "手柄松动" not "quality_stability")
- Affected review count, affected product count, severity distribution
- Timeline: first_seen → last_seen, duration annotation
- Representative quotes (bilingual, from `review_analysis.insight_cn`)
- Image evidence thumbnails inline
- LLM-generated specific recommendation

### 8.4 Tier 3: Analytical KPIs

- Feature×Product sentiment heatmap (red-green matrix)
- Review sentiment distribution (stacked bar: positive/mixed/negative/neutral)
- Review volume trend (line chart by day/week)
- Price-Rating quadrant chart (own vs competitor scatter)
- Issue emergence/resolution timeline
- Competitive radar chart (multi-dimensional comparison)

## 9. PDF Information Architecture

### 9.1 Design Principles

- **Data density first**: Every page has charts + data tables, no text filler
- **5-second rule**: Core conclusion of each section capturable in 5 seconds
- **Evidence accompanies conclusion**: Image evidence and quotes inline with issues
- **Same structure, different content**: Full/incremental modes share page structure but differ in content (deltas, trend arrows, new/resolved markers)
- **~5-7 pages**: 2× information density vs current, same page count

### 9.2 Page Structure

#### P1: Executive Dashboard (forced page break after)

- **Health Index** gauge (large number, 0-100, color-coded red/yellow/green)
- **6 KPI cards** with delta arrows (incremental) or absolute (baseline)
- **Alert signal** (red/yellow/green banner with one-line action item)
- **LLM hero headline** (1-2 sentences, data-driven core conclusion)
- **3 executive bullets** (LLM-generated, each pointing to specific product + action)
- **Report metadata** (mode, date range, threshold annotation)

#### P2: Product Health Matrix (flow layout)

- **Product health scorecard table**: All own products sorted by risk score
  - Columns: product, SKU, rating, negative rate, risk score, top issue (specific feature), trend arrow
  - Conditional formatting: red/yellow/green by risk level
- **Price-Rating quadrant chart** (Plotly scatter): Own (▲) vs Competitor (●), quadrant lines at median
- **Rating trend chart** (Plotly line, from `product_snapshots`): Shows multi-day trend when data available, single-point marker when only one day

#### P3: Issue Deep Dive (flow layout)

Issue cards sorted by impact (affected review count × severity):
- **Specific feature description** as heading (e.g. "手柄松动/脱落")
- **Impact metrics**: affected reviews, affected products, severity badge
- **Timeline**: first_seen → last_seen, duration annotation ("持续 2 年未解决")
- **Representative quotes**: 2-3 most representative, bilingual (from `review_analysis.insight_cn` + original), with rating and author
- **Image evidence**: Thumbnails inline (100×80px), up to 3 per issue
- **LLM recommendation**: Specific, actionable, based on actual review content (replaces hardcoded `_RECOMMENDATION_MAP`)

#### P4: Competitive Intelligence (flow layout)

- **Gap analysis matrix table**: Dimension × (competitor positive count, own negative count, gap, action priority)
- **LLM competitive insight**: Narrative paragraph with specific product/feature references
- **Competitive radar chart** (Plotly scatterpolar): Multi-dimensional comparison (6-8 axes)
- **Competitor weakness / our opportunity**: Dimensions where competitors are criticized but we are not

#### P5: Feature Sentiment Panorama (conditional, needs ≥3 products + ≥50 analyzed reviews)

- **Feature×Product sentiment heatmap** (Plotly heatmap): Red-green color scale, -1.0 to 1.0
- **Review sentiment distribution** (Plotly stacked bar): By product
- **Review volume trend** (Plotly line): By date_published

### 9.3 Visual Design

- **Retain warm tone palette**: `--paper: #f5f0e8`, `--accent: #93543f`, `--green: #345f57`
- **Shift to dashboard density**: Tighter spacing (padding 12-14px), higher chart ratio (~60%)
- **Tables as primary data carrier**: Replace loose card stacks with structured tables
- **Consistent color semantics**: Red=risk/negative, Green=healthy/positive, Yellow=attention, Gray=neutral
- **CSS design tokens**: Centralize all spacing, colors, typography into CSS custom properties

## 10. Email Information Architecture

### 10.1 Design: Executive Decision Dashboard

The email is an **independent decision tool**, not a PDF summary. Designed for 30-second consumption.

Structure (6 decision metrics total = 1 Health Index hero + 5 KPI cards):
1. **Health Index** (large standalone number with color-coded background, separate from KPI cards)
2. **Alert signal** (one-line: "⚠ 黄色预警：差评率上升 1.2 个百分点")
3. **5 KPI cards** (inline table: new reviews, negative count, negative rate, high-risk products, competitive gap — each with value + delta)
4. **3 action items** (LLM-generated, each naming a specific product + issue + recommended action)
5. **Attachment guide** ("📄 PDF = R&D deep dive, 📊 Excel = filterable raw data")
6. **Footer** (threshold annotation, internal-only disclaimer)

Note: "Product count" from Tier 1 KPI #1 is folded into the Health Index display area (as metadata), not a separate card. This keeps the KPI cards focused on actionable metrics.

### 10.2 Full vs Incremental Differentiation

| Element | Baseline | Incremental |
|---------|----------|-------------|
| Subject | 【产品评论基线建档】YYYY-MM-DD | [alert prefix] 【产品评论深度日报】YYYY-MM-DD |
| KPI cards | Absolute values only | Values + delta arrows |
| Action items | "Current landscape" focus | "What changed" focus |
| Health Index | Labeled "基线" | Shows △ vs previous |

## 11. Excel Information Architecture

### 11.1 Six-Sheet Analytical Workbook

| Sheet | Content | Audience |
|-------|---------|----------|
| **Executive Summary** | KPI table (with previous/delta), LLM executive summary, improvement priorities | Executives |
| **Product Scorecard** | All products sorted by risk, conditional formatting, specific top issues | R&D leads |
| **Issue Analysis** | Issues sorted by impact, severity coloring, representative quotes, timeline | R&D engineers |
| **Competitive Benchmark** | Dimension×score matrix, gap coloring, opportunity identification | Product/Strategy |
| **Review Details** | Enhanced raw data: original + translation + sentiment + features + insight | Operations/QA |
| **Trend Data** | Daily snapshots for sparklines and pivot tables (hidden when single-day) | Analysts |

### 11.2 Conditional Formatting Rules

- Negative rate > 30%: red background
- Negative rate 15-30%: yellow background
- Negative rate < 15%: green background
- Severity high: red text
- Sentiment score < -0.3: red, > 0.3: green
- Delta positive (bad direction): red arrow, Delta positive (good direction): green arrow

## 12. Technology Stack

### 12.1 Changes

| Component | Current | New | Reason |
|-----------|---------|-----|--------|
| **Charts** | Matplotlib | **Plotly ≥5.20.0** | 10/10 chart type coverage (gauge, heatmap, radar, timeline), modern visuals, ~27MB |
| **Chart rendering** | Matplotlib SVG → embed | **Plotly HTML fragments → Playwright renders all** | Zero extra dependency (no Kaleido), enables interactive HTML preview |
| **Labels** | Rule-based keyword matching | **LLM structured analysis** (piggybacked on translation) | 44.5% → 95%+ coverage, semantic understanding |
| **Recommendations** | Hardcoded `_RECOMMENDATION_MAP` | **LLM-generated per report** | Specific, actionable, based on actual review content |
| **Excel** | 2-sheet raw dump | **6-sheet analytical workbook** | Decision-ready for all audiences |

### 12.2 Retained

- **Jinja2**: HTML template engine (retained, templates redesigned)
- **Playwright**: PDF rendering (retained, already a dependency)
- **openpyxl**: Excel generation (retained, enhanced usage)
- **Snapshot architecture**: Freeze-then-render (retained, proven pattern)
- **SMTP email**: Retained, HTML template redesigned

### 12.3 Dependency Changes

```toml
# pyproject.toml
dependencies = [
    # ADD
    "plotly>=5.20.0",
    # REMOVE
    # "matplotlib>=3.9.0",  (removed)
]
```

Net dependency size change: approximately -3MB (matplotlib ~30MB removed, plotly ~27MB added).

### 12.4 Plotly Integration Strategy

Plotly charts are rendered as HTML `<div>` fragments with inline `plotly.js`, embedded into the Jinja2 template. Playwright renders the complete page (text + charts) to PDF in one pass.

Benefits:
- No separate chart rendering step (Kaleido not needed)
- Interactive HTML preview for free (`write_report_html_preview()` already exists)
- Single rendering engine (Playwright Chromium)

Implementation:
```python
# report_charts.py (new file) - replaces Matplotlib charts in report_pdf.py
import plotly.graph_objects as go
import plotly.io as pio

def build_chart_html_fragments(analytics: dict) -> dict[str, str]:
    """Return dict of chart_name → HTML fragment string."""
    charts = {}
    charts["health_gauge"] = _build_health_gauge(analytics["kpis"]["health_index"])
    charts["price_rating_quadrant"] = _build_quadrant(analytics)
    charts["feature_heatmap"] = _build_heatmap(analytics)
    charts["competitive_radar"] = _build_radar(analytics)
    # ... etc
    return charts

def _build_health_gauge(value: float) -> str:
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=value,
        gauge={"axis": {"range": [0, 100]},
               "steps": [
                   {"range": [0, 60], "color": "#93543f"},
                   {"range": [60, 80], "color": "#b0823a"},
                   {"range": [80, 100], "color": "#345f57"}
               ]},
    ))
    fig.update_layout(height=200, margin=dict(t=0,b=0,l=20,r=20))
    return pio.to_html(fig, full_html=False, include_plotlyjs=False)
```

**Plotly.js loading strategy**:
- **PDF path**: Use `include_plotlyjs=False` per fragment. The main Jinja2 template includes `plotly.min.js` once via a `<script>` tag (inlined into HTML, ~3.5MB). Playwright renders everything offline — no CDN needed.
- **HTML preview path**: Use `include_plotlyjs="cdn"` for lightweight preview files.
- **Impact**: PDF HTML size increases by ~3.5MB (plotly.js inline), but final PDF size is unaffected (JS is not part of PDF output).

## 13. Full vs Incremental Mode

### 13.1 Mode Detection

Current `detect_report_mode()` logic retained: ≥3 completed historical runs = incremental, otherwise baseline.

### 13.2 Content Differentiation

| Dimension | Baseline | Incremental |
|-----------|----------|-------------|
| **KPI display** | Absolute values + "基线" label | Absolute + △ delta + trend arrows |
| **Hero headline** | LLM generates landscape summary | LLM generates change summary ("较上期...首次出现...") |
| **Issue clusters** | Full Top N display | Highlight **new** issues, mark **resolved** issues |
| **Competitive** | Full benchmark matrix | Focus on **gap changes** (widening/narrowing) |
| **Recommendations** | LLM generates long-term optimization roadmap | LLM generates immediate action items |
| **Excel Trend sheet** | Labeled "首次建档", single-day data | Full historical data, sparkline-ready |

### 13.3 Delta Computation

```python
# Using existing models.get_previous_completed_run()
previous_run = models.get_previous_completed_run(current_run_id)
if previous_run and previous_run.analytics_path:
    prev_analytics = load_analytics(previous_run.analytics_path)
    deltas = compute_kpi_deltas(current_analytics, prev_analytics)
```

Delta fields added to KPI dict:
- `{kpi}_delta`: numeric change
- `{kpi}_delta_display`: formatted string ("+5 ↑" / "-3 ↓" / "—")
- `{kpi}_direction`: "up" / "down" / "flat"

## 14. File Impact Analysis

### 14.1 New Files

| File | Purpose |
|------|---------|
| `qbu_crawler/server/report_charts.py` | Plotly chart builders (replaces Matplotlib in report_pdf.py) |

### 14.2 Modified Files

| File | Changes |
|------|---------|
| `qbu_crawler/server/translator.py` | `_translate_batch()` → `_analyze_and_translate_batch()`, structured JSON prompt |
| `qbu_crawler/models.py` | Add `review_analysis` table DDL + CRUD functions |
| `qbu_crawler/server/report_analytics.py` | Use `review_analysis` data, new aggregation logic (features frequency, sentiment by dimension) |
| `qbu_crawler/server/report_common.py` | Health index calculation, configurable thresholds, updated normalization |
| `qbu_crawler/server/report_llm.py` | **Replace** existing `run_llm_report_analysis()` / `validate_findings()` / `merge_final_analytics()` with new `generate_report_insights()` function. The old candidate-pool + classification workflow is superseded by `review_analysis` table data. Existing functions can be removed once Phase 1 data is available. |
| `qbu_crawler/server/report_pdf.py` | Replace Matplotlib with Plotly imports, redesigned `build_chart_assets()`, updated template rendering |
| `qbu_crawler/server/report.py` | Enhanced `generate_excel()` (6 sheets), updated email rendering |
| `qbu_crawler/server/report_snapshot.py` | Wire new analytics and chart pipeline |
| `qbu_crawler/config.py` | Add `NEGATIVE_THRESHOLD`, `LOW_RATING_THRESHOLD`, `HEALTH_RED`, `HEALTH_YELLOW`, `HIGH_RISK_THRESHOLD` |
| `qbu_crawler/server/report_templates/daily_report.html.j2` | Complete redesign (5 sections, Plotly chart fragments) |
| `qbu_crawler/server/report_templates/daily_report.css` | Dashboard-density layout, design tokens |
| `qbu_crawler/server/report_templates/daily_report_email.html.j2` | Decision dashboard layout, 6 KPIs, health index |
| `qbu_crawler/server/report_templates/daily_report_email_body.txt.j2` | Updated plain text version |
| `pyproject.toml` | Add `plotly>=5.20.0`, remove `matplotlib>=3.9.0` |

### 14.3 Test Impact

All existing test files need updates to reflect:
- New `review_analysis` table and data
- Changed analytics structure (features-based instead of label-only)
- New chart types (Plotly instead of Matplotlib)
- 6-sheet Excel structure
- New KPIs (health index, competitive gap)
- Configurable thresholds

## 15. Migration Strategy

### 15.1 Schema Migration

The new `review_analysis` table DDL is added to `models.init_db()` using `CREATE TABLE IF NOT EXISTS`, following the established pattern in `models.py`. No formal migration framework needed — SQLite handles this idempotently.

### 15.2 Backward Compatibility

- `review_issue_labels` table retained — rule engine continues to run
- `report_analytics.py` uses `review_analysis` when available, falls back to `review_issue_labels`
- Existing MCP tool signatures (`generate_report`, `send_filtered_report`) unchanged
- Existing workflow state machine unchanged

### 15.3 Data Migration

For existing reviews without `review_analysis` data:
- **Option A**: Run a one-time backfill CLI command (`qbu-crawler backfill-analysis`) that re-processes all existing reviews through the new analysis prompt. At 636 reviews, this takes ~2 minutes and costs ~$0.05.
- **Option B**: Generate reports using `review_issue_labels` fallback until new reviews accumulate naturally.
- Recommendation: Option A for production, Option B for development/testing.

## 16. Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Review analysis coverage | 44.5% (rule labels) | 95%+ (LLM analysis) |
| Issue description specificity | Abstract labels (14 categories) | Concrete features (unlimited) |
| Report pages | ~5 pages | ~5-7 pages (2× information density) |
| Chart types | 4 (bar×3, scatter×1) | 10 (gauge, heatmap, radar, quadrant, sparkline, stacked bar, line, timeline, bar, scatter) |
| Excel sheets | 2 (raw dump) | 6 (analytical) |
| Email KPIs | 4 | 6 + health index |
| Recommendation quality | Static map (14 entries) | LLM-generated, review-specific |
| Delta support | Partial (model only) | Full (all KPIs, all outputs) |
| Threshold configurability | Hardcoded | All thresholds via .env |

## 17. Review Resolutions

Spec review performed 2026-04-06. Verdict: Approved with minor issues. Resolutions below.

### Critical fixes (applied in-place above)

- **C1**: Email KPI count clarified — 1 Health Index hero + 5 KPI cards = 6 total decision metrics. Section 10.1 updated.
- **C2**: `report_llm.py` role clarified — existing `run_llm_report_analysis()` / `validate_findings()` / `merge_final_analytics()` are **replaced** by new `generate_report_insights()`. The old candidate-pool workflow is superseded by `review_analysis` table. Section 14.2 updated.
- **C3**: Schema migration clarified — `review_analysis` DDL added to `init_db()` with `CREATE TABLE IF NOT EXISTS`. Section 15.1 added.

### Important clarifications

- **I1 (Plotly bundling)**: Use `include_plotlyjs=False` per fragment + inline `plotly.min.js` once in template for PDF. Use CDN for HTML preview. Section 12.4 updated.
- **I2 (Batch prompt)**: `get_pending_translations()` must be modified to JOIN `products` table and return `product_name` per review. Batch prompt includes per-review product context. To be detailed in implementation plan.
- **I3 (Cost estimate)**: The 28% figure is a lower bound. Realistic estimate is **30-50% more tokens** due to larger structured output + taxonomy instructions. At gpt-4o-mini pricing, this remains negligible (~$0.05-0.10 per full run of 636 reviews).
- **I4 (Health Index formula)**: `high_risk_ratio` = count of own products with risk_score ≥ `HIGH_RISK_THRESHOLD` / total own product count.
- **I5 (Competitive Gap Index)**: Defined as: sum of (competitor positive review count + own negative review count) across all overlapping label dimensions. Higher = wider gap.
- **I6 (P5 threshold)**: Intentionally hardcoded design choice (≥3 products, ≥50 analyzed reviews). Not exposed as config — these are minimum data requirements for statistical validity, not business preferences.
- **I7 (File location)**: Chart code lives in new `report_charts.py`. Section 12.4 code comment fixed.

### Design decisions on reviewer questions

- **Q1 (Report-level LLM caching)**: Result is cached in `analytics_path` JSON alongside the workflow run. Re-generation from the same snapshot reuses cached analytics. Only a new snapshot triggers a new LLM call.
- **Q2 (CJK fonts with Plotly)**: Plotly HTML fragments use the browser's font stack. Playwright's Chromium inherits OS fonts. On Windows (dev), CJK fonts are pre-installed. On Linux (deploy), `fonts-noto-cjk` is required in the Docker image — same requirement as current Matplotlib setup.
- **Q3 (prompt_version selection)**: Report queries `review_analysis` with `ORDER BY analyzed_at DESC LIMIT 1` per review_id, always using the latest analysis. Old versions are retained for audit but not used in reports.
- **Q4 (Resolved issues)**: An issue is "resolved" when it appeared in the previous report's analytics but has zero reviews in the current period's data window. This is a signal, not a guarantee — the report labels it as "本期未见新增" rather than "已解决".
- **Q5 (Backfill trigger)**: Added CLI command `qbu-crawler backfill-analysis` in Section 15.3.
