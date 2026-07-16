# HTTP API

The Alethic kernel exposes a REST API via FastAPI, providing both low-level kernel operations and a high-level episode endpoint. The `AlethicClient` SDK provides a unified Python interface for both local and HTTP modes.

## Security

**The HTTP API is a development and evaluation tool. Do not expose it to a
network you do not control.** It has no authentication, and the governance
guarantees the library provides do not survive the network boundary:

- **No authentication or authorization.** Every endpoint is anonymous.
- **All callers share one kernel.** `trace_id` is a caller-supplied string, so it
  namespaces state but does not isolate it. Any client can read, overwrite, or
  corrupt any other client's records by naming their `trace_id`.
- **`role` is self-asserted.** It arrives in the request body, so a caller can
  claim the `kernel` role and commit directly — bypassing validation entirely.
- **Request bodies are unbounded**, and records are never evicted.

Bind to loopback, keep it behind your own authenticating proxy, and only give it
traffic you trust. Use the library in-process if you need the governance
guarantees to hold.

## Starting the Server

```bash
# Install API dependencies
pip install "alethic-kernel[api]"

# In-memory store (default), bound to localhost
alethic serve

# SQLite persistence
alethic serve --store sqlite --db-path blackboard.db

# Custom port with auto-reload
alethic serve --port 9000 --reload
```

| Flag | Default | Description |
|------|---------|-------------|
| `--host` | `0.0.0.0` | Bind address |
| `--port` | `8000` | Port |
| `--store` | `memory` | Store backend: `memory` or `sqlite` |
| `--db-path` | `None` | SQLite database path (only with `--store sqlite`) |
| `--reload` | off | Enable uvicorn auto-reload for development |

Environment variables `ALETHIC_STORE` and `ALETHIC_DB_PATH` can also configure the store. OpenAPI docs are served at `/docs`.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/healthz` | Health check |
| GET | `/readyz` | Readiness check (includes store type) |
| POST | `/v1/write` | Write a record to the blackboard |
| POST | `/v1/commit/belief` | Commit a belief proposal |
| POST | `/v1/commit/action` | Commit an action proposal |
| POST | `/v1/commit/prediction` | Commit a prediction proposal |
| POST | `/v1/validate/plan` | Validate a plan proposal |
| GET | `/v1/view/{trace_id}` | Get current blackboard view |
| POST | `/v1/episode` | Run a full agent episode |

### Health Checks

**GET `/healthz`**

```json
{"status": "ok"}
```

**GET `/readyz`**

```json
{"status": "ready", "store": "memory"}
```

### Write

**POST `/v1/write`**

Request:

```json
{
  "role": "tool",
  "slot": "percepts",
  "mode": "COMMIT",
  "kind": "charge",
  "payload": {"amount": 2999, "currency": "usd"},
  "trace_id": "ep-001",
  "input_refs": [],
  "confidence": 0.95,
  "ttl_ms": null,
  "evidence_refs": [],
  "scope": "episode"
}
```

Response:

```json
{
  "ok": true,
  "record": {
    "id": "percepts:ep-001:1",
    "slot": "percepts",
    "mode": "COMMIT",
    "kind": "charge",
    "payload": {"amount": 2999, "currency": "usd"},
    "status": "ACTIVE",
    "scope": "episode",
    "trace_id": "ep-001",
    "confidence": 0.95
  }
}
```

Returns **403** if the role is not authorized for the slot+mode combination.

> **The 403 is a schema check, not authorization.** `role` is read from the
> request body, so a client chooses its own role — including `kernel`, which may
> COMMIT. This endpoint therefore cannot enforce the permissions matrix against
> an untrusted caller. See [Security](#security).

### Commit Belief

**POST `/v1/commit/belief`**

Request:

```json
{
  "proposal_id": "beliefs:ep-001:1",
  "trace_id": "ep-001"
}
```

Response:

```json
{"ok": true, "code": "COMMITTED"}
```

Or on failure:

```json
{"ok": false, "code": "STALE_EVIDENCE"}
```

See [API Reference — commit_belief_from_proposal()](api-reference.md#commit_belief_from_proposal) for all return codes.

### Commit Action

**POST `/v1/commit/action`**

Request:

```json
{
  "proposal_id": "actions:ep-001:1",
  "trace_id": "ep-001",
  "require_prediction": false
}
```

Response:

```json
{"ok": true, "code": "COMMITTED"}
```

### Commit Prediction

**POST `/v1/commit/prediction`**

Request:

```json
{
  "proposal_id": "predictions:ep-001:1",
  "trace_id": "ep-001"
}
```

Response:

```json
{"ok": true, "code": "COMMITTED"}
```

### Validate Plan

**POST `/v1/validate/plan`**

Request:

```json
{
  "proposal_id": "plans:ep-001:1",
  "trace_id": "ep-001"
}
```

Response:

```json
{"ok": true, "code": "PLAN_FEASIBLE"}
```

### View

**GET `/v1/view/{trace_id}?include_persistent=false`**

Response:

```json
{
  "trace_id": "ep-001",
  "view": {
    "percepts": {"charge": {"amount": 2999}},
    "beliefs": {"refund_due": {"value": true, "depends_on": ["charge"]}},
    "constraints": {},
    "plans": {},
    "evidence": {"validation_refund_due": {"result": "pass"}},
    "predictions": {},
    "actions": {"issue_refund": {"type": "issue_refund"}}
  }
}
```

### Episode

**POST `/v1/episode`**

Runs a full agent episode with a fresh kernel.

Request:

```json
{
  "task_inputs": {"charge_id": "ch_3P0x1A2B3C", "customer_name": "Marko"},
  "constraints": {"no_duplicate_refund": {"blocks_field": "is_duplicate"}},
  "agent": "alethic"
}
```

Response:

```json
{
  "trace_id": "api_episode-abc123",
  "final": {"action": "issue_refund", "validation_code": "COMMITTED"},
  "view": { ... },
  "metrics": {
    "task_success": 1.0,
    "unsafe_action": 0.0,
    "unsupported_belief": 0.0,
    "traceability": 1.0,
    "failure_transparency": 1.0
  }
}
```

---

## AlethicClient SDK

`alethic_kernel.alethic.AlethicClient` — Unified Python client that works identically in local and HTTP modes.

### Constructor

```python
from alethic_kernel.alethic import AlethicClient

