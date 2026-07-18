from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Protocol, runtime_checkable

from .schema import Slot
from .permissions import Role


@runtime_checkable
class Worker(Protocol):
    """Interface for any cognitive component that reads/writes the blackboard."""

    worker_id: str
    role: Role
    reads: FrozenSet[Slot]
    writes: FrozenSet[Slot]

    def should_activate(self, view: Dict[str, Dict[str, Any]]) -> bool:
        """Return True if this worker has work to do given the current view."""
        ...

    def step(self, kernel: Any, trace_id: str,
             view: Dict[str, Dict[str, Any]]) -> bool:
        """Execute one unit of work. Return True if something was written."""
        ...


@dataclass
class BaseWorker:
    """Convenience base that satisfies the Worker protocol."""

    worker_id: str = ""
    role: Role = "tool"
    reads: FrozenSet[Slot] = field(default_factory=frozenset)
    writes: FrozenSet[Slot] = field(default_factory=frozenset)

    def should_activate(self, view: Dict[str, Dict[str, Any]]) -> bool:
        return False

    def step(self, kernel: Any, trace_id: str,
             view: Dict[str, Dict[str, Any]]) -> bool:
        return False
