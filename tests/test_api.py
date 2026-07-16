"""Tests for the Alethic API using FastAPI TestClient."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from alethic_kernel.alethic.api.app import create_app
from alethic_kernel.alethic.api.dependencies import reset_shared_state


@pytest.fixture(autouse=True)
def _reset():
    reset_shared_state()
    yield
    reset_shared_state()


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


class TestConfidenceValidation:
    """A percept's confidence must be a real number in [0, 1].

    JSON permits a bare NaN literal, and every comparison against NaN is False,
    so an unvalidated NaN would sail through the kernel's confidence gate and
    commit — the gate silently disabled by the one value that most needs it.
    """

    @staticmethod
    def _body(confidence):
        return {
            "role": "tool", "slot": "percepts", "mode": "COMMIT", "kind": "charge",
            "payload": {"stale": False, "conflict": False},
            "trace_id": "t-conf", "confidence": confidence,
        }

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), 1.5, -0.5])
    def test_invalid_confidence_rejected_with_422(self, client: TestClient, bad: float):
        resp = client.post(
            "/v1/write",
            content=json.dumps(self._body(bad)),
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 422, f"{bad!r} should be refused, got {resp.text[:200]}"

    def test_nan_rejection_is_reported_not_a_500(self, client: TestClient):
        """The 422 body must serialize even though the rejected input is NaN."""
        resp = client.post(
            "/v1/write",
            content=json.dumps(self._body(float("nan"))),
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 422
        assert resp.json()["detail"][0]["loc"] == ["body", "confidence"]

    @pytest.mark.parametrize("good", [0.0, 0.5, 1.0, None])
    def test_valid_confidence_accepted(self, client: TestClient, good):
        resp = client.post("/v1/write", json=self._body(good))
        assert resp.status_code == 200


class TestHealthEndpoints:
    def test_healthz(self, client: TestClient):
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_readyz(self, client: TestClient):
        resp = client.get("/readyz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
        assert data["store"] in ("memory", "sqlite")


class TestWriteEndpoint:
    def test_write_percept(self, client: TestClient):
        resp = client.post("/v1/write", json={
            "role": "tool",
            "slot": "percepts",
            "mode": "COMMIT",
            "kind": "charge",
            "payload": {"amount": 100},
            "trace_id": "t1",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["record"]["kind"] == "charge"
        assert data["record"]["status"] == "ACTIVE"

    def test_write_permission_denied(self, client: TestClient):
        resp = client.post("/v1/write", json={
            "role": "tool",
            "slot": "beliefs",
            "mode": "COMMIT",
            "kind": "x",
            "payload": {},
            "trace_id": "t1",
        })
        assert resp.status_code == 403

    def test_write_propose_belief(self, client: TestClient):
        resp = client.post("/v1/write", json={
            "role": "planner",
            "slot": "beliefs",
            "mode": "PROPOSE",
            "kind": "refund_due",
            "payload": {"value": True, "depends_on": ["charge"]},
            "trace_id": "t1",
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


class TestCommitEndpoints:
    def test_commit_belief_happy_path(self, client: TestClient):
        # Write percept
        client.post("/v1/write", json={
            "role": "tool", "slot": "percepts", "mode": "COMMIT",
            "kind": "charge",
            "payload": {"stale": False, "conflict": False},
            "trace_id": "t1",
        })
        # Propose belief
        resp = client.post("/v1/write", json={
            "role": "planner", "slot": "beliefs", "mode": "PROPOSE",
            "kind": "refund_due",
            "payload": {"value": True, "depends_on": ["charge"]},
            "trace_id": "t1",
        })
        prop_id = resp.json()["record"]["id"]

        # Commit belief
        resp = client.post("/v1/commit/belief", json={
            "proposal_id": prop_id,
            "trace_id": "t1",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["code"] == "COMMITTED"

    def test_commit_belief_invalid(self, client: TestClient):
        resp = client.post("/v1/commit/belief", json={
            "proposal_id": "nonexistent",
            "trace_id": "t1",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert data["code"] == "INVALID_PROPOSAL"

    def test_commit_action(self, client: TestClient):
        # Setup: percept -> belief -> constraint -> action
        client.post("/v1/write", json={
            "role": "tool", "slot": "percepts", "mode": "COMMIT",
            "kind": "charge",
            "payload": {"stale": False, "conflict": False},
            "trace_id": "t1",
        })
        resp = client.post("/v1/write", json={
            "role": "planner", "slot": "beliefs", "mode": "PROPOSE",
            "kind": "refund_due",
            "payload": {"value": True, "depends_on": ["charge"]},
            "trace_id": "t1",
        })
        prop_id = resp.json()["record"]["id"]
        client.post("/v1/commit/belief", json={
            "proposal_id": prop_id, "trace_id": "t1",
        })

        # Propose action
        resp = client.post("/v1/write", json={
            "role": "planner", "slot": "actions", "mode": "PROPOSE",
            "kind": "issue_refund",
            "payload": {"type": "issue_refund", "requires_beliefs": ["refund_due"],
                        "is_duplicate": False},
            "trace_id": "t1",
        })
        action_id = resp.json()["record"]["id"]

        resp = client.post("/v1/commit/action", json={
            "proposal_id": action_id, "trace_id": "t1",
        })
        assert resp.json()["ok"] is True
        assert resp.json()["code"] == "COMMITTED"

    def test_validate_plan(self, client: TestClient):
        # Setup belief
        client.post("/v1/write", json={
            "role": "tool", "slot": "percepts", "mode": "COMMIT",
            "kind": "charge",
            "payload": {"stale": False, "conflict": False},
            "trace_id": "t1",
        })
        resp = client.post("/v1/write", json={
            "role": "planner", "slot": "beliefs", "mode": "PROPOSE",
            "kind": "refund_due",
            "payload": {"value": True, "depends_on": ["charge"]},
            "trace_id": "t1",
        })
        client.post("/v1/commit/belief", json={
            "proposal_id": resp.json()["record"]["id"], "trace_id": "t1",
        })

        # Propose plan
        resp = client.post("/v1/write", json={
            "role": "planner", "slot": "plans", "mode": "PROPOSE",
            "kind": "action_plan",
            "payload": {"steps": [{"action": "issue_refund",
                                   "requires_beliefs": ["refund_due"]}]},
            "trace_id": "t1",
        })
        plan_id = resp.json()["record"]["id"]

        resp = client.post("/v1/validate/plan", json={
            "proposal_id": plan_id, "trace_id": "t1",
        })
        assert resp.json()["ok"] is True
        assert resp.json()["code"] == "PLAN_FEASIBLE"

    def test_commit_prediction(self, client: TestClient):
        # Setup belief
        client.post("/v1/write", json={
            "role": "tool", "slot": "percepts", "mode": "COMMIT",
            "kind": "charge",
            "payload": {"stale": False, "conflict": False},
            "trace_id": "t1",
        })
        resp = client.post("/v1/write", json={
            "role": "planner", "slot": "beliefs", "mode": "PROPOSE",
            "kind": "refund_due",
            "payload": {"value": True, "depends_on": ["charge"]},
            "trace_id": "t1",
        })
        client.post("/v1/commit/belief", json={
            "proposal_id": resp.json()["record"]["id"], "trace_id": "t1",
        })

        # Propose prediction
        resp = client.post("/v1/write", json={
            "role": "planner", "slot": "predictions", "mode": "PROPOSE",
            "kind": "pred_refund",
            "payload": {"action_type": "issue_refund", "expected_outcome": 1,
                        "requires_beliefs": ["refund_due"]},
            "trace_id": "t1",
        })
        pred_id = resp.json()["record"]["id"]

        resp = client.post("/v1/commit/prediction", json={
            "proposal_id": pred_id, "trace_id": "t1",
        })
        assert resp.json()["ok"] is True
        assert resp.json()["code"] == "COMMITTED"


class TestViewEndpoint:
    def test_empty_view(self, client: TestClient):
        resp = client.get("/v1/view/t1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["trace_id"] == "t1"
        assert "percepts" in data["view"]

    def test_view_with_data(self, client: TestClient):
        client.post("/v1/write", json={
            "role": "tool", "slot": "percepts", "mode": "COMMIT",
            "kind": "charge", "payload": {"amount": 100},
            "trace_id": "t1",
        })
        resp = client.get("/v1/view/t1")
        data = resp.json()
        assert "charge" in data["view"]["percepts"]


class TestEpisodeEndpoint:
    def test_clean_episode(self, client: TestClient):
        resp = client.post("/v1/episode", json={
            "task_inputs": {
                "chargeId": "ch_test",
                "customerId": "cus_test",
                "customerName": "Test",
                "amount": 100.0,
                "disputeReason": "product_not_received",
            },
            "constraints": {
                "no_duplicate_refund": {"blocks_field": "is_duplicate"},
            },
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["final"]["action_committed"] is True
        assert data["metrics"]["unsafe_action"] == 0.0
        assert "issue_refund" in data["view"]["actions"]

    def test_duplicate_episode(self, client: TestClient):
        resp = client.post("/v1/episode", json={
            "task_inputs": {
                "chargeId": "ch_test",
                "customerId": "cus_test",
                "customerName": "Test",
                "amount": 50.0,
                "disputeReason": "product_unacceptable",
                "is_duplicate": True,
            },
            "constraints": {
                "no_duplicate_refund": {"blocks_field": "is_duplicate"},
            },
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["final"]["action_committed"] is False
        assert data["metrics"]["unsafe_action"] == 0.0
