"""Validate immutable non-live acceptance provenance without dereferencing filesystem paths."""

from __future__ import annotations

from typing import Any

from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_workflow import ExecutionPresetEvaluationReport, validate_control_contract
from eom_workflow.preset_model_validation import (
    PresetModelAcceptanceCases,
    PresetModelValidationRequest,
)
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError

from eom_orchestrator.control_models import (
    ExecutionPresetRevisionRecord,
    ExecutionPresetValidationRecord,
)
from eom_orchestrator.control_service import ControlPlaneError, compute_control_document_hash
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_orchestrator.preset_model_selection import (
    non_live_invocation_cases,
    require_model_only_successor,
    validated_preset,
)
from eom_orchestrator.preset_model_validation import PROTOCOL, TASK_TYPE, validated_request
from eom_orchestrator.preset_policy import execution_preset_policy_sha256

CASES_SCHEMA = "preset-model-acceptance-cases"
CASES_SCHEMA_REF = "eom://schemas/workflow/preset-model-acceptance-cases/1.0"


def validated_job_request(
    job: JobRecord, command: ExecutionPresetValidationRecord
) -> PresetModelValidationRequest:
    request = validated_request(command)
    expected = content_sha256(
        {"protocol_version": PROTOCOL, "task_type": TASK_TYPE, "request": command.canonical_request}
    )
    if (
        job.job_id != command.validation_id
        or job.protocol_version != PROTOCOL
        or job.task_type != TASK_TYPE
        or job.idempotency_key != command.idempotency_key
        or job.request != command.canonical_request
        or job.request_hash != expected
    ):
        raise ControlPlaneError(
            "CONTROL_VALIDATION_REQUEST_INVALID", "job request or identity differs"
        )
    return request


def validated_acceptance_checkpoint(
    *,
    job: JobRecord,
    request: PresetModelValidationRequest,
    draft: ExecutionPresetRevisionRecord,
    base: ExecutionPresetRevisionRecord,
    report_document: dict[str, Any],
    cases_document: dict[str, Any],
    evaluator_source_commit: str | None = None,
) -> tuple[ExecutionPresetEvaluationReport, PresetModelAcceptanceCases]:
    try:
        validate_control_contract("execution-preset-evaluation-report", report_document)
        validate_control_contract(CASES_SCHEMA, cases_document)
        report = ExecutionPresetEvaluationReport.model_validate(report_document)
        cases = PresetModelAcceptanceCases.model_validate(cases_document)
    except (JsonSchemaValidationError, PydanticValidationError, ValueError) as exc:
        raise ControlPlaneError(
            "CONTROL_VALIDATION_CHECKPOINT_INVALID", "acceptance checkpoint is invalid"
        ) from exc
    base_model, draft_model = validated_preset(base), validated_preset(draft)
    require_model_only_successor(base_model, draft_model)
    expected_cases = (
        "FIXED_POLICY_PRESERVED",
        "FRESH_ROLE_CAPABILITY",
        "RELEASED_BUNDLE_POINTERS",
        *non_live_invocation_cases(draft_model),
    )
    if (
        draft.preset_revision_id != request.preset_revision_id
        or draft.content_sha256 != request.preset_content_sha256
        or base.preset_revision_id != request.base_revision_id
        or base.content_sha256 != request.base_content_sha256
        or execution_preset_policy_sha256(draft.canonical_document) != request.preset_policy_sha256
        or cases.validation_id != job.job_id
        or cases.request_sha256 != job.request_hash
        or cases.preset_revision_id != request.preset_revision_id
        or cases.preset_content_sha256 != request.preset_content_sha256
        or cases.preset_policy_sha256 != request.preset_policy_sha256
        or cases.base_revision_id != request.base_revision_id
        or cases.base_content_sha256 != request.base_content_sha256
        or cases.case_keys != expected_cases
        or cases.cases_sha256 != compute_control_document_hash(cases_document, "cases_sha256")
        or report.report_sha256 != compute_control_document_hash(report_document, "report_sha256")
        or report.evaluated_preset_revision_id != request.preset_revision_id
        or report.evaluated_policy_sha256 != request.preset_policy_sha256
        or report.scope != "NON_LIVE"
        or report.outcome != "PASS"
        or report.summary_code != "FAKE_ADAPTER_ACCEPTANCE"
        or report.cases_total != len(expected_cases)
        or report.cases_passed != len(expected_cases)
        or report.completed_at != cases.completed_at
        or report.completed_at < request.requested_at
        or report.quality_score_permille is not None
    ):
        raise ControlPlaneError(
            "CONTROL_VALIDATION_CHECKPOINT_INVALID", "checkpoint pins, cases or hash differ"
        )
    if (
        evaluator_source_commit is not None
        and cases.evaluator_source_commit != evaluator_source_commit
    ):
        raise ControlPlaneError(
            "CONTROL_VALIDATION_EVALUATOR_CHANGED",
            "checkpoint belongs to another evaluator release",
        )
    return report, cases


def validate_acceptance_manifest(
    revision: ArtifactRevisionRecord,
    job: JobRecord,
    report_document: dict[str, Any],
    cases_document: dict[str, Any],
) -> None:
    """The existing control pointer pins the primary file; secondary SHA stays a member pin."""

    manifest = revision.manifest
    if (
        revision.revision_id != job.revision_id
        or revision.job_id != job.job_id
        or revision.logical_artifact_id != job.logical_artifact_id
        or not revision.approved
        or not isinstance(manifest, dict)
        or content_sha256(manifest) != revision.manifest_hash
        or manifest.get("logical_artifact_id") != job.logical_artifact_id
        or manifest.get("revision_id") != job.revision_id
        or manifest.get("job_id") != job.job_id
        or manifest.get("artifact_type") != TASK_TYPE
        or manifest.get("manifest_version") != "control-file-set/1.0"
        or manifest.get("primary_file") != "preset-evaluation.json"
    ):
        raise ControlPlaneError(
            "CONTROL_VALIDATION_EVIDENCE_MISMATCH", "acceptance manifest identity or hash differs"
        )
    entries = manifest.get("files")
    if (
        not isinstance(entries, list)
        or len(entries) != 2
        or any(not isinstance(entry, dict) for entry in entries)
    ):
        raise ControlPlaneError(
            "CONTROL_VALIDATION_EVIDENCE_MISMATCH", "acceptance manifest members differ"
        )
    if any(not isinstance(entry.get("file_name"), str) for entry in entries):
        raise ControlPlaneError(
            "CONTROL_VALIDATION_EVIDENCE_MISMATCH", "invalid acceptance member name"
        )
    by_path = {entry.get("file_name"): entry for entry in entries}
    if set(by_path) != {"preset-evaluation.json", "acceptance-cases.json"}:
        raise ControlPlaneError(
            "CONTROL_VALIDATION_EVIDENCE_MISMATCH", "acceptance member paths differ"
        )
    for name, schema_ref, document in (
        (
            "preset-evaluation.json",
            "eom://schemas/workflow/execution-preset-evaluation-report/1.0",
            report_document,
        ),
        ("acceptance-cases.json", CASES_SCHEMA_REF, cases_document),
    ):
        member = by_path[name]
        data = canonical_json_bytes(document) + b"\n"
        if (
            member.get("sha256") != sha256_bytes(data)
            or member.get("bytes") != len(data)
            or member.get("schema_ref") != schema_ref
            or member.get("media_type") != "application/json"
        ):
            raise ControlPlaneError(
                "CONTROL_VALIDATION_EVIDENCE_MISMATCH", "acceptance member hash or contract differs"
            )
