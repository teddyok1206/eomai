"""Dedicated creative analysis controls never broaden slots or change the baseline."""

from contextlib import nullcontext
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_identifiers import content_sha256
from eom_orchestrator import creative_knowledge_controls as controls
from eom_orchestrator.control_service import ControlPlaneError
from eom_workflow.control_plane import ExecutionPresetRevision

from tests.unit.test_execution_control_contracts import _preset
from tests.unit.test_external_item_learning_controls import _capacity


def policy():
    value = _preset()
    value["state"] = "RELEASED"
    value["role_policies"] = [value["role_policies"][0]]
    value["role_policies"][0].update(role="support", worker_pool_key="support")
    value["compatible_workflow_protocols"] = ["workflow-role/1.6.0"]
    value["capacity_policy_revision_id"] = _capacity().capacity_policy_revision_id
    value["content_sha256"] = content_sha256(
        {k: v for k, v in value.items() if k != "content_sha256"}
    )
    return ExecutionPresetRevision.model_validate(value)


def test_exact_released_creative_policy_replays_without_artifact_or_model(monkeypatch):
    baseline = policy()
    session = Mock()
    session.get.return_value = baseline
    session.scalar.return_value = NS(current_revision_id=baseline.preset_revision_id)
    sessions = NS(begin=lambda: nullcontext(session))
    monkeypatch.setattr(controls, "validated_preset", lambda row: row)
    monkeypatch.setattr(controls, "resolve_released_capacity_policy", lambda *args: _capacity())
    publisher = Mock()
    result = controls.release_creative_knowledge_controls(
        sessions,
        publisher,
        baseline_revision_id=baseline.preset_revision_id,
        capacity_revision_id=_capacity().capacity_policy_revision_id,
        operator_id="operator_" + "1" * 32,
        source_commit="a" * 40,
        authorize=Mock(),
    )
    assert result == baseline
    publisher.publish_bytes.assert_not_called()
    session.add.assert_not_called()


def test_two_slot_support_capacity_is_rejected_before_any_draft(monkeypatch):
    baseline = policy()
    session = Mock()
    session.get.return_value = baseline
    capacity = _capacity()
    pool = NS(pool_key="support", slot_keys=("slot05", "slot06"), max_active=2)
    monkeypatch.setattr(controls, "validated_preset", lambda row: row)
    monkeypatch.setattr(
        controls, "resolve_released_capacity_policy", lambda *args: NS(pools=(pool,))
    )
    publisher = Mock()
    with pytest.raises(ControlPlaneError, match="policy differs"):
        controls.release_creative_knowledge_controls(
            NS(begin=lambda: nullcontext(session)),
            publisher,
            baseline_revision_id=baseline.preset_revision_id,
            capacity_revision_id=capacity.capacity_policy_revision_id,
            operator_id="operator_" + "1" * 32,
            source_commit="a" * 40,
            authorize=Mock(),
        )
    publisher.publish_bytes.assert_not_called()
