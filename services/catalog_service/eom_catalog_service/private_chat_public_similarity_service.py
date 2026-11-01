"""Pure owned-question ranking over the same official public document proofs as DB search.

No launch, DB/NAS access, source enrollment or permissions are supplied here.
The existing private owner must establish and recheck current turn/source access.
"""

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.inference_transfer_embedding import EmbeddingVectorRowRef
from eom_catalog_contracts.inference_transfer_experiment import population_sha256
from eom_catalog_contracts.private_chat_query_basis import private_chat_query_text_sha256
from eom_catalog_contracts.private_chat_similarity import PRIVATE_CHAT_LIMITATION_ORDER
from eom_catalog_contracts.private_chat_similarity_v2 import (
    PrivateChatPublicQueryExecutionPointer,
    PrivateChatSimilarityContextV2,
    PrivateChatSimilarityRequestV2,
    validate_private_chat_public_query_execution,
)
from eom_catalog_contracts.registered_public_solution_similarity import (
    PublicSolutionSimilarityViewV4,
)
from eom_identifiers import content_sha256
from jsonschema.exceptions import ValidationError as SchemaError

from eom_catalog_service.embedding_registry_ports import (
    ResolvedEmbeddingLookup,
    ResolvedPinnedEmbeddingIndex,
)
from eom_catalog_service.public_solution_document_scope import (
    PublicSolutionDocumentScope,
    validate_public_solution_document,
    validated_public_solution_entries,
)
from eom_catalog_service.public_solution_similarity_service import (
    VerifiedPublicSolutionQueryRead,
    read_verified_public_solution_query_vector,
)
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_catalog_service.similarity_vector_ranking import rank_similarity_profiles


def compose_private_chat_public_similarity(
    request: PrivateChatSimilarityRequestV2,
    capture: ResolvedEmbeddingLookup,
    document: ResolvedPinnedEmbeddingIndex,
    query: VerifiedPublicSolutionQueryRead | None,
    *,
    question_text: str,
) -> PrivateChatSimilarityContextV2:
    """Use common row/proof/ranking rules, but do not subtract an invented self Item.

    Source revisions and encoding hashes are keyed maps; shared document rows
    remain shared. Complexity is O(text bytes + N*D + N log N), bounded by the
    existing 16,384-source scope. An empty authorized scope needs no fake query.
    """
    request = PrivateChatSimilarityRequestV2.model_validate(raw_similarity_contract_value(request))
    if private_chat_query_text_sha256(question_text) != request.query_basis.query_text_sha256:
        raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
    if request.views[0].index is None:
        raise SimilarityContextReadError("INDEX_POINTER_INVALID")
    view = PublicSolutionSimilarityViewV4.model_validate(request.views[0].model_dump(mode="json"))
    scope = PublicSolutionDocumentScope(
        view,
        request.graph_snapshot,
        request.policy_revision_id,
        request.policy_sha256,
        request.source_classes,
        request.maximum_sources,
    )
    entries = validated_public_solution_entries(scope, capture)
    validated = validate_public_solution_document(scope, capture, entries, document)
    references, profiles = validated.references, validated.profiles
    bindings, rows = validated.bindings, validated.rows
    execution = None
    candidates = []
    if bindings:
        if query is None:
            raise SimilarityContextReadError("QUERY_RESULT_INVALID")
        try:
            vector, common_execution = read_verified_public_solution_query_vector(query)
        except (ValueError, TypeError, AttributeError, SchemaError):
            raise SimilarityContextReadError("QUERY_RESULT_INVALID") from None
        if query.request.rows[0].text != question_text:
            raise SimilarityContextReadError("QUERY_RESULT_INVALID")
        execution = PrivateChatPublicQueryExecutionPointer(
            **common_execution.model_dump(mode="python"),
            basis_sha256=request.query_basis.basis_sha256,
        )
        ranked = rank_similarity_profiles(
            vector,
            tuple(
                (binding.profile, rows[binding.encoding.encoding_sha256].values)
                for binding in bindings.values()
            ),
            top_k=request.top_k,
        )
        by_profile = {binding.profile: binding for binding in bindings.values()}
        for rank, (profile, score) in enumerate(ranked, 1):
            binding = by_profile[profile]
            candidates.append(
                references[binding.source.item_revision_id].model_dump(mode="json")
                | dict(
                    observation=dict(
                        channel="VECTOR",
                        view="CONCRETE_FACETS",
                        rank=rank,
                        cosine_millionths=round(score * 1_000_000),
                        score_semantics="ROUNDED_DISPLAY_ONLY_NOT_RANKING_OR_PROBABILITY",
                        query_row=EmbeddingVectorRowRef(
                            shard_manifest=query.shard_member,
                            row_index=0,
                            encoding_sha256=query.request.rows[0].encoding.encoding_sha256,
                        ).model_dump(mode="json"),
                        document_row=binding.row_ref.model_dump(mode="json"),
                    )
                )
            )
    elif query is not None:
        raise SimilarityContextReadError("QUERY_RESULT_INVALID")
    flags: set[str] = set(PRIVATE_CHAT_LIMITATION_ORDER[:3])
    for condition, flag in (
        (len(entries) < len(capture.sources), "PARTIAL_REPORT_COVERAGE"),
        (len(bindings) < len(entries), "PARTIAL_VIEW_COVERAGE"),
        (capture.truncated, "BOUNDED_SCOPE_TRUNCATED"),
        (not candidates, "NO_RELATED_CANDIDATES"),
    ):
        if condition:
            flags.add(flag)
    body = dict(
        schema_version="system-rag-private-chat-similarity-context/2.0",
        request=request.model_dump(mode="json"),
        status="EMPTY" if not candidates else "PARTIAL" if len(flags) > 3 else "READY",
        population=dict(
            authorized_source_count=len(capture.sources),
            authorized_source_set_sha256=population_sha256(capture.sources),
            available_report_count=len(entries),
            available_report_set_sha256=content_sha256(
                [profiles[key].model_dump(mode="json") for key in sorted(profiles)]
            ),
            available_binding_count=len(bindings),
            binding_set_sha256=content_sha256(
                [bindings[key].binding_sha256 for key in sorted(bindings)]
            ),
            scored_count=len(bindings),
            truncated=capture.truncated,
        ),
        query_execution=None if execution is None else execution.model_dump(mode="json"),
        candidates=candidates,
        limitations=[flag for flag in PRIVATE_CHAT_LIMITATION_ORDER if flag in flags],
        unavailable_reason=None,
        error_code=None,
    )
    context = PrivateChatSimilarityContextV2.model_validate(
        body | dict(context_sha256=content_sha256(body))
    )
    if query is not None:
        validate_private_chat_public_query_execution(
            context, query.request, query.result, query.result_member, query.shard_member
        )
    return context
