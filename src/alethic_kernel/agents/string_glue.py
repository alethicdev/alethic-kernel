from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict
from ..tools.payment_tool import PaymentTool
from ..tools.refund_tool import RefundTool

@dataclass
class StringGlueAgent:
    payment_tool: PaymentTool
    refund_tool: RefundTool
    id: str = "string_glue"

    def run(self, seed: int, task_inputs: Dict[str, Any]) -> Dict[str, Any]:
        charge = self.payment_tool.get_charge(
            seed, task_inputs["chargeId"], task_inputs["customerId"],
            task_inputs["amount"])
        if charge is None:
            charge = {"charge_id": task_inputs["chargeId"],
                      "amount": task_inputs["amount"], "currency": "usd",
                      "status": "disputed", "stale": False, "conflict": False,
                      "customer_id": task_inputs["customerId"]}
        charge.pop("_confidence", None)
        refund_due = True
        is_duplicate = task_inputs.get("is_duplicate", False)
        refund = self.refund_tool.render_refund(
            task_inputs["chargeId"], task_inputs["amount"],
            task_inputs["customerId"],
            reason=task_inputs.get("disputeReason", "customer_request"),
            is_duplicate=is_duplicate)
        action = {"type": "issue_refund", "amount": refund["amount"],
                  "charge_id": refund["charge_id"], "is_duplicate": refund["is_duplicate"]}
        return {"beliefs": {"refund_due": refund_due}, "action": action,
                "tool_obs": {"charge": charge, "refund": refund}}
