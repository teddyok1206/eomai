"""Current source authorization precedes even a cached HTTP submission replay."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from eom_catalog_contracts.inference_transfer_invocation import (
    InferenceTransferPairSubmitRequest,
    parse_pair_submit_request,
)
from eom_catalog_contracts.inference_transfer_snapshot import (
    InferenceTransferSnapshotPrepareResult,
    InferenceTransferSnapshotReadRequest,
    InferenceTransferSnapshotReadResult,
    validate_snapshot_read_result,
)
from eom_catalog_contracts.item_inference_transfer import (
    InferenceTransferProfile,
    InferenceTransferProfilePointer,
)
from eom_identifiers import content_sha256
from eom_identity_service.tokens import AccessAuthentication
from eom_operator_identity import ActorContext, ActorSource, ActorType, PermissionKey
from eom_workflow.inference_transfer_workflow import InferenceTransferWorkflowRequest
from jsonschema.exceptions import ValidationError as SchemaError

from eom_api.errors import ApiError
from eom_api.services.inference_transfer_snapshot import InferenceTransferSnapshotApplicationService


@dataclass(frozen=True)
class AuthorizedInferenceTransferSubmission:
    """Server-only context; the initial permission digest is provenance, not a grant."""

    operator_id: str
    selection: InferenceTransferPairSubmitRequest
    workflow_request: InferenceTransferWorkflowRequest


class InferenceTransferStartPort(Protocol):
    def start(
        self,
        submission: AuthorizedInferenceTransferSubmission,
        actor: ActorContext,
        *,
        idempotency_key: str,
    ) -> tuple[str, str, int]: ...


class InferenceTransferSubmissionApplicationService:
    def __init__(
        self,
        snapshots: InferenceTransferSnapshotApplicationService,
        starter: InferenceTransferStartPort,
    ) -> None:
        self.snapshots = snapshots
        self.starter = starter

    def authorize_submission(
        self,
        authentication: AccessAuthentication,
        request: InferenceTransferPairSubmitRequest,
    ) -> AuthorizedInferenceTransferSubmission:
        """Resolve exact two pointers through the existing authenticated owner reads."""
        if (
            authentication.operator.status != "ACTIVE"
            or authentication.operator.must_change_password
            or authentication.password_change_required
            or PermissionKey.WORKFLOW_START not in authentication.permissions
        ):
            raise ApiError(403, "PERMISSION_DENIED", "Permission denied", "Workflow start denied.")
        try:
            request = parse_pair_submit_request(request.model_dump(mode="json"))
        except (ValueError, SchemaError) as exc:
            raise ApiError(
                422,
                "INFERENCE_TRANSFER_SUBMISSION_INVALID",
                "Invalid comparison selection",
                "The bounded selection does not satisfy its exact contract.",
            ) from exc
        prepared = self.snapshots.execute(authentication, request.snapshot_prepare)
        if not isinstance(prepared, InferenceTransferSnapshotPrepareResult):
            raise ApiError(
                503,
                "INFERENCE_TRANSFER_SNAPSHOT_REPLY_INVALID",
                "Invalid snapshot",
                "The owner did not return a prepared snapshot.",
            )
        if prepared.header.header_sha256 != request.expected_header_sha256:
            raise ApiError(
                409,
                "INFERENCE_TRANSFER_SNAPSHOT_CHANGED",
                "Snapshot changed",
                "The selected snapshot is no longer exact; no latest was substituted.",
            )
        by_pointer = {
            (row.profile.profile_id, row.profile.profile_revision_id): row
            for row in prepared.index
            if row.profile is not None
        }
        selected = []
        for pointer in (request.comparison.left_profile, request.comparison.right_profile):
            row = by_pointer.get((pointer.profile_id, pointer.profile_revision_id))
            if row is None or row.profile != pointer:
                raise ApiError(
                    409,
                    "INFERENCE_TRANSFER_SNAPSHOT_SELECTION_INVALID",
                    "Invalid comparison selection",
                    "An exact profile is unavailable.",
                )
            selected.append(row)
        # One profile per read respects even a one-entry chunk budget; the order
        # follows the frozen index, not left/right comparison direction.
        selected_set = {row.source_item_revision_id for row in selected}
        profiles: dict[tuple[str, str], InferenceTransferProfile] = {}
        for row in prepared.index:
            if row.source_item_revision_id not in selected_set:
                continue
            body = {
                "schema_version": "inference-transfer-snapshot-read/1.0",
                "operation": "INFERENCE_TRANSFER_SNAPSHOT",
                "phase": "READ",
                "header": prepared.header.model_dump(mode="json"),
                "selected_index_entries": [row.model_dump(mode="json")],
            }
            try:
                read = InferenceTransferSnapshotReadRequest.model_validate(
                    body | {"read_sha256": content_sha256(body)}
                )
            except ValueError as exc:
                raise ApiError(
                    422,
                    "INFERENCE_TRANSFER_SNAPSHOT_BUDGET_EXCEEDED",
                    "Read budget too small",
                    "The pinned budget cannot carry one profile request; it was not expanded.",
                ) from exc
            resolved = self.snapshots.execute(authentication, read)
            try:
                if not isinstance(resolved, InferenceTransferSnapshotReadResult):
                    raise ValueError("wrong snapshot phase")
                validate_snapshot_read_result(read, resolved, index=prepared.index)
                for record in resolved.records:
                    if record.staged_entry is not None:
                        profile = record.staged_entry.profile
                        profiles[(profile.profile_id, profile.profile_revision_id)] = profile
            except (ValueError, SchemaError) as exc:
                raise ApiError(
                    409,
                    "INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH",
                    "Comparison pins differ",
                    "The owner-resolved profile differs from the exact selected source.",
                ) from exc
        try:
            left = profiles[
                (
                    request.comparison.left_profile.profile_id,
                    request.comparison.left_profile.profile_revision_id,
                )
            ]
            right = profiles[
                (
                    request.comparison.right_profile.profile_id,
                    request.comparison.right_profile.profile_revision_id,
                )
            ]
            if (
                InferenceTransferProfilePointer.from_profile(left)
                != request.comparison.left_profile
                or InferenceTransferProfilePointer.from_profile(right)
                != request.comparison.right_profile
                or left.source_basis.graph_snapshot != request.snapshot_prepare.graph_snapshot
                or right.source_basis.graph_snapshot != request.snapshot_prepare.graph_snapshot
            ):
                raise ValueError("resolved pair differs")
            wrapper = {
                "schema_version": "inference-transfer-workflow-request/1.0",
                "request_name": "ITEM_INFERENCE_TRANSFER_PAIR_REQUEST",
                "execution_preset_key": "item-inference-transfer-comparison",
                "comparison": request.comparison.model_dump(mode="json"),
                "left_profile": left.model_dump(mode="json"),
                "right_profile": right.model_dump(mode="json"),
                "access_policy_revision_id": request.snapshot_prepare.access_policy_revision_id,
                "access_policy_sha256": request.snapshot_prepare.access_policy_sha256,
                "requester_permissions_sha256": content_sha256(
                    sorted(permission.value for permission in authentication.permissions)
                ),
            }
            workflow_request = InferenceTransferWorkflowRequest.model_validate(
                wrapper | {"request_sha256": content_sha256(wrapper)}
            )
        except (ValueError, KeyError, SchemaError) as exc:
            raise ApiError(
                409,
                "INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH",
                "Comparison pins differ",
                "The owner-resolved pair does not match the bounded selection.",
            ) from exc
        return AuthorizedInferenceTransferSubmission(
            authentication.operator.operator_id, request, workflow_request
        )

    def start(
        self,
        submission: AuthorizedInferenceTransferSubmission,
        actor: ActorContext,
        *,
        idempotency_key: str,
    ) -> tuple[str, str, int]:
        if (
            actor.actor_type != ActorType.OPERATOR
            or actor.source != ActorSource.APPLICATION_API
            or actor.actor_id != submission.operator_id
            or PermissionKey.WORKFLOW_START not in actor.permissions
            or content_sha256(sorted(p.value for p in actor.permissions))
            != submission.workflow_request.requester_permissions_sha256
        ):
            raise ApiError(
                403, "PERMISSION_DENIED", "Permission denied", "Actual principal differs."
            )
        return self.starter.start(submission, actor, idempotency_key=idempotency_key)
