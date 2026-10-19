"""Fixed current-capture service composition; no login, service actor or automatic claim."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from eom_catalog_contracts.embedding_reference_query import ReferenceQuerySpaces
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryOwnerConfiguration
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.settings import CatalogSettings
from eom_catalog_service.workflow_catalog import WorkflowCatalogService
from eom_identity_service import (
    AuthenticatedOperatorSession,
    AuthenticatedSessionFence,
    AuthenticatedSessionFenceOwnerPin,
    identity_provider_code_members,
)
from eom_identity_service.installed_owner_session_provider import (
    ProtectedInstalledIdentityProviderAdmission,
)
from eom_orchestrator.database import build_native_embedding_controller_engine
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.inference_transfer_cpu_handoff import (
    fixed_owner_identity,
    protected_cpu_handoff_directory,
)
from eom_orchestrator.native_embedding_cpu_execution import validate_fixed_native_cpu_resources
from eom_orchestrator.native_embedding_query_systemd import FixedNativeQueryLauncher
from eom_orchestrator.settings import Settings
from eom_workflow.local_indexing_owner_configuration import LocalIndexingOwnerDatabasePin
from eom_workflow.reference_query_owner_configuration import (
    SupportedReferenceQueryServiceConfiguration,
    validate_supported_reference_query_service_configuration,
)
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from eom_workflow_runner.actor_authorization_adapters import (
    OperatorIdentityWorkflowActorAuthorizer,
    SqlAlchemyOperatorActorSource,
)
from eom_workflow_runner.engine import WorkflowRunner
from eom_workflow_runner.local_indexing_runtime_verification import FixedIndexingRuntimeVerification
from eom_workflow_runner.readiness import (
    ReadinessStatus,
    RuntimeReadinessCheck,
    RuntimeReadinessReport,
)
from eom_workflow_runner.reference_query_native_executor import CatalogNativeReferenceQueryExecutor
from eom_workflow_runner.reference_query_owner_admission import CatalogReferenceQueryOwnerAdmission
from eom_workflow_runner.reference_query_prepare_application import NativeReferenceQueryPreparation
from eom_workflow_runner.reference_query_prepare_driver import ReferenceQueryPrepareDriver
from eom_workflow_runner.reference_query_source_read import (
    ReferenceQueryOwnerConfiguration,
    read_selected_reference_query_controls,
)
from eom_workflow_runner.repository import CommandExecutionFamily, NativeCommandActorSelection
from eom_workflow_runner.settings import RunnerConfig, WorkflowSettings

REFERENCE_QUERY_SERVICE_STATE_ROOT = Path("/var/lib/eom-workflow-runner/reference-query-owner")


def require_reference_query_database_owner(
    session: Session, expected: LocalIndexingOwnerDatabasePin
) -> None:
    """Read-only connection compatibility; never an actual-human/source grant."""
    role_name, session_role, role_oid = session.execute(
        text(
            "SELECT CURRENT_USER,SESSION_USER,role.oid::pg_catalog.int8 "
            "FROM pg_catalog.pg_roles role WHERE role.rolname=CURRENT_USER"
        )
    ).one()
    if (
        role_name != session_role
        or role_name != expected.role_name
        or type(role_oid) is not int
        or role_oid != expected.role_oid
    ):
        raise ValueError("REFERENCE_QUERY_OWNER_DATABASE_ROLE_MISMATCH")


class ReferenceQueryRoleExecutionDisabled:
    def evaluate(self) -> RuntimeReadinessReport:
        return RuntimeReadinessReport(
            (
                RuntimeReadinessCheck(
                    "role_execution",
                    ReadinessStatus.FAIL,
                    "REFERENCE_QUERY_ROLE_DISABLED",
                    "native QUERY only",
                ),
            )
        )


def require_current_reference_query_provider(
    admission: ProtectedInstalledIdentityProviderAdmission,
    configuration: SupportedReferenceQueryServiceConfiguration,
) -> None:
    if type(admission) is not ProtectedInstalledIdentityProviderAdmission:
        raise ValueError("REFERENCE_QUERY_OWNER_PROVIDER_UNAVAILABLE")
    selected = configuration.api_provider
    members = tuple(pin.member for pin in selected.code_members)
    observed = tuple(sorted(admission.observation.code, key=lambda member: str(member.path)))
    if (
        members != identity_provider_code_members()
        or len(observed) != len(members)
        or any(
            not str(current.path).endswith("/" + expected.member)
            or current.sha256 != expected.sha256
            for current, expected in zip(observed, selected.code_members, strict=True)
        )
    ):
        raise ValueError("REFERENCE_QUERY_OWNER_PROVIDER_UNAVAILABLE")
    admission.assert_current(
        source_commit=selected.source_commit,
        wheel_sha256=selected.wheel_sha256,
        configuration_sha256=selected.configuration_sha256,
    )


@dataclass(frozen=True, slots=True)
class ReferenceQueryOwnerRuntime:
    engine: Engine
    configuration: SupportedReferenceQueryServiceConfiguration
    publisher: ControlFileSetPublisher
    catalog_settings: CatalogSettings
    owner_configuration: ReferenceQueryOwnerConfiguration
    spaces: ReferenceQuerySpaces
    launcher: FixedNativeQueryLauncher
    admission: ProtectedInstalledIdentityProviderAdmission
    driver: ReferenceQueryPrepareDriver

    def application(self, capture: AuthenticatedOperatorSession) -> NativeReferenceQueryPreparation:
        """Construct an operation-local actual-human owner; no retained capture registry."""
        require_current_reference_query_provider(self.admission, self.configuration)
        if type(capture) is not AuthenticatedOperatorSession:
            raise ValueError("REFERENCE_QUERY_OWNER_CAPTURE_UNAVAILABLE")
        owner = CatalogReferenceQueryOwnerAdmission(
            self.engine,
            self.owner_configuration,
            capture=capture,
            session_fence=AuthenticatedSessionFence(
                AuthenticatedSessionFenceOwnerPin(
                    self.configuration.database_owner.role_name,
                    self.configuration.database_owner.role_oid,
                    900,
                )
            ),
            settings=self.catalog_settings,
        )
        executor = CatalogNativeReferenceQueryExecutor(
            owner=owner,
            publisher=self.publisher,
            launcher=self.launcher,
            source_commit=self.configuration.owner_source_commit,
        )
        runner = WorkflowRunner(
            self.engine,
            WorkflowSettings(),
            catalog=WorkflowCatalogService(self.engine, self.catalog_settings),
            actor_authorizer=OperatorIdentityWorkflowActorAuthorizer(
                SqlAlchemyOperatorActorSource(self.engine)
            ),
            readiness=ReferenceQueryRoleExecutionDisabled(),
            available_roles=frozenset(),
            reference_query_owner=owner,
            reference_query_executor=executor,
            command_families=frozenset({CommandExecutionFamily.REFERENCE_QUERY}),
            command_actor_selection=NativeCommandActorSelection("human", capture.operator_id),
            runner_config=RunnerConfig(
                version=1,
                poll_interval_seconds=5,
                command_lease_seconds=900,
                command_lease_heartbeat_seconds=30,
                max_commands_per_run=1,
            ),
        )
        return NativeReferenceQueryPreparation(
            owner=owner, executor=executor, runner=runner, driver=self.driver, spaces=self.spaces
        )

    def close(self) -> None:
        self.driver.close()
        self.engine.dispose()


def build_reference_query_owner_runtime(
    configuration: SupportedReferenceQueryServiceConfiguration,
    admission: ProtectedInstalledIdentityProviderAdmission,
) -> ReferenceQueryOwnerRuntime:
    """Installed child preflight. No operator capture, queue work, native run or NAS commit."""
    configuration = validate_supported_reference_query_service_configuration(configuration)
    require_current_reference_query_provider(admission, configuration)
    identity = fixed_owner_identity()
    if (os.geteuid(), os.getegid()) != (identity.owner_uid, identity.owner_gid) or os.getgroups():
        raise ValueError("REFERENCE_QUERY_OWNER_ACCOUNT_UNAVAILABLE")
    for path in (
        REFERENCE_QUERY_SERVICE_STATE_ROOT,
        REFERENCE_QUERY_SERVICE_STATE_ROOT / "workspaces",
        REFERENCE_QUERY_SERVICE_STATE_ROOT / "staging",
    ):
        with protected_cpu_handoff_directory(
            path, owner=identity, uid=identity.owner_uid, gid=identity.owner_gid, mode=0o700
        ):
            pass
    engine = build_native_embedding_controller_engine()
    try:
        settings = Settings(
            staging_root=REFERENCE_QUERY_SERVICE_STATE_ROOT / "staging",
            workspace_root=REFERENCE_QUERY_SERVICE_STATE_ROOT / "workspaces",
            runtime_source_commit=configuration.owner_source_commit,
        )
        publisher = ControlFileSetPublisher(engine, settings)
        catalog_settings = CatalogSettings(nas_artifact_root=settings.nas_artifact_root)
        with publisher.sessions.begin() as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            require_reference_query_database_owner(session, configuration.database_owner)
            policy, _bundle = read_selected_reference_query_controls(
                PinnedArtifactReadContext(session, catalog_settings),
                policy_member=configuration.native_execution_policy,
                policy_sha256=configuration.native_execution_policy_sha256,
                runtime_bundle=configuration.runtime_bundle,
            )
            validate_fixed_native_cpu_resources(policy.resource_profile)
            if policy.spaces.document.space_sha256 != configuration.namespace.space_sha256:
                raise ValueError("REFERENCE_QUERY_OWNER_SPACE_UNAVAILABLE")
        verifier = FixedIndexingRuntimeVerification(configuration.runtime_verifier)
        launcher = FixedNativeQueryLauncher(
            configuration.cpu_environment_raw_sha256.removeprefix("sha256:"),
            configuration.owner_environment_raw_sha256.removeprefix("sha256:"),
            verifier.assert_current,
        )
        launcher.assert_current_runtime()
        require_current_reference_query_provider(admission, configuration)
        return ReferenceQueryOwnerRuntime(
            engine,
            configuration,
            publisher,
            catalog_settings,
            ReferenceQueryOwnerConfiguration(
                EmbeddingRegistryOwnerConfiguration(
                    configuration.corpus_id,
                    configuration.namespace,
                    policy.spaces.document,
                    configuration.recipe,
                    configuration.source_classes,
                ),
                configuration.native_execution_policy,
                configuration.native_execution_policy_sha256,
                configuration.runtime_bundle,
            ),
            policy.spaces,
            launcher,
            admission,
            ReferenceQueryPrepareDriver(),
        )
    except Exception:
        engine.dispose()
        raise
