"""Resolve uploaded document facts; caller separately enforces actor/access policy.

This shares EducationalDocument, Artifact and bounded page membership owners with
intake. It never asserts purchased textbook rights or creates an alternate source.
"""

from typing import Literal

from eom_catalog_contracts.knowledge import (
    KnowledgeAnalysisDocumentDependencyV3,
    KnowledgeAnalysisOriginalSourceMemberV3,
)
from eom_catalog_contracts.material_knowledge_analysis import (
    EducationalDocumentKnowledgeSourceV5,
    MaterialKnowledgePageMember,
)
from eom_catalog_contracts.material_learning import (
    MaterialArtifactMember,
    MaterialLearningRights,
    MaterialSourceRegion,
)
from eom_catalog_contracts.material_learning_preparation import (
    material_document_source_class,
)
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactReader, CatalogArtifactService
from eom_catalog_service.educational_material_registration import read_material_document_revision
from eom_catalog_service.material_intake_read import material_intake_pointer, read_material_intake
from eom_catalog_service.material_learning_artifacts import read_material_metadata
from eom_catalog_service.material_learning_models import (
    LearningMaterialRecord,
    LearningMaterialRevisionRecord,
)
from eom_catalog_service.material_learning_source import (
    MaterialLearningSourceError,
    authorize_material_learning,
)
from eom_catalog_service.material_page_source_read import (
    ResolvedMaterialPage,
    read_material_source_pages,
)
from eom_catalog_service.models import EducationalDocumentRecord, EducationalDocumentRevisionRecord


def reauthorize_material_document_source(
    session: Session,
    artifacts: CatalogArtifactService,
    *,
    operator_id: str,
    source: EducationalDocumentKnowledgeSourceV5,
) -> None:
    """Actual uploader/current authority, separate from canonical fact resolution."""
    authorize_material_learning(session, operator_id)
    revision = session.get(LearningMaterialRevisionRecord, source.material_revision_id)
    if (
        revision is None
        or revision.created_by != operator_id
        or resolve_material_document_source(
            session,
            artifacts,
            document_revision_id=source.document_revision_id,
            source_class=source.source_class,
            first_physical_page=source.first_physical_page,
            last_physical_page=source.last_physical_page,
            selected_regions=source.selected_regions,
            curriculum_unit_keys=source.curriculum_unit_keys,
        )
        != source
    ):
        raise MaterialLearningSourceError("MATERIAL_LEARNING_SOURCE_AUTHORIZATION_FAILED")


