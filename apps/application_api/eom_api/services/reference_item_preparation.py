"""Current HTTP operator → existing native preparation → Catalog item-start context."""

from __future__ import annotations

from typing import Literal

from eom_catalog_contracts import (
    EducationalRetrievalRequirement,
    EducationalRetrievalRequirementV2,
    EvidenceBundlePublicationResultV5,
)
from eom_catalog_contracts.authoring_reference import AuthoringReferenceSelection
from eom_catalog_contracts.reference_query_prepare import (
    parse_supported_reference_query_prepare_request,
)
from eom_identifiers import content_sha256
from eom_operator_identity import ActorContext
from eom_orchestrator.control_service import ControlPlaneError
from eom_workflow.control_plane import ExecutionPresetRevisionV2
from eom_workflow.models import ExpectedWorkflowResolution, WorkflowRequest
from eom_workflow_runner.item_similarity_preparation import (
    PreparedItemSimilarity,
    validate_item_similarity_start_controls,
)
from jsonschema.exceptions import ValidationError as SchemaError

from eom_api.errors import ApiError
from eom_api.request_context import RequestContext
from eom_api.services.audit_service import AuditService
from eom_api.services.authoring_reference_client import AuthoringReferenceClientError
from eom_api.services.item_similarity_preparation import ItemSimilarityStartPreparationService
from eom_api.services.reference_item_start_ports import (
    AuthoringReferenceSelectionPort,
    ReferenceItemSimilarityNotOffered,
    ReferenceItemStartPending,
)
from eom_api.services.reference_query_preparation import ReferenceQueryPreparationApplicationService


