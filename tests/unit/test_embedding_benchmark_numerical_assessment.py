"""Real synthetic-worker f32 bytes, not model/source/OS or six live-run acceptance."""

from __future__ import annotations

import math
import struct
from dataclasses import FrozenInstanceError, replace

import pytest
from eom_catalog_contracts.embedding_device_benchmark import (
    MAX_BENCHMARK_OUTPUT_BYTES,
    BenchmarkTokenWitness,
    BenchmarkWorkerInvocation,
    BenchmarkWorkerResult,
    embedding_device_benchmark_bytes,
    parse_embedding_device_benchmark_bytes,
)
from eom_catalog_service.embedding_benchmark_cpu_reference import (
    CPU_REFERENCE_SCHEMA,
    build_cpu_benchmark_reference,
)
from eom_catalog_service.embedding_benchmark_numerical_assessment import (
    BenchmarkNumericalLaunch,
    assess_benchmark_series_numerics,
)
from eom_identifiers import sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer

from tests.unit.embedding_device_benchmark_fixtures import (
    owner_request,
    staged_inputs,
    worker_invocation,
)
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_device_benchmark_worker import run_scenario


def reseal_launch(launch, *, invocation=None, witness=None, result_body=None, binaries=None):
    invocation = invocation or launch.invocation
    body = (witness or launch.witness).model_dump(mode="json")
    body["invocation_sha256"] = invocation.invocation_sha256
    witness = BenchmarkTokenWitness.model_validate(seal(body, "witness_sha256"))
    raw = embedding_device_benchmark_bytes(witness)
    body = result_body or launch.result.model_dump(mode="json")
    body.update(
        invocation_sha256=invocation.invocation_sha256, execution_id=invocation.execution_id
    )
    body["token_witness"].update(sha256=sha256_bytes(raw), byte_count=len(raw))
    for member, hash_key in (("timings", "timing_sha256"), ("resources", "resource_sha256")):
        body[member]["invocation_sha256"] = invocation.invocation_sha256
        body[member] = seal(body[member], hash_key)
    result = BenchmarkWorkerResult.model_validate(seal(body, "result_sha256"))
    return BenchmarkNumericalLaunch(invocation, result, witness, binaries or launch.binaries)


@pytest.fixture(scope="module")
def series(tmp_path_factory):
    launches = []
    for ordinal in range(1, 7):
        path = tmp_path_factory.mktemp(f"numerical-{ordinal}")
        with pytest.MonkeyPatch.context() as patch:
            result, _backend, _events, root, _checkpoints = run_scenario(path, patch, ordinal)
        assert result.status == "COMPLETED"
        output = root / "outputs"
        witness = parse_embedding_device_benchmark_bytes(
            (output / "token-witness.json").read_bytes(), maximum_bytes=MAX_BENCHMARK_OUTPUT_BYTES
        )
        assert isinstance(witness, BenchmarkTokenWitness)
        invocation = BenchmarkWorkerInvocation.model_validate(
            seal(
                worker_invocation(ordinal).model_dump(mode="json") | {"job_id": "job_" + "a" * 32},
                "invocation_sha256",
            )
        )
        binaries = tuple(sorted((p.name, p.read_bytes()) for p in output.glob("*.f32")))
        launches.append(
            reseal_launch(
                BenchmarkNumericalLaunch(
                    invocation,
                    result,
                    witness,
                    binaries,
                )
            )
        )
    return tuple(launches)


def reference(series):
    request = owner_request()
    unit = (1.0,) + (0.0,) * 1023
    value, scores = build_cpu_benchmark_reference(
        series[0].invocation,
        tuple((row, unit) for row in request.document_rows),
        tuple((row, unit) for row in request.query_rows),
        artifact_id="artifact_" + "a" * 32,
        artifact_revision_id="rev_" + "b" * 32,
    )
    raw = embedding_device_benchmark_bytes(value)
    pointer = ArtifactMemberPointer(
        artifact_id=value.score_binary.artifact_id,
        artifact_revision_id=value.score_binary.artifact_revision_id,
        member_path="near-tie-reference.json",
        schema_ref=CPU_REFERENCE_SCHEMA,
        media_type="application/json",
        sha256=sha256_bytes(raw),
    )
    return pointer, raw, scores


