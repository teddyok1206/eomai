"""Preview projection reuses original Intake bytes only as a temporary input."""

from __future__ import annotations

import hashlib
import json
from contextlib import nullcontext
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.document_review import OfficeDocumentReviewConversionIdentity
from eom_catalog_contracts.external_item_media import ExternalItemDocumentMediaQuery
from eom_catalog_contracts.external_item_preview import ExternalItemPreviewManifest
from eom_catalog_service.artifacts import VerifiedArtifactMemberStream
from eom_catalog_service.external_item_document_media import (
    ExternalDocumentMediaType,
    ResolvedExternalItemDocumentMedia,
)
from eom_catalog_service.external_item_preview_projection import (
    ExternalItemPreviewProjectionService,
    ExternalItemPreviewUnavailable,
    _copy_verified_source,
)
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_file
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord


def _media(
    payload: bytes,
    *,
    media_type: ExternalDocumentMediaType = "application/vnd.hancom.hwp",
) -> ResolvedExternalItemDocumentMedia:
    return ResolvedExternalItemDocumentMedia(
        member=VerifiedArtifactMemberStream(
            stream=BytesIO(payload),
            content_length=len(payload),
            sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
        ),
        media_type=media_type,
        filename="문항_12345.hwp",
        source_file_id="sourcefile_" + "3" * 32,
        artifact_id="artifact_" + "4" * 32,
        artifact_revision_id="rev_" + "5" * 32,
        member_path="source/문항_12345.hwp",
    )


def test_copy_rejects_changed_verified_input(tmp_path: Path) -> None:
    source = _media(b"original source bytes")
    source = replace(
        source,
        member=VerifiedArtifactMemberStream(
            stream=BytesIO(b"changed source bytes"),
            content_length=source.member.content_length,
            sha256=source.member.sha256,
        ),
    )
    try:
        _copy_verified_source(source, tmp_path / "original.hwp")
    except ValueError as exc:
        assert "changed during materialization" in str(exc)
    else:
        raise AssertionError("changed source was accepted")
    assert source.member.stream.closed


def test_build_commits_only_derivative_pdf_and_pinned_manifest(tmp_path: Path) -> None:
    source = _media(
        b"PK\x03\x04" + b"source bytes",
        media_type="application/vnd.hancom.hwpx",
    )
    workspace = tmp_path / "office-conversion" / ("officeconv_" + "a" * 32)
    workspace.mkdir(parents=True)
    pdf_bytes = b"%PDF-1.7\npreview\n%%EOF"

    class FakeConverter:
        def create_workspace(self) -> Path:
            return workspace

        def convert(
            self, path: Path, *, source_format: str
        ) -> OfficeDocumentReviewConversionIdentity:
            assert path == workspace
            assert source_format == "HWPX"
            assert (path / "original.hwpx").read_bytes() == b"PK\x03\x04" + b"source bytes"
            output = path / "converted"
            output.mkdir()
            (output / "original.pdf").write_bytes(pdf_bytes)
            return OfficeDocumentReviewConversionIdentity(
                conversion_kind="LIBREOFFICE_H2ORESTART_PDF",
                review_pdf_sha256=sha256_file(output / "original.pdf"),
                libreoffice_version="LibreOffice 24.2",
                libreoffice_sha256="sha256:" + "8" * 64,
                h2orestart_sha256="sha256:" + "9" * 64,
            )

    def commit(**arguments):
        assert set(arguments["files"]) == {"preview-manifest.json", "preview/original.pdf"}
        assert all("original.hwpx" not in member for member in arguments["files"])
        manifest_raw = json.loads(arguments["files"]["preview-manifest.json"].read_bytes())
        manifest = ExternalItemPreviewManifest.model_validate(manifest_raw)
        assert manifest.source_member_path == "source/문항_12345.hwp"
        assert manifest.source_format == "HWPX"
        assert manifest.pdf_sha256 == sha256_file(arguments["files"]["preview/original.pdf"])
        assert arguments["expected_file_sha256"]["preview/original.pdf"] == manifest.pdf_sha256
        assert arguments["request"]["conversion"]["review_pdf_sha256"] == manifest.pdf_sha256
        return SimpleNamespace(artifact_id="artifact_" + "f" * 32)

    service = object.__new__(ExternalItemPreviewProjectionService)
    service.settings = CatalogSettings(staging_root=tmp_path)
    service.source_media = SimpleNamespace(open=Mock(return_value=source))
    service.converter = FakeConverter()
    service.artifacts = SimpleNamespace(commit_file_set=Mock(side_effect=commit))
    result = service.build(
        ExternalItemDocumentMediaQuery(
            source_id="extitem_" + "1" * 32,
            source_revision_id="extitemrev_" + "2" * 32,
            edition=3,
        )
    )
    assert result.artifact_id == "artifact_" + "f" * 32
    assert not workspace.exists()
    assert source.member.stream.closed
    service.artifacts.commit_file_set.assert_called_once()


def test_build_rejects_workspace_outside_converter_boundary(tmp_path: Path) -> None:
    source = _media(b"original source bytes")
    sentinel = tmp_path / "keep.txt"
    sentinel.write_text("keep")
    service = object.__new__(ExternalItemPreviewProjectionService)
    service.settings = CatalogSettings(staging_root=tmp_path)
    service.source_media = SimpleNamespace(open=Mock(return_value=source))
    service.converter = SimpleNamespace(create_workspace=lambda: tmp_path)
    service.artifacts = SimpleNamespace(commit_file_set=Mock())
    with pytest.raises(ValueError, match="outside the fixed boundary"):
        service.build(
            ExternalItemDocumentMediaQuery(
                source_id="extitem_" + "1" * 32,
                source_revision_id="extitemrev_" + "2" * 32,
                edition=3,
            )
        )
    assert sentinel.read_text() == "keep"
    assert source.member.stream.closed
    service.artifacts.commit_file_set.assert_not_called()


