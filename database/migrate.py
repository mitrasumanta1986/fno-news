"""Applies versioned SQL migrations from database/migrations (NNN_name.sql)."""
from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path

from utils.timeutils import now_iso

log = logging.getLogger(__name__)
MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def migrate(conn: sqlite3.Connection) -> int:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
    current = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()[0]
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        match = re.match(r"(\d+)_", path.name)
        if not match or int(match.group(1)) <= current:
            continue
        version = int(match.group(1))
        log.info("applying migration %s", path.name)
        script = path.read_text(encoding="utf-8")
        try:
            conn.executescript(
                f"BEGIN;\n{script}\nINSERT INTO schema_version(version, applied_at) VALUES ({version}, '{now_iso()}');\nCOMMIT;"
            )
        except sqlite3.Error:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        current = version
    return current
