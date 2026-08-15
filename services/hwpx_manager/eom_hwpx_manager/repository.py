"""Transactional persistence helpers for HWPX templates and builds."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from eom_identifiers import content_sha256, new_hwpx_validation_id
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_hwpx_manager.errors import HwpxManagerError, HwpxManagerErrorCode
from eom_hwpx_manager.models import (
    HwpxBuildRecord,
    HwpxTemplateRecord,
    HwpxTemplateRevisionRecord,
    HwpxValidationRunRecord,
)
from eom_hwpx_manager.state_machine import HwpxBuildState, require_transition


def get_or_create_template(
    session: Session, *, template_id: str, logical_name: str, description: str
) -> HwpxTemplateRecord:
    existing = session.scalar(
        select(HwpxTemplateRecord).where(HwpxTemplateRecord.logical_name == logical_name)
    )
    if existing is not None:
        return existing
    template = HwpxTemplateRecord(
        template_id=template_id,
        logical_name=logical_name,
        description=description,
        active=True,
    )
    session.add(template)
    session.flush()
    return template


def add_template_revision(
    session: Session,
    *,
    template_revision_id: str,
    template: HwpxTemplateRecord,
    source_artifact_id: str,
    source_artifact_revision_id: str,
    source_sha256: str,
    binding_manifest_sha256: str,
    owpml_version: str,
    hancom_version: str,
    package_profile: dict[str, Any],
    analysis_summary: dict[str, Any],
) -> HwpxTemplateRevisionRecord:
    existing = session.scalar(
        select(HwpxTemplateRevisionRecord).where(
            HwpxTemplateRevisionRecord.template_id == template.template_id,
            HwpxTemplateRevisionRecord.source_sha256 == source_sha256,
        )
    )
    if existing is not None:
        if existing.binding_manifest_sha256 != binding_manifest_sha256:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_TEMPLATE_HASH_MISMATCH,
                "stored binding hash conflicts with the same template bytes",
            )
        return existing
    record = HwpxTemplateRevisionRecord(
        template_revision_id=template_revision_id,
        template_id=template.template_id,
        source_artifact_id=source_artifact_id,
        source_artifact_revision_id=source_artifact_revision_id,
        source_sha256=source_sha256,
        binding_manifest_artifact_id=source_artifact_id,
        binding_manifest_revision_id=source_artifact_revision_id,
        binding_manifest_sha256=binding_manifest_sha256,
        owpml_version=owpml_version,
        hancom_version_declared=hancom_version,
        package_profile=package_profile,
        analysis_summary=analysis_summary,
        approved_at=datetime.now(UTC),
        immutable=True,
    )
    session.add(record)
    session.flush()
    return record


def create_build(
    session: Session,
    *,
    build_id: str,
    template_revision_id: str,
    platform_job_id: str,
    input_payload: dict[str, Any],
    renderer_version: str,
    idempotency_key: str,
) -> tuple[HwpxBuildRecord, bool]:
    input_hash = content_sha256(input_payload)
    existing = session.scalar(
        select(HwpxBuildRecord).where(HwpxBuildRecord.idempotency_key == idempotency_key)
    )
    if existing is not None:
        if (
            existing.input_sha256 != input_hash
            or existing.template_revision_id != template_revision_id
        ):
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_BUILD_IDEMPOTENCY_CONFLICT,
                "HWPX build idempotency key conflicts with stored input",
            )
        return existing, False
    build = HwpxBuildRecord(
        build_id=build_id,
        template_revision_id=template_revision_id,
        platform_job_id=platform_job_id,
        status=HwpxBuildState.CREATED.value,
        input_payload=input_payload,
        input_sha256=input_hash,
        renderer_version=renderer_version,
        idempotency_key=idempotency_key,
        workspace_id=build_id,
        manual_validation_status="PENDING_MANUAL_ACTION",
    )
    session.add(build)
    session.flush()
    return build, True


def transition_build(
    session: Session, build: HwpxBuildRecord, target: HwpxBuildState
) -> HwpxBuildRecord:
    require_transition(HwpxBuildState(build.status), target)
    build.status = target.value
    if target == HwpxBuildState.RENDERING and build.started_at is None:
        build.started_at = datetime.now(UTC)
    if target in {
        HwpxBuildState.SUCCEEDED,
        HwpxBuildState.FAILED,
        HwpxBuildState.PENDING_MANUAL_VALIDATION,
    }:
        build.completed_at = datetime.now(UTC)
    session.flush()
    return build


def add_validation(
    session: Session,
    *,
    build_id: str,
    validation_type: str,
    status: str,
    validator_version: str,
    artifact_id: str | None = None,
    revision_id: str | None = None,
    hancom_version: str | None = None,
    windows_version: str | None = None,
    performed_by: str | None = None,
    notes: str | None = None,
) -> HwpxValidationRunRecord:
    existing = session.scalar(
        select(HwpxValidationRunRecord).where(
            HwpxValidationRunRecord.build_id == build_id,
            HwpxValidationRunRecord.validation_type == validation_type,
        )
    )
    if existing is not None:
        return existing
    validation = HwpxValidationRunRecord(
        validation_id=new_hwpx_validation_id(),
        build_id=build_id,
        validation_type=validation_type,
        status=status,
        validator_version=validator_version,
        report_artifact_id=artifact_id,
        report_artifact_revision_id=revision_id,
        hancom_version=hancom_version,
        windows_version=windows_version,
        performed_by=performed_by,
        notes=notes[:1000] if notes else None,
    )
    session.add(validation)
    session.flush()
    return validation
