from __future__ import annotations
import sys

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .kernel import Kernel
from .worker import Worker


@dataclass
class OrchestratorResult:
    trace_id: str
    view: Dict[str, Dict[str, Any]]
    rounds: int
    worker_log: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)


def _dependency_key(w: Worker) -> int:
    """Sort workers so those that write to early slots run first."""
    order = {"percepts": 0, "beliefs": 1, "constraints": 2,
             "plans": 3, "evidence": 4, "predictions": 5, "actions": 6}
    if not w.writes:
        return 0
    return min(order.get(s, 99) for s in w.writes)


class Orchestrator:
    """Generic round-robin loop over Worker instances on a Kernel.

    Workers are sorted by dependency (writers of early slots run first).
    Each round, every worker that wants to activate gets a `step()` call.
    The loop stops at quiescence (no worker produced) or max_rounds.

    Worker exceptions are caught, logged, and the loop continues with
    the remaining workers.  Errors are collected in the result.
    """

    def __init__(self, kernel: Kernel, workers: List[Worker],
                 max_rounds: int = 20,
                 on_error: Optional[Callable[[str, Exception], None]] = None,
                 ) -> None:
        self.kernel = kernel
        self.workers = sorted(workers, key=_dependency_key)
        self.max_rounds = max_rounds
        self._on_error = on_error

    def run(self, trace_id: str,
            include_persistent: bool = False) -> OrchestratorResult:
        log: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        rounds = 0

        for _ in range(self.max_rounds):
            rounds += 1
            any_produced = False
            view = self.kernel.current_view(trace_id,
                                            include_persistent=include_persistent)

            for w in self.workers:
                try:
                    if not w.should_activate(view):
                        continue
                except Exception as exc:
                    self._handle_error(w.worker_id, "should_activate", exc, errors)
                    continue

                try:
                    produced = w.step(self.kernel, trace_id, view)
                except Exception as exc:
                    self._handle_error(w.worker_id, "step", exc, errors)
                    produced = False

                log.append({"round": rounds, "worker": w.worker_id,
                            "produced": produced})
                if produced:
                    any_produced = True
                    view = self.kernel.current_view(
                        trace_id, include_persistent=include_persistent)

            if not any_produced:
                break  # quiescence

        final_view = self.kernel.current_view(trace_id,
                                              include_persistent=include_persistent)
        return OrchestratorResult(trace_id=trace_id, view=final_view,
                                 rounds=rounds, worker_log=log, errors=errors)

    def _handle_error(self, worker_id: str, phase: str, exc: Exception,
                      errors: List[Dict[str, Any]]) -> None:
        entry = {"worker": worker_id, "phase": phase,
                 "error": str(exc), "type": type(exc).__name__}
        errors.append(entry)
        if self._on_error:
            self._on_error(worker_id, exc)
        else:
            print(f"[orchestrator] {worker_id}.{phase}() failed: {exc}",
                  file=sys.stderr)
