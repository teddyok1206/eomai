"""Approved-reference composition; independent scores never become Evidence or approval."""

from __future__ import annotations

import re

from eom_catalog_contracts.embedding_reference_query import (
    REFERENCE_QUERY_RESULT_REF,
    ReferenceQueryExecutionPointer,
    parse_embedding_reference_query_result,
    raw_similarity_contract_value,
)
from eom_catalog_contracts.embedding_reference_query_v11 import (
    parse_supported_reference_query_input,
    validate_supported_reference_query_result,
)
from eom_catalog_contracts.embedding_vector_binary import read_unit_vectors
from eom_catalog_contracts.inference_transfer_embedding import (
    SHARD_SCHEMA_REF,
    EmbeddingVectorRowRef,
)
from eom_catalog_contracts.inference_transfer_experiment import ExperimentView
from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfilePointer
from eom_catalog_contracts.similarity_context import (
    SimilarityCandidate,
    SimilarityContext,
    SimilarityContextRequest,
    SimilarityFailureCode,
    SimilarityGraphObservation,
    SimilarityLimitation,
    SimilarityObservation,
    SimilarityPopulation,
    SimilarityUnavailableReason,
    SimilarityVectorObservation,
    SimilarityViewCoverage,
    parse_similarity_context,
    parse_similarity_context_request,
    validate_similarity_query_execution,
)
from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema.exceptions import ValidationError as JsonSchemaError

from eom_catalog_service.embedding_registry_ports import (
    AUTHORING_REFERENCE_PURPOSES,
    EmbeddingRegistryCaller,
    ResolvedPinnedEmbeddingIndex,
)
from eom_catalog_service.inference_transfer_service import bounded_profile_channel_union
from eom_catalog_service.inference_transfer_vectors import rank_normalized_vectors
from eom_catalog_service.similarity_context_ports import (
    PreparedSimilarityContext,
    PreparedSimilaritySource,
    SimilarityContextReadError,
    SimilarityContextSourceReadPort,
    SimilarityQueryUnavailable,
    SimilarityReferenceQueryReadPort,
    VerifiedReferenceQueryRead,
)
from eom_catalog_service.similarity_document_read_validation import (
    validate_prepared_similarity_sources,
    validate_similarity_document_reads,
)


def validate_similarity_preparation(
    request: SimilarityContextRequest, prepared: PreparedSimilarityContext
) -> dict[str, PreparedSimilaritySource]:
    if not isinstance(prepared, PreparedSimilarityContext) or (
        prepared.request_sha256 != request.request_sha256
        or type(prepared.sources) is not tuple
        or type(prepared.query_texts) is not tuple
        or type(prepared.graph_scores) is not tuple
        or type(prepared.truncated) is not bool
        or len(prepared.sources) > request.maximum_sources
        or len(prepared.query_texts) > 3
        or len(prepared.graph_scores) > 64
        or (
            prepared.graph_evidence is not None
            and not isinstance(prepared.graph_evidence, ArtifactMemberPointer)
        )
    ):
        raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
    sources = validate_prepared_similarity_sources(
        prepared.sources,
        source_classes=request.source_classes,
        maximum_sources=request.maximum_sources,
    )
    anchor = sources.get(request.anchor.source.item_revision_id)
    if anchor is None or (
        anchor.source != request.anchor.source
        or anchor.profile != request.anchor.profile
        or anchor.solution_evidence != request.anchor.solution_evidence
    ):
        raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
    selected = {value.view for value in request.views}
    texts: dict[ExperimentView, str] = {}
    for view, text in prepared.query_texts:
        if view not in selected or view in texts or type(text) is not str or not text.strip():
            raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
        texts[view] = text
    if prepared.graph_evidence is not None:
        ArtifactMemberPointer.model_validate(raw_similarity_contract_value(prepared.graph_evidence))
    if sum(len(text.encode("utf-8")) for text in texts.values()) > 1024 * 1024 or (
        request.anchor.profile is None and texts
    ):
        raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
    graph = dict(prepared.graph_scores)
    if len(graph) != len(prepared.graph_scores) or any(
        revision not in sources or type(score) is not int or not 0 <= score <= 2147483647
        for revision, score in graph.items()
    ):
        raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
    return sources


