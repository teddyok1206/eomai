"""Original metadata guards in a marked disposable DB, not private execution.

The definition is inactive and every origin is synthetic. No source permission,
Chat claim, worker, model, Artifact bytes or production installation is exercised.
Committed concurrency evidence is retained until the official database cleanup.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from eom_catalog_contracts.private_chat_query_read import ChatPrivateQueryOrigin
from eom_workflow.private_chat_query_execution import PrivateChatQueryWorkflowRequest
from eom_workflow.private_chat_query_submission_context import (
    build_private_chat_query_submission_context,
    parse_private_chat_query_submission_context,
    private_chat_query_submission_fingerprint,
)
from eom_workflow_runner.models import WorkflowDefinitionRecord, WorkflowInstanceRecord
from eom_workflow_runner.private_chat_query_persistence_guards import (
    PRIVATE_CHAT_QUERY_CONTEXT_CHECK,
    PRIVATE_CHAT_QUERY_TURN_INDEX,
)
from sqlalchemy import Connection, Engine, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from tests.integration.test_inference_transfer_stage_migration import (
    stage_owner_connection as stage_owner_connection,
)
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_private_chat_query_context_models import migration_module
from tests.unit.test_private_chat_query_submission_context import context_case

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]
KEY = "local-embedding-private-chat-query"


def _case():
    value = context_case()
    actor = "operator_" + uuid4().hex
    request = PrivateChatQueryWorkflowRequest.model_validate(
        seal(
            value.request.model_dump(mode="json")
            | {
                "operator_audit": value.request.operator_audit.model_dump(mode="json")
                | {"operator_id": actor}
            },
            "request_sha256",
        )
    )
    origin = ChatPrivateQueryOrigin.model_validate(
        seal(value.context.origin.model_dump(mode="json") | {"actor_id": actor}, "origin_sha256")
    )
    return request, build_private_chat_query_submission_context(request, origin)


def _definition(connection: Connection, request) -> str:
    connection.execute(
        insert(WorkflowDefinitionRecord)
        .values(
            definition_id="wfdef_" + uuid4().hex,
            definition_key=KEY,
            definition_version="1.0.0",
            schema_version="1.1",
            canonical_definition={"fixture_kind": "INACTIVE_PRIVATE_CONTEXT_GUARD_ONLY"},
            definition_hash=request.workflow_definition_sha256,
            active=False,
            source_path="synthetic/private-context-guard-only",
        )
        .on_conflict_do_nothing(constraint="uq_workflow_definition_key_version")
    )
    row = (
        connection.execute(
            select(WorkflowDefinitionRecord.__table__).where(
                WorkflowDefinitionRecord.definition_key == KEY,
                WorkflowDefinitionRecord.definition_version == "1.0.0",
            )
        )
        .mappings()
        .one()
    )
    assert not row["active"] and row["definition_hash"] == request.workflow_definition_sha256
    return row["definition_id"]


def _row(definition_id, request, context):
    return dict(
        workflow_id="workflow_" + uuid4().hex,
        definition_id=definition_id,
        definition_key=KEY,
        definition_version="1.0.0",
        definition_hash=request.workflow_definition_sha256,
        protocol_version="1.0.1",
        role_schema_version="private-chat-query/1.0",
        state="REQUESTED",
        stage="LOCAL_EMBEDDING",
        current_step_key="encode_private_chat_query",
        request_payload=request.model_dump(mode="json"),
        initial_request=request.model_dump(mode="json"),
        runtime_context=context.model_dump(mode="json"),
        idempotency_key="synthetic-private-context-" + uuid4().hex,
        request_hash=private_chat_query_submission_fingerprint(
            request,
            context,
            definition_sha256=request.workflow_definition_sha256,
            actor_type="human",
            actor_id=context.origin.actor_id,
        ),
        lock_version=1,
        rework_cycle_count=0,
        created_actor_type="human",
        created_actor_id=context.origin.actor_id,
    )


def test_guard_round_trip_without_private_history(stage_owner_connection, monkeypatch):
    connection = stage_owner_connection
    assert (
        connection.scalar(
            text("SELECT count(*) FROM workflow_instances WHERE definition_key=:key"), {"key": KEY}
        )
        == 0
    )
    migration = migration_module()
    monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
    migration.downgrade()
    migration.upgrade()
    assert connection.scalar(
        text("SELECT to_regclass(:name)"), {"name": PRIVATE_CHAT_QUERY_TURN_INDEX}
    )


def test_original_context_round_trips_and_only_state_progression_remains_mutable(
    stage_owner_connection,
):
    connection = stage_owner_connection
    request, context = _case()
    row = _row(_definition(connection, request), request, context)
    connection.execute(insert(WorkflowInstanceRecord).values(**row))
    saved = connection.scalar(
        select(WorkflowInstanceRecord.runtime_context).where(
            WorkflowInstanceRecord.workflow_id == row["workflow_id"]
        )
    )
    assert parse_private_chat_query_submission_context(saved) == context
    connection.execute(
        text("UPDATE workflow_instances SET state='RUNNING' WHERE workflow_id=:id"),
        {"id": row["workflow_id"]},
    )
    assert context.origin.actor_id == row["created_actor_id"]


@pytest.mark.parametrize(
    "fault", ("empty", "null", "extra", "pointers", "actor", "basis", "payload", "size")
)
def test_db_rejects_incomplete_or_unbound_private_metadata(stage_owner_connection, fault):
    connection = stage_owner_connection
    request, context = _case()
    row = _row(_definition(connection, request), request, context)
    if fault == "empty":
        row["runtime_context"] = {}
    elif fault == "null":
        row["runtime_context"] = None
    elif fault == "extra":
        row["runtime_context"]["untrusted_authority"] = "ADMIN"
    elif fault == "pointers":
        row["runtime_context"]["artifact_pointers"] = [{}]
    elif fault == "actor":
        row["created_actor_id"] = "operator_" + "f" * 32
    elif fault == "basis":
        row["runtime_context"]["origin"]["basis"]["turn_id"] = "chatturn_" + "f" * 32
    elif fault == "payload":
        row["request_payload"] = {}
    else:
        row["runtime_context"]["origin"]["padding"] = "x" * 65536
    with pytest.raises(IntegrityError) as error, connection.begin_nested():
        connection.execute(insert(WorkflowInstanceRecord).values(**row))
    assert error.value.orig.sqlstate == "23514"
    assert error.value.orig.diag.constraint_name == PRIVATE_CHAT_QUERY_CONTEXT_CHECK


@pytest.mark.parametrize(
    "field", ("runtime_context", "created_actor_id", "request_payload", "delete")
)
def test_private_origin_history_cannot_be_rewritten_or_deleted(stage_owner_connection, field):
    connection = stage_owner_connection
    request, context = _case()
    row = _row(_definition(connection, request), request, context)
    connection.execute(insert(WorkflowInstanceRecord).values(**row))
    with (
        pytest.raises(IntegrityError, match="PRIVATE_CHAT_QUERY_ORIGIN_IMMUTABLE"),
        connection.begin_nested(),
    ):
        table = WorkflowInstanceRecord.__table__
        if field == "delete":
            statement = table.delete()
        else:
            value = "operator_" + "f" * 32 if field == "created_actor_id" else {}
            statement = table.update().values({field: value})
        connection.execute(statement.where(table.c.workflow_id == row["workflow_id"]))
    assert connection.scalar(
        select(WorkflowInstanceRecord.runtime_context).where(
            WorkflowInstanceRecord.workflow_id == row["workflow_id"]
        )
    ) == context.model_dump(mode="json")


def test_downgrade_refuses_private_history_and_preserves_guards(
    stage_owner_connection, monkeypatch
):
    connection = stage_owner_connection
    request, context = _case()
    connection.execute(
        insert(WorkflowInstanceRecord).values(
            **_row(_definition(connection, request), request, context)
        )
    )
    migration = migration_module()
    monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
    with pytest.raises(DBAPIError, match="absent original history"), connection.begin_nested():
        migration.downgrade()
    assert connection.scalar(
        text("SELECT to_regclass(:name)"), {"name": PRIVATE_CHAT_QUERY_TURN_INDEX}
    )


def test_concurrent_different_keys_and_fingerprints_keep_one_original_turn(guarded_engine: Engine):
    request, context = _case()
    other_origin = ChatPrivateQueryOrigin.model_validate(
        seal(
            context.origin.model_dump(mode="json") | {"runtime_id": "chatrt_" + uuid4().hex},
            "origin_sha256",
        )
    )
    other_context = build_private_chat_query_submission_context(request, other_origin)
    with guarded_engine.begin() as connection:
        definition = _definition(connection, request)
    rows = [_row(definition, request, origin) for origin in (context, other_context)]
    assert rows[0]["request_hash"] != rows[1]["request_hash"]
    assert rows[0]["idempotency_key"] != rows[1]["idempotency_key"]
    barrier = Barrier(2)

    def submit(row):
        try:
            with guarded_engine.begin() as connection:
                barrier.wait(timeout=10)
                connection.execute(insert(WorkflowInstanceRecord).values(**row))
            return "COMMITTED"
        except IntegrityError as error:
            assert error.orig.sqlstate == "23505"
            assert error.orig.diag.constraint_name == PRIVATE_CHAT_QUERY_TURN_INDEX
            return "DUPLICATE_TURN_REJECTED"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = sorted(pool.map(submit, rows))
    assert results == ["COMMITTED", "DUPLICATE_TURN_REJECTED"]
    with Session(guarded_engine) as session:
        saved = list(
            session.scalars(
                select(WorkflowInstanceRecord).where(
                    WorkflowInstanceRecord.created_actor_id == context.origin.actor_id,
                    WorkflowInstanceRecord.definition_key == KEY,
                )
            )
        )
        assert len(saved) == 1
        assert saved[0].runtime_context in [row["runtime_context"] for row in rows]
