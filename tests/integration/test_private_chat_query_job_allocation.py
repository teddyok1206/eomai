"""Guarded PostgreSQL original Job allocation; Workflow/source/native authority is synthetic."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from eom_catalog_contracts.embedding_private_chat_query import EmbeddingPrivateChatQueryInput
from eom_identifiers import canonical_json_bytes
from eom_orchestrator import native_query_job_allocation as allocation
from eom_orchestrator.models import JobEventRecord, JobRecord
from eom_workflow.private_chat_query_execution import PrivateChatQueryWorkflowRequest
from eom_workflow.private_chat_query_publication import (
    PrivateChatQueryLaunchAssociation,
    validate_private_chat_query_launch,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_private_chat_query_basis import TEXT
from tests.unit.test_private_chat_query_publication import launch_case
from tests.unit.test_reference_query_execution_contracts import case

pytestmark = pytest.mark.integration


@pytest.fixture
def private_launch():
    request, policy, bundle, native, launch = launch_case()
    native = EmbeddingPrivateChatQueryInput.model_validate(
        seal(
            native.model_dump(mode="json")
            | {
                "job_id": "job_" + uuid4().hex,
                "query_request_id": "embeddingquery_" + uuid4().hex,
            },
            "request_sha256",
        )
    )
    body = launch.model_dump(mode="json") | {
        "workflow_id": "workflow_" + uuid4().hex,
        "step_run_id": "steprun_" + uuid4().hex,
        "original_command_id": "wfcmd_" + uuid4().hex,
        "native_launch_job_id": native.job_id,
        "query_request_id": native.query_request_id,
        "query_request_sha256": native.request_sha256,
    }
    launch = PrivateChatQueryLaunchAssociation.model_validate(seal(body, "association_sha256"))
    validate_private_chat_query_launch(launch, request, policy, bundle, native)
    return request, launch


def test_postgres_exact_private_job_replay_is_text_free_and_single(guarded_engine, private_launch):
    request, launch = private_launch
    with Session(guarded_engine) as session, session.begin():
        assert (
            allocation.create_native_query_launch(session, request=request, launch=launch) == launch
        )
    with Session(guarded_engine) as session, session.begin():
        assert (
            allocation.create_native_query_launch(session, request=request, launch=launch) == launch
        )
        job = session.get(JobRecord, launch.native_launch_job_id)
        assert job is not None and job.status == "CLAIMED" and job.worker_slot_id is None
        assert TEXT.encode() not in canonical_json_bytes(job.request)
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobEventRecord)
                .where(
                    JobEventRecord.job_id == job.job_id,
                    JobEventRecord.event == "PRIVATE_CHAT_QUERY_NATIVE_LAUNCH",
                )
            )
            == 1
        )


def test_postgres_caller_rollback_removes_only_its_uncommitted_launch(
    guarded_engine, private_launch
):
    request, launch = private_launch
    with (
        pytest.raises(RuntimeError, match="rollback"),
        Session(guarded_engine) as session,
        session.begin(),
    ):
        allocation.create_native_query_launch(session, request=request, launch=launch)
        raise RuntimeError("rollback")
    with Session(guarded_engine) as session:
        assert session.get(JobRecord, launch.native_launch_job_id) is None
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobEventRecord)
                .where(
                    JobEventRecord.job_id == launch.native_launch_job_id,
                )
            )
            == 0
        )


def test_postgres_two_original_allocators_cannot_commit_duplicate_jobs(
    guarded_engine, private_launch, monkeypatch
):
    request, launch = private_launch
    first_read = allocation.read_native_query_launch
    barrier = Barrier(2)

    def racing_read(session, **kwargs):
        result = first_read(session, **kwargs)
        if result is None:
            barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(allocation, "read_native_query_launch", racing_read)
    alternative = PrivateChatQueryLaunchAssociation.model_validate(
        seal(
            launch.model_dump(mode="json") | {"native_launch_job_id": "job_" + uuid4().hex},
            "association_sha256",
        )
    )

    def run(proposed):
        try:
            with Session(guarded_engine) as session, session.begin():
                return allocation.create_native_query_launch(
                    session, request=request, launch=proposed
                )
        except allocation.NativeQueryLaunchError as error:
            assert str(error) in {
                "PRIVATE_CHAT_QUERY_LAUNCH_RACE_UNRECONCILED",
                "PRIVATE_CHAT_QUERY_LAUNCH_CONFLICT",
            }
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = tuple(pool.map(run, (launch, alternative)))
    winners = tuple(value for value in result if value is not None)
    assert len(winners) == 1
    with Session(guarded_engine) as session, session.begin():
        key = allocation.native_query_launch_key(request, launch.workflow_id, launch.step_run_id)
        assert (
            session.scalar(
                select(func.count()).select_from(JobRecord).where(JobRecord.idempotency_key == key)
            )
            == 1
        )
        assert (
            first_read(
                session,
                request=request,
                workflow_id=launch.workflow_id,
                step_run_id=launch.step_run_id,
            )
            == winners[0]
        )


def test_postgres_changed_private_intent_cannot_create_a_new_original_step(
    guarded_engine, private_launch
):
    request, launch = private_launch
    with Session(guarded_engine) as session, session.begin():
        allocation.create_native_query_launch(session, request=request, launch=launch)
    changed = PrivateChatQueryWorkflowRequest.model_validate(
        seal(
            request.model_dump(mode="json")
            | {
                "operator_audit": request.operator_audit.model_dump(mode="json")
                | {
                    "requester_permissions_sha256": "sha256:" + "e" * 64,
                },
            },
            "request_sha256",
        )
    )
    with (
        Session(guarded_engine) as session,
        session.begin(),
        pytest.raises(allocation.NativeQueryLaunchError, match="HISTORY_INVALID"),
    ):
        allocation.read_native_query_launch(
            session, request=changed, workflow_id=launch.workflow_id, step_run_id=launch.step_run_id
        )


def test_postgres_reference_launch_cannot_be_stored_under_private_purpose(
    guarded_engine, private_launch
):
    request, _ = private_launch
    foreign = case().launch
    with (
        Session(guarded_engine) as session,
        session.begin(),
        pytest.raises(allocation.NativeQueryLaunchError, match="REQUEST_INVALID"),
    ):
        allocation.create_native_query_launch(session, request=request, launch=foreign)
