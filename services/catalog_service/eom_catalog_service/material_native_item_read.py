"""Catalog-owned reads of native material Item metadata and exact original files.

The DB projection is bounded metadata only. Opening a document additionally resolves
the committed binding against its actual material intake and canonical components.
Neither a model hash nor an invented legacy source row grants access.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

from eom_catalog_contracts.material_learning import MaterialArtifactMember, MaterialLearningRights
from eom_catalog_contracts.material_native_files import (
    MATERIAL_NATIVE_BINDING_REF,
    MaterialImportedNativeItemMetadata,
    MaterialNativeItemBinding,
    material_native_source_identity,
)
from eom_catalog_contracts.material_native_intake import (
    MaterialNativeLearningIntakeManifest,
    bind_native_exam_items,
)
from eom_catalog_contracts.material_native_item_read import (
    MaterialNativeItemReadRequest,
    MaterialNativeItemReadResponse,
    MaterialNativeItemSource,
)
from eom_identifiers import content_sha256
from eom_identity_service.models import OperatorRecord
from eom_identity_service.repository import effective_permissions
from eom_operator_identity import PermissionKey
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord
from sqlalchemy import Engine, and_, select, tuple_
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactService, VerifiedArtifactMemberStream
from eom_catalog_service.material_intake_read import material_intake_pointer, read_material_intake
from eom_catalog_service.material_learning_artifacts import read_material_metadata
from eom_catalog_service.material_learning_models import (
    LearningMaterialRecord,
    LearningMaterialRevisionRecord,
)
from eom_catalog_service.material_native_item_registration import (
    NATIVE_BINDING_MEMBER,
    NATIVE_ITEM_PACK_METADATA_REF,
    verify_registered_native_material,
)
from eom_catalog_service.material_native_resolution import read_material_native_bundle
from eom_catalog_service.models import (
    ItemComponentRecord,
    ItemMetadataSnapshotRecord,
    ItemRecord,
    ItemRevisionRecord,
)
from eom_catalog_service.settings import CatalogSettings

NATIVE_METADATA_VERSION = "material-imported-native-item-metadata/2.0"
_READ_PERMISSIONS = frozenset({PermissionKey.ITEM_READ, PermissionKey.CONTENT_INTAKE_READ})


class MaterialNativeItemReadError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class MaterialNativeOriginalMetadata:
    metadata: MaterialImportedNativeItemMetadata
    material_title: str


def read_native_material_original_metadata(
    session: Session, *, item_manifests: Mapping[str, str]
) -> dict[str, MaterialNativeOriginalMetadata]:
    """One bounded indexed projection; no document/whole-workbook reads per result.

    Callers own ITEM_READ + CONTENT_INTAKE_READ. This is the same immutable,
    registration-validated source metadata, not Graph-assigned curriculum units.
    Non-native Items are absent rather than converted into counterfeit legacy rows.
    """
    if not item_manifests:
        return {}
    if len(item_manifests) > 100:
        raise MaterialNativeItemReadError("MATERIAL_NATIVE_READ_BATCH_INVALID")
    rows = session.execute(
        select(
            ItemRevisionRecord,
            ItemRecord,
            LearningMaterialRevisionRecord,
            LearningMaterialRecord,
            ItemMetadataSnapshotRecord,
            ItemComponentRecord,
        )
        .join(ItemRecord, ItemRecord.item_id == ItemRevisionRecord.item_id)
        .outerjoin(
            LearningMaterialRevisionRecord,
            LearningMaterialRevisionRecord.material_revision_id
            == ItemRevisionRecord.metadata_json["material_revision_id"].as_string(),
        )
        .outerjoin(
            LearningMaterialRecord,
            LearningMaterialRecord.material_id == LearningMaterialRevisionRecord.material_id,
        )
        .outerjoin(
            ItemMetadataSnapshotRecord,
            ItemMetadataSnapshotRecord.item_revision_id == ItemRevisionRecord.item_revision_id,
        )
        .outerjoin(
            ItemComponentRecord,
            and_(
                ItemComponentRecord.item_revision_id == ItemRevisionRecord.item_revision_id,
                ItemComponentRecord.component_type == "METADATA",
                ItemComponentRecord.ordinal == 0,
            ),
        )
        .where(
            ItemRevisionRecord.item_revision_id.in_(item_manifests),
            ItemRevisionRecord.item_type_key == "uploaded-material-item",
            ItemRevisionRecord.metadata_json["schema_version"].as_string()
            == NATIVE_METADATA_VERSION,
        )
    ).all()
    result = {}
    for revision, item, material_revision, material, snapshot, component in rows:
        if (
            revision.manifest_sha256 != item_manifests[revision.item_revision_id]
            or item.lifecycle_state != "ACTIVE"
            or revision.revision_state not in {"APPROVED", "SUPERSEDED"}
            or material_revision is None
            or material is None
            or material.lifecycle_state != "ACTIVE"
            or material_revision.created_by != material.created_by
            or revision.metadata_sha256 != content_sha256(revision.metadata_json)
            or snapshot is None
            or snapshot.schema_ref != NATIVE_ITEM_PACK_METADATA_REF
            or snapshot.metadata_json != revision.metadata_json
            or snapshot.metadata_sha256 != revision.metadata_sha256
        ):
            raise MaterialNativeItemReadError("MATERIAL_NATIVE_ITEM_SOURCE_STALE")
        try:
            metadata = MaterialImportedNativeItemMetadata.model_validate(revision.metadata_json)
        except ValueError as error:
            raise MaterialNativeItemReadError("MATERIAL_NATIVE_ITEM_METADATA_INVALID") from error
        pointer = metadata.native_binding
        if (
            metadata.material_id != material.material_id
            or metadata.material_revision_id != material_revision.material_revision_id
            or component is None
            or component.required is not True
            or component.metadata_json != {"metadata_kind": "NATIVE_ITEM_SOURCE_BINDING_V1"}
            or component.logical_name != NATIVE_BINDING_MEMBER
            or pointer.member_path != NATIVE_BINDING_MEMBER
            or any(
                getattr(component, key) != getattr(pointer, key)
                for key in (
                    "artifact_id",
                    "artifact_revision_id",
                    "sha256",
                    "schema_ref",
                    "media_type",
                )
            )
            or revision.item_revision_id in result
        ):
            raise MaterialNativeItemReadError("MATERIAL_NATIVE_ITEM_BINDING_INVALID")
        result[revision.item_revision_id] = MaterialNativeOriginalMetadata(
            metadata=metadata, material_title=material_revision.title
        )
    return result


def authorize_native_material_read(session: Session, operator_id: str) -> None:
    operator = session.get(OperatorRecord, operator_id, populate_existing=True)
    if (
        operator is None
        or operator.status != "ACTIVE"
        or operator.deleted_at is not None
        or operator.must_change_password
        or not _READ_PERMISSIONS.issubset(effective_permissions(session, operator_id))
    ):
        raise MaterialNativeItemReadError("MATERIAL_NATIVE_READ_PERMISSION_DENIED")


def require_native_material_source_members(
    session: Session, pointers: tuple[MaterialArtifactMember, ...]
) -> None:
    """Reauthorize original lifecycle with one small metadata batch, not whole-paper rehashes."""
    keys = {(pointer.artifact_id, pointer.artifact_revision_id) for pointer in pointers}
    rows = session.execute(
        select(ArtifactRecord, ArtifactRevisionRecord)
        .join(
            ArtifactRevisionRecord,
            ArtifactRevisionRecord.logical_artifact_id == ArtifactRecord.logical_artifact_id,
        )
        .where(
            tuple_(ArtifactRecord.logical_artifact_id, ArtifactRevisionRecord.revision_id).in_(
                tuple(sorted(keys))
            )
        )
    ).all()
    indexed = {
        (artifact.logical_artifact_id, revision.revision_id): (artifact, revision)
        for artifact, revision in rows
    }
    if set(indexed) != keys or len(indexed) != len(rows):
        raise MaterialNativeItemReadError("MATERIAL_NATIVE_SOURCE_MEMBER_UNAVAILABLE")
    for pointer in pointers:
        artifact, revision = indexed[(pointer.artifact_id, pointer.artifact_revision_id)]
        files = revision.manifest.get("files")
        matches = (
            [
                member
                for member in files
                if isinstance(member, dict) and member.get("file_name") == pointer.member_path
            ]
            if isinstance(files, list)
            else []
        )
        if (
            not artifact.approved
            or not revision.approved
            or revision.manifest_hash != content_sha256(revision.manifest)
            or len(matches) != 1
            or any(
                matches[0].get(field) != expected
                for field, expected in (
                    ("schema_ref", pointer.schema_ref),
                    ("media_type", pointer.media_type),
                    ("sha256", pointer.sha256),
                    ("bytes", pointer.bytes),
                )
            )
        ):
            raise MaterialNativeItemReadError("MATERIAL_NATIVE_SOURCE_MEMBER_UNAVAILABLE")


@dataclass(frozen=True, slots=True)
class ResolvedMaterialNativeDocument:
    header: MaterialNativeItemReadResponse
    member: VerifiedArtifactMemberStream


class MaterialNativeItemReadService:
    def __init__(self, engine: Engine, settings: CatalogSettings | None = None) -> None:
        self.sessions = build_session_factory(engine)
        self.artifacts = CatalogArtifactService(engine, settings)

    def _resolve(
        self, session: Session, request: MaterialNativeItemReadRequest
    ) -> tuple[MaterialNativeItemSource, MaterialNativeItemBinding]:
        authorize_native_material_read(session, request.actor_id)
        values = read_native_material_original_metadata(
            session, item_manifests={request.item_revision_id: request.item_manifest_sha256}
        )
        source = values.get(request.item_revision_id)
        if source is None:
            raise MaterialNativeItemReadError("MATERIAL_NATIVE_ITEM_SOURCE_NOT_FOUND")
        metadata = source.metadata

        def authorize() -> None:
            authorize_native_material_read(session, request.actor_id)

        binding = read_material_metadata(
            self.artifacts,
            metadata.native_binding,
            MaterialNativeItemBinding,
            schema_ref=MATERIAL_NATIVE_BINDING_REF,
            member_path=NATIVE_BINDING_MEMBER,
            maximum_bytes=4 * 1024 * 1024,
        )
        revision = session.get(ItemRevisionRecord, request.item_revision_id)
        components = {
            (component.component_type, component.ordinal): component
            for component in session.scalars(
                select(ItemComponentRecord).where(
                    ItemComponentRecord.item_revision_id == request.item_revision_id
                )
            )
        }
        if revision is None or set(components) != {
            ("ITEM_CONTENT", 0),
            ("SOURCE_REFERENCE", 0),
            ("REVIEW_REPORT", 0),
            ("METADATA", 0),
            ("OTHER", 0),
            ("OTHER", 1),
        }:
            raise MaterialNativeItemReadError("MATERIAL_NATIVE_ITEM_COMPONENTS_INVALID")
        verify_registered_native_material(session, self.artifacts, revision, components, binding)
        material_revision = session.get(
            LearningMaterialRevisionRecord, metadata.material_revision_id
        )
        if material_revision is None:
            raise MaterialNativeItemReadError("MATERIAL_NATIVE_ITEM_SOURCE_NOT_FOUND")
        intake = read_material_intake(
            self.artifacts,
            material_intake_pointer(
                session,
                artifact_id=material_revision.manifest_artifact_id,
                revision_id=material_revision.manifest_artifact_revision_id,
                sha256=material_revision.manifest_sha256,
            ),
            authorize=authorize,
        )
        if (
            not isinstance(intake, MaterialNativeLearningIntakeManifest)
            or intake.requested_by != material_revision.created_by
            or intake.material_revision_id != metadata.material_revision_id
            or intake.material_id != metadata.material_id
        ):
            raise MaterialNativeItemReadError("MATERIAL_NATIVE_ITEM_INTAKE_INVALID")
        bundle = read_material_native_bundle(
            self.artifacts,
            intake.native_bundle,
            sources=intake.sources,
            operator_id=intake.requested_by,
            authorize=authorize,
        )
        require_native_material_source_members(
            session,
            (
                *(
                    pointer
                    for selected in intake.sources
                    for pointer in (
                        selected.source_upload.manifest,
                        selected.source_upload.original,
                    )
                ),
                intake.rights_attestation,
                bundle.workbook.workbook,
                bundle.workbook.parsed_workbook,
            ),
        )
        rights = read_material_metadata(
            self.artifacts,
            intake.rights_attestation,
            MaterialLearningRights,
            schema_ref="eom://schemas/material-learning/rights/1.0",
            member_path="rights/attestation.json",
        )
        if (rights.material_id, rights.material_revision_id, rights.attested_by) != (
            metadata.material_id,
            metadata.material_revision_id,
            intake.requested_by,
        ) or rights.source_hashes != tuple(
            selected.source_upload.original.sha256 for selected in intake.sources
        ):
            raise MaterialNativeItemReadError("MATERIAL_NATIVE_ITEM_RIGHTS_INVALID")
        (expected,) = bind_native_exam_items(
            bundle,
            material_id=metadata.material_id,
            material_revision_id=metadata.material_revision_id,
            units={metadata.item_number: (metadata.unit_key, metadata.printed_label)},
        )
        if expected != binding:
            raise MaterialNativeItemReadError("MATERIAL_NATIVE_ITEM_SOURCE_STALE")
        authorize()
        return MaterialNativeItemSource(
            material_title=source.material_title,
            metadata=metadata,
            question=binding.question.document,
            solution=binding.solution.document,
            workbook=binding.workbook,
        ), binding

    def read_source(self, request: MaterialNativeItemReadRequest) -> MaterialNativeItemSource:
        if request.operation != "GET_NATIVE_MATERIAL_ITEM_SOURCE":
            raise MaterialNativeItemReadError("MATERIAL_NATIVE_READ_OPERATION_INVALID")
        with self.sessions() as session:
            source, _ = self._resolve(session, request)
            return source

    def open_document(
        self, request: MaterialNativeItemReadRequest
    ) -> ResolvedMaterialNativeDocument:
        if request.operation != "GET_NATIVE_MATERIAL_ITEM_DOCUMENT" or request.source_role is None:
            raise MaterialNativeItemReadError("MATERIAL_NATIVE_READ_OPERATION_INVALID")
        with self.sessions() as session:
            source, binding = self._resolve(session, request)
            file = binding.question if request.source_role == "MAIN" else binding.solution
            pointer = file.document
            if pointer.bytes > 50 * 1024 * 1024 or pointer.media_type not in {
                "application/vnd.hancom.hwpx",
                "application/hwp+zip",
            }:
                raise MaterialNativeItemReadError("MATERIAL_NATIVE_DOCUMENT_POINTER_INVALID")
            member = self.artifacts.open_verified_member(
                artifact_id=pointer.artifact_id,
                revision_id=pointer.artifact_revision_id,
                member_path=pointer.member_path,
                schema_ref=pointer.schema_ref,
                media_type=pointer.media_type,
                sha256=pointer.sha256,
                max_bytes=pointer.bytes,
            )
            try:
                if member.content_length != pointer.bytes:
                    raise MaterialNativeItemReadError("MATERIAL_NATIVE_DOCUMENT_POINTER_INVALID")
                authorize_native_material_read(session, request.actor_id)
                number = source.metadata.external_number or str(source.metadata.item_number)
                identity = material_native_source_identity(binding).removeprefix("sha256:")[:12]
                filename = f"EOM-{number}-{identity}-{request.source_role.lower()}.hwpx"
                header = MaterialNativeItemReadResponse(
                    operation=request.operation,
                    status="OK",
                    filename=filename,
                    media_type=cast(
                        Literal["application/vnd.hancom.hwpx", "application/hwp+zip"],
                        pointer.media_type,
                    ),
                    content_length=member.content_length,
                    sha256=member.sha256,
                )
                return ResolvedMaterialNativeDocument(header=header, member=member)
            except Exception:
                member.stream.close()
                raise
