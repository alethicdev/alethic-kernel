"""Tests specifically targeting uncovered lines to reach 100% coverage."""
from __future__ import annotations

import os
import time
import unittest.mock as mock
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

from alethic_kernel.adaptive_worker import AdaptiveWorker
from alethic_kernel.api.app import create_app
from alethic_kernel.api.dependencies import reset_shared_state
from alethic_kernel.client import AlethicClient
from alethic_kernel.kernel import Kernel
from alethic_kernel.orchestrator import Orchestrator
from alethic_kernel.schema import Record, Provenance
from alethic_kernel.sim_worker import SimRule, SimulatorWorker
from alethic_kernel.sqlite_store import SqliteStore
from alethic_kernel.store import MemoryStore
from alethic_kernel.worker import BaseWorker

from tests.helpers import make_record


# ── BaseWorker defaults (worker.py:38, 42) ──────────────────────────

class TestBaseWorkerDefaults:
    def test_should_activate_returns_false(self):
        w = BaseWorker(worker_id="test", role="tool")
        assert w.should_activate({}) is False

    def test_step_returns_false(self):
        w = BaseWorker(worker_id="test", role="tool")
        kernel = Kernel()
        assert w.step(kernel, "trace", {}) is False


# ── AdaptiveWorker unknown reason (adaptive_worker.py:92) ───────────

class TestAdaptiveWorkerUnknownReasonAboveThreshold:
    def test_unknown_reason_above_threshold_skipped(self):
        """Reason above threshold but with no mapping → continue (line 92)."""
        store = MemoryStore()
        # Write records invalidated with a reason not in reason_to_constraint
        for i in range(3):
            rec = make_record(rec_id=f"b:t:{i}", slot="beliefs")
            store.append(rec)
            store.invalidate(f"b:t:{i}", "SOME_UNKNOWN_REASON")

        worker = AdaptiveWorker(
            worker_id="adaptive", role="symbolic_validator",
            failure_threshold=2,
        )
        result = worker.analyze(store)
        # No constraint queued because SOME_UNKNOWN_REASON has no mapping
        assert result == []
        assert len(worker._queued) == 0


# ── Orchestrator default error handler (orchestrator.py:98) ─────────

class TestOrchestratorDefaultErrorPrint:
    def test_error_without_callback_prints_to_stderr(self, capsys):
        """Error in step with no on_error callback → prints to stderr."""
        class FailWorker(BaseWorker):
            def should_activate(self, view: Dict[str, Dict[str, Any]]) -> bool:
                return True
            def step(self, kernel: Any, trace_id: str,
                     view: Dict[str, Dict[str, Any]]) -> bool:
                raise ValueError("boom")

        kernel = Kernel()
        worker = FailWorker(
            worker_id="fail", role="tool",
            reads=frozenset(), writes=frozenset(["percepts"]),
        )
        # No on_error callback
        orch = Orchestrator(kernel, [worker], max_rounds=1)
        result = orch.run("test-trace")
        captured = capsys.readouterr()
        assert "boom" in captured.err
        assert len(result.errors) == 1


# ── SimulatorWorker multi-rule with non-matching (sim_worker.py:145) ─

class TestSimulatorWorkerRuleSkip:
    def test_non_matching_rule_skipped(self):
        """A rule whose conditions don't match → continue (line 145)."""
        # Rule 1: matches (will produce prediction)
        matching_rule = SimRule(
            action_type="alert",
            expected_outcome=1.0,
            requires_beliefs=["anomaly"],
            percept_conditions={},
            belief_conditions={},
        )
        # Rule 2: doesn't match (missing required belief)
        non_matching_rule = SimRule(
            action_type="shutdown",
            expected_outcome=-1.0,
            requires_beliefs=["critical_failure"],
            percept_conditions={},
            belief_conditions={},
        )

        kernel = Kernel()
        trace = "test-trace"

        # Commit the belief that rule 1 needs
        kernel.write("tool", "percepts", "COMMIT", "sensor", {"value": 95}, trace)
        prop = kernel.write("planner", "beliefs", "PROPOSE", "anomaly",
                            {"value": True, "depends_on": ["sensor"]}, trace)
        kernel.commit_belief_from_proposal(prop.id, trace)

        worker = SimulatorWorker(
            worker_id="sim", role="sim_validator",
            rules=[matching_rule, non_matching_rule],
        )
        view = kernel.current_view(trace)
        assert worker.should_activate(view)
        produced = worker.step(kernel, trace, view)
        assert produced is True

        # Only alert prediction committed (pred_alert), not shutdown (pred_shutdown)
        final_view = kernel.current_view(trace)
        assert "pred_alert" in final_view["predictions"]
        assert "pred_shutdown" not in final_view["predictions"]


