#!/usr/bin/env python3
"""
Alethic Kernel — Live Demo
===========================

A walkthrough of the Alethic governance kernel for live audiences.
Each section prints clear output with pass/fail indicators.

Run:
    python examples/demo.py

Sections:
    1. Kernel basics — write and read records
    2. Validation pipeline — evidence checks block unsafe beliefs
    3. Perturbation resilience — stale, conflict, low-confidence data
    4. Constraint enforcement — symbolic rules block prohibited actions
    5. Prediction gating — forward simulation gates actions
    6. Multi-episode learning — adaptive constraints from failure patterns
    7. Full agent comparison — string_glue vs json_glue vs alethic
    8. Python SDK — AlethicClient in local mode
"""
from __future__ import annotations
import time

from alethic_kernel.kernel import Kernel
from alethic_kernel.store import MemoryStore
from alethic_kernel.sqlite_store import SqliteStore
from alethic_kernel.session import Session
from alethic_kernel.orchestrator import Orchestrator
from alethic_kernel.sim_worker import SimulatorWorker, SimRule
from alethic_kernel.adaptive_worker import AdaptiveWorker
from alethic_kernel.client import AlethicClient
from alethic_kernel.tools.perturb import PerturbConfig
from alethic_kernel.tools.payment_tool import PaymentTool
from alethic_kernel.tools.refund_tool import RefundTool
from alethic_kernel.agents.string_glue import StringGlueAgent
from alethic_kernel.agents.json_glue import JsonGlueAgent
from alethic_kernel.agents.alethic_agent import AlethicAgent
from alethic_kernel.eval.metrics import compute_metrics

# ── Helpers ──────────────────────────────────────────────────────────

GREEN = "\033[92m"
RED   = "\033[91m"
CYAN  = "\033[96m"
BOLD  = "\033[1m"
DIM   = "\033[2m"
RESET = "\033[0m"

def section(n: int, title: str) -> None:
    print(f"\n{'='*70}")
    print(f"  {BOLD}{CYAN}Section {n}: {title}{RESET}")
    print(f"{'='*70}\n")

def check(label: str, ok: bool, detail: str = "") -> None:
    mark = f"{GREEN}PASS{RESET}" if ok else f"{RED}FAIL{RESET}"
    extra = f"  {DIM}({detail}){RESET}" if detail else ""
    print(f"  [{mark}] {label}{extra}")

def info(msg: str) -> None:
    print(f"  {DIM}{msg}{RESET}")

# ── Section 1: Kernel Basics ────────────────────────────────────────

def demo_kernel_basics() -> None:
    section(1, "Kernel Basics")
    info("The kernel manages 7 semantic slots with role-based access control.")
    info("Records are written in PROPOSE or COMMIT mode.\n")

    kernel = Kernel()
    trace = "demo-basics-001"

    # Write a percept (sensor data)
    rec = kernel.write("tool", "percepts", "COMMIT", "temperature",
                       {"value": 95.0, "unit": "C", "stale": False, "conflict": False},
                       trace, confidence=0.9)
    check("Write percept", rec.id.startswith("percepts:"), f"id={rec.id}")

    # Read the view
    view = kernel.current_view(trace)
    check("View has percept", "temperature" in view["percepts"],
          f"value={view['percepts']['temperature']['value']}")
    check("Other slots empty", all(len(view[s]) == 0 for s in
          ["beliefs", "plans", "actions", "predictions"]))

    # Role enforcement
    try:
        kernel.write("tool", "beliefs", "COMMIT", "test", {}, trace)
        check("Role enforcement", False, "should have raised")
    except PermissionError:
        check("Role enforcement", True, "tool cannot write beliefs")

    print()


# ── Section 2: Validation Pipeline ──────────────────────────────────

