from __future__ import annotations

from alethic_kernel.schema import Record, Provenance, Slot, WriteMode


class TestProvenance:
    def test_construction_minimal(self):
        p = Provenance(writer_id="tool", trace_id="t1", ts_ms=1000)
        assert p.writer_id == "tool"
        assert p.trace_id == "t1"
        assert p.ts_ms == 1000
        assert p.input_refs == []
        assert p.confidence is None
        assert p.ttl_ms is None

    def test_construction_full(self):
        p = Provenance(
            writer_id="kernel", trace_id="t2", ts_ms=2000,
            input_refs=["ref1", "ref2"], confidence=0.9, ttl_ms=5000,
        )
        assert p.input_refs == ["ref1", "ref2"]
        assert p.confidence == 0.9
        assert p.ttl_ms == 5000


class TestRecord:
    def test_construction_defaults(self):
        p = Provenance(writer_id="tool", trace_id="t1", ts_ms=1000)
        r = Record(id="r1", slot="percepts", mode="COMMIT", kind="charge",
                   payload={"a": 1}, prov=p)
        assert r.id == "r1"
        assert r.slot == "percepts"
        assert r.mode == "COMMIT"
        assert r.kind == "charge"
        assert r.payload == {"a": 1}
        assert r.evidence_refs == []
        assert r.status == "ACTIVE"
        assert r.reason is None
        assert r.scope == "episode"

    def test_construction_full(self):
        p = Provenance(writer_id="kernel", trace_id="t1", ts_ms=1000)
        r = Record(
            id="r2", slot="beliefs", mode="PROPOSE", kind="refund_due",
            payload={"value": True}, prov=p,
            evidence_refs=["ev1"], status="INVALIDATED",
            reason="test", scope="persistent",
        )
        assert r.evidence_refs == ["ev1"]
        assert r.status == "INVALIDATED"
        assert r.reason == "test"
        assert r.scope == "persistent"

    def test_slot_literal_values(self):
        valid: list[Slot] = [
            "percepts", "beliefs", "constraints", "plans",
            "evidence", "predictions", "actions",
        ]
        assert len(valid) == 7

    def test_write_mode_literal_values(self):
        valid: list[WriteMode] = ["PROPOSE", "COMMIT"]
        assert len(valid) == 2
