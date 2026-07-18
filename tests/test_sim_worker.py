"""Tests for alethic/sim_worker.py."""
from __future__ import annotations

from alethic.kernel import Kernel
from alethic.sim_worker import SimRule, SimulatorWorker, evaluate_rule, _check_conditions


class TestCheckConditions:
    def test_equality_match(self):
        assert _check_conditions({"status": "active"}, {"status": "active"}) is True

    def test_equality_mismatch(self):
        assert _check_conditions({"status": "active"}, {"status": "inactive"}) is False

    def test_missing_field(self):
        assert _check_conditions({}, {"status": "active"}) is False

    def test_gt(self):
        assert _check_conditions({"temp": 80}, {"temp__gt": 70}) is True
        assert _check_conditions({"temp": 70}, {"temp__gt": 70}) is False

    def test_lt(self):
        assert _check_conditions({"temp": 60}, {"temp__lt": 70}) is True
        assert _check_conditions({"temp": 70}, {"temp__lt": 70}) is False

    def test_gte(self):
        assert _check_conditions({"temp": 70}, {"temp__gte": 70}) is True
        assert _check_conditions({"temp": 69}, {"temp__gte": 70}) is False

    def test_lte(self):
        assert _check_conditions({"temp": 70}, {"temp__lte": 70}) is True
        assert _check_conditions({"temp": 71}, {"temp__lte": 70}) is False

    def test_ne(self):
        assert _check_conditions({"status": "active"}, {"status__ne": "inactive"}) is True
        assert _check_conditions({"status": "active"}, {"status__ne": "active"}) is False

    def test_unknown_op_returns_false(self):
        assert _check_conditions({"x": 1}, {"x__unknown": 1}) is False

    def test_missing_field_for_op(self):
        assert _check_conditions({}, {"temp__gt": 70}) is False

    def test_multiple_conditions(self):
        payload = {"temp": 80, "status": "active"}
        assert _check_conditions(payload, {"temp__gt": 70, "status": "active"}) is True
        assert _check_conditions(payload, {"temp__gt": 70, "status": "inactive"}) is False


class TestEvaluateRule:
    def test_all_conditions_match(self):
        rule = SimRule(
            action_type="cool_down",
            expected_outcome=1.0,
            requires_beliefs=["temp_reading"],
            belief_conditions={"temp_reading": {"value__gt": 70}},
        )
        view = {
            "beliefs": {"temp_reading": {"value": 80}},
            "percepts": {},
        }
        assert evaluate_rule(rule, view) == 1.0

    def test_missing_required_belief(self):
        rule = SimRule(
            action_type="cool_down",
            expected_outcome=1.0,
            requires_beliefs=["temp_reading"],
        )
        view = {"beliefs": {}, "percepts": {}}
        assert evaluate_rule(rule, view) is None

    def test_belief_condition_fails(self):
        rule = SimRule(
            action_type="cool_down",
            expected_outcome=1.0,
            requires_beliefs=["temp_reading"],
            belief_conditions={"temp_reading": {"value__gt": 90}},
        )
        view = {
            "beliefs": {"temp_reading": {"value": 80}},
            "percepts": {},
        }
        assert evaluate_rule(rule, view) is None

    def test_percept_condition_match(self):
        rule = SimRule(
            action_type="cool_down",
            expected_outcome=0.5,
            percept_conditions={"sensor": {"temp__gt": 70}},
        )
        view = {
            "beliefs": {},
            "percepts": {"sensor": {"temp": 80}},
        }
        assert evaluate_rule(rule, view) == 0.5

    def test_percept_condition_fails(self):
        rule = SimRule(
            action_type="cool_down",
            expected_outcome=0.5,
            percept_conditions={"sensor": {"temp__gt": 90}},
        )
        view = {
            "beliefs": {},
            "percepts": {"sensor": {"temp": 80}},
        }
        assert evaluate_rule(rule, view) is None

    def test_missing_percept(self):
        rule = SimRule(
            action_type="cool_down",
            expected_outcome=0.5,
            percept_conditions={"sensor": {"temp__gt": 70}},
        )
        view = {"beliefs": {}, "percepts": {}}
        assert evaluate_rule(rule, view) is None

    def test_no_conditions_always_matches(self):
        rule = SimRule(action_type="noop", expected_outcome=0.0)
        view = {"beliefs": {}, "percepts": {}}
        assert evaluate_rule(rule, view) == 0.0

    def test_belief_not_dict(self):
        rule = SimRule(
            action_type="test",
            expected_outcome=1.0,
            belief_conditions={"b1": {"value": True}},
        )
        view = {"beliefs": {"b1": "not_a_dict"}, "percepts": {}}
        assert evaluate_rule(rule, view) is None


class TestSimulatorWorker:
    def test_should_activate_no_beliefs(self):
        w = SimulatorWorker(rules=[SimRule(action_type="test", expected_outcome=1.0)])
        view = {"beliefs": {}, "percepts": {}}
        assert w.should_activate(view) is False

    def test_should_activate_with_beliefs(self):
        w = SimulatorWorker(rules=[SimRule(action_type="test", expected_outcome=1.0)])
        view = {"beliefs": {"b": {"value": True}}, "percepts": {}}
        assert w.should_activate(view) is True

    def test_should_activate_after_done(self):
        w = SimulatorWorker(rules=[])
        w._done = True
        view = {"beliefs": {"b": {"value": True}}, "percepts": {}}
        assert w.should_activate(view) is False

    def test_reset(self):
        w = SimulatorWorker(rules=[])
        w._done = True
        w.reset()
        assert w._done is False

    def test_integration_proposes_and_commits_prediction(self):
        k = Kernel()
        trace = "t1"
        # Setup: commit percept and belief
        k.write("tool", "percepts", "COMMIT", "charge",
                {"stale": False, "conflict": False}, trace)
        prop = k.write("planner", "beliefs", "PROPOSE", "refund_due",
                       {"value": True, "depends_on": ["charge"]}, trace)
        k.commit_belief_from_proposal(prop.id, trace)

        rule = SimRule(
            action_type="issue_refund",
            expected_outcome=1.0,
            requires_beliefs=["refund_due"],
        )
        w = SimulatorWorker(rules=[rule])
        view = k.current_view(trace)
        produced = w.step(k, trace, view)
        assert produced is True

        view = k.current_view(trace)
        assert "pred_issue_refund" in view["predictions"]

    def test_skips_already_committed_prediction(self):
        k = Kernel()
        trace = "t1"
        k.write("tool", "percepts", "COMMIT", "charge",
                {"stale": False, "conflict": False}, trace)
        prop = k.write("planner", "beliefs", "PROPOSE", "refund_due",
                       {"value": True, "depends_on": ["charge"]}, trace)
        k.commit_belief_from_proposal(prop.id, trace)

        rule = SimRule(
            action_type="issue_refund",
            expected_outcome=1.0,
            requires_beliefs=["refund_due"],
        )
        w = SimulatorWorker(rules=[rule])

        # First step: commits prediction
        view = k.current_view(trace)
        w._done = False
        w.step(k, trace, view)

        # Second step: should skip (already committed)
        w._done = False
        view = k.current_view(trace)
        produced = w.step(k, trace, view)
        assert produced is False