def _validate_query(
    request: SimilarityContextRequest,
    prepared: PreparedSimilarityContext,
    query: VerifiedReferenceQueryRead,
) -> tuple[tuple[float, ...], ...]:
    if not isinstance(query, VerifiedReferenceQueryRead) or (
        type(query.binary) is not bytes
        or not isinstance(query.result_member, ArtifactMemberPointer)
        or not isinstance(query.shard_member, ArtifactMemberPointer)
    ):
        raise SimilarityContextReadError("QUERY_RESULT_INVALID")
    input_value = parse_supported_reference_query_input(query.request)
    result = parse_embedding_reference_query_result(query.result)
    ArtifactMemberPointer.model_validate(raw_similarity_contract_value(query.result_member))
    ArtifactMemberPointer.model_validate(raw_similarity_contract_value(query.shard_member))
    validate_supported_reference_query_result(input_value, result)
    texts = dict(prepared.query_texts)
    expected = {
        selection.view: texts[selection.view]
        for selection in request.views
        if selection.index is not None and selection.view in texts
    }
    selections = {selection.view: selection for selection in request.views}
    if input_value.context_request_sha256 != request.request_sha256 or (
        {row.view: row.text for row in input_value.rows} != expected
        or query.result_member.member_path != "result.json"
        or query.result_member.schema_ref != REFERENCE_QUERY_RESULT_REF
        or query.result_member.media_type != "application/json"
        or query.shard_member.member_path != "shard.json"
        or query.shard_member.schema_ref != SHARD_SCHEMA_REF
        or query.shard_member.media_type != "application/json"
        or (query.result_member.artifact_id, query.result_member.artifact_revision_id)
        != (query.shard_member.artifact_id, query.shard_member.artifact_revision_id)
        or query.result_member.sha256 != content_sha256(result.model_dump(mode="json"))
        or query.shard_member.sha256 != content_sha256(result.shard.model_dump(mode="json"))
    ):
        raise SimilarityContextReadError("QUERY_RESULT_INVALID")
    for row in input_value.rows:
        selection = selections[row.view]
        if selection.index is None or (
            input_value.spaces != selection.index.spaces
            or input_value.recipe != selection.recipe
            or row.encoding.storage_partition != selection.index.storage_partition
        ):
            raise SimilarityContextReadError("QUERY_RESULT_INVALID")
    return read_unit_vectors(
        query.binary,
        dimension=result.shard.dimension,
        row_count=result.shard.row_count,
        expected_sha256=result.shard.binary.sha256,
    )


def _context(
    request: SimilarityContextRequest,
    *,
    status: str,
    population: SimilarityPopulation | None,
    execution: ReferenceQueryExecutionPointer | None,
    prepared: PreparedSimilarityContext | None,
    candidates: tuple[SimilarityCandidate, ...],
    limitations: tuple[SimilarityLimitation, ...],
    error: SimilarityFailureCode | None = None,
) -> SimilarityContext:
    document = {
        "schema_version": "system-rag-similarity-context/1.0",
        "request": request.model_dump(mode="json"),
        "status": status,
        "population": None if population is None else population.model_dump(mode="json"),
        "query_execution": None if execution is None else execution.model_dump(mode="json"),
        "graph_evidence": None
        if prepared is None or prepared.graph_evidence is None
        else prepared.graph_evidence.model_dump(mode="json"),
        "candidates": [value.model_dump(mode="json") for value in candidates],
        "limitations": limitations,
        "error_code": error,
    }
    return parse_similarity_context(document | {"context_sha256": content_sha256(document)})