def assess(series, *, selected=None):
    pointer, raw, scores = selected or reference(series)
    return assess_benchmark_series_numerics(
        owner_request(),
        staged_inputs(),
        series,
        reference_pointer=pointer,
        reference_raw=raw,
        reference_scores=scores,
    )


def change_vector(launch, *, member="cold-documents.f32", row=0, delta=0.01):
    members = dict(launch.binaries)
    raw = bytearray(members[member])
    struct.pack_into(
        "<1024f", raw, row * 4096, math.sqrt(1 - delta * delta), delta, *([0.0] * 1022)
    )
    members[member] = bytes(raw)
    body = launch.result.model_dump(mode="json")
    for sample in body["vectors"]:
        if sample["binary"]["member_name"] == member:
            sample["binary"]["sha256"] = sha256_bytes(members[member])
            sample.update(seal(sample, "sample_sha256"))
    return reseal_launch(launch, result_body=body, binaries=tuple(sorted(members.items())))


@pytest.fixture(params=[False, True], ids=["same-cluster", "cross-cluster"])
def mixed_score_series(series, request):
    owner = owner_request()
    cross_cluster = request.param
    common_rows = tuple(
        row
        for row in owner.document_rows
        if all(row.profile != query.profile for query in owner.query_rows)
    )
    assert len(common_rows) == 12
    gap = 2.0**-16
    boundary_scores = (
        (0.5 + 2 * gap, 0.5, 0.5 - gap) if cross_cluster else (0.8, 0.5 + gap / 2, 0.5 - gap / 2)
    )
    # Both queries exclude different profiles, but share these actual top6 rows.
    cpu_scores = {
        row.row_sha256: 0.1 - index * 0.003 for index, row in enumerate(owner.document_rows)
    }
    cpu_scores.update(
        (row.row_sha256, score)
        for row, score in zip(
            common_rows,
            (0.95, 0.9, 0.85, *boundary_scores, *(0.4 - index * 0.03 for index in range(6))),
            strict=True,
        )
    )
    left, right = (row.row_sha256 for row in common_rows[4:6])
    cuda_scores = cpu_scores | {left: cpu_scores[right], right: cpu_scores[left]}
    raw_documents = {
        device: b"".join(
            struct.pack(
                "<1024f",
                scores[row.row_sha256],
                math.sqrt(1 - scores[row.row_sha256] ** 2),
                *([0.0] * 1022),
            )
            for row in owner.document_rows
        )
        for device, scores in (("CPU", cpu_scores), ("CUDA", cuda_scores))
    }
    matrices = {
        device: tuple(struct.iter_unpack("<1024f", raw)) for device, raw in raw_documents.items()
    }
    # Offset assertions use the durable f32 values, not pre-serialization doubles.
    scores_by_device = {
        device: {
            row.row_sha256: vector[0]
            for row, vector in zip(owner.document_rows, matrix, strict=True)
        }
        for device, matrix in matrices.items()
    }
    launches = []
    for launch in series:
        members = dict(launch.binaries)
        document_raw = raw_documents[launch.invocation.device]
        members["cold-documents.f32"] = document_raw
        if "supplementary-documents.f32" in members:
            supplementary = bytearray(members["supplementary-documents.f32"])
            for sample in launch.result.vectors:
                if sample.key.phase == "WARM_DOCUMENT":
                    supplementary[sample.byte_offset : sample.byte_offset + sample.byte_count] = (
                        document_raw
                    )
            members["supplementary-documents.f32"] = bytes(supplementary)
        member_hashes = {name: sha256_bytes(raw) for name, raw in members.items()}
        body = launch.result.model_dump(mode="json")
        for sample in body["vectors"]:
            sample["binary"]["sha256"] = member_hashes[sample["binary"]["member_name"]]
            sample.update(seal(sample, "sample_sha256"))
        launches.append(
            reseal_launch(launch, result_body=body, binaries=tuple(sorted(members.items())))
        )
    unit = (1.0,) + (0.0,) * 1023
    value, scores = build_cpu_benchmark_reference(
        launches[0].invocation,
        tuple(zip(owner.document_rows, matrices["CPU"], strict=True)),
        tuple((row, unit) for row in owner.query_rows),
        artifact_id="artifact_" + "a" * 32,
        artifact_revision_id="rev_" + "b" * 32,
    )
    raw = embedding_device_benchmark_bytes(value)
    pointer = ArtifactMemberPointer(
        artifact_id=value.score_binary.artifact_id,
        artifact_revision_id=value.score_binary.artifact_revision_id,
        member_path="near-tie-reference.json",
        schema_ref=CPU_REFERENCE_SCHEMA,
        media_type="application/json",
        sha256=sha256_bytes(raw),
    )
    return tuple(launches), (pointer, raw, scores), scores_by_device, (left, right), cross_cluster


