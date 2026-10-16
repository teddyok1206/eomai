"""Current Catalog source owner selects only an original official Evidence reference."""

from __future__ import annotations

from typing import TYPE_CHECKING

from eom_catalog_contracts import ApprovedItemKnowledgeSourceV2, EvidenceBundleManifestV5
from eom_catalog_contracts.authoring_reference import (
    AuthoringReferenceRequest,
    AuthoringReferenceSelection,
)
from eom_orchestrator.database import build_session_factory

from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryLookup,
    ResolvedEmbeddingLookup,
    SelectedEmbeddingSources,
)
from eom_catalog_service.knowledge_retrieval_service import KnowledgeRetrievalApplicationService
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError

if TYPE_CHECKING:
    from eom_workflow_runner.reference_query_source_read import ReferenceQuerySourceOwner


def authoring_reference_ids(manifest: EvidenceBundleManifestV5) -> tuple[str, ...]:
    """First original eligible reference only; never materialize unused Item bytes."""
    for entry in manifest.entries:
        if (
            isinstance(entry.source, ApprovedItemKnowledgeSourceV2)
            and entry.source.source_class == "PAST_EXAM"
            and entry.evidence_kind == "ITEM_REVISION"
            and entry.use == "REFERENCE_PATTERN"
            and not entry.answer_bearing
            and entry.solution_evidence is not None
        ):
            return (entry.source.item_revision_id,)
    return ()


def select_authoring_reference(
    manifest: EvidenceBundleManifestV5, resolved: ResolvedEmbeddingLookup
) -> AuthoringReferenceSelection | None:
    """Exact source/report join, preserving the official Evidence relevance order."""
    expected = authoring_reference_ids(manifest)
    sources = {source.item_revision_id: source for source in resolved.sources}
    entries = {
        entry.profile.source_basis.source.item_revision_id: entry for entry in resolved.entries
    }
    if (
        resolved.truncated
        or len(sources) != len(resolved.sources)
        or len(entries) != len(resolved.entries)
        or set(sources) != set(expected)
        or not set(entries).issubset(sources)
    ):
        raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
    selected: AuthoringReferenceSelection | None = None
    expected_set = set(expected)
    for entry in manifest.entries:
        source = entry.source
        if (
            not isinstance(source, ApprovedItemKnowledgeSourceV2)
            or source.item_revision_id not in expected_set
            or entry.use != "REFERENCE_PATTERN"
            or entry.evidence_kind != "ITEM_REVISION"
            or entry.answer_bearing
            or entry.solution_evidence is None
        ):
            continue
        current = sources[source.item_revision_id]
        projected = entries.get(source.item_revision_id)
        if current != source or projected is None:
            raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
        basis = projected.profile.source_basis
        if (
            basis.source.item_id != source.item_id
            or basis.source.item_revision_id != source.item_revision_id
            or basis.source.source_class != source.source_class
            or basis.source.artifact_member != source.artifact_member
            or basis.graph_snapshot != manifest.graph_snapshot
            or basis.solution_evidence != entry.solution_evidence
        ):
            raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
        if selected is None:
            selected = AuthoringReferenceSelection(
                evidence_id=entry.evidence_id,
                source_item_revision_id=source.item_revision_id,
                source_sha256=source.artifact_member.sha256,
                solution_pointer_sha256=entry.solution_evidence.pointer_sha256,
            )
    return selected


class CatalogAuthoringReferenceSelection:
    """Read-only same-root composition; no native launch, publication or durable cache."""

    def __init__(self, owner: ReferenceQuerySourceOwner) -> None:
        self.owner = owner
        self.sessions = build_session_factory(owner.catalog.engine)
        self.retrieval = KnowledgeRetrievalApplicationService(owner.catalog.engine, owner.settings)

    def select(self, request: AuthoringReferenceRequest) -> AuthoringReferenceSelection | None:
        request = AuthoringReferenceRequest.model_validate(request)
        caller = EmbeddingRegistryCaller(request.actor_id)
        publication = request.evidence
        config = self.owner.configuration.registry
        scope = EmbeddingRegistryLookup(
            config.corpus_id,
            config.namespace,
            publication.graph_snapshot,
            publication.access_policy_revision_id,
            publication.access_policy_sha256,
            1024,
        )
        with self.sessions.begin() as session:
            self.owner.identity.fence_current_operator(session, caller.operator_id)
            self.owner.catalog.authorize_scope(session, caller, scope)
            manifest = self.retrieval.read_published_item_evidence_in_session(
                session,
                publication,
                requested_by=caller.operator_id,
                artifact_reader=PinnedArtifactReadContext(session, self.owner.settings),
            )
            ids = authoring_reference_ids(manifest)
            result = None
            if ids:
                resolved = self.owner.catalog.resolve_selected_sources(
                    session, caller, SelectedEmbeddingSources(scope, ids)
                )
                result = select_authoring_reference(manifest, resolved)
            # Empty eligible references still require current authority after IO.
            self.owner.catalog.authorize_scope(session, caller, scope)
            return result