# ── SqliteStore find_active_by_kind TTL expiry (sqlite_store.py:100) ─

class TestSqliteStoreFindActiveByKindTTLExpiry:
    def test_ttl_expired_during_find(self):
        """Record found by kind but TTL expired → return None (line 100)."""
        store = SqliteStore(":memory:")
        rec = make_record(rec_id="p:t:1", kind="charge", trace_id="t1", ttl_ms=1)
        rec.prov.ts_ms = int(time.time() * 1000) - 2000  # expired
        store.append(rec)
        result = store.find_active_by_kind("percepts", "charge", "t1")
        assert result is None
        store.close()


# ── Kernel validate_plan non-dict constraint (kernel.py:156) ────────

class TestKernelValidatePlanNonDictConstraint:
    def test_non_dict_constraint_skipped(self):
        """Constraint value that is not a dict → continue (line 155-156)."""
        kernel = Kernel()
        trace = "test-trace"

        # Commit a belief
        kernel.write("tool", "percepts", "COMMIT", "charge", {"amount": 100}, trace)
        bp = kernel.write("planner", "beliefs", "PROPOSE", "refund_due",
                          {"value": True, "depends_on": ["charge"]}, trace)
        kernel.commit_belief_from_proposal(bp.id, trace)

        # Commit a non-dict constraint (e.g., a string)
        kernel.write("symbolic_validator", "constraints", "COMMIT", "legacy_flag",
                      "just_a_string", trace)

        # Commit a disabled dict constraint
        kernel.write("symbolic_validator", "constraints", "COMMIT", "disabled_one",
                      {"enabled": False, "blocks_field": "something"}, trace)

        # Propose plan
        plan = kernel.write("planner", "plans", "PROPOSE", "refund_plan",
                            {"steps": [{"requires_beliefs": ["refund_due"]}]},
                            trace)
        ok, code = kernel.validate_plan(plan.id, trace)
        assert ok is True
        assert code == "PLAN_FEASIBLE"


# ── API sqlite store mode (dependencies.py:19-20) ──────────────────

class TestAPISqliteStoreMode:
    def test_sqlite_store_write_and_readyz(self, tmp_path):
        """Exercise _create_store() sqlite branch (dependencies.py:19-20)."""
        reset_shared_state()
        db_path = str(tmp_path / "test.db")
        os.environ["ALETHIC_STORE"] = "sqlite"
        os.environ["ALETHIC_DB_PATH"] = db_path
        try:
            app = create_app()
            client = TestClient(app)
            # readyz checks store type
            resp = client.get("/readyz")
            assert resp.status_code == 200
            assert resp.json()["store"] == "sqlite"
            # write triggers get_shared_kernel() → _create_store() → SqliteStore
            resp = client.post("/v1/write", json={
                "role": "tool", "slot": "percepts", "mode": "COMMIT",
                "kind": "charge", "payload": {"x": 1}, "trace_id": "t1",
            })
            assert resp.status_code == 200
        finally:
            os.environ.pop("ALETHIC_STORE", None)
            os.environ.pop("ALETHIC_DB_PATH", None)
            reset_shared_state()


# ── API lifespan shutdown (app.py:15-16) ────────────────────────────

class TestAPILifespan:
    def test_lifespan_resets_on_shutdown(self):
        """Lifespan context manager resets shared state on exit."""
        reset_shared_state()
        app = create_app()
        with TestClient(app) as client:
            # Write something to create shared state
            client.post("/v1/write", json={
                "role": "tool", "slot": "percepts", "mode": "COMMIT",
                "kind": "charge", "payload": {"x": 1}, "trace_id": "t1",
            })
        # After exiting TestClient context, lifespan shutdown fires
        # Create a new app/client — shared state should be fresh
        reset_shared_state()
        app2 = create_app()
        with TestClient(app2) as client2:
            resp = client2.get("/v1/view/t1")
            view = resp.json()["view"]
            # Fresh state — no percepts from previous app
            assert view["percepts"] == {}


# ── API tracing with mocked OpenTelemetry (tracing.py:14-15, 25) ───

