from __future__ import annotations
from dataclasses import dataclass
import random, hashlib

@dataclass
class PerturbConfig:
    tool_drop_rate: float = 0.05
    stale_rate: float = 0.10
    conflict_rate: float = 0.10
    low_confidence_rate: float = 0.10

def _rng(seed: int, key: str) -> random.Random:
    h = int(hashlib.md5(f"{seed}:{key}".encode()).hexdigest(), 16) % (2**32)
    return random.Random(h)

def maybe(seed: int, key: str, rate: float) -> bool:
    return _rng(seed, key).random() < rate
