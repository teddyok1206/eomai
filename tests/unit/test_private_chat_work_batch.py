"""Private numerical envelope3 over the unchanged QUERY2 encoder; synthetic model only."""

from contextlib import contextmanager
from pathlib import Path

import pytest
from eom_catalog_contracts.embedding_work_batch import (
    PrivateChatWorkBatchInput,
    PublicSolutionWorkBatchInput,
    parse_embedding_work_batch_input,
    parse_supported_embedding_work_batch_input,
)
from eom_catalog_contracts.embedding_work_batch_binary import validate_embedding_work_batch_binary
from eom_catalog_contracts.embedding_work_batch_result import (
    PrivateChatWorkBatchResult,
    PublicSolutionWorkBatchResult,
    build_embedding_work_batch_result,
    parse_embedding_work_batch_result,
    parse_supported_embedding_work_batch_result,
    validate_embedding_work_batch_result,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_catalog_service.embedding_encoder_adapter import encode_public_solution_query
from eom_catalog_service.embedding_work_batch_execution import (
    EmbeddingWorkBatchExecutionResources,
    execute_embedding_work_batch,
)
from eom_identifiers import sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_incremental_encoding import SyntheticNativeBackend
from tests.unit.test_embedding_work_batch import Fence, batch_body
from tests.unit.test_private_chat_public_query_execution import execution_case, native
from tests.unit.test_private_chat_query_basis import TEXT

ERRORS = (ValueError, SchemaError)


def private_case(device="CPU"):
    request, policy, bundle = execution_case(device)
    query = native(request, policy, bundle).native
    body = batch_body(count=1, device=device)
    body["schema_version"] = "embedding-work-batch-input/3.0"
    body["purpose"] = "PRIVATE_CHAT_QUERY"
    body["resource_profile_sha256"] = policy.resource_profile.resource_profile_sha256
    body["timeout_seconds"] = min(policy.resource_profile.timeout_seconds, 180)
    body["scope"] = seal(
        body["scope"]
        | {
            "actor_id": request.operator_audit.operator_id,
            "storage_partition": query.rows[0].encoding.storage_partition,
            "access_policy_sha256": request.context_request.policy_sha256,
        },
        "scope_sha256",
    )
    body["children"] = [
        {"scope_sha256": body["scope"]["scope_sha256"], "request": query.model_dump(mode="json")}
    ]
    batch = PrivateChatWorkBatchInput.model_validate(seal(body, "request_sha256"))
    backend = SyntheticNativeBackend(query.spaces.query)
    backend.batch_size, backend.threads = query.batch_size, query.threads
    lifetime = []

    @contextmanager
    def scope():
        lifetime.append("load")
        try:
            yield backend
        finally:
            lifetime.append("close")

    resources = EmbeddingWorkBatchExecutionResources(
        batch.resource_profile_sha256, batch.timeout_seconds, batch.vector_max_bytes
    )
    return batch, backend, scope, resources, lifetime


@pytest.mark.parametrize("name", ("input", "result"))
def test_private_batch3_schema_is_pinned_mirrored_and_valid_without_activating_a_worker(name):
    resource = CATALOG_SCHEMA_RESOURCES[f"private-chat-work-batch-{name}-v3"]
    root = Path(__file__).resolve().parents[2]
    raw = (root / resource.canonical_path).read_bytes()
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
    )
    assert sha256_bytes(raw) == resource.sha256
    Draft202012Validator.check_schema(load_schema(f"private-chat-work-batch-{name}-v3"))


@pytest.mark.parametrize("device", ("CPU", "CUDA"))
def test_owned_private_query_uses_identical_query2_text_encoder_and_vector_bytes(device):
    batch, backend, scope, resources, lifetime = private_case(device)
    encoded = execute_embedding_work_batch(
        batch, resources=resources, backend_scope=scope, fence=Fence()
    )
    assert lifetime == ["load", "close"] and backend.calls == [((TEXT,), "QUERY")]
    query = batch.children[0].request
    independent = SyntheticNativeBackend(query.spaces.query)
    independent.batch_size, independent.threads = query.batch_size, query.threads
    single = encode_public_solution_query(query, independent)
    assert encoded.children == (single,)
    result = build_embedding_work_batch_result(
        batch, (single.result,), sha256_bytes(single.vectors)
    )
    assert isinstance(result, PrivateChatWorkBatchResult)
    assert result.children[0].result == single.result
    ranges = validate_embedding_work_batch_binary(batch, result, single.vectors)
    assert len(ranges) == 1 and ranges[0].readonly and ranges[0].obj is single.vectors
    assert parse_supported_embedding_work_batch_input(batch) == batch
    assert parse_supported_embedding_work_batch_result(result) == result
    for parser, value in (
        (parse_embedding_work_batch_input, batch),
        (PublicSolutionWorkBatchInput.model_validate, batch),
        (parse_embedding_work_batch_result, result),
        (PublicSolutionWorkBatchResult.model_validate, result),
    ):
        with pytest.raises(ERRORS):
            parser(value)


