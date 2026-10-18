"""Actual live-origin composition over existing native owners; never a human capture."""

from __future__ import annotations

import re
from dataclasses import dataclass

from eom_catalog_contracts.embedding_reference_query import (
    ReferenceQuerySpaces,
    raw_similarity_contract_value,
)
from eom_catalog_contracts.private_chat_query_read import ChatPrivateQueryOrigin
from eom_catalog_service.settings import CatalogSettings
from eom_catalog_service.workflow_catalog import WorkflowCatalogService
from eom_identity_service.operator_authorization_fence_sql import OperatorAuthorizationFenceOwnerPin
from eom_identity_service.owned_operator_authorization_fence import OwnedOperatorAuthorizationFence
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.general_chat_private_query_client import GeneralChatPrivateQueryClient
from eom_orchestrator.native_private_chat_query_systemd import FixedNativePrivateQueryLauncher
from sqlalchemy import Engine

from eom_workflow_runner.actor_authorization_adapters import (
    OperatorIdentityWorkflowActorAuthorizer,
    SqlAlchemyOperatorActorSource,
)
from eom_workflow_runner.engine import WorkflowRunner
from eom_workflow_runner.native_query_prepare_driver import NativeQueryPrepareDriver
from eom_workflow_runner.private_chat_query_native_executor import (
    CatalogNativePrivateChatQueryExecutor,
)
from eom_workflow_runner.private_chat_query_owner_admission import (
    CatalogPrivateChatQueryOwnerAdmission,
)
from eom_workflow_runner.private_chat_query_prepare_application import (
    NativePrivateChatQueryPreparation,
)
from eom_workflow_runner.private_chat_query_prepare_dispatch import (
    NativePrivateChatQueryPrepareDispatch,
)
from eom_workflow_runner.private_chat_query_source_read import (
    CatalogPrivateChatQuerySourceOwner,
    PrivateChatQueryOwnerConfiguration,
)
from eom_workflow_runner.readiness import (
    ReadinessStatus,
    RuntimeReadinessCheck,
    RuntimeReadinessReport,
)
from eom_workflow_runner.repository import CommandExecutionFamily, NativeCommandActorSelection
from eom_workflow_runner.settings import RunnerConfig, WorkflowSettings


class PrivateChatRoleExecutionDisabled:
    def evaluate(self) -> RuntimeReadinessReport:
        return RuntimeReadinessReport(
            (
                RuntimeReadinessCheck(
                    "role_execution",
                    ReadinessStatus.FAIL,
                    "PRIVATE_CHAT_QUERY_ROLE_DISABLED",
                    "this owner processes only original private native QUERY commands",
                ),
            )
        )


@dataclass(frozen=True, slots=True)
class PrivateChatQueryOwnerFactory:
    engine: Engine
    publisher: ControlFileSetPublisher
    settings: CatalogSettings
    configuration: PrivateChatQueryOwnerConfiguration
    spaces: ReferenceQuerySpaces
    operator_owner: OperatorAuthorizationFenceOwnerPin
    chat: GeneralChatPrivateQueryClient
    launcher: FixedNativePrivateQueryLauncher
    driver: NativeQueryPrepareDriver
    source_commit: str

    def __post_init__(self) -> None:
        if (
            type(self.configuration) is not PrivateChatQueryOwnerConfiguration
            or type(self.operator_owner) is not OperatorAuthorizationFenceOwnerPin
        ):
            raise ValueError("PRIVATE_CHAT_QUERY_OWNER_COMPOSITION_INVALID")
        self.configuration.__post_init__()
        self.operator_owner.__post_init__()
        spaces = ReferenceQuerySpaces.model_validate(raw_similarity_contract_value(self.spaces))
        if (
            self.publisher.engine is not self.engine
            or self.publisher.settings.nas_artifact_root != self.settings.nas_artifact_root
            or self.configuration.registry.namespace.view != "CONTENT_ONLY"
            or self.configuration.registry.space != spaces.document
            or type(self.chat) is not GeneralChatPrivateQueryClient
            or type(self.launcher) is not FixedNativePrivateQueryLauncher
            or type(self.driver) is not NativeQueryPrepareDriver
            or type(self.operator_owner) is not OperatorAuthorizationFenceOwnerPin
            or type(self.source_commit) is not str
            or re.fullmatch(r"[0-9a-f]{40}", self.source_commit) is None
        ):
            raise ValueError("PRIVATE_CHAT_QUERY_OWNER_COMPOSITION_INVALID")
        object.__setattr__(self, "spaces", spaces)

    def application(self, origin: ChatPrivateQueryOrigin) -> NativePrivateChatQueryPrepareDispatch:
        """Bind one live original; no local queue/claim/model work during construction."""
        self.__post_init__()
        origin = ChatPrivateQueryOrigin.model_validate(raw_similarity_contract_value(origin))
        self.launcher.assert_current_runtime()
        current = ChatPrivateQueryOrigin.model_validate(
            raw_similarity_contract_value(self.chat.authorize(origin))
        )
        if current != origin:
            raise ValueError("PRIVATE_CHAT_QUERY_OWNER_ORIGIN_INVALID")
        self.launcher.assert_current_runtime()
        sources = CatalogPrivateChatQuerySourceOwner(
            self.engine,
            self.configuration,
            chat=self.chat,
            identity_fence=OwnedOperatorAuthorizationFence(self.operator_owner, origin.actor_id),
            settings=self.settings,
        )
        owner = CatalogPrivateChatQueryOwnerAdmission(sources)
        executor = CatalogNativePrivateChatQueryExecutor(
            owner=owner,
            publisher=self.publisher,
            launcher=self.launcher,
            source_commit=self.source_commit,
        )
        runner = WorkflowRunner(
            self.engine,
            WorkflowSettings(),
            catalog=WorkflowCatalogService(self.engine, self.settings),
            actor_authorizer=OperatorIdentityWorkflowActorAuthorizer(
                SqlAlchemyOperatorActorSource(self.engine)
            ),
            readiness=PrivateChatRoleExecutionDisabled(),
            available_roles=frozenset(),
            private_chat_query_owner=owner,
            private_chat_query_executor=executor,
            command_families=frozenset({CommandExecutionFamily.PRIVATE_CHAT_QUERY}),
            command_actor_selection=NativeCommandActorSelection("human", origin.actor_id),
            runner_config=RunnerConfig(
                version=1,
                poll_interval_seconds=5,
                command_lease_seconds=900,
                command_lease_heartbeat_seconds=30,
                max_commands_per_run=1,
            ),
        )
        return NativePrivateChatQueryPrepareDispatch(
            NativePrivateChatQueryPreparation(
                owner=owner,
                executor=executor,
                runner=runner,
                driver=self.driver,
            ),
            self.spaces,
        )
