"""Existing actual-actor owners reauthorize exact batch children; no allocation or launch."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from eom_catalog_contracts.embedding_reference_query_v11 import EmbeddingReferenceQueryInputV11
from eom_catalog_contracts.embedding_work_batch import (
    EmbeddingWorkBatchChild,
    EmbeddingWorkBatchInput,
    parse_embedding_work_batch_input,
)
from eom_orchestrator.native_reference_query_coordinator import read_native_reference_query_launch
from eom_workflow.embedding_batch_plan import EmbeddingBatchChildBinding
from eom_workflow.local_embedding_encoding_dispatch import (
    SupportedEmbeddingAssociation,
    parse_supported_embedding_association,
)
from eom_workflow.local_embedding_request_v2 import supported_local_embedding_request_actor
from eom_workflow.reference_query_execution import (
    ReferenceQueryLaunchAssociation,
    SupportedReferenceQueryWorkflowRequest,
    parse_reference_query_launch_association,
    parse_supported_reference_query_workflow_request,
)

from eom_workflow_runner.local_embedding_encoding_admission import CatalogEncodingOwnerAdmission
from eom_workflow_runner.local_embedding_execution_port import NativeFencedRunnerTransaction
from eom_workflow_runner.reference_query_owner_admission import (
    CatalogReferenceQueryOwnerAdmission,
    validate_current_reference_query_input,
)
from eom_workflow_runner.repository import CommandLeaseIdentity, require_command_lease


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("EMBEDDING_BATCH_SOURCE_AUTHORIZATION_INVALID")


@dataclass(frozen=True, slots=True)
class DocumentBatchSource:
    """Operation-local existing owner/association, not a persistent permission carrier."""

    owner: CatalogEncodingOwnerAdmission
    association: SupportedEmbeddingAssociation
    transaction: NativeFencedRunnerTransaction

    def __post_init__(self) -> None:
        _require(type(self.owner) is CatalogEncodingOwnerAdmission and callable(self.transaction))
        association = parse_supported_embedding_association(self.association)
        _require(association.intent == self.owner.execution.intent)
        object.__setattr__(self, "association", association)

    @property
    def input_sha256(self) -> str:
        return self.association.owned_input_request_sha256

    def authorize(self, batch: EmbeddingWorkBatchInput, child: EmbeddingWorkBatchChild) -> None:
        _require(batch.purpose == "DOCUMENT")
        with self.transaction() as session:
            current = self.owner.resolve_launch(session, self.association)
            request = current.scope.workflow_request
            kind, actor_id = supported_local_embedding_request_actor(request)
            _require(
                current.owned_input == child.request
                and request.request_sha256 == self.owner.execution.request.request_sha256
                and batch.scope.actor_kind
                == {"human": "OPERATOR", "local_indexing_service": "LOCAL_INDEXING_SERVICE"}[kind]
                and batch.scope.actor_id == actor_id
                and batch.scope.storage_partition == request.namespace.storage_partition
                and batch.scope.access_policy_sha256 == request.access_policy_sha256
                and batch.resource_profile_sha256
                == request.resource_profile.resource_profile_sha256
            )
            # Artifact validation may consume time. Repeat the current actor/lease
            # fence before leaving this short root, never cache a successful fence.
            self.owner.owner.fence_current_actor(session, request)
            require_command_lease(session, self.owner.execution.command_lease)


@dataclass(frozen=True, slots=True)
class ReferenceQueryBatchSource:
    owner: CatalogReferenceQueryOwnerAdmission
    request: SupportedReferenceQueryWorkflowRequest
    launch: ReferenceQueryLaunchAssociation
    command_lease: CommandLeaseIdentity
    transaction: NativeFencedRunnerTransaction

    def __post_init__(self) -> None:
        _require(
            type(self.owner) is CatalogReferenceQueryOwnerAdmission
            and type(self.command_lease) is CommandLeaseIdentity
            and callable(self.transaction)
        )
        request = parse_supported_reference_query_workflow_request(self.request)
        launch = parse_reference_query_launch_association(self.launch)
        _require(launch.workflow_request_sha256 == request.request_sha256)
        object.__setattr__(self, "request", request)
        object.__setattr__(self, "launch", launch)

    @property
    def input_sha256(self) -> str:
        return self.launch.query_request_sha256

    def authorize(self, batch: EmbeddingWorkBatchInput, child: EmbeddingWorkBatchChild) -> None:
        _require(batch.purpose == "REFERENCE_QUERY")
        _require(isinstance(child.request, EmbeddingReferenceQueryInputV11))
        assert isinstance(child.request, EmbeddingReferenceQueryInputV11)
        with self.transaction() as session:
            current = self.owner.resolve_execution_sources(
                session,
                self.request,
                self.command_lease,
                workflow_id=self.launch.workflow_id,
                step_run_id=self.launch.step_run_id,
            )
            _require(
                read_native_reference_query_launch(
                    session,
                    request=self.request,
                    workflow_id=self.launch.workflow_id,
                    step_run_id=self.launch.step_run_id,
                )
                == self.launch
            )
            validate_current_reference_query_input(current, self.launch, child.request)
            _require(
                batch.scope.actor_kind == "OPERATOR"
                and batch.scope.actor_id == current.request.operator_audit.operator_id
                and batch.scope.access_policy_sha256
                == current.request.context_request.policy_sha256
                and batch.resource_profile_sha256
                == current.request.resource_profile.resource_profile_sha256
            )
            self.owner.identity.fence_current_operator(
                session, current.request.operator_audit.operator_id
            )
            require_command_lease(session, self.command_lease)


type BatchSource = DocumentBatchSource | ReferenceQueryBatchSource


class CatalogEmbeddingBatchSourceAuthorization:
    """One immutable local batch and O(1) child lookup; every call reopens its own fence.

    This is the source side of the root controller port, not its allocation admission.
    Trusted composition supplies already-selected original owners and transactions.
    No SQL root, decoded Artifact, authenticated result or lease is cached here.
    """

    def __init__(self, batch: EmbeddingWorkBatchInput, sources: tuple[BatchSource, ...]) -> None:
        batch = parse_embedding_work_batch_input(batch)
        _require(type(sources) is tuple and len(sources) == len(batch.children))
        expected = DocumentBatchSource if batch.purpose == "DOCUMENT" else ReferenceQueryBatchSource
        _require(all(type(source) is expected for source in sources))
        keys = tuple(source.input_sha256 for source in sources)
        _require(keys == tuple(child.request.request_sha256 for child in batch.children))
        _require(len(set(keys)) == len(keys))
        self._batch = batch
        self._children = MappingProxyType(
            {child.request.request_sha256: child for child in batch.children}
        )
        self._sources = MappingProxyType(dict(zip(keys, sources, strict=True)))

    def authorize_child(self, batch_request_sha256: str, child_request_sha256: str) -> None:
        """Small immutable identity arguments; never receive arbitrary source/role authority."""
        _require(
            type(batch_request_sha256) is str and batch_request_sha256 == self._batch.request_sha256
        )
        _require(type(child_request_sha256) is str and child_request_sha256 in self._sources)
        self._sources[child_request_sha256].authorize(
            self._batch, self._children[child_request_sha256]
        )

    def authorize_batch(self) -> None:
        for child in self._batch.children:
            self.authorize_child(self._batch.request_sha256, child.request.request_sha256)

    def authorize_binding(self, binding: EmbeddingBatchChildBinding) -> None:
        """Validate the original canonical Workflow/Job references before plan BOUND writes."""
        binding = EmbeddingBatchChildBinding.model_validate(binding)
        _require(binding.native_input_sha256 in self._sources)
        source = self._sources[binding.native_input_sha256]
        if isinstance(source, DocumentBatchSource):
            association = source.association
            intent = association.intent
            expected = (
                intent.workflow_id,
                intent.step_run_id,
                intent.native_launch_job_id,
                source.owner.execution.request.request_sha256,
                association.association_sha256,
            )
        else:
            launch = source.launch
            expected = (
                launch.workflow_id,
                launch.step_run_id,
                launch.native_launch_job_id,
                source.request.request_sha256,
                launch.association_sha256,
            )
        _require(
            (
                binding.workflow_id,
                binding.step_run_id,
                binding.native_job_id,
                binding.workflow_request_sha256,
                binding.launch_association_sha256,
            )
            == expected
        )
        self.authorize_child(self._batch.request_sha256, binding.native_input_sha256)
