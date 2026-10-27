"""Catalog-owned Office-to-PDF derivative for an already imported external Item."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from eom_catalog_contracts.external_item_media import ExternalItemDocumentMediaQuery
from eom_catalog_contracts.external_item_preview import (
    EXTERNAL_ITEM_PREVIEW_MANIFEST_SCHEMA,
    EXTERNAL_ITEM_PREVIEW_MANIFEST_SCHEMA_REF,
    EXTERNAL_ITEM_PREVIEW_PDF_SCHEMA_REF,
    ExternalItemPreviewManifest,
)
from eom_catalog_contracts.validation import validate_contract
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_file
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from jsonschema import ValidationError as JsonSchemaValidationError
from sqlalchemy import Engine, select

from eom_catalog_service.artifacts import (
    CatalogArtifact,
    CatalogArtifactService,
    VerifiedArtifactMemberStream,
    normalize_catalog_idempotency_key,
)
from eom_catalog_service.external_item_document_media import (
    ExternalItemDocumentMediaService,
    ResolvedExternalItemDocumentMedia,
)
from eom_catalog_service.office_converter_worker import INSTANCE_PATTERN
from eom_catalog_service.office_document_converter import (
    CONVERSION_DIRECTORY,
    SystemdOfficeDocumentConverter,
)
from eom_catalog_service.settings import CatalogSettings

_ARTIFACT_TYPE = "external-item-preview-v1"
_MANIFEST_MEMBER = "preview-manifest.json"
_PDF_MEMBER = "preview/original.pdf"
_MANIFEST_MAX_BYTES = 64 * 1024
_PDF_MAX_BYTES = 256 * 1024 * 1024


class ExternalItemPreviewUnavailable(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ResolvedExternalItemPreview:
    member: VerifiedArtifactMemberStream
    manifest: ExternalItemPreviewManifest
    artifact_id: str
    artifact_revision_id: str


def _idempotency_key(query: ExternalItemDocumentMediaQuery) -> str:
    return f"external-item-preview-v1:{query.source_revision_id}:{query.edition}"


def _copy_verified_source(source: ResolvedExternalItemDocumentMedia, target: Path) -> None:
    """Materialize one temporary converter input from a verified Intake FD."""

    digest = hashlib.sha256()
    copied = 0
    try:
        descriptor = os.open(
            target,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "wb") as output:
            for chunk in source.member.iter_chunks():
                output.write(chunk)
                digest.update(chunk)
                copied += len(chunk)
            output.flush()
            os.fsync(output.fileno())
    finally:
        source.member.stream.close()
    if copied != source.member.content_length or "sha256:" + digest.hexdigest() != (
        source.member.sha256
    ):
        raise ValueError("external Item preview source changed during materialization")


class ExternalItemPreviewProjectionService:
    """Build a PDF-only Artifact; never recommit the original Office document."""

    def __init__(
        self,
        engine: Engine,
        *,
        settings: CatalogSettings | None = None,
        source_media: ExternalItemDocumentMediaService | None = None,
        artifacts: CatalogArtifactService | None = None,
        converter: SystemdOfficeDocumentConverter | None = None,
    ) -> None:
        self.settings = settings or CatalogSettings.from_environment()
        self.source_media = source_media or ExternalItemDocumentMediaService(engine)
        self.artifacts = artifacts or CatalogArtifactService(engine, self.settings)
        self.converter = converter
        self.sessions = build_session_factory(engine)

    def open(self, query: ExternalItemDocumentMediaQuery) -> ResolvedExternalItemPreview:
        """Read one already-built PDF after reauthorizing its exact current source."""

        source = self.source_media.open(query)
        source.member.stream.close()
        with self.sessions() as session:
            job = session.scalar(
                select(JobRecord).where(
                    JobRecord.idempotency_key
                    == normalize_catalog_idempotency_key(_idempotency_key(query))
                )
            )
            if job is None:
                raise ExternalItemPreviewUnavailable("EXTERNAL_ITEM_PREVIEW_NOT_READY")
            if job.status in {"CREATED", "VALIDATED", "QUEUED", "CLAIMED", "RUNNING"}:
                raise ExternalItemPreviewUnavailable("EXTERNAL_ITEM_PREVIEW_NOT_READY")
            logical = session.get(ArtifactRecord, job.logical_artifact_id)
            revision = session.get(ArtifactRevisionRecord, job.revision_id)
            if (
                job.status != "SUCCEEDED"
                or job.task_type != _ARTIFACT_TYPE
                or logical is None
                or revision is None
                or not logical.approved
                or not revision.approved
                or logical.artifact_type != _ARTIFACT_TYPE
                or logical.job_id != job.job_id
                or revision.job_id != job.job_id
                or revision.logical_artifact_id != job.logical_artifact_id
                or not isinstance(revision.manifest, dict)
                or revision.manifest_hash != content_sha256(revision.manifest)
                or revision.manifest.get("artifact_type") != _ARTIFACT_TYPE
                or revision.manifest.get("primary_file") != _MANIFEST_MEMBER
                or revision.manifest.get("job_id") != job.job_id
                or revision.manifest.get("logical_artifact_id") != job.logical_artifact_id
                or revision.manifest.get("revision_id") != job.revision_id
                or revision.manifest.get("content_hash") != revision.content_hash
                or not isinstance(job.request, dict)
                or not isinstance(revision.result, dict)
            ):
                raise ExternalItemPreviewUnavailable("EXTERNAL_ITEM_PREVIEW_POINTER_INVALID")
            request = job.request
            if (
                request.get("source_id") != query.source_id
                or request.get("source_revision_id") != query.source_revision_id
                or request.get("edition") != query.edition
                or request.get("source_file_id") != source.source_file_id
                or request.get("source_artifact_id") != source.artifact_id
                or request.get("source_artifact_revision_id") != source.artifact_revision_id
                or request.get("source_member_path") != source.member_path
                or request.get("source_sha256") != source.member.sha256
            ):
                raise ExternalItemPreviewUnavailable("EXTERNAL_ITEM_PREVIEW_SOURCE_STALE")
            raw_files = revision.manifest.get("files")
            files = (
                {
                    entry.get("file_name"): entry
                    for entry in raw_files
                    if isinstance(entry, dict) and isinstance(entry.get("file_name"), str)
                }
                if isinstance(raw_files, list)
                else {}
            )
            manifest_entry = files.get(_MANIFEST_MEMBER)
            pdf_entry = files.get(_PDF_MEMBER)
            if (
                not isinstance(raw_files, list)
                or len(raw_files) != 2
                or set(files) != {_MANIFEST_MEMBER, _PDF_MEMBER}
                or not isinstance(manifest_entry, dict)
                or not isinstance(pdf_entry, dict)
                or manifest_entry.get("sha256") != revision.content_hash
                or manifest_entry.get("bytes") != revision.content_bytes
                or manifest_entry.get("media_type") != "application/json"
                or manifest_entry.get("schema_ref") != EXTERNAL_ITEM_PREVIEW_MANIFEST_SCHEMA_REF
                or not isinstance(manifest_entry.get("bytes"), int)
                or not 1 <= manifest_entry["bytes"] <= _MANIFEST_MAX_BYTES
                or pdf_entry.get("media_type") != "application/pdf"
                or pdf_entry.get("schema_ref") != EXTERNAL_ITEM_PREVIEW_PDF_SCHEMA_REF
                or not isinstance(pdf_entry.get("bytes"), int)
                or not 8 <= pdf_entry["bytes"] <= _PDF_MAX_BYTES
            ):
                raise ExternalItemPreviewUnavailable("EXTERNAL_ITEM_PREVIEW_POINTER_INVALID")
            artifact_id = job.logical_artifact_id
            revision_id = job.revision_id
            manifest_sha = revision.content_hash
            pdf_sha = pdf_entry.get("sha256")
            pdf_bytes = pdf_entry["bytes"]
            result = revision.result
        try:
            manifest_bytes = self.artifacts.read_member(
                artifact_id=artifact_id,
                revision_id=revision_id,
                member_path=_MANIFEST_MEMBER,
                sha256=manifest_sha,
                media_type="application/json",
                schema_ref=EXTERNAL_ITEM_PREVIEW_MANIFEST_SCHEMA_REF,
                max_bytes=_MANIFEST_MAX_BYTES,
            )
            raw_manifest = json.loads(manifest_bytes)
            validate_contract(EXTERNAL_ITEM_PREVIEW_MANIFEST_SCHEMA, raw_manifest)
            manifest = ExternalItemPreviewManifest.model_validate(raw_manifest)
            if (
                manifest.source_id != query.source_id
                or manifest.source_revision_id != query.source_revision_id
                or manifest.edition != query.edition
                or manifest.source_file_id != source.source_file_id
                or manifest.source_artifact_id != source.artifact_id
                or manifest.source_artifact_revision_id != source.artifact_revision_id
                or manifest.source_member_path != source.member_path
                or manifest.source_sha256 != source.member.sha256
                or manifest.source_media_type != source.media_type
                or manifest.source_bytes != source.member.content_length
                or manifest.pdf_sha256 != pdf_sha
                or manifest.pdf_bytes != pdf_bytes
                or request.get("conversion") != manifest.conversion.model_dump(mode="json")
                or result.get("manifest_sha256") != manifest.manifest_sha256
                or result.get("pdf_sha256") != manifest.pdf_sha256
            ):
                raise ValueError("preview manifest differs from its exact source or PDF")
            member = self.artifacts.open_verified_member(
                artifact_id=artifact_id,
                revision_id=revision_id,
                member_path=_PDF_MEMBER,
                sha256=manifest.pdf_sha256,
                media_type="application/pdf",
                schema_ref=EXTERNAL_ITEM_PREVIEW_PDF_SCHEMA_REF,
                max_bytes=_PDF_MAX_BYTES,
            )
            if member.content_length != manifest.pdf_bytes:
                member.stream.close()
                raise ValueError("preview PDF size differs")
        except (OSError, ValueError, TypeError, JsonSchemaValidationError) as exc:
            raise ExternalItemPreviewUnavailable("EXTERNAL_ITEM_PREVIEW_POINTER_INVALID") from exc
        return ResolvedExternalItemPreview(
            member=member,
            manifest=manifest,
            artifact_id=artifact_id,
            artifact_revision_id=revision_id,
        )

    def build(self, query: ExternalItemDocumentMediaQuery) -> CatalogArtifact:
        source = self.source_media.open(query)
        source_format = "HWPX" if source.media_type.endswith("hwpx") else "HWP"
        try:
            converter = self.converter or SystemdOfficeDocumentConverter(self.settings.staging_root)
            workspace = converter.create_workspace()
            if (
                workspace.parent != self.settings.staging_root / CONVERSION_DIRECTORY
                or INSTANCE_PATTERN.fullmatch(workspace.name) is None
                or workspace.is_symlink()
            ):
                raise ValueError("external Item preview workspace is outside the fixed boundary")
        except Exception:
            source.member.stream.close()
            raise
        try:
            input_file = workspace / f"original.{source_format.casefold()}"
            _copy_verified_source(source, input_file)
            conversion = converter.convert(workspace, source_format=source_format)
            pdf = workspace / "converted/original.pdf"
            pdf_bytes = pdf.stat().st_size
            manifest_value: dict[str, object] = {
                "schema_version": "external-item-preview-manifest/1.0",
                "source_id": query.source_id,
                "source_revision_id": query.source_revision_id,
                "edition": query.edition,
                "source_file_id": source.source_file_id,
                "source_artifact_id": source.artifact_id,
                "source_artifact_revision_id": source.artifact_revision_id,
                "source_member_path": source.member_path,
                "source_schema_ref": "eom://schemas/content-intake/source-file/1.0",
                "source_sha256": source.member.sha256,
                "source_media_type": source.media_type,
                "source_bytes": source.member.content_length,
                "source_format": source_format,
                "pdf_member_path": _PDF_MEMBER,
                "pdf_sha256": conversion.review_pdf_sha256,
                "pdf_bytes": pdf_bytes,
                "conversion": conversion.model_dump(mode="json"),
            }
            manifest_value["manifest_sha256"] = content_sha256(manifest_value)
            validate_contract(EXTERNAL_ITEM_PREVIEW_MANIFEST_SCHEMA, manifest_value)
            manifest = ExternalItemPreviewManifest.model_validate(manifest_value)
            manifest_file = workspace / _MANIFEST_MEMBER
            manifest_file.write_bytes(canonical_json_bytes(manifest.model_dump(mode="json")))
            manifest_file.chmod(0o600)
            expected_hashes = {
                _MANIFEST_MEMBER: sha256_file(manifest_file),
                _PDF_MEMBER: conversion.review_pdf_sha256,
            }
            return self.artifacts.commit_file_set(
                files={_MANIFEST_MEMBER: manifest_file, _PDF_MEMBER: pdf},
                primary_file=_MANIFEST_MEMBER,
                artifact_type=_ARTIFACT_TYPE,
                idempotency_key=_idempotency_key(query),
                request={
                    "source_id": query.source_id,
                    "source_revision_id": query.source_revision_id,
                    "edition": query.edition,
                    "source_file_id": source.source_file_id,
                    "source_artifact_id": source.artifact_id,
                    "source_artifact_revision_id": source.artifact_revision_id,
                    "source_member_path": source.member_path,
                    "source_sha256": source.member.sha256,
                    "conversion": conversion.model_dump(mode="json"),
                },
                result={
                    "source_id": query.source_id,
                    "source_revision_id": query.source_revision_id,
                    "edition": query.edition,
                    "pdf_sha256": conversion.review_pdf_sha256,
                    "manifest_sha256": manifest.manifest_sha256,
                },
                file_metadata={
                    _MANIFEST_MEMBER: {
                        "media_type": "application/json",
                        "schema_ref": EXTERNAL_ITEM_PREVIEW_MANIFEST_SCHEMA_REF,
                    },
                    _PDF_MEMBER: {
                        "media_type": "application/pdf",
                        "schema_ref": EXTERNAL_ITEM_PREVIEW_PDF_SCHEMA_REF,
                    },
                },
                manifest_version="external-item-preview-file-set/1.0",
                expected_file_sha256=expected_hashes,
            )
        finally:
            shutil.rmtree(workspace)
