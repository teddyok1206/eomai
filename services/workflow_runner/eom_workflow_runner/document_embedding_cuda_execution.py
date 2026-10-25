"""One existing namespace Workflow through its original finite CUDA parent execution."""

from __future__ import annotations

from enum import StrEnum
from threading import Lock
from typing import Literal

from eom_catalog_contracts.inference_transfer_embedding import (
    IncrementalEmbeddingResult,
    validate_incremental_embedding_result,
)
from eom_workflow.local_embedding_encoding_dispatch import SupportedEmbeddingIntent
from eom_workflow.local_embedding_request_v2 import (
    SupportedLocalEmbeddingRequest,
)
from sqlalchemy.orm import Session

from eom_workflow_runner.document_embedding_batch_context import (
    OriginalDocumentEmbeddingBatchContext,
)
from eom_workflow_runner.document_embedding_batch_context import (
    document_embedding_batch_workflow_key as document_embedding_batch_workflow_key,
)
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
        _require(
            active.request.purpose == "INDEX"
            and active.history.route is not None
            and active.history.route.decision.selected.backend.device == "CUDA"
        )
        assert active.history.route is not None
        self.active = active
        self.context = OriginalDocumentEmbeddingBatchContext(
            active.operation, active.request, active.history.route.decision, owner, request
        )
        self._lock = Lock()
        self._phase = _Phase.READY
        self._intent: SupportedEmbeddingIntent | None = None
        self._work: OwnedDocumentEmbedding | None = None
        self._saved: PublishedEmbeddingBatchExecution | None = None

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

    def _validate_request(self, request: SupportedLocalEmbeddingRequest) -> None:
        self.context.validate_request(request)

    def _original_workflow(self, session: Session, intent: SupportedEmbeddingIntent) -> None:
        self.context.validate_intent(session, intent)
        with self._lock:
            _require(self._intent is None or self._intent == intent)
            self._intent = intent

    def validate_workflow(self, workflow: WorkflowInstanceRecord) -> None:
        """Pure original-parent relationship, not current actor/source/claim authority."""
        self.context.validate_workflow(workflow)

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
        self.context.authorize_work(work, source, transaction)
        with self._lock:
            _require(self._intent is None or self._intent == work.association.intent)
            self._intent = work.association.intent
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
        route = self.active.history.route
        assert route is not None
        binding, batch = self.context.binding(work, route.record_sha256)
        authorization = CatalogEmbeddingBatchSourceAuthorization(
            batch, (DocumentBatchSource(source, work.association, transaction),)
        )
        return self.active.run(binding, batch, authorization=authorization)
