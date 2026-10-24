"""Synthetic finite-batch contracts and lifetime checks; no model or runtime activation."""

from __future__ import annotations

from contextlib import contextmanager, suppress
from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, Literal

import pytest
from eom_catalog_contracts.embedding_reference_query_v11 import (
    EmbeddingReferenceQueryInputV11,
    validate_reference_query_result_v11,
)
from eom_catalog_contracts.embedding_work_batch import (
    EMBEDDING_WORK_BATCH_SCHEMA,
    EmbeddingWorkBatchChild,
    EmbeddingWorkBatchInput,
    parse_embedding_work_batch_input,
)
from eom_catalog_contracts.inference_transfer_embedding import (
    validate_incremental_embedding_result,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_catalog_service.embedding_encoder_adapter import ReferenceQueryEmbeddingEncodeError
from eom_catalog_service.embedding_work_batch_execution import (
    EmbeddingWorkBatchExecutionError,
    EmbeddingWorkBatchExecutionResources,
    execute_embedding_work_batch,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import (
    PARTITION,
    embedding_input,
    embedding_space,
    encoding_identity,
    seal,
)
from tests.unit.inference_transfer_fixtures import sha
from tests.unit.test_embedding_incremental_encoding import SyntheticNativeBackend
from tests.unit.test_embedding_reference_query_v11_contracts import input_body

ROOT = Path(__file__).resolve().parents[2]
ERRORS = (ValueError, SchemaError)


def batch_body(
    purpose: str = "REFERENCE_QUERY", count: int = 2, *, device: Literal["CPU", "CUDA"] = "CPU"
) -> dict[str, Any]:
    scope = seal(
        {
            "actor_kind": "OPERATOR",
            "actor_id": "operator_synthetic",
            "storage_partition": PARTITION,
            "access_policy_sha256": sha("c"),
        },
        "scope_sha256",
    )
    children: list[dict[str, Any]] = []
    for index in range(count):
        identity = f"{index + 1:032x}"
        if purpose == "REFERENCE_QUERY":
            request = input_body()
            query_space = embedding_space(device=device, purpose="QUERY")
            request["spaces"] = {
                "query": query_space.model_dump(mode="json"),
                "document": embedding_space(device=device).model_dump(mode="json"),
            }
            for row in request["rows"]:
                row["encoding"] = encoding_identity(row["text"], query_space).model_dump(
                    mode="json"
                )
            request["input_set_sha256"] = content_sha256(
                [row["encoding"] for row in request["rows"]]
            )
            request["job_id"] = "job_" + identity
            request["query_request_id"] = "embeddingquery_" + identity
            request["context_request_sha256"] = content_sha256({"context": index})
            request = seal(request, "request_sha256")
        else:
            request = embedding_input(
                f"합성 문항 {index}의 보존 관계를 분석한다.",
                job_id="job_" + identity,
                space=embedding_space(device=device),
            ).model_dump(mode="json")
        children.append({"scope_sha256": scope["scope_sha256"], "request": request})
    return seal(
        {
            "schema_version": "embedding-work-batch-input/1.0",
            "purpose": purpose,
            "scope": scope,
            "routing_decision_sha256": sha("d"),
            "resource_profile_sha256": sha("e"),
            "timeout_seconds": 180,
            "vector_max_bytes": 16 * 1024**2,
            "children": children,
        },
        "request_sha256",
    )


class Fence:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []
        self.reject: str | None = None
        self.reject_at: int | None = None
        self.child_checks = 0

    def assert_batch_current(self, batch: EmbeddingWorkBatchInput) -> None:
        self.events.append(("batch", batch.request_sha256))

    def assert_child_current(
        self, batch: EmbeddingWorkBatchInput, child: EmbeddingWorkBatchChild
    ) -> None:
        assert child in batch.children
        self.events.append(("child", child.request.job_id))
        self.child_checks += 1
        if child.request.job_id == self.reject or self.child_checks == self.reject_at:
            raise ValueError("SYNTHETIC_SOURCE_REVOKED")


def resources(batch: EmbeddingWorkBatchInput) -> EmbeddingWorkBatchExecutionResources:
    return EmbeddingWorkBatchExecutionResources(
        batch.resource_profile_sha256, batch.timeout_seconds, batch.vector_max_bytes
    )


def test_schema_is_packaged_mirrored_pinned_and_has_no_runtime_authority() -> None:
    resource = CATALOG_SCHEMA_RESOURCES[EMBEDDING_WORK_BATCH_SCHEMA]
    raw = (ROOT / resource.canonical_path).read_bytes()
    installed = ROOT / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
    assert installed.read_bytes() == raw
    assert sha256_bytes(raw) == resource.sha256
    schema = load_schema(EMBEDDING_WORK_BATCH_SCHEMA)
    Draft202012Validator.check_schema(schema)
    assert schema["$id"] == "eom://schemas/knowledge/embedding-work-batch-input/1.0"
    assert set(schema["required"]) == set(schema["properties"])
    assert "launch" not in schema["properties"]


@pytest.mark.parametrize("purpose", ["REFERENCE_QUERY", "DOCUMENT"])
def test_existing_children_keep_exact_identity_order_and_canonical_hash(purpose: str) -> None:
    body = batch_body(purpose)
    batch = parse_embedding_work_batch_input(body)
    assert canonical_json_bytes(batch.model_dump(mode="json")) == canonical_json_bytes(body)
    assert batch.expected_vector_bytes == sum(
        len(child.request.rows) * child.space.model_spec.dimension * 4 for child in batch.children
    )
    assert [child.request.job_id for child in batch.children] == [
        row["request"]["job_id"] for row in body["children"]
    ]
    with pytest.raises(ValueError):
        batch.timeout_seconds = 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("purpose", "QUERY"),
        ("purpose", "PRIVATE_CHAT_QUERY"),
        ("purpose", "UNKNOWN"),
        ("timeout_seconds", 0),
        ("timeout_seconds", 181),
        ("timeout_seconds", True),
        ("timeout_seconds", 30.0),
        ("vector_max_bytes", 0),
        ("vector_max_bytes", 16 * 1024**2 + 1),
        ("vector_max_bytes", True),
        ("resource_profile_sha256", "unprotected"),
        ("routing_decision_sha256", "unbound"),
        ("request_sha256", sha("0")),
        ("children", []),
    ],
)
def test_invalid_outer_values_are_rejected(field: str, value: Any) -> None:
    body = batch_body()
    body[field] = value
    if field != "request_sha256" and not isinstance(value, float):
        body = seal(body, "request_sha256")
    with pytest.raises(ERRORS):
        parse_embedding_work_batch_input(body)


