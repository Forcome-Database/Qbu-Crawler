"""Read `notification_outbox` rows produced by a business run and
serialize their payloads to HTML/Markdown files under the scenario dir.
Mark drained rows as 'delivered' so they're not re-processed."""
import json
from datetime import datetime
from pathlib import Path
from .env_bootstrap import load_business


def drain_outbox_for_run(run_id: int, scenario_dir: Path) -> list[dict]:
    biz = load_business()
    emails_dir = scenario_dir / "emails"
    emails_dir.mkdir(parents=True, exist_ok=True)
    drained = []
    with biz.models.get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM notification_outbox
               WHERE status IN ('pending','claimed','deadletter','sent')
               ORDER BY id"""
        ).fetchall()
        for r in rows:
            try:
                payload = json.loads(r["payload"] or "{}")
            except (ValueError, TypeError):
                payload = {"_raw": r["payload"]}
            if payload.get("run_id") not in (None, run_id):
                continue
            kind = r["kind"] or "unknown"
            fname_base = f"{kind}-outbox{r['id']}"
            (emails_dir / f"{fname_base}.json").write_text(
                json.dumps(dict(r), default=str, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            if isinstance(payload, dict):
                body = payload.get("html") or payload.get("body") or payload.get("markdown")
                if body:
                    ext = "html" if "html" in payload else "md"
                    (emails_dir / f"{fname_base}.{ext}").write_text(
                        body, encoding="utf-8",
                    )
            now_iso = datetime.now().isoformat(timespec="seconds")
            conn.execute(
                "UPDATE notification_outbox SET status='delivered', delivered_at=? WHERE id=?",
                (now_iso, r["id"]),
            )
            drained.append({
                "id": r["id"], "kind": kind, "channel": r["channel"],
                "status_before": r["status"],
            })
        conn.commit()
    return drained
