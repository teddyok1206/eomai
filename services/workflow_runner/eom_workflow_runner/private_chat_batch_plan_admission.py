"""Original private Chat sources around finite parent metadata; never GPU authority."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Literal

from eom_catalog_contracts.public_solution_embedding_index import PublicSolutionIndexNamespace
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryCaller
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_workflow.embedding_batch_plan_family import (
    SupportedEmbeddingBatchRequest,
    parse_embedding_batch_plan_request,
)
from eom_workflow.embedding_batch_plan_v17 import (
    EmbeddingBatchPlanRequestV17,
    EmbeddingBatchSelectionV17,
    build_private_chat_batch_query_context,
    validate_private_query_batch_controls,
)
from eom_workflow.embedding_device_routing import EmbeddingDeviceRoutingPolicy
from eom_workflow.local_embedding_execution_policy import validate_query_runtime_bundle
from eom_workflow.private_chat_query_execution_v2 import (
    PrivateChatQueryExecutionPolicyV2,
    PrivateChatQueryWorkflowRequestV2,
)
from eom_workflow.private_chat_query_submission_context import (
    build_private_chat_query_submission_context,
)
from sqlalchemy.orm import Session

from eom_workflow_runner.embedding_batch_plan_admission import (
    CatalogEmbeddingBatchPlanAdmission,
    EmbeddingBatchPlanOwnerConfiguration,
    resolve_embedding_batch_plan_controls,
)
from eom_workflow_runner.private_chat_query_owner_admission import (
    CatalogPrivateChatQueryOwnerAdmission,
)
from eom_workflow_runner.private_chat_query_preparation import (
    prepare_private_chat_query_request_in_session,
)
from eom_workflow_runner.private_chat_query_source_read import (
    ResolvedPrivateChatPublicQuerySources,
    read_pinned_supported_private_chat_query_controls,
    require_private_chat_query_source_root,
)


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("PRIVATE_CHAT_BATCH_PLAN_ADMISSION_INVALID")


@dataclass(frozen=True, slots=True)
class ResolvedPrivateChatBatchPlanSources:
    """Small checked controls only; no question, saved authority or physical execution proof."""

    selection: EmbeddingBatchSelectionV17
    policy: EmbeddingDeviceRoutingPolicy


class CatalogPrivateChatBatchPlanAdmission:
    """Actual private owners for both devices; public Reference admission is not borrowed."""

    def __init__(
        self,
        cpu: CatalogPrivateChatQueryOwnerAdmission,
        cuda: CatalogPrivateChatQueryOwnerAdmission,
        caller: EmbeddingRegistryCaller,
        configuration: EmbeddingBatchPlanOwnerConfiguration,
    ) -> None:
        _require(
            type(cpu) is CatalogPrivateChatQueryOwnerAdmission
            and type(cuda) is CatalogPrivateChatQueryOwnerAdmission
            and type(caller) is EmbeddingRegistryCaller
        )
        configuration.__post_init__()
        cpu_config, cuda_config = cpu.configuration.registry, cuda.configuration.registry
        scope = configuration.source_scope
        _require(
            cpu.catalog.engine is cuda.catalog.engine
            and cpu.settings == cuda.settings
            and cpu_config.space.runtime.device == "CPU"
            and cuda_config.space.runtime.device == "CUDA"
            and cpu_config.corpus_id == cuda_config.corpus_id == scope.corpus_id
            and cpu_config.namespace == scope.namespace
            and cpu_config.recipe == cuda_config.recipe
            and cpu_config.source_classes == cuda_config.source_classes
            and isinstance(cpu_config.namespace, PublicSolutionIndexNamespace)
            and isinstance(cuda_config.namespace, PublicSolutionIndexNamespace)
            and cpu_config.namespace.model_dump(exclude={"space_sha256"})
            == cuda_config.namespace.model_dump(exclude={"space_sha256"})
        )
        self.cpu, self.cuda, self.caller, self.configuration = cpu, cuda, caller, configuration
        self.catalog = cpu.catalog

    @contextmanager
    def admit(
        self, session: Session, request: SupportedEmbeddingBatchRequest
    ) -> Iterator[ResolvedPrivateChatBatchPlanSources]:
        request = parse_embedding_batch_plan_request(request)
        _require(type(request) is EmbeddingBatchPlanRequestV17)
        assert isinstance(request, EmbeddingBatchPlanRequestV17)
        root = require_private_chat_query_source_root(session)
        _require(
            session.get_bind() is self.catalog.engine
            and request.routing_policy == self.configuration.routing_policy
            and request.routing_policy_sha256 == self.configuration.routing_policy_sha256
            and request.scope.actor_id == self.caller.operator_id
        )
        self.cpu.sources.identity.fence_current_operator(session, self.caller.operator_id)
        self.cuda.sources.identity.fence_current_operator(session, self.caller.operator_id)
        reader = PinnedArtifactReadContext.for_session(session, self.cpu.settings)
        selection, routing = resolve_embedding_batch_plan_controls(reader, request)
        _require(isinstance(selection, EmbeddingBatchSelectionV17))
        assert isinstance(selection, EmbeddingBatchSelectionV17)
        scope, registry = self.configuration.source_scope, self.cpu.configuration.registry
        _require(
            selection.corpus_id == scope.corpus_id
            and selection.graph_snapshot == scope.graph_snapshot
            and selection.access_policy_revision_id == scope.policy_revision_id
            and selection.scope.access_policy_sha256 == scope.policy_sha256
            and selection.scope.storage_partition == registry.namespace.storage_partition
            and selection.recipe == registry.recipe
            and selection.source_classes == registry.source_classes
            and selection.query.maximum_sources <= scope.maximum_sources
            and routing.cpu.profile.space == registry.space
            and routing.cuda.profile.space == self.cuda.configuration.registry.space
        )
        cpu_policy, cpu_bundle = read_pinned_supported_private_chat_query_controls(
            reader, self.cpu.configuration
        )
        cuda_policy, cuda_bundle = read_pinned_supported_private_chat_query_controls(
            reader, self.cuda.configuration
        )
        _require(
            isinstance(cpu_policy, PrivateChatQueryExecutionPolicyV2)
            and isinstance(cuda_policy, PrivateChatQueryExecutionPolicyV2)
            and selection.private_policies.cpu.member
            == self.cpu.configuration.native_execution_policy
            and selection.private_policies.cuda.member
            == self.cuda.configuration.native_execution_policy
        )
        assert isinstance(cpu_policy, PrivateChatQueryExecutionPolicyV2)
        assert isinstance(cuda_policy, PrivateChatQueryExecutionPolicyV2)
        validate_private_query_batch_controls(request, selection, routing, cpu_policy, cuda_policy)
        for policy, bundle in ((cpu_policy, cpu_bundle), (cuda_policy, cuda_bundle)):
            validate_query_runtime_bundle(
                policy.spaces, policy.runtime_bundle, policy.resource_profile, bundle
            )
        checked: list[
            tuple[CatalogPrivateChatQueryOwnerAdmission, ResolvedPrivateChatPublicQuerySources]
        ] = []
        owners: tuple[tuple[Literal["CPU", "CUDA"], CatalogPrivateChatQueryOwnerAdmission], ...] = (
            ("CPU", self.cpu),
            ("CUDA", self.cuda),
        )
        for device, owner in owners:
            if selection.index_pair.select(device).index is None:
                continue
            child = prepare_private_chat_query_request_in_session(
                session,
                caller=self.caller,
                context=build_private_chat_batch_query_context(selection, device),
                owner=owner,
                artifact_reader=reader,
            )
            _require(isinstance(child, PrivateChatQueryWorkflowRequestV2))
            assert isinstance(child, PrivateChatQueryWorkflowRequestV2)
            sources = owner.resolve_submission(
                session, child, build_private_chat_query_submission_context(child, selection.origin)
            )
            checked.append((owner, sources))
        _require(require_private_chat_query_source_root(session) is root)
        yield ResolvedPrivateChatBatchPlanSources(selection, routing)
        _require(require_private_chat_query_source_root(session) is root)
        for owner, original in checked:
            current = owner.resolve_submission(
                session,
                original.request,
                build_private_chat_query_submission_context(original.request, selection.origin),
            )
            _require(current == original)
        reader.revalidate_provenance()
        _require(require_private_chat_query_source_root(session) is root)


type SupportedEmbeddingBatchPlanAdmission = (
    CatalogEmbeddingBatchPlanAdmission | CatalogPrivateChatBatchPlanAdmission
)
