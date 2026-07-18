from __future__ import annotations

import pytest

from alethic_kernel.permissions import PERMISSIONS, Role


class TestPermissions:
    def test_all_roles_present(self):
        expected_roles: list[Role] = [
            "kernel", "tool", "planner", "symbolic_validator",
            "evidence_validator", "sim_validator",
        ]
        for role in expected_roles:
            assert role in PERMISSIONS, f"Missing role: {role}"

    def test_tool_can_commit_percepts(self):
        assert "COMMIT" in PERMISSIONS["tool"]["percepts"]

    def test_tool_cannot_commit_beliefs(self):
        assert "beliefs" not in PERMISSIONS["tool"]

    def test_planner_can_propose_beliefs(self):
        assert "PROPOSE" in PERMISSIONS["planner"]["beliefs"]

    def test_planner_can_propose_plans(self):
        assert "PROPOSE" in PERMISSIONS["planner"]["plans"]

    def test_planner_can_propose_actions(self):
        assert "PROPOSE" in PERMISSIONS["planner"]["actions"]

    def test_planner_can_propose_predictions(self):
        assert "PROPOSE" in PERMISSIONS["planner"]["predictions"]

    def test_planner_cannot_commit_beliefs(self):
        assert "COMMIT" not in PERMISSIONS["planner"]["beliefs"]

    def test_kernel_can_commit_beliefs(self):
        assert "COMMIT" in PERMISSIONS["kernel"]["beliefs"]

    def test_kernel_can_commit_actions(self):
        assert "COMMIT" in PERMISSIONS["kernel"]["actions"]

    def test_kernel_can_commit_predictions(self):
        assert "COMMIT" in PERMISSIONS["kernel"]["predictions"]

    def test_symbolic_validator_can_commit_constraints(self):
        assert "COMMIT" in PERMISSIONS["symbolic_validator"]["constraints"]

    def test_evidence_validator_can_commit_evidence(self):
        assert "COMMIT" in PERMISSIONS["evidence_validator"]["evidence"]

    def test_sim_validator_can_commit_evidence_and_predictions(self):
        assert "COMMIT" in PERMISSIONS["sim_validator"]["evidence"]
        assert "COMMIT" in PERMISSIONS["sim_validator"]["predictions"]

    def test_invalid_role_slot_combo_not_in_permissions(self):
        assert "percepts" not in PERMISSIONS["kernel"]
        assert "constraints" not in PERMISSIONS["planner"]
        assert "actions" not in PERMISSIONS["tool"]
