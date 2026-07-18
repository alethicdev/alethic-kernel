from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Optional
from .perturb import PerturbConfig, maybe

@dataclass
class PaymentTool:
    cfg: PerturbConfig

    def get_charge(self, seed: int, charge_id: str, customer_id: str,
                   amount: float) -> Optional[Dict[str, Any]]:
        key = f"charge:{charge_id}:{customer_id}"
        if maybe(seed, key + ":drop", self.cfg.tool_drop_rate):
            return None
        stale = maybe(seed, key + ":stale", self.cfg.stale_rate)
        conflict = maybe(seed, key + ":conflict", self.cfg.conflict_rate)
        low_conf = maybe(seed, key + ":low_conf", self.cfg.low_confidence_rate)
        result: Dict[str, Any] = {
            "charge_id": charge_id,
            "amount": amount,
            "currency": "usd",
            "status": "disputed",
            "stale": stale,
            "conflict": conflict,
            "low_confidence": low_conf,
            "customer_id": customer_id,
        }
        if low_conf:
            result["_confidence"] = 0.3
        return result
