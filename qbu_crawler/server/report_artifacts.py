"""F011 §5.1 — report_artifacts table CRUD.

Records every report output artifact (snapshot JSON, Excel, V3 HTML, email body)
into the `report_artifacts` table created by migration 0010.  Each row carries
a sha256[:16] content hash, byte size, the generator version (qbu_crawler
package version) and an optional template version, so downstream auditing /
diff tooling can answer "which artifact came from which run with which
template".
"""
from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
from typing import Optional

_logger = logging.getLogger(__name__)


def record_artifact(
    conn: sqlite3.Connection,
    run_id: int,
    artifact_type: str,
    path: str,
    *,
    template_version: Optional[str] = None,
) -> Optional[int]:
    """F011 §5.1 — record one report artifact and return its rowid.

    Returns ``None`` if the file does not exist on disk; we never half-record a
    missing artifact (callers are expected to verify their write succeeded
    before calling).

    ``artifact_type`` must be one of the table's CHECK enum values:
    ``html_attachment`` / ``xlsx`` / ``pdf`` / ``snapshot`` / ``analytics`` /
    ``email_body``.  Unknown values raise ``sqlite3.IntegrityError``.

    The connection is committed inline.  Callers must not pass an in-progress
    transaction connection.
    """
    from qbu_crawler import __version__

    if not os.path.exists(path):
        _logger.debug(
            "record_artifact: skipping missing file run_id=%s type=%s path=%s",
            run_id, artifact_type, path,
        )
        return None

    with open(path, "rb") as f:
        content = f.read()

    file_hash = hashlib.sha256(content).hexdigest()[:16]
    bytes_size = len(content)

    cur = conn.cursor()
    cur.execute(
        """INSERT INTO report_artifacts
           (run_id, artifact_type, path, hash, template_version, generator_version, bytes)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (run_id, artifact_type, path, file_hash, template_version, __version__, bytes_size),
    )
    conn.commit()
    return cur.lastrowid


def list_artifacts(conn: sqlite3.Connection, run_id: int) -> list[dict]:
    """List all artifacts for ``run_id`` in insert (id-asc) order."""
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM report_artifacts WHERE run_id = ? ORDER BY id",
        (run_id,),
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]
