"""Creative source admission reuses the Workflow repository without worker execution."""

from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest
from eom_identifiers import content_sha256
from eom_workflow.compiler import compile_definition
from eom_workflow.models import WorkflowRequest
from eom_workflow_runner.errors import WorkflowError
from eom_workflow_runner.external_item_learning_admission import (
    external_item_learning_fingerprint,
    validate_external_item_learning_definition,
)
from eom_workflow_runner.models import WorkflowDefinitionRecord, WorkflowInstanceRecord
from eom_workflow_runner.repository import (
    create_workflow_instance,
    load_persisted_workflow_request,
    workflow_request_storage_document,
)
from sqlalchemy.orm import Session

from tests.unit.test_external_item_learning_work_contract import _work

ROOT = Path(__file__).resolve().parents[2]
OPERATOR = "operator_" + "a" * 32
OTHER_OPERATOR = "operator_" + "b" * 32


def _definition() -> WorkflowDefinitionRecord:
    compiled = compile_definition(
        ROOT / "config/workflows/external-item-learning.v1.yaml", {"support"}
    )
    return WorkflowDefinitionRecord(
        definition_id="wfdef_" + "c" * 32,
        definition_key="external-item-learning",
        definition_version="1.0.0",
        schema_version="1.0",
        canonical_definition=compiled.as_dict(),
        definition_hash=compiled.sha256,
        source_path=compiled.source_path,
        active=True,  # synthetic admission; no production definition is activated
    )


def _request() -> WorkflowRequest:
    return WorkflowRequest(
        request_name="EXTERNAL_ITEM_LEARNING_REQUEST",
        image_mode="skip",
        execution_preset_key="external-item-learning",
        external_item_learning_work=_work(),
    )


def _session() -> Mock:
    session = Mock(spec=Session)
    session.scalar.return_value = None
    session.begin_nested.side_effect = lambda: nullcontext()
    return session


def _owner(request: WorkflowRequest) -> Mock:
    owner = Mock()
    owner.reauthorize.return_value = request.external_item_learning_work.source
    return owner


def _create(
    session: Mock, *, actor: str = OPERATOR, owner: Mock | None = None
) -> tuple[WorkflowInstanceRecord, bool]:
    request = _request()
    return create_workflow_instance(
        session,
        definition=_definition(),
        request=request,
        actor_type="human",
        actor_id=actor,
        idempotency_key="synthetic-creative-owner-admission",
        external_item_learning_authorizer=owner or _owner(request),
    )


def test_persisted_creative_work_uses_current_source_and_knowledge_stage() -> None:
    session = _session()
    request = _request()
    owner = _owner(request)
    workflow, created = _create(session, owner=owner)

    assert created
    assert workflow.stage == "KNOWLEDGE_ANALYSIS"
    assert workflow.created_actor_id == OPERATOR
    assert workflow.role_schema_version == "workflow-role/1.33.0"
    assert load_persisted_workflow_request(workflow.initial_request) == request
    assert owner.reauthorize.call_count == 2
    for call in owner.reauthorize.call_args_list:
        assert call.args == (session,)
        assert call.kwargs["operator_id"] == OPERATOR
        assert call.kwargs["source"] == request.external_item_learning_work.source
    assert workflow.runtime_context == {"artifact_pointers": []}
    assert set(workflow.initial_request["external_item_learning_work"]) == {
        "schema_version",
        "request_id",
        "source",
        "page_set",
        "page_artifact",
        "request_sha256",
    }


@pytest.mark.parametrize("limit", ["max_step_attempts", "max_rework_cycles"])
def test_creative_definition_cannot_expand_one_shot_limits(limit):
    definition = _definition()
    definition.canonical_definition["limits"][limit] = 2
    definition.definition_hash = content_sha256(definition.canonical_definition)
    with pytest.raises(WorkflowError):
        validate_external_item_learning_definition(definition)


