"""Comprehensive tests for alethic/kernel.py — every public method, every code path."""
from __future__ import annotations

import pytest

from alethic.kernel import Kernel
from alethic.store import MemoryStore


class TestKernelWrite:
    def test_permission_granted(self, kernel: Kernel, trace_id: str):
        rec = kernel.write("tool", "percepts", "COMMIT", "charge",
                           {"amount": 100}, trace_id)
        assert rec.slot == "percepts"
        assert rec.mode == "COMMIT"
        assert rec.kind == "charge"
        assert rec.payload == {"amount": 100}
        assert rec.status == "ACTIVE"

    def test_permission_denied(self, kernel: Kernel, trace_id: str):
        with pytest.raises(PermissionError, match="tool.*COMMIT.*beliefs"):
            kernel.write("tool", "beliefs", "COMMIT", "x", {}, trace_id)

    def test_planner_cannot_commit_beliefs(self, kernel: Kernel, trace_id: str):
        with pytest.raises(PermissionError):
            kernel.write("planner", "beliefs", "COMMIT", "x", {}, trace_id)

    def test_ids_increment(self, kernel: Kernel, trace_id: str):
        r1 = kernel.write("tool", "percepts", "COMMIT", "c1", {}, trace_id)
        r2 = kernel.write("tool", "percepts", "COMMIT", "c2", {}, trace_id)
        assert r1.id == f"percepts:{trace_id}:1"
        assert r2.id == f"percepts:{trace_id}:2"

    def test_ids_independent_per_slot(self, kernel: Kernel, trace_id: str):
        r1 = kernel.write("tool", "percepts", "COMMIT", "c", {}, trace_id)
        r2 = kernel.write("planner", "beliefs", "PROPOSE", "b", {}, trace_id)
        assert "percepts" in r1.id
        assert "beliefs" in r2.id
        assert r1.id.endswith(":1")
        assert r2.id.endswith(":1")

    def test_ttl_flows_through(self, kernel: Kernel, trace_id: str):
        rec = kernel.write("tool", "percepts", "COMMIT", "c", {},
                           trace_id, ttl_ms=5000)
        assert rec.prov.ttl_ms == 5000

    def test_confidence_flows_through(self, kernel: Kernel, trace_id: str):
        rec = kernel.write("tool", "percepts", "COMMIT", "c", {},
                           trace_id, confidence=0.8)
        assert rec.prov.confidence == 0.8

    def test_scope_flows_through(self, kernel: Kernel, trace_id: str):
        rec = kernel.write("symbolic_validator", "constraints", "COMMIT",
                           "c", {}, trace_id, scope="persistent")
        assert rec.scope == "persistent"

    def test_input_refs_flow_through(self, kernel: Kernel, trace_id: str):
        rec = kernel.write("tool", "percepts", "COMMIT", "c", {},
                           trace_id, input_refs=["ref1"])
        assert rec.prov.input_refs == ["ref1"]

    def test_evidence_refs_flow_through(self, kernel: Kernel, trace_id: str):
        rec = kernel.write("tool", "percepts", "COMMIT", "c", {},
                           trace_id, evidence_refs=["ev1"])
        assert rec.evidence_refs == ["ev1"]

    def test_record_stored(self, kernel: Kernel, trace_id: str):
        rec = kernel.write("tool", "percepts", "COMMIT", "c", {}, trace_id)
        got = kernel.store.get(rec.id)
        assert got is not None
        assert got.id == rec.id


