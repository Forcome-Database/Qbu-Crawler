"""Simulation-wide constants: paths, timeline, scenario IDs."""
from pathlib import Path
from datetime import date

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Baseline DB (read-only)
BASELINE_DB = Path(r"C:\Users\leo\Desktop\报告\data\products.db")

# Working DB (writable, in project)
SIM_DATA_DIR = PROJECT_ROOT / "data" / "sim"
# NOTE: filename must match qbu_crawler hardcoded DB_PATH ("products.db")
SIM_DB = SIM_DATA_DIR / "products.db"
CHECKPOINT_DIR = SIM_DATA_DIR / "checkpoints"

# Report outputs (on desktop)
REPORT_ROOT = Path(r"C:\Users\leo\Desktop\报告\reports")
SCENARIOS_DIR = REPORT_ROOT / "scenarios"
LEGACY_DIR = REPORT_ROOT / "_legacy"
INDEX_HTML = REPORT_ROOT / "index.html"
ISSUES_MD = REPORT_ROOT / "issues.md"

# Temp REPORT_DIR used by business code during a run
# (all emitted files are then copied to scenario dir)
REPORT_WORK_DIR = SIM_DATA_DIR / "reports_raw"

# Timeline
TIMELINE_START = date(2026, 3, 20)
TIMELINE_END = date(2026, 5, 1)

# Scenario IDs (11 named + variants defined in scenarios.py)
NAMED_SCENARIOS = [
    "S01", "S02", "S03", "S04", "S05",
    "S06", "S07", "S08a", "S08b", "S08c",
    "S09a", "S09b", "S09c", "S10", "S11",
    "W0", "W1", "W2", "W3", "W4", "W5",
    "M1",
]
