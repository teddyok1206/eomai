"""Catalog resolves exact DB pointers and an explicit indexed search scope; no execution."""

from eom_catalog_contracts.item_db_similarity_selection import (
    ItemDbExternalSelection,
    ItemDbGraphSelection,
    ItemDbSimilarityItemPin,
    ItemDbSimilarityPreparedSelection,
    ItemDbSimilaritySelectionErrorCode,
    ItemDbSimilaritySelectionRequest,
)
from eom_catalog_contracts.public_solution_embedding import PublicSolutionEmbeddingEntry
from eom_catalog_contracts.public_solution_embedding_index import PublicSolutionIndexNamespace
from eom_catalog_contracts.reference_query_prepare import ReferenceQueryPrepareRequestV4
from eom_identifiers import content_sha256
from eom_identity_service import OperatorAuthorizationFenceError
from eom_orchestrator.database import build_session_factory
from eom_workflow_runner.reference_query_source_read import CatalogReferenceQueryReadOwner
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_catalog_service.creative_item_registration import creative_registration_key
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryError,
    EmbeddingRegistryLookup,
    SelectedEmbeddingSources,
)
from eom_catalog_service.embedding_registry_repository import EmbeddingRegistryRepository
from eom_catalog_service.external_item_models import (
    ExternalItemSourceRecord,
    ExternalItemSourceRevisionRecord,
)
from eom_catalog_service.knowledge_graph_models import (
    KnowledgeGraphSnapshotRecord,
    KnowledgeNodeRecord,
    KnowledgeNodeSourcePointerRecord,
)
from eom_catalog_service.knowledge_retrieval_service import (
    KnowledgeRetrievalApplicationService,
    KnowledgeRetrievalServiceError,
)
from eom_catalog_service.models import ItemRecord, ItemRevisionRecord
from eom_catalog_service.similarity_context_ports import similarity_context_error_from_registry


class ItemDbSimilaritySelectionError(ValueError):
    def __init__(self, code: ItemDbSimilaritySelectionErrorCode) -> None:
        self.code = code
        super().__init__(code)


