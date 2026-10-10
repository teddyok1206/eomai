from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from typing import Any, Literal

import pytest
from eom_catalog_contracts.inference_transfer_experiment import (
    CanonicalExperimentItemText,
    InferenceTransferExperimentRequest,
    InferenceTransferExperimentResult,
    StagedExperimentEntry,
    validate_experiment_result,
)
from eom_catalog_service.inference_transfer_experiment import (
    experiment_view_text,
    run_staged_inference_transfer_experiment,
)
from eom_catalog_service.inference_transfer_ports import EmbeddingRankerProvenance
from eom_identifiers import canonical_json_bytes, content_sha256
from pydantic import ValidationError

from tests.unit.inference_transfer_experiment_fixtures import entry, experiment_request
from tests.unit.inference_transfer_fixtures import NOW, sha


class FakeMeasuredBackend:
    dimension = 2
    provenance = EmbeddingRankerProvenance("TEST_ONLY", None)

    def __init__(self) -> None:
        self.token_calls: list[tuple[tuple[str, ...], str]] = []
        self.encode_calls: list[tuple[tuple[str, ...], str]] = []
        self.count: Callable[[str], int] = lambda text: len(text.split()) + 3
        self.vector: Callable[[str], tuple[float, ...]] = lambda _text: (1.0, 0.0)

    def token_lengths(
        self, texts: tuple[str, ...], *, purpose: Literal["QUERY", "DOCUMENT"]
    ) -> tuple[int, ...]:
        self.token_calls.append((texts, purpose))
        return tuple(self.count(text) for text in texts)

    def encode(
        self, texts: tuple[str, ...], *, purpose: Literal["QUERY", "DOCUMENT"]
    ) -> tuple[tuple[float, ...], ...]:
        self.encode_calls.append((texts, purpose))
        return tuple(self.vector(text) for text in texts)


def run(
    request: InferenceTransferExperimentRequest | None = None,
    backend: FakeMeasuredBackend | None = None,
) -> InferenceTransferExperimentResult:
    return run_staged_inference_transfer_experiment(
        request or experiment_request(),
        backend or FakeMeasuredBackend(),
        execution_id="embeddingexecution_" + "f" * 32,
        created_at=NOW,
        clock=lambda: 1.0,
    )


def changed_content(value: StagedExperimentEntry, text: str | None) -> StagedExperimentEntry:
    return StagedExperimentEntry(
        profile=value.profile,
        content=None
        if text is None
        else CanonicalExperimentItemText(
            text=text,
            original_source=value.profile.source_basis.source.artifact_member,
            text_sha256=content_sha256(text),
        ),
        metadata=value.metadata,
        limitations=value.limitations,
    )


def test_each_view_is_encoded_once_for_many_queries_with_same_candidate_pool() -> None:
    value = experiment_request()
    body = value.model_dump(mode="json", exclude={"request_sha256"})
    body["queries"] = [
        {
            "profile_id": e.profile.profile_id,
            "profile_revision_id": e.profile.profile_revision_id,
            "profile_sha256": e.profile.profile_sha256,
            "schema_ref": "eom://schemas/knowledge/item-inference-transfer/1.0",
        }
        for e in value.entries
    ]
    value = InferenceTransferExperimentRequest.model_validate(
        body | {"request_sha256": content_sha256(body)}
    )
    backend = FakeMeasuredBackend()
    result = run(value, backend)
    assert result.status == "MEASURED"
    assert len(backend.token_calls) == len(backend.encode_calls) == 3
    assert all(len(texts) == 3 and purpose == "DOCUMENT" for texts, purpose in backend.encode_calls)
    assert len(result.query_results) == 9
    assert result.measurements.encoded_text_count == 9
    assert result.measurements.encoding_requests_completed == 3
    assert result.human_transfer_review == "NOT_EVALUATED"
    assert result.current_authorization == "NOT_VERIFIED_BY_HARNESS"
    assert result.production_activation == "NOT_PERFORMED"
    assert result.data_provenance == "TEST_ONLY_SYNTHETIC"
    assert result.backend_kind == "TEST_ONLY"
    assert result.actual_model_manifest_sha256 is None
    assert result.baseline_status == "NOT_MATERIALIZED"
    assert "cosine_millionths" in canonical_json_bytes(result.model_dump(mode="json")).decode()


