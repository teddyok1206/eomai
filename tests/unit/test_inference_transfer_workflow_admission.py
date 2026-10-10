from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from typing import Any, cast
from unittest.mock import Mock

import pytest
from eom_identifiers import content_sha256
from eom_workflow.inference_transfer import TRANSFER_PAIR_PROTOCOL
from eom_workflow.inference_transfer_workflow import InferenceTransferWorkflowRequest
from eom_workflow.models import WorkflowRequest
from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.inference_transfer_admission import (
    InferenceTransferSubmissionContext,
    admit_inference_transfer_workflow_request,
)
from eom_workflow_runner.models import WorkflowInstanceRecord
from eom_workflow_runner.repository import (
    create_workflow_instance,
    load_persisted_inference_transfer_workflow_request,
    load_persisted_workflow_request,
    workflow_business_fingerprint,
    workflow_request_storage_document,
)
from eom_workflow_runner.state_machine import WorkflowStage
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tests.unit.inference_transfer_fixtures import sha
from tests.unit.inference_transfer_workflow_fixtures import (
    OPERATOR_ID,
    OTHER_OPERATOR_ID,
    definition,
    submission_context,
    workflow_request,
)


def _admit(
    value: WorkflowRequest | InferenceTransferWorkflowRequest,
    *,
    key: str = "item-inference-transfer-comparison",
    version: str = "1.0.0",
    protocol: str = TRANSFER_PAIR_PROTOCOL,
    actor_id: str = OPERATOR_ID,
    actor_type: str = "human",
    context: InferenceTransferSubmissionContext | None = None,
) -> WorkflowRequest | InferenceTransferWorkflowRequest:
    return admit_inference_transfer_workflow_request(
        definition_key=key,
        definition_version=version,
        role_protocol_version=protocol,
        request=value,
        actor_type=actor_type,
        actor_id=actor_id,
        submission_context=context,
    )


def _create(
    session: Mock,
    *,
    value: WorkflowRequest | InferenceTransferWorkflowRequest | None = None,
    actor_id: str = OPERATOR_ID,
    key: str = "synthetic-transfer-submission",
    context: InferenceTransferSubmissionContext | None = None,
) -> tuple[WorkflowInstanceRecord, bool]:
    return create_workflow_instance(
        cast(Session, session),
        definition=definition(),
        request=value or workflow_request(),
        idempotency_key=key,
        actor_type="human",
        actor_id=actor_id,
        inference_transfer_context=context,
    )


def _empty_session() -> Mock:
    session = Mock(spec=Session)
    session.scalar.return_value = None
    session.begin_nested.return_value = nullcontext()
    return session


def _assert_no_repository_activity(session: Mock) -> None:
    session.scalar.assert_not_called()
    session.execute.assert_not_called()
    session.add.assert_not_called()
    session.flush.assert_not_called()
    session.begin_nested.assert_not_called()


def test_exact_purpose_wrapper_requires_server_input_but_grants_no_source_authority() -> None:
    value = workflow_request()
    assert _admit(value, context=submission_context()) == value
    assert _admit(value, context=submission_context()) is not value
    legacy = WorkflowRequest(request_name="PLACEHOLDER_REQUEST", image_mode="skip")
    assert _admit(legacy, key="generic-item-development") is legacy


@pytest.mark.parametrize(
    ("key", "version", "protocol", "legacy"),
    (
        ("item-inference-transfer-comparison", "1.0.0", TRANSFER_PAIR_PROTOCOL, True),
        ("generic-item-development", "1.0.0", TRANSFER_PAIR_PROTOCOL, False),
        ("customer-support", "1.0.0", TRANSFER_PAIR_PROTOCOL, False),
        ("pdf-document-review", "1.0.0", TRANSFER_PAIR_PROTOCOL, False),
        ("item-inference-transfer-comparison", "2.0.0", TRANSFER_PAIR_PROTOCOL, False),
        ("item-inference-transfer-comparison", "1.0.0", "workflow-role/1.28.0", False),
    ),
)
def test_cross_purpose_or_version_protocol_mismatch_is_not_admitted(
    key: str, version: str, protocol: str, legacy: bool
) -> None:
    value = (
        WorkflowRequest(request_name="PLACEHOLDER_REQUEST", image_mode="skip")
        if legacy
        else workflow_request()
    )
    with pytest.raises(WorkflowError) as error:
        _admit(value, key=key, version=version, protocol=protocol, context=submission_context())
    assert error.value.code == WorkflowErrorCode.WORKFLOW_REQUEST_INVALID


