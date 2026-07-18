from __future__ import annotations

import time
import pytest

from alethic_kernel.store import MemoryStore
from alethic_kernel.schema import Record, Provenance

from tests.helpers import make_record


class TestMemoryStoreAppendAndGet:
    def test_append_and_get(self, memory_store: MemoryStore):
        rec = make_record(rec_id="p:t:1")
        memory_store.append(rec)
        assert memory_store.get("p:t:1") is rec

    def test_get_missing_returns_none(self, memory_store: MemoryStore):
        assert memory_store.get("nonexistent") is None

    def test_multiple_records(self, memory_store: MemoryStore):
        r1 = make_record(rec_id="p:t:1", kind="charge")
        r2 = make_record(rec_id="p:t:2", kind="invoice")
        memory_store.append(r1)
        memory_store.append(r2)
        assert memory_store.get("p:t:1") is r1
        assert memory_store.get("p:t:2") is r2


class TestMemoryStoreListSlot:
    def test_list_slot_empty(self, memory_store: MemoryStore):
        assert memory_store.list_slot("percepts") == []

    def test_list_slot_returns_records(self, memory_store: MemoryStore):
        r1 = make_record(rec_id="p:t:1", slot="percepts")
        r2 = make_record(rec_id="b:t:1", slot="beliefs")
        memory_store.append(r1)
        memory_store.append(r2)
        percepts = memory_store.list_slot("percepts")
        assert len(percepts) == 1
        assert percepts[0] is r1

    def test_list_slot_multiple(self, memory_store: MemoryStore):
        r1 = make_record(rec_id="p:t:1", slot="percepts", kind="charge")
        r2 = make_record(rec_id="p:t:2", slot="percepts", kind="invoice")
        memory_store.append(r1)
        memory_store.append(r2)
        assert len(memory_store.list_slot("percepts")) == 2


class TestMemoryStoreFindActiveByKind:
    def test_find_active(self, memory_store: MemoryStore):
        rec = make_record(rec_id="p:t:1", kind="charge", trace_id="t1")
        memory_store.append(rec)
        found = memory_store.find_active_by_kind("percepts", "charge", "t1")
        assert found is rec

    def test_find_returns_none_for_wrong_kind(self, memory_store: MemoryStore):
        rec = make_record(rec_id="p:t:1", kind="charge", trace_id="t1")
        memory_store.append(rec)
        assert memory_store.find_active_by_kind("percepts", "invoice", "t1") is None

    def test_find_returns_none_for_wrong_trace(self, memory_store: MemoryStore):
        rec = make_record(rec_id="p:t:1", kind="charge", trace_id="t1")
        memory_store.append(rec)
        assert memory_store.find_active_by_kind("percepts", "charge", "t2") is None

    def test_find_skips_invalidated(self, memory_store: MemoryStore):
        rec = make_record(rec_id="p:t:1", kind="charge", trace_id="t1")
        memory_store.append(rec)
        memory_store.invalidate("p:t:1", "test reason")
        assert memory_store.find_active_by_kind("percepts", "charge", "t1") is None


class TestMemoryStoreInvalidate:
    def test_invalidate(self, memory_store: MemoryStore):
        rec = make_record(rec_id="p:t:1")
        memory_store.append(rec)
        memory_store.invalidate("p:t:1", "test reason")
        got = memory_store.get("p:t:1")
        assert got.status == "INVALIDATED"
        assert got.reason == "test reason"

    def test_invalidate_nonexistent_is_noop(self, memory_store: MemoryStore):
        memory_store.invalidate("nonexistent", "reason")


class TestMemoryStoreTTL:
    def test_ttl_not_expired(self, memory_store: MemoryStore):
        rec = make_record(rec_id="p:t:1", ttl_ms=60000)
        memory_store.append(rec)
        got = memory_store.get("p:t:1")
        assert got.status == "ACTIVE"

    def test_ttl_expired(self, memory_store: MemoryStore):
        rec = make_record(rec_id="p:t:1", ttl_ms=1)
        rec.prov.ts_ms = int(time.time() * 1000) - 1000
        memory_store.append(rec)
        got = memory_store.get("p:t:1")
        assert got.status == "EXPIRED"
        assert got.reason == "TTL_EXPIRED"

    def test_ttl_checked_on_list_slot(self, memory_store: MemoryStore):
        rec = make_record(rec_id="p:t:1", ttl_ms=1)
        rec.prov.ts_ms = int(time.time() * 1000) - 1000
        memory_store.append(rec)
        recs = memory_store.list_slot("percepts")
        assert recs[0].status == "EXPIRED"

    def test_no_ttl_never_expires(self, memory_store: MemoryStore):
        rec = make_record(rec_id="p:t:1", ttl_ms=None)
        rec.prov.ts_ms = 0  # very old
        memory_store.append(rec)
        got = memory_store.get("p:t:1")
        assert got.status == "ACTIVE"
