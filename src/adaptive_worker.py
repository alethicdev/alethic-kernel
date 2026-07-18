"""Outcome-driven adaptive constraint learner.

Inspects the kernel's store for invalidated records, counts failure
patterns by reason code, and proposes persistent constraints when
a pattern exceeds a configurable threshold.  This is real learning
from observed data — the constraints are derived, not scripted.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Set

from .permissions import Role
from .schema import Slot, Record
from .worker import BaseWorker

# Mapping from invalidation reason codes to constraint definitions.
# Each entry says: "if we see this reason N times, create this constraint."
_DEFAULT_REASON_TO_CONSTRAINT = {
    "STALE_EVIDENCE": {
        "name": "block_stale_actions",
        "definition": {"enabled": True, "blocks_field": "uses_stale_data",
                        "source": "adaptive", "trigger": "STALE_EVIDENCE"},
    },
    "UNRESOLVED_CONFLICT": {
        "name": "block_conflicted_actions",
        "definition": {"enabled": True, "blocks_field": "uses_conflicted_data",
                        "source": "adaptive", "trigger": "UNRESOLVED_CONFLICT"},
    },
    "LOW_CONFIDENCE": {
        "name": "block_low_confidence_actions",
        "definition": {"enabled": True, "blocks_field": "uses_low_confidence_data",
                        "source": "adaptive", "trigger": "LOW_CONFIDENCE"},
    },
    "NEGATIVE_PREDICTION": {
        "name": "block_negative_predictions",
        "definition": {"enabled": True, "blocks_field": "has_negative_prediction",
                        "source": "adaptive", "trigger": "NEGATIVE_PREDICTION"},
    },
}


@dataclass
class AdaptiveWorker(BaseWorker):
    """Learns persistent constraints from failure patterns in the store.

    After each episode, call `analyze(store)` to scan invalidated records
    and queue constraints.  On the next orchestrator run the worker will
    commit any queued constraints as persistent records.

    Attributes:
        failure_threshold: how many occurrences of a reason code before
            a constraint is proposed (default 2 — learn fast)
        reason_to_constraint: mapping from reason codes to constraint
            definitions.  Override to customize what gets learned.
        emitted: set of constraint names already committed (prevents dupes)
    """
    worker_id: str = "adaptive"
    role: Role = "symbolic_validator"
    reads: FrozenSet[Slot] = field(
        default_factory=lambda: frozenset(["constraints"]))
    writes: FrozenSet[Slot] = field(
        default_factory=lambda: frozenset(["constraints"]))
    failure_threshold: int = 2
    reason_to_constraint: Dict[str, Dict[str, Any]] = field(
        default_factory=lambda: dict(_DEFAULT_REASON_TO_CONSTRAINT))
    emitted: Set[str] = field(default_factory=set)
    _queued: Dict[str, Dict[str, Any]] = field(
        default_factory=dict, repr=False)

    def analyze(self, store: Any) -> List[str]:
        """Scan the store for failure patterns and queue constraints.

        Works with any store.  Iterates invalidated records across
        mutable slots and normalizes reason strings to base codes
        (STALE_EVIDENCE, LOW_CONFIDENCE, etc.) before counting.

        Returns a list of constraint names that were queued.
        """
        counts: Dict[str, int] = {}
        for slot_name in ["beliefs", "actions", "plans", "predictions"]:
            for rec in store.list_slot(slot_name):
                if rec.status == "INVALIDATED" and rec.reason:
                    base = self._base_reason(rec.reason)
                    counts[base] = counts.get(base, 0) + 1

        queued_names: List[str] = []
        for reason, count in counts.items():
            if count < self.failure_threshold:
                continue
            mapping = self.reason_to_constraint.get(reason)
            if mapping is None:
                continue
            cname = mapping["name"]
            if cname in self.emitted:
                continue
            defn = dict(mapping["definition"])
            defn["learned_from_count"] = count
            self._queued[cname] = defn
            queued_names.append(cname)

        return queued_names

    def should_activate(self, view: Dict[str, Dict[str, Any]]) -> bool:
        return bool(self._queued)

    def step(self, kernel: Any, trace_id: str,
             view: Dict[str, Dict[str, Any]]) -> bool:
        if not self._queued:
            return False
        for cname, cdef in self._queued.items():
            kernel.write("symbolic_validator", "constraints", "COMMIT",
                         cname, cdef, trace_id, scope="persistent")
            self.emitted.add(cname)
        self._queued.clear()
        return True

    @staticmethod
    def _base_reason(reason: str) -> str:
        """Extract the base reason code from a detailed reason string.

        e.g. 'Belief depends on stale percept: invoice' -> 'STALE_EVIDENCE'
             'Low confidence on percept: temperature'   -> 'LOW_CONFIDENCE'
        """
        r = reason.upper()
        if "STALE" in r:
            return "STALE_EVIDENCE"
        if "CONFLICT" in r:
            return "UNRESOLVED_CONFLICT"
        if "LOW CONFIDENCE" in r or "LOW_CONFIDENCE" in r:
            return "LOW_CONFIDENCE"
        if "NEGATIVE" in r:
            return "NEGATIVE_PREDICTION"
        # return the raw reason if no mapping found
        return reason