@pytest.mark.parametrize("field", ["actor_kind", "actor_id", "access_policy_sha256"])
def test_changed_scope_claim_does_not_keep_previous_scope_hash(field: str) -> None:
    body = batch_body()
    body["scope"][field] = {
        "actor_kind": "LOCAL_INDEXING_SERVICE",
        "actor_id": "another_operator",
        "access_policy_sha256": sha("9"),
    }[field]
    with pytest.raises(ERRORS):
        parse_embedding_work_batch_input(seal(body, "request_sha256"))


@pytest.mark.parametrize("fault", ["scope", "job", "query", "request", "recipe", "partition"])
def test_foreign_duplicate_or_mixed_child_is_rejected(fault: str) -> None:
    body = batch_body()
    first, second = body["children"]
    request = second["request"]
    if fault == "scope":
        second["scope_sha256"] = sha("9")
    elif fault == "job":
        request["job_id"] = first["request"]["job_id"]
    elif fault == "query":
        request["query_request_id"] = first["request"]["query_request_id"]
    elif fault == "request":
        second["request"] = deepcopy(first["request"])
    elif fault == "recipe":
        request["batch_size"] = 3
    else:
        query_space = embedding_space(purpose="QUERY")
        for row in request["rows"]:
            row["encoding"] = encoding_identity(
                row["text"], query_space, storage_partition="another-owner"
            ).model_dump(mode="json")
        request["input_set_sha256"] = content_sha256([row["encoding"] for row in request["rows"]])
    second["request"] = seal(second["request"], "request_sha256")
    with pytest.raises(ERRORS):
        parse_embedding_work_batch_input(seal(body, "request_sha256"))


@pytest.mark.parametrize("purpose", ["REFERENCE_QUERY", "DOCUMENT"])
def test_child_limit_output_preflight_and_foreign_extra_are_rejected(purpose: str) -> None:
    body = batch_body(purpose, count=33)
    with pytest.raises(ERRORS):
        parse_embedding_work_batch_input(body)
    body = batch_body(purpose)
    body["vector_max_bytes"] = 4
    with pytest.raises(ERRORS):
        parse_embedding_work_batch_input(seal(body, "request_sha256"))
    body = batch_body(purpose)
    body["children"][0]["request"]["paths"] = ["/not/a/grant"]
    with pytest.raises(ERRORS):
        parse_embedding_work_batch_input(seal(body, "request_sha256"))