class TestKernelCurrentView:
    def test_empty_view(self, kernel: Kernel, trace_id: str):
        view = kernel.current_view(trace_id)
        assert set(view.keys()) == {
            "percepts", "beliefs", "constraints", "plans",
            "evidence", "predictions", "actions",
        }
        for v in view.values():
            assert v == {}

    def test_committed_records_in_view(self, kernel: Kernel, trace_id: str):
        kernel.write("tool", "percepts", "COMMIT", "charge",
                     {"amount": 100}, trace_id)
        view = kernel.current_view(trace_id)
        assert "charge" in view["percepts"]
        assert view["percepts"]["charge"] == {"amount": 100}

    def test_proposals_in_view(self, kernel: Kernel, trace_id: str):
        kernel.write("planner", "beliefs", "PROPOSE", "refund_due",
                     {"value": True}, trace_id)
        view = kernel.current_view(trace_id)
        assert "_proposals" in view["beliefs"]
        assert view["beliefs"]["_proposals"][0]["kind"] == "refund_due"

    def test_different_trace_id_not_visible(self, kernel: Kernel):
        kernel.write("tool", "percepts", "COMMIT", "charge",
                     {"amount": 100}, "trace-A")
        view = kernel.current_view("trace-B")
        assert view["percepts"] == {}

    def test_persistent_scope_visible_with_flag(self, kernel: Kernel, trace_id: str):
        kernel.write("symbolic_validator", "constraints", "COMMIT",
                     "c1", {"enabled": True}, "other-trace", scope="persistent")
        view = kernel.current_view(trace_id, include_persistent=True)
        assert "c1" in view["constraints"]

    def test_persistent_scope_hidden_without_flag(self, kernel: Kernel, trace_id: str):
        kernel.write("symbolic_validator", "constraints", "COMMIT",
                     "c1", {"enabled": True}, "other-trace", scope="persistent")
        view = kernel.current_view(trace_id, include_persistent=False)
        assert "c1" not in view["constraints"]

    def test_invalidated_records_not_in_view(self, kernel: Kernel, trace_id: str):
        rec = kernel.write("tool", "percepts", "COMMIT", "charge",
                           {"amount": 100}, trace_id)
        kernel.store.invalidate(rec.id, "test")
        view = kernel.current_view(trace_id)
        assert "charge" not in view["percepts"]


