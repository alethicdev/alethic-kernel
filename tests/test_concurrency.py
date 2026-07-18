"""Concurrency tests: verify thread safety of stores, kernel, and session."""
from __future__ import annotations

import threading

from alethic.kernel import Kernel
from alethic.store import MemoryStore
from alethic.sqlite_store import SqliteStore
from alethic.session import Session

from tests.helpers import make_record


NUM_THREADS = 10
RECORDS_PER_THREAD = 100


class TestMemoryStoreConcurrency:
    def test_concurrent_append(self):
        store = MemoryStore()
        barrier = threading.Barrier(NUM_THREADS)

        def worker(thread_id: int):
            barrier.wait()
            for i in range(RECORDS_PER_THREAD):
                rec = make_record(
                    rec_id=f"p:t{thread_id}:{i}",
                    kind=f"data_{thread_id}_{i}",
                    trace_id=f"t{thread_id}",
                )
                store.append(rec)

        threads = [threading.Thread(target=worker, args=(t,))
                   for t in range(NUM_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Verify all records present
        total = 0
        for tid in range(NUM_THREADS):
            for i in range(RECORDS_PER_THREAD):
                rec = store.get(f"p:t{tid}:{i}")
                assert rec is not None
                total += 1
        assert total == NUM_THREADS * RECORDS_PER_THREAD

    def test_concurrent_invalidate(self):
        store = MemoryStore()
        for i in range(NUM_THREADS * RECORDS_PER_THREAD):
            store.append(make_record(rec_id=f"p:t:{i}", kind=f"k{i}"))

        barrier = threading.Barrier(NUM_THREADS)

        def worker(thread_id: int):
            barrier.wait()
            for i in range(RECORDS_PER_THREAD):
                idx = thread_id * RECORDS_PER_THREAD + i
                store.invalidate(f"p:t:{idx}", f"reason_{thread_id}")

        threads = [threading.Thread(target=worker, args=(t,))
                   for t in range(NUM_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        for i in range(NUM_THREADS * RECORDS_PER_THREAD):
            rec = store.get(f"p:t:{i}")
            assert rec.status == "INVALIDATED"


class TestSqliteStoreConcurrency:
    def test_concurrent_append(self, tmp_path):
        store = SqliteStore(str(tmp_path / "conc.db"))
        barrier = threading.Barrier(NUM_THREADS)

        def worker(thread_id: int):
            barrier.wait()
            for i in range(RECORDS_PER_THREAD):
                rec = make_record(
                    rec_id=f"p:t{thread_id}:{i}",
                    kind=f"data_{thread_id}_{i}",
                    trace_id=f"t{thread_id}",
                )
                store.append(rec)

        threads = [threading.Thread(target=worker, args=(t,))
                   for t in range(NUM_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        total = 0
        for tid in range(NUM_THREADS):
            for i in range(RECORDS_PER_THREAD):
                rec = store.get(f"p:t{tid}:{i}")
                assert rec is not None
                total += 1
        assert total == NUM_THREADS * RECORDS_PER_THREAD
        store.close()


class TestKernelConcurrency:
    def test_concurrent_write_no_id_collisions(self):
        kernel = Kernel()
        barrier = threading.Barrier(NUM_THREADS)
        all_ids: list[list[str]] = [[] for _ in range(NUM_THREADS)]

        def worker(thread_id: int):
            barrier.wait()
            trace = f"trace-{thread_id}"
            for i in range(RECORDS_PER_THREAD):
                rec = kernel.write("tool", "percepts", "COMMIT",
                                   f"data_{i}", {"t": thread_id}, trace)
                all_ids[thread_id].append(rec.id)

        threads = [threading.Thread(target=worker, args=(t,))
                   for t in range(NUM_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All IDs should be unique within each trace
        for thread_id in range(NUM_THREADS):
            ids = all_ids[thread_id]
            assert len(ids) == RECORDS_PER_THREAD
            assert len(set(ids)) == RECORDS_PER_THREAD

    def test_concurrent_write_same_trace(self):
        kernel = Kernel()
        barrier = threading.Barrier(NUM_THREADS)
        all_ids: list[list[str]] = [[] for _ in range(NUM_THREADS)]

        def worker(thread_id: int):
            barrier.wait()
            for i in range(RECORDS_PER_THREAD):
                rec = kernel.write("tool", "percepts", "COMMIT",
                                   f"data_{thread_id}_{i}", {"t": thread_id},
                                   "shared-trace")
                all_ids[thread_id].append(rec.id)

        threads = [threading.Thread(target=worker, args=(t,))
                   for t in range(NUM_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All IDs across all threads should be unique (same trace, same slot)
        flat = [rid for ids in all_ids for rid in ids]
        assert len(flat) == NUM_THREADS * RECORDS_PER_THREAD
        assert len(set(flat)) == NUM_THREADS * RECORDS_PER_THREAD


class TestSessionConcurrency:
    def test_concurrent_trace_ids_unique(self):
        session = Session()
        barrier = threading.Barrier(NUM_THREADS)
        all_ids: list[list[str]] = [[] for _ in range(NUM_THREADS)]

        def worker(thread_id: int):
            barrier.wait()
            for _ in range(RECORDS_PER_THREAD):
                tid = session.episode_trace_id()
                all_ids[thread_id].append(tid)

        threads = [threading.Thread(target=worker, args=(t,))
                   for t in range(NUM_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        flat = [tid for ids in all_ids for tid in ids]
        assert len(flat) == NUM_THREADS * RECORDS_PER_THREAD
        assert len(set(flat)) == NUM_THREADS * RECORDS_PER_THREAD

    def test_concurrent_counter_no_gaps(self):
        session = Session()
        barrier = threading.Barrier(NUM_THREADS)
        counters: list[list[int]] = [[] for _ in range(NUM_THREADS)]

        def worker(thread_id: int):
            barrier.wait()
            for _ in range(RECORDS_PER_THREAD):
                tid = session.episode_trace_id()
                # Extract counter from trace_id: "session-epN-random"
                ep_part = tid.split("-")[1]
                n = int(ep_part.replace("ep", ""))
                counters[thread_id].append(n)

        threads = [threading.Thread(target=worker, args=(t,))
                   for t in range(NUM_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        flat = sorted(c for cs in counters for c in cs)
        expected = list(range(1, NUM_THREADS * RECORDS_PER_THREAD + 1))
        assert flat == expected
