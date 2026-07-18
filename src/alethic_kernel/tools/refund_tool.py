from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict

@dataclass
class RefundTool:
    def render_refund(self, charge_id: str, amount: float, customer_id: str,
                      reason: str = "customer_request",
                      is_duplicate: bool = False) -> Dict[str, Any]:
        return {
            "charge_id": charge_id,
            "amount": amount,
            "currency": "usd",
            "reason": reason,
            "is_duplicate": is_duplicate,
        }
