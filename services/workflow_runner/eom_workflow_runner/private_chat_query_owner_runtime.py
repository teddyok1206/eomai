"""Optional private composition over the existing installed non-root QUERY runtime."""

from __future__ import annotations

import os
from collections.abc import Callable

from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryOwnerConfiguration
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_identity_service.operator_authorization_fence_sql import OperatorAuthorizationFenceOwnerPin
from eom_orchestrator.general_chat_private_query_client import (
    GeneralChatPrivateQueryClient,
    fixed_private_chat_query_source_endpoint,
)
from eom_orchestrator.inference_transfer_cpu_handoff import fixed_owner_identity
from eom_orchestrator.native_embedding_cpu_execution import validate_fixed_native_cpu_resources
from eom_orchestrator.native_private_chat_query_systemd import FixedNativePrivateQueryLauncher
from eom_workflow.local_embedding_execution_policy import validate_query_runtime_bundle
from eom_workflow.private_chat_query_owner_configuration import (
    PrivateChatQueryServiceConfiguration,
    require_private_chat_query_reference_configuration,
)
from sqlalchemy import text

from eom_workflow_runner.private_chat_query_owner_factory import PrivateChatQueryOwnerFactory
from eom_workflow_runner.private_chat_query_source_read import (
    PrivateChatQueryOwnerConfiguration,
    read_pinned_private_chat_query_controls,
)
from eom_workflow_runner.reference_query_owner_runtime import (
    ReferenceQueryOwnerRuntime,
    require_current_reference_query_provider,
    require_reference_query_database_owner,
)


def build_private_chat_query_owner_factory(
    runtime: ReferenceQueryOwnerRuntime,
    configuration: PrivateChatQueryServiceConfiguration,
    *,
    configuration_guard: Callable[[], None],
) -> PrivateChatQueryOwnerFactory:
    """Read-only startup; no actor, session capture, native launch or extra lifecycle."""
    if type(runtime) is not ReferenceQueryOwnerRuntime or not callable(configuration_guard):
        raise ValueError("PRIVATE_CHAT_QUERY_OWNER_COMPOSITION_INVALID")
    configuration = PrivateChatQueryServiceConfiguration.model_validate(configuration)
    require_private_chat_query_reference_configuration(configuration, runtime.configuration)
    configuration_guard()
    require_current_reference_query_provider(runtime.admission, runtime.configuration)
    identity = fixed_owner_identity()
    if (os.geteuid(), os.getegid()) != (identity.owner_uid, identity.owner_gid) or os.getgroups():
        raise ValueError("PRIVATE_CHAT_QUERY_OWNER_ACCOUNT_UNAVAILABLE")
    if configuration.namespace.space_sha256 != runtime.spaces.document.space_sha256:
        raise ValueError("PRIVATE_CHAT_QUERY_OWNER_SPACE_UNAVAILABLE")
    endpoint = fixed_private_chat_query_source_endpoint()
    endpoint.require_socket()
    selected = PrivateChatQueryOwnerConfiguration(
        EmbeddingRegistryOwnerConfiguration(
            configuration.corpus_id,
            configuration.namespace,
            runtime.spaces.document,
            configuration.recipe,
            configuration.source_classes,
        ),
        configuration.native_execution_policy,
        configuration.native_execution_policy_sha256,
        configuration.runtime_bundle,
    )
    with runtime.publisher.sessions.begin() as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        require_reference_query_database_owner(session, runtime.configuration.database_owner)
        reader = PinnedArtifactReadContext(session, runtime.catalog_settings)
        policy, bundle = read_pinned_private_chat_query_controls(reader, selected)
        validate_query_runtime_bundle(
            policy.spaces, policy.runtime_bundle, policy.resource_profile, bundle
        )
        validate_fixed_native_cpu_resources(policy.resource_profile)
        if policy.spaces != runtime.spaces:
            raise ValueError("PRIVATE_CHAT_QUERY_OWNER_SPACE_UNAVAILABLE")
        reader.revalidate_provenance()
    launcher = FixedNativePrivateQueryLauncher(
        runtime.configuration.cpu_environment_raw_sha256.removeprefix("sha256:"),
        configuration.owner_environment_raw_sha256.removeprefix("sha256:"),
        runtime.launcher.assert_runtime_current,
    )
    launcher.assert_current_runtime()
    configuration_guard()
    require_current_reference_query_provider(runtime.admission, runtime.configuration)
    return PrivateChatQueryOwnerFactory(
        runtime.engine,
        runtime.publisher,
        runtime.catalog_settings,
        selected,
        policy.spaces,
        OperatorAuthorizationFenceOwnerPin(
            runtime.configuration.database_owner.role_name,
            runtime.configuration.database_owner.role_oid,
        ),
        GeneralChatPrivateQueryClient(endpoint),
        launcher,
        runtime.driver,
        runtime.configuration.owner_source_commit,
        configuration_guard,
    )