def test_mixed_scores_preserve_cpu_clusters_top5_semantics_and_row_specific_offsets(
    mixed_score_series,
):
    launches, selected, scores_by_device, swapped_rows, cross_cluster = mixed_score_series
    result = assess(launches, selected=selected)
    evidence = result.evidence
    for field in (
        "norm_failures",
        "cosine_failures",
        "component_failures",
        "query_score_failures",
        "wide_gap_order_failures",
    ):
        assert getattr(evidence, field) == 0
    assert (
        evidence.cluster_order_failures
        == evidence.top5_boundary_failures
        == (10 if cross_cluster else 0)
    )
    assert evidence.same_device_failures == (70 if cross_cluster else 0)
    assert {decision.gap_class for decision in evidence.decisions} == {"NEAR_TIE", "WIDE_GAP"}
    swaps = tuple(decision for decision in evidence.decisions if not decision.order_preserved)
    assert len(swaps) == 10
    for decision in swaps:
        assert {decision.left_row_sha256, decision.right_row_sha256} == set(swapped_rows)
        assert decision.gap_class == "NEAR_TIE"
        assert decision.top5_same_cluster is not cross_cluster
    cpu_offsets, cuda_offsets = {}, {}
    for decision in evidence.decisions:
        for side in ("left", "right"):
            row_hash = getattr(decision, f"{side}_row_sha256")
            for device, offsets in (("CPU", cpu_offsets), ("CUDA", cuda_offsets)):
                offset = getattr(decision, f"{device.lower()}_{side}_offset")
                key = (decision.query_ordinal, row_hash)
                if device == "CUDA":
                    key = (*key, decision.repetition)
                assert offsets.setdefault(key, offset) == offset
                assert offset % 8 == 0 and 0 <= offset <= len(result.score_binary) - 8
                assert struct.unpack_from("<d", result.score_binary, offset) == (
                    scores_by_device[device][row_hash],
                )
    assert len(cpu_offsets) == 30 and len(cuda_offsets) == 150
    assert result.score_binary.startswith(selected[2])
    assert set(cpu_offsets.values()) == set(range(0, len(selected[2]), 8))
    assert set(cuda_offsets.values()) == set(range(len(selected[2]), len(result.score_binary), 8))
    assert evidence.score_binary.sha256 == sha256_bytes(result.score_binary)
    assert evidence.score_binary.byte_count == len(result.score_binary) == 1440