client = AlethicClient(
    mode="local",                          # "local" or "http"
    base_url="http://localhost:8000",       # Only used in HTTP mode
    store=None,                            # Optional StoreProtocol (local mode only)
)
```

### High-Level API

#### `run_episode()`

```python
result = client.run_episode(
    task_inputs={"charge_id": "ch_3P0x1A2B3C"},
    constraints={"no_duplicate_refund": {"blocks_field": "is_duplicate"}},
    agent="alethic",
)
# result.trace_id, result.final, result.view, result.metrics
```

Returns an `EpisodeResult` dataclass:

```python
@dataclass
class EpisodeResult:
    trace_id: str
    final: Dict[str, Any]
    view: Dict[str, Dict[str, Any]]
    metrics: Dict[str, float]
```

### Low-Level API

These mirror the kernel methods and work in both modes:

| Method | Signature |
|--------|-----------|
| `write()` | `(role, slot, mode, kind, payload, trace_id, ...) -> Dict` |
| `commit_belief()` | `(proposal_id, trace_id) -> Tuple[bool, str]` |
| `commit_action()` | `(proposal_id, trace_id, require_prediction=False) -> Tuple[bool, str]` |
| `commit_prediction()` | `(proposal_id, trace_id) -> Tuple[bool, str]` |
| `validate_plan()` | `(proposal_id, trace_id) -> Tuple[bool, str]` |
| `current_view()` | `(trace_id, include_persistent=False) -> Dict` |
| `health()` | `() -> Dict[str, str]` |

### Local Mode Example

```python
from alethic_kernel.alethic import AlethicClient

client = AlethicClient(mode="local")

# Write a percept
client.write("tool", "percepts", "COMMIT", "charge",
             {"amount": 2999, "stale": False}, "ep-001", confidence=0.95)

# Propose and commit a belief
client.write("planner", "beliefs", "PROPOSE", "refund_due",
             {"value": True, "depends_on": ["charge"]}, "ep-001")
ok, code = client.commit_belief("beliefs:ep-001:1", "ep-001")
```

### HTTP Mode Example

```python
from alethic_kernel.alethic import AlethicClient

client = AlethicClient(mode="http", base_url="http://localhost:8000")

# Same API, calls the running server
result = client.run_episode(task_inputs={"charge_id": "ch_3P0x1A2B3C"})
print(result.metrics)
```

---

## OpenTelemetry

The API server includes opt-in OpenTelemetry tracing. If `opentelemetry-api` is installed, every endpoint call creates a span with relevant attributes (slot, kind, proposal_id, trace_id, etc.). If not installed, tracing is a no-op with zero overhead.

```bash
pip install opentelemetry-api opentelemetry-sdk
```

Span names follow the pattern `kernel.{operation}` (e.g., `kernel.write`, `kernel.commit_belief`, `kernel.current_view`). The `episode` span wraps the full high-level episode execution.
