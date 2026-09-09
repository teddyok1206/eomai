"""Application service for the reviewed three-range extraction recovery."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from eom_catalog_contracts import (
    LegacyExtractionBatchWorkUnitV2,
    LegacyItemExtractionBatchManifestV2,
    LegacyItemExtractionRequest,
    LegacyItemExtractionValidationRecovery,
    validate_contract,
)
from eom_identifiers import content_sha256
from eom_orchestrator.control_models import ExecutionBundleRevisionRecord
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.models import JobRecord
from eom_workflow import ExecutionPresetRevision
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from jsonschema import ValidationError as JsonSchemaValidationError
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from eom_catalog_service.legacy_extraction_preset_resolution import (
    LegacyExtractionPresetResolutionError,
    resolve_legacy_extraction_preset_pointer,
)
from eom_catalog_service.legacy_item_extraction_batch_models import (
    LegacyItemExtractionBatchRecord,
    LegacyItemExtractionBatchWorkUnitRecord,
)
from eom_catalog_service.legacy_item_extraction_batch_service import (
    CreateLegacyItemExtractionBatchCommand,
    LegacyItemExtractionBatchService,
    LegacyItemExtractionBatchServiceError,
    LegacyItemExtractionBatchView,
)


class LegacyItemExtractionRecoveryError(RuntimeError):
    """Stable content-free failure at the validation-recovery boundary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CreateLegacyItemExtractionRecoveryCommand:
    recovery: LegacyItemExtractionValidationRecovery
    requested_by: str

    def __post_init__(self) -> None:
        if not 1 <= len(self.requested_by) <= 128:
            raise ValueError("requested actor length is invalid")
        if any(ord(character) < 0x20 for character in self.requested_by):
            raise ValueError("requested actor contains a control character")


@dataclass(frozen=True)
class LegacyItemExtractionRecoveryResult:
    recovery_sha256: str
    successor_manifest_sha256: str
    batch: LegacyItemExtractionBatchView


