"""Bind the pure common application to a caller-owned root, including completed QUERY IO."""

from __future__ import annotations

from dataclasses import dataclass

from eom_catalog_contracts.similarity_context import SimilarityContext, SimilarityContextRequest
from eom_catalog_service.embedding_registry_catalog_adapter import CatalogEmbeddingRegistryVerifier
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    ResolvedPinnedEmbeddingIndex,
)
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.similarity_context_ports import (
    PreparedSimilarityContext,
    SimilarityContextReadError,
    VerifiedReferenceQueryRead,
)
from eom_catalog_service.similarity_context_service import SimilarityContextApplicationService
from sqlalchemy.orm import Session

from eom_workflow_runner.reference_query_consumer_read import CatalogCompletedReferenceQueryRead


@dataclass(frozen=True, slots=True)
class _SessionSources:
    session: Session
    catalog: CatalogEmbeddingRegistryVerifier
    artifact_reader: PinnedArtifactReadContext | None

    def prepare_similarity_context(
        self, caller: EmbeddingRegistryCaller, request: SimilarityContextRequest
    ) -> PreparedSimilarityContext:
        if self.artifact_reader is None:
            return self.catalog.prepare_similarity_context_in_session(self.session, caller, request)
        return self.catalog.prepare_similarity_context_in_session(
            self.session, caller, request, artifact_reader=self.artifact_reader
        )

    def read_similarity_views(
        self,
        caller: EmbeddingRegistryCaller,
        request: SimilarityContextRequest,
        prepared: PreparedSimilarityContext,
    ) -> tuple[ResolvedPinnedEmbeddingIndex, ...]:
        if self.artifact_reader is None:
            return self.catalog.read_similarity_views_in_session(
                self.session, caller, request, prepared
            )
        return self.catalog.read_similarity_views_in_session(
            self.session, caller, request, prepared, artifact_reader=self.artifact_reader
        )

    def reauthorize_similarity_context(
        self,
        caller: EmbeddingRegistryCaller,
        request: SimilarityContextRequest,
        prepared: PreparedSimilarityContext,
    ) -> None:
        if self.prepare_similarity_context(caller, request) != prepared:
            raise SimilarityContextReadError("SOURCE_REVOKED")


@dataclass(frozen=True, slots=True)
class _SessionQuery:
    session: Session
    query: CatalogCompletedReferenceQueryRead

    def resolve_reference_query(
        self,
        caller: EmbeddingRegistryCaller,
        request: SimilarityContextRequest,
        prepared: PreparedSimilarityContext,
    ) -> VerifiedReferenceQueryRead:
        return self.query.resolve_reference_query_in_session(
            self.session, caller, request, prepared
        )


class CatalogSimilaritySessionContextReader:
    """Fresh bounded adapters per read, not an authority cache or a new execution owner."""

    def __init__(self, query: CatalogCompletedReferenceQueryRead) -> None:
        self.query = query

    def compose_in_session(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        request: SimilarityContextRequest,
    ) -> SimilarityContext:
        root = session.get_transaction()
        if root is None or not root.is_active or session.in_nested_transaction():
            raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
        return SimilarityContextApplicationService(
            _SessionSources(session, self.query.owner.catalog, self.query.artifact_reader),
            _SessionQuery(session, self.query),
        ).compose(caller, request)