def test_mixed_purpose_and_cpu_cuda_spaces_are_not_implicitly_combined() -> None:
    body = batch_body()
    body["children"][1] = batch_body("DOCUMENT")["children"][1]
    with pytest.raises(ERRORS):
        parse_embedding_work_batch_input(seal(body, "request_sha256"))
    body = batch_body("DOCUMENT")
    body["children"][1]["request"] = embedding_input(
        "장치가 다른 합성 자료.", space=embedding_space(device="CUDA"), job_id="job_" + "2" * 32
    ).model_dump(mode="json")
    with pytest.raises(ERRORS):
        parse_embedding_work_batch_input(seal(body, "request_sha256"))


@pytest.mark.parametrize("purpose", ["REFERENCE_QUERY", "DOCUMENT"])
@pytest.mark.parametrize("device", ["CPU", "CUDA"])
def test_one_model_scope_preserves_existing_per_child_encode_and_results(
    purpose: str, device: Literal["CPU", "CUDA"]
) -> None:
    batch = parse_embedding_work_batch_input(batch_body(purpose, device=device))
    backend = SyntheticNativeBackend(batch.children[0].space)
    backend.batch_size = batch.children[0].request.batch_size
    events: list[str] = []
    fence = Fence()

    @contextmanager
    def scope():
        events.append("open")
        assert fence.child_checks == len(batch.children)
        try:
            yield backend
        finally:
            events.append("close")

    result = execute_embedding_work_batch(
        batch, resources=resources(batch), backend_scope=scope, fence=fence
    )
    assert events == ["open", "close"]
    assert backend.execution_runtime.device == device
    assert result.request_sha256 == batch.request_sha256
    assert len(backend.calls) == len(batch.children) == len(result.children)
    assert [call[1] for call in backend.calls] == [
        "QUERY" if purpose == "REFERENCE_QUERY" else "DOCUMENT"
    ] * len(batch.children)
    for child, output in zip(batch.children, result.children, strict=True):
        assert output.result.request_sha256 == child.request.request_sha256
        assert output.result.job_id == child.request.job_id
        if isinstance(child.request, EmbeddingReferenceQueryInputV11):
            validate_reference_query_result_v11(child.request, output.result)
        else:
            validate_incremental_embedding_result(child.request, output.result)
    assert sum(len(output.vectors) for output in result.children) == batch.expected_vector_bytes
    assert fence.child_checks == len(batch.children) * 4
    with pytest.raises(FrozenInstanceError):
        result.request_sha256 = sha("9")


def test_all_children_authorized_before_model_construction() -> None:
    batch = parse_embedding_work_batch_input(batch_body())
    fence = Fence()
    fence.reject = batch.children[-1].request.job_id
    opened: list[bool] = []

    @contextmanager
    def scope():
        opened.append(True)
        yield SyntheticNativeBackend(batch.children[0].space)

    with pytest.raises(ValueError, match="SYNTHETIC_SOURCE_REVOKED"):
        execute_embedding_work_batch(
            batch, resources=resources(batch), backend_scope=scope, fence=fence
        )
    assert opened == []


def test_early_child_revoked_during_later_encode_rejects_after_scope_cleanup() -> None:
    batch = parse_embedding_work_batch_input(batch_body())
    backend = SyntheticNativeBackend(batch.children[0].space)
    backend.batch_size = batch.children[0].request.batch_size
    fence = Fence()
    events: list[str] = []
    original_encode = backend.encode

    def encode(texts, *, purpose):
        result = original_encode(texts, purpose=purpose)
        if len(backend.calls) == 2:
            fence.reject = batch.children[0].request.job_id
        return result

    backend.encode = encode

    @contextmanager
    def scope():
        try:
            yield backend
        finally:
            events.append("closed")

    with pytest.raises(ValueError, match="SYNTHETIC_SOURCE_REVOKED"):
        execute_embedding_work_batch(
            batch, resources=resources(batch), backend_scope=scope, fence=fence
        )
    assert len(backend.calls) == 2
    assert events == ["closed"]


def test_scope_cannot_suppress_child_error_and_return_partial_success() -> None:
    batch = parse_embedding_work_batch_input(batch_body())
    backend = SyntheticNativeBackend(batch.children[0].space)
    backend.batch_size = batch.children[0].request.batch_size
    fence = Fence()
    fence.reject_at = len(batch.children) + 2

    @contextmanager
    def scope():
        with suppress(ValueError):
            yield backend

    with pytest.raises(EmbeddingWorkBatchExecutionError, match="INCOMPLETE"):
        execute_embedding_work_batch(
            batch, resources=resources(batch), backend_scope=scope, fence=fence
        )


