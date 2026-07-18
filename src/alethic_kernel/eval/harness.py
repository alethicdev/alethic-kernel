from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import uuid

from .task_loader import Task
from ..tools.perturb import PerturbConfig
from ..tools.payment_tool import PaymentTool
from ..tools.refund_tool import RefundTool
from ..agents.string_glue import StringGlueAgent
from ..agents.json_glue import JsonGlueAgent
from ..agents.alethic_agent import AlethicAgent
from ..agents.llm_agent import LLMAgent
from ..kernel import Kernel
from .metrics import compute_metrics

@dataclass
class Episode:
    task_id: str
    seed: int
    agent: str
    output: Dict[str, Any]
    metrics: Dict[str, float]

def run_suite(tasks: List[Task], seeds: List[int], agents: List[str], cfg: PerturbConfig,
              llm_kw: Optional[Dict[str, Any]] = None) -> List[Episode]:
    out: List[Episode] = []
    for t in tasks:
        for s in seeds:
            payment_tool = PaymentTool(cfg)
            refund_tool = RefundTool()
            for a in agents:
                o: Dict[str, Any]
                if a == "string_glue":
                    sg = StringGlueAgent(payment_tool, refund_tool)
                    o = sg.run(s, t.inputs)
                elif a == "json_glue":
                    jg = JsonGlueAgent(payment_tool, refund_tool)
                    o = jg.run(s, t.inputs)
                elif a == "alethic":
                    kernel = Kernel()
                    aa = AlethicAgent(kernel, payment_tool, refund_tool)
                    o = aa.run(s, t.id, t.inputs, t.constraints)
                elif a == "llm_bk":
                    kernel = Kernel()
                    la = LLMAgent(kernel, payment_tool, refund_tool, llm_kw=llm_kw or {})
                    o = la.run(s, t.id, t.inputs, t.constraints)
                else:
                    raise ValueError(a)

                m = compute_metrics(a, o, task_constraints=t.constraints, task_inputs=t.inputs)
                out.append(Episode(t.id, s, a, o, m))
    return out
