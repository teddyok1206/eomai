"""Official Catalog source/index reads for public reports; no model, queue or authority cache."""

from dataclasses import dataclass

from eom_catalog_contracts.embedding_reference_query import ReferenceQuerySpaces
from eom_catalog_contracts.public_solution_embedding import PublicSolutionEmbeddingEntry
from eom_catalog_contracts.public_solution_embedding_index import PublicSolutionIndexNamespace
from eom_catalog_contracts.public_solution_reference import PublicSolutionSourceReference
from eom_catalog_contracts.public_solution_similarity import (
    PublicSolutionSimilarityContext,
    PublicSolutionSimilarityIndexPin,
    PublicSolutionSimilarityPurpose,
    PublicSolutionSimilarityRequest,
    PublicSolutionSimilarityView,
)
from eom_identifiers import content_sha256
from sqlalchemy.orm import Session

from eom_catalog_service.embedding_registry_application import (
    read_pinned_embedding_index,
    validate_registered_embedding_index_read,
)
from eom_catalog_service.embedding_registry_catalog_adapter import CatalogEmbeddingRegistryVerifier
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryLookup,
    EmbeddingRegistryRead,
    ResolvedEmbeddingLookup,
    ResolvedPinnedEmbeddingIndex,
    SelectedEmbeddingSources,
)
from eom_catalog_service.embedding_registry_repository import EmbeddingRegistryRepository
from eom_catalog_service.public_solution_similarity_service import (
    PreparedPublicSolutionQuerySource,
    VerifiedPublicSolutionQueryRead,
    compose_public_solution_similarity,
    prepare_public_solution_query_source,
)
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError


@dataclass(frozen=True, slots=True)
class PublicSolutionSimilarityPreparation:
    """Initial pinned intent from an authenticated use case, not a replay or read grant."""

    request_id: str
    selection: SelectedEmbeddingSources
    spaces: ReferenceQuerySpaces
    consumer_purpose: PublicSolutionSimilarityPurpose
    top_k: int


