"""Transactional application boundary for one legacy item extraction workflow.

The authoritative pilot record is deliberately pointer-oriented: the workflow,
its resolved plan, step run/platform Job, and the orchestrator-written receipt
Artifact Revision.  This service never copies the worker's extraction result
JSON into a Catalog table.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from eom_catalog_contracts import (
    AssessmentArtifactMemberPointer,
    LegacyItemExtractionReceipt,
    LegacyItemExtractionRequest,
    validate_contract,
)
from eom_identifiers import content_sha256
from eom_orchestrator.control_models import (
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
    ResolvedExecutionPlanRecord,
    ResolvedExecutionPlanStepRecord,
    WorkerCapacityPoolSlotRecord,
)
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.execution_resolver import resolve_legacy_item_extraction_plan
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_workflow import WorkflowRequest
from eom_workflow.control_plane import ExecutionPresetRevision
from eom_workflow_runner.errors import WorkflowError
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.repository import (
    CommandType,
    admitted_workflow_definition,
    create_workflow_instance,
    enqueue_command,
)
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from eom_catalog_service.item_origin_models import (
    AssessmentOccurrenceRecord,
    AssessmentOccurrenceRevisionRecord,
)
from eom_catalog_service.legacy_assessment_models import (
    AssessmentLayoutObservationRecord,
    AssessmentSourceBundleMemberRecord,
    AssessmentSourceBundleRecord,
    AssessmentSourceBundleRevisionRecord,
)

WORKFLOW_KEY = "legacy-item-extraction"
WORKFLOW_VERSION = "1.0.0"
WORKFLOW_ROLE_PROTOCOL = "workflow-role/1.14.0"
WORKER_POOL_KEY = "legacy-extraction"
DEDICATED_SLOT_ID = "06"
MAX_POINTER_MEMBER_BYTES = 512 * 1024 * 1024
type ReviewedBundleMemberIdentity = tuple[str, str, str, str, str, str, str]


class LegacyItemExtractionServiceError(RuntimeError):
    """Stable, content-free error raised at the extraction application boundary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CreateLegacyItemExtractionCommand:
    request: LegacyItemExtractionRequest
    idempotency_key: str
    requested_by: str

    def __post_init__(self) -> None:
        if not 1 <= len(self.idempotency_key) <= 128:
            raise ValueError("idempotency key length is invalid")
        if not 1 <= len(self.requested_by) <= 128:
            raise ValueError("requested actor length is invalid")
        if any(ord(character) < 0x20 for character in self.idempotency_key):
            raise ValueError("idempotency key contains a control character")
        if any(ord(character) < 0x20 for character in self.requested_by):
            raise ValueError("requested actor contains a control character")


@dataclass(frozen=True)
class LegacyItemExtractionApplicationResult:
    extraction_request_id: str
    request_sha256: str
    workflow_id: str
    workflow_state: str
    workflow_stage: str
    plan_id: str
    plan_sha256: str
    preset_id: str
    preset_revision_id: str
    worker_pool_key: str
    dedicated_slot_id: str
    start_command_id: str
    platform_job_id: str | None
    worker_slot_id: str | None
    job_status: str | None
    receipt_artifact_id: str | None
    receipt_artifact_revision_id: str | None
    receipt_content_sha256: str | None
    extraction_result_id: str | None
    result_sha256: str | None

    def as_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.__dataclass_fields__}


