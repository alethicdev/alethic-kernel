from __future__ import annotations
import threading
from dataclasses import dataclass, field
from typing import Any, Dict
import uuid


@dataclass
class Session:
    """Groups multiple episodes under a single persistent context."""

    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    metadata: Dict[str, Any] = field(default_factory=dict)
    _episode_counter: int = field(default=0, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def episode_trace_id(self) -> str:
        """Generate a unique trace_id for a new episode within this session."""
        with self._lock:
            self._episode_counter += 1
            counter = self._episode_counter
        short = uuid.uuid4().hex[:8]
        return f"{self.session_id}-ep{counter}-{short}"
