from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict
import uuid

from ..kernel import Kernel
from ..tools.payment_tool import PaymentTool
from ..tools.refund_tool import RefundTool

@dataclass
class AlethicAgent:
    kernel: Kernel
    payment_tool: PaymentTool
    refund_tool: RefundTool
    id: str = "alethic"

    def run(self, seed: int, task_id: str, task_inputs: Dict[str, Any],
            constraints: Dict[str, Any]) -> Dict[str, Any]:
        trace_id = f"{task_id}-{seed}-{uuid.uuid4().hex[:8]}"

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

        # t2  Planner proposes belief
        belief_prop = self.kernel.write(
            "planner", "beliefs", "PROPOSE", "refund_due",
            {"value": True, "depends_on": ["charge"]},
            trace_id, input_refs=["charge"])

        # t3-t4  Kernel validates evidence, confidence, conflicts
        ok_belief, belief_code = self.kernel.commit_belief_from_proposal(
            belief_prop.id, trace_id)

        # t5  Planner proposes plan
        is_duplicate = task_inputs.get("is_duplicate", False)
        refund = self.refund_tool.render_refund(
            task_inputs["chargeId"], task_inputs["amount"],
            task_inputs["customerId"],
            reason=task_inputs.get("disputeReason", "customer_request"),
            is_duplicate=is_duplicate)
        plan_step = {
            "action": "issue_refund",
            "requires_beliefs": ["refund_due"],
            "is_duplicate": refund.get("is_duplicate", False),
        }
        plan_prop = self.kernel.write(
            "planner", "plans", "PROPOSE", "action_plan",
            {"steps": [plan_step]}, trace_id)

        # t6  Validators check plan feasibility
        ok_plan, plan_code = self.kernel.validate_plan(plan_prop.id, trace_id)

        ok_action, action_code = False, ""
        ok_safe, safe_code = False, ""

        if ok_plan:
            # t7  Propose action from plan
            action_payload = {
                "type": "issue_refund",
                "charge_id": refund["charge_id"],
                "amount": refund["amount"],
                "reason": refund["reason"],
                "is_duplicate": refund["is_duplicate"],
                "requires_beliefs": ["refund_due"],
            }
            action_prop = self.kernel.write(
                "planner", "actions", "PROPOSE", "issue_refund",
                action_payload, trace_id, input_refs=[belief_prop.id])
            # t8-t9  Kernel gates action
            ok_action, action_code = self.kernel.commit_action_from_proposal(
                action_prop.id, trace_id)

        if not ok_action:
            reason = action_code or plan_code
            safe_prop = self.kernel.write(
                "planner", "actions", "PROPOSE", "queue_for_review",
                {"type": "queue_for_review", "reason": reason},
                trace_id, input_refs=[plan_prop.id])
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