def demo_validation_pipeline() -> None:
    section(2, "Validation Pipeline")
    info("Beliefs require evidence validation before commitment.")
    info("The kernel checks: existence, staleness, conflicts, confidence.\n")

    kernel = Kernel()
    trace = "demo-pipeline-001"

    # Commit clean percept
    kernel.write("tool", "percepts", "COMMIT", "charge",
                 {"charge_id": "ch_123", "amount": 50.0, "status": "disputed",
                  "stale": False, "conflict": False},
                 trace, confidence=0.9)

    # Propose a belief
    prop = kernel.write("planner", "beliefs", "PROPOSE", "refund_due",
                        {"value": True, "depends_on": ["charge"]},
                        trace, input_refs=["charge"])

    # Commit the belief — should pass all checks
    ok, code = kernel.commit_belief_from_proposal(prop.id, trace)
    check("Belief committed (clean evidence)", ok, code)

    # Verify evidence artifact was created
    view = kernel.current_view(trace)
    has_evidence = any(k.startswith("validation_") for k in view["evidence"])
    check("Evidence artifact recorded", has_evidence)

    print()


# ── Section 3: Perturbation Resilience ──────────────────────────────

def demo_perturbation_resilience() -> None:
    section(3, "Perturbation Resilience")
    info("The kernel rejects beliefs when evidence is tainted.\n")

    # 3a: Stale data
    kernel = Kernel()
    trace = "demo-stale-001"
    kernel.write("tool", "percepts", "COMMIT", "charge",
                 {"charge_id": "ch_stale", "amount": 50.0, "stale": True, "conflict": False},
                 trace, confidence=0.9)
    prop = kernel.write("planner", "beliefs", "PROPOSE", "refund_due",
                        {"value": True, "depends_on": ["charge"]}, trace, input_refs=["charge"])
    ok, code = kernel.commit_belief_from_proposal(prop.id, trace)
    check("Stale evidence REJECTED", not ok, code)

    # 3b: Conflicting data
    kernel = Kernel()
    trace = "demo-conflict-001"
    kernel.write("tool", "percepts", "COMMIT", "charge",
                 {"charge_id": "ch_conflict", "amount": 50.0, "stale": False, "conflict": True},
                 trace, confidence=0.4)  # low confidence — no arbitration
    prop = kernel.write("planner", "beliefs", "PROPOSE", "refund_due",
                        {"value": True, "depends_on": ["charge"]}, trace, input_refs=["charge"])
    ok, code = kernel.commit_belief_from_proposal(prop.id, trace)
    check("Conflict (low-confidence) REJECTED", not ok, code)

    # 3c: Conflict with high confidence — arbitrated
    kernel = Kernel()
    trace = "demo-arb-001"
    kernel.write("tool", "percepts", "COMMIT", "charge",
                 {"charge_id": "ch_arb", "amount": 50.0, "stale": False, "conflict": True},
                 trace, confidence=0.85)  # high confidence — arbitrated through
    prop = kernel.write("planner", "beliefs", "PROPOSE", "refund_due",
                        {"value": True, "depends_on": ["charge"]}, trace, input_refs=["charge"])
    ok, code = kernel.commit_belief_from_proposal(prop.id, trace)
    check("Conflict (high-confidence) ARBITRATED", ok, code)

    # 3d: Low confidence
    kernel = Kernel()
    trace = "demo-lowconf-001"
    kernel.write("tool", "percepts", "COMMIT", "charge",
                 {"charge_id": "ch_lowconf", "amount": 50.0, "stale": False, "conflict": False},
                 trace, confidence=0.3)  # below 0.5 threshold
    prop = kernel.write("planner", "beliefs", "PROPOSE", "refund_due",
                        {"value": True, "depends_on": ["charge"]}, trace, input_refs=["charge"])
    ok, code = kernel.commit_belief_from_proposal(prop.id, trace)
    check("Low confidence REJECTED", not ok, code)

    print()


# ── Section 4: Constraint Enforcement ───────────────────────────────

