"""Immutable Execution Preset lifecycle and evaluation-evidence transactions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from eom_identifiers import (
    content_sha256,
    new_execution_preset_evaluation_id,
    new_execution_preset_id,
    new_execution_preset_revision_id,
)
from eom_workflow import (
    ControlArtifactPointer,
    ExecutionPresetEvaluationReport,
    ExecutionPresetRevision,
    ExecutionPresetRevisionV2,
    validate_control_contract,
)
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from eom_orchestrator.control_models import (
    ExecutionPresetEvaluationRecord,
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
)
from eom_orchestrator.control_service import (
    ControlPlaneError,
    compute_control_document_hash,
    record_execution_preset_revision,
    resolve_control_artifact_pointer,
)

EVALUATION_SCHEMA_REF = "eom://schemas/workflow/execution-preset-evaluation-report/1.0"
EVALUATION_MEDIA_TYPE = "application/json"


def execution_preset_policy_sha256(
    document: dict[str, Any] | ExecutionPresetRevision | ExecutionPresetRevisionV2,
) -> str:
    """Hash only executable policy, independent of revision lifecycle metadata."""

    try:
        if isinstance(document, (ExecutionPresetRevision, ExecutionPresetRevisionV2)):
            preset = document
        elif document.get("schema_version") == "execution-preset-revision/2.0":
            preset = ExecutionPresetRevisionV2.model_validate(document)
        else:
            preset = ExecutionPresetRevision.model_validate(document)
    except PydanticValidationError as exc:
        raise ControlPlaneError(
            "CONTROL_PRESET_DOCUMENT_INVALID", "preset policy document is invalid"
        ) from exc
    normalized = preset.model_dump(mode="json")
    policy = {
        "capacity_policy_revision_id": normalized["capacity_policy_revision_id"],
        "compatible_workflow_protocols": normalized["compatible_workflow_protocols"],
        "general_knowledge_policy": normalized["general_knowledge_policy"],
        "role_policies": normalized["role_policies"],
    }
    if isinstance(preset, ExecutionPresetRevisionV2):
        policy["retrieval_policy"] = normalized["retrieval_policy"]
    return content_sha256(policy)


def create_execution_preset_draft(
    session: Session,
    *,
    preset_key: str,
    display_name: str,
    description: str,
    role_policies: list[dict[str, Any]],
    capacity_policy_revision_id: str,
    general_knowledge_policy: str,
    compatible_workflow_protocols: list[str],
    created_by: str,
    created_at: datetime,
) -> ExecutionPresetRevisionRecord:
    """Create one new immutable DRAFT revision under a stable logical preset key."""

    logical = session.execute(
        select(ExecutionPresetRecord)
        .where(ExecutionPresetRecord.preset_key == preset_key)
        .with_for_update()
    ).scalar_one_or_none()
    if logical is not None and logical.state != "ACTIVE":
        raise ControlPlaneError("CONTROL_PRESET_RETIRED", "execution preset is retired")
    preset_id = logical.preset_id if logical is not None else new_execution_preset_id()
    highest = session.scalar(
        select(func.coalesce(func.max(ExecutionPresetRevisionRecord.revision_number), 0)).where(
            ExecutionPresetRevisionRecord.preset_id == preset_id
        )
    )
    document: dict[str, Any] = {
        "schema_version": "execution-preset-revision/1.0",
        "preset_id": preset_id,
        "preset_revision_id": new_execution_preset_revision_id(),
        "revision_number": int(highest or 0) + 1,
        "state": "DRAFT",
        "display_name": display_name,
        "description": description,
        "role_policies": role_policies,
        "capacity_policy_revision_id": capacity_policy_revision_id,
        "general_knowledge_policy": general_knowledge_policy,
        "compatible_workflow_protocols": compatible_workflow_protocols,
        "content_sha256": "sha256:" + "0" * 64,
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
    }
    document["content_sha256"] = compute_control_document_hash(document, "content_sha256")
    return record_execution_preset_revision(
        session,
        preset_key=preset_key,
        document=document,
        created_by=created_by,
    )


def create_execution_preset_draft_v2(
    session: Session,
    *,
    preset_key: str,
    display_name: str,
    description: str,
    role_policies: list[dict[str, Any]],
    capacity_policy_revision_id: str,
    general_knowledge_policy: str,
    compatible_workflow_protocols: list[str],
    retrieval_policy: dict[str, Any],
    created_by: str,
    created_at: datetime,
) -> ExecutionPresetRevisionRecord:
    """Create a V2 DRAFT without modifying historical V1 preset documents."""

    logical = session.execute(
        select(ExecutionPresetRecord)
        .where(ExecutionPresetRecord.preset_key == preset_key)
        .with_for_update()
    ).scalar_one_or_none()
    if logical is not None and logical.state != "ACTIVE":
        raise ControlPlaneError("CONTROL_PRESET_RETIRED", "execution preset is retired")
    preset_id = logical.preset_id if logical is not None else new_execution_preset_id()
    highest = session.scalar(
        select(func.coalesce(func.max(ExecutionPresetRevisionRecord.revision_number), 0)).where(
            ExecutionPresetRevisionRecord.preset_id == preset_id
        )
    )
    document: dict[str, Any] = {
        "schema_version": "execution-preset-revision/2.0",
        "preset_id": preset_id,
        "preset_revision_id": new_execution_preset_revision_id(),
        "revision_number": int(highest or 0) + 1,
        "state": "DRAFT",
        "display_name": display_name,
        "description": description,
        "role_policies": role_policies,
        "capacity_policy_revision_id": capacity_policy_revision_id,
        "general_knowledge_policy": general_knowledge_policy,
        "compatible_workflow_protocols": compatible_workflow_protocols,
        "retrieval_policy": retrieval_policy,
        "content_sha256": "sha256:" + "0" * 64,
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
    }
    document["content_sha256"] = compute_control_document_hash(document, "content_sha256")
    return record_execution_preset_revision(
        session,
        preset_key=preset_key,
        document=document,
        created_by=created_by,
    )


def record_execution_preset_evaluation(
    session: Session,
    *,
    document: dict[str, Any],
    report_artifact: ControlArtifactPointer,
    created_by: str,
) -> ExecutionPresetEvaluationRecord:
    """Attach one immutable, approved, hash-pinned evaluation report to an exact policy."""

    try:
        validate_control_contract("execution-preset-evaluation-report", document)
        report = ExecutionPresetEvaluationReport.model_validate(document)
    except (JsonSchemaValidationError, PydanticValidationError, ValueError) as exc:
        raise ControlPlaneError(
            "CONTROL_EVALUATION_INVALID", "preset evaluation report is invalid"
        ) from exc
    normalized = report.model_dump(mode="json")
    if report.report_sha256 != compute_control_document_hash(normalized, "report_sha256"):
        raise ControlPlaneError(
            "CONTROL_EVALUATION_HASH_MISMATCH", "preset evaluation report hash differs"
        )
    preset_revision = session.get(
        ExecutionPresetRevisionRecord, report.evaluated_preset_revision_id
    )
    if preset_revision is None:
        raise ControlPlaneError(
            "CONTROL_PRESET_REVISION_MISSING", "evaluated preset revision is missing"
        )
    if execution_preset_policy_sha256(preset_revision.canonical_document) != (
        report.evaluated_policy_sha256
    ):
        raise ControlPlaneError(
            "CONTROL_EVALUATION_POLICY_MISMATCH", "evaluation targets a different preset policy"
        )
    resolved = resolve_control_artifact_pointer(
        session,
        report_artifact,
        expected_schema_ref=EVALUATION_SCHEMA_REF,
        expected_media_type=EVALUATION_MEDIA_TYPE,
    )
    existing = session.scalar(
        select(ExecutionPresetEvaluationRecord).where(
            ExecutionPresetEvaluationRecord.report_artifact_revision_id
            == report_artifact.artifact_revision_id
        )
    )
    if existing is not None:
        if (
            existing.evaluated_preset_revision_id != report.evaluated_preset_revision_id
            or existing.evaluated_policy_sha256 != report.evaluated_policy_sha256
            or existing.report_document_sha256 != report.report_sha256
            or existing.report_content_sha256 != report_artifact.sha256
        ):
            raise ControlPlaneError(
                "CONTROL_EVALUATION_CONFLICT",
                "evaluation Artifact Revision is already attached to different evidence",
            )
        return existing
    record = ExecutionPresetEvaluationRecord(
        evaluation_id=new_execution_preset_evaluation_id(),
        preset_id=preset_revision.preset_id,
        evaluated_preset_revision_id=report.evaluated_preset_revision_id,
        evaluated_policy_sha256=report.evaluated_policy_sha256,
        scope=report.scope,
        outcome=report.outcome,
        summary_code=report.summary_code,
        cases_total=report.cases_total,
        cases_passed=report.cases_passed,
        quality_score_permille=report.quality_score_permille,
        report_artifact_id=report_artifact.artifact_id,
        report_artifact_revision_id=resolved.revision_id,
        report_document_sha256=report.report_sha256,
        report_content_sha256=report_artifact.sha256,
        completed_at=report.completed_at,
        created_by=created_by,
    )
    session.add(record)
    session.flush()
    return record


def release_execution_preset(
    session: Session,
    *,
    draft_revision_id: str,
    released_by: str,
    released_at: datetime,
) -> ExecutionPresetRevisionRecord:
    """Copy a reviewed DRAFT policy into a new immutable RELEASED revision."""

    draft = session.get(ExecutionPresetRevisionRecord, draft_revision_id)
    if draft is None or draft.state != "DRAFT":
        raise ControlPlaneError("CONTROL_PRESET_DRAFT_REQUIRED", "preset draft is missing")
    logical = session.execute(
        select(ExecutionPresetRecord)
        .where(ExecutionPresetRecord.preset_id == draft.preset_id)
        .with_for_update()
    ).scalar_one_or_none()
    if logical is None or logical.state != "ACTIVE":
        raise ControlPlaneError("CONTROL_PRESET_RETIRED", "execution preset is unavailable")
    policy_sha256 = execution_preset_policy_sha256(draft.canonical_document)
    accepted_evaluation = session.scalar(
        select(ExecutionPresetEvaluationRecord)
        .where(
            ExecutionPresetEvaluationRecord.preset_id == draft.preset_id,
            ExecutionPresetEvaluationRecord.evaluated_preset_revision_id
            == draft.preset_revision_id,
            ExecutionPresetEvaluationRecord.evaluated_policy_sha256 == policy_sha256,
            ExecutionPresetEvaluationRecord.outcome == "PASS",
            ExecutionPresetEvaluationRecord.scope.in_(("NON_LIVE", "LIVE_ONE_SHOT")),
        )
        .order_by(
            ExecutionPresetEvaluationRecord.completed_at.desc(),
            ExecutionPresetEvaluationRecord.evaluation_id.desc(),
        )
    )
    if accepted_evaluation is None:
        raise ControlPlaneError(
            "CONTROL_PRESET_EVALUATION_REQUIRED",
            "preset release requires passing non-live or live evidence",
        )
    if logical.current_revision_id is not None:
        current = session.get(ExecutionPresetRevisionRecord, logical.current_revision_id)
        if (
            current is not None
            and current.state == "RELEASED"
            and execution_preset_policy_sha256(current.canonical_document) == policy_sha256
        ):
            return current
    highest = session.scalar(
        select(func.max(ExecutionPresetRevisionRecord.revision_number)).where(
            ExecutionPresetRevisionRecord.preset_id == draft.preset_id
        )
    )
    released_document = dict(draft.canonical_document)
    released_document.update(
        {
            "preset_revision_id": new_execution_preset_revision_id(),
            "revision_number": int(highest or 0) + 1,
            "state": "RELEASED",
            "created_at": released_at.isoformat().replace("+00:00", "Z"),
            "content_sha256": "sha256:" + "0" * 64,
        }
    )
    released_document["content_sha256"] = compute_control_document_hash(
        released_document, "content_sha256"
    )
    released = record_execution_preset_revision(
        session,
        preset_key=logical.preset_key,
        document=released_document,
        created_by=released_by,
    )
    logical.current_revision_id = released.preset_revision_id
    session.flush()
    return released


def deprecate_execution_preset(
    session: Session,
    *,
    preset_id: str,
    deprecated_by: str,
    deprecated_at: datetime,
) -> ExecutionPresetRevisionRecord:
    """Append deprecation evidence and retire the logical preset without rewriting history."""

    logical = session.execute(
        select(ExecutionPresetRecord)
        .where(ExecutionPresetRecord.preset_id == preset_id)
        .with_for_update()
    ).scalar_one_or_none()
    if logical is None:
        raise ControlPlaneError("CONTROL_PRESET_MISSING", "execution preset is missing")
    if logical.state == "RETIRED":
        existing = session.scalar(
            select(ExecutionPresetRevisionRecord)
            .where(
                ExecutionPresetRevisionRecord.preset_id == preset_id,
                ExecutionPresetRevisionRecord.state == "DEPRECATED",
            )
            .order_by(ExecutionPresetRevisionRecord.revision_number.desc())
        )
        if existing is None:
            raise ControlPlaneError(
                "CONTROL_PRESET_HISTORY_INVALID", "retired preset lacks deprecation evidence"
            )
        return existing
    current = (
        session.get(ExecutionPresetRevisionRecord, logical.current_revision_id)
        if logical.current_revision_id is not None
        else None
    )
    if current is None or current.state != "RELEASED":
        raise ControlPlaneError(
            "CONTROL_PRESET_CURRENT_REQUIRED", "preset has no released current revision"
        )
    highest = session.scalar(
        select(func.max(ExecutionPresetRevisionRecord.revision_number)).where(
            ExecutionPresetRevisionRecord.preset_id == preset_id
        )
    )
    deprecated_document = dict(current.canonical_document)
    deprecated_document.update(
        {
            "preset_revision_id": new_execution_preset_revision_id(),
            "revision_number": int(highest or 0) + 1,
            "state": "DEPRECATED",
            "created_at": deprecated_at.isoformat().replace("+00:00", "Z"),
            "content_sha256": "sha256:" + "0" * 64,
        }
    )
    deprecated_document["content_sha256"] = compute_control_document_hash(
        deprecated_document, "content_sha256"
    )
    deprecated = record_execution_preset_revision(
        session,
        preset_key=logical.preset_key,
        document=deprecated_document,
        created_by=deprecated_by,
    )
    logical.state = "RETIRED"
    session.flush()
    return deprecated