class TestTracingWithOTel:
    def test_span_with_mocked_tracer(self):
        """Exercise the OTel branch by patching module globals."""
        import alethic_kernel.api.tracing as tracing_mod

        mock_span = mock.MagicMock()
        mock_span.__enter__ = mock.MagicMock(return_value=mock_span)
        mock_span.__exit__ = mock.MagicMock(return_value=False)

        mock_tracer = mock.MagicMock()
        mock_tracer.start_as_current_span.return_value = mock_span

        old_has_otel = tracing_mod._HAS_OTEL
        old_tracer = tracing_mod._tracer
        try:
            tracing_mod._HAS_OTEL = True
            tracing_mod._tracer = mock_tracer
            with tracing_mod.span("test.operation", key="value") as s:
                assert s is mock_span
            mock_tracer.start_as_current_span.assert_called_once_with(
                "test.operation", attributes={"key": "value"}
            )
        finally:
            tracing_mod._HAS_OTEL = old_has_otel
            tracing_mod._tracer = old_tracer

    def test_span_noop_when_disabled(self):
        """Exercise the no-op branch (tracing.py:25) by disabling OTel."""
        import alethic_kernel.api.tracing as tracing_mod

        old_has_otel = tracing_mod._HAS_OTEL
        old_tracer = tracing_mod._tracer
        try:
            tracing_mod._HAS_OTEL = False
            tracing_mod._tracer = None
            with tracing_mod.span("noop.span") as s:
                assert s is None
        finally:
            tracing_mod._HAS_OTEL = old_has_otel
            tracing_mod._tracer = old_tracer


# ── Client HTTP mode (client.py all HTTP paths) ─────────────────────

class TestClientRealHTTPMethods:
    """Test the actual urllib-based _post and _get methods via mocking."""

    def test_post_success(self):
        client = AlethicClient(mode="http", base_url="http://localhost:9999")
        response_data = b'{"ok": true, "record": {"id": "p:t:1", "status": "ACTIVE"}}'
        mock_resp = mock.MagicMock()
        mock_resp.read.return_value = response_data
        mock_resp.__enter__ = mock.MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = mock.MagicMock(return_value=False)

        with mock.patch("urllib.request.urlopen", return_value=mock_resp):
            result = client._post("/v1/write", {"role": "tool"})
        assert result["ok"] is True

    def test_post_http_error(self):
        import urllib.error
        client = AlethicClient(mode="http", base_url="http://localhost:9999")
        error = urllib.error.HTTPError(
            "http://localhost:9999/v1/write", 403, "Forbidden",
            {}, mock.MagicMock(read=mock.MagicMock(return_value=b'{"detail":"forbidden"}'))
        )
        error.read = mock.MagicMock(return_value=b'{"detail":"forbidden"}')
        with mock.patch("urllib.request.urlopen", side_effect=error):
            with pytest.raises(RuntimeError, match="403"):
                client._post("/v1/write", {"role": "tool"})

    def test_get_success(self):
        client = AlethicClient(mode="http", base_url="http://localhost:9999")
        response_data = b'{"status": "ok"}'
        mock_resp = mock.MagicMock()
        mock_resp.read.return_value = response_data
        mock_resp.__enter__ = mock.MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = mock.MagicMock(return_value=False)

        with mock.patch("urllib.request.urlopen", return_value=mock_resp):
            result = client._get("/healthz")
        assert result["status"] == "ok"

    def test_get_with_params(self):
        client = AlethicClient(mode="http", base_url="http://localhost:9999")
        response_data = b'{"trace_id": "t1", "view": {}}'
        mock_resp = mock.MagicMock()
        mock_resp.read.return_value = response_data
        mock_resp.__enter__ = mock.MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = mock.MagicMock(return_value=False)

        with mock.patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            client._get("/v1/view/t1", params={"include_persistent": "true"})
        called_url = mock_open.call_args[0][0].full_url
        assert "include_persistent=true" in called_url

    def test_get_http_error(self):
        import urllib.error
        client = AlethicClient(mode="http", base_url="http://localhost:9999")
        error = urllib.error.HTTPError(
            "http://localhost:9999/healthz", 500, "Server Error",
            {}, mock.MagicMock(read=mock.MagicMock(return_value=b"internal error"))
        )
        error.read = mock.MagicMock(return_value=b"internal error")
        with mock.patch("urllib.request.urlopen", side_effect=error):
            with pytest.raises(RuntimeError, match="500"):
                client._get("/healthz")


