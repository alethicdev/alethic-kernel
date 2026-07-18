from __future__ import annotations
import math
import threading
from typing import Any, Dict, List, Literal, Optional, Tuple
import time

from .schema import Record, Provenance, RecordIdConflict, Slot, WriteMode
from .store import MemoryStore
from .store_protocol import StoreProtocol
from .permissions import PERMISSIONS, Role
from .validators import EvidenceValidator, SymbolicValidator

def _rid(slot: str, n: int, trace_id: str) -> str:
    return f"{slot}:{trace_id}:{n}"


# A backstop against spinning forever if a store reports every id as taken.
# Reached only by a store that is misbehaving, never by a busy trace.
_MAX_ID_PROBES = 10_000

class Kernel:
    def __init__(self, min_confidence: float = 0.5,
                 conflict_confidence_threshold: float = 0.7,
                 store: Optional[StoreProtocol] = None) -> None:
        self.store: StoreProtocol = store if store is not None else MemoryStore()
        self._counters: Dict[str, int] = {}
        self._counter_lock = threading.Lock()
        self._commit_lock = threading.Lock()
        self.evidence_validator = EvidenceValidator()
        self.symbolic_validator = SymbolicValidator()
        self.min_confidence = min_confidence
        self.conflict_confidence_threshold = conflict_confidence_threshold

    def _next_id(self, slot: str, trace_id: str) -> str:
        key = f"{slot}:{trace_id}"
        with self._counter_lock:
            self._counters[key] = self._counters.get(key, 0) + 1
            return _rid(slot, self._counters[key], trace_id)


    def write(self, role: Role, slot: Slot, mode: WriteMode, kind: str, payload: Dict[str, Any],
              trace_id: str, input_refs: Optional[List[str]] = None, confidence: Optional[float] = None,
              ttl_ms: Optional[int] = None, evidence_refs: Optional[List[str]] = None,
              scope: Literal["episode", "persistent"] = "episode") -> Record:
        perms = PERMISSIONS.get(role)
        allowed = perms.get(slot, frozenset()) if perms is not None else frozenset()
        if mode not in allowed:
            raise PermissionError(f"Role {role} cannot {mode} to {slot}")
        # Rejects NaN and the infinities as well as out-of-range values: every
        # comparison against NaN is False, so a NaN that reached the confidence
        # gate would pass straight through it.
        if confidence is not None and not (0.0 <= confidence <= 1.0):
            raise ValueError(f"confidence must be in [0.0, 1.0], got {confidence!r}")
        # Counters live in this process while the store may outlive it, so the
        # store can already hold `beliefs:order-123:1` — written by an earlier
        # run against the same database, or by another kernel sharing it. Walk
        # forward until an id is free rather than colliding on the primary key.
        # Each pass takes the next counter value, so this converges on the
        # records already under this trace.
        for _ in range(_MAX_ID_PROBES):
            rec = Record(
                id=self._next_id(slot, trace_id),
                slot=slot, mode=mode, kind=kind, payload=payload,
                prov=Provenance(
                    writer_id=role, trace_id=trace_id,
                    ts_ms=int(time.time() * 1000),
                    input_refs=input_refs or [],
                    confidence=confidence, ttl_ms=ttl_ms,
                ),
                evidence_refs=evidence_refs or [],
                scope=scope,
            )
            try:
                self.store.append(rec)
                return rec
            except RecordIdConflict:
                continue
        raise RuntimeError(
            f"could not allocate a record id for {slot}:{trace_id} after "
            f"{_MAX_ID_PROBES} attempts"
        )

    def current_view(self, trace_id: str,
                     include_persistent: bool = False) -> Dict[str, Dict[str, Any]]:
        slots: List[Slot] = ["percepts", "beliefs", "constraints", "plans",
                             "evidence", "predictions", "actions"]
        view: Dict[str, Dict[str, Any]] = {s: {} for s in slots}
        for slot in slots:
            for r in self.store.list_slot(slot):
                if r.status != "ACTIVE":
                    continue
                # include record if it matches the trace_id, or if it's
                # persistent and the caller opted in
                if r.prov.trace_id != trace_id:
                    if not (include_persistent and r.scope == "persistent"):
                        continue
                if r.mode == "COMMIT":
                    view[slot][r.kind] = r.payload
                else:
                    view[slot].setdefault("_proposals", []).append(
                        {"id": r.id, "kind": r.kind, "payload": r.payload})
        return view

    # ── belief commitment with evidence validation ──────────────────────

    def commit_belief_from_proposal(self, proposal_id: str, trace_id: str) -> Tuple[bool, str]:
        with self._commit_lock:
            prop = self.store.get(proposal_id)
            if not prop or prop.status != "ACTIVE" or prop.slot != "beliefs" or prop.mode != "PROPOSE":
                return False, "INVALID_PROPOSAL"

            view = self.current_view(trace_id)
            res = self.evidence_validator.validate_belief_commit(prop.payload, view["percepts"])

            if not res.ok:
                # conflict arbitration: high-confidence source overrides conflict
                if res.code == "CONFLICTING_EVIDENCE":
                    dep_key = res.context.get("percept_key")
                    dep_rec = self.store.find_active_by_kind("percepts", dep_key, trace_id) if dep_key else None
                    if (dep_rec and dep_rec.prov.confidence is not None
                            and dep_rec.prov.confidence >= self.conflict_confidence_threshold):
                        pass  # arbitrated — proceed
                    else:
                        self.store.invalidate(proposal_id, res.detail)
                        return False, "UNRESOLVED_CONFLICT"
                else:
                    self.store.invalidate(proposal_id, res.detail)
                    return False, res.code

            # confidence gate on dependent percepts
            for dep_kind in prop.payload.get("depends_on", []):
                dep_rec = self.store.find_active_by_kind("percepts", dep_kind, trace_id)
                if dep_rec and dep_rec.prov.confidence is not None:
                    conf = dep_rec.prov.confidence
                    # An unknown confidence is exactly what this gate is for, so
                    # NaN must fail it rather than slip through `conf < min`.
                    if math.isnan(conf) or conf < self.min_confidence:
                        self.store.invalidate(proposal_id, f"Low confidence on percept: {dep_kind}")
                        return False, "LOW_CONFIDENCE"

            # record evidence artifact
            checks = ["existence", "staleness", "conflict"]
            for dep_kind in prop.payload.get("depends_on", []):
                dep_rec = self.store.find_active_by_kind("percepts", dep_kind, trace_id)
                if dep_rec and dep_rec.prov.confidence is not None:
                    checks.append("confidence")
                    break
            # One unit: evidence saying validation passed must not outlive the
            # belief it vouches for, and the proposal must stay retryable unless
            # the belief actually lands.
            with self.store.transaction():
                ev_rec = self.write(
                    "evidence_validator", "evidence", "COMMIT",
                    f"validation_{prop.kind}",
                    {"belief": prop.kind, "result": "pass", "checks": checks},
                    trace_id,
                )
                self.store.invalidate(proposal_id, "SUPERSEDED_BY_COMMIT")
                self.write(
                    "kernel", "beliefs", "COMMIT", prop.kind, prop.payload, trace_id,
                    input_refs=prop.prov.input_refs, confidence=prop.prov.confidence,
                    evidence_refs=[ev_rec.id],
                )
            return True, "COMMITTED"

    # ── plan feasibility check ──────────────────────────────────────────

    def validate_plan(self, proposal_id: str, trace_id: str) -> Tuple[bool, str]:
        with self._commit_lock:
            prop = self.store.get(proposal_id)
            if not prop or prop.status != "ACTIVE" or prop.slot != "plans" or prop.mode != "PROPOSE":
                return False, "INVALID_PLAN_PROPOSAL"

            view = self.current_view(trace_id)
            committed_beliefs = view["beliefs"]
            constraints = view["constraints"]

            for step in prop.payload.get("steps", []):
                # required beliefs must be committed and truthy
                for belief_name in step.get("requires_beliefs", []):
                    belief = committed_beliefs.get(belief_name)
                    if belief is None:
                        self.store.invalidate(proposal_id, f"Plan requires missing belief: {belief_name}")
                        return False, "PLAN_MISSING_BELIEF"
                    value = belief.get("value") if isinstance(belief, dict) else belief
                    if not value:
                        self.store.invalidate(proposal_id, f"Plan requires unsatisfied belief: {belief_name}")
                        return False, "PLAN_BELIEF_NOT_SATISFIED"
                # constraint pre-check
                for cname, cval in constraints.items():
                    if not isinstance(cval, dict) or not cval.get("enabled"):
                        continue
                    blocked_field = cval.get("blocks_field")
                    if blocked_field and step.get(blocked_field) is True:
                        self.store.invalidate(proposal_id, f"Plan blocked by constraint: {cname}")
                        return False, f"PLAN_{cname.upper()}_BLOCKED"

            return True, "PLAN_FEASIBLE"

    # ── prediction commitment ───────────────────────────────────────────

    def commit_prediction(self, proposal_id: str, trace_id: str) -> Tuple[bool, str]:
        with self._commit_lock:
            prop = self.store.get(proposal_id)
            if (not prop or prop.status != "ACTIVE"
                    or prop.slot != "predictions" or prop.mode != "PROPOSE"):
                return False, "INVALID_PREDICTION_PROPOSAL"
            # validate that required beliefs exist
            for dep in prop.payload.get("requires_beliefs", []):
                if not self.store.find_active_by_kind("beliefs", dep, trace_id):
                    self.store.invalidate(proposal_id,
                                          f"Prediction requires missing belief: {dep}")
                    return False, "PREDICTION_MISSING_BELIEF"
            with self.store.transaction():
                self.store.invalidate(proposal_id, "SUPERSEDED_BY_COMMIT")
                self.write(
                    "kernel", "predictions", "COMMIT", prop.kind, prop.payload,
                    trace_id, input_refs=prop.prov.input_refs,
                    confidence=prop.prov.confidence,
                )
            return True, "COMMITTED"

    # ── action commitment with symbolic validation ──────────────────────

    def commit_action_from_proposal(self, proposal_id: str, trace_id: str,
                                    require_prediction: bool = False) -> Tuple[bool, str]:
        with self._commit_lock:
            prop = self.store.get(proposal_id)
            if not prop or prop.status != "ACTIVE" or prop.slot != "actions" or prop.mode != "PROPOSE":
                return False, "INVALID_ACTION_PROPOSAL"
            view = self.current_view(trace_id)

            # optional prediction gate
            if require_prediction:
                action_type = prop.payload.get("type", prop.kind)
                predictions = view.get("predictions", {})
                matched = None
                for _pk, pval in predictions.items():
                    if isinstance(pval, dict) and pval.get("action_type") == action_type:
                        matched = pval
                        break
                if matched is None:
                    self.store.invalidate(proposal_id,
                                          f"No prediction for action type: {action_type}")
                    return False, "NO_PREDICTION"
                if matched.get("expected_outcome", 0) < 0:
                    self.store.invalidate(proposal_id,
                                          f"Prediction negative for: {action_type}")
                    return False, "NEGATIVE_PREDICTION"

            res = self.symbolic_validator.validate_action(prop.payload, view["beliefs"], view["constraints"])
            if not res.ok:
                self.store.invalidate(proposal_id, res.detail)
                return False, res.code
            with self.store.transaction():
                self.store.invalidate(proposal_id, "SUPERSEDED_BY_COMMIT")
                self.write(
                    "kernel", "actions", "COMMIT", prop.kind, prop.payload, trace_id,
                    input_refs=prop.prov.input_refs, confidence=prop.prov.confidence,
                )
            return True, "COMMITTED"