class CatalogPublicSolutionSimilarityRead:
    """Reuse the actual operator-fenced Catalog Registry owner for all source/member IO.

    Preparing a request only selects its immutable index. Numerical QUERY execution
    remains Orchestrator-owned. Each completed read recaptures/re-authorizes these
    exact sources/index/recipe instead of trusting a prior request or latest head.
    """

    def __init__(self, catalog: CatalogEmbeddingRegistryVerifier) -> None:
        if type(catalog) is not CatalogEmbeddingRegistryVerifier or not isinstance(
            catalog.configuration.namespace, PublicSolutionIndexNamespace
        ):
            raise ValueError("PUBLIC_SIMILARITY_CATALOG_OWNER_REQUIRED")
        self.catalog = catalog

    def _require_root(self, session: Session) -> None:
        root = session.get_transaction()
        if (
            root is None
            or not root.is_active
            or session.in_nested_transaction()
            or session.get_bind() is not self.catalog.engine
        ):
            raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")

    def prepare_in_session(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        preparation: PublicSolutionSimilarityPreparation,
    ) -> PublicSolutionSimilarityRequest:
        self._require_root(session)
        if (
            type(caller) is not EmbeddingRegistryCaller
            or type(preparation) is not PublicSolutionSimilarityPreparation
        ):
            raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
        preparation.selection.__post_init__()
        scope = preparation.selection.scope
        config = self.catalog.configuration
        if (
            len(preparation.selection.source_revision_ids) != 1
            or scope.corpus_id != config.corpus_id
            or scope.namespace != config.namespace
            or preparation.spaces.document != config.space
        ):
            raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
        captured = self.catalog.resolve_selected_sources(session, caller, preparation.selection)
        if len(captured.entries) != 1 or not isinstance(
            captured.entries[0], PublicSolutionEmbeddingEntry
        ):
            raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
        entry = captured.entries[0]
        if entry.public_solution.status != "AVAILABLE":
            raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
        current = EmbeddingRegistryRepository(session).current_namespace_revision(
            scope.corpus_id, scope.namespace
        )
        if current is None:
            raise SimilarityContextReadError("INDEX_POINTER_INVALID")
        registered, _version = current
        selected = PublicSolutionSimilarityView(
            recipe=entry.recipe,
            index=PublicSolutionSimilarityIndexPin(
                index_id=registered.index_id,
                index_revision_id=registered.index_revision_id,
                index_manifest=registered.index_manifest,
                index_sha256=registered.index_sha256,
                storage_partition=scope.namespace.storage_partition,
                spaces=preparation.spaces,
            ),
        )
        intent = EmbeddingRegistryRead(scope, selected)
        validate_registered_embedding_index_read(intent, registered)
        # This also validates canonical package bytes and current report/binding
        # identity under the actual operator before any request is submitted.
        read_pinned_embedding_index(session, caller, intent, self.catalog)
        body = dict(
            schema_version="system-rag-similarity-request/3.0",
            request_id=preparation.request_id,
            consumer_purpose=preparation.consumer_purpose,
            anchor=PublicSolutionSourceReference.from_entry(entry).model_dump(mode="json"),
            graph_snapshot=scope.graph_snapshot.model_dump(mode="json"),
            policy_revision_id=scope.policy_revision_id,
            policy_sha256=scope.policy_sha256,
            source_classes=config.source_classes,
            views=[selected.model_dump(mode="json")],
            maximum_sources=scope.maximum_sources,
            top_k=preparation.top_k,
        )
        result = PublicSolutionSimilarityRequest.model_validate(
            body | {"request_sha256": content_sha256(body)}
        )
        if (
            self.catalog.resolve_selected_sources(session, caller, preparation.selection)
            != captured
        ):
            raise SimilarityContextReadError("SOURCE_REVOKED")
        return result

    def read_in_session(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        request: PublicSolutionSimilarityRequest,
        query: VerifiedPublicSolutionQueryRead,
    ) -> PublicSolutionSimilarityContext:
        captured, document = self._read_pinned_request(session, caller, request)
        result = compose_public_solution_similarity(request, captured, document, query)
        self._reauthorize_pinned_read(session, caller, document, captured)
        return result

    def prepare_query_in_session(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        request: PublicSolutionSimilarityRequest,
    ) -> PreparedPublicSolutionQuerySource:
        """Materialize the original pinned QUERY text; never discover another head."""
        captured, document = self._read_pinned_request(session, caller, request)
        result = prepare_public_solution_query_source(request, captured)
        self._reauthorize_pinned_read(session, caller, document, captured)
        return result

    def _read_pinned_request(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        request: PublicSolutionSimilarityRequest,
    ) -> tuple[ResolvedEmbeddingLookup, ResolvedPinnedEmbeddingIndex]:
        self._require_root(session)
        request = PublicSolutionSimilarityRequest.model_validate(request)
        config = self.catalog.configuration
        view = request.views[0]
        if (
            type(caller) is not EmbeddingRegistryCaller
            or request.source_classes != config.source_classes
            or view.recipe != config.recipe
            or view.index.spaces.document != config.space
            or view.index.storage_partition != config.namespace.storage_partition
        ):
            raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
        scope = EmbeddingRegistryLookup(
            config.corpus_id,
            config.namespace,
            request.graph_snapshot,
            request.policy_revision_id,
            request.policy_sha256,
            request.maximum_sources,
        )
        captured = self.catalog.resolve_lookup(session, caller, scope)
        document = read_pinned_embedding_index(
            session, caller, EmbeddingRegistryRead(scope, view), self.catalog
        )
        return captured, document

    def _reauthorize_pinned_read(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        document: ResolvedPinnedEmbeddingIndex,
        captured: ResolvedEmbeddingLookup,
    ) -> None:
        # Keep source locks and recheck after local text/ranking materialization.
        # Never select the current index head for continuation or completed reads.
        if self.catalog.resolve_lookup(session, caller, document.intent.scope) != captured:
            raise SimilarityContextReadError("SOURCE_REVOKED")