class TestClientHTTPWithTestServer:
    """Exercise all HTTP code paths using a real FastAPI TestClient."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        reset_shared_state()
        yield
        reset_shared_state()

    def _make_http_client(self) -> tuple[AlethicClient, TestClient]:
        """Create a client that routes through TestClient instead of urllib."""
        app = create_app()
        test_client = TestClient(app)
        client = AlethicClient(mode="http", base_url="http://testserver")
        # Monkey-patch _post and _get to use TestClient
        def _post(path: str, body: dict) -> dict:
            resp = test_client.post(path, json=body)
            if resp.status_code >= 400:
                raise RuntimeError(f"API error {resp.status_code}: {resp.text}")
            return resp.json()

        def _get(path: str, params: dict = None) -> dict:
            resp = test_client.get(path, params=params)
            if resp.status_code >= 400:
                raise RuntimeError(f"API error {resp.status_code}: {resp.text}")
            return resp.json()

        client._post = _post  # type: ignore[assignment]
        client._get = _get  # type: ignore[assignment]
        return client, test_client

    def test_health_http(self):
        client, _ = self._make_http_client()
        h = client.health()
        assert h["status"] == "ok"

    def test_write_http(self):
        client, _ = self._make_http_client()
        result = client.write(
            "tool", "percepts", "COMMIT", "charge",
            {"amount": 100}, "t1", confidence=0.9,
        )
        assert result["ok"] is True

    def test_current_view_http(self):
        client, _ = self._make_http_client()
        client.write("tool", "percepts", "COMMIT", "charge",
                      {"amount": 100}, "t1")
        view = client.current_view("t1")
        assert "charge" in view["percepts"]

    def test_commit_belief_http(self):
        client, _ = self._make_http_client()
        client.write("tool", "percepts", "COMMIT", "charge",
                      {"amount": 100}, "t1", confidence=0.9)
        bp = client.write("planner", "beliefs", "PROPOSE", "refund_due",
                           {"value": True, "depends_on": ["charge"]}, "t1")
        ok, code = client.commit_belief(bp["record"]["id"], "t1")
        assert ok is True
        assert code == "COMMITTED"

    def test_commit_action_http(self):
        client, _ = self._make_http_client()
        client.write("tool", "percepts", "COMMIT", "charge",
                      {"amount": 100}, "t1", confidence=0.9)
        bp = client.write("planner", "beliefs", "PROPOSE", "refund_due",
                           {"value": True, "depends_on": ["charge"]}, "t1")
        client.commit_belief(bp["record"]["id"], "t1")
        client.write("symbolic_validator", "constraints", "COMMIT",
                      "no_dup", {"enabled": True, "blocks_field": "is_duplicate"}, "t1")
        ap = client.write("planner", "actions", "PROPOSE", "issue_refund",
                           {"type": "issue_refund", "requires_beliefs": ["refund_due"]}, "t1")
        ok, code = client.commit_action(ap["record"]["id"], "t1")
        assert ok is True

    def test_commit_prediction_http(self):
        client, _ = self._make_http_client()
        client.write("tool", "percepts", "COMMIT", "charge",
                      {"amount": 100}, "t1", confidence=0.9)
        bp = client.write("planner", "beliefs", "PROPOSE", "refund_due",
                           {"value": True, "depends_on": ["charge"]}, "t1")
        client.commit_belief(bp["record"]["id"], "t1")
        pp = client.write("planner", "predictions", "PROPOSE", "outcome",
                           {"action_type": "refund", "expected_outcome": 1,
                            "requires_beliefs": ["refund_due"]}, "t1")
        ok, code = client.commit_prediction(pp["record"]["id"], "t1")
        assert ok is True

    def test_validate_plan_http(self):
        client, _ = self._make_http_client()
        client.write("tool", "percepts", "COMMIT", "charge",
                      {"amount": 100}, "t1", confidence=0.9)
        bp = client.write("planner", "beliefs", "PROPOSE", "refund_due",
                           {"value": True, "depends_on": ["charge"]}, "t1")
        client.commit_belief(bp["record"]["id"], "t1")
        pp = client.write("planner", "plans", "PROPOSE", "plan",
                           {"steps": [{"requires_beliefs": ["refund_due"]}]}, "t1")
        ok, code = client.validate_plan(pp["record"]["id"], "t1")
        assert ok is True
        assert code == "PLAN_FEASIBLE"

    def test_run_episode_http(self):
        client, _ = self._make_http_client()
        result = client.run_episode(
            task_inputs={
                "chargeId": "ch_test", "customerId": "cus_test",
                "amount": 100, "currency": "usd", "is_duplicate": False,
            },
            constraints={"no_duplicate_refund": {"blocks_field": "is_duplicate"}},
        )
        assert result.trace_id
        assert result.metrics["unsafe_action"] == 0.0
