"""Explicit source-position reads, separate from routine progress metadata polls."""

from dataclasses import dataclass

from eom_catalog_contracts.material_knowledge_analysis import CreateMaterialKnowledgeAnalysisCommand
from eom_catalog_contracts.material_learning import MaterialDiscoveryWork, MaterialExtractionWork
from eom_catalog_contracts.material_learning_intake import MaterialTaskSourcePage
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.material_intake_read import material_intake_pointer, read_material_intake
from eom_catalog_service.material_knowledge_source import (
    reauthorize_material_document_source,
    resolve_material_document_source,
)
from eom_catalog_service.material_learning_artifacts import (
    pin_material_primary,
    read_material_metadata,
)
from eom_catalog_service.material_learning_authorization import (
    CatalogMaterialLearningSourceAuthorizer,
)
from eom_catalog_service.material_learning_coordinator import read_material_discovery_plan
from eom_catalog_service.material_learning_models import (
    LearningMaterialRevisionRecord,
    MaterialLearningRunRecord,
    MaterialLearningTaskRecord,
)
from eom_catalog_service.material_learning_source import (
    MaterialLearningSourceError,
    authorize_material_learning,
)
from eom_catalog_service.material_task_history import MaterialTaskHistory


@dataclass(frozen=True, slots=True)
class MaterialTaskSourceLocation:
    printed_label: str | None
    section_path: tuple[str, ...]
    source_pages: tuple[MaterialTaskSourcePage, ...]