def test_all_original_samples_cpu_seal_canonical_f64_decisions_and_repeated_ranks(series):
    result = assess(series)
    evidence = result.evidence
    for field in (
        "norm_failures",
        "cosine_failures",
        "component_failures",
        "query_score_failures",
        "wide_gap_order_failures",
        "cluster_order_failures",
        "top5_boundary_failures",
        "same_device_failures",
    ):
        assert getattr(evidence, field) == 0
    assert len(evidence.decisions) == 1050
    assert len(result.repeated_rankings) == 150
    assert result.score_binary.startswith(reference(series)[2])
    assert evidence.score_binary.sha256 == sha256_bytes(result.score_binary)
    assert evidence.score_binary.byte_count == len(result.score_binary) == 1440
    for decision in evidence.decisions:
        assert decision.gap_class == "EXACT_TIE" and decision.order_preserved
        assert struct.unpack_from("<d", result.score_binary, decision.cpu_left_offset) == (1.0,)
        assert struct.unpack_from("<d", result.score_binary, decision.cuda_right_offset) == (1.0,)
    assert not hasattr(result, "default_device") and not hasattr(result, "source_authorized")
    with pytest.raises(FrozenInstanceError):
        result.score_binary = b"changed"


def test_same_exact_input_is_deterministic_without_a_run_or_mutation(series):
    first = assess(series)
    second = assess(series)
    assert first == second
    assert embedding_device_benchmark_bytes(first.evidence) == embedding_device_benchmark_bytes(
        second.evidence
    )


def test_each_immutable_f32_member_is_decoded_once_not_once_per_rank_or_sample(series, monkeypatch):
    from eom_catalog_service import embedding_benchmark_numerical_assessment as module

    reader = module.read_unit_vectors
    calls = []

    def observed(*args, **kwargs):
        calls.append(kwargs["expected_sha256"])
        return reader(*args, **kwargs)

    monkeypatch.setattr(module, "read_unit_vectors", observed)
    assess(series)
    assert len(calls) == sum(len(launch.binaries) for launch in series) == 28


@pytest.mark.parametrize("ordinal", range(1, 7))
def test_no_original_cold_drift_can_be_discarded(series, ordinal):
    changed = list(series)
    changed[ordinal - 1] = change_vector(changed[ordinal - 1])
    if ordinal == 1:
        with pytest.raises(ValueError, match="BENCHMARK_NUMERICAL_SERIES_INVALID"):
            assess(tuple(changed), selected=reference(series))
    else:
        result = assess(tuple(changed))
        assert result.evidence.cosine_failures > 0
        assert result.evidence.component_failures > 0
        assert result.evidence.same_device_failures > 0


@pytest.mark.parametrize(
    "ordinal,member,row",
    [
        (2, "supplementary-documents.f32", 0),
        (2, "supplementary-documents.f32", 35),
        (2, "supplementary-documents.f32", 124),
        (2, "query-2-5.f32", 0),
        (1, "supplementary-documents.f32", 35),
        (1, "supplementary-documents.f32", 120),
        (1, "query-2-5.f32", 0),
    ],
)
def test_warm_last_query_and_synthetic_batch_rows_are_all_assessed(series, ordinal, member, row):
    changed = list(series)
    changed[ordinal - 1] = change_vector(changed[ordinal - 1], member=member, row=row)
    result = assess(tuple(changed))
    assert result.evidence.cosine_failures > 0 and result.evidence.component_failures > 0
    assert result.evidence.same_device_failures > 0