class TestCommitBeliefFromProposal:
    """Tests for kernel.commit_belief_from_proposal()."""

    def _setup_clean_belief(self, kernel: Kernel, trace_id: str):
        """Helper: commit clean percept, propose belief."""
        kernel.write("tool", "percepts", "COMMIT", "charge",
                     {"stale": False, "conflict": False, "amount": 100},
                     trace_id)
        prop = kernel.write("planner", "beliefs", "PROPOSE", "refund_due",
                            {"value": True, "depends_on": ["charge"]},
                            trace_id, input_refs=["charge"])
        return prop

    def test_happy_path(self, kernel: Kernel, trace_id: str):
        prop = self._setup_clean_belief(kernel, trace_id)
        ok, code = kernel.commit_belief_from_proposal(prop.id, trace_id)
        assert ok is True
        assert code == "COMMITTED"

    def test_evidence_record_created(self, kernel: Kernel, trace_id: str):
        prop = self._setup_clean_belief(kernel, trace_id)
        kernel.commit_belief_from_proposal(prop.id, trace_id)
        view = kernel.current_view(trace_id)
        assert "validation_refund_due" in view["evidence"]
        ev = view["evidence"]["validation_refund_due"]
        assert ev["result"] == "pass"
        assert "existence" in ev["checks"]
        assert "staleness" in ev["checks"]

    def test_committed_belief_in_view(self, kernel: Kernel, trace_id: str):
        prop = self._setup_clean_belief(kernel, trace_id)
        kernel.commit_belief_from_proposal(prop.id, trace_id)
        view = kernel.current_view(trace_id)
        assert "refund_due" in view["beliefs"]

    def test_proposal_superseded(self, kernel: Kernel, trace_id: str):
        prop = self._setup_clean_belief(kernel, trace_id)
        kernel.commit_belief_from_proposal(prop.id, trace_id)
        got = kernel.store.get(prop.id)
        assert got.status == "INVALIDATED"
        assert got.reason == "SUPERSEDED_BY_COMMIT"

    def test_missing_percept(self, kernel: Kernel, trace_id: str):
        # No percept committed
        prop = kernel.write("planner", "beliefs", "PROPOSE", "refund_due",
                            {"value": True, "depends_on": ["charge"]}, trace_id)
        ok, code = kernel.commit_belief_from_proposal(prop.id, trace_id)
        assert ok is False
        assert code == "MISSING_EVIDENCE"

    def test_stale_evidence(self, kernel: Kernel, trace_id: str):
        kernel.write("tool", "percepts", "COMMIT", "charge",
                     {"stale": True, "conflict": False}, trace_id)
        prop = kernel.write("planner", "beliefs", "PROPOSE", "refund_due",
                            {"value": True, "depends_on": ["charge"]}, trace_id)
        ok, code = kernel.commit_belief_from_proposal(prop.id, trace_id)
        assert ok is False
        assert code == "STALE_EVIDENCE"

    def test_conflict_low_confidence_unresolved(self, kernel: Kernel, trace_id: str):
        kernel.write("tool", "percepts", "COMMIT", "charge",
                     {"stale": False, "conflict": True}, trace_id,
                     confidence=0.4)
        prop = kernel.write("planner", "beliefs", "PROPOSE", "refund_due",
                            {"value": True, "depends_on": ["charge"]}, trace_id)
        ok, code = kernel.commit_belief_from_proposal(prop.id, trace_id)
        assert ok is False
        assert code == "UNRESOLVED_CONFLICT"

    def test_conflict_high_confidence_arbitrated(self, kernel: Kernel, trace_id: str):
        kernel.write("tool", "percepts", "COMMIT", "charge",
                     {"stale": False, "conflict": True}, trace_id,
                     confidence=0.9)
        prop = kernel.write("planner", "beliefs", "PROPOSE", "refund_due",
                            {"value": True, "depends_on": ["charge"]}, trace_id)
        ok, code = kernel.commit_belief_from_proposal(prop.id, trace_id)
        assert ok is True
        assert code == "COMMITTED"

    def test_conflict_at_threshold_arbitrated(self, kernel: Kernel, trace_id: str):
        kernel.write("tool", "percepts", "COMMIT", "charge",
                     {"stale": False, "conflict": True}, trace_id,
                     confidence=0.7)
        prop = kernel.write("planner", "beliefs", "PROPOSE", "refund_due",
                            {"value": True, "depends_on": ["charge"]}, trace_id)
        ok, code = kernel.commit_belief_from_proposal(prop.id, trace_id)
        assert ok is True
        assert code == "COMMITTED"

    def test_conflict_no_confidence_unresolved(self, kernel: Kernel, trace_id: str):
        kernel.write("tool", "percepts", "COMMIT", "charge",
                     {"stale": False, "conflict": True}, trace_id)
        prop = kernel.write("planner", "beliefs", "PROPOSE", "refund_due",
                            {"value": True, "depends_on": ["charge"]}, trace_id)
        ok, code = kernel.commit_belief_from_proposal(prop.id, trace_id)
        assert ok is False
        assert code == "UNRESOLVED_CONFLICT"

    def test_low_confidence_rejected(self, kernel: Kernel, trace_id: str):
        kernel.write("tool", "percepts", "COMMIT", "charge",
                     {"stale": False, "conflict": False}, trace_id,
                     confidence=0.3)
        prop = kernel.write("planner", "beliefs", "PROPOSE", "refund_due",
                            {"value": True, "depends_on": ["charge"]}, trace_id)
        ok, code = kernel.commit_belief_from_proposal(prop.id, trace_id)
        assert ok is False
        assert code == "LOW_CONFIDENCE"

    def test_nan_confidence_does_not_bypass_gate(self, kernel: Kernel, trace_id: str):
        """NaN must fail the gate closed, not slip through it.

        Every comparison against NaN is False, so an unguarded `confidence <
        min_confidence` silently admits it. A percept whose confidence is
        unknown is the case the gate exists for.
        """
        with pytest.raises(ValueError):
            kernel.write("tool", "percepts", "COMMIT", "charge",
                         {"stale": False, "conflict": False}, trace_id,
                         confidence=float("nan"))

    def test_nan_confidence_rejected_even_if_it_reaches_the_gate(self, trace_id: str):
        """Defence in depth: if a NaN is already in the store, the gate still refuses."""
        k = Kernel()
        rec = k.write("tool", "percepts", "COMMIT", "charge",
                      {"stale": False, "conflict": False}, trace_id, confidence=0.9)
        object.__setattr__(rec.prov, "confidence", float("nan"))
        prop = k.write("planner", "beliefs", "PROPOSE", "refund_due",
                       {"value": True, "depends_on": ["charge"]}, trace_id)
        ok, code = k.commit_belief_from_proposal(prop.id, trace_id)
        assert ok is False
        assert code == "LOW_CONFIDENCE"

    @pytest.mark.parametrize("bad", [1.5, -0.5, float("inf"), float("-inf")])
    def test_out_of_range_confidence_rejected(self, kernel: Kernel, trace_id: str, bad: float):
        with pytest.raises(ValueError):
            kernel.write("tool", "percepts", "COMMIT", "charge",
                         {"stale": False, "conflict": False}, trace_id,
                         confidence=bad)

    @pytest.mark.parametrize("ok_conf", [0.0, 0.5, 1.0])
    def test_valid_confidence_still_accepted(self, kernel: Kernel, trace_id: str, ok_conf: float):
        rec = kernel.write("tool", "percepts", "COMMIT", "charge",
                           {"stale": False, "conflict": False}, trace_id,
                           confidence=ok_conf)
        assert rec.prov.confidence == ok_conf

    def test_confidence_at_threshold_passes(self, kernel: Kernel, trace_id: str):
        kernel.write("tool", "percepts", "COMMIT", "charge",
                     {"stale": False, "conflict": False}, trace_id,
                     confidence=0.5)
        prop = kernel.write("planner", "beliefs", "PROPOSE", "refund_due",
                            {"value": True, "depends_on": ["charge"]}, trace_id)
        ok, code = kernel.commit_belief_from_proposal(prop.id, trace_id)
        assert ok is True
        assert code == "COMMITTED"

    def test_invalid_proposal_wrong_slot(self, kernel: Kernel, trace_id: str):
        prop = kernel.write("tool", "percepts", "COMMIT", "charge",
                            {}, trace_id)
        ok, code = kernel.commit_belief_from_proposal(prop.id, trace_id)
        assert ok is False
        assert code == "INVALID_PROPOSAL"

    def test_invalid_proposal_already_invalidated(self, kernel: Kernel, trace_id: str):
        prop = kernel.write("planner", "beliefs", "PROPOSE", "refund_due",
                            {"value": True}, trace_id)
        kernel.store.invalidate(prop.id, "already invalidated")
        ok, code = kernel.commit_belief_from_proposal(prop.id, trace_id)
        assert ok is False
        assert code == "INVALID_PROPOSAL"

    def test_invalid_proposal_nonexistent(self, kernel: Kernel, trace_id: str):
        ok, code = kernel.commit_belief_from_proposal("nonexistent", trace_id)
        assert ok is False
        assert code == "INVALID_PROPOSAL"

    def test_evidence_includes_confidence_check(self, kernel: Kernel, trace_id: str):
        kernel.write("tool", "percepts", "COMMIT", "charge",
                     {"stale": False, "conflict": False}, trace_id,
                     confidence=0.9)
        prop = kernel.write("planner", "beliefs", "PROPOSE", "refund_due",
                            {"value": True, "depends_on": ["charge"]}, trace_id)
        kernel.commit_belief_from_proposal(prop.id, trace_id)
        view = kernel.current_view(trace_id)
        ev = view["evidence"]["validation_refund_due"]
        assert "confidence" in ev["checks"]

    def test_custom_min_confidence(self, trace_id: str):
        k = Kernel(min_confidence=0.8)
        k.write("tool", "percepts", "COMMIT", "charge",
                {"stale": False, "conflict": False}, trace_id,
                confidence=0.7)
        prop = k.write("planner", "beliefs", "PROPOSE", "refund_due",
                       {"value": True, "depends_on": ["charge"]}, trace_id)
        ok, code = k.commit_belief_from_proposal(prop.id, trace_id)
        assert ok is False
        assert code == "LOW_CONFIDENCE"

    def test_custom_conflict_confidence_threshold(self, trace_id: str):
        k = Kernel(conflict_confidence_threshold=0.9)
        k.write("tool", "percepts", "COMMIT", "charge",
                {"stale": False, "conflict": True}, trace_id,
                confidence=0.85)
        prop = k.write("planner", "beliefs", "PROPOSE", "refund_due",
                       {"value": True, "depends_on": ["charge"]}, trace_id)
        ok, code = k.commit_belief_from_proposal(prop.id, trace_id)
        assert ok is False
        assert code == "UNRESOLVED_CONFLICT"


