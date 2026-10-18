"""Pure original-series numerical evidence, never an authority or device-default verdict."""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass

from eom_catalog_contracts.embedding_device_benchmark import (
    BENCHMARK_DEVICE_SEQUENCE,
    MAX_BENCHMARK_OUTPUT_BYTES,
    BenchmarkDevice,
    BenchmarkLocalBinary,
    BenchmarkNumericalEvidence,
    BenchmarkOwnerRequest,
    BenchmarkRankDecision,
    BenchmarkSampleKey,
    BenchmarkScoreBinary,
    BenchmarkStagedInputs,
    BenchmarkTokenSample,
    BenchmarkTokenWitness,
    BenchmarkVectorSample,
    BenchmarkWorkerInvocation,
    BenchmarkWorkerResult,
    embedding_device_benchmark_bytes,
    validate_benchmark_invocation,
)
from eom_catalog_contracts.embedding_vector_binary import read_unit_vectors
from eom_identifiers import content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema.exceptions import ValidationError as SchemaError

from eom_catalog_service.embedding_benchmark_cpu_reference import (
    BenchmarkRowVector,
    build_cpu_benchmark_reference,
    validate_cpu_benchmark_reference,
)
from eom_catalog_service.embedding_benchmark_ranking import (
    BenchmarkRankComparison,
    ScoredBenchmarkRow,
    compare_benchmark_row_rankings,
    rank_benchmark_rows,
)

_MINIMUM_COSINE = 0.99999
_MAXIMUM_COMPONENT_ERROR = 1e-4
_INVALID = "BENCHMARK_NUMERICAL_SERIES_INVALID"
type _Matrix = tuple[tuple[float, ...], ...]


@dataclass(frozen=True, slots=True)
class BenchmarkNumericalLaunch:
    """Already resolved original members, not a transferable Artifact/source grant."""

    invocation: BenchmarkWorkerInvocation
    result: BenchmarkWorkerResult
    witness: BenchmarkTokenWitness
    binaries: tuple[tuple[str, bytes], ...]


@dataclass(frozen=True, slots=True)
class BenchmarkRepeatedRankAssessment:
    device: BenchmarkDevice
    launch_ordinal: int
    document_sample: BenchmarkSampleKey
    query_ordinal: int
    repetition: int
    comparison: BenchmarkRankComparison


@dataclass(frozen=True, slots=True)
class BenchmarkSeriesNumericalAssessment:
    evidence: BenchmarkNumericalEvidence
    score_binary: bytes
    repeated_rankings: tuple[BenchmarkRepeatedRankAssessment, ...]


@dataclass(frozen=True, slots=True)
class _DecodedLaunch:
    original: BenchmarkNumericalLaunch
    samples: tuple[tuple[BenchmarkVectorSample, _Matrix], ...]