@pytest.mark.parametrize("delta,failures", [(1e-4, False), (0.0001001, True)])
def test_fixed_component_threshold_is_not_rounded_or_posthoc_relaxed(series, delta, failures):
    changed = list(series)
    changed[5] = change_vector(changed[5], delta=delta)
    result = assess(tuple(changed))
    assert (result.evidence.component_failures > 0) is failures
    assert result.evidence.cosine_failures == 0


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "extra",
        "reorder",
        "list",
        "foreign_job",
        "reused_execution",
        "failed",
        "member_missing",
        "member_extra",
        "member_duplicate",
        "member_mutable",
        "bad_hash",
        "norm",
        "nan",
        "row_order",
        "space",
        "range",
        "result_pin",
        "witness_pin",
        "private_extra",
    ],
)
def test_incomplete_foreign_or_invalid_original_evidence_fails_without_content(series, fault):
    changed = list(series)
    launch = changed[2]
    if fault == "missing":
        changed.pop()
    elif fault == "extra":
        changed.append(changed[-1])
    elif fault == "reorder":
        changed[2], changed[5] = changed[5], changed[2]
    elif fault in {"foreign_job", "reused_execution"}:
        body = launch.invocation.model_dump(mode="json")
        body["job_id" if fault == "foreign_job" else "execution_id"] = (
            "job_" + "f" * 32 if fault == "foreign_job" else changed[0].invocation.execution_id
        )
        invocation = BenchmarkWorkerInvocation.model_validate(seal(body, "invocation_sha256"))
        changed[2] = reseal_launch(launch, invocation=invocation)
    elif fault.startswith("member_") or fault in {"bad_hash", "norm", "nan"}:
        members = list(launch.binaries)
        if fault == "member_missing":
            members.pop()
        elif fault == "member_extra":
            members.append(("extra.f32", members[0][1]))
        elif fault == "member_duplicate":
            members.append(members[0])
        elif fault == "member_mutable":
            members[0] = (members[0][0], bytearray(members[0][1]))
        else:
            raw = bytearray(members[0][1])
            struct.pack_into("<f", raw, 0, float("nan") if fault == "nan" else 0.5)
            members[0] = (members[0][0], bytes(raw))
            if fault != "bad_hash":
                body = launch.result.model_dump(mode="json")
                body["vectors"][0]["binary"]["sha256"] = sha256_bytes(bytes(raw))
                body["vectors"][0] = seal(body["vectors"][0], "sample_sha256")
                launch = reseal_launch(launch, result_body=body)
        changed[2] = replace(launch, binaries=tuple(members))
    elif fault == "witness_pin":
        changed[2] = replace(launch, witness=series[5].witness)
    else:
        body = launch.result.model_dump(mode="json")
        if fault == "failed":
            body.update(status="FAILED", reason_codes=["TEST_FAILURE"])
        elif fault == "result_pin":
            body["invocation_sha256"] = "sha256:" + "f" * 64
            for member, hash_key in (
                ("timings", "timing_sha256"),
                ("resources", "resource_sha256"),
            ):
                body[member]["invocation_sha256"] = body["invocation_sha256"]
                body[member] = seal(body[member], hash_key)
        elif fault == "row_order":
            body["vectors"][0]["ordered_rows"].reverse()
        elif fault == "space":
            body["vectors"][0]["space_sha256"] = "sha256:" + "f" * 64
        elif fault == "range":
            body["vectors"][0]["byte_offset"] = 4096
        elif fault == "private_extra":
            changed[2] = replace(
                launch, result=launch.result.model_copy(update={"private_note": "PRIVATE_SENTINEL"})
            )
        if fault != "private_extra":
            if fault in {"row_order", "space", "range"}:
                body["vectors"][0] = seal(body["vectors"][0], "sample_sha256")
            if fault == "range":
                # A forged post-construction model must not skip revalidation.
                sample = launch.result.vectors[0].model_copy(update={"byte_offset": 4096})
                result = launch.result.model_copy(update={"vectors": (sample,)})
            else:
                result = BenchmarkWorkerResult.model_validate(seal(body, "result_sha256"))
            changed[2] = replace(launch, result=result)
    with pytest.raises(ValueError, match="BENCHMARK_NUMERICAL_SERIES_INVALID") as error:
        assess(changed if fault == "list" else tuple(changed))
    assert "PRIVATE_SENTINEL" not in str(error.value)


def test_reference_pointer_and_binary_hash_are_not_substituted_with_latest(series):
    pointer, raw, scores = reference(series)
    for selected in (
        (pointer.model_copy(update={"sha256": "sha256:" + "f" * 64}), raw, scores),
        (pointer, raw, scores[:-8]),
        (pointer.model_copy(update={"artifact_revision_id": "rev_" + "f" * 32}), raw, scores),
    ):
        with pytest.raises(ValueError, match="BENCHMARK_NUMERICAL_SERIES_INVALID"):
            assess(series, selected=selected)


