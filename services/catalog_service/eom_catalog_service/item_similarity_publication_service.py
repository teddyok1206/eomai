"""Current Catalog source owner → existing Orchestrator context publisher."""

from __future__ import annotations

from eom_catalog_contracts.item_similarity_publication import (
    ItemSimilarityPublication,
    ItemSimilarityPublicationRequest,
)
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_workflow_runner.item_similarity_preparation import CatalogItemSimilarityPreparation
from eom_workflow_runner.reference_query_consumer_read import (
    CatalogCompletedReferenceQueryRead,
    select_completed_reference_query_request,
)
from eom_workflow_runner.reference_query_source_read import ReferenceQuerySourceOwner

from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryCaller


class CatalogItemSimilarityPublicationService:
    """Pointer-only publication for the authenticated API, not QUERY or item submission."""

    def __init__(
        self,
        owner: ReferenceQuerySourceOwner,
        publisher: ControlFileSetPublisher,
        *,
        source_commit: str,
    ) -> None:
        self.owner = owner
        self.publisher = publisher
        self.source_commit = source_commit
        self.sessions = build_session_factory(owner.catalog.engine)

    def publish(self, request: ItemSimilarityPublicationRequest) -> ItemSimilarityPublication:
        request = ItemSimilarityPublicationRequest.model_validate(request)
        caller = EmbeddingRegistryCaller(request.actor_id)
        with self.sessions.begin() as session:
            original = select_completed_reference_query_request(
                session, self.owner, caller, request.selection
            )
        query = CatalogCompletedReferenceQueryRead(
            self.owner, workflow_id=request.selection.workflow_id, request=original
        )
        # The shared owner rechecks current operator/source/history/member state in
        # its actual root before publication and after the independent Artifact commit.
        _plan, published = CatalogItemSimilarityPreparation(
            query, self.publisher, source_commit=self.source_commit
        ).publish_context(caller)
        return ItemSimilarityPublication(
            owner_job_id=published.owner_job_id,
            delivery=published.delivery,
            manifest_sha256=published.manifest_sha256,
        )
