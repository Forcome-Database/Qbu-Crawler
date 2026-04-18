"""Build issues.md from all manifests with FAIL/WARN."""
import json
from . import config


def build_issues() -> str:
    rows = []
    if not config.SCENARIOS_DIR.exists():
        config.ISSUES_MD.write_text("# Simulation Issues\n\n(no scenarios)\n", encoding="utf-8")
        return ""
    for sd in sorted(config.SCENARIOS_DIR.iterdir()):
        mp = sd / "manifest.json"
        if not mp.exists():
            continue
        try:
            rows.append((sd, json.loads(mp.read_text(encoding="utf-8"))))
        except Exception:
            continue
    fails = [(sd, m) for sd, m in rows if m.get("verdict") == "FAIL"]
    warns = [(sd, m) for sd, m in rows if m.get("verdict") == "WARN"]
    if not fails and not warns:
        out = "# Simulation Issues\n\n✅ All scenarios PASS.\n"
    else:
        out = "# Simulation Issues\n\n"
        if fails:
            out += f"## ❌ FAIL ({len(fails)})\n\n"
            for sd, m in fails:
                out += f"### {m['scenario_id']} {m.get('description','')} ({m['logical_date']})\n\n"
                for f in m.get("failures", []):
                    out += f"- {f}\n"
                out += f"- 重现：`python -m scripts.simulate_reports run-one {m['scenario_id']}`\n\n"
        if warns:
            out += f"## ⚠️ WARN ({len(warns)})\n\n"
            for sd, m in warns:
                out += f"### {m['scenario_id']} ({m['logical_date']})\n\n"
                for w in m.get("warnings", []):
                    out += f"- {w}\n"
                out += "\n"
    config.ISSUES_MD.write_text(out, encoding="utf-8")
    return out
