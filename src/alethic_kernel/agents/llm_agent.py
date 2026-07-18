from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
import sys
import uuid

from ..kernel import Kernel
from ..tools.payment_tool import PaymentTool
from ..tools.refund_tool import RefundTool
from ..llm.planner import propose_belief, propose_plan, propose_action


@dataclass
class LLMAgent:
    kernel: Kernel
    payment_tool: PaymentTool
    refund_tool: RefundTool
    id: str = "llm_bk"
    llm_kw: Dict[str, Any] = field(default_factory=dict)

    def run(self, seed: int, task_id: str, task_inputs: Dict[str, Any],
            constraints: Dict[str, Any]) -> Dict[str, Any]:
        trace_id = f"{task_id}-{seed}-{uuid.uuid4().hex[:8]}"
        task_desc = (f"Process a refund for customer {task_inputs['customerName']} "
                     f"on charge {task_inputs['chargeId']} "
                     f"(${task_inputs['amount']:.2f}, reason: {task_inputs.get('disputeReason', 'unknown')})")
        belief_name = "refund_due"

        # t0  Commit constraints
        for cname, cdef in constraints.items():
            payload = {"enabled": True}
            if isinstance(cdef, dict):
                payload.update(cdef)
            self.kernel.write("symbolic_validator", "constraints", "COMMIT",
                              cname, payload, trace_id)

        # t0  Tools commit percepts
        charge = self.payment_tool.get_charge(
            seed, task_inputs["chargeId"], task_inputs["customerId"],
            task_inputs["amount"])
        if charge is None:
            charge = {"charge_id": task_inputs["chargeId"],
                      "amount": task_inputs["amount"], "currency": "usd",
                      "status": "disputed", "stale": True, "conflict": False,
                      "customer_id": task_inputs["customerId"]}
        confidence = charge.pop("_confidence", None)
        self.kernel.write("tool", "percepts", "COMMIT", "charge", charge,
                          trace_id, confidence=confidence)

        percept_keys = ["charge"]

        # ── LLM proposes belief ──────────────────────────────────────
        view = self.kernel.current_view(trace_id)
        llm_belief = self._llm_propose_belief(
            view["percepts"], view["constraints"], task_desc,
            belief_name, percept_keys)

        ok_belief, belief_code = False, "LLM_NO_BELIEF"
        should_propose = True
        if llm_belief is not None:
            should_propose = llm_belief.get("propose", True)

        if should_propose:
            belief_prop = self.kernel.write(
                "planner", "beliefs", "PROPOSE", belief_name,
                {"value": True, "depends_on": percept_keys},
                trace_id, input_refs=percept_keys)
            ok_belief, belief_code = self.kernel.commit_belief_from_proposal(
                belief_prop.id, trace_id)

        # ── LLM proposes plan ────────────────────────────────────────
        is_duplicate = task_inputs.get("is_duplicate", False)
        refund = self.refund_tool.render_refund(
            task_inputs["chargeId"], task_inputs["amount"],
            task_inputs["customerId"],
            reason=task_inputs.get("disputeReason", "customer_request"),
            is_duplicate=is_duplicate)

        view = self.kernel.current_view(trace_id)
        action_context = {
            "charge_id": refund["charge_id"],
            "amount": refund["amount"],
            "reason": refund["reason"],
            "is_duplicate": refund["is_duplicate"],
        }
        required_beliefs = [belief_name]
        llm_plan = self._llm_propose_plan(
            view["beliefs"], view["constraints"], task_desc,
            action_context, required_beliefs)

        ok_plan, plan_code = False, "LLM_NO_PLAN"
        plan_steps: list[Dict[str, Any]] = []

        if llm_plan and llm_plan.get("steps"):
            plan_steps = []
            for step in llm_plan["steps"]:
                normalized = dict(step)
                normalized["requires_beliefs"] = required_beliefs
                normalized.setdefault("is_duplicate", refund.get("is_duplicate", False))
                plan_steps.append(normalized)

            plan_prop = self.kernel.write(
                "planner", "plans", "PROPOSE", "action_plan",
                {"steps": plan_steps}, trace_id)
            ok_plan, plan_code = self.kernel.validate_plan(plan_prop.id, trace_id)

        # ── LLM proposes action ──────────────────────────────────────
        ok_action, action_code = False, ""

        if ok_plan and plan_steps:
            step = plan_steps[0]
            llm_action = self._llm_propose_action(
                step, f"Refund ${refund['amount']:.2f} to {task_inputs['customerName']}",
                refund.get("is_duplicate", False), {})

            if llm_action:
                action_payload = {
                    "type": "issue_refund",
                    "charge_id": refund["charge_id"],
                    "amount": refund["amount"],
                    "reason": refund["reason"],
                    "is_duplicate": refund["is_duplicate"],
                    "requires_beliefs": required_beliefs,
                }
                action_prop = self.kernel.write(
                    "planner", "actions", "PROPOSE", "issue_refund",
                    action_payload, trace_id,
                    input_refs=[f"beliefs:{trace_id}:1"] if ok_belief else [])
                ok_action, action_code = self.kernel.commit_action_from_proposal(
                    action_prop.id, trace_id)

        # ── Fallback: queue for review ───────────────────────────────
        ok_safe, safe_code = False, ""
        if not ok_action:
            reason = action_code or plan_code or belief_code
            safe_prop = self.kernel.write(
                "planner", "actions", "PROPOSE", "queue_for_review",
                {"type": "queue_for_review", "reason": reason},
                trace_id)
            ok_safe, safe_code = self.kernel.commit_action_from_proposal(
                safe_prop.id, trace_id)

        return {
            "trace_id": trace_id,
            "final": {
                "belief_committed": ok_belief, "belief_code": belief_code,
                "plan_feasible": ok_plan, "plan_code": plan_code,
                "action_committed": ok_action, "action_code": action_code,
                "safe_action_committed": ok_safe, "safe_action_code": safe_code,
            },
            "view": self.kernel.current_view(trace_id),
        }

    def _llm_propose_belief(self, percepts: Dict[str, Any], constraints: Dict[str, Any],
                            task_desc: str, belief_name: str,
                            percept_keys: list[str]) -> Optional[Dict[str, Any]]:
        try:
            return propose_belief(percepts, constraints, task_desc,
                                  belief_name=belief_name,
                                  percept_keys=percept_keys,
                                  **self.llm_kw)
        except Exception as e:
            print(f"[llm_bk] propose_belief error: {e}", file=sys.stderr)
            return None

    def _llm_propose_plan(self, beliefs: Dict[str, Any], constraints: Dict[str, Any],
                          task_desc: str, action_context: Dict[str, Any],
                          required_beliefs: list[str]) -> Optional[Dict[str, Any]]:
        try:
            return propose_plan(beliefs, constraints, task_desc,
                                action_context,
                                required_beliefs=required_beliefs,
                                **self.llm_kw)
        except Exception as e:
            print(f"[llm_bk] propose_plan error: {e}", file=sys.stderr)
            return None

    def _llm_propose_action(self, plan_step: Dict[str, Any], message_text: str,
                            is_duplicate: bool,
                            action_metadata: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            return propose_action(plan_step, message_text, is_duplicate,
                                  action_metadata, **self.llm_kw)
        except Exception as e:
            print(f"[llm_bk] propose_action error: {e}", file=sys.stderr)
            return None
