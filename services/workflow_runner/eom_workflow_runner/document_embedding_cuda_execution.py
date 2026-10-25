"""One existing namespace Workflow through its original finite CUDA parent execution."""

from __future__ import annotations

from enum import StrEnum
from threading import Lock
from typing import Literal

from eom_catalog_contracts.embedding_work_batch import (
    MAX_EMBEDDING_WORK_BATCH_SECONDS,
    MAX_EMBEDDING_WORK_BATCH_VECTOR_BYTES,
    EmbeddingWorkBatchInput,
)
from eom_catalog_contracts.inference_transfer_embedding import (
    IncrementalEmbeddingResult,
    validate_incremental_embedding_result,
)
from eom_identifiers import content_sha256
from eom_workflow.embedding_batch_plan import (
    BATCH_PLAN_PROTOCOL,
    EmbeddingBatchBound,
    EmbeddingBatchPlanRequest,
)
from eom_workflow.local_embedding_encoding_dispatch import SupportedEmbeddingIntent
from eom_workflow.local_embedding_request_v2 import (
    SupportedLocalEmbeddingRequest,
    parse_supported_local_embedding_request,
    supported_local_embedding_request_actor,
)
from sqlalchemy.orm import Session

from eom_workflow_runner.document_embedding_batch_material import stage_batch_document_publication
from eom_workflow_runner.document_embedding_execution import (
    DocumentEmbeddingOutput,
    DocumentExecutionState,
    OwnedDocumentEmbedding,
)
from eom_workflow_runner.embedding_batch_execution import (
    ActiveEmbeddingBatchExecution,
    PublishedEmbeddingBatchExecution,
)
from eom_workflow_runner.embedding_batch_source_authorization import (
    CatalogEmbeddingBatchSourceAuthorization,
    DocumentBatchSource,
)
from eom_workflow_runner.local_embedding_encoding_admission import CatalogEncodingOwnerAdmission
from eom_workflow_runner.local_embedding_execution_port import NativeFencedRunnerTransaction
from eom_workflow_runner.local_embedding_owner_admission import CatalogLocalEmbeddingOwnerAdmission
from eom_workflow_runner.models import WorkflowInstanceRecord


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("DOCUMENT_CUDA_EXECUTION_INVALID")


def document_embedding_batch_workflow_key(parent: EmbeddingBatchPlanRequest) -> str:
    """Original parent/namespace relation in the existing unique Workflow key, not authority."""
    parent = EmbeddingBatchPlanRequest.model_validate(parent)
    _require(parent.purpose == "INDEX" and len(parent.child_selection_sha256s) == 1)
    return "embedding-batch-index:" + content_sha256(
        {
            "parent_request_sha256": parent.request_sha256,
            "child_selection_sha256": parent.child_selection_sha256s[0],
        }
    ).removeprefix("sha256:")


class _Phase(StrEnum):
    READY = "READY"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    INTERRUPTED = "INTERRUPTED"


