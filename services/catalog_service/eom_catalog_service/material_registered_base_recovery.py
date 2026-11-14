"""Internal typed scope for one accepted, unusable Material Item base successor.

No wire, queue or mutable recovery registry: task history and the new analysis's
explicit predecessor pin retain the complete immutable handoff.
"""

from dataclasses import dataclass

from eom_catalog_contracts import KnowledgeAnalysisRequestV2, KnowledgeProposalArtifactMember
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_catalog_service.material_learning_models import (
    LearningMaterialRecord,
    LearningMaterialRevisionRecord,
    MaterialLearningEventRecord,
    MaterialLearningRunRecord,
    MaterialLearningTaskRecord,
)
from eom_catalog_service.material_learning_source import authorize_material_learning
from eom_catalog_service.registered_item_solution_base import (
    RegisteredItemSolutionAnchorError,
    RegisteredItemSolutionReferenceError,
)

REGISTERED_BASE_RECOVERY_CODES = frozenset(
    {RegisteredItemSolutionAnchorError.code, RegisteredItemSolutionReferenceError.code}
)


@dataclass(frozen=True, slots=True)
class MaterialRegisteredBaseRecoveryProof:
    task_id: str
    item_revision_id: str
    base_analysis_run_id: str
    request: KnowledgeAnalysisRequestV2
    accepted_result_artifact_id: str
    accepted_result_artifact_revision_id: str
    accepted_result_sha256: str
    proposal_receipt: KnowledgeProposalArtifactMember
    failure_code: str


@dataclass(frozen=True, slots=True)
class CreateMaterialBaseRecoveryCommand:
    """Trusted Python use case input, never a model-supplied execution permission."""

    task_id: str
    predecessor_analysis_run_id: str
    operator_id: str


def lock_material_base_recovery_target(
    session: Session, command: CreateMaterialBaseRecoveryCommand
) -> tuple[MaterialLearningTaskRecord, MaterialLearningRunRecord, MaterialLearningTaskRecord]:
    """Same revision→run ordering as all other Material successor creation."""

    authorize_material_learning(session, command.operator_id)
    task = session.get(MaterialLearningTaskRecord, command.task_id)
    run = session.get(MaterialLearningRunRecord, task.run_id) if task else None
    if run is None:
        raise ValueError("MATERIAL_REGISTERED_BASE_RECOVERY_SCOPE_INVALID")
    revision = session.scalar(
        select(LearningMaterialRevisionRecord)
        .where(LearningMaterialRevisionRecord.material_revision_id == run.material_revision_id)
        .with_for_update()
    )
    run = session.scalar(
        select(MaterialLearningRunRecord)
        .where(MaterialLearningRunRecord.run_id == run.run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    task = session.scalar(
        select(MaterialLearningTaskRecord)
        .where(MaterialLearningTaskRecord.task_id == command.task_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    material = session.get(LearningMaterialRecord, revision.material_id) if revision else None
    previous = session.get(MaterialLearningTaskRecord, task.predecessor_task_id) if task else None
    previous_run = session.get(MaterialLearningRunRecord, previous.run_id) if previous else None
    pins = (
        "input_artifact_id",
        "input_artifact_revision_id",
        "input_sha256",
        "output_artifact_id",
        "output_artifact_revision_id",
        "output_sha256",
        "item_revision_id",
    )
    creating = task is not None and task.analysis_run_id is None
    started = (
        session.scalar(
            select(MaterialLearningEventRecord.event_id).where(
                MaterialLearningEventRecord.run_id == run.run_id,
                MaterialLearningEventRecord.sequence == 1,
                MaterialLearningEventRecord.event_type == "MATERIAL_NATIVE_REFERENCE_RETRY_STARTED",
            )
        )
        if run
        else None
    )
    if (
        revision is None
        or material is None
        or run is None
        or task is None
        or previous is None
        or previous_run is None
        or run.created_by != command.operator_id
        or revision.created_by != command.operator_id
        or material.created_by != command.operator_id
        or material.lifecycle_state != "ACTIVE"
        or material.current_revision_id != run.material_revision_id
        or started is None
        or run.state == "CANCELLED"
        or (creating and run.state not in {"PROCESSING", "WAITING_FOR_CAPACITY", "PAUSED"})
        or task.run_id != run.run_id
        or (creating and task.state not in {"REGISTERED", "ANALYZING"})
        or task.task_kind != "QUESTION"
        or previous.task_kind != task.task_kind
        or previous.state != "FAILED"
        or previous.error_code not in REGISTERED_BASE_RECOVERY_CODES
        or previous_run.created_by != command.operator_id
        or previous_run.state not in {"FAILED", "COMPLETED_WITH_EXCEPTIONS"}
        or previous_run.material_revision_id != run.material_revision_id
        or run.predecessor_run_id != previous.run_id
        or run.attempt != previous_run.attempt + 1
        or task.attempt != previous.attempt + 1
        or task.ordinal != previous.ordinal
        or task.unit_key != previous.unit_key
        or (
            creating
            and (
                task.solution_analysis_run_id is not None
                or task.graph_snapshot_revision_id is not None
            )
        )
        or any(getattr(task, field) != getattr(previous, field) for field in pins)
        or any(getattr(task, field) is None for field in pins)
    ):
        raise ValueError("MATERIAL_REGISTERED_BASE_RECOVERY_SCOPE_INVALID")
    return task, run, previous
