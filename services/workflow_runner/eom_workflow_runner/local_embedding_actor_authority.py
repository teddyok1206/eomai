"""Two explicit current-actor authorities over one native execution application.

No saved audit/DTO is authority. Operator sessions remain actual user sessions;
service indexing reuses Catalog's installed runtime/DB/current-grant source gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from eom_catalog_contracts.local_indexing_mixed_policy import (
    LocalIndexingMixedAccessPolicy,
    supported_local_indexing_authorization_audit_sha256,
)
from eom_catalog_contracts.public_solution_indexing_policy import PublicSolutionIndexingAccessPolicy
from eom_catalog_service.embedding_registry_catalog_adapter import CatalogEmbeddingRegistryVerifier
from eom_catalog_service.embedding_registry_indexing_authority import (
    CatalogIndexingRegistrySourceAuthority,
)
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryLookup,
    EmbeddingRegistryOwnerConfiguration,
    EmbeddingRegistryServiceCaller,
)
from eom_catalog_service.local_indexing_source_ports import LocalIndexingSourceError
from eom_catalog_service.settings import CatalogSettings
from eom_identity_service import CapturedOperatorAuthorizationFence
from eom_workflow.local_embedding_execution_policy import (
    LOCAL_EMBEDDING_POLICY_SCHEMA_REF,
    LOCAL_EMBEDDING_SERVICE_POLICY_SCHEMA_REF,
)
from eom_workflow.local_embedding_request import (
    LocalEmbeddingServiceWorkflowRequest,
    LocalEmbeddingWorkflowRequestV11,
    require_local_embedding_operator_seed,
)
from eom_workflow.local_embedding_request_v2 import (
    LocalEmbeddingWorkflowRequestV2,
    supported_local_embedding_request_service,
)
from eom_workflow.local_embedding_request_v3 import (
    LocalEmbeddingWorkflowRequestV3,
)
from eom_workflow.local_embedding_request_v4 import LocalEmbeddingWorkflowRequestV4
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from eom_workflow_runner.local_embedding_admission import (
    SupportedLocalEmbeddingOwnerRequest,
    parse_supported_local_embedding_owner_request,
)


@dataclass(frozen=True, slots=True)
class OperatorLocalEmbeddingActorAuthority:
    identity: CapturedOperatorAuthorizationFence
    policy_schema_ref: ClassVar[str] = LOCAL_EMBEDDING_POLICY_SCHEMA_REF

    def registry_caller(
        self, request: SupportedLocalEmbeddingOwnerRequest
    ) -> EmbeddingRegistryCaller:
        request = parse_supported_local_embedding_owner_request(request)
        if not isinstance(request, LocalEmbeddingWorkflowRequestV11):
            raise ValueError("LOCAL_EMBEDDING_OPERATOR_UNAVAILABLE")
        return EmbeddingRegistryCaller(require_local_embedding_operator_seed(request).operator_id)

    def fence(self, session: Session, request: SupportedLocalEmbeddingOwnerRequest) -> None:
        self.identity.fence_current_operator(session, self.registry_caller(request).operator_id)

    def catalog(
        self,
        engine: Engine,
        configuration: EmbeddingRegistryOwnerConfiguration,
        settings: CatalogSettings,
    ) -> CatalogEmbeddingRegistryVerifier:
        return CatalogEmbeddingRegistryVerifier(
            engine, configuration, identity_fence=self.identity, settings=settings
        )


@dataclass(frozen=True, slots=True)
class ServiceLocalEmbeddingActorAuthority:
    source_authority: CatalogIndexingRegistrySourceAuthority
    registry: EmbeddingRegistryOwnerConfiguration
    policy_schema_ref: ClassVar[str] = LOCAL_EMBEDDING_SERVICE_POLICY_SCHEMA_REF

    def __post_init__(self) -> None:
        if type(self.source_authority) is not CatalogIndexingRegistrySourceAuthority:
            raise ValueError("LOCAL_EMBEDDING_SERVICE_UNAVAILABLE")
        self.source_authority.__post_init__()

    def registry_caller(
        self, request: SupportedLocalEmbeddingOwnerRequest
    ) -> EmbeddingRegistryServiceCaller:
        checked = parse_supported_local_embedding_owner_request(request)
        if not isinstance(
            checked,
            LocalEmbeddingServiceWorkflowRequest
            | LocalEmbeddingWorkflowRequestV2
            | LocalEmbeddingWorkflowRequestV3
            | LocalEmbeddingWorkflowRequestV4,
        ):
            raise ValueError("LOCAL_EMBEDDING_SERVICE_UNAVAILABLE")
        gate, audit = self.source_authority, checked.actor_context
        service = supported_local_embedding_request_service(checked)
        caller = EmbeddingRegistryServiceCaller(service)
        if (
            caller.service != gate.authority.service_fence.pin.service
            or audit.service_policy_revision_id != gate.service_policy_revision_id
            or audit.service_policy_sha256 != gate.service_policy_sha256
            or checked.native_execution_policy_sha256 != gate.native_execution_policy_sha256
            or checked.resource_profile.resource_profile_sha256 != gate.resource_profile_sha256
        ):
            raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_FORBIDDEN")
        return caller

    def fence(self, session: Session, request: SupportedLocalEmbeddingOwnerRequest) -> None:
        request = parse_supported_local_embedding_owner_request(request)
        caller = self.registry_caller(request)
        policy = self.source_authority.authorize_scope(
            session,
            caller,
            EmbeddingRegistryLookup(
                request.corpus_id,
                request.namespace,
                request.graph_snapshot,
                request.access_policy_revision_id,
                request.access_policy_sha256,
                self.source_authority.maximum_sources,
            ),
            self.registry,
        )
        if (
            not isinstance(
                request,
                LocalEmbeddingServiceWorkflowRequest
                | LocalEmbeddingWorkflowRequestV2
                | LocalEmbeddingWorkflowRequestV3
                | LocalEmbeddingWorkflowRequestV4,
            )
            or (
                isinstance(request, LocalEmbeddingWorkflowRequestV2)
                != isinstance(policy, LocalIndexingMixedAccessPolicy)
            )
            or (
                isinstance(
                    request, LocalEmbeddingWorkflowRequestV3 | LocalEmbeddingWorkflowRequestV4
                )
                != isinstance(policy, PublicSolutionIndexingAccessPolicy)
            )
            or (
                request.actor_context.authorization_audit_sha256
                != supported_local_indexing_authorization_audit_sha256(policy)
            )
        ):
            raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_FORBIDDEN")

    def catalog(
        self,
        engine: Engine,
        configuration: EmbeddingRegistryOwnerConfiguration,
        settings: CatalogSettings,
    ) -> CatalogEmbeddingRegistryVerifier:
        if configuration != self.registry:
            raise ValueError("LOCAL_EMBEDDING_OWNER_CONFIGURATION_MISMATCH")
        return CatalogEmbeddingRegistryVerifier.for_indexing_service(
            engine, configuration, source_authority=self.source_authority, settings=settings
        )


type LocalEmbeddingActorAuthority = (
    OperatorLocalEmbeddingActorAuthority | ServiceLocalEmbeddingActorAuthority
)
