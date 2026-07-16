# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Alethic is a governed cognition framework for AI systems. It provides a domain-agnostic governance layer (the Blackboard Kernel) that sits between what an LLM wants to do and what it's allowed to do — validating every belief, plan, and action against evidence quality, confidence thresholds, and declarative constraints before anything gets committed. The framework includes a benchmark harness that compares four agents (StringGlue, JsonGlue, Alethic deterministic, LLM+Alethic) under controlled perturbations (stale data, conflicts, low confidence, tool failures). The current example domain is Stripe payment refunds. The core kernel is fully generic and domain-agnostic.

## Running the Benchmark

```bash
# Full benchmark (6 tasks, 50 seeds, 4 agents = 1200 episodes)
python -m alethic_kernel.run

# Without LLM agent (no local model needed)
python -m alethic_kernel.run --no-llm

# Specific agents only
python -m alethic_kernel.run --agents llm_bk --seeds 10

# Custom perturbation rates
python -m alethic_kernel.run --tasks stripe_refund_clean --seeds 10 --stale 0.10 --conflict 0.10 --low-confidence 0.10

# Custom LLM endpoint
python -m alethic_kernel.run --llm-url http://localhost:11434/v1/chat/completions --llm-model qwen3:8b

# Remote LLM with API key and reasoning_effort
python -m alethic_kernel.run --agents llm_bk --seeds 50 \
  --llm-url https://llama.iam.clinic/v1/chat/completions \
  --llm-model gpt-oss-20b \
  --llm-api-key $HOMESERVER_API_KEY \
  --reasoning-effort low

# Generate markdown report from existing results
python -m alethic_kernel.run --build-report --input results.jsonl --out-report report.md
```

No external runtime dependencies beyond the Python standard library. The LLM agent requires an OpenAI-compatible API endpoint (default: localhost:11434 via Ollama). Remote endpoints are supported via `--llm-api-key` and `--reasoning-effort`.

## Development

```bash
# Install in development mode
pip install -e ".[dev]"

# Run all tests (349 tests)
pytest tests/ -v

# Run a single test file
pytest tests/test_kernel.py -v

# Coverage report
pytest --cov=alethic --cov-report=term-missing

# Type checking (strict mode, 0 errors across 37 source files)
mypy --strict -p alethic_kernel.alethic -p alethic_kernel.llm -p alethic_kernel.agents -p alethic_kernel.eval -p alethic_kernel.tools
```

## CLI Subcommands

The CLI supports both subcommand and legacy modes:

```bash
# Subcommand mode
alethic run --tasks stripe_refund_clean --seeds 10 --no-llm
alethic serve --store sqlite --port 8000
alethic migrate blackboard.db
alethic report --input results.jsonl --out-report report.md

# Legacy mode (backward compatible, no subcommand)
python -m alethic_kernel.run --no-llm --seeds 10
python -m alethic_kernel.run --build-report --input results.jsonl
```

## API Server

```bash
# Start with in-memory store
pip install -e ".[api]"
alethic serve

# Start with SQLite persistence
alethic serve --store sqlite --db-path blackboard.db

# Docker
docker compose up
```

Endpoints: `/healthz`, `/readyz`, `/v1/write`, `/v1/commit/belief`, `/v1/commit/action`, `/v1/commit/prediction`, `/v1/validate/plan`, `/v1/view/{trace_id}`, `/v1/episode`. OpenAPI docs at `/docs`.

## Python Client

```python
from alethic_kernel.alethic import AlethicClient

# Local mode (in-process kernel, no network)
client = AlethicClient(mode="local")
result = client.run_episode(task_inputs={...}, constraints={...})

# HTTP mode (calls running API server)
client = AlethicClient(mode="http", base_url="http://localhost:8000")
result = client.run_episode(task_inputs={...})
```

## Architecture

### Core Kernel (`alethic/`) — Cognitive Substrate

The Blackboard Kernel (`kernel.py`) is the central orchestrator. It manages seven semantic slots: `percepts`, `beliefs`, `constraints`, `plans`, `evidence`, `predictions`, `actions`. Records are written in two modes: `PROPOSE` (tentative) or `COMMIT` (finalized). The kernel contains zero domain-specific logic.

- **`schema.py`** — `Record` (with `scope: "episode"|"persistent"`), `Provenance`, `Slot`, `WriteMode` dataclasses
- **`permissions.py`** — Role-based access control (tool, planner, symbolic_validator, evidence_validator, sim_validator, kernel)
- **`store.py`** — `MemoryStore`: in-memory record storage with TTL enforcement and record lookup by kind
- **`store_protocol.py`** — `StoreProtocol` (`typing.Protocol`): explicit interface for pluggable store backends
- **`sqlite_store.py`** — `SqliteStore`: persistent SQLite-backed store (WAL mode, indexed queries, survives process restarts)
- **`validators.py`** — `EvidenceValidator` (stale, missing, conflict detection) and `SymbolicValidator` (declarative constraint rules)
- **`worker.py`** — `Worker` protocol and `BaseWorker` convenience dataclass for cognitive components
- **`sim_worker.py`** — `SimulatorWorker` + `SimRule`: declarative rule-based forward simulator with condition operators (gt, lt, gte, lte, ne, eq)
- **`adaptive_worker.py`** — `AdaptiveWorker`: scans store for failure patterns, derives persistent constraints when threshold exceeded
- **`orchestrator.py`** — `Orchestrator`: generic round-robin loop over workers with dependency ordering, quiescence detection, and per-worker error handling
- **`session.py`** — `Session` dataclass for multi-episode contexts with `episode_trace_id()` generation

