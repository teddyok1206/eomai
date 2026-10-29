"""New source-visual controls retain the baseline and its one-slot boundary."""

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_orchestrator import creative_source_controls as controls
from eom_orchestrator.control_models import ExecutionPresetRecord
from eom_orchestrator.control_service import ControlPlaneError
from eom_workflow.control_plane import ExecutionPresetRevision

from tests.unit.test_external_item_learning_controls import _capacity, _publication
from tests.unit.test_external_item_learning_execution_resolver import _published_preset


def fixture(monkeypatch):
    _, row = _published_preset()
    baseline = ExecutionPresetRevision.model_validate(row.canonical_document)
    baseline = baseline.model_copy(
        update={"capacity_policy_revision_id": _capacity().capacity_policy_revision_id}
    )
    instruction = baseline.role_policies[0].instruction_bundle.model_copy(
        update={
            "bundle_id": "instrbundle_" + "a" * 32,
            "bundle_revision_id": "instrrev_" + "b" * 32,
        }
    )
    policies = (baseline.role_policies[0].model_copy(update={"instruction_bundle": instruction}),)
    released = baseline.model_copy(
        update={
            "preset_id": "execpreset_" + "c" * 32,
            "preset_revision_id": "execpresetrev_" + "d" * 32,
            "role_policies": policies,
            "compatible_workflow_protocols": ("workflow-role/1.34.0",),
        }
    )
    logical = NS(state="ACTIVE", preset_key="external-item-learning")
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=None)
    session.get.side_effect = lambda model, key: (
        logical
        if model is ExecutionPresetRecord
        else baseline
        if key == baseline.preset_revision_id
        else released
    )
    session.scalar.return_value = NS(
        state="ACTIVE",
        current_revision_id=released.preset_revision_id,
        preset_id=released.preset_id,
    )
    sessions = Mock(return_value=session)
    sessions.begin.side_effect = lambda: nullcontext(session)
    monkeypatch.setattr(controls, "validated_preset", lambda row: row)
    monkeypatch.setattr(controls, "resolve_released_capacity_policy", lambda *args: _capacity())
    protocol = Mock()
    monkeypatch.setattr(controls, "ensure_protocol_version", protocol)
    bundle = Mock(return_value=instruction)
    monkeypatch.setattr(controls, "_instruction", bundle)
    publisher, authorize = Mock(), Mock()
    args = dict(
        baseline_revision_id=baseline.preset_revision_id,
        capacity_revision_id=baseline.capacity_policy_revision_id,
        platform_payload=b"synthetic platform",
        role_payload=b"synthetic source role",
        operator_id="operator_" + "1" * 32,
        source_commit="a" * 40,
        authorize=authorize,
    )
    return NS(**locals())


def test_released_purpose_replays_without_modifying_the_original_or_running_a_model(monkeypatch):
    value = fixture(monkeypatch)
    actual = controls.release_creative_source_controls(
        value.sessions, value.publisher, **value.args
    )
    assert actual == value.released
    assert value.baseline.compatible_workflow_protocols == ("workflow-role/1.33.0",)
    assert (
        actual.role_policies[0].model_candidates == value.baseline.role_policies[0].model_candidates
    )
    assert actual.role_policies[0].instruction_bundle == value.instruction
    assert actual.capacity_policy_revision_id == value.baseline.capacity_policy_revision_id
    assert value.protocol.call_args.args[1] == "workflow-role/1.34.0"
    assert value.protocol.call_args.args[2] == controls.role_schema_bundle_hash(
        "workflow-role/1.34.0"
    )
    value.publisher.publish_bytes.assert_not_called()


def test_registered_protocol_hash_conflict_does_not_release_a_preset(monkeypatch):
    value = fixture(monkeypatch)
    value.protocol.side_effect = RuntimeError("protocol schema hash mismatch")
    create = Mock()
    monkeypatch.setattr(controls, "create_execution_preset_draft", create)
    with pytest.raises(RuntimeError, match="hash mismatch"):
        controls.release_creative_source_controls(value.sessions, value.publisher, **value.args)
    create.assert_not_called()
    value.publisher.publish_bytes.assert_not_called()


