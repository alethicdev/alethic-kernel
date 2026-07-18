from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict

@dataclass
class ValidationResult:
    ok: bool
    code: str
    detail: str
    context: Dict[str, Any] = field(default_factory=dict)

class EvidenceValidator:
    def validate_belief_commit(self, belief_payload: Dict[str, Any], percepts: Dict[str, Any]) -> ValidationResult:
        depends = belief_payload.get("depends_on", [])
        for k in depends:
            p = percepts.get(k)
            if p is None:
                return ValidationResult(False, "MISSING_EVIDENCE",
                    f"Belief depends on missing percept: {k}", {"percept_key": k})
            if isinstance(p, dict) and p.get("stale") is True:
                return ValidationResult(False, "STALE_EVIDENCE",
                    f"Belief depends on stale percept: {k}", {"percept_key": k})
            if isinstance(p, dict) and p.get("conflict") is True:
                return ValidationResult(False, "CONFLICTING_EVIDENCE",
                    f"Belief depends on conflicting percept: {k}", {"percept_key": k})
        return ValidationResult(True, "OK", "Belief evidence acceptable")

class SymbolicValidator:
    def validate_action(self, action: Dict[str, Any], committed_beliefs: Dict[str, Any], constraints: Dict[str, Any]) -> ValidationResult:
        for belief_name in action.get("requires_beliefs", []):
            belief = committed_beliefs.get(belief_name)
            if belief is None:
                return ValidationResult(False, "NO_COMMITTED_BELIEF",
                    f"Action requires committed belief: {belief_name}")
            value = belief.get("value") if isinstance(belief, dict) else belief
            if not value:
                return ValidationResult(False, "BELIEF_NOT_SATISFIED",
                    f"Committed belief '{belief_name}' is not satisfied")
        for cname, cval in constraints.items():
            if not isinstance(cval, dict) or not cval.get("enabled"):
                continue
            blocked_field = cval.get("blocks_field")
            if blocked_field and action.get(blocked_field) is True:
                return ValidationResult(False, f"{cname.upper()}_BLOCKED",
                    f"Constraint '{cname}' blocks action with {blocked_field}=true")
        return ValidationResult(True, "OK", "Action OK")
