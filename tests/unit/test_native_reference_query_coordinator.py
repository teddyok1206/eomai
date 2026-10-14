"""Actual temporary SQLite history and closed contracts; synthetic unit/IAM values."""

from datetime import timedelta
from pathlib import Path

import pytest
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.models import JobEventRecord, JobRecord, ProtocolVersionRecord
from eom_orchestrator.native_reference_query_coordinator import (
    NativeReferenceQueryCoordinator,
    create_native_reference_query_launch,
    native_reference_query_launch_key,
    read_native_reference_query_launch,
)
from eom_orchestrator.state_machine import JobState, transition_job
from eom_workflow.native_reference_query_coordinator import (
    native_reference_query_checkpoint,
    parse_native_reference_query_checkpoint,
    validate_native_reference_query_history,
)
from eom_workflow.reference_query_execution import parse_reference_query_launch_association
from eom_workflow.schemas import (
    NATIVE_REFERENCE_QUERY_COORDINATOR_SCHEMA_RESOURCE,
    load_native_reference_query_coordinator_schema,
)
from sqlalchemy import func, select

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.native_reference_query_coordinator_fixtures import query_records
from tests.unit.test_control_file_set_publication import _publisher
from tests.unit.test_reference_query_execution_contracts import case


def test_schema_exact_mirror_pinned_hash_and_isolated_public_copy():
    root = Path(__file__).resolve().parents[2]
    filename, schema_id, digest = NATIVE_REFERENCE_QUERY_COORDINATOR_SCHEMA_RESOURCE
    raw = (root / "schemas/workflow" / filename).read_bytes()
    assert raw == (root / "packages/workflow/eom_workflow/resources" / filename).read_bytes()
    assert sha256_bytes(raw) == digest
    document = load_native_reference_query_coordinator_schema()
    assert document["$id"] == schema_id
    document["type"] = "null"
    assert load_native_reference_query_coordinator_schema()["type"] == "object"


def test_small_metadata_only_and_every_contiguous_prefix():
    value = case()
    records = query_records(value)
    for record in records:
        assert parse_native_reference_query_checkpoint(record) == record
        assert parse_native_reference_query_checkpoint(record.model_dump(mode="json")) == record
        raw = canonical_json_bytes(record.model_dump(mode="json"))
        assert len(raw) < 16 * 1024
        assert all(
            token not in raw for token in (b'"text"', b'"vectors"', b'"path"', b'"lease_token"')
        )
    for count in range(5):
        validate_native_reference_query_history(records[:count], value.launch, value.request)


def test_checkpoint_builder_does_not_serialize_away_forged_model_fields():
    value = case()
    payload = query_records(value)[0].payload.model_copy(update={"authority": "ADMIN"})
    with pytest.raises(ValueError):
        native_reference_query_checkpoint(value.launch, "ALLOCATION", payload)


@pytest.mark.parametrize(
    "fault",
    [
        "hash",
        "extra",
        "phase",
        "native",
        "producer",
        "float",
        "bool",
        "order",
        "invocation",
        "template",
        "file",
        "member",
    ],
)
def test_closed_frame_does_not_repair_forged_values(fault):
    records = query_records()
    body = records[
        1
        if fault in {"float", "bool", "order", "invocation", "template"}
        else 2
        if fault in {"file", "member"}
        else 0
    ].model_dump(mode="json")
    if fault == "hash":
        body["checkpoint_sha256"] = "sha256:" + "0" * 64
    if fault == "extra":
        body["authority"] = "ADMIN"
    if fault == "phase":
        body["record_type"] = "EXECUTED"
    if fault == "native":
        body["payload"]["query_producer"]["job_id"] = body["native_launch_job_id"]
    if fault == "producer":
        body["payload"]["receipt_producer"] = body["payload"]["query_producer"]
    if fault == "float":
        body["payload"]["query"]["started_monotonic"] = 3.0
    if fault == "bool":
        body["payload"]["query"]["started_monotonic"] = True
    if fault == "order":
        body["payload"]["query"]["exited_monotonic"] = 1
    if fault == "invocation":
        body["payload"]["query"]["invocation_id"] = body["payload"]["prepare"]["invocation_id"]
    if fault == "template":
        body["payload"]["query_template_sha256"] = "sha256:" + "a" * 64
    if fault == "file":
        body["payload"]["result"]["artifact_revision_id"] = "rev_" + "f" * 32
    if fault == "member":
        body["payload"]["binary"]["member_path"] = "../vectors.f32"
    with pytest.raises((ValueError, TypeError)):
        parse_native_reference_query_checkpoint(
            body if fault == "hash" else seal(body, "checkpoint_sha256")
        )


