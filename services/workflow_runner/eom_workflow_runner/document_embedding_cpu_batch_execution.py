"""Frozen precompute-unavailable route through the existing fixed CPU numerical owner."""

from __future__ import annotations

from threading import Lock
from typing import Literal

from eom_catalog_contracts.embedding_work_batch import MAX_EMBEDDING_WORK_BATCH_SECONDS
from eom_orchestrator.embedding_batch_plan_store import EmbeddingBatchPlanStore
from eom_workflow.embedding_batch_owner_control import validate_embedding_batch_owner_context
from eom_workflow.embedding_batch_plan_family import SupportedEmbeddingBatchRequest
from eom_workflow.local_embedding_encoding_dispatch import SupportedEmbeddingIntent
from eom_workflow.local_embedding_request_v2 import SupportedLocalEmbeddingRequest

from eom_workflow_runner.document_embedding_batch_context import (
    OriginalDocumentEmbeddingBatchContext,
)
from eom_workflow_runner.document_embedding_cpu_execution import FixedCpuDocumentEmbeddingExecution
from eom_workflow_runner.document_embedding_execution import (
    DocumentEmbeddingOutput,
    DocumentExecutionState,
    OwnedDocumentEmbedding,
)
from eom_workflow_runner.embedding_batch_execution import (
    CatalogEmbeddingBatchExecution,
    UnavailableEmbeddingBatchExecution,
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
        raise ValueError("DOCUMENT_CPU_ROUTE_INVALID")


class CatalogCpuDocumentBatchExecution:
    """No GPU exception handling. Only an original verified BUSY route can enter here.

    Parent planning remains metadata, not CPU numerical success. CPU completion,
    pending/uncertain work and exact result reuse belong to the unchanged fixed
    launcher and common encoding/Artifact/index application.
    """

    def __init__(
        self,
        operation: CatalogEmbeddingBatchExecution,
        parent: SupportedEmbeddingBatchRequest,
        unavailable: UnavailableEmbeddingBatchExecution,
        owner: CatalogLocalEmbeddingOwnerAdmission,
        request: SupportedLocalEmbeddingRequest,
        execution: FixedCpuDocumentEmbeddingExecution,
    ) -> None:
        _require(
            type(operation) is CatalogEmbeddingBatchExecution
            and type(unavailable) is UnavailableEmbeddingBatchExecution
            and type(execution) is FixedCpuDocumentEmbeddingExecution
            and request.resource_profile.device == "CPU"
            and request.resource_profile.timeout_seconds <= MAX_EMBEDDING_WORK_BATCH_SECONDS
        )
        route = unavailable.history.route
        _require(route is not None and route.decision.selected.backend.device == "CPU")
        assert route is not None
        self.context = OriginalDocumentEmbeddingBatchContext(
            operation, parent, route.decision, owner, request
        )
        self.unavailable, self.execution = unavailable, execution
        self._lock = Lock()
        self._intent: SupportedEmbeddingIntent | None = None
        self._require_original_route()

    @property
    def device(self) -> Literal["CPU"]:
        return "CPU"

    @property
    def owner(self) -> CatalogLocalEmbeddingOwnerAdmission:
        return self.context.owner

    @property
    def request(self) -> SupportedLocalEmbeddingRequest:
        return self.context.request

    @property
    def workflow_key(self) -> str:
        return self.context.workflow_key

    def _require_original_route(self) -> None:
        context, original = self.context, self.unavailable
        with (
            context.operation.publisher.sessions.begin() as session,
            context.operation.admission.admit(session, context.parent) as sources,
        ):
            current = EmbeddingBatchPlanStore(
                context.parent, sources.selection, sources.policy
            ).read(session)
            _require(
                current is not None
                and current.failure is None
                and current.state in {"RUNNING", "SUCCEEDED"}
                and current.allocation == original.history.allocation
                and current.route == original.history.route
                and current.route is not None
            )
            assert current is not None and current.route is not None
            observation = current.route.observation
            _require(
                observation.status == "BUSY"
                and observation.phase == "PRE_EXECUTION"
                and observation.cuda_launch_state == "NOT_STARTED"
                and observation.allocation_reference_sha256
                == original.root_observation.message_sha256
                and current.route.decision == context.decision
                and context.decision.reason == "GPU_BUSY_CPU_FALLBACK"
            )
            validate_embedding_batch_owner_context(
                current.allocation.control_request,
                context.operation.controller_release,
                original.root_observation,
            )

    def validate_workflow(self, workflow: WorkflowInstanceRecord) -> None:
        self.context.validate_workflow(workflow)

    def assert_current_runtime(self, request: SupportedLocalEmbeddingRequest) -> None:
        self.context.validate_request(request)
        self.execution.assert_current_runtime(request)

    def observe(self, intent: SupportedEmbeddingIntent) -> DocumentExecutionState:
        # Do not take a parent lock while a child SQL root may already be held.
        # Current child/source/lease checks and final binding remain separate.
        with self.context.operation.publisher.sessions.begin() as session:
            self.context.validate_intent(session, intent)
        with self._lock:
            _require(self._intent is None or self._intent == intent)
            self._intent = intent
        return self.execution.observe(intent)

    def execute(
        self,
        work: OwnedDocumentEmbedding,
        *,
        source: CatalogEncodingOwnerAdmission,
        transaction: NativeFencedRunnerTransaction,
    ) -> DocumentEmbeddingOutput | None:
        _require(source.execution_backend is self)
        self.context.authorize_work(work, source, transaction)
        with self._lock:
            _require(self._intent is None or self._intent == work.association.intent)
            self._intent = work.association.intent
        self._require_original_route()
        route = self.unavailable.history.route
        assert route is not None
        binding, batch = self.context.binding(work, route.record_sha256)
        authorization = CatalogEmbeddingBatchSourceAuthorization(
            batch, (DocumentBatchSource(source, work.association, transaction),)
        )
        operation, parent = self.context.operation, self.context.parent
        # No child SQL root is held through parent binding or numerical work.
        with (
            operation.publisher.sessions.begin() as session,
            operation.admission.admit(session, parent) as sources,
        ):
            EmbeddingBatchPlanStore(parent, sources.selection, sources.policy).bind(
                session, binding, batch, authorize_child=authorization.authorize_binding
            )
        return self.execution.execute(work, source=source, transaction=transaction)
