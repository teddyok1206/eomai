"""Sanitized Application API projection for an HWPX build resource."""

from typing import Literal, cast

from eom_api_contracts.hwpx import (
    HwpxBuildState,
    HwpxBuildView,
    HwpxValidationState,
)
from eom_hwpx_manager.models import HwpxApplicationBuildRecord


def project_hwpx_build(record: HwpxApplicationBuildRecord) -> HwpxBuildView:
    return HwpxBuildView(
        build_id=record.build_id,
        item_id=record.item_id,
        item_revision_id=record.item_revision_id,
        source_artifact_revision_id=record.source_artifact_revision_id,
        source_sha256=record.source_sha256,
        renderer=cast(Literal["kordoc", "eom-template", "content-team"], record.renderer),
        renderer_version=cast(Literal["4.9.0", "1.0.0"], record.renderer_version),
        state=HwpxBuildState(record.state),
        validation_state=HwpxValidationState(record.validation_state),
        native_equation_count=record.native_equation_count,
        native_table_count=record.native_table_count,
        output_artifact_id=record.output_artifact_id,
        output_artifact_revision_id=record.output_artifact_revision_id,
        output_sha256=record.output_sha256,
        download_available=record.state == "SUCCEEDED" and record.validation_state == "PASS",
        failure_code=record.failure_code,
        failure_detail_sanitized=record.failure_detail_sanitized,
        created_by_operator_id=record.created_by_operator_id,
        created_at=record.created_at,
        started_at=record.started_at,
        completed_at=record.completed_at,
        resource_version=record.resource_version,
    )