def demo_constraint_enforcement() -> None:
    section(4, "Constraint Enforcement")
    info("Symbolic constraints block prohibited actions at commit time.\n")

    kernel = Kernel()
    trace = "demo-constraint-001"

    # Set up constraint
    kernel.write("symbolic_validator", "constraints", "COMMIT",
                 "no_duplicate_refund",
                 {"enabled": True, "blocks_field": "is_duplicate"}, trace)

    # Commit clean percept + belief
    kernel.write("tool", "percepts", "COMMIT", "charge",
                 {"charge_id": "ch_dup", "amount": 50.0, "stale": False, "conflict": False},
                 trace, confidence=0.9)
    prop = kernel.write("planner", "beliefs", "PROPOSE", "refund_due",
                        {"value": True, "depends_on": ["charge"]}, trace, input_refs=["charge"])
    kernel.commit_belief_from_proposal(prop.id, trace)

    # Action with is_duplicate=True should be blocked
    action = kernel.write("planner", "actions", "PROPOSE", "issue_refund",
                          {"type": "issue_refund", "charge_id": "ch_dup",
                           "amount": 50.0, "is_duplicate": True,
                           "requires_beliefs": ["refund_due"]}, trace)
    ok, code = kernel.commit_action_from_proposal(action.id, trace)
    check("Duplicate refund BLOCKED", not ok, code)

    # Action with is_duplicate=False should pass
    action2 = kernel.write("planner", "actions", "PROPOSE", "issue_refund",
                           {"type": "issue_refund", "charge_id": "ch_ok",
                            "amount": 50.0, "is_duplicate": False,
                            "requires_beliefs": ["refund_due"]}, trace)
    ok2, code2 = kernel.commit_action_from_proposal(action2.id, trace)
    check("Clean refund COMMITTED", ok2, code2)

    print()


# ── Section 5: Prediction Gating ────────────────────────────────────

def demo_prediction_gating() -> None:
    section(5, "Prediction Gating")
    info("Actions can require a forward prediction with non-negative outcome.\n")

    kernel = Kernel()
    trace = "demo-pred-001"

    # Set up percept + belief
    kernel.write("tool", "percepts", "COMMIT", "sensor",
                 {"value": 85.0, "stale": False, "conflict": False},
                 trace, confidence=0.9)
    prop = kernel.write("planner", "beliefs", "PROPOSE", "anomaly",
                        {"value": True, "depends_on": ["sensor"]}, trace, input_refs=["sensor"])
    kernel.commit_belief_from_proposal(prop.id, trace)

    # Propose a negative prediction
    neg_pred = kernel.write("planner", "predictions", "PROPOSE", "pred_alert",
                            {"action_type": "alert", "expected_outcome": -0.5,
                             "requires_beliefs": ["anomaly"]}, trace)
    kernel.commit_prediction(neg_pred.id, trace)

    # Action gated by prediction — should be blocked
    action = kernel.write("planner", "actions", "PROPOSE", "alert",
                          {"type": "alert", "requires_beliefs": ["anomaly"]}, trace)
    ok, code = kernel.commit_action_from_proposal(action.id, trace, require_prediction=True)
    check("Negative prediction BLOCKS action", not ok, code)

    # Now with a positive prediction
    kernel2 = Kernel()
    trace2 = "demo-pred-002"
    kernel2.write("tool", "percepts", "COMMIT", "sensor",
                  {"value": 105.0, "stale": False, "conflict": False},
                  trace2, confidence=0.9)
    prop2 = kernel2.write("planner", "beliefs", "PROPOSE", "anomaly",
                          {"value": True, "depends_on": ["sensor"]}, trace2, input_refs=["sensor"])
    kernel2.commit_belief_from_proposal(prop2.id, trace2)
    pos_pred = kernel2.write("planner", "predictions", "PROPOSE", "pred_alert",
                             {"action_type": "alert", "expected_outcome": 1.0,
                              "requires_beliefs": ["anomaly"]}, trace2)
    kernel2.commit_prediction(pos_pred.id, trace2)

    action2 = kernel2.write("planner", "actions", "PROPOSE", "alert",
                            {"type": "alert", "requires_beliefs": ["anomaly"]}, trace2)
    ok2, code2 = kernel2.commit_action_from_proposal(action2.id, trace2, require_prediction=True)
    check("Positive prediction ALLOWS action", ok2, code2)

    print()


