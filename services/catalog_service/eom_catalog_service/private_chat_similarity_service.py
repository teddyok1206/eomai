"""Owned-question vector observations through mandatory owners and shared document checks."""

from __future__ import annotations

import re

from eom_catalog_contracts.embedding_private_chat_query import (
    EmbeddingPrivateChatQueryInput,
    EmbeddingPrivateChatQueryResult,
    validate_private_chat_query_result,
)
from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.embedding_vector_binary import read_unit_vectors
from eom_catalog_contracts.inference_transfer_embedding import EmbeddingVectorRowRef
from eom_catalog_contracts.private_chat_query_basis import private_chat_query_text_sha256
from eom_catalog_contracts.private_chat_similarity import (
    PRIVATE_CHAT_LIMITATION_ORDER,
    PrivateChatPopulation,
    PrivateChatQueryExecutionPointer,
    PrivateChatSimilarityContext,
    PrivateChatSimilarityRequest,
    PrivateChatViewCoverage,
    validate_private_chat_query_execution,
)
from eom_catalog_contracts.similarity_context import (
    SimilarityCandidate,
    SimilarityFailureCode,
    SimilarityUnavailableReason,
    SimilarityVectorObservation,
)
from eom_identifiers import content_sha256
from jsonschema.exceptions import ValidationError as JsonSchemaError

from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    ResolvedPinnedEmbeddingIndex,
)
from eom_catalog_service.inference_transfer_vectors import rank_normalized_vectors
from eom_catalog_service.private_chat_similarity_ports import (
    PreparedPrivateChatSimilarity,
    PrivateChatQueryUnavailable,
    PrivateChatSimilarityReadPort,
    VerifiedPrivateChatQueryRead,
)
from eom_catalog_service.similarity_context_ports import (
    PreparedSimilaritySource,
    SimilarityContextReadError,
)
from eom_catalog_service.similarity_document_read_validation import (
    validate_prepared_similarity_sources,
    validate_similarity_document_reads,
)


def _context(
    request: PrivateChatSimilarityRequest,
    *,
    status: str,
    population: PrivateChatPopulation | None = None,
    execution: PrivateChatQueryExecutionPointer | None = None,
    candidates: tuple[SimilarityCandidate, ...] = (),
    error: SimilarityFailureCode | None = None,
) -> PrivateChatSimilarityContext:
    flags: set[str] = set(PRIVATE_CHAT_LIMITATION_ORDER[:3])
    if population is not None:
        coverage = population.views[0]
        for condition, flag in (
            (coverage.status == "UNAVAILABLE", "VECTOR_NOT_AVAILABLE"),
            (bool(population.missing_report_count), "PARTIAL_REPORT_COVERAGE"),
            (bool(coverage.missing_view_count), "PARTIAL_VIEW_COVERAGE"),
            (population.truncated, "BOUNDED_SCOPE_TRUNCATED"),
            (not candidates, "NO_RELATED_CANDIDATES"),
        ):
            if condition:
                flags.add(flag)
    document = {
        "schema_version": "system-rag-private-chat-similarity-context/1.0",
        "request": request.model_dump(mode="json"),
        "status": status,
        "population": None if population is None else population.model_dump(mode="json"),
        "query_execution": None if execution is None else execution.model_dump(mode="json"),
        "candidates": [value.model_dump(mode="json") for value in candidates],
        "limitations": [v for v in PRIVATE_CHAT_LIMITATION_ORDER if v in flags],
        "error_code": error,
    }
    return PrivateChatSimilarityContext.model_validate(
        document | {"context_sha256": content_sha256(document)}
    )


def _prepare(
    request: PrivateChatSimilarityRequest, prepared: PreparedPrivateChatSimilarity
) -> dict[str, PreparedSimilaritySource]:
    if type(prepared) is not PreparedPrivateChatSimilarity or (
        prepared.request_sha256 != request.request_sha256
        or prepared.query_basis != request.query_basis
        or type(prepared.truncated) is not bool
        or private_chat_query_text_sha256(prepared.query_text)
        != request.query_basis.query_text_sha256
    ):
        raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
    return validate_prepared_similarity_sources(
        prepared.sources,
        source_classes=request.source_classes,
        maximum_sources=request.maximum_sources,
    )


