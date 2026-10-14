"""Service-purpose Registry source admission; no parallel materializer or fake operator."""

from __future__ import annotations

import re
from dataclasses import dataclass

from eom_catalog_contracts.embedding_registry import RegisterEmbeddingIndexCommand
from eom_catalog_contracts.local_indexing_policy import LocalIndexingAccessPolicy
from sqlalchemy.orm import Session

from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryError,
    EmbeddingRegistryLookup,
    EmbeddingRegistryOwnerConfiguration,
    EmbeddingRegistryServiceCaller,
    validate_embedding_registry_actor,
)
from eom_catalog_service.inference_transfer_snapshot_catalog_adapter import (
    CatalogInferenceTransferSnapshotSourceAdapter,
    InferenceTransferSessionCapturePhase,
    LocalIndexingSessionCapture,
)
from eom_catalog_service.local_indexing_source_authority import CatalogLocalIndexingSourceAuthority
from eom_catalog_service.local_indexing_source_ports import LocalIndexingSourceReadIntent
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext


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
            or not 1 <= self.maximum_sources <= 1024
        ):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_CONFIGURATION_INVALID")

    def source_intent(
        self,
        caller: EmbeddingRegistryServiceCaller,
        intent: RegisterEmbeddingIndexCommand | EmbeddingRegistryLookup,
        configuration: EmbeddingRegistryOwnerConfiguration,
    ) -> LocalIndexingSourceReadIntent:
        """Exact immutable selection only, never current authorization."""
        validate_embedding_registry_actor(caller)
        if caller.service != self.authority.service_fence.pin.service:
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
            maximum_candidates=self.maximum_sources
            if isinstance(intent, RegisterEmbeddingIndexCommand)
            else intent.maximum_sources,
        )
        if selection.maximum_candidates > self.maximum_sources:
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_FORBIDDEN")
        return selection

    def authorize_scope(
        self,
        session: Session,
        caller: EmbeddingRegistryServiceCaller,
        intent: RegisterEmbeddingIndexCommand | EmbeddingRegistryLookup,
        configuration: EmbeddingRegistryOwnerConfiguration,
    ) -> LocalIndexingAccessPolicy:
        """Fresh actual service/data fence, no population/file materialization."""
        return self.authority.authorize_scope(
            session, self.source_intent(caller, intent, configuration)
        )

    def capture(
        self,
        session: Session,
        caller: EmbeddingRegistryServiceCaller,
        intent: RegisterEmbeddingIndexCommand | EmbeddingRegistryLookup,
        configuration: EmbeddingRegistryOwnerConfiguration,
        *,
        sources: CatalogInferenceTransferSnapshotSourceAdapter,
        artifact_reader: PinnedArtifactReadContext,
        phase: InferenceTransferSessionCapturePhase,
    ) -> LocalIndexingSessionCapture:
        return sources.capture_indexing_in_session(
            session,
            self.source_intent(caller, intent, configuration),
            authority=self.authority,
            artifact_reader=artifact_reader,
            phase=phase,
        )
