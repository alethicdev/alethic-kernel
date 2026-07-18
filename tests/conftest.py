from __future__ import annotations

import pytest

from alethic_kernel.kernel import Kernel
from alethic_kernel.store import MemoryStore
from alethic_kernel.sqlite_store import SqliteStore
from alethic_kernel.tools.perturb import PerturbConfig
from alethic_kernel.tools.payment_tool import PaymentTool
from alethic_kernel.tools.refund_tool import RefundTool


@pytest.fixture(params=["memory", "sqlite"])
def kernel(request, tmp_path) -> Kernel:
    """Run every governance assertion against both stores.

    The two backends must agree: which store is configured is a deployment
    choice and must never change whether a proposal is committed or refused.
    """
    if request.param == "memory":
        yield Kernel()
        return
    store = SqliteStore(str(tmp_path / "kernel.db"))
    try:
        yield Kernel(store=store)
    finally:
        store.close()


@pytest.fixture
def memory_store() -> MemoryStore:
    return MemoryStore()


@pytest.fixture
def sqlite_store(tmp_path) -> SqliteStore:
    store = SqliteStore(str(tmp_path / "test.db"))
    yield store
    store.close()


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    """Both StoreProtocol implementations, for tests that must hold on either."""
    if request.param == "memory":
        yield MemoryStore()
        return
    s = SqliteStore(str(tmp_path / "store.db"))
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def trace_id() -> str:
    return "test-trace-001"


# ── Charge fixtures ──────────────────────────────────────────────────

@pytest.fixture
def clean_charge() -> dict:
    return {
        "charge_id": "ch_clean",
        "amount": 100.00,
        "currency": "usd",
        "status": "disputed",
        "stale": False,
        "conflict": False,
        "customer_id": "cus_clean",
    }


@pytest.fixture
def stale_charge() -> dict:
    return {
        "charge_id": "ch_stale",
        "amount": 100.00,
        "currency": "usd",
        "status": "disputed",
        "stale": True,
        "conflict": False,
        "customer_id": "cus_stale",
    }


@pytest.fixture
def conflict_charge() -> dict:
    return {
        "charge_id": "ch_conflict",
        "amount": 100.00,
        "currency": "usd",
        "status": "disputed",
        "stale": False,
        "conflict": True,
        "customer_id": "cus_conflict",
    }


@pytest.fixture
def low_confidence_charge() -> dict:
    return {
        "charge_id": "ch_lowconf",
        "amount": 100.00,
        "currency": "usd",
        "status": "disputed",
        "stale": False,
        "conflict": False,
        "low_confidence": True,
        "customer_id": "cus_lowconf",
    }


# ── Tool fixtures ────────────────────────────────────────────────────

@pytest.fixture
def payment_tool() -> PaymentTool:
    return PaymentTool(PerturbConfig(
        tool_drop_rate=0.0,
        stale_rate=0.0,
        conflict_rate=0.0,
        low_confidence_rate=0.0,
    ))


@pytest.fixture
def refund_tool() -> RefundTool:
    return RefundTool()


# ── Task inputs ──────────────────────────────────────────────────────

@pytest.fixture
def clean_task_inputs() -> dict:
    return {
        "chargeId": "ch_3P0x1A2B3C",
        "customerId": "cus_9Xk2mN",
        "customerName": "Marko",
        "amount": 149.99,
        "disputeReason": "product_not_received",
    }


@pytest.fixture
def duplicate_task_inputs() -> dict:
    return {
        "chargeId": "ch_8S3a4D7H8I",
        "customerId": "cus_6Wp3sM",
        "customerName": "Alicia",
        "amount": 59.99,
        "disputeReason": "product_unacceptable",
        "is_duplicate": True,
    }


@pytest.fixture
def default_constraints() -> dict:
    return {
        "no_duplicate_refund": {"blocks_field": "is_duplicate"},
    }