@pytest.mark.parametrize(
    ("actor_type", "actor_id", "context"),
    (
        ("human", OPERATOR_ID, None),
        ("worker", OPERATOR_ID, submission_context()),
        ("human", OTHER_OPERATOR_ID, submission_context()),
        (
            "human",
            OPERATOR_ID,
            InferenceTransferSubmissionContext(
                operator_id=OPERATOR_ID, requester_permissions_sha256=sha("f")
            ),
        ),
    ),
)
def test_actor_and_initial_snapshot_are_server_composition_inputs(
    actor_type: str, actor_id: str, context: InferenceTransferSubmissionContext | None
) -> None:
    with pytest.raises(WorkflowError) as error:
        _admit(workflow_request(), actor_type=actor_type, actor_id=actor_id, context=context)
    assert error.value.code == WorkflowErrorCode.ACTOR_AUTHORIZATION_UNAVAILABLE


def test_copied_context_is_reparsed_not_trusted_as_authentication() -> None:
    copied = submission_context().model_copy(update={"operator_id": "ADMIN"})
    with pytest.raises(WorkflowError) as error:
        _admit(workflow_request(), actor_id="ADMIN", context=copied)
    assert error.value.code == WorkflowErrorCode.WORKFLOW_REQUEST_INVALID


def test_storage_reload_preserves_exact_null_bearing_context() -> None:
    value = workflow_request()
    stored = workflow_request_storage_document(value)
    assert stored == value.model_dump(mode="json")
    assert stored["left_profile"]["extraction"]["prompt_sha256"] is None
    assert load_persisted_inference_transfer_workflow_request(stored) == value
    assert (
        workflow_request_storage_document(
            load_persisted_inference_transfer_workflow_request(stored)
        )
        == stored
    )
    with pytest.raises(ValueError):
        load_persisted_workflow_request(stored)
    legacy = WorkflowRequest(request_name="PLACEHOLDER_REQUEST", image_mode="skip")
    assert load_persisted_workflow_request(workflow_request_storage_document(legacy)) == legacy


def test_new_loader_does_not_repair_missing_required_nulls() -> None:
    stored = workflow_request_storage_document(workflow_request())
    del stored["left_profile"]["extraction"]["prompt_sha256"]
    with pytest.raises(ValueError):
        load_persisted_inference_transfer_workflow_request(stored)


def test_legacy_fingerprint_bytes_remain_the_existing_canonical_projection() -> None:
    legacy = WorkflowRequest(request_name="PLACEHOLDER_REQUEST", image_mode="skip")
    old_definition = definition()
    old_definition.definition_key = "generic-item-development"
    expected = content_sha256(
        {
            "definition_key": old_definition.definition_key,
            "definition_version": old_definition.definition_version,
            "definition_hash": old_definition.definition_hash,
            "request": legacy.model_dump(mode="json", exclude_none=True),
        }
    )
    assert workflow_business_fingerprint(old_definition, legacy) == expected


@pytest.mark.parametrize("invalid", ("legacy", "context", "copied", "old_protocol"))
def test_create_rejects_invalid_admission_before_first_sql(invalid: str) -> None:
    session = _empty_session()
    value: WorkflowRequest | InferenceTransferWorkflowRequest = workflow_request()
    context: InferenceTransferSubmissionContext | None = submission_context()
    target = definition()
    if invalid == "legacy":
        value = WorkflowRequest(request_name="PLACEHOLDER_REQUEST", image_mode="skip")
    elif invalid == "context":
        context = None
    elif invalid == "copied":
        value = cast(InferenceTransferWorkflowRequest, value).model_copy(
            update={"request_name": "CUSTOMER_SUPPORT_REQUEST"}
        )
    elif invalid == "old_protocol":
        target.canonical_definition = deepcopy(target.canonical_definition)
        target.canonical_definition["steps"][0]["result_schema"] = "pdf-document-review-result@4.0"
    with pytest.raises(WorkflowError):
        create_workflow_instance(
            cast(Session, session),
            definition=target,
            request=value,
            idempotency_key="synthetic-invalid-transfer",
            actor_type="human",
            actor_id=OPERATOR_ID,
            inference_transfer_context=context,
        )
    _assert_no_repository_activity(session)


