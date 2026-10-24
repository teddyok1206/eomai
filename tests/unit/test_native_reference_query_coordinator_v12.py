"""Batch checkpoint metadata, never an actual canonical batch/GPU/source acceptance."""

from __future__ import annotations

from pathlib import Path

import pytest
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.models import JobRecord, ProtocolVersionRecord
from eom_orchestrator.native_reference_query_coordinator import (
    NativeReferenceQueryCoordinator,
    create_native_reference_query_launch,
)
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.native_reference_query_coordinator import (
    NativeQueryBatchExecuted,
    native_reference_query_continuation_checkpoint,
    parse_supported_native_reference_query_checkpoint,
    validate_native_reference_query_history,
)
from eom_workflow.schemas import NATIVE_REFERENCE_QUERY_COORDINATOR_V12_SCHEMA_RESOURCE
from jsonschema import Draft202012Validator

from tests.unit.embedding_batch_execution_fixtures import execution_case
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.native_reference_query_coordinator_fixtures import query_records
from tests.unit.test_control_file_set_publication import _publisher
from tests.unit.test_reference_query_execution_contracts import case

V12 = "native-reference-query-coordinator/1.2"


def batch_query_records(value=None):
    value = value or case(device="CUDA")
    old = query_records(value)
    receipt = execution_case().receipt
    executed = NativeQueryBatchExecuted(
        batch_receipt=ArtifactMemberPointer(
            artifact_id="artifact_" + "9" * 32,
            artifact_revision_id="rev_" + "9" * 32,
            member_path="receipt.json",
            media_type="application/json",
            schema_ref="eom://schemas/workflow/embedding-batch-execution-receipt/1.0",
            sha256=sha256_bytes(canonical_json_bytes(receipt.model_dump(mode="json"))),
        ),
        batch_receipt_sha256=receipt.receipt_sha256,
        child_ordinal=0,
        result_sha256=value.result.result_sha256,
        completed_observed_at=value.launch.launched_at,
    )
    result = []
    for original in old:
        result.append(
            native_reference_query_continuation_checkpoint(
                value.launch,
                original.record_type,
                executed if original.record_type == "EXECUTED" else original.payload,
                previous=tuple(result),
                initial_version=V12,
            )
        )
    return tuple(result)


def test_batch_checkpoint_schema_is_pinned_mirrored_and_old_bytes_unchanged():
    root = Path(__file__).resolve().parents[2]
    name, schema_id, digest = NATIVE_REFERENCE_QUERY_COORDINATOR_V12_SCHEMA_RESOURCE
    raw = (root / "schemas/workflow" / name).read_bytes()
    assert raw == (root / "packages/workflow/eom_workflow/resources" / name).read_bytes()
    assert sha256_bytes(raw) == digest and schema_id.endswith("/1.2")
    import json

    Draft202012Validator.check_schema(json.loads(raw))
    assert (
        sha256_bytes(
            (
                root / "schemas/workflow/native-reference-query-coordinator-v1.schema.json"
            ).read_bytes()
        )
        == "sha256:b3711bf1f8722b9a0b884dac7f3ef032c0bd28bd4e76351f3d7ee4d1e0f17745"
    )
    assert (
        sha256_bytes(
            (
                root / "schemas/workflow/native-reference-query-coordinator-v1.1.schema.json"
            ).read_bytes()
        )
        == "sha256:a3f08ea22ec5f71582f86598f6fa16737115e23742a332173da034f59860e6ed"
    )


def test_all_contiguous_prefixes_preserve_new_family_but_are_not_canonical_read_proof():
    value = case(device="CUDA")
    records = batch_query_records(value)
    for count in range(5):
        validate_native_reference_query_history(records[:count], value.launch, value.request)
    for record in records:
        assert parse_supported_native_reference_query_checkpoint(record) == record
    with pytest.raises(ValueError):
        validate_native_reference_query_history(records, case().launch, case().request)


