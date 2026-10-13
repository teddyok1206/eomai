"""Native coordinator allocation/history in a disposable local DB, never runtime authority."""

from __future__ import annotations

from pathlib import Path

import pytest
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.embedding_encoding_reservation_storage import ENCODING_PROTOCOL_VERSION
from eom_orchestrator.models import JobEventRecord, JobRecord, ProtocolVersionRecord
from eom_orchestrator.native_embedding_launch_identity import (
    create_native_embedding_launch,
    native_embedding_launch_key,
    require_native_embedding_launch,
)
from eom_workflow.schemas import LOCAL_EMBEDDING_SCHEMA_RESOURCES
from sqlalchemy import func, select

from tests.unit.local_embedding_admission_fixtures import native_fixture
from tests.unit.test_control_file_set_publication import _publisher


@pytest.fixture
def coordinator(tmp_path: Path):
    fixture = native_fixture()
    publisher, _engine = _publisher(tmp_path)
    with publisher.sessions.begin() as session:
        session.add(
            ProtocolVersionRecord(
                version=ENCODING_PROTOCOL_VERSION,
                schema_sha256=next(
                    row[3] for row in LOCAL_EMBEDDING_SCHEMA_RESOURCES if row[0] == "encoding-job"
                ),
            )
        )
    intent = fixture.association.intent
    args = dict(
        request=fixture.request,
        workflow_id=intent.workflow_id,
        step_run_id=intent.step_run_id,
        command_id=intent.command_id,
        runner_id=intent.runner_id,
        lease_generation=intent.lease_generation,
    )
    return publisher, args


def test_key_matches_existing_length_limit_and_pins_whole_context() -> None:
    fixture = native_fixture()
    intent = fixture.association.intent
    first = native_embedding_launch_key(
        intent.workflow_id, intent.step_run_id, fixture.request.request_sha256
    )
    assert len(first) <= 128
    assert (
        native_embedding_launch_key(
            intent.workflow_id, intent.step_run_id, fixture.request.request_sha256
        )
        == first
    )
    assert (
        native_embedding_launch_key(
            "workflow_" + "f" * 32, intent.step_run_id, fixture.request.request_sha256
        )
        != first
    )


def test_one_job_and_original_intent_survive_new_command_generation_without_new_allocation(
    coordinator,
) -> None:
    publisher, args = coordinator
    with publisher.sessions.begin() as session:
        original = create_native_embedding_launch(session, **args)
        assert original.state == "CLAIMED"
    with publisher.sessions.begin() as session:
        replay = create_native_embedding_launch(
            session,
            **(
                args
                | {
                    "command_id": "wfcmd_" + "e" * 32,
                    "runner_id": "new-synthetic-runner",
                    "lease_generation": 2,
                }
            ),
        )
        assert replay == original
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
        rows = tuple(session.scalars(select(JobEventRecord)))
        assert len(rows) == 4
        job = session.scalar(select(JobRecord))
        raw = canonical_json_bytes(job.request)
        assert b'"text"' not in raw and b'"rows"' not in raw
        assert job.worker_slot_id is None


@pytest.mark.parametrize("fault", ("hash", "request", "task", "slot", "intent"))
def test_wrong_context_does_not_replay_or_allocate_another_job(coordinator, fault: str) -> None:
    publisher, args = coordinator
    with publisher.sessions.begin() as session:
        original = create_native_embedding_launch(session, **args)
    with publisher.sessions.begin() as session:
        job = session.get(JobRecord, original.intent.native_launch_job_id)
        if fault == "hash":
            job.request_hash = "sha256:" + "f" * 64
        if fault == "request":
            job.request = {"wrong": "synthetic metadata"}
        if fault == "task":
            job.task_type = "native_embedding_encoding"
        if fault == "slot":
            job.worker_slot_id = "01"
        if fault == "intent":
            event = session.scalar(
                select(JobEventRecord).where(
                    JobEventRecord.event == "EMBEDDING_NATIVE_LAUNCH_INTENT"
                )
            )
            event.data = {"wrong": "synthetic intent"}
    with publisher.sessions.begin() as session, pytest.raises((ValueError, RuntimeError)):
        require_native_embedding_launch(session, original.intent, args["request"])
    with publisher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1


@pytest.mark.parametrize("state", ("absent", "savepoint"))
def test_coordinator_does_not_autobegin_or_use_unfenced_nested_root(
    coordinator, state: str
) -> None:
    publisher, args = coordinator
    with publisher.sessions() as session:
        if state == "savepoint":
            session.begin()
            session.begin_nested()
        with pytest.raises(RuntimeError, match="OWNER_ROOT_REQUIRED"):
            create_native_embedding_launch(session, **args)
