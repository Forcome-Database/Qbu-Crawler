"""Index real review texts keyed by (label_code, polarity) for cloning."""
import random
import sqlite3
from pathlib import Path


class BodyPool:
    def __init__(self, db_path: Path, *, seed: int = 42):
        self._rng = random.Random(seed)
        self._by_key: dict[tuple, list[dict]] = {}
        with sqlite3.connect(str(db_path)) as c:
            c.row_factory = sqlite3.Row
            rows = c.execute("""
                SELECT r.id, r.body, r.headline, r.rating, r.body_hash,
                       l.label_code, l.label_polarity
                FROM reviews r
                JOIN review_issue_labels l ON l.review_id = r.id
            """).fetchall()
        for r in rows:
            key = (r["label_code"], r["label_polarity"])
            self._by_key.setdefault(key, []).append({
                "body": r["body"],
                "headline": r["headline"],
                "rating": r["rating"],
                "body_hash": r["body_hash"],
            })

    def sample(self, label_code: str, polarity: str, n: int) -> list[dict]:
        """Return n rows with replacement (always returns n items if pool non-empty)."""
        key = (label_code, polarity)
        pool = self._by_key.get(key, [])
        if not pool:
            # Fallback: sample any review with matching polarity
            for (lc, pol), rows in self._by_key.items():
                if pol == polarity and rows:
                    pool = rows
                    break
        if not pool:
            return []
        return [self._rng.choice(pool) for _ in range(n)]
