"""Catalog Registry composition over the same canonical source/member validators."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any, Literal, overload

from eom_catalog_contracts.embedding_index_families import (
    SupportedEmbeddingBinding,
    embedding_entry_profile,
    embedding_entry_source,
    parse_supported_embedding_index,
    validate_supported_embedding_source_bindings,
)
from eom_catalog_contracts.embedding_reference_query import (
    ReferenceQuerySpaces,
    raw_similarity_contract_value,
)
from eom_catalog_contracts.embedding_registry import (
    EmbeddingIndexNamespace,
    RegisterEmbeddingIndexCommand,
)
from eom_catalog_contracts.embedding_vector_binary import read_unit_vectors
from eom_catalog_contracts.exam_similarity_observation import (
    ExamObservationRequest,
    ExamSimilarityObservation,
    parse_exam_observation_request,
)
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
    parse_embedding_shard,
    parse_incremental_embedding_result,
    validate_embedding_source_bindings,
)
from eom_catalog_contracts.inference_transfer_experiment import (
    ExperimentView,
    ExperimentViewRecipe,
    StagedExperimentEntry,
    experiment_view_text,
)
from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfilePointer
from eom_catalog_contracts.knowledge import ApprovedItemKnowledgeSourceV2
from eom_catalog_contracts.mixed_embedding_index import (
    MIXED_EMBEDDING_INDEX_SCHEMA_REF,
    MixedEmbeddingIndexManifest,
    RegisteredReviewEmbeddingEntry,
    RegisteredReviewEmbeddingSourceBinding,
)
from eom_catalog_contracts.mixed_embedding_registry import (
    MixedEmbeddingIndexNamespace,
    RegisterEmbeddingIndexCommandV2,
)
from eom_catalog_contracts.private_chat_similarity import PrivateChatSimilarityRequest
from eom_catalog_contracts.public_solution_embedding import (
    PublicSolutionEmbeddingEntry,
    PublicSolutionEmbeddingRecipe,
)
from eom_catalog_contracts.public_solution_embedding_index import (
    MAX_PUBLIC_SOLUTION_SOURCES,
    PUBLIC_SOLUTION_INDEX_SCHEMA_REF,
    PublicSolutionEmbeddingIndex,
    PublicSolutionEmbeddingSourceBinding,
    PublicSolutionIndexNamespace,
)
from eom_catalog_contracts.public_solution_embedding_registry import (
    RegisterPublicSolutionIndexCommand,
)
from eom_catalog_contracts.public_solution_similarity import PublicSolutionSimilarityView
from eom_catalog_contracts.registered_public_solution_embedding import (
    RegisteredPublicSolutionEmbeddingEntry,
)
from eom_catalog_contracts.registered_public_solution_index import (
    REGISTERED_PUBLIC_SOLUTION_INDEX_SCHEMA_REF,
    PublicSolutionEmbeddingIndexV4,
    RegisteredPublicSolutionSourceBinding,
)
from eom_catalog_contracts.registered_public_solution_registry import (
    RegisterPublicSolutionIndexCommandV4,
)
from eom_catalog_contracts.registered_public_solution_similarity import (
    PublicSolutionSimilarityViewV4,
)
from eom_catalog_contracts.registered_review_profile import RegisteredReviewProfilePointer
from eom_catalog_contracts.similarity_context import (
    SimilarityContext,
    SimilarityIndexPin,
    SimilarityViewSelection,
    similarity_index_matches_pin,
)
from eom_catalog_contracts.similarity_context_v2 import (
    SimilarityContextRequestV2,
    SimilarityContextV2,
    SimilarityIndexPinV2,
    SimilarityViewSelectionV2,
    SupportedSimilarityContext,
    SupportedSimilarityContextRequest,
    parse_supported_similarity_context,
    parse_supported_similarity_context_request,
    validate_deliverable_similarity_context_v2,
)
from eom_catalog_contracts.similarity_delivery import validate_deliverable_similarity_context
from eom_catalog_contracts.similarity_materials import (
    MAX_SIMILARITY_MATERIAL_CANDIDATES,
    SimilarityReferenceMaterials,
    build_similarity_materials,
)
from eom_catalog_contracts.similarity_materials_v2 import (
    SimilarityReferenceMaterialsV2,
    build_similarity_materials_v2,
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
from eom_workflow.local_embedding_source_plan import (
    validate_local_embedding_entry_source,
)
from eom_workflow.local_embedding_source_plan_dispatch import SupportedLocalEmbeddingSourcePlan
from eom_workflow.local_embedding_source_plan_v2 import (
    LocalEmbeddingSourcePlanV2,
    validate_local_embedding_entry_source_v2,
)
from eom_workflow.local_embedding_source_plan_v3 import LocalEmbeddingSourcePlanV3
from eom_workflow.local_embedding_source_plan_v4 import LocalEmbeddingSourcePlanV4
from jsonschema.exceptions import ValidationError as JsonSchemaError
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from eom_catalog_service.embedding_incremental_plan import (
    RegisteredEmbeddingRow,
    plan_embedding_delta,
)
from eom_catalog_service.embedding_index_assembly import (
    PreparedEmbeddingIndexBasis,
    assemble_embedding_source_binding,
)
from eom_catalog_service.embedding_index_assembly_v2 import (
    PreparedMixedEmbeddingIndexBasis,
    assemble_registered_review_source_binding,
)
from eom_catalog_service.embedding_registry_application import (
    read_pinned_embedding_index,
    validate_registered_embedding_index_manifest,
    validate_registered_embedding_index_read,
)
from eom_catalog_service.embedding_registry_indexing_authority import (
    CatalogIndexingRegistrySourceAuthority,
)
from eom_catalog_service.embedding_registry_ports import (
    AUTHORING_REFERENCE_PURPOSES,
    AuthorizedEmbeddingReadProfile,
    EmbeddingBindingOrigin,
    EmbeddingPopulationTruncated,
    EmbeddingRegistryActor,
    EmbeddingRegistryCaller,
    EmbeddingRegistryError,
    EmbeddingRegistryLookup,
    EmbeddingRegistryRead,
    EmbeddingRegistryServiceCaller,
    MaterializedEmbeddingReadRow,
    PrivateChatContextPreparation,
    ReferenceQueryContextPreparation,
    RegisteredEmbeddingIndexRead,
    ResolvedEmbeddingBindingOrigin,
    ResolvedEmbeddingLookup,
    ResolvedEmbeddingReferences,
    ResolvedEmbeddingRegistration,
    ResolvedPinnedEmbeddingIndex,
    SelectedEmbeddingSources,
    SupportedEmbeddingIndex,
    SupportedEmbeddingRegistrationCommand,
    validate_embedding_registry_actor,
)
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryOwnerConfiguration as EmbeddingRegistryOwnerConfiguration,
)
from eom_catalog_service.embedding_registry_repository import (
    EmbeddingRegistryRepository,
    binding_columns,
    binding_origin,
    registered_row,
)
from eom_catalog_service.evidence_usage_receipts import OrchestratorEvidenceUsageReceiptResolver
from eom_catalog_service.exam_similarity_observation import compose_exam_similarity_observation
from eom_catalog_service.inference_transfer_catalog_adapter import (
    InferenceTransferCorpusReadCommand,
)
from eom_catalog_service.inference_transfer_population_read_set import (
    InferenceTransferPopulationReadSet,
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
from eom_catalog_service.local_embedding_source_plan_v2 import build_local_embedding_source_plan_v2
from eom_catalog_service.local_embedding_source_plan_v3 import (
    build_local_embedding_source_plan_v3,
    build_local_embedding_source_plan_v4,
)
from eom_catalog_service.local_indexing_source_ports import (
    LocalIndexingSourceError,
    LocalIndexingSourceReadIntent,
)
from eom_catalog_service.pinned_artifact_resolution import (
    PinnedArtifactReadContext,
    PinnedArtifactResolutionError,
)
from eom_catalog_service.private_chat_context_preparation import (
    validate_private_chat_context_preparation,
)
from eom_catalog_service.private_chat_document_read import (
    prepare_private_chat_document_scope_in_session,
    read_private_chat_document_index_in_session,
)
from eom_catalog_service.private_chat_similarity_ports import PreparedPrivateChatDocumentScope
from eom_catalog_service.public_solution_capture_ports import CapturedPublicSolutionSources
from eom_catalog_service.public_solution_index_assembly import (
    PreparedPublicSolutionIndexBasis,
    PreparedRegisteredPublicSolutionIndexBasis,
    assemble_public_solution_binding,
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
from eom_catalog_service.similarity_document_read_window import (
    SimilarityDocumentReadWindow as _SimilarityReadWindow,
)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for name, item in pairs:
        if name in value:
            raise ValueError("duplicate immutable JSON key")
        value[name] = item
    return value


def _validate_similarity_manifest(
    selection: SimilarityViewSelection
    | SimilarityViewSelectionV2
    | PublicSolutionSimilarityView
    | PublicSolutionSimilarityViewV4,
    pointer: ArtifactMemberPointer,
    index: SupportedEmbeddingIndex,
) -> None:
    if isinstance(selection, PublicSolutionSimilarityView | PublicSolutionSimilarityViewV4):
        if not isinstance(index, PublicSolutionEmbeddingIndex | PublicSolutionEmbeddingIndexV4) or (
            isinstance(selection, PublicSolutionSimilarityView)
            and not isinstance(index, PublicSolutionEmbeddingIndex)
        ):
            raise ValueError("public similarity requires its exact supported index family")
        pin = selection.index
        if (
            pointer != pin.index_manifest
            or index.index_id != pin.index_id
            or index.index_revision_id != pin.index_revision_id
            or index.index_sha256 != pin.index_sha256
            or index.storage_partition != pin.storage_partition
            or index.space != pin.spaces.document
            or index.view != selection.view
            or index.recipe != selection.recipe
        ):
            raise ValueError("public similarity index pin differs")
        return
    if isinstance(selection, SimilarityViewSelectionV2):
        if not isinstance(index, MixedEmbeddingIndexManifest):
            raise ValueError("similarity request2 requires an actual index2")
    else:
        if not isinstance(index, EmbeddingIndexManifest):
            raise ValueError("similarity request1 cannot reinterpret an index2")
    if not similarity_index_matches_pin(selection, pointer, index):
        raise ValueError("resolved immutable index differs from its view/recipe/space/revision pin")


def _reject_constant(_value: str) -> Any:
    raise ValueError("nonstandard immutable JSON constant")


def _document(payload: bytes) -> dict[str, Any]:
    value = json.loads(payload, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    if not isinstance(value, dict) or canonical_json_bytes(value) != payload:
        raise ValueError("immutable member is not exact canonical JSON")
    return value


_REGISTRATION_TYPES = (
    RegisterEmbeddingIndexCommand,
    RegisterEmbeddingIndexCommandV2,
    RegisterPublicSolutionIndexCommand,
    RegisterPublicSolutionIndexCommandV4,
)


def _decode_index_manifest(schema_ref: str, payload: bytes) -> SupportedEmbeddingIndex:
    if schema_ref not in (
        INDEX_SCHEMA_REF,
        MIXED_EMBEDDING_INDEX_SCHEMA_REF,
        PUBLIC_SOLUTION_INDEX_SCHEMA_REF,
        REGISTERED_PUBLIC_SOLUTION_INDEX_SCHEMA_REF,
    ):
        raise ValueError("foreign index schema")
    index = parse_supported_embedding_index(_document(payload))
    if schema_ref != "eom://schemas/knowledge/" + index.schema_version:
        raise ValueError("index pointer and document schema differ")
    return index


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
        if type(configuration.namespace) not in (
            EmbeddingIndexNamespace,
            MixedEmbeddingIndexNamespace,
            PublicSolutionIndexNamespace,
        ):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_CONFIGURATION_INVALID")
        expected_recipe = (
            PublicSolutionEmbeddingRecipe
            if isinstance(configuration.namespace, PublicSolutionIndexNamespace)
            else ExperimentViewRecipe
        )
        if type(configuration.recipe) is not expected_recipe:
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_CONFIGURATION_INVALID")
        self.configuration = EmbeddingRegistryOwnerConfiguration(
            configuration.corpus_id,
            type(configuration.namespace).model_validate(
                raw_similarity_contract_value(configuration.namespace)
            ),
            EmbeddingSpace.model_validate(configuration.space.model_dump(mode="json")),
            expected_recipe.model_validate(configuration.recipe.model_dump(mode="json")),
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
        self._review_receipts = OrchestratorEvidenceUsageReceiptResolver(self.sessions)
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
        intent: SupportedEmbeddingRegistrationCommand | EmbeddingRegistryLookup,
        *,
        artifact_reader: PinnedArtifactReadContext,
        phase: InferenceTransferSessionCapturePhase,
        source_revision_ids: tuple[str, ...] = (),
        population_read_set: InferenceTransferPopulationReadSet | None = None,
    ) -> (
        InferenceTransferSessionCapture
        | LocalIndexingSessionCapture
        | CapturedPublicSolutionSources
    ):
        validate_embedding_registry_actor(caller)
        if isinstance(caller, EmbeddingRegistryServiceCaller):
            if (
                self._indexing_source_authority is None
                or self._similarity_read_window is not None
                or population_read_set is not None
            ):
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
        options = (
            {} if population_read_set is None else {"population_read_set": population_read_set}
        )
        maximum_page = (
            intent.maximum_sources if isinstance(intent, EmbeddingRegistryLookup) else 1024
        )
        if isinstance(intent.namespace, PublicSolutionIndexNamespace):
            maximum_page = min(1024, maximum_page)
        command = InferenceTransferCorpusReadCommand(
            actor_id=caller.operator_id,
            graph_snapshot=intent.graph_snapshot,
            access_policy_revision_id=intent.policy_revision_id,
            access_policy_sha256=intent.policy_sha256,
            source_classes=self.configuration.source_classes,
            maximum_candidates=maximum_page,
            population_scope=InferenceTransferPopulationScope(intent.namespace.population_scope),
            top_k=1
            if self._similarity_requested_top_k is None
            else self._similarity_requested_top_k,
            source_revision_ids=source_revision_ids,
        )
        if isinstance(self.configuration.namespace, PublicSolutionIndexNamespace):
            # Load registered Workflow provenance only when composing this family.
            # Registry/bootstrap imports must not load the runner execution root.
            from eom_catalog_service.public_solution_source_capture import (
                CatalogPublicSolutionSourceCapture,
            )

            if (
                not isinstance(self.configuration.recipe, PublicSolutionEmbeddingRecipe)
                or population_read_set is not None
            ):
                raise EmbeddingRegistryError("EMBEDDING_REGISTRY_CONFIGURATION_INVALID")
            public_owner = CatalogPublicSolutionSourceCapture(self.engine, self.settings)
            public_owner.sources = self.sources
            if phase is InferenceTransferSessionCapturePhase.AUTHORIZE_SCOPE:
                scope = self.sources.authorize_scope_in_session(
                    session,
                    command,
                    identity_fence=self.identity_fence,
                    artifact_reader=artifact_reader,
                )
                return CapturedPublicSolutionSources((), (), (), scope, None)
            if not source_revision_ids:
                maximum = (
                    MAX_PUBLIC_SOLUTION_SOURCES
                    if isinstance(
                        intent,
                        RegisterPublicSolutionIndexCommand | RegisterPublicSolutionIndexCommandV4,
                    )
                    else intent.maximum_sources
                    if isinstance(intent, EmbeddingRegistryLookup)
                    else 1024
                )
                return public_owner.capture_population_in_session(
                    session,
                    command,
                    self.configuration.recipe,
                    identity_fence=self.identity_fence,
                    artifact_reader=artifact_reader,
                    maximum_population_sources=maximum,
                )
            return public_owner.capture_in_session(
                session,
                command,
                self.configuration.recipe,
                identity_fence=self.identity_fence,
                artifact_reader=artifact_reader,
            )
        if not isinstance(self.configuration.recipe, ExperimentViewRecipe):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_CONFIGURATION_INVALID")
        return self.sources.capture_in_session(
            session,
            command,
            self.configuration.recipe,
            identity_fence=self.identity_fence,
            artifact_reader=artifact_reader,
            phase=phase,
            **options,
        )

    @staticmethod
    def _require_publication_authority(
        caller: EmbeddingRegistryActor,
        capture: InferenceTransferSessionCapture
        | LocalIndexingSessionCapture
        | CapturedPublicSolutionSources,
    ) -> None:
        if isinstance(caller, EmbeddingRegistryServiceCaller):
            if not (
                type(capture) is LocalIndexingSessionCapture
                or (
                    isinstance(capture, CapturedPublicSolutionSources)
                    and type(capture.scope) is LocalIndexingSourceReadIntent
                )
            ):
                raise EmbeddingRegistryError("EMBEDDING_REGISTRY_AUTHORITY_UNAVAILABLE")
        elif not isinstance(
            capture, (InferenceTransferSessionCapture, CapturedPublicSolutionSources)
        ):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_AUTHORITY_UNAVAILABLE")
        else:
            from eom_catalog_service.knowledge_retrieval_service import ReadOnlyCandidatePoolScope

            if not isinstance(capture.scope, ReadOnlyCandidatePoolScope):
                raise EmbeddingRegistryError("EMBEDDING_REGISTRY_AUTHORITY_UNAVAILABLE")
            if "knowledge_graph:publish" not in capture.scope.requester_permission_keys:
                raise EmbeddingRegistryError("EMBEDDING_REGISTRY_FORBIDDEN")

    def _capture(
        self,
        session: Session,
        caller: EmbeddingRegistryActor,
        intent: SupportedEmbeddingRegistrationCommand | EmbeddingRegistryLookup,
        phase: InferenceTransferSessionCapturePhase,
        *,
        source_revision_ids: tuple[str, ...] = (),
        artifact_reader: PinnedArtifactReadContext | None = None,
        population_read_set: InferenceTransferPopulationReadSet | None = None,
    ) -> tuple[
        PinnedArtifactReadContext,
        InferenceTransferSessionCapture
        | LocalIndexingSessionCapture
        | CapturedPublicSolutionSources,
    ]:
        if source_revision_ids and (
            isinstance(intent, _REGISTRATION_TYPES) or self._similarity_read_window is not None
        ):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
        if (
            intent.corpus_id != self.configuration.corpus_id
            or intent.namespace != self.configuration.namespace
        ):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
        window = self._similarity_read_window
        if artifact_reader is not None and (
            not isinstance(artifact_reader, PinnedArtifactReadContext)
            or isinstance(intent, _REGISTRATION_TYPES)
            or self._indexing_source_authority is not None
            or (window is not None and artifact_reader is not window.reader)
        ):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_AUTHORITY_UNAVAILABLE")
        reader = (
            window.reader
            if window is not None
            else artifact_reader
            if artifact_reader is not None
            else PinnedArtifactReadContext(session, self.settings)
        )
        reader.require_session(session)
        if reader.settings != self.settings:
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_AUTHORITY_UNAVAILABLE")
        capture = self._capture_source(
            session,
            caller,
            intent,
            artifact_reader=reader,
            phase=phase if window is None else InferenceTransferSessionCapturePhase.AUTHORIZE_SCOPE,
            source_revision_ids=source_revision_ids
            if window is None
            else window.source_revision_ids,
            population_read_set=population_read_set,
        )
        if artifact_reader is not None and window is None:
            # Immutable bytes may be reused; current Artifact/producer approval may not.
            # This is three indexed metadata reads, not another physical materialization.
            reader.revalidate_provenance()
        if window is not None:
            if (
                isinstance(intent, _REGISTRATION_TYPES)
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
        if isinstance(intent, _REGISTRATION_TYPES):
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

    def _captured_lookup(
        self,
        session: Session,
        caller: EmbeddingRegistryActor,
        intent: SupportedEmbeddingRegistrationCommand | EmbeddingRegistryLookup,
        capture: InferenceTransferSessionCapture
        | LocalIndexingSessionCapture
        | CapturedPublicSolutionSources,
    ) -> ResolvedEmbeddingLookup:
        """Fresh review proof in this exact root; never a legacy read-set cache grant."""
        if capture.corpus is None:
            raise ValueError("embedding capture has no current admitted population")
        sources = tuple(row.source for row in capture.corpus.sources)
        if isinstance(capture, CapturedPublicSolutionSources):
            return ResolvedEmbeddingLookup(
                intent.corpus_id,
                self.configuration.space,
                self.configuration.recipe,
                sources,
                capture.entries,
                capture.corpus.truncated,
                tuple(
                    (row.source.item_revision_id, row.analysis_run_id)
                    for row in capture.corpus.sources
                ),
            )
        if not isinstance(intent.namespace, MixedEmbeddingIndexNamespace):
            return ResolvedEmbeddingLookup(
                intent.corpus_id,
                self.configuration.space,
                self.configuration.recipe,
                sources,
                capture.entries,
                capture.corpus.truncated,
            )
        # This is the runtime composition boundary. Legacy readers do not load
        # the new Workflow provenance adapter during runner package bootstrap.
        from eom_catalog_service.registered_review_embedding_capture import (
            capture_registered_review_embedding_entries,
        )

        if not isinstance(self.configuration.recipe, ExperimentViewRecipe):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_CONFIGURATION_INVALID")

        admitted = {source.item_revision_id: source for source in sources}

        def authorize_source(source: ApprovedItemKnowledgeSourceV2) -> None:
            # The official pool retains exact current source/base rows under shared
            # locks. Full actual actor/service scope is freshly checked pre/post.
            if admitted.get(source.item_revision_id) != source:
                raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")

        self.authorize_scope(session, caller, intent)
        review = capture_registered_review_embedding_entries(
            session,
            admitted_sources=capture.corpus.sources,
            existing_entries=capture.entries,
            graph_snapshot=intent.graph_snapshot,
            recipe=self.configuration.recipe,
            artifacts=self.sources.sources.retrieval.artifacts,
            receipts=self._review_receipts,
            authorize_source=authorize_source,
        )
        self.authorize_scope(session, caller, intent)
        review.assert_current(session)
        return ResolvedEmbeddingLookup(
            intent.corpus_id,
            self.configuration.space,
            self.configuration.recipe,
            sources,
            review.entries,
            capture.corpus.truncated,
            review.base_analysis_run_ids,
        )

    def _read_index_member(
        self, reader: PinnedArtifactReadContext, pointer: ArtifactMemberPointer
    ) -> bytes:
        """Same physical/provenance closure for selected indices and immutable origins."""
        pointer = ArtifactMemberPointer.model_validate(pointer.model_dump(mode="json"))
        if (
            pointer.schema_ref
            not in (
                INDEX_SCHEMA_REF,
                MIXED_EMBEDDING_INDEX_SCHEMA_REF,
                PUBLIC_SOLUTION_INDEX_SCHEMA_REF,
                REGISTERED_PUBLIC_SOLUTION_INDEX_SCHEMA_REF,
            )
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
        return raw.payload

    def _read_index(
        self, reader: PinnedArtifactReadContext, pointer: ArtifactMemberPointer
    ) -> SupportedEmbeddingIndex:
        # Resolution and file-set checks remain current; only the immutable
        # interpretation is reused inside this reader's root transaction.
        raw = self._read_index_member(reader, pointer)
        return reader.read_model_member(
            pointer, expected_bytes=len(raw), decoder=_decode_index_manifest
        )

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
        self,
        request: SupportedSimilarityContextRequest,
        selection: SimilarityViewSelection | SimilarityViewSelectionV2,
    ) -> CatalogEmbeddingRegistryVerifier:
        if (
            request.consumer_purpose not in AUTHORING_REFERENCE_PURPOSES
            or request.anchor.source.source_class != "PAST_EXAM"
            or request.topics
            or request.unit_ids
            or isinstance(request, SimilarityContextRequestV2)
            != isinstance(self.configuration.namespace, MixedEmbeddingIndexNamespace)
        ):
            raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
        return self._document_view_owner(request.source_classes, selection, request.top_k)

    def _document_view_owner(
        self,
        source_classes: tuple[Literal["APPROVED_ITEM", "PAST_EXAM"], ...],
        selection: SimilarityViewSelection | SimilarityViewSelectionV2,
        top_k: int,
    ) -> CatalogEmbeddingRegistryVerifier:
        """Shared document owner configuration, not consumer or read authorization."""
        config = self.configuration
        if (
            not set(source_classes).issubset(config.source_classes)
            or selection.recipe != config.recipe
            or (selection.index is not None and selection.index.spaces.document != config.space)
        ):
            raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
        namespace = type(config.namespace).model_validate(
            config.namespace.model_dump(mode="json") | {"view": selection.view}
        )
        owner = CatalogEmbeddingRegistryVerifier(
            self.engine,
            EmbeddingRegistryOwnerConfiguration(
                config.corpus_id, namespace, config.space, config.recipe, source_classes
            ),
            identity_fence=self.identity_fence,
            settings=self.settings,
        )
        # One real source owner, not three independently captured authority providers.
        owner.sources = self.sources
        owner._similarity_requested_top_k = top_k
        return owner

    def _similarity_capture(
        self,
        session: Session,
        caller: EmbeddingRegistryActor,
        request: SupportedSimilarityContextRequest,
        *,
        source_revision_ids: tuple[str, ...] = (),
        artifact_reader: PinnedArtifactReadContext | None = None,
        population_read_set: InferenceTransferPopulationReadSet | None = None,
    ) -> tuple[
        CatalogEmbeddingRegistryVerifier,
        PinnedArtifactReadContext,
        InferenceTransferSessionCapture,
        ResolvedEmbeddingLookup | None,
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
        if population_read_set is not None:
            if artifact_reader is None or type(caller) is not EmbeddingRegistryCaller:
                raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
            population_read_set.require_request(
                session, caller.operator_id, request.request_sha256, artifact_reader
            )
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
                artifact_reader=artifact_reader,
                population_read_set=population_read_set,
            )
        )
        if not isinstance(capture, InferenceTransferSessionCapture):
            raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
        resolved = (
            owner._captured_lookup(session, caller, scope, capture)
            if isinstance(request, SimilarityContextRequestV2)
            else None
        )
        return owner, reader, capture, resolved

    @staticmethod
    def _prepared_document_sources(
        capture: InferenceTransferSessionCapture,
        resolved: ResolvedEmbeddingLookup | None = None,
    ) -> tuple[PreparedSimilaritySource, ...]:
        if capture.corpus is None:
            raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
        entries = {
            embedding_entry_source(entry).item_revision_id: entry
            for entry in (capture.entries if resolved is None else resolved.entries)
        }
        values = []
        for value in sorted(
            capture.corpus.sources, key=lambda value: value.source.item_revision_id
        ):
            entry = entries.get(value.source.item_revision_id)
            if isinstance(
                entry, PublicSolutionEmbeddingEntry | RegisteredPublicSolutionEmbeddingEntry
            ):
                raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
            values.append(
                PreparedSimilaritySource(
                    source=value.source,
                    profile=None
                    if entry is None
                    else (
                        RegisteredReviewProfilePointer.from_profile(entry.profile)
                        if isinstance(entry, RegisteredReviewEmbeddingEntry)
                        else InferenceTransferProfilePointer.from_profile(entry.profile)
                    ),
                    solution_evidence=None
                    if entry is None or isinstance(entry, RegisteredReviewEmbeddingEntry)
                    else entry.profile.source_basis.solution_evidence,
                    review_evidence=entry.profile.source_basis.review_evidence
                    if isinstance(entry, RegisteredReviewEmbeddingEntry)
                    else None,
                )
            )
        return tuple(values)

    @staticmethod
    def _prepare_similarity_capture(
        request: SupportedSimilarityContextRequest,
        capture: InferenceTransferSessionCapture,
        resolved: ResolvedEmbeddingLookup | None = None,
    ) -> PreparedSimilarityContext:
        if capture.corpus is None:
            raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
        values = CatalogEmbeddingRegistryVerifier._prepared_document_sources(capture, resolved)
        anchor = next(
            (
                entry
                for entry in (capture.entries if resolved is None else resolved.entries)
                if embedding_entry_source(entry).item_revision_id
                == request.anchor.source.item_revision_id
            ),
            None,
        )
        texts = []
        if anchor is not None:
            if not isinstance(anchor, StagedExperimentEntry):
                raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
            for selection in request.views:
                text = experiment_view_text(anchor, selection.view)
                if text is not None and text.strip():
                    texts.append((selection.view, text))
        return PreparedSimilarityContext(
            request.request_sha256,
            values,
            tuple(texts),
            capture.corpus.graph_scores,
            truncated=capture.corpus.truncated,
        )

    def prepare_similarity_context(
        self, caller: EmbeddingRegistryActor, request: SupportedSimilarityContextRequest
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
        request: SupportedSimilarityContextRequest,
        *,
        artifact_reader: PinnedArtifactReadContext | None = None,
        population_read_set: InferenceTransferPopulationReadSet | None = None,
    ) -> PreparedSimilarityContext:
        """Preserve the current native owner's root; never open or commit another root."""
        self._require_similarity_root(session)
        request = parse_supported_similarity_context_request(request)
        try:
            with session.no_autoflush:
                _owner, _reader, capture, resolved = self._similarity_capture(
                    session,
                    caller,
                    request,
                    artifact_reader=artifact_reader,
                    population_read_set=population_read_set,
                )
                return self._prepare_similarity_capture(request, capture, resolved)
        except EmbeddingRegistryError as error:
            raise similarity_context_error_from_registry(error) from None

    def create_similarity_population_read_set_in_session(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        request: SupportedSimilarityContextRequest,
        *,
        artifact_reader: PinnedArtifactReadContext,
    ) -> InferenceTransferPopulationReadSet:
        """Bind empty read-local validation state; never admit or cache permission."""
        self._require_similarity_root(session)
        request = parse_supported_similarity_context_request(request)
        if (
            type(caller) is not EmbeddingRegistryCaller
            or self.identity_fence is None
            or self._indexing_source_authority is not None
            or artifact_reader.settings != self.settings
            or session.new
            or session.dirty
            or session.deleted
        ):
            raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
        artifact_reader.require_session(session)
        self._similarity_view_owner(request, request.views[0])
        return InferenceTransferPopulationReadSet(
            session,
            artifact_reader,
            operator_id=caller.operator_id,
            request_sha256=request.request_sha256,
        )

    def read_similarity_views(
        self,
        caller: EmbeddingRegistryActor,
        request: SupportedSimilarityContextRequest,
        prepared: PreparedSimilarityContext,
    ) -> tuple[ResolvedPinnedEmbeddingIndex, ...]:
        """Bounded views share one read window; full start/end capture is actual authority."""
        with self.sessions() as session, session.begin():
            return self.read_similarity_views_in_session(session, caller, request, prepared)

    def read_similarity_views_in_session(
        self,
        session: Session,
        caller: EmbeddingRegistryActor,
        request: SupportedSimilarityContextRequest,
        prepared: PreparedSimilarityContext,
        *,
        artifact_reader: PinnedArtifactReadContext | None = None,
        population_read_set: InferenceTransferPopulationReadSet | None = None,
    ) -> tuple[ResolvedPinnedEmbeddingIndex, ...]:
        """Same checked read window in a caller root, with fresh start/end source fences."""
        self._require_similarity_root(session)
        request = parse_supported_similarity_context_request(request)
        try:
            with session.no_autoflush:
                _owner, reader, capture, resolved = self._similarity_capture(
                    session,
                    caller,
                    request,
                    artifact_reader=artifact_reader,
                    population_read_set=population_read_set,
                )
                if self._prepare_similarity_capture(request, capture, resolved) != prepared:
                    raise SimilarityContextReadError("SOURCE_REVOKED")
                window = _SimilarityReadWindow(
                    session,
                    session.get_transaction(),
                    caller,
                    reader,
                    capture,
                    population_read_set=population_read_set,
                )
                return self._read_similarity_views_in_window(request, prepared, window)
        except EmbeddingRegistryError as error:
            raise similarity_context_error_from_registry(error) from None

    def prepare_and_read_similarity_context_in_session(
        self,
        session: Session,
        caller: EmbeddingRegistryActor,
        request: SupportedSimilarityContextRequest,
    ) -> tuple[PreparedSimilarityContext, tuple[ResolvedPinnedEmbeddingIndex, ...]]:
        """Prepare at the read's start; retain full start/end fences in this same root."""
        return self._prepare_and_read_similarity_scope(session, caller, request, ())

    def prepare_reference_query_anchor_in_session(
        self,
        session: Session,
        caller: EmbeddingRegistryActor,
        request: SupportedSimilarityContextRequest,
        *,
        artifact_reader: PinnedArtifactReadContext | None = None,
    ) -> PreparedSimilarityContext:
        """Validate QUERY's exact anchor and pinned indexes, never population coverage."""
        self._require_similarity_root(session)
        request = parse_supported_similarity_context_request(request)
        prepared, _reads = self._prepare_and_read_similarity_scope(
            session,
            caller,
            request,
            (request.anchor.source.item_revision_id,),
            artifact_reader=artifact_reader,
        )
        if len(prepared.sources) != 1 or prepared.truncated:
            raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
        return prepared

    def _prepare_and_read_similarity_scope(
        self,
        session: Session,
        caller: EmbeddingRegistryActor,
        request: SupportedSimilarityContextRequest,
        source_revision_ids: tuple[str, ...],
        *,
        artifact_reader: PinnedArtifactReadContext | None = None,
    ) -> tuple[PreparedSimilarityContext, tuple[ResolvedPinnedEmbeddingIndex, ...]]:
        self._require_similarity_root(session)
        request = parse_supported_similarity_context_request(request)
        try:
            with session.no_autoflush:
                _owner, reader, capture, resolved = self._similarity_capture(
                    session,
                    caller,
                    request,
                    source_revision_ids=source_revision_ids,
                    artifact_reader=artifact_reader,
                )
                prepared = self._prepare_similarity_capture(request, capture, resolved)
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
        request: SupportedSimilarityContextRequest,
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
            results.append(owner._read_document_index_in_window(window, scope, selection))
        # READ COMMITTED or shared Session is not immutable source membership.
        # Re-resolve every source/report in this exact scope before returning.
        # Only QUERY input preparation is anchor-scoped; ranking remains full-population.
        _owner, _reader, final, resolved = self._similarity_capture(
            session,
            caller,
            request,
            source_revision_ids=window.source_revision_ids,
            artifact_reader=window.reader,
            population_read_set=window.population_read_set,
        )
        if self._prepare_similarity_capture(request, final, resolved) != prepared:
            raise SimilarityContextReadError("SOURCE_REVOKED")
        return tuple(results)

    def _read_document_index_in_window(
        self,
        window: _SimilarityReadWindow,
        scope: EmbeddingRegistryLookup,
        selection: SimilarityViewSelection | SimilarityViewSelectionV2,
    ) -> ResolvedPinnedEmbeddingIndex:
        self._similarity_read_window = window
        try:
            return read_pinned_embedding_index(
                window.session, window.caller, EmbeddingRegistryRead(scope, selection), self
            )
        except EmbeddingRegistryError as error:
            if error.code in {
                "EMBEDDING_REGISTRY_FORBIDDEN",
                "EMBEDDING_REGISTRY_AUTHORITY_UNAVAILABLE",
            }:
                raise similarity_context_error_from_registry(error) from None
            raise SimilarityContextReadError("INDEX_POINTER_INVALID") from None

    def observe_exam_similarity_in_session(
        self,
        session: Session,
        caller: EmbeddingRegistryActor,
        request: ExamObservationRequest,
    ) -> ExamSimilarityObservation:
        """Exact25 current sources, shared pinned DOCUMENT reads, then fresh end fence."""
        self._require_similarity_root(session)
        root = session.get_transaction()
        request = parse_exam_observation_request(request)
        if (
            type(caller) is not EmbeddingRegistryCaller
            or self._indexing_source_authority is not None
        ):
            raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
        owners = tuple(
            self._document_view_owner(request.source_classes, selection, 25)
            for selection in request.views
        )
        source_ids = tuple(sorted(member.item_revision_id for member in request.cohort.members))
        first = self._document_view_owner(request.source_classes, request.views[0], 25)
        source_reader = PinnedArtifactReadContext(session, self.settings)
        scope = EmbeddingRegistryLookup(
            first.configuration.corpus_id,
            first.configuration.namespace,
            request.graph_snapshot,
            request.policy_revision_id,
            request.policy_sha256,
            25,
        )

        def capture_current() -> tuple[PinnedArtifactReadContext, InferenceTransferSessionCapture]:
            self._require_similarity_root(session)
            if session.get_transaction() is not root:
                raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
            reader, capture = first._guard(
                lambda: first._capture(
                    session,
                    caller,
                    scope,
                    InferenceTransferSessionCapturePhase.CAPTURE_POPULATION,
                    source_revision_ids=source_ids,
                    artifact_reader=source_reader,
                )
            )
            self._require_similarity_root(session)
            if session.get_transaction() is not root:
                raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
            if (
                not isinstance(capture, InferenceTransferSessionCapture)
                or capture.corpus is None
                or capture.corpus.truncated
            ):
                raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
            return reader, capture

        try:
            with session.no_autoflush:
                reader, capture = capture_current()
                prepared = self._prepared_document_sources(capture)
                if tuple(value.source.item_revision_id for value in prepared) != source_ids:
                    raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
                window = _SimilarityReadWindow(
                    session, session.get_transaction(), caller, reader, capture, source_ids
                )
                reads = tuple(
                    owner._read_document_index_in_window(
                        window,
                        EmbeddingRegistryLookup(
                            scope.corpus_id,
                            owner.configuration.namespace,
                            request.graph_snapshot,
                            request.policy_revision_id,
                            request.policy_sha256,
                            25,
                        ),
                        selection,
                    )
                    for owner, selection in zip(owners, request.views, strict=True)
                    if selection.index is not None
                )
                result = compose_exam_similarity_observation(request, prepared, reads)
                # first is a dedicated capture owner, never a window-reuse owner.
                # A changed full cohort/report cannot survive the final current read.
                _reader, final = capture_current()
                if self._prepared_document_sources(final) != prepared:
                    raise SimilarityContextReadError("SOURCE_REVOKED")
                return result
        except EmbeddingRegistryError as error:
            raise similarity_context_error_from_registry(error) from None

    def reauthorize_similarity_context(
        self,
        caller: EmbeddingRegistryActor,
        request: SupportedSimilarityContextRequest,
        prepared: PreparedSimilarityContext,
    ) -> None:
        """Fresh full-population check after QUERY/ranking, never a persisted grant."""
        current = self.prepare_similarity_context(caller, request)
        if current != prepared:
            raise SimilarityContextReadError("SOURCE_REVOKED")

    def prepare_private_chat_document_scope_in_session(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        request: PrivateChatSimilarityRequest,
        *,
        artifact_reader: PinnedArtifactReadContext | None = None,
    ) -> PreparedPrivateChatDocumentScope:
        return prepare_private_chat_document_scope_in_session(
            self, session, caller, request, artifact_reader=artifact_reader
        )

    def read_private_chat_document_index_in_session(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        request: PrivateChatSimilarityRequest,
        prepared: PreparedPrivateChatDocumentScope,
        *,
        artifact_reader: PinnedArtifactReadContext | None = None,
    ) -> tuple[ResolvedPinnedEmbeddingIndex, ...]:
        return read_private_chat_document_index_in_session(
            self, session, caller, request, prepared, artifact_reader=artifact_reader
        )

    def authorize_scope(
        self,
        session: Session,
        caller: EmbeddingRegistryActor,
        intent: SupportedEmbeddingRegistrationCommand | EmbeddingRegistryLookup,
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
            if error.code == "INFERENCE_TRANSFER_SNAPSHOT_POPULATION_TRUNCATED":
                raise EmbeddingPopulationTruncated() from None
            code = (
                "EMBEDDING_REGISTRY_FORBIDDEN"
                if error.code == "INFERENCE_TRANSFER_FORBIDDEN"
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
        command: SupportedEmbeddingRegistrationCommand,
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
            current = self._captured_lookup(session, caller, command, capture)
            sources = tuple(sorted(current.sources, key=lambda value: value.item_revision_id))
            return ResolvedEmbeddingRegistration(
                command.corpus_id,
                index,
                shards,
                previous,
                sources,
                current.entries,
                current.truncated,
                current.base_analysis_run_ids,
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
        command: SupportedEmbeddingRegistrationCommand,
        index: SupportedEmbeddingIndex,
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
            checked = parse_supported_embedding_index(index)
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
            current = self._captured_lookup(session, caller, command, capture)
            return ResolvedEmbeddingRegistration(
                command.corpus_id,
                checked,
                shards,
                previous,
                tuple(sorted(current.sources, key=lambda s: s.item_revision_id)),
                current.entries,
                current.truncated,
                current.base_analysis_run_ids,
            )

        return self._guard(resolve)

    def resolve_optional_index_publication(
        self,
        session: Session,
        caller: EmbeddingRegistryActor,
        command: SupportedEmbeddingRegistrationCommand,
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
            return self._captured_lookup(session, caller, query, capture)

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
            return self._captured_lookup(session, caller, selection.scope, capture)

        return self._guard(resolve)

    def prepare_reference_query_context_in_session(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        preparation: ReferenceQueryContextPreparation,
    ) -> SupportedSimilarityContextRequest:
        """Pin initial reference/report/current-view indexes, never reselect on replay.

        The caller first selects a real initial request; stored QUERY requests are
        the replay source. No vector read/encode, source grant, commit or queue.
        """
        self._require_similarity_root(session)

        def resolve() -> SupportedSimilarityContextRequest:
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
                if not isinstance(entry, StagedExperimentEntry):
                    raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
                if isinstance(scope.namespace, MixedEmbeddingIndexNamespace):
                    validate_local_embedding_entry_source_v2(
                        source,
                        entry,
                        graph_snapshot=scope.graph_snapshot,
                        projection_version=scope.namespace.projection_version,
                    )
                else:
                    validate_local_embedding_entry_source(
                        source,
                        entry,
                        graph_snapshot=scope.graph_snapshot,
                        projection_version=scope.namespace.projection_version,
                    )
            reader = PinnedArtifactReadContext.for_session(session, self.settings)
            views = self._initial_similarity_views(
                session, scope, spaces, preparation.views, reader
            )
            body = {
                "schema_version": "system-rag-similarity-request/2.0"
                if isinstance(scope.namespace, MixedEmbeddingIndexNamespace)
                else "system-rag-similarity-request/1.0",
                "request_id": preparation.request_id,
                "consumer_purpose": preparation.consumer_purpose,
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
                "views": [view.model_dump(mode="json") for view in views],
                "vector_mode": preparation.vector_mode,
                "maximum_sources": scope.maximum_sources,
                "top_k": preparation.top_k,
            }
            request = parse_supported_similarity_context_request(
                body | {"request_sha256": content_sha256(body)}
            )
            validate_reference_query_context_preparation(preparation, config, request)
            # Reauthorize the exact anchor after bytes, not a second mutable-head selection.
            if self.resolve_selected_sources(session, caller, selection) != captured:
                raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
            return request

        return self._guard(resolve)

    def for_pinned_similarity_request_in_session(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        request: SupportedSimilarityContextRequest,
        *,
        artifact_reader: PinnedArtifactReadContext | None = None,
    ) -> CatalogEmbeddingRegistryVerifier:
        """Resolve stored exact view pins without changing the initial namespace.

        This is read-local selection, never permission, current-head discovery or
        a mutation of the installed owner. The original Workflow/request owner
        supplies the pinned request; subsequent reads retain every source fence.
        """
        self._require_similarity_root(session)

        def resolve() -> CatalogEmbeddingRegistryVerifier:
            if (
                type(caller) is not EmbeddingRegistryCaller
                or self.identity_fence is None
                or self._indexing_source_authority is not None
                or self._similarity_read_window is not None
                or session.get_bind() is not self.engine
            ):
                raise EmbeddingRegistryError("EMBEDDING_REGISTRY_AUTHORITY_UNAVAILABLE")
            checked = parse_supported_similarity_context_request(request)
            config = self.configuration
            if not set(checked.source_classes).issubset(config.source_classes):
                raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
            lookup = EmbeddingRegistryLookup(
                config.corpus_id,
                config.namespace,
                checked.graph_snapshot,
                checked.policy_revision_id,
                checked.policy_sha256,
                checked.maximum_sources,
            )
            # A retained PAST-only request does not borrow the configured mixed
            # owner's wider class scope merely to select its exact old pins.
            self._document_view_owner(
                checked.source_classes, checked.views[0], checked.top_k
            ).authorize_scope(session, caller, lookup)
            selections = tuple(value for value in checked.views if value.index is not None)
            if not selections:
                if (
                    isinstance(checked, SimilarityContextRequestV2)
                    != isinstance(config.namespace, MixedEmbeddingIndexNamespace)
                    or checked.source_classes != config.source_classes
                ):
                    raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
                return self
            identities = tuple(
                (value.index.index_id, value.index.index_revision_id)
                for value in selections
                if value.index is not None
            )
            registered = EmbeddingRegistryRepository(session).read_pinned_revisions(identities)
            if set(registered) != set(identities):
                raise EmbeddingRegistryError("EMBEDDING_REGISTRY_POINTER_INVALID")
            reader = (
                PinnedArtifactReadContext.for_session(session, self.settings)
                if artifact_reader is None
                else artifact_reader
            )
            reader.require_session(session)
            if reader.settings != self.settings:
                raise EmbeddingRegistryError("EMBEDDING_REGISTRY_AUTHORITY_UNAVAILABLE")
            selected_namespace: EmbeddingIndexNamespace | MixedEmbeddingIndexNamespace | None = None
            for selection in selections:
                pin = selection.index
                assert pin is not None
                value = registered[(pin.index_id, pin.index_revision_id)]
                namespace_type = (
                    MixedEmbeddingIndexNamespace
                    if isinstance(checked, SimilarityContextRequestV2)
                    else EmbeddingIndexNamespace
                )
                namespace = namespace_type.model_validate(value.namespace.model_dump(mode="json"))
                expected = config.namespace.model_dump(mode="json") | {
                    "view": selection.view,
                    "population_scope": namespace.population_scope,
                    "projection_version": namespace.projection_version,
                }
                if namespace.model_dump(mode="json") != expected or (
                    namespace.population_scope != config.namespace.population_scope
                    and (
                        config.namespace.population_scope != "ALL_ADMITTED_GRAPH_ITEMS"
                        or namespace.population_scope != "OCCURRENCE_BACKED_PAST_EXAM"
                        or checked.source_classes != ("PAST_EXAM",)
                    )
                ):
                    raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
                if isinstance(namespace, MixedEmbeddingIndexNamespace) and not isinstance(
                    config.namespace, MixedEmbeddingIndexNamespace
                ):
                    raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
                normalized = namespace_type.model_validate(
                    namespace.model_dump(mode="json") | {"view": config.namespace.view}
                )
                if selected_namespace is not None and selected_namespace != normalized:
                    raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
                selected_namespace = normalized
                intent = EmbeddingRegistryRead(
                    EmbeddingRegistryLookup(
                        config.corpus_id,
                        namespace,
                        checked.graph_snapshot,
                        checked.policy_revision_id,
                        checked.policy_sha256,
                        checked.maximum_sources,
                    ),
                    selection,
                )
                validate_registered_embedding_index_read(intent, value)
            reader.prefetch(
                tuple(
                    (value.index_manifest.artifact_id, value.index_manifest.artifact_revision_id)
                    for value in registered.values()
                )
            )
            for selection in selections:
                pin = selection.index
                assert pin is not None
                value = registered[(pin.index_id, pin.index_revision_id)]
                index = self._read_index(reader, value.index_manifest)
                _validate_similarity_manifest(selection, value.index_manifest, index)
                validate_registered_embedding_index_manifest(value, index)
                if index.space != config.space or index.recipe != config.recipe:
                    raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
            assert selected_namespace is not None
            owner = self
            if (
                selected_namespace != config.namespace
                or checked.source_classes != config.source_classes
            ):
                owner = CatalogEmbeddingRegistryVerifier(
                    self.engine,
                    EmbeddingRegistryOwnerConfiguration(
                        config.corpus_id,
                        selected_namespace,
                        config.space,
                        config.recipe,
                        checked.source_classes,
                    ),
                    identity_fence=self.identity_fence,
                    settings=self.settings,
                )
                owner.sources = self.sources
            owner.authorize_scope(
                session,
                caller,
                EmbeddingRegistryLookup(
                    config.corpus_id,
                    selected_namespace,
                    checked.graph_snapshot,
                    checked.policy_revision_id,
                    checked.policy_sha256,
                    checked.maximum_sources,
                ),
            )
            reader.revalidate_provenance()
            return owner

        return self._guard(resolve)

    def _initial_similarity_views(
        self,
        session: Session,
        scope: EmbeddingRegistryLookup,
        spaces: ReferenceQuerySpaces,
        views: tuple[ExperimentView, ...],
        reader: PinnedArtifactReadContext,
    ) -> tuple[SimilarityViewSelection | SimilarityViewSelectionV2, ...]:
        """One current-head capture for initial reference/private intents, not replay."""
        repository = EmbeddingRegistryRepository(session)
        if not isinstance(self.configuration.recipe, ExperimentViewRecipe):
            raise ValueError("legacy similarity request requires its released recipe family")
        selected_views = []
        for view in views:
            namespace = type(scope.namespace).model_validate(
                scope.namespace.model_dump(mode="json") | {"view": view}
            )
            current = repository.current_namespace_revision(scope.corpus_id, namespace)
            selection_type = (
                SimilarityViewSelectionV2
                if isinstance(namespace, MixedEmbeddingIndexNamespace)
                else SimilarityViewSelection
            )
            pin_type = (
                SimilarityIndexPinV2
                if isinstance(namespace, MixedEmbeddingIndexNamespace)
                else SimilarityIndexPin
            )
            selected = selection_type(view=view, recipe=self.configuration.recipe, index=None)
            if current is not None:
                registered, _version = current
                pin_value = pin_type(
                    index_id=registered.index_id,
                    index_revision_id=registered.index_revision_id,
                    index_manifest=registered.index_manifest,
                    index_sha256=registered.index_sha256,
                    storage_partition=namespace.storage_partition,
                    spaces=spaces,
                )
                selected = selection_type.model_validate(
                    {
                        "view": view,
                        "recipe": self.configuration.recipe,
                        "index": pin_value,
                    }
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
                _validate_similarity_manifest(selected, registered.index_manifest, manifest)
                validate_registered_embedding_index_manifest(registered, manifest)
            selected_views.append(selected)
        return tuple(selected_views)

    def prepare_private_chat_context_in_session(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        preparation: PrivateChatContextPreparation,
    ) -> PrivateChatSimilarityRequest:
        """Initial official index pins for an owned question; no invented Item or native run."""
        self._require_similarity_root(session)

        def resolve() -> PrivateChatSimilarityRequest:
            if (
                type(caller) is not EmbeddingRegistryCaller
                or type(preparation) is not PrivateChatContextPreparation
                or session.get_bind() is not self.engine
                or self._indexing_source_authority is not None
            ):
                raise EmbeddingRegistryError("EMBEDDING_REGISTRY_AUTHORITY_UNAVAILABLE")
            validate_private_chat_context_preparation(preparation, self.configuration)
            scope = preparation.scope
            self.authorize_scope(session, caller, scope)
            reader = PinnedArtifactReadContext(session, self.settings)
            views = self._initial_similarity_views(
                session, scope, preparation.spaces, ("CONTENT_ONLY",), reader
            )
            body = {
                "schema_version": "system-rag-private-chat-similarity-request/1.0",
                "request_id": preparation.request_id,
                "consumer_purpose": "GENERAL_CHAT_READ",
                "query_basis": preparation.query_basis.model_dump(mode="json"),
                "graph_snapshot": scope.graph_snapshot.model_dump(mode="json"),
                "policy_revision_id": scope.policy_revision_id,
                "policy_sha256": scope.policy_sha256,
                "source_classes": list(self.configuration.source_classes),
                "views": [view.model_dump(mode="json") for view in views],
                "vector_mode": "REQUIRED",
                "maximum_sources": scope.maximum_sources,
                "top_k": preparation.top_k,
            }
            request = PrivateChatSimilarityRequest.model_validate(
                body | {"request_sha256": content_sha256(body)}
            )
            validate_private_chat_context_preparation(preparation, self.configuration, request)
            self.authorize_scope(session, caller, scope)
            reader.revalidate_provenance()
            self._require_similarity_root(session)
            return request

        return self._guard(resolve)

    @overload
    def read_similarity_materials_in_session(
        self, session: Session, caller: EmbeddingRegistryCaller, context: SimilarityContext
    ) -> SimilarityReferenceMaterials: ...

    @overload
    def read_similarity_materials_in_session(
        self, session: Session, caller: EmbeddingRegistryCaller, context: SimilarityContextV2
    ) -> SimilarityReferenceMaterialsV2: ...

    def read_similarity_materials_in_session(
        self, session: Session, caller: EmbeddingRegistryCaller, context: SupportedSimilarityContext
    ) -> SimilarityReferenceMaterials | SimilarityReferenceMaterialsV2:
        """Selected official projections; caller separately verifies QUERY/context provenance."""
        self._require_similarity_root(session)
        context = parse_supported_similarity_context(context)
        request = context.request
        if isinstance(context, SimilarityContextV2):
            validate_deliverable_similarity_context_v2(context, expected_request=context.request)
        else:
            validate_deliverable_similarity_context(context, expected_request=context.request)
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
                return (
                    build_similarity_materials_v2(context, anchor_profile=None, entries=())
                    if isinstance(context, SimilarityContextV2)
                    else build_similarity_materials(context, anchor_profile=None, entries=())
                )
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
                embedding_entry_source(entry).item_revision_id: entry for entry in resolved.entries
            }
            if len(entries) != len(resolved.entries) or set(entries) != targets:
                raise ValueError("selected reference projections differ")
            if any(
                isinstance(
                    entry, PublicSolutionEmbeddingEntry | RegisteredPublicSolutionEmbeddingEntry
                )
                for entry in entries.values()
            ):
                raise ValueError("legacy materials cannot reinterpret a public-solution entry")
            anchor_entry = entries.get(request.anchor.source.item_revision_id)
            if anchor_entry is not None and not isinstance(anchor_entry, StagedExperimentEntry):
                raise ValueError("reference QUERY anchor cannot borrow a registered-review profile")
            if isinstance(context, SimilarityContextV2):
                return build_similarity_materials_v2(
                    context,
                    anchor_profile=None
                    if request.anchor.profile is None or anchor_entry is None
                    else anchor_entry.profile,
                    entries=tuple(
                        entry
                        for row in context.candidates
                        if isinstance(
                            (entry := entries[row.source.item_revision_id]),
                            (StagedExperimentEntry, RegisteredReviewEmbeddingEntry),
                        )
                    ),
                )
            if any(not isinstance(entry, StagedExperimentEntry) for entry in entries.values()):
                raise ValueError("materials1 cannot reinterpret registered-review entries")
            return build_similarity_materials(
                context,
                anchor_profile=None
                if request.anchor.profile is None
                else anchor_entry.profile
                if anchor_entry is not None
                else None,
                entries=tuple(
                    entry
                    for row in context.candidates
                    if isinstance(
                        (entry := entries[row.source.item_revision_id]), StagedExperimentEntry
                    )
                ),
            )
        except EmbeddingRegistryError as error:
            raise similarity_context_error_from_registry(error) from None
        except (ValueError, TypeError, JsonSchemaError):
            raise SimilarityContextReadError("SOURCE_POINTER_INVALID") from None

    def _namespace_predecessor(
        self,
        reader: PinnedArtifactReadContext,
        repository: EmbeddingRegistryRepository,
        query: EmbeddingRegistryLookup,
    ) -> tuple[tuple[ArtifactMemberPointer, SupportedEmbeddingIndex] | None, int]:
        selected = repository.current_namespace_revision(query.corpus_id, query.namespace)
        if selected is None:
            return None, 1
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
        return (registered.index_manifest, index), version

    def resolve_indexing_namespace_predecessor(
        self, session: Session, caller: EmbeddingRegistryActor, query: EmbeddingRegistryLookup
    ) -> tuple[ArtifactMemberPointer, SupportedEmbeddingIndex] | None:
        """Service-only current head capture; not a public source-content read.

        Reuse the caller's current-root source capture for membership planning;
        this operation rechecks authority but does not project the corpus again.
        Select one namespace head, pin it, and read its exact canonical member.
        Absence is distinct from dangling/corrupt/retired Artifact provenance.
        """

        def resolve() -> tuple[ArtifactMemberPointer, SupportedEmbeddingIndex] | None:
            if (
                type(caller) is not EmbeddingRegistryServiceCaller
                or self._indexing_source_authority is None
            ):
                raise EmbeddingRegistryError("EMBEDDING_REGISTRY_FORBIDDEN")
            reader, _capture = self._capture(
                session, caller, query, InferenceTransferSessionCapturePhase.AUTHORIZE_SCOPE
            )
            previous, _version = self._namespace_predecessor(
                reader, EmbeddingRegistryRepository(session), query
            )
            self.authorize_scope(session, caller, query)
            return previous

        return self._guard(resolve)

    def prepare_index_basis(
        self, session: Session, caller: EmbeddingRegistryActor, query: EmbeddingRegistryLookup
    ) -> PreparedEmbeddingIndexBasis:
        """The released plan1 boundary never silently accepts a mixed namespace."""
        if not isinstance(query.namespace, EmbeddingIndexNamespace):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
        basis = self._prepare_index_basis(session, caller, query)
        if not isinstance(basis, PreparedEmbeddingIndexBasis):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
        return basis

    def prepare_mixed_index_basis(
        self, session: Session, caller: EmbeddingRegistryActor, query: EmbeddingRegistryLookup
    ) -> PreparedMixedEmbeddingIndexBasis:
        """Explicit plan2 route; old binding bytes and exact numeric rows stay reusable."""
        if not isinstance(query.namespace, MixedEmbeddingIndexNamespace):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
        basis = self._prepare_index_basis(session, caller, query)
        if not isinstance(basis, PreparedMixedEmbeddingIndexBasis):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
        return basis

    def prepare_public_index_basis(
        self, session: Session, caller: EmbeddingRegistryActor, query: EmbeddingRegistryLookup
    ) -> PreparedPublicSolutionIndexBasis:
        if not isinstance(query.namespace, PublicSolutionIndexNamespace):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
        basis = self._prepare_index_basis(session, caller, query)
        if not isinstance(basis, PreparedPublicSolutionIndexBasis):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
        return basis

    def prepare_registered_public_index_basis(
        self, session: Session, caller: EmbeddingRegistryActor, query: EmbeddingRegistryLookup
    ) -> PreparedRegisteredPublicSolutionIndexBasis:
        if not isinstance(query.namespace, PublicSolutionIndexNamespace):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
        basis = self._prepare_index_basis(session, caller, query, public_metadata_version="4.0")
        if not isinstance(basis, PreparedRegisteredPublicSolutionIndexBasis):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
        return basis

    def _prepare_index_basis(
        self,
        session: Session,
        caller: EmbeddingRegistryActor,
        query: EmbeddingRegistryLookup,
        *,
        public_metadata_version: Literal["3.0", "4.0"] = "3.0",
    ) -> (
        PreparedEmbeddingIndexBasis
        | PreparedMixedEmbeddingIndexBasis
        | PreparedPublicSolutionIndexBasis
        | PreparedRegisteredPublicSolutionIndexBasis
    ):
        """Capture full current eligibility and reusable rows once before index assembly.

        Old index bindings provide predecessor identity ONLY. Reusable numeric rows
        are selected by exact current encoding keys, checked against current source
        projections, and resolved through the canonical finite/L2 file-set reader.
        No Job/model execution, registry mutation or future permission is returned.
        """

        def resolve() -> (
            PreparedEmbeddingIndexBasis
            | PreparedMixedEmbeddingIndexBasis
            | PreparedPublicSolutionIndexBasis
            | PreparedRegisteredPublicSolutionIndexBasis
        ):
            reader, capture = self._capture(
                session, caller, query, InferenceTransferSessionCapturePhase.CAPTURE_POPULATION
            )
            if capture.corpus is None:
                raise ValueError("index basis has no complete current population")
            resolved = self._captured_lookup(session, caller, query, capture)
            targets = tuple(sorted(s.item_revision_id for s in resolved.sources))
            plan: SupportedLocalEmbeddingSourcePlan
            if isinstance(query.namespace, PublicSolutionIndexNamespace):
                plan = (
                    build_local_embedding_source_plan_v4(
                        query, resolved, target_revision_ids=targets
                    )
                    if public_metadata_version == "4.0"
                    else build_local_embedding_source_plan_v3(
                        query, resolved, target_revision_ids=targets
                    )
                )
            elif isinstance(query.namespace, MixedEmbeddingIndexNamespace):
                plan = build_local_embedding_source_plan_v2(
                    query,
                    resolved,
                    target_revision_ids=targets,
                    base_analysis_run_ids=dict(resolved.base_analysis_run_ids),
                )
            else:
                plan = build_local_embedding_source_plan(
                    query, resolved, target_revision_ids=targets
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
            previous, version = self._namespace_predecessor(reader, repository, query)
            # The proof is root-local. Later publication roots independently
            # recapture review dependencies rather than reusing this observation.
            self.authorize_scope(session, caller, query)
            if isinstance(plan, LocalEmbeddingSourcePlanV4):
                registered_previous = None
                if previous is not None:
                    registered_index = previous[1]
                    if not isinstance(
                        registered_index,
                        PublicSolutionEmbeddingIndex | PublicSolutionEmbeddingIndexV4,
                    ):
                        raise ValueError("source-plan4 cannot reinterpret non-public index history")
                    registered_previous = (previous[0], registered_index)
                return PreparedRegisteredPublicSolutionIndexBasis(
                    plan, rows, shards, registered_previous, version
                )
            if isinstance(plan, LocalEmbeddingSourcePlanV3):
                public_previous = None
                if previous is not None:
                    public_index = previous[1]
                    if not isinstance(public_index, PublicSolutionEmbeddingIndex):
                        raise ValueError(
                            "source-plan3 cannot reinterpret predecessor index families"
                        )
                    public_previous = (previous[0], public_index)
                return PreparedPublicSolutionIndexBasis(
                    plan, rows, shards, public_previous, version
                )
            if isinstance(plan, LocalEmbeddingSourcePlanV2):
                if previous is not None and not isinstance(
                    previous[1], (EmbeddingIndexManifest, MixedEmbeddingIndexManifest)
                ):
                    raise ValueError("source-plan2 cannot reinterpret public index history")
                mixed_previous: (
                    tuple[
                        ArtifactMemberPointer, EmbeddingIndexManifest | MixedEmbeddingIndexManifest
                    ]
                    | None
                ) = None
                if previous is not None:
                    old_index = previous[1]
                    if not isinstance(
                        old_index, (EmbeddingIndexManifest, MixedEmbeddingIndexManifest)
                    ):
                        raise ValueError("source-plan2 cannot reinterpret public index history")
                    mixed_previous = (previous[0], old_index)
                return PreparedMixedEmbeddingIndexBasis(plan, rows, shards, mixed_previous, version)
            legacy_previous = None
            if previous is not None:
                if not isinstance(previous[1], EmbeddingIndexManifest):
                    raise ValueError("source-plan1 cannot reinterpret an index2")
                legacy_previous = (previous[0], previous[1])
            # Recheck current caller/policy after filesystem reads; no corpus recapture.
            return PreparedEmbeddingIndexBasis(plan, rows, shards, legacy_previous, version)

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
            _validate_similarity_manifest(intent.selection, pin.index_manifest, index)
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
            current = (
                self._captured_lookup(session, caller, intent.scope, capture)
                if isinstance(
                    intent.selection,
                    (
                        SimilarityViewSelectionV2,
                        PublicSolutionSimilarityView,
                        PublicSolutionSimilarityViewV4,
                    ),
                )
                else None
            )
            current_entries = capture.entries if current is None else current.entries
            entries = {
                embedding_entry_source(value).item_revision_id: value for value in current_entries
            }
            base_ids = {} if current is None else dict(current.base_analysis_run_ids)
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
                    or not intent.scope.namespace.accepts_projection(binding.projection_version)
                    or (
                        isinstance(
                            binding,
                            (
                                RegisteredReviewEmbeddingSourceBinding,
                                PublicSolutionEmbeddingSourceBinding,
                                RegisteredPublicSolutionSourceBinding,
                            ),
                        )
                        and binding.base_analysis_run_id
                        != base_ids.get(binding.source.item_revision_id)
                    )
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
            by_pointer: dict[ArtifactMemberPointer, list[SupportedEmbeddingBinding]] = {}
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
            if isinstance(
                intent.selection,
                (
                    SimilarityViewSelectionV2,
                    PublicSolutionSimilarityView,
                    PublicSolutionSimilarityViewV4,
                ),
            ):
                validate_supported_embedding_source_bindings(
                    selected, current_entries, tuple(shards)
                )
            else:
                if any(not isinstance(binding, EmbeddingSourceBinding) for binding in selected):
                    raise ValueError("similarity request1 cannot reinterpret binding2")
                validate_embedding_source_bindings(
                    tuple(
                        binding
                        for binding in selected
                        if isinstance(binding, EmbeddingSourceBinding)
                    ),
                    tuple(
                        entry
                        for entry in capture.entries
                        if isinstance(entry, StagedExperimentEntry)
                    ),
                    tuple(shards),
                )
            rows = tuple(materialized[key] for key in sorted(materialized))
            profiles = tuple(
                AuthorizedEmbeddingReadProfile(
                    revision,
                    embedding_entry_profile(entry),
                )
                for revision, entry in sorted(entries.items())
            )
            return ResolvedPinnedEmbeddingIndex(intent, sources, profiles, selected, rows)

        return self._guard(resolve)

    def verify_registered_references(
        self,
        session: Session,
        caller: EmbeddingRegistryActor,
        intent: SupportedEmbeddingRegistrationCommand | EmbeddingRegistryLookup,
        rows: tuple[RegisteredEmbeddingRow, ...],
        origins: tuple[EmbeddingBindingOrigin, ...],
    ) -> ResolvedEmbeddingReferences:
        def resolve() -> ResolvedEmbeddingReferences:
            maximum = (
                MAX_PUBLIC_SOLUTION_SOURCES
                if isinstance(intent.namespace, PublicSolutionIndexNamespace)
                else 1024
            )
            if len(rows) > maximum or len(origins) > maximum:
                raise ValueError("registered reference budget exceeded")
            reader, capture = self._capture(
                session, caller, intent, InferenceTransferSessionCapturePhase.CAPTURE_POPULATION
            )
            current = self._captured_lookup(session, caller, intent, capture)
            plan = plan_embedding_delta(
                current.entries,
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
            if (
                len({row.encoding.encoding_sha256 for row in checked_rows}) != len(rows)
                or len(set(origins)) != len(origins)
                or len({origin.binding_sha256 for origin in origins}) != len(origins)
            ):
                raise ValueError("duplicate registered references")
            admitted_sources = {value.item_revision_id: value for value in current.sources}
            entries = {
                embedding_entry_source(value).item_revision_id: value for value in current.entries
            }
            base_ids = dict(current.base_analysis_run_ids)
            by_encoding = {row.encoding.encoding_sha256: row for row in checked_rows}
            rebuilt: dict[str, SupportedEmbeddingBinding] = {}
            for demand in plan.demands:
                row = by_encoding.get(demand.encoding.encoding_sha256)
                if row is None:
                    continue
                entry = entries[demand.source_revision_id]
                binding: SupportedEmbeddingBinding
                recipe = self.configuration.recipe
                if isinstance(
                    entry, PublicSolutionEmbeddingEntry | RegisteredPublicSolutionEmbeddingEntry
                ):
                    if not isinstance(intent.namespace, PublicSolutionIndexNamespace):
                        raise ValueError("public solution requires its exact namespace")
                    binding = assemble_public_solution_binding(
                        entry, row=row, space=self.configuration.space, namespace=intent.namespace
                    )
                elif isinstance(entry, RegisteredReviewEmbeddingEntry):
                    if not isinstance(recipe, ExperimentViewRecipe):
                        raise ValueError("registered review requires its released recipe family")
                    if not isinstance(
                        intent.namespace, MixedEmbeddingIndexNamespace
                    ) or not isinstance(demand.profile, RegisteredReviewProfilePointer):
                        raise ValueError("index1 does not support a registered-review profile")
                    binding = assemble_registered_review_source_binding(
                        source=admitted_sources[demand.source_revision_id],
                        base_analysis_run_id=base_ids[demand.source_revision_id],
                        profile=demand.profile,
                        review_evidence=entry.profile.source_basis.review_evidence,
                        graph_snapshot=intent.graph_snapshot,
                        policy_revision_id=intent.policy_revision_id,
                        policy_sha256=intent.policy_sha256,
                        recipe=recipe,
                        view=intent.namespace.view,
                        row=row,
                    )
                else:
                    if not isinstance(recipe, ExperimentViewRecipe):
                        raise ValueError("legacy solution requires its released recipe family")
                    if not isinstance(demand.profile, InferenceTransferProfilePointer):
                        raise ValueError("legacy binding requires its own profile family")
                    binding = assemble_embedding_source_binding(
                        source=admitted_sources[demand.source_revision_id],
                        profile=demand.profile,
                        solution_evidence=entry.profile.source_basis.solution_evidence,
                        graph_snapshot=intent.graph_snapshot,
                        policy_revision_id=intent.policy_revision_id,
                        policy_sha256=intent.policy_sha256,
                        recipe=recipe,
                        view=intent.namespace.view,
                        projection_version=entry.profile.extraction.extractor_version,
                        row=row,
                    )
                if binding.binding_sha256 in rebuilt:
                    raise ValueError("duplicate reconstructed source binding")
                rebuilt[binding.binding_sha256] = binding
            ledger = EmbeddingRegistryRepository(session).bindings_by_sha256(
                tuple(origin.binding_sha256 for origin in origins)
            )
            if set(ledger) != {origin.binding_sha256 for origin in origins}:
                raise ValueError("registered binding ledger identity is missing")
            resolved_values = []
            for origin in origins:
                current_binding = rebuilt.get(origin.binding_sha256)
                record = ledger[origin.binding_sha256]
                if (
                    current_binding is None
                    or binding_origin(record) != origin
                    or any(
                        getattr(record, name) != value
                        for name, value in binding_columns(current_binding).items()
                    )
                ):
                    raise ValueError("registered binding ledger differs from exact current binding")
                resolved_values.append(ResolvedEmbeddingBindingOrigin(origin, current_binding))
            resolved = tuple(resolved_values)
            pointers = {row.row_ref.shard_manifest for row in checked_rows}
            index_pointers = tuple(
                sorted(
                    {origin.manifest for origin in origins},
                    key=lambda p: (p.artifact_id, p.artifact_revision_id, p.member_path, p.sha256),
                )
            )
            reader.prefetch(tuple((p.artifact_id, p.artifact_revision_id) for p in index_pointers))
            # Registration fully validates this value before the immutable ledger
            # insertion. Exact reconstruction/ledger equality plus the SAME origin
            # bytes preserve membership without reparsing every cumulative prefix.
            for pointer in index_pointers:
                self._read_index_member(reader, pointer)
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
            if any(
                value.binding.source != admitted_sources.get(value.binding.source.item_revision_id)
                or value.binding.graph_snapshot != intent.graph_snapshot
                or value.binding.policy_revision_id != intent.policy_revision_id
                or value.binding.policy_sha256 != intent.policy_sha256
                or value.binding.view != intent.namespace.view
                or value.binding.recipe != self.configuration.recipe
                or not intent.namespace.accepts_projection(value.binding.projection_version)
                for value in resolved
            ):
                raise ValueError("registered binding differs from exact current admitted scope")
            binding_shards = tuple(
                (pointer, shard) for pointer, shard in shards if pointer in selected
            )
            validate_supported_embedding_source_bindings(
                tuple(value.binding for value in resolved), current.entries, binding_shards
            )
            return ResolvedEmbeddingReferences(resolved, binding_shards)

        return self._guard(resolve)
