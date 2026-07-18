"""Tests for LLMAgent with mocked LLM calls."""
from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest

from alethic_kernel.kernel import Kernel
from alethic_kernel.tools.payment_tool import PaymentTool
from alethic_kernel.tools.refund_tool import RefundTool
from alethic_kernel.tools.perturb import PerturbConfig
from alethic_kernel.agents.llm_agent import LLMAgent


def _clean_cfg() -> PerturbConfig:
    return PerturbConfig(
        tool_drop_rate=0.0, stale_rate=0.0,
        conflict_rate=0.0, low_confidence_rate=0.0)


def _make_llm_agent(cfg: PerturbConfig | None = None) -> LLMAgent:
    cfg = cfg or _clean_cfg()
    return LLMAgent(
        kernel=Kernel(),
        payment_tool=PaymentTool(cfg),
        refund_tool=RefundTool(),
    )


def _mock_chat_responses(*responses):
    """Create a side_effect for llm.planner.chat that returns canned responses."""
    call_count = [0]
    def side_effect(messages, **kwargs):
        idx = min(call_count[0], len(responses) - 1)
        call_count[0] += 1
        return responses[idx]
    return side_effect


class TestLLMAgentCleanWithPropose:
    @patch("alethic_kernel.llm.planner.chat")
    def test_full_pipeline(self, mock_chat, clean_task_inputs, default_constraints):
        # Mock LLM responses: belief, plan, action
        belief_resp = json.dumps({"propose": True, "value": True,
                                  "depends_on": ["charge"], "reasoning": "ok"})
        plan_resp = json.dumps({"steps": [{"action": "issue_refund",
                                           "requires_beliefs": ["refund_due"],
                                           "is_duplicate": False}]})
        action_resp = json.dumps({"type": "issue_refund",
                                  "description": "refund",
                                  "is_duplicate": False,
                                  "requires_beliefs": ["refund_due"]})
        mock_chat.side_effect = _mock_chat_responses(belief_resp, plan_resp, action_resp)

        agent = _make_llm_agent()
        result = agent.run(0, "test_task", clean_task_inputs, default_constraints)

        assert result["final"]["belief_committed"] is True
        assert result["final"]["plan_feasible"] is True
        assert result["final"]["action_committed"] is True
        assert "issue_refund" in result["view"]["actions"]


class TestLLMAgentDeclines:
    @patch("alethic_kernel.llm.planner.chat")
    def test_llm_declines_belief(self, mock_chat, clean_task_inputs, default_constraints):
        belief_resp = json.dumps({"propose": False, "reasoning": "no data"})
        mock_chat.side_effect = _mock_chat_responses(belief_resp)

        agent = _make_llm_agent()
        result = agent.run(0, "test_task", clean_task_inputs, default_constraints)
        # LLM declined → should_propose becomes False, but agent still proposes
        # because should_propose defaults to True and llm_belief.get("propose", True)
        # In this case propose=False so should_propose=False
        # No belief proposed, so plan and action also fail
        assert result["final"]["belief_committed"] is False
        assert result["final"]["action_committed"] is False
        # Should queue for review
        assert "queue_for_review" in result["view"]["actions"]


class TestLLMAgentStale:
    @patch("alethic_kernel.llm.planner.chat")
    def test_stale_rejected_by_kernel(self, mock_chat, clean_task_inputs, default_constraints):
        cfg = PerturbConfig(
            tool_drop_rate=0.0, stale_rate=1.0,
            conflict_rate=0.0, low_confidence_rate=0.0)
        belief_resp = json.dumps({"propose": True, "value": True,
                                  "depends_on": ["charge"], "reasoning": "ok"})
        mock_chat.side_effect = _mock_chat_responses(belief_resp)

        agent = _make_llm_agent(cfg)
        result = agent.run(0, "test_task", clean_task_inputs, default_constraints)

        assert result["final"]["belief_committed"] is False
        assert result["final"]["belief_code"] == "STALE_EVIDENCE"
        assert "issue_refund" not in result["view"]["actions"]


class TestLLMAgentDuplicate:
    @patch("alethic_kernel.llm.planner.chat")
    def test_duplicate_blocked(self, mock_chat, duplicate_task_inputs, default_constraints):
        belief_resp = json.dumps({"propose": True, "value": True,
                                  "depends_on": ["charge"], "reasoning": "ok"})
        plan_resp = json.dumps({"steps": [{"action": "issue_refund",
                                           "requires_beliefs": ["refund_due"],
                                           "is_duplicate": True}]})
        mock_chat.side_effect = _mock_chat_responses(belief_resp, plan_resp)

        agent = _make_llm_agent()
        result = agent.run(0, "test_task", duplicate_task_inputs, default_constraints)

        assert result["final"]["belief_committed"] is True
        assert "issue_refund" not in result["view"]["actions"]


class TestLLMAgentLLMError:
    @patch("alethic_kernel.llm.planner.chat")
    def test_llm_error_handled(self, mock_chat, clean_task_inputs, default_constraints):
        mock_chat.side_effect = Exception("Connection refused")

        agent = _make_llm_agent()
        result = agent.run(0, "test_task", clean_task_inputs, default_constraints)

        # LLM error → returns None → agent still proposes belief (should_propose=True)
        # Belief should commit since evidence is clean
        assert result["final"]["belief_committed"] is True


class TestLLMAgentMalformedResponse:
    @patch("alethic_kernel.llm.planner.chat")
    def test_malformed_json(self, mock_chat, clean_task_inputs, default_constraints):
        belief_resp = "I think we should definitely issue a refund"
        plan_resp = "not json"
        mock_chat.side_effect = _mock_chat_responses(belief_resp, plan_resp)

        agent = _make_llm_agent()
        result = agent.run(0, "test_task", clean_task_inputs, default_constraints)

        # Malformed → _extract_json returns None → propose_belief returns None
        # Agent treats None as should_propose=True → belief commits (evidence clean)
        assert result["final"]["belief_committed"] is True
