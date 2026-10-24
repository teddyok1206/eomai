"""Shared SQL admission predicates for immutable capability snapshot reads."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.sql.elements import ColumnElement

from eom_orchestrator.control_models import (
    CodexAuthAssignmentRevisionRecord,
    CodexAuthBindingRecord,
    CodexCapabilitySnapshotRecord,
)


def current_assignment_snapshot_clause() -> ColumnElement[bool]:
    """Legacy NULL assignments stay supported; never reuse a preceding account's proof.

    Existing V1 snapshot bytes remain immutable. Assignment time is resolved by PK;
    a missing assigned revision yields SQL NULL and fails closed.
    """

    assigned_at = (
        select(CodexAuthAssignmentRevisionRecord.assigned_at)
        .where(
            CodexAuthAssignmentRevisionRecord.assignment_revision_id
            == CodexAuthBindingRecord.current_assignment_revision_id
        )
        .correlate(CodexAuthBindingRecord)
        .scalar_subquery()
    )
    return or_(
        CodexAuthBindingRecord.current_assignment_revision_id.is_(None),
        CodexCapabilitySnapshotRecord.observed_at >= assigned_at,
    )


def latest_binding_snapshot_clause() -> ColumnElement[bool]:
    """Do not fall back to an older snapshot merely because it contains a requested model."""

    snapshots = CodexCapabilitySnapshotRecord.__table__.alias("latest_binding_capability")
    latest_id = (
        select(snapshots.c.capability_snapshot_id)
        .where(snapshots.c.binding_id == CodexAuthBindingRecord.binding_id)
        .order_by(snapshots.c.observed_at.desc(), snapshots.c.capability_snapshot_id.desc())
        .limit(1)
        .correlate(CodexAuthBindingRecord)
        .scalar_subquery()
    )
    return CodexCapabilitySnapshotRecord.capability_snapshot_id == latest_id
