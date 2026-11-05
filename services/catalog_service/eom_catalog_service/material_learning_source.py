"""Catalog-owned raw source publication; parsing and AI run after durable intake."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
from pathlib import Path

from eom_catalog_contracts.material_learning import MaterialArtifactMember
from eom_catalog_contracts.material_learning_intake import (
    MATERIAL_SOURCE_FORMATS,
    MaterialSourceMember,
    MaterialSourceUploadCommand,
    MaterialSourceUploadManifest,
    MaterialSourceUploadReceipt,
)
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_identity_service.models import OperatorRecord
from eom_identity_service.repository import effective_permissions
from eom_operator_identity import PermissionKey
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.models import ArtifactRevisionRecord
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.office_converter_worker import OfficeConverterError, validate_office_source
from eom_catalog_service.settings import CatalogSettings

_MANIFEST_PATH = "material/source-upload-manifest.json"
_MANIFEST_SCHEMA = "eom://schemas/material-learning/source-manifest/1.0"
_PROTOCOL = "catalog-material-learning/1.0"
_PROTOCOL_HASH = content_sha256(
    {"protocol": _PROTOCOL, "contracts": ["material-learning-source-manifest/1.0"]}
)
_PERMISSIONS = frozenset(
    {
        PermissionKey.CONTENT_INTAKE_READ,
        PermissionKey.WORKFLOW_START,
        PermissionKey.KNOWLEDGE_ANALYSIS_CREATE,
    }
)


class MaterialLearningSourceError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def authorize_material_learning(session: Session, operator_id: str) -> None:
    """Recheck the real submitting operator, including during background claims."""
    operator = session.get(OperatorRecord, operator_id, populate_existing=True)
    if (
        operator is None
        or operator.status != "ACTIVE"
        or operator.deleted_at is not None
        or operator.must_change_password
        or not _PERMISSIONS.issubset(effective_permissions(session, operator_id))
    ):
        raise MaterialLearningSourceError("MATERIAL_LEARNING_PERMISSION_DENIED")


def validate_material_source_file(source: Path, command: MaterialSourceUploadCommand) -> None:
    """Validate at the private input boundary, never trust a filename or caller hash."""
    descriptor = os.open(
        source, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != os.geteuid()
            or before.st_size != command.content_length
            or stat.S_IMODE(before.st_mode) != 0o600
        ):
            raise MaterialLearningSourceError("MATERIAL_LEARNING_SOURCE_FILE_INVALID")
        prefix = os.read(descriptor, 8)
        if command.source_format == "PDF":
            if re.fullmatch(rb"%PDF-[12]\.[0-9]", prefix) is None:
                raise MaterialLearningSourceError("MATERIAL_LEARNING_SOURCE_SIGNATURE_INVALID")
        else:
            try:
                validate_office_source(source, command.source_format, os.geteuid())
            except OfficeConverterError as error:
                raise MaterialLearningSourceError(
                    "MATERIAL_LEARNING_SOURCE_SIGNATURE_INVALID"
                ) from error
        os.lseek(descriptor, 0, os.SEEK_SET)
        digest = hashlib.sha256()
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise MaterialLearningSourceError("MATERIAL_LEARNING_SOURCE_CHANGED")
            digest.update(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)

        # atime is not content identity. Detect both in-place writes and path swaps.
        def identity(value: os.stat_result) -> tuple[int, ...]:
            return (
                value.st_dev,
                value.st_ino,
                value.st_mode,
                value.st_uid,
                value.st_nlink,
                value.st_size,
                value.st_mtime_ns,
                value.st_ctime_ns,
            )

        if identity(before) != identity(after) or identity(after) != identity(source.lstat()):
            raise MaterialLearningSourceError("MATERIAL_LEARNING_SOURCE_CHANGED")
        if "sha256:" + digest.hexdigest() != command.sha256:
            raise MaterialLearningSourceError("MATERIAL_LEARNING_SOURCE_HASH_MISMATCH")
    finally:
        os.close(descriptor)


class MaterialLearningSourceService:
    def __init__(self, engine: Engine, settings: CatalogSettings | None = None) -> None:
        self.settings = settings or CatalogSettings.from_environment()
        self.sessions = build_session_factory(engine)
        self.artifacts = CatalogArtifactService(engine, self.settings)

    def authorize_upload(self, command: MaterialSourceUploadCommand) -> None:
        with self.sessions() as session:
            authorize_material_learning(session, command.actor_id)

    def ingest(
        self, source: Path, command: MaterialSourceUploadCommand
    ) -> MaterialSourceUploadReceipt:
        command = MaterialSourceUploadCommand.model_validate(command.model_dump(mode="json"))
        self.authorize_upload(command)
        validate_material_source_file(source, command)
        descriptor = MATERIAL_SOURCE_FORMATS[command.source_format]
        original_path = "source/original" + descriptor.suffix
        manifest = MaterialSourceUploadManifest(
            uploaded_by=command.actor_id,
            original_filename=command.original_filename,
            source_format=command.source_format,
            rights_confirmed=True,
            original=MaterialSourceMember(
                member_path=original_path,
                schema_ref=descriptor.schema_ref,
                media_type=descriptor.media_type,
                sha256=command.sha256,
                bytes=command.content_length,
            ),
        )
        encoded = canonical_json_bytes(manifest.model_dump(mode="json"))
        manifest_sha = "sha256:" + hashlib.sha256(encoded).hexdigest()
        # This is an explicit metadata staging boundary, not a second original copy.
        with tempfile.TemporaryDirectory(
            prefix="material-source.", dir=self.settings.staging_root
        ) as temporary:
            manifest_path = Path(temporary) / "manifest.json"
            with manifest_path.open("xb") as stream:
                stream.write(encoded)
            with self.sessions() as session:
                authorize_material_learning(session, command.actor_id)
            published = self.artifacts.commit_file_set(
                files={_MANIFEST_PATH: manifest_path, original_path: source},
                primary_file=_MANIFEST_PATH,
                artifact_type="material-learning-source",
                idempotency_key="material-source:"
                + content_sha256([command.actor_id, command.idempotency_key])[7:],
                request=command.model_dump(mode="json"),
                result={"manifest_sha256": manifest_sha},
                file_metadata={
                    _MANIFEST_PATH: {
                        "schema_ref": _MANIFEST_SCHEMA,
                        "media_type": "application/json",
                    },
                    original_path: {
                        "schema_ref": descriptor.schema_ref,
                        "media_type": descriptor.media_type,
                    },
                },
                expected_file_sha256={
                    _MANIFEST_PATH: manifest_sha,
                    original_path: command.sha256,
                },
                protocol_version=_PROTOCOL,
                protocol_schema_hash=_PROTOCOL_HASH,
            )
        with self.sessions() as session:
            authorize_material_learning(session, command.actor_id)
            revision = session.get(ArtifactRevisionRecord, published.revision_id)
            if revision is None or revision.logical_artifact_id != published.artifact_id:
                raise MaterialLearningSourceError("MATERIAL_LEARNING_SOURCE_NOT_COMMITTED")
            created_at = revision.created_at
        return MaterialSourceUploadReceipt(
            manifest=MaterialArtifactMember(
                artifact_id=published.artifact_id,
                artifact_revision_id=published.revision_id,
                member_path=_MANIFEST_PATH,
                schema_ref=_MANIFEST_SCHEMA,
                media_type="application/json",
                sha256=manifest_sha,
                bytes=len(encoded),
            ),
            original=MaterialArtifactMember(
                artifact_id=published.artifact_id,
                artifact_revision_id=published.revision_id,
                member_path=original_path,
                schema_ref=descriptor.schema_ref,
                media_type=descriptor.media_type,
                sha256=command.sha256,
                bytes=command.content_length,
            ),
            uploaded_by=manifest.uploaded_by,
            created_at=created_at,
            original_filename=manifest.original_filename,
            source_format=manifest.source_format,
        )

    def resolve(
        self, receipt: MaterialSourceUploadReceipt, *, operator_id: str
    ) -> MaterialSourceUploadManifest:
        receipt = MaterialSourceUploadReceipt.model_validate(receipt.model_dump(mode="json"))
        with self.sessions() as session:
            authorize_material_learning(session, operator_id)
            if receipt.uploaded_by != operator_id:
                raise MaterialLearningSourceError("MATERIAL_LEARNING_SOURCE_OWNER_MISMATCH")
            revision = session.get(ArtifactRevisionRecord, receipt.manifest.artifact_revision_id)
            if revision is None or revision.created_at != receipt.created_at:
                raise MaterialLearningSourceError("MATERIAL_LEARNING_SOURCE_RECEIPT_STALE")
        # The existing Artifact owner validates lifecycle, schema/media and member hash.
        raw = self.artifacts.read_member(
            artifact_id=receipt.manifest.artifact_id,
            revision_id=receipt.manifest.artifact_revision_id,
            member_path=receipt.manifest.member_path,
            schema_ref=receipt.manifest.schema_ref,
            media_type=receipt.manifest.media_type,
            sha256=receipt.manifest.sha256,
            max_bytes=min(receipt.manifest.bytes, 16_384),
        )
        manifest = MaterialSourceUploadManifest.model_validate_json(raw)
        original = receipt.original
        if (
            manifest.uploaded_by != operator_id
            or manifest.source_format != receipt.source_format
            or manifest.original_filename != receipt.original_filename
            or manifest.original.model_dump()
            != original.model_dump(exclude={"artifact_id", "artifact_revision_id"})
            or len(raw) != receipt.manifest.bytes
        ):
            raise MaterialLearningSourceError("MATERIAL_LEARNING_SOURCE_RECEIPT_MISMATCH")
        self.artifacts.verify_member(
            artifact_id=original.artifact_id,
            revision_id=original.artifact_revision_id,
            member_path=original.member_path,
            schema_ref=original.schema_ref,
            media_type=original.media_type,
            sha256=original.sha256,
            max_bytes=original.bytes,
        )
        with self.sessions() as session:
            authorize_material_learning(session, operator_id)
        return manifest
