"""Synthetic Workflow/Chat/IAM metadata with actual ORM roots and control files.

SQLite is not DB guard proof. No private compiler, step admission, model or unit
is activated; the guarded PostgreSQL inventory owns persistence acceptance.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.models import Base
from eom_workflow.admission import workflow_definition_is_admitted
from eom_workflow.private_chat_query_execution import PrivateChatQueryWorkflowRequest
from eom_workflow.private_chat_query_submission_context import (
    build_private_chat_query_submission_context,
    private_chat_query_submission_fingerprint,
    private_chat_query_submission_key,
)
from eom_workflow.private_chat_query_workflow import PrivateChatQueryWorkflowDefinition
from eom_workflow_runner import native_workflow_transaction as transaction_module
from eom_workflow_runner.errors import WorkflowError
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.private_chat_query_owner_admission import (
    PRIVATE_CHAT_QUERY_SUBMISSION_SOURCE,
    CatalogPrivateChatQueryOwnerAdmission,
    validate_private_chat_query_workflow_submission,
)
from eom_workflow_runner.repository import (
    CommandLeaseIdentity,
    CommandType,
    command_business_fingerprint,
)
from sqlalchemy import select
from sqlalchemy.orm.attributes import set_committed_value

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_private_chat_query_basis import TEXT
from tests.unit.test_private_chat_query_source_owner import make_private_source_case
from tests.unit.test_private_chat_query_workflow import definition_body


def seed_owner_rows(publisher, request, origin):
    """Declared fixtures only; source/private definition admission is not inferred."""
    fixed = PrivateChatQueryWorkflowDefinition.model_validate(definition_body())
    digest = sha256_bytes(canonical_json_bytes(fixed))
    request = PrivateChatQueryWorkflowRequest.model_validate(
        seal(
            request.model_dump(mode="json") | {"workflow_definition_sha256": digest},
            "request_sha256",
        )
    )
    context = build_private_chat_query_submission_context(request, origin)
    workflow_id = "workflow_" + uuid4().hex
    definition_id = "wfdef_" + uuid4().hex
    command_id = "wfcmd_" + uuid4().hex
    with publisher.sessions.begin() as session:
        # Reuse one immutable fixed definition in a shared disposable database.
        definition = session.scalar(
            select(WorkflowDefinitionRecord).where(
                WorkflowDefinitionRecord.definition_key == fixed.definition_key,
                WorkflowDefinitionRecord.definition_version == fixed.definition_version,
            )
        )
        if definition is None:
            definition = WorkflowDefinitionRecord(
                definition_id=definition_id,
                definition_key=fixed.definition_key,
                definition_version=fixed.definition_version,
                schema_version=fixed.schema_version,
                canonical_definition=fixed.model_dump(mode="json"),
                definition_hash=digest,
                active=True,
                source_path="synthetic/not-admitted-private-runner",
            )
            session.add(definition)
            session.flush()
        assert definition.active is True and definition.definition_hash == digest
        workflow = WorkflowInstanceRecord(
            workflow_id=workflow_id,
            definition_id=definition.definition_id,
            definition_key=fixed.definition_key,
            definition_version=fixed.definition_version,
            definition_hash=digest,
            protocol_version="1.0.1",
            role_schema_version="private-chat-query/1.0",
            state="REQUESTED",
            stage="LOCAL_EMBEDDING",
            current_step_key=fixed.start_step,
            request_payload=request.model_dump(mode="json"),
            initial_request=request.model_dump(mode="json"),
            runtime_context=context.model_dump(mode="json"),
            idempotency_key=private_chat_query_submission_key(context),
            request_hash=private_chat_query_submission_fingerprint(
                request,
                context,
                definition_sha256=digest,
                actor_type="human",
                actor_id=origin.actor_id,
            ),
            lock_version=1,
            rework_cycle_count=0,
            created_actor_type="human",
            created_actor_id=origin.actor_id,
        )
        command = WorkflowCommandRecord(
            command_id=command_id,
            workflow_id=workflow_id,
            command_type=CommandType.START_WORKFLOW.value,
            payload={},
            actor_type="human",
            actor_id=origin.actor_id,
            source=PRIVATE_CHAT_QUERY_SUBMISSION_SOURCE,
            idempotency_key=f"start:{workflow_id}",
            request_hash=command_business_fingerprint(
                workflow_id=workflow_id,
                command_type=CommandType.START_WORKFLOW,
                payload={},
                actor_type="human",
                actor_id=origin.actor_id,
                source=PRIVATE_CHAT_QUERY_SUBMISSION_SOURCE,
            ),
            state="PENDING",
            attempts=0,
            lease_generation=0,
        )
        session.add(workflow)
        session.flush()
        session.add(command)
    return SimpleNamespace(
        request=request, context=context, workflow_id=workflow_id, command_id=command_id
    )


@pytest.fixture
def declared(tmp_path, monkeypatch):
    fixed = PrivateChatQueryWorkflowDefinition.model_validate(definition_body())
    source = make_private_source_case(
        tmp_path, monkeypatch, definition_sha256=sha256_bytes(canonical_json_bytes(fixed))
    )
    Base.metadata.create_all(
        source.publisher.engine,
        tables=[
            WorkflowDefinitionRecord.__table__,
            WorkflowInstanceRecord.__table__,
            WorkflowCommandRecord.__table__,
            WorkflowStepRunRecord.__table__,
        ],
    )
    value = seed_owner_rows(source.publisher, source.request, source.projection.origin)
    value.source = source
    value.owner = CatalogPrivateChatQueryOwnerAdmission(source.owner)
    return value


def rows(value, session):
    value.source.fault.session = session
    workflow = session.get(WorkflowInstanceRecord, value.workflow_id)
    command = session.get(WorkflowCommandRecord, value.command_id)
    assert workflow is not None and command is not None
    return workflow, command


def test_fresh_original_claim_rechecks_real_controls_and_actual_source_port(declared):
    value = declared
    with value.source.publisher.sessions.begin() as session:
        workflow, command = rows(value, session)
        root = session.get_transaction()
        resolved = value.owner.resolve_claim(
            session, workflow=workflow, command=command, request=value.request
        )
        assert resolved.projection.origin == value.context.origin and TEXT not in repr(resolved)
        assert session.get_transaction() is root and not session.new and not session.dirty
        assert command.state == "PENDING" and command.attempts == 0
    assert not workflow_definition_is_admitted("local-embedding-private-chat-query", "1.0.0")


@pytest.mark.parametrize("fault", ("claim", "public_during_private_auth", "producer"))
def test_current_chat_public_or_producer_changes_refuse_original_claim(declared, fault):
    value = declared
    with value.source.publisher.sessions.begin() as session:
        workflow, command = rows(value, session)
        value.source.fault.value = fault
        with pytest.raises(SimilarityContextReadError) as error:
            value.owner.resolve_claim(
                session, workflow=workflow, command=command, request=value.request
            )
        assert TEXT not in str(error.value) and command.state == "PENDING"


@pytest.mark.parametrize(
    "field,value",
    (
        ("request_hash", "sha256:" + "f" * 64),
        ("idempotency_key", "another-original-key"),
        ("created_actor_id", "operator_" + "f" * 32),
        ("runtime_context", {}),
        ("request_payload", {}),
        ("role_schema_version", "reference-query/1.0"),
    ),
)
def test_current_row_replay_mismatches_fail_before_source_io(declared, field, value):
    with declared.source.publisher.sessions.begin() as session:
        workflow, _ = rows(declared, session)
        # Simulated corrupted SQL read; no protected row is rewritten or committed.
        set_committed_value(workflow, field, value)
        before = len(declared.source.events)
        with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_WORKFLOW_CONTEXT_INVALID"):
            validate_private_chat_query_workflow_submission(session, workflow, declared.request)
        assert len(declared.source.events) == before


@pytest.mark.parametrize(
    "field,value",
    (
        ("source", "reference_query_submission"),
        ("actor_id", "operator_" + "f" * 32),
        ("payload", {"authority": "ADMIN"}),
        ("command_type", "ADVANCE_WORKFLOW"),
        ("request_hash", "sha256:" + "f" * 64),
    ),
)
def test_other_command_identity_cannot_borrow_private_origin(declared, field, value):
    with declared.source.publisher.sessions.begin() as session:
        workflow, command = rows(declared, session)
        set_committed_value(command, field, value)
        with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_COMMAND_CONTEXT_INVALID"):
            declared.owner.resolve_claim(
                session, workflow=workflow, command=command, request=declared.request
            )


def test_expired_original_without_allocation_cannot_invent_a_new_attempt(declared):
    with declared.source.publisher.sessions.begin() as session:
        workflow, command = rows(declared, session)
        for key, value in {
            "state": "PROCESSING",
            "attempts": 1,
            "lease_generation": 1,
            "lease_owner": "old",
            "lease_token": "wflease_" + "e" * 32,
            "lease_expires_at": datetime.now(UTC) - timedelta(seconds=1),
        }.items():
            set_committed_value(command, key, value)
        with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_ORIGINAL_EXECUTION_MISSING"):
            declared.owner.resolve_claim(
                session, workflow=workflow, command=command, request=declared.request
            )


def test_pending_caller_write_is_denied_before_autoflush_or_source_io(declared):
    with declared.source.publisher.sessions.begin() as session:
        workflow, command = rows(declared, session)
        command.state = "FAILED"
        before = len(declared.source.events)
        with pytest.raises(SimilarityContextReadError, match="AUTHORITY_UNAVAILABLE"):
            declared.owner.resolve_claim(
                session, workflow=workflow, command=command, request=declared.request
            )
        assert len(declared.source.events) == before and session.dirty
        session.rollback()


def test_mutation_without_a_real_acquired_command_fails_closed(declared):
    with declared.source.publisher.sessions.begin() as session:
        rows(declared, session)
        with pytest.raises(WorkflowError, match="ownership was lost"):
            declared.owner.fence_mutation(
                session,
                declared.request,
                CommandLeaseIdentity(declared.command_id, "not-owner", "not-lease", 1),
            )


@pytest.mark.parametrize("state", ("FAILED", "CANCELLED", "COMPLETED", "RUNNING"))
def test_missing_execution_never_restarts_a_non_requested_workflow(declared, state):
    with declared.source.publisher.sessions.begin() as session:
        workflow, command = rows(declared, session)
        set_committed_value(workflow, "state", state)
        with pytest.raises(
            ValueError, match=r"PRIVATE_CHAT_QUERY_(CLAIM_UNAVAILABLE|ORIGINAL_EXECUTION_MISSING)"
        ):
            declared.owner.resolve_claim(
                session, workflow=workflow, command=command, request=declared.request
            )


def test_shared_private_root_redacts_invalid_stored_schema_before_source_admission(
    declared, monkeypatch
):
    sentinel = "PRIVATE_UNTRUSTED_METADATA_NOT_FOR_LOGS"
    with declared.source.publisher.sessions.begin() as session:
        workflow, _ = rows(declared, session)
        # SQLite negative fixture only; not an update to a guarded/operating history.
        workflow.initial_request = workflow.initial_request | {"unknown_authority": sentinel}
        workflow.request_payload = workflow.initial_request
    monkeypatch.setattr(
        transaction_module,
        "require_command_lease",
        lambda session, *_a, **_kw: session.get(WorkflowCommandRecord, declared.command_id),
    )
    before = len(declared.source.events)
    with (
        pytest.raises(
            WorkflowError, match="private native mutation original request is invalid"
        ) as error,
        transaction_module.native_fenced_runner_transaction(
            declared.source.publisher.sessions,
            owner=declared.owner,
            workflow_id=declared.workflow_id,
            request=declared.request,
            lease=CommandLeaseIdentity(
                declared.command_id, "synthetic-parse-only", "not-a-grant", 1
            ),
        ),
    ):
        pytest.fail("invalid private request reached the mutation body")
    assert sentinel not in str(error.value) and error.value.__suppress_context__
    assert len(declared.source.events) == before