class LegacyItemExtractionApplicationService:
    """Validate reviewed pointers, resolve V6, and enqueue exactly one start command."""

    def __init__(self, engine: Engine) -> None:
        self.sessions = build_session_factory(engine)

    def create(
        self, command: CreateLegacyItemExtractionCommand
    ) -> LegacyItemExtractionApplicationResult:
        try:
            validate_contract(
                "legacy-item-extraction-request",
                command.request.model_dump(mode="json"),
            )
        except (JsonSchemaValidationError, ValueError) as exc:
            raise LegacyItemExtractionServiceError(
                "LEGACY_ITEM_EXTRACTION_REQUEST_INVALID",
                "legacy item extraction request is invalid",
            ) from exc

        submission_sha256 = content_sha256(
            {
                "request": command.request.model_dump(mode="json"),
                "requested_by": command.requested_by,
            }
        )
        workflow_idempotency_key = self._workflow_idempotency_key(command.idempotency_key)
        try:
            with transaction(self.sessions) as session:
                existing = session.scalar(
                    select(WorkflowInstanceRecord)
                    .where(WorkflowInstanceRecord.idempotency_key == workflow_idempotency_key)
                    .with_for_update()
                )
                if existing is not None:
                    if (
                        existing.runtime_context.get("legacy_item_extraction_submission_sha256")
                        != submission_sha256
                        or existing.created_actor_id != command.requested_by
                    ):
                        self._fail(
                            "LEGACY_ITEM_EXTRACTION_IDEMPOTENCY_CONFLICT",
                            "legacy item extraction idempotency key has different input",
                        )
                    return self._projection(session, existing)

                duplicate_request = session.scalar(
                    self._duplicate_request_statement(command.request.extraction_request_id)
                )
                if duplicate_request is not None:
                    self._fail(
                        "LEGACY_ITEM_EXTRACTION_IDENTITY_CONFLICT",
                        "legacy item extraction request identity already has a workflow",
                    )

                self._validate_reviewed_pointers(session, command.request)
                definition = admitted_workflow_definition(
                    session,
                    definition_key=WORKFLOW_KEY,
                    definition_version=WORKFLOW_VERSION,
                )
                if definition is None:
                    self._fail(
                        "LEGACY_ITEM_EXTRACTION_WORKFLOW_UNAVAILABLE",
                        "legacy item extraction workflow definition is unavailable",
                    )
                workflow_request = WorkflowRequest(
                    request_name="LEGACY_ITEM_EXTRACTION_REQUEST",
                    image_mode="skip",
                    legacy_extraction_request=command.request,
                )
                workflow, created = create_workflow_instance(
                    session,
                    definition=definition,
                    request=workflow_request,
                    idempotency_key=workflow_idempotency_key,
                    actor_type="human",
                    actor_id=command.requested_by,
                    runtime_context={
                        "legacy_item_extraction_submission_sha256": submission_sha256,
                        "legacy_item_extraction_request_sha256": command.request.request_sha256,
                    },
                )
                if not created:
                    self._fail(
                        "LEGACY_ITEM_EXTRACTION_CONCURRENCY_CONFLICT",
                        "an equivalent legacy item extraction workflow already exists",
                    )
                if workflow.role_schema_version != WORKFLOW_ROLE_PROTOCOL:
                    self._fail(
                        "LEGACY_ITEM_EXTRACTION_WORKFLOW_INCOMPATIBLE",
                        "legacy item extraction workflow protocol is incompatible",
                    )
                plan = resolve_legacy_item_extraction_plan(
                    session,
                    workflow_id=workflow.workflow_id,
                    workflow_definition_version=definition.definition_version,
                    workflow_definition_sha256=definition.definition_hash,
                    workflow_role_schema_version=workflow.role_schema_version,
                    request=command.request,
                )
                self._require_dedicated_slot(session, plan.capacity_policy_revision_id)
                context = dict(workflow.runtime_context)
                context["execution_plan"] = {
                    "plan_id": plan.plan_id,
                    "plan_sha256": plan.plan_sha256,
                    "preset_id": plan.preset_id,
                    "preset_revision_id": plan.preset_revision_id,
                }
                workflow.runtime_context = context
                start, command_created = enqueue_command(
                    session,
                    workflow_id=workflow.workflow_id,
                    command_type=CommandType.START_WORKFLOW,
                    payload={},
                    actor_type="human",
                    actor_id=command.requested_by,
                    source="legacy_item_extraction",
                    idempotency_key=f"start:{workflow.workflow_id}",
                )
                if not command_created:
                    self._fail(
                        "LEGACY_ITEM_EXTRACTION_CONCURRENCY_CONFLICT",
                        "legacy item extraction start command already exists",
                    )
                session.flush()
                return self._projection(
                    session,
                    workflow,
                    expected_start_command_id=start.command_id,
                )
        except LegacyItemExtractionServiceError:
            raise
        except ControlPlaneError as exc:
            raise LegacyItemExtractionServiceError(
                "LEGACY_ITEM_EXTRACTION_PRESET_INCOMPATIBLE",
                "legacy item extraction execution plan could not be resolved",
            ) from exc
        except WorkflowError as exc:
            raise LegacyItemExtractionServiceError(
                "LEGACY_ITEM_EXTRACTION_CONCURRENCY_CONFLICT",
                "legacy item extraction workflow could not be created",
            ) from exc
        except IntegrityError as exc:
            raise LegacyItemExtractionServiceError(
                "LEGACY_ITEM_EXTRACTION_CONCURRENCY_CONFLICT",
                "legacy item extraction submission raced with another transaction",
            ) from exc
        except (PydanticValidationError, ValueError) as exc:
            raise LegacyItemExtractionServiceError(
                "LEGACY_ITEM_EXTRACTION_REQUEST_INVALID",
                "legacy item extraction request could not be persisted",
            ) from exc

    def inspect(self, workflow_id: str) -> LegacyItemExtractionApplicationResult:
        """Project only workflow/plan/Job/receipt pointers, never the large result document."""

        if not workflow_id.startswith("workflow_") or len(workflow_id) != 41:
            self._fail(
                "LEGACY_ITEM_EXTRACTION_WORKFLOW_NOT_FOUND",
                "legacy item extraction workflow was not found",
            )
        with self.sessions() as session:
            workflow = session.get(WorkflowInstanceRecord, workflow_id)
            if workflow is None or workflow.definition_key != WORKFLOW_KEY:
                self._fail(
                    "LEGACY_ITEM_EXTRACTION_WORKFLOW_NOT_FOUND",
                    "legacy item extraction workflow was not found",
                )
            return self._projection(session, workflow)

    def validate_reviewed_request(
        self, session: Session, request: LegacyItemExtractionRequest
    ) -> None:
        """Validate one exact reviewed request without creating a workflow."""

        self._validate_reviewed_pointers(session, request)

    def _validate_reviewed_pointers(
        self, session: Session, request: LegacyItemExtractionRequest
    ) -> None:
        bundle = session.get(
            AssessmentSourceBundleRecord,
            request.bundle.assessment_source_bundle_id,
        )
        bundle_revision = session.get(
            AssessmentSourceBundleRevisionRecord,
            request.bundle.assessment_source_bundle_revision_id,
        )
        if (
            bundle is None
            or bundle_revision is None
            or bundle.lifecycle_state != "ACTIVE"
            or bundle_revision.assessment_source_bundle_id
            != request.bundle.assessment_source_bundle_id
            or bundle_revision.state not in {"REVIEWED", "SUPERSEDED"}
            or bundle_revision.bundle_manifest_sha256 != request.bundle.bundle_manifest_sha256
        ):
            self._stale("reviewed assessment source bundle pointer is stale")

        occurrence = session.get(
            AssessmentOccurrenceRecord,
            request.occurrence.assessment_occurrence_id,
        )
        occurrence_revision = session.get(
            AssessmentOccurrenceRevisionRecord,
            request.occurrence.assessment_occurrence_revision_id,
        )
        if (
            occurrence is None
            or occurrence_revision is None
            or occurrence.lifecycle_state != "ACTIVE"
            or occurrence_revision.assessment_occurrence_id
            != request.occurrence.assessment_occurrence_id
            or occurrence_revision.revision_state not in {"REVIEWED", "SUPERSEDED"}
            or occurrence_revision.revision_sha256 != request.occurrence.occurrence_revision_sha256
            or bundle_revision.assessment_occurrence_id
            != request.occurrence.assessment_occurrence_id
            or bundle_revision.assessment_occurrence_revision_id
            != request.occurrence.assessment_occurrence_revision_id
            or bundle_revision.occurrence_revision_sha256
            != request.occurrence.occurrence_revision_sha256
        ):
            self._stale("reviewed assessment occurrence pointer is stale")
        if (
            bundle_revision.rights_policy_id != occurrence_revision.rights_policy_id
            or bundle_revision.rights_policy_revision_id
            != occurrence_revision.rights_policy_revision_id
            or bundle_revision.rights_policy_sha256 != occurrence_revision.rights_policy_sha256
        ):
            self._fail(
                "LEGACY_ITEM_EXTRACTION_RIGHTS_INVALID",
                "bundle and occurrence rights policies are inconsistent",
            )

        layout = session.get(
            AssessmentLayoutObservationRecord,
            request.layout_observation.assessment_layout_observation_id,
        )
        layout_pointer = request.layout_observation.artifact
        if (
            layout is None
            or layout.assessment_source_bundle_id != request.bundle.assessment_source_bundle_id
            or layout.assessment_source_bundle_revision_id
            != request.bundle.assessment_source_bundle_revision_id
            or layout.bundle_manifest_sha256 != request.bundle.bundle_manifest_sha256
            or layout.artifact_id != layout_pointer.artifact_id
            or layout.artifact_revision_id != layout_pointer.artifact_revision_id
            or layout.artifact_member_path != layout_pointer.member_path
            or layout.artifact_schema_ref != layout_pointer.schema_ref
            or layout.artifact_media_type != layout_pointer.media_type
            or layout.artifact_sha256 != layout_pointer.sha256
            or layout.observation_sha256 != request.layout_observation.observation_sha256
        ):
            self._stale("reviewed assessment layout pointer is stale")
        self._require_artifact_member(session, layout_pointer)

        members = list(
            session.scalars(
                select(AssessmentSourceBundleMemberRecord).where(
                    AssessmentSourceBundleMemberRecord.assessment_source_bundle_revision_id
                    == request.bundle.assessment_source_bundle_revision_id
                )
            )
        )
        member_index = {
            (
                member.role,
                member.source_artifact_id,
                member.source_artifact_revision_id,
                member.source_member_path,
                member.source_schema_ref,
                member.source_media_type,
                member.source_sha256,
            )
            for member in members
        }
        for page in request.page_inputs:
            self._require_reviewed_bundle_member(
                member_index,
                role=page.source_role,
                pointer=page.source,
            )
            self._require_artifact_member(session, page.source)
            self._require_artifact_member(session, page.image)
        for materialization in request.source_materializations:
            self._require_reviewed_bundle_member(
                member_index,
                role=materialization.source_role,
                pointer=materialization.source,
            )
            self._require_artifact_member(session, materialization.source)

        preset = session.get(ExecutionPresetRecord, request.execution_preset_id)
        preset_revision = session.get(
            ExecutionPresetRevisionRecord,
            request.execution_preset_revision_id,
        )
        if (
            preset is None
            or preset_revision is None
            or preset.state != "ACTIVE"
            or preset.preset_key != WORKFLOW_KEY
            or preset_revision.preset_id != preset.preset_id
            or preset_revision.state != "RELEASED"
            or preset_revision.content_sha256 != request.execution_preset_sha256
            or WORKFLOW_ROLE_PROTOCOL not in preset_revision.compatible_workflow_protocols
        ):
            self._stale("legacy item extraction preset pointer is stale")
        try:
            canonical_preset = ExecutionPresetRevision.model_validate(
                preset_revision.canonical_document
            )
        except PydanticValidationError as exc:
            raise LegacyItemExtractionServiceError(
                "LEGACY_ITEM_EXTRACTION_PRESET_INCOMPATIBLE",
                "legacy item extraction preset document is invalid",
            ) from exc
        if (
            canonical_preset.preset_id != request.execution_preset_id
            or canonical_preset.preset_revision_id != request.execution_preset_revision_id
            or canonical_preset.content_sha256 != request.execution_preset_sha256
        ):
            self._stale("legacy item extraction preset document differs from its pointer")

    @staticmethod
    def _member_identity(
        role: str, pointer: AssessmentArtifactMemberPointer
    ) -> ReviewedBundleMemberIdentity:
        return (
            role,
            pointer.artifact_id,
            pointer.artifact_revision_id,
            pointer.member_path,
            pointer.schema_ref,
            pointer.media_type,
            pointer.sha256,
        )

    @classmethod
    def _require_reviewed_bundle_member(
        cls,
        member_index: set[ReviewedBundleMemberIdentity],
        *,
        role: str,
        pointer: AssessmentArtifactMemberPointer,
    ) -> None:
        if cls._member_identity(role, pointer) not in member_index:
            cls._stale("assessment source is outside the reviewed bundle")

    def _require_artifact_member(
        self, session: Session, pointer: AssessmentArtifactMemberPointer
    ) -> None:
        artifact = session.get(ArtifactRecord, pointer.artifact_id)
        revision = session.get(ArtifactRevisionRecord, pointer.artifact_revision_id)
        job = session.get(JobRecord, revision.job_id) if revision is not None else None
        files = revision.manifest.get("files") if revision is not None else None
        matching = (
            [
                value
                for value in files
                if isinstance(value, dict) and value.get("file_name") == pointer.member_path
            ]
            if isinstance(files, list)
            else []
        )
        if (
            artifact is None
            or revision is None
            or job is None
            or not artifact.approved
            or not revision.approved
            or job.status != "SUCCEEDED"
            or revision.logical_artifact_id != pointer.artifact_id
            or artifact.job_id != revision.job_id
            or len(matching) != 1
            or matching[0].get("sha256") != pointer.sha256
            or matching[0].get("media_type") != pointer.media_type
            or matching[0].get("schema_ref") != pointer.schema_ref
            or not isinstance(matching[0].get("bytes"), int)
            or not 0 < matching[0]["bytes"] <= MAX_POINTER_MEMBER_BYTES
        ):
            self._stale("Artifact member pointer is stale")

    def _require_dedicated_slot(self, session: Session, capacity_revision_id: str) -> None:
        slots = tuple(
            session.scalars(
                select(WorkerCapacityPoolSlotRecord.slot_id)
                .where(
                    WorkerCapacityPoolSlotRecord.capacity_policy_revision_id
                    == capacity_revision_id,
                    WorkerCapacityPoolSlotRecord.pool_key == WORKER_POOL_KEY,
                )
                .order_by(WorkerCapacityPoolSlotRecord.slot_id)
            )
        )
        if slots != (DEDICATED_SLOT_ID,):
            self._fail(
                "LEGACY_ITEM_EXTRACTION_CAPACITY_INVALID",
                "legacy item extraction pool is not isolated to its dedicated slot",
            )

    def _projection(
        self,
        session: Session,
        workflow: WorkflowInstanceRecord,
        *,
        expected_start_command_id: str | None = None,
    ) -> LegacyItemExtractionApplicationResult:
        request = WorkflowRequest.model_validate(workflow.initial_request)
        extraction = request.legacy_extraction_request
        if extraction is None:
            self._fail(
                "LEGACY_ITEM_EXTRACTION_RECORD_INVALID",
                "workflow does not contain an extraction request",
            )
        plan = session.scalar(
            select(ResolvedExecutionPlanRecord).where(
                ResolvedExecutionPlanRecord.workflow_id == workflow.workflow_id
            )
        )
        step_plan = (
            session.get(ResolvedExecutionPlanStepRecord, (plan.plan_id, "extract"))
            if plan is not None
            else None
        )
        commands = list(
            session.scalars(
                select(WorkflowCommandRecord).where(
                    WorkflowCommandRecord.workflow_id == workflow.workflow_id,
                    WorkflowCommandRecord.command_type == CommandType.START_WORKFLOW.value,
                )
            )
        )
        if (
            plan is None
            or step_plan is None
            or step_plan.worker_pool_key != WORKER_POOL_KEY
            or len(commands) != 1
            or (
                expected_start_command_id is not None
                and commands[0].command_id != expected_start_command_id
            )
        ):
            self._fail(
                "LEGACY_ITEM_EXTRACTION_RECORD_INVALID",
                "legacy item extraction workflow record is incomplete",
            )
        step_run = session.scalar(
            select(WorkflowStepRunRecord)
            .where(
                WorkflowStepRunRecord.workflow_id == workflow.workflow_id,
                WorkflowStepRunRecord.step_key == "extract",
            )
            .order_by(
                WorkflowStepRunRecord.attempt.desc(),
                WorkflowStepRunRecord.step_run_id.desc(),
            )
            .limit(1)
        )
        job = (
            session.get(JobRecord, step_run.platform_job_id)
            if step_run is not None and step_run.platform_job_id is not None
            else None
        )
        receipt: LegacyItemExtractionReceipt | None = None
        if job is not None and job.status == "SUCCEEDED":
            receipt_revision = session.get(ArtifactRevisionRecord, job.revision_id)
            try:
                if receipt_revision is None:
                    raise ValueError("receipt Artifact Revision is missing")
                receipt = LegacyItemExtractionReceipt.model_validate(receipt_revision.result)
                if (
                    not receipt_revision.approved
                    or receipt_revision.logical_artifact_id != job.logical_artifact_id
                    or receipt.extraction_request_id != extraction.extraction_request_id
                    or receipt.request_sha256 != extraction.request_sha256
                    or receipt.result_artifact.artifact_id != job.logical_artifact_id
                    or receipt.result_artifact.artifact_revision_id != job.revision_id
                    or receipt.result_artifact.sha256 != receipt_revision.content_hash
                ):
                    raise ValueError("receipt pointer differs from the platform Job")
            except (PydanticValidationError, ValueError) as exc:
                raise LegacyItemExtractionServiceError(
                    "LEGACY_ITEM_EXTRACTION_RECORD_INVALID",
                    "succeeded extraction Job has an invalid receipt pointer",
                ) from exc
        return LegacyItemExtractionApplicationResult(
            extraction_request_id=extraction.extraction_request_id,
            request_sha256=extraction.request_sha256,
            workflow_id=workflow.workflow_id,
            workflow_state=workflow.state,
            workflow_stage=workflow.stage,
            plan_id=plan.plan_id,
            plan_sha256=plan.plan_sha256,
            preset_id=plan.preset_id,
            preset_revision_id=plan.preset_revision_id,
            worker_pool_key=step_plan.worker_pool_key,
            dedicated_slot_id=DEDICATED_SLOT_ID,
            start_command_id=commands[0].command_id,
            platform_job_id=job.job_id if job is not None else None,
            worker_slot_id=job.worker_slot_id if job is not None else None,
            job_status=job.status if job is not None else None,
            receipt_artifact_id=(
                receipt.result_artifact.artifact_id if receipt is not None else None
            ),
            receipt_artifact_revision_id=(
                receipt.result_artifact.artifact_revision_id if receipt is not None else None
            ),
            receipt_content_sha256=(
                receipt.result_artifact.sha256 if receipt is not None else None
            ),
            extraction_result_id=receipt.extraction_result_id if receipt is not None else None,
            result_sha256=receipt.result_sha256 if receipt is not None else None,
        )

    @staticmethod
    def _workflow_idempotency_key(operator_key: str) -> str:
        digest = content_sha256(
            {"scope": "legacy-item-extraction", "idempotency_key": operator_key}
        ).removeprefix("sha256:")
        return f"legacy-item-extraction:{digest}"

    @staticmethod
    def _duplicate_request_statement(
        extraction_request_id: str,
    ) -> Select[tuple[WorkflowInstanceRecord]]:
        """Use JSON traversal that compiles on both PostgreSQL and SQLite."""

        return (
            select(WorkflowInstanceRecord)
            .where(
                WorkflowInstanceRecord.definition_key == WORKFLOW_KEY,
                WorkflowInstanceRecord.initial_request["legacy_extraction_request"][
                    "extraction_request_id"
                ].as_string()
                == extraction_request_id,
            )
            .order_by(
                WorkflowInstanceRecord.created_at,
                WorkflowInstanceRecord.workflow_id,
            )
            .limit(1)
            .with_for_update()
        )

    @staticmethod
    def _stale(message: str) -> NoReturn:
        raise LegacyItemExtractionServiceError(
            "LEGACY_ITEM_EXTRACTION_POINTER_STALE",
            message,
        )

    @staticmethod
    def _fail(code: str, message: str) -> NoReturn:
        raise LegacyItemExtractionServiceError(code, message)