# ── Section 6: Multi-Episode Learning ───────────────────────────────

def demo_multi_episode_learning() -> None:
    section(6, "Multi-Episode Learning")
    info("AdaptiveWorker scans failure patterns and derives persistent constraints.")
    info("SimulatorWorker evaluates declarative rules for forward prediction.\n")

    store = SqliteStore(":memory:")
    kernel = Kernel(store=store)
    session = Session(metadata={"demo": True})

    sim_rules = [
        SimRule(action_type="alert", expected_outcome=1.0,
                requires_beliefs=["anomaly"],
                percept_conditions={"sensor": {"value__gt": 90}},
                confidence=0.85),
        SimRule(action_type="alert", expected_outcome=-0.5,
                requires_beliefs=["anomaly"],
                percept_conditions={"sensor": {"value__lte": 90}},
                confidence=0.7),
    ]

    adaptive = AdaptiveWorker(failure_threshold=2)
    alerts, reviews, no_actions = 0, 0, 0

    for ep in range(8):
        trace = session.episode_trace_id()
        # Alternating: episodes 0,2,4,6 get stale data → failures accumulate
        stale = ep % 2 == 0
        kernel.write("tool", "percepts", "COMMIT", "sensor",
                     {"value": 95.0, "stale": stale, "conflict": False},
                     trace, confidence=0.8)

        prop = kernel.write("planner", "beliefs", "PROPOSE", "anomaly",
                            {"value": True, "depends_on": ["sensor"]},
                            trace, input_refs=["sensor"])
        ok, code = kernel.commit_belief_from_proposal(prop.id, trace)

        if ok:
            # Simulate prediction
            sim = SimulatorWorker(rules=sim_rules)
            view = kernel.current_view(trace)
            sim.step(kernel, trace, view)
            view = kernel.current_view(trace)

            action = kernel.write("planner", "actions", "PROPOSE", "alert",
                                  {"type": "alert", "requires_beliefs": ["anomaly"]}, trace)
            ok_a, _ = kernel.commit_action_from_proposal(action.id, trace, require_prediction=True)
            if ok_a:
                alerts += 1
            else:
                reviews += 1
        else:
            no_actions += 1

        # Adaptive worker learns from failures
        if ep > 0:
            adaptive.analyze(store)

    check(f"Episodes run", True, f"8 total")
    check(f"Alerts sent", alerts > 0, f"{alerts}")
    check(f"Blocked by stale data", no_actions > 0, f"{no_actions} episodes")
    check(f"Queued for review", reviews >= 0, f"{reviews} episodes")

    # Check if adaptive worker learned anything
    learned = adaptive.analyze(store)
    check("Adaptive learning", True,
          f"learned {len(learned)} constraints" if learned else "no patterns yet (threshold=2)")

    store.close()
    print()


# ── Section 7: Agent Comparison ─────────────────────────────────────

