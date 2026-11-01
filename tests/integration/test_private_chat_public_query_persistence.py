"""Successor metadata guards in a marked disposable PostgreSQL database only.

Inactive synthetic definitions/rows prove storage constraints, not application
admission, a real Chat claim, native execution or current source access. The
committed uniqueness fixtures remain until official disposable DB cleanup.
"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from eom_catalog_contracts.private_chat_query_read import ChatPrivateQueryOrigin
from eom_workflow.private_chat_query_execution import PrivateChatQueryWorkflowRequest
from eom_workflow.private_chat_query_execution_v2 import (
    PrivateChatQueryWorkflowRequestV2,
    parse_supported_private_chat_query_workflow_request,
)
from eom_workflow.private_chat_query_submission_context import (
    build_private_chat_query_submission_context,
    parse_private_chat_query_submission_context,
)
from eom_workflow_runner.models import (
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.private_chat_query_persistence_guards import (
    PRIVATE_CHAT_QUERY_CONTEXT_CHECK,
    PRIVATE_CHAT_QUERY_TURN_INDEX,
)
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError, IntegrityError

from tests.integration.test_inference_transfer_stage_migration import (
    stage_owner_connection as stage_owner_connection,
)
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.integration.test_private_chat_query_context_persistence import _row as legacy_row
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_private_chat_public_query_execution import execution_case
from tests.unit.test_private_chat_public_query_persistence import public_query_migration
from tests.unit.test_private_chat_query_submission_context import context_case

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]
KEY = "local-embedding-private-chat-query"


def case(version=2, *, origin=None):
    previous = context_case()
    if origin is None:
        origin = ChatPrivateQueryOrigin.model_validate(
            seal(
                previous.context.origin.model_dump(mode="json")
                | {"actor_id": "operator_" + uuid4().hex},
                "origin_sha256",
            )
        )
    template = previous.request if version == 1 else execution_case()[0]
    context = seal(
        template.context_request.model_dump(mode="json")
        | {"query_basis": origin.basis.model_dump(mode="json")},
        "request_sha256",
    )
    request_type = (
        PrivateChatQueryWorkflowRequest if version == 1 else PrivateChatQueryWorkflowRequestV2
    )
    request = request_type.model_validate(
        seal(
            template.model_dump(mode="json")
            | {
                "context_request": context,
                "operator_audit": template.operator_audit.model_dump(mode="json")
                | {"operator_id": origin.actor_id},
            },
            "request_sha256",
        )
    )
    return request, build_private_chat_query_submission_context(request, origin)


def definition(connection, request):
    connection.execute(
        insert(WorkflowDefinitionRecord)
        .values(
            definition_id="wfdef_" + uuid4().hex,
            definition_key=KEY,
            definition_version=request.workflow_definition_version,
            schema_version="1.3",
            canonical_definition={"fixture_kind": "INACTIVE_PRIVATE_SUCCESSOR_GUARD_ONLY"},
            definition_hash=request.workflow_definition_sha256,
            active=False,
            source_path="synthetic/private2-storage-guard",
        )
        .on_conflict_do_nothing(constraint="uq_workflow_definition_key_version")
    )
    row = (
        connection.execute(
            select(WorkflowDefinitionRecord.__table__).where(
                WorkflowDefinitionRecord.definition_key == KEY,
                WorkflowDefinitionRecord.definition_version == request.workflow_definition_version,
            )
        )
        .mappings()
        .one()
    )
    assert row["active"] is False and row["definition_hash"] == request.workflow_definition_sha256
    return row["definition_id"]


def row(definition_id, request, context):
    value = legacy_row(definition_id, request, context)
    value.update(
        definition_version=request.workflow_definition_version,
        role_schema_version={"1.0.0": "private-chat-query/1.0", "2.0.0": "private-chat-query/2.0"}[
            request.workflow_definition_version
        ],
    )
    return value


def guards(connection):
    return tuple(
        connection.execute(
            text(
                "SELECT conname,pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid IN "
                "('workflow_instances'::regclass,'workflow_step_runs'::regclass) "
                "AND conname IN ('ck_workflow_instances_private_query_context',"
                "'ck_workflow_step_runs_local_embedding') ORDER BY conname"
            )
        ).all()
    )


def test_successor_migration_roundtrip_preserves_original_index_and_triggers(
    stage_owner_connection, monkeypatch
):
    connection = stage_owner_connection
    assert (
        connection.scalar(
            text(
                "SELECT count(*) FROM workflow_instances "
                "WHERE role_schema_version='private-chat-query/2.0'"
            )
        )
        == 0
    )
    index = connection.scalar(
        text("SELECT to_regclass(:name)::oid"), {"name": PRIVATE_CHAT_QUERY_TURN_INDEX}
    )
    triggers = tuple(
        connection.execute(
            text(
                "SELECT tgname,pg_get_triggerdef(oid) FROM pg_trigger "
                "WHERE tgrelid='workflow_instances'::regclass AND NOT tgisinternal ORDER BY tgname"
            )
        ).all()
    )
    before = guards(connection)
    migration = public_query_migration()
    monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
    migration.downgrade()
    migration.upgrade()
    assert guards(connection) == before
    assert (
        connection.scalar(
            text("SELECT to_regclass(:name)::oid"), {"name": PRIVATE_CHAT_QUERY_TURN_INDEX}
        )
        == index
    )
    assert (
        tuple(
            connection.execute(
                text(
                    "SELECT tgname,pg_get_triggerdef(oid) FROM pg_trigger "
                    "WHERE tgrelid='workflow_instances'::regclass "
                    "AND NOT tgisinternal ORDER BY tgname"
                )
            ).all()
        )
        == triggers
    )


def test_private2_metadata_roundtrips_and_rolls_back_interrupted_creation_without_rekey(
    stage_owner_connection,
):
    connection = stage_owner_connection
    request, context = case()
    value = row(definition(connection, request), request, context)
    with pytest.raises(InterruptedError), connection.begin_nested():
        connection.execute(insert(WorkflowInstanceRecord).values(**value))
        raise InterruptedError("synthetic-after-flush-interruption")
    assert (
        connection.scalar(
            select(WorkflowInstanceRecord.workflow_id).where(
                WorkflowInstanceRecord.idempotency_key == value["idempotency_key"]
            )
        )
        is None
    )
    connection.execute(insert(WorkflowInstanceRecord).values(**value))
    saved = (
        connection.execute(
            select(WorkflowInstanceRecord.__table__).where(
                WorkflowInstanceRecord.idempotency_key == value["idempotency_key"]
            )
        )
        .mappings()
        .one()
    )
    assert (
        saved["workflow_id"] == value["workflow_id"]
        and saved["request_hash"] == value["request_hash"]
    )
    assert parse_supported_private_chat_query_workflow_request(saved["initial_request"]) == request
    assert parse_private_chat_query_submission_context(saved["runtime_context"]) == context


@pytest.mark.parametrize(
    "fault",
    (
        "role1",
        "definition1",
        "request1",
        "context1",
        "declared_version",
        "definition_hash",
        "audit_actor",
        "actor",
        "basis",
        "extra",
    ),
)
def test_db_requires_correlated_version_protocol_request_and_original_origin(
    stage_owner_connection, fault
):
    connection = stage_owner_connection
    request, context = case()
    value = row(definition(connection, request), request, context)
    if fault == "role1":
        value["role_schema_version"] = "private-chat-query/1.0"
    elif fault == "definition1":
        value["definition_version"] = "1.0.0"
    elif fault == "request1":
        value["initial_request"]["schema_version"] = "private-chat-query-workflow-request/1.0"
    elif fault == "context1":
        value["initial_request"]["context_request"]["schema_version"] = (
            "system-rag-private-chat-similarity-request/1.0"
        )
    elif fault == "declared_version":
        value["initial_request"]["workflow_definition_version"] = "1.0.0"
    elif fault == "definition_hash":
        value["initial_request"]["workflow_definition_sha256"] = "sha256:" + "f" * 64
    elif fault == "audit_actor":
        value["initial_request"]["operator_audit"]["operator_id"] = "operator_" + "f" * 32
    elif fault == "actor":
        value["created_actor_id"] = "operator_" + "f" * 32
    elif fault == "basis":
        value["runtime_context"]["origin"]["basis"]["turn_id"] = "chatturn_" + "f" * 32
    else:
        value["runtime_context"]["authority"] = "ADMIN"
    value["request_payload"] = deepcopy(value["initial_request"])
    with pytest.raises(IntegrityError) as error, connection.begin_nested():
        connection.execute(insert(WorkflowInstanceRecord).values(**value))
    assert (
        error.value.orig.sqlstate == "23514"
        and error.value.orig.diag.constraint_name == PRIVATE_CHAT_QUERY_CONTEXT_CHECK
    )


@pytest.mark.parametrize(
    "field",
    (
        "initial_request",
        "runtime_context",
        "created_actor_id",
        "definition_version",
        "role_schema_version",
        "delete",
    ),
)
def test_successor_cannot_rewrite_original_snapshot_or_origin(stage_owner_connection, field):
    connection = stage_owner_connection
    request, context = case()
    value = row(definition(connection, request), request, context)
    connection.execute(insert(WorkflowInstanceRecord).values(**value))
    table = WorkflowInstanceRecord.__table__
    bad = (
        "operator_" + "f" * 32
        if field == "created_actor_id"
        else "invalid"
        if field in {"definition_version", "role_schema_version"}
        else {}
    )
    statement = table.delete() if field == "delete" else table.update().values({field: bad})
    with pytest.raises(DBAPIError), connection.begin_nested():
        connection.execute(statement.where(table.c.workflow_id == value["workflow_id"]))
    assert connection.scalar(
        select(WorkflowInstanceRecord.initial_request).where(
            table.c.workflow_id == value["workflow_id"]
        )
    ) == request.model_dump(mode="json")


def test_new_history_prevents_downgrade_before_any_constraint_changes(
    stage_owner_connection, monkeypatch
):
    connection = stage_owner_connection
    request, context = case()
    connection.execute(
        insert(WorkflowInstanceRecord).values(
            **row(definition(connection, request), request, context)
        )
    )
    before = guards(connection)
    migration = public_query_migration()
    monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
    with pytest.raises(DBAPIError, match="absent successor history"), connection.begin_nested():
        migration.downgrade()
    assert guards(connection) == before


@pytest.mark.parametrize(
    "fault", (None, "agent", "worker_role", "reference_key", "attempt2", "legacy_schema")
)
def test_postgres_common_query2_step_is_only_the_exact_private_application_tuple(
    stage_owner_connection, fault
):
    connection = stage_owner_connection
    request, context = case()
    value = row(definition(connection, request), request, context)
    connection.execute(insert(WorkflowInstanceRecord).values(**value))
    step = dict(
        step_run_id="steprun_" + uuid4().hex,
        workflow_id=value["workflow_id"],
        step_key="encode_private_chat_query",
        attempt=1,
        step_type="application",
        worker_role=None,
        result_schema="embedding-reference-query-result@2.0",
        state="READY",
        platform_job_id=None,
        input_pointer_manifest={"fixture_kind": "INACTIVE_PRIVATE_STEP_ONLY"},
    )
    if fault == "agent":
        step["step_type"] = "agent"
    elif fault == "worker_role":
        step["worker_role"] = "reviewer"
    elif fault == "reference_key":
        step["step_key"] = "encode_reference_query"
    elif fault == "attempt2":
        step["attempt"] = 2
    elif fault == "legacy_schema":
        step["result_schema"] = "embedding-reference-query-result@1.0"
    if fault is None:
        connection.execute(insert(WorkflowStepRunRecord).values(**step))
    else:
        with pytest.raises(IntegrityError) as error, connection.begin_nested():
            connection.execute(insert(WorkflowStepRunRecord).values(**step))
        assert error.value.orig.sqlstate == "23514"
        assert error.value.orig.diag.constraint_name == "ck_workflow_step_runs_local_embedding"


@pytest.mark.parametrize("kinds", ((2, 2), (1, 2)))
def test_original_turn_uniqueness_is_shared_across_versions_even_with_different_keys(
    guarded_engine, kinds
):
    engine = guarded_engine
    first = case(kinds[0])
    second = case(kinds[1], origin=first[1].origin)
    with engine.begin() as connection:
        rows = tuple(
            row(definition(connection, request), request, context)
            for request, context in (first, second)
        )
    for value in rows:
        # Failed synthetic metadata isolates the permanent turn index from the
        # separate active-request hash index. No real history changes state.
        value.update(state="FAILED", stage="FAILED", failure_code="SYNTHETIC_GUARD_ONLY")
    assert rows[0]["idempotency_key"] != rows[1]["idempotency_key"]
    barrier = Barrier(2)

    def create(value):
        barrier.wait(timeout=15)
        try:
            with engine.begin() as connection:
                connection.execute(insert(WorkflowInstanceRecord).values(**value))
            return "SAVED"
        except IntegrityError as error:
            assert (
                error.orig.sqlstate == "23505"
                and error.orig.diag.constraint_name == PRIVATE_CHAT_QUERY_TURN_INDEX
            )
            return "DUPLICATE"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(create, rows))
    assert sorted(outcomes) == ["DUPLICATE", "SAVED"]
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT count(*) FROM workflow_instances WHERE created_actor_id=:actor"),
                {"actor": first[1].origin.actor_id},
            )
            == 1
        )
