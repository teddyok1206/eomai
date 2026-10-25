"""Compose real per-device Catalog/service preparation before acquiring a physical GPU."""

from __future__ import annotations

from dataclasses import dataclass

from eom_catalog_contracts.embedding_registry import EmbeddingIndexNamespace
from eom_catalog_contracts.mixed_embedding_registry import MixedEmbeddingIndexNamespace
from eom_catalog_service.embedding_registry_indexing_authority import (
    CatalogIndexingRegistrySourceAuthority,
)
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryOwnerConfiguration
from eom_catalog_service.knowledge_retrieval_service import KnowledgeRetrievalApplicationService
from eom_catalog_service.local_indexing_source_authority import CatalogLocalIndexingSourceAuthority
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.settings import CatalogSettings
from eom_identity_service import PostgresLocalIndexingServiceFence
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.embedding_device_routing import EmbeddingDeviceRoutingPolicy
from eom_workflow.local_embedding_execution_policy import LocalEmbeddingRuntimeProfile
from eom_workflow.local_indexing_owner_configuration import CpuLocalIndexingOwnerSelection
from eom_workflow.local_indexing_routed_owner_configuration import (
    RoutedLocalIndexingOwnerConfiguration,
    require_routed_indexing_policy,
)
from eom_workflow.native_embedding_backend_selection import select_native_index_runtime_profile
from sqlalchemy import Engine

from eom_workflow_runner.embedding_batch_plan_admission import (
    resolve_embedding_device_routing_policy,
)
from eom_workflow_runner.local_embedding_owner_admission import (
    CatalogLocalEmbeddingOwnerAdmission,
    LocalEmbeddingOwnerConfiguration,
    ServiceReconciliationControls,
)
from eom_workflow_runner.local_embedding_service_reconciliation import (
    LocalEmbeddingServicePreparation,
)


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("LOCAL_INDEXING_ROUTED_SOURCE_MISMATCH")


@dataclass(frozen=True, slots=True)
class PairedIndexingNamespacePreparation:
    """Actual owners, not transferable grants or serialized permissions."""

    cpu: LocalEmbeddingServicePreparation
    cuda: LocalEmbeddingServicePreparation

    @property
    def namespace(self) -> EmbeddingIndexNamespace | MixedEmbeddingIndexNamespace:
        return self.cuda.owner.configuration.registry.namespace


@dataclass(frozen=True, slots=True)
class RoutedIndexingSources:
    configuration: RoutedLocalIndexingOwnerConfiguration
    policy: EmbeddingDeviceRoutingPolicy
    namespaces: tuple[PairedIndexingNamespacePreparation, ...]


def _preparation(
    engine: Engine,
    publisher: ControlFileSetPublisher,
    source_authority: CatalogLocalIndexingSourceAuthority,
    cpu: CpuLocalIndexingOwnerSelection,
    namespace: EmbeddingIndexNamespace | MixedEmbeddingIndexNamespace,
    profile: LocalEmbeddingRuntimeProfile,
    *,
    grant_revision_id: str,
    grant_sha256: str,
    native_policy: ArtifactMemberPointer,
    native_policy_sha256: str,
    source_commit: str,
    settings: CatalogSettings,
) -> LocalEmbeddingServicePreparation:
    authority = CatalogIndexingRegistrySourceAuthority(
        source_authority,
        grant_revision_id,
        grant_sha256,
        native_policy_sha256,
        profile.resource_profile.resource_profile_sha256,
        cpu.maximum_sources,
    )
    owner = CatalogLocalEmbeddingOwnerAdmission.for_indexing_service(
        engine,
        LocalEmbeddingOwnerConfiguration(
            EmbeddingRegistryOwnerConfiguration(
                cpu.corpus_id, namespace, profile.space, cpu.recipe, cpu.source_classes
            ),
            native_policy,
            native_policy_sha256,
        ),
        source_authority=authority,
        settings=settings,
    )
    return LocalEmbeddingServicePreparation(
        owner,
        publisher,
        profile,
        source_commit=source_commit,
        maximum_targets=cpu.maximum_targets,
    )


def _same_source_grant(
    cpu: ServiceReconciliationControls, cuda: ServiceReconciliationControls
) -> None:
    _require(cpu.caller == cuda.caller and type(cpu.grant) is type(cuda.grant))
    _require(
        all(
            getattr(cpu.grant, name) == getattr(cuda.grant, name)
            for name in (
                "source_access_policy_revision_id",
                "source_access_policy_sha256",
                "corpus_id",
                "graph_id",
                "source_classes",
                "maximum_sources",
                "answer_bearing_use",
            )
        )
    )


