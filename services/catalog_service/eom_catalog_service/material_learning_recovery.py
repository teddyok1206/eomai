"""Explicit failed-unit successor over the original immutable source revision."""

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from eom_catalog_contracts.material_learning_intake import (
    MaterialLearningRetryResult,
    RetryMaterialLearningRunCommand,
)
from eom_identifiers import content_sha256
from eom_orchestrator.control_models import WorkerLeaseRecord
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from eom_workflow_runner.models import WorkflowInstanceRecord
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from eom_catalog_service.material_learning_models import (
    LearningMaterialRecord,
    LearningMaterialRevisionRecord,
    MaterialLearningRunRecord,
    MaterialLearningTaskRecord,
)
from eom_catalog_service.material_learning_source import (
    MaterialLearningSourceError,
    authorize_material_learning,
)
from eom_catalog_service.material_learning_store import append_material_event
from eom_catalog_service.material_task_history import (
    MAX_MATERIAL_ATTEMPTS,
    read_material_task_histories,
)

_TERMINAL_TASKS = frozenset({"COMPLETED", "FAILED", "EXCEPTION", "CANCELLED"})
_ARTIFACT_FIELDS = (
    "input_artifact_id",
    "input_artifact_revision_id",
    "input_sha256",
    "output_artifact_id",
    "output_artifact_revision_id",
    "output_sha256",
    "item_revision_id",
    "graph_snapshot_revision_id",
)


