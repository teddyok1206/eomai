"""Source-contract evidence only: no real corpus, installed runtime or benchmark invocation."""

from __future__ import annotations

import ast
import copy
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from eom_catalog_contracts import embedding_device_benchmark as contracts
from eom_catalog_contracts.embedding_device_benchmark import (
    EMBEDDING_DEVICE_BENCHMARK_SCHEMA,
    EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF,
    BenchmarkAck,
    BenchmarkCheckpoint,
    BenchmarkDevice,
    BenchmarkInvocationTimings,
    BenchmarkModelFamily,
    BenchmarkNearTieReference,
    BenchmarkNumericalEvidence,
    BenchmarkOwnerRequest,
    BenchmarkOwnerResult,
    BenchmarkResourceEvidence,
    BenchmarkSession,
    BenchmarkStagedInputs,
    BenchmarkTextRow,
    BenchmarkTimingEvidence,
    BenchmarkTokenBatch,
    BenchmarkTokenWitness,
    BenchmarkVectorSample,
    BenchmarkWorkerInvocation,
    BenchmarkWorkerResult,
    benchmark_model_family_sha256,
    embedding_device_benchmark_bytes,
    parse_embedding_device_benchmark,
    parse_embedding_device_benchmark_bytes,
    validate_benchmark_invocation,
    validate_benchmark_staged_inputs,
)
from eom_catalog_contracts.embedding_runtime_bundle import EmbeddingNumericalRecipe
from eom_catalog_contracts.item_inference_transfer import LocalEmbeddingModelSpec
from eom_catalog_contracts.models import FrozenModel
from eom_catalog_contracts.validation import (
    CATALOG_SCHEMA_RESOURCES,
    catalog_schema_registry,
    load_schema,
    validate_contract,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from tests.unit.embedding_device_benchmark_fixtures import (
    benchmark_family,
    benchmark_policy,
    benchmark_recipe,
    cold_token_witness,
    insufficient_result,
    invocation_timings,
    launch_receipt,
    measured_result,
    near_tie_reference,
    numerical_evidence,
    owner_gates,
    owner_request,
    resources,
    session,
    staged_inputs,
    timing_evidence,
    vector_evidence,
    vector_samples,
    worker_invocation,
    worker_result,
)
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.inference_transfer_fixtures import sha

ROOT = Path(__file__).resolve().parents[2]


def test_single_schema_mirror_raw_pin_and_all_references_resolve_locally() -> None:
    resource = CATALOG_SCHEMA_RESOURCES[EMBEDDING_DEVICE_BENCHMARK_SCHEMA]
    canonical = (ROOT / resource.canonical_path).read_bytes()
    packaged = (
        ROOT / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
    ).read_bytes()
    assert canonical == packaged
    assert sha256_bytes(canonical) == resource.sha256
    schema = load_schema(EMBEDDING_DEVICE_BENCHMARK_SCHEMA)
    Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF
    refs: set[str] = set()

    def visit(value: object) -> None:
        if isinstance(value, dict):
            if "$ref" in value:
                refs.add(value["$ref"])
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(schema)
    resolver = catalog_schema_registry().resolver()
    for ref in refs:
        resolver.lookup(EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF + ref if ref.startswith("#") else ref)
    for definition in schema["$defs"].values():
        if definition.get("type") == "object":
            assert definition["additionalProperties"] is False


@pytest.mark.parametrize(
    "factory",
    (
        benchmark_family,
        benchmark_recipe,
        benchmark_policy,
        owner_request,
        staged_inputs,
        worker_invocation,
        session,
        invocation_timings,
        timing_evidence,
        resources,
        worker_result,
        cold_token_witness,
        owner_gates,
        insufficient_result,
        measured_result,
        launch_receipt,
        vector_evidence,
        near_tie_reference,
        numerical_evidence,
    ),
)
def test_primary_frozen_value_and_raw_roundtrip(factory: Callable[[], FrozenModel]) -> None:
    value = factory()
    body = value.model_dump(mode="json")
    before = copy.deepcopy(body)
    checked = parse_embedding_device_benchmark(body)
    raw = embedding_device_benchmark_bytes(checked)
    assert checked == value
    bound = (
        contracts.MAX_BENCHMARK_STAGED_BYTES
        if isinstance(value, BenchmarkStagedInputs)
        else contracts.MAX_BENCHMARK_OUTPUT_BYTES
        if isinstance(
            value,
            (BenchmarkTokenWitness, BenchmarkNumericalEvidence, contracts.BenchmarkVectorEvidence),
        )
        else contracts.MAX_BENCHMARK_ENVELOPE_BYTES
    )
    assert parse_embedding_device_benchmark_bytes(raw, maximum_bytes=bound) == value
    assert raw == canonical_json_bytes(body)
    assert body == before
    frozen_field = "schema_version"
    with pytest.raises(ValidationError):
        setattr(value, frozen_field, "altered")


@pytest.mark.parametrize("ordinal", range(1, 7))
def test_six_invocations_are_exact_serial_device_projections(ordinal: int) -> None:
    invocation = worker_invocation(ordinal)
    validate_benchmark_invocation(owner_request(), invocation, staged_inputs())
    assert invocation.device == ("CPU", "CUDA", "CUDA", "CPU", "CPU", "CUDA")[ordinal - 1]
    assert invocation.owner_request_sha256 != invocation.invocation_sha256
    assert invocation.local_input.sha256 != invocation.input_set_sha256
    assert invocation.benchmark_id != invocation.benchmark_revision_id


def test_real_rows_all_views_and_query_purpose_are_not_registered_encodings() -> None:
    request, inputs = owner_request(), staged_inputs()
    validate_benchmark_staged_inputs(request, inputs)
    assert len(request.document_rows) == 18
    assert len(request.query_rows) == 2
    assert len({row.profile.profile_id for row in request.document_rows}) == 6
    for query in request.query_rows:
        documents = [
            row
            for row in request.document_rows
            if row.profile == query.profile and row.view == query.view
        ]
        assert len(documents) == 1
        assert documents[0].input_text_sha256 == query.input_text_sha256
        assert documents[0].row_sha256 != query.row_sha256
        assert documents[0].purpose == "DOCUMENT" and query.purpose == "QUERY"
    assert (
        len(
            {
                space.space_sha256
                for runtime in (request.cpu, request.cuda)
                for space in (runtime.spaces.document, runtime.spaces.query)
            }
        )
        == 4
    )
    assert not {"encoding_sha256", "storage_partition", "row_ref", "shard"}.intersection(
        contracts.BenchmarkRowRef.model_fields
    )


@pytest.mark.parametrize(
    "field",
    (
        "role",
        "actor_id",
        "authority",
        "source_grant",
        "db_uri",
        "nas_uri",
        "model_path",
        "python_path",
        "output_path",
        "workflow_id",
    ),
)
def test_worker_descriptor_rejects_authority_and_path_choices(field: str) -> None:
    body = worker_invocation().model_dump(mode="json")
    body[field] = "untrusted"
    with pytest.raises(ValidationError):
        BenchmarkWorkerInvocation.model_validate(seal(body, "invocation_sha256"))
    assert not {
        "operator_audit_id",
        "graph_snapshot",
        "sources",
        "policy_revision_id",
        "policy_sha256",
    }.intersection(contracts.BenchmarkWorkerInvocation.model_fields)


@pytest.mark.parametrize(
    "field", ("input_set_sha256", "benchmark_revision_id", "view_recipe", "documents", "queries")
)
def test_staged_resolution_rejects_changed_exact_values(field: str) -> None:
    body = staged_inputs().model_dump(mode="json")
    if field == "input_set_sha256":
        body[field] = sha("f")
    elif field == "benchmark_revision_id":
        body[field] = "embeddingbenchmarkrev_" + "f" * 32
    elif field == "view_recipe":
        body[field]["recipe_sha256"] = sha("f")
    else:
        body[field] = list(reversed(body[field]))
    with pytest.raises(ValueError):
        value = BenchmarkStagedInputs.model_validate(body)
        validate_benchmark_staged_inputs(owner_request(), value)


@pytest.mark.parametrize(
    "field,value",
    (
        ("token_count", True),
        ("token_count", 10.0),
        ("token_count", "10"),
        ("token_count", 2049),
        ("text", ""),
        ("text", "  \n"),
        ("text", "bad\x00text"),
    ),
)
def test_staged_row_strict_bounds_and_empty_control_rejection(field: str, value: object) -> None:
    body = staged_inputs().documents[0].model_dump(mode="json")
    body[field] = value
    with pytest.raises(ValueError):
        BenchmarkTextRow.model_validate(body)


@pytest.mark.parametrize("index", (0, 1, 2))
def test_family_changes_relevant_payload_or_implementation_identity(index: int) -> None:
    body = benchmark_family().model_dump(mode="json")
    if index == 0:
        body["model"]["files"][0]["sha256"] = sha("f")
        body["model"] = seal(body["model"], "manifest_sha256")
    elif index == 1:
        body["implementations"][0]["sha256"] = sha("f")
    else:
        body["implementations"] = list(reversed(body["implementations"]))
    with pytest.raises(ValueError):
        BenchmarkModelFamily.model_validate(body)


def test_family_omits_runtime_device_and_unrelated_release_audit_not_numeric_rules() -> None:
    family = benchmark_family()
    model_body = family.model.model_dump(mode="json")
    model_body["model_revision_id"] = "embeddingmodelrev_" + "f" * 32
    model_body["runtime_versions"][0]["version"] = "999.0"
    model = LocalEmbeddingModelSpec.model_validate(seal(model_body, "manifest_sha256"))
    cuda_recipe = EmbeddingNumericalRecipe(cublas_workspace=":4096:8", batch_size=4, threads=4)
    assert (
        benchmark_model_family_sha256(model, family.implementations, cuda_recipe)
        == family.family_sha256
    )
    body = family.model_dump(mode="json") | {"git_commit": "f" * 40}
    with pytest.raises(ValidationError):
        BenchmarkModelFamily.model_validate(body)


@pytest.mark.parametrize("target", ("document", "query"))
def test_owner_request_does_not_accept_query_document_space_substitution(target: str) -> None:
    body = owner_request().model_dump(mode="json")
    other = "query" if target == "document" else "document"
    body["cuda"]["spaces"][target] = body["cuda"]["spaces"][other]
    with pytest.raises(ValueError):
        BenchmarkOwnerRequest.model_validate(seal(body, "request_sha256"))


@pytest.mark.parametrize("device", ("CPU", "CUDA"))
def test_exact_numeric_closure_not_minimum_four_and_claimed_fingerprint(
    device: BenchmarkDevice,
) -> None:
    body = owner_request().model_dump(mode="json")
    runtime = body[device.lower()]
    runtime["numerical_runtime"]["libraries"] = [
        pin for pin in runtime["numerical_runtime"]["libraries"] if pin["name"] != "numpy"
    ]
    runtime["numerical_runtime"] = seal(runtime["numerical_runtime"], "runtime_sha256")
    for purpose in ("document", "query"):
        space = runtime["spaces"][purpose]
        space["runtime"]["execution_runtime_sha256"] = runtime["numerical_runtime"][
            "runtime_sha256"
        ]
        runtime["spaces"][purpose] = seal(space, "space_sha256")
    with pytest.raises(ValueError):
        BenchmarkOwnerRequest.model_validate(seal(body, "request_sha256"))


@pytest.mark.parametrize(
    "mutation", ("ordinal", "runtime", "local_sha", "local_size", "owner_sha", "input_sha")
)
def test_worker_projection_fails_changed_exact_pointer_or_device(mutation: str) -> None:
    body = worker_invocation().model_dump(mode="json")
    if mutation == "ordinal":
        body["launch_ordinal"] = 2
    elif mutation == "runtime":
        body["runtime"] = owner_request().cuda.model_dump(mode="json")
    elif mutation == "local_sha":
        body["local_input"]["sha256"] = sha("f")
    elif mutation == "local_size":
        body["local_input"]["byte_count"] += 1
    elif mutation == "owner_sha":
        body["owner_request_sha256"] = sha("f")
    else:
        body["input_set_sha256"] = sha("f")
    with pytest.raises(ValueError):
        value = BenchmarkWorkerInvocation.model_validate(seal(body, "invocation_sha256"))
        validate_benchmark_invocation(owner_request(), value, staged_inputs())


@pytest.mark.parametrize("ordinal", range(1, 7))
def test_exact_cold_prepared_ready_program_and_matching_acks(ordinal: int) -> None:
    value = session(ordinal)
    assert len(value.checkpoints) == len(value.acks) == (21 if ordinal in (1, 2) else 1)
    for checkpoint, ack in zip(value.checkpoints, value.acks, strict=True):
        assert checkpoint.sequence == ack.sequence
        if checkpoint.phase == "QUERY_PREPARED":
            assert checkpoint.vector is None and checkpoint.encode_duration_ns is None
        elif checkpoint.phase == "QUERY_READY":
            assert checkpoint.vector is not None and checkpoint.vector.purpose == "QUERY"
            assert checkpoint.vector.row_count == 1
    validate_contract(EMBEDDING_DEVICE_BENCHMARK_SCHEMA, value.model_dump(mode="json"))


@pytest.mark.parametrize(
    "mutation",
    (
        "missing",
        "duplicate",
        "order",
        "wrong_ack_hash",
        "wrong_execution",
        "extra",
        "cold_only_extra",
    ),
)
def test_session_rejects_missing_replay_foreign_and_reordered_frames(mutation: str) -> None:
    body = session(3 if mutation == "cold_only_extra" else 1).model_dump(mode="json")
    if mutation == "missing":
        body["checkpoints"].pop()
    elif mutation == "duplicate":
        body["checkpoints"][2] = body["checkpoints"][1]
    elif mutation == "order":
        body["acks"][1], body["acks"][2] = body["acks"][2], body["acks"][1]
    elif mutation == "wrong_ack_hash":
        body["acks"][1]["checkpoint_sha256"] = sha("f")
    elif mutation == "wrong_execution":
        body["acks"][1]["execution_id"] = "f" * 32
    elif mutation == "extra":
        body["acks"].append(body["acks"][-1])
    else:
        body["checkpoints"].append(body["checkpoints"][0])
        body["acks"].append(body["acks"][0])
    with pytest.raises(ValueError):
        BenchmarkSession.model_validate(seal(body, "session_sha256"))


@pytest.mark.parametrize(
    "field,value",
    (
        ("sequence", 3),
        ("query_ordinal", 2),
        ("query_repetition", 2),
        ("vector", {}),
        ("encode_duration_ns", 1),
    ),
)
def test_prepared_checkpoint_cannot_echo_encoded_vector_or_other_phase(
    field: str, value: object
) -> None:
    body = session().checkpoints[1].model_dump(mode="json")
    body[field] = value
    with pytest.raises(ValueError):
        BenchmarkCheckpoint.model_validate(seal(body, "checkpoint_sha256"))


@pytest.mark.parametrize(
    "field,value",
    (
        ("sequence", True),
        ("sequence", 2.0),
        ("sequence", "2"),
        ("query_ordinal", 2),
        ("phase", "QUERY_READY"),
    ),
)
def test_ack_identity_and_integer_closure(field: str, value: object) -> None:
    body = session().acks[1].model_dump(mode="json")
    body[field] = value
    with pytest.raises(ValueError):
        BenchmarkAck.model_validate(body)


@pytest.mark.parametrize("device", ("CPU", "CUDA"))
def test_ns_conversion_conservative_and_authorization_part_of_query_total(
    device: BenchmarkDevice,
) -> None:
    value = timing_evidence(device)
    assert value.gate_timings.warm_batch_encode_us[0] == (1000 if device == "CPU" else 1001)
    body = value.model_dump(mode="json")
    body["gate_timings"]["warm_batch_encode_us"][0] += 1
    with pytest.raises(ValueError):
        BenchmarkTimingEvidence.model_validate(seal(body, "timing_sha256"))
    body = value.model_dump(mode="json")
    body["queries"][0]["end_to_end_ns"] = body["queries"][0]["encode_ns"]
    with pytest.raises(ValueError):
        BenchmarkTimingEvidence.model_validate(seal(body, "timing_sha256"))


@pytest.mark.parametrize(
    "mutation",
    ("query_count", "query_order", "warm_count", "warmup_count", "cold_only_warm", "cold_order"),
)
def test_timing_shapes_are_exact_not_missing_or_additional_samples(mutation: str) -> None:
    model: type[FrozenModel]
    if mutation == "cold_order":
        body = timing_evidence().model_dump(mode="json")
        body["cold"] = list(reversed(body["cold"]))
        model = BenchmarkTimingEvidence
    else:
        body = invocation_timings(3 if mutation == "cold_only_warm" else 1).model_dump(mode="json")
        model = BenchmarkInvocationTimings
        if mutation == "query_count":
            body["query_encode_ns"].pop()
        elif mutation == "query_order":
            body["query_encode_ns"] = list(reversed(body["query_encode_ns"]))
        elif mutation == "warm_count":
            body["warm_encode_ns"].pop()
        elif mutation == "warmup_count":
            body["warmup_count"] = 0
        else:
            body["warm_encode_ns"] = [1] * 5
    with pytest.raises(ValueError):
        model.model_validate(seal(body, "timing_sha256"))


def test_resource_failures_remain_integer_evidence_not_suppressed_by_policy() -> None:
    body = resources(2).model_dump(mode="json")
    body.update(
        peak_rss_bytes=7 * 1024**3,
        peak_reserved_gpu_bytes=9 * 1024**3,
        peak_whole_process_gpu_bytes=9 * 1024**3,
        peak_whole_device_gpu_bytes=9 * 1024**3,
        oom_count=1,
        other_consumer_overlap_count=1,
    )
    value = BenchmarkResourceEvidence.model_validate(seal(body, "resource_sha256"))
    assert value.peak_rss_bytes > benchmark_policy().rss_limit_bytes
    assert value.oom_count == 1 and value.other_consumer_overlap_count == 1


@pytest.mark.parametrize(
    "field",
    (
        "peak_allocated_gpu_bytes",
        "peak_reserved_gpu_bytes",
        "peak_whole_process_gpu_bytes",
        "peak_whole_device_gpu_bytes",
        "owner_observation_count",
    ),
)
def test_complete_cuda_cannot_report_allocated_only_or_missing_owner_observations(
    field: str,
) -> None:
    body = worker_result(2).model_dump(mode="json")
    body["resources"][field] = 0 if field == "owner_observation_count" else None
    body["resources"] = seal(body["resources"], "resource_sha256")
    with pytest.raises(ValueError):
        BenchmarkWorkerResult.model_validate(seal(body, "result_sha256"))


@pytest.mark.parametrize(
    "mutation",
    (
        "vector_count",
        "vectors_order",
        "query_purpose",
        "capacity_missing",
        "negative_missing",
        "foreign_timing",
    ),
)
def test_completed_worker_result_has_actual_prescribed_evidence(mutation: str) -> None:
    body = worker_result().model_dump(mode="json")
    if mutation == "vector_count":
        body["vectors"].pop()
    elif mutation == "vectors_order":
        body["vectors"] = list(reversed(body["vectors"]))
    elif mutation == "query_purpose":
        vector = next(v for v in body["vectors"] if v["key"]["phase"] == "QUERY")
        vector["purpose"] = "DOCUMENT"
        vector.update(seal(vector, "sample_sha256"))
    elif mutation == "capacity_missing":
        body["resources"]["capacity_samples"] = []
        body["resources"] = seal(body["resources"], "resource_sha256")
    elif mutation == "negative_missing":
        body["synthetic_rejections"].pop()
    else:
        body["timings"]["invocation_sha256"] = sha("f")
        body["timings"] = seal(body["timings"], "timing_sha256")
    with pytest.raises(ValueError):
        BenchmarkWorkerResult.model_validate(seal(body, "result_sha256"))


@pytest.mark.parametrize(
    "mutation",
    ("row_count", "byte_offset", "byte_count", "row_order", "binary_name", "float_offset"),
)
def test_binary_sample_shape_range_and_fixed_aliases(mutation: str) -> None:
    body = vector_samples()[0].model_dump(mode="json")
    if mutation == "row_count":
        body["row_count"] -= 1
    elif mutation == "byte_offset":
        body["byte_offset"] = 4096
    elif mutation == "byte_count":
        body["byte_count"] -= 4
    elif mutation == "row_order":
        body["ordered_rows"][1] = body["ordered_rows"][0]
    elif mutation == "binary_name":
        body["binary"]["member_name"] = "../../escaped.f32"
    else:
        body["byte_offset"] = 0.0
    with pytest.raises(ValueError):
        BenchmarkVectorSample.model_validate(
            body if mutation == "float_offset" else seal(body, "sample_sha256")
        )


@pytest.mark.parametrize("mutation", ("mask", "ids_length", "token_types", "boolean_id", "pad_id"))
def test_token_witness_ids_masks_types_and_padding_readback(mutation: str) -> None:
    body = cold_token_witness().samples[0].batches[2].model_dump(mode="json")
    row = body["rows"][0]
    if mutation == "mask":
        row["attention_mask"][0] = 0
    elif mutation == "ids_length":
        row["input_ids"].pop()
    elif mutation == "token_types":
        row["token_type_ids"] = [0]
    elif mutation == "boolean_id":
        row["input_ids"][0] = True
    else:
        shorter = next(
            r
            for batch in cold_token_witness().samples[0].batches
            for r in batch.rows
            if r.token_count < len(r.input_ids)
        )
        row = shorter.model_dump(mode="json")
        row["input_ids"][-1] = 999
        body["rows"] = [
            row,
            cold_token_witness().samples[0].batches[2].rows[-1].model_dump(mode="json"),
        ]
    with pytest.raises(ValueError):
        BenchmarkTokenBatch.model_validate(seal(body, "batch_sha256"))


@pytest.mark.parametrize(
    "mutation",
    (
        "ordered_cases",
        "duplicate_text",
        "capacity_tokens",
        "overflow_count",
        "empty_text",
        "fixture_hash",
    ),
)
def test_public_synthetic_and_capacity_inputs_are_exact_pinned_values(mutation: str) -> None:
    body = staged_inputs().model_dump(mode="json")
    if mutation == "ordered_cases":
        body["synthetic_cases"] = list(reversed(body["synthetic_cases"]))
    elif mutation == "duplicate_text":
        body["synthetic_cases"][5]["text"] = "not duplicate"
        body["synthetic_cases"][5]["input_text_sha256"] = content_sha256("not duplicate")
    elif mutation == "capacity_tokens":
        body["capacity"]["token_count"] = 2047
    elif mutation == "overflow_count":
        body["synthetic_cases"][7]["token_count"] = 2048
    elif mutation == "empty_text":
        body["synthetic_cases"][6]["text"] = "not empty"
        body["synthetic_cases"][6]["input_text_sha256"] = content_sha256("not empty")
    else:
        body["public_fixture_sha256"] = sha("f")
    with pytest.raises(ValueError):
        BenchmarkStagedInputs.model_validate(body)


@pytest.mark.parametrize("field", ("cpu", "cuda", "numerical_evidence", "near_tie_reference"))
def test_measured_does_not_allow_missing_complete_device_or_evidence(field: str) -> None:
    body = measured_result().model_dump(mode="json")
    body[field] = None
    with pytest.raises(ValueError):
        BenchmarkOwnerResult.model_validate(seal(body, "result_sha256"))


@pytest.mark.parametrize(
    "raw", (b"[]", b'{"x":1,"x":2}', b'{"x":1.0}', b'{"x":NaN}', b'{"x":123456789012345678901}')
)
def test_bounded_json_parser_rejects_wrong_shape_duplicates_floats_nonfinite_and_huge_integer(
    raw: bytes,
) -> None:
    with pytest.raises(ValueError):
        parse_embedding_device_benchmark_bytes(raw)


def test_raw_bound_is_checked_before_json_allocation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(contracts, "MAX_BENCHMARK_ENVELOPE_BYTES", 8)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("unbounded parse attempted")

    monkeypatch.setattr(json, "loads", forbidden)
    with pytest.raises(ValueError, match="byte bound"):
        parse_embedding_device_benchmark_bytes(b"123456789", maximum_bytes=8)


def test_json_nesting_bound_before_allocation(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("unbounded nested parse")

    monkeypatch.setattr(json, "loads", forbidden)
    with pytest.raises(ValueError, match="pre-allocation"):
        parse_embedding_device_benchmark_bytes(b"[" * 33 + b"0" + b"]" * 33)


@pytest.mark.parametrize("style", ("copied", "constructed"))
def test_literal_integer_bool_is_checked_before_model_dump(
    style: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = (
        benchmark_policy().model_copy(update={"timeout_seconds": True})
        if style == "copied"
        else type(benchmark_policy()).model_construct(
            **(benchmark_policy().model_dump(mode="python") | {"timeout_seconds": True})
        )
    )

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("raw Literal bool was serialized")

    monkeypatch.setattr(FrozenModel, "model_dump", forbidden)
    with pytest.raises(ValueError, match="exact integers"):
        type(value).model_validate(value)
    with pytest.raises(ValueError, match="exact integers"):
        embedding_device_benchmark_bytes(value)


def test_nested_copied_tf32_zero_cannot_serialize_as_false(monkeypatch: pytest.MonkeyPatch) -> None:
    request = owner_request()
    space = request.cpu.spaces.document.model_copy(
        update={
            "runtime": request.cpu.spaces.document.runtime.model_copy(update={"tf32_enabled": 0})
        }
    )
    value = request.model_copy(
        update={
            "cpu": request.cpu.model_copy(
                update={"spaces": request.cpu.spaces.model_copy(update={"document": space})}
            )
        }
    )

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("copied numeric bool was serialized")

    monkeypatch.setattr(FrozenModel, "model_dump", forbidden)
    with pytest.raises(ValueError, match="declared boolean"):
        BenchmarkOwnerRequest.model_validate(value)


def test_copied_hidden_extra_is_rejected_before_serialization() -> None:
    value = benchmark_policy().model_copy(update={"authority": "ADMIN"})
    with pytest.raises(ValueError, match="undeclared"):
        type(value).model_validate(value)
    with pytest.raises(ValueError, match="undeclared"):
        embedding_device_benchmark_bytes(value)


@pytest.mark.parametrize(
    "helper", ("family", "staged", "invocation", "input_hash", "fixture_hash", "serializer")
)
def test_exported_helpers_check_copied_bool_before_any_dump(
    helper: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    family, request, inputs, invocation = (
        benchmark_family(),
        owner_request(),
        staged_inputs(),
        worker_invocation(),
    )
    bad_model = family.model.model_copy(update={"maximum_tokens": True})
    bad_policy = request.execution_policy.model_copy(update={"timeout_seconds": True})
    bad_request = request.model_copy(update={"execution_policy": bad_policy})
    bad_invocation = invocation.model_copy(update={"execution_policy": bad_policy})
    bad_row = inputs.documents[0].model_copy(update={"token_count": True})
    bad_case = inputs.synthetic_cases[0].model_copy(update={"token_count": True})
    calls: dict[str, Callable[[], object]] = {
        "family": lambda: benchmark_model_family_sha256(
            bad_model, family.implementations, family.recipe
        ),
        "staged": lambda: validate_benchmark_staged_inputs(bad_request, inputs),
        "invocation": lambda: validate_benchmark_invocation(request, bad_invocation, inputs),
        "input_hash": lambda: contracts.benchmark_input_set_sha256(
            (bad_row, *inputs.documents[1:]), inputs.queries, inputs.view_recipe
        ),
        "fixture_hash": lambda: contracts.benchmark_public_fixture_sha256(
            (bad_case, *inputs.synthetic_cases[1:]), inputs.capacity
        ),
        "serializer": lambda: embedding_device_benchmark_bytes(bad_request),
    }

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("helper serialized raw copied bool")

    monkeypatch.setattr(FrozenModel, "model_dump", forbidden)
    with pytest.raises(ValueError, match="exact integers"):
        calls[helper]()


@pytest.mark.parametrize("case", ("cycle", "deep", "mapping", "sequence", "string"))
def test_python_documents_and_constructed_models_have_pre_dump_bounds(
    case: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    extra: object
    if case == "cycle":
        cyclic: dict[str, object] = {}
        cyclic["self"] = cyclic
        extra = cyclic
    elif case == "deep":
        extra = 0
        for _ in range(33):
            extra = {"next": extra}
    elif case == "mapping":
        extra = {str(index): 0 for index in range(65)}
    elif case == "sequence":
        extra = [0] * 4097
    else:
        extra = "a" * 262145
    document = benchmark_policy().model_dump(mode="json") | {"unexpected": extra}
    value = benchmark_policy().model_copy(update={"unexpected": extra})

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("unbounded dump attempted")

    monkeypatch.setattr(FrozenModel, "model_dump", forbidden)
    with pytest.raises(ValueError):
        parse_embedding_device_benchmark(document)
    with pytest.raises(ValueError):
        type(value).model_validate(value)


def test_raw_node_budget_and_shared_noncyclic_values(monkeypatch: pytest.MonkeyPatch) -> None:
    leaf = [0] * 64
    large: object = leaf
    for _ in range(3):
        large = [large] * 64

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("oversized canonicalization attempted")

    monkeypatch.setattr(contracts, "canonical_json_bytes", forbidden)
    with pytest.raises(ValueError, match="node/depth"):
        parse_embedding_device_benchmark({"unexpected": large})


@pytest.mark.parametrize(
    "mutation",
    ("float_score", "unaligned_offset", "outside_offset", "boolean_counter", "duplicate_pair"),
)
def test_numerical_evidence_is_bounded_binary_and_integer_trace_only(mutation: str) -> None:
    body = numerical_evidence().model_dump(mode="json")
    if mutation == "float_score":
        body["cpu_score"] = 0.99999
    elif mutation == "unaligned_offset":
        body["decisions"][0]["cpu_left_offset"] = 1
    elif mutation == "outside_offset":
        body["decisions"][0]["cuda_right_offset"] = 1280
    elif mutation == "boolean_counter":
        body["norm_failures"] = False
    else:
        body["decisions"].append(body["decisions"][0])
    with pytest.raises(ValueError):
        BenchmarkNumericalEvidence.model_validate(
            body if mutation == "float_score" else seal(body, "numerical_sha256")
        )


@pytest.mark.parametrize(
    "mutation",
    ("missing_query", "same_purpose_space", "self_inclusion", "cluster_rows", "unaligned_scores"),
)
def test_near_tie_reference_real_rows_and_self_exclusion_not_fake_profile_ids(
    mutation: str,
) -> None:
    body = near_tie_reference().model_dump(mode="json")
    if mutation == "missing_query":
        body["queries"].pop()
    elif mutation == "same_purpose_space":
        body["cpu_query_space_sha256"] = body["cpu_document_space_sha256"]
    elif mutation == "self_inclusion":
        body["queries"][0]["ordered_candidates"][0] = (
            owner_request().document_rows[0].model_dump(mode="json")
        )
    elif mutation == "cluster_rows":
        body["queries"][0]["clusters"][0]["row_sha256"].pop()
    else:
        body["queries"][0]["clusters"][0]["cpu_score_offsets"][0] = 1
    with pytest.raises(ValueError):
        BenchmarkNearTieReference.model_validate(seal(body, "reference_sha256"))


def test_contract_has_no_runtime_workflow_io_ml_or_source_authority_dependency() -> None:
    tree = ast.parse(
        (
            ROOT / "packages/catalog_contracts/eom_catalog_contracts/embedding_device_benchmark.py"
        ).read_text()
    )
    imported = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    }
    imported.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    forbidden = {
        "eom_workflow",
        "eom_catalog_service",
        "eom_orchestrator_service",
        "torch",
        "transformers",
        "tokenizers",
        "numpy",
        "subprocess",
        "pathlib",
        "os",
        "sqlalchemy",
    }
    assert not any(name.split(".")[0] in forbidden for name in imported)
    assert all(
        not isinstance(node, ast.Call)
        or not isinstance(node.func, ast.Name)
        or node.func.id not in {"open", "exec", "eval"}
        for node in ast.walk(tree)
    )