class HttpReferenceItemStartPreparation:
    """Only operation-local RequestContext is retained; no actor/capture cache."""

    def __init__(
        self,
        context: RequestContext,
        queries: ReferenceQueryPreparationApplicationService,
        items: ItemSimilarityStartPreparationService,
        *,
        references: AuthoringReferenceSelectionPort | None = None,
        audit: AuditService | None = None,
    ) -> None:
        self.context, self.queries, self.items = context, queries, items
        self.references, self.audit = references, audit

    def _not_offered(
        self,
        request: WorkflowRequest,
        evidence: EvidenceBundlePublicationResultV5,
        reason: Literal["REFERENCE_NOT_OFFERED", "INDEX_NOT_PREPARED"],
    ) -> ReferenceItemSimilarityNotOffered:
        assert self.audit is not None
        result = ReferenceItemSimilarityNotOffered(
            reason, content_sha256(request.model_dump(mode="json")), evidence.result_sha256
        )
        self.audit.append(
            self.context,
            event_type="REFERENCE_ITEM_SIMILARITY_NOT_OFFERED",
            operation_id="workflow_reference_start",
            outcome="NOT_OFFERED",
            http_status=202,
            error_code=reason,
            target_type="evidence_bundle_revision",
            target_id=evidence.evidence_bundle_revision_id,
        )
        return result

    def prepare(
        self,
        actor: ActorContext,
        *,
        workflow_request: WorkflowRequest,
        expected_resolution: ExpectedWorkflowResolution,
        evidence: EvidenceBundlePublicationResultV5,
        preset: ExecutionPresetRevisionV2,
        idempotency_key: str,
    ) -> PreparedItemSimilarity | ReferenceItemStartPending | ReferenceItemSimilarityNotOffered:
        if actor != self.context.actor():
            raise ApiError(403, "PERMISSION_DENIED", "Permission denied", "Current caller differs.")
        self.context.owner_capture()
        try:
            workflow_request, expected_resolution, evidence, preset = (
                validate_item_similarity_start_controls(
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
        reference: AuthoringReferenceSelection | None = None
        if isinstance(requirement, EducationalRetrievalRequirementV2):
            source_id = requirement.past_exam_variation.source_item_revision_id
        else:
            assert isinstance(requirement, EducationalRetrievalRequirement)
            if self.audit is None:
                raise ApiError(
                    503,
                    "AUTHORING_REFERENCE_UNAVAILABLE",
                    "Reference audit unavailable",
                    "The ordinary reference operation requires its canonical audit adapter.",
                )
            if "PAST_EXAM" not in requirement.source_classes:
                return self._not_offered(workflow_request, evidence, "REFERENCE_NOT_OFFERED")
            if self.references is None:
                raise ApiError(
                    503,
                    "AUTHORING_REFERENCE_UNAVAILABLE",
                    "Reference selection unavailable",
                    "The compatible official-Evidence selector is not configured.",
                )
            try:
                reference = self.references.select(actor.actor_id, evidence)
                if reference is not None:
                    reference = AuthoringReferenceSelection.model_validate(reference)
            except AuthoringReferenceClientError as error:
                raise ApiError(
                    403 if error.code in {"SOURCE_ACCESS_DENIED", "SOURCE_REVOKED"} else 503,
                    error.code,
                    "Reference selection unavailable",
                    "The original Evidence reference could not be resolved.",
                ) from None
            except (ValueError, SchemaError):
                raise ApiError(
                    409,
                    "CONTROL_SIMILARITY_PREPARATION_INVALID",
                    "Reference selection differs",
                    "The official selector did not return a valid exact reference.",
                ) from None
            if reference is None:
                return self._not_offered(workflow_request, evidence, "REFERENCE_NOT_OFFERED")
            source_id = reference.source_item_revision_id
        # The enclosing API claim already binds the complete Item request hash.
        # The domain key also scopes the QUERY to this actual operator/operation.
        key = idempotency_key + ":reference"
        operation = content_sha256({"purpose": "REFERENCE_ITEM_START/1.0", "key": key})
        body = {
            "schema_version": "system-rag-reference-query-prepare-request/1.0",
            "operation": "PREPARE_REFERENCE_QUERY",
            "operation_id": "queryprepare_" + operation.removeprefix("sha256:")[:32],
            "idempotency_key": key,
            "source_item_revision_id": source_id,
            "graph_snapshot": evidence.graph_snapshot.model_dump(mode="json"),
            "policy_revision_id": evidence.access_policy_revision_id,
            "policy_sha256": evidence.access_policy_sha256,
        }
        if reference is not None:
            body.update(
                schema_version="system-rag-reference-query-prepare-request/1.1",
                consumer_purpose="ITEM_AUTHORING",
            )
        query = parse_supported_reference_query_prepare_request(
            {**body, "request_sha256": content_sha256(body)}
        )
        reply = self.queries.prepare(self.context, query, idempotency_key=key)
        if reply.status == "PENDING":
            assert reply.workflow_id is not None
            return ReferenceItemStartPending(reply.workflow_id)
        if (
            reference is not None
            and reply.status == "UNAVAILABLE"
            and reply.error_code == "INDEX_NOT_PREPARED"
        ):
            return self._not_offered(workflow_request, evidence, "INDEX_NOT_PREPARED")
        if reply.status != "READY" or reply.selection is None:
            raise ApiError(
                409 if reply.status == "FAILED" else 503,
                reply.error_code or "REFERENCE_QUERY_PREPARE_UNAVAILABLE",
                "Reference preparation unavailable",
                "Retain the original request and key; no Item Workflow was accepted.",
            )
        prepared = self.items.prepare(
            actor,
            reply.selection,
            workflow_request=workflow_request,
            expected_resolution=expected_resolution,
            evidence=evidence,
            preset=preset,
        )
        if reference is not None:
            anchor = prepared.plan.context.request.anchor
            if (
                anchor.source.item_revision_id != reference.source_item_revision_id
                or anchor.source.artifact_member.sha256 != reference.source_sha256
                or anchor.solution_evidence is None
                or anchor.solution_evidence.pointer_sha256 != reference.solution_pointer_sha256
            ):
                # Publication may already exist; do not retry/re-key or start an Item.
                raise ApiError(
                    409,
                    "CONTROL_SIMILARITY_PREPARATION_INVALID",
                    "Reference pins differ",
                    "The prepared reference differs from the original Evidence selection.",
                )
        return prepared