def _query_vector(
    request: PrivateChatSimilarityRequest,
    prepared: PreparedPrivateChatSimilarity,
    query: VerifiedPrivateChatQueryRead,
) -> tuple[float, ...]:
    if type(query) is not VerifiedPrivateChatQueryRead or type(query.binary) is not bytes:
        raise ValueError("private QUERY read differs")
    native = EmbeddingPrivateChatQueryInput.model_validate(
        raw_similarity_contract_value(query.request)
    )
    result = EmbeddingPrivateChatQueryResult.model_validate(
        raw_similarity_contract_value(query.result)
    )
    validate_private_chat_query_result(native, result)
    selection = request.views[0]
    if selection.index is None or (
        native.context_request_sha256 != request.request_sha256
        or native.basis != request.query_basis
        or native.row.text != prepared.query_text
        or native.spaces != selection.index.spaces
        or native.document_recipe != selection.recipe
        or native.row.encoding.storage_partition != selection.index.storage_partition
    ):
        raise ValueError("private QUERY parent/basis/index differs")
    return read_unit_vectors(
        query.binary,
        dimension=result.shard.dimension,
        row_count=1,
        expected_sha256=result.shard.binary.sha256,
    )[0]


def _compose(
    request: PrivateChatSimilarityRequest,
    prepared: PreparedPrivateChatSimilarity,
    sources: dict[str, PreparedSimilaritySource],
    query: VerifiedPrivateChatQueryRead | None,
    vector: tuple[float, ...],
    document: ResolvedPinnedEmbeddingIndex | None,
    unavailable: SimilarityUnavailableReason,
) -> PrivateChatSimilarityContext:
    profiles = {v.profile: v for v in sources.values() if v.profile is not None}
    candidates: list[SimilarityCandidate] = []
    execution = None
    if document is None:
        coverage = PrivateChatViewCoverage(
            view="CONTENT_ONLY",
            status="UNAVAILABLE",
            available_binding_count=None,
            binding_set_sha256=None,
            scored_count=0,
            missing_view_count=None,
            reason=unavailable,
        )
    else:
        assert query is not None
        rows = {v.row.encoding.encoding_sha256: v.values for v in document.numerical_rows}
        by_profile = {v.profile: v for v in document.bindings}
        # Unlike approved-reference lookup, a private question has no self Item to remove.
        ranked = rank_normalized_vectors(
            vector,
            tuple((v.profile, rows[v.encoding.encoding_sha256]) for v in document.bindings),
            top_k=request.top_k,
        )
        for rank, scored in enumerate(ranked, 1):
            source = profiles[scored.profile]
            assert source.solution_evidence is not None
            candidates.append(
                SimilarityCandidate(
                    source=source.source,
                    profile=scored.profile,
                    solution_evidence=source.solution_evidence,
                    observations=(
                        SimilarityVectorObservation(
                            view="CONTENT_ONLY",
                            rank=rank,
                            cosine_millionths=round(scored.cosine_similarity * 1_000_000),
                            query_row=EmbeddingVectorRowRef(
                                shard_manifest=query.shard_member,
                                row_index=0,
                                encoding_sha256=query.request.row.encoding.encoding_sha256,
                            ),
                            document_row=by_profile[scored.profile].row_ref,
                        ),
                    ),
                    explanation=None,
                )
            )
        count = len(document.bindings)
        missing = len(profiles) - count
        coverage = PrivateChatViewCoverage(
            view="CONTENT_ONLY",
            status="EMPTY" if not count else "PARTIAL" if missing else "READY",
            available_binding_count=count,
            binding_set_sha256=content_sha256(sorted(v.binding_sha256 for v in document.bindings)),
            scored_count=count,
            missing_view_count=missing,
            reason=None,
        )
        execution = PrivateChatQueryExecutionPointer(
            job_id=query.request.job_id,
            query_request_id=query.request.query_request_id,
            request_sha256=query.request.request_sha256,
            input_set_sha256=query.request.input_set_sha256,
            basis_sha256=query.request.basis.basis_sha256,
            result_member=query.result_member,
            result_sha256=query.result.result_sha256,
        )
    population = PrivateChatPopulation(
        authorized_source_count=len(sources),
        authorized_source_set_sha256=content_sha256(
            [sources[k].source.model_dump(mode="json") for k in sorted(sources)]
        ),
        accepted_profile_count=len(profiles),
        accepted_profile_set_sha256=content_sha256(
            [
                v.model_dump(mode="json")
                for v in sorted(
                    profiles, key=lambda p: (p.profile_id, p.profile_revision_id, p.profile_sha256)
                )
            ]
        ),
        missing_report_count=len(sources) - len(profiles),
        truncated=prepared.truncated,
        views=(coverage,),
    )
    partial = bool(
        population.missing_report_count or coverage.missing_view_count or prepared.truncated
    )
    context = _context(
        request,
        status="UNAVAILABLE"
        if document is None
        else "EMPTY"
        if not candidates
        else "PARTIAL"
        if partial
        else "READY",
        population=population,
        execution=execution,
        candidates=tuple(candidates),
    )
    if query is not None:
        validate_private_chat_query_execution(
            context, query.request, query.result, query.result_member, query.shard_member
        )
    return context


