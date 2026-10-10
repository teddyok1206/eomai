"""Fresh baseline guard for model-selection acceptance; historical report families stay valid."""

from __future__ import annotations

from datetime import datetime

from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow import ControlArtifactPointer
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_orchestrator.control_models import (
    ExecutionPresetEvaluationRecord,
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
    ExecutionPresetValidationRecord,
)
from eom_orchestrator.control_service import ControlPlaneError, resolve_control_artifact_pointer
from eom_orchestrator.models import JobEventRecord, JobRecord
from eom_orchestrator.preset_model_evidence import (
    validate_acceptance_manifest,
    validated_acceptance_checkpoint,
    validated_job_request,
)
from eom_orchestrator.preset_model_selection import validate_model_selection, validated_preset
from eom_orchestrator.preset_model_validation import PROTOCOL, TASK_TYPE


def require_current_model_acceptance(
    session: Session,
    *,
    logical: ExecutionPresetRecord,
    draft: ExecutionPresetRevisionRecord,
    evaluation: ExecutionPresetEvaluationRecord,
    observed_at: datetime,
) -> None:
    """Only this new queue lineage requires new cases/baseline checks, under the release lock."""

    job = session.scalar(
        select(JobRecord).where(JobRecord.revision_id == evaluation.report_artifact_revision_id)
    )
    if job is None or job.protocol_version != PROTOCOL:
        return
    command = session.get(ExecutionPresetValidationRecord, job.job_id)
    if (
        job.task_type != TASK_TYPE
        or job.status != "SUCCEEDED"
        or command is None
        or command.state != "SUCCEEDED"
    ):
        raise ControlPlaneError(
            "CONTROL_VALIDATION_EVIDENCE_MISMATCH", "validation lineage is not accepted"
        )
    request = validated_job_request(job, command)
    base = session.get(ExecutionPresetRevisionRecord, request.base_revision_id)
    if (
        logical.current_revision_id != request.base_revision_id
        or base is None
        or base.state != "RELEASED"
        or base.preset_id != draft.preset_id
        or request.preset_revision_id != draft.preset_revision_id
    ):
        raise ControlPlaneError(
            "CONTROL_PRESET_BASE_STALE", "release baseline changed after evaluation"
        )
    event = session.scalar(
        select(JobEventRecord).where(
            JobEventRecord.job_id == job.job_id,
            JobEventRecord.event == "PRESET_MODEL_ACCEPTANCE_STAGED",
        )
    )
    if event is None:
        raise ControlPlaneError(
            "CONTROL_VALIDATION_CHECKPOINT_MISSING", "acceptance checkpoint is missing"
        )
    report_document, cases_document = event.data.get("report"), event.data.get("cases")
    if not isinstance(report_document, dict) or not isinstance(cases_document, dict):
        raise ControlPlaneError("CONTROL_VALIDATION_CHECKPOINT_INVALID", "checkpoint is incomplete")
    report, cases = validated_acceptance_checkpoint(
        job=job,
        request=request,
        draft=draft,
        base=base,
        report_document=report_document,
        cases_document=cases_document,
    )
    if (
        evaluation.report_artifact_id != job.logical_artifact_id
        or evaluation.report_artifact_revision_id != job.revision_id
        or evaluation.report_document_sha256 != report.report_sha256
        or evaluation.report_content_sha256
        != sha256_bytes(canonical_json_bytes(report_document) + b"\n")
        or evaluation.evaluated_policy_sha256 != request.preset_policy_sha256
        or evaluation.cases_total != len(cases.case_keys)
        or evaluation.cases_passed != len(cases.case_keys)
        or evaluation.scope != "NON_LIVE"
        or evaluation.outcome != "PASS"
    ):
        raise ControlPlaneError("CONTROL_VALIDATION_EVIDENCE_MISMATCH", "report metadata differs")
    # Preserve the existing control pointer's primary-hash meaning, then validate the pinned
    # file-set manifest and secondary member instead of pretending its SHA is the primary SHA.
    schema_ref = "eom://schemas/workflow/execution-preset-evaluation-report/1.0"
    revision = resolve_control_artifact_pointer(
        session,
        ControlArtifactPointer(
            artifact_id=job.logical_artifact_id,
            artifact_revision_id=job.revision_id,
            sha256=evaluation.report_content_sha256,
            schema_ref=schema_ref,
            media_type="application/json",
            logical_name="preset-evaluation.json",
        ),
        expected_schema_ref=schema_ref,
        expected_media_type="application/json",
    )
    validate_acceptance_manifest(revision, job, report_document, cases_document)
    validate_model_selection(
        session, validated_preset(base), validated_preset(draft), observed_at=observed_at
    )
