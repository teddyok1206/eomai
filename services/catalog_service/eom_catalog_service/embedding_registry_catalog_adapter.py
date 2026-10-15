"""Catalog Registry composition over the same canonical source/member validators."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from eom_catalog_contracts.embedding_registry import (
    EmbeddingIndexNamespace,
    RegisterEmbeddingIndexCommand,
)
from eom_catalog_contracts.embedding_vector_binary import read_unit_vectors
from eom_catalog_contracts.inference_transfer_embedding import (
    INDEX_SCHEMA_REF,
    MAX_EMBEDDING_INPUT_BYTES,
    RESULT_SCHEMA_REF,
    SHARD_SCHEMA_REF,
    EmbeddingEncodingIdentity,
    EmbeddingIndexManifest,
    EmbeddingSourceBinding,
    EmbeddingSpace,
    EmbeddingVectorRowRef,
    EmbeddingVectorShardManifest,
    parse_embedding_index,
    parse_embedding_shard,
    parse_incremental_embedding_result,
    validate_embedding_source_bindings,
)
from eom_catalog_contracts.inference_transfer_experiment import (
    ExperimentViewRecipe,
    experiment_view_text,
)
from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfilePointer
from eom_catalog_contracts.similarity_context import (
    SimilarityContext,
    SimilarityContextRequest,
    SimilarityIndexPin,
    SimilarityViewSelection,
    parse_similarity_context,
    parse_similarity_context_request,
    validate_similarity_index_pin,
)
from eom_catalog_contracts.similarity_delivery import validate_deliverable_similarity_context
from eom_catalog_contracts.similarity_materials import (
    MAX_SIMILARITY_MATERIAL_CANDIDATES,
    SimilarityReferenceMaterials,
    build_similarity_materials,
)
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_identity_service import OperatorAuthorizationFenceError
from eom_identity_service.operator_authorization_fence import OperatorAuthorizationFence
from eom_operator_identity.errors import IdentityError
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.embedding_artifact_store import (
    EMBEDDING_INDEX_ARTIFACT_TYPE,
    EMBEDDING_INDEX_MANIFEST_VERSION,
    EMBEDDING_INDEX_MEMBER_NAMES,
    EMBEDDING_INDEX_PRIMARY_MEMBER,
)
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.local_embedding_source_plan import validate_local_embedding_entry_source
from jsonschema.exceptions import ValidationError as JsonSchemaError
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from eom_catalog_service.embedding_incremental_plan import (
    RegisteredEmbeddingRow,
    plan_embedding_delta,
)
from eom_catalog_service.embedding_index_assembly import PreparedEmbeddingIndexBasis
from eom_catalog_service.embedding_registry_application import (
    read_pinned_embedding_index,
    validate_registered_embedding_index_manifest,
    validate_registered_embedding_index_read,
)
from eom_catalog_service.embedding_registry_indexing_authority import (
    CatalogIndexingRegistrySourceAuthority,
)
from eom_catalog_service.embedding_registry_ports import (
    AuthorizedEmbeddingReadProfile,
    EmbeddingBindingOrigin,
    EmbeddingRegistryActor,
    EmbeddingRegistryCaller,
    EmbeddingRegistryError,
    EmbeddingRegistryLookup,
    EmbeddingRegistryRead,
    EmbeddingRegistryServiceCaller,
    MaterializedEmbeddingReadRow,
    ReferenceQueryContextPreparation,
    RegisteredEmbeddingIndexRead,
    ResolvedEmbeddingBindingOrigin,
    ResolvedEmbeddingLookup,
    ResolvedEmbeddingReferences,
    ResolvedEmbeddingRegistration,
    ResolvedPinnedEmbeddingIndex,
    SelectedEmbeddingSources,
    validate_embedding_registry_actor,
)
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryOwnerConfiguration as EmbeddingRegistryOwnerConfiguration,
)
from eom_catalog_service.embedding_registry_repository import (
    EmbeddingRegistryRepository,
    registered_row,
)
from eom_catalog_service.inference_transfer_catalog_adapter import (
    InferenceTransferCorpusReadCommand,
)
from eom_catalog_service.inference_transfer_scope import InferenceTransferPopulationScope
from eom_catalog_service.inference_transfer_service import InferenceTransferServiceError
from eom_catalog_service.inference_transfer_snapshot_catalog_adapter import (
    CatalogInferenceTransferSnapshotSourceAdapter,
    InferenceTransferSessionCapture,
    InferenceTransferSessionCapturePhase,
    LocalIndexingSessionCapture,
)
from eom_catalog_service.knowledge_graph_models import (
    KnowledgeCorpusRecord,
    KnowledgeGraphPublicationRecord,
    KnowledgeGraphSnapshotRecord,
)
from eom_catalog_service.knowledge_retrieval_service import KnowledgeRetrievalServiceError
from eom_catalog_service.local_embedding_source_plan import build_local_embedding_source_plan
from eom_catalog_service.local_indexing_source_ports import LocalIndexingSourceError
from eom_catalog_service.pinned_artifact_resolution import (
    PinnedArtifactReadContext,
    PinnedArtifactResolutionError,
)
from eom_catalog_service.reference_query_context_preparation import (
    validate_reference_query_context_preparation,
)
from eom_catalog_service.settings import CatalogSettings
from eom_catalog_service.similarity_context_ports import (
    PreparedSimilarityContext,
    PreparedSimilaritySource,
    SimilarityContextReadError,
    similarity_context_error_from_registry,
)
from eom_catalog_service.similarity_context_service import validate_similarity_preparation


@dataclass(frozen=True, slots=True)
class _SimilarityReadWindow:
    """Owner-private bounded decode reuse, not a current authority/membership cache."""

    session: Session
    transaction: object
    caller: EmbeddingRegistryActor
    reader: PinnedArtifactReadContext
    capture: InferenceTransferSessionCapture
    source_revision_ids: tuple[str, ...] = ()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for name, item in pairs:
        if name in value:
            raise ValueError("duplicate immutable JSON key")
        value[name] = item
    return value


def _reject_constant(_value: str) -> Any:
    raise ValueError("nonstandard immutable JSON constant")


def _document(payload: bytes) -> dict[str, Any]:
    value = json.loads(payload, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    if not isinstance(value, dict) or canonical_json_bytes(value) != payload:
        raise ValueError("immutable member is not exact canonical JSON")
    return value


class CatalogEmbeddingRegistryVerifier:
    """Concrete official source/member composition; IAM fence is mandatory and not supplied.

    Construct in the trusted owner, not from a DTO. No controller/runtime wiring
    is activated here. A required Identity fence implementation remains a separate
    official Identity security gate, and absent composition fails before writes.
    """

    def __init__(
        self,
        engine: Engine,
        configuration: EmbeddingRegistryOwnerConfiguration,
        *,
        identity_fence: OperatorAuthorizationFence | None,
        settings: CatalogSettings | None = None,
    ) -> None:
        self.engine = engine
        self.sessions = build_session_factory(engine)
        self._similarity_read_window: _SimilarityReadWindow | None = None
        self._similarity_requested_top_k: int | None = None
        self.configuration = EmbeddingRegistryOwnerConfiguration(
            configuration.corpus_id,
            EmbeddingIndexNamespace.model_validate(configuration.namespace.model_dump(mode="json")),
            EmbeddingSpace.model_validate(configuration.space.model_dump(mode="json")),
            ExperimentViewRecipe.model_validate(configuration.recipe.model_dump(mode="json")),
            configuration.source_classes,
        )
        config = self.configuration
        if (
            config.namespace.space_sha256 != config.space.space_sha256
            or config.namespace.recipe_sha256 != config.recipe.recipe_sha256
            or config.space.purpose != "DOCUMENT"
            or not config.source_classes
            or config.source_classes != tuple(sorted(set(config.source_classes)))
            or not set(config.source_classes).issubset({"APPROVED_ITEM", "PAST_EXAM"})
        ):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_CONFIGURATION_INVALID")
        self.settings = settings or CatalogSettings.from_environment()
        self.identity_fence = identity_fence
        self.sources = CatalogInferenceTransferSnapshotSourceAdapter(engine, self.settings)
        self._indexing_source_authority: CatalogIndexingRegistrySourceAuthority | None = None

    @classmethod
    def for_indexing_service(
        cls,
        engine: Engine,
        configuration: EmbeddingRegistryOwnerConfiguration,
        *,
        source_authority: CatalogIndexingRegistrySourceAuthority,
        settings: CatalogSettings | None = None,
    ) -> CatalogEmbeddingRegistryVerifier:
        """Explicit service owner, never inferred from caller identity or missing user auth."""
        if type(source_authority) is not CatalogIndexingRegistrySourceAuthority:
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_AUTHORITY_UNAVAILABLE")
        source_authority.__post_init__()
        owner = cls(engine, configuration, identity_fence=None, settings=settings)
        owner._indexing_source_authority = source_authority
        return owner

    def _capture_source(
        self,
        session: Session,
        caller: EmbeddingRegistryActor,
        intent: RegisterEmbeddingIndexCommand | EmbeddingRegistryLookup,
        *,
        artifact_reader: PinnedArtifactReadContext,
        phase: InferenceTransferSessionCapturePhase,
        source_revision_ids: tuple[str, ...] = (),
    ) -> InferenceTransferSessionCapture | LocalIndexingSessionCapture:
        validate_embedding_registry_actor(caller)
        if isinstance(caller, EmbeddingRegistryServiceCaller):
            if self._indexing_source_authority is None or self._similarity_read_window is not None:
                raise EmbeddingRegistryError("EMBEDDING_REGISTRY_AUTHORITY_UNAVAILABLE")
            return self._indexing_source_authority.capture(
                session,
                caller,
                intent,
                self.configuration,
                sources=self.sources,
                artifact_reader=artifact_reader,
                phase=phase,
                source_revision_ids=source_revision_ids,
            )
        if self.identity_fence is None or self._indexing_source_authority is not None:
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_AUTHORITY_UNAVAILABLE")
        return self.sources.capture_in_session(
            session,
            InferenceTransferCorpusReadCommand(
                actor_id=caller.operator_id,
                graph_snapshot=intent.graph_snapshot,
                access_policy_revision_id=intent.policy_revision_id,
                access_policy_sha256=intent.policy_sha256,
                source_classes=self.configuration.source_classes,
                maximum_candidates=1024
                if isinstance(intent, RegisterEmbeddingIndexCommand)
                else intent.maximum_sources,
                population_scope=InferenceTransferPopulationScope(
                    intent.namespace.population_scope
                ),
                top_k=1
                if self._similarity_requested_top_k is None
                else self._similarity_requested_top_k,
                source_revision_ids=source_revision_ids,
            ),
            self.configuration.recipe,
            identity_fence=self.identity_fence,
            artifact_reader=artifact_reader,
            phase=phase,
        )

    @staticmethod
    def _require_publication_authority(
        caller: EmbeddingRegistryActor,
        capture: InferenceTransferSessionCapture | LocalIndexingSessionCapture,
    ) -> None:
        if isinstance(caller, EmbeddingRegistryServiceCaller):
            if type(capture) is not LocalIndexingSessionCapture:
                raise EmbeddingRegistryError("EMBEDDING_REGISTRY_AUTHORITY_UNAVAILABLE")
        elif not isinstance(capture, InferenceTransferSessionCapture):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_AUTHORITY_UNAVAILABLE")
        elif "knowledge_graph:publish" not in capture.scope.requester_permission_keys:
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_FORBIDDEN")

    def _capture(
        self,
        session: Session,
        caller: EmbeddingRegistryActor,
        intent: RegisterEmbeddingIndexCommand | EmbeddingRegistryLookup,
        phase: InferenceTransferSessionCapturePhase,
        *,
        source_revision_ids: tuple[str, ...] = (),
    ) -> tuple[
        PinnedArtifactReadContext, InferenceTransferSessionCapture | LocalIndexingSessionCapture
    ]:
        if source_revision_ids and (
            isinstance(intent, RegisterEmbeddingIndexCommand)
            or self._similarity_read_window is not None
        ):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
        if (
            intent.corpus_id != self.configuration.corpus_id
            or intent.namespace != self.configuration.namespace
        ):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
        reader = PinnedArtifactReadContext(session, self.settings)
        window = self._similarity_read_window
        capture = self._capture_source(
            session,
            caller,
            intent,
            artifact_reader=reader if window is None else window.reader,
            phase=phase if window is None else InferenceTransferSessionCapturePhase.AUTHORIZE_SCOPE,
            source_revision_ids=source_revision_ids
            if window is None
            else window.source_revision_ids,
        )
        if window is not None:
            if (
                isinstance(intent, RegisterEmbeddingIndexCommand)
                or window.session is not session
                or window.transaction is not session.get_transaction()
                or session.in_nested_transaction()
                or window.caller != caller
                or window.capture.scope != capture.scope
            ):
                raise EmbeddingRegistryError("EMBEDDING_REGISTRY_AUTHORITY_UNAVAILABLE")
            reader = window.reader
            if phase is InferenceTransferSessionCapturePhase.CAPTURE_POPULATION:
                capture = window.capture
        if isinstance(intent, RegisterEmbeddingIndexCommand):
            self._require_publication_authority(caller, capture)
        corpus = session.scalar(
            select(KnowledgeCorpusRecord)
            .where(KnowledgeCorpusRecord.corpus_id == intent.corpus_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        graph = session.get(
            KnowledgeGraphSnapshotRecord, intent.graph_snapshot.graph_snapshot_revision_id
        )
        publication = session.scalar(
            select(KnowledgeGraphPublicationRecord).where(
                KnowledgeGraphPublicationRecord.graph_snapshot_revision_id
                == intent.graph_snapshot.graph_snapshot_revision_id,
                KnowledgeGraphPublicationRecord.corpus_id == intent.corpus_id,
            )
        )
        if (
            corpus is None
            or graph is None
            or publication is None
            or corpus.lifecycle_state != "ACTIVE"
            or graph.graph_id != corpus.graph_id
        ):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
        return reader, capture

    def _read_index(
        self, reader: PinnedArtifactReadContext, pointer: ArtifactMemberPointer
    ) -> EmbeddingIndexManifest:
        pointer = ArtifactMemberPointer.model_validate(pointer.model_dump(mode="json"))
        if (
            pointer.schema_ref != INDEX_SCHEMA_REF
            or pointer.member_path != EMBEDDING_INDEX_PRIMARY_MEMBER
            or pointer.media_type != "application/json"
        ):
            raise ValueError("foreign index pointer")
        reader.prefetch(((pointer.artifact_id, pointer.artifact_revision_id),))
        raw = reader.read_pinned(
            **pointer.model_dump(mode="python"),
            expected_artifact_types=(EMBEDDING_INDEX_ARTIFACT_TYPE,),
            expected_primary_file=EMBEDDING_INDEX_PRIMARY_MEMBER,
            max_bytes=MAX_EMBEDDING_INPUT_BYTES,
        )
        reader.require_file_set(
            pointer.artifact_id,
            pointer.artifact_revision_id,
            EMBEDDING_INDEX_MEMBER_NAMES,
            manifest_version=EMBEDDING_INDEX_MANIFEST_VERSION,
        )
        return parse_embedding_index(_document(raw.payload))

    def _read_shards(
        self,
        reader: PinnedArtifactReadContext,
        pointers: tuple[ArtifactMemberPointer, ...],
    ) -> tuple[tuple[ArtifactMemberPointer, EmbeddingVectorShardManifest], ...]:
        shards = []
        for pointer, shard, values in self._iter_numerical_shards(reader, pointers):
            shards.append((pointer, shard))
            del values
        return tuple(shards)

    def _iter_numerical_shards(
        self,
        reader: PinnedArtifactReadContext,
        pointers: tuple[ArtifactMemberPointer, ...],
    ) -> Iterator[
        tuple[ArtifactMemberPointer, EmbeddingVectorShardManifest, tuple[tuple[float, ...], ...]]
    ]:
        """One existing owner numeric boundary; registration discards decoded local values."""
        reader.prefetch(tuple(sorted({(p.artifact_id, p.artifact_revision_id) for p in pointers})))
        for pointer in pointers:
            if (
                pointer.schema_ref != SHARD_SCHEMA_REF
                or pointer.member_path != "shard.json"
                or pointer.media_type != "application/json"
            ):
                raise ValueError("foreign shard pointer")
            shard = parse_embedding_shard(
                _document(
                    reader.read_pinned(
                        **pointer.model_dump(mode="python"),
                        expected_artifact_types=("control_incremental_embedding",),
                        expected_primary_file="result.json",
                        max_bytes=MAX_EMBEDDING_INPUT_BYTES,
                    ).payload
                )
            )
            reader.require_file_set(
                pointer.artifact_id,
                pointer.artifact_revision_id,
                ("result.json", "shard.json", "vectors.f32"),
                manifest_version="control-file-set/1.0",
            )
            # The primary SHA is owner metadata, never guessed from the shard SHA.
            result_pointer = reader.member_pointer(
                pointer.artifact_id,
                pointer.artifact_revision_id,
                "result.json",
                schema_ref=RESULT_SCHEMA_REF,
                media_type="application/json",
            )
            result = parse_incremental_embedding_result(
                _document(
                    reader.read_pinned(
                        **result_pointer.model_dump(mode="python"),
                        expected_artifact_types=("control_incremental_embedding",),
                        expected_primary_file="result.json",
                        max_bytes=MAX_EMBEDDING_INPUT_BYTES,
                    ).payload
                )
            )
            if result.shard != shard or shard.space != self.configuration.space:
                raise ValueError("native result and exact configured shard differ")
            binary = ArtifactMemberPointer(
                artifact_id=pointer.artifact_id,
                artifact_revision_id=pointer.artifact_revision_id,
                member_path=shard.binary.member_path,
                schema_ref=shard.binary.schema_ref,
                media_type=shard.binary.media_type,
                sha256=shard.binary.sha256,
            )
            vectors = read_unit_vectors(
                reader.read_pinned(
                    **binary.model_dump(mode="python"),
                    expected_artifact_types=("control_incremental_embedding",),
                    expected_primary_file="result.json",
                    max_bytes=shard.binary.byte_count,
                ).payload,
                dimension=shard.dimension,
                row_count=shard.row_count,
                expected_sha256=shard.binary.sha256,
            )
            yield pointer, shard, vectors
            del vectors

    def _similarity_view_owner(
        self, request: SimilarityContextRequest, selection: SimilarityViewSelection
    ) -> CatalogEmbeddingRegistryVerifier:
        config = self.configuration
        if (
            request.consumer_purpose != "PAST_EXAM_VARIATION"
            or request.anchor.source.source_class != "PAST_EXAM"
            or request.topics
            or request.unit_ids
            or not set(request.source_classes).issubset(config.source_classes)
            or selection.recipe != config.recipe
            or (selection.index is not None and selection.index.spaces.document != config.space)
        ):
            raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
        namespace = EmbeddingIndexNamespace.model_validate(
            config.namespace.model_dump(mode="json") | {"view": selection.view}
        )
        owner = CatalogEmbeddingRegistryVerifier(
            self.engine,
            EmbeddingRegistryOwnerConfiguration(
                config.corpus_id, namespace, config.space, config.recipe, request.source_classes
            ),
            identity_fence=self.identity_fence,
            settings=self.settings,
        )
        # One real source owner, not three independently captured authority providers.
        owner.sources = self.sources
        owner._similarity_requested_top_k = request.top_k
        return owner

    def _similarity_capture(
        self,
        session: Session,
        caller: EmbeddingRegistryActor,
        request: SimilarityContextRequest,
        *,
        source_revision_ids: tuple[str, ...] = (),
    ) -> tuple[
        CatalogEmbeddingRegistryVerifier, PinnedArtifactReadContext, InferenceTransferSessionCapture
    ]:
        if (
            type(caller) is not EmbeddingRegistryCaller
            or self._indexing_source_authority is not None
        ):
            raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
        if any(
            selection.recipe != self.configuration.recipe
            or (
                selection.index is not None
                and selection.index.spaces.document != self.configuration.space
            )
            for selection in request.views
        ):
            raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
        owner = self._similarity_view_owner(request, request.views[0])
        scope = EmbeddingRegistryLookup(
            self.configuration.corpus_id,
            owner.configuration.namespace,
            request.graph_snapshot,
            request.policy_revision_id,
            request.policy_sha256,
            request.maximum_sources,
        )
        reader, capture = owner._guard(
            lambda: owner._capture(
                session,
                caller,
                scope,
                InferenceTransferSessionCapturePhase.CAPTURE_POPULATION,
                source_revision_ids=source_revision_ids,
            )
        )
        if not isinstance(capture, InferenceTransferSessionCapture):
            raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
        return owner, reader, capture

    @staticmethod
    def _prepare_similarity_capture(
        request: SimilarityContextRequest, capture: InferenceTransferSessionCapture
    ) -> PreparedSimilarityContext:
        if capture.corpus is None:
            raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
        entries = {
            entry.profile.source_basis.source.item_revision_id: entry for entry in capture.entries
        }
        values = []
        for value in sorted(
            capture.corpus.sources, key=lambda value: value.source.item_revision_id
        ):
            entry = entries.get(value.source.item_revision_id)
            values.append(
                PreparedSimilaritySource(
                    source=value.source,
                    profile=None
                    if entry is None
                    else InferenceTransferProfilePointer.from_profile(entry.profile),
                    solution_evidence=None
                    if entry is None
                    else entry.profile.source_basis.solution_evidence,
                )
            )
        anchor = entries.get(request.anchor.source.item_revision_id)
        texts = []
        if anchor is not None:
            for selection in request.views:
                text = experiment_view_text(anchor, selection.view)
                if text is not None and text.strip():
                    texts.append((selection.view, text))
        return PreparedSimilarityContext(
            request.request_sha256,
            tuple(values),
            tuple(texts),
            capture.corpus.graph_scores,
            truncated=capture.corpus.truncated,
        )

    def prepare_similarity_context(
        self, caller: EmbeddingRegistryActor, request: SimilarityContextRequest
    ) -> PreparedSimilarityContext:
        """Capture once through the official owner; only anchor text leaves preparation."""
        with self.sessions() as session, session.begin():
            return self.prepare_similarity_context_in_session(session, caller, request)

    @staticmethod
    def _require_similarity_root(session: Session) -> None:
        root = session.get_transaction()
        if root is None or not root.is_active or session.in_nested_transaction():
            raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")

    def prepare_similarity_context_in_session(
        self,
        session: Session,
        caller: EmbeddingRegistryActor,
        request: SimilarityContextRequest,
    ) -> PreparedSimilarityContext:
        """Preserve the current native owner's root; never open or commit another root."""
        self._require_similarity_root(session)
        request = parse_similarity_context_request(request)
        try:
            with session.no_autoflush:
                _owner, _reader, capture = self._similarity_capture(session, caller, request)
                return self._prepare_similarity_capture(request, capture)
        except EmbeddingRegistryError as error:
            raise similarity_context_error_from_registry(error) from None

    def read_similarity_views(
        self,
        caller: EmbeddingRegistryActor,
        request: SimilarityContextRequest,
        prepared: PreparedSimilarityContext,
    ) -> tuple[ResolvedPinnedEmbeddingIndex, ...]:
        """Bounded views share one read window; full start/end capture is actual authority."""
        with self.sessions() as session, session.begin():
            return self.read_similarity_views_in_session(session, caller, request, prepared)

    def read_similarity_views_in_session(
        self,
        session: Session,
        caller: EmbeddingRegistryActor,
        request: SimilarityContextRequest,
        prepared: PreparedSimilarityContext,
    ) -> tuple[ResolvedPinnedEmbeddingIndex, ...]:
        """Same checked read window in a caller root, with fresh start/end source fences."""
        self._require_similarity_root(session)
        request = parse_similarity_context_request(request)
        try:
            with session.no_autoflush:
                _owner, reader, capture = self._similarity_capture(session, caller, request)
                if self._prepare_similarity_capture(request, capture) != prepared:
                    raise SimilarityContextReadError("SOURCE_REVOKED")
                window = _SimilarityReadWindow(
                    session, session.get_transaction(), caller, reader, capture
                )
                return self._read_similarity_views_in_window(request, prepared, window)
        except EmbeddingRegistryError as error:
            raise similarity_context_error_from_registry(error) from None

    def prepare_and_read_similarity_context_in_session(
        self,
        session: Session,
        caller: EmbeddingRegistryActor,
        request: SimilarityContextRequest,
    ) -> tuple[PreparedSimilarityContext, tuple[ResolvedPinnedEmbeddingIndex, ...]]:
        """Prepare at the read's start; retain full start/end fences in this same root."""
        return self._prepare_and_read_similarity_scope(session, caller, request, ())

    def prepare_reference_query_anchor_in_session(
        self,
        session: Session,
        caller: EmbeddingRegistryActor,
        request: SimilarityContextRequest,
    ) -> PreparedSimilarityContext:
        """Validate QUERY's exact anchor and pinned indexes, never population coverage."""
        self._require_similarity_root(session)
        request = parse_similarity_context_request(request)
        prepared, _reads = self._prepare_and_read_similarity_scope(
            session, caller, request, (request.anchor.source.item_revision_id,)
        )
        if len(prepared.sources) != 1 or prepared.truncated:
            raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
        return prepared

    def _prepare_and_read_similarity_scope(
        self,
        session: Session,
        caller: EmbeddingRegistryActor,
        request: SimilarityContextRequest,
        source_revision_ids: tuple[str, ...],
    ) -> tuple[PreparedSimilarityContext, tuple[ResolvedPinnedEmbeddingIndex, ...]]:
        self._require_similarity_root(session)
        request = parse_similarity_context_request(request)
        try:
            with session.no_autoflush:
                _owner, reader, capture = self._similarity_capture(
                    session, caller, request, source_revision_ids=source_revision_ids
                )
                prepared = self._prepare_similarity_capture(request, capture)
                validate_similarity_preparation(request, prepared)
                if source_revision_ids and (
                    tuple(value.source.item_revision_id for value in prepared.sources)
                    != source_revision_ids
                    or prepared.truncated
                ):
                    raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
                window = _SimilarityReadWindow(
                    session, session.get_transaction(), caller, reader, capture, source_revision_ids
                )
                reads = self._read_similarity_views_in_window(request, prepared, window)
                return prepared, reads
        except EmbeddingRegistryError as error:
            raise similarity_context_error_from_registry(error) from None

    def _read_similarity_views_in_window(
        self,
        request: SimilarityContextRequest,
        prepared: PreparedSimilarityContext,
        window: _SimilarityReadWindow,
    ) -> tuple[ResolvedPinnedEmbeddingIndex, ...]:
        """One authoritative read/end-fence path for both root-local entrypoints."""
        session, caller = window.session, window.caller
        results = []
        query_views = {view for view, _text in prepared.query_texts}
        for selection in request.views:
            if selection.index is None or selection.view not in query_views:
                continue
            owner = self._similarity_view_owner(request, selection)
            owner._similarity_read_window = window
            scope = EmbeddingRegistryLookup(
                self.configuration.corpus_id,
                owner.configuration.namespace,
                request.graph_snapshot,
                request.policy_revision_id,
                request.policy_sha256,
                request.maximum_sources,
            )
            try:
                results.append(
                    read_pinned_embedding_index(
                        session, caller, EmbeddingRegistryRead(scope, selection), owner
                    )
                )
            except EmbeddingRegistryError as error:
                if error.code in {
                    "EMBEDDING_REGISTRY_FORBIDDEN",
                    "EMBEDDING_REGISTRY_AUTHORITY_UNAVAILABLE",
                }:
                    raise similarity_context_error_from_registry(error) from None
                raise SimilarityContextReadError("INDEX_POINTER_INVALID") from None
        # READ COMMITTED or shared Session is not immutable source membership.
        # Re-resolve every source/report in this exact scope before returning.
        # Only QUERY input preparation is anchor-scoped; ranking remains full-population.
        _owner, _reader, final = self._similarity_capture(
            session, caller, request, source_revision_ids=window.source_revision_ids
        )
        if self._prepare_similarity_capture(request, final) != prepared:
            raise SimilarityContextReadError("SOURCE_REVOKED")
        return tuple(results)

    def reauthorize_similarity_context(
        self,
        caller: EmbeddingRegistryActor,
        request: SimilarityContextRequest,
        prepared: PreparedSimilarityContext,
    ) -> None:
        """Fresh full-population check after QUERY/ranking, never a persisted grant."""
        current = self.prepare_similarity_context(caller, request)
        if current != prepared:
            raise SimilarityContextReadError("SOURCE_REVOKED")

    def authorize_scope(
        self,
        session: Session,
        caller: EmbeddingRegistryActor,
        intent: RegisterEmbeddingIndexCommand | EmbeddingRegistryLookup,
    ) -> None:
        self._guard(
            lambda: self._capture(
                session, caller, intent, InferenceTransferSessionCapturePhase.AUTHORIZE_SCOPE
            )
        )

    @staticmethod
    def _guard[T](operation: Callable[[], T]) -> T:
        try:
            return operation()
        except EmbeddingRegistryError:
            raise
        except OperatorAuthorizationFenceError as error:
            code = (
                "EMBEDDING_REGISTRY_FORBIDDEN"
                if error.code
                in {
                    "OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN",
                    "OPERATOR_AUTHORIZATION_FENCE_OPERATOR_INVALID",
                }
                else "EMBEDDING_REGISTRY_AUTHORITY_UNAVAILABLE"
            )
            raise EmbeddingRegistryError(code) from None
        except IdentityError:
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_FORBIDDEN") from None
        except LocalIndexingSourceError as error:
            code = (
                "EMBEDDING_REGISTRY_FORBIDDEN"
                if error.code == "LOCAL_INDEXING_SOURCE_FORBIDDEN"
                else "EMBEDDING_REGISTRY_AUTHORITY_UNAVAILABLE"
            )
            raise EmbeddingRegistryError(code) from None
        except InferenceTransferServiceError as error:
            code = (
                "EMBEDDING_REGISTRY_FORBIDDEN"
                if error.code == "INFERENCE_TRANSFER_FORBIDDEN"
                else "EMBEDDING_REGISTRY_SCOPE_LIMIT"
                if error.code == "INFERENCE_TRANSFER_SNAPSHOT_POPULATION_TRUNCATED"
                else "EMBEDDING_REGISTRY_POINTER_INVALID"
            )
            raise EmbeddingRegistryError(code) from None
        except KnowledgeRetrievalServiceError as error:
            code = (
                "EMBEDDING_REGISTRY_FORBIDDEN"
                if error.code
                in {"KNOWLEDGE_RETRIEVAL_UNAUTHORIZED", "KNOWLEDGE_RETRIEVAL_REQUESTER_INVALID"}
                else "EMBEDDING_REGISTRY_POINTER_INVALID"
            )
            raise EmbeddingRegistryError(code) from None
        except (PinnedArtifactResolutionError, JsonSchemaError, ValueError, TypeError, KeyError):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_POINTER_INVALID") from None

    def resolve_registration(
        self,
        session: Session,
        caller: EmbeddingRegistryActor,
        command: RegisterEmbeddingIndexCommand,
    ) -> ResolvedEmbeddingRegistration:
        def resolve() -> ResolvedEmbeddingRegistration:
            reader, _ = self._capture(
                session, caller, command, InferenceTransferSessionCapturePhase.AUTHORIZE_SCOPE
            )
            index = self._read_index(reader, command.index_manifest)
            if index.space != self.configuration.space or index.recipe != self.configuration.recipe:
                raise ValueError("index numerical configuration differs")
            shards = self._read_shards(reader, index.shards)
            previous = (
                None
                if index.previous_manifest is None
                else (index.previous_manifest, self._read_index(reader, index.previous_manifest))
            )
            # Source/lifecycle eligibility stays with the same official owner and root Session.
            capture = self._capture_source(
                session,
                caller,
                command,
                artifact_reader=reader,
                phase=InferenceTransferSessionCapturePhase.CAPTURE_POPULATION,
            )
            assert capture.corpus is not None
            sources = tuple(
                sorted(
                    (value.source for value in capture.corpus.sources),
                    key=lambda value: value.item_revision_id,
                )
            )
            return ResolvedEmbeddingRegistration(
                command.corpus_id, index, shards, previous, sources, capture.entries
            )

        return self._guard(resolve)

    def require_index_publication_scope(
        self, session: Session, caller: EmbeddingRegistryActor, query: EmbeddingRegistryLookup
    ) -> None:
        """Admit the real publish permission BEFORE native allocation/model work."""

        def admit() -> None:
            _reader, capture = self._capture(
                session, caller, query, InferenceTransferSessionCapturePhase.AUTHORIZE_SCOPE
            )
            self._require_publication_authority(caller, capture)

        self._guard(admit)

    def resolve_prepared_index(
        self,
        session: Session,
        caller: EmbeddingRegistryActor,
        command: RegisterEmbeddingIndexCommand,
        index: EmbeddingIndexManifest,
    ) -> ResolvedEmbeddingRegistration:
        """Validate exact local proposed bytes with canonical CURRENT sources/numeric rows.

        This does not claim that the index Artifact is committed or registered. It
        permits the existing Artifact owner to publish a trusted prepared result;
        registration still resolves and verifies that actual committed member.
        """

        def resolve() -> ResolvedEmbeddingRegistration:
            reader, _capture = self._capture(
                session, caller, command, InferenceTransferSessionCapturePhase.AUTHORIZE_SCOPE
            )
            checked = parse_embedding_index(index.model_dump(mode="json"))
            if (
                checked.space != self.configuration.space
                or checked.recipe != self.configuration.recipe
            ):
                raise ValueError("prepared index numerical configuration differs")
            shards = self._read_shards(reader, checked.shards)
            previous = (
                None
                if checked.previous_manifest is None
                else (
                    checked.previous_manifest,
                    self._read_index(reader, checked.previous_manifest),
                )
            )
            capture = self._capture_source(
                session,
                caller,
                command,
                artifact_reader=reader,
                phase=InferenceTransferSessionCapturePhase.CAPTURE_POPULATION,
            )
            assert capture.corpus is not None
            return ResolvedEmbeddingRegistration(
                command.corpus_id,
                checked,
                shards,
                previous,
                tuple(
                    sorted(
                        (s.source for s in capture.corpus.sources), key=lambda s: s.item_revision_id
                    )
                ),
                capture.entries,
                capture.corpus.truncated,
            )

        return self._guard(resolve)

    def resolve_optional_index_publication(
        self,
        session: Session,
        caller: EmbeddingRegistryActor,
        command: RegisterEmbeddingIndexCommand,
    ) -> ResolvedEmbeddingRegistration | None:
        """Only absence of BOTH exact metadata identities means not yet published.

        Wrong identity, partial metadata, revoked source, hash drift or unapproved
        producer is an error, never a fallback to local/new/latest materialization.
        Current publication authority is checked before revealing either existence.
        """

        def resolve() -> ResolvedEmbeddingRegistration | None:
            self.authorize_scope(session, caller, command)
            pointer = command.index_manifest
            logical = session.get(ArtifactRecord, pointer.artifact_id, populate_existing=True)
            revision = session.get(
                ArtifactRevisionRecord, pointer.artifact_revision_id, populate_existing=True
            )
            if logical is None and revision is None:
                return None
            if (
                logical is None
                or revision is None
                or revision.logical_artifact_id != pointer.artifact_id
            ):
                raise ValueError(
                    "index publication identity is dangling or belongs to another entity"
                )
            return self.resolve_registration(session, caller, command)

        return self._guard(resolve)

    def resolve_lookup(
        self, session: Session, caller: EmbeddingRegistryActor, query: EmbeddingRegistryLookup
    ) -> ResolvedEmbeddingLookup:
        def resolve() -> ResolvedEmbeddingLookup:
            _reader, capture = self._capture(
                session, caller, query, InferenceTransferSessionCapturePhase.CAPTURE_POPULATION
            )
            assert capture.corpus is not None
            return ResolvedEmbeddingLookup(
                query.corpus_id,
                self.configuration.space,
                self.configuration.recipe,
                tuple(value.source for value in capture.corpus.sources),
                capture.entries,
            )

        return self._guard(resolve)

    def resolve_selected_sources(
        self,
        session: Session,
        caller: EmbeddingRegistryActor,
        selection: SelectedEmbeddingSources,
    ) -> ResolvedEmbeddingLookup:
        """Exact native-plan targets; never use this result as full index coverage."""

        def resolve() -> ResolvedEmbeddingLookup:
            if type(selection) is not SelectedEmbeddingSources:
                raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
            selection.__post_init__()
            _reader, capture = self._capture(
                session,
                caller,
                selection.scope,
                InferenceTransferSessionCapturePhase.CAPTURE_POPULATION,
                source_revision_ids=selection.source_revision_ids,
            )
            if capture.corpus is None:
                raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
            sources = tuple(value.source for value in capture.corpus.sources)
            actual = tuple(value.item_revision_id for value in sources)
            if (
                set(actual) != set(selection.source_revision_ids)
                or len(actual) != len(selection.source_revision_ids)
                or capture.corpus.truncated
            ):
                raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
            return ResolvedEmbeddingLookup(
                selection.scope.corpus_id,
                self.configuration.space,
                self.configuration.recipe,
                sources,
                capture.entries,
            )

        return self._guard(resolve)

    def prepare_reference_query_context_in_session(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        preparation: ReferenceQueryContextPreparation,
    ) -> SimilarityContextRequest:
        """Pin initial reference/report/current-view indexes, never reselect on replay.

        The caller first selects a real initial request; stored QUERY requests are
        the replay source. No vector read/encode, source grant, commit or queue.
        """
        self._require_similarity_root(session)

        def resolve() -> SimilarityContextRequest:
            if (
                type(caller) is not EmbeddingRegistryCaller
                or type(preparation) is not ReferenceQueryContextPreparation
                or session.get_bind() is not self.engine
                or self._indexing_source_authority is not None
            ):
                raise EmbeddingRegistryError("EMBEDDING_REGISTRY_AUTHORITY_UNAVAILABLE")
            validate_reference_query_context_preparation(preparation, self.configuration)
            selection, spaces = preparation.selection, preparation.spaces
            scope, config = selection.scope, self.configuration
            captured = self.resolve_selected_sources(session, caller, selection)
            source = captured.sources[0]
            if source.source_class != "PAST_EXAM" or len(captured.entries) > 1:
                raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
            entry = captured.entries[0] if captured.entries else None
            if entry is not None:
                validate_local_embedding_entry_source(
                    source,
                    entry,
                    graph_snapshot=scope.graph_snapshot,
                    projection_version=scope.namespace.projection_version,
                )
            reader = PinnedArtifactReadContext(session, self.settings)
            repository = EmbeddingRegistryRepository(session)
            views = []
            for view in preparation.views:
                namespace = EmbeddingIndexNamespace.model_validate(
                    scope.namespace.model_dump(mode="json") | {"view": view}
                )
                current = repository.current_namespace_revision(scope.corpus_id, namespace)
                selected = SimilarityViewSelection(view=view, recipe=config.recipe, index=None)
                if current is not None:
                    registered, _version = current
                    selected = SimilarityViewSelection(
                        view=view,
                        recipe=config.recipe,
                        index=SimilarityIndexPin(
                            index_id=registered.index_id,
                            index_revision_id=registered.index_revision_id,
                            index_manifest=registered.index_manifest,
                            index_sha256=registered.index_sha256,
                            storage_partition=namespace.storage_partition,
                            spaces=spaces,
                        ),
                    )
                    intent = EmbeddingRegistryRead(
                        EmbeddingRegistryLookup(
                            scope.corpus_id,
                            namespace,
                            scope.graph_snapshot,
                            scope.policy_revision_id,
                            scope.policy_sha256,
                            scope.maximum_sources,
                        ),
                        selected,
                    )
                    validate_registered_embedding_index_read(intent, registered)
                    manifest = self._read_index(reader, registered.index_manifest)
                    validate_similarity_index_pin(selected, registered.index_manifest, manifest)
                    validate_registered_embedding_index_manifest(registered, manifest)
                views.append(selected.model_dump(mode="json"))
            body = {
                "schema_version": "system-rag-similarity-request/1.0",
                "request_id": preparation.request_id,
                "consumer_purpose": "PAST_EXAM_VARIATION",
                "anchor": {
                    "basis": "APPROVED_REFERENCE_ITEM",
                    "source": source.model_dump(mode="json"),
                    "profile": None
                    if entry is None
                    else InferenceTransferProfilePointer.from_profile(entry.profile).model_dump(
                        mode="json"
                    ),
                    "solution_evidence": None
                    if entry is None
                    else entry.profile.source_basis.solution_evidence.model_dump(mode="json"),
                },
                "graph_snapshot": scope.graph_snapshot.model_dump(mode="json"),
                "policy_revision_id": scope.policy_revision_id,
                "policy_sha256": scope.policy_sha256,
                "source_classes": list(config.source_classes),
                "topics": [],
                "unit_ids": [],
                "views": views,
                "vector_mode": preparation.vector_mode,
                "maximum_sources": scope.maximum_sources,
                "top_k": preparation.top_k,
            }
            request = parse_similarity_context_request(
                body | {"request_sha256": content_sha256(body)}
            )
            validate_reference_query_context_preparation(preparation, config, request)
            # Reauthorize the exact anchor after bytes, not a second mutable-head selection.
            if self.resolve_selected_sources(session, caller, selection) != captured:
                raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
            return request

        return self._guard(resolve)

    def read_similarity_materials_in_session(
        self, session: Session, caller: EmbeddingRegistryCaller, context: SimilarityContext
    ) -> SimilarityReferenceMaterials:
        """Selected official projections; caller separately verifies QUERY/context provenance."""
        self._require_similarity_root(session)
        context = parse_similarity_context(context)
        request = context.request
        validate_deliverable_similarity_context(context, expected_request=request)
        if len(context.candidates) > MAX_SIMILARITY_MATERIAL_CANDIDATES:
            raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
        if (
            type(caller) is not EmbeddingRegistryCaller
            or self._indexing_source_authority is not None
        ):
            raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
        owner = self._similarity_view_owner(request, request.views[0])
        targets = {candidate.source.item_revision_id for candidate in context.candidates}
        if request.anchor.profile is not None:
            targets.add(request.anchor.source.item_revision_id)
        try:
            if not targets:
                # Even an empty projection cannot skip the actual source owner.
                self._similarity_capture(session, caller, request)
                return build_similarity_materials(context, anchor_profile=None, entries=())
            selected = SelectedEmbeddingSources(
                EmbeddingRegistryLookup(
                    owner.configuration.corpus_id,
                    owner.configuration.namespace,
                    request.graph_snapshot,
                    request.policy_revision_id,
                    request.policy_sha256,
                    request.maximum_sources,
                ),
                tuple(sorted(targets)),
            )
            resolved = owner.resolve_selected_sources(session, caller, selected)
            entries = {
                entry.profile.source_basis.source.item_revision_id: entry
                for entry in resolved.entries
            }
            if len(entries) != len(resolved.entries) or set(entries) != targets:
                raise ValueError("selected reference projections differ")
            return build_similarity_materials(
                context,
                anchor_profile=None
                if request.anchor.profile is None
                else entries[request.anchor.source.item_revision_id].profile,
                entries=tuple(entries[row.source.item_revision_id] for row in context.candidates),
            )
        except EmbeddingRegistryError as error:
            raise similarity_context_error_from_registry(error) from None
        except (ValueError, TypeError, JsonSchemaError):
            raise SimilarityContextReadError("SOURCE_POINTER_INVALID") from None

    def prepare_index_basis(
        self, session: Session, caller: EmbeddingRegistryActor, query: EmbeddingRegistryLookup
    ) -> PreparedEmbeddingIndexBasis:
        """Capture full current eligibility and reusable rows once before index assembly.

        Old index bindings provide predecessor identity ONLY. Reusable numeric rows
        are selected by exact current encoding keys, checked against current source
        projections, and resolved through the canonical finite/L2 file-set reader.
        No Job/model execution, registry mutation or future permission is returned.
        """

        def resolve() -> PreparedEmbeddingIndexBasis:
            reader, capture = self._capture(
                session, caller, query, InferenceTransferSessionCapturePhase.CAPTURE_POPULATION
            )
            if capture.corpus is None:
                raise ValueError("index basis has no complete current population")
            resolved = ResolvedEmbeddingLookup(
                query.corpus_id,
                self.configuration.space,
                self.configuration.recipe,
                tuple(s.source for s in capture.corpus.sources),
                capture.entries,
                capture.corpus.truncated,
            )
            plan = build_local_embedding_source_plan(
                query,
                resolved,
                target_revision_ids=tuple(sorted(s.item_revision_id for s in resolved.sources)),
            )
            expected = {d.encoding.encoding_sha256: d.encoding for d in plan.demands}
            repository = EmbeddingRegistryRepository(session)
            records = repository.encodings(tuple(sorted(expected)))
            rows = tuple(registered_row(records[key]) for key in sorted(records))
            if any(row.encoding != expected.get(row.encoding.encoding_sha256) for row in rows):
                raise ValueError("registered encoding differs from exact current input")
            pointers = tuple(
                sorted(
                    {row.row_ref.shard_manifest for row in rows},
                    key=lambda p: (p.artifact_id, p.artifact_revision_id, p.member_path, p.sha256),
                )
            )
            shards = self._read_shards(reader, pointers)
            by_pointer = dict(shards)
            for row in rows:
                shard = by_pointer[row.row_ref.shard_manifest]
                if (
                    row.row_ref.row_index >= len(shard.rows)
                    or shard.rows[row.row_ref.row_index] != row.encoding
                ):
                    raise ValueError("registered row differs from exact committed ordinal")
            selected = repository.current_namespace_revision(query.corpus_id, query.namespace)
            previous = None
            version = 1
            if selected is not None:
                registered, version = selected
                index = self._read_index(reader, registered.index_manifest)
                validate_registered_embedding_index_manifest(registered, index)
                if (
                    registered.corpus_id != query.corpus_id
                    or registered.namespace != query.namespace
                    or index.space != self.configuration.space
                    or index.recipe != self.configuration.recipe
                ):
                    raise ValueError("registered predecessor differs from its immutable namespace")
                previous = registered.index_manifest, index
            # Recheck current caller/policy after filesystem reads; no corpus recapture.
            self.authorize_scope(session, caller, query)
            return PreparedEmbeddingIndexBasis(plan, rows, shards, previous, version)

        return self._guard(resolve)

    def resolve_pinned_read(
        self,
        session: Session,
        caller: EmbeddingRegistryActor,
        intent: EmbeddingRegistryRead,
        registered: RegisteredEmbeddingIndexRead,
    ) -> ResolvedPinnedEmbeddingIndex:
        """Use the existing actual read owner, never registration/write authority."""

        def resolve() -> ResolvedPinnedEmbeddingIndex:
            if (
                type(caller) is not EmbeddingRegistryCaller
                or self._indexing_source_authority is not None
            ):
                raise EmbeddingRegistryError("EMBEDDING_REGISTRY_FORBIDDEN")
            reader, capture = self._capture(
                session,
                caller,
                intent.scope,
                InferenceTransferSessionCapturePhase.CAPTURE_POPULATION,
            )
            assert capture.corpus is not None
            pin = intent.selection.index
            if pin is None:
                raise ValueError("pinned index selection is absent")
            index = self._read_index(reader, pin.index_manifest)
            validate_similarity_index_pin(intent.selection, pin.index_manifest, index)
            validate_registered_embedding_index_manifest(registered, index)
            if (
                index.space != self.configuration.space
                or index.recipe != self.configuration.recipe
                or registered.index_manifest != pin.index_manifest
            ):
                raise ValueError("registered index namespace/revision/hash/count differs")
            sources = tuple(
                sorted(
                    (value.source for value in capture.corpus.sources),
                    key=lambda value: value.item_revision_id,
                )
            )
            admitted = {value.item_revision_id: value for value in sources}
            entries = {
                value.profile.source_basis.source.item_revision_id: value
                for value in capture.entries
            }
            selected = tuple(
                binding for binding in index.bindings if binding.source.item_revision_id in admitted
            )
            for binding in selected:
                if (
                    binding.source != admitted[binding.source.item_revision_id]
                    or binding.source.item_revision_id not in entries
                    or binding.graph_snapshot != intent.scope.graph_snapshot
                    or binding.policy_revision_id != intent.scope.policy_revision_id
                    or binding.policy_sha256 != intent.scope.policy_sha256
                    or binding.view != intent.selection.view
                    or binding.recipe != intent.selection.recipe
                    or binding.projection_version != intent.scope.namespace.projection_version
                ):
                    raise ValueError("eligible binding source/report/Graph/policy pin is stale")
            pointers = tuple(
                sorted(
                    {binding.row_ref.shard_manifest for binding in selected},
                    key=lambda pointer: (
                        pointer.artifact_id,
                        pointer.artifact_revision_id,
                        pointer.member_path,
                        pointer.sha256,
                    ),
                )
            )
            by_pointer: dict[ArtifactMemberPointer, list[EmbeddingSourceBinding]] = {}
            for binding in selected:
                by_pointer.setdefault(binding.row_ref.shard_manifest, []).append(binding)
            shards = []
            materialized: dict[str, MaterializedEmbeddingReadRow] = {}
            for pointer, shard, values in self._iter_numerical_shards(reader, pointers):
                shards.append((pointer, shard))
                for binding in by_pointer[pointer]:
                    if binding.row_ref.row_index >= len(values):
                        raise ValueError("selected immutable row index is missing")
                    row = MaterializedEmbeddingReadRow(
                        RegisteredEmbeddingRow(binding.encoding, binding.row_ref),
                        values[binding.row_ref.row_index],
                    )
                    previous = materialized.get(binding.encoding.encoding_sha256)
                    if previous is not None and previous.row != row.row:
                        raise ValueError("one selected encoding has conflicting immutable rows")
                    materialized[binding.encoding.encoding_sha256] = row
                # Retain selected row tuples only, not every decoded corpus shard matrix.
                del values
            validate_embedding_source_bindings(
                selected,
                capture.entries,
                tuple(shards),
            )
            rows = tuple(materialized[key] for key in sorted(materialized))
            profiles = tuple(
                AuthorizedEmbeddingReadProfile(
                    revision, InferenceTransferProfilePointer.from_profile(entry.profile)
                )
                for revision, entry in sorted(entries.items())
            )
            return ResolvedPinnedEmbeddingIndex(intent, sources, profiles, selected, rows)

        return self._guard(resolve)

    def verify_registered_references(
        self,
        session: Session,
        caller: EmbeddingRegistryActor,
        intent: RegisterEmbeddingIndexCommand | EmbeddingRegistryLookup,
        rows: tuple[RegisteredEmbeddingRow, ...],
        origins: tuple[EmbeddingBindingOrigin, ...],
    ) -> ResolvedEmbeddingReferences:
        def resolve() -> ResolvedEmbeddingReferences:
            if len(rows) > 1024 or len(origins) > 1024:
                raise ValueError("registered reference budget exceeded")
            reader, capture = self._capture(
                session, caller, intent, InferenceTransferSessionCapturePhase.CAPTURE_POPULATION
            )
            plan = plan_embedding_delta(
                capture.entries,
                space=self.configuration.space,
                storage_partition=intent.namespace.storage_partition,
                views=(intent.namespace.view,),
            )
            expected = {d.encoding.encoding_sha256: d.encoding for d in plan.demands}
            checked_rows = tuple(
                RegisteredEmbeddingRow(
                    EmbeddingEncodingIdentity.model_validate(row.encoding.model_dump(mode="json")),
                    EmbeddingVectorRowRef.model_validate(row.row_ref.model_dump(mode="json")),
                )
                for row in rows
            )
            if len({row.encoding.encoding_sha256 for row in checked_rows}) != len(rows) or len(
                set(origins)
            ) != len(origins):
                raise ValueError("duplicate registered references")
            pointers = {row.row_ref.shard_manifest for row in checked_rows}
            index_pointers = tuple(
                sorted(
                    {origin.manifest for origin in origins},
                    key=lambda p: (p.artifact_id, p.artifact_revision_id, p.member_path, p.sha256),
                )
            )
            reader.prefetch(tuple((p.artifact_id, p.artifact_revision_id) for p in index_pointers))
            indices = {pointer: self._read_index(reader, pointer) for pointer in index_pointers}
            bindings = {
                pointer: {value.binding_sha256: value for value in index.bindings}
                for pointer, index in indices.items()
            }
            resolved = tuple(
                ResolvedEmbeddingBindingOrigin(
                    origin, bindings[origin.manifest][origin.binding_sha256]
                )
                for origin in origins
            )
            pointers.update(value.binding.row_ref.shard_manifest for value in resolved)
            shards = self._read_shards(
                reader,
                tuple(
                    sorted(
                        pointers,
                        key=lambda p: (
                            p.artifact_id,
                            p.artifact_revision_id,
                            p.member_path,
                            p.sha256,
                        ),
                    )
                ),
            )
            by_pointer = dict(shards)
            for row in checked_rows:
                shard = by_pointer[row.row_ref.shard_manifest]
                if (
                    row.encoding != expected.get(row.encoding.encoding_sha256)
                    or row.row_ref.encoding_sha256 != row.encoding.encoding_sha256
                    or row.row_ref.row_index >= len(shard.rows)
                    or shard.rows[row.row_ref.row_index] != row.encoding
                ):
                    raise ValueError("registered encoding differs from current source or exact row")
            selected = {value.binding.row_ref.shard_manifest for value in resolved}
            assert capture.corpus is not None
            admitted_sources = {
                value.source.item_revision_id: value.source for value in capture.corpus.sources
            }
            if any(
                value.binding.source != admitted_sources.get(value.binding.source.item_revision_id)
                or value.binding.graph_snapshot != intent.graph_snapshot
                or value.binding.policy_revision_id != intent.policy_revision_id
                or value.binding.policy_sha256 != intent.policy_sha256
                or value.binding.view != intent.namespace.view
                or value.binding.recipe != self.configuration.recipe
                or value.binding.projection_version != intent.namespace.projection_version
                for value in resolved
            ):
                raise ValueError("registered binding differs from exact current admitted scope")
            binding_shards = tuple(
                (pointer, shard) for pointer, shard in shards if pointer in selected
            )
            validate_embedding_source_bindings(
                tuple(value.binding for value in resolved), capture.entries, binding_shards
            )
            return ResolvedEmbeddingReferences(resolved, binding_shards)

        return self._guard(resolve)
