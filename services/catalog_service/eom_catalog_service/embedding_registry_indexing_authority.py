"""Service-purpose Registry source admission; no parallel materializer or fake operator."""

from __future__ import annotations

import re
from dataclasses import dataclass

from eom_catalog_contracts.embedding_registry import RegisterEmbeddingIndexCommand
from eom_catalog_contracts.local_indexing_mixed_policy import SupportedLocalIndexingAccessPolicy
from eom_catalog_contracts.mixed_embedding_registry import RegisterEmbeddingIndexCommandV2
from eom_catalog_contracts.public_solution_embedding_index import (
    MAX_PUBLIC_SOLUTION_SOURCES,
    PublicSolutionIndexNamespace,
)
from eom_catalog_contracts.public_solution_embedding_registry import (
    RegisterPublicSolutionIndexCommand,
)
from sqlalchemy.orm import Session

from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryError,
    EmbeddingRegistryLookup,
    EmbeddingRegistryOwnerConfiguration,
    EmbeddingRegistryServiceCaller,
    SupportedEmbeddingRegistrationCommand,
    validate_embedding_registry_actor,
)
from eom_catalog_service.inference_transfer_snapshot_catalog_adapter import (
    CatalogInferenceTransferSnapshotSourceAdapter,
    InferenceTransferSessionCapturePhase,
    LocalIndexingSessionCapture,
)
from eom_catalog_service.local_indexing_source_authority import CatalogLocalIndexingSourceAuthority
from eom_catalog_service.local_indexing_source_ports import (
    LocalIndexingSourceError,
    LocalIndexingSourceReadIntent,
)
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.public_solution_capture_ports import CapturedPublicSolutionSources