def test_new_request_cannot_create_under_legacy_definition_before_first_sql() -> None:
    session = _empty_session()
    target = definition()
    target.definition_key = "customer-support"
    with pytest.raises(WorkflowError):
        create_workflow_instance(
            cast(Session, session),
            definition=target,
            request=workflow_request(),
            idempotency_key="synthetic-foreign-purpose",
            actor_type="human",
            actor_id=OPERATOR_ID,
            inference_transfer_context=submission_context(),
        )
    _assert_no_repository_activity(session)


def test_new_workflow_records_actual_actor_distinct_hash_and_transfer_stage() -> None:
    session = _empty_session()
    first, created = _create(session, context=submission_context())
    assert created
    assert first.created_actor_id == OPERATOR_ID
    assert first.created_actor_type == "human"
    assert first.stage == WorkflowStage.INFERENCE_TRANSFER.value
    assert first.role_schema_version == TRANSFER_PAIR_PROTOCOL
    assert first.request_payload == workflow_request().model_dump(mode="json")
    assert "actor_id" not in first.request_payload
    assert (
        len(
            [
                call
                for call in session.add.call_args_list
                if isinstance(call.args[0], WorkflowInstanceRecord)
            ]
        )
        == 1
    )
    other, other_created = _create(
        session,
        actor_id=OTHER_OPERATOR_ID,
        key="synthetic-other-actor",
        context=submission_context(OTHER_OPERATOR_ID),
    )
    assert other_created
    assert first.request_hash != other.request_hash
    assert first.workflow_id != other.workflow_id


def test_actual_repository_idempotency_replay_and_foreign_actor_conflict() -> None:
    first, _ = _create(_empty_session(), context=submission_context())
    replay = _empty_session()
    replay.scalar.return_value = first
    same, created = _create(replay, context=submission_context())
    assert same is first and not created
    replay.add.assert_not_called()
    replay.scalar.reset_mock()
    with pytest.raises(WorkflowError) as error:
        _create(
            replay,
            actor_id=OTHER_OPERATOR_ID,
            context=submission_context(OTHER_OPERATOR_ID),
        )
    assert error.value.code == WorkflowErrorCode.WORKFLOW_COMMAND_DUPLICATE
    replay.add.assert_not_called()
    assert replay.scalar.call_count == 1


def test_active_equivalent_reuse_is_actor_local() -> None:
    first, _ = _create(_empty_session(), context=submission_context())
    session = _empty_session()

    def lookup(statement: Any) -> WorkflowInstanceRecord | None:
        parameters = statement.compile().params
        return first if parameters.get("request_hash_1") == first.request_hash else None

    session.scalar.side_effect = lookup
    same, created = _create(session, key="synthetic-active-replay", context=submission_context())
    assert same is first and not created
    other, created = _create(
        session,
        actor_id=OTHER_OPERATOR_ID,
        key="synthetic-other-active",
        context=submission_context(OTHER_OPERATOR_ID),
    )
    assert created and other.request_hash != first.request_hash


def test_unique_conflict_replay_keeps_same_actor_and_existing_identity() -> None:
    winner, _ = _create(_empty_session(), context=submission_context())
    raced = _empty_session()
    raced.scalar.side_effect = [None, None, None, winner]
    raced.flush.side_effect = IntegrityError("synthetic concurrent claim", {}, Exception())
    result, created = _create(raced, context=submission_context())
    assert not created and result is winner
    assert raced.scalar.call_count == 4


def test_foreign_actor_unique_conflict_does_not_reinterpret_history() -> None:
    winner, _ = _create(_empty_session(), context=submission_context())
    raced = _empty_session()
    raced.scalar.side_effect = [None, None, None, winner]
    raced.flush.side_effect = IntegrityError("synthetic concurrent global key", {}, Exception())
    with pytest.raises(WorkflowError) as error:
        _create(
            raced,
            actor_id=OTHER_OPERATOR_ID,
            context=submission_context(OTHER_OPERATOR_ID),
        )
    assert error.value.code == WorkflowErrorCode.WORKFLOW_COMMAND_DUPLICATE
    assert winner.created_actor_id == OPERATOR_ID
