"""Bounded, owner-authorized progress projections; no document bytes or model calls."""

from __future__ import annotations

from collections import defaultdict

from eom_catalog_contracts.material_learning_intake import (
    GetMaterialLearningRunQuery,
    GetMaterialLearningTaskQuery,
    ListMaterialLearningRunsQuery,
    MaterialLearningRunDetail,
    MaterialLearningRunList,
    MaterialLearningRunSummary,
    MaterialLearningTaskDetail,
    MaterialLearningTaskSummary,
)
from eom_orchestrator.database import build_session_factory
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactService
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
from eom_catalog_service.material_task_history import (
    MaterialTaskHistory,
    read_material_task_histories,
)
from eom_catalog_service.material_task_source_read import read_material_task_source
from eom_catalog_service.settings import CatalogSettings


def _task_summary(
    task: MaterialLearningTaskRecord, history: MaterialTaskHistory | None = None
) -> MaterialLearningTaskSummary:
    base = history.analysis_owner() if history else task
    workflow = task.workflow_id
    if history and workflow is None and task.input_artifact_revision_id:
        workflow = next(
            (
                row.workflow_id
                for row in history.tasks
                if row.workflow_id
                and row.input_artifact_revision_id == task.input_artifact_revision_id
            ),
            None,
        )
    return MaterialLearningTaskSummary.model_validate(
        dict(
            task_id=task.task_id,
            ordinal=task.ordinal,
            task_kind=task.task_kind,
            state=task.state,
            workflow_id=workflow,
            item_revision_id=task.item_revision_id,
            analysis_run_id=base.analysis_run_id if base else None,
            graph_snapshot_revision_id=task.graph_snapshot_revision_id,
            error_code=task.error_code,
        )
    )


def _summaries(
    session: Session,
    rows: tuple[tuple[MaterialLearningRunRecord, LearningMaterialRevisionRecord], ...],
) -> tuple[MaterialLearningRunSummary, ...]:
    if not rows:
        return ()
    # One indexed aggregate for the bounded set, not a query per source/run.
    counters: dict[str, list[dict[str, object]]] = defaultdict(list)
    for run_id, state, count in session.execute(
        select(
            MaterialLearningTaskRecord.run_id,
            MaterialLearningTaskRecord.state,
            func.count(MaterialLearningTaskRecord.task_id),
        )
        .where(MaterialLearningTaskRecord.run_id.in_(tuple(run.run_id for run, _ in rows)))
        .group_by(MaterialLearningTaskRecord.run_id, MaterialLearningTaskRecord.state)
        .order_by(MaterialLearningTaskRecord.run_id, MaterialLearningTaskRecord.state)
    ):
        counters[run_id].append({"state": state, "count": count})
    return tuple(
        MaterialLearningRunSummary.model_validate(
            {
                "material_id": revision.material_id,
                "material_revision_id": revision.material_revision_id,
                "run_id": run.run_id,
                "title": revision.title,
                "attempt": run.attempt,
                "predecessor_run_id": run.predecessor_run_id,
                "material_kind": revision.material_kind,
                "state": run.state,
                "task_counts": counters.get(run.run_id, []),
                "error_code": run.error_code,
                "created_at": run.created_at,
                "updated_at": run.updated_at,
            }
        )
        for run, revision in rows
    )


