from __future__ import annotations
import threading
from contextlib import contextmanager
from typing import Callable, Dict, Iterator, List, Optional
import time
from .schema import Record, RecordIdConflict, Slot

class MemoryStore:
    def __init__(self) -> None:
        self._records: Dict[str, Record] = {}
        self._by_slot: Dict[str, List[str]] = {}
        self._lock = threading.RLock()
        self._tx_depth = 0
        self._undo: List[Callable[[], None]] = []

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Undo any writes made in this block if it does not complete.

        SqliteStore rolls back; this store must too, or the same interruption
        leaves different state depending on which backend is configured.
        """
        with self._lock:
            self._tx_depth += 1
            mark = len(self._undo)
            try:
                yield
            except BaseException:
                if self._tx_depth == 1:
                    for undo in reversed(self._undo[mark:]):
                        undo()
                    del self._undo[mark:]
                raise
            finally:
                self._tx_depth -= 1
                if self._tx_depth == 0:
                    self._undo.clear()

    def _record_undo(self, undo: Callable[[], None]) -> None:
        if self._tx_depth > 0:
            self._undo.append(undo)

    def _check_ttl(self, rec: Record) -> None:
        if rec.status == "ACTIVE" and rec.prov.ttl_ms is not None:
            now = int(time.time() * 1000)
            if now >= rec.prov.ts_ms + rec.prov.ttl_ms:
                rec.status = "EXPIRED"
                rec.reason = "TTL_EXPIRED"

    def append(self, rec: Record) -> None:
        with self._lock:
            if rec.id in self._records:
                raise RecordIdConflict(rec.id)
            self._records[rec.id] = rec
            self._by_slot.setdefault(rec.slot, []).append(rec.id)

            def undo() -> None:
                self._records.pop(rec.id, None)
                ids = self._by_slot.get(rec.slot)
                if ids and rec.id in ids:
                    ids.remove(rec.id)
            self._record_undo(undo)

    def get(self, rec_id: str) -> Optional[Record]:
        with self._lock:
            r = self._records.get(rec_id)
            if r:
                self._check_ttl(r)
            return r

    def list_slot(self, slot: Slot) -> List[Record]:
        with self._lock:
            recs = [self._records[i] for i in self._by_slot.get(slot, [])]
            for r in recs:
                self._check_ttl(r)
            return recs

    def find_active_by_kind(self, slot: Slot, kind: str, trace_id: str) -> Optional[Record]:
        with self._lock:
            for rid in self._by_slot.get(slot, []):
                r = self._records[rid]
                self._check_ttl(r)
                if r.kind == kind and r.prov.trace_id == trace_id and r.status == "ACTIVE":
                    return r
            return None

    def invalidate(self, rec_id: str, reason: str) -> None:
        with self._lock:
            r = self._records.get(rec_id)
            if r:
                prev_status, prev_reason = r.status, r.reason

                def undo() -> None:
                    r.status = prev_status
                    r.reason = prev_reason
                self._record_undo(undo)
                r.status = "INVALIDATED"
                r.reason = reason

    def close(self) -> None:
        pass
