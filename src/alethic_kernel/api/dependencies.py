"""Kernel lifecycle management for the API layer."""
from __future__ import annotations

import os
import threading

from ..kernel import Kernel
from ..store import MemoryStore
from ..sqlite_store import SqliteStore
from ..store_protocol import StoreProtocol


def _get_store_type() -> str:
    return os.environ.get("ALETHIC_STORE", "memory")


def _create_store() -> StoreProtocol:
    store_type = _get_store_type()
    if store_type == "sqlite":
        db_path = os.environ.get("ALETHIC_DB_PATH", "blackboard.db")
        return SqliteStore(db_path)
    return MemoryStore()


# Shared state — both modes use a shared kernel for low-level endpoints.
# The difference: memory mode loses data on restart; sqlite mode persists.
_shared_store: StoreProtocol | None = None
_shared_kernel: Kernel | None = None
_init_lock = threading.Lock()


def get_shared_kernel() -> Kernel:
    """Return the shared kernel for low-level endpoints.

    In memory mode: shared MemoryStore (data lost on restart).
    In sqlite mode: shared SqliteStore (data persists across restarts).
    """
    global _shared_store, _shared_kernel
    if _shared_kernel is not None:
        return _shared_kernel
    with _init_lock:
        if _shared_kernel is None:
            _shared_store = _create_store()
            _shared_kernel = Kernel(store=_shared_store)
    return _shared_kernel


def get_ephemeral_kernel() -> Kernel:
    """Always return a fresh kernel (for /v1/episode)."""
    return Kernel()


def reset_shared_state() -> None:
    """Reset shared state (for testing)."""
    global _shared_store, _shared_kernel
    if _shared_store is not None:
        _shared_store.close()
    _shared_store = None
    _shared_kernel = None
