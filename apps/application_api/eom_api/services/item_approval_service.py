"""Post-registration Item approval application use case."""

from __future__ import annotations

from eom_catalog_contracts import (
    ApproveItemRevisionCommandV1,
    ItemRevisionApprovalReceiptV1,
)
from eom_hwpx_manager import HwpxApplicationService
from eom_identifiers import content_sha256
from eom_operator_identity import ActorContext

from eom_api.errors import ApiError
from eom_api.services.catalog_application_client import CatalogApplicationClient


class ItemApprovalApplicationService:
    """Resolve one exact validated HWPX build before Catalog-owned approval."""

    def __init__(
        self,
        *,
        hwpx: HwpxApplicationService,
        catalog: CatalogApplicationClient,
    ) -> None:
        self._hwpx = hwpx
        self._catalog = catalog

    def approve(
        self,
        item_revision_id: str,
        *,
        hwpx_build_id: str,
        reason: str,
        expected_revision_version: int,
        actor: ActorContext,
        idempotency_key: str,
    ) -> ItemRevisionApprovalReceiptV1:
        build = self._hwpx.get_build(hwpx_build_id)
        if (
            build.item_revision_id != item_revision_id
            or build.state != "SUCCEEDED"
            or build.validation_state != "PASS"
            or build.output_artifact_id is None
            or build.output_artifact_revision_id is None
            or build.output_sha256 is None
        ):
            raise ApiError(
                409,
                "ITEM_APPROVAL_HWPX_INVALID",
                "Validated HWPX is required",
                (
                    "The selected HWPX build is not a successful validated build "
                    "for this Item Revision."
                ),
            )
        body = {
            "operation": "APPROVE_ITEM_REVISION",
            "item_revision_id": item_revision_id,
            "expected_revision_version": expected_revision_version,
            "hwpx_build_id": hwpx_build_id,
            "hwpx_output_artifact_id": build.output_artifact_id,
            "hwpx_output_artifact_revision_id": build.output_artifact_revision_id,
            "hwpx_output_sha256": build.output_sha256,
            "reason": reason,
            "approved_by": actor.actor_id,
            "idempotency_key": idempotency_key,
        }
        command = ApproveItemRevisionCommandV1.model_validate(
            body | {"submission_sha256": content_sha256(body)}
        )
        return self._catalog.approve_item_revision(command)