class CatalogItemDbSimilaritySelection:
    """Initial head selection is explicit; replay authorizes the original scope, never latest."""

    def __init__(self, owner: CatalogReferenceQueryReadOwner) -> None:
        if not isinstance(owner.configuration.registry.namespace, PublicSolutionIndexNamespace):
            raise ValueError("ITEM_DB_PUBLIC_SOURCE_OWNER_REQUIRED")
        self.owner = owner
        self.sessions = build_session_factory(owner.catalog.engine)
        self.retrieval = KnowledgeRetrievalApplicationService(owner.catalog.engine, owner.settings)

    def resolve(
        self, request: ItemDbSimilaritySelectionRequest
    ) -> ItemDbSimilarityPreparedSelection:
        request = ItemDbSimilaritySelectionRequest.model_validate(request)
        caller = EmbeddingRegistryCaller(request.actor_id)
        try:
            with self.sessions.begin() as session:
                # Official source capture retains shared lifecycle/completion
                # locks. PostgreSQL READ ONLY forbids even those SELECT locks;
                # this existing read use case issues no DML in its normal root.
                self.owner.identity.fence_current_operator(session, request.actor_id)
                scope, snapshot_hash = self._scope(session, request)
                self.owner.catalog.authorize_scope(session, caller, scope)
                revision = self._selected_revision(session, request, caller, scope)
                captured = self.owner.catalog.resolve_selected_sources(
                    session,
                    caller,
                    SelectedEmbeddingSources(scope, (revision.item_revision_id,)),
                )
                if len(captured.entries) != 1:
                    raise ItemDbSimilaritySelectionError("ITEM_DB_SIMILARITY_NOT_INDEXED")
                entry = captured.entries[0]
                if not isinstance(entry, PublicSolutionEmbeddingEntry) or (
                    entry.source.item_revision_id != revision.item_revision_id
                    or entry.source.item_id != revision.item_id
                    or entry.public_solution.status != "AVAILABLE"
                ):
                    raise ItemDbSimilaritySelectionError("ITEM_DB_SIMILARITY_NOT_INDEXED")
                query = request.pinned_query
                if query is None:
                    value = dict(
                        schema_version="system-rag-reference-query-prepare-request/4.0",
                        operation="PREPARE_REFERENCE_QUERY",
                        operation_id=request.operation_id,
                        idempotency_key=request.idempotency_key,
                        source_item_revision_ids=[revision.item_revision_id],
                        graph_snapshot=scope.graph_snapshot.model_dump(mode="json"),
                        policy_revision_id=scope.policy_revision_id,
                        policy_sha256=scope.policy_sha256,
                        consumer_purpose="ITEM_DATABASE_SEARCH",
                        top_k=request.top_k,
                    )
                    query = ReferenceQueryPrepareRequestV4.model_validate(
                        value | {"request_sha256": content_sha256(value)}
                    )
                elif query.source_item_revision_ids != (revision.item_revision_id,):
                    raise ItemDbSimilaritySelectionError("ITEM_DB_SIMILARITY_REQUEST_CONFLICT")
                result = ItemDbSimilarityPreparedSelection(
                    selection_sha256=content_sha256(request.selection),
                    anchor=ItemDbSimilarityItemPin(
                        item_id=revision.item_id,
                        item_revision_id=revision.item_revision_id,
                        item_manifest_sha256=revision.manifest_sha256,
                    ),
                    query=query,
                    search_snapshot_sha256=snapshot_hash,
                )
                self.owner.identity.fence_current_operator(session, request.actor_id)
                return result
        except OperatorAuthorizationFenceError:
            raise ItemDbSimilaritySelectionError("AUTHORITY_UNAVAILABLE") from None
        except EmbeddingRegistryError as error:
            raise ItemDbSimilaritySelectionError(
                similarity_context_error_from_registry(error).code,
            ) from None
        except KnowledgeRetrievalServiceError:
            raise ItemDbSimilaritySelectionError("SOURCE_POINTER_INVALID") from None

    def _scope(
        self,
        session: Session,
        request: ItemDbSimilaritySelectionRequest,
    ) -> tuple[EmbeddingRegistryLookup, str]:
        config = self.owner.configuration.registry
        query = request.pinned_query
        if query is None:
            repository = EmbeddingRegistryRepository(session)
            current = repository.current_namespace_revision(config.corpus_id, config.namespace)
            cuda_owner = self.owner.cuda_owner
            if current is None or cuda_owner is None:
                raise ItemDbSimilaritySelectionError("ITEM_DB_SIMILARITY_NOT_INDEXED")
            cuda = repository.current_namespace_revision(
                config.corpus_id,
                cuda_owner.configuration.registry.namespace,
            )
            registered = current[0]
            if cuda is None or (
                cuda[0].graph_snapshot_revision_id != registered.graph_snapshot_revision_id
                or cuda[0].policy_revision_id != registered.policy_revision_id
                or cuda[0].policy_sha256 != registered.policy_sha256
            ):
                raise ItemDbSimilaritySelectionError("ITEM_DB_SIMILARITY_NOT_INDEXED")
            snapshot_id = registered.graph_snapshot_revision_id
            policy_id, policy_hash = registered.policy_revision_id, registered.policy_sha256
        else:
            snapshot_id = query.graph_snapshot.graph_snapshot_revision_id
            policy_id, policy_hash = query.policy_revision_id, query.policy_sha256
        graph = self.retrieval.resolve_snapshot_pointer(session, snapshot_id)
        if query is not None and graph != query.graph_snapshot:
            raise ItemDbSimilaritySelectionError("SOURCE_HASH_MISMATCH")
        snapshot = session.get(KnowledgeGraphSnapshotRecord, snapshot_id)
        if snapshot is None or snapshot.state != "PUBLISHED":
            raise ItemDbSimilaritySelectionError("SOURCE_POINTER_INVALID")
        return EmbeddingRegistryLookup(
            config.corpus_id,
            config.namespace,
            graph,
            policy_id,
            policy_hash,
            16384,
        ), snapshot.snapshot_sha256

    def _selected_revision(
        self,
        session: Session,
        request: ItemDbSimilaritySelectionRequest,
        caller: EmbeddingRegistryCaller,
        scope: EmbeddingRegistryLookup,
    ) -> ItemRevisionRecord:
        selected = request.selection
        if isinstance(selected, ItemDbExternalSelection):
            source = session.get(ExternalItemSourceRecord, selected.source_id)
            observation = session.get(ExternalItemSourceRevisionRecord, selected.source_revision_id)
            if (
                source is None
                or observation is None
                or source.current_revision_id != selected.source_revision_id
                or observation.source_id != source.source_id
                or observation.observation_sha256 != selected.observation_sha256
            ):
                raise ItemDbSimilaritySelectionError("SOURCE_POINTER_INVALID")
            revision = session.scalar(
                select(ItemRevisionRecord).where(
                    ItemRevisionRecord.registration_key
                    == creative_registration_key(source.source_id),
                )
            )
            if revision is None:
                raise ItemDbSimilaritySelectionError("ITEM_DB_SIMILARITY_NOT_REGISTERED")
            if (
                revision.metadata_json.get("source_id") != selected.source_id
                or revision.metadata_json.get("source_revision_id") != selected.source_revision_id
            ):
                raise ItemDbSimilaritySelectionError("SOURCE_POINTER_INVALID")
        else:
            revision = session.get(ItemRevisionRecord, selected.item_revision_id)
            if (
                revision is None
                or revision.item_id != selected.item_id
                or revision.manifest_sha256 != selected.item_manifest_sha256
            ):
                raise ItemDbSimilaritySelectionError("SOURCE_POINTER_INVALID")
            self._require_selected_graph(session, selected, revision, caller, scope)
        item = session.get(ItemRecord, revision.item_id)
        if (
            item is None
            or item.lifecycle_state != "ACTIVE"
            or revision.revision_state not in {"APPROVED", "SUPERSEDED"}
        ):
            raise ItemDbSimilaritySelectionError("SOURCE_REVOKED")
        return revision

    def _require_selected_graph(
        self,
        session: Session,
        selected: ItemDbGraphSelection,
        revision: ItemRevisionRecord,
        caller: EmbeddingRegistryCaller,
        scope: EmbeddingRegistryLookup,
    ) -> None:
        snapshot_id = selected.graph_snapshot_revision_id
        graph = self.retrieval.resolve_snapshot_pointer(session, snapshot_id)
        snapshot = session.get(KnowledgeGraphSnapshotRecord, snapshot_id)
        if snapshot is None or snapshot.snapshot_sha256 != selected.graph_snapshot_sha256:
            raise ItemDbSimilaritySelectionError("SOURCE_HASH_MISMATCH")
        self.owner.catalog.authorize_scope(
            session,
            caller,
            EmbeddingRegistryLookup(
                scope.corpus_id,
                scope.namespace,
                graph,
                scope.policy_revision_id,
                scope.policy_sha256,
                scope.maximum_sources,
            ),
        )
        exists = session.scalar(
            select(KnowledgeNodeSourcePointerRecord.pointer_id)
            .join(
                KnowledgeNodeRecord,
                (
                    KnowledgeNodeRecord.graph_snapshot_revision_id
                    == KnowledgeNodeSourcePointerRecord.graph_snapshot_revision_id
                )
                & (KnowledgeNodeRecord.node_id == KnowledgeNodeSourcePointerRecord.node_id),
            )
            .where(
                KnowledgeNodeSourcePointerRecord.graph_snapshot_revision_id == snapshot_id,
                KnowledgeNodeSourcePointerRecord.source_revision_id == revision.item_revision_id,
                KnowledgeNodeSourcePointerRecord.source_class.in_(
                    self.owner.configuration.registry.source_classes
                ),
                KnowledgeNodeRecord.node_type == "ITEM_REVISION",
                KnowledgeNodeRecord.stable_key == "item-revision:" + revision.item_revision_id,
            )
            .limit(1)
        )
        if exists is None:
            raise ItemDbSimilaritySelectionError("SOURCE_POINTER_INVALID")
