"""Disposable PG first common preparation/replay; source/head/IAM are explicit fake ports."""

from dataclasses import replace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.private_chat_similarity_v2 import (
    parse_supported_private_chat_similarity_request,
)
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryCaller
from eom_operator_identity import PermissionKey
from eom_workflow_runner import private_chat_query_preparation as preparation_module
from eom_workflow_runner.models import WorkflowCommandRecord, WorkflowInstanceRecord
from eom_workflow_runner.private_chat_query_preparation import (
    PrivateChatQueryPreparationUnavailable,
    prepare_and_start_private_chat_query_selection_in_session,
    read_private_chat_query_selection_in_session,
)
from sqlalchemy import func, select

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.integration.test_private_chat_document_read import registered as registered
from tests.integration.test_private_chat_public_query_native_persistence import query as query
from tests.integration.test_private_chat_public_query_submission import submission as submission
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.local_embedding_admission_fixtures import runtime_profile
from tests.unit.test_private_chat_query_preparation import initial_selection

pytestmark = [
    pytest.mark.integration,
    pytest.mark.parametrize("registered", [runtime_profile("CPU").space], indirect=True),
]


@pytest.fixture
def prepared(submission, monkeypatch):
    value = submission
    value.preparation = initial_selection(value)
    value.capture = Mock(return_value=value.request.context_request)
    monkeypatch.setattr(
        value.owner.catalog, "prepare_private_chat_context_in_session", value.capture
    )
    monkeypatch.setattr(
        preparation_module,
        "effective_permissions",
        lambda *_args: frozenset({PermissionKey.WORKFLOW_START}),
    )
    return value


def prepare(value, session):
    value.source.fault.session = session
    return prepare_and_start_private_chat_query_selection_in_session(
        session,
        caller=EmbeddingRegistryCaller(value.context.origin.actor_id),
        origin=value.context.origin,
        preparation=value.preparation,
        owner=value.owner,
        executor=value.executor,
    )


def test_postgres_common_preparation_and_read_keep_first_head_and_original_start(prepared):
    value = prepared
    with value.publisher.sessions.begin() as session:
        first = prepare(value, session)
        ids = first.workflow.workflow_id, first.command.command_id
        request = first.workflow.initial_request
        assert first.workflow.role_schema_version == "private-chat-query/2.0"
    value.capture.side_effect = AssertionError("replay/read must not capture a newer head")
    with value.publisher.sessions.begin() as session:
        replay = prepare(value, session)
        assert (replay.workflow.workflow_id, replay.command.command_id) == ids
        assert replay.workflow.initial_request == request
        assert not replay.workflow_created and not replay.command_created
    with value.publisher.sessions.begin() as session:
        selected = read_private_chat_query_selection_in_session(
            session,
            caller=EmbeddingRegistryCaller(value.context.origin.actor_id),
            origin=value.context.origin,
            preparation=value.preparation,
            owner=value.owner,
        )
        assert (
            selected.workflow_id == ids[0] and selected.request.model_dump(mode="json") == request
        )
        assert session.get(WorkflowCommandRecord, ids[1]).lease_generation == 0
    assert value.capture.call_count == 1
    value.executor.execute.assert_not_called()


def test_postgres_missing_common_head_does_not_create_workflow_or_start(prepared):
    value = prepared
    body = value.request.context_request.model_dump(mode="json")
    body["views"][0]["index"] = None
    value.capture.return_value = parse_supported_private_chat_similarity_request(
        seal(body, "request_sha256")
    )
    with value.publisher.sessions.begin() as session:
        before = session.scalar(select(func.count()).select_from(WorkflowInstanceRecord))
    with (
        pytest.raises(PrivateChatQueryPreparationUnavailable),
        value.publisher.sessions.begin() as session,
    ):
        prepare(value, session)
    with value.publisher.sessions.begin() as session:
        assert session.scalar(select(func.count()).select_from(WorkflowInstanceRecord)) == before
    value.executor.execute.assert_not_called()


def test_postgres_changed_common_scope_cannot_reselect_or_replace_existing_original(prepared):
    value = prepared
    with value.publisher.sessions.begin() as session:
        first = prepare(value, session)
        identity = first.workflow.workflow_id
    value.preparation = replace(value.preparation, top_k=value.preparation.top_k + 1)
    value.capture.side_effect = AssertionError("changed scope may not capture another head")
    with pytest.raises(ValueError), value.publisher.sessions.begin() as session:
        prepare(value, session)
    with value.publisher.sessions.begin() as session:
        assert session.get(WorkflowInstanceRecord, identity).state == "REQUESTED"
    assert value.capture.call_count == 1
    value.executor.execute.assert_not_called()