class TestValidatePlan:
    """Tests for kernel.validate_plan()."""

    def _setup_belief(self, kernel: Kernel, trace_id: str):
        """Commit a percept + belief."""
        kernel.write("tool", "percepts", "COMMIT", "charge",
                     {"stale": False, "conflict": False}, trace_id)
        prop = kernel.write("planner", "beliefs", "PROPOSE", "refund_due",
                            {"value": True, "depends_on": ["charge"]}, trace_id)
        kernel.commit_belief_from_proposal(prop.id, trace_id)

    def test_feasible_plan(self, kernel: Kernel, trace_id: str):
        self._setup_belief(kernel, trace_id)
        plan = kernel.write("planner", "plans", "PROPOSE", "action_plan",
                            {"steps": [{"action": "issue_refund",
                                        "requires_beliefs": ["refund_due"]}]},
                            trace_id)
        ok, code = kernel.validate_plan(plan.id, trace_id)
        assert ok is True
        assert code == "PLAN_FEASIBLE"

    def test_missing_belief(self, kernel: Kernel, trace_id: str):
        plan = kernel.write("planner", "plans", "PROPOSE", "action_plan",
                            {"steps": [{"action": "issue_refund",
                                        "requires_beliefs": ["refund_due"]}]},
                            trace_id)
        ok, code = kernel.validate_plan(plan.id, trace_id)
        assert ok is False
        assert code == "PLAN_MISSING_BELIEF"

    def test_unsatisfied_belief(self, kernel: Kernel, trace_id: str):
        # Commit a belief with value=False
        kernel.write("tool", "percepts", "COMMIT", "charge",
                     {"stale": False, "conflict": False}, trace_id)
        prop = kernel.write("planner", "beliefs", "PROPOSE", "refund_due",
                            {"value": False, "depends_on": ["charge"]}, trace_id)
        kernel.commit_belief_from_proposal(prop.id, trace_id)

        plan = kernel.write("planner", "plans", "PROPOSE", "action_plan",
                            {"steps": [{"action": "issue_refund",
                                        "requires_beliefs": ["refund_due"]}]},
                            trace_id)
        ok, code = kernel.validate_plan(plan.id, trace_id)
        assert ok is False
        assert code == "PLAN_BELIEF_NOT_SATISFIED"

    def test_constraint_blocks_plan(self, kernel: Kernel, trace_id: str):
        self._setup_belief(kernel, trace_id)
        kernel.write("symbolic_validator", "constraints", "COMMIT",
                     "no_duplicate_refund",
                     {"enabled": True, "blocks_field": "is_duplicate"},
                     trace_id)
        plan = kernel.write("planner", "plans", "PROPOSE", "action_plan",
                            {"steps": [{"action": "issue_refund",
                                        "requires_beliefs": ["refund_due"],
                                        "is_duplicate": True}]},
                            trace_id)
        ok, code = kernel.validate_plan(plan.id, trace_id)
        assert ok is False
        assert code == "PLAN_NO_DUPLICATE_REFUND_BLOCKED"

    def test_constraint_not_blocking(self, kernel: Kernel, trace_id: str):
        self._setup_belief(kernel, trace_id)
        kernel.write("symbolic_validator", "constraints", "COMMIT",
                     "no_duplicate_refund",
                     {"enabled": True, "blocks_field": "is_duplicate"},
                     trace_id)
        plan = kernel.write("planner", "plans", "PROPOSE", "action_plan",
                            {"steps": [{"action": "issue_refund",
                                        "requires_beliefs": ["refund_due"],
                                        "is_duplicate": False}]},
                            trace_id)
        ok, code = kernel.validate_plan(plan.id, trace_id)
        assert ok is True

    def test_invalid_plan_proposal(self, kernel: Kernel, trace_id: str):
        rec = kernel.write("tool", "percepts", "COMMIT", "c", {}, trace_id)
        ok, code = kernel.validate_plan(rec.id, trace_id)
        assert ok is False
        assert code == "INVALID_PLAN_PROPOSAL"

    def test_invalid_plan_nonexistent(self, kernel: Kernel, trace_id: str):
        ok, code = kernel.validate_plan("nonexistent", trace_id)
        assert ok is False
        assert code == "INVALID_PLAN_PROPOSAL"

    def test_empty_steps_feasible(self, kernel: Kernel, trace_id: str):
        plan = kernel.write("planner", "plans", "PROPOSE", "action_plan",
                            {"steps": []}, trace_id)
        ok, code = kernel.validate_plan(plan.id, trace_id)
        assert ok is True
        assert code == "PLAN_FEASIBLE"