@pytest.mark.parametrize("fault", ["backend", "revoked", "timeout", "load_timeout"])
def test_failures_close_single_scope_without_fallback_or_aggregate_success(fault: str) -> None:
    batch = parse_embedding_work_batch_input(batch_body())
    backend = SyntheticNativeBackend(batch.children[0].space)
    backend.batch_size = batch.children[0].request.batch_size
    fence = Fence()
    closed: list[bool] = []
    now = [0]
    original_encode = backend.encode

    def encode(texts, *, purpose):
        result = original_encode(texts, purpose=purpose)
        if fault == "backend":
            backend.batch_size += 1
        if fault == "timeout":
            now[0] = batch.timeout_seconds * 10**9
        return result

    backend.encode = encode
    if fault == "revoked":
        fence.reject_at = len(batch.children) + 2

    @contextmanager
    def scope():
        try:
            if fault == "load_timeout":
                now[0] = batch.timeout_seconds * 10**9
            yield backend
        finally:
            closed.append(True)

    with pytest.raises((ReferenceQueryEmbeddingEncodeError, ValueError)):
        execute_embedding_work_batch(
            batch,
            resources=resources(batch),
            backend_scope=scope,
            fence=fence,
            clock_ns=lambda: now[0],
        )
    assert closed == [True]
    assert len(backend.calls) <= 1


@pytest.mark.parametrize("fault", ["hash", "time", "output"])
def test_actual_resource_mismatch_is_rejected_before_model_or_authorization(fault: str) -> None:
    batch = parse_embedding_work_batch_input(batch_body())
    actual = EmbeddingWorkBatchExecutionResources(
        sha("9") if fault == "hash" else batch.resource_profile_sha256,
        1 if fault == "time" else batch.timeout_seconds,
        4 if fault == "output" else batch.vector_max_bytes,
    )
    fence = Fence()
    with pytest.raises(EmbeddingWorkBatchExecutionError, match="RESOURCES_MISMATCH"):
        execute_embedding_work_batch(
            batch,
            resources=actual,
            backend_scope=lambda: pytest.fail("must not construct a model"),
            fence=fence,
        )
    assert fence.events == []


@pytest.mark.parametrize("clock", [lambda: True, lambda: -1, lambda: 0.1])
def test_invalid_clock_is_not_silently_accepted(clock) -> None:
    batch = parse_embedding_work_batch_input(batch_body())
    with pytest.raises(EmbeddingWorkBatchExecutionError, match="CLOCK_INVALID"):
        execute_embedding_work_batch(
            batch,
            resources=resources(batch),
            backend_scope=lambda: pytest.fail("must not construct a model"),
            fence=Fence(),
            clock_ns=clock,
        )


@pytest.mark.parametrize("rows_per_child", [512, 513])
def test_document_total_row_budget_is_not_the_sum_of_independent_child_limits(
    rows_per_child: int,
) -> None:
    body = batch_body("DOCUMENT")
    for index, child in enumerate(body["children"]):
        child["request"] = embedding_input(
            *(f"합성 자료 {index}-{row}" for row in range(rows_per_child)),
            job_id=child["request"]["job_id"],
        ).model_dump(mode="json")
    body = seal(body, "request_sha256")
    if rows_per_child == 512:
        batch = parse_embedding_work_batch_input(body)
        assert sum(len(child.request.rows) for child in batch.children) == 1024
    else:
        with pytest.raises(ERRORS, match="row/output bound"):
            parse_embedding_work_batch_input(body)


def test_whole_canonical_byte_budget_is_checked_before_backend(monkeypatch) -> None:
    import eom_catalog_contracts.embedding_work_batch as contracts

    body = batch_body()
    monkeypatch.setattr(contracts, "MAX_EMBEDDING_WORK_BATCH_BYTES", 1024)
    with pytest.raises(ERRORS, match="canonical byte budget"):
        parse_embedding_work_batch_input(body)


def test_constructed_nested_objects_do_not_bypass_closed_schema() -> None:
    batch = parse_embedding_work_batch_input(batch_body())
    request = batch.children[0].request.model_copy(update={"unapproved": "extra"})
    child = batch.children[0].model_copy(update={"request": request})
    modified = batch.model_copy(update={"children": (child, *batch.children[1:])})
    with pytest.raises(ERRORS):
        parse_embedding_work_batch_input(modified)


@pytest.mark.parametrize(
    "hash_value,timeout,maximum",
    [
        ("arbitrary", 180, 1024),
        (sha("1"), True, 1024),
        (sha("1"), 180.0, 1024),
        (sha("1"), 181, 1024),
        (sha("1"), 180, True),
        (sha("1"), 180, 16 * 1024**2 + 1),
    ],
)
def test_owner_resource_value_is_also_strict(hash_value, timeout, maximum) -> None:
    with pytest.raises(EmbeddingWorkBatchExecutionError, match="RESOURCES_INVALID"):
        EmbeddingWorkBatchExecutionResources(hash_value, timeout, maximum)
