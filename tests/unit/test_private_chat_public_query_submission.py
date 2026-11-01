"""Actual local metadata and source controls; source/IAM and admission2 are synthetic.

The test-local exact admission seam does not activate global private2 support.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.models import Base, JobRecord
from eom_workflow.admission import workflow_definition_is_admitted
from eom_workflow.compiler import compile_definition
from eom_workflow.private_chat_query_submission_context import (
    build_private_chat_query_submission_context,
)
from eom_workflow_runner import private_chat_query_admission as admission
from eom_workflow_runner.errors import WorkflowError
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowEventRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.private_chat_query_execution_port import PrivateChatQueryNativeExecutor
from eom_workflow_runner.private_chat_query_owner_admission import (
    CatalogPrivateChatQueryOwnerAdmission,
)
from eom_workflow_runner.private_chat_query_submission import start_private_chat_query_in_session
from sqlalchemy import Integer, func, select

from tests.unit.test_private_chat_public_query_source_owner import make_private_public_source_case
from tests.unit.test_private_chat_query_basis import TEXT


def make_common_submission_case(source, monkeypatch):
    publisher, request = source.publisher, source.request
    fixed = compile_definition(
        Path(__file__).resolve().parents[2]
        / "config/workflows/local-embedding-private-chat-query.v2.yaml",
        set(),
    )
    assert request.workflow_definition_sha256 == fixed.sha256
    with publisher.sessions.begin() as session:
        definition = session.scalar(
            select(WorkflowDefinitionRecord).where(
                WorkflowDefinitionRecord.definition_key == fixed.definition.definition_key,
                WorkflowDefinitionRecord.definition_version == fixed.definition.definition_version,
            )
        )
        if definition is None:
            definition = WorkflowDefinitionRecord(
                definition_id="wfdef_" + uuid4().hex,
                definition_key=fixed.definition.definition_key,
                definition_version=fixed.definition.definition_version,
                schema_version=fixed.definition.schema_version,
                definition_hash=fixed.sha256,
                canonical_definition=fixed.as_dict(),
                source_path="synthetic/common-submission",
                active=True,
            )
            session.add(definition)
            session.flush()
        definition_id = definition.definition_id
    assert not workflow_definition_is_admitted(fixed.definition.definition_key, "2.0.0")
    real = admission.workflow_definition_is_admitted
    monkeypatch.setattr(
        admission,
        "workflow_definition_is_admitted",
        lambda key, version: (
            (key, version) == (fixed.definition.definition_key, "2.0.0") or real(key, version)
        ),
    )
    return SimpleNamespace(
        source=source,
        publisher=publisher,
        request=request,
        context=build_private_chat_query_submission_context(request, source.projection.origin),
        owner=CatalogPrivateChatQueryOwnerAdmission(source.owner),
        executor=Mock(spec=PrivateChatQueryNativeExecutor),
        definition_id=definition_id,
    )


@pytest.fixture
def submission(tmp_path, monkeypatch):
    fixed = compile_definition(
        Path(__file__).resolve().parents[2]
        / "config/workflows/local-embedding-private-chat-query.v2.yaml",
        set(),
    )
    current = make_private_public_source_case(tmp_path, monkeypatch, definition_sha256=fixed.sha256)
    source = SimpleNamespace(
        publisher=current.old.publisher,
        request=current.request,
        owner=current.owner,
        projection=current.old.projection,
        fault=current.old.fault,
    )
    # PostgreSQL uses the actual BIGINT identity; SQLite needs INTEGER for rowid.
    monkeypatch.setattr(WorkflowEventRecord.__table__.c.event_id, "type", Integer())
    Base.metadata.create_all(
        source.publisher.engine,
        tables=[
            WorkflowDefinitionRecord.__table__,
            WorkflowInstanceRecord.__table__,
            WorkflowCommandRecord.__table__,
            WorkflowStepRunRecord.__table__,
            WorkflowEventRecord.__table__,
        ],
    )
    return make_common_submission_case(source, monkeypatch)


def submit(value, session):
    value.source.fault.session = session
    return start_private_chat_query_in_session(
        session,
        definition=session.get(WorkflowDefinitionRecord, value.definition_id),
        request=value.request,
        context=value.context,
        actor_type="human",
        actor_id=value.context.origin.actor_id,
        owner=value.owner,
        executor=value.executor,
    )


def test_common_original_start_is_text_free_atomic_and_reuses_same_start(submission):
    value = submission
    with value.publisher.sessions.begin() as session:
        count = session.scalar(select(func.count()).select_from(JobRecord))
        first = submit(value, session)
        ids = first.workflow.workflow_id, first.command.command_id
        assert first.workflow_created and first.command_created
        assert first.workflow.role_schema_version == "private-chat-query/2.0"
        assert first.workflow.state == "REQUESTED" and first.command.state == "PENDING"
        assert first.workflow.runtime_context == value.context.model_dump(mode="json")
        assert session.scalar(select(func.count()).select_from(JobRecord)) == count
        assert TEXT.encode() not in canonical_json_bytes(first.workflow.initial_request)
    with value.publisher.sessions.begin() as session:
        replay = submit(value, session)
        assert (replay.workflow.workflow_id, replay.command.command_id) == ids
        assert not replay.workflow_created and not replay.command_created
    value.executor.execute.assert_not_called()


@pytest.mark.parametrize("deny_at", [2])
def test_common_late_source_loss_rolls_back_every_released_savepoint(
    submission, monkeypatch, deny_at
):
    # SQLite's released-savepoint semantics are not PostgreSQL root rollback.
    # The actual post-write (3/4) cases belong to the disposable PG suite.
    value = submission
    real = value.owner.resolve_submission
    calls = []

    def resolve(session, request, context):
        assert not session.in_nested_transaction()
        calls.append(session.get_transaction())
        if len(calls) == deny_at:
            raise ValueError("SYNTHETIC_LATE_SOURCE_LOSS")
        return real(session, request, context)

    monkeypatch.setattr(value.owner, "resolve_submission", resolve)
    with (
        pytest.raises(ValueError, match="SYNTHETIC_LATE_SOURCE_LOSS"),
        value.publisher.sessions.begin() as session,
    ):
        submit(value, session)
    assert len(calls) == deny_at and all(root is calls[0] for root in calls)
    with value.publisher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(WorkflowInstanceRecord)) == 0
        assert session.scalar(select(func.count()).select_from(WorkflowCommandRecord)) == 0


def test_common_new_submission_stays_closed_without_exact_global_admission(submission, monkeypatch):
    monkeypatch.setattr(admission, "workflow_definition_is_admitted", lambda *_args: False)
    with pytest.raises(WorkflowError), submission.publisher.sessions.begin() as session:
        submit(submission, session)
    with submission.publisher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(WorkflowInstanceRecord)) == 0
    submission.executor.execute.assert_not_called()
