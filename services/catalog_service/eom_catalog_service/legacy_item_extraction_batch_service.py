"""Durable FIFO coordination for reviewed legacy item extraction batches."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, NoReturn

from eom_catalog_contracts import (
    LegacyExtractionBatchWorkUnitV2,
    LegacyItemExtractionBatchManifestV2,
    LegacyItemExtractionResult,
    LegacySourceInventoryV2,
    LegacySourcePreliminaryClass,
    validate_contract,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_identity_service.models import OperatorRecord
from eom_orchestrator.database import build_session_factory, transaction
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifact, CatalogArtifactService
from eom_catalog_service.legacy_assessment_models import (
    AssessmentSourceBundleMemberRecord,
    LegacyItemExtractionAcceptanceRecord,
)
from eom_catalog_service.legacy_item_extraction_batch_models import (
    LegacyItemExtractionBatchEventRecord,
    LegacyItemExtractionBatchRecord,
    LegacyItemExtractionBatchWorkUnitRecord,
)
from eom_catalog_service.legacy_item_extraction_service import (
    CreateLegacyItemExtractionCommand,
    LegacyItemExtractionApplicationResult,
    LegacyItemExtractionApplicationService,
    LegacyItemExtractionServiceError,
)
from eom_catalog_service.settings import CatalogSettings

BATCH_MANIFEST_MEMBER = "legacy-item-extraction-batch.json"
BATCH_MANIFEST_SCHEMA_REF = "eom://schemas/legacy-assessment/legacy-item-extraction-batch/1.1"
BATCH_MANIFEST_MEDIA_TYPE = "application/json"
MAX_BATCH_MANIFEST_BYTES = 32 * 1024 * 1024
MAX_INVENTORY_BYTES = 32 * 1024 * 1024
DEFAULT_CLAIM_LEASE = timedelta(minutes=5)
SUBMITTED_POLL_INTERVAL = timedelta(seconds=5)
REVIEW_POLL_INTERVAL = timedelta(seconds=30)
ACTIVE_BATCH_STATES = frozenset({"QUEUED", "RUNNING"})
ACTIVE_WORK_UNIT_STATES = frozenset({"PENDING", "CLAIMED", "SUBMITTED"})
IN_FLIGHT_WORK_UNIT_STATES = frozenset({"CLAIMED", "SUBMITTED"})
# One fixed legacy-extraction slot means one durable submission boundary at a time.
LEGACY_EXTRACTION_BATCH_CLAIM_LOCK_ID = 4_609_259_983_361_590_172
WORK_UNIT_TRANSITIONS: dict[str, frozenset[str]] = {
    "PENDING": frozenset({"CLAIMED"}),
    "CLAIMED": frozenset({"PENDING", "SUBMITTED", "FAILED"}),
    "SUBMITTED": frozenset({"AWAITING_REVIEW", "ACCEPTED", "FAILED"}),
    "AWAITING_REVIEW": frozenset({"ACCEPTED", "FAILED"}),
    "ACCEPTED": frozenset(),
    "FAILED": frozenset(),
    "CANCELLED": frozenset(),
}
BATCH_TRANSITIONS: dict[str, frozenset[str]] = {
    "QUEUED": frozenset({"RUNNING"}),
    "RUNNING": frozenset({"AWAITING_REVIEW", "SUCCEEDED", "COMPLETED_WITH_GAPS"}),
    "AWAITING_REVIEW": frozenset({"SUCCEEDED", "COMPLETED_WITH_GAPS"}),
    "SUCCEEDED": frozenset(),
    "COMPLETED_WITH_GAPS": frozenset(),
    "CANCELLED": frozenset(),
}


class LegacyItemExtractionBatchServiceError(RuntimeError):
    """Stable, content-free error at the extraction batch boundary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CreateLegacyItemExtractionBatchCommand:
    manifest: LegacyItemExtractionBatchManifestV2
    requested_by: str

    def __post_init__(self) -> None:
        if not 1 <= len(self.requested_by) <= 128:
            raise ValueError("requested actor length is invalid")
        if any(ord(character) < 0x20 for character in self.requested_by):
            raise ValueError("requested actor contains a control character")


@dataclass(frozen=True)
class LegacyItemExtractionBatchView:
    extraction_batch_id: str
    manifest_sha256: str
    inventory_id: str
    inventory_sha256: str
    manifest_artifact_id: str
    manifest_artifact_revision_id: str
    state: str
    total_work_unit_count: int
    pending_count: int
    claimed_count: int
    submitted_count: int
    awaiting_review_count: int
    accepted_count: int
    failed_count: int
    cancelled_count: int
    created_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True)
class LegacyItemExtractionBatchWorkUnitView:
    work_unit_id: str
    extraction_batch_id: str
    ordinal: int
    extraction_request_id: str
    request_sha256: str
    assessment_source_bundle_revision_id: str
    execution_mode: str
    state: str
    submission_attempts: int
    workflow_id: str | None
    platform_job_id: str | None
    extraction_result_id: str | None
    result_sha256: str | None
    acceptance_id: str | None
    error_code: str | None
    lease_owner: str | None
    lease_expires_at: datetime | None


