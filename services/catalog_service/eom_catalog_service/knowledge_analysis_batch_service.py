"""Durable FIFO coordination for fresh-authorized Knowledge Analysis batches."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from eom_catalog_contracts import (
    CreateKnowledgeAnalysisBatchCommand,
    CreateKnowledgeAnalysisCommand,
    EducationalDocumentKnowledgeAnalysisSelection,
    EducationalDocumentKnowledgeSourceV3,
    EducationalDocumentKnowledgeSourceV4,
    KnowledgeAnalysisBatchApplicationResult,
    KnowledgeAnalysisBatchRequestV3,
    KnowledgeAnalysisBatchRequestV4,
    KnowledgeAnalysisRequestV3,
    KnowledgeAnalysisRequestV4,
    KnowledgeAnalysisRequestV5,
    KnowledgeAnalysisRequestV6,
    KnowledgeAnalysisRequestV7,
    KnowledgeAnalysisRequestV8,
    KnowledgeAnalysisResultV3,
    KnowledgeAnalysisResultV4,
    KnowledgeAnalysisResultV5,
    KnowledgeAnalysisResultV6,
    KnowledgeAnalysisResultV7,
    KnowledgeAnalysisResultV8,
    ReconcileKnowledgeAnalysisCommand,
    ReuseAcceptedKnowledgeAnalysisRange,
    ReviewKnowledgeAnalysisCommand,
    validate_contract,
)
from eom_identifiers import (
    content_sha256,
    new_knowledge_analysis_batch_id,
    new_knowledge_analysis_range_id,
)
from eom_orchestrator.control_models import (
    ExecutionBundleRevisionRecord,
    ExecutionPresetRevisionRecord,
    WorkerCapacityPolicyRevisionRecord,
)
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord
from eom_workflow import WorkerCapacityPolicyV2
from sqlalchemy import Engine, exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.knowledge_analysis_batch_models import (
    KnowledgeAnalysisBatchEventRecord,
    KnowledgeAnalysisBatchRangeRecord,
    KnowledgeAnalysisBatchRecord,
)
from eom_catalog_service.knowledge_analysis_service import (
    KnowledgeAnalysisApplicationService,
    KnowledgeAnalysisServiceError,
)
from eom_catalog_service.knowledge_analysis_sources import (
    EducationalDocumentSourceResolutionCache,
    KnowledgeAnalysisSourceError,
    resolve_educational_document_source,
)
from eom_catalog_service.settings import CatalogSettings

BATCH_POLL_INTERVAL = timedelta(seconds=2)
BATCH_ACTION_LEASE = timedelta(seconds=30)
TERMINAL_ANALYSIS_STATES = frozenset({"ACCEPTED", "REJECTED", "FAILED", "CANCELLED"})
STOP_ON_FIRST_FAILURE = "STOP_ON_FIRST_FAILURE"
CONTINUE_AND_COLLECT = "CONTINUE_AND_COLLECT"
COLLECTED_FAILURE_CODE = "KNOWLEDGE_ANALYSIS_BATCH_RANGE_FAILURES_COLLECTED"


class KnowledgeAnalysisBatchServiceError(RuntimeError):
    """Stable, bounded error at the Knowledge Analysis batch boundary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class KnowledgeAnalysisBatchService:
    """Own batch persistence and delegate every range to the existing analysis use case."""

    def __init__(
        self,
        engine: Engine,
        settings: CatalogSettings | None = None,
        *,
        analysis: KnowledgeAnalysisApplicationService | None = None,
    ) -> None:
        self.settings = settings or CatalogSettings.from_environment()
        self.sessions = build_session_factory(engine)
        self.artifacts = CatalogArtifactService(engine, self.settings)
        self.analysis = analysis or KnowledgeAnalysisApplicationService(engine, self.settings)

    def create(
        self, command: CreateKnowledgeAnalysisBatchCommand
    ) -> KnowledgeAnalysisBatchApplicationResult:
        """Validate all immutable dependencies and insert one complete aggregate."""

        request_schema = {
            "knowledge-analysis-batch-request/1.0": "knowledge-analysis-batch-request",
            "knowledge-analysis-batch-request/1.1": "knowledge-analysis-batch-request-v2",
            "knowledge-analysis-batch-request/1.2": "knowledge-analysis-batch-request-v3",
            "knowledge-analysis-batch-request/1.3": "knowledge-analysis-batch-request-v4",
        }[command.request.schema_version]
        validate_contract(request_schema, command.request.model_dump(mode="json"))
        try:
            with transaction(self.sessions) as session:
                existing = session.scalar(
                    select(KnowledgeAnalysisBatchRecord)
                    .where(KnowledgeAnalysisBatchRecord.idempotency_key == command.idempotency_key)
                    .with_for_update()
                )
                if existing is not None:
                    if existing.request_sha256 != command.submission_sha256:
                        raise KnowledgeAnalysisBatchServiceError(
                            "KNOWLEDGE_ANALYSIS_BATCH_IDEMPOTENCY_CONFLICT",
                            "Knowledge Analysis batch idempotency key has different input",
                        )
                    return self._projection(session, existing)

                preset, preset_revision = self.analysis.published_preset(
                    session, command.request.preset_key
                )
                if isinstance(command.request, KnowledgeAnalysisBatchRequestV4):
                    capacity = session.get(
                        WorkerCapacityPolicyRevisionRecord,
                        preset_revision.capacity_policy_revision_id,
                    )
                    try:
                        reviewed_capacity = (
                            WorkerCapacityPolicyV2.model_validate(capacity.canonical_document)
                            if capacity is not None and capacity.state == "RELEASED"
                            else None
                        )
                    except ValueError:
                        reviewed_capacity = None
                    if (
                        capacity is None
                        or reviewed_capacity is None
                        or capacity.schema_version != reviewed_capacity.schema_version
                        or capacity.content_sha256 != reviewed_capacity.content_sha256
                        or capacity.max_active_knowledge_analysis
                        != reviewed_capacity.max_active_knowledge_analysis
                    ):
                        raise KnowledgeAnalysisBatchServiceError(
                            "KNOWLEDGE_ANALYSIS_BATCH_CAPACITY_INVALID",
                            "Bounded-parallel batch requires released capacity policy V2",
                        )
                policy = self.analysis.risk_policy(session, command.request.risk_policy_revision_id)
                batch = KnowledgeAnalysisBatchRecord(
                    batch_id=new_knowledge_analysis_batch_id(),
                    request_sha256=command.submission_sha256,
                    idempotency_key=command.idempotency_key,
                    preset_id=preset.preset_id,
                    preset_revision_id=preset_revision.preset_revision_id,
                    preset_sha256=preset_revision.content_sha256,
                    risk_policy_revision_id=policy.risk_policy_revision_id,
                    risk_policy_sha256=policy.content_sha256,
                    general_knowledge_mode=command.request.general_knowledge_mode,
                    review_policy=command.request.review_policy,
                    range_failure_policy=(
                        command.request.range_failure_policy
                        if isinstance(
                            command.request,
                            (KnowledgeAnalysisBatchRequestV3, KnowledgeAnalysisBatchRequestV4),
                        )
                        else STOP_ON_FIRST_FAILURE
                    ),
                    scheduling_mode=(
                        command.request.scheduling_mode
                        if isinstance(command.request, KnowledgeAnalysisBatchRequestV4)
                        else "SERIAL"
                    ),
                    max_in_flight=(
                        command.request.max_in_flight
                        if isinstance(command.request, KnowledgeAnalysisBatchRequestV4)
                        else 1
                    ),
                    authorized_by_operator_id=command.requested_by,
                    authorized_at=command.authorized_at,
                    state="QUEUED",
                    total_range_count=len(command.request.ranges),
                    failure_code=None,
                    resource_version=1,
                )
                session.add(batch)
                session.flush()
                accepted_count = 0
                source_cache = EducationalDocumentSourceResolutionCache()
                for requested_range in command.request.ranges:
                    range_id = new_knowledge_analysis_range_id()
                    source = resolve_educational_document_source(
                        session,
                        self.artifacts,
                        document_revision_id=requested_range.source.document_revision_id,
                        source_class=requested_range.source.source_class,
                        first_physical_page=requested_range.source.first_physical_page,
                        last_physical_page=requested_range.source.last_physical_page,
                        curriculum_unit_keys=requested_range.source.curriculum_unit_keys,
                        cache=source_cache,
                    )
                    execution = requested_range.execution
                    analysis_run_id: str | None = None
                    predecessor_id: str | None = None
                    reuse_id: str | None = None
                    range_state = "PENDING"
                    if isinstance(execution, ReuseAcceptedKnowledgeAnalysisRange):
                        reuse_id = execution.accepted_analysis_run_id
                        self._validate_reused_analysis(
                            session,
                            run_id=reuse_id,
                            source=source,
                            preset_id=preset.preset_id,
                            preset_revision_id=preset_revision.preset_revision_id,
                            risk_policy_revision_id=policy.risk_policy_revision_id,
                            general_knowledge_mode=command.request.general_knowledge_mode,
                            allow_semantic_preset_equivalence=isinstance(
                                command.request, KnowledgeAnalysisBatchRequestV4
                            ),
                        )
                        analysis_run_id = reuse_id
                        range_state = "ACCEPTED"
                        accepted_count += 1
                    else:
                        predecessor_id = execution.predecessor_analysis_run_id
                        if predecessor_id is not None:
                            predecessor = self.analysis.retry_predecessor(
                                session,
                                self._range_create_command(
                                    batch=batch,
                                    range_id=range_id,
                                    source=source,
                                    predecessor_analysis_run_id=predecessor_id,
                                ),
                                source,
                            )
                            if predecessor is None or (
                                predecessor.preset_id != preset.preset_id
                                or predecessor.preset_revision_id
                                != preset_revision.preset_revision_id
                            ):
                                raise KnowledgeAnalysisBatchServiceError(
                                    "KNOWLEDGE_ANALYSIS_BATCH_RETRY_INVALID",
                                    "Knowledge Analysis batch retry preset is inconsistent",
                                )
                    session.add(
                        KnowledgeAnalysisBatchRangeRecord(
                            range_id=range_id,
                            batch_id=batch.batch_id,
                            ordinal=requested_range.ordinal,
                            document_id=source.document_id,
                            document_revision_id=source.document_revision_id,
                            first_physical_page=source.first_physical_page,
                            last_physical_page=source.last_physical_page,
                            curriculum_unit_keys=list(source.curriculum_unit_keys),
                            source_artifact_id=source.artifact_member.artifact_id,
                            source_artifact_revision_id=(
                                source.artifact_member.artifact_revision_id
                            ),
                            source_sha256=source.artifact_member.sha256,
                            source_media_type=source.artifact_member.media_type,
                            source_schema_ref=source.artifact_member.schema_ref,
                            analysis_artifact_id=source.analysis_bundle_manifest.artifact_id,
                            analysis_artifact_revision_id=(
                                source.analysis_bundle_manifest.artifact_revision_id
                            ),
                            analysis_manifest_sha256=source.analysis_bundle_manifest.sha256,
                            analysis_media_type=source.analysis_bundle_manifest.media_type,
                            analysis_schema_ref=source.analysis_bundle_manifest.schema_ref,
                            rights_artifact_id=source.rights_attestation.artifact_id,
                            rights_artifact_revision_id=(
                                source.rights_attestation.artifact_revision_id
                            ),
                            rights_attestation_sha256=source.rights_attestation.sha256,
                            rights_media_type=source.rights_attestation.media_type,
                            rights_schema_ref=source.rights_attestation.schema_ref,
                            execution_mode=execution.mode,
                            predecessor_analysis_run_id=predecessor_id,
                            reuse_accepted_analysis_run_id=reuse_id,
                            analysis_run_id=analysis_run_id,
                            state=range_state,
                            submission_attempts=0,
                            lease_owner=None,
                            lease_expires_at=None,
                            error_code=None,
                            resource_version=1,
                            completed_at=(datetime.now(UTC) if range_state == "ACCEPTED" else None),
                        )
                    )
                session.flush()
                session.add(
                    KnowledgeAnalysisBatchEventRecord(
                        batch_id=batch.batch_id,
                        range_id=None,
                        sequence=1,
                        event_type="BATCH_CREATED",
                        prior_state=None,
                        new_state=batch.state,
                        payload={
                            "request_sha256": batch.request_sha256,
                            "total_range_count": batch.total_range_count,
                            "reused_range_count": accepted_count,
                            "scheduling_mode": batch.scheduling_mode,
                            "max_in_flight": batch.max_in_flight,
                        },
                    )
                )
                if accepted_count == batch.total_range_count:
                    batch.state = "SUCCEEDED"
                    batch.completed_at = datetime.now(UTC)
                    batch.resource_version += 1
                    session.add(
                        KnowledgeAnalysisBatchEventRecord(
                            batch_id=batch.batch_id,
                            range_id=None,
                            sequence=2,
                            event_type="BATCH_SUCCEEDED",
                            prior_state="QUEUED",
                            new_state="SUCCEEDED",
                            payload={"accepted_range_count": accepted_count},
                        )
                    )
                session.flush()
                return self._projection(session, batch)
        except KnowledgeAnalysisBatchServiceError:
            raise
        except KnowledgeAnalysisSourceError as exc:
            raise KnowledgeAnalysisBatchServiceError(exc.code, str(exc)) from exc
        except KnowledgeAnalysisServiceError as exc:
            raise KnowledgeAnalysisBatchServiceError(exc.code, str(exc)) from exc
        except IntegrityError as exc:
            raise KnowledgeAnalysisBatchServiceError(
                "KNOWLEDGE_ANALYSIS_BATCH_CONCURRENCY_CONFLICT",
                "Knowledge Analysis batch raced with another transaction",
            ) from exc

    def advance_once(self, *, runner_id: str) -> bool:
        """Advance one poll and refill at most one reviewed capacity position."""

        submitted = self._reserve_submitted_action()
        if submitted is not None:
            self._advance_submitted(*submitted)
            # Polling every submitted range before claiming again can keep a due, long-running
            # range permanently ahead of the empty second position. Refill only after the
            # reserved poll commits; the batch lock and max_in_flight invariant still cap this at
            # one new range, and each range retains its single deterministic submission key.
            claimed = self._claim_next_range(
                runner_id=runner_id,
                parallel_refill_batch_id=submitted[0],
            )
            if claimed is not None:
                self._submit_claimed(*claimed, runner_id=runner_id)
            return True
        reclaimed = self._reclaim_expired_claim(runner_id=runner_id)
        if reclaimed is not None:
            self._submit_claimed(*reclaimed, runner_id=runner_id)
            return True
        claimed = self._claim_next_range(runner_id=runner_id)
        if claimed is None:
            return False
        self._submit_claimed(*claimed, runner_id=runner_id)
        return True

    def _reserve_submitted_action(self) -> tuple[str, str, str, int, str] | None:
        now = datetime.now(UTC)
        with transaction(self.sessions) as session:
            row = session.scalar(
                select(KnowledgeAnalysisBatchRangeRecord)
                .join(
                    KnowledgeAnalysisBatchRecord,
                    KnowledgeAnalysisBatchRecord.batch_id
                    == KnowledgeAnalysisBatchRangeRecord.batch_id,
                )
                .where(
                    KnowledgeAnalysisBatchRangeRecord.state == "SUBMITTED",
                    KnowledgeAnalysisBatchRangeRecord.next_action_at <= now,
                    KnowledgeAnalysisBatchRecord.state.in_(("QUEUED", "RUNNING")),
                )
                .order_by(
                    KnowledgeAnalysisBatchRangeRecord.next_action_at,
                    KnowledgeAnalysisBatchRangeRecord.batch_id,
                    KnowledgeAnalysisBatchRangeRecord.ordinal,
                )
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None or row.analysis_run_id is None:
                return None
            batch = session.get(KnowledgeAnalysisBatchRecord, row.batch_id)
            if batch is None:
                raise KnowledgeAnalysisBatchServiceError(
                    "KNOWLEDGE_ANALYSIS_BATCH_POINTER_INVALID",
                    "Knowledge Analysis batch range has no owning batch",
                )
            row.next_action_at = now + BATCH_ACTION_LEASE
            row.resource_version += 1
            return (
                batch.batch_id,
                row.range_id,
                row.analysis_run_id,
                row.resource_version,
                batch.authorized_by_operator_id,
            )

    def _reclaim_expired_claim(self, *, runner_id: str) -> tuple[str, str] | None:
        now = datetime.now(UTC)
        with transaction(self.sessions) as session:
            row = session.scalar(
                select(KnowledgeAnalysisBatchRangeRecord)
                .join(
                    KnowledgeAnalysisBatchRecord,
                    KnowledgeAnalysisBatchRecord.batch_id
                    == KnowledgeAnalysisBatchRangeRecord.batch_id,
                )
                .where(
                    KnowledgeAnalysisBatchRangeRecord.state == "CLAIMED",
                    KnowledgeAnalysisBatchRangeRecord.lease_expires_at <= now,
                    KnowledgeAnalysisBatchRecord.state.in_(("QUEUED", "RUNNING")),
                )
                .order_by(
                    KnowledgeAnalysisBatchRangeRecord.lease_expires_at,
                    KnowledgeAnalysisBatchRangeRecord.batch_id,
                    KnowledgeAnalysisBatchRangeRecord.ordinal,
                )
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                return None
            batch = session.get(KnowledgeAnalysisBatchRecord, row.batch_id)
            if batch is None:
                raise KnowledgeAnalysisBatchServiceError(
                    "KNOWLEDGE_ANALYSIS_BATCH_POINTER_INVALID",
                    "Claimed Knowledge Analysis range has no owning batch",
                )
            row.lease_owner = runner_id
            row.lease_expires_at = now + BATCH_ACTION_LEASE
            row.resource_version += 1
            self._append_event(
                session,
                batch=batch,
                range_id=row.range_id,
                event_type="RANGE_CLAIM_RECLAIMED",
                prior_state="CLAIMED",
                new_state="CLAIMED",
                payload={"ordinal": row.ordinal},
            )
            return batch.batch_id, row.range_id

    def _advance_submitted(
        self,
        batch_id: str,
        range_id: str,
        analysis_run_id: str,
        reserved_version: int,
        actor_id: str,
    ) -> None:
        try:
            result = self.analysis.reconcile(
                ReconcileKnowledgeAnalysisCommand(
                    analysis_run_id=analysis_run_id,
                    requested_by=actor_id,
                )
            )
            if result.state == "NEEDS_REVIEW":
                result = self.analysis.review(
                    ReviewKnowledgeAnalysisCommand(
                        analysis_run_id=analysis_run_id,
                        expected_version=result.resource_version,
                        decision="APPROVE",
                        notes=(f"Preauthorized validated batch approval: {batch_id}/{range_id}"),
                        decided_by=actor_id,
                        idempotency_key=f"analysis-batch-review:{range_id}",
                    )
                )
        except KnowledgeAnalysisServiceError as exc:
            self._block_submitted_range(
                range_id=range_id,
                analysis_run_id=analysis_run_id,
                reserved_version=reserved_version,
                error_code=exc.code,
            )
            return
        if result.state == "ACCEPTED":
            self._accept_submitted_range(
                range_id=range_id,
                analysis_run_id=analysis_run_id,
                reserved_version=reserved_version,
            )
        elif result.state in TERMINAL_ANALYSIS_STATES:
            self._block_submitted_range(
                range_id=range_id,
                analysis_run_id=analysis_run_id,
                reserved_version=reserved_version,
                error_code="KNOWLEDGE_ANALYSIS_BATCH_RANGE_FAILED",
            )
        else:
            self._release_submitted_poll(
                range_id=range_id,
                analysis_run_id=analysis_run_id,
                reserved_version=reserved_version,
            )

    def _claim_next_range(
        self,
        *,
        runner_id: str,
        parallel_refill_batch_id: str | None = None,
    ) -> tuple[str, str] | None:
        now = datetime.now(UTC)
        active = aliased(KnowledgeAnalysisBatchRangeRecord)
        pending = aliased(KnowledgeAnalysisBatchRangeRecord)
        earlier = aliased(KnowledgeAnalysisBatchRangeRecord)
        with transaction(self.sessions) as session:
            active_count = (
                select(func.count(active.range_id))
                .where(
                    active.batch_id == KnowledgeAnalysisBatchRecord.batch_id,
                    active.state.in_(("CLAIMED", "SUBMITTED")),
                )
                .correlate(KnowledgeAnalysisBatchRecord)
                .scalar_subquery()
            )
            batch_conditions = [
                KnowledgeAnalysisBatchRecord.state.in_(("QUEUED", "RUNNING")),
                active_count < KnowledgeAnalysisBatchRecord.max_in_flight,
                exists(
                    select(1).where(
                        pending.batch_id == KnowledgeAnalysisBatchRecord.batch_id,
                        pending.state == "PENDING",
                        pending.next_action_at <= now,
                    )
                ),
            ]
            if parallel_refill_batch_id is not None:
                batch_conditions.extend(
                    (
                        KnowledgeAnalysisBatchRecord.batch_id == parallel_refill_batch_id,
                        KnowledgeAnalysisBatchRecord.scheduling_mode == "BOUNDED_PARALLEL",
                        KnowledgeAnalysisBatchRecord.range_failure_policy == CONTINUE_AND_COLLECT,
                        KnowledgeAnalysisBatchRecord.max_in_flight == 2,
                    )
                )
            batch = session.scalar(
                select(KnowledgeAnalysisBatchRecord)
                .where(*batch_conditions)
                .order_by(
                    KnowledgeAnalysisBatchRecord.created_at,
                    KnowledgeAnalysisBatchRecord.batch_id,
                )
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if batch is None:
                return None
            held_count = int(
                session.scalar(
                    select(func.count(KnowledgeAnalysisBatchRangeRecord.range_id)).where(
                        KnowledgeAnalysisBatchRangeRecord.batch_id == batch.batch_id,
                        KnowledgeAnalysisBatchRangeRecord.state.in_(("CLAIMED", "SUBMITTED")),
                    )
                )
                or 0
            )
            if held_count >= batch.max_in_flight:
                return None
            row_conditions = [
                KnowledgeAnalysisBatchRangeRecord.batch_id == batch.batch_id,
                KnowledgeAnalysisBatchRangeRecord.state == "PENDING",
                KnowledgeAnalysisBatchRangeRecord.next_action_at <= now,
            ]
            if batch.scheduling_mode == "SERIAL":
                predecessor_states = (
                    ("ACCEPTED",)
                    if batch.range_failure_policy == STOP_ON_FIRST_FAILURE
                    else ("ACCEPTED", "FAILED")
                )
                row_conditions.append(
                    ~exists(
                        select(1).where(
                            earlier.batch_id == batch.batch_id,
                            earlier.ordinal < KnowledgeAnalysisBatchRangeRecord.ordinal,
                            ~earlier.state.in_(predecessor_states),
                        )
                    )
                )
            elif (
                batch.scheduling_mode != "BOUNDED_PARALLEL"
                or batch.range_failure_policy != CONTINUE_AND_COLLECT
                or batch.max_in_flight != 2
            ):
                raise KnowledgeAnalysisBatchServiceError(
                    "KNOWLEDGE_ANALYSIS_BATCH_POINTER_INVALID",
                    "Knowledge Analysis batch scheduling contract is invalid",
                )
            row = session.scalar(
                select(KnowledgeAnalysisBatchRangeRecord)
                .where(*row_conditions)
                .order_by(KnowledgeAnalysisBatchRangeRecord.ordinal)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                return None
            row.state = "CLAIMED"
            row.lease_owner = runner_id
            row.lease_expires_at = now + BATCH_ACTION_LEASE
            row.resource_version += 1
            if batch.state == "QUEUED":
                prior = batch.state
                batch.state = "RUNNING"
                batch.started_at = batch.started_at or now
                batch.resource_version += 1
                self._append_event(
                    session,
                    batch=batch,
                    range_id=None,
                    event_type="BATCH_STARTED",
                    prior_state=prior,
                    new_state="RUNNING",
                    payload={},
                )
            self._append_event(
                session,
                batch=batch,
                range_id=row.range_id,
                event_type="RANGE_CLAIMED",
                prior_state="PENDING",
                new_state="CLAIMED",
                payload={"ordinal": row.ordinal},
            )
            return batch.batch_id, row.range_id

    def _submit_claimed(self, batch_id: str, range_id: str, *, runner_id: str) -> None:
        try:
            with self.sessions() as session:
                batch = session.get(KnowledgeAnalysisBatchRecord, batch_id)
                row = session.get(KnowledgeAnalysisBatchRangeRecord, range_id)
                if (
                    batch is None
                    or row is None
                    or row.batch_id != batch_id
                    or row.state != "CLAIMED"
                    or row.lease_owner != runner_id
                ):
                    return
                source = self._resolve_and_verify_range_source(session, row)
                command = self._range_create_command(
                    batch=batch,
                    range_id=row.range_id,
                    source=source,
                    predecessor_analysis_run_id=row.predecessor_analysis_run_id,
                )
                preset_id = batch.preset_id
                preset_revision_id = batch.preset_revision_id
            result = self.analysis.create_with_pinned_preset(
                command,
                preset_id=preset_id,
                preset_revision_id=preset_revision_id,
            )
        except (KnowledgeAnalysisServiceError, KnowledgeAnalysisSourceError) as exc:
            self._fail_claimed_range(
                batch_id=batch_id,
                range_id=range_id,
                runner_id=runner_id,
                error_code=exc.code,
            )
            return
        with transaction(self.sessions) as session:
            row = session.scalar(
                select(KnowledgeAnalysisBatchRangeRecord)
                .where(KnowledgeAnalysisBatchRangeRecord.range_id == range_id)
                .with_for_update()
            )
            batch = session.get(KnowledgeAnalysisBatchRecord, batch_id)
            if (
                row is None
                or batch is None
                or row.state != "CLAIMED"
                or row.lease_owner != runner_id
            ):
                return
            row.analysis_run_id = result.analysis_run_id
            row.submission_attempts = 1
            row.state = "SUBMITTED"
            row.lease_owner = None
            row.lease_expires_at = None
            row.submitted_at = datetime.now(UTC)
            row.next_action_at = datetime.now(UTC) + BATCH_POLL_INTERVAL
            row.resource_version += 1
            self._append_event(
                session,
                batch=batch,
                range_id=range_id,
                event_type="RANGE_SUBMITTED",
                prior_state="CLAIMED",
                new_state="SUBMITTED",
                payload={"analysis_run_id": result.analysis_run_id},
            )

    def _resolve_and_verify_range_source(
        self,
        session: Session,
        row: KnowledgeAnalysisBatchRangeRecord,
    ) -> EducationalDocumentKnowledgeSourceV3 | EducationalDocumentKnowledgeSourceV4:
        source = resolve_educational_document_source(
            session,
            self.artifacts,
            document_revision_id=row.document_revision_id,
            source_class="TEXTBOOK",
            first_physical_page=row.first_physical_page,
            last_physical_page=row.last_physical_page,
            curriculum_unit_keys=tuple(row.curriculum_unit_keys),
        )
        if not self._source_matches_row(source, row):
            raise KnowledgeAnalysisSourceError(
                "KNOWLEDGE_ANALYSIS_SOURCE_STALE",
                "Knowledge Analysis batch source differs from its pinned dependencies",
            )
        return source

    @staticmethod
    def _source_matches_row(
        source: EducationalDocumentKnowledgeSourceV3 | EducationalDocumentKnowledgeSourceV4,
        row: KnowledgeAnalysisBatchRangeRecord,
    ) -> bool:
        return (
            source.document_id == row.document_id
            and source.document_revision_id == row.document_revision_id
            and source.artifact_member.artifact_id == row.source_artifact_id
            and source.artifact_member.artifact_revision_id == row.source_artifact_revision_id
            and source.artifact_member.sha256 == row.source_sha256
            and source.artifact_member.media_type == row.source_media_type
            and source.artifact_member.schema_ref == row.source_schema_ref
            and source.analysis_bundle_manifest.artifact_id == row.analysis_artifact_id
            and source.analysis_bundle_manifest.artifact_revision_id
            == row.analysis_artifact_revision_id
            and source.analysis_bundle_manifest.sha256 == row.analysis_manifest_sha256
            and source.analysis_bundle_manifest.media_type == row.analysis_media_type
            and source.analysis_bundle_manifest.schema_ref == row.analysis_schema_ref
            and source.rights_attestation.artifact_id == row.rights_artifact_id
            and source.rights_attestation.artifact_revision_id == row.rights_artifact_revision_id
            and source.rights_attestation.sha256 == row.rights_attestation_sha256
            and source.rights_attestation.media_type == row.rights_media_type
            and source.rights_attestation.schema_ref == row.rights_schema_ref
            and source.first_physical_page == row.first_physical_page
            and source.last_physical_page == row.last_physical_page
            and source.curriculum_unit_keys == tuple(row.curriculum_unit_keys)
        )

    @staticmethod
    def _range_create_command(
        *,
        batch: KnowledgeAnalysisBatchRecord,
        range_id: str,
        source: EducationalDocumentKnowledgeSourceV3 | EducationalDocumentKnowledgeSourceV4,
        predecessor_analysis_run_id: str | None,
    ) -> CreateKnowledgeAnalysisCommand:
        return CreateKnowledgeAnalysisCommand(
            source=EducationalDocumentKnowledgeAnalysisSelection(
                source_class=source.source_class,
                document_revision_id=source.document_revision_id,
                first_physical_page=source.first_physical_page,
                last_physical_page=source.last_physical_page,
                curriculum_unit_keys=source.curriculum_unit_keys,
            ),
            preset_key="knowledge-analysis",
            general_knowledge_mode=cast(
                Literal["DISABLED", "AUXILIARY_UNATTRIBUTED"],
                batch.general_knowledge_mode,
            ),
            risk_policy_revision_id=batch.risk_policy_revision_id,
            predecessor_analysis_run_id=predecessor_analysis_run_id,
            requested_by=batch.authorized_by_operator_id,
            idempotency_key=f"analysis-batch-range:{range_id}",
        )

    @staticmethod
    def _validate_reused_analysis(
        session: Session,
        *,
        run_id: str,
        source: EducationalDocumentKnowledgeSourceV3 | EducationalDocumentKnowledgeSourceV4,
        preset_id: str,
        preset_revision_id: str,
        risk_policy_revision_id: str,
        general_knowledge_mode: str,
        allow_semantic_preset_equivalence: bool,
    ) -> None:
        run = session.get(KnowledgeAnalysisRunRecord, run_id)
        if run is None or run.state != "ACCEPTED":
            raise KnowledgeAnalysisBatchServiceError(
                "KNOWLEDGE_ANALYSIS_BATCH_REUSE_INVALID",
                "Reused Knowledge Analysis run is absent or not accepted",
            )
        try:
            request_version = run.canonical_request.get("schema_version")
            request: (
                KnowledgeAnalysisRequestV3
                | KnowledgeAnalysisRequestV4
                | KnowledgeAnalysisRequestV5
                | KnowledgeAnalysisRequestV6
                | KnowledgeAnalysisRequestV7
                | KnowledgeAnalysisRequestV8
            )
            if request_version == "knowledge-analysis-request/8.0":
                request = KnowledgeAnalysisRequestV8.model_validate(run.canonical_request)
            elif request_version == "knowledge-analysis-request/7.0":
                request = KnowledgeAnalysisRequestV7.model_validate(run.canonical_request)
            elif request_version == "knowledge-analysis-request/6.0":
                request = KnowledgeAnalysisRequestV6.model_validate(run.canonical_request)
            elif request_version == "knowledge-analysis-request/5.0":
                request = KnowledgeAnalysisRequestV5.model_validate(run.canonical_request)
            elif request_version == "knowledge-analysis-request/4.0":
                request = KnowledgeAnalysisRequestV4.model_validate(run.canonical_request)
            else:
                request = KnowledgeAnalysisRequestV3.model_validate(run.canonical_request)
        except ValueError as exc:
            raise KnowledgeAnalysisBatchServiceError(
                "KNOWLEDGE_ANALYSIS_BATCH_REUSE_INVALID",
                "Reused Knowledge Analysis request is invalid",
            ) from exc
        logical = session.get(ArtifactRecord, run.accepted_result_artifact_id)
        revision = session.get(ArtifactRevisionRecord, run.accepted_result_artifact_revision_id)
        try:
            accepted_result: (
                KnowledgeAnalysisResultV3
                | KnowledgeAnalysisResultV4
                | KnowledgeAnalysisResultV5
                | KnowledgeAnalysisResultV6
                | KnowledgeAnalysisResultV7
                | KnowledgeAnalysisResultV8
            )
            if isinstance(request, KnowledgeAnalysisRequestV8):
                accepted_result = KnowledgeAnalysisResultV8.model_validate(
                    revision.result if revision is not None else None
                )
            elif isinstance(request, KnowledgeAnalysisRequestV7):
                accepted_result = KnowledgeAnalysisResultV7.model_validate(
                    revision.result if revision is not None else None
                )
            elif isinstance(request, KnowledgeAnalysisRequestV6):
                accepted_result = KnowledgeAnalysisResultV6.model_validate(
                    revision.result if revision is not None else None
                )
            elif isinstance(request, KnowledgeAnalysisRequestV5):
                accepted_result = KnowledgeAnalysisResultV5.model_validate(
                    revision.result if revision is not None else None
                )
            elif isinstance(request, KnowledgeAnalysisRequestV4):
                accepted_result = KnowledgeAnalysisResultV4.model_validate(
                    revision.result if revision is not None else None
                )
            else:
                accepted_result = KnowledgeAnalysisResultV3.model_validate(
                    revision.result if revision is not None else None
                )
        except ValueError as exc:
            raise KnowledgeAnalysisBatchServiceError(
                "KNOWLEDGE_ANALYSIS_BATCH_REUSE_INVALID",
                "Reused Knowledge Analysis result pointer is invalid",
            ) from exc
        preset_revision_matches = run.preset_revision_id == preset_revision_id
        if not preset_revision_matches and allow_semantic_preset_equivalence:
            preset_revision_matches = (
                KnowledgeAnalysisBatchService._preset_execution_semantics_sha256(
                    session, run.preset_revision_id
                )
                == KnowledgeAnalysisBatchService._preset_execution_semantics_sha256(
                    session, preset_revision_id
                )
            )
        if (
            request.source != source
            or request.general_knowledge_mode != general_knowledge_mode
            or request.risk_policy_revision_id != risk_policy_revision_id
            or run.preset_id != preset_id
            or not preset_revision_matches
            or logical is None
            or revision is None
            or not logical.approved
            or not revision.approved
            or revision.logical_artifact_id != logical.logical_artifact_id
            or logical.logical_artifact_id != run.accepted_result_artifact_id
            or revision.revision_id != run.accepted_result_artifact_revision_id
            or revision.content_hash != run.accepted_result_sha256
            or revision.manifest.get("artifact_type") != "knowledge-analysis-accepted-result"
            or revision.manifest.get("primary_file") != "evidence/accepted-result.json"
            or accepted_result.analysis_request_sha256 != run.request_sha256
            or accepted_result.source != source
            or accepted_result.status != "ACCEPTED"
        ):
            raise KnowledgeAnalysisBatchServiceError(
                "KNOWLEDGE_ANALYSIS_BATCH_REUSE_INVALID",
                "Reused Knowledge Analysis dependencies are stale or inconsistent",
            )

    @staticmethod
    def _preset_execution_semantics_sha256(session: Session, preset_revision_id: str) -> str:
        revision = session.get(ExecutionPresetRevisionRecord, preset_revision_id)
        if revision is None or revision.state != "RELEASED":
            raise KnowledgeAnalysisBatchServiceError(
                "KNOWLEDGE_ANALYSIS_BATCH_REUSE_INVALID",
                "Reused Knowledge Analysis preset revision is unavailable",
            )
        document = revision.canonical_document
        try:
            normalized_roles: list[dict[str, object]] = []
            for raw_policy in document["role_policies"]:
                if not isinstance(raw_policy, dict):
                    raise KeyError("role_policies")
                instruction_pointer = raw_policy["instruction_bundle"]
                if not isinstance(instruction_pointer, dict):
                    raise KeyError("instruction_bundle")
                bundle_revision_id = instruction_pointer["bundle_revision_id"]
                if not isinstance(bundle_revision_id, str):
                    raise KeyError("bundle_revision_id")
                bundle = session.get(ExecutionBundleRevisionRecord, bundle_revision_id)
                if (
                    bundle is None
                    or bundle.state != "RELEASED"
                    or bundle.bundle_kind != "INSTRUCTION"
                ):
                    raise KeyError("instruction_bundle")
                components = bundle.canonical_document["components"]
                if not isinstance(components, list):
                    raise KeyError("components")
                normalized_components: list[dict[str, object]] = []
                for component in components:
                    if not isinstance(component, dict) or not isinstance(
                        component.get("artifact"), dict
                    ):
                        raise KeyError("components")
                    artifact = component["artifact"]
                    normalized_components.append(
                        {
                            "layer": component["layer"],
                            "relative_path": component["relative_path"],
                            "artifact_sha256": artifact["sha256"],
                            "schema_ref": artifact["schema_ref"],
                            "media_type": artifact["media_type"],
                            "logical_name": artifact["logical_name"],
                        }
                    )
                normalized_roles.append(
                    {
                        key: value
                        for key, value in raw_policy.items()
                        if key not in {"instruction_bundle", "reference_bundle"}
                    }
                    | {
                        "instruction_components": normalized_components,
                        "reference_bundle": raw_policy.get("reference_bundle"),
                    }
                )
            projection = {
                "schema_version": document["schema_version"],
                "role_policies": normalized_roles,
                "general_knowledge_policy": document["general_knowledge_policy"],
                "compatible_workflow_protocols": document["compatible_workflow_protocols"],
            }
        except (KeyError, TypeError) as exc:
            raise KnowledgeAnalysisBatchServiceError(
                "KNOWLEDGE_ANALYSIS_BATCH_REUSE_INVALID",
                "Reused Knowledge Analysis preset semantics are incomplete",
            ) from exc
        return content_sha256(projection)

    def _accept_submitted_range(
        self,
        *,
        range_id: str,
        analysis_run_id: str,
        reserved_version: int,
    ) -> None:
        with transaction(self.sessions) as session:
            row, batch = self._locked_reserved_range(
                session,
                range_id=range_id,
                analysis_run_id=analysis_run_id,
                reserved_version=reserved_version,
            )
            if row is None or batch is None:
                return
            run = session.get(KnowledgeAnalysisRunRecord, analysis_run_id)
            if run is None or run.state != "ACCEPTED":
                raise KnowledgeAnalysisBatchServiceError(
                    "KNOWLEDGE_ANALYSIS_BATCH_POINTER_INVALID",
                    "Accepted batch range does not resolve an accepted run",
                )
            row.state = "ACCEPTED"
            row.completed_at = datetime.now(UTC)
            row.next_action_at = datetime.now(UTC)
            row.resource_version += 1
            self._append_event(
                session,
                batch=batch,
                range_id=row.range_id,
                event_type="RANGE_ACCEPTED",
                prior_state="SUBMITTED",
                new_state="ACCEPTED",
                payload={"analysis_run_id": analysis_run_id},
            )
            self._terminalize_completed_batch(session, batch=batch)

    def _block_submitted_range(
        self,
        *,
        range_id: str,
        analysis_run_id: str,
        reserved_version: int,
        error_code: str,
    ) -> None:
        with transaction(self.sessions) as session:
            row, batch = self._locked_reserved_range(
                session,
                range_id=range_id,
                analysis_run_id=analysis_run_id,
                reserved_version=reserved_version,
            )
            if row is None or batch is None:
                return
            self._mark_failed(session, batch=batch, row=row, error_code=error_code)

    def _release_submitted_poll(
        self,
        *,
        range_id: str,
        analysis_run_id: str,
        reserved_version: int,
    ) -> None:
        with transaction(self.sessions) as session:
            row, _batch = self._locked_reserved_range(
                session,
                range_id=range_id,
                analysis_run_id=analysis_run_id,
                reserved_version=reserved_version,
            )
            if row is None:
                return
            row.next_action_at = datetime.now(UTC) + BATCH_POLL_INTERVAL
            row.resource_version += 1

    def _fail_claimed_range(
        self,
        *,
        batch_id: str,
        range_id: str,
        runner_id: str,
        error_code: str,
    ) -> None:
        with transaction(self.sessions) as session:
            row = session.scalar(
                select(KnowledgeAnalysisBatchRangeRecord)
                .where(KnowledgeAnalysisBatchRangeRecord.range_id == range_id)
                .with_for_update()
            )
            batch = session.get(KnowledgeAnalysisBatchRecord, batch_id)
            if (
                row is None
                or batch is None
                or row.state != "CLAIMED"
                or row.lease_owner != runner_id
            ):
                return
            self._mark_failed(session, batch=batch, row=row, error_code=error_code)

    def _mark_failed(
        self,
        session: Session,
        *,
        batch: KnowledgeAnalysisBatchRecord,
        row: KnowledgeAnalysisBatchRangeRecord,
        error_code: str,
    ) -> None:
        range_prior = row.state
        row.state = "FAILED"
        row.error_code = error_code
        row.lease_owner = None
        row.lease_expires_at = None
        row.completed_at = datetime.now(UTC)
        row.resource_version += 1
        self._append_event(
            session,
            batch=batch,
            range_id=row.range_id,
            event_type="RANGE_FAILED",
            prior_state=range_prior,
            new_state="FAILED",
            payload={
                "error_code": error_code,
                "ordinal": row.ordinal,
                "range_failure_policy": batch.range_failure_policy,
            },
        )
        if batch.range_failure_policy == STOP_ON_FIRST_FAILURE:
            self._block_batch(
                session,
                batch=batch,
                error_code=error_code,
                range_id=row.range_id,
            )
        else:
            self._terminalize_completed_batch(session, batch=batch)

    def _terminalize_completed_batch(
        self,
        session: Session,
        *,
        batch: KnowledgeAnalysisBatchRecord,
    ) -> None:
        accepted = self._count_ranges(session, batch.batch_id, "ACCEPTED")
        failed = self._count_ranges(session, batch.batch_id, "FAILED")
        if accepted + failed != batch.total_range_count:
            return
        if failed:
            self._block_batch(
                session,
                batch=batch,
                error_code=COLLECTED_FAILURE_CODE,
                range_id=None,
            )
            return
        prior = batch.state
        batch.state = "SUCCEEDED"
        batch.failure_code = None
        batch.completed_at = datetime.now(UTC)
        batch.resource_version += 1
        self._append_event(
            session,
            batch=batch,
            range_id=None,
            event_type="BATCH_SUCCEEDED",
            prior_state=prior,
            new_state="SUCCEEDED",
            payload={"accepted_range_count": accepted},
        )

    def _block_batch(
        self,
        session: Session,
        *,
        batch: KnowledgeAnalysisBatchRecord,
        error_code: str,
        range_id: str | None,
    ) -> None:
        prior = batch.state
        batch.state = "BLOCKED"
        batch.failure_code = error_code
        batch.completed_at = datetime.now(UTC)
        batch.resource_version += 1
        self._append_event(
            session,
            batch=batch,
            range_id=None,
            event_type="BATCH_BLOCKED",
            prior_state=prior,
            new_state="BLOCKED",
            payload={"error_code": error_code, "range_id": range_id},
        )

    @staticmethod
    def _locked_reserved_range(
        session: Session,
        *,
        range_id: str,
        analysis_run_id: str,
        reserved_version: int,
    ) -> tuple[KnowledgeAnalysisBatchRangeRecord | None, KnowledgeAnalysisBatchRecord | None]:
        row = session.scalar(
            select(KnowledgeAnalysisBatchRangeRecord)
            .where(KnowledgeAnalysisBatchRangeRecord.range_id == range_id)
            .with_for_update()
        )
        if (
            row is None
            or row.state != "SUBMITTED"
            or row.analysis_run_id != analysis_run_id
            or row.resource_version != reserved_version
        ):
            return None, None
        batch = session.scalar(
            select(KnowledgeAnalysisBatchRecord)
            .where(KnowledgeAnalysisBatchRecord.batch_id == row.batch_id)
            .with_for_update()
        )
        return row, batch

    @staticmethod
    def _append_event(
        session: Session,
        *,
        batch: KnowledgeAnalysisBatchRecord,
        range_id: str | None,
        event_type: str,
        prior_state: str | None,
        new_state: str,
        payload: dict[str, object],
    ) -> None:
        with session.no_autoflush:
            sequence = session.scalar(
                select(
                    func.coalesce(func.max(KnowledgeAnalysisBatchEventRecord.sequence), 0)
                ).where(KnowledgeAnalysisBatchEventRecord.batch_id == batch.batch_id)
            )
        session.add(
            KnowledgeAnalysisBatchEventRecord(
                batch_id=batch.batch_id,
                range_id=range_id,
                sequence=int(sequence or 0) + 1,
                event_type=event_type,
                prior_state=prior_state,
                new_state=new_state,
                payload=payload,
            )
        )
        session.flush()

    @staticmethod
    def _count_ranges(session: Session, batch_id: str, state: str) -> int:
        value = session.scalar(
            select(func.count())
            .select_from(KnowledgeAnalysisBatchRangeRecord)
            .where(
                KnowledgeAnalysisBatchRangeRecord.batch_id == batch_id,
                KnowledgeAnalysisBatchRangeRecord.state == state,
            )
        )
        return int(value or 0)

    @classmethod
    def _projection(
        cls,
        session: Session,
        batch: KnowledgeAnalysisBatchRecord,
    ) -> KnowledgeAnalysisBatchApplicationResult:
        return KnowledgeAnalysisBatchApplicationResult(
            batch_id=batch.batch_id,
            state=cast(
                Literal["QUEUED", "RUNNING", "BLOCKED", "SUCCEEDED", "CANCELLED"],
                batch.state,
            ),
            resource_version=batch.resource_version,
            total_range_count=batch.total_range_count,
            accepted_range_count=cls._count_ranges(session, batch.batch_id, "ACCEPTED"),
            failed_range_count=cls._count_ranges(session, batch.batch_id, "FAILED"),
        )