class PrivateChatSimilarityApplicationService:
    """No fallback authority, approved-anchor conversion or implicit backend execution."""

    def __init__(self, owner: PrivateChatSimilarityReadPort | None) -> None:
        self.owner = owner

    def compose(
        self, caller: EmbeddingRegistryCaller, request: PrivateChatSimilarityRequest
    ) -> PrivateChatSimilarityContext:
        request = PrivateChatSimilarityRequest.model_validate(
            raw_similarity_contract_value(request)
        )
        try:
            if type(caller) is not EmbeddingRegistryCaller or (
                type(caller.operator_id) is not str
                or not re.fullmatch(r"operator_[0-9a-f]{32}", caller.operator_id)
                or self.owner is None
                or not all(
                    callable(getattr(self.owner, name, None))
                    for name in (
                        "prepare_private_chat_similarity",
                        "resolve_private_chat_query",
                        "read_private_chat_similarity_index",
                        "reauthorize_private_chat_similarity",
                    )
                )
            ):
                raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
            prepared = self.owner.prepare_private_chat_similarity(caller, request)
            sources = _prepare(request, prepared)
            query = None
            document = None
            vector: tuple[float, ...] = ()
            unavailable: SimilarityUnavailableReason = "INDEX_NOT_PREPARED"
            if request.views[0].index is not None:
                try:
                    outcome = self.owner.resolve_private_chat_query(caller, request, prepared)
                    if isinstance(outcome, PrivateChatQueryUnavailable):
                        if outcome.reason not in {"QUERY_NOT_OFFERED", "INPUT_OVERFLOW"}:
                            raise ValueError("invalid private QUERY absence")
                        unavailable = outcome.reason
                    else:
                        query = outcome
                        vector = _query_vector(request, prepared, query)
                except SimilarityContextReadError:
                    raise
                except Exception:
                    raise SimilarityContextReadError("QUERY_RESULT_INVALID") from None
                if query is not None:
                    try:
                        document = validate_similarity_document_reads(
                            request,
                            sources,
                            self.owner.read_private_chat_similarity_index(
                                caller, request, prepared
                            ),
                            {"CONTENT_ONLY"},
                        )["CONTENT_ONLY"]
                    except SimilarityContextReadError:
                        raise
                    except Exception:
                        raise SimilarityContextReadError("INDEX_POINTER_INVALID") from None
            try:
                context = _compose(request, prepared, sources, query, vector, document, unavailable)
            except (JsonSchemaError, ValueError, TypeError, KeyError):
                raise SimilarityContextReadError("QUERY_RESULT_INVALID") from None
            self.owner.reauthorize_private_chat_similarity(caller, request, prepared)
            return context
        except SimilarityContextReadError as error:
            code = error.code
        except Exception:
            code = "SOURCE_POINTER_INVALID"
        return _context(request, status="FAILED", error=code)
