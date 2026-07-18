from __future__ import annotations

import time

from alethic.schema import Record, Provenance


def make_record(
    rec_id: str = "test:trace:1",
    slot: str = "percepts",
    mode: str = "COMMIT",
    kind: str = "charge",
    payload: dict | None = None,
    trace_id: str = "test-trace-001",
    confidence: float | None = None,
    ttl_ms: int | None = None,
    scope: str = "episode",
) -> Record:
    return Record(
        id=rec_id,
        slot=slot,
        mode=mode,
        kind=kind,
        payload=payload or {"value": True},
        prov=Provenance(
            writer_id="tool",
            trace_id=trace_id,
            ts_ms=int(time.time() * 1000),
            input_refs=[],
            confidence=confidence,
            ttl_ms=ttl_ms,
        ),
        scope=scope,
    )