@dataclass(frozen=True, slots=True)
class CatalogIndexingRegistrySourceAuthority:
    """Trusted installed composition; immutable pins alone never supply authority.

    Every capture still calls Catalog's actual runtime/DB/source-policy gate in
    the caller root. The authority is never reconstructed from a request or audit.
    """

    authority: CatalogLocalIndexingSourceAuthority
    service_policy_revision_id: str
    service_policy_sha256: str
    native_execution_policy_sha256: str
    resource_profile_sha256: str
    maximum_sources: int = 1024

    def __post_init__(self) -> None:
        if (
            type(self.authority) is not CatalogLocalIndexingSourceAuthority
            or type(self.service_policy_revision_id) is not str
            or re.fullmatch(r"accessrev_[0-9a-f]{32}", self.service_policy_revision_id) is None
            or any(
                type(value) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None
                for value in (
                    self.service_policy_sha256,
                    self.native_execution_policy_sha256,
                    self.resource_profile_sha256,
                )
            )
            or type(self.maximum_sources) is not int
            or not 1 <= self.maximum_sources <= MAX_PUBLIC_SOLUTION_SOURCES
        ):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_CONFIGURATION_INVALID")

    def source_intent(
        self,
        caller: EmbeddingRegistryServiceCaller,
        intent: SupportedEmbeddingRegistrationCommand | EmbeddingRegistryLookup,
        configuration: EmbeddingRegistryOwnerConfiguration,
        *,
        source_revision_ids: tuple[str, ...] = (),
    ) -> LocalIndexingSourceReadIntent:
        """Exact immutable selection only, never current authorization."""
        validate_embedding_registry_actor(caller)
        if caller.service != self.authority.service_fence.pin.service:
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_FORBIDDEN")
        if source_revision_ids and isinstance(
            intent,
            RegisterEmbeddingIndexCommand
            | RegisterEmbeddingIndexCommandV2
            | RegisterPublicSolutionIndexCommand,
        ):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
        maximum = (
            self.maximum_sources
            if isinstance(
                intent,
                (
                    RegisterEmbeddingIndexCommand,
                    RegisterEmbeddingIndexCommandV2,
                    RegisterPublicSolutionIndexCommand,
                ),
            )
            else intent.maximum_sources
        )
        public = isinstance(intent.namespace, PublicSolutionIndexNamespace)
        if (not public and maximum > min(self.maximum_sources, 1024)) or (
            public and maximum > MAX_PUBLIC_SOLUTION_SOURCES
        ):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_FORBIDDEN")
        selection = LocalIndexingSourceReadIntent(
            corpus_id=intent.corpus_id,
            graph_snapshot=intent.graph_snapshot,
            access_policy_revision_id=intent.policy_revision_id,
            access_policy_sha256=intent.policy_sha256,
            service_policy_revision_id=self.service_policy_revision_id,
            service_policy_sha256=self.service_policy_sha256,
            source_classes=configuration.source_classes,
            namespace=intent.namespace,
            space=configuration.space,
            recipe=configuration.recipe,
            native_execution_policy_sha256=self.native_execution_policy_sha256,
            resource_profile_sha256=self.resource_profile_sha256,
            maximum_candidates=min(1024, maximum, self.maximum_sources),
            source_revision_ids=source_revision_ids,
        )
        if selection.maximum_candidates > self.maximum_sources:
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_FORBIDDEN")
        return selection

    def authorize_scope(
        self,
        session: Session,
        caller: EmbeddingRegistryServiceCaller,
        intent: SupportedEmbeddingRegistrationCommand | EmbeddingRegistryLookup,
        configuration: EmbeddingRegistryOwnerConfiguration,
    ) -> SupportedLocalIndexingAccessPolicy:
        """Fresh actual service/data fence, no population/file materialization."""
        return self.authority.authorize_scope(
            session, self.source_intent(caller, intent, configuration)
        )

    def current_lookup(
        self, session: Session, configuration: EmbeddingRegistryOwnerConfiguration
    ) -> EmbeddingRegistryLookup | None:
        """Select the current published head only for a new reconciliation observation."""
        policy, graph = self.authority.current_graph(
            session, self.service_policy_revision_id, self.service_policy_sha256
        )
        if (
            configuration.corpus_id != policy.corpus_id
            or configuration.namespace not in policy.namespaces
            or configuration.space != policy.space
            or configuration.recipe != policy.recipe
            or not set(configuration.source_classes).issubset(policy.source_classes)
            or self.native_execution_policy_sha256 != policy.native_execution_policy_sha256
            or self.resource_profile_sha256 != policy.resource_profile_sha256
            or self.maximum_sources > policy.maximum_sources
        ):
            raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_FORBIDDEN")
        if graph is None:
            return None
        query = EmbeddingRegistryLookup(
            configuration.corpus_id,
            configuration.namespace,
            graph,
            policy.source_access_policy_revision_id,
            policy.source_access_policy_sha256,
            self.maximum_sources,
        )
        caller = EmbeddingRegistryServiceCaller(self.authority.service_fence.pin.service)
        self.authorize_scope(session, caller, query, configuration)
        return query

    def capture(
        self,
        session: Session,
        caller: EmbeddingRegistryServiceCaller,
        intent: SupportedEmbeddingRegistrationCommand | EmbeddingRegistryLookup,
        configuration: EmbeddingRegistryOwnerConfiguration,
        *,
        sources: CatalogInferenceTransferSnapshotSourceAdapter,
        artifact_reader: PinnedArtifactReadContext,
        phase: InferenceTransferSessionCapturePhase,
        source_revision_ids: tuple[str, ...] = (),
    ) -> LocalIndexingSessionCapture | CapturedPublicSolutionSources:
        selection = self.source_intent(
            caller, intent, configuration, source_revision_ids=source_revision_ids
        )
        if isinstance(selection.namespace, PublicSolutionIndexNamespace):
            from eom_catalog_service.public_solution_source_capture import (
                CatalogPublicSolutionSourceCapture,
            )

            self.authority.authorize_scope(session, selection)
            if phase is InferenceTransferSessionCapturePhase.AUTHORIZE_SCOPE:
                return CapturedPublicSolutionSources((), (), (), selection, None)
            capture = CatalogPublicSolutionSourceCapture(sources.engine, artifact_reader.settings)
            capture.sources = sources
            if source_revision_ids:
                return capture.capture_indexing_in_session(
                    session, selection, authority=self.authority, artifact_reader=artifact_reader
                )
            maximum = (
                self.maximum_sources
                if isinstance(intent, RegisterPublicSolutionIndexCommand)
                else intent.maximum_sources
                if isinstance(intent, EmbeddingRegistryLookup)
                else 1024
            )
            return capture.capture_indexing_population_in_session(
                session,
                selection,
                authority=self.authority,
                artifact_reader=artifact_reader,
                maximum_population_sources=min(maximum, self.maximum_sources),
            )
        return sources.capture_indexing_in_session(
            session,
            selection,
            authority=self.authority,
            artifact_reader=artifact_reader,
            phase=phase,
        )
