"""Persist one validated DB ranking; every hit still fences current Catalog authority."""

from __future__ import annotations

from hashlib import sha256

from eom_catalog_contracts.completed_public_ranking import (
    MAX_SAVED_PUBLIC_RANKING_BYTES,
    CompletedPublicSimilarityRanking,
)
from eom_catalog_contracts.registered_public_solution_similarity import (
    SupportedPublicSolutionSimilarityContext,
)
from eom_catalog_contracts.similarity_read import CompletedSimilarityQuerySelection
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_orchestrator.completed_public_ranking_artifact import (
    SAVED_PUBLIC_RANKING_ARTIFACT_TYPE,
    SAVED_PUBLIC_RANKING_SCHEMA_REF,
    CompletedPublicRankingArtifactStore,
)
from eom_orchestrator.file_set_control_artifacts import CONTROL_FILE_SET_PROTOCOL
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.reference_query_execution import PublicReferenceQueryWorkflowRequest
from eom_workflow_runner.reference_query_consumer_read import (
    read_completed_public_solution_similarity_in_session,
    select_completed_reference_query_request,
)
from eom_workflow_runner.reference_query_source_read import (
    ReferenceQuerySourceOwner,
    select_completed_reference_query_read_owner,
)
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from eom_catalog_service.completed_public_ranking_dependencies import (
    observe_completed_public_ranking_dependencies,
)
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryLookup,
)
from eom_catalog_service.inference_transfer_catalog_adapter import (
    InferenceTransferCorpusReadCommand,
)
from eom_catalog_service.inference_transfer_read_timing import (
    InferenceTransferReadStage,
    observe_read_stage,
)
from eom_catalog_service.inference_transfer_scope import InferenceTransferPopulationScope
from eom_catalog_service.knowledge_retrieval_service import ReadOnlyCandidatePoolScope
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError


def _scope(
    session: Session,
    owner: ReferenceQuerySourceOwner,
    caller: EmbeddingRegistryCaller,
    request: PublicReferenceQueryWorkflowRequest,
) -> ReadOnlyCandidatePoolScope:
    context, config = request.context_request, owner.configuration.registry
    owner.catalog.authorize_scope(
        session,
        caller,
        EmbeddingRegistryLookup(
            config.corpus_id,
            config.namespace,
            context.graph_snapshot,
            context.policy_revision_id,
            context.policy_sha256,
            context.maximum_sources,
        ),
    )
    return owner.catalog.sources.authorize_scope_in_session(
        session,
        InferenceTransferCorpusReadCommand(
            actor_id=caller.operator_id,
            graph_snapshot=context.graph_snapshot,
            access_policy_revision_id=context.policy_revision_id,
            access_policy_sha256=context.policy_sha256,
            source_classes=context.source_classes,
            maximum_candidates=min(1024, context.maximum_sources),
            top_k=context.top_k,
            population_scope=InferenceTransferPopulationScope(config.namespace.population_scope),
        ),
        identity_fence=owner.identity,
        artifact_reader=PinnedArtifactReadContext.for_session(session, owner.settings),
    )


def _lock_result(session: Session, workflow_id: str) -> None:
    # One original QUERY only. An exception/crash releases the transaction lock;
    # no placeholder state, new work queue or process-local authority cache exists.
    key = int.from_bytes(
        sha256(("saved-public-ranking:" + workflow_id).encode()).digest()[:8], "big", signed=True
    )
    session.execute(select(func.pg_advisory_xact_lock(key)))


