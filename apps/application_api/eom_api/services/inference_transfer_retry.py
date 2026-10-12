"""Authorize one explicit successor while keeping the failed comparison immutable."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from eom_catalog_contracts.inference_transfer_invocation_v11 import (
    parse_workflow_read_request_v11,
)
from eom_catalog_contracts.inference_transfer_retry import (
    InferenceTransferPairRetryRequestV1,
    parse_pair_retry_request_v1,
)
from eom_identifiers import content_sha256
from eom_identity_service.tokens import AccessAuthentication
from eom_operator_identity import ActorContext, ActorSource, ActorType, PermissionKey
from jsonschema.exceptions import ValidationError as SchemaError

from eom_api.errors import ApiError
from eom_api.services.inference_transfer_submission import (
    AuthorizedInferenceTransferSubmission,
    InferenceTransferSubmissionApplicationService,
)
from eom_api.services.inference_transfer_workflow_read import (
    InferenceTransferWorkflowReadApplicationServiceV11,
)


@dataclass(frozen=True)
class AuthorizedInferenceTransferRetry:
    """Server-only current source authorization, never a reusable permission token."""

    parent_workflow_id: str
    request: InferenceTransferPairRetryRequestV1
    submission: AuthorizedInferenceTransferSubmission


class InferenceTransferRetryPort(Protocol):
    def retry(
        self,
        authorized: AuthorizedInferenceTransferRetry,
        actor: ActorContext,
        *,
        expected_version: int,
        idempotency_key: str,
    ) -> tuple[str, str, int]: ...


class InferenceTransferRetryApplicationService:
    def __init__(
        self,
        submissions: InferenceTransferSubmissionApplicationService,
        reads: InferenceTransferWorkflowReadApplicationServiceV11,
        retry_port: InferenceTransferRetryPort,
    ) -> None:
        self.submissions = submissions
        self.reads = reads
        self.retry_port = retry_port

    def authorize_retry(
        self,
        authentication: AccessAuthentication,
        parent_workflow_id: str,
        request: InferenceTransferPairRetryRequestV1,
    ) -> AuthorizedInferenceTransferRetry:
        """Current own-creator Catalog and original selection reads precede HTTP replay."""
        if PermissionKey.WORKFLOW_START not in authentication.permissions:
            raise ApiError(403, "PERMISSION_DENIED", "Permission denied", "Workflow start denied.")
        try:
            checked = parse_pair_retry_request_v1(request.model_dump(mode="json"))
            body = {
                "schema_version": "inference-transfer-workflow-read-request/1.1",
                "workflow_id": parent_workflow_id,
                "mode": "STATUS_ONLY",
            }
            query = parse_workflow_read_request_v11(body | {"read_sha256": content_sha256(body)})
        except (ValueError, SchemaError) as exc:
            raise ApiError(
                422,
                "INFERENCE_TRANSFER_RETRY_INVALID",
                "Invalid comparison retry",
                "The exact parent and bounded retry request are invalid.",
            ) from exc
        parent = self.reads.execute(authentication, query)
        submission = self.submissions.authorize_submission(authentication, checked.selection)
        selected = checked.selection
        if (
            parent.comparison != selected.comparison
            or parent.graph_snapshot != selected.snapshot_prepare.graph_snapshot
            or parent.access_policy_revision_id
            != selected.snapshot_prepare.access_policy_revision_id
            or parent.access_policy_sha256 != selected.snapshot_prepare.access_policy_sha256
        ):
            raise ApiError(
                409,
                "INFERENCE_TRANSFER_RETRY_CONFLICT",
                "Comparison retry conflict",
                "The original comparison and source pins differ from the saved selection.",
            )
        if parent.workflow_state != "FAILED" or parent.result_state != "NO_RESULT":
            raise ApiError(
                409,
                "INFERENCE_TRANSFER_RETRY_INELIGIBLE",
                "Comparison cannot be retried",
                "Only an unsuccessful original comparison without a result can be retried.",
            )
        return AuthorizedInferenceTransferRetry(parent_workflow_id, checked, submission)

    def retry(
        self,
        authorized: AuthorizedInferenceTransferRetry,
        actor: ActorContext,
        *,
        expected_version: int,
        idempotency_key: str,
    ) -> tuple[str, str, int]:
        if (
            actor.actor_type != ActorType.OPERATOR
            or actor.source != ActorSource.APPLICATION_API
            or actor.actor_id != authorized.submission.operator_id
            or not {PermissionKey.WORKFLOW_START, PermissionKey.WORKFLOW_READ}.issubset(
                actor.permissions
            )
            or content_sha256(sorted(p.value for p in actor.permissions))
            != authorized.submission.workflow_request.requester_permissions_sha256
        ):
            raise ApiError(
                403, "PERMISSION_DENIED", "Permission denied", "Actual retry principal differs."
            )
        if type(expected_version) is not int or expected_version < 1:
            raise ApiError(
                422,
                "INFERENCE_TRANSFER_RETRY_INVALID",
                "Invalid retry version",
                "Exact version required.",
            )
        return self.retry_port.retry(
            authorized, actor, expected_version=expected_version, idempotency_key=idempotency_key
        )
