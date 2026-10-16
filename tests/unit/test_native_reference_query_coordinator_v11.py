"""Successor runtime provenance without rewriting released QUERY checkpoints."""

from pathlib import Path

import pytest
from eom_identifiers import sha256_bytes
from eom_orchestrator.models import ProtocolVersionRecord
from eom_orchestrator.native_reference_query_coordinator import (
    NativeReferenceQueryCoordinator,
    create_native_reference_query_launch,
)
from eom_workflow.native_reference_query_coordinator import (
    native_reference_query_continuation_checkpoint,
    parse_native_reference_query_checkpoint,
    parse_supported_native_reference_query_checkpoint,
    validate_native_reference_query_history,
)
from eom_workflow.schemas import (
    NATIVE_REFERENCE_QUERY_COORDINATOR_SCHEMA_RESOURCE,
    NATIVE_REFERENCE_QUERY_COORDINATOR_V11_SCHEMA_RESOURCE,
)

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.native_reference_query_coordinator_fixtures import query_records
from tests.unit.test_control_file_set_publication import _publisher
from tests.unit.test_reference_query_execution_contracts import case

V10 = "native-reference-query-coordinator/1.0"
V11 = "native-reference-query-coordinator/1.1"


@pytest.mark.parametrize(
    "value",
    (None, [], 1, True, "1.1", {}, {"schema_version": "native-reference-query-coordinator/1.2"}),
)
def test_supported_reader_rejects_nonobjects_and_undeclared_versions(value):
    with pytest.raises(ValueError):
        parse_supported_native_reference_query_checkpoint(value)


def test_successor_schema_is_mirrored_and_predecessor_bytes_are_unchanged():
    root = Path(__file__).resolve().parents[2]
    name, schema_id, digest = NATIVE_REFERENCE_QUERY_COORDINATOR_V11_SCHEMA_RESOURCE
    raw = (root / "schemas/workflow" / name).read_bytes()
    assert raw == (root / "packages/workflow/eom_workflow/resources" / name).read_bytes()
    assert sha256_bytes(raw) == digest
    assert schema_id.endswith("/1.1")
    assert (
        sha256_bytes(
            (
                root / "schemas/workflow" / NATIVE_REFERENCE_QUERY_COORDINATOR_SCHEMA_RESOURCE[0]
            ).read_bytes()
        )
        == "sha256:b3711bf1f8722b9a0b884dac7f3ef032c0bd28bd4e76351f3d7ee4d1e0f17745"
    )


@pytest.mark.parametrize("version", (V10, V11))
def test_supported_reader_and_all_contiguous_prefixes(version):
    value = case()
    records = query_records(value, version=version)
    for record in records:
        assert parse_supported_native_reference_query_checkpoint(record) == record
        assert (
            parse_supported_native_reference_query_checkpoint(record.model_dump(mode="json"))
            == record
        )
        if version == V11:
            with pytest.raises(ValueError):
                parse_native_reference_query_checkpoint(record)
    for count in range(5):
        validate_native_reference_query_history(records[:count], value.launch, value.request)


@pytest.mark.parametrize(
    "fault", ("template", "hash", "extra", "family", "foreign", "forged_payload")
)
def test_new_family_does_not_repair_or_promote_old_or_forged_values(fault):
    value = case()
    records = query_records(value, version=V11)
    if fault in {"template", "hash", "extra"}:
        body = records[1].model_dump(mode="json")
        if fault == "template":
            body["payload"]["prepare_template_sha256"] = query_records(value)[
                1
            ].payload.prepare_template_sha256
        elif fault == "hash":
            body["checkpoint_sha256"] = "sha256:" + "0" * 64
        else:
            body["authority"] = "ADMIN"
        with pytest.raises(ValueError):
            parse_supported_native_reference_query_checkpoint(
                body if fault == "hash" else seal(body, "checkpoint_sha256")
            )
        return
    previous = records[:1]
    payload = records[1].payload
    if fault == "family":
        previous = (query_records(value)[0], records[1])
    elif fault == "foreign":
        body = records[0].model_dump(mode="json") | {"association_sha256": "sha256:" + "f" * 64}
        previous = (
            parse_supported_native_reference_query_checkpoint(seal(body, "checkpoint_sha256")),
        )
    else:
        payload = payload.model_copy(update={"authority": "ADMIN"})
    with pytest.raises(ValueError):
        native_reference_query_continuation_checkpoint(
            value.launch, "EXECUTED", payload, previous=previous, initial_version=V11
        )


def test_continuation_keeps_the_original_family_even_after_release_change():
    value = case()
    records = query_records(value)
    assert (
        native_reference_query_continuation_checkpoint(
            value.launch, "PUBLISHED", records[2].payload, previous=records[:2], initial_version=V11
        )
        == records[2]
    )
    with pytest.raises(ValueError):
        validate_native_reference_query_history(
            (records[0], query_records(value, version=V11)[1]), value.launch, value.request
        )


@pytest.mark.parametrize("version", (V10, V11))
def test_all_four_persisted_phases_and_replay_use_the_exact_registry_family(tmp_path, version):
    publisher, _ = _publisher(tmp_path)
    value = case()
    records = query_records(value, version=version)
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
        selected = "native-query-coordinator/" + version.rsplit("/", 1)[1]
        assert session.get(ProtocolVersionRecord, selected) is not None
        other = "native-query-coordinator/" + ("1.0" if version == V11 else "1.1")
        assert session.get(ProtocolVersionRecord, other) is None
