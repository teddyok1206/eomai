"""Official Catalog source/index reads for public reports; no model, queue or authority cache."""

from dataclasses import dataclass
from typing import overload

from eom_catalog_contracts.embedding_reference_query import ReferenceQuerySpaces
from eom_catalog_contracts.public_solution_embedding import PublicSolutionEmbeddingEntry
from eom_catalog_contracts.public_solution_embedding_index import PublicSolutionIndexNamespace
from eom_catalog_contracts.public_solution_similarity import (
    PublicSolutionSimilarityContext,
    PublicSolutionSimilarityIndexPin,
    PublicSolutionSimilarityPurpose,
    PublicSolutionSimilarityRequest,
    PublicSolutionSimilarityView,
)
from eom_catalog_contracts.registered_public_solution_embedding import (
    RegisteredPublicSolutionEmbeddingEntry,
)
from eom_catalog_contracts.registered_public_solution_index import (
    REGISTERED_PUBLIC_SOLUTION_INDEX_SCHEMA_REF,
)
from eom_catalog_contracts.registered_public_solution_similarity import (
    PublicSolutionSimilarityContextV4,
    PublicSolutionSimilarityIndexPinV4,
    PublicSolutionSimilarityRequestV4,
    PublicSolutionSimilarityViewV4,
    SupportedPublicSolutionSimilarityContext,
    SupportedPublicSolutionSimilarityRequest,
    parse_supported_public_solution_similarity_request,
    public_solution_reference_for_entry,
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
    ) -> SupportedPublicSolutionSimilarityRequest:
        return self.prepare_many_in_session(session, caller, (preparation,))[0]

    def prepare_many_in_session(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        preparations: tuple[PublicSolutionSimilarityPreparation, ...],
    ) -> tuple[SupportedPublicSolutionSimilarityRequest, ...]:
        """One current source capture and index read per device, not N full-index reads.

        Only the ordered source/request identities differ. These returned pins
        are never a cached permission or a numerical execution grant.
        """
        self._require_root(session)
        if (
            type(caller) is not EmbeddingRegistryCaller
            or type(preparations) is not tuple
            or not 1 <= len(preparations) <= 32
            or any(type(value) is not PublicSolutionSimilarityPreparation for value in preparations)
        ):
            raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
        preparation = preparations[0]
        for value in preparations:
            value.selection.__post_init__()
        scope = preparation.selection.scope
        config = self.catalog.configuration
        if (
            any(
                len(value.selection.source_revision_ids) != 1
                or value.selection.scope != scope
                or value.spaces != preparation.spaces
                or value.consumer_purpose != preparation.consumer_purpose
                or value.top_k != preparation.top_k
                for value in preparations
            )
            or scope.corpus_id != config.corpus_id
            or scope.namespace != config.namespace
            or preparation.spaces.document != config.space
        ):
            raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
        ids = tuple(value.selection.source_revision_ids[0] for value in preparations)
        if len(set(ids)) != len(ids) or len({value.request_id for value in preparations}) != len(
            ids
        ):
            raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
        selection = SelectedEmbeddingSources(scope, tuple(sorted(ids)))
        captured = self.catalog.resolve_selected_sources(session, caller, selection)
        entries = {
            entry.source.item_revision_id: entry
            for entry in captured.entries
            if isinstance(
                entry, PublicSolutionEmbeddingEntry | RegisteredPublicSolutionEmbeddingEntry
            )
        }
        if (
            len(entries) != len(captured.entries)
            or len(entries) != len(ids)
            or set(entries) != set(ids)
        ):
            raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
        entry = entries[ids[0]]
        if any(
            value.public_solution.status != "AVAILABLE" or value.recipe != entry.recipe
            for value in entries.values()
        ):
            raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
        current = EmbeddingRegistryRepository(session).current_namespace_revision(
            scope.corpus_id, scope.namespace
        )
        if current is None:
            raise SimilarityContextReadError("INDEX_POINTER_INVALID")
        registered, _version = current
        registered_source = (
            registered.index_manifest.schema_ref == REGISTERED_PUBLIC_SOLUTION_INDEX_SCHEMA_REF
            or any(
                isinstance(value, RegisteredPublicSolutionEmbeddingEntry)
                for value in entries.values()
            )
        )
        view_type = (
            PublicSolutionSimilarityViewV4 if registered_source else PublicSolutionSimilarityView
        )
        pin_type = (
            PublicSolutionSimilarityIndexPinV4
            if registered_source
            else PublicSolutionSimilarityIndexPin
        )
        pin = pin_type(
            index_id=registered.index_id,
            index_revision_id=registered.index_revision_id,
            index_manifest=registered.index_manifest,
            index_sha256=registered.index_sha256,
            storage_partition=scope.namespace.storage_partition,
            spaces=preparation.spaces,
        )
        selected = view_type.model_validate(
            {"recipe": entry.recipe.model_dump(mode="json"), "index": pin.model_dump(mode="json")}
        )
        intent = EmbeddingRegistryRead(scope, selected)
        validate_registered_embedding_index_read(intent, registered)
        # This also validates canonical package bytes and current report/binding
        # identity under the actual operator before any request is submitted.
        read_pinned_embedding_index(session, caller, intent, self.catalog)
        body = dict(
            schema_version="system-rag-similarity-request/4.0"
            if registered_source
            else "system-rag-similarity-request/3.0",
            consumer_purpose=preparation.consumer_purpose,
            graph_snapshot=scope.graph_snapshot.model_dump(mode="json"),
            policy_revision_id=scope.policy_revision_id,
            policy_sha256=scope.policy_sha256,
            source_classes=config.source_classes,
            views=[selected.model_dump(mode="json")],
            maximum_sources=scope.maximum_sources,
            top_k=preparation.top_k,
        )
        result = []
        for prepared_value, source_id in zip(preparations, ids, strict=True):
            child = body | {
                "request_id": prepared_value.request_id,
                "anchor": public_solution_reference_for_entry(entries[source_id]).model_dump(
                    mode="json"
                ),
            }
            result.append(
                parse_supported_public_solution_similarity_request(
                    child | {"request_sha256": content_sha256(child)}
                )
            )
        if self.catalog.resolve_selected_sources(session, caller, selection) != captured:
            raise SimilarityContextReadError("SOURCE_REVOKED")
        return tuple(result)

    @overload
    def read_in_session(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        request: PublicSolutionSimilarityRequest,
        query: VerifiedPublicSolutionQueryRead,
    ) -> PublicSolutionSimilarityContext: ...

    @overload
    def read_in_session(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        request: PublicSolutionSimilarityRequestV4,
        query: VerifiedPublicSolutionQueryRead,
    ) -> PublicSolutionSimilarityContextV4: ...

    @overload
    def read_in_session(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        request: SupportedPublicSolutionSimilarityRequest,
        query: VerifiedPublicSolutionQueryRead,
    ) -> SupportedPublicSolutionSimilarityContext: ...

    def read_in_session(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        request: SupportedPublicSolutionSimilarityRequest,
        query: VerifiedPublicSolutionQueryRead,
    ) -> SupportedPublicSolutionSimilarityContext:
        captured, document = self._read_pinned_request(session, caller, request)
        result = compose_public_solution_similarity(request, captured, document, query)
        self._reauthorize_pinned_read(session, caller, document, captured)
        return result

    def prepare_query_in_session(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        request: SupportedPublicSolutionSimilarityRequest,
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
        request: SupportedPublicSolutionSimilarityRequest,
    ) -> tuple[ResolvedEmbeddingLookup, ResolvedPinnedEmbeddingIndex]:
        self._require_root(session)
        request = parse_supported_public_solution_similarity_request(request)
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
