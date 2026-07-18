# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - Unreleased

### Changed

- Flattened the public Python namespace from `alethic_kernel.alethic` to
  `alethic_kernel`.
- Moved the installable package into the conventional `src/alethic_kernel`
  layout.
- Renamed the source repository to `alethicdev/alethic-kernel` so the GitHub,
  PyPI, and Python package names describe the same artifact.

## [0.1.0] - 2026-07-16

### Added

- **Blackboard Kernel** — Core governed cognition substrate with 7 semantic slots (percepts, beliefs, constraints, plans, evidence, predictions, actions)
- **PROPOSE/COMMIT Protocol** — Two-phase validation ensuring all decisions pass evidence quality checks before commitment
- **Validation Pipelines**
  - Evidence validation (staleness, missing percepts, conflict detection)
  - Confidence thresholds (0.5 default minimum confidence)
  - Conflict arbitration (high-confidence sources override conflicts)
  - Constraint-based action gating
  - Prediction-gated actions (optional forward validation)
- **Role-Based Access Control** — 6 roles with explicit permission model (tool, planner, symbolic_validator, evidence_validator, sim_validator, kernel)
- **Store Abstraction**
  - `MemoryStore` — Thread-safe in-memory store (default)
  - `SqliteStore` — WAL-mode SQLite with persistent records and indexed queries
- **Worker Protocol** — Extensible worker framework for cognitive components
  - `SimulatorWorker` — Rule-based forward simulator with declarative conditions
  - `AdaptiveWorker` — Learns constraints from failure patterns across episodes
  - `Orchestrator` — Generic round-robin scheduler with dependency ordering
- **Four Reference Agents**
  - `StringGlue` — Baseline (always acts, no validation)
  - `JsonGlue` — Confidence tracking but no validation
  - `AlethicAgent` — Full kernel with deterministic planner
  - `LLMAgent` — Full kernel with LLM-based planner (OpenAI-compatible)
- **Evaluation Framework**
  - Task loader for YAML/JSON task definitions
  - Benchmark harness (1,200 episodes: 6 tasks × 50 seeds × 4 agents)
  - 5 metrics: task success, unsafe actions, unsupported beliefs, traceability, evidence taint
  - Perturbation system (staleness, conflicts, low confidence, tool failures)
  - Markdown report generation
- **Example Domain: Stripe Refunds**
  - 6 refund tasks exercising different failure modes
  - Constraints: no duplicate refunds, no partial refunds without evidence
  - Perturbation scenarios validating governance under adversarial conditions
- **HTTP API**
  - FastAPI server with `/v1/write`, `/v1/commit/*`, `/v1/validate/*` endpoints
  - OpenTelemetry support for distributed tracing
  - OpenAPI documentation at `/docs`
  - Docker and docker-compose deployment
- **Comprehensive Documentation**
  - Architecture guide with semantic slots and validation pipelines
  - API reference for all public classes and methods
  - Worker protocol and custom worker examples
  - HTTP API specification
  - Benchmark methodology and CLI reference
  - Deployment guide with store selection and environment variables
- **Type Safety** — Strict mypy configuration across all modules
- **Test Suite** — 349 unit and integration tests with pytest

### Benchmark Results

In a controlled evaluation of 1,200 episodes:

| Agent | Task Success | Unsafe Actions | Unsupported Beliefs | Traceability |
|-------|-------------|----------------|---------------------|--------------|
| StringGlue | 61.3% | 38.7% | 26.0% | 0.10 |
| JsonGlue | 57.0% | 43.0% | 31.0% | 0.30 |
| **Alethic** | **100%** | **0%** | **0%** | **1.00** |
| **LLM+Alethic** | **99.0%** | **0%** | **0%** | **1.00** |

- Kernel-backed agents achieve zero unsafe actions across all perturbation scenarios
- Baseline agents produce unsafe actions 39-43% of the time on stale/conflicting/low-confidence data
- LLM agent demonstrates that governance generalizes regardless of planner implementation

### Known Limitations

- Example domain currently limited to Stripe refund tasks (kernel itself is domain-agnostic)
- LLM planner sometimes declines to act conservatively, reducing task success vs. deterministic agent
- Local LLM inference requires OpenAI-compatible endpoint (defaults to Ollama on localhost:11434)

### Paper & Attribution

Alethic is the reference implementation of [From Fragile Glue to Governed Cognition](https://doi.org/10.5281/zenodo.18691808), a controlled study of blackboard kernels for modular AI systems.
