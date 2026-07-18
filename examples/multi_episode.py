"""
Multi-episode cognitive substrate demo — domain-agnostic.

A monitoring system observes temperature sensors, forms beliefs about
anomalies, predicts action outcomes, and takes governed actions.

Nothing is scripted.  The SimulatorWorker evaluates declarative rules
against actual percepts.  The AdaptiveWorker scans the store for failure
patterns and derives persistent constraints when a threshold is met.
Behavior genuinely changes across episodes as the system learns.

Run:
    python examples/multi_episode.py
"""
from __future__ import annotations
import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List

from alethic.kernel import Kernel
from alethic.sqlite_store import SqliteStore
from alethic.session import Session
from alethic.orchestrator import Orchestrator
from alethic.worker import BaseWorker
from alethic.sim_worker import SimulatorWorker, SimRule
from alethic.adaptive_worker import AdaptiveWorker
from alethic.schema import Slot


# ── Deterministic sensor simulation ─────────────────────────────────

def _sensor_reading(seed: int, episode: int) -> Dict[str, Any]:
    """Generate a deterministic sensor reading from seed + episode.

    Produces a mix of clean, stale, conflicting, and low-confidence
    readings so the system encounters real failure modes.
    """
    h = int(hashlib.sha256(f"{seed}:{episode}".encode()).hexdigest(), 16)
    value = 80.0 + (h % 30)          # 80-109
    stale = (h >> 8) % 10 < 3         # 30% stale rate
    conflict = (h >> 16) % 10 < 2     # 20% conflict rate
    conf_raw = 0.4 + ((h >> 24) % 60) / 100.0   # 0.40 - 0.99
    low_conf = conf_raw < 0.5

    return {
        "value": round(value, 1),
        "unit": "C",
        "stale": stale,
        "conflict": conflict,
        "_confidence": round(conf_raw, 2),
    }


# ── Workers ──────────────────────────────────────────────────────────

@dataclass
class SensorWorker(BaseWorker):
    """Commits a sensor percept."""
    worker_id: str = "sensor"
    role: str = "tool"
    reads: FrozenSet[Slot] = field(default_factory=lambda: frozenset(["percepts"]))
    writes: FrozenSet[Slot] = field(default_factory=lambda: frozenset(["percepts"]))
    _reading: Dict[str, Any] = field(default_factory=dict)
    _done: bool = False

    def load(self, reading: Dict[str, Any]) -> None:
        self._reading = dict(reading)
        self._done = False

    def should_activate(self, view: Dict[str, Dict[str, Any]]) -> bool:
        return not self._done and bool(self._reading)

    def step(self, kernel: Any, trace_id: str,
             view: Dict[str, Dict[str, Any]]) -> bool:
        self._done = True
        conf = self._reading.pop("_confidence", None)
        kernel.write("tool", "percepts", "COMMIT", "temperature",
                     self._reading, trace_id, confidence=conf)
        return True


@dataclass
class AnalystWorker(BaseWorker):
    """Proposes an anomaly_detected belief from the temperature percept."""
    worker_id: str = "analyst"
    role: str = "planner"
    reads: FrozenSet[Slot] = field(default_factory=lambda: frozenset(["percepts", "beliefs"]))
    writes: FrozenSet[Slot] = field(default_factory=lambda: frozenset(["beliefs"]))
    _done: bool = False

    def reset(self) -> None:
        self._done = False

    def should_activate(self, view: Dict[str, Dict[str, Any]]) -> bool:
        if self._done:
            return False
        return "temperature" in view["percepts"] and "anomaly_detected" not in view["beliefs"]

    def step(self, kernel: Any, trace_id: str,
             view: Dict[str, Dict[str, Any]]) -> bool:
        self._done = True
        prop = kernel.write(
            "planner", "beliefs", "PROPOSE", "anomaly_detected",
            {"value": True, "depends_on": ["temperature"]},
            trace_id, input_refs=["temperature"])
        ok, code = kernel.commit_belief_from_proposal(prop.id, trace_id)
        return ok


@dataclass
class ActuatorWorker(BaseWorker):
    """Proposes an alert action, gated by predictions."""
    worker_id: str = "actuator"
    role: str = "planner"
    reads: FrozenSet[Slot] = field(
        default_factory=lambda: frozenset(["beliefs", "predictions", "actions"]))
    writes: FrozenSet[Slot] = field(default_factory=lambda: frozenset(["actions"]))
    require_prediction: bool = True
    _done: bool = False

    def reset(self) -> None:
        self._done = False

    def should_activate(self, view: Dict[str, Dict[str, Any]]) -> bool:
        if self._done:
            return False
        return ("anomaly_detected" in view["beliefs"]
                and "alert" not in view.get("actions", {}))

    def step(self, kernel: Any, trace_id: str,
             view: Dict[str, Dict[str, Any]]) -> bool:
        self._done = True
        prop = kernel.write(
            "planner", "actions", "PROPOSE", "alert",
            {"type": "alert",
             "requires_beliefs": ["anomaly_detected"],
             "message": "Anomaly detected — alerting operator"},
            trace_id)
        ok, code = kernel.commit_action_from_proposal(
            prop.id, trace_id, require_prediction=self.require_prediction)
        if not ok:
            safe = kernel.write(
                "planner", "actions", "PROPOSE", "queue_for_review",
                {"type": "queue_for_review", "reason": code}, trace_id)
            kernel.commit_action_from_proposal(safe.id, trace_id)
        return True


