"""python -m scripts.simulate_reports verify | issues"""
import json
from .. import config
from ..issues_page import build_issues


def run(argv):
    total = pass_n = warn_n = fail_n = 0
    if config.SCENARIOS_DIR.exists():
        for sd in sorted(config.SCENARIOS_DIR.iterdir()):
            mp = sd / "manifest.json"
            if not mp.exists():
                continue
            try:
                m = json.loads(mp.read_text(encoding="utf-8"))
            except Exception:
                continue
            total += 1
            v = m.get("verdict", "?")
            tag = {"PASS": "\033[32m✅", "WARN": "\033[33m⚠️", "FAIL": "\033[31m❌"}.get(v, "?")
            print(f"{tag} {m['scenario_id']:8s} {v:5s}\033[0m  {m.get('description','')}")
            if v == "PASS":
                pass_n += 1
            elif v == "WARN":
                warn_n += 1
            elif v == "FAIL":
                fail_n += 1
            for f in m.get("failures", []):
                print(f"      · {f}")
    print(f"\n总计 {total} · PASS {pass_n} · WARN {warn_n} · FAIL {fail_n}")
    build_issues()
    print(f"issues.md → {config.ISSUES_MD}")
    return 0 if fail_n == 0 else 1
