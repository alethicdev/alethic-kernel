from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Literal

Slot = Literal["percepts","beliefs","constraints","plans","evidence","predictions","actions"]
WriteMode = Literal["PROPOSE","COMMIT"]


class RecordIdConflict(Exception):
    """A record with this id already exists.

    Records are an append-only audit trail, so a store must refuse to replace
    one rather than silently overwrite it. Raised by every store so callers can
    react without knowing which backend they hold.
    """

@dataclass
class Provenance:
    writer_id: str
    trace_id: str
    ts_ms: int
    input_refs: List[str] = field(default_factory=list)
    confidence: Optional[float] = None
    ttl_ms: Optional[int] = None

@dataclass
class Record:
    id: str
    slot: Slot
    mode: WriteMode
    kind: str
    payload: Dict[str, Any]
    prov: Provenance
    evidence_refs: List[str] = field(default_factory=list)
    status: Literal["ACTIVE","INVALIDATED","EXPIRED"] = "ACTIVE"
    reason: Optional[str] = None
    scope: Literal["episode", "persistent"] = "episode"