def _decode(
    request: BenchmarkOwnerRequest,
    inputs: BenchmarkStagedInputs,
    launch: BenchmarkNumericalLaunch,
) -> _DecodedLaunch:
    if type(launch) is not BenchmarkNumericalLaunch or type(launch.binaries) is not tuple:
        raise ValueError(_INVALID)
    invocation, result, witness = launch.invocation, launch.result, launch.witness
    validate_benchmark_invocation(request, invocation, inputs)
    embedding_device_benchmark_bytes(result)
    witness_raw = embedding_device_benchmark_bytes(witness)
    if (
        result.status != "COMPLETED"
        or result.execution_id != invocation.execution_id
        or result.invocation_sha256 != invocation.invocation_sha256
        or result.launch_ordinal != invocation.launch_ordinal
        or result.device != invocation.device
        or witness.invocation_sha256 != invocation.invocation_sha256
        or witness.launch_ordinal != invocation.launch_ordinal
        or result.token_witness is None
        or result.token_witness.byte_count != len(witness_raw)
        or result.token_witness.sha256 != sha256_bytes(witness_raw)
    ):
        raise ValueError(_INVALID)
    members: dict[str, bytes] = {}
    for member in launch.binaries:
        if (
            type(member) is not tuple
            or len(member) != 2
            or type(member[0]) is not str
            or type(member[1]) is not bytes
            or member[0] in members
        ):
            raise ValueError(_INVALID)
        members[member[0]] = member[1]
    if (
        set(members) != {sample.binary.member_name for sample in result.vectors}
        or sum(len(raw) for raw in members.values()) > MAX_BENCHMARK_OUTPUT_BYTES
    ):
        raise ValueError(_INVALID)
    descriptors: dict[str, BenchmarkLocalBinary] = {
        sample.binary.member_name: sample.binary for sample in result.vectors
    }
    decoded = {}
    for name, raw in members.items():
        descriptor = descriptors[name]
        if descriptor.byte_count != len(raw):
            raise ValueError(_INVALID)
        decoded[name] = read_unit_vectors(
            raw, dimension=1024, row_count=len(raw) // 4096, expected_sha256=descriptor.sha256
        )
    samples = []
    supplementary_offset = 0
    for sample, tokens in zip(result.vectors, witness.samples, strict=True):
        key = sample.key
        if key != tokens.key or sample.binary != descriptors[sample.binary.member_name]:
            raise ValueError(_INVALID)
        real_rows = (
            inputs.documents
            if key.phase in {"COLD_DOCUMENT", "WARM_DOCUMENT"}
            else (inputs.queries[(key.query_ordinal or 1) - 1],)
            if key.phase == "QUERY"
            else ()
        )
        expected_tokens: tuple[tuple[str, int, str | None], ...]
        if real_rows:
            expected_tokens = tuple(
                (row.row.row_sha256, row.token_count, row.token_ids_sha256) for row in real_rows
            )
        else:
            fixture = (
                inputs.capacity
                if key.phase == "CAPACITY"
                else inputs.synthetic_cases[(key.synthetic_case or 1) - 1]
            )
            expected_tokens = (
                (fixture.input_text_sha256, fixture.token_count, fixture.token_ids_sha256),
            ) * key.batch_size
        if (
            sample.ordered_rows != tuple(row.row.row_sha256 for row in real_rows)
            or sample.space_sha256
            != (
                invocation.runtime.spaces.query.space_sha256
                if sample.purpose == "QUERY"
                else invocation.runtime.spaces.document.space_sha256
            )
            or tuple(
                (row.row_sha256, row.token_count, row.token_ids_sha256)
                for batch in tokens.batches
                for row in batch.rows
            )
            != expected_tokens
        ):
            raise ValueError(_INVALID)
        if sample.binary.member_name == "supplementary-documents.f32":
            if sample.byte_offset != supplementary_offset:
                raise ValueError(_INVALID)
            supplementary_offset += sample.byte_count
        start = sample.byte_offset // 4096
        matrix = decoded[sample.binary.member_name][start : start + sample.row_count]
        if len(matrix) != sample.row_count:
            raise ValueError(_INVALID)
        samples.append((sample, matrix))
    if supplementary_offset != len(members.get("supplementary-documents.f32", b"")):
        raise ValueError(_INVALID)
    return _DecodedLaunch(launch, tuple(samples))


def _compare_rows(left: _Matrix, right: _Matrix) -> tuple[int, int, int]:
    cosine_failures = component_failures = failed_rows = 0
    for expected, actual in zip(left, right, strict=True):
        # Accepted f32 norms may differ from1 by1e-5. Compare true directional
        # cosine without modifying stored values; ranking retains its old dot rule.
        directional_cosine = math.fsum(a * b for a, b in zip(expected, actual, strict=True)) / (
            math.hypot(*expected) * math.hypot(*actual)
        )
        cosine = directional_cosine < _MINIMUM_COSINE
        component = max(abs(a - b) for a, b in zip(expected, actual, strict=True)) > (
            _MAXIMUM_COMPONENT_ERROR
        )
        cosine_failures += int(cosine)
        component_failures += int(component)
        failed_rows += int(cosine or component)
    return cosine_failures, component_failures, failed_rows


