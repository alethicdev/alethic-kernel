"""Rule-based forward simulator.

SimRules are declarative: they specify conditions on beliefs and percepts,
an action_type, and an expected_outcome.  The SimulatorWorker evaluates
all rules against the current view and proposes predictions for matching
rules via the kernel's commit_prediction() pipeline.

Conditions are dicts of {field: value} for equality, or {field__op: value}
for comparisons (gt, lt, gte, lte, ne).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional

from .permissions import Role
from .schema import Slot
from .worker import BaseWorker


@dataclass
class SimRule:
    """One declarative prediction rule.

    Attributes:
        action_type: the action this prediction is about
        expected_outcome: positive = favorable, negative = unfavorable, 0 = neutral
        requires_beliefs: belief kinds that must be committed
        percept_conditions: {percept_kind: {field_op: value, ...}}
            field_op is either "field" (equality) or "field__gt", "field__lt",
            "field__gte", "field__lte", "field__ne"
        belief_conditions: {belief_kind: {field_op: value, ...}}
        confidence: confidence to attach to the prediction
    """
    action_type: str
    expected_outcome: float
    requires_beliefs: List[str] = field(default_factory=list)
    percept_conditions: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    belief_conditions: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    confidence: float = 0.8


_OPS = {
    "gt":  lambda a, b: a > b,
    "lt":  lambda a, b: a < b,
    "gte": lambda a, b: a >= b,
    "lte": lambda a, b: a <= b,
    "ne":  lambda a, b: a != b,
}


def _check_conditions(payload: Dict[str, Any],
                      conditions: Dict[str, Any]) -> bool:
    """Evaluate declarative conditions against a payload dict."""
    for key, expected in conditions.items():
        if "__" in key:
            field_name, op = key.rsplit("__", 1)
            actual = payload.get(field_name)
            if actual is None:
                return False
            op_fn = _OPS.get(op)
            if op_fn is None:
                return False
            if not op_fn(actual, expected):
                return False
        else:
            if payload.get(key) != expected:
                return False
    return True


def evaluate_rule(rule: SimRule,
                  view: Dict[str, Dict[str, Any]]) -> Optional[float]:
    """Evaluate a single rule against a view.

    Returns the expected_outcome if all conditions pass, None otherwise.
    """
    beliefs = view.get("beliefs", {})
    percepts = view.get("percepts", {})

    # required beliefs must exist
    for bname in rule.requires_beliefs:
        if bname not in beliefs:
            return None

    # belief conditions
    for bname, conds in rule.belief_conditions.items():
        belief = beliefs.get(bname)
        if belief is None or not isinstance(belief, dict):
            return None
        if not _check_conditions(belief, conds):
            return None

    # percept conditions
    for pname, conds in rule.percept_conditions.items():
        percept = percepts.get(pname)
        if percept is None or not isinstance(percept, dict):
            return None
        if not _check_conditions(percept, conds):
            return None

    return rule.expected_outcome


@dataclass
class SimulatorWorker(BaseWorker):
    """Evaluates SimRules and proposes predictions through the kernel.

    For each rule whose conditions match the current view, proposes a
    prediction with the rule's expected_outcome.  The kernel's
    commit_prediction() validates that required beliefs exist before
    committing.
    """
    worker_id: str = "simulator"
    role: Role = "planner"
    reads: FrozenSet[Slot] = field(
        default_factory=lambda: frozenset(["beliefs", "percepts", "predictions"]))
    writes: FrozenSet[Slot] = field(
        default_factory=lambda: frozenset(["predictions"]))
    rules: List[SimRule] = field(default_factory=list)
    _done: bool = field(default=False, repr=False)

    def reset(self) -> None:
        self._done = False

    def should_activate(self, view: Dict[str, Dict[str, Any]]) -> bool:
        if self._done:
            return False
        # activate once beliefs exist and we haven't run yet
        return bool(view.get("beliefs"))

    def step(self, kernel: Any, trace_id: str,
             view: Dict[str, Dict[str, Any]]) -> bool:
        self._done = True
        produced = False
        predictions = view.get("predictions", {})

        for rule in self.rules:
            # skip if prediction for this action_type already committed
            pred_kind = f"pred_{rule.action_type}"
            if pred_kind in predictions:
                continue

            outcome = evaluate_rule(rule, view)
            if outcome is None:
                continue

            prop = kernel.write(
                "planner", "predictions", "PROPOSE", pred_kind,
                {"action_type": rule.action_type,
                 "expected_outcome": outcome,
                 "requires_beliefs": rule.requires_beliefs,
                 "rule_conditions": {
                     "percept_conditions": rule.percept_conditions,
                     "belief_conditions": rule.belief_conditions,
                 }},
                trace_id, confidence=rule.confidence,
            )
            ok, code = kernel.commit_prediction(prop.id, trace_id)
            if ok:
                produced = True

        return produced
