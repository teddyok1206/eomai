"""Actual temporary Job/event storage; private source/native/Workflow authority is synthetic."""

from __future__ import annotations

import pytest
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_orchestrator import native_query_job_allocation as allocation
from eom_orchestrator.models import JobEventRecord, JobRecord, ProtocolVersionRecord
from eom_orchestrator.native_query_job_allocation import (
    NativeQueryLaunchError,
    create_native_query_launch,
    native_query_launch_key,
    read_native_query_launch,
)
from eom_orchestrator.native_reference_query_coordinator import native_reference_query_launch_key
from eom_workflow.private_chat_query_execution import PrivateChatQueryWorkflowRequest
from eom_workflow.private_chat_query_publication import PrivateChatQueryLaunchAssociation
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_control_file_set_publication import _publisher
from tests.unit.test_private_chat_query_basis import TEXT
from tests.unit.test_private_chat_query_publication import launch_case
from tests.unit.test_reference_query_execution_contracts import case


@pytest.fixture
def storage(tmp_path):
    publisher, engine = _publisher(tmp_path)
    yield publisher
    engine.dispose()


def test_private_original_job_is_metadata_only_and_exact_replay_never_allocates(storage):
    request, _, _, _, launch = launch_case()
    with storage.sessions.begin() as session:
        assert create_native_query_launch(session, request=request, launch=launch) == launch
    with storage.sessions.begin() as session:
        proposed = launch.model_dump(mode="json") | {"native_launch_job_id": "job_" + "f" * 32}
        replacement = PrivateChatQueryLaunchAssociation.model_validate(
            seal(proposed, "association_sha256")
        )
        assert create_native_query_launch(session, request=request, launch=replacement) == launch
        assert (
            read_native_query_launch(
                session,
                request=request,
                workflow_id=launch.workflow_id,
                step_run_id=launch.step_run_id,
            )
            == launch
        )
        jobs = tuple(session.scalars(select(JobRecord)))
        assert len(jobs) == 1 and jobs[0].job_id == launch.native_launch_job_id
        assert jobs[0].status == "CLAIMED" and jobs[0].worker_slot_id is None
        assert jobs[0].task_type == "native_private_chat_query_launch"
        assert jobs[0].protocol_version == "private-chat-query/1.0"
        assert TEXT.encode() not in canonical_json_bytes(jobs[0].request)
        assert '"text"' not in canonical_json_bytes(jobs[0].request).decode()
        events = tuple(session.scalars(select(JobEventRecord).order_by(JobEventRecord.sequence)))
        assert len(events) == 4 and events[-1].event == "PRIVATE_CHAT_QUERY_NATIVE_LAUNCH"
        assert session.get(ProtocolVersionRecord, "private-chat-query/1.0") is not None


def test_reference_fingerprint_is_unchanged_and_private_has_a_distinct_original_step_key():
    reference, private = case(), launch_case()
    request, _, _, _, launch = private
    old = "native-reference-query:" + content_sha256(
        {
            "workflow_id": reference.launch.workflow_id,
            "step_run_id": reference.launch.step_run_id,
            "attempt": 1,
            "request_sha256": reference.request.request_sha256,
        }
    ).removeprefix("sha256:")
    assert (
        native_reference_query_launch_key(
            reference.launch.workflow_id,
            reference.launch.step_run_id,
            reference.request.request_sha256,
        )
        == old
    )
    assert (
        native_query_launch_key(
            reference.request, reference.launch.workflow_id, reference.launch.step_run_id
        )
        == old
    )
    assert native_query_launch_key(request, launch.workflow_id, launch.step_run_id) != old


def test_changed_private_request_cannot_bypass_original_step_allocation(storage):
    request, _, _, _, launch = launch_case()
    changed = request.model_dump(mode="json") | {
        "operator_audit": request.operator_audit.model_dump(mode="json")
        | {"requester_permissions_sha256": "sha256:" + "e" * 64}
    }
    changed = PrivateChatQueryWorkflowRequest.model_validate(seal(changed, "request_sha256"))
    assert native_query_launch_key(
        request, launch.workflow_id, launch.step_run_id
    ) == native_query_launch_key(changed, launch.workflow_id, launch.step_run_id)
    with storage.sessions.begin() as session:
        create_native_query_launch(session, request=request, launch=launch)
    with (
        storage.sessions.begin() as session,
        pytest.raises(NativeQueryLaunchError, match="HISTORY_INVALID"),
    ):
        read_native_query_launch(
            session, request=changed, workflow_id=launch.workflow_id, step_run_id=launch.step_run_id
        )
    with storage.sessions.begin() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1


@pytest.mark.parametrize(
    "field",
    [
        "basis_sha256",
        "recipe_sha256",
        "workflow_request_sha256",
        "context_request_sha256",
        "resource_profile_sha256",
    ],
)
def test_private_wrong_parent_fails_before_protocol_or_job_writes(storage, field):
    request, _, _, _, launch = launch_case()
    body = launch.model_dump(mode="json") | {field: "sha256:" + "e" * 64}
    altered = PrivateChatQueryLaunchAssociation.model_validate(seal(body, "association_sha256"))
    with storage.sessions.begin() as session, pytest.raises(ValueError):
        create_native_query_launch(session, request=request, launch=altered)
    with storage.sessions.begin() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 0
        assert session.scalar(select(func.count()).select_from(ProtocolVersionRecord)) == 0


def test_private_job_and_protocol_are_rolled_back_with_caller_root(storage):
    request, _, _, _, launch = launch_case()
    with pytest.raises(RuntimeError, match="rollback"), storage.sessions.begin() as session:
        create_native_query_launch(session, request=request, launch=launch)
        raise RuntimeError("rollback")
    with storage.sessions.begin() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 0
        assert session.scalar(select(func.count()).select_from(ProtocolVersionRecord)) == 0


def test_nested_transaction_does_not_supply_allocation_authority(storage):
    request, _, _, _, launch = launch_case()
    with (
        storage.sessions.begin() as session,
        session.begin_nested(),
        pytest.raises(NativeQueryLaunchError, match="ROOT_REQUIRED"),
    ):
        create_native_query_launch(session, request=request, launch=launch)


def test_forged_private_question_field_cannot_be_silently_serialized_or_logged(storage):
    request, _, _, _, launch = launch_case()
    copied = request.model_copy(update={"private_question": "do-not-leak"})
    with storage.sessions.begin() as session, pytest.raises(NativeQueryLaunchError) as error:
        create_native_query_launch(session, request=copied, launch=launch)
    assert str(error.value) == "PRIVATE_CHAT_QUERY_LAUNCH_REQUEST_INVALID"


def test_private_sql_conflict_is_content_free_and_requires_caller_root_rollback(
    storage, monkeypatch
):
    request, _, _, _, launch = launch_case()

    def conflict(*_args, **_kwargs):
        raise IntegrityError("private-sql", {"private": "do-not-leak"}, RuntimeError("detail"))

    monkeypatch.setattr(allocation, "submit_structured_job", conflict)
    with pytest.raises(NativeQueryLaunchError) as error, storage.sessions.begin() as session:
        create_native_query_launch(session, request=request, launch=launch)
    assert str(error.value) == "PRIVATE_CHAT_QUERY_LAUNCH_CONFLICT"
    with storage.sessions.begin() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 0
        assert session.scalar(select(func.count()).select_from(ProtocolVersionRecord)) == 0
