"""Closed metadata and negative submission seams, not current/physical admission."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_workflow.compiler import compile_definition_data
from eom_workflow.private_chat_query_submission_context import private_chat_query_submission_key
from eom_workflow_runner import private_chat_query_admission as admission
from eom_workflow_runner import private_chat_query_owner_admission as owner_module
from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.models import WorkflowDefinitionRecord
from eom_workflow_runner.native_start_command import (
    PRIVATE_CHAT_QUERY_SUBMISSION_SOURCE,
    resolve_native_start_command,
)
from eom_workflow_runner.private_chat_query_submission import start_private_chat_query_in_session
from eom_workflow_runner.repository import (
    create_workflow_instance,
    workflow_request_storage_document,
)
from sqlalchemy.orm import Session

from tests.unit.test_private_chat_query_submission_context import context_case
from tests.unit.test_private_chat_query_workflow import definition_body


@pytest.fixture
def submission():
    value = context_case()
    compiled = compile_definition_data(definition_body(), "synthetic-private-submission", set())
    value.definition = WorkflowDefinitionRecord(
        definition_id="wfdef_" + "a" * 32,
        definition_key=compiled.definition.definition_key,
        definition_version=compiled.definition.definition_version,
        schema_version=compiled.definition.schema_version,
        definition_hash=compiled.sha256,
        canonical_definition=compiled.as_dict(),
        source_path=compiled.source_path,
        active=True,
    )
    value.session = Mock(spec=Session)
    value.owner, value.executor = Mock(), Mock()
    return value


def create(value, **overrides):
    return create_workflow_instance(
        value.session,
        **(
            dict(
                definition=value.definition,
                request=value.request,
                idempotency_key=private_chat_query_submission_key(value.context),
                actor_type="human",
                actor_id=value.context.origin.actor_id,
                private_chat_query_context=value.context,
                private_chat_query_owner=value.owner,
                private_chat_query_executor=value.executor,
            )
            | overrides
        ),
    )


def test_private_definition_remains_unoffered_before_any_sql_or_current_source_io(
    submission, monkeypatch
):
    # This negative seam requires an unoffered definition, independently of
    # which purposes the current production admission catalog now supports.
    monkeypatch.setattr(admission, "workflow_definition_is_admitted", lambda *_args: False)
    value = submission
    with pytest.raises(WorkflowError) as error:
        create(value)
    assert error.value.code is WorkflowErrorCode.LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE
    assert value.session.mock_calls == value.owner.mock_calls == value.executor.mock_calls == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("runtime_context", {}),
        ("completed_preset_revision_id", "presetrv_" + "b" * 32),
        ("inference_transfer_context", object()),
        ("local_embedding_owner", object()),
        ("local_embedding_executor", object()),
        ("reference_query_owner", object()),
        ("reference_query_executor", object()),
        ("private_chat_query_context", None),
        ("idempotency_key", "caller-invented-private-key"),
    ],
)
def test_private_submission_refuses_other_purpose_context_and_caller_chosen_keys_before_io(
    submission, field, value
):
    with pytest.raises(WorkflowError) as error:
        create(submission, **{field: value})
    assert error.value.code is WorkflowErrorCode.WORKFLOW_REQUEST_INVALID
    assert submission.session.mock_calls == submission.owner.mock_calls == []


@pytest.mark.parametrize("kind", ["reference", "role", "private_to_other_definition"])
def test_private_context_cannot_enter_another_workflow_persistence_branch(submission, kind):
    value = submission
    request = value.request
    if kind != "private_to_other_definition":
        request = object()
    else:
        value.definition.definition_key = "local-embedding-reference-query"
    with pytest.raises(WorkflowError) as error:
        create(value, request=request)
    assert error.value.code is WorkflowErrorCode.WORKFLOW_REQUEST_INVALID
    assert value.session.mock_calls == value.owner.mock_calls == []


def test_atomic_private_start_does_not_offer_a_definition_or_invent_a_start(
    submission, monkeypatch
):
    monkeypatch.setattr(admission, "workflow_definition_is_admitted", lambda *_args: False)
    value = submission
    with pytest.raises(WorkflowError) as error:
        start_private_chat_query_in_session(
            value.session,
            definition=value.definition,
            request=value.request,
            context=value.context,
            actor_type="human",
            actor_id=value.context.origin.actor_id,
            owner=value.owner,
            executor=value.executor,
        )
    assert error.value.code is WorkflowErrorCode.LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE
    assert value.session.mock_calls == value.owner.mock_calls == value.executor.mock_calls == []


def test_storage_retains_closed_nullable_values_and_rejects_unvalidated_private_extras(submission):
    request = submission.request
    assert workflow_request_storage_document(request) == request.model_dump(mode="json")
    with pytest.raises(ValueError):
        workflow_request_storage_document(request.model_copy(update={"authority": "ADMIN"}))


def test_private_row_validator_is_one_rule_with_its_existing_supported_export():
    assert (
        owner_module.validate_private_chat_query_workflow_submission
        is admission.validate_private_chat_query_workflow_submission
    )


def test_native_start_private_replay_refuses_missing_original_without_persistence(submission):
    value = submission
    value.session.scalar.return_value = None
    workflow = SimpleNamespace(
        workflow_id="workflow_" + "a" * 32,
        created_actor_type="human",
        created_actor_id=value.context.origin.actor_id,
    )
    with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_SUBMISSION_REPLAY_INVALID"):
        resolve_native_start_command(
            value.session,
            workflow=workflow,
            workflow_created=False,
            actor_type="human",
            actor_id=workflow.created_actor_id,
            source=PRIVATE_CHAT_QUERY_SUBMISSION_SOURCE,
        )
    value.session.add.assert_not_called()
    value.session.flush.assert_not_called()
