"""Bind the pure common application to a caller-owned root, including completed QUERY IO."""

from __future__ import annotations

from dataclasses import dataclass

from eom_catalog_contracts.similarity_context import SimilarityContext, SimilarityContextRequest
from eom_catalog_service.embedding_registry_catalog_adapter import CatalogEmbeddingRegistryVerifier
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    ResolvedPinnedEmbeddingIndex,
)
from eom_catalog_service.inference_transfer_population_read_set import (
    InferenceTransferPopulationReadSet,
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
    population_read_set: InferenceTransferPopulationReadSet | None = None

    def prepare_similarity_context(
        self, caller: EmbeddingRegistryCaller, request: SimilarityContextRequest
    ) -> PreparedSimilarityContext:
        if self.artifact_reader is None:
            return self.catalog.prepare_similarity_context_in_session(self.session, caller, request)
        if self.population_read_set is None:
            return self.catalog.prepare_similarity_context_in_session(
                self.session, caller, request, artifact_reader=self.artifact_reader
            )
        return self.catalog.prepare_similarity_context_in_session(
            self.session,
            caller,
            request,
            artifact_reader=self.artifact_reader,
            population_read_set=self.population_read_set,
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
        if self.population_read_set is None:
            return self.catalog.read_similarity_views_in_session(
                self.session, caller, request, prepared, artifact_reader=self.artifact_reader
            )
        return self.catalog.read_similarity_views_in_session(
            self.session,
            caller,
            request,
            prepared,
            artifact_reader=self.artifact_reader,
            population_read_set=self.population_read_set,
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
        catalog = self.query.owner.catalog
        population_read_set = (
            None
            if self.query.artifact_reader is None
            else catalog.create_similarity_population_read_set_in_session(
                session, caller, request, artifact_reader=self.query.artifact_reader
            )
        )
        return SimilarityContextApplicationService(
            _SessionSources(session, catalog, self.query.artifact_reader, population_read_set),
            _SessionQuery(session, self.query),
        ).compose(caller, request)