# ── Main ─────────────────────────────────────────────────────────────

def run_demo(num_episodes: int = 10, seed: int = 42) -> None:
    db_path = ":memory:"  # use a file path for cross-process persistence
    store = SqliteStore(db_path)
    kernel = Kernel(store=store)
    session = Session(metadata={"system": "monitoring_demo", "seed": seed})

    # Simulation rules: if anomaly_detected AND temperature > 90 → positive
    #                    if anomaly_detected AND temperature <= 90 → negative
    sim_rules = [
        SimRule(action_type="alert", expected_outcome=1.0,
                requires_beliefs=["anomaly_detected"],
                percept_conditions={"temperature": {"value__gt": 90}},
                confidence=0.85),
        SimRule(action_type="alert", expected_outcome=-0.5,
                requires_beliefs=["anomaly_detected"],
                percept_conditions={"temperature": {"value__lte": 90}},
                confidence=0.7),
    ]

    sensor = SensorWorker()
    analyst = AnalystWorker()
    simulator = SimulatorWorker(rules=sim_rules)
    actuator = ActuatorWorker(require_prediction=True)
    adaptive = AdaptiveWorker(failure_threshold=2)

    workers = [sensor, analyst, simulator, actuator, adaptive]
    orch = Orchestrator(kernel, workers, on_error=lambda w, e: None)

    results: List[Dict[str, Any]] = []

    print(f"{'='*70}")
    print(f"  Multi-Episode Cognitive Substrate Demo")
    print(f"  {num_episodes} episodes, seed={seed}, store={db_path}")
    print(f"{'='*70}")
    print()

    for ep in range(num_episodes):
        trace = session.episode_trace_id()
        reading = _sensor_reading(seed, ep)

        # load sensor data and reset per-episode workers
        sensor.load(reading)
        analyst.reset()
        simulator.reset()
        actuator.reset()

        # between episodes: adaptive worker analyzes failures and queues constraints
        if ep > 0:
            learned = adaptive.analyze(kernel.store)
            if learned:
                print(f"  >> LEARNED: {learned}")

        result = orch.run(trace, include_persistent=True)
        view = result.view

        actions = [k for k in view["actions"] if k != "_proposals"]
        beliefs = [k for k in view["beliefs"] if k != "_proposals"]
        predictions = {k: v.get("expected_outcome")
                       for k, v in view.get("predictions", {}).items()
                       if k != "_proposals" and isinstance(v, dict)}
        constraints = {k: v for k, v in view["constraints"].items()
                       if isinstance(v, dict) and v.get("source") == "adaptive"}

        status = "ALERT" if "alert" in actions else ("REVIEW" if "queue_for_review" in actions else "NO_ACTION")

        pred_str = str(predictions) if predictions else "-"
        learned_str = str(list(constraints.keys())) if constraints else "-"
        print(f"  Ep {ep:2d} | temp={reading['value']:5.1f} "
              f"stale={reading['stale']!s:5s} conf={reading['_confidence']:.2f} "
              f"conflict={reading['conflict']!s:5s} | "
              f"belief={'Y' if beliefs else 'N'} "
              f"pred={pred_str:<40s} "
              f"| {status:>9s} "
              f"| learned={learned_str}")

        results.append({
            "episode": ep, "trace": trace, "reading": reading,
            "status": status, "beliefs": beliefs, "predictions": predictions,
            "actions": actions, "learned_constraints": list(constraints.keys()),
            "rounds": result.rounds, "errors": result.errors,
        })

    # ── Summary ──────────────────────────────────────────────────────
    print()
    print(f"{'='*70}")
    print("  Summary")
    print(f"{'='*70}")
    alerts = sum(1 for r in results if r["status"] == "ALERT")
    reviews = sum(1 for r in results if r["status"] == "REVIEW")
    no_action = sum(1 for r in results if r["status"] == "NO_ACTION")
    all_learned = set()
    for r in results:
        all_learned.update(r["learned_constraints"])
    error_count = sum(len(r["errors"]) for r in results)

    print(f"  Episodes:     {num_episodes}")
    print(f"  Alerts sent:  {alerts}")
    print(f"  Queued:       {reviews}")
    print(f"  No action:    {no_action}")
    print(f"  Constraints learned: {sorted(all_learned) if all_learned else 'none'}")
    print(f"  Worker errors: {error_count}")
    print(f"  Session:      {session.session_id}")

    store.close()


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--episodes", type=int, default=10)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()
    run_demo(num_episodes=args.episodes, seed=args.seed)
