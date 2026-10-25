"""Claim-bound asynchronous reference Item start using the existing domain owner."""

from __future__ import annotations

from eom_api_contracts import CommandResult
from eom_api_contracts.workflow_reference_start import (
    SupportedWorkflowReferenceStartReply,
    WorkflowReferencePreparationPending,
    WorkflowReferenceStartReply,
)
from eom_api_contracts.workflows import (
    EducationalRetrievalIntentRequest,
    EducationalRetrievalIntentRequestV2,
    WorkflowStartRequest,
)
from eom_operator_identity import PermissionKey

from eom_api.errors import ApiError
from eom_api.request_context import RequestContext
from eom_api.services.audit_service import AuditService
from eom_api.services.command_adapter import CommandAdapter
from eom_api.services.idempotency_service import IdempotencyService
from eom_api.services.item_similarity_preparation import ItemSimilarityStartPreparationService
from eom_api.services.reference_item_preparation import HttpReferenceItemStartPreparation
from eom_api.services.reference_item_start_ports import (
    AuthoringReferenceSelectionPort,
    ReferenceItemStartPending,
)
from eom_api.services.reference_query_preparation import ReferenceQueryPreparationApplicationService

REFERENCE_ITEM_START_OPERATION = "workflow_reference_start"


class ReferenceItemStartApplicationService:
    def __init__(
        self,
        *,
        enabled: bool,
        commands: CommandAdapter,
        queries: ReferenceQueryPreparationApplicationService,
        items: ItemSimilarityStartPreparationService,
        idempotency: IdempotencyService,
        audit: AuditService,
        references: AuthoringReferenceSelectionPort | None = None,
    ) -> None:
        self.enabled, self.commands, self.queries = enabled, commands, queries
        self.items, self.idempotency, self.audit = items, idempotency, audit
        self.references = references

    def start(
        self, context: RequestContext, request: WorkflowStartRequest, *, idempotency_key: str
    ) -> SupportedWorkflowReferenceStartReply:
        if not self.enabled:
            raise ApiError(
                503,
                "REFERENCE_ITEM_START_UNAVAILABLE",
                "Reference Item start unavailable",
                "The compatible asynchronous reference start is not activated.",
            )
        actor = context.actor()
        if PermissionKey.WORKFLOW_START not in actor.permissions:
            raise ApiError(403, "PERMISSION_DENIED", "Permission denied", "Item start denied.")
        context.owner_capture()
        if request.production_occurrence is not None:
            raise ApiError(
                403,
                "WORKFLOW_PRODUCTION_OCCURRENCE_INTERNAL_ONLY",
                "Production occurrence is internal-only",
                "Bulk production retains its own application boundary.",
            )
        if (
            not isinstance(
                request.educational_retrieval,
                (EducationalRetrievalIntentRequest, EducationalRetrievalIntentRequestV2),
            )
            or request.definition_key != "generic-item-development"
            or request.definition_version != "1.16.0"
        ):
            raise ApiError(
                422,
                "REFERENCE_ITEM_START_REQUEST_INVALID",
                "Reference Item request required",
                "This operation accepts supported ordinary or exact-reference Item requests.",
            )
        fingerprint = self.idempotency.request_hash(
            method=context.method,
            operation_id=REFERENCE_ITEM_START_OPERATION,
            path_parameters={},
            body=request.model_dump(mode="json"),
            operator_id=actor.actor_id,
        )
        try:
            claim = self.idempotency.claim(
                operator_id=actor.actor_id,
                endpoint_key=REFERENCE_ITEM_START_OPERATION,
                raw_key=idempotency_key,
                request_sha256=fingerprint,
            )
        except ApiError as error:
            self.audit.append(
                context,
                event_type="IDEMPOTENCY_CONFLICT",
                operation_id=REFERENCE_ITEM_START_OPERATION,
                outcome="DENIED",
                http_status=error.status,
                error_code=error.error_code,
                target_type="workflow",
            )
            raise
        if claim.replayed:
            assert claim.replay_body is not None
            command = CommandResult.model_validate(claim.replay_body)
            self.audit.append(
                context,
                event_type="IDEMPOTENCY_REPLAY",
                operation_id=REFERENCE_ITEM_START_OPERATION,
                outcome="REPLAYED",
                http_status=202,
                target_type="workflow",
                target_id=command.resource_id,
            )
            return WorkflowReferenceStartReply(
                status="ACCEPTED", reference_query_workflow_id=None, command=command
            )
        key = self.idempotency.submission_key(
            operator_id=actor.actor_id,
            endpoint_key=REFERENCE_ITEM_START_OPERATION,
            raw_key=idempotency_key,
        )
        try:
            result = self.commands.start_reference_workflow(
                request,
                actor,
                idempotency_key=key,
                preparation=HttpReferenceItemStartPreparation(
                    context, self.queries, self.items, references=self.references, audit=self.audit
                ),
            )
            if isinstance(result, ReferenceItemStartPending):
                self.idempotency.defer(claim)
                self.audit.append(
                    context,
                    event_type="REFERENCE_ITEM_PREPARATION_PENDING",
                    operation_id=REFERENCE_ITEM_START_OPERATION,
                    outcome="SUBMITTED",
                    http_status=202,
                    target_type="reference_query"
                    if result.reference_query_workflow_id is not None
                    else "reference_query_preparation",
                    target_id=result.reference_query_workflow_id
                    or (
                        result.preparation.artifact_revision_id
                        if result.preparation is not None
                        else None
                    ),
                )
                if result.preparation is not None:
                    assert result.parent_request_sha256 is not None
                    return WorkflowReferencePreparationPending(
                        reference_query_workflow_id=result.reference_query_workflow_id,
                        reference_query_preparation=result.preparation,
                        reference_query_parent_sha256=result.parent_request_sha256,
                    )
                return WorkflowReferenceStartReply(
                    status="PENDING",
                    reference_query_workflow_id=result.reference_query_workflow_id,
                    command=None,
                )
            command_id, workflow_id, version = result
            command = CommandResult(
                command_id=command_id,
                resource_type="workflow",
                resource_id=workflow_id,
                status="ACCEPTED",
                resource_version=version,
                status_url=f"/api/v1/workflows/{workflow_id}",
            )
            self.idempotency.complete(
                claim,
                status=202,
                body=command.model_dump(mode="json"),
                resource_type="workflow",
                resource_id=workflow_id,
            )
        except Exception as error:
            code = (
                error.error_code if isinstance(error, ApiError) else "REFERENCE_ITEM_START_FAILED"
            )
            self.idempotency.fail_final(claim, code)
            self.audit.append(
                context,
                event_type="DOMAIN_COMMAND_FAILED",
                operation_id=REFERENCE_ITEM_START_OPERATION,
                outcome="FAILED",
                http_status=getattr(error, "status", 409),
                error_code=code,
                target_type="workflow",
            )
            raise
        self.audit.append(
            context,
            event_type="DOMAIN_COMMAND_SUCCEEDED",
            operation_id=REFERENCE_ITEM_START_OPERATION,
            outcome="SUCCEEDED",
            http_status=202,
            target_type="workflow",
            target_id=workflow_id,
        )
        return WorkflowReferenceStartReply(
            status="ACCEPTED", reference_query_workflow_id=None, command=command
        )