@pytest.mark.parametrize(
    "fault",
    (
        "actor",
        "scope",
        "partition",
        "second_child",
        "purpose",
        "timeout",
        "budget",
        "hash",
        "authority",
    ),
)
def test_private_input_cannot_change_scope_bounds_purpose_or_add_another_question(fault):
    batch, *_ = private_case()
    body = batch.model_dump(mode="json")
    if fault == "actor":
        body["scope"] = seal(
            body["scope"] | {"actor_kind": "LOCAL_INDEXING_SERVICE"}, "scope_sha256"
        )
        body["children"][0]["scope_sha256"] = body["scope"]["scope_sha256"]
    elif fault == "scope":
        body["children"][0]["scope_sha256"] = "sha256:" + "f" * 64
    elif fault == "partition":
        body["scope"] = seal(
            body["scope"] | {"storage_partition": "another-partition"}, "scope_sha256"
        )
        body["children"][0]["scope_sha256"] = body["scope"]["scope_sha256"]
    elif fault == "second_child":
        body["children"] *= 2
    elif fault == "purpose":
        body["purpose"] = "REFERENCE_QUERY"
    elif fault == "timeout":
        body["timeout_seconds"] = 181
    elif fault == "budget":
        body["vector_max_bytes"] = 4
    elif fault == "authority":
        body["compute_granted"] = True
    body = seal(body, "request_sha256")
    if fault == "hash":
        body["request_sha256"] = "sha256:" + "f" * 64
    with pytest.raises(ERRORS):
        parse_supported_embedding_work_batch_input(body)


@pytest.mark.parametrize(
    "fault", ("request", "route", "offset", "context", "vector", "result_hash", "family")
)
def test_private_output_cannot_reuse_another_request_route_family_or_binary(fault):
    batch, _, scope, resources, _ = private_case()
    output = execute_embedding_work_batch(
        batch, resources=resources, backend_scope=scope, fence=Fence()
    ).children[0]
    result = build_embedding_work_batch_result(
        batch, (output.result,), sha256_bytes(output.vectors)
    )
    body = result.model_dump(mode="json")
    binary = output.vectors
    if fault == "request":
        body["request_sha256"] = "sha256:" + "f" * 64
    elif fault == "route":
        body["routing_decision_sha256"] = "sha256:" + "f" * 64
    elif fault == "offset":
        body["children"][0]["vector_offset"] = 4
    elif fault == "context":
        child = body["children"][0]
        child["result"] = seal(
            child["result"] | {"context_request_sha256": "sha256:" + "f" * 64}, "result_sha256"
        )
    elif fault == "vector":
        binary = bytes(len(binary))
    elif fault == "family":
        body["schema_version"] = "embedding-work-batch-result/2.0"
        body["purpose"] = "REFERENCE_QUERY"
    body = seal(body, "result_sha256")
    if fault == "result_hash":
        body["result_sha256"] = "sha256:" + "f" * 64
    with pytest.raises(ERRORS):
        altered = parse_supported_embedding_work_batch_result(body)
        validate_embedding_work_batch_result(batch, altered)
        validate_embedding_work_batch_binary(batch, altered, binary)


def test_private_source_withdrawal_closes_model_without_returning_aggregate_success():
    batch, backend, scope, resources, lifetime = private_case()
    fence = Fence()
    fence.reject_at = 3
    with pytest.raises(ValueError, match="SOURCE_REVOKED"):
        execute_embedding_work_batch(batch, resources=resources, backend_scope=scope, fence=fence)
    assert lifetime == ["load", "close"] and backend.calls == [((TEXT,), "QUERY")]


@pytest.mark.parametrize("purpose", ("INDEX", "REFERENCE_QUERY", "PRIVATE_CHAT_QUERY"))
def test_private_grant_metadata_requires_the_exact_private_purpose_not_a_public_grant(purpose):
    from eom_catalog_contracts.embedding_gpu_control import (
        EmbeddingGpuAllocationRequest,
        EmbeddingGpuComputeGrant,
        EmbeddingGpuControlError,
        validate_embedding_gpu_batch_grant,
    )

    from tests.unit.test_embedding_gpu_control import control_case

    batch, *_ = private_case("CUDA")
    original, _, _, grant, _, _, _, raw = control_case(batch=batch)
    request = EmbeddingGpuAllocationRequest.model_validate(
        seal(original.model_dump(mode="json") | {"purpose": purpose}, "message_sha256")
    )
    grant = EmbeddingGpuComputeGrant.model_validate(
        seal(
            grant.model_dump(mode="json") | {"allocation_request_sha256": request.message_sha256},
            "message_sha256",
        )
    )
    if purpose == "PRIVATE_CHAT_QUERY":
        validate_embedding_gpu_batch_grant(
            request, grant, batch, input_raw_sha256=sha256_bytes(raw), input_byte_count=len(raw)
        )
    else:
        with pytest.raises(EmbeddingGpuControlError):
            validate_embedding_gpu_batch_grant(
                request, grant, batch, input_raw_sha256=sha256_bytes(raw), input_byte_count=len(raw)
            )