class CatalogCudaDocumentEmbeddingExecution:
    """No reservations, DB mutations, model restart, device switching or NAS writes here.

    Each existing INDEX namespace/view is one Workflow. All its owned rows share
    the original finite native model scope. The common executor retains source
    ownership, unique encoding reservations, canonical commit and index assembly.
    """

    def __init__(
        self,
        active: ActiveEmbeddingBatchExecution,
        owner: CatalogLocalEmbeddingOwnerAdmission,
        request: SupportedLocalEmbeddingRequest,
    ) -> None:
        _require(
            type(active) is ActiveEmbeddingBatchExecution
            and type(owner) is CatalogLocalEmbeddingOwnerAdmission
        )
        operation = active.operation
        _require(
            operation.publisher.engine is owner.catalog.engine
            and operation.publisher.settings.nas_artifact_root == owner.settings.nas_artifact_root
            and active.request.purpose == "INDEX"
            and active.history.route is not None
            and active.history.route.decision.selected.backend.device == "CUDA"
        )
        with (
            operation.publisher.sessions.begin() as session,
            operation.admission.admit(session, active.request) as sources,
        ):
            self.selection = sources.selection
        assert active.history.route is not None
        self.active, self.owner = active, owner
        self.decision = active.history.route.decision
        self.request = parse_supported_local_embedding_request(request)
        self.workflow_key = document_embedding_batch_workflow_key(active.request)
        self._lock = Lock()
        self._phase = _Phase.READY
        self._intent: SupportedEmbeddingIntent | None = None
        self._work: OwnedDocumentEmbedding | None = None
        self._saved: PublishedEmbeddingBatchExecution | None = None
        self._validate_request(self.request)

    @property
    def device(self) -> Literal["CUDA"]:
        return "CUDA"

    def _validate_request(self, request: SupportedLocalEmbeddingRequest) -> None:
        request = parse_supported_local_embedding_request(request)
        actor_kind, actor_id = supported_local_embedding_request_actor(request)
        registry, selection = self.owner.configuration.registry, self.selection
        profile, config = self.decision.selected.profile, self.owner.configuration
        _require(
            request == self.request
            and selection.views == (request.namespace.view,)
            and registry.namespace == request.namespace
            and registry.corpus_id == selection.corpus_id == request.corpus_id
            and registry.space == profile.space == request.space
            and registry.recipe == selection.recipe
            and request.graph_snapshot == selection.graph_snapshot
            and request.access_policy_revision_id == selection.access_policy_revision_id
            and request.access_policy_sha256 == selection.scope.access_policy_sha256
            and request.namespace.storage_partition == selection.scope.storage_partition
            and selection.scope.actor_kind
            == {"human": "OPERATOR", "local_indexing_service": "LOCAL_INDEXING_SERVICE"}[actor_kind]
            and selection.scope.actor_id == actor_id
            and request.runtime_bundle == profile.runtime_bundle
            and request.resource_profile == profile.resource_profile
            and request.native_execution_policy == config.native_execution_policy
            and request.native_execution_policy_sha256 == config.native_execution_policy_sha256
        )

    def _original_workflow(self, session: Session, intent: SupportedEmbeddingIntent) -> None:
        _require(
            intent.workflow_request_sha256 == self.request.request_sha256
            and intent.source_plan == self.request.source_plan
            and intent.source_plan_sha256 == self.request.source_plan_sha256
            and intent.resource_profile_sha256
            == self.request.resource_profile.resource_profile_sha256
        )
        workflow = session.get(WorkflowInstanceRecord, intent.workflow_id, populate_existing=True)
        _require(workflow is not None)
        assert workflow is not None
        self.validate_workflow(workflow)
        with self._lock:
            _require(self._intent is None or self._intent == intent)
            self._intent = intent

    def validate_workflow(self, workflow: WorkflowInstanceRecord) -> None:
        """Pure original-parent relationship, not current actor/source/claim authority."""
        actor_kind, actor_id = supported_local_embedding_request_actor(self.request)
        _require(
            workflow.idempotency_key == self.workflow_key
            and workflow.initial_request == self.request.model_dump(mode="json")
            and workflow.created_actor_type == actor_kind
            and workflow.created_actor_id == actor_id
        )

    def assert_current_runtime(self, request: SupportedLocalEmbeddingRequest) -> None:
        self._validate_request(request)
        with self._lock:
            phase = self._phase
        _require(phase in {_Phase.READY, _Phase.COMPLETED})
        if phase is _Phase.READY:
            self.active.channel.require_direct_peer()

    def observe(self, intent: SupportedEmbeddingIntent) -> DocumentExecutionState:
        # Current source/lease checks belong to CatalogEncodingOwnerAdmission.
        # This indexed immutable relationship alone is not a permission carrier.
        with self.active.operation.publisher.sessions.begin() as session:
            self._original_workflow(session, intent)
        with self._lock:
            phase = self._phase
        if phase is _Phase.COMPLETED:
            return DocumentExecutionState.SUCCEEDED
        if phase is not _Phase.READY:
            return DocumentExecutionState.UNCERTAIN
        self.active.channel.require_direct_peer()
        return DocumentExecutionState.NOT_STARTED

    def execute(
        self,
        work: OwnedDocumentEmbedding,
        *,
        source: CatalogEncodingOwnerAdmission,
        transaction: NativeFencedRunnerTransaction,
    ) -> DocumentEmbeddingOutput:
        _require(
            type(work) is OwnedDocumentEmbedding
            and type(source) is CatalogEncodingOwnerAdmission
            and source.owner is self.owner
            and source.execution.request == self.request
            and source.execution.intent == work.association.intent
            and source.execution_backend is self
        )
        self._validate_request(source.execution.request)
        with transaction() as session:
            current = source.resolve_launch(session, work.association)
            plan = current.scope.plan
            self._original_workflow(session, work.association.intent)
            _require(
                current.owned_input == work.request
                and plan.recipe == self.selection.recipe
                and {s.item_revision_id: s for s in plan.sources}
                == {a.source.item_revision_id: a.source for a in self.selection.anchors}
            )
        with self._lock:
            if self._phase is _Phase.COMPLETED:
                _require(self._work == work and self._saved is not None)
                saved = self._saved
            else:
                _require(self._phase is _Phase.READY)
                self._work, self._phase = work, _Phase.EXECUTING
                saved = None
        if saved is None:
            try:
                saved = self._run(work, source, transaction)
                with self._lock:
                    self._saved, self._phase = saved, _Phase.COMPLETED
            except BaseException:
                with self._lock:
                    self._phase = _Phase.INTERRUPTED
                raise
        # Original compute/publication receipt is retained even if child staging
        # below is interrupted. Replay can reuse it, never grant another model run.
        saved.verified.assert_current()
        current_source = DocumentBatchSource(source, work.association, transaction)
        authorization = CatalogEmbeddingBatchSourceAuthorization(
            saved.verified.staged.batch, (current_source,)
        )
        authorization.authorize_batch()
        _require(len(saved.verified.result.children) == len(saved.verified.child_vectors) == 1)
        result = saved.verified.result.children[0].result
        _require(isinstance(result, IncrementalEmbeddingResult))
        assert isinstance(result, IncrementalEmbeddingResult)
        validate_incremental_embedding_result(work.request, result)
        return stage_batch_document_publication(work, result, saved.verified.child_vectors[0])

    def _run(
        self,
        work: OwnedDocumentEmbedding,
        source: CatalogEncodingOwnerAdmission,
        transaction: NativeFencedRunnerTransaction,
    ) -> PublishedEmbeddingBatchExecution:
        scope, resources = self.active.request.scope, self.request.resource_profile
        body = dict(
            schema_version="embedding-work-batch-input/1.0",
            purpose="DOCUMENT",
            scope=scope.model_dump(mode="json"),
            routing_decision_sha256=self.decision.decision_sha256,
            resource_profile_sha256=resources.resource_profile_sha256,
            timeout_seconds=min(resources.timeout_seconds, MAX_EMBEDDING_WORK_BATCH_SECONDS),
            vector_max_bytes=MAX_EMBEDDING_WORK_BATCH_VECTOR_BYTES,
            children=[
                dict(scope_sha256=scope.scope_sha256, request=work.request.model_dump(mode="json"))
            ],
        )
        batch = EmbeddingWorkBatchInput.model_validate(
            body | {"request_sha256": content_sha256(body)}
        )
        route = self.active.history.route
        assert route is not None
        intent = work.association.intent
        body = dict(
            schema_version=BATCH_PLAN_PROTOCOL,
            message_type="BOUND",
            request_sha256=self.active.request.request_sha256,
            route_record_sha256=route.record_sha256,
            batch_request_sha256=batch.request_sha256,
            resource_profile_sha256=resources.resource_profile_sha256,
            children=[
                dict(
                    selection_sha256=self.active.request.child_selection_sha256s[0],
                    workflow_id=intent.workflow_id,
                    step_run_id=intent.step_run_id,
                    native_job_id=intent.native_launch_job_id,
                    workflow_request_sha256=self.request.request_sha256,
                    launch_association_sha256=work.association.association_sha256,
                    native_input_sha256=work.request.request_sha256,
                )
            ],
        )
        binding = EmbeddingBatchBound.model_validate(body | {"record_sha256": content_sha256(body)})
        authorization = CatalogEmbeddingBatchSourceAuthorization(
            batch, (DocumentBatchSource(source, work.association, transaction),)
        )
        return self.active.run(binding, batch, authorization=authorization)