def retry_material_learning_run(
    sessions: sessionmaker[Session], command: RetryMaterialLearningRunCommand
) -> MaterialLearningRetryResult:
    command = RetryMaterialLearningRunCommand.model_validate(command.model_dump(mode="json"))
    identity = (
        "materialrun_"
        + uuid5(
            NAMESPACE_URL, "eom:material-retry:" + content_sha256(command.model_dump(mode="json"))
        ).hex
    )
    with sessions.begin() as session:
        authorize_material_learning(session, command.actor_id)
        source = session.get(MaterialLearningRunRecord, command.run_id)
        if source is None or source.created_by != command.actor_id:
            raise MaterialLearningSourceError("MATERIAL_LEARNING_RUN_NOT_FOUND")
        # One lock order for every predecessor in this material revision, not
        # only for two callers retrying the same old run.
        revision = session.scalar(
            select(LearningMaterialRevisionRecord)
            .where(
                LearningMaterialRevisionRecord.material_revision_id == source.material_revision_id
            )
            .with_for_update()
        )
        material = session.get(LearningMaterialRecord, revision.material_id) if revision else None
        source = session.scalar(
            select(MaterialLearningRunRecord)
            .where(MaterialLearningRunRecord.run_id == command.run_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            source is None
            or revision is None
            or material is None
            or revision.created_by != command.actor_id
            or source.created_by != command.actor_id
            or material.created_by != command.actor_id
            or material.lifecycle_state != "ACTIVE"
            or material.current_revision_id != revision.material_revision_id
        ):
            raise MaterialLearningSourceError("MATERIAL_LEARNING_RUN_NOT_FOUND")
        if source.updated_at != command.expected_updated_at:
            raise MaterialLearningSourceError("MATERIAL_LEARNING_STATE_STALE")
        if source.state not in {"FAILED", "COMPLETED_WITH_EXCEPTIONS"}:
            raise MaterialLearningSourceError("MATERIAL_LEARNING_RETRY_PHASE_INVALID")
        if source.prepared_artifact_revision_id is None:
            raise MaterialLearningSourceError("MATERIAL_LEARNING_PREPARATION_RECOVERY_REQUIRED")
        tasks = tuple(
            session.scalars(
                select(MaterialLearningTaskRecord)
                .where(MaterialLearningTaskRecord.run_id == source.run_id)
                .order_by(MaterialLearningTaskRecord.ordinal)
            )
        )
        failed = tuple(row for row in tasks if row.state == "FAILED")
        if not failed or any(row.task_kind == "PREPARE" for row in failed):
            raise MaterialLearningSourceError("MATERIAL_LEARNING_NO_RETRYABLE_TASKS")
        if any(row.state not in _TERMINAL_TASKS for row in tasks):
            raise MaterialLearningSourceError("MATERIAL_LEARNING_RECONCILIATION_REQUIRED")
        existing = session.get(MaterialLearningRunRecord, identity)
        if existing is not None:
            if existing.predecessor_run_id != source.run_id:
                raise MaterialLearningSourceError("MATERIAL_LEARNING_RETRY_IDENTITY_INVALID")
            return _result(source, existing, tasks, replayed=True)
        if source.attempt >= MAX_MATERIAL_ATTEMPTS or session.scalar(
            select(MaterialLearningRunRecord.run_id)
            .where(
                MaterialLearningRunRecord.material_revision_id == source.material_revision_id,
                MaterialLearningRunRecord.attempt > source.attempt,
            )
            .limit(1)
        ):
            raise MaterialLearningSourceError("MATERIAL_LEARNING_RETRY_SUPERSEDED")
        # The succeeded source extraction remains owned by its original task.
        # Resolve only failed questions requiring that checkpoint; no per-item
        # history query for the book's already-completed units.
        resumable = tuple(
            row for row in failed if row.task_kind == "QUESTION" and row.output_artifact_revision_id
        )
        histories = read_material_task_histories(session, resumable)
        result_owners = {key: history.result_task() for key, history in histories.items()}
        workflows = _quiescent_failed_workflows(
            session,
            failed,
            extra_workflows=tuple(
                row.workflow_id for row in result_owners.values() if row.workflow_id
            ),
        )
        if any(
            row.workflow_id is None
            or workflows.get(row.workflow_id) is None
            or workflows[row.workflow_id].state != "COMPLETED"
            for row in result_owners.values()
        ):
            raise MaterialLearningSourceError("MATERIAL_LEARNING_RECONCILIATION_REQUIRED")
        if any(
            row.task_kind == "QUESTION"
            and row.item_revision_id
            and row.task_id not in result_owners
            for row in failed
        ):
            raise MaterialLearningSourceError("MATERIAL_LEARNING_INHERITED_RESULT_INVALID")
        now = datetime.now(UTC)
        successor = MaterialLearningRunRecord(
            run_id=identity,
            material_revision_id=source.material_revision_id,
            attempt=source.attempt + 1,
            predecessor_run_id=source.run_id,
            state="PROCESSING"
            if any(row.task_kind in {"QUESTION", "EXPLANATION"} for row in tasks)
            else "DISCOVERING",
            next_event_sequence=1,
            created_by=source.created_by,
            prepared_artifact_id=source.prepared_artifact_id,
            prepared_artifact_revision_id=source.prepared_artifact_revision_id,
            prepared_sha256=source.prepared_sha256,
            created_at=now,
            updated_at=now,
        )
        session.add(successor)
        session.flush()
        append_material_event(
            session, successor, event_type="MATERIAL_RETRY_STARTED", prior_state=None
        )
        copies = []
        for row in tasks:
            state = row.state
            inherit = state != "FAILED"
            if state == "FAILED":
                inherit = row.task_id in result_owners
                state = (
                    "REGISTERED"
                    if inherit and row.item_revision_id
                    else "RESULT_READY"
                    if inherit
                    else "PENDING"
                )
            clone = MaterialLearningTaskRecord(
                task_id="materialtask_" + uuid5(NAMESPACE_URL, f"{identity}:{row.task_id}").hex,
                run_id=identity,
                task_kind=row.task_kind,
                unit_key=row.unit_key,
                ordinal=row.ordinal,
                attempt=row.attempt + 1,
                predecessor_task_id=row.task_id,
                state=state,
                execution_lane="MATERIAL_LEARNING",
                error_code=row.error_code if state in {"EXCEPTION", "CANCELLED"} else None,
                created_at=now,
                updated_at=now,
                **{name: getattr(row, name) for name in _ARTIFACT_FIELDS} if inherit else {},
            )
            copies.append(clone)
        session.add_all(copies)
        session.flush()
        for row in copies:
            append_material_event(
                session,
                successor,
                event_type="MATERIAL_TASK_CHECKPOINT_INHERITED"
                if row.state != "PENDING"
                else "MATERIAL_TASK_RETRY_CREATED",
                prior_state=None,
                task=row,
            )
        authorize_material_learning(session, command.actor_id)
        return _result(source, successor, tasks, replayed=False)


def _quiescent_failed_workflows(
    session: Session,
    tasks: tuple[MaterialLearningTaskRecord, ...],
    *,
    extra_workflows: tuple[str, ...] = (),
) -> dict[str, WorkflowInstanceRecord]:
    analysis_ids = {
        identity
        for row in tasks
        for identity in (row.analysis_run_id, row.solution_analysis_run_id)
        if identity
    }
    analyses = (
        tuple(
            session.scalars(
                select(KnowledgeAnalysisRunRecord).where(
                    KnowledgeAnalysisRunRecord.analysis_run_id.in_(analysis_ids)
                )
            )
        )
        if analysis_ids
        else ()
    )
    if {row.analysis_run_id for row in analyses} != analysis_ids or any(
        row.state not in {"ACCEPTED", "FAILED", "REJECTED", "CANCELLED"} for row in analyses
    ):
        raise MaterialLearningSourceError("MATERIAL_LEARNING_RECONCILIATION_REQUIRED")
    workflow_ids = (
        set(extra_workflows)
        | {row.workflow_id for row in tasks if row.workflow_id}
        | {row.workflow_id for row in analyses}
    )
    if not workflow_ids:
        return {}
    workflows = {
        row.workflow_id: row
        for row in session.scalars(
            select(WorkflowInstanceRecord).where(
                WorkflowInstanceRecord.workflow_id.in_(workflow_ids)
            )
        )
    }
    if (
        set(workflows) != workflow_ids
        or any(row.state not in {"COMPLETED", "FAILED", "CANCELLED"} for row in workflows.values())
        or session.scalar(
            select(WorkerLeaseRecord.lease_id)
            .where(
                WorkerLeaseRecord.workflow_id.in_(workflow_ids),
                WorkerLeaseRecord.state.in_({"ACTIVE", "RECONCILING"}),
            )
            .limit(1)
        )
    ):
        raise MaterialLearningSourceError("MATERIAL_LEARNING_RECONCILIATION_REQUIRED")
    return workflows


def _result(
    source: MaterialLearningRunRecord,
    successor: MaterialLearningRunRecord,
    tasks: tuple[MaterialLearningTaskRecord, ...],
    *,
    replayed: bool,
) -> MaterialLearningRetryResult:
    return MaterialLearningRetryResult.model_validate(
        dict(
            predecessor_run_id=source.run_id,
            run_id=successor.run_id,
            state=successor.state,
            reused_tasks=sum(row.state == "COMPLETED" for row in tasks),
            retried_tasks=sum(row.state == "FAILED" for row in tasks),
            replayed=replayed,
        )
    )
