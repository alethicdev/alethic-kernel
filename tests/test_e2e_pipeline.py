"""End-to-end pipeline tests against a real uvicorn server.

Starts an actual HTTP server, then exercises the full kernel pipeline
over the network: percepts → beliefs → plans → predictions → actions,
including rejection paths (stale evidence, constraint blocks, negative
predictions) and the high-level episode endpoint.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict

import httpx
import pytest
import uvicorn

from alethic_kernel.api.app import create_app
from alethic_kernel.api.dependencies import reset_shared_state

# ── Server fixture ───────────────────────────────────────────────────

_PORT = 9876


@pytest.fixture(scope="module")
def server():
    """Start a real uvicorn server in a background thread."""
    reset_shared_state()
    app = create_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=_PORT, log_level="error")
    srv = uvicorn.Server(config)
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    # Wait for server to be ready
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            httpx.get(f"http://127.0.0.1:{_PORT}/healthz", timeout=1)
            break
        except httpx.ConnectError:
            time.sleep(0.05)
    else:
        pytest.fail("Server did not start within 10 seconds")
    yield srv
    srv.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(autouse=True)
def _reset_between_tests(server):
    """Reset kernel state before each test."""
    reset_shared_state()


@pytest.fixture
def base_url() -> str:
    return f"http://127.0.0.1:{_PORT}"


# ── Helpers ──────────────────────────────────────────────────────────

def write(base: str, role: str, slot: str, mode: str, kind: str,
          payload: Dict[str, Any], trace_id: str, **kw: Any) -> Dict[str, Any]:
    resp = httpx.post(f"{base}/v1/write", json={
        "role": role, "slot": slot, "mode": mode,
        "kind": kind, "payload": payload, "trace_id": trace_id, **kw,
    }, timeout=5)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    return data


def commit_belief(base: str, proposal_id: str, trace_id: str) -> Dict[str, Any]:
    resp = httpx.post(f"{base}/v1/commit/belief", json={
        "proposal_id": proposal_id, "trace_id": trace_id,
    }, timeout=5)
    assert resp.status_code == 200
    return resp.json()


def commit_action(base: str, proposal_id: str, trace_id: str,
                  require_prediction: bool = False) -> Dict[str, Any]:
    resp = httpx.post(f"{base}/v1/commit/action", json={
        "proposal_id": proposal_id, "trace_id": trace_id,
        "require_prediction": require_prediction,
    }, timeout=5)
    assert resp.status_code == 200
    return resp.json()


def commit_prediction(base: str, proposal_id: str,
                      trace_id: str) -> Dict[str, Any]:
    resp = httpx.post(f"{base}/v1/commit/prediction", json={
        "proposal_id": proposal_id, "trace_id": trace_id,
    }, timeout=5)
    assert resp.status_code == 200
    return resp.json()


def validate_plan(base: str, proposal_id: str,
                  trace_id: str) -> Dict[str, Any]:
    resp = httpx.post(f"{base}/v1/validate/plan", json={
        "proposal_id": proposal_id, "trace_id": trace_id,
    }, timeout=5)
    assert resp.status_code == 200
    return resp.json()


def get_view(base: str, trace_id: str) -> Dict[str, Any]:
    resp = httpx.get(f"{base}/v1/view/{trace_id}", timeout=5)
    assert resp.status_code == 200
    return resp.json()


# ── Tests ────────────────────────────────────────────────────────────

class TestHealthChecks:
    def test_healthz(self, base_url: str):
        resp = httpx.get(f"{base_url}/healthz", timeout=5)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_readyz(self, base_url: str):
        resp = httpx.get(f"{base_url}/readyz", timeout=5)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
        assert data["store"] == "memory"


class TestFullPipelineClean:
    """Happy path: percepts → belief → plan → prediction → action → verify view."""

    def test_full_pipeline(self, base_url: str):
        tid = "e2e-clean"

        # 1. Commit percept (tool writes charge data)
        percept = write(base_url, "tool", "percepts", "COMMIT", "charge", {
            "charge_id": "ch_E2E001",
            "amount": 299.99,
            "currency": "usd",
            "status": "disputed",
            "stale": False,
            "conflict": False,
            "customer_id": "cus_E2E",
        }, tid, confidence=0.95)
        assert percept["record"]["slot"] == "percepts"
        assert percept["record"]["status"] == "ACTIVE"

        # 2. Commit constraint
        write(base_url, "symbolic_validator", "constraints", "COMMIT",
              "no_duplicate_refund", {
                  "enabled": True,
                  "blocks_field": "is_duplicate",
              }, tid)

        # 3. Propose belief
        belief_prop = write(base_url, "planner", "beliefs", "PROPOSE",
                            "refund_due", {
                                "value": True,
                                "depends_on": ["charge"],
                            }, tid)
        belief_id = belief_prop["record"]["id"]

        # 4. Commit belief (evidence validation + confidence check)
        result = commit_belief(base_url, belief_id, tid)
        assert result["ok"] is True
        assert result["code"] == "COMMITTED"

        # 5. Propose plan
        plan_prop = write(base_url, "planner", "plans", "PROPOSE",
                          "refund_plan", {
                              "steps": [{"action": "issue_refund",
                                         "requires_beliefs": ["refund_due"]}],
                          }, tid)
        plan_id = plan_prop["record"]["id"]

        # 6. Validate plan (feasibility check)
        result = validate_plan(base_url, plan_id, tid)
        assert result["ok"] is True
        assert result["code"] == "PLAN_FEASIBLE"

        # 7. Propose prediction
        pred_prop = write(base_url, "planner", "predictions", "PROPOSE",
                          "pred_refund", {
                              "action_type": "issue_refund",
                              "expected_outcome": 1.0,
                              "requires_beliefs": ["refund_due"],
                          }, tid)
        pred_id = pred_prop["record"]["id"]

        # 8. Commit prediction
        result = commit_prediction(base_url, pred_id, tid)
        assert result["ok"] is True
        assert result["code"] == "COMMITTED"

        # 9. Propose action
        action_prop = write(base_url, "planner", "actions", "PROPOSE",
                            "issue_refund", {
                                "type": "issue_refund",
                                "charge_id": "ch_E2E001",
                                "amount": 299.99,
                                "is_duplicate": False,
                                "requires_beliefs": ["refund_due"],
                            }, tid)
        action_id = action_prop["record"]["id"]

        # 10. Commit action (with prediction gating)
        result = commit_action(base_url, action_id, tid, require_prediction=True)
        assert result["ok"] is True
        assert result["code"] == "COMMITTED"

        # 11. Verify final blackboard state
        view = get_view(base_url, tid)
        assert view["trace_id"] == tid
        v = view["view"]

        # Percept committed
        assert "charge" in v["percepts"]
        assert v["percepts"]["charge"]["amount"] == 299.99

        # Belief committed
        assert "refund_due" in v["beliefs"]
        assert v["beliefs"]["refund_due"]["value"] is True

        # Constraint present
        assert "no_duplicate_refund" in v["constraints"]

        # Evidence artifact created by kernel
        assert len(v["evidence"]) > 0

        # Prediction committed
        assert "pred_refund" in v["predictions"]
        assert v["predictions"]["pred_refund"]["expected_outcome"] == 1.0

        # Action committed
        assert "issue_refund" in v["actions"]
        assert v["actions"]["issue_refund"]["amount"] == 299.99


class TestStaleEvidenceRejection:
    """Belief rejected because dependent percept is stale."""

    def test_stale_blocks_belief(self, base_url: str):
        tid = "e2e-stale"

        # Commit stale percept
        write(base_url, "tool", "percepts", "COMMIT", "charge", {
            "stale": True, "conflict": False,
        }, tid)

        # Propose belief depending on stale charge
        prop = write(base_url, "planner", "beliefs", "PROPOSE", "refund_due", {
            "value": True, "depends_on": ["charge"],
        }, tid)

        # Belief commit should fail
        result = commit_belief(base_url, prop["record"]["id"], tid)
        assert result["ok"] is False
        assert result["code"] == "STALE_EVIDENCE"

        # Verify: no beliefs in view
        view = get_view(base_url, tid)
        assert view["view"]["beliefs"] == {}


class TestConflictEvidenceRejection:
    """Belief rejected because dependent percept has unresolved conflict."""

    def test_conflict_blocks_belief(self, base_url: str):
        tid = "e2e-conflict"

        # Commit conflicting percept (low confidence → no arbitration)
        write(base_url, "tool", "percepts", "COMMIT", "charge", {
            "stale": False, "conflict": True,
        }, tid, confidence=0.3)

        prop = write(base_url, "planner", "beliefs", "PROPOSE", "refund_due", {
            "value": True, "depends_on": ["charge"],
        }, tid)

        result = commit_belief(base_url, prop["record"]["id"], tid)
        assert result["ok"] is False
        assert result["code"] == "UNRESOLVED_CONFLICT"

    def test_conflict_arbitrated_at_high_confidence(self, base_url: str):
        tid = "e2e-conflict-arb"

        # Conflict with high confidence → arbitrated (allowed through)
        write(base_url, "tool", "percepts", "COMMIT", "charge", {
            "stale": False, "conflict": True,
        }, tid, confidence=0.9)

        prop = write(base_url, "planner", "beliefs", "PROPOSE", "refund_due", {
            "value": True, "depends_on": ["charge"],
        }, tid)

        result = commit_belief(base_url, prop["record"]["id"], tid)
        assert result["ok"] is True
        assert result["code"] == "COMMITTED"


class TestConstraintBlocksAction:
    """Action rejected because a constraint blocks it."""

    def test_duplicate_constraint_blocks(self, base_url: str):
        tid = "e2e-blocked"

        # Setup: clean percept + committed belief + constraint
        write(base_url, "tool", "percepts", "COMMIT", "charge", {
            "stale": False, "conflict": False,
        }, tid)
        write(base_url, "symbolic_validator", "constraints", "COMMIT",
              "no_duplicate_refund", {
                  "enabled": True, "blocks_field": "is_duplicate",
              }, tid)
        prop = write(base_url, "planner", "beliefs", "PROPOSE", "refund_due", {
            "value": True, "depends_on": ["charge"],
        }, tid)
        commit_belief(base_url, prop["record"]["id"], tid)

        # Propose action with is_duplicate=True
        action_prop = write(base_url, "planner", "actions", "PROPOSE",
                            "issue_refund", {
                                "type": "issue_refund",
                                "is_duplicate": True,
                                "requires_beliefs": ["refund_due"],
                            }, tid)

        result = commit_action(base_url, action_prop["record"]["id"], tid)
        assert result["ok"] is False
        assert "BLOCKED" in result["code"]

        # No action in view
        view = get_view(base_url, tid)
        assert view["view"]["actions"] == {}


class TestNegativePredictionBlocksAction:
    """Action rejected because prediction has negative expected outcome."""

    def test_negative_prediction_blocks(self, base_url: str):
        tid = "e2e-neg-pred"

        # Setup: percept + belief
        write(base_url, "tool", "percepts", "COMMIT", "charge", {
            "stale": False, "conflict": False,
        }, tid)
        prop = write(base_url, "planner", "beliefs", "PROPOSE", "refund_due", {
            "value": True, "depends_on": ["charge"],
        }, tid)
        commit_belief(base_url, prop["record"]["id"], tid)

        # Commit negative prediction
        pred = write(base_url, "planner", "predictions", "PROPOSE",
                     "pred_refund", {
                         "action_type": "issue_refund",
                         "expected_outcome": -0.5,
                         "requires_beliefs": ["refund_due"],
                     }, tid)
        commit_prediction(base_url, pred["record"]["id"], tid)

        # Propose action
        action = write(base_url, "planner", "actions", "PROPOSE",
                       "issue_refund", {
                           "type": "issue_refund",
                           "is_duplicate": False,
                           "requires_beliefs": ["refund_due"],
                       }, tid)

        # Action gated on prediction → should fail
        result = commit_action(base_url, action["record"]["id"], tid,
                               require_prediction=True)
        assert result["ok"] is False
        assert result["code"] == "NEGATIVE_PREDICTION"


class TestPlanRejection:
    """Plan rejected because required belief is missing or unsatisfied."""

    def test_plan_missing_belief(self, base_url: str):
        tid = "e2e-plan-miss"

        # Propose plan without any beliefs committed
        plan = write(base_url, "planner", "plans", "PROPOSE", "refund_plan", {
            "steps": [{"action": "issue_refund",
                       "requires_beliefs": ["refund_due"]}],
        }, tid)

        result = validate_plan(base_url, plan["record"]["id"], tid)
        assert result["ok"] is False
        assert result["code"] == "PLAN_MISSING_BELIEF"

    def test_plan_belief_not_satisfied(self, base_url: str):
        tid = "e2e-plan-unsat"

        # Commit belief with value=False
        write(base_url, "tool", "percepts", "COMMIT", "charge", {
            "stale": False, "conflict": False,
        }, tid)
        prop = write(base_url, "planner", "beliefs", "PROPOSE", "refund_due", {
            "value": False, "depends_on": ["charge"],
        }, tid)
        commit_belief(base_url, prop["record"]["id"], tid)

        plan = write(base_url, "planner", "plans", "PROPOSE", "refund_plan", {
            "steps": [{"action": "issue_refund",
                       "requires_beliefs": ["refund_due"]}],
        }, tid)

        result = validate_plan(base_url, plan["record"]["id"], tid)
        assert result["ok"] is False
        assert result["code"] == "PLAN_BELIEF_NOT_SATISFIED"


class TestEpisodeEndpoint:
    """High-level /v1/episode exercises the full agent pipeline."""

    def test_clean_episode(self, base_url: str):
        resp = httpx.post(f"{base_url}/v1/episode", json={
            "task_inputs": {
                "chargeId": "ch_E2EFULL",
                "customerId": "cus_E2E",
                "customerName": "TestUser",
                "amount": 49.99,
                "disputeReason": "product_not_received",
            },
            "constraints": {
                "no_duplicate_refund": {"blocks_field": "is_duplicate"},
            },
        }, timeout=10)
        assert resp.status_code == 200
        data = resp.json()

        # Agent should issue refund (clean data, no perturbations)
        assert data["final"]["action_committed"] is True
        assert data["metrics"]["task_success"] == 1.0
        assert data["metrics"]["unsafe_action"] == 0.0
        assert data["metrics"]["traceability"] == 1.0
        assert "issue_refund" in data["view"]["actions"]

    def test_duplicate_episode_blocked(self, base_url: str):
        resp = httpx.post(f"{base_url}/v1/episode", json={
            "task_inputs": {
                "chargeId": "ch_DUP",
                "customerId": "cus_DUP",
                "customerName": "DupUser",
                "amount": 10.00,
                "disputeReason": "product_unacceptable",
                "is_duplicate": True,
            },
            "constraints": {
                "no_duplicate_refund": {"blocks_field": "is_duplicate"},
            },
        }, timeout=10)
        assert resp.status_code == 200
        data = resp.json()

        # Duplicate should be blocked
        assert data["final"]["action_committed"] is False
        assert data["metrics"]["unsafe_action"] == 0.0


class TestPermissionEnforcement:
    """HTTP 403 when role lacks permission for slot+mode."""

    def test_tool_cannot_commit_beliefs(self, base_url: str):
        resp = httpx.post(f"{base_url}/v1/write", json={
            "role": "tool", "slot": "beliefs", "mode": "COMMIT",
            "kind": "x", "payload": {}, "trace_id": "perm-1",
        }, timeout=5)
        assert resp.status_code == 403

    def test_planner_cannot_commit_actions(self, base_url: str):
        resp = httpx.post(f"{base_url}/v1/write", json={
            "role": "planner", "slot": "actions", "mode": "COMMIT",
            "kind": "x", "payload": {}, "trace_id": "perm-2",
        }, timeout=5)
        assert resp.status_code == 403
