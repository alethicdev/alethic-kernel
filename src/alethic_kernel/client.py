"""Unified Python client for the Alethic kernel.

Works in two modes:
- **local**: creates an in-process Kernel (zero network overhead)
- **http**: calls a running Alethic API server over HTTP

Both modes expose the same interface so callers don't need to care.
"""
from __future__ import annotations

import json
import urllib.request
import urllib.error
import urllib.parse
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Tuple, cast

from .kernel import Kernel
from .store import MemoryStore
from .store_protocol import StoreProtocol
from .sqlite_store import SqliteStore
from .schema import Slot, WriteMode
from .permissions import Role


@dataclass
class EpisodeResult:
    """Result of a full agent episode."""
    trace_id: str
    final: Dict[str, Any]
    view: Dict[str, Dict[str, Any]]
    metrics: Dict[str, float]


class AlethicClient:
    """Unified client — works locally or over HTTP.

    Examples::

        # Local mode (default)
        client = AlethicClient()
        result = client.run_episode(task_inputs={"charge_id": "ch_123"})

        # HTTP mode
        client = AlethicClient(mode="http", base_url="http://localhost:8000")
        result = client.run_episode(task_inputs={"charge_id": "ch_123"})
    """

    def __init__(
        self,
        mode: Literal["local", "http"] = "local",
        base_url: str = "http://localhost:8000",
        store: Optional[StoreProtocol] = None,
    ) -> None:
        self._mode = mode
        self._base_url = base_url.rstrip("/")
        self._kernel: Optional[Kernel] = None
        self._store = store
        if mode == "local":
            self._kernel = Kernel(store=store)

    @property
    def kernel(self) -> Optional[Kernel]:
        """Direct access to the kernel in local mode (None in HTTP mode)."""
        return self._kernel

    # ── High-level API ────────────────────────────────────────────────

    def run_episode(
        self,
        task_inputs: Dict[str, Any],
        constraints: Optional[Dict[str, Any]] = None,
        agent: str = "alethic",
    ) -> EpisodeResult:
        """Run a full governance episode.

        In local mode, executes the AlethicAgent pipeline directly.
        In HTTP mode, calls POST /v1/episode on the remote server.
        """
        constraints = constraints or {}

        if self._mode == "http":
            return self._http_episode(task_inputs, constraints, agent)
        return self._local_episode(task_inputs, constraints)

    # ── Low-level API (mirrors kernel) ────────────────────────────────

    def write(
        self,
        role: Role,
        slot: Slot,
        mode: WriteMode,
        kind: str,
        payload: Dict[str, Any],
        trace_id: str,
        input_refs: Optional[List[str]] = None,
        confidence: Optional[float] = None,
        ttl_ms: Optional[int] = None,
        scope: Literal["episode", "persistent"] = "episode",
    ) -> Dict[str, Any]:
        """Write a record to the kernel."""
        if self._mode == "local":
            if self._kernel is None:
                raise RuntimeError("Kernel not initialized in local mode")
            rec = self._kernel.write(
                role, slot, mode, kind, payload, trace_id,
                input_refs=input_refs, confidence=confidence,
                ttl_ms=ttl_ms, scope=scope,
            )
            return {"ok": True, "record": {"id": rec.id, "status": rec.status}}
        return self._post("/v1/write", {
            "role": role, "slot": slot, "mode": mode,
            "kind": kind, "payload": payload, "trace_id": trace_id,
            "input_refs": input_refs or [], "confidence": confidence,
            "ttl_ms": ttl_ms, "scope": scope,
        })

    def commit_belief(self, proposal_id: str, trace_id: str) -> Tuple[bool, str]:
        """Commit a belief proposal."""
        if self._mode == "local":
            if self._kernel is None:
                raise RuntimeError("Kernel not initialized in local mode")
            return self._kernel.commit_belief_from_proposal(proposal_id, trace_id)
        resp = self._post("/v1/commit/belief", {
            "proposal_id": proposal_id, "trace_id": trace_id,
        })
        return resp["ok"], resp["code"]

    def commit_action(
        self,
        proposal_id: str,
        trace_id: str,
        require_prediction: bool = False,
    ) -> Tuple[bool, str]:
        """Commit an action proposal."""
        if self._mode == "local":
            if self._kernel is None:
                raise RuntimeError("Kernel not initialized in local mode")
            return self._kernel.commit_action_from_proposal(
                proposal_id, trace_id, require_prediction=require_prediction,
            )
        resp = self._post("/v1/commit/action", {
            "proposal_id": proposal_id, "trace_id": trace_id,
            "require_prediction": require_prediction,
        })
        return resp["ok"], resp["code"]

    def commit_prediction(self, proposal_id: str, trace_id: str) -> Tuple[bool, str]:
        """Commit a prediction proposal."""
        if self._mode == "local":
            if self._kernel is None:
                raise RuntimeError("Kernel not initialized in local mode")
            return self._kernel.commit_prediction(proposal_id, trace_id)
        resp = self._post("/v1/commit/prediction", {
            "proposal_id": proposal_id, "trace_id": trace_id,
        })
        return resp["ok"], resp["code"]

    def validate_plan(self, proposal_id: str, trace_id: str) -> Tuple[bool, str]:
        """Validate a plan proposal."""
        if self._mode == "local":
            if self._kernel is None:
                raise RuntimeError("Kernel not initialized in local mode")
            return self._kernel.validate_plan(proposal_id, trace_id)
        resp = self._post("/v1/validate/plan", {
            "proposal_id": proposal_id, "trace_id": trace_id,
        })
        return resp["ok"], resp["code"]

    def current_view(
        self,
        trace_id: str,
        include_persistent: bool = False,
    ) -> Dict[str, Dict[str, Any]]:
        """Get the current blackboard view."""
        if self._mode == "local":
            if self._kernel is None:
                raise RuntimeError("Kernel not initialized in local mode")
            return self._kernel.current_view(trace_id, include_persistent=include_persistent)
        resp = self._get(
            f"/v1/view/{trace_id}",
            params={"include_persistent": str(include_persistent).lower()},
        )
        return cast(Dict[str, Dict[str, Any]], resp["view"])

    def health(self) -> Dict[str, str]:
        """Check server health (HTTP mode) or return local status."""
        if self._mode == "local":
            return {"status": "ok", "mode": "local"}
        return self._get("/healthz")

    # ── Internal ──────────────────────────────────────────────────────

    def _local_episode(
        self,
        task_inputs: Dict[str, Any],
        constraints: Dict[str, Any],
    ) -> EpisodeResult:
        from .tools.payment_tool import PaymentTool
        from .tools.refund_tool import RefundTool
        from .tools.perturb import PerturbConfig
        from .agents.alethic_agent import AlethicAgent
        from .eval.metrics import compute_metrics

        kernel = self._kernel if self._kernel is not None else Kernel()
        cfg = PerturbConfig(
            tool_drop_rate=0.0, stale_rate=0.0,
            conflict_rate=0.0, low_confidence_rate=0.0,
        )
        payment_tool = PaymentTool(cfg)
        refund_tool = RefundTool()
        agent = AlethicAgent(kernel, payment_tool, refund_tool)
        output = agent.run(0, "client_episode", task_inputs, constraints)
        metrics = compute_metrics(
            "alethic", output,
            task_constraints=constraints,
            task_inputs=task_inputs,
        )
        return EpisodeResult(
            trace_id=output["trace_id"],
            final=output["final"],
            view=output["view"],
            metrics=metrics,
        )

    def _http_episode(
        self,
        task_inputs: Dict[str, Any],
        constraints: Dict[str, Any],
        agent: str,
    ) -> EpisodeResult:
        resp = self._post("/v1/episode", {
            "task_inputs": task_inputs,
            "constraints": constraints,
            "agent": agent,
        })
        return EpisodeResult(
            trace_id=resp["trace_id"],
            final=resp["final"],
            view=resp["view"],
            metrics=resp["metrics"],
        )

    def _post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            f"{self._base_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                result: Dict[str, Any] = json.loads(resp.read().decode("utf-8"))
                return result
        except urllib.error.HTTPError as e:
            body_text = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Alethic API error {e.code} on POST {path}: {body_text}"
            ) from e

    def _get(
        self,
        path: str,
        params: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        url = f"{self._base_url}{path}"
        if params:
            qs = urllib.parse.urlencode(params)
            url = f"{url}?{qs}"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req) as resp:
                result: Dict[str, Any] = json.loads(resp.read().decode("utf-8"))
                return result
        except urllib.error.HTTPError as e:
            body_text = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Alethic API error {e.code} on GET {path}: {body_text}"
            ) from e
