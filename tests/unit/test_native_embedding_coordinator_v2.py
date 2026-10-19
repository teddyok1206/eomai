"""Real local SQLite Job2 history and pure frames; no runtime/source authority."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts.mixed_embedding_registry import (
    EmbeddingIndexRegistrationResultV2,
    RegisterEmbeddingIndexCommandV2,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.embedding_encoding_reservation_storage import ENCODING_PROTOCOL_VERSION
from eom_orchestrator.models import JobEventRecord, JobRecord, ProtocolVersionRecord
from eom_orchestrator.native_embedding_coordinator import (
    NativeEmbeddingCoordinator,
    native_embedding_index_registration_key,
)
from eom_orchestrator.native_embedding_launch_identity import (
    NATIVE_INTENT_EVENT,
    create_native_embedding_launch,
    read_native_embedding_launch,
)
from eom_workflow.local_embedding_encoding_job import LocalEmbeddingLaunchIntent
from eom_workflow.local_embedding_encoding_ownership_v2 import (
    LocalEmbeddingLaunchIntentV2,
    local_embedding_launch_protocol,
    parse_local_embedding_launch_intent_for_request,
)
from eom_workflow.local_embedding_workflow_receipt_v2 import LocalEmbeddingStepOutputV2
from eom_workflow.native_embedding_coordinator import (
    NativeArtifactProducerIdentity,
    NativeCoordinatorAllocation,
    parse_native_embedding_coordinator_checkpoint,
)
from eom_workflow.native_embedding_coordinator_v2 import (
    NativeCoordinatorCompletedV2,
    NativeCoordinatorIndexPreparedV2,
    NativeCoordinatorRegisteredV2,
    NativeEmbeddingCoordinatorCheckpointV2,
    native_coordinator_checkpoint_v2,
    parse_native_embedding_coordinator_checkpoint_v2,
    validate_native_coordinator_history_v2,
)
from eom_workflow.schemas import (
    NATIVE_EMBEDDING_COORDINATOR_V2_SCHEMA_RESOURCE,
    load_native_embedding_coordinator_v2_schema,
)
from sqlalchemy import func, select

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.inference_transfer_fixtures import NOW
from tests.unit.local_embedding_admission_fixtures import native_fixture
from tests.unit.native_embedding_coordinator_fixtures import coordinator_records
from tests.unit.test_control_file_set_publication import _publisher
from tests.unit.test_mixed_native_workflow_carriers import carrier_fixture

ROOT = Path(__file__).resolve().parents[2]


def _records(intent: LocalEmbeddingLaunchIntentV2 | None = None) -> tuple[Any, ...]:
    f = carrier_fixture()
    intent = intent or f["association"].intent
    command_body = f["receipt"].registration_command.model_dump(mode="json")
    command_body["operation_key"] = native_embedding_index_registration_key(
        intent, command_body["index_id"], command_body["index_revision_id"]
    )
    command = RegisterEmbeddingIndexCommandV2.model_validate(seal(command_body, "request_sha256"))
    result_body = f["receipt"].registration_result.model_dump(mode="json")
    result_body.update(operation_key=command.operation_key, request_sha256=command.request_sha256)
    result = EmbeddingIndexRegistrationResultV2.model_validate(seal(result_body, "result_sha256"))
    output_body = f["output"].model_dump(mode="json")
    # The carrier fixture uses arbitrary pointer IDs; actual coordinator owners
    # allocate distinct index and receipt logical/revision identities.
    output_body["receipt"].update(
        artifact_id="artifact_" + "d" * 32, artifact_revision_id="rev_" + "d" * 32
    )
    output = LocalEmbeddingStepOutputV2.model_validate(seal(output_body, "output_sha256"))
    allocation = NativeCoordinatorAllocation(
        index_producer=NativeArtifactProducerIdentity(
            job_id="job_" + "c" * 32,
            artifact_id=command.index_manifest.artifact_id,
            artifact_revision_id=command.index_manifest.artifact_revision_id,
        ),
        receipt_producer=NativeArtifactProducerIdentity(
            job_id=output.receipt_owner_job_id,
            artifact_id=output.receipt.artifact_id,
            artifact_revision_id=output.receipt.artifact_revision_id,
        ),
        created_at=NOW,
        source_commit="a" * 40,
    )
    payloads = (
        ("ALLOCATION", allocation),
        (
            "INDEX_PREPARED",
            NativeCoordinatorIndexPreparedV2(registration_command=command, index_created_at=NOW),
        ),
        (
            "REGISTERED",
            NativeCoordinatorRegisteredV2(
                registration_result=result, registration_observed_at=NOW + timedelta(seconds=1)
            ),
        ),
        ("COMPLETED", NativeCoordinatorCompletedV2(output=output)),
    )
    return tuple(native_coordinator_checkpoint_v2(intent, phase, body) for phase, body in payloads)


@pytest.fixture
def owner(tmp_path: Path) -> tuple[Any, dict[str, Any]]:
    publisher, _engine = _publisher(tmp_path)
    old = native_fixture().request
    request = carrier_fixture()["request"]
    with publisher.sessions.begin() as session:
        for version, digest in (
            local_embedding_launch_protocol(old),
            local_embedding_launch_protocol(request),
        ):
            session.add(ProtocolVersionRecord(version=version, schema_sha256=digest))
    intent = carrier_fixture()["association"].intent
    return publisher, dict(
        request=request,
        workflow_id=intent.workflow_id,
        step_run_id=intent.step_run_id,
        command_id=intent.command_id,
        runner_id=intent.runner_id,
        lease_generation=intent.lease_generation,
    )


def test_exact_schema_mirror_and_public_copy() -> None:
    filename, schema_id, expected = NATIVE_EMBEDDING_COORDINATOR_V2_SCHEMA_RESOURCE
    raw = (ROOT / "schemas/workflow" / filename).read_bytes()
    assert raw == (ROOT / "packages/workflow/eom_workflow/resources" / filename).read_bytes()
    assert sha256_bytes(raw) == expected
    schema = load_native_embedding_coordinator_v2_schema()
    assert schema["$id"] == schema_id
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    schema["properties"]["schema_version"]["const"] = "forged"
    assert load_native_embedding_coordinator_v2_schema()["properties"]["schema_version"] == {
        "const": "native-embedding-coordinator/2.0"
    }


def test_independent_checkpoints_roundtrip_exact_families_and_preserve_numeric1() -> None:
    f = carrier_fixture()
    records = _records()
    for record in records:
        assert type(record) is NativeEmbeddingCoordinatorCheckpointV2
        assert parse_native_embedding_coordinator_checkpoint_v2(record) == record
        with pytest.raises(ValueError):
            parse_native_embedding_coordinator_checkpoint(record)
        raw = canonical_json_bytes(record.model_dump(mode="json"))
        assert len(raw) < 16 * 1024
        assert all(word not in raw for word in (b'"text"', b'"vectors"', b'"lease_token"'))
    for count in range(5):
        validate_native_coordinator_history_v2(records[:count], f["association"].intent)
    with pytest.raises(ValueError):
        parse_native_embedding_coordinator_checkpoint_v2(coordinator_records()[0])
    assert f["association"].owned_jobs[0].request.schema_version == "embedding-encoding-job/1.0"
    assert f["input"].schema_version == "incremental-embedding-input/1.0"
    assert f["result"].schema_version == "incremental-embedding-result/1.0"


def test_protocol_and_intent_dispatch_use_actual_request_family_not_retagging() -> None:
    f = carrier_fixture()
    old = native_fixture()
    assert local_embedding_launch_protocol(old.request)[0] == ENCODING_PROTOCOL_VERSION
    assert local_embedding_launch_protocol(f["request"])[0] == "embedding-encoding-ownership/2.0"
    assert (
        type(parse_local_embedding_launch_intent_for_request(old.association.intent, old.request))
        is LocalEmbeddingLaunchIntent
    )
    assert (
        type(parse_local_embedding_launch_intent_for_request(f["association"].intent, f["request"]))
        is LocalEmbeddingLaunchIntentV2
    )
    for intent, request in (
        (old.association.intent, f["request"]),
        (f["association"].intent, old.request),
    ):
        with pytest.raises(ValueError):
            parse_local_embedding_launch_intent_for_request(intent, request)


def test_public_checkpoint_builder_preserves_family_and_rejects_foreign_payload() -> None:
    f = carrier_fixture()
    owner = NativeEmbeddingCoordinator(f["association"].intent, f["request"])
    for record in _records():
        assert owner.checkpoint(record.record_type, record.payload) == record
    old = native_fixture()
    legacy_owner = NativeEmbeddingCoordinator(old.association.intent, old.request)
    for record in coordinator_records(old.association.intent):
        assert legacy_owner.checkpoint(record.record_type, record.payload) == record
    with pytest.raises(ValueError):
        owner.checkpoint("INDEX_PREPARED", coordinator_records()[1].payload)
    with pytest.raises(ValueError):
        owner.checkpoint("ALLOCATION", _records()[0].payload.model_copy(update={"grant": True}))


@pytest.mark.parametrize(
    "fault", ["hash", "extra", "copied_extra", "producer", "old_command", "old_output", "float"]
)
def test_malformed_checkpoint_never_becomes_continuation_authority(fault: str) -> None:
    records = _records()
    value = records[0].model_dump(mode="json")
    if fault == "hash":
        value["checkpoint_sha256"] = "sha256:" + "0" * 64
    elif fault == "extra":
        value["permissions"] = ["ADMIN"]
    elif fault == "copied_extra":
        with pytest.raises(ValueError):
            parse_native_embedding_coordinator_checkpoint_v2(
                records[0].model_copy(update={"authority": "ADMIN"})
            )
        return
    elif fault == "producer":
        value["payload"]["index_producer"]["job_id"] = value["native_launch_job_id"]
    elif fault == "old_command":
        value = records[1].model_dump(mode="json")
        value["payload"]["registration_command"] = coordinator_records()[
            1
        ].payload.registration_command.model_dump(mode="json")
    elif fault == "old_output":
        value = records[3].model_dump(mode="json")
        value["payload"]["output"] = coordinator_records()[3].payload.output.model_dump(mode="json")
    else:
        value = records[1].model_dump(mode="json")
        value["payload"]["registration_command"]["expected_lock_version"] = 1.0
    with pytest.raises((ValueError, TypeError)):
        parse_native_embedding_coordinator_checkpoint_v2(
            value if fault in {"hash", "float"} else seal(value, "checkpoint_sha256")
        )


@pytest.mark.parametrize("fault", ["skip", "duplicate", "foreign", "backdated", "receipt_owner"])
def test_fixed_history_original_producer_and_times_are_not_weakened(fault: str) -> None:
    records = _records()
    if fault == "skip":
        changed = (records[0], records[2])
    elif fault == "duplicate":
        changed = (records[0], records[0])
    else:
        index = 0 if fault == "foreign" else 1 if fault == "backdated" else 3
        body = records[index].model_dump(mode="json")
        if fault == "foreign":
            body["intent_sha256"] = "sha256:" + "f" * 64
        elif fault == "backdated":
            body["payload"]["index_created_at"] = (
                (NOW - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
            )
        else:
            output = body["payload"]["output"]
            output["receipt_owner_job_id"] = "job_" + "f" * 32
            body["payload"]["output"] = seal(output, "output_sha256")
        changed = list(records)
        changed[index] = parse_native_embedding_coordinator_checkpoint_v2(
            seal(body, "checkpoint_sha256")
        )
        changed = tuple(changed)
    with pytest.raises(ValueError):
        validate_native_coordinator_history_v2(changed, carrier_fixture()["association"].intent)


def test_actual_job2_allocation_reentry_and_four_original_transitions(
    owner: tuple[Any, Any],
) -> None:
    publisher, args = owner
    with publisher.sessions.begin() as session:
        launch = create_native_embedding_launch(session, **args)
        assert type(launch.intent) is LocalEmbeddingLaunchIntentV2
    with publisher.sessions.begin() as session:
        assert (
            create_native_embedding_launch(
                session, **(args | {"lease_generation": 2, "runner_id": "new-runner"})
            )
            == launch
        )
        assert (
            read_native_embedding_launch(
                session,
                request=args["request"],
                workflow_id=args["workflow_id"],
                step_run_id=args["step_run_id"],
            )
            == launch
        )
        job = session.get(JobRecord, launch.intent.native_launch_job_id)
        assert job.protocol_version == "embedding-encoding-ownership/2.0"
        assert job.worker_slot_id is None and job.request == args["request"].model_dump(mode="json")
        assert job.request_hash == content_sha256(
            {
                "protocol_version": job.protocol_version,
                "task_type": job.task_type,
                "request": job.request,
            }
        )
    coordinator = NativeEmbeddingCoordinator(launch.intent, args["request"])
    records = _records(launch.intent)
    for record, expected in zip(
        records, ("RUNNING", "VALIDATING_RESULT", "COMMITTING", "SUCCEEDED"), strict=True
    ):
        with publisher.sessions.begin() as session:
            result = coordinator.append(session, record)
            assert result.state == expected
        with publisher.sessions.begin() as session:
            assert coordinator.append(session, record) == result
    with publisher.sessions.begin() as session:
        assert coordinator.read(session).records == records
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
        checkpoint_protocol = session.get(ProtocolVersionRecord, "native-embedding-coordinator/2.0")
        assert (
            checkpoint_protocol.schema_sha256 == NATIVE_EMBEDDING_COORDINATOR_V2_SCHEMA_RESOURCE[2]
        )
        assert session.get(ProtocolVersionRecord, "native-embedding-coordinator/1.0") is None


@pytest.mark.parametrize(
    "fault",
    ["job_protocol", "protocol_hash", "intent_family", "event_transition", "checkpoint_family"],
)
def test_wrong_actual_job_or_event_family_is_rejected_without_new_job(
    owner: tuple[Any, Any], fault: str
) -> None:
    publisher, args = owner
    with publisher.sessions.begin() as session:
        launch = create_native_embedding_launch(session, **args)
        coordinator = NativeEmbeddingCoordinator(launch.intent, args["request"])
        coordinator.append(session, _records(launch.intent)[0])
    with publisher.sessions.begin() as session:
        if fault == "job_protocol":
            session.get(
                JobRecord, launch.intent.native_launch_job_id
            ).protocol_version = ENCODING_PROTOCOL_VERSION
        elif fault == "protocol_hash":
            session.get(ProtocolVersionRecord, "embedding-encoding-ownership/2.0").schema_sha256 = (
                "sha256:" + "0" * 64
            )
        elif fault == "intent_family":
            event = session.scalar(
                select(JobEventRecord).where(JobEventRecord.event == NATIVE_INTENT_EVENT)
            )
            event.data = native_fixture().association.intent.model_dump(mode="json")
        else:
            event = session.scalar(
                select(JobEventRecord).where(JobEventRecord.event == "EMBEDDING_NATIVE_ALLOCATION")
            )
            if fault == "event_transition":
                event.from_state = "QUEUED"
            else:
                event.data = coordinator_records()[0].model_dump(mode="json")
    with publisher.sessions.begin() as session, pytest.raises((ValueError, RuntimeError)):
        coordinator.read(session)
    with publisher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1


def test_missing_launch_metadata_protocol_is_not_initialized_by_runtime_reads(
    owner: tuple[Any, Any],
) -> None:
    publisher, args = owner
    with publisher.sessions.begin() as session:
        session.delete(session.get(ProtocolVersionRecord, "embedding-encoding-ownership/2.0"))
    with (
        publisher.sessions.begin() as session,
        pytest.raises(RuntimeError, match="PROTOCOL_UNAVAILABLE"),
    ):
        create_native_embedding_launch(session, **args)
    with publisher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 0


def test_old_checkpoint_cannot_be_appended_to_new_original_job(owner: tuple[Any, Any]) -> None:
    publisher, args = owner
    with publisher.sessions.begin() as session:
        launch = create_native_embedding_launch(session, **args)
        coordinator = NativeEmbeddingCoordinator(launch.intent, args["request"])
        with pytest.raises(ValueError):
            coordinator.append(session, coordinator_records()[0])
        assert coordinator.read(session).records == ()
        assert session.get(JobRecord, launch.intent.native_launch_job_id).status == "CLAIMED"
