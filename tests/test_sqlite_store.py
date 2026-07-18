from __future__ import annotations

import time
import pytest

from alethic_kernel.sqlite_store import SqliteStore
from alethic_kernel.schema import Record, Provenance

from tests.helpers import make_record


class TestSqliteStoreBasic:
    def test_append_and_get(self, sqlite_store: SqliteStore):
        rec = make_record(rec_id="p:t:1")
        sqlite_store.append(rec)
        got = sqlite_store.get("p:t:1")
        assert got is not None
        assert got.id == "p:t:1"
        assert got.payload == rec.payload

    def test_get_missing_returns_none(self, sqlite_store: SqliteStore):
        assert sqlite_store.get("nonexistent") is None

    def test_list_slot(self, sqlite_store: SqliteStore):
        r1 = make_record(rec_id="p:t:1", slot="percepts", kind="charge")
        r2 = make_record(rec_id="b:t:1", slot="beliefs", kind="refund_due")
        sqlite_store.append(r1)
        sqlite_store.append(r2)
        percepts = sqlite_store.list_slot("percepts")
        assert len(percepts) == 1
        assert percepts[0].kind == "charge"

    def test_find_active_by_kind(self, sqlite_store: SqliteStore):
        rec = make_record(rec_id="p:t:1", kind="charge", trace_id="t1")
        sqlite_store.append(rec)
        found = sqlite_store.find_active_by_kind("percepts", "charge", "t1")
        assert found is not None
        assert found.kind == "charge"

    def test_find_active_skips_invalidated(self, sqlite_store: SqliteStore):
        rec = make_record(rec_id="p:t:1", kind="charge", trace_id="t1")
        sqlite_store.append(rec)
        sqlite_store.invalidate("p:t:1", "reason")
        assert sqlite_store.find_active_by_kind("percepts", "charge", "t1") is None


class TestSqliteStoreInvalidate:
    def test_invalidate(self, sqlite_store: SqliteStore):
        rec = make_record(rec_id="p:t:1")
        sqlite_store.append(rec)
        sqlite_store.invalidate("p:t:1", "test reason")
        got = sqlite_store.get("p:t:1")
        assert got.status == "INVALIDATED"
        assert got.reason == "test reason"


class TestSqliteStoreTTL:
    def test_ttl_not_expired(self, sqlite_store: SqliteStore):
        rec = make_record(rec_id="p:t:1", ttl_ms=60000)
        sqlite_store.append(rec)
        got = sqlite_store.get("p:t:1")
        assert got.status == "ACTIVE"

    def test_ttl_expired(self, sqlite_store: SqliteStore):
        rec = make_record(rec_id="p:t:1", ttl_ms=1)
        rec.prov.ts_ms = int(time.time() * 1000) - 1000
        sqlite_store.append(rec)
        got = sqlite_store.get("p:t:1")
        assert got.status == "EXPIRED"

    def test_ttl_expired_persisted_to_db(self, sqlite_store: SqliteStore):
        rec = make_record(rec_id="p:t:1", ttl_ms=1)
        rec.prov.ts_ms = int(time.time() * 1000) - 1000
        sqlite_store.append(rec)
        sqlite_store.get("p:t:1")  # triggers TTL check
        got = sqlite_store.get("p:t:1")
        assert got.status == "EXPIRED"


class TestSqliteStoreExtended:
    def test_list_by_status(self, sqlite_store: SqliteStore):
        r1 = make_record(rec_id="p:t:1")
        r2 = make_record(rec_id="p:t:2")
        sqlite_store.append(r1)
        sqlite_store.append(r2)
        sqlite_store.invalidate("p:t:2", "reason")
        active = sqlite_store.list_by_status("ACTIVE")
        invalidated = sqlite_store.list_by_status("INVALIDATED")
        assert len(active) == 1
        assert len(invalidated) == 1

    def test_list_persistent(self, sqlite_store: SqliteStore):
        r1 = make_record(rec_id="p:t:1", scope="episode")
        r2 = make_record(rec_id="c:t:1", slot="constraints", scope="persistent")
        sqlite_store.append(r1)
        sqlite_store.append(r2)
        persistent = sqlite_store.list_persistent()
        assert len(persistent) == 1
        assert persistent[0].scope == "persistent"

    def test_list_persistent_by_slot(self, sqlite_store: SqliteStore):
        r1 = make_record(rec_id="c:t:1", slot="constraints", scope="persistent")
        r2 = make_record(rec_id="b:t:1", slot="beliefs", scope="persistent")
        sqlite_store.append(r1)
        sqlite_store.append(r2)
        constraints = sqlite_store.list_persistent(slot="constraints")
        assert len(constraints) == 1

    def test_count_invalidated_by_reason(self, sqlite_store: SqliteStore):
        for i in range(3):
            rec = make_record(rec_id=f"b:t:{i}", slot="beliefs")
            sqlite_store.append(rec)
            sqlite_store.invalidate(f"b:t:{i}", "STALE_EVIDENCE")
        rec = make_record(rec_id="b:t:3", slot="beliefs")
        sqlite_store.append(rec)
        sqlite_store.invalidate("b:t:3", "LOW_CONFIDENCE")
        counts = sqlite_store.count_invalidated_by_reason()
        assert counts["STALE_EVIDENCE"] == 3
        assert counts["LOW_CONFIDENCE"] == 1


class TestSqliteStoreWALAndDurability:
    def test_wal_mode(self, tmp_path):
        store = SqliteStore(str(tmp_path / "wal.db"))
        cur = store._conn.execute("PRAGMA journal_mode")
        mode = cur.fetchone()[0]
        assert mode.lower() == "wal"
        store.close()

    def test_reopen_durability(self, tmp_path):
        db_path = str(tmp_path / "durable.db")
        store1 = SqliteStore(db_path)
        rec = make_record(rec_id="p:t:1", payload={"key": "value"})
        store1.append(rec)
        store1.close()

        store2 = SqliteStore(db_path)
        got = store2.get("p:t:1")
        assert got is not None
        assert got.payload == {"key": "value"}
        store2.close()


class TestSqliteStoreFieldPreservation:
    def test_confidence_preserved(self, sqlite_store: SqliteStore):
        rec = make_record(rec_id="p:t:1", confidence=0.85)
        sqlite_store.append(rec)
        got = sqlite_store.get("p:t:1")
        assert got.prov.confidence == 0.85

    def test_input_refs_preserved(self, sqlite_store: SqliteStore):
        rec = make_record(rec_id="p:t:1")
        rec.prov.input_refs = ["ref1", "ref2"]
        sqlite_store.append(rec)
        got = sqlite_store.get("p:t:1")
        assert got.prov.input_refs == ["ref1", "ref2"]

    def test_evidence_refs_preserved(self, sqlite_store: SqliteStore):
        rec = make_record(rec_id="p:t:1")
        rec.evidence_refs = ["ev1"]
        sqlite_store.append(rec)
        got = sqlite_store.get("p:t:1")
        assert got.evidence_refs == ["ev1"]
