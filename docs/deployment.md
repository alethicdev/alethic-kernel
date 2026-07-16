# Deployment

## Requirements

- Python 3.11+
- No external runtime dependencies for the core kernel and benchmark
- FastAPI + uvicorn for the API server (`[api]` extra)
- pytest + mypy for development (`[dev]` extra)

## Installation

```bash
# Core package (kernel + benchmark)
pip install alethic-kernel

# With API server
pip install "alethic-kernel[api]"
```

From a source checkout, for development:

```bash
# Core package (kernel + benchmark)
pip install -e .

# With development tools
pip install -e ".[dev]"

# Everything
pip install -e ".[api,dev]"
```

## Docker

The Dockerfile uses a multi-stage build with two targets:

### API Server

```bash
docker build --target api -t alethic-api .
docker run -p 8000:8000 alethic-api
```

The API container exposes port 8000, includes a healthcheck on `/healthz`, and runs uvicorn with the FastAPI app.

### Benchmark Runner

```bash
docker build --target bench -t alethic .
docker run alethic
```

Runs the benchmark with `--no-llm` (no local model needed inside the container).

### Docker Compose

```bash
# API server only
docker compose up alethic-api

# API server + Ollama for LLM agent
docker compose --profile llm up
```

The compose file defines two services:

| Service | Port | Description |
|---------|------|-------------|
| `alethic-api` | 8000 | API server with in-memory store |
| `ollama` | 11434 | Ollama LLM server (profile: `llm`) |

## Database Migrations

When using SQLite persistence, run migrations on an existing database:

```bash
alethic migrate blackboard.db
```

Migrations are applied automatically when `SqliteStore` is initialized. The `migrate` command is for manual upgrades of databases created by older versions.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ALETHIC_STORE` | `memory` | Store backend: `memory` or `sqlite` |
| `ALETHIC_DB_PATH` | `blackboard.db` | SQLite database file path |

These are read by the API server's dependency injection. CLI flags (`--store`, `--db-path`) take precedence.

## Store Selection

| Use Case | Store | Reason |
|----------|-------|--------|
| Benchmark runs | `MemoryStore` | Fast, no persistence needed |
| Unit tests | `MemoryStore` | Isolated, no cleanup |
| API server (dev) | `MemoryStore` | Simple, no file management |
| Multi-episode learning | `SqliteStore` | Persistent records across episodes |
| Custom integration | Implement `StoreProtocol` | 6 methods to satisfy |

> **`SqliteStore` is not yet recommended for production.** It is durable and
> correct for single-process, single-kernel use, but it has known gaps that
> `MemoryStore` does not: commits span multiple transactions (a crash mid-commit
> can leave an evidence record for a belief that was never written), record IDs
> come from an in-process counter (so reusing a `trace_id` after a restart, or
> running more than one worker, raises `IntegrityError`), and it can disagree with
> `MemoryStore` on TTL-expired evidence. Track these before depending on it.
>
> Note also that the [HTTP API has no authentication](http-api.md#security), so
> "production API server" is not a supported posture in any store configuration
> today.

## Testing

```bash
# Run all tests (349 tests)
pytest tests/ -v

# Single test file
pytest tests/test_kernel.py -v

# Coverage report
pytest --cov=alethic --cov-report=term-missing

# Type checking (strict mode, 0 errors across 37 source files)
mypy --strict -p alethic_kernel.alethic -p alethic_kernel.llm -p alethic_kernel.agents -p alethic_kernel.eval -p alethic_kernel.tools
```
