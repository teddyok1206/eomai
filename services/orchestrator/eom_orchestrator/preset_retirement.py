"""Bounded maintenance for obsolete presets and unreferenced settings.

The caller supplies an exact reviewed scope. No cascade to items, analyses, runs,
evaluations or artifact bytes is allowed. PostgreSQL foreign keys remain enabled.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from eom_workflow.feature_model_settings import OBSOLETE_PRESET_KEYS
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from eom_orchestrator.control_models import (
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
    ResolvedExecutionPlanRecord,
    WorkerLeaseRecord,
)
from eom_orchestrator.control_service import LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID, ControlPlaneError
from eom_orchestrator.metadata_reset_transaction import MetadataResetTransaction
from eom_orchestrator.models import Base
from eom_orchestrator.preset_lifecycle import deprecate_execution_preset
from eom_orchestrator.preset_model_selection import validated_preset


@dataclass(frozen=True)
class PresetRevisionToRemove:
    preset_key: str
    revision_id: str
    sha256: str


@dataclass(frozen=True)
class PresetRetirementResult:
    retired_keys: tuple[str, ...]
    deleted_revision_ids: tuple[str, ...]
    already_deleted_ids: tuple[str, ...]


_REVISION_REFERENCES = (
    ("execution_preset_evaluations", "evaluated_preset_revision_id"),
    ("execution_preset_validations", "preset_revision_id"),
    ("execution_preset_validations", "base_revision_id"),
    ("resolved_execution_plans", "preset_revision_id"),
    ("knowledge_analysis_runs", "preset_revision_id"),
    ("knowledge_analysis_batches", "preset_revision_id"),
    ("execution_presets", "current_revision_id"),
)


def referenced_preset_revisions(session: Session, ids: tuple[str, ...]) -> frozenset[str]:
    """Seven bounded indexed queries, not a per-revision history scan."""
    if not ids:
        return frozenset()
    referenced: set[str] = set()
    for table_name, column_name in _REVISION_REFERENCES:
        table = Base.metadata.tables.get(table_name)
        if table is None:
            raise ControlPlaneError(
                "CONTROL_RETIREMENT_COMPOSITION_MISSING", "owner composition missing"
            )
        column = table.c[column_name]
        referenced.update(session.scalars(select(column).where(column.in_(ids))))
    return frozenset(referenced)


def retire_obsolete_presets(
    session: Session,
    *,
    current_pins: tuple[PresetRevisionToRemove, ...],
    unused_revisions: tuple[PresetRevisionToRemove, ...],
    operator_id: str,
    changed_at: datetime,
) -> PresetRetirementResult:
    """Run inside the maintenance owner's transaction; stale/busy scope rolls back all."""
    if (
        not operator_id
        or len(current_pins) > len(OBSOLETE_PRESET_KEYS)
        or len(unused_revisions) > 256
    ):
        raise ControlPlaneError("CONTROL_RETIREMENT_SCOPE_INVALID", "bounded scope required")
    if len({v.preset_key for v in current_pins}) != len(current_pins) or len(
        {v.revision_id for v in unused_revisions}
    ) != len(unused_revisions):
        raise ControlPlaneError("CONTROL_RETIREMENT_SCOPE_INVALID", "duplicate scope")
    if any(v.preset_key not in OBSOLETE_PRESET_KEYS for v in current_pins):
        raise ControlPlaneError("CONTROL_RETIREMENT_SCOPE_INVALID", "current feature cannot retire")
    session.execute(select(func.pg_advisory_xact_lock(LEGACY_ITEM_LEARNING_CONTROL_LOCK_ID)))
    keys = sorted({v.preset_key for v in (*current_pins, *unused_revisions)})
    logicals = {
        v.preset_key: v
        for v in session.scalars(
            select(ExecutionPresetRecord)
            .where(ExecutionPresetRecord.preset_key.in_(keys))
            .order_by(ExecutionPresetRecord.preset_key)
            .with_for_update()
        )
    }
    retiring = []
    for pin in current_pins:
        logical = logicals.get(pin.preset_key)
        if logical is None or logical.current_revision_id != pin.revision_id:
            raise ControlPlaneError("CONTROL_RETIREMENT_BASE_STALE", "current pointer changed")
        row = session.get(ExecutionPresetRevisionRecord, pin.revision_id)
        if row is None or validated_preset(row).content_sha256 != pin.sha256:
            raise ControlPlaneError("CONTROL_RETIREMENT_BASE_STALE", "current hash changed")
        retiring.append(logical)
    # Do not retire an executable old workflow or a held physical worker lease.
    ids = tuple(v.preset_id for v in retiring)
    workflows = Base.metadata.tables.get("workflow_instances")
    if workflows is None:
        raise ControlPlaneError(
            "CONTROL_RETIREMENT_COMPOSITION_MISSING", "workflow composition missing"
        )
    if ids and (
        session.scalar(
            select(ResolvedExecutionPlanRecord.plan_id)
            .join(workflows, workflows.c.workflow_id == ResolvedExecutionPlanRecord.workflow_id)
            .where(
                ResolvedExecutionPlanRecord.preset_id.in_(ids),
                workflows.c.state.not_in(("COMPLETED", "FAILED", "CANCELLED")),
            )
            .limit(1)
        )
        or session.scalar(
            select(WorkerLeaseRecord.lease_id)
            .join(
                ResolvedExecutionPlanRecord,
                ResolvedExecutionPlanRecord.workflow_id == WorkerLeaseRecord.workflow_id,
            )
            .where(
                ResolvedExecutionPlanRecord.preset_id.in_(ids),
                WorkerLeaseRecord.state.in_(("ACTIVE", "RECONCILING")),
            )
            .limit(1)
        )
    ):
        raise ControlPlaneError("CONTROL_RETIREMENT_BUSY", "old work is still executable")
    revision_ids = tuple(v.revision_id for v in unused_revisions)
    if referenced_preset_revisions(session, revision_ids):
        raise ControlPlaneError("CONTROL_RETIREMENT_REFERENCED", "history references revision")
    removed, absent = [], []
    for pin in unused_revisions:
        row = session.get(ExecutionPresetRevisionRecord, pin.revision_id)
        if row is None:
            absent.append(pin.revision_id)
            continue
        logical = logicals.get(pin.preset_key)
        if (
            logical is None
            or row.preset_id != logical.preset_id
            or row.state not in ("DRAFT", "RELEASED")
            or validated_preset(row).content_sha256 != pin.sha256
        ):
            raise ControlPlaneError("CONTROL_RETIREMENT_REVISION_STALE", "revision pointer differs")
        removed.append(pin.revision_id)
    if removed:
        # Reuse the existing DB-owner maintenance boundary, scoped to these two
        # tables only. FK constraints stay enabled; trigger DDL rolls back with
        # this transaction. Runtime API/worker roles cannot perform this operation.
        session.flush()
        raw = session.connection().connection.driver_connection
        if raw is None:
            raise ControlPlaneError("CONTROL_RETIREMENT_OWNER_REQUIRED", "owner connection missing")
        with raw.cursor() as cursor:
            owner = MetadataResetTransaction(cursor)
            tables = ("execution_preset_revisions", "execution_preset_role_policies")
            with owner.owner_mutations(tables, tuple((t, t + "_immutable") for t in tables)):
                for revision_id in removed:
                    session.delete(session.get(ExecutionPresetRevisionRecord, revision_id))
                session.flush()
    for logical in retiring:
        deprecate_execution_preset(
            session,
            preset_id=logical.preset_id,
            deprecated_by=operator_id,
            deprecated_at=changed_at,
        )
    session.flush()
    return PresetRetirementResult(
        tuple(v.preset_key for v in retiring), tuple(removed), tuple(absent)
    )
