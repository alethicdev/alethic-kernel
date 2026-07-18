"""Optional OpenTelemetry tracing. No-op if opentelemetry-api is not installed."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Generator, Optional

_tracer: Optional[Any] = None
_HAS_OTEL = False

try:
    from opentelemetry import trace as _trace
    _tracer = _trace.get_tracer("alethic.kernel")
    _HAS_OTEL = True
except ImportError:  # pragma: no cover
    pass


@contextmanager
def span(name: str, **attributes: Any) -> Generator[Any, None, None]:
    """Create a traced span if OpenTelemetry is available, otherwise no-op."""
    if _HAS_OTEL and _tracer is not None:
        with _tracer.start_as_current_span(name, attributes=attributes) as s:
            yield s
    else:
        yield None
