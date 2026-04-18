"""python -m scripts.simulate_reports show <SID>"""
import json
from .. import config
from ..manifest import read_manifest


def _find_dir(sid):
    if not config.SCENARIOS_DIR.exists():
        return None
    for sd in config.SCENARIOS_DIR.iterdir():
        if sd.is_dir() and sd.name.startswith(f"{sid}-"):
            return sd
    return None


def run(argv):
    if not argv:
        print("Usage: show <SID>"); return 2
    sid = argv[0]
    sd = _find_dir(sid)
    if not sd:
        print(f"Scenario dir not found for {sid}"); return 2
    m = read_manifest(sd)
    if not m:
        print(f"No manifest in {sd}"); return 2
    print(f"=== {sid} ===")
    print(json.dumps(m, ensure_ascii=False, indent=2))
    dbg = sd / "debug"
    if dbg.exists():
        print("\ndebug/:")
        for p in sorted(dbg.iterdir()):
            print(f"  {p.name} ({p.stat().st_size} bytes)")
    return 0