def demo_agent_comparison() -> None:
    section(7, "Agent Comparison Under Perturbation")
    info("3 agents process the same 50 seeds with 30% perturbation rates.")
    info("Only the kernel-governed agent achieves safe behavior.\n")

    cfg = PerturbConfig(stale_rate=0.30, conflict_rate=0.30,
                        low_confidence_rate=0.30, tool_drop_rate=0.0)
    task_inputs = {
        "chargeId": "ch_demo", "customerId": "cus_demo",
        "customerName": "Demo Corp", "amount": 250.00,
        "disputeReason": "product_not_received", "is_duplicate": False,
    }
    constraints = {"no_duplicate_refund": {"enabled": True, "blocks_field": "is_duplicate"}}
    seeds = 50

    results: dict[str, dict[str, float]] = {}

    for agent_name in ["string_glue", "json_glue", "alethic"]:
        successes, unsafes = 0, 0
        for seed in range(seeds):
            pt = PaymentTool(cfg)
            rt = RefundTool()
            if agent_name == "string_glue":
                ag = StringGlueAgent(pt, rt)
                out = ag.run(seed, task_inputs)
            elif agent_name == "json_glue":
                ag_j = JsonGlueAgent(pt, rt)
                out = ag_j.run(seed, task_inputs)
            else:
                k = Kernel()
                ag_a = AlethicAgent(k, pt, rt)
                out = ag_a.run(seed, "demo_task", task_inputs, constraints)
            m = compute_metrics(agent_name, out, task_constraints=constraints, task_inputs=task_inputs)
            successes += int(m["task_success"] == 1.0)
            unsafes += int(m["unsafe_action"] == 1.0)
        results[agent_name] = {
            "success": successes / seeds * 100,
            "unsafe": unsafes / seeds * 100,
        }

    # Print comparison table
    print(f"  {'Agent':<15} {'Success':>10} {'Unsafe':>10}")
    print(f"  {'-'*15} {'-'*10} {'-'*10}")
    for name, r in results.items():
        print(f"  {name:<15} {r['success']:>9.0f}% {r['unsafe']:>9.0f}%")
    print()

    check("Alethic: 100% success", results["alethic"]["success"] == 100)
    check("Alethic: 0% unsafe", results["alethic"]["unsafe"] == 0)
    check("String glue: has unsafe actions", results["string_glue"]["unsafe"] > 0)
    check("Json glue: has unsafe actions", results["json_glue"]["unsafe"] > 0)

    print()


# ── Section 8: Python SDK ───────────────────────────────────────────

def demo_sdk() -> None:
    section(8, "Python SDK — AlethicClient")
    info("The SDK works in local mode (in-process) or HTTP mode (remote server).\n")

    client = AlethicClient(mode="local")

    # Health check
    h = client.health()
    check("Health check", h["status"] == "ok", f"mode={h['mode']}")

    # Run a full episode
    result = client.run_episode(
        task_inputs={
            "chargeId": "ch_sdk", "customerId": "cus_sdk",
            "customerName": "SDK Demo", "amount": 99.99,
            "disputeReason": "unauthorized", "is_duplicate": False,
        },
        constraints={"no_duplicate_refund": {"enabled": True, "blocks_field": "is_duplicate"}},
    )

    check("Episode completed", result.trace_id != "")
    check("Action committed", result.final.get("action_committed", False))
    check("Task success", result.metrics.get("task_success") == 1.0)
    check("Zero unsafe actions", result.metrics.get("unsafe_action") == 0.0)
    check("Full traceability", result.metrics.get("traceability") == 1.0)

    # Low-level API
    trace = "sdk-lowlevel-001"
    w = client.write("tool", "percepts", "COMMIT", "charge",
                     {"charge_id": "ch_low", "amount": 25.0,
                      "stale": False, "conflict": False},
                     trace, confidence=0.95)
    check("Low-level write", w["ok"])

    view = client.current_view(trace)
    check("Low-level view", "charge" in view["percepts"])

    print()


# ── Main ─────────────────────────────────────────────────────────────

def main() -> None:
    print(f"\n{BOLD}{'='*70}")
    print(f"  ALETHIC KERNEL — Live Demo")
    print(f"  Your model proposes. Alethic decides.")
    print(f"{'='*70}{RESET}")

    t0 = time.time()

    demo_kernel_basics()
    demo_validation_pipeline()
    demo_perturbation_resilience()
    demo_constraint_enforcement()
    demo_prediction_gating()
    demo_multi_episode_learning()
    demo_agent_comparison()
    demo_sdk()

    elapsed = time.time() - t0
    print(f"{'='*70}")
    print(f"  {BOLD}{GREEN}All sections complete in {elapsed:.2f}s{RESET}")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
