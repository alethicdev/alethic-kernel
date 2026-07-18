from __future__ import annotations
from types import MappingProxyType
from typing import Dict, FrozenSet, Literal, Mapping, Set

Role = Literal["kernel","tool","planner","symbolic_validator","evidence_validator","sim_validator"]

PERMISSIONS: Mapping[str, Mapping[str, FrozenSet[str]]] = MappingProxyType({
    "tool": MappingProxyType({"percepts": frozenset({"COMMIT"})}),
    "planner": MappingProxyType({"beliefs": frozenset({"PROPOSE"}), "plans": frozenset({"PROPOSE"}),
                "actions": frozenset({"PROPOSE"}), "predictions": frozenset({"PROPOSE"})}),
    "symbolic_validator": MappingProxyType({"constraints": frozenset({"COMMIT"})}),
    "evidence_validator": MappingProxyType({"evidence": frozenset({"COMMIT"})}),
    "sim_validator": MappingProxyType({"evidence": frozenset({"COMMIT"}), "predictions": frozenset({"COMMIT"})}),
    "kernel": MappingProxyType({"beliefs": frozenset({"COMMIT"}), "actions": frozenset({"COMMIT"}),
               "predictions": frozenset({"COMMIT"})}),
})