Key kernel capabilities:
- **Evidence validation**: rejects beliefs dependent on stale, missing, or conflicting percepts
- **Confidence thresholds**: rejects beliefs when dependent percepts have confidence below `min_confidence` (default 0.5)
- **Conflict arbitration**: conflicts with high-confidence sources (>= `conflict_confidence_threshold`, default 0.7) are arbitrated and allowed through
- **Plan validation**: pre-flight feasibility check on proposed action plans before individual actions are committed
- **Prediction slot**: forward dynamics — predictions proposed by planners/simulators, committed by kernel, optionally gate actions
- **Prediction-gated actions**: `commit_action_from_proposal(require_prediction=True)` enforces prediction with non-negative outcome before action commit
- **Evidence recording**: every successful belief commit writes an evidence artifact documenting what checks passed
- **TTL enforcement**: records with `ttl_ms` auto-expire when accessed after their TTL elapses
- **Session scoping**: records tagged `scope="persistent"` survive across episodes; `current_view(include_persistent=True)` includes them
- **Pluggable store**: kernel accepts any `StoreProtocol` implementation (defaults to `MemoryStore`)
- **Worker orchestration**: `Orchestrator` runs workers in dependency order until quiescence or max rounds

### LLM Planner (`llm/`)

- **`planner.py`** — OpenAI-compatible chat completion client using `urllib` (no external packages). Provides `propose_belief()`, `propose_plan()`, `propose_action()`. Supports `api_key` (Bearer auth) and `reasoning_effort` (passed through to request body) for remote endpoints. Includes `_strip_think()` and `_extract_json()` for robust response parsing. Default endpoint: `localhost:11434` (Ollama), default model: `qwen3:8b`.

### Agents (`agents/`)

Four agents of increasing sophistication:
- **`string_glue.py`** — Baseline: always acts, no validation
- **`json_glue.py`** — Adds confidence scores but still always acts
- **`alethic_agent.py`** — Full kernel orchestration with deterministic planner
- **`llm_agent.py`** — Full kernel orchestration with LLM planner. The LLM decides *whether* to propose; the agent governs belief names, dependencies, and action fields. The kernel validation pipeline is identical to the deterministic agent.

### Evaluation (`eval/`)

- **`task_loader.py`** — Loads YAML/JSON task definitions from `tasks/`
- **`harness.py`** — `run_suite()` iterates over tasks x seeds x agents
- **`metrics.py`** — Computes `task_success`, `unsafe_action`, `unsupported_belief`, `traceability`, `failure_transparency`. Evidence is "tainted" if stale, conflicting, or low-confidence. Constraint violations (e.g., duplicate refund with `no_duplicate_refund` active) are also detected.
- **`report.py`** — Renders markdown summary tables

### Tools (`tools/`)

Simulated external tools with deterministic perturbation via seed+key hashing (`perturb.py`):
- **`payment_tool.py`** — Stripe charge lookup with configurable perturbation rates for staleness, conflict, low confidence, and tool failure
- **`refund_tool.py`** — Stripe refund renderer with duplicate detection

### Task Definitions (`tasks/`)

6 Stripe payment refund tasks exercising different failure modes. Tasks are JSON files (`.yaml` extension) with declarative constraints:
```json
"constraints": {
  "no_duplicate_refund": {"blocks_field": "is_duplicate"}
}
```

## Data Flow

`run.py` loads tasks -> `run_suite` creates tool instances per (task, seed) -> each agent runs against the tools -> metrics computed per episode with task context -> results written to JSONL -> optional markdown report.

## Key Design Patterns

- All domain objects are `@dataclass` with type hints (`from __future__ import annotations`)
- Deterministic randomness: `PerturbConfig` hashes seed+key for reproducible perturbations
- Proposals are invalidated on rejection (with reason) or on successful commit (`SUPERSEDED_BY_COMMIT`)
- Alethic agent pipeline: commit constraints -> commit percepts -> propose belief -> evidence validation + confidence check + conflict arbitration -> write evidence record -> propose plan -> validate plan feasibility -> propose action -> symbolic validation -> commit or queue_for_review
- LLM agent: same pipeline, but belief/plan/action proposals come from LLM calls; agent normalizes LLM output to governed schema before writing to kernel
- Worker protocol: any component implementing `Worker` (worker_id, role, reads, writes, should_activate, step) can be orchestrated by the generic `Orchestrator`
- Session persistence: records with `scope="persistent"` accumulate across episodes; adaptive workers can learn constraints from past outcomes

### Examples (`examples/`)

- **`multi_episode.py`** — Domain-agnostic demo: monitoring system with sensor, analyst, simulator, actuator, and adaptive workers across N episodes. SqliteStore persistence, real rule-based predictions, real outcome-driven constraint learning. Run: `python examples/multi_episode.py --episodes 20 --seed 42`

### Results (`results/`)

Benchmark output files:
- **`results.jsonl`** — Merged final results (1200 episodes, 4 agents)
- **`det_results.jsonl`** — Deterministic agents only (900 episodes)
- **`llm_results_v2.jsonl`** — LLM agent with tuned prompts (300 episodes)
- **`results_v1.jsonl`** — Historical: first LLM run with untuned prompts
- **`report.md`** — Rendered markdown report