@pytest.mark.parametrize(
    "fault", ("extra", "path", "schema", "media", "ordinal", "bool", "hash", "cpu_fields")
)
def test_batch_checkpoint_rejects_forged_or_ambiguous_execution_metadata(fault):
    body = batch_query_records()[1].model_dump(mode="json")
    value = body["payload"]
    if fault == "extra":
        value["authority"] = "ADMIN"
    elif fault == "path":
        value["batch_receipt"]["member_path"] = "result.json"
    elif fault == "schema":
        value["batch_receipt"]["schema_ref"] = "eom://schemas/other/1.0"
    elif fault == "media":
        value["batch_receipt"]["media_type"] = "application/octet-stream"
    elif fault == "ordinal":
        value["child_ordinal"] = 32
    elif fault == "bool":
        value["child_ordinal"] = False
    elif fault == "hash":
        body["checkpoint_sha256"] = "sha256:" + "f" * 64
    else:
        value["cpu_environment_sha256"] = "sha256:" + "a" * 64
    with pytest.raises(ValueError):
        parse_supported_native_reference_query_checkpoint(
            body if fault == "hash" else seal(body, "checkpoint_sha256")
        )


@pytest.mark.parametrize("version", ("1.0", "1.1"))
def test_cpu_unit_proofs_and_batch_receipts_cannot_be_mixed_or_relabelled(version):
    value = case(device="CUDA")
    old = query_records(value, version="native-reference-query-coordinator/" + version)
    new = batch_query_records(value)
    for previous, payload, initial in (
        (old[:1], new[1].payload, V12),
        (new[:1], old[1].payload, V12),
    ):
        with pytest.raises(ValueError):
            native_reference_query_continuation_checkpoint(
                value.launch, "EXECUTED", payload, previous=previous, initial_version=initial
            )
    with pytest.raises(ValueError):
        validate_native_reference_query_history((new[0], old[1]), value.launch, value.request)
    assert (
        native_reference_query_continuation_checkpoint(
            value.launch, "ALLOCATION", old[0].payload, previous=old[:1], initial_version=V12
        )
        == old[0]
    )


def test_cpu_request_cannot_masquerade_as_cuda_batch_history():
    value = case()
    records = batch_query_records(value)
    with pytest.raises(ValueError):
        validate_native_reference_query_history(records[:1], value.launch, value.request)


def test_existing_checkpoint_store_persists_new_protocol_without_rewriting_old(tmp_path):
    publisher, _ = _publisher(tmp_path)
    value = case(device="CUDA")
    records = batch_query_records(value)
    owner = NativeReferenceQueryCoordinator(value.request, value.launch)
    with publisher.sessions.begin() as session:
        create_native_reference_query_launch(session, request=value.request, launch=value.launch)
    for record in records:
        with publisher.sessions.begin() as session:
            first = owner.append(session, record)
        with publisher.sessions.begin() as session:
            assert owner.append(session, record) == first
    with publisher.sessions.begin() as session:
        assert owner.read(session).records == records
        assert session.get(ProtocolVersionRecord, "native-query-coordinator/1.2") is not None
        assert session.get(ProtocolVersionRecord, "native-query-coordinator/1.1") is None


def test_original_known_failure_remains_terminal_and_is_not_labelled_cpu_execution(tmp_path):
    publisher, _ = _publisher(tmp_path)
    value = case(device="CUDA")
    records = batch_query_records(value)
    owner = NativeReferenceQueryCoordinator(value.request, value.launch)
    with publisher.sessions.begin() as session:
        create_native_reference_query_launch(session, request=value.request, launch=value.launch)
        owner.append(session, records[0])
        failed = owner.record_known_failure(session)
        assert failed.state == "FAILED"
        assert (
            session.get(JobRecord, value.launch.native_launch_job_id).error_message
            == "original finite CUDA QUERY batch failed"
        )
    with publisher.sessions.begin() as session:
        assert owner.record_known_failure(session) == failed
        with pytest.raises(ValueError):
            owner.append(session, records[1])
    with publisher.sessions.begin() as session:
        assert owner.read(session) == failed
