"""Real attached rows/control reads; Chat/IAM/document authority remains synthetic.

Read/lease fences for the successor are not global admission or native execution.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.models import Base, JobRecord
from eom_orchestrator.native_private_chat_query_coordinator import NativePrivateChatQueryCoordinator
from eom_orchestrator.native_query_job_allocation import (
    create_native_query_launch,
    read_native_query_launch,
)
from eom_workflow.admission import workflow_definition_is_admitted
from eom_workflow.compiler import compile_definition
from eom_workflow.native_private_chat_query_coordinator import (
    NativePrivateQueryAllocation,
    native_private_chat_public_query_checkpoint,
)
from eom_workflow.native_reference_query_coordinator import NativeQueryAllocation
from eom_workflow.private_chat_query_execution_v2 import PrivateChatQueryWorkflowRequestV2
from eom_workflow.private_chat_query_publication import PrivateChatQueryLaunchAssociation
from eom_workflow.private_chat_query_submission_context import (
    build_private_chat_query_submission_context,
)
from eom_workflow.private_chat_query_workflow_v2 import (
    private_chat_query_result_schema,
    validate_supported_private_chat_query_definition,
)
from eom_workflow_runner.local_embedding_publications import new_native_artifact_producer
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.private_chat_query_command_lineage import (
    PRIVATE_CHAT_QUERY_CONTINUATION_SOURCE,
    private_chat_query_continuation_key,
)
from eom_workflow_runner.private_chat_query_owner_admission import (
    CatalogPrivateChatQueryOwnerAdmission,
    validate_private_chat_query_execution_step,
)
from eom_workflow_runner.private_chat_query_source_read import (
    ResolvedPrivateChatPublicQuerySources,
    build_private_chat_public_query_native_input,
)
from eom_workflow_runner.repository import CommandType, enqueue_command
from sqlalchemy import update
from sqlalchemy.orm.attributes import set_committed_value

from tests.unit import test_private_chat_query_owner_admission as legacy
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_private_chat_public_query_source_owner import make_private_public_source_case
from tests.unit.test_private_chat_public_query_workflow import public_completed as public_completed
from tests.unit.test_private_chat_query_workflow import completed as completed


@pytest.fixture
def declared(tmp_path, monkeypatch):
    return make_private_public_owner_case(tmp_path, monkeypatch)


def make_private_public_owner_case(tmp_path, monkeypatch):
    fixed = compile_definition(
        Path(__file__).resolve().parents[2]
        / "config/workflows/local-embedding-private-chat-query.v2.yaml",
        set(),
    ).definition
    current = make_private_public_source_case(
        tmp_path, monkeypatch, definition_sha256=sha256_bytes(canonical_json_bytes(fixed))
    )
    source = SimpleNamespace(
        publisher=current.old.publisher,
        request=current.request,
        owner=current.owner,
        projection=current.old.projection,
        fault=current.old.fault,
        events=current.old.events,
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
    value = legacy.seed_owner_rows(source.publisher, source.request, source.projection.origin)
    value.source, value.current, value.fixed = source, current, fixed
    value.owner = CatalogPrivateChatQueryOwnerAdmission(source.owner)
    return value


def test_successor_claim_reads_common_sources_without_activating_global_definition(declared):
    with declared.source.publisher.sessions.begin() as session:
        workflow, command = legacy.rows(declared, session)
        result = declared.owner.resolve_claim(
            session, workflow=workflow, command=command, request=declared.request
        )
        assert type(result) is ResolvedPrivateChatPublicQuerySources
        assert workflow.role_schema_version == "private-chat-query/2.0"
        assert result.request == declared.request and len(result.documents.entries) == 3
        assert command.state == "PENDING" and command.lease_generation == 0
        assert not session.dirty and not session.new
    assert not workflow_definition_is_admitted("local-embedding-private-chat-query", "2.0.0")


@pytest.mark.parametrize("fault", ["wrong_family", "retained_request"])
def test_source_port_cannot_return_another_family_or_cached_request(declared, monkeypatch, fault):
    with declared.source.publisher.sessions.begin() as session:
        declared.source.fault.session = session
        resolved = declared.owner.resolve_submission(session, declared.request, declared.context)
        request = declared.request
        context = declared.context
        if fault == "wrong_family":
            resolved = object()
        else:
            private_context = seal(
                request.context_request.model_dump(mode="json") | {"top_k": 6},
                "request_sha256",
            )
            request = PrivateChatQueryWorkflowRequestV2.model_validate(
                seal(
                    request.model_dump(mode="json") | {"context_request": private_context},
                    "request_sha256",
                )
            )
            context = build_private_chat_query_submission_context(request, declared.context.origin)
        monkeypatch.setattr(declared.source.owner, "resolve_sources", lambda *_args: resolved)
        with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_SUBMISSION_CONTEXT_INVALID"):
            declared.owner.resolve_submission(session, request, context)


@pytest.mark.parametrize("fault", ["claim", "public_during_private_auth"])
def test_successor_still_rechecks_current_private_and_public_authority(declared, fault):
    legacy.test_current_chat_public_or_producer_changes_refuse_original_claim(declared, fault)


@pytest.mark.parametrize(
    "field,value",
    [
        ("request_hash", "sha256:" + "f" * 64),
        ("idempotency_key", "foreign-original"),
        ("created_actor_id", "operator_" + "f" * 32),
        ("runtime_context", {}),
        ("request_payload", {}),
        ("role_schema_version", "private-chat-query/1.0"),
        ("definition_version", "1.0.0"),
    ],
)
def test_successor_cannot_relabel_other_row_family_or_payload(declared, field, value):
    legacy.test_current_row_replay_mismatches_fail_before_source_io(declared, field, value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("source", "reference_query_submission"),
        ("payload", {"authority": "ADMIN"}),
        ("command_type", "ADVANCE_WORKFLOW"),
        ("request_hash", "sha256:" + "f" * 64),
    ],
)
def test_reference_or_forged_command_cannot_borrow_successor_origin(declared, field, value):
    legacy.test_other_command_identity_cannot_borrow_private_origin(declared, field, value)


def test_successor_expired_original_without_allocation_never_creates_a_retry(declared):
    legacy.test_expired_original_without_allocation_cannot_invent_a_new_attempt(declared)


def test_successor_pending_write_never_autoflushes_before_source_read(declared):
    legacy.test_pending_caller_write_is_denied_before_autoflush_or_source_io(declared)


def test_successor_failed_control_producer_remains_a_failure(declared):
    with declared.source.publisher.sessions.begin() as session:
        session.execute(
            update(JobRecord)
            .where(JobRecord.job_id == declared.current.saved.owner_job_id)
            .values(status="FAILED")
        )
    with declared.source.publisher.sessions.begin() as session:
        workflow, command = legacy.rows(declared, session)
        with pytest.raises(SimilarityContextReadError, match="SOURCE_POINTER_INVALID"):
            declared.owner.resolve_claim(
                session, workflow=workflow, command=command, request=declared.request
            )


def test_fixed_successor_definition_and_step_choose_only_common_result_schema(declared):
    validate_supported_private_chat_query_definition(declared.fixed, declared.request)
    assert (
        private_chat_query_result_schema(declared.request) == "embedding-reference-query-result@2.0"
    )
    workflow = SimpleNamespace(
        workflow_id=declared.workflow_id,
        state="RUNNING",
        current_step_key="encode_private_chat_query",
    )
    step = SimpleNamespace(
        workflow_id=declared.workflow_id,
        step_key="encode_private_chat_query",
        state="RUNNING",
        step_type="application",
        worker_role=None,
        attempt=1,
        result_schema=private_chat_query_result_schema(declared.request),
        input_pointer_manifest={"workflow_request_sha256": declared.request.request_sha256},
    )
    validate_private_chat_query_execution_step(step, workflow, declared.request)
    step.result_schema = "embedding-private-chat-query-result@1.0"
    with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_CURRENT_STEP_INVALID"):
        validate_private_chat_query_execution_step(step, workflow, declared.request)


def test_private_definition_and_request_families_cannot_be_mixed(declared):
    with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_DEFINITION_FAMILY_MISMATCH"):
        validate_supported_private_chat_query_definition(
            legacy.PrivateChatQueryWorkflowDefinition.model_validate(legacy.definition_body()),
            declared.request,
        )
    with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_DEFINITION_FAMILY_MISMATCH"):
        validate_supported_private_chat_query_definition(
            declared.fixed, declared.current.old.request
        )


@pytest.mark.parametrize("state", ["FAILED", "CANCELLED", "SUCCEEDED"])
def test_successor_terminal_command_is_not_a_fresh_or_expired_claim(declared, state):
    with declared.source.publisher.sessions.begin() as session:
        workflow, command = legacy.rows(declared, session)
        command.state = state
        command.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.flush()
        with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_CLAIM_UNAVAILABLE"):
            declared.owner.resolve_claim(
                session, workflow=workflow, command=command, request=declared.request
            )


def declare_original_allocation(declared, template):
    """Explicit interrupted metadata only; not an executor, scheduler or native grant."""
    with declared.source.publisher.sessions.begin() as session:
        declared.source.fault.session = session
        sources = declared.owner.resolve_submission(session, declared.request, declared.context)
    native = build_private_chat_public_query_native_input(
        sources, job_id="job_" + uuid4().hex, query_request_id="embeddingquery_" + uuid4().hex
    )
    launch = PrivateChatQueryLaunchAssociation.model_validate(
        seal(
            template.launch.model_dump(mode="json")
            | {
                "workflow_id": declared.workflow_id,
                "step_run_id": "steprun_" + uuid4().hex,
                "workflow_request_sha256": declared.request.request_sha256,
                "context_request_sha256": declared.request.context_request.request_sha256,
                "basis_sha256": declared.context.origin.basis.basis_sha256,
                "native_launch_job_id": native.job_id,
                "query_request_id": native.query_request_id,
                "query_request_sha256": native.request_sha256,
                "query_input_set_sha256": native.input_set_sha256,
                "recipe_sha256": native.recipe.recipe_sha256,
                "runtime_bundle": declared.request.runtime_bundle.model_dump(mode="json"),
                "resource_profile_sha256": (
                    declared.request.resource_profile.resource_profile_sha256
                ),
                "original_command_id": declared.command_id,
                "original_command_generation": 1,
            },
            "association_sha256",
        )
    )
    allocation = NativePrivateQueryAllocation(
        allocation=NativeQueryAllocation(
            query_producer=new_native_artifact_producer(),
            receipt_producer=new_native_artifact_producer(),
            created_at=datetime.now(UTC),
            source_commit="a" * 40,
        ),
        origin=declared.context.origin,
    )
    with declared.source.publisher.sessions.begin() as session:
        assert (
            create_native_query_launch(session, request=declared.request, launch=launch) == launch
        )
        NativePrivateChatQueryCoordinator(declared.request, launch).append(
            session,
            native_private_chat_public_query_checkpoint(launch, "ALLOCATION", allocation),
        )
    with declared.source.publisher.sessions.begin() as session:
        workflow, command = legacy.rows(declared, session)
        workflow.state = "RUNNING"
        command.state, command.attempts, command.lease_generation = "PROCESSING", 1, 1
        command.lease_owner, command.lease_token = "synthetic-original", "wflease_" + uuid4().hex
        command.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.add(
            WorkflowStepRunRecord(
                workflow_id=workflow.workflow_id,
                step_run_id=launch.step_run_id,
                step_key="encode_private_chat_query",
                attempt=1,
                state="RUNNING",
                step_type="application",
                worker_role=None,
                result_schema=private_chat_query_result_schema(declared.request),
                input_pointer_manifest={"workflow_request_sha256": declared.request.request_sha256},
            )
        )
    return launch


def test_successor_expired_claim_reuses_exact_original_allocation_and_checkpoint(
    declared, public_completed
):
    launch = declare_original_allocation(declared, public_completed)
    with declared.source.publisher.sessions.begin() as session:
        workflow, command = legacy.rows(declared, session)
        # SQLite drops timezone metadata; production PostgreSQL retains UTC.
        if command.lease_expires_at.tzinfo is None:
            set_committed_value(
                command, "lease_expires_at", command.lease_expires_at.replace(tzinfo=UTC)
            )
        result = declared.owner.resolve_claim(
            session, workflow=workflow, command=command, request=declared.request
        )
        assert result.projection.origin == declared.context.origin
        assert (
            read_native_query_launch(
                session,
                request=declared.request,
                workflow_id=workflow.workflow_id,
                step_run_id=launch.step_run_id,
            )
            == launch
        )
        history = NativePrivateChatQueryCoordinator(declared.request, launch).read(session)
        assert len(history.records) == 1 and history.state == "RUNNING"
        assert not session.new and not session.dirty


@pytest.mark.parametrize("bad_parent", [False, True])
def test_successor_continuation_reuses_successful_original_and_rejects_failed_parent(
    declared, public_completed, bad_parent
):
    launch = declare_original_allocation(declared, public_completed)
    with declared.source.publisher.sessions.begin() as session:
        workflow, original = legacy.rows(declared, session)
        original.state = "FAILED" if bad_parent else "SUCCEEDED"
        command, _created = enqueue_command(
            session,
            workflow_id=workflow.workflow_id,
            command_type=CommandType.ADVANCE_WORKFLOW,
            payload={"step_run_id": launch.step_run_id},
            actor_type="human",
            actor_id=declared.context.origin.actor_id,
            source=PRIVATE_CHAT_QUERY_CONTINUATION_SOURCE,
            idempotency_key=private_chat_query_continuation_key(
                launch.step_run_id, original.command_id
            ),
        )
        command_id = command.command_id
    with declared.source.publisher.sessions.begin() as session:
        workflow, _original = legacy.rows(declared, session)
        command = session.get(WorkflowCommandRecord, command_id)
        if bad_parent:
            before = len(declared.source.events)
            with pytest.raises(
                ValueError, match="PRIVATE_CHAT_QUERY_CONTINUATION_PARENT_UNAVAILABLE"
            ):
                declared.owner.resolve_claim(
                    session, workflow=workflow, command=command, request=declared.request
                )
            assert len(declared.source.events) == before
        else:
            result = declared.owner.resolve_claim(
                session, workflow=workflow, command=command, request=declared.request
            )
            assert result.projection.origin == declared.context.origin
        assert (
            len(NativePrivateChatQueryCoordinator(declared.request, launch).read(session).records)
            == 1
        )