def _same_device(launches: tuple[_DecodedLaunch, ...], inputs: BenchmarkStagedInputs) -> int:
    baseline_documents = launches[0].samples[0][1]
    first_queries: dict[int, _Matrix] = {}
    first_fixtures: dict[tuple[str, str], tuple[float, ...]] = {}
    failures = 0
    cold_tokens = launches[0].original.witness.samples[0].batches
    query_tokens: dict[int, BenchmarkTokenSample] = {}
    for launch in launches:
        for (sample, matrix), tokens in zip(
            launch.samples, launch.original.witness.samples, strict=True
        ):
            key = sample.key
            if key.phase in {"COLD_DOCUMENT", "WARM_DOCUMENT"}:
                if tokens.batches != cold_tokens:
                    raise ValueError(_INVALID)
                failures += _compare_rows(baseline_documents, matrix)[2]
            elif key.phase == "QUERY":
                query = key.query_ordinal or 1
                if query not in first_queries:
                    first_queries[query], query_tokens[query] = matrix, tokens
                if tokens.batches != query_tokens[query].batches:
                    raise ValueError(_INVALID)
                failures += _compare_rows(first_queries[query], matrix)[2]
            else:
                fixture = (
                    inputs.capacity
                    if key.phase == "CAPACITY"
                    else inputs.synthetic_cases[(key.synthetic_case or 1) - 1]
                )
                # Duplicate public text remains the same input even when its
                # independently prescribed case ordinals differ.
                fixture_key = key.phase, fixture.input_text_sha256
                expected = first_fixtures.setdefault(fixture_key, matrix[0])
                failures += _compare_rows((expected,) * len(matrix), matrix)[2]
    return failures


def _documents(request: BenchmarkOwnerRequest, matrix: _Matrix) -> tuple[BenchmarkRowVector, ...]:
    return tuple(zip(request.document_rows, matrix, strict=True))


