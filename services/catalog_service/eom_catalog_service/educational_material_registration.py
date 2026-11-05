"""Generic uploaded documents inside the existing EducationalDocument owner.

The textbook registration profile stays unchanged. These documents use explicit
uploader attestation, source-local identity and pointer-only page chunk manifests.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from eom_catalog_contracts.material_learning import (
    MaterialArtifactMember,
    MaterialLearningRights,
    SourceRole,
)
from eom_catalog_contracts.material_learning_intake import MaterialLearningIntakeManifest
from eom_catalog_contracts.material_learning_preparation import (
    MaterialDocumentReceipt,
    MaterialDocumentRevision,
    MaterialPageBundle,
    material_document_kind,
)
from eom_identifiers import content_sha256
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.models import ArtifactRevisionRecord
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.material_learning_artifacts import (
    pin_material_primary,
    publish_material_metadata,
    read_material_metadata,
)
from eom_catalog_service.material_learning_models import (
    LearningMaterialRecord,
    LearningMaterialRevisionRecord,
)
from eom_catalog_service.material_learning_source import (
    MaterialLearningSourceError,
    authorize_material_learning,
)
from eom_catalog_service.models import (
    EducationalDocumentRecord,
    EducationalDocumentRegistrationRecord,
    EducationalDocumentRevisionRecord,
)
from eom_catalog_service.settings import CatalogSettings

MATERIAL_DOCUMENT_SCHEMA = "eom://schemas/material-learning/document-revision/1.0"


def material_document_identity(
    material_revision_id: str, source_role: SourceRole
) -> tuple[str, str, str]:
    namespace = uuid5(NAMESPACE_URL, f"eom:material-document:{material_revision_id}:{source_role}")
    return (
        "edudoc_" + uuid5(namespace, "logical-document").hex,
        "edudocrev_" + uuid5(namespace, "revision:1").hex,
        "material-" + material_revision_id.removeprefix("materialrev_") + "-" + source_role.lower(),
    )


def material_document_registration_hash(
    *,
    material_id: str,
    material_revision_id: str,
    source_role: SourceRole,
    intake_sha256: str,
    analysis_bundle_manifest: MaterialArtifactMember,
    rights_attestation: MaterialArtifactMember,
) -> str:
    return content_sha256(
        {
            "material_id": material_id,
            "material_revision_id": material_revision_id,
            "source_role": source_role,
            "intake_sha256": intake_sha256,
            "analysis_bundle_manifest": analysis_bundle_manifest.model_dump(mode="json"),
            "rights_attestation": rights_attestation.model_dump(mode="json"),
        }
    )


class MaterialDocumentRegistrationService:
    """Implementation delegate of EducationalDocumentService, not a parallel registry."""

    def __init__(self, engine: Engine, settings: CatalogSettings) -> None:
        self.sessions = build_session_factory(engine)
        self.settings = settings
        self.artifacts = CatalogArtifactService(engine, settings)

    def _require_intake(
        self, session: Session, revision: MaterialDocumentRevision, *, operator_id: str
    ) -> LearningMaterialRevisionRecord:
        authorize_material_learning(session, operator_id)
        source = session.get(
            LearningMaterialRevisionRecord, revision.material_revision_id, populate_existing=True
        )
        material = session.get(LearningMaterialRecord, revision.material_id, populate_existing=True)
        if (
            source is None
            or material is None
            or material.lifecycle_state != "ACTIVE"
            or source.material_id != material.material_id
            or material.current_revision_id != source.material_revision_id
            or source.created_by != operator_id
            or revision.registered_by != operator_id
        ):
            raise MaterialLearningSourceError("MATERIAL_LEARNING_DOCUMENT_SOURCE_STALE")
        return source

    def register(
        self, revision: MaterialDocumentRevision, *, operator_id: str
    ) -> MaterialDocumentReceipt:
        revision = MaterialDocumentRevision.model_validate(revision.model_dump(mode="json"))
        if (
            revision.document_id,
            revision.document_revision_id,
            revision.document_key,
        ) != material_document_identity(revision.material_revision_id, revision.source_role):
            raise MaterialLearningSourceError("MATERIAL_LEARNING_DOCUMENT_IDENTITY_INVALID")
        with self.sessions() as session:
            source = self._require_intake(session, revision, operator_id=operator_id)
            intake_pointer = pin_material_primary(
                session,
                ArtifactMemberPointer(
                    artifact_id=source.manifest_artifact_id,
                    artifact_revision_id=source.manifest_artifact_revision_id,
                    member_path=source.manifest_member_path,
                    schema_ref="eom://schemas/material-learning/intake/1.0",
                    media_type="application/json",
                    sha256=source.manifest_sha256,
                ),
            ).pointer
            intake = read_material_metadata(
                self.artifacts,
                intake_pointer,
                MaterialLearningIntakeManifest,
                schema_ref="eom://schemas/material-learning/intake/1.0",
                member_path="material/intake.json",
            )
            expected_kind = material_document_kind(intake.upload.material_kind)
            selected = next(
                (entry for entry in intake.sources if entry.source_role == revision.source_role),
                None,
            )
            bundle_artifact = session.get(
                ArtifactRevisionRecord, revision.analysis_bundle_manifest.artifact_revision_id
            )
            if (
                intake.material_revision_id != revision.material_revision_id
                or intake.material_id != revision.material_id
                or intake.requested_by != operator_id
                or revision.registration_request_sha256
                != material_document_registration_hash(
                    material_id=revision.material_id,
                    material_revision_id=revision.material_revision_id,
                    source_role=revision.source_role,
                    intake_sha256=source.manifest_sha256,
                    analysis_bundle_manifest=revision.analysis_bundle_manifest,
                    rights_attestation=revision.rights_attestation,
                )
                or selected is None
                or selected.source_upload.original != revision.original
                or revision.rights_attestation != intake.rights_attestation
                or revision.title != intake.upload.title
                or revision.source_description != intake.upload.source_description
                or revision.document_kind != expected_kind
                or bundle_artifact is None
                or bundle_artifact.created_at != revision.registered_at
            ):
                raise MaterialLearningSourceError("MATERIAL_LEARNING_DOCUMENT_INPUT_MISMATCH")
        bundle = read_material_metadata(
            self.artifacts,
            revision.analysis_bundle_manifest,
            MaterialPageBundle,
            schema_ref="eom://schemas/material-learning/page-bundle/1.0",
            member_path="analysis/manifest.json",
        )
        rights = read_material_metadata(
            self.artifacts,
            revision.rights_attestation,
            MaterialLearningRights,
            schema_ref="eom://schemas/material-learning/rights/1.0",
            member_path="rights/attestation.json",
        )
        if (
            bundle.document_id != revision.document_id
            or bundle.document_revision_id != revision.document_revision_id
            or bundle.source_role != revision.source_role
            or bundle.original != revision.original
            or bundle.pdf != revision.source
            or bundle.page_count != revision.source_page_count
            or rights.material_id != revision.material_id
            or rights.material_revision_id != revision.material_revision_id
            or rights.attested_by != operator_id
            or revision.original.sha256 not in rights.source_hashes
        ):
            raise MaterialLearningSourceError("MATERIAL_LEARNING_DOCUMENT_DEPENDENCY_MISMATCH")
        published = publish_material_metadata(
            self.artifacts,
            self.settings,
            revision,
            schema_ref=MATERIAL_DOCUMENT_SCHEMA,
            member_path="document/document-revision.json",
            idempotency_key="material-document:" + revision.document_revision_id,
            artifact_type="material-learning-document",
        )
        with self.sessions.begin() as session:
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": revision.document_id},
            )
            self._require_intake(session, revision, operator_id=operator_id)
            existing = session.get(EducationalDocumentRevisionRecord, revision.document_revision_id)
            document = session.get(EducationalDocumentRecord, revision.document_id)
            if existing is not None:
                if (
                    document is None
                    or document.lifecycle_state != "ACTIVE"
                    or document.current_revision_id != existing.document_revision_id
                    or existing.registration_request_sha256 != revision.registration_request_sha256
                    or existing.revision_manifest_sha256 != published.sha256
                    or existing.revision_manifest_artifact_id != published.artifact_id
                    or existing.revision_manifest_artifact_revision_id
                    != published.artifact_revision_id
                ):
                    raise MaterialLearningSourceError("MATERIAL_LEARNING_DOCUMENT_REPLAY_CONFLICT")
            else:
                if document is not None:
                    raise MaterialLearningSourceError("MATERIAL_LEARNING_DOCUMENT_REPLAY_CONFLICT")
                document = EducationalDocumentRecord(
                    document_id=revision.document_id,
                    document_key=revision.document_key,
                    document_kind=revision.document_kind,
                    lifecycle_state="ACTIVE",
                    current_revision_id=None,
                    created_at=revision.registered_at,
                    created_by=operator_id,
                    lock_version=1,
                )
                session.add(document)
                session.flush([document])
                key = "material-document:" + revision.document_revision_id
                record = EducationalDocumentRevisionRecord(
                    document_id=revision.document_id,
                    document_revision_id=revision.document_revision_id,
                    revision_number=1,
                    previous_revision_id=None,
                    revision_state="APPROVED",
                    registration_key=key,
                    registration_request_sha256=revision.registration_request_sha256,
                    # Storage sentinels are explicitly unverified; the authoritative
                    # generic manifest preserves unknown bibliographic values as null.
                    publisher_key="unverified",
                    publisher_label="미확인",
                    title=revision.title,
                    curriculum_volume=None,
                    edition_label="미확인",
                    language="ko-KR",
                    source_artifact_id=revision.source.artifact_id,
                    source_artifact_revision_id=revision.source.artifact_revision_id,
                    source_sha256=revision.source.sha256,
                    source_size_bytes=revision.source.bytes,
                    source_page_count=revision.source_page_count,
                    analysis_artifact_id=revision.analysis_bundle_manifest.artifact_id,
                    analysis_artifact_revision_id=revision.analysis_bundle_manifest.artifact_revision_id,
                    analysis_manifest_sha256=revision.analysis_bundle_manifest.sha256,
                    rights_artifact_id=revision.rights_attestation.artifact_id,
                    rights_artifact_revision_id=revision.rights_attestation.artifact_revision_id,
                    rights_attestation_sha256=revision.rights_attestation.sha256,
                    revision_manifest_artifact_id=published.artifact_id,
                    revision_manifest_artifact_revision_id=published.artifact_revision_id,
                    revision_manifest_sha256=published.sha256,
                    created_at=revision.registered_at,
                    created_by=operator_id,
                )
                session.add(record)
                session.flush([record])
                document.current_revision_id = record.document_revision_id
                now = datetime.now(UTC)
                session.add(
                    EducationalDocumentRegistrationRecord(
                        document_registration_id="edudocreg_" + uuid5(NAMESPACE_URL, key).hex,
                        registration_key=key,
                        registration_request_sha256=revision.registration_request_sha256,
                        document_id=revision.document_id,
                        document_revision_id=revision.document_revision_id,
                        revision_number=1,
                        previous_revision_id=None,
                        state="COMMITTED",
                        failure_code=None,
                        created_at=revision.registered_at,
                        updated_at=now,
                        completed_at=now,
                        lock_version=1,
                    )
                )
            authorize_material_learning(session, operator_id)
        return self._receipt(revision, published)

    @staticmethod
    def _receipt(
        revision: MaterialDocumentRevision, published: MaterialArtifactMember
    ) -> MaterialDocumentReceipt:
        return MaterialDocumentReceipt(
            document_id=revision.document_id,
            document_revision_id=revision.document_revision_id,
            registration_request_sha256=revision.registration_request_sha256,
            revision_manifest=published,
            original=revision.original,
            source=revision.source,
            analysis_bundle_manifest=revision.analysis_bundle_manifest,
            rights_attestation=revision.rights_attestation,
        )

    def inspect_revision(self, revision_id: str, *, verify: bool) -> MaterialDocumentReceipt:
        with self.sessions() as session:
            row = session.get(EducationalDocumentRevisionRecord, revision_id)
            if row is None or row.revision_state != "APPROVED":
                raise MaterialLearningSourceError("MATERIAL_LEARNING_DOCUMENT_NOT_FOUND")
            artifact = session.get(
                ArtifactRevisionRecord, row.revision_manifest_artifact_revision_id
            )
            if artifact is None:
                raise MaterialLearningSourceError("MATERIAL_LEARNING_DOCUMENT_NOT_FOUND")
            pointer = MaterialArtifactMember(
                artifact_id=row.revision_manifest_artifact_id,
                artifact_revision_id=row.revision_manifest_artifact_revision_id,
                member_path="document/document-revision.json",
                schema_ref=MATERIAL_DOCUMENT_SCHEMA,
                media_type="application/json",
                sha256=row.revision_manifest_sha256,
                bytes=artifact.content_bytes,
            )
            expected = (row.document_id, row.document_revision_id, row.registration_request_sha256)
        revision = read_material_metadata(
            self.artifacts,
            pointer,
            MaterialDocumentRevision,
            schema_ref=MATERIAL_DOCUMENT_SCHEMA,
            member_path="document/document-revision.json",
        )
        if (
            revision.document_id,
            revision.document_revision_id,
            revision.registration_request_sha256,
        ) != expected:
            raise MaterialLearningSourceError("MATERIAL_LEARNING_DOCUMENT_POINTER_MISMATCH")
        if verify:
            members = (
                revision.original,
                revision.source,
                revision.analysis_bundle_manifest,
                revision.rights_attestation,
            )
            unique = {
                (
                    selected.artifact_id,
                    selected.artifact_revision_id,
                    selected.member_path,
                ): selected
                for selected in members
            }
            for selected in unique.values():
                self.artifacts.verify_member(
                    artifact_id=selected.artifact_id,
                    revision_id=selected.artifact_revision_id,
                    member_path=selected.member_path,
                    schema_ref=selected.schema_ref,
                    media_type=selected.media_type,
                    sha256=selected.sha256,
                    max_bytes=selected.bytes,
                )
        return self._receipt(revision, pointer)
