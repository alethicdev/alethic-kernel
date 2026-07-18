"""Integration tests for AlethicAgent.run() with various inputs."""
from __future__ import annotations

import pytest

from alethic_kernel.kernel import Kernel
from alethic_kernel.tools.payment_tool import PaymentTool
from alethic_kernel.tools.refund_tool import RefundTool
from alethic_kernel.tools.perturb import PerturbConfig
from alethic_kernel.agents.alethic_agent import AlethicAgent


def _make_agent(cfg: PerturbConfig | None = None) -> AlethicAgent:
    cfg = cfg or PerturbConfig(
        tool_drop_rate=0.0, stale_rate=0.0,
        conflict_rate=0.0, low_confidence_rate=0.0)
    return AlethicAgent(
        kernel=Kernel(),
        payment_tool=PaymentTool(cfg),
        refund_tool=RefundTool(),
    )


class TestAlethicAgentClean:
    def test_issues_refund(self, clean_task_inputs, default_constraints):
        agent = _make_agent()
        result = agent.run(0, "clean_task", clean_task_inputs, default_constraints)
        assert result["final"]["belief_committed"] is True
        assert result["final"]["plan_feasible"] is True
        assert result["final"]["action_committed"] is True
        assert "issue_refund" in result["view"]["actions"]

    def test_trace_id_contains_task_and_seed(self, clean_task_inputs, default_constraints):
        agent = _make_agent()
        result = agent.run(42, "clean_task", clean_task_inputs, default_constraints)
        assert "clean_task" in result["trace_id"]
        assert "42" in result["trace_id"]


class TestAlethicAgentStale:
    def test_rejects_stale_evidence(self, clean_task_inputs, default_constraints):
        cfg = PerturbConfig(
            tool_drop_rate=0.0, stale_rate=1.0,
            conflict_rate=0.0, low_confidence_rate=0.0)
        agent = _make_agent(cfg)
        result = agent.run(0, "stale_task", clean_task_inputs, default_constraints)
        assert result["final"]["belief_committed"] is False
        assert result["final"]["belief_code"] == "STALE_EVIDENCE"
        assert "issue_refund" not in result["view"]["actions"]

    def test_queues_for_review(self, clean_task_inputs, default_constraints):
        cfg = PerturbConfig(
            tool_drop_rate=0.0, stale_rate=1.0,
            conflict_rate=0.0, low_confidence_rate=0.0)
        agent = _make_agent(cfg)
        result = agent.run(0, "stale_task", clean_task_inputs, default_constraints)
        assert result["final"]["safe_action_committed"] is True
        assert "queue_for_review" in result["view"]["actions"]


class TestAlethicAgentConflict:
    def test_rejects_conflict_low_confidence(self, clean_task_inputs, default_constraints):
        cfg = PerturbConfig(
            tool_drop_rate=0.0, stale_rate=0.0,
            conflict_rate=1.0, low_confidence_rate=0.0)
        agent = _make_agent(cfg)
        result = agent.run(0, "conflict_task", clean_task_inputs, default_constraints)
        # Conflict without confidence → unresolved
        assert result["final"]["belief_committed"] is False
        assert "issue_refund" not in result["view"]["actions"]


class TestAlethicAgentDuplicate:
    def test_blocks_duplicate_refund(self, duplicate_task_inputs, default_constraints):
        agent = _make_agent()
        result = agent.run(0, "dup_task", duplicate_task_inputs, default_constraints)
        # Belief should commit (evidence is clean), but plan/action should be blocked
        assert result["final"]["belief_committed"] is True
        assert "issue_refund" not in result["view"]["actions"]
        assert "queue_for_review" in result["view"]["actions"]


class TestAlethicAgentToolFailure:
    def test_tool_drop_handled(self, clean_task_inputs, default_constraints):
        cfg = PerturbConfig(
            tool_drop_rate=1.0, stale_rate=0.0,
            conflict_rate=0.0, low_confidence_rate=0.0)
        agent = _make_agent(cfg)
        result = agent.run(0, "drop_task", clean_task_inputs, default_constraints)
        # Tool returns None → agent creates fallback charge with stale=True
        assert result["final"]["belief_committed"] is False
        assert result["final"]["belief_code"] == "STALE_EVIDENCE"


class TestAlethicAgentLowConfidence:
    def test_rejects_low_confidence(self, clean_task_inputs, default_constraints):
        cfg = PerturbConfig(
            tool_drop_rate=0.0, stale_rate=0.0,
            conflict_rate=0.0, low_confidence_rate=1.0)
        agent = _make_agent(cfg)
        result = agent.run(0, "lowconf_task", clean_task_inputs, default_constraints)
        assert result["final"]["belief_committed"] is False
        assert result["final"]["belief_code"] == "LOW_CONFIDENCE"
        assert "issue_refund" not in result["view"]["actions"]