def _assess(
    request: BenchmarkOwnerRequest,
    inputs: BenchmarkStagedInputs,
    launches: tuple[BenchmarkNumericalLaunch, ...],
    reference_pointer: ArtifactMemberPointer,
    reference_raw: bytes,
    reference_scores: bytes,
) -> BenchmarkSeriesNumericalAssessment:
    if type(launches) is not tuple or len(launches) != 6:
        raise ValueError(_INVALID)
    decoded = tuple(_decode(request, inputs, launch) for launch in launches)
    if (
        tuple(launch.invocation.device for launch in launches) != BENCHMARK_DEVICE_SEQUENCE
        or tuple(launch.invocation.launch_ordinal for launch in launches) != tuple(range(1, 7))
        or len({launch.invocation.job_id for launch in launches}) != 1
        or len({launch.invocation.execution_id for launch in launches}) != 6
    ):
        raise ValueError(_INVALID)
    reference = validate_cpu_benchmark_reference(
        request, reference_pointer, reference_raw, reference_scores
    )
    cpu, cuda = decoded[0], decoded[1]
    cpu_queries = tuple(
        (request.query_rows[(sample.key.query_ordinal or 1) - 1], matrix[0])
        for sample, matrix in cpu.samples
        if sample.key.phase == "QUERY" and sample.key.repetition == 1
    )
    regenerated, scores = build_cpu_benchmark_reference(
        launches[0].invocation,
        _documents(request, cpu.samples[0][1]),
        cpu_queries,
        artifact_id=reference_pointer.artifact_id,
        artifact_revision_id=reference_pointer.artifact_revision_id,
    )
    if regenerated != reference or scores != reference_scores:
        raise ValueError(_INVALID)
    cosine_failures = component_failures = 0
    # Every original cold pair plus all first-invocation warm/query/fixture pairs.
    for left, right in (
        (decoded[0], decoded[1]),
        (decoded[3], decoded[2]),
        (decoded[4], decoded[5]),
    ):
        for (sample, matrix), (other, actual), tokens, other_tokens in zip(
            left.samples,
            right.samples,
            left.original.witness.samples,
            right.original.witness.samples,
            strict=True,
        ):
            if sample.key != other.key or tokens.batches != other_tokens.batches:
                raise ValueError(_INVALID)
            cosine, component, _ = _compare_rows(matrix, actual)
            cosine_failures += cosine
            component_failures += component
    same_device_failures = sum(
        _same_device(
            tuple(run for run in decoded if run.original.invocation.device == device), inputs
        )
        for device in ("CPU", "CUDA")
    )
    binary = bytearray(reference_scores)
    decisions: list[BenchmarkRankDecision] = []
    repeated = []
    query_score_failures = wide_failures = cluster_failures = boundary_failures = 0
    for query in reference.queries:
        offsets = {
            row: offset
            for cluster in query.clusters
            for row, offset in zip(cluster.row_sha256, cluster.cpu_score_offsets, strict=True)
        }
        baseline = tuple(
            ScoredBenchmarkRow(
                row, struct.unpack_from("<d", reference_scores, offsets[row.row_sha256])[0]
            )
            for row in query.ordered_candidates
        )
        for launch in decoded:
            first = cpu if launch.original.invocation.device == "CPU" else cuda
            queries = tuple(
                (sample, matrix[0])
                for sample, matrix in first.samples
                if sample.key.phase == "QUERY" and sample.key.query_ordinal == query.query_ordinal
            )
            for document_sample, matrix in launch.samples:
                if document_sample.key.phase not in {"COLD_DOCUMENT", "WARM_DOCUMENT"}:
                    continue
                documents = _documents(request, matrix)
                for query_sample, vector in queries:
                    observed = rank_benchmark_rows(query.query_row, vector, documents)
                    compared = compare_benchmark_row_rankings(baseline, observed)
                    repetition = query_sample.key.repetition or 1
                    canonical = launch is cuda and document_sample.key.phase == "COLD_DOCUMENT"
                    if not canonical:
                        repeated.append(
                            BenchmarkRepeatedRankAssessment(
                                launch.original.invocation.device,
                                launch.original.invocation.launch_ordinal,
                                document_sample.key,
                                query.query_ordinal,
                                repetition,
                                compared,
                            )
                        )
                        same_device_failures += int(not compared.ranks_equivalent_within_tolerance)
                        continue
                    query_score_failures += compared.query_score_failures
                    wide_failures += compared.wide_gap_order_failures
                    cluster_failures += compared.cluster_order_failures
                    boundary_failures += compared.top5_boundary_failures
                    actual_offsets = {}
                    for scored in observed:
                        actual_offsets[scored.row.row_sha256] = len(binary)
                        binary.extend(struct.pack("<d", scored.cosine_similarity))
                    decisions.extend(
                        BenchmarkRankDecision(
                            query_ordinal=query.query_ordinal,
                            repetition=repetition,
                            left_row_sha256=value.left_row_sha256,
                            right_row_sha256=value.right_row_sha256,
                            cpu_left_offset=offsets[value.left_row_sha256],
                            cpu_right_offset=offsets[value.right_row_sha256],
                            cuda_left_offset=actual_offsets[value.left_row_sha256],
                            cuda_right_offset=actual_offsets[value.right_row_sha256],
                            gap_class=value.gap_class,
                            order_preserved=value.order_preserved,
                            top5_same_cluster=value.top5_same_cluster,
                        )
                        for value in compared.observations
                    )
    raw = bytes(binary)
    body = dict(
        schema_version="embedding-device-benchmark-numerical-evidence/1.0",
        input_set_sha256=request.input_set_sha256,
        family_sha256=request.family.family_sha256,
        score_binary=BenchmarkScoreBinary(sha256=sha256_bytes(raw), byte_count=len(raw)).model_dump(
            mode="json"
        ),
        near_tie_reference=reference_pointer.model_dump(mode="json"),
        norm_failures=0,
        cosine_failures=cosine_failures,
        component_failures=component_failures,
        query_score_failures=query_score_failures,
        wide_gap_order_failures=wide_failures,
        cluster_order_failures=cluster_failures,
        top5_boundary_failures=boundary_failures,
        same_device_failures=same_device_failures,
        decisions=[
            value.model_dump(mode="json")
            for value in sorted(
                decisions,
                key=lambda value: (
                    value.query_ordinal,
                    value.repetition,
                    value.left_row_sha256,
                    value.right_row_sha256,
                ),
            )
        ],
    )
    evidence = BenchmarkNumericalEvidence.model_validate(
        body | {"numerical_sha256": content_sha256(body)}
    )
    return BenchmarkSeriesNumericalAssessment(evidence, raw, tuple(repeated))


def assess_benchmark_series_numerics(
    request: BenchmarkOwnerRequest,
    inputs: BenchmarkStagedInputs,
    launches: tuple[BenchmarkNumericalLaunch, ...],
    *,
    reference_pointer: ArtifactMemberPointer,
    reference_raw: bytes,
    reference_scores: bytes,
) -> BenchmarkSeriesNumericalAssessment:
    """All original samples, no source/chronology/cleanup/performance/default assertion.

    The caller must independently resolve/authorize original Artifacts and prove
    CPU1 was sealed before CUDA. Parsed pointers and these pure values cannot.
    """
    try:
        return _assess(
            request, inputs, launches, reference_pointer, reference_raw, reference_scores
        )
    except (ValueError, TypeError, SchemaError, AttributeError, KeyError, IndexError, struct.error):
        raise ValueError(_INVALID) from None