class TestCommitActionFromProposal:
    """Tests for kernel.commit_action_from_proposal()."""

    def _setup_full_pipeline(self, kernel: Kernel, trace_id: str):
        """Setup: percept -> belief -> constraints -> ready for action."""
        kernel.write("tool", "percepts", "COMMIT", "charge",
                     {"stale": False, "conflict": False}, trace_id)
        prop = kernel.write("planner", "beliefs", "PROPOSE", "refund_due",
                            {"value": True, "depends_on": ["charge"]}, trace_id)
        kernel.commit_belief_from_proposal(prop.id, trace_id)
        kernel.write("symbolic_validator", "constraints", "COMMIT",
                     "no_duplicate_refund",
                     {"enabled": True, "blocks_field": "is_duplicate"}, trace_id)

    def test_happy_path(self, kernel: Kernel, trace_id: str):
        self._setup_full_pipeline(kernel, trace_id)
        action = kernel.write("planner", "actions", "PROPOSE", "issue_refund",
                              {"type": "issue_refund",
                               "requires_beliefs": ["refund_due"],
                               "is_duplicate": False},
                              trace_id)
        ok, code = kernel.commit_action_from_proposal(action.id, trace_id)
        assert ok is True
        assert code == "COMMITTED"

    def test_action_in_view(self, kernel: Kernel, trace_id: str):
        self._setup_full_pipeline(kernel, trace_id)
        action = kernel.write("planner", "actions", "PROPOSE", "issue_refund",
                              {"type": "issue_refund",
                               "requires_beliefs": ["refund_due"],
                               "is_duplicate": False},
                              trace_id)
        kernel.commit_action_from_proposal(action.id, trace_id)
        view = kernel.current_view(trace_id)
        assert "issue_refund" in view["actions"]

    def test_missing_belief(self, kernel: Kernel, trace_id: str):
        action = kernel.write("planner", "actions", "PROPOSE", "issue_refund",
                              {"type": "issue_refund",
                               "requires_beliefs": ["refund_due"]},
                              trace_id)
        ok, code = kernel.commit_action_from_proposal(action.id, trace_id)
        assert ok is False
        assert code == "NO_COMMITTED_BELIEF"

    def test_constraint_blocks(self, kernel: Kernel, trace_id: str):
        self._setup_full_pipeline(kernel, trace_id)
        action = kernel.write("planner", "actions", "PROPOSE", "issue_refund",
                              {"type": "issue_refund",
                               "requires_beliefs": ["refund_due"],
                               "is_duplicate": True},
                              trace_id)
        ok, code = kernel.commit_action_from_proposal(action.id, trace_id)
        assert ok is False
        assert code == "NO_DUPLICATE_REFUND_BLOCKED"

    def test_invalid_action_proposal(self, kernel: Kernel, trace_id: str):
        rec = kernel.write("tool", "percepts", "COMMIT", "c", {}, trace_id)
        ok, code = kernel.commit_action_from_proposal(rec.id, trace_id)
        assert ok is False
        assert code == "INVALID_ACTION_PROPOSAL"

    def test_action_proposal_superseded(self, kernel: Kernel, trace_id: str):
        self._setup_full_pipeline(kernel, trace_id)
        action = kernel.write("planner", "actions", "PROPOSE", "issue_refund",
                              {"type": "issue_refund",
                               "requires_beliefs": ["refund_due"],
                               "is_duplicate": False},
                              trace_id)
        kernel.commit_action_from_proposal(action.id, trace_id)
        got = kernel.store.get(action.id)
        assert got.status == "INVALIDATED"
        assert got.reason == "SUPERSEDED_BY_COMMIT"

    # ── Prediction-gated action tests ────────────────────────────────

    def test_require_prediction_no_prediction(self, kernel: Kernel, trace_id: str):
        self._setup_full_pipeline(kernel, trace_id)
        action = kernel.write("planner", "actions", "PROPOSE", "issue_refund",
                              {"type": "issue_refund",
                               "requires_beliefs": ["refund_due"],
                               "is_duplicate": False},
                              trace_id)
        ok, code = kernel.commit_action_from_proposal(
            action.id, trace_id, require_prediction=True)
        assert ok is False
        assert code == "NO_PREDICTION"

    def test_require_prediction_negative(self, kernel: Kernel, trace_id: str):
        self._setup_full_pipeline(kernel, trace_id)
        # Commit a negative prediction
        pred_prop = kernel.write("planner", "predictions", "PROPOSE",
                                 "pred_issue_refund",
                                 {"action_type": "issue_refund",
                                  "expected_outcome": -1,
                                  "requires_beliefs": ["refund_due"]},
                                 trace_id)
        kernel.commit_prediction(pred_prop.id, trace_id)

        action = kernel.write("planner", "actions", "PROPOSE", "issue_refund",
                              {"type": "issue_refund",
                               "requires_beliefs": ["refund_due"],
                               "is_duplicate": False},
                              trace_id)
        ok, code = kernel.commit_action_from_proposal(
            action.id, trace_id, require_prediction=True)
        assert ok is False
        assert code == "NEGATIVE_PREDICTION"

    def test_require_prediction_positive(self, kernel: Kernel, trace_id: str):
        self._setup_full_pipeline(kernel, trace_id)
        pred_prop = kernel.write("planner", "predictions", "PROPOSE",
                                 "pred_issue_refund",
                                 {"action_type": "issue_refund",
                                  "expected_outcome": 1,
                                  "requires_beliefs": ["refund_due"]},
                                 trace_id)
        kernel.commit_prediction(pred_prop.id, trace_id)

        action = kernel.write("planner", "actions", "PROPOSE", "issue_refund",
                              {"type": "issue_refund",
                               "requires_beliefs": ["refund_due"],
                               "is_duplicate": False},
                              trace_id)
        ok, code = kernel.commit_action_from_proposal(
            action.id, trace_id, require_prediction=True)
        assert ok is True
        assert code == "COMMITTED"

    def test_require_prediction_zero_outcome(self, kernel: Kernel, trace_id: str):
        self._setup_full_pipeline(kernel, trace_id)
        pred_prop = kernel.write("planner", "predictions", "PROPOSE",
                                 "pred_issue_refund",
                                 {"action_type": "issue_refund",
                                  "expected_outcome": 0,
                                  "requires_beliefs": ["refund_due"]},
                                 trace_id)
        kernel.commit_prediction(pred_prop.id, trace_id)

        action = kernel.write("planner", "actions", "PROPOSE", "issue_refund",
                              {"type": "issue_refund",
                               "requires_beliefs": ["refund_due"],
                               "is_duplicate": False},
                              trace_id)
        ok, code = kernel.commit_action_from_proposal(
            action.id, trace_id, require_prediction=True)
        assert ok is True
        assert code == "COMMITTED"

    def test_no_require_prediction_skips_check(self, kernel: Kernel, trace_id: str):
        self._setup_full_pipeline(kernel, trace_id)
        action = kernel.write("planner", "actions", "PROPOSE", "issue_refund",
                              {"type": "issue_refund",
                               "requires_beliefs": ["refund_due"],
                               "is_duplicate": False},
                              trace_id)
        ok, code = kernel.commit_action_from_proposal(
            action.id, trace_id, require_prediction=False)
        assert ok is True
        assert code == "COMMITTED"

    def test_queue_for_review_always_succeeds(self, kernel: Kernel, trace_id: str):
        action = kernel.write("planner", "actions", "PROPOSE", "queue_for_review",
                              {"type": "queue_for_review", "reason": "test"},
                              trace_id)
        ok, code = kernel.commit_action_from_proposal(action.id, trace_id)
        assert ok is True
        assert code == "COMMITTED"


