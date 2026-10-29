"""Bounded metadata capture for the existing completed-proposal validator."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from threading import get_ident
from types import MappingProxyType

from eom_catalog_contracts.external_item_learning_authorization import (
    ExternalItemLearningRoleSelection,
)
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from sqlalchemy import select
from sqlalchemy.orm import Session, SessionTransaction

MAX_CREATIVE_REPORT_CAPTURE = 16


@dataclass(frozen=True, slots=True)
class CreativeProposalRows:
    workflow: WorkflowInstanceRecord | None
    step: WorkflowStepRunRecord | None
    plan: ResolvedExecutionPlanRecord | None
    job: JobRecord | None
    result_revision: ArtifactRevisionRecord | None


@dataclass(frozen=True, slots=True)
class CreativeProposalReadSet:
    """No source grant or alternative validator; pinned to this root transaction."""

    _rows: Mapping[ExternalItemLearningRoleSelection, CreativeProposalRows]
    _session: Session = field(repr=False, compare=False)
    _transaction: SessionTransaction = field(repr=False, compare=False)
    _thread: int = field(repr=False, compare=False)

    def for_selection(
        self, session: Session, selection: ExternalItemLearningRoleSelection
    ) -> CreativeProposalRows:
        if (
            session is not self._session
            or get_ident() != self._thread
            or session.get_transaction() is not self._transaction
            or not self._transaction.is_active
            or session.in_nested_transaction()
            or selection not in self._rows
        ):
            raise ValueError("CREATIVE_PROPOSAL_READ_SET_INVALID")
        return self._rows[selection]


def capture_creative_proposal_read_set(
    session: Session, selections: tuple[ExternalItemLearningRoleSelection, ...]
) -> CreativeProposalReadSet:
    """Five ordered indexed metadata queries per <=16 sources, not five per Item.

    Shared row locks preserve completion/plan/Job evidence until source admission
    and Artifact checks finish in the caller's root transaction. Missing rows
    remain explicit None values for the original validator's stable errors.
    """
    if (
        type(selections) is not tuple
        or not 1 <= len(selections) <= MAX_CREATIVE_REPORT_CAPTURE
        or len(set(selections)) != len(selections)
        or session.in_nested_transaction()
    ):
        raise ValueError("CREATIVE_PROPOSAL_READ_SET_INVALID")
    selections = tuple(
        ExternalItemLearningRoleSelection.model_validate(value.model_dump(mode="json"))
        for value in selections
    )

    workflows = {
        row.workflow_id: row
        for row in session.scalars(
            select(WorkflowInstanceRecord)
            .where(
                WorkflowInstanceRecord.workflow_id.in_(
                    tuple(value.workflow_id for value in selections)
                )
            )
            .order_by(WorkflowInstanceRecord.workflow_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
    }
    steps = {
        row.step_run_id: row
        for row in session.scalars(
            select(WorkflowStepRunRecord)
            .where(
                WorkflowStepRunRecord.step_run_id.in_(
                    tuple(value.step_run_id for value in selections)
                )
            )
            .order_by(WorkflowStepRunRecord.step_run_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
    }
    plans = {
        row.plan_id: row
        for row in session.scalars(
            select(ResolvedExecutionPlanRecord)
            .where(
                ResolvedExecutionPlanRecord.plan_id.in_(
                    tuple(value.plan_id for value in selections)
                )
            )
            .order_by(ResolvedExecutionPlanRecord.plan_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
    }
    jobs = {
        row.job_id: row
        for row in session.scalars(
            select(JobRecord)
            .where(
                JobRecord.job_id.in_(
                    tuple(row.platform_job_id for row in steps.values() if row.platform_job_id)
                )
            )
            .order_by(JobRecord.job_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
    }
    revisions = {
        row.revision_id: row
        for row in session.scalars(
            select(ArtifactRevisionRecord)
            .where(
                ArtifactRevisionRecord.revision_id.in_(
                    tuple(row.revision_id for row in jobs.values() if row.revision_id)
                )
            )
            .order_by(ArtifactRevisionRecord.revision_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
    }
    transaction = session.get_transaction()
    if transaction is None:
        raise ValueError("CREATIVE_PROPOSAL_READ_SET_INVALID")
    rows = {}
    for selection in selections:
        step = steps.get(selection.step_run_id)
        job = jobs.get(step.platform_job_id) if step is not None and step.platform_job_id else None
        rows[selection] = CreativeProposalRows(
            workflows.get(selection.workflow_id),
            step,
            plans.get(selection.plan_id),
            job,
            revisions.get(job.revision_id) if job is not None and job.revision_id else None,
        )
    return CreativeProposalReadSet(MappingProxyType(rows), session, transaction, get_ident())
