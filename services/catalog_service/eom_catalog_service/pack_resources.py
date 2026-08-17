"""Resolve pinned files from an immutable Content Pack bundle revision."""

from __future__ import annotations

import zipfile
from pathlib import Path

from eom_content_pack import ContentPackError, ContentPackErrorCode
from eom_identifiers import sha256_bytes
from eom_orchestrator.models import ArtifactRevisionRecord
from sqlalchemy.orm import Session

from eom_catalog_service.models import ContentPackReleaseRecord


class PackResourceResolver:
    def read(
        self, session: Session, release: ContentPackReleaseRecord, relative_path: str
    ) -> bytes:
        revision = session.get(ArtifactRevisionRecord, release.bundle_artifact_revision_id)
        if (
            release.state not in {"RELEASED", "DEPRECATED"}
            or revision is None
            or not revision.approved
            or revision.logical_artifact_id != release.bundle_artifact_id
            or revision.content_hash != release.bundle_sha256
            or revision.manifest.get("manifest_version") != "catalog-file-set/1.0"
            or revision.manifest.get("artifact_type") != "content-pack-bundle"
        ):
            raise ContentPackError(
                ContentPackErrorCode.CONTENT_PACK_INVALID,
                "content pack bundle pointer does not resolve",
            )
        primary = revision.manifest.get("primary_file")
        if not isinstance(primary, str) or not primary.endswith(".eompack"):
            raise ContentPackError(
                ContentPackErrorCode.CONTENT_PACK_INVALID, "content pack primary file is invalid"
            )
        expected = {
            item["relative_path"]: item["sha256"]
            for item in release.canonical_manifest_json.get("files", [])
        }
        expected_hash = expected.get(relative_path)
        if expected_hash is None:
            raise ContentPackError(
                ContentPackErrorCode.CONTENT_PACK_REFERENCE_MISSING,
                "content pack resource is not in the manifest",
            )
        bundle = Path(revision.nas_path) / primary
        try:
            with zipfile.ZipFile(bundle) as archive:
                data = archive.read(relative_path)
        except (OSError, KeyError, zipfile.BadZipFile) as exc:
            raise ContentPackError(
                ContentPackErrorCode.CONTENT_PACK_REFERENCE_MISSING,
                "content pack resource cannot be read",
            ) from exc
        if sha256_bytes(data) != expected_hash:
            raise ContentPackError(
                ContentPackErrorCode.CONTENT_PACK_INVALID,
                "content pack resource hash mismatch",
            )
        return data
