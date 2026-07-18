"""Regression tests for the public package namespace."""

from __future__ import annotations

import importlib.util
from typing import get_args

from alethic_kernel import AlethicClient, Kernel, Slot, __version__


def test_primary_api_is_available_at_the_package_root() -> None:
    assert Kernel.__module__ == "alethic_kernel.kernel"
    assert AlethicClient.__module__ == "alethic_kernel.client"
    assert "percepts" in get_args(Slot)


def test_redundant_alethic_subpackage_is_gone() -> None:
    assert importlib.util.find_spec("alethic_kernel.alethic") is None


def test_package_reports_the_release_version() -> None:
    assert __version__ == "0.2.0"
