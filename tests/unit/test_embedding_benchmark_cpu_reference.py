"""Exact f64/source closure using synthetic vectors, never a model or source grant."""

import struct

import pytest
from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkNearTieReference,
    embedding_device_benchmark_bytes,
)
from eom_catalog_service.embedding_benchmark_cpu_reference import (
    CPU_REFERENCE_SCHEMA,
    build_cpu_benchmark_reference,
    validate_cpu_benchmark_reference,
)
from eom_identifiers import sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema.exceptions import ValidationError as JsonSchemaError

from tests.unit.embedding_device_benchmark_fixtures import owner_request, worker_invocation
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_benchmark_ranking import vector


def cpu_reference(invocation=None, request=None, artifact_id=None, artifact_revision_id=None):
    request = request or owner_request()
    reference, binary = build_cpu_benchmark_reference(
        invocation or worker_invocation(1),
        tuple((row, vector(0.9 - index * 3e-5)) for index, row in enumerate(request.document_rows)),
        tuple((row, vector()) for row in request.query_rows),
        artifact_id=artifact_id or "artifact_" + "a" * 32,
        artifact_revision_id=artifact_revision_id or "rev_" + "b" * 32,
    )
    raw = embedding_device_benchmark_bytes(reference)
    pointer = ArtifactMemberPointer(
        artifact_id=reference.score_binary.artifact_id,
        artifact_revision_id=reference.score_binary.artifact_revision_id,
        member_path="near-tie-reference.json",
        schema_ref=CPU_REFERENCE_SCHEMA,
        media_type="application/json",
        sha256=sha256_bytes(raw),
    )
    return reference, pointer, raw, binary


def test_first_cpu_reference_has_one_raw_f64_member_and_complete_actual_row_scope():
    reference, pointer, raw, binary = cpu_reference()
    assert validate_cpu_benchmark_reference(owner_request(), pointer, raw, binary) == reference
    assert len(binary) == 2 * 15 * 8
    offsets = tuple(
        offset
        for query in reference.queries
        for cluster in query.clusters
        for offset in cluster.cpu_score_offsets
    )
    assert offsets == tuple(range(0, len(binary), 8))
    assert cpu_reference() == (reference, pointer, raw, binary)


@pytest.mark.parametrize("ordinal", (2, 3, 4, 5, 6))
def test_other_launch_cannot_create_posthoc_cpu_reference(ordinal):
    with pytest.raises(ValueError, match="FIRST_LAUNCH_REQUIRED"):
        cpu_reference(worker_invocation(ordinal))


@pytest.mark.parametrize(
    "fault",
    (
        "request",
        "space",
        "family",
        "query",
        "artifact",
        "scope",
        "offset",
        "cluster",
        "nan",
        "trailing",
        "truncated",
    ),
)
def test_correct_rehash_does_not_make_changed_scope_or_bad_scores_valid(fault):
    reference, pointer, _raw, binary = cpu_reference()
    body = reference.model_dump(mode="json")
    if fault in {"request", "family"}:
        body[fault + "_sha256"] = "sha256:" + "f" * 64
    elif fault == "space":
        body["cpu_document_space_sha256"] = "sha256:" + "f" * 64
    elif fault == "query":
        body["queries"][0]["query_row"] = body["queries"][1]["query_row"]
    elif fault == "artifact":
        body["score_binary"]["artifact_id"] = "artifact_" + "f" * 32
    elif fault == "scope":
        body["queries"][0]["ordered_candidates"].pop()
        final = body["queries"][0]["clusters"][-1]
        final["row_sha256"].pop()
        final["cpu_score_offsets"].pop()
        if not final["row_sha256"]:
            body["queries"][0]["clusters"].pop()
    elif fault == "offset":
        body["queries"][0]["clusters"][0]["cpu_score_offsets"][0] = 8
    elif fault == "cluster":
        clusters = body["queries"][0]["clusters"]
        clusters[0]["row_sha256"].extend(clusters[1]["row_sha256"])
        clusters[0]["cpu_score_offsets"].extend(clusters[1]["cpu_score_offsets"])
        clusters.pop(1)
        for ordinal, cluster in enumerate(clusters, 1):
            cluster["cluster_ordinal"] = ordinal
    elif fault == "nan":
        binary = struct.pack("<d", float("nan")) + binary[8:]
    elif fault == "trailing":
        binary += struct.pack("<d", 0.0)
    else:
        binary = binary[:-8]
    body["score_binary"]["sha256"] = sha256_bytes(binary)
    with pytest.raises((ValueError, JsonSchemaError)):
        changed = BenchmarkNearTieReference.model_validate(seal(body, "reference_sha256"))
        raw = embedding_device_benchmark_bytes(changed)
        pointer = pointer.model_copy(update={"sha256": sha256_bytes(raw)})
        validate_cpu_benchmark_reference(owner_request(), pointer, raw, binary)
