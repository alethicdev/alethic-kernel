# Workers

Workers are modular cognitive components that read from and write to the blackboard. The `Orchestrator` runs workers in dependency order until no worker produces new output (quiescence) or a maximum round count is reached.

## Worker Protocol

Any object satisfying the `Worker` protocol can be orchestrated:

```python
@runtime_checkable
class Worker(Protocol):
    worker_id: str                    # Unique identifier
    role: Role                        # Determines write permissions
    reads: FrozenSet[Slot]            # Slots this worker reads
    writes: FrozenSet[Slot]           # Slots this worker writes

    def should_activate(self, view: Dict[str, Dict[str, Any]]) -> bool:
        """Return True if this worker has work to do."""
        ...

    def step(self, kernel: Any, trace_id: str,
             view: Dict[str, Dict[str, Any]]) -> bool:
        """Execute one unit of work. Return True if something was written."""
        ...
```

The `writes` field determines dependency ordering — workers that write to earlier slots (percepts → beliefs → constraints → ...) run first.

## BaseWorker

`alethic.worker.BaseWorker` — Convenience dataclass that satisfies the `Worker` protocol with no-op defaults:

```python
@dataclass
class BaseWorker:
    worker_id: str = ""
    role: Role = "tool"
    reads: FrozenSet[Slot] = frozenset()
    writes: FrozenSet[Slot] = frozenset()

    def should_activate(self, view) -> bool:
        return False

    def step(self, kernel, trace_id, view) -> bool:
        return False
```

Subclass `BaseWorker` and override `should_activate` and `step` to create custom workers.

## SimulatorWorker

`alethic.sim_worker.SimulatorWorker` — Evaluates declarative rules against the current blackboard view and proposes predictions through the kernel's `commit_prediction()` pipeline.

### SimRule

```python
@dataclass
class SimRule:
    action_type: str                                        # Action this prediction is about
    expected_outcome: float                                 # Positive = favorable, negative = unfavorable
    requires_beliefs: List[str] = []                        # Belief kinds that must be committed
    percept_conditions: Dict[str, Dict[str, Any]] = {}      # Conditions on percepts
    belief_conditions: Dict[str, Dict[str, Any]] = {}       # Conditions on beliefs
    confidence: float = 0.8                                 # Confidence for the prediction
```

### Condition Operators

Conditions use `field__op` syntax for comparisons:

| Operator | Syntax | Example |
|----------|--------|---------|
| equals | `"field"` | `{"value": 100}` |
| greater than | `"field__gt"` | `{"value__gt": 90}` |
| less than | `"field__lt"` | `{"value__lt": 50}` |
| greater or equal | `"field__gte"` | `{"value__gte": 90}` |
| less or equal | `"field__lte"` | `{"value__lte": 90}` |
| not equal | `"field__ne"` | `{"status__ne": "closed"}` |

### Example

```python
from alethic.sim_worker import SimulatorWorker, SimRule

rules = [
    SimRule(
        action_type="alert",
        expected_outcome=1.0,
        requires_beliefs=["anomaly_detected"],
        percept_conditions={"temperature": {"value__gt": 90}},
        confidence=0.85,
    ),
    SimRule(
        action_type="alert",
        expected_outcome=-0.5,
        requires_beliefs=["anomaly_detected"],
        percept_conditions={"temperature": {"value__lte": 90}},
        confidence=0.7,
    ),
]

simulator = SimulatorWorker(rules=rules)
```

The simulator activates once beliefs exist, evaluates all rules, and proposes predictions for rules whose conditions match. It runs once per episode (call `simulator.reset()` between episodes).

## AdaptiveWorker

`alethic.adaptive_worker.AdaptiveWorker` — Scans the store for invalidated records, counts failure patterns by reason code, and commits persistent constraints when a pattern exceeds a configurable threshold.

```python
adaptive = AdaptiveWorker(failure_threshold=2)
```

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| `failure_threshold` | `int` | `2` | Occurrences before a constraint is derived |
| `reason_to_constraint` | `Dict` | (built-in) | Maps reason codes to constraint definitions |
| `emitted` | `Set[str]` | `set()` | Constraint names already committed |

### Built-in Reason Mappings

| Reason Code | Constraint Name | Blocks Field |
|-------------|----------------|--------------|
| `STALE_EVIDENCE` | `block_stale_actions` | `uses_stale_data` |
| `UNRESOLVED_CONFLICT` | `block_conflicted_actions` | `uses_conflicted_data` |
| `LOW_CONFIDENCE` | `block_low_confidence_actions` | `uses_low_confidence_data` |
| `NEGATIVE_PREDICTION` | `block_negative_predictions` | `has_negative_prediction` |

### Usage

Call `analyze(store)` between episodes to scan for failure patterns:

```python
learned = adaptive.analyze(kernel.store)
# learned = ["block_stale_actions"]  (if threshold was met)
```

On the next orchestrator run, the worker commits any queued constraints as persistent records. Constraints derived this way have `scope="persistent"` and `source="adaptive"` in their payload.

## Orchestrator

`alethic.orchestrator.Orchestrator` — Runs workers in dependency-sorted order until quiescence or max rounds.

```python
orch = Orchestrator(
    kernel=kernel,
    workers=[sensor, analyst, simulator, actuator, adaptive],
    max_rounds=20,
    on_error=None,  # Optional callback: Callable[[str, Exception], None]
)
```

### `run()`

```python
result = orch.run(trace_id, include_persistent=False)
```

Returns `OrchestratorResult`:

```python
@dataclass
class OrchestratorResult:
    trace_id: str                          # The trace_id that was run
    view: Dict[str, Dict[str, Any]]        # Final blackboard state
    rounds: int                            # Number of rounds executed
    worker_log: List[Dict[str, Any]]       # [{round, worker, produced}, ...]
    errors: List[Dict[str, Any]]           # [{worker, phase, error, type}, ...]
```

Workers are sorted by `writes` dependency (percepts=0, beliefs=1, ..., actions=6). Each round, every worker that returns `True` from `should_activate()` gets a `step()` call. If any worker produces, the view is refreshed before the next worker runs. Worker exceptions are caught, logged in `errors`, and the loop continues.

## Writing a Custom Worker

Here's a complete example from the multi-episode demo — a sensor worker that commits percepts:

```python
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet
from alethic.worker import BaseWorker
from alethic.schema import Slot

@dataclass
class SensorWorker(BaseWorker):
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
```

Key patterns:
1. **Subclass `BaseWorker`** and set `worker_id`, `role`, `reads`, `writes`
2. **`should_activate()`** returns `True` when the worker has work to do based on the current view
3. **`step()`** does exactly one unit of work using the kernel's `write()` method and returns `True` if it produced output
4. **Use a `_done` flag** to prevent re-activation in the same episode
5. **Add a `reset()` method** if the worker needs to run again in subsequent episodes

See `examples/multi_episode.py` for a complete working system with sensor, analyst, simulator, actuator, and adaptive workers.
