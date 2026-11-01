"""Current private origin → original common index pair; no native work or saved authority."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.private_chat_query_prepare import private_chat_query_context_request_id
from eom_catalog_contracts.private_chat_query_prepare_v2 import PrivateChatQueryPrepareRequestV2
from eom_catalog_contracts.private_chat_query_read import ChatPrivateQueryOrigin
from eom_catalog_contracts.private_chat_similarity_v2 import PrivateChatSimilarityRequestV2
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryLookup,
    PrivateChatContextPreparation,
)
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_orchestrator.file_set_control_artifacts import (
    CONTROL_FILE_SET_PROTOCOL,
    ControlFileSetPublisher,
)
from eom_orchestrator.local_embedding_control_artifacts import (
    BATCH_SELECTION_ARTIFACT_TYPE,
    LocalEmbeddingControlArtifactPublisher,
)
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.embedding_batch_plan import EmbeddingBatchAllocation
from eom_workflow.embedding_batch_plan_v17 import (
    BATCH_SELECTION_V17_SCHEMA_REF,
    EmbeddingBatchPlanRequestV17,
    EmbeddingBatchSelectionV17,
    build_private_chat_batch_query_context,
    private_chat_batch_parent_request_sha256,
)
from eom_workflow.embedding_device_routing import EmbeddingDeviceRoutingPolicy
from eom_workflow.private_chat_query_execution_v2 import PrivateChatQueryExecutionPolicyV2
from eom_workflow.private_chat_query_owner_configuration import (
    PrivateChatQueryPublicServiceConfiguration,
    require_private_chat_public_query_policies,
)
from eom_workflow.private_chat_query_submission_context import private_chat_query_origin_key
from sqlalchemy.orm import Session

from eom_workflow_runner.embedding_batch_allocation_candidate import (
    new_embedding_batch_allocation_candidate,
)
from eom_workflow_runner.embedding_batch_execution import CatalogEmbeddingBatchExecution
from eom_workflow_runner.embedding_batch_plan_admission import EmbeddingBatchPlanOwnerConfiguration
from eom_workflow_runner.private_chat_batch_plan_admission import (
    CatalogPrivateChatBatchPlanAdmission,
)
from eom_workflow_runner.private_chat_query_owner_admission import (
    CatalogPrivateChatQueryOwnerAdmission,
)
from eom_workflow_runner.private_chat_query_source_read import (
    require_private_chat_query_source_root,
)


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("PRIVATE_CHAT_BATCH_SELECTION_INVALID")


@dataclass(frozen=True, slots=True)
class PreparedPrivateChatBatchSelection:
    manifest: ArtifactMemberPointer
    parent: EmbeddingBatchPlanRequestV17
    selection: EmbeddingBatchSelectionV17
    operation: CatalogEmbeddingBatchExecution
    routing_policy: EmbeddingDeviceRoutingPolicy

    def context(self, device: Literal["CPU", "CUDA"]) -> PrivateChatSimilarityRequestV2:
        return build_private_chat_batch_query_context(self.selection, device)

    def allocation_candidate(self) -> EmbeddingBatchAllocation:
        return new_embedding_batch_allocation_candidate(self.parent, self.routing_policy)


class CatalogPrivateChatBatchSelection:
    """One indexed original selection, with actual private/public fences on every call.

    Metadata publication is not admission to compute. A caller must still open
    the returned existing batch operation under its current native claim/lease.
    """

    def __init__(
        self,
        *,
        cpu: CatalogPrivateChatQueryOwnerAdmission,
        cuda: CatalogPrivateChatQueryOwnerAdmission,
        publisher: ControlFileSetPublisher,
        configuration: PrivateChatQueryPublicServiceConfiguration,
        policy: EmbeddingDeviceRoutingPolicy,
        cpu_policy: PrivateChatQueryExecutionPolicyV2,
        cuda_policy: PrivateChatQueryExecutionPolicyV2,
        origin: ChatPrivateQueryOrigin,
        source_commit: str,
        controller_release: str,
        maximum_sources: int = 16384,
        top_k: int = 8,
    ) -> None:
        configuration = PrivateChatQueryPublicServiceConfiguration.model_validate(
            raw_similarity_contract_value(configuration)
        )
        require_private_chat_public_query_policies(configuration, policy, cpu_policy, cuda_policy)
        _require(type(cpu) is type(cuda) is CatalogPrivateChatQueryOwnerAdmission)
        _require(
            publisher.engine is cpu.catalog.engine is cuda.catalog.engine
            and publisher.settings.nas_artifact_root == cpu.settings.nas_artifact_root
            and cpu.settings == cuda.settings
            and cpu.configuration.registry.namespace == configuration.namespace
            and cpu.configuration.registry.corpus_id == configuration.corpus_id
            and cpu.configuration.registry.recipe == configuration.recipe
            and cpu.configuration.registry.source_classes == configuration.source_classes
            and type(maximum_sources) is int
            and 1 <= maximum_sources <= 16384
            and type(top_k) is int
            and 1 <= top_k <= 64
        )
        for owner, expected, member, digest in (
            (
                cpu,
                cpu_policy,
                configuration.native_execution_policy,
                configuration.native_execution_policy_sha256,
            ),
            (
                cuda,
                cuda_policy,
                configuration.cuda_native_execution_policy,
                configuration.cuda_native_execution_policy_sha256,
            ),
        ):
            _require(
                owner.configuration.registry.space == expected.spaces.document
                and owner.configuration.native_execution_policy == member
                and owner.configuration.native_execution_policy_sha256 == digest
                and owner.configuration.runtime_bundle == expected.runtime_bundle
            )
        self.cpu, self.cuda, self.publisher = cpu, cuda, publisher
        self.configuration, self.policy = configuration, policy
        self.origin = ChatPrivateQueryOrigin.model_validate(raw_similarity_contract_value(origin))
        self.caller = EmbeddingRegistryCaller(self.origin.actor_id)
        self.spaces = (cpu_policy.spaces, cuda_policy.spaces)
        self.maximum_sources, self.top_k = maximum_sources, top_k
        self.source_commit, self.controller_release = source_commit, controller_release
        self.controls = LocalEmbeddingControlArtifactPublisher(
            publisher, source_commit=source_commit
        )

    def _scope(
        self,
        owner: CatalogPrivateChatQueryOwnerAdmission,
        request: PrivateChatQueryPrepareRequestV2,
    ) -> EmbeddingRegistryLookup:
        registry = owner.configuration.registry
        return EmbeddingRegistryLookup(
            registry.corpus_id,
            registry.namespace,
            request.graph_snapshot,
            request.policy_revision_id,
            request.policy_sha256,
            self.maximum_sources,
        )

    def _authorize(self, session: Session, request: PrivateChatQueryPrepareRequestV2) -> None:
        root = require_private_chat_query_source_root(session)
        _require(session.get_bind() is self.publisher.engine and request.origin == self.origin)
        for owner in (self.cpu, self.cuda):
            owner.sources.identity.fence_current_operator(session, self.origin.actor_id)
            current = owner.sources.chat.authorize(self.origin)
            _require(
                ChatPrivateQueryOrigin.model_validate(raw_similarity_contract_value(current))
                == self.origin
            )
            owner.catalog.authorize_scope(session, self.caller, self._scope(owner, request))
        _require(require_private_chat_query_source_root(session) is root)

    def _new_selection(
        self, request: PrivateChatQueryPrepareRequestV2
    ) -> EmbeddingBatchSelectionV17:
        with self.publisher.sessions.begin() as session:
            self._authorize(session, request)
            contexts = []
            for owner, spaces in zip((self.cpu, self.cuda), self.spaces, strict=True):
                context = owner.catalog.prepare_private_chat_context_in_session(
                    session,
                    self.caller,
                    PrivateChatContextPreparation(
                        private_chat_query_context_request_id(self.origin),
                        self.origin.basis,
                        self._scope(owner, request),
                        spaces,
                        self.top_k,
                    ),
                )
                _require(isinstance(context, PrivateChatSimilarityRequestV2))
                assert isinstance(context, PrivateChatSimilarityRequestV2)
                _require(
                    context.query_basis == self.origin.basis
                    and context.graph_snapshot == request.graph_snapshot
                    and context.policy_revision_id == request.policy_revision_id
                    and context.policy_sha256 == request.policy_sha256
                    and context.request_id == private_chat_query_context_request_id(self.origin)
                    and context.source_classes == self.configuration.source_classes
                    and context.maximum_sources == self.maximum_sources
                    and context.top_k == self.top_k
                )
                contexts.append(context)
            scope = dict(
                actor_kind="OPERATOR",
                actor_id=self.origin.actor_id,
                storage_partition=self.configuration.namespace.storage_partition,
                access_policy_sha256=request.policy_sha256,
            )
            body = dict(
                schema_version="embedding-batch-plan/1.7",
                message_type="SELECTION",
                purpose="PRIVATE_CHAT_QUERY",
                scope=scope | {"scope_sha256": content_sha256(scope)},
                corpus_id=self.configuration.corpus_id,
                graph_snapshot=request.graph_snapshot.model_dump(mode="json"),
                access_policy_revision_id=request.policy_revision_id,
                origin=self.origin.model_dump(mode="json"),
                recipe=self.configuration.recipe.model_dump(mode="json"),
                views=["CONCRETE_FACETS"],
                source_classes=self.configuration.source_classes,
                query=dict(
                    consumer_purpose="GENERAL_CHAT_READ",
                    context_request_id=private_chat_query_context_request_id(self.origin),
                    maximum_sources=self.maximum_sources,
                    top_k=self.top_k,
                ),
                index_pair=dict(cpu=contexts[0].views[0], cuda=contexts[1].views[0]),
                private_policies=dict(
                    cpu=dict(
                        member=self.configuration.native_execution_policy,
                        policy_sha256=self.configuration.native_execution_policy_sha256,
                    ),
                    cuda=dict(
                        member=self.configuration.cuda_native_execution_policy,
                        policy_sha256=self.configuration.cuda_native_execution_policy_sha256,
                    ),
                ),
            )
            selection = EmbeddingBatchSelectionV17.model_validate(
                body | {"selection_sha256": content_sha256(body)}
            )
            self._authorize(session, request)
            return selection

    def _read_selection(
        self, pointer: ArtifactMemberPointer, request: PrivateChatQueryPrepareRequestV2
    ) -> EmbeddingBatchSelectionV17:
        with self.publisher.sessions.begin() as session:
            self._authorize(session, request)
            reader = PinnedArtifactReadContext.for_session(session, self.cpu.settings)
            reader.prefetch(((pointer.artifact_id, pointer.artifact_revision_id),))
            _require(
                pointer.member_path == "selection.json"
                and pointer.schema_ref == BATCH_SELECTION_V17_SCHEMA_REF
                and pointer.media_type == "application/json"
            )
            reader.require_file_set(
                pointer.artifact_id,
                pointer.artifact_revision_id,
                (pointer.member_path,),
                manifest_version=CONTROL_FILE_SET_PROTOCOL,
            )
            raw = reader.read_pinned(
                **pointer.model_dump(mode="python"),
                expected_artifact_types=(BATCH_SELECTION_ARTIFACT_TYPE,),
                expected_primary_file="selection.json",
                max_bytes=512 * 1024,
            ).payload
            selection = EmbeddingBatchSelectionV17.model_validate(json.loads(raw))
            _require(canonical_json_bytes(selection) == raw)
            reader.revalidate_provenance()
            self._authorize(session, request)
            return selection

    def prepare(
        self, request: PrivateChatQueryPrepareRequestV2
    ) -> PreparedPrivateChatBatchSelection:
        request = PrivateChatQueryPrepareRequestV2.model_validate(
            raw_similarity_contract_value(request)
        )
        _require(request.action == "PREPARE_PRIVATE_CHAT_QUERY" and request.origin == self.origin)
        admission = CatalogPrivateChatBatchPlanAdmission(
            self.cpu,
            self.cuda,
            self.caller,
            EmbeddingBatchPlanOwnerConfiguration(
                self._scope(self.cpu, request),
                self.configuration.routing_policy,
                self.configuration.routing_policy_sha256,
            ),
        )
        original_key = content_sha256({"origin_key": private_chat_query_origin_key(self.origin)})[
            7:
        ]
        key = "private-chat-batch-selection:" + original_key
        with self.publisher.sessions.begin() as session:
            self._authorize(session, request)
        pointer = self.publisher.find_published_primary_member(
            idempotency_key=key, artifact_type=BATCH_SELECTION_ARTIFACT_TYPE
        )
        if pointer is None:
            selected = self._new_selection(request)
            pointer = self.controls.reuse_or_publish_batch_selection(selected, idempotency_key=key)
        selected = self._read_selection(pointer, request)
        _require(
            selected.origin == self.origin
            and selected.graph_snapshot == request.graph_snapshot
            and selected.access_policy_revision_id == request.policy_revision_id
            and selected.scope.access_policy_sha256 == request.policy_sha256
            and selected.query.maximum_sources == self.maximum_sources
            and selected.query.top_k == self.top_k
        )
        body = dict(
            schema_version="embedding-batch-plan/1.7",
            message_type="REQUEST",
            batch_id="embeddingbatch_" + original_key[:32],
            parent_request_sha256=private_chat_batch_parent_request_sha256(selected),
            purpose="PRIVATE_CHAT_QUERY",
            scope=selected.scope,
            selection_manifest=pointer,
            selection_sha256=selected.selection_sha256,
            routing_policy=self.configuration.routing_policy,
            routing_policy_sha256=self.configuration.routing_policy_sha256,
            child_selection_sha256s=selected.child_selection_sha256s,
        )
        parent = EmbeddingBatchPlanRequestV17.model_validate(
            body | {"request_sha256": content_sha256(body)}
        )
        with (
            self.publisher.sessions.begin() as session,
            admission.admit(session, parent) as current,
        ):
            _require(current.selection == selected and current.policy == self.policy)
            self._authorize(session, request)
        operation = CatalogEmbeddingBatchExecution(
            admission,
            self.publisher,
            source_commit=self.source_commit,
            controller_release=self.controller_release,
        )
        return PreparedPrivateChatBatchSelection(pointer, parent, selected, operation, self.policy)
