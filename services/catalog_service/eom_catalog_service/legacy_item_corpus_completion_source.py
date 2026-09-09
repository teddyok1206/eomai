"""Concrete repeatable-read source for exact legacy corpus coverage completion."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Collection
from datetime import UTC
from typing import NoReturn, TypeVar

from eom_catalog_contracts import (
    AssessmentArtifactMemberPointer,
    LegacyExtractionBatchWorkUnitV2,
    LegacyItemCorpusCompletionCommand,
    LegacyItemExtractionAcceptance,
    LegacyItemExtractionBatchManifestV2,
    LegacyItemExtractionReceipt,
    LegacyItemExtractionRequest,
    LegacyItemExtractionResult,
    LegacyItemExtractionValidationRecovery,
    LegacySourceInventoryV2,
    validate_contract,
)
from eom_identifiers import content_sha256
from eom_identity_service.models import (
    OperatorRecord,
    OperatorRoleAssignmentRecord,
    PermissionRecord,
    RolePermissionRecord,
)
from eom_operator_identity import PermissionKey
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_workflow import WorkflowRequest
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from eom_catalog_service.legacy_assessment_models import (
    LegacyItemExtractionAcceptanceRecord,
)
from eom_catalog_service.legacy_item_corpus_completion_service import (
    AcceptedTerminalWorkUnit,
    FailedTerminalWorkUnit,
    LegacyItemCorpusCompletionError,
    ResolvedArtifactRevision,
    ResolvedBatchSnapshot,
    ResolvedCorpusCompletionSnapshot,
)
from eom_catalog_service.legacy_item_extraction_batch_models import (
    LegacyItemExtractionBatchRecord,
    LegacyItemExtractionBatchWorkUnitRecord,
)
from eom_catalog_service.pinned_artifact_resolution import (
    PinnedArtifactMember,
    PinnedArtifactResolutionError,
    resolve_pinned_artifact_member,
)
from eom_catalog_service.settings import CatalogSettings

MAX_INVENTORY_BYTES = 32 * 1024 * 1024
MAX_BATCH_MANIFEST_BYTES = 32 * 1024 * 1024
MAX_RECOVERY_BYTES = 2 * 1024 * 1024
MAX_EXTRACTION_RESULT_BYTES = 16 * 1024 * 1024
MAX_ACCEPTANCE_BYTES = 16 * 1024 * 1024
TModel = TypeVar("TModel", bound=BaseModel)


class PostgresLegacyItemCorpusCompletionSource:
    """Resolve every generic coverage input inside one PostgreSQL repeatable-read snapshot."""

    def __init__(self, engine: Engine, settings: CatalogSettings | None = None) -> None:
        self.engine = engine
        self.sessions = build_session_factory(engine)
        self.settings = settings or CatalogSettings.from_environment()

    def resolve_completion_snapshot(
        self,
        command: LegacyItemCorpusCompletionCommand,
    ) -> ResolvedCorpusCompletionSnapshot:
        try:
            with self.sessions() as session, session.begin():
                if session.bind is not None and session.bind.dialect.name == "postgresql":
                    session.execute(
                        text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                    )
                return self.resolve_completion_snapshot_in_session(session, command)
        except LegacyItemCorpusCompletionError:
            raise
        except (
            JsonSchemaValidationError,
            PinnedArtifactResolutionError,
            PydanticValidationError,
            UnicodeError,
            ValueError,
        ) as exc:
            raise LegacyItemCorpusCompletionError(
                "LEGACY_ITEM_CORPUS_COMPLETION_SOURCE_INVALID",
                "completion source snapshot does not resolve",
            ) from exc

    def resolve_completion_snapshot_in_session(
        self,
        session: Session,
        command: LegacyItemCorpusCompletionCommand,
    ) -> ResolvedCorpusCompletionSnapshot:
        """Resolve the same evidence inside a caller-owned repeatable-read transaction."""

        active, authorized = self._operator_authority(session, command.requested_by)
        if not active or not authorized:
            self._fail("completion operator is not active and authorized")
        original = self._resolve_batch(
            session,
            batch_id=command.original_batch.extraction_batch_id,
            manifest_sha256=command.original_batch.manifest_sha256,
        )
        successor = self._resolve_batch(
            session,
            batch_id=command.successor_batch.extraction_batch_id,
            manifest_sha256=command.successor_batch.manifest_sha256,
        )
        inventory_pointer = original.manifest.inventory_artifact
        inventory_member = self._resolve_member(
            session,
            pointer=inventory_pointer,
            artifact_types={"legacy-source-inventory"},
            primary_file="legacy-source-inventory.json",
            max_bytes=MAX_INVENTORY_BYTES,
        )
        inventory = self._typed_json(
            inventory_member.payload,
            route="legacy-source-inventory-v2",
            model=LegacySourceInventoryV2,
        )
        recovery_member = self._resolve_member(
            session,
            pointer=command.recovery_artifact,
            artifact_types={
                "control_legacy_item_extraction_validation_recovery",
                "legacy-item-extraction-validation-recovery",
            },
            primary_file="validation-recovery.json",
            max_bytes=MAX_RECOVERY_BYTES,
        )
        recovery = self._typed_json(
            recovery_member.payload,
            route="legacy-item-extraction-validation-recovery",
            model=LegacyItemExtractionValidationRecovery,
        )
        return ResolvedCorpusCompletionSnapshot(
            requested_by=command.requested_by,
            requester_active=True,
            requester_authorized=True,
            recovery=recovery,
            recovery_artifact_resolution=self._resolution(
                command.recovery_artifact, recovery_member
            ),
            inventory=inventory,
            inventory_artifact_resolution=self._resolution(inventory_pointer, inventory_member),
            original_batch=original,
            successor_batch=successor,
        )

    def _resolve_batch(
        self,
        session: Session,
        *,
        batch_id: str,
        manifest_sha256: str,
    ) -> ResolvedBatchSnapshot:
        batch = session.get(LegacyItemExtractionBatchRecord, batch_id)
        if batch is None:
            self._fail("completion batch does not exist")
        pointer = AssessmentArtifactMemberPointer(
            artifact_id=batch.manifest_artifact_id,
            artifact_revision_id=batch.manifest_artifact_revision_id,
            member_path=batch.manifest_artifact_member_path,
            schema_ref=batch.manifest_artifact_schema_ref,
            media_type=batch.manifest_artifact_media_type,
            sha256=batch.manifest_artifact_sha256,
        )
        member = self._resolve_member(
            session,
            pointer=pointer,
            artifact_types={"legacy-item-extraction-batch"},
            primary_file="legacy-item-extraction-batch.json",
            max_bytes=MAX_BATCH_MANIFEST_BYTES,
        )
        manifest = self._typed_json(
            member.payload,
            route="legacy-item-extraction-batch-v2",
            model=LegacyItemExtractionBatchManifestV2,
        )
        if (
            batch.schema_version != manifest.schema_version
            or batch.idempotency_key != manifest.idempotency_key
            or batch.manifest_sha256 != manifest_sha256
            or manifest.manifest_sha256 != manifest_sha256
            or manifest.extraction_batch_id != batch_id
            or batch.inventory_id != manifest.inventory_id
            or batch.inventory_sha256 != manifest.inventory_sha256
            or batch.failure_policy != manifest.failure_policy
            or batch.total_work_unit_count != len(manifest.work_units)
            or batch.created_at.astimezone(UTC) != manifest.created_at
            or batch.completed_at is None
            or batch.state not in {"COMPLETED_WITH_GAPS", "SUCCEEDED"}
        ):
            self._fail("completion batch identity or state differs")

        rows = tuple(
            session.scalars(
                select(LegacyItemExtractionBatchWorkUnitRecord)
                .where(LegacyItemExtractionBatchWorkUnitRecord.extraction_batch_id == batch_id)
                .order_by(
                    LegacyItemExtractionBatchWorkUnitRecord.ordinal,
                    LegacyItemExtractionBatchWorkUnitRecord.work_unit_id,
                )
            )
        )
        acceptance_ids = tuple(
            sorted({row.acceptance_id for row in rows if row.acceptance_id is not None})
        )
        acceptances = {
            value.acceptance_id: value
            for value in session.scalars(
                select(LegacyItemExtractionAcceptanceRecord).where(
                    LegacyItemExtractionAcceptanceRecord.acceptance_id.in_(acceptance_ids)
                )
            )
        }
        revision_ids = tuple(
            sorted(
                {
                    identity
                    for acceptance in acceptances.values()
                    for identity in (
                        acceptance.result_artifact_revision_id,
                        acceptance.acceptance_artifact_revision_id,
                    )
                }
            )
        )
        self._preload_artifact_graph(session, revision_ids)
        workflow_ids = tuple(
            sorted({row.workflow_id for row in rows if row.workflow_id is not None})
        )
        workflows = {
            value.workflow_id: value
            for value in session.scalars(
                select(WorkflowInstanceRecord).where(
                    WorkflowInstanceRecord.workflow_id.in_(workflow_ids)
                )
            )
        }
        job_ids = tuple(
            sorted({row.platform_job_id for row in rows if row.platform_job_id is not None})
        )
        jobs = {
            value.job_id: value
            for value in session.scalars(select(JobRecord).where(JobRecord.job_id.in_(job_ids)))
        }
        steps_by_workflow: dict[str, list[WorkflowStepRunRecord]] = defaultdict(list)
        for value in session.scalars(
            select(WorkflowStepRunRecord)
            .where(
                WorkflowStepRunRecord.workflow_id.in_(workflow_ids),
                WorkflowStepRunRecord.step_key == "extract",
            )
            .order_by(
                WorkflowStepRunRecord.workflow_id,
                WorkflowStepRunRecord.attempt,
                WorkflowStepRunRecord.step_run_id,
            )
        ):
            steps_by_workflow[value.workflow_id].append(value)

        terminals: list[AcceptedTerminalWorkUnit | FailedTerminalWorkUnit] = []
        manifest_by_id = {unit.work_unit_id: unit for unit in manifest.work_units}
        if len(rows) != len(manifest_by_id) or len(manifest_by_id) != len(manifest.work_units):
            self._fail("completion batch row set differs from its manifest")
        for row in rows:
            manifest_unit = manifest_by_id.get(row.work_unit_id)
            if manifest_unit is None or not self._work_unit_row_matches(row, manifest_unit):
                self._fail("completion work unit row differs from its manifest")
            workflow = workflows.get(row.workflow_id or "")
            job = jobs.get(row.platform_job_id or "")
            if manifest_unit.execution_mode == "REUSE_ACCEPTED":
                if row.workflow_id is not None or row.platform_job_id is not None:
                    self._fail("reused completion work unit has execution pointers")
            else:
                self._validate_execute_binding(
                    row=row,
                    request=manifest_unit.request,
                    workflow=workflow,
                    job=job,
                    step_runs=tuple(steps_by_workflow.get(row.workflow_id or "", ())),
                )
            completed_at = row.completed_at
            if completed_at is None:
                self._fail("completion work unit lacks a terminal timestamp")
            if row.state == "ACCEPTED":
                terminals.append(
                    self._accepted_terminal(
                        session,
                        row=row,
                        acceptance=acceptances.get(row.acceptance_id or ""),
                        producing_job=job,
                        execution_mode=manifest_unit.execution_mode,
                    )
                )
            elif row.state == "FAILED":
                if (
                    workflow is None
                    or job is None
                    or row.workflow_id is None
                    or row.platform_job_id is None
                    or row.error_code is None
                    or workflow.failure_code is None
                    or job.error_code is None
                    or job.error_message is None
                    or row.receipt_artifact_id is not None
                    or row.receipt_artifact_revision_id is not None
                    or row.receipt_artifact_sha256 is not None
                    or row.extraction_result_id is not None
                    or row.result_sha256 is not None
                    or row.acceptance_id is not None
                    or row.acceptance_sha256 is not None
                ):
                    self._fail("failed completion work unit evidence differs")
                terminals.append(
                    FailedTerminalWorkUnit(
                        extraction_batch_id=batch_id,
                        work_unit_id=row.work_unit_id,
                        ordinal=row.ordinal,
                        state="FAILED",
                        extraction_request_id=row.extraction_request_id,
                        request_sha256=row.request_sha256,
                        error_code=row.error_code,
                        workflow_id=row.workflow_id,
                        platform_job_id=row.platform_job_id,
                        workflow_failure_code=workflow.failure_code,
                        job_error_code=job.error_code,
                        failure_message_sha256=(
                            "sha256:"
                            + hashlib.sha256(job.error_message.encode("utf-8")).hexdigest()
                        ),
                        result_present=False,
                        receipt_present=False,
                        acceptance_present=False,
                        completed_at=completed_at.astimezone(UTC),
                    )
                )
            else:
                self._fail("completion batch contains a nonterminal work unit")
        return ResolvedBatchSnapshot(
            manifest=manifest,
            manifest_artifact=pointer,
            manifest_artifact_resolution=self._resolution(pointer, member),
            state=batch.state,  # type: ignore[arg-type]
            work_units=tuple(terminals),
        )

    def _accepted_terminal(
        self,
        session: Session,
        *,
        row: LegacyItemExtractionBatchWorkUnitRecord,
        acceptance: LegacyItemExtractionAcceptanceRecord | None,
        producing_job: JobRecord | None,
        execution_mode: str,
    ) -> AcceptedTerminalWorkUnit:
        if (
            acceptance is None
            or row.acceptance_id is None
            or row.acceptance_sha256 is None
            or row.extraction_result_id is None
            or row.result_sha256 is None
            or row.completed_at is None
            or row.receipt_artifact_id is None
            or row.receipt_artifact_revision_id is None
            or row.receipt_artifact_sha256 is None
        ):
            self._fail("accepted completion work unit pointer is incomplete")
        result_pointer = AssessmentArtifactMemberPointer(
            artifact_id=acceptance.result_artifact_id,
            artifact_revision_id=acceptance.result_artifact_revision_id,
            member_path=acceptance.result_artifact_member_path,
            schema_ref=acceptance.result_artifact_schema_ref,
            media_type=acceptance.result_artifact_media_type,
            sha256=acceptance.result_artifact_sha256,
        )
        acceptance_pointer = AssessmentArtifactMemberPointer(
            artifact_id=acceptance.acceptance_artifact_id,
            artifact_revision_id=acceptance.acceptance_artifact_revision_id,
            member_path=acceptance.acceptance_artifact_member_path,
            schema_ref=acceptance.acceptance_artifact_schema_ref,
            media_type=acceptance.acceptance_artifact_media_type,
            sha256=acceptance.acceptance_artifact_sha256,
        )
        result_member = self._resolve_member(
            session,
            pointer=result_pointer,
            artifact_types={"workflow_support", "legacy-item-extraction-result"},
            manifest_artifact_types={"legacy-item-extraction-result"},
            primary_file="result.json",
            max_bytes=MAX_EXTRACTION_RESULT_BYTES,
        )
        acceptance_member = self._resolve_member(
            session,
            pointer=acceptance_pointer,
            artifact_types={"legacy-item-extraction-acceptance"},
            primary_file="acceptance.json",
            max_bytes=MAX_ACCEPTANCE_BYTES,
        )
        result = self._typed_json(
            result_member.payload,
            route="legacy-item-extraction-result",
            model=LegacyItemExtractionResult,
        )
        acceptance_document = self._typed_json(
            acceptance_member.payload,
            route="legacy-item-extraction-acceptance",
            model=LegacyItemExtractionAcceptance,
        )
        revision = session.get(ArtifactRevisionRecord, result_pointer.artifact_revision_id)
        if revision is None:
            self._fail("accepted completion result database receipt is absent")
        receipt = self._typed_value(
            revision.result,
            route="legacy-item-extraction-receipt",
            model=LegacyItemExtractionReceipt,
        )
        if (
            row.receipt_artifact_id != result_pointer.artifact_id
            or row.receipt_artifact_revision_id != result_pointer.artifact_revision_id
            or row.receipt_artifact_sha256 != result_pointer.sha256
            or acceptance.acceptance_id != acceptance_document.acceptance_id
            or acceptance.extraction_result_id != result.extraction_result_id
            or acceptance.result_sha256 != result.result_sha256
            or acceptance.state != acceptance_document.state
            or acceptance.coverage_state != acceptance_document.coverage_state
            or acceptance.reviewed_at.astimezone(UTC) != acceptance_document.reviewed_at
            or acceptance.reviewed_by != acceptance_document.reviewed_by
            or acceptance.acceptance_sha256 != acceptance_document.acceptance_sha256
            or row.extraction_result_id != result.extraction_result_id
            or row.result_sha256 != result.result_sha256
            or row.acceptance_id != acceptance_document.acceptance_id
            or row.acceptance_sha256 != acceptance_document.acceptance_sha256
            or (
                execution_mode == "EXECUTE"
                and (
                    producing_job is None
                    or row.platform_job_id != revision.job_id
                    or producing_job.job_id != revision.job_id
                    or producing_job.logical_artifact_id != result_pointer.artifact_id
                    or producing_job.revision_id != result_pointer.artifact_revision_id
                    or producing_job.status != "SUCCEEDED"
                )
            )
        ):
            self._fail("accepted completion database projection differs")
        return AcceptedTerminalWorkUnit(
            extraction_batch_id=row.extraction_batch_id,
            work_unit_id=row.work_unit_id,
            ordinal=row.ordinal,
            state="ACCEPTED",
            extraction_request_id=row.extraction_request_id,
            request_sha256=row.request_sha256,
            result_artifact=result_pointer,
            result_artifact_resolution=self._resolution(result_pointer, result_member),
            extraction_result_id=row.extraction_result_id,
            result_sha256=row.result_sha256,
            result=result,
            extraction_receipt_sha256=receipt.receipt_sha256,
            extraction_receipt=receipt,
            acceptance_id=row.acceptance_id,
            acceptance_sha256=row.acceptance_sha256,
            acceptance_artifact=acceptance_pointer,
            acceptance_artifact_resolution=self._resolution(acceptance_pointer, acceptance_member),
            acceptance=acceptance_document,
            completed_at=row.completed_at.astimezone(UTC),
        )

    @classmethod
    def _validate_execute_binding(
        cls,
        *,
        row: LegacyItemExtractionBatchWorkUnitRecord,
        request: LegacyItemExtractionRequest,
        workflow: WorkflowInstanceRecord | None,
        job: JobRecord | None,
        step_runs: tuple[WorkflowStepRunRecord, ...],
    ) -> None:
        matching_steps = tuple(
            value for value in step_runs if value.platform_job_id == row.platform_job_id
        )
        try:
            workflow_request = (
                WorkflowRequest.model_validate(workflow.initial_request)
                if workflow is not None
                else None
            )
        except PydanticValidationError as exc:
            raise LegacyItemCorpusCompletionError(
                "LEGACY_ITEM_CORPUS_COMPLETION_SOURCE_INVALID",
                "executed completion workflow request is invalid",
            ) from exc
        terminal_state_matches = (
            workflow is not None
            and job is not None
            and len(matching_steps) == 1
            and (
                (
                    row.state == "ACCEPTED"
                    and workflow.state == "COMPLETED"
                    and workflow.stage == "COMPLETED"
                    and matching_steps[0].state == "SUCCEEDED"
                    and job.status == "SUCCEEDED"
                )
                or (
                    row.state == "FAILED"
                    and workflow.state in {"FAILED", "CANCELLED"}
                    and matching_steps[0].state in {"FAILED", "CANCELLED"}
                    and job.status in {"FAILED", "CANCELLED"}
                )
            )
        )
        if (
            row.workflow_id is None
            or row.platform_job_id is None
            or workflow is None
            or job is None
            or workflow_request is None
            or workflow.workflow_id != row.workflow_id
            or workflow.definition_key != "legacy-item-extraction"
            or workflow_request.request_name != "LEGACY_ITEM_EXTRACTION_REQUEST"
            or workflow_request.legacy_extraction_request != request
            or workflow.runtime_context.get("legacy_item_extraction_request_sha256")
            != row.request_sha256
            or len(matching_steps) != 1
            or matching_steps[0].workflow_id != workflow.workflow_id
            or matching_steps[0].step_key != "extract"
            or matching_steps[0].step_type != "agent"
            or matching_steps[0].worker_role != "support"
            or matching_steps[0].result_schema != "legacy-item-extraction-result@1.0"
            or job.job_id != row.platform_job_id
            or not terminal_state_matches
        ):
            cls._fail("executed completion work unit provenance differs")

    @staticmethod
    def _work_unit_row_matches(
        row: LegacyItemExtractionBatchWorkUnitRecord,
        unit: LegacyExtractionBatchWorkUnitV2,
    ) -> bool:
        expected_attempts = 0 if unit.execution_mode == "REUSE_ACCEPTED" else 1
        return (
            row.ordinal == unit.ordinal
            and row.extraction_request_id == unit.request.extraction_request_id
            and row.request_sha256 == unit.request.request_sha256
            and row.assessment_source_bundle_id == unit.request.bundle.assessment_source_bundle_id
            and row.assessment_source_bundle_revision_id
            == unit.request.bundle.assessment_source_bundle_revision_id
            and row.bundle_manifest_sha256 == unit.request.bundle.bundle_manifest_sha256
            and row.expected_item_numbers_sha256 == unit.expected_item_numbers_sha256
            and row.corpus_source_bindings_sha256
            == content_sha256(
                {
                    "corpus_source_bindings": [
                        binding.model_dump(mode="json") for binding in unit.corpus_source_bindings
                    ]
                }
            )
            and row.execution_mode == unit.execution_mode
            and row.submission_attempts == expected_attempts
            and row.lease_owner is None
            and row.lease_expires_at is None
        )

    def _resolve_member(
        self,
        session: Session,
        *,
        pointer: AssessmentArtifactMemberPointer,
        artifact_types: Collection[str],
        primary_file: str,
        max_bytes: int,
        manifest_artifact_types: Collection[str] | None = None,
    ) -> PinnedArtifactMember:
        return resolve_pinned_artifact_member(
            session,
            self.settings,
            artifact_id=pointer.artifact_id,
            artifact_revision_id=pointer.artifact_revision_id,
            member_path=pointer.member_path,
            sha256=pointer.sha256,
            schema_ref=pointer.schema_ref,
            media_type=pointer.media_type,
            expected_artifact_types=artifact_types,
            expected_primary_file=primary_file,
            max_bytes=max_bytes,
            expected_manifest_artifact_types=manifest_artifact_types,
        )

    @staticmethod
    def _preload_artifact_graph(session: Session, revision_ids: tuple[str, ...]) -> None:
        if not revision_ids:
            return
        revisions = tuple(
            session.scalars(
                select(ArtifactRevisionRecord).where(
                    ArtifactRevisionRecord.revision_id.in_(revision_ids)
                )
            )
        )
        artifact_ids = tuple(sorted({value.logical_artifact_id for value in revisions}))
        job_ids = tuple(sorted({value.job_id for value in revisions}))
        tuple(
            session.scalars(
                select(ArtifactRecord).where(ArtifactRecord.logical_artifact_id.in_(artifact_ids))
            )
        )
        tuple(session.scalars(select(JobRecord).where(JobRecord.job_id.in_(job_ids))))

    @staticmethod
    def _operator_authority(session: Session, actor_id: str) -> tuple[bool, bool]:
        operator = session.get(OperatorRecord, actor_id)
        if operator is None or operator.status != "ACTIVE":
            return False, False
        permission = session.scalar(
            select(PermissionRecord.permission_key)
            .join(
                RolePermissionRecord,
                RolePermissionRecord.permission_id == PermissionRecord.permission_id,
            )
            .join(
                OperatorRoleAssignmentRecord,
                OperatorRoleAssignmentRecord.role_id == RolePermissionRecord.role_id,
            )
            .where(
                OperatorRoleAssignmentRecord.operator_id == actor_id,
                OperatorRoleAssignmentRecord.revoked_at.is_(None),
                PermissionRecord.permission_key == PermissionKey.KNOWLEDGE_GRAPH_PUBLISH.value,
            )
            .limit(1)
        )
        return True, permission == PermissionKey.KNOWLEDGE_GRAPH_PUBLISH.value

    @classmethod
    def _typed_json(cls, payload: bytes, *, route: str, model: type[TModel]) -> TModel:
        try:
            decoded = payload.decode("utf-8")
            value = json.loads(decoded, object_pairs_hook=cls._unique_object)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("completion Artifact JSON is invalid") from exc
        return cls._typed_value(value, route=route, model=model)

    @staticmethod
    def _typed_value(value: object, *, route: str, model: type[TModel]) -> TModel:
        if not isinstance(value, dict):
            raise ValueError("completion Artifact JSON is not an object")
        validate_contract(route, value)
        return model.model_validate(value)

    @staticmethod
    def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, member in pairs:
            if key in value:
                raise ValueError("completion Artifact JSON contains duplicate keys")
            value[key] = member
        return value

    @staticmethod
    def _resolution(
        pointer: AssessmentArtifactMemberPointer,
        member: PinnedArtifactMember,
    ) -> ResolvedArtifactRevision:
        return ResolvedArtifactRevision(
            pointer=pointer,
            logical_artifact_type=member.artifact_type,
            manifest_artifact_type=member.manifest_artifact_type,
            approved=True,
            producing_job_state="SUCCEEDED",
        )

    @staticmethod
    def _fail(message: str) -> NoReturn:
        raise LegacyItemCorpusCompletionError(
            "LEGACY_ITEM_CORPUS_COMPLETION_SOURCE_INVALID",
            message,
        )


__all__ = ["PostgresLegacyItemCorpusCompletionSource"]
