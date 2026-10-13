"""Protocol/actual SQLite Job history; no production authority or numerical execution."""

from pathlib import Path

import pytest
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.models import JobEventRecord, JobRecord, ProtocolVersionRecord
from eom_orchestrator.native_embedding_coordinator import NativeEmbeddingCoordinator
from eom_orchestrator.native_embedding_launch_identity import create_native_embedding_launch
from eom_workflow.native_embedding_coordinator import (
    parse_native_embedding_coordinator_checkpoint,
    validate_native_coordinator_history,
)
from eom_workflow.schemas import (
    NATIVE_EMBEDDING_COORDINATOR_SCHEMA_RESOURCE,
    load_native_embedding_coordinator_schema,
)
from sqlalchemy import func, select

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.local_embedding_admission_fixtures import native_fixture
from tests.unit.native_embedding_coordinator_fixtures import coordinator_records
from tests.unit.test_native_embedding_launch_identity import coordinator as coordinator

ROOT = Path(__file__).resolve().parents[2]


def test_exact_schema_mirror_hash_and_public_copy() -> None:
    filename, schema_id, expected = NATIVE_EMBEDDING_COORDINATOR_SCHEMA_RESOURCE
    raw = (ROOT / "schemas/workflow" / filename).read_bytes()
    assert raw == (ROOT / "packages/workflow/eom_workflow/resources" / filename).read_bytes()
    assert sha256_bytes(raw) == expected
    schema = load_native_embedding_coordinator_schema()
    assert schema["$id"] == schema_id and schema["additionalProperties"] is False
    schema["type"] = "null"
    assert load_native_embedding_coordinator_schema()["type"] == "object"


def test_every_checkpoint_roundtrips_closed_schema_and_is_small_metadata() -> None:
    intent = native_fixture().association.intent
    records = coordinator_records(intent)
    for record in records:
        assert parse_native_embedding_coordinator_checkpoint(record) == record
        assert (
            parse_native_embedding_coordinator_checkpoint(record.model_dump(mode="json")) == record
        )
        raw = canonical_json_bytes(record.model_dump(mode="json"))
        assert len(raw) < 16 * 1024
        assert all(
            token not in raw for token in (b'"text"', b'"vectors"', b'"lease_token"', b'"path"')
        )
    for count in range(5):
        validate_native_coordinator_history(records[:count], intent)


@pytest.mark.parametrize("fault", ["hash", "extra", "native", "producer", "stage", "float", "bool"])
def test_invalid_checkpoint_never_becomes_continuation_proof(fault: str) -> None:
    records = coordinator_records()
    body = records[0].model_dump(mode="json")
    if fault == "hash":
        body["checkpoint_sha256"] = "sha256:" + "0" * 64
    if fault == "extra":
        body["authority"] = "ADMIN"
    if fault == "native":
        body["payload"]["index_producer"]["job_id"] = body["native_launch_job_id"]
    if fault == "producer":
        body["payload"]["receipt_producer"] = body["payload"]["index_producer"]
    if fault == "stage":
        body["record_type"] = "COMPLETED"
    if fault in {"float", "bool"}:
        body = records[1].model_dump(mode="json")
        body["payload"]["registration_command"]["expected_lock_version"] = (
            1.0 if fault == "float" else True
        )
    with pytest.raises((ValueError, TypeError)):
        parse_native_embedding_coordinator_checkpoint(
            body if fault == "hash" else seal(body, "checkpoint_sha256")
        )


@pytest.mark.parametrize("kind", ["skipped", "duplicate", "reordered", "foreign"])
def test_history_requires_one_exact_contiguous_original_intent(kind: str) -> None:
    native = native_fixture()
    records = coordinator_records(native.association.intent)
    if kind == "skipped":
        records = (records[0], records[2])
    if kind == "duplicate":
        records = (records[0], records[0])
    if kind == "reordered":
        records = tuple(reversed(records))
    if kind == "foreign":
        body = records[0].model_dump(mode="json")
        body["intent_sha256"] = "sha256:" + "f" * 64
        records = (parse_native_embedding_coordinator_checkpoint(seal(body, "checkpoint_sha256")),)
    with pytest.raises(ValueError):
        validate_native_coordinator_history(records, native.association.intent)


def test_actual_job_transition_order_exact_reentry_and_completed_history(coordinator) -> None:
    publisher, arguments = coordinator
    with publisher.sessions.begin() as session:
        launch = create_native_embedding_launch(session, **arguments)
    owner = NativeEmbeddingCoordinator(launch.intent, arguments["request"])
    records = coordinator_records(launch.intent)
    expected = ("RUNNING", "VALIDATING_RESULT", "COMMITTING", "SUCCEEDED")
    for record, state in zip(records, expected, strict=True):
        with publisher.sessions.begin() as session:
            first = owner.append(session, record)
            assert first.state == state
        with publisher.sessions.begin() as session:
            assert owner.append(session, record) == first
    with publisher.sessions.begin() as session:
        history = owner.read(session)
        assert history.records == records
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
        events = tuple(
            session.scalars(
                select(JobEventRecord).where(JobEventRecord.event.like("EMBEDDING_NATIVE_%"))
            )
        )
        assert len(events) == 7  # three prefixed creation events + four continuation events


def test_checkpoint_conflict_or_skip_does_not_modify_original_job(coordinator) -> None:
    publisher, arguments = coordinator
    with publisher.sessions.begin() as session:
        launch = create_native_embedding_launch(session, **arguments)
    owner = NativeEmbeddingCoordinator(launch.intent, arguments["request"])
    records = coordinator_records(launch.intent)
    with publisher.sessions.begin() as session, pytest.raises(RuntimeError, match="ORDER_INVALID"):
        owner.append(session, records[1])
    with publisher.sessions.begin() as session:
        first = owner.append(session, records[0])
    body = records[0].model_dump(mode="json")
    body["payload"]["receipt_producer"]["job_id"] = "job_" + "d" * 32
    changed = parse_native_embedding_coordinator_checkpoint(seal(body, "checkpoint_sha256"))
    with publisher.sessions.begin() as session, pytest.raises(RuntimeError, match="CONFLICT"):
        owner.append(session, changed)
    with publisher.sessions.begin() as session:
        assert owner.read(session) == first


def test_wrong_registered_checkpoint_protocol_is_not_read_as_valid_history(coordinator) -> None:
    publisher, arguments = coordinator
    with publisher.sessions.begin() as session:
        launch = create_native_embedding_launch(session, **arguments)
        owner = NativeEmbeddingCoordinator(launch.intent, arguments["request"])
        owner.append(session, coordinator_records(launch.intent)[0])
    with publisher.sessions.begin() as session:
        session.get(ProtocolVersionRecord, "native-embedding-coordinator/1.0").schema_sha256 = (
            "sha256:" + "0" * 64
        )
    with (
        publisher.sessions.begin() as session,
        pytest.raises(RuntimeError, match="HISTORY_INVALID"),
    ):
        owner.read(session)
