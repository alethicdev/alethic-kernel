from __future__ import annotations
from typing import ContextManager, List, Optional, Protocol, runtime_checkable

from .schema import Record, Slot


@runtime_checkable
class StoreProtocol(Protocol):
    """Minimal interface that any backing store must satisfy."""

    def append(self, rec: Record) -> None:
        """Add a record. Raises RecordIdConflict if the id is already taken."""
        ...

    def get(self, rec_id: str) -> Optional[Record]: ...
    def list_slot(self, slot: Slot) -> List[Record]: ...
    def find_active_by_kind(self, slot: Slot, kind: str, trace_id: str) -> Optional[Record]: ...
    def invalidate(self, rec_id: str, reason: str) -> None: ...
    def close(self) -> None: ...

    def transaction(self) -> ContextManager[None]:
        """Group writes so they land together or not at all.

        A commit writes an evidence artifact, invalidates the proposal, then
        writes the record. Applied piecemeal, an interruption can leave evidence
        asserting that validation passed for a record that was never written,
        beside a proposal already marked superseded by that same commit — an
        audit trail that is not merely incomplete but false, and an episode that
        cannot be retried.

        Re-entrant: only the outermost block commits or rolls back.
        """
        ...
