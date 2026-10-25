"""Installed purpose-only composition over the existing Runner and Catalog owners."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from eom_catalog_contracts.embedding_registry import EmbeddingIndexNamespace
from eom_catalog_contracts.mixed_embedding_registry import MixedEmbeddingIndexNamespace
from eom_catalog_service.embedding_registry_indexing_authority import (
    CatalogIndexingRegistrySourceAuthority,
)
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryOwnerConfiguration
from eom_catalog_service.knowledge_retrieval_service import KnowledgeRetrievalApplicationService
from eom_catalog_service.local_indexing_source_authority import CatalogLocalIndexingSourceAuthority
from eom_catalog_service.runtime_privileges import catalog_runtime_privileges_ready
from eom_catalog_service.settings import CatalogSettings
from eom_catalog_service.workflow_catalog import WorkflowCatalogService
from eom_identity_service import PostgresLocalIndexingServiceFence
from eom_identity_service.local_indexing_fence_sql import LocalIndexingFenceOwnerPin
from eom_identity_service.local_indexing_runtime import (
    AuthenticatedLocalIndexingRuntime,
    LocalIndexingRuntimePin,
)
from eom_orchestrator.database import build_native_embedding_controller_engine
from eom_orchestrator.embedding_encoding_reservation_storage import (
    EmbeddingEncodingReservationStorage,
)
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.native_embedding_index_systemd import FixedNativeIndexLauncher
from eom_orchestrator.settings import Settings
from eom_workflow.local_indexing_owner_configuration import (
    MAX_LOCAL_INDEXING_OWNER_BYTES,
    CpuLocalIndexingOwnerSelection,
    LocalIndexingMixedOwnerConfiguration,
    LocalIndexingOwnerConfigurationError,
    parse_cpu_local_indexing_owner_configuration,
)
from eom_workflow.local_indexing_routed_owner_configuration import (
    RoutedLocalIndexingOwnerConfiguration,
    parse_local_indexing_routed_owner_configuration,
)
from sqlalchemy import Engine

from eom_workflow_runner.actor_authorization_adapters import (
    OperatorIdentityWorkflowActorAuthorizer,
    SqlAlchemyOperatorActorSource,
)
from eom_workflow_runner.document_embedding_cpu_execution import FixedCpuDocumentEmbeddingExecution
from eom_workflow_runner.engine import WorkflowRunner
from eom_workflow_runner.local_embedding_native_executor import CatalogNativeEmbeddingExecutor
from eom_workflow_runner.local_embedding_owner_admission import (
    CatalogLocalEmbeddingOwnerAdmission,
    LocalEmbeddingOwnerConfiguration,
)
from eom_workflow_runner.local_embedding_service_reconciliation import (
    LocalEmbeddingReconciliationResult,
    LocalEmbeddingServiceReconciliation,
)
from eom_workflow_runner.local_indexing_routed_namespace import RoutedLocalIndexingNamespaceRuntime
from eom_workflow_runner.local_indexing_routed_sources import build_routed_indexing_sources
from eom_workflow_runner.local_indexing_runner_composition import (
    IndexingRoleExecutionDisabled as IndexingRoleExecutionDisabled,
)
from eom_workflow_runner.local_indexing_runtime_verification import FixedIndexingRuntimeVerification
from eom_workflow_runner.models import WorkflowCommandRecord
from eom_workflow_runner.repository import CommandExecutionFamily, NativeCommandActorSelection
from eom_workflow_runner.settings import RunnerConfig, WorkflowSettings

_STATE_ROOT = Path("/var/lib/eom-local-indexing")


@dataclass(frozen=True, slots=True)
class LocalIndexingNamespaceRuntime:
    namespace: EmbeddingIndexNamespace | MixedEmbeddingIndexNamespace
    runner: WorkflowRunner
    reconciliation: LocalEmbeddingServiceReconciliation

    def run_once(self) -> WorkflowCommandRecord | None:
        return self.runner.run_once()

    def reconcile_once(self) -> LocalEmbeddingReconciliationResult:
        return self.reconciliation.run_once()


@dataclass(frozen=True, slots=True)
class LocalIndexingServiceRuntime:
    engine: Engine
    namespaces: tuple[LocalIndexingNamespaceRuntime | RoutedLocalIndexingNamespaceRuntime, ...]
    configuration: CpuLocalIndexingOwnerSelection | RoutedLocalIndexingOwnerConfiguration


def parse_indexing_service_configuration(
    raw: bytes,
) -> CpuLocalIndexingOwnerSelection | RoutedLocalIndexingOwnerConfiguration:
    """Only this executable dispatcher opts into5; original CPU decoders stay closed."""
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_LOCAL_INDEXING_OWNER_BYTES:
            raise LocalIndexingOwnerConfigurationError()
        value = json.loads(raw)
        if (
            isinstance(value, dict)
            and value.get("schema_version") == "local-indexing-owner-configuration/5.0"
        ):
            return parse_local_indexing_routed_owner_configuration(raw)
        return parse_cpu_local_indexing_owner_configuration(raw)
    except Exception:
        raise LocalIndexingOwnerConfigurationError() from None


def build_local_indexing_service_runtime(
    capture: AuthenticatedLocalIndexingRuntime,
    pin: LocalIndexingRuntimePin,
) -> LocalIndexingServiceRuntime:
    if (
        type(capture) is not AuthenticatedLocalIndexingRuntime
        or type(pin) is not LocalIndexingRuntimePin
    ):
        raise ValueError("LOCAL_INDEXING_SERVICE_RUNTIME_UNAVAILABLE")
    selected = parse_indexing_service_configuration(capture.read_owner_configuration())
    selection = (
        selected.cpu_configuration
        if isinstance(selected, RoutedLocalIndexingOwnerConfiguration)
        else selected
    )
    if selection.runtime_profile.resource_profile.device != "CPU":
        raise ValueError("LOCAL_INDEXING_SERVICE_DEVICE_UNAVAILABLE")
    capture.assert_current(
        service=pin.service,
        runtime_source_commit=pin.runtime_source_commit,
        configuration_sha256=pin.configuration_sha256,
    )
    engine = build_native_embedding_controller_engine()
    try:
        settings = Settings(
            staging_root=_STATE_ROOT / "staging",
            workspace_root=_STATE_ROOT / "workspaces",
            runtime_source_commit=pin.runtime_source_commit,
        )
        catalog_settings = CatalogSettings(
            nas_artifact_root=settings.nas_artifact_root,
            staging_root=_STATE_ROOT / "catalog-staging",
        )
        publisher = ControlFileSetPublisher(engine, settings)
        fence = PostgresLocalIndexingServiceFence(
            LocalIndexingFenceOwnerPin(
                selection.database_owner.role_name, selection.database_owner.role_oid
            ),
            pin,
            capture,
        )
        with publisher.sessions.begin() as session:
            fence.fence_current_service(session)
            if not catalog_runtime_privileges_ready(session.connection()):
                raise ValueError("LOCAL_INDEXING_SERVICE_PRIVILEGES_UNAVAILABLE")
            # A missing deployment prerequisite must fail before any queue claim,
            # not strand a RUNNING application step at its first allocation.
            EmbeddingEncodingReservationStorage.require_protocol(session)
            if isinstance(selection, LocalIndexingMixedOwnerConfiguration):
                EmbeddingEncodingReservationStorage.require_mixed_ownership_protocol(session)
        verifier = FixedIndexingRuntimeVerification(selection.runtime_verifier)
        launcher = FixedNativeIndexLauncher(
            selection.cpu_environment_raw_sha256.removeprefix("sha256:"),
            selection.owner_environment_raw_sha256.removeprefix("sha256:"),
            verifier.assert_current,
        )
        launcher.assert_current_runtime()
        if isinstance(selected, RoutedLocalIndexingOwnerConfiguration):
            routed = build_routed_indexing_sources(
                engine,
                publisher,
                fence,
                selected,
                source_commit=pin.runtime_source_commit,
                settings=catalog_settings,
            )
            routed_namespaces = tuple(
                RoutedLocalIndexingNamespaceRuntime(pair, selected, launcher, fence)
                for pair in routed.namespaces
            )
            return LocalIndexingServiceRuntime(engine, routed_namespaces, selected)
        selections: tuple[CpuLocalIndexingOwnerSelection, ...] = (selection,)
        if (
            isinstance(selection, LocalIndexingMixedOwnerConfiguration)
            and selection.legacy_configuration is not None
        ):
            selections = (selection, selection.legacy_configuration)
        source_authority = CatalogLocalIndexingSourceAuthority(
            KnowledgeRetrievalApplicationService(engine, catalog_settings), fence
        )
        authorities = tuple(
            CatalogIndexingRegistrySourceAuthority(
                source_authority,
                configured.service_policy_revision_id,
                configured.service_policy_sha256,
                configured.native_execution_policy_sha256,
                configured.runtime_profile.resource_profile.resource_profile_sha256,
                configured.maximum_sources,
            )
            for configured in selections
        )
        namespaces = tuple(
            _build_namespace_runtime(
                engine, publisher, authority, configured, namespace, pin, catalog_settings, launcher
            )
            for configured, authority in zip(selections, authorities, strict=True)
            for namespace in configured.namespaces
        )
        return LocalIndexingServiceRuntime(engine, namespaces, selection)
    except Exception:
        engine.dispose()
        raise


def _build_namespace_runtime(
    engine: Engine,
    publisher: ControlFileSetPublisher,
    authority: CatalogIndexingRegistrySourceAuthority,
    selection: CpuLocalIndexingOwnerSelection,
    namespace: EmbeddingIndexNamespace | MixedEmbeddingIndexNamespace,
    pin: LocalIndexingRuntimePin,
    catalog_settings: CatalogSettings,
    launcher: FixedNativeIndexLauncher,
) -> LocalIndexingNamespaceRuntime:
    owner = CatalogLocalEmbeddingOwnerAdmission.for_indexing_service(
        engine,
        LocalEmbeddingOwnerConfiguration(
            EmbeddingRegistryOwnerConfiguration(
                selection.corpus_id,
                namespace,
                selection.runtime_profile.space,
                selection.recipe,
                selection.source_classes,
            ),
            selection.native_execution_policy,
            selection.native_execution_policy_sha256,
        ),
        source_authority=authority,
        settings=catalog_settings,
    )
    with publisher.sessions.begin() as session:
        query = owner.current_reconciliation_lookup(session)
        if query is not None:
            owner.resolve_reconciliation_controls(session, query, selection.runtime_profile)
    executor = CatalogNativeEmbeddingExecutor(
        owner=owner,
        publisher=publisher,
        execution_backend=FixedCpuDocumentEmbeddingExecution(launcher),
        runtime_profile=selection.runtime_profile,
        source_commit=pin.runtime_source_commit,
    )
    runner = WorkflowRunner(
        engine,
        settings=WorkflowSettings(),
        catalog=WorkflowCatalogService(engine, catalog_settings),
        actor_authorizer=OperatorIdentityWorkflowActorAuthorizer(
            SqlAlchemyOperatorActorSource(engine)
        ),
        readiness=IndexingRoleExecutionDisabled(),
        available_roles=frozenset(),
        local_embedding_owner=owner,
        local_embedding_executor=executor,
        command_families=frozenset({CommandExecutionFamily.LOCAL_EMBEDDING}),
        command_actor_selection=NativeCommandActorSelection(
            "local_indexing_service", pin.service.service_id, namespace, pin.service
        ),
        runner_config=RunnerConfig(
            version=1,
            poll_interval_seconds=5,
            command_lease_seconds=900,
            command_lease_heartbeat_seconds=30,
            max_commands_per_run=64,
        ),
    )
    reconciliation = LocalEmbeddingServiceReconciliation(
        executor, maximum_targets=selection.maximum_targets
    )
    return LocalIndexingNamespaceRuntime(namespace, runner, reconciliation)
