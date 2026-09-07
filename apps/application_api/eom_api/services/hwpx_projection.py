"""Sanitized Application API projection for an HWPX build resource."""

from typing import Literal, cast

from eom_api_contracts.hwpx import (
    AssessmentHwpxBuildView,
    HwpxBuildState,
    HwpxBuildView,
    HwpxValidationState,
)
from eom_hwpx_manager.models import HwpxApplicationBuildRecord, HwpxAssessmentAssemblyBuildRecord


def project_hwpx_build(record: HwpxApplicationBuildRecord) -> HwpxBuildView:
    return HwpxBuildView(
        build_id=record.build_id,
        item_id=record.item_id,
        item_revision_id=record.item_revision_id,
        source_artifact_revision_id=record.source_artifact_revision_id,
        source_sha256=record.source_sha256,
        renderer=cast(Literal["kordoc", "eom-template", "content-team"], record.renderer),
        renderer_version=cast(Literal["4.9.0", "1.0.0", "2.0.0"], record.renderer_version),
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


def project_assessment_hwpx_build(
    record: HwpxAssessmentAssemblyBuildRecord,
) -> AssessmentHwpxBuildView:
    return AssessmentHwpxBuildView(
        build_id=record.build_id,
        assessment_assembly_id=record.assessment_assembly_id,
        assessment_assembly_revision_id=record.assessment_assembly_revision_id,
        assembly_manifest_sha256=record.assembly_manifest_sha256,
        policy_revision_id=record.policy_revision_id,
        policy_sha256=record.policy_sha256,
        graph_snapshot_revision_id=record.graph_snapshot_revision_id,
        graph_snapshot_sha256=record.graph_snapshot_sha256,
        item_set_sha256=record.item_set_sha256,
        renderer="content-team-exam",
        renderer_version="1.0.0",
        state=HwpxBuildState(record.state),
        validation_state=HwpxValidationState(record.validation_state),
        item_count=record.item_count,
        section_count=record.section_count,
        native_equation_count=record.native_equation_count,
        native_table_count=record.native_table_count,
        visual_count=record.visual_count,
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
