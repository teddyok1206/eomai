"""Official parent/source-fenced canonical batch receipt publication, never numerical dispatch."""

from __future__ import annotations

from collections.abc import Callable

from eom_catalog_service.embedding_batch_owner_channel import EmbeddingBatchOwnerChannel
from eom_orchestrator.embedding_batch_plan_store import EmbeddingBatchPlanStore
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.local_embedding_control_artifacts import (
    LocalEmbeddingControlArtifactPublisher,
    PublishedLocalEmbeddingControl,
    batch_execution_receipt_publication_key,
)
from eom_workflow.embedding_batch_plan_family import (
    SupportedEmbeddingBatchRequest,
    parse_embedding_batch_plan_request,
)

from eom_workflow_runner.embedding_batch_plan_admission import CatalogEmbeddingBatchPlanAdmission
from eom_workflow_runner.embedding_batch_result_read import VerifiedLocalEmbeddingBatchResult
from eom_workflow_runner.embedding_batch_source_authorization import (
    CatalogEmbeddingBatchSourceAuthorization,
)


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("EMBEDDING_BATCH_EXECUTION_PUBLICATION_INVALID")


class CatalogEmbeddingBatchExecutionPublication:
    """Original actual parent and child authorities surround the existing Artifact owner.

    A planning SUCCEEDED row is not numerical success. Root output verification
    is required separately; this use case only publishes its immutable metadata.
    Child outputs and native completion checkpoints remain their existing owners.
    """

    def __init__(
        self,
        admission: CatalogEmbeddingBatchPlanAdmission,
        request: SupportedEmbeddingBatchRequest,
        authorization: CatalogEmbeddingBatchSourceAuthorization,
        publisher: ControlFileSetPublisher,
        *,
        source_commit: str,
    ) -> None:
        _require(
            type(admission) is CatalogEmbeddingBatchPlanAdmission
            and type(authorization) is CatalogEmbeddingBatchSourceAuthorization
            and publisher.engine is admission.catalog.engine
            and publisher.settings.nas_artifact_root == admission.catalog.settings.nas_artifact_root
        )
        self.admission, self.authorization = admission, authorization
        self.request = parse_embedding_batch_plan_request(request)
        self.publisher = publisher
        self.controls = LocalEmbeddingControlArtifactPublisher(
            publisher, source_commit=source_commit
        )

    def publish(
        self, channel: EmbeddingBatchOwnerChannel, verified: VerifiedLocalEmbeddingBatchResult
    ) -> PublishedLocalEmbeddingControl:
        _require(type(verified) is VerifiedLocalEmbeddingBatchResult)
        request = self.request
        _require(
            channel.request.parent_request_sha256 == request.request_sha256
            and verified.staged.batch.request_sha256 == self.authorization.batch_request_sha256
            and verified.staged.batch.scope == request.scope
        )
        self._authorize()
        verified.assert_current()
        # This is only small receipt publication. No pending parent/child write,
        # inference or bulk binary IO crosses this independent publisher commit.
        with (
            self.publisher.sessions.begin() as session,
            self.admission.admit(session, request) as sources,
        ):
            history = EmbeddingBatchPlanStore(request, sources.selection, sources.policy).read(
                session
            )
            _require(
                history is not None
                and history.state == "SUCCEEDED"
                and history.failure is None
                and history.route is not None
                and history.bound == verified.staged.notice.binding
                and history.allocation.control_request == channel.request
            )
            assert history is not None and history.route is not None
            _require(
                history.route.decision.selected.backend.device == "CUDA"
                and history.route.decision.decision_sha256
                == verified.staged.batch.routing_decision_sha256
            )
            for child in verified.staged.notice.binding.children:
                self.authorization.authorize_binding(child)
            receipt = verified.receipt(history.job_id, channel)
            key = batch_execution_receipt_publication_key(
                request.request_sha256, history.allocation.record_sha256
            )
            result = self.controls.publish_batch_execution_receipt(receipt, idempotency_key=key)
            self._authorize()
            verified.assert_current()
            _require(result.semantic_sha256 == receipt.receipt_sha256)
        return result

    def _authorize(self) -> None:
        callback: Callable[[], object] = self.authorization.authorize_batch
        _require(callback() is None)
