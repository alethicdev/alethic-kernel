from __future__ import annotations
import argparse, json, sys
from typing import Any
from pathlib import Path

from .eval.task_loader import load_tasks
from .eval.harness import run_suite
from .tools.perturb import PerturbConfig
from .eval.report import render_markdown


def _cmd_run(args: argparse.Namespace) -> None:
    """Run the benchmark suite."""
    root = Path(__file__).resolve().parent
    tasks = load_tasks(root / "tasks")
    if args.tasks != "all":
        wanted = set(x.strip() for x in args.tasks.split(",") if x.strip())
        tasks = [t for t in tasks if t.id in wanted]

    cfg = PerturbConfig(
        tool_drop_rate=args.tool_drop,
        stale_rate=args.stale,
        conflict_rate=args.conflict,
        low_confidence_rate=args.low_confidence,
    )
    seeds = list(range(args.seeds))
    llm_kw: dict[str, Any] = {"base_url": args.llm_url, "model": args.llm_model}
    if args.llm_api_key is not None:
        llm_kw["api_key"] = args.llm_api_key
    if args.reasoning_effort is not None:
        llm_kw["reasoning_effort"] = args.reasoning_effort
    if args.agents:
        agents = [a.strip() for a in args.agents.split(",")]
    else:
        agents = ["string_glue", "json_glue", "alethic"]
        if not args.no_llm:
            agents.append("llm_bk")
    eps = run_suite(tasks, seeds, agents, cfg, llm_kw=llm_kw)

    out_path = Path(args.out)
    with open(out_path, "w", encoding="utf-8") as f:
        for e in eps:
            row = {"task_id": e.task_id, "seed": e.seed, "agent": e.agent, "output": e.output, "metrics": e.metrics}
            f.write(json.dumps(row) + "\n")
    print(f"Wrote results: {out_path} ({len(eps)} episodes)")


def _cmd_serve(args: argparse.Namespace) -> None:
    """Start the API server."""
    try:
        import uvicorn
    except ImportError:
        print("uvicorn not installed. Run: pip install 'alethic-kernel[api]'", file=sys.stderr)
        sys.exit(1)
    import os
    os.environ.setdefault("ALETHIC_STORE", args.store)
    if args.db_path:
        os.environ["ALETHIC_DB_PATH"] = args.db_path
    uvicorn.run(
        "alethic_kernel.api.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


def _cmd_migrate(args: argparse.Namespace) -> None:
    """Run schema migrations on a SQLite database."""
    import sqlite3
    from .migrations import migrate

    db_path = args.db_path
    conn = sqlite3.connect(db_path)
    final = migrate(conn)
    conn.close()
    print(f"Database {db_path} migrated to schema version {final}")


def _cmd_report(args: argparse.Namespace) -> None:
    """Generate a markdown report from results."""
    rows = [
        json.loads(line)
        for line in Path(args.input).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    Path(args.out_report).write_text(render_markdown(rows), encoding="utf-8")
    print(f"Wrote report: {args.out_report}")


def _add_run_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--tasks", default="all")
    p.add_argument("--seeds", type=int, default=50)
    p.add_argument("--out", default="results.jsonl")
    p.add_argument("--tool-drop", type=float, default=0.05)
    p.add_argument("--stale", type=float, default=0.10)
    p.add_argument("--conflict", type=float, default=0.10)
    p.add_argument("--low-confidence", type=float, default=0.10)
    p.add_argument("--llm-url", default="http://localhost:11434/v1/chat/completions",
                   help="OpenAI-compatible chat completions endpoint for LLM agent")
    p.add_argument("--llm-model", default="qwen3:8b")
    p.add_argument("--llm-api-key", default=None,
                   help="Bearer token for authenticated LLM endpoints")
    p.add_argument("--reasoning-effort", default=None,
                   choices=["low", "medium", "high"],
                   help="Reasoning effort level (passed to LLM endpoint)")
    p.add_argument("--no-llm", action="store_true", help="Exclude LLM agent from run")
    p.add_argument("--agents", default=None, help="Comma-separated agent list (overrides defaults)")


_SUBCOMMANDS = {"run", "serve", "migrate", "report"}


def main() -> None:
    # Backward compatibility: if the first arg is not a known subcommand,
    # fall back to legacy single-command parsing.
    if len(sys.argv) < 2 or sys.argv[1] not in _SUBCOMMANDS:
        legacy = argparse.ArgumentParser()
        _add_run_args(legacy)
        legacy.add_argument("--build-report", action="store_true")
        legacy.add_argument("--input", default="results.jsonl")
        legacy.add_argument("--out-report", default="report.md")
        args = legacy.parse_args()
        if getattr(args, "build_report", False):
            _cmd_report(args)
        else:
            _cmd_run(args)
        return

    p = argparse.ArgumentParser(
        prog="alethic",
        description="Alethic Kernel — benchmark, API, and management CLI",
    )
    sub = p.add_subparsers(dest="command")

    # ── run ──────────────────────────────────────────────────────────
    run_p = sub.add_parser("run", help="Run the benchmark suite")
    _add_run_args(run_p)

    # ── serve ────────────────────────────────────────────────────────
    serve_p = sub.add_parser("serve", help="Start the API server")
    serve_p.add_argument("--host", default="0.0.0.0")
    serve_p.add_argument("--port", type=int, default=8000)
    serve_p.add_argument("--store", choices=["memory", "sqlite"], default="memory",
                         help="Store backend (memory or sqlite)")
    serve_p.add_argument("--db-path", default=None,
                         help="SQLite database path (only used with --store sqlite)")
    serve_p.add_argument("--reload", action="store_true",
                         help="Enable auto-reload for development")

    # ── migrate ──────────────────────────────────────────────────────
    migrate_p = sub.add_parser("migrate", help="Run schema migrations on a SQLite database")
    migrate_p.add_argument("db_path", help="Path to the SQLite database file")

    # ── report ───────────────────────────────────────────────────────
    report_p = sub.add_parser("report", help="Generate markdown report from results")
    report_p.add_argument("--input", default="results.jsonl",
                          help="Path to JSONL results file")
    report_p.add_argument("--out-report", default="report.md",
                          help="Output markdown file path")

    args = p.parse_args()
    dispatch = {
        "run": _cmd_run,
        "serve": _cmd_serve,
        "migrate": _cmd_migrate,
        "report": _cmd_report,
    }
    dispatch[args.command](args)

if __name__ == "__main__":
    main()
