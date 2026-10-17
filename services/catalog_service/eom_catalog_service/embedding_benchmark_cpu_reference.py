"""Pure CPU-first f64 ranking reference construction/validation; no publication or grant."""

from __future__ import annotations

import math
import struct

from eom_catalog_contracts.embedding_device_benchmark import (
    EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF,
    BenchmarkNearTieReference,
    BenchmarkOwnerRequest,
    BenchmarkRowRef,
    BenchmarkWorkerInvocation,
    embedding_device_benchmark_bytes,
    parse_embedding_device_benchmark_bytes,
)
from eom_catalog_contracts.inference_transfer_experiment import profile_key
from eom_identifiers import content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer

from eom_catalog_service.embedding_benchmark_ranking import (
    ScoredBenchmarkRow,
    cluster_cpu_benchmark_rows,
    rank_benchmark_rows,
)

CPU_REFERENCE_SCHEMA = EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF + "#/$defs/nearTieReference"
CPU_SCORE_SCHEMA = "eom://schemas/knowledge/embedding-benchmark-scores-f64le/1.0"
type BenchmarkRowVector = tuple[BenchmarkRowRef, tuple[float, ...]]


def build_cpu_benchmark_reference(
    invocation: BenchmarkWorkerInvocation,
    documents: tuple[BenchmarkRowVector, ...],
    queries: tuple[BenchmarkRowVector, ...],
    *,
    artifact_id: str,
    artifact_revision_id: str,
) -> tuple[BenchmarkNearTieReference, bytes]:
    """First CPU repetition per exact query, selected before any live benchmark result.

    The caller supplies already validated CPU1 vectors and publication identities.
    At most34 scalars, one f64 member, no rounded decision or invented profile ID.
    """
    embedding_device_benchmark_bytes(invocation)
    if invocation.device != "CPU" or invocation.launch_ordinal != 1 or len(queries) != 2:
        raise ValueError("BENCHMARK_CPU_REFERENCE_FIRST_LAUNCH_REQUIRED")
    binary = bytearray()
    query_records = []
    for ordinal, (query_row, vector) in enumerate(queries, 1):
        ranked = rank_benchmark_rows(query_row, vector, documents)
        offsets = {
            value.row.row_sha256: len(binary) + index * 8 for index, value in enumerate(ranked)
        }
        binary.extend(b"".join(struct.pack("<d", value.cosine_similarity) for value in ranked))
        query_records.append(
            dict(
                query_ordinal=ordinal,
                query_row=query_row.model_dump(mode="json"),
                ordered_candidates=[value.row.model_dump(mode="json") for value in ranked],
                clusters=[
                    dict(
                        cluster_ordinal=index,
                        row_sha256=[value.row.row_sha256 for value in cluster],
                        cpu_score_offsets=[offsets[value.row.row_sha256] for value in cluster],
                    )
                    for index, cluster in enumerate(cluster_cpu_benchmark_rows(ranked), 1)
                ],
            )
        )
    raw = bytes(binary)
    pointer = ArtifactMemberPointer(
        artifact_id=artifact_id,
        artifact_revision_id=artifact_revision_id,
        member_path="rank-evidence.f64",
        schema_ref=CPU_SCORE_SCHEMA,
        media_type="application/octet-stream",
        sha256=sha256_bytes(raw),
    )
    body = dict(
        schema_version="embedding-device-benchmark-near-tie-reference/1.0",
        request_sha256=invocation.owner_request_sha256,
        input_set_sha256=invocation.input_set_sha256,
        family_sha256=invocation.family.family_sha256,
        cpu_document_space_sha256=invocation.runtime.spaces.document.space_sha256,
        cpu_query_space_sha256=invocation.runtime.spaces.query.space_sha256,
        score_binary=pointer.model_dump(mode="json"),
        queries=query_records,
    )
    reference = BenchmarkNearTieReference.model_validate(
        body | {"reference_sha256": content_sha256(body)}
    )
    return reference, raw


def validate_cpu_benchmark_reference(
    request: BenchmarkOwnerRequest,
    pointer: ArtifactMemberPointer,
    raw: bytes,
    binary: bytes,
) -> BenchmarkNearTieReference:
    """Exact source/space/pointer/scope and complete-span revalidation, not authorization.

    The official reader must establish permission, registered Artifact ownership and
    publication-before-CUDA. This pure function does not infer those from a timestamp.
    """
    embedding_device_benchmark_bytes(request)
    reference = parse_embedding_device_benchmark_bytes(raw)
    if (
        not isinstance(reference, BenchmarkNearTieReference)
        or embedding_device_benchmark_bytes(reference) != raw
        or pointer.member_path != "near-tie-reference.json"
        or pointer.schema_ref != CPU_REFERENCE_SCHEMA
        or pointer.media_type != "application/json"
        or pointer.sha256 != sha256_bytes(raw)
        or reference.request_sha256 != request.request_sha256
        or reference.input_set_sha256 != request.input_set_sha256
        or reference.family_sha256 != request.family.family_sha256
        or reference.cpu_document_space_sha256 != request.cpu.spaces.document.space_sha256
        or reference.cpu_query_space_sha256 != request.cpu.spaces.query.space_sha256
        or (reference.score_binary.artifact_id, reference.score_binary.artifact_revision_id)
        != (pointer.artifact_id, pointer.artifact_revision_id)
        or type(binary) is not bytes
        or not 80 <= len(binary) <= 272
        or len(binary) % 8
        or reference.score_binary.sha256 != sha256_bytes(binary)
    ):
        raise ValueError("BENCHMARK_CPU_REFERENCE_CLOSURE_INVALID")
    offset = 0
    for expected_query, query in zip(request.query_rows, reference.queries, strict=True):
        if query.query_row != expected_query:
            raise ValueError("BENCHMARK_CPU_REFERENCE_QUERY_INVALID")
        expected = {
            row.row_sha256: row
            for row in request.document_rows
            if profile_key(row.profile) != profile_key(expected_query.profile)
        }
        actual = {row.row_sha256: row for row in query.ordered_candidates}
        if actual != expected or len(actual) != len(query.ordered_candidates):
            raise ValueError("BENCHMARK_CPU_REFERENCE_POPULATION_INVALID")
        ranked = []
        offsets = []
        for row in query.ordered_candidates:
            if offset + 8 > len(binary):
                raise ValueError("BENCHMARK_CPU_REFERENCE_OFFSETS_INVALID")
            (score,) = struct.unpack_from("<d", binary, offset)
            if not math.isfinite(score) or not -1.0 <= score <= 1.0:
                raise ValueError("BENCHMARK_CPU_REFERENCE_SCORE_INVALID")
            ranked.append(ScoredBenchmarkRow(row, score))
            offsets.append(offset)
            offset += 8
        clusters = cluster_cpu_benchmark_rows(tuple(ranked))
        if tuple(cluster.row_sha256 for cluster in query.clusters) != tuple(
            tuple(value.row.row_sha256 for value in cluster) for cluster in clusters
        ) or tuple(
            value for cluster in query.clusters for value in cluster.cpu_score_offsets
        ) != tuple(offsets):
            raise ValueError("BENCHMARK_CPU_REFERENCE_CLUSTER_INVALID")
    if offset != len(binary):
        raise ValueError("BENCHMARK_CPU_REFERENCE_OFFSETS_INVALID")
    return reference
