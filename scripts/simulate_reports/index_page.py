"""Build reports/index.html from all scenario manifests."""
import html as _html
import json
from pathlib import Path
from . import config


def _load_all_manifests():
    out = []
    if not config.SCENARIOS_DIR.exists():
        return out
    for sd in sorted(config.SCENARIOS_DIR.iterdir()):
        m = sd / "manifest.json"
        if m.exists():
            try:
                out.append((sd, json.loads(m.read_text(encoding="utf-8"))))
            except Exception:
                continue
    return out


_BADGE = {"PASS": "#2ecc71", "WARN": "#f39c12", "FAIL": "#e74c3c"}


def build_index():
    rows = _load_all_manifests()
    n_pass = sum(1 for _, m in rows if m.get("verdict") == "PASS")
    n_warn = sum(1 for _, m in rows if m.get("verdict") == "WARN")
    n_fail = sum(1 for _, m in rows if m.get("verdict") == "FAIL")
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<title>Report Simulation Index</title>",
        "<style>",
        "body{font-family:-apple-system,Segoe UI,sans-serif;background:#f5f5f7;margin:0;padding:24px}",
        ".summary{font-size:18px;margin-bottom:16px}",
        ".card{background:#fff;border-radius:8px;padding:16px;margin:12px 0;",
        "box-shadow:0 1px 3px rgba(0,0,0,.08)}",
        ".badge{display:inline-block;padding:2px 10px;border-radius:12px;color:#fff;font-size:12px;margin-left:8px}",
        ".meta{color:#666;font-size:13px}",
        "details{margin-top:8px}",
        "pre{background:#f7f7f7;padding:8px;border-radius:4px;overflow-x:auto;font-size:12px}",
        "a{color:#0366d6}",
        ".filter{margin:0 0 20px}",
        ".filter label{margin-right:12px;font-size:13px}",
        "</style></head><body>",
        f"<h1>Report Simulation Index</h1>",
        f"<div class='summary'>✅ {n_pass} PASS &nbsp; ⚠️ {n_warn} WARN &nbsp; ❌ {n_fail} FAIL &nbsp; — 共 {len(rows)} 场景</div>",
        "<div class='filter'>",
        "<label><input type='checkbox' class='vf' value='PASS' checked>PASS</label>",
        "<label><input type='checkbox' class='vf' value='WARN' checked>WARN</label>",
        "<label><input type='checkbox' class='vf' value='FAIL' checked>FAIL</label>",
        "<label>tier: <select id='tf'><option>all</option><option>daily</option><option>weekly</option><option>monthly</option></select></label>",
        "</div>",
    ]
    for sd, m in rows:
        rel = sd.relative_to(config.REPORT_ROOT).as_posix()
        verdict = m.get("verdict", "?")
        badge_color = _BADGE.get(verdict, "#999")
        artifacts_links = "".join(
            f"<a href='{rel}/{_html.escape(a)}'>{_html.escape(a)}</a> "
            for a in m.get("artifacts", [])
        )
        debug_link = f"<a href='{rel}/debug/'>debug/</a>"
        emails_link = f"<a href='{rel}/emails/'>emails/</a>"
        exp_json = json.dumps(m.get("expected", {}), ensure_ascii=False, indent=2)
        act_json = json.dumps(m.get("actual", {}), ensure_ascii=False, indent=2)
        failures = "<ul>" + "".join(
            f"<li>{_html.escape(f)}</li>" for f in m.get("failures", [])
        ) + "</ul>" if m.get("failures") else ""
        parts.append(
            f"<div class='card' data-verdict='{verdict}' data-tier='{m.get('tier','?')}'>"
            f"<strong>{_html.escape(m.get('scenario_id','?'))}</strong>"
            f"<span class='badge' style='background:{badge_color}'>{verdict}</span>"
            f"<div class='meta'>{_html.escape(str(m.get('logical_date','?')))}"
            f" · {_html.escape(m.get('tier','?'))}"
            f" · {_html.escape(m.get('description',''))}</div>"
            f"<div class='meta'>Artifacts: {artifacts_links} {debug_link} {emails_link}</div>"
            f"{failures}"
            f"<details><summary>expected vs actual</summary>"
            f"<div style='display:flex;gap:16px'>"
            f"<div style='flex:1'><h4>expected</h4><pre>{_html.escape(exp_json)}</pre></div>"
            f"<div style='flex:1'><h4>actual</h4><pre>{_html.escape(act_json)}</pre></div>"
            f"</div></details>"
            "</div>"
        )
    parts.append("""
<script>
const vfs=[...document.querySelectorAll('.vf')];
const tf=document.getElementById('tf');
function filter(){
  const allowed=new Set(vfs.filter(c=>c.checked).map(c=>c.value));
  const tier=tf.value;
  document.querySelectorAll('.card').forEach(c=>{
    const v=c.dataset.verdict, t=c.dataset.tier;
    c.style.display=(allowed.has(v)&&(tier==='all'||t===tier))?'':'none';
  });
}
vfs.forEach(c=>c.onchange=filter); tf.onchange=filter;
</script>
</body></html>""")
    config.INDEX_HTML.write_text("\n".join(parts), encoding="utf-8")
    return config.INDEX_HTML