def build_routed_indexing_sources(
    engine: Engine,
    publisher: ControlFileSetPublisher,
    service_fence: PostgresLocalIndexingServiceFence,
    configuration: RoutedLocalIndexingOwnerConfiguration,
    *,
    source_commit: str,
    settings: CatalogSettings,
) -> RoutedIndexingSources:
    """Only the installed service's actual same-process runtime/Identity fence is accepted.

    The caller still owns bootstrap privileges/reservation prerequisites and the
    surrounding runtime capture. This function neither authenticates a model-
    supplied service ID nor dispatches, claims, activates or runs a numerical model.
    """
    _require(
        type(service_fence) is PostgresLocalIndexingServiceFence
        and publisher.engine is engine
        and publisher.settings.nas_artifact_root == settings.nas_artifact_root
        and source_commit == service_fence.pin.runtime_source_commit
    )
    configuration = RoutedLocalIndexingOwnerConfiguration.model_validate(configuration)
    authority = CatalogLocalIndexingSourceAuthority(
        KnowledgeRetrievalApplicationService(engine, settings), service_fence
    )
    pairs = []
    for group in configuration.groups:
        cpu, grant = group.cpu, group.cuda_grant
        cpu_namespaces: tuple[EmbeddingIndexNamespace | MixedEmbeddingIndexNamespace, ...] = (
            cpu.namespaces
        )
        for cpu_ns, cuda_ns in zip(
            cpu_namespaces, group.cuda_namespaces(configuration.cuda_runtime_profile), strict=True
        ):
            pairs.append(
                PairedIndexingNamespacePreparation(
                    _preparation(
                        engine,
                        publisher,
                        authority,
                        cpu,
                        cpu_ns,
                        cpu.runtime_profile,
                        grant_revision_id=cpu.service_policy_revision_id,
                        grant_sha256=cpu.service_policy_sha256,
                        native_policy=cpu.native_execution_policy,
                        native_policy_sha256=cpu.native_execution_policy_sha256,
                        source_commit=source_commit,
                        settings=settings,
                    ),
                    _preparation(
                        engine,
                        publisher,
                        authority,
                        cpu,
                        cuda_ns,
                        configuration.cuda_runtime_profile,
                        grant_revision_id=grant.service_policy_revision_id,
                        grant_sha256=grant.service_policy_sha256,
                        native_policy=grant.native_execution_policy,
                        native_policy_sha256=grant.native_execution_policy_sha256,
                        source_commit=source_commit,
                        settings=settings,
                    ),
                )
            )
    _require(bool(pairs))
    # One current root holds every actual grant. No physical capacity, source-plan
    # publication, Workflow creation or numerical work is part of this composition.
    with publisher.sessions.begin() as session:
        service_fence.fence_current_service(session)
        native_controls = []
        for pair in pairs:
            cpu_query = pair.cpu.owner.current_reconciliation_lookup(session)
            cuda_query = pair.cuda.owner.current_reconciliation_lookup(session)
            if cpu_query is None or cuda_query is None:
                _require(cpu_query is None and cuda_query is None)
                continue
            _require(
                cpu_query.graph_snapshot == cuda_query.graph_snapshot
                and cpu_query.policy_revision_id == cuda_query.policy_revision_id
                and cpu_query.policy_sha256 == cuda_query.policy_sha256
            )
            cpu_controls = pair.cpu.owner.resolve_reconciliation_controls(
                session, cpu_query, pair.cpu.runtime_profile
            )
            cuda_controls = pair.cuda.owner.resolve_reconciliation_controls(
                session, cuda_query, pair.cuda.runtime_profile
            )
            _same_source_grant(cpu_controls, cuda_controls)
            native_controls.append((pair, cpu_controls, cuda_controls))
        reader = PinnedArtifactReadContext.for_session(session, settings)
        policy = resolve_embedding_device_routing_policy(reader, configuration.routing_policy)
        require_routed_indexing_policy(configuration, policy)
        for pair, cpu_controls, cuda_controls in native_controls:
            _require(
                select_native_index_runtime_profile(policy.cpu.backend, cpu_controls.policy)
                == pair.cpu.runtime_profile
                and select_native_index_runtime_profile(policy.cuda.backend, cuda_controls.policy)
                == pair.cuda.runtime_profile
            )
        reader.revalidate_provenance()
        service_fence.fence_current_service(session)
    return RoutedIndexingSources(configuration, policy, tuple(pairs))
