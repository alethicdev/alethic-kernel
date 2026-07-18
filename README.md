# Alethic

**A governed cognitive substrate for AI systems.**

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.18691808.svg)](https://doi.org/10.5281/zenodo.18691808)

Models propose. Alethic decides what may enter state and what may become action.

Alethic places a small, enforceable kernel between reasoning components and
external effects. It maintains typed state, links beliefs to evidence, applies
declarative constraints, and records why each proposal was committed or
invalidated. The kernel contains no model, prompt, tool, task, or domain logic.

## Install

The Python distribution is named `alethic-kernel`; its single import namespace
is `alethic`.

```bash
pip install alethic-kernel
```

## Use

```python
from alethic import Kernel

kernel = Kernel()
trace = "episode-001"

kernel.write(
    "tool",
    "percepts",
    "COMMIT",
    "observation",
    {"value": 42, "stale": False, "conflict": False},
    trace,
    confidence=0.9,
)

proposal = kernel.write(
    "planner",
    "beliefs",
    "PROPOSE",
    "threshold_reached",
    {"value": True, "depends_on": ["observation"]},
    trace,
    input_refs=["observation"],
)

committed, reason = kernel.commit_belief_from_proposal(proposal.id, trace)
print(committed, reason)
```

Every worker can propose. Only the kernel can commit. State lives in seven
semantic slots: percepts, beliefs, constraints, plans, evidence, predictions,
and actions.

## What belongs here

This repository contains only the domain-neutral Alethic substrate:

- the governed blackboard kernel and typed record schema;
- evidence, confidence, conflict, constraint, and prediction validation;
- in-memory and SQLite stores;
- worker orchestration, sessions, simulation, and adaptive constraints;
- tests, architectural documentation, and a domain-neutral example.

The controlled study, results, and verification artifacts live separately in
[governed-cognition](https://github.com/emiluzelac/governed-cognition).

## Documentation

- [Architecture](docs/architecture.md)
- [API reference](docs/api-reference.md)
- [Workers](docs/workers.md)
- [Research paper](https://doi.org/10.5281/zenodo.18691808)

## Source layout

The repository name is Alethic exactly once. Setuptools maps `src/` directly to
the installed `alethic` namespace.

```text
src/
  __init__.py
  kernel.py
  schema.py
  permissions.py
  validators.py
  store.py
  sqlite_store.py
  worker.py
  orchestrator.py
  session.py
  sim_worker.py
  adaptive_worker.py
```

## Development

```bash
python -m pip install -e ".[dev]"
pytest
mypy --strict src
```

## License

MIT © Emil Uzelac
