"""Read an original committed CUDA completion; no root dispatch or history mutation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from eom_catalog_contracts.inference_transfer_embedding import IncrementalEmbeddingResult
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.embedding_batch_plan_store import (
    EmbeddingBatchPlanHistory,
    EmbeddingBatchPlanStore,
)
from eom_orchestrator.file_set_control_artifacts import CONTROL_FILE_SET_PROTOCOL
from eom_orchestrator.local_embedding_control_artifacts import (
    BATCH_EXECUTION_RECEIPT_ARTIFACT_TYPE,
    LocalEmbeddingControlArtifactPublisher,
)
from eom_workflow.embedding_batch_execution_receipt import (
    MAX_BATCH_EXECUTION_RECEIPT_BYTES,
    EmbeddingBatchExecutionReceipt,
)
from eom_workflow.embedding_batch_plan_family import (
    SupportedEmbeddingBatchRequest,
    parse_embedding_batch_plan_request,
)
from eom_workflow.local_embedding_encoding_dispatch import SupportedEmbeddingIntent
from eom_workflow.local_embedding_request_v2 import SupportedLocalEmbeddingRequest

from eom_workflow_runner.document_embedding_batch_context import (
    OriginalDocumentEmbeddingBatchContext,
)
from eom_workflow_runner.document_embedding_batch_material import stage_batch_document_publication
from eom_workflow_runner.document_embedding_execution import (
    DocumentEmbeddingOutput,
    DocumentExecutionState,
    OwnedDocumentEmbedding,
)
from eom_workflow_runner.embedding_batch_execution import CatalogEmbeddingBatchExecution
from eom_workflow_runner.embedding_batch_result_read import read_completed_embedding_batch_result
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
        raise ValueError("DOCUMENT_BATCH_RECOVERY_INVALID")


@dataclass(frozen=True, slots=True)
class CompletedDocumentEmbeddingBatch:
    """Pinned canonical metadata, not a cached actor/source/lease capability."""

    history: EmbeddingBatchPlanHistory
    receipt: EmbeddingBatchExecutionReceipt


def read_document_embedding_completion(
    operation: CatalogEmbeddingBatchExecution, parent: SupportedEmbeddingBatchRequest
) -> CompletedDocumentEmbeddingBatch | None:
    """Exact indexed original publication lookup. Missing completion never starts compute."""
    _require(type(operation) is CatalogEmbeddingBatchExecution)
    parent = parse_embedding_batch_plan_request(parent)
    _require(parent.purpose == "INDEX" and len(parent.child_selection_sha256s) == 1)
    with (
        operation.publisher.sessions.begin() as session,
        operation.admission.admit(session, parent) as sources,
    ):
        history = EmbeddingBatchPlanStore(parent, sources.selection, sources.policy).read(session)
        if history is None or history.state != "SUCCEEDED" or history.failure is not None:
            return None
        _require(history.route is not None and history.bound is not None)
        assert history.route is not None
        if history.route.decision.selected.backend.device != "CUDA":
            return None
        controls = LocalEmbeddingControlArtifactPublisher(
            operation.publisher, source_commit=operation.source_commit
        )
        pointer = controls.find_batch_execution_receipt(
            parent_request_sha256=parent.request_sha256,
            allocation_record_sha256=history.allocation.record_sha256,
        )
        if pointer is None:
            return None
        reader = PinnedArtifactReadContext.for_session(
            session, operation.admission.catalog.settings
        )
        reader.prefetch(((pointer.artifact_id, pointer.artifact_revision_id),))
        reader.require_file_set(
            pointer.artifact_id,
            pointer.artifact_revision_id,
            ("receipt.json",),
            manifest_version=CONTROL_FILE_SET_PROTOCOL,
        )
        raw = reader.read_pinned(
            **pointer.model_dump(mode="python"),
            expected_artifact_types=(BATCH_EXECUTION_RECEIPT_ARTIFACT_TYPE,),
            expected_primary_file="receipt.json",
            max_bytes=MAX_BATCH_EXECUTION_RECEIPT_BYTES,
        ).payload
        receipt = EmbeddingBatchExecutionReceipt.model_validate_json(raw)
        _require(
            canonical_json_bytes(receipt.model_dump(mode="json")) == raw
            and receipt.parent_plan_job_id == history.job_id
            and receipt.purpose == "INDEX"
            and receipt.scope == parent.scope
            and receipt.allocation == history.allocation.control_request
            and receipt.bound.binding == history.bound
            and receipt.completed.grant.routing_decision_sha256
            == history.route.decision.decision_sha256
            and len(receipt.children) == 1
        )
        reader.revalidate_provenance()
        return CompletedDocumentEmbeddingBatch(history, receipt)


class CatalogRecoveredCudaDocumentEmbeddingExecution:
    """Resume existing reservations/publication only after original canonical completion."""

    def __init__(
        self,
        operation: CatalogEmbeddingBatchExecution,
        parent: SupportedEmbeddingBatchRequest,
        completed: CompletedDocumentEmbeddingBatch,
        owner: CatalogLocalEmbeddingOwnerAdmission,
        request: SupportedLocalEmbeddingRequest,
    ) -> None:
        _require(type(completed) is CompletedDocumentEmbeddingBatch)
        _require(completed.history.route is not None)
        assert completed.history.route is not None
        self.context = OriginalDocumentEmbeddingBatchContext(
            operation, parent, completed.history.route.decision, owner, request
        )
        self.completed = completed
        self._current()

    @property
    def device(self) -> Literal["CUDA"]:
        return "CUDA"

    @property
    def owner(self) -> CatalogLocalEmbeddingOwnerAdmission:
        return self.context.owner

    @property
    def request(self) -> SupportedLocalEmbeddingRequest:
        return self.context.request

    @property
    def workflow_key(self) -> str:
        return self.context.workflow_key

    def _current(self) -> None:
        _require(
            read_document_embedding_completion(self.context.operation, self.context.parent)
            == self.completed
        )
        original = self.completed.receipt.bound.binding.children[0]
        with self.context.operation.publisher.sessions.begin() as session:
            self.owner.resolve_sources(session, self.request)
            workflow = session.get(
                WorkflowInstanceRecord, original.workflow_id, populate_existing=True
            )
            _require(
                workflow is not None and workflow.state in {"REQUESTED", "RUNNING", "COMPLETED"}
            )
            assert workflow is not None
            self.context.validate_workflow(workflow)
            _require(original.workflow_request_sha256 == self.request.request_sha256)

    def validate_workflow(self, workflow: WorkflowInstanceRecord) -> None:
        self.context.validate_workflow(workflow)

    def assert_current_runtime(self, request: SupportedLocalEmbeddingRequest) -> None:
        self.context.validate_request(request)
        self._current()

    def observe(self, intent: SupportedEmbeddingIntent) -> DocumentExecutionState:
        with self.context.operation.publisher.sessions.begin() as session:
            self.context.validate_intent(session, intent)
        self._current()
        bound = self.completed.receipt.bound.binding.children[0]
        _require(
            bound.workflow_id == intent.workflow_id
            and bound.step_run_id == intent.step_run_id
            and bound.native_job_id == intent.native_launch_job_id
        )
        return DocumentExecutionState.SUCCEEDED

    def execute(
        self,
        work: OwnedDocumentEmbedding,
        *,
        source: CatalogEncodingOwnerAdmission,
        transaction: NativeFencedRunnerTransaction,
    ) -> DocumentEmbeddingOutput:
        _require(source.execution_backend is self)
        self.context.authorize_work(work, source, transaction)
        self._current()
        route = self.completed.history.route
        assert route is not None
        binding, batch = self.context.binding(work, route.record_sha256)
        _require(binding == self.completed.receipt.bound.binding)
        authorization = CatalogEmbeddingBatchSourceAuthorization(
            batch, (DocumentBatchSource(source, work.association, transaction),)
        )
        verified = read_completed_embedding_batch_result(
            self.completed.receipt, authorization=authorization
        )
        _require(len(verified.result.children) == len(verified.child_vectors) == 1)
        # The common executor still owns Artifact commit, encoding completion and
        # index assembly. This is the same explicit child materialization boundary.
        result = verified.result.children[0].result
        _require(isinstance(result, IncrementalEmbeddingResult))
        assert isinstance(result, IncrementalEmbeddingResult)
        return stage_batch_document_publication(work, result, verified.child_vectors[0])
