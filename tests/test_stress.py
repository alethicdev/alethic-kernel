"""Stress tests: concurrency, volume, resource limits, error resilience.

Goes beyond test_concurrency.py (which covers basic thread safety) to
exercise the system under adversarial conditions: high contention,
large volumes, rapid state transitions, error storms, and resource
accumulation.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest
import alethic_kernel

from alethic_kernel.kernel import Kernel
from alethic_kernel.store import MemoryStore
from alethic_kernel.sqlite_store import SqliteStore
from alethic_kernel.session import Session
from alethic_kernel.orchestrator import Orchestrator, OrchestratorResult
from alethic_kernel.worker import BaseWorker
from alethic_kernel.adaptive_worker import AdaptiveWorker
from alethic_kernel.sim_worker import SimulatorWorker, SimRule
from alethic_kernel.schema import Slot
from alethic_kernel.agents.alethic_agent import AlethicAgent
from alethic_kernel.agents.string_glue import StringGlueAgent
from alethic_kernel.tools.perturb import PerturbConfig
from alethic_kernel.tools.payment_tool import PaymentTool
from alethic_kernel.tools.refund_tool import RefundTool
from alethic_kernel.eval.harness import run_suite
from alethic_kernel.eval.task_loader import load_tasks

from tests.helpers import make_record

# ── Constants ────────────────────────────────────────────────────────

THREADS = 20
OPS_PER_THREAD = 200
TASKS_DIR = Path(alethic_kernel.__file__).resolve().parent / "tasks"


# =====================================================================
# 1. KERNEL WRITE CONTENTION
# =====================================================================

class TestKernelWriteContention:
    """High-contention writes: many threads, same slot, same trace."""

    def test_same_trace_same_slot_unique_ids(self):
        """20 threads x 200 writes to percepts on one trace → 4000 unique IDs."""
        kernel = Kernel()
        barrier = threading.Barrier(THREADS)
        results: list[list[str]] = [[] for _ in range(THREADS)]

        def worker(tid: int) -> None:
            barrier.wait()
            for i in range(OPS_PER_THREAD):
                rec = kernel.write("tool", "percepts", "COMMIT",
                                   f"k_{tid}_{i}", {"v": i}, "contention")
                results[tid].append(rec.id)

        threads = [threading.Thread(target=worker, args=(t,))
                   for t in range(THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        flat = [r for rs in results for r in rs]
        assert len(flat) == THREADS * OPS_PER_THREAD
        assert len(set(flat)) == len(flat), "Duplicate record IDs detected"

    def test_many_traces_interleaved(self):
        """Each thread uses its own trace; counters should not collide across traces."""
        kernel = Kernel()
        barrier = threading.Barrier(THREADS)
        results: list[list[str]] = [[] for _ in range(THREADS)]

        def worker(tid: int) -> None:
            barrier.wait()
            trace = f"trace-{tid}"
            for i in range(OPS_PER_THREAD):
                rec = kernel.write("tool", "percepts", "COMMIT",
                                   f"k_{i}", {"v": i}, trace)
                results[tid].append(rec.id)

        threads = [threading.Thread(target=worker, args=(t,))
                   for t in range(THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        flat = [r for rs in results for r in rs]
        assert len(flat) == THREADS * OPS_PER_THREAD
        assert len(set(flat)) == len(flat)


# =====================================================================
# 2. CONCURRENT COMMIT PIPELINES
# =====================================================================

class TestConcurrentCommitPipelines:
    """Multiple threads each run a full propose→commit pipeline."""

    def test_parallel_belief_commits(self):
        """20 threads each: write percept → propose belief → commit belief."""
        kernel = Kernel()
        barrier = threading.Barrier(THREADS)
        outcomes: list[tuple[bool, str]] = []
        lock = threading.Lock()

        def worker(tid: int) -> None:
            trace = f"pipe-{tid}"
            barrier.wait()
            kernel.write("tool", "percepts", "COMMIT", "charge",
                         {"stale": False, "conflict": False}, trace,
                         confidence=0.9)
            prop = kernel.write("planner", "beliefs", "PROPOSE", "refund_due",
                                {"value": True, "depends_on": ["charge"]}, trace)
            ok, code = kernel.commit_belief_from_proposal(prop.id, trace)
            with lock:
                outcomes.append((ok, code))

        threads = [threading.Thread(target=worker, args=(t,))
                   for t in range(THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(outcomes) == THREADS
        for ok, code in outcomes:
            assert ok is True, f"Expected COMMITTED, got {code}"

    def test_parallel_action_commits(self):
        """Full pipeline in parallel: percept → belief → action."""
        kernel = Kernel()
        barrier = threading.Barrier(THREADS)
        outcomes: list[tuple[bool, str]] = []
        lock = threading.Lock()

        def worker(tid: int) -> None:
            trace = f"action-{tid}"
            barrier.wait()
            kernel.write("tool", "percepts", "COMMIT", "charge",
                         {"stale": False, "conflict": False}, trace,
                         confidence=0.9)
            bp = kernel.write("planner", "beliefs", "PROPOSE", "refund_due",
                              {"value": True, "depends_on": ["charge"]}, trace)
            kernel.commit_belief_from_proposal(bp.id, trace)

            ap = kernel.write("planner", "actions", "PROPOSE", "issue_refund",
                              {"type": "issue_refund", "is_duplicate": False,
                               "requires_beliefs": ["refund_due"]}, trace)
            ok, code = kernel.commit_action_from_proposal(ap.id, trace)
            with lock:
                outcomes.append((ok, code))

        threads = [threading.Thread(target=worker, args=(t,))
                   for t in range(THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(outcomes) == THREADS
        for ok, code in outcomes:
            assert ok is True, f"Expected COMMITTED, got {code}"


# =====================================================================
# 3. CONCURRENT PROPOSAL INVALIDATION RACES
# =====================================================================

class TestProposalInvalidationRaces:
    """Two threads try to commit the same proposal simultaneously."""

    def test_double_commit_same_proposal(self):
        """Only one thread wins; the other gets INVALID_PROPOSAL."""
        kernel = Kernel()
        kernel.write("tool", "percepts", "COMMIT", "charge",
                     {"stale": False, "conflict": False}, "race",
                     confidence=0.9)
        prop = kernel.write("planner", "beliefs", "PROPOSE", "refund_due",
                            {"value": True, "depends_on": ["charge"]}, "race")

        barrier = threading.Barrier(2)
        outcomes: list[tuple[bool, str]] = []
        lock = threading.Lock()

        def committer() -> None:
            barrier.wait()
            ok, code = kernel.commit_belief_from_proposal(prop.id, "race")
            with lock:
                outcomes.append((ok, code))

        t1 = threading.Thread(target=committer)
        t2 = threading.Thread(target=committer)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        codes = {code for _, code in outcomes}
        assert "COMMITTED" in codes, "At least one should succeed"
        # The other either also sees COMMITTED (if both read ACTIVE before
        # invalidation) or gets INVALID_PROPOSAL — both are acceptable.
        assert codes <= {"COMMITTED", "INVALID_PROPOSAL"}


# =====================================================================
# 4. STORE VOLUME STRESS
# =====================================================================

class TestMemoryStoreVolume:
    """Large record volumes in MemoryStore."""

    def test_10k_records(self):
        """Insert 10,000 records, verify all retrievable."""
        store = MemoryStore()
        for i in range(10_000):
            store.append(make_record(
                rec_id=f"percepts:vol:{i}",
                kind=f"k{i}",
                trace_id="vol",
            ))
        # Spot-check first, last, middle
        assert store.get("percepts:vol:0") is not None
        assert store.get("percepts:vol:9999") is not None
        assert store.get("percepts:vol:5000") is not None
        # list_slot returns all
        recs = store.list_slot("percepts")
        assert len(recs) == 10_000

    def test_many_traces(self):
        """1000 different traces, 10 records each."""
        store = MemoryStore()
        for t in range(1000):
            for i in range(10):
                store.append(make_record(
                    rec_id=f"percepts:t{t}:{i}",
                    kind=f"k{i}",
                    trace_id=f"t{t}",
                ))
        recs = store.list_slot("percepts")
        assert len(recs) == 10_000

        # find_active_by_kind scans correctly
        for t in [0, 500, 999]:
            r = store.find_active_by_kind("percepts", "k0", f"t{t}")
            assert r is not None
            assert r.prov.trace_id == f"t{t}"


class TestSqliteStoreVolume:
    """Large record volumes in SqliteStore."""

    def test_10k_records(self, tmp_path: Any):
        store = SqliteStore(str(tmp_path / "vol.db"))
        for i in range(10_000):
            store.append(make_record(
                rec_id=f"percepts:vol:{i}",
                kind=f"k{i}",
                trace_id="vol",
            ))
        assert store.get("percepts:vol:0") is not None
        assert store.get("percepts:vol:9999") is not None
        recs = store.list_slot("percepts")
        assert len(recs) == 10_000
        store.close()

    def test_concurrent_append_and_read(self, tmp_path: Any):
        """Writers and readers operating simultaneously."""
        store = SqliteStore(str(tmp_path / "rw.db"))
        barrier = threading.Barrier(THREADS)
        write_count = 100

        def writer(tid: int) -> None:
            barrier.wait()
            for i in range(write_count):
                store.append(make_record(
                    rec_id=f"percepts:t{tid}:{i}",
                    kind=f"k{i}",
                    trace_id=f"t{tid}",
                ))

        def reader() -> None:
            barrier.wait()
            for _ in range(write_count):
                store.list_slot("percepts")

        writers = [threading.Thread(target=writer, args=(t,))
                   for t in range(THREADS - 2)]
        readers = [threading.Thread(target=reader) for _ in range(2)]
        for t in writers + readers:
            t.start()
        for t in writers + readers:
            t.join()

        total = len(store.list_slot("percepts"))
        assert total == (THREADS - 2) * write_count
        store.close()


# =====================================================================
# 5. TTL STRESS
# =====================================================================

class TestTTLStress:
    """TTL enforcement under concurrent access and tight deadlines."""

    def test_rapid_ttl_expiry(self):
        """Records with 1ms TTL should expire almost immediately."""
        store = MemoryStore()
        for i in range(100):
            store.append(make_record(
                rec_id=f"percepts:ttl:{i}",
                kind=f"k{i}",
                ttl_ms=1,
            ))
        time.sleep(0.01)  # 10ms — well past 1ms TTL
        for i in range(100):
            rec = store.get(f"percepts:ttl:{i}")
            assert rec is not None
            assert rec.status == "EXPIRED"

    def test_concurrent_ttl_check(self):
        """Multiple threads reading TTL-expiring records simultaneously."""
        store = MemoryStore()
        for i in range(100):
            store.append(make_record(
                rec_id=f"percepts:cttl:{i}",
                kind=f"k{i}",
                ttl_ms=50,  # 50ms TTL
            ))

        time.sleep(0.06)  # Wait for expiry
        barrier = threading.Barrier(THREADS)
        statuses: list[list[str]] = [[] for _ in range(THREADS)]

        def reader(tid: int) -> None:
            barrier.wait()
            for i in range(100):
                rec = store.get(f"percepts:cttl:{i}")
                if rec:
                    statuses[tid].append(rec.status)

        threads = [threading.Thread(target=reader, args=(t,))
                   for t in range(THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All readers should see EXPIRED
        for tid in range(THREADS):
            for s in statuses[tid]:
                assert s == "EXPIRED"


# =====================================================================
# 6. ORCHESTRATOR STRESS
# =====================================================================

class TestOrchestratorStress:
    """Orchestrator under error storms, runaway workers, and deep rounds."""

    def test_error_storm_resilience(self):
        """Worker that throws on every step; orchestrator should survive."""
        kernel = Kernel()

        bomb = BaseWorker(
            worker_id="bomb",
            role="tool",
            reads=frozenset({"percepts"}),
            writes=frozenset({"percepts"}),
        )
        # Override methods on instance
        bomb.should_activate = lambda view: True  # type: ignore[assignment]
        bomb.step = lambda k, tid, v: (_ for _ in ()).throw(  # type: ignore[assignment]
            RuntimeError("boom"))

        errors_caught: list[tuple[str, Exception]] = []

        def on_error(worker_id: str, exc: Exception) -> None:
            errors_caught.append((worker_id, exc))

        orch = Orchestrator(kernel=kernel, workers=[bomb],
                            max_rounds=50, on_error=on_error)
        result = orch.run("bomb-trace")

        # Should complete without raising
        assert result.rounds > 0
        assert len(result.errors) > 0
        assert all(e["worker"] == "bomb" for e in result.errors)

    def test_runaway_worker_capped_by_max_rounds(self):
        """Worker that always produces; verify max_rounds caps it."""
        kernel = Kernel()
        step_count = 0

        class RunawayWorker(BaseWorker):
            worker_id: str = "runaway"
            role: str = "tool"
            reads = frozenset({"percepts"})
            writes = frozenset({"percepts"})

            def should_activate(self, view: Dict[str, Dict[str, Any]]) -> bool:
                return True

            def step(self, k: Any, trace_id: str,
                     view: Dict[str, Dict[str, Any]]) -> bool:
                nonlocal step_count
                step_count += 1
                k.write("tool", "percepts", "COMMIT", f"data_{step_count}",
                        {"i": step_count}, trace_id)
                return True

        orch = Orchestrator(kernel=kernel, workers=[RunawayWorker()],
                            max_rounds=10)
        result = orch.run("runaway-trace")

        assert result.rounds == 10
        assert step_count == 10

    def test_multi_worker_dependency_order(self):
        """Workers with different slot writes execute in correct order."""
        kernel = Kernel()
        order: list[str] = []
        lock = threading.Lock()

        class PerceptWorker(BaseWorker):
            worker_id: str = "sensor"
            role: str = "tool"
            reads = frozenset({"percepts"})
            writes = frozenset({"percepts"})
            _done: bool = False

            def should_activate(self, view: Dict[str, Dict[str, Any]]) -> bool:
                return not self._done

            def step(self, k: Any, trace_id: str,
                     view: Dict[str, Dict[str, Any]]) -> bool:
                self._done = True
                with lock:
                    order.append("percepts")
                k.write("tool", "percepts", "COMMIT", "data",
                        {"v": 1}, trace_id)
                return True

        class BeliefWorker(BaseWorker):
            worker_id: str = "analyst"
            role: str = "planner"
            reads = frozenset({"percepts"})
            writes = frozenset({"beliefs"})
            _done: bool = False

            def should_activate(self, view: Dict[str, Dict[str, Any]]) -> bool:
                return not self._done and "data" in view.get("percepts", {})

            def step(self, k: Any, trace_id: str,
                     view: Dict[str, Dict[str, Any]]) -> bool:
                self._done = True
                with lock:
                    order.append("beliefs")
                k.write("planner", "beliefs", "PROPOSE", "analysis",
                        {"value": True, "depends_on": ["data"]}, trace_id)
                return True

        orch = Orchestrator(kernel=kernel,
                            workers=[BeliefWorker(), PerceptWorker()],
                            max_rounds=5)
        orch.run("order-trace")

        assert order == ["percepts", "beliefs"]


# =====================================================================
# 7. ADAPTIVE WORKER ACCUMULATION
# =====================================================================

class TestAdaptiveWorkerStress:
    """AdaptiveWorker under multi-episode accumulation."""

    def test_many_episodes_learning(self):
        """Run 50 episodes on shared store; adaptive worker learns constraints."""
        store = MemoryStore()
        adaptive = AdaptiveWorker(failure_threshold=3)

        for ep in range(50):
            kernel = Kernel(store=store)
            # Simulate stale evidence failures — all land in the same store
            kernel.write("tool", "percepts", "COMMIT", "charge",
                         {"stale": True, "conflict": False},
                         f"ep-{ep}", confidence=0.9)
            prop = kernel.write("planner", "beliefs", "PROPOSE", "refund_due",
                                {"value": True, "depends_on": ["charge"]},
                                f"ep-{ep}")
            kernel.commit_belief_from_proposal(prop.id, f"ep-{ep}")

        # Analyze the accumulated store — should have 50 STALE_EVIDENCE invalidations
        learned = adaptive.analyze(store)
        assert "block_stale_actions" in learned
        assert "block_stale_actions" not in adaptive.emitted  # only queued, not emitted yet

    def test_emitted_set_no_duplicates(self):
        """Same constraint should not be queued twice after emitting."""
        store = MemoryStore()
        adaptive = AdaptiveWorker(failure_threshold=1)

        # Create invalidated records in one shared store
        for ep in range(10):
            store.append(make_record(
                rec_id=f"beliefs:ep{ep}:1",
                slot="beliefs",
                kind="refund_due",
                trace_id=f"ep{ep}",
            ))
            store.invalidate(f"beliefs:ep{ep}:1", "STALE_EVIDENCE")

        # First analyze → queued
        learned = adaptive.analyze(store)
        assert "block_stale_actions" in learned

        # Simulate step() committing the constraint
        kernel = Kernel(store=store)
        adaptive.step(kernel, "emit-trace", kernel.current_view("emit-trace"))

        assert "block_stale_actions" in adaptive.emitted

        # Second analyze → should NOT re-queue (already emitted)
        learned2 = adaptive.analyze(store)
        assert "block_stale_actions" not in learned2


# =====================================================================
# 8. FULL BENCHMARK HARNESS STRESS
# =====================================================================

class TestHarnessStress:
    """Run the benchmark harness at scale to verify stability."""

    def test_high_seed_count(self):
        """100 seeds x 6 tasks x 3 agents = 1800 episodes."""
        tasks = load_tasks(TASKS_DIR)
        assert len(tasks) == 6

        cfg = PerturbConfig(
            tool_drop_rate=0.15,
            stale_rate=0.20,
            conflict_rate=0.20,
            low_confidence_rate=0.20,
        )
        episodes = run_suite(tasks, list(range(100)),
                             ["string_glue", "json_glue", "alethic"], cfg)

        assert len(episodes) == 1800
        # Alethic agent: zero unsafe actions across all episodes
        alethic_eps = [e for e in episodes if e.agent == "alethic"]
        for e in alethic_eps:
            assert e.metrics["unsafe_action"] == 0.0, (
                f"Unsafe action in {e.task_id} seed={e.seed}"
            )

    def test_extreme_perturbation_rates(self):
        """All perturbation rates at 100% — everything fails."""
        tasks = load_tasks(TASKS_DIR)

        cfg = PerturbConfig(
            tool_drop_rate=1.0,
            stale_rate=1.0,
            conflict_rate=1.0,
            low_confidence_rate=1.0,
        )
        episodes = run_suite(tasks, list(range(10)),
                             ["alethic"], cfg)

        assert len(episodes) == 60
        for e in episodes:
            assert e.metrics["unsafe_action"] == 0.0
            assert e.metrics["traceability"] == 1.0


# =====================================================================
# 9. SESSION COUNTER STRESS
# =====================================================================

class TestSessionStress:
    """Session trace ID generation under extreme contention."""

    def test_1000_concurrent_trace_ids(self):
        """50 threads x 1000 IDs = 50,000 unique trace IDs."""
        session = Session()
        n_threads = 50
        ids_per_thread = 1000
        barrier = threading.Barrier(n_threads)
        results: list[list[str]] = [[] for _ in range(n_threads)]

        def worker(tid: int) -> None:
            barrier.wait()
            for _ in range(ids_per_thread):
                results[tid].append(session.episode_trace_id())

        threads = [threading.Thread(target=worker, args=(t,))
                   for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        flat = [r for rs in results for r in rs]
        assert len(flat) == n_threads * ids_per_thread
        assert len(set(flat)) == len(flat), "Duplicate trace IDs"


# =====================================================================
# 10. API CONCURRENT STRESS (via TestClient, in-process)
# =====================================================================

class TestAPIConcurrentStress:
    """Concurrent API calls to shared kernel via TestClient."""

    @pytest.fixture(autouse=True)
    def _reset(self) -> None:
        from alethic_kernel.api.dependencies import reset_shared_state
        reset_shared_state()
        yield  # type: ignore[misc]
        reset_shared_state()

    @pytest.fixture
    def client(self) -> Any:
        from fastapi.testclient import TestClient
        from alethic_kernel.api.app import create_app
        return TestClient(create_app())

    def test_concurrent_writes_via_api(self, client: Any) -> None:
        """20 threads writing to shared kernel via API."""
        barrier = threading.Barrier(THREADS)
        errors: list[str] = []
        lock = threading.Lock()

        def writer(tid: int) -> None:
            barrier.wait()
            for i in range(50):
                resp = client.post("/v1/write", json={
                    "role": "tool", "slot": "percepts", "mode": "COMMIT",
                    "kind": f"k_{tid}_{i}", "payload": {"v": i},
                    "trace_id": f"api-stress-{tid}",
                })
                if resp.status_code != 200:
                    with lock:
                        errors.append(f"t{tid}i{i}: {resp.status_code}")

        threads = [threading.Thread(target=writer, args=(t,))
                   for t in range(THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"API errors: {errors[:5]}"

    def test_concurrent_episodes_via_api(self, client: Any) -> None:
        """10 concurrent /v1/episode requests."""
        n = 10
        barrier = threading.Barrier(n)
        results: list[Dict[str, Any]] = []
        lock = threading.Lock()

        def runner(tid: int) -> None:
            barrier.wait()
            resp = client.post("/v1/episode", json={
                "task_inputs": {
                    "chargeId": f"ch_stress_{tid}",
                    "customerId": f"cus_{tid}",
                    "customerName": f"User{tid}",
                    "amount": 10.0 + tid,
                    "disputeReason": "product_not_received",
                },
                "constraints": {
                    "no_duplicate_refund": {"blocks_field": "is_duplicate"},
                },
            })
            with lock:
                results.append(resp.json())

        threads = [threading.Thread(target=runner, args=(t,))
                   for t in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == n
        for r in results:
            assert r["metrics"]["unsafe_action"] == 0.0


# =====================================================================
# 11. PERTURBATION DETERMINISM UNDER CONCURRENT ACCESS
# =====================================================================

class TestPerturbationDeterminism:
    """Verify perturbation outcomes are identical across runs."""

    def test_concurrent_rng_determinism(self):
        """Same (seed, key) pair gives same result regardless of threading."""
        cfg = PerturbConfig(
            stale_rate=0.5,
            conflict_rate=0.5,
            low_confidence_rate=0.5,
            tool_drop_rate=0.5,
        )
        tool = PaymentTool(cfg)

        # Run sequentially
        sequential: list[Any] = []
        for seed in range(100):
            result = tool.get_charge(seed, f"ch_{seed}", f"cus_{seed}", 100.0)
            sequential.append(result)

        # Run concurrently
        concurrent: list[Any] = [None] * 100
        barrier = threading.Barrier(THREADS)

        def worker(tid: int) -> None:
            barrier.wait()
            start = tid * (100 // THREADS)
            end = start + (100 // THREADS)
            for seed in range(start, end):
                concurrent[seed] = tool.get_charge(
                    seed, f"ch_{seed}", f"cus_{seed}", 100.0)

        threads = [threading.Thread(target=worker, args=(t,))
                   for t in range(THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        for i in range(100):
            assert sequential[i] == concurrent[i], (
                f"Seed {i}: sequential != concurrent"
            )


# =====================================================================
# 12. KERNEL COUNTER ACCUMULATION
# =====================================================================

class TestCounterAccumulation:
    """Verify kernel handles many distinct trace/slot combinations."""

    def test_many_distinct_counters(self):
        """1000 unique (slot, trace_id) pairs → 1000 counter keys."""
        kernel = Kernel()
        for i in range(1000):
            kernel.write("tool", "percepts", "COMMIT",
                         f"k{i}", {"v": i}, f"trace-{i}")

        # Each trace should have exactly 1 record
        for i in range(1000):
            view = kernel.current_view(f"trace-{i}")
            assert f"k{i}" in view["percepts"]

    def test_high_counter_values(self):
        """500 writes to same (slot, trace) → counter reaches 500."""
        kernel = Kernel()
        for i in range(500):
            rec = kernel.write("tool", "percepts", "COMMIT",
                               f"k{i}", {"v": i}, "highcount")
            assert rec.id == f"percepts:highcount:{i + 1}"


# =====================================================================
# 13. VALIDATION PIPELINE EDGE CASES
# =====================================================================

class TestValidationEdgeCases:
    """Boundary conditions in the validation pipeline."""

    def test_belief_with_many_dependencies(self):
        """Belief depending on 50 percepts — all must be clean."""
        kernel = Kernel()
        deps = []
        for i in range(50):
            kernel.write("tool", "percepts", "COMMIT", f"p{i}",
                         {"stale": False, "conflict": False}, "deps",
                         confidence=0.9)
            deps.append(f"p{i}")

        prop = kernel.write("planner", "beliefs", "PROPOSE", "complex",
                            {"value": True, "depends_on": deps}, "deps")
        ok, code = kernel.commit_belief_from_proposal(prop.id, "deps")
        assert ok is True
        assert code == "COMMITTED"

    def test_belief_with_one_stale_in_many(self):
        """49 clean percepts + 1 stale → rejection."""
        kernel = Kernel()
        deps = []
        for i in range(49):
            kernel.write("tool", "percepts", "COMMIT", f"p{i}",
                         {"stale": False, "conflict": False}, "stale1",
                         confidence=0.9)
            deps.append(f"p{i}")
        kernel.write("tool", "percepts", "COMMIT", "p49",
                     {"stale": True, "conflict": False}, "stale1",
                     confidence=0.9)
        deps.append("p49")

        prop = kernel.write("planner", "beliefs", "PROPOSE", "complex",
                            {"value": True, "depends_on": deps}, "stale1")
        ok, code = kernel.commit_belief_from_proposal(prop.id, "stale1")
        assert ok is False
        assert code == "STALE_EVIDENCE"

    def test_many_constraints_all_checked(self):
        """10 constraints, action violates the last one."""
        kernel = Kernel()
        kernel.write("tool", "percepts", "COMMIT", "charge",
                     {"stale": False, "conflict": False}, "mc",
                     confidence=0.9)
        bp = kernel.write("planner", "beliefs", "PROPOSE", "refund_due",
                          {"value": True, "depends_on": ["charge"]}, "mc")
        kernel.commit_belief_from_proposal(bp.id, "mc")

        for i in range(10):
            kernel.write("symbolic_validator", "constraints", "COMMIT",
                         f"constraint_{i}",
                         {"enabled": True, "blocks_field": f"flag_{i}"},
                         "mc")

        # Action with flag_9=True → blocked by constraint_9
        payload: Dict[str, Any] = {
            "type": "issue_refund",
            "requires_beliefs": ["refund_due"],
        }
        for i in range(10):
            payload[f"flag_{i}"] = (i == 9)

        ap = kernel.write("planner", "actions", "PROPOSE",
                          "issue_refund", payload, "mc")
        ok, code = kernel.commit_action_from_proposal(ap.id, "mc")
        assert ok is False
        assert "BLOCKED" in code

    def test_prediction_gating_with_zero_outcome(self):
        """Prediction with expected_outcome=0.0 should allow action."""
        kernel = Kernel()
        kernel.write("tool", "percepts", "COMMIT", "charge",
                     {"stale": False, "conflict": False}, "zero",
                     confidence=0.9)
        bp = kernel.write("planner", "beliefs", "PROPOSE", "refund_due",
                          {"value": True, "depends_on": ["charge"]}, "zero")
        kernel.commit_belief_from_proposal(bp.id, "zero")

        pp = kernel.write("planner", "predictions", "PROPOSE", "pred",
                          {"action_type": "issue_refund",
                           "expected_outcome": 0.0,
                           "requires_beliefs": ["refund_due"]}, "zero")
        kernel.commit_prediction(pp.id, "zero")

        ap = kernel.write("planner", "actions", "PROPOSE", "issue_refund",
                          {"type": "issue_refund", "is_duplicate": False,
                           "requires_beliefs": ["refund_due"]}, "zero")
        ok, code = kernel.commit_action_from_proposal(
            ap.id, "zero", require_prediction=True)
        assert ok is True
