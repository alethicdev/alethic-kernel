"""Tests for alethic_kernel/adaptive_worker.py."""
from __future__ import annotations

from alethic_kernel.kernel import Kernel
from alethic_kernel.store import MemoryStore
from alethic_kernel.adaptive_worker import AdaptiveWorker

from tests.helpers import make_record


class TestAdaptiveWorkerAnalyze:
    def test_counts_stale_evidence(self):
        store = MemoryStore()
        for i in range(3):
            rec = make_record(rec_id=f"b:t:{i}", slot="beliefs")
            store.append(rec)
            store.invalidate(f"b:t:{i}", "Belief depends on stale percept: charge")

        w = AdaptiveWorker(failure_threshold=2)
        queued = w.analyze(store)
        assert "block_stale_actions" in queued

    def test_below_threshold_not_queued(self):
        store = MemoryStore()
        rec = make_record(rec_id="b:t:0", slot="beliefs")
        store.append(rec)
        store.invalidate("b:t:0", "Belief depends on stale percept: charge")

        w = AdaptiveWorker(failure_threshold=3)
        queued = w.analyze(store)
        assert queued == []

    def test_counts_low_confidence(self):
        store = MemoryStore()
        for i in range(2):
            rec = make_record(rec_id=f"b:t:{i}", slot="beliefs")
            store.append(rec)
            store.invalidate(f"b:t:{i}", "Low confidence on percept: charge")

        w = AdaptiveWorker(failure_threshold=2)
        queued = w.analyze(store)
        assert "block_low_confidence_actions" in queued

    def test_counts_unresolved_conflict(self):
        store = MemoryStore()
        for i in range(2):
            rec = make_record(rec_id=f"b:t:{i}", slot="beliefs")
            store.append(rec)
            store.invalidate(f"b:t:{i}", "UNRESOLVED_CONFLICT")

        w = AdaptiveWorker(failure_threshold=2)
        queued = w.analyze(store)
        assert "block_conflicted_actions" in queued

    def test_counts_negative_prediction(self):
        store = MemoryStore()
        for i in range(2):
            rec = make_record(rec_id=f"a:t:{i}", slot="actions")
            store.append(rec)
            store.invalidate(f"a:t:{i}", "Prediction negative for: issue_refund")

        w = AdaptiveWorker(failure_threshold=2)
        queued = w.analyze(store)
        assert "block_negative_predictions" in queued

    def test_skips_already_emitted(self):
        store = MemoryStore()
        for i in range(3):
            rec = make_record(rec_id=f"b:t:{i}", slot="beliefs")
            store.append(rec)
            store.invalidate(f"b:t:{i}", "STALE_EVIDENCE")

        w = AdaptiveWorker(failure_threshold=2)
        w.emitted.add("block_stale_actions")
        queued = w.analyze(store)
        assert "block_stale_actions" not in queued

    def test_scans_multiple_slots(self):
        store = MemoryStore()
        # Stale in beliefs
        rec1 = make_record(rec_id="b:t:0", slot="beliefs")
        store.append(rec1)
        store.invalidate("b:t:0", "STALE_EVIDENCE")
        # Stale in actions
        rec2 = make_record(rec_id="a:t:0", slot="actions")
        store.append(rec2)
        store.invalidate("a:t:0", "STALE_EVIDENCE")

        w = AdaptiveWorker(failure_threshold=2)
        queued = w.analyze(store)
        assert "block_stale_actions" in queued


class TestAdaptiveWorkerBaseReason:
    def test_stale(self):
        assert AdaptiveWorker._base_reason("Belief depends on stale percept: x") == "STALE_EVIDENCE"

    def test_conflict(self):
        assert AdaptiveWorker._base_reason("UNRESOLVED_CONFLICT") == "UNRESOLVED_CONFLICT"

    def test_low_confidence_phrase(self):
        assert AdaptiveWorker._base_reason("Low confidence on percept: x") == "LOW_CONFIDENCE"

    def test_low_confidence_code(self):
        assert AdaptiveWorker._base_reason("LOW_CONFIDENCE") == "LOW_CONFIDENCE"

    def test_negative(self):
        assert AdaptiveWorker._base_reason("Prediction negative for: issue_refund") == "NEGATIVE_PREDICTION"

    def test_unknown_passthrough(self):
        assert AdaptiveWorker._base_reason("SOME_OTHER_REASON") == "SOME_OTHER_REASON"


class TestAdaptiveWorkerShouldActivate:
    def test_inactive_when_empty(self):
        w = AdaptiveWorker()
        assert w.should_activate({}) is False

    def test_active_after_analyze(self):
        store = MemoryStore()
        for i in range(2):
            rec = make_record(rec_id=f"b:t:{i}", slot="beliefs")
            store.append(rec)
            store.invalidate(f"b:t:{i}", "STALE_EVIDENCE")

        w = AdaptiveWorker(failure_threshold=2)
        w.analyze(store)
        assert w.should_activate({}) is True


class TestAdaptiveWorkerStep:
    def test_commits_constraint(self):
        k = Kernel()
        store = MemoryStore()
        for i in range(2):
            rec = make_record(rec_id=f"b:t:{i}", slot="beliefs")
            store.append(rec)
            store.invalidate(f"b:t:{i}", "STALE_EVIDENCE")

        w = AdaptiveWorker(failure_threshold=2)
        w.analyze(store)
        produced = w.step(k, "t1", {})
        assert produced is True

        view = k.current_view("t1")
        assert "block_stale_actions" in view["constraints"]
        c = view["constraints"]["block_stale_actions"]
        assert c["enabled"] is True
        assert c["blocks_field"] == "uses_stale_data"
        assert c["source"] == "adaptive"

    def test_emitted_set_updated(self):
        store = MemoryStore()
        for i in range(2):
            rec = make_record(rec_id=f"b:t:{i}", slot="beliefs")
            store.append(rec)
            store.invalidate(f"b:t:{i}", "STALE_EVIDENCE")

        w = AdaptiveWorker(failure_threshold=2)
        w.analyze(store)
        w.step(Kernel(), "t1", {})
        assert "block_stale_actions" in w.emitted

    def test_step_clears_queue(self):
        store = MemoryStore()
        for i in range(2):
            rec = make_record(rec_id=f"b:t:{i}", slot="beliefs")
            store.append(rec)
            store.invalidate(f"b:t:{i}", "STALE_EVIDENCE")

        w = AdaptiveWorker(failure_threshold=2)
        w.analyze(store)
        w.step(Kernel(), "t1", {})
        assert w.should_activate({}) is False

    def test_step_no_queue_returns_false(self):
        w = AdaptiveWorker()
        assert w.step(Kernel(), "t1", {}) is False

    def test_persistent_scope(self):
        k = Kernel()
        store = MemoryStore()
        for i in range(2):
            rec = make_record(rec_id=f"b:t:{i}", slot="beliefs")
            store.append(rec)
            store.invalidate(f"b:t:{i}", "STALE_EVIDENCE")

        w = AdaptiveWorker(failure_threshold=2)
        w.analyze(store)
        w.step(k, "t1", {})

        # Constraint should be persistent
        recs = k.store.list_slot("constraints")
        constraint_rec = [r for r in recs if r.kind == "block_stale_actions"]
        assert len(constraint_rec) == 1
        assert constraint_rec[0].scope == "persistent"
