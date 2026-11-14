"""Canonical PDF/native-figure projections through existing converter/publishers."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from eom_catalog_contracts.document_review import OfficeDocumentReviewConversionIdentity
from eom_catalog_contracts.material_learning import MaterialArtifactMember
from eom_catalog_contracts.material_learning_intake import MaterialLearningSourceSelection
from eom_catalog_contracts.material_learning_preparation import (
    MaterialPdfProjection,
)
from eom_catalog_contracts.material_native_intake import MaterialPreparation
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes, sha256_file
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetMember,
    ControlFileSetPublisher,
)
from eom_orchestrator.office_picture_use_extraction import extract_office_picture_use_input
from eom_orchestrator.office_picture_use_publication import publish_office_picture_catalog
from eom_orchestrator.settings import Settings
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy import Engine

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.material_learning_artifacts import (
    find_material_publication,
    pin_material_primary,
    read_material_metadata,
)
from eom_catalog_service.material_learning_source import (
    MaterialLearningSourceError,
    MaterialLearningSourceService,
    MaterialSourceFileFingerprint,
)
from eom_catalog_service.settings import CatalogSettings

_PROJECTION_TYPE = "control_material_learning_pdf_projection"
_PROJECTION_REF = "eom://schemas/material-learning/pdf-projection/1.0"
_PROJECTION_PATH = "analysis/pdf-projection.json"
_PDF_REF = "eom://schemas/educational-document/pdf-source/1.0"


class MaterialOfficeConverter(Protocol):
    libreoffice: Path
    h2orestart_bundle: Path

    def get_or_create_workspace(self, instance_id: str) -> Path: ...

    def validate_source(
        self, workspace: Path, *, fingerprint: MaterialSourceFileFingerprint
    ) -> None: ...

    def convert(
        self, workspace: Path, *, source_format: str
    ) -> OfficeDocumentReviewConversionIdentity: ...

    def read_completed(
        self, workspace: Path, *, source_format: str, expected_source_sha256: str
    ) -> OfficeDocumentReviewConversionIdentity: ...


@dataclass(frozen=True, slots=True)
class MaterialSourceProjection:
    pdf: MaterialArtifactMember
    conversion: OfficeDocumentReviewConversionIdentity
    office_catalog: MaterialArtifactMember | None


@dataclass(frozen=True, slots=True)
class LocalMaterialSource:
    """A temporary parsing input plus its canonical pointers, never a new source."""

    pdf_path: Path
    pdf: MaterialArtifactMember
    conversion: OfficeDocumentReviewConversionIdentity
    office_catalog: MaterialArtifactMember | None


class MaterialSourceProjectionService:
    def __init__(
        self,
        engine: Engine,
        *,
        settings: CatalogSettings,
        platform_settings: Settings,
        publisher: ControlFileSetPublisher,
        converter: MaterialOfficeConverter | None = None,
    ) -> None:
        self.sessions = build_session_factory(engine)
        self.settings, self.platform_settings = settings, platform_settings
        self.publisher = publisher
        self.artifacts = CatalogArtifactService(engine, settings)
        self._sources = MaterialLearningSourceService(engine, settings)
        self.converter = converter

    def authorize_source(
        self, selection: MaterialLearningSourceSelection, *, operator_id: str
    ) -> None:
        self._sources.resolve(selection.source_upload, operator_id=operator_id)

    @contextmanager
    def stage(
        self,
        work: MaterialPreparation,
        selection: MaterialLearningSourceSelection,
        *,
        operator_id: str,
        authorize: Callable[[], None],
    ) -> Iterator[LocalMaterialSource]:
        authorize()
        receipt = selection.source_upload
        self.authorize_source(selection, operator_id=operator_id)
        if receipt.source_format == "PDF":
            result = MaterialSourceProjection(
                receipt.original,
                OfficeDocumentReviewConversionIdentity(
                    conversion_kind="IDENTITY_PDF", review_pdf_sha256=receipt.original.sha256
                ),
                None,
            )
        else:
            result = self._office(work, selection, authorize=authorize)
        with tempfile.TemporaryDirectory(
            prefix="material-pdf-input.", dir=self.settings.staging_root
        ) as temporary:
            path = Path(temporary) / "original.pdf"
            self._copy_member(result.pdf, path)
            authorize()
            yield LocalMaterialSource(path, result.pdf, result.conversion, result.office_catalog)

    def _copy_member(self, member: MaterialArtifactMember, path: Path) -> None:
        verified = self.artifacts.open_verified_member(
            artifact_id=member.artifact_id,
            revision_id=member.artifact_revision_id,
            member_path=member.member_path,
            schema_ref=member.schema_ref,
            media_type=member.media_type,
            sha256=member.sha256,
            max_bytes=member.bytes,
        )
        try:
            if verified.content_length != member.bytes:
                raise MaterialLearningSourceError("MATERIAL_LEARNING_SOURCE_RECEIPT_MISMATCH")
            with path.open("xb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                for chunk in verified.iter_chunks():
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            verified.stream.close()
        if path.stat().st_size != member.bytes or sha256_file(path) != member.sha256:
            raise MaterialLearningSourceError("MATERIAL_LEARNING_SOURCE_HASH_MISMATCH")

    def _office(
        self,
        work: MaterialPreparation,
        selection: MaterialLearningSourceSelection,
        *,
        authorize: Callable[[], None],
    ) -> MaterialSourceProjection:
        receipt, profile = selection.source_upload, work.profile
        key = (
            "material-pdf:"
            + content_sha256(
                {
                    "material_revision_id": work.material_revision_id,
                    "source_role": selection.source_role,
                    "source": receipt.original.model_dump(mode="json"),
                    "profile_sha256": profile.profile_sha256,
                }
            )[7:]
        )
        pointer = find_material_publication(
            self.publisher, idempotency_key=key, artifact_type=_PROJECTION_TYPE
        )
        if pointer is None:
            if self.converter is None or self.platform_settings.office_image_tool_root is None:
                raise MaterialLearningSourceError("MATERIAL_LEARNING_OFFICE_TOOLS_UNAVAILABLE")
            tool_root = self.platform_settings.office_image_tool_root
            if tool_root.parent.name != profile.office_tool_source_commit:
                raise MaterialLearningSourceError("MATERIAL_LEARNING_PREPARATION_PROFILE_STALE")
            if (
                sha256_file(self.converter.libreoffice) != profile.libreoffice_sha256
                or sha256_file(self.converter.h2orestart_bundle) != profile.h2orestart_sha256
            ):
                raise MaterialLearningSourceError("MATERIAL_LEARNING_PREPARATION_PROFILE_STALE")
            instance = "officeconv_" + content_sha256([work.task_id, selection.source_role])[7:39]
            workspace = self.converter.get_or_create_workspace(instance)
            source = workspace / ("original." + receipt.source_format.lower())
            if not os.path.lexists(source):
                self._copy_member(receipt.original, source)
            self.converter.validate_source(
                workspace,
                fingerprint=MaterialSourceFileFingerprint(
                    receipt.source_format, receipt.original.bytes, receipt.original.sha256
                ),
            )
            authorize()
            if os.path.lexists(workspace / "conversion-outcome.json"):
                conversion = self.converter.read_completed(
                    workspace,
                    source_format=receipt.source_format,
                    expected_source_sha256=receipt.original.sha256,
                )
            else:
                conversion = self.converter.convert(workspace, source_format=receipt.source_format)
            if (
                conversion.libreoffice_sha256 != profile.libreoffice_sha256
                or conversion.h2orestart_sha256 != profile.h2orestart_sha256
            ):
                raise MaterialLearningSourceError("MATERIAL_LEARNING_PREPARATION_PROFILE_STALE")
            authorize()
            with tempfile.TemporaryDirectory(
                prefix="material-native.", dir=self.settings.staging_root
            ) as temporary:
                extracted = extract_office_picture_use_input(
                    source.read_bytes(),
                    expected_sha256=receipt.original.sha256,
                    tool_root=tool_root,
                    workspace=Path(temporary) / "extracted",
                )
                catalog_artifact = publish_office_picture_catalog(
                    self.publisher,
                    extracted,
                    source_commit=profile.source_commit,
                    authorize_source=authorize,
                )
                catalog = MaterialArtifactMember(
                    artifact_id=catalog_artifact.artifact_id,
                    artifact_revision_id=catalog_artifact.artifact_revision_id,
                    member_path=catalog_artifact.member_path,
                    schema_ref=catalog_artifact.schema_ref,
                    media_type="application/json",
                    sha256=catalog_artifact.sha256,
                    bytes=len(canonical_json_bytes(extracted.catalog.model_dump(mode="json"))),
                )
            pdf = workspace / "converted/original.pdf"
            projection = MaterialPdfProjection(
                source_sha256=receipt.original.sha256,
                profile_sha256=profile.profile_sha256,
                conversion=conversion,
                pdf_bytes=pdf.stat().st_size,
                office_catalog=catalog,
            )
            encoded = canonical_json_bytes(projection.model_dump(mode="json"))
            metadata = workspace / "material-pdf-projection.json"
            if os.path.lexists(metadata):
                if metadata.is_symlink() or metadata.read_bytes() != encoded:
                    raise MaterialLearningSourceError(
                        "MATERIAL_LEARNING_PREPARATION_REPLAY_CONFLICT"
                    )
            else:
                with metadata.open("xb") as stream:
                    stream.write(encoded)
            authorize()
            published = self.publisher.publish_first_observation(
                members=(
                    ControlFileSetMember(
                        _PROJECTION_PATH,
                        metadata,
                        sha256_bytes(encoded),
                        len(encoded),
                        _PROJECTION_REF,
                        "application/json",
                    ),
                    ControlFileSetMember(
                        "source/original.pdf",
                        pdf,
                        conversion.review_pdf_sha256,
                        projection.pdf_bytes,
                        _PDF_REF,
                        "application/pdf",
                    ),
                ),
                primary_file=_PROJECTION_PATH,
                artifact_type=_PROJECTION_TYPE,
                manifest_version="material-learning-pdf-projection-artifact/1.0",
                idempotency_key=key,
                source_commit=profile.source_commit,
            )
            pointer = ArtifactMemberPointer(
                artifact_id=published.artifact_id,
                artifact_revision_id=published.artifact_revision_id,
                member_path=_PROJECTION_PATH,
                schema_ref=_PROJECTION_REF,
                media_type="application/json",
                sha256=published.primary_sha256,
            )
            # Completed conversion is now committed. Keep failed workspaces for
            # exact recovery; remove only this validated private successful instance.
            shutil.rmtree(workspace)
        with self.sessions() as session:
            canonical = pin_material_primary(session, pointer).pointer
        observed = read_material_metadata(
            self.artifacts,
            canonical,
            MaterialPdfProjection,
            schema_ref=_PROJECTION_REF,
            member_path=_PROJECTION_PATH,
        )
        if (
            observed.source_sha256 != receipt.original.sha256
            or observed.profile_sha256 != profile.profile_sha256
        ):
            raise MaterialLearningSourceError("MATERIAL_LEARNING_PREPARATION_REPLAY_CONFLICT")
        authorize()
        return MaterialSourceProjection(
            MaterialArtifactMember(
                artifact_id=canonical.artifact_id,
                artifact_revision_id=canonical.artifact_revision_id,
                member_path="source/original.pdf",
                schema_ref=_PDF_REF,
                media_type="application/pdf",
                sha256=observed.conversion.review_pdf_sha256,
                bytes=observed.pdf_bytes,
            ),
            observed.conversion,
            observed.office_catalog,
        )
