"""Zero-dependency schema migration system for SqliteStore.

Tracks schema version in a `schema_version` table. Each migration is a SQL
string keyed by version number. `migrate()` applies all pending migrations
in order. Fresh databases get all migrations. Existing databases upgrade
incrementally. Running `migrate()` twice is safe (idempotent).
"""
from __future__ import annotations

import sqlite3
from typing import Dict


# ── Migration registry ───────────────────────────────────────────────
# Each key is a version number (1-indexed). Value is the SQL to apply.
# New migrations MUST be appended — never modify or reorder existing ones.

MIGRATIONS: Dict[int, str] = {
    1: """
    CREATE TABLE IF NOT EXISTS records (
        id         TEXT PRIMARY KEY,
        slot       TEXT NOT NULL,
        mode       TEXT NOT NULL,
        kind       TEXT NOT NULL,
        payload    TEXT NOT NULL,
        writer_id  TEXT NOT NULL,
        trace_id   TEXT NOT NULL,
        ts_ms      INTEGER NOT NULL,
        input_refs TEXT NOT NULL,
        confidence REAL,
        ttl_ms     INTEGER,
        evidence_refs TEXT NOT NULL,
        status     TEXT NOT NULL DEFAULT 'ACTIVE',
        reason     TEXT,
        scope      TEXT NOT NULL DEFAULT 'episode'
    );
    CREATE INDEX IF NOT EXISTS idx_slot ON records(slot);
    CREATE INDEX IF NOT EXISTS idx_trace ON records(trace_id);
    CREATE INDEX IF NOT EXISTS idx_status ON records(status);
    CREATE INDEX IF NOT EXISTS idx_slot_kind_trace ON records(slot, kind, trace_id, status);
    """,
}


def _ensure_version_table(conn: sqlite3.Connection) -> None:
    """Create the schema_version table if it doesn't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY
        )
    """)
    conn.commit()


def _current_version(conn: sqlite3.Connection) -> int:
    """Return the current schema version (0 if no migrations applied)."""
    cur = conn.execute("SELECT MAX(version) FROM schema_version")
    row = cur.fetchone()
    if row is None or row[0] is None:
        return 0
    return int(row[0])


def migrate(conn: sqlite3.Connection) -> int:
    """Apply all pending migrations. Returns the final schema version."""
    _ensure_version_table(conn)
    current = _current_version(conn)

    for version in sorted(MIGRATIONS.keys()):
        if version <= current:
            continue
        conn.executescript(MIGRATIONS[version])
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
        conn.commit()

    return _current_version(conn)
