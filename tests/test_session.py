"""Tests for alethic_kernel/session.py."""
from __future__ import annotations

from alethic_kernel.session import Session


class TestSession:
    def test_session_id_generated(self):
        s = Session()
        assert len(s.session_id) == 12

    def test_session_id_hex(self):
        s = Session()
        int(s.session_id, 16)  # should not raise

    def test_custom_session_id(self):
        s = Session(session_id="custom123")
        assert s.session_id == "custom123"

    def test_metadata_default_empty(self):
        s = Session()
        assert s.metadata == {}

    def test_metadata_custom(self):
        s = Session(metadata={"env": "test"})
        assert s.metadata["env"] == "test"


class TestEpisodeTraceId:
    def test_format(self):
        s = Session(session_id="abc123def456")
        tid = s.episode_trace_id()
        assert tid.startswith("abc123def456-ep1-")
        assert len(tid.split("-")) == 3

    def test_counter_increments(self):
        s = Session(session_id="abc123def456")
        t1 = s.episode_trace_id()
        t2 = s.episode_trace_id()
        assert "-ep1-" in t1
        assert "-ep2-" in t2

    def test_unique_trace_ids(self):
        s = Session()
        ids = {s.episode_trace_id() for _ in range(100)}
        assert len(ids) == 100

    def test_trace_id_contains_session_id(self):
        s = Session(session_id="mysession123")
        tid = s.episode_trace_id()
        assert "mysession123" in tid
