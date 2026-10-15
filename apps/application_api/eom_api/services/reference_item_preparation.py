"""Current HTTP operator → existing native preparation → Catalog item-start context."""

from __future__ import annotations

from eom_catalog_contracts import (
    EducationalRetrievalRequirementV2,
    EvidenceBundlePublicationResultV5,
)
from eom_catalog_contracts.reference_query_prepare import ReferenceQueryPrepareRequest
from eom_identifiers import content_sha256
from eom_operator_identity import ActorContext
from eom_orchestrator.control_service import ControlPlaneError
from eom_workflow.control_plane import ExecutionPresetRevisionV2
from eom_workflow.models import ExpectedWorkflowResolution, WorkflowRequest
from eom_workflow_runner.item_similarity_preparation import (
    PreparedItemSimilarity,
    validate_item_similarity_start_inputs,
)

from eom_api.errors import ApiError
from eom_api.request_context import RequestContext
from eom_api.services.item_similarity_preparation import ItemSimilarityStartPreparationService
from eom_api.services.reference_item_start_ports import ReferenceItemStartPending
from eom_api.services.reference_query_preparation import ReferenceQueryPreparationApplicationService


class HttpReferenceItemStartPreparation:
    """Only operation-local RequestContext is retained; no actor/capture cache."""

    def __init__(
        self,
        context: RequestContext,
        queries: ReferenceQueryPreparationApplicationService,
        items: ItemSimilarityStartPreparationService,
    ) -> None:
        self.context, self.queries, self.items = context, queries, items

    def prepare(
        self,
        actor: ActorContext,
        *,
        workflow_request: WorkflowRequest,
        expected_resolution: ExpectedWorkflowResolution,
        evidence: EvidenceBundlePublicationResultV5,
        preset: ExecutionPresetRevisionV2,
        idempotency_key: str,
    ) -> PreparedItemSimilarity | ReferenceItemStartPending:
        if actor != self.context.actor():
            raise ApiError(403, "PERMISSION_DENIED", "Permission denied", "Current caller differs.")
        self.context.owner_capture()
        try:
            workflow_request, expected_resolution, evidence, preset = (
                validate_item_similarity_start_inputs(
                    workflow_request=workflow_request,
                    expected_resolution=expected_resolution,
                    evidence=evidence,
                    preset=preset,
                )
            )
        except ControlPlaneError as error:
            raise ApiError(
                409, error.code, "Reference controls differ", "Compatible inputs are not active."
            ) from None
        requirement = workflow_request.educational_retrieval
        assert isinstance(requirement, EducationalRetrievalRequirementV2)
        # The enclosing API claim already binds the complete Item request hash.
        # The domain key also scopes the QUERY to this actual operator/operation.
        key = idempotency_key + ":reference"
        operation = content_sha256({"purpose": "REFERENCE_ITEM_START/1.0", "key": key})
        body = {
            "schema_version": "system-rag-reference-query-prepare-request/1.0",
            "operation": "PREPARE_REFERENCE_QUERY",
            "operation_id": "queryprepare_" + operation.removeprefix("sha256:")[:32],
            "idempotency_key": key,
            "source_item_revision_id": requirement.past_exam_variation.source_item_revision_id,
            "graph_snapshot": evidence.graph_snapshot.model_dump(mode="json"),
            "policy_revision_id": evidence.access_policy_revision_id,
            "policy_sha256": evidence.access_policy_sha256,
        }
        query = ReferenceQueryPrepareRequest.model_validate(
            {**body, "request_sha256": content_sha256(body)}
        )
        reply = self.queries.prepare(self.context, query, idempotency_key=key)
        if reply.status == "PENDING":
            assert reply.workflow_id is not None
            return ReferenceItemStartPending(reply.workflow_id)
        if reply.status != "READY" or reply.selection is None:
            raise ApiError(
                409 if reply.status == "FAILED" else 503,
                reply.error_code or "REFERENCE_QUERY_PREPARE_UNAVAILABLE",
                "Reference preparation unavailable",
                "Retain the original request and key; no Item Workflow was accepted.",
            )
        return self.items.prepare(
            actor,
            reply.selection,
            workflow_request=workflow_request,
            expected_resolution=expected_resolution,
            evidence=evidence,
            preset=preset,
        )