class TestCommitPrediction:
    """Tests for kernel.commit_prediction()."""

    def _setup_belief(self, kernel: Kernel, trace_id: str):
        kernel.write("tool", "percepts", "COMMIT", "charge",
                     {"stale": False, "conflict": False}, trace_id)
        prop = kernel.write("planner", "beliefs", "PROPOSE", "refund_due",
                            {"value": True, "depends_on": ["charge"]}, trace_id)
        kernel.commit_belief_from_proposal(prop.id, trace_id)

    def test_happy_path(self, kernel: Kernel, trace_id: str):
        self._setup_belief(kernel, trace_id)
        pred = kernel.write("planner", "predictions", "PROPOSE",
                            "pred_refund",
                            {"action_type": "issue_refund",
                             "expected_outcome": 1,
                             "requires_beliefs": ["refund_due"]},
                            trace_id)
        ok, code = kernel.commit_prediction(pred.id, trace_id)
        assert ok is True
        assert code == "COMMITTED"

    def test_prediction_in_view(self, kernel: Kernel, trace_id: str):
        self._setup_belief(kernel, trace_id)
        pred = kernel.write("planner", "predictions", "PROPOSE",
                            "pred_refund",
                            {"action_type": "issue_refund",
                             "expected_outcome": 1,
                             "requires_beliefs": ["refund_due"]},
                            trace_id)
        kernel.commit_prediction(pred.id, trace_id)
        view = kernel.current_view(trace_id)
        assert "pred_refund" in view["predictions"]

    def test_missing_belief(self, kernel: Kernel, trace_id: str):
        pred = kernel.write("planner", "predictions", "PROPOSE",
                            "pred_refund",
                            {"action_type": "issue_refund",
                             "expected_outcome": 1,
                             "requires_beliefs": ["refund_due"]},
                            trace_id)
        ok, code = kernel.commit_prediction(pred.id, trace_id)
        assert ok is False
        assert code == "PREDICTION_MISSING_BELIEF"

    def test_invalid_prediction_proposal(self, kernel: Kernel, trace_id: str):
        rec = kernel.write("tool", "percepts", "COMMIT", "c", {}, trace_id)
        ok, code = kernel.commit_prediction(rec.id, trace_id)
        assert ok is False
        assert code == "INVALID_PREDICTION_PROPOSAL"

    def test_nonexistent_proposal(self, kernel: Kernel, trace_id: str):
        ok, code = kernel.commit_prediction("nonexistent", trace_id)
        assert ok is False
        assert code == "INVALID_PREDICTION_PROPOSAL"

    def test_proposal_superseded(self, kernel: Kernel, trace_id: str):
        self._setup_belief(kernel, trace_id)
        pred = kernel.write("planner", "predictions", "PROPOSE",
                            "pred_refund",
                            {"action_type": "issue_refund",
                             "expected_outcome": 1,
                             "requires_beliefs": ["refund_due"]},
                            trace_id)
        kernel.commit_prediction(pred.id, trace_id)
        got = kernel.store.get(pred.id)
        assert got.status == "INVALIDATED"
        assert got.reason == "SUPERSEDED_BY_COMMIT"

    def test_no_requires_beliefs_passes(self, kernel: Kernel, trace_id: str):
        pred = kernel.write("planner", "predictions", "PROPOSE",
                            "pred_something",
                            {"action_type": "something",
                             "expected_outcome": 0},
                            trace_id)
        ok, code = kernel.commit_prediction(pred.id, trace_id)
        assert ok is True


class TestKernelWithCustomStore:
    def test_sqlite_store(self, tmp_path, trace_id: str):
        from alethic.sqlite_store import SqliteStore
        store = SqliteStore(str(tmp_path / "kernel_test.db"))
        k = Kernel(store=store)
        k.write("tool", "percepts", "COMMIT", "charge",
                {"stale": False, "conflict": False}, trace_id)
        prop = k.write("planner", "beliefs", "PROPOSE", "refund_due",
                       {"value": True, "depends_on": ["charge"]}, trace_id)
        ok, code = k.commit_belief_from_proposal(prop.id, trace_id)
        assert ok is True
        store.close()
