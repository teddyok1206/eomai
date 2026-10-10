"""Bounded pure staged experiment use case: no source fetching, persistence or authority."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from time import perf_counter
from typing import Any, Literal

from eom_catalog_contracts.inference_transfer_experiment import (
    VIEWS,
    ExperimentMeasurements,
    ExperimentQueryResult,
    ExperimentRank,
    ExperimentTokenCoverage,
    ExperimentView,
    InferenceTransferExperimentRequest,
    InferenceTransferExperimentResult,
    profile_set_sha256,
    validate_experiment_result,
)
from eom_catalog_contracts.inference_transfer_experiment import (
    experiment_view_text as experiment_view_text,
)
from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfilePointer
from eom_catalog_contracts.validation import validate_contract
from eom_identifiers import content_sha256

from eom_catalog_service.inference_transfer_ports import (
    EmbeddingRankerProvenance,
    TokenMeasuredEmbeddingBackend,
)
from eom_catalog_service.inference_transfer_vectors import (
    normalized_vector,
    rank_normalized_vectors,
)


def _provenance(backend: TokenMeasuredEmbeddingBackend) -> EmbeddingRankerProvenance:
    value = backend.provenance
    if not isinstance(value, EmbeddingRankerProvenance):
        raise ValueError("INFERENCE_EXPERIMENT_MODEL_PROVENANCE_INVALID")
    # Revalidate even an object manufactured by a test or an alternate adapter.
    return EmbeddingRankerProvenance(value.kind, value.model_spec)


def run_staged_inference_transfer_experiment(
    request: InferenceTransferExperimentRequest,
    backend: TokenMeasuredEmbeddingBackend,
    *,
    execution_id: str,
    created_at: datetime,
    model_load_milliseconds: int = 0,
    peak_rss_kib_linux: int = 0,
    clock: Callable[[], float] = perf_counter,
) -> InferenceTransferExperimentResult:
    """Measure an exact frozen input; caller owns staging, current reauthorization and commit."""
    request = InferenceTransferExperimentRequest.model_validate(request.model_dump(mode="json"))
    validate_contract("item-inference-transfer-experiment", request.model_dump(mode="json"))
    initial = _provenance(backend)
    dimension = backend.dimension
    if type(dimension) is not int or not 1 <= dimension <= 4096:
        raise ValueError("LOCAL_EMBEDDING_VECTOR_INVALID")
    if initial.model_spec is not None and (
        initial.model_spec != request.model_spec or dimension != initial.model_spec.dimension
    ):
        raise ValueError("INFERENCE_EXPERIMENT_MODEL_PIN_MISMATCH")

    def guard() -> None:
        if _provenance(backend) != initial or backend.dimension != dimension:
            raise ValueError("INFERENCE_EXPERIMENT_MODEL_CHANGED")

    pointers = tuple(
        InferenceTransferProfilePointer.from_profile(e.profile) for e in request.entries
    )
    texts: dict[tuple[InferenceTransferProfilePointer, ExperimentView], str | None] = {}
    coverage: list[ExperimentTokenCoverage] = []
    token_started = clock()
    for view in VIEWS:
        measurable: list[tuple[InferenceTransferProfilePointer, str]] = []
        rows: dict[InferenceTransferProfilePointer, ExperimentTokenCoverage] = {}
        for pointer, entry in zip(pointers, request.entries, strict=True):
            text = experiment_view_text(entry, view)
            texts[pointer, view] = text
            size = len(text.encode("utf-8")) if text is not None else 0
            status: Literal["MISSING_SOURCE_VIEW", "EMPTY", "BYTE_LIMIT_EXCEEDED"] | None = (
                "MISSING_SOURCE_VIEW"
                if text is None
                else "EMPTY"
                if not text.strip()
                else "BYTE_LIMIT_EXCEEDED"
                if size > request.recipe.maximum_text_bytes
                else None
            )
            if status is None:
                assert text is not None
                measurable.append((pointer, text))
            else:
                rows[pointer] = ExperimentTokenCoverage(
                    profile=pointer,
                    view=view,
                    text_sha256=content_sha256(text),
                    utf8_bytes=size,
                    token_count=None,
                    status=status,
                )
        if measurable:
            guard()
            lengths = backend.token_lengths(
                tuple(text for _, text in measurable), purpose="DOCUMENT"
            )
            guard()
            if (
                not isinstance(lengths, tuple)
                or len(lengths) != len(measurable)
                or any(type(count) is not int or not 0 < count <= 4 * 1024**2 for count in lengths)
            ):
                raise ValueError("INFERENCE_EXPERIMENT_TOKEN_MEASUREMENT_INVALID")
            for (pointer, text), count in zip(measurable, lengths, strict=True):
                rows[pointer] = ExperimentTokenCoverage(
                    profile=pointer,
                    view=view,
                    text_sha256=content_sha256(text),
                    utf8_bytes=len(text.encode("utf-8")),
                    token_count=count,
                    status="ENCODABLE"
                    if count <= request.model_spec.maximum_tokens
                    else "TOKEN_OVERFLOW",
                )
        coverage.extend(rows[pointer] for pointer in pointers)
    token_ms = round(1000 * (clock() - token_started))
    common_set = set.intersection(
        *(
            {row.profile for row in coverage if row.view == view and row.status == "ENCODABLE"}
            for view in VIEWS
        )
    )
    common = tuple(pointer for pointer in pointers if pointer in common_set)
    enough = (
        len(common) - 1 >= request.budget.minimum_common_candidates
        and set(request.queries).issubset(common_set)
        and len(common) * len(VIEWS) <= request.budget.maximum_encoded_texts
    )
    queries: list[ExperimentQueryResult] = []
    started_requests = completed_requests = requested_texts = encoded_texts = 0
    encoding_ms = 0
    if enough:
        for view in VIEWS:
            selected = tuple(texts[pointer, view] for pointer in common)
            assert all(isinstance(text, str) for text in selected)
            forward_input = tuple(str(text) for text in selected)
            guard()
            started_requests += 1
            requested_texts += len(common)
            encode_started = clock()
            vectors = backend.encode(forward_input, purpose="DOCUMENT")
            encoding_ms += round(1000 * (clock() - encode_started))
            guard()
            if not isinstance(vectors, tuple) or len(vectors) != len(common):
                raise ValueError("LOCAL_EMBEDDING_VECTOR_INVALID")
            matrix = {
                pointer: normalized_vector(vector, dimension)
                for pointer, vector in zip(common, vectors, strict=True)
            }
            completed_requests += 1
            encoded_texts += len(common)
            for query in request.queries:
                rank_started = clock()
                scores = rank_normalized_vectors(
                    matrix[query],
                    tuple(
                        (pointer, vector) for pointer, vector in matrix.items() if pointer != query
                    ),
                    top_k=request.budget.top_k,
                )
                queries.append(
                    ExperimentQueryResult(
                        query=query,
                        view=view,
                        ranks=tuple(
                            ExperimentRank(
                                profile=row.profile,
                                rank=index,
                                cosine_millionths=round(1_000_000 * row.cosine_similarity),
                            )
                            for index, row in enumerate(scores, start=1)
                        ),
                        ranking_milliseconds=round(1000 * (clock() - rank_started)),
                    )
                )
    guard()
    limitations = [
        "Harness does not verify current permissions; caller must reauthorize "
        "the entire admitted population before publication.",
        "Cosine ranking is a model measurement, not decisive-inference transfer "
        "or educational quality approval.",
        "Exact profile claims may include answer-bearing judgments; "
        "this is not an answer-free crux-only representation.",
        "Count/thread/input budgets are not enforced wall-time/RSS OS isolation limits.",
        "Supplied official Graph baseline retains its exact original candidates and is not "
        "proven comparable with the token-eligible common pool.",
    ]
    if request.scope.data_provenance == "TEST_ONLY_SYNTHETIC":
        limitations.append(
            "Synthetic staged data is not a real-corpus acceptance "
            "or Catalog authorization receipt."
        )
    if not enough:
        limitations.append(
            "Common pool is below threshold, excludes a requested query, or exceeds "
            "the encoding-text budget; no model forward was requested."
        )
    body: dict[str, Any] = {
        "schema_version": "inference-transfer-experiment-result/1.0",
        "execution_id": execution_id,
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "request_sha256": request.request_sha256,
        "input_profile_set_sha256": request.scope.eligible_profile_set_sha256,
        "model_manifest_sha256": request.model_spec.manifest_sha256,
        "actual_model_manifest_sha256": None
        if initial.model_spec is None
        else initial.model_spec.manifest_sha256,
        "view_recipe_sha256": request.recipe.recipe_sha256,
        "status": "MEASURED" if enough else "INSUFFICIENT_ENCODING_COVERAGE",
        "common_profiles": [pointer.model_dump(mode="json") for pointer in common],
        "common_profile_set_sha256": profile_set_sha256(common),
        "coverage": [row.model_dump(mode="json") for row in coverage],
        "query_results": [row.model_dump(mode="json") for row in queries],
        "baseline_status": "SUPPLIED_NOT_REEXECUTED" if request.baselines else "NOT_MATERIALIZED",
        "measurements": ExperimentMeasurements(
            model_load_milliseconds=model_load_milliseconds,
            token_measurement_milliseconds=token_ms,
            encoding_milliseconds=encoding_ms,
            peak_rss_kib_linux=peak_rss_kib_linux,
            encoding_requests_started=started_requests,
            encoding_requests_completed=completed_requests,
            requested_text_count=requested_texts,
            encoded_text_count=encoded_texts,
        ).model_dump(mode="json"),
        "backend_kind": initial.kind,
        "data_provenance": request.scope.data_provenance,
        "current_authorization": "NOT_VERIFIED_BY_HARNESS",
        "human_transfer_review": "NOT_EVALUATED",
        "production_activation": "NOT_PERFORMED",
        "limitations": limitations,
    }
    result = InferenceTransferExperimentResult.model_validate(
        body | {"result_sha256": content_sha256(body)}
    )
    validate_experiment_result(request, result)
    validate_contract("item-inference-transfer-experiment", result.model_dump(mode="json"))
    return result
