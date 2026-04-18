"""Build per-scenario manifest: expected / actual / verdict."""
import json
import subprocess
from datetime import datetime
from pathlib import Path


def compute_verdict(expected: dict, actual: dict) -> tuple[str, list[str], list[str]]:
    failures, warnings = [], []
    # report_mode exact match
    if "report_mode" in expected and expected["report_mode"] != actual.get("report_mode"):
        failures.append(
            f"report_mode: expected={expected['report_mode']}, actual={actual.get('report_mode')}"
        )
    if "tier" in expected and expected["tier"] != actual.get("tier"):
        failures.append(f"tier: expected={expected['tier']}, actual={actual.get('tier')}")
    if "is_partial" in expected and expected["is_partial"] != actual.get("is_partial"):
        failures.append(
            f"is_partial: expected={expected['is_partial']}, actual={actual.get('is_partial')}"
        )
    # lifecycle must include
    must = set(expected.get("lifecycle_states_must_include", []))
    seen = set(actual.get("lifecycle_states_seen", []))
    missing = must - seen
    if missing:
        failures.append(f"lifecycle missing: {sorted(missing)}")
    # html contains
    for token in expected.get("html_must_contain", []):
        if not actual.get("html_contains", {}).get(token):
            failures.append(f"html missing token: {token!r}")
    # excel sheets
    for sheet in expected.get("excel_must_have_sheets", []):
        if sheet not in actual.get("excel_sheets", []):
            failures.append(f"excel missing sheet: {sheet!r}")
    # email counts
    if "email_count_min" in expected:
        if actual.get("email_count", 0) < expected["email_count_min"]:
            warnings.append(
                f"email_count {actual.get('email_count')} < min {expected['email_count_min']}"
            )
    if "email_count_max" in expected:
        if actual.get("email_count", 0) > expected["email_count_max"]:
            warnings.append(
                f"email_count {actual.get('email_count')} > max {expected['email_count_max']}"
            )
    if failures:
        return "FAIL", failures, warnings
    if warnings:
        return "WARN", failures, warnings
    return "PASS", failures, warnings


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True
        ).strip()
    except Exception:
        return "unknown"


def build_manifest(
    *,
    scenario_id: str,
    logical_date,
    phase: str,
    description: str,
    tier: str,
    expected: dict,
    actual: dict,
    artifacts: list[str],
) -> dict:
    verdict, failures, warnings = compute_verdict(expected, actual)
    return {
        "scenario_id": scenario_id,
        "logical_date": logical_date.isoformat() if hasattr(logical_date, "isoformat") else str(logical_date),
        "phase": phase,
        "description": description,
        "tier": tier,
        "expected": expected,
        "actual": actual,
        "verdict": verdict,
        "failures": failures,
        "warnings": warnings,
        "artifacts": artifacts,
        "git_sha": _git_sha(),
        "spec_version": "2026-04-17",
        "executed_at": datetime.now().isoformat(timespec="seconds"),
    }


def write_manifest(scenario_dir: Path, manifest: dict):
    (scenario_dir / "manifest.json").write_text(
        json.dumps(manifest, default=str, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def read_manifest(scenario_dir: Path) -> dict | None:
    p = scenario_dir / "manifest.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def collect_actual(
    *,
    run_id: int,
    scenario_dir: Path,
    expected: dict,
) -> dict:
    """Inspect business output + scenario files to populate `actual` dict."""
    from .env_bootstrap import load_business
    biz = load_business()
    actual: dict = {}
    with biz.models.get_conn() as conn:
        run = conn.execute(
            "SELECT * FROM workflow_runs WHERE id=?", (run_id,)
        ).fetchone()
    if run:
        actual["tier"] = run["report_tier"]
        actual["report_mode"] = run["report_mode"]
        actual["status"] = run["status"]
        actual["report_phase"] = run["report_phase"]
        # is_partial was persisted to workflow_runs in Task 1.3 (D4);
        # previously pulled from analytics_tree which only exists for
        # full-pipeline runs — workflow_runs is authoritative now.
        try:
            actual["is_partial"] = bool(run["is_partial"])
        except (IndexError, KeyError):
            actual["is_partial"] = False
    # lifecycle_states_seen: pull from analytics envelope (v4) or raw tree
    analytics_path = scenario_dir / "debug" / "analytics_tree.json"
    if analytics_path.exists():
        try:
            tree = json.loads(analytics_path.read_text(encoding="utf-8"))
            states = set()
            for lc in (tree.get("lifecycle") or {}).values():
                if isinstance(lc, dict) and lc.get("state"):
                    states.add(lc["state"])
            actual["lifecycle_states_seen"] = sorted(states)
        except Exception:
            pass
    # html contains
    html_checks = {}
    html_files = list(scenario_dir.glob("*.html"))
    combined_html = "\n".join(
        f.read_text(encoding="utf-8", errors="ignore") for f in html_files
    )
    for token in expected.get("html_must_contain", []):
        html_checks[token] = token in combined_html
    actual["html_contains"] = html_checks
    # excel sheets
    xl_struct = scenario_dir / "debug" / "excel_structure.json"
    sheets = set()
    if xl_struct.exists():
        try:
            s = json.loads(xl_struct.read_text(encoding="utf-8"))
            for sheet_map in s.values():
                if isinstance(sheet_map, dict):
                    sheets.update(sheet_map.keys())
        except Exception:
            pass
    actual["excel_sheets"] = sorted(sheets)
    # email count
    emails_dir = scenario_dir / "emails"
    actual["email_count"] = (
        len(list(emails_dir.glob("*.html"))) + len(list(emails_dir.glob("*.md")))
        if emails_dir.exists() else 0
    )
    return actual