class MaterialLearningReadService:
    def __init__(self, engine: Engine, settings: CatalogSettings | None = None) -> None:
        self.sessions = build_session_factory(engine)
        self.artifacts = CatalogArtifactService(
            engine, settings or CatalogSettings.from_environment()
        )

    def recent(self, query: ListMaterialLearningRunsQuery) -> MaterialLearningRunList:
        query = ListMaterialLearningRunsQuery.model_validate(query.model_dump(mode="json"))
        with self.sessions() as session:
            authorize_material_learning(session, query.actor_id)
            rows = tuple(
                session.execute(
                    select(MaterialLearningRunRecord, LearningMaterialRevisionRecord)
                    .join(
                        LearningMaterialRevisionRecord,
                        LearningMaterialRevisionRecord.material_revision_id
                        == MaterialLearningRunRecord.material_revision_id,
                    )
                    .join(
                        LearningMaterialRecord,
                        LearningMaterialRecord.material_id
                        == LearningMaterialRevisionRecord.material_id,
                    )
                    .where(
                        MaterialLearningRunRecord.created_by == query.actor_id,
                        LearningMaterialRecord.lifecycle_state == "ACTIVE",
                    )
                    .order_by(
                        MaterialLearningRunRecord.created_at.desc(),
                        MaterialLearningRunRecord.run_id.desc(),
                    )
                    .limit(query.limit)
                ).tuples()
            )
            result = MaterialLearningRunList(runs=_summaries(session, rows))
            authorize_material_learning(session, query.actor_id)
            return result

    def inspect(self, query: GetMaterialLearningRunQuery) -> MaterialLearningRunDetail:
        query = GetMaterialLearningRunQuery.model_validate(query.model_dump(mode="json"))
        with self.sessions() as session:
            authorize_material_learning(session, query.actor_id)
            row = (
                session.execute(
                    select(MaterialLearningRunRecord, LearningMaterialRevisionRecord)
                    .join(
                        LearningMaterialRevisionRecord,
                        LearningMaterialRevisionRecord.material_revision_id
                        == MaterialLearningRunRecord.material_revision_id,
                    )
                    .join(
                        LearningMaterialRecord,
                        LearningMaterialRecord.material_id
                        == LearningMaterialRevisionRecord.material_id,
                    )
                    .where(
                        MaterialLearningRunRecord.run_id == query.run_id,
                        MaterialLearningRunRecord.created_by == query.actor_id,
                        LearningMaterialRecord.lifecycle_state == "ACTIVE",
                    )
                )
                .tuples()
                .one_or_none()
            )
            if row is None:
                raise MaterialLearningSourceError("MATERIAL_LEARNING_RUN_NOT_FOUND")
            tasks = tuple(
                session.scalars(
                    select(MaterialLearningTaskRecord)
                    .where(
                        MaterialLearningTaskRecord.run_id == query.run_id,
                        MaterialLearningTaskRecord.ordinal > query.after_ordinal,
                    )
                    .order_by(MaterialLearningTaskRecord.ordinal)
                    .limit(query.limit + 1)
                )
            )
            visible = tasks[: query.limit]
            inherited = tuple(
                task
                for task in visible
                if task.predecessor_task_id
                and row[0].state != "CANCELLED"
                and task.state != "CANCELLED"
            )
            histories = read_material_task_histories(session, inherited)
            result = MaterialLearningRunDetail(
                run=_summaries(session, (row,))[0],
                tasks=tuple(_task_summary(task, histories.get(task.task_id)) for task in visible),
                next_ordinal=visible[-1].ordinal if len(tasks) > query.limit else None,
            )
            authorize_material_learning(session, query.actor_id)
            return result

    def task(self, query: GetMaterialLearningTaskQuery) -> MaterialLearningTaskDetail:
        query = GetMaterialLearningTaskQuery.model_validate(query.model_dump(mode="json"))
        with self.sessions() as session:
            authorize_material_learning(session, query.actor_id)
            task = session.get(MaterialLearningTaskRecord, query.task_id)
            run = session.get(MaterialLearningRunRecord, query.run_id)
            revision = (
                session.get(LearningMaterialRevisionRecord, run.material_revision_id)
                if run
                else None
            )
            material = (
                session.get(LearningMaterialRecord, revision.material_id) if revision else None
            )
            if (
                task is None
                or run is None
                or revision is None
                or material is None
                or task.run_id != run.run_id
                or run.created_by != query.actor_id
                or material.lifecycle_state != "ACTIVE"
                or material.current_revision_id != revision.material_revision_id
            ):
                raise MaterialLearningSourceError("MATERIAL_LEARNING_TASK_NOT_FOUND")
            history = (
                read_material_task_histories(session, (task,))[task.task_id]
                if task.predecessor_task_id
                and run.state != "CANCELLED"
                and task.state != "CANCELLED"
                else None
            )
            location = read_material_task_source(
                session,
                self.artifacts,
                run=run,
                revision=revision,
                task=task,
                operator_id=query.actor_id,
                history=history,
            )
            authorize_material_learning(session, query.actor_id)
            return MaterialLearningTaskDetail(
                run_id=run.run_id,
                task=_task_summary(task, history),
                attempt=task.attempt,
                predecessor_task_id=task.predecessor_task_id,
                printed_label=location.printed_label,
                section_path=location.section_path,
                source_pages=location.source_pages,
            )
