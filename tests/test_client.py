"""Tests for the AlethicClient in local mode."""
from __future__ import annotations

import pytest

from alethic_kernel.client import AlethicClient, EpisodeResult


class TestClientLocal:
    def test_health_local(self):
        client = AlethicClient(mode="local")
        h = client.health()
        assert h["status"] == "ok"
        assert h["mode"] == "local"

    def test_kernel_accessible(self):
        client = AlethicClient(mode="local")
        assert client.kernel is not None

    def test_write_and_view(self):
        client = AlethicClient(mode="local")
        trace = "test-trace-001"
        result = client.write(
            role="tool", slot="percepts", mode="COMMIT",
            kind="charge", payload={"amount": 100},
            trace_id=trace,
        )
        assert result["ok"] is True
        view = client.current_view(trace)
        assert "charge" in view["percepts"]

    def test_commit_belief_flow(self):
        client = AlethicClient(mode="local")
        trace = "test-trace-001"

        # Write a percept
        client.write(
            role="tool", slot="percepts", mode="COMMIT",
            kind="charge", payload={"amount": 100},
            trace_id=trace, confidence=0.9,
        )

        # Propose a belief
        result = client.write(
            role="planner", slot="beliefs", mode="PROPOSE",
            kind="refund_due", payload={"value": True, "depends_on": ["charge"]},
            trace_id=trace,
        )
        proposal_id = result["record"]["id"]

        # Commit the belief
        ok, code = client.commit_belief(proposal_id, trace)
        assert ok is True
        assert code == "COMMITTED"

    def test_commit_action_flow(self):
        client = AlethicClient(mode="local")
        trace = "test-trace-001"

        # Write percept + commit belief
        client.write("tool", "percepts", "COMMIT", "charge",
                      {"amount": 100}, trace, confidence=0.9)
        bp = client.write("planner", "beliefs", "PROPOSE", "refund_due",
                           {"value": True, "depends_on": ["charge"]}, trace)
        client.commit_belief(bp["record"]["id"], trace)

        # Write constraint (symbolic_validator role has COMMIT on constraints)
        client.write("symbolic_validator", "constraints", "COMMIT", "no_duplicate_refund",
                      {"enabled": True, "blocks_field": "is_duplicate"}, trace)

        # Propose + commit action
        ap = client.write("planner", "actions", "PROPOSE", "issue_refund",
                           {"type": "issue_refund", "requires_beliefs": ["refund_due"]},
                           trace)
        ok, code = client.commit_action(ap["record"]["id"], trace)
        assert ok is True
        assert code == "COMMITTED"

    def test_validate_plan(self):
        client = AlethicClient(mode="local")
        trace = "test-trace-001"

        # Write percept + commit belief
        client.write("tool", "percepts", "COMMIT", "charge",
                      {"amount": 100}, trace, confidence=0.9)
        bp = client.write("planner", "beliefs", "PROPOSE", "refund_due",
                           {"value": True, "depends_on": ["charge"]}, trace)
        client.commit_belief(bp["record"]["id"], trace)

        # Propose plan
        pp = client.write("planner", "plans", "PROPOSE", "refund_plan",
                           {"steps": [{"requires_beliefs": ["refund_due"]}]},
                           trace)
        ok, code = client.validate_plan(pp["record"]["id"], trace)
        assert ok is True
        assert code == "PLAN_FEASIBLE"

    def test_commit_prediction(self):
        client = AlethicClient(mode="local")
        trace = "test-trace-001"

        # Write percept + commit belief
        client.write("tool", "percepts", "COMMIT", "charge",
                      {"amount": 100}, trace, confidence=0.9)
        bp = client.write("planner", "beliefs", "PROPOSE", "refund_due",
                           {"value": True, "depends_on": ["charge"]}, trace)
        client.commit_belief(bp["record"]["id"], trace)

        # Propose prediction
        pp = client.write("planner", "predictions", "PROPOSE", "refund_outcome",
                           {"action_type": "issue_refund", "expected_outcome": 1,
                            "requires_beliefs": ["refund_due"]},
                           trace)
        ok, code = client.commit_prediction(pp["record"]["id"], trace)
        assert ok is True
        assert code == "COMMITTED"

    def test_run_episode_local(self):
        client = AlethicClient(mode="local")
        result = client.run_episode(
            task_inputs={
                "chargeId": "ch_test",
                "customerId": "cus_test",
                "amount": 100,
                "currency": "usd",
                "is_duplicate": False,
            },
            constraints={"no_duplicate_refund": {"blocks_field": "is_duplicate"}},
        )
        assert isinstance(result, EpisodeResult)
        assert result.trace_id
        assert "unsafe_action" in result.metrics
        assert result.metrics["unsafe_action"] == 0.0


class TestClientHTTPMode:
    def test_kernel_none_in_http_mode(self):
        client = AlethicClient(mode="http", base_url="http://localhost:9999")
        assert client.kernel is None

    def test_local_methods_raise_when_kernel_none(self):
        """Local-mode methods raise RuntimeError when kernel is unexpectedly None."""
        client = AlethicClient(mode="local")
        client._kernel = None  # simulate broken state
        trace = "t1"
        with pytest.raises(RuntimeError, match="Kernel not initialized"):
            client.write("tool", "percepts", "COMMIT", "k", {}, trace)
        with pytest.raises(RuntimeError, match="Kernel not initialized"):
            client.commit_belief("p1", trace)
        with pytest.raises(RuntimeError, match="Kernel not initialized"):
            client.commit_action("p1", trace)
        with pytest.raises(RuntimeError, match="Kernel not initialized"):
            client.commit_prediction("p1", trace)
        with pytest.raises(RuntimeError, match="Kernel not initialized"):
            client.validate_plan("p1", trace)
        with pytest.raises(RuntimeError, match="Kernel not initialized"):
            client.current_view(trace)


class TestStoreClose:
    def test_memory_store_close(self):
        """MemoryStore.close() is a no-op but satisfies the protocol."""
        from alethic_kernel.store import MemoryStore
        store = MemoryStore()
        store.close()  # should not raise
