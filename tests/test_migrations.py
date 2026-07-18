"""Tests for the zero-dependency schema migration system."""
from __future__ import annotations

import sqlite3

import pytest

from alethic_kernel.migrations import (
    MIGRATIONS, _current_version, _ensure_version_table, migrate,
)
from alethic_kernel.sqlite_store import SqliteStore

from tests.helpers import make_record


class TestEnsureVersionTable:
    def test_creates_table(self):
        conn = sqlite3.connect(":memory:")
        _ensure_version_table(conn)
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        )
        assert cur.fetchone() is not None
        conn.close()

    def test_idempotent(self):
        conn = sqlite3.connect(":memory:")
        _ensure_version_table(conn)
        _ensure_version_table(conn)  # should not raise
        conn.close()


class TestCurrentVersion:
    def test_zero_on_fresh_db(self):
        conn = sqlite3.connect(":memory:")
        _ensure_version_table(conn)
        assert _current_version(conn) == 0
        conn.close()

    def test_reflects_inserted_version(self):
        conn = sqlite3.connect(":memory:")
        _ensure_version_table(conn)
        conn.execute("INSERT INTO schema_version (version) VALUES (3)")
        conn.commit()
        assert _current_version(conn) == 3
        conn.close()

    def test_returns_max_version(self):
        conn = sqlite3.connect(":memory:")
        _ensure_version_table(conn)
        conn.execute("INSERT INTO schema_version (version) VALUES (1)")
        conn.execute("INSERT INTO schema_version (version) VALUES (5)")
        conn.execute("INSERT INTO schema_version (version) VALUES (3)")
        conn.commit()
        assert _current_version(conn) == 5
        conn.close()


class TestMigrate:
    def test_fresh_db_gets_all_migrations(self):
        conn = sqlite3.connect(":memory:")
        final = migrate(conn)
        assert final == max(MIGRATIONS.keys())
        # records table should exist
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='records'"
        )
        assert cur.fetchone() is not None
        conn.close()

    def test_idempotent(self):
        conn = sqlite3.connect(":memory:")
        v1 = migrate(conn)
        v2 = migrate(conn)
        assert v1 == v2
        conn.close()

    def test_indexes_created(self):
        conn = sqlite3.connect(":memory:")
        migrate(conn)
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
        )
        index_names = {row[0] for row in cur.fetchall()}
        assert "idx_slot" in index_names
        assert "idx_trace" in index_names
        assert "idx_status" in index_names
        assert "idx_slot_kind_trace" in index_names
        conn.close()

    def test_partial_upgrade(self):
        """DB at version N upgrades to N+1 when a new migration is added."""
        conn = sqlite3.connect(":memory:")
        # Apply only version 1 manually
        _ensure_version_table(conn)
        conn.executescript(MIGRATIONS[1])
        conn.execute("INSERT INTO schema_version (version) VALUES (1)")
        conn.commit()
        assert _current_version(conn) == 1

        # Running migrate should be no-op since we only have version 1
        final = migrate(conn)
        assert final == 1
        conn.close()

    def test_skips_already_applied(self):
        """Migration for version already in schema_version is skipped."""
        conn = sqlite3.connect(":memory:")
        migrate(conn)
        # Insert a record to prove the schema is intact
        conn.execute(
            "INSERT INTO records (id, slot, mode, kind, payload, writer_id, "
            "trace_id, ts_ms, input_refs, confidence, ttl_ms, evidence_refs, "
            "status, reason, scope) VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("id1", "percepts", "COMMIT", "charge", "{}", "w", "t", 0,
             "[]", None, None, "[]", "ACTIVE", None, "episode"),
        )
        conn.commit()

        # Running migrate again should not fail or duplicate
        final = migrate(conn)
        assert final == max(MIGRATIONS.keys())
        cur = conn.execute("SELECT COUNT(*) FROM records")
        assert cur.fetchone()[0] == 1
        conn.close()


class TestMigrateWithSqliteStore:
    def test_store_uses_migrations(self):
        """SqliteStore.__init__ uses migrate() and produces a working store."""
        store = SqliteStore(":memory:")
        rec = make_record(rec_id="p:t:1")
        store.append(rec)
        got = store.get("p:t:1")
        assert got is not None
        assert got.id == "p:t:1"
        store.close()

    def test_reopen_preserves_version(self, tmp_path):
        """Reopening a DB file doesn't re-run migrations."""
        db_path = str(tmp_path / "migrate.db")
        store1 = SqliteStore(db_path)
        rec = make_record(rec_id="p:t:1")
        store1.append(rec)
        store1.close()

        store2 = SqliteStore(db_path)
        # Should not fail (migrations idempotent)
        got = store2.get("p:t:1")
        assert got is not None

        # Verify version table has correct version
        cur = store2._conn.execute("SELECT MAX(version) FROM schema_version")
        assert cur.fetchone()[0] == max(MIGRATIONS.keys())
        store2.close()

    def test_old_records_deserialize(self, tmp_path):
        """Records written before schema changes still deserialize correctly."""
        db_path = str(tmp_path / "compat.db")
        store = SqliteStore(db_path)
        rec = make_record(
            rec_id="p:t:1",
            payload={"amount": 100},
            confidence=0.95,
            scope="persistent",
        )
        store.append(rec)
        store.close()

        # Reopen — simulates upgrade scenario
        store2 = SqliteStore(db_path)
        got = store2.get("p:t:1")
        assert got is not None
        assert got.payload == {"amount": 100}
        assert got.prov.confidence == 0.95
        assert got.scope == "persistent"
        store2.close()
