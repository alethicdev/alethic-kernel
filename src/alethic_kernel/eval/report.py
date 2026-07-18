from __future__ import annotations
from typing import Any, Dict, List
import statistics, json

def summarize(rows: List[Dict[str,Any]]) -> Dict[str,Dict[str,float]]:
    by: Dict[str,List[Dict[str,float]]] = {}
    for r in rows:
        by.setdefault(r["agent"], []).append(r["metrics"])
    out: Dict[str,Dict[str,float]] = {}
    for agent, mets in by.items():
        keys = mets[0].keys()
        out[agent] = {k: float(statistics.mean([m[k] for m in mets])) for k in keys}
    return out

def render_markdown(rows: List[Dict[str,Any]]) -> str:
    s = summarize(rows)
    agents = sorted(s.keys())
    keys = list(next(iter(s.values())).keys()) if s else []
    lines: List[str] = []
    lines.append("# alethic report")
    lines.append("")
    lines.append("## Aggregate metrics (mean across episodes)")
    lines.append("")
    lines.append("| agent | " + " | ".join(keys) + " |")
    lines.append("|---|" + "|".join(["---"]*len(keys)) + "|")
    for a in agents:
        lines.append("| " + a + " | " + " | ".join(f"{s[a][k]:.3f}" for k in keys) + " |")
    lines.append("")
    lines.append("## Representative episodes")
    lines.append("")
    for a in agents:
        ex = next((r for r in rows if r["agent"] == a and (r["metrics"]["unsafe_action"] > 0 or r["metrics"]["unsupported_belief"] > 0)), None)
        if ex is None:
            ex = next((r for r in rows if r["agent"] == a), None)
        if ex:
            lines.append(f"### {a}")
            lines.append("```json")
            lines.append(json.dumps(ex, indent=2))
            lines.append("```")
            lines.append("")
    return "\n".join(lines)