def read_material_task_source(
    session: Session,
    artifacts: CatalogArtifactService,
    *,
    run: MaterialLearningRunRecord,
    revision: LearningMaterialRevisionRecord,
    task: MaterialLearningTaskRecord,
    operator_id: str,
    history: MaterialTaskHistory | None,
) -> MaterialTaskSourceLocation:
    if (
        task.run_id != run.run_id
        or run.created_by != operator_id
        or revision.material_revision_id != run.material_revision_id
    ):
        raise MaterialLearningSourceError("MATERIAL_LEARNING_TASK_NOT_FOUND")
    origin = task
    if history and task.input_artifact_revision_id:
        origin = next(
            (
                row
                for row in history.tasks
                if row.input_artifact_revision_id == task.input_artifact_revision_id
                and row.workflow_id is not None
            ),
            task,
        )
    pages: tuple[MaterialTaskSourcePage, ...] = ()
    label: str | None = None
    sections: tuple[str, ...] = ()
    if origin.input_artifact_revision_id is None and origin.task_kind == "QUESTION":
        # Structural exceptions can precede extraction input creation.
        # Read the original discovered unit instead of inventing a page
        # or polling every result for routine status refreshes.
        plan = read_material_discovery_plan(
            session, artifacts, run_id=run.run_id, operator_id=operator_id
        )
        unit = plan.by_unit.get(task.unit_key)
        if unit is None:
            raise MaterialLearningSourceError("MATERIAL_LEARNING_TASK_SOURCE_MISSING")
        label, sections = unit.unit.printed_label, unit.unit.section_path
        pages = tuple(
            MaterialTaskSourcePage(
                source_role=role,
                original_filename=unit.source.original_filename,
                physical_page=number,
            )
            for role, number in sorted(
                {(region.source_role, region.physical_page) for region in unit.unit.anchors}
            )
        )
    if origin.input_artifact_revision_id and origin.task_kind != "PREPARE":
        if origin.input_artifact_id is None or origin.input_sha256 is None:
            raise MaterialLearningSourceError("MATERIAL_LEARNING_INPUT_MISSING")
        explanation = origin.task_kind == "EXPLANATION"
        schema = (
            "eom://schemas/knowledge/create-material-knowledge-analysis/1.0"
            if explanation
            else "eom://schemas/material-learning/"
            + ("discovery-work/1.0" if origin.task_kind == "DISCOVER" else "extraction-work/1.0")
        )
        member = "material/knowledge-command.json" if explanation else "material/work.json"
        pointer = pin_material_primary(
            session,
            ArtifactMemberPointer(
                artifact_id=origin.input_artifact_id,
                artifact_revision_id=origin.input_artifact_revision_id,
                member_path=member,
                schema_ref=schema,
                media_type="application/json",
                sha256=origin.input_sha256,
            ),
        ).pointer
        if explanation:
            command = read_material_metadata(
                artifacts,
                pointer,
                CreateMaterialKnowledgeAnalysisCommand,
                schema_ref=schema,
                member_path=member,
            )
            if command.material_task_id != origin.task_id or command.requested_by != operator_id:
                raise MaterialLearningSourceError("MATERIAL_LEARNING_SOURCE_INPUT_MISMATCH")
            source = resolve_material_document_source(
                session,
                artifacts,
                document_revision_id=command.source.document_revision_id,
                source_class=command.source.source_class,
                first_physical_page=command.source.first_physical_page,
                last_physical_page=command.source.last_physical_page,
                selected_regions=command.source.selected_regions,
                curriculum_unit_keys=command.source.curriculum_unit_keys,
            )
            if source.material_revision_id != run.material_revision_id:
                raise MaterialLearningSourceError("MATERIAL_LEARNING_SOURCE_INPUT_MISMATCH")
            reauthorize_material_document_source(
                session, artifacts, operator_id=operator_id, source=source
            )
            # The source's original filename is not an identity; resolve
            # the enclosing intake before presenting it below.
            filenames = _filenames(session, revision, artifacts, operator_id=operator_id)
            locations = {
                (region.source_role, region.physical_page)
                for region in command.source.selected_regions
            }
        else:
            model: type[MaterialDiscoveryWork | MaterialExtractionWork] = (
                MaterialDiscoveryWork if origin.task_kind == "DISCOVER" else MaterialExtractionWork
            )
            work = read_material_metadata(
                artifacts, pointer, model, schema_ref=schema, member_path=member
            )
            if (
                work.task_id != origin.task_id
                or work.material_revision_id != run.material_revision_id
            ):
                raise MaterialLearningSourceError("MATERIAL_LEARNING_SOURCE_INPUT_MISMATCH")
            CatalogMaterialLearningSourceAuthorizer(
                artifacts.engine, artifacts.settings
            ).reauthorize(session, operator_id=operator_id, work=work)
            filenames = {source.source_role: source.original_filename for source in work.sources}
            if isinstance(work, MaterialExtractionWork):
                label, sections = work.question.printed_label, work.question.section_path
                locations = {
                    (region.source_role, region.physical_page) for region in work.question.anchors
                }
            else:
                locations = {(page.source_role, page.physical_page) for page in work.core_pages}
        pages = tuple(
            MaterialTaskSourcePage(
                source_role=role, original_filename=filenames[role], physical_page=number
            )
            for role, number in sorted(locations)
        )
    return MaterialTaskSourceLocation(label, sections, pages)


def _filenames(
    session: Session,
    revision: LearningMaterialRevisionRecord,
    artifacts: CatalogArtifactService,
    *,
    operator_id: str,
) -> dict[str, str]:
    if revision.created_by != operator_id:
        raise MaterialLearningSourceError("MATERIAL_LEARNING_SOURCE_AUTHORIZATION_FAILED")
    pointer = material_intake_pointer(
        session,
        artifact_id=revision.manifest_artifact_id,
        revision_id=revision.manifest_artifact_revision_id,
        sha256=revision.manifest_sha256,
    )
    intake = read_material_intake(
        artifacts,
        pointer,
        authorize=lambda: authorize_material_learning(session, operator_id),
    )
    if (
        intake.requested_by != operator_id
        or intake.material_revision_id != revision.material_revision_id
    ):
        raise MaterialLearningSourceError("MATERIAL_LEARNING_SOURCE_INPUT_MISMATCH")
    return {
        selection.source_role: selection.source_upload.original_filename
        for selection in intake.sources
    }