@pytest.mark.parametrize(
    "fault", ["skip", "duplicate", "reverse", "foreign", "late", "producer", "output"]
)
def test_history_requires_original_producers_order_and_completion(fault):
    value = case()
    records = query_records(value)
    if fault == "skip":
        records = records[:1] + records[2:]
    if fault == "duplicate":
        records = (records[0], records[0])
    if fault == "reverse":
        records = tuple(reversed(records))
    if fault in {"foreign", "late", "producer", "output"}:
        index = {"foreign": 0, "late": 1, "producer": 2, "output": 3}[fault]
        body = records[index].model_dump(mode="json")
        if fault == "foreign":
            body["association_sha256"] = "sha256:" + "f" * 64
        if fault == "late":
            body["payload"]["completed_observed_at"] = (
                (value.launch.launched_at - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
            )
        if fault == "producer":
            body["payload"]["query_owner_job_id"] = "job_" + "f" * 32
        if fault == "output":
            output = body["payload"]["output"]
            output["receipt"]["artifact_revision_id"] = "rev_" + "f" * 32
            body["payload"]["output"] = seal(output, "output_sha256")
        records = (
            *records[:index],
            parse_native_reference_query_checkpoint(seal(body, "checkpoint_sha256")),
            *records[index + 1 :],
        )
    with pytest.raises(ValueError):
        validate_native_reference_query_history(records, value.launch, value.request)


def test_real_sqlite_job_four_phases_exact_replay_and_no_new_identity(tmp_path):
    publisher, _ = _publisher(tmp_path)
    value = case()
    records = query_records(value)
    with publisher.sessions.begin() as session:
        original = create_native_reference_query_launch(
            session, request=value.request, launch=value.launch
        )
    changed = value.launch.model_dump(mode="json")
    changed.update(native_launch_job_id="job_" + "f" * 32, original_command_generation=2)
    with publisher.sessions.begin() as session:
        assert (
            create_native_reference_query_launch(
                session,
                request=value.request,
                launch=parse_reference_query_launch_association(
                    seal(changed, "association_sha256")
                ),
            )
            == original
        )
    owner = NativeReferenceQueryCoordinator(value.request, original)
    for record, expected in zip(
        records, ("RUNNING", "VALIDATING_RESULT", "COMMITTING", "SUCCEEDED"), strict=True
    ):
        with publisher.sessions.begin() as session:
            history = owner.append(session, record)
            assert history.state == expected
        with publisher.sessions.begin() as session:
            assert owner.append(session, record) == history
    with publisher.sessions.begin() as session:
        assert owner.read(session).records == records
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
        job = session.get(JobRecord, original.native_launch_job_id)
        assert job.worker_slot_id is None
        assert all(
            token not in canonical_json_bytes(job.request)
            for token in (b'"text"', b'"rows"', b'"lease_token"')
        )
        assert (
            len(
                native_reference_query_launch_key(
                    original.workflow_id, original.step_run_id, value.request.request_sha256
                )
            )
            < 128
        )


@pytest.mark.parametrize(
    "fault",
    [
        "task",
        "slot",
        "request",
        "hash",
        "launch",
        "event",
        "protocol",
        "state",
        "checkpoint",
        "checkpoint_protocol",
    ],
)
def test_altered_persistence_is_not_a_valid_original_execution(tmp_path, fault):
    publisher, _ = _publisher(tmp_path)
    value = case()
    owner = NativeReferenceQueryCoordinator(value.request, value.launch)
    with publisher.sessions.begin() as session:
        create_native_reference_query_launch(session, request=value.request, launch=value.launch)
        owner.append(session, query_records(value)[0])
    with publisher.sessions.begin() as session:
        job = session.get(JobRecord, value.launch.native_launch_job_id)
        if fault == "task":
            job.task_type = "native_embedding_launch"
        if fault == "slot":
            job.worker_slot_id = "01"
        if fault == "request":
            job.request = {"changed": True}
        if fault == "hash":
            job.request_hash = "sha256:" + "f" * 64
        if fault in {"launch", "event"}:
            event = session.scalar(
                select(JobEventRecord).where(
                    JobEventRecord.event == "REFERENCE_QUERY_NATIVE_LAUNCH"
                )
            )
            if fault == "launch":
                event.data = {"forged": True}
            else:
                event.from_state = "RUNNING"
        if fault in {"protocol", "checkpoint_protocol"}:
            version = (
                "reference-query/1.0"
                if fault == "protocol"
                else "native-reference-query-coordinator/1.0"
            )
            session.get(ProtocolVersionRecord, version).schema_sha256 = "sha256:" + "0" * 64
        if fault == "state":
            job.status = "SUCCEEDED"
        if fault == "checkpoint":
            event = session.scalar(
                select(JobEventRecord).where(
                    JobEventRecord.event == "REFERENCE_QUERY_NATIVE_ALLOCATION"
                )
            )
            event.to_state = "SUCCEEDED"
    with publisher.sessions.begin() as session, pytest.raises(ValueError):
        owner.read(session)


def test_conflict_skip_and_terminal_job_never_rewrite_history(tmp_path):
    publisher, _ = _publisher(tmp_path)
    value = case()
    owner = NativeReferenceQueryCoordinator(value.request, value.launch)
    records = query_records(value)
    with publisher.sessions.begin() as session:
        create_native_reference_query_launch(session, request=value.request, launch=value.launch)
        with pytest.raises(ValueError, match="ORDER_INVALID"):
            owner.append(session, records[1])
        owner.append(session, records[0])
        changed = records[0].model_dump(mode="json")
        changed["payload"]["source_commit"] = "b" * 40
        with pytest.raises(ValueError, match="CONFLICT"):
            owner.append(
                session, parse_native_reference_query_checkpoint(seal(changed, "checkpoint_sha256"))
            )
        transition_job(
            session, value.launch.native_launch_job_id, JobState.FAILED, "SYNTHETIC_FAILURE"
        )
    with publisher.sessions.begin() as session:
        assert owner.read(session).state == "FAILED"
        with pytest.raises(ValueError, match="TERMINAL_OR_FOREIGN"):
            owner.append(session, records[1])
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1


@pytest.mark.parametrize("nested", [False, True])
def test_no_autobegin_or_savepoint_as_current_owner_root(tmp_path, nested):
    publisher, _ = _publisher(tmp_path)
    value = case()
    with publisher.sessions() as session:
        if nested:
            session.begin()
            session.begin_nested()
        with pytest.raises(ValueError, match="ROOT_REQUIRED"):
            read_native_reference_query_launch(
                session,
                request=value.request,
                workflow_id=value.launch.workflow_id,
                step_run_id=value.launch.step_run_id,
            )
