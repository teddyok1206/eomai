"""Canonical approval projection shared by Catalog reads and API presentation."""

from typing import Literal, cast

from eom_api_contracts.items import ItemApprovalView
from eom_catalog_contracts import ItemRevisionApprovalReceiptV1

from eom_catalog_service.models import ItemEventRecord, ItemRevisionRecord


def project_item_approval(
    revision: ItemRevisionRecord, event: ItemEventRecord | None
) -> ItemApprovalView:
    status = cast(
        Literal["PENDING", "APPROVED", "REJECTED", "SUPERSEDED", "RETIRED"],
        {
            "DRAFT": "PENDING",
            "IN_REVIEW": "PENDING",
            "APPROVED": "APPROVED",
            "REJECTED": "REJECTED",
            "SUPERSEDED": "SUPERSEDED",
            "RETIRED": "RETIRED",
        }[revision.revision_state],
    )
    human_review_required = revision.workflow_definition_version == "1.16.0"
    parsed_receipt: ItemRevisionApprovalReceiptV1 | None = None
    if human_review_required and event is not None:
        receipt = event.payload.get("approval_receipt")
        try:
            parsed_receipt = ItemRevisionApprovalReceiptV1.model_validate(receipt)
        except (TypeError, ValueError):
            raise ValueError("ITEM_APPROVAL_PROJECTION_INVALID") from None
        if (
            event.item_id != revision.item_id
            or event.item_revision_id != revision.item_revision_id
            or event.event_type != "ITEM_REVISION_APPROVED"
            or event.new_state != "APPROVED"
            or parsed_receipt.item_id != revision.item_id
            or parsed_receipt.item_revision_id != revision.item_revision_id
            or parsed_receipt.item_revision_number != revision.revision_number
            or parsed_receipt.manifest_artifact_id != revision.manifest_artifact_id
            or parsed_receipt.manifest_artifact_revision_id
            != revision.manifest_artifact_revision_id
            or parsed_receipt.manifest_sha256 != revision.manifest_sha256
            or parsed_receipt.workflow_id != revision.workflow_id
            or parsed_receipt.registration_step_run_id != revision.source_workflow_step_run_id
            or parsed_receipt.approved_by != revision.approved_by
            or parsed_receipt.approved_at != revision.approved_at
        ):
            raise ValueError("ITEM_APPROVAL_PROJECTION_INVALID")
    if human_review_required:
        approved_history = status in {"APPROVED", "SUPERSEDED", "RETIRED"}
        if approved_history != (parsed_receipt is not None):
            raise ValueError("ITEM_APPROVAL_PROJECTION_INVALID")
        if status in {"PENDING", "REJECTED"} and (
            revision.approved_at is not None or revision.approved_by is not None
        ):
            raise ValueError("ITEM_APPROVAL_PROJECTION_INVALID")
    return ItemApprovalView(
        status=status,
        human_review_required=human_review_required,
        approved_at=revision.approved_at,
        approved_by=revision.approved_by,
        approval_receipt_sha256=(
            parsed_receipt.receipt_sha256 if parsed_receipt is not None else None
        ),
        hwpx_build_id=(parsed_receipt.hwpx_build_id if parsed_receipt is not None else None),
    )
