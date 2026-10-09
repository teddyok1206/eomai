"""Resolve bounded review-correction and pre-commit retry lineage, without latest fallback."""

from __future__ import annotations

from itertools import pairwise

from eom_orchestrator.models import JobRecord
from eom_workflow import (
    ArtifactPointer,
    WorkflowReviewCorrectionDirective,
    WorkflowReviewEscalationDirective,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_workflow_runner.models import WorkflowEventRecord, WorkflowStepRunRecord
from eom_workflow_runner.state_machine import StepState


def validate_review_correction_step_binding(
    session: Session,
    *,
    step: WorkflowStepRunRecord,
    directive: WorkflowReviewCorrectionDirective,
) -> tuple[ArtifactPointer, ...]:
    """Resolve at most ten indexed attempts; infrastructure retries do not consume a proof.

    The original directive remains immutable. A later attempt is admissible only through the
    existing supersession links and append-only pre-commit retry events, not by an attempt >= test.
    Catalog owns approved Artifact/media/hash/receipt resolution at materialization boundaries.
    """

    raw_directive = directive.model_dump(mode="json")
    if (
        step.workflow_id != directive.workflow_id
        or step.step_key != "review"
        or step.worker_role != "review"
        or step.result_schema != "review-result@12.0"
        or not directive.next_attempt <= step.attempt <= 10
        or step.input_pointer_manifest.get("review_correction_directive") != raw_directive
    ):
        raise ValueError("review correction is not bound to the exact review step")
    rows = session.scalars(
        select(WorkflowStepRunRecord)
        .where(
            WorkflowStepRunRecord.workflow_id == step.workflow_id,
            WorkflowStepRunRecord.step_key == "review",
            WorkflowStepRunRecord.attempt.between(directive.source_attempt, step.attempt),
        )
        .order_by(WorkflowStepRunRecord.attempt)
    ).all()
    if (
        len(rows) != step.attempt - directive.source_attempt + 1
        or rows[-1].step_run_id != step.step_run_id
        or rows[-1].input_pointer_manifest != step.input_pointer_manifest
    ):
        raise ValueError("review correction attempt chain is incomplete or changed")
    source = rows[0]
    if (
        source.state != StepState.FAILED.value
        or source.output_pointer_manifest != directive.source_review.model_dump(mode="json")
        or source.platform_job_id != directive.source_review.job_id
        or source.error_code != directive.issue.code
    ):
        raise ValueError("review correction source is not the exact rejected review")
    prior = source.input_pointer_manifest.get("review_correction_directive")
    if directive.pass_number == 2:
        if prior is not None:
            raise ValueError("second proof cannot reset a prior correction")
    else:
        prior_directive = WorkflowReviewCorrectionDirective.model_validate(prior)
        if (
            prior_directive.pass_number != 2
            or prior_directive.workflow_id != directive.workflow_id
            or prior_directive.reviewed_authoring != directive.reviewed_authoring
            or prior_directive.review_pass != directive.review_pass
        ):
            raise ValueError("third proof does not continue the exact second proof")
        # Only two correction levels exist, so recursive resolution is strictly bounded.
        validate_review_correction_step_binding(session, step=source, directive=prior_directive)
    source_job = session.get(JobRecord, directive.source_review.job_id)
    if (
        source_job is None
        or source_job.status != "SUCCEEDED"
        or source_job.logical_artifact_id != directive.source_review.logical_artifact_id
        or source_job.revision_id != directive.source_review.revision_id
    ):
        raise ValueError("review correction source job is not committed")

    origin = rows[1]
    input_keys = ("upstream_artifacts", "review_escalation_directive")
    if any(
        source.input_pointer_manifest.get(key) != origin.input_pointer_manifest.get(key)
        for key in input_keys
    ):
        raise ValueError("review correction changed the rejected review's upstream or tier pins")
    for previous, successor in pairwise(rows):
        if previous.superseded_by_step_run_id != successor.step_run_id:
            raise ValueError("review correction supersession link is absent")
        if successor.input_pointer_manifest.get(
            "review_correction_directive"
        ) != raw_directive or any(
            successor.input_pointer_manifest.get(key) != origin.input_pointer_manifest.get(key)
            for key in input_keys
        ):
            raise ValueError("review correction immutable inputs changed")
        if previous is source:
            continue
        if previous.state != StepState.FAILED.value or previous.output_pointer_manifest is not None:
            raise ValueError("review correction retry was not pre-commit")
        retry_event = session.scalar(
            select(WorkflowEventRecord).where(
                WorkflowEventRecord.workflow_id == step.workflow_id,
                WorkflowEventRecord.event_type == "STEP_RETRY_SCHEDULED",
                WorkflowEventRecord.payload["failed_step_run_id"].as_string()
                == previous.step_run_id,
                WorkflowEventRecord.payload["next_step_run_id"].as_string()
                == successor.step_run_id,
            )
        )
        failed_job = session.get(JobRecord, previous.platform_job_id)
        if (
            retry_event is None
            or failed_job is None
            or failed_job.status != "FAILED"
            or retry_event.payload.get("failed_job_id") != failed_job.job_id
            or retry_event.payload.get("error_code") != failed_job.error_code
        ):
            raise ValueError("review correction retry has no supported pre-commit evidence")

    raw_upstream = step.input_pointer_manifest.get("upstream_artifacts")
    if not isinstance(raw_upstream, list):
        raise ValueError("review correction upstream pins are absent")
    pointers = tuple(ArtifactPointer.model_validate(value) for value in raw_upstream)
    by_key = {pointer.step_key: pointer for pointer in pointers}
    if (
        len(by_key) != len(pointers)
        or by_key.get("authoring") != directive.reviewed_authoring
        or directive.source_review in pointers
    ):
        raise ValueError("review correction upstream pins differ from the reviewed draft")
    raw_escalation = step.input_pointer_manifest.get("review_escalation_directive")
    if directive.review_pass == "PRIMARY":
        if raw_escalation is not None or "review" in by_key:
            raise ValueError("primary review correction changed execution tier")
    else:
        escalation = WorkflowReviewEscalationDirective.model_validate(raw_escalation)
        if (
            escalation.workflow_id != directive.workflow_id
            or escalation.reviewed_authoring != directive.reviewed_authoring
            or by_key.get("review") != escalation.source_review
            or escalation.next_attempt > directive.source_attempt
        ):
            raise ValueError("escalated review correction changed primary review pins")
    return pointers
