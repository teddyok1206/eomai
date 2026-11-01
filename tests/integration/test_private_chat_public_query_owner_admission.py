"""Actual disposable PG commands/steps/Jobs; source permission is an explicit fake port.

The common Catalog/control/Chat resolver is covered separately. These declared
rows do not activate private2 submission, a real claim, runtime or model.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_catalog_contracts.private_chat_query_read import (
    ChatPrivateQueryOrigin,
    LiveChatQueryProjection,
)
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.models import JobRecord
from eom_orchestrator.native_private_chat_query_coordinator import NativePrivateChatQueryCoordinator
from eom_orchestrator.native_query_job_allocation import create_native_query_launch
from eom_workflow.admission import workflow_definition_is_admitted
from eom_workflow_runner.errors import WorkflowError
from eom_workflow_runner.models import WorkflowInstanceRecord
from eom_workflow_runner.private_chat_query_owner_admission import (
    CatalogPrivateChatQueryOwnerAdmission,
)
from eom_workflow_runner.repository import CommandLeaseIdentity
from sqlalchemy import func, select

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit import test_private_chat_public_query_owner_admission as cases
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_private_chat_public_query_workflow import public_completed as public_completed
from tests.unit.test_private_chat_query_owner_admission import rows, seed_owner_rows
from tests.unit.test_private_chat_query_workflow import completed as completed

pytestmark = pytest.mark.integration


@pytest.fixture
def declared(guarded_engine, tmp_path, monkeypatch):
    original = cases.make_private_public_owner_case(tmp_path, monkeypatch)
    with original.source.publisher.sessions.begin() as session:
        original.source.fault.session = session
        resolved = original.owner.resolve_submission(session, original.request, original.context)
    # One declared actor/turn per case, as in the existing PG metadata suite.
    origin = ChatPrivateQueryOrigin.model_validate(
        seal(
            original.context.origin.model_dump(mode="json")
            | {"actor_id": "operator_" + uuid4().hex},
            "origin_sha256",
        )
    )
    request = type(original.request).model_validate(
        seal(
            original.request.model_dump(mode="json")
            | {
                "operator_audit": original.request.operator_audit.model_dump(mode="json")
                | {"operator_id": origin.actor_id}
            },
            "request_sha256",
        )
    )
    resolved = replace(
        resolved,
        request=request,
        projection=LiveChatQueryProjection.model_validate(
            resolved.projection.model_dump(mode="json") | {"origin": origin.model_dump(mode="json")}
        ),
    )
    publisher = ControlFileSetPublisher(guarded_engine, original.source.publisher.settings)
    source = SimpleNamespace(
        publisher=publisher, fault=SimpleNamespace(session=None, value=None), events=[]
    )

    def resolve(session, supplied_request, supplied_origin):
        assert session.get_bind() is guarded_engine and session.get_transaction().is_active
        assert supplied_request == request and supplied_origin == origin
        assert not session.new and not session.dirty and not session.deleted
        source.events.append("synthetic-current-source")
        if source.fault.value == "deny":
            raise SimilarityContextReadError("SOURCE_REVOKED")
        return resolved

    # Metadata/transaction tests inject the source port explicitly, not fake SQL roles.
    source_owner = SimpleNamespace(
        configuration=original.source.owner.configuration,
        catalog=SimpleNamespace(engine=guarded_engine),
        settings=original.source.owner.settings,
        resolve_sources=resolve,
    )
    value = seed_owner_rows(publisher, request, origin)
    value.source = source
    value.owner = CatalogPrivateChatQueryOwnerAdmission(source_owner)
    return value


def live_lease(value):
    with value.source.publisher.sessions.begin() as session:
        _workflow, command = rows(value, session)
        command.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
        return CommandLeaseIdentity(
            command.command_id, command.lease_owner, command.lease_token, command.lease_generation
        )


def test_postgres_successor_current_owner_claim_is_read_only_without_global_admission(declared):
    with declared.source.publisher.sessions.begin() as session:
        workflow, command = rows(declared, session)
        root = session.get_transaction()
        result = declared.owner.resolve_claim(
            session, workflow=workflow, command=command, request=declared.request
        )
        assert result.request == declared.request
        assert workflow.role_schema_version == "private-chat-query/2.0"
        assert command.state == "PENDING" and command.lease_generation == 0
        assert session.get_transaction() is root and not session.dirty and not session.new
    assert not workflow_definition_is_admitted("local-embedding-private-chat-query", "2.0.0")


def test_postgres_expired_successor_reuses_original_launch_and_checkpoint(
    declared, public_completed
):
    cases.test_successor_expired_claim_reuses_exact_original_allocation_and_checkpoint(
        declared, public_completed
    )


@pytest.mark.parametrize("bad_parent", [False, True])
def test_postgres_successor_continuation_obeys_original_parent_state(
    declared, public_completed, bad_parent
):
    cases.test_successor_continuation_reuses_successful_original_and_rejects_failed_parent(
        declared, public_completed, bad_parent
    )


@pytest.mark.parametrize("fault", ["source", "lease"])
def test_postgres_late_source_or_lease_loss_rolls_back_same_caller_root(
    declared, public_completed, fault
):
    launch = cases.declare_original_allocation(declared, public_completed)
    lease = live_lease(declared)
    with declared.source.publisher.sessions() as session:
        initial = session.get(WorkflowInstanceRecord, declared.workflow_id).lock_version
    error = SimilarityContextReadError if fault == "source" else WorkflowError
    with pytest.raises(error), declared.source.publisher.sessions.begin() as session:
        declared.owner.resolve_mutation_sources(session, declared.request, lease)
        workflow, command = rows(declared, session)
        workflow.lock_version += 1
        if fault == "source":
            declared.source.fault.value = "deny"
        else:
            command.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.flush()
        declared.owner.fence_mutation(session, declared.request, lease)
    with declared.source.publisher.sessions() as session:
        assert session.get(WorkflowInstanceRecord, declared.workflow_id).lock_version == initial
        assert session.get(JobRecord, launch.native_launch_job_id).status == "RUNNING"


def test_postgres_concurrent_same_original_replay_never_creates_another_job(
    declared, public_completed
):
    launch = cases.declare_original_allocation(declared, public_completed)
    lease = live_lease(declared)
    barrier = Barrier(2)

    def replay(_index):
        barrier.wait(timeout=15)
        with declared.source.publisher.sessions.begin() as session:
            declared.owner.resolve_mutation_sources(session, declared.request, lease)
            observed = create_native_query_launch(session, request=declared.request, launch=launch)
            assert (
                len(
                    NativePrivateChatQueryCoordinator(declared.request, observed)
                    .read(session)
                    .records
                )
                == 1
            )
            return observed

    with ThreadPoolExecutor(max_workers=2) as pool:
        observed = tuple(pool.map(replay, range(2)))
    assert observed == (launch, launch)
    with declared.source.publisher.sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobRecord)
                .where(JobRecord.job_id == launch.native_launch_job_id)
            )
            == 1
        )
