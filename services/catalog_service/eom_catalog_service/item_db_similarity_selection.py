"""Catalog resolves exact DB pointers and an explicit indexed search scope; no execution."""

from eom_catalog_contracts.creative_source_lineage import creative_registration_key
from eom_catalog_contracts.item_db_similarity_selection import (
    ItemDbExternalSelection,
    ItemDbGraphSelection,
    ItemDbSimilarityItemPin,
    ItemDbSimilarityPreparedSelection,
    ItemDbSimilaritySelection,
    ItemDbSimilaritySelectionErrorCode,
    ItemDbSimilaritySelectionRequest,
)
from eom_catalog_contracts.item_db_similarity_selection_v2 import (
    ItemDbSimilarityPreparedSelectionV2,
    ItemDbSimilaritySelectionRequestV2,
)
from eom_catalog_contracts.public_solution_embedding import PublicSolutionEmbeddingEntry
from eom_catalog_contracts.public_solution_embedding_index import PublicSolutionIndexNamespace
from eom_catalog_contracts.reference_query_prepare import ReferenceQueryPrepareRequestV4
from eom_catalog_contracts.registered_public_solution_embedding import (
    RegisteredPublicSolutionEmbeddingEntry,
)
from eom_identifiers import content_sha256
from eom_identity_service import OperatorAuthorizationFenceError
from eom_orchestrator.database import build_session_factory
from eom_workflow_runner.reference_query_source_read import CatalogReferenceQueryReadOwner
from sqlalchemy import Select, literal, or_, select, tuple_
from sqlalchemy.orm import Session

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
        result = self._resolve(request)
        return ItemDbSimilarityPreparedSelection(
            selection_sha256=content_sha256(request.selection),
            anchor=result.anchors[0],
            query=result.query,
            search_snapshot_sha256=result.search_snapshot_sha256,
        )

    def resolve_many(
        self, request: ItemDbSimilaritySelectionRequestV2
    ) -> ItemDbSimilarityPreparedSelectionV2:
        return self._resolve(ItemDbSimilaritySelectionRequestV2.model_validate(request))

    def _resolve(
        self, request: ItemDbSimilaritySelectionRequest | ItemDbSimilaritySelectionRequestV2
    ) -> ItemDbSimilarityPreparedSelectionV2:
        caller = EmbeddingRegistryCaller(request.actor_id)
        try:
            with self.sessions.begin() as session:
                # Official source capture retains shared lifecycle/completion
                # locks. PostgreSQL READ ONLY forbids even those SELECT locks;
                # this existing read use case issues no DML in its normal root.
                self.owner.identity.fence_current_operator(session, request.actor_id)
                scope, snapshot_hash = self._scope(session, request)
                self.owner.catalog.authorize_scope(session, caller, scope)
                revisions = (
                    (self._selected_revision(session, request, caller, scope),)
                    if isinstance(request, ItemDbSimilaritySelectionRequest)
                    else self._selected_pointers(session, request.selections, caller, scope)
                )
                revision_ids = tuple(revision.item_revision_id for revision in revisions)
                if len(set(revision_ids)) != len(revision_ids):
                    # External and Graph selections can resolve to the same canonical Item.
                    raise ItemDbSimilaritySelectionError("ITEM_DB_SIMILARITY_REQUEST_CONFLICT")
                captured = self.owner.catalog.resolve_selected_sources(
                    session,
                    caller,
                    SelectedEmbeddingSources(scope, revision_ids),
                )
                if len(captured.entries) != len(revisions):
                    raise ItemDbSimilaritySelectionError("ITEM_DB_SIMILARITY_NOT_INDEXED")
                entries: dict[
                    str, PublicSolutionEmbeddingEntry | RegisteredPublicSolutionEmbeddingEntry
                ] = {}
                for entry in captured.entries:
                    if not isinstance(
                        entry, PublicSolutionEmbeddingEntry | RegisteredPublicSolutionEmbeddingEntry
                    ):
                        raise ItemDbSimilaritySelectionError("ITEM_DB_SIMILARITY_NOT_INDEXED")
                    entries[entry.source.item_revision_id] = entry
                if len(entries) != len(revisions):
                    raise ItemDbSimilaritySelectionError("ITEM_DB_SIMILARITY_NOT_INDEXED")
                for revision in revisions:
                    selected_entry = entries.get(revision.item_revision_id)
                    if not isinstance(
                        selected_entry,
                        PublicSolutionEmbeddingEntry | RegisteredPublicSolutionEmbeddingEntry,
                    ) or (
                        selected_entry.source.item_id != revision.item_id
                        or selected_entry.public_solution.status != "AVAILABLE"
                    ):
                        raise ItemDbSimilaritySelectionError("ITEM_DB_SIMILARITY_NOT_INDEXED")
                query = request.pinned_query
                if query is None:
                    value = dict(
                        schema_version="system-rag-reference-query-prepare-request/4.0",
                        operation="PREPARE_REFERENCE_QUERY",
                        operation_id=request.operation_id,
                        idempotency_key=request.idempotency_key,
                        source_item_revision_ids=list(revision_ids),
                        graph_snapshot=scope.graph_snapshot.model_dump(mode="json"),
                        policy_revision_id=scope.policy_revision_id,
                        policy_sha256=scope.policy_sha256,
                        consumer_purpose="ITEM_DATABASE_SEARCH",
                        top_k=request.top_k,
                    )
                    query = ReferenceQueryPrepareRequestV4.model_validate(
                        value | {"request_sha256": content_sha256(value)}
                    )
                elif query.source_item_revision_ids != revision_ids:
                    raise ItemDbSimilaritySelectionError("ITEM_DB_SIMILARITY_REQUEST_CONFLICT")
                selections = (
                    (request.selection,)
                    if isinstance(request, ItemDbSimilaritySelectionRequest)
                    else request.selections
                )
                result = ItemDbSimilarityPreparedSelectionV2(
                    selection_sha256=content_sha256(selections),
                    anchors=tuple(
                        ItemDbSimilarityItemPin(
                            item_id=revision.item_id,
                            item_revision_id=revision.item_revision_id,
                            item_manifest_sha256=revision.manifest_sha256,
                        )
                        for revision in revisions
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
        request: ItemDbSimilaritySelectionRequest | ItemDbSimilaritySelectionRequestV2,
    ) -> tuple[EmbeddingRegistryLookup, str]:
        config = self.owner.configuration.registry
        query = request.pinned_query
        if query is None:
            repository = EmbeddingRegistryRepository(session)
            cuda_owner = self.owner.cuda_owner
            if cuda_owner is None:
                raise ItemDbSimilaritySelectionError("ITEM_DB_SIMILARITY_NOT_INDEXED")
            cuda = repository.current_namespace_revision(
                config.corpus_id,
                cuda_owner.configuration.registry.namespace,
            )
            if cuda is None:
                raise ItemDbSimilaritySelectionError("ITEM_DB_SIMILARITY_NOT_INDEXED")
            # Choose one complete published GPU scope, not a composite of two
            # independently advancing heads. The QUERY owner still validates
            # its exact device/index and any permitted CPU fallback separately.
            registered = cuda[0]
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
        return self._selected_pointer(session, request.selection, caller, scope)

    def _selected_pointer(
        self,
        session: Session,
        selected: ItemDbSimilaritySelection,
        caller: EmbeddingRegistryCaller,
        scope: EmbeddingRegistryLookup,
    ) -> ItemRevisionRecord:
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

    def _selected_pointers(
        self,
        session: Session,
        selections: tuple[ItemDbSimilaritySelection, ...],
        caller: EmbeddingRegistryCaller,
        scope: EmbeddingRegistryLookup,
    ) -> tuple[ItemRevisionRecord, ...]:
        """Batch metadata once; only distinct Graph scopes need separate authority reads."""
        external = tuple(
            value for value in selections if isinstance(value, ItemDbExternalSelection)
        )
        graph = tuple(value for value in selections if isinstance(value, ItemDbGraphSelection))
        external_rows = (
            {
                (source.source_id, observation.revision_id): (source, observation)
                for source, observation in session.execute(
                    select(
                        ExternalItemSourceRecord,
                        ExternalItemSourceRevisionRecord,
                    )
                    .join(
                        ExternalItemSourceRevisionRecord,
                        ExternalItemSourceRevisionRecord.source_id
                        == ExternalItemSourceRecord.source_id,
                    )
                    .where(
                        tuple_(
                            ExternalItemSourceRecord.source_id,
                            ExternalItemSourceRevisionRecord.revision_id,
                        ).in_(
                            tuple((value.source_id, value.source_revision_id) for value in external)
                        )
                    )
                )
            }
            if external
            else {}
        )
        keys = tuple(creative_registration_key(value.source_id) for value in external)
        registration_keys = set(keys)
        revisions = tuple(
            session.scalars(
                select(ItemRevisionRecord).where(
                    or_(
                        ItemRevisionRecord.item_revision_id.in_(
                            tuple(value.item_revision_id for value in graph)
                        ),
                        ItemRevisionRecord.registration_key.in_(keys),
                    )
                )
            )
        )
        by_revision = {value.item_revision_id: value for value in revisions}
        by_registration = {
            value.registration_key: value
            for value in revisions
            if value.registration_key in registration_keys
        }
        items = {
            value.item_id: value
            for value in session.scalars(
                select(ItemRecord).where(
                    ItemRecord.item_id.in_(tuple({value.item_id for value in revisions})),
                )
            )
        }
        ordered = []
        graph_scopes: dict[str, str] = {}
        for selected in selections:
            if isinstance(selected, ItemDbExternalSelection):
                pair = external_rows.get((selected.source_id, selected.source_revision_id))
                if pair is None:
                    raise ItemDbSimilaritySelectionError("SOURCE_POINTER_INVALID")
                source, observation = pair
                if (
                    source.current_revision_id != selected.source_revision_id
                    or observation.observation_sha256 != selected.observation_sha256
                ):
                    raise ItemDbSimilaritySelectionError("SOURCE_POINTER_INVALID")
                revision = by_registration.get(creative_registration_key(selected.source_id))
                if revision is None:
                    raise ItemDbSimilaritySelectionError("ITEM_DB_SIMILARITY_NOT_REGISTERED")
                if (
                    revision.metadata_json.get("source_id") != selected.source_id
                    or revision.metadata_json.get("source_revision_id")
                    != selected.source_revision_id
                ):
                    raise ItemDbSimilaritySelectionError("SOURCE_POINTER_INVALID")
            else:
                revision = by_revision.get(selected.item_revision_id)
                if (
                    revision is None
                    or revision.item_id != selected.item_id
                    or revision.manifest_sha256 != selected.item_manifest_sha256
                ):
                    raise ItemDbSimilaritySelectionError("SOURCE_POINTER_INVALID")
                previous_hash = graph_scopes.get(selected.graph_snapshot_revision_id)
                if previous_hash is None:
                    self._require_selected_graph(session, selected, revision, caller, scope)
                    graph_scopes[selected.graph_snapshot_revision_id] = (
                        selected.graph_snapshot_sha256
                    )
                elif previous_hash != selected.graph_snapshot_sha256:
                    raise ItemDbSimilaritySelectionError("SOURCE_HASH_MISMATCH")
            item = items.get(revision.item_id)
            if (
                item is None
                or item.lifecycle_state != "ACTIVE"
                or revision.revision_state not in {"APPROVED", "SUPERSEDED"}
            ):
                raise ItemDbSimilaritySelectionError("SOURCE_REVOKED")
            ordered.append(revision)
        if graph:
            wanted = {(value.graph_snapshot_revision_id, value.item_revision_id) for value in graph}
            found = set(
                session.execute(
                    self._graph_memberships().where(
                        tuple_(
                            KnowledgeNodeSourcePointerRecord.graph_snapshot_revision_id,
                            KnowledgeNodeSourcePointerRecord.source_revision_id,
                        ).in_(tuple(wanted))
                    )
                ).all()
            )
            if found != wanted:
                raise ItemDbSimilaritySelectionError("SOURCE_POINTER_INVALID")
        return tuple(ordered)

    def _graph_memberships(self) -> Select[tuple[str, str]]:
        return (
            select(
                KnowledgeNodeSourcePointerRecord.graph_snapshot_revision_id,
                KnowledgeNodeSourcePointerRecord.source_revision_id,
            )
            .join(
                KnowledgeNodeRecord,
                (
                    KnowledgeNodeRecord.graph_snapshot_revision_id
                    == KnowledgeNodeSourcePointerRecord.graph_snapshot_revision_id
                )
                & (KnowledgeNodeRecord.node_id == KnowledgeNodeSourcePointerRecord.node_id),
            )
            .where(
                KnowledgeNodeSourcePointerRecord.source_class.in_(
                    self.owner.configuration.registry.source_classes
                ),
                KnowledgeNodeRecord.node_type == "ITEM_REVISION",
                KnowledgeNodeRecord.stable_key
                == literal("item-revision:") + KnowledgeNodeSourcePointerRecord.source_revision_id,
            )
        )

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
        exists = session.execute(
            self._graph_memberships()
            .where(
                KnowledgeNodeSourcePointerRecord.graph_snapshot_revision_id == snapshot_id,
                KnowledgeNodeSourcePointerRecord.source_revision_id == revision.item_revision_id,
            )
            .limit(1)
        ).first()
        if exists is None:
            raise ItemDbSimilaritySelectionError("SOURCE_POINTER_INVALID")
