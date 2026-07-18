"""API endpoint definitions."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from ..kernel import Kernel
from .models import (
    WriteRequest, WriteResponse, RecordResponse,
    CommitRequest, ActionCommitRequest, CommitResponse,
    ViewResponse,
    EpisodeRequest, EpisodeResponse,
    HealthResponse, ReadyResponse,
)
from .dependencies import get_shared_kernel, get_ephemeral_kernel, _get_store_type
from .tracing import span

router = APIRouter()


def _record_to_response(rec: Any) -> RecordResponse:
    return RecordResponse(
        id=rec.id,
        slot=rec.slot,
        mode=rec.mode,
        kind=rec.kind,
        payload=rec.payload,
        status=rec.status,
        scope=rec.scope,
        trace_id=rec.prov.trace_id,
        confidence=rec.prov.confidence,
    )


# ── Health ───────────────────────────────────────────────────────────

@router.get("/healthz", response_model=HealthResponse)
def healthz() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/readyz", response_model=ReadyResponse)
def readyz() -> ReadyResponse:
    return ReadyResponse(status="ready", store=_get_store_type())


# ── Low-level kernel API ─────────────────────────────────────────────

@router.post("/v1/write", response_model=WriteResponse)
def write(req: WriteRequest) -> WriteResponse:
    kernel = get_shared_kernel()
    with span("kernel.write", slot=req.slot, kind=req.kind):
        try:
            rec = kernel.write(
                req.role, req.slot, req.mode, req.kind, req.payload,
                req.trace_id, input_refs=req.input_refs,
                confidence=req.confidence, ttl_ms=req.ttl_ms,
                evidence_refs=req.evidence_refs, scope=req.scope,
            )
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=str(e))
    return WriteResponse(ok=True, record=_record_to_response(rec))


@router.post("/v1/commit/belief", response_model=CommitResponse)
def commit_belief(req: CommitRequest) -> CommitResponse:
    kernel = get_shared_kernel()
    with span("kernel.commit_belief", proposal_id=req.proposal_id):
        ok, code = kernel.commit_belief_from_proposal(req.proposal_id, req.trace_id)
    return CommitResponse(ok=ok, code=code)


@router.post("/v1/commit/action", response_model=CommitResponse)
def commit_action(req: ActionCommitRequest) -> CommitResponse:
    kernel = get_shared_kernel()
    with span("kernel.commit_action", proposal_id=req.proposal_id):
        ok, code = kernel.commit_action_from_proposal(
            req.proposal_id, req.trace_id,
            require_prediction=req.require_prediction,
        )
    return CommitResponse(ok=ok, code=code)


@router.post("/v1/commit/prediction", response_model=CommitResponse)
def commit_prediction(req: CommitRequest) -> CommitResponse:
    kernel = get_shared_kernel()
    with span("kernel.commit_prediction", proposal_id=req.proposal_id):
        ok, code = kernel.commit_prediction(req.proposal_id, req.trace_id)
    return CommitResponse(ok=ok, code=code)


@router.post("/v1/validate/plan", response_model=CommitResponse)
def validate_plan(req: CommitRequest) -> CommitResponse:
    kernel = get_shared_kernel()
    with span("kernel.validate_plan", proposal_id=req.proposal_id):
        ok, code = kernel.validate_plan(req.proposal_id, req.trace_id)
    return CommitResponse(ok=ok, code=code)


@router.get("/v1/view/{trace_id}", response_model=ViewResponse)
def get_view(trace_id: str, include_persistent: bool = False) -> ViewResponse:
    kernel = get_shared_kernel()
    with span("kernel.current_view", trace_id=trace_id):
        view = kernel.current_view(trace_id, include_persistent=include_persistent)
    return ViewResponse(trace_id=trace_id, view=view)


# ── High-level episode API ───────────────────────────────────────────

@router.post("/v1/episode", response_model=EpisodeResponse)
def run_episode(req: EpisodeRequest) -> EpisodeResponse:
    """Run a full agent episode. Creates a fresh kernel per request."""
    from ..tools.payment_tool import PaymentTool
    from ..tools.refund_tool import RefundTool
    from ..tools.perturb import PerturbConfig
    from ..agents.alethic_agent import AlethicAgent
    from ..eval.metrics import compute_metrics

    with span("episode", agent=req.agent):
        kernel = get_ephemeral_kernel()
        cfg = PerturbConfig(
            tool_drop_rate=0.0, stale_rate=0.0,
            conflict_rate=0.0, low_confidence_rate=0.0,
        )
        payment_tool = PaymentTool(cfg)
        refund_tool = RefundTool()

        agent = AlethicAgent(kernel, payment_tool, refund_tool)
        output = agent.run(0, "api_episode", req.task_inputs, req.constraints)
        metrics = compute_metrics(
            "alethic", output,
            task_constraints=req.constraints,
            task_inputs=req.task_inputs,
        )

    return EpisodeResponse(
        trace_id=output["trace_id"],
        final=output["final"],
        view=output["view"],
        metrics=metrics,
    )
