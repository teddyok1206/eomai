"""Control preparation uses synthetic ports, never Codex or production state."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_identifiers import content_sha256, sha256_bytes
from eom_orchestrator import external_item_learning_controls as controls
from eom_orchestrator.control_artifacts import PublishedControlArtifact
from eom_orchestrator.control_models import ExecutionBundleRecord, WorkerCapacityPolicyRecord
from eom_orchestrator.control_service import ControlPlaneError
from eom_workflow.control_plane import (
    ControlArtifactPointer,
    InstructionBundleManifest,
    ModelCandidate,
    WorkerCapacityPolicyV4,
)
from sqlalchemy.orm import Session

NOW = datetime(2026, 10, 27, 19, tzinfo=UTC)
OPERATOR = "operator_" + "1" * 32


def _capacity():
    body = {
        "schema_version": "worker-capacity-policy/1.3",
        "capacity_policy_id": "capacity_" + "1" * 32,
        "capacity_policy_revision_id": "capacityrev_" + "2" * 32,
        "revision_number": 4,
        "state": "RELEASED",
        "max_configured_slots": 6,
        "max_active_codex": 3,
        "max_active_per_slot": 1,
        "max_active_gpu": 1,
        "max_active_knowledge_analysis": 2,
        "pools": [
            {"pool_key": key, "roles": [role], "slot_keys": [f"slot{index:02}"], "max_active": 1}
            for index, (key, role) in enumerate(
                (
                    ("authoring", "authoring"),
                    ("review", "review"),
                    ("image", "image"),
                    ("item-management", "item_management"),
                    ("support", "support"),
                    ("customer-support", "support"),
                ),
                start=1,
            )
        ],
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
    }
    return WorkerCapacityPolicyV4.model_validate({**body, "content_sha256": content_sha256(body)})


def _publication(monkeypatch):
    session = Mock(spec=Session)
    sessions = SimpleNamespace(begin=lambda: nullcontext(session))
    publisher = Mock()

    def publish(**kwargs):
        digest = sha256_bytes(kwargs["payload"])
        return PublishedControlArtifact(
            job_id="job_" + digest[7:39],
            pointer=ControlArtifactPointer(
                artifact_id="artifact_" + digest[7:39],
                artifact_revision_id="rev_" + digest[7:39],
                sha256=digest,
                schema_ref=kwargs["schema_ref"],
                media_type=kwargs["media_type"],
                logical_name=kwargs["logical_name"],
            ),
            manifest_sha256="sha256:" + "a" * 64,
        )

    publisher.publish_bytes.side_effect = publish
    record = Mock(
        side_effect=lambda _session, **kwargs: SimpleNamespace(
            bundle_id=kwargs["document"]["bundle_id"],
            bundle_revision_id=kwargs["document"]["bundle_revision_id"],
        )
    )
    activate = Mock()
    authorize = Mock()
    monkeypatch.setattr(controls, "record_bundle_revision", record)
    monkeypatch.setattr(controls, "publish_bundle_revision", activate)
    args = dict(
        platform_payload=b"# Synthetic platform\n",
        role_payload=b"# Synthetic creative role\n",
        source_commit="a" * 40,
        operator_id=OPERATOR,
        created_at=NOW,
        authorize_control_change=authorize,
    )
    return SimpleNamespace(**locals())


def test_instruction_publication_pins_exact_two_layers_and_replay(monkeypatch):
    value = _publication(monkeypatch)
    first = controls.publish_external_item_learning_instruction_bundle(
        value.sessions, value.publisher, **value.args
    )
    second = controls.publish_external_item_learning_instruction_bundle(
        value.sessions, value.publisher, **value.args
    )
    assert first == second
    assert value.publisher.publish_bytes.call_count == 6
    manifest = InstructionBundleManifest.model_validate(value.record.call_args.kwargs["document"])
    assert tuple(part.layer for part in manifest.components) == ("PLATFORM", "ROLE")
    assert tuple(part.relative_path for part in manifest.components) == (
        "instructions/platform.md",
        "instructions/external-item-learning.md",
    )
    assert manifest.components[1].artifact.sha256 == sha256_bytes(value.args["role_payload"])
    assert all(call.args == (OPERATOR,) for call in value.authorize.call_args_list)


@pytest.mark.parametrize("payload", [b"", b"x" * (64 * 1024 + 1), b"\xff", b"# x\x00"])
def test_both_instruction_inputs_are_checked_before_any_publication(monkeypatch, payload):
    value = _publication(monkeypatch)
    value.args["role_payload"] = payload
    with pytest.raises(ValueError):
        controls.publish_external_item_learning_instruction_bundle(
            value.sessions, value.publisher, **value.args
        )
    value.publisher.publish_bytes.assert_not_called()


def _draft_case(monkeypatch):
    published = _publication(monkeypatch)
    pointer = controls.publish_external_item_learning_instruction_bundle(
        published.sessions, published.publisher, **published.args
    )
    manifest = InstructionBundleManifest.model_validate(
        published.record.call_args.kwargs["document"]
    )
    capacity = _capacity()
    logical_capacity = SimpleNamespace(
        policy_key="fixed-host",
        state="ACTIVE",
        current_revision_id=capacity.capacity_policy_revision_id,
    )
    logical_bundle = SimpleNamespace(
        bundle_key=controls.CREATIVE_INSTRUCTION_BUNDLE_KEY,
        bundle_kind="INSTRUCTION",
        state="ACTIVE",
        current_revision_id=pointer.bundle_revision_id,
    )
    session = Mock(spec=Session)
    session.in_transaction.return_value = True
    session.get.side_effect = lambda model, _key, **_kwargs: {
        WorkerCapacityPolicyRecord: logical_capacity,
        ExecutionBundleRecord: logical_bundle,
    }[model]
    session.scalar.return_value = None
    monkeypatch.setattr(controls, "resolve_released_capacity_policy", Mock(return_value=capacity))
    monkeypatch.setattr(
        controls, "resolve_released_instruction_bundle", Mock(return_value=manifest)
    )

    def create(_session, **kwargs):
        body = {
            "schema_version": "execution-preset-revision/1.0",
            "preset_id": "execpreset_" + "1" * 32,
            "preset_revision_id": "execpresetrev_" + "2" * 32,
            "revision_number": 1,
            "state": "DRAFT",
            "created_at": kwargs["created_at"].isoformat().replace("+00:00", "Z"),
            **{
                key: kwargs[key]
                for key in (
                    "display_name",
                    "description",
                    "role_policies",
                    "capacity_policy_revision_id",
                    "general_knowledge_policy",
                    "compatible_workflow_protocols",
                )
            },
        }
        body["content_sha256"] = content_sha256(body)
        return SimpleNamespace(**body, canonical_document=body)

    create_draft = Mock(side_effect=create)
    monkeypatch.setattr(controls, "create_execution_preset_draft", create_draft)
    authorize = Mock()
    args = dict(
        instruction=pointer,
        capacity_revision_id=capacity.capacity_policy_revision_id,
        candidate=ModelCandidate(model="synthetic-reviewed-model", reasoning_effort="high"),
        operator_id=OPERATOR,
        created_at=NOW,
        authorize_control_change=authorize,
    )
    return SimpleNamespace(**locals())


def test_prepare_draft_reuses_existing_slot_policy_without_releasing(monkeypatch):
    value = _draft_case(monkeypatch)
    draft = controls.prepare_external_item_learning_control_draft(value.session, **value.args)
    assert draft.state == "DRAFT"
    assert draft.capacity_policy_revision_id == value.capacity.capacity_policy_revision_id
    assert draft.role_policies[0].worker_pool_key == "support"
    assert draft.role_policies[0].reference_bundle is None
    assert draft.compatible_workflow_protocols == ("workflow-role/1.33.0",)
    assert value.authorize.call_count == 2
    assert value.create_draft.call_count == 1
    value.session.commit.assert_not_called()
    value.session.rollback.assert_not_called()


def test_replay_returns_one_draft_without_a_new_revision(monkeypatch):
    value = _draft_case(monkeypatch)
    first = controls.prepare_external_item_learning_control_draft(value.session, **value.args)
    row = SimpleNamespace(
        **first.model_dump(mode="json"), canonical_document=first.model_dump(mode="json")
    )
    logical = SimpleNamespace(preset_id=first.preset_id, state="ACTIVE", current_revision_id=None)
    value.session.scalar.side_effect = [logical, row]
    second = controls.prepare_external_item_learning_control_draft(value.session, **value.args)
    assert first == second and value.create_draft.call_count == 1


@pytest.mark.parametrize(
    "fault", ["capacity", "stale_capacity", "purpose", "stale_bundle", "active_preset"]
)
def test_draft_cannot_borrow_another_or_stale_control_purpose(monkeypatch, fault):
    value = _draft_case(monkeypatch)
    if fault == "capacity":
        value.logical_capacity.policy_key = "different-capacity"
    elif fault == "stale_capacity":
        value.logical_capacity.current_revision_id = "capacityrev_" + "0" * 32
    elif fault == "purpose":
        value.logical_bundle.bundle_key = "ordinary-review"
    elif fault == "stale_bundle":
        value.logical_bundle.current_revision_id = "instrrev_" + "0" * 32
    else:
        value.session.scalar.side_effect = [
            SimpleNamespace(
                preset_id="execpreset_" + "1" * 32, state="ACTIVE", current_revision_id="published"
            ),
            SimpleNamespace(),
        ]
    with pytest.raises(ControlPlaneError):
        controls.prepare_external_item_learning_control_draft(value.session, **value.args)
    value.create_draft.assert_not_called()
    value.session.rollback.assert_called_once()


def test_late_authorization_failure_discards_draft(monkeypatch):
    value = _draft_case(monkeypatch)
    value.authorize.side_effect = [None, ValueError("synthetic revocation")]
    with pytest.raises(ValueError):
        controls.prepare_external_item_learning_control_draft(value.session, **value.args)
    value.session.rollback.assert_called_once()


def test_source_instructions_preserve_the_closed_proposal_boundary():
    root = Path(__file__).resolve().parents[2]
    role = (
        root
        / "config/control-plane/external-item-learning-v1/instructions/external-item-learning.md"
    ).read_text()
    assert "REFERENCE_ORIGINAL" in role and "NEEDS_DECISION" in role
    assert "content_region_map" in role and "EDITORIAL_SOLUTION" in role
    assert "Omit `result_sha256`" in role
    # Exact schema/pointer and semantic tests provide the runtime enforcement;
    # this check only guards accidental removal of the prompt's core duties.