class LegacyItemExtractionBatchService:
    """Persist manifests and delegate each executable unit to the existing use case."""

    def __init__(
        self,
        engine: Engine,
        settings: CatalogSettings | None = None,
        *,
        artifacts: CatalogArtifactService | None = None,
        extraction: LegacyItemExtractionApplicationService | None = None,
    ) -> None:
        self.settings = settings or CatalogSettings.from_environment()
        self.sessions = build_session_factory(engine)
        self.artifacts = artifacts or CatalogArtifactService(engine, self.settings)
        self.extraction = extraction or LegacyItemExtractionApplicationService(engine)

    def create(
        self, command: CreateLegacyItemExtractionBatchCommand
    ) -> LegacyItemExtractionBatchView:
        """Validate the complete pointer graph and insert one immutable aggregate."""

        manifest = command.manifest
        try:
            validate_contract("legacy-item-extraction-batch-v2", manifest.model_dump(mode="json"))
        except (JsonSchemaValidationError, ValueError) as exc:
            raise LegacyItemExtractionBatchServiceError(
                "LEGACY_EXTRACTION_BATCH_REQUEST_INVALID",
                "legacy extraction batch manifest is invalid",
            ) from exc
        inventory = self._load_inventory(manifest)
        existing = self._find_by_idempotency(manifest.idempotency_key)
        if existing is not None:
            if (
                existing.extraction_batch_id != manifest.extraction_batch_id
                or existing.manifest_sha256 != manifest.manifest_sha256
                or existing.requested_by_operator_id != command.requested_by
            ):
                self._fail(
                    "LEGACY_EXTRACTION_BATCH_IDEMPOTENCY_CONFLICT",
                    "batch idempotency key has different input",
                )
            return self.inspect(existing.extraction_batch_id)

        # Artifact commit uses its own transaction. Reject an invalid actor or pointer graph
        # before crossing that durable boundary, then repeat the admission checks in the batch
        # transaction so a concurrent lifecycle change cannot be accepted.
        with self.sessions() as session:
            self._validate_admission(session, command, inventory)

        artifact = self._commit_manifest(manifest)
        try:
            with transaction(self.sessions) as session:
                replay = session.scalar(
                    select(LegacyItemExtractionBatchRecord)
                    .where(
                        LegacyItemExtractionBatchRecord.idempotency_key == manifest.idempotency_key
                    )
                    .with_for_update()
                )
                if replay is not None:
                    if (
                        replay.extraction_batch_id != manifest.extraction_batch_id
                        or replay.manifest_sha256 != manifest.manifest_sha256
                        or replay.requested_by_operator_id != command.requested_by
                    ):
                        self._fail(
                            "LEGACY_EXTRACTION_BATCH_IDEMPOTENCY_CONFLICT",
                            "batch idempotency key has different input",
                        )
                    return self._batch_view(session, replay)
                if (
                    session.get(
                        LegacyItemExtractionBatchRecord,
                        manifest.extraction_batch_id,
                    )
                    is not None
                ):
                    self._fail(
                        "LEGACY_EXTRACTION_BATCH_IDENTITY_CONFLICT",
                        "batch identity already exists",
                    )
                validated_reuse = self._validate_admission(session, command, inventory)
                now = manifest.created_at.astimezone(UTC)
                all_reused = len(validated_reuse) == len(manifest.work_units)
                batch = LegacyItemExtractionBatchRecord(
                    extraction_batch_id=manifest.extraction_batch_id,
                    schema_version=manifest.schema_version,
                    idempotency_key=manifest.idempotency_key,
                    manifest_sha256=manifest.manifest_sha256,
                    inventory_id=manifest.inventory_id,
                    inventory_sha256=manifest.inventory_sha256,
                    manifest_artifact_id=artifact.artifact_id,
                    manifest_artifact_revision_id=artifact.revision_id,
                    manifest_artifact_member_path=BATCH_MANIFEST_MEMBER,
                    manifest_artifact_schema_ref=BATCH_MANIFEST_SCHEMA_REF,
                    manifest_artifact_media_type=BATCH_MANIFEST_MEDIA_TYPE,
                    manifest_artifact_sha256=artifact.content_hash,
                    failure_policy=manifest.failure_policy,
                    state="SUCCEEDED" if all_reused else "QUEUED",
                    total_work_unit_count=len(manifest.work_units),
                    requested_by_operator_id=command.requested_by,
                    resource_version=1,
                    created_at=now,
                    started_at=now if all_reused else None,
                    completed_at=now if all_reused else None,
                )
                session.add(batch)
                session.flush()
                self._append_event(
                    session,
                    batch,
                    work_unit_id=None,
                    event_type="BATCH_CREATED",
                    prior_state=None,
                    new_state=batch.state,
                    payload={"manifest_sha256": manifest.manifest_sha256},
                )
                for unit in manifest.work_units:
                    acceptance = validated_reuse.get(unit.work_unit_id)
                    record = self._new_work_unit(unit, batch, acceptance, now)
                    session.add(record)
                    session.flush()
                    self._append_event(
                        session,
                        batch,
                        work_unit_id=record.work_unit_id,
                        event_type=(
                            "WORK_UNIT_REUSED" if acceptance is not None else "WORK_UNIT_QUEUED"
                        ),
                        prior_state=None,
                        new_state=record.state,
                        payload={
                            "request_sha256": record.request_sha256,
                            "corpus_source_bindings_sha256": (record.corpus_source_bindings_sha256),
                        },
                    )
                return self._batch_view(session, batch)
        except LegacyItemExtractionBatchServiceError:
            raise
        except IntegrityError as exc:
            raise LegacyItemExtractionBatchServiceError(
                "LEGACY_EXTRACTION_BATCH_CONCURRENCY_CONFLICT",
                "batch creation raced with another transaction",
            ) from exc

    def advance_once(self, *, runner_id: str) -> bool:
        """Submit one idle-capacity unit, otherwise advance one due reconciliation.

        A submitted unit blocks ``claim`` through the global in-flight invariant, so
        its reconciliation still takes precedence while work is running.  Trying a
        claim first when capacity is idle prevents a growing set of 30-second human
        review polls from permanently starving pending work.
        """

        claimed = self.claim(lease_owner=runner_id, observed_at=datetime.now(UTC))
        if claimed is not None:
            self.submit_claimed(
                claimed.work_unit_id,
                lease_owner=runner_id,
                observed_at=datetime.now(UTC),
            )
            return True
        reserved = self._reserve_reconciliation(datetime.now(UTC))
        if reserved is not None:
            self.reconcile_work_unit(reserved, observed_at=datetime.now(UTC))
            return True
        return False

    def inspect(self, extraction_batch_id: str) -> LegacyItemExtractionBatchView:
        with self.sessions() as session:
            batch = session.get(LegacyItemExtractionBatchRecord, extraction_batch_id)
            if batch is None:
                self._fail(
                    "LEGACY_EXTRACTION_BATCH_NOT_FOUND",
                    "legacy extraction batch does not exist",
                )
            return self._batch_view(session, batch)

    def work_units(
        self, extraction_batch_id: str
    ) -> tuple[LegacyItemExtractionBatchWorkUnitView, ...]:
        with self.sessions() as session:
            if session.get(LegacyItemExtractionBatchRecord, extraction_batch_id) is None:
                self._fail(
                    "LEGACY_EXTRACTION_BATCH_NOT_FOUND",
                    "legacy extraction batch does not exist",
                )
            records = session.scalars(
                select(LegacyItemExtractionBatchWorkUnitRecord)
                .where(
                    LegacyItemExtractionBatchWorkUnitRecord.extraction_batch_id
                    == extraction_batch_id
                )
                .order_by(LegacyItemExtractionBatchWorkUnitRecord.ordinal)
            )
            return tuple(self._work_unit_view(record) for record in records)

    def claim(
        self,
        *,
        lease_owner: str,
        observed_at: datetime,
        lease_duration: timedelta = DEFAULT_CLAIM_LEASE,
    ) -> LegacyItemExtractionBatchWorkUnitView | None:
        """Claim the oldest eligible unit with one indexed skip-locked query."""

        self._validate_lease(lease_owner, lease_duration)
        now = observed_at.astimezone(UTC)
        with transaction(self.sessions) as session:
            session.execute(
                select(func.pg_advisory_xact_lock(LEGACY_EXTRACTION_BATCH_CLAIM_LOCK_ID))
            )
            self._release_expired_claims(session, now)
            if self._in_flight_work_unit_id(session) is not None:
                return None
            record = session.scalar(
                select(LegacyItemExtractionBatchWorkUnitRecord)
                .join(
                    LegacyItemExtractionBatchRecord,
                    LegacyItemExtractionBatchRecord.extraction_batch_id
                    == LegacyItemExtractionBatchWorkUnitRecord.extraction_batch_id,
                )
                .where(
                    LegacyItemExtractionBatchWorkUnitRecord.state == "PENDING",
                    LegacyItemExtractionBatchWorkUnitRecord.next_action_at <= now,
                    LegacyItemExtractionBatchRecord.state.in_(ACTIVE_BATCH_STATES),
                )
                .order_by(
                    LegacyItemExtractionBatchRecord.created_at,
                    LegacyItemExtractionBatchRecord.extraction_batch_id,
                    LegacyItemExtractionBatchWorkUnitRecord.ordinal,
                )
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if record is None:
                return None
            batch = session.get(
                LegacyItemExtractionBatchRecord,
                record.extraction_batch_id,
                with_for_update=True,
            )
            if batch is None:
                self._fail(
                    "LEGACY_EXTRACTION_BATCH_RECORD_INVALID",
                    "work unit has no batch aggregate",
                )
            prior = record.state
            self._transition_work_unit(record, "CLAIMED")
            record.lease_owner = lease_owner
            record.lease_expires_at = now + lease_duration
            record.resource_version += 1
            if batch.state == "QUEUED":
                self._transition_batch(batch, "RUNNING")
                batch.started_at = now
                batch.resource_version += 1
            self._append_event(
                session,
                batch,
                work_unit_id=record.work_unit_id,
                event_type="WORK_UNIT_CLAIMED",
                prior_state=prior,
                new_state=record.state,
                payload={"lease_owner": lease_owner},
            )
            return self._work_unit_view(record)

    @staticmethod
    def _in_flight_work_unit_id(session: Session) -> str | None:
        """Return the active handoff that must settle before another claim."""

        return session.scalar(
            select(LegacyItemExtractionBatchWorkUnitRecord.work_unit_id)
            .join(
                LegacyItemExtractionBatchRecord,
                LegacyItemExtractionBatchRecord.extraction_batch_id
                == LegacyItemExtractionBatchWorkUnitRecord.extraction_batch_id,
            )
            .where(
                LegacyItemExtractionBatchWorkUnitRecord.state.in_(IN_FLIGHT_WORK_UNIT_STATES),
                LegacyItemExtractionBatchRecord.state.in_(ACTIVE_BATCH_STATES),
            )
            .order_by(
                LegacyItemExtractionBatchRecord.created_at,
                LegacyItemExtractionBatchRecord.extraction_batch_id,
                LegacyItemExtractionBatchWorkUnitRecord.ordinal,
            )
            .limit(1)
        )

    def submit_claimed(
        self,
        work_unit_id: str,
        *,
        lease_owner: str,
        observed_at: datetime,
    ) -> LegacyItemExtractionBatchWorkUnitView:
        """Delegate exactly once; a lost response reuses the workflow idempotency key."""

        with self.sessions() as session:
            record = session.get(LegacyItemExtractionBatchWorkUnitRecord, work_unit_id)
            if record is None:
                self._fail(
                    "LEGACY_EXTRACTION_BATCH_WORK_UNIT_NOT_FOUND",
                    "legacy extraction work unit does not exist",
                )
            if record.state == "SUBMITTED":
                return self._work_unit_view(record)
            if record.state != "CLAIMED" or record.lease_owner != lease_owner:
                self._fail(
                    "LEGACY_EXTRACTION_BATCH_LEASE_CONFLICT",
                    "work unit is not claimed by this lease owner",
                )
            batch_id = record.extraction_batch_id
            ordinal = record.ordinal
        manifest = self._load_manifest(batch_id)
        unit = manifest.work_units[ordinal]
        if unit.work_unit_id != work_unit_id:
            self._fail(
                "LEGACY_EXTRACTION_BATCH_MANIFEST_STALE",
                "work unit differs from its immutable manifest",
            )
        try:
            submitted = self.extraction.create(
                CreateLegacyItemExtractionCommand(
                    request=unit.request,
                    idempotency_key=f"legacy-batch:{batch_id}:{work_unit_id}",
                    requested_by=self._requested_by(batch_id),
                )
            )
        except LegacyItemExtractionServiceError as exc:
            self._mark_failed(work_unit_id, exc.code, observed_at.astimezone(UTC))
            raise LegacyItemExtractionBatchServiceError(exc.code, str(exc)) from exc
        now = observed_at.astimezone(UTC)
        with transaction(self.sessions) as session:
            record = session.get(
                LegacyItemExtractionBatchWorkUnitRecord,
                work_unit_id,
                with_for_update=True,
            )
            if record is None:
                self._fail(
                    "LEGACY_EXTRACTION_BATCH_WORK_UNIT_NOT_FOUND",
                    "legacy extraction work unit does not exist",
                )
            if record.state == "SUBMITTED":
                if record.workflow_id != submitted.workflow_id:
                    self._fail(
                        "LEGACY_EXTRACTION_BATCH_CONCURRENCY_CONFLICT",
                        "submitted work unit points to another workflow",
                    )
                return self._work_unit_view(record)
            if record.state != "CLAIMED" or record.lease_owner != lease_owner:
                self._fail(
                    "LEGACY_EXTRACTION_BATCH_LEASE_CONFLICT",
                    "work-unit lease changed during submission",
                )
            batch = session.get(
                LegacyItemExtractionBatchRecord,
                record.extraction_batch_id,
                with_for_update=True,
            )
            if batch is None:
                self._fail(
                    "LEGACY_EXTRACTION_BATCH_RECORD_INVALID",
                    "work unit has no batch aggregate",
                )
            prior = record.state
            self._transition_work_unit(record, "SUBMITTED")
            record.submission_attempts = 1
            record.workflow_id = submitted.workflow_id
            record.platform_job_id = submitted.platform_job_id
            record.lease_owner = None
            record.lease_expires_at = None
            record.submitted_at = now
            record.next_action_at = now
            record.resource_version += 1
            self._append_event(
                session,
                batch,
                work_unit_id=record.work_unit_id,
                event_type="WORK_UNIT_SUBMITTED",
                prior_state=prior,
                new_state=record.state,
                payload={"workflow_id": submitted.workflow_id},
            )
            self._refresh_batch_state(session, batch, now)
            return self._work_unit_view(record)

    def reconcile_work_unit(
        self, work_unit_id: str, *, observed_at: datetime
    ) -> LegacyItemExtractionBatchWorkUnitView:
        """Advance one unit solely from its exact workflow or acceptance evidence."""

        with self.sessions() as session:
            record = session.get(LegacyItemExtractionBatchWorkUnitRecord, work_unit_id)
            if record is None:
                self._fail(
                    "LEGACY_EXTRACTION_BATCH_WORK_UNIT_NOT_FOUND",
                    "legacy extraction work unit does not exist",
                )
            workflow_id = record.workflow_id
            current_state = record.state
        inspected: LegacyItemExtractionApplicationResult | None = None
        if current_state == "SUBMITTED" and workflow_id is not None:
            try:
                inspected = self.extraction.inspect(workflow_id)
            except LegacyItemExtractionServiceError as exc:
                raise LegacyItemExtractionBatchServiceError(exc.code, str(exc)) from exc
        now = observed_at.astimezone(UTC)
        with transaction(self.sessions) as session:
            record = session.get(
                LegacyItemExtractionBatchWorkUnitRecord,
                work_unit_id,
                with_for_update=True,
            )
            if record is None:
                self._fail(
                    "LEGACY_EXTRACTION_BATCH_WORK_UNIT_NOT_FOUND",
                    "legacy extraction work unit does not exist",
                )
            batch = session.get(
                LegacyItemExtractionBatchRecord,
                record.extraction_batch_id,
                with_for_update=True,
            )
            if batch is None:
                self._fail(
                    "LEGACY_EXTRACTION_BATCH_RECORD_INVALID",
                    "work unit has no batch aggregate",
                )
            prior = record.state
            prior_next_action = record.next_action_at
            event_type: str | None = None
            if record.state == "SUBMITTED" and inspected is not None:
                record.platform_job_id = inspected.platform_job_id
                if (
                    inspected.workflow_state == "COMPLETED"
                    and inspected.workflow_stage == "COMPLETED"
                    and inspected.job_status == "SUCCEEDED"
                    and inspected.receipt_artifact_id is not None
                    and inspected.receipt_artifact_revision_id is not None
                    and inspected.receipt_content_sha256 is not None
                    and inspected.extraction_result_id is not None
                    and inspected.result_sha256 is not None
                ):
                    record.receipt_artifact_id = inspected.receipt_artifact_id
                    record.receipt_artifact_revision_id = inspected.receipt_artifact_revision_id
                    record.receipt_artifact_sha256 = inspected.receipt_content_sha256
                    record.extraction_result_id = inspected.extraction_result_id
                    record.result_sha256 = inspected.result_sha256
                    acceptance = self._matching_acceptance(session, record)
                    if acceptance is None:
                        self._transition_work_unit(record, "AWAITING_REVIEW")
                        record.next_action_at = now + REVIEW_POLL_INTERVAL
                        event_type = "WORK_UNIT_AWAITING_REVIEW"
                    elif acceptance.state in {"ACCEPTED", "ACCEPTED_WITH_CORRECTIONS"}:
                        self._bind_acceptance(record, acceptance)
                        self._transition_work_unit(record, "ACCEPTED")
                        record.completed_at = now
                        event_type = "WORK_UNIT_ACCEPTED"
                    else:
                        self._bind_acceptance(record, acceptance)
                        self._transition_work_unit(record, "FAILED")
                        record.error_code = "LEGACY_ITEM_EXTRACTION_REJECTED"
                        record.completed_at = now
                        event_type = "WORK_UNIT_REJECTED"
                elif inspected.workflow_state in {"FAILED", "CANCELLED"}:
                    self._transition_work_unit(record, "FAILED")
                    record.error_code = "LEGACY_ITEM_EXTRACTION_WORKFLOW_FAILED"
                    record.completed_at = now
                    event_type = "WORK_UNIT_FAILED"
                else:
                    record.next_action_at = now + SUBMITTED_POLL_INTERVAL
            elif record.state == "AWAITING_REVIEW":
                acceptance = self._matching_acceptance(session, record)
                if acceptance is not None:
                    self._bind_acceptance(record, acceptance)
                    record.completed_at = now
                    if acceptance.state in {"ACCEPTED", "ACCEPTED_WITH_CORRECTIONS"}:
                        self._transition_work_unit(record, "ACCEPTED")
                        event_type = "WORK_UNIT_ACCEPTED"
                    else:
                        self._transition_work_unit(record, "FAILED")
                        record.error_code = "LEGACY_ITEM_EXTRACTION_REJECTED"
                        event_type = "WORK_UNIT_REJECTED"
                else:
                    record.next_action_at = now + REVIEW_POLL_INTERVAL
            if event_type is not None:
                record.resource_version += 1
                self._append_event(
                    session,
                    batch,
                    work_unit_id=record.work_unit_id,
                    event_type=event_type,
                    prior_state=prior,
                    new_state=record.state,
                    payload={
                        "workflow_id": record.workflow_id,
                        "extraction_result_id": record.extraction_result_id,
                        "acceptance_id": record.acceptance_id,
                    },
                )
            elif record.next_action_at != prior_next_action:
                record.resource_version += 1
            self._refresh_batch_state(session, batch, now)
            return self._work_unit_view(record)

    def reconcile_batch(
        self, extraction_batch_id: str, *, observed_at: datetime
    ) -> LegacyItemExtractionBatchView:
        unit_ids = tuple(
            unit.work_unit_id
            for unit in self.work_units(extraction_batch_id)
            if unit.state in {"SUBMITTED", "AWAITING_REVIEW"}
        )
        for work_unit_id in unit_ids:
            self.reconcile_work_unit(work_unit_id, observed_at=observed_at)
        return self.inspect(extraction_batch_id)

    def _reserve_reconciliation(self, now: datetime) -> str | None:
        """Lease one due poll by moving only its indexed next-action timestamp."""

        with transaction(self.sessions) as session:
            record = session.scalar(
                select(LegacyItemExtractionBatchWorkUnitRecord)
                .join(
                    LegacyItemExtractionBatchRecord,
                    LegacyItemExtractionBatchRecord.extraction_batch_id
                    == LegacyItemExtractionBatchWorkUnitRecord.extraction_batch_id,
                )
                .where(
                    LegacyItemExtractionBatchWorkUnitRecord.state.in_(
                        ("SUBMITTED", "AWAITING_REVIEW")
                    ),
                    LegacyItemExtractionBatchWorkUnitRecord.next_action_at <= now,
                    LegacyItemExtractionBatchRecord.state.in_(("RUNNING", "AWAITING_REVIEW")),
                )
                .order_by(
                    LegacyItemExtractionBatchWorkUnitRecord.next_action_at,
                    LegacyItemExtractionBatchRecord.created_at,
                    LegacyItemExtractionBatchRecord.extraction_batch_id,
                    LegacyItemExtractionBatchWorkUnitRecord.ordinal,
                )
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if record is None:
                return None
            interval = (
                SUBMITTED_POLL_INTERVAL if record.state == "SUBMITTED" else REVIEW_POLL_INTERVAL
            )
            record.next_action_at = now + interval
            record.resource_version += 1
            return record.work_unit_id

    def _load_inventory(
        self, manifest: LegacyItemExtractionBatchManifestV2
    ) -> LegacySourceInventoryV2:
        pointer = manifest.inventory_artifact
        try:
            raw = self.artifacts.read_member(
                artifact_id=pointer.artifact_id,
                revision_id=pointer.artifact_revision_id,
                member_path=pointer.member_path,
                sha256=pointer.sha256,
                media_type=pointer.media_type,
                schema_ref=pointer.schema_ref,
                max_bytes=MAX_INVENTORY_BYTES,
            )
            value = json.loads(raw, object_pairs_hook=self._unique_object)
            if not isinstance(value, dict):
                raise ValueError("inventory is not an object")
            validate_contract("legacy-source-inventory-v2", value)
            inventory = LegacySourceInventoryV2.model_validate(value)
        except (
            UnicodeError,
            json.JSONDecodeError,
            JsonSchemaValidationError,
            PydanticValidationError,
            ValueError,
        ) as exc:
            raise LegacyItemExtractionBatchServiceError(
                "LEGACY_EXTRACTION_BATCH_INVENTORY_INVALID",
                "batch inventory pointer does not resolve",
            ) from exc
        if (
            inventory.inventory_id != manifest.inventory_id
            or inventory.inventory_sha256 != manifest.inventory_sha256
        ):
            self._fail(
                "LEGACY_EXTRACTION_BATCH_INVENTORY_STALE",
                "batch inventory identity differs from its manifest",
            )
        return inventory

    def _load_manifest(self, extraction_batch_id: str) -> LegacyItemExtractionBatchManifestV2:
        with self.sessions() as session:
            batch = session.get(LegacyItemExtractionBatchRecord, extraction_batch_id)
            if batch is None:
                self._fail(
                    "LEGACY_EXTRACTION_BATCH_NOT_FOUND",
                    "legacy extraction batch does not exist",
                )
            pointer = {
                "artifact_id": batch.manifest_artifact_id,
                "revision_id": batch.manifest_artifact_revision_id,
                "member_path": batch.manifest_artifact_member_path,
                "sha256": batch.manifest_artifact_sha256,
                "media_type": batch.manifest_artifact_media_type,
                "schema_ref": batch.manifest_artifact_schema_ref,
                "manifest_sha256": batch.manifest_sha256,
            }
        try:
            raw = self.artifacts.read_member(
                artifact_id=pointer["artifact_id"],
                revision_id=pointer["revision_id"],
                member_path=pointer["member_path"],
                sha256=pointer["sha256"],
                media_type=pointer["media_type"],
                schema_ref=pointer["schema_ref"],
                max_bytes=MAX_BATCH_MANIFEST_BYTES,
            )
            value = json.loads(raw, object_pairs_hook=self._unique_object)
            if not isinstance(value, dict):
                raise ValueError("manifest is not an object")
            validate_contract("legacy-item-extraction-batch-v2", value)
            manifest = LegacyItemExtractionBatchManifestV2.model_validate(value)
        except (
            UnicodeError,
            json.JSONDecodeError,
            JsonSchemaValidationError,
            PydanticValidationError,
            ValueError,
        ) as exc:
            raise LegacyItemExtractionBatchServiceError(
                "LEGACY_EXTRACTION_BATCH_MANIFEST_STALE",
                "batch manifest Artifact does not resolve",
            ) from exc
        if manifest.manifest_sha256 != pointer["manifest_sha256"]:
            self._fail(
                "LEGACY_EXTRACTION_BATCH_MANIFEST_STALE",
                "batch manifest identity differs from its record",
            )
        return manifest

    def _commit_manifest(self, manifest: LegacyItemExtractionBatchManifestV2) -> CatalogArtifact:
        raw = canonical_json_bytes(manifest.model_dump(mode="json"))
        if len(raw) > MAX_BATCH_MANIFEST_BYTES:
            self._fail(
                "LEGACY_EXTRACTION_BATCH_REQUEST_INVALID",
                "legacy extraction batch manifest exceeds the byte limit",
            )
        self.settings.staging_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="legacy-item-extraction-batch-",
            dir=self.settings.staging_root,
        ) as directory:
            path = Path(directory) / BATCH_MANIFEST_MEMBER
            path.write_bytes(raw)
            return self.artifacts.commit_file_set(
                files={BATCH_MANIFEST_MEMBER: path},
                primary_file=BATCH_MANIFEST_MEMBER,
                artifact_type="legacy-item-extraction-batch",
                idempotency_key=(f"legacy-item-extraction-batch:{manifest.manifest_sha256}"),
                request={
                    "schema_version": "legacy-item-extraction-batch-commit-request/1.0",
                    "extraction_batch_id": manifest.extraction_batch_id,
                    "manifest_sha256": manifest.manifest_sha256,
                },
                result={
                    "schema_version": "legacy-item-extraction-batch-commit-result/1.0",
                    "extraction_batch_id": manifest.extraction_batch_id,
                    "manifest_sha256": manifest.manifest_sha256,
                },
                file_metadata={
                    BATCH_MANIFEST_MEMBER: {
                        "media_type": BATCH_MANIFEST_MEDIA_TYPE,
                        "schema_ref": BATCH_MANIFEST_SCHEMA_REF,
                    }
                },
                manifest_version="legacy-item-extraction-batch-artifact/1.0",
                expected_file_sha256={BATCH_MANIFEST_MEMBER: sha256_bytes(raw)},
            )

    def _validate_admission(
        self,
        session: Session,
        command: CreateLegacyItemExtractionBatchCommand,
        inventory: LegacySourceInventoryV2,
    ) -> dict[str, LegacyItemExtractionAcceptanceRecord]:
        actor = session.get(OperatorRecord, command.requested_by)
        if actor is None or actor.status != "ACTIVE":
            self._fail(
                "LEGACY_EXTRACTION_BATCH_OPERATOR_INVALID",
                "batch requires an active operator",
            )
        accepted: dict[str, LegacyItemExtractionAcceptanceRecord] = {}
        for unit in command.manifest.work_units:
            self.extraction.validate_reviewed_request(session, unit.request)
            self._validate_corpus_bindings(session, command.manifest, unit, inventory)
            if unit.execution_mode == "REUSE_ACCEPTED":
                accepted[unit.work_unit_id] = self._validate_reuse(session, unit)
        return accepted

    def _validate_corpus_bindings(
        self,
        session: Session,
        manifest: LegacyItemExtractionBatchManifestV2,
        unit: LegacyExtractionBatchWorkUnitV2,
        inventory: LegacySourceInventoryV2,
    ) -> None:
        members = tuple(
            session.scalars(
                select(AssessmentSourceBundleMemberRecord)
                .where(
                    AssessmentSourceBundleMemberRecord.assessment_source_bundle_revision_id
                    == unit.request.bundle.assessment_source_bundle_revision_id
                )
                .order_by(AssessmentSourceBundleMemberRecord.ordinal)
            )
        )
        member_index = {member.assessment_source_bundle_member_id: member for member in members}
        binding_index = {
            binding.bundle_member_id: binding for binding in unit.corpus_source_bindings
        }
        inventory_index = {entry.entry_key: entry for entry in inventory.entries}
        if set(member_index) != set(binding_index):
            self._fail(
                "LEGACY_EXTRACTION_BATCH_CORPUS_BINDING_INVALID",
                "corpus bindings do not exactly cover the reviewed bundle",
            )
        for member_id, member in member_index.items():
            binding = binding_index[member_id]
            reviewed = binding.reviewed_inventory_source
            corpus = binding.corpus_inventory_source
            entry = inventory_index.get(corpus.entry_key)
            if (
                reviewed.inventory_id != member.inventory_id
                or reviewed.inventory_sha256 != member.inventory_sha256
                or reviewed.entry_key != member.inventory_entry_key
                or reviewed.content_sha256 != member.inventory_content_sha256
                or corpus.inventory_id != manifest.inventory_id
                or corpus.inventory_sha256 != manifest.inventory_sha256
                or entry is None
                or entry.content_sha256 != corpus.content_sha256
                or entry.preliminary_class != LegacySourcePreliminaryClass.ORIGINAL_SOURCE_CANDIDATE
                or member.source_sha256 != corpus.content_sha256
            ):
                self._fail(
                    "LEGACY_EXTRACTION_BATCH_CORPUS_BINDING_STALE",
                    "corpus source binding differs from immutable source evidence",
                )

    def _validate_reuse(
        self,
        session: Session,
        unit: LegacyExtractionBatchWorkUnitV2,
    ) -> LegacyItemExtractionAcceptanceRecord:
        pointer = unit.reuse_accepted
        if pointer is None:
            self._fail(
                "LEGACY_EXTRACTION_BATCH_ACCEPTANCE_INVALID",
                "reuse work unit has no acceptance pointer",
            )
        record = session.get(LegacyItemExtractionAcceptanceRecord, pointer.acceptance_id)
        result_pointer = pointer.extraction_result
        if (
            record is None
            or record.state not in {"ACCEPTED", "ACCEPTED_WITH_CORRECTIONS"}
            or record.coverage_state != "COMPLETE"
            or record.acceptance_sha256 != pointer.acceptance_sha256
            or record.extraction_result_id != result_pointer.extraction_result_id
            or record.result_artifact_id != result_pointer.artifact.artifact_id
            or record.result_artifact_revision_id != result_pointer.artifact.artifact_revision_id
            or record.result_artifact_member_path != result_pointer.artifact.member_path
            or record.result_artifact_schema_ref != result_pointer.artifact.schema_ref
            or record.result_artifact_media_type != result_pointer.artifact.media_type
            or record.result_artifact_sha256 != result_pointer.artifact.sha256
            or record.result_sha256 != result_pointer.result_sha256
        ):
            self._fail(
                "LEGACY_EXTRACTION_BATCH_ACCEPTANCE_STALE",
                "accepted extraction pointer does not resolve",
            )
        try:
            raw = self.artifacts.read_member(
                artifact_id=result_pointer.artifact.artifact_id,
                revision_id=result_pointer.artifact.artifact_revision_id,
                member_path=result_pointer.artifact.member_path,
                sha256=result_pointer.artifact.sha256,
                media_type=result_pointer.artifact.media_type,
                schema_ref=result_pointer.artifact.schema_ref,
                max_bytes=MAX_BATCH_MANIFEST_BYTES,
            )
            value = json.loads(raw, object_pairs_hook=self._unique_object)
            if not isinstance(value, dict):
                raise ValueError("result is not an object")
            validate_contract("legacy-item-extraction-result", value)
            result = LegacyItemExtractionResult.model_validate(value)
        except (
            UnicodeError,
            json.JSONDecodeError,
            JsonSchemaValidationError,
            PydanticValidationError,
            ValueError,
        ) as exc:
            raise LegacyItemExtractionBatchServiceError(
                "LEGACY_EXTRACTION_BATCH_ACCEPTANCE_STALE",
                "accepted extraction result does not resolve",
            ) from exc
        if (
            result.extraction_request_id != unit.request.extraction_request_id
            or result.request_sha256 != unit.request.request_sha256
            or result.extraction_result_id != result_pointer.extraction_result_id
            or result.result_sha256 != result_pointer.result_sha256
            or tuple(item.item_number for item in result.items)
            != unit.request.expected_item_numbers
        ):
            self._fail(
                "LEGACY_EXTRACTION_BATCH_ACCEPTANCE_STALE",
                "accepted extraction result differs from the work-unit request",
            )
        return record

    @staticmethod
    def _new_work_unit(
        unit: LegacyExtractionBatchWorkUnitV2,
        batch: LegacyItemExtractionBatchRecord,
        acceptance: LegacyItemExtractionAcceptanceRecord | None,
        now: datetime,
    ) -> LegacyItemExtractionBatchWorkUnitRecord:
        reused = acceptance is not None
        result_pointer = unit.reuse_accepted.extraction_result if unit.reuse_accepted else None
        return LegacyItemExtractionBatchWorkUnitRecord(
            work_unit_id=unit.work_unit_id,
            extraction_batch_id=batch.extraction_batch_id,
            ordinal=unit.ordinal,
            extraction_request_id=unit.request.extraction_request_id,
            request_sha256=unit.request.request_sha256,
            assessment_source_bundle_id=(unit.request.bundle.assessment_source_bundle_id),
            assessment_source_bundle_revision_id=(
                unit.request.bundle.assessment_source_bundle_revision_id
            ),
            bundle_manifest_sha256=unit.request.bundle.bundle_manifest_sha256,
            expected_item_numbers_sha256=unit.expected_item_numbers_sha256,
            corpus_source_bindings_sha256=content_sha256(
                {
                    "corpus_source_bindings": [
                        binding.model_dump(mode="json") for binding in unit.corpus_source_bindings
                    ]
                }
            ),
            execution_mode=unit.execution_mode,
            state="ACCEPTED" if reused else "PENDING",
            submission_attempts=0,
            lease_owner=None,
            lease_expires_at=None,
            next_action_at=now,
            workflow_id=None,
            platform_job_id=None,
            receipt_artifact_id=(
                result_pointer.artifact.artifact_id if result_pointer is not None else None
            ),
            receipt_artifact_revision_id=(
                result_pointer.artifact.artifact_revision_id if result_pointer is not None else None
            ),
            receipt_artifact_sha256=(
                result_pointer.artifact.sha256 if result_pointer is not None else None
            ),
            extraction_result_id=(
                result_pointer.extraction_result_id if result_pointer is not None else None
            ),
            result_sha256=result_pointer.result_sha256 if result_pointer is not None else None,
            acceptance_id=acceptance.acceptance_id if acceptance is not None else None,
            acceptance_sha256=(acceptance.acceptance_sha256 if acceptance is not None else None),
            error_code=None,
            resource_version=1,
            created_at=now,
            submitted_at=None,
            completed_at=now if reused else None,
        )

    def _release_expired_claims(self, session: Session, now: datetime) -> None:
        expired = tuple(
            session.scalars(
                select(LegacyItemExtractionBatchWorkUnitRecord)
                .where(
                    LegacyItemExtractionBatchWorkUnitRecord.state == "CLAIMED",
                    LegacyItemExtractionBatchWorkUnitRecord.lease_expires_at <= now,
                )
                .order_by(
                    LegacyItemExtractionBatchWorkUnitRecord.extraction_batch_id,
                    LegacyItemExtractionBatchWorkUnitRecord.ordinal,
                )
                .with_for_update(skip_locked=True)
            )
        )
        for record in expired:
            batch = session.get(
                LegacyItemExtractionBatchRecord,
                record.extraction_batch_id,
                with_for_update=True,
            )
            if batch is None:
                self._fail(
                    "LEGACY_EXTRACTION_BATCH_RECORD_INVALID",
                    "expired work unit has no batch aggregate",
                )
            self._transition_work_unit(record, "PENDING")
            record.lease_owner = None
            record.lease_expires_at = None
            record.next_action_at = now
            record.resource_version += 1
            self._append_event(
                session,
                batch,
                work_unit_id=record.work_unit_id,
                event_type="WORK_UNIT_CLAIM_EXPIRED",
                prior_state="CLAIMED",
                new_state="PENDING",
                payload={},
            )

    def _mark_failed(self, work_unit_id: str, error_code: str, now: datetime) -> None:
        with transaction(self.sessions) as session:
            record = session.get(
                LegacyItemExtractionBatchWorkUnitRecord,
                work_unit_id,
                with_for_update=True,
            )
            if record is None or record.state != "CLAIMED":
                return
            batch = session.get(
                LegacyItemExtractionBatchRecord,
                record.extraction_batch_id,
                with_for_update=True,
            )
            if batch is None:
                return
            self._transition_work_unit(record, "FAILED")
            record.error_code = error_code
            record.lease_owner = None
            record.lease_expires_at = None
            record.completed_at = now
            record.resource_version += 1
            self._append_event(
                session,
                batch,
                work_unit_id=record.work_unit_id,
                event_type="WORK_UNIT_FAILED",
                prior_state="CLAIMED",
                new_state="FAILED",
                payload={"error_code": error_code},
            )
            self._refresh_batch_state(session, batch, now)

    @staticmethod
    def _matching_acceptance(
        session: Session,
        record: LegacyItemExtractionBatchWorkUnitRecord,
    ) -> LegacyItemExtractionAcceptanceRecord | None:
        if record.extraction_result_id is None:
            return None
        return session.scalar(
            select(LegacyItemExtractionAcceptanceRecord)
            .where(
                LegacyItemExtractionAcceptanceRecord.extraction_result_id
                == record.extraction_result_id,
                LegacyItemExtractionAcceptanceRecord.result_artifact_id
                == record.receipt_artifact_id,
                LegacyItemExtractionAcceptanceRecord.result_artifact_revision_id
                == record.receipt_artifact_revision_id,
                LegacyItemExtractionAcceptanceRecord.result_artifact_sha256
                == record.receipt_artifact_sha256,
                LegacyItemExtractionAcceptanceRecord.result_sha256 == record.result_sha256,
                LegacyItemExtractionAcceptanceRecord.coverage_state == "COMPLETE",
            )
            .order_by(
                LegacyItemExtractionAcceptanceRecord.reviewed_at,
                LegacyItemExtractionAcceptanceRecord.acceptance_id,
            )
            .limit(1)
        )

    @staticmethod
    def _bind_acceptance(
        record: LegacyItemExtractionBatchWorkUnitRecord,
        acceptance: LegacyItemExtractionAcceptanceRecord,
    ) -> None:
        record.acceptance_id = acceptance.acceptance_id
        record.acceptance_sha256 = acceptance.acceptance_sha256

    def _refresh_batch_state(
        self, session: Session, batch: LegacyItemExtractionBatchRecord, now: datetime
    ) -> None:
        counts = self._state_counts(session, batch.extraction_batch_id)
        prior = batch.state
        active = sum(counts.get(state, 0) for state in ACTIVE_WORK_UNIT_STATES)
        if counts.get("ACCEPTED", 0) == batch.total_work_unit_count:
            target = "SUCCEEDED"
        elif active > 0:
            target = "RUNNING" if batch.started_at is not None else "QUEUED"
        elif counts.get("AWAITING_REVIEW", 0) > 0:
            target = "AWAITING_REVIEW"
        else:
            target = "COMPLETED_WITH_GAPS"
        if target == prior:
            return
        self._transition_batch(batch, target)
        batch.resource_version += 1
        if target == "RUNNING" and batch.started_at is None:
            batch.started_at = now
        if target in {"SUCCEEDED", "COMPLETED_WITH_GAPS"}:
            batch.completed_at = now
        self._append_event(
            session,
            batch,
            work_unit_id=None,
            event_type="BATCH_STATE_CHANGED",
            prior_state=prior,
            new_state=target,
            payload={"state_counts": counts},
        )

    def _batch_view(
        self, session: Session, batch: LegacyItemExtractionBatchRecord
    ) -> LegacyItemExtractionBatchView:
        counts = self._state_counts(session, batch.extraction_batch_id)
        return LegacyItemExtractionBatchView(
            extraction_batch_id=batch.extraction_batch_id,
            manifest_sha256=batch.manifest_sha256,
            inventory_id=batch.inventory_id,
            inventory_sha256=batch.inventory_sha256,
            manifest_artifact_id=batch.manifest_artifact_id,
            manifest_artifact_revision_id=batch.manifest_artifact_revision_id,
            state=batch.state,
            total_work_unit_count=batch.total_work_unit_count,
            pending_count=counts.get("PENDING", 0),
            claimed_count=counts.get("CLAIMED", 0),
            submitted_count=counts.get("SUBMITTED", 0),
            awaiting_review_count=counts.get("AWAITING_REVIEW", 0),
            accepted_count=counts.get("ACCEPTED", 0),
            failed_count=counts.get("FAILED", 0),
            cancelled_count=counts.get("CANCELLED", 0),
            created_at=batch.created_at,
            completed_at=batch.completed_at,
        )

    @staticmethod
    def _work_unit_view(
        record: LegacyItemExtractionBatchWorkUnitRecord,
    ) -> LegacyItemExtractionBatchWorkUnitView:
        return LegacyItemExtractionBatchWorkUnitView(
            work_unit_id=record.work_unit_id,
            extraction_batch_id=record.extraction_batch_id,
            ordinal=record.ordinal,
            extraction_request_id=record.extraction_request_id,
            request_sha256=record.request_sha256,
            assessment_source_bundle_revision_id=(record.assessment_source_bundle_revision_id),
            execution_mode=record.execution_mode,
            state=record.state,
            submission_attempts=record.submission_attempts,
            workflow_id=record.workflow_id,
            platform_job_id=record.platform_job_id,
            extraction_result_id=record.extraction_result_id,
            result_sha256=record.result_sha256,
            acceptance_id=record.acceptance_id,
            error_code=record.error_code,
            lease_owner=record.lease_owner,
            lease_expires_at=record.lease_expires_at,
        )

    @staticmethod
    def _state_counts(session: Session, extraction_batch_id: str) -> dict[str, int]:
        return {
            state: count
            for state, count in session.execute(
                select(
                    LegacyItemExtractionBatchWorkUnitRecord.state,
                    func.count(),
                )
                .where(
                    LegacyItemExtractionBatchWorkUnitRecord.extraction_batch_id
                    == extraction_batch_id
                )
                .group_by(LegacyItemExtractionBatchWorkUnitRecord.state)
            )
        }

    def _find_by_idempotency(self, idempotency_key: str) -> LegacyItemExtractionBatchRecord | None:
        with self.sessions() as session:
            return session.scalar(
                select(LegacyItemExtractionBatchRecord).where(
                    LegacyItemExtractionBatchRecord.idempotency_key == idempotency_key
                )
            )

    def _requested_by(self, extraction_batch_id: str) -> str:
        with self.sessions() as session:
            batch = session.get(LegacyItemExtractionBatchRecord, extraction_batch_id)
            if batch is None:
                self._fail(
                    "LEGACY_EXTRACTION_BATCH_NOT_FOUND",
                    "legacy extraction batch does not exist",
                )
            return batch.requested_by_operator_id

    @staticmethod
    def _validate_lease(lease_owner: str, duration: timedelta) -> None:
        if (
            not 1 <= len(lease_owner) <= 128
            or any(ord(character) < 0x20 for character in lease_owner)
            or not timedelta(seconds=1) <= duration <= timedelta(minutes=30)
        ):
            raise LegacyItemExtractionBatchServiceError(
                "LEGACY_EXTRACTION_BATCH_LEASE_INVALID",
                "batch claim lease is invalid",
            )

    @staticmethod
    def _append_event(
        session: Session,
        batch: LegacyItemExtractionBatchRecord,
        *,
        work_unit_id: str | None,
        event_type: str,
        prior_state: str | None,
        new_state: str,
        payload: dict[str, Any],
    ) -> None:
        sequence = (
            session.scalar(
                select(func.max(LegacyItemExtractionBatchEventRecord.sequence)).where(
                    LegacyItemExtractionBatchEventRecord.extraction_batch_id
                    == batch.extraction_batch_id
                )
            )
            or 0
        ) + 1
        session.add(
            LegacyItemExtractionBatchEventRecord(
                extraction_batch_id=batch.extraction_batch_id,
                work_unit_id=work_unit_id,
                sequence=sequence,
                event_type=event_type,
                prior_state=prior_state,
                new_state=new_state,
                payload=payload,
            )
        )

    @staticmethod
    def _transition_work_unit(
        record: LegacyItemExtractionBatchWorkUnitRecord,
        target: str,
    ) -> None:
        if target not in WORK_UNIT_TRANSITIONS.get(record.state, frozenset()):
            LegacyItemExtractionBatchService._fail(
                "LEGACY_EXTRACTION_BATCH_TRANSITION_INVALID",
                "legacy extraction work-unit transition is invalid",
            )
        record.state = target

    @staticmethod
    def _transition_batch(record: LegacyItemExtractionBatchRecord, target: str) -> None:
        if target not in BATCH_TRANSITIONS.get(record.state, frozenset()):
            LegacyItemExtractionBatchService._fail(
                "LEGACY_EXTRACTION_BATCH_TRANSITION_INVALID",
                "legacy extraction batch transition is invalid",
            )
        record.state = target

    @staticmethod
    def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON object key")
            value[key] = item
        return value

    @staticmethod
    def _fail(code: str, message: str) -> NoReturn:
        raise LegacyItemExtractionBatchServiceError(code, message)