@pytest.mark.parametrize("change", ["purpose", "network", "sandbox", "capacity"])
def test_baseline_boundary_drift_is_rejected_before_any_instruction_publication(
    monkeypatch, change
):
    value = fixture(monkeypatch)
    if change == "purpose":
        value.logical.preset_key = "unrelated"
    elif change == "capacity":
        monkeypatch.setattr(
            controls,
            "resolve_released_capacity_policy",
            lambda *args: NS(
                pools=(NS(pool_key="support", slot_keys=("slot05", "slot06"), max_active=2),)
            ),
        )
    else:
        policy = value.baseline.role_policies[0].model_copy(
            update={change: "enabled" if change == "network" else "danger-full-access"}
        )
        value.baseline = value.baseline.model_copy(update={"role_policies": (policy,)})
        value.session.get.side_effect = lambda model, key: (
            value.logical if model is ExecutionPresetRecord else value.baseline
        )
    with pytest.raises(ControlPlaneError, match="baseline differs"):
        controls.release_creative_source_controls(value.sessions, value.publisher, **value.args)
    value.bundle.assert_not_called()
    value.publisher.publish_bytes.assert_not_called()


def test_new_purpose_releases_only_the_exact_role_family_with_non_live_evidence(monkeypatch):
    value = fixture(monkeypatch)
    value.session.scalar.return_value = None
    create = Mock(return_value=value.released.model_copy(update={"state": "DRAFT"}))
    record = Mock()
    release = Mock(return_value=value.released)
    monkeypatch.setattr(controls, "create_execution_preset_draft", create)
    monkeypatch.setattr(controls, "record_execution_preset_evaluation", record)
    monkeypatch.setattr(controls, "release_execution_preset", release)
    value.publisher.publish_bytes.return_value = NS(pointer=object())
    actual = controls.release_creative_source_controls(
        value.sessions, value.publisher, **value.args
    )
    assert actual == value.released
    assert create.call_args.kwargs["preset_key"] == "creative-source-learning"
    assert create.call_args.kwargs["compatible_workflow_protocols"] == ["workflow-role/1.34.0"]
    assert record.call_args.kwargs["document"]["scope"] == "NON_LIVE"
    assert record.call_args.kwargs["document"]["quality_score_permille"] is None


def test_source_bundle_has_its_own_identity_and_cannot_rewrite_the_released_one(monkeypatch):
    from eom_orchestrator import external_item_learning_controls as bundle_owner

    value = _publication(monkeypatch)
    old = bundle_owner.publish_external_item_learning_instruction_bundle(
        value.sessions, value.publisher, **value.args
    )
    new = bundle_owner.publish_external_item_learning_instruction_bundle(
        value.sessions,
        value.publisher,
        **value.args,
        bundle_key=bundle_owner.CREATIVE_SOURCE_INSTRUCTION_BUNDLE_KEY,
    )
    assert old.bundle_id != new.bundle_id
    assert old.bundle_revision_id != new.bundle_revision_id
    assert value.record.call_args.kwargs["bundle_key"] == "creative-source-learning-instructions"
    with pytest.raises(ValueError):
        bundle_owner.publish_external_item_learning_instruction_bundle(
            value.sessions, value.publisher, **value.args, bundle_key="arbitrary-control"
        )


def test_source_role_teaches_regions_unprinted_score_and_separate_independent_report():
    root = Path(__file__).resolve().parents[2] / "config/control-plane"
    old, new = (
        root / "external-item-learning-v1/instructions",
        root / "creative-source-learning-v1/instructions",
    )
    assert (old / "platform.md").read_bytes() == (new / "platform.md").read_bytes()
    role = (new / "external-item-learning.md").read_text()
    for term in (
        "external-item-learning-result@2.0",
        "source_image",
        "target_region_id",
        "UNPRINTED",
        "solution_report",
        "EVEN IF WRONG",
        "not private",
        "REFERENCE_ORIGINAL",
        "NEEDS_DECISION",
    ):
        assert term in role
    assert "external-item-learning-result@1.0" in (old / "external-item-learning.md").read_text()
