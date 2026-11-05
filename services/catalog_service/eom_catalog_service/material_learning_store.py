"""Catalog persistence adapter for material checkpoints, not a second worker queue.

The calling application authorizes/resolves all inputs and owns the transaction.
This adapter records pointers and claims short coordinator actions. Actual model
capacity, child execution and Artifact publication stay with their current owners.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import NAMESPACE_URL, uuid4, uuid5

from eom_catalog_contracts.material_learning import MaterialArtifactMember, MaterialKind
from eom_workflow.material_learning_state import (
    MaterialLearningState,
    MaterialTaskState,
    require_material_task_transition,
    require_material_transition,
)
from sqlalchemy import exists, or_, select, text
from sqlalchemy.orm import Session

from eom_catalog_service.material_learning_models import (
    LearningMaterialRecord,
    LearningMaterialRevisionRecord,
    MaterialLearningEventRecord,
    MaterialLearningRunRecord,
    MaterialLearningTaskRecord,
)

_TERMINAL_RUNS = frozenset({"COMPLETED", "COMPLETED_WITH_EXCEPTIONS", "FAILED", "CANCELLED"})
_AI_STATES = frozenset({"RUNNING", "ANALYZING"})
# A separate, transaction-scoped lock: never the host-capacity/model lock.
_MATERIAL_AI_LANE_LOCK = 8202611057401


class MaterialLearningStorageError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class MaterialIdentity:
    material_id: str
    material_revision_id: str
    first_run_id: str


def material_submission_identity(operator_id: str, idempotency_key: str) -> MaterialIdentity:
    """IDs bind the operator/command identity, independently of content hashes."""
    if not operator_id or not 16 <= len(idempotency_key) <= 128:
        raise MaterialLearningStorageError("MATERIAL_LEARNING_SUBMISSION_KEY_INVALID")
    namespace = uuid5(NAMESPACE_URL, f"eom:material-learning:{operator_id}:{idempotency_key}")
    return MaterialIdentity(
        "material_" + uuid5(namespace, "logical-material").hex,
        "materialrev_" + uuid5(namespace, "source-revision:1").hex,
        "materialrun_" + uuid5(namespace, "processing-attempt:1").hex,
    )


@dataclass(frozen=True, slots=True)
class MaterialSubmissionPins:
    operator_id: str
    idempotency_key: str
    title: str
    material_kind: MaterialKind
    request_sha256: str
    manifest: MaterialArtifactMember


@dataclass(frozen=True, slots=True)
class MaterialRunClaim:
    run_id: str
    lease_owner: str
    lease_token: str
    lease_expires_at: datetime


def _require_transaction(session: Session) -> None:
    if not session.in_transaction():
        raise MaterialLearningStorageError("MATERIAL_LEARNING_TRANSACTION_REQUIRED")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise MaterialLearningStorageError("MATERIAL_LEARNING_UTC_REQUIRED")
    return value


def create_material_learning(
    session: Session, pins: MaterialSubmissionPins
) -> tuple[MaterialLearningRunRecord, bool]:
    """Exact replay, never global hash reuse across operators or other commands."""
    _require_transaction(session)
    identity = material_submission_identity(pins.operator_id, pins.idempotency_key)
    # Serialize only this operator/key; the DB unique constraint remains the guard.
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"material-submit:{pins.operator_id}:{pins.idempotency_key}"},
    )
    previous = session.scalar(
        select(LearningMaterialRevisionRecord).where(
            LearningMaterialRevisionRecord.created_by == pins.operator_id,
            LearningMaterialRevisionRecord.idempotency_key == pins.idempotency_key,
        )
    )
    if previous is not None:
        if (
            previous.material_id != identity.material_id
            or previous.material_revision_id != identity.material_revision_id
            or previous.request_sha256 != pins.request_sha256
            or previous.title != pins.title
            or previous.material_kind != pins.material_kind
            or (
                previous.manifest_artifact_id,
                previous.manifest_artifact_revision_id,
                previous.manifest_member_path,
                previous.manifest_sha256,
            )
            != (
                pins.manifest.artifact_id,
                pins.manifest.artifact_revision_id,
                pins.manifest.member_path,
                pins.manifest.sha256,
            )
        ):
            raise MaterialLearningStorageError("MATERIAL_LEARNING_IDEMPOTENCY_CONFLICT")
        run = session.get(MaterialLearningRunRecord, identity.first_run_id)
        if run is None:
            raise MaterialLearningStorageError("MATERIAL_LEARNING_RUN_MISSING")
        return run, False
    material = LearningMaterialRecord(
        material_id=identity.material_id,
        current_revision_id=None,
        lifecycle_state="ACTIVE",
        created_by=pins.operator_id,
    )
    session.add(material)
    session.flush()
    revision = LearningMaterialRevisionRecord(
        material_revision_id=identity.material_revision_id,
        material_id=identity.material_id,
        revision_number=1,
        previous_revision_id=None,
        title=pins.title,
        material_kind=pins.material_kind,
        request_sha256=pins.request_sha256,
        manifest_artifact_id=pins.manifest.artifact_id,
        manifest_artifact_revision_id=pins.manifest.artifact_revision_id,
        manifest_member_path=pins.manifest.member_path,
        manifest_sha256=pins.manifest.sha256,
        idempotency_key=pins.idempotency_key,
        created_by=pins.operator_id,
    )
    session.add(revision)
    session.flush()
    material.current_revision_id = revision.material_revision_id
    run = MaterialLearningRunRecord(
        run_id=identity.first_run_id,
        material_revision_id=revision.material_revision_id,
        attempt=1,
        predecessor_run_id=None,
        state="RECEIVED",
        next_event_sequence=1,
        created_by=pins.operator_id,
    )
    session.add(run)
    session.flush()
    append_material_event(session, run, event_type="MATERIAL_RECEIVED", prior_state=None)
    return run, True


def claim_next_material_run(
    session: Session, *, lease_owner: str, now: datetime, lease_duration: timedelta
) -> MaterialRunClaim | None:
    _require_transaction(session)
    _utc(now)
    if not 1 <= len(lease_owner) <= 128 or not timedelta(seconds=10) <= lease_duration <= timedelta(
        hours=1
    ):
        raise MaterialLearningStorageError("MATERIAL_LEARNING_LEASE_INVALID")
    run = session.scalar(
        select(MaterialLearningRunRecord)
        .join(
            LearningMaterialRevisionRecord,
            LearningMaterialRevisionRecord.material_revision_id
            == MaterialLearningRunRecord.material_revision_id,
        )
        .join(
            LearningMaterialRecord,
            LearningMaterialRecord.material_id == LearningMaterialRevisionRecord.material_id,
        )
        .where(
            MaterialLearningRunRecord.state.not_in(_TERMINAL_RUNS),
            or_(
                MaterialLearningRunRecord.state != "PAUSED",
                exists().where(
                    MaterialLearningTaskRecord.run_id == MaterialLearningRunRecord.run_id,
                    MaterialLearningTaskRecord.state.in_(_AI_STATES),
                ),
            ),
            LearningMaterialRecord.lifecycle_state == "ACTIVE",
            or_(
                MaterialLearningRunRecord.lease_expires_at.is_(None),
                MaterialLearningRunRecord.lease_expires_at <= now,
            ),
        )
        .order_by(MaterialLearningRunRecord.created_at, MaterialLearningRunRecord.run_id)
        .with_for_update(of=MaterialLearningRunRecord, skip_locked=True)
        .limit(1)
        .execution_options(populate_existing=True)
    )
    if run is None:
        return None
    run.lease_owner = lease_owner
    run.lease_token = uuid4().hex
    run.lease_expires_at = now + lease_duration
    run.updated_at = now
    session.flush()
    return MaterialRunClaim(run.run_id, lease_owner, run.lease_token, run.lease_expires_at)


def lock_material_run(
    session: Session, claim: MaterialRunClaim, *, now: datetime
) -> MaterialLearningRunRecord:
    _require_transaction(session)
    _utc(now)
    run = session.scalar(
        select(MaterialLearningRunRecord)
        .where(MaterialLearningRunRecord.run_id == claim.run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        run is None
        or run.lease_owner != claim.lease_owner
        or run.lease_token != claim.lease_token
        or run.lease_expires_at is None
        or run.lease_expires_at <= now
        or run.state in _TERMINAL_RUNS
    ):
        raise MaterialLearningStorageError("MATERIAL_LEARNING_COORDINATOR_LEASE_STALE")
    return run


def renew_material_claim(
    session: Session, claim: MaterialRunClaim, *, now: datetime, lease_duration: timedelta
) -> MaterialRunClaim:
    if not timedelta(seconds=10) <= lease_duration <= timedelta(hours=1):
        raise MaterialLearningStorageError("MATERIAL_LEARNING_LEASE_INVALID")
    run = lock_material_run(session, claim, now=now)
    run.lease_expires_at = now + lease_duration
    run.updated_at = now
    return MaterialRunClaim(run.run_id, claim.lease_owner, claim.lease_token, run.lease_expires_at)


def release_material_claim(session: Session, claim: MaterialRunClaim, *, now: datetime) -> None:
    run = lock_material_run(session, claim, now=now)
    run.lease_owner = run.lease_token = run.lease_expires_at = None
    run.updated_at = now


def append_material_event(
    session: Session,
    run: MaterialLearningRunRecord,
    *,
    event_type: str,
    prior_state: str | None,
    task: MaterialLearningTaskRecord | None = None,
    error_code: str | None = None,
) -> None:
    """The caller holds the parent row lock (or owns a not-yet-committed new row)."""
    if task is not None and task.run_id != run.run_id:
        raise MaterialLearningStorageError("MATERIAL_LEARNING_TASK_OWNER_MISMATCH")
    sequence = run.next_event_sequence
    run.next_event_sequence += 1
    session.add(
        MaterialLearningEventRecord(
            run_id=run.run_id,
            task_id=task.task_id if task else None,
            sequence=sequence,
            event_type=event_type,
            prior_state=prior_state,
            new_state=task.state if task else run.state,
            error_code=error_code,
        )
    )


def transition_material_run(
    session: Session,
    run: MaterialLearningRunRecord,
    target: MaterialLearningState,
    *,
    now: datetime,
    error_code: str | None = None,
) -> None:
    _utc(now)
    prior = run.state
    require_material_transition(MaterialLearningState(prior), target)
    if target in _TERMINAL_RUNS and session.scalar(
        select(
            exists().where(
                MaterialLearningTaskRecord.run_id == run.run_id,
                MaterialLearningTaskRecord.state.in_(_AI_STATES),
            )
        )
    ):
        raise MaterialLearningStorageError("MATERIAL_LEARNING_ACTIVE_CHILD_REQUIRES_RECONCILIATION")
    if target in {MaterialLearningState.COMPLETED, MaterialLearningState.COMPLETED_WITH_EXCEPTIONS}:
        unfinished = session.scalar(
            select(
                exists().where(
                    MaterialLearningTaskRecord.run_id == run.run_id,
                    MaterialLearningTaskRecord.state.not_in(
                        {"COMPLETED", "FAILED", "EXCEPTION", "CANCELLED"}
                    ),
                )
            )
        )
        issues = session.scalar(
            select(
                exists().where(
                    MaterialLearningTaskRecord.run_id == run.run_id,
                    MaterialLearningTaskRecord.state.in_({"FAILED", "EXCEPTION", "CANCELLED"}),
                )
            )
        )
        has_coverage = session.scalar(
            select(
                exists().where(
                    MaterialLearningTaskRecord.run_id == run.run_id,
                    MaterialLearningTaskRecord.task_kind == "DISCOVER",
                )
            )
        )
        if unfinished or not has_coverage:
            raise MaterialLearningStorageError("MATERIAL_LEARNING_COVERAGE_NOT_FINISHED")
        if bool(issues) != (target == MaterialLearningState.COMPLETED_WITH_EXCEPTIONS):
            raise MaterialLearningStorageError("MATERIAL_LEARNING_COMPLETION_ISSUES_MISMATCH")
    if target == MaterialLearningState.WAITING_FOR_CAPACITY:
        run.phase_before_wait = prior
    elif prior == MaterialLearningState.WAITING_FOR_CAPACITY:
        if (
            target not in {MaterialLearningState.PAUSED, MaterialLearningState.CANCELLED}
            and target != run.phase_before_wait
        ):
            raise MaterialLearningStorageError("MATERIAL_LEARNING_RESUME_PHASE_MISMATCH")
        run.phase_before_wait = None
    if target in _TERMINAL_RUNS:
        run.lease_owner = run.lease_token = run.lease_expires_at = None
    run.state = target.value
    run.error_code = error_code
    run.updated_at = now
    append_material_event(
        session, run, event_type="MATERIAL_STATE_CHANGED", prior_state=prior, error_code=error_code
    )


def add_material_task(
    session: Session,
    run: MaterialLearningRunRecord,
    *,
    task_kind: str,
    unit_key: str,
    ordinal: int,
) -> tuple[MaterialLearningTaskRecord, bool]:
    """Stable task identity across coordinator restart; retry has a separate use case."""
    if (
        task_kind not in {"DISCOVER", "EXPLANATION", "QUESTION"}
        or not 1 <= len(unit_key) <= 128
        or ordinal < 1
    ):
        raise MaterialLearningStorageError("MATERIAL_LEARNING_TASK_IDENTITY_INVALID")
    task_id = (
        "materialtask_" + uuid5(NAMESPACE_URL, f"{run.run_id}:{task_kind}:{unit_key}:attempt:1").hex
    )
    task = session.get(MaterialLearningTaskRecord, task_id)
    if task is not None:
        if (task.run_id, task.task_kind, task.unit_key, task.ordinal, task.attempt) != (
            run.run_id,
            task_kind,
            unit_key,
            ordinal,
            1,
        ):
            raise MaterialLearningStorageError("MATERIAL_LEARNING_TASK_REPLAY_CONFLICT")
        return task, False
    task = MaterialLearningTaskRecord(
        task_id=task_id,
        run_id=run.run_id,
        task_kind=task_kind,
        unit_key=unit_key,
        ordinal=ordinal,
        attempt=1,
        state="PENDING",
        execution_lane="MATERIAL_LEARNING",
    )
    session.add(task)
    session.flush()
    append_material_event(
        session, run, event_type="MATERIAL_TASK_ADDED", prior_state=None, task=task
    )
    return task, True


def transition_material_task(
    session: Session,
    run: MaterialLearningRunRecord,
    task: MaterialLearningTaskRecord,
    target: MaterialTaskState,
    *,
    now: datetime,
    error_code: str | None = None,
) -> bool:
    _utc(now)
    if task.run_id != run.run_id:
        raise MaterialLearningStorageError("MATERIAL_LEARNING_TASK_OWNER_MISMATCH")
    prior = task.state
    require_material_task_transition(MaterialTaskState(prior), target)
    if target in _AI_STATES:
        lane_locked = session.scalar(
            text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": _MATERIAL_AI_LANE_LOCK}
        )
        if not lane_locked or session.scalar(
            select(
                exists().where(
                    MaterialLearningTaskRecord.state.in_(_AI_STATES),
                    MaterialLearningTaskRecord.task_id != task.task_id,
                )
            )
        ):
            return False
    task.state = target.value
    task.error_code = error_code
    task.updated_at = now
    session.flush()
    append_material_event(
        session,
        run,
        event_type="MATERIAL_TASK_STATE_CHANGED",
        prior_state=prior,
        task=task,
        error_code=error_code,
    )
    return True


def next_material_task(session: Session, run_id: str) -> MaterialLearningTaskRecord | None:
    return session.scalar(
        select(MaterialLearningTaskRecord)
        .where(
            MaterialLearningTaskRecord.run_id == run_id,
            MaterialLearningTaskRecord.state.not_in(
                {"COMPLETED", "EXCEPTION", "FAILED", "CANCELLED"}
            ),
        )
        .order_by(MaterialLearningTaskRecord.ordinal, MaterialLearningTaskRecord.attempt.desc())
        .limit(1)
    )