def test_rehashed_token_padding_metadata_still_cannot_drift_between_original_runs(series):
    changed = list(series)
    launch = changed[2]
    body = launch.witness.model_dump(mode="json")
    batch = body["samples"][0]["batches"][0]
    assert all(row["token_count"] == len(row["input_ids"]) for row in batch["rows"])
    batch["pad_token_id"] = 1
    body["samples"][0]["batches"][0] = seal(batch, "batch_sha256")
    body["samples"][0] = seal(body["samples"][0], "sample_sha256")
    witness = BenchmarkTokenWitness.model_validate(seal(body, "witness_sha256"))
    changed[2] = reseal_launch(launch, witness=witness)
    with pytest.raises(ValueError, match="BENCHMARK_NUMERICAL_SERIES_INVALID"):
        assess(tuple(changed))


def test_validly_rehashed_cpu_reference_scores_must_still_equal_actual_cpu1_f32(series):
    from eom_catalog_contracts.embedding_device_benchmark import BenchmarkNearTieReference

    pointer, raw, scores = reference(series)
    value = parse_embedding_device_benchmark_bytes(raw)
    assert isinstance(value, BenchmarkNearTieReference)
    scores = struct.pack("<d", 0.99999) * (len(scores) // 8)
    body = value.model_dump(mode="json")
    body["score_binary"]["sha256"] = sha256_bytes(scores)
    value = BenchmarkNearTieReference.model_validate(seal(body, "reference_sha256"))
    raw = embedding_device_benchmark_bytes(value)
    pointer = pointer.model_copy(update={"sha256": sha256_bytes(raw)})
    with pytest.raises(ValueError, match="BENCHMARK_NUMERICAL_SERIES_INVALID"):
        assess(series, selected=(pointer, raw, scores))


def test_duplicate_synthetic_cases_cannot_drift_identically_on_both_devices(series):
    changed = list(series)
    for index in (0, 1):
        launch = changed[index]
        members = dict(launch.binaries)
        raw = bytearray(members["supplementary-documents.f32"])
        body = launch.result.model_dump(mode="json")
        for sample in body["vectors"]:
            if sample["key"]["synthetic_case"] == 6:
                for row in range(sample["row_count"]):
                    struct.pack_into(
                        "<1024f",
                        raw,
                        sample["byte_offset"] + row * 4096,
                        math.sqrt(1 - 0.01**2),
                        0.01,
                        *([0.0] * 1022),
                    )
        members["supplementary-documents.f32"] = bytes(raw)
        for sample in body["vectors"]:
            if sample["binary"]["member_name"] == "supplementary-documents.f32":
                sample["binary"]["sha256"] = sha256_bytes(bytes(raw))
                sample.update(seal(sample, "sample_sha256"))
        changed[index] = reseal_launch(
            launch, result_body=body, binaries=tuple(sorted(members.items()))
        )
    result = assess(tuple(changed))
    assert result.evidence.cosine_failures == result.evidence.component_failures == 0
    assert result.evidence.same_device_failures == 10


@pytest.mark.parametrize("scale", [0.999991, 1.000009])
def test_accepted_f32_norm_roundoff_does_not_fake_directional_cosine_failure(series, scale):
    changed = list(series)
    for index in (2, 3):
        launch = changed[index]
        members = dict(launch.binaries)
        raw = struct.pack("<1024f", scale, *([0.0] * 1023)) * len(owner_request().document_rows)
        members["cold-documents.f32"] = raw
        body = launch.result.model_dump(mode="json")
        sample = body["vectors"][0]
        sample["binary"]["sha256"] = sha256_bytes(raw)
        body["vectors"][0] = seal(sample, "sample_sha256")
        changed[index] = reseal_launch(
            launch, result_body=body, binaries=tuple(sorted(members.items()))
        )
    result = assess(tuple(changed))
    assert result.evidence.norm_failures == 0
    assert result.evidence.cosine_failures == result.evidence.component_failures == 0
    assert result.evidence.same_device_failures == 0
