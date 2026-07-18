from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List
import json

def _load_yaml_or_json(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore[import-untyped]
        result: Dict[str, Any] = yaml.safe_load(text)
        return result
    except Exception:
        result = json.loads(text)
        return result

@dataclass
class Task:
    id: str
    env: str
    description: str
    inputs: Dict[str, Any]
    expected: Dict[str, Any]
    constraints: Dict[str, Any]

def load_tasks(tasks_dir: Path) -> List[Task]:
    tasks: List[Task] = []
    for p in sorted(tasks_dir.glob("*.yaml")):
        obj = _load_yaml_or_json(p)
        tasks.append(Task(
            id=obj["id"],
            env=obj.get("env","enterprise"),
            description=obj.get("description",""),
            inputs=obj.get("inputs",{}),
            expected=obj.get("expected",{}),
            constraints=obj.get("constraints",{}),
        ))
    return tasks
