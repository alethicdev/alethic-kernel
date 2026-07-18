"""Tests for CLI subcommands."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# Exercise the source tree directly so the subprocess cannot accidentally use
# an older globally installed wheel.
_PROJECT_SRC = str(Path(__file__).resolve().parent.parent / "src")


def _run_cli(*args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    """Run a CLI command with the correct PYTHONPATH."""
    env = os.environ.copy()
    env["PYTHONPATH"] = _PROJECT_SRC + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "alethic_kernel.run", *args],
        capture_output=True, text=True, timeout=timeout, env=env,
    )


class TestCLIRun:
    def test_run_subcommand(self, tmp_path):
        out_file = str(tmp_path / "results.jsonl")
        result = _run_cli(
            "run",
            "--tasks", "stripe_refund_clean",
            "--seeds", "2",
            "--agents", "alethic",
            "--no-llm",
            "--out", out_file,
        )
        assert result.returncode == 0, result.stderr
        lines = Path(out_file).read_text().strip().splitlines()
        assert len(lines) == 2  # 1 task × 2 seeds × 1 agent
        row = json.loads(lines[0])
        assert "metrics" in row
        assert row["metrics"]["unsafe_action"] == 0.0

    def test_legacy_mode(self, tmp_path):
        """No subcommand → legacy mode still works."""
        out_file = str(tmp_path / "results.jsonl")
        result = _run_cli(
            "--tasks", "stripe_refund_clean",
            "--seeds", "1",
            "--agents", "alethic",
            "--no-llm",
            "--out", out_file,
        )
        assert result.returncode == 0, result.stderr
        lines = Path(out_file).read_text().strip().splitlines()
        assert len(lines) == 1


class TestCLIReport:
    def test_report_subcommand(self, tmp_path):
        # Create minimal results file
        results_file = tmp_path / "results.jsonl"
        row = {
            "task_id": "test_task", "seed": 0, "agent": "alethic",
            "output": {"view": {"percepts": {}, "beliefs": {}, "constraints": {},
                                "plans": {}, "evidence": {}, "predictions": {},
                                "actions": {}},
                       "final": {"status": "done"},
                       "trace_id": "t1"},
            "metrics": {"task_success": 1.0, "unsafe_action": 0.0,
                        "unsupported_belief": 0.0, "traceability": 1.0,
                        "failure_transparency": 1.0},
        }
        results_file.write_text(json.dumps(row) + "\n")

        report_file = tmp_path / "report.md"
        result = _run_cli(
            "report",
            "--input", str(results_file),
            "--out-report", str(report_file),
        )
        assert result.returncode == 0, result.stderr
        assert report_file.exists()
        content = report_file.read_text()
        assert "alethic" in content


class TestCLIMigrate:
    def test_migrate_subcommand(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        result = _run_cli("migrate", db_path)
        assert result.returncode == 0, result.stderr
        assert "migrated to schema version" in result.stdout

        # Verify database is usable
        import sqlite3
        conn = sqlite3.connect(db_path)
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='records'")
        assert cur.fetchone() is not None
        conn.close()


class TestCLIServe:
    def test_serve_help(self):
        """Verify serve subcommand is registered (don't actually start server)."""
        result = _run_cli("serve", "--help")
        assert result.returncode == 0
        assert "--host" in result.stdout
        assert "--port" in result.stdout
        assert "--store" in result.stdout
