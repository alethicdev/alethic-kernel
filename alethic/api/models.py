"""Pydantic request/response models for the Alethic API."""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ── Shared types ─────────────────────────────────────────────────────

SlotType = Literal[
    "percepts", "beliefs", "constraints", "plans",
    "evidence", "predictions", "actions",
]
WriteModeType = Literal["PROPOSE", "COMMIT"]
RoleType = Literal[
    "kernel", "tool", "planner", "symbolic_validator",
    "evidence_validator", "sim_validator",
]


# ── Write ────────────────────────────────────────────────────────────

class WriteRequest(BaseModel):
    role: RoleType
    slot: SlotType
    mode: WriteModeType
    kind: str
    payload: Dict[str, Any]
    trace_id: str
    input_refs: List[str] = Field(default_factory=list)
    # ge/le also rejects the bare NaN literal that JSON permits.
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    ttl_ms: Optional[int] = None
    evidence_refs: List[str] = Field(default_factory=list)
    scope: Literal["episode", "persistent"] = "episode"


class RecordResponse(BaseModel):
    id: str
    slot: str
    mode: str
    kind: str
    payload: Dict[str, Any]
    status: str
    scope: str
    trace_id: str
    confidence: Optional[float] = None


class WriteResponse(BaseModel):
    ok: bool
    record: RecordResponse


# ── Commit / Validate ────────────────────────────────────────────────

class CommitRequest(BaseModel):
    proposal_id: str
    trace_id: str


class ActionCommitRequest(BaseModel):
    proposal_id: str
    trace_id: str
    require_prediction: bool = False


class CommitResponse(BaseModel):
    ok: bool
    code: str


# ── View ─────────────────────────────────────────────────────────────

class ViewResponse(BaseModel):
    trace_id: str
    view: Dict[str, Dict[str, Any]]


# ── Episode (high-level) ─────────────────────────────────────────────

class EpisodeRequest(BaseModel):
    task_inputs: Dict[str, Any]
    constraints: Dict[str, Any] = Field(default_factory=dict)
    agent: Literal["alethic"] = "alethic"


class EpisodeResponse(BaseModel):
    trace_id: str
    final: Dict[str, Any]
    view: Dict[str, Dict[str, Any]]
    metrics: Dict[str, float]


# ── Health ───────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str


class ReadyResponse(BaseModel):
    status: str
    store: str