@observe_read_stage(InferenceTransferReadStage.SAVED_RANKING_READ)
def read_saved_public_ranking_in_session(
    session: Session,
    owner: ReferenceQuerySourceOwner,
    caller: EmbeddingRegistryCaller,
    selection: CompletedSimilarityQuerySelection,
    *,
    store: CompletedPublicRankingArtifactStore,
) -> SupportedPublicSolutionSimilarityContext:
    original = select_completed_reference_query_request(session, owner, caller, selection)
    if not isinstance(original, PublicReferenceQueryWorkflowRequest):
        raise SimilarityContextReadError("QUERY_RESULT_INVALID")
    if original.context_request.consumer_purpose != "ITEM_DATABASE_SEARCH":
        return read_completed_public_solution_similarity_in_session(
            session, owner, caller, selection
        )
    owner = select_completed_reference_query_read_owner(owner, original)
    scope = _scope(session, owner, caller, original)
    key = "completed-public-ranking:" + content_sha256(
        dict(
            operator_id=caller.operator_id,
            selection=selection.model_dump(mode="json"),
        )
    ).removeprefix("sha256:")
    pointer = store.find(key)
    if pointer is None:
        # Only publication needs serialization. An immutable saved ranking may
        # be read concurrently, with the same current authority/dependency fences.
        _lock_result(session, selection.workflow_id)
        pointer = store.find(key)
    before = observe_completed_public_ranking_dependencies(
        session, scope, original, selection.workflow_id
    )
    reader = PinnedArtifactReadContext.for_session(session, owner.settings)

    def read_snapshot(member: ArtifactMemberPointer) -> CompletedPublicSimilarityRanking:
        if (
            member.schema_ref != SAVED_PUBLIC_RANKING_SCHEMA_REF
            or member.member_path != "ranking.json"
        ):
            raise SimilarityContextReadError("QUERY_RESULT_INVALID")
        reader.prefetch(((member.artifact_id, member.artifact_revision_id),))
        reader.require_file_set(
            member.artifact_id,
            member.artifact_revision_id,
            ("ranking.json",),
            manifest_version=CONTROL_FILE_SET_PROTOCOL,
        )
        value = reader.read_pinned(
            **member.model_dump(mode="python"),
            expected_artifact_types=(SAVED_PUBLIC_RANKING_ARTIFACT_TYPE,),
            expected_primary_file="ranking.json",
            max_bytes=MAX_SAVED_PUBLIC_RANKING_BYTES,
        )
        try:
            snapshot = CompletedPublicSimilarityRanking.model_validate_json(value.payload)
        except (ValueError, SchemaError):
            raise SimilarityContextReadError("QUERY_RESULT_INVALID") from None
        if canonical_json_bytes(snapshot.model_dump(mode="json")) != value.payload:
            raise SimilarityContextReadError("QUERY_RESULT_INVALID")
        return snapshot

    if pointer is None:
        context = read_completed_public_solution_similarity_in_session(
            session, owner, caller, selection
        )
        cached = None
    else:
        cached = read_snapshot(pointer)
        if (
            cached.operator_id != caller.operator_id
            or cached.selection != selection
            or cached.context.request != original.context_request
        ):
            raise SimilarityContextReadError("QUERY_RESULT_INVALID")
        if cached.dependency_sha256 != before:
            raise SimilarityContextReadError("SOURCE_REVOKED")
        context = cached.context
    late = select_completed_reference_query_request(session, owner, caller, selection)
    final_scope = _scope(session, owner, caller, original)
    after = observe_completed_public_ranking_dependencies(
        session, final_scope, original, selection.workflow_id
    )
    if late != original or final_scope != scope or before != after:
        raise SimilarityContextReadError("SOURCE_REVOKED")
    if cached is None:
        body = dict(
            schema_version="completed-public-similarity-ranking/1.0",
            operator_id=caller.operator_id,
            selection=selection.model_dump(mode="json"),
            context=context.model_dump(mode="json"),
            dependency_sha256=after,
        )
        cached = CompletedPublicSimilarityRanking.model_validate(
            body | {"snapshot_sha256": content_sha256(body)}
        )
        committed = read_snapshot(store.commit(cached, key))
        if committed != cached:
            raise SimilarityContextReadError("QUERY_RESULT_INVALID")
        if (
            _scope(session, owner, caller, original) != scope
            or observe_completed_public_ranking_dependencies(
                session, scope, original, selection.workflow_id
            )
            != before
        ):
            raise SimilarityContextReadError("SOURCE_REVOKED")
    reader.revalidate_provenance()
    return context