@pytest.mark.parametrize("invalid", ["owner", "definition", "inactive", "hash", "context", "actor"])
def test_invalid_creative_admission_is_rejected_before_lookup(invalid: str) -> None:
    session = _session()
    request = _request()
    definition = _definition()
    owner = _owner(request)
    if invalid == "definition":
        definition.definition_key = "customer-support"
    elif invalid == "inactive":
        definition.active = False
    elif invalid == "hash":
        definition.definition_hash = "sha256:" + "0" * 64

    with pytest.raises(WorkflowError):
        create_workflow_instance(
            session,
            definition=definition,
            request=request,
            actor_type="worker" if invalid == "actor" else "human",
            actor_id=OPERATOR,
            idempotency_key="synthetic-invalid-creative",
            runtime_context={} if invalid == "context" else None,
            external_item_learning_authorizer=None if invalid == "owner" else owner,
        )
    session.scalar.assert_not_called()
    session.add.assert_not_called()
    owner.reauthorize.assert_not_called()


def test_other_request_cannot_borrow_creative_source_authorizer() -> None:
    session = _session()
    definition = _definition()
    definition.definition_key = "generic-item-development"
    with pytest.raises(WorkflowError):
        create_workflow_instance(
            session,
            definition=definition,
            request=WorkflowRequest(request_name="PLACEHOLDER_REQUEST", image_mode="skip"),
            actor_type="human",
            actor_id=OPERATOR,
            idempotency_key="synthetic-other-purpose",
            external_item_learning_authorizer=_owner(_request()),
        )
    session.scalar.assert_not_called()


def test_creative_replay_reauthorizes_and_does_not_share_another_owner() -> None:
    first, _ = _create(_session())
    replay = _session()
    replay.scalar.return_value = first
    owner = _owner(_request())
    same, created = _create(replay, owner=owner)
    assert same is first and not created
    assert owner.reauthorize.call_count == 2
    replay.add.assert_not_called()
    with pytest.raises(WorkflowError):
        _create(replay, actor=OTHER_OPERATOR)

    other, _ = _create(_session(), actor=OTHER_OPERATOR)
    assert other.request_hash != first.request_hash


@pytest.mark.parametrize("late", [False, True])
def test_source_revocation_rejects_without_reinterpreting_history(late: bool) -> None:
    session = _session()
    owner = _owner(_request())
    error = ValueError("source revoked")
    owner.reauthorize.side_effect = (
        [_request().external_item_learning_work.source, error] if late else error
    )
    with pytest.raises(WorkflowError):
        _create(session, owner=owner)
    if late:
        session.rollback.assert_called_once()
    else:
        session.add.assert_not_called()


def test_same_source_lookups_cannot_substitute_another_preview() -> None:
    session = _session()
    owner = _owner(_request())
    original = _request().external_item_learning_work.source
    owner.reauthorize.return_value = original.model_copy(
        update={"preview_artifact_revision_id": "rev_" + "0" * 32}
    )
    with pytest.raises(WorkflowError):
        _create(session, owner=owner)
    session.add.assert_not_called()


def test_replay_with_modified_initial_input_is_not_accepted() -> None:
    first, _ = _create(_session())
    first.initial_request = deepcopy(first.initial_request)
    first.initial_request["external_item_learning_work"]["source"]["external_number"] = "00000"
    replay = _session()
    replay.scalar.return_value = first
    with pytest.raises(WorkflowError):
        _create(replay)
    replay.rollback.assert_called_once()


def test_creative_input_storage_contains_only_existing_typed_pointers() -> None:
    value = workflow_request_storage_document(_request())
    assert load_persisted_workflow_request(value) == _request()
    assert "operator_id" not in value
    assert "workspace" not in value
    assert isinstance(value["external_item_learning_work"]["page_artifact"], dict)


def test_new_request_id_does_not_multiply_the_same_pinned_work() -> None:
    original = _request()
    changed = original.model_dump(mode="json")
    work = changed["external_item_learning_work"]
    work["request_id"] = "extlearnreq_" + "0" * 32
    work["request_sha256"] = content_sha256(
        {key: value for key, value in work.items() if key != "request_sha256"}
    )
    successor = WorkflowRequest.model_validate(changed)
    assert external_item_learning_fingerprint(_definition(), original, operator_id=OPERATOR) == (
        external_item_learning_fingerprint(_definition(), successor, operator_id=OPERATOR)
    )
    first, _ = _create(_session())
    session = _session()
    session.scalar.return_value = first
    with pytest.raises(WorkflowError):
        create_workflow_instance(
            session,
            definition=_definition(),
            request=successor,
            actor_type="human",
            actor_id=OPERATOR,
            idempotency_key="synthetic-new-request-id-same-pins",
            external_item_learning_authorizer=_owner(successor),
        )
    session.add.assert_not_called()
