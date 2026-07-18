"""Tests for alethic_kernel/eval/report.py — summarize() and render_markdown()."""
from __future__ import annotations
import json
from typing import Any, Dict, List

import pytest

from alethic_kernel.eval.report import summarize, render_markdown


# ── Fixtures ────────────────────────────────────────────────────────

def _episode(agent: str, task_success: float = 1.0,
             unsafe_action: float = 0.0,
             unsupported_belief: float = 0.0,
             traceability: float = 1.0,
             failure_transparency: float = 1.0,
             **extra: Any) -> Dict[str, Any]:
    return {
        "agent": agent,
        "task_id": extra.get("task_id", "task_1"),
        "seed": extra.get("seed", 0),
        "metrics": {
            "task_success": task_success,
            "unsafe_action": unsafe_action,
            "unsupported_belief": unsupported_belief,
            "traceability": traceability,
            "failure_transparency": failure_transparency,
        },
        "output": extra.get("output", {}),
    }


# ── summarize() ─────────────────────────────────────────────────────

class TestSummarize:
    def test_single_agent_single_episode(self) -> None:
        rows = [_episode("alethic", task_success=1.0, unsafe_action=0.0)]
        s = summarize(rows)
        assert "alethic" in s
        assert s["alethic"]["task_success"] == 1.0
        assert s["alethic"]["unsafe_action"] == 0.0

    def test_single_agent_multiple_episodes(self) -> None:
        rows = [
            _episode("alethic", task_success=1.0),
            _episode("alethic", task_success=0.0),
            _episode("alethic", task_success=1.0),
        ]
        s = summarize(rows)
        assert abs(s["alethic"]["task_success"] - 2 / 3) < 1e-9

    def test_multiple_agents(self) -> None:
        rows = [
            _episode("alethic", task_success=1.0, unsafe_action=0.0),
            _episode("string_glue", task_success=0.0, unsafe_action=1.0),
        ]
        s = summarize(rows)
        assert set(s.keys()) == {"alethic", "string_glue"}
        assert s["alethic"]["task_success"] == 1.0
        assert s["string_glue"]["unsafe_action"] == 1.0

    def test_averages_across_many_episodes(self) -> None:
        rows = [_episode("a", task_success=float(i % 2)) for i in range(100)]
        s = summarize(rows)
        assert abs(s["a"]["task_success"] - 0.5) < 1e-9

    def test_preserves_all_metric_keys(self) -> None:
        rows = [_episode("x")]
        s = summarize(rows)
        assert set(s["x"].keys()) == {
            "task_success", "unsafe_action", "unsupported_belief",
            "traceability", "failure_transparency",
        }


# ── render_markdown() ───────────────────────────────────────────────

class TestRenderMarkdown:
    def test_basic_structure(self) -> None:
        rows = [_episode("alethic")]
        md = render_markdown(rows)
        assert "# alethic report" in md
        assert "## Aggregate metrics" in md
        assert "## Representative episodes" in md
        assert "| alethic |" in md

    def test_table_header_matches_metrics(self) -> None:
        rows = [_episode("alethic")]
        md = render_markdown(rows)
        assert "task_success" in md
        assert "unsafe_action" in md

    def test_multiple_agents_sorted(self) -> None:
        rows = [
            _episode("string_glue"),
            _episode("alethic"),
            _episode("json_glue"),
        ]
        md = render_markdown(rows)
        lines = md.split("\n")
        agent_rows = [l for l in lines if l.startswith("| ") and "---" not in l and "agent" not in l]
        agents = [r.split("|")[1].strip() for r in agent_rows]
        assert agents == ["alethic", "json_glue", "string_glue"]

    def test_representative_prefers_failure(self) -> None:
        rows = [
            _episode("a", task_success=1.0, unsafe_action=0.0, seed=1),
            _episode("a", task_success=0.0, unsafe_action=1.0, seed=2),
            _episode("a", task_success=1.0, unsafe_action=0.0, seed=3),
        ]
        md = render_markdown(rows)
        # The representative episode should be the one with unsafe_action=1.0
        assert '"unsafe_action": 1.0' in md or '"unsafe_action": 1' in md

    def test_representative_falls_back_to_first(self) -> None:
        """When no failure episodes exist, uses first episode for agent."""
        rows = [
            _episode("a", task_success=1.0, unsafe_action=0.0, seed=42),
        ]
        md = render_markdown(rows)
        assert "### a" in md
        assert "```json" in md

    def test_values_formatted_3_decimals(self) -> None:
        rows = [_episode("a", task_success=1.0)]
        md = render_markdown(rows)
        assert "1.000" in md

    def test_empty_rows(self) -> None:
        """Edge case: empty input should not crash."""
        # summarize requires at least one row to get keys, but render_markdown
        # guards with `if s else []`
        rows: List[Dict[str, Any]] = []
        # This will crash because summarize returns empty dict and
        # next(iter({})) would fail — but only if the guard is hit.
        # Actually, summarize({}) returns {} and `if s else []` handles it.
        md = render_markdown(rows)
        assert "# alethic report" in md

    def test_json_in_representative_is_valid(self) -> None:
        rows = [_episode("alethic", seed=7, task_id="t1")]
        md = render_markdown(rows)
        # Extract JSON block
        in_block = False
        json_lines: list[str] = []
        for line in md.split("\n"):
            if line.strip() == "```json":
                in_block = True
                continue
            if line.strip() == "```" and in_block:
                break
            if in_block:
                json_lines.append(line)
        parsed = json.loads("\n".join(json_lines))
        assert parsed["agent"] == "alethic"
        assert parsed["seed"] == 7