def resolve_material_document_source(
    session: Session,
    artifacts: CatalogArtifactReader,
    *,
    document_revision_id: str,
    source_class: str,
    first_physical_page: int,
    last_physical_page: int,
    selected_regions: tuple[MaterialSourceRegion, ...],
    curriculum_unit_keys: tuple[str, ...],
) -> EducationalDocumentKnowledgeSourceV5:
    if (
        not 1 <= first_physical_page <= last_physical_page <= 2000
        or last_physical_page - first_physical_page >= 32
    ):
        raise MaterialLearningSourceError("MATERIAL_LEARNING_KNOWLEDGE_RANGE_INVALID")
    row = session.get(EducationalDocumentRevisionRecord, document_revision_id)
    document_row = (
        session.get(EducationalDocumentRecord, row.document_id, populate_existing=True)
        if row
        else None
    )
    if (
        row is None
        or document_row is None
        or row.revision_state != "APPROVED"
        or document_row.lifecycle_state != "ACTIVE"
        or document_row.current_revision_id != row.document_revision_id
    ):
        raise MaterialLearningSourceError("MATERIAL_LEARNING_DOCUMENT_NOT_FOUND")
    document, revision_manifest = read_material_document_revision(
        session, artifacts, document_revision_id
    )
    material = session.get(LearningMaterialRecord, document.material_id, populate_existing=True)
    revision = session.get(LearningMaterialRevisionRecord, document.material_revision_id)
    if (
        material is None
        or revision is None
        or material.lifecycle_state != "ACTIVE"
        or revision.material_id != material.material_id
        or material.created_by != revision.created_by
        or document.registered_by != revision.created_by
        or document.source_class != source_class
        or document.document_kind != document_row.document_kind
        or source_class != material_document_source_class(document.document_kind)
        or (
            document.source.artifact_id,
            document.source.artifact_revision_id,
            document.source.sha256,
            document.source.bytes,
            document.source_page_count,
        )
        != (
            row.source_artifact_id,
            row.source_artifact_revision_id,
            row.source_sha256,
            row.source_size_bytes,
            row.source_page_count,
        )
        or document.source_page_count < last_physical_page
    ):
        raise MaterialLearningSourceError("MATERIAL_LEARNING_DOCUMENT_INPUT_MISMATCH")
    intake_pointer = material_intake_pointer(
        session,
        artifact_id=revision.manifest_artifact_id,
        revision_id=revision.manifest_artifact_revision_id,
        sha256=revision.manifest_sha256,
    )

    def require_source_lifecycle() -> None:
        # Fact resolution has no actor grant. Its caller owns actual-user RAG policy;
        # this callback rechecks only the same canonical source's lifecycle, never
        # impersonating the uploader as permission to read another user's source.
        current = session.get(
            EducationalDocumentRecord, document.document_id, populate_existing=True
        )
        current_material = session.get(
            LearningMaterialRecord, document.material_id, populate_existing=True
        )
        if (
            current is None
            or current.lifecycle_state != "ACTIVE"
            or current.current_revision_id != document_revision_id
            or current_material is None
            or current_material.lifecycle_state != "ACTIVE"
        ):
            raise MaterialLearningSourceError("MATERIAL_LEARNING_DOCUMENT_NOT_FOUND")

    intake = read_material_intake(
        artifacts,
        intake_pointer,
        authorize=require_source_lifecycle,
    )
    rights = read_material_metadata(
        artifacts,
        document.rights_attestation,
        MaterialLearningRights,
        schema_ref="eom://schemas/material-learning/rights/1.0",
        member_path="rights/attestation.json",
    )
    receipts = {entry.source_role: entry.source_upload for entry in intake.sources}
    receipt = receipts.get(document.source_role)
    if (
        receipt is None
        or receipt.original != document.original
        or intake.material_id != material.material_id
        or intake.material_revision_id != revision.material_revision_id
        or intake.requested_by != revision.created_by
        or document.rights_attestation != intake.rights_attestation
        or rights.material_id != document.material_id
        or rights.material_revision_id != document.material_revision_id
        or rights.attested_by != document.registered_by
        or rights.source_hashes
        != tuple(entry.source_upload.original.sha256 for entry in intake.sources)
        or (
            row.analysis_artifact_id,
            row.analysis_artifact_revision_id,
            row.analysis_manifest_sha256,
        )
        != (
            document.analysis_bundle_manifest.artifact_id,
            document.analysis_bundle_manifest.artifact_revision_id,
            document.analysis_bundle_manifest.sha256,
        )
        or (row.rights_artifact_id, row.rights_artifact_revision_id, row.rights_attestation_sha256)
        != (
            document.rights_attestation.artifact_id,
            document.rights_attestation.artifact_revision_id,
            document.rights_attestation.sha256,
        )
    ):
        raise MaterialLearningSourceError("MATERIAL_LEARNING_KNOWLEDGE_LINEAGE_INVALID")
    selected = read_material_source_pages(
        artifacts, document, tuple(range(first_physical_page, last_physical_page + 1))
    )

    def dependency(pointer: MaterialArtifactMember) -> KnowledgeAnalysisDocumentDependencyV3:
        return KnowledgeAnalysisDocumentDependencyV3(
            **pointer.model_dump(exclude={"bytes"}),
            logical_name=pointer.member_path.rsplit("/", 1)[-1],
        )

    members = (
        *(_knowledge_page_member(page, "PAGE_TEXT") for page in selected.pages),
        *(_knowledge_page_member(page, "PAGE_IMAGE") for page in selected.pages),
    )
    return EducationalDocumentKnowledgeSourceV5(
        source_class=source_class,
        material_id=document.material_id,
        material_revision_id=document.material_revision_id,
        source_role=document.source_role,
        document_id=document.document_id,
        document_revision_id=document.document_revision_id,
        document_manifest=revision_manifest,
        original_source=document.original,
        artifact_member=KnowledgeAnalysisOriginalSourceMemberV3(
            **document.source.model_dump(), logical_name="original.pdf"
        ),
        analysis_bundle_manifest=dependency(document.analysis_bundle_manifest),
        rights_attestation=dependency(document.rights_attestation),
        first_physical_page=first_physical_page,
        last_physical_page=last_physical_page,
        selected_regions=selected_regions,
        curriculum_unit_keys=curriculum_unit_keys,
        chunk_manifests=selected.chunk_manifests,
        materialization_members=members,
        materialization_bytes=sum(member.bytes for member in members),
        page_image_count=len(selected.pages),
    )


def _knowledge_page_member(
    selected: ResolvedMaterialPage, kind: Literal["PAGE_TEXT", "PAGE_IMAGE"]
) -> MaterialKnowledgePageMember:
    page = selected.page
    image = kind == "PAGE_IMAGE"
    member = page.image if image else page.text
    return MaterialKnowledgePageMember(
        member_kind=kind,
        physical_page=page.physical_page,
        artifact_id=selected.chunk_manifest.artifact_id,
        artifact_revision_id=selected.chunk_manifest.artifact_revision_id,
        **member.model_dump(mode="json"),
        materialized_path="source/document/" + member.member_path.removeprefix("analysis/"),
        logical_name=member.member_path.rsplit("/", 1)[-1],
        width_pixels=page.width_pixels if image else None,
        height_pixels=page.height_pixels if image else None,
    )