def test_open_reauthorizes_original_and_reads_only_exact_committed_pdf(tmp_path: Path) -> None:
    query = ExternalItemDocumentMediaQuery(
        source_id="extitem_" + "1" * 32,
        source_revision_id="extitemrev_" + "2" * 32,
        edition=3,
    )
    source = _media(b"original source bytes")
    pdf_bytes = b"%PDF-1.7\npreview\n%%EOF"
    pdf_sha = "sha256:" + hashlib.sha256(pdf_bytes).hexdigest()
    value: dict[str, object] = {
        "schema_version": "external-item-preview-manifest/1.0",
        "source_id": query.source_id,
        "source_revision_id": query.source_revision_id,
        "edition": 3,
        "source_file_id": source.source_file_id,
        "source_artifact_id": source.artifact_id,
        "source_artifact_revision_id": source.artifact_revision_id,
        "source_member_path": source.member_path,
        "source_schema_ref": "eom://schemas/content-intake/source-file/1.0",
        "source_sha256": source.member.sha256,
        "source_media_type": source.media_type,
        "source_bytes": source.member.content_length,
        "source_format": "HWP",
        "pdf_member_path": "preview/original.pdf",
        "pdf_sha256": pdf_sha,
        "pdf_bytes": len(pdf_bytes),
        "conversion": {
            "conversion_kind": "LIBREOFFICE_H2ORESTART_PDF",
            "review_pdf_sha256": pdf_sha,
            "libreoffice_version": "LibreOffice 24.2",
            "libreoffice_sha256": "sha256:" + "8" * 64,
            "h2orestart_sha256": "sha256:" + "9" * 64,
        },
    }
    value["manifest_sha256"] = content_sha256(value)
    manifest_bytes = canonical_json_bytes(value)
    manifest_sha = "sha256:" + hashlib.sha256(manifest_bytes).hexdigest()
    files = [
        {
            "file_name": "preview-manifest.json",
            "sha256": manifest_sha,
            "bytes": len(manifest_bytes),
            "media_type": "application/json",
            "schema_ref": "eom://schemas/external-item/preview-manifest/1.0",
        },
        {
            "file_name": "preview/original.pdf",
            "sha256": pdf_sha,
            "bytes": len(pdf_bytes),
            "media_type": "application/pdf",
            "schema_ref": "eom://schemas/external-item/preview-pdf/1.0",
        },
    ]
    artifact_id = "artifact_" + "f" * 32
    revision_id = "rev_" + "e" * 32
    job_id = "job_test"
    file_set = {
        "artifact_type": "external-item-preview-v1",
        "primary_file": "preview-manifest.json",
        "job_id": job_id,
        "logical_artifact_id": artifact_id,
        "revision_id": revision_id,
        "content_hash": manifest_sha,
        "files": files,
    }
    job = SimpleNamespace(
        job_id=job_id,
        status="SUCCEEDED",
        task_type="external-item-preview-v1",
        logical_artifact_id=artifact_id,
        revision_id=revision_id,
        request={
            "source_id": query.source_id,
            "source_revision_id": query.source_revision_id,
            "edition": 3,
            "source_file_id": source.source_file_id,
            "source_artifact_id": source.artifact_id,
            "source_artifact_revision_id": source.artifact_revision_id,
            "source_member_path": source.member_path,
            "source_sha256": source.member.sha256,
            "conversion": value["conversion"],
        },
    )
    logical = SimpleNamespace(
        approved=True,
        artifact_type="external-item-preview-v1",
        job_id=job_id,
    )
    revision = SimpleNamespace(
        approved=True,
        job_id=job_id,
        logical_artifact_id=artifact_id,
        manifest=file_set,
        manifest_hash=content_sha256(file_set),
        content_hash=manifest_sha,
        content_bytes=len(manifest_bytes),
        result={"manifest_sha256": value["manifest_sha256"], "pdf_sha256": pdf_sha},
    )

    def get_record(model, identity):
        if model is ArtifactRecord:
            return logical
        if model is ArtifactRevisionRecord:
            return revision
        return None

    session = SimpleNamespace(scalar=lambda statement: job, get=get_record)
    service = object.__new__(ExternalItemPreviewProjectionService)
    service.settings = CatalogSettings(staging_root=tmp_path)
    service.source_media = SimpleNamespace(open=Mock(return_value=source))
    service.sessions = lambda: nullcontext(session)
    service.artifacts = SimpleNamespace(
        read_member=Mock(return_value=manifest_bytes),
        open_verified_member=Mock(
            return_value=VerifiedArtifactMemberStream(
                stream=BytesIO(pdf_bytes), content_length=len(pdf_bytes), sha256=pdf_sha
            )
        ),
    )
    opened = service.open(query)
    assert opened.manifest.source_file_id == source.source_file_id
    assert opened.member.stream.read() == pdf_bytes
    assert source.member.stream.closed
    opened.member.stream.close()

    stale_source = _media(b"changed source bytes")
    service.source_media.open.return_value = stale_source
    with pytest.raises(ExternalItemPreviewUnavailable) as exc:
        service.open(query)
    assert exc.value.code == "EXTERNAL_ITEM_PREVIEW_SOURCE_STALE"
    assert stale_source.member.stream.closed
