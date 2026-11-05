"""Bounded, owner-authorized progress projections; no document bytes or model calls."""

from __future__ import annotations

from collections import defaultdict

from eom_catalog_contracts.material_learning_intake import (
    GetMaterialLearningRunQuery,
    ListMaterialLearningRunsQuery,
    MaterialLearningRunDetail,
    MaterialLearningRunList,
    MaterialLearningRunSummary,
    MaterialLearningTaskSummary,
)
from eom_orchestrator.database import build_session_factory
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

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
    def __init__(self, engine: Engine) -> None:
        self.sessions = build_session_factory(engine)

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
            result = MaterialLearningRunDetail(
                run=_summaries(session, (row,))[0],
                tasks=tuple(
                    MaterialLearningTaskSummary.model_validate(
                        {
                            "task_id": task.task_id,
                            "ordinal": task.ordinal,
                            "task_kind": task.task_kind,
                            "state": task.state,
                            "workflow_id": task.workflow_id,
                            "item_revision_id": task.item_revision_id,
                            "analysis_run_id": task.analysis_run_id,
                            "graph_snapshot_revision_id": task.graph_snapshot_revision_id,
                            "error_code": task.error_code,
                        }
                    )
                    for task in visible
                ),
                next_ordinal=visible[-1].ordinal if len(tasks) > query.limit else None,
            )
            authorize_material_learning(session, query.actor_id)
            return result