class LegacyItemExtractionRecoveryService:
    """Validate exact failed history and create one fresh pinned continuation."""

    def __init__(
        self,
        engine: Engine,
        *,
        batches: LegacyItemExtractionBatchService | None = None,
    ) -> None:
        self.sessions = build_session_factory(engine)
        self.batches = batches or LegacyItemExtractionBatchService(engine)

    def create(
        self,
        command: CreateLegacyItemExtractionRecoveryCommand,
    ) -> LegacyItemExtractionRecoveryResult:
        recovery = command.recovery
        try:
            validate_contract(
                "legacy-item-extraction-validation-recovery",
                recovery.model_dump(mode="json"),
            )
        except (JsonSchemaValidationError, ValueError) as exc:
            raise LegacyItemExtractionRecoveryError(
                "LEGACY_EXTRACTION_RECOVERY_REQUEST_INVALID",
                "legacy extraction recovery request is invalid",
            ) from exc
        try:
            predecessor_manifest = self.batches.resolve_manifest(
                recovery.predecessor_batch_id,
                expected_manifest_sha256=recovery.predecessor_manifest_sha256,
            )
            predecessor_batch = self.batches.inspect(recovery.predecessor_batch_id)
        except LegacyItemExtractionBatchServiceError as exc:
            raise LegacyItemExtractionRecoveryError(exc.code, str(exc)) from exc
        self._require_exact_predecessor_distribution(
            predecessor_batch,
            predecessor_manifest,
            expected_manifest_sha256=recovery.predecessor_manifest_sha256,
        )

        with self.sessions() as session:
            existing = session.get(
                LegacyItemExtractionBatchRecord,
                recovery.successor_batch_id,
            )
            self._validate_runtime_history(
                session,
                recovery=recovery,
                predecessor_manifest=predecessor_manifest,
                require_successor_current=existing is None,
            )
        successor_manifest = self._build_successor_manifest(
            recovery,
            predecessor_manifest,
        )
        try:
            batch = self.batches.create(
                CreateLegacyItemExtractionBatchCommand(
                    manifest=successor_manifest,
                    requested_by=command.requested_by,
                    required_current_preset=recovery.successor_preset,
                )
            )
        except LegacyItemExtractionBatchServiceError as exc:
            raise LegacyItemExtractionRecoveryError(exc.code, str(exc)) from exc
        return LegacyItemExtractionRecoveryResult(
            recovery_sha256=recovery.recovery_sha256,
            successor_manifest_sha256=successor_manifest.manifest_sha256,
            batch=batch,
        )

    @staticmethod
    def _require_exact_predecessor_distribution(
        predecessor_batch: LegacyItemExtractionBatchView,
        predecessor_manifest: LegacyItemExtractionBatchManifestV2,
        *,
        expected_manifest_sha256: str,
    ) -> None:
        if (
            predecessor_batch.state != "COMPLETED_WITH_GAPS"
            or predecessor_batch.manifest_sha256 != expected_manifest_sha256
            or predecessor_batch.total_work_unit_count != 108
            or len(predecessor_manifest.work_units) != 108
            or predecessor_batch.accepted_count != 105
            or predecessor_batch.failed_count != 3
            or predecessor_batch.pending_count != 0
            or predecessor_batch.claimed_count != 0
            or predecessor_batch.submitted_count != 0
            or predecessor_batch.awaiting_review_count != 0
            or predecessor_batch.cancelled_count != 0
        ):
            raise LegacyItemExtractionRecoveryError(
                "LEGACY_EXTRACTION_RECOVERY_PREDECESSOR_STATE_INVALID",
                "recovery predecessor state distribution differs",
            )

    def _validate_runtime_history(
        self,
        session: Session,
        *,
        recovery: LegacyItemExtractionValidationRecovery,
        predecessor_manifest: LegacyItemExtractionBatchManifestV2,
        require_successor_current: bool,
    ) -> None:
        batch = session.get(
            LegacyItemExtractionBatchRecord,
            recovery.predecessor_batch_id,
        )
        failed = tuple(
            session.scalars(
                select(LegacyItemExtractionBatchWorkUnitRecord)
                .where(
                    LegacyItemExtractionBatchWorkUnitRecord.extraction_batch_id
                    == recovery.predecessor_batch_id,
                    LegacyItemExtractionBatchWorkUnitRecord.state == "FAILED",
                )
                .order_by(LegacyItemExtractionBatchWorkUnitRecord.ordinal)
            )
        )
        replacements = {
            replacement.predecessor_work_unit_id: replacement
            for replacement in recovery.replacements
        }
        if (
            batch is None
            or batch.state != "COMPLETED_WITH_GAPS"
            or batch.manifest_sha256 != recovery.predecessor_manifest_sha256
            or len(failed) != 3
            or {record.work_unit_id for record in failed} != set(replacements)
        ):
            self._fail(
                "LEGACY_EXTRACTION_RECOVERY_PREDECESSOR_STATE_INVALID",
                "recovery does not exactly cover the predecessor failed set",
            )

        manifest_units = {unit.work_unit_id: unit for unit in predecessor_manifest.work_units}
        for record in failed:
            replacement = replacements[record.work_unit_id]
            unit = manifest_units.get(record.work_unit_id)
            workflow = session.get(WorkflowInstanceRecord, replacement.predecessor_workflow_id)
            job = session.get(JobRecord, replacement.predecessor_platform_job_id)
            step = session.scalar(
                select(WorkflowStepRunRecord).where(
                    WorkflowStepRunRecord.workflow_id == replacement.predecessor_workflow_id,
                    WorkflowStepRunRecord.platform_job_id
                    == replacement.predecessor_platform_job_id,
                )
            )
            message_sha256 = (
                "sha256:" + hashlib.sha256(job.error_message.encode("utf-8")).hexdigest()
                if job is not None and job.error_message is not None
                else None
            )
            if (
                unit is None
                or unit.execution_mode != "EXECUTE"
                or unit.reuse_accepted is not None
                or record.ordinal != replacement.predecessor_ordinal
                or record.extraction_request_id != replacement.predecessor_extraction_request_id
                or record.request_sha256 != replacement.predecessor_request_sha256
                or record.workflow_id != replacement.predecessor_workflow_id
                or record.platform_job_id != replacement.predecessor_platform_job_id
                or record.error_code != replacement.failure_code
                or record.execution_mode != "EXECUTE"
                or record.assessment_source_bundle_revision_id
                != replacement.predecessor_bundle_revision_id
                or record.expected_item_numbers_sha256 != replacement.expected_item_numbers_sha256
                or record.submission_attempts != 1
                or record.extraction_result_id is not None
                or record.result_sha256 is not None
                or record.receipt_artifact_id is not None
                or record.receipt_artifact_revision_id is not None
                or record.receipt_artifact_sha256 is not None
                or record.acceptance_id is not None
                or record.acceptance_sha256 is not None
                or unit.ordinal != replacement.predecessor_ordinal
                or unit.request.extraction_request_id
                != replacement.predecessor_extraction_request_id
                or unit.request.request_sha256 != replacement.predecessor_request_sha256
                or unit.request.bundle.assessment_source_bundle_revision_id
                != replacement.predecessor_bundle_revision_id
                or unit.request.expected_item_numbers != replacement.expected_item_numbers
                or unit.expected_item_numbers_sha256 != replacement.expected_item_numbers_sha256
                or workflow is None
                or workflow.definition_id != recovery.predecessor_preset.workflow_definition_id
                or workflow.definition_key != "legacy-item-extraction"
                or workflow.definition_version
                != recovery.predecessor_preset.workflow_definition_version
                or workflow.definition_hash
                != recovery.predecessor_preset.workflow_definition_sha256
                or workflow.role_schema_version != recovery.predecessor_preset.role_schema_version
                or workflow.state != "FAILED"
                or workflow.failure_code != replacement.workflow_failure_code
                or job is None
                or job.protocol_version != recovery.predecessor_preset.role_schema_version
                or job.task_type != "workflow_support"
                or job.status != "FAILED"
                or job.error_code != replacement.job_error_code
                or message_sha256 != replacement.failure_message_sha256
                or step is None
                or step.workflow_id != replacement.predecessor_workflow_id
                or step.platform_job_id != replacement.predecessor_platform_job_id
                or step.step_key != "extract"
                or step.attempt != 1
                or step.step_type != "agent"
                or step.worker_role != "support"
                or step.result_schema != "legacy-item-extraction-result@1.0"
                or step.state != "FAILED"
                or step.error_code != replacement.job_error_code
            ):
                self._fail(
                    "LEGACY_EXTRACTION_RECOVERY_PREDECESSOR_POINTER_STALE",
                    "failed extraction predecessor evidence differs",
                )

        try:
            predecessor_preset = resolve_legacy_extraction_preset_pointer(
                session,
                recovery.predecessor_preset,
                require_current=False,
            )
            successor_preset = resolve_legacy_extraction_preset_pointer(
                session,
                recovery.successor_preset,
                require_current=require_successor_current,
            )
        except LegacyExtractionPresetResolutionError as exc:
            raise LegacyItemExtractionRecoveryError(exc.code, str(exc)) from exc
        if any(
            unit.request.execution_preset_id != recovery.predecessor_preset.preset_id
            or unit.request.execution_preset_revision_id
            != recovery.predecessor_preset.preset_revision_id
            or unit.request.execution_preset_sha256 != recovery.predecessor_preset.preset_sha256
            for unit in (manifest_units[record.work_unit_id] for record in failed)
        ):
            self._fail(
                "LEGACY_EXTRACTION_RECOVERY_PREDECESSOR_POINTER_STALE",
                "failed extraction requests do not pin the reviewed predecessor preset",
            )
        self._require_instruction_only_successor(
            session,
            predecessor=predecessor_preset,
            successor=successor_preset,
            recovery=recovery,
        )

    @staticmethod
    def _require_instruction_only_successor(
        session: Session,
        *,
        predecessor: ExecutionPresetRevision,
        successor: ExecutionPresetRevision,
        recovery: LegacyItemExtractionValidationRecovery,
    ) -> None:
        predecessor_bundle = session.get(
            ExecutionBundleRevisionRecord,
            recovery.predecessor_preset.instruction_bundle_revision_id,
        )
        successor_bundle = session.get(
            ExecutionBundleRevisionRecord,
            recovery.successor_preset.instruction_bundle_revision_id,
        )
        if (
            predecessor_bundle is None
            or successor_bundle is None
            or successor_bundle.revision_number != predecessor_bundle.revision_number + 1
            or successor.revision_number != predecessor.revision_number + 2
        ):
            raise LegacyItemExtractionRecoveryError(
                "LEGACY_EXTRACTION_RECOVERY_SUCCESSOR_INVALID",
                "extraction recovery successor is not append-only",
            )
        predecessor_policy = _execution_policy(predecessor)
        successor_policy = _execution_policy(successor)
        successor_policy["role_policies"][0]["instruction_bundle"] = predecessor_policy[
            "role_policies"
        ][0]["instruction_bundle"]
        if successor_policy != predecessor_policy:
            raise LegacyItemExtractionRecoveryError(
                "LEGACY_EXTRACTION_RECOVERY_SUCCESSOR_INVALID",
                "extraction recovery changed a non-instruction policy field",
            )

    @staticmethod
    def _build_successor_manifest(
        recovery: LegacyItemExtractionValidationRecovery,
        predecessor: LegacyItemExtractionBatchManifestV2,
    ) -> LegacyItemExtractionBatchManifestV2:
        predecessor_units = {unit.work_unit_id: unit for unit in predecessor.work_units}
        successor_units: list[LegacyExtractionBatchWorkUnitV2] = []
        for replacement in recovery.replacements:
            prior = predecessor_units[replacement.predecessor_work_unit_id]
            request_document = prior.request.model_dump(mode="json")
            request_document.update(
                {
                    "extraction_request_id": replacement.successor_extraction_request_id,
                    "work_unit_ordinal": replacement.successor_ordinal,
                    "execution_preset_id": recovery.successor_preset.preset_id,
                    "execution_preset_revision_id": (recovery.successor_preset.preset_revision_id),
                    "execution_preset_sha256": recovery.successor_preset.preset_sha256,
                    "created_at": recovery.created_at.isoformat().replace("+00:00", "Z"),
                    "request_sha256": "sha256:" + "0" * 64,
                }
            )
            request_document["request_sha256"] = content_sha256(
                {key: value for key, value in request_document.items() if key != "request_sha256"}
            )
            request = LegacyItemExtractionRequest.model_validate(request_document)
            successor_units.append(
                LegacyExtractionBatchWorkUnitV2(
                    work_unit_id=replacement.successor_work_unit_id,
                    ordinal=replacement.successor_ordinal,
                    request=request,
                    expected_item_numbers_sha256=replacement.expected_item_numbers_sha256,
                    execution_mode="EXECUTE",
                    reuse_accepted=None,
                    corpus_source_bindings=prior.corpus_source_bindings,
                )
            )
        manifest_document: dict[str, Any] = {
            "schema_version": "legacy-item-extraction-batch/1.1",
            "extraction_batch_id": recovery.successor_batch_id,
            "idempotency_key": recovery.successor_idempotency_key,
            "inventory_id": predecessor.inventory_id,
            "inventory_sha256": predecessor.inventory_sha256,
            "inventory_artifact": predecessor.inventory_artifact.model_dump(mode="json"),
            "failure_policy": "CONTINUE_AND_COLLECT",
            "work_units": [unit.model_dump(mode="json") for unit in successor_units],
            "created_at": recovery.created_at.isoformat().replace("+00:00", "Z"),
            "manifest_sha256": "sha256:" + "0" * 64,
        }
        manifest_document["manifest_sha256"] = content_sha256(
            {key: value for key, value in manifest_document.items() if key != "manifest_sha256"}
        )
        manifest = LegacyItemExtractionBatchManifestV2.model_validate(manifest_document)
        validate_contract("legacy-item-extraction-batch-v2", manifest.model_dump(mode="json"))
        return manifest

    @staticmethod
    def _fail(code: str, message: str) -> None:
        raise LegacyItemExtractionRecoveryError(code, message)


def _execution_policy(preset: ExecutionPresetRevision) -> dict[str, Any]:
    document = preset.model_dump(mode="json")
    return {
        "capacity_policy_revision_id": document["capacity_policy_revision_id"],
        "compatible_workflow_protocols": document["compatible_workflow_protocols"],
        "general_knowledge_policy": document["general_knowledge_policy"],
        "role_policies": document["role_policies"],
    }


__all__ = [
    "CreateLegacyItemExtractionRecoveryCommand",
    "LegacyItemExtractionRecoveryError",
    "LegacyItemExtractionRecoveryResult",
    "LegacyItemExtractionRecoveryService",
]
