"""Bounded exact checkpoint inheritance, never a replay of a completed child.

The existing task/run PK and predecessor FKs implement linked revision history.
One recursive indexed query serves a batch of roots; callers authorize the actor
and resolve Artifact bytes with their existing source owners.
"""

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from sqlalchemy import literal, select
from sqlalchemy.orm import Session, aliased

from eom_catalog_service.material_learning_models import (
    MaterialLearningRunRecord,
    MaterialLearningTaskRecord,
)

MAX_MATERIAL_ATTEMPTS = 32


@dataclass(frozen=True, slots=True)
class MaterialTaskHistory:
    tasks: tuple[MaterialLearningTaskRecord, ...]

    @property
    def current(self) -> MaterialLearningTaskRecord:
        return self.tasks[0]

    def result_task(self) -> MaterialLearningTaskRecord:
        """An inherited result must pin the same exact input and output members."""
        root = self.current
        for row in self.tasks:
            if (
                row.input_artifact_id,
                row.input_artifact_revision_id,
                row.input_sha256,
                row.output_artifact_id,
                row.output_artifact_revision_id,
                row.output_sha256,
            ) != (
                root.input_artifact_id,
                root.input_artifact_revision_id,
                root.input_sha256,
                root.output_artifact_id,
                root.output_artifact_revision_id,
                root.output_sha256,
            ):
                break
            if row.workflow_id is not None:
                return row
        raise ValueError("MATERIAL_LEARNING_INHERITED_RESULT_INVALID")

    def analysis_owner(self, *, solution: bool = False) -> MaterialLearningTaskRecord | None:
        root = self.current
        for row in self.tasks:
            if (
                row.input_artifact_id,
                row.input_artifact_revision_id,
                row.input_sha256,
                row.item_revision_id,
            ) != (
                root.input_artifact_id,
                root.input_artifact_revision_id,
                root.input_sha256,
                root.item_revision_id,
            ):
                break
            identity = row.solution_analysis_run_id if solution else row.analysis_run_id
            if identity is not None:
                return row
        return None


def read_material_task_histories(
    session: Session, tasks: tuple[MaterialLearningTaskRecord, ...]
) -> Mapping[str, MaterialTaskHistory]:
    if not tasks:
        return MappingProxyType({})
    ids = tuple(row.task_id for row in tasks)
    if len(set(ids)) != len(ids) or len(ids) > 20_000:
        raise ValueError("MATERIAL_LEARNING_HISTORY_BOUND_INVALID")
    lineage = (
        select(
            MaterialLearningTaskRecord.task_id,
            MaterialLearningTaskRecord.predecessor_task_id,
            MaterialLearningTaskRecord.task_id.label("root_id"),
            literal(0).label("depth"),
        )
        .where(MaterialLearningTaskRecord.task_id.in_(ids))
        .cte("material_task_lineage", recursive=True)
    )
    predecessor = aliased(MaterialLearningTaskRecord)
    lineage = lineage.union_all(
        select(
            predecessor.task_id,
            predecessor.predecessor_task_id,
            lineage.c.root_id,
            lineage.c.depth + 1,
        )
        .join(lineage, predecessor.task_id == lineage.c.predecessor_task_id)
        .where(lineage.c.depth < MAX_MATERIAL_ATTEMPTS - 1)
    )
    groups: dict[str, list[tuple[MaterialLearningTaskRecord, MaterialLearningRunRecord]]] = (
        defaultdict(list)
    )
    rows = session.execute(
        select(lineage.c.root_id, MaterialLearningTaskRecord, MaterialLearningRunRecord)
        .select_from(lineage)
        .join(MaterialLearningTaskRecord, MaterialLearningTaskRecord.task_id == lineage.c.task_id)
        .join(
            MaterialLearningRunRecord,
            MaterialLearningRunRecord.run_id == MaterialLearningTaskRecord.run_id,
        )
        .order_by(lineage.c.root_id, lineage.c.depth)
        .execution_options(populate_existing=True)
    )
    for root_id, task, run in rows:
        groups[root_id].append((task, run))
    if set(groups) != set(ids):
        raise ValueError("MATERIAL_LEARNING_HISTORY_MISSING")
    result = {}
    for key, chain in groups.items():
        first, parent = chain[0]
        if first.task_id != key or chain[-1][0].predecessor_task_id is not None:
            raise ValueError("MATERIAL_LEARNING_HISTORY_INCOMPLETE")
        seen = set()
        for index, (row, run) in enumerate(chain):
            if (
                row.task_id in seen
                or row.task_kind != first.task_kind
                or row.unit_key != first.unit_key
                or row.ordinal != first.ordinal
                or row.attempt != first.attempt - index
                or run.material_revision_id != parent.material_revision_id
                or run.created_by != parent.created_by
                or run.attempt != parent.attempt - index
                or run.state == "CANCELLED"
                or (index and chain[index - 1][0].predecessor_task_id != row.task_id)
                or (index and chain[index - 1][1].predecessor_run_id != run.run_id)
            ):
                raise ValueError("MATERIAL_LEARNING_HISTORY_SOURCE_MISMATCH")
            seen.add(row.task_id)
        result[key] = MaterialTaskHistory(tuple(row for row, _run in chain))
    return MappingProxyType(result)
