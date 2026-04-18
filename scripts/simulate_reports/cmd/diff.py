"""python -m scripts.simulate_reports diff <SID1> <SID2>"""
import json
from .. import config
from .show import _find_dir


def _load(sid):
    sd = _find_dir(sid)
    if not sd:
        return None, None
    m = json.loads((sd / "manifest.json").read_text(encoding="utf-8"))
    return sd, m


def run(argv):
    if len(argv) < 2:
        print("Usage: diff <SID1> <SID2>"); return 2
    sid1, sid2 = argv[0], argv[1]
    d1, m1 = _load(sid1)
    d2, m2 = _load(sid2)
    if not m1 or not m2:
        print("One or both scenarios missing"); return 2
    print(f"=== {sid1} vs {sid2} ===")
    for key in ("tier", "report_mode", "status", "report_phase", "is_partial", "email_count"):
        v1 = m1.get("actual", {}).get(key)
        v2 = m2.get("actual", {}).get(key)
        mark = "  " if v1 == v2 else "≠ "
        print(f"  {mark}{key:18s}  {v1!r:30s}  {v2!r}")
    for sd, m in [(d1, m1), (d2, m2)]:
        ap = sd / "debug" / "analytics_tree.json"
        if ap.exists():
            tree = json.loads(ap.read_text(encoding="utf-8"))
            print(f"\n  {m['scenario_id']} analytics keys: {sorted(tree.keys())[:12]}")
    return 0
