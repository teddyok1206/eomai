"""Catalog-owned Office-to-PDF derivative for an already imported external Item."""

from __future__ import annotations

import hashlib
import os
import shutil
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
from sqlalchemy import Engine

from eom_catalog_service.artifacts import CatalogArtifact, CatalogArtifactService
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
                idempotency_key=(
                    f"external-item-preview-v1:{query.source_revision_id}:{query.edition}"
                ),
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
