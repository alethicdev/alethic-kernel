# Alethic

**A governed cognition framework for AI systems.**

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.18691808.svg)](https://doi.org/10.5281/zenodo.18691808)

**Your model proposes. Alethic decides.**

Alethic is a domain-agnostic governance layer for AI agents. It sits between what an LLM *wants* to do and what it's *allowed* to do — validating every belief, plan, and action against evidence quality, confidence thresholds, and declarative constraints before anything gets committed.

The core insight: architectural governance — not model scale — is the primary bottleneck for trustworthy modular AI. An LLM decides *what* to propose; the kernel decides *whether* the proposal meets the evidence standard for commitment.

## How It Works

<p align="center">
  <!-- Absolute: PyPI renders this README with no repository to resolve a
       relative path against. Safe now that the repo is public — GitHub fetches
       README images anonymously, which is why this had to stay relative before. -->
  <img src="https://raw.githubusercontent.com/alethicdev/alethic/main/docs/architecture.png" alt="Blackboard Kernel Architecture" width="720">
</p>

Seven semantic slots hold all state. Workers read from and write to the kernel using two modes: **PROPOSE** (tentative, must pass validation) and **COMMIT** (finalized). Every proposal passes through the kernel's validation pipelines — stale evidence, missing percepts, constraint violations, and negative predictions all cause rejection, not action.

## Quick Start

```bash
pip install alethic-kernel
```

### Use as a library

```python
from alethic_kernel.alethic import AlethicClient

client = AlethicClient(mode="local")
result = client.run_episode(task_inputs={
    "chargeId": "ch_3P0x1A2B3C",
    "customerId": "cus_QXyZ123",
    "customerName": "Ada Lovelace",
    "amount": 4200,
    "disputeReason": "duplicate",
})
print(result.metrics)  # {'task_success': 1.0, 'unsafe_action': 0.0, ...}
```

### Run the benchmark

```bash
# All agents except LLM (no local model needed)
python -m alethic_kernel.run --no-llm

# Full benchmark (6 tasks, 50 seeds, 4 agents = 1200 episodes)
python -m alethic_kernel.run
```

### Start the API server

```bash
pip install "alethic-kernel[api]"
alethic serve --port 8000
```

> **The HTTP API has no authentication and is not production-ready.** Every
> endpoint is anonymous and all callers share one kernel, so any client can read
> and overwrite any other client's state by naming its `trace_id`. Bind it to
> localhost and treat it as a development and evaluation tool only. The library
> itself does not carry this limitation.

## Benchmark Results

To validate the framework, we ran 1,200 episodes (6 tasks, 50 seeds, 4 agents) across Stripe refund tasks with controlled perturbations:

| Agent | Task Success | Unsafe Actions | Unsupported Beliefs | Traceability |
|-------|-------------|----------------|---------------------|--------------|
| string_glue | 61.3% | 38.7% | 26.0% | 0.10 |
| json_glue | 57.0% | 43.0% | 31.0% | 0.30 |
| **alethic** | **100%** | **0%** | **0%** | **1.00** |
| **llm_bk** | **99.0%** | **0%** | **0%** | **1.00** |

The kernel-backed agents (`alethic` and `llm_bk`) achieve **zero unsafe actions** across all perturbation scenarios. Baseline agents act on stale, conflicting, or low-confidence evidence 39-43% of the time. The LLM agent has slightly lower task success (it sometimes declines to act even when safe) but never acts unsafely — the kernel governance is identical regardless of planner.

## Documentation

- **[Architecture](https://github.com/alethicdev/alethic/blob/main/docs/architecture.md)** — Blackboard kernel design, semantic slots, validation pipelines
- **[API Reference](https://github.com/alethicdev/alethic/blob/main/docs/api-reference.md)** — Every public class and method with signatures and return codes
- **[Workers](https://github.com/alethicdev/alethic/blob/main/docs/workers.md)** — Worker protocol, built-in workers, writing custom workers
- **[HTTP API](https://github.com/alethicdev/alethic/blob/main/docs/http-api.md)** — REST endpoints, AlethicClient SDK, OpenTelemetry
- **[Benchmark](https://github.com/alethicdev/alethic/blob/main/docs/benchmark.md)** — Tasks, perturbations, metrics, CLI reference
- **[Deployment](https://github.com/alethicdev/alethic/blob/main/docs/deployment.md)** — Docker, environment variables, store selection, testing

## Project Structure

```
alethic/               Core kernel (domain-agnostic)
  kernel.py            Blackboard kernel — central orchestrator
  schema.py            Record, Provenance, Slot, WriteMode
  validators.py        Evidence and symbolic validation
  store.py             In-memory store
  sqlite_store.py      SQLite-backed persistent store
  orchestrator.py      Worker round-robin loop
  sim_worker.py        Rule-based forward simulator
  adaptive_worker.py   Learns constraints from failure patterns
  session.py           Multi-episode session management
  client.py            AlethicClient (local + HTTP modes)
  api/                 FastAPI server
agents/                Four agents of increasing sophistication
  string_glue.py       Baseline: always acts, no validation
  json_glue.py         Adds confidence scores, still always acts
  alethic_agent.py     Full kernel with deterministic planner
  llm_agent.py         Full kernel with LLM planner
eval/                  Evaluation framework
  harness.py           Task x seed x agent runner
  metrics.py           5 safety and traceability metrics
  report.py            Markdown report generation
tools/                 Simulated tools with perturbations
tasks/                 6 Stripe refund task definitions (YAML)
examples/              Multi-episode demo with adaptive learning
results/               Benchmark outputs (JSONL + report)
```

## Research Paper

The full academic treatment is in [From Fragile Glue to Governed Cognition](https://doi.org/10.5281/zenodo.18691808) — a controlled study of blackboard kernels for modular AI systems. Paper artifact repository: [governed-cognition](https://github.com/emiluzelac/governed-cognition).

## License

MIT
