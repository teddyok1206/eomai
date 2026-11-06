"""Atomically bind a material explanation before its Workflow can be claimed."""

from eom_catalog_contracts.material_knowledge_analysis import (
    CreateMaterialKnowledgeAnalysisCommand,
    EducationalDocumentKnowledgeSourceV5,
)
from eom_catalog_contracts.material_learning import MaterialArtifactMember
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from eom_orchestrator.models import ArtifactRevisionRecord
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.material_learning_artifacts import read_material_metadata
from eom_catalog_service.material_learning_models import (
    MaterialLearningRunRecord,
    MaterialLearningTaskRecord,
)


def bind_material_knowledge_analysis(
    session: Session,
    artifacts: CatalogArtifactService,
    *,
    command: CreateMaterialKnowledgeAnalysisCommand,
    source: EducationalDocumentKnowledgeSourceV5,
    analysis: KnowledgeAnalysisRunRecord,
) -> None:
    """Caller owns the analysis/command transaction; no externally visible orphan child."""
    task = session.scalar(
        select(MaterialLearningTaskRecord)
        .where(MaterialLearningTaskRecord.task_id == command.material_task_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    parent = (
        session.get(MaterialLearningRunRecord, task.run_id, populate_existing=True)
        if task
        else None
    )
    revision = (
        session.get(ArtifactRevisionRecord, task.input_artifact_revision_id)
        if task and task.input_artifact_revision_id
        else None
    )
    if (
        task is None
        or parent is None
        or revision is None
        or task.task_kind != "EXPLANATION"
        or parent.state == "CANCELLED"
        or task.state not in {"ANALYZING", "PUBLISHING", "GRAPH_READY", "COMPLETED"}
        or parent.created_by != command.requested_by
        or parent.material_revision_id != source.material_revision_id
        or task.input_artifact_id is None
        or task.input_sha256 is None
        or task.input_artifact_revision_id is None
        or (task.analysis_run_id is not None and task.analysis_run_id != analysis.analysis_run_id)
        or (task.workflow_id is not None and task.workflow_id != analysis.workflow_id)
    ):
        raise ValueError("MATERIAL_KNOWLEDGE_TASK_BINDING_INVALID")
    pointer = MaterialArtifactMember(
        artifact_id=task.input_artifact_id,
        artifact_revision_id=task.input_artifact_revision_id,
        member_path="material/knowledge-command.json",
        schema_ref="eom://schemas/knowledge/create-material-knowledge-analysis/1.0",
        media_type="application/json",
        sha256=task.input_sha256,
        bytes=revision.content_bytes,
    )
    stored = read_material_metadata(
        artifacts,
        pointer,
        CreateMaterialKnowledgeAnalysisCommand,
        schema_ref=pointer.schema_ref,
        member_path=pointer.member_path,
    )
    if stored != command:
        raise ValueError("MATERIAL_KNOWLEDGE_TASK_INPUT_CHANGED")
    task.workflow_id = analysis.workflow_id
    task.analysis_run_id = analysis.analysis_run_id
    session.flush()
