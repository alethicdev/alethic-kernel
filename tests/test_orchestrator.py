"""Tests for alethic_kernel/orchestrator.py."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet

from alethic_kernel.kernel import Kernel
from alethic_kernel.orchestrator import Orchestrator, OrchestratorResult
from alethic_kernel.worker import BaseWorker
from alethic_kernel.schema import Slot


@dataclass
class CountingWorker(BaseWorker):
    """Worker that produces N times then stops."""
    worker_id: str = "counter"
    role: str = "tool"
    reads: FrozenSet[Slot] = field(default_factory=frozenset)
    writes: FrozenSet[Slot] = field(default_factory=lambda: frozenset(["percepts"]))
    max_steps: int = 3
    _count: int = field(default=0, repr=False)

    def should_activate(self, view: Dict[str, Dict[str, Any]]) -> bool:
        return self._count < self.max_steps

    def step(self, kernel: Any, trace_id: str,
             view: Dict[str, Dict[str, Any]]) -> bool:
        self._count += 1
        kernel.write("tool", "percepts", "COMMIT",
                     f"data_{self._count}", {"n": self._count}, trace_id)
        return True


@dataclass
class NeverWorker(BaseWorker):
    """Worker that never activates."""
    worker_id: str = "never"

    def should_activate(self, view: Dict[str, Dict[str, Any]]) -> bool:
        return False


@dataclass
class ErrorWorker(BaseWorker):
    """Worker that raises on step()."""
    worker_id: str = "error"
    role: str = "tool"
    reads: FrozenSet[Slot] = field(default_factory=frozenset)
    writes: FrozenSet[Slot] = field(default_factory=lambda: frozenset(["percepts"]))
    _activated: bool = field(default=False, repr=False)

    def should_activate(self, view: Dict[str, Dict[str, Any]]) -> bool:
        return not self._activated

    def step(self, kernel: Any, trace_id: str,
             view: Dict[str, Dict[str, Any]]) -> bool:
        self._activated = True
        raise RuntimeError("deliberate error")


@dataclass
class ActivateErrorWorker(BaseWorker):
    """Worker that raises on should_activate()."""
    worker_id: str = "activate_error"

    def should_activate(self, view: Dict[str, Dict[str, Any]]) -> bool:
        raise ValueError("activate error")


class TestOrchestratorQuiescence:
    def test_quiescence_when_no_workers(self):
        k = Kernel()
        orch = Orchestrator(k, [])
        result = orch.run("t1")
        assert result.rounds == 1
        assert result.worker_log == []

    def test_quiescence_never_worker(self):
        k = Kernel()
        orch = Orchestrator(k, [NeverWorker()])
        result = orch.run("t1")
        assert result.rounds == 1

    def test_quiescence_after_work_done(self):
        k = Kernel()
        w = CountingWorker(max_steps=2)
        orch = Orchestrator(k, [w])
        result = orch.run("t1")
        assert result.rounds == 3  # 2 producing rounds + 1 quiescent round
        assert any(e["produced"] for e in result.worker_log)


class TestOrchestratorMaxRounds:
    def test_max_rounds_limits_execution(self):
        k = Kernel()
        w = CountingWorker(max_steps=100)
        orch = Orchestrator(k, [w], max_rounds=5)
        result = orch.run("t1")
        assert result.rounds == 5


class TestOrchestratorErrorIsolation:
    def test_error_in_step_isolated(self):
        k = Kernel()
        good = CountingWorker(max_steps=1)
        bad = ErrorWorker()
        orch = Orchestrator(k, [good, bad], on_error=lambda w, e: None)
        result = orch.run("t1")
        assert len(result.errors) == 1
        assert result.errors[0]["worker"] == "error"
        assert result.errors[0]["phase"] == "step"
        # Good worker still ran
        assert any(e["worker"] == "counter" and e["produced"]
                   for e in result.worker_log)

    def test_error_in_should_activate_isolated(self):
        k = Kernel()
        good = CountingWorker(max_steps=1)
        bad = ActivateErrorWorker()
        orch = Orchestrator(k, [good, bad], on_error=lambda w, e: None)
        result = orch.run("t1")
        assert len(result.errors) >= 1
        assert any(e["phase"] == "should_activate" for e in result.errors)


class TestOrchestratorDependencyOrdering:
    def test_workers_sorted_by_slot_order(self):
        k = Kernel()

        @dataclass
        class ActionWriter(BaseWorker):
            worker_id: str = "action_writer"
            writes: FrozenSet[Slot] = field(
                default_factory=lambda: frozenset(["actions"]))

        @dataclass
        class PerceptWriter(BaseWorker):
            worker_id: str = "percept_writer"
            writes: FrozenSet[Slot] = field(
                default_factory=lambda: frozenset(["percepts"]))

        orch = Orchestrator(k, [ActionWriter(), PerceptWriter()])
        # percept_writer should come first (slot order: percepts=0, actions=6)
        assert orch.workers[0].worker_id == "percept_writer"
        assert orch.workers[1].worker_id == "action_writer"


class TestOrchestratorResult:
    def test_result_has_final_view(self):
        k = Kernel()
        w = CountingWorker(max_steps=1)
        orch = Orchestrator(k, [w])
        result = orch.run("t1")
        assert "percepts" in result.view
        assert "data_1" in result.view["percepts"]

    def test_result_trace_id(self):
        k = Kernel()
        orch = Orchestrator(k, [])
        result = orch.run("my-trace")
        assert result.trace_id == "my-trace"

    def test_include_persistent(self):
        k = Kernel()
        k.write("symbolic_validator", "constraints", "COMMIT",
                "c1", {"enabled": True}, "other-trace", scope="persistent")
        orch = Orchestrator(k, [])
        result = orch.run("my-trace", include_persistent=True)
        assert "c1" in result.view["constraints"]


class TestOrchestratorCallback:
    def test_on_error_callback(self):
        errors = []
        k = Kernel()
        bad = ErrorWorker()
        orch = Orchestrator(k, [bad], on_error=lambda w, e: errors.append((w, e)))
        orch.run("t1")
        assert len(errors) == 1
        assert errors[0][0] == "error"
