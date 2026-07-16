"""FastAPI application factory."""
from __future__ import annotations

import math
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .routes import router
from .dependencies import reset_shared_state


def _json_safe(value: Any) -> Any:
    """Replace non-finite floats with their repr so the value can be encoded.

    Validation errors echo the offending input back to the client, and a
    rejected NaN or infinity is not JSON-encodable — without this the 422 fails
    to serialize and the client gets a 500 instead of the reason it was refused.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


async def _validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": _json_safe(exc.errors())})


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    yield
    reset_shared_state()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Alethic Kernel API",
        description="Domain-agnostic AI governance kernel",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_exception_handler(RequestValidationError, _validation_error_handler)  # type: ignore[arg-type]
    app.include_router(router)
    return app