def test_ties_are_stable_and_result_contains_no_model_vectors_or_item_payloads() -> None:
    first, second = run(), run()
    assert first == second
    assert first.query_results[0].ranks[0].profile.profile_id.endswith("b" * 32)
    assert first.query_results[0].ranks[1].profile.profile_id.endswith("c" * 32)
    payload = first.model_dump(mode="json")
    assert "entries" not in payload and "vectors" not in payload and "source_basis" not in payload


def test_full_precision_controls_ties_not_integer_wire_rounding() -> None:
    backend = FakeMeasuredBackend()
    backend.vector = lambda text: (1.0, 0.0001) if "물체 B" in text else (1.0, 0.0)
    result = run(backend=backend)
    ranks = result.query_results[0].ranks
    assert ranks[0].profile.profile_id.endswith("c" * 32)
    assert ranks[1].profile.profile_id.endswith("b" * 32)
    assert ranks[0].cosine_millionths == ranks[1].cosine_millionths == 1_000_000


@pytest.mark.parametrize("count,status", [(512, "ENCODABLE"), (513, "TOKEN_OVERFLOW")])
def test_token_boundary_is_observed_without_silent_truncation(count: int, status: str) -> None:
    text = "구체적인 조건을 지키고 에너지는 보존되지 않는다. " * 30
    value = experiment_request(entry("a"), entry("b"), changed_content(entry("c"), text))
    backend = FakeMeasuredBackend()
    backend.count = lambda observed: count if observed == text else 10
    result = run(value, backend)
    rows = [
        row
        for row in result.coverage
        if row.profile.profile_id.endswith("c" * 32) and row.view == "CONTENT_ONLY"
    ]
    assert rows[0].token_count == count and rows[0].status == status
    assert text in backend.token_calls[0][0]
    if status == "TOKEN_OVERFLOW":
        assert len(result.common_profiles) == 2
        assert all(text not in texts for texts, _ in backend.encode_calls)
    else:
        assert len(result.common_profiles) == 3
        assert text in backend.encode_calls[0][0]


@pytest.mark.parametrize(
    "kind,status",
    [("missing", "MISSING_SOURCE_VIEW"), ("empty", "EMPTY"), ("bytes", "BYTE_LIMIT_EXCEEDED")],
)
def test_missing_empty_and_utf8_limit_are_distinct_and_do_not_enter_tokenizer(
    kind: str, status: str
) -> None:
    text = None if kind == "missing" else "" if kind == "empty" else "가" * 100_000
    value = experiment_request(entry("a"), entry("b"), changed_content(entry("c"), text))
    backend = FakeMeasuredBackend()
    result = run(value, backend)
    row = next(
        row
        for row in result.coverage
        if row.view == "CONTENT_ONLY" and row.profile.profile_id.endswith("c" * 32)
    )
    assert row.status == status and row.token_count is None
    assert len(backend.token_calls[0][0]) == 2
    assert len(result.common_profiles) == 2
    assert all(len(texts) == 2 for texts, _ in backend.encode_calls)


@pytest.mark.parametrize("reason", ["threshold", "query", "budget"])
def test_insufficient_common_pool_does_not_start_model_forward(reason: str) -> None:
    if reason == "query":
        value = experiment_request(changed_content(entry("a"), None), entry("b"), entry("c"))
    else:
        value = experiment_request(
            **(
                {"minimum_common_candidates": 3}
                if reason == "threshold"
                else {"maximum_encoded_texts": 8}
            )
        )
    backend = FakeMeasuredBackend()
    result = run(value, backend)
    assert result.status == "INSUFFICIENT_ENCODING_COVERAGE"
    assert result.query_results == () and backend.encode_calls == []
    assert result.measurements.encoding_requests_started == 0