class SimilarityContextApplicationService:
    """One approved-reference use case; mandatory owners are never authority defaults."""

    def __init__(
        self,
        sources: SimilarityContextSourceReadPort | None,
        query_reads: SimilarityReferenceQueryReadPort | None = None,
    ) -> None:
        self.sources = sources
        self.query_reads = query_reads

    def compose(
        self, caller: EmbeddingRegistryCaller, request: SimilarityContextRequest
    ) -> SimilarityContext:
        request = parse_similarity_context_request(request)
        try:
            if (
                not isinstance(caller, EmbeddingRegistryCaller)
                or not re.fullmatch(r"operator_[0-9a-f]{32}", caller.operator_id)
                or self.sources is None
                or not all(
                    callable(getattr(self.sources, name, None))
                    for name in (
                        "prepare_similarity_context",
                        "read_similarity_views",
                        "reauthorize_similarity_context",
                    )
                )
                or request.consumer_purpose not in AUTHORING_REFERENCE_PURPOSES
                or request.anchor.source.source_class != "PAST_EXAM"
                or request.topics
                or request.unit_ids
            ):
                raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
            prepared = self.sources.prepare_similarity_context(caller, request)
            sources = validate_similarity_preparation(request, prepared)
            query: VerifiedReferenceQueryRead | None = None
            unavailable: SimilarityUnavailableReason = "QUERY_NOT_OFFERED"
            query_views = {view for view, _text in prepared.query_texts}
            usable = any(
                value.index is not None and value.view in query_views for value in request.views
            )
            if (
                self.query_reads is not None
                and usable
                and callable(getattr(self.query_reads, "resolve_reference_query", None))
            ):
                try:
                    outcome = self.query_reads.resolve_reference_query(caller, request, prepared)
                except SimilarityContextReadError:
                    raise
                except (JsonSchemaError, ValueError, TypeError, KeyError):
                    raise SimilarityContextReadError("QUERY_RESULT_INVALID") from None
                if isinstance(outcome, SimilarityQueryUnavailable):
                    if outcome.reason not in {"QUERY_NOT_OFFERED", "INPUT_OVERFLOW"}:
                        raise SimilarityContextReadError("QUERY_RESULT_INVALID")
                    unavailable = outcome.reason
                else:
                    query = outcome
            try:
                vectors = () if query is None else _validate_query(request, prepared, query)
            except (JsonSchemaError, ValueError, TypeError, KeyError):
                raise SimilarityContextReadError("QUERY_RESULT_INVALID") from None
            try:
                reads = (
                    {}
                    if query is None
                    else validate_similarity_document_reads(
                        request,
                        sources,
                        self.sources.read_similarity_views(caller, request, prepared),
                        {row.view for row in query.result.view_rows},
                    )
                )
            except SimilarityContextReadError:
                raise
            except (JsonSchemaError, ValueError, TypeError, KeyError):
                raise SimilarityContextReadError("INDEX_POINTER_INVALID") from None
            result = self._compose(request, prepared, sources, query, vectors, reads, unavailable)
            self.sources.reauthorize_similarity_context(caller, request, prepared)
            return result
        except SimilarityContextReadError as error:
            code = error.code
        except (JsonSchemaError, ValueError, TypeError, KeyError):
            code = "SOURCE_POINTER_INVALID"
        return _context(
            request,
            status="FAILED",
            population=None,
            execution=None,
            prepared=None,
            candidates=(),
            limitations=("REFERENCE_ANCHOR_NOT_PRIVATE_INTENT",),
            error=code,
        )

    @staticmethod
    def _compose(
        request: SimilarityContextRequest,
        prepared: PreparedSimilarityContext,
        sources: dict[str, PreparedSimilaritySource],
        query: VerifiedReferenceQueryRead | None,
        vectors: tuple[tuple[float, ...], ...],
        reads: dict[ExperimentView, ResolvedPinnedEmbeddingIndex],
        unavailable: SimilarityUnavailableReason,
    ) -> SimilarityContext:
        profiles = {value.profile: value for value in sources.values() if value.profile is not None}
        observations: dict[InferenceTransferProfilePointer, list[SimilarityObservation]] = {}
        channels: list[tuple[InferenceTransferProfilePointer, ...]] = []
        coverage: list[SimilarityViewCoverage] = []
        query_rows = {} if query is None else {row.view: row for row in query.result.view_rows}
        query_views = {view for view, _text in prepared.query_texts}
        for selection in request.views:
            reason: SimilarityUnavailableReason | None = None
            if request.anchor.profile is None:
                reason = "ANCHOR_REPORT_MISSING"
            elif selection.index is None:
                reason = "INDEX_NOT_PREPARED"
            elif selection.view not in query_views:
                reason = "VIEW_INPUT_MISSING"
            elif query is None:
                reason = unavailable
            if reason is not None:
                coverage.append(
                    SimilarityViewCoverage(
                        view=selection.view,
                        status="UNAVAILABLE",
                        available_binding_count=None,
                        binding_set_sha256=None,
                        scored_count=0,
                        missing_view_count=None,
                        reason=reason,
                    )
                )
                continue
            document = reads.get(selection.view)
            query_row = query_rows.get(selection.view)
            if document is None or query_row is None or query is None:
                raise SimilarityContextReadError("INDEX_POINTER_INVALID")
            rows = {value.row.encoding.encoding_sha256: value for value in document.numerical_rows}
            eligible = tuple(
                (binding.profile, rows[binding.encoding.encoding_sha256].values)
                for binding in document.bindings
                if binding.source.item_revision_id != request.anchor.source.item_revision_id
            )
            ranked = rank_normalized_vectors(
                vectors[query_row.row_index], eligible, top_k=request.top_k
            )
            by_profile = {binding.profile: binding for binding in document.bindings}
            for rank, value in enumerate(ranked, 1):
                observations.setdefault(value.profile, []).append(
                    SimilarityVectorObservation(
                        view=selection.view,
                        rank=rank,
                        cosine_millionths=round(value.cosine_similarity * 1_000_000),
                        query_row=EmbeddingVectorRowRef(
                            shard_manifest=query.shard_member,
                            row_index=query_row.row_index,
                            encoding_sha256=query_row.encoding_sha256,
                        ),
                        document_row=by_profile[value.profile].row_ref,
                    )
                )
            channels.append(tuple(value.profile for value in ranked))
            count = len(document.bindings)
            missing = len(profiles) - count
            coverage.append(
                SimilarityViewCoverage(
                    view=selection.view,
                    status="EMPTY" if not count else ("PARTIAL" if missing else "READY"),
                    available_binding_count=count,
                    binding_set_sha256=content_sha256(
                        sorted(binding.binding_sha256 for binding in document.bindings)
                    ),
                    scored_count=len(eligible),
                    missing_view_count=missing,
                    reason=None,
                )
            )
        graph_values = tuple(
            (sources[revision].profile, score)
            for revision, score in sorted(
                prepared.graph_scores, key=lambda value: (-value[1], value[0])
            )
            if sources[revision].profile is not None
            and revision != request.anchor.source.item_revision_id
        )[: request.top_k]
        graph_channel = []
        for rank, (pointer, score) in enumerate(graph_values, 1):
            assert pointer is not None
            observations.setdefault(pointer, []).append(
                SimilarityGraphObservation(rank=rank, graph_relevance_milli=score)
            )
            graph_channel.append(pointer)
        channels.append(tuple(graph_channel))
        ordered = bounded_profile_channel_union(tuple(channels), top_k=request.top_k)
        unavailable_view = any(value.status == "UNAVAILABLE" for value in coverage)
        if request.vector_mode == "REQUIRED" and unavailable_view:
            ordered = ()
        candidate_values = []
        for pointer in ordered:
            candidate_source = profiles[pointer]
            assert candidate_source.solution_evidence is not None
            candidate_values.append(
                SimilarityCandidate(
                    source=candidate_source.source,
                    profile=pointer,
                    solution_evidence=candidate_source.solution_evidence,
                    observations=tuple(observations[pointer]),
                    explanation=None,
                )
            )
        candidates = tuple(candidate_values)
        missing_reports = len(sources) - len(profiles)
        limitations: list[SimilarityLimitation] = ["REFERENCE_ANCHOR_NOT_PRIVATE_INTENT"]
        if unavailable_view:
            limitations.append("VECTOR_NOT_AVAILABLE")
        if missing_reports:
            limitations.append("PARTIAL_REPORT_COVERAGE")
        if any(value.missing_view_count for value in coverage):
            limitations.append("PARTIAL_VIEW_COVERAGE")
        if prepared.truncated:
            limitations.append("BOUNDED_SCOPE_TRUNCATED")
        if not candidates:
            limitations.append("NO_RELATED_CANDIDATES")
        partial = len(limitations) > 1
        status = (
            "UNAVAILABLE"
            if unavailable_view and not candidates
            else ("EMPTY" if not candidates else ("PARTIAL" if partial else "READY"))
        )
        execution = None
        if query is not None and any(value.scored_count for value in coverage):
            execution = ReferenceQueryExecutionPointer(
                job_id=query.request.job_id,
                query_request_id=query.request.query_request_id,
                request_sha256=query.request.request_sha256,
                input_set_sha256=query.request.input_set_sha256,
                result_member=query.result_member,
                result_sha256=query.result.result_sha256,
            )
        population = SimilarityPopulation(
            authorized_source_count=len(sources),
            authorized_source_set_sha256=content_sha256(
                [sources[key].source.model_dump(mode="json") for key in sorted(sources)]
            ),
            accepted_profile_count=len(profiles),
            accepted_profile_set_sha256=content_sha256(
                [
                    pointer.model_dump(mode="json")
                    for pointer in sorted(
                        profiles,
                        key=lambda value: (
                            value.profile_id,
                            value.profile_revision_id,
                            value.profile_sha256,
                        ),
                    )
                ]
            ),
            missing_report_count=missing_reports,
            truncated=prepared.truncated,
            views=tuple(coverage),
        )
        context = _context(
            request,
            status=status,
            population=population,
            execution=execution,
            prepared=prepared,
            candidates=candidates,
            limitations=tuple(limitations),
        )
        if query is not None and execution is not None:
            validate_similarity_query_execution(
                context, query.request, query.result, query.result_member, query.shard_member
            )
        return context
