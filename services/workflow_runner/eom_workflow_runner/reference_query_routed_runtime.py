"""Optional GPU-first reference composition over the unchanged installed CPU owner."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

from eom_catalog_service.embedding_batch_control_workspace import BATCH_CONTROL_ROOT
from eom_catalog_service.embedding_batch_owner_workspace import BATCH_OWNER_ROOT
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryOwnerConfiguration
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_identity_service import AuthenticatedOperatorSession
from eom_orchestrator.inference_transfer_cpu_handoff import (
    fixed_owner_identity,
    protected_cpu_handoff_directory,
)
from eom_workflow.embedding_device_routing import EmbeddingDeviceRoutingPolicy
from eom_workflow.reference_query_execution import ReferenceQueryExecutionPolicy
from eom_workflow.reference_query_routed_owner_configuration import (
    SupportedRoutedReferenceQueryOwnerConfiguration,
    require_supported_routed_reference_query_policy,
    validate_supported_routed_reference_query_configuration,
)
from sqlalchemy import text

from eom_workflow_runner.embedding_batch_plan_admission import (
    resolve_embedding_device_routing_policy,
)
from eom_workflow_runner.reference_query_owner_admission import CatalogReferenceQueryOwnerAdmission
from eom_workflow_runner.reference_query_owner_runtime import (
    ReferenceQueryOwnerRuntime,
    require_current_reference_query_provider,
    require_reference_query_database_owner,
)
from eom_workflow_runner.reference_query_prepare_application import NativeReferenceQueryPreparation
from eom_workflow_runner.reference_query_routed_selection import (
    CatalogRoutedReferenceQuerySelection,
)
from eom_workflow_runner.reference_query_source_read import (
    ReferenceQueryOwnerConfiguration,
    read_selected_reference_query_controls,
)


@dataclass(frozen=True, slots=True)
class RoutedReferenceQuerySession:
    """Operation-local actual capture only; no shared authenticated/source-result cache."""

    cpu: NativeReferenceQueryPreparation
    selection: CatalogRoutedReferenceQuerySelection


class RoutedReferenceQueryOwnerFactory:
    """Shares the installed lifecycle, provider and CPU launcher, never a parallel daemon.

    Factory state contains configuration/policy metadata, not human sessions.
    Every operation constructs independent CPU/CUDA Catalog owners sharing the
    same genuine current capture. Those owners reauthorize each read/START.
    """

    def __init__(
        self,
        runtime: ReferenceQueryOwnerRuntime,
        configuration: SupportedRoutedReferenceQueryOwnerConfiguration,
        routing: EmbeddingDeviceRoutingPolicy,
        cpu_policy: ReferenceQueryExecutionPolicy,
        cuda_policy: ReferenceQueryExecutionPolicy,
        configuration_guard: Callable[[], None],
    ) -> None:
        self.runtime, self.configuration, self.routing = runtime, configuration, routing
        self.cpu_policy, self.cuda_policy = cpu_policy, cuda_policy
        self.configuration_guard = configuration_guard

    def session(self, capture: AuthenticatedOperatorSession) -> RoutedReferenceQuerySession:
        self.configuration_guard()
        runtime, configuration = self.runtime, self.configuration
        require_current_reference_query_provider(runtime.admission, runtime.configuration)
        cpu = runtime.application(capture)
        original = cpu.owner.configuration.registry
        namespace = type(original.namespace).model_validate(
            original.namespace.model_dump(mode="json")
            | {"space_sha256": self.cuda_policy.spaces.document.space_sha256}
        )
        cuda = CatalogReferenceQueryOwnerAdmission(
            runtime.engine,
            ReferenceQueryOwnerConfiguration(
                EmbeddingRegistryOwnerConfiguration(
                    original.corpus_id,
                    namespace,
                    self.cuda_policy.spaces.document,
                    original.recipe,
                    original.source_classes,
                ),
                configuration.cuda_native_execution_policy,
                configuration.cuda_native_execution_policy_sha256,
                self.cuda_policy.runtime_bundle,
            ),
            capture=cpu.owner.identity.capture,
            session_fence=cpu.owner.identity.fence,
            settings=runtime.catalog_settings,
        )
        selected = CatalogRoutedReferenceQuerySelection(
            cpu=cpu.owner,
            cuda=cuda,
            publisher=runtime.publisher,
            configuration=configuration,
            policy=self.routing,
            cpu_policy=self.cpu_policy,
            cuda_policy=self.cuda_policy,
        )
        self.configuration_guard()
        require_current_reference_query_provider(runtime.admission, runtime.configuration)
        return RoutedReferenceQuerySession(cpu, selected)


def build_routed_reference_query_owner_factory(
    runtime: ReferenceQueryOwnerRuntime,
    configuration: SupportedRoutedReferenceQueryOwnerConfiguration,
    *,
    configuration_guard: Callable[[], None],
) -> RoutedReferenceQueryOwnerFactory:
    """Read-only installed selection, no human capture, GPU, model, claim or activation."""
    if type(runtime) is not ReferenceQueryOwnerRuntime or not callable(configuration_guard):
        raise ValueError("REFERENCE_QUERY_ROUTED_OWNER_COMPOSITION_INVALID")
    configuration = validate_supported_routed_reference_query_configuration(configuration)
    if configuration.cpu_configuration != runtime.configuration:
        raise ValueError("REFERENCE_QUERY_ROUTED_OWNER_COMPOSITION_INVALID")
    configuration_guard()
    require_current_reference_query_provider(runtime.admission, runtime.configuration)
    identity = fixed_owner_identity()
    if (os.geteuid(), os.getegid()) != (identity.owner_uid, identity.owner_gid) or os.getgroups():
        raise ValueError("REFERENCE_QUERY_ROUTED_OWNER_ACCOUNT_UNAVAILABLE")
    require_routed_query_staging()
    with runtime.publisher.sessions.begin() as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        require_reference_query_database_owner(session, runtime.configuration.database_owner)
        reader = PinnedArtifactReadContext(session, runtime.catalog_settings)
        routing = resolve_embedding_device_routing_policy(reader, configuration.routing_policy)
        policies = []
        for pointer, digest, bundle in (
            (
                runtime.configuration.native_execution_policy,
                runtime.configuration.native_execution_policy_sha256,
                runtime.configuration.runtime_bundle,
            ),
            (
                configuration.cuda_native_execution_policy,
                configuration.cuda_native_execution_policy_sha256,
                routing.cuda.profile.runtime_bundle,
            ),
        ):
            policy, _bundle = read_selected_reference_query_controls(
                reader,
                policy_member=pointer,
                policy_sha256=digest,
                runtime_bundle=bundle,
            )
            policies.append(policy)
        cpu, cuda = policies
        require_supported_routed_reference_query_policy(configuration, routing, cpu, cuda)
        if cpu.spaces != runtime.spaces:
            raise ValueError("REFERENCE_QUERY_ROUTED_OWNER_SPACE_UNAVAILABLE")
        reader.revalidate_provenance()
    configuration_guard()
    require_current_reference_query_provider(runtime.admission, runtime.configuration)
    return RoutedReferenceQueryOwnerFactory(
        runtime, configuration, routing, cpu, cuda, configuration_guard
    )


def require_routed_query_staging() -> None:
    """Read-only fixed layout preflight, not directory provisioning or a GPU allocation."""
    identity = fixed_owner_identity()
    for path in (BATCH_CONTROL_ROOT, BATCH_OWNER_ROOT):
        with protected_cpu_handoff_directory(
            path, owner=identity, uid=identity.owner_uid, gid=identity.owner_gid, mode=0o700
        ) as directory:
            if os.fstatvfs(directory).f_flag & os.ST_RDONLY:
                raise ValueError("REFERENCE_QUERY_ROUTED_OWNER_WORKSPACE_READ_ONLY")