@pytest.mark.parametrize(
    "vector", [(0.0, 0.0), (float("nan"), 1.0), (float("inf"), 1.0), (True, 0.0), (1.0,)]
)
def test_malformed_vector_never_becomes_measurement(vector: Any) -> None:
    backend = FakeMeasuredBackend()
    backend.vector = lambda _text: vector
    with pytest.raises(ValueError, match="VECTOR_INVALID"):
        run(backend=backend)


@pytest.mark.parametrize("count", [0, True, -1, 3.5, None])
def test_malformed_token_count_is_not_encoding_coverage(count: Any) -> None:
    backend = FakeMeasuredBackend()
    backend.count = lambda _text: count
    with pytest.raises(ValueError, match="TOKEN_MEASUREMENT_INVALID"):
        run(backend=backend)


def test_model_identity_change_during_measurement_fails_before_output() -> None:
    backend = FakeMeasuredBackend()

    def changed(_text: str) -> int:
        backend.dimension = 3
        return 10

    backend.count = changed
    with pytest.raises(ValueError, match="MODEL_CHANGED"):
        run(backend=backend)
    assert backend.encode_calls == []


def test_model_copy_forgery_is_revalidated_at_public_boundary() -> None:
    value = experiment_request().model_copy(update={"request_sha256": sha("f")})
    backend = FakeMeasuredBackend()
    with pytest.raises(ValidationError):
        run(value, backend)
    assert backend.token_calls == [] and backend.encode_calls == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("human_transfer_review", "PASS"),
        ("data_provenance", "AUTHORIZED_CORPUS_SNAPSHOT"),
        ("common_profile_set_sha256", sha("f")),
        ("actual_model_manifest_sha256", sha("f")),
    ],
)
def test_result_cannot_promote_quality_provenance_or_change_population(
    field: str, value: Any
) -> None:
    request = experiment_request()
    result = run(request).model_copy(update={field: value})
    with pytest.raises((ValidationError, ValueError)):
        validate_experiment_result(request, result)


@pytest.mark.parametrize("mutation", ["text", "bytes", "tokens", "origin", "counts", "threshold"])
def test_rehashed_results_bind_exact_views_and_execution_budget(mutation: str) -> None:
    request = experiment_request()
    body = run(request).model_dump(mode="json", exclude={"result_sha256"})
    if mutation == "text":
        body["coverage"][0]["text_sha256"] = sha("f")
    elif mutation == "bytes":
        body["coverage"][0]["utf8_bytes"] += 1
    elif mutation == "tokens":
        body["coverage"][0]["token_count"] = 0
    elif mutation == "origin":
        body["data_provenance"] = "AUTHORIZED_CORPUS_SNAPSHOT"
    elif mutation == "counts":
        body["measurements"]["requested_text_count"] -= 1
    else:
        body["status"] = "INSUFFICIENT_ENCODING_COVERAGE"
        body["query_results"] = []
        for name in (
            "requested_text_count",
            "encoded_text_count",
            "encoding_requests_started",
            "encoding_requests_completed",
        ):
            body["measurements"][name] = 0
    forged = InferenceTransferExperimentResult.model_validate(
        body | {"result_sha256": content_sha256(body)}
    )
    with pytest.raises(ValueError):
        validate_experiment_result(request, forged)


def test_content_metadata_and_claim_text_keep_distinct_information_and_no_ids() -> None:
    value = entry()
    assert "합이 일정하다" in str(experiment_view_text(value, "CONCRETE_FACETS"))
    assert "36 km/h" in str(experiment_view_text(value, "CONTENT_ONLY"))
    assert experiment_view_text(value, "METADATA_ONLY") == "CONCEPT: 역학적 에너지"
    for view in ("CONTENT_ONLY", "CONCRETE_FACETS", "METADATA_ONLY"):
        text = str(experiment_view_text(value, view))
        assert value.profile.profile_id not in text and value.profile.profile_sha256 not in text


def test_core_experiment_import_does_not_import_numerical_or_filesystem_adapter() -> None:
    code = (
        "import sys; import eom_catalog_service.inference_transfer_experiment; "
        "assert all(name not in sys.modules for name in "
        "('torch', 'transformers', 'numpy', 'eom_catalog_service.local_embedding_adapter'))"
    )
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)
